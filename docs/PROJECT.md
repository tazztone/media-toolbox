# Project: media_toolbox

## Architecture
Modern Python media toolbox package in `src/media_toolbox` replacing legacy Bash/Zenity scripts.
Architected in three isolated layers:
1. **Core Headless Engine (`core/`)**: Zero GUI dependencies (`gi`, `Gtk`, `Adw`, `Nautilus`). Frozen dataclass models, transactional output staging and collision protection (`jobs.py`), centralized option/preset validation (`validation.py`), mockable `ffprobe -print_format json` probing (`probe.py`), deterministic filtergraph and CLI builder with explicit stream mappings (`builder.py`, `filtergraph.py`), container muxing math engine (`bitrate.py`), and async/threaded subprocess runner with `-progress pipe:1 -nostats` streaming and bounded cancellation reaping (`runner.py`).
2. **Desktop UI Layer (`ui/`)**: Libadwaita / GTK4 desktop interface (`Gtk` 4.0, `Adw` 1) using decoupled pure form state extraction (`forms.py`), dynamic preferences groups with revealers, non-blocking asynchronous probing, monotonic progress tracking, speed/ETA display, and graceful cancellation.
3. **Desktop Integrations (`nautilus/`)**: Dual Nautilus file manager integration consisting of a zero-privilege user script in `~/.local/share/nautilus/scripts/Media-Toolbox` with baked interpreter tracking, and a native `python-nautilus` extension in `~/.local/share/nautilus-python/extensions/` with MIME-type contextual menus.

## Code Layout
```
src/media_toolbox/
├── __init__.py
├── __main__.py               # CLI/UI package execution router
├── cli/                      # Standalone CLI entrypoint package (parser, formatting, handlers)
├── core/
│   ├── __init__.py
│   ├── models.py             # Frozen dataclasses (VideoStream, AudioStream, FormatInfo, MediaInfo, ProgressEvent, exceptions)
│   ├── jobs.py               # Transactional execution, same-filesystem staging (.tmp_media_toolbox_), safe atomic publication
│   ├── validation.py         # Centralized option, preset, rate-mode, and extension validation
│   ├── probe.py              # ffprobe JSON deserializer, N/A duration fallback, fractional fps
│   ├── bitrate.py            # 2-pass bitrate math, speed-aware output duration, container mux margin, budget floor validation
│   ├── filtergraph.py        # Video/audio filter chains, orientation-agnostic crop, aspect pad, atempo splitting (>2.0x, <0.5x)
│   ├── presets.py            # Codec presets (H.264, H.265, AV1, VP9, GIF, ProRes, MP3, AAC, Opus, FLAC) + aliases
│   ├── formatters.py         # Human-readable formatters (duration, size with KiB/MiB vs decimal MB, bitrate, aspect, fps)
│   ├── builder.py            # Deterministic FFmpeg CLI argument builder (CRF & 2-pass) with explicit stream mapping
│   └── runner.py             # Process-isolated runner, bounded watcher thread, -progress pipe:1 parser, SIGTERM/SIGKILL cancellation
├── ui/
│   ├── __init__.py
│   ├── app.py                # Adw.Application, display detection, lifecycle
│   ├── window.py             # Main Libadwaita application window coordinator
│   ├── window_builder.py     # Libadwaita / GTK4 view layout construction
│   ├── window_probing.py     # Async file probing and destination picking mixin
│   ├── window_worker.py      # Background worker thread execution and idle dispatch mixin
│   ├── constants.py          # UI state enums and preset definitions
│   ├── forms.py              # Pure form-state extraction and path resolution decoupled from GTK
│   └── widgets.py            # Custom reactive widgets (monotonic progress bar, speed/ETA labels, revealers)
├── nautilus/
│   ├── __init__.py
│   ├── launcher.sh           # User script for ~/.local/share/nautilus/scripts/Media-Toolbox
│   ├── extension.py          # python-nautilus MenuProvider for ~/.local/share/nautilus-python/extensions/
│   ├── installer.py          # CLI installer/uninstaller for dual Nautilus integration (bakes python interpreter)
│   └── io.github.tazztone.MediaToolbox.desktop # XDG desktop entry
tests/
├── conftest.py               # Synthetic ffprobe JSON fixtures, mock progress streams, sys.path
├── test_adversarial.py       # Fuzzing and adversarial error handling
├── test_bitrate.py           # Bitrate calculations, container overhead margins, speed scaling, floor validation
├── test_builder.py           # Complete FFmpeg command line assembly (CRF and 2-pass) and stream mapping
├── test_cli.py               # CLI invocation and formatted metadata output
├── test_e2e.py               # End-to-end multi-step workflow verification
├── test_filtergraph.py       # Filter chains, atempo splitting, orientation-agnostic crop, aspect pad
├── test_forms.py             # Pure headless form-state and collision-avoidance resolution
├── test_headless_ast.py      # Static AST import verification (asserts ZERO GUI imports in core/)
├── test_integration_media.py # Real FFmpeg/FFprobe execution on synthesized test media
├── test_jobs.py              # Transactional staging, atomic publication, collision rejection, cleanup
├── test_models.py            # Immutability and defaults tests
├── test_nautilus.py          # Extension MIME matching, launcher script generation, installer tests
├── test_presets.py           # Codec preset CLI flag generations
├── test_probe.py             # Valid videos, silent media, audio-only, images, N/A durations, 0/0 fps
├── test_runner.py            # Subprocess runner, progress parsing, ETA, cancellation
├── test_runner_lifecycle.py  # Subprocess shutdown semantics, EOF handling, bounded thread reaping
├── test_shutdown_lifecycle.py # Asynchronous GTK close request, job generation guards, runner cancellation
├── test_ui_app.py            # App lifecycle, display environment, GActions, CLI open dispatch
├── test_ui_forms.py          # Pure form state translation, collision-safe output paths
├── test_ui_widgets.py        # Dynamic revealers, metadata card layouts, stream badge formatting
├── test_ui_window.py         # Window coordinator, state machine, monotonic aggregate progress
├── test_ui_worker.py         # Background worker lifecycle, non-blocking execution, cancellation flow
├── ui_test_helpers.py        # Shared lazy PyGObject loaders, main context drains, mock fixtures
└── test_validation.py        # Centralized encode options and preset validation
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Probing: JSON Deserialization | `ffprobe -print_format json` deserialized into typed dataclasses | M1 | survey (spec_miner) |
| 2 | Probing: Duration Resolution | Fallback from format to stream duration, handling `"N/A"` as `None` | M1 | survey (spec_miner) |
| 3 | Probing: Fractional FPS | Evaluating fractional `r_frame_rate` (e.g. `24000/1001`), handling `"0/0"` safely | M1 | survey (spec_miner) |
| 4 | Probing: Missing Streams | Clean handling of silent videos, audio-only files, and still images | M1 | survey (spec_miner) |
| 5 | Probing: Attached Cover Art | Distinguishing MP3 album art from video tracks (`attached_pic == 1`) | M1 | survey (spec_miner) |
| 6 | Math: 2-Pass Bitrate Calculation | Total bitrate math from target MB and duration | M1 | survey (spec_miner) |
| 7 | Math: Container Overhead Margin | Reserving 3-5% safety margin for muxing overhead | M1 | survey (spec_miner) |
| 8 | Math: 64 kbps Bitrate Clamp | Enforcing minimum 64 kbps video bitrate floor | M1 | survey (spec_miner) |
| 9 | Filtergraph: Video Scaling | Deterministic `scale=w:h` with even dimension snapping (`scale=w:-2`) | M2 | survey (explorer_1) |
| 10 | Filtergraph: Aspect Ratio Padding | Pillarbox/letterbox padding (`pad=w:h:x:y:color`) | M2 | survey (spec_miner) |
| 11 | Filtergraph: Video Speed | Adjusting PTS via `setpts=(1/speed)*PTS` | M2 | survey (spec_miner) |
| 12 | Filtergraph: Audio `atempo` Chaining | Splitting multipliers >2.0x and <0.5x into valid `atempo` filter chains | M2 | survey (spec_miner) |
| 13 | Filtergraph: Video Cropping | Aspect ratio center cropping (9:16, 16:9, 1:1, 4:3, 21:9) | M2 | survey (explorer_1) |
| 14 | Filtergraph: Volume Normalization | Audio loudness normalization (`loudnorm`) and volume boost | M2 | survey (explorer_1) |
| 15 | Filtergraph: Audio Mute / Extract | Muting audio (`-an`) or extracting audio (`-vn`) | M2 | survey (spec_miner) |
| 16 | Presets: 10 Codec Presets | Exact CLI flags for H.264, H.265, AV1, VP9, GIF, ProRes, MP3, AAC, Opus, FLAC | M2 | survey (spec_miner) |
| 17 | Builder: 2-Pass vs CRF Argument Generation | Assembly of Pass 1 null output and Pass 2 final output or single-pass CRF | M2 | survey (spec_miner) |
| 18 | Runner: Key-Value Progress Streaming | Parsing line-by-line `-progress pipe:1 -nostats` key=value pairs | M3 | survey (spec_miner) |
| 19 | Runner: Microsecond Time Conversion | Converting `out_time_us` / `out_time_ms` microseconds to seconds | M3 | survey (explorer_3) |
| 20 | Runner: Percentage & ETA Calculation | Calculating percentage and ETA from elapsed time and total duration | M3 | survey (spec_miner) |
| 21 | Runner: Process Group Cancellation | Clean `SIGTERM` followed by `SIGKILL` on process group to avoid zombies | M3 | survey (spec_miner) |
| 22 | CLI: Formatted Metadata Output | Terminal output of probed media details without GUI dependencies | M4 | survey (explorer_3) |
| 23 | CLI: Headless AST Invariant | Test ensuring zero `gi`/GUI imports across `core/` modules | M4 | survey (explorer_3) |
| 24 | UI: Dynamic Libadwaita Interface | Adw window with dynamic revealers for mode (CRF vs Target Size) and resolution | M5 | survey (explorer_3) |
| 25 | UI: Non-Blocking Transcode Execution | Background worker thread executing runner with `GLib.idle_add` UI updates | M5 | survey (explorer_3) |
| 26 | UI: Live Progress & Speed/ETA | Real-time progress bar, speed factor, and time remaining indicators | M5 | survey (explorer_3) |
| 27 | Nautilus: User Launcher Script | User-space script in `~/.local/share/nautilus/scripts/Media-Toolbox` | M6 | survey (explorer_3) |
| 28 | Nautilus: Python-Nautilus Extension | Native extension in `~/.local/share/nautilus-python/extensions/` with MIME menus | M6 | survey (explorer_3) |
| 29 | Nautilus: Dual Installer CLI | Automated installer command (`--install-nautilus`, `--uninstall-nautilus`) | M6 | survey (explorer_3) |
| 30 | E2E: Full Suite Automated Pass | 100% test pass on `.venv/bin/pytest python/` with mock fixtures | M7 | survey (explorer_3) |
| 31 | E2E: Adversarial Hardening | Tier 5 adversarial tests covering malformed inputs and concurrency | M7 | survey (spec_miner) |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Media Inspection & Math Engine | `core/models.py`, `core/probe.py`, `core/bitrate.py`, tests | none | DONE |
| M2 | Filtergraph, Presets & CLI Builder | `core/filtergraph.py`, `core/presets.py`, `core/builder.py`, tests | M1 | DONE |
| M3 | Non-Blocking Progress Runner | `core/runner.py`, tests | M1 | DONE |
| M4 | CLI Entrypoint & Headless AST Check | `cli/`, `__main__.py`, `tests/test_headless_ast.py`, tests | M1, M2, M3 | DONE |
| M5 | Dynamic Libadwaita / GTK4 UI | `ui/app.py`, `ui/window.py`, `ui/window_builder.py`, `ui/window_probing.py`, `ui/window_worker.py`, `ui/widgets.py`, tests | M1, M2, M3 | DONE |
| M6 | Dual Nautilus Integration & Installer | `nautilus/launcher.sh`, `nautilus/extension.py`, `nautilus/installer.py`, tests | M4, M5 | DONE |
| M7 | E2E Test Suite 100% Pass & Hardening | Full suite pass (`.venv/bin/pytest python/`), Tier 1-5 validation | M1-M6 | DONE |

## Interface Contracts

### `core/models.py`
- `VideoStream`: `index: int`, `codec_name: str`, `width: int`, `height: int`, `fps: Optional[float]`, `bit_rate: Optional[int]`, `duration: Optional[float]`, `rotation: int`, `is_attached_pic: bool`
- `AudioStream`: `index: int`, `codec_name: str`, `channels: int`, `sample_rate: int`, `channel_layout: Optional[str]`, `bit_rate: Optional[int]`, `duration: Optional[float]`
- `FormatInfo`: `filename: str`, `format_name: str`, `duration: Optional[float]`, `size_bytes: Optional[int]`, `bit_rate: Optional[int]`
- `MediaInfo`: `format: FormatInfo`, `video_streams: tuple[VideoStream, ...]`, `audio_streams: tuple[AudioStream, ...]`, properties: `primary_video`, `primary_audio`, `has_video`, `has_audio`, `duration`
- `ProgressEvent`: `frame: int`, `fps: float`, `out_time_seconds: float`, `total_size_bytes: int`, `speed: Optional[float]`, `percentage: float`, `eta_seconds: Optional[float]`, `is_completed: bool`

### `core/probe.py`
- `probe_media(file_path: str | Path, ffprobe_bin: str = "ffprobe") -> MediaInfo`
- `parse_probe_json(data: dict[str, Any]) -> MediaInfo`

### `core/bitrate.py`
- `calculate_target_video_bitrate(target_size_mb: float, duration_seconds: float, audio_bitrate_kbps: int = 128, mux_overhead_margin: float = 0.03, min_video_bitrate_kbps: int = 64) -> int`

### `core/formatters.py`
- `format_duration(seconds: Optional[float]) -> str`
- `format_file_size(size_bytes: Optional[int], binary: bool = True) -> str` (IEC KiB/MiB binary vs SI KB/MB decimal)
- `format_decimal_size(size_bytes: Optional[int]) -> str`
- `format_bitrate(bps: Optional[int]) -> str`
- `format_aspect_ratio(width: int, height: int) -> str`
- `format_fps(fps: Optional[float], is_attached_pic: bool = False) -> str`
- `format_channels(layout: Optional[str], channels: int) -> str`

### `core/filtergraph.py`
- `build_video_filter(scale: Optional[tuple[int, int]], crop: Optional[str], pad: Optional[str], speed: Optional[float], fps: Optional[int]) -> list[str]`
- `build_atempo_chain(speed: float) -> list[str]`
- `build_audio_filter(speed: Optional[float], normalize_loudness: bool, volume_boost_db: Optional[float]) -> list[str]`

### `core/models.py`
- `EncodeOptions`: Data structure supporting stream selection (`audio_track_index`, `keep_subtitles`), hardware acceleration (`hwaccel`), GIF palette options (`gif_max_colors`, `gif_dither`, `gif_stats_mode`), metadata passthrough (`copy_metadata`, `copy_chapters`), size budget enforcement (`strict_size`), speed, and filters.
- `InvalidOptionsError`: Specialized exception subclassing `MediaToolboxError` and `ValueError`.

### `core/presets.py`
- Hardware-accelerated presets (`h264_nvenc`, `hevc_nvenc`, `h264_vaapi`, `hevc_vaapi`, `h264_qsv`, `hevc_qsv`), hardware encoder detection (`get_available_encoders`), and automated hwaccel resolution (`resolve_hardware_preset`).

### `core/builder.py`
- `build_ffmpeg_commands(input_path: str, output_path: str, options: EncodeOptions, ffmpeg_bin: str = "ffmpeg") -> list[list[str]]`
  (Returns 1 command for CRF/single-pass, or 2 commands for 2-pass bitrate mode with unified pass generation, stream mapping, subtitle passthrough, metadata/chapters copying, and configurable binary path).
- `build_gif_command(...)`: Paletted animated GIF pipeline with automated bounds capping (max 800px width, max 15 fps) when input media exceeds thresholds, and customizable `palettegen` / `paletteuse` parameters (`gif_max_colors`, `gif_dither`, `gif_stats_mode`).

### `core/filtergraph.py`
- Video/audio filter chains, orientation-agnostic crop, aspect pad, atempo splitting (>2.0x, <0.5x), and GIF palette generator/user helpers (`build_palettegen_filter`, `build_paletteuse_filter`).

### `core/runner.py`
- `run_ffmpeg(cmd: list[str], total_duration_seconds: Optional[float] = None, ...)`: Subprocess execution with process-group isolation and graceful SIGTERM to SIGKILL escalation.
- `run_ffmpeg_pipeline(cmds: list[list[str]], ...)`: Sequential multi-pass pipeline runner.
- Compatibility: `run_command` and `total_duration` keyword arguments are deprecated in favor of `run_ffmpeg` and `total_duration_seconds`.

### `core/validation.py`
- `validate_encode_options(options: EncodeOptions, output_path: Optional[str] = None) -> None`: Centralized option verification. Enforces mutual exclusivity (CRF vs 2-pass/target-size), positive dimensions and framerates, preset audio bitrate ranges, codec-container compatibility (e.g. strict WebM validation where non-Opus/Vorbis codecs raise `InvalidOptionsError` rather than silent fallback), and filter/copy incompatibility checks.
- `validate_extra_args(extra_args: tuple[str, ...]) -> None`: Rejects naked positional tokens, managed execution flags (`-y`, `-n`, `-nostdin`), input flags (`-i`), unsafe filter/report flags (`-filter_complex`, `-filter_complex_script`, `-lavfi`, `-passlogfile`, `-report`, `-dump_attachment`, `-protocol_whitelist`), and filter source injections (`movie=`, `amovie=`). Allows negative numbers as parameter values (e.g. `-ss -5`).
- `resolve_job_spec(options: EncodeOptions, media_info: Optional[MediaInfo] = None, output_path: Optional[str] = None) -> ResolvedJobSpec`: Resolves canonical presets, encoder names (aliases like `mp3` → `libmp3lame`), container defaults, rate control parameters, and filter chains.

### `core/jobs.py`
- `JobConfig`: Configuration specification supporting `ffmpeg_bin` executable configuration.
- `run_job(config: JobConfig, progress_callback: Optional[Callable[[ProgressEvent], None]] = None, pipeline_progress_callback: Optional[Callable[[int, int, ProgressEvent], None]] = None, cancel_event: Optional[threading.Event] = None) -> JobResult`: Transactional staging in a private temporary directory on the same filesystem (`.tmp_media_toolbox_<uuid>/`), atomic no-clobber publication, preflight hard-link capability checks, symlink overwrite rejection, automated sweep of stale staging directories older than 24 hours, post-encode target size verification (`exceeded_target`), `--strict-size` retry pass, and cleanup on failure or cancellation.
- `cleanup_stale_staging_dirs(target_dir: Path | str, max_age_seconds: float = 86400.0) -> int`: Sweeps orphaned staging directories in the target output directory older than specified max age.

### `cli/handlers.py`
- `_run_cli_job(args: argparse.Namespace, options: EncodeOptions, label: str, error_prefix: str = "FFmpeg") -> int`: Unified CLI job runner encapsulating signal trapping, probing, execution, and error handling.

### `ui/window_worker.py`
- `WindowWorkerMixin`: Asynchronous worker execution with GLib idle loop dispatch, generation guards (`_job_generation`) dropping stale completion/progress events from superseded jobs, consolidated teardown handler (`_finish`) with sequential multi-file batch queue execution, modern `Adw.AlertDialog` overwrite prompt with `Adw.MessageDialog` fallback, and cancel-then-close lifecycle ensuring application quit during active transcodes defers window destruction until staging cleanup completes without orphaned FFmpeg processes. Deprecates `_launch_worker_pipeline` in favor of `_start_worker`.

### `nautilus/launcher.sh`
- Background execution script logging GUI diagnostic output to `${XDG_STATE_HOME:-$HOME/.local/state}/media-toolbox/launch.log`.

