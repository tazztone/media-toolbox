"""
Unit tests for bitrate calculation engine (core/bitrate.py).
"""

from __future__ import annotations

import pytest
from media_toolbox.core.bitrate import (
    DEFAULT_AUDIO_BITRATE_KBPS,
    DEFAULT_MIN_VIDEO_BITRATE_KBPS,
    DEFAULT_MUX_OVERHEAD_MARGIN,
    KBITS_PER_MB,
    TargetSizeTooSmallError,
    calculate_target_video_bitrate,
)


class TestBitrateCalculation:
    """Test suite for calculate_target_video_bitrate."""

    @pytest.mark.parametrize(
        "target_mb, duration_s, audio_kbps, margin, expected_kbps",
        [
            # 25MB, 60s, 128k audio, 3% margin -> (25 * 8000 * 0.97 / 60) - 128 = 3105 kbps
            (25.0, 60.0, 128, 0.03, 3105),
            # 8MB (Discord limit), 120s, 128k audio, 3% margin -> (8 * 8000 * 0.97 / 120) - 128 = 389 kbps
            (8.0, 120.0, 128, 0.03, 389),
            # 100MB, 1800s (30 min), 192k audio, 5% margin -> (100 * 8000 * 0.95 / 1800) - 192 = 230 kbps
            (100.0, 1800.0, 192, 0.05, 230),
            # Zero margin: 25MB, 60s, 128k audio, 0% margin -> (25 * 8000 * 1.0 / 60) - 128 = 3205 kbps
            (25.0, 60.0, 128, 0.0, 3205),
            # Zero audio bitrate (muted/silent video): 10MB, 100s, 0k audio, 3% margin -> 776 kbps
            (10.0, 100.0, 0, 0.03, 776),
            # Integer inputs: 25, 60, 128 -> 3105 kbps
            (25, 60, 128, 0.03, 3105),
        ],
    )
    def test_bitrate_standard_scenarios(
        self, target_mb: float, duration_s: float, audio_kbps: int, margin: float, expected_kbps: int
    ) -> None:
        result = calculate_target_video_bitrate(
            target_size_mb=target_mb,
            duration_seconds=duration_s,
            audio_bitrate_kbps=audio_kbps,
            mux_overhead_margin=margin,
        )
        assert result == expected_kbps
        assert isinstance(result, int)

    def test_bitrate_default_parameters(self) -> None:
        # target_mb=25.0, duration_seconds=60.0 with all defaults -> 3105 kbps
        result = calculate_target_video_bitrate(25.0, 60.0)
        assert result == 3105

    def test_bitrate_speed_scaling(self) -> None:
        # 25 MB, 60s video sped up by 2.0x -> effective 30s -> higher bitrate
        # (25 * 8000 * 0.97 / 30) - 128 = 6339 kbps
        result_fast = calculate_target_video_bitrate(25.0, 60.0, speed=2.0)
        assert result_fast == 6339

        # 25 MB, 60s video slowed down to 0.5x -> effective 120s -> lower bitrate
        # (25 * 8000 * 0.97 / 120) - 128 = 1489 kbps
        result_slow = calculate_target_video_bitrate(25.0, 60.0, speed=0.5)
        assert result_slow == 1489

    @pytest.mark.parametrize(
        "target_mb, duration_s, audio_kbps",
        [
            # Extreme long duration (1 hour) with tiny size (1 MB)
            (1.0, 3600.0, 128),
            # Duration where net bitrate is negative
            (0.5, 600.0, 128),
            # Net bitrate slightly below floor
            (1.0, 60.0, 160),
        ],
    )
    def test_bitrate_too_small_raises_typed_error(
        self, target_mb: float, duration_s: float, audio_kbps: int
    ) -> None:
        with pytest.raises(TargetSizeTooSmallError) as exc_info:
            calculate_target_video_bitrate(
                target_size_mb=target_mb,
                duration_seconds=duration_s,
                audio_bitrate_kbps=audio_kbps,
            )
        err = exc_info.value
        assert err.target_size_mb == target_mb
        assert err.min_required_mb > target_mb

    def test_bitrate_clamps_to_minimum_when_explicitly_requested(self) -> None:
        result = calculate_target_video_bitrate(
            target_size_mb=1.0,
            duration_seconds=3600.0,
            audio_bitrate_kbps=128,
            clamp_to_min=True,
        )
        assert result == DEFAULT_MIN_VIDEO_BITRATE_KBPS

    def test_custom_min_video_bitrate(self) -> None:
        # Clamping to custom floor 100 kbps
        result = calculate_target_video_bitrate(
            target_size_mb=1.0,
            duration_seconds=3600.0,
            audio_bitrate_kbps=128,
            min_video_bitrate_kbps=100,
            clamp_to_min=True,
        )
        assert result == 100

        # Clamping to custom floor 0 kbps
        result_zero = calculate_target_video_bitrate(
            target_size_mb=1.0,
            duration_seconds=3600.0,
            audio_bitrate_kbps=128,
            min_video_bitrate_kbps=0,
            clamp_to_min=True,
        )
        assert result_zero == 0

    @pytest.mark.parametrize(
        "invalid_duration",
        [0, 0.0, -1, -60.0, float("nan"), float("inf"), float("-inf")],
    )
    def test_invalid_duration_raises_value_error(self, invalid_duration: float) -> None:
        with pytest.raises(ValueError, match="duration_seconds must be a positive finite number"):
            calculate_target_video_bitrate(25.0, invalid_duration)

    @pytest.mark.parametrize(
        "invalid_target_size",
        [0, 0.0, -1, -25.0, float("nan"), float("inf"), float("-inf")],
    )
    def test_invalid_target_size_raises_value_error(self, invalid_target_size: float) -> None:
        with pytest.raises(ValueError, match="target_size_mb must be a positive finite number"):
            calculate_target_video_bitrate(invalid_target_size, 60.0)

    def test_negative_audio_bitrate_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="audio_bitrate_kbps cannot be negative"):
            calculate_target_video_bitrate(25.0, 60.0, audio_bitrate_kbps=-1)

    @pytest.mark.parametrize("invalid_margin", [-0.01, -1.0, 1.0, 1.05, 2.0])
    def test_invalid_margin_raises_value_error(self, invalid_margin: float) -> None:
        with pytest.raises(ValueError, match="mux_overhead_margin must be in range"):
            calculate_target_video_bitrate(25.0, 60.0, mux_overhead_margin=invalid_margin)

    def test_negative_min_video_bitrate_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="min_video_bitrate_kbps cannot be negative"):
            calculate_target_video_bitrate(25.0, 60.0, min_video_bitrate_kbps=-1)
