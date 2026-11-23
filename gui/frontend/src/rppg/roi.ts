export type Point = {x:number;y:number}
function inside(p:Point, polygon:Point[], width:number,height:number) {
  let yes=false
  for(let i=0,j=polygon.length-1;i<polygon.length;j=i++){
    const xi=polygon[i].x*width,yi=polygon[i].y*height,xj=polygon[j].x*width,yj=polygon[j].y*height
    if(((yi>p.y)!==(yj>p.y))&&p.x<(xj-xi)*(p.y-yi)/(yj-yi)+xi)yes=!yes
  }
  return yes
}
export function polygonMean(data:Uint8ClampedArray,width:number,height:number,points:Point[],minPixels=40,exclusions:Point[][]=[]):[number,number,number]|null{
  if(width<=0||height<=0||points.length<3||data.length<width*height*4)return null
  const xs=points.map(p=>p.x*width),ys=points.map(p=>p.y*height),x0=Math.max(0,Math.floor(Math.min(...xs))),x1=Math.min(width,Math.ceil(Math.max(...xs))),y0=Math.max(0,Math.floor(Math.min(...ys))),y1=Math.min(height,Math.ceil(Math.max(...ys)))
  let r=0,g=0,b=0,n=0
  for(let y=y0;y<y1;y++)for(let x=x0;x<x1;x++){
    const pos={x:x+.5,y:y+.5}
    if(!inside(pos,points,width,height)||exclusions.some(poly=>inside(pos,poly,width,height)))continue
    const q=(y*width+x)*4,rr=data[q],gg=data[q+1],bb=data[q+2],lum=(rr+gg+bb)/3
    // Conservative RGB skin heuristic is a capture-quality filter, not
    // universal skin segmentation. Eye/lip polygons are excluded separately.
    if(lum<35||lum>245||rr<gg*.88||gg<bb*.82||rr-bb<8)continue
    r+=rr;g+=gg;b+=bb;n++
  }
  return n<minPixels?null:[r/n,g/n,b/n]
}
