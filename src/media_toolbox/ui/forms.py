"""
Pure form-state extraction and path resolution helpers for Media Toolbox GUI.

Decoupled from GTK/Adw toolkit widgets to allow pure unit testing
without initializing graphical environments.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from media_toolbox.core.models import EncodeOptions
from media_toolbox.core.presets import (
    get_audio_preset,
    get_video_preset,
    is_audio_preset,
    is_video_preset,
)


def build_encode_options_from_state(
    preset: str,
    rate_mode: str,  # "crf" | "target_size"
    crf_value: int,
    target_size_mb: float,
    scale: Optional[tuple[int, int]],
    mute_audio: bool,
    normalize_audio: bool,
    volume_boost_db: Optional[float],
    audio_bitrate_kbps: int,
    speed_factor: float = 1.0,
    fps: Optional[int] = None,
    crop: Optional[str] = None,
    speed_preset: Optional[str] = None,
    is_extract_audio: bool = False,
) -> EncodeOptions:
    """
    Pure conversion of form widget states into an immutable EncodeOptions dataclass.
    """
    # Rate control resolution
    crf: Optional[int] = None
    target_size: Optional[float] = None
    two_pass: bool = False

    if not is_extract_audio and preset not in ("gif", "prores"):
        if rate_mode == "crf":
            crf = crf_value
        elif rate_mode == "target_size":
            target_size = target_size_mb
            two_pass = True

    # Audio resolution
    if mute_audio and not is_extract_audio:
        eff_mute = True
        eff_extract = False
        eff_norm = False
        eff_boost = None
        eff_audio_br = 128
    else:
        eff_mute = False
        eff_extract = is_extract_audio
        eff_norm = normalize_audio
        eff_boost = volume_boost_db if volume_boost_db and abs(volume_boost_db) > 0.01 else None
        eff_audio_br = audio_bitrate_kbps

    # Speed resolution
    eff_speed = speed_factor if abs(speed_factor - 1.0) > 0.001 else None

    # Resolution resolution
    eff_scale = None if is_extract_audio else scale
    eff_crop = None if is_extract_audio else crop

    return EncodeOptions(
        target_size_mb=target_size,
        crf=crf,
        video_codec=preset if not is_extract_audio else "libx264",
        audio_codec=None,
        audio_bitrate_kbps=eff_audio_br,
        scale=eff_scale,
        crop=eff_crop,
        speed=eff_speed,
        fps=fps,
        mute_audio=eff_mute,
        extract_audio=eff_extract,
        normalize_audio=eff_norm,
        volume_boost_db=eff_boost,
        two_pass=two_pass,
        preset=preset,
        speed_preset=speed_preset,
    )


def resolve_default_output_path(
    input_path: str | Path,
    preset_name: str,
    is_extract_audio: bool = False,
    is_target_size: bool = False,
) -> Path:
    """
    Generate default output file path with collision avoidance and overwrite protection.
    """
    inp = Path(input_path).resolve()
    directory = inp.parent
    stem = inp.stem

    if is_extract_audio or is_audio_preset(preset_name):
        ext = get_audio_preset(preset_name).default_extension
        tag = "audio"
    elif is_video_preset(preset_name):
        ext = get_video_preset(preset_name).default_extension
        tag = "compressed" if is_target_size else "transcoded"
    else:
        ext = "mp4"
        tag = "converted"

    candidate = directory / f"{stem}_{tag}.{ext}"
    counter = 1
    # Ensure candidate never overwrites the input file itself or existing disk files
    while candidate == inp or candidate.exists():
        candidate = directory / f"{stem}_{tag}_{counter}.{ext}"
        counter += 1

    return candidate
