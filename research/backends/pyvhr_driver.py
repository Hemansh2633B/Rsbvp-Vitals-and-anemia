#!/usr/bin/env python3
"""RSBVP -> pyVHR bridge driver. Runs INSIDE the pyVHR environment.

This file is original RSBVP code (MIT). It imports the external GPL-3.0
``pyVHR`` package at runtime; it does not copy any pyVHR source. It reads a
manifest JSON: [{"recording_id": ..., "video_path": ...}, ...], executes
pyVHR's ``Pipeline.run_on_video`` per recording and per method, and prints
one JSON object per line:

  {"type": "window", "recording_id": ..., "algorithm": ..., "roi": ...,
   "timestamp_s": <pyVHR estimation time>, "window_end_s": ...,
   "sampling_rate_hz": <container fps or null>, "estimated_hr_bpm": <float>}
  {"type": "info", ...} / {"type": "error", ...}

pyVHR's exact ``timesES`` convention (window start vs centre) follows the
upstream release you installed; consult the pyVHR documentation before
aligning windows across backends. Exit code 0 when at least one window was
produced, 3 when pyVHR cannot be imported, 1 on total failure.
"""
from __future__ import annotations

import argparse
import json
import sys


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, default=str) + "\n")
    sys.stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--methods", nargs="+", required=True)
    parser.add_argument("--winsize", type=float, default=6.0)
    parser.add_argument("--roi-approach", default="patches", choices=["holistic", "patches"])
    parser.add_argument("--cuda", default="false")
    args = parser.parse_args()

    try:
        from pyVHR.analysis.pipeline import Pipeline  # external GPL-3.0 package
    except Exception as exc:  # noqa: BLE001
        emit({"type": "error", "stage": "import", "message": f"pyVHR import failed: {exc}"})
        return 3

    with open(args.manifest, encoding="utf-8") as handle:
        entries = json.load(handle)

    try:
        import cv2
        def container_fps(path):
            capture = cv2.VideoCapture(path)
            fps = capture.get(cv2.CAP_PROP_FPS)
            capture.release()
            return float(fps) if fps and fps > 0 else None
    except Exception:  # noqa: BLE001
        def container_fps(path):
            return None

    use_cuda = str(args.cuda).lower() in {"1", "true", "yes"}
    estimate = "medians" if args.roi_approach == "patches" else "clustering"
    window_records = 0
    errors = 0
    pipeline = Pipeline()

    for entry in entries:
        recording_id = entry["recording_id"]
        video_path = entry["video_path"]
        fps = container_fps(video_path)
        for method in args.methods:
            try:
                bvps, times_es, bpm_es = pipeline.run_on_video(
                    video_path,
                    winsize=args.winsize,
                    roi_method="convexhull",
                    roi_approach=args.roi_approach,
                    method=method,
                    estimate=estimate,
                    patch_size=0,
                    RGB_LOW_HIGH_TH=(5, 230),
                    Skin_LOW_HIGH_TH=(5, 230),
                    pre_filt=True,
                    post_filt=True,
                    cuda=use_cuda,
                    verb=False,
                )
            except Exception as exc:  # noqa: BLE001 — keep processing remaining methods
                errors += 1
                emit({"type": "error", "recording_id": recording_id,
                      "algorithm": method, "message": str(exc)})
                continue
            times = list(times_es) if times_es is not None else []
            bpms = list(bpm_es) if bpm_es is not None else []
            for index, bpm in enumerate(bpms):
                try:
                    bpm_value = float(bpm)
                except (TypeError, ValueError):
                    bpm_value = None
                t = float(times[index]) if index < len(times) else None
                emit({
                    "type": "window",
                    "recording_id": recording_id,
                    "algorithm": method,
                    "roi": args.roi_approach,
                    "timestamp_s": t,
                    "window_end_s": (t + args.winsize) if t is not None else None,
                    "sampling_rate_hz": fps,
                    "estimated_hr_bpm": bpm_value,
                })
                window_records += 1

    emit({"type": "info", "window_records": window_records, "errors": errors})
    return 0 if window_records else 1


if __name__ == "__main__":
    sys.exit(main())
