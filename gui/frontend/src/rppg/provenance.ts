// Software provenance for research exports. Version matches CITATION.cff.
// Release builds should set VITE_GIT_SHA so exports carry the exact commit;
// local/dev builds report 'unknown' rather than inventing an identifier.
export const SOFTWARE_NAME = 'RSBVP'
export const SOFTWARE_VERSION = '1.0.0'

export function buildCommit(): string {
  const v = (import.meta.env as Record<string, unknown>).VITE_GIT_SHA
  return typeof v === 'string' && v.trim() ? v.trim() : 'unknown'
}

export function softwareBlock() {
  return { name: SOFTWARE_NAME, version: SOFTWARE_VERSION, commit: buildCommit(), package: 'rsbvp-frontend' }
}

// Non-identifying random id that ties exports from one capture session
// together (CSV <-> JSON <-> windows.json) without personal data.
export function newSessionId(): string {
  const bytes = new Uint8Array(8)
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
    crypto.getRandomValues(bytes)
  } else {
    for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256)
  }
  return 'sess-' + Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('')
}
