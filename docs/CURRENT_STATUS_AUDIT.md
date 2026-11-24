# Current status audit — capability matrix (Sprint 10, 2026-11-24)

> **Sprint 8 note (2026-11-23):** six separated quality concepts and the union ROI-coverage gate replaced the five-concept decomposition described below; see `docs/IMPLEMENTATION_STATUS.md` for the current authoritative matrix.
> **Sprint 10 note (2026-11-24):** candidate_bpm validation hardening added — corrected consensus from legacy motion heuristics is rejected unless within `AGREEMENT_TOLERANCE_BPM` (12) of every trustworthy estimator AND within 6 BPM of at least one; cross-ROI agreement (`roi_agreement`) gating added; no estimator anchor ⇒ candidate rejected (`candidate_no_estimator_backing`). Per-ROI HR estimation with cross-ROI agreement gating wired into `run_full_rppg_pipeline`.

This is the **living** capability statement for the repository. It is distinct from the [initial repository audit](INITIAL_REPOSITORY_AUDIT.md), which is a historical record of the baseline state. Numbers below were captured on this date against branch `feat/sprint-10-quality-robustness`; consult commit history for the exact tree.

## How to read the matrix

**Implementation status:** `Implemented` · `Partially implemented` · `Missing` · `Blocked (external dependency)`.

**Evidence tier:** `TESTED-SOFTWARE` = deterministic tests pass in CI (no dataset/GPU/hardware) · `TESTED-FIXTURE` = synthetic software verification only — **not** physiological evidence · `HARDWARE-UNTESTED` = built, software-tested, never run on a physical camera/oximeter · `NOT RUN` = no authorized data/device; numbers do not exist.

> **Central honesty rule:** no row of this matrix constitutes clinical validation. Synthetic-fixture results verify software behavior; they cannot estimate accuracy, robustness or safety on real people.

## 1. Contactless pulse / rPPG

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Green / POS / CHROM transforms (Python) | Implemented | TESTED-SOFTWARE (`tests/test_rppg_*`, `test_backends_reference`) | Rolling POS retained; CHROM independent transform; 0.7–3.5 Hz passband |
| Green / POS / CHROM (browser TS) | Implemented (experimental variants) | TESTED-FIXTURE (`liveDsp.parity.test.ts`) | In-browser POS/CHROM are documented experimental variants; agreement **demonstrated only on one synthetic fixture** |
| Python↔TypeScript DSP parity | Implemented | TESTED-FIXTURE (`tests/fixtures/generate_rppg_rgb_fixture_expected.py`) | Peak frequency, peak fraction, SNR dB, separation asserted to tight tolerance on the shared fixture; not evidence beyond it |
| Quality verdicts per window (Python + browser) | Implemented | TESTED-SOFTWARE (`tests/test_quality.py`, `test_reliability.py`) | Six separated concepts (`face_tracking`, `roi_extraction`, `temporal_acquisition`, `pulse_signal`, `algorithm_agreement`, `availability`) + union ROI-coverage gate ≥ 0.50; status tokens incl. `irregular_timestamps`, `processing_error`; unavailable ⇒ no number. Sprint 10: `candidate_bpm` from legacy motion heuristics is now rejected unless within `AGREEMENT_TOLERANCE_BPM` (12) of every trustworthy estimator AND within 6 BPM of at least one; cross-ROI agreement (`roi_agreement`) added; no estimator anchor ⇒ candidate rejected (`candidate_no_estimator_backing`). |
| Low-light false-accept handling | Partially implemented | TESTED-FIXTURE | Diagnostics flag marginal low-light POS windows (native 0.556 / reference 0.630 quality-ok). Forehead of the perfectly periodic fixture still passes — an artifact of idealized input, not robustness evidence. Cross-estimator agreement is the remaining mitigation; **no real-world light validation exists** (NOT RUN) |
| Multi-ROI extraction (browser) | Implemented | TESTED-SOFTWARE (roi.ts tests) + HARDWARE-UNTESTED | 3 ROIs, RGB skin heuristic, eye/lip/brow exclusion; **not** MediaPipe segmentation; dropout accounting in exports |
| Offline 3-region RGB extraction (Python) | Implemented (heuristic) | TESTED-SOFTWARE | Skin-heuristic; documented as heuristic; not landmark segmentation |
| Face tracking lifecycle (browser) | Implemented | TESTED-SOFTWARE (BrowserPulse tests) + HARDWARE-UNTESTED | Permission/errors, face loss/reacquisition, tab-hidden stop, worker crash, camera interruption, camera switching, asset-load failure messaging. **Never verified on a physical browser+camera matrix** (`docs/MANUAL_CAMERA_TESTS.md`) |
| Legacy local-host capture + CMS50D | Implemented | TESTED-SOFTWARE + HARDWARE-UNTESTED | OpenCV camera on the host; serial oximeter overlay; 2-min motion-segment mode preserved; quality gate now null-reports consensus when invalid |
| Respiratory (tachogram) | Implemented (experimental) | TESTED-SOFTWARE | PRV explicitly not ECG HRV |
| Research backends (native/reference) | Implemented | TESTED-SOFTWARE | In-process, offline, MIT |
| External backends (rPPG-Toolbox, pyVHR, neural) | Implemented (optional, isolated) | TESTED-SOFTWARE (contract/availability tests only) | Never vendored; license boundaries enforced (RAIL-1.1 flow-down; GPL-3.0 subprocess-only; checkpoint terms unresolved ⇒ unavailable). **None has been executed against a dataset here** |
| Benchmark schema & provenance (`rsbvp.benchmark-record.v1`) | Implemented | TESTED-SOFTWARE | Missing values preserved; gap rejection; availability accounting; registry snapshot |
| Benchmarks on UBFC-rPPG (simple/realistic) | **NOT RUN — DATASET NOT AVAILABLE** | — | Archive verified absent; `reports/research_validation/DATA_READINESS.md`; UBFC-rPPG stays not-authorized-unverified |
| COHFACE | Missing (never present) | — | Same status |
| Real-camera accuracy, latency, browser FPS, CMS50D agreement | HARDWARE-UNTESTED / NOT RUN | — | Procedures prepared (`docs/MANUAL_CAMERA_TESTS.md`); no numbers exist |

## 2. Anemia image research (infrastructure only)

| Capability | Status | Evidence | Notes |
|---|---|---|---|
| Image QA (decode, size, illumination, exposure, clipping, sharpness, directional-blur heuristic, non-finite) | Implemented | TESTED-SOFTWARE (`test_anemia_features.py`) | `possible_motion_blur` is a documented anisotropy heuristic |
| Mask validation + coverage + ROI stats | Implemented | TESTED-SOFTWARE | Explicit reject reasons; percentiles/histograms; illumination indicators |
| Dataset audit (hashes, exact + near `aHash` duplicates, label join, patient grouping, QA buckets) | Implemented | TESTED-SOFTWARE (`test_anemia_audit.py`) | Output is sensitive research metadata; never commit |
| Patient-level split integrity | Implemented | TESTED-SOFTWARE | `grouped_holdout`, `assert_patient_disjoint`; image-level splits rejected |
| Anemia / Hb prediction, diagnosis, risk, thresholds | **Missing — by design** | — | Model card: no model until a governed, independently evaluated study exists; prohibited in this project |
| Automatic conjunctiva localization | **Missing** | — | Must be separately implemented, tested and labelled experimental; never conjunctival colour = Hb |

## 3. Data and validation

| Item | Status | Evidence |
|---|---|---|
| `reports/validation/validation.md` | `NOT RUN — DATASET NOT AVAILABLE` | unchanged, honest |
| `reports/research_validation/` (readiness, synthetic reliability, provenance/license/config) | Implemented | committed; reproducible from recorded config |
| Dataset manifest/reference tooling (`research/rppg/validate_dataset.py`, compare, dataset_io) | Implemented | TESTED-SOFTWARE on fixtures |
| Authorized UBFC-rPPG run (8-simple + 42-realistic) | **NOT RUN** | blocked on archive access + license verification; no numbers exist and none may be quoted |

## 4. Engineering quality gates

| Item | Status | Value |
|---|---|---|
| Python test suite | Implemented | **203 passed** (`python -m pytest -q`) |
| Frontend tests | Implemented | **17 passed** (`npm test`) |
| Frontend build / lint | Implemented | build OK (`vite`, ~388 kB); `oxlint` 0 errors |
| `compileall` / `git diff --check` | Implemented | clean |
| CI (`.github/workflows/ci.yml`) | Implemented | Python + frontend gates; dataset/GPU-independent; extend-only (no replacement) |
| MIT license + attribution preserved | Implemented | third-party notices in docs; no relabeling |

## 5. What is genuinely established vs what is not

**Established (software level, on synthetic fixtures):** deterministic reproducibility of backends/metrics/reports; gap handling and rejection accounting; quality-gate composition; low-light-POS flagging; schema integrity; license-register completeness; patient-split guards; browser/Python parity on the shared fixture; UI lifecycle error surfacing (permission denied, model load failure, worker crash, tab hidden, camera interruption).

**Not established (nothing may be claimed):** accuracy or reliability on any real recording or camera; UBFC-rPPG/COHFACE numbers; browser HR agreement outside the fixture; camera→browser colour fidelity; CMS50D agreement; anemia anything (no dataset, no model, no claim); any clinical utility, screening performance, or safety property.

## 6. Known open defects and limitations

1. Low-light POS plausible-but-wrong peaks: mitigated (flagged `low_quality`), not solved; synthetic-only evidence.
2. Browser estimator differs structurally from rolling-window Python POS/CHROM (documented; parity shown only for spectral stages).
3. Quality thresholds are uncalibrated research heuristics; SNR floor is relative to a periodogram median, not to camera physiology.
4. `performance.now()` clock is monotonic but not synchronized with `getVideoPlaybackQuality()` frame counts beyond the browser's own accounting.
5. Existing motion-correction heuristics (`gui/rppg_core/pipeline.py`) remain experimental and unvalidated; retained for reproducibility, not as proven improvements. Sprint 10 candidate_bpm validation (`quality.py`, `research.measurement_gate`) now gates corrected consensus against every trustworthy estimator so heuristics cannot manufacture an unsupported consensus HR.
6. Environment-dependent tests: AVI-codec-dependent probe tests skip on OpenCV builds that cannot decode their own AVI output.
7. Eyes-defy-anemia and any other anemia dataset: not present; audit tooling is ready but unexercised on real data.

## 7. Blocked by external dependencies (all documented)

Authorized UBFC-rPPG archive (+license clarity) · COHFACE · eyes-defy-anemia/licensed anemia data with identifiers · physical camera browser matrix · CMS50D · rPPG-Toolbox pinned checkout & neural checkpoints (RAIL-1.1/terms unresolved ⇒ unavailable) · pyVHR isolated env · GPU for neural inference · deployment target (Vercel-connected frontend only; capture needs a host). See `docs/REMAINING_EXTERNAL_REQUIREMENTS.md`.

## 8. Provenance

Sprint 10 (2026-11-24). Branch `feat/sprint-10-quality-robustness`. Baseline: `79e1cc9` (main after PR #5 merge). Commit `786eb67` (candidate_bpm validation hardening + regression tests). PR: see repository pull requests. All dataset/hardware validation: NOT RUN.
