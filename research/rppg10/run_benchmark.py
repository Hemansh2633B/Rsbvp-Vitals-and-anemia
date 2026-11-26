#!/usr/bin/env python3
"""rPPG-10 benchmark CLI: inventory readiness, then (only with data) the frozen run.

Usage
-----
Inspect an authorized local copy (no signal values read, no benchmark):
    python research/rppg10/run_benchmark.py inspect \
        --data-root /path/to/rppg10 --output-dir reports/rppg10 --ecg-fs-hz 1000

Run the frozen benchmark (requires the same root plus explicit authorization
confirmation; refuses otherwise):
    python research/rppg10/run_benchmark.py benchmark \
        --data-root /path/to/rppg10 --output-dir reports/rppg10 --ecg-fs-hz 1000 \
        --i-have-verified-the-licence

With no data available, use the readiness path:
    python research/rppg10/run_benchmark.py readiness --output-dir reports/rppg10

Nothing here downloads data, writes into the dataset root, tunes a threshold,
or reports a metric when the reference is unavailable.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from research.ecg import reference as ecgref  # noqa: E402
from research.rppg10 import adapter, protocol  # noqa: E402

DATASET_CITATION = ("Rodrigues G., Garcia N.M. Evaluating remote photoplethysmography: a 10-minute "
                    "video dataset in uncontrolled lighting. Data in Brief 61 (2025) 111888. "
                    "doi:10.1016/j.dib.2025.111888  (dataset doi:10.17632/bx8982xgwt.1, CC BY-NC-SA 4.0)")

LIMITATIONS = [
    "26 participants (Subject_4 excluded by the provider), predominantly young Portuguese university "
    "students; Fitzpatrick I–IV only (no V/VI). No generalisation beyond this population.",
    "Single-site acquisition: one room, natural indoor daylight, 10:00–16:00, one webcam type, "
    "participants seated and asked to stay still. No claim about other lighting, motion or devices.",
    "64×64 ROI crops with consumer compression: fine pulsatile detail is limited by the provider's "
    "anonymisation pipeline, not by this implementation.",
    "Video/ECG synchronisation is manual with a documented uncertainty of up to ±500 ms; this "
    "protocol therefore evaluates 30 s windows, not sub-second timing.",
    "The ECG reference is a pulse-rate reference derived from R-peaks. Agreement with it is NOT "
    "validation of pulse-rate variability, HRV, or any clinical parameter.",
    "Non-commercial licence (CC BY-NC-SA 4.0): results are research-use only and share-alike terms apply "
    "to redistribution of derived data.",
]


def _environment_block() -> dict:
    """Software provenance for this benchmark run.

    Records the interpreter, the numerical stack, the git commit of the code that
    produced the numbers and the estimator configuration actually used. Missing
    information is reported as null/"unknown" - never guessed - so a reader can
    tell whether a report is reproducible.
    """
    import os
    import subprocess

    import scipy

    def _commit() -> str:
        env = (os.environ.get("RSBVP_GIT_SHA") or "").strip()
        if env:
            return env
        try:
            root = Path(__file__).resolve().parents[2]
            out = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=root,
                                 capture_output=True, text=True, timeout=5, check=True)
            return out.stdout.strip() or "unknown"
        except Exception:
            return "unknown"

    try:
        import cv2

        opencv = cv2.__version__
    except Exception:
        opencv = None

    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "opencv": opencv,
        "git_commit": _commit(),
        "estimators": {
            # The three projections under test and the estimator that consumes them.
            "green": "bandpassed green-channel spectral peak",
            "pos": "POS projection, spectral peak",
            "chrom": "CHROM projection, spectral peak",
            "estimator": "Hann-windowed periodogram peak in the cardiac passband",
        },
        "frozen_protocol": protocol.PROTOCOL_VERSION,
    }


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def cmd_readiness(output_dir: Path) -> int:
    """No data: emit the readiness assessment and an explicit NOT RUN report."""
    payload = {
        "schema": "rsbvp.rppg10-readiness.v1",
        "generated_at_utc": _now(),
        "status": "NOT RUN",
        "dataset": "rPPG-10",
        "citation": DATASET_CITATION,
        "license": "CC BY-NC-SA 4.0 — non-commercial, share-alike; verify at the provider record",
        "availability": {
            "public_record": "https://data.mendeley.com/datasets/bx8982xgwt/1",
            "paper_doi": "10.1016/j.dib.2025.111888",
            "download": "Mendeley Data zip (approx. 116 MB compressed / 78.4 MB listed payload); no "
                        "agreement gate documented, but the licence is non-commercial",
            "obtained_locally": False,
            "reason_not_run": "No authorized local copy was supplied to this environment; RSBVP_DATA_ROOT "
                              "is unset and no rPPG-10 files are present.",
        },
        "documented_structure": {
            "participants": 26,
            "excluded_by_provider": [4],
            "rois": ["Forehead", "Cheek1 (right)", "Cheek2 (left)"],
            "video": "Subject_<n>/Subject_<n>_<ROI>.avi — provider states 64x64, 30 fps, 600 s",
            "ecg": "Subject_<n>/Subject_<n>_ECG.npy — provider states BITalino, 1000 Hz, 3-electrode",
            "metadata": "provider .xlsx (demographics, environment) — presence recorded, never parsed",
        },
        "adapter": {
            "module": "research/rppg10/adapter.py",
            "modes": ["discover", "inventory (container metadata + checksums)", "extract_roi_trace (RGB means)"],
            "derives_from_files": ["frame size", "frame count", "declared fps", "duration", "ECG length/dtype"],
            "never_guesses": ["ECG sampling rate (must be supplied)", "synchronisation offset", "units"],
            "repairs": "none — inconsistencies are validation failures",
        },
        "ecg_reference_pathway": {
            "module": "research/ecg/reference.py",
            "method": "Pan–Tompkins QRS detection (1985): 5–15 Hz bandpass, derivative, squaring, 150 ms "
                      "integration, adaptive thresholding, 200 ms refractory, R-peak refinement",
            "hr_rule": "60 / median(valid R-R) per window",
            "rejections": ["ecg_fs_invalid", "ecg_nonfinite_samples", "ecg_flat_signal", "ecg_saturated",
                           "ecg_timestamps_irregular", "ecg_window_out_of_bounds", "ecg_too_few_rpeaks",
                           "ecg_rr_out_of_range", "ecg_window_too_short"],
            "existing_evaluator_unchanged": True,
            "why_separate": "research/rppg/dataset_io.py rejects ECG references with "
                            "ecg_rpeak_estimator_unavailable; that behaviour is preserved and this pathway "
                            "is the only ECG reader, feeding references after estimation",
            "explicitly_not": ["HRV/PRV estimation", "arrhythmia detection", "clinical interpretation",
                               "ECG spectral-peak HR"],
        },
        "protocol": protocol.protocol_description(),
        "blocking_reason": "Dataset not present in this environment. The readiness adapter, ECG reference "
                           "pathway, frozen protocol and dataset-independent tests are complete; the "
                           "benchmark itself is NOT RUN.",
        "limitations": LIMITATIONS,
        "honesty": {
            "accuracy_evaluation": "NOT RUN — no rPPG-10 data was available",
            "fabricated_numbers": "none",
            "test_data": "All tests use synthetic ECG/traces and PNG/GIF-encoded synthetic videos; "
                         "no participant data was created or collected by this project.",
        },
    }
    _write(output_dir / "rppg10_readiness.json", payload)
    (output_dir / "rppg10_readiness.md").write_text(_readiness_markdown(payload), encoding="utf-8")
    print(f"wrote {output_dir / 'rppg10_readiness.json'}")
    return 0


def _readiness_markdown(payload: dict) -> str:
    return f"""# rPPG-10 readiness assessment

**Status: NOT RUN — dataset not present in this environment.**

- Dataset: rPPG-10 (Mendeley Data, doi:10.17632/bx8982xgwt.1), CC BY-NC-SA 4.0.
- Citation: Rodrigues G., Garcia N.M. *Evaluating remote photoplethysmography: a 10-minute video dataset
  in uncontrolled lighting.* Data in Brief 61 (2025) 111888. doi:10.1016/j.dib.2025.111888
- Documented contents: 26 participants × 3 ROI videos (forehead, right/left cheek), 600 s each, 64×64 AVI,
  synchronised BITalino ECG (`.npy`), plus a provider metadata spreadsheet. Subject_4 excluded by the provider.
- Adapter: `research/rppg10/adapter.py` (inventory + trace extraction; no guessed metadata, no repairs).
- ECG reference pathway: `research/ecg/reference.py` (Pan–Tompkins R-peaks; 60/median R-R per window).
  The existing evaluator continues to reject ECG references — that behaviour is deliberately preserved.
- Protocol: `{payload['protocol']['protocol_version']}` frozen {payload['protocol']['frozen_date']} —
  30 s non-overlapping windows, GREEN/POS/CHROM, unchanged quality gates, participant-level bootstrap.

## Why it is not run

{payload['blocking_reason']}

## What is ready

1. Readiness inventory (`inspect`) that derives file facts and reports every inconsistency as a
   machine-readable validation failure.
2. An independently tested ECG reference pathway with explicit rejection tokens.
3. A frozen, pre-registered protocol with participant-grouped uncertainty and explicit coverage accounting.
4. Dataset-independent regression tests (synthetic ECG, synthetic traces, synthetic videos).

## What must happen to run it

1. Download the dataset from the provider record (no agreement gate is documented, but the licence is
   **non-commercial** — confirm this is acceptable for the intended use).
2. Keep it **outside Git**, e.g. `$RSBVP_DATA_ROOT/rppg10/Subject_1/...`.
3. `python research/rppg10/run_benchmark.py inspect --data-root $RSBVP_DATA_ROOT/rppg10 --output-dir reports/rppg10 --ecg-fs-hz 1000`
4. Resolve every validation failure in the inventory (do not edit the report).
5. `python research/rppg10/run_benchmark.py benchmark --data-root ... --output-dir reports/rppg10 --ecg-fs-hz 1000 --i-have-verified-the-licence`
   (add `--allow-deviation` only if you have reviewed each documented-attribute deviation; the deviations are echoed into the report)

## Limitations that will still apply after the run

{chr(10).join('- ' + item for item in payload['limitations'])}

No accuracy metric exists for rPPG-10 in this project, and nothing in this document is a result.
"""


def _require_authorization(args) -> None:
    if not getattr(args, "i_have_verified_the_licence", False):
        raise SystemExit(
            "refusing to run: pass --i-have-verified-the-licence after confirming CC BY-NC-SA 4.0 "
            "terms (non-commercial, share-alike) apply to your intended use"
        )


def cmd_inspect(args) -> int:
    data_root = Path(args.data_root).expanduser().resolve()
    payload = adapter.inventory(
        data_root,
        ecg_fs_hz=args.ecg_fs_hz,
        probe_frames=args.probe_frames,
        checksums=not args.no_checksums,
        expected_subjects=args.expected_subjects,
        exclude_subjects=args.exclude_subjects,
    )
    payload["generated_at_utc"] = _now()
    payload["citation"] = DATASET_CITATION
    payload["limitations"] = LIMITATIONS
    payload["honesty"]["benchmark"] = "NOT RUN — inventory only; run the benchmark command afterwards"
    _write(Path(args.output_dir) / "rppg10_inventory.json", payload)
    failures = payload["validation_failures"]
    print(f"subjects found: {payload['subjects_found']} complete: {payload['subjects_complete']} "
          f"excluded: {[e['subject'] for e in payload['excluded_subjects']]}")
    print(f"validation failures: {len(failures)} (errors: {len(payload['error_tokens'])}, "
          f"deviations: {len(payload['deviation_tokens'])})")
    for failure in failures:
        print(f"  - [{failure['severity']}] {failure['token']}: {failure['artifact']} — {failure['detail']}")
    return 0 if not failures else 2


def cmd_benchmark(args) -> int:
    _require_authorization(args)
    data_root = Path(args.data_root).expanduser().resolve()
    output_dir = Path(args.output_dir)
    inv = adapter.inventory(data_root, ecg_fs_hz=args.ecg_fs_hz, probe_frames=False,
                            checksums=True, expected_subjects=args.expected_subjects,
                            exclude_subjects=args.exclude_subjects)
    payload = {
        "schema": "rsbvp.rppg10-benchmark.v1",
        "generated_at_utc": _now(),
        "dataset": "rPPG-10",
        "citation": DATASET_CITATION,
        "license": "CC BY-NC-SA 4.0 (non-commercial, share-alike)",
        # Reproducibility provenance: which software produced these numbers, on
        # which platform, with which estimator configuration. A report without
        # this cannot be reproduced or compared over time.
        "environment": _environment_block(),
        "protocol": protocol.protocol_description(),
        "inventory_summary": {
            "subjects_found": inv["subjects_found"],
            "subjects_complete": inv["subjects_complete"],
            "excluded_subjects": inv["excluded_subjects"],
            "validation_failures": inv["validation_failures"],
            "error_tokens": inv["error_tokens"],
            "deviation_tokens": inv["deviation_tokens"],
        },
        "limitations": LIMITATIONS,
    }
    if inv["error_tokens"]:
        payload.update({
            "status": "NOT RUN",
            "blocking_reason": "Dataset inventory reported structural errors "
                               f"({', '.join(inv['error_tokens'])}); resolve them before benchmarking "
                               "(the adapter never repairs inconsistencies).",
        })
        _write(output_dir / "rppg10_benchmark.json", payload)
        (output_dir / "rppg10_benchmark.md").write_text(protocol.markdown_report(payload), encoding="utf-8")
        print("NOT RUN: structural validation errors present")
        return 2
    undocumented = [e for e in inv["excluded_subjects"] if not e.get("provider_documentation")]
    if undocumented and not args.allow_deviation:
        payload.update({
            "status": "NOT RUN",
            "blocking_reason": "Undocumented participant exclusion requested for "
                               f"Subject(s) {[e['subject'] for e in undocumented]}. The provider documents "
                               "no such exclusion, so it requires --allow-deviation and is echoed into the report.",
        })
        _write(output_dir / "rppg10_benchmark.json", payload)
        (output_dir / "rppg10_benchmark.md").write_text(protocol.markdown_report(payload), encoding="utf-8")
        print("NOT RUN: undocumented exclusion (pass --allow-deviation to proceed)")
        return 2
    if inv["deviation_tokens"] and not args.allow_deviation:
        payload.update({
            "status": "NOT RUN",
            "blocking_reason": "Dataset deviates from the provider's documented attributes "
                               f"({', '.join(inv['deviation_tokens'])}). Re-run with --allow-deviation to "
                               "benchmark anyway; every deviation is echoed into the report.",
        })
        _write(output_dir / "rppg10_benchmark.json", payload)
        (output_dir / "rppg10_benchmark.md").write_text(protocol.markdown_report(payload), encoding="utf-8")
        print("NOT RUN: undocumented deviations present (pass --allow-deviation to proceed)")
        return 2

    limit_subjects = int(args.limit_subjects) if args.limit_subjects else None
    records: list[protocol.WindowResult] = []
    reference_audit: list[dict] = []
    traces: list[dict] = []
    for record in inv["records"]:
        if limit_subjects is not None and record["subject"] > limit_subjects:
            continue
        ecg_path = Path(record["ecg"]["path"])
        ecg = adapter.load_ecg(ecg_path)
        fs = float(record["ecg"]["declared_fs_hz"])

        # Decode every ROI first so all three share one window grid (identical
        # recordings and windows regardless of which ROI decodes fastest).
        roi_traces: dict[str, dict] = {}
        grids: dict[tuple, float] = {}
        for roi in protocol.ROIS:
            video = record["videos"].get(roi)
            if not video:
                continue
            trace = adapter.extract_roi_trace(Path(video["path"]), max_seconds=args.max_seconds)
            roi_traces[roi] = trace
            duration = float(trace["timestamps_s"][-1] - trace["timestamps_s"][0])
            grids[(record["subject"], roi)] = duration
        if not roi_traces:
            continue
        duration = min(grids.values())
        starts = protocol.window_starts(duration, require_full=not args.allow_partial_window)

        # One reference evaluation per window start, computed once per subject.
        subject_refs: dict[float, dict] = {}
        for start in starts:
            window_ref = ecgref.window_reference_hr(
                ecg, fs, start, start + protocol.WINDOW_SECONDS,
                min_window_seconds=protocol.WINDOW_SECONDS,
            )
            entry = {"subject": record["subject"], "start_s": start, **window_ref}
            reference_audit.append(entry)
            subject_refs[start] = entry

        for roi, trace in roi_traces.items():
            t, rgb = trace["timestamps_s"], trace["rgb"]
            traces.append({
                "subject": record["subject"], "roi": roi, "path": trace["path"],
                "frame_count": trace["frame_count"], "measured_fps_hz": round(trace["measured_fps_hz"], 4),
                "dropped_frames": trace["dropped_frames"],
                "dropped_fraction": round(trace["dropped_fraction"], 6),
                "duration_s": round(float(t[-1] - t[0]), 3),
                "timestamp_jitter_fraction": round(trace["timestamp_jitter_fraction"], 6),
            })
            for index, start in enumerate(starts):
                ref = subject_refs[start]
                result = protocol.estimate_window(
                    record["subject"], roi, index, start, start + protocol.WINDOW_SECONDS,
                    t, rgb,
                    reference_bpm=ref.get("hr_bpm"),
                    reference_reasons=ref.get("rejection_reasons", []),
                )
                records.append(result)

    payload["status"] = "RUN"
    payload["results"] = protocol.aggregate(records)
    payload["windows"] = [r.to_dict() for r in records]
    payload["traces"] = traces
    payload["ecg_reference_audit"] = reference_audit
    payload["ecg_reference_summary"] = {
        "windows_total": len(reference_audit),
        "windows_ok": sum(1 for e in reference_audit if e["status"] == "ok"),
        "rejected_reasons": _count_tokens(reference_audit),
    }
    _write(output_dir / "rppg10_benchmark.json", payload)
    (output_dir / "rppg10_benchmark.md").write_text(protocol.markdown_report(payload), encoding="utf-8")
    print(f"wrote {output_dir / 'rppg10_benchmark.json'}")
    return 0


def _count_tokens(entries) -> dict:
    counts: dict[str, int] = {}
    for entry in entries:
        if entry.get("status") == "ok":
            continue
        for reason in entry.get("rejection_reasons", ["unknown"]):
            counts[reason] = counts.get(reason, 0) + 1
    return counts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    readiness = sub.add_parser("readiness", help="emit the no-data readiness assessment (NOT RUN)")
    readiness.add_argument("--output-dir", default="reports/rppg10")

    inspect = sub.add_parser("inspect", help="validate an authorized local copy (no benchmark)")
    inspect.add_argument("--data-root", required=True)
    inspect.add_argument("--output-dir", default="reports/rppg10")
    inspect.add_argument("--ecg-fs-hz", type=float, required=True,
                         help="ECG sampling rate declared by the provider documentation (never guessed)")
    inspect.add_argument("--probe-frames", action="store_true", help="decode a few frames per video")
    inspect.add_argument("--no-checksums", action="store_true")
    inspect.add_argument("--expected-subjects", type=int, nargs="*", default=None)
    inspect.add_argument("--exclude-subjects", type=int, nargs="*", default=None,
                         help="explicitly excluded participants (recorded with evidence in the report)")

    bench = sub.add_parser("benchmark", help="run the frozen protocol")
    bench.add_argument("--data-root", required=True)
    bench.add_argument("--output-dir", default="reports/rppg10")
    bench.add_argument("--ecg-fs-hz", type=float, required=True)
    bench.add_argument("--expected-subjects", type=int, nargs="*", default=None)
    bench.add_argument("--exclude-subjects", type=int, nargs="*", default=None,
                       help="explicitly excluded participants (an undocumented exclusion refuses to run "
                            "unless --allow-deviation is also given)")
    bench.add_argument("--limit-subjects", type=int, default=None, help="debug only: first N subject ids")
    bench.add_argument("--max-seconds", type=float, default=None, help="debug only: truncate each ROI video")
    bench.add_argument("--allow-partial-window", action="store_true",
                       help="include a trailing window shorter than the protocol length (debug only)")
    bench.add_argument("--allow-deviation", action="store_true",
                       help="proceed despite documented-attribute deviations (echoed into the report)")
    bench.add_argument("--i-have-verified-the-licence", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "readiness":
        return cmd_readiness(Path(args.output_dir))
    if args.command == "inspect":
        return cmd_inspect(args)
    return cmd_benchmark(args)


if __name__ == "__main__":
    raise SystemExit(main())
