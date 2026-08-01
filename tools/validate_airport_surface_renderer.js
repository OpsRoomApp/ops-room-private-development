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
class Geometry{constructor(coords){this.coords=coords}getCoordinates(){return this.coords}getType(){return this.constructor.name}getCoordinateAt(frac){const a=this.coords[0],b=this.coords[this.coords.length-1];return [a[0]+(b[0]-a[0])*frac,a[1]+(b[1]-a[1])*frac]}getExtent(){let xs=[],ys=[];const walk=x=>{if(Array.isArray(x)&&typeof x[0]==='number'){xs.push(x[0]);ys.push(x[1])}else if(Array.isArray(x))x.forEach(walk)};walk(this.coords);return [Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)]}}
class LineString extends Geometry{} class Polygon extends Geometry{} class Point extends Geometry{getExtent(){return [this.coords[0],this.coords[1],this.coords[0],this.coords[1]]}}
class Feature{constructor(props){this.props={...props}}get(k){return this.props[k]}set(k,v){this.props[k]=v}getGeometry(){return this.props.geometry}}
class VectorSource{constructor(){this.features=[]}clear(){this.features=[]}addFeatures(rows){this.features.push(...rows)}getFeatures(){return this.features}}
class Style{constructor(o){this.options=o}} class Stroke{constructor(o){this.options=o}} class Fill{constructor(o){this.options=o}} class Text{constructor(o){this.options=o}}
const runwaySource=new VectorSource(),taxiSource=new VectorSource(),labelSource=new VectorSource();let selected='';let zoom=16.7;
const context={console,Math,Number,String,Map,Set,Infinity,
 ol:{geom:{LineString,Polygon,Point},Feature,proj:{fromLonLat:x=>x},extent:{getCenter:e=>[(e[0]+e[2])/2,(e[1]+e[3])/2]},style:{Style,Stroke,Fill,Text}},
 olMap:{getView:()=>({getZoom:()=>zoom})},mapSurfaceRequestSeq:1,mapSurfaceLoadingIcao:'EDDK',mapSurfaceDetailMode:'full',mapSurfaceRenderTimer:null,mapSurfaceLoadedIcao:'',mapSurfaceTargetIcao:'',mapSurfaceAutoIcao:'',mapAirportIndex:new Map(),
 olRunwaySurfaceLayer:{getSource:()=>runwaySource,changed:()=>{}},olTaxiSurfaceLayer:{getSource:()=>taxiSource,changed:()=>{}},olSurfaceLabelLayer:{getSource:()=>labelSource,changed:()=>{}},
 olBaseLayer:{setOpacity:()=>{}},olRasterFallbackLayer:{setOpacity:()=>{}},mapLayerChecked:()=>true,updateMapAviationStatus:()=>{},rememberMapAirport:()=>{},cancelSurfaceRenderTimers:()=>{},
 $:()=>({set textContent(v){selected=v},get textContent(){return selected}}),
};
vm.createContext(context);
for(const name of ['surfaceZoomMode','runwaySurfaceStyle','taxiSurfaceStyle','runwayPolygonFromLine','runwayCrossLine','runwayThresholdStripes','runwayEndLabelFeature','surfaceLabelStyle','taxiLabelBudget','shouldKeepTaxiLabel','lineMidpoint','addAirportSurfaceFeatures','finishSurfaceLoad'])vm.runInContext(extractFunction(name),context);
if(context.surfaceZoomMode(null)!=='full'||context.surfaceZoomMode(undefined)!=='full')throw new Error('null/undefined zoom hides surface');
const payload={ok:true,source:'local',airport:{ident:'EDDK'},runways:[{name:'14R/32L',primary_name:'14R',secondary_name:'32L',primary_lon:6.95,primary_lat:50.86,secondary_lon:7.00,secondary_lat:50.90,width_ft:197}],taxiways:[{name:'A',width_ft:75,type:'TAXI',points:[[6.96,50.87],[6.97,50.88],[6.98,50.89]]},{name:'',width_ft:35,type:'PATH',points:[[6.965,50.875],[6.97,50.875]]}],raw_taxi_segment_count:382,taxi_polyline_count:2};
if(!context.addAirportSurfaceFeatures(payload,1,'EDDK'))throw new Error('surface load failed');
const rw=runwaySource.getFeatures(),tw=taxiSource.getFeatures(),labels=labelSource.getFeatures();
if(!rw.some(f=>f.get('kind')==='runway-surface'))throw new Error('runway polygon missing');
if(!rw.some(f=>f.get('kind')==='runway-centerline'))throw new Error('runway centreline missing');
if(rw.filter(f=>f.get('kind')==='runway-threshold').length<10)throw new Error('runway threshold markings missing');
if(tw.length!==2)throw new Error(`taxi paths incomplete: ${tw.length}`);
const endLabels=labels.filter(f=>f.get('kind')==='runway-end-label').map(f=>f.get('label')).sort();
if(JSON.stringify(endLabels)!==JSON.stringify(['14R','32L']))throw new Error(`separate runway end labels missing: ${endLabels}`);
for(const feature of rw){if(!context.runwaySurfaceStyle(feature,1))throw new Error(`runway style missing for ${feature.get('kind')}`)}
for(const feature of tw){const styles=context.taxiSurfaceStyle(feature,1);if(!Array.isArray(styles)||styles.length<2)throw new Error('taxi style missing');const widths=styles.map(x=>x.options?.stroke?.options?.width).filter(Number.isFinite);if(Math.max(...widths)>9)throw new Error(`taxiway still too thick: ${Math.max(...widths)}`)}
for(const feature of labels){if(!context.surfaceLabelStyle(feature))throw new Error(`label style missing for ${feature.get('kind')}`)}
zoom=13.7;if(context.surfaceLabelStyle(labels.find(f=>f.get('kind')==='taxi-label'))!==null)throw new Error('taxi label not zoom gated');
zoom=16.7;if(!context.surfaceLabelStyle(labels.find(f=>f.get('kind')==='taxi-label')))throw new Error('taxi label did not return after zoom');
if(!selected.includes('1 RWY')||!selected.includes('2/2 TAXI LINES'))throw new Error(`surface counts incorrect: ${selected}`);
if(source.includes('setStyle(taxiSurfaceStyle)')||source.includes('setStyle(runwaySurfaceStyle)'))throw new Error('feature-level style regression');
console.log(JSON.stringify({ok:true,runway_features:rw.length,taxiway_features:tw.length,labels:endLabels,status:selected},null,2));
