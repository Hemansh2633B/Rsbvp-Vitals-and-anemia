# Runtime and deployment

## Local research runtime

The FastAPI service controls the machine on which it runs. Current live camera acquisition through OpenCV and optional serial CMS50D access therefore require a trusted local machine with those devices attached. They do not access a remote user's webcam/serial port when deployed in the cloud. The React app communicates with relative `/api` and `/ws` paths through Vite in development.

From `gui/`, install Python dependencies using `uv sync` (Python >=3.12 per manifest), then run `uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000`. In a second terminal run `cd gui/frontend && npm ci && npm run dev -- --host 0.0.0.0`. Vite proxies APIs to local port 8000. The React live view now includes browser-side `getUserMedia()` acquisition and MediaPipe Face Landmarker. It requests access only after Start and stops tracks on Stop/unmount. Face frames are processed in the browser and are not sent to FastAPI. The WASM runtime is fetched from jsDelivr and the task model from the published Google Storage URL at start; those endpoints must be reachable and their asset versions/provenance should be reviewed before a production deployment. Camera permission requires HTTPS or localhost. The legacy local capture remains available separately.

## Vercel

The Vite frontend can be built with `cd gui/frontend && npm ci && npm run build`; deploy `gui/frontend` as the Vercel project root with build command `npm run build` and output directory `dist`. This frontend-only deployment does not provide persistent camera capture, serial access, or a long-running WebSocket worker. API-backed upload/live features require a separately hosted persistent backend and explicit `VITE_API_BASE_URL`/proxy and CORS design; do not assume the current relative endpoints work remotely without that configuration. Never expose secrets in Vite variables.

No remote backend deployment or hardware test was performed in this environment.
