# Initial repository audit — HISTORICAL (2026-11-23, baseline `f827cdd`)

> **This document is a historical record of the state of the repository at the first audit and is kept for provenance only. It does not describe the current system.** For the current capability matrix see [`CURRENT_STATUS_AUDIT.md`](CURRENT_STATUS_AUDIT.md). Many limitations listed below (no Python test suite, no frontend tests, no MediaPipe capture path, minimal quality gating, 60–90 BPM defaults) have since been addressed; consult the methodology and reliability documents for present status.


Audit performed 2026-11-23 against the checked-out baseline `f827cdd` (grafted history contains this commit only; full earlier history was not present locally). Working tree was clean at inspection.

## Existing implementation

- `gui/rppg_core/pipeline.py` is a substantial headless extraction of the earlier `final_with_PR_n_metrics.py` research code. It includes Green/POS, FFT candidates, peak-guided consensus, motion classification, three facial regions in offline extraction, respiratory tachogram analysis, plots, and CMS50D comparison support.
- `gui/rppg_core/live.py`, `live_eval.py`, and `device.py` support local OpenCV webcam acquisition, optional serial device integration, websocket live status and evaluation. Backend is FastAPI and stores uploaded runs in `gui/runs`.
- `gui/frontend` is React 19, TypeScript and Vite. It already has offline upload, a live websocket screen, result metrics/plots and device status.
- Historical notebooks, archived variants, live/offline scripts and MIT attribution are present and were preserved.
- There is no anemia pipeline, no Python test suite, and frontend scripts have no test command. No separate baseline recordings or reference data were found in the repository inventory.

## Baseline execution

- `python -m pytest -q` from `gui`: unavailable because pytest is not installed in the environment (`No module named pytest`).
- `npm test -- --run` from `gui/frontend`: unavailable because no test script exists.
- No camera or CMS50D hardware was available/used. No experimental performance claims are made.
- Source inspection found the central pipeline defaults at 60–90 BPM, despite broad research requirements. The filter used direct-form coefficients and silently returned original signals on exceptions. Frontend development proxies only backend `/api` and `/ws` paths. Backend uses its host camera, so hosted execution cannot access the browser camera.

## Risks / unfinished work

- Existing live and offline code paths have distinct capture assumptions; default webcam access is backend-local, not browser-local.
- Existing motion correction heuristics need independent data-based evaluation and must not be treated as proven improvements.
- Available recording provenance and dataset inventory are insufficient to establish reproducible baseline performance.
- MediaPipe Tasks Vision, browser-side multi-ROI capture, stable tracking and ROI visual feedback are not implemented here; this is an environment/development limitation rather than a claim of functionality.
- No eyes-defy-anemia data is in the checkout. Its access, license and identifiers must be independently verified before data use; no dataset or model has been fabricated.
- Dataset-level algorithm comparison, PRV validation, RR validation and clinical validation remain outstanding.

## Changes made after audit

Central defaults are widened to 42–210 BPM; the reusable filter now uses SOS and validates Nyquist/passband inputs. Added independent CHROM RGB processing, timestamp-derived sampling-rate helper and conservative quality-state helper with synthetic unit tests. Offline ROI extraction now uses a conservative YCrCb skin heuristic, retains separate ROI RGB samples, records frame-gap indicators and uses decoder timestamps where available. The UI now identifies the project and disclosures; anemia utilities/audit tooling and upload limits were added. Existing Green/POS, legacy correction/evaluation code, archives, notebooks and license were not removed. MediaPipe landmark tracking and browser-side live DSP remain unimplemented. See project documentation for limitations and deployment boundary.
