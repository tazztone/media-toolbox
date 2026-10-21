"""
UI state enums and preset configurations for Libadwaita application window.
"""

from __future__ import annotations

import enum
from typing import Optional

from media_toolbox.core.presets import list_audio_presets, list_video_presets


class WindowState(enum.Enum):
    EMPTY = "empty"
    PROBING = "probing"
    READY = "ready"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CLOSED = "closed"


VIDEO_PRESETS: list[tuple[str, str]] = [(p.display_name, p.name) for p in list_video_presets()]
AUDIO_PRESETS: list[tuple[str, str]] = [(p.display_name, p.name) for p in list_audio_presets()]

CROP_PRESETS: list[tuple[str, Optional[str]]] = [
    ("None (Original)", None),
    ("16:9 Landscape", "16:9"),
    ("9:16 Portrait / Shorts", "9:16"),
    ("1:1 Square", "1:1"),
    ("4:3 Classic", "4:3"),
    ("21:9 Ultrawide", "21:9"),
]

SPEED_PRESETS: list[tuple[str, float]] = [
    ("1.0x (Normal)", 1.0),
    ("0.5x (Half Speed)", 0.5),
    ("0.75x", 0.75),
    ("1.25x", 1.25),
    ("1.5x", 1.5),
    ("2.0x (Double Speed)", 2.0),
]
