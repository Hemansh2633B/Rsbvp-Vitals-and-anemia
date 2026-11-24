import {render,screen,fireEvent,waitFor,act} from '@testing-library/react'
import {beforeEach,describe,expect,it,vi} from 'vitest'
import {BrowserPulse} from './BrowserPulse'
vi.mock('@mediapipe/tasks-vision',()=>({FaceLandmarker:{createFromOptions:vi.fn().mockResolvedValue({close:vi.fn(),detectForVideo:vi.fn(()=>({faceLandmarks:[]}))})},FilesetResolver:{forVisionTasks:vi.fn().mockResolvedValue({})}}))
class MockWorker{static latest:MockWorker;onmessage:any=null;onerror:any=null;constructor(){MockWorker.latest=this}postMessage=vi.fn();terminate=vi.fn()}
beforeEach(()=>{vi.stubGlobal('Worker',MockWorker);vi.stubGlobal('requestAnimationFrame',vi.fn(()=>1));vi.stubGlobal('cancelAnimationFrame',vi.fn());Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:vi.fn(),enumerateDevices:vi.fn().mockResolvedValue([])}});Object.defineProperty(HTMLMediaElement.prototype,'play',{configurable:true,value:vi.fn().mockResolvedValue(undefined)})})
describe('browser camera lifecycle',()=>{
 it('reports denied permission and exposes no estimate',async()=>{vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValueOnce(new DOMException('denied','NotAllowedError'));render(<BrowserPulse/>);fireEvent.click(screen.getByRole('button',{name:/^Start camera$/}));expect(await screen.findByRole('alert')).toHaveTextContent(/denied/i);expect(screen.getByText('Unavailable')).toBeInTheDocument()})
 it('reports missing camera hardware distinctly',async()=>{vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValueOnce(new DOMException('Requested device not found','NotFoundError'));render(<BrowserPulse/>);fireEvent.click(screen.getByRole('button',{name:/^Start camera$/}));expect(await screen.findByRole('alert')).toHaveTextContent(/NotFoundError/i)})
 it('reports lost face tracking without a stale BPM',async()=>{let callback:FrameRequestCallback|undefined;vi.stubGlobal('requestAnimationFrame',vi.fn((cb:FrameRequestCallback)=>{callback=cb;return 2}));Object.defineProperties(HTMLVideoElement.prototype,{readyState:{configurable:true,get:()=>2},videoWidth:{configurable:true,get:()=>640},videoHeight:{configurable:true,get:()=>480}});vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage:vi.fn(),clearRect:vi.fn(),strokeStyle:'',lineWidth:1,beginPath:vi.fn(),moveTo:vi.fn(),lineTo:vi.fn(),closePath:vi.fn(),stroke:vi.fn()} as unknown as CanvasRenderingContext2D);vi.mocked(navigator.mediaDevices.getUserMedia).mockResolvedValueOnce({getTracks:()=>[{stop:vi.fn()}],getVideoTracks:()=>[]} as unknown as MediaStream);render(<BrowserPulse/>);fireEvent.click(screen.getByRole('button',{name:/^Start camera$/}));await waitFor(()=>expect(callback).toBeTruthy());act(()=>callback?.(performance.now()+100));expect((await screen.findAllByText('face not detected')).length).toBeGreaterThan(0);expect(screen.getByText('Unavailable')).toBeInTheDocument()})
 it('stops every acquired camera track on stop',async()=>{const stop=vi.fn();const mockStream={getTracks:()=>[{stop}],getVideoTracks:()=>[]};vi.mocked(navigator.mediaDevices.getUserMedia).mockResolvedValueOnce(mockStream as unknown as MediaStream);render(<BrowserPulse/>);fireEvent.click(screen.getByRole('button',{name:/^Start camera$/}));await waitFor(()=>expect(screen.getByRole('button',{name:'Stop camera'})).toBeInTheDocument());fireEvent.click(screen.getByRole('button',{name:'Stop camera'}));expect(stop).toHaveBeenCalled();expect(MockWorker.latest.terminate).toHaveBeenCalled()})
 it('invalidates output and stops capture after a DSP worker crash',async()=>{const stop=vi.fn();vi.mocked(navigator.mediaDevices.getUserMedia).mockResolvedValueOnce({getTracks:()=>[{stop}],getVideoTracks:()=>[]} as unknown as MediaStream);render(<BrowserPulse/>);fireEvent.click(screen.getByRole('button',{name:/^Start camera$/}));await waitFor(()=>expect(MockWorker.latest).toBeTruthy());MockWorker.latest.onerror?.();expect(await screen.findByRole('alert')).toHaveTextContent(/worker crashed/i);expect(stop).toHaveBeenCalled()})
})

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
   fireEvent.click(screen.getByRole('button',{name:/^Start camera$/}))
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
   vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage:vi.fn(),clearRect:vi.fn(),getImageData:vi.fn(()=>imageData),strokeStyle:'',lineWidth:1,beginPath:vi.fn(),moveTo:vi.fn(),lineTo:vi.fn(),closePath:vi.fn(),stroke:vi.fn()} as unknown as CanvasRenderingContext2D)
   const face=Array.from({length:478},(_,i)=>({x:.3+((i*7)%40)/100,y:.2+((i*13)%50)/100,z:0}))
   const detectForVideo=vi.fn().mockReturnValueOnce({faceLandmarks:[]}).mockReturnValue({faceLandmarks:[face]})
   const {FaceLandmarker}=await import('@mediapipe/tasks-vision')
   vi.mocked(FaceLandmarker.createFromOptions).mockResolvedValueOnce({close:vi.fn(),detectForVideo} as never)
   vi.mocked(navigator.mediaDevices.getUserMedia).mockResolvedValueOnce({getTracks:()=>[{stop:vi.fn()}],getVideoTracks:()=>[]} as unknown as MediaStream)
   render(<BrowserPulse/>)
   fireEvent.click(screen.getByRole('button',{name:/^Start camera$/}))
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
   fireEvent.click(screen.getByRole('button',{name:/^Start camera$/}))
   await waitFor(()=>expect(screen.getByRole('button',{name:'Stop camera'})).toBeInTheDocument())
   act(()=>{document.dispatchEvent(new Event('visibilitychange'))})
   expect(stopTrack).toHaveBeenCalled()
   Object.defineProperty(document,'hidden',{configurable:true,get:()=>false})
 })
})
