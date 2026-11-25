# Reliability and failure analysis — investigation notes (Sprint 6; updated Sprint 8)

**Sprint 8 update.** Quality concepts are now six explicitly separated, never-blended verdicts: `face_tracking`, `roi_extraction`, `temporal_acquisition`, `pulse_signal`, `algorithm_agreement`, `availability` (`gui/rppg_core/quality.py`; mirrored in `gui/frontend/src/rppg/liveDsp.ts`). A union ROI-coverage gate (≥ 0.50 of window samples with at least one usable skin ROI, `MIN_ROI_COVERAGE`) is required for a `valid` verdict in both pathways; per-ROI coverage is reported alongside the overall union fraction. In the browser, excessive motion now **purges the rolling analysis buffer** (raw export samples are retained for provenance) so motion-contaminated windows cannot leak into later estimates. Browser CHROM/POS now validate inputs and convert estimator failure into an explicit unavailable estimate instead of crashing the window; the same holds for the Python CHROM call in the legacy pipeline (`ValueError` ⇒ CHROM unavailable, never a crash). Browser CHROM remains free of an IIR bandpass (band restriction happens in the in-band Hann periodogram); Python `chrom_rppg` retains its zero-phase Butterworth — the two are parity-tested at the estimator level, not interchangeable. New regression tests: near-flat/zero RGB, union-coverage gate, timestamp-gap windows, per-estimator isolation (`liveDsp.test.ts`, `tests/test_quality.py`, `tests/test_rppg_research.py`). Calibration of these heuristics to real camera physiology: still **NOT RUN**.

**Sprint 7 update.** The per-window quality verdict was decomposed into separately reported concepts: acquisition quality, trace/ROI quality, physiological signal quality, estimator agreement, availability (`gui/rppg_core/quality.py`; mirrored in `gui/frontend/src/rppg/liveDsp.ts` and `research/backends/reference_methods.py`). Spectral diagnostics added: spectral concentration (≥ 0.20), SNR vs the out-of-peak passband median (≥ 3 dB, guard radius 0.15 Hz), peak separation vs the strongest competing in-band local maximum ≥ 0.25 Hz away (≥ 1.5×). Token `low_quality:<check>` is now emitted when any check fails; `quality_ok_fraction` / `windows_quality_ok` / `windows_low_quality` appear in backend summary accounting. The Python and browser estimators use the identical formulation (symmetric Hann, explicit DFT) and are parity-tested on a shared synthetic fixture (assertions on peak frequency, fraction, SNR and separation; `tests/fixtures/rppg_rgb_fixture.csv`). Browser status set extended: `irregular_timestamps`, `processing_error`. Python live pipeline gates `consensus_hr`/`rr_final` on the composite verdict (per-estimator values stay visible). Synthetic low-light POS false-accept is now flagged as low-quality on the marginal windows (native POS quality-ok 0.556, reference POS 0.630) — the forehead windows of the perfectly periodic synthetic fixture still pass, which is expected of an idealized signal and is not evidence of real-world robustness. Acquisition-clipping acquisitions (near-black/near-white rails) are rejected regardless of spectral peak quality. Calibration of these heuristics to real camera physiology: NOT RUN.

Scope: poor illumination, face movement, ROI tracking failure, missing/irregular frames, camera frame-rate variation, browser/camera configurations, and failure/unavailable states — with the evidence tier of every statement marked.

**Evidence tiers used below:** `SOFTWARE` = verified by deterministic tests/synthetic fixtures · `HARDWARE-UNTESTED` = implemented and software-tested, never verified on a physical camera/CMS50D · `NOT RUN` = no data or device available · `DOCUMENTED` = failure behavior exists and is surfaced to the user, but not physiologically characterized.

## 1. Poor illumination

- Mechanism: lower photon flux → lower pulsatile SNR; camera exposure/gain changes possible mid-capture.
- Synthetic evidence (`SOFTWARE`): unscaled read-noise model shows GREEN/CHROM/ICA/PBV hold to 0.15× gain in the fixture, while POS (both implementations) silently biases 12–15 BPM with **availability still 1.000** (`reports/research_validation/synthetic/`). 
- Gate behavior: the spectral-concentration gate (`_quality_token`, ≥ 0.20 quasi-flat-reject threshold) does **not** catch plausible-but-wrong peaks — documented in `reports/research_validation/validation_report.md` §6.
- User-facing: browser shows spectral concentration and marks low-quality windows unavailable rather than showing a number (`DOCUMENTED`).
- Real-world performance: `NOT RUN` (no dataset; no controlled lighting rig). Mitigations before trusting this path: dataset-level UBFC-rPPG run under its natural varying illumination, plus a staged manual lighting protocol (`docs/MANUAL_CAMERA_TESTS.md`).

## 2. Face movement / motion artifacts

- Browser gate (`SOFTWARE`, UI-level): normalized displacement of the tracked face centre over a 2 s span (> 0.08 in Face-Landmarker normalized units) ⇒ acquisition reset, state `excessive_motion`; estimators are not run; any stale estimate is cleared. A poor-quality measurement stays unavailable by construction.
- Python offline path: historical motion heuristics in `gui/rppg_core` are experimental and retain historical correction behavior; validation with correction on/off by recording/motion condition remains pending (`docs/RESEARCH_METHODOLOGY.md`).
- Synthetic (`SOFTWARE`): step transients every ~7 s did not bias HR in the fixture (all ≈ 0 MAE); PBV produced `low_quality` tokens, not wrong numbers, in the superseded token bug (fixed).
- Physiological motion rejection (e.g., spectra-based accelerometry grading): `NOT RUN` — no real motion corpus here.

## 3. ROI tracking failure / occlusion

- Browser: Face Landmarker loss ⇒ `face_not_detected` → after 1.8 s `reacquiring`; after 4 s the acquisition buffer is reset and all stale estimates/waveforms are cleared (`DOCUMENTED` + unit-tested ROI polygon logic). Occlusion of an individual ROI (e.g., glasses glare on cheek) ⇒ that ROI reports null coverage; measurement proceeds on remaining ROIs or goes unavailable.
- Export: missing samples are empty cells; `dropped_interval_fraction` reported; nothing is interpolated on export.
- Synthetic (`SOFTWARE`): `left_cheek` dropout ⇒ exactly 1/3 of windows unavailable with `rejected:nonfinite_samples`; the other ROIs unaffected.
- Real faces: `HARDWARE-UNTESTED`.

## 4. Missing / irregular frames

- Browser: `dropped_interval_fraction` measured from timestamps; display and export both report it; live analysis requires contiguous windows internally.
- Python offline: gap > 0.25 s invalidates the window; short gaps linearly regularized at the measured rate (`resample_rgb_traces` / `regularize_segment`). Sprint 6 fix: the in-process backends no longer treat gappy windows as uniform samples (they used to produce a systematic ~17.5 BPM bias with quality `ok`; now such windows are rejected as `rejected:excessive_gaps` and short gaps are interpolated). Regression tests: `tests/test_backends_gaps.py`.
- Fixture note: `tests/fixtures/rppg_rgb_fixture.csv` is 301 rows over 15 s (~20 fps effective) — usable only for short-window smoke tests, not multi-window statistics.

## 5. Camera frame-rate variation

- Browser: frame rate is measured from `getVideoPlaybackQuality()` deltas (not assumed 30 fps); exported metadata carries camera-reported fps and timestamp-measured sample rate; acquisition works at whatever the camera delivers (typically 30/60).
- Python: sampling rate re-derived from timestamps per recording (median interval); no hardcoded 30 fps.
- Synthetic (`SOFTWARE`): 15 Hz and 10 Hz fixtures estimate HR without error in this fixture (70 BPM is far below Nyquist for either); POS behaves the same.
- Very low effective rates (< ~6 Hz) make 0.7–3.5 Hz passband estimation unreliable — windows degrade to unavailable/low-quality rather than hallucinating; not separately swept here (`NOT RUN` at < 10 Hz).

## 6. Browser and camera configurations

- Supported gate today: Chromium-family with `getUserMedia` over HTTPS/localhost; MediaPipe Face Landmarker (GPU delegate with CPU fallback) via `@mediapipe/tasks-vision` 1.2.3 (Apache-2.0), model fetched at start from the documented Google-hosted URL (provenance: `docs/MEDIAPIPE_ASSETS.md`).
- Web Workers required; absent ⇒ explicit error state, never a silent failure. `OFFSCREEN`/WASM threads: not required.
- Failure surfacing: camera denied/ended/muted, worker crash, hidden tab (capture auto-stops), face lost, excessive motion, worker error — all become explicit unavailable states; stale estimates are always cleared (see `docs/PRIVACY.md`, `docs/MEDIAPIPE_ASSETS.md`).
- Safari/Firefox behavior: not verified on hardware (`HARDWARE-UNTESTED`); expect equivalent failure-state behavior, unproven.
- Different CMOS rolling-shutter/banding under 50/60 Hz mains flicker: not evaluated (`NOT RUN`).
- Camera-to-browser RGB fidelity (ICC/color pipeline): unknown; browser traces are device-dependent by nature.

## 7. Failure and unavailable states (inventory, current behavior)

| State | Trigger | Measure shown? |
|---|---|---|
| `face_not_detected` | landmarker finds no face | No — BPM cleared |
| `reacquiring` | face reappearing / camera resumed | No — fresh window collected |
| `excessive_motion` | displacement > 8 % frame diagonal over 2 s | No — BPM cleared |
| `low_signal_quality` | gates fail (duration, agreement, spectral/SNR/separation, ROI coverage) | No — "Unavailable" |
| `Camera stream ended/interrupted` | `ended`/`mute` events, hidden tab | No — capture stopped |
| `error` | getUserMedia/model/worker failure | No — error banner |
| `rejected:nonfinite_samples` / `rejected:excessive_gaps` (backends) | NaN in window / gap > 0.25 s | Never estimated |
| `unavailable:*` (neural/toolbox/pyvhr) | backend not installed / checkpoint absent / unsupported method | Never estimated |
| `low_signal_quality` + `quality_reasons` | any of acquisition/spectral/agreement/ROI checks fail | No — reason spelled out (e.g. `low_concentration_0.191`, `weak_separation_1.37`, `low_snr_11.7db`, `estimator_disagreement_22.0bpm`) |
| `irregular_timestamps` | any ROI trace gap > 0.25 s | No — capture integrity reported |
| `insufficient_frames` | effective fs < 12 Hz or too few samples | No |
| `low_quality:<check>` (backends) | spectral checks fail | Estimate emitted but flagged; backend summary counts `quality_ok_fraction` |

Acceptance invariant: **a poor-quality result is unavailable, never silently plausible.** Any code path violating this is a P0 defect — report it.

## 7b. ECG reference failure modes (Sprint 11)

The ECG reference pathway is separate from the rPPG estimator path so that no
reference value can influence an estimate or a quality gate. Its failure modes
are enumerated as tokens, and every rejection leaves the window out of the
error statistics while remaining visible in the coverage accounting:

| Failure | Token | Handling |
|---|---|---|
| Missing/incorrect sampling rate | `ecg_fs_invalid` | Hard failure; the rate is caller-supplied and recorded, never inferred |
| Non-finite / empty / 2-D array | `ecg_nonfinite_samples`, `ecg_empty`, `ecg_not_1d` | Window rejected; no interpolation or forward-fill |
| Flat / saturated / clipped signal | `ecg_flat_signal`, `ecg_saturated` | Window rejected; a rail-clipped ECG cannot yield trustworthy beats |
| Irregular or non-increasing timestamps | `ecg_timestamps_irregular`, `ecg_timestamps_not_increasing`, `ecg_timestamps_length_mismatch` | Window rejected; no silent re-timing |
| Fewer than 3 R-peaks / window < 5 s | `ecg_too_few_rpeaks`, `ecg_window_too_short` | Rejected; median R-R not estimable |
| Implausible R-R bulk | `ecg_rr_out_of_range` | Rejected (>25 % outside 0.3–2.0 s) |
| No QRS structure (noise only) | `ecg_qrs_prominence_low` | Rejected; prevents a fabricated reference rate |
| Window outside the recording | `ecg_window_out_of_bounds` | Rejected |
| Sustained ADC rail runs (real data) | `ecg_rail_saturated` | Runs of ≥10 samples pinned at min/max (observed: 174- and 214-sample runs in rPPG-10) mean saturated beats; the window is rejected. A single-sample clip check does not catch this |
| Two detectors disagree (real data) | `ecg_cross_check_disagreement` | A matched-filter detector must agree with the Pan–Tompkins detector on median R-R and beat count within 10 %; otherwise the window is ambiguous and rejected |
| Excessive R-R dispersion | `ecg_rr_dispersion_high` | MAD(R-R)/median(R-R) > 0.25: a misdetection cannot be distinguished from a genuine irregularity, so no reference value is produced |
| Generic manifest path | `ecg_rpeak_estimator_unavailable` | Unchanged: the generic evaluator still refuses ECG by design |

Evidence tier: **SYNTHETIC-TESTED + DATASET-EXERCISED** — run on the 27 rPPG-10 ECG
recordings (477/540 windows accepted, 88 %). The three failure modes above were
discovered by that run, not by the synthetic tests, which is exactly why the
pathway reports rejections instead of repairing them. Nothing in it supports an
HRV, PRV, morphology or clinical claim.

Measurement caveat for rPPG-10 specifically: the released `.npy` files contain raw
BITalino ADC counts (baseline ≈500, range 0–1023), i.e. **arbitrary units, not
mV**. Amplitude-dependent reasoning (e.g. mV thresholds) would be invalid on them;
the pathway only uses timing, so this does not affect the reference HR — but any
future amplitude-based work must not treat these values as calibrated voltages.

## 8. Open gaps (explicit)

1. No real-illumination or motion study (dataset absent; no rig).
2. No multi-browser/multi-camera matrix execution; GPU vs CPU MediaPipe path not benchmarked.
3. Spectral-concentration gate false-accepts plausible-but-wrong peaks (low-light POS) — mitigation is reference-data evaluation + estimator agreement, both pending.
4. Browser POS/CHROM vs Python CHROM parity claim: experimental only (`liveDsp.parity.test.ts` checks implementation structure on fixtures, not physiological parity).
5. CMS50D-synchronized sessions: not run in this environment; previous sprint notes stand.
6. Physical browser-camera matrix (lighting × device × occlusion): NOT RUN — unit/component tests with mocked browser APIs are not a substitute; see `docs/MANUAL_CAMERA_TESTS.md`.

## 9. How to extend this analysis with real evidence

Follow `reports/research_validation/DATA_READINESS.md` §5 (obtain UBFC-rPPG), then `docs/RESEARCH_BACKENDS.md` §6 (fair comparison). Add per-recording condition metadata locally in your manifest provenance note (lighting condition if the provider exposes it) and report per-condition availability + error. Do not commit condition metadata tied to pseudonyms.

## 10. Threshold register (value, rationale, evidence tier)

Every quality threshold below is a documented research heuristic chosen a priori to fail closed — never tuned to make a fixture pass. None is calibrated against real physiology; none is a clinical cut-off. `SOFTWARE` = deterministic tests exercise the boundary · `SYNTHETIC` = behavior observed on synthetic fixtures · `DOCUMENTED` = design rationale only · `NOT RUN` = not verified on real data/hardware.

| Threshold | Value | Rationale | Evidence |
|---|---|---|---|
| Estimator passband | 0.7–3.5 Hz (42–210 BPM) | Wide research band covering resting/tachycardic pulse rates; keeps LF noise and breathing harmonics mostly out | DOCUMENTED, SYNTHETIC |
| `MIN_SAMPLING_RATE_HZ` | 12 Hz | Must exceed 2 × 3.5 Hz with margin for windowing/Nyquist of the highest in-band frequency | SOFTWARE, DOCUMENTED |
| `MAX_GAP_SECONDS` | 0.25 s | Short-gap linear regularization limit; beyond it windows are rejected rather than resampled through holes | SOFTWARE, SYNTHETIC (gap suite §6) |
| `MIN_WINDOW_SECONDS` | 10 s | Enough cycles for stable peak estimation at 42 BPM (~7 cycles) | DOCUMENTED |
| `SPECTRAL_MIN_CONCENTRATION` | 0.20 | Quasi-flat-spectrum reject floor; lower values accept noise as pulse | SYNTHETIC (does not catch plausible-but-wrong peaks — documented) |
| `SPECTRAL_MIN_SNR_DB` | 3.0 dB | Peak vs median out-of-peak passband floor; weak-but-present pulses survive, noise floor does not dominate | SYNTHETIC |
| `SPECTRAL_MIN_SEPARATION` | 1.5× | Top peak must dominate the strongest competing in-band local maximum | SYNTHETIC |
| `PEAK_GUARD_RADIUS_HZ` | 0.15 Hz | Exclusion radius around the peak when computing the noise floor and competitors | DOCUMENTED |
| `COMPETITOR_MIN_DISTANCE_HZ` | 0.25 Hz | Below this, a second maximum is treated as the same peak/harmonic neighborhood, not a competitor | DOCUMENTED |
| `AGREEMENT_TOLERANCE_BPM` | 12 BPM | Max−min spread across independent Green/POS/CHROM × ROI estimators; wider disagreement ⇒ not available | SYNTHETIC, DOCUMENTED |
| `MIN_ROI_COVERAGE` (union) | 0.50 | Window verdict requires at least half of samples with ≥1 usable skin ROI; per-ROI estimates may still exist below this (never reported as `valid`) | SOFTWARE |
| `CLIP_MAX_FRACTION` | 0.10 | Fraction of saturated/black channel values tolerated before `acquisition_clipping_or_flat` | SOFTWARE, SYNTHETIC (clipping rails rejected) |
| `MIN_DYNAMIC_RANGE` | 6 counts | Sensor flatness floor; below it no pulsatile component can exist | SOFTWARE |
| Motion trip (browser) | centre spread > 0.08 over rolling 2 s | UI-level gross-motion detector; resets analysis buffer, never estimates through motion | SOFTWARE (UI heuristic, DOCUMENTED) |
| Face-lost handling (browser) | 1.8 s label `reacquiring`; 4.0 s buffer reset | Avoids both flickering state and unbounded stale capture | DOCUMENTED (UX timing) |
| `min_pixels` (mask QA) | 20 | Minimum non-zero mask pixels for a valid conjunctival mask in the anemia contract validator | SOFTWARE |
| RGB skin heuristic bounds | lum 35–245, rr≥0.88·gg, gg≥0.82·bb, rr−bb≥8 | Conservative capture-quality filter, **not** universal skin segmentation; documented in `roi.ts` | SOFTWARE |
| ECG sampling-rate guard | 100–2000 Hz | Implementation guard in `research/ecg/reference.py`; the real rate must come from provider documentation and is recorded verbatim. Not a physiological claim | SOFTWARE |
| ECG R-R plausibility band | 0.3–2.0 s (30–200 BPM) | Reject implausible intervals; >25 % implausible ⇒ whole window rejected (`ecg_rr_out_of_range`) rather than averaged away | SOFTWARE |
| ECG QRS prominence floor | median R-peak deflection ≥ 3 robust σ (MAD) | Prevents a reference HR being manufactured from noise-only or artefactual segments (`ecg_qrs_prominence_low`); exposed by a synthetic noise test | SYNTHETIC |
| ECG QRS refractory period | 200 ms | Pan–Tompkins default; also the physical limit for detecting two beats | DOCUMENTED (published method) |
| ECG window minimum | 5 s, ≥3 R-peaks | Below this the median R-R is not estimable; yields `ecg_window_too_short` / `ecg_too_few_rpeaks` | SOFTWARE |
| rPPG-10 window / step | 30 s / 30 s (non-overlapping) | Pre-registered to match the provider baseline and to avoid counting correlated windows as independent; frozen before any data | PRE-REGISTERED |
| rPPG-10 trace completeness | ≥98 % expected frames finite, timestamp jitter ≤5 % of frames | A window with dropped/corrupt frames is rejected with a token, never interpolated by this pathway | SOFTWARE |

**Calibration statement:** none of these values has been fitted to real camera data. Where a synthetic fixture motivated or exposed a threshold (e.g. concentration/SNR/separation during the low-light POS analysis), the threshold was set before that fixture's acceptance criteria and is not adjusted to flatter it. Real-camera calibration is **NOT RUN**.
