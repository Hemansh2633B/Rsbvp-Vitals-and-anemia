"""Optional subprocess adapter to pyVHR (GPL-3.0).

pyVHR (https://github.com/phuselab/pyVHR, GPL-3.0) is an *external, optional*
research environment. NO pyVHR source code is copied into this repository —
this module only launches a driver script (``pyvhr_driver.py``, written for
RSBVP and licensed MIT) inside the user's separate pyVHR installation and
converts its JSON-lines output into standardized records.

Isolation contract:

* install pyVHR into its own environment (conda ``pyvhr`` env per upstream,
  or the CPU-only ``pyvhr_CPU`` branch / ``pyvhr-cpu`` package);
* set ``RSBVP_PYVHR_PYTHON`` to that environment's interpreter;
* set ``RSBVP_PYVHR_PATH`` to the checkout (needed to locate the driver);
* the main RSBVP application never imports ``pyVHR``.

Method naming differs between builds (CPU builds prefix ``cpu_``); pass the
exact method string via ``methods=`` or ``--pyvhr-method``. Defaults target
the current 2.0 (GPU) build: Green/POS/CHROM/ICA/LGI/PBV/OMIT/SSR/PCA.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .base import (
    BackendError,
    BackendInfo,
    BackendRunResult,
    BackendUnavailable,
    ResearchBackend,
    configuration_hash,
)
from .schema import BenchmarkRecord
import math

PINNED_MASTER_COMMIT = "a6270f04a97f05a13d145dd0a5e8c8df48d8bd62"  # 2024-11-20, v2.0 line
PINNED_CPU_BRANCH_COMMIT = "e39ae5fa30c84c77300d43da5e3b8037fc852a9e"  # 2022-04-28 (pyVHR_CPU branch, v1.2 line)
PYVHR_URL = "https://github.com/phuselab/pyVHR"
PYVHR_LICENSE = "GPL-3.0"
ADAPTER_VERSION = "1.0.0"

# Methods exposed by pyVHR 2.0 (GPU) master. CPU builds use the cpu_ prefix;
# the driver forwards the string verbatim so both work.
PYVHR_METHODS = ("Green", "POS", "CHROM", "ICA", "PCA", "SSR", "LGI", "PBV", "OMIT", "MTTS-CAN")


def _pyvhr_python() -> str | None:
    return os.environ.get("RSBVP_PYVHR_PYTHON")


def _pyvhr_path() -> Path | None:
    raw = os.environ.get("RSBVP_PYVHR_PATH")
    return Path(raw).expanduser().resolve() if raw else None


def _driver_path() -> Path:
    return Path(__file__).resolve().parent / "pyvhr_driver.py"


def parse_driver_output(text: str) -> list[dict]:
    records: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("type") == "window":
            records.append(payload)
    return records


class PyVHRBackend(ResearchBackend):
    name = "pyvhr"

    def info(self) -> BackendInfo:
        return BackendInfo(
            name=self.name,
            version=f"pyvhr@master-{PINNED_MASTER_COMMIT[:12]}+adapter{ADAPTER_VERSION}",
            backend_type="external-subprocess",
            license_id=PYVHR_LICENSE,
            source=PYVHR_URL,
            pinned_commit=PINNED_MASTER_COMMIT,
            integration="subprocess driver (research/backends/pyvhr_driver.py); source not copied",
            notes=f"CPU-only line pins branch pyVHR_CPU @ {PINNED_CPU_BRANCH_COMMIT[:12]} (pyvhr-cpu 1.0.2 on PyPI)",
        )

    def available(self) -> tuple[bool, str]:
        python = _pyvhr_python()
        if not python:
            return False, (
                "RSBVP_PYVHR_PYTHON is not set. Create a separate pyVHR environment "
                "(conda per upstream README, or the CPU-only pyvhr-cpu package) and point "
                "RSBVP_PYVHR_PYTHON at its interpreter. GPL-3.0 code stays out of this repository."
            )
        path = _pyvhr_path()
        if path is not None and not path.is_dir():
            return False, f"RSBVP_PYVHR_PATH is not a directory: {path}"
        try:
            probe = subprocess.run(
                [python, "-c", "import pyVHR; print(getattr(pyVHR, '__version__', 'unknown'))"],
                capture_output=True, text=True, timeout=60, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"RSBVP_PYVHR_PYTHON cannot execute: {exc}"
        if probe.returncode != 0:
            detail = (probe.stderr or probe.stdout or "").strip().splitlines()[-1:] or ["unknown error"]
            return False, f"pyVHR is not importable in {python}: {detail[0]}"
        return True, ""

    def supported_algorithms(self) -> list[str]:
        return list(PYVHR_METHODS)

    def run(self, recording, algorithms=None, window_seconds=12.0, step_seconds=6.0,
            passband_hz=(0.7, 3.5), rois=None) -> BackendRunResult:
        raise BackendUnavailable(
            "video-mode-required",
            "pyVHR consumes video files (it performs its own face detection, ROI tracking and patches). "
            "Use run_on_videos(...) with authorized local videos instead of RGB trace input.",
        )

    def run_on_videos(
        self,
        videos: list[tuple[str, str | Path]],
        *,
        methods: list[str] | None = None,
        winsize_s: float = 6.0,
        roi_approach: str = "patches",
        cuda: bool = False,
        output_dir: str | Path = "runs/rsbvp_pyvhr",
        timeout_s: int = 7200,
    ) -> BackendRunResult:
        """Run pyVHR over (recording_id, video_path) pairs; emit window records."""
        usable, reason = self.available()
        if not usable:
            raise BackendUnavailable("pyvhr-unavailable", reason)
        methods = methods or ["CHROM", "POS", "Green", "ICA"]
        for video_id, video_path in videos:
            if not Path(video_path).is_file():
                raise BackendUnavailable("video-missing", f"{video_id}: {video_path} does not exist")
        out_dir = Path(output_dir).expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest = out_dir / "driver_manifest.json"
        manifest.write_text(json.dumps([{"recording_id": rid, "video_path": str(Path(p).resolve())}
                                         for rid, p in videos]), encoding="utf-8")
        config_hash = configuration_hash({
            "backend": self.name, "methods": methods, "winsize_s": winsize_s,
            "roi_approach": roi_approach, "cuda": bool(cuda),
            "pinned_master_commit": PINNED_MASTER_COMMIT, "pinned_cpu_commit": PINNED_CPU_BRANCH_COMMIT,
        })
        command = [_pyvhr_python() or "python3", str(_driver_path()),
                   "--manifest", str(manifest),
                   "--methods", *methods,
                   "--winsize", str(winsize_s),
                   "--roi-approach", roi_approach,
                   "--cuda", "true" if cuda else "false"]
        log_file = out_dir / "pyvhr_driver.log"
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout_s, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise BackendError(f"pyVHR driver timed out after {timeout_s}s; see {log_file}") from exc
        log_file.write_text((completed.stdout or "") + "\n--- STDERR ---\n" + (completed.stderr or ""),
                            encoding="utf-8")
        if completed.returncode != 0:
            tail = (completed.stderr or completed.stdout or "").strip().splitlines()[-20:]
            raise BackendError(f"pyVHR driver exited with code {completed.returncode}:\n" + "\n".join(tail))
        info = self.info()
        version = f"{info.version}"
        records: list[BenchmarkRecord] = []
        for payload in parse_driver_output(completed.stdout or ""):
            timestamp = float(payload.get("timestamp_s", 0.0))
            fps = payload.get("sampling_rate_hz")
            bpm = payload.get("estimated_hr_bpm")
            bpm = float(bpm) if bpm is not None and math.isfinite(float(bpm)) else None
            records.append(BenchmarkRecord(
                recording_id=str(payload.get("recording_id", "unknown")),
                timestamp_s=timestamp,
                algorithm=str(payload.get("algorithm", "UNKNOWN")),
                roi=str(payload.get("roi", "patches")),
                pulse_signal=None,  # driver does not export raw BVP arrays; documented limitation
                estimated_hr_bpm=bpm,
                signal_quality="ok" if bpm is not None else "unavailable:no_estimate",
                sampling_rate_hz=float(fps) if fps else None,
                backend=info.name,
                backend_version=version,
                model_checkpoint=("pyVHR-MTTS-CAN" if str(payload.get("algorithm", "")).upper() == "MTTS-CAN" else None),
                configuration_hash=config_hash,
                window_end_s=float(payload["window_end_s"]) if payload.get("window_end_s") is not None else None,
                backend_output_type="window",
                backend_report={"driver_record": payload},
            ))
        return BackendRunResult(
            backend=info,
            records=records,
            latency_s={},
            warnings=([] if records else ["pyVHR produced no window records; inspect pyvhr_driver.log"]),
            configuration_hash=config_hash,
        )
