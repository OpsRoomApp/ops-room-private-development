#!/usr/bin/env node
'use strict';
const fs=require('fs'),vm=require('vm'),path=require('path');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'app/static/opsroom.js'),'utf8');
function extractFunction(name){
  const marker=`function ${name}(`,start=source.indexOf(marker);if(start<0)throw new Error(`missing ${name}`);
  const open=source.indexOf('{',start);let depth=0,quote='',escape=false;
  for(let i=open;i<source.length;i++){const ch=source[i];if(quote){if(escape)escape=false;else if(ch==='\\')escape=true;else if(ch===quote)quote='';continue}if(ch==='"'||ch==="'"||ch==='`'){quote=ch;continue}if(ch==='{')depth++;else if(ch==='}'){depth--;if(depth===0)return source.slice(start,i+1)}}throw new Error(`unterminated ${name}`)
}
class Geometry{constructor(coords){this.coords=coords}getCoordinates(){return this.coords}getType(){return this.constructor.name}getCoordinateAt(frac){const a=this.coords[0],b=this.coords[this.coords.length-1];return [a[0]+(b[0]-a[0])*frac,a[1]+(b[1]-a[1])*frac]}getExtent(){const pts=this.coords.flat(2);let xs=[],ys=[];const walk=x=>{if(Array.isArray(x)&&typeof x[0]==='number'){xs.push(x[0]);ys.push(x[1])}else if(Array.isArray(x))x.forEach(walk)};walk(this.coords);return [Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)]}}
class LineString extends Geometry{}
class Polygon extends Geometry{}
class Point extends Geometry{constructor(coords){super(coords)}getExtent(){return [this.coords[0],this.coords[1],this.coords[0],this.coords[1]]}}
class Feature{constructor(props){this.props={...props}}get(k){return this.props[k]}set(k,v){this.props[k]=v}getGeometry(){return this.props.geometry}}
class VectorSource{constructor(){this.features=[]}clear(){this.features=[]}addFeatures(rows){this.features.push(...rows)}getFeatures(){return this.features}}
class Style{constructor(o){this.options=o}}class Stroke{constructor(o){this.options=o}}class Fill{constructor(o){this.options=o}}class Text{constructor(o){this.options=o}}
const runwaySource=new VectorSource(),taxiSource=new VectorSource(),labelSource=new VectorSource();
let selected='';
const context={console,Math,Number,String,Map,Set,Infinity,
 ol:{geom:{LineString,Polygon,Point},Feature,proj:{fromLonLat:x=>x},extent:{getCenter:e=>[(e[0]+e[2])/2,(e[1]+e[3])/2]},style:{Style,Stroke,Fill,Text}},
 olMap:{getView:()=>({getZoom:()=>16.7})},mapSurfaceRequestSeq:1,mapSurfaceLoadingIcao:'EDDM',mapSurfaceDetailMode:'full',mapSurfaceRenderTimer:null,mapSurfaceLoadedIcao:'',mapSurfaceTargetIcao:'',mapSurfaceAutoIcao:'',mapAirportIndex:new Map(),
 olRunwaySurfaceLayer:{getSource:()=>runwaySource,changed:()=>{}},olTaxiSurfaceLayer:{getSource:()=>taxiSource,changed:()=>{}},olSurfaceLabelLayer:{getSource:()=>labelSource,changed:()=>{}},
 olBaseLayer:{setOpacity:()=>{}},olRasterFallbackLayer:{setOpacity:()=>{}},
 mapLayerChecked:()=>true,updateMapAviationStatus:()=>{},rememberMapAirport:()=>{},cancelSurfaceRenderTimers:()=>{},
 $:()=>({set textContent(v){selected=v},get textContent(){return selected}}),
};
vm.createContext(context);
for(const name of ['surfaceZoomMode','runwaySurfaceStyle','taxiSurfaceStyle','runwayPolygonFromLine','runwayCrossLine','runwayThresholdStripes','runwayEndLabelFeature','taxiLabelBudget','shouldKeepTaxiLabel','lineMidpoint','addAirportSurfaceFeatures','finishSurfaceLoad'])vm.runInContext(extractFunction(name),context);
const payload={ok:true,source:'local',airport:{ident:'EDDM'},runways:[{name:'08L/26R',primary_lon:11.73,primary_lat:48.35,secondary_lon:11.82,secondary_lat:48.36,width_ft:197}],taxiways:[{name:'A4',width_ft:70,type:'TAXI',points:[[11.75,48.35],[11.77,48.355],[11.79,48.36]]},{name:'',width_ft:35,type:'PATH',points:[[11.76,48.35],[11.76,48.36]]}],raw_taxi_segment_count:20,taxi_polyline_count:2};
if(!context.addAirportSurfaceFeatures(payload,1,'EDDM'))throw new Error('surface add returned false');
const rw=runwaySource.getFeatures(),tw=taxiSource.getFeatures();
if(rw.length!==16)throw new Error(`expected pavement, centerline, thresholds and stripes, got ${rw.length}`);
if(tw.length!==2)throw new Error(`expected two taxi polylines, got ${tw.length}`);
const labels=labelSource.getFeatures().map(feature=>String(feature.get('label')||''));
if(!labels.includes('08L')||!labels.includes('26R'))throw new Error(`expected separate runway-end labels, got ${labels.join(', ')}`);
if(!labels.includes('A4'))throw new Error(`expected taxiway label A4, got ${labels.join(', ')}`);
for(const feature of rw){const style=context.runwaySurfaceStyle(feature,1);if(!style)throw new Error('runway style missing')}
for(const feature of tw){const style=context.taxiSurfaceStyle(feature,1);if(!Array.isArray(style)||style.length<2)throw new Error('taxi style missing')}
if(source.includes('setStyle(taxiSurfaceStyle)')||source.includes('setStyle(runwaySurfaceStyle)'))throw new Error('surface feature-level style callback regression');
if(!selected.includes('1 RWY')||!selected.includes('2/2 TAXI LINES'))throw new Error(`renderer counts missing: ${selected}`);
console.log(JSON.stringify({ok:true,runway_features:rw.length,taxiway_features:tw.length,label_features:labelSource.getFeatures().length,status:selected},null,2));
