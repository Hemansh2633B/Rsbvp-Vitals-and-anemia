import {describe,it,expect} from 'vitest'
import {polygonMean} from './roi'
const pixels=(w:number,h:number,r=180,g=120,b=90)=>{const a=new Uint8ClampedArray(w*h*4);for(let i=0;i<w*h;i++){a[i*4]=r;a[i*4+1]=g;a[i*4+2]=b;a[i*4+3]=255}return a}
describe('ROI pixel extraction',()=>{
 it('rejects invalid or out-of-bounds ROI polygons',()=>{expect(polygonMean(pixels(20,20),20,20,[])).toBeNull();expect(polygonMean(pixels(20,20),20,20,[{x:3,y:3},{x:4,y:3},{x:3,y:4}])).toBeNull()})
 it('excludes eye/lip regions instead of counting skin-colored pixels there',()=>{const poly=[{x:.1,y:.1},{x:.9,y:.1},{x:.9,y:.9},{x:.1,y:.9}],eye=[{x:.1,y:.1},{x:.9,y:.1},{x:.9,y:.9},{x:.1,y:.9}];expect(polygonMean(pixels(20,20),20,20,poly,20,[eye])).toBeNull()})
 it('computes RGB mean only from accepted skin-like pixels',()=>{expect(polygonMean(pixels(20,20),20,20,[{x:.1,y:.1},{x:.9,y:.1},{x:.9,y:.9},{x:.1,y:.9}],20)).toEqual([180,120,90])})
})
