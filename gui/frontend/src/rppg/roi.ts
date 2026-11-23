export type Point = {x:number;y:number}
export function polygonMean(data:Uint8ClampedArray, width:number,height:number, points:Point[], minPixels=40):[number,number,number]|null {
  if(width<=0||height<=0||points.length<3||data.length<width*height*4)return null
  const xs=points.map(p=>p.x*width),ys=points.map(p=>p.y*height),x0=Math.max(0,Math.floor(Math.min(...xs))),x1=Math.min(width,Math.ceil(Math.max(...xs))),y0=Math.max(0,Math.floor(Math.min(...ys))),y1=Math.min(height,Math.ceil(Math.max(...ys)))
  let r=0,g=0,b=0,n=0
  for(let y=y0;y<y1;y++)for(let x=x0;x<x1;x++){
    const px=x+.5,py=y+.5;let inside=false
    for(let i=0,j=points.length-1;i<points.length;j=i++){
      const xi=points[i].x*width,yi=points[i].y*height,xj=points[j].x*width,yj=points[j].y*height
      if(((yi>py)!==(yj>py))&&px<(xj-xi)*(py-yi)/(yj-yi)+xi)inside=!inside
    }
    if(!inside)continue
    const q=(y*width+x)*4,rr=data[q],gg=data[q+1],bb=data[q+2],lum=(rr+gg+bb)/3
    if(lum<35||lum>245||rr<gg*.88||gg<bb*.82||rr-bb<8)continue
    r+=rr;g+=gg;b+=bb;n++
  }
  return n<minPixels?null:[r/n,g/n,b/n]
}
