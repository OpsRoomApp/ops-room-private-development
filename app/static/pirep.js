const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function pirepBrand(){const f=entry?.flight||{},b=f.airline_branding||{};if(settings?.interface?.airline_branding_enabled===false||b.enabled===false)return null;const cs=String(f.callsign||'').toUpperCase(),prefix=(cs.match(/^([A-Z]{2,4})/)||[])[1]||'',code=String(b.code||f.airline||prefix||'OR').toUpperCase();return {...b,code,name:b.name||code,logo_url:b.logo_data_uri||b.logo_url||null}}
function pirepBrandHtml(size='medium',showName=false){const b=pirepBrand();if(!b)return'';const code=b.code||'OR',img=b.logo_url?`<img src="${esc(b.logo_url)}" alt="${esc(code)}" onerror="this.hidden=true;this.nextElementSibling.hidden=false" />`:'';return `<span class="pirep-airline-brand ${esc(size)}">${img}<b ${b.logo_url?'hidden':''}>${esc(code)}</b>${showName?`<span><strong>${esc(b.name||code)}</strong><small>${esc(code)}</small></span>`:''}</span>`}
const num=value=>{if(value===null||value===undefined||value==='')return null;const n=Number(value);return Number.isFinite(n)?n:null};
const arr=value=>Array.isArray(value)?value:[];
const fmt=(value,digits=0,suffix='--')=>num(value)==null?'--':`${Number(value).toLocaleString(undefined,{maximumFractionDigits:digits,minimumFractionDigits:digits})}${suffix==='--'?'':` ${suffix}`}`;
const duration=value=>{const n=Math.max(0,Math.round(num(value)||0));return `${String(Math.floor(n/3600)).padStart(2,'0')}:${String(Math.floor(n%3600/60)).padStart(2,'0')}`};
const utc=value=>{if(!value)return'--';const d=new Date(value);return Number.isNaN(d.getTime())?'--':d.toISOString().slice(11,19)};
const css=name=>getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const palette={blue:css('--blue'),red:css('--red'),green:css('--green'),amber:css('--amber'),purple:css('--purple'),cyan:css('--cyan'),muted:css('--muted'),line:css('--line'),grid:css('--grid'),text:css('--text'),card:css('--card')};
let entry=null,telemetry=null,analysis=null,samples=[],settings=null;
const chartZoomState={};
const units=()=>settings?.interface?.units||{};
const cvAlt=v=>units().altitude==='m'&&num(v)!=null?num(v)*0.3048:v;
const cvDist=v=>units().distance==='km'&&num(v)!=null?num(v)*1.852:v;
const cvWeight=v=>units().weight==='kg'&&num(v)!=null?num(v)*0.45359237:v;
const cvSpeed=v=>units().speed==='kmh'&&num(v)!=null?num(v)*1.852:v;
const cvVs=v=>units().vertical_speed==='mps'&&num(v)!=null?num(v)*0.00508:v;
const uAlt=()=>units().altitude==='m'?'M':'FT'; const uDist=()=>units().distance==='km'?'KM':'NM'; const uWeight=()=>units().weight==='kg'?'KG':'LB'; const uSpeed=()=>units().speed==='kmh'?'KM/H':'KT'; const uVs=()=>units().vertical_speed==='mps'?'M/S':'FPM';

function flightId(){const parts=location.pathname.split('/').filter(Boolean);return parts.at(-1)||''}
async function getJson(url){const response=await fetch(url,{cache:'no-store'});let data={};try{data=await response.json()}catch{}if(!response.ok)throw new Error(data.detail||'The requested flight report is unavailable.');return data}
function metric(label,value,detail=''){return `<div class="metric-tile"><span>${esc(label)}</span><strong>${esc(value)}</strong>${detail?`<small>${esc(detail)}</small>`:''}</div>`}
function fitCanvas(canvas){const rect=canvas.getBoundingClientRect();const dpr=Math.min(2,window.devicePixelRatio||1);canvas.width=Math.max(320,Math.round(rect.width*dpr));canvas.height=Math.max(180,Math.round(rect.height*dpr));const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);return {ctx,w:rect.width,h:rect.height}}
function niceStep(raw){
  const v=Math.abs(raw)||1;
  const pow=Math.pow(10,Math.floor(Math.log10(v)));
  const n=v/pow;
  const mult=n<=1?1:n<=1.5?1.5:n<=2?2:n<=2.5?2.5:n<=5?5:10;
  return mult*pow;
}
function roundAxisExtent(lo,hi,{includeZero=false,symmetric=false,minAbs=null,maxAbs=null,tickCount=6}={}){
  lo=Number.isFinite(lo)?lo:0;hi=Number.isFinite(hi)?hi:1;
  if(includeZero){lo=Math.min(lo,0);hi=Math.max(hi,0)}
  if(symmetric){
    let lim=Math.max(Math.abs(lo),Math.abs(hi),minAbs||0,1);
    const step=niceStep((lim*2)/tickCount);
    lim=Math.ceil(lim/step)*step;
    if(maxAbs)lim=Math.min(maxAbs,Math.ceil(lim/step)*step);
    return [-lim,lim,step];
  }
  if(lo===hi){lo-=1;hi+=1}
  const span=hi-lo;
  const step=niceStep(span/tickCount);
  lo=Math.floor(lo/step)*step;
  hi=Math.ceil(hi/step)*step;
  if(lo===hi)hi=lo+step;
  return [lo,hi,step];
}
function extent(values,pad=.08,includeZero=false){
  let vals=values.map(num).filter(v=>v!=null&&Number.isFinite(v));
  if(!vals.length)return[0,1,1];
  let lo=Math.min(...vals),hi=Math.max(...vals);
  if(lo===hi){lo-=1;hi+=1}
  const range=hi-lo;lo-=range*pad;hi+=range*pad;
  return roundAxisExtent(lo,hi,{includeZero,tickCount:6});
}
function zoomedXExtent(canvasId, fullExt){
  const lo=Number(fullExt?.[0]),hi=Number(fullExt?.[1]);
  if(!Number.isFinite(lo)||!Number.isFinite(hi)||hi<=lo)return fullExt;
  const z=chartZoomState[canvasId];
  if(!z||!Number.isFinite(z.lo)||!Number.isFinite(z.hi)||z.hi<=z.lo)return fullExt;
  const span=hi-lo,minSpan=(hi-lo)*0.04;
  const a=Math.max(lo,Math.min(hi-minSpan,z.lo));
  const b=Math.max(a+minSpan,Math.min(hi,z.hi));
  return [a,b,niceStep((b-a)/6)];
}
function setChartZoomDomain(canvas,pct,zoomIn=true,pctY=.5){
  const data=canvas?._opsChartRows;if(!data||!Array.isArray(data.fullXExt))return;
  const id=canvas.id,full=data.fullXExt,state=chartZoomState[id],cur=(state&&Number.isFinite(state.lo)&&Number.isFinite(state.hi)&&state.hi>state.lo)?[state.lo,state.hi]:full;const lo=cur[0],hi=cur[1],span=hi-lo;const factor=zoomIn?.72:1.38;let center=lo+span*Math.max(0,Math.min(1,pct));if(data.reverseX)center=hi-span*Math.max(0,Math.min(1,pct));let newSpan=Math.min(full[1]-full[0],Math.max((full[1]-full[0])*.04,span*factor));let nlo=center-newSpan/2,nhi=center+newSpan/2;if(nlo<full[0]){nhi+=full[0]-nlo;nlo=full[0]}if(nhi>full[1]){nlo-=nhi-full[1];nhi=full[1]}
  const next={lo:nlo,hi:nhi};
  if(data.route2d&&Array.isArray(data.fullYExt)){
    const fy=data.fullYExt,z=chartZoomState[id],cy=(z&&Number.isFinite(z.yLo)&&Number.isFinite(z.yHi))?[z.yLo,z.yHi]:data.yExt||fy;const ySpan=cy[1]-cy[0],yCenter=cy[1]-ySpan*Math.max(0,Math.min(1,pctY));let nySpan=Math.min(fy[1]-fy[0],Math.max((fy[1]-fy[0])*.04,ySpan*factor));let yLo=yCenter-nySpan/2,yHi=yCenter+nySpan/2;if(yLo<fy[0]){yHi+=fy[0]-yLo;yLo=fy[0]}if(yHi>fy[1]){yLo-=yHi-fy[1];yHi=fy[1]}next.yLo=yLo;next.yHi=yHi;
  }
  chartZoomState[id]=next;renderAll();
}
function resetChartZoom(canvas){if(canvas?.id)delete chartZoomState[canvas.id];renderAll()}

function nice(value){
  if(!Number.isFinite(value))return '';
  const abs=Math.abs(value);
  if(abs>=10000)return `${Math.round(value/1000)}k`;
  if(abs>=1000){const v=value/1000;return Number.isInteger(v)?`${v.toFixed(0)}k`:`${v.toFixed(1)}k`;}
  if(abs>=100)return `${Math.round(value)}`;
  if(abs>=10)return `${value.toFixed(0)}`;
  return `${value.toFixed(1)}`;
}
function tickValues(ext,tickCount=5){
  const lo=ext[0],hi=ext[1],step=ext[2]||niceStep((hi-lo)/tickCount);
  const out=[];
  const start=Math.ceil(lo/step)*step;
  for(let v=start,i=0;v<=hi+step*.25&&i<80;v+=step,i++)out.push(Math.abs(v)<step*1e-6?0:v);
  if(!out.length)for(let i=0;i<=tickCount;i++)out.push(lo+(hi-lo)*i/tickCount);
  return out;
}
function axes(ctx,w,h,xLabel,yLabel,rightLabel=''){
  const m={l:64,r:rightLabel?68:28,t:24,b:46};
  ctx.strokeStyle=palette.grid||palette.line;ctx.fillStyle=palette.muted;ctx.lineWidth=1;ctx.font='11px Inter, Segoe UI';
  for(let i=0;i<=5;i++){const y=m.t+(h-m.t-m.b)*i/5;ctx.beginPath();ctx.moveTo(m.l,y);ctx.lineTo(w-m.r,y);ctx.stroke()}
  ctx.textAlign='center';ctx.fillText(xLabel,w/2,h-8);
  ctx.save();ctx.translate(14,h/2);ctx.rotate(-Math.PI/2);ctx.fillText(yLabel,0,0);ctx.restore();
  if(rightLabel){ctx.save();ctx.translate(w-10,h/2);ctx.rotate(Math.PI/2);ctx.fillText(rightLabel,0,0);ctx.restore()}
  return m;
}
function plotLine(ctx,points,xMap,yMap,color,width=2,dash=[]){ctx.beginPath();let started=false;for(const p of points){const x=xMap(p),y=yMap(p);if(!Number.isFinite(x)||!Number.isFinite(y)){started=false;continue}if(!started){ctx.moveTo(x,y);started=true}else ctx.lineTo(x,y)}ctx.strokeStyle=color;ctx.lineWidth=width;ctx.setLineDash(dash);ctx.stroke();ctx.setLineDash([])}
function visibleRowsForX(rows,key,xExt){const lo=Math.min(xExt[0],xExt[1]),hi=Math.max(xExt[0],xExt[1]);const visible=arr(rows).filter(r=>{const v=num(r[key]);return v!=null&&v>=lo&&v<=hi});return visible.length>=2?visible:arr(rows)}
function drawProfile(){
  const canvas=$('profileChart');const {ctx,w,h}=fitCanvas(canvas);ctx.clearRect(0,0,w,h);
  const rows=arr(samples).filter(x=>num(x.elapsed_seconds)!=null);if(rows.length<2)return noData(ctx,w,h);
  const m=axes(ctx,w,h,'UTC / ELAPSED TIME',`ALTITUDE (${uAlt()})`,`${uSpeed()==='KT'?'GROUNDSPEED (KT)':`GROUNDSPEED (${uSpeed()})`}`);
  const mapped=rows.map(r=>({...r,altitude_display:cvAlt(r.altitude_ft),ground_speed_display:cvSpeed(r.ground_speed_kts)}));
  const fullXExt=extent(mapped.map(x=>x.elapsed_seconds),.01);const xExt=zoomedXExtent('profileChart',fullXExt);const visible=visibleRowsForX(mapped,'elapsed_seconds',xExt);
  const yAlt=extent(visible.map(x=>x.altitude_display),.05,true);const yGs=extent(visible.map(x=>x.ground_speed_display),.05,true);
  const x=v=>m.l+(num(v.elapsed_seconds)-xExt[0])/(xExt[1]-xExt[0])*(w-m.l-m.r);const ya=v=>h-m.b-(num(v.altitude_display)-yAlt[0])/(yAlt[1]-yAlt[0])*(h-m.t-m.b);const yg=v=>h-m.b-(num(v.ground_speed_display)-yGs[0])/(yGs[1]-yGs[0])*(h-m.t-m.b);
  canvas._opsChartRows={rows:mapped,xKey:'elapsed_seconds',yKeys:['altitude_display','ground_speed_display'],xExt,fullXExt,title:'Flight Profile'};
  ctx.save();ctx.beginPath();ctx.rect(m.l,m.t,w-m.l-m.r,h-m.t-m.b);ctx.clip();plotLine(ctx,mapped,x,ya,palette.blue,2.4);plotLine(ctx,mapped,x,yg,palette.red,2.2);ctx.restore();
  ctx.fillStyle=palette.blue;ctx.textAlign='left';ctx.font='10px Inter, Segoe UI';ctx.fillText('ALTITUDE',m.l,m.t-8);ctx.fillStyle=palette.red;ctx.fillText('GROUNDSPEED',m.l+82,m.t-8);
  for(let i=0;i<=5;i++){const y=m.t+(h-m.t-m.b)*i/5;ctx.fillStyle=palette.blue;ctx.textAlign='right';ctx.fillText(nice(yAlt[1]-(yAlt[1]-yAlt[0])*i/5),m.l-7,y+3);ctx.fillStyle=palette.red;ctx.textAlign='left';ctx.fillText(nice(yGs[1]-(yGs[1]-yGs[0])*i/5),w-m.r+7,y+3)}
  const startEpoch=new Date(entry.started_utc||0).getTime()/1000;for(let i=0;i<=6;i++){const xv=xExt[0]+(xExt[1]-xExt[0])*i/6;const stamp=startEpoch?new Date((startEpoch+xv)*1000).toISOString().slice(11,16):`${Math.round(xv/3600)}h`;ctx.fillStyle=palette.muted;ctx.textAlign='center';ctx.fillText(stamp,m.l+(w-m.l-m.r)*i/6,h-m.b+20)}
  const significant=(entry.events||[]).filter(e=>/TAKEOFF|LANDING|BLOCK|TOP OF|GO.AROUND|PUSHBACK/i.test(`${e.kind} ${e.detail}`));for(const e of significant){const ep=new Date(e.time||0).getTime()/1000;if(!Number.isFinite(ep)||!startEpoch)continue;const ex=m.l+((ep-startEpoch)-xExt[0])/(xExt[1]-xExt[0])*(w-m.l-m.r);if(ex<m.l||ex>w-m.r)continue;ctx.strokeStyle='rgba(255,255,255,.23)';ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(ex,m.t);ctx.lineTo(ex,h-m.b);ctx.stroke();ctx.setLineDash([]);ctx.beginPath();ctx.arc(ex,m.t+5,3.5,0,Math.PI*2);ctx.fillStyle=palette.amber;ctx.fill()}
}
function noData(ctx,w,h,text='INSUFFICIENT TELEMETRY'){ctx.fillStyle=palette.muted;ctx.font='700 12px Segoe UI';ctx.textAlign='center';ctx.fillText(text,w/2,h/2)}
function drawXY(canvasId,rows,xKey,yKey,opts={}){
  const canvas=$(canvasId);const {ctx,w,h}=fitCanvas(canvas);ctx.clearRect(0,0,w,h);
  const clean=arr(rows).filter(r=>num(r[xKey])!=null&&num(r[yKey])!=null);
  if(clean.length<2)return noData(ctx,w,h);
  const m=axes(ctx,w,h,opts.xLabel||xKey,opts.yLabel||yKey,opts.rightLabel||'');
  const fullXExt=opts.xExtent||extent(clean.map(r=>r[xKey]),.08,!!opts.xZero);
  const xExt=zoomedXExtent(canvasId,fullXExt);
  const visibleClean=clean.filter(r=>{const xv=num(r[xKey]);return xv!=null&&xv>=Math.min(xExt[0],xExt[1])&&xv<=Math.max(xExt[0],xExt[1])});
  const yRows=visibleClean.length>=2?visibleClean:clean;
  const yExt=opts.yExtent||extent(yRows.map(r=>r[yKey]),.08,!!opts.yZero);
  const xmVal=v=>m.l+(v-xExt[0])/(xExt[1]-xExt[0])*(w-m.l-m.r);
  const ymVal=v=>h-m.b-(v-yExt[0])/(yExt[1]-yExt[0])*(h-m.t-m.b);
  const xm=r=>xmVal(num(r[xKey]));
  const ym=r=>ymVal(num(r[yKey]));
  canvas._opsChartRows={rows:clean,xKey,yKeys:[yKey,opts.secondKey].filter(Boolean),xExt,fullXExt,title:opts.primaryLabel||opts.yLabel||yKey};
  const drawPolyline=(points,color,width=1.6,dash=[5,5])=>{
    const valid=points.filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y));
    if(valid.length<2)return;
    ctx.beginPath();let started=false;
    for(const p of valid){const x=xmVal(p.x),y=ymVal(p.y);if(!started){ctx.moveTo(x,y);started=true}else ctx.lineTo(x,y)}
    ctx.strokeStyle=color;ctx.lineWidth=width;ctx.setLineDash(dash);ctx.stroke();ctx.setLineDash([]);
  };
  if(opts.localizerCone){
    const maxY=Math.max(...clean.map(r=>num(r[yKey])||0),yExt[1]);
    const halfAngle=(opts.localizerCone.deg||2.5)*Math.PI/180;
    const ptsL=[],ptsR=[];
    for(let i=0;i<=24;i++){
      const y=maxY*i/24;
      const dev=y*6076.12*Math.tan(halfAngle);
      ptsL.push({x:-dev,y});ptsR.push({x:dev,y});
    }
    drawPolyline(ptsL,opts.localizerCone.color||'rgba(130,148,170,.72)',1.2,opts.localizerCone.dash||[6,6]);
    drawPolyline(ptsR,opts.localizerCone.color||'rgba(130,148,170,.72)',1.2,opts.localizerCone.dash||[6,6]);
  }
  if(opts.reference){
    for(const ref of opts.reference){
      const rv=ref.value;ctx.strokeStyle=ref.color||palette.muted;ctx.setLineDash(ref.dash||[5,5]);
      if(ref.axis==='x'){const px=xmVal(rv);ctx.beginPath();ctx.moveTo(px,m.t);ctx.lineTo(px,h-m.b);ctx.stroke()}
      else{const py=ymVal(rv);ctx.beginPath();ctx.moveTo(m.l,py);ctx.lineTo(w-m.r,py);ctx.stroke()}
      ctx.setLineDash([]);
    }
  }
  plotLine(ctx,clean,xm,ym,opts.color||palette.purple,2.4);
  ctx.fillStyle=opts.color||palette.purple;ctx.font='10px Inter, Segoe UI';ctx.textAlign='left';ctx.fillText(opts.primaryLabel||opts.yLabel||yKey,m.l,m.t-8);
  if(opts.secondKey){
    const second=clean.filter(r=>num(r[opts.secondKey])!=null);
    const secondVisible=visibleRowsForX(second,xKey,xExt);
    const y2Ext=opts.secondExtent||extent(secondVisible.map(r=>r[opts.secondKey]),.08,!!opts.secondZero);
    const y2=r=>h-m.b-(num(r[opts.secondKey])-y2Ext[0])/(y2Ext[1]-y2Ext[0])*(h-m.t-m.b);
    plotLine(ctx,second,xm,y2,opts.secondColor||palette.red,2.1);
    for(const v of tickValues(y2Ext,5)){const y=ymVal(yExt[0]+(yExt[1]-yExt[0])*(v-y2Ext[0])/(y2Ext[1]-y2Ext[0]));ctx.fillStyle=opts.secondColor||palette.red;ctx.textAlign='left';ctx.font='10px Segoe UI';ctx.fillText(nice(v),w-m.r+6,y+3)}
  }
  ctx.font='10px Segoe UI';
  for(const v of tickValues(yExt,5)){const y=ymVal(v);ctx.fillStyle=palette.muted;ctx.textAlign='right';ctx.fillText(nice(v),m.l-6,y+3)}
  for(const v of tickValues(xExt,5)){const x=xmVal(v);ctx.fillStyle=palette.muted;ctx.textAlign='center';ctx.fillText(nice(v),x,h-m.b+18)}
}

function saneLateralRows(rows,xKey,yKey,maxAbs=5000,maxY=null){
  return arr(rows).filter(r=>{
    const x=num(r[xKey]), y=num(r[yKey]);
    if(x==null||y==null)return false;
    if(Math.abs(x)>maxAbs)return false;
    if(maxY!=null&&(y<0||y>maxY))return false;
    return true;
  });
}
function centeredLateralExtent(rows,key,minAbs=800,maxAbs=3500){
  const vals=arr(rows).map(r=>Math.abs(num(r[key])||0)).filter(Number.isFinite);
  const raw=Math.max(350,...vals);
  const rough=Math.max(minAbs,raw*1.18);
  const step=rough<=1500?500:1000;
  const lim=Math.min(maxAbs,Math.ceil(rough/step)*step);
  return [-lim,lim,step];
}
function drawApproachVertical(){
  const rows=arr(analysis?.approach?.profile).filter(r=>num(r.nm_to_threshold)!=null&&num(r.approach_agl_ft)!=null);
  const canvas=$('approachVertical');const {ctx,w,h}=fitCanvas(canvas);ctx.clearRect(0,0,w,h);
  if(rows.length<2)return noData(ctx,w,h);
  const m=axes(ctx,w,h,'NM TO THRESHOLD','ALTITUDE AGL (FT)','GROUNDSPEED (KT)');
  const maxNm=Math.max(10,...rows.map(r=>num(r.nm_to_threshold)||0));
  const fullXExt=roundAxisExtent(0,maxNm,{includeZero:true,tickCount:5});
  const xExt=zoomedXExtent('approachVertical',fullXExt);
  const visible=visibleRowsForX(rows,'nm_to_threshold',xExt);
  const altMax=Math.max(300,...visible.map(r=>num(r.approach_agl_ft)||0),...visible.map(r=>(num(r.ideal_3deg_agl_ft)||0)+300));
  const altExt=roundAxisExtent(0,altMax,{includeZero:true,tickCount:5});
  const gsExt=extent(visible.map(r=>r.ground_speed_kts),.08,true);
  const xVal=nm=>m.l+(xExt[1]-nm)/(xExt[1]-xExt[0])*(w-m.l-m.r);
  const yAlt=ft=>h-m.b-(ft-altExt[0])/(altExt[1]-altExt[0])*(h-m.t-m.b);
  const yGs=kts=>h-m.b-(kts-gsExt[0])/(gsExt[1]-gsExt[0])*(h-m.t-m.b);
  const x=r=>xVal(num(r.nm_to_threshold)||0);
  const ya=r=>yAlt(num(r.approach_agl_ft)||0);
  canvas._opsChartRows={rows,xKey:'nm_to_threshold',yKeys:['approach_agl_ft','ideal_3deg_agl_ft','ground_speed_kts'],xExt,fullXExt,reverseX:true,title:'Final Approach Profile'};
  const idealY=r=>yAlt(num(r.ideal_3deg_agl_ft)||0);
  const ygs=r=>yGs(num(r.ground_speed_kts)||0);
  plotLine(ctx,rows,x,idealY,'rgba(132,154,183,.85)',2,[7,6]);
  const plus=rows.map(r=>({...r,ideal_3deg_agl_ft:(num(r.ideal_3deg_agl_ft)||0)+300}));
  const minus=rows.map(r=>({...r,ideal_3deg_agl_ft:Math.max(0,(num(r.ideal_3deg_agl_ft)||0)-300)}));
  plotLine(ctx,plus,x,idealY,palette.green,1.2,[4,4]);
  plotLine(ctx,minus,x,idealY,palette.green,1.2,[4,4]);
  plotLine(ctx,rows,x,ya,palette.blue,2.5);
  plotLine(ctx,rows,x,ygs,palette.red,2);
  ctx.font='10px Segoe UI';
  for(const v of tickValues(altExt,5)){const y=yAlt(v);ctx.fillStyle=palette.muted;ctx.textAlign='right';ctx.fillText(nice(v),m.l-6,y+3)}
  for(const v of tickValues(gsExt,5)){const y=yGs(v);ctx.fillStyle=palette.red;ctx.textAlign='left';ctx.fillText(nice(v),w-m.r+6,y+3)}
  for(const v of tickValues(xExt,5)){const xPos=xVal(v);ctx.fillStyle=palette.muted;ctx.textAlign='center';ctx.fillText(nice(v),xPos,h-m.b+18)}
}

function drawRunway(canvasId,data,mode){
  const canvas=$(canvasId);const {ctx,w,h}=fitCanvas(canvas);ctx.clearRect(0,0,w,h);
  const length=Math.max(3000,num(data?.runway_length_ft)||8000),widthFt=Math.max(80,num(data?.runway_width_ft)||150);
  const rawPath=arr(data?.runway_path);
  const path=rawPath.map(p=>({along_ft:num(p.along_ft),deviation_ft:num(p.deviation_ft)||0,ground_speed_kts:num(p.ground_speed_kts),time:p.time})).filter(p=>p.along_ft!=null&&p.deviation_ft!=null);
  const margin={l:82,r:82,t:48,b:62};const innerW=w-margin.l-margin.r,innerH=h-margin.t-margin.b;
  if(innerW<150||innerH<80)return noData(ctx,w,h);
  const displaced=Math.max(0,num(data?.displaced_threshold_ft)||0);const lda=num(data?.lda_ft)||Math.max(0,length-displaced);
  const maxDev=Math.max(widthFt*.8,...path.map(p=>Math.abs(p.deviation_ft||0)));
  const crossExtent=Math.max(widthFt*1.75,Math.min(widthFt*5.0,maxDev*1.18),260);
  const plotTop=margin.t,plotBottom=h-margin.b,plotH=plotBottom-plotTop;
  const yCenter=plotTop+plotH/2;
  const yVal=dev=>yCenter-(num(dev)||0)/crossExtent*(plotH/2);
  const xValRaw=ft=>margin.l+(ft/length)*innerW;
  const xVal=ft=>margin.l+(Math.max(0,Math.min(length,ft))/length)*innerW;
  const runwayTop=yVal(widthFt/2),runwayBottom=yVal(-widthFt/2),runwayH=runwayBottom-runwayTop;
  const thresholdX=xVal(displaced);

  ctx.font='10px Inter, Segoe UI';ctx.lineWidth=1;ctx.strokeStyle=palette.grid||palette.line;ctx.fillStyle=palette.muted;
  for(let i=0;i<=4;i++){
    const dev=-widthFt+i*(widthFt/2);
    const y=yVal(dev);ctx.beginPath();ctx.moveTo(margin.l,y);ctx.lineTo(margin.l+innerW,y);ctx.stroke();
  }
  ctx.textAlign='right';ctx.fillStyle=palette.cyan||'#71d9e9';
  ctx.fillText(`L ${Math.round(widthFt/2)}ft`,margin.l-12,yVal(widthFt/2)+3);
  ctx.fillText('CL',margin.l-12,yVal(0)+3);
  ctx.fillText(`R ${Math.round(widthFt/2)}ft`,margin.l-12,yVal(-widthFt/2)+3);

  ctx.fillStyle='rgba(45,54,62,.88)';ctx.fillRect(margin.l,runwayTop,innerW,runwayH);
  ctx.strokeStyle='rgba(245,247,248,.82)';ctx.lineWidth=.85;ctx.strokeRect(margin.l,runwayTop,innerW,runwayH);
  ctx.fillStyle='rgba(255,255,255,.02)';
  for(let gx=margin.l;gx<margin.l+innerW;gx+=12){for(let gy=runwayTop;gy<runwayBottom;gy+=10){ctx.fillRect(gx,gy,1,1)}}

  if(displaced>0){
    ctx.fillStyle='rgba(110,124,138,.70)';ctx.fillRect(margin.l,runwayTop,Math.max(0,thresholdX-margin.l),runwayH);
    ctx.strokeStyle='rgba(245,247,248,.9)';ctx.lineWidth=.95;ctx.beginPath();ctx.moveTo(thresholdX,runwayTop);ctx.lineTo(thresholdX,runwayBottom);ctx.stroke();
    ctx.strokeStyle='rgba(245,247,248,.75)';ctx.lineWidth=1.1;ctx.beginPath();ctx.moveTo(margin.l+16,yVal(0));ctx.lineTo(thresholdX-24,yVal(0));ctx.stroke();
    ctx.beginPath();ctx.moveTo(thresholdX-9,yVal(0));ctx.lineTo(thresholdX-26,yVal(0)-7);ctx.lineTo(thresholdX-26,yVal(0)+7);ctx.closePath();ctx.fillStyle='rgba(245,247,248,.9)';ctx.fill();
  }
  if(mode==='landing'){
    const tdzEnd=xVal(Math.min(length,displaced+3000));
    ctx.fillStyle='rgba(22,105,65,.30)';ctx.fillRect(thresholdX,runwayTop,Math.max(0,tdzEnd-thresholdX),runwayH);
  }
  ctx.strokeStyle='rgba(255,255,255,.70)';ctx.setLineDash([12,15]);ctx.lineWidth=1.05;ctx.beginPath();ctx.moveTo(margin.l+8,yVal(0));ctx.lineTo(margin.l+innerW-8,yVal(0));ctx.stroke();ctx.setLineDash([]);

  ctx.fillStyle='rgba(245,247,248,.88)';
  const stripeH=Math.max(1.4,runwayH*.028),stripeW=Math.max(8,innerW*.007);
  for(let i=-4;i<=4;i++){
    if(i===0)continue;
    const yy=yVal(i*widthFt/12)-stripeH/2;
    if(yy>runwayTop&&yy<runwayBottom)ctx.fillRect(thresholdX+7,yy,stripeW,stripeH);
  }
  if(mode==='landing'){
    const drawPair=(distanceFt,wPx,hPx)=>{
      if(displaced+distanceFt>=length)return;
      const x=xVal(displaced+distanceFt), topY=yVal(widthFt*.22)-hPx/2, botY=yVal(-widthFt*.22)-hPx/2;
      ctx.fillRect(x-wPx/2,topY,wPx,hPx);ctx.fillRect(x-wPx/2,botY,wPx,hPx);
    };
    const smallW=Math.max(15,innerW*.012),smallH=Math.max(2.0,runwayH*.032),aimW=Math.max(46,innerW*.040),aimH=Math.max(4.0,runwayH*.060);
    [500,1500,2000,2500].forEach(d=>drawPair(d,smallW,smallH));drawPair(1000,aimW,aimH);
  }

  const rwy=String(data?.runway||'').replace(/^RWY\s*/i,'').toUpperCase();const opposite=String(data?.opposite_runway||'').replace(/^RWY\s*/i,'').toUpperCase();
  ctx.save();ctx.fillStyle='rgba(245,247,248,.76)';ctx.font=`760 ${Math.max(10,Math.min(18,runwayH*.22))}px Inter, Segoe UI`;ctx.textAlign='center';ctx.textBaseline='middle';
  const drawIdent=(text,x,y,angle)=>{ctx.save();ctx.translate(x,y);ctx.rotate(angle);ctx.fillText(text,0,0);ctx.restore()};
  if(rwy)drawIdent(rwy,Math.min(thresholdX+Math.max(45,innerW*.038),xVal(displaced+420)),yVal(0),Math.PI/2);
  if(opposite)drawIdent(opposite,Math.max(margin.l+innerW-Math.max(45,innerW*.038),xVal(length-420)),yVal(0),-Math.PI/2);
  ctx.restore();

  const tickMax=Math.floor(length/1000);
  for(let i=0;i<=tickMax;i++){const x=xVal(i*1000);ctx.strokeStyle='rgba(255,255,255,.25)';ctx.beginPath();ctx.moveTo(x,runwayBottom);ctx.lineTo(x,runwayBottom+7);ctx.stroke();ctx.fillStyle=palette.muted;ctx.textAlign='center';ctx.font='10px Inter, Segoe UI';ctx.fillText(`${i*1000}`,x,runwayBottom+20)}
  if(path.length>=2){
    const display=path.filter(p=>p.along_ft>=-450&&p.along_ft<=length+450&&Math.abs(p.deviation_ft)<=crossExtent*.98);
    if(display.length>=2){
      const xMap=p=>xValRaw(p.along_ft);const yMap=p=>yVal(p.deviation_ft);
      plotLine(ctx,display,xMap,yMap,palette.blue,2.0);
      const excursions=display.filter(p=>Math.abs(p.deviation_ft)>widthFt/2);
      ctx.fillStyle=palette.amber||'#f2b94b';
      for(const p of excursions.slice(0,160)){ctx.beginPath();ctx.arc(xMap(p),yMap(p),2.2,0,Math.PI*2);ctx.fill()}
    }
  }
  let marker=null,label='';
  if(mode==='landing'){
    const tdAlong=num(data.touchdown_distance_ft),tdDev=num(data.touchdown_centerline_deviation_ft);
    marker=tdAlong!=null&&tdDev!=null?{along_ft:tdAlong,deviation_ft:tdDev}:null;label='TD';
  }
  else{marker=path.find(p=>num(data.liftoff_distance_ft)!=null&&Math.abs(p.along_ft-num(data.liftoff_distance_ft))<120)||path.at(-1)||null;label='LO'}
  if(marker){const mx=xValRaw(marker.along_ft),my=yVal(marker.deviation_ft);ctx.beginPath();ctx.arc(mx,my,6.8,0,Math.PI*2);ctx.fillStyle=palette.green;ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=1.35;ctx.stroke();ctx.fillStyle='#061018';ctx.textAlign='center';ctx.font='800 7.2px Inter, Segoe UI';ctx.fillText(label,mx,my+2.5)}

  ctx.fillStyle=palette.muted;ctx.font='11px Inter, Segoe UI';ctx.textAlign='left';ctx.fillText(mode==='landing'?'THRESHOLD / TOUCHDOWN ZONE':'THRESHOLD / TAKEOFF ROLL',margin.l,Math.max(14,runwayTop-14));ctx.textAlign='right';ctx.fillText('RUNWAY END',margin.l+innerW,Math.max(14,runwayTop-14));ctx.textAlign='center';ctx.fillText(`${Math.round(lda).toLocaleString()}ft LDA · ${Math.round(length).toLocaleString()}ft × ${Math.round(widthFt)}ft`,w/2,h-16);
}



function renderMetrics(){
  const f=entry.flight||{},a=entry.aircraft||{},d=entry.durations||{},m=entry.metrics||{};
  const fuel=entry.fuel||{},times=entry.times||{};
  const dep=analysis.departure||{},en=analysis.enroute||{},app=analysis.approach||{},land=analysis.landing||{};
  const score=analysis.score||entry.debrief||{};
  $('flightCallsign').textContent=f.callsign||'UNASSIGNED';
  if($('airlineLogoTop'))$('airlineLogoTop').innerHTML=pirepBrandHtml('small',false);
  if($('airlineHero'))$('airlineHero').innerHTML=`${pirepBrandHtml('large',true)}<div><b>${esc(f.callsign||'FLIGHT')}</b><span>${esc(f.origin||'----')} ? ${esc(f.destination||'----')}</span><small>${esc([f.aircraft,f.registration].filter(Boolean).join(' · '))}</small></div>`;
  if($('financeAirlineIdentity'))$('financeAirlineIdentity').innerHTML=pirepBrandHtml('medium',true);
  $('flightRoute').textContent=`${f.origin||'----'} ? ${f.destination||'----'}`;
  $('originIcao').textContent=f.origin||'----';
  $('destinationIcao').textContent=f.destination||'----';
  $('aircraftLine').textContent=[f.aircraft_icao||a.type||a.model||a.title,f.registration,entry.telemetry_source?`DATA: ${String(entry.telemetry_source).toUpperCase()}`:''].filter(Boolean).join(' · ')||'AIRCRAFT NOT REPORTED';
  $('overallScore').textContent=score.overall??entry.debrief?.score??'--';
  $('overallGrade').textContent=score.grade||entry.debrief?.landing_grade||'NOT GRADED';
  $('geometrySource').textContent=analysis.geometry_source||'TELEMETRY-DERIVED RUNWAY ANALYSIS';
  $('summaryMetrics').innerHTML=[
    metric('Block Time',duration(d.block_seconds)),metric('Airborne',duration(d.airborne_seconds)),
    metric('Distance',fmt(cvDist(m.distance_nm),1,uDist())),metric('Fuel Used',fmt(cvWeight(fuel.used_lb),0,uWeight())),
    metric('Takeoff',utc(times.takeoff),'UTC'),metric('Landing',utc(times.landing),'UTC'),
    metric('Max Altitude',fmt(cvAlt(m.max_altitude_ft),0,uAlt())),metric('Landing Rate',fmt(cvVs(m.landing_rate_fpm),0,uVs())),
    metric('Touchdown G',fmt(m.touchdown_g,2,'G')),metric('Touchdown Speed',fmt(cvSpeed(m.touchdown_speed_kts),0,uSpeed())),
    metric('Rating',entry.rating?`${entry.rating} / 5`:'NOT RATED'),metric('Samples',fmt(entry.sample_count,0,''))
  ].join('');
  $('departureRunway').textContent=`RWY ${dep.runway||f.departure_runway||'----'}`;
  $('approachRunway').textContent=`RWY ${app.runway||f.arrival_runway||'----'}`;
  $('landingRunway').textContent=`RWY ${land.runway||f.arrival_runway||'----'}`;
  $('departureMetrics').innerHTML=[
    metric('Liftoff Speed',fmt(cvSpeed(dep.liftoff_speed_kts),0,uSpeed())),metric('Pitch',fmt(dep.liftoff_pitch_deg,1,'°')),
    metric('Bank',fmt(dep.liftoff_bank_deg,1,'°')),metric('Takeoff Roll',fmt(cvAlt(dep.takeoff_roll_ft),0,uAlt()),dep.takeoff_roll_percent!=null?`${dep.takeoff_roll_percent}% EST. RUNWAY`:''),
    metric('Climb Gradient',fmt(dep.climb_gradient_ft_nm,0,'FT/NM')),metric('Climb Rate',fmt(cvVs(dep.average_initial_climb_fpm),0,uVs())),
    metric('Max CL Deviation',fmt(cvAlt(dep.max_centerline_deviation_ft),0,uAlt())),metric('Runway Heading',fmt(dep.heading_deg,1,'°')),
    metric('Gear Up',utc(dep.gear_up_time),'UTC'),metric('Flaps Up',utc(dep.flaps_up_time),'UTC')
  ].join('');
  $('enrouteMetrics').innerHTML=[
    metric('Planned Distance',fmt(cvDist(en.planned_distance_nm),1,uDist())),metric('Actual Distance',fmt(cvDist(en.actual_distance_nm),1,uDist())),
    metric('Distance Variance',fmt(cvDist(en.distance_variance_nm),1,uDist())),metric('Planned Fuel',fmt(cvWeight(en.planned_trip_fuel),0,uWeight())),
    metric('Actual Fuel',fmt(cvWeight(en.actual_fuel_used_lb),0,uWeight())),metric('Fuel Variance',fmt(cvWeight(en.fuel_variance),0,uWeight())),
    metric('Planned Block',duration(en.planned_block_seconds)),metric('Actual Block',duration(en.actual_block_seconds)),
    metric('Planned Airborne',duration(en.planned_airborne_seconds)),metric('Actual Airborne',duration(en.actual_airborne_seconds))
  ].join('');
  $('approachMetrics').innerHTML=[
    metric('Max Lateral Dev',fmt(cvAlt(app.max_lateral_deviation_ft),0,uAlt())),metric('Max Vertical Dev',fmt(cvAlt(app.max_glidepath_deviation_ft),0,uAlt())),
    metric('Gear Down',fmt(cvDist(app.gear_down_distance_nm),1,uDist()),'FROM THRESHOLD'),metric('Landing Flap',fmt(cvDist(app.landing_flap_distance_nm),1,uDist()),'FROM THRESHOLD'),
    metric('Approach Heading',fmt(app.heading_deg,1,'°')),metric('Analyzed Distance',arr(app.profile).some(x=>num(x.nm_to_threshold)!=null)?fmt(cvDist(Math.max(...arr(app.profile).map(x=>num(x.nm_to_threshold)).filter(x=>x!=null))),1,uDist()):'--')
  ].join('');
  $('landingMetrics').innerHTML=[
    metric('Touchdown Rate',fmt(cvVs(land.touchdown_rate_fpm),0,uVs())),metric('G-Force',fmt(land.touchdown_g,2,'G')),
    metric('TD Point',fmt(cvAlt(land.touchdown_distance_ft),0,uAlt()),land.touchdown_percent!=null?`${land.touchdown_percent}% OF EST. LENGTH`:''),
    metric('Centerline Dev',fmt(cvAlt(land.touchdown_centerline_deviation_ft),0,uAlt())),metric('Rollout',fmt(cvAlt(land.rollout_distance_ft),0,uAlt())),
    metric('Touchdown Speed',fmt(cvSpeed(land.touchdown_speed_kts),0,uSpeed())),metric('Pitch',fmt(land.touchdown_pitch_deg,1,'°')),
    metric('Bank',fmt(land.touchdown_bank_deg,1,'°')),metric('Touchdowns',fmt(land.touchdowns,0,'')),
    metric('Distance Remaining',fmt(cvAlt(land.distance_remaining_at_touchdown_ft),0,uAlt()))
  ].join('');
}
function renderFlags(){const violations=entry.violations||[];const flags=[];if(analysis.approach?.stability_1000?.stable===false)flags.push({text:'UNSTABLE AT 1000 FT',level:'warning'});if(analysis.approach?.stability_500?.stable===false)flags.push({text:'UNSTABLE AT 500 FT',level:'critical'});if((analysis.landing?.touchdowns||0)>1)flags.push({text:`${analysis.landing.touchdowns} TOUCHDOWNS`,level:'warning'});for(const v of violations.slice(-8))flags.push({text:v.title||v.key||'FLIGHT FLAG',level:Number(v.penalty||0)>=8?'critical':'warning'});if(!flags.length)flags.push({text:'NO MAJOR DEVIATIONS',level:'good'});$('flagStrip').innerHTML=flags.map(x=>`<span class="flag ${x.level}">${esc(x.text)}</span>`).join('')}
function renderEvents(){const events=entry.events||[];$('eventChips').innerHTML=events.filter(x=>/PUSH|ENGINE|FLAP|GEAR|TAKEOFF|TOUCHDOWN|LANDING|STABILITY|TOP OF/i.test(`${x.kind} ${x.detail}`)).slice(-18).map(x=>`<span class="event-chip"><strong>${esc(utc(x.time))}</strong>${esc(x.kind||'EVENT')}</span>`).join('')||'<span class="event-chip">NO EVENT MARKERS</span>';const start=new Date(entry.started_utc||0).getTime();const end=new Date(entry.completed_utc||Date.now()).getTime();const phases=[];let active=null;for(const s of samples){const phase=String(s.phase||'UNKNOWN');if(!active||active.phase!==phase){if(active)phases.push(active);active={phase,start:num(s.elapsed_seconds)||0,end:num(s.elapsed_seconds)||0}}else active.end=num(s.elapsed_seconds)||active.end}if(active)phases.push(active);const total=Math.max(1,...phases.map(x=>x.end));const colors=['#315e6b','#394f7a','#6a4f86','#825634','#476744','#79524d','#655c35','#3f5968'];$('phaseStrip').innerHTML=phases.map((p,i)=>`<div class="phase-segment" title="${esc(p.phase)}" style="width:${Math.max(.4,(p.end-p.start)/total*100)}%;background:${colors[i%colors.length]}">${(p.end-p.start)/total>0.08?esc(p.phase):''}</div>`).join('')}
function renderStability(){const gates=[analysis.approach?.stability_1000,analysis.approach?.stability_500].filter(Boolean);$('stabilityGates').innerHTML=gates.map(g=>{const status=g.available?(g.stable?'STABLE':'UNSTABLE'):'NO DATA';const cls=g.available?(g.stable?'stable':'unstable'):'unknown';return `<article class="gate"><div class="gate-head"><h3>${esc(g.target_agl_ft)} FT GATE</h3><span class="gate-status ${cls}">${status}</span></div><div class="gate-checks">${(g.checks||[]).map(c=>`<div class="gate-check ${c.ok?'':'fail'}"><span>${esc(c.label)}</span><b>${esc(c.value)}</b></div>`).join('')}</div></article>`}).join('')||'<div class="empty">No stability-gate data was available.</div>'}
function renderScore(){const score=analysis.score||{},max={departure:15,enroute:20,approach:25,landing:25,integrity:15};$('scoreBreakdown').innerHTML=Object.entries(max).map(([key,total])=>{const value=num(score.breakdown?.[key])||0;return `<div class="score-row"><span>${key.toUpperCase()}</span><div class="score-track"><div class="score-fill" style="width:${Math.max(0,Math.min(100,value/total*100))}%"></div></div><b>${value} / ${total}</b></div>`}).join('')}

function moneyP(value,symbol=''){const n=Number(value);return Number.isFinite(n)?`${symbol}${Math.round(n).toLocaleString()}`:'--'}
function financeSourceLabel(value){const key=String(value||'').toLowerCase();if(key==='gsx')return 'GSX receipt';if(key==='estimated-from-departure')return 'Estimated from departure';if(key==='estimated-from-arrival')return 'Estimated from arrival';if(key==='ops-room-estimate')return 'OPS ROOM estimate';return key==='mixed'?'GSX + estimate':key==='estimated'?'Estimated':key||'Not available'}
function renderFinance(){
  const enabled=settings?.interface?.finance_career_enabled!==false;
  const section=$('finance'),link=document.querySelector('.section-nav a[href="#finance"]');
  if(section)section.hidden=!enabled;if(link)link.hidden=!enabled;
  if(!enabled)return;
  const fin=entry.finance,attachedReceipts=arr(entry.gsx_invoices);
  const statementReceipts=arr(fin?.airline?.invoices),visibleReceipts=statementReceipts.length?statementReceipts:attachedReceipts;
  const receiptHtml=visibleReceipts.length?`<div class="metric-tile finance-wide finance-invoices"><span>GSX service receipts</span>${visibleReceipts.map(inv=>{
    const src=inv.display_amount||((inv.currency&&inv.amount!=null)?`${esc(inv.currency)} ${Number(inv.amount).toLocaleString(undefined,{maximumFractionDigits:2})}`:'');
    const lines=arr(inv.line_items).slice(0,8).map(li=>`<li><span>${esc(li.item||'Service')}</span><b>${esc(li.currency||inv.currency||'')} ${Number(li.amount||0).toLocaleString(undefined,{maximumFractionDigits:2})}</b></li>`).join('');
    const context=[inv.phase?String(inv.phase).toUpperCase():'',inv.airport||'',inv.category||inv.service||''].filter(Boolean).join(' · ');
    return `<section class="invoice-card"><strong>${esc(inv.operator||inv.title||'GSX')}</strong>${context?`<small>${esc(context)}</small>`:''}${src?`<small>Receipt total ${esc(src)}</small>`:''}${lines?`<ul>${lines}</ul>`:''}${inv.url?`<a href="${esc(inv.url)}" target="_blank" rel="noopener">OPEN RECEIPT</a>`:''}</section>`
  }).join('')}</div>`:'';
  if(!fin||!fin.ok){
    $('financeReport').innerHTML=(receiptHtml||'<div class="empty finance-wide">No matching GSX receipts were found for this PIREP.</div>')+`<div class="empty finance-wide">Finance statement unavailable${fin?.reason?`: ${esc(fin.reason)}`:'. Reopen this PIREP to rebuild it.'}</div>`;
    return;
  }
  const sym=fin.symbol||'',air=fin.airline||{},pilot=fin.pilot||{},route=fin.route||{},open=fin.opening_balance||{},close=fin.closing_balance||{};
  const invoiceHtml=receiptHtml||`<div class="metric-tile finance-wide"><span>GSX service receipts</span><strong>No matching GSX receipts</strong><small>Departure and arrival service costs were estimated automatically.</small></div>`;
  $('financeReport').innerHTML=[
    metric('Airline opening balance',moneyP(open.airline,sym),fin.currency||''),
    metric('Airline revenue',moneyP(air.revenue?.total,sym),`Pax ${moneyP(air.revenue?.passenger,sym)} · Cargo ${moneyP(air.revenue?.cargo,sym)}`),
    metric('Airline costs',moneyP(air.costs?.total,sym),`Fuel ${moneyP(air.costs?.fuel,sym)} · Ground services ${moneyP(air.costs?.ground_services,sym)}`),
    metric('Departure services',moneyP(air.costs?.ground_services_departure,sym),financeSourceLabel(air.costs?.ground_services_departure_source)),
    metric('Arrival services',moneyP(air.costs?.ground_services_arrival,sym),financeSourceLabel(air.costs?.ground_services_arrival_source)),
    metric('Airline flight result',moneyP(air.profit,sym),`${route.origin||'----'} ? ${route.destination||'----'}`),
    metric('Airline closing balance',moneyP(close.airline,sym),''),
    metric('Pilot opening balance',moneyP(open.pilot,sym),''),
    metric('Pilot flight pay',moneyP(pilot.pay,sym),`${pilot.rank?.label||'Pilot'}`),
    metric('Pilot closing balance',moneyP(close.pilot,sym),''),
  ].join('') + invoiceHtml;
}

function setupInteractiveCharts(){
  document.querySelectorAll('.chart-card').forEach(card=>{
    if(card.dataset.interactiveReady)return;
    const wrap=card.querySelector('.canvas-wrap'),canvas=card.querySelector('canvas');if(!wrap||!canvas||!canvas._opsChartRows)return;
    card.dataset.interactiveReady='1';let drag=null;
    const tools=document.createElement('div');tools.className='chart-tools';tools.innerHTML='<button type="button" data-zoom="in">ZOOM +</button><button type="button" data-zoom="out">ZOOM ?</button><button type="button" data-zoom="reset">RESET</button>';card.appendChild(tools);
    tools.addEventListener('click',event=>{const button=event.target.closest('button');if(!button)return;if(button.dataset.zoom==='reset')resetChartZoom(canvas);else setChartZoomDomain(canvas,.5,button.dataset.zoom==='in',.5)});
    wrap.addEventListener('wheel',event=>{event.preventDefault();const rect=wrap.getBoundingClientRect(),pctX=(event.clientX-rect.left)/Math.max(1,rect.width),pctY=(event.clientY-rect.top)/Math.max(1,rect.height);setChartZoomDomain(canvas,pctX,event.deltaY<0,pctY)},{passive:false});
    wrap.addEventListener('pointerdown',event=>{const data=canvas._opsChartRows,state=chartZoomState[canvas.id];if(!data||!state)return;drag={x:event.clientX,y:event.clientY,domain:{...state},full:data.fullXExt,fullY:data.fullYExt,route2d:!!data.route2d};wrap.setPointerCapture?.(event.pointerId)});
    wrap.addEventListener('pointermove',event=>{
      showChartTip(event,card,canvas);if(!drag)return;
      const rect=wrap.getBoundingClientRect(),full=drag.full||canvas._opsChartRows?.fullXExt;if(!full)return;
      const span=drag.domain.hi-drag.domain.lo,deltaX=-(event.clientX-drag.x)/Math.max(1,rect.width)*span;let lo=drag.domain.lo+deltaX,hi=drag.domain.hi+deltaX;if(lo<full[0]){hi+=full[0]-lo;lo=full[0]}if(hi>full[1]){lo-=hi-full[1];hi=full[1]}
      const next={lo,hi};
      if(drag.route2d&&drag.fullY&&Number.isFinite(drag.domain.yLo)&&Number.isFinite(drag.domain.yHi)){
        const ySpan=drag.domain.yHi-drag.domain.yLo,deltaY=(event.clientY-drag.y)/Math.max(1,rect.height)*ySpan;let yLo=drag.domain.yLo+deltaY,yHi=drag.domain.yHi+deltaY;if(yLo<drag.fullY[0]){yHi+=drag.fullY[0]-yLo;yLo=drag.fullY[0]}if(yHi>drag.fullY[1]){yLo-=yHi-drag.fullY[1];yHi=drag.fullY[1]}next.yLo=yLo;next.yHi=yHi;
      }
      chartZoomState[canvas.id]=next;renderAll();
    });
    wrap.addEventListener('pointerup',()=>{drag=null});wrap.addEventListener('pointercancel',()=>{drag=null});wrap.addEventListener('pointerleave',()=>{drag=null;hideChartTip()});
  });
}

let chartTip=null;
function showChartTip(event,card,canvas){
  if(!chartTip){chartTip=document.createElement('div');chartTip.className='chart-tip';document.body.appendChild(chartTip)}
  const rect=canvas.getBoundingClientRect();const pct=Math.max(0,Math.min(1,(event.clientX-rect.left)/Math.max(1,rect.width)));const title=card.querySelector('h3')?.textContent||canvas._opsChartRows?.title||'CHART';
  let detail='Zoom with mouse wheel/pinch. Drag when zoomed.';
  const data=canvas._opsChartRows;
  if(data&&Array.isArray(data.rows)&&data.rows.length&&Array.isArray(data.xExt)){
    const [lo,hi]=data.xExt;let target=lo+(hi-lo)*pct;if(data.reverseX)target=hi-(hi-lo)*pct;
    let nearest=data.rows[0],best=Infinity;
    for(const row of data.rows){const xv=num(row[data.xKey]);if(xv==null)continue;const d=Math.abs(xv-target);if(d<best){best=d;nearest=row}}
    const yText=(data.yKeys||[]).slice(0,3).map(k=>`${String(k).replaceAll('_',' ')} ${nice(num(nearest[k]))}`).join(' · ');
    detail=`${String(data.xKey||'x').replaceAll('_',' ')} ${nice(num(nearest[data.xKey]))}${yText?' · '+yText:''}`;
  }
  chartTip.innerHTML=`${esc(title)}<small>${esc(detail)}</small>`;chartTip.style.left=`${event.clientX+14}px`;chartTip.style.top=`${event.clientY+14}px`;chartTip.hidden=false
}
function hideChartTip(){if(chartTip)chartTip.hidden=true}

function renderReview(){const violations=entry.violations||[];$('violationList').innerHTML=violations.length?violations.slice().reverse().map(v=>`<div class="review-item ${Number(v.penalty||0)>=8?'critical':'warning'}"><time>${esc(utc(v.time))}</time><div><b>${esc(v.title||v.key||'DEVIATION')}</b><p>${esc(v.detail||'')}</p></div></div>`).join(''):'<div class="empty">No recorded deviations.</div>';const events=entry.events||[];$('timelineList').innerHTML=events.length?events.slice().reverse().slice(0,120).map(e=>`<div class="review-item ${esc(e.severity||'')}"><time>${esc(utc(e.time))}</time><div><b>${esc(e.kind||'EVENT')}</b><p>${esc(e.detail||'')}</p></div></div>`).join(''):'<div class="empty">No timeline events were recorded.</div>';$('pilotNotes').textContent=entry.notes||'No notes were added to this flight.'}

function latLonPoint(item){
  if(!item||typeof item!=='object')return null;
  const lat=num(item.lat ?? item.latitude ?? item.lat_deg ?? item.latitude_deg);
  const lon=num(item.lon ?? item.lng ?? item.longitude ?? item.lon_deg ?? item.longitude_deg);
  if(lat==null||lon==null||Math.abs(lat)>90||Math.abs(lon)>180)return null;
  return {lat,lon,label:String(item.ident||item.name||item.waypoint||item.icao||item.type||'').trim()};
}
function drawRoute(){
  const canvas=$('routeChart');if(!canvas)return;
  const {ctx,w,h}=fitCanvas(canvas);ctx.clearRect(0,0,w,h);
  const actual=arr(samples).map(latLonPoint).filter(Boolean),planned=arr(telemetry?.route||entry?.flight?.navlog).map(latLonPoint).filter(Boolean),all=[...actual,...planned];
  if(all.length<2)return noData(ctx,w,h,'NO ROUTE POSITION DATA');
  const base=planned[0]||actual[0]||all[0],lat0=all.reduce((sum,p)=>sum+p.lat,0)/all.length,cosLat=Math.max(.15,Math.cos(lat0*Math.PI/180));
  const xy=(p,series)=>({route_x:(p.lon-base.lon)*60*cosLat,route_y:(p.lat-base.lat)*60,label:p.label,series});
  const actualXY=actual.map(p=>xy(p,'actual')),plannedXY=planned.map(p=>xy(p,'planned')),allXY=[...actualXY,...plannedXY];
  const fullXExt=extent(allXY.map(p=>p.route_x),.04),fullYExt=extent(allXY.map(p=>p.route_y),.04),state=chartZoomState.routeChart;
  const xExt=zoomedXExtent('routeChart',fullXExt),rawY=(state&&Number.isFinite(state.yLo)&&Number.isFinite(state.yHi)&&state.yHi>state.yLo)?[state.yLo,state.yHi,niceStep((state.yHi-state.yLo)/6)]:fullYExt;
  let xMin=xExt[0],xMax=xExt[1],yMin=rawY[0],yMax=rawY[1];
  const m={l:64,r:30,t:28,b:48},plotW=w-m.l-m.r,plotH=h-m.t-m.b;let spanX=Math.max(.001,xMax-xMin),spanY=Math.max(.001,yMax-yMin);
  const target=plotW/Math.max(1,plotH);if(spanX/spanY>target){const wanted=spanX/target,add=(wanted-spanY)/2;yMin-=add;yMax+=add;spanY=wanted}else{const wanted=spanY*target,add=(wanted-spanX)/2;xMin-=add;xMax+=add;spanX=wanted}
  const mapX=p=>m.l+(p.route_x-xMin)/spanX*plotW,mapY=p=>h-m.b-(p.route_y-yMin)/spanY*plotH;
  ctx.strokeStyle=palette.grid||palette.line;ctx.lineWidth=1;ctx.font='10px Inter, Segoe UI';ctx.fillStyle=palette.muted;
  const xTicks=tickValues([xMin,xMax,niceStep(spanX/6)],6),yTicks=tickValues([yMin,yMax,niceStep(spanY/6)],6);
  for(const value of xTicks){const x=m.l+(value-xMin)/spanX*plotW;ctx.beginPath();ctx.moveTo(x,m.t);ctx.lineTo(x,h-m.b);ctx.stroke();ctx.textAlign='center';ctx.fillText(nice(value),x,h-m.b+17)}
  for(const value of yTicks){const y=h-m.b-(value-yMin)/spanY*plotH;ctx.beginPath();ctx.moveTo(m.l,y);ctx.lineTo(w-m.r,y);ctx.stroke();ctx.textAlign='right';ctx.fillText(nice(value),m.l-7,y+3)}
  ctx.textAlign='center';ctx.fillText('E / W OFFSET (NM)',w/2,h-8);ctx.save();ctx.translate(14,h/2);ctx.rotate(-Math.PI/2);ctx.fillText('N / S OFFSET (NM)',0,0);ctx.restore();
  const line=(pts,color,width=2,dash=[])=>{if(pts.length<2)return;ctx.save();ctx.beginPath();ctx.rect(m.l,m.t,plotW,plotH);ctx.clip();ctx.beginPath();let started=false;for(const p of pts){const x=mapX(p),y=mapY(p);if(!Number.isFinite(x)||!Number.isFinite(y)){started=false;continue}if(!started){ctx.moveTo(x,y);started=true}else ctx.lineTo(x,y)}ctx.strokeStyle=color;ctx.lineWidth=width;ctx.setLineDash(dash);ctx.stroke();ctx.restore()};
  line(plannedXY,'rgba(132,154,183,.75)',1.7,[7,6]);line(actualXY,palette.blue,2.5,[]);
  const marker=(p,label,color)=>{if(!p||p.route_x<xMin||p.route_x>xMax||p.route_y<yMin||p.route_y>yMax)return;const x=mapX(p),y=mapY(p);ctx.beginPath();ctx.arc(x,y,5.8,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=1.4;ctx.stroke();ctx.fillStyle=palette.text;ctx.font='800 9px Inter, Segoe UI';ctx.textAlign='center';ctx.fillText(label,x,y-10)};
  marker(actualXY[0]||plannedXY[0],'START',palette.green);marker(actualXY.at(-1)||plannedXY.at(-1),'END',palette.red);
  canvas._opsChartRows={rows:allXY,xKey:'route_x',yKeys:['route_y'],xExt,fullXExt,yExt:rawY,fullYExt,route2d:true,title:'Actual Track / Planned Route'};
  ctx.textAlign='left';ctx.fillStyle=palette.muted;ctx.font='10px Inter, Segoe UI';ctx.fillText('PLANNED ROUTE',m.l,m.t-10);ctx.fillStyle=palette.blue;ctx.fillText('ACTUAL TRACK',m.l+110,m.t-10);
}
function drawLandingCharts(){
  const landingTimeRows=arr(samples).filter(r=>num(r.seconds_to_touchdown)!=null&&num(r.seconds_to_touchdown)>=-35&&num(r.seconds_to_touchdown)<=45);
  const attitude=landingTimeRows.filter(r=>num(r.pitch_deg)!=null||num(r.bank_deg)!=null);
  if(attitude.length>=2){
    drawXY('landingAttitude',attitude,'seconds_to_touchdown','pitch_deg',{xLabel:'SECONDS FROM TOUCHDOWN',yLabel:'PITCH (°)',rightLabel:'BANK (°)',secondKey:'bank_deg',secondColor:palette.red,reference:[{axis:'x',value:0,color:palette.green,dash:[4,4]},{axis:'y',value:0,color:palette.muted,dash:[3,5]}]});
  }else{
    const canvas=$('landingAttitude'); if(canvas){const {ctx,w,h}=fitCanvas(canvas);ctx.clearRect(0,0,w,h);noData(ctx,w,h,'NO LANDING ATTITUDE DATA')}
  }
  const force=landingTimeRows.filter(r=>num(r.g_force)!=null||num(r.radio_altitude_ft)!=null||num(r.agl_ft)!=null).map(r=>({...r,landing_agl_ft:num(r.radio_altitude_ft)!=null?num(r.radio_altitude_ft):num(r.agl_ft)}));
  if(force.length>=2){
    drawXY('landingForce',force,'seconds_to_touchdown','g_force',{xLabel:'SECONDS FROM TOUCHDOWN',yLabel:'G-FORCE',rightLabel:'RADIO ALT (FT)',secondKey:'landing_agl_ft',secondColor:palette.cyan,reference:[{axis:'x',value:0,color:palette.green,dash:[4,4]},{axis:'y',value:1,color:palette.muted,dash:[3,5]}]});
  }else{
    const canvas=$('landingForce'); if(canvas){const {ctx,w,h}=fitCanvas(canvas);ctx.clearRect(0,0,w,h);noData(ctx,w,h,'NO TOUCHDOWN FORCE DATA')}
  }
}
function renderSection(name,fn){
  try{fn();return true}catch(error){console.error(`PIREP ${name} render failed`,error);renderFailures.push(name);return false}
}
function finishReportStatus(){
  const stamp=new Date().toISOString().slice(0,19).replace('T',' ');
  $('reportGenerated').textContent=renderFailures.length?`REPORT ${stamp}Z · ${renderFailures.length} SECTION WARNING${renderFailures.length>1?'S':''}`:`REPORT ${stamp}Z`;
  document.title=`${entry?.flight?.callsign||'OPS ROOM'} · ${entry?.flight?.origin||'----'}-${entry?.flight?.destination||'----'} · PIREP`;
}

async function downloadPirepPdf(button,id){
  const original=button?.textContent||'SAVE PDF';
  if(button){button.disabled=true;button.textContent='GENERATING PDF...'}
  try{
    const response=await fetch(`/api/logbook/${encodeURIComponent(id)}/export.pdf`,{cache:'no-store'});
    if(!response.ok){let detail='Full PIREP PDF could not be generated.';try{const data=await response.json();detail=data.detail||detail}catch{}throw new Error(detail)}
    const blob=await response.blob();if(!blob.size||!String(blob.type||'').includes('pdf'))throw new Error('The PDF renderer returned an invalid file.');
    const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=`OPS_ROOM_PIREP_${String(id||'').slice(0,8)}.pdf`;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
  }catch(error){alert(error.message||'Full PIREP PDF could not be generated.');}
  finally{if(button){button.disabled=false;button.textContent=original}}
}

let renderFailures=[];
function renderAll(){
  analysis=telemetry.analysis||entry.analysis_summary||{};
  samples=arr(telemetry.samples);
  renderFailures=[];
  renderSection('summary',()=>{renderMetrics();renderFlags();renderEvents();renderScore();renderReview();renderFinance();});
  renderSection('stability gates',()=>renderStability());
  renderSection('flight profile',()=>drawProfile());
  renderSection('departure',()=>{
    const depLat=saneLateralRows(arr(analysis.departure?.lateral_profile),'deviation_ft','distance_nm',5000,null);
    drawXY('departureLateral',depLat,'deviation_ft','distance_nm',{xLabel:'CENTERLINE DEVIATION (FT)',yLabel:'DISTANCE FLOWN (NM)',xZero:true,xExtent:centeredLateralExtent(depLat,'deviation_ft',500,2500),reference:[{axis:'x',value:0,color:palette.muted,dash:[5,4]}]});
    drawXY('departureClimb',arr(analysis.departure?.climb_profile),'distance_nm','altitude_agl_ft',{xLabel:'DISTANCE FLOWN (NM)',yLabel:'ALTITUDE AGL (FT)',rightLabel:'GROUNDSPEED (KT)',secondKey:'ground_speed_kts',secondColor:palette.red,xZero:true,yZero:true});
    drawRunway('departureRunwayChart',analysis.departure||{},'departure');
  });
  renderSection('enroute',()=>{
    drawRoute();
    drawXY('fuelChart',samples.map(r=>({...r,fuel_total_display:cvWeight(r.fuel_total_lb),elapsed_minutes:num(r.elapsed_seconds)!=null?num(r.elapsed_seconds)/60:null})),'elapsed_minutes','fuel_total_display',{xLabel:'ELAPSED MINUTES',yLabel:`FUEL REMAINING (${uWeight()})`,primaryLabel:`Fuel remaining (${uWeight()})`,xZero:true});
  });
  renderSection('approach',()=>{
    const appLat=saneLateralRows(arr(analysis.approach?.profile),'lateral_deviation_ft','nm_to_threshold',5000,15);
    drawXY('approachLateral',appLat,'lateral_deviation_ft','nm_to_threshold',{xLabel:'CENTERLINE DEVIATION (FT)',yLabel:'NM TO THRESHOLD',xZero:true,xExtent:centeredLateralExtent(appLat,'lateral_deviation_ft',1000,3000),localizerCone:{deg:2.5,color:'rgba(118,139,163,.72)',dash:[6,6]},reference:[{axis:'x',value:0,color:palette.muted,dash:[5,4]}]});
    drawApproachVertical();
  });
  renderSection('landing',()=>{
    drawRunway('landingRunwayChart',analysis.landing||{},'landing');
    drawLandingCharts();
  });
  finishReportStatus();
  setupInteractiveCharts();
}
async function boot(){
  try{
    const preloaded=window.__OPSROOM_PIREP_PRELOADED__||null;
    const id=String(preloaded?.entry?.id||flightId()||'');
    if(!id)throw new Error('No flight record was selected.');
    const pdfButton=$('pdfExport');if(pdfButton){pdfButton.disabled=true;if(!preloaded)pdfButton.addEventListener('click',()=>downloadPirepPdf(pdfButton,id))}if(preloaded||new URLSearchParams(location.search).get('pdf_render')==='1')document.documentElement.classList.add('pdf-render');
    let e,t,s;
    if(preloaded){e={entry:preloaded.entry};t=preloaded.telemetry;s=preloaded.settings||{};}
    else{[e,t,s]=await Promise.all([getJson(`/api/logbook/${encodeURIComponent(id)}`),getJson(`/api/logbook/${encodeURIComponent(id)}/telemetry?max_points=5000`),getJson('/api/settings/public')]);}
    entry=e.entry;telemetry=t;settings=s;
    $('scoringRules')?.addEventListener('click',()=>window.open('/scoring-rules','_blank','noopener'));
    if(!entry||!telemetry.ok)throw new Error('The flight report is incomplete.');
    $('loading').hidden=true;$('errorPanel').hidden=true;$('reportContent').hidden=false;$('report').setAttribute('aria-busy','false');
    renderAll();
    document.documentElement.dataset.pirepReady='1';window.__OPSROOM_PIREP_READY__=true;if($('pdfExport'))$('pdfExport').disabled=false;
    let timer;
    addEventListener('resize',()=>{clearTimeout(timer);timer=setTimeout(()=>renderAll(),160)});
    addEventListener('beforeprint',()=>renderAll());addEventListener('afterprint',()=>renderAll());
  }catch(error){
    $('loading').hidden=true;
    if($('reportContent')&&!$('reportContent').hidden){$('errorPanel').hidden=true;console.error('PIREP non-blocking error',error);}
    else{$('errorPanel').hidden=false;$('errorText').textContent=error.message||'The flight report could not be loaded.';}
    $('report').setAttribute('aria-busy','false');
  }
}
boot();
