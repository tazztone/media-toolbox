"""
Unit tests for media_toolbox.ui.forms (pure headless form extraction).

INVARIANT: Strict zero GUI imports (no gi, Gtk, Adw).
"""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

from media_toolbox.ui.forms import (
    build_encode_options_from_state,
    resolve_default_output_path,
)


def test_forms_zero_gui_imports() -> None:
    """Verify forms.py imports zero GUI modules."""
    for mod in ("gi", "gi.repository", "gi.repository.Gtk", "gi.repository.Adw"):
        assert mod not in sys.modules or "media_toolbox.ui.forms" not in getattr(sys.modules.get(mod), "__file__", "")


def test_build_encode_options_crf_mode() -> None:
    """CRF mode populates crf field and sets two_pass=False."""
    opts = build_encode_options_from_state(
        preset="h264",
        rate_mode="crf",
        crf_value=18,
        target_size_mb=25.0,
        scale=(1920, 1080),
        mute_audio=False,
        normalize_audio=True,
        volume_boost_db=3.0,
        audio_bitrate_kbps=192,
        speed_factor=1.5,
        fps=60,
        crop="16:9",
        speed_preset="slow",
    )
    assert opts.preset == "h264"
    assert opts.crf == 18
    assert opts.two_pass is False
    assert opts.target_size_mb is None
    assert opts.scale == (1920, 1080)
    assert opts.speed == 1.5
    assert opts.fps == 60
    assert opts.crop == "16:9"
    assert opts.normalize_audio is True
    assert opts.volume_boost_db == 3.0
    assert opts.audio_bitrate_kbps == 192


def test_build_encode_options_target_size_mode() -> None:
    """Target size mode sets target_size_mb, two_pass=True, and crf=None."""
    opts = build_encode_options_from_state(
        preset="h265",
        rate_mode="target_size",
        crf_value=23,
        target_size_mb=50.0,
        scale=None,
        mute_audio=False,
        normalize_audio=False,
        volume_boost_db=None,
        audio_bitrate_kbps=128,
    )
    assert opts.preset == "h265"
    assert opts.two_pass is True
    assert opts.target_size_mb == 50.0
    assert opts.crf is None


def test_build_encode_options_audio_extraction() -> None:
    """Audio extraction suppresses video scale/crop and enables extract_audio flag."""
    opts = build_encode_options_from_state(
        preset="mp3",
        rate_mode="crf",
        crf_value=23,
        target_size_mb=25.0,
        scale=(1280, 720),
        mute_audio=False,
        normalize_audio=True,
        volume_boost_db=6.0,
        audio_bitrate_kbps=256,
        crop="1:1",
        is_extract_audio=True,
    )
    assert opts.extract_audio is True
    assert opts.mute_audio is False
    assert opts.scale is None
    assert opts.crop is None
    assert opts.audio_bitrate_kbps == 256
    assert opts.normalize_audio is True
    assert opts.volume_boost_db == 6.0


def test_build_encode_options_mute_audio() -> None:
    """Mute audio resets audio filters and normalization."""
    opts = build_encode_options_from_state(
        preset="h264",
        rate_mode="crf",
        crf_value=23,
        target_size_mb=25.0,
        scale=None,
        mute_audio=True,
        normalize_audio=True,
        volume_boost_db=6.0,
        audio_bitrate_kbps=320,
    )
    assert opts.mute_audio is True
    assert opts.normalize_audio is False
    assert opts.volume_boost_db is None


def test_resolve_default_output_path_collision_avoidance(tmp_path: Path) -> None:
    """Collision avoidance increments counter when target path exists."""
    in_file = tmp_path / "clip.mp4"
    in_file.touch()

    # First resolve -> clip_transcoded.mp4
    out1 = resolve_default_output_path(in_file, "h264")
    assert out1 == tmp_path / "clip_transcoded.mp4"
    out1.touch()

    # Second resolve -> clip_transcoded_1.mp4
    out2 = resolve_default_output_path(in_file, "h264")
    assert out2 == tmp_path / "clip_transcoded_1.mp4"
    out2.touch()

    # Third resolve -> clip_transcoded_2.mp4
    out3 = resolve_default_output_path(in_file, "h264")
    assert out3 == tmp_path / "clip_transcoded_2.mp4"


def test_resolve_default_output_path_target_size(tmp_path: Path) -> None:
    """Target size uses compressed tag instead of transcoded."""
    in_file = tmp_path / "movie.mkv"
    in_file.touch()
    out = resolve_default_output_path(in_file, "h264", is_target_size=True)
    assert out.name == "movie_compressed.mp4"
