"""The live socket must measure the camera of the device that opened the page.

Regression context: the live pathway used to open ``cv2.VideoCapture`` on the
*machine running the backend*, so a phone (or a second laptop) viewing the
dashboard measured the host laptop's webcam. These tests pin the replacement:
the browser sends its own frames, the server decodes them, and the measurement
code path stays the same.
"""
from __future__ import annotations

import base64

import cv2
import numpy as np
import pytest

pytest.importorskip("cv2")

from rppg_core.remote_live import (  # noqa: E402
    MAX_FRAME_BYTES,
    FrameDecodeError,
    RemoteLiveSession,
    SourceFrameCamera,
    decode_envelope,
    decode_frame,
)


def _jpeg(width: int = 640, height: int = 480, seed: int = 0) -> bytes:
    rng = np.random.default_rng(seed)
    frame = (rng.random((height, width, 3)) * 255).astype("uint8")
    ok, buffer = cv2.imencode(".jpg", frame)
    assert ok
    return buffer.tobytes()


# ---------------------------------------------------------------------------
# decoding
# ---------------------------------------------------------------------------
def test_decodes_a_jpeg_frame():
    frame = decode_frame(_jpeg())
    assert frame.shape[0] == 480 and frame.shape[1] == 640
    assert frame.ndim == 3 and frame.shape[2] == 3, "the rPPG pipeline needs BGR"


def test_decodes_a_png_frame():
    rng = np.random.default_rng(1)
    ok, buffer = cv2.imencode(".png", (rng.random((120, 160, 3)) * 255).astype("uint8"))
    assert ok
    assert decode_frame(buffer.tobytes()).shape[:2] == (120, 160)


def test_rejects_empty_and_non_image_payloads():
    with pytest.raises(FrameDecodeError, match="Empty"):
        decode_frame(b"")
    with pytest.raises(FrameDecodeError, match="JPEG or PNG"):
        decode_frame(b"definitely not an image")


def test_rejects_oversized_frames():
    with pytest.raises(FrameDecodeError, match="too large"):
        decode_frame(b"\xff\xd8\xff" + b"0" * (MAX_FRAME_BYTES + 1))


def test_rejects_undecodable_image_data():
    # valid JPEG magic, corrupt body
    with pytest.raises(FrameDecodeError):
        decode_frame(b"\xff\xd8\xff" + b"\x00" * 32)


# ---------------------------------------------------------------------------
# text envelope transport (fallback for clients without binary frames)
# ---------------------------------------------------------------------------
def test_envelope_accepts_base64_frame():
    payload = _jpeg(seed=2)
    frame = decode_frame(decode_envelope(
        {"type": "frame", "data": base64.b64encode(payload).decode()}))
    assert frame.shape[1] == 640


def test_envelope_accepts_data_url():
    payload = _jpeg(seed=3)
    data_url = "data:image/jpeg;base64," + base64.b64encode(payload).decode()
    assert decode_frame(decode_envelope({"type": "frame", "data_url": data_url})) is not None


def test_envelope_ignores_non_frame_messages():
    assert decode_envelope({"action": "stop"}) is None
    assert decode_envelope({"type": "frame"}) is None
    assert decode_envelope("not a dict") is None


# ---------------------------------------------------------------------------
# the stand-in camera
# ---------------------------------------------------------------------------
def test_camera_keeps_only_the_newest_frame():
    camera = SourceFrameCamera()
    assert camera.read() == (False, None)

    camera.push(decode_frame(_jpeg(seed=4)))
    ok, first = camera.read()
    assert ok and first is not None

    camera.push(decode_frame(_jpeg(seed=5)))
    camera.push(decode_frame(_jpeg(seed=6)))
    ok, newest = camera.read()
    assert ok and newest is not None
    # the frame that was never read was dropped instead of queued
    assert camera.dropped == 1
    assert camera.received == 3


def test_camera_implements_the_opencv_surface_used_by_the_session():
    camera = SourceFrameCamera()
    assert camera.isOpened() is True
    assert camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640) is True
    assert camera.get(cv2.CAP_PROP_FRAME_WIDTH) == 640.0
    camera.release()
    assert camera.isOpened() is False
    camera.push(decode_frame(_jpeg()))  # ignored after release
    assert camera.read() == (False, None)


def test_camera_reports_a_timeout_when_no_frame_arrives():
    assert SourceFrameCamera().wait_for_first_frame(timeout=0.05) is False


# ---------------------------------------------------------------------------
# the session itself
# ---------------------------------------------------------------------------
def test_remote_session_never_opens_the_host_webcam(monkeypatch):
    """The whole point: no cv2.VideoCapture on the server for browser frames."""
    import rppg_core.live as live_module

    def forbidden(*_args, **_kwargs):
        raise AssertionError("cv2.VideoCapture must not be used for browser frames")

    monkeypatch.setattr(live_module.cv2, "VideoCapture", forbidden)

    source = SourceFrameCamera()
    source.push(decode_frame(_jpeg()))
    session = RemoteLiveSession(source=source)
    session.open()
    assert session.cap is source, "the session must read from the browser source"
    assert type(session).__name__ == "RemoteLiveSession"


def test_remote_session_waits_for_the_first_frame_before_opening():
    session = RemoteLiveSession(source=SourceFrameCamera())
    with pytest.raises(RuntimeError, match="No camera frames"):
        session.open()


def test_remote_session_processes_browser_frames_end_to_end():
    """One pushed frame produces one processed state with a preview image."""
    source = SourceFrameCamera()
    source.push(decode_frame(_jpeg()))
    session = RemoteLiveSession(source=source)
    session.open()
    try:
        state = session.process_frame()
        assert state is not None
        assert state["frame_index"] == 1
        preview = session.encode_last_preview()
        assert preview and preview.startswith("data:image/jpeg;base64,")
    finally:
        session.close()


def test_remote_session_records_the_camera_source_without_host_paths():
    session = RemoteLiveSession(source=SourceFrameCamera())
    described = session.describe_source()
    assert described["kind"] == "browser"
    assert "received" in described


# ---------------------------------------------------------------------------
# structural guards for the websocket wiring
# ---------------------------------------------------------------------------
def test_frames_are_received_before_the_session_waits_for_one():
    """Regression: the client watcher must start *before* session.open().

    open() blocks waiting for the first browser frame. If the receiver is only
    created afterwards, nothing is ever received and every session times out -
    which is exactly what happened the first time this pathway was written.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "gui" / "backend" / "main.py").read_text(
        encoding="utf-8")
    watcher_at = source.index("watcher = asyncio.create_task(_watch_client())")
    open_at = source.index("session = await loop.run_in_executor(None, session.open)")
    assert watcher_at < open_at, "the frame receiver must start before open() waits"


def test_live_socket_defaults_to_the_browser_camera():
    """A client that does not say otherwise must never trigger host capture."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "gui" / "backend" / "main.py").read_text(
        encoding="utf-8")
    assert 'cfg.get("camera_source") or "browser"' in source


def test_frontend_declares_the_browser_source_and_sends_frames():
    from pathlib import Path

    live = (Path(__file__).resolve().parents[1] / "gui" / "frontend" / "src" / "Live.tsx").read_text(
        encoding="utf-8")
    assert "camera_source: 'browser'" in live
    assert "startBrowserCamera" in live, "the page must acquire the local camera itself"
    # the host camera *index* must not be sent; only a camera_source marker
    sent = [line for line in live.splitlines() if " camera_index:" in line]
    assert not sent, f"the host camera index must not be sent any more: {sent}"
