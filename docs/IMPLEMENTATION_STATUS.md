# Implementation status — authoritative capability matrix

**Last updated:** 2026-11-23 (Sprint 9). Baseline: `main` @ `79e1cc9`. Evidence
tiers are never upgraded because tests pass; a green CI run is
software verification, not physiological or clinical validation. Status
vocabulary: `DONE` (implemented + software-tested for its stated scope) ·
`PARTIAL` (implemented with documented gaps) · `NOT IMPLEMENTED` ·
`NOT RUN` (implemented, but the required data/hardware/protocol has not been
executed) · `BLOCKED` (cannot proceed without external input).

| Component | Implementation status | Source files | Tests | Known limitations | Evidence level | Next action |
|---|---|---|---|---|---|---|
| Green rPPG estimator (Python) | DONE | `gui/rppg_core/pipeline.py`, `gui/rppg_core/research.py` | yes (`test_rppg_research.py`, `test_backends_*`) | Historical correction heuristics retained; not validated | SOFTWARE-TESTED | Dataset evaluation (blocked) |
| POS estimator (Python) | DONE | `gui/rppg_core/pipeline.py`; `research/backends/reference_methods.py` | yes | Low-light false-accept risk on synthetic fixtures (documented); not physiologically calibrated | SYNTHETIC-TESTED | Independent dataset run |
| CHROM estimator (Python) | DONE | `gui/rppg_core/research.py::chrom_rppg` | yes (incl. invalid-input contract, Sprint 8) | Zero-phase Butterworth differs from browser path by design; no physiological validation | SYNTHETIC-TESTED | Dataset evaluation |
| POS/CHROM (browser TS) | DONE | `gui/frontend/src/rppg/liveDsp.ts` | yes (`liveDsp.test.ts`, parity tests) | No IIR filter in browser; band restriction via in-band Hann periodogram | SYNTHETIC-TESTED | Physical camera matrix (NOT RUN) |
| Python↔browser DSP parity | PARTIAL | `tests/fixtures/rppg_rgb_fixture.csv`, `liveDsp.parity.test.ts` | yes | Demonstrated on ONE synthetic fixture only; real-camera parity unknown | SYNTHETIC-TESTED | Multi-fixture + hardware protocol |
| Green/POS/CHROM selection + display (browser) | DONE | `BrowserPulse.tsx`, `Live.tsx` | yes (component tests) | Selection is user choice; consensus always visible | SOFTWARE-TESTED | Usability review |
| Six-concept quality model (browser) | DONE (software) | `gui/frontend/src/rppg/liveDsp.ts` (`concepts`) | yes (`liveDsp.test.ts`) | Heuristic thresholds; NOT physiologically validated; no blended score | SYNTHETIC-TESTED | Real-camera calibration study |
| Six-concept quality model (Python) | DONE (software) | `gui/rppg_core/quality.py` | yes (`test_quality.py`) | Same threshold caveats | SYNTHETIC-TESTED | Same |
| ROI coverage gate (union ≥ 0.50) | DONE (software) | TS `liveDsp.ts`; Python `quality.py` | yes (both suites) | Coverage counts usable-skin samples, not pixels; 0.50 is a research heuristic | SYNTHETIC-TESTED | Contract study on real faces |
| Motion-buffer purge (> 8 % centre spread ⇒ window reset) | DONE (software) | `BrowserPulse.tsx` | partial (lifecycle tests) | UI-level heuristic; does not prove motion-free data | SOFTWARE-TESTED | Manual camera protocol |
| MediaPipe Face Landmarker init (GPU→CPU fallback) | DONE | `BrowserPulse.tsx` | yes (mocked fallback test) | Model artifact license terms not independently verified (see MEDIAPIPE_ASSETS) | SOFTWARE-TESTED | Legal review of artifact terms |
| MediaPipe cleanup on stop/unmount | DONE | `BrowserPulse.tsx` (`stop()`) | yes (component tests: tracks stopped, worker terminated, `landmarker.close()`) | `close()` called, not awaited | SOFTWARE-TESTED | — |
| MediaPipe failure paths (permission, missing GPU, no camera, worker crash, hidden tab, face loss, reacquisition) | DONE (software) | `BrowserPulse.tsx` | yes (mocked, `BrowserPulse.test.tsx`) | No physical-camera execution yet | SOFTWARE-TESTED | `docs/MANUAL_CAMERA_TESTS.md` execution |
| Multi-ROI trace contract (`rsbvp.rgb-trace.v1`) | DONE (doc + both pathways) | `docs/RGB_TRACE_FORMAT.md`, exporters | yes (rois/export tests) | Browser = landmark ROIs; Python = heuristic ROIs; values not byte-identical | SOFTWARE-TESTED | Document in validation report |
| Per-window export (`rsbvp.window-analysis.v1`) + provenance | DONE | `BrowserPulse.tsx`, `gui/frontend/src/rppg/{exports.ts,provenance.ts}`, `docs/EXPORT_SCHEMA.md` | yes (`exports.test.ts`) | Windows overlap; correlated observations | SOFTWARE-TESTED | Schema-compat review on `v2` |
| Quality verdict styling/reasons in UI | DONE | `BrowserPulse.tsx`, `App.css` | yes | Reasons are technical strings | SOFTWARE-TESTED | Mobile usability pass |
| Legacy Python live pipeline (OpenCV webcam, CMS50D) | PARTIAL | `gui/rppg_core/*`, backend | partially | Requires backend host hardware; heuristic corrections retained; NOT validated | SOFTWARE-TESTED / HARDWARE-UNTESTED | Hardware test session |
| Algorithm comparison CLI | DONE | `research/rppg/compare_algorithms.py` | yes | Requires externally supplied synchronized traces; fabricates nothing | SOFTWARE-TESTED | Dataset run (blocked) |
| Benchmark run provenance (`rsbvp.benchmark-run.v1`) | DONE | `research/backends/{run_info.py,benchmark.py}` | yes (`test_backends_run_info.py`) | Records environment + manifest SHA-256; does not attest data authorization | SOFTWARE-TESTED | Dataset run (blocked) |
| Export provenance (software/commit, config, session id) | DONE | `gui/rppg_core/version.py`, `gui/frontend/src/rppg/provenance.ts` | yes | `commit` = `unknown` unless `VITE_GIT_SHA`/`RSBVP_GIT_SHA` set; never invented | SOFTWARE-TESTED | Release pipeline sets commit |
| Camera/hardware session record (`rsbvp.camera-test-record.v1`) | DONE (infrastructure) | `research/camera/`, `docs/CAMERA_HARDWARE_VALIDATION.md` | yes (`test_camera_record.py`) | Validator checks structure only; cannot attest a session ran; physical tests NOT RUN | SOFTWARE-TESTED | Supervised session (blocked) |
| Anemia readiness audit | DONE (documentation) | `docs/ANEMIA_READINESS.md` | — | No dataset, no model; requirements listed, none satisfied | NOT AVAILABLE | Lawful labeled dataset + oversight |
| UBFC-rPPG dataset validation | NOT RUN | `research/rppg/{validate_dataset,ubfcrppg_probe}.py`, `reports/research_validation/` | probe tests yes | Archive absent; mirror claims (e.g. Kaggle CC0) not accepted as provider authorization | NOT RUN | Obtain archive per DATA_READINESS.md §5 |
| COHFACE validation | NOT RUN | — | — | Not present; EULA-gated; do not redistribute | NOT RUN | Authorized access only |
| rPPG-Toolbox backend integration | PARTIAL | `research/backends/rppg_toolbox.py` (unavailable; RAIL-1.1, not vendored) | availability-gated tests | Requires external env + checkpoints; license boundaries enforced | NOT RUN (backend absent) | Install in isolated env |
| Neural checkpoints (5 tracked, none runnable) | NOT IMPLEMENTED (runnable inference) | `research/backends/neural.py` | availability-gated | No checkpoint satisfies provenance policy | NOT RUN | Provenance-verified checkpoints |
| CMS50D reference comparison | NOT RUN | `gui/rppg_core` (serial option) | — | No device in this environment | NOT RUN | Hardware session |
| Anemia image contract + annotation format | DONE (foundations) | `research/anemia/contract.py`, `docs/ANEMIA_IMAGE_CONTRACT.md` | yes (`test_anemia_contract.py`) | No dataset; no model; contract untested on real conjunctival images | SOFTWARE-TESTED | Lawful dataset (blocked) |
| Anemia image QA / colour utilities | DONE | `gui/anemia_core/image_features.py` | yes (`test_anemia_features.py`) | Colour heuristics; camera-dependent | SOFTWARE-TESTED | — |
| Anemia dataset audit (hashes, near-dups, patient groups) | DONE | `research/anemia/audit_dataset.py` | yes (`test_anemia_audit.py`) | aHash is a review aid, not proof | SOFTWARE-TESTED | Run on authorized data |
| Anemia model / predictor | **NOT AVAILABLE — NO VERIFIED LABELED DATASET** | — | — | Prohibited without provenance, permissions, lab Hb labels, oversight, patient-independent splits, independent evaluation | none | Blocked on data + governance |
| CI (dataset/GPU/webcam-free) | DONE | `.github/workflows/ci.yml` | — | Cannot exercise camera paths | SOFTWARE-TESTED | Keep green |

## Reading the evidence tiers

`software-tested` = deterministic tests pass. `synthetic-tested` = tested on
synthetic fixtures only. `hardware-tested` = executed on a physical camera /
CMS50D. `physiologically validated` / `clinically validated` = **neither has
occurred anywhere in this project**. Any statement upgrading these tiers
without such runs is a defect — report it.

See also: `docs/RELIABILITY.md` (failure modes), `docs/RESEARCH_METHODOLOGY.md`
(protocol), `reports/research_validation/validation_report.md` (validation
status), `docs/REMAINING_EXTERNAL_REQUIREMENTS.md` (what is blocked on whom).
