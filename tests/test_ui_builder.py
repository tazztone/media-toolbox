"""Unit test suite for window_builder declarative layout construction.

Tests:
- Complete window UI layout construction (header bar, stacks, status pages, footer)
- Transcode Video preferences page construction (presets, rate control, filters, action buttons)
- Extract Audio preferences page construction (format presets, bitrate, loudness, actions)
- Signal and callback wiring across all interactive controls
"""

# pyright: reportMissingImports=false, reportMissingModuleSource=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportGeneralTypeIssues=false, reportInvalidTypeForm=false

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.desktop]


class SignalMock(MagicMock):
    """Mock widget that captures signal connections and allows triggering them."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.connected_signals: dict[str, list[Callable[..., Any]]] = {}

    def connect(self, signal: str, callback: Callable[..., Any], *args: Any) -> int:
        self.connected_signals.setdefault(signal, []).append(callback)
        return 1

    def trigger(self, signal: str, *args: Any, **kwargs: Any) -> Any:
        callbacks = self.connected_signals.get(signal, [])
        results = [cb(*args, **kwargs) for cb in callbacks]
        return results[0] if results else None


@pytest.fixture
def mock_ui_env():
    """Harness providing mocked GTK, Libadwaita, and custom widgets to run window_builder headlessly."""
    wb = importlib.import_module("media_toolbox.ui.window_builder")

    with (
        patch.object(wb, "Adw") as mock_adw,
        patch.object(wb, "Gtk") as mock_gtk,
        patch.object(wb, "Gio") as mock_gio,
        patch.object(wb, "MetadataCard", side_effect=SignalMock) as mock_meta,
        patch.object(wb, "ProgressFooterWidget", side_effect=SignalMock) as mock_footer,
        patch.object(wb, "RateControlWidget", side_effect=SignalMock) as mock_rate,
        patch.object(wb, "ResolutionWidget", side_effect=SignalMock) as mock_res,
        patch.object(wb, "AudioOptionsWidget", side_effect=SignalMock) as mock_audio,
    ):
        # Configure Adw / Gtk constructors to return SignalMock so .connect works
        mock_adw.HeaderBar.side_effect = SignalMock
        mock_adw.WindowTitle.side_effect = SignalMock
        mock_adw.ToastOverlay.side_effect = SignalMock
        mock_adw.StatusPage.side_effect = SignalMock
        mock_adw.ViewStack.side_effect = SignalMock
        mock_adw.ViewSwitcher.side_effect = SignalMock
        mock_adw.PreferencesPage.side_effect = SignalMock
        mock_adw.PreferencesGroup.side_effect = SignalMock
        mock_adw.ComboRow.side_effect = SignalMock
        mock_adw.ActionRow.side_effect = SignalMock
        mock_adw.SpinRow.side_effect = SignalMock
        mock_adw.SwitchRow.side_effect = SignalMock

        mock_gtk.Button.side_effect = SignalMock
        mock_gtk.Box.side_effect = SignalMock
        mock_gtk.Stack.side_effect = SignalMock
        mock_gtk.ScrolledWindow.side_effect = SignalMock
        mock_gtk.MenuButton.side_effect = SignalMock
        mock_gtk.Adjustment.side_effect = SignalMock
        mock_gtk.StringList.new.side_effect = SignalMock

        mock_gio.Menu.side_effect = SignalMock

        yield {
            "adw": mock_adw,
            "gtk": mock_gtk,
            "gio": mock_gio,
            "meta": mock_meta,
            "footer": mock_footer,
            "rate": mock_rate,
            "res": mock_res,
            "audio": mock_audio,
        }


def _create_mock_window() -> MagicMock:
    return MagicMock()


@pytest.mark.usefixtures("mock_ui_env")
class TestWindowBuilder:
    """Verifies complete declarative UI construction and signal routing."""

    def test_build_window_layout_attaches_expected_widgets(self) -> None:
        import media_toolbox.ui.window_builder as wb

        win = _create_mock_window()
        wb.build_window_layout(win)

        # 1. Verify Top Header Bar
        assert win.header_bar is not None
        assert win.open_btn is not None
        assert win.window_title is not None
        win.header_bar.pack_start.assert_called_with(win.open_btn)
        win.header_bar.set_title_widget.assert_called_with(win.window_title)

        # Trigger open button click signal
        assert isinstance(win.open_btn, SignalMock)
        win.open_btn.trigger("clicked", win.open_btn)
        win.open_file_dialog.assert_called_once()

        # 2. Verify ToastOverlay & Root Layout
        assert win.toast_overlay is not None
        win.set_content.assert_called_with(win.toast_overlay)

        # 3. Verify Main Stack
        assert win.main_stack is not None
        assert win.main_stack.add_named.call_count == 2
        added_names = [call[0][1] for call in win.main_stack.add_named.call_args_list]
        assert "empty" in added_names
        assert "loaded" in added_names

        # 4. Verify Empty State open button
        empty_page = win.main_stack.add_named.call_args_list[0][0][0]
        empty_btn = empty_page.set_child.call_args[0][0]
        assert isinstance(empty_btn, SignalMock)
        win.open_file_dialog.reset_mock()
        empty_btn.trigger("clicked", empty_btn)
        win.open_file_dialog.assert_called_once()

        # 5. Verify Metadata Card and View Stack
        assert win.metadata_card is not None
        assert win.view_stack is not None
        assert win.view_switcher is not None
        assert win.view_stack.add_titled_with_icon.call_count == 2
        tab_names = [
            call[0][1] for call in win.view_stack.add_titled_with_icon.call_args_list
        ]
        assert "transcode" in tab_names
        assert "extract" in tab_names

        # 6. Verify Progress Footer
        assert win.progress_footer is not None

    def test_build_transcode_page_wires_all_controls(self) -> None:
        import media_toolbox.ui.window_builder as wb

        win = _create_mock_window()
        page = wb.build_transcode_page(win)

        assert page is not None

        # Verify widgets attached to window instance
        assert win.video_preset_row is not None
        assert win.rate_widget is not None
        assert win.res_widget is not None
        assert win.crop_row is not None
        assert win.speed_row is not None
        assert win.audio_widget is not None
        assert win.video_dest_row is not None
        assert win.transcode_btn is not None

        # Verify video preset notify signal triggers win._on_video_preset_changed
        assert isinstance(win.video_preset_row, SignalMock)
        win.video_preset_row.trigger("notify::selected", win.video_preset_row, None)
        win._on_video_preset_changed.assert_called_once()

        # Verify rate widget mode notify triggers win._update_default_output_paths
        win.rate_widget.mode_row = SignalMock()
        wb.build_transcode_page(win)
        win.rate_widget.mode_row.trigger("notify::selected")
        win._update_default_output_paths.assert_called_once()

        # Verify transcode button triggers win._start_transcode
        assert isinstance(win.transcode_btn, SignalMock)
        win.transcode_btn.trigger("clicked", win.transcode_btn)
        win._start_transcode.assert_called_once()

        # Verify destination browse button triggers choose_output_destination(is_audio=False)
        browse_btn = win.video_dest_row.add_suffix.call_args[0][0]
        assert isinstance(browse_btn, SignalMock)
        browse_btn.trigger("clicked", browse_btn)
        win.choose_output_destination.assert_called_once_with(is_audio=False)

    def test_build_extract_audio_page_wires_all_controls(self) -> None:
        import media_toolbox.ui.window_builder as wb

        win = _create_mock_window()
        page = wb.build_extract_audio_page(win)

        assert page is not None

        # Verify widgets attached to window instance
        assert win.audio_preset_row is not None
        assert win.extract_bitrate_adj is not None
        assert win.extract_bitrate_row is not None
        assert win.extract_speed_row is not None
        assert win.extract_norm_switch is not None
        assert win.extract_boost_adj is not None
        assert win.extract_boost_row is not None
        assert win.audio_dest_row is not None
        assert win.extract_btn is not None

        # Verify audio preset change signal
        assert isinstance(win.audio_preset_row, SignalMock)
        win.audio_preset_row.trigger("notify::selected", win.audio_preset_row, None)
        win._on_audio_preset_changed.assert_called_once()

        # Verify extract button click signal
        assert isinstance(win.extract_btn, SignalMock)
        win.extract_btn.trigger("clicked", win.extract_btn)
        win._start_extract_audio.assert_called_once()

        # Verify destination browse button triggers choose_output_destination(is_audio=True)
        browse_btn = win.audio_dest_row.add_suffix.call_args[0][0]
        assert isinstance(browse_btn, SignalMock)
        browse_btn.trigger("clicked", browse_btn)
        win.choose_output_destination.assert_called_once_with(is_audio=True)

    def test_build_window_layout_with_mainwindow_spec(self) -> None:
        """Verifies layout construction against a strict MainWindow spec without extra attributes."""
        import media_toolbox.ui.window_builder as wb
        from media_toolbox.ui.window import MainWindow

        win = MagicMock(spec=MainWindow)
        wb.build_window_layout(win)
        assert win.video_preset_row is not None
        assert win.crop_row is not None
        assert win.speed_row is not None
        assert win.audio_preset_row is not None
