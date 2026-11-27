# Quality Gate Specification — Sample Acceptance / Rejection Rules

**Project:** RSBVP — Remote Screening of Blood Parameters and Vital Signs
**Status:** Research prototype — not a medical device, no clinical claims
**Last updated:** 2026-11-27
**Applies to:** `gui/rppg_core/quality.py`, `gui/rppg_core/research.py`, `gui/rppg_core/live.py`, `gui/rppg_core/pipeline.py`, `gui/rppg_core/session.py`, `gui/frontend/src/rppg/liveDsp.ts`, `gui/frontend/src/rppg/sessionAggregate.ts`

---

## 1. Purpose and scope

This document specifies every point at which an analysis window (a "sample") can be accepted or rejected, from raw camera frames through to the final session result. It is written as research-grade documentation: every threshold is listed with its value, rationale, and evidence tier. **No threshold is a clinical cut-off; none has been calibrated against real camera physiology.**

The specification exists so that:

1. Every rejection is traceable to a named check with a named threshold.
2. No rejection can occur silently — every rejected window carries a machine-readable reason token.
3. Code changes to the gates can be reviewed against this document before being applied.

---

## 2. System architecture — where rejections happen

A sample passes through five layers. Each layer can reject independently, and rejection at any layer prevents the sample from reaching the session result.

```
Layer 1: Capture
  └─ Camera frames → RGB traces + timestamps
        ↓ (reject: no face, no ROI, too few frames, wrong sampling rate)
Layer 2: Per-window quality gate  (quality.py assess_window / liveDsp.ts assessWindow)
  └─ Six separated concepts → composite verdict (valid / low_signal_quality / ...)
        ↓ (reject: spectral, agreement, timing, acquisition, coverage, candidate)
Layer 3: Measurement gate         (research.py measurement_gate)
  └─ Cross-estimator gate on uncorrected estimates + candidate validation
        ↓ (reject: <8s, <2 trustworthy estimators, spread >12 BPM, candidate mismatch)
Layer 4: Pipeline consensus       (pipeline.py run_full_rppg_pipeline / estimate_live_rppg_from_buffer)
  └─ Sets consensus_hr = None when any gate fails
        ↓ (reject: consensus withheld)
Layer 5: Session acceptance       (session.py classify_reading / summarize)
  └─ quality_verdict == "valid" + finite value + plausible band + not stale + not duplicate
        ↓ (reject: wrong verdict, NaN, implausible value, stale, duplicate)
Layer 6: Session aggregation      (session.py summarize / summarize_session)
  └─ Requires ≥5 accepted readings AND ≥2 independent (non-overlapping) windows
        ↓ (reject: insufficient data — no headline number shown)
```

Rejection is **hierarchical**: the most fundamental failure wins. `assess_window()` returns on the first failing concept in the order: face → ROI → timing → motion → acquisition → spectral → agreement → candidate. A window that fails face detection never reaches the spectral check.

---

## 3. Layer 2 — Per-window quality gate (`assess_window`)

File: `gui/rppg_core/quality.py:289` (`assess_window`)
Browser mirror: `gui/frontend/src/rppg/liveDsp.ts`

### Inputs

| Input | Source | Notes |
|---|---|---|
| `trace` | `Q.trace_report(timestamps)` | Effective rate, gaps, duplicates, stalls, jitter |
| `acquisition` | `Q.acquisition_report(rgb_window)` | Clipping, dynamic range, brightness |
| `spectral` | `Q.spectral_quality(signal, fs)` | Concentration, SNR, separation |
| `agreement` | `Q.agreement_report(estimates)` | Spread across Green/POS/CHROM estimators |
| `roi_agreement` | `Q.agreement_report(roi_estimates)` | Spread across forehead/left_cheek/right_cheek |
| `roi_coverage` | Caller-supplied | Fraction of samples with ≥1 usable skin ROI |
| `face_detected` | Caller-supplied | Whether a face was tracked in the window |
| `tracking_lost` | Caller-supplied | Whether tracking was lost during the window |
| `excessive_motion` | Caller-supplied | Whether face displacement exceeded threshold |
| `candidate_bpm` | Caller-supplied | Legacy motion-corrected consensus candidate |

### Six separated concepts (never blended)

| Concept | Meaning | States |
|---|---|---|
| `face_tracking` | Face detected and tracked | pass / fail / not_evaluated |
| `roi_extraction` | Usable skin ROI coverage | pass / fail / not_evaluated |
| `temporal_acquisition` | Timing regularity, rate, duration | pass / fail / not_evaluated |
| `pulse_signal` | Spectral quality of pulse-band estimate | pass / fail / not_evaluated |
| `algorithm_agreement` | Cross-estimator spread within tolerance | pass / fail / not_evaluated |
| `availability` | Composite: all required concepts passed | pass / fail |

### Rejection hierarchy (order of evaluation)

1. **`face_not_detected`** — `face_detected == False`
   - Concepts: face_tracking=fail, availability=fail
   - No estimate reported.

2. **`roi_lost`** — `tracking_lost == True` or `roi_coverage <= 0.0`
   - Concepts: roi_extraction=fail, availability=fail

3. **Temporal acquisition** (only if `trace` is not None), checked in order:

   a. **`insufficient_frames`** — `fs_hz is None or fs_hz < MIN_SAMPLING_RATE_HZ` (12 Hz)
   - Concepts: temporal_acquisition=fail

   b. **`irregular_timestamps`** — `max_gap_s > MAX_GAP_SECONDS` (0.25 s)
   - Concepts: temporal_acquisition=fail

   c. **`irregular_timestamps`** (`duplicate_samples`) — `has_duplicate_samples` (>2% of intervals ≤ 1 ms)
   - Same token as (b), distinct reason string

   d. **`irregular_timestamps`** (`irregular_timing`) — `has_irregular_timing` (jitter CV > 0.25 or stalled)
   - Same token as (b), distinct reason string

   e. **`warming_up`** — `duration_s < min_window_s` (default 10 s)
   - Concepts: temporal_acquisition=not_evaluated, availability=fail
   - This is not an error; it means "keep acquiring."

4. **`excessive_motion`** — `excessive_motion == True`
   - Concepts: pulse_signal=fail, availability=fail

5. **Acquisition checks** (only if `acquisition` is not None):
   - **`acquisition_clipping_or_flat`** — `clip_fraction > CLIP_MAX_FRACTION` (0.10)
   - **`acquisition_low_dynamic_range`** — `dynamic_range < MIN_DYNAMIC_RANGE` (6 counts)
   - Either failure sets `pulse_state = FAIL`

6. **ROI coverage** — `roi_coverage < MIN_ROI_COVERAGE` (0.50)
   - Reason: `insufficient_roi_coverage_<value>`

7. **Spectral checks** (only if `spectral` is not None):
   - **`no_spectral_peak`** — no peak found in passband
   - **`low_concentration_<fraction>`** — `peak_fraction < SPECTRAL_MIN_CONCENTRATION` (0.20)
   - **`low_snr_<db>db`** — `snr_db < SPECTRAL_MIN_SNR_DB` (3.0 dB)
   - **`weak_separation_<ratio>`** — `separation_ratio < SPECTRAL_MIN_SEPARATION` (1.5×)
   - Any failure sets `pulse_state = FAIL`

8. **Estimator agreement** (only if `agreement` is not None):
   - **`estimator_disagreement_<spread>bpm`** — `spread_bpm > AGREEMENT_TOLERANCE_BPM` (12 BPM)
   - Requires ≥2 valid estimates; <2 estimates → `agreement_state = NOT_EVALUATED` (not a rejection by itself)

9. **Cross-ROI agreement** (only if `roi_agreement` is not None):
   - **`roi_estimator_disagreement_<spread>bpm`** — ROI spread > 12 BPM
   - Requires ≥2 valid ROI estimates; <2 → not evaluated

10. **Candidate validation** (only if `candidate_bpm` is not None):
    - **`candidate_no_estimator_backing`** — no trustworthy estimator values exist
    - **`candidate_not_finite`** — candidate is NaN or infinite
    - **`candidate_disagrees_with_estimators`** — candidate not within 12 BPM of every estimator AND within 6 BPM of at least one

### Composite verdict

- **`valid`** — all required checks passed; no reasons.
- **`low_signal_quality`** — one or more reasons; status is never `valid` when any reason exists.
- All other tokens (`face_not_detected`, `roi_lost`, `insufficient_frames`, `irregular_timestamps`, `warming_up`, `excessive_motion`) are returned immediately on first failure and short-circuit remaining checks.

### Threshold register (Layer 2)

| Threshold | Value | Rationale | Evidence tier |
|---|---|---|---|
| `MIN_SAMPLING_RATE_HZ` | 12 Hz | Must exceed 2 × 3.5 Hz (Nyquist of passband top) with margin | SOFTWARE, DOCUMENTED |
| `MAX_GAP_SECONDS` | 0.25 s | Short gaps linearly regularized; beyond it, reject rather than interpolate | SOFTWARE, SYNTHETIC |
| `MIN_WINDOW_SECONDS` | 10 s | ~7 cycles at 42 BPM for stable peak estimation | DOCUMENTED |
| `MIN_ROI_COVERAGE` | 0.50 | ≥half of samples with ≥1 usable skin ROI | SOFTWARE |
| `CLIP_MAX_FRACTION` | 0.10 | Saturated/black channel fraction tolerated | SOFTWARE, SYNTHETIC |
| `MIN_DYNAMIC_RANGE` | 6 counts | Sensor flatness floor | SOFTWARE |
| `SPECTRAL_MIN_CONCENTRATION` | 0.20 | Quasi-flat-spectrum reject floor | SYNTHETIC |
| `SPECTRAL_MIN_SNR_DB` | 3.0 dB | Peak vs median out-of-peak passband floor | SYNTHETIC |
| `SPECTRAL_MIN_SEPARATION` | 1.5× | Top peak vs strongest competing local maximum | SYNTHETIC |
| `AGREEMENT_TOLERANCE_BPM` | 12 BPM | Max spread across independent estimators | SYNTHETIC, DOCUMENTED |
| `CANDIDATE_NEAR_ESTIMATOR_BPM` | 6 BPM | Candidate within half tolerance of ≥1 estimator | SYNTHETIC (Sprint 10) |
| `DUPLICATE_EPSILON_S` | 0.001 s | ~1 ms: same sensor frame sampled twice | SOFTWARE |
| `has_duplicate_samples` threshold | >2% of intervals | Above this, duplicates are not rounding noise | SOFTWARE |
| `STALL_INTERVAL_MULTIPLE` | 2.5× median | Single interval this far beyond typical = a stall | SOFTWARE |
| `intervalJitterCv` | >0.25 | Interval variability breaking uniform-sampling premise | SOFTWARE |

**Calibration statement:** none of these values has been fitted to real camera data. Real-camera calibration is **NOT RUN**.

---

## 4. Layer 3 — Measurement gate (`measurement_gate`)

File: `gui/rppg_core/research.py:96`

A conservative cross-estimator gate that runs *after* legacy motion corrections in the offline pipeline. It validates the corrected consensus candidate against the uncorrected estimates.

### Rules

1. `duration_seconds < 8` → `warming_up`, invalid
2. Fewer than 2 trustworthy estimators (reliability ≥ 0.25) → `low_signal_quality`, invalid
3. `max(values) - min(values) > agreement_bpm` (12 BPM) → `low_signal_quality`, invalid
4. `candidate` provided:
   - Not finite → `low_signal_quality`, invalid
   - Not within `agreement_bpm` (12 BPM) of *every* trustworthy estimate → invalid
   - Not within `agreement_bpm / 2` (6 BPM) of *at least one* trustworthy estimate → invalid

### Threshold register (Layer 3)

| Threshold | Value | Rationale | Evidence tier |
|---|---|---|---|
| Minimum duration | 8 s | Shorter than Layer 2's 10 s minimum — pipeline-level pre-screen | DOCUMENTED |
| Minimum trustworthy estimators | 2 | Agreement requires ≥2 independent values | DOCUMENTED |
| Minimum reliability | 0.25 | Below this, an estimator is not trustworthy | DOCUMENTED |
| Agreement tolerance | 12 BPM | Same as Layer 2 `AGREEMENT_TOLERANCE_BPM` | SYNTHETIC, DOCUMENTED |
| Candidate near-estimator | 6 BPM | Half of agreement tolerance | SYNTHETIC (Sprint 10) |

**Note:** Layer 3's 8 s minimum is *shorter* than Layer 2's default 10 s `min_window_s`. In the live pathway (`estimate_live_rppg_from_buffer`), `min_seconds_for_hr` is passed as `min_window_s` to `assess_window`, so the live gate effectively requires 10–12 s while the pipeline gate requires 8 s. This mismatch is a known consistency issue (see §8).

---

## 5. Layer 4 — Pipeline consensus (`run_full_rppg_pipeline`, `estimate_live_rppg_from_buffer`)

### `run_full_rppg_pipeline` (`pipeline.py:2025`)

1. Extracts RGB signals (face box + per-ROI crops) from video
2. Runs Green, POS, CHROM estimators + legacy motion corrections (adaptive_final_correction, motion_peak_guidance_correction, left_right_* corrections)
3. Computes per-ROI consensus estimates (forehead, left_cheek, right_cheek)
4. Calls `measurement_gate()` with `[green, pos, chrom]` estimates and `candidate=hr_consensus`
5. If `quality_gate["valid"]` is False → `hr_consensus = None`
6. If `roi_agreement.n_valid >= 2` and ROI agreement fails → `hr_consensus = None`
7. Returns `consensus_hr`, `measurement_valid`, `measurement_state`, `measurement_reason`

### `estimate_live_rppg_from_buffer` (`live.py:325`)

1. Requires `len(rgb_values) >= 30` → else returns `None` entirely
2. Requires `duration >= min_seconds_for_hr` → else returns `None` entirely
3. Runs Green, POS estimators + legacy motion corrections
4. Computes `Q.assess_window()` with trace, acquisition, spectral, agreement, candidate
5. If verdict not available → `consensus_hr = None`, `rr_final = None`
6. Returns full state dict including `quality_status`, `quality_reason`, `quality_reasons`, `quality_scores`, `quality_concepts`

### Rejection output

When rejected, the pipeline returns `consensus_hr = None` but **preserves** per-estimator values (`hr_green_fft`, `hr_pos_fft`, `hr_green_peak`, `hr_pos_peak`) so disagreement is never hidden.

---

## 6. Layer 5 — Session acceptance (`classify_reading`)

File: `gui/rppg_core/session.py:282`

A reading is accepted only when **all** of the following hold:

1. **Supported metric** — `reading.metric` is in `METRICS` (heart_rate or respiratory_rate)
2. **Not stale** — `analyzed_at_ms` within `stale_after_ms` (5 s) of reference time
3. **Quality verdict is exactly `valid`** — `reading.quality_verdict != "valid"` ⇒ reject with `reading.rejection_reason or reading.quality_verdict`
   - No threshold was relaxed for this feature; the gates are the ones that already existed.
4. **Finite value** — `value is not None and math.isfinite(value)`
5. **Plausible band** — HR: 30–220 BPM; RR: 4–60 br/min
   - These are **data-hygiene** filters catching unit mix-ups and lost estimates (0, 3, 900). They are **not** clinical ranges.
6. **Not a duplicate** — `window_key` (metric|algorithm|start|end) not already in session history (when `suppress_duplicate_windows` is enabled)

### Rejection reasons

| Reason | Meaning |
|---|---|
| `unsupported_metric:<name>` | Unknown metric |
| `stale_reading` | Result describes a moment that has passed |
| `<rejection_reason>` or `<quality_verdict>` | Quality gate rejected (e.g. `low_signal_quality`, `face_not_detected`) |
| `valid_verdict_without_estimate` | Verdict valid but value is None or non-finite |
| `implausible_value_<v>_outside_<lo>-<hi>` | Outside plausibility band |
| `duplicate_window` | Same metric/algorithm/window already recorded |

Duplicate windows are **recorded** (history stays complete) but **refused** (`final_rejection_reason = "duplicate_window"`) and **counted separately** from rejections (`n_duplicate_windows`, never inside `n_rejected`).

---

## 7. Layer 6 — Session aggregation (`summarize` / `summarize_session`)

File: `gui/rppg_core/session.py` (Python), `gui/frontend/src/rppg/sessionAggregate.ts` (browser)

### Requirements for a session result

| Requirement | Default | Why |
|---|---|---|
| Accepted readings (heart_rate) | ≥ 5 | Each already passed all gates; lower bar buys speed, not accuracy |
| Independent (non-overlapping) windows | ≥ 2 | A session average must never be one moment re-counted |

Independence is computed by `count_independent_windows()` — greedy interval scheduling by end time over readings carrying window bounds. Sliding-window analysis re-analyse the same stretch many times; raw count hugely overstates independent observations.

### Completion states

| State | Condition | Headline number shown? |
|---|---|---|
| `idle` | No session, no readings | No |
| `initialising` | Running, no analysable window yet | No |
| `collecting` | Running, aggregate not available | No |
| `insufficient` | Stopped, aggregate not available | No — specific reason shown |
| `available` | Running, aggregate available | Yes |
| `interrupted` | Interrupted before aggregate available | No |
| `completed` | Stopped, aggregate available | Yes |

**Invariant:** a stop invitation may appear only when `result_available` is true (heart-rate aggregate verdict is `available`). Enforced by test in both languages.

### Outliers

Flagged, **never removed**. A reading is flagged when it is >2.5 leave-one-out SDs **and** ≥6 BPM from the rest. Flagged readings are included in every statistic; the median is shown beside the mean so outlier sensitivity is visible.

---

## 8. Known issues — the "rejects samples every time" problem

The following are plausible causes of sustained sample rejection in real use. Each is a hypothesis to verify against real camera data before any threshold change.

### Issue 8.1 — Sampling rate floor too high for real cameras

`MIN_SAMPLING_RATE_HZ = 12 Hz` requires the effective frame rate to be ≥12 fps. Real camera capture under load (browser tab throttling, host processing lag, thermal) can easily drop below this. A window at 10 fps effective rate is rejected as `insufficient_frames` even though 10 fps is still above the Nyquist rate for 3.5 Hz (7 Hz).

**Verification needed:** Measure effective fps on real devices under load before adjusting.

### Issue 8.2 — Duration requirement (10–12 s) rejects short measurements

`min_window_s` defaults to 10 s (quality.py) or 12 s (live.py original mode). A user doing a 5–8 s measurement gets `warming_up` on every window — every sample rejected. This is correct behavior per specification, but may feel like "the app rejects everything" to a user expecting instant results.

**Verification needed:** Is the user doing short (<10 s) measurements? If so, this is expected behavior, not a bug.

### Issue 8.3 — Estimator agreement tolerance too tight

`AGREEMENT_TOLERANCE_BPM = 12 BPM` requires Green and POS FFT to agree within 12 BPM. On real data with motion, low light, or skin-tone variation, the two estimators can diverge by more than this, causing `estimator_disagreement` rejection on every window.

**Verification needed:** Check real-data spread between Green and POS before adjusting.

### Issue 8.4 — Spectral concentration floor too high

`SPECTRAL_MIN_CONCENTRATION = 0.20` requires the top passband peak to hold ≥20% of passband power. Real rPPG signals often have broad, low-concentration spectra, especially with motion or poor illumination, causing `low_concentration` rejection.

**Verification needed:** Check real-data concentration values before adjusting.

### Issue 8.5 — ROI coverage gate too strict

`MIN_ROI_COVERAGE = 0.50` requires ≥half of samples with ≥1 usable skin ROI. Face tracking loss, occlusion, or poor lighting can drop coverage below this, causing `insufficient_roi_coverage` rejection.

**Verification needed:** Check real-data coverage before adjusting.

### Issue 8.6 — Candidate validation rejects corrected consensus

Sprint 10 hardening requires `candidate_bpm` to be within 12 BPM of every trustworthy estimator AND within 6 BPM of at least one. If legacy motion corrections produce a candidate that diverges from uncorrected estimators (which they sometimes do by design), every corrected window is rejected with `candidate_disagrees_with_estimators`.

**Verification needed:** Check how often motion corrections produce divergent candidates on real data.

### Issue 8.7 — Mismatch between Layer 2 and Layer 3 duration minima

Layer 2 (`assess_window`) defaults to `min_window_s = 10 s` (live: 12 s original / 10 s segment). Layer 3 (`measurement_gate`) requires `duration >= 8 s`. A recording of 8–10 s could pass Layer 3 but fail Layer 2. This inconsistency means a sample can be accepted by the pipeline gate but rejected by the live quality gate, or vice versa.

**Recommended fix:** Align the duration minima so both layers use the same minimum.

---

## 9. Recommended changes (to be implemented after documentation review)

These are **recommendations only**, not yet implemented. Each requires verification against real data before application.

1. **Align duration minima:** Make Layer 2 and Layer 3 use the same minimum duration (recommend 8 s to match Layer 3, or 10 s to match Layer 2's documented minimum). Do not lower without real-data evidence.

2. **Add configurable thresholds:** Expose all quality thresholds as a single `QualityConfig` dataclass passed through `assess_window()` instead of module-level constants, so deployments can tune for their camera population without editing source.

3. **Add rejection telemetry:** Emit per-reason rejection counters (not just the winning reason) so operators can see which gate is the bottleneck. Currently `assess_window()` returns only the first failing reason.

4. **Add a "marginal" verdict:** Between `valid` and `low_signal_quality`, add `marginal` for windows that pass all hard gates but have marginal spectral scores. Marginal windows could be reported with a lower-confidence flag instead of being fully withheld.

5. **Review candidate validation:** Confirm that `candidate_disagrees_with_estimators` is not rejecting legitimate motion-corrected consensus values on real data. If corrections are systematically divergent, either improve the corrections or relax the near-one threshold from 6 BPM with real-data justification.

---

## 10. Evidence tier summary

| Tier | Meaning | Applied to |
|---|---|---|
| SOFTWARE-TESTED | Deterministic unit tests pass | Most Python thresholds, trace_report, acquisition_report |
| SYNTHETIC-TESTED | Behavior observed on generated signals with known ground truth | Spectral thresholds, agreement tolerance, candidate validation |
| DOCUMENTED | Design rationale only, not empirically validated | Duration minima, reliability floor, plausibility bands |
| NOT RUN | Never verified on real camera/physiological data | **All real-camera performance claims** |

**Central honesty rule:** no row of this specification constitutes clinical validation. Synthetic-fixture results verify software behavior; they cannot estimate accuracy, robustness or safety on real people.

---

## Related documents

- `docs/RELIABILITY.md` — Failure modes and threshold history (Sprint 6–12)
- `docs/SESSION_AGGREGATION.md` — Session aggregation rules and statistics
- `docs/RESEARCH_METHODOLOGY.md` — Research methodology and validation approach
- `docs/IMPLEMENTATION_STATUS.md` — Authoritative capability matrix
- `docs/CURRENT_STATUS_AUDIT.md` — Capability matrix and evidence tiers (Sprint 10)
- `docs/ROI_GEOMETRY.md` — ROI geometry and pixel acceptance
- `docs/MANUAL_CAMERA_TESTS.md` — Physical camera test protocol (not yet executed)
- `gui/rppg_core/quality.py` — Source of `assess_window()` and all quality types
- `gui/rppg_core/research.py` — Source of `measurement_gate()`
- `gui/rppg_core/live.py` — Source of `estimate_live_rppg_from_buffer()` and `LiveSession`
- `gui/rppg_core/pipeline.py` — Source of `run_full_rppg_pipeline()`
- `gui/rppg_core/session.py` — Source of `classify_reading()` and `summarize()`
