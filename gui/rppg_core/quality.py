"""Explainable signal-quality assessment for rPPG research windows.

This module separates five concepts that were previously collapsed into a
single spectral-concentration ratio:

1. **Acquisition quality** — pixel clipping, exposure/brightness and dynamic
   range of the captured RGB window.
2. **Tracing/ROI quality** — coverage of usable pixels, face detection and
   tracking stability (supplied by the caller; this module scores them).
3. **Physiological signal quality** — spectral properties of the pulse-band
   estimate: concentration, SNR vs the passband noise floor and separation of
   the selected peak from a competing peak.
4. **Estimator agreement** — spread across independent algorithms/ROIs.
5. **Estimate availability** — the composite verdict every consumer relies on.

A strong spectral peak is *not* proof of pulse origin: every spectral check
exists to reject plausible-but-wrong peaks, and the composite verdict stays
``low_signal_quality`` unless checks that are actually independent of each
other agree. Nothing in this module is a physiological validation; it is a
software-level, conservative gating layer. Thresholds below are documented
research heuristics (2026-11), not calibrated clinical cut-offs.

Statuses produced by :func:`assess_window` are the same tokens used across the
browser app, the Python pipeline and the research backends.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

DEFAULT_PASSBAND_HZ = (0.7, 3.5)

# Documented heuristic research defaults (NOT calibrated clinical cut-offs).
SPECTRAL_MIN_CONCENTRATION = 0.20     # top passband peak / total passband power
SPECTRAL_MIN_SNR_DB = 3.0             # peak power vs median passband power (excl. peak bins)
SPECTRAL_MIN_SEPARATION = 1.5         # top peak vs best competing local maximum (>= 0.25 Hz away)
PEAK_GUARD_RADIUS_HZ = 0.15           # bins around the peak excluded from the noise floor
COMPETITOR_MIN_DISTANCE_HZ = 0.25     # minimum distance to a competing local maximum
AGREEMENT_TOLERANCE_BPM = 12.0        # cross-estimator spread ceiling (browser convention)
CANDIDATE_NEAR_ESTIMATOR_BPM = 6.0    # corrected candidate vs at least one estimator
MIN_WINDOW_SECONDS = 10.0             # minimum duration before any estimate is reported
MIN_SAMPLING_RATE_HZ = 12.0           # below this, passband estimation is not meaningful
MAX_GAP_SECONDS = 0.25                # timestamp gaps longer than this invalidate a window
MIN_ROI_COVERAGE = 0.50               # fraction of samples with a usable ROI
CLIP_MAX_FRACTION = 0.10              # fraction of saturated/black channel values tolerated
MIN_DYNAMIC_RANGE = 6.0               # counts; below this the sensor is effectively flat


@dataclass(frozen=True)
class SpectralQuality:
    peak_hz: float | None
    peak_fraction: float | None
    snr_db: float | None
    separation_ratio: float | None  # None => no competing local maximum found (pass)
    bin_hz: float

    @property
    def passing(self) -> bool:
        if self.peak_hz is None or self.peak_fraction is None or self.snr_db is None:
            return False
        if self.peak_fraction < SPECTRAL_MIN_CONCENTRATION:
            return False
        if self.snr_db < SPECTRAL_MIN_SNR_DB:
            return False
        if self.separation_ratio is not None and self.separation_ratio < SPECTRAL_MIN_SEPARATION:
            return False
        return True

    @property
    def failing_checks(self) -> tuple[str, ...]:
        failing: list[str] = []
        if self.peak_hz is None or self.peak_fraction is None:
            failing.append("no_spectral_peak")
            return tuple(failing)
        if self.peak_fraction < SPECTRAL_MIN_CONCENTRATION:
            failing.append(f"low_concentration_{self.peak_fraction:.3f}")
        if self.snr_db is None or self.snr_db < SPECTRAL_MIN_SNR_DB:
            failing.append(f"low_snr_{(self.snr_db if self.snr_db is not None else float('nan')):.1f}db")
        if self.separation_ratio is not None and self.separation_ratio < SPECTRAL_MIN_SEPARATION:
            failing.append(f"weak_separation_{self.separation_ratio:.2f}")
        return tuple(failing)


def spectral_quality(signal, fs, passband=DEFAULT_PASSBAND_HZ) -> SpectralQuality:
    """Spectral characterization of one de-meaned window. No filtering is applied."""
    x = np.asarray(signal, dtype=float)
    if x.ndim != 1 or len(x) < max(8, int(4 * fs)) or not np.isfinite(x).all():
        return SpectralQuality(None, None, None, None, 0.0)
    centered = x - x.mean()
    if np.std(centered) < 1e-10:
        return SpectralQuality(None, None, None, None, 0.0)
    n = len(centered)
    window = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n) / (n - 1))
    power = np.abs(np.fft.rfft(centered * window)) ** 2
    freqs = np.arange(power.size) * float(fs) / n
    lo, hi = passband
    mask = (freqs >= lo) & (freqs <= hi)
    if not mask.any():
        return SpectralQuality(None, None, None, None, 0.0)
    band_freqs, band = freqs[mask], power[mask]
    total = float(band.sum())
    if not np.isfinite(total) or total <= 0:
        return SpectralQuality(None, None, None, None, 0.0)
    bin_hz = float(freqs[1] - freqs[0]) if len(freqs) > 1 else float(fs / len(freqs))
    peak_index = int(np.argmax(band))
    peak_hz = float(band_freqs[peak_index])
    peak_power = float(band[peak_index])
    peak_fraction = float(band[peak_index] / total)

    # Noise floor: median passband power outside a guard radius around the peak.
    guard = np.abs(band_freqs - peak_hz) > PEAK_GUARD_RADIUS_HZ
    floor_bins = band[guard]
    if floor_bins.size == 0 or float(np.median(floor_bins)) <= 0.0:
        snr_db = None
    else:
        snr_db = float(10.0 * np.log10(peak_power / np.median(floor_bins)))

    # Separation: ratio to the best *other* local maximum at least
    # COMPETITOR_MIN_DISTANCE_HZ away. A flat noise floor has no maxima →
    # separation reported as None (no competitor found), which passes.
    separation_ratio = None
    for i in range(1, len(band) - 1):
        if abs(band_freqs[i] - peak_hz) < COMPETITOR_MIN_DISTANCE_HZ:
            continue
        if band[i] >= band[i - 1] and band[i] >= band[i + 1]:
            ratio = peak_power / max(float(band[i]), 1e-30)
            separation_ratio = ratio if separation_ratio is None else min(separation_ratio, ratio)
    return SpectralQuality(peak_hz, peak_fraction, snr_db, separation_ratio, bin_hz)


@dataclass(frozen=True)
class AcquisitionReport:
    clip_fraction: float          # values at 0 or 255 (per any channel, aggregated)
    underexposed_fraction: float  # near-black pixels across channels
    overexposed_fraction: float   # near-white pixels across channels
    dynamic_range: float          # max-min across all channels (counts)
    mean_brightness: float        # mean across channels (counts)

    @property
    def passing(self) -> bool:
        return (self.clip_fraction <= CLIP_MAX_FRACTION
                and self.dynamic_range >= MIN_DYNAMIC_RANGE)


def acquisition_report(rgb_window) -> AcquisitionReport:
    x = np.asarray(rgb_window, dtype=float)
    if x.ndim != 2 or x.shape[1] < 3 or x.size == 0:
        return AcquisitionReport(clip_fraction=1.0, underexposed_fraction=1.0,
                                 overexposed_fraction=1.0, dynamic_range=0.0, mean_brightness=0.0)
    channels = x[:, :3]
    clip = float(np.mean((channels <= 2) | (channels >= 253)))
    luminance = channels.mean(axis=1)
    under = float(np.mean(luminance <= 8.0))
    over = float(np.mean(luminance >= 248.0))
    dynamic = float(channels.max() - channels.min())
    return AcquisitionReport(clip_fraction=clip, underexposed_fraction=under,
                             overexposed_fraction=over, dynamic_range=dynamic,
                             mean_brightness=float(luminance.mean()))


@dataclass(frozen=True)
class AgreementReport:
    n_valid: int
    spread_bpm: float | None
    within_tolerance: bool
    median_bpm: float | None
    values: tuple[float, ...] = field(default_factory=tuple)

    @property
    def passing(self) -> bool:
        return self.n_valid >= 2 and self.spread_bpm is not None and self.spread_bpm <= AGREEMENT_TOLERANCE_BPM


def agreement_report(estimates: dict[str, float | None], tolerance_bpm: float = AGREEMENT_TOLERANCE_BPM) -> AgreementReport:
    values = sorted(v for v in estimates.values() if v is not None and np.isfinite(v))
    if len(values) < 2:
        return AgreementReport(len(values), None, False, None, tuple(values))
    spread = values[-1] - values[0]
    return AgreementReport(len(values), float(spread), bool(spread <= tolerance_bpm),
                           float(np.median(values)), tuple(values))


@dataclass(frozen=True)
class TraceReport:
    n_samples: int
    duration_s: float
    fs_hz: float | None
    max_gap_s: float | None
    dropped_interval_fraction: float | None

    @property
    def regular(self) -> bool:
        return (self.fs_hz is not None and self.fs_hz >= MIN_SAMPLING_RATE_HZ
                and self.max_gap_s is not None and self.max_gap_s <= MAX_GAP_SECONDS)


def trace_report(timestamps) -> TraceReport:
    t = np.asarray(timestamps, dtype=float)
    n = int(t.size)
    if n < 2 or not np.isfinite(t).all():
        return TraceReport(n, 0.0, None, None, None)
    d = np.diff(t)
    if np.any(d <= 0):
        return TraceReport(n, float(t[-1] - t[0]), None, None, None)
    median_interval = float(np.median(d))
    fs = float(1.0 / median_interval)
    dropped = float(np.mean(d > 1.5 * median_interval))
    return TraceReport(n, float(t[-1] - t[0]), fs, float(d.max()), dropped)


PASS, FAIL, NOT_EVALUATED = "pass", "fail", "not_evaluated"

#: The six explicitly separated quality concepts. These are components of the
#: verdict, never a blended score; each is reported independently by
#: :func:`assess_window` as ``concepts`` in the returned assessment.
QUALITY_CONCEPTS = ("face_tracking", "roi_extraction", "temporal_acquisition",
                    "pulse_signal", "algorithm_agreement", "availability")


def _concepts(face, roi, temporal, pulse, agreement, availability):
    return {"face_tracking": face, "roi_extraction": roi,
            "temporal_acquisition": temporal, "pulse_signal": pulse,
            "algorithm_agreement": agreement, "availability": availability}


@dataclass(frozen=True)
class QualityAssessment:
    status: str           # one of the canonical tokens below
    reason: str           # human-readable explanation
    reasons: tuple[str, ...]  # machine tokens naming every failing check
    scores: dict[str, float | None] = field(default_factory=dict)
    concepts: dict[str, str] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.status == "valid"


def assess_window(*, trace: TraceReport | None = None,
                  acquisition: AcquisitionReport | None = None,
                  spectral: SpectralQuality | None = None,
                  agreement: AgreementReport | None = None,
                  roi_agreement: AgreementReport | None = None,
                  roi_coverage: float | None = None,
                  face_detected: bool = True,
                  tracking_lost: bool = False,
                  excessive_motion: bool = False,
                  candidate_bpm: float | None = None,
                  age_s: float | None = None,
                  min_window_s: float = MIN_WINDOW_SECONDS) -> QualityAssessment:
    """Composite window verdict. Hierarchical; the most fundamental failure wins.

    Estimator agreement is only meaningful once signal quality passes; agreement is
    therefore checked after spectral checks, not instead of them.

    A corrected consensus ``candidate_bpm`` (from legacy motion heuristics) is
    validated against the uncorrected estimates: it must stay within the full
    agreement tolerance of every trustworthy estimator and within half that
    tolerance of at least one, so a heuristic cannot manufacture agreement that
    no estimator supports.
    """
    reasons: list[str] = []
    scores: dict[str, float | None] = {}

    if not face_detected:
        return QualityAssessment("face_not_detected", "No usable face in the camera frame",
                                 ("face_not_detected",), scores,
                                 _concepts(FAIL, NOT_EVALUATED, NOT_EVALUATED,
                                           NOT_EVALUATED, NOT_EVALUATED, FAIL))
    if tracking_lost or (roi_coverage is not None and roi_coverage <= 0.0):
        return QualityAssessment("roi_lost", "Tracked skin regions are lost or occluded",
                                 ("roi_lost",), scores,
                                 _concepts(PASS, FAIL, NOT_EVALUATED,
                                           NOT_EVALUATED, NOT_EVALUATED, FAIL))
    if trace is not None:
        scores.update({"fs_hz": trace.fs_hz, "max_gap_s": trace.max_gap_s,
                       "duration_s": trace.duration_s,
                       "dropped_interval_fraction": trace.dropped_interval_fraction})
        roi_state = NOT_EVALUATED if roi_coverage is None else (PASS if roi_coverage >= MIN_ROI_COVERAGE else FAIL)
        if trace.fs_hz is None or trace.fs_hz < MIN_SAMPLING_RATE_HZ:
            return QualityAssessment("insufficient_frames",
                                     f"Effective sampling rate too low or invalid (fs={trace.fs_hz})",
                                     ("insufficient_frames",), scores,
                                     _concepts(PASS, roi_state, FAIL, NOT_EVALUATED, NOT_EVALUATED, FAIL))
        if trace.max_gap_s is not None and trace.max_gap_s > MAX_GAP_SECONDS:
            return QualityAssessment("irregular_timestamps",
                                     f"Timestamp gap {trace.max_gap_s:.2f}s exceeds {MAX_GAP_SECONDS}s",
                                     ("irregular_timestamps",), scores,
                                     _concepts(PASS, roi_state, FAIL, NOT_EVALUATED, NOT_EVALUATED, FAIL))
        if trace.duration_s < min_window_s:
            remaining = min_window_s - trace.duration_s
            return QualityAssessment("warming_up", f"Acquire {remaining:.1f} more seconds",
                                     ("warming_up",), scores,
                                     _concepts(PASS, roi_state, NOT_EVALUATED,
                                               NOT_EVALUATED, NOT_EVALUATED, FAIL))
    if excessive_motion:
        return QualityAssessment("excessive_motion", "Excessive face displacement; hold still",
                                 ("excessive_motion",), scores,
                                 _concepts(PASS, PASS if roi_coverage is None or roi_coverage >= MIN_ROI_COVERAGE else FAIL,
                                           PASS, FAIL, NOT_EVALUATED, FAIL))
    if acquisition is not None:
        scores.update({"clip_fraction": acquisition.clip_fraction,
                       "dynamic_range": acquisition.dynamic_range,
                       "mean_brightness": acquisition.mean_brightness,
                       "underexposed_fraction": acquisition.underexposed_fraction,
                       "overexposed_fraction": acquisition.overexposed_fraction})
        if not acquisition.passing:
            reasons.append("acquisition_clipping_or_flat" if acquisition.clip_fraction > CLIP_MAX_FRACTION
                           else "acquisition_low_dynamic_range")
    roi_state = NOT_EVALUATED if roi_coverage is None else (PASS if roi_coverage >= MIN_ROI_COVERAGE else FAIL)
    if roi_coverage is not None:
        scores["roi_coverage"] = float(roi_coverage)
        if roi_coverage < MIN_ROI_COVERAGE:
            reasons.append(f"insufficient_roi_coverage_{roi_coverage:.2f}")
    pulse_state = NOT_EVALUATED
    if spectral is not None:
        scores.update({"peak_fraction": spectral.peak_fraction, "snr_db": spectral.snr_db,
                       "separation_ratio": spectral.separation_ratio, "peak_hz": spectral.peak_hz})
        pulse_state = PASS if spectral.passing else FAIL
        if not spectral.passing:
            reasons.extend(spectral.failing_checks)
    if acquisition is not None and not acquisition.passing:
        pulse_state = FAIL
    agreement_state = NOT_EVALUATED
    agreement_values: list[float] = []
    if agreement is not None:
        scores.update({"agreement_spread_bpm": agreement.spread_bpm,
                       "estimators_within_tolerance": float(agreement.within_tolerance)})
        agreement_values.extend(agreement.values)
        if agreement.n_valid >= 2 and agreement.spread_bpm is not None:
            agreement_state = PASS if agreement.spread_bpm <= AGREEMENT_TOLERANCE_BPM else FAIL
            if agreement.spread_bpm > AGREEMENT_TOLERANCE_BPM:
                reasons.append(f"estimator_disagreement_{agreement.spread_bpm:.1f}bpm")
    # Cross-ROI agreement: independent skin regions must not yield divergent
    # estimates, else the consensus is unsupported even when per-ROI spectra look clean.
    roi_agreement_state = NOT_EVALUATED
    if roi_agreement is not None:
        scores.update({"roi_agreement_spread_bpm": roi_agreement.spread_bpm,
                       "roi_estimators_within_tolerance": float(roi_agreement.within_tolerance)})
        agreement_values.extend(roi_agreement.values)
        if roi_agreement.n_valid >= 2 and roi_agreement.spread_bpm is not None:
            roi_agreement_state = PASS if roi_agreement.spread_bpm <= AGREEMENT_TOLERANCE_BPM else FAIL
            if roi_agreement.spread_bpm > AGREEMENT_TOLERANCE_BPM:
                reasons.append(f"roi_estimator_disagreement_{roi_agreement.spread_bpm:.1f}bpm")
    # A corrected consensus candidate must not override independent estimates.
    # With no trustworthy estimator anchor, a heuristic-manufactured consensus
    # cannot be validated and must be rejected.
    if candidate_bpm is not None:
        if not agreement_values:
            reasons.append("candidate_no_estimator_backing")
        elif not np.isfinite(candidate_bpm):
            reasons.append("candidate_not_finite")
        else:
            candidate_bpm = float(candidate_bpm)
            within_all = all(abs(candidate_bpm - v) <= AGREEMENT_TOLERANCE_BPM for v in agreement_values)
            near_one = any(abs(candidate_bpm - v) <= CANDIDATE_NEAR_ESTIMATOR_BPM for v in agreement_values)
            if not (within_all and near_one):
                reasons.append("candidate_disagrees_with_estimators")
    if reasons:
        return QualityAssessment("low_signal_quality",
                                 "Inadequate signal quality: " + ", ".join(reasons),
                                 tuple(reasons), scores,
                                 _concepts(PASS, roi_state, PASS, pulse_state, agreement_state, FAIL))
    return QualityAssessment("valid", "Signal, acquisition and estimator agreement all pass",
                             (), scores,
                             _concepts(PASS, roi_state, PASS,
                                       pulse_state if pulse_state != NOT_EVALUATED else PASS,
                                       agreement_state if agreement_state != NOT_EVALUATED else PASS, PASS))
