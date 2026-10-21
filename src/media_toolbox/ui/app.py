"""
Libadwaita / GTK4 Application entrypoint and lifecycle manager for media_toolbox.
"""

# pyright: reportMissingImports=false, reportMissingModuleSource=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportGeneralTypeIssues=false, reportInvalidTypeForm=false

from __future__ import annotations

import os
import sys
from typing import Any, Optional, Sequence

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gio, Gtk

    _GUI_AVAILABLE = True
    _GUI_IMPORT_ERROR = ""
except (ImportError, ValueError) as _err:
    _GUI_AVAILABLE = False
    _GUI_IMPORT_ERROR = str(_err)
    Adw = Any  # type: ignore[misc,assignment]
    Gdk = Any  # type: ignore[misc,assignment]
    Gio = Any  # type: ignore[misc,assignment]
    Gtk = Any  # type: ignore[misc,assignment]


def has_graphical_display() -> bool:
    """
    Robust verification that a graphical display server (Wayland or X11) is active.
    Prevents GTK initialization segfaults in headless CI or sandbox containers.
    """
    if not _GUI_AVAILABLE:
        return False
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    try:
        if not Gtk.init_check():
            return False
        return Gdk.Display.get_default() is not None
    except Exception:
        return False


_AppBase = Adw.Application if _GUI_AVAILABLE else object


class MediaToolboxApp(_AppBase):  # type: ignore[misc,valid-type]
    """
    Libadwaita desktop application instance.
    Handles startup action registrations, command-line file arguments, and window lifecycle.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            application_id="io.github.tazztone.MediaToolbox",
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
            **kwargs,
        )
        self.window: Any = None
        self._setup_actions()

    def _setup_actions(self) -> None:
        """Register application actions and keyboard accelerators."""
        actions = [
            ("quit", self._on_action_quit, ["<Control>q"]),
            ("open", self._on_action_open, ["<Control>o"]),
            ("about", self._on_action_about, None),
        ]

        for action_name, handler, accels in actions:
            if not self.lookup_action(action_name):
                action = Gio.SimpleAction.new(action_name, None)
                action.connect("activate", handler)
                self.add_action(action)
                if accels:
                    self.set_accels_for_action(f"app.{action_name}", accels)

    def do_startup(self) -> None:
        """Application startup handler."""
        if self.get_is_registered() and Gdk.Display.get_default() is not None:
            super().do_startup()
        self._setup_actions()

    def do_activate(self) -> None:
        """Activate handler for standard desktop launch."""
        if self.window is None:
            from media_toolbox.ui.window import MainWindow

            self.window = MainWindow(application=self)
        self.window.present()

    def do_open(self, files: list[Gio.File], n_files: int, _hint: str) -> None:
        """Handles opening files passed via CLI arguments or file managers."""
        if self.window is None:
            from media_toolbox.ui.window import MainWindow

            self.window = MainWindow(application=self)

        if n_files > 0 and files:
            first_path = files[0].get_path()
            if first_path:
                self.window.load_media_file(first_path)
            if len(files) > 1 and hasattr(self.window, "toast_overlay"):
                ignored_count = len(files) - 1
                s = "s" if ignored_count > 1 else ""
                self.window.toast_overlay.add_toast(
                    Adw.Toast(title=f"Loaded first file. {ignored_count} additional file{s} ignored.")
                )
            self.window.present()

    def _on_action_quit(self, _action: Gio.SimpleAction, _param: Any) -> None:
        win = self.window or self.get_active_window()
        if win and hasattr(win, "close"):
            win.close()
        elif win and hasattr(win, "_on_close_request"):
            if not win._on_close_request():
                self.quit()
        else:
            self.quit()

    def _on_action_open(self, _action: Gio.SimpleAction, _param: Any) -> None:
        win = self.window or self.get_active_window()
        if win and hasattr(win, "open_file_dialog"):
            win.open_file_dialog()

    def _on_action_about(self, _action: Gio.SimpleAction, _param: Any) -> None:
        win = self.window or self.get_active_window()
        from media_toolbox import __version__

        about = Adw.AboutDialog(
            application_name="Media Toolbox",
            application_icon="io.github.tazztone.MediaToolbox",
            developer_name="tazztone",
            version=__version__,
            comments="Modern video & audio transcoding and media inspection toolbox.",
            website="https://github.com/tazztone/media-toolbox",
            issue_url="https://github.com/tazztone/media-toolbox/issues",
            license_type=Gtk.License.APACHE_2_0,
        )
        if win:
            about.present(win)
        else:
            about.present()


def main(argv: Optional[Sequence[str]] = None) -> int:
    """
    Desktop UI entrypoint. Checks for graphical display availability before running.
    """
    if not _GUI_AVAILABLE:
        sys.stderr.write(
            f"Error: Desktop GUI requirements not satisfied: {_GUI_IMPORT_ERROR}\n"
            "Please install desktop dependencies (e.g. 'pip install .[desktop]') and system GTK4 / Libadwaita libraries.\n"
        )
        return 1

    if not has_graphical_display():
        sys.stderr.write(
            "Error: No graphical display server found (Wayland or X11 required).\n"
            "Use 'media_toolbox.cli' for headless operation.\n"
        )
        return 1

    app = MediaToolboxApp()
    if argv is None:
        argv = sys.argv
    return app.run(list(argv))


if __name__ == "__main__":
    sys.exit(main())
