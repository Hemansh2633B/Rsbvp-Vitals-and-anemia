#!/usr/bin/env python3
"""Regenerate ``rppg_rgb_fixture_expected.json`` from ``rppg_rgb_fixture.csv``.

The fixture itself is a *synthetic software-test fixture* (not physiological
data). This script deterministically recomputes the expected JSON so reviewers
can audit the chain fixture -> expected values. Run from the repository root:

    python tests/fixtures/generate_rppg_rgb_fixture_expected.py

``reference_free_expected_python_estimates_bpm`` is the Python algorithm chain
(``compare_algorithms.evaluate_recording``) output on the fixture's first
12 s. ``python_spectral_diagnostics_first_12_seconds`` evaluates the exact
projections implemented in ``gui/frontend/src/rppg/liveDsp.ts`` (de-meaned
Hann-periodogram estimates) so the browser/TS implementation can be compared
against an independent reimplementation on identical input samples.
"""
import csv
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "rppg_rgb_fixture.csv"
JSON_PATH = HERE / "rppg_rgb_fixture_expected.json"
WINDOW_SECONDS = 12.0
ROIS = ("forehead", "left_cheek", "right_cheek")
CHANNELS = ("r", "g", "b")
METHODS = ("green", "pos", "chrom")


def _rgb_for_roi(rows, roi):
    return np.array([[float(r[f"{roi}_{c}"]) for c in CHANNELS] for r in rows], dtype=float)


def spectral_features(signal, fs, lo=0.7, hi=3.5):
    """Mirror of the spectralDiagnostics() implementation (TS) for the fixture."""
    x = np.asarray(signal, dtype=float)
    centered = x - x.mean()
    n = len(centered)
    window = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n) / (n - 1))
    power = np.abs(np.fft.rfft(centered * window)) ** 2
    freqs = np.arange(power.size) * float(fs) / n
    mask = (freqs >= lo) & (freqs <= hi)
    band_freqs, band = freqs[mask], power[mask]
    total = float(band.sum())
    peak_index = int(np.argmax(band))
    peak_hz = float(band_freqs[peak_index])
    peak_power = float(band[peak_index])
    floor = band[np.abs(band_freqs - peak_hz) > 0.15]
    snr_db = None
    if floor.size:
        median = float(np.median(floor))
        if median > 0:
            snr_db = float(10.0 * np.log10(peak_power / median))
    return {
        "peak_hz": peak_hz,
        "bpm": peak_hz * 60.0,
        "peak_fraction": float(band[peak_index] / total),
        "snr_db": snr_db,
        "separation_ratio": None,  # no competing in-band local maximum in this fixture
    }


def pos_projection(rgb):
    means = rgb.mean(axis=0)
    normed = rgb / means - 1.0
    s1 = normed[:, 1] - normed[:, 2]
    s2 = normed[:, 1] + normed[:, 2] - 2.0 * normed[:, 0]
    alpha = s1.std() / max(s2.std(), 1e-8)
    return s1 + alpha * s2


def chrom_projection(rgb, fs):
    colmean = rgb.mean(axis=0)
    norm = rgb / colmean - 1.0
    xs = 3.0 * norm[:, 0] - 2.0 * norm[:, 1]
    ys = 1.5 * norm[:, 0] + norm[:, 1] - 1.5 * norm[:, 2]
    win = max(8, round(fs * 1.6))
    step = max(1, win // 2)
    out = np.zeros_like(xs)
    weight = np.zeros_like(xs)
    for start in range(0, len(xs), step):
        end = min(len(xs), start + win)
        sx, sy = xs[start:end], ys[start:end]
        alpha = sx.std() / max(sy.std(), 1e-8)
        for i in range(start, end):
            out[i] += xs[i] - alpha * ys[i]
            weight[i] += 1
    return out / np.maximum(weight, 1)


def main():
    rows = list(csv.DictReader(CSV_PATH.open(newline="")))
    rows = [r for r in rows if float(r["timestamp_s"]) < WINDOW_SECONDS]
    ts = np.array([float(r["timestamp_s"]) for r in rows])
    fs = 1.0 / np.median(np.diff(ts))

    diagnostics = {
        "fs_hz": float(fs),
        "window_seconds": WINDOW_SECONDS,
        "n_samples": int(len(rows)),
    }
    reference_free = {}

    for roi in ROIS:
        rgb = _rgb_for_roi(rows, roi)
        projections = {
            "green": rgb[:, 1],
            "pos": pos_projection(rgb),
            "chrom": chrom_projection(rgb, fs),
        }
        for method in METHODS:
            key = f"{roi}_{method}"
            feats = spectral_features(projections[method], fs)
            diagnostics[key] = feats
            reference_free[key] = feats["bpm"]

    doc = json.loads(JSON_PATH.read_text())
    doc["reference_free_expected_python_estimates_bpm"] = reference_free
    doc["python_spectral_diagnostics_first_12_seconds"] = diagnostics
    doc["python_spectral_diagnostics_note"] = (
        "Independent Python evaluation of the TypeScript projections in "
        "gui/frontend/src/rppg/liveDsp.ts (de-meaned Hann periodogram, 0.7-3.5 Hz). "
        "Computed by tests/fixtures/generate_rppg_rgb_fixture_expected.py. "
        "software-verification values only; not a physiological validation claim."
    )
    JSON_PATH.write_text(json.dumps(doc, indent=2) + "\n")
    print(json.dumps(diagnostics, indent=2))


if __name__ == "__main__":
    main()
