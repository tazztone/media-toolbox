"""
Formatting utilities for human-readable media properties and metrics.

INVARIANT: Must have ZERO imports from GUI toolkits (gi, Gtk, Adw, etc.).
"""

from __future__ import annotations

import math
from typing import Optional

__all__ = [
    "format_duration",
    "format_file_size",
    "format_decimal_size",
    "format_bitrate",
    "format_aspect_ratio",
    "format_fps",
    "format_channels",
]


def format_duration(seconds: Optional[float]) -> str:
    """Format duration in seconds as HH:MM:SS.ff, or 'N/A' if unknown."""
    if seconds is None or seconds < 0:
        return "N/A"
    mins, secs = divmod(seconds, 60.0)
    hours, mins = divmod(int(mins), 60)
    return f"{hours:02d}:{mins:02d}:{secs:05.2f}"


def format_file_size(size_bytes: Optional[int], binary: bool = True) -> str:
    """
    Format byte size into scaled units with exact byte count.

    If binary=True (default), uses IEC binary units (B, KiB, MiB, GiB, TiB) with base 1024.
    If binary=False, uses SI decimal units (B, KB, MB, GB, TB) with base 1000.
    """
    if size_bytes is None or size_bytes < 0:
        return "N/A"
    if binary:
        units = ["B", "KiB", "MiB", "GiB", "TiB"]
        base = 1024.0
    else:
        units = ["B", "KB", "MB", "GB", "TB"]
        base = 1000.0

    val = float(size_bytes)
    idx = 0
    while val >= base and idx < len(units) - 1:
        val /= base
        idx += 1
    if idx == 0:
        return f"{int(val)} B"
    return f"{val:.2f} {units[idx]} ({size_bytes:,} bytes)"


def format_decimal_size(size_bytes: Optional[int]) -> str:
    """Format byte size using decimal SI units (KB, MB, GB; base 1000)."""
    return format_file_size(size_bytes, binary=False)


def format_bitrate(bps: Optional[int]) -> str:
    """Format bitrate in bps to kbps (and Mbps if >= 1,000,000 bps)."""
    if bps is None or bps <= 0:
        return "N/A"
    kbps = round(bps / 1000)
    if bps >= 1_000_000:
        return f"{kbps:,} kbps ({bps / 1_000_000:.2f} Mbps)"
    return f"{kbps:,} kbps"


def format_aspect_ratio(width: int, height: int) -> str:
    """Calculate and format aspect ratio (e.g. '16:9 (1.78:1)')."""
    if width <= 0 or height <= 0:
        return "N/A"
    g = math.gcd(width, height)
    rw, rh = width // g, height // g
    ratio = width / height
    if rw <= 32 and rh <= 32:
        return f"{rw}:{rh} ({ratio:.2f}:1)"
    return f"{ratio:.2f}:1"


def format_fps(fps: Optional[float], is_attached_pic: bool = False) -> str:
    """Format frame rate in fps, handling still pictures and fractional fps."""
    if is_attached_pic:
        return "N/A (still picture)"
    if fps is None or fps <= 0:
        return "N/A"
    if fps.is_integer():
        return f"{int(fps)} fps"
    return f"{fps:.2f} fps"


def format_channels(layout: Optional[str], channels: int) -> str:
    """Format channel count and layout with proper pluralization."""
    ch_word = "channel" if channels == 1 else "channels"
    if layout:
        return f"{layout} ({channels} {ch_word})"
    return f"{channels} {ch_word}"
