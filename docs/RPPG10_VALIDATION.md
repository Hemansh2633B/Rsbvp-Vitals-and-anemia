# rPPG-10 — readiness assessment and benchmark protocol

**Headline: NOT RUN. No accuracy number exists for rPPG-10 in this project, and
none may be quoted from this repository.** The dataset is publicly downloadable
(CC BY-NC-SA 4.0) but no authorized local copy was supplied to the development
environment, so only the readiness path was executed.

- Dataset: **rPPG-10** — Rodrigues G., Garcia N.M., *Evaluating remote
  photoplethysmography: a 10-minute video dataset in uncontrolled lighting*,
  Data in Brief 61 (2025) 111888, doi:10.1016/j.dib.2025.111888
- Record: Mendeley Data, doi:10.17632/bx8982xgwt.1
  (<https://data.mendeley.com/datasets/bx8982xgwt/1>), published 2025-04-04, v1.
- Licence: **CC BY-NC-SA 4.0** (non-commercial, share-alike). The article itself
  is CC BY 4.0; the *data* licence governs use of the data. Verify current terms
  at the record before use — they are the provider's, not this repository's.
- Institution: Universidade de Lisboa, Faculdade de Ciências (Portugal).
- Ethics: Faculty of Sciences of the University of Lisbon, ref. CEC/2/2024
  (per the article); written informed consent; anonymised 64×64 ROI crops.

## 1. Verified dataset facts (from the provider record + article)

| Item | Provider statement | How this repository treats it |
|---|---|---|
| Participants | 26 (12 male, 14 female), mean age 22.5 ± 1.2 y; 27 recorded, **Subject_4 excluded** by the provider | `expected_subjects` check; exclusion never re-added |
| Recordings | 3 ROI videos per participant (forehead, Cheek1 = right cheek, Cheek2 = left cheek), 600 s each, 30 fps | `ROI_TO_PROJECT` mapping; durations re-derived from containers |
| Video | AVI, **64×64**, XVID crop of a 1280×720 / 30 fps Microsoft webcam original | strict size/fps checks → `video_size_unexpected` / `video_fps_unexpected` |
| ECG | BITalino, 3 electrodes (wrists + left hip), **1000 Hz, ±1.5 mV**, `.npy` per subject, saved as a Python list | sampling rate must be **supplied by the caller** (`--ecg-fs-hz`), never guessed |
| Synchronisation | manual trigger pulse on the ECG stream; **not** hardware-embedded in video; documented uncertainty **≤ ±500 ms** | 30 s windows only; no sub-second claim; offset never guessed |
| Environment | natural daylight only, one room, 10:00–16:00, illumination 0–800 lx, white background | no generalisation claim; conditions are the dataset's, not ours |
| Skin tone | Fitzpatrick I–IV only (I=2, II=17, III=4, IV=3; V/VI=0) | documented limitation |
| Metadata | provider `.xlsx` (demographics, health factors, environment) | presence recorded; **never parsed** by this repository |
| Provider baseline | rPPG-Toolbox, combined forehead+both cheeks, non-overlapping 30 s windows, GREEN MAE 7.57 ± 0.66 BPM etc. | context only — never used as this repository's result |

Documented acquisition defects (from the article): ≈15–20 brief face-tracking
failures per dataset with fallback to the previous frame; Subject_13 partly
out of focus; Subject_21 last ~20 s obstructed; Subject_4 excluded entirely.

## 2. What was actually executed (2026-11-25)

1. Verified the provider record, article (methods, limitations, ethics),
   licence, and the authors' public code repository (`GRodrigues4/rPPG-10`).
   The public notebook documents the raw ≥1000 Hz ECG stream, the 6th column
   of the OpenSignals text export (`row[5]`), and `np.save` of that column —
   hence 1000 Hz `--ecg-fs-hz` for the released `.npy` files.
2. Implemented the readiness adapter (`research/rppg10/adapter.py`): discovery,
   container-level inventory, checksums, machine-readable validation failures.
3. Implemented the **independent ECG reference pathway**
   (`research/ecg/reference.py`) with 22 dataset-independent tests.
4. Froze the benchmark protocol (`research/rppg10/protocol.py`, v1) **before**
   any data was available; 34 dataset-independent protocol tests.
5. Ran `run_benchmark.py readiness` → `reports/rppg10/rppg10_readiness.{json,md}`.

**Not executed:** the benchmark itself, on any real rPPG-10 file.

## 3. Frozen benchmark protocol (v1, `rsbvp.rppg10-protocol.v1`)

| Element | Frozen choice | Rationale |
|---|---|---|
| Windows | 30 s, **non-overlapping** (step = 30 s) → 20 windows/recording | matches the provider's baseline; avoids treating correlated windows as independent observations |
| Estimators | GREEN, POS, CHROM (`research/backends/reference_methods.py`) | implemented, documented, independently tested; ICA/PBV excluded from the primary protocol |
| Passband | 0.7–3.5 Hz (42–210 BPM) | repository-wide default; **not** dataset-tuned |
| Quality gates | existing `quality_failures` constants (concentration, SNR, separation) | unchanged; a failing window yields `bpm = null` + tokens |
| ROIs | forehead / right_cheek / left_cheek evaluated separately | provider ROI structure; no invented fusion |
| Reference | ECG → Pan–Tompkins R-peaks → 60 / median(valid R-R) per window | documented method, no ECG spectral peak, no HRV |
| Joining | reference joined **after** estimation, per window | no reference value enters any estimator or gate |
| Uncertainty | participant-level bootstrap, 2000 draws, seed 20261125 | ROIs are not independent participants |
| Coverage | every window counted; rejected references excluded from error stats and reported | no silent dropping |
| Tuning | none; no per-subject offset; no post-hoc outlier removal | pre-registered |

Deviation policy: a local copy differing from the provider's documented
attributes (e.g. truncated videos) is **not** silently accepted. Structural
errors block the run; documented-attribute deviations require
`--allow-deviation` and are echoed into the report. In addition
`--i-have-verified-the-licence` is mandatory, because the data licence is
non-commercial.

## 4. ECG reference pathway (independent, deliberately separate)

The generic trace-manifest evaluator still **rejects** ECG references with
`ecg_rpeak_estimator_unavailable` — that behaviour is intentional and covered
by an existing regression test. The ECG reference pathway is separate:

- Pan–Tompkins (1985) QRS detection: 5–15 Hz zero-phase bandpass (order 2),
  five-point derivative, squaring, 150 ms moving-window integration, adaptive
  SPKI/NPKI thresholding, 200 ms refractory, ±80 ms R-peak refinement.
- Additional guard: median R-peak deflection must exceed 3 robust noise sigma
  (`ecg_qrs_prominence_low`) so noise-only or artefact-contaminated segments
  cannot manufacture a reference rate.
- HR rule: `60 / median(valid R-R)` — robust to residual misdetections.
- Rejection tokens: `ecg_fs_invalid`, `ecg_not_1d`, `ecg_empty`,
  `ecg_nonfinite_samples`, `ecg_flat_signal`, `ecg_saturated`,
  `ecg_length_too_short`, `ecg_timestamps_length_mismatch`,
  `ecg_timestamps_not_increasing`, `ecg_timestamps_irregular`,
  `ecg_window_bounds_invalid`, `ecg_window_too_short`, `ecg_window_out_of_bounds`,
  `ecg_too_few_rpeaks`, `ecg_rr_out_of_range`, `ecg_qrs_prominence_low`.
- Guards: fs ∈ [100, 2000] Hz, R-R ∈ [0.3, 2.0] s, ≤25 % implausible R-R,
  ≥3 R-peaks per window, window ≥5 s.

**Explicitly not claimed:** HRV/PRV, inter-beat timing, arrhythmia detection,
clinical interpretation. Video-vs-ECG agreement measures *pulse-rate* agreement
only. With ≤±500 ms synchronisation uncertainty, nothing sub-second is claimed.

## 5. Exact steps to complete the real benchmark

1. Read the current licence at the Mendeley record; confirm non-commercial use
   is acceptable for your intent (the data, not the article, is NC).
2. Download `Dataset_rPPG-10.zip` (~116 MB) — **keep it outside Git**.
3. Extract to `$RSBVP_DATA_ROOT/rppg10/Subject_<n>/...` (provider layout).
4. `python research/rppg10/run_benchmark.py inspect --data-root $RSBVP_DATA_ROOT/rppg10 --output-dir reports/rppg10 --ecg-fs-hz 1000`
5. Resolve every `error`-severity validation failure (do not edit the report).
   Review each `deviation` (duration/fps/size) against the provider docs.
6. `python research/rppg10/run_benchmark.py benchmark --data-root ... --output-dir reports/rppg10 --ecg-fs-hz 1000 [--allow-deviation] --i-have-verified-the-licence`
7. Publish `reports/rppg10/rppg10_benchmark.{json,md}` with the dataset
   citation, the frozen protocol version, and §6 limitations attached.
8. Do not tune anything on these results. Any later protocol change requires a
   new protocol version and an explicit note in the report.

Runtime note: decoding 78 ROI videos × 600 s at 64×64 takes minutes on a
laptop CPU; the dataset JSON keeps every window row so a re-run is auditable.

## 6. Limitations that remain true after a successful run

- **26 participants**, predominantly young (mean 22.5 y) Portuguese university
  students; Fitzpatrick I–IV only, no V/VI. Recruitment was passive (email,
  flyers): no claim of ethnic, age, or skin-tone representativeness.
- **One acquisition environment**: single room, natural daylight, 10:00–16:00,
  0–800 lx, one webcam model, seated participants asked to stay still.
  No claim for other lighting, motion, devices, or clinical settings.
- **64×64 compressed ROI crops** cap fine pulsatile detail; results reflect the
  provider's anonymisation pipeline as much as the algorithms.
- **Manual synchronisation** with ≤±500 ms uncertainty; 30 s windows only.
- **ECG-derived reference HR is a pulse-rate reference, not an optical pulse
  waveform**: it can validate average rate, not morphology, PRV, or HRV.
- **Non-commercial licence**: research use only; share-alike terms apply to
  redistribution of derived data.
- The provider's own baseline numbers are context, not a target and never a
  substitute for this repository's result.

## 7. Honest one-line status

`ADAPTER + ECG REFERENCE PATHWAY + FROZEN PROTOCOL TESTED / BENCHMARK NOT RUN — no authorized local copy in this environment.`
