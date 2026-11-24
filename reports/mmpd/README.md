# MMPD reports — provenance

Files in this directory:

- `mmpd_gif_smoke.json` / `mmpd_gif_smoke.md` — output of
  `research/mmpd/mmpd_probe.py --gif-dir <dir-of-public-sample-gifs>` on the 16
  public sample GIFs from `THU-CS-PI/MMPD_rPPG_dataset` (Git tree commit
  `b88d2e248cf4d0b362c90492d189d7bd68ae85e7`). Contains only per-GIF pipeline
  diagnostics and SHA-256 hashes — no frames, no personal data, no accuracy
  metric. **Not an accuracy evaluation** (no reference PPG exists for the
  samples; each clip is ≈4.5 s, below the 10 s analysis minimum).
- `mmpd_mat_inspect.json` — written only when the full dataset is lawfully
  obtained and `--inspect-mat` is run locally (key/shape/dtype inventory;
  never committed together with dataset files, which are never allowed in Git).

Sample GIFs and MMPD dataset files must NOT be committed here or anywhere in
this repository. See `docs/MMPD_VALIDATION.md` for terms and acquisition.
Regenerate the smoke report with:

```bash
python research/mmpd/mmpd_probe.py --gif-dir /path/to/sample-gifs --output-dir reports/mmpd
```
