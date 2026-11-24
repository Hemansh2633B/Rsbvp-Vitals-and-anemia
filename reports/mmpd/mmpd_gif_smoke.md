# MMPD sample-GIF pipeline smoke report

**rsbvp.mmpd-gif-smoke.v1** — 16 public sample GIFs, 71.52s total.

**DIAGNOSTIC PIPELINE CHECK ONLY. The sample GIFs carry no reference PPG. No accuracy, fidelity, or clinical metric is computed or claimed.**

| GIF | frames | fps | dur(s) | face detect | ROI cov (F/LC/RC) | meets ≥10s |
|---|---|---|---|---|---|---|
| Incandescent_R.gif | 150 | 33.333 | 4.47 | 0.3867 | 0.9828/0.931/0.931 | no |
| Incandescent_S.gif | 150 | 33.333 | 4.47 | 1.0 | 1.0/1.0/1.0 | no |
| Incandescent_T.gif | 150 | 33.333 | 4.47 | 0.8 | 1.0/0.8417/1.0 | no |
| Incandescent_W.gif | 150 | 33.333 | 4.47 | 1.0 | 1.0/1.0/1.0 | no |
| LED-high_R.gif | 150 | 33.333 | 4.47 | 0.84 | 1.0/1.0/1.0 | no |
| LED-high_S.gif | 150 | 33.333 | 4.47 | 1.0 | 1.0/1.0/1.0 | no |
| LED-high_T.gif | 150 | 33.333 | 4.47 | 1.0 | 1.0/1.0/1.0 | no |
| LED-high_W.gif | 150 | 33.333 | 4.47 | 1.0 | 1.0/1.0/1.0 | no |
| LED-low_R.gif | 150 | 33.333 | 4.47 | 0.8467 | 0.9921/0.9291/0.937 | no |
| LED-low_S.gif | 150 | 33.333 | 4.47 | 1.0 | 1.0/1.0/1.0 | no |
| LED-low_T.gif | 150 | 33.333 | 4.47 | 1.0 | 1.0/1.0/1.0 | no |
| LED-low_W.gif | 150 | 33.333 | 4.47 | 1.0 | 1.0/1.0/1.0 | no |
| Nature_R.gif | 150 | 33.333 | 4.47 | 0.7667 | 0.9826/1.0/1.0 | no |
| Nature_S.gif | 150 | 33.333 | 4.47 | 1.0 | 1.0/1.0/1.0 | no |
| Nature_T.gif | 150 | 33.333 | 4.47 | 1.0 | 1.0/1.0/1.0 | no |
| Nature_W.gif | 150 | 33.333 | 4.47 | 1.0 | 1.0/1.0/1.0 | no |

## What this proves and what it does not

- Proves: the offline decode → face/ROI → skin-mask → trace → estimator path executes on real mobile-camera MMPD sample GIFs and reports unavailable states instead of crashing or fabricating.
- Does NOT prove: any estimate is correct, stable, or physiological. 4.5 s clips fall far below the 10 s research minimum window; spectral resolution ≈ 13 BPM; gates are not physiologically calibrated.
- Accuracy evaluation against PPG ground truth requires the **full MMPD dataset**, which is not public: it needs the signed data-release agreement (faculty-signed email to the authors) and local placement under `RSBVP_DATA_ROOT`. See `docs/MMPD_VALIDATION.md`.
