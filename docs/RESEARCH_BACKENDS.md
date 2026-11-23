# RSBVP Research Backends — setup, schema and fair comparison

> RSBVP is an **educational research prototype**. Nothing in this document or in the
> code under `research/backends/` is a medical device, a diagnosis, or an anemia /
> blood-pressure / cardiac-output estimate. rPPG pulse estimates from any backend are
> experimental numerical outputs requiring research validation before any interpretation.
> Never record classmates or patients without appropriate adult and institutional
> supervision, informed consent and data protection. Use authorized public research
> data and deterministic software fixtures only.

## 1. What this is

Sprint 5 adds a **standardized benchmark adapter** so RSBVP can compare its existing
implementation against independently maintained research software — without touching
the main application, the browser bundle, privacy posture, or licensing.

```
                ┌────────────────────────── RSBVP (this repo) ───────────────────────────┐
 browser  ────► │ frontend (MediaPipe, Green/POS/CHROM in TS)   unchanged                │
 trace CSV ───► │ research/backends/  ── standardized benchmark CLI (this document)       │
                │   ├─ rsbvp_native      in-process: existing gui/rppg_core (MIT)         │
                │   ├─ rsbvp_reference   in-process: independent implementations (MIT)    │
                │   ├─ rppg_toolbox      subprocess → external rPPG-Toolbox (RAIL-1.1)    │
                │   ├─ pyvhr             subprocess → external pyVHR (GPL-3.0)            │
                │   └─ neural_*          checkpoint contract + delegated only_test (RAIL) │
                └──────────────────────────────────────────────────────────────────────────┘
```

**Hard rules (enforced in code and tests):**

1. No external project's source is vendored into this repository. Adapters generate
   configs, invoke subprocesses, parse logs, and record provenance.
2. Reference measurements never enter a backend; they are joined afterwards for metrics.
3. Missing values stay missing (`null` / empty cell). Nothing is interpolated across
   long gaps, zero-filled, or unit-converted silently.
4. Checkpoints live only under `RSBVP_MODEL_ROOT` (sha256-verified, `git`-ignored).
5. CI runs offline: no GPU, no datasets, no checkpoints, no toolbox installation.

## 2. Which capability lives where

| Capability | Browser only | Local Python research env | Optional GPU env (toolbox/pyVHR) |
|---|---|---|---|
| MediaPipe face tracking, ROI RGB sampling | ✅ | — | — |
| Timestamped RGB CSV export + run metadata | ✅ | ✅ (analysis) | — |
| Green / POS / CHROM (TypeScript, in-browser) | ✅ | — | — |
| Green / POS / CHROM (Python, `gui/rppg_core`) | — | ✅ | ✅ |
| Independent reference: GREEN / ICA / CHROM / POS / PBV* | — | ✅ | ✅ |
| LGI / OMIT (video-domain) | — | ❌ (report *unsupported* on traces) | ✅ via toolbox/pyVHR |
| Neural DeepPhys/PhysNet/TS-CAN/EfficientPhys/PhysFormer | ❌ (never bundled) | ❌ | ✅ toolbox `only_test` (+ local checkpoint) |
| CMS50D serial evaluation | — (backend host hardware) | ✅ | ✅ |
| UBFC-rPPG / COHFACE evaluation | ❌ | ✅ if authorized data present | ✅ |

*PBV in the in-process reference backend is a documented trace-domain approximation
(signature-gated chrominance); the authoritative PBV runs in the external backends.

## 3. The standardized record schema

Every backend emits `rsbvp.benchmark-record.v1` records
(`research/backends/schema.py`). One record = one algorithm × one window × one ROI.

| Field | Meaning | Notes |
|---|---|---|
| `recording_id` | recording identifier (pseudonymous) | required |
| `participant_id` | pseudonymous participant grouping | optional; never raw identifiers |
| `timestamp_s` | window **start**, seconds, input timebase | finite; strictly increasing inputs enforced upstream |
| `window_end_s` | last sample time of the window | ≥ `timestamp_s` |
| `algorithm` | e.g. `GREEN`, `POS`, `CHROM`, `ICA`, `PBV`, `Tscan` | upper-case for classical, registry name for neural |
| `roi` | `forehead`, `left_cheek`, `right_cheek`, `cheeks`, `multi_roi`, `whole_video` | `whole_video` only for aggregate toolbox/pyVHR records |
| `pulse_signal` | waveform samples in `[timestamp_s, window_end_s]` | `null` when unavailable; NaNs preserved as JSON `null`; never zero-filled |
| `estimated_hr_bpm` | window HR estimate | `null` when unavailable; (0, 400) BPM when present |
| `signal_quality` | `ok` · `low_quality:…` · `rejected:<reason>` · `unavailable:<reason>` · `aggregate` | machine-parseable token |
| `sampling_rate_hz` | **original** sampling rate of the samples | never altered; missing ⇒ `null` |
| `backend` | backend name (`rsbvp_native`, `rppg_toolbox`, …) | required |
| `backend_version` | version incl. pinned commit (`toolbox@b7500b848f84+adapter1.0.0`) | required |
| `model_checkpoint` | checkpoint path/name | `null` for unsupervised methods; sha256 lives in `backend_report`/summary |
| `configuration_hash` | sha256 of the canonical JSON of the effective configuration | stable across runs; see below |
| `backend_output_type` | `window` or `aggregate` | aggregate = dataset-level metrics, excluded from window pairing |
| `backend_report` | optional structured passthrough (parsed log lines, driver payloads) | JSON only, not CSV |

**CSV exports** (`records.csv`, `waveforms.csv`) are convenience views: waveforms are
exported per sample (`sample_index`, `timestamp_s = start + index/fs`), missing samples
are empty cells, and `records.csv` carries `pulse_signal_length` instead of the samples.
The canonical, lossless export is `records.json`. `configuration_hash` covers
`{backend, backend_version, algorithm, roi, window_seconds, step_seconds, passband_hz,
estimator, hr_selection, missing_data}` — identical configs hash identically.

**Timestamps and gaps are never invented across.** In-process backends reject any
window containing non-finite samples (`rejected:nonfinite_samples`); any window with a
gap longer than 0.25 s is rejected (`rejected:excessive_gaps`); windows with only
short-range irregularity are linearly interpolated onto a uniform grid at the measured
rate (the same convention as `gui/rppg_core/research.py::resample_rgb_traces`); tail
windows shorter than the full window are dropped, not padded. Configuration hashes
record the effective `missing_data` policy.

Two Sprint 6 additions extend the reliability story without touching dataset claims:

- `research/rppg/ubfcrppg_probe.py` — local-only UBFC-rPPG readiness probe; reports
  archive structure/gaps without inferring units, rates or clock offsets; exits 2 when
  no data root is configured; writes `reports/research_validation/data_readiness.{json,md}`.
- `research/backends/reliability.py` — deterministic synthetic degradation suite
  (low light, unscaled read noise, motion transients, 20% frame drops, 15/10 Hz,
  ROI dropout); outputs `reports/research_validation/synthetic/` (software verification
  only — never validation).

## 4. Setup

### 4.1 In-process backends (nothing extra)

```bash
# repo root; uses the same deps as CI
python -m pip install pytest numpy scipy pandas matplotlib opencv-python-headless
python -m pytest -q
```

`rsbvp_native` reuses `gui/rppg_core` (read-only). `rsbvp_reference` is self-contained.

### 4.2 rPPG-Toolbox (optional, external, RAIL-1.1)

Pin: **commit `b7500b848f84ad7f86e277b4612563b69f4f88f9`** (2025-09-15). Do not use `main` HEAD.

```bash
git clone https://github.com/ubicomplab/rPPG-Toolbox.git
cd rPPG-Toolbox && git checkout b7500b848f84ad7f86e277b4612563b69f4f88f9
bash setup.sh conda          # python 3.8, torch 2.1.2+cu121, requirements.txt (mamba-ssm needs a compiler)
conda activate rppg-toolbox
export RSBVP_RPPG_TOOLBOX_PATH=/absolute/path/to/rPPG-Toolbox
export RSBVP_RPPG_TOOLBOX_PYTHON=/absolute/path/to/conda/envs/rppg-toolbox/bin/python
```

- Unsupervised run (writes a config into your scratch dir, then calls `main.py`):

```python
from research.backends.rppg_toolbox import RppgToolboxBackend
backend = RppgToolboxBackend()
print(backend.available())   # ('usable?, reason')
result = backend.run_unsupervised_dataset(
    "/data/UBFC-rPPG/RawData", cached_path="/data/cache/rppg_toolbox",
    dataset="UBFC-rPPG", methods=["GREEN","ICA","CHROM","POS","LGI","PBV","OMIT"],
    do_preprocess=False,     # True on the very first run only
)
for record in result.records:
    print(record.algorithm, record.signal_quality, record.backend_report["parsed_metrics"])
```

- The toolbox consumes **toolbox-formatted video datasets** (UBFC-rPPG: `vid.avi` + `ground_truth.txt` per subject), **not** RSBVP RGB traces. The adapter refuses trace input by design.
- **Output limitation (important):** in `unsupervised_method` mode the toolbox prints aggregate metrics and saves BA plots; it does not emit per-window predictions. Adapter records are therefore `backend_output_type="aggregate"` with the parsed lines preserved in `backend_report`. They anchor absolute numbers; they do not participate in per-window pairing statistics.
- If your checkout HEAD differs from the pin, `available()` refuses to run. Tarball checkouts without `.git` are allowed but recorded as `unverified` in `backend_version` notes.
- Manual reproduction without the adapter: `python main.py --config_file <your copy of> configs/infer_configs/UBFC-rPPG_UNSUPERVISED.yaml` (see `research/backends/configs/`).

### 4.3 pyVHR (optional, external, GPL-3.0 — keep isolated)

Pin: **master `a6270f04a97f05a13d145dd0a5e8c8df48d8bd62`** (v2.0 line, 2024-11-20);
CPU-only line **`pyVHR_CPU` branch `e39ae5fa30c84c77300d43da5e3b8037fc852a9e`** (pyvhr-cpu 1.0.2, 2022-04-28).

```bash
conda create -n pyvhr python=3.9 -y && conda activate pyvhr
pip install pyvhr            # GPU build; or: pip install pyvhr-cpu  (legacy 1.0.2, CPU)
export RSBVP_PYVHR_PYTHON=/absolute/path/to/conda/envs/pyvhr/bin/python
export RSBVP_PYVHR_PATH=/absolute/path/to/pyvhr/checkout   # optional, for provenance
```

**CPU-only verdict:** feasible for the nine classical methods on small UBFC-style
corpora; **not supported by upstream for the modern v2.0 dependency set without CUDA
(cu113)**. The maintained CPU path (`pyvhr-cpu` 1.0.2, python 3.9.7, torch 1.10.0,
numba 0.53.1, mediapipe 0.8.8.1, **TensorFlow 2.5.0**) is a legacy stack with known EOL
dependencies; run it only inside a dedicated conda env, never in the main venv or CI.
MTTS-CAN on CPU is impractical for 28-video UBFC sweeps on weak hardware; use the GPU
build for neural comparisons. If the environment cannot be created on your machine, the
adapter reports *unavailable* — the primary application is unaffected.

```python
from research.backends.pyvhr import PyVHRBackend
backend = PyVHRBackend()
print(backend.available())
result = backend.run_on_videos(
    [("subject01", "/data/UBFC-rPPG/subject01/vid.avi")],
    methods=["Green", "POS", "CHROM", "ICA"], winsize_s=6.0, roi_approach="patches", cuda=False,
)
```

pyVHR performs its own face detection/ROIs; windows follow pyVHR's `timesES` convention —
consult your pyVHR release docs before aligning windows with other backends.

### 4.4 Neural checkpoints (`RSBVP_MODEL_ROOT`) — contract, not code

```bash
export RSBVP_MODEL_ROOT=/absolute/path/to/model_root
# layout mirrors the toolbox final_model_release/ directory, e.g.:
#   $RSBVP_MODEL_ROOT/PURE_TSCAN.pth
#   $RSBVP_MODEL_ROOT/PURE_PhysFormer_DiffNormalized.pth
```

The adapter (`research/backends/neural.py`) sha256-verifies the file and delegates
inference to the toolbox `only_test` pipeline (Haar-cascade crop 1.5×, per-model resize,
DiffNormalized labels, FFT HR evaluation). **No weights are downloaded, mirrored or
committed by RSBVP.** Checkpoints are released inside the toolbox repository under
**RAIL-1.1**; a separate weight license does not exist. If no checkpoint is configured,
or the toolbox is not installed, inference is reported **unavailable** — never
approximated. The official PhysFormer VIPL weights (Google Drive) were **rejected**: no
stated weight license. Per-model input geometry and training provenance: see
`docs/OPEN_SOURCE_LICENSE_REGISTER.md` §E and `research/backends/neural.py::MODEL_REGISTRY`.

Recommended first (and cheapest) neural baseline: **TS-CAN (`neural_tscan`)** on
PURE→UBFC-rPPG per the toolbox's own published example (§4.2). PhysNet is the fallback.

## 5. Running the benchmark

```bash
# in-process backends on the shipped synthetic fixture (software verification)
python research/backends/benchmark.py tests/fixtures/rppg_rgb_fixture.csv \
    --backends rsbvp_native,rsbvp_reference \
    --output-dir reports/research_backends/smoke

# multiple recordings with pseudonymous participant ids
python research/backends/benchmark.py --manifest manifest.csv \
    --backends rsbvp_native,rsbvp_reference --output-dir out/
# manifest.csv columns: recording_id,csv_path[,participant_id]

# authorized reference windows (never passed to backends)
python research/backends/benchmark.py tests/fixtures/rppg_rgb_fixture.csv \
    --backends rsbvp_native --reference-windows reference_windows.csv \
    --reference-source "UBFC-rPPG ground_truth.txt (authorized local archive, Bobbia 2017)" \
    --output-dir out/
# reference_windows.csv columns: recording_id,window_start_s,reference_hr_bpm
```

Outputs: `records.json` (canonical), `records.csv`, `waveforms.csv`, `summary.json`,
`summary.md`. Exit codes: `0` ok · `2` input error · `3` no backend could run.

A **committed synthetic example** lives in `reports/research_backends/` — it is labelled
software verification, not validation. No dataset-level comparison report is committed
because no authorized dataset is present in this workspace; the protocol below is what to
run when one is.

## 6. Fair comparison protocol

1. **Same recordings, same windows.** All in-process backends consume identical
   timestamp-regularized windows (default 12 s window / 6 s step, 0.7–3.5 Hz passband,
   hann-periodogram HR estimator). External backends consume identical *recordings*
   (video) under each tool's own published preprocessing — noted as a confound.
2. **Same reference, separate from predictions.** References (PPG/BVP from the dataset)
   are loaded only by the benchmark/metrics layer. Backends never receive them.
3. **Participant-level grouping.** Report per-recording metrics, then per-participant
   metrics, then a deterministic participant bootstrap CI (`research/backends/metrics.py`,
   seed `20261123`, 1000 resamples). **Pooled window metrics are descriptive only** —
   overlapping windows are correlated and are not independent participants.
4. **No leakage, no test-set tuning.** Subject-disjoint splits (the toolbox UBFC configs
   split BEGIN/END by subject; PURE→UBFC-rPPG is a clean cross-dataset protocol). Do not
   adjust thresholds, windows or passbands on the evaluation subjects; any such change
   requires a fresh, untouched test set.
5. **Metrics:** HR MAE, RMSE, signed bias, Bland–Altman limits of agreement (1.96·SD),
   MAPE, Pearson r (omitted for zero-variance series), within-±3/5 BPM fractions, plus
   **estimate availability**, **rejected/unavailable window counts and reasons**,
   per-window **processing latency**, and **peak RSS** (Linux). Every method gets the
   same window grid; different grids are a different experiment.
6. **No ranking across different test sets.** Numbers from non-identical recordings,
   passbands or window lengths must not be presented as a method ranking.
7. **Reporting.** Distinguish always: software tests → synthetic experiments →
   public-dataset evaluation → pretrained-model evaluation → hardware (CMS50D) tests.
8. **License honesty.** Only methods you actually ran may be reported; external-tool
   numbers cite tool and version; RAIL-1.1 §3.2 applies to any published artifact.

## 7. Pretrained model policy

* Do not assume weights are open because code is public. (PhysFormer official VIPL
  weights: **not used** — no weight license stated.)
* Do not download checkpoints from unverified mirrors. Toolbox `final_model_release/*.pth`
  are first-party artifacts of the pinned toolbox commit — still treated as RAIL-1.1
  licensed, never redistributed by RSBVP.
* Never commit `*.pth` (blocked by `.gitignore`). Set `RSBVP_MODEL_ROOT`; the adapter
  sha256-verifies at load time and records the digest in the aggregate record.
* If a legally usable checkpoint is absent: the adapter reports **inference unavailable**
  (default in CI/this workspace) — never a substitute.
* Published training/eval protocol per checkpoint: toolbox README + `neural.py` entries
  (all five verified against toolbox configs on 2026-11-23).
* Hardware: toolbox pins CUDA 12.1 builds of torch 2.1.2; CPU inference unverified
  upstream; PhysFormer 128×128/160-frame chunks strongly prefer a discrete GPU.

## 8. pyVHR GPL-3.0 isolation rules

* pyVHR never appears in `pyproject.toml`, `requirements*.txt`, `uv.lock`, `package.json`,
  Docker/Vercel artifacts, or CI. It is installed by the researcher into a separate conda
  env; RSBVP talks to it only through the `RSBVP_PYVHR_PYTHON` subprocess boundary.
* Outputs (BVP traces, BPM series, stats) are data, not derivative code; they may be
  stored in reports with citations.
* The RSBVP driver file is MIT-licensed first-party code; it is not a copy of any pyVHR
  source file.
* No viral obligations flow into the MIT application provided distribution rules are kept;
  see register §F.2 and §G item 2 before any packaged release.

## 9. Preserving the browser application

The browser implementation is untouched: MediaPipe Face Landmarker via
`@mediapipe/tasks-vision` (Apache-2.0), timestamped `getUserMedia()` RGB acquisition,
in-browser Green/POS/CHROM, quality-state reporting, timestamped CSV export — all still
in `gui/frontend/src/rppg/`. No Python, NumPy, SciPy, torch or toolbox code enters the
bundle. Browser capabilities are not silently extended by the research backend; they are
documented as a separate tier (§2). The legacy FastAPI backend and its CMS50D/serial path
are unchanged and remain hardware-host-dependent.

## 10. Tests and reproducibility

| Test file | Covers |
|---|---|
| `tests/test_backends_schema.py` | record validation, JSON/CSV round-trips, missing-value preservation, no NaN leakage, hash format |
| `tests/test_backends_reference.py` | independent implementations recover 66–95 BPM on synthetic traces; rejection semantics; ICA determinism; LGI/OMIT explicitly unsupported |
| `tests/test_backends_contract.py` | registry contract, availability gating, pinned SHAs, license IDs per backend, missing checkpoint paths, toolbox aggregate parsing |
| `tests/test_backends_benchmark.py` | end-to-end CLI: identical windows across backends, reference join, participant grouping + bootstrap, rejection on NaN gaps, byte-identical determinism |
| `tests/test_backends_metrics.py` | MAE/RMSE/bias/LoA/Pearson/MAPE on known inputs; participant bootstrap determinism |
| `tests/test_license_register.py` | register completeness (tools, pins, SPDX ids, isolation rules) |
| `tests/test_rppg_*.py`, `tests/test_roi_extraction.py`, … | pre-existing suite (unchanged behavior) |

All of the above run with `python -m pytest -q` and require no network, GPU, datasets or
checkpoints. `python -m compileall -q gui research` and the frontend suite
(`npm run test && npm run build && npm run lint`) run in CI too.

**Not reproducible here:** anything requiring the authorized UBFC-rPPG archive (absent),
a CMS50D device (absent), or a GPU (absent). `reports/validation/validation.md` and the
comparison report remain `NOT RUN` until those inputs are lawfully provided. CI passing
is not physiological evidence.

## 11. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `rsbvp_toolbox` → "RSBVP_RPPG_TOOLBOX_PATH is not set" | expected; create the isolated toolbox env, export the var; see §4.2 |
| "toolbox checkout is at X, expected pinned commit …" | `git checkout b7500b8…` — pin mismatch is refused on purpose |
| `"no metric lines could be parsed"` warning | toolbox ran but its output format drifted; inspect `runs/**/toolbox.log`, update `rppg_toolbox.parse_toolbox_log` with a test |
| per-window records expected but only `aggregate` records produced | upstream emits aggregate only; per-window comparison uses in-process backends |
| `neural_tscan` → "RSBVP_MODEL_ROOT is not set" | point it at a local checkpoint root; do not commit weights |
| `neural_tscan` → "checkpoint present but rPPG-Toolbox is not usable" | inference is delegated to the toolbox; install it (§4.2) or accept *unavailable* |
| `pyvhr` → "pyVHR is not importable" | create the isolated env, set `RSBVP_PYVHR_PYTHON`; note GPL-3.0 isolation (§8) |
| `pytest` finds duplicate module `research` | run from repo root; conftest puts `gui/` and repo root on `sys.path` |

## 12. Capability matrix vs the tasking

| Required capability | Location |
|---|---|
| Browser only | §2, `gui/frontend/src/rppg/` |
| Local Python research environment | §4.1 |
| Optional GPU environment | §4.2–§4.4 (toolbox/pyVHR; CUDA 12.1 stack) |
| Comparison report | `reports/research_backends/` (synthetic only; dataset report pending authorized UBFC-rPPG) |
