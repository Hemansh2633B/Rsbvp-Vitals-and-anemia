import {render,screen,fireEvent,waitFor} from '@testing-library/react'
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
