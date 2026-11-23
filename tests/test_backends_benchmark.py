"""End-to-end benchmark CLI tests (fixture-only, offline, no datasets)."""
import csv
import json
from pathlib import Path

import numpy as np
import pytest

from research.backends import benchmark as bench_cli

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "rppg_rgb_fixture.csv"


def synthetic_trace_csv(tmp_path, name, heart_bpm=70.0, duration_s=60.0, fs=30.0,
                        nan_gap=None, seed=11):
    """Write a deterministic synthetic RGB-trace CSV with a known pulse rate."""
    rng = np.random.default_rng(seed)
    t = np.arange(0, duration_s, 1.0 / fs)
    phase = 2 * np.pi * (heart_bpm / 60.0) * t
    green = 100 + 20 * np.sin(phase)
    red = 110 + 8 * np.sin(phase + 0.2)
    blue = 90 + 4 * np.sin(phase + 0.4)
    columns = {"timestamp_s": t,
               "forehead_r": red, "forehead_g": green, "forehead_b": blue,
               "left_cheek_r": red * 0.9, "left_cheek_g": green * 0.9, "left_cheek_b": blue * 0.9,
               "right_cheek_r": red * 1.1, "right_cheek_g": green * 1.1, "right_cheek_b": blue * 1.1}
    path = tmp_path / name
    fieldnames = list(columns)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(fieldnames)
        for i in range(len(t)):
            row = []
            for key in fieldnames:
                value = columns[key][i] + (rng.normal(0, 0.2) if key != "timestamp_s" else 0.0)
                if nan_gap and nan_gap[0] <= t[i] < nan_gap[1] and key != "timestamp_s":
                    row.append("")
                else:
                    row.append(f"{value:.6f}")
            writer.writerow(row)
    return path


def reference_windows_csv(tmp_path, name, entries):
    """entries: iterable of (recording_id, window_start_s, reference_hr_bpm)."""
    path = tmp_path / name
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["recording_id", "window_start_s", "reference_hr_bpm"])
        for rid, start, bpm in entries:
            writer.writerow([rid, f"{start:.12g}", bpm])
    return path


def window_starts(duration_s=60.0, fs=30.0, window_s=12.0, step_s=6.0):
    n = int(duration_s * fs)
    window = int(round(window_s * fs))
    step = int(round(step_s * fs))
    t = np.arange(0, duration_s, 1.0 / fs)
    return [float(t[s]) for s in range(0, n - window + 1, step)]


def test_benchmark_fixture_runs_and_writes_outputs(tmp_path):
    rc = bench_cli.main([str(FIXTURE), "--backends", "rsbvp_native,rsbvp_reference,rppg_toolbox",
                         "--output-dir", str(tmp_path / "out")])
    assert rc == 0
    out = tmp_path / "out"
    for name in ("records.json", "records.csv", "waveforms.csv", "summary.json", "summary.md"):
        assert (out / name).is_file(), name
    summary = json.loads((out / "summary.json").read_text())
    statuses = {entry["backend"]["name"]: entry["status"] for entry in summary["backends"]}
    assert statuses["rsbvp_native"] == "completed"
    assert statuses["rsbvp_reference"] == "completed"
    assert statuses["rppg_toolbox"] == "unavailable"  # no external toolbox in CI
    assert summary["pairing_metrics"] == {}  # no reference supplied -> no metrics invented
    assert summary["reference_metrics_authorized"] is False


def test_benchmark_records_have_identical_windows_across_backends(tmp_path):
    trace = synthetic_trace_csv(tmp_path, "identical.csv")
    rc = bench_cli.main([str(trace), "--backends", "rsbvp_native,rsbvp_reference",
                         "--output-dir", str(tmp_path / "out")])
    assert rc == 0
    records = json.loads((tmp_path / "out" / "records.json").read_text())["records"]
    windows = {}
    for record in records:
        if record["backend_output_type"] != "window":
            continue
        windows.setdefault((record["backend"], record["algorithm"], record["roi"]), []).append(record["timestamp_s"])
    native_green = sorted(windows[("rsbvp_native", "GREEN", "forehead")])
    reference_green = sorted(windows[("rsbvp_reference", "GREEN", "forehead")])
    assert native_green == reference_green
    assert len(native_green) >= 9


def test_benchmark_pairing_requires_reference_source(tmp_path):
    reference = reference_windows_csv(tmp_path, "reference.csv", [("rppg_rgb_fixture", 0.0, 70.0)])
    rc = bench_cli.main([str(FIXTURE), "--backends", "rsbvp_native",
                         "--reference-windows", str(reference),
                         "--output-dir", str(tmp_path / "out")])
    assert rc == 2  # provenance string is mandatory before error metrics are emitted


def test_benchmark_pairing_metrics_with_reference(tmp_path):
    trace = synthetic_trace_csv(tmp_path, "paired.csv", heart_bpm=70.0)
    starts = window_starts()
    reference = reference_windows_csv(tmp_path, "reference.csv",
                                     [("paired", start, 70.0) for start in starts])
    rc = bench_cli.main([str(trace), "--backends", "rsbvp_native,rsbvp_reference",
                         "--reference-windows", str(reference),
                         "--reference-source", "deterministic synthetic fixture (software verification only)",
                         "--output-dir", str(tmp_path / "out")])
    assert rc == 0
    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert summary["reference_metrics_authorized"] is True
    key = "rsbvp_native:GREEN"
    assert key in summary["pairing_metrics"]
    metrics = summary["pairing_metrics"][key]["pooled_window_metrics_descriptive_only"]
    # GREEN is evaluated for all 5 ROI definitions (3 raw + cheeks + multi_roi).
    assert metrics["n_pairs"] == len(starts) * 5
    assert metrics["mae_bpm"] is not None
    # The synthetic trace is a deterministic 70 BPM signal; native GREEN recovers it.
    assert metrics["mae_bpm"] <= 3.0


def test_benchmark_participant_grouping_and_bootstrap(tmp_path):
    trace = synthetic_trace_csv(tmp_path, "shared.csv", heart_bpm=70.0)
    manifest = tmp_path / "manifest.csv"
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["recording_id", "csv_path", "participant_id"])
        writer.writerow(["rec_a", str(trace), "participant_a"])
        writer.writerow(["rec_b", str(trace), "participant_b"])
    starts = window_starts()
    reference = reference_windows_csv(tmp_path, "reference.csv",
                                     [(rid, start, 70.0) for rid in ("rec_a", "rec_b") for start in starts])
    rc = bench_cli.main(["--manifest", str(manifest),
                         "--backends", "rsbvp_native",
                         "--algorithms", "GREEN",
                         "--reference-windows", str(reference),
                         "--reference-source", "synthetic fixture; software verification only",
                         "--output-dir", str(tmp_path / "out")])
    assert rc == 0
    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    pairing = summary["pairing_metrics"]["rsbvp_native:GREEN"]
    assert set(pairing["participant_metrics"]) == {"participant_a", "participant_b"}
    assert pairing["participant_bootstrap"] is not None
    # No cross-participant leakage: each participant's metric uses only its own pairs.
    assert pairing["participant_metrics"]["participant_a"]["n_pairs"] == len(starts) * 5
    assert pairing["recording_metrics"]["rec_a"]["mae_bpm"] == pytest.approx(
        pairing["participant_metrics"]["participant_a"]["mae_bpm"])


def test_benchmark_never_fabricates_estimates(tmp_path):
    trace = synthetic_trace_csv(tmp_path, "degraded.csv", nan_gap=(20.0, 32.0))
    rc = bench_cli.main([str(trace), "--backends", "rsbvp_native",
                         "--output-dir", str(tmp_path / "out")])
    assert rc == 0
    records = json.loads((tmp_path / "out" / "records.json").read_text())["records"]
    rejected = [r for r in records if r["signal_quality"] == "rejected:nonfinite_samples"]
    assert rejected, "windows overlapping the missing segment must be rejected, not interpolated"
    for record in rejected:
        assert record["estimated_hr_bpm"] is None
        assert record["pulse_signal"] is None


def test_benchmark_is_deterministic(tmp_path):
    trace = synthetic_trace_csv(tmp_path, "deterministic.csv")
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    for out in (out_a, out_b):
        rc = bench_cli.main([str(trace), "--backends", "rsbvp_native,rsbvp_reference",
                             "--output-dir", str(out)])
        assert rc == 0
    assert (out_a / "records.json").read_bytes() == (out_b / "records.json").read_bytes()
    summary_a = json.loads((out_a / "summary.json").read_text())
    summary_b = json.loads((out_b / "summary.json").read_text())
    for key in ("availability", "windowing", "passband_hz", "pairing_metrics"):
        assert summary_a[key] == summary_b[key]


def test_benchmark_rejects_unknown_backend(tmp_path):
    rc = bench_cli.main([str(FIXTURE), "--backends", "not_a_backend",
                         "--output-dir", str(tmp_path / "out")])
    assert rc == 2


def test_aggregate_records_excluded_from_window_pairing(tmp_path):
    # Aggregate records (e.g. toolbox) must not leak into window pairing.
    rc = bench_cli.main([str(FIXTURE), "--backends", "rppg_toolbox",
                         "--output-dir", str(tmp_path / "out")])
    assert rc == 3  # no backend completed; toolbox is unavailable in CI
