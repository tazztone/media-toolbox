"""
Tests for media_toolbox.core.validation: Centralized option and preset validation.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from media_toolbox.core.builder import build_ffmpeg_commands
from media_toolbox.core.models import EncodeOptions, MediaInfo
from media_toolbox.core.validation import validate_encode_options


class TestValidationAndPresetNormalization:
    @pytest.mark.parametrize(
        "preset_alias,expected_extension",
        [
            ("h264", "mp4"),
            ("libx264", "mp4"),
            ("x264", "mkv"),
            ("discord", "mp4"),
            ("discord-h264", "mp4"),
            ("h265", "mp4"),
            ("hevc", "mkv"),
            ("av1", "webm"),
            ("vp9", "webm"),
            ("webm", "webm"),
            ("gif", "gif"),
            ("animated_gif", "gif"),
            ("prores", "mov"),
            ("apple_prores", "mov"),
            ("mp3", "mp3"),
            ("aac", "m4a"),
            ("opus", "opus"),
            ("flac", "flac"),
        ],
    )
    def test_valid_presets_and_aliases_pass_validation(
        self, preset_alias: str, expected_extension: str
    ) -> None:
        opts = EncodeOptions(preset=preset_alias)
        # Should not raise
        validate_encode_options(opts, output_path=f"out.{expected_extension}")

    def test_unknown_preset_rejected(self) -> None:
        opts = EncodeOptions(preset="unsupported_codec_123")
        with pytest.raises(ValueError, match="[Uu]nknown preset"):
            validate_encode_options(opts)

    def test_unknown_preset_fails_builder_without_fallback(self) -> None:
        opts = EncodeOptions(preset="bogus_preset")
        with pytest.raises(ValueError, match="[Uu]nknown preset"):
            build_ffmpeg_commands("in.mp4", "out.mp4", opts)

    def test_prores_rejects_two_pass_and_target_size(self) -> None:
        opts_two_pass = EncodeOptions(preset="prores", two_pass=True)
        with pytest.raises(ValueError, match="[Tt]wo-pass.*not supported.*[Pp]ro[Rr]es"):
            validate_encode_options(opts_two_pass)

        opts_target_size = EncodeOptions(preset="prores", target_size_mb=50.0)
        with pytest.raises(ValueError, match="[Tt]arget size.*not supported.*[Pp]ro[Rr]es"):
            validate_encode_options(opts_target_size)

    def test_prores_rejects_crf_mode(self) -> None:
        opts = EncodeOptions(preset="prores", crf=20)
        with pytest.raises(ValueError, match="CRF.*not supported.*[Pp]ro[Rr]es"):
            validate_encode_options(opts)

    def test_gif_rejects_two_pass_and_target_size(self) -> None:
        opts_two_pass = EncodeOptions(preset="gif", two_pass=True)
        with pytest.raises(ValueError, match="[Tt]wo-pass.*not supported.*[Gg][Ii][Ff]"):
            validate_encode_options(opts_two_pass)

        opts_target_size = EncodeOptions(preset="gif", target_size_mb=10.0)
        with pytest.raises(ValueError, match="[Tt]arget size.*not supported.*[Gg][Ii][Ff]"):
            validate_encode_options(opts_target_size)

    def test_animated_gif_alias_enters_gif_palette_mode(self) -> None:
        opts = EncodeOptions(preset="animated_gif")
        cmds = build_ffmpeg_commands("in.mp4", "out.gif", opts)
        assert len(cmds) == 1
        cmd_str = " ".join(cmds[0])
        assert "palettegen" in cmd_str
        assert "paletteuse" in cmd_str

    @pytest.mark.parametrize(
        "preset,invalid_crf",
        [
            ("h264", -1),
            ("h264", 52),
            ("h265", -5),
            ("h265", 60),
            ("av1", -1),
            ("av1", 64),
            ("vp9", -2),
            ("vp9", 70),
        ],
    )
    def test_crf_out_of_range_rejected(self, preset: str, invalid_crf: int) -> None:
        opts = EncodeOptions(preset=preset, crf=invalid_crf)
        with pytest.raises(ValueError, match="CRF.*range"):
            validate_encode_options(opts)

    @pytest.mark.parametrize("bad_speed", [-1.0, 0.0, float("nan"), float("inf")])
    def test_invalid_speed_rejected(self, bad_speed: float) -> None:
        opts = EncodeOptions(speed=bad_speed)
        with pytest.raises(ValueError, match="[Ss]peed"):
            validate_encode_options(opts)

    @pytest.mark.parametrize("bad_bitrate", [-128, 0, 100000])
    def test_invalid_audio_bitrate_rejected(self, bad_bitrate: int) -> None:
        opts = EncodeOptions(audio_bitrate_kbps=bad_bitrate)
        with pytest.raises(ValueError, match="[Aa]udio bitrate"):
            validate_encode_options(opts)

    def test_incompatible_extension_rejected(self) -> None:
        opts = EncodeOptions(preset="h264")
        with pytest.raises(ValueError, match="[Ii]ncompatible.*extension"):
            validate_encode_options(opts, output_path="output.webm")

        opts_gif = EncodeOptions(preset="gif")
        with pytest.raises(ValueError, match="[Ii]ncompatible.*extension"):
            validate_encode_options(opts_gif, output_path="output.mp4")
