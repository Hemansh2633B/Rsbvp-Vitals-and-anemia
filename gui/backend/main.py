"""FastAPI backend for the mrz rPPG dashboard (offline analysis).

Local single-user tool: the /analyze endpoint runs the pipeline
synchronously and returns the full result in one response. Generated
plot PNGs and the run log are written under runs/<run_id>/ and served
back as static files.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import threading
import uuid
from pathlib import Path

from fastapi import (
    FastAPI,
    File,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from rppg_core import analyze
from rppg_core.device import list_serial_ports
from rppg_core.live import LiveSession
from rppg_core.live_eval import evaluate_live_recording

BASE_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = BASE_DIR / "runs"
RUNS_DIR.mkdir(exist_ok=True)

VIDEO_SUFFIXES = {".avi", ".mp4", ".mov", ".mkv"}
MAX_VIDEO_BYTES = 512 * 1024 * 1024
MAX_CSV_BYTES = 20 * 1024 * 1024


def _copy_limited(upload: UploadFile, destination: Path, limit: int) -> None:
    total = 0
    with destination.open("wb") as output:
        while chunk := upload.file.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                output.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Uploaded file exceeds the size limit.")
            output.write(chunk)

app = FastAPI(title="mrz rPPG dashboard", version="0.1.0")

# In deployment the built frontend is served from this same app (same origin), so
# no CORS is needed. CORS is only added for the Vite development server, whose
# port is not fixed (5173, 5174, ... when the first port is taken).
_DEV_ORIGIN_RE = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_DEV_ORIGIN_RE,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _new_run_id() -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{uuid.uuid4().hex[:6]}"


def _run_dir(run_id: str) -> Path:
    # Resolve and guard against path traversal in the run id.
    path = (RUNS_DIR / run_id).resolve()
    if RUNS_DIR.resolve() not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid run id.")
    return path


def _result_payload(run_id: str, summary: dict) -> dict:
    plots = summary.get("plots", [])
    return {
        "run_id": run_id,
        "summary": summary,
        "plot_urls": [f"/api/runs/{run_id}/files/{name}" for name in plots],
        "log_url": (
            f"/api/runs/{run_id}/files/{summary['log']}"
            if summary.get("log")
            else None
        ),
    }


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/analyze")
def analyze_upload(
    video: UploadFile = File(...),
    csv: UploadFile | None = File(None),
) -> dict:
    """Analyze an uploaded video (+ optional CMS50D CSV)."""
    suffix = Path(video.filename or "").suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported video type '{suffix}'. Use one of {sorted(VIDEO_SUFFIXES)}.",
        )

    run_id = _new_run_id()
    run_dir = _run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    video_path = run_dir / f"input{suffix}"
    _copy_limited(video, video_path, MAX_VIDEO_BYTES)

    csv_path = None
    if csv is not None and csv.filename:
        csv_path = run_dir / "input.csv"
        _copy_limited(csv, csv_path, MAX_CSV_BYTES)

    return _run_analysis(run_id, run_dir, video_path, csv_path)


def _run_analysis(run_id, run_dir, video_path, csv_path) -> dict:
    try:
        summary = analyze(
            str(video_path),
            csv_path=str(csv_path) if csv_path else None,
            out_dir=str(run_dir),
        )
    except Exception as exc:
        logging.exception("Analysis failed for run %s", run_id)
        # Do not expose server filesystem paths or implementation details.
        raise HTTPException(status_code=500, detail="Analysis failed; consult the local server log.") from exc
    return _result_payload(run_id, summary)


@app.get("/api/runs")
def list_runs() -> list[dict]:
    runs = []
    for path in sorted(RUNS_DIR.glob("*/"), reverse=True):
        if path.name.startswith("_"):
            continue
        plots = sorted(p.name for p in path.glob("*.png"))
        if not plots:
            continue
        runs.append({"run_id": path.name, "n_plots": len(plots)})
    return runs


@app.get("/api/runs/{run_id}/files/{name:path}")
def get_run_file(run_id: str, name: str) -> FileResponse:
    # name may include a subfolder (e.g. "offline/plot_01.png").
    run_dir = _run_dir(run_id)
    file_path = (run_dir / name).resolve()
    if run_dir not in file_path.parents or not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(file_path)


# ============================================================
# Live mode
# ============================================================

@app.get("/api/devices")
def list_devices() -> dict:
    """Serial ports (for the optional CMS50D) + default camera hint.

    Cameras are not opened here (that would trigger an OS permission prompt
    on every poll); the UI defaults to index 0 and can override.
    """
    ports = list_serial_ports()
    return {
        "serial_ports": ports,
        "cms_candidate": next((p["device"] for p in ports if p["candidate"]), None),
        "default_camera_index": 0,
    }


@app.websocket("/ws/live")
async def live_ws(ws: WebSocket) -> None:
    """Stream live rPPG (and optional CMS50D) state to the browser.

    Protocol: client sends one JSON start message, e.g.
        {"camera_index": 0, "serial_port": null, "duration": 60, "record": false}
    Server streams {"type": "frame", ...} messages and a final
    {"type": "done"} (or {"type": "error", ...}).
    Client may send {"action": "stop"} at any time.
    """
    await ws.accept()
    session: LiveSession | None = None
    stop = threading.Event()  # shared with the capture thread

    # Preview streaming rate (decoupled from the ~30 FPS processing loop).
    stream_fps = 15

    try:
        cfg = await ws.receive_json()
        camera_index = int(cfg.get("camera_index", 0))
        serial_port = cfg.get("serial_port") or None
        duration = cfg.get("duration")  # seconds, or None for unbounded
        record = bool(cfg.get("record", False))
        # segment_mode = 2-min "motion segment" behaviour; off = original 30s.
        segment_mode = bool(cfg.get("segment_mode", False))

        record_path = None
        run_id = None
        run_dir = None
        if record:
            run_id = _new_run_id()
            run_dir = _run_dir(run_id)
            run_dir.mkdir(parents=True, exist_ok=True)
            record_path = run_dir / "live_input.avi"

        loop = asyncio.get_running_loop()
        session = await loop.run_in_executor(
            None,
            lambda: LiveSession(
                camera_index=camera_index,
                serial_port=serial_port,
                record_path=record_path,
                segment_mode=segment_mode,
            ).open(),
        )

        await ws.send_json({
            "type": "started",
            "cms_connected": session.cms_connected,
            "cms_streaming": session.cms_streaming,
            "cms_error": session.cms_error,
            "serial_port": serial_port,
            "recording": bool(record_path),
            "segment_mode": session.segment_mode,
        })

        # Watch for a client stop message without blocking the stream loop.
        async def _watch_stop() -> None:
            try:
                while not stop.is_set():
                    msg = await ws.receive_json()
                    if msg.get("action") == "stop":
                        stop.set()
                        return
            except Exception:
                stop.set()

        watcher = asyncio.create_task(_watch_stop())

        # Run the capture+processing loop in its own thread so the motion/RGB
        # buffers fill at the camera's ~30 FPS (matching the scripts), while we
        # stream the preview to the browser at a lower, throttled rate.
        capture_future = loop.run_in_executor(
            None, session.run_capture, stop, duration
        )

        last_streamed_index = -1
        try:
            while not capture_future.done():
                await asyncio.sleep(1.0 / stream_fps)
                state = session._last_state
                if state is None:
                    continue
                # Skip when the capture thread has not produced a new frame
                # since our last send (it may run below stream_fps on slower
                # machines); avoids re-encoding+resending an identical frame.
                idx = state.get("frame_index")
                if idx == last_streamed_index:
                    continue
                last_streamed_index = idx
                # Encode the JPEG preview in the thread pool, NOT on the event
                # loop. JPEG + base64 is CPU-heavy; doing it inline here would
                # block every websocket send and starve the ~30 FPS capture
                # thread of GIL time (the script's cv2.imshow is ~free, so this
                # is the main gap vs the native GUI).
                out = dict(state)
                out["frame"] = await loop.run_in_executor(
                    None, session.encode_last_preview
                )
                await ws.send_json(out)
        finally:
            stop.set()
            watcher.cancel()
            await capture_future  # let the capture loop finish cleanly

        if session._capture_error:
            await ws.send_json({"type": "error", "detail": session._capture_error})

        # Flush + close the recording (CSV and video writer) BEFORE reading it
        # back. Both are buffered and only guaranteed on disk after close();
        # running the evaluation / offline analysis first would read a partial
        # or empty file (the 30s sync CSV came back empty -> pandas
        # "No columns to parse from file"). close() is idempotent, so the
        # finally-block call below is a harmless no-op.
        if session is not None and record_path is not None:
            await asyncio.get_running_loop().run_in_executor(None, session.close)

        done_msg = {"type": "done"}
        if session is not None and session.segment_mode:
            done_msg["segments"] = session.segment_summaries()
            # Persist the motion-segment HR summary CSV (2-min script parity).
            if run_dir is not None:
                try:
                    session.write_segment_summary_csv(
                        run_dir / "live_motion_segment_summary.csv"
                    )
                except Exception:
                    pass

        # Post-recording metric evaluation (only when we recorded a CSV).
        if record_path is not None and run_dir is not None:
            csv_path = run_dir / "live_input_sync.csv"
            if csv_path.exists():
                try:
                    loop = asyncio.get_running_loop()
                    eval_result = await loop.run_in_executor(
                        None,
                        lambda: evaluate_live_recording(str(csv_path), str(run_dir)),
                    )
                    eval_result["run_id"] = run_id
                    files = [eval_result.get("dashboard"),
                             eval_result.get("segment_summary_csv"),
                             eval_result.get("metric_summary_csv"),
                             eval_result.get("log")]
                    eval_result["urls"] = {
                        name: f"/api/runs/{run_id}/files/{name}"
                        for name in files if name
                    }
                    done_msg["evaluation"] = eval_result
                except Exception as exc:
                    done_msg["evaluation_error"] = str(exc)

        await ws.send_json(done_msg)

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await ws.send_json({"type": "error", "detail": str(exc)})
        except Exception:
            pass
    finally:
        if session is not None:
            await asyncio.get_running_loop().run_in_executor(None, session.close)
        try:
            await ws.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Production deployment: serve the built web interface from this same process.
#
# `deploy.sh` / `deploy.cmd` / `deploy.ps1` (via deploy_server.py) build
# gui/frontend and point RSBVP_FRONTEND_DIST at the output. When that variable is
# set and the directory exists, the app serves the SPA at "/" so one URL and one
# port are enough. API routes (/api/...) and the websocket (/ws/...) are declared
# above and therefore keep precedence over the catch-all mount.
# --------------------------------------------------------------------------- #
_FRONTEND_DIST = os.environ.get("RSBVP_FRONTEND_DIST", "").strip()
if _FRONTEND_DIST:
    _dist_path = Path(_FRONTEND_DIST).expanduser().resolve()
    if (_dist_path / "index.html").is_file():
        app.mount("/", StaticFiles(directory=str(_dist_path), html=True), name="frontend")
    else:
        # Fail loudly rather than silently serving an API-only app.
        @app.get("/")
        def _frontend_missing() -> JSONResponse:
            return JSONResponse(
                status_code=503,
                content={"detail": "RSBVP_FRONTEND_DIST is set but contains no index.html "
                                   f"({_dist_path}). Build the frontend first."},
            )
