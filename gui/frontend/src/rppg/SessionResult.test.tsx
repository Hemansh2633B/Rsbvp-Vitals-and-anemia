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

function sessionWith(
  values: Array<number | null>,
  over: Partial<ReadingInput> = {},
  lifecycle: 'running' | 'stopped' | 'interrupted' = 'running',
) {
  const collector = new SessionCollector()
  for (const v of values) {
    const r = reading(v, over)
    collector.add(r, r.analyzedAtMs)
  }
  return summarizeSession(collector.all(), { lifecycle })
}

const noop = () => {}

describe('session result: main result', () => {
  it('leads with one clearly labelled session average and its unit', () => {
    render(<SessionResult summary={sessionWith([70, 72, 74, 76, 78])} sessionId="sess-a"
      onExportReadings={noop} onExportAggregate={noop} />)
    const value = screen.getByTestId('session-value-heart_rate')
    expect(value).toHaveTextContent('74.0')
    expect(value).toHaveTextContent('BPM')
    // The brief's required plain-language explanation, with the count in it.
    expect(screen.getByText(/This result is calculated from the 5 valid readings collected during this session/i)).toBeInTheDocument()
    expect(screen.getByText(/average pulse rate/i)).toBeInTheDocument()
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
    expect(screen.queryByTestId('session-value-heart_rate')).not.toBeInTheDocument()
    expect(screen.getAllByText('Insufficient data').length).toBeGreaterThan(0)
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
    render(<SessionResult summary={summarizeSession([], { lifecycle:'running' })} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.getByText(/No readings\s+were recorded yet/i)).toBeInTheDocument()
    expect(screen.getByText(/Waiting for the first analysable window/i)).toBeInTheDocument()
  })

  it('says why every reading failed when that is the whole session', () => {
    const collector = new SessionCollector()
    for (let i = 0; i < 3; i++) {
      const r = reading(null, { qualityVerdict: 'roi_lost', rejectionReason: 'All skin ROIs are lost or unavailable' })
      collector.add(r, r.analyzedAtMs)
    }
    render(<SessionResult summary={summarizeSession(collector.all())} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.getByText(/0 of 3 readings passed the quality checks/i)).toBeInTheDocument()
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
    // The reason is rendered inside the status cell alongside the verdict, so match
    // on its text rather than on an exact cell.
    expect(within(table).getByText(/Frame gap of 0.40 s/)).toBeInTheDocument()
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
    render(<SessionResult summary={sessionWith([72, 72, 72, 72, 72])} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.getByText('Result available')).toBeInTheDocument()
    expect(screen.getByText(/you can stop the camera/i)).toBeInTheDocument()
  })
  it('shows Completed only once the capture has actually stopped', () => {
    render(<SessionResult summary={sessionWith([70, 72, 74, 76, 78], {}, 'stopped')} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.getByText('Completed')).toBeInTheDocument()
    expect(screen.getByText(/Session complete: 5 accepted readings/i)).toBeInTheDocument()
  })
  it('never renders a stop invitation when the aggregate is insufficient', () => {
    // The Sprint 13 bug, at the UI level: 8 accepted readings from one window.
    const collector = new SessionCollector()
    for (let i = 0; i < 8; i++) {
      const r = reading(72, { sampling: { fsHz: 30, nSamples: 300, windowStartS: 100, windowEndS: 110 } })
      collector.add(r, r.analyzedAtMs)
    }
    render(<SessionResult summary={summarizeSession(collector.all(), { lifecycle: 'running' })}
      sessionId="s" onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.queryByText(/you can stop the camera/i)).not.toBeInTheDocument()
    expect(screen.getByText('Collecting')).toBeInTheDocument()
    expect(screen.getAllByText('Insufficient data').length).toBeGreaterThan(0)
  })
  it('labels an interruption as an interruption', () => {
    render(<SessionResult summary={sessionWith([70, 72], {}, 'interrupted')} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.getByText('Interrupted')).toBeInTheDocument()
    expect(screen.getByText(/Capture interrupted/i)).toBeInTheDocument()
  })

  it('separates the live status from the session average', () => {
    render(<SessionResult summary={sessionWith([72])} sessionId="s" liveStatus="Live: signal acceptable"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.getByText('Live: signal acceptable')).toBeInTheDocument()
    // The session header describes collection, not the live signal.
    expect(screen.getByText(/Collecting: 1 of 5 accepted readings/i)).toBeInTheDocument()
  })
})

describe('completion state label', () => {
  // The chip is the one place the UI says where the session is. Every state must
  // render a human label, and the two "you may stop" states must be the only ones
  // whose copy invites a stop.
  const collect = (values: Array<number | null>, lifecycle: 'running'|'stopped'|'interrupted') =>
    sessionWith(values, {}, lifecycle)

  it('labels an available running session in words', () => {
    render(<SessionResult summary={collect([70, 72, 74, 76, 78], 'running')} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    const chip = screen.getByText('Result available')
    expect(chip).toHaveClass('state-chip')
    expect(chip).toHaveClass('state-available')
  })

  it('labels a stopped session with a result as complete', () => {
    render(<SessionResult summary={collect([70, 72, 74, 76, 78], 'stopped')} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.getByText('Completed')).toHaveClass('state-completed')
  })

  it('labels a stopped session without a result as insufficient data', () => {
    render(<SessionResult summary={collect([70, 72], 'stopped')} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.getAllByText('Insufficient data').length).toBeGreaterThan(0)
  })

  it('labels an interrupted session distinctly from a finished one', () => {
    render(<SessionResult summary={collect([70, 72], 'interrupted')} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    const chip = screen.getByText('Interrupted')
    expect(chip).toHaveClass('state-interrupted')
    expect(screen.queryByText(/you can stop/i)).toBeNull()
  })

  it('never invites a stop while the result is not available', () => {
    // Sweep the states that can occur with the camera still running but no result.
    for (const values of [[], [70], [70, 72], [70, 70, 70, 70, 70, 70, 70, 70]]) {
      const { container, unmount } = render(
        <SessionResult summary={collect(values, 'running')} sessionId="s"
          onExportReadings={noop} onExportAggregate={noop} />)
      const summary = collect(values, 'running')
      if (!summary.resultAvailable) {
        expect(container.textContent).not.toMatch(/you can stop the camera/i)
      }
      unmount()
    }
  })
})

describe('analysis-density disclosure', () => {
  it('warns that the average weights every reading equally when density is uneven', () => {
    // 60 readings early, 15 much later: ratio well over 3x, plus drift.
    const collector = new SessionCollector()
    let t = 0
    for (let i = 0; i < 60; i += 1) { const r = reading(70, { sessionElapsedS: t }); collector.add(r, r.analyzedAtMs); t += 0.5 }
    t = 200
    for (let i = 0; i < 15; i += 1) { const r = reading(82, { sessionElapsedS: t }); collector.add(r, r.analyzedAtMs); t += 4 }
    const summary = summarizeSession(collector.all(), { lifecycle: 'running' })
    expect(summary.unevenDensity).toBe(true)
    render(<SessionResult summary={summary} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.getByText(/gives every accepted reading equal weight/i)).toBeInTheDocument()
    // And the mean is exactly the plain all-window mean: disclosure, not correction.
    const hr = summary.metrics.find(m => m.metric === 'heart_rate')!
    expect(hr.mean).toBeCloseTo((70 * 60 + 82 * 15) / 75, 10)
  })

  it('stays silent when density is even', () => {
    render(<SessionResult summary={sessionWith([70, 72, 74, 76, 78])} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.queryByText(/gives every accepted reading equal weight/i)).toBeNull()
  })
})

describe('experimental metrics', () => {
  it('separates respiratory rate from the session result and says why', () => {
    const collector = new SessionCollector()
    for (let i = 0; i < 5; i += 1) {
      const hr = reading(70 + i * 2)
      collector.add(hr, hr.analyzedAtMs)
      const rr = reading(15, { metric: 'respiratory_rate' })
      collector.add(rr, rr.analyzedAtMs + 1)
    }
    const summary = summarizeSession(collector.all(), { lifecycle: 'running' })
    const { container } = render(<SessionResult summary={summary} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.getByText(/Experimental \(not part of the session result\)/i)).toBeInTheDocument()
    // The sentence wraps a <strong>, so assert on textContent rather than node text.
    expect(container.textContent).toMatch(/not included in the session\s+average above/i)
    expect(screen.getAllByText(/pulse-interval variability/i).length).toBeGreaterThan(0)
    // The heart-rate headline must not have become an RR number.
    expect(screen.getByTestId('session-value-heart_rate')).toHaveTextContent(/BPM/)
    expect(screen.queryByTestId('session-value-respiratory_rate')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// Sprint 16: the simple-results experience. A non-technical reader must get one
// number, three supporting facts, plain warnings, and detail only on request.
// All readings here are synthetic.
// ---------------------------------------------------------------------------
describe('session result: simple result screen', () => {
  it('leads with a plainly labelled average pulse rate', () => {
    render(<SessionResult summary={sessionWith([70, 72, 74, 76, 78])} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.getByRole('heading', { name: /your session result/i })).toBeInTheDocument()
    expect(screen.getByText(/average pulse rate/i)).toBeInTheDocument()
    expect(screen.getByTestId('session-value-heart_rate')).toHaveTextContent('74.0')
  })

  it('shows median, range and accepted count as the supporting facts', () => {
    render(<SessionResult summary={sessionWith([70, 72, 74, 76, 78])} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.getByText(/median/i)).toBeInTheDocument()
    expect(screen.getByText(/range/i)).toBeInTheDocument()
    // median of 70..78 is 74; range 70-78
    expect(screen.getByText('74.0 BPM')).toBeInTheDocument()
    expect(screen.getByText('70.0 – 78.0 BPM')).toBeInTheDocument()
    expect(screen.getByText(/^Accepted$/i)).toBeInTheDocument()
  })

  it('says the result comes from the valid readings of this session', () => {
    render(<SessionResult summary={sessionWith([70, 72, 74, 76, 78])} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.getByText(/calculated from the 5 valid readings collected during this session/i))
      .toBeInTheDocument()
  })

  it('warns about variability without hiding the result', () => {
    const summary = sessionWith([55, 95, 60, 100, 70, 85])
    expect(summary.variable).toBe(true)
    render(<SessionResult summary={summary} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.getByText(/your readings varied during this session/i)).toBeInTheDocument()
    expect(screen.getByText(/consider repeating the measurement under steady conditions/i)).toBeInTheDocument()
    // The number is still shown: a warning is not a refusal.
    expect(screen.getByTestId('session-value-heart_rate')).toHaveTextContent('77.5')
  })

  it('stays silent about variability in a steady session', () => {
    render(<SessionResult summary={sessionWith([72, 73, 72, 71, 73, 72])} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.queryByText(/your readings varied/i)).not.toBeInTheDocument()
  })

  it('offers the required retry wording when data is insufficient', () => {
    render(<SessionResult summary={sessionWith([72, 72], {}, 'stopped')} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.getByText(/not enough reliable readings were collected/i)).toBeInTheDocument()
    expect(screen.getByText(/please try again/i)).toBeInTheDocument()
    // And no reassuring number anywhere.
    expect(screen.queryByText(/average pulse rate/i)).not.toBeInTheDocument()
  })

  it('never shows a success state for a rejected-only session', () => {
    const summary = sessionWith(
      [null, null, null],
      { qualityVerdict: 'low_signal_quality', rejectionReason: 'low_signal_quality' },
      'stopped',
    )
    render(<SessionResult summary={summary} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(summary.resultAvailable).toBe(false)
    expect(screen.getByText(/not enough reliable readings/i)).toBeInTheDocument()
    expect(screen.getAllByText(/Insufficient data/i).length).toBeGreaterThan(0)
  })
})

describe('session result: individual readings', () => {
  const open = () =>
    fireEvent.click(screen.getByRole('button', { name: /individual readings/i }))

  it('shows time, BPM, ROI, method and verdict for every reading', () => {
    render(<SessionResult summary={sessionWith([70, 72, 74, 76, 78])} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    open()
    const table = screen.getByRole('table')
    for (const col of ['Time', 'BPM', 'ROI', 'Method', 'Signal', 'Status']) {
      expect(within(table).getByRole('columnheader', { name: col })).toBeInTheDocument()
    }
    expect(within(table).getAllByText('All regions').length).toBeGreaterThan(0)
    expect(within(table).getAllByText(CONSENSUS).length).toBeGreaterThan(0)
  })

  it('marks a repeated window as repeated rather than as bad signal', () => {
    const collector = new SessionCollector()
    let firstWindow: ReadingInput['sampling'] | null = null
    for (const v of [70, 72, 74, 76, 78]) {
      const r = reading(v)
      firstWindow ??= r.sampling
      collector.add(r, r.analyzedAtMs)
    }
    // Re-deliver the *first* reading's window. Read from the collector rather than
    // hard-coding, because `reading()` advances a shared clock between tests.
    const dup = reading(70, { sampling: firstWindow! })
    collector.add(dup, dup.analyzedAtMs)
    expect(collector.rejected().map(r => r.finalRejectionReason)).toEqual(['duplicate_window'])
    render(<SessionResult summary={summarizeSession(collector.all())} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    open()
    expect(document.body.textContent).toMatch(/repeated window/i)
    // Disclosed at session level too.
    expect(screen.getByText(/already been counted/i)).toBeInTheDocument()
  })

  it('discloses flagged outliers and says they are included', () => {
    const summary = sessionWith([70, 71, 72, 71, 70, 155])
    expect(summary.nFlaggedOutliers).toBe(1)
    render(<SessionResult summary={summary} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    // "included" appears in bold inside the sentence, so assert the sentence.
    expect(document.body.textContent).toMatch(/They are included in the average/i)
    expect(screen.getByText(/less affected by them/i)).toBeInTheDocument()
  })

  it('keeps the screen simple until detail is requested', () => {
    render(<SessionResult summary={sessionWith([70, 72, 74, 76, 78])} sessionId="s"
      onExportReadings={noop} onExportAggregate={noop} />)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    open()
    expect(screen.getByRole('table')).toBeInTheDocument()
  })
})
