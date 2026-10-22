"""
Core engine for media_toolbox.

Provides domain models, probing, bitrate math, filtergraphs, presets, builder, and runner.
INVARIANT: ZERO GUI imports.
"""

from media_toolbox.core.bitrate import (
    DEFAULT_AUDIO_BITRATE_KBPS,
    DEFAULT_MIN_VIDEO_BITRATE_KBPS,
    DEFAULT_MUX_OVERHEAD_MARGIN,
    calculate_target_video_bitrate,
)
from media_toolbox.core.models import (
    AudioStream,
    EncodeOptions,
    FormatInfo,
    MediaInfo,
    MediaToolboxError,
    ProbeError,
    ProgressEvent,
    VideoStream,
)
from media_toolbox.core.probe import (
    parse_frame_rate,
    parse_optional_float,
    parse_optional_int,
    parse_probe_json,
    parse_rotation,
    parse_stream_fps,
    probe_media,
)
from media_toolbox.core.runner import (
    ProgressParser,
    RunnerCancelledError,
    RunnerError,
    parse_progress_stream,
    run_ffmpeg,
    run_ffmpeg_pipeline,
)

__all__ = [
    "DEFAULT_AUDIO_BITRATE_KBPS",
    "DEFAULT_MIN_VIDEO_BITRATE_KBPS",
    "DEFAULT_MUX_OVERHEAD_MARGIN",
    "AudioStream",
    "EncodeOptions",
    "FormatInfo",
    "MediaInfo",
    "MediaToolboxError",
    "ProbeError",
    "ProgressEvent",
    "ProgressParser",
    "RunnerCancelledError",
    "RunnerError",
    "VideoStream",
    "calculate_target_video_bitrate",
    "parse_frame_rate",
    "parse_optional_float",
    "parse_optional_int",
    "parse_probe_json",
    "parse_progress_stream",
    "parse_rotation",
    "parse_stream_fps",
    "probe_media",
    "run_ffmpeg",
    "run_ffmpeg_pipeline",
]
