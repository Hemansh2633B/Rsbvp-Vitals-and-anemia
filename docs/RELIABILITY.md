# Reliability and failure analysis — investigation notes (Sprint 6; updated Sprint 7)

**Sprint 7 update.** The per-window quality verdict is now decomposed into five separately reported concepts: acquisition quality, trace/ROI quality, physiological signal quality, estimator agreement, availability (`gui/rppg_core/quality.py`; mirrored in `gui/frontend/src/rppg/liveDsp.ts` and `research/backends/reference_methods.py`). Spectral diagnostics added: spectral concentration (≥ 0.20), SNR vs the out-of-peak passband median (≥ 3 dB, guard radius 0.15 Hz), peak separation vs the strongest competing in-band local maximum ≥ 0.25 Hz away (≥ 1.5×). Token `low_quality:<check>` is now emitted when any check fails; `quality_ok_fraction` / `windows_quality_ok` / `windows_low_quality` appear in backend summary accounting. The Python and browser estimators use the identical formulation (symmetric Hann, explicit DFT) and are parity-tested on a shared synthetic fixture (assertions on peak frequency, fraction, SNR and separation; `tests/fixtures/rppg_rgb_fixture.csv`). Browser status set extended: `irregular_timestamps`, `processing_error`. Python live pipeline gates `consensus_hr`/`rr_final` on the composite verdict (per-estimator values stay visible). Synthetic low-light POS false-accept is now flagged as low-quality on the marginal windows (native POS quality-ok 0.556, reference POS 0.630) — the forehead windows of the perfectly periodic synthetic fixture still pass, which is expected of an idealized signal and is not evidence of real-world robustness. Acquisition-clipping acquisitions (near-black/near-white rails) are rejected regardless of spectral peak quality. Calibration of these heuristics to real camera physiology: NOT RUN.

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
| `low_signal_quality` | gates fail (duration, agreement, spectral concentration) | No — "Unavailable" |
| `Camera stream ended/interrupted` | `ended`/`mute` events, hidden tab | No — capture stopped |
| `error` | getUserMedia/model/worker failure | No — error banner |
| `rejected:nonfinite_samples` / `rejected:excessive_gaps` (backends) | NaN in window / gap > 0.25 s | Never estimated |
| `unavailable:*` (neural/toolbox/pyvhr) | backend not installed / checkpoint absent / unsupported method | Never estimated |
| `low_signal_quality` + `quality_reasons` | any of acquisition/spectral/agreement/ROI checks fail | No — reason spelled out (e.g. `low_concentration_0.191`, `weak_separation_1.37`, `low_snr_11.7db`, `estimator_disagreement_22.0bpm`) |
| `irregular_timestamps` | any ROI trace gap > 0.25 s | No — capture integrity reported |
| `insufficient_frames` | effective fs < 12 Hz or too few samples | No |
| `low_quality:<check>` (backends) | spectral checks fail | Estimate emitted but flagged; backend summary counts `quality_ok_fraction` |

Acceptance invariant: **a poor-quality result is unavailable, never silently plausible.** Any code path violating this is a P0 defect — report it.

## 8. Open gaps (explicit)

1. No real-illumination or motion study (dataset absent; no rig).
2. No multi-browser/multi-camera matrix execution; GPU vs CPU MediaPipe path not benchmarked.
3. Spectral-concentration gate false-accepts plausible-but-wrong peaks (low-light POS) — mitigation is reference-data evaluation + estimator agreement, both pending.
4. Browser POS/CHROM vs Python CHROM parity claim: experimental only (`liveDsp.parity.test.ts` checks implementation structure on fixtures, not physiological parity).
5. CMS50D-synchronized sessions: not run in this environment; previous sprint notes stand.

## 9. How to extend this analysis with real evidence

Follow `reports/research_validation/DATA_READINESS.md` §5 (obtain UBFC-rPPG), then `docs/RESEARCH_BACKENDS.md` §6 (fair comparison). Add per-recording condition metadata locally in your manifest provenance note (lighting condition if the provider exposes it) and report per-condition availability + error. Do not commit condition metadata tied to pseudonyms.
