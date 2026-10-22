"""
Codec and format preset definitions for media_toolbox.

This module provides frozen dataclasses, enums, and deterministic argument
generators for 10 industry-standard video and audio codecs:
- Video: H.264, H.265, AV1, VP9, GIF, ProRes
- Audio: MP3, AAC, Opus, FLAC

INVARIANT: Must have ZERO imports from GUI toolkits (gi, Gtk, Adw, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import shutil
import subprocess
from typing import Any, Optional


class PresetName(str, Enum):
    """Canonical preset keys."""
    # Video
    H264 = "h264"
    H265 = "h265"
    AV1 = "av1"
    VP9 = "vp9"
    GIF = "gif"
    PRORES = "prores"
    H264_NVENC = "h264_nvenc"
    HEVC_NVENC = "hevc_nvenc"
    H264_VAAPI = "h264_vaapi"
    HEVC_VAAPI = "hevc_vaapi"
    H264_QSV = "h264_qsv"
    HEVC_QSV = "hevc_qsv"

    # Audio
    MP3 = "mp3"
    AAC = "aac"
    OPUS = "opus"
    FLAC = "flac"


@dataclass(frozen=True, slots=True)
class VideoPreset:
    """
    Video codec preset specification and CLI argument generator.
    """
    name: str
    display_name: str
    codec_name: str
    default_extension: str
    compatible_extensions: tuple[str, ...]
    default_crf: Optional[int] = None
    crf_range: Optional[tuple[int, int]] = None
    default_speed_preset: Optional[str] = None
    default_pix_fmt: Optional[str] = "yuv420p"
    default_audio_codec: Optional[str] = "aac"
    compatible_audio_codecs: tuple[str, ...] = ("aac", "libmp3lame", "libopus", "flac")
    supports_two_pass: bool = True
    supports_crf: bool = True
    apple_tag: Optional[str] = None
    prores_profile: Optional[int] = None
    extra_video_args: tuple[str, ...] = ()
    description: str = ""
    crf_arg: str = "-crf"

    def build_video_args(
        self,
        crf: Optional[int] = None,
        bitrate_kbps: Optional[int] = None,
        pass_num: Optional[int] = None,
        pass_logfile: Optional[str] = None,
        speed_preset: Optional[str] = None,
        pix_fmt: Optional[str] = None,
    ) -> list[str]:
        """
        Build deterministic FFmpeg video codec arguments.

        Handles:
        1. Two-pass bitrate targeting (-pass 1 / -pass 2, -b:v).
        2. Single-pass CRF mode (-crf, with -b:v 0 for VP9).
        3. ProRes profile encoding (-profile:v, -vendor).
        4. GIF palette handling (returns -c:v gif).
        """
        args: list[str] = []

        # Codec selection
        args.extend(["-c:v", self.codec_name])

        if (pass_num is not None or bitrate_kbps is not None) and not self.supports_two_pass:
            raise ValueError(
                f"Preset '{self.name}' ({self.codec_name}) does not support two-pass bitrate encoding"
            )

        # ProRes master encoding
        if self.codec_name == "prores_ks":
            profile = self.prores_profile if self.prores_profile is not None else 3
            args.extend(["-profile:v", str(profile), "-vendor", "apl0"])
            fmt = pix_fmt or self.default_pix_fmt or "yuv422p10le"
            args.extend(["-pix_fmt", fmt])
            return args

        # GIF encoding
        if self.codec_name == "gif":
            return args

        # Two-pass bitrate mode
        if pass_num is not None and bitrate_kbps is not None:
            if not self.supports_two_pass:
                raise ValueError(
                    f"Preset '{self.name}' ({self.codec_name}) does not support two-pass bitrate encoding"
                )
            args.extend(["-b:v", f"{int(bitrate_kbps)}k"])
            preset = (
                speed_preset.strip().lower()
                if speed_preset and is_speed_preset(speed_preset)
                else self.default_speed_preset
            )
            if preset:
                args.extend(["-preset", preset])
            if self.apple_tag:
                args.extend(["-tag:v", self.apple_tag])
            args.extend(self.extra_video_args)
            fmt = pix_fmt or self.default_pix_fmt
            if fmt:
                args.extend(["-pix_fmt", fmt])

            if self.codec_name == "libx265":
                x265_opts = [f"pass={pass_num}"]
                if pass_logfile:
                    x265_opts.append(f"stats={pass_logfile}")
                args.extend(["-x265-params", ":".join(x265_opts)])
            else:
                args.extend(["-pass", str(pass_num)])
                if pass_logfile:
                    args.extend(["-passlogfile", pass_logfile])
            return args

        # Single-pass CRF mode
        effective_crf = crf if crf is not None else self.default_crf
        if effective_crf is not None:
            if self.codec_name == "libvpx-vp9":
                # Crucial FFmpeg rule: libvpx-vp9 requires -b:v 0 for true CRF mode
                args.extend(["-b:v", "0"])
            args.extend([self.crf_arg, str(effective_crf)])

        preset = (
            speed_preset.strip().lower()
            if speed_preset and is_speed_preset(speed_preset)
            else self.default_speed_preset
        )
        if preset:
            args.extend(["-preset", preset])
        if self.apple_tag:
            args.extend(["-tag:v", self.apple_tag])
        args.extend(self.extra_video_args)
        fmt = pix_fmt or self.default_pix_fmt
        if fmt:
            args.extend(["-pix_fmt", fmt])
        return args

    def build_container_args(self, container_ext: str) -> list[str]:
        """
        Return container-specific global flags (e.g. -movflags +faststart for MP4/MOV).
        """
        return get_container_faststart_args(container_ext)


@dataclass(frozen=True, slots=True)
class AudioPreset:
    """
    Audio codec preset specification and CLI argument generator.
    """
    name: str
    display_name: str
    codec_name: str
    default_extension: str
    compatible_extensions: tuple[str, ...]
    default_bitrate_kbps: Optional[int] = 192
    bitrate_range_kbps: Optional[tuple[int, int]] = (64, 320)
    is_lossless: bool = False
    default_vbr_quality: Optional[int] = None
    compression_level: Optional[int] = None
    description: str = ""

    def build_audio_args(
        self,
        bitrate_kbps: Optional[int] = None,
        extract_audio: bool = False,
        vbr_quality: Optional[int] = None,
    ) -> list[str]:
        """
        Build deterministic FFmpeg audio codec arguments.
        """
        args: list[str] = []
        if extract_audio:
            args.append("-vn")

        args.extend(["-c:a", self.codec_name])

        if self.is_lossless:
            lvl = self.compression_level if self.compression_level is not None else 5
            args.extend(["-compression_level", str(lvl)])
            return args

        # VBR quality mode (e.g. MP3 -q:a 2)
        if vbr_quality is not None or (self.default_vbr_quality is not None and bitrate_kbps is None):
            q = vbr_quality if vbr_quality is not None else self.default_vbr_quality
            args.extend(["-q:a", str(q)])
            return args

        # CBR/ABR bitrate mode
        effective_kbps = bitrate_kbps if bitrate_kbps is not None else self.default_bitrate_kbps
        if effective_kbps is not None:
            args.extend(["-b:a", f"{int(effective_kbps)}k"])

        return args


def get_container_faststart_args(container_ext: str) -> list[str]:
    """
    Return container-specific flags (-movflags +faststart for MP4/MOV/M4V).
    Accepts full filenames (e.g. 'output.mp4'), extensions with leading dot ('.mp4'),
    or bare extensions ('mp4').
    """
    if "." in container_ext:
        ext = container_ext.rsplit(".", 1)[-1].lower()
    else:
        ext = container_ext.strip().lower()
    if ext in ("mp4", "mov", "m4v"):
        return ["-movflags", "+faststart"]
    return []


# --- Preset Definitions ---

H264_PRESET = VideoPreset(
    name="h264",
    display_name="H.264 / AVC",
    codec_name="libx264",
    default_extension="mp4",
    compatible_extensions=("mp4", "mkv", "mov", "ts"),
    default_crf=23,
    crf_range=(0, 51),
    default_speed_preset="medium",
    default_pix_fmt="yuv420p",
    default_audio_codec="aac",
    compatible_audio_codecs=("aac", "libmp3lame", "libopus", "flac"),
    supports_two_pass=True,
    supports_crf=True,
    description="Universal compatibility MP4 video suitable for web, mobile, and legacy players.",
)

H265_PRESET = VideoPreset(
    name="h265",
    display_name="H.265 / HEVC",
    codec_name="libx265",
    default_extension="mp4",
    compatible_extensions=("mp4", "mkv", "mov"),
    default_crf=28,
    crf_range=(0, 51),
    default_speed_preset="medium",
    default_pix_fmt="yuv420p",
    default_audio_codec="aac",
    compatible_audio_codecs=("aac", "libmp3lame", "libopus", "flac"),
    supports_two_pass=True,
    supports_crf=True,
    apple_tag="hvc1",
    description="High-efficiency video coding with Apple ecosystem tag (hvc1).",
)

AV1_PRESET = VideoPreset(
    name="av1",
    display_name="AV1",
    codec_name="libaom-av1",
    default_extension="mp4",
    compatible_extensions=("mp4", "mkv", "webm"),
    default_crf=30,
    crf_range=(0, 63),
    default_speed_preset=None,
    default_pix_fmt="yuv420p",
    default_audio_codec="libopus",
    compatible_audio_codecs=("libopus", "aac", "flac"),
    supports_two_pass=True,
    supports_crf=True,
    extra_video_args=("-cpu-used", "4", "-row-mt", "1"),
    description="Next-generation royalty-free open video standard.",
)

VP9_PRESET = VideoPreset(
    name="vp9",
    display_name="VP9 / WebM",
    codec_name="libvpx-vp9",
    default_extension="webm",
    compatible_extensions=("webm", "mkv"),
    default_crf=30,
    crf_range=(0, 63),
    default_speed_preset=None,
    default_pix_fmt="yuv420p",
    default_audio_codec="libopus",
    compatible_audio_codecs=("libopus", "vorbis"),
    supports_two_pass=True,
    supports_crf=True,
    description="Standard open web video format optimized for HTML5 players.",
)

GIF_PRESET = VideoPreset(
    name="gif",
    display_name="Animated GIF",
    codec_name="gif",
    default_extension="gif",
    compatible_extensions=("gif",),
    default_crf=None,
    crf_range=None,
    default_pix_fmt=None,
    default_audio_codec=None,
    compatible_audio_codecs=(),
    supports_two_pass=False,
    supports_crf=False,
    description="Paletted animated GIF utilizing two-stage palettegen/paletteuse filter.",
)

PRORES_PRESET = VideoPreset(
    name="prores",
    display_name="Apple ProRes",
    codec_name="prores_ks",
    default_extension="mov",
    compatible_extensions=("mov", "mkv"),
    default_crf=None,
    crf_range=None,
    default_speed_preset=None,
    default_pix_fmt="yuv422p10le",
    default_audio_codec="pcm_s16le",
    compatible_audio_codecs=("pcm_s16le", "pcm_s24le", "aac"),
    supports_two_pass=False,
    supports_crf=False,
    prores_profile=3,
    description="Apple ProRes 422 HQ broadcast master editing format.",
)

H264_NVENC_PRESET = VideoPreset(
    name="h264_nvenc",
    display_name="H.264 (NVIDIA NVENC)",
    codec_name="h264_nvenc",
    default_extension="mp4",
    compatible_extensions=("mp4", "mkv", "mov", "ts"),
    default_crf=23,
    crf_range=(0, 51),
    crf_arg="-cq",
    default_speed_preset="p4",
    default_pix_fmt="yuv420p",
    default_audio_codec="aac",
    compatible_audio_codecs=("aac", "libmp3lame", "libopus", "flac"),
    supports_two_pass=False,
    supports_crf=True,
    description="Hardware-accelerated H.264 video encoding via NVIDIA NVENC.",
)

HEVC_NVENC_PRESET = VideoPreset(
    name="hevc_nvenc",
    display_name="H.265 / HEVC (NVIDIA NVENC)",
    codec_name="hevc_nvenc",
    default_extension="mp4",
    compatible_extensions=("mp4", "mkv", "mov"),
    default_crf=28,
    crf_range=(0, 51),
    crf_arg="-cq",
    default_speed_preset="p4",
    default_pix_fmt="yuv420p",
    default_audio_codec="aac",
    compatible_audio_codecs=("aac", "libmp3lame", "libopus", "flac"),
    supports_two_pass=False,
    supports_crf=True,
    apple_tag="hvc1",
    description="Hardware-accelerated HEVC video encoding via NVIDIA NVENC.",
)

H264_VAAPI_PRESET = VideoPreset(
    name="h264_vaapi",
    display_name="H.264 (VAAPI)",
    codec_name="h264_vaapi",
    default_extension="mp4",
    compatible_extensions=("mp4", "mkv", "mov", "ts"),
    default_crf=23,
    crf_range=(0, 51),
    crf_arg="-qp",
    default_speed_preset=None,
    default_pix_fmt=None,
    default_audio_codec="aac",
    compatible_audio_codecs=("aac", "libmp3lame", "libopus", "flac"),
    supports_two_pass=False,
    supports_crf=True,
    description="Hardware-accelerated H.264 video encoding via VAAPI (Intel/AMD).",
)

HEVC_VAAPI_PRESET = VideoPreset(
    name="hevc_vaapi",
    display_name="H.265 / HEVC (VAAPI)",
    codec_name="hevc_vaapi",
    default_extension="mp4",
    compatible_extensions=("mp4", "mkv", "mov"),
    default_crf=28,
    crf_range=(0, 51),
    crf_arg="-qp",
    default_speed_preset=None,
    default_pix_fmt=None,
    default_audio_codec="aac",
    compatible_audio_codecs=("aac", "libmp3lame", "libopus", "flac"),
    supports_two_pass=False,
    supports_crf=True,
    apple_tag="hvc1",
    description="Hardware-accelerated HEVC video encoding via VAAPI (Intel/AMD).",
)

H264_QSV_PRESET = VideoPreset(
    name="h264_qsv",
    display_name="H.264 (Intel QuickSync)",
    codec_name="h264_qsv",
    default_extension="mp4",
    compatible_extensions=("mp4", "mkv", "mov", "ts"),
    default_crf=23,
    crf_range=(0, 51),
    crf_arg="-global_quality",
    default_speed_preset="medium",
    default_pix_fmt="nv12",
    default_audio_codec="aac",
    compatible_audio_codecs=("aac", "libmp3lame", "libopus", "flac"),
    supports_two_pass=False,
    supports_crf=True,
    description="Hardware-accelerated H.264 video encoding via Intel QuickSync.",
)

HEVC_QSV_PRESET = VideoPreset(
    name="hevc_qsv",
    display_name="H.265 / HEVC (Intel QuickSync)",
    codec_name="hevc_qsv",
    default_extension="mp4",
    compatible_extensions=("mp4", "mkv", "mov"),
    default_crf=28,
    crf_range=(0, 51),
    crf_arg="-global_quality",
    default_speed_preset="medium",
    default_pix_fmt="nv12",
    default_audio_codec="aac",
    compatible_audio_codecs=("aac", "libmp3lame", "libopus", "flac"),
    supports_two_pass=False,
    supports_crf=True,
    apple_tag="hvc1",
    description="Hardware-accelerated HEVC video encoding via Intel QuickSync.",
)

MP3_PRESET = AudioPreset(
    name="mp3",
    display_name="MP3 (LAME)",
    codec_name="libmp3lame",
    default_extension="mp3",
    compatible_extensions=("mp3",),
    default_bitrate_kbps=192,
    bitrate_range_kbps=(64, 320),
    is_lossless=False,
    default_vbr_quality=None,
    description="MPEG Audio Layer III encoded via LAME.",
)

AAC_PRESET = AudioPreset(
    name="aac",
    display_name="AAC",
    codec_name="aac",
    default_extension="m4a",
    compatible_extensions=("m4a", "aac"),
    default_bitrate_kbps=192,
    bitrate_range_kbps=(64, 320),
    is_lossless=False,
    description="Advanced Audio Coding standard format.",
)

OPUS_PRESET = AudioPreset(
    name="opus",
    display_name="Opus",
    codec_name="libopus",
    default_extension="opus",
    compatible_extensions=("opus", "ogg"),
    default_bitrate_kbps=128,
    bitrate_range_kbps=(32, 256),
    is_lossless=False,
    description="Highly efficient open audio codec for speech and music.",
)

FLAC_PRESET = AudioPreset(
    name="flac",
    display_name="FLAC (Lossless)",
    codec_name="flac",
    default_extension="flac",
    compatible_extensions=("flac", "ogg"),
    default_bitrate_kbps=None,
    bitrate_range_kbps=None,
    is_lossless=True,
    compression_level=5,
    description="Free Lossless Audio Codec preserving bit-perfect audio.",
)

VIDEO_PRESETS: dict[str, VideoPreset] = {
    "h264": H264_PRESET,
    "h265": H265_PRESET,
    "av1": AV1_PRESET,
    "vp9": VP9_PRESET,
    "gif": GIF_PRESET,
    "prores": PRORES_PRESET,
    "h264_nvenc": H264_NVENC_PRESET,
    "hevc_nvenc": HEVC_NVENC_PRESET,
    "h264_vaapi": H264_VAAPI_PRESET,
    "hevc_vaapi": HEVC_VAAPI_PRESET,
    "h264_qsv": H264_QSV_PRESET,
    "hevc_qsv": HEVC_QSV_PRESET,
}

AUDIO_PRESETS: dict[str, AudioPreset] = {
    "mp3": MP3_PRESET,
    "aac": AAC_PRESET,
    "opus": OPUS_PRESET,
    "flac": FLAC_PRESET,
}

VALID_SPEED_PRESETS: frozenset[str] = frozenset({
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
    "placebo",
    "p1",
    "p2",
    "p3",
    "p4",
    "p5",
    "p6",
    "p7",
})


def is_speed_preset(name: str | Enum | None) -> bool:
    """Return True if name is a recognized FFmpeg encoder speed preset."""
    if not name:
        return False
    return getattr(name, "value", str(name)).strip().lower() in VALID_SPEED_PRESETS


_PRESET_ALIASES: dict[str, str] = {
    # Video aliases
    "h264": "h264",
    "h.264": "h264",
    "x264": "h264",
    "libx264": "h264",
    "avc": "h264",
    "h265": "h265",
    "h.265": "h265",
    "x265": "h265",
    "libx265": "h265",
    "hevc": "h265",
    "av1": "av1",
    "libaom-av1": "av1",
    "aom": "av1",
    "vp9": "vp9",
    "libvpx-vp9": "vp9",
    "vpx-vp9": "vp9",
    "webm": "vp9",
    "gif": "gif",
    "animated_gif": "gif",
    "prores": "prores",
    "prores_ks": "prores",
    "apple_prores": "prores",
    "discord": "h264",
    "discord-h264": "h264",
    # Hardware video aliases
    "nvenc": "h264_nvenc",
    "nvenc_h264": "h264_nvenc",
    "h264-nvenc": "h264_nvenc",
    "nvenc_hevc": "hevc_nvenc",
    "nvenc_h265": "hevc_nvenc",
    "hevc-nvenc": "hevc_nvenc",
    "h265_nvenc": "hevc_nvenc",
    "h265-nvenc": "hevc_nvenc",
    "vaapi": "h264_vaapi",
    "vaapi_h264": "h264_vaapi",
    "h264-vaapi": "h264_vaapi",
    "vaapi_hevc": "hevc_vaapi",
    "vaapi_h265": "hevc_vaapi",
    "hevc-vaapi": "hevc_vaapi",
    "h265_vaapi": "hevc_vaapi",
    "h265-vaapi": "hevc_vaapi",
    "qsv": "h264_qsv",
    "qsv_h264": "h264_qsv",
    "h264-qsv": "h264_qsv",
    "qsv_hevc": "hevc_qsv",
    "qsv_h265": "hevc_qsv",
    "hevc-qsv": "hevc_qsv",
    "h265_qsv": "hevc_qsv",
    "h265-qsv": "hevc_qsv",
    # Audio aliases
    "mp3": "mp3",
    "libmp3lame": "mp3",
    "lame": "mp3",
    "aac": "aac",
    "m4a": "aac",
    "opus": "opus",
    "libopus": "opus",
    "ogg_opus": "opus",
    "flac": "flac",
    "lossless_audio": "flac",
}


def _normalize_preset_key(name: Any) -> str:
    key = getattr(name, "value", str(name)).strip().lower()
    return _PRESET_ALIASES.get(key, key)


def get_video_preset(name: str | PresetName) -> VideoPreset:
    """Retrieve video preset by canonical name, enum, or alias."""
    resolved = _normalize_preset_key(name)
    if resolved in VIDEO_PRESETS:
        return VIDEO_PRESETS[resolved]
    raise KeyError(f"Unknown video preset '{name}'. Available: {list(VIDEO_PRESETS.keys())}")


def get_audio_preset(name: str | PresetName) -> AudioPreset:
    """Retrieve audio preset by canonical name, enum, or alias."""
    resolved = _normalize_preset_key(name)
    if resolved in AUDIO_PRESETS:
        return AUDIO_PRESETS[resolved]
    raise KeyError(f"Unknown audio preset '{name}'. Available: {list(AUDIO_PRESETS.keys())}")


def get_preset(name: str | PresetName) -> VideoPreset | AudioPreset:
    """Retrieve either video or audio preset by name or alias."""
    resolved = _normalize_preset_key(name)
    if resolved in VIDEO_PRESETS:
        return VIDEO_PRESETS[resolved]
    if resolved in AUDIO_PRESETS:
        return AUDIO_PRESETS[resolved]
    all_keys = list(VIDEO_PRESETS.keys()) + list(AUDIO_PRESETS.keys())
    raise KeyError(f"Unknown preset '{name}'. Available presets: {all_keys}")


def is_audio_preset(name: str | PresetName | None) -> bool:
    """Return True if name or alias corresponds to an audio preset."""
    if not name:
        return False
    return _normalize_preset_key(name) in AUDIO_PRESETS


def is_video_preset(name: str | PresetName | None) -> bool:
    """Return True if name or alias corresponds to a video preset."""
    if not name:
        return False
    return _normalize_preset_key(name) in VIDEO_PRESETS


def list_video_presets() -> list[VideoPreset]:
    """Return all registered video presets in standard order."""
    return list(VIDEO_PRESETS.values())


def list_audio_presets() -> list[AudioPreset]:
    """Return all registered audio presets in standard order."""
    return list(AUDIO_PRESETS.values())


def get_available_encoders(executable: Optional[str] = None) -> set[str]:
    """
    Return all available encoder names supported by the host FFmpeg installation.
    """
    ffmpeg_bin = executable or shutil.which("ffmpeg") or "ffmpeg"
    try:
        proc = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        encoders: set[str] = set()
        for line in proc.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and len(parts[0]) == 6:
                encoders.add(parts[1])
        return encoders
    except Exception:
        return set()


def check_encoder_available(codec_name: str, executable: Optional[str] = None) -> bool:
    """
    Detect if the host FFmpeg installation has support for the requested encoder.

    Args:
        codec_name: Target encoder name (e.g. 'libx265', 'libx264', 'libvpx-vp9').
        executable: Optional FFmpeg binary path.
    """
    return codec_name in get_available_encoders(executable)


def resolve_hardware_preset(
    base_preset: str,
    hwaccel: str = "auto",
    available_encoders: Optional[set[str]] = None,
    executable: Optional[str] = None,
) -> VideoPreset:
    """
    Resolve requested base preset (e.g. 'h264', 'h265') to a hardware-accelerated preset
    if available and requested, otherwise return the standard video preset.
    """
    canon = _normalize_preset_key(base_preset)
    mode = (hwaccel or "none").strip().lower()
    if mode == "none" or canon not in ("h264", "h265"):
        return get_video_preset(base_preset)

    prefix = "hevc" if canon == "h265" else "h264"

    # Explicit backend
    if mode in ("nvenc", "vaapi", "qsv"):
        candidate_name = f"{prefix}_{mode}"
        if candidate_name in VIDEO_PRESETS:
            return VIDEO_PRESETS[candidate_name]
        return get_video_preset(base_preset)

    # Auto backend: probe available encoders with priority nvenc -> vaapi -> qsv
    if mode == "auto":
        encoders = available_encoders if available_encoders is not None else get_available_encoders(executable)
        for backend in ("nvenc", "vaapi", "qsv"):
            cand = f"{prefix}_{backend}"
            if cand in encoders and cand in VIDEO_PRESETS:
                return VIDEO_PRESETS[cand]

    return get_video_preset(base_preset)


