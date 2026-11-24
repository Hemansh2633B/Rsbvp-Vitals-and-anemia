# RSBVP scientific validation report — Sprint 6 (evidence before deployment)

**Status: PUBLIC-DATASET EVALUATION NOT RUN — NO AUTHORIZED UBFC-rPPG ARCHIVE AVAILABLE IN THIS WORKSPACE.**
**What is reported below: software verification on deterministic synthetic fixtures only. Nothing here is physiological, medical or clinical evidence.**

---

## Sprint 8 addendum (2026-11-23)

- Quality concepts are six explicitly separated, never-blended verdicts in both pathways (`face_tracking`, `roi_extraction`, `temporal_acquisition`, `pulse_signal`, `algorithm_agreement`, `availability`); a union ROI-coverage gate (≥ 0.50) is required for `valid`.
- Browser regression coverage added for: near-flat RGB, fully dark (zero) RGB means, union-coverage failure, timestamp-gap windows, per-estimator isolation, GPU→CPU fallback, reacquisition buffer reset, hidden-tab stop, worker crash, camera interruption. Python coverage added for CHROM invalid inputs, standardized output, six-concept verdicts, and gate None-estimates.
- Test status after Sprint 8 changes: Python **154 passed**; frontend **28 passed**; build and lint clean. These remain software verification. No fixture was tuned to pass; the gate is not physiologically validated.
- Physical browser-camera testing: **NOT RUN** (`docs/MANUAL_CAMERA_TESTS.md`). Dataset-level validation (UBFC-rPPG simple/realistic, COHFACE): **NOT RUN — DATASET NOT AVAILABLE**. These are independent of CI; CI requires neither.
- Status vocabulary for this report is unchanged: `software-tested` ≠ `synthetic-tested` ≠ `dataset-tested` ≠ `hardware-tested` ≠ `physiologically validated` ≠ `clinically validated`. No tier was upgraded by Sprint 8 work.
- Anemia: foundations only (`research/anemia/contract.py`, `docs/ANEMIA_IMAGE_CONTRACT.md`). Status: **NOT AVAILABLE — NO VERIFIED LABELED DATASET**. No model, no predictor, no screening claim.

---

## 1. Evaluation summary matrix

| Layer | Status | Where |
|---|---|---|
| Software unit/contract tests (schema, backends, gap handling, probe, metrics, license register) | RUN — 115 tests pass | `tests/` |
| Synthetic benchmark (70 BPM deterministic fixture, native vs reference) | RUN (software verification) | `../research_backends/synthetic/` |
| Synthetic degradation suite (low light, noise, motion, frame drops, low fs, ROI dropout) | RUN (software verification) | `synthetic/` |
| UBFC-rPPG realistic subset (42) — primary target | **NOT RUN — DATASET NOT AVAILABLE** | `DATA_READINESS.md` |
| UBFC-rPPG simple subset (8) — sanity check | **NOT RUN — DATASET NOT AVAILABLE** | `DATA_READINESS.md` |
| COHFACE | NOT RUN — not authorized/present; deferred | register §D |
| rPPG-Toolbox external backend on UBFC-rPPG | NOT RUN — requires archive + isolated env + checkpoints | `docs/RESEARCH_BACKENDS.md` §4.2 |
| pyVHR cross-check | NOT RUN — GPL-3.0 isolated env; not installed/used | `docs/RESEARCH_BACKENDS.md` §4.3/§8 |
| Neural checkpoints (TS-CAN first) | NOT RUN — no checkpoint present; inference reported unavailable | register §E |
| CMS50D hardware comparison | NOT RUN — no device; unchanged since earlier sprints | `docs/MANUAL_CAMERA_TESTS.md` |
| Lighting / motion / acquisition-condition performance **on real data** | NOT RUN — dataset absent (synthetic proxies only, §4) | this report |
| Browser vs Python numerical agreement | NOT RUN — browser exports not collected on a research protocol | `docs/RESEARCH_METHODOLOGY.md` |

## 2. Methods compared (identical protocol)

In-process backends on identical recordings, identical 12 s windows / 6 s step, 0.7–3.5 Hz passband, hann-periodogram-v1 estimator, references joined after prediction only:

- `rsbvp_native` (MIT): GREEN, POS, CHROM — the shipped implementation, reused read-only.
- `rsbvp_reference` (MIT): GREEN, ICA, CHROM, POS, PBV (trace-domain signature-gated approximation).
- Not run (require external environments/checkpoints/data): LGI, OMIT (video-domain; the in-process backend reports them explicitly unsupported), toolbox neural models.

Per-window availability, rejection reasons, latency, and peak RSS are emitted by every run; identical windows make window-level pairing valid descriptively, with participant bootstrap reserved for authorized grouped data.

## 3. Results on deterministic synthetic fixtures (software verification only)

Fixture: `reports/research_backends/synthetic/inputs/synthetic_70bpm.csv` (60 s, 30 Hz, 70 BPM sinusoid + seeded noise). All backends × all algorithms: MAE ≈ 0.0007 BPM vs truth, availability 1.000, 0 rejections — the pipeline recovers a clean synthetic pulse essentially exactly, as expected. **This is a software correctness check, not accuracy evidence.**

Reliability/degradation evidence (`synthetic/reliability_synthetic.md`, seed 20261123, 60 s):

| Finding | Evidence (synthetic) |
|---|---|
| Low light (unscaled read-noise model) | at 0.30× gain: no degradation. At 0.15× gain: `rsbvp_native:POS` MAE ≈ 14.6 BPM, `rsbvp_reference:POS` MAE ≈ 11.7 BPM with availability still 1.000. Sprint 7 quality diagnostics no longer pass these windows silently: per-window Quality-OK fractions for POS in this condition are 0.556 (native) / 0.630 (reference), driven by `low_concentration_*` and `weak_separation_*` tokens — see `synthetic/reliability_synthetic.md`. GREEN/CHROM/ICA/PBV ≈ 0 error in this fixture. Plausible-but-wrong POS estimates remain the documented risk. |
| Elevated sensor noise (σ = 3.0) | no measurable error in this fixture |
| Frame drops (20% of samples, short irregular gaps) | all methods MAE ≈ 1.05 BPM (ICA/PBV ≈ 2.5 BPM) after short-gap linear interpolation; availability 1.000. Before the Sprint 6 fix (gap > 0.25 s ⇒ rejection), the same fixture produced a systematic ≈ 17.5 BPM error **with quality `ok`** — see §6. |
| Low frame rate | 15 Hz and 10 Hz: no degradation in this fixture (70 BPM is far from Nyquist) |
| ROI dropout (`left_cheek` NaN) | exactly the affected third of windows rejected (`rejected:nonfinite_samples`); other ROIs unaffected — 0.667 availability as designed |
| Motion transients (+18–30 count, 0.28 s, every ~7 s) | no HR bias in this fixture (all ≈ 0 MAE) |
| Long gaps (> 0.25 s) | windows now rejected (`rejected:excessive_gaps`) — conservative gate, added this sprint |

## 4. Lighting, motion and acquisition conditions

No dataset ⇒ **no real-world performance can be reported** across illumination, motion or device conditions. The only acquisition-relevant statement possible today: UBFC-rPPG (when available) is a 30 fps / 640×480 / ~1 m indoor-illumination C920 corpus with a mathematical-game stressor — the protocol above will report per-recording metrics; no subgroup claims will be possible without a documented per-recording condition map (which the provider does not publish; if obtainable, record it locally in the manifest's provenance note). Browser camera-path reliability (MediaPipe tracking failure, occlusion, low light, frame drops, `getUserMedia` loss mid-capture) is implemented and failure-tested at the software level; **physical camera/hardware tests remain NOT RUN** (`docs/MANUAL_CAMERA_TESTS.md`).

## 5. Participant-level analysis and uncertainty

Not possible — no authorized data. The metrics layer (`research/backends/metrics.py`) already implements deterministic participant bootstrap CI (seed 20261123, 1000 resamples) and window-pairing on `recording_id`; it activates automatically when a manifest with pseudonymous participant IDs is supplied. Note: UBFC-rPPG does not publish a recording→participant mapping; treat each recording as the unit and say so in any report.

## 6. Failure analysis and defects closed in this sprint

1. **Systematic bias on gappy traces (fixed).** In-process backends treated irregularly sampled windows as uniformly sampled; a 20% frame drop produced a ≈ 17.5 BPM systematic error reported with quality `ok`. Now: any window with a gap > 0.25 s is rejected (`rejected:excessive_gaps`); windows with only short gaps are linearly interpolated to the measured rate (the same convention as `gui/rppg_core/research.py::resample_rgb_traces`). Regression tests: `tests/test_backends_gaps.py`.
2. **Quality tokens could crash schema validation (fixed).** `_quality_token` emitted `low_quality:spectral_concentration=0.152` containing `=`, which the schema charset rejects; the exception surfaced as `rejected:schemaerror`, masking genuinely low-quality windows as processing failures. Token now `low_quality:spectral_concentration_0.152` (charset-safe). Found by the synthetic motion suite, not by inspection.
3. **Spectral-concentration gate does not detect systematic HR bias (largely root-caused; mitigated, not eliminated).** The low-light synthetic case above sits ~12–15 BPM off truth while every estimate is confident and prior to this sprint passed `quality: ok` outright. Sprint-7 work added SNR and peak-separation diagnostics (`spectral_features` in `research/backends/reference_methods.py`, mirrored in `gui/rppg_core/quality.py`) plus per-window `quality_ok` accounting. On the low-light POS synthetic windows, the new diagnostics **do** flag the marginal ones — e.g. CHEEK regions repeatedly fail `low_concentration_*` / `weak_separation_*` — but the forehead POS estimator still reads 70 BPM with high concentration on these perfectly periodic synthetic traces, so the bias (when present) is not caught by within-window spectral shape alone. The remaining false-accept exposure lives in **cross-estimator/cross-ROI disagreement and reference verification**, not single-window peak sharpness. Additional honest limitation: absolute SNR dB values are relative to a periodogram median floor, not calibrated to camera physiology. The composite, conservative verdict therefore requires agreement across independent estimators alongside the spectral checks. Documented as a software-level mitigation; no substitute for real validation.
4. **PBV approximation is trace-domain.** It is a signature-gated chrominance approximation and materially weaker than the video-domain PBV/LGI/OMIT in the external backends; it is included for relative ranking only and must not be quoted as "the PBV result".

## 7. What is genuinely validated vs what remains unknown

**Genuinely established (software level only):**
- Deterministic reproducibility of the full path (fixture → backends → metrics → reports), byte-stable outputs.
- The in-process pipeline recovers a clean synthetic pulse; gap handling and rejection accounting behave conservatively after the §6 fixes.
- Schema integrity (missing values preserved, no NaN leakage, strict JSON), backend availability gating, license-register completeness checks, and CLI exit semantics — all under CI without network/GPU/datasets.
- Honest status reporting: the repository never claims dataset validation anywhere.

**Not established / unknown (nothing may be claimed):**
- Accuracy of any method on UBFC-rPPG (simple or realistic) or any real recording.
- Whether browser POS/CHROM agree numerically with the Python implementations.
- Robustness under real illumination/motion/occlusion; real browser/camera behavior across devices.
- Neural baseline performance; mediapipe landmarker behavior on real dark/low-light faces; toolbox/pyVHR cross-checks.
- Any physiological, medical or screening interpretation (anemia, hemoglobin, BP, HRV, SpO₂, cardiac output).
- The spectral-concentration gate's false-accept rate on real data.

## 8. Explicit limitations (protocol-level)

1. Windows overlap 2× (12 s / 6 s) → correlated; pooled window metrics are descriptive only; participant-level inference only.
2. The synthetic truth is a 70 BPM sinusoid; physiological waveforms are not sinusoids. Successive sinusoid benchmarks flatter all linear methods.
3. External backends' numbers (when ever produced) inherit each tool's own preprocessing; cross-tool comparisons are protocol-confounded and must be labelled as such.
4. Passband 0.7–3.5 Hz (42–210 BPM) is a research default, not a physiological limit.
5. UBFC-rPPG CMS50E reference is a finger sensor, not an ECG; ECG claims remain out of scope by design. **PRV ≠ HRV.**
6. A CMS50E/hospital-grade reference is the ceiling of truth here; no "medical accuracy" language is permitted anywhere downstream.

## 9. Reproduction

See `README.md` § "Reproducing this directory". CI runs the full offline suite (`python -m pytest -q`) on every push; it must remain green without datasets/GPU. The dataset protocol, once data are lawfully obtained, is §5–§7 of `README.md` plus `DATA_READINESS.md` §5.
