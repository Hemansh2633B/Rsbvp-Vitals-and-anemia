# MediaPipe Face Landmarker assets: source, license, and runtime

## Software dependency

The browser imports `@mediapipe/tasks-vision`, declared as `^1.2.3` and resolved exactly by `gui/frontend/package-lock.json`. The npm package declares Apache License 2.0. Upstream source/license: [Google AI Edge MediaPipe](https://github.com/google-ai-edge/mediapipe) and [upstream LICENSE](https://github.com/google-ai-edge/mediapipe/blob/master/LICENSE). Browser WASM is loaded from the version-pinned jsDelivr path:

`https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.2.3/wasm`

## Model artifact

The default task file is Google's Face Landmarker `float16/1` artifact:

`https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task`

This repository does not bundle or redistribute the binary. The browser fetches it after the user requests camera access; image frames are not sent to the asset host or FastAPI. The artifact's specific license and redistribution conditions are separate from the npm package license. Their exact terms were not independently verified in this environment; deployers must confirm the published artifact terms before redistribution, self-hosting, or commercial use. No legal determination is implied.

## Configuration and failure behavior

`gui/frontend/.env.example` documents `VITE_MEDIAPIPE_WASM_URL` and `VITE_FACE_LANDMARKER_MODEL_URL`. These are public build-time URLs, never secrets. Deployments may configure reviewed/self-hosted copies. No fallback model is silently selected. If the URLs are unreachable or model initialization fails, the UI reports a visible error and shows no new BPM. Runtime external requests are listed in the UI and this document.

For production/offline deployment, mirror only assets with verified terms, record version and SHA-256, review transitive licenses, and make the build/deploy asset source explicit. Functional camera and supported-device validation is still required.

## Test posture (Sprint 8)

Failure and recovery paths carry mocked regression tests (`gui/frontend/src/rppg/BrowserPulse.test.tsx`): permission denial, missing camera hardware, GPU→CPU delegate fallback, face loss without a stale BPM, reacquisition buffer reset, hidden tab auto-stop, track termination + worker termination on stop, worker crash. These are software tests with stubbed APIs — they do not exercise a physical camera, a real WASM runtime, real model inference, or real reacquisition timing. Physical browser-camera testing per `docs/MANUAL_CAMERA_TESTS.md` remains **NOT RUN** and must be reported separately from unit-test results.
