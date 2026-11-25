"""Live rPPG driven by frames from the *browser's* camera, not the host's.

Why this module exists
----------------------
The original live pathway (`rppg_core.live.LiveSession`) opens a webcam through
OpenCV **on the machine running the backend**. When a phone or another laptop
opened the dashboard, the video that appeared was the host laptop's camera -
the person holding the phone was never seen. That is a correctness bug, not a
preference: the measurement has to come from the device the user is using.

This module takes the opposite direction: the browser acquires its own camera
with `getUserMedia` (so the user sees the normal camera permission prompt on
*their* device) and streams frames over the existing `/ws/live` websocket. The
server decodes those frames and feeds them through the **same** measurement
code as the local pathway - `LiveSession` - by substituting the camera read step
only. ROI, motion classification, rPPG estimation, the CMS50D oximeter
integration and the recorded CSV/video are therefore identical to a local run;
nothing about the algorithm changes, only where the pixels come from.

Two frame transports are accepted, both over the same socket:

* ``binary`` messages - a JPEG/PNG frame as-is (preferred; no base64 cost);
* ``text`` messages - a small JSON envelope
  ``{"type": "frame", "data": "<base64>", "t": 12.3}`` (fallback for clients
  that cannot send binary frames).

The browser sends frames at a capped rate; the server processes them as they
arrive (``SourceFrameCamera.read`` returns the newest frame, so a slow consumer
never queues stale video).

Privacy: frames are processed in memory. Only when "record" is on does the
server keep a local copy (the same AVI + sync CSV the local pathway writes), and
it never leaves that run directory.
"""

from __future__ import annotations

import base64
import threading
import time
from typing import Any

import cv2
import numpy as np

from .device import CMS50D
from .live import TARGET_FPS, LiveSession

# A browser frame larger than this is refused rather than decoded: it would be a
# multi-megapixel upload, not a 640x480 rPPG stream.
MAX_FRAME_BYTES = 4 * 1024 * 1024

# Accepted decodable magic bytes (JPEG / PNG). Anything else is rejected before
# the decoder sees it.
_JPEG_MAGIC = (b"\xff\xd8\xff",)
_PNG_MAGIC = (b"\x89PNG\r\n\x1a\n",)


class FrameDecodeError(ValueError):
    """The payload was not a usable uint8 colour image."""


def decode_frame(payload: bytes) -> np.ndarray:
    """Decode a JPEG/PNG byte string into a BGR frame.

    Raises ``FrameDecodeError`` with a user-facing message when the payload is
    empty, too large, not an image, or greyscale/alpha (out of scope: the rPPG
    pipeline expects three colour channels).
    """
    if not payload:
        raise FrameDecodeError("Empty frame payload.")
    if len(payload) > MAX_FRAME_BYTES:
        raise FrameDecodeError(
            f"Frame is too large ({len(payload)} bytes; limit {MAX_FRAME_BYTES}). "
            "Send a downscaled JPEG (e.g. 640x480) instead of a full-resolution one."
        )
    if not payload.startswith(_JPEG_MAGIC + _PNG_MAGIC):
        raise FrameDecodeError(
            "Frame is not JPEG or PNG data. Send an image, not raw pixels."
        )
    buffer = np.frombuffer(payload, dtype=np.uint8)
    frame = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if frame is None or frame.size == 0:
        raise FrameDecodeError("Frame could not be decoded as an image.")
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise FrameDecodeError("Frame must have three colour channels.")
    return frame


def decode_envelope(message: Any) -> bytes | None:
    """Extract frame bytes from a text message, or None if it is not a frame.

    Accepted shapes:
        {"type": "frame", "data": "<base64>"}
        {"type": "frame", "data_url": "data:image/jpeg;base64,..."}
        {"type": "frame", "jpeg": "<base64>"}
    """
    if not isinstance(message, dict) or message.get("type") != "frame":
        return None
    raw = message.get("data") or message.get("jpeg") or message.get("data_url")
    if not isinstance(raw, str) or not raw:
        return None
    if raw.startswith("data:"):
        _, _, raw = raw.partition(",")
    try:
        return base64.b64decode(raw, validate=False)
    except (ValueError, TypeError) as exc:
        raise FrameDecodeError(f"Frame payload is not valid base64: {exc}") from exc


class SourceFrameCamera:
    """Stands in for ``cv2.VideoCapture`` inside :class:`LiveSession`.

    ``LiveSession.open()`` does ``self.cap = cv2.VideoCapture(index)`` and
    ``process_frame`` calls ``self.cap.read()``. Supplying this object instead
    keeps every other line of the pipeline - and therefore the measurement -
    exactly as it is for a local camera.
    """

    def __init__(self, width: int | None = None, height: int | None = None,
                 fps: float | None = None) -> None:
        self._frame: np.ndarray | None = None
        self._seq = 0
        self._read_seq = 0
        self._closed = False
        self._lock = threading.Lock()
        self._first_frame = threading.Event()
        self._width = width
        self._height = height
        self._fps = fps
        self.received = 0
        self.dropped = 0

    # -- producer side (websocket) ---------------------------------------
    def push(self, frame: np.ndarray) -> None:
        """Store the newest frame. Older unread frames are dropped on purpose."""
        with self._lock:
            if self._closed:
                return
            if self._frame is not None and self._read_seq != self._seq:
                self.dropped += 1
            self._frame = frame
            self._seq += 1
            self.received += 1
        self._first_frame.set()

    def wait_for_first_frame(self, timeout: float = 15.0) -> bool:
        return self._first_frame.wait(timeout)

    # -- cv2.VideoCapture-compatible surface -----------------------------
    def isOpened(self) -> bool:  # noqa: N802 - OpenCV's spelling
        return not self._closed

    def set(self, prop: int, value: float) -> bool:  # noqa: N802
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            self._width = int(value)
        elif prop == cv2.CAP_PROP_FRAME_HEIGHT:
            self._height = int(value)
        elif prop == cv2.CAP_PROP_FPS:
            self._fps = float(value)
        return True

    def get(self, prop: int) -> float:  # noqa: N802
        with self._lock:
            frame = self._frame
        if prop == cv2.CAP_PROP_FRAME_WIDTH and frame is not None:
            return float(frame.shape[1])
        if prop == cv2.CAP_PROP_FRAME_HEIGHT and frame is not None:
            return float(frame.shape[0])
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return float(self._width or 0)
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return float(self._height or 0)
        if prop == cv2.CAP_PROP_FPS:
            return float(self._fps or 0)
        return 0.0

    def read(self) -> tuple[bool, np.ndarray | None]:
        """Return the newest frame (and mark it read), like a camera would."""
        with self._lock:
            if self._frame is None:
                return False, None
            frame = self._frame
            self._read_seq = self._seq
            return True, frame

    def release(self) -> None:
        with self._lock:
            self._closed = True
            self._frame = None

    # -- diagnostics -----------------------------------------------------
    @staticmethod
    def is_remote() -> bool:
        return True


class RemoteLiveSession(LiveSession):
    """A :class:`LiveSession` whose camera is the browser's, not the host's."""

    def __init__(self, *args, source: SourceFrameCamera | None = None, **kwargs):
        self._source = source or SourceFrameCamera()
        self._camera_ready = False
        super().__init__(*args, **kwargs)

    @property
    def source(self) -> SourceFrameCamera:
        return self._source

    def open(self):  # noqa: D401 - inherits the contract from LiveSession.open
        """Same as ``LiveSession.open`` but without touching host hardware.

        Deliberately does not call ``super().open()``: that would open
        ``cv2.VideoCapture(camera_index)`` on the server (the bug being fixed).
        Everything else it does - video writer, sync CSV, CMS50D oximeter - is
        reproduced here unchanged.
        """
        if not self._source.wait_for_first_frame(timeout=15.0):
            raise RuntimeError(
                "No camera frames arrived from the browser within 15 s. Grant the "
                "camera permission prompt on this device and press Start again."
            )

        frame = self._source.read()[1]
        width = int(frame.shape[1]) if frame is not None else int(self._source.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(frame.shape[0]) if frame is not None else int(self._source.get(cv2.CAP_PROP_FRAME_HEIGHT))

        # The camera read step is the only behavioural difference; undo the
        # "host camera" bookkeeping from the parent so nothing tries to open it.
        self.cap = self._source
        self._camera_ready = True

        if self.record_path:
            fourcc = cv2.VideoWriter_fourcc(*"XVID")
            self.writer = cv2.VideoWriter(
                str(self.record_path), fourcc, float(self.source_fps), (width, height)
            )
            self._open_csv()

        if self.serial_port:
            try:
                self.monitor = CMS50D(port=self.serial_port)
                self.monitor.connect()
                self.monitor.start_live_acquisition()
                self.cms_connected = True
                self.cms_streaming = self._wait_for_first_packet(timeout=3.0)
                if not self.cms_streaming:
                    self.cms_error = (
                        f"Port {self.serial_port} opened but no data was received. "
                        "Check the CMS50D is powered on, the finger probe is "
                        "inserted, and this is the correct port."
                    )
            except Exception as exc:  # oximeter optional; degrade gracefully
                self.monitor = None
                self.cms_connected = False
                self.cms_streaming = False
                self.cms_error = f"Could not open {self.serial_port}: {exc}"

        self.start_time = time.time()
        return self

    @property
    def source_fps(self) -> float:
        """Nominal frame rate for the recorded video.

        The browser paces frames at ~30 fps (the rate the pipeline is tuned
        for), but a phone may deliver less; the recorded AVI does not carry a
        timing table in this project either way, so the tuned value is used and
        the real rate is reported in the live state (``fps``).
        """
        return float(TARGET_FPS)

    def describe_source(self) -> dict:
        return {"kind": "browser", "received": self._source.received,
                "dropped": self._source.dropped}
