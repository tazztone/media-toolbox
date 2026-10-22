#!/usr/bin/env bash
# Run the GitHub Actions CI suite locally.
#
# Mirrors .github/workflows/ci.yml job for job:
#   lint        ruff check + ruff format --check (pinned version)
#   headless    AST invariants + unit/CLI suite with the 85% core coverage gate
#   integration real FFmpeg/ffprobe tests
#   desktop     GUI & Nautilus suite (xvfb-run when available)
#   typecheck   basedpyright src tests
#   packaging   sdist/wheel build, isolated install, CLI + installed-package tests
#
# Differences from CI:
#   * One interpreter, not the 3.10/3.12/3.13 matrix. Override with PYTHON=...
#   * CI removes ffmpeg/ffprobe from PATH for the headless job; this script
#     cannot do that safely on a developer machine, so headless runs with
#     ffmpeg available (unit tests mock subprocess anyway).
#   * Jobs whose environment prerequisites are missing (ffmpeg, PyGObject) are
#     skipped with a warning; pass --strict to turn skips into failures.
#
# Usage:
#   scripts/ci-local.sh                    # all jobs
#   scripts/ci-local.sh --fast             # lint + headless + typecheck
#   scripts/ci-local.sh --jobs lint,desktop
#   scripts/ci-local.sh --install-tools    # pip install -e ".[dev]" build first
#   PYTHON=/usr/bin/python3.12 scripts/ci-local.sh
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || {
  cd "$(dirname "$0")/.." && pwd
})"
cd "$REPO_ROOT"

ALL_JOBS=(lint headless integration desktop typecheck packaging)
JOBS=("${ALL_JOBS[@]}")
STRICT=0
INSTALL_TOOLS=0

usage() {
  cat <<'EOF'
Usage: scripts/ci-local.sh [options]

Options:
  --jobs LIST       Comma-separated subset of:
                    lint,headless,integration,desktop,typecheck,packaging
  --fast            Shorthand for --jobs lint,headless,typecheck
  --strict          Fail when a job's prerequisites are missing instead of skipping
  --install-tools   Install dev tooling (pip install -e ".[dev]" build) first
  -h, --help        Show this help

Environment:
  PYTHON            Interpreter to test with (default: .venv/bin/python, else python3)
EOF
}

valid_job() {
  case "$1" in
  lint | headless | integration | desktop | typecheck | packaging) return 0 ;;
  *) return 1 ;;
  esac
}

while (($# > 0)); do
  case "$1" in
  --jobs)
    [[ $# -ge 2 ]] || {
      echo "✘ --jobs requires a value" >&2
      exit 2
    }
    IFS=',' read -r -a JOBS <<<"$2"
    shift 2
    ;;
  --jobs=*)
    IFS=',' read -r -a JOBS <<<"${1#*=}"
    shift
    ;;
  --fast)
    JOBS=(lint headless typecheck)
    shift
    ;;
  --strict)
    STRICT=1
    shift
    ;;
  --install-tools)
    INSTALL_TOOLS=1
    shift
    ;;
  -h | --help)
    usage
    exit 0
    ;;
  *)
    echo "✘ Unknown option: $1" >&2
    usage
    exit 2
    ;;
  esac
done

if ((${#JOBS[@]} == 0)); then
  echo "✘ No jobs selected" >&2
  exit 2
fi
for job in "${JOBS[@]}"; do
  if ! valid_job "$job"; then
    echo "✘ Unknown job: $job" >&2
    usage
    exit 2
  fi
done

# --- Interpreter & tool resolution -----------------------------------------

if [[ -n "${PYTHON:-}" ]]; then
  PY="$PYTHON"
elif [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PY="$REPO_ROOT/.venv/bin/python"
else
  PY="$(command -v python3 || true)"
fi
if [[ -z "$PY" || ! -x "$PY" ]]; then
  echo "✘ No Python interpreter found; set PYTHON=/path/to/python" >&2
  exit 2
fi
case "$PY" in
/*) ;;
*) PY="$REPO_ROOT/$PY" ;;
esac
PY_BIN_DIR="$(dirname "$PY")"

tool_path() {
  local name="$1"
  local candidate="$PY_BIN_DIR/$name"
  if [[ -x "$candidate" ]]; then
    printf '%s\n' "$candidate"
    return 0
  fi
  if command -v "$name" >/dev/null 2>&1; then
    command -v "$name"
    return 0
  fi
  return 1
}

TMP_DIRS=()
cleanup() {
  local dir
  for dir in "${TMP_DIRS[@]:-}"; do
    [[ -n "$dir" ]] && rm -rf "$dir"
  done
}
trap cleanup EXIT

skip_or_fail() {
  if ((STRICT)); then
    echo "✘ $1"
    return 1
  fi
  echo "⚠ $1 — skipping (use --strict to fail instead)"
  return 2
}

ensure_pytest() {
  if ! "$PY" -m pytest --version >/dev/null 2>&1; then
    echo "✘ pytest is not installed for $PY"
    echo "  Run: $0 --install-tools"
    return 1
  fi
}

if ((INSTALL_TOOLS)); then
  echo "▶ Installing dev tooling into $("$PY" -V 2>&1) ($PY_BIN_DIR)"
  "$PY" -m pip install --upgrade pip || exit 1
  "$PY" -m pip install -e ".[dev]" build || exit 1
fi

# --- Jobs -------------------------------------------------------------------

job_lint() {
  local ruff expected actual
  if ! ruff="$(tool_path ruff)"; then
    echo "✘ ruff not found for $PY"
    echo "  Run: $0 --install-tools  (or pip install 'ruff==<pin from pyproject>')"
    return 1
  fi
  expected="$(sed -n 's/.*"ruff==\([0-9][0-9.]*\)".*/\1/p' pyproject.toml | head -n 1)"
  actual="$("$ruff" --version 2>/dev/null | awk '{print $2}')"
  if [[ -n "$expected" && "$actual" != "$expected" ]]; then
    echo "✘ ruff $actual does not match the pin in pyproject.toml ($expected)"
    echo "  Run: $0 --install-tools"
    return 1
  fi
  "$ruff" check . && "$ruff" format --check .
}

job_headless() {
  ensure_pytest || return 1
  if ! "$PY" -c 'import pytest_cov' >/dev/null 2>&1; then
    echo "✘ pytest-cov is not installed for $PY (needed by the coverage gate)"
    echo "  Run: $0 --install-tools"
    return 1
  fi
  "$PY" -m pytest tests/test_headless_ast.py || return 1
  "$PY" -m pytest \
    --cov=media_toolbox.core \
    --cov-report=term-missing \
    --cov-fail-under=85 \
    -m "not desktop and not integration"
}

job_integration() {
  ensure_pytest || return 1
  if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
    skip_or_fail "ffmpeg and ffprobe are required on PATH"
    return $?
  fi
  "$PY" -m pytest -m integration
}

job_desktop() {
  ensure_pytest || return 1
  if ! "$PY" -c 'import gi' >/dev/null 2>&1; then
    skip_or_fail "PyGObject (gi) is not importable with $PY"
    return $?
  fi
  if command -v xvfb-run >/dev/null 2>&1; then
    xvfb-run -a "$PY" -m pytest -m desktop
  else
    echo "⚠ xvfb-run not found; running against the current display (DISPLAY=${DISPLAY:-unset})"
    "$PY" -m pytest -m desktop
  fi
}

job_typecheck() {
  local basedpyright
  if ! basedpyright="$(tool_path basedpyright)"; then
    echo "✘ basedpyright not found for $PY"
    echo "  Run: $0 --install-tools"
    return 1
  fi
  "$basedpyright" src tests
}

job_packaging() {
  if ! "$PY" -c 'import build' >/dev/null 2>&1; then
    echo "✘ Python package 'build' is not installed for $PY"
    echo "  Run: $0 --install-tools"
    return 1
  fi

  local tmp
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/media-toolbox-ci.XXXXXX")"
  TMP_DIRS+=("$tmp")

  if ! "$PY" -m build --outdir "$tmp/dist" . >"$tmp/build.log" 2>&1; then
    echo "✘ Build failed; last 40 log lines:"
    tail -n 40 "$tmp/build.log"
    return 1
  fi
  echo "  built $(basename "$tmp"/dist/*.whl)"

  "$PY" -m venv "$tmp/venv" || return 1
  "$tmp/venv/bin/python" -m pip install --quiet --upgrade pip || return 1
  "$tmp/venv/bin/python" -m pip install --quiet "$tmp"/dist/*.whl pytest || return 1

  "$tmp/venv/bin/media-toolbox" --version || return 1
  "$tmp/venv/bin/media_toolbox" --version || return 1
  "$tmp/venv/bin/media-toolbox" --help >/dev/null || return 1
  "$tmp/venv/bin/media-toolbox" inspect --help >/dev/null || return 1
  "$tmp/venv/bin/media-toolbox" transcode --help >/dev/null || return 1

  (
    export TEST_INSTALLED=1
    "$tmp/venv/bin/python" -m pytest -o pythonpath="" \
      -m "not desktop and not integration" tests/
  ) || return 1
}

# --- Runner -----------------------------------------------------------------

RESULTS=()
FAILED=0
for job in "${JOBS[@]}"; do
  echo
  echo "▶ $job"
  status=0
  "job_$job" || status=$?
  case "$status" in
  0) RESULTS+=("PASS  $job") ;;
  2) RESULTS+=("SKIP  $job") ;;
  *)
    RESULTS+=("FAIL  $job")
    FAILED=1
    ;;
  esac
done

echo
echo "=== CI mirror summary ($("$PY" -V 2>&1)) ==="
printf '%s\n' "${RESULTS[@]}"
if ((FAILED)); then
  echo
  echo "✘ CI mirror failed"
  exit 1
fi
echo
echo "✔ CI mirror passed"
