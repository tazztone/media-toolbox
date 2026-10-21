# Repository Guidelines

## Project Overview

`media-toolbox` — Python media inspection, transcoding, and audio extraction (FFmpeg front-end). Three layers: headless core, Libadwaita/GTK4 GUI, dual Nautilus integration. Python >= 3.10, Apache-2.0. Hard dependencies: None (headless CLI uses pure standard library); PyGObject is optional for desktop GUI (`pip install .[desktop]`). External binaries `ffmpeg`/`ffprobe` required on PATH (not packaged).

## Architecture & Data Flow

CLI (`cli/`) → `core/` → subprocess FFmpeg. Strict layering:

```
cli/ / __main__.py ──> core/jobs.py ──> core/ ──> ffmpeg/ffprobe subprocess
ui/ (Adw GUI)       ──> core/jobs.py ──> core/     (same core API)
nautilus/           ──> launcher.sh / installer.py (installs entry point, env, desktop entry)
```

`core/` pipeline: `probe.probe_media()` (ffprobe JSON → `models.MediaInfo`) → `validation.validate_encode_options()` → `builder.build_ffmpeg_commands()` (dispatches audio-extract / GIF palettegen / two-pass / CRF modes, resolves presets via `presets.py`, maps deterministic streams) → `jobs.run_job()` (transactional same-filesystem staging `.tmp_<uuid>/`, atomic publication, overwrite safety) → `runner.run_ffmpeg()` / `run_ffmpeg_pipeline()` (`-progress pipe:1` parsed by `ProgressParser`, bounded watcher thread, graceful SIGTERM→SIGKILL cancellation).

## Key Directories

- `src/media_toolbox/core/` — headless engine: `models.py` (frozen dataclasses, `MediaToolboxError` hierarchy), `jobs.py` (transactional execution and publication), `validation.py` (options/preset verification), `probe.py`, `bitrate.py` (speed-aware decimal MB two-pass math), `filtergraph.py` (orientation-agnostic crop, aspect pad, atempo chaining), `presets.py` (codec registry + aliases), `formatters.py`, `builder.py`, `runner.py` (subprocess isolation, progress parsing).
- `src/media_toolbox/ui/` — `app.py` (`MediaToolboxApp`), `window.py` (async probing), `forms.py` (pure decoupled form logic), `widgets.py` (monotonic progress).
- `src/media_toolbox/nautilus/` — `installer.py` (stdlib-only, bakes interpreter), `extension.py` (context-menu provider, python-nautilus mock fallbacks), `launcher.sh`.
- `tests/` — flat dir, one file per module, plus `test_integration_media.py` for real FFmpeg execution.

## Development Commands

```bash
.venv/bin/pytest tests/          # run tests (524 pass as of 2026-10)
.venv/bin/pytest tests/ -q       # addopts already: -ra -q --import-mode=importlib
media-toolbox inspect video.mp4
media-toolbox transcode input.mp4 output.mp4 --preset h264
media-toolbox transcode input.mp4 output.mp4 --target-mb 25   # two-pass
media-toolbox extract-audio input.mp4 output.mp3
media-toolbox-gui                # GUI (needs DISPLAY/WAYLAND_DISPLAY)
```

CI configured via GitHub Actions (`.github/workflows/ci.yml`): headless tests, desktop tests with Xvfb, wheel build smoke test. Package build: `python -m build` (setuptools backend, src layout).

## Code Conventions & Common Patterns

- **Zero-GUI invariant in `core/`**: no `gi`/GTK imports allowed; enforced by AST tests (`test_headless_ast.py`, `test_filtergraph_zero_gui`, `test_builder_zero_gui`, `test_presets_zero_gui`). Never import GUI modules from `core/`.
- **Frozen dataclasses + exception hierarchy** in `models.py` (`MediaToolboxError` base). Raise typed errors (`ProbeError`, `RunnerError`, `RunnerCancelledError`), don't bare `Exception`.
- **Lazy imports for GUI**: `__main__.py` and `nautilus/__init__.py` use lazy `__getattr__`/conditional imports so headless environments never touch GTK.
- **Mock all subprocess calls in tests** (`unittest.mock.patch`); never require real ffmpeg in unit tests.
- Registry pattern in `presets.py` with alias map `_PRESET_ALIASES` (case-insensitive lookup).
- No docstring/style enforcement; keep modules self-contained, stdlib-first.

## Important Files

- `pyproject.toml` — packaging (setuptools>=61), deps, console scripts (`media-toolbox`, `media_toolbox`, `media-toolbox-gui`, `media_toolbox_gui`).
- `pytest.ini` — all pytest config (testpaths, pythonpath=src, addopts).
- `src/media_toolbox/cli/` — modular CLI (`__init__.py`, `parser.py`, `formatting.py`, `handlers.py`, `__main__.py`).
- `.githooks/pre-commit` — bash `-n` syntax check + pytest; activate: `git config core.hooksPath .githooks`.
- `docs/PROJECT.md` — interface contracts, feature inventory. `docs/TEST_INFRA.md` — test philosophy, coverage tiers.
- `src/media_toolbox/nautilus/launcher.sh` — installed to `~/.local/share/nautilus/scripts/Media-Toolbox`; resolves interpreter, sets `PYTHONPATH=src`.

## Runtime/Tooling Preferences

- Python >= 3.10 (venv observed on 3.14). Package manager: pip. No other runtimes.
- `.venv/` at repo root — use `.venv/bin/pytest` / `.venv/bin/python` for all test/dev invocations (pre-commit hook hardcodes this path).
- setuptools src layout: `where = ["src"]`; `pytest.ini` puts `src` on sys.path so imports work uninstalled.

## Testing & QA

- pytest 8/9, flat `tests/` layout; 524 tests, ~3.5s runtime.
- Mock all subprocess calls in unit tests (`unittest.mock.patch`); real FFmpeg verified in `tests/test_integration_media.py`.
- Synthetic in-memory ffprobe JSON fixtures live in `tests/conftest.py`; temp files via `tmp_path`.
- `pytest.raises(match=...)` for error assertions; `pytest.mark.parametrize` heavily used.
- Zero GUI invariant in `core/` strictly enforced by AST tests (`tests/test_headless_ast.py`).
