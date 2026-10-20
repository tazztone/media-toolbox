"""
Bitrate calculation engine for media_toolbox.

Provides deterministic video bitrate calculation for two-pass encoding
targeting fixed file sizes (using standard decimal Megabytes and FFmpeg decimal kbps),
compensating for container multiplexing overhead, playback speed, and audio allocation.

INVARIANT: Strict zero GUI imports (gi, Gtk, Adw, Nautilus, tkinter, PyQt, PySide).
"""

from __future__ import annotations

import math
from typing import Optional

from media_toolbox.core.models import TargetSizeTooSmallError

DEFAULT_AUDIO_BITRATE_KBPS: int = 128
DEFAULT_MUX_OVERHEAD_MARGIN: float = 0.03  # 3% container safety margin
DEFAULT_MIN_VIDEO_BITRATE_KBPS: int = 64  # Minimum video bitrate floor
KBITS_PER_MB: float = 8000.0  # 1 MB = 1,000,000 bytes * 8 / 1000 = 8000 kbits (decimal)

__all__ = [
    "calculate_target_video_bitrate",
    "DEFAULT_AUDIO_BITRATE_KBPS",
    "DEFAULT_MUX_OVERHEAD_MARGIN",
    "DEFAULT_MIN_VIDEO_BITRATE_KBPS",
    "KBITS_PER_MB",
    "TargetSizeTooSmallError",
]


def calculate_target_video_bitrate(
    target_size_mb: float,
    duration_seconds: float,
    audio_bitrate_kbps: int = DEFAULT_AUDIO_BITRATE_KBPS,
    mux_overhead_margin: float = DEFAULT_MUX_OVERHEAD_MARGIN,
    min_video_bitrate_kbps: int = DEFAULT_MIN_VIDEO_BITRATE_KBPS,
    speed: Optional[float] = None,
    clamp_to_min: bool = False,
) -> int:
    """
    Calculate target video bitrate in kbps for two-pass encoding.

    Formula:
        effective_duration = duration_seconds / speed (if speed provided)
        total_kbits = target_size_mb * 8000.0 (decimal MB)
        usable_kbits = total_kbits * (1.0 - mux_overhead_margin)
        total_bitrate_kbps = usable_kbits / effective_duration
        net_video_bitrate_kbps = total_bitrate_kbps - audio_bitrate_kbps

    Parameters:
        target_size_mb: Desired total output file size in decimal Megabytes (MB).
        duration_seconds: Duration of source media in seconds.
        audio_bitrate_kbps: Allocated audio bitrate in kbps (0 for muted/silent).
        mux_overhead_margin: Safety margin fraction reserved for container overhead (0.0 <= margin < 1.0).
        min_video_bitrate_kbps: Floor video bitrate to prevent unplayable output.
        speed: Playback speed multiplier (changes effective output duration).
        clamp_to_min: If True, clamps unattainable budgets to min_video_bitrate_kbps instead of raising.

    Returns:
        Target video bitrate in kilobits per second (kbps) as an integer.

    Raises:
        ValueError: If duration_seconds or target_size_mb are non-positive or non-finite.
        TargetSizeTooSmallError: If net video bitrate is below min_video_bitrate_kbps and clamp_to_min is False.
    """
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError(f"duration_seconds must be a positive finite number, got {duration_seconds}")

    if not math.isfinite(target_size_mb) or target_size_mb <= 0:
        raise ValueError(f"target_size_mb must be a positive finite number, got {target_size_mb}")

    if audio_bitrate_kbps < 0:
        raise ValueError(f"audio_bitrate_kbps cannot be negative, got {audio_bitrate_kbps}")

    if not (0.0 <= mux_overhead_margin < 1.0):
        raise ValueError(
            f"mux_overhead_margin must be in range [0.0, 1.0), got {mux_overhead_margin}"
        )

    if min_video_bitrate_kbps < 0:
        raise ValueError(f"min_video_bitrate_kbps cannot be negative, got {min_video_bitrate_kbps}")

    eff_duration = duration_seconds
    if speed is not None:
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError(f"speed must be a positive finite number, got {speed}")
        eff_duration = duration_seconds / speed

    total_kbits = float(target_size_mb) * KBITS_PER_MB
    usable_kbits = total_kbits * (1.0 - float(mux_overhead_margin))
    total_bitrate_kbps = usable_kbits / float(eff_duration)

    net_video_bitrate_kbps = total_bitrate_kbps - float(audio_bitrate_kbps)

    if net_video_bitrate_kbps < min_video_bitrate_kbps:
        if clamp_to_min:
            return int(min_video_bitrate_kbps)

        min_kbits_needed = (float(min_video_bitrate_kbps) + float(audio_bitrate_kbps)) * float(eff_duration)
        min_required_total_kbits = min_kbits_needed / (1.0 - float(mux_overhead_margin))
        min_required_mb = round(min_required_total_kbits / KBITS_PER_MB, 2)

        raise TargetSizeTooSmallError(
            target_size_mb=target_size_mb,
            duration_seconds=eff_duration,
            audio_bitrate_kbps=audio_bitrate_kbps,
            min_required_mb=min_required_mb,
            min_video_bitrate_kbps=min_video_bitrate_kbps,
        )

    return int(round(net_video_bitrate_kbps))
