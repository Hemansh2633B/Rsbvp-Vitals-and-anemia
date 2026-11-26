# External research repositories (git submodules)

The five external projects this work references are pinned as **git submodules**
under `tools/`. Only a URL and one commit SHA are stored in this repository; the
source itself is never vendored, mixed into the MIT application or shipped in a
release.

| Submodule | Upstream | Pinned commit | Licence |
|---|---|---|---|
| `tools/rPPG-Toolbox` | <https://github.com/ubicomplab/rPPG-Toolbox> | `b7500b848f84ad7f86e277b4612563b69f4f88f9` | **RAIL-1.1** (non-commercial, behavioural restrictions) |
| `tools/pyVHR` | <https://github.com/phuselab/pyVHR> | `a6270f04a97f05a13d145dd0a5e8c8df48d8bd62` | **GPL-3.0** |
| `tools/ConjunctivaHb` | <https://github.com/stzifkas/ConjunctivaHb> | `a0d6e1938b7b43b950a57dc710f8d353a084d5ed` | inspected, **not integrated** |
| `tools/ViT-Anemia-Detection` | <https://github.com/Oscar-RamosS/ViT-Anemia-Detection> | `86fc1465bcf5a9ba4afecdda4564563ea4ff728c` | inspected, **not integrated** |
| `tools/mediapipe` | <https://github.com/google-ai-edge/mediapipe> | `07b4da024346f8a86c0496dd077ca1b2e4ab2c32` | Apache-2.0 (reference only; the browser uses the npm package) |

`tests/test_submodules.py` asserts these properties offline: every submodule is an
HTTPS gitlink (mode `160000`), no upstream file is tracked inside one, the
rPPG-Toolbox gitlink equals the adapter's `PINNED_COMMIT`, and the adapters still
cross a subprocess boundary instead of importing upstream code.

## Why submodules rather than a copy

1. **Licence isolation.** RAIL-1.1 restricts commercial use and pyVHR is GPL-3.0.
   Both are incompatible with vendoring into an MIT application. A submodule is a
   pointer, not a copy: `git clone` without `--recurse-submodules` never fetches
   them, and nothing from them is compiled into the product.
2. **Reproducibility.** Each is pinned to an exact commit, so a benchmark that
   cites rPPG-Toolbox names the revision that produced the numbers.
3. **Size.** `tools/rPPG-Toolbox` is ~353 MB and `tools/pyVHR` ~137 MB checked
   out. Neither belongs in this repository's history.

## Usage

Nothing is required for the application or CI. Initialise only what a specific
external benchmark needs:

```bash
# Fetch the pinned revisions (no build, no dependencies)
git submodule update --init --depth 1 tools/rPPG-Toolbox tools/pyVHR
```

Then point the existing adapter at the checkout - the adapters locate external
code by environment variable and run it in a **separate interpreter**
(`docs/RESEARCH_BACKENDS.md`), never by importing it:

```bash
export RSBVP_RPPG_TOOLBOX_PATH="$PWD/tools/rPPG-Toolbox"
export RSBVP_RPPG_TOOLBOX_PYTHON=/path/to/that/env/bin/python   # its own env

export RSBVP_PYVHR_PATH="$PWD/tools/pyVHR"
export RSBVP_PYVHR_PYTHON=/path/to/that/env/bin/python
```

Each upstream project needs its own dependency environment; do not install their
packages into the RSBVP deployment environment (`.venv`), which the deploy scripts
manage.

## What has and has not been run

| Check | Status |
|---|---|
| Submodules declared and pinned | **DONE** - verified by `tests/test_submodules.py` |
| rPPG-Toolbox check fetched at the pinned commit | **DONE** - `git submodule update` checked out `b7500b84…` |
| rPPG-Toolbox adapter constants matched to the gitlink | **DONE** - asserted in tests |
| rPPG-Toolbox executed on a dataset | **NOT RUN** - no authorized dataset in this environment, and RAIL-1.1 restricts use to non-commercial research |
| pyVHR check fetched at the pinned commit | **DONE** |
| pyVHR executed on a dataset | **NOT RUN** - GPL-3.0 isolation is in place; no authorized run has been made |
| ConjunctivaHb / ViT-Anemia-Detection executed | **NOT RUN** - inspected for licence and scope only; see `docs/OPEN_SOURCE_LICENSE_REGISTER.md` |

Fetching a checkout is a **software** verification step. It is not evidence that
any upstream method reproduces, performs, or is clinically meaningful - none of
those claims exist in this repository.

## Adding a dataset

Submodules carry code, never data. Authorized recordings stay outside the
repository and are located through `RSBVP_DATA_ROOT` (`data/README.md`). The single
exception remains the bundled `data/rPPG-10.zip`, documented in the README.

## Test collection

`pytest.ini` pins collection to `tests/` and excludes `tools/`. The pinned
repositories ship their own suites which import triton, mamba and tensorflow and
expect a GPU; without that exclusion `python -m pytest -q` aborts with five
collection errors as soon as the submodules are checked out. The gate must stay
offline, dataset-free and GPU-free, so the exclusion lives in configuration
rather than in a skip inside upstream code we do not own.
`tests/test_submodules.py::test_submodule_trees_are_excluded_from_pytest_collection`
locks this in.
