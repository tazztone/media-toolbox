"""
Deterministic FFmpeg CLI command builder for media_toolbox.

This module provides the central command line construction engine for media_toolbox,
assembling fully-qualified FFmpeg invocations for:
- Single-pass CRF video encoding
- Two-pass bitrate targeting (Pass 1 null sink and Pass 2 final output)
- Standalone audio extraction and transcoding
- Two-stage animated GIF generation via palettegen / paletteuse

INVARIANT: Must have ZERO imports from GUI toolkits (gi, Gtk, Adw, etc.).
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Optional

from media_toolbox.core.bitrate import calculate_target_video_bitrate
from media_toolbox.core.filtergraph import (
    build_audio_filter,
    build_audio_filter_args,
    build_video_filter,
    build_video_filter_args,
)
from media_toolbox.core.models import EncodeOptions, MediaInfo, ResolvedJobSpec
from media_toolbox.core.presets import (
    AUDIO_PRESETS,
    VIDEO_PRESETS,
    get_audio_preset,
    get_container_faststart_args,
    is_audio_preset,
    is_speed_preset,
)
from media_toolbox.core.probe import probe_media
from media_toolbox.core.validation import resolve_job_spec, validate_encode_options


def resolve_speed_preset(options: EncodeOptions) -> Optional[str]:
    """
    Resolve valid FFmpeg encoder speed preset from EncodeOptions.
    Only returns recognized speed presets, or None.
    """
    sp = getattr(options, "speed_preset", None) or options.preset
    return sp.strip().lower() if sp and is_speed_preset(sp) else None


def has_stream_map(extra_args: tuple[str, ...]) -> bool:
    """Return True if extra_args contains stream mapping arguments (-map)."""
    i = 0
    while i < len(extra_args):
        arg = extra_args[i]
        if arg == "-map":
            return True
        if arg.startswith("-map:") or (
            arg.startswith("-map")
            and not arg.startswith(("-map_metadata", "-map_chapters"))
        ):
            return True
        i += 1
    return False


def extract_user_stream_maps(extra_args: tuple[str, ...]) -> list[str]:
    """Extract stream mapping arguments from extra_args for forwarding to pass 1."""
    maps: list[str] = []
    i = 0
    while i < len(extra_args):
        arg = extra_args[i]
        if arg == "-map":
            if i + 1 < len(extra_args):
                maps.extend(["-map", extra_args[i + 1]])
                i += 2
                continue
        elif arg.startswith("-map:") or (
            arg.startswith("-map")
            and not arg.startswith(("-map_metadata", "-map_chapters"))
        ):
            maps.append(arg)
        i += 1
    return maps


def resolve_stream_mappings(
    media_info: Optional[MediaInfo],
) -> tuple[str, str]:
    """
    Resolve deterministic video and audio stream mapping identifiers.
    Prioritizes primary non-attached-picture video when cover art is present.
    """
    if media_info and media_info.attached_pics and media_info.primary_video:
        v_map = f"0:{media_info.primary_video.index}"
    else:
        v_map = "0:v:0"
    a_map = "0:a:0?"
    return v_map, a_map


def build_audio_extract_command(
    input_path: str,
    output_path: str,
    options: EncodeOptions,
    media_info: Optional[MediaInfo] = None,
    include_progress: bool = False,
    spec: Optional[ResolvedJobSpec] = None,
) -> list[str]:
    """
    Construct FFmpeg command for audio extraction / transcoding.
    """
    if spec is None:
        spec = resolve_job_spec(options, media_info=media_info, output_path=output_path)

    cmd: list[str] = ["ffmpeg", "-y", "-nostdin"]
    if include_progress:
        cmd.extend(["-progress", "pipe:1", "-nostats"])

    has_user_map = has_stream_map(options.extra_args)
    if not has_user_map:
        _, a_map = resolve_stream_mappings(media_info)
        cmd.extend(["-i", input_path, "-vn", "-map", a_map])
    else:
        cmd.extend(["-i", input_path, "-vn"])

    # Audio filters
    cmd.extend(
        build_audio_filter_args(
            speed=options.speed,
            normalize_loudness=options.normalize_audio,
            volume_boost_db=options.volume_boost_db,
        )
    )

    # Resolve audio preset / codec
    audio_preset = AUDIO_PRESETS.get(spec.audio_preset_name) if spec.audio_preset_name else None
    if audio_preset is None:
        out_ext = Path(output_path).suffix.lstrip(".").lower()
        if is_audio_preset(out_ext):
            audio_preset = get_audio_preset(out_ext)

    if audio_preset is not None:
        cmd.extend(audio_preset.build_audio_args(bitrate_kbps=options.audio_bitrate_kbps, extract_audio=False))
    else:
        codec = spec.audio_codec or options.audio_codec or "aac"
        cmd.extend(["-c:a", codec, "-b:a", f"{options.audio_bitrate_kbps}k"])

    cmd.extend(options.extra_args)
    cmd.append(output_path)
    return cmd


def build_gif_command(
    input_path: str,
    output_path: str,
    options: EncodeOptions,
    media_info: Optional[MediaInfo] = None,
    include_progress: bool = False,
) -> list[str]:
    """
    Construct FFmpeg command for paletted animated GIF generation.
    """
    cmd: list[str] = ["ffmpeg", "-y", "-nostdin"]
    if include_progress:
        cmd.extend(["-progress", "pipe:1", "-nostats"])

    cmd.extend(["-i", input_path])

    vf = build_video_filter(
        scale=options.scale,
        crop=options.crop,
        pad=options.pad,
        speed=options.speed,
        fps=options.fps,
    )

    v_label = (
        f"0:{media_info.primary_video.index}"
        if (media_info and media_info.attached_pics and media_info.primary_video)
        else "0:v"
    )

    if vf:
        filter_spec = f"[{v_label}]{','.join(vf)},split[a][b];[a]palettegen[p];[b][p]paletteuse"
    else:
        filter_spec = f"[{v_label}]split[a][b];[a]palettegen[p];[b][p]paletteuse"

    cmd.extend(["-filter_complex", filter_spec, "-an"])

    if not output_path.lower().endswith(".gif"):
        cmd.extend(["-f", "gif"])

    cmd.extend(options.extra_args)
    cmd.append(output_path)
    return cmd


def build_two_pass_commands(
    input_path: str,
    output_path: str,
    options: EncodeOptions,
    media_info: Optional[MediaInfo] = None,
    pass_logfile: Optional[str] = None,
    include_progress: bool = False,
    spec: Optional[ResolvedJobSpec] = None,
) -> list[list[str]]:
    """
    Construct two FFmpeg commands for two-pass bitrate targeting.
    Pass 1 writes statistics to null sink with audio disabled.
    Pass 2 encodes final output file with identical video filters.
    """
    if spec is None:
        spec = resolve_job_spec(options, media_info=media_info, output_path=output_path)

    if media_info is None:
        if os.path.exists(input_path):
            media_info = probe_media(input_path)
        else:
            raise ValueError("media_info is required when input file is not on disk")

    duration = media_info.duration
    if duration <= 0:
        raise ValueError(f"Cannot calculate target bitrate: media duration is {duration}")

    # Audio bitrate for math formula
    if options.mute_audio or not media_info.has_audio:
        audio_br = 0
    else:
        audio_br = options.audio_bitrate_kbps

    target_mb = options.target_size_mb if options.target_size_mb is not None else 25.0
    v_bitrate_kbps = calculate_target_video_bitrate(
        target_size_mb=target_mb,
        duration_seconds=duration,
        audio_bitrate_kbps=audio_br,
        speed=options.speed,
    )

    log_prefix = pass_logfile or os.path.join(tempfile.gettempdir(), f"ffmpeg2pass_{os.getpid()}")

    vf_args = build_video_filter_args(
        scale=options.scale,
        crop=options.crop,
        pad=options.pad,
        speed=options.speed,
        fps=options.fps,
    )

    v_preset = VIDEO_PRESETS.get(spec.video_preset_name) if spec.video_preset_name else None
    speed_preset = resolve_speed_preset(options)
    v_map, a_map = resolve_stream_mappings(media_info)
    has_user_map = has_stream_map(options.extra_args)

    # Pass 1 Command
    pass1_cmd: list[str] = ["ffmpeg", "-y", "-nostdin"]
    if include_progress:
        pass1_cmd.extend(["-progress", "pipe:1", "-nostats"])
    pass1_cmd.extend(["-i", input_path])
    if not has_user_map:
        pass1_cmd.extend(["-map", v_map])
    else:
        pass1_cmd.extend(extract_user_stream_maps(options.extra_args))
    pass1_cmd.extend(vf_args)

    if v_preset is not None:
        pass1_cmd.extend(
            v_preset.build_video_args(
                bitrate_kbps=v_bitrate_kbps,
                pass_num=1,
                pass_logfile=log_prefix,
                speed_preset=speed_preset,
            )
        )
    else:
        v_codec = spec.video_codec or options.video_codec or "libx264"
        pass1_cmd.extend([
            "-c:v", v_codec,
            "-b:v", f"{int(v_bitrate_kbps)}k",
        ])
        if v_codec in ("libx265", "x265", "hevc"):
            x265_opts = ["pass=1"]
            if log_prefix:
                x265_opts.append(f"stats={log_prefix}")
            pass1_cmd.extend(["-x265-params", ":".join(x265_opts)])
        else:
            pass1_cmd.extend([
                "-pass", "1",
                "-passlogfile", log_prefix,
            ])
        if speed_preset:
            pass1_cmd.extend(["-preset", speed_preset])

    pass1_cmd.extend(["-an", "-f", "null", os.devnull])

    # Pass 2 Command
    pass2_cmd: list[str] = ["ffmpeg", "-y", "-nostdin"]
    if include_progress:
        pass2_cmd.extend(["-progress", "pipe:1", "-nostats"])
    pass2_cmd.extend(["-i", input_path])
    if not has_user_map:
        pass2_cmd.extend(["-map", v_map])
        if not options.mute_audio and (media_info is None or media_info.has_audio):
            pass2_cmd.extend(["-map", a_map])
    pass2_cmd.extend(vf_args)

    if v_preset is not None:
        pass2_cmd.extend(
            v_preset.build_video_args(
                bitrate_kbps=v_bitrate_kbps,
                pass_num=2,
                pass_logfile=log_prefix,
                speed_preset=speed_preset,
            )
        )
    else:
        v_codec = spec.video_codec or options.video_codec or "libx264"
        pass2_cmd.extend([
            "-c:v", v_codec,
            "-b:v", f"{int(v_bitrate_kbps)}k",
        ])
        if v_codec in ("libx265", "x265", "hevc"):
            x265_opts = ["pass=2"]
            if log_prefix:
                x265_opts.append(f"stats={log_prefix}")
            pass2_cmd.extend(["-x265-params", ":".join(x265_opts)])
        else:
            pass2_cmd.extend([
                "-pass", "2",
                "-passlogfile", log_prefix,
            ])
        if speed_preset:
            pass2_cmd.extend(["-preset", speed_preset])

    # Pass 2 Audio
    if options.mute_audio or not media_info.has_audio:
        pass2_cmd.append("-an")
    else:
        pass2_cmd.extend(
            build_audio_filter_args(
                speed=options.speed,
                normalize_loudness=options.normalize_audio,
                volume_boost_db=options.volume_boost_db,
            )
        )
        a_codec = spec.audio_codec or "aac"
        pass2_cmd.extend(["-c:a", a_codec])
        if not a_codec.startswith("pcm_"):
            pass2_cmd.extend(["-b:a", f"{options.audio_bitrate_kbps}k"])

    if v_preset is not None:
        pass2_cmd.extend(v_preset.build_container_args(output_path))
    else:
        pass2_cmd.extend(get_container_faststart_args(output_path))
    pass2_cmd.extend(options.extra_args)
    pass2_cmd.append(output_path)

    return [pass1_cmd, pass2_cmd]


def build_single_pass_command(
    input_path: str,
    output_path: str,
    options: EncodeOptions,
    media_info: Optional[MediaInfo] = None,
    include_progress: bool = False,
    spec: Optional[ResolvedJobSpec] = None,
) -> list[str]:
    """
    Construct FFmpeg command for single-pass CRF or fixed-bitrate video encoding.
    """
    if spec is None:
        spec = resolve_job_spec(options, media_info=media_info, output_path=output_path)

    cmd: list[str] = ["ffmpeg", "-y", "-nostdin"]
    if include_progress:
        cmd.extend(["-progress", "pipe:1", "-nostats"])

    cmd.extend(["-i", input_path])
    has_user_map = has_stream_map(options.extra_args)
    if not has_user_map:
        v_map, a_map = resolve_stream_mappings(media_info)
        cmd.extend(["-map", v_map])
        if not options.mute_audio and (media_info is None or media_info.has_audio):
            cmd.extend(["-map", a_map])

    # Video filters
    cmd.extend(
        build_video_filter_args(
            scale=options.scale,
            crop=options.crop,
            pad=options.pad,
            speed=options.speed,
            fps=options.fps,
        )
    )

    # Video codec & quality
    v_preset = VIDEO_PRESETS.get(spec.video_preset_name) if spec.video_preset_name else None
    speed_preset = resolve_speed_preset(options)

    if v_preset is not None:
        cmd.extend(v_preset.build_video_args(crf=options.crf, speed_preset=speed_preset))
    else:
        v_codec = spec.video_codec or options.video_codec or "libx264"
        cmd.extend(["-c:v", v_codec])
        if options.crf is not None:
            cmd.extend(["-crf", str(options.crf)])
        if speed_preset:
            cmd.extend(["-preset", speed_preset])

    # Audio handling
    if options.mute_audio or (media_info is not None and not media_info.has_audio):
        cmd.append("-an")
    else:
        cmd.extend(
            build_audio_filter_args(
                speed=options.speed,
                normalize_loudness=options.normalize_audio,
                volume_boost_db=options.volume_boost_db,
            )
        )
        a_codec = spec.audio_codec or "aac"
        cmd.extend(["-c:a", a_codec])
        if not a_codec.startswith("pcm_"):
            cmd.extend(["-b:a", f"{options.audio_bitrate_kbps}k"])

    if v_preset is not None:
        cmd.extend(v_preset.build_container_args(output_path))
    else:
        cmd.extend(get_container_faststart_args(output_path))
    cmd.extend(options.extra_args)
    cmd.append(output_path)

    return cmd


def build_ffmpeg_commands(
    input_path: str | Path,
    output_path: str | Path,
    options: EncodeOptions,
    media_info: Optional[MediaInfo] = None,
    pass_logfile: Optional[str] = None,
    include_progress: bool = False,
) -> list[list[str]]:
    """
    Construct deterministic FFmpeg CLI argument list(s).

    Returns:
        list[list[str]]: 1 command for single-pass/CRF/audio/GIF; 2 commands for 2-pass.

    Raises:
        ValueError: On contradictory options (e.g. mute + extract audio, GIF + two-pass),
                    non-positive speeds/target sizes, or missing duration for bitrate targeting.
    """
    input_str = str(input_path)
    output_str = str(output_path)

    # Centralized validation upfront
    spec = validate_encode_options(options, media_info=media_info, output_path=output_str)

    # Mode 1: Audio Extraction / Audio-Only Presets
    if spec.rate_mode == "extract_audio":
        return [
            build_audio_extract_command(
                input_str,
                output_str,
                options,
                media_info=media_info,
                include_progress=include_progress,
                spec=spec,
            )
        ]

    # Mode 2: Animated GIF
    if spec.rate_mode == "gif":
        return [
            build_gif_command(
                input_str,
                output_str,
                options,
                media_info=media_info,
                include_progress=include_progress,
            )
        ]

    # Mode 3: Two-Pass Bitrate Targeting
    if spec.rate_mode == "target_size":
        return build_two_pass_commands(
            input_path=input_str,
            output_path=output_str,
            options=options,
            media_info=media_info,
            pass_logfile=pass_logfile,
            include_progress=include_progress,
            spec=spec,
        )

    # Mode 4: Single-Pass Video (CRF / ProRes)
    return [
        build_single_pass_command(
            input_path=input_str,
            output_path=output_str,
            options=options,
            media_info=media_info,
            include_progress=include_progress,
            spec=spec,
        )
    ]
