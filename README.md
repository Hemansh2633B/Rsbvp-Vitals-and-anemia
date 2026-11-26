# RSBVP — Remote Screening of Blood Parameters and Vital Signs

RSBVP is an academic research prototype investigating two **independent** questions: camera-derived pulse signals (rPPG), and whether conjunctival image features may associate with laboratory-measured hemoglobin. It is not a medical device, diagnostic tool, or substitute for clinical measurement.

## Current status

- **Pulse research:** Existing Green and POS extraction, motion classification/corrections, FFT/peak estimation, experimental tachogram respiratory analysis, local webcam capture and optional CMS50D evaluation remain available. Defaults now use a 0.7–3.5 Hz (42–210 BPM) search passband. CHROM processing, per-ROI RGB retention with a conservative skin-color mask, timestamp-derived sampling-rate helper, and frame-gap accounting are included. The ROI mask is a heuristic, not MediaPipe landmark segmentation. An algorithm comparison CLI scores Green/POS/CHROM and ROI/multi-ROI variants from a supplied synchronized RGB-trace CSV; it does not create reference data. Python↔browser DSP parity now covers all 3 ROIs × 3 estimators (9 combos) on a shared synthetic fixture, and cross-ROI agreement gating plus candidate_bpm validation hardening are in place.
- **Anemia research:** No verified dataset or trained model is included. The image quality and RGB/HSV/Lab feature helpers, a standardized input-image contract and a researcher-reviewed conjunctival-ROI annotation format (`docs/ANEMIA_IMAGE_CONTRACT.md`, `research/anemia/contract.py`) are research foundations only; they do not locate conjunctiva or produce hemoglobin/anemia predictions. A composite image-QA aggregation layer (contract + image QA + mask) is implemented and software-tested, emitting machine-readable rejection reasons; it performs no Hb estimation or diagnosis. Status: **NOT AVAILABLE — NO VERIFIED LABELED DATASET**.
- **Validation:** No new reference recordings, clinical results, dataset performance, or hardware tests are claimed by this update. UBFC-rPPG and COHFACE remain absent; CI never requires datasets, GPU, webcams or CMS50D. CI runs the full Python suite (280 tests at this commit) plus 34 frontend tests and remains dataset/GPU/webcam-free.

The original research scripts, notebooks and archive remain in the repository. The original MIT license and attribution are preserved.

## Deploy it (Linux, macOS, Windows)

> **Just want it running?** One command. It installs the Python packages, builds
> the web interface, starts the service on a single port, waits until it is
> healthy, and prints the URL. No webcam, GPU or dataset download is involved.

| Your system | Command | Where to run it |
|---|---|---|
| **Linux** | `./deploy.sh` | Terminal, in the repo folder |
| **macOS** | `./deploy.sh` | Terminal, in the repo folder |
| **Windows** (simplest) | `deploy.cmd` | Double-click the file, or type it in Command Prompt |
| Windows PowerShell | `.\deploy.ps1` | PowerShell, in the repo folder |
| Windows Git Bash / WSL | `./deploy.sh` | Git Bash / WSL terminal |

`deploy.sh` may need `chmod +x deploy.sh` once (or run `bash deploy.sh`).
If macOS or Linux says `bad interpreter: /usr/bin/env bash^M`, your checkout has
Windows line endings: the repository's `.gitattributes` prevents this for new
clones — for an existing clone run `git rm --cached -r . && git reset --hard`.

### Options (identical on every platform)

| Bash | Windows | Meaning |
|---|---|---|
| `--host 127.0.0.1` | `--host 127.0.0.1` / `-Host 127.0.0.1` | this machine only (the default `0.0.0.0` also allows your phone / LAN) |
| `--port 8080` | `--port 8080` / `-Port 8080` | preferred port (the next free one is used if busy) |
| `--open` | `--open` / `-Open` | open the browser when the service is ready |
| `--stop` | `--stop` / `-Stop` | stop the running service |
| `--foreground` | `--foreground` / `-Foreground` | keep it attached to the terminal (default: background) |
| `--skip-install` | `--skip-install` / `-SkipInstall` | skip `pip install` / `npm ci` |
| `--unpack-dataset` | `--unpack-dataset` / `-UnpackDataset` | only unpack the bundled rPPG-10 dataset, then exit |
| `--status` | `--status` / `-Status` | show what is installed/cached and exit (changes nothing) |
| `--offline` | `--offline` / `-Offline` | redeploy with no network, from the local cache |
| `--recreate` | `--recreate` / `-Recreate` | delete and rebuild `.venv` (repair only) |
| `--rebuild` | `--rebuild` / `-Rebuild` | rebuild the interface even if it looks current |
| `--tls` | `--tls` / `-Tls` | serve over HTTPS with a local certificate (needed for the camera on other devices) |
| `--help` | `--help` | show the usage text |

### Redeploying is cheap (and works offline)

**The script never recreates your environment.** A second deploy reuses
everything it built the first time: `.venv`, the installed Python packages,
`node_modules` and the built interface. In this repository a first deploy takes
about a minute; a redeploy takes **2-3 seconds** and downloads nothing.

| What | Reinstalled when |
|---|---|
| `.venv` | only if it is missing or broken (never on a normal redeploy) |
| Python packages | only if `requirements.txt` changed, or a package is missing |
| `node_modules` | only if `package-lock.json` changed (npm installs are destructive, so they are avoided) |
| `gui/frontend/dist` | only if the frontend sources are newer than the build |

The decision lives in **`deploy_env.py`**, which all three scripts call, so
Windows and Linux/macOS behave identically.

- `./deploy.sh --status` prints exactly what is installed, what is stale and
  where the cache is - it changes nothing.
- `./deploy.sh --offline` redeploys with **no network at all**, from
  `.cache/deploy/` (pip wheels + npm cache). Useful on a lab machine or after
  the first install; `RSBVP_OFFLINE=1` does the same for any script.
- If an install fails, **nothing is deleted**: the existing `.venv`, packages and
  `node_modules` are kept, and re-running resumes from where it stopped.
- `--recreate` (and only that) rebuilds `.venv` from scratch; `--rebuild` forces
  a fresh frontend build. Both are repair tools, not part of a normal redeploy.
- The cache in `.cache/deploy/` is ignored by Git and can be deleted at any time;
  the next deploy will simply populate it again.

### The camera is the one on the device you opened the page with

The live view measures **the camera of the device showing the page** - your
phone measures your phone's camera, a second laptop measures its own. The server
never opens its own webcam for this pathway. Frames are captured in the browser
(`getUserMedia`), downscaled to 640 px wide JPEG, streamed to the server over the
same WebSocket, and processed there by the same rPPG pipeline - so the numbers
are directly comparable to a local run. Nothing is stored unless you press
record, and then only in that run's folder (`gui/runs/<run_id>/`, with a
`live_source.txt` noting which device supplied the frames).

**One browser rule to know about:** camera access requires a *secure context*.

| How you open it | Camera access |
|---|---|
| `http://localhost:8000` on the machine running the server | allowed (localhost counts as secure) |
| `http://<lan-ip>:8000` on a phone or another computer | **blocked by the browser** - not by this app |
| `https://<lan-ip>:8443` on a phone or another computer | allowed (accept the self-signed warning once) |

So to use a phone's camera, deploy with HTTPS:

```bash
./deploy.sh --tls                 # https://localhost:8000 and https://<lan-ip>:8000
./deploy.sh --tls --port 8443     # pick the port explicitly
deploy.cmd --tls                  # Windows
.\deploy.ps1 -Tls                 # Windows PowerShell
```

`--tls` creates a self-signed certificate once, in `.run/tls/` (private key mode
`600`, ignored by Git), valid for `localhost`, `127.0.0.1` and this machine's
current LAN addresses. On each device you accept the browser warning once
("Advanced" -> "Proceed"). It is fine on a trusted lab network; for anything
exposed beyond it, use a real certificate (reverse proxy / Let's Encrypt), which
this project does not set up.

If a page is opened over plain HTTP from another device, the interface says so
plainly instead of silently measuring the wrong camera. Serving HTTPS also means
the WebSocket runs over `wss://`.

### What "deployed" means here

The backend and the built interface are served **from the same process on one
port** (`http://localhost:8000`), so there is no second server to start:

- `/` serves the built web interface (`gui/frontend/dist`), listening on
  `0.0.0.0:8000` so the same URL also works from your phone on the same Wi-Fi;
- `/api/...` and `/ws/live` are the backend;
- the launcher polls `/api/health` and only reports success when it answers — if
  the server fails to start, the last 20 log lines are printed;
- the service runs in the background with a PID file, and `--stop` shuts it down;
- logs: `.run/server.log`, PID: `.run/rsbvp.pid`.

This is a **local research deployment**: no authentication, no TLS, no
multi-user isolation. Keep it on a trusted network. For anything internet-facing
you need a reverse proxy with TLS and access control, which this project does
not provide.

To also run it on a server/container in the foreground:
`./deploy.sh --host 0.0.0.0 --foreground --skip-install`.

### Beginner walkthrough

**1. Install the two prerequisites (once).**

- **Python 3.10 or newer** (3.12 recommended, which is what CI uses) —
  <https://www.python.org/downloads/>. On Windows **tick "Add python.exe to
  PATH"** during setup. macOS: `brew install python@3.12`.
  Debian/Ubuntu: `sudo apt install python3.12 python3.12-venv`.
  The script creates a private `.venv` next to the code the first time, so your
  system Python is never modified.
- **Node.js 20 LTS** — <https://nodejs.org/>. Needed to *build* the interface;
  once built, only Python is needed to serve it.

**2. Get the code.**

```bash
git clone https://github.com/Hemansh2633B/Rsbvp-Vitals-and-anemia.git
cd Rsbvp-Vitals-and-anemia
```

(Or download the ZIP from GitHub and unzip it.)

**3. Deploy.**

```bash
./deploy.sh
```

On Windows: double-click `deploy.cmd`.

**4. Open the URL it prints** — normally <http://localhost:8000>. The browser
asks for camera permission for the live view; nothing is uploaded.

**5. Stop it** with `./deploy.sh --stop` (or `deploy.cmd --stop`).

**If something goes wrong**, every step prints `[ok]` or `[fail]` followed by the
exact command to run. The common cases:

| Message | Fix |
|---|---|
| `Python 3.10+ not found` | Install Python (see step 1); on Windows reopen the terminal afterwards |
| `npm (Node.js) not found` | Install Node.js LTS — it is required to build the interface |
| `pip install failed` | Check your internet connection, then re-run — already-installed packages are kept, so it resumes |
| `offline mode, but the local wheel cache is empty` | The first deploy needs a network connection; afterwards `--offline` works |
| `the frontend build failed` | Run `cd gui/frontend && npm run build` to see the full error |
| An older `.venv` behaves oddly | `./deploy.sh --recreate` rebuilds it (the only case where packages are re-downloaded) |
| `port 8000 is busy` | Nothing to do — the next free port is chosen automatically and printed |
| PowerShell: `running scripts is disabled` | Use `deploy.cmd`, or once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `bad interpreter ... ^M` (macOS/Linux) | Line endings — see the note above about `.gitattributes` |
| Phone shows "Secure context required" / camera never opens | You opened `http://<lan-ip>` — redeploy with `--tls` and accept the certificate warning on the phone |
| Camera permission prompt never appears | Check the browser's site permissions; on iOS Safari use HTTPS and a current browser |

### Development mode (hot reload)

If you are changing the code, run the two dev servers instead; the frontend then
proxies `/api` and `/ws` to the backend:

```bash
# terminal 1 - backend
cd gui
../.venv/bin/python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

```bash
# terminal 2 - interface with hot reload
cd gui/frontend
npm run dev -- --host 0.0.0.0
```

Then open <http://localhost:5173>. Windows: `..\.venv\Scripts\python -m uvicorn ...`.

### Tests (optional - CI runs these, deployment does not)

```bash
.venv/bin/python -m pytest -q                 # 295 Python tests, dataset-free
cd gui/frontend && npm test && npm run build && npm run lint
```

### Where the research results are

| What | Where |
|---|---|
| Research benchmark report | `reports/rppg10/rppg10_benchmark.md` |
| Full benchmark data (every window) | `reports/rppg10/rppg10_benchmark.json` |
| Dataset validation output | `reports/rppg10/rppg10_inventory.json` |

The bundled dataset is unpacked with `bash deploy.sh --unpack-dataset` (ask for it
explicitly; deployment never touches data).

### About the bundled dataset - a deliberate, documented exception

Every other dataset in this repository is **not** stored in Git: `data/README.md`
requires licensed data to live outside the repository (`RSBVP_DATA_ROOT`), and
`.gitignore` blocks `.avi`, `.npy`, `.h5` and friends.

**rPPG-10 is the single exception.** The 82 MB archive `data/rPPG-10.zip` is
committed on purpose so that a beginner can run a real, ECG-referenced evaluation
without hunting for data. The details that make this defensible:

| Question | Answer |
|---|---|
| Which dataset? | **rPPG-10** - Rodrigues & Garcia, *Data in Brief* 61 (2025) 111888 (doi:10.1016/j.dib.2025.111888); data doi:10.17632/bx8982xgwt.1 |
| Licence | **CC BY-NC-SA 4.0** - research / **non-commercial** use only, share-alike, attribution required |
| Is a dataset in Git allowed here? | Yes, **only** for this file, because the licence permits redistribution. No other dataset, recording, derived trace or participant data may be added. `.gitignore` still blocks `*.avi`, `*.npy`, `*.h5` etc., and `/data/rppg10/` (the unpacked copy) is ignored |
| May I redistribute it? | Only under the same CC BY-NC-SA 4.0 terms, with attribution and the citation above |
| May I use it commercially? | **No** - the licence forbids it |
| Which participants? | 26 of the provider's 27 subjects. `Subject_4` is **excluded by the provider** (its three ROI videos are 0-byte placeholders); tooling passes `--exclude-subjects 4` and the exclusion, citation and evidence are recorded in every report |
| What does the benchmark show? | ECG-referenced pulse-rate agreement on a small, single-site dataset (26 young Portuguese students, Fitzpatrick I-IV, natural indoor light, 64x64 crops, manual sync <= +/-500 ms). **Research evidence, not a medical result** |

### Camera acquisition integrity

The live view reports **what the camera actually delivered**, measured from the
capture timestamps rather than the requested frame rate: effective sampling rate,
largest frame gap, duplicate-frame percentage and timing regularity. If a window
has a timing defect (duplicated frames, a stall, a dropped-frame gap, or a rate too
low to analyse) the measurement is shown as **unavailable** with a reason — never
as a plausible-looking BPM. A camera that drops out is reopened with exponential
backoff (1 s → 30 s, 4 attempts) instead of freezing on a stale number.

The browser and Python implementations are checked against a shared fixture, so the
live pathway and the research pathway cannot disagree about whether a capture was
regular. See [docs/RELIABILITY.md](docs/RELIABILITY.md) for the thresholds and
[docs/SPRINT_12_EVIDENCE.md](docs/SPRINT_12_EVIDENCE.md) for exactly which claims
have which kind of evidence.

### External research software

rPPG-Toolbox, pyVHR, ConjunctivaHb, ViT-Anemia-Detection and MediaPipe are pinned
as **git submodules** under `tools/` (URL + commit only; no upstream code is
vendored or licensed in here). See [docs/EXTERNAL_SUBMODULES.md](docs/EXTERNAL_SUBMODULES.md).

See also [MMPD](docs/MMPD_VALIDATION.md) - smoke-tested only, still blocked on the
provider's signed data-release agreement - and [rPPG-10 validation details](docs/RPPG10_VALIDATION.md).

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
