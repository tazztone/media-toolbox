"""
Unit tests for media_toolbox.core.presets.

Verifies:
- All 10 video and audio presets exist with correct defaults
- Alias and case-insensitive resolution
- Deterministic CLI flag generation (CRF, 2-pass, ProRes profile, audio extraction)
- Container faststart rules
- AST headless invariant (zero GUI imports)
"""

from __future__ import annotations

import ast
from pathlib import Path
import subprocess
from unittest.mock import patch
import pytest

from media_toolbox.core.presets import (
    AAC_PRESET,
    AV1_PRESET,
    FLAC_PRESET,
    GIF_PRESET,
    H264_PRESET,
    H265_PRESET,
    MP3_PRESET,
    OPUS_PRESET,
    PRORES_PRESET,
    VP9_PRESET,
    AudioPreset,
    PresetName,
    VideoPreset,
    get_audio_preset,
    get_container_faststart_args,
    get_preset,
    get_video_preset,
    is_audio_preset,
    is_speed_preset,
    is_video_preset,
    list_audio_presets,
    list_video_presets,
)


def test_all_10_presets_exist() -> None:
    """Core video presets (software + hardware) and audio presets must be registered."""
    video_presets = list_video_presets()
    audio_presets = list_audio_presets()

    assert len(video_presets) == 12
    assert len(audio_presets) == 4

    video_names = {p.name for p in video_presets}
    assert {"h264", "h265", "av1", "vp9", "gif", "prores"}.issubset(video_names)
    assert {"h264_nvenc", "hevc_nvenc", "h264_vaapi", "hevc_vaapi", "h264_qsv", "hevc_qsv"}.issubset(video_names)

    audio_names = {p.name for p in audio_presets}
    assert audio_names == {"mp3", "aac", "opus", "flac"}


def test_preset_case_insensitive_and_aliases() -> None:
    """Preset resolution works across case variations and common aliases."""
    # Video aliases
    assert get_preset("h264") == H264_PRESET
    assert get_preset("H264") == H264_PRESET
    assert get_preset("H.264") == H264_PRESET
    assert get_preset("libx264") == H264_PRESET
    assert get_preset("x264") == H264_PRESET
    assert get_preset("avc") == H264_PRESET

    assert get_preset("h265") == H265_PRESET
    assert get_preset("H.265") == H265_PRESET
    assert get_preset("libx265") == H265_PRESET
    assert get_preset("hevc") == H265_PRESET

    assert get_preset("av1") == AV1_PRESET
    assert get_preset("libaom-av1") == AV1_PRESET
    assert not is_video_preset("libsvtav1")
    assert not is_video_preset("svt-av1")

    assert get_preset("vp9") == VP9_PRESET
    assert get_preset("libvpx-vp9") == VP9_PRESET
    assert get_preset("webm") == VP9_PRESET

    assert get_preset("gif") == GIF_PRESET
    assert get_preset("animated_gif") == GIF_PRESET

    assert get_preset("prores") == PRORES_PRESET
    assert get_preset("prores_ks") == PRORES_PRESET

    # Audio aliases
    assert get_preset("mp3") == MP3_PRESET
    assert get_preset("libmp3lame") == MP3_PRESET
    assert get_preset("lame") == MP3_PRESET

    assert get_preset("aac") == AAC_PRESET
    assert get_preset("m4a") == AAC_PRESET

    assert get_preset("opus") == OPUS_PRESET
    assert get_preset("libopus") == OPUS_PRESET

    assert get_preset("flac") == FLAC_PRESET
    assert get_preset("lossless_audio") == FLAC_PRESET

    # Enum resolution
    assert get_preset(PresetName.H264) == H264_PRESET
    assert get_preset(PresetName.FLAC) == FLAC_PRESET


def test_preset_unknown_raises() -> None:
    """Unrecognized preset name raises KeyError."""
    with pytest.raises(KeyError, match="Unknown preset"):
        get_preset("invalid_format_xyz")

    with pytest.raises(KeyError, match="Unknown video preset"):
        get_video_preset("mp3")

    with pytest.raises(KeyError, match="Unknown audio preset"):
        get_audio_preset("h264")


def test_is_audio_and_is_video_preset() -> None:
    """Category classification helpers return accurate booleans."""
    assert is_audio_preset("mp3") is True
    assert is_audio_preset("libmp3lame") is True
    assert is_audio_preset("aac") is True
    assert is_audio_preset("opus") is True
    assert is_audio_preset("flac") is True
    assert is_audio_preset("h264") is False
    assert is_audio_preset("gif") is False
    assert is_audio_preset(None) is False
    assert is_audio_preset("") is False

    assert is_video_preset("h264") is True
    assert is_video_preset("libx264") is True
    assert is_video_preset("h265") is True
    assert is_video_preset("av1") is True
    assert is_video_preset("vp9") is True
    assert is_video_preset("gif") is True
    assert is_video_preset("prores") is True
    assert is_video_preset("mp3") is False
    assert is_video_preset(None) is False
    assert is_video_preset("") is False


def test_default_values_contract() -> None:
    """Verify CRF defaults, bitrate defaults, and container mappings."""
    # CRF defaults
    assert H264_PRESET.default_crf == 23
    assert H265_PRESET.default_crf == 28
    assert AV1_PRESET.default_crf == 30
    assert VP9_PRESET.default_crf == 30
    assert GIF_PRESET.default_crf is None
    assert PRORES_PRESET.default_crf is None

    # Audio bitrate defaults
    assert MP3_PRESET.default_bitrate_kbps == 192
    assert AAC_PRESET.default_bitrate_kbps == 192
    assert OPUS_PRESET.default_bitrate_kbps == 128
    assert FLAC_PRESET.default_bitrate_kbps is None
    assert FLAC_PRESET.is_lossless is True

    # Containers
    assert H264_PRESET.default_extension == "mp4"
    assert VP9_PRESET.default_extension == "webm"
    assert PRORES_PRESET.default_extension == "mov"
    assert GIF_PRESET.default_extension == "gif"
    assert MP3_PRESET.default_extension == "mp3"
    assert AAC_PRESET.default_extension == "m4a"
    assert OPUS_PRESET.default_extension == "opus"
    assert FLAC_PRESET.default_extension == "flac"


def test_h264_cli_flags() -> None:
    """H.264 video args generate expected CRF and 2-pass flags."""
    # Default CRF
    crf_args = H264_PRESET.build_video_args()
    assert crf_args == [
        "-c:v", "libx264",
        "-crf", "23",
        "-preset", "medium",
        "-pix_fmt", "yuv420p",
    ]

    # Custom CRF override
    custom_crf = H264_PRESET.build_video_args(crf=18)
    assert custom_crf == [
        "-c:v", "libx264",
        "-crf", "18",
        "-preset", "medium",
        "-pix_fmt", "yuv420p",
    ]

    # Two-Pass Pass 1
    pass1_args = H264_PRESET.build_video_args(
        bitrate_kbps=1200,
        pass_num=1,
        pass_logfile="/tmp/p264",
    )
    assert pass1_args == [
        "-c:v", "libx264",
        "-b:v", "1200k",
        "-preset", "medium",
        "-pix_fmt", "yuv420p",
        "-pass", "1",
        "-passlogfile", "/tmp/p264",
    ]
    assert "-crf" not in pass1_args


def test_h265_cli_flags() -> None:
    """H.265 video args include Apple ecosystem hvc1 tag and encoder-specific 2-pass."""
    args = H265_PRESET.build_video_args()
    assert args == [
        "-c:v", "libx265",
        "-crf", "28",
        "-preset", "medium",
        "-tag:v", "hvc1",
        "-pix_fmt", "yuv420p",
    ]

    # Two-pass pass 1
    p1 = H265_PRESET.build_video_args(
        bitrate_kbps=1500,
        pass_num=1,
        pass_logfile="/tmp/p265_stats",
    )
    assert p1 == [
        "-c:v", "libx265",
        "-b:v", "1500k",
        "-preset", "medium",
        "-tag:v", "hvc1",
        "-pix_fmt", "yuv420p",
        "-x265-params", "pass=1:stats=/tmp/p265_stats",
    ]
    assert "-pass" not in p1
    assert "-passlogfile" not in p1

    # Two-pass pass 2
    p2 = H265_PRESET.build_video_args(
        bitrate_kbps=1500,
        pass_num=2,
        pass_logfile="/tmp/p265_stats",
    )
    assert p2 == [
        "-c:v", "libx265",
        "-b:v", "1500k",
        "-preset", "medium",
        "-tag:v", "hvc1",
        "-pix_fmt", "yuv420p",
        "-x265-params", "pass=2:stats=/tmp/p265_stats",
    ]
    assert "-pass" not in p2
    assert "-passlogfile" not in p2


def test_unsupported_two_pass_raises_value_error() -> None:
    """Presets marked supports_two_pass=False must reject two-pass generation."""
    with pytest.raises(ValueError, match="does not support two-pass"):
        GIF_PRESET.build_video_args(bitrate_kbps=1000, pass_num=1)

    with pytest.raises(ValueError, match="does not support two-pass"):
        PRORES_PRESET.build_video_args(bitrate_kbps=50000, pass_num=1)


def test_check_encoder_available() -> None:
    """Detects available encoders using ffmpeg -encoders output."""
    from media_toolbox.core.presets import check_encoder_available

    mock_stdout = (
        "Encoders:\n"
        " V..... = Video\n"
        " A..... = Audio\n"
        " V..... libx264              libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10\n"
        " V..... libx265              libx265 H.265 / HEVC\n"
        " A..... aac                  AAC (Advanced Audio Coding)\n"
    )

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["ffmpeg", "-hide_banner", "-encoders"],
            returncode=0,
            stdout=mock_stdout,
            stderr="",
        )
        assert check_encoder_available("libx264") is True
        assert check_encoder_available("libx265") is True
        assert check_encoder_available("aac") is True
        assert check_encoder_available("nonexistent_codec_12345") is False

    with patch("subprocess.run", side_effect=FileNotFoundError):
        assert check_encoder_available("libx264") is False


def test_hardware_presets_build_args() -> None:
    """Hardware presets emit correct codec and quality flags (-cq for nvenc, -qp for vaapi)."""
    h264_nv = get_video_preset("h264_nvenc")
    assert h264_nv.codec_name == "h264_nvenc"
    args_nv = h264_nv.build_video_args(crf=20)
    assert "-c:v" in args_nv and "h264_nvenc" in args_nv
    assert "-cq" in args_nv and "20" in args_nv
    assert "-crf" not in args_nv

    hevc_nv = get_video_preset("hevc_nvenc")
    assert hevc_nv.codec_name == "hevc_nvenc"
    assert hevc_nv.apple_tag == "hvc1"
    args_hevc_nv = hevc_nv.build_video_args(crf=26)
    assert "-cq" in args_hevc_nv and "26" in args_hevc_nv
    assert "-tag:v" in args_hevc_nv and "hvc1" in args_hevc_nv

    h264_va = get_video_preset("h264_vaapi")
    assert h264_va.codec_name == "h264_vaapi"
    args_va = h264_va.build_video_args(crf=22)
    assert "-c:v" in args_va and "h264_vaapi" in args_va
    assert "-qp" in args_va and "22" in args_va


def test_resolve_hardware_preset() -> None:
    """resolve_hardware_preset maps requested backend or auto-probed encoders."""
    from media_toolbox.core.presets import resolve_hardware_preset

    # Explicit backend
    p_nv = resolve_hardware_preset("h264", hwaccel="nvenc")
    assert p_nv.name == "h264_nvenc"

    p_va = resolve_hardware_preset("h265", hwaccel="vaapi")
    assert p_va.name == "hevc_vaapi"

    # None mode returns base preset
    p_none = resolve_hardware_preset("h264", hwaccel="none")
    assert p_none.name == "h264"

    # Auto mode with mocked available encoders
    mock_nv_encoders = {"h264_nvenc", "hevc_nvenc", "libx264"}
    p_auto_nv = resolve_hardware_preset("h264", hwaccel="auto", available_encoders=mock_nv_encoders)
    assert p_auto_nv.name == "h264_nvenc"

    mock_va_encoders = {"h264_vaapi", "hevc_vaapi", "libx264"}
    p_auto_va = resolve_hardware_preset("h264", hwaccel="auto", available_encoders=mock_va_encoders)
    assert p_auto_va.name == "h264_vaapi"

    # Auto mode fallback to CPU when no hardware encoder present
    mock_cpu_only = {"libx264", "libx265"}
    p_auto_cpu = resolve_hardware_preset("h264", hwaccel="auto", available_encoders=mock_cpu_only)
    assert p_auto_cpu.name == "h264"




def test_av1_cli_flags() -> None:
    """AV1 video args include multicore parameters."""
    args = AV1_PRESET.build_video_args()
    assert args == [
        "-c:v", "libaom-av1",
        "-crf", "30",
        "-cpu-used", "4",
        "-row-mt", "1",
        "-pix_fmt", "yuv420p",
    ]


def test_vp9_cli_flags() -> None:
    """VP9 video args include required -b:v 0 in CRF mode."""
    # CRF mode
    crf_args = VP9_PRESET.build_video_args()
    assert crf_args == [
        "-c:v", "libvpx-vp9",
        "-b:v", "0",
        "-crf", "30",
        "-pix_fmt", "yuv420p",
    ]

    # Two-pass mode
    p1_args = VP9_PRESET.build_video_args(
        bitrate_kbps=800,
        pass_num=1,
        pass_logfile="/tmp/pvp9",
    )
    assert p1_args == [
        "-c:v", "libvpx-vp9",
        "-b:v", "800k",
        "-pix_fmt", "yuv420p",
        "-pass", "1",
        "-passlogfile", "/tmp/pvp9",
    ]
    assert "-crf" not in p1_args


def test_prores_cli_flags() -> None:
    """Apple ProRes args format HQ profile 3 and 10-bit 4:2:2 pixel format."""
    args = PRORES_PRESET.build_video_args()
    assert args == [
        "-c:v", "prores_ks",
        "-profile:v", "3",
        "-vendor", "apl0",
        "-pix_fmt", "yuv422p10le",
    ]


def test_gif_cli_flags() -> None:
    """GIF preset flags and capability flags."""
    args = GIF_PRESET.build_video_args()
    assert args == ["-c:v", "gif"]
    assert GIF_PRESET.supports_two_pass is False
    assert GIF_PRESET.supports_crf is False


def test_mp3_cli_flags() -> None:
    """MP3 audio args support extraction, bitrate, and VBR quality."""
    extract = MP3_PRESET.build_audio_args(extract_audio=True)
    assert extract == ["-vn", "-c:a", "libmp3lame", "-b:a", "192k"]

    custom_br = MP3_PRESET.build_audio_args(bitrate_kbps=320)
    assert custom_br == ["-c:a", "libmp3lame", "-b:a", "320k"]

    vbr = MP3_PRESET.build_audio_args(vbr_quality=2)
    assert vbr == ["-c:a", "libmp3lame", "-q:a", "2"]


def test_aac_cli_flags() -> None:
    """AAC audio args format correctly."""
    extract = AAC_PRESET.build_audio_args(extract_audio=True)
    assert extract == ["-vn", "-c:a", "aac", "-b:a", "192k"]

    companion = AAC_PRESET.build_audio_args(bitrate_kbps=128)
    assert companion == ["-c:a", "aac", "-b:a", "128k"]


def test_opus_cli_flags() -> None:
    """Opus audio args format correctly."""
    extract = OPUS_PRESET.build_audio_args(extract_audio=True)
    assert extract == ["-vn", "-c:a", "libopus", "-b:a", "128k"]


def test_flac_cli_flags() -> None:
    """FLAC lossless audio args format with compression level without bitrate."""
    extract = FLAC_PRESET.build_audio_args(extract_audio=True)
    assert extract == ["-vn", "-c:a", "flac", "-compression_level", "5"]
    assert "-b:a" not in extract


def test_container_faststart() -> None:
    """Faststart container flag applies only to MP4/MOV containers."""
    assert get_container_faststart_args("output.mp4") == ["-movflags", "+faststart"]
    assert get_container_faststart_args("output.mov") == ["-movflags", "+faststart"]
    assert get_container_faststart_args("output.m4v") == ["-movflags", "+faststart"]
    assert get_container_faststart_args("output.webm") == []
    assert get_container_faststart_args("output.mkv") == []
    assert get_container_faststart_args("output.gif") == []
    assert get_container_faststart_args("output.mp3") == []


def test_presets_zero_gui() -> None:
    """Presets module must have zero imports from GUI toolkits."""
    target_path = Path(__file__).resolve().parent.parent / "src" / "media_toolbox" / "core" / "presets.py"
    with open(target_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=str(target_path))

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, "module", "") or ""
            for alias in getattr(node, "names", []):
                full_name = f"{mod}.{alias.name}" if mod else alias.name
                assert not any(
                    gui_pkg in full_name
                    for gui_pkg in ("gi", "Gtk", "Adw", "Nautilus", "tkinter", "PyQt", "PySide")
                ), f"Forbidden GUI import found in presets.py: {full_name}"


def test_is_speed_preset() -> None:
    """is_speed_preset correctly classifies CPU speed presets vs format presets."""
    for valid in ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow", "placebo"):
        assert is_speed_preset(valid) is True
        assert is_speed_preset(valid.upper()) is True
        assert is_speed_preset(f"  {valid}  ") is True

    for invalid in ("h264", "h265", "av1", "vp9", "gif", "prores", "mp3", "aac", "opus", "flac", "", None, "invalid_xyz"):
        assert is_speed_preset(invalid) is False


def test_video_preset_build_args_ignores_invalid_speed_preset() -> None:
    """VideoPreset.build_video_args rejects non-speed presets and falls back to default."""
    args_h264 = H264_PRESET.build_video_args(speed_preset="h264")
    assert "-preset" in args_h264
    assert args_h264[args_h264.index("-preset") + 1] == "medium"

    args_h265 = H265_PRESET.build_video_args(speed_preset="h265")
    assert "-preset" in args_h265
    assert args_h265[args_h265.index("-preset") + 1] == "medium"

