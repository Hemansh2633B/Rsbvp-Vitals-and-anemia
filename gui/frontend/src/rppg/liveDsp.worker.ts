/// <reference lib="webworker" />
import {analyzeSamples,type TraceSample} from './liveDsp'
type Request={id:number;samples:TraceSample[]}
const worker=self as unknown as DedicatedWorkerGlobalScope
worker.onmessage=(event:MessageEvent<Request>)=>{
  const {id,samples}=event.data
  try{worker.postMessage({id,result:analyzeSamples(samples)})}
  catch(error){worker.postMessage({id,error:error instanceof Error?error.message:String(error)})}
}
