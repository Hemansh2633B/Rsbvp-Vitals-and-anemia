/**
 * Parsing of the `"<roi>_<method>"` keys used for per-estimator series.
 *
 * WHY THIS IS A MODULE
 * --------------------
 * The keys combine a region name that may itself contain an underscore
 * (`left_cheek`, `right_cheek`) with a method name that never does (`green`,
 * `pos`, `chrom`). Splitting on the first underscore is therefore wrong:
 *
 *   "left_cheek_green".split('_')[0]      -> "left"
 *   "left_cheek_green".slice(indexOf('_')+1) -> "cheek_green"
 *
 * The previous code in `BrowserPulse.tsx` did exactly that, so every cheek
 * estimate was recorded with `roi: "left"` / `roi: "right"` and
 * `algorithm: "cheek_green"`. The readings then belonged to no known ROI and no
 * known algorithm: they were excluded from the consensus series (which filters on
 * `algorithm === 'consensus'`), mislabelled in the export, and invisible in the
 * per-ROI diagnostics. Forehead keys happened to survive ("forehead_green"), which
 * is why the defect was easy to miss.
 *
 * The parser here is anchored on the *known* method suffixes, longest first, and
 * validates the remaining prefix against the known region names. An unknown key
 * is reported as unparsable rather than being silently half-interpreted.
 */

export const ESTIMATOR_METHODS = ['green', 'pos', 'chrom'] as const
export type EstimatorMethod = (typeof ESTIMATOR_METHODS)[number]

export const PARSED_ROIS = ['forehead', 'left_cheek', 'right_cheek'] as const
export type ParsedRoi = (typeof PARSED_ROIS)[number]

export type ParsedEstimateKey = { roi: ParsedRoi; method: EstimatorMethod; key: string }

/** Every key the estimator layer can produce, in a stable order. */
export function estimateKeys(): string[] {
  return PARSED_ROIS.flatMap(roi => ESTIMATOR_METHODS.map(method => `${roi}_${method}`))
}

/**
 * Parse `"<roi>_<method>"`.
 *
 * Returns `null` for anything that is not exactly one known region plus one known
 * method. Longest-suffix matching keeps `pos` from shadowing a hypothetical
 * `_xpos` method, and prefix validation keeps `left_cheek_green` from being read
 * as region `left`.
 */
export function parseEstimateKey(key: string): ParsedEstimateKey | null {
  if (typeof key !== 'string' || !key) return null
  // Try suffixes longest-first so a method name that is a suffix of another can
  // never win.
  const methods = [...ESTIMATOR_METHODS].sort((a, b) => b.length - a.length)
  for (const method of methods) {
    const suffix = `_${method}`
    if (!key.endsWith(suffix)) continue
    const roi = key.slice(0, -suffix.length)
    if ((PARSED_ROIS as readonly string[]).includes(roi)) {
      return { roi: roi as ParsedRoi, method: method as EstimatorMethod, key }
    }
  }
  return null
}

/**
 * Split an estimates record into parsed entries and the keys that could not be
 * understood. Never throws: a malformed key must not break the capture loop, but
 * it must not be smuggled in under a wrong label either.
 */
export function partitionEstimateKeys(estimates: Record<string, unknown>): {
  parsed: ParsedEstimateKey[]
  unparsable: string[]
} {
  const parsed: ParsedEstimateKey[] = []
  const unparsable: string[] = []
  for (const key of Object.keys(estimates)) {
    const result = parseEstimateKey(key)
    if (result) parsed.push(result)
    else unparsable.push(key)
  }
  return { parsed, unparsable }
}

/** Human label for a key, e.g. "Left cheek · POS", for the diagnostics list. */
export function estimateKeyLabel(key: string): string {
  const parsed = parseEstimateKey(key)
  if (!parsed) return key.replaceAll('_', ' ')
  const region = parsed.roi.replace('_', ' ')
  const regionLabel = region.charAt(0).toUpperCase() + region.slice(1)
  const methodLabel = parsed.method === 'pos' ? 'POS' : parsed.method === 'chrom' ? 'CHROM' : 'Green'
  return `${regionLabel} · ${methodLabel}`
}

/** Region display label, e.g. `left_cheek` -> "left cheek". */
export function roiLabel(roi: ParsedRoi): string {
  return roi.replace('_', ' ')
}
