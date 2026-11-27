"""Reference loading, clock offsets and window-to-reference pairing.

These tests cover the two ways a validation study is most often ruined:

1. a *plausible* synchronisation that is wrong, and
2. a *plausible* reference that is not a reference (a units error, a duplicate, an
   overlapping interval).

Every value here is synthetic.
"""
from __future__ import annotations

import io

import pytest

from research.validation.alignment import (
    SyncConfig,
    TimeBase,
    align,
    derive_offset,
    reference_span,
)
from research.validation.errors import InputRejection, Severity
from research.validation.loader import Reading
from research.validation.reference import ReferenceInterval, ReferenceTable, load_reference

# --- reference loading -------------------------------------------------------


def interval_csv(rows: str) -> io.StringIO:
    return io.StringIO("start_s,end_s,bpm\n" + rows)


def test_interval_reference_loads():
    table = load_reference(interval_csv("0,10,70\n10,20,72\n"))
    assert len(table.intervals) == 2
    assert table.span_s == (0.0, 20.0)
    assert table.interval_mode is True


def test_sustained_plateau_is_accepted():
    table = load_reference(interval_csv("0,30,70\n30,60,70\n"))
    assert len(table.intervals) == 2


def test_sample_reference_is_resampled_into_intervals():
    table = load_reference(io.StringIO("t_s,bpm\n0,70\n1,71\n2,72\n3,73\n4,74\n"))
    assert table.interval_mode is False
    # Each sample holds until the next one.
    assert table.intervals[0].start_s == 0 and table.intervals[0].end_s == 1
    assert any(f.code == "reference_resampled" for f in table.findings)


def test_unrecognised_layout_is_rejected():
    with pytest.raises(InputRejection) as excinfo:
        load_reference(io.StringIO("time,value\n0,70\n"))
    assert "unrecognised_reference_layout" in excinfo.value.codes


def test_implausible_reference_is_rejected_not_clipped():
    """A reference at 4 or 900 BPM is a units error, not a heart rate."""
    with pytest.raises(InputRejection) as excinfo:
        load_reference(interval_csv("0,10,4\n10,20,70\n"))
    assert "implausible_reference_bpm" in excinfo.value.codes


def test_overlapping_reference_intervals_are_rejected():
    """Two candidate values for one moment makes the pairing arbitrary."""
    with pytest.raises(InputRejection) as excinfo:
        load_reference(interval_csv("0,20,70\n10,30,72\n"))
    assert "overlapping_reference_intervals" in excinfo.value.codes


def test_reference_too_short_is_rejected():
    with pytest.raises(InputRejection) as excinfo:
        load_reference(interval_csv("0,2,70\n2,4,71\n"))
    assert "reference_too_short" in excinfo.value.codes


def test_reference_gaps_are_disclosed_not_fatal():
    table = load_reference(interval_csv("0,10,70\n30,40,72\n"))
    assert any(f.code == "reference_gaps" and f.severity is Severity.WARN
               for f in table.findings)


def test_missing_reference_value_is_rejected():
    with pytest.raises(InputRejection) as excinfo:
        load_reference(interval_csv("0,10,\n10,20,72\n"))
    assert "missing_reference_value" in excinfo.value.codes


def test_non_increasing_sample_time_is_rejected():
    with pytest.raises(InputRejection) as excinfo:
        load_reference(io.StringIO("t_s,bpm\n0,70\n0,71\n1,72\n2,73\n"))
    assert "non_increasing_reference_time" in excinfo.value.codes


# --- sync configuration ------------------------------------------------------


def test_undeclared_time_base_is_refused():
    """The whole point: the CSV cannot tell the two clock origins apart."""
    table = load_reference(interval_csv("0,10,70\n10,20,72\n"))
    result = align([], table, SyncConfig())
    assert any(f.code == "time_base_undeclared" and f.severity is Severity.REJECT
               for f in result.findings)


def test_zero_offset_must_be_stated_explicitly():
    table = load_reference(interval_csv("0,10,70\n10,20,72\n"))
    result = align([], table, SyncConfig(time_base=TimeBase.CAPTURE_START, offset_s=None))
    assert any(f.code == "offset_not_established" for f in result.findings)


def test_zero_offset_is_accepted_when_supplied():
    table = load_reference(interval_csv("0,30,70\n30,60,70\n"))
    result = align([], table, SyncConfig(time_base=TimeBase.CAPTURE_START, offset_s=0.0))
    assert not [f for f in result.findings if f.code == "offset_not_established"]


def test_negative_offset_is_a_real_offset_not_a_missing_value():
    table = load_reference(interval_csv("0,30,70\n30,60,70\n"))
    reading = make_reading(start=30.0, end=40.0, value=71.0)
    result = align([reading], table, SyncConfig(time_base=TimeBase.PAGE_LOAD, offset_s=-30.0))
    assert len(result.pairs) == 1
    assert result.pairs[0].reference_clock_start_s == pytest.approx(0.0)


def test_invalid_overlap_fraction_is_refused():
    table = load_reference(interval_csv("0,10,70\n10,20,72\n"))
    result = align([], table, SyncConfig(time_base=TimeBase.REFERENCE_CLOCK,
                                        min_overlap_fraction=1.5))
    assert any(f.code == "invalid_overlap_fraction" for f in result.findings)


def test_reference_clock_time_base_ignores_a_supplied_offset():
    table = load_reference(interval_csv("0,30,70\n30,60,70\n"))
    result = align([], table, SyncConfig(time_base=TimeBase.REFERENCE_CLOCK, offset_s=99.0))
    assert any(f.code == "offset_ignored" for f in result.findings)


# --- pairing -----------------------------------------------------------------


def make_reading(*, start: float, end: float, value: float | None = 70.0,
                 accepted: bool = True, algorithm: str = "consensus", roi: str = "all",
                 reading_id: int = 1, reason: str | None = None) -> Reading:
    return Reading(
        reading_id=reading_id, metric="heart_rate", value=value, algorithm=algorithm,
        roi=roi, accepted_in_file=accepted, quality_verdict="valid" if accepted else "low_signal",
        rejection_reason=reason, quality_score=0.6, fs_hz=30.0, n_samples=300,
        window_start_s=start, window_end_s=end, session_elapsed_s=start,
        window_index=1, recorded_utc="2026-01-01T00:00:00.000Z",
        accepted_recomputed=accepted,
        recomputed_reason=None if accepted else (reason or "low_signal"),
    )


def flat_reference(duration_s: float = 120.0, bpm: float = 70.0,
                   step_s: float = 5.0) -> ReferenceTable:
    intervals = [ReferenceInterval(float(t), float(t) + step_s, bpm)
                 for t in range(0, int(duration_s), int(step_s))]
    return ReferenceTable(source="<synthetic>", interval_mode=True, intervals=intervals)


def test_a_window_is_paired_with_the_overlapping_reference():
    table = flat_reference()
    reading = make_reading(start=10.0, end=20.0, value=72.0)
    result = align([reading], table, SyncConfig(time_base=TimeBase.CAPTURE_START, offset_s=0.0))
    assert len(result.pairs) == 1
    pair = result.pairs[0]
    assert pair.reference_bpm == pytest.approx(70.0)
    assert pair.estimate_bpm == pytest.approx(72.0)
    assert pair.error_bpm == pytest.approx(2.0)


def test_reference_is_weighted_by_actual_overlap():
    """A window half in a 70 BPM segment and half in an 80 BPM segment sees 75."""
    intervals = [ReferenceInterval(0, 10, 70.0), ReferenceInterval(10, 20, 80.0)]
    table = ReferenceTable(source="<synthetic>", interval_mode=True, intervals=intervals)
    # Deliberately asymmetric: 2 s in the first segment, 8 s in the second.
    reading = make_reading(start=8.0, end=18.0)
    result = align([reading], table, SyncConfig(time_base=TimeBase.CAPTURE_START,
                                                offset_s=0.0))
    assert len(result.pairs) == 1
    expected = (2 * 70.0 + 8 * 80.0) / 10.0
    assert result.pairs[0].reference_bpm == pytest.approx(expected)


def test_window_outside_the_reference_is_excluded_not_unmatched():
    """A time-base or offset error must be named, not disguised as missing coverage."""
    table = flat_reference(duration_s=60.0)
    reading = make_reading(start=500.0, end=510.0)
    result = align([reading], table, SyncConfig(time_base=TimeBase.CAPTURE_START,
                                                offset_s=0.0))
    assert result.excluded[0]["reason"] == "outside_reference_span"
    assert not result.pairs


def test_window_inside_a_reference_gap_is_unmatched():
    intervals = [ReferenceInterval(0, 10, 70.0), ReferenceInterval(60, 70, 70.0)]
    table = ReferenceTable(source="<synthetic>", interval_mode=True, intervals=intervals)
    reading = make_reading(start=25.0, end=35.0)
    result = align([reading], table, SyncConfig(time_base=TimeBase.CAPTURE_START,
                                                offset_s=0.0))
    assert result.unmatched[0]["reason"] == "no_reference_coverage"


def test_short_windows_are_excluded():
    table = flat_reference()
    reading = make_reading(start=10.0, end=11.0)  # 1 s, below the 4 s default
    result = align([reading], table, SyncConfig(time_base=TimeBase.CAPTURE_START,
                                                offset_s=0.0))
    assert result.excluded[0]["reason"] == "window_too_short"


def test_a_reference_that_varies_across_a_window_is_excluded():
    """If no single value represents the window, pairing it would invent one."""
    intervals = [ReferenceInterval(0, 5, 60.0), ReferenceInterval(5, 10, 90.0)]
    table = ReferenceTable(source="<synthetic>", interval_mode=True, intervals=intervals)
    reading = make_reading(start=0.0, end=10.0)
    result = align([reading], table, SyncConfig(time_base=TimeBase.CAPTURE_START,
                                                offset_s=0.0,
                                                max_reference_variation_fraction=0.1))
    assert result.excluded[0]["reason"] == "reference_varied_across_window"


def test_duplicate_windows_are_excluded_and_counted():
    table = flat_reference()
    dup = make_reading(start=10.0, end=20.0, accepted=False, reason="duplicate_window")
    result = align([dup], table, SyncConfig(time_base=TimeBase.CAPTURE_START, offset_s=0.0))
    assert any(e["reason"] == "duplicate_window" for e in result.excluded)


def test_no_pairs_is_a_blocking_finding():
    table = flat_reference()
    reading = make_reading(start=500.0, end=510.0)
    result = align([reading], table, SyncConfig(time_base=TimeBase.CAPTURE_START,
                                                offset_s=0.0))
    assert any(f.code == "no_paired_observations" and f.severity is Severity.REJECT
               for f in result.findings)


def test_coverage_accounting_never_loses_a_window():
    table = flat_reference(duration_s=60.0)
    readings = [
        make_reading(start=10.0, end=20.0, reading_id=1),
        make_reading(start=20.0, end=30.0, reading_id=2, value=None, accepted=False,
                     reason="low_signal"),
        make_reading(start=500.0, end=510.0, reading_id=3),
    ]
    result = align(readings, table, SyncConfig(time_base=TimeBase.CAPTURE_START,
                                               offset_s=0.0))
    coverage = result.coverage()
    # Only the accepted reading is a candidate; the rejected one never becomes one,
    # and the out-of-span one is excluded. Nothing disappears.
    assert coverage["windows_paired"] == 1
    assert coverage["windows_excluded"] == 1


def test_evaluation_window_restriction_limits_the_reference_span():
    table = flat_reference(duration_s=120.0)
    config = SyncConfig(time_base=TimeBase.CAPTURE_START, offset_s=0.0,
                        evaluate_from_s=20.0, evaluate_to_s=40.0)
    assert reference_span(table, config) == (20.0, 40.0)


# --- offset derivation -------------------------------------------------------


def test_offset_is_derived_from_consistent_anchors():
    estimate = derive_offset([(1000.0, 0.0), (1005.0, 5.0), (1010.0, 10.0)])
    assert estimate.established
    assert estimate.offset_s == pytest.approx(1000.0)
    assert estimate.anchors == 3


def test_a_single_anchor_is_not_enough():
    estimate = derive_offset([(1000.0, 0.0)])
    assert not estimate.established
    assert "at least 2" in estimate.reason


def test_disagreeing_anchors_are_refused_rather_than_averaged():
    """Drift (or a misread anchor) means one constant offset does not fit."""
    estimate = derive_offset([(1000.0, 0.0), (1005.0, 9.0)])
    assert not estimate.established
    assert "disagree" in estimate.reason


def test_offset_derivation_tolerates_sub_second_delays():
    estimate = derive_offset([(1000.0, 0.0), (1005.2, 5.0), (1010.1, 10.0)],
                             max_residual_s=1.0)
    assert estimate.established
    assert estimate.offset_s == pytest.approx(1000.1, abs=0.15)


def test_offset_derivation_is_monotonic_in_the_anchor_offset():
    """A regression on the first implementation, which always returned 0.0.

    The original scoring function used the spread of (reference - (anchor + offset)),
    which is algebraically invariant to the offset, so every candidate tied and the
    first was chosen. These two anchor sets differ only by a constant and must
    produce offsets that differ by that constant.
    """
    base = derive_offset([(100.0, 0.0), (110.0, 10.0)])
    shifted = derive_offset([(600.0, 0.0), (610.0, 10.0)])
    assert base.established and shifted.established
    assert shifted.offset_s - base.offset_s == pytest.approx(500.0)
