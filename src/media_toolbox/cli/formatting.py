"""
CLI terminal formatting, JSON serialization, and progress reporting utilities.

Zero GUI dependencies: only standard library and media_toolbox.core domain formatters.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from typing import Any

from media_toolbox.core.formatters import (
    format_aspect_ratio,
    format_bitrate,
    format_channels,
    format_duration,
    format_file_size,
    format_fps,
)
from media_toolbox.core.models import MediaInfo, ProgressEvent


def parse_scale_arg(scale_str: str | None) -> tuple[int, int] | None:
    """Parse WIDTHxHEIGHT or WIDTH:HEIGHT scale string into (width, height) tuple."""
    if not scale_str:
        return None
    s = scale_str.strip().lower()
    sep = "x" if "x" in s else (":" if ":" in s else None)
    if not sep:
        raise ValueError(
            f"Invalid scale format '{scale_str}'. Expected WIDTHxHEIGHT or WIDTH:HEIGHT (e.g. 1920x1080, 1280:-2)"
        )
    parts = s.split(sep)
    if len(parts) != 2:
        raise ValueError(
            f"Invalid scale format '{scale_str}'. Expected WIDTHxHEIGHT or WIDTH:HEIGHT"
        )
    try:
        w, h = int(parts[0]), int(parts[1])
        if w <= 0 and h <= 0:
            raise ValueError(
                f"Scale dimensions cannot both be non-positive: {scale_str}"
            )
        if w == 0 or h == 0:
            raise ValueError(f"Scale dimensions cannot be 0: {scale_str}")
        return (w, h)
    except ValueError as e:
        if "Scale dimensions" in str(e) or "Invalid scale format" in str(e):
            raise
        raise ValueError(
            f"Invalid non-integer scale dimensions in '{scale_str}'"
        ) from e


def should_colorize(stream: Any = sys.stdout) -> bool:
    """Return True if stream is a TTY and NO_COLOR is not set in environment."""
    if "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb":
        return False
    return hasattr(stream, "isatty") and stream.isatty()


def media_info_to_dict(media: MediaInfo) -> dict[str, Any]:
    """Serialize MediaInfo dataclass into JSON-serializable dictionary."""
    dur_val = media.duration if media.duration > 0 else media.format.duration
    vid_count = len([s for s in media.video_streams if not s.is_attached_pic])

    v_streams: list[dict[str, Any]] = []
    for s in media.video_streams:
        v_dict = {
            "index": s.index,
            "codec_name": s.codec_name or None,
            "width": s.width,
            "height": s.height,
            "resolution": [s.width, s.height]
            if (s.width > 0 and s.height > 0)
            else None,
            "display_resolution": s.display_resolution
            if (s.width > 0 and s.height > 0)
            else None,
            "effective_resolution": list(s.effective_dimensions)
            if (s.width > 0 and s.height > 0)
            else None,
            "aspect_ratio": format_aspect_ratio(s.width, s.height),
            "aspect_ratio_float": round(s.aspect_ratio, 4)
            if s.aspect_ratio > 0
            else None,
            "pixel_format": s.pix_fmt,
            "fps": s.fps,
            "bit_rate": s.bit_rate,
            "bit_rate_kbps": round(s.bit_rate / 1000)
            if s.bit_rate is not None
            else None,
            "duration": s.duration,
            "duration_formatted": format_duration(s.duration)
            if s.duration is not None
            else None,
            "rotation": s.rotation,
            "is_attached_pic": s.is_attached_pic,
        }
        v_streams.append(v_dict)

    a_streams: list[dict[str, Any]] = []
    for s in media.audio_streams:
        a_dict = {
            "index": s.index,
            "codec_name": s.codec_name or None,
            "channels": s.channels,
            "channel_layout": s.channel_layout,
            "sample_rate": s.sample_rate,
            "sample_rate_khz": s.sample_rate_khz if s.sample_rate > 0 else None,
            "bit_rate": s.bit_rate,
            "bit_rate_kbps": s.bit_rate_kbps,
            "duration": s.duration,
            "duration_formatted": format_duration(s.duration)
            if s.duration is not None
            else None,
        }
        a_streams.append(a_dict)

    return {
        "format": {
            "filename": media.format.filename,
            "format_name": media.format.format_name,
            "duration": media.format.duration,
            "duration_formatted": format_duration(media.format.duration)
            if media.format.duration is not None
            else None,
            "size_bytes": media.format.size_bytes,
            "size_human": format_file_size(media.format.size_bytes),
            "bit_rate": media.format.bit_rate,
            "bit_rate_kbps": media.format.bit_rate_kbps,
        },
        "video_streams": v_streams,
        "audio_streams": a_streams,
        "summary": {
            "resolved_duration": media.duration,
            "duration_formatted": format_duration(dur_val)
            if dur_val is not None and dur_val > 0
            else "N/A",
            "has_video": media.has_video,
            "has_audio": media.has_audio,
            "is_audio_only": media.is_audio_only,
            "is_video_only": media.is_video_only,
            "is_image": media.is_image,
            "video_stream_count": vid_count,
            "audio_stream_count": len(media.audio_streams),
            "attached_pic_count": len(media.attached_pics),
        },
    }


def format_media_info_json(media: MediaInfo, indent: int = 2) -> str:
    """Serialize MediaInfo into formatted JSON string."""
    return json.dumps(media_info_to_dict(media), indent=indent)


def render_media_info_text(media: MediaInfo, use_color: bool = False) -> str:
    """Render human-readable structured terminal output for MediaInfo."""
    bold = "\033[1m" if use_color else ""
    reset = "\033[0m" if use_color else ""
    cyan = "\033[1;36m" if use_color else ""
    green = "\033[32m" if use_color else ""

    lines: list[str] = []

    # Container / File Header
    filename = media.format.filename or "<unknown>"
    lines.append(f"{cyan}[Media: {filename}]{reset}")
    lines.append(f"  {'Container:':<16}{media.format.format_name or 'N/A'}")
    lines.append(f"  {'Size:':<16}{format_file_size(media.format.size_bytes)}")
    dur_val = media.duration if media.duration > 0 else media.format.duration
    dur_str = format_duration(dur_val)
    if media.is_image:
        dur_str += " (still image)"
    lines.append(f"  {'Duration:':<16}{dur_str}")
    lines.append(f"  {'Total Bitrate:':<16}{format_bitrate(media.format.bit_rate)}")

    badges: list[str] = []
    if media.is_image:
        badges.append("[Still Image]")
    elif media.is_audio_only:
        badges.append("[Audio Only]")
    elif media.is_video_only:
        badges.append("[Silent Video]")
    if badges:
        lines.append(f"  {'Type:':<16}{green}{' '.join(badges)}{reset}")

    # Video Stream(s)
    if media.video_streams:
        for s in media.video_streams:
            lines.append("")
            tag = (
                " (Cover Art)"
                if s.is_attached_pic
                else (" (Still Image)" if media.is_image else "")
            )
            lines.append(f"{bold}[Video Stream #{s.index}{tag}]{reset}")
            lines.append(f"  {'Codec:':<16}{s.codec_name or 'N/A'}")
            res_str = (
                f"{s.width}x{s.height}" if (s.width > 0 and s.height > 0) else "N/A"
            )
            if s.rotation != 0:
                res_str += f" (effective: {s.effective_dimensions[0]}x{s.effective_dimensions[1]} @ {s.rotation}°)"
            lines.append(f"  {'Resolution:':<16}{res_str}")
            lines.append(
                f"  {'Aspect Ratio:':<16}{format_aspect_ratio(s.width, s.height)}"
            )
            lines.append(f"  {'Pixel Format:':<16}{s.pix_fmt or 'N/A'}")
            lines.append(f"  {'Frame Rate:':<16}{format_fps(s.fps, s.is_attached_pic)}")
            lines.append(f"  {'Bitrate:':<16}{format_bitrate(s.bit_rate)}")
            lines.append(f"  {'Duration:':<16}{format_duration(s.duration)}")
    elif not media.is_audio_only:
        lines.append("")
        lines.append(f"{bold}[Video Streams]{reset}")
        lines.append("  (No video streams)")

    # Audio Stream(s)
    if media.audio_streams:
        for s in media.audio_streams:
            lines.append("")
            lines.append(f"{bold}[Audio Stream #{s.index}]{reset}")
            lines.append(f"  {'Codec:':<16}{s.codec_name or 'N/A'}")
            lines.append(
                f"  {'Channels:':<16}{format_channels(s.channel_layout, s.channels)}"
            )
            sr_str = (
                f"{s.sample_rate:,} Hz ({s.sample_rate_khz:.1f} kHz)"
                if s.sample_rate > 0
                else "N/A"
            )
            lines.append(f"  {'Sample Rate:':<16}{sr_str}")
            lines.append(f"  {'Bitrate:':<16}{format_bitrate(s.bit_rate)}")
            lines.append(f"  {'Duration:':<16}{format_duration(s.duration)}")
    elif not media.is_image and not media.is_video_only:
        lines.append("")
        lines.append(f"{bold}[Audio Streams]{reset}")
        lines.append("  (No audio streams)")

    # Streams Summary
    lines.append("")
    lines.append(f"{bold}[Streams Summary]{reset}")
    vid_count = len([s for s in media.video_streams if not s.is_attached_pic])
    lines.append(f"  {'Video Streams:':<16}{vid_count}")
    lines.append(f"  {'Audio Streams:':<16}{len(media.audio_streams)}")
    lines.append(f"  {'Attachments:':<16}{len(media.attached_pics)}")

    return "\n".join(lines)


def create_progress_reporter(
    quiet: bool = False,
) -> Callable[[ProgressEvent], None] | None:
    """Create terminal progress callback handling TTY carriage return or non-TTY logging."""
    if quiet:
        return None

    is_tty = sys.stdout.isatty()
    last_pct = -1.0

    def _reporter(evt: ProgressEvent) -> None:
        nonlocal last_pct
        if is_tty:
            bar_len = 20
            pct = max(0.0, min(100.0, evt.percentage))
            filled = round(bar_len * (pct / 100.0))
            bar = "=" * max(0, filled - 1) + (
                ">"
                if filled > 0 and filled < bar_len
                else ("=" if filled == bar_len else "")
            )
            bar_str = f"[{bar:<{bar_len}}]"
            size_mb = (
                (evt.total_size_bytes / (1024 * 1024)) if evt.total_size_bytes else 0.0
            )
            line = f"\r{bar_str} {pct:5.1f}% | Speed: {evt.speed_str:<6} | ETA: {evt.eta_str:<8} | Size: {size_mb:6.1f} MB"
            sys.stdout.write(line)
            sys.stdout.flush()
            if evt.is_completed:
                sys.stdout.write("\n")
                sys.stdout.flush()
        else:
            if int(evt.percentage / 10) > int(last_pct / 10) or evt.is_completed:
                last_pct = evt.percentage
                sys.stdout.write(
                    f"Progress: {evt.percentage:5.1f}% (ETA: {evt.eta_str})\n"
                )
                sys.stdout.flush()

    return _reporter
