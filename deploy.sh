#!/usr/bin/env bash
# =============================================================================
#  RSBVP deploy - Linux, macOS, WSL and Git Bash
# =============================================================================
#  Builds the web interface and starts the service. One command, one URL.
#
#      ./deploy.sh                 deploy on http://localhost:8000 (LAN-reachable)
#      ./deploy.sh --host 127.0.0.1 this machine only (no LAN access)
#      ./deploy.sh --open          open the browser when ready
#      ./deploy.sh --stop          stop the running service
#      ./deploy.sh --foreground    keep it attached to this terminal (default: background)
#      ./deploy.sh --help
#
#  Nothing is downloaded except Python packages from PyPI. No webcam or GPU is
#  required to deploy. This is a local research deployment: no authentication,
#  no TLS - keep it on a trusted network.
#
#  Exit codes: 0 = deployed, 1 = failed, 2 = bad usage.
# =============================================================================

set -u

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || { echo "ERROR: cannot enter $SCRIPT_DIR"; exit 1; }

HOST="0.0.0.0"
PORT="8000"
OPEN_BROWSER=0
FOREGROUND=0
STOP=0
SKIP_INSTALL=0
UNPACK_DATASET=0

say()  { printf '%s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }
ok()   { printf '    [ok] %s\n' "$*"; }
bad()  { printf '    [fail] %s\n' "$*"; }

usage() {
  cat <<'USAGE'
RSBVP deploy - Linux / macOS / WSL / Git Bash

Usage: ./deploy.sh [options]

  --host ADDR       0.0.0.0 (default: this machine and your local network)
                    or 127.0.0.1 (this machine only)
  --port N          preferred port (default 8000; the next free port is used if busy)
  --open            open the browser when the service is ready
  --stop            stop a service started by this script
  --foreground      run attached to this terminal instead of in the background
  --skip-install    do not run pip install / npm install (already installed)
  --unpack-dataset  only unpack the bundled rPPG-10 dataset, then exit
  -h, --help        show this help
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --host)         shift; HOST="${1:-0.0.0.0}" ;;
    --port)         shift; PORT="${1:-8000}" ;;
    --open)         OPEN_BROWSER=1 ;;
    --stop)         STOP=1 ;;
    --foreground)   FOREGROUND=1 ;;
    --skip-install) SKIP_INSTALL=1 ;;
    --unpack-dataset) UNPACK_DATASET=1 ;;
    -h|--help)      usage; exit 0 ;;
    *) say "Unknown option: $1"; usage; exit 2 ;;
  esac
  shift
done

# ---------------------------------------------------------------------------
# Pick the Python interpreter: prefer .venv, then python3.12+, then python3.
# ---------------------------------------------------------------------------
venv_python() {
  if [ -x .venv/bin/python ]; then echo ".venv/bin/python"; return 0; fi
  if [ -x .venv/Scripts/python.exe ]; then echo ".venv/Scripts/python.exe"; return 0; fi
  return 1
}

detect_python() {
  local candidate
  for candidate in python3.13 python3.12 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,12) else 1)' >/dev/null 2>&1; then
      echo "$candidate"; return 0
    fi
  done
  return 1
}

PY="$(venv_python || detect_python || true)"

if [ "$STOP" = "1" ]; then
  [ -n "$PY" ] || { bad "no Python interpreter found"; exit 1; }
  exec "$PY" deploy_server.py --stop
fi

if [ "$UNPACK_DATASET" = "1" ]; then
  [ -n "$PY" ] || { bad "no Python interpreter found"; exit 1; }
  exec "$PY" deploy_server.py --unpack-dataset
fi

say "=============================================================="
say " RSBVP deploy  ($(uname -s 2>/dev/null || echo unknown))"
say "=============================================================="

if [ -z "$PY" ]; then
  bad "Python 3.12+ not found."
  say "     Linux : sudo apt install python3.12 python3.12-venv"
  say "     macOS : brew install python@3.12   (or https://www.python.org/downloads/)"
  say "     Then re-run: ./deploy.sh"
  exit 1
fi
ok "Python: $("$PY" -V 2>&1) ($PY)"

if [ "$SKIP_INSTALL" = "0" ]; then
  step "Installing Python packages"
  if ! "$PY" -m pip install -q -r requirements.txt; then
    bad "pip install failed - check your internet connection"
    exit 1
  fi
  ok "Python packages ready"
fi

step "Building the web interface"
if ! command -v npm >/dev/null 2>&1; then
  bad "npm (Node.js) not found - it is required to build the interface."
  say "     Install Node.js LTS from https://nodejs.org/ and re-run."
  exit 1
fi
(
  cd gui/frontend || exit 1
  if [ "$SKIP_INSTALL" = "0" ]; then
    npm ci --silent || exit 1
  fi
  npm run build || exit 1
) || { bad "the frontend build failed"; exit 1; }
[ -f gui/frontend/dist/index.html ] || { bad "gui/frontend/dist/index.html is missing after the build"; exit 1; }
ok "interface built: gui/frontend/dist"

step "Starting the service"
DEPLOY_ARGS=(--dist gui/frontend/dist --host "$HOST" --port "$PORT")
[ "$OPEN_BROWSER" = "1" ] && DEPLOY_ARGS+=(--open)
[ "$FOREGROUND" = "1" ] && DEPLOY_ARGS+=(--foreground)
exec "$PY" deploy_server.py "${DEPLOY_ARGS[@]}"
