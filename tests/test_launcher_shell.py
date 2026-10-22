"""Shell integration tests for nautilus/launcher.sh.

Tests headless execution, argument parsing, multi-file inspection dispatch,
and source repository isolation.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.desktop]


def test_launcher_headless_dispatches_inspect_multi_file(tmp_path: Path) -> None:
    """launcher.sh in headless mode dispatches 'inspect' with all selected file arguments."""
    repo_root = Path(__file__).resolve().parent.parent
    launcher_script = repo_root / "src" / "media_toolbox" / "nautilus" / "launcher.sh"
    assert launcher_script.is_file()

    # Create mock media-toolbox executable that logs its arguments
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "cli_args.log"
    mock_cli = bin_dir / "media-toolbox"
    mock_cli.write_text(
        f"""#!/usr/bin/env bash
echo "$@" > "{log_file}"
exit 0
""",
        encoding="utf-8",
    )
    mock_cli.chmod(0o755)

    # Set up headless environment
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    env.pop("MEDIA_TOOLBOX_PYTHON", None)
    env.pop("NAUTILUS_SCRIPT_SELECTED_FILE_PATHS", None)

    test_file1 = str(tmp_path / "clip1.mp4")
    test_file2 = str(tmp_path / "clip2.mkv")

    proc = subprocess.run(
        ["bash", str(launcher_script), test_file1, test_file2],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, f"launcher.sh failed with stderr:\n{proc.stderr}"
    assert log_file.is_file(), "mock media-toolbox was not invoked"
    recorded = log_file.read_text(encoding="utf-8").strip()
    assert recorded.startswith("inspect ")
    assert test_file1 in recorded
    assert test_file2 in recorded
