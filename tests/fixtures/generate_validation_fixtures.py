"""Generate deterministic synthetic session/reference fixtures for *testing the code*.

These fixtures exist to exercise parsing, alignment and statistics. They are NOT
data, and every artefact produced from them carries ``synthetic`` in its filename
and ``input_is_synthetic: true`` in its JSON, so a synthetic result cannot be
mistaken for a validated one. The values are chosen by construction; nothing here
resembles a real participant.

Run only when the fixture design changes:
    python tests/fixtures/generate_validation_fixtures.py
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "validation"
OUT.mkdir(parents=True, exist_ok=True)

#: A 10 s analysis window every 0.5 s for 60 s = 101 windows, overlapping by design.
WINDOW_S = 10.0
STEP_S = 0.5
DURATION_S = 60.0

#: The reference follows a slow ramp so that drift and non-stationarity are
#: representable: a session mean that ignores drift must look worse than the median.
REFERENCE_START_BPM = 62.0
REFERENCE_END_BPM = 78.0


def reference_bpm(t: float) -> float:
    return REFERENCE_START_BPM + (REFERENCE_END_BPM - REFERENCE_START_BPM) * (t / DURATION_S)


def write(name: str, text: str) -> None:
    path = OUT / name
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path} ({path.stat().st_size} B)  [SYNTHETIC]")


def session_csv(*, oracle: str = "good", duplicate_windows: int = 0,
                include_estimators: bool = True) -> str:
    """Build a readings CSV in the exact column order the application writes.

    ``oracle`` selects a deterministic error pattern; it is not a model of rPPG, it
    is a way to place known error into the fixture so the statistics can be checked
    against arithmetic that is worked out by hand.
    """
    header = [
        "reading_id", "metric", "unit", "value", "algorithm", "roi", "accepted",
        "rejection_reason", "quality_score", "quality_verdict", "sampling_rate_hz",
        "n_samples", "window_start_s", "window_end_s", "session_elapsed_s",
        "window_index", "recorded_utc",
    ]
    rows: list[list[str]] = []
    reading_id = 1
    window_index = 1
    n_windows = int(round((DURATION_S - WINDOW_S) / STEP_S)) + 1
    for i in range(n_windows):
        start = i * STEP_S
        end = start + WINDOW_S
        # The window's own reference is the value at its centre.
        centre = 0.5 * (start + end)
        truth = reference_bpm(centre)

        if oracle == "good":
            error = 1.5 if i % 7 == 0 else (-1.0 if i % 5 == 0 else 0.5)
        elif oracle == "biased":
            error = 8.0
        elif oracle == "drifting":
            error = -6.0 + 12.0 * (i / max(n_windows - 1, 1))
        else:  # pragma: no cover - guard
            raise ValueError(oracle)

        # Every fifth window is rejected by the quality gates, so rejection rate and
        # coverage are exercised. Rejected windows still carry a value in this
        # fixture only where the app would too: it emits the estimate with a failing
        # verdict, and the shared rule refuses to count it.
        rejected = i % 5 == 4
        verdict = "low_signal_quality" if rejected else "valid"
        reason = "low_signal_quality" if rejected else ""
        accepted = "false" if rejected else "true"
        value = "" if rejected else f"{truth + error:.3f}"

        rows.append([
            str(reading_id), "heart_rate", "BPM", value, "consensus", "all", accepted,
            reason, "0.62" if not rejected else "0.21", verdict, "30", "300",
            f"{start:.3f}", f"{end:.3f}", f"{start:.3f}", str(window_index),
            f"2026-01-01T00:00:{min(59, reading_id):02d}.000Z",
        ])
        reading_id += 1
        window_index += 1

        if include_estimators and not rejected and i % 3 == 0:
            for offset, method in ((0.0, "green"), (1.7, "pos"), (-2.4, "chrom")):
                for roi in ("forehead", "left_cheek", "right_cheek"):
                    rows.append([
                        str(reading_id), "heart_rate", "BPM", f"{truth + error + offset:.3f}",
                        method, roi, "true", "", "0.55", "valid", "30", "300",
                        f"{start:.3f}", f"{end:.3f}", f"{start:.3f}", str(window_index - 1),
                        f"2026-01-01T00:00:{min(59, reading_id):02d}.000Z",
                    ])
                    reading_id += 1

    # Duplicates: the same window re-emitted, which the shared rule must refuse.
    # A duplicate is the *same window emitted twice with a real estimate*, which is
    # what a double-render or a replayed frame actually produces. An earlier version
    # of this fixture emitted the copy with an empty value, which made it land in
    # "valid verdict without an estimate" and never exercise duplicate suppression
    # at all: the fixture passed while the rule it was meant to test was untested.
    for k in range(duplicate_windows):
        start = k * STEP_S
        original = next(
            (row for row in rows
             if row[4] == "consensus" and row[6] == "true"
             and abs(float(row[12]) - start) < 1e-9),
            None,
        )
        if original is None:
            continue
        rows.append([
            str(reading_id), "heart_rate", "BPM", original[3], "consensus", "all", "false",
            "duplicate_window", original[8], "valid", "30", "300",
            f"{start:.3f}", f"{start + WINDOW_S:.3f}", f"{start:.3f}", original[15],
            "2026-01-01T00:00:59.000Z",
        ])
        reading_id += 1

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def reference_csv() -> str:
    """Interval-layout reference covering the same 60 s."""
    lines = ["start_s,end_s,bpm,device,condition"]
    step = 2.0
    for start in range(0, int(DURATION_S), int(step)):
        end = start + step
        centre = 0.5 * (start + end)
        lines.append(f"{start},{end},{reference_bpm(centre):.3f},SYNTHETIC-ref,still_indoor")
    return "\n".join(lines) + "\n"


def reference_samples_csv() -> str:
    """Sample-layout reference, to test resampling."""
    lines = ["t_s,bpm,device,condition"]
    for second in range(0, int(DURATION_S) + 1):
        lines.append(f"{second},{reference_bpm(second):.3f},SYNTHETIC-ref,still_indoor")
    return "\n".join(lines) + "\n"


def main() -> None:
    note = (
        "# SYNTHETIC TEST FIXTURES - NOT DATA, NOT VALIDATION\n\n"
        "Files in this directory are generated by\n"
        "`tests/fixtures/generate_validation_fixtures.py` to exercise the evaluation\n"
        "code's parsing, alignment and statistics. They contain no participant, no\n"
        "camera recording and no measured value. Any report produced from them must be\n"
        "labelled synthetic and must never be cited as evidence of accuracy.\n"
    )
    write("README.md", note)
    write("synthetic_session_good.csv", session_csv(oracle="good"))
    write("synthetic_session_biased.csv", session_csv(oracle="biased", include_estimators=False))
    write("synthetic_session_drifting.csv", session_csv(oracle="drifting", include_estimators=False))
    write("synthetic_session_duplicates.csv",
          session_csv(oracle="good", duplicate_windows=4, include_estimators=False))
    write("synthetic_reference_intervals.csv", reference_csv())
    write("synthetic_reference_samples.csv", reference_samples_csv())

    manifest = {
        "note": "SYNTHETIC test fixtures. Not data. Not validation. See README.md.",
        "synthetic": True,
        "generated_by": "tests/fixtures/generate_validation_fixtures.py",
        "design": {
            "window_s": WINDOW_S,
            "step_s": STEP_S,
            "duration_s": DURATION_S,
            "reference_ramp_bpm": [REFERENCE_START_BPM, REFERENCE_END_BPM],
            "rejected_every_nth_window": 5,
            "summary_json": "synthetic_session_summary_good.json accompanies the good "
                            "session CSV so the bundle path (readings + summary) is exercised",
            "oracles": {
                "good": "small alternating error, MAE ~1 BPM",
                "biased": "constant +8 BPM offset: excellent correlation, poor accuracy",
                "drifting": "-6 to +6 BPM ramp: averaging should not help",
            },
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'manifest.json'}  [SYNTHETIC]")


if __name__ == "__main__":
    main()
