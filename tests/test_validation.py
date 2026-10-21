"""
Tests for media_toolbox.core.validation: Centralized option and preset validation.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from media_toolbox.core.builder import build_ffmpeg_commands
from media_toolbox.core.models import (
    AudioStream,
    EncodeOptions,
    FormatInfo,
    MediaInfo,
    VideoStream,
)
from media_toolbox.core.validation import (
    resolve_job_spec,
    validate_encode_options,
)


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

    def test_audio_extraction_from_silent_media_rejected(self) -> None:
        """Extracting audio from silent media fails before execution."""
        silent_info = MediaInfo(
            format=FormatInfo(filename="silent.mp4", format_name="mp4", duration=10.0),
            video_streams=(VideoStream(index=0, codec_name="h264", width=1280, height=720),),
            audio_streams=(),
        )
        opts = EncodeOptions(extract_audio=True)
        with pytest.raises(ValueError, match="no audio streams"):
            validate_encode_options(opts, media_info=silent_info)

    def test_video_transcode_from_audio_only_media_rejected(self) -> None:
        """Transcoding video from audio-only media fails before execution."""
        audio_info = MediaInfo(
            format=FormatInfo(filename="audio.mp3", format_name="mp3", duration=60.0),
            video_streams=(),
            audio_streams=(AudioStream(index=0, codec_name="mp3", channels=2, sample_rate=44100),),
        )
        opts = EncodeOptions(preset="h264")
        with pytest.raises(ValueError, match="no video stream"):
            validate_encode_options(opts, media_info=audio_info)

    def test_crf_checked_on_default_codec_and_codec_flag(self) -> None:
        """CRF bounds check applies even when preset flag is not explicitly passed."""
        # Default codec is libx264 (range 0-51)
        opts_default = EncodeOptions(crf=55)
        with pytest.raises(ValueError, match="CRF.*range"):
            validate_encode_options(opts_default)

        # Explicit video_codec='libx265'
        opts_hevc = EncodeOptions(video_codec="libx265", crf=60)
        with pytest.raises(ValueError, match="CRF.*range"):
            validate_encode_options(opts_hevc)

    def test_audio_extraction_rejects_target_size_and_two_pass(self) -> None:
        """Audio extraction rejects target size or two-pass video settings."""
        opts_target = EncodeOptions(extract_audio=True, target_size_mb=10.0)
        with pytest.raises(ValueError, match="Target size.*not supported.*audio"):
            validate_encode_options(opts_target)

        opts_2pass = EncodeOptions(extract_audio=True, two_pass=True)
        with pytest.raises(ValueError, match="Two-pass.*not supported.*audio"):
            validate_encode_options(opts_2pass)

    def test_audio_preset_with_mute_audio_rejected(self) -> None:
        """Audio preset combined with mute_audio is rejected as contradictory."""
        opts = EncodeOptions(preset="mp3", mute_audio=True)
        with pytest.raises(ValueError, match="Cannot simultaneously extract and mute audio"):
            validate_encode_options(opts)

    def test_resolve_job_spec_preserves_explicit_svtav1(self) -> None:
        """Explicit video_codec='libsvtav1' is preserved and not substituted with libaom-av1."""
        from media_toolbox.core.validation import resolve_job_spec

        opts = EncodeOptions(video_codec="libsvtav1")
        spec = resolve_job_spec(opts)
        assert spec.video_codec == "libsvtav1"

    def test_resolve_job_spec_audio_extract_m4a_resolves_to_aac(self) -> None:
        """Audio extraction to .m4a canonicalizes to AAC preset and codec."""
        from media_toolbox.core.validation import resolve_job_spec

        opts = EncodeOptions(extract_audio=True)
        spec = resolve_job_spec(opts, output_path="output.m4a")
        assert spec.audio_preset_name == "aac"
        assert spec.audio_codec == "aac"

    def test_resolve_job_spec_preserves_explicit_audio_codec(self) -> None:
        """Explicit audio codec like pcm_s16le is preserved for extraction."""
        from media_toolbox.core.validation import resolve_job_spec

        opts = EncodeOptions(extract_audio=True, audio_codec="pcm_s16le")
        spec = resolve_job_spec(opts, output_path="output.wav")
        assert spec.audio_codec == "pcm_s16le"

    def test_crf_and_two_pass_or_target_size_mutually_exclusive(self) -> None:
        """CRF cannot be combined with two-pass or target-size mode."""
        opts_two_pass = EncodeOptions(crf=23, two_pass=True)
        with pytest.raises(ValueError, match="CRF rate control is mutually exclusive"):
            validate_encode_options(opts_two_pass)

        opts_target_size = EncodeOptions(crf=23, target_size_mb=25.0)
        with pytest.raises(ValueError, match="CRF rate control is mutually exclusive"):
            validate_encode_options(opts_target_size)

    def test_webm_incompatible_audio_codec_rejected(self) -> None:
        """Explicitly requesting an incompatible audio codec for WebM raises ValueError."""
        opts = EncodeOptions(preset="vp9", audio_codec="aac")
        with pytest.raises(ValueError, match="Incompatible audio codec 'aac' for WebM/VP9"):
            validate_encode_options(opts, output_path="out.webm")

    def test_stream_copy_with_filters_rejected(self) -> None:
        """Combining audio/video stream copy with filters is rejected."""
        # Audio copy with audio filters
        opts_a_speed = EncodeOptions(audio_codec="copy", speed=1.5)
        with pytest.raises(ValueError, match="Audio filters .* cannot be applied when audio codec is 'copy'"):
            validate_encode_options(opts_a_speed)

        opts_a_norm = EncodeOptions(audio_codec="copy", normalize_audio=True)
        with pytest.raises(ValueError, match="Audio filters .* cannot be applied when audio codec is 'copy'"):
            validate_encode_options(opts_a_norm)

        # Video copy with video filters
        opts_v_crop = EncodeOptions(video_codec="copy", crop="16:9")
        with pytest.raises(ValueError, match="Video filters .* cannot be applied when video codec is 'copy'"):
            validate_encode_options(opts_v_crop)

        opts_v_scale = EncodeOptions(video_codec="copy", scale=(1280, 720))
        with pytest.raises(ValueError, match="Video filters .* cannot be applied when video codec is 'copy'"):
            validate_encode_options(opts_v_scale)

    def test_scale_and_fps_upfront_validation(self) -> None:
        """Invalid scale dimensions and fps are caught in validate_encode_options."""
        with pytest.raises(ValueError, match="Scale dimensions cannot both be non-positive"):
            validate_encode_options(EncodeOptions(scale=(-1, -1)))

        with pytest.raises(ValueError, match="Frame rate must be positive"):
            validate_encode_options(EncodeOptions(fps=-5))

    def test_audio_bitrate_preset_range_validation(self) -> None:
        """Audio bitrates outside preset boundaries are rejected."""
        # Minimum threshold < 8 kbps rejected
        with pytest.raises(ValueError, match="Audio bitrate must be between 8 and 2000 kbps"):
            validate_encode_options(EncodeOptions(audio_bitrate_kbps=4))

        # OPUS preset range is 32-256 kbps; 320 kbps should be rejected for opus preset
        with pytest.raises(ValueError, match="Audio bitrate 320 kbps out of valid range"):
            validate_encode_options(EncodeOptions(preset="opus", audio_bitrate_kbps=320), output_path="out.opus")

    def test_transcode_resolves_audio_codec_alias_to_encoder(self) -> None:
        """In video transcoding, audio codec alias 'mp3' resolves to 'libmp3lame'."""
        from media_toolbox.core.validation import resolve_job_spec

        opts = EncodeOptions(preset="h264", audio_codec="mp3")
        spec = resolve_job_spec(opts)
        assert spec.audio_codec == "libmp3lame"

