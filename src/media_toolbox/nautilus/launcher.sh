#!/usr/bin/env bash
# ==============================================================================
# Media Toolbox — Nautilus User Scripts Launcher
# Installed to: ~/.local/share/nautilus/scripts/Media-Toolbox
# ==============================================================================
set -euo pipefail

# 1. Parse selected files from Nautilus environment or positional arguments
declare -a FILES=()

if [[ -n "${NAUTILUS_SCRIPT_SELECTED_FILE_PATHS:-}" ]]; then
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ -z "$line" ]] && continue
        FILES+=("$line")
    done <<< "$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS"
elif [[ $# -gt 0 ]]; then
    FILES=("$@")
fi

if [[ ${#FILES[@]} -eq 0 ]]; then
    echo "Error: No files selected or provided to Media Toolbox." >&2
    if command -v notify-send >/dev/null 2>&1; then
        notify-send --urgency=low "Media Toolbox" "No files selected or provided."
    fi
    exit 1
fi

# 2. Locate Python 3 interpreter
PYTHON=""

# (a) Explicit override
if [[ -n "${MEDIA_TOOLBOX_PYTHON:-}" && -x "$MEDIA_TOOLBOX_PYTHON" ]]; then
    PYTHON="$MEDIA_TOOLBOX_PYTHON"
fi

# (b) Baked interpreter from installer
INSTALLED_PYTHON=""
if [[ -z "$PYTHON" && -n "$INSTALLED_PYTHON" && -x "$INSTALLED_PYTHON" ]]; then
    PYTHON="$INSTALLED_PYTHON"
fi

# (c) Resolve relative to script location
if [[ -z "$PYTHON" ]]; then
    SCRIPT_PATH="$(readlink -f -- "$0" 2>/dev/null || realpath -- "$0" 2>/dev/null || echo "$0")"
    SCRIPT_DIR="$(cd -- "$(dirname -- "$SCRIPT_PATH")" >/dev/null 2>&1 && pwd)"
    REPO_ROOT="$(cd -- "$SCRIPT_DIR/../../.." >/dev/null 2>&1 && pwd)"
    if [[ -x "$REPO_ROOT/.venv/bin/python3" ]]; then
        PYTHON="$REPO_ROOT/.venv/bin/python3"
    fi
fi

# (d) Active virtualenv
if [[ -z "$PYTHON" && -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python3" ]]; then
    PYTHON="$VIRTUAL_ENV/bin/python3"
fi

# (e) System fallback (PATH)
if [[ -z "$PYTHON" ]]; then
    if command -v python3 >/dev/null 2>&1; then
        PYTHON="$(command -v python3)"
    elif command -v python >/dev/null 2>&1; then
        PYTHON="$(command -v python)"
    fi
fi

if [[ -z "$PYTHON" ]]; then
    echo "Error: Python 3 interpreter could not be found." >&2
    if command -v notify-send >/dev/null 2>&1; then
        notify-send --urgency=critical "Media Toolbox" "Python 3 interpreter could not be found."
    fi
    exit 1
fi

# 3. Ensure media_toolbox module is in PYTHONPATH if running from source checkout
SCRIPT_PATH="$(readlink -f -- "$0" 2>/dev/null || realpath -- "$0" 2>/dev/null || echo "$0")"
SCRIPT_DIR="$(cd -- "$(dirname -- "$SCRIPT_PATH")" >/dev/null 2>&1 && pwd)"
REPO_SRC="$(cd -- "$SCRIPT_DIR/../../.." >/dev/null 2>&1 && pwd)/src"
if [[ -f "$REPO_SRC/media_toolbox/__init__.py" ]]; then
    export PYTHONPATH="$REPO_SRC${PYTHONPATH:+:$PYTHONPATH}"
fi

# 4. Dispatch execution
if [[ -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ]]; then
    if [[ -z "${MEDIA_TOOLBOX_PYTHON:-}" ]] && command -v media-toolbox-gui >/dev/null 2>&1; then
        nohup media-toolbox-gui "${FILES[@]}" >/dev/null 2>&1 &
        exit 0
    fi
    # Graphical environment: launch GUI detached
    nohup "$PYTHON" -m media_toolbox.ui.app "${FILES[@]}" >/dev/null 2>&1 &
    exit 0
else
    if [[ -z "${MEDIA_TOOLBOX_PYTHON:-}" ]] && command -v media-toolbox >/dev/null 2>&1; then
        exec media-toolbox "${FILES[@]}"
    fi
    # Terminal / headless fallback: run CLI
    exec "$PYTHON" -m media_toolbox.cli "${FILES[@]}"
fi
