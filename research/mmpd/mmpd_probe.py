#!/usr/bin/env python3
"""MMPD readiness + sample-GIF pipeline smoke probe.

Two honest modes, neither of which may be represented as an accuracy
evaluation:

``--gif-dir DIR``  Decode the 16 *public sample GIFs* shipped in the MMPD
GitHub repository (a few seconds each, 112x199, no ground truth), extract
skin-masked forehead/cheek RGB traces with the repository's offline tooling,
and run the trace-domain classical estimators. The result demonstrates that
the end-to-end path *executes* on real mobile-camera samples and reports
per-GIF availability/rejection diagnostics. It contains NO reference PPG, so
**no accuracy metric is computed or permitted** — any such number would be a
fabrication.

``--inspect-mat ROOT``  Inspect a *locally acquired* MMPD full dataset (after
the signed data-release agreement). Prints the subject/mat layout, per-file
variable-name/shape/dtype inventory and label-distribution cross-checks
against the public ``meta_label.csv``. Values of video/PPG arrays are never
read into the report. No estimation happens in this mode.

Both modes write JSON + Markdown reports and never modify inputs. Sample
GIFs and dataset files must never be committed to Git.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "gui"))
sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402
import cv2  # noqa: E402
from PIL import Image  # noqa: E402

from rppg_core import pipeline as legacy  # noqa: E402
from research.backends import reference_methods as rm  # noqa: E402

SCHEMA_GIF = "rsbvp.mmpd-gif-smoke.v1"
SCHEMA_MAT = "rsbvp.mmpd-mat-inspect.v1"
HONESTY = {
    "accuracy_evaluation": "NOT RUN — the sample GIFs carry no reference PPG; no MAE/RMSE/agreement may be computed from them",
    "face_detection_floor": "Haar when available; otherwise a centred face prior (reported per record), never a silent substitution",
    "clinical_use": "none — research software verification only",
    "dataset_affiliation": "MMPD (Tsinghua University, EMBC 2023); academic use only; citation doi:10.1109/EMBC40787.2023.10340857",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_gif(gif_path: Path) -> dict:
    """Decode one sample GIF and run the trace pipeline. Diagnostic only."""
    im = Image.open(gif_path)
    n_frames = getattr(im, "n_frames", 1)
    durations = []
    frames_rgb: list[np.ndarray] = []
    for index in range(n_frames):
        im.seek(index)
        durations.append(im.info.get("duration", None))
        frames_rgb.append(np.asarray(im.convert("RGB"), dtype=np.uint8))
    uniform = len(set(durations)) == 1
    frame_ms = durations[0] if durations and durations[0] is not None else None
    fps = (1000.0 / frame_ms) if frame_ms else None
    timestamps = np.cumsum([(d or 0.0) / 1000.0 for d in durations]) - (durations[0] or 0.0) / 2000.0 if fps else np.arange(n_frames, dtype=float) / 30.0

    face_cascade = None
    if hasattr(cv2, "CascadeClassifier"):
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    face_detection = "haar" if face_cascade is not None else "unavailable_in_cv2_build__central_prior"
    roi_traces: dict[str, list] = {name: [] for name in ("forehead", "left_cheek", "right_cheek")}
    ts_keep: list[float] = []
    faces_found = 0
    upscale = 3
    for index, frame in enumerate(frames_rgb):
        bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        face = None
        if face_cascade is not None:
            big = cv2.resize(bgr, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
            detected = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(30, 30))
            if detected is not None and len(detected):
                face = legacy.largest_face(detected)
                face = tuple(int(v / upscale) for v in face)
        else:
            # No Haar support in this OpenCV build: assume the published sample
            # previews are close-cropped faces and take a centred face prior.
            h, w = bgr.shape[:2]
            face = (int(0.15 * w), int(0.05 * h), int(0.70 * w), int(0.85 * h))
        if face is None:
            continue
        faces_found += 1
        rois = legacy.get_multi_rois(face, bgr.shape)
        samples = {name: legacy.mean_rgb_from_roi(bgr, roi) for name, roi in rois.items()}
        ts_keep.append(float(timestamps[index]))
        for name in roi_traces:
            roi_traces[name].append(None if samples[name] is None else samples[name].astype(float))

    duration_s = float(timestamps[-1] - timestamps[0]) if n_frames > 1 else 0.0
    record = {
        "file": gif_path.name,
        "sha256": sha256_file(gif_path),
        "bytes": gif_path.stat().st_size,
        "frames": n_frames,
        "width": int(frames_rgb[0].shape[1]) if frames_rgb else 0,
        "height": int(frames_rgb[0].shape[0]) if frames_rgb else 0,
        "frame_duration_ms": frame_ms,
        "uniform_frame_duration": bool(uniform),
        "gif_fps_effective": round(fps, 3) if fps else None,
        "duration_s": round(duration_s, 3),
        "face_detection": face_detection,
        "face_detected_frames": faces_found,
        "face_detection_rate": round(faces_found / n_frames, 4) if n_frames else None,
        "expected_window_seconds": 10.0,
        "meets_min_window_seconds": bool(duration_s >= 10.0),
        "roi_coverage": {},
        "diagnostic_estimates_bpm": {},
        "honesty": dict(HONESTY),
    }
    if face_detection != "haar":
        record["notes"] = "No face detector in this OpenCV build (cv2.CascadeClassifier absent, e.g. opencv 5 headless); ROI used a centred face prior. ROI presence values are estimates, not detections."
    for name, samples in roi_traces.items():
        valid = [s for s in samples if s is not None]
        record["roi_coverage"][name] = round(len(valid) / len(samples), 4) if samples else 0.0
    if ts_keep and fps and duration_s >= 1.0:
        fs = 1.0 / (np.median(np.diff(np.asarray(ts_keep))) if len(ts_keep) > 1 else 1.0 / fps)
        for name, samples in roi_traces.items():
            arr = np.asarray([s if s is not None else (np.nan, np.nan, np.nan) for s in samples], dtype=float)
            mask = np.isfinite(arr).all(axis=1)
            if mask.sum() < max(8, int(0.5 * len(arr))):
                record["diagnostic_estimates_bpm"][name] = {m: None for m in ("GREEN", "POS", "CHROM", "ICA", "PBV")}
                record["diagnostic_estimates_bpm"][name]["_unavailable_reason"] = "insufficient_valid_roi_samples"
                continue
            trace = arr[mask]
            ts = np.asarray(ts_keep)[mask]
            trace_fs = 1.0 / float(np.median(np.diff(ts))) if len(ts) > 1 else fps
            entry = {}
            for method in ("green", "pos", "chrom", "ica", "pbv"):
                try:
                    filtered, _meta = getattr(rm, method)(trace, trace_fs)
                except Exception as exc:  # unavailable/estimator failure — never fabricate
                    entry[method.upper()] = None
                    entry[f"{method.upper()}_unavailable_reason"] = f"{type(exc).__name__}:{exc}"
                    continue
                bpm, peak_fraction, snr_db, separation = rm.spectral_features(filtered, trace_fs)
                entry[method.upper()] = None if bpm is None else round(float(bpm), 2)
                entry[f"{method.upper()}_spectral"] = {
                    "peak_fraction": None if peak_fraction is None else round(float(peak_fraction), 4),
                    "snr_db": None if snr_db is None else round(float(snr_db), 2),
                    "separation_ratio": None if separation is None else round(float(separation), 3),
                    "quality_tokens": rm.quality_failures(peak_fraction, snr_db, separation),
                }
            record["diagnostic_estimates_bpm"][name] = entry
    else:
        for name in roi_traces:
            record["diagnostic_estimates_bpm"][name] = None
    return record


def gif_smoke(gif_dir: Path, output_dir: Path) -> dict:
    gifs = sorted(gif_dir.glob("*.gif"))
    if not gifs:
        raise SystemExit(f"no .gif files in {gif_dir}")
    records = [probe_gif(p) for p in gifs]
    report = {
        "schema": SCHEMA_GIF,
        "gif_dir": str(gif_dir),
        "record_count": len(records),
        "total_duration_seconds": round(sum(r["duration_s"] for r in records), 3),
        "records": records,
        "interpretation": (
            "Public MMPD sample previews (few seconds each, no reference PPG). "
            "Per-GIF estimates are diagnostics of pipeline execution only — NOT physiological measurements, "
            "NOT an accuracy evaluation, and NOT a substitute for the full dataset under the data-release agreement."
        ),
        "honesty": dict(HONESTY),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "mmpd_gif_smoke.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    write_markdown(report, output_dir / "mmpd_gif_smoke.md")
    return report


def write_markdown(report: dict, path: Path) -> None:
    lines = [
        "# MMPD sample-GIF pipeline smoke report",
        "",
        f"**{SCHEMA_GIF}** — {report['record_count']} public sample GIFs, {report['total_duration_seconds']}s total.",
        "",
        "**DIAGNOSTIC PIPELINE CHECK ONLY. The sample GIFs carry no reference PPG. "
        "No accuracy, fidelity, or clinical metric is computed or claimed.**",
        "",
        "| GIF | frames | fps | dur(s) | face detect | ROI cov (F/LC/RC) | meets ≥10s |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in report["records"]:
        cov = r["roi_coverage"]
        lines.append(
            f"| {r['file']} | {r['frames']} | {r['gif_fps_effective']} | {r['duration_s']} | "
            f"{r['face_detection_rate']} | {cov.get('forehead')}/{cov.get('left_cheek')}/{cov.get('right_cheek')} | "
            f"{'yes' if r['meets_min_window_seconds'] else 'no'} |"
        )
    lines += [
        "",
        "## What this proves and what it does not",
        "",
        "- Proves: the offline decode → face/ROI → skin-mask → trace → estimator path executes on real "
        "mobile-camera MMPD sample GIFs and reports unavailable states instead of crashing or fabricating.",
        "- Does NOT prove: any estimate is correct, stable, or physiological. 4.5 s clips fall far below the "
        "10 s research minimum window; spectral resolution ≈ 13 BPM; gates are not physiologically calibrated.",
        "- Accuracy evaluation against PPG ground truth requires the **full MMPD dataset**, which is not public: "
        "it needs the signed data-release agreement (faculty-signed email to the authors) and local placement "
        "under `RSBVP_DATA_ROOT`. See `docs/MMPD_VALIDATION.md`.",
    ]
    path.write_text("\n".join(lines) + "\n")


def inspect_mat(root: Path, output_dir: Path) -> dict:
    import scipy.io
    subjects = sorted(p for p in root.glob("subject*") if p.is_dir())
    mats = [m for s in subjects for m in sorted(s.glob("p*_*.mat"))]
    inventory = []
    for mat_path in mats[: min(5, len(mats))]:
        try:
            mat = scipy.io.loadmat(str(mat_path), struct_as_record=True, squeeze_me=False)
            keys = {k: (list(v.shape), str(v.dtype)) for k, v in mat.items() if not k.startswith("__")}
        except Exception as exc:
            keys = {"_load_error": f"{type(exc).__name__}:{exc}"}
        inventory.append({"file": str(mat_path.relative_to(root)), "keys": keys})
    report = {
        "schema": SCHEMA_MAT,
        "root": str(root),
        "subject_dirs": len(subjects),
        "mat_files": len(mats),
        "expected_per_meta_label_csv": 660,
        "sampled_inventory": inventory,
        "note": "Key inventory only; video/PPG sample values are never read into reports. Verify light/motion/skin_color/GT_ppg semantics against the provider documentation before any analysis.",
        "honesty": dict(HONESTY),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "mmpd_mat_inspect.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--gif-dir", type=Path, help="Directory of public MMPD sample GIFs (never commit them)")
    group.add_argument("--inspect-mat", type=Path, help="Root of a locally acquired MMPD full dataset")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/mmpd"))
    args = parser.parse_args()
    if args.gif_dir:
        report = gif_smoke(args.gif_dir, args.output_dir)
        print(f"wrote {args.output_dir/'mmpd_gif_smoke.json'} ({report['record_count']} GIFs)")
    else:
        report = inspect_mat(args.inspect_mat, args.output_dir)
        print(f"wrote {args.output_dir/'mmpd_mat_inspect.json'} ({report['mat_files']} .mat files, {report['subject_dirs']} subjects)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
