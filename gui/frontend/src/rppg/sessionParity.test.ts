// Browser/Python parity for session aggregation.
//
// The fixture is generated from the Python implementation
// (tests/fixtures/generate_session_parity.py) and read by both suites, so a rule
// change in either language breaks a test instead of letting the two UIs drift.
//
// Synthetic readings only: this verifies agreement between two implementations,
// not physiological accuracy.
import { describe, it, expect } from 'vitest'
import fixture from '../../../../tests/fixtures/session_aggregation_parity.json'
import {
  CONSENSUS,
  SessionCollector,
  summarizeSession,
  type MetricId,
  type ReadingInput,
  type SessionLifecycle,
} from './sessionAggregate'

const NOW = 1_767_000_000_000

type CaseSpec = {
  lifecycle: string
  expected: {
    completion: string
    result_available: boolean
    verdict: string
    n_accepted: number
    n_rejected: number
    n_independent: number | null
    mean: number | null
    median: number | null
    sd: number | null
    acceptance_pct: number | null
    density_ratio: number | null
    uneven_density: boolean
  }
}

type ReadingSpec = {
  value?: number | null
  window_start_s?: number
  window_end_s?: number
  metric?: string
  algorithm?: string
  quality_verdict?: string
  rejection_reason?: string | null
  session_elapsed_s?: number
}

// The readings live in the Python test module, so the fixture stores only the
// expectations. Re-deriving the inputs from the same compact recipe keeps both
// suites honest without duplicating a JSON blob of hundreds of readings.
const RECIPES: Record<string, ReadingSpec[]> = {
  sliding_window_overlap: Array.from({ length: 40 }, (_, i) => ({
    value: 70 + (i % 5),
    window_start_s: 0.5 * i,
    window_end_s: 0.5 * i + 10,
  })),
  non_overlapping_available: [70, 72, 74, 76, 78].map((v, i) => ({
    value: v,
    window_start_s: 10 * i,
    window_end_s: 10 * i + 10,
  })),
  non_overlapping_completed: [70, 72, 74, 76, 78].map((v, i) => ({
    value: v,
    window_start_s: 10 * i,
    window_end_s: 10 * i + 10,
  })),
  mixed_verdicts: [
    { value: 70, window_start_s: 0, window_end_s: 10 },
    { value: 72, window_start_s: 10, window_end_s: 20 },
    { value: 74, window_start_s: 20, window_end_s: 30 },
    { value: 76, window_start_s: 30, window_end_s: 40 },
    { value: 78, window_start_s: 40, window_end_s: 50 },
    {
      value: 190,
      window_start_s: 50,
      window_end_s: 60,
      quality_verdict: 'low_signal_quality',
      rejection_reason: 'low SNR',
    },
    {
      value: null,
      window_start_s: 60,
      window_end_s: 70,
      quality_verdict: 'roi_lost',
      rejection_reason: 'All skin ROIs are lost',
    },
  ],
  all_rejected: Array.from({ length: 3 }, (_, i) => ({
    value: null,
    window_start_s: 10 * i,
    window_end_s: 10 * i + 10,
    quality_verdict: 'roi_lost',
    rejection_reason: 'All skin ROIs are lost',
  })),
  interrupted_short: [70, 72].map((v, i) => ({
    value: v,
    window_start_s: 10 * i,
    window_end_s: 10 * i + 10,
  })),
  single_window_overlap: Array.from({ length: 8 }, () => ({
    value: 72,
    window_start_s: 100,
    window_end_s: 110,
  })),
  single_window_overlap_running: Array.from({ length: 8 }, () => ({
    value: 72,
    window_start_s: 100,
    window_end_s: 110,
  })),
  empty: [],
  empty_running: [],
  uneven_density: [
    ...Array.from({ length: 60 }, (_, k) => ({
      value: 70,
      window_start_s: 0.5 * k,
      window_end_s: 0.5 * k + 10,
    })),
    ...Array.from({ length: 15 }, (_, k) => ({
      value: 80,
      window_start_s: 30 + 4 * k,
      window_end_s: 40 + 4 * k,
    })),
  ],
}

function run(specs: ReadingSpec[], lifecycle: string) {
  const collector = new SessionCollector()
  for (const spec of specs) {
    const start = spec.window_start_s ?? 0
    const reading: ReadingInput = {
      metric: (spec.metric ?? 'heart_rate') as MetricId,
      value: (spec.value === undefined ? 72 : spec.value) as number | null,
      algorithm: spec.algorithm ?? CONSENSUS,
      roi: 'all',
      qualityScore: 0.6,
      qualityVerdict: spec.quality_verdict ?? 'valid',
      sampling: {
        fsHz: 30,
        nSamples: 300,
        windowStartS: start,
        windowEndS: spec.window_end_s ?? start + 10,
      },
      rejectionReason: spec.rejection_reason ?? null,
      analyzedAtMs: NOW + start * 1000,
      sessionElapsedS: spec.session_elapsed_s ?? start,
      windowIndex: Math.floor(start / 10),
    }
    collector.add(reading, reading.analyzedAtMs)
  }
  return summarizeSession(collector.all(), { lifecycle: lifecycle as SessionLifecycle })
}

const cases = fixture.cases as Record<string, CaseSpec>

describe('session aggregation parity with the Python implementation', () => {
  it('uses a fixture generated from the Python implementation', () => {
    expect(fixture.schema).toBe('rsbvp.session-parity.v1')
    expect(fixture.note.toLowerCase()).toContain('synthetic')
    expect(fixture.generated_by).toBe('tests/fixtures/generate_session_parity.py')
  })

  it('has a recipe for every fixture case', () => {
    expect(Object.keys(RECIPES).sort()).toEqual(Object.keys(cases).sort())
  })

  for (const [name, spec] of Object.entries(cases)) {
    it(`agrees on "${name}"`, () => {
      const summary = run(RECIPES[name], spec.lifecycle)
      const hr = summary.metrics.find(m => m.metric === 'heart_rate')!
      const round = (v: number | null) => (v === null ? null : Number(v.toFixed(6)))
      expect({
        completion: summary.completion,
        result_available: summary.resultAvailable,
        verdict: hr.verdict,
        n_accepted: hr.nAccepted,
        n_rejected: hr.nRejected,
        n_independent: hr.nIndependentAccepted,
        mean: round(hr.mean),
        median: round(hr.median),
        sd: round(hr.sd),
        acceptance_pct: round(summary.acceptancePct),
        density_ratio: round(summary.densityRatio),
        uneven_density: summary.unevenDensity,
      }).toEqual(spec.expected)
    })
  }

  it('covers every completion state the UI can display', () => {
    const states = new Set(Object.values(cases).map(c => c.expected.completion))
    for (const state of ['idle', 'initialising', 'collecting', 'insufficient', 'available', 'interrupted', 'completed']) {
      expect(states.has(state)).toBe(true)
    }
  })
})
