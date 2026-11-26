# Manual browser camera verification procedure

These checks require a local camera and a supported browser. **No physical-camera
session has been performed for this repository** (Sprint 3, 11 or 12); this
document is a procedure, not a result. Automated browser tests with simulated
media streams are *software* tests and are recorded separately — see the table at
the end, which must never be read as physical validation. Do not record or retain another person's face without qualified oversight, consent, and privacy safeguards.

1. Serve the frontend on HTTPS (or localhost). In current Chrome and Firefox, open the live rPPG panel, deny camera permission, and confirm an explicit error and no estimate. Grant permission and confirm preview begins only after Start.
2. Confirm MediaPipe asset/model initialization success is visible via face/ROI tracking. Block or invalidate the model URL and confirm a recoverable error, camera tracks stop, and no stale BPM remains. In a compatible environment with GPU unavailable, verify CPU initialization fallback.
3. Center a consenting operator's face; verify forehead and bilateral cheek ROI overlays track landmarks. Move face out of view and back; verify face-lost/reacquisition states and that estimates remain unavailable until a fresh valid window.
4. Allow stable capture long enough for warm-up. Export CSV and inspect timestamp monotonicity, expected ROI columns, empty values for unavailable regions, and no image/frame payload. Do not treat the displayed estimate as a clinical measurement.
5. Test bright and low-light scenes, moderate head motion, temporary occlusion, and camera selection. Confirm quality gating invalidates unreliable results rather than forcing a number.
6. Stop capture and confirm the camera indicator turns off; restart and ensure duration, traces, and prior estimates do not carry into the new session.
7. Physically disconnect the camera during capture; confirm stream-ended error, tracks stopped, and estimates cleared. Repeat in the target browser/device matrix.
8. Inspect the browser network panel: camera frames should remain local; expected MediaPipe runtime/model assets may be fetched from configured URLs. No RGB traces should be sent to a backend unless the user explicitly exports/downloads them.
9. **Acquisition integrity (Sprint 12).** Watch the "Camera acquisition integrity" panel during a steady 30 s capture. Expect: effective ≈ mean rate, largest gap ≤ ~0.05 s, duplicate frames 0 %, regularity "Regular". Then deliberately provoke each condition and confirm the panel reports it and the measurement becomes unavailable (never a stale BPM):
   - **Duplicates:** open a second tab streaming the same camera, or use a 60 fps camera on a slow machine — duplicate percentage should rise above 2 % and the window must go `irregular_timestamps`.
   - **Stall:** move the browser window to the background for ~1 s (tab throttling) and back. A stall should be reported as a gap/irregularity.
   - **Low rate:** use a heavily loaded machine or a 640x480 capture under CPU pressure until the effective rate falls below 12 fps; the window must report insufficient sampling rate.
   - **Recovery:** with capture running, unplug a USB camera (or cover/disable it with the OS). Expect the interruption to be reported, the camera to be reopened with backoff, and after 4 failed attempts the message "Automatic recovery stopped after 4 attempts - press Start to try again". Never a silent freeze with a stale number.
   - **Reacquisition:** turn the face away for > 4 s and back; the buffer must reset and no estimate from the previous position may survive.
10. Record the measured numbers (effective fps, largest gap, duplicate %, recovery attempts) in the test record. These are measured acquisition properties, not accuracy figures.

## Software tests with simulated media (NOT physical validation)

These run in CI with a mocked media pipeline. They verify the *software* reacts
correctly; they cannot show that a real camera behaves this way.

| Scenario | Where it is covered |
|---|---|
| Permission denied → clear message, no socket opened | `gui/frontend/src/Live.test.tsx` |
| Insecure context (plain HTTP on another device) explained | `Live.test.tsx`, `browserCamera.ts` |
| Permission granted → local camera acquired, frames streamed | `Live.test.tsx` |
| Camera stream interruption / track ended | `BrowserPulse.test.tsx`, `captureIntegrity.test.ts` |
| Duplicate frames, stalls, low rate, irregular timing | `captureIntegrity.test.ts`, `tests/test_capture_integrity.py` |
| Browser/Python agreement on the same timestamps | `captureIntegrityParity.test.ts`, `tests/fixtures/capture_integrity_cases.json` |
| Recovery backoff schedule | `captureIntegrity.test.ts` |
| Face disappearance / reacquisition | `BrowserPulse.test.tsx` |
| Stop releases tracks, worker and MediaPipe | `BrowserPulse.test.tsx` |
| Device (camera) change and enumeration | `Live.test.tsx` |

Record browser/version, OS, camera model, lighting condition, and pass/fail outcomes in a non-identifying test record conforming to `rsbvp.camera-test-record.v1` — see `research/camera/manual_test_record.example.json` for the template and `docs/CAMERA_HARDWARE_VALIDATION.md` for the full session protocol. Validate each record with `python research/camera/validate_manual_test_record.py <record.json>` before filing it outside Git. Structural validity never attests that a session happened. Hardware checks are not physiological validation; synchronized reference evaluation is a separate protocol.
