"""
Headless transactional job execution and file lifecycle manager.

Provides robust execution semantics:
- Path validation (identical file, symlink, hard link, and collision detection)
- Non-destructive execution via same-filesystem staging files (.tmp_media_toolbox_*)
- Private temporary directory isolation for multi-pass logfiles
- Atomic publication (os.replace) only upon exit code 0 and non-empty output
- Complete cleanup of job-owned staging artifacts without touching pre-existing files

INVARIANT: Strict zero GUI imports (gi, Gtk, Adw, Nautilus, tkinter, PyQt, PySide).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
import errno
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
from typing import Callable, Optional
import uuid

from media_toolbox.core.builder import build_ffmpeg_commands
from media_toolbox.core.models import (
    DestinationExistsError,
    EncodeOptions,
    FileCollisionError,
    MediaInfo,
    OutputPublishError,
    ProbeError,
    ProgressEvent,
)
from media_toolbox.core.probe import probe_media
from media_toolbox.core.runner import (
    RunnerCancelledError,
    run_ffmpeg_pipeline,
)


@dataclass(frozen=True, slots=True)
class JobConfig:
    """Configuration for a standalone media processing job."""

    input_path: Path | str
    output_path: Path | str
    options: EncodeOptions
    media_info: Optional[MediaInfo] = None
    overwrite: bool = False
    sigterm_timeout: float = 2.0
    allow_unprobed: bool = False
    allow_non_atomic_fallback: bool = False


@dataclass(frozen=True, slots=True)
class JobResult:
    """Outcome and metadata of a successfully published job."""

    input_path: Path
    output_path: Path
    file_size_bytes: int
    duration_seconds: Optional[float] = None
    exceeded_target: bool = False
    target_size_bytes: Optional[int] = None


def cleanup_stale_staging_dirs(target_dir: Path | str, max_age_seconds: float = 86400.0) -> int:
    """
    Remove orphaned .tmp_media_toolbox_* staging directories older than max_age_seconds
    within target_dir. Returns number of directories cleaned up.
    """
    cleaned = 0
    p = Path(target_dir)
    if not p.is_dir():
        return 0
    now = time.time()
    try:
        for entry in p.iterdir():
            if entry.is_dir() and entry.name.startswith(".tmp_media_toolbox_"):
                try:
                    stat = entry.stat()
                    if (now - stat.st_mtime) > max_age_seconds:
                        shutil.rmtree(entry, ignore_errors=True)
                        cleaned += 1
                except OSError:
                    pass
    except OSError:
        pass
    return cleaned


def validate_job_paths(
    input_path: Path | str,
    output_path: Path | str,
    overwrite: bool = False,
) -> tuple[Path, Path]:
    """
    Validate input and output paths for existence, collisions, and overwrite policy.

    Args:
        input_path: Source media file path.
        output_path: Target destination path.
        overwrite: If False, raises DestinationExistsError when output exists.

    Returns:
        tuple[Path, Path]: Resolved (input_path, output_path).

    Raises:
        FileNotFoundError: If input does not exist.
        FileCollisionError: If input and output point to the same physical file.
        DestinationExistsError: If output exists and overwrite=False.
    """
    in_raw = Path(input_path)
    out_raw = Path(output_path)

    if not in_raw.exists():
        raise FileNotFoundError(f"Input file not found: {in_raw}")

    in_resolved = in_raw.resolve()
    out_resolved = out_raw.resolve()

    # Exact resolved path equality
    if in_resolved == out_resolved:
        raise FileCollisionError(
            f"Input and output point to the same file: {in_raw} -> {out_raw}"
        )

    # Inode comparison for symlinks and hardlinks
    if out_raw.exists() or out_raw.is_symlink():
        try:
            if out_raw.exists() and os.path.samefile(in_raw, out_raw):
                raise FileCollisionError(
                    f"Input and output share the same underlying inode: {in_raw} and {out_raw}"
                )
        except OSError:
            pass

        if not overwrite:
            raise DestinationExistsError(
                f"Destination file already exists: {out_raw}. Use overwrite to replace."
            )

        if out_raw.is_symlink():
            raise FileCollisionError(
                f"Output path cannot be a symbolic link: {out_raw}. "
                "Overwriting symlinks is disallowed for security; please specify the direct destination file."
            )

    return in_resolved, out_resolved


def check_atomic_publish_supported(directory: Path) -> bool:
    """
    Pre-flight test verifying whether directory's filesystem supports hard links for atomic publication.
    """
    probe_src = directory / f".mtb_probe_{uuid.uuid4().hex[:8]}.tmp"
    probe_dst = directory / f".mtb_probe_{uuid.uuid4().hex[:8]}.tmp"
    try:
        probe_src.touch(exist_ok=False)
        try:
            os.link(probe_src, probe_dst)
            return True
        except OSError:
            return False
        finally:
            try:
                probe_dst.unlink(missing_ok=True)
            except OSError:
                pass
    except OSError:
        # If directory permissions prevent probe touch, defer validation to publish_output
        return True
    finally:
        try:
            probe_src.unlink(missing_ok=True)
        except OSError:
            pass


def _fallback_noclobber_publish(staging_path: Path, out_path: Path) -> None:
    """Non-atomic O_CREAT|O_EXCL streaming fallback for filesystems lacking hard link support."""
    try:
        fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    except FileExistsError as err:
        raise DestinationExistsError(
            f"Destination file already exists: {out_path}. Use overwrite to replace."
        ) from err
    except OSError as err:
        raise OutputPublishError(
            f"Failed to publish output file to {out_path}: {err}"
        ) from err

    try:
        with os.fdopen(fd, "wb") as dst, open(staging_path, "rb") as src:
            shutil.copyfileobj(src, dst)
    except Exception as err:
        try:
            out_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise OutputPublishError(
            f"Failed to stream staging output to {out_path}: {err}"
        ) from err


def publish_output(
    staging_path: Path,
    out_path: Path,
    *,
    overwrite: bool = False,
    allow_non_atomic_fallback: bool = False,
) -> None:
    """
    Publish staging file to destination path atomically and safely.

    If overwrite is True:
        Atomically replaces target using os.replace().
    If overwrite is False:
        Atomically creates target using same-filesystem hard link (os.link),
        failing immediately with DestinationExistsError if destination exists.
        Unlinks staging_path upon successful link.
        If hard links are unsupported (e.g. FAT, EXDEV, permissions):
            - If allow_non_atomic_fallback is False (default): raises OutputPublishError.
            - If allow_non_atomic_fallback is True: falls back to exclusive creation
              (O_CREAT | O_EXCL) with streaming copy (weaker visibility guarantee).
    """
    if overwrite:
        try:
            os.replace(staging_path, out_path)
        except OSError as err:
            raise OutputPublishError(
                f"Failed to atomically publish output to {out_path}: {err}"
            ) from err
        return

    # No-overwrite path: atomic no-clobber
    try:
        os.link(staging_path, out_path)
    except FileExistsError as err:
        raise DestinationExistsError(
            f"Destination file already exists: {out_path}. Use overwrite to replace."
        ) from err
    except OSError as err:
        # Fall back if filesystem does not support hard links (e.g. FAT, EXDEV, permissions)
        if err.errno in (errno.EPERM, errno.ENOSYS, errno.EOPNOTSUPP, errno.EXDEV):
            if not allow_non_atomic_fallback:
                raise OutputPublishError(
                    f"Underlying filesystem for '{out_path}' does not support atomic no-clobber publication "
                    f"(hard links unsupported, errno={err.errno}). Enable allow_non_atomic_fallback to permit non-atomic copy."
                ) from err
            _fallback_noclobber_publish(staging_path, out_path)
        else:
            raise OutputPublishError(
                f"Failed to publish output file to {out_path}: {err}"
            ) from err
    else:
        try:
            staging_path.unlink()
        except OSError:
            pass


def run_job(
    config: JobConfig,
    progress_callback: Optional[Callable[[ProgressEvent], None]] = None,
    pipeline_progress_callback: Optional[Callable[[int, int, ProgressEvent], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    builder: Optional[Callable[..., list[list[str]]]] = None,
    runner: Optional[Callable[..., None]] = None,
) -> JobResult:
    """
    Execute a media transcode or extraction job transactionally.

    Output is rendered to an isolated staging file in a private temporary directory
    on the target filesystem and published atomically only when FFmpeg completes with exit code 0.
    Any failure or cancellation discards the staging directory and preserves any
    pre-existing destination file.

    Args:
        config: JobConfig settings.
        progress_callback: Callback for aggregated progress events.
        pipeline_progress_callback: Callback for pass-specific progress events.
        cancel_event: Event to trigger graceful shutdown.
        builder: Optional custom command builder (defaults to build_ffmpeg_commands).
        runner: Optional custom pipeline runner (defaults to run_ffmpeg_pipeline).

    Returns:
        JobResult: Published output details.

    Raises:
        FileNotFoundError: If input does not exist.
        FileCollisionError: If input and output paths resolve to the same file.
        DestinationExistsError: If destination exists and overwrite=False.
        RunnerCancelledError: If job is cancelled.
        RunnerError: If FFmpeg execution fails.
        OutputPublishError: If output file is not produced or empty.
    """
    builder_fn = builder or build_ffmpeg_commands
    runner_fn = runner or run_ffmpeg_pipeline

    in_path, out_path = validate_job_paths(
        config.input_path,
        config.output_path,
        overwrite=config.overwrite,
    )

    if cancel_event is not None and cancel_event.is_set():
        raise RunnerCancelledError("Job cancelled before start")

    # Resolve media info if absent
    media_info = config.media_info
    if media_info is None:
        try:
            media_info = probe_media(in_path)
        except Exception as err:
            if config.allow_unprobed:
                media_info = None
            else:
                if isinstance(err, ProbeError):
                    raise
                raise ProbeError(f"Failed to probe '{in_path}': {err}") from err

    raw_duration = media_info.duration if media_info else None
    duration = (
        raw_duration / config.options.speed
        if (raw_duration is not None and config.options.speed and config.options.speed > 0)
        else raw_duration
    )

    # Ensure target directory exists
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Pre-flight verify atomic publication capability before beginning potentially expensive encode
    if not config.overwrite and not config.allow_non_atomic_fallback:
        if not check_atomic_publish_supported(out_path.parent):
            raise OutputPublishError(
                f"Underlying filesystem for '{out_path}' does not support atomic no-clobber publication "
                "(hard links unsupported). Pass --allow-fallback-copy to permit non-atomic copy."
            )

    # Sweep stale staging directories older than 24h
    cleanup_stale_staging_dirs(out_path.parent)

    # Staging directory on the same filesystem ensures atomic publication
    staging_temp_dir = tempfile.TemporaryDirectory(
        dir=out_path.parent,
        prefix=".tmp_media_toolbox_",
    )
    staging_path = Path(staging_temp_dir.name) / out_path.name

    # Isolated temporary directory for multi-pass logs
    pass_tmp_dir: Optional[tempfile.TemporaryDirectory[str]] = None
    pass_logfile_prefix: Optional[str] = None

    if config.options.two_pass or config.options.target_size_mb is not None:
        pass_tmp_dir = tempfile.TemporaryDirectory(prefix="media_toolbox_2pass_")
        pass_logfile_prefix = str(Path(pass_tmp_dir.name) / f"pass_{uuid.uuid4().hex[:8]}")

    try:
        cmds = builder_fn(
            str(in_path),
            str(staging_path),
            config.options,
            media_info=media_info,
            pass_logfile=pass_logfile_prefix,
            include_progress=True,
        )

        runner_fn(
            cmds,
            total_duration_seconds=duration,
            progress_callback=progress_callback,
            pipeline_progress_callback=pipeline_progress_callback,
            cancel_event=cancel_event,
            sigterm_timeout=config.sigterm_timeout,
        )

        # Check cancellation immediately prior to publishing
        if cancel_event is not None and cancel_event.is_set():
            raise RunnerCancelledError("Job cancelled before publication")

        # Output validation and atomic publication
        if not staging_path.exists():
            raise OutputPublishError(
                f"Encoded output file was not produced: {staging_path}"
            )

        file_size = staging_path.stat().st_size
        if file_size == 0:
            raise OutputPublishError(
                f"Encoded output file is empty (0 bytes): {staging_path}"
            )

        target_size_bytes: Optional[int] = None
        exceeded_target = False
        if config.options.target_size_mb is not None:
            target_size_bytes = int(config.options.target_size_mb * 1_000_000)
            if file_size > target_size_bytes:
                exceeded_target = True

        if (
            exceeded_target
            and config.options.strict_size
            and config.options.target_size_mb is not None
            and target_size_bytes is not None
        ):
            scale_factor = (target_size_bytes / file_size) * 0.97
            scaled_target_mb = config.options.target_size_mb * scale_factor
            retry_options = dataclasses.replace(
                config.options,
                target_size_mb=scaled_target_mb,
                strict_size=False,
            )
            try:
                staging_path.unlink()
            except OSError:
                pass

            retry_cmds = builder_fn(
                str(in_path),
                str(staging_path),
                retry_options,
                media_info=media_info,
                pass_logfile=pass_logfile_prefix,
                include_progress=True,
            )
            runner_fn(
                retry_cmds,
                total_duration_seconds=duration,
                progress_callback=progress_callback,
                pipeline_progress_callback=pipeline_progress_callback,
                cancel_event=cancel_event,
                sigterm_timeout=config.sigterm_timeout,
            )

            if cancel_event is not None and cancel_event.is_set():
                raise RunnerCancelledError("Job cancelled before publication")

            if not staging_path.exists():
                raise OutputPublishError(
                    f"Encoded output file was not produced on retry: {staging_path}"
                )
            file_size = staging_path.stat().st_size
            if file_size == 0:
                raise OutputPublishError(
                    f"Encoded output file is empty (0 bytes) on retry: {staging_path}"
                )
            exceeded_target = file_size > target_size_bytes

        publish_output(
            staging_path,
            out_path,
            overwrite=config.overwrite,
            allow_non_atomic_fallback=config.allow_non_atomic_fallback,
        )

        return JobResult(
            input_path=in_path,
            output_path=out_path,
            file_size_bytes=file_size,
            duration_seconds=duration,
            exceeded_target=exceeded_target,
            target_size_bytes=target_size_bytes,
        )

    finally:
        # Guaranteed cleanup of job-owned staging and temporary artifacts
        try:
            staging_temp_dir.cleanup()
        except OSError:
            pass

        if pass_tmp_dir is not None:
            try:
                pass_tmp_dir.cleanup()
            except OSError:
                pass
