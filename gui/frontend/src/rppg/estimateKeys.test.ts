// Algorithm/ROI key parsing.
//
// The bug these tests exist for: `"left_cheek_green"` was split on the first
// underscore, producing region `"left"` and algorithm `"cheek_green"`. Cheek
// readings were then attributed to a non-existent ROI and a non-existent
// algorithm, so they vanished from the consensus series and appeared mislabelled
// in exports. Forehead keys survived, which is why it went unnoticed.
import { describe, it, expect } from 'vitest'
import {
  ESTIMATOR_METHODS,
  PARSED_ROIS,
  estimateKeyLabel,
  estimateKeys,
  parseEstimateKey,
  partitionEstimateKeys,
  roiLabel,
} from './estimateKeys'

const ALL_KEYS = [
  'forehead_green',
  'forehead_pos',
  'forehead_chrom',
  'left_cheek_green',
  'left_cheek_pos',
  'left_cheek_chrom',
  'right_cheek_green',
  'right_cheek_pos',
  'right_cheek_chrom',
]

describe('estimate key parsing', () => {
  it('parses all nine ROI x method combinations correctly', () => {
    // The exact contract the task asks for, asserted key by key.
    const expected: Record<string, [string, string]> = {
      forehead_green: ['forehead', 'green'],
      forehead_pos: ['forehead', 'pos'],
      forehead_chrom: ['forehead', 'chrom'],
      left_cheek_green: ['left_cheek', 'green'],
      left_cheek_pos: ['left_cheek', 'pos'],
      left_cheek_chrom: ['left_cheek', 'chrom'],
      right_cheek_green: ['right_cheek', 'green'],
      right_cheek_pos: ['right_cheek', 'pos'],
      right_cheek_chrom: ['right_cheek', 'chrom'],
    }
    for (const [key, [roi, method]] of Object.entries(expected)) {
      const parsed = parseEstimateKey(key)
      expect(parsed, key).not.toBeNull()
      expect(parsed!.roi, key).toBe(roi)
      expect(parsed!.method, key).toBe(method)
      expect(parsed!.key).toBe(key)
    }
  })

  it('does not produce the old truncated region names', () => {
    // THE REGRESSION: these are exactly the values the previous parser returned.
    const oldParser = (key: string) => ({ roi: key.split('_')[0], method: key.slice(key.indexOf('_') + 1) })
    expect(oldParser('left_cheek_green')).toEqual({ roi: 'left', method: 'cheek_green' })
    expect(oldParser('right_cheek_chrom')).toEqual({ roi: 'right', method: 'cheek_chrom' })

    const fixed = parseEstimateKey('left_cheek_green')!
    expect(fixed.roi).toBe('left_cheek')
    expect(fixed.method).toBe('green')
    expect(fixed.roi).not.toBe('left')
    expect(fixed.method).not.toBe('cheek_green')
  })

  it('rejects unknown or malformed keys instead of guessing', () => {
    for (const key of [
      '',
      'forehead',
      'forehead_',
      'forehead_fft',
      'cheek_green',
      'left_green',
      'LEFT_CHEEK_GREEN',
      'left_cheek_green_extra',
      'left__cheek_green',
      '__green',
      'forehead_GREEN',
    ]) {
      expect(parseEstimateKey(key), key).toBeNull()
    }
  })

  it('agrees with the canonical key list', () => {
    expect(estimateKeys().sort()).toEqual([...ALL_KEYS].sort())
    expect(estimateKeys()).toHaveLength(PARSED_ROIS.length * ESTIMATOR_METHODS.length)
    for (const key of estimateKeys()) expect(parseEstimateKey(key)?.key).toBe(key)
  })

  it('round-trips every generated key', () => {
    for (const key of estimateKeys()) {
      const parsed = parseEstimateKey(key)!
      expect(`${parsed.roi}_${parsed.method}`).toBe(key)
    }
  })

  it('keeps ROI and algorithm labels distinct in partitioned records', () => {
    const estimates = Object.fromEntries(ALL_KEYS.map(k => [k, 70]))
    const { parsed, unparsable } = partitionEstimateKeys(estimates)
    expect(unparsable).toEqual([])
    expect(parsed).toHaveLength(9)
    // Every region appears exactly three times, once per method.
    for (const roi of PARSED_ROIS) {
      expect(parsed.filter(p => p.roi === roi)).toHaveLength(3)
    }
    for (const method of ESTIMATOR_METHODS) {
      expect(parsed.filter(p => p.method === method)).toHaveLength(3)
    }
  })

  it('separates unparsable keys rather than dropping them silently', () => {
    const { parsed, unparsable } = partitionEstimateKeys({
      forehead_green: 70,
      left_cheek_pos: 71,
      cheek_chrom: 72,
      bogus: 73,
    })
    expect(parsed.map(p => p.key)).toEqual(['forehead_green', 'left_cheek_pos'])
    expect(unparsable).toEqual(['cheek_chrom', 'bogus'])
  })

  it('formats human labels without ambiguity', () => {
    expect(estimateKeyLabel('left_cheek_green')).toBe('Left cheek · Green')
    expect(estimateKeyLabel('right_cheek_chrom')).toBe('Right cheek · CHROM')
    expect(estimateKeyLabel('forehead_pos')).toBe('Forehead · POS')
    expect(estimateKeyLabel('nonsense_key')).toBe('nonsense key')
    expect(roiLabel('left_cheek')).toBe('left cheek')
  })

  it('is not order-dependent for suffix matching', () => {
    // "pos" is a suffix-compatible fragment of hypothetical longer method names;
    // parsing must anchor on known methods, not on the first underscore.
    const shuffled = [...ALL_KEYS].reverse()
    for (const key of shuffled) expect(parseEstimateKey(key)).not.toBeNull()
  })
})
