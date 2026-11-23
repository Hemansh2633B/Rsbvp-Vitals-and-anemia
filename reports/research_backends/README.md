# reports/research_backends/ — generated benchmark summaries

Everything under this directory is produced by `research/backends/benchmark.py`.
Nothing here is physiological validation. The committed example is a **deterministic
synthetic fixture** (70 BPM synthetic pulse, zero biological meaning), included only
so the schema and metrics can be inspected offline.

## Synthetic example (`synthetic/`)

Regenerate byte-identically (inputs are committed; `records.json`/`waveforms.csv` are omitted from git for size):

```bash
python research/backends/benchmark.py \
  reports/research_backends/synthetic/inputs/synthetic_70bpm.csv \
  --backends rsbvp_native,rsbvp_reference \
  --reference-windows reports/research_backends/synthetic/inputs/reference_windows.csv \
  --reference-source "deterministic synthetic fixture (software verification only)" \
  --output-dir reports/research_backends/synthetic
```

Committed artifacts: `inputs/synthetic_70bpm.csv` (generator logic: 60 s, 30 Hz,
70 BPM sinusoid, `default_rng(20261123)`), `inputs/reference_windows.csv`,
`records.csv`, `summary.json`, `summary.md`.

To regenerate the large waveform exports locally, add `--output-dir` pointing at a
scratch directory; do not commit `records.json` or `waveforms.csv`.

## Dataset-level report

**NOT RUN — DATASET NOT AVAILABLE.** No authorized UBFC-rPPG archive (or COHFACE) is
present in this workspace and none may be downloaded automatically. When authorized
access exists, run the protocol in `docs/RESEARCH_BACKENDS.md` §6 and commit the
resulting report here with: dataset citation, access basis, pseudonymous participant
IDs, and RAIL-1.1-compliant attribution if the rPPG-Toolbox was used.
