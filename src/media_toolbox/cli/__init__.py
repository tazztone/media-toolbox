"""
Standalone Command Line Interface for media_toolbox.

Provides CLI subcommands:
- inspect: Probes media and renders formatted technical metadata or JSON.
- transcode: Video transcoding with presets, CRF/two-pass bitrate, scale, crop, speed.
- extract-audio: Standalone audio track extraction and transcoding.
- install-nautilus / uninstall-nautilus / status-nautilus: Desktop file manager integration.

INVARIANT: Strict zero GUI imports (gi, Gtk, Adw, Nautilus, tkinter, PyQt, PySide, wx).
Only Python standard library and media_toolbox.core domain modules.
"""

from __future__ import annotations

import sys
from typing import Optional, Sequence

from media_toolbox.core.builder import build_ffmpeg_commands
from media_toolbox.core.formatters import (
    format_aspect_ratio,
    format_bitrate,
    format_channels,
    format_decimal_size,
    format_duration,
    format_file_size,
    format_fps,
)
from media_toolbox.core.jobs import run_job, validate_job_paths
from media_toolbox.core.probe import probe_media
from media_toolbox.core.runner import run_ffmpeg_pipeline

from media_toolbox.cli.formatting import (
    create_progress_reporter,
    format_media_info_json,
    media_info_to_dict,
    parse_scale_arg,
    render_media_info_text,
    should_colorize,
)
from media_toolbox.cli.handlers import (
    handle_extract_audio,
    handle_inspect,
    handle_install_nautilus,
    handle_status_nautilus,
    handle_transcode,
    handle_uninstall_nautilus,
)
from media_toolbox.cli.parser import (
    build_parser,
    is_file_like,
    normalize_argv,
)

__all__ = [
    "parse_scale_arg",
    "format_duration",
    "format_file_size",
    "format_decimal_size",
    "format_bitrate",
    "format_aspect_ratio",
    "format_fps",
    "format_channels",
    "render_media_info_text",
    "format_media_info_json",
    "media_info_to_dict",
    "create_progress_reporter",
    "build_parser",
    "normalize_argv",
    "main",
    "probe_media",
    "build_ffmpeg_commands",
    "run_ffmpeg_pipeline",
    "run_job",
    "validate_job_paths",
    "handle_install_nautilus",
    "handle_uninstall_nautilus",
    "handle_status_nautilus",
]


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI execution entrypoint. Returns integer exit code."""
    raw_args = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()

    norm_args = normalize_argv(raw_args)
    args = parser.parse_args(norm_args)

    if args.subcommand == "inspect":
        return handle_inspect(args)
    elif args.subcommand == "transcode":
        if not (args.output or args.output_opt):
            parser.error("the following arguments are required: output (positional or -o/--output)")
        return handle_transcode(args)
    elif args.subcommand == "extract-audio":
        if not (args.output or args.output_opt):
            parser.error("the following arguments are required: output (positional or -o/--output)")
        return handle_extract_audio(args)
    elif args.subcommand == "install-nautilus":
        return handle_install_nautilus(args)
    elif args.subcommand == "uninstall-nautilus":
        return handle_uninstall_nautilus(args)
    elif args.subcommand == "status-nautilus":
        return handle_status_nautilus(args)

    return 0
