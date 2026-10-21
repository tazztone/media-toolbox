"""
Background worker thread lifecycle, GLib idle synchronization, and overwrite confirmation mixin.
"""

# pyright: reportMissingImports=false, reportMissingModuleSource=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportGeneralTypeIssues=false, reportInvalidTypeForm=false

from __future__ import annotations

import dataclasses
from pathlib import Path
import threading
from typing import Any, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib

from media_toolbox.core.jobs import JobConfig, run_job
from media_toolbox.core.models import ProgressEvent
from media_toolbox.core.runner import (
    RunnerCancelledError,
    RunnerError,
    run_ffmpeg_pipeline,
)
from media_toolbox.ui.constants import WindowState


class WindowWorkerMixin:
    """Mixin managing worker thread execution, process cancellation, and GLib idle UI updates."""

    state: WindowState
    cancel_event: Optional[threading.Event]
    is_transcoding: bool
    _pending_confirmation: bool
    _active_worker: Optional[threading.Thread]
    _job_generation: int = 0
    _close_after_cleanup: bool = False

    def _set_ui_controls_sensitive(self, sensitive: bool) -> None:
        if hasattr(self, "view_stack") and self.view_stack is not None:
            self.view_stack.set_sensitive(sensitive)
        if hasattr(self, "transcode_btn") and self.transcode_btn is not None:
            self.transcode_btn.set_sensitive(sensitive)
        if hasattr(self, "extract_btn") and self.extract_btn is not None:
            self.extract_btn.set_sensitive(sensitive)
        if hasattr(self, "open_btn") and self.open_btn is not None:
            self.open_btn.set_sensitive(sensitive)

    def _confirm_overwrite_and_start(self, config: JobConfig, title: str) -> None:
        if getattr(self, "_pending_confirmation", False) is True:
            return

        out_p = Path(config.output_path)
        if out_p.exists():
            self._pending_confirmation = True
            if hasattr(self, "_set_ui_controls_sensitive"):
                self._set_ui_controls_sensitive(False)
            if hasattr(self, "open_btn") and self.open_btn is not None and hasattr(self.open_btn, "set_sensitive"):
                self.open_btn.set_sensitive(False)

            dialog = Adw.MessageDialog(
                transient_for=self,
                heading="Replace File?",
                body=f"'{out_p.name}' already exists. Overwriting will replace its contents.",
            )
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("replace", "Replace")
            dialog.set_response_appearance("replace", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.set_default_response("cancel")
            dialog.set_close_response("cancel")

            current_input = getattr(self, "input_file", None)

            def _on_response(_d: Any, response_id: str) -> None:
                self._pending_confirmation = False
                if getattr(self, "state", None) == WindowState.CLOSED:
                    return

                if response_id == "replace":
                    if getattr(self, "state", None) != WindowState.READY or getattr(self, "input_file", None) != current_input:
                        if hasattr(self, "_set_ui_controls_sensitive"):
                            self._set_ui_controls_sensitive(True)
                        if hasattr(self, "open_btn") and self.open_btn is not None and hasattr(self.open_btn, "set_sensitive"):
                            self.open_btn.set_sensitive(True)
                        return
                    confirmed_config = dataclasses.replace(config, overwrite=True)
                    self._start_worker(confirmed_config, title)
                else:
                    if hasattr(self, "_set_ui_controls_sensitive"):
                        self._set_ui_controls_sensitive(True)
                    if hasattr(self, "open_btn") and self.open_btn is not None and hasattr(self.open_btn, "set_sensitive"):
                        self.open_btn.set_sensitive(True)

            dialog.connect("response", _on_response)
            dialog.present()
        else:
            self._start_worker(config, title)

    def _start_worker(
        self,
        config: JobConfig,
        title: str = "Processing media...",
    ) -> None:
        if (
            hasattr(self, "_active_worker")
            and self._active_worker is not None
            and hasattr(self._active_worker, "is_alive")
            and self._active_worker.is_alive() is True
        ):
            return
        if getattr(self, "state", None) == WindowState.CLOSED:
            return
        self.state = WindowState.RUNNING
        self._close_after_cleanup = False
        self._job_generation = getattr(self, "_job_generation", 0) + 1
        self.cancel_event = threading.Event()
        self.is_transcoding = True
        self._set_ui_controls_sensitive(False)
        if hasattr(self, "open_btn") and self.open_btn is not None:
            self.open_btn.set_sensitive(False)

        self.progress_footer.start(title)
        worker_args: tuple[Any, ...] = (config, self.cancel_event)

        worker_thread = threading.Thread(
            target=self._worker_thread_entry,
            args=worker_args,
            daemon=True,
            name="MediaToolboxWorker",
        )
        self._active_worker = worker_thread
        worker_thread.start()

    # Backwards compatibility alias
    _launch_worker_pipeline = _start_worker

    def _worker_thread_entry(
        self,
        config: JobConfig,
        cancel_event: threading.Event,
    ) -> None:
        """Worker thread running FFmpeg job in background without blocking UI thread."""
        current_gen = getattr(self, "_job_generation", 0)

        def _on_progress(evt: ProgressEvent) -> None:
            if getattr(self, "_job_generation", 0) == current_gen:
                GLib.idle_add(self._on_progress_idle, evt)

        def _on_pass_progress(pass_num: int, total_passes: int, evt: ProgressEvent) -> None:
            if getattr(self, "_job_generation", 0) == current_gen:
                GLib.idle_add(self._on_pass_progress_idle, pass_num, total_passes, evt)

        try:
            result = run_job(
                config=config,
                progress_callback=_on_progress,
                pipeline_progress_callback=_on_pass_progress,
                cancel_event=cancel_event,
            )
            if getattr(self, "_job_generation", 0) == current_gen:
                GLib.idle_add(self._on_success_idle, result.output_path)
        except RunnerCancelledError:
            if getattr(self, "_job_generation", 0) == current_gen:
                GLib.idle_add(self._on_cancelled_idle, Path(config.output_path))
        except RunnerError as err:
            err_msg = err.last_error_line or str(err)
            if getattr(self, "_job_generation", 0) == current_gen:
                GLib.idle_add(self._on_error_idle, err_msg)
        except Exception as exc:
            if getattr(self, "_job_generation", 0) == current_gen:
                GLib.idle_add(self._on_error_idle, str(exc))

    def _on_progress_idle(self, event: ProgressEvent) -> bool:
        if getattr(self, "state", None) in (WindowState.CLOSED, WindowState.CANCELLING):
            return GLib.SOURCE_REMOVE
        self.progress_footer.update_progress(event)
        return GLib.SOURCE_REMOVE

    def _on_pass_progress_idle(self, pass_num: int, total_passes: int, event: ProgressEvent) -> bool:
        if getattr(self, "state", None) in (WindowState.CLOSED, WindowState.CANCELLING):
            return GLib.SOURCE_REMOVE
        pass_info = f"Pass {pass_num} of {total_passes} ({event.percentage:.1f}%)" if total_passes > 1 else None
        self.progress_footer.update_progress(event, pass_info=pass_info)
        return GLib.SOURCE_REMOVE

    def _on_success_idle(self, output_path: Path) -> bool:
        if getattr(self, "state", None) == WindowState.CLOSED:
            return GLib.SOURCE_REMOVE

        if getattr(self, "_close_after_cleanup", False) is True:
            self.state = WindowState.CLOSED
            self.is_transcoding = False
            if hasattr(self, "destroy"):
                self.destroy()
            return GLib.SOURCE_REMOVE

        self.state = WindowState.READY
        self.is_transcoding = False
        self._set_ui_controls_sensitive(True)
        if hasattr(self, "open_btn") and self.open_btn is not None:
            self.open_btn.set_sensitive(True)
        self.progress_footer.finish(True, f"Saved: {output_path.name}")
        self.toast_overlay.add_toast(Adw.Toast(title=f"Completed successfully: {output_path.name}"))
        return GLib.SOURCE_REMOVE

    def _on_cancelled_idle(self, _output_path: Path) -> bool:
        if getattr(self, "state", None) == WindowState.CLOSED:
            return GLib.SOURCE_REMOVE

        if getattr(self, "_close_after_cleanup", False) is True:
            self.state = WindowState.CLOSED
            self.is_transcoding = False
            if hasattr(self, "destroy"):
                self.destroy()
            return GLib.SOURCE_REMOVE

        self.state = WindowState.READY
        self.is_transcoding = False
        self._set_ui_controls_sensitive(True)
        if hasattr(self, "open_btn") and self.open_btn is not None:
            self.open_btn.set_sensitive(True)
        self.progress_footer.finish(False, "Operation cancelled")
        self.toast_overlay.add_toast(Adw.Toast(title="Operation cancelled by user."))
        return GLib.SOURCE_REMOVE

    def _on_error_idle(self, error_message: str) -> bool:
        if getattr(self, "state", None) == WindowState.CLOSED:
            return GLib.SOURCE_REMOVE

        if getattr(self, "_close_after_cleanup", False) is True:
            self.state = WindowState.CLOSED
            self.is_transcoding = False
            if hasattr(self, "destroy"):
                self.destroy()
            return GLib.SOURCE_REMOVE

        self.state = WindowState.READY
        self.is_transcoding = False
        self._set_ui_controls_sensitive(True)
        if hasattr(self, "open_btn") and self.open_btn is not None:
            self.open_btn.set_sensitive(True)
        self.progress_footer.finish(False, f"Failed: {error_message}")
        self.toast_overlay.add_toast(Adw.Toast(title=f"Encoding failed: {error_message}"))
        return GLib.SOURCE_REMOVE

    def _on_cancel_clicked(self) -> None:
        self.state = WindowState.CANCELLING
        if self.cancel_event:
            self.cancel_event.set()
        self.progress_footer.set_cancelling()

    def _on_close_request(self, *_args: Any) -> bool:
        if getattr(self, "is_transcoding", False):
            self._close_after_cleanup = True
            self.state = WindowState.CANCELLING
            cancel_event = self.cancel_event
            if cancel_event is not None:
                cancel_event.set()
            if hasattr(self, "progress_footer") and hasattr(self.progress_footer, "set_cancelling"):
                self.progress_footer.set_cancelling()
            return True
        self.state = WindowState.CLOSED
        return False
