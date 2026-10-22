"""Unit test suite for asynchronous shutdown lifecycle, job generation guarding, and cancellation escalation."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("gi")

from media_toolbox.core.jobs import JobConfig
from media_toolbox.core.models import EncodeOptions, ProgressEvent

pytestmark = [pytest.mark.desktop]


def make_mock_window():
    from media_toolbox.ui.constants import WindowState
    from media_toolbox.ui.window_worker import WindowWorkerMixin

    class MockWindow(WindowWorkerMixin):
        def __init__(self) -> None:
            self.state = WindowState.READY
            self.cancel_event = None
            self.is_transcoding = False
            self._pending_confirmation = False
            self._active_worker = None
            self._job_generation = 0
            self._close_after_cleanup = False
            self.progress_footer = MagicMock()
            self.toast_overlay = MagicMock()
            self.open_btn = MagicMock()
            self.destroyed = False

        def destroy(self) -> None:
            self.destroyed = True

    return MockWindow()


def test_close_request_vetoes_when_transcoding() -> None:
    """Close request returns True (veto) while transcoding and sets cancel_event."""
    from media_toolbox.ui.constants import WindowState

    win = make_mock_window()
    win.is_transcoding = True
    win.cancel_event = threading.Event()

    ret = win._on_close_request()
    assert ret is True
    assert win.cancel_event.is_set() is True
    assert win._close_after_cleanup is True
    assert win.state == WindowState.CANCELLING
    win.progress_footer.set_cancelling.assert_called_once()


def test_cancelled_idle_destroys_window_if_close_requested(tmp_path: Path) -> None:
    """_on_cancelled_idle triggers destroy() when _close_after_cleanup is set."""
    from media_toolbox.ui.constants import WindowState

    win = make_mock_window()
    win.state = WindowState.CANCELLING
    win.is_transcoding = True
    win._job_generation = 1
    win._close_after_cleanup = True

    ret = win._on_cancelled_idle(tmp_path / "out.mp4")
    assert ret is False
    assert win.state == WindowState.CLOSED
    assert win.is_transcoding is False
    assert win.destroyed is True


def test_progress_events_discarded_when_closed() -> None:
    """Progress events are discarded if window state is CLOSED."""
    from media_toolbox.ui.constants import WindowState

    win = make_mock_window()
    win.state = WindowState.CLOSED
    win._job_generation = 1

    evt = ProgressEvent(
        frame=10, fps=30.0, total_size_bytes=100000, out_time_seconds=1.0
    )
    ret = win._on_progress_idle(evt)
    assert ret is False
    win.progress_footer.update_progress.assert_not_called()


def test_progress_events_discarded_when_cancelling() -> None:
    """Progress events are discarded if window state is CANCELLING."""
    from media_toolbox.ui.constants import WindowState

    win = make_mock_window()
    win.state = WindowState.CANCELLING
    win._job_generation = 1

    evt = ProgressEvent(
        frame=10, fps=30.0, total_size_bytes=100000, out_time_seconds=1.0
    )
    ret = win._on_progress_idle(evt)
    assert ret is False
    win.progress_footer.update_progress.assert_not_called()


def test_worker_generation_guards_stale_callbacks(tmp_path: Path) -> None:
    """Worker thread ignores progress and success callbacks from superseding jobs."""
    from media_toolbox.ui.constants import WindowState

    win = make_mock_window()
    win.state = WindowState.RUNNING
    win._job_generation = 1

    captured_progress = None

    def fake_run_job(**kwargs):
        nonlocal captured_progress
        captured_progress = kwargs.get("progress_callback")
        # Simulate job supersession while job is running
        win._job_generation = 2
        return MagicMock(output_path=tmp_path / "out.mp4")

    with (
        patch("media_toolbox.ui.window_worker.run_job", side_effect=fake_run_job),
        patch("media_toolbox.ui.window_worker.GLib.idle_add") as mock_idle_add,
    ):
        config = JobConfig(
            input_path="in.mp4",
            output_path=str(tmp_path / "out.mp4"),
            options=EncodeOptions(),
        )
        cancel_evt = threading.Event()
        win._worker_thread_entry(config, cancel_evt)

        # Calling progress from gen 1 should be dropped because win._job_generation is now 2
        if captured_progress:
            captured_progress(ProgressEvent(frame=10))

        # Neither progress nor success should have been scheduled via idle_add
        mock_idle_add.assert_not_called()
