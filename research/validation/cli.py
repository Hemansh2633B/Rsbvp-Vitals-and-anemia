"""Command-line entry point.

    python -m research.validation evaluate \
        --readings rsbvp_session_readings_2026-11-27.csv \
        --summary  rsbvp_session_summary_2026-11-27.json \
        --reference reference.csv \
        --time-base capture_start --offset -1000.0 \
        --out reports/validation

    python -m research.validation readiness
    python -m research.validation check --readings ... --reference ...

``check`` runs validation and alignment only, and prints what it found. It exists
because most failed evaluations are input problems, and a researcher should be able
to diagnose those without generating a report.

Exit codes: 0 success, 2 input rejected (with findings listed), 3 insufficient
evidence (the evaluation ran but could not support a conclusion).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from research.validation.alignment import SyncConfig, TimeBase, derive_offset
from research.validation.datasets import audit, readiness_summary
from research.validation.errors import InputRejection
from research.validation.pipeline import evaluate_session
from research.validation.report import write_reports


def _sync_from_args(args) -> SyncConfig:
    try:
        time_base = TimeBase(args.time_base)
    except ValueError:
        time_base = TimeBase.UNKNOWN
    offset = args.offset
    anchors = None
    if args.anchors:
        anchors = []
        for pair in args.anchors:
            try:
                session_s, reference_s = (float(part) for part in pair.split(","))
            except ValueError as exc:
                raise SystemExit(f"--anchors expects session_s,reference_s pairs; got {pair!r}") from exc
            anchors.append((session_s, reference_s))
        derived = derive_offset(anchors)
        if derived.established:
            offset = derived.offset_s
        else:
            print(f"offset derivation failed: {derived.reason}", file=sys.stderr)
            offset = None
    return SyncConfig(
        time_base=time_base,
        offset_s=offset,
        min_overlap_fraction=args.min_overlap,
        min_window_duration_s=args.min_window_s,
        evaluate_from_s=args.from_s,
        evaluate_to_s=args.to_s,
    ), anchors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m research.validation",
        description="Evaluate RSBVP session exports against an independent reference.")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_io(p):
        p.add_argument("--readings", type=Path, help="rsbvp_session_readings_*.csv")
        p.add_argument("--summary", type=Path, help="rsbvp_session_summary_*.json")
        p.add_argument("--reference", type=Path, required=True,
                       help="independent reference CSV (start_s,end_s,bpm or t_s,bpm)")
        p.add_argument("--time-base", default="unknown",
                       choices=[t.value for t in TimeBase],
                       help="what window_*_s is measured from; required for evaluation")
        p.add_argument("--offset", type=float, default=None,
                       help="reference_clock_s = window_start_s + offset. Not inferred.")
        p.add_argument("--anchors", action="append", metavar="SESSION_S,REFERENCE_S",
                       help="independent synchronisation anchor; repeatable. Derives the offset.")
        p.add_argument("--min-overlap", type=float, default=0.5)
        p.add_argument("--min-window-s", type=float, default=4.0)
        p.add_argument("--from-s", type=float, default=None, dest="from_s")
        p.add_argument("--to-s", type=float, default=None, dest="to_s")

    evaluate = sub.add_parser("evaluate", help="run a full evaluation and write reports")
    add_io(evaluate)
    evaluate.add_argument("--out", type=Path, default=Path("reports/validation"))
    evaluate.add_argument("--stem", default="validation")
    evaluate.add_argument("--stratum", default=None)
    evaluate.add_argument("--notes", default=None)

    check = sub.add_parser("check", help="validate inputs and alignment only")
    add_io(check)

    sub.add_parser("readiness", help="report dataset availability without downloading anything")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "readiness":
        statuses = audit()
        summary = readiness_summary(statuses)
        print(json.dumps({"summary": summary,
                          "datasets": [s.as_dict() for s in statuses]}, indent=2))
        return 0

    sync, anchors = _sync_from_args(args)
    try:
        result = evaluate_session(
            readings_csv=args.readings,
            summary_json=args.summary,
            reference_csv=args.reference,
            sync=sync,
            anchors=anchors,
            stratum=getattr(args, "stratum", None),
            notes=getattr(args, "notes", None),
        )
    except InputRejection as rejection:
        print("INPUT REJECTED — no evaluation was produced.", file=sys.stderr)
        for finding in rejection.findings:
            location = f" [{finding.source}" + (f" row {finding.row}" if finding.row else "") + "]"
            print(f"  {finding.severity.value:<6} {finding.code}: {finding.message}{location}",
                  file=sys.stderr)
        return 2

    if args.command == "check":
        data = result.as_dict()
        print(json.dumps({
            "validated": True,
            "input_is_synthetic": data["input_is_synthetic"],
            "alignment": data["sync"]["coverage"],
            "offset_provenance": data["sync"]["offset_provenance"],
            "findings": data["findings"],
        }, indent=2))
        return 0

    paths = write_reports(result, args.out, stem=args.stem)
    print(f"wrote {paths['json']}")
    print(f"wrote {paths['markdown']}")
    for figure in paths["figures"]:
        print(f"  figure: {figure['path']} (n={figure['n']})")

    data = result.as_dict()
    if not data["metrics"]["evaluation_available"]:
        print("\nINSUFFICIENT EVIDENCE: " + data["metrics"]["reason"], file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
