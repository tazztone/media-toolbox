"""Unit and worker lifecycle test suite for background transcoding and cancellation.

Tests:
- Non-blocking background worker thread and GLib.idle_add event loop marshalling
- Cancellation flow, process group termination, and partial file cleanup
"""

# pyright: reportMissingImports=false, reportMissingModuleSource=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportGeneralTypeIssues=false, reportInvalidTypeForm=false

from __future__ import annotations

from pathlib import Path
import threading
from unittest.mock import MagicMock, patch
import pytest

from media_toolbox.core.jobs import JobConfig
from media_toolbox.core.models import EncodeOptions, ProgressEvent
from media_toolbox.core.runner import RunnerCancelledError, RunnerError
from tests.ui_test_helpers import (
    drain_main_context,
    gi_env,
    isolate_gi_sys_modules,
    iterate_main_context,
)

pytestmark = [pytest.mark.desktop]


# ---------------------------------------------------------------------------
# 6. Non-Blocking Worker Thread & GLib.idle_add Tests
# ---------------------------------------------------------------------------


class TestNonBlockingWorkerThread:
    """Verifies daemon worker thread execution and GLib.idle_add main loop marshalling using genuine production methods."""

    def test_worker_thread_spawns_daemon(self, tmp_path: Path) -> None:
        """Verify MainWindow._launch_worker_pipeline spawns a daemon thread with correct name and target."""
        from media_toolbox.ui.window import MainWindow

        mock_win = MagicMock()
        mock_win.progress_footer = MagicMock()
        mock_win._set_ui_controls_sensitive = MagicMock()
        mock_win._worker_thread_entry = MagicMock()

        out_file = tmp_path / "output.mp4"
        config = JobConfig(input_path="in.mp4", output_path=str(out_file), options=EncodeOptions())

        with patch("threading.Thread") as mock_thread_cls:
            mock_thread_inst = MagicMock()
            mock_thread_cls.return_value = mock_thread_inst

            MainWindow._launch_worker_pipeline(mock_win, config, "Encoding...")

            assert mock_win.is_transcoding is True
            assert isinstance(mock_win.cancel_event, threading.Event)
            assert not mock_win.cancel_event.is_set()
            mock_win._set_ui_controls_sensitive.assert_called_with(False)
            mock_win.progress_footer.start.assert_called_with("Encoding...")

            mock_thread_cls.assert_called_once_with(
                target=mock_win._worker_thread_entry,
                args=(config, mock_win.cancel_event),
                daemon=True,
                name="MediaToolboxWorker",
            )
            mock_thread_inst.start.assert_called_once()

    def test_worker_dispatches_progress_via_glib_idle_add(self, gi_env) -> None:
        """Verify ProgressEvents update UI via MainWindow._on_progress_idle and ProgressFooterWidget.update_progress."""
        _, _, _, _, _, GLib = gi_env
        from media_toolbox.ui.window import MainWindow
        from media_toolbox.ui.widgets import ProgressFooterWidget

        mock_win = MagicMock()
        evt = ProgressEvent(frame=150, fps=30.0, out_time_seconds=5.0, percentage=50.0, speed=2.0, eta_seconds=5.0, total_size_bytes=1048576)

        # 1. Verify MainWindow._on_progress_idle dispatch
        GLib.idle_add(MainWindow._on_progress_idle, mock_win, evt)

        ctx = GLib.MainContext.default()
        drain_main_context(ctx)

        mock_win.progress_footer.update_progress.assert_called_once_with(evt)

        # 2. Verify ProgressFooterWidget.update_progress widget formatting
        mock_footer = MagicMock()
        ProgressFooterWidget.update_progress(mock_footer, evt)
        mock_footer.progress_bar.set_fraction.assert_called_with(0.5)
        mock_footer.pct_label.set_text.assert_called_with("50.0%")
        mock_footer.speed_label.set_text.assert_called_with("Speed: 2.00x")
        mock_footer.eta_label.set_text.assert_called_with("ETA: 00:05")
        mock_footer.size_label.set_text.assert_called_with("Size: 1.00 MiB (1,048,576 bytes)")

    def test_worker_dispatches_pipeline_progress_idle(self, gi_env) -> None:
        """Verify multi-pass progress events dispatch to MainWindow._on_pass_progress_idle with pass_info formatted."""
        _, _, _, _, _, GLib = gi_env
        from media_toolbox.ui.window import MainWindow

        mock_win = MagicMock()
        evt = ProgressEvent(frame=300, fps=30.0, out_time_seconds=10.0, percentage=75.5)

        # Multi-pass: pass 1 of 2
        GLib.idle_add(MainWindow._on_pass_progress_idle, mock_win, 1, 2, evt)

        ctx = GLib.MainContext.default()
        drain_main_context(ctx)

        mock_win.progress_footer.update_progress.assert_called_once_with(
            evt, pass_info="Pass 1 of 2 (75.5%)"
        )

        # Single pass: pass_info is None
        mock_win.reset_mock()
        GLib.idle_add(MainWindow._on_pass_progress_idle, mock_win, 1, 1, evt)
        drain_main_context(ctx)

        mock_win.progress_footer.update_progress.assert_called_once_with(
            evt, pass_info=None
        )

    def test_worker_idle_handlers_return_source_remove(self, gi_env, tmp_path: Path) -> None:
        """Verify all MainWindow idle handlers return GLib.SOURCE_REMOVE (False) and do not repeat."""
        _, _, _, _, _, GLib = gi_env
        from media_toolbox.ui.window import MainWindow

        mock_win = MagicMock()
        evt = ProgressEvent(frame=100, fps=25.0, out_time_seconds=4.0, percentage=40.0)
        fake_path = tmp_path / "out.mp4"

        # Direct return value check
        assert MainWindow._on_progress_idle(mock_win, evt) == GLib.SOURCE_REMOVE
        assert MainWindow._on_pass_progress_idle(mock_win, 1, 2, evt) == GLib.SOURCE_REMOVE
        assert MainWindow._on_success_idle(mock_win, fake_path) == GLib.SOURCE_REMOVE
        assert MainWindow._on_cancelled_idle(mock_win, fake_path) == GLib.SOURCE_REMOVE
        assert MainWindow._on_error_idle(mock_win, "error message") == GLib.SOURCE_REMOVE

        # Verify handlers execute exactly once in GLib main context without infinite loop
        mock_win.reset_mock()
        GLib.idle_add(MainWindow._on_progress_idle, mock_win, evt)
        ctx = GLib.MainContext.default()
        assert ctx.pending()
        iterate_main_context(ctx)
        assert not ctx.pending()
        assert mock_win.progress_footer.update_progress.call_count == 1

    def test_worker_success_completion_handling(self, gi_env, tmp_path: Path) -> None:
        """Verify successful transcode schedules success handler and restores UI controls."""
        _, _, _, _, _, GLib = gi_env
        from media_toolbox.ui.window import MainWindow
        from media_toolbox.ui.widgets import ProgressFooterWidget

        mock_win = MagicMock()
        mock_win.is_transcoding = True
        out_file = tmp_path / "done.mp4"

        GLib.idle_add(MainWindow._on_success_idle, mock_win, out_file)

        ctx = GLib.MainContext.default()
        drain_main_context(ctx)

        assert mock_win.is_transcoding is False
        mock_win._set_ui_controls_sensitive.assert_called_with(True)
        mock_win.progress_footer.finish.assert_called_with(True, "Saved: done.mp4")
        mock_win.toast_overlay.add_toast.assert_called_once()

        # Verify ProgressFooterWidget.finish on success
        mock_footer = MagicMock()
        ProgressFooterWidget.finish(mock_footer, True, "Saved: done.mp4")
        mock_footer.cancel_button.set_sensitive.assert_called_with(False)
        mock_footer.progress_bar.set_fraction.assert_called_with(1.0)
        mock_footer.pct_label.set_text.assert_called_with("100.0%")
        mock_footer.status_label.set_text.assert_called_with("Saved: done.mp4")

    def test_worker_error_marshalled_to_ui(self, gi_env) -> None:
        """Verify runner error message is marshalled back to main thread and displayed."""
        _, _, _, _, _, GLib = gi_env
        from media_toolbox.ui.window import MainWindow
        from media_toolbox.ui.widgets import ProgressFooterWidget

        mock_win = MagicMock()
        mock_win.is_transcoding = True
        err = RunnerError("FFmpeg error", returncode=1, stderr="Invalid codec parameters")

        GLib.idle_add(MainWindow._on_error_idle, mock_win, err.last_error_line)

        ctx = GLib.MainContext.default()
        drain_main_context(ctx)

        assert mock_win.is_transcoding is False
        mock_win._set_ui_controls_sensitive.assert_called_with(True)
        mock_win.progress_footer.finish.assert_called_with(False, "Failed: Invalid codec parameters")
        mock_win.toast_overlay.add_toast.assert_called_once()

        # Verify ProgressFooterWidget.finish on failure
        mock_footer = MagicMock()
        ProgressFooterWidget.finish(mock_footer, False, "Failed: Invalid codec parameters")
        mock_footer.cancel_button.set_sensitive.assert_called_with(False)
        mock_footer.status_label.set_text.assert_called_with("Failed: Invalid codec parameters")

    @pytest.mark.usefixtures("gi_env")
    def test_worker_start_disables_open_btn(self, tmp_path: Path) -> None:
        """Verify _start_worker marks is_transcoding and disables open_btn."""
        from media_toolbox.ui.window import MainWindow

        mock_win = MagicMock()
        mock_win.is_transcoding = False
        out_file = tmp_path / "out.mp4"
        config = JobConfig(input_path="in.mp4", output_path=str(out_file), options=EncodeOptions())

        with patch("threading.Thread") as mock_thread_cls:
            MainWindow._start_worker(mock_win, config, "Transcoding...")

        assert mock_win.is_transcoding is True
        mock_win._set_ui_controls_sensitive.assert_called_with(False)
        mock_win.open_btn.set_sensitive.assert_called_with(False)
        mock_win.progress_footer.start.assert_called_with("Transcoding...")
        mock_thread_cls.assert_called_once()

    @pytest.mark.usefixtures("gi_env")
    def test_worker_success_completion_restores_open_btn(self, tmp_path: Path) -> None:
        """Verify _on_success_idle marks is_transcoding=False and enables open_btn."""
        from media_toolbox.ui.window import MainWindow

        mock_win = MagicMock()
        mock_win.is_transcoding = True
        out_file = tmp_path / "done.mp4"

        ret = MainWindow._on_success_idle(mock_win, out_file)

        assert ret is False  # GLib.SOURCE_REMOVE
        assert mock_win.is_transcoding is False
        mock_win._set_ui_controls_sensitive.assert_called_with(True)
        mock_win.open_btn.set_sensitive.assert_called_with(True)
        mock_win.progress_footer.finish.assert_called_with(True, f"Saved: {out_file.name}")

    @pytest.mark.usefixtures("gi_env")
    def test_worker_cancelled_completion_restores_open_btn(self, tmp_path: Path) -> None:
        """Verify _on_cancelled_idle marks is_transcoding=False and enables open_btn."""
        from media_toolbox.ui.window import MainWindow

        mock_win = MagicMock()
        mock_win.is_transcoding = True
        out_file = tmp_path / "cancelled.mp4"

        ret = MainWindow._on_cancelled_idle(mock_win, out_file)

        assert ret is False  # GLib.SOURCE_REMOVE
        assert mock_win.is_transcoding is False
        mock_win._set_ui_controls_sensitive.assert_called_with(True)
        mock_win.open_btn.set_sensitive.assert_called_with(True)
        mock_win.progress_footer.finish.assert_called_with(False, "Operation cancelled")

    @pytest.mark.usefixtures("gi_env")
    def test_worker_error_restores_open_btn(self) -> None:
        """Verify _on_error_idle marks is_transcoding=False and enables open_btn."""
        from media_toolbox.ui.window import MainWindow

        mock_win = MagicMock()
        mock_win.is_transcoding = True

        ret = MainWindow._on_error_idle(mock_win, "Encode failed")

        assert ret is False  # GLib.SOURCE_REMOVE
        assert mock_win.is_transcoding is False
        mock_win._set_ui_controls_sensitive.assert_called_with(True)
        mock_win.open_btn.set_sensitive.assert_called_with(True)
        mock_win.progress_footer.finish.assert_called_with(False, "Failed: Encode failed")

    @pytest.mark.usefixtures("gi_env")
    def test_open_file_dialog_blocked_during_transcoding(self) -> None:
        """Verify open_file_dialog toasts and returns early when is_transcoding=True."""
        from media_toolbox.ui.window import MainWindow

        mock_win = MagicMock()
        mock_win.is_transcoding = True

        MainWindow.open_file_dialog(mock_win)

        mock_win.toast_overlay.add_toast.assert_called_once()

    @pytest.mark.usefixtures("gi_env")
    def test_load_media_file_blocked_during_transcoding(self, tmp_path: Path) -> None:
        """Verify load_media_file toasts and does not load file when is_transcoding=True."""
        from media_toolbox.ui.window import MainWindow

        mock_win = MagicMock()
        mock_win.is_transcoding = True
        sample_file = tmp_path / "input.mp4"
        sample_file.touch()

        MainWindow.load_media_file(mock_win, sample_file)

        mock_win.toast_overlay.add_toast.assert_called_once()
        assert not hasattr(mock_win, "input_file") or mock_win.input_file != sample_file


# ---------------------------------------------------------------------------
# 7. Cancellation Flow Tests
# ---------------------------------------------------------------------------


class TestCancellationFlow:
    """Verifies responsive cancellation, cancel_event signaling, and partial file cleanup using genuine production methods."""

    def test_cancel_button_triggers_cancel_event(self) -> None:
        """Verify ProgressFooterWidget cancel invokes callback, and MainWindow._on_cancel_clicked sets cancel_event."""
        from media_toolbox.ui.window import MainWindow
        from media_toolbox.ui.widgets import ProgressFooterWidget

        # 1. Verify ProgressFooterWidget._on_cancel_clicked invokes callback
        mock_cb = MagicMock()
        mock_footer = MagicMock()
        mock_footer.on_cancel_callback = mock_cb
        ProgressFooterWidget._on_cancel_clicked(mock_footer, MagicMock())
        mock_cb.assert_called_once()

        # 2. Verify MainWindow._on_cancel_clicked sets cancel_event and transitions footer
        mock_win = MagicMock()
        mock_win.cancel_event = threading.Event()
        assert not mock_win.cancel_event.is_set()

        MainWindow._on_cancel_clicked(mock_win)
        assert mock_win.cancel_event.is_set() is True
        mock_win.progress_footer.set_cancelling.assert_called_once()

    def test_cancel_updates_ui_state_to_cancelling(self) -> None:
        """Verify ProgressFooterWidget.set_cancelling disables button, updates label and status."""
        from media_toolbox.ui.widgets import ProgressFooterWidget

        mock_footer = MagicMock()
        ProgressFooterWidget.set_cancelling(mock_footer)

        mock_footer.cancel_button.set_sensitive.assert_called_with(False)
        mock_footer.cancel_button.set_label.assert_called_with("Cancelling...")
        mock_footer.status_label.set_text.assert_called_with("Cancelling transcode...")

    def test_worker_catches_runner_cancelled_error(self, gi_env, tmp_path: Path) -> None:
        """Verify MainWindow._worker_thread_entry catches RunnerCancelledError, preserves destination, and schedules _on_cancelled_idle."""
        _, _, _, _, _, GLib = gi_env
        from media_toolbox.ui.window import MainWindow

        mock_win = MagicMock()
        mock_win.is_transcoding = True
        mock_win._on_cancelled_idle.return_value = GLib.SOURCE_REMOVE

        pre_existing_file = tmp_path / "cancelled_output.mp4"
        pre_existing_file.write_bytes(b"original video data")
        assert pre_existing_file.exists()

        cancel_event = threading.Event()
        cancel_event.set()

        config = JobConfig(
            input_path=Path("/tmp/input.mp4"),
            output_path=pre_existing_file,
            options=EncodeOptions(),
        )

        with patch("media_toolbox.ui.window_worker.run_job", side_effect=RunnerCancelledError("Process killed")):
            MainWindow._worker_thread_entry(mock_win, config, cancel_event)

        # File is safely preserved, not deleted
        assert pre_existing_file.exists()
        assert pre_existing_file.read_bytes() == b"original video data"

        # GLib main context dispatches scheduled _on_cancelled_idle
        ctx = GLib.MainContext.default()
        drain_main_context(ctx)

        mock_win._on_cancelled_idle.assert_called_once_with(pre_existing_file)

        # Verify MainWindow._on_cancelled_idle logic directly
        mock_win_idle = MagicMock()
        mock_win_idle.is_transcoding = True
        ret = MainWindow._on_cancelled_idle(mock_win_idle, pre_existing_file)

        assert ret == GLib.SOURCE_REMOVE
        assert mock_win_idle.is_transcoding is False
        mock_win_idle._set_ui_controls_sensitive.assert_called_with(True)
        mock_win_idle.progress_footer.finish.assert_called_with(False, "Operation cancelled")
        mock_win_idle.toast_overlay.add_toast.assert_called_once()

    def test_cancellation_preserves_pre_existing_output_file(self, tmp_path: Path) -> None:
        """Verify MainWindow._worker_thread_entry does not delete pre-existing output files upon cancellation."""
        from media_toolbox.ui.window import MainWindow

        mock_win = MagicMock()
        mock_win._on_cancelled_idle.return_value = False

        pre_existing_file = tmp_path / "partially_encoded.mp4"
        pre_existing_file.write_bytes(b"original output bytes")
        assert pre_existing_file.exists()

        cancel_event = threading.Event()
        cancel_event.set()

        config = JobConfig(
            input_path=Path("/tmp/input.mp4"),
            output_path=pre_existing_file,
            options=EncodeOptions(),
        )

        with patch("media_toolbox.ui.window_worker.run_job", side_effect=RunnerCancelledError("Aborted")):
            MainWindow._worker_thread_entry(mock_win, config, cancel_event)

        assert pre_existing_file.exists()
        assert pre_existing_file.read_bytes() == b"original output bytes"

    def test_window_close_request_aborts_active_transcode(self) -> None:
        """Verify MainWindow._on_close_request signals cancel_event when transcoding and permits window closure."""
        from media_toolbox.ui.window import MainWindow

        mock_win = MagicMock()
        mock_win.cancel_event = threading.Event()
        mock_win.is_transcoding = True

        # When transcoding: sets cancel_event, returns False
        ret = MainWindow._on_close_request(mock_win)
        assert ret is False
        assert mock_win.cancel_event.is_set() is True

        # When idle: leaves cancel_event unset, returns False
        mock_win.cancel_event.clear()
        mock_win.is_transcoding = False
        ret = MainWindow._on_close_request(mock_win)
        assert ret is False
        assert not mock_win.cancel_event.is_set()
