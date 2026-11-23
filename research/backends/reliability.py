#!/usr/bin/env python3
"""Deterministic synthetic degradation suite for reliability analysis.

Generates synthetic 60 s RGB traces (70 BPM embedded pulse, seeded noise) and
applies documented degradations (low illumination, elevated noise, motion
transients, frame drops, low frame rates, ROI dropout). Runs the in-process
backends on identical windows and reports availability, rejection reasons and
error against the synthetic truth.

SYNTHETIC SOFTWARE VERIFICATION ONLY. These results say nothing about
real cameras, skin, illumination or physiology. They verify that quality gates
reject or flag what they should and that deterministic pipelines behave
reproducibly under controlled corruption.

There is deliberately no mode that loads or synthesizes real datasets.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.backends import metrics as bench_metrics  # noqa: E402
from research.backends.base import RecordingInput  # noqa: E402
from research.backends import registry  # noqa: E402

TRUTH_BPM = 70.0
CONDITIONS = (
    "baseline",
    "low_light_gain_0.30",
    "low_light_gain_0.15",
    "high_noise_sigma_3.0",
    "motion_transients",
    "frame_drops_20pct",
    "low_fs_15hz",
    "low_fs_10hz",
    "roi_dropout_left_cheek",
)


def generate_trace(condition: str, *, duration_s: float, fs: float, seed: int):
    """Return (timestamps, rois dict) for one synthetic condition."""
    if condition == "low_fs_15hz":
        fs = 15.0
    elif condition == "low_fs_10hz":
        fs = 10.0

    rng = np.random.default_rng(seed)
    n = int(round(duration_s * fs))
    t = np.arange(n, dtype=float) / fs
    phase = 2.0 * np.pi * (TRUTH_BPM / 60.0) * t

    gain = 1.0
    noise_sigma = 1.0
    if condition == "low_light_gain_0.30":
        gain, noise_sigma = 0.30, 1.0
    elif condition == "low_light_gain_0.15":
        gain, noise_sigma = 0.15, 1.0
    elif condition == "high_noise_sigma_3.0":
        noise_sigma = 3.0

    # skin-like background levels (counts, 0–255) per ROI; pulse rides strongest on green
    bases = {"forehead": (148.0, 172.0, 158.0), "left_cheek": (132.0, 158.0, 145.0), "right_cheek": (140.0, 166.0, 152.0)}

    def roi_trace(base, pulse_amp, phase_shift, rng):
        # illumination scales the optical signal; read noise is NOT scaled with it,
        # so low light genuinely reduces SNR (unlike a pure digital gain)
        r = (base[0] + pulse_amp * 0.55 * np.sin(phase + phase_shift + 0.2)) * gain
        g = (base[1] + pulse_amp * np.sin(phase + phase_shift)) * gain
        b = (base[2] + pulse_amp * 0.30 * np.sin(phase + phase_shift + 0.4)) * gain
        rgb = np.stack([r, g, b], axis=1)
        return rgb + rng.normal(0.0, noise_sigma, rgb.shape)

    rois = {
        "forehead": roi_trace(bases["forehead"], 9.0, 0.0, rng),
        "left_cheek": roi_trace(bases["left_cheek"], 6.0, 0.15, rng),
        "right_cheek": roi_trace(bases["right_cheek"], 6.0, -0.1, rng),
    }

    if condition == "motion_transients":
        # brief additive transients every ~7 s (seeded), same pattern across channels
        for onset in (4.0, 11.0, 19.0, 27.0, 35.0, 43.0, 51.0):
            width = int(round(0.28 * fs))
            start = int(round((onset + rng.uniform(-0.5, 0.5)) * fs))
            for roi in rois.values():
                roi[start:start + width] += rng.uniform(18.0, 30.0)

    if condition == "frame_drops_20pct":
        keep = rng.random(n) >= 0.20
        keep[0] = keep[-1] = True
        t = t[keep]
        rois = {name: values[keep] for name, values in rois.items()}

    if condition == "roi_dropout_left_cheek":
        rois["left_cheek"] = np.full_like(rois["left_cheek"], np.nan)

    return t, rois, fs


def evaluate_condition(condition: str, *, duration_s: float, fs: float, seed: int,
                       window_seconds: float, step_seconds: float,
                       backends: tuple[str, ...]) -> dict:
    t, rois, effective_fs = generate_trace(condition, duration_s=duration_s, fs=fs, seed=seed)
    # timestamps must be strictly increasing; frame_drops keeps that by construction
    recording = RecordingInput(
        recording_id=f"synthetic_{condition}",
        timestamps_s=t,
        rois=rois,
        sampling_rate_hz=float(1.0 / np.median(np.diff(t))),
        participant_id=None,
        source_path=None,
        dataset="synthetic",
    )
    result = {
        "condition": condition,
        "effective_fs_hz": float(recording.sampling_rate_hz),
        "n_samples": int(len(t)),
        "backends": {},
    }
    for backend_name in backends:
        backend = registry.get_backend(backend_name)
        usable, reason = backend.available()
        if not usable:
            result["backends"][backend_name] = {"status": "unavailable", "reason": reason}
            continue
        started = time.perf_counter()
        run = backend.run(recording, window_seconds=window_seconds, step_seconds=step_seconds)
        wall_s = time.perf_counter() - started
        summary = bench_metrics.availability_summary(run.records)
        pairs = [(TRUTH_BPM, r.estimated_hr_bpm) for r in run.records
                 if r.estimated_hr_bpm is not None]
        summary["error_vs_synthetic_truth"] = bench_metrics.error_metrics(pairs)
        summary["latency_s_total"] = wall_s
        summary["per_algorithm"] = {}
        for algo in sorted({r.algorithm for r in run.records}):
            subset = [r for r in run.records if r.algorithm == algo]
            algo_summary = bench_metrics.availability_summary(subset)
            algo_pairs = [(TRUTH_BPM, r.estimated_hr_bpm) for r in subset if r.estimated_hr_bpm is not None]
            algo_summary["error_vs_synthetic_truth"] = bench_metrics.error_metrics(algo_pairs)
            summary["per_algorithm"][algo] = algo_summary
        summary["status"] = "completed"
        result["backends"][backend_name] = summary
    return result


def render_markdown(report: dict) -> str:
    lines = [
        "# Synthetic degradation suite — reliability software verification",
        "",
        f"- Schema: `{report['schema']}`",
        f"- Truth: {TRUTH_BPM} BPM (synthetic pulse; no physiology)",
        f"- Windowing: {report['windowing']}",
        f"- Seed: {report['seed']} · duration {report['duration_s']} s · base fs {report['fs']} Hz",
        "",
        "> **SYNTHETIC SOFTWARE VERIFICATION ONLY — NOT PHYSIOLOGICAL VALIDATION.**",
        "> These measurements exercise the pipelines and quality gates under controlled",
        "> corruption. They say nothing about real cameras, skin, motion or patients.",
        "",
        "| Condition | Backend | Algo | Availability | Quality-OK | Rejected/unavailable | MAE vs truth (BPM) |",
        "|---|---|---|---|---|---|---|",
    ]
    for condition in report["conditions"]:
        backends = condition["backends"]
        for backend_name, summary in backends.items():
            if summary.get("status") != "completed":
                lines.append(f"| {condition['condition']} | {backend_name} | — | unavailable ({summary.get('reason')}) | — | — |")
                continue
            for algo, algo_summary in summary["per_algorithm"].items():
                err = algo_summary["error_vs_synthetic_truth"]
                mae = err["mae_bpm"]
                availability = algo_summary["estimate_availability"]
                availability_cell = f"{availability:.3f}" if availability is not None else "—"
                ok = algo_summary["quality_ok_fraction"]
                ok_cell = f"{ok:.3f}" if ok is not None else "—"
                mae_cell = f"{mae:.4f}" if mae is not None else "—"
                lines.append(
                    f"| {condition['condition']} | {backend_name} | {algo} "
                    f"| {availability_cell} | {ok_cell} | {algo_summary['windows_rejected_or_unavailable']} | {mae_cell} |"
                )
    lines += ["", "## Rejection reasons (aggregate)", ""]
    for condition in report["conditions"]:
        for backend_name, summary in condition["backends"].items():
            if summary.get("status") != "completed":
                continue
            reasons = summary["rejection_or_unavailability_reasons"]
            if reasons:
                lines.append(f"- {condition['condition']} · {backend_name}: {reasons}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--output-dir", type=Path, default=Path("reports/research_validation/synthetic"))
    parser.add_argument("--duration-s", type=float, default=60.0)
    parser.add_argument("--fs", type=float, default=30.0)
    parser.add_argument("--window-seconds", type=float, default=12.0)
    parser.add_argument("--step-seconds", type=float, default=6.0)
    parser.add_argument("--seed", type=int, default=20261123)
    parser.add_argument("--conditions", default=",".join(CONDITIONS),
                        help="comma-separated subset of: " + ", ".join(CONDITIONS))
    parser.add_argument("--backends", default="rsbvp_native,rsbvp_reference")
    args = parser.parse_args(argv)

    requested = [c.strip() for c in args.conditions.split(",") if c.strip()]
    unknown = [c for c in requested if c not in CONDITIONS]
    if unknown:
        print(f"unknown conditions: {unknown}; known: {list(CONDITIONS)}", file=sys.stderr)
        return 2
    backends = tuple(b.strip() for b in args.backends.split(",") if b.strip())

    report = {
        "schema": "rsbvp.reliability-synthetic.v1",
        "truth_bpm": TRUTH_BPM,
        "duration_s": args.duration_s,
        "fs": args.fs,
        "windowing": {"window_seconds": args.window_seconds, "step_seconds": args.step_seconds},
        "seed": args.seed,
        "conditions": [
            evaluate_condition(c, duration_s=args.duration_s, fs=args.fs, seed=args.seed,
                               window_seconds=args.window_seconds, step_seconds=args.step_seconds,
                               backends=backends)
            for c in requested
        ],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "reliability_synthetic.json"
    md_path = args.output_dir / "reliability_synthetic.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"conditions": len(report["conditions"]), "output": str(json_path)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
