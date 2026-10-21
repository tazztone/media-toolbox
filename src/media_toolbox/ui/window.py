"""
MainWindow Libadwaita application window for media_toolbox.

Features:
- HeaderBar with file opening, subtitle showing active file, and application menu.
- Dual-mode workflow: Transcode Video vs Extract Audio via Adw.ViewStack / Adw.ViewSwitcher.
- Dynamic preferences pages integrating RateControlWidget, ResolutionWidget, AudioOptionsWidget, and MetadataCard.
- Output destination file picker via Gtk.FileDialog.
- Non-blocking daemon background worker thread executing core.runner.run_ffmpeg_pipeline.
- Thread-safe UI updates dispatched via GLib.idle_add with GLib.SOURCE_REMOVE returns.
- Clean cancellation with process group termination and incomplete partial file cleanup.
- Window close-request handler ensuring no orphaned background FFmpeg processes.
"""

# pyright: reportMissingImports=false, reportMissingModuleSource=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportGeneralTypeIssues=false, reportInvalidTypeForm=false

from __future__ import annotations

from pathlib import Path
import threading
from typing import Any, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from media_toolbox.core.jobs import JobConfig
from media_toolbox.core.models import EncodeOptions, MediaInfo
from media_toolbox.ui.constants import (
    AUDIO_PRESETS,
    CROP_PRESETS,
    SPEED_PRESETS,
    VIDEO_PRESETS,
    WindowState,
)
from media_toolbox.ui.forms import (
    build_encode_options_from_state,
    resolve_default_output_path,
)
from media_toolbox.ui.widgets import (
    AudioOptionsWidget,
    MetadataCard,
    ProgressFooterWidget,
    RateControlWidget,
    ResolutionWidget,
)
from media_toolbox.ui.window_builder import (
    build_extract_audio_page,
    build_transcode_page,
    build_window_layout,
)
from media_toolbox.ui.window_probing import WindowProbingMixin
from media_toolbox.ui.window_worker import WindowWorkerMixin

__all__ = [
    "WindowState",
    "MainWindow",
]


class MainWindow(Adw.ApplicationWindow, WindowProbingMixin, WindowWorkerMixin):
    """
    Main Libadwaita application window.
    """

    VIDEO_PRESETS = VIDEO_PRESETS
    AUDIO_PRESETS = AUDIO_PRESETS
    CROP_PRESETS = CROP_PRESETS
    SPEED_PRESETS = SPEED_PRESETS

    # Widget attributes attached by window_builder.build_window_layout()
    header_bar: Adw.HeaderBar
    window_title: Adw.WindowTitle
    toast_overlay: Adw.ToastOverlay
    main_stack: Gtk.Stack
    metadata_card: MetadataCard
    view_stack: Adw.ViewStack
    view_switcher: Adw.ViewSwitcher
    progress_footer: ProgressFooterWidget
    video_preset_row: Adw.ComboRow
    rate_widget: RateControlWidget
    res_widget: ResolutionWidget
    crop_row: Adw.ComboRow
    speed_row: Adw.ComboRow
    audio_widget: AudioOptionsWidget
    video_dest_row: Adw.ActionRow
    transcode_btn: Gtk.Button
    audio_preset_row: Adw.ComboRow
    extract_bitrate_adj: Gtk.Adjustment
    extract_bitrate_row: Adw.SpinRow
    extract_speed_row: Adw.ComboRow
    extract_norm_switch: Adw.SwitchRow
    extract_boost_adj: Gtk.Adjustment
    extract_boost_row: Adw.SpinRow
    audio_dest_row: Adw.ActionRow
    extract_btn: Gtk.Button

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.set_default_size(920, 740)
        self.set_size_request(640, 500)

        self.state: WindowState = WindowState.EMPTY
        self.input_file: Optional[Path] = None
        self.media_info: Optional[MediaInfo] = None
        self.video_output_path: Optional[Path] = None
        self.audio_output_path: Optional[Path] = None
        self._video_output_custom: bool = False
        self._audio_output_custom: bool = False
        self.cancel_event: Optional[threading.Event] = None
        self.is_transcoding: bool = False
        self.open_btn: Optional[Gtk.Button] = None
        self._probe_request_id: int = 0
        self._pending_confirmation: bool = False
        self._active_worker: Optional[threading.Thread] = None

        self._build_ui()
        self.connect("close-request", self._on_close_request)

    def _build_ui(self) -> None:
        """Construct the complete Libadwaita window UI layout."""
        build_window_layout(self)

    # -----------------------------------------------------------------------
    # Preset & Output Path Management
    # -----------------------------------------------------------------------

    def get_current_video_preset(self) -> str:
        idx = self.video_preset_row.get_selected()
        return VIDEO_PRESETS[idx][1]

    def get_current_audio_preset(self) -> str:
        idx = self.audio_preset_row.get_selected()
        return AUDIO_PRESETS[idx][1]

    def _on_video_preset_changed(self, _combo: Adw.ComboRow, _param: Any) -> None:
        preset = self.get_current_video_preset()
        self.rate_widget.set_codec_preset(preset)
        self._update_default_output_paths()

    def _on_audio_preset_changed(self, _combo: Adw.ComboRow, _param: Any) -> None:
        preset = self.get_current_audio_preset()
        self.extract_bitrate_row.set_sensitive(preset != "flac")
        self._update_default_output_paths()

    # -----------------------------------------------------------------------
    # Form Extraction
    # -----------------------------------------------------------------------

    def get_transcode_options(self) -> EncodeOptions:
        preset = self.get_current_video_preset()
        rate_mode = self.rate_widget.get_mode()
        crf_val = self.rate_widget.get_crf()
        target_size_mb = self.rate_widget.get_target_size_mb()
        scale = self.res_widget.get_scale()

        crop_idx = self.crop_row.get_selected()
        crop = CROP_PRESETS[crop_idx][1]

        speed_idx = self.speed_row.get_selected()
        speed_factor = SPEED_PRESETS[speed_idx][1]

        mute = self.audio_widget.get_mute()
        norm = self.audio_widget.get_normalize()
        boost = self.audio_widget.get_volume_boost()
        audio_br = self.audio_widget.get_audio_bitrate()

        return build_encode_options_from_state(
            preset=preset,
            rate_mode=rate_mode,
            crf_value=crf_val,
            target_size_mb=target_size_mb,
            scale=scale,
            crop=crop,
            mute_audio=mute,
            normalize_audio=norm,
            volume_boost_db=boost,
            audio_bitrate_kbps=audio_br,
            speed_factor=speed_factor,
            is_extract_audio=False,
        )

    def get_extract_audio_options(self) -> EncodeOptions:
        preset = self.get_current_audio_preset()
        bitrate = int(self.extract_bitrate_row.get_value())
        speed_idx = self.extract_speed_row.get_selected()
        speed_factor = SPEED_PRESETS[speed_idx][1]
        norm = bool(self.extract_norm_switch.get_active())
        boost_val = float(self.extract_boost_row.get_value())
        boost = boost_val if abs(boost_val) > 0.01 else None

        return build_encode_options_from_state(
            preset=preset,
            rate_mode="crf",
            crf_value=23,
            target_size_mb=25.0,
            scale=None,
            mute_audio=False,
            normalize_audio=norm,
            volume_boost_db=boost,
            audio_bitrate_kbps=bitrate,
            speed_factor=speed_factor,
            is_extract_audio=True,
        )

    # -----------------------------------------------------------------------
    # Action Triggers
    # -----------------------------------------------------------------------

    def _start_transcode(self) -> None:
        if self.state != WindowState.READY or not self.input_file or not self.media_info:
            self.toast_overlay.add_toast(Adw.Toast(title="Please open a media file first."))
            return

        options = self.get_transcode_options()
        out_path = self.video_output_path
        if not out_path:
            out_path = resolve_default_output_path(self.input_file, options.preset or "h264")
            self.video_output_path = out_path

        config = JobConfig(
            input_path=self.input_file,
            output_path=out_path,
            options=options,
            media_info=self.media_info,
            overwrite=False,
        )

        self._confirm_overwrite_and_start(config, "Transcoding video...")

    def _start_extract_audio(self) -> None:
        if self.state != WindowState.READY or not self.input_file or not self.media_info:
            self.toast_overlay.add_toast(Adw.Toast(title="Please open a media file first."))
            return

        options = self.get_extract_audio_options()
        out_path = self.audio_output_path
        if not out_path:
            out_path = resolve_default_output_path(self.input_file, options.preset or "mp3", is_extract_audio=True)
            self.audio_output_path = out_path

        config = JobConfig(
            input_path=self.input_file,
            output_path=out_path,
            options=options,
            media_info=self.media_info,
            overwrite=False,
        )

        self._confirm_overwrite_and_start(config, "Extracting audio...")
