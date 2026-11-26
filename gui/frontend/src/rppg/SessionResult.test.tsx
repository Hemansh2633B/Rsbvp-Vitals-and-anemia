// Session result UI. Synthetic readings only: these tests show the interface
// presents and separates numbers correctly. They are software tests and say
// nothing about physiological accuracy.
import { render, screen, within, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { SessionResult } from './SessionResult'
import {
  CONSENSUS,
  SessionCollector,
  summarizeSession,
  type ReadingInput,
} from './sessionAggregate'

const NOW = 1_767_000_000_000
let elapsed = 0

const reading = (value: number | null, over: Partial<ReadingInput> = {}): ReadingInput => {
  const start = (elapsed += 10)
  return {
    metric: 'heart_rate', value, algorithm: CONSENSUS, roi: 'all',
    qualityScore: 0.55, qualityVerdict: 'valid',
    sampling: { fsHz: 30, nSamples: 300, windowStartS: start, windowEndS: start + 10 },
    rejectionReason: null, analyzedAtMs: NOW + start * 1000, sessionElapsedS: start,
    windowIndex: Math.round(start / 10), ...over,
  }
}

function sessionWith(values: Array<number | null>, over: Partial<ReadingInput> = {}) {
  const collector = new SessionCollector()
  for (const v of values) {
    const r = reading(v, over)
    collector.add(r, r.analyzedAtMs)
  }
  return summarizeSession(collector.all())
}

const noop = () => {}

describe('session result: main result', () => {
  it('leads with one clearly labelled session average and its unit', () => {
    render(<SessionResult summary={sessionWith([70, 72, 74, 76, 78])} sessionId="sess-a"
      onExportReadings={noop} onExportAggregate={noop} />)
    const value = screen.getByTestId('session-value-heart_rate')
    expect(value).toHaveTextContent('74.0')
    expect(value).toHaveTextContent('BPM')
    expect(screen.getByText(/session average of 5 accepted readings/i)).toBeInTheDocument()
    // Stated twice on purpose: once in the framing, once next to the number.
    expect(screen.getAllByText(/not a medical measurement/i).length).toBeGreaterThan(0)
  })

  it('shows how many readings contributed and how many were rejected', () => {
    const collector = new SessionCollector()
    for (const v of [70, 72, 74, 76, 78]) {
      const r = reading(v); collector.add(r, r.analyzedAtMs)
    }
    const bad = reading(200, { qualityVerdict: 'low_signal_quality', rejectionReason: 'low SNR' })
    collector.add(bad, bad.analyzedAtMs)
    render(<SessionResult summary={summarizeSession(collector.all())} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    const quality = screen.getByLabelText('Measurement quality')
    expect(within(quality).getByText('Accepted').parentElement).toHaveTextContent('5')
    expect(within(quality).getByText('Rejected').parentElement).toHaveTextContent('1')
    expect(within(quality).getByText('Acceptance').parentElement).toHaveTextContent('83%')
  })

  it('never presents a rejected reading as the result', () => {
    const collector = new SessionCollector()
    const bad = reading(199, { qualityVerdict: 'low_signal_quality', rejectionReason: 'spectral concentration below 20%' })
    collector.add(bad, bad.analyzedAtMs)
    render(<SessionResult summary={summarizeSession(collector.all())} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.queryByText(/199/)).not.toBeInTheDocument()
    expect(screen.getByText('Insufficient data')).toBeInTheDocument()
  })
})

describe('session result: insufficient data', () => {
  it('shows an insufficient-data state instead of a number', () => {
    render(<SessionResult summary={sessionWith([72, 73])} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.getAllByText('Insufficient data').length).toBeGreaterThan(0)
    expect(screen.getByText(/at least 5 are needed/i)).toBeInTheDocument()
    expect(screen.queryByText('72.5')).not.toBeInTheDocument()
  })

  it('explains an empty session and does not invent readings', () => {
    render(<SessionResult summary={summarizeSession([])} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.getByText(/No readings yet/i)).toBeInTheDocument()
    expect(screen.getByText(/Start a session to collect readings/i)).toBeInTheDocument()
  })

  it('says why every reading failed when that is the whole session', () => {
    const collector = new SessionCollector()
    for (let i = 0; i < 3; i++) {
      const r = reading(null, { qualityVerdict: 'roi_lost', rejectionReason: 'All skin ROIs are lost or unavailable' })
      collector.add(r, r.analyzedAtMs)
    }
    render(<SessionResult summary={summarizeSession(collector.all())} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.getByText(/3 of 3 readings did not pass the quality checks/i)).toBeInTheDocument()
  })
})

describe('session result: stability against fluctuating live values', () => {
  it('keeps the session average steadier than the individual readings', () => {
    // A realistic wobble: the live number swings between 66 and 84.
    const values = [66, 84, 68, 82, 70, 80, 72, 78, 74]
    const summary = sessionWith(values)
    const mean = summary.metrics.find(m => m.metric === 'heart_rate')!.mean as number
    const spread = Math.max(...values) - Math.min(...values)
    expect(spread).toBe(18)
    expect(mean).toBeCloseTo(74.89, 2)
    // The stability claim that actually matters: removing any single reading
    // moves the session average by well under a BPM, while individual live
    // values swing by 18 BPM. That is the whole point of aggregation.
    const worstShift = Math.max(
      ...values.map((_, i) => Math.abs(
        values.filter((__, j) => j !== i).reduce((a, b) => a + b, 0) / (values.length - 1) - mean,
      )),
    )
    // Dropping any one reading moves the average by ~1 BPM; the live number
    // moves by 18 BPM. The aggregate is an order of magnitude steadier.
    expect(worstShift).toBeLessThan(2)
    expect(spread / worstShift).toBeGreaterThan(10)
    expect(mean).toBeGreaterThan(Math.min(...values))
    expect(mean).toBeLessThan(Math.max(...values))
    render(<SessionResult summary={summary} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.getByTestId('session-value-heart_rate')).toHaveTextContent('74.9')
  })

  it('reports the median and range alongside the mean', () => {
    render(<SessionResult summary={sessionWith([70, 70, 70, 70, 150])} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    // Mean is dragged by the outlier (86), median is not (70): both are visible.
    expect(screen.getByTestId('session-value-heart_rate')).toHaveTextContent('86.0')
    expect(screen.getByText('70.0 BPM')).toBeInTheDocument()
    expect(screen.getByText(/70.0 – 150.0 BPM/)).toBeInTheDocument()
  })

  it('plots only accepted readings and states that rejections are excluded', () => {
    const collector = new SessionCollector()
    for (const v of [70, 72, 74, 76, 78]) {
      const r = reading(v); collector.add(r, r.analyzedAtMs)
    }
    for (let i = 0; i < 4; i++) {
      const r = reading(180, { qualityVerdict: 'excessive_motion', rejectionReason: 'hold still' })
      collector.add(r, r.analyzedAtMs)
    }
    const { container } = render(<SessionResult summary={summarizeSession(collector.all())} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(container.querySelectorAll('.chart-dot')).toHaveLength(5)
    expect(screen.getByText(/rejected readings are not plotted/i)).toBeInTheDocument()
  })
})

describe('session result: individual readings', () => {
  it('hides history by default and reveals it on request', () => {
    render(<SessionResult summary={sessionWith([70, 72, 74, 76, 78])} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    const toggle = screen.getByRole('button', { name: /Show individual readings \(5\)/i })
    fireEvent.click(toggle)
    const table = screen.getByRole('table')
    expect(within(table).getAllByRole('row')).toHaveLength(6)  // header + 5
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
  })

  it('lists rejected readings with their reason so nothing is hidden', () => {
    const collector = new SessionCollector()
    const r1 = reading(70); collector.add(r1, r1.analyzedAtMs)
    const bad = reading(null, { qualityVerdict: 'irregular_timestamps', rejectionReason: 'Frame gap of 0.40 s' })
    collector.add(bad, bad.analyzedAtMs)
    render(<SessionResult summary={summarizeSession(collector.all())} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    fireEvent.click(screen.getByRole('button', { name: /Show individual readings/i }))
    const table = screen.getByRole('table')
    expect(within(table).getByText('Rejected')).toBeInTheDocument()
    expect(within(table).getByText('Frame gap of 0.40 s')).toBeInTheDocument()
  })

  it('disables the export buttons when there is nothing to export', () => {
    render(<SessionResult summary={summarizeSession([])} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.getByRole('button', { name: /Export readings/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Export session summary/i })).toBeDisabled()
  })

  it('calls the export handlers when data exists', () => {
    const onExportReadings = vi.fn()
    const onExportAggregate = vi.fn()
    render(<SessionResult summary={sessionWith([70, 72, 74, 76, 78])} sessionId="s"
      onExportReadings={onExportReadings} onExportAggregate={onExportAggregate} />)
    fireEvent.click(screen.getByRole('button', { name: /Export readings/i }))
    fireEvent.click(screen.getByRole('button', { name: /Export session summary/i }))
    expect(onExportReadings).toHaveBeenCalledTimes(1)
    expect(onExportAggregate).toHaveBeenCalledTimes(1)
  })
})

describe('session result: advanced details', () => {
  it('keeps DSP diagnostics collapsed until asked for', () => {
    render(<SessionResult summary={sessionWith([70, 72, 74, 76, 78])} sessionId="sess-xyz"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.queryByText(/independent observations/i)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Show advanced details/i }))
    expect(screen.getByText(/independent observations is smaller/i)).toBeInTheDocument()
    expect(screen.getByText(/sess-xyz/)).toBeInTheDocument()
    expect(screen.getByText(/HRV\/RMSSD, SpO₂ and blood pressure are not aggregated/i)).toBeInTheDocument()
  })

  it('does not aggregate HRV or anemia metrics into the session result', () => {
    const summary = sessionWith([70, 72, 74, 76, 78])
    render(<SessionResult summary={summary} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(summary.metrics.map(m => m.metric)).toEqual(['heart_rate', 'respiratory_rate'])
    expect(screen.queryByText(/RMSSD/)).not.toBeInTheDocument()
    expect(screen.queryByText(/hemoglobin/i)).not.toBeInTheDocument()
  })
})

describe('session result: completion', () => {
  it('says when enough data has been collected', () => {
    render(<SessionResult summary={sessionWith([72, 72, 72, 72, 72, 72, 72, 72])} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.getByText(/Complete — /)).toBeInTheDocument()
    expect(screen.getByText(/you can stop the camera/i)).toBeInTheDocument()
  })

  it('separates the live status from the session average', () => {
    render(<SessionResult summary={sessionWith([72])} sessionId="s" liveStatus="Live: signal acceptable"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.getByText('Live: signal acceptable')).toBeInTheDocument()
    // The session header describes collection, not the live signal.
    expect(screen.getByText(/1 of 8 accepted readings collected/i)).toBeInTheDocument()
  })
})
