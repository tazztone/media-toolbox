"""
Libadwaita / GTK4 Desktop User Interface package for media_toolbox.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "MediaToolboxApp",
    "MainWindow",
    "main",
    "has_graphical_display",
]


def __getattr__(name: str) -> Any:
    if name in ("MediaToolboxApp", "has_graphical_display", "main"):
        from media_toolbox.ui.app import MediaToolboxApp, has_graphical_display, main

        mapping = {
            "MediaToolboxApp": MediaToolboxApp,
            "has_graphical_display": has_graphical_display,
            "main": main,
        }
        return mapping[name]
    if name == "MainWindow":
        from media_toolbox.ui.window import MainWindow

        return MainWindow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

