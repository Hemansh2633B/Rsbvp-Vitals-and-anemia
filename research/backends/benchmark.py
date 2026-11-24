#!/usr/bin/env python3
"""RSBVP standardized benchmark CLI — identical recordings/windows for all backends.

Outputs (into --output-dir, default reports/research_backends):
  records.json     lossless canonical records (schema rsbvp.benchmark-record.v1)
  records.csv      scalar subset (waveforms excluded)
  waveforms.csv    per-sample waveform export (never fabricated; empty when missing)
  summary.json     availability, rejection accounting, latency, memory, pairing metrics
  summary.md       human-readable report

Reference measurements (when supplied) are used ONLY for the pairing metrics
in summary.*; they are never passed to any backend. Metrics are emitted only
with --reference-source, a provenance string for the authorized reference.

There is deliberately no mode that synthesizes or downloads datasets.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.backends.base import BackendUnavailable, BackendError  # noqa: E402
from research.backends import metrics as bench_metrics  # noqa: E402
from research.backends.metrics import memory_peak_mb  # noqa: E402
from research.backends import registry  # noqa: E402
from research.backends.schema import (  # noqa: E402
    read_records_json,
    write_records_csv,
    write_records_json,
    write_waveforms_csv,
)
from research.backends.run_info import run_report  # noqa: E402

SUMMARY_SCHEMA_VERSION = "rsbvp.benchmark-summary.v1"
ROIS = ("forehead", "left_cheek", "right_cheek", "cheeks", "multi_roi")


class InputError(ValueError):
    pass


def _read_trace(path: Path, recording_id: str, participant_id: str | None):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or "timestamp_s" not in rows[0]:
        raise InputError(f"{path}: requires a timestamp_s column")
    try:
        t = np.array([float(r["timestamp_s"]) for r in rows], dtype=float)
    except (TypeError, ValueError) as exc:
        raise InputError(f"{path}: non-numeric timestamp_s: {exc}") from exc
    if len(t) < 8 or not np.isfinite(t).all():
        raise InputError(f"{path}: at least 8 finite timestamps are required")
    if np.any(np.diff(t) <= 0):
        raise InputError(f"{path}: timestamps must be strictly increasing")
    fs = float(1.0 / np.median(np.diff(t)))
    drop = float(np.mean(np.diff(t) > 1.5 * np.median(np.diff(t))))

    def column(roi: str, channel: str):
        name = f"{roi}_{channel}"
        if name not in rows[0]:
            return None
        out = []
        for row in rows:
            raw = (row.get(name) or "").strip()
            try:
                out.append(float(raw) if raw else np.nan)
            except ValueError:
                out.append(np.nan)
        return np.array(out, dtype=float)

    rois: dict[str, np.ndarray] = {}
    for roi in ("forehead", "left_cheek", "right_cheek"):
        cols = [column(roi, ch) for ch in "rgb"]
        if all(c is not None for c in cols):
            rois[roi] = np.column_stack(cols)  # type: ignore[arg-type]
    if not rois:
        raise InputError(f"{path}: no ROI channel columns found (expected e.g. forehead_r/g/b)")
    # Derived ROIs, identical definitions to research/rppg/compare_algorithms.py.
    for name, members, required in (("cheeks", ("left_cheek", "right_cheek"), 1),
                                    ("multi_roi", ("forehead", "left_cheek", "right_cheek"), 2)):
        present = [rois[m] for m in members if m in rois]
        if not present:
            continue
        cube = np.stack(present)
        valid = np.isfinite(cube).all(axis=2)
        counts = valid.sum(axis=0)
        sums = np.nansum(cube, axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            mean = np.divide(sums, counts[:, None], out=np.full((cube.shape[1], 3), np.nan),
                             where=counts[:, None] > 0)
        mean[counts < required] = np.nan
        rois[name] = mean

    reference_rows = None
    if "reference_hr_bpm" in rows[0]:
        reference_rows = np.array([
            float(r["reference_hr_bpm"]) if (r.get("reference_hr_bpm") or "").strip() else np.nan
            for r in rows
        ], dtype=float)

    from research.backends.base import RecordingInput
    recording = RecordingInput(
        recording_id=recording_id,
        timestamps_s=t,
        rois=rois,
        sampling_rate_hz=float(fs),
        participant_id=participant_id,
        source_path=str(path),
    )
    return recording, drop, reference_rows


def _load_inputs(args):
    inputs: list[tuple[Path, str, str | None]] = []
    if args.manifest:
        manifest = Path(args.manifest)
        with manifest.open(newline="", encoding="utf-8-sig") as handle:
            for line, row in enumerate(csv.DictReader(handle), start=2):
                rid = (row.get("recording_id") or "").strip()
                csv_path = (row.get("csv_path") or "").strip()
                if not rid or not csv_path:
                    raise InputError(f"{manifest} line {line}: recording_id and csv_path are required")
                path = Path(csv_path)
                path = path if path.is_absolute() else (manifest.parent / path)
                inputs.append((path, rid, (row.get("participant_id") or "").strip() or None))
        return inputs
    path = Path(args.input)
    if not path.is_file():
        raise InputError(f"input not found: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        first = (next(csv.reader(handle), []) or [])
    if {"recording_id", "csv_path"}.issubset(set(first)):
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for line, row in enumerate(csv.DictReader(handle), start=2):
                p = Path(row["csv_path"])
                p = p if p.is_absolute() else (path.parent / p)
                inputs.append((p, row["recording_id"], (row.get("participant_id") or "").strip() or None))
        return inputs
    recording_id = args.recording_id or path.stem
    return [(path, recording_id, args.participant_id)]


def _reference_windows_from_trace(t, reference_rows, window_seconds, step_seconds):
    """Median finite reference per analysis window (same grid as backends)."""
    if reference_rows is None:
        return {}
    from research.backends.base import iter_windows
    n = len(t)
    fs_est = float(1.0 / np.median(np.diff(t)))
    out = {}
    for start, stop in iter_windows(n, fs_est, window_seconds, step_seconds):
        seg = reference_rows[start:stop]
        finite = seg[np.isfinite(seg)]
        if len(finite) >= max(4, int(0.5 * len(seg))):
            out[float(t[start])] = float(np.median(finite))
    return out


def _load_reference_windows(args, recordings):
    reference_by_key: dict[str, float] = {}
    if args.reference_windows:
        path = Path(args.reference_windows)
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            required = {"recording_id", "window_start_s", "reference_hr_bpm"}
            missing = required - set(reader.fieldnames or ())
            if missing:
                raise InputError(f"{path}: missing columns: {', '.join(sorted(missing))}")
            for line, row in enumerate(reader, start=2):
                try:
                    key = bench_metrics.window_key(row["recording_id"].strip(), float(row["window_start_s"]))
                    reference_by_key[key] = float(row["reference_hr_bpm"])
                except (TypeError, ValueError) as exc:
                    raise InputError(f"{path} line {line}: {exc}") from exc
        return reference_by_key
    for recording, _drop, reference_rows in recordings:
        if reference_rows is None:
            continue
        per_window = _reference_windows_from_trace(
            recording.timestamps_s, reference_rows, args.window_seconds, args.step_seconds)
        for start_s, bpm in per_window.items():
            reference_by_key[bench_metrics.window_key(recording.recording_id, start_s)] = bpm
    return reference_by_key


def run_benchmark(args) -> dict:
    inputs = _load_inputs(args)
    if not inputs:
        raise InputError("no recordings selected")

    recordings = []
    drops = {}
    for path, rid, participant in inputs:
        recording, drop, reference_rows = _read_trace(path, rid, participant)
        recordings.append((recording, drop, reference_rows))
        drops[recording.recording_id] = drop

    if args.reference_source is None and (args.reference_windows
                                          or any(r[2] is not None for r in recordings)):
        raise InputError("reference windows supplied but --reference-source provenance string is missing")

    reference_by_key = {}
    if args.reference_source:
        reference_by_key = _load_reference_windows(args, recordings)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    backends = [name.strip() for name in args.backends.split(",") if name.strip()]
    if not backends:
        raise InputError("--backends must name at least one backend")

    all_records = []
    backend_entries = []
    backend_errors = []
    for name in backends:
        try:
            backend = registry.get_backend(name)
        except KeyError as exc:
            raise InputError(str(exc)) from exc
        usable, reason = backend.available()
        if not usable:
            backend_entries.append({"backend": backend.info().as_dict(), "status": "unavailable",
                                    "reason": reason, "latency_s": None, "memory_peak_mb": None})
            continue
        started = time.perf_counter()
        try:
            algorithms = args.algorithms.split(",") if args.algorithms else None
            for recording, _drop, _ref in recordings:
                all_records.extend(
                    backend.run(recording, algorithms=algorithms,
                                window_seconds=args.window_seconds,
                                step_seconds=args.step_seconds,
                                passband_hz=(args.passband_low, args.passband_high)).records)
        except BackendUnavailable as exc:
            backend_entries.append({"backend": backend.info().as_dict(), "status": "unavailable",
                                    "reason": str(exc), "latency_s": None, "memory_peak_mb": None})
            continue
        except BackendError as exc:
            backend_errors.append({"backend": name, "error": str(exc)})
            continue
        elapsed = time.perf_counter() - started
        backend_entries.append({
            "backend": backend.info().as_dict(),
            "status": "completed",
            "latency_s": elapsed,
            "memory_peak_mb": memory_peak_mb(),
        })

    configuration = {
        "window_seconds": args.window_seconds,
        "step_seconds": args.step_seconds,
        "passband_hz": [args.passband_low, args.passband_high],
        "algorithms_requested": (args.algorithms.split(",") if args.algorithms else None),
        "backends_requested": list(backends),
    }
    run = run_report(configuration=configuration,
                     manifest_path=(Path(args.manifest) if args.manifest else None))

    window_records = [r for r in all_records if r.backend_output_type == "window"]
    aggregate_records = [r for r in all_records if r.backend_output_type == "aggregate"]

    # Availability accounting per (backend, algorithm).
    availability: dict[str, dict] = {}
    for record in all_records:
        key = f"{record.backend}:{record.algorithm}"
        bucket = availability.setdefault(key, {"windows_total": 0, "windows_with_estimate": 0,
                                               "rejected_or_unavailable": 0})
        if record.backend_output_type != "window":
            bucket["aggregate_records"] = bucket.get("aggregate_records", 0) + 1
            continue
        bucket["windows_total"] += 1
        if record.estimated_hr_bpm is not None:
            bucket["windows_with_estimate"] += 1
        head = (record.signal_quality or "").split(":", 1)[0]
        if head in {"rejected", "unavailable"}:
            bucket["rejected_or_unavailable"] += 1
    for key, bucket in availability.items():
        total = bucket["windows_total"]
        bucket["estimate_availability"] = (bucket["windows_with_estimate"] / total) if total else None

    # Pairing metrics (identical windows for every backend).
    pairing: dict[str, dict] = {}
    if reference_by_key:
        groups: dict[tuple[str, str], list] = {}
        for record in window_records:
            if record.estimated_hr_bpm is None:
                continue
            key = bench_metrics.window_key(record.recording_id, record.timestamp_s)
            reference = reference_by_key.get(key)
            if reference is not None:
                groups.setdefault((record.backend, record.algorithm), []).append((reference, record))
        for (backend_name, algorithm), items in groups.items():
            pairs = [(reference, record.estimated_hr_bpm) for reference, record in items]
            participant_pairs: dict[str, list[tuple[float, float]]] = {}
            recording_pairs: dict[str, list[tuple[float, float]]] = {}
            for reference, record in items:
                pair = (float(reference), float(record.estimated_hr_bpm))
                recording_pairs.setdefault(record.recording_id, []).append(pair)
                if record.participant_id:
                    participant_pairs.setdefault(record.participant_id, []).append(pair)
            pairing[f"{backend_name}:{algorithm}"] = {
                "pooled_window_metrics_descriptive_only": bench_metrics.error_metrics(pairs),
                "recording_metrics": {rid: bench_metrics.error_metrics(p) for rid, p in recording_pairs.items()},
                "participant_metrics": {pid: bench_metrics.error_metrics(p) for pid, p in participant_pairs.items()},
                "participant_bootstrap": bench_metrics.participant_bootstrap_mae(participant_pairs),
                "windows_paired": len(pairs),
                "reference_source": args.reference_source,
            }

    write_records_json(all_records, output_dir / "records.json")
    write_records_csv(all_records, output_dir / "records.csv")
    write_waveforms_csv(all_records, output_dir / "waveforms.csv")

    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "run": run,
        "reference_metrics_authorized": bool(args.reference_source),
        "reference_source": args.reference_source,
        "reference_windows_available": len(reference_by_key),
        "inputs": [{"recording_id": r.recording_id, "source": r.source_path,
                    "participant_id": r.participant_id,
                    "sampling_rate_hz": r.sampling_rate_hz,
                    "dropped_interval_fraction": drops.get(r.recording_id)} for r, _d, _ref in recordings],
        "windowing": {"window_seconds": args.window_seconds, "step_seconds": args.step_seconds},
        "passband_hz": [args.passband_low, args.passband_high],
        "backends": backend_entries,
        "backend_errors": backend_errors,
        "algorithms_requested": (args.algorithms.split(",") if args.algorithms else None),
        "availability": availability,
        "pairing_metrics": pairing,
        "aggregate_records": [r.to_dict(include_waveform=False) for r in aggregate_records],
        "notes": [
            "Identical recordings and identical time windows were used for every in-process backend.",
            "Native and reference backends share the same passband (0.7-3.5 Hz default) and HR estimator (hann-periodogram-v1); differences reflect the transform, not the estimator.",
            "Overlapping windows are correlated; pooled metrics are descriptive only. Prefer participant-level metrics and the participant bootstrap CI.",
            "Subprocess backends (rppg_toolbox, pyvhr) report aggregate records only and are excluded from window-level pairing statistics.",
            "Reference measurements were never passed to any backend; they were joined after prediction.",
            "Synthetic fixtures are software verification only; no physiological validation is claimed.",
        ],
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (output_dir / "summary.md").write_text(_markdown_report(summary), encoding="utf-8")
    return summary


def _markdown_report(summary: dict) -> str:
    lines = [
        "# RSBVP research backend benchmark",
        "",
        f"- Schema: `{summary['schema_version']}`",
        f"- Reference metrics authorized: {'YES — ' + str(summary['reference_source']) if summary['reference_metrics_authorized'] else 'NO (--reference-source not supplied)'}",
        f"- Windowing: {summary['windowing']}",
        f"- Passband (Hz): {summary['passband_hz']}",
        "",
        "> Synthetic or aggregate outputs in this file are software verification artifacts.",
        "> They are not physiological validation, not clinical evidence, and not a ranking of medical devices.",
        "",
        "## Run environment",
        "",
        f"- Software: {summary['run']['software']['name']} {summary['run']['software']['version']} (commit {summary['run']['software']['commit']})",
        f"- Python {summary['run']['environment']['python']} ({summary['run']['environment']['implementation']}) · numpy {summary['run']['environment']['numpy']} · scipy {summary['run']['environment']['scipy']} · platform {summary['run']['environment']['platform']}",
        f"- Generated (UTC): {summary['run']['generated_utc']}",
        f"- Configuration: window={summary['run']['configuration']['window_seconds']}s / step={summary['run']['configuration']['step_seconds']}s · passband={summary['run']['configuration']['passband_hz']} Hz",
        f"- Manifest SHA-256: {summary['run']['manifest_sha256'] or 'not applicable (single-trace input)'}",
        "",
        "## Inputs",
        "",
        "| Recording | Participant | fs (Hz) | Dropped intervals |",
        "|---|---|---|---|",
    ]
    for item in summary["inputs"]:
        drop = item["dropped_interval_fraction"]
        lines.append(f"| {item['recording_id']} | {item['participant_id'] or '—'} | {item['sampling_rate_hz']:.3f} | {drop if drop is not None else '—'} |")
    lines += ["", "## Backends", "", "| Backend | Status | License | Latency (s) |", "|---|---|---|---|"]
    for entry in summary["backends"]:
        info = entry["backend"]
        latency = "—" if entry.get("latency_s") is None else f"{entry['latency_s']:.3f}"
        lines.append(f"| {info['name']} | {entry['status']} | {info['license_id']} | {latency} |")
    lines += ["", "## Availability and rejection accounting", "",
              "| Backend:algorithm | Windows | With estimate | Availability | Rejected/unavailable |",
              "|---|---|---|---|---|"]
    for key, bucket in sorted(summary["availability"].items()):
        availability = bucket.get("estimate_availability")
        lines.append(f"| {key} | {bucket['windows_total']} | {bucket['windows_with_estimate']} | "
                     f"{availability if availability is None else f'{availability:.3f}'} | "
                     f"{bucket['rejected_or_unavailable']} |")
    if summary["pairing_metrics"]:
        lines += ["", "## Paired comparison (identical windows)", "",
                  "*Pooled descriptive statistics; participant-level metrics are primary. Overlapping windows are correlated.*", "",
                  "| Backend:algorithm | n | MAE | RMSE | Bias | LoA 95% | Pearson r |",
                  "|---|---|---|---|---|---|---|"]
        for key, item in sorted(summary["pairing_metrics"].items()):
            m = item["pooled_window_metrics_descriptive_only"]
            fmt = lambda v: "—" if v is None else f"{v:.2f}"  # noqa: E731
            lines.append(f"| {key} | {m['n_pairs']} | {fmt(m['mae_bpm'])} | {fmt(m['rmse_bpm'])} | "
                         f"{fmt(m['bias_bpm'])} | {fmt(m['loa_lower_95_bpm'])} to {fmt(m['loa_upper_95_bpm'])} | "
                         f"{fmt(m['pearson_r'])} |")
    lines += ["", "## Notes", ""] + [f"- {note}" for note in summary["notes"]] + [""]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", nargs="?", help="RGB trace CSV or auto-detected manifest CSV")
    parser.add_argument("--manifest", help="Explicit manifest CSV: recording_id,csv_path[,participant_id]")
    parser.add_argument("--recording-id", help="Recording ID for single-trace input (default: filename stem)")
    parser.add_argument("--participant-id", help="Participant pseudonym for single-trace input")
    parser.add_argument("--backends", default="rsbvp_native,rsbvp_reference",
                        help="Comma-separated backends (rsbvp_native, rsbvp_reference, rppg_toolbox, pyvhr, neural_tscan, ...)")
    parser.add_argument("--algorithms", help="Comma-separated algorithm subset (default: all supported by each backend)")
    parser.add_argument("--window-seconds", type=float, default=12.0)
    parser.add_argument("--step-seconds", type=float, default=6.0)
    parser.add_argument("--passband-low", type=float, default=0.7)
    parser.add_argument("--passband-high", type=float, default=3.5)
    parser.add_argument("--reference-source", help="Provenance string for the authorized reference data; enables pairing metrics")
    parser.add_argument("--reference-windows", help="CSV: recording_id,window_start_s,reference_hr_bpm")
    parser.add_argument("--output-dir", default="reports/research_backends")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.manifest and not args.input:
        parser.error("provide an input trace CSV (or --manifest)")
    try:
        summary = run_benchmark(args)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    completed = sum(1 for b in summary["backends"] if b["status"] == "completed")
    print(json.dumps({
        "recordings": len(summary["inputs"]),
        "backends_completed": completed,
        "backends_total": len(summary["backends"]),
        "output_dir": str(Path(args.output_dir).resolve()),
    }, indent=2))
    if completed == 0:
        print("no backend completed; see output_dir/summary.json for availability reasons", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
