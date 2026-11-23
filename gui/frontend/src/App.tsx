import { useState } from 'react'
import {
  analyzeUpload,
  type AnalysisResult,
} from './api'
import { Results } from './Results'
import { Live } from './Live'
import './App.css'

export default function App() {
  const [view, setView] = useState<'analyze' | 'live'>('analyze')
  const [video, setVideo] = useState<File | null>(null)
  const [csv, setCsv] = useState<File | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AnalysisResult | null>(null)

  async function run(label: string, fn: () => Promise<AnalysisResult>) {
    setBusy(label)
    setError(null)
    setResult(null)
    try {
      setResult(await fn())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <h1>
          RSBVP <span className="muted">· research prototype</span>
        </h1>
        <p className="muted">
          Remote Screening of Blood Parameters and Vital Signs Using Computer Vision and AI
        </p>
        <nav className="tabs">
          <button
            className={view === 'analyze' ? 'tab active' : 'tab'}
            onClick={() => setView('analyze')}
          >
            Offline analysis
          </button>
          <button
            className={view === 'live' ? 'tab active' : 'tab'}
            onClick={() => setView('live')}
          >
            Live capture
          </button>
        </nav>
      </header>

      <section className="panel">
        <h2>Research platform</h2>
        <p>RSBVP investigates two independent research questions: camera-derived pulse signals, and visual features in conjunctival images associated with laboratory hemoglobin. Neither module is a medical diagnostic tool.</p>
        <div className="subcards">
          <article className="subcard"><h3>01 · Contactless pulse</h3><p>Existing Green and POS processing with experimental motion-aware analysis. Estimates are unavailable when signal quality is inadequate.</p></article>
          <article className="subcard"><h3>02 · Anemia research</h3><p>No verified dataset or trained model is currently configured. This prototype does not predict hemoglobin or anemia.</p></article>
          <article className="subcard"><h3>Privacy & limitations</h3><p>Uploads are processed by the configured backend. Local live capture uses the backend machine camera. See <a href="https://github.com/Hemansh2633B/Rsbvp-Vitals-and-anemia/blob/main/docs/PRIVACY.md">privacy and research notes</a>.</p></article>
        </div>
      </section>

      {view === 'live' && <Live />}

      {view === 'analyze' && (
        <>
      <section className="panel">
        <h2>Upload a video</h2>
        <div className="upload-row">
          <label className="file-input">
            <span>Video {video ? `· ${video.name}` : '(.avi/.mp4)'}</span>
            <input
              type="file"
              accept="video/*,.avi"
              onChange={(e) => setVideo(e.target.files?.[0] ?? null)}
            />
          </label>
          <label className="file-input">
            <span>CMS50D CSV {csv ? `· ${csv.name}` : '(optional)'}</span>
            <input
              type="file"
              accept=".csv"
              onChange={(e) => setCsv(e.target.files?.[0] ?? null)}
            />
          </label>
          <button
            className="primary"
            disabled={!video || !!busy}
            onClick={() =>
              video && run('upload', () => analyzeUpload(video, csv))
            }
          >
            Analyze
          </button>
        </div>
      </section>

      {busy && (
        <div className="status running">
          <span className="spinner" /> Running pipeline on{' '}
          <strong>{busy}</strong>… (face detection, rPPG, HR/RR, evaluation)
        </div>
      )}
      {error && <div className="status error">Error: {error}</div>}

      {result && <Results result={result} />}
        </>
      )}
    </div>
  )
}
