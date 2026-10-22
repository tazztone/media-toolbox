"""
Installer and lifecycle manager for media_toolbox desktop & Nautilus integrations.

Manages automated deployment and removal of:
1. Nautilus user launcher script:
   ~/.local/share/nautilus/scripts/Media-Toolbox (mode 0o755)
2. Python-Nautilus context menu extension:
   ~/.local/share/nautilus-python/extensions/media_toolbox_nautilus.py (mode 0o644)
3. XDG desktop application entry:
   ~/.local/share/applications/io.github.tazztone.MediaToolbox.desktop (mode 0o644)

INVARIANT: Strict zero GUI imports (gi, Gtk, Adw, Nautilus).
Uses standard library exclusively (os, pathlib, shutil, subprocess, sys).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

__all__ = [
    "check_desktop_environment",
    "get_data_home",
    "get_nautilus_paths",
    "install_nautilus",
    "resolve_desktop_inspect_exec",
    "run_update_desktop_database",
    "status_nautilus",
    "uninstall_nautilus",
]


def get_data_home(dest_dir: str | Path | None = None) -> Path:
    """
    Resolve base XDG data directory.

    Priority:
    1. Explicit dest_dir argument (enables pytest tmp_path isolation)
    2. $XDG_DATA_HOME environment variable
    3. Fallback: ~/.local/share
    """
    if dest_dir is not None:
        return Path(dest_dir).expanduser().resolve()
    xdg_env = os.environ.get("XDG_DATA_HOME")
    if xdg_env and xdg_env.strip():
        return Path(xdg_env).expanduser().resolve()
    return (Path.home() / ".local" / "share").resolve()


def get_nautilus_paths(dest_dir: str | Path | None = None) -> dict[str, Path]:
    """Return dictionary of target component paths under resolved data home."""
    data_home = get_data_home(dest_dir)
    return {
        "launcher": data_home / "nautilus" / "scripts" / "Media-Toolbox",
        "extension": data_home
        / "nautilus-python"
        / "extensions"
        / "media_toolbox_nautilus.py",
        "desktop": data_home
        / "applications"
        / "io.github.tazztone.MediaToolbox.desktop",
    }


def run_update_desktop_database(applications_dir: Path) -> bool:
    """
    Execute update-desktop-database if the binary is present on the host.
    Returns True if update executed successfully, False otherwise.
    Never raises exceptions.
    """
    bin_path = shutil.which("update-desktop-database")
    if not bin_path or not applications_dir.is_dir():
        return False
    try:
        proc = subprocess.run(
            [bin_path, str(applications_dir)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def check_desktop_environment(python_bin: str = sys.executable) -> tuple[bool, str]:
    """
    Check if Python environment supports GTK 4.10+ and Libadwaita 1.0+.
    Uses standard library subprocess to avoid GUI imports in installer.
    """
    check_code = (
        "import sys\n"
        "try:\n"
        "    import gi\n"
        "    gi.require_version('Gtk', '4.0')\n"
        "    gi.require_version('Adw', '1')\n"
        "    from gi.repository import Gtk, Adw\n"
        "    major, minor = Gtk.get_major_version(), Gtk.get_minor_version()\n"
        "    if (major, minor) < (4, 10):\n"
        "        sys.exit(2)\n"
        "    for cls in ('SpinRow', 'SwitchRow'):\n"
        "        if not hasattr(Adw, cls):\n"
        "            sys.exit(3)\n"
        "    if not hasattr(Adw, 'AboutDialog') and not hasattr(Adw, 'AboutWindow'):\n"
        "        sys.exit(3)\n"
        "except Exception as err:\n"
        "    sys.stderr.write(str(err))\n"
        "    sys.exit(1)\n"
    )
    try:
        proc = subprocess.run(
            [python_bin, "-c", check_code],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0:
            return True, "GTK >= 4.10 and Libadwaita are available"
        if proc.returncode == 2:
            return False, "GTK version is older than required 4.10"
        if proc.returncode == 3:
            return (
                False,
                "Libadwaita is missing required widgets (AboutDialog/SpinRow/SwitchRow)",
            )
        err = proc.stderr.strip() or "PyGObject / GTK4 / Libadwaita not found"
        return False, err
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def resolve_desktop_inspect_exec() -> str:
    """
    Resolve the most appropriate terminal emulator command for the desktop inspect action.
    Maintains 'x-terminal-emulator -e media-toolbox inspect %f' when x-terminal-emulator
    is present, otherwise falls back to available desktop terminal emulators.
    """
    if shutil.which("x-terminal-emulator"):
        return "x-terminal-emulator -e media-toolbox inspect %f"

    for candidate in ("ptyxis", "gnome-terminal"):
        if shutil.which(candidate):
            return f"{candidate} -- media-toolbox inspect %f"

    for candidate in ("kgx", "alacritty", "kitty", "xterm"):
        if shutil.which(candidate):
            return f"{candidate} -e media-toolbox inspect %f"

    return "x-terminal-emulator -e media-toolbox inspect %f"


def _escape_shell_double_quotes(s: str) -> str:
    r"""Escape special shell characters (\, ", $, `) inside double-quoted string."""
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
    )


def _escape_python_double_quotes(s: str) -> str:
    r"""Escape special python characters (\, ") inside double-quoted string literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _is_toolbox_owned(path: Path) -> bool:
    """Verify that file is owned by media-toolbox before unlinking."""
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        return (
            "media_toolbox" in content
            or "MediaToolbox" in content
            or "Media-Toolbox" in content
        )
    except OSError:
        return False


def _atomic_write_file(target: Path, content: str, mode: int) -> None:
    """Atomically write content to target via sibling temporary file with explicit permissions."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.parent / f".tmp_{uuid.uuid4().hex}_{target.name}"
    try:
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.chmod(mode)
        os.replace(tmp_path, target)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def install_nautilus(
    dest_dir: str | Path | None = None,
    dry_run: bool = False,
) -> list[Path]:
    """
    Install Nautilus launcher script, python-nautilus extension, and desktop entry.

    Args:
        dest_dir: Optional target root path (overriding XDG_DATA_HOME).
        dry_run: If True, simulate actions without modifying filesystem.

    Returns:
        List of Path objects representing installed files.
    """
    # Check desktop environment requirements and warn if unsupported
    gtk_ok, gtk_msg = check_desktop_environment(sys.executable)
    if not gtk_ok:
        sys.stderr.write(f"Warning: {gtk_msg}. Desktop GUI entry may fail to launch.\n")

    if not shutil.which("media-toolbox-gui"):
        sys.stderr.write(
            "Warning: 'media-toolbox-gui' not found on PATH. "
            "Ensure ~/.local/bin or your Python environment's bin directory is in PATH for desktop launchers.\n"
        )

    if not shutil.which("ffmpeg"):
        sys.stderr.write(
            "Warning: 'ffmpeg' not found on PATH. Media transcoding will fail until FFmpeg is installed.\n"
        )
    if not shutil.which("ffprobe"):
        sys.stderr.write(
            "Warning: 'ffprobe' not found on PATH. Media inspection will fail until FFprobe is installed.\n"
        )

    paths = get_nautilus_paths(dest_dir)
    targets = [paths["launcher"], paths["extension"], paths["desktop"]]

    if dry_run:
        return targets

    pkg_nautilus_dir = Path(__file__).resolve().parent

    # 1. Source files resolution
    src_launcher = pkg_nautilus_dir / "launcher.sh"
    src_ext = pkg_nautilus_dir / "extension.py"
    src_desktop = pkg_nautilus_dir / "io.github.tazztone.MediaToolbox.desktop"

    python_bin = sys.executable
    escaped_shell_python = _escape_shell_double_quotes(python_bin)
    escaped_py_python = _escape_python_double_quotes(python_bin)

    # Read launcher content
    if src_launcher.is_file():
        launcher_content = src_launcher.read_text(encoding="utf-8")
        if 'INSTALLED_PYTHON=""' in launcher_content:
            launcher_content = launcher_content.replace(
                'INSTALLED_PYTHON=""',
                f'INSTALLED_PYTHON="{escaped_shell_python}"',
            )
    else:
        launcher_content = (
            "#!/usr/bin/env bash\n"
            "# Media-Toolbox launcher fallback\n"
            f'exec "{escaped_shell_python}" -m media_toolbox.ui.app "$@"\n'
        )

    # Read extension content
    if src_ext.is_file():
        ext_content = src_ext.read_text(encoding="utf-8")
        if (
            'INSTALLED_PYTHON: str = ""' in ext_content
            or 'INSTALLED_PYTHON = ""' in ext_content
        ):
            ext_content = ext_content.replace(
                'INSTALLED_PYTHON: str = ""',
                f'INSTALLED_PYTHON: str = "{escaped_py_python}"',
            ).replace(
                'INSTALLED_PYTHON = ""',
                f'INSTALLED_PYTHON = "{escaped_py_python}"',
            )
    else:
        ext_content = "# python-nautilus extension placeholder\n"

    # Read desktop entry content
    if src_desktop.is_file():
        desktop_content = src_desktop.read_text(encoding="utf-8")
        inspect_exec = resolve_desktop_inspect_exec()
        if "Exec=x-terminal-emulator -e media-toolbox inspect %f" in desktop_content:
            desktop_content = desktop_content.replace(
                "Exec=x-terminal-emulator -e media-toolbox inspect %f",
                f"Exec={inspect_exec}",
            )
    else:
        raise FileNotFoundError(f"Desktop entry template not found at '{src_desktop}'")

    # 2. Write atomically and set permissions
    _atomic_write_file(paths["launcher"], launcher_content, 0o755)
    _atomic_write_file(paths["extension"], ext_content, 0o644)
    _atomic_write_file(paths["desktop"], desktop_content, 0o644)

    # 3. Update desktop database
    run_update_desktop_database(paths["desktop"].parent)

    return targets


def uninstall_nautilus(
    dest_dir: str | Path | None = None,
    dry_run: bool = False,
) -> list[Path]:
    """
    Safely remove installed Nautilus launcher script, extension, and desktop entry.
    Preserves parent directories and verifies application ownership before deletion.

    Args:
        dest_dir: Optional target root path (overriding XDG_DATA_HOME).
        dry_run: If True, simulate removal without modifying filesystem.

    Returns:
        List of Path objects representing removed files.
    """
    paths = get_nautilus_paths(dest_dir)
    existing_targets = [
        p for p in paths.values() if p.is_file() and _is_toolbox_owned(p)
    ]

    if dry_run:
        return existing_targets

    removed: list[Path] = []
    for p in existing_targets:
        try:
            p.unlink()
            removed.append(p)
        except OSError:
            pass

    # Clean up auxiliary bytecode cache if extension was removed
    if paths["extension"] in removed:
        pycache_dir = paths["extension"].parent / "__pycache__"
        if pycache_dir.is_dir():
            for pyc in pycache_dir.glob("media_toolbox_nautilus*.pyc"):
                try:
                    pyc.unlink()
                except OSError:
                    pass
            try:
                # Remove __pycache__ if empty
                pycache_dir.rmdir()
            except OSError:
                pass

    # Update desktop database if desktop file was removed
    if paths["desktop"] in removed:
        run_update_desktop_database(paths["desktop"].parent)

    return removed


def status_nautilus(dest_dir: str | Path | None = None) -> dict[str, bool]:
    """
    Query installation status of each Nautilus integration component.

    Returns:
        dict with boolean status for "launcher", "extension", "desktop", and "installed".
    """
    paths = get_nautilus_paths(dest_dir)

    launcher_ok = paths["launcher"].is_file() and os.access(paths["launcher"], os.X_OK)
    extension_ok = paths["extension"].is_file()
    desktop_ok = paths["desktop"].is_file()
    all_ok = launcher_ok and extension_ok and desktop_ok

    return {
        "launcher": launcher_ok,
        "extension": extension_ok,
        "desktop": desktop_ok,
        "installed": all_ok,
    }
