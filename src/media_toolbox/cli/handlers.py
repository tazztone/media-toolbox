"""
CLI subcommand execution handlers.

Coordinates validation, probing, job execution, and user cancellation signals.
Dispatches to media_toolbox.core with zero GUI dependencies.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from typing import Any

import media_toolbox.cli as cli
from media_toolbox.cli.formatting import (
    create_progress_reporter,
    format_media_info_json,
    parse_scale_arg,
    render_media_info_text,
    should_colorize,
)
from media_toolbox.core.jobs import JobConfig
from media_toolbox.core.models import (
    DestinationExistsError,
    EncodeOptions,
    FileCollisionError,
    OutputPublishError,
    ProbeError,
    TargetSizeTooSmallError,
)
from media_toolbox.core.runner import RunnerCancelledError, RunnerError
from media_toolbox.nautilus.installer import (
    get_nautilus_paths,
    install_nautilus,
    status_nautilus,
    uninstall_nautilus,
)


def handle_inspect(args: argparse.Namespace) -> int:
    """Handle 'inspect' subcommand."""
    file_arg = args.file
    try:
        info = cli.probe_media(file_arg, ffprobe_bin=getattr(args, "ffprobe_bin", "ffprobe"))
    except FileNotFoundError as err:
        sys.stderr.write(f"Error: File not found: {err}\n")
        return 1
    except ProbeError as err:
        sys.stderr.write(f"Error probing media: {err}\n")
        return 1
    except Exception as err:
        sys.stderr.write(f"Unexpected error probing media: {err}\n")
        return 1

    if getattr(args, "json", False):
        sys.stdout.write(format_media_info_json(info) + "\n")
    else:
        use_color = should_colorize(sys.stdout)
        sys.stdout.write(render_media_info_text(info, use_color=use_color) + "\n")

    return 0


def handle_transcode(args: argparse.Namespace) -> int:
    """Handle 'transcode' subcommand."""
    if args.output and args.output_opt and args.output != args.output_opt:
        sys.stderr.write(
            f"Error: Conflicting output paths specified: '{args.output}' and '{args.output_opt}'\n"
        )
        return 2

    output_path = args.output or args.output_opt
    if not output_path:
        sys.stderr.write("Error: Output path is required (pass positional argument or via -o/--output)\n")
        return 2

    if args.speed is not None and args.speed <= 0:
        sys.stderr.write(f"Error: Speed multiplier must be positive, got {args.speed}\n")
        return 2

    try:
        scale_tuple = parse_scale_arg(args.scale)
    except ValueError as err:
        sys.stderr.write(f"Error: {err}\n")
        return 2

    # Validate paths early before expensive probing
    try:
        cli.validate_job_paths(args.input, output_path, overwrite=getattr(args, "overwrite", False))
    except DestinationExistsError as err:
        sys.stderr.write(f"Error: {err}\n")
        return 1
    except FileCollisionError as err:
        sys.stderr.write(f"Error: {err}\n")
        return 1
    except FileNotFoundError as err:
        sys.stderr.write(f"Error: Input file not found: {err}\n")
        return 1

    # Probe input to obtain duration and stream layout
    try:
        media_info = cli.probe_media(args.input)
    except FileNotFoundError as err:
        sys.stderr.write(f"Error: Input file not found: {err}\n")
        return 1
    except ProbeError as err:
        sys.stderr.write(f"Error probing media: {err}\n")
        return 1
    except Exception as err:
        sys.stderr.write(f"Error probing media: {err}\n")
        return 1

    options = EncodeOptions(
        preset=args.preset,
        crf=args.crf,
        target_size_mb=args.target_size_mb,
        two_pass=args.two_pass,
        speed=args.speed,
        scale=scale_tuple,
        crop=args.crop,
        pad=args.pad,
        audio_codec=args.audio_codec,
        audio_bitrate_kbps=args.audio_bitrate,
        mute_audio=args.mute_audio,
        normalize_audio=args.normalize,
    )

    config = JobConfig(
        input_path=args.input,
        output_path=output_path,
        options=options,
        media_info=media_info,
        overwrite=getattr(args, "overwrite", False),
    )

    cancel_event = threading.Event()

    def _sigint_handler(_signum: int, _frame: Any) -> None:
        cancel_event.set()
        sys.stderr.write("\nProcess cancellation requested...\n")

    try:
        orig_sigint = signal.signal(signal.SIGINT, _sigint_handler)
    except (ValueError, AttributeError):
        orig_sigint = None

    reporter = create_progress_reporter(quiet=args.quiet)

    try:
        cli.run_job(
            config,
            progress_callback=reporter,
            cancel_event=cancel_event,
            builder=cli.build_ffmpeg_commands,
            runner=cli.run_ffmpeg_pipeline,
        )
        if not args.quiet:
            sys.stdout.write(f"✓ Transcoding complete: {output_path}\n")
        return 0
    except TargetSizeTooSmallError as err:
        sys.stderr.write(f"Error: {err}\n")
        return 2
    except ValueError as err:
        sys.stderr.write(f"Error building FFmpeg command: {err}\n")
        return 2
    except DestinationExistsError as err:
        sys.stderr.write(f"Error: {err}\n")
        return 1
    except FileCollisionError as err:
        sys.stderr.write(f"Error: {err}\n")
        return 1
    except (FileNotFoundError, OSError) as err:
        sys.stderr.write(f"Error: {err}\n")
        return 1
    except RunnerCancelledError:
        sys.stderr.write("Operation cancelled by user.\n")
        return 130
    except RunnerError as err:
        sys.stderr.write(f"Transcoding failed: {err}\n")
        return 1
    except OutputPublishError as err:
        sys.stderr.write(f"Output publication failed: {err}\n")
        return 1
    finally:
        if orig_sigint is not None:
            try:
                signal.signal(signal.SIGINT, orig_sigint)
            except (ValueError, AttributeError):
                pass


def handle_extract_audio(args: argparse.Namespace) -> int:
    """Handle 'extract-audio' subcommand."""
    if args.output and args.output_opt and args.output != args.output_opt:
        sys.stderr.write(
            f"Error: Conflicting output paths specified: '{args.output}' and '{args.output_opt}'\n"
        )
        return 2

    output_path = args.output or args.output_opt
    if not output_path:
        sys.stderr.write("Error: Output path is required (pass positional argument or via -o/--output)\n")
        return 2

    if args.speed is not None and args.speed <= 0:
        sys.stderr.write(f"Error: Speed multiplier must be positive, got {args.speed}\n")
        return 2

    # Validate paths early before expensive probing
    try:
        cli.validate_job_paths(args.input, output_path, overwrite=getattr(args, "overwrite", False))
    except DestinationExistsError as err:
        sys.stderr.write(f"Error: {err}\n")
        return 1
    except FileCollisionError as err:
        sys.stderr.write(f"Error: {err}\n")
        return 1
    except FileNotFoundError as err:
        sys.stderr.write(f"Error: Input file not found: {err}\n")
        return 1

    try:
        media_info = cli.probe_media(args.input)
    except FileNotFoundError as err:
        sys.stderr.write(f"Error: Input file not found: {err}\n")
        return 1
    except ProbeError as err:
        sys.stderr.write(f"Error probing media: {err}\n")
        return 1
    except Exception as err:
        sys.stderr.write(f"Error probing media: {err}\n")
        return 1

    options = EncodeOptions(
        extract_audio=True,
        audio_codec=args.codec,
        audio_bitrate_kbps=args.bitrate,
        speed=args.speed,
        normalize_audio=args.normalize,
    )

    config = JobConfig(
        input_path=args.input,
        output_path=output_path,
        options=options,
        media_info=media_info,
        overwrite=getattr(args, "overwrite", False),
    )

    cancel_event = threading.Event()

    def _sigint_handler(_signum: int, _frame: Any) -> None:
        cancel_event.set()
        sys.stderr.write("\nAudio extraction cancellation requested...\n")

    try:
        orig_sigint = signal.signal(signal.SIGINT, _sigint_handler)
    except (ValueError, AttributeError):
        orig_sigint = None

    reporter = create_progress_reporter(quiet=args.quiet)

    try:
        cli.run_job(
            config,
            progress_callback=reporter,
            cancel_event=cancel_event,
            builder=cli.build_ffmpeg_commands,
            runner=cli.run_ffmpeg_pipeline,
        )
        if not args.quiet:
            sys.stdout.write(f"✓ Audio extraction complete: {output_path}\n")
        return 0
    except TargetSizeTooSmallError as err:
        sys.stderr.write(f"Error: {err}\n")
        return 2
    except ValueError as err:
        sys.stderr.write(f"Error building audio extraction command: {err}\n")
        return 2
    except DestinationExistsError as err:
        sys.stderr.write(f"Error: {err}\n")
        return 1
    except FileCollisionError as err:
        sys.stderr.write(f"Error: {err}\n")
        return 1
    except (FileNotFoundError, OSError) as err:
        sys.stderr.write(f"Error: {err}\n")
        return 1
    except RunnerCancelledError:
        sys.stderr.write("Operation cancelled by user.\n")
        return 130
    except RunnerError as err:
        sys.stderr.write(f"Extraction failed: {err}\n")
        return 1
    except OutputPublishError as err:
        sys.stderr.write(f"Output publication failed: {err}\n")
        return 1
    finally:
        if orig_sigint is not None:
            try:
                signal.signal(signal.SIGINT, orig_sigint)
            except (ValueError, AttributeError):
                pass


def handle_install_nautilus(args: argparse.Namespace) -> int:
    """Handle install-nautilus CLI subcommand."""
    try:
        dest_dir = getattr(args, "dest_dir", None)
        dry_run = getattr(args, "dry_run", False)
        quiet = getattr(args, "quiet", False)

        installed = install_nautilus(dest_dir=dest_dir, dry_run=dry_run)
        if not quiet:
            label = "Would install" if dry_run else "Successfully installed"
            sys.stdout.write(f"{label} {len(installed)} Nautilus component(s):\n")
            for p in installed:
                sys.stdout.write(f"  ✓ {p}\n")
        return 0
    except Exception as err:
        sys.stderr.write(f"Error installing Nautilus integration: {err}\n")
        return 1


def handle_uninstall_nautilus(args: argparse.Namespace) -> int:
    """Handle uninstall-nautilus CLI subcommand."""
    try:
        dest_dir = getattr(args, "dest_dir", None)
        dry_run = getattr(args, "dry_run", False)
        quiet = getattr(args, "quiet", False)

        removed = uninstall_nautilus(dest_dir=dest_dir, dry_run=dry_run)
        if not quiet:
            if not removed:
                label = "Dry-run: no files found to remove." if dry_run else "No installed Nautilus components were found to remove."
                sys.stdout.write(f"{label}\n")
            else:
                label = "Would remove" if dry_run else "Successfully removed"
                sys.stdout.write(f"{label} {len(removed)} Nautilus component(s):\n")
                for p in removed:
                    sys.stdout.write(f"  ✓ {p}\n")
        return 0
    except Exception as err:
        sys.stderr.write(f"Error uninstalling Nautilus integration: {err}\n")
        return 1


def handle_status_nautilus(args: argparse.Namespace) -> int:
    """Handle status-nautilus CLI subcommand."""
    try:
        dest_dir = getattr(args, "dest_dir", None)
        as_json = getattr(args, "json", False)
        check_mode = getattr(args, "check", False)

        status = status_nautilus(dest_dir=dest_dir)
        paths = get_nautilus_paths(dest_dir=dest_dir)

        if as_json:
            sys.stdout.write(json.dumps(status, indent=2) + "\n")
        else:
            sys.stdout.write("Nautilus Integration Status:\n")
            launcher_label = "Installed" if status["launcher"] else "Not installed"
            ext_label = "Installed" if status["extension"] else "Not installed"
            desk_label = "Installed" if status["desktop"] else "Not installed"
            all_label = "Installed" if status["installed"] else "Incomplete / Not installed"

            sys.stdout.write(f"  Launcher Script:   {launcher_label} ({paths['launcher']})\n")
            sys.stdout.write(f"  Python Extension:  {ext_label} ({paths['extension']})\n")
            sys.stdout.write(f"  Desktop Entry:     {desk_label} ({paths['desktop']})\n")
            sys.stdout.write(f"Overall Status:      {all_label}\n")

        if check_mode and not status["installed"]:
            return 1
        return 0
    except Exception as err:
        sys.stderr.write(f"Error querying Nautilus status: {err}\n")
        return 1
