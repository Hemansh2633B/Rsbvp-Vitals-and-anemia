#!/usr/bin/env python3
"""Prepare the deployment environment - safely, and only when something changed.

Why this exists
---------------
Redeploying must not recreate the virtual environment, redownload every Python
package, or reinstall ``node_modules``. This module owns that decision so
``deploy.sh``, ``deploy.cmd`` and ``deploy.ps1`` all behave identically (they
just call ``python deploy_env.py ...``).

What it guarantees
------------------
* one project-local virtual environment at ``.venv`` that is created only if it
  is missing, and *reused* otherwise - even if it was made by ``uv``, ``venv``
  or the old setup script;
* a broken/incomplete ``.venv`` (for example an interrupted download) is
  repaired instead of being used: it is recreated, never silently half-used;
* Python packages are installed only when ``requirements.txt`` changed (its
  SHA-256 is stored in ``.venv/.rsbvp-requirements.sha256``) or when a package
  the deployment needs cannot be imported - never on every run;
* ``gui/frontend/node_modules`` is reused when ``package-lock.json`` is
  unchanged (``npm ci`` deletes it first, so it only runs when it must), and the
  frontend is rebuilt only when its sources are newer than ``dist/index.html``;
* a dependency cache lives in ``.cache/deploy`` (``pip download --dest`` /
  ``npm cache``) so even a *first* install on a fresh machine can be restored
  from disk when the network is slow or flaky;
* ``--offline`` / ``RSBVP_OFFLINE=1`` makes a redeploy work with no network at
  all (typical on a lab LAN), using only the local cache;
* nothing is ever downloaded from anywhere except PyPI and the npm registry -
  no dataset is touched, and no user files are overwritten.

Usage
-----
    python deploy_env.py --check                 # report state, change nothing
    python deploy_env.py --python-only           # venv + pip packages
    python deploy_env.py                          # venv + pip + node_modules
    python deploy_env.py --build                  # the above + build the frontend
    python deploy_env.py --force-install          # reinstall packages anyway
    python deploy_env.py --offline --python-only  # no network at all
    python deploy_env.py --print-json             # machine-readable summary

Exit codes: 0 = environment ready, 1 = could not prepare it, 2 = bad usage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
FRONTEND = ROOT / "gui" / "frontend"
NODE_MODULES = FRONTEND / "node_modules"
PACKAGE_LOCK = FRONTEND / "package-lock.json"
DIST_INDEX = FRONTEND / "dist" / "index.html"

CACHE_DIR = ROOT / ".cache" / "deploy"
PIP_CACHE = CACHE_DIR / "pip"
NPM_CACHE = CACHE_DIR / "npm"
WHEELS = CACHE_DIR / "wheels"

REQ_STAMP_NAME = ".rsbvp-requirements.sha256"
NPM_STAMP_NAME = ".rsbvp-package-lock.sha256"
STAMPS = (VENV / REQ_STAMP_NAME, NODE_MODULES / NPM_STAMP_NAME)

MIN_PYTHON = (3, 10)

# Import name for each distribution we must be able to import. Used to detect a
# half-installed environment (the usual result of an interrupted download).
REQUIRED_MODULES = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "python-multipart": "multipart",
    "pyserial": "serial",
    "numpy": "numpy",
    "scipy": "scipy",
    "pandas": "pandas",
    "matplotlib": "matplotlib",
    "pillow": "PIL",
    "opencv-python-headless": "cv2",
}

IS_WINDOWS = os.name == "nt"


class DeployError(RuntimeError):
    """Something the user has to fix (missing Python, no npm, ...)."""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def say(message: str = "") -> None:
    print(message, flush=True)


def ok(message: str) -> None:
    print(f"    [ok] {message}", flush=True)


def note(message: str) -> None:
    print(f"    [--] {message}", flush=True)


def bad(message: str) -> None:
    print(f"    [fail] {message}", flush=True)


def step(message: str) -> None:
    print(f"\n==> {message}", flush=True)


def file_digest(path: Path) -> str:
    """SHA-256 of a file, or '' when it does not exist."""
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def newest_mtime(paths) -> float:
    newest = 0.0
    for path in paths:
        for candidate in path.rglob("*"):
            if candidate.is_file():
                newest = max(newest, candidate.stat().st_mtime)
    return newest


def run(command, cwd: Path | None = None, env=None, capture: bool = False) -> subprocess.CompletedProcess:
    printable = command if isinstance(command, str) else " ".join(str(part) for part in command)
    print(f"    $ {printable}", flush=True)
    return subprocess.run(command, cwd=str(cwd) if cwd else None, env=env,
                          capture_output=capture, text=True, shell=isinstance(command, str))


def venv_python(venv: Path | None = None) -> Path | None:
    """The interpreter inside ``venv``, on Windows or POSIX layout."""
    venv = VENV if venv is None else venv
    for relative in ("bin/python", "bin/python3", "Scripts/python.exe", "Scripts/python3.exe"):
        candidate = venv / relative
        if candidate.is_file():
            return candidate
    return None


def python_version(executable) -> tuple[int, int] | None:
    try:
        result = subprocess.run(
            [str(executable), "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        major, minor = result.stdout.strip().split(".")
        return int(major), int(minor)
    except ValueError:
        return None


def remove_path(path: Path) -> None:
    """Delete a directory we created. A symlinked .venv is unlinked, not followed."""
    if path.is_symlink():
        path.unlink(missing_ok=True)
        return
    shutil.rmtree(path, ignore_errors=True)


def usable_venv(venv: Path | None = None) -> Path | None:
    """Return the venv's interpreter when the venv is complete and usable."""
    venv = VENV if venv is None else venv
    executable = venv_python(venv)
    if executable is None:
        return None
    version = python_version(executable)
    if version is None or version < MIN_PYTHON:
        return None
    if not (venv / "pyvenv.cfg").is_file():
        return None
    return executable


def find_base_python(offline: bool) -> list[str]:
    """A system interpreter able to create a venv (``venv`` or ``uv``)."""
    candidates: list[list[str]] = []
    if IS_WINDOWS:
        candidates += [["py", "-3"], ["python"], ["python3"]]
    else:
        candidates += [["python3.13"], ["python3.12"], ["python3.11"], ["python3"], ["python"]]
    for candidate in candidates:
        executable = shutil.which(candidate[0])
        if not executable:
            continue
        version = python_version(executable)
        if version is None or version < MIN_PYTHON:
            continue
        return candidate
    raise DeployError(
        "Python %d.%d+ was not found. Install it and re-run.\n"
        "     Linux : sudo apt install python3.12 python3.12-venv\n"
        "     macOS : brew install python@3.12\n"
        "     Windows: https://www.python.org/downloads/ (tick 'Add to PATH')"
        % MIN_PYTHON)


def pip_available(python: str) -> bool:
    result = subprocess.run([python, "-m", "pip", "--version"], capture_output=True, text=True)
    return result.returncode == 0


# ---------------------------------------------------------------------------
# virtual environment
# ---------------------------------------------------------------------------
def ensure_venv(force_recreate: bool = False, offline: bool = False) -> tuple[Path, bool]:
    """Create ``.venv`` only if needed. Returns (interpreter, created_now)."""
    step("Python environment")
    if force_recreate and (VENV.exists() or VENV.is_symlink()):
        note("--recreate: removing the existing .venv")
        remove_path(VENV)

    if VENV.exists() and not force_recreate:
        executable = usable_venv()
        if executable is not None:
            ok(f"reusing existing .venv (Python {'.'.join(map(str, python_version(executable)))})")
            return executable, False
        note("the existing .venv is incomplete or unusable -> recreating it")
        remove_path(VENV)

    interpreter = find_base_python(offline)
    version = python_version(shutil.which(interpreter[0]))
    say(f"    creating .venv once with {' '.join(interpreter)} "
        f"(Python {'.'.join(map(str, version))})")
    result = run(interpreter + ["-m", "venv", str(VENV)])
    if result.returncode != 0:
        raise DeployError(
            "could not create the virtual environment.\n"
            "     Debian/Ubuntu: sudo apt install python3.12-venv\n"
            "     then re-run the deploy script.")

    executable = usable_venv()
    if executable is None:
        raise DeployError("the virtual environment was created but is not usable")
    ok(f"created .venv ({executable})")
    return executable, True


def required_modules_import(python: Path) -> tuple[bool, list[str]]:
    code = ("import importlib\n"
            "missing = []\n"
            "for name in %r:\n"
            "    try:\n"
            "        importlib.import_module(name)\n"
            "    except Exception:\n"
            "        missing.append(name)\n"
            "print(','.join(missing))\n") % (sorted(REQUIRED_MODULES.values()),)
    result = subprocess.run([str(python), "-c", code], capture_output=True, text=True)
    if result.returncode != 0:
        return False, sorted(REQUIRED_MODULES.values())
    missing = [name for name in result.stdout.strip().split(",") if name]
    return not missing, missing


def package_state(python: Path) -> dict:
    """Cheap check: do the packages we need already import?"""
    complete, missing = required_modules_import(python)
    return {"complete": complete, "missing_modules": missing,
            "requirements_sha256": file_digest(REQUIREMENTS),
            "stamp": (VENV / REQ_STAMP_NAME).read_text(encoding="utf-8").strip()
            if (VENV / REQ_STAMP_NAME).is_file() else ""}


def ensure_packages(python: Path, force: bool = False, offline: bool = False,
                    skip: bool = False) -> dict:
    """Install from requirements.txt only when it changed or imports fail."""
    step("Python packages")
    if skip:
        complete, missing = required_modules_import(python)
        if not complete:
            raise DeployError(
                "--skip-install was given, but these packages are not importable yet:\n"
                f"     {', '.join(missing)}\n"
                "     Re-run without --skip-install (installs happen once, then are reused).")
        ok("--skip-install: reusing the packages already installed")
        return {"action": "skipped"}

    stamp_path = VENV / REQ_STAMP_NAME
    wanted = file_digest(REQUIREMENTS)
    installed_stamp = stamp_path.read_text(encoding="utf-8").strip() if stamp_path.is_file() else ""
    complete, missing = required_modules_import(python)

    if not force and complete and installed_stamp == wanted:
        ok("already up to date (requirements.txt unchanged)")
        return {"action": "reused"}

    if not force and complete and not installed_stamp:
        # .venv from an older script or a hand-made environment: it already has
        # everything, so record that instead of re-downloading it.
        stamp_path.write_text(wanted + "\n", encoding="utf-8")
        ok("packages already present -> recorded, nothing re-downloaded")
        return {"action": "adopted"}

    if not force and complete and installed_stamp and installed_stamp != wanted:
        note("requirements.txt changed since the last deploy -> checking for updates")
    elif not complete:
        note("missing packages: " + (", ".join(missing) if missing else "unknown")
             + " -> installing them")

    if not pip_available(python):
        note("pip is missing inside .venv -> bootstrapping it")
        bootstrap = run([str(python), "-m", "ensurepip", "--upgrade"], capture=True)
        if bootstrap.returncode != 0:
            raise DeployError("pip is not available inside .venv and could not be bootstrapped")

    WHEELS.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    # the local wheel cache first, then (optionally) the index
    env["PIP_CACHE_DIR"] = str(PIP_CACHE)
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")

    common = [str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS),
              "--no-input"]
    if offline:
        cached = sorted(str(path) for path in WHEELS.glob("*"))
        if not cached:
            raise DeployError(
                "offline mode, but the local wheel cache is empty.\n"
                "     Run once with a network connection, or drop the --offline flag.")
        note(f"offline: installing from {len(cached)} cached wheel(s)")
        command = [str(python), "-m", "pip", "install", "--no-index",
                   "--find-links", str(WHEELS), "-r", str(REQUIREMENTS), "--no-input"]
    else:
        command = common + ["--upgrade-strategy", "only-if-needed"]

    result = run(command, env=env)
    if result.returncode != 0:
        # second chance: restore from the local cache (works after a failure)
        if any(WHEELS.glob("*")):
            note("retrying from the local wheel cache in .cache/deploy/wheels")
            retry = run([str(python), "-m", "pip", "install", "--no-index",
                         "--find-links", str(WHEELS), "-r", str(REQUIREMENTS), "--no-input"],
                        env=env)
            if retry.returncode == 0:
                result = retry
    if result.returncode != 0:
        raise DeployError(
            "pip install failed.\n"
            "     Check your internet connection (or PyPI access), then re-run.\n"
            "     The .venv and any packages already installed were kept - nothing\n"
            "     has to be recreated or re-downloaded from scratch.")

    # warm the offline cache so a later redeploy needs no network
    if not offline:
        run([str(python), "-m", "pip", "download", "-r", str(REQUIREMENTS),
             "--dest", str(WHEELS), "--no-input"], env=env, capture=True)

    stamp_path.write_text(wanted + "\n", encoding="utf-8")
    ok("packages installed and recorded (next deploy will reuse them)")
    return {"action": "installed"}


# ---------------------------------------------------------------------------
# node / frontend
# ---------------------------------------------------------------------------
def npm_available() -> bool:
    return shutil.which("npm") is not None


def npm_env() -> dict:
    NPM_CACHE.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["npm_config_cache"] = str(NPM_CACHE)
    env.setdefault("npm_config_fund", "false")
    env.setdefault("npm_config_audit", "false")
    return env


def node_modules_state() -> dict:
    lock = file_digest(PACKAGE_LOCK)
    stamp_file = NODE_MODULES / NPM_STAMP_NAME
    stamp = stamp_file.read_text(encoding="utf-8").strip() if stamp_file.is_file() else ""
    present = NODE_MODULES.is_dir() and any(NODE_MODULES.iterdir())
    return {"present": present, "lock_sha256": lock, "stamp": stamp,
            "up_to_date": present and lock != "" and stamp == lock}


def adoptable_node_modules(state: dict) -> bool:
    """True when an existing node_modules clearly matches the current lockfile.

    ``npm ci`` deletes node_modules before installing, so it must not run on
    every deploy. On the first run of this caching logic there is no stamp file
    yet; if the tree looks complete (npm's own hidden lockfile is there and the
    build tool is installed) we adopt it and only rebuild if needed.
    """
    hidden_lock = NODE_MODULES / ".package-lock.json"
    if not (hidden_lock.is_file() and (NODE_MODULES / "vite").is_dir()):
        return False
    if not state["present"]:
        return False
    # npm rewrites the hidden lockfile whenever it installs: a hidden lockfile
    # older than package-lock.json means the tree predates the current lockfile.
    return hidden_lock.stat().st_mtime >= PACKAGE_LOCK.stat().st_mtime


def ensure_node_modules(offline: bool = False, skip: bool = False) -> dict:
    step("Interface dependencies (node_modules)")
    if not npm_available():
        raise DeployError(
            "npm (Node.js) was not found - it is required to build the interface.\n"
            "     Install Node.js LTS from https://nodejs.org/ and re-run.")
    if skip:
        ok("--skip-install: keeping node_modules")
        return {"action": "skipped"}

    state = node_modules_state()
    if state["up_to_date"]:
        ok("node_modules already up to date (package-lock.json unchanged)")
        return {"action": "reused"}

    if adoptable_node_modules(state):
        (NODE_MODULES / NPM_STAMP_NAME).write_text(state["lock_sha256"] + "\n", encoding="utf-8")
        ok("reusing the node_modules already in the checkout (no reinstall)")
        return {"action": "adopted"}

    if state["present"]:
        note("package-lock.json changed since the last deploy -> reinstalling")
    else:
        note("first run for this checkout -> installing interface dependencies once")

    env = npm_env()
    # `npm ci` wipes node_modules; only reach for it when it is really needed.
    command = ["npm", "ci", "--silent", "--no-audit", "--no-fund"]
    if offline:
        command.append("--prefer-offline")
        note("offline: using the npm cache in .cache/deploy/npm")
    result = run(command, cwd=FRONTEND, env=env)
    if result.returncode != 0 and not state["present"]:
        note("npm ci failed -> trying a plain install")
        result = run(["npm", "install", "--silent", "--no-audit", "--no-fund"],
                     cwd=FRONTEND, env=env)
    if result.returncode != 0:
        raise DeployError(
            "could not install the interface dependencies.\n"
            "     Check your internet connection, then re-run.\n"
            "     Existing node_modules and the npm cache were kept.")

    (NODE_MODULES / NPM_STAMP_NAME).write_text(state["lock_sha256"] + "\n", encoding="utf-8")
    ok("interface dependencies installed (next deploy will reuse them)")
    return {"action": "installed"}


def frontend_needs_build() -> tuple[bool, str]:
    if not DIST_INDEX.is_file():
        return True, "no previous build"
    built_at = DIST_INDEX.stat().st_mtime
    sources = [FRONTEND / name for name in ("src", "public", "index.html")]
    sources += [FRONTEND / name for name in
                ("package.json", "package-lock.json", "vite.config.js", "vite.config.ts")]
    newest = newest_mtime([path for path in sources if path.exists()])
    if newest > built_at:
        return True, "frontend sources changed"
    return False, "build is newer than the sources"


def build_frontend(force: bool = False) -> dict:
    step("Web interface build")
    needed, reason = frontend_needs_build()
    if not needed and not force:
        ok(f"reusing gui/frontend/dist ({reason})")
        return {"action": "reused"}
    note(reason + " -> building")
    result = run(["npm", "run", "build"], cwd=FRONTEND, env=npm_env())
    if result.returncode != 0 or not DIST_INDEX.is_file():
        raise DeployError("the frontend build failed - see the output above")
    ok("built gui/frontend/dist")
    return {"action": "built"}


# ---------------------------------------------------------------------------
# stale artefact cleanup
# ---------------------------------------------------------------------------
def clean_artifacts() -> list[str]:
    """Remove only files this project generated. Never user data."""
    removed = []
    for path in STAMPS:
        if path.is_file():
            path.unlink()
            removed.append(str(path.relative_to(ROOT)))
    for path in (ROOT / ".run" / "rsbvp.pid",):
        if path.is_file():
            path.unlink()
            removed.append(str(path.relative_to(ROOT)))
    if removed:
        for item in removed:
            note(f"removed {item}")
    return removed


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------
def report() -> dict:
    executable = usable_venv()
    python = executable or venv_python()
    node_state = node_modules_state()
    build_needed, reason = frontend_needs_build()
    payload = {
        "venv": {"path": str(VENV), "exists": VENV.is_dir(),
                 "usable": executable is not None,
                 "python": str(executable) if executable else None,
                 "version": ".".join(map(str, python_version(python))) if python and
                 python_version(python) else None},
        "packages": package_state(executable) if executable else {"complete": False},
        "node_modules": node_state,
        "frontend": {"dist": str(DIST_INDEX), "build_needed": build_needed,
                     "reason": reason},
        "cache": {"dir": str(CACHE_DIR),
                  "wheels": len(list(WHEELS.glob("*"))) if WHEELS.is_dir() else 0},
    }
    return payload


def print_report(payload: dict) -> None:
    venv_info = payload["venv"]
    say("=" * 70)
    say(" RSBVP deployment environment")
    say("=" * 70)
    if venv_info["usable"]:
        say(f" .venv      : ready (Python {venv_info['version']}) -> {venv_info['path']}")
    elif venv_info["exists"]:
        say(f" .venv      : present but unusable -> {venv_info['path']} (will be recreated)")
    else:
        say(f" .venv      : not created yet -> {venv_info['path']} (created on first deploy)")
    packages = payload["packages"]
    if packages.get("complete"):
        say(" packages   : all imports available")
    else:
        say(" packages   : missing -> " + ", ".join(packages.get("missing_modules") or ["unknown"]))
    node = payload["node_modules"]
    if not node["up_to_date"] and adoptable_node_modules(node):
        node["up_to_date"] = True
    say(" node_modules: " + ("up to date" if node["up_to_date"]
                              else ("stale -> reinstall" if node["present"] else "not installed")))
    frontend = payload["frontend"]
    say(" interface  : " + ("rebuilt on next deploy (" + frontend["reason"] + ")"
                            if frontend["build_needed"] else "build is current"))
    say(f" cache      : {payload['cache']['dir']} ({payload['cache']['wheels']} wheels)")
    say("=" * 70)
    say(" Redeploying reuses all of the above. Nothing is re-downloaded unless")
    say(" requirements.txt or package-lock.json changed, a package is missing, or")
    say(" the frontend sources are newer than the build.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare the RSBVP deployment environment, reusing what already exists.")
    parser.add_argument("--check", action="store_true",
                        help="report the current state and exit (changes nothing)")
    parser.add_argument("--python-only", action="store_true",
                        help="only the virtual environment and Python packages")
    parser.add_argument("--build", action="store_true", help="also build the frontend")
    parser.add_argument("--recreate", action="store_true",
                        help="delete and rebuild .venv (last resort)")
    parser.add_argument("--force-install", action="store_true",
                        help="re-run pip install even if packages look installed")
    parser.add_argument("--rebuild", action="store_true", help="rebuild the frontend anyway")
    parser.add_argument("--clean", action="store_true",
                        help="only remove generated stamps/PID file, then exit")
    parser.add_argument("--skip-install", action="store_true",
                        help="do not install Python or node packages")
    parser.add_argument("--offline", action="store_true",
                        help="use only the local cache in .cache/deploy (no network)")
    parser.add_argument("--print-json", action="store_true", help="print a JSON summary")
    args = parser.parse_args(argv)

    offline = args.offline or os.environ.get("RSBVP_OFFLINE") in ("1", "true", "yes")

    try:
        if args.check:
            payload = report()
            if args.print_json:
                print(json.dumps(payload))
            else:
                print_report(payload)
            return 0

        if args.clean:
            step("Removing generated files")
            if not clean_artifacts():
                ok("nothing to remove")
            return 0

        python, _ = ensure_venv(force_recreate=args.recreate, offline=offline)
        package_result = ensure_packages(python, force=args.force_install,
                                         offline=offline, skip=args.skip_install)
        summary = {"python": str(python), "packages": package_result}

        # Everything after this point needs npm; the server itself does not, so a
        # machine that already has a build can still deploy without Node.js.
        if not args.python_only:
            if npm_available():
                summary["node_modules"] = ensure_node_modules(offline=offline,
                                                              skip=args.skip_install)
                if args.build:
                    summary["frontend"] = build_frontend(force=args.rebuild)
            elif DIST_INDEX.is_file():
                note("npm not found, but gui/frontend/dist already exists -> using it")
                summary["node_modules"] = {"action": "skipped (no npm)"}
            else:
                raise DeployError(
                    "npm (Node.js) was not found and there is no build to reuse.\n"
                    "     Install Node.js LTS from https://nodejs.org/ and re-run.")

        if args.print_json:
            print(json.dumps({"ready": True, **summary, "python_executable": str(python)}))
        else:
            ok("environment ready")
        return 0

    except DeployError as exc:
        print("", flush=True)
        bad(str(exc))
        return 1


__all__ = [
    "DeployError", "ROOT", "VENV", "REQUIREMENTS", "FRONTEND", "NODE_MODULES",
    "PACKAGE_LOCK", "DIST_INDEX", "CACHE_DIR", "WHEELS", "REQ_STAMP_NAME",
    "NPM_STAMP_NAME", "REQUIRED_MODULES",
    "file_digest", "newest_mtime", "venv_python", "usable_venv", "find_base_python",
    "ensure_venv", "required_modules_import", "package_state", "ensure_packages",
    "npm_available", "node_modules_state", "adoptable_node_modules",
    "ensure_node_modules", "frontend_needs_build", "build_frontend",
    "clean_artifacts", "report", "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
