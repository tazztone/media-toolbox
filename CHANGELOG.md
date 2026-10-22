# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-22

### Added
- `--strict-size` CLI flag and automated retry pass when output exceeds target file size budget.
- `InvalidOptionsError` typed exception hierarchy inheriting from `MediaToolboxError` and `ValueError`.
- Security validation in `validate_extra_args` rejecting unsafe flags (`-filter_complex`, `-lavfi`, `-passlogfile`, `-report`, `-dump_attachment`, `-protocol_whitelist`) and filter injections (`movie=`, `amovie=`).
- Automated startup sweep of stale `.tmp_media_toolbox_*` staging directories older than 24 hours.
- Configurable `ffmpeg_bin` executable path across `JobConfig` and builder functions.
- `py.typed` marker file for PEP 561 typed package distribution.
- Automated release workflow for GitHub Actions via PyPI trusted publishing.

### Changed
- Deduplicated `handle_transcode` and `handle_extract_audio` via unified `_run_cli_job` handler.
- Unified two-pass command generation in `build_two_pass_commands` using shared pass constructor.
- Consolidated window worker completion, cancellation, and error idle teardown into single `_finish` handler.
- Modernized `pyproject.toml` metadata (PEP 639 license, project URLs, classifiers, extra self-references).
- Pinned GitHub Actions workflows to explicit immutable commit SHAs.

### Deprecated
- `run_command` in `runner.py`: use `run_ffmpeg` instead.
- `total_duration` parameter in runner functions: use `total_duration_seconds` instead.
- `_launch_worker_pipeline` on `WindowWorkerMixin`: use `_start_worker` instead.
- Specifying audio codecs via `video_codec` during audio extraction operations.
