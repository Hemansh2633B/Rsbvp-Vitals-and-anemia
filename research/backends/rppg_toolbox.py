"""Optional subprocess adapter to the UbiComp Lab rPPG-Toolbox.

The toolbox (https://github.com/ubicomplab/rPPG-Toolbox, RAIL-1.1, pinned
commit ``b7500b848f84ad7f86e277b4612563b69f4f88f9``) is an *external* research
environment. Its source is never copied into this repository; this module only
generates explicit YAML configuration files, invokes ``python main.py
--config_file ...`` in a user-provided checkout, and records provenance.

Capabilities:

* unsupervised methods GREEN, ICA, CHROM, POS, LGI, PBV, OMIT (as shipped);
* neural ``only_test`` inference for DeepPhys / PhysNet / TS-CAN /
  EfficientPhys / PhysFormer — delegated here so checkpoint handling,
  preprocessing (Haar-cascade face crop, 1.5× box, per-model resize/FPS) and
  evaluation stay inside the toolbox exactly as published.

The toolbox prints aggregate metrics per method; it does not emit per-window
machine-readable predictions in ``unsupervised_method`` mode. Records produced
here are therefore ``backend_output_type="aggregate"`` (one record per method
per run, ``estimated_hr_bpm=None``) with the parsed metric lines preserved in
``backend_report``. Per-window comparison uses the in-process backends;
aggregate records are sanity anchors and are excluded from window-level
pairing statistics. Toolbox output provenance is only as good as the local
checkout — see docs/RESEARCH_BACKENDS.md and docs/OPEN_SOURCE_LICENSE_REGISTER.md.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .base import (
    BACKEND_RECORD_SCHEMA_VERSION,
    BackendError,
    BackendInfo,
    BackendRunResult,
    BackendUnavailable,
    ResearchBackend,
    configuration_hash,
)
from .schema import BenchmarkRecord

PINNED_COMMIT = "b7500b848f84ad7f86e277b4612563b69f4f88f9"
TOOLBOX_URL = "https://github.com/ubicomplab/rPPG-Toolbox"
TOOLBOX_LICENSE = "RAIL-1.1"
ADAPTER_VERSION = "1.0.0"

UNSUPERVISED_METHODS = ("GREEN", "ICA", "CHROM", "POS", "LGI", "PBV", "OMIT")
NEURAL_MODELS = ("DeepPhys", "PhysNet", "Tscan", "EfficientPhys", "PhysFormer")

_METRIC_LINE = re.compile(
    r"^\s*(?P<kind>FFT|PEAK)\s+(?P<metric>MAE|RMSE|MAPE|Pearson|SNR|MACC)\b[^:]*:\s*(?P<value>[-+0-9.eEnaN]+)"
)
_SECTION = re.compile(r"===Unsupervised Method \(\s*(?P<method>[A-Za-z0-9_-]+)\s*\) Predicting")


def _toolbox_path() -> Path | None:
    raw = os.environ.get("RSBVP_RPPG_TOOLBOX_PATH")
    return Path(raw).expanduser().resolve() if raw else None


def _toolbox_python() -> str:
    return os.environ.get("RSBVP_RPPG_TOOLBOX_PYTHON", "python3")


def _git_head(path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except Exception:  # noqa: BLE001
        return None
    head = result.stdout.strip()
    return head or None


def parse_toolbox_log(log_text: str) -> dict[str, dict[str, float]]:
    """Parse the toolbox's per-method aggregate metric lines from stdout."""
    metrics: dict[str, dict[str, float]] = {}
    current = "unknown"
    for line in log_text.splitlines():
        section = _SECTION.search(line)
        if section:
            current = section.group("method").upper()
            metrics.setdefault(current, {})
            continue
        match = _METRIC_LINE.match(line)
        if match:
            key = f"{match.group('kind').lower()}_{match.group('metric').lower()}"
            try:
                metrics.setdefault(current, {})[key] = float(match.group("value"))
            except ValueError:
                pass
    return metrics


def _write_unsupervised_config(
    output_dir: Path,
    *,
    dataset: str,
    data_path: str,
    cached_path: str,
    methods: list[str],
    fs: int,
    do_preprocess: bool,
    log_path: str,
) -> Path:
    method_list = ", ".join(f'"{m}"' for m in methods)
    config = f"""BASE: ['']
TOOLBOX_MODE: "unsupervised_method"
UNSUPERVISED:
  METHOD: [{method_list}]
  METRICS: ['MAE', 'RMSE', 'MAPE', 'Pearson', 'SNR', 'BA']
  DATA:
    FS: {int(fs)}
    DATASET: {dataset}
    DO_PREPROCESS: {'True' if do_preprocess else 'False'}
    DATA_FORMAT: NDHWC
    DATA_PATH: "{data_path}"
    CACHED_PATH: "{cached_path}"
    EXP_DATA_NAME: "rsbvp_adapter"
    BEGIN: 0.0
    END: 1.0
    PREPROCESS:
      DATA_TYPE: ['Raw']
      DATA_AUG: ['None']
      LABEL_TYPE: Raw
      DO_CHUNK: False
      CHUNK_LENGTH: 180
      CROP_FACE:
        DO_CROP_FACE: True
        BACKEND: 'HC'
        USE_LARGE_FACE_BOX: True
        LARGE_BOX_COEF: 1.5
        DETECTION:
          DO_DYNAMIC_DETECTION: False
          DYNAMIC_DETECTION_FREQUENCY : 30
          USE_MEDIAN_FACE_BOX: False
      RESIZE:
        H: 72
        W: 72
INFERENCE:
  EVALUATION_METHOD: "FFT"
  EVALUATION_WINDOW:
    USE_SMALLER_WINDOW: False
    WINDOW_SIZE: 10
LOG:
  PATH: {log_path}
"""
    target = output_dir / "rsbvp_unsupervised.yaml"
    target.write_text(config, encoding="utf-8")
    return target


class RppgToolboxBackend(ResearchBackend):
    name = "rppg_toolbox"

    def info(self) -> BackendInfo:
        path = _toolbox_path()
        head = _git_head(path) if path and (path / ".git").exists() else None
        return BackendInfo(
            name=self.name,
            version=f"toolbox@{PINNED_COMMIT[:12]}+adapter{ADAPTER_VERSION}",
            backend_type="external-subprocess",
            license_id=TOOLBOX_LICENSE,
            source=TOOLBOX_URL,
            pinned_commit=PINNED_COMMIT,
            integration="subprocess (python main.py --config_file); source not copied",
            notes=f"local checkout HEAD: {head or 'unverified (no .git)'}",
        )

    # ------------------------------------------------------------------
    def available(self) -> tuple[bool, str]:
        path = _toolbox_path()
        if path is None:
            return False, (
                "RSBVP_RPPG_TOOLBOX_PATH is not set. Clone https://github.com/ubicomplab/rPPG-Toolbox "
                f"at commit {PINNED_COMMIT}, create its own conda/uv environment (see its setup.sh), "
                "then export RSBVP_RPPG_TOOLBOX_PATH=/path/to/checkout and RSBVP_RPPG_TOOLBOX_PYTHON=/path/to/env/python."
            )
        if not path.is_dir():
            return False, f"RSBVP_RPPG_TOOLBOX_PATH is not a directory: {path}"
        if not (path / "main.py").is_file():
            return False, f"{path} does not look like an rPPG-Toolbox checkout (main.py missing)"
        if not (path / "requirements.txt").is_file():
            return False, f"{path} does not look like an rPPG-Toolbox checkout (requirements.txt missing)"
        if (path / ".git").exists():
            head = _git_head(path)
            if head and not head.startswith(PINNED_COMMIT):
                return False, f"toolbox checkout is at {head[:12]}, expected pinned commit {PINNED_COMMIT[:12]}; check it out before running"
        return True, ""

    def supported_algorithms(self) -> list[str]:
        return list(UNSUPERVISED_METHODS) + list(NEURAL_MODELS)

    # ------------------------------------------------------------------
    def run(self, recording, algorithms=None, window_seconds=12.0, step_seconds=6.0,
            passband_hz=(0.7, 3.5), rois=None) -> BackendRunResult:
        raise BackendUnavailable(
            "recording-mode-not-supported",
            "The rPPG-Toolbox consumes toolbox-formatted video datasets, not RSBVP RGB traces. "
            "Use run_unsupervised_dataset(...) with a locally authorized dataset root.",
        )

    # ------------------------------------------------------------------
    def run_unsupervised_dataset(
        self,
        dataset_root: str | Path,
        *,
        dataset: str = "UBFC-rPPG",
        cached_path: str | Path,
        methods: list[str] | None = None,
        fs: int = 30,
        do_preprocess: bool = False,
        output_dir: str | Path = "runs/rsbvp_toolbox",
        timeout_s: int = 7200,
    ) -> BackendRunResult:
        usable, reason = self.available()
        if not usable:
            raise BackendUnavailable("toolbox-unavailable", reason)
        methods = [m.upper() for m in (methods or list(UNSUPERVISED_METHODS))]
        unknown = [m for m in methods if m not in UNSUPERVISED_METHODS]
        if unknown:
            raise BackendUnavailable("unsupported-unsupervised-method",
                                     f"unsupported: {', '.join(unknown)}; supported: {', '.join(UNSUPERVISED_METHODS)}")
        toolbox = _toolbox_path()
        assert toolbox is not None
        data_path = str(Path(dataset_root).expanduser().resolve())
        if not Path(data_path).is_dir():
            raise BackendUnavailable("dataset-root-missing", f"dataset root does not exist: {data_path}")
        cache = str(Path(cached_path).expanduser().resolve())
        Path(cache).mkdir(parents=True, exist_ok=True)
        out_dir = Path(output_dir).expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        log_path = out_dir / "runs"
        config_path = _write_unsupervised_config(
            out_dir, dataset=dataset, data_path=data_path, cached_path=cache,
            methods=methods, fs=fs, do_preprocess=do_preprocess, log_path=str(log_path),
        )
        config_payload = json.loads(json.dumps({
            "dataset": dataset, "data_path": data_path, "cached_path": cache,
            "methods": methods, "fs": fs, "do_preprocess": do_preprocess,
            "toolbox_commit": PINNED_COMMIT, "toolbox_mode": "unsupervised_method",
        }))
        config_hash = configuration_hash(config_payload)
        command = [_toolbox_python(), "main.py", "--config_file", str(config_path)]
        log_file = out_dir / "toolbox.log"
        try:
            completed = subprocess.run(
                command, cwd=str(toolbox), capture_output=True, text=True,
                timeout=timeout_s, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise BackendError(f"rPPG-Toolbox run timed out after {timeout_s}s; see partial log in {log_file}") from exc
        log_file.write_text((completed.stdout or "") + "\n--- STDERR ---\n" + (completed.stderr or ""),
                            encoding="utf-8")
        if completed.returncode != 0:
            tail = (completed.stderr or completed.stdout or "").strip().splitlines()[-20:]
            raise BackendError(
                f"rPPG-Toolbox exited with code {completed.returncode}. Tail of log:\n" + "\n".join(tail)
            )
        parsed = parse_toolbox_log(completed.stdout or "")
        info = self.info()
        records = []
        for method in methods:
            metrics = parsed.get(method, {})
            records.append(BenchmarkRecord(
                recording_id=f"{dataset}:aggregate",
                timestamp_s=0.0,
                algorithm=method,
                roi="whole_video",
                pulse_signal=None,
                estimated_hr_bpm=None,
                signal_quality="aggregate",
                sampling_rate_hz=float(fs),
                backend=info.name,
                backend_version=info.version,
                model_checkpoint=None,
                configuration_hash=config_hash,
                backend_output_type="aggregate",
                backend_report={
                    "dataset": dataset,
                    "parsed_metrics": metrics,
                    "log_file": str(log_file),
                    "config_file": str(config_path),
                    "evaluation": "toolbox aggregate over all videos; per-window predictions are not emitted by the toolbox in unsupervised mode",
                },
            ))
        return BackendRunResult(
            backend=info,
            records=records,
            latency_s={},
            warnings=([] if parsed else ["no metric lines could be parsed from the toolbox log; inspect toolbox.log"]),
            configuration_hash=config_hash,
        )
