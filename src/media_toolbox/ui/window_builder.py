"""
Declarative layout and widget hierarchy builder for Media Toolbox MainWindow.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk  # pyright: ignore[reportAttributeAccessIssue]

from media_toolbox.ui.constants import (
    AUDIO_PRESETS,
    CROP_PRESETS,
    SPEED_PRESETS,
    VIDEO_PRESETS,
)
from media_toolbox.ui.widgets import (
    AudioOptionsWidget,
    MetadataCard,
    ProgressFooterWidget,
    RateControlWidget,
    ResolutionWidget,
)

if TYPE_CHECKING:
    from media_toolbox.ui.window import MainWindow


def build_window_layout(win: MainWindow) -> None:
    """Construct and attach the complete Libadwaita window UI layout."""
    # Top Header Bar
    win.header_bar = Adw.HeaderBar()
    open_btn = Gtk.Button(
        icon_name="document-open-symbolic",
        tooltip_text="Open Media File (<Ctrl>O)",
    )
    win.open_btn = open_btn
    open_btn.connect("clicked", lambda _b: win.open_file_dialog())
    win.header_bar.pack_start(open_btn)

    win.window_title = Adw.WindowTitle(
        title="Media Toolbox",
        subtitle="No media selected",
    )
    win.header_bar.set_title_widget(win.window_title)

    # Menu button
    menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
    menu = Gio.Menu()
    menu.append("Open File...", "app.open")
    menu.append("About Media Toolbox", "app.about")
    menu.append("Quit", "app.quit")
    menu_btn.set_menu_model(menu)
    win.header_bar.pack_end(menu_btn)

    # Root box inside ToastOverlay
    win.toast_overlay = Adw.ToastOverlay()
    root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    root_box.append(win.header_bar)

    # Main Stack: empty state vs loaded state
    win.main_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)

    # 1. Empty State Page
    empty_page = Adw.StatusPage(
        title="Media Toolbox",
        description="Open a video or audio file to inspect, transcode, or extract audio.",
        icon_name="video-x-generic-symbolic",
    )
    empty_btn = Gtk.Button(
        label="Open Media File...",
        halign=Gtk.Align.CENTER,
        css_classes=["suggested-action", "pill"],
    )
    empty_btn.connect("clicked", lambda _b: win.open_file_dialog())
    empty_page.set_child(empty_btn)
    win.main_stack.add_named(empty_page, "empty")

    # 2. Loaded State Page
    scrolled = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
    content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
    content_box.set_margin_start(18)
    content_box.set_margin_end(18)
    content_box.set_margin_top(14)
    content_box.set_margin_bottom(14)

    # Metadata summary card
    win.metadata_card = MetadataCard()
    content_box.append(win.metadata_card)

    # Tabs for Transcode Video vs Extract Audio
    win.view_stack = Adw.ViewStack()

    # Tab 1: Transcode Video
    transcode_page = build_transcode_page(win)
    win.view_stack.add_titled_with_icon(
        transcode_page,
        "transcode",
        "Transcode Video",
        "video-x-generic-symbolic",
    )

    # Tab 2: Extract Audio
    extract_page = build_extract_audio_page(win)
    win.view_stack.add_titled_with_icon(
        extract_page,
        "extract",
        "Extract Audio",
        "audio-x-generic-symbolic",
    )

    win.view_switcher = Adw.ViewSwitcher(
        stack=win.view_stack,
        policy=Adw.ViewSwitcherPolicy.WIDE,
        halign=Gtk.Align.CENTER,
    )
    content_box.append(win.view_switcher)
    content_box.append(win.view_stack)

    scrolled.set_child(content_box)
    win.main_stack.add_named(scrolled, "loaded")

    root_box.append(win.main_stack)

    # Progress Footer (anchored at bottom)
    win.progress_footer = ProgressFooterWidget(
        on_cancel_callback=win._on_cancel_clicked
    )
    root_box.append(win.progress_footer)

    win.toast_overlay.set_child(root_box)
    win.set_content(win.toast_overlay)


def build_transcode_page(win: MainWindow) -> Adw.PreferencesPage:
    """Construct the Transcode Video preferences page."""
    page = Adw.PreferencesPage()

    # Codec Preset Group
    preset_group = Adw.PreferencesGroup(title="Target Codec & Format")
    preset_strings = [p[0] for p in VIDEO_PRESETS]
    win.video_preset_row = Adw.ComboRow(
        title="Video Codec Preset",
        model=Gtk.StringList.new(preset_strings),
        selected=0,
    )
    win.video_preset_row.connect("notify::selected", win._on_video_preset_changed)
    preset_group.add(win.video_preset_row)
    page.add(preset_group)

    # Rate Control & Quality
    win.rate_widget = RateControlWidget()
    win.rate_widget.mode_row.connect(
        "notify::selected", lambda *_: win._update_default_output_paths()
    )
    page.add(win.rate_widget)

    # Resolution & Dimensions
    win.res_widget = ResolutionWidget()
    page.add(win.res_widget)

    # Video Adjustments Group (Crop & Speed)
    adjust_group = Adw.PreferencesGroup(title="Video Transformations")
    crop_strings = [c[0] for c in CROP_PRESETS]
    win.crop_row = Adw.ComboRow(
        title="Aspect Ratio Crop",
        model=Gtk.StringList.new(crop_strings),
        selected=0,
    )
    adjust_group.add(win.crop_row)

    speed_strings = [s[0] for s in SPEED_PRESETS]
    win.speed_row = Adw.ComboRow(
        title="Playback Speed",
        model=Gtk.StringList.new(speed_strings),
        selected=0,
    )
    adjust_group.add(win.speed_row)
    page.add(adjust_group)

    # Audio Adjustments
    win.audio_widget = AudioOptionsWidget()
    page.add(win.audio_widget)

    # Destination & Action Group
    action_group = Adw.PreferencesGroup(title="Destination & Action")
    win.video_dest_row = Adw.ActionRow(
        title="Output File",
        subtitle="Not configured",
    )
    browse_btn = Gtk.Button(label="Browse...")
    browse_btn.connect(
        "clicked", lambda _b: win.choose_output_destination(is_audio=False)
    )
    win.video_dest_row.add_suffix(browse_btn)
    action_group.add(win.video_dest_row)

    win.transcode_btn = Gtk.Button(
        label="Start Transcode",
        halign=Gtk.Align.END,
        css_classes=["suggested-action"],
        margin_top=8,
        margin_bottom=8,
    )
    win.transcode_btn.connect("clicked", lambda _b: win._start_transcode())
    action_group.add(win.transcode_btn)

    page.add(action_group)
    return page


def build_extract_audio_page(win: MainWindow) -> Adw.PreferencesPage:
    """Construct the standalone Extract Audio preferences page."""
    page = Adw.PreferencesPage()

    # Audio Format Group
    format_group = Adw.PreferencesGroup(title="Audio Format & Bitrate")
    audio_preset_strings = [p[0] for p in AUDIO_PRESETS]
    win.audio_preset_row = Adw.ComboRow(
        title="Audio Format",
        model=Gtk.StringList.new(audio_preset_strings),
        selected=0,
    )
    win.audio_preset_row.connect("notify::selected", win._on_audio_preset_changed)
    format_group.add(win.audio_preset_row)

    win.extract_bitrate_adj = Gtk.Adjustment(
        value=192,
        lower=32,
        upper=320,
        step_increment=32,
        page_increment=64,
    )
    win.extract_bitrate_row = Adw.SpinRow(
        title="Audio Bitrate (kbps)",
        adjustment=win.extract_bitrate_adj,
        climb_rate=32.0,
        digits=0,
    )
    format_group.add(win.extract_bitrate_row)
    page.add(format_group)

    # Audio Adjustments Group
    adjust_group = Adw.PreferencesGroup(title="Audio Processing")
    speed_strings = [s[0] for s in SPEED_PRESETS]
    win.extract_speed_row = Adw.ComboRow(
        title="Playback Speed",
        model=Gtk.StringList.new(speed_strings),
        selected=0,
    )
    adjust_group.add(win.extract_speed_row)

    win.extract_norm_switch = Adw.SwitchRow(
        title="Normalize Loudness",
        subtitle="EBU R128 loudness normalization (loudnorm)",
        active=False,
    )
    adjust_group.add(win.extract_norm_switch)

    win.extract_boost_adj = Gtk.Adjustment(
        value=0.0,
        lower=-20.0,
        upper=20.0,
        step_increment=0.5,
        page_increment=2.0,
    )
    win.extract_boost_row = Adw.SpinRow(
        title="Volume Boost (dB)",
        adjustment=win.extract_boost_adj,
        climb_rate=0.5,
        digits=1,
    )
    adjust_group.add(win.extract_boost_row)
    page.add(adjust_group)

    # Destination & Action Group
    action_group = Adw.PreferencesGroup(title="Destination & Action")
    win.audio_dest_row = Adw.ActionRow(
        title="Output File",
        subtitle="Not configured",
    )
    browse_btn = Gtk.Button(label="Browse...")
    browse_btn.connect(
        "clicked", lambda _b: win.choose_output_destination(is_audio=True)
    )
    win.audio_dest_row.add_suffix(browse_btn)
    action_group.add(win.audio_dest_row)

    win.extract_btn = Gtk.Button(
        label="Extract Audio",
        halign=Gtk.Align.END,
        css_classes=["suggested-action"],
        margin_top=8,
        margin_bottom=8,
    )
    win.extract_btn.connect("clicked", lambda _b: win._start_extract_audio())
    action_group.add(win.extract_btn)

    page.add(action_group)
    return page
