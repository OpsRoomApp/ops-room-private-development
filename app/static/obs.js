const params=new URLSearchParams(location.search);
const view=params.get('view')||'flight';
const layout=params.get('layout')||'strip';
const position=params.get('position')||'center';
const fields=new Set((params.get('fields')||'route,callsign,altitude,groundspeed,phase').split(',').filter(Boolean));
const showLabels=params.get('labels')!=='0';
const showLogo=params.get('logo')==='1';
const brandingMode=['active_airline','custom','ops_room'].includes(params.get('branding'))?params.get('branding'):'active_airline';
const logoPosition=params.get('logo_position')==='right'?'right':'left';
const logoSize=Math.max(32,Math.min(160,Number(params.get('logo_size')||72)));
const opacity=Math.max(0,Math.min(1,Number(params.get('opacity')||.94)));
const scale=Math.max(.7,Math.min(1.6,Number(params.get('scale')||1)));
const accent=/^#[0-9a-f]{6}$/i.test(params.get('accent')||'')?params.get('accent'):'#76c4d3';
if(params.get('transparent')==='0')document.body.classList.add('opaque');
document.documentElement.style.setProperty('--accent',accent);
document.documentElement.style.setProperty('--panel',`rgba(13,16,18,${opacity})`);
document.documentElement.style.setProperty('--scale',scale);
document.documentElement.style.setProperty('--logo-size',`${logoSize}px`);
const root=document.getElementById('overlay');
root.className=`overlay position-${position} layout-${layout}${showLabels?'':' no-labels'}`;
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number=v=>{const n=Number(v);return Number.isFinite(n)?n:null};
const hm=v=>{if(!v)return'--:--';const d=new Date(v);return Number.isNaN(d.getTime())?'--:--':d.toISOString().slice(11,16)};
const fmt=(v,d=0,s='')=>number(v)==null?'--':`${Number(v).toLocaleString(undefined,{maximumFractionDigits:d,minimumFractionDigits:d})}${s}`;
const fmtAlt=v=>fmt(v,0,' ft');
const fmtSpd=v=>fmt(v,0,' kt');
const fmtVs=v=>fmt(v,0,' fpm');
const fmtDeg=v=>number(v)==null?'--':`${String(Math.round(Number(v))).padStart(3,'0')}°`;
const phaseText=(watch)=>{const raw=String(watch?.phase||watch?.state||'').trim().toUpperCase();return !watch?.ok||!raw||['STANDBY','OFFLINE','UNKNOWN'].includes(raw)?'--':raw};
function lamp(state){return['connected','running','detected','configured','loaded'].includes(state)?'green':['standby','cached'].includes(state)?'amber':['fault','failed'].includes(state)?'red':''}
async function json(url){const r=await fetch(url,{cache:'no-store'});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Unavailable');return d}
function label(text){return showLabels?`<span class="field-label">${esc(text)}</span>`:''}
function metric(key,name,value,detail=''){if(!fields.has(key))return'';return `<div class="metric">${label(name)}<strong>${esc(value)}</strong>${detail?`<small>${esc(detail)}</small>`:''}</div>`}
let brandingData=null,brandingLoadedAt=0;
async function loadOverlayBranding(){if(brandingData&&Date.now()-brandingLoadedAt<30000)return brandingData;try{brandingData=await json('/api/obs/branding');brandingLoadedAt=Date.now()}catch{brandingData={}}return brandingData}
function logo(){if(!showLogo)return'';const custom=brandingData?.logo_available?'/api/obs/logo?t=1':null,air=brandingData?.airline||{};if(brandingMode==='active_airline'&&air.enabled===false)return'';let url=null,code='OR',name='OPS ROOM';if(brandingMode==='custom'&&custom){url=custom;name=brandingData.filename||'CUSTOM'}else if(brandingMode==='ops_room'){url='/assets/brand/opsroom-logo-icon.svg'}else{url=air.logo_url||null;code=air.code||'OR';name=air.name||code}const image=url?`<img src="${esc(url)}" alt="${esc(name)}" onerror="this.hidden=true;this.nextElementSibling.hidden=false">`:'';return `<div class="brand-logo ${logoPosition}">${image}<b class="brand-monogram" ${url?'hidden':''}>${esc(code)}</b></div>`}
function shell(content){return `<div class="obs-shell">${logoPosition==='left'?logo():''}${content}${logoPosition==='right'?logo():''}</div>`}
function identity(origin,dest){if(!fields.has('route'))return'';return `<div class="identity-block"><div class="airport">${showLabels?'<span class="airport-label">Departure</span>':''}<b>${esc(origin)}</b></div><div class="route-arrow">→</div><div class="airport destination">${showLabels?'<span class="airport-label">Arrival</span>':''}<b>${esc(dest)}</b></div></div>`}
function flightValues(plan,watch){const p=plan.plan||plan.cached_plan||{},f=watch.flight||watch.simbrief||p||{},pos=watch.telemetry||watch.position||{};return {p,f,pos,watch,origin:f.origin?.icao||f.origin||p.origin?.icao||'----',dest:f.destination?.icao||f.destination||p.destination?.icao||'----'}}
function metricHtml(data){const {p,f,pos,watch}=data;const items=[
 metric('callsign','Callsign',f.callsign||p.callsign||'--'),metric('aircraft','Aircraft',pos.aircraft_type||pos.aircraft_title||f.aircraft_icao||p.aircraft?.icao_code||'--'),metric('registration','Registration',pos.registration||f.registration||p.aircraft?.reg||'--'),
 metric('altitude','Altitude',fmtAlt(pos.indicated_altitude_ft??pos.altitude_ft)),metric('agl','AGL',fmtAlt(pos.agl_ft??pos.radio_altitude_ft)),metric('ias','IAS',fmtSpd(pos.indicated_speed_kts??pos.ias_kts)),metric('groundspeed','Groundspeed',fmtSpd(pos.ground_speed_kts)),
 metric('verticalspeed','Vertical speed',fmtVs(pos.vertical_speed_fpm)),metric('heading','Heading',fmtDeg(pos.heading_deg)),metric('track','Track',fmtDeg(pos.track_deg)),metric('phase','Phase',phaseText(watch)),
 metric('remaining','Remaining',fmt(f.remaining_nm,1,' NM')),metric('eta','ETA',hm(f.eta_utc),'UTC'),metric('fuel','Fuel',fmt(pos.fuel_total_lb,0,' lb')),metric('wind','Wind',number(pos.wind_speed_kts)==null?'--':`${fmtDeg(pos.wind_direction_deg)} / ${fmtSpd(pos.wind_speed_kts)}`),
 metric('autopilot','Autopilot',pos.autopilot_master===true?'ON':pos.autopilot_master===false?'OFF':'--'),metric('source','Data source',String(pos.source||pos.provider||watch.telemetry_source||'--').toUpperCase()),metric('zulu','UTC',new Date().toISOString().slice(11,19))
];return items.join('')}
async function renderFlight(){const [plan,watch]=await Promise.all([json('/api/simbrief/status').catch(()=>({})),json('/api/flight-watch').catch(()=>({ok:false,state:'standby'}))]);const data=flightValues(plan,watch);root.innerHTML=shell(`<section class="obs-card flight-card">${identity(data.origin,data.dest)}<div class="metrics-grid">${metricHtml(data)}</div></section>`)}
async function renderTelemetry(){const [plan,watch]=await Promise.all([json('/api/simbrief/status').catch(()=>({})),json('/api/flight-watch').catch(()=>({ok:false,state:'standby'}))]);const data=flightValues(plan,watch);root.innerHTML=shell(`<section class="obs-card telemetry-card">${metricHtml(data)}</section>`)}
async function renderProgress(){const [plan,watch]=await Promise.all([json('/api/simbrief/status').catch(()=>({})),json('/api/flight-watch').catch(()=>({ok:false,state:'standby'}))]);const data=flightValues(plan,watch),progress=Math.max(0,Math.min(1,number(data.f.progress)||0));root.innerHTML=shell(`<section class="obs-card progress-card"><div class="progress-head"><div class="progress-route">${esc(data.origin)}<i>→</i>${esc(data.dest)}</div><div class="progress-meta">${metric('remaining','Remaining',fmt(data.f.remaining_nm,1,' NM'))}${metric('eta','ETA',hm(data.f.eta_utc),'UTC')}</div></div><div class="progress-track"><div class="progress-fill" style="width:${progress*100}%"></div></div></section>`)}
async function renderPhase(){const watch=await json('/api/flight-watch').catch(()=>({ok:false,state:'standby'}));root.innerHTML=shell(`<section class="obs-card phase-card">${showLabels?'<span>FLIGHT PHASE</span>':''}${esc(phaseText(watch))}</section>`)}
async function renderMessages(){const [vp,hp]=await Promise.all([json('/api/vpilot/messages?limit=20').catch(()=>({messages:[]})),json('/api/hoppie/status').catch(()=>({messages:[]}))]);const v=(vp.messages||[]).filter(x=>x.direction!=='OUT').at(-1),h=(hp.messages||[]).filter(x=>x.direction==='IN').at(-1),items=[];if(v)items.push({time:v.time,source:'vPilot',from:v.from||'ATC',text:v.message||'',kind:'vpilot'});if(h)items.push({time:h.time,source:'Hoppie',from:h.from||'ATC',text:h.message||h.display||'',kind:'hoppie'});const item=items.sort((a,b)=>new Date(a.time)-new Date(b.time)).at(-1);if(!item){root.innerHTML='<div class="obs-wait">WAITING FOR ATC MESSAGE</div>';return}root.innerHTML=shell(`<section class="obs-card message-card ${item.kind}"><div>${label(item.source)}<strong>${esc(item.from)}</strong></div><p>${esc(item.text)}</p><time>${hm(item.time)}Z</time></section>`)}

function serviceActive(row){const raw=Number(row?.raw||0);const rs=String(row?.remote_state||row?.state||'').toLowerCase();return [4,5,7].includes(raw)||['requested','performing','completing','waiting'].includes(rs)||row?.waiting===true}
function serviceDone(row){const raw=Number(row?.raw||0);const rs=String(row?.remote_state||row?.state||'').toLowerCase();return raw===6||['completed','complete','bypassed'].includes(rs)}
function serviceIdle(row){const raw=Number(row?.raw||0);const rs=String(row?.remote_state||row?.state||'').toLowerCase();return !serviceActive(row)&&!serviceDone(row)&&['idle','available','ready',''].includes(rs)}
function serviceOperator(text){const m=String(text||'').match(/by\s+([^*·|]+?)(?:\s*[*·|]|$)/i);return m?m[1].trim():''}
function progressLine(progress){const parts=[];const bp=progress?.passengers_boarding_total,bt=progress?.passengers_target,dp=progress?.passengers_deboarding_total,dt=progress?.passengers_deboarding_target||progress?.passengers_target;const bc=progress?.boarding_cargo_percent,dc=progress?.deboarding_cargo_percent;if(number(bp)!=null&&number(bt)!=null)parts.push(`Boarding ${bp}/${bt}`);if(number(dp)!=null&&number(dt)!=null)parts.push(`Deboarding ${dp}/${dt}`);if(number(bc)!=null)parts.push(`Cargo ${bc}%`);if(number(dc)!=null)parts.push(`Bags ${dc}%`);return parts.join(' · ')}
function gsxServiceRows(services){return Object.entries(services||{}).filter(([_,row])=>row&&typeof row==='object').map(([key,row])=>({key,row,label:row.label||key.toUpperCase(),state:row.remote_state||row.state||row.label||'',status:row.status_text||row.progress_text||row.waiting_reason||'',raw:Number(row.raw||0)}))}
async function renderGsx(){
  const [gsx,plan,auto,receipts]=await Promise.all([json('/api/gsx/status').catch(e=>({ok:false,connected:false,reason:e.message,services:{},progress:{}})),json('/api/simbrief/status').catch(()=>({})),json('/api/gsx/automation/status').catch(()=>({})),json('/api/gsx/receipts?limit=3').catch(()=>({items:[]}))]);
  const p=plan.plan||plan.cached_plan||{},f=plan.flight||p||{};const origin=f.origin?.icao||f.origin||p.origin?.icao||'----',dest=f.destination?.icao||f.destination||p.destination?.icao||'----';
  const rows=gsxServiceRows(gsx.services);const active=rows.find(x=>serviceActive(x.row));const completed=rows.filter(x=>serviceDone(x.row)).slice(0,4);const next=rows.find(x=>!serviceDone(x.row)&&!serviceActive(x.row)&&(x.row.can_trigger||serviceIdle(x.row)));
  const current=active||next||rows[0];const status=current?.status||gsx.reason||'Waiting for GSX service data';const operator=serviceOperator(status)||serviceOperator(current?.label)||'';const prog=progressLine(gsx.progress);const remote=gsx.source||gsx.official_remote?.protocol||'GSX';
  const latest=(receipts.items||[])[0];
  if(layout==='compact'){
    root.innerHTML=shell(`<section class="obs-card gsx-card gsx-compact"><div class="gsx-title"><b>${esc(origin)} → ${esc(dest)}</b><span>GSX ${gsx.connected?'ONLINE':'OFFLINE'}</span></div><strong>${esc(current?.label||'Ground handling')}</strong><small>${esc(prog||status)}</small></section>`);return;
  }
  if(layout==='debug'){
    root.innerHTML=shell(`<section class="obs-card gsx-card gsx-debug"><div class="gsx-title"><b>GSX REMOTE API</b><span>${esc(gsx.connected?'CONNECTED':'OFFLINE')} · ${esc(remote)}</span></div><div class="gsx-debug-grid">${rows.slice(0,12).map(x=>`<div><b>${esc(x.key)}</b><span>raw ${esc(x.raw)} · ${esc(x.state||'--')}</span><small>${esc(x.status||'')}</small></div>`).join('')||'<div><b>NO SERVICES</b><span>waiting</span></div>'}</div></section>`);return;
  }
  root.innerHTML=shell(`<section class="obs-card gsx-card"><div class="gsx-title"><div><span>${esc(gsx.connected?'GSX GROUND HANDLING':'GSX OFFLINE')}</span><b>${esc(origin)} → ${esc(dest)}</b></div><div class="gsx-badge">${esc(auto.active?'SERVICE FLOW':'REMOTE')}</div></div><div class="gsx-main"><div><span>Current service</span><strong>${esc(current?.label||'Ground handling')}</strong><small>${esc(operator?`${operator} · ${status}`:status)}</small></div><div><span>Progress</span><strong>${esc(prog||'--')}</strong><small>${esc(next?`Next: ${next.label}`:'No next service published')}</small></div></div><div class="gsx-chips">${completed.map(x=>`<i class="done">${esc(x.label)}</i>`).join('')}${active?`<i class="live">${esc(active.label)}</i>`:''}${latest?`<i class="invoice">Invoice ${esc(latest.category||'GSX')}</i>`:''}</div></section>`)
}

async function renderLanding(){const d=await json('/api/logbook?limit=1').catch(()=>({entries:[]})),e=(d.entries||[])[0];if(!e){root.innerHTML='<div class="obs-wait">NO COMPLETED FLIGHT</div>';return}const m=e.metrics||{},f=e.flight||{},de=e.debrief||{},a=e.analysis_summary?.landing||{},hard=Math.abs(number(m.landing_rate_fpm)||0)>500;root.innerHTML=shell(`<section class="obs-card landing-card ${hard?'hard':''}"><div class="landing-title">${label('Latest landing')}<strong>${esc(f.destination||'----')} ${esc(a.runway||f.arrival_runway||'')}</strong><b>${esc(de.landing_grade||'NOT GRADED')}</b></div><div class="metric">${label('Rate')}<strong>${fmt(m.landing_rate_fpm,0,' fpm')}</strong></div><div class="metric">${label('G-force')}<strong>${fmt(m.touchdown_g,2,' G')}</strong></div><div class="metric">${label('Speed')}<strong>${fmtSpd(m.touchdown_speed_kts)}</strong></div><div class="metric">${label('TD point')}<strong>${fmt(a.touchdown_distance_ft,0,' ft')}</strong></div><div class="metric">${label('Rollout')}<strong>${fmt(a.rollout_distance_ft,0,' ft')}</strong></div><div class="metric">${label('Score')}<strong>${esc(de.score??'--')}</strong></div></section>`)}
async function renderStatus(){const d=await json('/api/system/summary').catch(()=>({integrations:{}})),labels={msfs:'MSFS',telemetry:'DATA',vatsim:'VATSIM',simbrief:'SIMBRIEF',vpilot:'VPILOT',hoppie:'HOPPIE',gsx:'GSX'};root.innerHTML=shell(`<section class="obs-card status-card">${Object.entries(d.integrations||{}).map(([k,x])=>`<div class="status-item"><i class="lamp ${lamp(x.state)}"></i><div>${label(labels[k]||k)}<b>${esc(x.label||'')}</b></div></div>`).join('')}</section>`)}
async function render(){try{if(showLogo)await loadOverlayBranding();if(view==='messages')await renderMessages();else if(view==='landing')await renderLanding();else if(view==='status')await renderStatus();else if(view==='gsx')await renderGsx();else if(view==='telemetry')await renderTelemetry();else if(view==='progress')await renderProgress();else if(view==='phase')await renderPhase();else await renderFlight()}catch{root.innerHTML='<div class="obs-wait">OPS ROOM UNAVAILABLE</div>'}}
render();setInterval(render,view==='messages'?1500:2500);
