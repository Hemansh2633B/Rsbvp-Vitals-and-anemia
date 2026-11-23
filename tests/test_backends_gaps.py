"""Conservative-gap regression tests for the in-process backends.

Irregular sampling must be handled the way the rest of RSBVP handles it:
short gaps are linearly interpolated, long gaps invalidate the window
entirely (never invented samples). Timestamps are synthetic.
"""
import numpy as np
import pytest

from research.backends.base import RecordingInput, regularize_segment
from research.backends.registry import get_backend


def make_recording(t, rois=None):
    n = len(t)
    base = np.stack(
        [150 + 2 * np.sin(np.arange(n)), 175 + 10 * np.sin(2 * np.pi * 70 / 60 * t), 160 + np.cos(np.arange(n))],
        axis=1,
    )
    rois = rois or {"forehead": base.copy()}
    return RecordingInput(
        recording_id="gap_test",
        timestamps_s=np.asarray(t, dtype=float),
        rois={k: np.asarray(v, dtype=float) for k, v in rois.items()},
        sampling_rate_hz=float(1.0 / np.median(np.diff(t))),
    )


def test_regularize_segment_regular_input_is_unchanged():
    t = np.arange(300, dtype=float) / 30.0
    segment = np.stack([np.arange(300.0), np.arange(300.0) * 2, np.arange(300.0) + 1], axis=1)
    out = regularize_segment(t, segment, 30.0)
    np.testing.assert_array_equal(out, segment)


def test_regularize_segment_short_gap_interpolates_linearly():
    fs = 30.0
    t_full = np.arange(300, dtype=float) / fs
    drop = sorted(range(100, 104))  # 4/30 s gap — under the 0.25 s limit
    keep = [i for i in range(300) if i not in drop]
    t = t_full[keep]
    segment = np.stack([t * 100.0, t * 200.0, t * 300.0], axis=1)
    out = regularize_segment(t, segment, fs)
    assert out is not None
    # linear data stays linear under linear interpolation
    np.testing.assert_allclose(out[:, 0], out[:, 1] / 2.0, rtol=1e-9, atol=1e-6)


def test_regularize_segment_long_gap_is_rejected():
    fs = 30.0
    t_full = np.arange(400, dtype=float) / fs
    keep = [i for i in range(400) if not (200 <= i < 216)]  # 16/30 s > 0.25 s gap
    t = t_full[keep]
    segment = np.stack([np.sin(t), np.cos(t), t], axis=1)
    assert regularize_segment(t, segment, fs) is None


def test_backend_windows_over_long_gap_are_rejected():
    fs = 30.0
    n = 600
    t = np.arange(n, dtype=float) / fs
    pulse = np.sin(2 * np.pi * (70 / 60.0) * t)
    rgb = np.stack([150.0 + pulse, 175.0 + 10 * pulse, 160.0 + pulse], axis=1)
    # carve a 0.5 s hole by deleting 15 timestamps mid-recording
    keep = np.ones(n, dtype=bool)
    keep[250:265] = False
    t = t[keep]
    rgb = rgb[keep]
    recording = make_recording(t, {"forehead": rgb})
    backend = get_backend("rsbvp_reference")
    result = backend.run(recording, algorithms=["GREEN"], window_seconds=12.0, step_seconds=6.0)
    gap_records = [r for r in result.records if 0.0 < r.timestamp_s < t[-1]
                   and r.timestamp_s <= 9.0 and r.timestamp_s + 12.0 > t[160]]
    statuses = {r.signal_quality for r in result.records}
    assert "rejected:excessive_gaps" in statuses
    gap_hits = [r for r in result.records if r.signal_quality == "rejected:excessive_gaps"]
    for record in gap_hits:
        assert record.estimated_hr_bpm is None
        assert record.pulse_signal is None


def test_backend_short_gap_windows_still_estimate():
    fs = 30.0
    n = 600
    t = np.arange(n, dtype=float) / fs
    pulse = np.sin(2 * np.pi * (70 / 60.0) * t)
    rgb = np.stack([150.0 + pulse, 175.0 + 10 * pulse, 160.0 + pulse], axis=1)
    keep = np.ones(n, dtype=bool)
    keep[100] = False  # one dropped frame (0.067 s gap) — well under the limit
    recording = make_recording(t[keep], {"forehead": rgb[keep]})
    backend = get_backend("rsbvp_reference")
    result = backend.run(recording, algorithms=["GREEN"], window_seconds=12.0, step_seconds=6.0)
    ok = [r for r in result.records if r.signal_quality == "ok"]
    assert ok, "windows spanning a single dropped frame must still be analyzable"
