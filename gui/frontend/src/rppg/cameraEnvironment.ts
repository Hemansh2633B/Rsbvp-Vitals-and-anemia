/**
 * Camera environment checks: secure context, API availability and the actual
 * track geometry.
 *
 * WHY THIS EXISTS
 * ---------------
 * `getUserMedia` is only exposed in a *secure context*. `http://localhost` is
 * secure by specification; an arbitrary private-network address such as
 * `http://192.168.1.7:5173` is **not**, even though it is on the same LAN. In that
 * case `navigator.mediaDevices` is `undefined`, so the previous check
 * (`if (!navigator.mediaDevices?.getUserMedia)`) did fire - but the message,
 * "Camera API unavailable. Use HTTPS or localhost in a supported browser.", did
 * not say *which* condition had failed or what the current origin actually was,
 * which makes it hard to act on in the field.
 *
 * This module answers three questions separately, because they fail separately:
 *   1. Is the page a secure context, and is the camera API present at all?
 *   2. What did the camera actually deliver (resolution, facing mode, frame rate)?
 *   3. Do the video element, the sampling canvas and the overlay agree on size?
 *
 * Everything is a pure function of values the caller passes in, so it can be
 * tested without a browser or a camera.
 */

export type SecureContextReport = {
  secure: boolean
  /** `window.isSecureContext`, or null when unavailable. */
  isSecureContext: boolean | null
  /** `navigator.mediaDevices` present. */
  mediaDevices: boolean
  /** `navigator.mediaDevices.getUserMedia` present. */
  getUserMedia: boolean
  /** The page origin, for the operator message. Never includes a path or query. */
  origin: string | null
  hostname: string | null
  protocol: string | null
  /** True when the host is a loopback name where HTTP is still secure. */
  loopback: boolean
  /** True when the host is a private-network address (secure only over HTTPS). */
  privateNetwork: boolean
  /** Actionable explanation, or a "ready" message. */
  message: string
  /** True only when camera capture can be attempted. */
  canCapture: boolean
}

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '[::1]'])

/** RFC1918 / link-local / unique-local ranges commonly used for LAN dev servers. */
export function isPrivateNetworkHost(hostname: string): boolean {
  const host = hostname.toLowerCase()
  if (LOOPBACK_HOSTS.has(host)) return false
  const v4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host)
  if (v4) {
    const [a, b] = [Number(v4[1]), Number(v4[2])]
    if (a === 10) return true
    if (a === 192 && b === 168) return true
    if (a === 172 && b >= 16 && b <= 31) return true
    if (a === 169 && b === 254) return true
    return false
  }
  // IPv6 unique-local (fc00::/7) and link-local (fe80::/10)
  if (host.startsWith('fc') || host.startsWith('fd') || host.startsWith('fe8') || host.startsWith('fe9') || host.startsWith('fea') || host.startsWith('feb')) return true
  // mDNS names used by some dev servers
  return host.endsWith('.local')
}

/**
 * Inspect the current browsing context.
 *
 * Takes its inputs explicitly so the decision logic is testable; the default
 * implementation reads the real globals.
 */
export function inspectSecureContext(
  env: {
    isSecureContext?: boolean
    mediaDevices?: boolean
    getUserMedia?: boolean
    location?: { origin?: string; hostname?: string; protocol?: string } | null
  } = {},
): SecureContextReport {
  const isSecureContext = typeof env.isSecureContext === 'boolean' ? env.isSecureContext : null
  const mediaDevices = env.mediaDevices === true
  const getUserMedia = env.getUserMedia === true
  const origin = env.location?.origin ?? null
  const hostname = env.location?.hostname ?? null
  const protocol = env.location?.protocol ?? null
  const loopback = hostname ? LOOPBACK_HOSTS.has(hostname.toLowerCase()) : false
  const privateNetwork = hostname ? isPrivateNetworkHost(hostname) : false
  const secure = isSecureContext ?? (loopback || protocol === 'https:')

  let message: string
  let canCapture = false
  if (!mediaDevices || !getUserMedia) {
    if (!secure) {
      message = privateNetwork
        ? `Camera unavailable: this page is served over ${protocol ?? 'HTTP'} from a private network address (${hostname}), and browsers only expose the camera in a secure context. Serve the same build over HTTPS (for example with a self-signed certificate on the LAN address) or test on localhost.`
        : `Camera unavailable: this page is not a secure context (${protocol ?? 'unknown protocol'}//${hostname ?? 'unknown host'}), so the browser does not expose the camera API. Use HTTPS, or localhost on the device running the server.`
    } else if (!mediaDevices) {
      message = 'Camera unavailable: navigator.mediaDevices is missing even though the context is secure. The browser may not support getUserMedia, or a policy may have disabled it.'
    } else {
      message = 'Camera unavailable: getUserMedia is missing from navigator.mediaDevices. This browser cannot capture frames for analysis.'
    }
  } else if (!secure) {
    // API present but the context claims to be insecure: do not start.
    message = `Camera unavailable: the context reports itself as insecure (${origin ?? 'unknown origin'}), so capture results cannot be trusted. Use HTTPS or localhost.`
  } else {
    canCapture = true
    message = loopback ? 'Camera API available on localhost.' : 'Camera API available over a secure context.'
  }
  return { secure, isSecureContext, mediaDevices, getUserMedia, origin, hostname, protocol, loopback, privateNetwork, message, canCapture }
}

/** Read the real global environment and inspect it. */
export function inspectBrowserEnvironment(): SecureContextReport {
  const nav = typeof navigator === 'undefined' ? undefined : navigator
  const loc = typeof window === 'undefined' ? undefined : window.location
  return inspectSecureContext({
    isSecureContext: typeof window === 'undefined' ? undefined : window.isSecureContext,
    mediaDevices: Boolean(nav?.mediaDevices),
    getUserMedia: Boolean(nav?.mediaDevices?.getUserMedia),
    location: loc ? { origin: loc.origin, hostname: loc.hostname, protocol: loc.protocol } : null,
  })
}

/* ------------------------------------------------------------------ *
 * Track geometry
 * ------------------------------------------------------------------ */

export type TrackGeometry = {
  /** Live frame width/height in pixels, 0 while the element has not decoded yet. */
  videoWidth: number
  videoHeight: number
  /** Nominal settings reported by the track (may differ from the decoded size). */
  settingsWidth: number | null
  settingsHeight: number | null
  frameRate: number | null
  /** `user` for a front camera; drives overlay mirroring and labels. */
  facingMode: string | null
  deviceLabel: string | null
  /** Sampled-canvas size, which must equal the video size. */
  canvasWidth: number
  canvasHeight: number
  /** 'portrait' when height > width, 'landscape' otherwise. */
  orientation: 'portrait' | 'landscape' | 'square'
  /** Aspect ratio (width / height), null before the first frame. */
  aspectRatio: number | null
  /** True when the sampling canvas matches the decoded frame exactly. */
  canvasMatchesVideo: boolean
  /** Human-readable summary for the diagnostics panel. */
  message: string
}

/**
 * Describe what the camera actually delivered.
 *
 * Deliberately compares the *decoded* size with the canvas size: sampling a
 * canvas that does not match the frame silently rescales pixels, which changes
 * the ROI geometry relative to the landmarks. This is checked rather than
 * assumed.
 */
export function describeTrackGeometry(
  input: {
    videoWidth?: number
    videoHeight?: number
    settings?: { width?: number; height?: number; frameRate?: number; facingMode?: string; deviceId?: string } | null
    deviceLabel?: string | null
    canvasWidth?: number
    canvasHeight?: number
  },
): TrackGeometry {
  const videoWidth = Math.max(0, Math.round(input.videoWidth ?? 0))
  const videoHeight = Math.max(0, Math.round(input.videoHeight ?? 0))
  const canvasWidth = Math.max(0, Math.round(input.canvasWidth ?? 0))
  const canvasHeight = Math.max(0, Math.round(input.canvasHeight ?? 0))
  const settings = input.settings ?? null
  const aspectRatio = videoHeight > 0 ? videoWidth / videoHeight : null
  const orientation: TrackGeometry['orientation'] =
    videoWidth === 0 || videoHeight === 0 ? 'square' : videoWidth === videoHeight ? 'square' : videoWidth > videoHeight ? 'landscape' : 'portrait'
  const canvasMatchesVideo = videoWidth > 0 && videoHeight > 0 && canvasWidth === videoWidth && canvasHeight === videoHeight
  const facingMode = typeof settings?.facingMode === 'string' ? settings.facingMode : null

  let message: string
  if (!videoWidth || !videoHeight) {
    message = 'Waiting for the first decoded frame; frame dimensions are not known yet.'
  } else {
    const parts = [
      `Decoded frame ${videoWidth}x${videoHeight} (${orientation}${aspectRatio ? `, ${aspectRatio.toFixed(2)}:1` : ''})`,
      facingMode ? `facing ${facingMode}` : 'facing mode not reported',
    ]
    if (settings?.width && settings?.height && (settings.width !== videoWidth || settings.height !== videoHeight)) {
      parts.push(`track settings asked for ${settings.width}x${settings.height}`)
    }
    if (settings?.frameRate) parts.push(`${settings.frameRate.toFixed(1)} fps requested`)
    if (!canvasMatchesVideo) parts.push(`canvas ${canvasWidth}x${canvasHeight} DOES NOT match the frame`)
    message = `${parts.join('; ')}.`
  }

  return {
    videoWidth,
    videoHeight,
    settingsWidth: settings?.width ?? null,
    settingsHeight: settings?.height ?? null,
    frameRate: typeof settings?.frameRate === 'number' ? settings.frameRate : null,
    facingMode,
    deviceLabel: input.deviceLabel ?? null,
    canvasWidth,
    canvasHeight,
    orientation,
    aspectRatio,
    canvasMatchesVideo,
    message,
  }
}

/** Read the geometry of a live video element and sampling canvas. */
export function readTrackGeometry(
  video: Pick<HTMLVideoElement, 'videoWidth' | 'videoHeight'> | null,
  canvas: Pick<HTMLCanvasElement, 'width' | 'height'> | null,
  stream: MediaStream | null,
  deviceLabel: string | null = null,
): TrackGeometry {
  const track = stream?.getVideoTracks?.()[0]
  const settings = track?.getSettings ? track.getSettings() : null
  return describeTrackGeometry({
    videoWidth: video?.videoWidth ?? 0,
    videoHeight: video?.videoHeight ?? 0,
    settings: settings ?? null,
    deviceLabel,
    canvasWidth: canvas?.width ?? 0,
    canvasHeight: canvas?.height ?? 0,
  })
}

/**
 * Whether a freshly requested constraint should ask for the front camera.
 *
 * Kept explicit so the intent is testable: the analysis needs a stable, frontal,
 * well-lit face, and a rear camera is normally pointed at something else.
 */
export function videoConstraintsFor(deviceId: string, options: { facingMode?: 'user' | 'environment' } = {}): MediaTrackConstraints {
  if (deviceId) return { deviceId: { exact: deviceId }, width: { ideal: 640 }, height: { ideal: 480 } }
  return { facingMode: { ideal: options.facingMode ?? 'user' }, width: { ideal: 640 }, height: { ideal: 480 } }
}
