// Session result presentation.
//
// Kept as a separate component so both live pathways (browser DSP and server
// DSP) render the *same* session result from the same aggregate, instead of two
// UIs drifting apart. The layout deliberately leads with one number and pushes
// DSP diagnostics into a collapsed section.
import { useId, useState } from 'react'
import {
  CONSENSUS,
  METRICS,
  type Measurement,
  type MetricAggregate,
  type SessionSummary,
} from './sessionAggregate'
import './sessionResult.css'

const BAND_LABEL: Record<'good' | 'fair' | 'poor', string> = {
  good: 'Good',
  fair: 'Fair',
  poor: 'Poor',
}

function fmt(value: number | null, decimals: number): string {
  if (value === null || !Number.isFinite(value)) return '—'
  return value.toFixed(decimals)
}

/** Small line chart of accepted readings over the session, with the mean. */
function ReadingChart({ readings, aggregate }: { readings: Measurement[]; aggregate: MetricAggregate }) {
  const accepted = readings.filter(r => r.accepted)
  const width = 340
  const height = 90
  if (accepted.length < 2) {
    return <p className="muted small">A trend appears once at least two accepted readings exist.</p>
  }
  const xs = accepted.map(r => r.sessionElapsedS ?? r.windowIndex ?? 0)
  const xMin = Math.min(...xs)
  const xMax = Math.max(...xs)
  const yValues = accepted.map(r => r.value as number)
  const meanValue = aggregate.mean ?? 0
  const pad = Math.max(2, (Math.max(...yValues) - Math.min(...yValues)) * 0.25)
  const yMin = Math.min(...yValues, meanValue) - pad
  const yMax = Math.max(...yValues, meanValue) + pad
  const xSpan = xMax - xMin || 1
  const ySpan = yMax - yMin || 1
  const px = (x: number) => ((x - xMin) / xSpan) * (width - 8) + 4
  const py = (y: number) => height - 4 - ((y - yMin) / ySpan) * (height - 12)
  const points = accepted.map(r => `${px(r.sessionElapsedS ?? r.windowIndex ?? 0)},${py(r.value as number)}`).join(' ')
  const meanY = py(meanValue)
  return (
    <figure className="session-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img"
        aria-label={`Accepted ${aggregate.label.toLowerCase()} readings over the session, with the session average`}>
        <line x1={0} x2={width} y1={meanY} y2={meanY} className="chart-mean" strokeDasharray="4 3" />
        <polyline points={points} className="chart-line" fill="none" />
        {accepted.map(r => (
          <circle key={r.id} cx={px(r.sessionElapsedS ?? r.windowIndex ?? 0)}
            cy={py(r.value as number)} r={2.5} className="chart-dot" />
        ))}
      </svg>
      <figcaption className="muted small">
        {accepted.length} accepted reading{accepted.length === 1 ? '' : 's'} · dashed line is the
        session average · rejected readings are not plotted
      </figcaption>
    </figure>
  )
}

function AggregateCard({ aggregate, readings }: { aggregate: MetricAggregate; readings: Measurement[] }) {
  const metric = METRICS[aggregate.metric]
  const hasResult = aggregate.verdict === 'available'
  return (
    <section className={`session-metric ${hasResult ? 'is-available' : 'is-unavailable'}`}>
      <div className="session-metric-head">{aggregate.label}</div>
      {hasResult ? (
        <>
          <div className="session-value" data-testid={`session-value-${aggregate.metric}`}>
            {fmt(aggregate.mean, metric.decimals)}
            <span className="session-unit">{metric.unit}</span>
          </div>
          <p className="session-note">
            Session average of {aggregate.nAccepted} accepted reading
            {aggregate.nAccepted === 1 ? '' : 's'}. {metric.note}
          </p>
        </>
      ) : (
        <>
          <div className="session-value unavailable" data-testid={`session-value-${aggregate.metric}`}>
            Insufficient data
          </div>
          <p className="session-note">{aggregate.reason}</p>
        </>
      )}
      <ReadingChart readings={readings.filter(r => r.metric === aggregate.metric && r.algorithm === CONSENSUS)}
        aggregate={aggregate} />
    </section>
  )
}

export interface SessionResultProps {
  summary: SessionSummary
  sessionId: string
  onExportReadings: () => void
  onExportAggregate: () => void
  /** Optional: the live pathway's own "nothing is being measured" state. */
  liveStatus?: string | null
}

export function SessionResult({ summary, sessionId, onExportReadings, onExportAggregate, liveStatus }: SessionResultProps) {
  const [showReadings, setShowReadings] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const readingsId = useId()
  const advancedId = useId()
  const presentable = summary.metrics.filter(m => m.verdict === 'available')
  const band = summary.acceptanceBand

  return (
    <section className="panel session-result" aria-labelledby="session-result-heading">
      <h2 id="session-result-heading">Session result</h2>
      <p className="muted small">
        One session, many short analysis windows. The session average uses only the readings that
        passed the quality checks, so it moves far less than the live number. It is still an
        estimate from a camera, not a medical measurement.
      </p>

      <p className={`completion ${summary.completion}`} role="status">
        {summary.completion === 'complete' ? 'Complete — ' : ''}
        {summary.completionReason}
      </p>
      {liveStatus && <p className="muted small">{liveStatus}</p>}

      {presentable.length === 0 ? (
        <div className="session-metric is-unavailable">
          <div className="session-value unavailable">Insufficient data</div>
          <p className="session-note">
            {summary.primaryReadings.length === 0
              ? 'No readings yet. Start the camera and hold still in even light.'
              : `${summary.nRejectedTotal} of ${summary.primaryReadings.length} readings did not pass the quality checks. ${
                  summary.metrics.find(m => m.metric === 'heart_rate')?.reason ?? ''
                }`}
          </p>
          <p className="muted small">
            A session average is not shown until there is enough independent evidence, because a
            number from one or two windows would suggest a precision that does not exist.
          </p>
        </div>
      ) : (
        <div className="session-metrics">
          {presentable.map(aggregate => (
            <AggregateCard key={aggregate.metric} aggregate={aggregate} readings={summary.readings} />
          ))}
        </div>
      )}

      <div className="session-quality" aria-label="Measurement quality">
        <div className="quality-cell">
          <span className="quality-label">Accepted</span>
          <span className="quality-value">{summary.nAcceptedTotal}</span>
        </div>
        <div className="quality-cell">
          <span className="quality-label">Rejected</span>
          <span className="quality-value">{summary.nRejectedTotal}</span>
        </div>
        <div className="quality-cell">
          <span className="quality-label">Acceptance</span>
          <span className="quality-value">
            {summary.acceptancePct === null ? '—' : `${summary.acceptancePct.toFixed(0)}%`}
          </span>
        </div>
        <div className="quality-cell">
          <span className="quality-label">Quality</span>
          <span className={`quality-value band-${band ?? 'none'}`}>
            {band ? BAND_LABEL[band] : '—'}
          </span>
        </div>
      </div>
      <p className="muted small">
        Quality describes how much of what the camera delivered was usable — the observed
        acceptance rate of the existing signal checks. It is not a confidence score and says
        nothing about accuracy.
      </p>

      <div className="session-secondary">
        <div>
          <span className="quality-label">Median</span>
          <span className="session-secondary-value">
            {presentable.length === 1
              ? `${fmt(presentable[0].median, METRICS[presentable[0].metric].decimals)} ${presentable[0].unit}`
              : '—'}
          </span>
          <span className="muted small"> less sensitive to a single outlier</span>
        </div>
        <div>
          <span className="quality-label">Range</span>
          <span className="session-secondary-value">
            {presentable.length === 1 && presentable[0].min !== null && presentable[0].max !== null
              ? `${fmt(presentable[0].min, METRICS[presentable[0].metric].decimals)} – ${fmt(
                  presentable[0].max,
                  METRICS[presentable[0].metric].decimals,
                )} ${presentable[0].unit}`
              : '—'}
          </span>
          <span className="muted small"> lowest and highest accepted reading</span>
        </div>
      </div>

      <div className="session-actions">
        <button type="button" className="secondary" aria-expanded={showReadings}
          aria-controls={readingsId} onClick={() => setShowReadings(v => !v)}>
          {showReadings ? 'Hide' : 'Show'} individual readings ({summary.primaryReadings.length})
        </button>
        <button type="button" className="secondary" disabled={!summary.readings.length}
          onClick={onExportReadings}>
          Export readings (CSV)
        </button>
        <button type="button" className="secondary" disabled={!summary.readings.length}
          onClick={onExportAggregate}>
          Export session summary (JSON)
        </button>
      </div>

      {showReadings && (
        <div id={readingsId} className="readings-table-wrap">
          <table className="readings-table">
            <caption className="muted small">
              One row per analysed window this session, accepted and rejected. Rejected windows are
              kept so the record shows what was excluded and why. Individual GREEN/POS/CHROM
              estimates are in the exported CSV, not counted here as extra evidence.
            </caption>
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">Value</th>
                <th scope="col">Status</th>
                <th scope="col">Reason</th>
                <th scope="col">At (s)</th>
              </tr>
            </thead>
            <tbody>
              {summary.primaryReadings.map(r => {
                const spec = METRICS[r.metric]
                return (
                  <tr key={r.id} className={r.accepted ? 'accepted' : 'rejected'}>
                    <td>{r.id}</td>
                    <td>
                      {r.value === null ? '—' : `${fmt(r.value, spec.decimals)} ${spec.unit}`}
                      <span className="muted small"> {spec.shortLabel}</span>
                    </td>
                    <td>{r.accepted ? 'Accepted' : 'Rejected'}</td>
                    <td>{r.accepted ? '—' : r.finalRejectionReason}</td>
                    <td>{r.sessionElapsedS === null ? '—' : r.sessionElapsedS.toFixed(1)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <button type="button" className="link-button" aria-expanded={showAdvanced}
        aria-controls={advancedId} onClick={() => setShowAdvanced(v => !v)}>
        {showAdvanced ? 'Hide' : 'Show'} advanced details
      </button>
      {showAdvanced && (
        <div id={advancedId} className="advanced-details">
          <p className="muted small">
            Diagnostics for this session. Session <code>{sessionId}</code>. Windows overlap, so the
            number of independent observations is smaller than the reading count — that is the
            figure used for statistical uncertainty.
          </p>
          <table className="readings-table">
            <thead>
              <tr>
                <th scope="col">Series</th>
                <th scope="col">Verdict</th>
                <th scope="col">n</th>
                <th scope="col">Independent</th>
                <th scope="col">Median</th>
                <th scope="col">SD</th>
                <th scope="col">SE</th>
              </tr>
            </thead>
            <tbody>
              {[...summary.metrics, ...summary.perAlgorithm]
                .filter(a => a.nTotal > 0)
                .map(a => {
                  const spec = METRICS[a.metric]
                  return (
                    <tr key={`${a.metric}-${a.algorithm}`}>
                      <td>
                        {spec.shortLabel} · {a.algorithm}
                      </td>
                      <td>{a.verdict}</td>
                      <td>
                        {a.nAccepted}/{a.nTotal}
                      </td>
                      <td>{a.nIndependentAccepted ?? '—'}</td>
                      <td>{fmt(a.median, spec.decimals)}</td>
                      <td>{fmt(a.sd, spec.decimals)}</td>
                      <td>{fmt(a.standardError, spec.decimals)}</td>
                    </tr>
                  )
                })}
            </tbody>
          </table>
          <ul className="muted small">
            <li>Mean is the arithmetic mean of accepted readings only.</li>
            <li>
              Standard error comes from the non-overlapping subset; it is “—” when that subset is
              too small to estimate, rather than guessed from overlapping windows.
            </li>
            <li>
              GREEN, POS and CHROM are summarised separately. Only the agreement-checked consensus
              is presented as the session result, because the three are not interchangeable.
            </li>
            <li>HRV/RMSSD, SpO₂ and blood pressure are not aggregated or shown: no validated estimator exists here.</li>
            <li>Anemia image features are a separate pathway and are never averaged into these metrics.</li>
          </ul>
        </div>
      )}
    </section>
  )
}

export default SessionResult
