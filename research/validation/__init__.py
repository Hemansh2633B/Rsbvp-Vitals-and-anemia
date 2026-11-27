"""Research validation platform: evaluation of RSBVP session exports against
independent reference measurements.

This package is deliberately separate from the live measurement path. Nothing here
is imported by ``gui/`` and nothing here can influence a number shown to a user.

Design rules, each enforced by a test:

* **No data is invented.** A missing dataset, a missing reference value or a short
  recording produces ``insufficient``, never a filled-in number.
* **Validation precedes evaluation.** Every input is checked and either accepted or
  rejected with a stated reason. Nothing is silently repaired.
* **Synchronisation is explicit.** A time offset is either supplied by the operator
  or derived by a documented, deterministic procedure — never guessed, never
  inferred from the estimates themselves.
* **Sample counts travel with every statistic.** No mean is reported without the
  number of paired observations behind it.
* **Correlation is not agreement, and agreement is not accuracy.** They are
  computed and labelled separately.
* **Overlapping windows are not independent observations**, and are never counted
  as if they were participants.
* **Synthetic fixtures are for testing the code, never for reporting performance.**
  Every artefact records whether its input was synthetic.

The rule engine (``metric_rules``) is shared with the TypeScript session layer so
the two cannot drift; ``tests/test_validation_parity.py`` pins that.
"""

from research.validation.errors import (
    REJECT,
    WARN,
    InputFinding,
    InputRejection,
    severity_rank,
)
from research.validation.loader import (
    LoadedSession,
    Reading,
    SessionExport,
    load_session_csv,
    load_session_json,
    load_session_bundle,
)
from research.validation.metric_rules import (
    CONSENSUS,
    DUPLICATE_WINDOW,
    MIN_ACCEPTED_READINGS,
    MIN_INDEPENDENT_WINDOWS,
    PLAUSIBLE_BPM,
    classify_reading,
    count_independent_windows,
    window_key,
)

__all__ = [
    "CONSENSUS",
    "DUPLICATE_WINDOW",
    "MIN_ACCEPTED_READINGS",
    "MIN_INDEPENDENT_WINDOWS",
    "PLAUSIBLE_BPM",
    "InputFinding",
    "InputRejection",
    "LoadedSession",
    "Reading",
    "REJECT",
    "SessionExport",
    "WARN",
    "classify_reading",
    "count_independent_windows",
    "load_session_bundle",
    "load_session_csv",
    "load_session_json",
    "severity_rank",
    "window_key",
]
