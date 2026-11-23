"""Correctness and determinism tests for the independent reference implementations."""
import numpy as np
import pytest

from research.backends import reference_methods
from research.backends.base import RecordingInput, UnsupportedAlgorithm
from research.backends.reference import ReferenceBackend
from research.backends.registry import get_backend


def synth_trace(heart_bpm=70.0, duration_s=30.0, fs=30.0, noise=0.15, seed=7):
    """Deterministic synthetic RGB trace with a known pulse frequency."""
    rng = np.random.default_rng(seed)
    t = np.arange(0, duration_s, 1.0 / fs)
    phase = 2 * np.pi * (heart_bpm / 60.0) * t
    rgb = np.column_stack([
        110 + 6 * np.sin(phase),
        130 + 22 * np.sin(phase + 0.15),
        95 + 4 * np.sin(phase + 0.3),
    ]) + rng.normal(0, noise, (len(t), 3))
    return t, rgb


def recording(heart_bpm=70.0, **kwargs):
    t, rgb = synth_trace(heart_bpm=heart_bpm, **kwargs)
    return RecordingInput(
        recording_id=f"synthetic-{heart_bpm}bpm",
        timestamps_s=t,
        rois={"forehead": rgb},
        sampling_rate_hz=30.0,
    )


@pytest.mark.parametrize("algorithm", ["GREEN", "ICA", "CHROM", "POS", "PBV"])
def test_reference_methods_recover_known_pulse(algorithm):
    backend = ReferenceBackend()
    result = backend.run(recording(heart_bpm=72.0), algorithms=[algorithm],
                         window_seconds=12.0, step_seconds=6.0)
    estimates = [r.estimated_hr_bpm for r in result.records if r.estimated_hr_bpm is not None]
    assert len(estimates) >= 3, "expected estimates on a clean synthetic trace"
    assert abs(np.median(estimates) - 72.0) <= 3.0


def test_flat_green_channel_is_rejected_not_fabricated():
    t, rgb = synth_trace()
    rgb[:, 1] = 128.0  # zero modulation
    rec = RecordingInput(recording_id="flat", timestamps_s=t,
                         rois={"forehead": rgb}, sampling_rate_hz=30.0)
    backend = ReferenceBackend()
    result = backend.run(rec, algorithms=["GREEN"])
    assert all(r.estimated_hr_bpm is None for r in result.records)
    assert all(r.signal_quality.startswith("rejected") or r.signal_quality.startswith("unavailable")
               for r in result.records)


def test_nonfinite_samples_reject_the_window():
    t, rgb = synth_trace()
    rgb[100:105, 0] = np.nan
    rec = RecordingInput(recording_id="nans", timestamps_s=t,
                         rois={"forehead": rgb}, sampling_rate_hz=30.0)
    backend = ReferenceBackend()
    result = backend.run(rec, algorithms=["GREEN"])
    affected = [r for r in result.records
                if r.timestamp_s <= t[104] < (r.window_end_s or 0)]
    unaffected = [r for r in result.records
                  if not (r.timestamp_s <= t[104] < (r.window_end_s or 0))]
    assert affected and all(r.signal_quality == "rejected:nonfinite_samples" for r in affected)
    assert unaffected and all(r.estimated_hr_bpm is not None for r in unaffected)


def test_lgi_and_omit_are_explicitly_unsupported_on_traces():
    backend = ReferenceBackend()
    with pytest.raises(UnsupportedAlgorithm):
        backend.run(recording(), algorithms=["LGI"])
    with pytest.raises(UnsupportedAlgorithm):
        backend.run(recording(), algorithms=["OMIT"])


def test_ica_is_deterministic():
    rec = recording(heart_bpm=66.0)
    backend = ReferenceBackend()
    first = backend.run(rec, algorithms=["ICA"])
    second = backend.run(rec, algorithms=["ICA"])
    assert [r.estimated_hr_bpm for r in first.records] == [r.estimated_hr_bpm for r in second.records]
    for a, b in zip(first.records, second.records):
        assert a.pulse_signal == b.pulse_signal


def test_estimate_hr_bpm_rejects_short_signals():
    assert reference_methods.estimate_hr_bpm(np.zeros(10), 30.0) == (None, None)


def test_transforms_reject_nonfinite_input():
    rgb = np.full((100, 3), 100.0)
    rgb[5, 0] = np.nan
    with pytest.raises(ValueError):
        reference_methods.green(rgb, 30.0)


def test_different_heart_rate_is_recovered():
    rec = recording(heart_bpm=95.0)
    backend = get_backend("rsbvp_reference")
    result = backend.run(rec, algorithms=["POS"])
    estimates = [r.estimated_hr_bpm for r in result.records if r.estimated_hr_bpm is not None]
    assert estimates and abs(np.median(estimates) - 95.0) <= 4.0
