"""Unit and widget test suite for dynamic revealers and metadata card display.

Tests:
- Dynamic revealer visibility and widget sensitivity logic
- MetadataCard rendering for video+audio, silent video, audio only, still image, and cleared states
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from media_toolbox.core.models import (
    AudioStream,
    FormatInfo,
    MediaInfo,
    VideoStream,
)

pytestmark = [pytest.mark.desktop]


# ---------------------------------------------------------------------------
# 5. Dynamic Revealers Tests
# ---------------------------------------------------------------------------


class TestDynamicRevealers:
    """Verifies conditional visibility and sensitivity logic for dynamic forms using genuine unbound methods."""

    def test_rate_control_revealer_crf_vs_target_size(self) -> None:
        """Verify mode index 0 reveals CRF and collapses Target Size; index 1 reverses."""
        from media_toolbox.ui.widgets import RateControlWidget

        mock_self = MagicMock()
        mock_combo = MagicMock()

        # Mode 0: CRF
        mock_combo.get_selected.return_value = 0
        RateControlWidget._on_mode_changed(mock_self, mock_combo, None)
        mock_self.crf_revealer.set_reveal_child.assert_called_with(True)
        mock_self.target_size_revealer.set_reveal_child.assert_called_with(False)

        # Mode 1: Target Size
        mock_combo.get_selected.return_value = 1
        RateControlWidget._on_mode_changed(mock_self, mock_combo, None)
        mock_self.crf_revealer.set_reveal_child.assert_called_with(False)
        mock_self.target_size_revealer.set_reveal_child.assert_called_with(True)

    def test_rate_control_revealer_disabled_for_gif_prores(self) -> None:
        """Verify selecting GIF or ProRes disables the rate control selector, and standard codecs re-enable."""
        from media_toolbox.ui.widgets import RateControlWidget

        mock_self = MagicMock()
        mock_self.mode_row = MagicMock()
        mock_self.mode_row.get_selected.return_value = 0
        mock_self._on_mode_changed = RateControlWidget._on_mode_changed.__get__(
            mock_self, RateControlWidget
        )

        # GIF disables rate control and collapses revealers
        RateControlWidget.set_codec_preset(mock_self, "gif")
        mock_self.mode_row.set_sensitive.assert_called_with(False)
        mock_self.crf_revealer.set_reveal_child.assert_called_with(False)
        mock_self.target_size_revealer.set_reveal_child.assert_called_with(False)

        # ProRes also disables rate control
        RateControlWidget.set_codec_preset(mock_self, "prores")
        mock_self.mode_row.set_sensitive.assert_called_with(False)
        mock_self.crf_revealer.set_reveal_child.assert_called_with(False)
        mock_self.target_size_revealer.set_reveal_child.assert_called_with(False)

        # Standard codec (h264) re-enables and configures upper bound to 51
        RateControlWidget.set_codec_preset(mock_self, "h264")
        mock_self.mode_row.set_sensitive.assert_called_with(True)
        mock_self.crf_adj.set_upper.assert_called_with(51)
        mock_self.crf_revealer.set_reveal_child.assert_called_with(True)

        # AV1 configures upper bound to 63
        RateControlWidget.set_codec_preset(mock_self, "av1")
        mock_self.crf_adj.set_upper.assert_called_with(63)

    def test_resolution_revealer_custom_expansion(self) -> None:
        """Verify index 4 (Custom) expands custom dimensions revealer; presets collapse it."""
        from media_toolbox.ui.widgets import ResolutionWidget

        mock_self = MagicMock()
        mock_combo = MagicMock()

        mock_combo.get_selected.return_value = 4  # Custom
        ResolutionWidget._on_resolution_changed(mock_self, mock_combo, None)
        mock_self.custom_revealer.set_reveal_child.assert_called_with(True)

        mock_combo.get_selected.return_value = 1  # 1080p
        ResolutionWidget._on_resolution_changed(mock_self, mock_combo, None)
        mock_self.custom_revealer.set_reveal_child.assert_called_with(False)

    def test_resolution_revealer_preset_collapse(self) -> None:
        """Verify selecting standard presets collapses custom revealer."""
        from media_toolbox.ui.widgets import ResolutionWidget

        mock_self = MagicMock()
        mock_combo = MagicMock()

        for idx in (0, 1, 2, 3):
            mock_combo.get_selected.return_value = idx
            ResolutionWidget._on_resolution_changed(mock_self, mock_combo, None)
            mock_self.custom_revealer.set_reveal_child.assert_called_with(False)

    def test_audio_revealer_mute_collapses_adjustments(self) -> None:
        """Verify toggling mute collapses volume and loudness adjustments."""
        from media_toolbox.ui.widgets import AudioOptionsWidget

        mock_self = MagicMock()
        mock_switch = MagicMock()

        mock_switch.get_active.return_value = True
        AudioOptionsWidget._on_mute_changed(mock_self, mock_switch, None)
        mock_self.adjustments_revealer.set_reveal_child.assert_called_with(False)

        mock_switch.get_active.return_value = False
        AudioOptionsWidget._on_mute_changed(mock_self, mock_switch, None)
        mock_self.adjustments_revealer.set_reveal_child.assert_called_with(True)

    def test_audio_options_disabled_when_source_is_silent(
        self, sample_silent_media_info: MediaInfo
    ) -> None:
        """Verify that files without audio streams disable the audio options group."""
        from media_toolbox.ui.widgets import AudioOptionsWidget

        mock_self = MagicMock()
        AudioOptionsWidget.set_has_audio(mock_self, sample_silent_media_info.has_audio)
        mock_self.set_sensitive.assert_called_with(False)
        mock_self.set_description.assert_called_with(
            "Source file contains no audio streams"
        )

    def test_audio_options_tracks_revealer_and_selection(self) -> None:
        """Verify multi-track audio reveals track dropdown, while single/zero tracks hide it."""
        from media_toolbox.ui.widgets import AudioOptionsWidget

        mock_self = MagicMock()
        mock_self.audio_tracks_model = MagicMock()
        mock_self.audio_track_row = MagicMock()
        mock_self.audio_track_revealer = MagicMock()

        # Multi-track: 2 audio streams
        s1 = AudioStream(index=1, codec_name="aac", channels=2, sample_rate=48000)
        s2 = AudioStream(index=2, codec_name="ac3", channels=6, sample_rate=48000)
        AudioOptionsWidget.set_audio_tracks(mock_self, [s1, s2])
        assert mock_self._num_audio_tracks == 2
        mock_self.audio_track_revealer.set_reveal_child.assert_called_with(True)

        mock_self.audio_track_row.get_selected.return_value = 1
        assert AudioOptionsWidget.get_audio_track_index(mock_self) == 1

        # Single track: hides revealer
        AudioOptionsWidget.set_audio_tracks(mock_self, [s1])
        assert mock_self._num_audio_tracks == 1
        mock_self.audio_track_revealer.set_reveal_child.assert_called_with(False)
        assert AudioOptionsWidget.get_audio_track_index(mock_self) is None

        # Zero tracks: hides revealer
        AudioOptionsWidget.set_audio_tracks(mock_self, [])
        assert mock_self._num_audio_tracks == 0
        mock_self.audio_track_revealer.set_reveal_child.assert_called_with(False)
        assert AudioOptionsWidget.get_audio_track_index(mock_self) is None

    def test_audio_options_subtitles_getter(self) -> None:
        """Verify get_keep_subtitles returns switch active state."""
        from media_toolbox.ui.widgets import AudioOptionsWidget

        mock_self = MagicMock()
        mock_self.keep_subs_switch = MagicMock()
        mock_self.keep_subs_switch.get_active.return_value = True
        assert AudioOptionsWidget.get_keep_subtitles(mock_self) is True

        mock_self.keep_subs_switch.get_active.return_value = False
        assert AudioOptionsWidget.get_keep_subtitles(mock_self) is False

        AudioOptionsWidget.set_has_audio(mock_self, True)
        mock_self.set_sensitive.assert_called_with(True)
        mock_self.set_description.assert_called_with("")


# ---------------------------------------------------------------------------
# 5b. Metadata Card Tests
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("gi_env")
class TestMetadataCard:
    """Headless unit verification for MetadataCard.set_media_info and clear."""

    def test_metadata_card_video_and_audio(self) -> None:
        """Verify card displays both video and audio stream specs and [Video + Audio] badge."""
        from media_toolbox.ui.widgets import MetadataCard

        v = VideoStream(
            index=0,
            codec_name="h264",
            width=1920,
            height=1080,
            fps=30.0,
            duration=60.0,
            bit_rate=2_000_000,
        )
        a = AudioStream(
            index=1,
            codec_name="aac",
            channels=2,
            sample_rate=48000,
            duration=60.0,
            channel_layout="stereo",
            bit_rate=128_000,
        )
        fmt = FormatInfo(
            filename="sample.mp4",
            format_name="mov,mp4",
            duration=60.0,
            size_bytes=15_000_000,
        )
        info = MediaInfo(format=fmt, video_streams=(v,), audio_streams=(a,))

        mock_card = MagicMock()
        MetadataCard.set_media_info(mock_card, info)

        mock_card.badge_row.set_subtitle.assert_called_with("[Video + Audio]")
        mock_card.video_row.set_subtitle.assert_called_with(
            "H264 | 1920 × 1080 @ 30 fps | Bitrate: 2,000 kbps (2.00 Mbps)"
        )
        mock_card.audio_row.set_subtitle.assert_called_with(
            "AAC | stereo (2 channels) | 48.0 kHz | Bitrate: 128 kbps"
        )
        mock_card.format_row.set_subtitle.assert_called_with(
            "mov,mp4 | Duration: 00:01:00.00 | Size: 14.31 MiB (15,000,000 bytes)"
        )

    def test_metadata_card_silent_video(self) -> None:
        """Verify card displays [Silent Video] badge and 'No audio stream' for video-only media."""
        from media_toolbox.ui.widgets import MetadataCard

        v = VideoStream(
            index=0,
            codec_name="hevc",
            width=3840,
            height=2160,
            fps=59.94,
            duration=10.0,
            bit_rate=15_000_000,
        )
        fmt = FormatInfo(
            filename="silent.mp4",
            format_name="mp4",
            duration=10.0,
            size_bytes=18_750_000,
        )
        info = MediaInfo(format=fmt, video_streams=(v,), audio_streams=())

        mock_card = MagicMock()
        MetadataCard.set_media_info(mock_card, info)

        mock_card.badge_row.set_subtitle.assert_called_with("[Silent Video]")
        mock_card.video_row.set_subtitle.assert_called_with(
            "HEVC | 3840 × 2160 @ 59.94 fps | Bitrate: 15,000 kbps (15.00 Mbps)"
        )
        mock_card.audio_row.set_subtitle.assert_called_with("No audio stream")
        mock_card.format_row.set_subtitle.assert_called_with(
            "mp4 | Duration: 00:00:10.00 | Size: 17.88 MiB (18,750,000 bytes)"
        )

    def test_metadata_card_audio_only(self) -> None:
        """Verify card displays [Audio Only] badge and 'No video stream' for audio-only media."""
        from media_toolbox.ui.widgets import MetadataCard

        a = AudioStream(
            index=0,
            codec_name="mp3",
            channels=2,
            sample_rate=44100,
            duration=120.0,
            channel_layout="stereo",
            bit_rate=320_000,
        )
        fmt = FormatInfo(
            filename="track.mp3",
            format_name="mp3",
            duration=120.0,
            size_bytes=4_800_000,
        )
        info = MediaInfo(format=fmt, video_streams=(), audio_streams=(a,))

        mock_card = MagicMock()
        MetadataCard.set_media_info(mock_card, info)

        mock_card.badge_row.set_subtitle.assert_called_with("[Audio Only]")
        mock_card.video_row.set_subtitle.assert_called_with("No video stream")
        mock_card.audio_row.set_subtitle.assert_called_with(
            "MP3 | stereo (2 channels) | 44.1 kHz | Bitrate: 320 kbps"
        )
        mock_card.format_row.set_subtitle.assert_called_with(
            "mp3 | Duration: 00:02:00.00 | Size: 4.58 MiB (4,800,000 bytes)"
        )

    def test_metadata_card_still_image(self) -> None:
        """Verify card displays [Still Image / Other] for images and containers without streams."""
        from media_toolbox.ui.widgets import MetadataCard

        # Probed still image with 0 duration
        v = VideoStream(
            index=0,
            codec_name="png",
            width=800,
            height=600,
            fps=None,
            duration=None,
            bit_rate=None,
        )
        fmt = FormatInfo(
            filename="diagram.png",
            format_name="image2",
            duration=None,
            size_bytes=45_000,
        )
        info = MediaInfo(format=fmt, video_streams=(v,), audio_streams=())

        mock_card = MagicMock()
        MetadataCard.set_media_info(mock_card, info)

        mock_card.badge_row.set_subtitle.assert_called_with("[Still Image / Other]")
        mock_card.video_row.set_subtitle.assert_called_with(
            "PNG | 800 × 600 @ N/A | Bitrate: -"
        )
        mock_card.audio_row.set_subtitle.assert_called_with("No audio stream")

        # Container without any streams
        mock_card_empty = MagicMock()
        empty_fmt = FormatInfo(
            filename="raw.bin", format_name="data", duration=None, size_bytes=1024
        )
        empty_info = MediaInfo(format=empty_fmt, video_streams=(), audio_streams=())
        MetadataCard.set_media_info(mock_card_empty, empty_info)
        mock_card_empty.badge_row.set_subtitle.assert_called_with(
            "[Still Image / Other]"
        )
        mock_card_empty.video_row.set_subtitle.assert_called_with("No video stream")
        mock_card_empty.audio_row.set_subtitle.assert_called_with("No audio stream")

    def test_metadata_card_missing_channel_layout(self) -> None:
        """Verify format_channels works seamlessly when channel_layout is None."""
        from media_toolbox.ui.widgets import MetadataCard

        # Multi-channel layout is None
        a_multi = AudioStream(
            index=0,
            codec_name="flac",
            channels=6,
            sample_rate=96000,
            duration=60.0,
            channel_layout=None,
            bit_rate=None,
        )
        fmt = FormatInfo(
            filename="surround.flac",
            format_name="flac",
            duration=60.0,
            size_bytes=30_000_000,
        )
        info_multi = MediaInfo(format=fmt, video_streams=(), audio_streams=(a_multi,))

        mock_card = MagicMock()
        MetadataCard.set_media_info(mock_card, info_multi)
        mock_card.audio_row.set_subtitle.assert_called_with(
            "FLAC | 6 channels | 96.0 kHz | Bitrate: -"
        )

        # Mono layout is None
        a_mono = AudioStream(
            index=0,
            codec_name="wav",
            channels=1,
            sample_rate=44100,
            duration=5.0,
            channel_layout=None,
            bit_rate=705_600,
        )
        info_mono = MediaInfo(format=fmt, video_streams=(), audio_streams=(a_mono,))
        mock_card_mono = MagicMock()
        MetadataCard.set_media_info(mock_card_mono, info_mono)
        mock_card_mono.audio_row.set_subtitle.assert_called_with(
            "WAV | 1 channel | 44.1 kHz | Bitrate: 706 kbps"
        )

    def test_metadata_card_clear(self) -> None:
        """Verify clear restores placeholder labels across all rows."""
        from media_toolbox.ui.widgets import MetadataCard

        mock_card = MagicMock()
        MetadataCard.clear(mock_card)

        mock_card.badge_row.set_subtitle.assert_called_with("No media loaded")
        mock_card.video_row.set_subtitle.assert_called_with("-")
        mock_card.audio_row.set_subtitle.assert_called_with("-")
        mock_card.format_row.set_subtitle.assert_called_with("-")
