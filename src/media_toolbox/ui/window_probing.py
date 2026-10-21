"""
Media probing and file chooser portal mixin for Media Toolbox MainWindow.
"""

# pyright: reportMissingImports=false, reportMissingModuleSource=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportGeneralTypeIssues=false, reportInvalidTypeForm=false

from __future__ import annotations

from pathlib import Path
import threading
from typing import Any, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from media_toolbox.core.models import MediaInfo
from media_toolbox.core.probe import probe_media
from media_toolbox.ui.constants import WindowState
from media_toolbox.ui.forms import resolve_default_output_path


class WindowProbingMixin:
    """Mixin providing file dialogs, async media probing, and output path resolution."""

    # Attributes declared on MainWindow
    state: WindowState
    input_file: Optional[Path]
    media_info: Optional[MediaInfo]
    video_output_path: Optional[Path]
    audio_output_path: Optional[Path]
    _video_output_custom: bool
    _audio_output_custom: bool
    _probe_request_id: int
    is_transcoding: bool

    def open_file_dialog(self) -> None:
        """Present modern async file chooser portal."""
        if getattr(self, "is_transcoding", False):
            self.toast_overlay.add_toast(Adw.Toast(title="Cannot open file while transcoding is in progress."))
            return
        dialog = Gtk.FileDialog(title="Select Media File")
        dialog.open(self, None, self._on_file_dialog_finish)

    def _on_file_dialog_finish(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            gfile = dialog.open_finish(result)
            if gfile:
                path = gfile.get_path()
                if path:
                    self.load_media_file(path)
        except Exception:
            pass  # User cancelled dialog

    def choose_output_destination(self, is_audio: bool = False) -> None:
        """Present save file dialog for destination selection."""
        dialog = Gtk.FileDialog(title="Select Destination File")
        current = self.audio_output_path if is_audio else self.video_output_path
        if current:
            dialog.set_initial_name(current.name)
            dialog.set_initial_folder(Gio.File.new_for_path(str(current.parent)))

        dialog.save(self, None, lambda d, res: self._on_dest_dialog_finish(d, res, is_audio))

    def _on_dest_dialog_finish(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult, is_audio: bool) -> None:
        try:
            gfile = dialog.save_finish(result)
            if gfile and gfile.get_path():
                p = Path(gfile.get_path())
                if is_audio:
                    self.audio_output_path = p
                    self._audio_output_custom = True
                    self.audio_dest_row.set_subtitle(str(p))
                else:
                    self.video_output_path = p
                    self._video_output_custom = True
                    self.video_dest_row.set_subtitle(str(p))
        except Exception:
            pass  # User cancelled

    def load_media_file(self, path: str | Path, sync: bool = False) -> None:
        """Inspect media file and configure widgets asynchronously."""
        if getattr(self, "state", None) in (WindowState.RUNNING, WindowState.CANCELLING, WindowState.CLOSED) or getattr(self, "is_transcoding", False):
            self.toast_overlay.add_toast(Adw.Toast(title="Cannot load file while transcoding is in progress."))
            return
        p = Path(path).resolve()
        if not p.exists():
            self.toast_overlay.add_toast(Adw.Toast(title=f"File not found: {p.name}"))
            return

        self._probe_request_id += 1
        req_id = self._probe_request_id
        self.state = WindowState.PROBING
        # Invalidate active loaded media during probing
        self.input_file = None
        self.media_info = None
        self.transcode_btn.set_sensitive(False)
        self.extract_btn.set_sensitive(False)
        self.window_title.set_subtitle(f"Probing {p.name}...")

        if sync:
            self._probe_worker(p, req_id)
        else:
            threading.Thread(
                target=self._probe_worker,
                args=(p, req_id),
                daemon=True,
            ).start()

    def _probe_worker(self, p: Path, req_id: int) -> None:
        try:
            media_info = probe_media(p)
            GLib.idle_add(self._on_probe_success, p, req_id, media_info)
        except Exception as exc:
            GLib.idle_add(self._on_probe_error, p, req_id, str(exc))

    def _on_probe_success(self, p: Path, req_id: int, media_info: MediaInfo) -> bool:
        if getattr(self, "state", None) == WindowState.CLOSED or req_id != self._probe_request_id:
            return False  # Discard stale completion

        self.input_file = p
        self.media_info = media_info
        self.state = WindowState.READY
        self._video_output_custom = False
        self._audio_output_custom = False
        self.window_title.set_subtitle(p.name)
        self.metadata_card.set_media_info(media_info)

        if media_info.primary_video:
            pv = media_info.primary_video
            eff_w, eff_h = pv.effective_dimensions
            self.res_widget.set_source_resolution(eff_w, eff_h)

        self.audio_widget.set_has_audio(media_info.has_audio)
        self._update_default_output_paths()
        self.main_stack.set_visible_child_name("loaded")
        self._set_ui_controls_sensitive(True)
        return False

    def _on_probe_error(self, p: Path, req_id: int, error_msg: str) -> bool:
        if getattr(self, "state", None) == WindowState.CLOSED or req_id != self._probe_request_id:
            return False

        self.state = WindowState.EMPTY
        self.window_title.set_subtitle("No media selected")
        self.main_stack.set_visible_child_name("empty")
        self._set_ui_controls_sensitive(True)
        self.transcode_btn.set_sensitive(False)
        self.extract_btn.set_sensitive(False)
        self.toast_overlay.add_toast(Adw.Toast(title=f"Failed to probe media: {error_msg}"))
        return False

    def _update_default_output_paths(self) -> None:
        input_file = self.input_file
        if input_file is None:
            return

        # Video path
        if not getattr(self, "_video_output_custom", False):
            video_preset = self.get_current_video_preset()
            is_target_size = (self.rate_widget.get_mode() == "target_size") and video_preset not in ("gif", "prores")
            self.video_output_path = resolve_default_output_path(
                input_file,
                video_preset,
                is_extract_audio=False,
                is_target_size=is_target_size,
            )
            self.video_dest_row.set_subtitle(str(self.video_output_path))

        # Audio path
        if not getattr(self, "_audio_output_custom", False):
            audio_preset = self.get_current_audio_preset()
            self.audio_output_path = resolve_default_output_path(
                input_file,
                audio_preset,
                is_extract_audio=True,
            )
            self.audio_dest_row.set_subtitle(str(self.audio_output_path))
