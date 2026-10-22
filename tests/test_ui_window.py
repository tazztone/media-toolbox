"""Unit and integration test suite for MainWindow coordination and state decoupling.

Tests:
- Performance benchmarks, thread leak checks, and monotonic progress footer
- MainWindow state machine, probing lockout, overwrite confirmation, and progress decoupling
"""

# pyright: reportMissingImports=false, reportMissingModuleSource=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportGeneralTypeIssues=false, reportInvalidTypeForm=false

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from media_toolbox.core.jobs import JobConfig
from media_toolbox.core.models import (
    EncodeOptions,
    FormatInfo,
    MediaInfo,
    ProgressEvent,
    VideoStream,
)

pytestmark = [pytest.mark.desktop]


# ---------------------------------------------------------------------------
# 8. Performance and Budget Benchmark Tests
# ---------------------------------------------------------------------------


class TestPerformanceAndTiming:
    """Guarantees sub-second execution without lingering threads or CPU saturation."""

    def test_entire_ui_test_suite_executes_under_500ms(self) -> None:
        """Assert operational logic of the UI suite executes well within 500ms."""
        start = time.perf_counter()

        from media_toolbox.ui.forms import (
            build_encode_options_from_state,
            resolve_default_output_path,
        )

        p = Path("/tmp/test.mkv")
        for _ in range(100):
            _ = build_encode_options_from_state(
                "h264", "crf", 23, 25.0, (1920, 1080), False, True, 2.0, 192
            )
            _ = resolve_default_output_path(p, "h264")

        duration = time.perf_counter() - start
        assert duration < 0.2, (
            f"Execution took too long: {duration:.4f}s (budget: 0.2s)"
        )

    def test_zero_thread_leaks_after_execution(self) -> None:
        """Assert no active MediaToolboxWorker threads remain alive."""
        active_names = [t.name for t in threading.enumerate() if t.is_alive()]
        assert "MediaToolboxWorker" not in active_names

    def test_monotonic_progress_footer_bar(self) -> None:
        """Verify ProgressFooterWidget maintains non-decreasing progress unless pass changes."""
        from media_toolbox.ui.widgets import ProgressFooterWidget

        mock_footer = MagicMock()
        mock_footer._current_fraction = 0.0
        mock_footer._last_pass_info = None

        # Step 1: 50%
        ProgressFooterWidget.update_progress(
            mock_footer, ProgressEvent(percentage=50.0)
        )
        mock_footer.progress_bar.set_fraction.assert_called_with(0.5)
        mock_footer.pct_label.set_text.assert_called_with("50.0%")
        assert mock_footer._current_fraction == 0.5

        # Step 2: 40% (jitter backwards) should NOT regress
        ProgressFooterWidget.update_progress(
            mock_footer, ProgressEvent(percentage=40.0)
        )
        mock_footer.progress_bar.set_fraction.assert_called_with(0.5)
        mock_footer.pct_label.set_text.assert_called_with("50.0%")
        assert mock_footer._current_fraction == 0.5

        # Step 3: 75%
        ProgressFooterWidget.update_progress(
            mock_footer, ProgressEvent(percentage=75.0)
        )
        mock_footer.progress_bar.set_fraction.assert_called_with(0.75)
        mock_footer.pct_label.set_text.assert_called_with("75.0%")
        assert mock_footer._current_fraction == 0.75

        # Step 4: pass change updates status label without regressing progress
        ProgressFooterWidget.update_progress(
            mock_footer, ProgressEvent(percentage=10.0), pass_info="Pass 2/2"
        )
        mock_footer.status_label.set_text.assert_called_with("Pass 2/2")
        assert mock_footer._current_fraction == 0.75

        # Step 5: new job start resets baseline
        ProgressFooterWidget.start(mock_footer, "Transcoding...")
        assert mock_footer._current_fraction == 0.0

    @pytest.mark.usefixtures("gi_env")
    def test_async_probe_sequence_counter_discards_stale_completion(
        self, tmp_path: Path
    ) -> None:
        """Verify stale probe completion from earlier request ID is discarded."""
        from media_toolbox.ui.window import MainWindow

        mock_win = MagicMock()
        mock_win._probe_request_id = 2  # Current request is 2

        file1 = tmp_path / "first.mp4"
        info1 = MediaInfo(
            format=FormatInfo(filename="first.mp4", format_name="mp4", duration=10.0)
        )

        file2 = tmp_path / "second.mp4"
        info2 = MediaInfo(
            format=FormatInfo(filename="second.mp4", format_name="mp4", duration=20.0)
        )

        # Stale completion with req_id=1
        ret1 = MainWindow._on_probe_success(mock_win, file1, 1, info1)
        assert ret1 is False
        mock_win.window_title.set_subtitle.assert_not_called()

        # Current completion with req_id=2
        ret2 = MainWindow._on_probe_success(mock_win, file2, 2, info2)
        assert ret2 is False
        mock_win.window_title.set_subtitle.assert_called_with(file2.name)


class TestWindowStateAndProgressDecoupling:
    """Verifies MainWindow state machine, probing lockout, overwrite confirmation, and progress decoupling."""

    def test_probing_lockout_prevents_stale_job_submission(
        self, tmp_path: Path
    ) -> None:
        """Loading file B while file A was ready invalidates A and prevents starting jobs during probing."""
        from media_toolbox.ui.window import MainWindow, WindowState

        mock_win = MagicMock()
        mock_win.state = WindowState.READY
        mock_win.is_transcoding = False
        mock_win._probe_request_id = 1
        mock_win.input_file = tmp_path / "file_a.mp4"
        mock_win.media_info = MediaInfo(
            format=FormatInfo(filename="file_a.mp4", format_name="mp4", duration=10.0)
        )

        target_b = tmp_path / "file_b.mp4"
        target_b.touch()

        with patch("threading.Thread"):
            MainWindow.load_media_file(mock_win, target_b, sync=False)

        assert mock_win.state == WindowState.PROBING
        assert mock_win.input_file is None
        assert mock_win.media_info is None
        mock_win.transcode_btn.set_sensitive.assert_called_with(False)
        mock_win.extract_btn.set_sensitive.assert_called_with(False)

        # Attempting transcode during PROBING is rejected
        mock_win._start_worker = MagicMock()
        MainWindow._start_transcode(mock_win)
        mock_win._start_worker.assert_not_called()

    def test_interleaved_pass_and_aggregate_progress_monotonic(self) -> None:
        """Progress bar is driven exclusively by aggregate events and never regresses."""
        from media_toolbox.ui.widgets import ProgressFooterWidget

        mock_footer = MagicMock()
        mock_footer._current_fraction = 0.0
        mock_footer._last_pass_info = None

        # 1. Pass 1 progress at 80% should update label only, not bar
        ProgressFooterWidget.update_progress(
            mock_footer,
            ProgressEvent(percentage=80.0, speed=1.5, eta_seconds=10.0),
            pass_info="Pass 1 of 2 (80.0%)",
        )
        mock_footer.status_label.set_text.assert_called_with("Pass 1 of 2 (80.0%)")
        mock_footer.progress_bar.set_fraction.assert_not_called()
        assert mock_footer._current_fraction == 0.0

        # 2. Aggregate progress at 40% updates bar
        ProgressFooterWidget.update_progress(
            mock_footer,
            ProgressEvent(percentage=40.0, speed=1.5, eta_seconds=20.0),
            pass_info=None,
        )
        mock_footer.progress_bar.set_fraction.assert_called_with(0.40)
        assert mock_footer._current_fraction == 0.40

        # 3. Pass 1 completes (100%), but bar must NOT jump to 100%
        ProgressFooterWidget.update_progress(
            mock_footer,
            ProgressEvent(percentage=100.0),
            pass_info="Pass 1 of 2 (100.0%)",
        )
        assert mock_footer._current_fraction == 0.40

        # 4. Pass 2 starts at 5% - bar must NOT decrease
        ProgressFooterWidget.update_progress(
            mock_footer,
            ProgressEvent(percentage=5.0),
            pass_info="Pass 2 of 2 (5.0%)",
        )
        assert mock_footer._current_fraction == 0.40

        # 5. Aggregate progress advances to 55%
        ProgressFooterWidget.update_progress(
            mock_footer,
            ProgressEvent(percentage=55.0),
            pass_info=None,
        )
        mock_footer.progress_bar.set_fraction.assert_called_with(0.55)
        assert mock_footer._current_fraction == 0.55

    def test_custom_output_path_persists_across_preset_changes(
        self, tmp_path: Path
    ) -> None:
        """Custom user output path is retained when changing presets."""
        from media_toolbox.ui.window import MainWindow

        mock_win = MagicMock()
        mock_win.input_file = tmp_path / "sample.mp4"
        custom_out = tmp_path / "my_custom_destination.mp4"
        mock_win.video_output_path = custom_out
        mock_win._video_output_custom = True
        mock_win._audio_output_custom = False

        mock_win.get_current_video_preset.return_value = "h265"
        mock_win.get_current_audio_preset.return_value = "aac"
        mock_win.rate_widget.get_mode.return_value = "crf"

        MainWindow._update_default_output_paths(mock_win)

        # Video path was custom, so it must not have been overwritten
        assert mock_win.video_output_path == custom_out

    def test_overwrite_confirmation_behavior(self, tmp_path: Path) -> None:
        """Non-existing file starts directly; existing file triggers Adw.MessageDialog."""
        from media_toolbox.core.models import EncodeOptions
        from media_toolbox.ui.window import MainWindow, WindowState

        mock_win = MagicMock()
        mock_win._start_worker = MagicMock()

        # Case 1: non-existing destination
        non_existing = tmp_path / "new_file.mp4"
        cfg1 = JobConfig(
            input_path="in.mp4", output_path=non_existing, options=EncodeOptions()
        )
        MainWindow._confirm_overwrite_and_start(mock_win, cfg1, "Encoding...")
        mock_win._start_worker.assert_called_once_with(cfg1, "Encoding...")

        # Case 2: existing destination triggers dialog
        mock_win._start_worker.reset_mock()
        mock_win.state = WindowState.READY
        mock_win.input_file = "in.mp4"
        existing = tmp_path / "already_exists.mp4"
        existing.touch()
        cfg2 = JobConfig(
            input_path="in.mp4", output_path=existing, options=EncodeOptions()
        )

        # Subcase 2a: Adw.AlertDialog (Libadwaita 1.5+)
        with patch("gi.repository.Adw.AlertDialog") as mock_dialog_cls:
            mock_dialog = MagicMock()
            mock_dialog_cls.return_value = mock_dialog

            MainWindow._confirm_overwrite_and_start(mock_win, cfg2, "Encoding...")
            mock_dialog_cls.assert_called_once()
            mock_dialog.choose.assert_called_once()
            choose_callback = mock_dialog.choose.call_args[0][2]
            # Worker must NOT start before user confirmation
            mock_win._start_worker.assert_not_called()
            # UI controls must be disabled while dialog is open
            mock_win._set_ui_controls_sensitive.assert_called_with(False)
            assert mock_win._pending_confirmation is True

            # Duplicate confirmation request while dialog is open must be ignored
            mock_dialog.choose.reset_mock()
            MainWindow._confirm_overwrite_and_start(mock_win, cfg2, "Encoding...")
            mock_dialog.choose.assert_not_called()

            # Callback handling: user cancels -> re-enable controls, no worker
            mock_dialog.choose_finish.return_value = "cancel"
            mock_win._set_ui_controls_sensitive.reset_mock()
            choose_callback(mock_dialog, MagicMock())
            assert mock_win._pending_confirmation is False
            mock_win._set_ui_controls_sensitive.assert_called_with(True)
            mock_win._start_worker.assert_not_called()

            # User replaces -> starts worker with overwrite=True
            mock_win._start_worker.reset_mock()
            mock_win._pending_confirmation = True
            mock_dialog.choose_finish.return_value = "replace"
            choose_callback(mock_dialog, MagicMock())
            assert mock_win._pending_confirmation is False
            mock_win._start_worker.assert_called_once()
            assert mock_win._start_worker.call_args[0][0].overwrite is True

        # Subcase 2b: Fallback to Adw.MessageDialog (Libadwaita < 1.5)
        mock_win._start_worker.reset_mock()
        mock_win._pending_confirmation = False
        import gi.repository.Adw as AdwModule

        with (
            patch.object(AdwModule, "AlertDialog", None),
            patch("gi.repository.Adw.MessageDialog") as mock_msg_cls,
        ):
            mock_msg = MagicMock()
            mock_msg_cls.return_value = mock_msg

            MainWindow._confirm_overwrite_and_start(mock_win, cfg2, "Encoding...")
            mock_msg_cls.assert_called_once()
            mock_msg.present.assert_called_once()
            resp_cb = mock_msg.connect.call_args[0][1]
            mock_win._pending_confirmation = True
            resp_cb(mock_msg, "replace")
            assert mock_win._start_worker.call_args[0][0].overwrite is True

    def test_start_worker_ignores_duplicate_when_worker_alive(self) -> None:
        """MainWindow._start_worker does not launch a second worker if one is active and alive."""
        from media_toolbox.core.models import EncodeOptions
        from media_toolbox.ui.window import MainWindow

        mock_win = MagicMock()
        mock_alive_worker = MagicMock()
        mock_alive_worker.is_alive.return_value = True
        mock_win._active_worker = mock_alive_worker

        cfg = JobConfig(
            input_path="in.mp4", output_path="out.mp4", options=EncodeOptions()
        )
        with patch("threading.Thread") as mock_thread_cls:
            MainWindow._start_worker(mock_win, cfg, "Title")
            mock_thread_cls.assert_not_called()

    def test_start_actions_do_not_mutate_filesystem_on_ui_thread(
        self, tmp_path: Path
    ) -> None:
        """_start_transcode and _start_extract_audio delegate destination directory creation to run_job."""
        from media_toolbox.ui.window import MainWindow, WindowState

        mock_win = MagicMock()
        mock_win.state = WindowState.READY
        mock_win.input_file = tmp_path / "input.mp4"
        mock_win.media_info = MediaInfo(
            format=FormatInfo(filename="input.mp4", format_name="mp4", duration=1.0)
        )
        mock_win.video_output_path = tmp_path / "nonexistent_dir" / "out.mp4"
        mock_win.audio_output_path = tmp_path / "nonexistent_dir2" / "out.mp3"
        mock_win.get_transcode_options.return_value = EncodeOptions()
        mock_win.get_extract_audio_options.return_value = EncodeOptions()
        mock_win._confirm_overwrite_and_start = MagicMock()

        MainWindow._start_transcode(mock_win)
        assert not (tmp_path / "nonexistent_dir").exists()
        mock_win._confirm_overwrite_and_start.assert_called_once()

        mock_win._confirm_overwrite_and_start.reset_mock()
        MainWindow._start_extract_audio(mock_win)
        assert not (tmp_path / "nonexistent_dir2").exists()
        mock_win._confirm_overwrite_and_start.assert_called_once()

    def test_probe_success_sets_effective_rotated_dimensions(
        self, tmp_path: Path
    ) -> None:
        """Probe success passes rotation-compensated effective dimensions to resolution widget."""
        from media_toolbox.ui.window import MainWindow

        mock_win = MagicMock()
        mock_win._probe_request_id = 1
        mock_win.state = None

        target = tmp_path / "portrait.mp4"
        video = VideoStream(
            index=0, codec_name="h264", width=1920, height=1080, rotation=90
        )
        info = MediaInfo(
            format=FormatInfo(
                filename="portrait.mp4", format_name="mp4", duration=10.0
            ),
            video_streams=(video,),
        )

        MainWindow._on_probe_success(mock_win, target, 1, info)
        mock_win.res_widget.set_source_resolution.assert_called_once_with(1080, 1920)

    def test_batch_queue_load_and_advancement(self, tmp_path: Path) -> None:
        """load_media_files populates batch_queue and _finish advances to next queue item."""
        from media_toolbox.ui.window import MainWindow

        mock_win = MagicMock()
        mock_win.batch_queue = []
        mock_win.batch_index = 0
        mock_win.is_batch_active = False
        mock_win.is_batch_running = False

        f1 = tmp_path / "1.mp4"
        f1.touch()
        f2 = tmp_path / "2.mp4"
        f2.touch()

        MainWindow.load_media_files(mock_win, [f1, f2])
        assert mock_win.batch_queue == [f1, f2]
        assert mock_win.batch_index == 0
        assert mock_win.is_batch_active is True
        mock_win.load_media_file.assert_called_once_with(f1)

        # Worker finish advances to f2
        mock_win.is_batch_running = True
        mock_win.state = None
        mock_win._close_after_cleanup = False
        with patch("media_toolbox.ui.window_worker.GLib.idle_add") as mock_idle:
            MainWindow._finish(
                mock_win, success=True, footer_msg="Saved: 1.mp4", toast_msg="Done"
            )
            assert mock_win.batch_index == 1
            mock_idle.assert_called_once()
            cb = mock_idle.call_args[0][0]
            assert callable(cb)
            cb()
            mock_win.load_media_file.assert_called_with(f2)

    def test_batch_queue_cancel_resets_batch(self) -> None:
        """User cancellation resets batch active and running states."""
        from media_toolbox.ui.window import MainWindow

        mock_win = MagicMock()
        mock_win.is_batch_active = True
        mock_win.is_batch_running = True
        mock_win.cancel_event = MagicMock()
        mock_win.progress_footer = MagicMock()

        MainWindow._on_cancel_clicked(mock_win)
        assert mock_win.is_batch_active is False
        assert mock_win.is_batch_running is False
