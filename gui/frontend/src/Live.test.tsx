import {render,screen,fireEvent,waitFor,within} from '@testing-library/react'
import {beforeEach,describe,expect,it,vi} from 'vitest'
import {Live} from './Live'
import {INSECURE_CONTEXT_MESSAGE} from './browserCamera'

vi.mock('./api',()=>({
  listDevices:vi.fn().mockResolvedValue({serial_ports:[],cms_candidate:null,default_camera_index:0}),
  // the legacy host-camera index must never be used by this component
  listLocalCameras:vi.fn(),
}))

class FakeWebSocket{
  static latest:FakeWebSocket
  onopen:((ev?:unknown)=>void)|null=null
  onerror:((ev?:unknown)=>void)|null=null
  onclose:((ev?:unknown)=>void)|null=null
  onmessage:((ev:{data:string})=>void)|null=null
  sent:Array<string|Blob>=[]
  readyState=0
  constructor(_url:string){FakeWebSocket.latest=this;this.readyState=0}
  send(v:string|Blob){this.sent.push(v)}
  close(){this.readyState=3;this.onclose?.()}
  open(){this.readyState=1;this.onopen?.()}
}

const stopTrack=vi.fn()

function stubCamera(impl?:()=>Promise<MediaStream>){
  const stream={getTracks:()=>[{stop:stopTrack}],getVideoTracks:()=>[{addEventListener:vi.fn()}]} as unknown as MediaStream
  const getUserMedia=vi.fn<(constraints?:MediaStreamConstraints)=>Promise<MediaStream>>(impl??(()=>Promise.resolve(stream)))
  Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{
    getUserMedia,
    enumerateDevices:vi.fn().mockResolvedValue([
      {kind:'videoinput',deviceId:'cam-a',label:'Front camera',groupId:'g'},
      {kind:'audioinput',deviceId:'mic',label:'Microphone',groupId:'g'},
    ]),
  }})
  return getUserMedia
}

beforeEach(()=>{
  ;(FakeWebSocket as unknown as {latest?:FakeWebSocket}).latest=undefined
  vi.stubGlobal('WebSocket',FakeWebSocket)
  vi.stubGlobal('isSecureContext',true)
  stopTrack.mockClear()
  // jsdom has no media pipeline; the element only needs to accept srcObject
  Object.defineProperty(HTMLMediaElement.prototype,'play',{configurable:true,value:vi.fn().mockResolvedValue(undefined)})
  Object.defineProperty(HTMLMediaElement.prototype,'srcObject',{configurable:true,writable:true,value:null})
})

describe('live capture uses the camera of the device that opened the page',()=>{
  it('asks this device for a camera before opening the socket',async()=>{
    const getUserMedia=stubCamera()
    render(<Live/>)
    await screen.findByText(/this device's camera/i)
    fireEvent.click(screen.getByRole('button',{name:/^Start$/}))
    await waitFor(()=>expect(getUserMedia).toHaveBeenCalledTimes(1))
    const constraints=getUserMedia.mock.calls[0]?.[0] as MediaStreamConstraints
    expect(constraints.video).toBeTruthy()
    expect(constraints.audio).toBe(false)
    // the request carries no numeric host camera index
    expect(JSON.stringify(constraints)).not.toMatch(/deviceId":\s*\d/)
  })

  it('tells the server the frames come from the browser, not the host',async()=>{
    stubCamera()
    render(<Live/>)
    fireEvent.click(screen.getByRole('button',{name:/^Start$/}))
    await waitFor(()=>expect(FakeWebSocket.latest).toBeTruthy())
    FakeWebSocket.latest.open()
    await waitFor(()=>expect(FakeWebSocket.latest.sent.length).toBeGreaterThan(0))
    const start=JSON.parse(FakeWebSocket.latest.sent[0] as string)
    expect(start.camera_source).toBe('browser')
    expect(start).not.toHaveProperty('camera_index')
  })

  it('never opens the socket when camera permission is denied',async()=>{
    stubCamera(()=>Promise.reject(Object.assign(new Error('denied'),{name:'NotAllowedError'})))
    render(<Live/>)
    fireEvent.click(screen.getByRole('button',{name:/^Start$/}))
    expect(await screen.findByText(/permission was denied on this device/i)).toBeInTheDocument()
    expect(FakeWebSocket.latest).toBeUndefined()
  })

  it('explains that a plain-http page on another device cannot use its camera',async()=>{
    vi.stubGlobal('isSecureContext',false)
    const getUserMedia=stubCamera()
    render(<Live/>)
    expect(await screen.findByText(new RegExp('secure context'))).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button',{name:/^Start$/}))
    await waitFor(()=>expect(screen.getAllByText(INSECURE_CONTEXT_MESSAGE).length).toBeGreaterThan(0))
    expect(getUserMedia).not.toHaveBeenCalled()
    expect(FakeWebSocket.latest).toBeUndefined()
  })

  it('releases the camera track when the session is stopped',async()=>{
    stubCamera()
    render(<Live/>)
    fireEvent.click(screen.getByRole('button',{name:/^Start$/}))
    await waitFor(()=>expect(FakeWebSocket.latest).toBeTruthy())
    FakeWebSocket.latest.open()
    fireEvent.click(await screen.findByRole('button',{name:/^Stop$/}))
    await waitFor(()=>expect(stopTrack).toHaveBeenCalled())
  })

  it('streams captured frames to the server as raw binary',async()=>{
    stubCamera()
    render(<Live/>)
    fireEvent.click(screen.getByRole('button',{name:/^Start$/}))
    await waitFor(()=>expect(FakeWebSocket.latest).toBeTruthy())
    FakeWebSocket.latest.open()
    // the capture loop lives in browserCamera; assert the socket is binary-ready
    expect(FakeWebSocket.latest.sent.every((m)=>typeof m==='string'||m instanceof Blob)).toBe(true)
  })

  it('shows which source is being measured once the session starts',async()=>{
    stubCamera()
    render(<Live/>)
    fireEvent.click(screen.getByRole('button',{name:/^Start$/}))
    await waitFor(()=>expect(FakeWebSocket.latest).toBeTruthy())
    FakeWebSocket.latest.open()
    FakeWebSocket.latest.onmessage?.({data:JSON.stringify({type:'started',camera_source:'browser',recording:false})})
    expect(await screen.findByText(/live .*this device/i)).toBeInTheDocument()
  })
})

// Session aggregation on the server pathway. Synthetic WebSocket frames only:
// this proves the interface collects, gates and averages readings consistently;
// it is not a physiological validation.
describe('live session aggregation',()=>{
  const frame=(over:Record<string,unknown>={})=>({
    type:'frame', frame_index:1, elapsed:20, fps:30, face_detected:true,
    buffer_seconds:12, warming_up:false, consensus_hr:72, hr_green_fft:71,
    hr_pos_fft:73, hr_green_peak:null, hr_pos_peak:null, rr_final:15,
    sampling_rate:30, quality_status:'valid', quality_reason:'ok', ...over,
  })
  // BrowserPulse renders its own session panel, so Live's must be addressed
  // explicitly by document order: BrowserPulse renders one above Live's.
  function liveSection(){
    const sections = Array.from(document.querySelectorAll('section.session-result')) as HTMLElement[]
    return sections[sections.length - 1]
  }
  function liveQuality(){
    return within(liveSection()).getByLabelText('Measurement quality')
  }
  async function startLive(){
    stubCamera()
    render(<Live/>)
    fireEvent.click(screen.getByRole('button',{name:/^Start$/}))
    await waitFor(()=>expect(FakeWebSocket.latest).toBeTruthy())
    FakeWebSocket.latest.open()
    const send=(msg:unknown)=>FakeWebSocket.latest.onmessage?.({data:JSON.stringify(msg)})
    send({type:'started',camera_source:'browser',recording:false})
    return send
  }

  it('averages accepted frames into one session result and keeps the live value separate',async()=>{
    const send = await startLive()
    expect(screen.getByText(/Live reading \(this window\)/i)).toBeInTheDocument()
    // Distinct elapsed values -> distinct, non-overlapping 12 s windows. Sending
    // the same window five times would (correctly) count as one observation.
    const elapseds = [20,40,60,80,100]
    for(const [i,hr] of [70,72,74,76,78].entries()) send(frame({consensus_hr:hr, elapsed:elapseds[i]}))
    await waitFor(()=>expect(screen.getByTestId('session-value-heart_rate')).toBeInTheDocument())
    expect(screen.getByTestId('session-value-heart_rate')).toHaveTextContent('74.0')
    expect(screen.getByTestId('session-value-heart_rate')).toHaveTextContent('BPM')
    // The live card still shows this window's value, labelled as such.
    expect(screen.getByText(/Live reading \(this window\)/i)).toBeInTheDocument()
  })

  it('excludes frames that failed the quality gate from the average',async()=>{
    const send = await startLive()
    for(const [i,hr] of [70,72,74,76,78].entries()) send(frame({consensus_hr:hr, elapsed:20+i*20}))
    send(frame({consensus_hr:190, quality_status:'low_signal_quality', quality_reason:'spectral concentration below 20%'}))
    await waitFor(()=>expect(screen.getByTestId('session-value-heart_rate')).toBeInTheDocument())
    expect(screen.getByTestId('session-value-heart_rate')).toHaveTextContent('74.0')
    const quality = liveQuality()
    expect(within(quality).getByText('Rejected').parentElement).toHaveTextContent('1')
  })

  it('reports insufficient data rather than a number when the gate rejects everything',async()=>{
    const send = await startLive()
    for(let i=0;i<3;i++) send(frame({consensus_hr:null, quality_status:'roi_lost', quality_reason:'All skin ROIs are lost', elapsed:20+i*20}))
    await waitFor(()=>expect(screen.getAllByText('Insufficient data').length).toBeGreaterThan(0))
    // Readings exist but none passed: the summary reports the aggregate's own
    // reason rather than a reassuring progress count.
    expect(within(liveSection()).getByText(/0 of 3 readings passed the quality checks/i)).toBeInTheDocument()
    expect(within(liveSection()).getByText(/No accepted readings/i)).toBeInTheDocument()
  })

  it('aggregates heart rate and respiratory rate as separate metrics with their own units',async()=>{
    const send = await startLive()
    for(let i=0;i<5;i++) send(frame({consensus_hr:70+i, rr_final:14+i/2, elapsed:20+i*20}))
    // Five independent windows (distinct elapsed times) are needed before an
    // average is presented; heartbeat and breathing are separate series.
    await waitFor(()=>expect(screen.getByTestId('session-value-heart_rate')).toBeInTheDocument())
    expect(screen.getByTestId('session-value-heart_rate')).toHaveTextContent('72.0')
    // Breathing is summarised only when it has its own evidence; it is never
    // reported as a copy of the heart-rate figure.
    const rr = screen.queryByTestId('session-value-respiratory_rate')
    if (rr) {
      expect(rr).toHaveTextContent('br/min')
      expect(rr).not.toHaveTextContent('72.0')
    }
    // The heart-rate average must not have absorbed the breathing values.
    expect(screen.getByTestId('session-value-heart_rate')).not.toHaveTextContent('15.0')
  })

  it('starts a fresh session on a new run instead of carrying readings over',async()=>{
    const send = await startLive()
    for(const [i,hr] of [70,72,74,76,78].entries()) send(frame({consensus_hr:hr, elapsed:20+i*20}))
    await waitFor(()=>expect(screen.getByTestId('session-value-heart_rate')).toHaveTextContent('74.0'))
    // The live pathway's own Start/Stop pair (BrowserPulse has its own camera
    // button, so these are addressed by exact label).
    const startButton = () => screen.getAllByRole('button').find(b => b.textContent?.trim() === 'Start')
    await waitFor(()=>expect(screen.getByRole('button',{name:/^Stop$/})).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button',{name:/^Stop$/}))
    await waitFor(()=>expect(startButton()).toBeTruthy())
    fireEvent.click(startButton() as HTMLElement)
    await waitFor(()=>expect(screen.queryByTestId('session-value-heart_rate')).not.toBeInTheDocument())
    expect(within(liveSection()).getByText(/No readings yet/i)).toBeInTheDocument()
  })
})
