"""
CLI argument parser configuration and argument normalization logic.

Zero GUI dependencies: only standard library argparse and pathlib.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from media_toolbox import __version__


def is_file_like(arg: str) -> bool:
    """Check if arg looks like a file path rather than a command name."""
    if Path(arg).exists():
        return True
    if "/" in arg or "\\" in arg:
        return True
    name = Path(arg).name
    if "." in name and not name.startswith("."):
        return True
    return False


def normalize_argv(argv: Sequence[str]) -> list[str]:
    """Normalize argv to support shortcut syntax and flag aliases."""
    args_list = list(argv)
    if not args_list:
        return args_list
    first = args_list[0]

    # Map flag aliases for nautilus commands
    flag_aliases = {
        "--install-nautilus": "install-nautilus",
        "--uninstall-nautilus": "uninstall-nautilus",
        "--status-nautilus": "status-nautilus",
    }
    if first in flag_aliases:
        return [flag_aliases[first]] + args_list[1:]

    known_commands = {
        "inspect",
        "transcode",
        "extract-audio",
        "install-nautilus",
        "uninstall-nautilus",
        "status-nautilus",
    }
    known_flags = {"-h", "--help", "-v", "--version"}
    if first in known_commands or first in known_flags:
        return args_list
    if first.startswith("-"):
        return args_list
    if is_file_like(first):
        return ["inspect"] + args_list
    return args_list


def build_parser() -> argparse.ArgumentParser:
    """Build root CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="media_toolbox",
        description="Modern media inspection, transcoding, and audio extraction CLI toolbox.",
    )
    parser.add_argument("-v", "--version", action="version", version=f"media_toolbox {__version__}")

    subparsers = parser.add_subparsers(dest="subcommand", metavar="<command>", required=True)

    # Subcommand: inspect
    inspect_parser = subparsers.add_parser("inspect", help="Inspect media technical metadata")
    inspect_parser.add_argument("file", help="Path to media file")
    inspect_parser.add_argument("--json", action="store_true", help="Print structured metadata in JSON format")
    inspect_parser.add_argument("--ffprobe-bin", default="ffprobe", help="Custom ffprobe binary path")

    # Subcommand: transcode
    trans_parser = subparsers.add_parser("transcode", help="Transcode video using presets or custom parameters")
    trans_parser.add_argument("input", help="Source media file")
    trans_parser.add_argument("output", nargs="?", default=None, help="Destination file (or specify via -o/--output)")
    trans_parser.add_argument("-o", "--output", dest="output_opt", default=None, help="Destination file")
    trans_parser.add_argument("--preset", default=None, help="Codec preset (h264, h265, av1, vp9, gif, prores)")
    trans_parser.add_argument("--crf", type=int, default=None, help="Constant Rate Factor quality (0-51)")
    trans_parser.add_argument(
        "--target-size-mb",
        "--target-mb",
        type=float,
        default=None,
        dest="target_size_mb",
        help="Target file size in MB for two-pass encoding",
    )
    trans_parser.add_argument(
        "--strict-size",
        action="store_true",
        help="Re-encode with scaled bitrate if output exceeds target size",
    )
    trans_parser.add_argument("--two-pass", action="store_true", help="Force two-pass bitrate targeting mode")
    trans_parser.add_argument("--speed", type=float, default=None, help="Playback speed multiplier (e.g. 0.5, 1.5, 2.0)")
    trans_parser.add_argument("--scale", default=None, help="Output resolution (e.g. 1920x1080, 1280:-2, -2:720)")
    trans_parser.add_argument("--crop", default=None, help="Crop aspect ratio (e.g. 9:16, 16:9, 1:1)")
    trans_parser.add_argument("--pad", default=None, help="Aspect ratio or canvas padding")
    trans_parser.add_argument("--audio-codec", default=None, help="Target audio codec (e.g. aac, libopus, mp3, flac)")
    trans_parser.add_argument("--audio-bitrate", type=int, default=128, help="Target audio bitrate in kbps (default: 128)")
    trans_parser.add_argument("--mute-audio", action="store_true", help="Remove audio stream from output")
    trans_parser.add_argument("--audio-track", type=int, default=None, help="Audio track index to select (e.g. 0, 1)")
    trans_parser.add_argument("--keep-subs", action="store_true", help="Preserve subtitle streams in output")
    trans_parser.add_argument("--map-metadata", action="store_true", help="Copy global metadata from input to output")
    trans_parser.add_argument("--map-chapters", action="store_true", help="Copy chapters from input to output")
    trans_parser.add_argument("--normalize", action="store_true", help="Normalize audio loudness using EBU R128")
    trans_parser.add_argument("-f", "--overwrite", action="store_true", help="Overwrite destination file if it exists")
    trans_parser.add_argument("--allow-fallback-copy", action="store_true", help="Allow non-atomic copy publication on filesystems lacking hard link support")
    trans_parser.add_argument("--quiet", action="store_true", help="Suppress interactive progress bar")

    # Subcommand: extract-audio
    audio_parser = subparsers.add_parser("extract-audio", help="Extract audio track to standalone file")
    audio_parser.add_argument("input", help="Source media file")
    audio_parser.add_argument("output", nargs="?", default=None, help="Destination audio file (or specify via -o/--output)")
    audio_parser.add_argument("-o", "--output", dest="output_opt", default=None, help="Destination audio file")
    audio_parser.add_argument("-f", "--overwrite", action="store_true", help="Overwrite destination file if it exists")
    audio_parser.add_argument("--allow-fallback-copy", action="store_true", help="Allow non-atomic copy publication on filesystems lacking hard link support")
    audio_parser.add_argument("--codec", default=None, help="Audio codec (e.g. mp3, aac, opus, flac)")
    audio_parser.add_argument("--bitrate", type=int, default=192, help="Audio bitrate in kbps (default: 192)")
    audio_parser.add_argument("--audio-track", type=int, default=None, help="Audio track index to extract (e.g. 0, 1)")
    audio_parser.add_argument("--map-metadata", action="store_true", help="Copy global metadata from input to output")
    audio_parser.add_argument("--speed", type=float, default=None, help="Audio playback speed multiplier")
    audio_parser.add_argument("--normalize", action="store_true", help="Normalize audio loudness using EBU R128")
    audio_parser.add_argument("--quiet", action="store_true", help="Suppress interactive progress bar")

    # Subcommand: install-nautilus
    install_parser = subparsers.add_parser(
        "install-nautilus",
        help="Install Nautilus launcher script, python-nautilus extension, and desktop entry",
    )
    install_parser.add_argument(
        "--dest-dir",
        default=None,
        help="Destination directory root (defaults to XDG data home, e.g. ~/.local/share)",
    )
    install_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate installation without writing any files to disk",
    )
    install_parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress informational console output",
    )

    # Subcommand: uninstall-nautilus
    uninstall_parser = subparsers.add_parser(
        "uninstall-nautilus",
        help="Uninstall Nautilus launcher script, python-nautilus extension, and desktop entry",
    )
    uninstall_parser.add_argument(
        "--dest-dir",
        default=None,
        help="Destination directory root (defaults to XDG data home, e.g. ~/.local/share)",
    )
    uninstall_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate uninstallation without removing any files",
    )
    uninstall_parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress informational console output",
    )

    # Subcommand: status-nautilus
    status_parser = subparsers.add_parser(
        "status-nautilus",
        help="Check installation status of Nautilus integration components",
    )
    status_parser.add_argument(
        "--dest-dir",
        default=None,
        help="Destination directory root (defaults to XDG data home, e.g. ~/.local/share)",
    )
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="Output status as structured JSON",
    )
    status_parser.add_argument(
        "--check",
        action="store_true",
        help="Exit with returncode 1 if any component is not installed (default: exit 0)",
    )

    return parser
