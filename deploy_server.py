#!/usr/bin/env python3
"""Run RSBVP as a deployed service on any operating system.

This is the single entry point used by ``deploy.sh`` (Linux/macOS/WSL/Git Bash),
``deploy.cmd`` (Windows) and ``deploy.ps1`` (Windows PowerShell), so the banner,
the port handling and the browser opening behave identically everywhere.

What "deploy" means here
------------------------
* the web interface is already built (``gui/frontend/dist``) by the caller;
* ``RSBVP_FRONTEND_DIST`` is set so the backend serves that build at ``/``;
* the FastAPI app is served by uvicorn on one port, bound to 0.0.0.0 by default
  (reachable from this machine and the local network, which is what the rest of
  this repository assumes) or 127.0.0.1 with ``--host 127.0.0.1`` for a
  strictly local-only deployment;
* the health endpoint is polled until the app answers, so the script only
  reports success when the service is genuinely up.

This is a local research deployment, not a hardened internet-facing server:
there is no authentication, no TLS and no multi-user isolation. Keep it on a
trusted network.

Usage
-----
    python deploy_server.py --dist gui/frontend/dist --port 8000
    python deploy_server.py --dist gui/frontend/dist --port 8000 --host 0.0.0.0 --open
    python deploy_server.py --stop --pidfile .run/rsbvp.pid
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_DIST = ROOT / "gui" / "frontend" / "dist"
DEFAULT_PIDFILE = ROOT / ".run" / "rsbvp.pid"
DEFAULT_LOGFILE = ROOT / ".run" / "server.log"


def free_port(host: str, preferred: int, attempts: int = 25) -> int:
    """Return ``preferred`` if bindable, otherwise the next free port."""
    for offset in range(attempts):
        candidate = preferred + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host if host != "0.0.0.0" else "0.0.0.0", candidate))
            except OSError:
                continue
        return candidate
    raise SystemExit(f"no free port in range {preferred}-{preferred + attempts - 1}")


def wait_until_healthy(url: str, timeout_s: float = 45.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    body = response.read(4096).decode("utf-8", "replace")
                    if '"status"' in body or "ok" in body.lower():
                        return True
        except (urllib.error.URLError, ConnectionError, OSError, TimeoutError):
            time.sleep(0.4)
    return False


def lan_address() -> str | None:
    """Best-effort local network address for the 'open on your phone' hint."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))  # no packets are sent
            return probe.getsockname()[0]
    except OSError:
        return None


def unpack_dataset(dest: Path) -> int:
    """Unpack the bundled rPPG-10 archive (zip inside a zip) and validate it.

    Deliberately NOT part of a normal deployment: data is unpacked only when the
    user asks for it. See the "dataset exception" note in README.md.
    """
    import zipfile

    archive = ROOT / "data" / "rPPG-10.zip"
    if not archive.is_file():
        print(f"ERROR: {archive} is not present.", file=sys.stderr)
        return 2
    dest.mkdir(parents=True, exist_ok=True)
    print(f"==> unpacking {archive.name} -> {dest}")
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(dest)
    for inner in dest.rglob("Dataset_rPPG-10.zip"):
        print(f"    nested archive: {inner.name}")
        with zipfile.ZipFile(inner) as bundle:
            bundle.extractall(dest)
    subject = next((p for p in dest.rglob("Subject_1") if p.is_dir()), None)
    if subject is None:
        print("ERROR: could not find Subject_1 after unpacking.", file=sys.stderr)
        return 1
    root = subject.parent
    print(f"[ok] dataset at {root}")
    print(f"     unpacked copies are ignored by Git; the licence is CC BY-NC-SA 4.0 "
          f"(non-commercial, share-alike).")
    return 0


def cmd_stop(args) -> int:
    pidfile = Path(args.pidfile)
    if not pidfile.is_file():
        print(f"nothing to stop (no pid file at {pidfile})")
        return 0
    try:
        pid = int(pidfile.read_text(encoding="utf-8").strip())
    except ValueError:
        print(f"pid file {pidfile} is unreadable; removing it")
        pidfile.unlink(missing_ok=True)
        return 0
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        print(f"process {pid} is not running")
    except OSError as exc:
        print(f"could not stop process {pid}: {exc}")
        return 1
    pidfile.unlink(missing_ok=True)
    print(f"stopped RSBVP (pid {pid})")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Deploy RSBVP locally (serve the API + built UI).")
    parser.add_argument("--dist", default=str(DEFAULT_DIST), help="built frontend directory")
    parser.add_argument("--host", default="0.0.0.0",
                        help="127.0.0.1 = this machine only; 0.0.0.0 = whole local network")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--open", action="store_true", help="open the browser when ready")
    parser.add_argument("--pidfile", default=str(DEFAULT_PIDFILE))
    parser.add_argument("--logfile", default=str(DEFAULT_LOGFILE))
    parser.add_argument("--stop", action="store_true", help="stop a server started by this script")
    parser.add_argument("--check", action="store_true", help="start, poll /api/health, then exit")
    parser.add_argument("--unpack-dataset", action="store_true",
                        help="only unpack the bundled rPPG-10 dataset, then exit")
    parser.add_argument("--dataset-dest", default=str(ROOT / "data" / "rppg10"))
    parser.add_argument("--foreground", action="store_true",
                        help="do not detach; log to the terminal (for containers/CI)")
    args = parser.parse_args(argv)

    if args.unpack_dataset:
        return unpack_dataset(Path(args.dataset_dest).expanduser().resolve())

    if args.stop:
        return cmd_stop(args)

    dist = Path(args.dist).expanduser().resolve()
    if not (dist / "index.html").is_file():
        print(f"ERROR: no built web interface at {dist} (index.html missing).", file=sys.stderr)
        print("       Build it first:  cd gui/frontend && npm ci && npm run build", file=sys.stderr)
        return 2

    port = free_port(args.host, args.port)
    if port != args.port:
        print(f"port {args.port} is busy -> using {port}")

    env = dict(os.environ)
    env["RSBVP_FRONTEND_DIST"] = str(dist)
    env.setdefault("PYTHONUNBUFFERED", "1")

    # The app package lives in gui/, so run uvicorn with gui/ as the cwd and
    # gui/ on PYTHONPATH (the module is imported as "backend.main").
    gui_dir = ROOT / "gui"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(gui_dir)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))

    command = [sys.executable, "-m", "uvicorn", "backend.main:app",
               "--host", args.host, "--port", str(port)]
    if not args.foreground:
        command += ["--log-level", "info"]

    print("=" * 74)
    print(" RSBVP deployment")
    print("=" * 74)
    print(f" interface : {dist}")
    print(f" open      : http://localhost:{port}")
    if args.host == "0.0.0.0":
        lan = lan_address()
        print(f" listening : 0.0.0.0:{port} (reachable from this network)")
        if lan:
            print(f" same Wi-Fi: http://{lan}:{port}")
    else:
        print(f" listening : {args.host}:{port} (this machine only)")
    print(f" health    : http://127.0.0.1:{port}/api/health")
    print(f" stop with : python deploy_server.py --stop --pidfile {args.pidfile}")
    print("=" * 74)

    Path(args.logfile).parent.mkdir(parents=True, exist_ok=True)
    Path(args.pidfile).parent.mkdir(parents=True, exist_ok=True)

    if args.foreground:
        os.environ.update(env)
        os.chdir(gui_dir)
        os.execv(sys.executable, command)  # never returns

    log = open(args.logfile, "ab")  # noqa: SIM115 - handle passed to the child
    process = subprocess.Popen(command, cwd=str(gui_dir), env=env,
                               stdout=log, stderr=subprocess.STDOUT,
                               start_new_session=(os.name != "nt"))
    Path(args.pidfile).write_text(str(process.pid), encoding="utf-8")

    healthy = wait_until_healthy(f"http://127.0.0.1:{port}/api/health")
    if not healthy:
        print("ERROR: the server did not become healthy. Last log lines:", file=sys.stderr)
        try:
            tail = Path(args.logfile).read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
            for line in tail:
                print("   " + line, file=sys.stderr)
        except OSError:
            pass
        print(f" full log: {args.logfile}", file=sys.stderr)
        return 1

    print(f"[ok] server is up (pid {process.pid}, log {args.logfile})")
    print(f"     open http://localhost:{port}")
    print(json.dumps({"pid": process.pid, "port": port, "host": args.host,
                      "url": f"http://localhost:{port}", "dist": str(dist)}))

    if args.open:
        threading.Thread(target=lambda: webbrowser.open(f"http://localhost:{port}"),
                         daemon=True).start()
    if args.check:
        cmd_stop(args)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
