# Media Toolbox

> [!NOTE]
> Standalone repository for Media Toolbox. Supersedes the legacy Bash/Zenity tools in [`tazztone/scripts`](https://github.com/tazztone/scripts).

Modern Python media inspection, transcoding, and audio extraction package replacing legacy Bash/Zenity scripts. Built with a decoupled headless core, a dynamic Libadwaita / GTK4 desktop interface, and dual GNOME Nautilus integrations.

## Features

- **Decoupled Headless Core (`core/`)**:
  - Strongly typed `ffprobe` JSON parsing (`probe.py`) into frozen dataclasses (`models.py`).
  - Transactional output execution and staging (`jobs.py`) with overwrite protection and collision detection.
  - Centralized options and preset validation (`validation.py`) rejecting invalid configurations before FFmpeg starts.
  - Decimal MB bitrate calculator (`bitrate.py`) accounting for playback speed and audio budget floors.
  - Deterministic FFmpeg CLI builder (`builder.py`) supporting 10 codec presets (H.264, H.265, AV1, VP9, GIF, ProRes, MP3, AAC, Opus, FLAC) with explicit stream mapping.
  - Video & audio filter chaining (`filtergraph.py`) with orientation-agnostic centering crop and automatic `atempo` splitting.
  - Real-time `-progress pipe:1` subprocess runner (`runner.py`) with process group isolation, graceful SIGTERM->SIGKILL escalation, and cancellation cleanup.
  - Zero GUI dependencies in `core/` for reliable headless CI/server execution.

- **Dynamic Libadwaita Desktop GUI (`ui/`)**:
  - Pure form-state extraction decoupled from toolkit widgets (`ui/forms.py`).
  - Asynchronous media probing with request sequence tracking to prevent UI freezes and race conditions.
  - Monotonic progress bar with smooth, non-regressing updates across encoding passes.
  - Dynamic forms with revealers (conditionally showing CRF quality slider vs 2-pass target size, custom resolutions).
  - Graceful cancellation and process reaping on window close/quit.

- **Dual Nautilus Integration (`nautilus/`)**:
  - Zero-privilege user script: `~/.local/share/nautilus/scripts/Media-Toolbox` with baked interpreter tracking.
  - Native python-nautilus extension: `~/.local/share/nautilus-python/extensions/media_toolbox_nautilus.py` with MIME-type filtering.
  - XDG desktop entry pointing to `media-toolbox-gui %F`.
  - One-click installer and status checker CLI.

## System Requirements

- **External Binaries**: `ffmpeg` and `ffprobe` on `$PATH` (e.g. `sudo apt install ffmpeg`).
- **Desktop GUI Requirements (optional)**:
  - System GTK 4.10+ and Libadwaita (`gir1.2-gtk-4.0`, `gir1.2-adw-1`).
  - Python desktop dependencies (`pip install ".[desktop]"`).
- **Nautilus Context Menu (optional)**: `python3-nautilus` package.
- **Filesystem Safety Guarantees**:
  - Atomic publication uses same-filesystem hard links (`os.link`) by default to prevent clobbering existing files.
  - On filesystems lacking hardlink support (e.g. FAT, exFAT), pass `--allow-fallback-copy`.
  - Output paths pointing to symbolic links are rejected by default to prevent accidental modification of unintended target files.

## Quick Start

### Installation

```bash
# Headless CLI only (no GTK/PyGObject required)
pip install .

# Full installation with Libadwaita/GTK4 desktop GUI
pip install ".[desktop]"

# Development installation with test suite
pip install ".[all]"
```

### CLI

```bash
# Inspect media metadata (supports single or multiple files)
media-toolbox inspect video.mp4
media-toolbox inspect clip1.mp4 clip2.mp4 --json

# Transcode using preset
media-toolbox transcode video.mp4 output.mp4 --preset h264

# Hardware accelerated encoding (auto, vaapi, nvenc, qsv, videotoolbox)
media-toolbox transcode video.mp4 output.mp4 --preset h264 --hwaccel auto

# Animated GIF generation via palettegen/paletteuse
media-toolbox transcode clip.mp4 animation.gif --preset gif

# 2-Pass target size transcode (in decimal MB)
media-toolbox transcode video.mp4 output.mp4 --target-mb 25

# 2-Pass with strict size retry enforcement
media-toolbox transcode video.mp4 output.mp4 --target-mb 25 --strict-size

# Stream selection and metadata passthrough
media-toolbox transcode video.mkv output.mp4 --audio-track 1 --keep-subs --map-metadata --map-chapters

# Overwrite existing destination safely
media-toolbox transcode video.mp4 output.mp4 --overwrite

# Filesystem fallback copy when hardlinks are unsupported (e.g. FAT/exFAT/cross-device)
media-toolbox transcode video.mp4 /media/external/output.mp4 --allow-fallback-copy

# Extract audio
media-toolbox extract-audio video.mp4 audio.mp3
```

### Desktop GUI & Batch Queue

```bash
# Launch GUI directly or with a file
media-toolbox-gui video.mp4

# Multi-file batch queue (runs sequential unattended transcoding with retry on failures)
media-toolbox-gui clip1.mp4 clip2.mp4 clip3.mp4
```

### Nautilus Integration

```bash
# Install Nautilus script, python-nautilus extension, and desktop entry
media-toolbox install-nautilus

# Check installation status
media-toolbox status-nautilus

# Uninstall integration
media-toolbox uninstall-nautilus
```

## Running Tests & Git Hooks

```bash
# Run test suite
.venv/bin/pytest tests/

# Run the full CI suite locally (lint, tests, desktop, integration, packaging)
scripts/ci-local.sh

# Faster subset: lint + headless tests + typecheck
scripts/ci-local.sh --fast

# Configure and run local pre-commit hook (bash -n and pytest)
git config core.hooksPath .githooks
.githooks/pre-commit
```
