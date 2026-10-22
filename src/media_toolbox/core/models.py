"""
Core domain models for media_toolbox.

This module defines frozen dataclasses representing inspected media streams,
container metadata, progress events, and encoding parameters.

INVARIANT: Must have ZERO imports from GUI toolkits (gi, Gtk, Adw, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass


class MediaToolboxError(Exception):
    """Base exception for media_toolbox domain errors."""


class InvalidOptionsError(MediaToolboxError, ValueError):
    """Raised when options or parameters fail validation."""


class ProbeError(MediaToolboxError):
    """Raised when probing media fails or returns invalid metadata."""


class FileCollisionError(MediaToolboxError):
    """Raised when input and output resolve to the same underlying file."""


class DestinationExistsError(MediaToolboxError):
    """Raised when the target output file exists and overwrite was not permitted."""


class OutputPublishError(MediaToolboxError):
    """Raised when the finished output cannot be validated or published."""


class TargetSizeTooSmallError(MediaToolboxError):
    """Raised when the requested target file size is too small for media duration and audio budget."""

    def __init__(
        self,
        target_size_mb: float,
        duration_seconds: float,
        audio_bitrate_kbps: int,
        min_required_mb: float,
        min_video_bitrate_kbps: int = 64,
        message: str = "",
    ) -> None:
        self.target_size_mb = target_size_mb
        self.duration_seconds = duration_seconds
        self.audio_bitrate_kbps = audio_bitrate_kbps
        self.min_required_mb = min_required_mb
        self.min_video_bitrate_kbps = min_video_bitrate_kbps
        msg = (
            message
            or f"Target size {target_size_mb:.2f} MB is unattainable for {duration_seconds:.1f}s media. "
            f"Minimum achievable size is ~{min_required_mb:.2f} MB (at {min_video_bitrate_kbps} kbps video floor + {audio_bitrate_kbps} kbps audio)."
        )
        super().__init__(msg)


@dataclass(frozen=True, slots=True)
class VideoStream:
    """Represents an inspected video or image track in a container."""

    index: int
    codec_name: str
    width: int
    height: int
    fps: float | None = None
    bit_rate: int | None = None
    duration: float | None = None
    pix_fmt: str | None = None
    rotation: int = 0
    is_attached_pic: bool = False

    @property
    def resolution(self) -> tuple[int, int]:
        """Video dimensions as (width, height)."""
        return (self.width, self.height)

    @property
    def aspect_ratio(self) -> float:
        """Display aspect ratio width / height (0.0 if invalid)."""
        return (self.width / self.height) if self.height > 0 else 0.0

    @property
    def effective_dimensions(self) -> tuple[int, int]:
        """Dimensions after compensating for 90 or 270 degree rotation."""
        normalized_rot = (self.rotation % 360 + 360) % 360
        if normalized_rot in (90, 270):
            return (self.height, self.width)
        return (self.width, self.height)

    @property
    def display_resolution(self) -> str:
        """Formatted string representation of resolution (e.g. '1920x1080')."""
        return f"{self.width}x{self.height}"


@dataclass(frozen=True, slots=True)
class AudioStream:
    """Represents an inspected audio track in a container."""

    index: int
    codec_name: str
    channels: int
    sample_rate: int
    channel_layout: str | None = None
    bit_rate: int | None = None
    duration: float | None = None

    @property
    def bit_rate_kbps(self) -> int | None:
        """Bitrate in kbps (rounded), or None if unknown."""
        return round(self.bit_rate / 1000) if self.bit_rate is not None else None

    @property
    def sample_rate_khz(self) -> float:
        """Sample rate in kHz (e.g. 44.1, 48.0)."""
        return self.sample_rate / 1000.0


@dataclass(frozen=True, slots=True)
class FormatInfo:
    """Represents container-level metadata."""

    filename: str
    format_name: str
    duration: float | None = None
    size_bytes: int | None = None
    bit_rate: int | None = None

    @property
    def size_mb(self) -> float | None:
        """Container size in mebibytes (MiB), or None if unknown."""
        return (
            round(self.size_bytes / (1024 * 1024), 2)
            if self.size_bytes is not None
            else None
        )

    @property
    def bit_rate_kbps(self) -> int | None:
        """Total container bitrate in kbps, or None if unknown."""
        return round(self.bit_rate / 1000) if self.bit_rate is not None else None


@dataclass(frozen=True, slots=True)
class MediaInfo:
    """
    Composite media metadata representing format and all constituent streams.

    Guarantees immutable tuple collections and defensive primary stream resolution.
    """

    format: FormatInfo
    video_streams: tuple[VideoStream, ...] = ()
    audio_streams: tuple[AudioStream, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.video_streams, tuple):
            object.__setattr__(self, "video_streams", tuple(self.video_streams))
        if not isinstance(self.audio_streams, tuple):
            object.__setattr__(self, "audio_streams", tuple(self.audio_streams))

    @property
    def primary_video(self) -> VideoStream | None:
        """
        First video stream that is not an attached picture (e.g. album cover art).
        Returns None for audio-only media or media with only cover art.
        """
        for s in self.video_streams:
            if not s.is_attached_pic:
                return s
        return None

    @property
    def primary_audio(self) -> AudioStream | None:
        """First audio stream in the media, or None if silent/video-only."""
        return self.audio_streams[0] if self.audio_streams else None

    @property
    def has_video(self) -> bool:
        """True if media contains a true video stream (excluding attached cover art)."""
        return self.primary_video is not None

    @property
    def has_audio(self) -> bool:
        """True if media contains at least one audio stream."""
        return self.primary_audio is not None

    @property
    def duration(self) -> float:
        """
        Resolved media presentation duration in seconds.
        Falls back from format duration to primary video, then primary audio.
        Returns 0.0 if duration cannot be resolved (e.g. still images).
        """
        if self.format.duration is not None and self.format.duration > 0:
            return self.format.duration
        if (
            self.primary_video
            and self.primary_video.duration is not None
            and self.primary_video.duration > 0
        ):
            return self.primary_video.duration
        if (
            self.primary_audio
            and self.primary_audio.duration is not None
            and self.primary_audio.duration > 0
        ):
            return self.primary_audio.duration
        return 0.0

    @property
    def attached_pics(self) -> tuple[VideoStream, ...]:
        """Tuple of attached pictures (e.g. ID3 APIC cover art)."""
        return tuple(s for s in self.video_streams if s.is_attached_pic)

    @property
    def is_audio_only(self) -> bool:
        """True if file has audio but no primary video stream."""
        return self.has_audio and not self.has_video

    @property
    def is_video_only(self) -> bool:
        """True if file has video but no audio stream."""
        return self.has_video and not self.has_audio

    @property
    def is_image(self) -> bool:
        """True if file is a still image (video stream with 0 duration and no audio)."""
        return self.has_video and self.duration == 0.0 and not self.has_audio


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """Emitted by runner on FFmpeg -progress pipe:1 updates."""

    frame: int = 0
    fps: float = 0.0
    out_time_seconds: float = 0.0
    total_size_bytes: int = 0
    speed: float | None = None
    percentage: float = 0.0
    eta_seconds: float | None = None
    is_completed: bool = False

    @property
    def speed_str(self) -> str:
        """Formatted speed multiplier (e.g. '2.50x' or 'N/A')."""
        return f"{self.speed:.2f}x" if self.speed is not None else "N/A"

    @property
    def eta_str(self) -> str:
        """Formatted ETA as MM:SS or HH:MM:SS, or 'N/A'."""
        if self.eta_seconds is None or self.eta_seconds < 0:
            return "N/A"
        secs = int(self.eta_seconds)
        mins, secs = divmod(secs, 60)
        hours, mins = divmod(mins, 60)
        if hours > 0:
            return f"{hours:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"


@dataclass(frozen=True, slots=True)
class EncodeOptions:
    """
    Encoding parameters passed to filtergraph and command builders.
    Forward-compatible contract for Milestone 2.
    """

    target_size_mb: float | None = None
    crf: int | None = None
    video_codec: str = "libx264"
    audio_codec: str | None = None
    audio_bitrate_kbps: int = 128
    scale: tuple[int, int] | None = None
    crop: str | None = None
    pad: str | None = None
    speed: float | None = None
    fps: int | None = None
    mute_audio: bool = False
    extract_audio: bool = False
    normalize_audio: bool = False
    volume_boost_db: float | None = None
    two_pass: bool = False
    preset: str | None = None
    speed_preset: str | None = None
    strict_size: bool = False
    audio_track_index: int | None = None
    keep_subtitles: bool = False
    copy_metadata: bool = False
    copy_chapters: bool = False
    gif_max_colors: int = 256
    gif_dither: str = "sierra2_4a"
    gif_stats_mode: str | None = None
    hwaccel: str | None = None
    extra_args: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.extra_args, tuple):
            object.__setattr__(self, "extra_args", tuple(self.extra_args))


@dataclass(frozen=True, slots=True)
class ResolvedJobSpec:
    """
    Effective encoding specification resolved from user options, codec presets,
    and probed media stream layout.
    """

    operation: str  # 'transcode' | 'extract_audio'
    rate_mode: str  # 'crf' | 'target_size' | 'prores' | 'gif' | 'extract_audio'
    video_codec: str | None = None
    audio_codec: str | None = None
    video_preset_name: str | None = None
    audio_preset_name: str | None = None
    video_stream_index: int | None = None
    audio_stream_index: int | None = None
    container_extension: str | None = None
    crf: int | None = None
    target_size_mb: float | None = None
    two_pass: bool = False
