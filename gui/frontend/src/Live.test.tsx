import {render,screen,fireEvent,waitFor} from '@testing-library/react'
import {beforeEach,describe,expect,it,vi} from 'vitest'
import {Live} from './Live'
vi.mock('./api',()=>({listDevices:vi.fn().mockResolvedValue({serial_ports:[],cms_candidate:null,default_camera_index:0})}))
class FakeWebSocket {static latest:FakeWebSocket;onopen:any=null;onerror:any=null;onclose:any=null;onmessage:any=null;sent:string[]=[];constructor(_url:string){FakeWebSocket.latest=this}send(v:string){this.sent.push(v)}close(){this.onclose?.()} }
beforeEach(()=>{vi.stubGlobal('WebSocket',FakeWebSocket);Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:vi.fn().mockRejectedValue(new Error('no camera')),enumerateDevices:vi.fn().mockResolvedValue([])}})})
describe('legacy live socket lifecycle',()=>{
 it('starts a live socket and reports disconnect failure',async()=>{render(<Live/>);await screen.findByText(/local host capture/i);fireEvent.click(screen.getByRole('button',{name:/^Start$/}));await waitFor(()=>expect(FakeWebSocket.latest).toBeTruthy());FakeWebSocket.latest.onerror?.();expect(await screen.findByText(/WebSocket connection failed/i)).toBeInTheDocument()})
 it('sends stop action when session is stopped',async()=>{render(<Live/>);fireEvent.click(screen.getByRole('button',{name:/^Start$/}));await waitFor(()=>expect(FakeWebSocket.latest).toBeTruthy());FakeWebSocket.latest.onopen?.();fireEvent.click(await screen.findByRole('button',{name:/^Stop$/}));expect(FakeWebSocket.latest.sent.some((x:string)=>JSON.parse(x).action==='stop')).toBe(true)})
})
