# Camera & Hardware Validation Infrastructure

**Status: NOT RUN. No physical-camera test has ever been executed in this repository.**
This document defines the harness for future supervised sessions. It does not,
by itself, provide any validation evidence, and no number recorded through it
is a clinical measurement until it has been reviewed under an institutional protocol.

Related documents:

- `docs/MANUAL_CAMERA_TESTS.md` — the detailed browser-camera manual procedure
  (permission, interruption, face loss, lighting, motion, background tab, device
  switch, worker failure, long session cleanup). Still **NOT PERFORMED**.
- `research/camera/validate_manual_test_record.py` + `manual_test_record.example.json` —
  structure validator and template for `rsbvp.camera-test-record.v1`.
- `tests/test_camera_record.py` — validator tests (CI-safe: structure only, no hardware).

## 1. What a manual session must record

Every session is captured as a single `rsbvp.camera-test-record.v1` JSON document
(see the example template). Fields, and why each matters:

| Field | Purpose |
|---|---|
| `session.operator_initials` | Non-identifying operator marker (≤8 chars). No full names. |
| `session.consent_confirmed` | Must be `true`. Self-test or overseen protocol only — never a patient. |
| `session.date_utc`, `site` | Traceability without PII. |
| `environment.browser(_version)`, `os`, `camera_model`, `camera_resolution`, `approx_fps`, `lighting`, `distance_cm_approx` | Reproduce the acquisition conditions; lighting/camera differences change the rPPG SNR. |
| `capture.duration_s`, `dropped_interval_fraction` | Feasibility / timing integrity. fps ≪ 30 limits bandwidth. |
| `capture.roi_availability.{forehead,left_cheek,right_cheek}` | Face/ROI visibility per region (`full`/`partial`/`lost`). |
| `capture.camera_interrupted`, `tab_hidden`, `device_switched` | Negative-control events; the gate must reject or blank, not fabricate. |
| `quality_gate.status`, `rejection_reasons[]`, `estimate_available`, `processing_latency_ms` | The gates behave as software, not as decoration: when conditions are unsuitable, output must be unavailable. |
| `reference.equipment` (`none`/`CMS50D`/`CMS50E`/`other`), `synchronized_capture` | Reference provenance. Absent a reference, only software-availability statements are permitted. |
| `result` (`pass`/`fail`/`partial`) | Honest session outcome; `fail` and `partial` are first-class results. |

## 2. Constraints (binding)

1. **No human-participant data in this repository.** Records embed no faces,
   frames, videos, or crops. The validator rejects records containing
   media/participant keys. Only self-tests or overseen protocols with consent.
2. **Physical camera validation stays NOT RUN until a supervised session exists.**
   Until then, every capability statement rooted in camera behaviour is labelled
   *software-tested* or *not evaluated*, never *validated*.
3. **No clinical claims.** A `pass` means the software behaved as specified in
   that run — it says nothing about diagnostic accuracy, sensitivity, or
   specificity for any condition.
4. **Thresholds are not tuned to make a session pass.** Gate constants are fixed
   and documented with their evidence tier (see `docs/RELIABILITY.md`); changing
   them requires a documented, evidence-backed proposal independent of any
   single fixture or session.
5. **Comparisons against a reference (e.g. CMS50D) are agreement checks**, not
   truth adjudication; both devices measure different physiological quantities
   (peripheral optical flow vs. pulse waveform) and disagreement must be
   reported, not averaged away.

## 3. Repeatable manual checklist (per session)

1. Confirm consent basis and record operator initials, date, site.
2. Record environment: browser, OS, camera, resolution, lighting, approx. distance.
3. Run `docs/MANUAL_CAMERA_TESTS.md` procedures in order: permission denied path,
   normal capture, face occlusion/loss, lighting change, subject motion,
   background tab, device unplug/switch, worker failure, ≥10-minute long session.
4. For each procedure, record: roi_availability, dropped_interval_fraction,
   quality_gate status/reasons, estimate_available, observed latency; note any
   unexpected behaviour verbatim in `notes`.
5. If a CMS50D (or other reference) is used, record `reference.equipment` and
   `synchronized_capture`; otherwise record `none`.
6. Validate the record:
   `python research/camera/validate_manual_test_record.py path/to/record.json`
7. File the record **outside** Git (e.g. institutional storage) and link only
   the record's SHA-256 and schema in the PR; never commit participant media.

## 4. What remains NOT RUN

Until step 3–6 above have actually happened on real hardware:

- No statement that the live browser pathway estimates heart rate accurately.
- No statement that gates behave correctly on physical cameras (they are only
  covered by unit tests with mocked media devices).
- No CMS50D agreement numbers. None exist anywhere in this project.

See `docs/REMAINING_EXTERNAL_REQUIREMENTS.md` for the full blocked list.
