# RSBVP — Remote Screening of Blood Parameters and Vital Signs

RSBVP is an academic research prototype investigating two **independent** questions: camera-derived pulse signals (rPPG), and whether conjunctival image features may associate with laboratory-measured hemoglobin. It is not a medical device, diagnostic tool, or substitute for clinical measurement.

## Current status

- **Pulse research:** Existing Green and POS extraction, motion classification/corrections, FFT/peak estimation, experimental tachogram respiratory analysis, local webcam capture and optional CMS50D evaluation remain available. Defaults now use a 0.7–3.5 Hz (42–210 BPM) search passband. CHROM processing, per-ROI RGB retention with a conservative skin-color mask, timestamp-derived sampling-rate helper, and frame-gap accounting are included. The ROI mask is a heuristic, not MediaPipe landmark segmentation. An algorithm comparison CLI scores Green/POS/CHROM and ROI/multi-ROI variants from a supplied synchronized RGB-trace CSV; it does not create reference data. Python↔browser DSP parity now covers all 3 ROIs × 3 estimators (9 combos) on a shared synthetic fixture, and cross-ROI agreement gating plus candidate_bpm validation hardening are in place.
- **Anemia research:** No verified dataset or trained model is included. The image quality and RGB/HSV/Lab feature helpers, a standardized input-image contract and a researcher-reviewed conjunctival-ROI annotation format (`docs/ANEMIA_IMAGE_CONTRACT.md`, `research/anemia/contract.py`) are research foundations only; they do not locate conjunctiva or produce hemoglobin/anemia predictions. A composite image-QA aggregation layer (contract + image QA + mask) is implemented and software-tested, emitting machine-readable rejection reasons; it performs no Hb estimation or diagnosis. Status: **NOT AVAILABLE — NO VERIFIED LABELED DATASET**.
- **Validation:** No new reference recordings, clinical results, dataset performance, or hardware tests are claimed by this update. UBFC-rPPG and COHFACE remain absent; CI never requires datasets, GPU, webcams or CMS50D. CI runs the full Python suite (280 tests at this commit) plus 34 frontend tests and remains dataset/GPU/webcam-free.

The original research scripts, notebooks and archive remain in the repository. The original MIT license and attribution are preserved.

## Beginner setup (all platforms)

> **New to this? Do this and nothing else.** Copy-paste the one line for your
> operating system. The script installs everything, runs the tests, and unpacks
> the bundled dataset. It never downloads a dataset, never needs a webcam, GPU or
> internet login, and never touches your other files.

| Your system | One command | Where to type it |
|---|---|---|
| **Linux** | `bash setup.sh` | Terminal |
| **macOS** | `bash setup.sh` | Terminal (Terminal.app) |
| **Windows 11/10** | `setup.cmd` | Double-click the file, or type it in Command Prompt |
| Windows, PowerShell fan | `.\setup.ps1` | PowerShell, inside the repo folder |
| Windows, using Git Bash / WSL | `bash setup.sh` | Git Bash / WSL terminal |

What the script does, in order (each step prints `[ok]`, `[warn]` or `[fail]`):

1. **checks Python 3.12+** — if it is missing, it tells you exactly what to install;
2. **creates `.venv`** (a private Python folder inside the repo) and installs the
   packages from `requirements-dev.txt`;
3. **runs the Python tests** (280 tests, no camera or dataset needed);
4. **installs the web interface** (`gui/frontend`) and runs its 34 tests, build and lint;
5. **unpacks the bundled rPPG-10 dataset** into `data/rppg10/` and validates it;
6. **prints what to do next** (start the backend, start the interface, open the browser).

Useful variations:

```bash
bash setup.sh --no-dataset      # skip the dataset entirely
bash setup.sh --dataset-only    # only unpack + validate the dataset
bash setup.sh --no-frontend     # Python only (no JavaScript/TypeScript)
bash setup.sh --benchmark       # also re-run the research benchmark (~3 min)
bash setup.sh --recreate        # delete and rebuild .venv
bash setup.sh --help            # all options
```

### Step-by-step for a complete beginner

**1. Install the two prerequisites (once).**

- **Python 3.12 or newer** — <https://www.python.org/downloads/>.
  On Windows, **tick "Add python.exe to PATH"** during installation. On macOS you
  can also use `brew install python@3.12`. On Debian/Ubuntu:
  `sudo apt install python3.12 python3.12-venv`.
- **Node.js 20 LTS** — <https://nodejs.org/>. Needed only for the web interface;
  if you skip it, run the script with `--no-frontend`.

Check them (optional):

```bash
python3 --version     # Windows: python --version
node --version
```

**2. Get the code.** Either download the ZIP from GitHub and unzip it, or:

```bash
git clone https://github.com/Hemansh2633B/Rsbvp-Vitals-and-anemia.git
cd Rsbvp-Vitals-and-anemia
```

**3. Run the setup script** — the one line from the table above.

**4. If something goes wrong.** The script never stops silently. Read the
`[fail]` line and the two lines under it; they name the missing tool or the failing
command. The most common cases:

| Message | Fix |
|---|---|
| `Python was not found` / `Python 3.x is too old` | Install Python 3.12+; on Windows re-open the terminal after installing |
| `could not create .venv` (Linux) | `sudo apt install python3.12-venv` |
| `Node.js was not found` | Install Node.js LTS, **or** run `bash setup.sh --no-frontend` (the Python research tools still work) |
| `npm ci failed` | Check your internet connection, then re-run; it is safe to re-run |
| `[warn] validation reported items to review` | **Normal.** The provider spreadsheet is a known, recorded deviation, not an error |
| PowerShell: `running scripts is disabled` | Use `setup.cmd` instead, or once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |

**5. Start it (two terminals).**

```bash
# terminal 1 — backend
cd gui
../.venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

```bash
# terminal 2 — web interface
cd gui/frontend
npm run dev -- --host 0.0.0.0
```

Then open <http://localhost:5173>. On Windows use
`..\.venv\Scripts\python -m uvicorn ...` in terminal 1. The browser asks for camera
permission for the live view; nothing is uploaded.

**6. Where the results are.**

| What | Where |
|---|---|
| Research benchmark report (human-readable) | `reports/rppg10/rppg10_benchmark.md` |
| Full benchmark data (every window) | `reports/rppg10/rppg10_benchmark.json` |
| Dataset validation output | `reports/rppg10/rppg10_inventory.json` |
| The unpacked dataset | `data/rppg10/Dataset_rPPG-10/Subject_<n>/` |

### About the bundled dataset — a deliberate, documented exception

Every other dataset in this repository is **not** stored in Git: `data/README.md`
requires licensed data to live outside the repository (`RSBVP_DATA_ROOT`), and
`.gitignore` blocks `.avi`, `.npy`, `.h5` and friends.

**rPPG-10 is the single exception.** The 82 MB archive `data/rPPG-10.zip` is
committed on purpose so that a beginner can run a real, ECG-referenced evaluation
without hunting for data. The details that make this defensible:

| Question | Answer |
|---|---|
| Which dataset? | **rPPG-10** — Rodrigues & Garcia, *Data in Brief* 61 (2025) 111888 (doi:10.1016/j.dib.2025.111888); data doi:10.17632/bx8982xgwt.1 |
| Licence | **CC BY-NC-SA 4.0** — research / **non-commercial** use only, share-alike, attribution required |
| Is a dataset in Git allowed here? | Yes, **only** for this file, because the licence permits redistribution. No other dataset, recording, derived trace or participant data may be added. `.gitignore` still blocks `*.avi`, `*.npy`, `*.h5` etc., and `/data/rppg10/` (the unpacked copy) is ignored |
| May I redistribute it? | Only under the same CC BY-NC-SA 4.0 terms, with attribution and the citation above |
| May I use it commercially? | **No** — the licence forbids it |
| Which participants? | 26 of the provider's 27 subjects. `Subject_4` is **excluded by the provider** (its three ROI videos are 0-byte placeholders); the scripts pass `--exclude-subjects 4` and the exclusion, the citation and that evidence are recorded in every report |
| What does the benchmark show? | ECG-referenced pulse-rate agreement on a small, single-site dataset (26 young Portuguese students, Fitzpatrick I–IV, natural indoor light, 64×64 crops, manual sync ≤ ±500 ms). It is **research evidence, not a medical result** |

If you do not want the dataset, run `bash setup.sh --no-dataset` and everything
else (tests, web interface, and the research tooling on your own traces) still works.

See also [MMPD](docs/MMPD_VALIDATION.md) — smoke-tested only, still blocked on the
provider's signed data-release agreement — and [rPPG-10 validation details](docs/RPPG10_VALIDATION.md).

## Local development

Python package metadata is in `gui/pyproject.toml` (requires Python >=3.12).

```bash
cd gui
uv sync
uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

In another terminal:

```bash
cd gui/frontend
npm ci
npm run dev -- --host 0.0.0.0
```

The frontend proxies `/api` and `/ws` to the local FastAPI service. The live view now offers browser-local `getUserMedia()` + MediaPipe acquisition with in-browser ROI/rPPG analysis and timestamped RGB CSV export; it does not upload frames. The legacy local OpenCV camera and optional serial/CMS50D functionality remain available and use the **backend host's** hardware. Browser use requires camera permission and reachable MediaPipe model/WASM endpoints. Numeric live estimates are experimental and require browser/hardware validation.

Browser exports a timestamped RGB CSV plus JSON run metadata, and a per-window analysis JSON (effective sampling rate, per-estimator BPMs, quality score, availability status, rejection reason); schemas are documented in [export schema](docs/EXPORT_SCHEMA.md) and [MediaPipe asset notes](docs/MEDIAPIPE_ASSETS.md).

Run tests from the repository root after installing test dependencies:

```bash
python -m pytest -q
```

The Python suite now comprises 214 tests.

Build and lint the standalone UI:

```bash
cd gui/frontend
npm ci
npm run build
npm run lint
```

## rPPG algorithm comparison

The comparison tool requires real extracted traces; it does not simulate or provide reference measurements. CSV columns are documented in `research/rppg/compare_algorithms.py`.

```bash
python research/rppg/compare_algorithms.py /path/to/recording_rgb.csv --output comparison.json
```

Only supply a constant `reference_hr_bpm` column if it represents an actually synchronized reference for that analysis window. Missing references remain unscored. Different windows/participants should be evaluated separately and split by recording/participant before aggregate claims.

## Open-source research backends (Sprint 5)

RSBVP can now compare its shipped Green/POS/CHROM implementation against independently maintained research software through a standardized, provenance-tracked benchmark interface — without vendoring any external code or changing the browser application.

- **In-process (offline, MIT):** `rsbvp_native` (existing Python pipeline, read-only) and `rsbvp_reference` (independent implementations of GREEN, ICA, CHROM, POS and a trace-domain PBV approximation) via `research/backends/`.
- **Optional external research environments (never vendored):** `rppg_toolbox` (UbiComp Lab rPPG-Toolbox, RAIL-1.1, pinned commit) for unsupervised GREEN/ICA/CHROM/POS/LGI/PBV/OMIT and neural only_test DeepPhys/PhysNet/TS-CAN/EfficientPhys/PhysFormer; `pyvhr` (GPL-3.0, isolated subprocess) for independent cross-checks.
- **Standardized schema** (`rsbvp.benchmark-record.v1`): timestamps, missing values and original sampling rates preserved; reference measurements joined only for metrics; CSV + JSON outputs; per-window latency and availability accounting.

```bash
# software-verification example (synthetic fixture; no dataset required)
python research/backends/benchmark.py tests/fixtures/rppg_rgb_fixture.csv \
    --backends rsbvp_native,rsbvp_reference \
    --output-dir /tmp/rsbvp_benchmark_smoke
```

See [research backends guide](docs/RESEARCH_BACKENDS.md) for setup (toolbox/pyVHR/`RSBVP_MODEL_ROOT`), the fair-comparison protocol, and the pretrained-checkpoint policy; [open-source audit](docs/OPEN_SOURCE_RESEARCH_AUDIT.md); [license register](docs/OPEN_SOURCE_LICENSE_REGISTER.md). A committed synthetic benchmark summary lives in `reports/research_backends/`. No dataset evaluation is claimed: the UBFC-rPPG archive is not present and `reports/validation/validation.md` remains NOT RUN.

## Evidence before deployment (Sprint 6)

RSBVP stays honest about what is actually established. The UBFC-rPPG official page was verified (2026-11-23) but the archive is **not present**; [data readiness report](reports/research_validation/DATA_READINESS.md) documents provenance, terms and the steps required before any dataset run. [research validation](reports/research_validation/validation_report.md) separates software verification (deterministic synthetic fixtures, committed) from dataset evidence (none). [Reliability analysis](docs/RELIABILITY.md) covers failure modes (low light, motion, ROI loss, gaps, frame rate) with every claim marked SOFTWARE / HARDWARE-UNTESTED / NOT RUN. [Public-interest safeguards](docs/PUBLIC_INTEREST_SAFEGUARDS.md) state hard limits: pulse rate is not blood pressure, PRV is not ECG HRV, conjunctival appearance is not a hemoglobin measurement, and the anemia module is not a validated predictor of anything. The interface carries the same “what this cannot tell you” statements.

## Live signal quality (Sprint 8)

A conservative, explainable quality layer governs when pulse estimates are reported. It reports six explicitly separated concepts — `face_tracking`, `roi_extraction`, `temporal_acquisition`, `pulse_signal`, `algorithm_agreement`, `availability` (each `pass` / `fail` / `not_evaluated`) — never a blended score, and requires a union ROI-coverage gate (≥ 0.50 of window samples with at least one usable skin ROI) before `valid`. Explicit per-window statuses: `warming_up`, `valid`, `low_signal_quality`, `excessive_motion`, `face_not_detected`, `roi_lost`, `insufficient_frames`, `irregular_timestamps`, `reacquiring`, `processing_error`. Inadequate quality ⇒ the estimate is unavailable with a human-readable reason — never a plausible-looking number, never a silent zero/previous substitution. Motion-contaminated buffers are purged; camera interruption, face loss and hidden-tab states all clear stale estimates. The browser-local path is the clearly explained default; the legacy backend-host path (OpenCV webcam, optional CMS50D) is labeled separately and uses the backend host's hardware. The legacy Python live pipeline and the browser DSP both apply these gates; browser and Python use matching spectral diagnostics (documented Python↔TypeScript parity tests run on a shared synthetic fixture; no claim is made beyond that fixture). Low-light POS false-accepts (12–15 BPM with unverifiable correctness) are flagged as low-quality in synthetic fixtures rather than passed silently — see [reliability analysis](docs/RELIABILITY.md). Quality thresholds are documented research heuristics, not clinical cut-offs; a strong spectral peak is not proof of pulse origin.

## Anemia dataset inventory

No images are included. After verifying dataset terms and local permission, inventory a local dataset without downloading anything:

```bash
python research/anemia/audit_dataset.py /path/to/images --labels /path/to/labels.csv --output audit.csv
```

The optional labels CSV should contain `image_id`; patient and laboratory fields are copied only if present. Treat audit outputs as potentially sensitive. The audit reports file hashes for exact duplicates and does not claim patient-independent validation. See [the anemia model card](docs/ANEMIA_MODEL_CARD.md).

## Local rPPG dataset validation

The Sprint 3 intake tools read only local files. Configure `RSBVP_DATA_ROOT` or pass `--data-root`; see [`data/README.md`](data/README.md) for explicit manifest/reference formats. Do not commit research data. Dataset-specific archive mappings must be verified against the actual archive and official documentation before use. Current checked-in validation status is [NOT RUN — DATASET NOT AVAILABLE](reports/validation/validation.md); the supplied UBFC-rPPG Drive archive was not accessible to this workspace. Run `python research/rppg/validate_dataset.py <manifest.csv> --data-root <local-root>` only after provenance, license, synchronization, and schema have been verified. Browser hardware procedure (not yet performed): [`docs/MANUAL_CAMERA_TESTS.md`](docs/MANUAL_CAMERA_TESTS.md).

## Research safeguards and deployment

- Unreliable pulse estimates should remain unavailable; synthetic tests are software tests, not physiological validation.
- RR derived from pulse intervals is experimental. Pulse-rate variability (PRV) is not ECG-derived HRV.
- Heart rate is not blood pressure. Anemia screening is not diagnosis, and conjunctival pallor does not establish iron deficiency.
- The current upload UI sends video to the configured backend. Review [privacy notes](docs/PRIVACY.md) before use.
- Vercel can host the static frontend, not persistent webcam capture, serial ports, or a long-running WebSocket capture service. See [deployment requirements](docs/DEPLOYMENT.md).

## Documentation

- [Implementation status (authoritative capability matrix)](docs/IMPLEMENTATION_STATUS.md)
- [Anemia image contract and annotation format](docs/ANEMIA_IMAGE_CONTRACT.md)
- [Current status audit](docs/CURRENT_STATUS_AUDIT.md)
- [Initial repository audit](docs/INITIAL_REPOSITORY_AUDIT.md) (historical)
- [Open-source research audit](docs/OPEN_SOURCE_RESEARCH_AUDIT.md)
- [Research backends guide](docs/RESEARCH_BACKENDS.md)
- [Reliability and failure analysis](docs/RELIABILITY.md)
- [Public-interest safeguards](docs/PUBLIC_INTEREST_SAFEGUARDS.md)
- [Open-source license register](docs/OPEN_SOURCE_LICENSE_REGISTER.md)
- [Methodology and status](docs/RESEARCH_METHODOLOGY.md)
- [Anemia model card](docs/ANEMIA_MODEL_CARD.md)
- [References](docs/REFERENCES.md)
- [Privacy](docs/PRIVACY.md)
- [Deployment](docs/DEPLOYMENT.md)

## Citation and license

See `CITATION.cff` and `LICENSE`. Reuse and derivative works must preserve applicable attribution and MIT license notices.
