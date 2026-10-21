"""
Integration test suite verifying real FFmpeg and FFprobe execution on synthesized media.

Requires `ffmpeg` and `ffprobe` binaries on PATH; skips gracefully if missing.
"""

from __future__ import annotations

import concurrent.futures
import shutil
import subprocess
from pathlib import Path
import pytest

from media_toolbox.core.jobs import JobConfig, run_job
from media_toolbox.core.models import DestinationExistsError, EncodeOptions
from media_toolbox.core.presets import check_encoder_available
from media_toolbox.core.probe import probe_media


has_ffmpeg = bool(shutil.which("ffmpeg"))
has_ffprobe = bool(shutil.which("ffprobe"))
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not (has_ffmpeg and has_ffprobe), reason="ffmpeg and ffprobe required"),
]


@pytest.fixture
def synthetic_av_clip(tmp_path: Path) -> Path:
    """Generate a valid 3-second 640x360 test video with stereo sine wave audio."""
    clip_path = tmp_path / "synthetic_input.mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=3:size=640x360:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1000:duration=3",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-movflags",
        "+faststart",
        str(clip_path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return clip_path


def test_real_probe_media(synthetic_av_clip: Path) -> None:
    """Real ffprobe inspects synthesized clip and extracts accurate stream metadata."""
    info = probe_media(synthetic_av_clip)
    assert info.duration >= 2.9
    assert info.has_video is True
    assert info.has_audio is True

    pv = info.primary_video
    assert pv is not None
    assert pv.width == 640
    assert pv.height == 360
    assert pv.codec_name == "h264"
    assert round(pv.fps or 0) == 30

    pa = info.primary_audio
    assert pa is not None
    assert pa.codec_name == "aac"
    assert pa.channels in (1, 2)


def test_real_single_pass_transcode(synthetic_av_clip: Path, tmp_path: Path) -> None:
    """Real single-pass transcode scales resolution, adjusts speed, and produces valid output."""
    out_file = tmp_path / "transcoded_output.mp4"
    opts = EncodeOptions(
        preset="h264",
        crf=28,
        scale=(320, 180),
        speed=1.5,
        audio_bitrate_kbps=64,
    )
    config = JobConfig(input_path=synthetic_av_clip, output_path=out_file, options=opts)
    result = run_job(config)

    assert result.output_path == out_file
    assert result.file_size_bytes > 0
    assert out_file.is_file()
    assert out_file.stat().st_size > 0

    # Probe resulting transcode
    info = probe_media(out_file)
    assert info.has_video is True
    assert info.has_audio is True
    assert info.primary_video is not None
    assert info.primary_video.width == 320
    assert info.primary_video.height == 180
    # 3.0s input at 1.5x speed should be approximately 2.0s
    assert abs(info.duration - 2.0) < 0.5


def test_real_audio_extraction(synthetic_av_clip: Path, tmp_path: Path) -> None:
    """Real audio extraction isolates audio track into MP3 format without video."""
    out_file = tmp_path / "extracted_audio.mp3"
    opts = EncodeOptions(
        extract_audio=True,
        video_codec="mp3",
        audio_bitrate_kbps=96,
    )
    config = JobConfig(input_path=synthetic_av_clip, output_path=out_file, options=opts)
    result = run_job(config)

    assert result.output_path == out_file
    assert result.file_size_bytes > 0
    assert out_file.is_file()

    info = probe_media(out_file)
    assert info.has_video is False
    assert info.has_audio is True
    assert info.primary_audio is not None
    assert info.primary_audio.codec_name == "mp3"


def test_real_two_pass_target_size(synthetic_av_clip: Path, tmp_path: Path) -> None:
    """Real two-pass targeting stays within bounded tolerance of target size budget."""
    out_file = tmp_path / "sized_output.mp4"
    # Target size: 0.5 MB budget
    target_mb = 0.5
    opts = EncodeOptions(
        preset="h264",
        two_pass=True,
        target_size_mb=target_mb,
        audio_bitrate_kbps=64,
    )
    config = JobConfig(input_path=synthetic_av_clip, output_path=out_file, options=opts)
    result = run_job(config)

    assert result.output_path == out_file
    assert result.file_size_bytes > 0
    assert out_file.is_file()

    actual_mb = out_file.stat().st_size / 1_000_000.0
    # Allow 10% ceiling margin for short container overhead
    assert actual_mb <= target_mb * 1.10


def test_real_job_refuses_overwrite_without_flag(synthetic_av_clip: Path, tmp_path: Path) -> None:
    """Real job refuses to overwrite existing destination when overwrite=False."""
    existing_dest = tmp_path / "already_exists.mp4"
    existing_dest.write_text("pre-existing content", encoding="utf-8")
    original_mtime = existing_dest.stat().st_mtime_ns

    opts = EncodeOptions(preset="h264", crf=28)
    config = JobConfig(input_path=synthetic_av_clip, output_path=existing_dest, options=opts, overwrite=False)

    with pytest.raises(DestinationExistsError):
        run_job(config)

    # Destination was NOT modified or replaced
    assert existing_dest.read_text(encoding="utf-8") == "pre-existing content"
    assert existing_dest.stat().st_mtime_ns == original_mtime


def test_real_two_pass_h265_target_size(synthetic_av_clip: Path, tmp_path: Path) -> None:
    """Real H.265 two-pass transcode produces valid HEVC stream with isolated stats."""
    if not check_encoder_available("libx265"):
        pytest.skip("libx265 encoder not supported in installed ffmpeg")

    out_file = tmp_path / "h265_sized_output.mp4"
    target_mb = 0.5
    opts = EncodeOptions(
        preset="h265",
        two_pass=True,
        target_size_mb=target_mb,
        audio_bitrate_kbps=64,
    )
    config = JobConfig(input_path=synthetic_av_clip, output_path=out_file, options=opts)
    result = run_job(config)

    assert result.output_path == out_file
    assert result.file_size_bytes > 0
    assert out_file.is_file()

    info = probe_media(out_file)
    assert info.has_video is True
    assert info.primary_video is not None
    assert info.primary_video.codec_name == "hevc"

    # Confirm stats files were cleaned up and did not leak into output dir or cwd
    leaked_stats = list(tmp_path.glob("*pass*")) + list(Path(".").glob("x265_2pass*"))
    assert len(leaked_stats) == 0


def test_real_concurrent_two_pass_h265_isolation(synthetic_av_clip: Path, tmp_path: Path) -> None:
    """Concurrent H.265 two-pass jobs operate in private temporary directories without colliding."""
    if not check_encoder_available("libx265"):
        pytest.skip("libx265 encoder not supported in installed ffmpeg")

    out1 = tmp_path / "worker1_out.mp4"
    out2 = tmp_path / "worker2_out.mp4"

    cfg1 = JobConfig(
        input_path=synthetic_av_clip,
        output_path=out1,
        options=EncodeOptions(preset="h265", two_pass=True, target_size_mb=0.4, audio_bitrate_kbps=64),
    )
    cfg2 = JobConfig(
        input_path=synthetic_av_clip,
        output_path=out2,
        options=EncodeOptions(preset="h265", two_pass=True, target_size_mb=0.6, audio_bitrate_kbps=64),
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(run_job, cfg1)
        f2 = executor.submit(run_job, cfg2)
        res1 = f1.result(timeout=60)
        res2 = f2.result(timeout=60)

    assert res1.output_path == out1 and out1.is_file() and out1.stat().st_size > 0
    assert res2.output_path == out2 and out2.is_file() and out2.stat().st_size > 0

    info1 = probe_media(out1)
    info2 = probe_media(out2)
    assert info1.primary_video is not None
    assert info2.primary_video is not None
    assert info1.primary_video.codec_name == "hevc"
    assert info2.primary_video.codec_name == "hevc"


def test_real_check_encoder_available() -> None:
    """Verifies check_encoder_available detection against real host ffmpeg."""
    assert check_encoder_available("libx264") is True
    assert check_encoder_available("nonexistent_codec_12345") is False


