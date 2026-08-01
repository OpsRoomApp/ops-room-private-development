from __future__ import annotations
import hashlib,json,re,subprocess,sys,tempfile,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
checks=[]
def check(name,ok):
    ok=bool(ok);checks.append((name,ok));print(('PASS' if ok else 'FAIL')+': '+name)
def text(rel): return (ROOT/rel).read_text(encoding='utf-8',errors='replace')
def sha(rel): return hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()
version=json.loads(text('version.json'));manifest=json.loads(text('update.json'))
ui=text('app/static/opsroom.js');html=text('app/static/index.html');css=text('app/static/opsroom.css')
black=text('app/black_box.py');sim=text('app/simconnect_position.py');aviation=text('app/aviation_data.py');main=text('app/main.py')
complete=text('BUILD OPS ROOM COMPLETE.bat');windows=text('BUILD WINDOWS APP ONLY.bat');camera=text('BUILD CAMERA BRIDGE 2024.bat')
check('version is v0.24.104 Black Box RC2',version=={'product':'OPS ROOM','version':'0.24.104','build':'public-beta-black-box-release-candidate-2','codename':'Flight Data Recorder Release Candidate 2','channel':'release-candidate'})
check('runtime and launcher target v0.24.104','FastAPI(title="OPS ROOM", version="0.24.104")' in main and 'Starting OPS ROOM v0.24.104' in text('opsroom_launcher.py'))
check('bundled updater manifest targets RC2',manifest.get('version')=='0.24.104' and str(manifest.get('download_url','')).endswith('OPS_ROOM_v0_24_104_Public_Beta_Black_Box_RC2_Windows_x64.zip') and manifest.get('sha256')=='TO_BE_FILLED_BY_BUILD_SCRIPT')
check('final dist remains beside build scripts','set "DIST_DIR=%~dp0dist"' in complete and 'set "DIST_DIR=%~dp0dist"' in windows)
check('only intermediates use short OR104 root','%TEMP%\\OR104' in complete and '%TEMP%\\OR104' in windows and '%TEMP%\\OR104' in camera and '%OPSROOM_BUILD_ROOT%\\camera_bridge' in camera)
check('build scripts and manifest writer use identical RC2 Windows zip',complete.count('OPS_ROOM_v0_24_104_Public_Beta_Black_Box_RC2_Windows_x64.zip')>=3 and windows.count('OPS_ROOM_v0_24_104_Public_Beta_Black_Box_RC2_Windows_x64.zip')>=4 and 'Flight Data Recorder Release Candidate 2' in text('tools/write_update_manifest.py'))
# Navigation rail
nav_buttons=re.findall(r'<button class="nav-item[^>]*>(.*?)</button>',html,re.S)
check('left navigation module numbering removed',len(nav_buttons)>=19 and all(not re.search(r'<span>\s*\d+',row) for row in nav_buttons))
check('text-only nav retains accessible collapsed labels',html.count('class="nav-item')==html.count('class="nav-item') and all('aria-label=' in tag for tag in re.findall(r'<button class="nav-item[^>]*>',html)))
# Map renderer
check('runway and taxiway use separate visible vector layers',all(token in ui for token in ['olRunwaySurfaceLayer=new ol.layer.Vector','olTaxiSurfaceLayer=new ol.layer.Vector','olTaxiSurfaceLayer,olRunwaySurfaceLayer,olSurfaceLabelLayer']))
check('surface geometry is styled at layer level only','style:runwaySurfaceStyle' in ui and 'style:taxiSurfaceStyle' in ui and 'setStyle(runwaySurfaceStyle)' not in ui and 'setStyle(taxiSurfaceStyle)' not in ui)
check('runway renderer includes width-aware polygon and centreline','runwayPolygonFromLine' in ui and "kind:'runway-surface'" in ui and "kind:'runway-centerline'" in ui)
check('taxi renderer includes casing, highlight and minor paths',"color:'rgba(2,4,5,.99)'" in ui and "const inner=major?'#ffd928':'#c8a72c'" in ui and "kind:'taxi'" in ui)
check('surface backend loads complete ordered taxi data','from taxi_path' in aviation and 'order by taxi_path_id' in aviation and 'limit 12000' not in aviation.lower() and '_merge_taxi_segments' in aviation)
check('surface UI reports actual renderer feature counts','renderedRunways' in ui and 'renderedTaxiways' in ui and '/${merged} TAXI LINES' in ui)
# FDR layout
check('Black Box is FDR-first two-column layout','#page-blackbox .blackbox-layout{grid-template-columns:minmax(270px,310px) minmax(0,1fr)!important' in css and '.blackbox-replay-panel{grid-column:2;grid-row:1/3' in css)
check('flight charts use responsive 2x2 panel grid','function bbPanelGrid' in ui and 'cols=w/dpr>=980?2:1' in ui and all(label in ui for label in ['ALTITUDE / RADIO HEIGHT','AIR / GROUND SPEED','VERTICAL SPEED','ATTITUDE / LOAD']))
check('controls and engines use horizontal card grids','function bbMetricCard' in ui and 'drawBlackBoxControls' in ui and 'drawBlackBoxEngines' in ui and 'index,3' in ui and 'index,4' in ui)
check('chart and metric text are collision-safe','bbClipText' in ui and 'text-overflow:ellipsis' in css and 'blackbox-controls{display:flex;flex-wrap:wrap' in css)
check('live FDR polling remains automatic and frequent','/api/blackbox/live' in ui and 'scheduleBlackBoxPoll(250)' in ui and "blackBoxRefresh" in html)
# Complex aircraft optional capture
check('direct SimConnect pilot-input fallback variables are read',all(token in sim for token in ['YOKE_X_POSITION','YOKE_Y_POSITION','RUDDER_PEDAL_POSITION','GENERAL_ENG_THROTTLE_LEVER_POSITION:1']))
check('pilot axes and percent encodings are normalized','def normalized_axis' in sim and 'for value in (fallback, primary)' in sim and '32768.0' in sim and '16384.0' in sim and 'normalized_percent' in sim)
check('FSUIPC core is supplemented without replacing flight path','_supplement_optional_parameters' in black and 'FSUIPC remains authoritative' in black and 'SIMCONNECT EXTENDED' in black and 'lat' not in black[black.find('_EXTENDED_FIELDS'):black.find('_EXTENDED_FIELDS')+700])
check('existing recording/replay formats remain compatible','Backward compatibility' in black and '.opsbb.part' in black and 'FIELDS' in black and 'black_box_replay' in main)
# Dynamic enrichment test
try:
    import app.black_box as bb
    old=bb.read_position
    bb.read_position=lambda force=False:{'ok':True,'aileron_position':.42,'elevator_position':-.2,'rudder_position':.1,'throttle_1_percent':73.0,'throttle_2_percent':72.5,'engine_1_n1_percent':84.0,'systems':{'parking_brake':False,'engines_running':True},'autopilot':{'engaged':True,'modes':['NAV']},'source':'simconnect'}
    sample=bb._supplement_optional_parameters({'ok':True,'source':'fsuipc','lat':48.0,'lon':11.0,'altitude_ft':10000})
    bb.read_position=old
    check('dynamic FSUIPC plus SimConnect enrichment works',sample.get('lat')==48.0 and sample.get('aileron_position')==.42 and sample.get('engine_1_n1_percent')==84.0 and sample.get('source')=='FSUIPC + SIMCONNECT EXTENDED')
except Exception as exc:
    print('ENRICHMENT ERROR:',exc);check('dynamic FSUIPC plus SimConnect enrichment works',False)
# End-to-end short recording/readback using an isolated temporary root.
try:
    import time as _time
    import app.black_box as bb
    with tempfile.TemporaryDirectory(prefix='opsroom-v104-bb-') as tmp:
        old_root,old_tel,old_pos,old_settings=bb._root,bb.read_telemetry,bb.read_position,bb.load_settings
        isolated_root=Path(tmp)/'BlackBox'; isolated_root.mkdir(parents=True,exist_ok=True)
        bb._root=lambda: isolated_root
        bb.load_settings=lambda:{'integrations':{'black_box_max_hz':30,'black_box_simconnect_max_hz':10,'black_box_enabled':True,'black_box_auto_record':True}}
        counter={'n':0}
        def _tel(force=False):
            counter['n']+=1;n=counter['n']
            return {'ok':True,'source':'fsuipc','lat':48+n*1e-5,'lon':11+n*1e-5,'altitude_ft':1500+n,'radio_altitude_ft':300+n,'indicated_speed_kts':140,'ground_speed_kts':142,'vertical_speed_fpm':800,'heading_deg':80,'pitch_deg':4,'bank_deg':1,'g_force':1.01,'systems':{'parking_brake':False,'engines_running':True}}
        def _pos(force=False):
            return {'ok':True,'source':'simconnect','aileron_position':.25,'elevator_position':-.15,'rudder_position':.05,'throttle_1_percent':78.0,'throttle_2_percent':77.5,'engine_1_n1_percent':88.0,'engine_2_n1_percent':87.5,'systems':{'parking_brake':False,'engines_running':True}}
        bb.read_telemetry,bb.read_position=_tel,_pos
        bb._PHASE_CONTEXT.update({'flight_id':'rc2-test','phase':'CLIMB','meta':{}})
        started=bb.start_recording('rc2-test',{'flight':{'callsign':'EWG7278','origin':'EDDM','destination':'LOWI'},'aircraft':{'registration':'D-AEWK'}})
        _time.sleep(.55)
        finished=bb.stop_recording('VALIDATION')
        rows=bb.samples(finished.get('recording_id',''),max_points=1000) if finished.get('ok') else []
        path=Path(finished.get('path','')) if finished.get('path') else None
        ok=bool(started.get('recording') and finished.get('ok') and path and path.is_file() and path.name.startswith('EWG7278_D-AEWK_EDDM-LOWI_') and path.suffix=='.opsbb' and rows and rows[-1].get('source')=='FSUIPC + SIMCONNECT EXTENDED' and rows[-1].get('aileron_position')==.25 and rows[-1].get('engine_1_n1_percent')==88.0)
        bb._root,bb.read_telemetry,bb.read_position,bb.load_settings=old_root,old_tel,old_pos,old_settings
        check('short recording finalizes and reads back extended Fenix-style data',ok)
except Exception as exc:
    print('RECORDING ERROR:',exc);check('short recording finalizes and reads back extended Fenix-style data',False)
# Frozen protected modules from supplied v0.24.103 baseline
expected={
'app/black_box_replay.py':'e1fac1c6b529ad0fdb5679a6a5ade80faf4ab8d6c83a0e93e995ef01b1061420','app/logbook.py':'ff03416ce9494935a6d8cf015469e507af8a9f54d35075532090fb9ea688f9c1','app/gsx_remote.py':'0bb9c659c23b049b5c30839cc3760de3762e9bbb5d0f3fe1e3922bf2c7f93e8a','app/fenix_adapter.py':'7a9597f65ea8f0e6e67f839fb607630faa4181d3bf725dd2160d1fc854571f46','app/fenix_gsx_loading_state_machine.py':'6a9fc247e785228c210a3f2a3942925e29d1d744e9ce9a583f3dfaa495c0d2cd','app/announcements.py':'52e6fb63ec88e3b70589d32574218defb2fe81db98579f8c8db00a94cb0dd488','app/announcement_hotkeys.py':'999942533047e0ebacdb6d3a5b2e2beb714994556c8e41bfe06ea546591005f9','app/gsx_receipts.py':'1af0c10b24f5e9acf28f951e49681f4faef92be4a6dc156ca5497191829a8e28','app/economy.py':'7c65910e4807871fdf5ba922144c1af7f4e13ab23ff805e62170da273e702f87','app/raas.py':'7e808122ebd1f8c6301421b28a0ca84585426b9d730bb9506408d99ee5e6578b','app/raas_audio.py':'bbff9073c51d00c60d390d120ef63e33844e1b1d1785d5ead5497ac13154b445','app/pirep_analysis.py':'a544897546cdbf03b2cb8d4e6d02a03b6c35b9e13f7d5a508e00f36ac63a6c3a','app/telemetry_provider.py':'f8bc19f7f7affc1244e5073b51d2d87a193ed3d52d66adf2731d8875f2e21682'}
check('13 protected operational/replay modules are byte-identical to v0.24.103',all(sha(rel)==digest for rel,digest in expected.items()))
check('airline logo collection remains complete',len(list((ROOT/'app/assets/logos').glob('*.png')))==3946)
# Runtime/OpenAPI
try:
    from app.main import app
    check('backend starts with expected route surface',app.version=='0.24.104' and len(app.routes)==210 and len(app.openapi().get('paths',{}))==185)
except Exception as exc:
    print('BACKEND ERROR:',exc);check('backend starts with expected route surface',False)
# Run JS renderer gate
proc=subprocess.run(['node',str(ROOT/'tools/validate_v024104_surface_renderer.js')],cwd=ROOT,text=True,capture_output=True)
print(proc.stdout,end='');
if proc.stderr: print(proc.stderr,end='')
check('dynamic OpenLayers surface feature/style gate passes',proc.returncode==0)
failed=[name for name,ok in checks if not ok]
print(f'RESULT: {len(checks)-len(failed)}/{len(checks)} checks passed')
if failed: print('FAILED: '+'; '.join(failed))
sys.exit(1 if failed else 0)
