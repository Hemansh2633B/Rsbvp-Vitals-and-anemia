"""In-process backend exposing RSBVP's existing Python implementations.

This backend reuses — but never modifies — the algorithms shipped in
``gui/rppg_core`` (Green-channel, POS, CHROM). It exists so external
reference implementations and optional research tools can be benchmarked
against the exact code that ships in the main application, on identical
windows of identical recordings.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .base import BackendInfo, TraceBackend

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GUI_DIR = _REPO_ROOT / "gui"

NATIVE_BACKEND_VERSION = "1.0.0"


def _load_native():
    if str(_GUI_DIR) not in sys.path:
        sys.path.insert(0, str(_GUI_DIR))
    from rppg_core import pipeline as _pipeline  # noqa: WPS433
    from rppg_core import research as _research
    return _pipeline, _research


class NativeBackend(TraceBackend):
    name = "rsbvp_native"

    def info(self) -> BackendInfo:
        return BackendInfo(
            name=self.name,
            version=NATIVE_BACKEND_VERSION,
            backend_type="native-inprocess",
            license_id="MIT",
            source="gui/rppg_core (this repository)",
            integration="import (read-only)",
            notes="Reuses the shipped Green/POS/CHROM implementations; HR estimation is shared benchmark-side (hann-periodogram-v1) for cross-backend fairness.",
        )

    def available(self) -> tuple[bool, str]:
        try:
            _load_native()
        except Exception as exc:  # noqa: BLE001
            return False, f"gui/rppg_core is not importable: {exc}. Run 'cd gui && uv sync' or install numpy/scipy/opencv-python-headless."
        return True, ""

    def _transforms(self) -> dict:
        pipeline, research = _load_native()

        def green(rgb, fs, min_hz, max_hz):
            return rgb[:, 1].copy(), {"algorithm": "GREEN"}

        def pos(rgb, fs, min_hz, max_hz):
            return pipeline.pos_rppg(rgb, fs), {"algorithm": "POS"}

        def chrom(rgb, fs, min_hz, max_hz):
            waveform, _meta = research.chrom_rppg(rgb, fs, min_hz=min_hz, max_hz=max_hz)
            return waveform, {"algorithm": "CHROM"}

        return {"GREEN": green, "POS": pos, "CHROM": chrom}
