"""Registry of available research backends and their capabilities."""
from __future__ import annotations

from .native import NativeBackend
from .reference import ReferenceBackend
from .rppg_toolbox import RppgToolboxBackend, UNSUPERVISED_METHODS
from .pyvhr import PyVHRBackend, PYVHR_METHODS
from .neural import MODEL_REGISTRY, NeuralBaselineBackend, checkpoint_status

TRACE_BACKENDS = {
    "rsbvp_native": NativeBackend,
    "rsbvp_reference": ReferenceBackend,
}

EXTERNAL_BACKENDS = {
    "rppg_toolbox": RppgToolboxBackend,
    "pyvhr": PyVHRBackend,
}

NEURAL_MODELS = tuple(MODEL_REGISTRY)


def all_backend_names() -> list[str]:
    return list(TRACE_BACKENDS) + list(EXTERNAL_BACKENDS) + [f"neural_{m.lower()}" for m in NEURAL_MODELS]


def get_backend(name: str):
    key = name.lower()
    if key in TRACE_BACKENDS:
        return TRACE_BACKENDS[key]()
    if key in EXTERNAL_BACKENDS:
        return EXTERNAL_BACKENDS[key]()
    if key.startswith("neural_"):
        model = key[len("neural_"):]
        for known in NEURAL_MODELS:
            if known.lower() == model:
                return NeuralBaselineBackend(known)
        raise KeyError(f"unknown neural model {model!r}; known: {', '.join(m.lower() for m in NEURAL_MODELS)}")
    raise KeyError(f"unknown backend {name!r}; available: {', '.join(all_backend_names())}")


def snapshot() -> dict:
    entries: list[dict] = []
    for name in all_backend_names():
        backend = get_backend(name)
        usable, reason = backend.available()
        info = backend.info().as_dict()
        info.update({"available": bool(usable), "availability_reason": reason,
                     "algorithms": backend.supported_algorithms()})
        entries.append(info)
    neural = []
    for model in NEURAL_MODELS:
        ok, detail, path = checkpoint_status(model)
        neural.append({"model": model, "checkpoint_available": bool(ok), "detail": detail,
                       "checkpoint_path": str(path) if path else None})
    return {"backends": entries, "neural_checkpoints": neural}
