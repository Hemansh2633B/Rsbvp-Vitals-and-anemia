"""Research figures.

Every figure carries its own sample count and the limitation that applies to it, in
the figure itself rather than only in the caption — a scatter plot lifted into a
slide keeps only what is drawn on it.

Synthetic input is marked in the figure title **and** in a banner across the plot, so
a synthetic figure cannot be mistaken for a validated one after it leaves this
program.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from research.validation.alignment import PairedObservation
from research.validation.metrics import Pair, agreement, correlation


@dataclass
class Figure:
    name: str
    path: Path
    n: int
    kind: str
    note: str


def _pyplot():
    import matplotlib
    matplotlib.use("Agg")  # headless; no display is assumed anywhere
    import matplotlib.pyplot as plt
    return plt


SYNTHETIC_WARNING = "SYNTHETIC TEST DATA — NOT VALIDATION"


def _finish(ax, fig, *, synthetic: bool, title: str, note: str, subtitle: str = "") -> None:
    """Shared title/caption handling so every figure marks its own limits.

    The synthetic warning is prepended to the *title* rather than floated over the
    axes: a floating annotation collided with the title at this figure size, and a
    warning that overlaps what it warns about is worse than none.
    """
    lines = []
    if synthetic:
        lines.append(SYNTHETIC_WARNING)
    lines.append(title)
    if subtitle:
        lines.append(subtitle)
    ax.set_title("\n".join(lines), fontsize=9.5,
                 color="#a00000" if synthetic else "black")
    ax.tick_params(labelsize=8)
    ax.xaxis.label.set_size(9)
    ax.yaxis.label.set_size(9)
    # Wrap the caption to the figure width so it cannot run off the edge.
    if note:
        fig.text(0.01, 0.005, note, fontsize=6, color="#444444", wrap=True,
                 va="bottom")
    fig.tight_layout(rect=(0, 0.06 if note else 0.0, 1, 1.0))


def _pairs(observations: Sequence[PairedObservation]) -> list[Pair]:
    return [Pair(o.reference_bpm, o.estimate_bpm) for o in observations]


def scatter_reference_vs_estimate(
    observations: Sequence[PairedObservation], path: Path, *,
    title: str = "Reference vs estimate", synthetic: bool = False,
) -> Figure | None:
    pairs = _pairs(observations)
    if len(pairs) < 3:
        return None
    plt = _pyplot()
    ref = np.array([p.reference_bpm for p in pairs])
    est = np.array([p.estimate_bpm for p in pairs])
    fig, ax = plt.subplots(figsize=(5.2, 4.6), dpi=140)
    ax.scatter(ref, est, s=12, alpha=0.6, edgecolors="none", color="#1f4e79")
    low = float(min(ref.min(), est.min()))
    high = float(max(ref.max(), est.max()))
    ax.plot([low, high], [low, high], "--", color="#888888", linewidth=1,
            label="identity (perfect agreement)")
    agree = agreement(pairs)
    corr = correlation(pairs)
    r_text = f"r = {corr['pearson_r']:.3f}" if corr.get("available") else "r unavailable"
    ax.set_xlabel("reference pulse (BPM)")
    ax.set_ylabel("estimated pulse (BPM)")
    ax.legend(fontsize=7, loc="upper left")
    ax.text(0.98, 0.02,
            f"MAE {agree['mae_bpm']:.1f} BPM · bias {agree['bias_bpm']:+.1f}\n"
            "Correlation is not agreement: points may be tight and offset.",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=6.5, color="#333333")
    _finish(ax, fig, synthetic=synthetic, title=title,
            subtitle=f"n = {len(pairs)} paired windows · {r_text}",
            note="Windows overlap; points are not independent draws. Correlation is not accuracy.")
    fig.savefig(path)
    plt.close(fig)
    return Figure(path.stem, path, len(pairs), "scatter",
                  "Overlapping windows are not independent observations.")


def bland_altman(
    observations: Sequence[PairedObservation], path: Path, *,
    title: str = "Bland–Altman", synthetic: bool = False,
) -> Figure | None:
    pairs = _pairs(observations)
    score = agreement(pairs)
    if not score.get("available") or score.get("loa_lower_bpm") is None:
        return None
    plt = _pyplot()
    ref = np.array([p.reference_bpm for p in pairs])
    est = np.array([p.estimate_bpm for p in pairs])
    mean = (ref + est) / 2
    diff = est - ref
    bias = score["bias_bpm"]
    lo, hi = score["loa_lower_bpm"], score["loa_upper_bpm"]

    fig, ax = plt.subplots(figsize=(5.4, 4.2), dpi=140)
    ax.scatter(mean, diff, s=12, alpha=0.6, edgecolors="none", color="#2e6b4f")
    ax.axhline(bias, color="#1f4e79", linewidth=1.2, label=f"bias {bias:+.1f} BPM")
    ax.axhline(lo, color="#a00000", linestyle="--", linewidth=1,
               label=f"95% limits {lo:+.1f} … {hi:+.1f}")
    ax.axhline(hi, color="#a00000", linestyle="--", linewidth=1)
    ax.axhline(0, color="#bbbbbb", linewidth=0.8)
    ax.set_xlabel("mean of reference and estimate (BPM)")
    ax.set_ylabel("estimate − reference (BPM)")
    ax.legend(fontsize=7, loc="upper right")
    ax.text(0.02, 0.02, "Limits are ±1.96 SD of this sample's errors.",
            transform=ax.transAxes, fontsize=6.5, color="#333333")
    _finish(ax, fig, synthetic=synthetic, title=title,
            subtitle=f"n = {score['n_pairs']} paired windows",
            note="Limits of agreement describe these recordings, not future measurements.")
    fig.savefig(path)
    plt.close(fig)
    return Figure(path.stem, path, score["n_pairs"], "bland_altman",
                  "Limits of agreement are sample properties.")


def error_histogram(
    observations: Sequence[PairedObservation], path: Path, *,
    title: str = "Error distribution", synthetic: bool = False,
) -> Figure | None:
    pairs = _pairs(observations)
    if len(pairs) < 3:
        return None
    plt = _pyplot()
    errors = np.array([p.error for p in pairs])
    fig, ax = plt.subplots(figsize=(5.2, 3.8), dpi=140)
    bins = int(min(40, max(5, np.sqrt(len(errors)) * 2)))
    ax.hist(errors, bins=bins, color="#4a6fa5", edgecolor="white", linewidth=0.5)
    ax.axvline(0, color="#888888", linewidth=1, linestyle=":")
    ax.axvline(float(errors.mean()), color="#a00000", linewidth=1.3,
               label=f"mean {errors.mean():+.1f} BPM")
    ax.set_xlabel("estimate − reference (BPM)")
    ax.set_ylabel("windows")
    ax.legend(fontsize=7)
    _finish(ax, fig, synthetic=synthetic, title=title,
            subtitle=f"n = {len(errors)} paired windows",
            note="A distribution of window errors is not a distribution of people.")
    fig.savefig(path)
    plt.close(fig)
    return Figure(path.stem, path, len(errors), "histogram", "Describes these windows only.")


def error_by_group(
    groups: dict[str, Sequence[PairedObservation]], path: Path, *,
    title: str, xlabel: str = "group", synthetic: bool = False,
) -> Figure | None:
    """Box plot of signed error per group, with n printed beneath each box."""
    usable = {name: obs for name, obs in groups.items() if len(obs) >= 3}
    if not usable:
        return None
    plt = _pyplot()
    names = sorted(usable)
    data = [np.array([o.estimate_bpm - o.reference_bpm for o in usable[name]]) for name in names]
    fig, ax = plt.subplots(figsize=(max(4.6, 1.15 * len(names) + 2.4), 3.9), dpi=140)
    ax.boxplot(data, tick_labels=names, showfliers=True, widths=0.6)
    ax.axhline(0, color="#888888", linewidth=1, linestyle=":")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("estimate − reference (BPM)")
    for position, (name, values) in enumerate(zip(names, data), start=1):
        ax.text(position, ax.get_ylim()[0], f"n={len(values)}", ha="center", va="bottom",
                fontsize=6.5, color="#444444")
    plt.setp(ax.get_xticklabels(), rotation=25, ha="right")
    _finish(ax, fig, synthetic=synthetic, title=title,
            subtitle=f"total n = {sum(len(d) for d in data)} paired windows",
            note="Group sizes differ; a smaller group has a wider spread, not necessarily worse accuracy.")
    fig.savefig(path)
    plt.close(fig)
    return Figure(path.stem, path, sum(len(d) for d in data), "box",
                  "Small groups have wide spreads; coverage differs by group.")


def coverage_vs_error(
    methods: Sequence[dict], path: Path, *, title: str = "Coverage vs error",
    synthetic: bool = False,
) -> Figure | None:
    """Does producing more estimates come at the cost of accuracy?

    X is the fraction of considered windows the method produced a value for, Y is its
    MAE. A method can win this chart either by being accurate or by being selective,
    which is exactly why coverage is plotted rather than tabulated alone.
    """
    usable = [m for m in methods
              if m.get("available") and m.get("agreement", {}).get("mae_bpm") is not None
              and m.get("coverage", {}).get("windows_paired") is not None
              and m.get("coverage", {}).get("windows_considered")]
    if len(usable) < 2:
        return None
    plt = _pyplot()
    xs = [m["coverage"]["windows_paired"] / m["coverage"]["windows_considered"] for m in usable]
    ys = [m["agreement"]["mae_bpm"] for m in usable]
    labels = [m["label"] for m in usable]
    fig, ax = plt.subplots(figsize=(5.8, 4.2), dpi=140)
    ax.scatter(xs, ys, s=28, color="#7a4a1f")
    # Methods that share a (coverage, MAE) pair land on the same pixel. Stack their
    # labels vertically instead of drawing them on top of each other, which is what
    # produced an unreadable smear of overlapping text in the first version.
    # Cluster near-coincident points, not exactly-equal ones: rounding to 6 decimals
    # split clusters whose y differed by 1e-9 (they differ by float noise from the
    # per-series means) and the labels still landed on top of each other. Clustering
    # on the plotted axis scale is what actually prevents the collision.
    x_span = (max(xs) - min(xs)) or 1.0
    y_span = (max(ys) - min(ys)) or 1.0
    clusters: list[dict] = []
    for x, y, label in zip(xs, ys, labels):
        for cluster in clusters:
            if (abs(cluster["x"] - x) / x_span < 0.06
                    and abs(cluster["y"] - y) / y_span < 0.06):
                cluster["labels"].append(label)
                break
        else:
            clusters.append({"x": x, "y": y, "labels": [label]})

    # One label block per cluster, drawn upward from the point with enough vertical
    # room for every method in it.
    for cluster in clusters:
        block = "\n".join(sorted(cluster["labels"]))
        ax.annotate(block, (cluster["x"], cluster["y"]), textcoords="offset points",
                    xytext=(8, -2), fontsize=6.2, va="top", linespacing=1.3,
                    bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": "#ccc",
                          "alpha": 0.85})
    ax.margins(x=0.30, y=0.22)
    ax.set_xlabel("fraction of considered windows paired with a reference")
    ax.set_ylabel("MAE (BPM)")
    _finish(ax, fig, synthetic=synthetic, title=title,
            subtitle=f"{len(usable)} method series",
            note="Low MAE with low coverage may mean the method only answers when the signal is "
                 "easy. Compare on the shared subset; per-estimator series are diagnostics, not "
                 "independent measurements.")
    fig.savefig(path)
    plt.close(fig)
    return Figure(path.stem, path, len(usable), "scatter",
                  "Coverage and accuracy trade off; see the shared-subset comparison.")


def individual_vs_session(
    observations: Sequence[PairedObservation], session: dict, path: Path, *,
    synthetic: bool = False,
) -> Figure | None:
    """Individual-window absolute errors beside the session mean's."""
    pairs = _pairs(observations)
    if len(pairs) < 3 or not session.get("available"):
        return None
    plt = _pyplot()
    individual = np.array([abs(p.error) for p in pairs])
    mean_err = session["session_mean"]["abs_error_bpm"]
    median_err = session["session_median"]["abs_error_bpm"]
    fig, ax = plt.subplots(figsize=(5.2, 3.9), dpi=140)
    ax.boxplot([individual], tick_labels=["individual windows"], widths=0.5, showfliers=True)
    ax.scatter([1], [mean_err], marker="D", s=45, color="#a00000", zorder=5,
               label=f"session mean {mean_err:.1f} BPM")
    ax.scatter([1.28], [median_err], marker="s", s=40, color="#1f4e79", zorder=5)
    ax.text(1.28, median_err, " session median", fontsize=7, va="center", color="#1f4e79")
    ax.set_ylabel("absolute error (BPM)")
    ax.set_xlim(0.6, 1.7)
    ax.legend(fontsize=7, loc="upper right")
    _finish(ax, fig, synthetic=synthetic, title="Individual windows vs session aggregate",
            subtitle=f"n = {len(individual)} windows, 1 session",
            note="One session: the aggregate is a single observation and has no interval.")
    fig.savefig(path)
    plt.close(fig)
    return Figure(path.stem, path, len(individual), "comparison",
                  "Session aggregate is a single observation.")


def generate_all(result, out_dir: Path) -> list[Figure]:
    """Draw every figure the result supports. Missing prerequisites are skipped."""
    out_dir.mkdir(parents=True, exist_ok=True)
    alignment = getattr(result, "alignment", None)
    if alignment is None:
        return []
    observations = alignment.pairs
    synthetic = bool(result.input_is_synthetic)
    figures: list[Figure] = []

    def add(figure):
        if figure is not None:
            figures.append(figure)

    add(scatter_reference_vs_estimate(observations, out_dir / "scatter_reference_vs_estimate.png",
                                      synthetic=synthetic))
    add(bland_altman(observations, out_dir / "bland_altman.png", synthetic=synthetic))
    add(error_histogram(observations, out_dir / "error_histogram.png", synthetic=synthetic))

    by_roi: dict[str, list] = {}
    by_algorithm: dict[str, list] = {}
    for observation in observations:
        by_roi.setdefault(observation.roi, []).append(observation)
        by_algorithm.setdefault(observation.algorithm, []).append(observation)
    add(error_by_group(by_roi, out_dir / "error_by_roi.png", title="Error by ROI",
                       xlabel="ROI", synthetic=synthetic))
    add(error_by_group(by_algorithm, out_dir / "error_by_algorithm.png",
                       title="Error by algorithm", xlabel="algorithm", synthetic=synthetic))

    device_groups: dict[str, list] = {}
    for observation in observations:
        device_groups.setdefault(observation.device or "unknown", []).append(observation)
    if len(device_groups) > 1:
        add(error_by_group(device_groups, out_dir / "error_by_device.png",
                           title="Error by reference device", xlabel="device",
                           synthetic=synthetic))

    add(coverage_vs_error(result.methods, out_dir / "coverage_vs_error.png",
                          synthetic=synthetic))
    add(individual_vs_session(observations, result.session_aggregation,
                              out_dir / "individual_vs_session.png", synthetic=synthetic))
    return figures
