# Data readiness

**Status: no external dataset is present in this repository, and none has been evaluated.**

This file is the index. The detailed evidence lives where it was produced, so that
there is one copy of each finding rather than several that drift apart.

| Dataset | Status | Detail |
|---|---|---|
| UBFC-rPPG | **Not available** — probe run, archive absent | [`reports/research_validation/DATA_READINESS.md`](../reports/research_validation/DATA_READINESS.md), machine-readable `data_readiness.{json,md}` |
| MMPD | **Not available** — investigated Sprint 10 | [`docs/MMPD_VALIDATION.md`](MMPD_VALIDATION.md), [`reports/mmpd/`](../reports/mmpd/) |
| COHFACE | **Not available** — request required | this file, §3 |
| rPPG-10 (own protocol) | **Protocol exists, recordings do not** | [`docs/RPPG10_VALIDATION.md`](RPPG10_VALIDATION.md), [`reports/rppg10/`](../reports/rppg10/) |

Verify the current state at any time:

```bash
.venv/bin/python -m research.validation readiness
```

That command prints a machine-readable audit. It **never downloads anything** and
never infers presence from files in the repository; a dataset is `ready` only when an
operator has supplied a local root and the dataset's own adapter has verified the
layout.

---

## 1. Why nothing is bundled

Every dataset below is distributed under terms that forbid redistribution, or is not
public at all. Bundling one would breach its licence; committing "sample" files taken
from it would breach it too. Fetching from an unofficial mirror would breach it and
also make the provenance of the numbers unknowable.

Fabricating a dataset is the worst option available. A synthetic file labelled as real
validation data is indistinguishable from a result, and it would be cited as one.
Synthetic data appears in this repository **only** under `tests/fixtures/validation/`,
where every file is named `synthetic_*`, the directory README says it is not data, and
every figure and report generated from it carries `SYNTHETIC TEST DATA — NOT
VALIDATION` in the output itself.

## 2. What "ready" means

A dataset is ready when all four hold:

1. An operator entitled to the data has obtained it through the provider's own process.
2. It is stored **outside** this repository.
3. Its root path is supplied through the environment variable in the table below.
4. The dataset-specific adapter verifies the layout and returns `ready`.

| Dataset | Environment variable | Adapter |
|---|---|---|
| rPPG-10 (own intake) | `RSBVP_RPPG10_ROOT` | `research/validation/datasets.py::_rppg10_adapter` |
| UBFC-rPPG | `RSBVP_UBFC_ROOT` | `_generic_adapter("UBFC-rPPG …")` |
| COHFACE | `RSBVP_COHFACE_ROOT` | `_generic_adapter("COHFACE …")` |
| MMPD | `RSBVP_MMPD_ROOT` | `_generic_adapter("MMPD")` |

The three external adapters are deliberately **refusing stubs**: given an
unrecognised tree they return `not ready` with the reason and list the top-level
entries they saw. They do not guess which column is the heart rate. Reading the wrong
column as a reference would produce a confident, wrong validation report, which is
worse than an explicit blockage. Writing a real adapter for one of them is a
reviewable change of roughly one function.

## 3. Per-dataset blockers and intake

### 3.1 rPPG-10 — our own protocol (highest priority)

**Blocker.** The protocol, the export format and the evaluation code all exist. What
does not exist is a consented recording with a simultaneous independent reference.
No participant data of any kind is in this repository.

**Intake.** This is the only path that does not depend on a third party, so it is the
one to pursue first:

1. Capture according to [`docs/MANUAL_CAMERA_TESTS.md`](MANUAL_CAMERA_TESTS.md): a
   phone running the app and a reference device, started together, with the reference
   device's own clock recorded at the moment capture starts.
2. Record at least two **synchronisation anchors** — the moment the app's capture
   began, expressed on the reference device's clock. Two are the minimum
   (`derive_offset` refuses one, because one anchor cannot distinguish a clock offset
   from a mistake).
3. Export the session CSV and JSON from the app.
4. Transcribe the reference device's displayed values with their timestamps into a
   CSV (`start_s,end_s,bpm` for intervals, or `t_s,bpm` for samples).
5. Run the reference through the intake directory and evaluate:
   `python -m research.validation evaluate --readings … --reference … --time-base capture_start --anchors S,R --anchors S,R`.
6. Keep the raw files outside the repository; commit only the resulting report.

**Licence.** Controlled by this project. Recordings are not redistributed.

### 3.2 UBFC-rPPG

**Blocker.** Access requires accepting the provider's terms and obtaining the archive
from the provider's distribution; no authorisation instrument is on file in this
workspace, so the archive is deliberately absent. The Sprint 6 probe verified the
source, the citation requirement and the ground-truth format without downloading
anything — see [`reports/research_validation/DATA_READINESS.md`](../reports/research_validation/DATA_READINESS.md).

**Intake.** Obtain from the provider's own distribution, store outside the repository,
point `RSBVP_UBFC_ROOT` at it, run `python -m research.rppg.ubfcrppg_probe`, then write
and review the real adapter.

**Licence.** Research use; redistribution restricted. Required citation is recorded in
the Sprint 6 report.

### 3.3 COHFACE

**Blocker.** Distributed on request from the authors; no request has been made.

**Intake.** Request access, store outside the repository, set `RSBVP_COHFACE_ROOT`,
then write and review the adapter.

**Licence.** Research use on request.

### 3.4 MMPD

**Blocker.** Investigated in Sprint 10; the dataset remains unavailable in this
workspace and no redistribution is permitted. See [`docs/MMPD_VALIDATION.md`](MMPD_VALIDATION.md).

**Intake.** Obtain through the provider's process, store outside the repository, set
`RSBVP_MMPD_ROOT`, run `python -m research.mmpd.mmpd_probe` to verify the layout.

**Licence.** Research use; redistribution restricted.

## 4. What the platform will do with a dataset once it is ready

The dataset layer ends at validated reference intervals
(`research/validation/reference.py::ReferenceTable`). Everything downstream — the
metrics, the comparison, the session aggregation, the report — sees only those
intervals and the session export, never a raw dataset file. This is enforced by
`tests/test_validation_datasets.py::test_metrics_code_does_not_import_dataset_adapters`,
so a dataset-specific quirk cannot change how an error is computed.

## 5. What a ready dataset will *not* prove

A result computed from any of these datasets is a result about that dataset's
recordings, that reference device, those cameras and those conditions. It is **not**
evidence that the RSBVP phone measurement is accurate, and the reports say so in their
own limitations section. Pooling datasets does not make the conclusion general; it
makes the pooled sample larger.
