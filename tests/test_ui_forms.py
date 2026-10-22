"""Unit test suite for form state translation and default output path resolution.

Tests:
- Form state translation into EncodeOptions (CRF, Target Size, Resolution, Speed, Audio, Crop)
- Collision-safe default output path resolution
"""

from __future__ import annotations

import sys
from pathlib import Path

from media_toolbox.ui.forms import (
    build_encode_options_from_state,
    resolve_default_output_path,
)


def test_forms_zero_gui_imports() -> None:
    """Verify forms.py imports zero GUI modules."""
    for mod in ("gi", "gi.repository", "gi.repository.Gtk", "gi.repository.Adw"):
        assert mod not in sys.modules or "media_toolbox.ui.forms" not in getattr(
            sys.modules.get(mod), "__file__", ""
        )


# ---------------------------------------------------------------------------
# 3. Form State to EncodeOptions Translation Tests
# ---------------------------------------------------------------------------


class TestWidgetStateToEncodeOptions:
    """Verifies pure conversion of form widgets state to immutable EncodeOptions."""

    def test_crf_mode_defaults_h264(self) -> None:
        """Verify standard CRF mode creates single-pass EncodeOptions with crf=23."""

        opts = build_encode_options_from_state(
            preset="h264",
            rate_mode="crf",
            crf_value=23,
            target_size_mb=25.0,
            scale=None,
            mute_audio=False,
            normalize_audio=False,
            volume_boost_db=None,
            audio_bitrate_kbps=128,
            speed_factor=1.0,
        )
        assert opts.crf == 23
        assert opts.two_pass is False
        assert opts.target_size_mb is None
        assert opts.video_codec == "h264"
        assert opts.speed is None
        assert opts.scale is None

    def test_crf_mode_codec_specific_bounds(self) -> None:
        """Verify CRF values map correctly for h265, av1, and vp9."""

        opts_h265 = build_encode_options_from_state(
            "h265", "crf", 28, 25.0, None, False, False, None, 128
        )
        assert opts_h265.crf == 28

        opts_av1 = build_encode_options_from_state(
            "av1", "crf", 30, 25.0, None, False, False, None, 128
        )
        assert opts_av1.crf == 30

        opts_vp9 = build_encode_options_from_state(
            "vp9", "crf", 32, 25.0, None, False, False, None, 128
        )
        assert opts_vp9.crf == 32

    def test_target_size_mode_two_pass(self) -> None:
        """Verify target size mode activates two_pass and sets target_size_mb."""

        opts = build_encode_options_from_state(
            preset="h264",
            rate_mode="target_size",
            crf_value=23,
            target_size_mb=50.0,
            scale=None,
            mute_audio=False,
            normalize_audio=False,
            volume_boost_db=None,
            audio_bitrate_kbps=128,
        )
        assert opts.two_pass is True
        assert opts.target_size_mb == 50.0
        assert opts.crf is None

    def test_resolution_original_scale_is_none(self) -> None:
        """Verify original resolution passes scale=None."""

        opts = build_encode_options_from_state(
            "h264",
            "crf",
            23,
            25.0,
            scale=None,
            mute_audio=False,
            normalize_audio=False,
            volume_boost_db=None,
            audio_bitrate_kbps=128,
        )
        assert opts.scale is None

    def test_resolution_preset_1080p(self) -> None:
        """Verify 1080p scale preset (1920, 1080)."""

        opts = build_encode_options_from_state(
            "h264",
            "crf",
            23,
            25.0,
            scale=(1920, 1080),
            mute_audio=False,
            normalize_audio=False,
            volume_boost_db=None,
            audio_bitrate_kbps=128,
        )
        assert opts.scale == (1920, 1080)

    def test_resolution_preset_720p(self) -> None:
        """Verify 720p scale preset (1280, 720)."""

        opts = build_encode_options_from_state(
            "h264",
            "crf",
            23,
            25.0,
            scale=(1280, 720),
            mute_audio=False,
            normalize_audio=False,
            volume_boost_db=None,
            audio_bitrate_kbps=128,
        )
        assert opts.scale == (1280, 720)

    def test_resolution_preset_480p(self) -> None:
        """Verify 480p scale preset (854, 480)."""

        opts = build_encode_options_from_state(
            "h264",
            "crf",
            23,
            25.0,
            scale=(854, 480),
            mute_audio=False,
            normalize_audio=False,
            volume_boost_db=None,
            audio_bitrate_kbps=128,
        )
        assert opts.scale == (854, 480)

    def test_resolution_custom_even_dimension_snapping(self) -> None:
        """Verify custom dimension snapping helper logic."""
        custom_w, custom_h = 1921, 1079
        snapped_w = custom_w - (custom_w % 2)
        snapped_h = custom_h - (custom_h % 2)

        opts = build_encode_options_from_state(
            "h264",
            "crf",
            23,
            25.0,
            scale=(snapped_w, snapped_h),
            mute_audio=False,
            normalize_audio=False,
            volume_boost_db=None,
            audio_bitrate_kbps=128,
        )
        assert opts.scale == (1920, 1078)

    def test_speed_factor_normal_and_multiplier(self) -> None:
        """Verify 1.0x maps to None, while other multipliers are preserved."""

        opts_1 = build_encode_options_from_state(
            "h264", "crf", 23, 25.0, None, False, False, None, 128, speed_factor=1.0
        )
        assert opts_1.speed is None

        opts_2 = build_encode_options_from_state(
            "h264", "crf", 23, 25.0, None, False, False, None, 128, speed_factor=2.0
        )
        assert opts_2.speed == 2.0

        opts_half = build_encode_options_from_state(
            "h264", "crf", 23, 25.0, None, False, False, None, 128, speed_factor=0.5
        )
        assert opts_half.speed == 0.5

    def test_audio_mute_strips_audio_and_resets_volume(self) -> None:
        """Verify mute_audio=True clears loudness normalization and volume boost."""

        opts = build_encode_options_from_state(
            preset="h264",
            rate_mode="crf",
            crf_value=23,
            target_size_mb=25.0,
            scale=None,
            mute_audio=True,
            normalize_audio=True,
            volume_boost_db=6.0,
            audio_bitrate_kbps=192,
        )
        assert opts.mute_audio is True
        assert opts.normalize_audio is False
        assert opts.volume_boost_db is None

    def test_audio_adjustments_loudness_and_boost(self) -> None:
        """Verify unmuted audio retains normalization and boost values."""

        opts = build_encode_options_from_state(
            preset="h264",
            rate_mode="crf",
            crf_value=23,
            target_size_mb=25.0,
            scale=None,
            mute_audio=False,
            normalize_audio=True,
            volume_boost_db=4.5,
            audio_bitrate_kbps=192,
        )
        assert opts.mute_audio is False
        assert opts.normalize_audio is True
        assert opts.volume_boost_db == 4.5
        assert opts.audio_bitrate_kbps == 192

    def test_extract_audio_mode_options(self) -> None:
        """Verify extract_audio mode sets extract_audio=True and scale=None."""

        opts = build_encode_options_from_state(
            preset="mp3",
            rate_mode="crf",
            crf_value=23,
            target_size_mb=25.0,
            scale=(1920, 1080),
            mute_audio=False,
            normalize_audio=True,
            volume_boost_db=None,
            audio_bitrate_kbps=256,
            is_extract_audio=True,
        )
        assert opts.extract_audio is True
        assert opts.scale is None
        assert opts.crf is None
        assert opts.two_pass is False
        assert opts.audio_bitrate_kbps == 256

    def test_gif_and_prores_incompatible_rate_control_ignored(self) -> None:
        """Verify GIF and ProRes presets omit CRF and two-pass rate control."""

        opts_gif = build_encode_options_from_state(
            "gif", "crf", 23, 10.0, None, False, False, None, 128
        )
        assert opts_gif.crf is None
        assert opts_gif.two_pass is False

        opts_prores = build_encode_options_from_state(
            "prores", "target_size", 23, 50.0, None, False, False, None, 128
        )
        assert opts_prores.two_pass is False
        assert opts_prores.target_size_mb is None

    def test_build_encode_options_with_crop(self) -> None:
        """Verify crop string is passed to EncodeOptions."""

        opts = build_encode_options_from_state(
            preset="h264",
            rate_mode="crf",
            crf_value=23,
            target_size_mb=25.0,
            scale=(1920, 1080),
            crop="ih*9/16:ih",
            mute_audio=False,
            normalize_audio=False,
            volume_boost_db=None,
            audio_bitrate_kbps=128,
        )
        assert opts.crop == "ih*9/16:ih"
        assert opts.scale == (1920, 1080)

    def test_build_encode_options_crop_ignored_on_audio_extract(self) -> None:
        """Verify crop is reset to None when extracting audio."""

        opts = build_encode_options_from_state(
            preset="mp3",
            rate_mode="crf",
            crf_value=23,
            target_size_mb=25.0,
            scale=(1920, 1080),
            crop="ih*9/16:ih",
            mute_audio=False,
            normalize_audio=False,
            volume_boost_db=None,
            audio_bitrate_kbps=128,
            is_extract_audio=True,
        )
        assert opts.crop is None
        assert opts.scale is None

    def test_build_encode_options_audio_track_and_subtitles(self) -> None:
        """Verify audio_track_index and keep_subtitles pass to EncodeOptions."""

        opts = build_encode_options_from_state(
            preset="h264",
            rate_mode="crf",
            crf_value=23,
            target_size_mb=25.0,
            scale=None,
            mute_audio=False,
            normalize_audio=False,
            volume_boost_db=None,
            audio_bitrate_kbps=128,
            audio_track_index=1,
            keep_subtitles=True,
        )
        assert opts.audio_track_index == 1
        assert opts.keep_subtitles is True

    def test_build_encode_options_muted_clears_audio_track_index(self) -> None:
        """When mute_audio is True, audio_track_index is reset to None."""

        opts = build_encode_options_from_state(
            preset="h264",
            rate_mode="crf",
            crf_value=23,
            target_size_mb=25.0,
            scale=None,
            mute_audio=True,
            normalize_audio=False,
            volume_boost_db=None,
            audio_bitrate_kbps=128,
            audio_track_index=1,
            keep_subtitles=True,
        )
        assert opts.audio_track_index is None
        assert opts.keep_subtitles is True


# ---------------------------------------------------------------------------
# 4. Default Output Path Resolution Tests
# ---------------------------------------------------------------------------


class TestDefaultOutputPathResolution:
    """Verifies default output path calculation, collision avoidance, and safety."""

    def test_output_path_transcode_video_preset(self, tmp_path: Path) -> None:
        """Verify default video transcode output path has _transcoded.mp4."""

        inp = tmp_path / "movie.mkv"
        out = resolve_default_output_path(inp, preset_name="h264")
        assert out == tmp_path / "movie_transcoded.mp4"

    def test_output_path_target_size_compressed_tag(self, tmp_path: Path) -> None:
        """Verify target size mode produces _compressed.mp4 tag."""

        inp = tmp_path / "movie.mkv"
        out = resolve_default_output_path(inp, preset_name="h264", is_target_size=True)
        assert out == tmp_path / "movie_compressed.mp4"

    def test_output_path_extract_audio_extension(self, tmp_path: Path) -> None:
        """Verify audio extraction uses audio extension and _audio tag."""

        inp = tmp_path / "clip.mp4"
        out_mp3 = resolve_default_output_path(
            inp, preset_name="mp3", is_extract_audio=True
        )
        assert out_mp3 == tmp_path / "clip_audio.mp3"

        out_flac = resolve_default_output_path(
            inp, preset_name="flac", is_extract_audio=True
        )
        assert out_flac == tmp_path / "clip_audio.flac"

    def test_output_path_collision_avoidance_increments(self, tmp_path: Path) -> None:
        """Verify existing candidate files cause numeric suffix increment (_1, _2)."""

        inp = tmp_path / "test.mp4"
        (tmp_path / "test_transcoded.mp4").touch()

        out1 = resolve_default_output_path(inp, preset_name="h264")
        assert out1 == tmp_path / "test_transcoded_1.mp4"

        out1.touch()
        out2 = resolve_default_output_path(inp, preset_name="h264")
        assert out2 == tmp_path / "test_transcoded_2.mp4"

    def test_output_path_never_overwrites_source_input(self, tmp_path: Path) -> None:
        """Verify output path is never identical to the input path."""

        inp = tmp_path / "video_transcoded.mp4"
        inp.touch()
        (tmp_path / "video_transcoded_transcoded.mp4").touch()
        out = resolve_default_output_path(inp, preset_name="h264")
        assert out != inp
        assert out == tmp_path / "video_transcoded_transcoded_1.mp4"
