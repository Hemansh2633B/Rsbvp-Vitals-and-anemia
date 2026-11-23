# RSBVP — Remote Screening of Blood Parameters and Vital Signs

RSBVP is an academic research prototype investigating two **independent** questions: camera-derived pulse signals (rPPG), and whether conjunctival image features may associate with laboratory-measured hemoglobin. It is not a medical device, diagnostic tool, or substitute for clinical measurement.

## Current status

- **Pulse research:** Existing Green and POS extraction, motion classification/corrections, FFT/peak estimation, experimental tachogram respiratory analysis, local webcam capture and optional CMS50D evaluation remain available. Defaults now use a 0.7–3.5 Hz (42–210 BPM) search passband. CHROM processing, per-ROI RGB retention with a conservative skin-color mask, timestamp-derived sampling-rate helper, and frame-gap accounting are included. The ROI mask is a heuristic, not MediaPipe landmark segmentation. An algorithm comparison CLI scores Green/POS/CHROM and ROI/multi-ROI variants from a supplied synchronized RGB-trace CSV; it does not create reference data.
- **Anemia research:** No verified dataset or trained model is included. The image quality and RGB/HSV/Lab feature helpers are research utilities only; they do not locate conjunctiva or produce hemoglobin/anemia predictions.
- **Validation:** No new reference recordings, clinical results, dataset performance, or hardware tests are claimed by this update.

The original research scripts, notebooks and archive remain in the repository. The original MIT license and attribution are preserved.

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

Browser exports a timestamped RGB CSV plus JSON run metadata; schema and the offline comparison path are documented in [RGB trace format](docs/RGB_TRACE_FORMAT.md) and [MediaPipe asset notes](docs/MEDIAPIPE_ASSETS.md).

Run tests from the repository root after installing test dependencies:

```bash
python -m pytest -q
```

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

- [Initial repository audit](docs/INITIAL_REPOSITORY_AUDIT.md)
- [Open-source research audit](docs/OPEN_SOURCE_RESEARCH_AUDIT.md)
- [Research backends guide](docs/RESEARCH_BACKENDS.md)
- [Open-source license register](docs/OPEN_SOURCE_LICENSE_REGISTER.md)
- [Methodology and status](docs/RESEARCH_METHODOLOGY.md)
- [Anemia model card](docs/ANEMIA_MODEL_CARD.md)
- [References](docs/REFERENCES.md)
- [Privacy](docs/PRIVACY.md)
- [Deployment](docs/DEPLOYMENT.md)

## Citation and license

See `CITATION.cff` and `LICENSE`. Reuse and derivative works must preserve applicable attribution and MIT license notices.
