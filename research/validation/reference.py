"""Independent reference (ground-truth) pulse measurements.

A "reference" here means a measurement from a **different modality** — an ECG, a
chest-strap, or a commercial pulse oximeter — with its own timestamps. It is never
derived from the RSBVP estimate, and this module has no access to the estimates at
all. That separation is what makes the comparison meaningful; a reference computed
from the thing being evaluated would guarantee agreement and prove nothing.

Two accepted layouts, both plain CSV:

``interval`` (preferred) — one row per reference segment::

    start_s,end_s,bpm          0,10,71.4
                               10,20,71.9

``samples`` — one row per reference reading, resampled internally::

    t_s,bpm                    0.0,71.4
                               1.0,71.2

A ``condition``/``device``/``participant`` column is carried through when present,
for stratification, but is never required and never used as an identity.
"""
from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research.validation.errors import INFO, REJECT, WARN, InputFinding, InputRejection

#: Bounds that catch a unit error (Hz vs BPM) or a lost reference sweep. These are
#: the same data-hygiene bounds the session layer uses; they are NOT healthy ranges.
REFERENCE_PLAUSIBLE_BPM = (20.0, 250.0)

#: A reference table covering less than this is not worth evaluating.
MIN_REFERENCE_SPAN_S = 5.0


@dataclass(frozen=True)
class ReferenceInterval:
    """One reference estimate covering ``[start_s, end_s)``."""

    start_s: float
    end_s: float
    bpm: float
    condition: str | None = None
    device: str | None = None
    participant: str | None = None

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s

    def overlaps(self, start_s: float, end_s: float) -> bool:
        return self.start_s < end_s and start_s < self.end_s

    def overlap_s(self, start_s: float, end_s: float) -> float:
        return max(0.0, min(self.end_s, end_s) - max(self.start_s, start_s))


@dataclass
class ReferenceTable:
    """A validated reference recording."""

    source: str
    interval_mode: bool
    intervals: list[ReferenceInterval]
    findings: list[InputFinding] = field(default_factory=list)
    synthetic: bool = False

    @property
    def span_s(self) -> tuple[float, float]:
        if not self.intervals:
            return (0.0, 0.0)
        return (min(i.start_s for i in self.intervals), max(i.end_s for i in self.intervals))

    @property
    def duration_s(self) -> float:
        start, end = self.span_s
        return end - start

    def as_samples(self, *, step_s: float) -> list[tuple[float, float]]:
        """Reference value at the centre of each interval, as (centre_s, bpm)."""
        return [(0.5 * (i.start_s + i.end_s), i.bpm) for i in self.intervals]

    def metadata_values(self, name: str) -> dict[str, int]:
        """Distinct non-null values of a stratifier, with counts."""
        values: dict[str, int] = {}
        for interval in self.intervals:
            value = getattr(interval, name, None)
            if value:
                values[value] = values.get(value, 0) + 1
        return dict(sorted(values.items()))


def _detect_synthetic(text: str) -> bool:
    lowered = text.lower()
    return "synthetic" in lowered or "fixture" in lowered


def load_reference(
    path: str | Path | io.TextIOBase,
    *,
    source_name: str | None = None,
) -> ReferenceTable:
    """Load and validate a reference CSV.

    Raises :class:`InputRejection` when the file cannot be used at all; warnings
    (for example a gap in coverage) are carried on the returned table.
    """
    if hasattr(path, "read"):
        text = path.read()  # type: ignore[union-attr]
        name = source_name or "<stream>"
    else:
        p = Path(path)
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            raise InputRejection([
                InputFinding(REJECT, "unreadable_file", f"cannot read {p}: {exc}", source=str(p))
            ]) from exc
        name = source_name or p.name

    if not text.strip():
        raise InputRejection([
            InputFinding(REJECT, "empty_reference", "the reference CSV is empty", source=name)
        ])

    synthetic = _detect_synthetic(name)
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise InputRejection([
            InputFinding(REJECT, "no_reference_header", "the reference CSV has no header row",
                         source=name)
        ])
    columns = [(c or "").strip() for c in reader.fieldnames]
    present = set(columns)

    has_interval = {"start_s", "end_s", "bpm"}.issubset(present)
    has_samples = {"t_s", "bpm"}.issubset(present)
    if not has_interval and not has_samples:
        raise InputRejection([
            InputFinding(
                REJECT, "unrecognised_reference_layout",
                "the reference CSV needs either start_s,end_s,bpm (intervals) or t_s,bpm (samples); "
                f"found columns: {', '.join(c for c in columns if c)}",
                source=name)
        ])

    findings: list[InputFinding] = []
    if has_interval and has_samples:
        findings.append(InputFinding(
            INFO, "ambiguous_reference_layout",
            "the file has both interval and sample columns; the interval layout is used",
            source=name))

    rows = list(reader)
    if not rows:
        raise InputRejection([
            InputFinding(REJECT, "no_reference_rows", "the reference CSV has no data rows", source=name)
        ])

    intervals: list[ReferenceInterval] = []
    for index, raw in enumerate(rows, start=2):
        row = {(k or "").strip(): (v if isinstance(v, str) else "") for k, v in raw.items() if k}
        if not any(v.strip() for v in row.values()):
            continue
        condition = (row.get("condition") or "").strip() or None
        device = (row.get("device") or "").strip() or None
        participant = (row.get("participant") or "").strip() or None

        if has_interval:
            start = _number(row.get("start_s"), "start_s", index, name, findings)
            end = _number(row.get("end_s"), "end_s", index, name, findings)
            bpm = _number(row.get("bpm"), "bpm", index, name, findings)
            if start is None or end is None or bpm is None:
                continue
            if end <= start:
                findings.append(InputFinding(
                    REJECT, "invalid_reference_interval",
                    f"end_s ({end}) is not after start_s ({start})", source=name, row=index))
                continue
            intervals.append(ReferenceInterval(start, end, bpm, condition, device, participant))
        else:
            t = _number(row.get("t_s"), "t_s", index, name, findings)
            bpm = _number(row.get("bpm"), "bpm", index, name, findings)
            if t is None or bpm is None:
                continue
            intervals.append(ReferenceInterval(t, t, bpm, condition, device, participant))

    if not intervals:
        raise InputRejection(findings + [InputFinding(
            REJECT, "no_valid_reference_rows", "no reference row could be read", source=name)])

    # Sample layout: convert to a piecewise-constant series between consecutive
    # samples. This is an explicit modelling choice, recorded in the report: a
    # reference sampled every second is treated as constant until the next sample,
    # which is right for a slowly-varying pulse and wrong for a sudden change.
    if not has_interval:
        times = sorted(intervals, key=lambda i: i.start_s)
        converted: list[ReferenceInterval] = []
        for position, interval in enumerate(times):
            if position + 1 < len(times):
                end = times[position + 1].start_s
            else:
                end = interval.start_s + 1.0
            if end <= interval.start_s:
                findings.append(InputFinding(
                    REJECT, "non_increasing_reference_time",
                    f"t_s does not increase at {interval.start_s}", source=name))
                continue
            converted.append(ReferenceInterval(
                interval.start_s, end, interval.bpm,
                interval.condition, interval.device, interval.participant))
        findings.append(InputFinding(
            INFO, "reference_resampled",
            "sample-layout reference converted to piecewise-constant intervals (each value holds "
            "until the next sample)", source=name))
        intervals = converted

    # Implausible values are rejected, not clipped: a reference at 4 BPM or 900 BPM
    # is a units error or a lost sweep, and evaluating against it would be worse
    # than refusing.
    low, high = REFERENCE_PLAUSIBLE_BPM
    implausible = [i for i in intervals if not (low <= i.bpm <= high)]
    if implausible:
        findings.append(InputFinding(
            REJECT, "implausible_reference_bpm",
            f"{len(implausible)} reference value(s) outside {low:g}-{high:g} BPM; a reference outside "
            "these bounds is a unit error or a lost measurement, not a heart rate",
            source=name, count=len(implausible)))
        intervals = [i for i in intervals if low <= i.bpm <= high]
        if not intervals:
            raise InputRejection(findings)

    # Overlapping reference intervals make "the reference during this window"
    # ambiguous, and picking one arbitrarily would silently choose a value.
    ordered = sorted(intervals, key=lambda i: i.start_s)
    overlaps = sum(
        1 for previous, current in zip(ordered, ordered[1:])
        if current.start_s < previous.end_s
    )
    if overlaps:
        findings.append(InputFinding(
            REJECT, "overlapping_reference_intervals",
            f"{overlaps} reference interval(s) overlap the previous one, so the reference during a "
            "window is ambiguous. Supply disjoint intervals or a sample-layout file.",
            source=name, count=overlaps))

    span = max(i.end_s for i in intervals) - min(i.start_s for i in intervals)
    if span < MIN_REFERENCE_SPAN_S:
        findings.append(InputFinding(
            REJECT, "reference_too_short",
            f"the reference covers {span:.1f} s; at least {MIN_REFERENCE_SPAN_S:g} s is needed to "
            "evaluate anything",
            source=name))

    # Gaps are disclosed but not fatal: the platform reports the unmatched windows.
    gaps = [
        (previous.end_s, current.start_s)
        for previous, current in zip(ordered, ordered[1:])
        if current.start_s > previous.end_s
    ]
    if gaps:
        findings.append(InputFinding(
            WARN, "reference_gaps",
            f"{len(gaps)} gap(s) in reference coverage; windows falling in them are reported as "
            "unmatched rather than being dropped silently",
            source=name, count=len(gaps)))

    # A REJECT finding means the reference cannot be used, so the function must not
    # hand back a table that carries one. Some of these checks (units, overlap,
    # span) were previously recorded without being raised, which let a caller
    # evaluate against a reference the loader itself had refused.
    blocking = [f for f in findings if f.severity is REJECT]
    if blocking:
        raise InputRejection(findings)

    return ReferenceTable(
        source=name, interval_mode=has_interval, intervals=intervals,
        findings=findings, synthetic=synthetic)


def reference_by_interval(table: ReferenceTable) -> list[ReferenceInterval]:
    return sorted(table.intervals, key=lambda i: i.start_s)


def _number(text: str | None, field_name: str, row: int, source: str,
            findings: list[InputFinding]) -> float | None:
    if text is None or text.strip() == "":
        findings.append(InputFinding(
            REJECT, "missing_reference_value", f"{field_name} is empty", source=source,
            field_name=field_name, row=row))
        return None
    try:
        value = float(text)
    except ValueError:
        findings.append(InputFinding(
            REJECT, "unparseable_reference_value", f"{field_name} is not a number: {text!r}",
            source=source, field_name=field_name, row=row))
        return None
    if not math.isfinite(value):
        findings.append(InputFinding(
            REJECT, "non_finite_reference_value", f"{field_name} is not finite: {text!r}",
            source=source, field_name=field_name, row=row))
        return None
    return value
