"""Unit and integration test suite for Libadwaita app lifecycle and environment.

Tests:
- Environment & Headless Compatibility (Gtk.init_check, display detection, graceful CLI fallback)
- MediaToolboxApp instantiation, application ID, actions, and file opening
"""

# pyright: reportMissingImports=false, reportMissingModuleSource=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportGeneralTypeIssues=false, reportInvalidTypeForm=false

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.ui_test_helpers import (
    get_gi_modules,
)

pytestmark = [pytest.mark.desktop]


# ---------------------------------------------------------------------------
# 1. Environment & Headless Compatibility Tests
# ---------------------------------------------------------------------------


class TestDisplayEnvironment:
    """Tests display detection, headless fallback, and CLI router coordination."""

    def test_has_graphical_display_true_when_display_connected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify has_graphical_display returns True when valid display is found."""
        _, _, Gdk, _, _, _ = get_gi_modules()
        from media_toolbox.ui.app import has_graphical_display

        monkeypatch.setenv("DISPLAY", ":0")
        with patch.object(Gdk.Display, "get_default", return_value=MagicMock()):
            assert has_graphical_display() is True

    def test_has_graphical_display_false_when_no_display_vars(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify has_graphical_display returns False if neither DISPLAY nor WAYLAND_DISPLAY are set."""
        from media_toolbox.ui.app import has_graphical_display

        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        assert has_graphical_display() is False

    def test_has_graphical_display_false_when_gdk_display_is_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify has_graphical_display returns False if env vars exist but Gdk.Display is None (e.g. sandbox)."""
        _, _, Gdk, _, _, _ = get_gi_modules()
        from media_toolbox.ui.app import has_graphical_display

        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        with patch.object(Gdk.Display, "get_default", return_value=None):
            assert has_graphical_display() is False

    def test_app_main_cli_fallback_when_headless(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Verify media_toolbox.ui.app.main exits with 1 and prints warning when headless."""
        from media_toolbox.ui import app

        monkeypatch.setattr(app, "has_graphical_display", lambda: False)
        exit_code = app.main([])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "No graphical display" in captured.err

    def test_app_main_exits_when_gui_libraries_missing(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Verify media_toolbox.ui.app.main exits with 1 and prints friendly warning when PyGObject is missing."""
        from media_toolbox.ui import app

        monkeypatch.setattr(app, "_GUI_AVAILABLE", False)
        monkeypatch.setattr(app, "_GUI_IMPORT_ERROR", "No module named 'gi'")
        exit_code = app.main([])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Desktop GUI requirements not satisfied" in captured.err

    def test_app_main_launches_when_display_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify media_toolbox.ui.app.main calls app.run when display is available."""
        from media_toolbox.ui import app

        monkeypatch.setattr(app, "has_graphical_display", lambda: True)
        mock_app = MagicMock()
        mock_app.run.return_value = 0
        monkeypatch.setattr(app, "MediaToolboxApp", lambda: mock_app)
        assert app.main(["app"]) == 0
        mock_app.run.assert_called_once_with(["app"])


# ---------------------------------------------------------------------------
# 2. MediaToolboxApp Lifecycle Tests
# ---------------------------------------------------------------------------


class TestMediaToolboxApp:
    """Tests Adw.Application subclass properties, flags, and open-file dispatch."""

    @pytest.mark.usefixtures("gi_env")
    def test_app_instantiation_and_id(self) -> None:
        """Verify app instantiates headlessly with correct application_id."""
        from media_toolbox.ui.app import MediaToolboxApp

        app = MediaToolboxApp()
        assert app.get_application_id() == "io.github.tazztone.MediaToolbox"

    def test_app_flags_handles_open(self, gi_env) -> None:
        """Verify app defines HANDLES_OPEN flag for CLI and Nautilus integration."""
        _, _, _, _, Gio, _ = gi_env
        from media_toolbox.ui.app import MediaToolboxApp

        app = MediaToolboxApp()
        assert app.get_flags() & Gio.ApplicationFlags.HANDLES_OPEN

    @pytest.mark.usefixtures("gi_env")
    def test_app_startup_installs_actions(self) -> None:
        """Verify startup installs 'quit', 'open', and 'about' GActions."""
        from media_toolbox.ui.app import MediaToolboxApp

        app = MediaToolboxApp()
        app.do_startup()
        assert app.lookup_action("quit") is not None
        assert app.lookup_action("open") is not None
        assert app.lookup_action("about") is not None

    @pytest.mark.usefixtures("gi_env")
    def test_app_activate_presents_window(self) -> None:
        """Verify do_activate presents window."""
        from media_toolbox.ui.app import MediaToolboxApp

        app = MediaToolboxApp()
        mock_win = MagicMock()
        app.window = mock_win
        app.do_activate()
        mock_win.present.assert_called_once()

    def test_app_do_open_routes_file_to_window(self, gi_env, tmp_path: Path) -> None:
        """Verify passing a file to do_open delegates to window.load_media_files."""
        _, _, _, _, Gio, _ = gi_env
        from media_toolbox.ui.app import MediaToolboxApp

        app = MediaToolboxApp()
        mock_win = MagicMock()
        app.window = mock_win

        test_file = tmp_path / "test.mp4"
        test_file.touch()
        gfile = Gio.File.new_for_path(str(test_file))

        app.do_open([gfile], 1, "")
        mock_win.load_media_files.assert_called_once_with([test_file])
        mock_win.present.assert_called_once()

    @pytest.mark.usefixtures("gi_env")
    def test_app_do_open_empty_files_noop(self) -> None:
        """Verify do_open handles empty file list without error."""
        from media_toolbox.ui.app import MediaToolboxApp

        app = MediaToolboxApp()
        mock_win = MagicMock()
        app.window = mock_win

        app.do_open([], 0, "")
        mock_win.load_media_files.assert_not_called()

    def test_app_do_open_multiple_files_delegates_to_batch_queue(
        self, gi_env, tmp_path: Path
    ) -> None:
        """Verify passing multiple files passes full sequence to load_media_files."""
        _, _, _, _, Gio, _ = gi_env
        from media_toolbox.ui.app import MediaToolboxApp

        app = MediaToolboxApp()
        mock_win = MagicMock()
        app.window = mock_win

        file1 = tmp_path / "first.mp4"
        file1.touch()
        file2 = tmp_path / "second.mp4"
        file2.touch()

        gfile1 = Gio.File.new_for_path(str(file1))
        gfile2 = Gio.File.new_for_path(str(file2))

        app.do_open([gfile1, gfile2], 2, "")
        mock_win.load_media_files.assert_called_once_with([file1, file2])
        mock_win.present.assert_called_once()

    @pytest.mark.usefixtures("gi_env")
    def test_app_action_about_dialog(self) -> None:
        """Verify _on_action_about presents AboutDialog with parent window."""
        import media_toolbox.ui.app as app_mod
        from media_toolbox.ui.app import MediaToolboxApp

        app = MediaToolboxApp()
        mock_win = MagicMock()
        app.window = mock_win

        mock_dialog_instance = MagicMock()
        mock_dialog_cls = MagicMock(return_value=mock_dialog_instance)

        with patch.object(app_mod.Adw, "AboutDialog", mock_dialog_cls, create=True):
            app._on_action_about(MagicMock(), None)
            mock_dialog_instance.present.assert_called_once_with(mock_win)

    @pytest.mark.usefixtures("gi_env")
    def test_app_action_about_window_fallback(self) -> None:
        """Verify _on_action_about fallback presents AboutWindow transient for parent."""
        import media_toolbox.ui.app as app_mod
        from media_toolbox.ui.app import MediaToolboxApp

        app = MediaToolboxApp()
        mock_win = MagicMock()
        app.window = mock_win

        mock_window_instance = MagicMock()
        mock_window_cls = MagicMock(return_value=mock_window_instance)

        # Ensure AboutDialog is absent to trigger AboutWindow fallback
        with (
            patch.object(app_mod.Adw, "AboutDialog", None, create=True),
            patch.object(app_mod.Adw, "AboutWindow", mock_window_cls, create=True),
        ):
            app._on_action_about(MagicMock(), None)
            mock_window_instance.set_transient_for.assert_called_once_with(mock_win)
            mock_window_instance.present.assert_called_once_with()
