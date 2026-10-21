"""
Centralized option and preset validation engine for media_toolbox.

Enforces parameter boundaries, preset capability constraints, codec compatibility,
stream presence, and container compatibility before FFmpeg command construction or execution.

INVARIANT: Strict zero GUI imports (gi, Gtk, Adw, Nautilus, tkinter, PyQt, PySide).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from media_toolbox.core.models import EncodeOptions, MediaInfo, ResolvedJobSpec
from media_toolbox.core.presets import (
    AUDIO_PRESETS,
    VALID_SPEED_PRESETS,
    VIDEO_PRESETS,
    _PRESET_ALIASES,
    is_speed_preset,
)


def normalize_preset_name(preset_str: Optional[str]) -> Optional[str]:
    """Resolve preset alias to its canonical registered name."""
    if not preset_str:
        return None
    raw = preset_str.strip().lower()
    return _PRESET_ALIASES.get(raw, raw)


def resolve_job_spec(
    options: EncodeOptions,
    media_info: Optional[MediaInfo] = None,
    output_path: Optional[str | Path] = None,
) -> ResolvedJobSpec:
    """
    Produce a canonical, unified encoding specification from options and metadata.
    """
    canon_preset = normalize_preset_name(options.preset)
    is_audio_op = options.extract_audio or (canon_preset is not None and canon_preset in AUDIO_PRESETS)
    operation = "extract_audio" if is_audio_op else "transcode"

    # Canonical preset resolution
    v_preset = None
    if not is_audio_op:
        if canon_preset and canon_preset in VIDEO_PRESETS:
            v_preset = VIDEO_PRESETS[canon_preset]
        elif options.video_codec:
            canon_codec = normalize_preset_name(options.video_codec)
            if canon_codec and canon_codec in VIDEO_PRESETS:
                v_preset = VIDEO_PRESETS[canon_codec]

    ext = Path(output_path).suffix.lower().lstrip(".") if output_path else None

    a_preset = None
    if canon_preset and canon_preset in AUDIO_PRESETS:
        a_preset = AUDIO_PRESETS[canon_preset]
    elif options.audio_codec:
        canon_acodec = normalize_preset_name(options.audio_codec)
        if canon_acodec and canon_acodec in AUDIO_PRESETS:
            a_preset = AUDIO_PRESETS[canon_acodec]
    elif is_audio_op and ext:
        canon_ext = normalize_preset_name(ext)
        if canon_ext and canon_ext in AUDIO_PRESETS:
            a_preset = AUDIO_PRESETS[canon_ext]

    # Effective codecs
    effective_vcodec = (
        v_preset.codec_name
        if v_preset
        else (options.video_codec if not is_audio_op else None)
    )

    if options.mute_audio:
        effective_acodec = None
    elif is_audio_op:
        if a_preset:
            effective_acodec = a_preset.codec_name
        elif options.audio_codec:
            effective_acodec = options.audio_codec
        elif options.video_codec in ("mp3", "aac", "opus", "flac"):
            effective_acodec = options.video_codec
        else:
            effective_acodec = "mp3"
    else:
        req_audio = options.audio_codec.strip().lower() if options.audio_codec else None
        is_webm = ext == "webm" or (v_preset is not None and v_preset.name == "vp9")
        if is_webm:
            effective_acodec = "libvorbis" if req_audio in ("vorbis", "libvorbis") else "libopus"
        elif options.audio_codec:
            effective_acodec = options.audio_codec
        elif v_preset and v_preset.default_audio_codec:
            effective_acodec = v_preset.default_audio_codec
        else:
            effective_acodec = "aac"

    # Rate mode
    if is_audio_op:
        rate_mode = "extract_audio"
    elif (v_preset and v_preset.codec_name == "gif") or options.video_codec == "gif":
        rate_mode = "gif"
    elif (v_preset and v_preset.codec_name == "prores_ks") or options.video_codec == "prores_ks":
        rate_mode = "prores"
    elif options.two_pass or options.target_size_mb is not None:
        rate_mode = "target_size"
    else:
        rate_mode = "crf"

    # Stream indices
    video_idx = media_info.primary_video.index if (media_info and media_info.primary_video) else None
    audio_idx = media_info.primary_audio.index if (media_info and media_info.primary_audio) else None

    return ResolvedJobSpec(
        operation=operation,
        rate_mode=rate_mode,
        video_codec=effective_vcodec,
        audio_codec=effective_acodec,
        video_preset_name=v_preset.name if v_preset else None,
        audio_preset_name=a_preset.name if a_preset else None,
        video_stream_index=video_idx,
        audio_stream_index=audio_idx,
        container_extension=ext,
        crf=options.crf,
        target_size_mb=options.target_size_mb,
        two_pass=options.two_pass,
    )


def validate_encode_options(
    options: EncodeOptions,
    media_info: Optional[MediaInfo] = None,
    output_path: Optional[str | Path] = None,
) -> ResolvedJobSpec:
    """
    Validate encoding options against codec metadata, stream layout, and sanity bounds.

    Args:
        options: EncodeOptions to validate.
        media_info: Optional probed MediaInfo for input stream checks.
        output_path: Optional destination path for container compatibility checks.

    Returns:
        ResolvedJobSpec: Canonical resolved parameters.

    Raises:
        ValueError: On unknown presets, contradictory options, unsupported rate modes,
                    out-of-range numeric parameters, missing required streams, or container mismatches.
    """
    canon_preset = normalize_preset_name(options.preset)

    if options.preset:
        if (
            canon_preset not in VIDEO_PRESETS
            and canon_preset not in AUDIO_PRESETS
            and not is_speed_preset(options.preset)
        ):
            valid_keys = sorted(
                list(VIDEO_PRESETS.keys())
                + list(AUDIO_PRESETS.keys())
                + list(VALID_SPEED_PRESETS)
            )
            raise ValueError(
                f"Unknown preset: '{options.preset}'. Available presets: {valid_keys}"
            )

    # Resolve pure specification
    spec = resolve_job_spec(options, media_info=media_info, output_path=output_path)

    v_preset = VIDEO_PRESETS.get(spec.video_preset_name) if spec.video_preset_name else None
    a_preset = AUDIO_PRESETS.get(spec.audio_preset_name) if spec.audio_preset_name else None

    # Contradictory options
    if (options.extract_audio or (canon_preset is not None and canon_preset in AUDIO_PRESETS)) and options.mute_audio:
        raise ValueError("Cannot simultaneously extract and mute audio")

    # Duration check for bitrate targeting
    if (options.two_pass or options.target_size_mb is not None) and media_info is not None and media_info.duration <= 0.0:
        raise ValueError("Cannot calculate target bitrate: media duration is zero or unknown")

    # Required stream checks against probed input media
    if spec.operation == "extract_audio":
        if media_info is not None and not media_info.has_audio:
            raise ValueError("Cannot extract audio: input media contains no audio streams")
        if options.target_size_mb is not None:
            raise ValueError("Target size bitrate targeting is not supported for audio extraction")
        if options.two_pass:
            raise ValueError("Two-pass encoding is not supported for audio extraction")
    else:
        if media_info is not None and not media_info.has_video:
            raise ValueError("Cannot transcode video: input media contains no video stream")

    # Mode 1: ProRes capability constraints
    if spec.rate_mode == "prores":
        if options.two_pass:
            raise ValueError("Two-pass encoding is not supported for ProRes preset")
        if options.target_size_mb is not None:
            raise ValueError("Target size bitrate targeting is not supported for ProRes preset")
        if options.crf is not None:
            raise ValueError("CRF rate control is not supported for ProRes preset (uses profile)")

    # Mode 2: GIF capability constraints
    if spec.rate_mode == "gif":
        if options.two_pass:
            raise ValueError("Two-pass encoding is not supported for GIF preset")
        if options.target_size_mb is not None:
            raise ValueError("Target size bitrate targeting is not supported for GIF preset")
        if options.crf is not None:
            raise ValueError("CRF rate control is not supported for GIF preset")

    # Mode 3: CRF boundaries (enforced on resolved preset even if requested via codec)
    if options.crf is not None:
        if v_preset is not None and v_preset.crf_range is not None:
            min_crf, max_crf = v_preset.crf_range
            if not (min_crf <= options.crf <= max_crf):
                raise ValueError(
                    f"CRF value {options.crf} out of valid range ({min_crf}-{max_crf}) for preset '{v_preset.name}'"
                )
        elif not (0 <= options.crf <= 63):
            raise ValueError(f"CRF value {options.crf} out of valid range (0-63)")

    # Mode 4: Numeric parameters sanity
    if options.speed is not None:
        if not math.isfinite(options.speed) or options.speed <= 0:
            raise ValueError(f"Speed multiplier must be positive, got {options.speed}")

    if options.target_size_mb is not None:
        if not math.isfinite(options.target_size_mb) or options.target_size_mb <= 0:
            raise ValueError(f"target_size_mb must be positive, got {options.target_size_mb}")

    if options.audio_bitrate_kbps is not None:
        if options.audio_bitrate_kbps <= 0 or options.audio_bitrate_kbps > 2000:
            raise ValueError(
                f"Audio bitrate must be between 8 and 2000 kbps, got {options.audio_bitrate_kbps}"
            )

    if options.volume_boost_db is not None:
        if not math.isfinite(options.volume_boost_db) or not (-60.0 <= options.volume_boost_db <= 60.0):
            raise ValueError(
                f"Volume boost must be finite and between -60 and +60 dB, got {options.volume_boost_db}"
            )

    # Mode 5: Container extension compatibility
    if output_path is not None:
        ext = spec.container_extension
        if ext:
            if spec.operation == "extract_audio" and a_preset is not None and a_preset.compatible_extensions:
                if ext not in a_preset.compatible_extensions:
                    raise ValueError(
                        f"Incompatible output extension '.{ext}' for preset '{a_preset.name}'. "
                        f"Supported extensions: {a_preset.compatible_extensions}"
                    )
            elif spec.operation != "extract_audio" and v_preset is not None and v_preset.compatible_extensions:
                if ext not in v_preset.compatible_extensions:
                    raise ValueError(
                        f"Incompatible output extension '.{ext}' for preset '{v_preset.name}'. "
                        f"Supported extensions: {v_preset.compatible_extensions}"
                    )

    return spec

