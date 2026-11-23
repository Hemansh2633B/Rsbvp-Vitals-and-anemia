"""Standardized benchmark adapter for RSBVP research backends (Sprint 5).

This package defines one common interface for every rPPG research backend
that RSBVP can consult:

* ``rsbvp_native``    – the existing in-repository Python pipeline
                        (Green / POS / CHROM), imported read-only.
* ``rsbvp_reference`` – independent, from-the-literature reference
                        implementations written for this project
                        (GREEN, ICA, CHROM, POS, PBV).
* ``rppg_toolbox``    – OPTIONAL external subprocess adapter to the
                        UbiComp Lab rPPG-Toolbox (RAIL-1.1). Source is
                        never copied into this repository.
* ``pyvhr``           – OPTIONAL external subprocess adapter to pyVHR
                        (GPL-3.0). Runs in a separate environment.
* ``neural``          – checkpoint availability/provenance contract for
                        DeepPhys, PhysNet, TS-CAN, EfficientPhys and
                        PhysFormer via ``RSBVP_MODEL_ROOT``. Inference is
                        only ever delegated to the external toolbox.

Hard rules enforced here (see docs/RESEARCH_BACKENDS.md):

* timestamps, missing values and original sampling rates are preserved;
* no signal samples are ever fabricated and no units are silently altered;
* reference measurements are kept strictly separate from predictions;
* every record carries backend/version/model/configuration provenance.
"""
from __future__ import annotations

from .base import (
    BACKEND_RECORD_SCHEMA_VERSION,
    BackendError,
    BackendUnavailable,
    BackendInfo,
    BackendRunResult,
    RecordingInput,
    ResearchBackend,
    WindowResult,
    UnsupportedAlgorithm,
    iter_windows,
    configuration_hash,
)
from .schema import (
    BenchmarkRecord,
    BenchmarkWaveformSample,
    SchemaError,
    records_to_csv_rows,
    records_from_json,
    records_to_json,
    validate_record,
    waveform_samples_to_csv_rows,
    write_records_csv,
    write_records_json,
    write_waveforms_csv,
    read_records_json,
    read_records_csv,
)

__all__ = [
    "BACKEND_RECORD_SCHEMA_VERSION",
    "BackendError",
    "BackendUnavailable",
    "BackendInfo",
    "BackendRunResult",
    "RecordingInput",
    "ResearchBackend",
    "WindowResult",
    "UnsupportedAlgorithm",
    "iter_windows",
    "configuration_hash",
    "BenchmarkRecord",
    "BenchmarkWaveformSample",
    "SchemaError",
    "validate_record",
    "records_to_json",
    "records_from_json",
    "records_to_csv_rows",
    "waveform_samples_to_csv_rows",
    "write_records_csv",
    "write_records_json",
    "write_waveforms_csv",
    "read_records_json",
    "read_records_csv",
]

__version__ = "1.0.0"
