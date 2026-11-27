"""Human-readable Markdown and machine-readable JSON reports.

Two rules govern the text produced here:

1. **Every number carries its n.** A table cell with an MAE and no count is a
   defect; the formatter refuses to emit one.
2. **The report restates its own limits.** The limitations travel with the numbers
   rather than in a separate document, because the numbers are what get copied out.

The Markdown is generated from the same :class:`EvaluationResult` as the JSON, and
``tests/test_validation_report.py`` checks that every metric present in the JSON
appears in the Markdown with the same value — a report that disagrees with its own
machine-readable output is worse than no report.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from research.validation.pipeline import EvaluationResult


def _fmt(value: Any, *, decimals: int = 2, unit: str = "") -> str:
    """Format a number, or say precisely why there is no number."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        text = f"{value:.{decimals}f}"
        return f"{text} {unit}".strip() if unit else text
    return str(value)


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


def _table(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(header) + " |",
             "|" + "|".join("---" for _ in header) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def _agreement_rows(block: dict) -> list[tuple[str, str]]:
    if not block or not block.get("available"):
        reason = (block or {}).get("reason", "no paired observations")
        return [("Not reported", str(reason))]
    rows = [
        ("Paired observations (n)", str(block["n_pairs"])),
        ("Mean absolute error", _fmt(block.get("mae_bpm"), unit="BPM")),
        ("Root mean square error", _fmt(block.get("rmse_bpm"), unit="BPM")),
        ("Bias (estimate − reference)", _fmt(block.get("bias_bpm"), unit="BPM")),
        ("Median absolute error", _fmt(block.get("median_absolute_error_bpm"), unit="BPM")),
        ("Error SD", _fmt(block.get("error_sd_bpm"), unit="BPM")),
    ]
    if block.get("loa_lower_bpm") is not None:
        rows.append(("95% limits of agreement",
                     f"{_fmt(block['loa_lower_bpm'])} … {_fmt(block['loa_upper_bpm'])} BPM"))
    else:
        rows.append(("95% limits of agreement", block.get("loa_note", "not reported")))
    rows += [
        ("Signed error p05 / p50 / p95",
         f"{_fmt(block.get('error_p05_bpm'))} / {_fmt(block.get('error_p50_bpm'))} / "
         f"{_fmt(block.get('error_p95_bpm'))} BPM"),
        ("Within ±3 BPM", _pct(block.get("within_3_bpm_fraction"))),
        ("Within ±5 BPM", _pct(block.get("within_5_bpm_fraction"))),
    ]
    if block.get("mae_ci95_bpm"):
        lo, hi = block["mae_ci95_bpm"]
        rows.append(("MAE bootstrap interval (windows)",
                     f"{_fmt(lo)} … {_fmt(hi)} BPM — **optimistic**, windows are not independent"))
    return rows


def render_markdown(result: EvaluationResult) -> str:
    data = result.as_dict()
    lines: list[str] = []

    synthetic = bool(data["input_is_synthetic"])
    if synthetic:
        lines.append("> ## ⚠️ SYNTHETIC TEST DATA — NOT VALIDATION\n>\n"
                     "> This report was generated from fixture files created to test the "
                     "evaluation code. It contains **no participant, no recording and no "
                     "measured value**. No number below is a result about RSBVP's accuracy.\n")

    lines.append("# RSBVP validation report\n")
    lines.append(f"- **Schema:** `{data['schema']}` (protocol `{data['protocol_version']}`)")
    lines.append(f"- **Generated:** {data['created_utc']}")
    lines.append(f"- **Session source:** `{data['inputs']['session_source']}`")
    lines.append(f"- **Session id:** `{data['inputs']['session_id'] or 'not in the export'}`")
    lines.append(f"- **Reference source:** `{data['inputs']['reference_source']}` "
                 f"({data['inputs']['reference_layout']} layout)")
    lines.append(f"- **Input is synthetic:** {'**YES**' if synthetic else 'no'}")
    if data["inputs"].get("stratum"):
        lines.append(f"- **Stratum:** {data['inputs']['stratum']}")

    # --- verdict up front -------------------------------------------------
    evaluation = data["metrics"]
    lines.append("\n## 1. What this evaluation can and cannot say\n")
    if not evaluation.get("evaluation_available"):
        lines.append(f"**Insufficient evidence.** {evaluation.get('reason', '')}\n")
    else:
        head = evaluation["headline_series"]
        agree = head.get("agreement", {})
        corr = head.get("correlation", {})
        lines.append(
            f"The consensus, all-region series was paired with the reference on "
            f"**{evaluation['n_paired_observations']} windows**. Over that subset the mean "
            f"absolute error is {_fmt(agree.get('mae_bpm'), unit='BPM')} with a bias of "
            f"{_fmt(agree.get('bias_bpm'), unit='BPM')}.\n")
        if corr.get("available"):
            lines.append(
                f"Pearson r is {_fmt(corr['pearson_r'], decimals=3)}. **That is a correlation, "
                "not agreement and not accuracy**: r is invariant to scale and offset, so a "
                "method that reads consistently high can correlate almost perfectly.\n")
        lines.append("These numbers describe the paired windows of this session. They are not a "
                     "claim about RSBVP in general, not a clinical validation, and not evidence "
                     "about any particular phone.\n")

    # --- validation -------------------------------------------------------
    lines.append("## 2. Input validation\n")
    summary = data["validation"]["summary"]
    lines.append(f"Worst finding: **{summary['worst']}** — "
                 f"{summary['by_severity']['reject']} blocking, "
                 f"{summary['by_severity']['warn']} warning, "
                 f"{summary['by_severity']['info']} informational.\n")
    if summary["by_code"]:
        lines.append(_table(("Code", "Count"),
                            [(code, count) for code, count in summary["by_code"].items()]))
    lines.append("\nInput problems are never repaired silently. A blocking finding stops the "
                 "evaluation, because numbers derived from input that failed its checks cannot be "
                 "trusted.\n")

    # --- synchronisation --------------------------------------------------
    lines.append("## 3. Synchronisation\n")
    lines.append(f"- **Time base declared:** `{data['sync']['settings']['time_base']}`")
    lines.append(f"- **Offset:** {_fmt(data['sync']['settings']['offset_s'], decimals=3, unit='s')}")
    lines.append(f"- **Overlap requirement:** "
                 f"{_pct(data['sync']['settings']['min_overlap_fraction'])} of the shorter span")
    lines.append(f"- **Provenance:** {data['sync']['offset_provenance'] or '—'}")
    coverage = data["sync"]["coverage"]
    lines.append("")
    lines.append(_table(("Alignment", "Windows"), [
        ("Considered", coverage["windows_considered"]),
        ("Paired with a reference", coverage["windows_paired"]),
        ("Unmatched (no reference coverage)", coverage["windows_unmatched_no_reference"]),
        ("Excluded before matching", coverage["windows_excluded"]),
    ]))
    if data["sync"]["unmatched_truncated"] or data["sync"]["excluded_truncated"]:
        lines.append("\n*(The per-window lists in the JSON are truncated; the counts above are not.)*")
    lines.append("\nNo offset is invented. If the time base is not declared, or no offset is "
                 "established, the evaluation refuses to run rather than assuming zero.\n")

    # --- accuracy ---------------------------------------------------------
    lines.append("## 4. Accuracy and agreement\n")
    lines.append(_table(("Statistic", "Value"), _agreement_rows(
        evaluation["headline_series"].get("agreement", {}))))
    lines.append("\nCoverage beside the accuracy, because an MAE over a few paired windows "
                 "describes only those windows:\n")
    cov = data["coverage"]
    lines.append(_table(("Coverage", "Value"), [
        ("Windows recorded", cov["windows_recorded"]),
        ("Accepted by the quality gates", cov["windows_accepted"]),
        ("Rejected", cov["windows_rejected"]),
        ("Paired with the reference", cov["windows_paired"]),
        ("Independent (non-overlapping) paired", cov["independent_windows_paired"]),
        ("Acceptance rate", _pct(cov["acceptance_rate"])),
        ("Acceptance band", cov["acceptance_band"] or "—"),
        ("Density ratio", _fmt(cov["density_ratio"], decimals=2)),
    ]))

    # --- methods ----------------------------------------------------------
    lines.append("\n## 5. Algorithm and ROI comparison\n")
    method_rows = []
    for method in data["methods"]:
        agreement = method.get("agreement", {})
        method_rows.append((
            method["label"],
            method["n_pairs"],
            _fmt(agreement.get("mae_bpm")),
            _fmt(agreement.get("bias_bpm")),
            _pct(method.get("coverage", {}).get("windows_paired", 0)
                 / max(method.get("coverage", {}).get("windows_considered", 1), 1)),
        ))
    if method_rows:
        lines.append(_table(("Series", "n", "MAE (BPM)", "Bias (BPM)", "Coverage"),
                            method_rows))
    else:
        lines.append("No method series could be scored.")
    comparisons = data["comparison"].get("comparisons", [])
    if comparisons:
        lines.append("\n### Like-for-like comparison\n")
        for comparison in comparisons:
            lines.append(f"**{comparison['left']} vs {comparison['right']}** — "
                         f"verdict: `{comparison['verdict']}`\n")
            lines.append(_table(("Figure", "Left", "Right"), [
                ("n paired", comparison["shared_windows"],
                 f"{comparison['left_only_windows']} / {comparison['right_only_windows']} "
                 "exclusive"),
                ("MAE on own subset", _fmt(comparison["left_mae_own_subset_bpm"]),
                 _fmt(comparison["right_mae_own_subset_bpm"])),
                ("MAE on shared subset", _fmt(comparison["left_mae_shared_subset_bpm"]),
                 _fmt(comparison["right_mae_shared_subset_bpm"])),
            ]))
            lines.append(f"\n{comparison['explanation']}\n")
    else:
        lines.append("\n" + data["comparison"].get("note", ""))

    # --- session aggregation ---------------------------------------------
    lines.append("\n## 6. Does the session average improve agreement?\n")
    aggregation = data["session_aggregation"]
    if not aggregation.get("available"):
        lines.append(f"Not evaluated: {aggregation.get('reason', '')}\n")
    else:
        comparison = aggregation["comparison"]
        lines.append(_table(("Quantity", "Value", "n"), [
            ("Individual window MAE", _fmt(comparison["individual_mae_bpm"], unit="BPM"),
             aggregation["n_windows"]),
            ("Individual window |error| p95",
             _fmt(comparison["individual_error_p95_bpm"], unit="BPM"), aggregation["n_windows"]),
            ("Session mean |error|", _fmt(comparison["session_mean_abs_error_bpm"], unit="BPM"), 1),
            ("Session median |error|", _fmt(comparison["session_median_abs_error_bpm"], unit="BPM"), 1),
            ("Independent windows", aggregation["n_independent_windows"], "—"),
        ]))
        lines.append(f"\n**Verdict: `{comparison['verdict']}`**\n")
        lines.append(f"{comparison['explanation']}\n")
        lines.append("\nOutliers were **not** removed. The session mean includes every accepted "
                     "window; the median is reported beside it because it is not pulled by a "
                     "single unusual window. Neither is more correct.\n")

    # --- stratification ---------------------------------------------------
    lines.append("## 7. Stratification\n")
    stratification = data["stratification"]
    lines.append(stratification.get("note", "") + "\n")
    for key in ("condition", "device", "participant"):
        block = stratification.get(key) or {}
        if block and list(block) != ["unknown"]:
            lines.append(f"\n**By {key}**\n")
            lines.append(_table((key, "n", "MAE (BPM)", "Bias (BPM)"),
                                [(value, detail["n"], _fmt(detail["mae_bpm"]),
                                  _fmt(detail["bias_bpm"]))
                                 for value, detail in block.items()]))

    # --- findings and limitations ----------------------------------------
    lines.append("\n## 8. Findings\n")
    for finding in data["findings"]:
        location = ""
        if finding.get("source"):
            location = f" ({finding['source']}"
            location += f" row {finding['row']}" if finding.get("row") else ""
            location += ")"
        lines.append(f"- `{finding['severity']}` **{finding['code']}**{location}: "
                     f"{finding['message']}")
    if not data["findings"]:
        lines.append("No findings.")

    lines.append("\n## 9. Limitations\n")
    for limitation in data["limitations"]:
        lines.append(f"- {limitation}")

    lines.append("\n## 10. Reproducibility\n")
    reproducibility = data["reproducibility"]
    lines.append(f"- **Protocol:** `{reproducibility['protocol_version']}`")
    lines.append(f"- **Python:** {reproducibility['python']} · **numpy:** "
                 f"{reproducibility['numpy']}")
    lines.append(f"- **Bootstrap seed:** {reproducibility['bootstrap_seed']}")
    lines.append("- **Input digests (SHA-256):**")
    for name, digest in reproducibility["input_digests"].items():
        lines.append(f"  - `{name}`: `{digest or 'not supplied'}`")
    lines.append(f"\n```python\n{reproducibility['reproduce_with']}\n```\n")
    lines.append("Synchronisation settings for that call:\n")
    lines.append("```json\n" + json.dumps(reproducibility["sync_settings"], indent=2) + "\n```")
    lines.append("")
    return "\n".join(lines)


def write_reports(result: EvaluationResult, out_dir: Path, *, stem: str = "validation") -> dict:
    """Write ``<stem>.json``, ``<stem>.md`` and any figures. Returns the paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(json.dumps(result.as_dict(), indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(result), encoding="utf-8")

    figures: list[dict] = []
    try:
        from research.validation.plots import generate_all
        for index, figure in enumerate(generate_all(result, out_dir / "plots"), start=1):
            figures.append({"name": figure.name, "kind": figure.kind, "n": figure.n,
                            "path": str(figure.path.relative_to(out_dir))})
        if figures:
            md = md_path.read_text(encoding="utf-8")
            block = ["\n## Figures\n",
                     "Each figure carries its own sample count and limitation. "
                     "Synthetic figures are marked as such in the figure itself.\n"]
            for figure in figures:
                block.append(f"### {figure['name'].replace('_', ' ')} (n = {figure['n']})\n")
                block.append(f"![{figure['name']}]({figure['path']})\n")
            md_path.write_text(md + "\n".join(block) + "\n", encoding="utf-8")
    except ImportError:  # pragma: no cover - matplotlib is a declared dependency
        figures.append({"name": "plots_unavailable", "kind": "error", "n": 0,
                        "path": "matplotlib is not installed"})

    return {"json": json_path, "markdown": md_path, "figures": figures}
