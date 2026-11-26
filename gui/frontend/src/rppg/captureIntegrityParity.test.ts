import {describe,it,expect} from 'vitest'
import {readFileSync} from 'node:fs'
import {resolve} from 'node:path'
import {captureIntegrity} from './captureIntegrity'

/**
 * Cross-language parity for acquisition integrity.
 *
 * The same timestamp lists were run through `trace_report()` in
 * `gui/rppg_core/quality.py`; the expected values in this fixture come from
 * that Python implementation. The browser is the acquisition layer for the live
 * pathway and Python is the research pathway, so the two must not disagree about
 * whether a capture was regular.
 *
 * This is a software parity check on synthetic timestamps - NOT evidence about
 * real cameras or measurement accuracy.
 */
type Case = {
  name: string
  times: number[]
  expected: {
    median_fs_hz: number | null
    regular: boolean
    has_duplicate_samples: boolean
    has_irregular_timing: boolean
  }
}

const fixture = JSON.parse(
  readFileSync(resolve(process.cwd(), '../../tests/fixtures/capture_integrity_cases.json'), 'utf8'),
) as {cases: Case[]}

describe('browser/Python acquisition-integrity parity', () => {
  it('has parity cases to check', () => {
    expect(fixture.cases.length).toBeGreaterThan(0)
  })

  for (const testCase of fixture.cases) {
    it(`agrees with Python on ${testCase.name}`, () => {
      const report = captureIntegrity({times: testCase.times})
      if (testCase.expected.median_fs_hz === null) {
        expect(report.medianFsHz).toBeNull()
      } else {
        expect(report.medianFsHz).toBeCloseTo(testCase.expected.median_fs_hz, 1)
      }
      expect(report.regular).toBe(testCase.expected.regular)
      expect(report.hasDuplicateSamples).toBe(testCase.expected.has_duplicate_samples)
      expect(report.hasIrregularTiming).toBe(testCase.expected.has_irregular_timing)
    })
  }
})
