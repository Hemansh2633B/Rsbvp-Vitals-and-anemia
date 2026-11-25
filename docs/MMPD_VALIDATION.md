# MMPD (Multi-Domain Mobile Video Physiology Dataset) — validation status

**Headline: full dataset validation is NOT RUN — the dataset is not public.
No accuracy number exists for this project on MMPD, and none may be quoted.**

MMPD: 11 h / 1,152K frames of mobile-phone recordings from 33 subjects,
varying skin tone (types 3–6), lighting (LED-low, LED-high, incandescent,
natural), motion (stationary, rotation, talking, walking), exercise state,
gender, glasses, hair cover, makeup. PPG ground truth from a pulse oximeter.
Citation required by the provider:

> Jiankai Tang, Kequan Chen, Yuntao Wang, Yuanchun Shi, Shwetak Patel,
> Daniel McDuff, Xin Liu, "MMPD: Multi-Domain Mobile Video Physiology
> Dataset", IEEE EMBC 2023. doi:10.1109/EMBC40787.2023.10340857

## 1. What the public GitHub repository actually contains (verified 2026-11-24)

Repo: `THU-CS-PI/MMPD_rPPG_dataset`, default branch `main` @
`b88d2e248cf4d0b362c90492d189d7bd68ae85e7`. GitHub API reports the repository
as MIT-licensed for its code. Contents enumerated via the Git tree API:

| Item | What it is | Usable here? |
|---|---|---|
| `gif/` — 16 sample GIFs (~2.3–2.8 MB each) | README illustration clips: `{LED-low,LED-high,Incandescent,Nature}_{S,R,T,W}.gif`, one subject per skin-tone row of the README table. **150 frames @ 112×199, uniform 30 ms/frame, ≈4.5 s, lossy GIF palette** | Yes — pipeline smoke check only (no PPG ground truth, ~13 BPM spectral resolution). Per-file SHA-256 in `reports/mmpd/mmpd_gif_smoke.json` |
| `meta_label.csv` | Public per-recording label manifest (660 recordings × labels: subject, light, motion, exercise, skin_color, gender, glasses, hair_cover, makeup, `.mat` path) | Reference for layout; never copied into Git |
| `size_MMPD.csv` | Provider's per-`.mat` byte sizes for integrity checking | Reference only |
| `MMPD_Release_Agreement.pdf`, `Data Usage Protocol.pdf` | The gate for the real data | Must be signed to obtain data |
| `rPPG-Toolbox_MMPD/` — loader code + `final_model_release/*.pth` | Tsinghua's fork of rPPG-Toolbox with MMPD loaders; pre-trained TS-CAN/DeepPhys/EfficientPhys/PhysNet checkpoints (trained on PURE/SCAMPS/UBFC) | Not runnable here — requires the full dataset + isolated ML environment; checkpoints are not vendored into this repo |
| Full dataset (370 GB @ 320×240 / 48 GB mini @ 80×60) | `.mat` files: `video` [t,w,h,c], `GT_ppg` [t], plus `light/motion/exercise/skin_color/gender/glasser/hair_cover/makeup` | **NOT in the repository. NOT obtained. NOT authorized in this environment.** |

## 2. Access terms (as stated by the provider)

- "This dataset is built for academic use. **Any commercial usage is banned.**"
- Access: download `MMPD_Release_Agreement.pdf`, complete it, and send it
  **from a faculty institutional email** to `tjk24@mails.tsinghua.edu.cn`,
  cc `yuntaowang@tsinghua.edu.cn`, subject `MMPD Access Request - your
  institution`, outlining your institution and intended application.
- Distribution: OneDrive / Baidu Netdisk (not GitHub); no redistribution.
- A subset of two participants' data is available to university faculty for
  educational purposes by email request only.

Nothing in this repository may bypass, fake or imply completion of that
process. The maintainer signs the agreement, not the agent.

## 3. What was actually done this sprint (2026-11-24)

1. Investigated the public repository (tree enumeration, README, agreement
   PDFs, license report, label CSV schema). Evidence summarized in §1.
2. Downloaded the 16 public sample GIFs for a **pipeline smoke check**
   (`research/mmpd/mmpd_probe.py --gif-dir …`): decode → haar face detection →
   forehead/cheek ROIs → YCrCb skin-masked RGB traces → GREEN/POS/CHROM/ICA/PBV
   trace-domain estimators with spectral diagnostics. Generated
   `reports/mmpd/mmpd_gif_smoke.{json,md}` (committed; contains diagnostics
   only — no frames, no personal data).
3. Full per-file provenance (SHA-256, repo commit) recorded in the smoke
   report. Sample GIFs were **not** committed to Git.
4. Found and worked around a real defect: `cv2.CascadeClassifier` (the legacy
   face detector) does not exist in opencv-python(-headless) 5.x headless
   builds; CI now pins `opencv-python-headless<5` with an explanatory comment.

## 4. What this does NOT establish

- **No accuracy/agreement/Bland–Altman/MAE/RMSE number exists for MMPD in this
  project.** The GIFs have no reference PPG; 4.5 s clips fall below the 10 s
  minimum analysis window; transient face-loss clips correctly yield
  `unavailable` diagnostics rather than fabricated estimates.
- The full MMPD benchmark (six classical methods on 33 subjects × 20
  recordings, per-recording and per-condition metrics vs CMS50E-style PPG
  ground truth, participant-grouped bootstrap) is **NOT RUN — DATASET NOT
  OBTAINED**. Nothing about lighting/motion/skin-tone subgroups may be
  claimed.
- The pre-trained checkpoints were not downloaded or run.

## 5. Exact steps to complete the real validation (owner action required)

1. Read `MMPD_Release_Agreement.pdf` and `Data Usage Protocol.pdf`.
2. Faculty signatory sends the request email as specified in §2.
3. After approval, download the archive (OneDrive/Baidu), keep it **outside
   Git**, and place it under `$RSBVP_DATA_ROOT/mmpd/` with the provider's
   `subject<n>/p<n>_<k>.mat` layout preserved (`cat data/README.md`).
4. Inspect before anything else:
   `python research/mmpd/mmpd_probe.py --inspect-mat $RSBVP_DATA_ROOT/mmpd --output-dir reports/mmpd`
   (key/shape/dtype inventory only — never reads signal values; cross-checks
   against `meta_label.csv` counts).
5. Build the synchronized-trim benchmark with the trace-domain reference
   methods (`research/backends/`), identical 12 s windows / 6 s step,
   0.7–3.5 Hz passband, hann-periodogram estimator, references joined only
   after prediction. Verify timestamp/clock handling against the provider's
   documentation — never visual alignment. Set the relevant manifest
   provenance fields.
6. Report per-recording and per-condition metrics (light, motion, skin_color)
   via `research/backends/metrics.py` with participant-level bootstrap CIs as
   the primary readout. Treat each recording as the unit (the provider does
   not publish a recording→participant map beyond the `p` index in labels —
   verify against the agreement).
7. Do not tune any estimator on these data. Publish nothing derived from the
   dataset without reproducing the agreement's terms and the citation above.
8. Update `reports/research_validation/validation_report.md` and
   `docs/IMPLEMENTATION_STATUS.md`; flip MMPD rows from NOT RUN to the actual
   result. Until then, MMPD stays NOT RUN.

## 6. Honest one-line status

`SMOKE-TESTED on public samples / NOT RUN for accuracy — requires signed MMPD data-release agreement and local dataset acquisition.`
