"""Does the all-window mean differ materially from a non-overlapping-window mean?

Why this exists
---------------
The session result reports the arithmetic mean of every *accepted* reading. A
sliding-window analyser produces those readings every ~0.5 s from a 10 s window,
so neighbouring readings share 95 % of their signal. Two defensible but different
estimators therefore exist:

* **all-window mean** - the mean of all accepted readings. Equal weight per
  reading, so a period of dense analysis is weighted more heavily than a period
  analysed sparsely.
* **non-overlapping mean** - the mean of one reading per non-overlapping window
  (the subset already used for the uncertainty calculation). Equal weight per
  unit of time, so it is not dominated by whichever stretch happened to be
  analysed most often.

Neither is universally correct, and the mean is therefore **not** changed by
default. This module measures how far apart they actually are, on inputs whose
ground truth is known, so the decision can be made from evidence rather than
taste.

Honesty notes
-------------
* All simulations here are synthetic. They say what the estimators *do* to a
  given input; they say nothing about real skin, cameras or physiology.
* "Non-overlapping" is not "statistically independent". Windows that do not
  overlap in time are still autocorrelated, because the underlying physiology
  drifts slowly. The module reports the lag-1 autocorrelation of the readings so
  the difference is not glossed over.
* No confidence interval is claimed. The reported interval is a bootstrap over
  windows and is explicitly labelled a bootstrap interval.

Usage
-----
    python research/session/aggregation_analysis.py            # human summary
    python research/session/aggregation_analysis.py --json F   # machine output
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, asdict
from typing import Sequence

import numpy as np

#: Slope estimator for the "drifting truth" scenario, in BPM per second.
DRIFT_BPM_PER_S = 0.25
#: One analysis window length, in seconds (matches the live browser pathway).
WINDOW_S = 10.0
#: Analysis cadence, in seconds (browser re-analyses every 500 ms).
CADENCE_S = 0.5
#: Fixture seed. Fixed so every number below is reproducible byte for byte.
SEED = 20261126


@dataclass(frozen=True)
class Estimate:
    """One candidate estimator's behaviour on one scenario."""

    scenario: str
    estimator: str
    n_readings: int
    n_non_overlapping: int
    value: float
    truth: float
    signed_error: float
    abs_error: float
    #: Bootstrap interval over *non-overlapping windows*; not a CI.
    bootstrap_low: float | None
    bootstrap_high: float | None

    def as_dict(self) -> dict:
        return asdict(self)


def non_overlapping_indices(starts: Sequence[float], ends: Sequence[float]) -> list[int]:
    """Indices of a maximal set of non-overlapping windows (greedy by end time).

    Mirrors ``countIndependentWindows`` / ``count_independent_windows`` in the
    application so the analysis and the product cannot disagree about which
    readings form the non-overlapping subset.
    """
    order = sorted(range(len(starts)), key=lambda i: (ends[i], starts[i]))
    chosen: list[int] = []
    last_end = -math.inf
    for i in order:
        if starts[i] >= last_end:
            chosen.append(i)
            last_end = ends[i]
    return sorted(chosen)


def simulate_session(
    *,
    duration_s: float,
    truth: float,
    drift_bpm_per_s: float = 0.0,
    reading_sd: float = 2.0,
    cadence_s: float = CADENCE_S,
    gap: tuple[float, float] | None = None,
    slow_after_s: float | None = None,
    slow_cadence_s: float = 2.0,
    seed: int = SEED,
) -> dict:
    """Synthesise a sliding-window reading series with a known truth function.

    Two independent ways to make measurement density uneven:

    * ``gap`` removes readings entirely (a rejected stretch), which leaves the
      *remaining* time covered uniformly.
    * ``slow_after_s`` keeps analysing but far less often (the machine is busy, or
      most windows are rejected). This is the case that actually biases an
      equal-weight-per-reading mean: one stretch contributes four times as many
      readings as the other for the same amount of time.

    ``truth_at`` is returned alongside the readings so error is measured against
    the truth the mean *should* report, not against the value at t=0. Scoring a
    drifting signal against its starting value would manufacture a large "error"
    that no estimator could avoid.
    """
    rng = np.random.default_rng(seed)
    times: list[float] = []
    values: list[float] = []
    t = 0.0
    while t <= duration_s - WINDOW_S:
        in_gap = gap is not None and gap[0] <= t < gap[1]
        if not in_gap:
            centre = t + WINDOW_S / 2.0
            value = truth + drift_bpm_per_s * centre + rng.normal(0.0, reading_sd)
            times.append(t)
            values.append(value)
        slow = slow_after_s is not None and t >= slow_after_s
        t += slow_cadence_s if slow else cadence_s
    starts = np.array(times, dtype=float)
    ends = starts + WINDOW_S
    centres = starts + WINDOW_S / 2.0
    return {
        "starts": starts,
        "ends": ends,
        "values": np.array(values, dtype=float),
        "centres": centres,
        "drift_bpm_per_s": drift_bpm_per_s,
        "base_truth": truth,
    }


def mean_truth(session: dict) -> float:
    """The value a session average *should* report: the TIME-averaged truth.

    Deliberately not the mean of the truth over readings. Averaging per reading
    would make the target depend on how often each moment happened to be
    analysed, which is the very bias under test: a stretch analysed four times as
    often would define the target. A session average describes the session, so
    the truth is weighted by the time each reading stands for (the interval to
    the next analysed centre), i.e. a Riemann approximation of the time average.
    """
    centres = session["centres"]
    if centres.size == 0:
        return float(session["base_truth"])
    truth = session["base_truth"] + session["drift_bpm_per_s"] * centres
    # Each reading stands for the time until the next one; the last stands for a
    # nominal slot so it is not silently dropped.
    if centres.size > 1:
        weights = np.diff(centres)
        weights = np.append(weights, float(np.median(weights)))
    else:
        weights = np.array([1.0])
    return float(np.average(truth, weights=weights))


def _bootstrap_interval(values: np.ndarray, n_boot: int = 2000, seed: int = SEED) -> tuple[float, float]:
    """Percentile bootstrap of the mean over the supplied (non-overlapping) values.

    This is a bootstrap interval over the analysed windows. It is NOT a formal
    confidence interval: it assumes the windows are exchangeable draws, and with
    autocorrelated physiology that assumption is only approximate.
    """
    if values.size < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = np.array([rng.choice(values, size=values.size, replace=True).mean() for _ in range(n_boot)])
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def lag1_autocorrelation(values: np.ndarray) -> float | None:
    """Lag-1 autocorrelation of successive readings (None when undefined)."""
    if values.size < 3:
        return None
    x = values - values.mean()
    denom = float(np.dot(x, x))
    if denom <= 0.0:
        return None
    return float(np.dot(x[:-1], x[1:]) / denom)


def compare(session: dict, scenario: str) -> list[Estimate]:
    """Compute both estimators for one synthesised session."""
    starts, ends, values = session["starts"], session["ends"], session["values"]
    chosen = non_overlapping_indices(starts, ends)
    non_overlap_values = values[chosen]
    low, high = _bootstrap_interval(non_overlap_values)
    truth = mean_truth(session)
    out: list[Estimate] = []
    for name, vals, lo, hi in (
        ("all_window_mean", values, None, None),
        ("non_overlapping_mean", non_overlap_values, low, high),
    ):
        value = float(np.mean(vals)) if vals.size else float("nan")
        out.append(Estimate(
            scenario=scenario,
            estimator=name,
            n_readings=int(values.size),
            n_non_overlapping=len(chosen),
            value=value,
            truth=truth,
            signed_error=value - truth,
            abs_error=abs(value - truth),
            bootstrap_low=lo,
            bootstrap_high=hi,
        ))
    return out


SCENARIOS: dict[str, dict] = {
    # A steady state: both estimators should agree closely.
    "steady_60s": dict(duration_s=60.0, truth=72.0, reading_sd=2.0),
    # Slow physiological drift: every window is a slightly different moment.
    "drift_120s": dict(duration_s=120.0, truth=72.0, drift_bpm_per_s=DRIFT_BPM_PER_S, reading_sd=2.0),
    # A stretch was rejected outright (motion, a hand across the face): the
    # remaining time is still covered uniformly.
    "rejected_gap": dict(duration_s=90.0, truth=68.0, reading_sd=2.0, gap=(30.0, 50.0)),
    # Uneven *density*: analysis continues but four times less often after 40 s
    # (busy machine, or most windows rejected). Equal-weight-per-reading then
    # over-weights the dense stretch; equal-weight-per-time does not.
    "uneven_density": dict(duration_s=90.0, truth=68.0, reading_sd=2.0, slow_after_s=40.0),
    # Uneven density *while drifting*: the case where the two estimators are
    # expected to disagree the most.
    "uneven_density_with_drift": dict(
        duration_s=120.0, truth=70.0, drift_bpm_per_s=DRIFT_BPM_PER_S, reading_sd=2.0, slow_after_s=50.0
    ),
    # A single wild accepted reading (an outlier the gates did not catch).
    "single_outlier": dict(duration_s=60.0, truth=75.0, reading_sd=1.5),
}


def run_all() -> dict:
    """Run every scenario and return a JSON-serialisable report."""
    per_scenario: list[dict] = []
    for name, kwargs in SCENARIOS.items():
        session = simulate_session(**kwargs)
        estimates = compare(session, name)
        divergence = float(
            math.hypot(
                estimates[0].value - estimates[1].value,
                estimates[0].abs_error - estimates[1].abs_error,
            )
        ) if not any(math.isnan(e.value) for e in estimates) else float("nan")
        per_scenario.append({
            "scenario": name,
            "spec": {k: v for k, v in kwargs.items()},
            "n_readings": estimates[0].n_readings,
            "n_non_overlapping": estimates[0].n_non_overlapping,
            "all_window_mean": estimates[0].value,
            "non_overlapping_mean": estimates[1].value,
            "difference_bpm": estimates[0].value - estimates[1].value,
            "all_window_abs_error": estimates[0].abs_error,
            "non_overlapping_abs_error": estimates[1].abs_error,
            "lag1_autocorrelation_of_readings": lag1_autocorrelation(session["values"]),
            "lag1_autocorrelation_of_non_overlapping": lag1_autocorrelation(
                session["values"][non_overlapping_indices(session["starts"], session["ends"])]),
            "divergence_metric": divergence,
        })

    # The outlier scenario gets an explicit high-frequency value added, because
    # the base fixture is deliberately tame (the gates are supposed to reject
    # wild readings; this tests what happens when one slips through).
    outlier_session = simulate_session(**SCENARIOS["single_outlier"])
    wild = outlier_session["values"].copy()
    wild[len(wild) // 2] += 60.0
    outlier_session["values"] = wild
    chosen = non_overlapping_indices(outlier_session["starts"], outlier_session["ends"])
    outlier = {
        "scenario": "single_outlier_injected",
        "spec": {"added_offset_bpm": 60.0, "readings": int(wild.size)},
        "n_readings": int(wild.size),
        "n_non_overlapping": len(chosen),
        "all_window_mean": float(np.mean(wild)),
        "non_overlapping_mean": float(np.mean(wild[chosen])),
        "difference_bpm": float(np.mean(wild) - np.mean(wild[chosen])),
        "median_all": float(np.median(wild)),
        "median_non_overlapping": float(np.median(wild[chosen])),
    }

    return {
        "schema": "rsbvp.aggregation-analysis.v1",
        "note": (
            "Synthetic scenarios with a known truth. They describe what the estimators do to "
            "a given input and say nothing about real cameras, skin or physiology. The bootstrap "
            "interval is over windows, not a formal confidence interval."
        ),
        "seed": SEED,
        "window_s": WINDOW_S,
        "cadence_s": CADENCE_S,
        "scenarios": per_scenario,
        "outlier": outlier,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=str, default=None, help="write the report here")
    args = parser.parse_args(argv)

    report = run_all()
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=False)
            handle.write("\n")

    print(f"window {WINDOW_S:g} s, cadence {CADENCE_S:g} s, seed {SEED}")
    header = f"{'scenario':30s} {'n':>4s} {'non-ovl':>7s} {'all-window':>10s} {'non-ovl':>9s} {'diff':>7s} {'|err| all':>10s} {'|err| nov':>10s} {'acf1':>6s}"
    print(header)
    print("-" * len(header))
    for row in report["scenarios"]:
        acf = row["lag1_autocorrelation_of_readings"]
        print(
            f"{row['scenario']:30s} {row['n_readings']:4d} {row['n_non_overlapping']:7d} "
            f"{row['all_window_mean']:10.2f} {row['non_overlapping_mean']:9.2f} "
            f"{row['difference_bpm']:7.2f} {row['all_window_abs_error']:10.2f} "
            f"{row['non_overlapping_abs_error']:10.2f} {('%.2f' % acf) if acf is not None else '   n/a':>6s}"
        )
    o = report["outlier"]
    print(
        f"\noutlier injected (+60 BPM on one reading): all-window mean {o['all_window_mean']:.2f}, "
        f"non-overlapping mean {o['non_overlapping_mean']:.2f}, difference {o['difference_bpm']:.2f} BPM; "
        f"median {o['median_all']:.2f} vs {o['median_non_overlapping']:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
