#!/usr/bin/env python3
"""Frozen rPPG-10 benchmark protocol (pre-registered before any data is seen).

Every choice below is fixed in code and versioned with the report; no
parameter is selected by looking at benchmark performance. See
docs/RPPG10_VALIDATION.md §"Frozen protocol" for the rationale.

Protocol (v1, frozen 2026-11-25)
-------------------------------
* Windows: **30 s, non-overlapping** (step = window). Chosen because the
  provider's own baseline used non-overlapping 30 s windows, and because
  non-overlapping windows avoid treating correlated observations as
  independent samples. Each recording (600 s) yields 20 windows.
* Estimators: GREEN, POS, CHROM — the three implemented, documented,
  threshold-frozen trace-domain methods (`research/backends/reference_methods.py`).
  ICA/PBV are excluded from the primary protocol (they are exploratory only).
* Passband: 0.7–3.5 Hz (42–210 BPM), the repository-wide default.
* Quality gates: `reference_methods.quality_failures` with its existing
  constants (concentration, SNR, separation). A window failing any gate yields
  ``bpm=None`` with the failing tokens — never a throttled or "best-effort"
  value, and the gates are never loosened for this dataset.
* ROI handling: forehead, right_cheek (Cheek1), left_cheek (Cheek2) evaluated
  separately, then reported per ROI. Three ROIs of one participant are **one**
  participant; ROI-level statistics are never pooled into participant counts.
* Reference: ECG → Pan–Tompkins R-peaks → 60/median(RR) per window
  (`research/ecg/reference.py`). Windows whose ECG reference is rejected are
  excluded from error statistics and counted in the coverage accounting.
* Uncertainty: participant-level bootstrap (resample subjects, 2000 draws,
  seed 20261125) over per-participant mean absolute error per ROI.
* No tuning, no calibration, no per-subject offsets, no outlier removal after
  the fact. Every window result is retained in the JSON report.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

import numpy as np

from research.backends import reference_methods as rm

PROTOCOL_VERSION = "rsbvp.rppg10-protocol.v1"
PROTOCOL_FROZEN_DATE = "2026-11-25"
WINDOW_SECONDS = 30.0
STEP_SECONDS = 30.0
PASSBAND_HZ = (0.7, 3.5)
ESTIMATORS = ("green", "pos", "chrom")
ROIS = ("forehead", "right_cheek", "left_cheek")
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20261125
MIN_WINDOW_FINITE_FRACTION = 0.98
MAX_TIMESTAMP_JITTER_FRACTION = 0.05


def protocol_description() -> dict:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "frozen_date": PROTOCOL_FROZEN_DATE,
        "window_seconds": WINDOW_SECONDS,
        "step_seconds": STEP_SECONDS,
        "overlap": False,
        "passband_hz": list(PASSBAND_HZ),
        "estimators": list(ESTIMATORS),
        "rois": list(ROIS),
        "quality_gates": {
            "module": "research/backends/reference_methods.py",
            "min_concentration": rm.SPECTRAL_MIN_CONCENTRATION,
            "min_snr_db": rm.SPECTRAL_MIN_SNR_DB,
            "min_separation": rm.SPECTRAL_MIN_SEPARATION,
            "note": "unchanged for this dataset; failures yield bpm=None",
        },
        "min_window_finite_fraction": MIN_WINDOW_FINITE_FRACTION,
        "max_timestamp_jitter_fraction": MAX_TIMESTAMP_JITTER_FRACTION,
        "reference_hr": "ECG Pan–Tompkins R-peaks; 60 / median(valid R-R)",
        "bootstrap": {"unit": "participant", "draws": BOOTSTRAP_DRAWS, "seed": BOOTSTRAP_SEED},
        "no_tuning": True,
    }


@dataclass
class WindowResult:
    subject: int
    roi: str
    window_index: int
    start_s: float
    end_s: float
    reference_bpm: Optional[float]
    reference_reasons: list[str]
    estimates_bpm: dict[str, Optional[float]] = field(default_factory=dict)
    quality: dict[str, str] = field(default_factory=dict)
    # Pre-gate spectral peaks, recorded for transparency only. They are NEVER used
    # as a protocol result: `estimates_bpm` is the gated protocol value. The
    # ungated numbers exist so a reader can see exactly what the quality gates
    # remove (they are summarised separately as a descriptive sensitivity analysis).
    raw_estimates_bpm: dict[str, Optional[float]] = field(default_factory=dict)
    trace_status: str = "ok"
    trace_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "subject": self.subject, "roi": self.roi, "window_index": self.window_index,
            "start_s": round(self.start_s, 6), "end_s": round(self.end_s, 6),
            "reference_bpm": self.reference_bpm, "reference_reasons": list(self.reference_reasons),
            "estimates_bpm": dict(self.estimates_bpm), "quality": dict(self.quality),
            "raw_estimates_bpm": dict(self.raw_estimates_bpm),
            "trace_status": self.trace_status, "trace_reasons": list(self.trace_reasons),
        }


def window_starts(duration_s: float, window_seconds: float = WINDOW_SECONDS,
                  step_seconds: float = STEP_SECONDS, *, require_full: bool = True) -> list[float]:
    """Deterministic window start times; a trailing partial window is dropped."""
    if not (math.isfinite(duration_s) and duration_s > 0):
        raise ValueError("duration_s must be finite and positive")
    if window_seconds <= 0 or step_seconds <= 0:
        raise ValueError("window and step must be positive")
    limit = duration_s - window_seconds if require_full else duration_s - 1e-9
    if limit < 0:
        return []
    count = int(math.floor(limit / step_seconds + 1e-9)) + 1
    return [round(i * step_seconds, 6) for i in range(count)]


def _segment(t: np.ndarray, rgb: np.ndarray, start: float, end: float) -> tuple[np.ndarray, np.ndarray]:
    mask = (t >= start) & (t < end)
    return t[mask], rgb[mask]


def estimate_window(subject: int, roi: str, index: int, start: float, end: float,
                    t: np.ndarray, rgb: np.ndarray,
                    reference_bpm: Optional[float], reference_reasons: Sequence[str]) -> WindowResult:
    """Run the frozen estimators on one window; never fabricate a value."""
    result = WindowResult(subject=subject, roi=roi, window_index=index, start_s=start, end_s=end,
                          reference_bpm=reference_bpm, reference_reasons=list(reference_reasons))
    segment_t, segment_rgb = _segment(t, rgb, start, end)
    expected = int(round((end - start) / max(1e-9, float(np.median(np.diff(t)))))) if t.size > 1 else 0
    if segment_t.size < 16:
        result.trace_status = "rejected"
        result.trace_reasons.append("trace_too_few_samples")
        result.estimates_bpm = {name: None for name in ESTIMATORS}
        result.raw_estimates_bpm = {name: None for name in ESTIMATORS}
        result.quality = {name: "rejected:trace_too_few_samples" for name in ESTIMATORS}
        return result
    finite_fraction = float(np.isfinite(segment_rgb).all(axis=1).mean())
    if expected and segment_t.size < MIN_WINDOW_FINITE_FRACTION * expected:
        result.trace_status = "rejected"
        result.trace_reasons.append(f"trace_missing_frames_{segment_t.size}_of_{expected}")
    if finite_fraction < MIN_WINDOW_FINITE_FRACTION:
        result.trace_status = "rejected"
        result.trace_reasons.append(f"trace_nonfinite_fraction_{1 - finite_fraction:.3f}")
    diffs = np.diff(segment_t)
    if diffs.size and float(np.mean(np.abs(diffs - np.median(diffs)) > MAX_TIMESTAMP_JITTER_FRACTION * np.median(diffs))) > MAX_TIMESTAMP_JITTER_FRACTION:
        result.trace_status = "rejected"
        result.trace_reasons.append("trace_timestamp_jitter")

    if result.trace_status != "ok":
        result.estimates_bpm = {name: None for name in ESTIMATORS}
        result.raw_estimates_bpm = {name: None for name in ESTIMATORS}
        result.quality = {name: f"rejected:{result.trace_reasons[0]}" for name in ESTIMATORS}
        return result

    fs = float(1.0 / np.median(diffs)) if diffs.size else 0.0
    if not math.isfinite(fs) or fs <= 2 * PASSBAND_HZ[1]:
        result.estimates_bpm = {name: None for name in ESTIMATORS}
        result.raw_estimates_bpm = {name: None for name in ESTIMATORS}
        result.quality = {name: "rejected:sampling_rate_insufficient" for name in ESTIMATORS}
        result.trace_status = "rejected"
        result.trace_reasons.append("sampling_rate_insufficient")
        return result

    methods = {"green": rm.green, "pos": rm.pos, "chrom": rm.chrom}
    for name in ESTIMATORS:
        try:
            signal, _meta = methods[name](segment_rgb, fs, *PASSBAND_HZ)
        except rm.FlatSignalError:
            result.estimates_bpm[name] = None
            result.raw_estimates_bpm[name] = None
            result.quality[name] = "rejected:flat_signal"
            continue
        except ValueError as exc:
            result.estimates_bpm[name] = None
            result.raw_estimates_bpm[name] = None
            result.quality[name] = f"rejected:invalid_trace_{type(exc).__name__}"
            continue
        bpm, peak_fraction, snr_db, separation = rm.spectral_features(signal, fs, *PASSBAND_HZ)
        result.raw_estimates_bpm[name] = None if bpm is None else float(bpm)
        failures = rm.quality_failures(peak_fraction, snr_db, separation)
        if failures or bpm is None:
            result.estimates_bpm[name] = None
            result.quality[name] = "rejected:" + "_".join(failures) if failures else "rejected:no_spectral_peak"
        else:
            result.estimates_bpm[name] = float(bpm)
            result.quality[name] = (
                f"ok:concentration={peak_fraction:.3f};snr_db={snr_db:.1f};"
                f"separation={'null' if separation is None else f'{separation:.2f}'}"
            )
    return result


def _metrics(pairs: Sequence[tuple[float, float]]) -> dict:
    """MAE/RMSE/bias/LoA/Pearson on validated (reference, estimate) pairs."""
    if not pairs:
        return {"n_pairs": 0, "mae_bpm": None, "rmse_bpm": None, "bias_bpm": None,
                "loa_lower_95_bpm": None, "loa_upper_95_bpm": None, "pearson_r": None}
    ref = np.asarray([p[0] for p in pairs], dtype=float)
    est = np.asarray([p[1] for p in pairs], dtype=float)
    errors = est - ref
    bias = float(errors.mean())
    sd = float(errors.std(ddof=1)) if errors.size > 1 else None
    pearson = None
    if errors.size >= 3 and np.std(ref) > 0 and np.std(est) > 0:
        pearson = float(np.corrcoef(ref, est)[0, 1])
    return {
        "n_pairs": int(errors.size),
        "mae_bpm": float(np.abs(errors).mean()),
        "rmse_bpm": float(np.sqrt(np.mean(errors ** 2))),
        "bias_bpm": bias,
        "loa_lower_95_bpm": (bias - 1.96 * sd) if sd is not None else None,
        "loa_upper_95_bpm": (bias + 1.96 * sd) if sd is not None else None,
        "pearson_r": pearson,
    }


def _pairs_ungated(records: Iterable[WindowResult], estimator: str, roi: Optional[str]) -> list[tuple[float, float]]:
    out = []
    for r in records:
        if roi is not None and r.roi != roi:
            continue
        estimate = r.raw_estimates_bpm.get(estimator)
        if estimate is None or r.reference_bpm is None:
            continue
        out.append((float(r.reference_bpm), float(estimate)))
    return out


def _pairs(records: Iterable[WindowResult], estimator: str, roi: Optional[str] = None) -> list[tuple[float, float]]:
    out = []
    for r in records:
        if roi is not None and r.roi != roi:
            continue
        estimate = r.estimates_bpm.get(estimator)
        if estimate is None or r.reference_bpm is None:
            continue
        out.append((float(r.reference_bpm), float(estimate)))
    return out


def _coverage(records: Sequence[WindowResult], estimator: str, roi: Optional[str] = None) -> dict:
    relevant = [r for r in records if roi is None or r.roi == roi]
    total = len(relevant)
    with_ref = sum(1 for r in relevant if r.reference_bpm is not None)
    with_estimate = sum(1 for r in relevant if r.estimates_bpm.get(estimator) is not None)
    usable = sum(1 for r in relevant if r.estimates_bpm.get(estimator) is not None and r.reference_bpm is not None)
    reasons: dict[str, int] = {}
    for r in relevant:
        quality = r.quality.get(estimator, "unknown")
        if quality.startswith("rejected"):
            bucket = quality.split(":", 1)[1].split("_low")[0][:40]
            reasons[bucket] = reasons.get(bucket, 0) + 1
    return {
        "windows_total": total,
        "windows_with_reference": with_ref,
        "windows_with_estimate": with_estimate,
        "windows_usable_pairs": usable,
        "reference_coverage": (with_ref / total) if total else None,
        "estimate_coverage": (with_estimate / total) if total else None,
        "usable_coverage": (usable / total) if total else None,
        "rejection_rate": (1 - usable / total) if total else None,
        "estimate_rejection_reasons": reasons,
    }


def _participant_bootstrap(per_participant_mae: dict[int, float], *, draws: int = BOOTSTRAP_DRAWS,
                           seed: int = BOOTSTRAP_SEED) -> Optional[dict]:
    keys = sorted(per_participant_mae)
    if len(keys) < 2:
        return None
    values = np.asarray([per_participant_mae[k] for k in keys], dtype=float)
    rng = np.random.default_rng(seed)
    samples = values[rng.integers(0, values.size, size=(draws, values.size))].mean(axis=1)
    return {
        "participants": int(values.size),
        "draws": draws,
        "seed": seed,
        "mean_of_participant_mae_bpm": float(values.mean()),
        "ci95_bpm": [float(np.quantile(samples, 0.025)), float(np.quantile(samples, 0.975))],
        "method": "participant-resampled bootstrap over per-participant mean absolute error",
    }


def aggregate(records: Sequence[WindowResult]) -> dict:
    """Per-ROI, per-estimator, per-participant aggregation with participant-level CIs.

    Three ROIs from one participant are pooled *within* that participant only;
    participant counts are never inflated by ROI counts.
    """
    per_roi: dict[str, dict] = {}
    for roi in ROIS:
        per_roi[roi] = {}
        for estimator in ESTIMATORS:
            pairs = _pairs(records, estimator, roi)
            per_participant: dict[str, list[float]] = {}
            for r in records:
                if r.roi != roi:
                    continue
                estimate = r.estimates_bpm.get(estimator)
                if estimate is None or r.reference_bpm is None:
                    continue
                per_participant.setdefault(str(r.subject), []).append(abs(estimate - r.reference_bpm))
            per_participant_mae = {k: float(np.mean(v)) for k, v in per_participant.items()}
            per_roi[roi][estimator] = {
                **_metrics(pairs),
                **_coverage(records, estimator, roi),
                "participants_with_pairs": len(per_participant_mae),
                "per_participant": {k: round(v, 6) for k, v in sorted(per_participant_mae.items(), key=lambda kv: int(kv[0]))},
                "participant_bootstrap": _participant_bootstrap({int(k): v for k, v in per_participant_mae.items()}),
            }

    per_participant_all: dict[str, dict] = {}
    for r in records:
        entry = per_participant_all.setdefault(str(r.subject), {
            "subject": r.subject,
            "windows_total": 0,
            "rois_present": set(),
            "estimates": {name: {"n_pairs": 0, "abs_error_sum": 0.0} for name in ESTIMATORS},
        })
        entry["windows_total"] += 1
        entry["rois_present"].add(r.roi)
        for estimator in ESTIMATORS:
            estimate = r.estimates_bpm.get(estimator)
            if estimate is not None and r.reference_bpm is not None:
                entry["estimates"][estimator]["n_pairs"] += 1
                entry["estimates"][estimator]["abs_error_sum"] += abs(estimate - r.reference_bpm)
    participant_summary = {}
    for key, entry in sorted(per_participant_all.items(), key=lambda kv: int(kv[0])):
        participant_summary[key] = {
            "subject": entry["subject"],
            "rois_present": sorted(entry["rois_present"]),
            "windows_total": entry["windows_total"],
            "mae_bpm": {
                name: (entry["estimates"][name]["abs_error_sum"] / entry["estimates"][name]["n_pairs"])
                if entry["estimates"][name]["n_pairs"] else None
                for name in ESTIMATORS
            },
            "n_pairs": {name: entry["estimates"][name]["n_pairs"] for name in ESTIMATORS},
        }
    # Participant-level (all ROIs pooled within participant) MAE per estimator
    pooled_participant_mae = {}
    for name in ESTIMATORS:
        values = {int(k): v["mae_bpm"][name] for k, v in participant_summary.items() if v["mae_bpm"][name] is not None}
        pooled_participant_mae[name] = {
            "participant_mae_bpm": {str(k): round(vv, 6) for k, vv in sorted(values.items())},
            "participant_bootstrap": _participant_bootstrap(values),
        }

    # Post-hoc, descriptive only: what the frozen gates remove. Never a protocol
    # result and never compared against the provider's baseline.
    ungated: dict[str, dict] = {}
    for roi in ROIS:
        ungated[roi] = {}
        for estimator in ESTIMATORS:
            pairs = _pairs_ungated(records, estimator, roi)
            ungated[roi][estimator] = _metrics(pairs)
    ungated["_note"] = ("Descriptive sensitivity analysis computed after the frozen protocol ran: these are the "
                        "same spectral peaks WITHOUT the quality gates. They are not rPPG-10 results and must "
                        "not be quoted as such; compare them with the gated numbers to see what the gates remove.")

    # Descriptive, ungated, provider-comparable: average the three ROIs of the same
    # window (the provider's baseline uses a combined ROI with non-overlapping 30 s
    # windows) and score that average against the ECG reference. This is the only
    # figure that can be read alongside the provider's published table, and it is
    # still NOT a validation result.
    roi_means: dict[tuple, dict] = {}
    for r in records:
        key = (r.subject, r.start_s)
        entry = roi_means.setdefault(key, {"reference_bpm": r.reference_bpm, "raw": {}, "gated": {}})
        for estimator in ESTIMATORS:
            entry["raw"].setdefault(estimator, []).append(r.raw_estimates_bpm.get(estimator))
            entry["gated"].setdefault(estimator, []).append(r.estimates_bpm.get(estimator))
    combined = {}
    for estimator in ESTIMATORS:
        ungated_pairs, gated_pairs = [], []
        gated_participants: set[int] = set()
        per_participant_raw: dict[int, list[float]] = {}
        for (subject, _start), entry in roi_means.items():
            if entry["reference_bpm"] is None:
                continue
            raw = [v for v in entry["raw"].get(estimator, []) if v is not None]
            if raw:
                error = abs(float(np.mean(raw)) - entry["reference_bpm"])
                ungated_pairs.append((entry["reference_bpm"], float(np.mean(raw))))
                per_participant_raw.setdefault(subject, []).append(error)
            gated = [v for v in entry["gated"].get(estimator, []) if v is not None]
            if gated:
                gated_pairs.append((entry["reference_bpm"], float(np.mean(gated))))
                gated_participants = gated_participants | {subject}
        subject_mae = {k: float(np.mean(v)) for k, v in per_participant_raw.items()}
        combined[estimator] = {
            "ungated_combined_roi": dict(_metrics(ungated_pairs), participants=len(per_participant_raw),
                                          median_participant_mae_bpm=(round(float(np.median(list(subject_mae.values()))), 3)
                                                                      if subject_mae else None)),
            "gated_combined_roi": dict(_metrics(gated_pairs), participants=len(gated_participants)),
        }
    combined["_note"] = ("Descriptive only. 'ungated_combined_roi' averages the three ROI estimates of the same "
                         "window (provider-comparable: their baseline uses a combined ROI over non-overlapping 30 s "
                         "windows); 'gated_combined_roi' uses only windows that survived the frozen quality gates. "
                         "Neither is a validation result and neither may be quoted as this project's accuracy.")

    participation = {}
    for estimator in ESTIMATORS:
        contributing = sorted({r.subject for r in records
                               if r.estimates_bpm.get(estimator) is not None and r.reference_bpm is not None})
        participation[estimator] = {
            "participants_with_any_pair": len(contributing),
            "participants": contributing,
            "participants_with_no_pairs": sorted({r.subject for r in records} - set(contributing)),
        }

    selection_bias = {}
    for roi in ROIS:
        for estimator in ESTIMATORS:
            accepted = [r for r in records if r.roi == roi and r.estimates_bpm.get(estimator) is not None
                        and r.reference_bpm is not None]
            rejected = [r for r in records if r.roi == roi and r.estimates_bpm.get(estimator) is None
                        and r.reference_bpm is not None]
            if not accepted or not rejected:
                selection_bias[f"{roi}|{estimator}"] = None
                continue
            selection_bias[f"{roi}|{estimator}"] = {
                "accepted_windows": len(accepted),
                "rejected_windows": len(rejected),
                "accepted_reference_hr_mean_bpm": round(float(np.mean([r.reference_bpm for r in accepted])), 3),
                "rejected_reference_hr_mean_bpm": round(float(np.mean([r.reference_bpm for r in rejected])), 3),
                "difference_bpm": round(float(np.mean([r.reference_bpm for r in accepted])
                                              - np.mean([r.reference_bpm for r in rejected])), 3),
            }

    return {
        "per_roi": per_roi,
        "descriptive_ungated": ungated,
        "combined_roi_descriptive": combined,
        "participation": participation,
        "selection_bias_diagnostic": selection_bias,
        "per_participant": participant_summary,
        "participant_level": pooled_participant_mae,
        "participant_count": len(participant_summary),
        "recording_count": len({(r.subject, r.roi) for r in records}),
        "window_count": len(records),
        "grouping_note": "ROIs are pooled within a participant; participant counts are never "
                         "multiplied by ROI counts.",
    }


def _fmt(value, digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def markdown_report(payload: dict) -> str:
    """Human-readable report; refuses to look like a result when nothing ran."""
    lines = ["# rPPG-10 benchmark report", ""]
    status = payload.get("status", "NOT RUN")
    lines.append(f"**Status:** {status}")
    lines.append("")
    lines.append(f"Protocol: `{payload.get('protocol', {}).get('protocol_version', PROTOCOL_VERSION)}` "
                 f"(frozen {payload.get('protocol', {}).get('frozen_date', PROTOCOL_FROZEN_DATE)})")
    lines.append("")
    if status != "RUN":
        lines += [payload.get("blocking_reason", "Benchmark not executed."), ""]
        lines.append("No accuracy metric exists for rPPG-10 in this project. Nothing here is a result.")
        return "\n".join(lines) + "\n"
    lines.append("## How to read these numbers (read this first)")
    lines.append("")
    results = payload["results"]
    lines.append(
        "Two things must be said together, or the table below will be misread:\n\n"
        "1. **The per-ROI table is availability-conditional.** Those numbers describe only the windows whose "
        "signal passed the frozen quality gates. Check the *usable coverage* column and the participation table: "
        "if coverage is low, the errors describe the easiest windows, not the method's accuracy.\n"
        "2. **The gates-OFF sensitivity analysis (bottom) is what the protocol would report without quality "
        "gating on nearly every window.** For an implementation check, compare that row with the provider's own "
        "published baseline (GREEN MAE 7.57 ± 0.66 BPM using a combined forehead+both-cheek ROI) — not with the "
        "gated row.\n\n"
        "Neither row is a clinical result, and neither may be quoted without the limitations at the end."
    )
    lines.append("")

    lines.append("## Per-ROI results")
    lines.append("")
    lines.append("| ROI | Estimator | n pairs | MAE (BPM) | RMSE (BPM) | Bias (BPM) | LoA 95% | Pearson r | usable coverage | participants | MAE CI95 (BPM) |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for roi, per_estimator in payload["results"]["per_roi"].items():
        for estimator, m in per_estimator.items():
            ci = m.get("participant_bootstrap")
            loa = "—"
            if m.get("loa_lower_95_bpm") is not None:
                loa = f"{m['loa_lower_95_bpm']:.2f} to {m['loa_upper_95_bpm']:.2f}"
            ci_text = "—"
            if ci:
                ci_text = f"{ci['ci95_bpm'][0]:.2f} to {ci['ci95_bpm'][1]:.2f}"
            lines.append(
                f"| {roi} | {estimator} | {m['n_pairs']} | {_fmt(m['mae_bpm'])} | {_fmt(m['rmse_bpm'])} | "
                f"{_fmt(m['bias_bpm'])} | {loa} | {_fmt(m.get('pearson_r'))} | "
                f"{_fmt((m.get('usable_coverage') or 0) * 100, 1)}% | {m['participants_with_pairs']} | {ci_text} |"
            )
    lines.append("")
    inv = payload.get("inventory_summary") or {}
    excluded = inv.get("excluded_subjects") or []
    if excluded:
        lines.append("## Participant exclusions")
        lines.append("")
        lines.append("| Subject | Reason | Provider documentation | Evidence found on disk |")
        lines.append("|---|---|---|---|")
        for entry in excluded:
            doc = entry.get("provider_documentation") or "**none — undocumented exclusion**"
            evidence = entry.get("adapter_derived_evidence") or "—"
            lines.append(f"| {entry['subject']} | {entry['reason']} | {doc} | {evidence} |")
        lines.append("")

    lines.append("## Coverage and rejection accounting")
    lines.append("")
    lines.append("See the JSON report for per-window quality tokens; rejected windows are listed, not hidden.")
    lines.append("")
    results = payload["results"]
    lines.append("## Participation (who the numbers actually describe)")
    lines.append("")
    lines.append("| Estimator | Participants contributing any pair | Participants with no usable window |")
    lines.append("|---|---|---|")
    for estimator, info in results.get("participation", {}).items():
        lines.append(f"| {estimator} | {info['participants_with_any_pair']} of "
                     f"{info['participants_with_any_pair'] + len(info['participants_with_no_pairs'])} "
                     f"| {', '.join(str(s) for s in info['participants_with_no_pairs']) or '—'} |")
    lines.append("")

    lines.append("## Selection-bias diagnostic (accepted vs rejected windows)")
    lines.append("")
    lines.append("If the mean reference HR of accepted windows differs materially from rejected ones, the "
                 "error statistics describe only the easier part of the dataset.")
    lines.append("")
    lines.append("| ROI \| estimator | accepted | rejected | accepted ref HR | rejected ref HR | difference |")
    lines.append("|---|---|---|---|---|---|")
    for key, value in (results.get("selection_bias_diagnostic") or {}).items():
        if not value:
            lines.append(f"| {key} | — | — | — | — | — |")
            continue
        lines.append(f"| {key} | {value['accepted_windows']} | {value['rejected_windows']} | "
                     f"{value['accepted_reference_hr_mean_bpm']:.1f} | {value['rejected_reference_hr_mean_bpm']:.1f} | "
                     f"{value['difference_bpm']:+.1f} |")
    lines.append("")

    combined = results.get("combined_roi_descriptive") or {}
    if combined:
        lines.append("## Provider-comparable view — combined ROI, gates OFF (not a result)")
        lines.append("")
        lines.append(combined.get("_note", ""))
        lines.append("")
        lines.append("| Estimator | n windows | pooled MAE (BPM) | RMSE (BPM) | bias (BPM) | median participant MAE (BPM) | participants |")
        lines.append("|---|---|---|---|---|---|---|")
        for estimator in ESTIMATORS:
            entry = combined.get(estimator) or {}
            row = entry.get("ungated_combined_roi")
            if not row:
                continue
            lines.append(f"| {estimator} | {row['n_pairs']} | {_fmt(row['mae_bpm'])} | {_fmt(row['rmse_bpm'])} | "
                         f"{_fmt(row['bias_bpm'])} | {_fmt(row.get('median_participant_mae_bpm'))} | {row.get('participants')} |")
        lines.append("")

    ungated = results.get("descriptive_ungated") or {}
    if ungated:
        lines.append("## Descriptive sensitivity analysis — gates OFF (not a result)")
        lines.append("")
        lines.append(ungated.get("_note", ""))
        lines.append("")
        lines.append("| ROI | estimator | n pairs | MAE (BPM) | RMSE (BPM) | bias (BPM) |")
        lines.append("|---|---|---|---|---|---|")
        for roi, per_estimator in ungated.items():
            if roi == "_note":
                continue
            for estimator, m in per_estimator.items():
                lines.append(f"| {roi} | {estimator} | {m['n_pairs']} | {_fmt(m['mae_bpm'])} | "
                             f"{_fmt(m['rmse_bpm'])} | {_fmt(m['bias_bpm'])} |")
        lines.append("")

    lines.append("## Interpretation limits (binding)")
    lines.append("")
    for item in payload.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("ECG reference agreement measures pulse-rate agreement only. It does not validate "
                 "PRV/HRV estimation, does not establish clinical validity, and does not generalise "
                 "beyond 26 young Portuguese university students under natural indoor light.")
    return "\n".join(lines) + "\n"
