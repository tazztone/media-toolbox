"""
Tests for media_toolbox.core.jobs: transactional staging, file safety, and cleanup.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path
import threading
from unittest.mock import MagicMock, patch

import pytest

from media_toolbox.core.jobs import (
    JobConfig,
    JobResult,
    publish_output,
    run_job,
    validate_job_paths,
)
from media_toolbox.core.models import (
    AudioStream,
    DestinationExistsError,
    EncodeOptions,
    FileCollisionError,
    FormatInfo,
    MediaInfo,
    OutputPublishError,
    ProbeError,
    VideoStream,
)
from media_toolbox.core.runner import RunnerCancelledError, RunnerError


@pytest.fixture
def dummy_media_info(tmp_path: Path) -> MediaInfo:
    fmt = FormatInfo(
        filename=str(tmp_path / "input.mp4"),
        format_name="mov,mp4,m4a,3gp,3g2,mj2",
        duration=10.0,
        size_bytes=1024,
    )
    v_stream = VideoStream(
        index=0,
        codec_name="h264",
        width=1920,
        height=1080,
        duration=10.0,
    )
    a_stream = AudioStream(
        index=1,
        codec_name="aac",
        channels=2,
        sample_rate=48000,
        duration=10.0,
    )
    return MediaInfo(
        format=fmt,
        video_streams=(v_stream,),
        audio_streams=(a_stream,),
    )


class TestPathSafety:
    def test_same_path_rejected(self, tmp_path: Path):
        inp = tmp_path / "video.mp4"
        inp.touch()
        with pytest.raises(FileCollisionError, match="same file"):
            validate_job_paths(inp, inp, overwrite=True)

    def test_symlink_collision_rejected(self, tmp_path: Path):
        inp = tmp_path / "video.mp4"
        inp.touch()
        link = tmp_path / "video_link.mp4"
        link.symlink_to(inp)
        with pytest.raises(FileCollisionError, match="same file"):
            validate_job_paths(inp, link, overwrite=True)

    def test_hardlink_collision_rejected(self, tmp_path: Path):
        inp = tmp_path / "video.mp4"
        inp.touch()
        hlink = tmp_path / "video_hard.mp4"
        os.link(inp, hlink)
        with pytest.raises(FileCollisionError, match="same underlying inode|same file"):
            validate_job_paths(inp, hlink, overwrite=True)

    def test_destination_exists_rejected_without_overwrite(self, tmp_path: Path):
        inp = tmp_path / "in.mp4"
        inp.touch()
        out = tmp_path / "out.mp4"
        out.touch()
        with pytest.raises(DestinationExistsError, match="already exists"):
            validate_job_paths(inp, out, overwrite=False)

    def test_broken_symlink_destination_rejected_without_overwrite(self, tmp_path: Path):
        inp = tmp_path / "in.mp4"
        inp.touch()
        out = tmp_path / "broken_link.mp4"
        out.symlink_to(tmp_path / "nonexistent.mp4")
        with pytest.raises(DestinationExistsError, match="already exists"):
            validate_job_paths(inp, out, overwrite=False)

    def test_destination_exists_allowed_with_overwrite(self, tmp_path: Path):
        inp = tmp_path / "in.mp4"
        inp.touch()
        out = tmp_path / "out.mp4"
        out.touch()
        in_p, out_p = validate_job_paths(inp, out, overwrite=True)
        assert in_p == inp.resolve()
        assert out_p == out.resolve()

    def test_missing_input_raises_filenotfound(self, tmp_path: Path):
        inp = tmp_path / "missing.mp4"
        out = tmp_path / "out.mp4"
        with pytest.raises(FileNotFoundError, match="not found"):
            validate_job_paths(inp, out)

    def test_output_symlink_rejected_even_with_overwrite(self, tmp_path: Path):
        inp = tmp_path / "in.mp4"
        inp.touch()
        target = tmp_path / "target.mp4"
        target.touch()
        symlink_out = tmp_path / "link.mp4"
        symlink_out.symlink_to(target)

        with pytest.raises(FileCollisionError, match="cannot be a symbolic link"):
            validate_job_paths(inp, symlink_out, overwrite=True)


class TestTransactionalJobExecution:
    @patch("media_toolbox.core.jobs.run_ffmpeg_pipeline")
    def test_successful_job_publishes_staging_file(
        self,
        mock_pipeline: MagicMock,
        tmp_path: Path,
        dummy_media_info: MediaInfo,
    ):
        inp = tmp_path / "input.mp4"
        inp.write_text("dummy input content")
        out = tmp_path / "output.mp4"

        # Simulate FFmpeg creating the staging output file
        def fake_ffmpeg(cmds, **_kwargs):
            # Target path is the last arg in the single-pass command
            staging_file = Path(cmds[0][-1])
            staging_file.write_bytes(b"dummy video data")

        mock_pipeline.side_effect = fake_ffmpeg

        config = JobConfig(
            input_path=inp,
            output_path=out,
            options=EncodeOptions(),
            media_info=dummy_media_info,
        )

        result = run_job(config)

        assert out.exists()
        assert out.read_bytes() == b"dummy video data"
        assert result.output_path == out.resolve()
        assert result.file_size_bytes == len(b"dummy video data")
        # Ensure no dangling temporary files in directory
        tmp_files = list(tmp_path.glob(".tmp_*"))
        assert len(tmp_files) == 0

    @patch("media_toolbox.core.jobs.run_ffmpeg_pipeline")
    def test_pre_cancelled_job_leaves_existing_destination_intact(
        self,
        _mock_pipeline: MagicMock,
        tmp_path: Path,
        dummy_media_info: MediaInfo,
    ):
        inp = tmp_path / "input.mp4"
        inp.write_bytes(b"source data")
        out = tmp_path / "output.mp4"
        out.write_bytes(b"pre-existing output")

        cancel_event = threading.Event()
        cancel_event.set()

        config = JobConfig(
            input_path=inp,
            output_path=out,
            options=EncodeOptions(),
            media_info=dummy_media_info,
            overwrite=True,
        )

        with pytest.raises(RunnerCancelledError):
            run_job(config, cancel_event=cancel_event)

        assert out.exists()
        assert out.read_bytes() == b"pre-existing output"
        assert inp.exists()
        assert inp.read_bytes() == b"source data"

    @patch("media_toolbox.core.jobs.run_ffmpeg_pipeline")
    def test_cancellation_during_execution_preserves_existing_output(
        self,
        mock_pipeline: MagicMock,
        tmp_path: Path,
        dummy_media_info: MediaInfo,
    ):
        inp = tmp_path / "input.mp4"
        inp.write_bytes(b"source data")
        out = tmp_path / "output.mp4"
        out.write_bytes(b"original output")

        def fake_cancellation(cmds, **_kwargs):
            staging_file = Path(cmds[0][-1])
            staging_file.write_bytes(b"partial bytes")
            raise RunnerCancelledError("cancelled")

        mock_pipeline.side_effect = fake_cancellation

        config = JobConfig(
            input_path=inp,
            output_path=out,
            options=EncodeOptions(),
            media_info=dummy_media_info,
            overwrite=True,
        )

        with pytest.raises(RunnerCancelledError):
            run_job(config)

        assert out.read_bytes() == b"original output"
        # Staging file was cleaned up
        assert len(list(tmp_path.glob(".tmp_*"))) == 0

    @patch("media_toolbox.core.jobs.run_ffmpeg_pipeline")
    def test_failure_cleans_staging_and_leaves_no_destination(
        self,
        mock_pipeline: MagicMock,
        tmp_path: Path,
        dummy_media_info: MediaInfo,
    ):
        inp = tmp_path / "input.mp4"
        inp.write_bytes(b"source")
        out = tmp_path / "new_output.mp4"

        def fake_failure(cmds, **_kwargs):
            staging_file = Path(cmds[0][-1])
            staging_file.write_bytes(b"partial corrupted data")
            raise RunnerError("ffmpeg crashed", returncode=1)

        mock_pipeline.side_effect = fake_failure

        config = JobConfig(
            input_path=inp,
            output_path=out,
            options=EncodeOptions(),
            media_info=dummy_media_info,
        )

        with pytest.raises(RunnerError):
            run_job(config)

        assert not out.exists()
        assert len(list(tmp_path.glob(".tmp_*"))) == 0

    def test_missing_staging_output_raises_publish_error(
        self,
        tmp_path: Path,
        dummy_media_info: MediaInfo,
    ):
        inp = tmp_path / "input.mp4"
        inp.write_bytes(b"source")
        out = tmp_path / "new_output.mp4"

        # Runner function runs and exits 0 but creates no output file
        def fake_silent_runner(_cmds, **_kwargs):
            pass

        config = JobConfig(
            input_path=inp,
            output_path=out,
            options=EncodeOptions(),
            media_info=dummy_media_info,
        )

        with pytest.raises(OutputPublishError, match="not produced"):
            run_job(config, runner=fake_silent_runner)

        assert not out.exists()

    def test_empty_staging_output_raises_publish_error(
        self,
        tmp_path: Path,
        dummy_media_info: MediaInfo,
    ):
        inp = tmp_path / "input.mp4"
        inp.write_bytes(b"source")
        out = tmp_path / "new_output.mp4"

        def fake_empty_runner(cmds, **_kwargs):
            staging_file = Path(cmds[0][-1])
            staging_file.touch()

        config = JobConfig(
            input_path=inp,
            output_path=out,
            options=EncodeOptions(),
            media_info=dummy_media_info,
        )

        with pytest.raises(OutputPublishError, match="empty"):
            run_job(config, runner=fake_empty_runner)

        assert not out.exists()

    def test_deterministic_race_destination_created_before_publication_preserved(
        self,
        tmp_path: Path,
        dummy_media_info: MediaInfo,
    ):
        inp = tmp_path / "input.mp4"
        inp.write_bytes(b"source")
        out = tmp_path / "race_output.mp4"

        def fake_racing_runner(cmds, **_kwargs):
            staging_file = Path(cmds[0][-1])
            staging_file.write_bytes(b"staged content")
            # Concurrently create destination right before publication
            out.write_bytes(b"interfering content")

        config = JobConfig(
            input_path=inp,
            output_path=out,
            options=EncodeOptions(),
            media_info=dummy_media_info,
            overwrite=False,
        )

        with pytest.raises(DestinationExistsError, match="already exists"):
            run_job(config, runner=fake_racing_runner)

        # Pre-existing destination content must remain untouched
        assert out.read_bytes() == b"interfering content"
        # Temporary staging directory must be cleaned up
        assert len(list(tmp_path.glob(".tmp_*"))) == 0

    def test_cancellation_right_before_publication_discards_staging(
        self,
        tmp_path: Path,
        dummy_media_info: MediaInfo,
    ):
        inp = tmp_path / "input.mp4"
        inp.write_bytes(b"source")
        out = tmp_path / "cancelled_output.mp4"
        cancel_evt = threading.Event()

        def fake_runner_cancelling_late(cmds, **_kwargs):
            staging_file = Path(cmds[0][-1])
            staging_file.write_bytes(b"complete staging file")
            # Cancellation requested right before runner returns
            cancel_evt.set()

        config = JobConfig(
            input_path=inp,
            output_path=out,
            options=EncodeOptions(),
            media_info=dummy_media_info,
        )

        with pytest.raises(RunnerCancelledError, match="cancelled before publication"):
            run_job(config, runner=fake_runner_cancelling_late, cancel_event=cancel_evt)

        assert not out.exists()
        assert len(list(tmp_path.glob(".tmp_*"))) == 0

    def test_publication_error_wrapped_and_chained(
        self,
        tmp_path: Path,
        dummy_media_info: MediaInfo,
    ):
        inp = tmp_path / "input.mp4"
        inp.write_bytes(b"source")
        out = tmp_path / "pub_error_output.mp4"

        def fake_runner(cmds, **_kwargs):
            staging_file = Path(cmds[0][-1])
            staging_file.write_bytes(b"staged content")

        config = JobConfig(
            input_path=inp,
            output_path=out,
            options=EncodeOptions(),
            media_info=dummy_media_info,
            overwrite=True,
        )

        with patch("os.replace", side_effect=OSError("Disk failure")):
            with pytest.raises(OutputPublishError) as exc_info:
                run_job(config, runner=fake_runner)
            assert exc_info.value.__cause__ is not None
            assert "Disk failure" in str(exc_info.value.__cause__)

    @patch("media_toolbox.core.jobs.probe_media")
    def test_probe_failure_raises_probe_error_not_name_error(
        self,
        mock_probe: MagicMock,
        tmp_path: Path,
    ):
        mock_probe.side_effect = ProbeError("Failed to parse probe JSON")
        inp = tmp_path / "corrupt.mp4"
        inp.write_bytes(b"bad content")
        out = tmp_path / "output.mp4"

        config = JobConfig(
            input_path=inp,
            output_path=out,
            options=EncodeOptions(),
            media_info=None,
            allow_unprobed=False,
        )

        with pytest.raises(ProbeError, match="Failed to parse probe JSON"):
            run_job(config)

    @patch("media_toolbox.core.jobs.probe_media")
    def test_probe_generic_exception_wrapped_in_probe_error(
        self,
        mock_probe: MagicMock,
        tmp_path: Path,
    ):
        mock_probe.side_effect = OSError("ffprobe executable not found")
        inp = tmp_path / "video.mp4"
        inp.write_bytes(b"content")
        out = tmp_path / "output.mp4"

        config = JobConfig(
            input_path=inp,
            output_path=out,
            options=EncodeOptions(),
            media_info=None,
            allow_unprobed=False,
        )

        with pytest.raises(ProbeError) as exc_info:
            run_job(config)
        assert "Failed to probe" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, OSError)

    @patch("media_toolbox.core.jobs.probe_media")
    def test_probe_failure_tolerated_when_allow_unprobed_is_true(
        self,
        mock_probe: MagicMock,
        tmp_path: Path,
    ):
        mock_probe.side_effect = ProbeError("ffprobe timeout")
        inp = tmp_path / "stream.mp4"
        inp.write_bytes(b"stream bytes")
        out = tmp_path / "stream_out.mp4"

        config = JobConfig(
            input_path=inp,
            output_path=out,
            options=EncodeOptions(),
            media_info=None,
            allow_unprobed=True,
        )

        def fake_runner(cmds, **_kwargs):
            staging_file = Path(cmds[0][-1])
            staging_file.write_bytes(b"staged stream")

        result = run_job(config, runner=fake_runner)
        assert result.output_path == out
        assert out.exists()

    def test_hardlink_unsupported_fails_closed_by_default(self, tmp_path: Path):
        staging = tmp_path / "stage.mp4"
        staging.write_bytes(b"content")
        out = tmp_path / "dest.mp4"
        err = OSError()
        err.errno = errno.EOPNOTSUPP
        with patch("os.link", side_effect=err):
            with pytest.raises(OutputPublishError, match="does not support atomic no-clobber"):
                publish_output(staging, out, overwrite=False, allow_non_atomic_fallback=False)

    def test_hardlink_unsupported_allowed_with_fallback_flag(self, tmp_path: Path):
        staging = tmp_path / "stage.mp4"
        staging.write_bytes(b"content")
        out = tmp_path / "dest.mp4"
        err = OSError()
        err.errno = errno.EOPNOTSUPP
        with patch("os.link", side_effect=err):
            publish_output(staging, out, overwrite=False, allow_non_atomic_fallback=True)
        assert out.exists()
        assert out.read_bytes() == b"content"

    @patch("media_toolbox.core.jobs.run_ffmpeg_pipeline")
    def test_run_job_fails_closed_when_hardlinks_unsupported(
        self,
        _mock_pipeline: MagicMock,
        tmp_path: Path,
        dummy_media_info: MediaInfo,
    ):
        inp = tmp_path / "in.mp4"
        inp.touch()
        out = tmp_path / "out.mp4"

        def fake_runner(cmds, **_kwargs):
            staging_file = Path(cmds[0][-1])
            staging_file.write_bytes(b"data")

        config = JobConfig(
            input_path=inp,
            output_path=out,
            options=EncodeOptions(),
            media_info=dummy_media_info,
            allow_non_atomic_fallback=False,
        )
        err = OSError()
        err.errno = errno.EXDEV
        with patch("os.link", side_effect=err):
            with pytest.raises(OutputPublishError, match="does not support atomic no-clobber"):
                run_job(config, runner=fake_runner)
