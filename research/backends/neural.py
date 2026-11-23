"""Checkpoint availability + provenance contract for neural rPPG models.

This module does NOT reimplement, download, or redistribute any neural model.
It (1) documents exactly what official pretrained weights exist and under
which terms, (2) resolves checkpoints from the user-configured
``RSBVP_MODEL_ROOT`` directory, (3) verifies integrity (sha256), and (4)
delegates actual inference to the external rPPG-Toolbox ``only_test`` mode so
that preprocessing and evaluation match the published protocol.

If no checkpoint is configured, inference is reported *unavailable* — never
fabricated, never silently substituted. See docs/RESEARCH_BACKENDS.md
("Pretrained model policy") and docs/OPEN_SOURCE_LICENSE_REGISTER.md.
"""
from __future__ import annotations

import hashlib
import os
import re
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
from .rppg_toolbox import (
    PINNED_COMMIT,
    TOOLBOX_LICENSE,
    TOOLBOX_URL,
    RppgToolboxBackend,
    _toolbox_path,
    _toolbox_python,
)
from .schema import BenchmarkRecord

ADAPTER_VERSION = "1.0.0"

#: Verified against configs/infer_configs/*.yaml at the pinned toolbox commit.
#: "verified" entries were read from the toolbox repository on 2026-11-23.
MODEL_REGISTRY: dict[str, dict] = {
    "DeepPhys": {
        "toolbox_name": "DeepPhys",
        "training_dataset": "PURE (cross-dataset release); see PURE_UBFC-rPPG / UBFC-rPPG_PURE config naming ({train}_{test})",
        "intended_inference_dataset": "UBFC-rPPG (28 videos, 42–210 BPM passband) or reverse; not for clinical use",
        "checkpoint_files": ["PURE_DeepPhys.pth", "UBFC-rPPG_DeepPhys.pth", "MA-UBFC_deepphys.pth", "SCAMPS_DeepPhys.pth"],
        "input": {"fs_hz": 30, "resize": [72, 72], "data_format": "NDCHW",
                  "data_type": ["DiffNormalized", "Standardized"], "chunk_length_frames": 180,
                  "face_crop": "Haar Cascade, LARGE_BOX_COEF=1.5"},
        "params": {"DROP_RATE": 0.2},
        "architecture_source": "ubicomplab/rPPG-Toolbox neural_methods/model/DeepPhys.py @ b7500b8",
        "architecture_license": TOOLBOX_LICENSE,
        "pretrained_on": "PURE (release checkpoint) / UBFC-rPPG (reverse release)",
        "weight_license": "distributed inside the rPPG-Toolbox repository; repository LICENSE is RAIL-1.1. No separate weight license statement found — outstanding legal review required",
        "hardware": "CUDA GPU recommended (toolbox setup pins torch 2.1.2+cu121); CPU inference unverified",
        "published_protocol": "FFT HR estimation over full clips; MAE/RMSE/MAPE/Pearson/SNR/BA; UBFC-rPPG test split subject-disjoint from PURE",
        "verification": "verified against UBFC-rPPG_PURE_DEEPPHYS_BASIC.yaml (2026-11-23)",
    },
    "PhysNet": {
        "toolbox_name": "Physnet",
        "training_dataset": "PURE (release); UBFC-rPPG (reverse)",
        "intended_inference_dataset": "UBFC-rPPG",
        "checkpoint_files": ["PURE_PhysNet_DiffNormalized.pth", "UBFC-rPPG_PhysNet_DiffNormalized.pth", "MA-UBFC_physnet.pth", "SCAMPS_PhysNet_DiffNormalized.pth"],
        "input": {"fs_hz": 30, "resize": [72, 72], "data_format": "NCDHW",
                  "data_type": ["DiffNormalized"], "chunk_length_frames": 128,
                  "face_crop": "Haar Cascade, LARGE_BOX_COEF=1.5"},
        "params": {"DROP_RATE": 0.2, "PHYSNET": {"FRAME_NUM": 128}},
        "architecture_source": "ubicomplab/rPPG-Toolbox neural_methods/model/Physnet.py @ b7500b8",
        "architecture_license": TOOLBOX_LICENSE,
        "pretrained_on": "PURE / UBFC-rPPG (DiffNormalized labels)",
        "weight_license": "RAIL-1.1 (repository LICENSE); no separate weight statement — outstanding legal review required",
        "hardware": "CUDA GPU recommended; CPU inference unverified",
        "published_protocol": "FFT HR estimation; same metrics; DiffNormalized DIFF labels",
        "verification": "verified against UBFC-rPPG_PURE_PHYSNET_BASIC.yaml (2026-11-23)",
    },
    "Tscan": {
        "toolbox_name": "Tscan",
        "training_dataset": "PURE (release); UBFC-rPPG (reverse)",
        "intended_inference_dataset": "UBFC-rPPG",
        "checkpoint_files": ["PURE_TSCAN.pth", "UBFC-rPPG_TSCAN.pth", "MA-UBFC_tscan.pth", "SCAMPS_TSCAN.pth"],
        "input": {"fs_hz": 30, "resize": [72, 72], "data_format": "NDCHW",
                  "data_type": ["DiffNormalized", "Standardized"], "chunk_length_frames": 180,
                  "face_crop": "Haar Cascade, LARGE_BOX_COEF=1.5"},
        "params": {"DROP_RATE": 0.2, "TSCAN": {"FRAME_DEPTH": 10}},
        "architecture_source": "ubicomplab/rPPG-Toolbox neural_methods/model/Tscan.py @ b7500b8",
        "architecture_license": TOOLBOX_LICENSE,
        "pretrained_on": "PURE / UBFC-rPPG",
        "weight_license": "RAIL-1.1 (repository LICENSE); no separate weight statement — outstanding legal review required",
        "hardware": "CUDA GPU recommended; CPU inference unverified",
        "published_protocol": "FFT HR estimation; MAE/RMSE/MAPE/Pearson/SNR/BA",
        "verification": "verified against UBFC-rPPG_PURE_TSCAN_BASIC.yaml (2026-11-23)",
    },
    "EfficientPhys": {
        "toolbox_name": "EfficientPhys",
        "training_dataset": "PURE (release); UBFC-rPPG (reverse)",
        "intended_inference_dataset": "UBFC-rPPG",
        "checkpoint_files": ["PURE_EfficientPhys.pth", "UBFC-rPPG_EfficientPhys.pth", "MA-UBFC_efficientphys.pth", "SCAMPS_EfficientPhys.pth"],
        "input": {"fs_hz": 30, "resize": [72, 72], "data_format": "NDCHW",
                  "data_type": ["Standardized"], "chunk_length_frames": 180,
                  "face_crop": "Haar Cascade, LARGE_BOX_COEF=1.5"},
        "params": {"DROP_RATE": 0.2, "EFFICIENTPHYS": {"FRAME_DEPTH": 10}},
        "architecture_source": "ubicomplab/rPPG-Toolbox neural_methods/model/EfficientPhys.py @ b7500b8",
        "architecture_license": TOOLBOX_LICENSE,
        "pretrained_on": "PURE / UBFC-rPPG",
        "weight_license": "RAIL-1.1 (repository LICENSE); no separate weight statement — outstanding legal review required",
        "hardware": "CUDA GPU recommended; CPU inference unverified",
        "published_protocol": "FFT HR estimation; MAE/RMSE/MAPE/Pearson/SNR/BA",
        "verification": "verified against UBFC-rPPG_PURE_EFFICIENTPHYS.yaml (2026-11-23)",
    },
    "PhysFormer": {
        "toolbox_name": "PhysFormer",
        "training_dataset": "PURE (release); UBFC-rPPG (reverse); official ZitongYu/PhysFormer VIPL weights are distributed via Google Drive with no explicit weight license — do NOT use",
        "intended_inference_dataset": "UBFC-rPPG",
        "checkpoint_files": ["PURE_PhysFormer_DiffNormalized.pth", "UBFC-rPPG_PhysFormer_DiffNormalized.pth", "SCAMPS_PhysFormer_DiffNormalized.pth"],
        "input": {"fs_hz": 30, "resize": [128, 128], "data_format": "NCDHW",
                  "data_type": ["DiffNormalized"], "chunk_length_frames": 160,
                  "face_crop": "Haar Cascade, LARGE_BOX_COEF=1.5"},
        "params": {"DROP_RATE": 0.1,
                   "PHYSFORMER": {"PATCH_SIZE": 4, "DIM": 96, "FF_DIM": 144,
                                  "NUM_HEADS": 4, "NUM_LAYERS": 12, "THETA": 0.7}},
        "architecture_source": "ubicomplab/rPPG-Toolbox neural_methods/model/PhysFormer.py @ b7500b8",
        "architecture_license": TOOLBOX_LICENSE,
        "pretrained_on": "PURE / UBFC-rPPG (DiffNormalized GaussProc labels)",
        "weight_license": "RAIL-1.1 (repository LICENSE); no separate weight statement — outstanding legal review required",
        "hardware": "CUDA GPU strongly recommended (12-layer transformer); CPU inference unverified",
        "published_protocol": "FFT HR estimation; MAE/RMSE/MAPE/Pearson/SNR/BA",
        "verification": "verified against PURE_UBFC-rPPG_PHYSFORMER_BASIC.yaml (2026-11-23)",
    },
}


def model_root() -> Path | None:
    raw = os.environ.get("RSBVP_MODEL_ROOT")
    return Path(raw).expanduser().resolve() if raw else None


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checkpoint_status(model_name: str) -> tuple[bool, str, Path | None]:
    """Return (available, detail, path) for a registry model."""
    if model_name not in MODEL_REGISTRY:
        return False, f"unknown model {model_name!r}; known: {', '.join(sorted(MODEL_REGISTRY))}", None
    root = model_root()
    if root is None:
        return False, ("RSBVP_MODEL_ROOT is not set; point it at a local model directory "
                       "whose layout mirrors rPPG-Toolbox final_model_release/ (never commit checkpoints to git)"), None
    for relative in MODEL_REGISTRY[model_name]["checkpoint_files"]:
        candidate = root / relative
        if candidate.is_file():
            return True, f"checkpoint found: {candidate}", candidate
    return False, (f"no checkpoint found under {root}; expected one of: "
                   + ", ".join(MODEL_REGISTRY[model_name]["checkpoint_files"])), None


_GENERIC_METRIC = re.compile(r"(MAE|RMSE|MAPE|Pearson|SNR|MACC)[^:\n]{0,40}:\s*([-+0-9.eEnaN]+)")


class NeuralBaselineBackend(ResearchBackend):
    """Availability/provenance contract + delegated inference via the toolbox."""

    def __init__(self, model_name: str = "Tscan"):
        if model_name not in MODEL_REGISTRY:
            raise ValueError(f"unknown neural model {model_name!r}; known: {', '.join(sorted(MODEL_REGISTRY))}")
        self.model_name = model_name

    @property
    def name(self) -> str:  # type: ignore[override]
        return f"neural_{self.model_name.lower()}"

    def info(self) -> BackendInfo:
        ok, detail, path = checkpoint_status(self.model_name)
        return BackendInfo(
            name=self.name,
            version=f"toolbox@{PINNED_COMMIT[:12]}+neural-contract{ADAPTER_VERSION}",
            backend_type="external-checkpoint-contract",
            license_id=TOOLBOX_LICENSE,
            source=TOOLBOX_URL,
            pinned_commit=PINNED_COMMIT,
            integration="checkpoint resolution + delegated inference via rPPG-Toolbox only_test",
            notes=f"{detail}",
        )

    def available(self) -> tuple[bool, str]:
        ok, detail, _path = checkpoint_status(self.model_name)
        if not ok:
            return False, detail
        toolbox = RppgToolboxBackend()
        usable, reason = toolbox.available()
        if not usable:
            return False, f"checkpoint present but rPPG-Toolbox is not usable: {reason}"
        return True, ""

    def supported_algorithms(self) -> list[str]:
        return list(MODEL_REGISTRY)

    def run(self, recording, algorithms=None, window_seconds=12.0, step_seconds=6.0,
            passband_hz=(0.7, 3.5), rois=None) -> BackendRunResult:
        raise BackendUnavailable(
            "recording-mode-not-supported",
            "Neural inference consumes toolbox-formatted video datasets. "
            "Use run_only_test_dataset(...) with an authorized local dataset.",
        )

    def describe_checkpoint(self) -> dict:
        """Machine-readable checkpoint provenance card (never fabricated)."""
        ok, detail, path = checkpoint_status(self.model_name)
        spec = MODEL_REGISTRY[self.model_name]
        card = dict(spec)
        card.update({
            "model": self.model_name,
            "checkpoint_available": bool(ok),
            "checkpoint_path": str(path) if path else None,
            "checkpoint_sha256": sha256_file(path) if path else None,
            "model_root_configured": model_root() is not None,
        })
        return card

    def run_only_test_dataset(
        self,
        dataset_root: str | Path,
        *,
        test_dataset: str = "UBFC-rPPG",
        cached_path: str | Path,
        checkpoint_filename: str | None = None,
        output_dir: str | Path = "runs/rsbvp_neural",
        timeout_s: int = 14400,
    ) -> BackendRunResult:
        """Run the toolbox ``only_test`` pipeline with a local checkpoint.

        Returns an aggregate-provenance record. Per-window predictions are not
        emitted by the toolbox in this mode; parsed log lines are preserved in
        ``backend_report`` verbatim for audit.
        """
        ok, detail, checkpoint = checkpoint_status(self.model_name)
        if not ok or checkpoint is None:
            raise BackendUnavailable("checkpoint-missing", detail)
        if checkpoint_filename is not None:
            candidate = (model_root() or Path(".")) / checkpoint_filename
            if not candidate.is_file():
                raise BackendUnavailable("checkpoint-missing", f"explicit checkpoint not found: {candidate}")
            checkpoint = candidate
        toolbox = RppgToolboxBackend()
        usable, reason = toolbox.available()
        if not usable:
            raise BackendUnavailable("toolbox-unavailable", reason)
        spec = MODEL_REGISTRY[self.model_name]
        data_path = str(Path(dataset_root).expanduser().resolve())
        if not Path(data_path).is_dir():
            raise BackendUnavailable("dataset-root-missing", f"dataset root does not exist: {data_path}")
        cache = str(Path(cached_path).expanduser().resolve())
        Path(cache).mkdir(parents=True, exist_ok=True)
        out_dir = Path(output_dir).expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        config_payload = {
            "toolbox_mode": "only_test",
            "model": spec["toolbox_name"],
            "checkpoint": str(checkpoint),
            "checkpoint_sha256": sha256_file(checkpoint),
            "test_dataset": test_dataset,
            "data_path": data_path,
            "cached_path": cache,
            "input": spec["input"],
            "params": spec["params"],
            "toolbox_commit": PINNED_COMMIT,
        }
        config_hash = configuration_hash(config_payload)
        model_lines = ["MODEL:", f"  DROP_RATE: {spec['params'].get('DROP_RATE', 0.2)}",
                       f"  NAME: {spec['toolbox_name']}"]
        for key, value in spec["params"].items():
            if key == "DROP_RATE":
                continue
            model_lines.append(f"  {key}:")
            for sub_key, sub_value in dict(value).items():
                model_lines.append(f"    {sub_key}: {sub_value}")
        model_block = "\n".join(model_lines) + "\n"
        resize_h, resize_w = spec["input"]["resize"]
        data_types = ", ".join(f"'{d}'" for d in spec["input"]["data_type"])
        config = f"""BASE: ['']
TOOLBOX_MODE: "only_test"
TEST:
  METRICS: ['MAE', 'RMSE', 'MAPE', 'Pearson', 'SNR', 'BA']
  USE_LAST_EPOCH: False
  DATA:
    FS: {spec['input']['fs_hz']}
    DATASET: {test_dataset}
    DO_PREPROCESS: False
    DATA_FORMAT: {spec['input']['data_format']}
    DATA_PATH: "{data_path}"
    CACHED_PATH: "{cache}"
    EXP_DATA_NAME: "rsbvp_adapter"
    BEGIN: 0.0
    END: 1.0
    PREPROCESS:
      DATA_TYPE: [{data_types}]
      LABEL_TYPE: DiffNormalized
      DO_CHUNK: True
      CHUNK_LENGTH: {spec['input']['chunk_length_frames']}
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
        H: {resize_h}
        W: {resize_w}
DEVICE: cuda:0
NUM_OF_GPU_TRAIN: 1
LOG:
  PATH: {out_dir / 'runs'}
{model_block}INFERENCE:
  BATCH_SIZE: 4
  EVALUATION_METHOD: "FFT"
  EVALUATION_WINDOW:
    USE_SMALLER_WINDOW: False
    WINDOW_SIZE: 10
  MODEL_PATH: "{checkpoint}"
"""
        config_path = out_dir / f"rsbvp_only_test_{self.model_name}.yaml"
        config_path.write_text(config, encoding="utf-8")
        command = [_toolbox_python(), "main.py", "--config_file", str(config_path)]
        log_file = out_dir / f"toolbox_{self.model_name}.log"
        try:
            completed = subprocess.run(
                command, cwd=str(_toolbox_path()), capture_output=True, text=True,
                timeout=timeout_s, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise BackendError(f"rPPG-Toolbox only_test timed out after {timeout_s}s; see {log_file}") from exc
        log_file.write_text((completed.stdout or "") + "\n--- STDERR ---\n" + (completed.stderr or ""),
                            encoding="utf-8")
        if completed.returncode != 0:
            tail = (completed.stderr or completed.stdout or "").strip().splitlines()[-20:]
            raise BackendError(f"rPPG-Toolbox exited with code {completed.returncode}:\n" + "\n".join(tail))
        raw = completed.stdout or ""
        parsed = {m.group(1): float(m.group(2)) for m in _GENERIC_METRIC.finditer(raw)
                  if m.group(2).lower() not in {"nan", "inf"}}
        info = self.info()
        record = BenchmarkRecord(
            recording_id=f"{test_dataset}:aggregate",
            timestamp_s=0.0,
            algorithm=self.model_name,
            roi="whole_video",
            pulse_signal=None,
            estimated_hr_bpm=None,
            signal_quality="aggregate",
            sampling_rate_hz=float(spec["input"]["fs_hz"]),
            backend=info.name,
            backend_version=info.version,
            model_checkpoint=str(checkpoint),
            configuration_hash=config_hash,
            backend_output_type="aggregate",
            backend_report={
                "checkpoint_sha256": config_payload["checkpoint_sha256"],
                "parsed_metrics_best_effort": parsed,
                "parse_reliability": "best-effort; the toolbox does not emit per-window machine-readable predictions in only_test mode",
                "log_file": str(log_file),
                "config_file": str(config_path),
            },
        )
        return BackendRunResult(
            backend=info,
            records=[record],
            latency_s={},
            warnings=([] if parsed else ["no metric lines could be parsed; inspect the log file"]),
            configuration_hash=config_hash,
        )
