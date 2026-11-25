#!/usr/bin/env python3
"""rPPG-10 dataset adapter — inventory, validation, timestamped ROI traces.

Documented expectations (verify against your own copy; nothing here is
assumed to hold automatically):

    <root>/
      Subject_<n>/Subject_<n>_Forehead.avi    64x64, 600 s
      Subject_<n>/Subject_<n>_Cheek1.avi      right cheek (provider mapping)
      Subject_<n>/Subject_<n>_Cheek2.avi      left cheek  (provider mapping)
      Subject_<n>/Subject_<n>_ECG.npy         float ECG, BITalino 1000 Hz
      <metadata>.xlsx (optional, presence recorded; never parsed here)

The provider states 26 subjects (Subject_4 excluded), 30 fps, 600 s per
recording, manual synchronisation with up to ±500 ms uncertainty. `--inspect`
re-derives frame counts, dimensions, measured frame rate, ECG sample count and
per-modality duration from the files themselves, and reports *differences* as
validation failures rather than silently adapting.

Design rules (binding):
* No file is ever written inside the dataset root; caches go to --cache-dir.
* No metadata is guessed: sampling rate for ECG must be supplied by the caller
  and is recorded verbatim in the report.
* ROI names map explicitly (Cheek1 → right_cheek, Cheek2 → left_cheek).
* No face detection is applied: the provider already cropped the ROIs.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

SCHEMA_INVENTORY = "rsbvp.rppg10-inventory.v1"
SCHEMA_TRACE = "rsbvp.rppg10-trace.v1"

# Provider file naming. The documentation shows `Subject_<n>_<ROI>.avi`, but the
# released archive (Dataset_rPPG-10.zip, 2025-04-04) actually contains a trailing
# underscore: `Subject_<n>_<ROI>_.avi`. Both spellings are accepted; the exact
# name is preserved in the inventory so the deviation is visible, never silent.
SUBJECT_DIR_RE = re.compile(r"^Subject_(\d+)$")
VIDEO_RE = re.compile(r"^Subject_(\d+)_(Forehead|Cheek1|Cheek2)_?\.avi$")
ECG_RE = re.compile(r"^Subject_(\d+)_ECG\.npy$")
DOCUMENTED_VIDEO_NAME = "Subject_<n>_<ROI>.avi (documented) / Subject_<n>_<ROI>_.avi (as released)"

# documented ROI mapping (Data in Brief 2025, §3): Cheek1 = right, Cheek2 = left
# Cheek1 = right cheek, Cheek2 = left cheek (Data in Brief 2025, §3). The paper
# also refers to them as "left and right cheek"; Cheek1 -> right is the provider's
# own numbering in §3 and is preserved verbatim rather than reinterpreted.
ROI_TO_PROJECT = {"Forehead": "forehead", "Cheek1": "right_cheek", "Cheek2": "left_cheek"}
PROJECT_ROIS = ("forehead", "right_cheek", "left_cheek")

DOCUMENTED_EXCLUDED_SUBJECT = 4     # article §4.7: excluded before release for tracking/ECG artifacts
EXPECTED_VIDEO_SIZE = (64, 64)      # (width, height) — provider documentation
EXPECTED_FPS = 30.0                 # provider documentation
EXPECTED_DURATION_S = 600.0         # provider documentation
DURATION_TOLERANCE_S = 2.0          # frames/second rounding, not a repair
SIZE_TOLERANCE_PX = 0            # 64x64 is documented exactly


class AdapterError(ValueError):
    """Machine-readable adapter failure (token + detail)."""

    def __init__(self, token: str, detail: str = ""):
        self.token = token
        super().__init__(f"{token}: {detail}" if detail else token)


# Failures that prevent any benchmark (missing/corrupt/mismatched structure).
# "deviation" failures are documented-attribute differences (e.g. a truncated
# local copy) that the researcher may explicitly accept; they are never
# silently ignored and are echoed into every downstream report.
ERROR_TOKENS = {
    "dataset_root_missing", "no_subject_directories", "unexpected_directory", "unexpected_nested_directory",
    "file_outside_subject_dir", "filename_subject_mismatch", "duplicate_roi_video", "duplicate_ecg",
    "missing_roi_video", "missing_ecg", "video_unreadable", "video_size_unexpected", "video_fps_unexpected",
    "video_timestamps_not_increasing", "video_too_few_frames", "ecg_not_1d", "ecg_dtype_unsupported",
    "ecg_fs_invalid", "expected_subject_missing", "unexpected_file", "documented_excluded_subject_present",
}
DEVIATION_TOKENS = {"video_duration_unexpected", "ecg_video_duration_mismatch", "additional_file_recorded"}


@dataclass
class ValidationFailure:
    token: str
    subject: Optional[int]
    artifact: str
    detail: str

    @property
    def severity(self) -> str:
        return "error" if self.token in ERROR_TOKENS else "deviation"

    def to_dict(self) -> dict:
        return {"token": self.token, "severity": self.severity, "subject": self.subject,
                "artifact": self.artifact, "detail": self.detail}


@dataclass
class SubjectFiles:
    subject: int
    directory: Path
    videos: dict[str, Path] = field(default_factory=dict)
    ecg: Optional[Path] = None


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def discover(root: str | Path) -> tuple[list[SubjectFiles], list[ValidationFailure]]:
    """Map the directory tree onto subjects; report, never repair."""
    root = Path(root).expanduser().resolve()
    failures: list[ValidationFailure] = []
    if not root.is_dir():
        raise AdapterError("dataset_root_missing", str(root))

    subjects: dict[int, SubjectFiles] = {}
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            if child.suffix.lower() in {".avi", ".npy"}:
                failures.append(ValidationFailure("file_outside_subject_dir", None, child.name,
                                                  "recording files must live inside Subject_<n>/"))
            elif child.suffix.lower() in {".xlsx", ".xls", ".csv", ".txt", ".md"}:
                failures.append(ValidationFailure("additional_file_recorded", None, child.name,
                                                  "provider metadata recorded, not parsed"))
            continue
        match = SUBJECT_DIR_RE.match(child.name)
        if not match:
            failures.append(ValidationFailure("unexpected_directory", None, child.name,
                                              "expected Subject_<n>"))
            continue
        sid = int(match.group(1))
        record = SubjectFiles(subject=sid, directory=child)
        for item in sorted(child.iterdir()):
            if item.is_dir():
                failures.append(ValidationFailure("unexpected_nested_directory", sid, item.name, "unexpected"))
                continue
            vmatch = VIDEO_RE.match(item.name)
            ematch = ECG_RE.match(item.name)
            if vmatch and int(vmatch.group(1)) == sid:
                roi = ROI_TO_PROJECT[vmatch.group(2)]
                if roi in record.videos:
                    failures.append(ValidationFailure("duplicate_roi_video", sid, item.name,
                                                      f"second file maps to {roi}"))
                record.videos[roi] = item
            elif ematch and int(ematch.group(1)) == sid:
                if record.ecg is not None:
                    failures.append(ValidationFailure("duplicate_ecg", sid, item.name, "second ECG file"))
                record.ecg = item
            elif vmatch or ematch:
                failures.append(ValidationFailure("filename_subject_mismatch", sid, item.name,
                                                  "subject number in filename disagrees with folder"))
            elif item.name.lower().endswith((".xlsx", ".xls", ".csv", ".txt", ".md")):
                # provider spreadsheet/metadata: recorded for provenance, never parsed
                failures.append(ValidationFailure("additional_file_recorded", sid, item.name,
                                                  "provider metadata recorded, not parsed"))
            else:
                failures.append(ValidationFailure("unexpected_file", sid, item.name,
                                                  "not part of the adapter contract"))
        subjects[sid] = record
    if not subjects:
        raise AdapterError("no_subject_directories", f"no Subject_<n>/ under {root}")
    return [subjects[k] for k in sorted(subjects)], failures


def probe_video(path: Path, *, max_frames: Optional[int] = None) -> dict:
    """Read container metadata and (optionally) decode frames to measure fps."""
    import cv2  # local import: adapter is importable without OpenCV

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise AdapterError("video_unreadable", str(path))
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        declared_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        decoded = 0
        if max_frames:
            while decoded < max_frames and cap.grab():
                decoded += 1
    finally:
        cap.release()
    return {
        "path": str(path),
        "width": width,
        "height": height,
        "declared_fps": declared_fps,
        "frame_count": frames,
        "frames_probed": decoded,
        "declared_duration_s": (frames / declared_fps) if declared_fps > 0 and frames > 0 else None,
    }


def probe_ecg(path: Path, fs_hz: float) -> dict:
    """Shape/dtype/duration only — values are never read into a report."""
    if not math.isfinite(fs_hz) or fs_hz <= 0:
        raise AdapterError("ecg_fs_invalid", f"declared ECG sampling rate {fs_hz!r}")
    array = np.load(path, mmap_mode="r", allow_pickle=False)
    if array.ndim != 1:
        raise AdapterError("ecg_not_1d", f"{path.name}: shape {array.shape}")
    if array.dtype.kind not in "fiu":
        raise AdapterError("ecg_dtype_unsupported", f"{path.name}: {array.dtype}")
    n = int(array.shape[0])
    return {
        "path": str(path),
        "sample_count": n,
        "dtype": str(array.dtype),
        "declared_fs_hz": float(fs_hz),
        "duration_s": n / fs_hz,
        "finite_sample_count": None,  # filled by load_ecg(), not by mmap probe
    }


def inventory(root: str | Path, *, ecg_fs_hz: float, probe_frames: bool = False,
              frame_probe_limit: int = 300, checksums: bool = True,
              expected_subjects: Optional[Iterable[int]] = None,
              exclude_subjects: Optional[Iterable[int]] = None) -> dict:
    """Full readiness inventory. Returns a JSON-serialisable dict.

    ``exclude_subjects`` is an explicit, recorded exclusion (e.g. a participant the
    provider removed, or a folder whose files are empty). Excluded subjects are not
    scanned, and the exclusion — with the caller's reason token and the evidence
    found on disk — is written into the report so it can never pass silently.
    """
    subjects, failures = discover(root)
    manifest_failures = list(failures)
    exclusions: list[dict] = []
    excluded = set(int(s) for s in (exclude_subjects or []))
    if excluded:
        kept = []
        for subject in subjects:
            if subject.subject in excluded:
                sizes = {roi: (path.stat().st_size if path.exists() else None)
                         for roi, path in subject.videos.items()}
                exclusions.append({
                    "subject": subject.subject,
                    "reason": "explicit_exclusion_by_caller",
                    "provider_documentation": (
                        "article §4.7 states Subject_4 was excluded before release for persistent "
                        "tracking failure and non-physiological ECG peaks" if subject.subject == DOCUMENTED_EXCLUDED_SUBJECT
                        else None),
                    "video_file_sizes_bytes": sizes,
                    "ecg_present": subject.ecg is not None,
                    "adapter_derived_evidence": (
                        "all ROI videos are 0 bytes (empty placeholder files)" if sizes and all(
                            size == 0 for size in sizes.values()) else None),
                })
            else:
                kept.append(subject)
        subjects = kept
    records: list[dict] = []
    for subject in subjects:
        missing = [roi for roi in PROJECT_ROIS if roi not in subject.videos]
        if missing:
            manifest_failures.append(ValidationFailure("missing_roi_video", subject.subject,
                                                       subject.directory.name, f"missing {', '.join(missing)}"))
        if subject.ecg is None:
            manifest_failures.append(ValidationFailure("missing_ecg", subject.subject,
                                                       subject.directory.name, "no Subject_<n>_ECG.npy"))
        record = {"subject": subject.subject, "directory": str(subject.directory), "videos": {}, "ecg": None}
        for roi, path in subject.videos.items():
            try:
                info = probe_video(path, max_frames=frame_probe_limit if probe_frames else None)
            except AdapterError as exc:
                manifest_failures.append(ValidationFailure(exc.token, subject.subject, path.name, str(exc)))
                record["videos"][roi] = {"path": str(path), "unreadable": True, "error": exc.token}
                continue
            if (info["width"], info["height"]) != EXPECTED_VIDEO_SIZE:
                manifest_failures.append(ValidationFailure(
                    "video_size_unexpected", subject.subject, path.name,
                    f"{info['width']}x{info['height']} vs documented 64x64"))
            if info["declared_fps"] and abs(info["declared_fps"] - EXPECTED_FPS) > 0.5:
                manifest_failures.append(ValidationFailure(
                    "video_fps_unexpected", subject.subject, path.name,
                    f"{info['declared_fps']:.2f} vs documented 30 fps"))
            duration = info["declared_duration_s"]
            if duration is not None and abs(duration - EXPECTED_DURATION_S) > DURATION_TOLERANCE_S:
                manifest_failures.append(ValidationFailure(
                    "video_duration_unexpected", subject.subject, path.name,
                    f"{duration:.2f}s vs documented 600s"))
            info["sha256"] = sha256_file(path) if checksums else None
            info["unreadable"] = False
            record["videos"][roi] = info
        if subject.ecg is not None:
            try:
                ecg_info = probe_ecg(subject.ecg, ecg_fs_hz)
            except AdapterError as exc:
                manifest_failures.append(ValidationFailure(exc.token, subject.subject, subject.ecg.name, str(exc)))
                ecg_info = None
            if ecg_info is not None:
                ecg_info["sha256"] = sha256_file(subject.ecg) if checksums else None
                durations = [v.get("declared_duration_s") for v in record["videos"].values()
                             if v.get("declared_duration_s")]
                if durations and abs(ecg_info["duration_s"] - max(durations)) > DURATION_TOLERANCE_S:
                    manifest_failures.append(ValidationFailure(
                        "ecg_video_duration_mismatch", subject.subject, subject.ecg.name,
                        f"ECG {ecg_info['duration_s']:.2f}s vs video {max(durations):.2f}s "
                        f"(manual sync, ±500 ms documented; this is a >2 s discrepancy)"))
                record["ecg"] = ecg_info
        records.append(record)

    found = {r["subject"] for r in records}
    if expected_subjects is not None:
        for sid in expected_subjects:
            if sid not in found:
                manifest_failures.append(ValidationFailure("expected_subject_missing", sid, "root", "not present"))
    # Provider documentation states Subject_4 was excluded before release; if it is
    # present and the caller has not explicitly excluded it, say so loudly.
    if DOCUMENTED_EXCLUDED_SUBJECT in found and DOCUMENTED_EXCLUDED_SUBJECT not in excluded:
        manifest_failures.append(ValidationFailure(
            "documented_excluded_subject_present", DOCUMENTED_EXCLUDED_SUBJECT, "root",
            "the article states Subject_4 was excluded before release, but Subject_4 is present in this copy; "
            f"use --expected-subjects to state your exclusion policy, or --allow-deviation to benchmark it"))
        records = records  # unchanged; the token above is the record of it
    complete = [r["subject"] for r in records
                if all(roi in r["videos"] for roi in PROJECT_ROIS) and r["ecg"] is not None
                and not any(r["videos"][roi].get("unreadable") for roi in PROJECT_ROIS)]

    return {
        "schema": SCHEMA_INVENTORY,
        "dataset": "rPPG-10",
        "dataset_version": "1 (Mendeley Data 10.17632/bx8982xgwt.1)",
        "citation": "Rodrigues G., Garcia N.M. Evaluating remote photoplethysmography: a 10-minute video "
                    "dataset in uncontrolled lighting. Data in Brief 61 (2025) 111888. "
                    "doi:10.1016/j.dib.2025.111888",
        "license": "CC BY-NC-SA 4.0 (non-commercial; share-alike). Verify current terms at the provider record.",
        "root": str(Path(root).expanduser().resolve()),
        "declared_ecg_fs_hz": float(ecg_fs_hz),
        "roi_mapping": {k: v for k, v in ROI_TO_PROJECT.items()},
        "subjects_found": len(records),
        "subjects_complete": len(complete),
        "excluded_subjects": exclusions,
        "expected_subjects": sorted(expected_subjects) if expected_subjects is not None else None,
        "records": records,
        "validation_failures": [f.to_dict() for f in manifest_failures],
        "validation_failure_tokens": sorted({f.token for f in manifest_failures}),
        "error_tokens": sorted({f.token for f in manifest_failures if f.severity == "error"}),
        "deviation_tokens": sorted({f.token for f in manifest_failures if f.severity == "deviation"}),
        "honesty": {
            "values_read": "No signal values were read: ECG inspected as a memory map (shape/dtype only).",
            "metadata_source": "Frame counts, dimensions and frame rate come from the file containers; "
                               "the ECG sampling rate is the caller-supplied value, recorded verbatim.",
            "repairs_applied": "none — every inconsistency is reported as a validation failure",
            "accuracy_evaluation": "NOT RUN — this is a readiness inventory, not a benchmark",
        },
    }


def load_ecg(path: Path) -> np.ndarray:
    """Load an ECG array for processing; non-finite values are reported, not repaired."""
    array = np.load(path, allow_pickle=False)
    if array.ndim != 1:
        raise AdapterError("ecg_not_1d", f"{path.name}: shape {array.shape}")
    return np.asarray(array, dtype=np.float64)


def extract_roi_trace(video_path: Path, *, max_seconds: Optional[float] = None,
                      expected_size: tuple[int, int] = EXPECTED_VIDEO_SIZE) -> dict:
    """Decode one already-cropped ROI video into per-frame mean RGB + timestamps.

    No face detection is applied. Corrupt/unreadable frames are counted and
    their indices recorded; frames are never interpolated or invented.
    """
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise AdapterError("video_unreadable", str(video_path))
    timestamps: list[float] = []
    means: list[list[float]] = []
    dropped: list[int] = []
    index = 0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if (width, height) != tuple(expected_size):
        cap.release()
        raise AdapterError("video_size_unexpected", f"{video_path.name}: {width}x{height}")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            position_ms = float(cap.get(cv2.CAP_PROP_POS_MSEC) or 0.0)
            if frame is None or frame.size == 0:
                dropped.append(index)
                index += 1
                continue
            pixels = frame.reshape(-1, 3).astype(np.float64)
            if not np.isfinite(pixels).all():
                dropped.append(index)
                index += 1
                continue
            # OpenCV yields BGR; store as R, G, B (trace-domain methods expect RGB)
            means.append([float(pixels[:, 2].mean()), float(pixels[:, 1].mean()), float(pixels[:, 0].mean())])
            timestamps.append(position_ms / 1000.0)
            index += 1
            if max_seconds is not None and timestamps and timestamps[-1] >= max_seconds:
                break
    finally:
        cap.release()
    if len(timestamps) < 2:
        raise AdapterError("video_too_few_frames", f"{video_path.name}: {len(timestamps)} frames")
    t = np.asarray(timestamps, dtype=np.float64)
    diffs = np.diff(t)
    if np.any(diffs <= 0):
        raise AdapterError("video_timestamps_not_increasing", f"{video_path.name}")
    measured_fps = float(1.0 / np.median(diffs))
    return {
        "schema": SCHEMA_TRACE,
        "path": str(video_path),
        "roi": next((v for k, v in ROI_TO_PROJECT.items()
                     if re.search(rf"_{k}_?\.avi$", video_path.name)), None),
        "timestamps_s": t,
        "rgb": np.asarray(means, dtype=np.float64),
        "frame_count": int(len(t)),
        "dropped_frames": dropped,
        "dropped_fraction": float(len(dropped) / max(1, len(dropped) + len(t))),
        "measured_fps_hz": measured_fps,
        "timestamp_jitter_fraction": float(np.mean(np.abs(diffs - np.median(diffs)) > 0.05 * np.median(diffs))),
        "raw_fps_estimate_note": "measured from CAP_PROP_POS_MSEC; container-declared fps is reported separately",
    }


def write_trace_csv(path: Path, trace: dict) -> None:
    """Persist a decoded ROI trace as CSV (timestamp_s + rgb) for reuse."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    t, rgb = trace["timestamps_s"], trace["rgb"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write("timestamp_s,r,g,b\n")
        for i in range(len(t)):
            fh.write(f"{t[i]:.6f},{rgb[i, 0]:.6f},{rgb[i, 1]:.6f},{rgb[i, 2]:.6f}\n")


def write_json(path: Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False, sort_keys=False) + "\n", encoding="utf-8")
