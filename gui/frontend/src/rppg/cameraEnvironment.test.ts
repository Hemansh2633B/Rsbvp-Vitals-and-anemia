// Camera environment checks. No browser and no camera: every case is a pure
// function of the values a real browser would supply.
import { describe, it, expect } from 'vitest'
import {
  describeTrackGeometry,
  inspectSecureContext,
  isPrivateNetworkHost,
  videoConstraintsFor,
} from './cameraEnvironment'

describe('secure-context detection', () => {
  it('treats localhost over HTTP as capturable', () => {
    const r = inspectSecureContext({
      isSecureContext: true, mediaDevices: true, getUserMedia: true,
      location: { origin: 'http://localhost:5173', hostname: 'localhost', protocol: 'http:' },
    })
    expect(r.secure).toBe(true)
    expect(r.canCapture).toBe(true)
    expect(r.loopback).toBe(true)
    expect(r.privateNetwork).toBe(false)
    expect(r.message).toMatch(/localhost/)
  })

  it('refuses a private-network HTTP address and explains exactly why', () => {
    // THE REPORTED FIELD CASE: the screenshot showed http://192.168.x.x with no
    // camera. This is not a secure context, so mediaDevices is absent.
    const r = inspectSecureContext({
      isSecureContext: false, mediaDevices: false, getUserMedia: false,
      location: { origin: 'http://192.168.1.7:5173', hostname: '192.168.1.7', protocol: 'http:' },
    })
    expect(r.secure).toBe(false)
    expect(r.canCapture).toBe(false)
    expect(r.privateNetwork).toBe(true)
    expect(r.message).toMatch(/private network address \(192\.168\.1\.7\)/)
    expect(r.message).toMatch(/HTTPS/)
    expect(r.message).toMatch(/localhost/)
  })

  it('explains a non-private insecure origin without blaming the network', () => {
    const r = inspectSecureContext({
      isSecureContext: false, mediaDevices: false, getUserMedia: false,
      location: { origin: 'http://example.test:8080', hostname: 'example.test', protocol: 'http:' },
    })
    expect(r.privateNetwork).toBe(false)
    expect(r.message).toMatch(/not a secure context/)
    expect(r.message).not.toMatch(/private network/)
  })

  it('accepts any host over HTTPS', () => {
    const r = inspectSecureContext({
      isSecureContext: true, mediaDevices: true, getUserMedia: true,
      location: { origin: 'https://192.168.1.7:8443', hostname: '192.168.1.7', protocol: 'https:' },
    })
    expect(r.secure).toBe(true)
    expect(r.canCapture).toBe(true)
    expect(r.privateNetwork).toBe(true) // still a private address, but now secure
  })

  it('separates a missing API from an insecure context', () => {
    const noApi = inspectSecureContext({
      isSecureContext: true, mediaDevices: true, getUserMedia: false,
      location: { origin: 'https://example.test', hostname: 'example.test', protocol: 'https:' },
    })
    expect(noApi.canCapture).toBe(false)
    expect(noApi.message).toMatch(/getUserMedia is missing/)

    const noDevices = inspectSecureContext({
      isSecureContext: true, mediaDevices: false, getUserMedia: false,
      location: { origin: 'https://example.test', hostname: 'example.test', protocol: 'https:' },
    })
    expect(noDevices.message).toMatch(/navigator\.mediaDevices is missing/)
  })

  it('falls back to protocol/host when isSecureContext is unavailable', () => {
    const https = inspectSecureContext({ mediaDevices: true, getUserMedia: true, location: { hostname: 'a.test', protocol: 'https:' } })
    expect(https.isSecureContext).toBeNull()
    expect(https.secure).toBe(true)
    const loop = inspectSecureContext({ mediaDevices: true, getUserMedia: true, location: { hostname: '127.0.0.1', protocol: 'http:' } })
    expect(loop.secure).toBe(true)
    const plain = inspectSecureContext({ mediaDevices: true, getUserMedia: true, location: { hostname: 'a.test', protocol: 'http:' } })
    expect(plain.secure).toBe(false)
    expect(plain.canCapture).toBe(false)
  })

  it('reports the origin without leaking path or query', () => {
    const r = inspectSecureContext({
      isSecureContext: true, mediaDevices: true, getUserMedia: true,
      location: { origin: 'https://example.test', hostname: 'example.test', protocol: 'https:' },
    })
    expect(r.origin).toBe('https://example.test')
    expect(r.origin).not.toMatch(/\?/)
  })

  it('classifies private and public hosts', () => {
    for (const host of ['10.0.0.5', '192.168.0.10', '172.16.4.2', '172.31.255.1', '169.254.1.1', 'fd00::1', 'fe80::1', 'phone.local']) {
      expect(isPrivateNetworkHost(host), host).toBe(true)
    }
    for (const host of ['localhost', '127.0.0.1', '8.8.8.8', '172.15.0.1', '172.32.0.1', 'example.com']) {
      expect(isPrivateNetworkHost(host), host).toBe(false)
    }
  })
})

describe('track geometry', () => {
  it('reports portrait and landscape orientation', () => {
    const portrait = describeTrackGeometry({ videoWidth: 720, videoHeight: 1280 })
    expect(portrait.orientation).toBe('portrait')
    expect(portrait.aspectRatio).toBeCloseTo(0.5625, 4)

    const landscape = describeTrackGeometry({ videoWidth: 1280, videoHeight: 720 })
    expect(landscape.orientation).toBe('landscape')
    expect(landscape.aspectRatio).toBeCloseTo(1.7778, 4)
  })

  it('flags a canvas that does not match the decoded frame', () => {
    const mismatch = describeTrackGeometry({ videoWidth: 1280, videoHeight: 720, canvasWidth: 640, canvasHeight: 480 })
    expect(mismatch.canvasMatchesVideo).toBe(false)
    expect(mismatch.message).toMatch(/DOES NOT match/)

    const match = describeTrackGeometry({ videoWidth: 640, videoHeight: 480, canvasWidth: 640, canvasHeight: 480 })
    expect(match.canvasMatchesVideo).toBe(true)
    expect(match.message).not.toMatch(/DOES NOT match/)
  })

  it('reports when the delivered size differs from what was requested', () => {
    const g = describeTrackGeometry({
      videoWidth: 720, videoHeight: 1280,
      settings: { width: 640, height: 480, frameRate: 30, facingMode: 'user' },
      canvasWidth: 720, canvasHeight: 1280,
    })
    expect(g.settingsWidth).toBe(640)
    expect(g.frameRate).toBe(30)
    expect(g.facingMode).toBe('user')
    expect(g.message).toMatch(/track settings asked for 640x480/)
    expect(g.message).toMatch(/facing user/)
  })

  it('says nothing is known before the first frame', () => {
    const g = describeTrackGeometry({ videoWidth: 0, videoHeight: 0 })
    expect(g.orientation).toBe('square')
    expect(g.aspectRatio).toBeNull()
    expect(g.canvasMatchesVideo).toBe(false)
    expect(g.message).toMatch(/Waiting for the first decoded frame/)
  })

  it('never produces NaN for missing settings', () => {
    const g = describeTrackGeometry({ videoWidth: 640, videoHeight: 480, settings: null })
    expect(g.settingsWidth).toBeNull()
    expect(g.frameRate).toBeNull()
    expect(g.facingMode).toBeNull()
    expect(Number.isFinite(g.aspectRatio!)).toBe(true)
  })
})

describe('video constraints', () => {
  it('asks for the front camera by default', () => {
    expect(videoConstraintsFor('')).toEqual({ facingMode: { ideal: 'user' }, width: { ideal: 640 }, height: { ideal: 480 } })
  })

  it('prefers an explicit device when one is chosen', () => {
    const c = videoConstraintsFor('abc123')
    expect(c.deviceId).toEqual({ exact: 'abc123' })
    expect(c.facingMode).toBeUndefined()
  })

  it('can request the environment camera explicitly', () => {
    expect(videoConstraintsFor('', { facingMode: 'environment' }).facingMode).toEqual({ ideal: 'environment' })
  })
})
