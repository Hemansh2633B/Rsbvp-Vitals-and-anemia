# Manual browser camera verification procedure

These checks require a local camera and a supported browser. They were **not performed** for Sprint 3; this document is a procedure, not a result. Do not record or retain another person's face without qualified oversight, consent, and privacy safeguards.

1. Serve the frontend on HTTPS (or localhost). In current Chrome and Firefox, open the live rPPG panel, deny camera permission, and confirm an explicit error and no estimate. Grant permission and confirm preview begins only after Start.
2. Confirm MediaPipe asset/model initialization success is visible via face/ROI tracking. Block or invalidate the model URL and confirm a recoverable error, camera tracks stop, and no stale BPM remains. In a compatible environment with GPU unavailable, verify CPU initialization fallback.
3. Center a consenting operator's face; verify forehead and bilateral cheek ROI overlays track landmarks. Move face out of view and back; verify face-lost/reacquisition states and that estimates remain unavailable until a fresh valid window.
4. Allow stable capture long enough for warm-up. Export CSV and inspect timestamp monotonicity, expected ROI columns, empty values for unavailable regions, and no image/frame payload. Do not treat the displayed estimate as a clinical measurement.
5. Test bright and low-light scenes, moderate head motion, temporary occlusion, and camera selection. Confirm quality gating invalidates unreliable results rather than forcing a number.
6. Stop capture and confirm the camera indicator turns off; restart and ensure duration, traces, and prior estimates do not carry into the new session.
7. Physically disconnect the camera during capture; confirm stream-ended error, tracks stopped, and estimates cleared. Repeat in the target browser/device matrix.
8. Inspect the browser network panel: camera frames should remain local; expected MediaPipe runtime/model assets may be fetched from configured URLs. No RGB traces should be sent to a backend unless the user explicitly exports/downloads them.

Record browser/version, OS, camera model, lighting condition, and pass/fail outcomes in a separate non-identifying test log. Hardware checks are not physiological validation; synchronized reference evaluation is a separate protocol.
