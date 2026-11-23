#!/usr/bin/env python3
"""Local-only readiness probe for a locally acquired UBFC-rPPG archive.

This tool performs NO downloads, NO uploads and NO physiological inference.
It inspects a directory the user has already obtained and reports facts about
its structure so a dataset-specific adapter can be configured *after*
inspection — never before. It deliberately avoids guessing:

* directory/file layout is reported as found, never assumed to match a template;
* ``ground_truth.txt`` layout is reported structurally (line count, per-line
  token counts, float parseability) without asserting which column means what;
* video frame count / FPS are reported as read via OpenCV when available, else
  reported as not inspected;
* the toolbox-consumable convention (``subject<n>/vid.avi`` + one-line BVP in
  ``ground_truth.txt``) is noted for reference only; conformance is reported,
  not enforced;
* the simple (8) vs realistic (42) subsets cannot be told apart from directory
  names and are NOT auto-assigned.

Outputs ``data_readiness.json`` and ``data_readiness.md`` next to the report
directory you choose (default: ``reports/research_validation/``). Raw archive
contents are never copied into the output.

Status codes: ``available_for_inspection`` (archive present and readable),
``not_available`` (directory missing/empty — the current state of this
workspace), ``invalid`` (path misconfigured). Exit codes: 0 = probe completed,
2 = usage/configuration error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SUBJECT_PATTERN = re.compile(r"^subject(\d+)$", re.IGNORECASE)
EXPECTED_VIDEO = "vid.avi"
EXPECTED_GROUND_TRUTH = "ground_truth.txt"


def _video_info(path: Path) -> dict:
    try:
        import cv2
    except ImportError:
        return {"opened": None, "frame_count": None, "fps": None,
                "note": "not inspected: OpenCV unavailable in this interpreter"}
    cap = cv2.VideoCapture(str(path))
    try:
        opened = bool(cap.isOpened())
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if opened else None
        fps = float(cap.get(cv2.CAP_PROP_FPS)) if opened else None
        return {"opened": opened, "frame_count": frames, "fps": fps,
                "note": None if opened else "cv2 could not open the video file"}
    finally:
        cap.release()


def _ground_truth_info(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"readable": False, "error": f"{type(exc).__name__}: {exc}"}
    lines = text.splitlines()
    info: dict[str, object] = {
        "readable": True,
        "line_count": len(lines),
        "line_token_counts": [len(line.split()) for line in lines[:8]],
        "first_line_float_tokens_parseable": None,
        "first_line_sample_count": None,
        "total_bytes": path.stat().st_size,
        "notes": [],
    }
    if lines:
        tokens = lines[0].split()
        try:
            values = [float(tok) for tok in tokens]
        except ValueError:
            info["first_line_float_tokens_parseable"] = False
            info["notes"].append(
                "first line does not parse as space-separated floats; column semantics "
                "are UNKNOWN — inspect against the provider's documentation before use"
            )
        else:
            info["first_line_float_tokens_parseable"] = True
            info["first_line_sample_count"] = len(values)
            if any(v != v or v in (float("inf"), float("-inf")) for v in values):
                info["notes"].append("first line contains NaN/Inf tokens")
    else:
        info["notes"].append("file is empty")
    info["notes"].append(
        "Column semantics, units, sampling rate and clock synchronization are NOT inferred "
        "by this probe. Verify against the official documentation and Bobbia et al. 2017 "
        "before any analysis."
    )
    return info


def probe(archive_dir: Path, *, generated_note: str | None = None) -> dict:
    report: dict[str, object] = {
        "schema": "rsbvp.ubfcrppg-readiness.v1",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_note": generated_note,
        "archive_dir": str(archive_dir),
        "status": "available_for_inspection",
        "subset_assignment": "NOT DETERMINED — simple (8) vs realistic (42) subsets cannot "
                             "be told apart from directory names; obtain the subset list "
                             "from the provider or dataset documentation",
        "recordings": [],
        "problems": [],
        "summary": {},
    }
    if not archive_dir.is_dir():
        report["status"] = "not_available"
        report["problems"].append(f"archive directory does not exist: {archive_dir}")
        report["summary"] = {"subject_dirs": 0, "complete_pairs": 0}
        return report

    candidates = sorted(
        (entry for entry in archive_dir.iterdir() if entry.is_dir() and SUBJECT_PATTERN.match(entry.name)),
        key=lambda entry: int(SUBJECT_PATTERN.match(entry.name).group(1)),
    )
    if not candidates:
        report["status"] = "not_available"
        report["problems"].append(
            f"no subject* directories found under {archive_dir}; archive is absent, unpacked "
            "elsewhere, or laid out differently. Do NOT rearrange it to match a template; "
            "inspect the provider documentation first."
        )
        report["summary"] = {"subject_dirs": 0, "complete_pairs": 0}
        return report

    complete_pairs = 0
    for entry in candidates:
        video = entry / EXPECTED_VIDEO
        truth = entry / EXPECTED_GROUND_TRUTH
        item: dict[str, object] = {"recording_id": entry.name, "path": str(entry)}
        entry_problems: list[str] = []

        if video.is_file():
            item["video_bytes"] = video.stat().st_size
            item["video"] = _video_info(video)
        else:
            item["video"] = None
            entry_problems.append(f"missing {EXPECTED_VIDEO}")

        if truth.is_file():
            item["ground_truth"] = _ground_truth_info(truth)
        else:
            item["ground_truth"] = None
            entry_problems.append(f"missing {EXPECTED_GROUND_TRUTH}")

        video_info = item["video"] or {}
        gt = item["ground_truth"] or {}
        frames = video_info.get("frame_count")
        samples = gt.get("first_line_sample_count")
        if frames and samples:
            item["bvp_samples_per_frame"] = round(samples / frames, 4)
            if abs(samples / frames - 1.0) > 0.05:
                entry_problems.append(
                    f"first-line float count ({samples}) differs from video frame count "
                    f"({frames}) by >5%; units/rates must be verified against the "
                    "official documentation before evaluation"
                )

        item["problems"] = entry_problems
        report["recordings"].append(item)
        if not entry_problems:
            complete_pairs += 1
        report["problems"].extend(f"{entry.name}: {problem}" for problem in entry_problems)

    report["summary"] = {
        "subject_dirs": len(candidates),
        "complete_pairs": complete_pairs,
        "incomplete": len(candidates) - complete_pairs,
        "expected_simple_subset": 8,
        "expected_realistic_subset": 42,
        "note": "Expected counts refer to the official subsets (simple: 8; realistic: 42 of 46). "
                "Which subset a local copy holds is not determinable from directory names.",
    }
    if complete_pairs == 0:
        report["status"] = "not_available"
    return report


def render_markdown(report: dict) -> str:
    lines = [
        "# UBFC-rPPG readiness probe",
        "",
        f"- Schema: `{report['schema']}`",
        f"- Generated (UTC): {report['generated_utc']}",
        f"- Archive directory: `{report['archive_dir']}`",
        f"- Status: **{report['status']}**",
        f"- Subset assignment: {report['subset_assignment']}",
        "",
        "> This probe performs no physiological inference and copies no raw data into this report.",
        "> Column semantics of `ground_truth.txt` are NOT inferred. Verify against the official",
        "> documentation and the citation below before any analysis.",
        "",
        "## Summary",
        "",
    ]
    summary = report.get("summary", {})
    for key, value in summary.items():
        lines.append(f"- {key}: {value}")
    problems = report.get("problems", [])
    lines += ["", "## Problems", ""]
    lines += [f"- {problem}" for problem in problems] or ["- none reported at scan time"]
    lines += ["", "## Per-recording detail", ""]
    for item in report.get("recordings", []):
        lines.append(f"### {item['recording_id']}")
        video = item.get("video")
        if video is None:
            lines.append("- video: **missing**")
        else:
            lines.append(f"- video: opened={video.get('opened')} frames={video.get('frame_count')} "
                         f"fps={video.get('fps')} bytes={item.get('video_bytes')}")
        gt = item.get("ground_truth")
        if gt is None:
            lines.append("- ground_truth.txt: **missing**")
        else:
            lines.append(f"- ground_truth.txt: lines={gt.get('line_count')} "
                         f"token_counts={gt.get('line_token_counts')} "
                         f"first_line_floats={gt.get('first_line_float_tokens_parseable')} "
                         f"first_line_sample_count={gt.get('first_line_sample_count')} "
                         f"bytes={gt.get('total_bytes')}")
            for note in gt.get("notes", []):
                lines.append(f"  - note: {note}")
        if "bvp_samples_per_frame" in item:
            lines.append(f"- first-line samples per video frame: {item['bvp_samples_per_frame']}")
        if item.get("problems"):
            for problem in item["problems"]:
                lines.append(f"- **problem:** {problem}")
        lines.append("")
    lines += [
        "## Citation",
        "",
        "S. Bobbia, R. Macwan, Y. Benezeth, A. Mansouri, J. Dubois, “Unsupervised skin tissue",
        "segmentation for remote photoplethysmography,” *Pattern Recognition Letters*, 2017.",
        "",
        "Official dataset page: https://sites.google.com/view/ybenezeth/ubfcrppg",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--archive-dir", type=Path, default=None,
                        help="Explicit path to the unpacked UBFC-rPPG archive "
                             "(default: $RSBVP_DATA_ROOT/ubfc-rppg)")
    parser.add_argument("--data-root", type=Path, default=None,
                        help="Data root override (default: RSBVP_DATA_ROOT env var)")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/research_validation"))
    args = parser.parse_args(argv)

    if args.archive_dir is not None:
        archive_dir = args.archive_dir.expanduser().resolve()
    else:
        import os
        raw = args.data_root if args.data_root is not None else os.environ.get("RSBVP_DATA_ROOT")
        if not raw:
            print("Set RSBVP_DATA_ROOT or pass --archive-dir; no implicit dataset path is used.",
                  file=sys.stderr)
            return 2
        archive_dir = Path(raw).expanduser().resolve() / "ubfc-rppg"

    report = probe(archive_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "data_readiness.json"
    md_path = args.output_dir / "data_readiness.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "subject_dirs": report["summary"].get("subject_dirs"),
                      "complete_pairs": report["summary"].get("complete_pairs"),
                      "report": str(md_path)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
