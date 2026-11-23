#!/usr/bin/env python3
"""Evaluate local timestamped RGB traces against independently derived reference HR.

Requires explicit, locally stored data and verified provenance/terms in a manifest.
No downloads or uploads are performed. Reports are descriptive research outputs.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research.rppg.dataset_io import data_root, load_reference, read_manifest, reference_hr_windows
from research.rppg.compare_algorithms import evaluate_recording


def _metrics(pairs: list[tuple[float, float]]) -> dict[str, object]:
    if not pairs:
        return {"n_windows": 0, "mae_bpm": None, "rmse_bpm": None, "mean_bias_bpm": None,
                "loa_lower_95_bpm": None, "loa_upper_95_bpm": None, "pearson_r": None}
    ref = np.asarray([p[0] for p in pairs]); est = np.asarray([p[1] for p in pairs]); err = est - ref
    bias = float(np.mean(err)); sd = float(np.std(err, ddof=1)) if len(err) > 1 else None
    corr = float(np.corrcoef(ref, est)[0, 1]) if len(err) > 1 and np.std(ref) > 0 and np.std(est) > 0 else None
    return {"n_windows": len(err), "mae_bpm": float(np.mean(np.abs(err))),
            "rmse_bpm": float(np.sqrt(np.mean(err**2))), "mean_bias_bpm": bias,
            "loa_lower_95_bpm": bias - 1.96 * sd if sd is not None else None,
            "loa_upper_95_bpm": bias + 1.96 * sd if sd is not None else None,
            "pearson_r": corr}


def _participant_bootstrap(per_participant: dict[str, list[tuple[float, float]]], *, seed: int = 2026, n_boot: int = 2000) -> dict[str, object] | None:
    ids = sorted(per_participant)
    if len(ids) < 2:
        return None
    rng = np.random.default_rng(seed)
    participant_mae = np.asarray([np.mean([abs(e-r) for r, e in per_participant[k]]) for k in ids])
    samples = np.mean(rng.choice(participant_mae, size=(n_boot, len(ids)), replace=True), axis=1)
    return {"participants": len(ids), "mae_mean_of_participant_mae_bpm": float(participant_mae.mean()),
            "mae_ci95_bpm": [float(np.quantile(samples, .025)), float(np.quantile(samples, .975))],
            "method": "participant-resampled bootstrap; each participant contributes one mean absolute error"}


def evaluate_manifest(manifest: Path, root: Path, *, window_seconds: float = 12, step_seconds: float = 6,
                      max_reference_gap_s: float = .25) -> dict[str, object]:
    rows = read_manifest(manifest, root)
    recordings: list[dict[str, object]] = []
    all_names: set[str] = set()
    for row in rows:
        trace_path = (root / row["trace_csv"]).resolve()
        trace = evaluate_recording(trace_path, recording_id=row["recording_id"],
                                   window_seconds=window_seconds, step_seconds=step_seconds)
        reference = load_reference(row, root)
        starts = [float(w["start_s"]) for w in trace["windows"]]
        refs = reference_hr_windows(reference, starts, window_seconds=window_seconds,
                                    step_seconds=step_seconds, max_gap_seconds=max_reference_gap_s)
        windows = []
        for signal_window, ref_window in zip(trace["windows"], refs):
            estimates = signal_window["estimates_bpm"]
            all_names.update(estimates)
            windows.append({**signal_window, "reference": ref_window,
                            "rejected_estimates": {k: "estimate_unavailable" for k, v in estimates.items() if v is None}})
        recordings.append({"dataset": row["dataset"], "dataset_version": row["dataset_version"],
                           "participant_id": row["participant_id"], "recording_id": row["recording_id"],
                           "reference_type": reference.signal_type,
                           "reference_sampling_hz": reference.sampling_hz,
                           "reference_time_offset_s": reference.offset_s,
                           "signal_sampling_hz": trace["sampling_rate_hz"],
                           "dropped_interval_fraction": trace["dropped_interval_fraction"],
                           "windows": windows})
    summary: dict[str, object] = {}
    for name in sorted(all_names):
        pairs: list[tuple[float, float]] = []
        participant_pairs: dict[str, list[tuple[float, float]]] = {}
        per_recording: dict[str, object] = {}
        total, ref_valid, usable, paired = 0, 0, 0, 0
        rejection_counts: dict[str, int] = {}
        for rec in recordings:
            rpairs: list[tuple[float, float]] = []
            for win in rec["windows"]:
                total += 1
                ref_info = win["reference"]
                if ref_info["valid"]:
                    ref_valid += 1
                else:
                    reason = str(ref_info["rejection_reason"])
                    rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
                estimate = win["estimates_bpm"].get(name)
                if estimate is not None:
                    usable += 1
                if ref_info["valid"] and estimate is not None:
                    pair = (float(ref_info["reference_hr_bpm"]), float(estimate))
                    pairs.append(pair); rpairs.append(pair); paired += 1
                    participant_pairs.setdefault(str(rec["participant_id"]), []).append(pair)
            per_recording[str(rec["recording_id"])] = _metrics(rpairs)
        per_participant = {pid: _metrics(p) for pid, p in participant_pairs.items()}
        summary[name] = {"pooled_window_metrics_descriptive_only": _metrics(pairs),
                         "recording_metrics": per_recording, "participant_metrics": per_participant,
                         "participant_bootstrap": _participant_bootstrap(participant_pairs),
                         "windows_total": total, "reference_valid_windows": ref_valid,
                         "windows_with_usable_estimate": usable, "paired_valid_windows": paired,
                         "estimate_coverage_all_windows": usable / total if total else None,
                         "paired_coverage_all_windows": paired / total if total else None,
                         "quality_gate_coverage": None,
                         "quality_gate_coverage_note": "Not available: RGB CSV has no per-window browser gate state. Estimate availability is not a substitute for quality-gate coverage.",
                         "reference_rejection_reasons": rejection_counts,
                         "note": "Overlapping windows are correlated and are not independent participants."}
    return {"status": "COMPLETED", "dataset": rows[0]["dataset"],
            "dataset_versions": sorted({r["dataset_version"] for r in rows}),
            "recording_count": len(recordings),
            "participant_count": len({r["participant_id"] for r in rows}),
            "synchronization": "reference timestamps plus manifest time_offset_s; no offset is inferred",
            "windowing": {"window_seconds": window_seconds, "step_seconds": step_seconds,
                          "reference_max_gap_seconds": max_reference_gap_s},
            "recordings": recordings, "metrics_by_algorithm_roi": summary,
            "limitations": ["Research software evaluation; not clinical validation.",
                            "Dataset mapping, citation, license and synchronization remain user-attested.",
                            "Participant pseudonyms are used in machine-readable output; remove them before sharing."]}


def markdown_report(result: dict[str, object], command: str) -> str:
    if result.get("status") != "COMPLETED":
        return "# rPPG validation\n\n**NOT RUN — DATASET NOT AVAILABLE**\n\n" + str(result.get("reason", "No locally configured dataset.")) + "\n"
    rows = ["# Local rPPG validation report", "", f"- Dataset/version: {result['dataset']} / {', '.join(result['dataset_versions'])}",
            f"- Recordings: {result['recording_count']}; participants (pseudonymous IDs): {result['participant_count']}",
            f"- Synchronization: {result['synchronization']}", f"- Windowing: {result['windowing']}",
            "- Methods/ROIs: Green, POS, CHROM; forehead, left/right cheek, both cheeks, multi-ROI (where present).",
            "- Missing reference samples and excessive gaps invalidate affected reference windows; no long-gap extrapolation.",
            "", "## Results", "", "| Estimate | Paired windows | Usable estimate coverage* | MAE BPM | RMSE BPM | Bias BPM | 95% LoA BPM | Participant MAE bootstrap CI |",
            "|---|---:|---:|---:|---:|---:|---:|---|"]
    for name, item in result["metrics_by_algorithm_roi"].items():
        m = item["pooled_window_metrics_descriptive_only"]
        fmt = lambda x: "—" if x is None else f"{x:.2f}"
        boot = item['participant_bootstrap']
        ci = "—" if boot is None else f"{boot['mae_ci95_bpm'][0]:.2f} to {boot['mae_ci95_bpm'][1]:.2f} (n={boot['participants']})"
        rows.append(f"| {name} | {item['paired_valid_windows']} | {fmt(item['estimate_coverage_all_windows'])} | {fmt(m['mae_bpm'])} | {fmt(m['rmse_bpm'])} | {fmt(m['mean_bias_bpm'])} | {fmt(m['loa_lower_95_bpm'])} to {fmt(m['loa_upper_95_bpm'])} | {ci} |")
    rows += ["", "*Usable estimate availability is not quality-gate coverage. The RGB trace format lacks per-window browser quality-gate state, so quality-gate coverage is NOT AVAILABLE from this input.", "", "## Limitations", *[f"- {x}" for x in result["limitations"]],
             "- Overlapping windows are correlated; participant-level results are reported separately.",
             "- No anemia inference, blood pressure measurement, clinical accuracy, or ECG-HRV claim.",
             "", "## Reproduction", "", "```sh", command, "```", ""]
    return "\n".join(rows)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest", type=Path)
    p.add_argument("--data-root", type=Path)
    p.add_argument("--output-dir", type=Path, default=Path("reports/validation"))
    p.add_argument("--window-seconds", type=float, default=12)
    p.add_argument("--step-seconds", type=float, default=6)
    p.add_argument("--max-reference-gap-seconds", type=float, default=.25)
    args = p.parse_args()
    root = data_root(args.data_root)
    result = evaluate_manifest(args.manifest, root, window_seconds=args.window_seconds,
                               step_seconds=args.step_seconds, max_reference_gap_s=args.max_reference_gap_seconds)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "validation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    command = f"python research/rppg/validate_dataset.py {args.manifest} --data-root {root} --window-seconds {args.window_seconds} --step-seconds {args.step_seconds}"
    (args.output_dir / "validation.md").write_text(markdown_report(result, command), encoding="utf-8")
    print(f"Wrote validation report to {args.output_dir.resolve()}; no data uploaded.")

if __name__ == "__main__":
    main()
