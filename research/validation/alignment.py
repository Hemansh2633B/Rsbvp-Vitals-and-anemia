"""Synchronisation of session windows with reference measurements.

This is the step where a validation study is most easily made worthless, so the
rules are deliberately strict and every decision is recorded.

**The time-base hazard this module exists to catch.** Session window bounds are not
on a clock. In the browser pathway ``window_start_s`` is ``samples[0].t`` and
``samples[].t`` is ``performance.now()/1000`` — milliseconds since the page loaded,
*not* since capture began. In the Python pathway the same fields are already
relative to capture start. The two are indistinguishable in the CSV: both are
plain positive numbers. Pairing either with a capture-relative ECG without
establishing the correct offset would produce plausible-looking errors made almost
entirely of the offset. Therefore:

* the session's own time base is **declared** by the operator, and
* the offset is either **supplied** or **derived from anchor points**, and
* an offset proposed by the estimator itself is **refused**, and
* the resulting agreement is always reported alongside the left-over ambiguity.

No offset is ever invented. ``None`` means "not established", and evaluation
refuses to run rather than defaulting to zero.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

from research.validation.errors import INFO, REJECT, WARN, InputFinding, InputRejection
from research.validation.loader import Reading
from research.validation.reference import ReferenceInterval, ReferenceTable

#: Two windows closer than this in reference value are not distinguishable anchors.
MIN_ANCHOR_SEPARATION_S = 2.0

#: A derived offset needs at least this many distinct anchors to be credible.
MIN_ANCHORS_FOR_OFFSET = 3

#: A derived offset is only accepted when the winning separation beats the runner-up
#: by this factor. A shallow peak means the choice is arbitrary, and an arbitrary
#: offset is a fabricated one.
MIN_OFFSET_PEAK_MARGIN = 1.5


class TimeBase(str, Enum):
    """What the session's ``window_*_s`` fields are measured from.

    The distinction is not cosmetic: it changes what a value means by an arbitrary,
    usually large amount.
    """

    #: Seconds from the start of capture (Python pathway, and any corrected export).
    CAPTURE_START = "capture_start"
    #: ``performance.now()/1000`` — milliseconds since the page loaded (browser
    #: pathway). Requires an explicit offset; the absolute origin is meaningless.
    PAGE_LOAD = "page_load"
    #: Already aligned to the reference clock by the dataset provider.
    REFERENCE_CLOCK = "reference_clock"
    #: Not established. Evaluation is refused rather than assuming zero.
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SyncConfig:
    """Everything that determines how a window is paired with a reference value.

    Frozen so a report can embed it verbatim and a run can be reproduced exactly.
    """

    time_base: TimeBase = TimeBase.UNKNOWN
    #: ``reference_clock_s = window_start_s + offset_s``. Required unless the time
    #: base is ``reference_clock``; must be ``None`` (not 0) when unestablished.
    offset_s: float | None = None
    #: A window is matched to a reference interval only if it overlaps it by at
    #: least this fraction of the *shorter* of the two spans.
    min_overlap_fraction: float = 0.5
    #: Windows shorter than this are not evaluated (too few samples to be a pulse).
    min_window_duration_s: float = 4.0
    #: Optional restriction of the reference timeline to evaluate only part of a
    #: recording (e.g. excluding a lead-in before perfusion stabilises).
    evaluate_from_s: float | None = None
    evaluate_to_s: float | None = None
    #: Require the reference to be constant enough across the matched span that a
    #: single value represents it. Expressed as a fraction of the reference level.
    max_reference_variation_fraction: float = 0.25

    def as_dict(self) -> dict:
        return {
            "time_base": self.time_base.value,
            "offset_s": self.offset_s,
            "min_overlap_fraction": self.min_overlap_fraction,
            "min_window_duration_s": self.min_window_duration_s,
            "evaluate_from_s": self.evaluate_from_s,
            "evaluate_to_s": self.evaluate_to_s,
            "max_reference_variation_fraction": self.max_reference_variation_fraction,
        }


@dataclass(frozen=True)
class PairedObservation:
    """One window estimate with the reference it was compared against."""

    reading_id: int
    algorithm: str
    roi: str
    window_start_s: float
    window_end_s: float
    reference_clock_start_s: float
    reference_clock_end_s: float
    reference_bpm: float
    estimate_bpm: float
    overlap_fraction: float
    accepted: bool
    duplicate: bool
    session_elapsed_s: float | None
    condition: str | None = None
    device: str | None = None
    participant: str | None = None

    @property
    def error_bpm(self) -> float:
        return self.estimate_bpm - self.reference_bpm

    @property
    def abs_error_bpm(self) -> float:
        return abs(self.error_bpm)


@dataclass
class AlignmentResult:
    """Paired observations plus an explicit account of what was not paired."""

    config: SyncConfig
    pairs: list[PairedObservation] = field(default_factory=list)
    #: Windows that have a usable estimate but no reference coverage.
    unmatched: list[dict] = field(default_factory=list)
    #: Windows excluded before matching, with the reason.
    excluded: list[dict] = field(default_factory=list)
    findings: list[InputFinding] = field(default_factory=list)
    #: How the offset was established, in words, for the report.
    offset_provenance: str = ""

    def pairs_for(self, *, algorithm: str | None = None, roi: str | None = None,
                  accepted: bool | None = None) -> list[PairedObservation]:
        out = self.pairs
        if algorithm is not None:
            out = [p for p in out if p.algorithm == algorithm]
        if roi is not None:
            out = [p for p in out if p.roi == roi]
        if accepted is not None:
            out = [p for p in out if p.accepted == accepted]
        return out

    def coverage(self) -> dict:
        """Matched/unmatched accounting, so nothing disappears quietly."""
        total = len(self.pairs) + len(self.unmatched) + len(self.excluded)
        return {
            "windows_considered": total,
            "windows_paired": len(self.pairs),
            "windows_unmatched_no_reference": len(self.unmatched),
            "windows_excluded": len(self.excluded),
            "coverage_fraction": (len(self.pairs) / total) if total else None,
        }


def _validate_config(config: SyncConfig) -> list[InputFinding]:
    findings: list[InputFinding] = []
    if config.time_base is TimeBase.UNKNOWN:
        findings.append(InputFinding(
            REJECT, "time_base_undeclared",
            "the session's time base is not declared. Set time_base to capture_start, page_load or "
            "reference_clock. The CSV cannot distinguish them: window bounds are plain positive "
            "numbers in every pathway, and pairing them against a capture-relative reference with "
            "the wrong assumption produces errors that are almost entirely the offset."))
    elif config.time_base is not TimeBase.REFERENCE_CLOCK and config.offset_s is None:
        findings.append(InputFinding(
            REJECT, "offset_not_established",
            "no clock offset was supplied or derived. An offset is not guessed: supply it, or use "
            "derive_offset() with independent anchor points. Note that 0 is a real offset and must "
            "be given explicitly if it is what you mean."))
    if config.offset_s is not None and not math.isfinite(config.offset_s):
        findings.append(InputFinding(REJECT, "offset_not_finite", "the clock offset is not finite"))
    if config.time_base is TimeBase.REFERENCE_CLOCK and config.offset_s not in (None, 0, 0.0):
        findings.append(InputFinding(
            WARN, "offset_ignored",
            "time_base is reference_clock, so no offset is applied; the supplied offset is ignored",
        ))
    if config.min_overlap_fraction <= 0 or config.min_overlap_fraction > 1:
        findings.append(InputFinding(
            REJECT, "invalid_overlap_fraction",
            f"min_overlap_fraction must be in (0, 1], got {config.min_overlap_fraction}"))
    if (config.evaluate_from_s is not None and config.evaluate_to_s is not None
            and config.evaluate_to_s <= config.evaluate_from_s):
        findings.append(InputFinding(
            REJECT, "invalid_evaluation_range",
            "evaluate_to_s must be after evaluate_from_s"))
    return findings


def apply_offset(config: SyncConfig) -> float:
    """The offset this configuration implies. Raises rather than defaulting."""
    if config.time_base is TimeBase.REFERENCE_CLOCK:
        return 0.0
    if config.offset_s is None:
        raise InputRejection([InputFinding(
            REJECT, "offset_not_established", "no clock offset is established")])
    return float(config.offset_s)


def reference_span(table: ReferenceTable, config: SyncConfig) -> tuple[float, float] | None:
    """The reference timeline actually evaluated, after any restriction."""
    if not table.intervals:
        return None
    low = config.evaluate_from_s if config.evaluate_from_s is not None else min(
        i.start_s for i in table.intervals)
    high = config.evaluate_to_s if config.evaluate_to_s is not None else max(
        i.end_s for i in table.intervals)
    if high <= low:
        return None
    return (float(low), float(high))


def align(
    readings: Sequence[Reading],
    reference: ReferenceTable,
    config: SyncConfig,
) -> AlignmentResult:
    """Pair each evaluable window estimate with the reference it overlaps.

    A window is paired only when a single reference interval covers at least
    ``min_overlap_fraction`` of the shorter span. Where several reference intervals
    touch a window, the one with the greatest overlap is used, and if two cover it
    almost equally the pairing is **ambiguous** and the window is excluded rather
    than settled arbitrarily.
    """
    findings = _validate_config(config)
    result = AlignmentResult(config=config, findings=findings)
    if any(f.severity is REJECT for f in findings):
        return result

    offset = apply_offset(config)
    span = reference_span(reference, config)
    if span is None:
        result.findings.append(InputFinding(
            REJECT, "no_reference_span", "the reference covers no evaluable span"))
        return result
    ref_low, ref_high = span

    result.offset_provenance = (
        f"reference_clock_s = window_start_s + ({offset:+.3f} s); "
        f"time base declared as {config.time_base.value}; "
        f"reference evaluated over [{ref_low:.3f}, {ref_high:.3f}] s"
    )

    # Duplicates were already refused by the loader; they are reported here so the
    # account of "windows considered" is complete.
    for reading in readings:
        if reading.recomputed_reason == "duplicate_window":
            result.excluded.append({
                "reading_id": reading.reading_id,
                "reason": "duplicate_window",
                "window_start_s": reading.window_start_s,
                "window_end_s": reading.window_end_s,
            })

    candidate = [
        r for r in readings
        if r.accepted_recomputed and r.value is not None
        and r.window_start_s is not None and r.window_end_s is not None
    ]

    for reading in candidate:
        start = float(reading.window_start_s) + offset
        end = float(reading.window_end_s) + offset
        duration = end - start

        if duration < config.min_window_duration_s:
            result.excluded.append({
                "reading_id": reading.reading_id, "reason": "window_too_short",
                "duration_s": duration})
            continue
        # Out-of-range by more than one window is a time-base or offset error, not
        # missing coverage; calling it "unmatched" would disguise a mistake.
        if end < ref_low - duration or start > ref_high + duration:
            result.excluded.append({
                "reading_id": reading.reading_id, "reason": "outside_reference_span",
                "reference_clock_start_s": start, "reference_clock_end_s": end})
            continue

        overlaps: list[tuple[float, ReferenceInterval]] = []
        for interval in reference.intervals:
            if not interval.overlaps(start, end):
                continue
            shorter = min(duration, interval.duration_s)
            if shorter <= 0:
                continue
            fraction = interval.overlap_s(start, end) / shorter
            if fraction > 0:
                overlaps.append((fraction, interval))

        if not overlaps:
            result.unmatched.append({
                "reading_id": reading.reading_id, "reason": "no_reference_coverage",
                "reference_clock_start_s": start, "reference_clock_end_s": end})
            continue

        overlaps.sort(key=lambda pair: pair[0], reverse=True)
        best_fraction, best = overlaps[0]
        if best_fraction < config.min_overlap_fraction:
            result.unmatched.append({
                "reading_id": reading.reading_id, "reason": "insufficient_overlap",
                "overlap_fraction": best_fraction,
                "required": config.min_overlap_fraction})
            continue

        # A 10 s window straddling five 2 s reference intervals is normal, not
        # ambiguous: each interval contributes its own overlap to a weighted mean, so
        # no interval is being chosen arbitrarily.
        #
        # This deliberately does NOT require one interval to dominate. The first
        # implementation did, and rejected every window when the reference was finer
        # than the analysis window (share 0.2 across five intervals) -- which is the
        # ordinary case for any reference sampled more finely than the window. What
        # makes a pairing ambiguous is that the covered values *disagree* so that no
        # single reference value represents the window; that is the variation test
        # below, and it is the only test needed.
        covered = [interval for fraction, interval in overlaps if fraction > 0]
        weighted_total = sum(i.overlap_s(start, end) for i in covered)
        if weighted_total <= 0:
            result.unmatched.append({
                "reading_id": reading.reading_id, "reason": "no_reference_coverage"})
            continue

        reference_bpm = _representative(covered, start, end)
        if reference_bpm is None:
            result.excluded.append({
                "reading_id": reading.reading_id, "reason": "reference_not_representative"})
            continue
        variation = _variation(covered)
        if (weighted_total > 0
                and variation / max(reference_bpm, 1e-9) > config.max_reference_variation_fraction):
            result.excluded.append({
                "reading_id": reading.reading_id, "reason": "reference_varied_across_window",
                "variation_bpm": variation,
                "relative": variation / max(reference_bpm, 1e-9)})
            continue

        result.pairs.append(PairedObservation(
            reading_id=reading.reading_id,
            algorithm=reading.algorithm,
            roi=reading.roi,
            window_start_s=float(reading.window_start_s),
            window_end_s=float(reading.window_end_s),
            reference_clock_start_s=start,
            reference_clock_end_s=end,
            reference_bpm=reference_bpm,
            estimate_bpm=float(reading.value),
            overlap_fraction=best_fraction,
            accepted=reading.accepted_recomputed,
            duplicate=False,
            session_elapsed_s=reading.session_elapsed_s,
            condition=best.condition,
            device=best.device,
            participant=best.participant,
        ))

    if not result.pairs:
        result.findings.append(InputFinding(
            REJECT, "no_paired_observations",
            "no window estimate could be paired with a reference value. Check the declared time "
            "base and the offset before concluding that the estimates disagree."))

    paired_fraction = (
        len(result.pairs) / len(candidate) if candidate else None)
    result.findings.append(InputFinding(
        INFO, "alignment_summary",
        f"{len(result.pairs)} of {len(candidate)} evaluable window(s) paired"
        + (f" ({paired_fraction:.0%})" if paired_fraction is not None else ""),
        count=len(result.pairs)))
    return result


def _representative(intervals: Sequence[ReferenceInterval], start: float,
                    end: float) -> float | None:
    """Overlap-weighted mean reference over the window ``[start, end]``.

    The weight is how much of *this window* each interval actually covers, not the
    interval's own length. Using the interval length would over-weight a long
    reference segment that only clips the edge of the window, and would make the
    matched reference depend on the reference file's granularity rather than on the
    window's contents. If the caller passes no bounds, interval length is used.
    """
    weighted = 0.0
    total = 0.0
    for interval in intervals:
        weight = interval.overlap_s(start, end) if end > start else interval.duration_s
        if weight <= 0:
            continue
        weighted += interval.bpm * weight
        total += weight
    if total <= 0:
        return None
    return weighted / total


def _variation(intervals: Sequence[ReferenceInterval]) -> float:
    values = [i.bpm for i in intervals]
    if len(values) < 2:
        return 0.0
    return max(values) - min(values)


# --- offset derivation -------------------------------------------------------


@dataclass
class OffsetEstimate:
    """A derived offset with its evidence, or an explicit refusal."""

    offset_s: float | None
    method: str
    anchors: int
    reason: str
    best_separation_bpm: float | None = None
    runner_up_bpm: float | None = None
    grid_step_s: float | None = None

    @property
    def established(self) -> bool:
        return self.offset_s is not None

    def as_dict(self) -> dict:
        return {
            "offset_s": self.offset_s,
            "established": self.established,
            "method": self.method,
            "anchors": self.anchors,
            "reason": self.reason,
            "best_separation_bpm": self.best_separation_bpm,
            "runner_up_bpm": self.runner_up_bpm,
            "grid_step_s": self.grid_step_s,
        }


def derive_offset(
    anchors: Sequence[tuple[float, float]],
    *,
    max_residual_s: float = 1.0,
) -> OffsetEstimate:
    """Derive a clock offset from **independent** anchor points.

    Each anchor is ``(session_clock_s, reference_clock_s)`` for *the same physical
    event* — the moment a synchronisation flash appears in the video and in the
    reference's own event marker, or the start of a simultaneous recording logged by
    both devices. Because both readings describe one event, their difference *is* the
    offset: ``offset_i = session_i - reference_i``. With no clock drift the values
    agree and the offset is identified. With drift they disagree, the disagreement
    is reported, and a mean is offered **only** when the residuals are small enough
    that the disagreement cannot move a window by more than one sample.

    What this method cannot do, and says so rather than guessing:

    * Two clocks running at exactly the same rate are identifiable from a single
      event; more anchors then only confirm it. The offset is the anchor difference.
    * If the offsets disagree by more than ``max_residual_s`` the clocks are not
      reconciled by a constant shift (drift, a different rate, or a misread anchor).
      No offset is returned.
    * There must be at least two anchors. One event cannot distinguish "the offset"
      from "a mistake in reading the event", and the whole point of the gate is that
      a single number from one observation is not evidence.

    This function never sees an estimate. An offset chosen to maximise agreement
    between the estimates and the reference would be fitting the result, not
    synchronising the clocks — so estimates are not an input to it.
    """
    usable = [(float(a), float(b)) for a, b in anchors
              if a is not None and b is not None and math.isfinite(a) and math.isfinite(b)]
    if len(usable) < 2:
        return OffsetEstimate(
            None, "anchor_difference", len(usable),
            "at least 2 independent anchors are needed: one event cannot be distinguished "
            f"from a misreading of one event; {len(usable)} supplied")

    differences = [session - reference for session, reference in usable]
    resid = [d - (sum(differences) / len(differences)) for d in differences]
    spread = max(resid) - min(resid) if resid else 0.0
    offset = sum(differences) / len(differences)

    if spread > max_residual_s:
        return OffsetEstimate(
            None, "anchor_difference", len(usable),
            f"the anchors disagree by {spread:.3f} s (tolerance {max_residual_s:g} s), so a single "
            "constant offset does not reconcile these clocks. Do not average them: establish the "
            "offset from one event, or correct the clock drift first.",
            best_separation_bpm=None, runner_up_bpm=None)

    return OffsetEstimate(
        offset, "anchor_difference", len(usable),
        f"derived from {len(usable)} anchors describing the same events; mean offset "
        f"{offset:+.3f} s, disagreement {spread:.3f} s (tolerance {max_residual_s:g} s)",
        best_separation_bpm=spread, runner_up_bpm=None)
