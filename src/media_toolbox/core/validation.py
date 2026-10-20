"""
Centralized option and preset validation engine for media_toolbox.

Enforces parameter boundaries, preset capability constraints, codec compatibility,
and container compatibility before FFmpeg command construction or execution.

INVARIANT: Strict zero GUI imports (gi, Gtk, Adw, Nautilus, tkinter, PyQt, PySide).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from media_toolbox.core.models import EncodeOptions, MediaInfo
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


def validate_encode_options(
    options: EncodeOptions,
    media_info: Optional[MediaInfo] = None,
    output_path: Optional[str | Path] = None,
) -> None:
    """
    Validate encoding options against codec metadata and sanity bounds.

    Args:
        options: EncodeOptions to validate.
        media_info: Optional probed MediaInfo for input stream checks.
        output_path: Optional destination path for container compatibility checks.

    Raises:
        ValueError: On unknown presets, contradictory options, unsupported rate modes,
                    out-of-range numeric parameters, or container mismatches.
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

    v_preset = VIDEO_PRESETS.get(canon_preset) if canon_preset else None
    a_preset = AUDIO_PRESETS.get(canon_preset) if canon_preset else None

    # Contradictory options
    if options.extract_audio and options.mute_audio:
        raise ValueError("Cannot simultaneously extract and mute audio")

    # Mode 1: ProRes capability constraints
    if (v_preset and v_preset.codec_name == "prores_ks") or options.video_codec == "prores_ks":
        if options.two_pass:
            raise ValueError("Two-pass encoding is not supported for ProRes preset")
        if options.target_size_mb is not None:
            raise ValueError("Target size bitrate targeting is not supported for ProRes preset")
        if options.crf is not None:
            raise ValueError("CRF rate control is not supported for ProRes preset (uses profile)")

    # Mode 2: GIF capability constraints
    if (v_preset and v_preset.codec_name == "gif") or options.video_codec == "gif":
        if options.two_pass:
            raise ValueError("Two-pass encoding is not supported for GIF preset")
        if options.target_size_mb is not None:
            raise ValueError("Target size bitrate targeting is not supported for GIF preset")
        if options.crf is not None:
            raise ValueError("CRF rate control is not supported for GIF preset")

    # Mode 3: CRF boundaries
    if options.crf is not None and v_preset is not None:
        if v_preset.crf_range is not None:
            min_crf, max_crf = v_preset.crf_range
            if not (min_crf <= options.crf <= max_crf):
                raise ValueError(
                    f"CRF value {options.crf} out of valid range ({min_crf}-{max_crf}) for preset '{v_preset.name}'"
                )

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
        ext = Path(output_path).suffix.lower().lstrip(".")
        if ext:
            if v_preset is not None and v_preset.compatible_extensions:
                if ext not in v_preset.compatible_extensions:
                    raise ValueError(
                        f"Incompatible output extension '.{ext}' for preset '{v_preset.name}'. "
                        f"Supported extensions: {v_preset.compatible_extensions}"
                    )
            elif a_preset is not None and a_preset.compatible_extensions:
                if ext not in a_preset.compatible_extensions:
                    raise ValueError(
                        f"Incompatible output extension '.{ext}' for preset '{a_preset.name}'. "
                        f"Supported extensions: {a_preset.compatible_extensions}"
                    )
