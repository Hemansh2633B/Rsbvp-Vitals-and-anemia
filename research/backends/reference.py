"""In-process backend with independent RSBVP reference implementations.

Implements GREEN, ICA, CHROM, POS and a trace-domain PBV approximation
directly from the published algorithms (see reference_methods.py). LGI and
OMIT are video-domain methods and are reported unsupported here by design.
"""
from __future__ import annotations

from . import reference_methods
from .base import BackendInfo, TraceBackend, UnsupportedAlgorithm, check_algorithms

REFERENCE_BACKEND_VERSION = "1.0.0"


class ReferenceBackend(TraceBackend):
    name = "rsbvp_reference"

    def info(self) -> BackendInfo:
        return BackendInfo(
            name=self.name,
            version=REFERENCE_BACKEND_VERSION,
            backend_type="reference-inprocess",
            license_id="MIT",
            source="research/backends/reference_methods.py (this repository)",
            integration="import",
            notes="Independent trace-domain implementations from the published algorithms; not bit-exact ports of rPPG-Toolbox/pyVHR. PBV is a signature-gated chrominance approximation.",
        )

    def available(self) -> tuple[bool, str]:
        return True, ""

    def _transforms(self) -> dict:
        return dict(reference_methods.METHODS)

    def supported_algorithms(self):
        return sorted(set(reference_methods.METHODS) | set(reference_methods.TRACE_ONLY_UNSUPPORTED))

    def run(self, recording, algorithms=None, window_seconds=12.0, step_seconds=6.0,
            passband_hz=(0.7, 3.5), rois=None):
        if algorithms is not None:
            requested = [str(a).upper() for a in algorithms]
            blocked = [a for a in requested if a in reference_methods.TRACE_ONLY_UNSUPPORTED]
            if blocked:
                reasons = "; ".join(f"{a}: {reference_methods.TRACE_ONLY_UNSUPPORTED[a]}" for a in blocked)
                raise UnsupportedAlgorithm(reasons)
            algorithms = requested
        return super().run(recording, algorithms=algorithms, window_seconds=window_seconds,
                           step_seconds=step_seconds, passband_hz=passband_hz, rois=rois)
