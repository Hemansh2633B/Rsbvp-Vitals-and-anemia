import { useEffect, useRef, useState } from 'react'
import { BrowserPulse } from './rppg/BrowserPulse'
import { SessionResult } from './rppg/SessionResult'
import { newSessionId } from './rppg/provenance'
import {
  CONSENSUS,
  SessionCollector,
  buildSessionAggregateExport,
  buildSessionReadingsCsv,
  summarizeSession,
  type SessionSummary,
} from './rppg/sessionAggregate'
import {
  listDevices,
  type Devices,
  type LiveEvaluation,
  type LiveState,
  type MotionSegment,
} from './api'
import {
  cameraContextAvailable,
  describeCameraError,
  INSECURE_CONTEXT_MESSAGE,
  listLocalCameras,
  startBrowserCamera,
  type BrowserCameraHandles,
} from './browserCamera'

type Mode = 'original' | 'segment'

function fmt(v: number | null | undefined, digits = 1, unit = '') {
  if (v === null || v === undefined) return '—'
  return `${v.toFixed(digits)}${unit ? ' ' + unit : ''}`
}

// Seconds -> "M:SS".
function clock(sec: number) {
  const s = Math.max(0, Math.round(sec))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

export function Live() {
  const [devices, setDevices] = useState<Devices | null>(null)
  const [mode, setMode] = useState<Mode>('original')
  // The camera always belongs to the device that opened this page. The server
  // never opens its own webcam for this pathway.
  const [cameras, setCameras] = useState<MediaDeviceInfo[]>([])
  const [deviceId, setDeviceId] = useState('')
  const [secureContext, setSecureContext] = useState(true)
  const [serialPort, setSerialPort] = useState<string>('')
  const [duration, setDuration] = useState(30)
  // Always on: recording writes the sync CSV the post-run 2×2 evaluation
  // dashboard is built from, so every live run produces its plots.
  const record = true

  const [running, setRunning] = useState(false)
  const [status, setStatus] = useState<string>('idle')
  const [error, setError] = useState<string | null>(null)
  const [frame, setFrame] = useState<string | null>(null)
  const [state, setState] = useState<LiveState | null>(null)
  const [segments, setSegments] = useState<MotionSegment[] | null>(null)
  const [evaluation, setEvaluation] = useState<LiveEvaluation | null>(null)

  // Same collector class as the browser pathway: one implementation of the
  // session statistics, two data sources. Readings are append-only.
  const collector = useRef(new SessionCollector())
  // Non-identifying id tying this session's exports together.
  const sessionIdRef = useRef(newSessionId())
  const sessionIdForExport = () => sessionIdRef.current
  const [session, setSession] = useState<SessionSummary>(() => summarizeSession([]))
  // Wall-clock arrival of each frame update, used for staleness: a frame that
  // arrives long after it describes a moment already past is not a current
  // observation.
  const framesSeen = useRef(0)
  const wsRef = useRef<WebSocket | null>(null)
  const cameraRef = useRef<BrowserCameraHandles | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)

  function selectMode(m: Mode) {
    if (running) return
    setMode(m)
    setDuration(m === 'segment' ? 120 : 30)
  }

  useEffect(() => {
    listDevices()
      .then((d) => {
        setDevices(d)
        if (d.cms_candidate) setSerialPort(d.cms_candidate)
      })
      // Only the serial ports come from the server now; the camera is local.
      .catch(() => setDevices({ serial_ports: [], cms_candidate: null, default_camera_index: 0 }))
    setSecureContext(cameraContextAvailable())
    listLocalCameras().then(setCameras).catch(() => setCameras([]))
    return () => {
      cameraRef.current?.stop()
      wsRef.current?.close()
    }
  }, [])

  async function start() {
    setError(null)
    setFrame(null)
    setState(null)
    setSegments(null)
    setEvaluation(null)
    // New run, new session: readings are never carried across sessions.
    collector.current.reset()
    framesSeen.current = 0
    sessionIdRef.current = newSessionId()
    setSession(summarizeSession([]))
    setStatus('opening camera…')

    // 1. Acquire the camera of THIS device. If the user denies it (or the page
    //    is not a secure context), say so plainly and never fall back to the
    //    server's webcam - that would measure the wrong person.
    const video = videoRef.current
    if (!video) {
      setError('The live preview element is not ready; reload the page.')
      setStatus('error')
      return
    }
    let handles: BrowserCameraHandles
    try {
      handles = await startBrowserCamera(video, {
        deviceId,
        fps: 30,
        width: 640,
        onFrame: (jpeg) => {
          const socket = wsRef.current
          if (socket && socket.readyState === WebSocket.OPEN) socket.send(jpeg)
        },
        onError: (message) => {
          setError(message)
          setStatus('error')
        },
      })
    } catch (err) {
      setError(describeCameraError(err))
      setStatus('error')
      return
    }
    cameraRef.current = handles
    // Camera permission granted: labels become readable, so refresh the list.
    listLocalCameras().then(setCameras).catch(() => setCameras([]))

    // 2. Then connect the socket that carries those frames to the measurement.
    setStatus('connecting…')
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/live`)
    wsRef.current = ws

    ws.onopen = () => {
      ws.send(
        JSON.stringify({
          // Explicit: the frames come from this browser, not the server host.
          camera_source: 'browser',
          camera_label: cameras.find((c) => c.deviceId === deviceId)?.label || 'this device',
          serial_port: serialPort || null,
          duration: duration || null,
          record,
          segment_mode: mode === 'segment',
        }),
      )
      setRunning(true)
    }

    ws.onmessage = (ev) => {
      const msg: LiveState = JSON.parse(ev.data)
      if (msg.type === 'started') {
        let cms = ''
        if (msg.serial_port) {
          if (msg.cms_streaming) cms = ' · CMS50D streaming'
          else if (msg.cms_connected) cms = ' · CMS50D port open, no data'
          else cms = ' · CMS50D failed'
        }
        const source = msg.camera_source === 'browser' ? 'this device' : 'host camera'
        setStatus(`live · ${source}${cms}${msg.recording ? ' · recording' : ''}`)
        if (msg.cms_error) setError(msg.cms_error)
      } else if (msg.type === 'frame') {
        if (msg.frame) setFrame(msg.frame)
        setState(msg)
        recordFrame(msg)
      } else if (msg.type === 'error') {
        setError(msg.detail ?? 'Unknown error')
        setStatus('error')
      } else if (msg.type === 'done') {
        setStatus('finished')
        if (msg.segments) setSegments(msg.segments)
        if (msg.evaluation) setEvaluation(msg.evaluation)
        if (msg.evaluation_error) setError(`Evaluation failed: ${msg.evaluation_error}`)
      }
    }

    ws.onerror = () => {
      setError('WebSocket connection failed.')
      cameraRef.current?.stop()
      cameraRef.current = null
    }
    ws.onclose = () => {
      cameraRef.current?.stop()
      cameraRef.current = null
      setRunning(false)
      if (status !== 'error') setStatus((s) => (s === 'live' || s.startsWith('live') ? 'finished' : s))
    }
  }

  function stop() {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'stop' }))
    }
    cameraRef.current?.stop()
    cameraRef.current = null
    // Reflect the stop immediately. Previously only the socket's onclose cleared
    // `running`, so the UI kept showing a Stop button and a live-looking status
    // until the server got round to closing - which on a slow phone link read as
    // "Stop did nothing".
    setRunning(false)
  }

  const warming = state?.warming_up ?? true
  const cmsConnected = state?.cms_connected ?? false

  // One server frame update -> readings. `consensus_hr` is the agreement-checked
  // estimate and is the only heart-rate value presented as a session result; the
  // per-estimator values (green/pos, FFT/peak) are recorded as their own series so
  // they are never averaged together as though interchangeable.
  function recordFrame(msg: LiveState) {
    framesSeen.current += 1
    const nowMs = Date.now()
    const shared = {
      qualityScore: typeof msg.green_reliability === 'number' ? msg.green_reliability : null,
      sampling: {
        fsHz: typeof msg.sampling_rate === 'number' ? msg.sampling_rate : null,
        nSamples: null,
        windowStartS: typeof msg.elapsed === 'number' ? Math.max(0, msg.elapsed - (msg.buffer_seconds ?? 0)) : null,
        windowEndS: typeof msg.elapsed === 'number' ? msg.elapsed : null,
      },
      analyzedAtMs: nowMs,
      sessionElapsedS: typeof msg.elapsed === 'number' ? msg.elapsed : null,
      windowIndex: framesSeen.current,
    }
    const verdict = msg.quality_status ?? 'unknown'
    const reason = msg.quality_reason ?? verdict
    // Heart rate: the consensus plus the individual estimator series.
    const hrSeries: Array<[string, number | null]> = [
      [CONSENSUS, msg.consensus_hr ?? null],
      ['green_fft', msg.hr_green_fft ?? null],
      ['pos_fft', msg.hr_pos_fft ?? null],
      ['green_peak', msg.hr_green_peak ?? null],
      ['pos_peak', msg.hr_pos_peak ?? null],
    ]
    for (const [algorithm, value] of hrSeries) {
      collector.current.add({
        metric: 'heart_rate', value, algorithm, roi: 'face',
        // The window verdict gates every series: an estimator is not more
        // trustworthy than the acquisition it came from.
        qualityVerdict: verdict,
        rejectionReason: verdict === 'valid' ? null : reason,
        ...shared,
      })
    }
    // Respiratory rate: only its own final estimate, and only when the window
    // verdict passed. Its gating already runs inside the same verdict.
    collector.current.add({
      metric: 'respiratory_rate', value: msg.rr_final ?? null, algorithm: 'welch+hilbert',
      roi: 'face', qualityVerdict: verdict,
      rejectionReason: verdict === 'valid' ? null : reason, ...shared,
    })
    setSession(summarizeSession(collector.current.all()))
  }

  function download(content: BlobPart, type: string, name: string) {
    const url = URL.createObjectURL(new Blob([content], { type }))
    const a = document.createElement('a')
    a.href = url
    a.download = name
    a.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  function exportSessionReadings() {
    const stamp = new Date().toISOString().replaceAll(':', '-')
    download(buildSessionReadingsCsv(collector.current.all()), 'text/csv', `rsbvp_session_readings_${stamp}.csv`)
  }

  function exportSessionAggregate() {
    const stamp = new Date().toISOString().replaceAll(':', '-')
    const out = buildSessionAggregateExport({
      sessionId: sessionIdForExport(),
      createdUtc: new Date().toISOString(),
      readings: collector.current.all(),
      summary: session,
      capture: {
        algorithms: ['Green', 'POS', 'CHROM (server pipeline)'],
        rois: ['face (server ROI)'],
        passbandHz: [0.7, 3.5],
        requiredSeconds: mode === 'segment' ? 10 : 12,
        backend: 'rsbvp-server-live',
        cameraLabel: cameras.find((c) => c.deviceId === deviceId)?.label ?? null,
        samplingRateHz: typeof state?.sampling_rate === 'number' ? state.sampling_rate : null,
      },
    })
    download(JSON.stringify(out, null, 2), 'application/json', `rsbvp_session_summary_${stamp}.json`)
  }

  return (
    <div className="live">
      <BrowserPulse />
      <section className="panel">
        <h2>Live capture (this device's camera)</h2>
        <p className="muted">
          Frames come from the camera on the device you are using now - a phone,
          tablet or another laptop measures its own camera, not the server's. The
          video is streamed to the analysing server over this connection; nothing
          is read from, or recorded by, any other machine's webcam.
        </p>
        <div className="live-controls">
          <label className="ctl">
            Camera
            <select
              value={deviceId}
              disabled={running}
              onChange={(e) => setDeviceId(e.target.value)}
            >
              <option value="">
                {cameras.length ? 'Default camera (this device)' : 'Default camera'}
              </option>
              {cameras.map((c, i) => (
                <option value={c.deviceId} key={c.deviceId || `cam-${i}`}>
                  {c.label || `Camera ${i + 1}`}
                </option>
              ))}
            </select>
          </label>
        </div>
        {!secureContext && (
          <div className="status error">
            {INSECURE_CONTEXT_MESSAGE}
          </div>
        )}
        <div className="live-video local-preview">
          <video ref={videoRef} autoPlay playsInline muted />
          {!running && (
            <div className="live-placeholder muted">
              The preview appears here once you press Start.
            </div>
          )}
        </div>
        <div className="mode-switch">
          <button
            className={mode === 'original' ? 'mode active' : 'mode'}
            disabled={running}
            onClick={() => selectMode('original')}
          >
            Original
            <span className="mode-sub">30s · single class</span>
          </button>
          <button
            className={mode === 'segment' ? 'mode active' : 'mode'}
            disabled={running}
            onClick={() => selectMode('segment')}
          >
            Motion segments
            <span className="mode-sub">2-min · per-segment HR</span>
          </button>
        </div>
        <div className="live-controls">
          <label className="ctl">
            CMS50D port
            <input
              list="cms-ports"
              value={serialPort}
              disabled={running}
              placeholder="e.g. COM5 — blank = camera-only"
              onChange={(e) => setSerialPort(e.target.value.trim())}
            />
            <datalist id="cms-ports">
              {devices?.serial_ports.map((p) => (
                <option key={p.device} value={p.device}>
                  {p.description} {p.candidate ? '★' : ''}
                </option>
              ))}
            </datalist>
          </label>

          {!running ? (
            <button className="primary" onClick={start}>
              Start
            </button>
          ) : (
            <button className="danger" onClick={stop}>
              Stop
            </button>
          )}
          <span className={`live-status ${status === 'error' ? 'err' : ''}`}>
            {status}
          </span>
        </div>
        {devices && devices.serial_ports.length === 0 && (
          <p className="muted small">
            No serial ports auto-detected. If your CMS50D is plugged in, just
            type its port name above (e.g. <code>COM5</code> on Windows, or
            <code> /dev/tty.usbserial-XXXX</code> on macOS) — same value the
            scripts used for <code>CMS50D_PORT</code>. Leave blank for
            camera-only.
          </p>
        )}
        {devices && devices.serial_ports.length > 0 && !serialPort && (
          <p className="muted small">
            {devices.serial_ports.length} serial port(s) detected (see the
            dropdown). Type or pick your CMS50D port above to enable SpO₂ /
            hardware HR — otherwise this runs camera-only.
          </p>
        )}
        {error && <div className="status error">Error: {error}</div>}
      </section>

      <section className="panel live-stage">
        <div className="live-video">
          {frame ? (
            <img src={frame} alt="processed frames as seen by the server" />
          ) : (
            <div className="live-placeholder muted">
              {running ? 'Waiting for measurements…' : 'Measurements appear after Start'}
            </div>
          )}
          {running && warming && (
            <div className="warm-badge">
              Warming up… {fmt(state?.buffer_seconds, 0)}s / {mode === 'segment' ? 10 : 12}s buffer
            </div>
          )}
          {running && mode === 'segment' && state?.position_state && (
            <div className={`pos-badge pos-${state.position_state}`}>
              {state.position_state}
              {state.motion_segment_id ? ` · seg ${state.motion_segment_id}` : ''}
            </div>
          )}
          {running && (
            <div className="live-timebar">
              <div className="live-time-text">
                <span className="live-elapsed">{clock(state?.elapsed ?? 0)}</span>
                {state?.fps != null && (
                  <span
                    className={`live-fps ${state.fps < 28 ? 'low' : ''}`}
                    title="Sustained processing FPS — the pipeline is tuned for the script's 30 FPS. Well below 30 means sparser motion samples and lower HR/motion quality."
                  >
                    {' · '}
                    {state.fps.toFixed(0)} fps
                  </span>
                )}
              </div>
              {duration > 0 && (
                <div className="live-progress">
                  <div
                    className="live-progress-fill"
                    style={{
                      width: `${Math.min(100, ((state?.elapsed ?? 0) / duration) * 100)}%`,
                    }}
                  />
                </div>
              )}
            </div>
          )}
        </div>

        <div className="live-metrics">
          <div className="metric-card" style={{ borderTopColor: '#C62828' }}>
            <div className="metric-label">Heart rate</div>
            <div className="metric-value">{fmt(state?.consensus_hr, 1, 'BPM')}</div>
            <div className="metric-sub muted">
              G {fmt(state?.hr_green_fft, 0)} · P {fmt(state?.hr_pos_fft, 0)}
            </div>
            {state?.quality_status && (
              <div className="metric-sub muted" role="status">
                {state.quality_status === 'valid'
                  ? 'quality checks passed'
                  : `unavailable: ${state.quality_reason ?? state.quality_status}`}
              </div>
            )}
            {state?.quality_concepts && (
              <div className="metric-sub muted">
                concepts:{' '}
                {Object.entries(state.quality_concepts)
                  .map(([k, v]) => `${k.replace(/_/g, ' ')}=${v}`)
                  .join(' · ')}
              </div>
            )}
          </div>
          <div className="metric-card" style={{ borderTopColor: '#2E7D32' }}>
            <div className="metric-label">Respiratory rate</div>
            <div className="metric-value">{fmt(state?.rr_final, 1, 'br/min')}</div>
            <div className="metric-sub muted">needs ≥20s</div>
          </div>
          <div className="metric-card" style={{ borderTopColor: '#1565C0' }}>
            <div className="metric-label">Motion</div>
            {/* Stable label: the committed segment's motion class, which only
                changes when a new segment is confirmed — so brief transient
                classifications don't flash up. Falls back to the raw per-update
                class while warming up or in original mode (already stable). */}
            <div className="metric-value sm">
              {state?.segment_motion_class ?? state?.motion_class ?? '—'}
            </div>
            <div className="metric-sub muted">
              {state?.face_detected ? 'face tracked' : 'no face'}
            </div>
          </div>
          <div className="metric-card" style={{ borderTopColor: '#6A1B9A' }}>
            <div className="metric-label">Reliability</div>
            <div className="metric-value sm">
              G {fmt(state?.green_reliability, 2)}
            </div>
            <div className="metric-sub muted">P {fmt(state?.pos_reliability, 2)}</div>
          </div>

          <div
            className={`metric-card oximeter ${cmsConnected ? '' : 'disabled'}`}
            style={{ borderTopColor: '#00838F' }}
          >
            <div className="metric-label">SpO₂ (CMS50D)</div>
            <div className="metric-value">
              {cmsConnected ? fmt(state?.spo2, 0, '%') : '—'}
            </div>
            <div className="metric-sub muted">
              {cmsConnected ? `HW HR ${fmt(state?.hardware_hr, 0)} BPM` : 'connect device'}
            </div>
          </div>
        </div>
      </section>

      {status === 'finished' && !evaluation && !error && (
        <section className="panel">
          <p className="muted small">
            No evaluation plots for this run — the recording was too short or no
            usable rPPG signal was captured. Try a longer run with your face
            clearly in frame.
          </p>
        </section>
      )}

      <SessionResult
        summary={session}
        sessionId={sessionIdRef.current}
        onExportReadings={exportSessionReadings}
        onExportAggregate={exportSessionAggregate}
        liveStatus={
          running
            ? `Live: ${state?.quality_status === 'valid' ? 'signal acceptable' : state?.quality_reason ?? 'waiting for a valid window'}`
            : null
        }
      />

      {segments && segments.length > 0 && (
        <section className="panel">
          <h2>Motion segments</h2>
          <p className="muted small">
            One row per continuous motion segment, each with its own median HR.
          </p>
          <table className="segments">
            <thead>
              <tr>
                <th>#</th>
                <th>Motion</th>
                <th>Window</th>
                <th>Duration</th>
                <th>HR (median)</th>
                <th>Device HR (median)</th>
                <th>RR (median)</th>
                <th>Samples</th>
                <th>Reliability G/P</th>
              </tr>
            </thead>
            <tbody>
              {segments.map((s) => (
                <tr key={s.id} className={s.low_samples ? 'low' : ''}>
                  <td>{s.id}</td>
                  <td>
                    <span className={`pill pill-${s.motion_class}`}>
                      {s.motion_class}
                    </span>
                  </td>
                  <td>
                    {s.start_sec}–{s.end_sec}s
                  </td>
                  <td>{s.duration_sec}s</td>
                  <td>{fmt(s.hr_median, 1, 'BPM')}</td>
                  <td>{fmt(s.device_hr_median, 1, 'BPM')}</td>
                  <td>{fmt(s.rr_median, 1)}</td>
                  <td>
                    {s.hr_count}
                    {s.low_samples ? ' ⚠' : ''}
                  </td>
                  <td>
                    {fmt(s.green_reliability_median, 2)} /{' '}
                    {fmt(s.pos_reliability_median, 2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {evaluation && evaluation.available && (
        <section className="panel">
          <h2>Recording evaluation</h2>
          {!evaluation.has_ground_truth && (
            <p className="muted small">
              No CMS50D ground truth in this recording — live-only panels are
              shown. Connect the oximeter to populate the GT comparison
              (Bland-Altman, correlation, per-segment error, SpO₂).
            </p>
          )}

          {evaluation.summary && (
            <div className="metric-grid eval-grid">
              <Stat label="GT median HR" v={evaluation.summary.GT_Median_HR} u="BPM" />
              <Stat label="Live rPPG median" v={evaluation.summary.Live_rPPG_HR_Median} u="BPM" />
              <Stat label="MAE" v={evaluation.summary.MAE} u="BPM" />
              <Stat label="MAPE" v={evaluation.summary.MAPE_percent} u="%" />
              <Stat label="Pointwise RMSE" v={evaluation.summary.Pointwise_RMSE} u="BPM" />
              <Stat label="Pearson r" v={evaluation.summary.Pointwise_Pearson_r} d={3} />
              <Stat label="SpO₂ mean" v={evaluation.summary.SpO2_Mean} u="%" />
              <div className="metric-card">
                <div className="metric-label">Clinical</div>
                <div className="metric-value sm">
                  {evaluation.summary.Clinical_Pass === null ||
                  evaluation.summary.Clinical_Pass === undefined
                    ? '—'
                    : evaluation.summary.Clinical_Pass
                      ? 'PASS'
                      : 'FAIL'}
                </div>
              </div>
            </div>
          )}

          {evaluation.summary && (
            <CmsStatsTable s={evaluation.summary} />
          )}

          {evaluation.urls?.[evaluation.dashboard ?? ''] && (
            <figure className="plot eval-dashboard">
              <a
                href={evaluation.urls[evaluation.dashboard!]}
                target="_blank"
                rel="noreferrer"
              >
                <img
                  src={evaluation.urls[evaluation.dashboard!]}
                  alt="live evaluation dashboard"
                  loading="lazy"
                />
              </a>
            </figure>
          )}

          <div className="eval-links">
            {evaluation.urls &&
              Object.entries(evaluation.urls).map(([name, url]) => (
                <a key={name} href={url} target="_blank" rel="noreferrer">
                  {name}
                </a>
              ))}
          </div>
        </section>
      )}
    </div>
  )
}

function Stat({
  label,
  v,
  u = '',
  d = 1,
}: {
  label: string
  v: number | boolean | null | undefined
  u?: string
  d?: number
}) {
  const txt =
    v === null || v === undefined || typeof v === 'boolean'
      ? '—'
      : `${v.toFixed(d)}${u ? ' ' + u : ''}`
  return (
    <div className="metric-card">
      <div className="metric-label">{label}</div>
      <div className="metric-value sm">{txt}</div>
    </div>
  )
}

// CMS50D oximeter device statistics + medians for the final report table.
function CmsStatsTable({ s }: { s: Record<string, number | boolean | null> }) {
  const num = (k: string): number | null => {
    const v = s[k]
    return typeof v === 'number' ? v : null
  }
  const f = (v: number | null, d = 1, u = '') =>
    v === null ? '—' : `${v.toFixed(d)}${u ? ' ' + u : ''}`

  const meanStd = (m: string, sd: string, u: string) => {
    const a = num(m)
    if (a === null) return '—'
    const b = num(sd)
    return b === null ? `${a.toFixed(1)} ${u}` : `${a.toFixed(1)} ± ${b.toFixed(1)} ${u}`
  }
  const range = (lo: string, hi: string, u: string) => {
    const a = num(lo)
    const b = num(hi)
    return a === null || b === null ? '—' : `${a.toFixed(0)}–${b.toFixed(0)} ${u}`
  }

  // No oximeter data in this recording.
  if (num('GT_Median_HR') === null && num('SpO2_Median') === null) {
    return (
      <p className="muted small">
        No CMS50D device data in this recording (oximeter not connected). The
        device statistics table populates from hardware HR / SpO₂ / waveform
        once the CMS50D is recording.
      </p>
    )
  }

  const rows: Array<[string, string]> = [
    ['Hardware HR — median', f(num('GT_Median_HR'), 1, 'BPM')],
    ['Hardware HR — mean ± std', meanStd('GT_Mean_HR', 'GT_Std_HR', 'BPM')],
    ['SpO₂ — median', f(num('SpO2_Median'), 1, '%')],
    ['SpO₂ — mean ± std', meanStd('SpO2_Mean', 'SpO2_Std', '%')],
    ['SpO₂ — range', range('SpO2_Min', 'SpO2_Max', '%')],
    ['CMS HR_FFT — stable', f(num('CMS_HR_FFT_Stable'), 1, 'BPM')],
    ['CMS HR_FFT — MAE vs hardware', f(num('CMS_HR_FFT_MAE'), 2, 'BPM')],
    ['HR from CMS waveform', f(num('HR_from_CMS_Waveform'), 1, 'BPM')],
    ['Perfusion index (proxy)', f(num('Perfusion_Index_Proxy'), 2, '%')],
    ['Pulse amplitude CV', f(num('Pulse_Amplitude_CV'), 2, '%')],
    ['Valid hardware-HR samples', f(num('Valid_GT_Count'), 0)],
  ]

  return (
    <>
      <h3 className="cms-stats-title">CMS50D device statistics</h3>
      <table className="cms-stats">
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label}>
              <td>{label}</td>
              <td>{value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}
