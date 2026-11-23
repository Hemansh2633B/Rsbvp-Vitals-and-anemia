import {render,screen,fireEvent,waitFor} from '@testing-library/react'
import {beforeEach,describe,expect,it,vi} from 'vitest'
import {BrowserPulse} from './BrowserPulse'
vi.mock('@mediapipe/tasks-vision',()=>({FaceLandmarker:{createFromOptions:vi.fn()},FilesetResolver:{forVisionTasks:vi.fn()}}))
beforeEach(()=>{Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:vi.fn(),enumerateDevices:vi.fn().mockResolvedValue([])}})})
describe('browser camera lifecycle',()=>{
 it('reports denied permission and exposes no estimate',async()=>{vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValueOnce(new DOMException('denied','NotAllowedError'));render(<BrowserPulse/>);fireEvent.click(screen.getByRole('button',{name:/^Start camera$/}));expect(await screen.findByRole('alert')).toHaveTextContent(/denied/i);expect(screen.getByText('Unavailable')).toBeInTheDocument()})
 it('stops every acquired camera track on stop',async()=>{const stop=vi.fn();const track={stop};const mockStream={getTracks:()=>[track]};vi.mocked(navigator.mediaDevices.getUserMedia).mockResolvedValueOnce(mockStream as unknown as MediaStream);Object.defineProperty(HTMLMediaElement.prototype,'play',{configurable:true,value:vi.fn().mockResolvedValue(undefined)});const {container}=render(<BrowserPulse/>);fireEvent.click(screen.getByRole('button',{name:/^Start camera$/}));await waitFor(()=>expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalled());await waitFor(()=>expect(screen.getByRole('button',{name:'Stop camera'})).toBeInTheDocument());fireEvent.click(screen.getByRole('button',{name:'Stop camera'}));expect(stop).toHaveBeenCalled();container.remove()})
})
