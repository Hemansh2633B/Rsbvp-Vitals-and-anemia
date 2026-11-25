#!/usr/bin/env bash
# =============================================================================
#  RSBVP one-command setup — Linux, macOS and Windows (Git Bash / MSYS2 / WSL)
# =============================================================================
#
#  What this script does
#  ---------------------
#    1. checks that Python 3.12+ and Node.js 20+ are installed;
#    2. creates a local virtual environment (.venv) and installs the Python
#       dependencies (numpy, scipy, pandas, matplotlib, opencv < 5, pytest,
#       pillow);
#    3. runs the Python test suite (dataset-free, webcam-free);
#    4. installs the frontend dependencies and runs its tests/build/lint;
#    5. unpacks the bundled rPPG-10 dataset (data/rPPG-10.zip -> data/rppg10/)
#       and validates it, unless you pass --no-dataset;
#    6. optionally runs the rPPG-10 research benchmark (--benchmark).
#
#  Nothing here downloads a dataset, needs a webcam, or needs a GPU.
#  Nothing is uploaded anywhere.
#
#  Quick start (complete beginner):
#      bash setup.sh                     # Linux / macOS / WSL / Git Bash
#
#  Common options:
#      bash setup.sh --help              # show every option
#      bash setup.sh --no-dataset        # skip the dataset entirely
#      bash setup.sh --dataset-only      # only unpack + validate the dataset
#      bash setup.sh --benchmark         # also run the research benchmark (~3 min)
#      bash setup.sh --no-frontend       # skip the JavaScript/TypeScript part
#      bash setup.sh --recreate          # delete and rebuild .venv
#
#  Windows users: run this from "Git Bash" (recommended) or WSL.  If you do not
#  have Git Bash, use setup.cmd from Command Prompt or double-click setup.ps1.
#  See README.md -> "Beginner setup (all platforms)" for step-by-step guidance.
# =============================================================================

set -u  # do NOT use -e: we want to keep going and report every step's status.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || { echo "ERROR: cannot enter repository directory"; exit 1; }

# ---------------------------------------------------------------------------
# Output helpers (no colour when not a terminal, e.g. CI logs or redirected)
# ---------------------------------------------------------------------------
if [ -t 1 ] && [ "${NO_COLOR:-}" = "" ]; then
  C_RESET='\033[0m'; C_BOLD='\033[1m'; C_GREEN='\033[32m'; C_YELLOW='\033[33m'
  C_RED='\033[31m'; C_BLUE='\033[36m'
else
  C_RESET=''; C_BOLD=''; C_GREEN=''; C_YELLOW=''; C_RED=''; C_BLUE=''
fi

step()  { printf '\n%s==> %s%s\n'  "$C_BOLD$C_BLUE" "$*" "$C_RESET"; }
ok()    { printf '%s  [ok]%s %s\n'   "$C_GREEN"  "$C_RESET" "$*"; }
warn()  { printf '%s  [warn]%s %s\n' "$C_YELLOW" "$C_RESET" "$*"; }
fail()  { printf '%s  [fail]%s %s\n' "$C_RED"    "$C_RESET" "$*"; }
info()  { printf '        %s\n' "$*"; }

FAILURES=0
record_failure() { FAILURES=$((FAILURES + 1)); fail "$*"; }

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------
case "$(uname -s 2>/dev/null || echo unknown)" in
  Linux*)   PLATFORM="linux" ;;
  Darwin*)  PLATFORM="macos" ;;
  MINGW*|MSYS*|CYGWIN*) PLATFORM="windows-gitbash" ;;
  *)        PLATFORM="other" ;;
esac
if [ -n "${WSL_DISTRO_NAME:-}" ]; then PLATFORM="wsl"; fi

# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------
OPT_DATASET=1
OPT_FRONTEND=1
OPT_TESTS=1
OPT_BENCHMARK=0
OPT_RECREATE=0
OPT_DATASET_ONLY=0
ECG_FS_HZ=1000        # provider-documented BITalino sampling rate for rPPG-10
EXCLUDE_SUBJECTS=4    # Subject_4 is the provider's excluded participant (0-byte videos)

usage() {
  cat <<'USAGE'
RSBVP setup — works on Linux, macOS and Windows (Git Bash / WSL).

Usage: bash setup.sh [options]

Options:
  --no-dataset        Skip unpacking/validating the bundled rPPG-10 dataset
  --dataset-only      Only unpack and validate the dataset (no venv, no npm)
  --no-frontend       Skip the frontend (npm) steps
  --no-tests          Install dependencies but do not run any tests
  --benchmark         Also run the rPPG-10 research benchmark (~3 minutes)
  --recreate          Delete the existing .venv and rebuild it from scratch
  --dest DIR          Where to unpack the dataset (default: data/rppg10)
  --ecg-fs-hz HZ      ECG sampling rate for validation (default: 1000)
  -h, --help          Show this help

This script never downloads a dataset and never needs a webcam or GPU.
USAGE
}

DEST_DIR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --no-dataset)   OPT_DATASET=0 ;;
    --dataset-only) OPT_DATASET_ONLY=1 ;;
    --no-frontend)  OPT_FRONTEND=0 ;;
    --no-tests)     OPT_TESTS=0 ;;
    --benchmark)    OPT_BENCHMARK=1 ;;
    --recreate)     OPT_RECREATE=1 ;;
    --dest)         shift; DEST_DIR="${1:-}" ;;
    --ecg-fs-hz)    shift; ECG_FS_HZ="${1:-1000}" ;;
    -h|--help)      usage; exit 0 ;;
    *) echo "Unknown option: $1"; echo; usage; exit 2 ;;
  esac
  shift
done
[ -n "$DEST_DIR" ] || DEST_DIR="data/rppg10"

printf '%sRSBVP setup%s  (%s)\n' "$C_BOLD" "$C_RESET" "$PLATFORM"
info "repository: $SCRIPT_DIR"

# ---------------------------------------------------------------------------
# Tool discovery.  On Windows, "python" is often the Microsoft Store stub, so we
# prefer the py launcher, and we look for python3 before python elsewhere.
# ---------------------------------------------------------------------------
find_python() {
  for candidate in python3.13 python3.12 python3 python py; do
    if command -v "$candidate" >/dev/null 2>&1; then
      # `py -3` style launchers need an extra argument.
      if [ "$candidate" = "py" ]; then
        if py -3 -c 'import sys; print(sys.version_info[:2])' >/dev/null 2>&1; then
          echo "py -3"; return 0
        fi
      elif "$candidate" -c 'import sys; print(sys.version_info[:2])' >/dev/null 2>&1; then
        echo "$candidate"; return 0
      fi
    fi
  done
  return 1
}

PYTHON_BIN="$(find_python || true)"

check_python() {
  step "Checking Python"
  if [ -x .venv/bin/python ] || [ -x .venv/Scripts/python.exe ]; then
    VENV_VERSION="$( [ -x .venv/bin/python ] && .venv/bin/python -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || .venv/Scripts/python.exe -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null )"
    ok "existing .venv already provides Python ${VENV_VERSION:-unknown} (system Python not required)"
    VENV_PY="$( [ -x .venv/bin/python ] && echo .venv/bin/python || echo .venv/Scripts/python.exe )"
    return 0
  fi
  if [ -z "$PYTHON_BIN" ]; then
    record_failure "Python was not found."
    info "Install Python 3.12 or newer from https://www.python.org/downloads/"
    info "  Windows: tick 'Add python.exe to PATH' during installation."
    info "  macOS:   brew install python@3.12   (or use the installer from python.org)"
    info "  Linux:   sudo apt install python3.12 python3.12-venv"
    return 1
  fi
  # shellcheck disable=SC2086
  PY_VERSION="$($PYTHON_BIN -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null)"
  # shellcheck disable=SC2086
  PY_OK="$($PYTHON_BIN -c 'import sys; print(int(sys.version_info[:2] >= (3, 12)))' 2>/dev/null)"
  if [ "$PY_OK" = "1" ]; then
    ok "Python $PY_VERSION ($PYTHON_BIN)"
    return 0
  fi
  record_failure "Python $PY_VERSION is too old (3.12+ required)."
  info "Install Python 3.12+ and re-run this script."
  return 1
}

check_node() {
  step "Checking Node.js (frontend)"
  if ! command -v node >/dev/null 2>&1; then
    record_failure "Node.js was not found (needed only for the web interface)."
    info "Install the LTS version from https://nodejs.org/ and re-run."
    info "You can skip the frontend entirely with: bash setup.sh --no-frontend"
    return 1
  fi
  NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
  if [ "$NODE_MAJOR" -ge 20 ] 2>/dev/null; then
    ok "Node.js $(node -v)"
    return 0
  fi
  record_failure "Node.js $(node -v 2>/dev/null) is too old (20+ recommended)."
  info "Install the LTS version from https://nodejs.org/"
  return 1
}

# ---------------------------------------------------------------------------
# Python environment
# ---------------------------------------------------------------------------
setup_python_env() {
  step "Creating the Python virtual environment (.venv)"
  if [ "$OPT_RECREATE" = "1" ] && [ -d .venv ]; then
    info "removing existing .venv (--recreate)"
    rm -rf .venv
  fi
  if [ -d .venv ]; then
    ok ".venv already exists (kept; use --recreate to rebuild)"
  else
    # shellcheck disable=SC2086
    if $PYTHON_BIN -m venv .venv; then
      ok "created .venv"
    else
      record_failure "could not create .venv"
      info "On Debian/Ubuntu you may need: sudo apt install python3-venv"
      return 1
    fi
  fi

  if [ -x .venv/bin/python ]; then
    VENV_PY=".venv/bin/python"     # Linux / macOS / WSL / Git Bash
  elif [ -x .venv/Scripts/python.exe ]; then
    VENV_PY=".venv/Scripts/python.exe"  # Windows venv layout
  else
    record_failure "virtual environment interpreter not found in .venv"
    return 1
  fi
  info "interpreter: $VENV_PY"

  step "Installing Python dependencies (this can take a few minutes)"
  # opencv is pinned below 5: opencv 5 headless builds removed
  # cv2.CascadeClassifier, which the legacy live pipeline uses.
  if "$VENV_PY" -m pip install --upgrade pip >/dev/null 2>&1; then
    ok "pip up to date"
  else
    warn "could not upgrade pip (continuing)"
  fi
  if "$VENV_PY" -m pip install -r requirements-dev.txt; then
    ok "dependencies installed"
  else
    record_failure "dependency installation failed"
    info "Check your internet connection, then re-run: bash setup.sh"
    return 1
  fi
  return 0
}

run_python_tests() {
  step "Running the Python test suite (dataset-free)"
  if "$VENV_PY" -m pytest -q; then
    ok "Python tests passed"
    return 0
  fi
  record_failure "Python tests failed"
  return 1
}

# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------
setup_frontend() {
  step "Installing and testing the web interface (gui/frontend)"
  if [ ! -d gui/frontend ]; then
    warn "gui/frontend not found; skipping"
    return 0
  fi
  (
    cd gui/frontend || exit 1
    if ! npm ci; then
      echo "npm ci failed"
      exit 1
    fi
    if [ "$OPT_TESTS" = "1" ]; then
      npm test || exit 1
      npm run build || exit 1
      npm run lint || exit 1
    fi
    exit 0
  )
  if [ $? -eq 0 ]; then
    ok "frontend ready"
  else
    record_failure "frontend setup or tests failed"
  fi
}

# ---------------------------------------------------------------------------
# Dataset (rPPG-10) — see the "dataset exception" note in README.md
# ---------------------------------------------------------------------------
setup_dataset() {
  step "Unpacking the bundled rPPG-10 dataset"
  ZIP="data/rPPG-10.zip"
  if [ ! -f "$ZIP" ]; then
    warn "$ZIP not present — skipping the dataset."
    info "The dataset is optional. Everything else works without it."
    info "To get it, see docs/RPPG10_VALIDATION.md (CC BY-NC-SA 4.0, non-commercial)."
    return 0
  fi
  if ! command -v unzip >/dev/null 2>&1; then
    # Fall back to Python's zipfile so no extra tool is required.
    info "unzip not found; using Python's zipfile module"
    ZIP_TOOL="$VENV_PY"
  else
    ZIP_TOOL=""
  fi

  mkdir -p "$DEST_DIR" || { record_failure "cannot create $DEST_DIR"; return 1; }

  # The provider ships a zip inside a zip. Unpack in two passes if needed.
  info "unpacking $ZIP -> $DEST_DIR (first pass)"
  if [ -z "$ZIP_TOOL" ]; then
    unzip -o -q "$ZIP" -d "$DEST_DIR" || { record_failure "could not unpack $ZIP"; return 1; }
  else
    "$ZIP_TOOL" -c "import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" \
      "$ZIP" "$DEST_DIR" || { record_failure "could not unpack $ZIP"; return 1; }
  fi

  INNER="$(find "$DEST_DIR" -name 'Dataset_rPPG-10.zip' -print -quit 2>/dev/null)"
  if [ -n "$INNER" ]; then
    info "found nested archive: ${INNER#$DEST_DIR/} (second pass)"
    if [ -z "$ZIP_TOOL" ]; then
      unzip -o -q "$INNER" -d "$DEST_DIR" || { record_failure "could not unpack $INNER"; return 1; }
    else
      "$ZIP_TOOL" -c "import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" \
        "$INNER" "$DEST_DIR" || { record_failure "could not unpack $INNER"; return 1; }
    fi
  fi

  DATASET_ROOT="$(find "$DEST_DIR" -maxdepth 2 -type d -name 'Subject_1' -print -quit 2>/dev/null)"
  if [ -z "$DATASET_ROOT" ]; then
    record_failure "could not locate Subject_1 inside $DEST_DIR"
    info "Expected layout: $DEST_DIR/.../Dataset_rPPG-10/Subject_1/..."
    return 1
  fi
  DATASET_ROOT="$(dirname "$DATASET_ROOT")"
  ok "dataset unpacked at $DATASET_ROOT"

  step "Validating the dataset (no signal values are read)"
  if [ -z "${VENV_PY:-}" ] || [ ! -x "${VENV_PY:-}" ]; then
    warn "no virtual environment yet; skipping validation"
    return 0
  fi
  "$VENV_PY" research/rppg10/run_benchmark.py inspect \
      --data-root "$DATASET_ROOT" \
      --output-dir reports/rppg10 \
      --ecg-fs-hz "$ECG_FS_HZ" \
      --exclude-subjects "$EXCLUDE_SUBJECTS"
  case $? in
    0) ok "dataset validated with no problems" ;;
    2) warn "validation reported items to review (this is normal: the provider spreadsheet is a known deviation)"
       info "read reports/rppg10/rppg10_inventory.json for the exact list" ;;
    *) record_failure "dataset validation crashed" ;;
  esac
  DATASET_ROOT="$DATASET_ROOT"
  return 0
}

run_benchmark() {
  step "Running the rPPG-10 research benchmark (~3 minutes)"
  if [ -z "${DATASET_ROOT:-}" ] || [ -z "${VENV_PY:-}" ]; then
    record_failure "--benchmark needs the dataset and the Python environment"
    return 1
  fi
  if "$VENV_PY" research/rppg10/run_benchmark.py benchmark \
      --data-root "$DATASET_ROOT" \
      --output-dir reports/rppg10 \
      --ecg-fs-hz "$ECG_FS_HZ" \
      --exclude-subjects "$EXCLUDE_SUBJECTS" \
      --allow-deviation \
      --i-have-verified-the-licence; then
    ok "benchmark finished -> reports/rppg10/rppg10_benchmark.md"
  else
    record_failure "benchmark failed"
  fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if [ "$OPT_DATASET_ONLY" = "1" ]; then
  PLATFORM_SUMMARY_PY_OK=0
  if check_python; then PLATFORM_SUMMARY_PY_OK=1; fi
  # Prefer an existing venv; fall back to whatever interpreter was found.
  if [ -x .venv/bin/python ]; then VENV_PY=".venv/bin/python"
  elif [ -x .venv/Scripts/python.exe ]; then VENV_PY=".venv/Scripts/python.exe"
  elif [ -n "$PYTHON_BIN" ]; then VENV_PY="$PYTHON_BIN"; fi

  # --dataset-only must not fail just because the system Python is older than
  # 3.12: unpacking and validating needs only numpy, and a venv (if present)
  # carries its own interpreter.
  if [ "$PLATFORM_SUMMARY_PY_OK" != "1" ] && { [ -x .venv/bin/python ] || [ -x .venv/Scripts/python.exe ]; }; then
    info "system Python is older than 3.12; using the .venv interpreter instead"
    FAILURES=0   # the recorded Python failure is resolved by the venv
  fi
  setup_dataset
else
  if check_python; then
    if setup_python_env; then
      [ "$OPT_TESTS" = "1" ] && run_python_tests
    fi
  fi
  if [ "$OPT_FRONTEND" = "1" ]; then
    if check_node; then setup_frontend; fi
  else
    info "frontend skipped (--no-frontend)"
  fi
  [ "$OPT_DATASET" = "1" ] && setup_dataset
  [ "$OPT_BENCHMARK" = "1" ] && run_benchmark
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
step "Summary"
if [ "$FAILURES" -eq 0 ]; then
  printf '%sAll steps completed.%s\n' "$C_GREEN$C_BOLD" "$C_RESET"
else
  printf '%s%d step(s) need attention (see [fail] lines above).%s\n' "$C_RED$C_BOLD" "$FAILURES" "$C_RESET"
fi
cat <<'NEXT'

What to do next
  1. Start the backend:
       Linux/macOS/WSL/Git Bash :  .venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000   (run from gui/)
       Windows cmd/PowerShell   :  .venv\Scripts\python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
  2. Start the web interface in a second terminal:
       cd gui/frontend && npm run dev -- --host 0.0.0.0
  3. Open http://localhost:5173 in a browser (camera permission is required for live analysis).

Reports:  reports/rppg10/rppg10_benchmark.md   (research results)
Docs:     README.md | docs/RPPG10_VALIDATION.md | docs/IMPLEMENTATION_STATUS.md

Reminder: this is research software. It is not a medical device and makes no
diagnostic claim. The bundled rPPG-10 dataset is CC BY-NC-SA 4.0: research and
non-commercial use only, and it is the one deliberate exception to this
repository's "no datasets in Git" rule.
NEXT

exit "$FAILURES"
