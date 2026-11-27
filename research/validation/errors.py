"""Findings, severities and the single rejection exception type.

Validation is not a boolean. A finding has a severity, a stable machine-readable
code, the input it came from, and a human-readable message that says what the
reader can do about it. Evaluation refuses to run on ``REJECT`` findings and
proceeds (with the warnings carried into the report) on ``WARN``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence


class Severity(str, Enum):
    """Ordered by seriousness; ``rank`` exists so sorting is explicit."""

    INFO = "info"
    WARN = "warn"
    REJECT = "reject"


_SEVERITY_RANK = {Severity.INFO: 0, Severity.WARN: 1, Severity.REJECT: 2}

# Re-exported for callers that prefer the short names.
INFO = Severity.INFO
WARN = Severity.WARN
REJECT = Severity.REJECT


def severity_rank(severity: Severity) -> int:
    return _SEVERITY_RANK[severity]


@dataclass(frozen=True)
class InputFinding:
    """One observation about the input data.

    ``code`` is stable and machine-readable so a script can react to it;
    ``message`` is what a researcher reads. ``field`` and ``row`` locate the
    problem in the input, because "invalid timestamp" is not actionable without
    knowing which row.
    """

    severity: Severity
    code: str
    message: str
    source: str = ""
    field_name: str | None = None
    row: int | None = None
    count: int | None = None

    def as_dict(self) -> dict:
        payload: dict = {"severity": self.severity.value, "code": self.code, "message": self.message}
        if self.source:
            payload["source"] = self.source
        if self.field_name:
            payload["field"] = self.field_name
        if self.row is not None:
            payload["row"] = self.row
        if self.count is not None:
            payload["count"] = self.count
        return payload


class InputRejection(Exception):
    """Raised when input cannot be evaluated at all.

    Carries every finding, not just the first: repairing an export is usually an
    iterative process and reporting one problem per run wastes the researcher's
    time.
    """

    def __init__(self, findings: Sequence[InputFinding], summary: str = "") -> None:
        self.findings = list(findings)
        blocking = [f for f in self.findings if f.severity is Severity.REJECT]
        self.summary = summary or (
            f"{len(blocking)} blocking input problem(s): "
            + "; ".join(sorted({f.code for f in blocking}))[:400]
        )
        super().__init__(self.summary)

    @property
    def codes(self) -> list[str]:
        return sorted({f.code for f in self.findings if f.severity is Severity.REJECT})


def worst_severity(findings: Sequence[InputFinding]) -> Severity:
    if not findings:
        return Severity.INFO
    return max((f.severity for f in findings), key=severity_rank)


def summarise_findings(findings: Sequence[InputFinding]) -> dict:
    """Counts by severity and by code — the shape the reports consume."""
    by_severity = {s.value: 0 for s in Severity}
    by_code: dict[str, int] = {}
    for finding in findings:
        by_severity[finding.severity.value] += 1
        by_code[finding.code] = by_code.get(finding.code, 0) + 1
    return {
        "worst": worst_severity(findings).value,
        "by_severity": by_severity,
        "by_code": dict(sorted(by_code.items())),
    }
