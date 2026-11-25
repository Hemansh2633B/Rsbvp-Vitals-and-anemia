# rPPG-10 readiness assessment

**Status: NOT RUN — dataset not present in this environment.**

- Dataset: rPPG-10 (Mendeley Data, doi:10.17632/bx8982xgwt.1), CC BY-NC-SA 4.0.
- Citation: Rodrigues G., Garcia N.M. *Evaluating remote photoplethysmography: a 10-minute video dataset
  in uncontrolled lighting.* Data in Brief 61 (2025) 111888. doi:10.1016/j.dib.2025.111888
- Documented contents: 26 participants × 3 ROI videos (forehead, right/left cheek), 600 s each, 64×64 AVI,
  synchronised BITalino ECG (`.npy`), plus a provider metadata spreadsheet. Subject_4 excluded by the provider.
- Adapter: `research/rppg10/adapter.py` (inventory + trace extraction; no guessed metadata, no repairs).
- ECG reference pathway: `research/ecg/reference.py` (Pan–Tompkins R-peaks; 60/median R-R per window).
  The existing evaluator continues to reject ECG references — that behaviour is deliberately preserved.
- Protocol: `rsbvp.rppg10-protocol.v1` frozen 2026-11-25 —
  30 s non-overlapping windows, GREEN/POS/CHROM, unchanged quality gates, participant-level bootstrap.

## Why it is not run

Dataset not present in this environment. The readiness adapter, ECG reference pathway, frozen protocol and dataset-independent tests are complete; the benchmark itself is NOT RUN.

## What is ready

1. Readiness inventory (`inspect`) that derives file facts and reports every inconsistency as a
   machine-readable validation failure.
2. An independently tested ECG reference pathway with explicit rejection tokens.
3. A frozen, pre-registered protocol with participant-grouped uncertainty and explicit coverage accounting.
4. Dataset-independent regression tests (synthetic ECG, synthetic traces, synthetic videos).

## What must happen to run it

1. Download the dataset from the provider record (no agreement gate is documented, but the licence is
   **non-commercial** — confirm this is acceptable for the intended use).
2. Keep it **outside Git**, e.g. `$RSBVP_DATA_ROOT/rppg10/Subject_1/...`.
3. `python research/rppg10/run_benchmark.py inspect --data-root $RSBVP_DATA_ROOT/rppg10 --output-dir reports/rppg10 --ecg-fs-hz 1000`
4. Resolve every validation failure in the inventory (do not edit the report).
5. `python research/rppg10/run_benchmark.py benchmark --data-root ... --output-dir reports/rppg10 --ecg-fs-hz 1000 --i-have-verified-the-licence`
   (add `--allow-deviation` only if you have reviewed each documented-attribute deviation; the deviations are echoed into the report)

## Limitations that will still apply after the run

- 26 participants (Subject_4 excluded by the provider), predominantly young Portuguese university students; Fitzpatrick I–IV only (no V/VI). No generalisation beyond this population.
- Single-site acquisition: one room, natural indoor daylight, 10:00–16:00, one webcam type, participants seated and asked to stay still. No claim about other lighting, motion or devices.
- 64×64 ROI crops with consumer compression: fine pulsatile detail is limited by the provider's anonymisation pipeline, not by this implementation.
- Video/ECG synchronisation is manual with a documented uncertainty of up to ±500 ms; this protocol therefore evaluates 30 s windows, not sub-second timing.
- The ECG reference is a pulse-rate reference derived from R-peaks. Agreement with it is NOT validation of pulse-rate variability, HRV, or any clinical parameter.
- Non-commercial licence (CC BY-NC-SA 4.0): results are research-use only and share-alike terms apply to redistribution of derived data.

No accuracy metric exists for rPPG-10 in this project, and nothing in this document is a result.
