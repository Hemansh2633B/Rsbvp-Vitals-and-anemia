# Open-Source License Register — RSBVP

**Compiled:** 2026-11-23 · **Scope:** every third-party tool, library, model checkpoint and dataset RSBVP depends on, imports, wraps, or documents.
**Status legend:** ✅ verified from source on the stated date · ⚠️ verify before redistribution · ⛔ rejected for use

RSBVP itself is **MIT** (`LICENSE`, © 2026 Mohammadreza Zamani). New Sprint 5 files preserve that license. No third-party copyright notice, license text, or attribution has been removed, and no third-party code has been relabeled MIT.

Version pins for first-party dependencies are resolved at build time by `gui/uv.lock` (Python) and `gui/frontend/package-lock.json` (npm); the identifiers below were checked against PyPI/npm registry metadata on 2026-11-23 and against the upstream LICENSE files in each project.

---

## A. Direct Python dependencies of the main application

| Tool | Source | Version (resolved) | License | Checkpoint license | Dataset terms | Integration method | Attribution requirement | Redistribution restrictions | Outstanding legal review |
|---|---|---|---|---|---|---|---|---|---|
| NumPy | https://github.com/numpy/numpy | ≥2.5 (CI: 2.5.5) | BSD-3-Clause | n/a | n/a | dependency (in-process) | retain copyright notice | permissive; notice retention only | none |
| SciPy | https://github.com/scipy/scipy | ≥1.18 (CI: 1.18.1) | BSD-3-Clause | n/a | n/a | dependency (in-process) | retain copyright notice | permissive; notice retention only | none |
| pandas | https://github.com/pandas-dev/pandas | ≥3.0 (CI: 3.1.1) | BSD-3-Clause | n/a | n/a | dependency (in-process) | retain copyright notice | permissive; notice retention only | none |
| Matplotlib | https://github.com/matplotlib/matplotlib | ≥3.11 (CI: 3.11.2) | PSF-2.0 | n/a | n/a | dependency (in-process, Agg backend) | retain copyright notice | permissive; notice retention only | none |
| OpenCV (headless) | https://github.com/opencv/opencv | opencv-python-headless 5.1.0.95 | Apache-2.0 | n/a | n/a | dependency (in-process, server only) | retain copyright + NOTICE file | permissive; NOTICE must travel with redistribution | none |
| FastAPI | https://github.com/fastapi/fastapi | ≥0.138 (CI: 0.165.0) | MIT | n/a | n/a | dependency (backend) | retain copyright notice | permissive | none |
| uvicorn | https://github.com/Kludex/uvicorn | ≥0.49 (CI: current) | BSD-3-Clause ⚠️ | n/a | n/a | dependency (backend) | retain copyright notice | permissive | confirm SPDX spelling in uv.lock at next bump |
| pytest | https://github.com/pytest-dev/pytest | ≥8 (CI: 9.2.0) | MIT | n/a | n/a | dev dependency (CI/tests) | retain copyright notice | permissive | none |
| h5py (optional) | https://github.com/h5py/h5py | ≥3.16 | BSD-3-Clause | n/a | n/a | optional dependency (dataset intake) | retain copyright notice | permissive | none |
| PyYAML (optional) | https://github.com/yaml/pyyaml | 6.x | MIT | n/a | n/a | optional (toolbox config generation) | retain copyright notice | permissive | none |
| PySerial | https://github.com/pyserial/pyserial | ≥3.5 | BSD-like ⚠️ | n/a | n/a | dependency (device bridge) | retain copyright notice | permissive | confirm exact SPDX spelling |
| python-multipart | https://github.com/Kludex/python-multipart | ≥0.0.32 | Apache-2.0 | n/a | n/a | dependency (backend forms) | retain NOTICE | permissive | none |

## B. Frontend dependencies (`gui/frontend/`)

| Tool | Source | Version (resolved) | License | Checkpoint license | Dataset terms | Integration method | Attribution requirement | Redistribution restrictions | Outstanding legal review |
|---|---|---|---|---|---|---|---|---|---|
| MediaPipe Tasks Vision (npm) | https://github.com/google-ai-edge/mediapipe · npm @mediapipe/tasks-vision | ^1.2.3 (1.2.3) | Apache-2.0 | n/a (model files: MediaPipe model cards) | n/a | npm runtime dependency; in-browser face landmarker | retain license + NOTICE; credit Google MediaPipe in docs | permissive; NOTICE retention | Face Landmarker .task model terms — see MEDIAPIPE_ASSETS.md |
| MediaPipe (repository) | https://github.com/google-ai-edge/mediapipe | master (docs reference) | Apache-2.0 | n/a | n/a | reference for browser integration | retain NOTICE | permissive | none |
| React / React-DOM | https://github.com/facebook/react | ^19.2.7 | MIT | n/a | n/a | npm dependency | retain copyright notice | permissive | none |
| Vite | https://github.com/vitejs/vite | ^8.1.0 | MIT | n/a | n/a | build tool | retain copyright notice | permissive | none |
| TypeScript | https://github.com/microsoft/TypeScript | ~6.0.2 | Apache-2.0 | n/a | n/a | dev dependency | retain NOTICE | permissive | none |
| Vitest | https://github.com/vitest-dev/vitest | ^5.1.1 | MIT | n/a | n/a | dev/test | retain copyright notice | permissive | none |
| oxlint | https://github.com/oxc-project/oxc | ^1.69.0 | MIT | n/a | n/a | dev/lint | retain copyright notice | permissive | none |
| jsdom | https://github.com/jsdom/jsdom | ^31.0.1 | MIT | n/a | n/a | dev/test | retain copyright notice | permissive | none |

## C. External research software (Sprint 5 integrations)

| Tool | Source | Version / commit | License | Checkpoint license | Dataset terms | Integration method | Attribution requirement | Redistribution restrictions | Outstanding legal review |
|---|---|---|---|---|---|---|---|---|---|
| UbiComp Lab rPPG-Toolbox | https://github.com/ubicomplab/rPPG-Toolbox | commit `b7500b848f84ad7f86e277b4612563b69f4f88f9` (2025-09-15) ✅ | RAIL-1.1 | RAIL-1.1 (see table E) — no separate weight statement ✅⚠️ | per-dataset; see table D ✅ | **external subprocess only** (`research/backends/rppg_toolbox.py`); source never copied; pinned commit enforced | cite toolbox paper + repo URL + NeurIPS 2023 D&B paper (Liu, Narayanswamy, Paruchuri et al., “rPPG-Toolbox: Deep Remote PPG Toolbox”, NeurIPS 2023 D&B, arXiv:2210.00716) and the toolbox LICENSE in any distribution or publication; retain RAIL-1.1 text | **§3.2 flow-down**: derivative works must carry RAIL-1.1 and forbid (i) surveillance/profiling uses, (ii) insurance-claim decisions/pricing, (iii) diagnosis without human oversight, (iv) criminal prediction from facial attributes, (v) undisclosed synthetic media. Flow the same terms to downstream users you distribute to. | whether CI log artifacts constitute "Derivative Works" when published; confirm NOTICE text of our adapter does not dilute RAIL-1.1 attribution; trained-weight redistribution is **prohibited** for RSBVP purposes |
| pyVHR | https://github.com/phuselab/pyVHR | master `a6270f04a97f05a13d145dd0a5e8c8df48d8bd62` (v2.0, 2024-11-20) ✅; CPU line branch `pyVHR_CPU` `e39ae5fa30c84c77300d43da5e3b8037fc852a9e` (v1.2, 2022-04-28) ✅; PyPI `pyvhr` 2.0 / `pyvhr-cpu` 1.0.2 | GPL-3.0 | MTTS-CAN weights ship inside the GPL-3.0 package; treat as GPL-3.0 | per-dataset; see table D | **external subprocess only** (`research/backends/pyvhr.py` + MIT driver `pyvhr_driver.py`); separate conda environment (`RSBVP_PYVHR_PYTHON`); source never copied or imported by the main app | cite the pyVHR PeerJ CS-929 paper + repo; GPL-3.0 notice if distributed | **copyleft**: any distributed derivative/combined work must be GPL-3.0; network use alone does not trigger copyleft; keep tool and outputs separate from MIT distribution packages unless legal clears it | aggregation vs derivative-work classification of the subprocess boundary; distribution of the MIT driver adjacent to GPL-3.0 pyVHR installs; MTTS-CAN weight terms inside pyVHR 1.0.2 (no explicit statement — treat as GPL-3.0) |
| PhysFormer (official repo) | https://github.com/ZitongYu/PhysFormer | commit `094c6942e8e7ebedf41dd407415d16bc9db34e1d` (2023-02-24) ✅ | MIT (code, © 2021 Zitong Yu) ✅ | **Not open** — VIPL checkpoints distributed via Google Drive (`Physformer_VIPL_fold1.pkl`) with **no stated weight license** ⛔ | VIPL-HR access-restricted | documentation only; **rejected** for inference | cite Yu et al. CVPR 2022 if used | n/a (not used) | whether any PhysFormer weights may ever be redistributed; do not mirror Google Drive weights |
| rPPG-Toolbox runtime stack | per toolbox `setup.sh`/`requirements.txt` @ pinned commit | torch 2.1.2+cu121; torchvision 0.16.2+cu121; mamba-ssm 2.2.2; causal-conv1d 1.0.0; yacs 0.1.8; scikit-learn 1.0.2; scikit-image 0.17.2; neurokit2 0.2.10; timm 1.0.11 | torch: BSD-style ⚠️; yacs: Apache-2.0 ⚠️; mamba-ssm/causal-conv1d: Apache-2.0 ⚠️; scikit-learn: BSD-3-Clause; scikit-image: BSD-3-Clause; neurokit2: MIT ⚠️; timm: Apache-2.0 ⚠️ | n/a | n/a | inside toolbox conda/uv environment only; **not** installed in main venv or CI | retain notices within toolbox env | per toolbox environment, not redistributed by RSBVP | verify the four ⚠️ identifiers before shipping a toolbox environment snapshot; `h5py==2.10.0` has known CVEs — isolated env only |
| ONNX Runtime (not adopted) | https://github.com/microsoft/onnxruntime | not adopted | MIT ⚠️ | n/a | n/a | documentation only — no verified ONNX exports of the five selected models exist | n/a | n/a | if/when verified conversions appear, repeat full review incl. weight licensing |
| OpenCV (external workflows) | https://github.com/opencv/opencv | 4.5.2.54 (toolbox pin), 5.x current | Apache-2.0 | n/a | n/a | optional dependency of external envs | NOTICE retention | permissive | none |

## D. Datasets (access-controlled research data — none redistributed)

| Dataset | Source | Terms (as stated upstream) | License | Citation | RSBVP status |
|---|---|---|---|---|---|
| UBFC-rPPG | https://sites.google.com/view/ybenezeth/ubfcrppg | request access via Google Sites form; research use; no redistribution | access-controlled, no SPDX | Bobbia et al., Pattern Recognition Letters 2017 | **not present** in this workspace; validation remains `NOT RUN — DATASET NOT AVAILABLE` |
| UBFC-Phys | https://sites.google.com/view/ybenezeth/ubfc-phys | request access; research use | access-controlled, no SPDX | Sabour et al., IEEE TAFFC 2021 | not present |
| COHFACE | https://www.idiap.ch/en/dataset/cohface | request form; research-only; attribution mandatory | access-controlled, no SPDX | Heusch, Anjos & Marcel, IEEE Biometrics Workshop 2017 | not present; do not scrape |
| PURE | TU Ilmenau data-sets page (see toolbox README) | request access; research use | access-controlled, no SPDX | Stricker et al., RO-MAN 2014 | not present |
| SCAMPS | https://github.com/danmcduff/scampsdataset | research use; synthetic twins; terms per repo LICENSE ⚠️ | verify upstream LICENSE ⚠️ | McDuff et al., NeurIPS 2022 (arXiv:2206.04197) | not present; potential redistributable candidate for regression tests — verify first |
| BP4D+ | Binghamton University (request) | request access; research use; no redistribution | access-controlled, no SPDX | Zhang et al., CVPR 2016 | not present |
| MMPD | https://github.com/McJackTang/MMPD_rPPG_dataset | research use; per repo terms ⚠️ | verify upstream ⚠️ | Tang et al., EMBC 2023 | not present |
| iBVP | https://github.com/PhysiologicAILab/iBVP-Dataset | per repo terms ⚠️ | verify upstream ⚠️ | Joshi & Cho, Electronics 2024, 13, 1334 | not present |
| VIPL-HR | request (see PhysFormer/toolbox docs) | request access | access-controlled | Niu et al., IEEE TBIOM 2020 | not present |
| MAHNOB-HCI | https://mahnob-db.eu/hci-tagging/ | request access; research use | access-controlled | Koelstra et al., IEEE TBMM 2012 | not present |
| LGI-PPGI | https://github.com/partofthestars/LGI-PPGI-DB | per repo terms ⚠️ | verify ⚠️ | Pilz et al., CVPRW 2018 | not present |
| V4V | https://vision4vitals.github.io/ | request access | access-controlled | Qiu et al., NeurIPS 2020 | not present |
| Vicar-PPG-2 | Google Forms (see pyVHR docs) | request access | access-controlled | Vicar-PPG-2 paper | not present |
| CMS50D recordings (project-internal) | local hardware | project participants; informed consent required | n/a (not distributed) | this repository | never committed; see PRIVACY.md |

## E. Model checkpoints distributed with the rPPG-Toolbox (`final_model_release/`)

All files below are part of the toolbox repository and are governed by the repository's **RAIL-1.1** license. No separate per-checkpoint license statement exists. **RSBVP never redistributes them; `.gitignore` blocks `*.pth`; adapters resolve a user-configured `RSBVP_MODEL_ROOT` and sha256-verify files at runtime.** "Open code" ≠ "open weights" — this table is the complete set considered for RSBVP.

| Checkpoint (file) | Architecture (toolbox name) | Trained on | Intended evaluation | License | RSBVP decision |
|---|---|---|---|---|---|
| PURE_TSCAN.pth | TS-CAN (Tscan, FRAME_DEPTH 10) | PURE | UBFC-rPPG | RAIL-1.1 ⚠️ | ✅ **selected first neural baseline** (Via toolbox only_test; not committed) |
| UBFC-rPPG_TSCAN.pth | TS-CAN (Tscan) | UBFC-rPPG | PURE | RAIL-1.1 ⚠️ | ✅ contract implemented (reverse-direction check) |
| MA-UBFC_tscan.pth | TS-CAN (Tscan) | motion-augmented UBFC-rPPG | UBFC-rPPG | RAIL-1.1 ⚠️ | ✅ contract implemented |
| SCAMPS_TSCAN.pth | TS-CAN (Tscan) | SCAMPS | UBFC-rPPG | RAIL-1.1 ⚠️ | ✅ contract implemented |
| PURE_DeepPhys.pth | DeepPhys | PURE | UBFC-rPPG | RAIL-1.1 ⚠️ | ✅ contract implemented |
| UBFC-rPPG_DeepPhys.pth | DeepPhys | UBFC-rPPG | PURE | RAIL-1.1 ⚠️ | ✅ contract implemented |
| MA-UBFC_deepphys.pth | DeepPhys | MA-UBFC-rPPG | UBFC-rPPG | RAIL-1.1 ⚠️ | ✅ contract implemented |
| SCAMPS_DeepPhys.pth | DeepPhys | SCAMPS | UBFC-rPPG | RAIL-1.1 ⚠️ | ✅ contract implemented |
| PURE_PhysNet_DiffNormalized.pth | PhysNet (FRAME_NUM 128) | PURE | UBFC-rPPG | RAIL-1.1 ⚠️ | ✅ contract implemented |
| UBFC-rPPG_PhysNet_DiffNormalized.pth | PhysNet | UBFC-rPPG | PURE | RAIL-1.1 ⚠️ | ✅ contract implemented |
| MA-UBFC_physnet.pth | PhysNet | MA-UBFC-rPPG | UBFC-rPPG | RAIL-1.1 ⚠️ | ✅ contract implemented |
| SCAMPS_PhysNet_DiffNormalized.pth | PhysNet | SCAMPS | UBFC-rPPG | RAIL-1.1 ⚠️ | ✅ contract implemented |
| PURE_EfficientPhys.pth | EfficientPhys (FRAME_DEPTH 10) | PURE | UBFC-rPPG | RAIL-1.1 ⚠️ | ✅ contract implemented |
| UBFC-rPPG_EfficientPhys.pth | EfficientPhys | UBFC-rPPG | PURE | RAIL-1.1 ⚠️ | ✅ contract implemented |
| MA-UBFC_efficientphys.pth | EfficientPhys | MA-UBFC-rPPG | UBFC-rPPG | RAIL-1.1 ⚠️ | ✅ contract implemented |
| SCAMPS_EfficientPhys.pth | EfficientPhys | SCAMPS | UBFC-rPPG | RAIL-1.1 ⚠️ | ✅ contract implemented |
| PURE_PhysFormer_DiffNormalized.pth | PhysFormer (DIM 96, 12 layers) | PURE | UBFC-rPPG | RAIL-1.1 ⚠️ | ✅ contract implemented (heaviest; GPU) |
| UBFC-rPPG_PhysFormer_DiffNormalized.pth | PhysFormer | UBFC-rPPG | PURE | RAIL-1.1 ⚠️ | ✅ contract implemented |
| SCAMPS_PhysFormer_DiffNormalized.pth | PhysFormer | SCAMPS | UBFC-rPPG | RAIL-1.1 ⚠️ | ✅ contract implemented |
| BP4D_PseudoLabel_TSCAN.pth | TS-CAN (pseudo-PPG labels) | BP4D+ | BP4D+ | RAIL-1.1 ⚠️ | ⛔ out of scope (BP4D+ access) |
| BP4D_PseudoLabel_DeepPhys.pth / BP4D_PseudoLabel_EfficientPhys.pth / BP4D_PseudoLabel_PhysNet_DiffNormalized.pth | as named (pseudo-PPG labels) | BP4D+ | BP4D+ | RAIL-1.1 ⚠️ | ⛔ out of scope (BP4D+ access) |
| PURE_BigSmall_*.pth / iBVP checkpoints | BigSmall / iBVPNet | PURE / iBVP | cross-dataset | RAIL-1.1 ⚠️ | ⛔ Sprint 5 not selected |
| PURE_FactorizePhys_FSAM_Res.pth / SCAMPS_* / UBFC-rPPG_* (same family) / iBVP_FactorizePhys_FSAM_Res.pth | FactorizePhys | PURE/UBFC-rPPG/SCAMPS/iBVP | cross-dataset | RAIL-1.1 ⚠️ | ⛔ Sprint 5 not selected |
| PURE_PhysMamba_DiffNormalized.pth / UBFC-rPPG_PhysMamba_DiffNormalized.pth | PhysMamba | PURE / UBFC-rPPG | cross-dataset | RAIL-1.1 ⚠️ | ⛔ requires mamba-ssm toolchain |
| PURE_RhythmFormer.pth / UBFC-rPPG_RhythmFormer.pth | RhythmFormer | PURE / UBFC-rPPG | cross-dataset | RAIL-1.1 ⚠️ | ⛔ Sprint 5 not selected |
| BP4D_BigSmall_Multitask_Fold{1,2,3}.pth | BigSmall multitask | BP4D+ | BP4D+ | RAIL-1.1 ⚠️ | ⛔ out of scope |

## F. Obligation summaries

### F.1 RAIL-1.1 (rPPG-Toolbox) — what running it in CI/research obligates
- ✅ Keep the complete RAIL-1.1 text with any distribution of the toolbox or derivatives.
- ✅ Attribution: toolbox paper + repository URL in publications/reports that use its outputs.
- 🚫 Never use (whether via the toolbox or an RSBVP adapter) for: surveillance/profiling of legally protected classes or identity traits; medical diagnosis **without human oversight**; insurance pricing/claims; criminal prediction; undisclosed synthetic media.
- 🚫 Do not remove the §3.2 restrictions in downstream agreements; flow them through.
- 🚫 Do not relabel toolbox code/weights as MIT or Apache-2.0.
- Note: research benchmarking on UBFC-rPPG for HR algorithm comparison is within scope; it never asserts diagnosis.

### F.2 GPL-3.0 (pyVHR) — what running it in a research environment obligates
- ✅ Keep pyVHR in its own environment; RSBVP imports nothing from it at build/test time.
- ✅ The RSBVP driver (`research/backends/pyvhr_driver.py`) is MIT and only calls public pyVHR APIs at runtime; it may be distributed, but any combined work distributed with pyVHR itself becomes GPL-3.0.
- ✅ Cite the pyVHR PeerJ CS-929 paper; retain GPL-3.0 notices.
- 🚫 Do not paste pyVHR functions into RSBVP source files.
- 🚫 Do not statically link or vendor; do not ship pyVHR inside the Vercel deployment, Docker images for end users, or the browser bundle.

### F.3 Apache-2.0 (MediaPipe, OpenCV, …)
- ✅ Retain LICENSE/NOTICE; state changes if you modify (RSBVP does not modify MediaPipe source).

### F.4 Datasets
- ✅ Access via each provider's request process only; never scrape; never redistribute; pseudonymize in outputs; delete when leaving the project; keep reference measurements separate from predictions; do not tune on held-out test subjects.

## G. Outstanding legal review (blocking items)

1. RAIL-1.1 §3.2 compatibility of publishing adapter-parsed metric logs (Bland–Altman PDFs, printed metric tables) produced by the toolbox on authorized UBFC-rPPG data — confirm before any public release of such artifacts.
2. Aggregation-vs-derivative classification of distributing the MIT pyVHR driver alongside a GPL-3.0 pyVHR install (RSBVP never ships pyVHR itself — confirm acceptable downstream posture).
3. Whether PhysFormer Google Drive VIPL weights or any toolbox `.pth` may be mirrored internally for air-gapped evaluation — current answer: **no**.
4. SCAMPS/MMPD/LGI-PPGI/iBVP upstream licenses (⚠️ rows) if those datasets are ever used for regression testing.
5. uvicorn / pyserial / yacs / mamba-ssm / causal-conv1d / neurokit2 / timm exact SPDX spellings at next dependency bump (⚠️ rows).
6. Vercel/static-hosting posture: confirmed to serve **only** the browser rPPG frontend; no external neural inference, no datasets, no checkpoints.

## H. Register maintenance

Validation (`tests/test_license_register.py`) enforces: presence of this file's required sections and column headers; the three critical identifiers (`RAIL-1.1`, `GPL-3.0`, `Apache-2.0`); full pinned commit SHAs; absence of RAIL-1.1/GPL license text inside `research/backends/*.py`; `.gitignore` blocking `*.pth`. Re-run it on every dependency change; re-verify registry metadata on every version bump.
