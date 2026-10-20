# Repository Guidelines

## Project Overview

`media-toolbox` — Python media inspection, transcoding, and audio extraction (FFmpeg front-end). Three layers: headless core, Libadwaita/GTK4 GUI, dual Nautilus integration. Python >= 3.10, Apache-2.0. Only hard dependency: PyGObject. External binaries `ffmpeg`/`ffprobe` required on PATH (not packaged).

## Architecture & Data Flow

CLI (`cli.py`) → `core/` → subprocess FFmpeg. Strict layering:

```
cli.py / __main__.py ──> core/ ──> ffmpeg/ffprobe subprocess
ui/ (Adw GUI)       ──> core/     (same core API)
nautilus/           ──> launcher.sh / installer.py (installs entry point, env, desktop entry)
```

`core/` pipeline: `probe.probe_media()` (ffprobe JSON → `models.MediaInfo`) → `builder.build_ffmpeg_commands()` (dispatches audio-extract / GIF palettegen / two-pass / CRF modes, resolves presets via `presets.py`) → `runner.run_ffmpeg()` / `run_ffmpeg_pipeline()` (`-progress pipe:1` parsed by `ProgressParser`, SIGTERM→SIGKILL cancellation).

## Key Directories

- `src/media_toolbox/core/` — headless engine: `models.py` (frozen dataclasses, `MediaToolboxError` hierarchy), `probe.py`, `bitrate.py` (two-pass math), `filtergraph.py` (composable filter builders, `build_atempo_chain` splits >2x/<0.5x), `presets.py` (codec registry + aliases), `builder.py`, `runner.py` (subprocess isolation, progress parsing).
- `src/media_toolbox/ui/` — `app.py` (`MediaToolboxApp`), `window.py`, `widgets.py` (state → `build_encode_options_from_state`).
- `src/media_toolbox/nautilus/` — `installer.py` (stdlib-only), `extension.py` (context-menu provider, python-nautilus mock fallbacks).
- `tests/` — flat dir, one file per module.

## Development Commands

```bash
.venv/bin/pytest tests/          # run tests (439 pass as of 2026-10)
.venv/bin/pytest tests/ -q       # addopts already: -ra -q --import-mode=importlib
python3 -m media_toolbox.cli inspect video.mp4
python3 -m media_toolbox.cli transcode input.mp4 output.mp4 --preset h264
python3 -m media_toolbox.cli transcode input.mp4 output.mp4 --target-mb 25   # two-pass
python3 -m media_toolbox.cli extract-audio input.mp4 output.mp3
python3 -m media_toolbox.ui.app  # GUI (needs DISPLAY/WAYLAND_DISPLAY)
```

No lint/format/type-check tooling configured (no ruff/black/mypy). No CI. Package build: `python -m build` (setuptools backend, src layout).

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
- `src/media_toolbox/cli.py` — CLI + `normalize_argv` shortcut handling (~811 lines).
- `.githooks/pre-commit` — bash `-n` syntax check + pytest; activate: `git config core.hooksPath .githooks`.
- `docs/PROJECT.md` — interface contracts, feature inventory. `docs/TEST_INFRA.md` — test philosophy, coverage tiers.
- `src/media_toolbox/nautilus/launcher.sh` — installed to `~/.local/share/nautilus/scripts/Media-Toolbox`; resolves interpreter, sets `PYTHONPATH=src`.

## Runtime/Tooling Preferences

- Python >= 3.10 (venv observed on 3.14). Package manager: pip. No other runtimes.
- `.venv/` at repo root — use `.venv/bin/pytest` / `.venv/bin/python` for all test/dev invocations (pre-commit hook hardcodes this path).
- setuptools src layout: `where = ["src"]`; `pytest.ini` puts `src` on sys.path so imports work uninstalled.

## Testing & QA

- pytest 8, flat `tests/` layout, no unit/integration split; 439 tests, ~2s runtime, no external binaries needed.
- Synthetic in-memory ffprobe JSON fixtures live in `tests/conftest.py`; temp files via `tmp_path`.
- `pytest.raises(match=...)` for error assertions; `pytest.mark.parametrize` heavily used.
- Docs set coverage expectations: opaque-box, category-partition/BVA, Tier 1–5 matrix (see `docs/TEST_INFRA.md`); target = exit 0, 0 regressions.
- Gotchas: README flags are stale (`-o` doesn't exist — transcode/extract-audio take positional input/output; preset `discord-h264` doesn't exist — see `presets.py` for real names); docs reference a `python/` tree that is actually `src/`.
