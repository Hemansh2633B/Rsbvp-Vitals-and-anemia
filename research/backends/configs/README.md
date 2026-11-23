# Research backend configuration templates

These YAML files are **examples** adapted from the UbiComp Lab rPPG-Toolbox
(`ubicomplab/rPPG-Toolbox` @ `b7500b848f84ad7f86e277b4612563b69f4f88f9`,
license **RAIL-1.1**):

- `UBFC-rPPG_UNSUPERVISED.example.yaml` ← `configs/infer_configs/UBFC-rPPG_UNSUPERVISED.yaml`
- `PURE_UBFC-rPPG_TSCAN_BASIC.example.yaml` ← `configs/infer_configs/PURE_UBFC-rPPG_TSCAN_BASIC.yaml`

They are kept only so the documented commands are copy-pastable. They are not
required for the in-process backends (`rsbvp_native`, `rsbvp_reference`) and
they are not wired into CI.

Before use:

1. Read `docs/RESEARCH_BACKENDS.md` (setup, authorization, fair comparison)
   and `docs/OPEN_SOURCE_LICENSE_REGISTER.md` (RAIL-1.1 obligations).
2. Copy the example to a scratch location outside git (or keep your copy
   untracked) and replace every `<PLACEHOLDER>`.
3. Never commit dataset paths, checkpoints (`*.pth`), preprocessed caches, or
   per-person data.
4. The rPPG-Toolbox remains an external tool: do not vendor its source into
   this repository.

The adapters (`research/backends/rppg_toolbox.py`, `research/backends/neural.py`)
can **generate** equivalent configs programmatically; you only need these
examples for manual reproduction.
