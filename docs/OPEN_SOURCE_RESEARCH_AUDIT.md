# Open-Source Research Software Audit — RSBVP Sprint 5

- **Date:** 2026-11-23
- **Branch audited:** `arena/ae4b6f9b-rsbvp-vitals-and-anemia` (based on `main` @ `ed2b2872deb9158a0a2cf971151a6763da598414`)
- **Method:** static review of the checked-out repository; read-only inspection of the four reference projects' public sources via their official repositories (all findings verified on 2026-11-23 and pinned by commit/digest in `docs/OPEN_SOURCE_LICENSE_REGISTER.md`).
- **Companion documents:** `docs/OPEN_SOURCE_LICENSE_REGISTER.md` (licenses), `docs/RESEARCH_BACKENDS.md` (integration, setup, fair comparison), `docs/SPRINT_3_AUDIT.md`, `docs/ALGORITHM_COMPARISON.md`.

> This document audits what exists and what may be integrated. It does not claim any
> dataset evaluation has been performed. The UBFC-rPPG archive is not present in this
> workspace; `reports/validation/validation.md` remains `NOT RUN — DATASET NOT AVAILABLE`.

---

## 1. What RSBVP already has (reuse, do not rebuild)

| Component | Location | Audited state | Reuse decision |
|---|---|---|---|
| Python offline rPPG pipeline (Green, POS, FFT peak picking, motion classes, HR/RR estimation, CMS50D evaluation) | `gui/rppg_core/pipeline.py` | Legacy but working; global constants `MIN_BPM=42`, `MAX_BPM=210`; 12 s windows | **Reuse unchanged** for the main application; call read-only from `rsbvp_native` backend. Do not refactor in this sprint. |
| CHROM implementation + RGB resampling + quality gates | `gui/rppg_core/research.py` (`chrom_rppg`, `timestamps_to_fs`, `resample_rgb_traces`, `measurement_gate`) | Independent CHROM utility; gap-aware; documented | **Reuse** via native backend. |
| Browser rPPG (MediaPipe Face Landmarker, ROI polygons, timestamped RGB sampling, in-browser Green/POS/CHROM, quality states, CSV export) | `gui/frontend/src/rppg/*` | Works; vitest coverage incl. Python-parity fixture | **Preserve.** No Python frameworks may enter the browser bundle. |
| Offline algorithm comparison CLI (Green/POS/CHROM, ROI variants) | `research/rppg/compare_algorithms.py` | Working; reference provenance user-attested | **Reuse as-is**; superseded for new backends by `research/backends/benchmark.py` but kept for compatibility. |
| UBFC/COHFACE dataset intake + validation (local manifests, reference-waveform processing, participant-level metrics, bootstrap) | `research/rppg/dataset_io.py`, `research/rppg/validate_dataset.py` | Thorough; handles monotone timestamps, jitter, gaps, ECG rejection | **Reuse unchanged.** No reimplementation of reference-HR logic. |
| Anemia image/feature utilities | `gui/anemia_core/*` | Research utilities; no dataset, no model, no clinical claim | **Out of scope** for Sprint 5; unchanged. |
| FastAPI backend + React/Vite frontend | `gui/backend/main.py`, `gui/frontend/*` | Working; proxies `/api` and `/ws`; Vercel hosts static frontend only | **Untouched.** Neural models must not be added to this path. |
| Dataset manifest examples | `data/manifests/*.example.csv`, `data/README.md` | Format documentation | **Reuse** for benchmark input format documentation. |
| CI | `.github/workflows/ci.yml` | Python tests + compileall; frontend test/build/lint | **Extended** with research-backend coverage (see §9). |
| Synthetic fixtures | `tests/fixtures/rppg_rgb_fixture.csv` (+ expected JSON) | Deterministic 70 BPM fixture | **Reuse** in backend tests; synthetic data is software verification only. |

### Existing algorithm coverage inside RSBVP

- **Green-channel rPPG** — Python (`pipeline.py`), browser (`liveDsp.ts`), comparison CLI.
- **POS** — Python (`pipeline.pos_rppg`, Wang 2017 formulation), browser, comparison CLI.
- **CHROM** — Python (`research.chrom_rppg`, de Haan & Jeanne 2013), browser, comparison CLI.
- **FFT/Welch HR estimation** — Python (`estimate_windowed_fft`, Welch in comparison CLI, Hann-periodogram-style passband restriction), 162 ms/frame-class browser worker.
- **No in-repo ICA, LGI, PBV, OMIT, SSR, PCA, or any neural method.** These are candidates for external integration or independent reference implementation.

## 2. Algorithms: already implemented vs. needing independent reference

| Algorithm | In RSBVP | Needed for Sprint 5 | Disposition |
|---|---|---|---|
| GREEN (Verkruysse 2008) | yes (3 impls) | parity anchor | Native backend wraps existing; reference backend has independent reimplementation |
| POS (Wang 2017) | yes (Python + browser) | parity anchor | Same as above; reference implementation uses the paper's projection form |
| CHROM (de Haan & Jeanne 2013) | yes (Python + browser) | parity anchor | Same as above |
| ICA (Poh 2010/2011) | **no** | prioritized unsupervised method | **Independent reference implementation written** (`research/backends/reference_methods.py`, deterministic whitening + deflated FastICA with spectral-concentration component selection). Not copied from any project. |
| LGI (Pilz 2018) | **no** | prioritized unsupervised method | Video-domain algorithm. Delegated to external backends (rPPG-Toolbox / pyVHR). Trace-domain approximation judged not meaningful; reported unsupported by in-process backends rather than faked. |
| PBV (de Haan & van Leest 2014) | **no** | prioritized unsupervised method | Trace-domain **approximation** in reference backend (signature-gated chrominance) — documented as such, fitness for purpose unproven. Authoritative comparison via external backends. |
| OMIT / Face2PPG (Álvarez Casado 2023) | **no** | "where dependencies permit" | Video-domain; OMIT in the toolbox needs only NumPy but operates on frames + Haar face detection inside the toolbox pipeline. Delegated to rPPG-Toolbox adapter; not approximated in-process. |
| SSR (Wang 2015), PCA (Lewandowska 2011) | **no** | "other supported methods" via pyVHR | Available through the optional pyVHR adapter (external); not reimplemented. |
| DeepPhys (ECCV 2018) | **no** | selected neural baseline family | rPPG-Toolbox `only_test` integration; checkpoint contract via `RSBVP_MODEL_ROOT`. |
| PhysNet (BMVC 2019) | **no** | selected neural baseline family | Same. |
| TS-CAN (NeurIPS 2020) | **no** | selected neural baseline family | Same — **recommended first neural baseline** (small, fast, toolbox example). |
| EfficientPhys (WACV 2023) | **no** | selected neural baseline family | Same. |
| PhysFormer (CVPR 2022) | **no** | selected neural baseline family | Same; heaviest of the five; 128×128 inputs. |

## 3. External tools: suitable for optional integration

All external tools are integrated **as optional research environments via subprocess adapters**. None of their source is vendored into this repository. Details and exact pins are in `docs/OPEN_SOURCE_LICENSE_REGISTER.md`.

| Tool | Source (pinned) | License | Suitable for | Integration decision |
|---|---|---|---|---|
| rPPG-Toolbox | github.com/ubicomplab/rPPG-Toolbox @ `b7500b848f84ad7f86e277b4612563b69f4f88f9` (2025-09-15) | RAIL-1.1 | Unsupervised GREEN/ICA/CHROM/POS/LGI/PBV/OMIT; neural DeepPhys/PhysNet/TS-CAN/EfficientPhys/PhysFormer + 34 more checkpoints; UBFC-rPPG & 7+ other datasets; UBFC evaluation workflow | **Yes** — `research/backends/rppg_toolbox.py` (subprocess, pinned commit enforcement) |
| pyVHR | github.com/phuselab/pyVHR @ master `a6270f04a97f05a13d145dd0a5e8c8df48d8bd62` (v2.0, 2024-11-20); CPU branch `pyVHR_CPU @ e39ae5fa30c84c77300d43da5e3b8037fc852a9e` (2022-04-28, v1.2) | GPL-3.0 | Independent cross-check of GREEN/POS/CHROM/ICA/PCA/SSR/LGI/PBV/OMIT/MTTS-CAN; UBFC/COHFACE/PURE/… loaders; nonparametric stats | **Yes** — `research/backends/pyvhr.py` + MIT driver; **strictly external, separate environment**, never vendored |
| PhysFormer (official) | github.com/ZitongYu/PhysFormer @ `094c6942e8e7ebedf41dd407415d16bc9db34e1d` (2023-02-24) | MIT (code); weights via Google Drive, **no weight license stated** | VIPL-HR training/inference code | **No** direct use — toolbox-distributed PhysFormer checkpoints used instead; official weights rejected (unverified license, Google Drive mirror policy) |
| MediaPipe | github.com/google-ai-edge/mediapipe (master); npm `@mediapipe/tasks-vision` 1.2.3 | Apache-2.0 | Face landmarking (already used in browser) | **Already in use** in the frontend; keep; no Python mediapipe needed |
| OpenCV | PyPI `opencv-python(-headless)` | Apache-2.0 | Video decode, image processing | Optional dependency of external workflows only; headless build in CI |
| NumPy / SciPy / pandas / Matplotlib | PyPI | BSD-3-Clause / BSD-3-Clause / BSD-3-Clause / PSF-2.0 | Numerical core for in-process backends + reporting | **In use**; already CI dependencies |
| ONNX Runtime | PyPI `onnxruntime` | MIT | Portable inference *if a verified conversion exists* | **Not adopted** — no verified ONNX exports of the five models exist; conversion would constitute re-implementation of model graphs without validation; revisit per-model with tests |
| PyTorch | PyPI `torch` (2.1.2+cu121 per toolbox setup.sh) | BSD-style (modified BSD) | Neural inference inside toolbox environment | Toolbox environment only; **not** a dependency of the main application or CI |

### rPPG-Toolbox facts (verified 2026-11-23)

- **Install:** `bash setup.sh conda` (python 3.8, `torch==2.1.2+cu121`, then `pip install -r requirements.txt`) or `uv` variant; Linux/macOS supported; Windows via WSL2. `mamba-ssm==2.2.2` + `causal-conv1d` are required by requirements.txt — they compile from source and may need `clang++`; **CUDA 12.1 required for the pinned torch build**; CPU-only operation not documented upstream.
- **Configuration:** YAML, one file per run under `configs/infer_configs/` or `configs/train_configs/`; `TOOLBOX_MODE` ∈ {train_and_test, only_test, unsupervised_method}; `UNSUPERVISED.METHOD ∈ {GREEN, ICA, CHROM, POS, LGI, PBV, OMIT}`; `METRICS ∈ {MAE, RMSE, MAPE, Pearson, SNR, BA}`; face crop Haar Cascade (HC, default) or YOLO5Face (Y5F); `DO_PREPROCESS` must be true on first use per dataset cache.
- **Datasets (loaders):** SCAMPS, UBFC-rPPG, PURE, BP4D+, UBFC-Phys, MMPD, iBVP, PhysDrive, SUMS, LADH (added Sep 2025). Layout: `data/<DATASET>/<subject>/vid.* + ground_truth.txt` for UBFC-rPPG.
- **Unsupervised inference:** `python main.py --config_file configs/infer_configs/UBFC-rPPG_UNSUPERVISED.yaml` — prints per-method aggregate MAE/RMSE/MAPE/Pearson/SNR/MACC and saves Bland–Altman PDFs. **It does not emit per-window predictions to disk** — adapter records are aggregate with the log preserved.
- **Neural only_test:** `configs/infer_configs/<train>_<test>_<MODEL>_BASIC.yaml`, e.g. `PURE_UBFC-rPPG_TSCAN_BASIC.yaml` (PURE-trained, UBFC-rPPG test). Prints summary metrics; likewise aggregate.
- **Outputs:** BA PDFs + stdout summaries under `LOG.PATH`; predictions pickle only when `TEST.OUTPUT_SAVE_DIR` is set (neural only).

### pyVHR facts (verified 2026-11-23)

- **Install (CPU-only):** conda env from `pyVHR_CPU/pyVHR_CPU_env.yml` (python 3.9.7, pytorch 1.10.0 cpuonly, numba 0.53.1, mediapipe 0.8.8.1, tensorflow 2.5.0) then `pip install pyvhr-cpu` (PyPI 1.0.2). **CPU build is the v1.2 line (2022) — old dependency floor, includes TensorFlow 2.5** — treat as legacy.
- **Install (current, GPU):** conda env from `pyVHR_env.yml` (python 3.9, cudatoolkit 11.3, pytorch latest for cu113) then `pip install pyvhr` (PyPI 2.0).
- **Methods:** Green, CHROM, ICA, LGI, PBV, PCA, POS, SSR, OMIT, MTTS-CAN (+ HR-CNN listed); CPU methods are prefixed `cpu_`.
- **Datasets:** COHFACE, LGI-PPGI, MAHNOB-HCI, PURE, UBFC1/2, UBFC-Phys, ECG-Fitness, Vicar-PPG-2, V4V, VIPL-HR.
- **Not vendored.** The driver is launched in the pyVHR environment; outputs are new data, not derivative source.
- **Can a CPU-only environment run a useful benchmark?** Partially: pyVHR-CPU 1.2 runs classical methods on UBFC-style datasets on modest CPUs; MTTS-CAN on CPU is possible but slow. The 2022 pins (python 3.9/torch 1.10) conflict with the repository's Python ≥3.12/torch-free main app but coexist fine as a separate conda env. The v2.0 line without a GPU also works for classical methods (`cuda=False`), but its env targets cu113. **Recommended:** separate conda env, CPU, classical methods only, smoke-benchmark on UBFC-rPPG when authorized — else documented as not runnable in this workspace. See `docs/RESEARCH_BACKENDS.md`.

## 4. Model weights: what is actually available

| Model (toolbox name) | Official artifact | Location / access | Weight license | Verdict |
|---|---|---|---|---|
| DeepPhys (DeepPhys) | `PURE_DeepPhys.pth`, `UBFC-rPPG_DeepPhys.pth`, `MA-UBFC_deepphys.pth`, `SCAMPS_DeepPhys.pth` | in-repo `final_model_release/` of the toolbox (download with the toolbox; ~8.9 MB each) | RAIL-1.1 (distributed under repository LICENSE; no separate statement) | **Available via toolbox checkout only** — never commit to RSBVP git; configure `RSBVP_MODEL_ROOT` |
| PhysNet (Physnet) | `PURE_PhysNet_DiffNormalized.pth`, `UBFC-rPPG_PhysNet_DiffNormalized.pth`, `MA-UBFC_physnet.pth`, `SCAMPS_PhysNet_DiffNormalized.pth`, `BP4D_PseudoLabel_PhysNet_DiffNormalized.pth` | same | same | same |
| TS-CAN (Tscan) | `PURE_TSCAN.pth`, `UBFC-rPPG_TSCAN.pth`, `MA-UBFC_tscan.pth`, `SCAMPS_TSCAN.pth`, `BP4D_PseudoLabel_TSCAN.pth` | same | same | same — **recommended first neural baseline** |
| EfficientPhys (EfficientPhys) | `PURE_EfficientPhys.pth`, `UBFC-rPPG_EfficientPhys.pth`, `MA-UBFC_efficientphys.pth`, `SCAMPS_EfficientPhys.pth`, `BP4D_PseudoLabel_EfficientPhys.pth` | same | same | same |
| PhysFormer (PhysFormer) | `PURE_PhysFormer_DiffNormalized.pth`, `UBFC-rPPG_PhysFormer_DiffNormalized.pth`, `SCAMPS_PhysFormer_DiffNormalized.pth` | same | same | same; also: official VIPL weights on Google Drive (**rejected** — no weight license stated) |
| BigSmall, FactorizePhys, RhythmFormer, PhysMamba, iBVPNet | various `.pth` in same folder | same | same | documented; out of scope for Sprint 5 |
| Official PhysFormer VIPL fold1 | `Physformer_VIPL_fold1.pkl` | Google Drive link in upstream README | **not stated** | **Rejected** — do not download; do not benchmark |
| pyVHR MTTS-CAN | bundled with pyVHR package | PyPI / repo | GPL-3.0 | Available inside pyVHR env only |

**Non-negotiable policy:** checkpoints are resolved from a user-configured `RSBVP_MODEL_ROOT`, sha256-verified by the adapter, and **never committed** (`.gitignore` blocks `*.pth`). "Public code" ≠ "open weights": everything above marked RAIL-1.1 requires the RAIL-1.1 flow-down restrictions (see register). Where no legal checkpoint exists for a model, the adapter must report **unavailable** — never substitute, never fabricate.

## 5. License and dependency conflicts found

1. **RAIL-1.1 (rPPG-Toolbox) vs permissive MIT RSBVP.** RAIL-1.1 §3.2 forbids using the toolbox contribution for: surveillance/profiling of legally protected classes or identity attributes; insurance-claim decisions; diagnosis **without human oversight**; criminal-prediction uses; undisclosed synthetic media. RSBVP's pulse-only, educational, non-diagnostic scope is compatible, but any integration docs must (a) carry the RAIL-1.1 text, (b) flow the §3.2 restrictions into downstream agreements, (c) never present toolbox output as a diagnosis. Our adapter outputs aggregate research metrics only — acceptable.
2. **RAIL-1.1 restrictions are viral for distributed derivative works.** Since we do not copy toolbox code/weights and do not redistribute derivatives, RSBVP's MIT license is unaffected. If we ever redistributed a work incorporating the toolbox, it would have to carry RAIL-1.1 terms — hence the hard "no vendoring" rule.
3. **GPL-3.0 (pyVHR) vs MIT RSBVP and RAIL-1.1 toolbox.** Mixing GPL-3.0 sources with MIT code in one distributed artifact would impose GPL-3.0 on the whole; we keep pyVHR strictly as an external runtime dependency (separate env, subprocess boundary, no shared source). The RSBVP driver is MIT, imports only public pyVHR APIs at runtime. Aggregation vs. derivative-work analysis is flagged for legal review before any distribution that ships the driver next to pyVHR.
4. **TensorFlow 2.5 (pyVHR-CPU env)** is EOL with unpatched CVEs; acceptable only in an isolated research conda env, never in the main venv or CI.
5. **requirements.txt pins vs modern stack.** Toolbox pins (`numpy==1.22.0`, `scipy==1.5.2`, `opencv_python==4.5.2.54`, `h5py==2.10.0`, `pandas==1.1.5`) are incompatible with the main app's modern pins — another reason integration is subprocess-only, not `pip install -r` into the main venv.
6. **`mamba-ssm`/`causal-conv1d`** need CUDA toolkit + compiler at install time; failure must not block unsupervised benchmarking — install the toolbox without PhysMamba/RhythmFormer and use the five supported methods/models only.
7. **Frontend deps** (`@mediapipe/tasks-vision` Apache-2.0, React MIT, Vite MIT, TS Apache-2.0) — compatible; no action.
8. **RSBVP top-level LICENSE is MIT** — our additions preserve it. Attribution to upstream projects is recorded in the register; no third-party code headers were removed anywhere.
9. **Dataset terms are the hardest constraint.** UBFC-rPPG and COHFACE are **not redistributable** and must be obtained by each researcher under their own request. No dataset bytes are committed. Benchmark reports must pseudonymize participants.
10. **CMS50D/serial** (`gui/rppg_core/device.py`) — unchanged; no licensing issue; hardware validation still pending.

## 6. Deployment architecture review

- Vercel hosts only the static frontend + serverless-free deployment; camera capture and MediaPipe run in-browser; backend FastAPI is for local/dev use with hardware (serial CMS50D). **No external neural inference is added to Vercel or the browser bundle** — heavyweight Python/Torch stay in the optional research environment.
- The research backends live under `research/backends/` (Python, CLI-first) and reuse the existing `research/` convention (local paths only, `RSBVP_DATA_ROOT`-style env configuration — here `RSBVP_RPPG_TOOLBOX_PATH`, `RSBVP_PYVHR_PYTHON`, `RSBVP_PYVHR_PATH`, `RSBVP_MODEL_ROOT`).
- CI (GitHub Actions, ubuntu-latest, no GPU) runs: Python unit tests (new backend contract/schema/metrics/reference/benchmark tests — all offline), `compileall gui research`, frontend test/build/lint. **No dataset download, no checkpoint download, no toolbox install in CI.**
- `reports/validation/` convention is extended by `reports/research_backends/` for generated benchmark summaries (committed only when small and clearly labelled synthetic/aggregate).

## 7. Test and reproducibility posture after Sprint 5

New offline tests (no GPU, no datasets, no checkpoints): adapter contract tests for every backend; schema round-trip/validation; reference-method correctness on deterministic synthetic pulses (GREEN/ICA/CHROM/POS/PBV recover 70/72/95 BPM within tolerance); benchmark determinism (byte-identical records.json); rejection semantics (NaN gaps ⇒ windows rejected, never interpolated/filled); missing-checkpoint and unavailable-backend paths; license-register format validation; pinned-commit format checks. See `docs/RESEARCH_BACKENDS.md` §10.

## 8. Risks and honesty boundaries

- **No dataset evaluation performed yet.** All numeric outputs from the in-process backends on the shipped fixture are software verification, not physiological validation. `reports/research_backends/SYNTHETIC_BENCHMARK.{json,md}` is labelled accordingly.
- **Trace-domain PBV/ICA are approximations** of the camera-domain algorithms; absolute agreement with toolbox results is not claimed until run under identical UBFC-rPPG recordings with an authorized archive.
- **Toolbox aggregate-only output** limits per-window pairing across backends; per-window comparison is native-vs-reference (same windows, same estimator) while toolbox/pyVHR anchor absolute numbers at dataset level.
- **Preprocessing mismatch warning:** toolbox unsupervised methods consume Haar-cascade face crops (1.5× box), not RSBVP's ROI means — cross-backend deltas mix ROI definition, face detection, and algorithm differences; the fair-comparison protocol (docs/RESEARCH_BACKENDS.md §7) states this explicitly.

## 9. Recommended integration order (executed in this sprint)

1. Standardized benchmark adapter + schema + native/reference backends (in-process, offline). ✅ implemented
2. rPPG-Toolbox **unsupervised** adapter with pinned commit + explicit configs. ✅ implemented
3. **One neural baseline via toolbox `only_test`** (TS-CAN) with checkpoint contract; other four models wired to the same contract. ✅ implemented
4. pyVHR optional adapter (GPL isolation) + CPU feasibility assessment. ✅ implemented (not executed here — no authorized data; documented)
5. Fair-comparison protocol + license register + CI. ✅ implemented
