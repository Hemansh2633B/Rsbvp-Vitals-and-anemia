/**
 * Capture frames from the camera of the device the page is open on.
 *
 * Why this exists: the live rPPG socket used to make the *server* open its own
 * webcam, so a phone (or a second laptop) that opened the dashboard saw the
 * host laptop's camera. This module acquires the local camera in the browser and
 * streams the frames to the server over the existing websocket, so the
 * measurement always comes from the device the user is actually using.
 *
 * Design notes:
 * - getUserMedia requires a secure context: `localhost` counts as secure, so
 *   http://localhost:8000 works on the host machine, but a phone on
 *   http://<lan-ip>:8000 does NOT get camera access from the browser. Callers
 *   must surface `isSecureContext === false` clearly instead of failing silently.
 * - Frames are downscaled to a 640-wide JPEG (the rPPG pipeline is tuned for
 *   640x480) and sent as raw binary, which is cheaper than base64 JSON.
 */

export interface BrowserCameraHandles {
  stop: () => void
}

export interface BrowserCameraOptions {
  /** Preferred camera device id ('' = default/front camera). */
  deviceId?: string
  /** Frames per second to send; the pipeline expects ~30. */
  fps?: number
  /** Target width in pixels; height follows the aspect ratio. */
  width?: number
  onFrame: (jpeg: Blob, timestampSeconds: number) => void
  onError?: (message: string) => void
}

export const INSECURE_CONTEXT_MESSAGE =
  'Camera access needs a secure context. Open http://localhost:8000 on this ' +
  'machine, or serve the app over HTTPS for other devices (see the README). ' +
  'A phone on http://<lan-ip>:8000 is blocked by the browser, not by this app.'

/** True when this page may request camera access at all. */
export function cameraContextAvailable(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices &&
    typeof navigator.mediaDevices.getUserMedia === 'function' &&
    (typeof window === 'undefined' || window.isSecureContext !== false)
  )
}

/** Human-readable reason a getUserMedia rejection happened. */
export function describeCameraError(error: unknown): string {
  const name = (error as { name?: string } | null)?.name ?? ''
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return 'Camera permission was denied on this device. Allow camera access in the browser, then press Start again.'
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') {
    return 'No camera was found on this device (or the selected one is unavailable).'
  }
  if (name === 'NotReadableError') {
    return 'The camera is already in use by another application on this device.'
  }
  if (!cameraContextAvailable()) return INSECURE_CONTEXT_MESSAGE
  const message = (error as { message?: string } | null)?.message
  return message ? `Camera error: ${message}` : 'Could not open the camera on this device.'
}

/** Cameras available *on this device* (labels need permission once granted). */
export async function listLocalCameras(): Promise<MediaDeviceInfo[]> {
  if (!cameraContextAvailable()) return []
  try {
    const devices = await navigator.mediaDevices.enumerateDevices()
    return devices.filter((d) => d.kind === 'videoinput')
  } catch {
    return []
  }
}

export async function startBrowserCamera(
  video: HTMLVideoElement,
  options: BrowserCameraOptions,
): Promise<BrowserCameraHandles> {
  if (!cameraContextAvailable()) throw new Error(INSECURE_CONTEXT_MESSAGE)

  const fps = Math.min(Math.max(options.fps ?? 30, 5), 60)
  const targetWidth = options.width ?? 640
  const constraints: MediaStreamConstraints = {
    audio: false,
    video: options.deviceId
      ? { deviceId: { exact: options.deviceId }, width: { ideal: targetWidth } }
      : { facingMode: { ideal: 'user' }, width: { ideal: targetWidth } },
  }

  const stream = await navigator.mediaDevices.getUserMedia(constraints)
  video.srcObject = stream
  video.muted = true
  video.playsInline = true
  await video.play()

  const canvas = document.createElement('canvas')
  let timer: number | undefined
  let stopped = false
  let reported = false

  const stop = () => {
    if (stopped) return
    stopped = true
    if (timer !== undefined) window.clearInterval(timer)
    stream.getTracks().forEach((track) => track.stop())
    if (video.srcObject === stream) video.srcObject = null
  }

  const fail = (message: string) => {
    if (reported) return
    reported = true
    stop()
    options.onError?.(message)
  }

  stream.getVideoTracks().forEach((track) => {
    track.addEventListener('ended', () =>
      fail('The camera stream ended. Reconnect the camera and press Start again.'),
    )
  })

  const sendFrame = () => {
    if (stopped) return
    const sourceWidth = video.videoWidth
    const sourceHeight = video.videoHeight
    if (!sourceWidth || !sourceHeight || video.readyState < 2) return
    const scale = Math.min(1, targetWidth / sourceWidth)
    canvas.width = Math.round(sourceWidth * scale)
    canvas.height = Math.round(sourceHeight * scale)
    const context = canvas.getContext('2d')
    if (!context) {
      fail('This browser cannot encode camera frames (2D canvas unavailable).')
      return
    }
    context.drawImage(video, 0, 0, canvas.width, canvas.height)
    canvas.toBlob(
      (blob) => {
        if (!stopped && blob) options.onFrame(blob, performance.now() / 1000)
      },
      'image/jpeg',
      0.8,
    )
  }

  timer = window.setInterval(sendFrame, Math.round(1000 / fps))
  return { stop }
}
