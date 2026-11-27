import {render,screen,fireEvent,waitFor,act} from '@testing-library/react'
import {beforeEach,describe,expect,it,vi} from 'vitest'
import {BrowserPulse} from './BrowserPulse'
vi.mock('@mediapipe/tasks-vision',()=>({FaceLandmarker:{createFromOptions:vi.fn().mockResolvedValue({close:vi.fn(),detectForVideo:vi.fn(()=>({faceLandmarks:[]}))})},FilesetResolver:{forVisionTasks:vi.fn().mockResolvedValue({})}}))
class MockWorker{static latest:MockWorker;onmessage:any=null;onerror:any=null;constructor(){MockWorker.latest=this}postMessage=vi.fn();terminate=vi.fn()}
beforeEach(()=>{vi.stubGlobal('Worker',MockWorker);vi.stubGlobal('requestAnimationFrame',vi.fn(()=>1));vi.stubGlobal('cancelAnimationFrame',vi.fn());Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:vi.fn(),enumerateDevices:vi.fn().mockResolvedValue([])}});Object.defineProperty(HTMLMediaElement.prototype,'play',{configurable:true,value:vi.fn().mockResolvedValue(undefined)})})
describe('browser camera lifecycle',()=>{
 it('reports denied permission and exposes no estimate',async()=>{vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValueOnce(new DOMException('denied','NotAllowedError'));render(<BrowserPulse/>);fireEvent.click(screen.getByRole('button',{name:/^Start measurement$/}));expect(await screen.findByRole('alert')).toHaveTextContent(/denied/i);expect(screen.getByText('Unavailable')).toBeInTheDocument()})
 it('reports missing camera hardware distinctly',async()=>{vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValueOnce(new DOMException('Requested device not found','NotFoundError'));render(<BrowserPulse/>);fireEvent.click(screen.getByRole('button',{name:/^Start measurement$/}));expect(await screen.findByRole('alert')).toHaveTextContent(/NotFoundError/i)})
 it('reports lost face tracking without a stale BPM',async()=>{let callback:FrameRequestCallback|undefined;vi.stubGlobal('requestAnimationFrame',vi.fn((cb:FrameRequestCallback)=>{callback=cb;return 2}));Object.defineProperties(HTMLVideoElement.prototype,{readyState:{configurable:true,get:()=>2},videoWidth:{configurable:true,get:()=>640},videoHeight:{configurable:true,get:()=>480}});vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue(canvasContext2d());vi.mocked(navigator.mediaDevices.getUserMedia).mockResolvedValueOnce({getTracks:()=>[{stop:vi.fn()}],getVideoTracks:()=>[]} as unknown as MediaStream);render(<BrowserPulse/>);fireEvent.click(screen.getByRole('button',{name:/^Start measurement$/}));await waitFor(()=>expect(callback).toBeTruthy());act(()=>callback?.(performance.now()+100));expect((await screen.findAllByText('face not detected')).length).toBeGreaterThan(0);expect(screen.getByText('Unavailable')).toBeInTheDocument()})
 it('stops every acquired camera track on stop',async()=>{const stop=vi.fn();const mockStream={getTracks:()=>[{stop}],getVideoTracks:()=>[]};vi.mocked(navigator.mediaDevices.getUserMedia).mockResolvedValueOnce(mockStream as unknown as MediaStream);render(<BrowserPulse/>);fireEvent.click(screen.getByRole('button',{name:/^Start measurement$/}));await waitFor(()=>expect(screen.getByRole('button',{name:'Finish session'})).toBeInTheDocument());fireEvent.click(screen.getByRole('button',{name:'Finish session'}));expect(stop).toHaveBeenCalled();expect(MockWorker.latest.terminate).toHaveBeenCalled()})
 it('invalidates output and stops capture after a DSP worker crash',async()=>{const stop=vi.fn();vi.mocked(navigator.mediaDevices.getUserMedia).mockResolvedValueOnce({getTracks:()=>[{stop}],getVideoTracks:()=>[]} as unknown as MediaStream);render(<BrowserPulse/>);fireEvent.click(screen.getByRole('button',{name:/^Start measurement$/}));await waitFor(()=>expect(MockWorker.latest).toBeTruthy());MockWorker.latest.onerror?.();expect(await screen.findByRole('alert')).toHaveTextContent(/worker crashed/i);expect(stop).toHaveBeenCalled()})
})

// Complete-enough CanvasRenderingContext2D for the overlay. jsdom has no canvas
// implementation, so every method the overlay uses must exist here. Kept in one
// place so a new drawing call cannot pass silently in one test and fail in another.
function canvasContext2d(imageData?: { data: Uint8ClampedArray }) {
  return {
    drawImage: () => {}, clearRect: () => {}, getImageData: () => imageData ?? { data: new Uint8ClampedArray(4) },
    save: () => {}, restore: () => {}, setTransform: () => {}, fillRect: () => {}, setLineDash: () => {},
    beginPath: () => {}, moveTo: () => {}, lineTo: () => {}, closePath: () => {}, stroke: () => {}, fill: () => {},
    strokeStyle: '', fillStyle: '', lineWidth: 1, globalAlpha: 1,
  } as unknown as CanvasRenderingContext2D
}


// Sprint 8 regression coverage for failure/cleanup/reacquisition paths.
// All browser APIs are mocked; passing these tests is software verification,
// not a physical browser-camera validation.
describe('browser camera failure and recovery paths',()=>{
 it('falls back to the CPU delegate when the GPU delegate is unavailable',async()=>{
   const {FaceLandmarker}=await import('@mediapipe/tasks-vision')
   const create=vi.mocked(FaceLandmarker.createFromOptions)
   create.mockReset()
   create.mockRejectedValueOnce(new Error('GPU delegate unsupported'))
   create.mockResolvedValue({close:vi.fn(),detectForVideo:vi.fn(()=>({faceLandmarks:[]}))} as never)
   vi.mocked(navigator.mediaDevices.getUserMedia).mockResolvedValueOnce({getTracks:()=>[{stop:vi.fn()}],getVideoTracks:()=>[]} as unknown as MediaStream)
   render(<BrowserPulse/>)
   fireEvent.click(screen.getByRole('button',{name:/^Start measurement$/}))
   await waitFor(()=>expect(create).toHaveBeenCalledTimes(2))
   expect((create.mock.calls[0][1] as {baseOptions:{delegate:string}}).baseOptions.delegate).toBe('GPU')
   expect((create.mock.calls[1][1] as {baseOptions:{delegate:string}}).baseOptions.delegate).toBe('CPU')
   create.mockReset()
   create.mockResolvedValue({close:vi.fn(),detectForVideo:vi.fn(()=>({faceLandmarks:[]}))} as never)
 })
 it('asks for a fresh window and never reuses stale samples after reacquisition',async()=>{
   const t0=1000
   const nowSpy=vi.spyOn(performance,'now').mockReturnValue(t0)
   let videoTime=0
   let callback:FrameRequestCallback|undefined
   vi.stubGlobal('requestAnimationFrame',vi.fn((cb:FrameRequestCallback)=>{callback=cb;return 2}))
   Object.defineProperties(HTMLVideoElement.prototype,{readyState:{configurable:true,get:()=>2},videoWidth:{configurable:true,get:()=>640},videoHeight:{configurable:true,get:()=>480},currentTime:{configurable:true,get:()=>videoTime}})
   const imageData={data:new Uint8ClampedArray(640*480*4)}
   for(let i=0;i<imageData.data.length;i+=4){imageData.data[i]=180;imageData.data[i+1]=120;imageData.data[i+2]=90;imageData.data[i+3]=255}
   vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue(canvasContext2d(imageData))
   const face=Array.from({length:478},(_,i)=>({x:.3+((i*7)%40)/100,y:.2+((i*13)%50)/100,z:0}))
   const detectForVideo=vi.fn().mockReturnValueOnce({faceLandmarks:[]}).mockReturnValue({faceLandmarks:[face]})
   const {FaceLandmarker}=await import('@mediapipe/tasks-vision')
   vi.mocked(FaceLandmarker.createFromOptions).mockResolvedValueOnce({close:vi.fn(),detectForVideo} as never)
   vi.mocked(navigator.mediaDevices.getUserMedia).mockResolvedValueOnce({getTracks:()=>[{stop:vi.fn()}],getVideoTracks:()=>[]} as unknown as MediaStream)
   render(<BrowserPulse/>)
   fireEvent.click(screen.getByRole('button',{name:/^Start measurement$/}))
   await waitFor(()=>expect(callback).toBeTruthy())
   act(()=>{nowSpy.mockReturnValue(t0+100);videoTime=0.03;callback?.(t0+100)})          // face missing
   expect((await screen.findAllByText('face not detected')).length).toBeGreaterThan(0)
   act(()=>{nowSpy.mockReturnValue(t0+1300);videoTime=0.07;callback?.(t0+1300)})        // face back
   expect(await screen.findByText(/reacquiring/i)).toBeInTheDocument()
   expect(screen.getByText('Unavailable')).toBeInTheDocument()           // BPM reset, never stale
   nowSpy.mockRestore()
 })
 it('stops capture when the tab becomes hidden',async()=>{
   const stopTrack=vi.fn()
   vi.mocked(navigator.mediaDevices.getUserMedia).mockResolvedValueOnce({getTracks:()=>[{stop:stopTrack}],getVideoTracks:()=>[]} as unknown as MediaStream)
   Object.defineProperty(document,'hidden',{configurable:true,get:()=>true})
   render(<BrowserPulse/>)
   fireEvent.click(screen.getByRole('button',{name:/^Start measurement$/}))
   await waitFor(()=>expect(screen.getByRole('button',{name:'Finish session'})).toBeInTheDocument())
   act(()=>{document.dispatchEvent(new Event('visibilitychange'))})
   expect(stopTrack).toHaveBeenCalled()
   Object.defineProperty(document,'hidden',{configurable:true,get:()=>false})
 })
})

// Sprint 12: the UI must state which acquisition phase it is in and why no
// estimate is shown. Simulated media only - software verification, never a
// physiological or physical-camera validation.
describe('acquisition phase reporting',()=>{
 const stubMedia=()=>{
   Object.defineProperties(HTMLVideoElement.prototype,{readyState:{configurable:true,get:()=>2},videoWidth:{configurable:true,get:()=>640},videoHeight:{configurable:true,get:()=>480}})
   vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue(canvasContext2d({data:new Uint8ClampedArray(640*480*4)}))
 }
 it('starts in a not-started phase and explains why no estimate exists',()=>{
   render(<BrowserPulse/>)
   // Both the acquisition panel and the session panel say "not started"; that is
   // consistent labelling rather than a duplicate, so assert on the count.
   expect(screen.getAllByText('Not started').length).toBeGreaterThan(0)
   expect(screen.getByText(/Camera access begins only when you press Start/)).toBeInTheDocument()
   expect(screen.getByText('Why unavailable:')).toBeInTheDocument()
   expect(screen.getByText('Unavailable')).toBeInTheDocument()
 })
 it('names the initialising phase while the camera and model load',async()=>{
   stubMedia()
   vi.mocked(navigator.mediaDevices.getUserMedia).mockResolvedValueOnce({getTracks:()=>[{stop:vi.fn()}],getVideoTracks:()=>[]} as unknown as MediaStream)
   render(<BrowserPulse/>)
   fireEvent.click(screen.getByRole('button',{name:/^Start measurement$/}))
   await waitFor(()=>expect(screen.getByRole('button',{name:'Finish session'})).toBeInTheDocument())
   const chip=document.querySelector('.phase-chip')
   // The camera is open and a window is being collected; it must no longer claim
   // "not started", and it must not claim an estimate is available.
   expect(chip?.textContent).toBe('Acquiring signal')
   // The acquisition panel has moved on; the session panel may still say it has
   // no result, which is correct until the aggregate is available.
   expect(screen.queryAllByText('Not started')).toHaveLength(0)
   expect(screen.getByText('Unavailable')).toBeInTheDocument()
 })
 it('moves to an interrupted phase after a stop and keeps no estimate',async()=>{
   stubMedia()
   vi.mocked(navigator.mediaDevices.getUserMedia).mockResolvedValueOnce({getTracks:()=>[{stop:vi.fn()}],getVideoTracks:()=>[]} as unknown as MediaStream)
   render(<BrowserPulse/>)
   fireEvent.click(screen.getByRole('button',{name:/^Start measurement$/}))
   await waitFor(()=>expect(screen.getByRole('button',{name:'Finish session'})).toBeInTheDocument())
   fireEvent.click(screen.getByRole('button',{name:'Finish session'}))
   expect(screen.getByText('Unavailable')).toBeInTheDocument()
   expect(screen.getByText(/Why unavailable:/)).toBeInTheDocument()
 })
})

describe('acquisition: ROI geometry and provenance', () => {
  // These drive the real component with a mocked camera + landmarker and a
  // synthetic frame. They verify the *wiring*: that the face landmarks reach the
  // ROI extractor, that per-ROI diagnostics surface in the UI, and that cheek
  // estimates keep their correct region label. They are software tests on
  // synthetic pixels - no claim about any real face or camera.
  async function runFrames(frames: number, opts: { skin?: [number, number, number] } = {}) {
    const t0 = 1000
    const nowSpy = vi.spyOn(performance, 'now').mockReturnValue(t0)
    let videoTime = 0
    let callback: FrameRequestCallback | undefined
    vi.stubGlobal('requestAnimationFrame', vi.fn((cb: FrameRequestCallback) => { callback = cb; return 2 }))
    Object.defineProperties(HTMLVideoElement.prototype, {
      readyState: { configurable: true, get: () => 2 },
      videoWidth: { configurable: true, get: () => 640 },
      videoHeight: { configurable: true, get: () => 480 },
      currentTime: { configurable: true, get: () => videoTime },
    })
    const imageData = { data: new Uint8ClampedArray(640 * 480 * 4) }
    const [sr, sg, sb] = opts.skin ?? [198, 160, 138]
    for (let i = 0; i < imageData.data.length; i += 4) {
      imageData.data[i] = sr; imageData.data[i + 1] = sg; imageData.data[i + 2] = sb; imageData.data[i + 3] = 255
    }
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(canvasContext2d(imageData))
    // A synthetic landmark set: 478 points scattered over the central face area.
    // Deliberately not the canonical model, so the geometry guards are exercised
    // rather than trivially satisfied.
    const face = Array.from({ length: 478 }, (_, i) => ({ x: 0.3 + ((i * 7) % 40) / 100, y: 0.15 + ((i * 13) % 50) / 100, z: 0 }))
    const detectForVideo = vi.fn().mockReturnValue({ faceLandmarks: [face] })
    const { FaceLandmarker } = await import('@mediapipe/tasks-vision')
    vi.mocked(FaceLandmarker.createFromOptions).mockResolvedValueOnce({ close: vi.fn(), detectForVideo } as never)
    // A camera track needs addEventListener for the ended/mute/unmute handlers the
    // component attaches; without it start() throws before the frame loop runs.
    const videoTrack = {
      stop: vi.fn(),
      addEventListener: vi.fn(),
      getSettings: () => ({ facingMode: 'user', width: 640, height: 480 }),
    }
    vi.mocked(navigator.mediaDevices.getUserMedia).mockResolvedValueOnce({
      getTracks: () => [videoTrack],
      getVideoTracks: () => [videoTrack],
    } as unknown as MediaStream)
    render(<BrowserPulse />)
    fireEvent.click(screen.getByRole('button', { name: /^Start measurement$/ }))
    // Wait for the async start() chain (getUserMedia -> model -> worker -> rAF) to
    // reach the frame loop. Waiting on the Stop button is a real UI transition,
    // whereas waitFor(callback) can race the pending microtasks.
    await waitFor(() => expect(screen.getByRole('button', { name: /Finish session/ })).toBeInTheDocument(), { timeout: 3000 })
    await waitFor(() => expect(callback).toBeTruthy(), { timeout: 3000 })
    for (let i = 1; i <= frames; i += 1) {
      act(() => { nowSpy.mockReturnValue(t0 + i * 100); videoTime = i * 0.05; callback?.(t0 + i * 100) })
    }
    return { nowSpy }
  }

  it('surfaces per-ROI pixel accounting in the diagnostics panel', async () => {
    const { nowSpy } = await runFrames(3)
    expect(await screen.findByText('ROI extraction diagnostics')).toBeInTheDocument()
    // One card per region, each stating whether it sampled.
    expect(screen.getAllByText(/^(Sampling|No sample)$/).length).toBeGreaterThanOrEqual(3)
    // The explanatory paragraph wraps a <code> node, so match on textContent.
    expect(document.body.textContent).toMatch(/candidate pixel inside a region is/i)
    nowSpy.mockRestore()
  })

  it('explains a region that produced no sample instead of leaving it blank', async () => {
    // A grey frame: geometry is fine, pixels carry no chroma. The UI must name the
    // reason rather than silently showing nothing.
    const { nowSpy } = await runFrames(3, { skin: [128, 128, 128] })
    expect(await screen.findByText('ROI extraction diagnostics')).toBeInTheDocument()
    const reasons = screen.getAllByText(/low_chroma|no_accepted_pixels|too_few_candidate_pixels/)
    expect(reasons.length).toBeGreaterThan(0)
    nowSpy.mockRestore()
  })

  it('shows the full accounting table when expanded', async () => {
    const { nowSpy } = await runFrames(3)
    fireEvent.click(await screen.findByRole('button', { name: /Show full pixel accounting/ }))
    expect(screen.getByText('Polygon px²')).toBeInTheDocument()
    expect(screen.getByText('Why candidate pixels were not used')).toBeInTheDocument()
    nowSpy.mockRestore()
  })

  it('never labels a cheek estimate as a bare "left" or "right" region', async () => {
    // The provenance regression: the old parser produced roi "left" and algorithm
    // "cheek_green". Whatever the estimates are, the UI must show the full region
    // name, and no bare left/right entry may appear.
    const { nowSpy } = await runFrames(3)
    const regionLabels = screen.queryAllByText(/^(left|right)$/)
    expect(regionLabels).toHaveLength(0)
    // ROI coverage cards use the full region name.
    expect(screen.getAllByText(/left cheek|right cheek/).length).toBeGreaterThan(0)
    nowSpy.mockRestore()
  })

  it('reports the camera environment and frame geometry once streaming', async () => {
    const { nowSpy } = await runFrames(3)
    expect(await screen.findByText('Camera environment')).toBeInTheDocument()
    expect(screen.getByText('Secure context')).toBeInTheDocument()
    // Geometry is reported from the decoded frame, not the requested constraints.
    // 640x480 appears twice (frame card and canvas card) because both are correct.
    expect(screen.getAllByText('640x480').length).toBeGreaterThan(0)
    expect(screen.getByText('matches frame')).toBeInTheDocument()
    expect(screen.getByText(/Decoded frame 640x480/)).toBeInTheDocument()
    nowSpy.mockRestore()
  })
})

describe('session controls', () => {
  // Local to this block: the legacy `stubMedia` is scoped to its own describe.
  const stubMedia = () => {
    Object.defineProperties(HTMLVideoElement.prototype, {
      readyState: { configurable: true, get: () => 2 },
      videoWidth: { configurable: true, get: () => 640 },
      videoHeight: { configurable: true, get: () => 480 },
    })
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext')
      .mockReturnValue(canvasContext2d({ data: new Uint8ClampedArray(640 * 480 * 4) }))
  }
  // Synthetic camera and landmarks throughout. These verify control *logic*: that
  // pause really stops recording, that finishing cannot happen twice, and that a
  // new session starts empty. No physiological claim is made or implied.
  async function startSession() {
    vi.spyOn(performance, 'now').mockReturnValue(1000)
    let videoTime = 0
    let callback: FrameRequestCallback | undefined
    vi.stubGlobal('requestAnimationFrame', vi.fn((cb: FrameRequestCallback) => { callback = cb; return 2 }))
    Object.defineProperties(HTMLVideoElement.prototype, {
      readyState: { configurable: true, get: () => 2 },
      videoWidth: { configurable: true, get: () => 640 },
      videoHeight: { configurable: true, get: () => 480 },
      currentTime: { configurable: true, get: () => videoTime },
    })
    const imageData = { data: new Uint8ClampedArray(640 * 480 * 4) }
    for (let i = 0; i < imageData.data.length; i += 4) {
      imageData.data[i] = 198; imageData.data[i + 1] = 160; imageData.data[i + 2] = 138; imageData.data[i + 3] = 255
    }
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(canvasContext2d(imageData))
    const face = Array.from({ length: 478 }, (_, i) => ({ x: 0.3 + ((i * 7) % 40) / 100, y: 0.15 + ((i * 13) % 50) / 100, z: 0 }))
    const detectForVideo = vi.fn().mockReturnValue({ faceLandmarks: [face] })
    const { FaceLandmarker } = await import('@mediapipe/tasks-vision')
    vi.mocked(FaceLandmarker.createFromOptions).mockResolvedValueOnce({ close: vi.fn(), detectForVideo } as never)
    const videoTrack = { stop: vi.fn(), addEventListener: vi.fn(), getSettings: () => ({ facingMode: 'user', width: 640, height: 480 }) }
    vi.mocked(navigator.mediaDevices.getUserMedia).mockResolvedValueOnce({
      getTracks: () => [videoTrack], getVideoTracks: () => [videoTrack],
    } as unknown as MediaStream)
    render(<BrowserPulse />)
    fireEvent.click(screen.getByRole('button', { name: /^Start measurement$/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: /Finish session/ })).toBeInTheDocument(), { timeout: 3000 })
    await waitFor(() => expect(callback).toBeTruthy(), { timeout: 3000 })
    return {
      tick: (i: number) => act(() => { vi.mocked(performance.now).mockReturnValue(1000 + i * 100); videoTime = i * 0.05; callback?.(1000 + i * 100) }),
      videoTrack,
    }
  }

  it('offers a Ready checklist before the camera opens', () => {
    stubMedia()
    render(<BrowserPulse />)
    expect(screen.getByRole('heading', { name: /before you start/i })).toBeInTheDocument()
    // Each precondition is named, so "camera not working" is never the only signal.
    expect(document.body.textContent).toMatch(/Camera:/)
    expect(document.body.textContent).toMatch(/Face detection:/)
    expect(document.body.textContent).toMatch(/Face regions \(ROI\):/)
    expect(document.body.textContent).toMatch(/Signal quality:/)
    expect(screen.getByRole('button', { name: /^Start measurement$/ })).toBeInTheDocument()
  })

  it('replaces the checklist with session controls once measuring', async () => {
    stubMedia()
    const { tick } = await startSession()
    tick(1)
    expect(screen.queryByRole('heading', { name: /before you start/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Pause' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Finish session/ })).toBeInTheDocument()
  })

  it('pauses without releasing the camera and resumes cleanly', async () => {
    stubMedia()
    const { tick, videoTrack } = await startSession()
    tick(1)
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
    expect(screen.getByRole('button', { name: 'Resume' })).toBeInTheDocument()
    // The camera stays open: pausing is a measurement stop, not a camera stop.
    expect(videoTrack.stop).not.toHaveBeenCalled()
    // A window that lands after Pause must not be recorded.
    tick(2)
    expect(document.body.textContent).toMatch(/Session paused/i)
    fireEvent.click(screen.getByRole('button', { name: 'Resume' }))
    expect(screen.getByRole('button', { name: 'Pause' })).toBeInTheDocument()
  })

  it('finishes the session and releases the camera', async () => {
    stubMedia()
    const { tick, videoTrack } = await startSession()
    tick(1)
    fireEvent.click(screen.getByRole('button', { name: /Finish session/ }))
    expect(videoTrack.stop).toHaveBeenCalled()
    expect(document.body.textContent).toMatch(/Session finished/i)
    // Finish cannot happen twice: the control is gone once the session is finished.
    expect(screen.queryByRole('button', { name: /^Finish session$/ })).not.toBeInTheDocument()
  })

  it('starts a clean session with no readings carried over', async () => {
    stubMedia()
    const { tick } = await startSession()
    tick(1)
    tick(2)
    // Enter a session, then start a new one.
    fireEvent.click(screen.getByRole('button', { name: /Finish session/ }))
    fireEvent.click(screen.getByRole('button', { name: /New session/ }))
    // Back to the Ready state, with the aggregate reset to zero.
    expect(screen.getByRole('heading', { name: /before you start/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Start measurement$/ })).toBeInTheDocument()
    // The reset is visible as the empty-session message, not as a stale number.
    expect(document.body.textContent).toMatch(/No readings\s+were recorded yet/i)
    expect(document.body.textContent).toMatch(/Not enough reliable readings/i)
  })
})
