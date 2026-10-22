"""
Lifecycle and process shutdown tests for media_toolbox.core.runner.

Uses real Python child processes to verify:
- Process normal exit when stdout closes before process terminates
- Error handling when end marker is followed by a non-zero exit code
- No leaked watcher threads on repeated executions
- Escalation to SIGKILL when child process ignores SIGTERM
- Graceful handling of missing binary with typed RunnerError
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from media_toolbox.core.models import ProgressEvent
from media_toolbox.core.runner import (
    RunnerCancelledError,
    RunnerError,
    run_ffmpeg,
)


class TestRunnerSubprocessLifecycle:
    def test_stdout_closes_before_delayed_exit_succeeds(self, tmp_path: Path) -> None:
        """
        Verify run_ffmpeg waits for process exit after stdout reaches EOF
        instead of terminating the still-running process with SIGTERM.
        """
        script = tmp_path / "delayed_exit.py"
        script.write_text(
            "import sys, time\n"
            "sys.stdout.write('frame=10\\nprogress=continue\\n')\n"
            "sys.stdout.flush()\n"
            "sys.stdout.close()\n"  # Closes stdout pipe
            "time.sleep(0.3)\n"  # Remains alive after EOF
            "sys.exit(0)\n"
        )

        events: list[ProgressEvent] = []
        # Should complete successfully (exit code 0) without raising RunnerError
        run_ffmpeg(
            [sys.executable, str(script)],
            progress_callback=events.append,
        )

        assert any(e.frame == 10 for e in events)

    def test_end_marker_followed_by_nonzero_exit_raises_error_without_success_completion(
        self, tmp_path: Path
    ) -> None:
        """
        Verify progress=end does NOT emit is_completed=True if the process subsequently exits non-zero.
        """
        script = tmp_path / "fail_after_end.py"
        script.write_text(
            "import sys, time\n"
            "sys.stdout.write('frame=100\\nprogress=end\\n')\n"
            "sys.stdout.flush()\n"
            "sys.stderr.write('Fatal container trailer write error\\n')\n"
            "sys.exit(1)\n"
        )

        events: list[ProgressEvent] = []
        with pytest.raises(RunnerError) as exc_info:
            run_ffmpeg(
                [sys.executable, str(script)],
                progress_callback=events.append,
            )

        assert exc_info.value.returncode == 1
        # No event emitted should claim is_completed == True
        assert not any(e.is_completed for e in events)

    def test_repeated_successful_jobs_leave_no_watcher_threads(
        self, tmp_path: Path
    ) -> None:
        """
        Verify cancellation watcher threads are terminated and joined upon completion,
        leaving no leaked threads.
        """
        script = tmp_path / "quick_job.py"
        script.write_text(
            "import sys\nsys.stdout.write('frame=1\\nprogress=end\\n')\nsys.exit(0)\n"
        )

        cancel_event = threading.Event()

        # Run 5 consecutive jobs with active cancel_event instances
        for _ in range(5):
            run_ffmpeg(
                [sys.executable, str(script)],
                cancel_event=cancel_event,
            )

        # Check that no ffmpeg-cancel-watch threads are still alive
        active_watchers = [
            t.name
            for t in threading.enumerate()
            if "ffmpeg-cancel-watch" in t.name and t.is_alive()
        ]
        assert active_watchers == []

    def test_cancellation_escalates_to_sigkill_when_sigterm_ignored(
        self, tmp_path: Path
    ) -> None:
        """
        Verify process is forcefully killed (SIGKILL) if it traps and ignores SIGTERM.
        """
        script = tmp_path / "ignore_sigterm.py"
        ready_file = tmp_path / "ready.txt"
        script.write_text(
            "import signal, sys, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            f"open({str(ready_file)!r}, 'w').write('ready')\n"
            "while True:\n"
            "    time.sleep(0.05)\n"
        )

        cancel_event = threading.Event()

        def _cancel_when_ready() -> None:
            for _ in range(100):
                if ready_file.exists():
                    time.sleep(0.05)
                    cancel_event.set()
                    return
                time.sleep(0.02)

        trigger_thread = threading.Thread(target=_cancel_when_ready)
        trigger_thread.start()

        start_time = time.monotonic()
        with pytest.raises(RunnerCancelledError):
            run_ffmpeg(
                [sys.executable, str(script)],
                cancel_event=cancel_event,
                sigterm_timeout=0.2,  # Quick escalation to SIGKILL
            )
        elapsed = time.monotonic() - start_time
        trigger_thread.join()

        # Escalation should terminate the stuck process within reasonable deadline
        assert elapsed < 3.0

    def test_missing_binary_raises_typed_runner_error(self) -> None:
        """
        Verify non-existent executable raises typed RunnerError with exit code 127.
        """
        with pytest.raises(RunnerError) as exc_info:
            run_ffmpeg(["/nonexistent/path/to/ffmpeg_binary_xyz_123"])

        assert exc_info.value.returncode in (127, 1)
        assert "not found" in str(exc_info.value).lower()
