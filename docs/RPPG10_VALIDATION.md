# rPPG-10 — readiness assessment and benchmark protocol

**Headline: RUN on the local authorized copy (2026-11-25).** The benchmark
executed end-to-end: 26 participants × 3 ROIs × 20 non-overlapping 30 s
windows, with an ECG-derived reference. The numbers are in
`reports/rppg10/rppg10_benchmark.{json,md}`.

**Read the result as encoded in code, not as accuracy:** 477 of 540 ECG
reference windows (88 %) were accepted; the frozen quality gates then accepted
only 124/477 forehead-GREEN windows (25 % usable coverage, 16 of 26 participants
contributing). The pooled MAE on those accepted windows (0.95 BPM) is therefore
**availability-conditional and must never be quoted without its coverage** —
11 of 26 participants contribute nothing at all because their pulsatile signal
never passes the gates. The gates-OFF, provider-comparable figure is 8.03 BPM
pooled MAE on the combined ROI across all 26 participants and 477 windows, which
brackets the provider's published 7.57 ± 0.66 BPM. Full accounting, including the
selection-bias diagnostic and per-participant results, is in the report.

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

## 2a. Result summary (2026-11-25 run)

Protocol `rsbvp.rppg10-protocol.v1`, ECG reference from `research/ecg/reference.py`,
26 participants (Subject_4 explicitly excluded — see §2b), 78 recordings,
1482 window-records.

| View | What it means | GREEN | POS | CHROM |
|---|---|---|---|---|
| **Combined ROI, gates OFF** (provider-comparable, descriptive) | mean of the three ROI estimates per window, all 477 windows with a reference, all 26 participants | **8.03** BPM pooled MAE (median participant 5.23) | 11.29 (9.82) | 13.19 (12.23) |
| Provider's published baseline (context only) | rPPG-Toolbox, combined ROI, non-overlapping 30 s windows | 7.57 ± 0.66 | 7.59 ± 0.46 | 10.05 ± 0.46 |
| **Per-ROI, gates ON** (frozen protocol) | only windows that passed the frozen gates | forehead 0.95 (n=124, 25 % coverage, 16/26 participants) | 1.22 (n=53, 11 %) | 0.84 (n=31, 6 %) |

**Interpretation rules that are part of the result:**
- The gates-ON numbers are **availability-conditional**. They must always be
  quoted with coverage and participant count.
- The gates-ON numbers are **lower than** the provider's baseline without any
  tuning, because our gates reject ~75–99 % of windows. That is selection, not
  superiority: the ungated row reproduces the provider's order of magnitude, and
  the ungated row is the honest yardstick for the implementation.
- **No leakage**: biological (not algorithmic) leakage is impossible — the ECG is
  an independent sensor. As a mechanical control, permuting references between
  participants raises forehead-GREEN MAE from 0.95 to 11.39 ± 2.01 BPM, and
  shifting each estimate onto the *next* window of the same participant raises it
  to 2.60 BPM. The pairing is real.
- CHROM performs worst on this dataset at every ROI (ungated 13–17 BPM), which is
  a dataset-level finding consistent with the provider reporting CHROM as their
  weakest method (10.05 BPM).

### Data-quality findings that changed the reference pathway
Both were found by running the pathway on the real recordings and are now
enforced in code, with tests:
1. **ADC rail saturation in beats**: some recordings contain sustained runs of
   samples pinned at 0 or 1023 (Subject_3: a 174-sample run; Subject_10: 214
   samples). A single-sample clip check misses this. `ecg_rail_saturated` now
   rejects the affected windows (14 of 540).
2. **Ambiguous rhythms cannot be certified by one detector.** A second,
   mechanically different detector (matched filtering against the median QRS) now
   cross-checks every window; disagreement yields `ecg_cross_check_disagreement`
   (3 of 540) instead of a number.

Subject-level detail (e.g. Subject_2's alternating 0.63 s / 0.99 s heart rate at
57–95 BPM, consistent with bigeminy) is **not** diagnosed or classified here: the
pathway only guarantees a trustworthy *median* rate per window, and it does not
claim any rhythm interpretation.

## 2b. What the local copy required (deviations from the documentation)

| Documentation says | The released archive actually contains | Handling |
|---|---|---|
| `Subject_<n>_<ROI>.avi` | `Subject_<n>_<ROI>_.avi` (trailing underscore) | both accepted; exact name preserved in the inventory |
| 26 subjects, Subject_4 excluded | **27 folders** including `Subject_4`, whose three ROI videos are **0-byte placeholders** (ECG file is real) | requires explicit `--exclude-subjects 4`; the exclusion, the provider citation and the 0-byte evidence are written into the report |
| `.xlsx` metadata | `Dataset_rPPG-10/Subject Data.xlsx` | recorded, never parsed |

The archive in `data/rPPG-10.zip` (SHA-256
`4faed19048db8dce15bd9c8f5087bc580ab64dc55a9401873804237ebd9ce62f`) is itself a
zip containing `rPPG-10/Dataset_rPPG-10.zip`; the inner archive (238 MB expanded,
109 files) is what the adapter reads.

## 2c. What was actually executed (2026-11-25)

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
5. Ran `run_benchmark.py readiness` → `reports/rppg10/rppg10_readiness.{json,md}`
   (kept for provenance of the pre-data state).
6. After the dataset was supplied, ran `inspect` (26 subjects complete, 1
   deviation: provider spreadsheet, 1 documented-exclusion notice) and then
   `benchmark` on the full copy → `reports/rppg10/rppg10_benchmark.{json,md}`.

**Not executed:** nothing remains blocked on data for this dataset. What is still
*not* claimed: chunk-level (t < 30 s) estimation, HRV/PRV, morphology, clinical
validity, generalisation beyond the 26 participants.

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

## 5. Reproducing the run exactly

```bash
# 1. Unpack the provider archive outside Git (the repo's data/rPPG-10.zip is a
#    zip-in-zip; the inner Archive is what the adapter reads)
unzip -o data/rPPG-10.zip -d /tmp/rppg10
unzip -o /tmp/rppg10/rPPG-10/Dataset_rPPG-10.zip -d /tmp/rppg10/extracted

# 2. Readiness (blocks on structural errors, reports deviations)
python research/rppg10/run_benchmark.py inspect \
    --data-root /tmp/rppg10/extracted/Dataset_rPPG-10 \
    --output-dir reports/rppg10 --ecg-fs-hz 1000 --exclude-subjects 4

# 3. Benchmark (frozen protocol; ~3 minutes on a laptop CPU)
python research/rppg10/run_benchmark.py benchmark \
    --data-root /tmp/rppg10/extracted/Dataset_rPPG-10 \
    --output-dir reports/rppg10 --ecg-fs-hz 1000 --exclude-subjects 4 \
    --allow-deviation --i-have-verified-the-licence
```

`--allow-deviation` is required only because the provider spreadsheet is present
and the archive is not byte-identical to the documented naming; both are echoed
into the report. `--i-have-verified-the-licence` is required because the data
licence is non-commercial.

Do not tune anything on these results. Any protocol change requires a new
protocol version and an explicit note in the report. The JSON keeps every window
row (1482 records) so a re-run and a re-analysis are auditable.

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

`RUN on the local authorized copy (26 participants, 477/540 ECG reference windows accepted). Gated per-ROI MAE 0.81–1.64 BPM at 0.2–25 % usable coverage; provider-comparable ungated combined-ROI GREEN MAE 8.03 BPM. Not a clinical result; not evidence of generalisation; not HRV/PRV validation.`
