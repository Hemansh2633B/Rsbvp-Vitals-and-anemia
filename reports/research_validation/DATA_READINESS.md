# UBFC-rPPG data readiness report

**Status: NOT AVAILABLE — dataset not present; no dataset-level benchmark was run.**

Generated 2026-11-23 (Sprint 6). Companion machine-readable output: `data_readiness.json` / `data_readiness.md` (probe artifact, status `not_available`).

## 1. Official source (verified 2026-11-23)

Fetched: `https://sites.google.com/view/ybenezeth/ubfcrppg` (public project page of the provider; read 2026-11-23).

Verified page contents:

| Item | Value (as stated on the official page) |
|---|---|
| Full name | UBFC-rPPG (Univ. Bourgogne Franche-Comté Remote PhotoPlethysmoGraphy) |
| Recorded by | R. Macwan and Y. Benezeth |
| Camera | Logitech C920 HD Pro webcam, 30 fps, 640×480, uncompressed 8-bit RGB, custom C++ acquisition app |
| Subject distance | ~1 m, face visible, indoors, varying sunlight and indoor illumination |
| Ground truth | CMS50E transmissive pulse oximeter — PPG waveform and PPG heart rates |
| Dataset 1 (simple) | 8 videos, ~16,500 frames; participants sit still (some videos show movement, especially at the beginning) |
| Dataset 2 (realistic) | 42 of 46 videos shared for research purposes; time-sensitive mathematical game intended to augment heart rate during a normal human-computer interaction scenario |
| Download | Google Drive folder `https://drive.google.com/drive/folders/1o0XU4gTIo46YfwaWjIgbtCncc-oF44Xk?usp=drive_link` · OneDrive `https://univbourgogne-my.sharepoint.com/:f:/g/personal/yannick_benezeth_u-bourgogne_fr/IgDQvHIcDjiMSrzknzArGE25AVSjt4fjw11QgLpsJX2QPec?e=ySQtZt` · DaTa@BFC (page states “link available soon”); basic Matlab and Python ground-truth readers are stated to be provided with the data |
| Contact | Yannick Benezeth (yannick.benezeth@u-bourgogne.fr), Richard Macwan (richard.macwan@u-bourgogne.fr), Serge Bobbia (serge.bobbia@u-bourgogne.fr) |
| Required citation | S. Bobbia, R. Macwan, Y. Benezeth, A. Mansouri, J. Dubois, “Unsupervised skin tissue segmentation for remote photoplethysmography,” *Pattern Recognition Letters*, 2017. |

The task's two evaluation targets — realistic subset (42) as primary, simple subset (8) as sanity check — match the official split above.

## 2. What is NOT verified

- The archive itself: **not downloaded, not inspected, not present.** Google Drive/OneDrive are not reachable from this development workspace, and no authorization instrument is on file. Raw recordings were not downloaded, uploaded or committed (they must never be).
- `ground_truth.txt` layout: unverified. The rPPG-Toolbox loader at the pinned commit `b7500b848f84ad7f86e277b4612563b69f4f88f9` (`dataset/data_loader/UBFCrPPGLoader.py`, source-inspected 2026-11-23) consumes `subject<n>/vid.avi` + `subject<n>/ground_truth.txt`, reads **only the first line** and parses it as space-separated float BVP samples, with `FS: 30`. This is the **toolbox's consumption convention, not a verified description of the archive documentation**. Whether `ground_truth.txt` carries timestamps, HR values, units or additional lines is UNKNOWN locally.
- Synchronization between video timestamps and the CMS50E clock: UNKNOWN locally. No `time_offset_s` may be assumed.
- Which of the two subsets a local copy holds, and which recordings belong to which: not determinable from directory names; requires the provider's list.
- License: the official page states no explicit license; it offers the dataset for research use with a request for citation. Treat access as **research-only, citation required, no redistribution**, and obtain the provider's written terms before any redistribution, publication or downstream release. This repository redistributes nothing.

## 3. Local state check (2026-11-23)

- `RSBVP_DATA_ROOT`: unset in the development environment.
- Repository contains **no** dataset archives, videos, HDF5 files or participant-level derived data (`data/manifests/*.example.csv` are blank schema templates marked `license_verified=false`).
- `reports/validation/validation.md`: `NOT RUN — DATASET NOT AVAILABLE`.
- `reports/research_validation/data_readiness.json|md`: probe output, status `not_available`, 0 subject directories at `data/ubfc-rppg`.

## 4. Layout consumed by the in-flight benchmark (for planning only, NOT verified)

```
$RSBVP_DATA_ROOT/ubfc-rppg/
  subject<n>/vid.avi            # 30 fps 640×480 (as stated by the provider page)
  subject<n>/ground_truth.txt   # PPG/BVP samples; semantics unverified — see §2
```

Do **not** rearrange a downloaded archive to match this sketch; inspect it with the probe first.

## 5. What must happen before any dataset-level number is reported

1. Obtain the archive through the official channels (Drive/OneDrive/DaTa@BFC) and record a provenance note: provider, URL, date obtained, stated terms, citation confirmation.
2. Keep the archive **outside Git**; set `RSBVP_DATA_ROOT` (see `data/README.md`). Never commit videos, `ground_truth.txt`, or derived participant-level data.
3. Run the readiness probe: `python research/rppg/ubfcrppg_probe.py --output-dir reports/research_validation` (uses `$RSBVP_DATA_ROOT/ubfc-rppg`, or `--archive-dir`). Resolve every `problem:` line against the provider documentation — do not guess units, rates or offsets.
4. Confirm which recordings are the simple (8) vs realistic (42) subsets with the provider or official docs; assign pseudonymous `recording_id`s; keep the mapping local.
5. Verify synchronization (video timestamps vs CMS50E clock) and the PPG reference modality/units; document the clock offset **from documentation**, never from visual alignment.
6. Instantiate browser-export-style RGB traces (or the toolbox's `vid.avi` pipeline for toolbox methods) and run the standardized benchmark (`research/backends/benchmark.py`) with identical 12 s / 6 s windows, 0.7–3.5 Hz passband, hann-periodogram estimator.
7. Metrics only via `research/backends/metrics.py`: MAE/RMSE/bias/Bland–Altman LoA/Pearson/MAPE + availability, rejection accounting, latency, per-recording and per-recording-participant coverage; participant-level bootstrap CIs as primary inferential readout. Treat each recording as the unit unless per-recording participant mapping is obtained.
8. Report under `reports/research_validation/` with this file updated to `available_for_inspection` and the full provenance table filled in. Until then: **NO RESULTS MAY BE REPORTED OR PUBLISHED.**

## 6. COHFACE — secondary candidate (checked 2026-11-23, Sprint 7)

A second authorized-data candidate was checked so the blocker list is complete (no data was accessed; nothing was downloaded):

| Item | Value |
|---|---|
| Contents | 160 one-minute sequences of 40 subjects (12 F / 28 M); Logitech HD C525, 640×480 @ 20 fps; synchronized PPG and respiration ground truth via BioGraph Infiniti (Thought Technologies) |
| Access | Non-commercial End-User License Agreement; request via the official page; Zenodo record `4081054` (metadata, modified 2025-09-15); distribution via the provider (Idiap) |
| Terms | Strictly restricted to **non-commercial research**; EULA sent after application; no redistribution; cite the provider (and per provider practice, De Haan / Tarassenko COHFACE publications) |
| Local status | **NOT PRESENT — NOT RUN.** No archive in this environment; no authorization instrument on file |

COHFACE is a lower frame rate (20 fps), different camera and different illumination profile than UBFC-rPPG; it is a complementary check, not a substitute, and would require its own readiness probe, synchronization verification and license confirmation before any number could exist.

## 6a. Re-verification note (2026-11-23, reproducibility sprint)

The official page and both candidate datasets were re-checked this sprint against primary sources: the UBFC-rPPG project page (Google Drive / OneDrive / DaTa@BFC download pattern, research-use request with citation, Bobbia et al. 2017) remains unchanged, and COHFACE remains restricted to non-commercial research via Idiap/Zenodo 4081054 under an EULA. A third-party mirror of UBFC-rPPG on Kaggle (claiming CC0) was observed but is **not authoritative** and must not be used or redistributed without the provider's written terms; this repository does not rely on it. The archive is **still not present in this environment** and `RSBVP_DATA_ROOT` remains unset — nothing in this section authorizes downloading or committing the data. Every step in §5 remains required before any dataset-level number may exist.

## 7. Why this report exists instead of results

Fabricating a benchmark — from synthetic data, from assumed layouts, from unverified sample rates — would violate the dataset's intended use, the repository's honesty rules, and basic scientific practice. The correct output when the data are absent is this report.
