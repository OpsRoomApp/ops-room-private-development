#!/usr/bin/env node
const fs=require('fs');
const vm=require('vm');
const path=require('path');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'app/static/opsroom.js'),'utf8');
function extractFunction(name){
  const marker=`function ${name}(`;const start=source.indexOf(marker);if(start<0)throw new Error(`missing ${name}`);
  const open=source.indexOf('{',start);let depth=0,quote='',escape=false;
  for(let i=open;i<source.length;i++){
    const ch=source[i];
    if(quote){if(escape)escape=false;else if(ch==='\\')escape=true;else if(ch===quote)quote='';continue}
    if(ch==='"'||ch==="'"||ch==='`'){quote=ch;continue}
    if(ch==='{')depth++;else if(ch==='}'){depth--;if(depth===0)return source.slice(start,i+1)}
  }
  throw new Error(`unterminated ${name}`);
}
const checks=[];function check(v,label){if(!v)throw new Error(label);checks.push(label)}
const context={console,Math,Number,String,Map,Set,Infinity,
  mapData:null,mapSelectedAirportIcao:'',mapSelectedAirportTitle:'',mapSurfaceTargetIcao:'',mapSurfaceLoadedIcao:'',mapSurfaceLoadingIcao:'',mapSurfaceAutoIcao:'',mapAirportIndex:new Map(),mapAviationRefreshPending:false,mapAviationBusy:false,
  activePage:'map',mapSurfaceDetailMode:'full',mapSurfaceRequestSeq:0,mapSurfaceRenderTimer:null,mapAviationRefreshTimer:null,
  ol:{proj:{toLonLat:x=>x,fromLonLat:x=>x,transformExtent:x=>x}},
  olMap:{getView:()=>({getCenter:()=>[4.7639,52.3091],getZoom:()=>16,calculateExtent:()=>[4.758,52.305,4.766,52.312]}),getSize:()=>[1200,700]},
  mapLayerChecked:()=>true,clearAirportSurface:()=>{},maybeCullSurfaceForZoom:()=>false,updateMapAviationStatus:()=>{},loadAirportSurface:async()=>{},scheduleAviationRefresh:()=>{},
};
vm.createContext(context);
for(const fn of ['surfaceZoomMode','mapDistanceNm','airportLookupBboxParam','rememberMapAirport','routeSurfaceAirports','airportNearMapCenter','chooseSurfaceAirport'])vm.runInContext(extractFunction(fn),context);
check(context.surfaceZoomMode(12.8)==='none'&&context.surfaceZoomMode(13)==='runway'&&context.surfaceZoomMode(14.5)==='taxi'&&context.surfaceZoomMode(16)==='full','zoom modes preserved');
const padded=context.airportLookupBboxParam(16).split(',').map(Number);
check((padded[2]-padded[0])>.5&&(padded[3]-padded[1])>.35,'airport lookup is padded beyond close viewport');
const eham={ident:'EHAM',name:'Schiphol',lat:52.3086,lon:4.7639,longest_runway_ft:12467};
const ehhv={ident:'EHHV',name:'Hilversum',lat:52.1919,lon:5.1469,longest_runway_ft:2200};
check(context.chooseSurfaceAirport([ehhv,eham]).ident==='EHAM','nearest airport chosen without exact ARP containment');
context.mapSelectedAirportIcao='EHHV';context.mapSelectedAirportTitle='EHHV · Hilversum';
check(context.chooseSurfaceAirport([eham,ehhv]).ident==='EHHV','explicit airport selection has priority');
context.mapSelectedAirportIcao='';context.mapSurfaceLoadedIcao='EHHV';context.mapAirportIndex.set('EHHV',ehhv);
check(context.chooseSurfaceAirport([eham,ehhv]).ident==='EHAM','distant loaded airport does not remain incorrectly sticky');
context.mapSurfaceLoadedIcao='EHAM';context.mapAirportIndex.set('EHAM',eham);
check(context.chooseSurfaceAirport([ehhv,eham]).ident==='EHAM','loaded airport remains sticky within its airport area');
context.mapSurfaceLoadedIcao='';context.mapData={ownship:{nearest_airport:'EHAM',lat:52.31,lon:4.77},airports:[]};
check(context.chooseSurfaceAirport([]).ident==='EHAM','ownship nearest airport can drive direct surface loading');
check(source.includes("if(mapAviationBusy){mapAviationRefreshPending=true;return}"),'busy refreshes are queued');
check(!source.includes("if(preset!=='airport')clearAirportSurface"),'presets do not erase surfaces');
check(source.includes("clean:{mapLayerTraffic:true,mapLayerControllers:true,mapLayerCoverage:false,mapLayerAirports:true,mapLayerRunways:true,mapLayerSurface:true"),'clean preset keeps zoom-driven surfaces');
check(source.includes("route:{mapLayerTraffic:true,mapLayerControllers:true,mapLayerCoverage:false,mapLayerAirports:true,mapLayerRunways:true,mapLayerSurface:true"),'route preset keeps zoom-driven surfaces');
check(source.includes("mapSelectedAirportIcao=ident;mapSurfaceTargetIcao=ident"),'airport clicks persist selection');
check(!/pointermove[^\n]+mapSelected/.test(source),'hover no longer overwrites selected airport');
console.log(JSON.stringify({ok:true,passed:checks.length,checks},null,2));
