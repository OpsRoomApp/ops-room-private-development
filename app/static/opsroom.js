const pages = ['home', 'status', 'fids', 'dispatch', 'briefing', 'scratchpad', 'watch', 'performance', 'raas', 'network', 'map', 'datalink', 'ground', 'announcer', 'procedures', 'logbook', 'blackbox', 'finances', 'obs', 'system'];
const MODULE_VISIBILITY_LABELS = {
  status:'Status', fids:'VATSIM FIDS', dispatch:'Dispatch', briefing:'Briefing', scratchpad:'Scratchpad', watch:'Flight Watch', performance:'Performance', raas:'Runway Awareness', network:'Network', map:'Live Map', datalink:'Datalink', ground:'Ground Control', announcer:'Announcer', procedures:'Procedures', logbook:'Logbook', blackbox:'Black Box', finances:'Finances', obs:'OBS Tools', system:'Settings'
};
const placeholders = {};

let settings = null;
let summary = null;
let flightPlan = null;
let ofpAutoFetchStarted = false;
let ofpFetchInProgress = false;
let dispatchContextData = null;
let dispatchSource = 'auto';
let dispatchLoaded = false;
let activeDispatchRoute = null;
let watchBusy = false;
let watchSocket = null;
let watchReconnectTimer = null;
let watchPollTimer = null;
let watchFallbackTimer = null;
let networkLoaded = false;
let nextSuggestedFrequency = null;
let vpilotSocket = null;
let vpilotReconnectTimer = null;
let vpilotPollTimer = null;
let lastVpilotEventId = 0;
let knownPrivateMessageIds = new Set();
let vpilotInitialized = false;
let commsSendMode = 'private';
let briefingWeatherTimer = null;
let briefingOfpTheme = 'dark';
// v0.25.65: live OFP completion panel state (chip-toggle polling lifecycle).
let briefingOfpLiveTimer = null;
let briefingOfpLiveBusy = false;
let briefingOfpLiveRevision = '';
let briefingOfpLiveData = null;
let briefingOfpLiveOpen = false;
let briefingOfpLiveAbortController = null;
let activePage = 'status';
let groundTimer = null;
let groundBusy = false;
let briefingOwnshipTimer = null;
let groundSocket = null;
let groundReconnectTimer = null;
let mapSocket = null;
let mapReconnectTimer = null;
let mapPollTimer = null;
let mapMode = localStorage.getItem('opsroom-map-mode') || 'world';
let mapData = null;
let olMap = null;
let olBaseLayer = null;
let olRasterFallbackLayer = null;
let olRouteLayer = null;
let olAirportLayer = null;
let olRouteAirportLayer = null;
let olCoverageLayer = null;
let olControllerLayer = null;
let olTrafficLayer = null;
let olOwnshipLayer = null;
let olOwnshipFeature = null;
let ownshipAnimFrame = null;
let ownshipAnimTarget = null;
let ownshipLastLonLat = null;
let olNavaidLayer = null;
let olAirwayLayer = null;
let olWaypointLayer = null;
let olBoundaryLayer = null;
let olNotamLayer = null;
let olSurfaceLayer = null;
let olRunwaySurfaceLayer = null;
let olTaxiSurfaceLayer = null;
let olSurfaceLabelLayer = null;
let mapAviationBusy = false;
let mapAviationRefreshPending = false;
let mapSelectedAirportIcao = '';
let mapSelectedAirportTitle = '';
let mapSurfaceTargetIcao = '';
const mapAirportIndex = new Map();
let mapSurfaceLoadedIcao = '';
let mapSurfaceLoadingIcao = '';
let mapSurfaceAutoIcao = '';
let mapSurfaceRequestSeq = 0;
let mapAviationRefreshTimer = null;
let mapSurfaceRenderTimer = null;
let mapSurfaceDetailMode = 'none';
const mapSurfaceCache = new Map();
const mapTrafficFeatures = new Map();
const mapControllerFeatures = new Map();
let mapAutoFramePending = true;
let mapHasStoredView = false;
let proceduresData = null;
let procedurePhase = '';
let procedureTimer = null;
let logbookTimer = null;
let blackBoxTimer = null;
let blackBoxData = null;
let selectedBlackBoxId = '';
let blackBoxSamples = [];
let blackBoxEvents = [];
let blackBoxDetail = null;
let blackBoxView = 'flight';
let blackBoxLiveLastElapsed = -1;
let blackBoxLoadBusy = false;
let blackBoxAdapterData = null;
let blackBoxAdapterLoadedAt = 0;
let blackBoxAdapterBusy = false;
let blackBoxSeekTimer = null;
let blackBoxPlayback = {playing:false,cursor:0,speed:1,loop:false,lastMono:0,lastDraw:0,raf:0};
let logbookData = null;
let selectedLogbookId = '';
let hoppieSocket = null;
let hoppieReconnectTimer = null;
let hoppiePollTimer = null;
let notificationItems = [];
let notificationUnread = 0;
let lastServerNotificationId = '';
let notificationTimer = null;
let notificationTitleTimer = null;
let notificationToastTimer = null;
let notificationToastPage = 'status';
let notificationToastAction = '';
let pendingUpdateManifest = null;
let lastUpdatePromptVersion = '';
let lastProcedureFlightPhase = '';
let procedureAdvanceTimer = null;
let lastNextStationKey = '';
let knownHoppieMessageIds = new Set();
let hoppieInitialized = false;
let knownGsxEventKeys = new Set();
let gsxInitialized = false;
let selectedTelemetryCache = new Map();
let terminalServerInfo = null;
let terminalIpVisible = false;
let networkCidVisible = false;
let obsBranding = {logo_available:false};
let obsBrandingPreferencePresent = false;
let airlineBrandingState = null;
let qrhData = null;
let qrhSelectedCondition = '';
let qrhQuery = '';
let lastFrontendError = '';
let scratchpadPage = 'departure';
let scratchpadData = {fields:{},strokes:[],mode:'template'};
let scratchpadTool = 'type';
let scratchpadDrawing = false;
let scratchpadCurrentStroke = null;
let scratchpadSaveTimer = null;
let scratchpadPeriodicSaveTimer = null;
let scratchpadDirty = false;
let scratchpadSaving = false;
let scratchpadCanvasReady = false;
let cameraBridgeTimer = null;
let raasTimer = null;
let announcerTimer = null;
let announcerLoadBusy = false;
let announcerLastRevision = -1;
let lastRaasToastId = null;
let lastRaasClientAudioToastId = null;
let raasGlobalTimer = null;
let raasGlobalPollTimer = null;
let landingMonitorTimer = null;
let landingBurstTimer = null;
let lastLandingToastId = null;
let landingMonitorPrimed = false;
let landingMonitorStartedAt = 0;
let raasListenerSeeded = false;
let cameraViewState = {mode:'tail_follow',distance:55,height:10,sideOffset:0,pitch:-7,orbitAngle:180,smoothing:0.35};
let cameraViewSaveTimer = null;
const KEEP_AWAKE_KEY = 'opsroom-efb-keep-awake-v1';
let keepAwakeWanted = localStorage.getItem(KEEP_AWAKE_KEY) === '1';
let keepAwakeState = {state:'off', label:'Keep Awake off', detail:''};
let briefingChartOwnshipTimer=null;
/** PDF.js renderer state for the chart preview canvas */
let cfPdfState = { pageNum: 1, pageRendering: false, pageNumPending: null,
  scale: 1.0, rotation: 0, darkMode: false,
  canvas: null, ctx: null, container: null,
  nativeWidth: 595, nativeHeight: 842,  // v0.25.60: PDF page native dims for annotation anchoring
  isPanning: false, panStart: {x:0,y:0}, panOffset: {x:0,y:0}, panMoved: false };
// v0.25.16 ChartFox charts browser implementation (list + preview with ownship overlay and pin, ~1500 lines). Legacy openChartFoxChart/briefingChart* block remains for export-to-PIREP step. Do not regress.
let cfState = { airport: null, items: [], groups: [], activeChartId: null,
  promoteTab: null,                // v0.25.16: tabs are sort-promotion, not filter toggle
  pins: [], previewTimer: null,
  _fetchingAirports: {},           // v0.25.60: in-flight dedup map cleared on every loadCharts()
  };
// v0.25.60 — Chart Viewer Annotation/Scratchpad overlay state (pen matches Scratchpad)
let cfAnnotation = { canvas: null, ctx: null, active: false,
  tool: 'pen', color: '#ff3333', width: 3.5, opacity: 0.85,
  strokes: [], undoStack: [], currentStroke: null,
  lastChartId: null };
const CF_ANNOTATION_COLORS = { amber: '#efbd47', cyan: '#4fc3f7', red: '#e07060', white: '#f0ecd9', yellow: '#ffe082' };
const TERMINAL_HOME_STYLE_KEY = 'opsroom-terminal-home-style-v1815';
const TERMINAL_HOME_STYLES = new Set(['auto','classic','efb']);
const RAIL_COLLAPSED_KEY = 'opsroom-classic-rail-collapsed-v1815';

const $ = id => document.getElementById(id);

// v0.25.73 (#8 sweep): in-app confirm modal. WebView2 silently blocks native
// window.confirm(), so every confirm-gated action goes through a real <dialog>.
// Returns a Promise<boolean>; resolve is wired before showModal() so the
// rejection path (ESC / backdrop click) also resolves false.
let _uiConfirmDialog = null;
function uiConfirm(message, okLabel){
  if(!_uiConfirmDialog){
    _uiConfirmDialog = document.createElement('dialog');
    _uiConfirmDialog.className = 'ui-confirm-dialog';
    _uiConfirmDialog.innerHTML =
      '<div class="ui-confirm-box">' +
        '<p class="ui-confirm-message"></p>' +
        '<div class="ui-confirm-actions">' +
          '<button type="button" class="control-button" data-ui-confirm-cancel>CANCEL</button>' +
          '<button type="button" class="control-button danger-control" data-ui-confirm-ok>CONFIRM</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(_uiConfirmDialog);
    _uiConfirmDialog.querySelector('[data-ui-confirm-ok]').addEventListener('click', ()=>{ _uiConfirmDialog._resolve(true); _uiConfirmDialog.close(); });
    _uiConfirmDialog.querySelector('[data-ui-confirm-cancel]').addEventListener('click', ()=>{ _uiConfirmDialog._resolve(false); _uiConfirmDialog.close(); });
    _uiConfirmDialog.addEventListener('cancel', e=>{ e.preventDefault(); _uiConfirmDialog._resolve(false); _uiConfirmDialog.close(); });
    _uiConfirmDialog.addEventListener('click', e=>{ if(e.target === _uiConfirmDialog){ _uiConfirmDialog._resolve(false); _uiConfirmDialog.close(); } });
  }
  _uiConfirmDialog.querySelector('.ui-confirm-message').textContent = String(message || 'Continue?');
  const ok = _uiConfirmDialog.querySelector('[data-ui-confirm-ok]');
  if(ok) ok.textContent = String(okLabel || 'CONFIRM');
  return new Promise(resolve=>{ _uiConfirmDialog._resolve = resolve; _uiConfirmDialog.showModal(); });
}

// v0.25.60: minimal showToast replacement — uses browser Notification API
// when available with permission, falls back to console logging.
// Previously rendered a bottom-left badge that was removed per user request.
// The 34 existing call sites now route through this no-DOM logger.
function showToast(title, subtitle, detail, level){
  const msg = subtitle ? title + ' — ' + subtitle + (detail ? ': ' + detail : '') : title + (detail ? ': ' + detail : '');
  const prefix = '[OPS ROOM][' + (level || 'info').toUpperCase() + ']';
  if(level === 'critical' || level === 'error'){
    console.error(prefix, msg);
  }else if(level === 'warn'){
    console.warn(prefix, msg);
  }else{
    console.info(prefix, msg);
  }
  // v0.25.60: attempt browser Notification API for user-visible toast.
  // Fails gracefully on permission denied, not-supported, or http origins.
  try{
    if(typeof Notification !== 'undefined' && Notification.permission === 'granted'){
      new Notification(title, {body: subtitle + (detail ? ' — ' + detail : ''), tag: 'opsroom-toast'});
    }
  }catch(_){}
}
const PAGE_LABELS = {
  home:'OPS ROOM HOME', status:'STATUS BOARD', fids:'VATSIM FIDS', dispatch:'DISPATCH', briefing:'BRIEFING', scratchpad:'SCRATCHPAD / KNEEBOARD', watch:'FLIGHT WATCH', performance:'PERFORMANCE', raas:'RUNWAY AWARENESS', network:'NETWORK / COMMS', map:'LIVE MAP', datalink:'DATALINK', ground:'GROUND CONTROL', announcer:'ANNOUNCER', procedures:'PROCEDURES', logbook:'LOGBOOK', obs:'OBS TOOLS', system:'SYSTEM'
};

const CPDLC_TEMPLATES = [
  {id:'pdc',cat:'PDC / DCL',phase:'ground',label:'PDC request, standard TELEX',sendType:'telex',to:'station',fields:['station','stand','atis'],build:c=>`REQUEST PREDEP CLEARANCE\n${c.callsign} ${c.aircraft} TO ${c.destination} AT ${c.origin} STAND ${c.stand} ATIS ${c.atis}`},
  {id:'pdc_short',cat:'PDC / DCL',phase:'ground',label:'PDC request, compact',sendType:'telex',to:'station',fields:['station','stand','atis'],build:c=>`${c.callsign} REQUEST PDC ${c.aircraft} TO ${c.destination} AT ${c.stand} ATIS ${c.atis}`},
  {id:'start',cat:'Request / Departure',phase:'ground',label:'Startup request',to:'station',fields:['station','stand','atis'],build:c=>`REQUEST STARTUP\nCALLSIGN ${c.callsign}\nACFT ${c.aircraft}\nSTAND ${c.stand}\nATIS ${c.atis}`},
  {id:'push',cat:'Request / Departure',phase:'ground',label:'Pushback request',to:'station',fields:['station','stand','direction','atis'],build:c=>`REQUEST PUSHBACK\nCALLSIGN ${c.callsign}\nSTAND ${c.stand}${c.direction?`\nPUSH ${c.direction}`:''}${c.atis?`\nATIS ${c.atis}`:''}`},
  {id:'taxi',cat:'Request / Departure',phase:'ground',label:'Taxi request',to:'station',fields:['station','stand','runway','atis'],build:c=>`REQUEST TAXI\nCALLSIGN ${c.callsign}\nSTAND ${c.stand}\nRWY ${c.runway}\nATIS ${c.atis}`},
  {id:'dep_clearance',cat:'Request / Departure',phase:'ground',label:'IFR clearance request',to:'station',fields:['station','stand','atis','runway','sid'],build:c=>`REQUEST IFR CLEARANCE\nCALLSIGN ${c.callsign}\nACFT ${c.aircraft}\n${c.origin} TO ${c.destination}\nSTAND ${c.stand}\nATIS ${c.atis}${c.runway?`\nRWY ${c.runway}`:''}${c.sid?`\nSID ${c.sid}`:''}`},
  {id:'ready_dep',cat:'Request / Departure',phase:'ground',label:'Ready for departure',to:'station',fields:['station','runway','intersection'],build:c=>`${c.callsign} READY DEPARTURE\nRWY ${c.runway}${c.intersection?`\nINTERSECTION ${c.intersection}`:''}`},
  {id:'climb',cat:'Vertical',phase:'climb',label:'Request climb',to:'atc',fields:['atc','level','reason'],build:c=>`REQUEST CLIMB TO ${c.level}${c.reason?` DUE ${c.reason}`:''}`},
  {id:'descent',cat:'Vertical',phase:'descent',label:'Request descent',to:'atc',fields:['atc','level','reason'],build:c=>`REQUEST DESCENT TO ${c.level}${c.reason?` DUE ${c.reason}`:''}`},
  {id:'cruise_level',cat:'Vertical',phase:'cruise',label:'Request cruise level',to:'atc',fields:['atc','level','reason'],build:c=>`REQUEST FLIGHT LEVEL ${c.level}${c.reason?` DUE ${c.reason}`:''}`},
  {id:'block_level',cat:'Vertical',phase:'cruise',label:'Request block level',to:'atc',fields:['atc','level_from','level_to','reason'],build:c=>`REQUEST BLOCK ${c.level_from} TO ${c.level_to}${c.reason?` DUE ${c.reason}`:''}`},
  {id:'when_higher',cat:'Vertical',phase:'cruise',label:'When can we expect higher',to:'atc',fields:['atc','level'],build:c=>`WHEN CAN WE EXPECT ${c.level}`},
  {id:'direct',cat:'Route',phase:'cruise',label:'Request direct',to:'atc',fields:['atc','waypoint','reason'],build:c=>`REQUEST DIRECT ${c.waypoint}${c.reason?` DUE ${c.reason}`:''}`},
  {id:'route_change',cat:'Route',phase:'cruise',label:'Request route change',to:'atc',fields:['atc','route','reason'],build:c=>`REQUEST ROUTE CHANGE\n${c.route}${c.reason?`\nDUE ${c.reason}`:''}`},
  {id:'offset',cat:'Route',phase:'cruise',label:'Request lateral offset',to:'atc',fields:['atc','offset','side','reason'],build:c=>`REQUEST OFFSET ${c.offset} NM ${c.side}${c.reason?` DUE ${c.reason}`:''}`},
  {id:'weather_dev',cat:'Route',phase:'cruise',label:'Request weather deviation',to:'atc',fields:['atc','side','distance','reason'],build:c=>`REQUEST WEATHER DEVIATION ${c.side} OF ROUTE UP TO ${c.distance} NM${c.reason?` DUE ${c.reason}`:''}`},
  {id:'speed',cat:'Speed',phase:'cruise',label:'Request speed',to:'atc',fields:['atc','speed','reason'],build:c=>`REQUEST SPEED ${c.speed}${c.reason?` DUE ${c.reason}`:''}`},
  {id:'mach',cat:'Speed',phase:'cruise',label:'Request Mach',to:'atc',fields:['atc','mach','reason'],build:c=>`REQUEST MACH ${c.mach}${c.reason?` DUE ${c.reason}`:''}`},
  {id:'approach',cat:'Arrival / Approach',phase:'arrival',label:'Request approach',to:'atc',fields:['atc','approach','runway','atis'],build:c=>`REQUEST ${c.approach} APPROACH RWY ${c.runway}${c.atis?`\nATIS ${c.atis}`:''}`},
  {id:'runway_change',cat:'Arrival / Approach',phase:'arrival',label:'Request runway change',to:'atc',fields:['atc','runway','reason'],build:c=>`REQUEST RWY ${c.runway}${c.reason?` DUE ${c.reason}`:''}`},
  {id:'arrival_clearance',cat:'Arrival / Approach',phase:'descent',label:'Request arrival clearance',to:'atc',fields:['atc','star','runway','atis'],build:c=>`REQUEST ARRIVAL CLEARANCE\nSTAR ${c.star}\nRWY ${c.runway}${c.atis?`\nATIS ${c.atis}`:''}`},
  {id:'hold',cat:'Arrival / Approach',phase:'arrival',label:'Request hold',to:'atc',fields:['atc','waypoint','reason'],build:c=>`REQUEST HOLD AT ${c.waypoint}${c.reason?` DUE ${c.reason}`:''}`},
  {id:'oceanic',cat:'Reports',phase:'cruise',label:'Position report',to:'atc',fields:['atc','position','time','level','next','eta'],build:c=>`POSITION REPORT\n${c.callsign}\nPOS ${c.position} AT ${c.time}\nLEVEL ${c.level}\nNEXT ${c.next} AT ${c.eta}`},
  {id:'estimate',cat:'Reports',phase:'cruise',label:'Estimate report',to:'atc',fields:['atc','waypoint','eta','level'],build:c=>`ESTIMATE ${c.waypoint} AT ${c.eta} LEVEL ${c.level}`},
  {id:'wilco',cat:'Replies',phase:'auto',label:'WILCO',to:'atc',fields:['atc'],build:c=>'WILCO'},
  {id:'unable',cat:'Replies',phase:'auto',label:'UNABLE',to:'atc',fields:['atc','reason'],build:c=>`UNABLE${c.reason?` DUE ${c.reason}`:''}`},
  {id:'standby',cat:'Replies',phase:'auto',label:'STANDBY',to:'atc',fields:['atc'],build:c=>'STANDBY'},
  {id:'roger',cat:'Replies',phase:'auto',label:'ROGER',to:'atc',fields:['atc'],build:c=>'ROGER'},
  {id:'free',cat:'Free Text',phase:'auto',label:'Free text CPDLC',to:'atc',fields:['atc','message'],build:c=>c.message}
];
const CPDLC_FIELD_LABELS={station:'STATION / ATS UNIT',atc:'ATC / DATA AUTHORITY',stand:'STAND / GATE',atis:'ATIS INFO',runway:'RUNWAY',sid:'SID',star:'STAR',remarks:'REMARKS',direction:'PUSH DIRECTION',intersection:'INTERSECTION',level:'LEVEL',level_from:'FROM LEVEL',level_to:'TO LEVEL',reason:'REASON',waypoint:'WAYPOINT',route:'ROUTE',offset:'OFFSET',side:'SIDE',distance:'DISTANCE',speed:'SPEED',mach:'MACH',approach:'APPROACH TYPE',position:'POSITION',time:'TIME',next:'NEXT FIX',eta:'ETA',message:'MESSAGE'};


function escapeHtml(value){
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function escapeAttr(value){
  // Strict allowlist: only http(s) URLs are accepted. Falls back to '#' for everything else.
  // This blocks javascript:/data:/vbscript:/file:/view-source:/intent:/jar:/chrome:/ms-appx:/x-javascript:
  // and obfuscated variants (encoded chars, zero-width prefixes) by construction.
  let s = String(value ?? '').replace(/[\u200B-\u200F\uFEFF]/g, '').trim();
  if(!s) return '#';
  if(!/^https?:\/\//i.test(s)) return '#';
  return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function friendlyError(value){
  const text=String(value||'').replace(/\b(?:OSError|RuntimeError|ConnectionError|TimeoutError|FileNotFoundError|ImportError|Exception):?\s*/gi,'').replace(/\[WinError[^\]]*\]/gi,'').replace(/\b-?2147\d+\b/g,'').replace(/HTTP\s+\d+/gi,'').replace(/\s{2,}/g,' ').trim();
  return text&&text.length<140?text:'The operation is currently unavailable.';
}


const UI_PHASE_LABELS={
  PREBLOCK:'Preflight',PARKED:'Parked',PUSHBACK:'Pushback',TAXI_OUT:'Taxi out',
  TAKEOFF_ROLL:'Takeoff roll',TAKEOFF:'Takeoff',INITIAL_CLIMB:'Initial climb',CLIMB:'Climb',
  ENROUTE:'Cruise',CRUISE:'Cruise',DESCENT:'Descent',APPROACH:'Approach',
  GO_AROUND:'Go-around',MISSED_APPROACH:'Missed approach',LANDING_ROLL:'Landing roll',
  TAXI_IN:'Taxi in',POST_ARRIVAL_PENDING:'Arrival services pending',COMPLETE:'Complete'
};
const UI_ANNOUNCEMENT_LABELS={
  BoardingMusic:'Boarding music',BoardingWelcome:'Welcome aboard',SafetyBriefing:'Safety briefing',
  CabinDimTakeoff:'Cabin lights for takeoff',CrewSeatsTakeoff:'Cabin crew for takeoff',
  AfterTakeoff:'After takeoff',FastenSeatbelt:'Fasten seat belts',DescentSeatbelts:'Seat belts for descent',
  CrewSeatsLanding:'Cabin crew for landing',Landing:'After landing',AfterLanding:'After landing',
  ArmDoors:'Doors armed',DisarmDoors:'Doors disarmed',DisembarkStarted:'Disembarkation'
};
const UI_KIND_LABELS={
  AUTO:'Automatic',COMPLETE:'Completed',COMPLETED:'Completed',PLAYING:'Playing',STARTING:'Starting',
  QUEUED:'Queued',SUPPRESSED:'Waiting',FAULT:'Attention',WARNING:'Attention',DEVIATION:'Flight note',
  TELEMETRY_RESTORED:'Simulator data restored',TELEMETRY_GAP_STARTED:'Simulator data interrupted',
  TELEMETRY_GAP_ENDED:'Simulator data restored',POST_ARRIVAL_PENDING:'Arrival services pending',
  BLOCK_OUT:'Off blocks',BLOCK_IN:'On blocks',PREBLOCK:'Recording started',PARKED:'Parked',
  PUSHBACK:'Pushback',TAXI_OUT:'Taxi out',TAKEOFF_ROLL:'Takeoff roll',TAKEOFF:'Takeoff',
  INITIAL_CLIMB:'Initial climb',CLIMB:'Climb',ENROUTE:'Cruise',CRUISE:'Cruise',DESCENT:'Descent',
  APPROACH:'Approach',GO_AROUND:'Go-around',MISSED_APPROACH:'Missed approach',LANDING_ROLL:'Landing roll',
  TAXI_IN:'Taxi in',SERVICING:'Services',DEBOARDING:'Deboarding',BOARDING:'Boarding',
  FENIX:'Fenix',PHASE_ACCEPTED:'Flight phase updated',PHASE_REJECTED:'Phase check ignored',
  ANN_PLAY_IMMEDIATE:'Played',ANNOUNCEMENT:'Announcement'
};

function uiToken(value){
  return String(value||'').trim().toUpperCase().replace(/[\s-]+/g,'_');
}
function uiWords(value){
  const raw=String(value||'').trim();
  if(!raw)return '';
  const token=uiToken(raw);
  if(UI_PHASE_LABELS[token])return UI_PHASE_LABELS[token];
  if(UI_KIND_LABELS[token])return UI_KIND_LABELS[token];
  if(UI_ANNOUNCEMENT_LABELS[raw])return UI_ANNOUNCEMENT_LABELS[raw];
  return raw.replace(/^ANN_/i,'').replaceAll('_',' ').replace(/([a-z])([A-Z])/g,'$1 $2').toLowerCase().replace(/\b\w/g,c=>c.toUpperCase());
}
function friendlyAirlineSource(value){
  const source=uiToken(value);
  if(source.includes('OVERRIDE'))return 'Manual selection';
  if(source.includes('SIMBRIEF'))return 'Flight plan';
  if(source.includes('CALLSIGN'))return 'Callsign';
  return 'Automatic';
}
function friendlyAnnouncementName(value){
  const raw=String(value||'').trim();
  return UI_ANNOUNCEMENT_LABELS[raw]||uiWords(raw)||'Cabin audio';
}
function friendlyStage(value){
  const token=uiToken(value);
  const direct={
    READY:'Ready',SERVICING:'Services in progress',WAITING_REFUEL_CATERING:'Waiting for refuelling and catering',
    READY_FOR_BOARDING:'Ready for boarding',REQUESTING_BOARDING:'Starting boarding',BOARDING_REQUESTED:'Boarding requested',
    MONITORING_BOARDING:'Boarding in progress',BOARDING_COMPLETE:'Boarding complete',AIRCRAFT_LOADED:'Aircraft loaded',
    PUSHBACK_ARMED:'Pushback timer armed',PUSHBACK_REQUESTED:'Pushback requested',PUSHBACK:'Pushback',
    DEBOARDING:'Deboarding in progress',DEBOARDING_COMPLETE:'Deboarding complete',CLEANING:'Cabin cleaning',
    LAVATORY:'Lavatory service',WATER:'Potable water',ARRIVAL_COMPLETE:'Arrival services complete',
    POST_ARRIVAL_PENDING:'Arrival services pending',ACTION_REQUIRED:'Action required'
  };
  return direct[token]||uiWords(value);
}
function friendlyDetail(value,scope='general'){
  let text=String(value||'').replace(/\s+/g,' ').trim();
  if(!text)return '';
  text=text.replace(/^FENIX:\s*/i,'');
  text=text.replace(/^[A-Z0-9_]+:\s*/,'');
  if(/coordinating gsx services in locked ops room sequence/i.test(text))return 'Ground services are in progress.';
  if(/announcement status is a cached snapshot/i.test(text))return '';
  if(/audio playback is handled only by the background worker/i.test(text))return '';
  if(/auto announcements waiting for stable loaded on-ground flight session/i.test(text))return 'Waiting for stable simulator data.';
  if(/manual recording initialized/i.test(text))return 'Flight recording started.';
  if(/^delay=60s$/i.test(text))return 'Pushback countdown started.';
  if(/^delay=60s remaining=(\d+)s$/i.test(text)){const m=text.match(/remaining=(\d+)s/i);return `Pushback available in ${m?.[1]||'a few'} seconds.`;}
  if(/Fenix EFB targets settled; loading handoff complete/i.test(text))return 'Aircraft loading checks complete.';
  if(/^BoardingMusic due in 30s$/i.test(text))return 'Boarding music starts in 30 seconds.';
  if(/^pax=(\d+)\/(\d+)\s+cargo=(\d+)\/(\d+)\s+fuel=(\d+)\/(\d+)$/i.test(text)){
    const m=text.match(/^pax=(\d+)\/(\d+)\s+cargo=(\d+)\/(\d+)\s+fuel=(\d+)\/(\d+)$/i);
    return m?`Loading status: ${m[1]} of ${m[2]} passengers · cargo ${m[3]}/${m[4]} kg · fuel ${m[5]}/${m[6]} kg.`:text;
  }
  if(/flight phase changed to\s+([A-Z_ ]+)/i.test(text)){
    const m=text.match(/flight phase changed to\s+([A-Z_ ]+)/i);return `${uiWords(m?.[1]||'Flight phase')}.`;
  }
  if(/from=\S+\s+to=([A-Z_ ]+)/i.test(text)){
    const m=text.match(/to=([A-Z_ ]+?)(?:\s+reason=|$)/i);return m?`${uiWords(m[1])}.`:text;
  }
  text=text.replace(/passengers\s+(\d+)\s*\/\s*(\d+)/i,'$1 of $2 passengers');
  text=text.replace(/pax\s+(\d+)\s*\/\s*(\d+)/i,'$1 of $2 passengers');
  text=text.replace(/bags\s*(\d+)\s*%/i,'bags $1%');
  text=text.replace(/\breason=[^·]+/ig,'').replace(/\s*·\s*·/g,' · ').trim();
  return text;
}
function friendlyTimelineEvent(item,scope='general'){
  const rawKind=String(item?.kind||item?.stage||'').trim();
  if(['PHASE_ACCEPTED','PHASE_REJECTED'].includes(uiToken(rawKind)))return null;
  const text=friendlyDetail(item?.text??item?.detail??'',scope);
  if(!text && scope!=='announcer')return null;
  let kind=scope==='ground-auto'?friendlyStage(rawKind):uiWords(rawKind);
  if(scope==='announcer'){
    const rawText=String(item?.text||'');
    if(/mixer channel|\.ogg(?:\s|$)|background worker|cached snapshot/i.test(rawText))return null;
    const eventMatch=rawText.match(/^([A-Za-z][A-Za-z0-9_]*)\b/);
    if(eventMatch && UI_ANNOUNCEMENT_LABELS[eventMatch[1]])kind=friendlyAnnouncementName(eventMatch[1]);
    if(uiToken(rawKind)==='SUPPRESSED')kind='Waiting';
    if(/playback complete/i.test(rawText))return {...item,kind:kind||'Announcement',text:'Completed'};
    if(/played immediately from automation/i.test(rawText))return {...item,kind:kind||'Announcement',text:'Played automatically'};
    if(uiToken(rawKind)==='QUEUED')return {...item,kind:kind||'Announcement',text:'Queued'};
    if(uiToken(rawKind)==='PLAYING')return {...item,kind:kind||'Announcement',text:'Playing'};
  }
  return {...item,kind:kind||'Update',text:text||friendlyAnnouncementName(rawKind)};
}
function operationalEvents(items,scope='general',limit=30){
  const output=[];
  for(const item of (items||[])){
    const event=friendlyTimelineEvent(item,scope);
    if(!event)continue;
    const prev=output[output.length-1];
    if(prev&&prev.kind===event.kind&&prev.text===event.text)continue;
    output.push(event);
    if(output.length>=limit)break;
  }
  return output;
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 8000){
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), Math.max(1000, Number(timeoutMs) || 8000));
  try{
    return await fetch(url, {...options, signal: controller.signal});
  }catch(error){
    if(error && error.name === 'AbortError') throw new Error('The latest status took too long to respond');
    throw error;
  }finally{
    clearTimeout(timer);
  }
}

async function safeJsonResponse(response){
  const text = await response.text();
  let data = {};
  if(text){
    try{ data = JSON.parse(text); }
    catch{ data = {detail: text.slice(0,220)}; }
  }
  if(!response.ok){
    throw new Error(data.detail || data.reason || `HTTP ${response.status}`);
  }
  return data;
}


function reportFrontendError(source, detail){
  try{
    const payload = {source:String(source||'frontend'), detail:String(detail||'').slice(0,800), page:activePage, href:location.href,    version:'0.25.73', ts:new Date().toISOString()};
    lastFrontendError = payload.detail;
    navigator.sendBeacon?.('/api/frontend/log', new Blob([JSON.stringify(payload)], {type:'application/json'})) || fetch('/api/frontend/log',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),keepalive:true}).catch(()=>{});
  }catch(_){ }
}
window.addEventListener('error', event=>reportFrontendError('window.onerror', `${event.message||'script error'} ${event.filename||''}:${event.lineno||''}`));
window.addEventListener('unhandledrejection', event=>reportFrontendError('unhandledrejection', event.reason?.message || event.reason || 'unhandled promise rejection'));

function runModuleStart(name, fn){
  try{ fn(); }
  catch(error){ reportFrontendError(`module:${name}`, error?.stack || error?.message || error); showToast('OPS ROOM', `${String(name||'MODULE').toUpperCase()} INIT FAILED`, friendlyError(error?.message || error), 'critical'); }
}

function stopRaas(){
  if(raasTimer){ clearInterval(raasTimer); raasTimer=null; }
}
let closureProximityKey = '';
let closureProximityExitSince = 0;
// v0.25.65: amber/red proximity pop-up when the aircraft is near a closed
// runway/taxiway per active NOTAMs. Rides the global 5s RAAS poll (no extra
// timer), reuses showRaasGlobalAlert (amber for taxiway/barrier, red for
// runway), and leaves a silent drawer record via notifyOps. The backend gates
// on the notam_notifications setting and never spawns.
// v0.25.72 (#17): the alert is announced once per closure NOTAM. The key is
// the stable closure identity (backend ``closure_id`` = NOTAM id, else
// airport:kind:ref) so switching between markers of the same closure never
// re-alerts, and the latch re-arms only after a sustained 30s exit instead of
// resetting on every near:false — drifting across the radius boundary stops
// re-triggering.
function pollClosureProximity(){
  fetch('/api/notams/closure-proximity',{cache:'no-store'}).then(r=>r.json()).then(data=>{
    if(!data?.ok){ return; }
    if(!data.near){
      if(!closureProximityExitSince) closureProximityExitSince = Date.now();
      else if(Date.now()-closureProximityExitSince >= 30000) closureProximityKey='';
      return;
    }
    closureProximityExitSince = 0;
    const key = String(data.closure_id||String(data.kind||'')+':'+String(data.ref||'')+':'+String(data.airport_icao||''));
    if(!key || key===closureProximityKey) return;
    closureProximityKey = key;
    // Barriers are hold-short lines carrying a runway ref -> treat as runway.
    const rwy = data.kind==='runway' || data.kind==='barrier';
    const text = rwy
      ? `RWY ${String(data.ref||'').toUpperCase()} CLOSED ${String(data.distance_nm||'')} NM AHEAD`
      : `TWY ${String(data.ref||'').toUpperCase()} CLOSED ${String(data.distance_nm||'')} NM AHEAD`;
    showRaasGlobalAlert(text, rwy ? 'critical' : 'amber');
    notifyOps({source:'NOTAM CLOSURE', title:rwy?'RUNWAY CLOSED AHEAD':'TAXIWAY CLOSED AHEAD', message:text, priority:rwy?'critical':'operational', page:'briefing', tag:'closure-proximity:'+key});
  }).catch(()=>{});
}
function startGlobalRaasListener(){
  if(raasGlobalPollTimer) return;
  loadRaas();
  pollClosureProximity();
  raasGlobalPollTimer = setInterval(()=>{loadRaas(); pollClosureProximity();}, 5000);
}
function startAnnouncements(){
  stopAnnouncements();
  const tick=async()=>{if(activePage!=='announcer')return;await loadAnnouncements();if(activePage==='announcer')announcerTimer=setTimeout(tick,650)};
  tick();
}
function stopAnnouncements(){
  if(announcerTimer){ clearTimeout(announcerTimer); announcerTimer=null; }
  announcerLoadBusy=false;
}

function updateClock(){
  const now = new Date();
  $('utcClock').textContent = `${now.toISOString().slice(11,19)} UTC`;
  $('dateLine').textContent = now.toLocaleDateString('en-GB',{day:'2-digit',month:'short',year:'numeric',timeZone:'UTC'}).toUpperCase();
  if($('efbLocalClock')) $('efbLocalClock').textContent = now.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
  if($('efbLocalDate')) $('efbLocalDate').textContent = now.toLocaleDateString([], {weekday:'short', day:'2-digit', month:'short'}).toUpperCase();
}

function isTabletLayout(){
  const touchCapable = matchMedia('(pointer: coarse)').matches;
  const hoverless = matchMedia('(hover: none)').matches;
  const ua = navigator.userAgent || '';
  const tabletUa = /iPad|Tablet|Android(?!.*Mobile)|Silk/i.test(ua);
  const iPadDesktopMode = /Macintosh/i.test(ua) && navigator.maxTouchPoints > 1;
  const compactTouch = touchCapable && hoverless && window.innerWidth <= 1180;
  return Boolean(tabletUa || iPadDesktopMode || compactTouch);
}

function terminalHomeStyle(){
  const value = localStorage.getItem(TERMINAL_HOME_STYLE_KEY) || 'auto';
  return TERMINAL_HOME_STYLES.has(value) ? value : 'auto';
}

function resolvedTerminalHomeStyle(){
  const value = terminalHomeStyle();
  if(value === 'efb' || value === 'classic') return value;
  return isTabletLayout() ? 'efb' : 'classic';
}

function useEfbHome(){
  return resolvedTerminalHomeStyle() === 'efb';
}

function airlineBrandingEnabled(){
  return settings?.interface?.airline_branding_enabled !== false;
}
function cleanAirlineCode(value){
  const code=String(value||'').toUpperCase().replace(/[^A-Z0-9]/g,'');
  return code.length>=2&&code.length<=4?code:'';
}
function resolvedAirlineBranding(subject=null){
  if(!airlineBrandingEnabled())return null;
  const source=subject||flightPlan||{};
  const flight=source?.flight&&typeof source.flight==='object'?source.flight:{};
  const airlineObject=source?.airline&&typeof source.airline==='object'?source.airline:(flight?.airline&&typeof flight.airline==='object'?flight.airline:null);
  const supplied=source?.airline_branding||flight?.airline_branding||airlineObject||((source?.code||source?.logo_url||source?.fallback)?source:null);
  const callsign=String(source?.callsign||flight?.callsign||'').toUpperCase();
  const prefix=(callsign.match(/^([A-Z]{2,4})/)||[])[1]||'';
  const override=cleanAirlineCode(settings?.interface?.airline_icao_override);
  const airlineValue=typeof source?.airline==='string'?source.airline:(typeof flight?.airline==='string'?flight.airline:'');
  const code=cleanAirlineCode(supplied?.code||airlineValue||prefix||override);
  const logo=supplied?.logo_data_uri||supplied?.logo_url||(code?`/assets/logos/${encodeURIComponent(code)}.png`:null);
  return {enabled:true,code,name:supplied?.name||code||'OPS ROOM',source:supplied?.source||'client',logo_url:logo,logo_available:!!logo,fallback:supplied?.fallback||(code?'monogram':'generic')};
}
function airlineBrandHtml(subject=null,size='medium',showName=false){
  const brand=resolvedAirlineBranding(subject);
  if(!brand)return '';
  const code=brand.code||'OR';
  const image=brand.logo_url?`<img src="${escapeHtml(brand.logo_url)}" alt="${escapeHtml(code)}" loading="lazy" decoding="async" onerror="this.hidden=true;this.nextElementSibling.hidden=false" />`:'';
  return `<span class="airline-brand airline-brand-${escapeHtml(size)}">${image}<b class="airline-monogram" ${brand.logo_url?'hidden':''}>${escapeHtml(code)}</b>${showName?`<span class="airline-brand-name"><strong>${escapeHtml(brand.name||code)}</strong><small>${escapeHtml(code)}</small></span>`:''}</span>`;
}

function renderAirlineIdentity(id,subject=null,size='medium',showName=true,detail=''){
  const target=$(id);if(!target)return;
  const html=airlineBrandHtml(subject,size,showName);
  target.innerHTML=html?`${html}${detail?`<span class="airline-identity-detail">${escapeHtml(detail)}</span>`:''}`:'';
  target.hidden=!html;
}
async function loadAirlineBranding(){
  try{airlineBrandingState=await safeJsonResponse(await fetch('/api/airline-branding',{cache:'no-store'}));return airlineBrandingState}catch{return null}
}

function streamerModeEnabled(){
  return Boolean(settings?.interface?.streamer_mode);
}

function sensitiveValueHtml(value, visible, label='sensitive value'){
  const text = value ? String(value) : '---';
  if(!streamerModeEnabled()) return `<b>${escapeHtml(text)}</b>`;
  const display = visible ? escapeHtml(text) : '******';
  return `<span class="sensitive-inline"><b class="streamer-sensitive ${visible?'revealed':'concealed'}" aria-label="${escapeHtml(label)}">${display}</b><button class="sensitive-toggle" type="button" data-sensitive="vatsim-cid">${visible?'HIDE':'SHOW'}</button></span>`;
}

async function toggleSensitiveField(kind){
  if(kind !== 'vatsim-cid') return;
  if(networkCidVisible){
    networkCidVisible = false;
    if(networkLoaded) loadNetwork(false);
    return;
  }
  if(streamerModeEnabled() && !(await uiConfirm('Streamer Mode is enabled. This may reveal your VATSIM CID on stream or in screenshots. Reveal anyway?', 'REVEAL'))) return;
  networkCidVisible = true;
  if(networkLoaded) loadNetwork(false);
}

function urlRequestedHomeStyle(){
  try{
    const params = new URLSearchParams(location.search || '');
    const requested = (params.get('home') || params.get('style') || '').toLowerCase();
    return TERMINAL_HOME_STYLES.has(requested) ? requested : '';
  }catch{return ''}
}

function setTerminalHomeStyle(value){
  const style = TERMINAL_HOME_STYLES.has(value) ? value : 'auto';
  localStorage.setItem(TERMINAL_HOME_STYLE_KEY, style);
  if($('terminalHomeStyle')) $('terminalHomeStyle').value = style;
  const resolved = resolvedTerminalHomeStyle();
  document.documentElement.dataset.homeStyle = resolved;
  if(activePage === 'home') showPage('home');
  else setEfbModuleShell(resolved === 'efb', activePage);
}

function isMobileRail(){
  return matchMedia('(max-width: 860px)').matches;
}

function setRailCollapsed(collapsed){
  document.body.classList.toggle('rail-collapsed', Boolean(collapsed));
  try{ localStorage.setItem(RAIL_COLLAPSED_KEY, collapsed ? '1' : '0'); }catch{}
  const btn = $('moduleButton');
  if(btn){
    btn.textContent = collapsed ? 'MENU' : 'MODULES';
    btn.setAttribute('aria-pressed', collapsed ? 'true' : 'false');
    btn.setAttribute('title', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
  }
}

function toggleClassicRail(){
  if(isMobileRail()){
    $('rail')?.classList.add('open');
    $('railScrim')?.classList.add('open');
    return;
  }
  setRailCollapsed(!document.body.classList.contains('rail-collapsed'));
}

function renderEfbHomeStatus(){
  const label = flightPlan?.ok ? (flightPlan.callsign || 'OPS ROOM') : (summary?.nearest_airport ? `OPS ROOM ${summary.nearest_airport}` : 'OPS ROOM');
  if($('efbProfileLabel')) $('efbProfileLabel').textContent = label;
  if($('efbProfileInitial')) $('efbProfileInitial').textContent = String(label || 'O').replace(/[^A-Z0-9]/gi,'').slice(0,1).toUpperCase() || 'O';
}

function openEfbHome(){
  document.body.classList.remove('efb-module-open');
  if($('efbModuleBar')) $('efbModuleBar').hidden = true;
  document.body.classList.add('efb-home-open');
  if($('efbHome')) $('efbHome').hidden = false;
  if(streamerModeEnabled()) networkCidVisible = false;
  renderEfbHomeStatus();
}

function closeEfbHome(){
  document.body.classList.remove('efb-home-open');
  if($('efbHome')) $('efbHome').hidden = true;
}

async function toggleFullscreen(){
  const root = document.documentElement;
  try{
    if(document.fullscreenElement){
      await document.exitFullscreen();
    }else if(root.requestFullscreen){
      await root.requestFullscreen({navigationUI:'hide'});
    }else if(root.webkitRequestFullscreen){
      root.webkitRequestFullscreen();
    }else{
      const button = $('efbFullscreen');
      if(button){button.textContent = 'ADD TO HOME SCREEN'; setTimeout(()=>button.textContent='FULLSCREEN',2400)}
      return;
    }
  }catch{
    const button = $('efbFullscreen');
    if(button){button.textContent = 'BROWSER BLOCKED'; setTimeout(()=>button.textContent='FULLSCREEN',1600)}
  }
}


function setEfbModuleShell(open, name='status'){
  document.body.classList.toggle('efb-module-open', Boolean(open));
  const bar = $('efbModuleBar');
  if(bar) bar.hidden = !open;
  const title = $('efbModuleTitle');
  if(title) title.textContent = PAGE_LABELS[name] || 'OPS ROOM';
}

function moduleVisibility(){
  return settings?.interface?.module_visibility || {};
}
function financeCareerEnabled(){
  return settings?.interface?.finance_career_enabled !== false;
}
function isModuleVisible(name){
  if(name === 'home') return true;
  if(name === 'finances' && !financeCareerEnabled()) return false;
  const visible = moduleVisibility();
  return visible[name] !== false;
}
function applyModuleVisibility(){
  const visible = moduleVisibility();
  document.querySelectorAll('[data-page]').forEach(el=>{
    const page = el.dataset.page;
    if(!page || page === 'home') return;
    const hide = visible[page] === false;
    if(el.classList.contains('nav-item') || el.classList.contains('module-tile') || el.classList.contains('efb-app')) el.hidden = hide;
  });
}
function renderModuleVisibilityGrid(){
  const grid = $('moduleVisibilityGrid');
  if(!grid) return;
  const visible = moduleVisibility();
  grid.innerHTML = Object.entries(MODULE_VISIBILITY_LABELS).filter(([key])=>key!=='finances'||financeCareerEnabled()).map(([key,label])=>`<label><input type="checkbox" data-module-visible="${escapeHtml(key)}" ${visible[key]===false?'':'checked'} /> ${escapeHtml(label)}</label>`).join('');
  grid.querySelectorAll('[data-module-visible]').forEach(input=>input.addEventListener('change',saveModuleVisibility));
}
async function saveModuleVisibility(){
  const current = {...moduleVisibility()};
  document.querySelectorAll('[data-module-visible]').forEach(input=>{current[input.dataset.moduleVisible]=input.checked;});
  try{
    const payload={interface:{module_visibility:current}};
    const res=await fetch('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const data=await safeJsonResponse(res);
    settings=data.settings || settings;
    applyModuleVisibility();
    renderModuleVisibilityGrid();
  }catch(error){showToast('SETTINGS','MODULE VISIBILITY SAVE FAILED',friendlyError(error.message),'critical')}
}

function showPage(name){
  if(name !== 'home' && !isModuleVisible(name)) name = 'home';
  activePage = name;
  document.body.classList.toggle('blackbox-page-open', name === 'blackbox');
  const efbHomeRequested = name === 'home' && useEfbHome();
  const efbModuleMode = useEfbHome() && name !== 'home';
  document.querySelectorAll('.page').forEach(page => page.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(button => button.classList.toggle('active', button.dataset.page === name));
  if(efbHomeRequested){
    setEfbModuleShell(false, name);
    openEfbHome();
  }else{
    closeEfbHome();
    setEfbModuleShell(efbModuleMode, name);
    if(pages.includes(name)){
      $(`page-${name}`).classList.add('active');
    }else{
      const [title,text] = placeholders[name] || ['MODULE','This control position is reserved.'];
      $('placeholderTitle').textContent = title;
      $('placeholderText').textContent = text;
      $('page-placeholder').classList.add('active');
    }
  }
  $('rail').classList.remove('open');
  $('railScrim').classList.remove('open');
  history.replaceState(null,'',`#${name}`);
  document.querySelector('.workspace').scrollTo({top:0,left:0,behavior:'auto'});
  renderEfbHomeStatus();
  if(keepAwakeWanted) requestOpsWakeLock(false);
  if(name !== 'watch') stopFlightWatchStream();
  if(name !== 'datalink') stopHoppieConsole();
  if(name !== 'ground') stopGroundControl();
  if(name !== 'map') stopMapStream();
  if(name !== 'briefing' && briefingWeatherTimer){clearInterval(briefingWeatherTimer);briefingWeatherTimer=null;}
  if(name !== 'briefing') stopBriefingOfpLive();
  if(name !== 'procedures') stopProcedures();
  if(name !== 'logbook') stopLogbook();
  if(name !== 'blackbox') stopBlackBox();
  if(name !== 'raas') stopRaas(); // detailed RAAS page polling stops, global alert listener remains active
  if(name !== 'announcer') stopAnnouncements();
  if(name !== 'fids' && cameraBridgeTimer){clearInterval(cameraBridgeTimer);cameraBridgeTimer=null;}

  if(name === 'dispatch' && !dispatchLoaded) runModuleStart('dispatch', loadDispatchContext);
  if(name === 'watch') runModuleStart('watch', startFlightWatchStream);
  if(name === 'performance') runModuleStart('performance', startPerformance);
  if(name === 'raas') runModuleStart('raas', startRaas);
  if(name === 'announcer') runModuleStart('announcer', startAnnouncements);
  if(name === 'datalink') runModuleStart('datalink', startHoppieConsole);
  if(name === 'ground') runModuleStart('ground', startGroundControl);
  if(name === 'map') runModuleStart('map', startMapStream);
  if(name === 'briefing') runModuleStart('briefing', startBriefingWeatherTimer);
  if(name === 'procedures') runModuleStart('procedures', startProcedures);
  if(name === 'logbook') runModuleStart('logbook', startLogbook);
  if(name === 'blackbox') runModuleStart('blackbox', startBlackBox);
  if(name === 'finances') runModuleStart('finances', startFinances);
  if(name === 'obs') runModuleStart('obs', ()=>{updateObsTools();loadObsBranding()});
  if(name === 'scratchpad') runModuleStart('scratchpad', startScratchpad);
  if(name === 'system') runModuleStart('system', ()=>{loadStorageStatus();checkUpdates(false,true);loadStartupConsole();renderModuleVisibilityGrid()});
  if(name === 'fids') runModuleStart('fids', loadCameraBridgeStatus);
  if(name === 'network') runModuleStart('network', ()=>{loadNetwork(false);loadComms(false);if(settings?.interface?.notifications&&'Notification' in window&&Notification.permission==='default')Notification.requestPermission().catch(()=>{})});
}

function stateLamp(item){
  const state = String(item?.state || 'unknown');
  if(['connected','running','detected','configured','loaded'].includes(state)) return 'green';
  if(['standby','cached'].includes(state)) return 'amber';
  if(['fault','failed'].includes(state)) return 'red';
  return 'off';
}

function statusRow(name, item){
  return `<div class="connection-row"><span class="row-lamp lamp-${stateLamp(item)}"></span><div class="connection-name">${escapeHtml(name)}</div><div class="state ${escapeHtml(item.state)}">${escapeHtml(item.label)}</div></div>`;
}

function renderBottomStatus(data){
  const integrations=data?.integrations||{};
  const sim=integrations.telemetry||integrations.msfs||{};
  const simLabel=(sim.label&&sim.label!=='UNAVAILABLE')?sim.label:(integrations.msfs?.label||'STANDBY');
  const plan=flightPlan||{};
  const origin=plan.origin?.iata||plan.origin?.icao||'---';
  const dest=plan.destination?.iata||plan.destination?.icao||'---';
  const callsign=plan.callsign||(plan.ofp?.general?.icao_airline&&plan.ofp?.general?.flight_number?`${plan.ofp?.general?.icao_airline}${plan.ofp?.general?.flight_number}`:'');
  const simbriefText=callsign?`${callsign} ${origin}-${dest}`:(integrations.simbrief?.label||'STANDBY');
  const wakeLamp = keepAwakeState.state === 'active' ? {state:'connected'} : (keepAwakeState.state === 'error' || keepAwakeState.state === 'https' ? {state:'fault'} : {state:'standby'});
  const rows=[
    ['VATSIM', integrations.vpilot?.state==='connected'||integrations.vpilot?.state==='running'?'vPilot Running':(integrations.vatsim?.label||'Standby'), integrations.vpilot||integrations.vatsim],
    ['SIMBRIEF', simbriefText, integrations.simbrief],
    ['HOPPIE', integrations.hoppie?.state==='configured'?'Connected':'Off', integrations.hoppie],
    ['GSX', integrations.gsx?.state==='detected'?'Running':'Not detected', integrations.gsx],
    ['SIM', String(simLabel||'STANDBY').replace('CONNECTED','Connected'), sim],
    ['EFB', keepAwakeState.label || 'Keep Awake off', wakeLamp],
  ];
  $('statusStrip').innerHTML = rows.map(([name,label,item])=>`<span class="strip-item strip-readable"><i class="status-lamp lamp-${stateLamp(item)}"></i><b>${escapeHtml(name)}</b><small>${escapeHtml(label)}</small></span>`).join('');
  updateKeepAwakeUi();
}
function renderSummary(data){
  summary = data;
  settings = data.settings || settings;
  applyModuleVisibility();
  renderEfbHomeStatus();
  const labels = {msfs:'MSFS / TELEMETRY',telemetry:'TELEMETRY SOURCE',vatsim:'VATSIM IDENTITY',simbrief:'SIMBRIEF',vpilot:'VPILOT',hoppie:'HOPPIE',gsx:'GSX PRO'};
  $('connectionRows').innerHTML = Object.entries(data.integrations).map(([key,item]) => statusRow(labels[key] || key.toUpperCase(),item)).join('');
  renderBottomStatus(data);
  hydrateMasterOfpFromSummary(data, 'system-summary');

  const fault = Object.values(data.integrations).some(item => item.state === 'fault');
  $('systemNormal').classList.toggle('fault', fault);
  $('systemNormal').querySelector('b').textContent = fault ? 'SYSTEM ATTENTION' : 'SYSTEM NORMAL';

  if(data.position?.ok){
    $('nearestAirport').textContent = data.nearest_airport || '----';
    $('aircraftAltitude').textContent = formatAltitude(data.position.altitude_ft,'-----');
    $('aircraftPosition').textContent = `${Number(data.position.lat).toFixed(4)}, ${Number(data.position.lon).toFixed(4)}`;
    $('positionState').textContent = 'LIVE';
  }else{
    $('positionState').textContent = 'STANDBY';
  }
  renderHostConfiguration(data);

  const notices = [];
  if(data.integrations.msfs.state !== 'connected') notices.push(['SIMULATOR','Simulator data standing by — connectivity will resume automatically.']);
  if(data.integrations.simbrief.state === 'unconfigured') notices.push(['FLIGHT PLAN','Pilot ID required — configure in Host Settings.']);
  else if(data.integrations.simbrief.state === 'standby') notices.push(['FLIGHT PLAN','Pilot ID configured — fetch OFP to load flight data.']);
  else if(data.integrations.simbrief.state === 'fault') notices.push(['FLIGHT PLAN','OFP fetch failed — verify your SimBrief username.']);
  if(data.integrations.gsx.state !== 'detected') notices.push(['GROUND SERVICES','GSX Pro not detected — verify Addon Manager path in Host Settings.']);
  if(!notices.length) notices.push(['SYSTEM','All systems operational — standing by for flight activity.']);
  const now = new Date().toISOString().slice(11,16);
  $('advisories').innerHTML = notices.map(([level,text]) => `<div class="advisory"><time>${now} UTC</time><span class="level">${escapeHtml(level)}</span><span>${escapeHtml(text)}</span></div>`).join('');
  $('advisoryCount').textContent = `${notices.length} advisories`;
  loadStatusNotams();
}

let statusNotamsLoadedAt=0,statusNotamsData=null;
async function loadStatusNotams(force=false){
  const target=$('advisoryNotams');if(!target)return;
  if(!force&&statusNotamsLoadedAt&&Date.now()-statusNotamsLoadedAt<240000&&statusNotamsData){renderStatusNotams(statusNotamsData);return}
  try{
    const res=await fetch('/api/briefing/operational?force_refresh=false',{cache:'no-store'});
    const data=await safeJsonResponse(res);
    if(!data.ok)throw new Error(data.reason||'Operational briefing unavailable');
    statusNotamsLoadedAt=Date.now();statusNotamsData=data;
    renderStatusNotams(data);
  }catch(e){
    target.hidden=true;
  }
}
function renderStatusNotams(data){
  const target=$('advisoryNotams');if(!target)return;
  const notams=Array.isArray(data?.notams)?data.notams:[];
  const live=Array.isArray(data?.notams_live)?data.notams_live:[];
  const pick=(scope)=>notams.filter(n=>n.scope_key===scope).slice(0,3);
  const livePick=(scope)=>live.filter(n=>n.scope_key===scope).slice(0,3);
  const dep=pick('departure'),arr=pick('destination');
  const liveDep=livePick('departure'),liveArr=livePick('destination');
  if(!dep.length&&!arr.length&&!liveDep.length&&!liveArr.length){target.hidden=true;return}
  const row=(n,tag,liveTag=false)=>{
    const txt=String(n.text||'').replace(/\s+/g,' ').trim();
    return `<div class="advisory advisory-notam"><time>${escapeHtml(tag)}</time><span class="level">${escapeHtml(String(n.location||n.id||'NOTAM').split(' ')[0])}</span><span>${liveTag?'<i class="briefing-source-chip live">LIVE</i> ':''}<b>${escapeHtml(String(n.id||''))}</b> ${escapeHtml(txt.length>110?txt.slice(0,110)+'…':txt)}</span></div>`;
  };
  // v0.25.60: flight-plan DEP/ARR rows are rendered exactly as before; a
  // labelled live FAA NMS group is appended below when data exists.
  let html=`<div class="advisory-notams-title">ROUTE NOTAMS · ${dep.length+arr.length} CLOSEST</div>`+[...dep.map(n=>row(n,'DEP')),...arr.map(n=>row(n,'ARR'))].join('');
  if(liveDep.length||liveArr.length){
    html+=`<div class="advisory-notams-title live">LIVE NOTAMS · FAA NMS</div>`+[...liveDep.map(n=>row(n,'DEP',true)),...liveArr.map(n=>row(n,'ARR',true))].join('');
  }
  target.hidden=false;
  target.innerHTML=html;
}

async function loadSummary(probe=false){
  $('probeMsfs').disabled = true;
  $('probeMsfs').textContent = probe ? 'RECONNECTING...' : 'RECONNECT MSFS';
  try{
    const response = await fetch(`/api/system/summary?probe_simconnect=${probe?'true':'false'}`,{cache:'no-store'});
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    renderSummary(await response.json());
  }catch(error){
    $('advisories').innerHTML = `<div class="advisory"><time>--:-- UTC</time><span class="level">FAULT</span><span>${escapeHtml(error.message)}</span></div>`;
  }finally{
    $('probeMsfs').disabled = false;
    $('probeMsfs').textContent = 'RECONNECT MSFS';
  }
}

function utcHm(value){
  if(!value) return '----';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '----' : `${String(date.getUTCHours()).padStart(2,'0')}:${String(date.getUTCMinutes()).padStart(2,'0')}Z`;
}

function duration(value){
  const seconds = Number(value);
  if(!Number.isFinite(seconds) || seconds <= 0) return '---';
  const h = Math.floor(seconds/3600);
  const m = Math.floor((seconds%3600)/60);
  return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}`;
}

function numberOr(value, suffix=''){
  if(value === null || value === undefined || value === '') return '---';
  const n = Number(value);
  return Number.isFinite(n) ? `${Math.round(n).toLocaleString()}${suffix}` : `${escapeHtml(value)}${suffix}`;
}

function unitPrefs(){
  return settings?.interface?.units || {weight:'kg',distance:'nm',altitude:'ft',speed:'kt',vertical_speed:'fpm'};
}
function formatDistance(nm, empty='---'){
  const n=Number(nm); if(!Number.isFinite(n))return empty;
  if(unitPrefs().distance==='km')return `${Math.round(n*1.852).toLocaleString()} KM`;
  return `${Math.round(n).toLocaleString()} NM`;
}
function formatAltitude(ft, empty='---'){
  const n=Number(ft); if(!Number.isFinite(n))return empty;
  if(unitPrefs().altitude==='m')return `${Math.round(n*0.3048).toLocaleString()} M`;
  return `${Math.round(n).toLocaleString()} FT`;
}
function formatSpeed(kts, empty='---'){
  const n=Number(kts); if(!Number.isFinite(n))return empty;
  if(unitPrefs().speed==='kmh')return `${Math.round(n*1.852).toLocaleString()} KM/H`;
  return `${Math.round(n).toLocaleString()} KT`;
}
function formatVerticalSpeed(fpm, empty='---'){
  const n=Number(fpm); if(!Number.isFinite(n))return empty;
  if(unitPrefs().vertical_speed==='mps')return `${(n*0.00508).toFixed(1)} M/S`;
  return `${Math.round(n).toLocaleString()} FPM`;
}
function formatWeightFromLb(lb, empty='---'){
  const n=Number(lb); if(!Number.isFinite(n))return empty;
  if(unitPrefs().weight==='kg')return `${Math.round(n*0.45359237).toLocaleString()} KG`;
  return `${Math.round(n).toLocaleString()} LB`;
}
function formatPlanWeight(value, sourceUnits){
  const n=Number(value); if(!Number.isFinite(n))return '---';
  const source=String(sourceUnits||'').toUpperCase();
  let lb=n;
  if(source.startsWith('KG'))lb=n/0.45359237;
  return formatWeightFromLb(lb);
}

function airportDisplay(ap){
  const icao=escapeHtml(ap?.icao||'---');
  const name=escapeHtml(ap?.name||'');
  return name?`${icao}<small class="airport-fullname">${name}</small>`:icao;
}
function airportPlain(ap){
  const code=ap?.icao||'---';
  return ap?.name?`${code} · ${ap.name}`:code;
}

async function applyAirlineTheme(){
  const clearTheme = () => {
    document.body.classList.remove('airline-theme','airline-theme-full','airline-theme-accent-only');
    ['--airline-bg-image','--airline-overlay-start','--airline-overlay-end'].forEach(name=>document.documentElement.style.removeProperty(name));
    const defaults = {'--amber':'#efbd47','--amber-pale':'#ffe09a','--bg':'#080a07','--panel':'#12150f','--line':'#4b4e3a','--line-bright':'#73765a'};
    Object.entries(defaults).forEach(([name,value])=>document.documentElement.style.setProperty(name,value));
  };
  try{
    const data=await fetch('/api/interface/theme',{cache:'no-store'}).then(r=>r.json());
    clearTheme();
    if(!data.active){
      renderEfbHomeStatus();
      return;
    }
    document.body.classList.add('airline-theme');
    document.body.classList.add(data.mode==='accent'?'airline-theme-accent-only':'airline-theme-full');
    document.documentElement.style.setProperty('--amber',data.accent||'#71b4c3');
    document.documentElement.style.setProperty('--amber-pale',data.accent_pale||'#d3edf2');
    document.documentElement.style.setProperty('--bg',data.background||'#101214');
    document.documentElement.style.setProperty('--panel',data.panel||'#191c1f');
    document.documentElement.style.setProperty('--line',data.line||'#59676d');
    document.documentElement.style.setProperty('--line-bright',data.line||'#59676d');
    document.documentElement.style.setProperty('--airline-bg-image',`url(${data.background_url})`);
    document.documentElement.style.setProperty('--airline-overlay-start',data.overlay_start||'rgba(8,10,7,.62)');
    document.documentElement.style.setProperty('--airline-overlay-end',data.overlay_end||'rgba(8,10,7,.78)');
    renderEfbHomeStatus();
  }catch{
    clearTheme();
    renderEfbHomeStatus();
  }
}

function renderActiveFlight(plan){
  const holder = $('activeFlight');
  if(!plan?.ok){
    $('flightState').textContent = plan?.state === 'fault' ? 'OFP FETCH FAILED' : 'NO OFP LOADED';
    holder.className = 'empty-flight';
    holder.innerHTML = `<div class="route-placeholder">---- <b>TO</b> ----</div><p>${escapeHtml(plan?.reason || 'Set a SimBrief Pilot ID in the OPS ROOM desktop host, then fetch the latest operational flight plan.')}</p>`;
    renderEfbHomeStatus();
    return;
  }
  const origin = plan.origin?.icao || '----';
  const destination = plan.destination?.icao || '----';
  const originName = plan.origin?.name || '';
  const destinationName = plan.destination?.name || '';
  const altitude = plan.cruise_altitude_ft ? `FL${String(Math.round(plan.cruise_altitude_ft/100)).padStart(3,'0')}` : '---';
  const depRunway = plan.origin?.runway ? `RWY ${plan.origin.runway}` : 'RWY ---';
  const arrRunway = plan.destination?.runway ? `RWY ${plan.destination.runway}` : 'RWY ---';
  $('flightState').textContent = 'OFP loaded';
  holder.className = 'active-flight';
  holder.innerHTML = `
    <div class="active-flight-hero">
      <div class="flight-brand-row">${airlineBrandHtml(plan,'large',true)}<div class="flight-ident-line"><span>${escapeHtml(resolvedAirlineBranding(plan)?.name||'Active flight')}</span><strong>${escapeHtml(plan.callsign || 'NO CALLSIGN')}</strong><small>${escapeHtml([plan.aircraft?.icao,plan.aircraft?.registration].filter(Boolean).join(' · '))}</small></div></div>
      <div class="active-route-block"><div class="active-route"><b>${escapeHtml(origin)}</b><i>TO</i><b>${escapeHtml(destination)}</b></div><div class="active-route-name-row"><span>${escapeHtml(originName || 'Departure airport')}</span><i></i><span>${escapeHtml(destinationName || 'Arrival airport')}</span></div></div>
    </div>
    <div class="flight-register">
      <div><span>CRUISE</span><b>${altitude}</b></div>
      <div><span>EOBT</span><b>${utcHm(plan.times?.scheduled_out)}</b></div>
      <div><span>ETE</span><b>${duration(plan.ete_seconds)}</b></div>
      <div><span>DISTANCE</span><b>${formatDistance(plan.distance_nm)}</b></div>
      <div><span>ALTERNATE</span><b>${escapeHtml(plan.alternate?.icao || 'NONE')}</b></div>
      <div><span>COST INDEX</span><b>${escapeHtml(plan.cost_index || '---')}</b></div>
    </div>`;
  renderEfbHomeStatus();
}


function simbriefStatusPlan(data=summary){
  const plan=data?.integrations?.simbrief?.plan;
  return plan && plan.ok ? plan : null;
}
function hasSimbriefConfigured(){
  return !!(
    settings?.identity?.simbrief_configured ||
    settings?.identity?.simbrief_user_id ||
    settings?.identity?.simbrief_username ||
    summary?.integrations?.simbrief?.state === 'loaded' ||
    summary?.integrations?.simbrief?.state === 'standby' ||
    simbriefStatusPlan(summary)
  );
}
function hydrateMasterOfpFromSummary(data=summary, source='summary'){
  const plan=simbriefStatusPlan(data);
  if(!plan) return false;
  const samePlan = flightPlan?.ok && (
    (plan.plan_id && flightPlan.plan_id === plan.plan_id) ||
    (plan.generated_utc && flightPlan.generated_utc === plan.generated_utc) ||
    (plan.callsign && flightPlan.callsign === plan.callsign && plan.origin?.icao === flightPlan.origin?.icao && plan.destination?.icao === flightPlan.destination?.icao)
  );
  if(!samePlan){
    flightPlan = {...plan, cache: plan.cache || source};
    renderActiveFlight(flightPlan);
    renderBriefing(flightPlan);
    if(activePage === 'briefing') startBriefingWeatherTimer();
    renderEfbHomeStatus();
    if (typeof cfRenderQuickPicks === 'function') cfRenderQuickPicks();
  }
  return true;
}
async function autoFetchMasterOFP(reason='boot'){
  if(ofpFetchInProgress) return;
  if(settings?.integrations?.simbrief_auto_load === false) return;
  if(!hasSimbriefConfigured()) return;
  ofpAutoFetchStarted = true;
  ofpFetchInProgress = true;
  if($('simbriefFetchState')) $('simbriefFetchState').textContent = 'Refreshing OFP';
  try{
    // Use the same master Status Board Fetch OFP path as the manual button.
    // This hydrates the shared SimBrief cache that all modules consume.
    await loadFlight(true);
  }catch(error){
    console.warn('OPS ROOM auto OFP fetch failed', reason, error);
  }finally{
    ofpFetchInProgress = false;
  }
}

function briefingCell(label, value, className=''){
  return `<div class="brief-cell ${className}"><span>${escapeHtml(label)}</span><b>${value || '---'}</b></div>`;
}

let briefingSection='overview';
let operationalBriefingLoadedAt=0;
let operationalBriefingData=null;
let briefingNotamFilter='all';
// v0.25.60: FAA NMS live NOTAMs are the default source when available;
// 'flightplan' / 'combined' are opt-in alternatives. Persisted like other
// module preferences. 'auto' means: live if notams_live has data, else plan.
let briefingNotamSource=localStorage.getItem('opsroom-notam-source')||'auto';
async function setBriefingSection(name){
  briefingSection=String(name||'overview').toLowerCase();
  document.querySelectorAll('[data-briefing-section]').forEach(panel=>{panel.hidden=panel.dataset.briefingSection!==briefingSection});
  document.querySelectorAll('[data-briefing-tab]').forEach(button=>button.classList.toggle('active',button.dataset.briefingTab===briefingSection));
  if(briefingSection==='weather')refreshBriefingWeather(false);
  if(['notams','hazards','sigwx','charts'].includes(briefingSection))loadOperationalBriefing(false);
  if(briefingSection==='notams')refreshClosureDeploy(false);
  if(briefingSection==='charts'){ await loadCharts(); cfState.pins = cfLoadPins(); cfRenderPinnedStrip(); if(cfState && cfState.airport) cfLoadAirport(cfState.airport); }
  // v0.25.65: live OFP completion polling follows the OFP section visibility.
  if(briefingSection==='ofp' && briefingOfpLiveOpen) startBriefingOfpLive();
  else stopBriefingOfpLive();
}
function briefingUtc(value){
  const formatted=utcHm(value);
  return formatted==='----'?'---':formatted;
}
function briefingDateTime(value){
  if(!value)return '---';
  const date=new Date(value);
  if(Number.isNaN(date.getTime()))return '---';
  const months=['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
  return `${String(date.getUTCDate()).padStart(2,'0')} ${months[date.getUTCMonth()]} ${date.getUTCFullYear()} ${String(date.getUTCHours()).padStart(2,'0')}:${String(date.getUTCMinutes()).padStart(2,'0')}Z`;
}
function briefingSourceLine(data){
  const source=(data?.sources||[])[0]||{},updates=data?.database_updates||source.updates||{};
  const parts=['SIMBRIEF'];
  const add=(label,value)=>{const stamp=briefingUtc(value);if(stamp!=='---')parts.push(`${label} ${stamp}`)};
  add('OFP',source.generated_utc);
  add('NOTAMS',updates.notams);
  add('HAZARDS',updates.sigmet);
  add('SIGWX',updates.sigwx);
  add('WINDS',updates.winds);
  return `<div class="briefing-source-line">${escapeHtml(parts.join(' · '))}</div>`;
}
function briefingNoticeCard(item){
  const validity=[];
  if(item.effective_utc)validity.push(`EFFECTIVE ${briefingDateTime(item.effective_utc)}`);
  if(item.permanent)validity.push('EXPIRES PERMANENT');else if(item.expires_utc)validity.push(`EXPIRES ${briefingDateTime(item.expires_utc)}${item.expires_estimated?' EST':''}`);
  const badges=[item.category,item.status,item.qcode].filter(Boolean);
  // v0.25.60: source chip distinguishes live FAA NMS rows from flight-plan rows.
  const src=String(item.source||'').toUpperCase();
  const sourceChip=src==='FAA NMS'?`<i class="briefing-source-chip live">LIVE</i>`:(src?`<i class="briefing-source-chip">${escapeHtml(src)}</i>`:'');
  // v0.25.65: plain-English expansion when available; raw ICAO always kept.
  const body = item.translated_text || item.text || '';
  const showRaw = item.raw && (item.translated_text || item.raw.trim() !== String(item.text||'').trim());
  return `<article class="briefing-notice" data-notam-scope="${escapeHtml(item.scope_key||'enroute')}"><header><div><strong>${escapeHtml(item.id||'NOTICE')}</strong><small>${escapeHtml(item.scope||item.location||'Flight briefing')}</small></div><span>${escapeHtml(item.location_name||item.location||item.source||'SIMBRIEF')}</span></header>${(badges.length||sourceChip)?`<div class="briefing-notice-badges">${sourceChip}${item.translated_text?`<i class="briefing-source-chip plain">PLAIN ENGLISH</i>`:''}${badges.map(x=>`<i>${escapeHtml(x)}</i>`).join('')}</div>`:''}<pre>${escapeHtml(body)}</pre>${validity.length||item.schedule?`<footer><span>${escapeHtml(validity.join(' · '))}</span>${item.schedule?`<span>${escapeHtml(item.schedule)}</span>`:''}</footer>`:''}${showRaw?`<details><summary>RAW ICAO NOTAM</summary><pre>${escapeHtml(item.raw)}</pre></details>`:''}</article>`;
}
function briefingNotices(rows,emptyText){
  const items=Array.isArray(rows)?rows:[];
  if(!items.length)return `<div class="briefing-operational-empty">${escapeHtml(emptyText)}</div>`;
  return `<div class="briefing-notice-list">${items.map(briefingNoticeCard).join('')}</div>`;
}
// v0.25.60: resolve which row set the NOTAMs tab shows, based on the source
// selector (auto → live when available, otherwise flight plan).
function briefingNotamRowSets(data){
  const plan=Array.isArray(data?.notams)?data.notams:[];
  const live=Array.isArray(data?.notams_live)?data.notams_live:[];
  let source=briefingNotamSource;
  if(source==='auto') source=live.length?'live':'flightplan';
  let rows;
  if(source==='live') rows=live;
  else if(source==='flightplan') rows=plan;
  else{
    // Combined: flight-plan first, then live rows whose id/location don't collide.
    const seen=new Set(plan.map(r=>`${String(r.id||'').toUpperCase()}:${String(r.location||'').toUpperCase()}`));
    rows=[...plan,...live.filter(r=>!seen.has(`${String(r.id||'').toUpperCase()}:${String(r.location||'').toUpperCase()}`))];
  }
  return {plan,live,rows,source};
}
function briefingNotamGroupCounts(rows){
  const counts={all:rows.length,departure:0,destination:0,alternate:0,enroute:0};
  rows.forEach(r=>{const k=String(r.scope_key||'enroute');if(k in counts)counts[k]++});
  return counts;
}
function renderBriefingNotams(data){
  const target=$('briefingNotams');if(!target)return;
  const sets=briefingNotamRowSets(data);
  const rows=sets.rows,counts=briefingNotamGroupCounts(rows);
  const filters=[['all','ALL'],['departure','DEPARTURE'],['destination','DESTINATION'],['alternate','ALTERNATE'],['enroute','EN-ROUTE']];
  const liveCount=sets.live.length,planCount=sets.plan.length;
  const resolved=sets.source;
  const selector=`<div class="briefing-notam-source" role="tablist">`+
    `<button type="button" data-notam-source="live" class="${resolved==='live'?'active':''}">LIVE NOTAMS<b>${liveCount}</b></button>`+
    `<button type="button" data-notam-source="flightplan" class="${resolved==='flightplan'?'active':''}">FLIGHT PLAN<b>${planCount}</b></button>`+
    `<button type="button" data-notam-source="combined" class="${resolved==='combined'?'active':''}">COMBINED<b>${sets.rows.length}</b></button>`+
    `</div>`;
  target.innerHTML=`${briefingSourceLine(data)}${selector}<div class="briefing-notam-tools"><div class="briefing-filter-chips">${filters.map(([key,label])=>`<button type="button" data-notam-filter="${key}" class="${briefingNotamFilter===key?'active':''}">${label}<b>${Number(counts[key]??(key==='all'?rows.length:0))}</b></button>`).join('')}</div><label class="briefing-notam-search"><span>SEARCH</span><input id="briefingNotamSearch" type="search" placeholder="ID, airport, runway, approach, airspace..." autocomplete="off"></label></div><div id="briefingNotamResults"></div>`;
  target.querySelectorAll('[data-notam-source]').forEach(button=>button.addEventListener('click',()=>{
    briefingNotamSource=button.dataset.notamSource||'auto';
    try{localStorage.setItem('opsroom-notam-source',briefingNotamSource)}catch(_){}
    renderBriefingNotams(operationalBriefingData||data);
  }));
  target.querySelectorAll('[data-notam-filter]').forEach(button=>button.addEventListener('click',()=>{briefingNotamFilter=button.dataset.notamFilter||'all';target.querySelectorAll('[data-notam-filter]').forEach(x=>x.classList.toggle('active',x===button));applyBriefingNotamFilter()}));
  $('briefingNotamSearch')?.addEventListener('input',applyBriefingNotamFilter);
  applyBriefingNotamFilter();
}
function applyBriefingNotamFilter(){
  const target=$('briefingNotamResults');if(!target||!operationalBriefingData)return;
  const query=String($('briefingNotamSearch')?.value||'').trim().toUpperCase();
  const sets=briefingNotamRowSets(operationalBriefingData);
  const rows=sets.rows.filter(row=>{
    if(briefingNotamFilter!=='all'&&String(row.scope_key||'enroute')!==briefingNotamFilter)return false;
    if(!query)return true;
    return [row.id,row.location,row.location_name,row.category,row.status,row.qcode,row.text,row.raw].some(value=>String(value||'').toUpperCase().includes(query));
  });
  target.innerHTML=briefingNotices(rows,query?'No NOTAM matches this search.':'No NOTAMs were included for this scope.');
}
function renderBriefingHazards(data){
  const target=$('briefingHazards');if(!target)return;
  const sections=Array.isArray(data?.hazards?.sections)?data.hazards.sections:[];
  target.innerHTML=`${briefingSourceLine(data)}<div class="briefing-hazard-grid">${sections.map(section=>{const items=Array.isArray(section.items)?section.items:[],state=String(section.state||'not_included');const message=state==='none'?'No current reports in this OFP.':state==='not_included'?'This category was not included in the current OFP.':'No reports returned.';return `<section class="briefing-hazard-card ${escapeHtml(state)}"><header><strong>${escapeHtml(section.label||'HAZARD')}</strong><span>${items.length?`${items.length} ACTIVE`:(state==='none'?'NONE':'NOT INCLUDED')}</span></header>${items.length?briefingNotices(items,message):`<p>${escapeHtml(message)}</p>`}</section>`}).join('')}</div>`;
}
function briefingGallery(items,emptyText){
  const rows=Array.isArray(items)?items:[];
  if(!rows.length)return `<div class="briefing-operational-empty">${escapeHtml(emptyText)}</div>`;
  return `<div class="briefing-simbrief-gallery">${rows.map(chart=>`<figure class="briefing-simbrief-chart"><figcaption><div><strong>${escapeHtml(chart.label||chart.name||'SIMBRIEF CHART')}</strong><span>${escapeHtml(chart.source||'SIMBRIEF')}</span></div><div><a href="${escapeHtml(chart.download_url||chart.url||'#')}" download>DOWNLOAD</a><button type="button" data-briefing-image="${escapeHtml(chart.url||'')}" data-briefing-image-remote="${escapeHtml(chart.remote_url||'')}" data-briefing-image-download="${escapeHtml(chart.download_url||chart.url||'')}" data-briefing-image-label="${escapeHtml(chart.label||chart.name||'SIMBRIEF CHART')}">EXPAND</button></div></figcaption><button class="briefing-chart-image" type="button" data-briefing-image="${escapeHtml(chart.url||'')}" data-briefing-image-remote="${escapeHtml(chart.remote_url||'')}" data-briefing-image-download="${escapeHtml(chart.download_url||chart.url||'')}" data-briefing-image-label="${escapeHtml(chart.label||chart.name||'SIMBRIEF CHART')}"><img src="${escapeHtml(chart.url||'')}" data-remote-src="${escapeHtml(chart.remote_url||'')}" loading="lazy" decoding="async" alt="${escapeHtml(chart.label||chart.name||'SimBrief chart')}"></button></figure>`).join('')}</div>`;
}
function attachBriefingImageActions(){
  document.querySelectorAll('[data-briefing-image]').forEach(node=>node.addEventListener('click',()=>openBriefingImageViewer(node.dataset.briefingImage||node.dataset.briefingImageRemote||'',node.dataset.briefingImageLabel||'SIMBRIEF CHART',node.dataset.briefingImageDownload||node.dataset.briefingImage||node.dataset.briefingImageRemote||'')));
  document.querySelectorAll('.briefing-chart-image img').forEach(image=>{
    image.addEventListener('load',()=>image.closest('.briefing-simbrief-chart')?.classList.add('image-loaded'));
    image.addEventListener('error',()=>{
      const remote=image.dataset.remoteSrc||'',figure=image.closest('.briefing-simbrief-chart');
      if(remote&&image.dataset.remoteTried!=='1'){
        image.dataset.remoteTried='1';
        figure?.querySelectorAll('[data-briefing-image]').forEach(node=>{node.dataset.briefingImage=remote;node.dataset.briefingImageDownload=remote});
        const link=figure?.querySelector('figcaption a');if(link)link.href=remote;
        image.src=remote;return;
      }
      figure?.classList.add('image-unavailable');
      const holder=image.closest('.briefing-chart-image');if(holder&&!holder.querySelector('.briefing-chart-image-error'))holder.insertAdjacentHTML('beforeend','<span class="briefing-chart-image-error">CHART IMAGE UNAVAILABLE<br><small>THE COMPLETE CHART REMAINS IN VIEW OFP</small></span>');
    });
  });
}
function renderBriefingSigwx(data){const target=$('briefingSigwx');if(!target)return;target.innerHTML=`${briefingSourceLine(data)}${briefingGallery(data?.sigwx?.charts,data?.sigwx?.message||'No SIGWX images were included in the current SimBrief OFP.')}`;attachBriefingImageActions()}
function renderBriefingCharts(data){
  const target=$('briefingSimbriefCharts');if(!target)return;
  const charts=Array.isArray(data?.charts)?data.charts:[],groups=[['route','ROUTE MAP'],['winds','WINDS ALOFT'],['profile','VERTICAL PROFILE'],['other','OTHER']];
  target.innerHTML=`${briefingSourceLine(data)}${groups.map(([key,label])=>{const rows=charts.filter(x=>String(x.category||'other')===key);return rows.length?`<section class="briefing-chart-group"><h3>${label}</h3>${briefingGallery(rows,'')}</section>`:''}).join('')||'<div class="briefing-operational-empty">No separate chart images were included in the current SimBrief OFP.</div>'}`;
  attachBriefingImageActions();
}
async function loadOperationalBriefing(force=false){
  const targets=[$('briefingNotams'),$('briefingHazards'),$('briefingSigwx'),$('briefingSimbriefCharts')];if(!targets.some(Boolean))return;
  if(!force&&operationalBriefingLoadedAt&&Date.now()-operationalBriefingLoadedAt<240000&&operationalBriefingData){renderBriefingNotams(operationalBriefingData);renderBriefingHazards(operationalBriefingData);renderBriefingSigwx(operationalBriefingData);renderBriefingCharts(operationalBriefingData);return}
  targets.forEach(node=>{if(node)node.innerHTML='<div class="briefing-operational-empty">Reading structured SimBrief OFP data...</div>'});
  try{
    const response=await fetch(`/api/briefing/operational?force_refresh=${force?'true':'false'}`,{cache:'no-store'});const data=await safeJsonResponse(response);if(!data.ok)throw new Error(data.reason||'Operational briefing unavailable');
    operationalBriefingLoadedAt=Date.now();operationalBriefingData=data;
    renderBriefingNotams(data);renderBriefingHazards(data);renderBriefingSigwx(data);renderBriefingCharts(data);
  }catch(error){targets.forEach(node=>{if(node)node.innerHTML=`<div class="briefing-operational-empty">${escapeHtml(friendlyError(error.message))}</div>`})}
}
let briefingImageScale=1,briefingImageX=0,briefingImageY=0,briefingImageDragging=false,briefingImageDragStart=null;
function applyBriefingImageTransform(){const image=$('briefingImageViewerImg');if(image)image.style.transform=`translate(${briefingImageX}px,${briefingImageY}px) scale(${briefingImageScale})`;if($('briefingImageZoomReadout'))$('briefingImageZoomReadout').textContent=`${Math.round(briefingImageScale*100)}%`}
function resetBriefingImageViewer(){briefingImageScale=1;briefingImageX=0;briefingImageY=0;applyBriefingImageTransform()}
function openBriefingImageViewer(url,label,downloadUrl){const viewer=$('briefingImageViewer'),image=$('briefingImageViewerImg');if(!viewer||!image||!url)return;viewer.hidden=false;image.src=url;if($('briefingImageViewerTitle'))$('briefingImageViewerTitle').textContent=label||'SIMBRIEF CHART';const dl=$('briefingImageViewerDownload');if(dl)dl.href=downloadUrl||url;resetBriefingImageViewer();document.body.classList.add('briefing-image-open')}
function closeBriefingImageViewer(){const viewer=$('briefingImageViewer');if(viewer)viewer.hidden=true;document.body.classList.remove('briefing-image-open')}
function setupBriefingImageViewer(){
  const stage=$('briefingImageViewerStage');if(!stage||stage.dataset.ready==='1')return;stage.dataset.ready='1';
  $('briefingImageViewerClose')?.addEventListener('click',closeBriefingImageViewer);$('briefingImageZoomIn')?.addEventListener('click',()=>{briefingImageScale=Math.min(5,briefingImageScale*1.2);applyBriefingImageTransform()});$('briefingImageZoomOut')?.addEventListener('click',()=>{briefingImageScale=Math.max(.35,briefingImageScale/1.2);applyBriefingImageTransform()});$('briefingImageZoomReset')?.addEventListener('click',resetBriefingImageViewer);
  stage.addEventListener('wheel',event=>{event.preventDefault();const previous=briefingImageScale;briefingImageScale=Math.max(.35,Math.min(5,briefingImageScale*(event.deltaY<0?1.12:.89)));const rect=stage.getBoundingClientRect(),px=event.clientX-rect.left-rect.width/2,py=event.clientY-rect.top-rect.height/2,ratio=briefingImageScale/previous;briefingImageX=px-(px-briefingImageX)*ratio;briefingImageY=py-(py-briefingImageY)*ratio;applyBriefingImageTransform()},{passive:false});
  stage.addEventListener('pointerdown',event=>{briefingImageDragging=true;briefingImageDragStart={x:event.clientX-briefingImageX,y:event.clientY-briefingImageY};stage.setPointerCapture(event.pointerId)});stage.addEventListener('pointermove',event=>{if(!briefingImageDragging||!briefingImageDragStart)return;briefingImageX=event.clientX-briefingImageDragStart.x;briefingImageY=event.clientY-briefingImageDragStart.y;applyBriefingImageTransform()});stage.addEventListener('pointerup',()=>{briefingImageDragging=false;briefingImageDragStart=null});
}
function renderBriefing(plan){
  const target = $('briefingContent');
  if(!plan?.ok){
    target.innerHTML = `<section class="panel briefing-empty"><header><span>Flight briefing</span><span>Not loaded</span></header><div><strong>No operational flight plan loaded</strong><p>${escapeHtml(plan?.reason || 'Configure a SimBrief Pilot ID in the OPS ROOM desktop host and use Refresh OFP.')}</p></div></section>`;
    return;
  }
  const units = plan.fuel?.units || plan.weights?.units || '';
  const altitude = plan.cruise_altitude_ft ? `FL${String(Math.round(plan.cruise_altitude_ft/100)).padStart(3,'0')}` : '---';
  const depRunway = plan.origin?.runway ? `RWY ${plan.origin.runway}` : 'RWY ---';
  const arrRunway = plan.destination?.runway ? `RWY ${plan.destination.runway}` : 'RWY ---';
  target.innerHTML = `
    <section class="panel briefing-banner">
      <header><span>Flight briefing</span><span>${escapeHtml(plan.generated_utc ? `Updated ${utcHm(plan.generated_utc)}` : 'OFP loaded')}</span></header>
      <div class="briefing-hero">
        <div class="briefing-identity">
          <div class="briefing-airline-logo">${airlineBrandHtml(plan,'hero',false)}</div>
          <div class="briefing-flight"><span>${escapeHtml(resolvedAirlineBranding(plan)?.name||'Flight')}</span><strong>${escapeHtml(plan.callsign || 'No callsign')}</strong><small>${escapeHtml([plan.aircraft?.icao,plan.aircraft?.registration].filter(Boolean).join(' · ')||'Aircraft not specified')}</small></div>
        </div>
        <div class="briefing-route-summary"><div><b>${escapeHtml(plan.origin?.icao || '----')}</b><i>&rarr;</i><b>${escapeHtml(plan.destination?.icao || '----')}</b></div><small>${escapeHtml(airportPlain(plan.origin))} → ${escapeHtml(airportPlain(plan.destination))}</small></div>
        <div class="briefing-action"><button id="briefingViewOfp" class="control-button" type="button">View OFP</button></div>
      </div>
    </section>
    <nav class="briefing-section-tabs" aria-label="Briefing sections">
      ${[['overview','OVERVIEW'],['weather','WEATHER'],['notams','NOTAMS'],['hazards','HAZARDS'],['sigwx','SIGWX'],['charts','CHARTS'],['ofp','OFP']].map(([key,label])=>`<button type="button" data-briefing-tab="${key}">${label}</button>`).join('')}
    </nav>
    <div class="briefing-section-panel" data-briefing-section="overview">
      <section class="panel briefing-panel route-panel"><header><span>Route and schedule</span><span>Current OFP</span></header><div class="brief-grid six">
        ${briefingCell('ORIGIN',`${airportDisplay(plan.origin)} · ${depRunway}`)}${briefingCell('DESTINATION',`${airportDisplay(plan.destination)} · ${arrRunway}`)}${briefingCell('ALTERNATE',plan.alternate?.icao?airportDisplay(plan.alternate):'NONE')}${briefingCell('CRUISE',altitude)}${briefingCell('EOBT',utcHm(plan.times?.scheduled_out))}${briefingCell('ETE',duration(plan.ete_seconds))}
      </div><div class="route-text"><span>ROUTE</span><p>${escapeHtml(plan.route || 'NO ROUTE RETURNED')}</p></div></section>
      <section class="panel briefing-panel"><header><span>Fuel plan</span><span>${escapeHtml(units)}</span></header><div class="brief-grid four">
        ${briefingCell('RAMP',formatPlanWeight(plan.fuel?.ramp,plan.fuel?.units))}${briefingCell('TAKEOFF',formatPlanWeight(plan.fuel?.takeoff,plan.fuel?.units))}${briefingCell('TRIP',formatPlanWeight(plan.fuel?.trip,plan.fuel?.units))}${briefingCell('LANDING',formatPlanWeight(plan.fuel?.landing,plan.fuel?.units))}${briefingCell('RESERVE',formatPlanWeight(plan.fuel?.reserve,plan.fuel?.units))}${briefingCell('ALTERNATE',formatPlanWeight(plan.fuel?.alternate,plan.fuel?.units))}${briefingCell('EXTRA',formatPlanWeight(plan.fuel?.extra,plan.fuel?.units))}${briefingCell('DISPLAY UNITS',unitPrefs().weight.toUpperCase())}
      </div></section>
      <section class="panel briefing-panel"><header><span>Load and aircraft</span><span>Planned</span></header><div class="brief-grid four">
        ${briefingCell('PASSENGERS',numberOr(plan.weights?.passengers))}${briefingCell('CARGO',formatPlanWeight(plan.weights?.cargo,plan.weights?.units))}${briefingCell('PAYLOAD',formatPlanWeight(plan.weights?.payload,plan.weights?.units))}${briefingCell('ZFW',formatPlanWeight(plan.weights?.zfw,plan.weights?.units))}${briefingCell('TOW',formatPlanWeight(plan.weights?.tow,plan.weights?.units))}${briefingCell('LDW',formatPlanWeight(plan.weights?.ldw,plan.weights?.units))}${briefingCell('COST INDEX',escapeHtml(plan.cost_index || '---'))}${briefingCell('DISTANCE',formatDistance(plan.distance_nm))}
      </div></section>
    </div>
    <div class="briefing-section-panel" data-briefing-section="weather" hidden><section class="panel briefing-panel weather-panel"><header><span>Weather and ATIS</span><span id="briefingWeatherUpdated">Updates every 5 min</span></header><div id="briefingLiveWeather" class="briefing-live-weather"><article><h3>LOADING</h3><small>Fetching live briefing weather...</small></article></div></section></div>
    <div class="briefing-section-panel" data-briefing-section="notams" hidden><section class="panel briefing-panel"><header><span>Route-relevant NOTAMs</span><span>Structured SimBrief OFP data</span></header><section id="simClosureDeploy" class="panel briefing-panel sim-closure-deploy" hidden><!-- v0.25.71: closure-marker DEPLOY IN SIM control is hidden (feature shelved; re-enable later) --><header><span>Runway & taxiway closure markers</span><span>NOTAM → MSFS SimObjects</span></header><div class="sim-closure-body"><div class="sim-closure-actions"><button id="closureDeployToggle" class="control-button closure-deploy-toggle" type="button" aria-pressed="false">DEPLOY IN SIM</button><button id="closureDeployClear" class="control-button closure-deploy-clear" type="button">REMOVE</button></div><div id="closureDeployStatus" class="map-layer-status">CLOSURE MARKERS — OFF · NO DEPLOYMENT</div><div id="closureDeployInstall" class="map-layer-status dim" hidden></div></div></section><div id="briefingNotams"></div></section></div>
    <div class="briefing-section-panel" data-briefing-section="hazards" hidden><section class="panel briefing-panel"><header><span>Aviation weather hazards</span><span>AIRMET · SIGMET · TC · VA</span></header><div id="briefingHazards"></div></section></div>
    <div class="briefing-section-panel" data-briefing-section="sigwx" hidden><section class="panel briefing-panel"><header><span>SIGWX</span><span>Separate SimBrief chart images</span></header><div id="briefingSigwx"></div></section></div>
    <div class="briefing-section-panel" data-briefing-section="charts" hidden><section class="panel briefing-panel" id="briefingChartFoxSection"><header><span>ChartFox charts</span><span>ChartFox API</span></header><div id="briefingChartFoxPanel" class="bridge-charts-panel"><b>LOADING CHARTFOX...</b></div></section><section class="panel briefing-panel"><header><span>SimBrief briefing charts</span><span>Route · winds · vertical profile</span></header><div id="briefingSimbriefCharts"></div></section><!-- v0.25.60 RC: legacy briefingChartViewer + briefingChartFrame iframe removed (was a hidden dead block that confused users who saw "chartfox.org refused to connect"). ChartFox charts render exclusively through cfRenderPreview (img via proxy + PDF.js canvas). --></div>
    <div class="briefing-section-panel" data-briefing-section="ofp" hidden><section id="briefingOfpPanel" class="panel briefing-panel ofp-embed-panel"><header><span>Operational flight plan</span><span></span></header>${(()=>{const pdf=plan.files?.pdf_local||plan.files?.pdf;const src=`/api/simbrief/ofp-view?theme=${encodeURIComponent(briefingOfpTheme)}`;return `<div class="briefing-ofp-actions"><div class="ofp-theme-buttons"><button id="ofpThemeDark" class="${briefingOfpTheme==='dark'?'active':''}" type="button">DARK</button><button id="ofpThemeLight" class="${briefingOfpTheme==='light'?'active':''}" type="button">LIGHT</button></div><div class="ofp-reader-actions"><span class="page-readout">OFP reader</span><button id="ofpLiveToggle" class="ofp-live-chip ${briefingOfpLiveOpen?'active':''}" type="button" aria-expanded="${briefingOfpLiveOpen?'true':'false'}" title="Toggle the live OFP completion panel">◈ LIVE OFP</button>${pdf?`<a class="control-button" href="${escapeHtml(pdf)}" target="opsroom-ofp-pdf" rel="noopener">Open SimBrief PDF</a>`:''}</div></div><section id="briefingOfpLivePanel" class="ofp-live-panel" ${briefingOfpLiveOpen?'':'hidden'}><div class="network-empty">LIVE OFP completion is standing by — click ◈ LIVE OFP to open the live comparison.</div></section><iframe id="briefingOfpFrame" class="briefing-ofp-frame" src="${escapeHtml(src)}" title="Operational Flight Plan"></iframe>`;})()}</section></div>
    <div id="briefingImageViewer" class="briefing-image-viewer" hidden><div class="briefing-image-viewer-head"><strong id="briefingImageViewerTitle">SIMBRIEF CHART</strong><div><span id="briefingImageZoomReadout">100%</span><button id="briefingImageZoomOut" type="button">−</button><button id="briefingImageZoomIn" type="button">+</button><button id="briefingImageZoomReset" type="button">RESET</button><a id="briefingImageViewerDownload" href="#" download>DOWNLOAD</a><button id="briefingImageViewerClose" type="button">CLOSE</button></div></div><div id="briefingImageViewerStage" class="briefing-image-viewer-stage"><img id="briefingImageViewerImg" alt="Expanded SimBrief chart"></div></div>`;
  document.querySelectorAll('[data-briefing-tab]').forEach(button=>button.addEventListener('click',()=>setBriefingSection(button.dataset.briefingTab)));
  $('briefingViewOfp')?.addEventListener('click',()=>setBriefingSection('ofp'));
  $('ofpThemeDark')?.addEventListener('click',()=>setBriefingOfpTheme('dark'));$('ofpThemeLight')?.addEventListener('click',()=>setBriefingOfpTheme('light'));
  $('ofpLiveToggle')?.addEventListener('click',()=>setBriefingOfpLiveOpen(!briefingOfpLiveOpen));
  setupBriefingImageViewer();
  setBriefingSection(briefingSection||'overview');refreshBriefingWeather(false);loadOperationalBriefing(false);
  // v0.25.71: closure-marker DEPLOY IN SIM control is shelved - the panel is
  // hidden above, so bindClosureDeploy() (and its API calls) are not wired.
  // bindClosureDeploy();
  // Auto-pin charts from SimBrief flight plan (handles loading airport data itself)
  if (plan && plan.ok) {
    cfAutoPinFromSimBrief(plan);
  }
}

function setBriefingOfpTheme(theme){
  briefingOfpTheme = theme === 'light' ? 'light' : 'dark';
  document.querySelectorAll('.ofp-theme-buttons button').forEach(button=>button.classList.toggle('active',button.id.toLowerCase().includes(briefingOfpTheme)));
  const frame=$('briefingOfpFrame');
  if(frame && !String(frame.src||'').includes('/api/simbrief/ofp-cache/')) frame.src=`/api/simbrief/ofp-view?theme=${encodeURIComponent(briefingOfpTheme)}&t=${Date.now()}`;
}

// ── Live OFP completion (v0.25.65) ───────────────────────────────────────
// Toggle chip in the OFP reader action row. While open, polls
// GET /api/briefing/ofp-live every 2 s and patches stable DOM cells by
// data-ofp-live attributes. The SimBrief iframe is never reloaded by this
// polling, and missing values are always rendered as "—", never zero.
function briefingOfpLiveActive(){
  return briefingOfpLiveOpen && activePage === 'briefing' && briefingSection === 'ofp' && !document.hidden;
}
function briefingOfpStateLabel(state){
  return {waiting:'WAITING',live:'LIVE',complete:'COMPLETE',stale:'STALE',mismatch:'PLAN MISMATCH','no-plan':'NO PLAN'}[state] || String(state||'—').toUpperCase();
}
function briefingOfpCellClass(state){
  return {waiting:'state-standby',live:'state-live',complete:'state-complete',stale:'state-stale',mismatch:'state-fault','no-plan':'state-fault'}[state] || 'state-standby';
}
function briefingOfpNum(value, digits=0){
  if(value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if(!Number.isFinite(n)) return '—';
  return digits>0 ? n.toFixed(digits) : Math.round(n).toLocaleString();
}
function briefingOfpTime(iso){
  if(!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : `${String(d.getUTCHours()).padStart(2,'0')}${String(d.getUTCMinutes()).padStart(2,'0')}Z`;
}
function briefingOfpDelta(seconds){
  if(seconds === null || seconds === undefined || seconds === '') return '—';
  const s = Number(seconds);
  if(!Number.isFinite(s)) return '—';
  if(Math.abs(s) <= 0) return 'ON TIME';
  // v0.25.72 (#13): whole-minute deltas match the minute-precision times
  // (OUT 1735Z -> 1754Z shows +19, never +1909).
  const minutes = Math.round(Math.abs(s)/60);
  const sign = s > 0 ? '+' : '-';
  if(minutes <= 0) return 'ON TIME';
  const h = Math.floor(minutes/60), m = minutes%60;
  return h ? `${sign}${h}${String(m).padStart(2,'0')}` : `${sign}${m}`;
}
function briefingOfpDuration(seconds){
  if(seconds === null || seconds === undefined || seconds === '') return '—';
  const s = Number(seconds);
  if(!Number.isFinite(s) || s < 0) return '—';
  const h = Math.floor(s/3600), m = Math.floor((s%3600)/60);
  return `${String(h).padStart(2,'0')}${String(m).padStart(2,'0')}`;
}
function briefingOfpUnit(unit){
  const u = String(unit || '').toUpperCase();
  return u === 'KGS' ? 'KG' : (u === 'LBS' ? 'LB' : u || '');
}
function briefingOfpWeight(value, unit, digits=0){
  if(value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if(!Number.isFinite(n)) return '—';
  const base = digits>0 ? n.toFixed(digits) : Math.round(n).toLocaleString();
  return unit ? `${base} ${unit}` : base;
}
function briefingOfpLiveSkeleton(data){
  const unit = briefingOfpUnit(data?.units?.display);
  // Columns in the fourth argument are editable: clicking the ACTUAL cell
  // opens an inline input that writes a manual override (source=manual).
  const row = (label,key,cols,ovrCols=[]) => `<tr><th scope="row">${label}</th>${cols.map(c=>{const attrs=ovrCols.includes(c)?' data-ofp-override="'+key+'" class="ofp-ovr" title="Click to enter a manual value"':'';return `<td data-ofp-live="${key}:${c}"${attrs}>—</td>`;}).join('')}</tr>`;
  return `<div class="ofp-live-status-strip"><b id="ofpLiveState" class="ofp-live-state state-standby">WAITING</b><span><i>PHASE</i><b id="ofpLivePhase">—</b></span><span><i>SOURCE</i><b id="ofpLiveSource">—</b></span><span><i>OPERATION</i><b id="ofpLiveOp">—</b></span><span><i>UPDATED</i><b id="ofpLiveUpdated">—</b></span><span class="ofp-live-manual" id="ofpLiveManualChip" hidden><i>MANUAL</i><b id="ofpLiveManualCount">0</b></span><span class="ofp-live-hint">click ACTUAL cells to enter manual values</span><span class="ofp-live-actions"><button type="button" class="control-button" id="ofpLiveClearOverrides" hidden>CLEAR OVERRIDES</button><button type="button" class="control-button" data-ofp-copy="actuals">COPY ACTUALS</button><button type="button" class="control-button" data-ofp-copy="full">COPY FULL COMPARISON</button><button type="button" class="control-button" id="ofpLivePrint" data-ofp-print title="Print the live comparison to the configured Thermal/POS printer">PRINT</button></span></div>
  <div class="ofp-live-tables">
  <table class="ofp-live-table"><caption>TIMES</caption><thead><tr><th scope="col">EVENT</th><th scope="col">SCHEDULED</th><th scope="col">ACTUAL</th><th scope="col">DELTA</th><th scope="col">NOTE</th></tr></thead><tbody>
  ${row('OUT','times:out',['sched','actual','delta','est'],['actual'])}${row('OFF','times:off',['sched','actual','delta','est'],['actual'])}${row('ON','times:on',['sched','actual','delta','est'],['actual'])}${row('IN','times:in',['sched','actual','delta','est'],['actual'])}${row('BLOCK','times:block',['sched','actual','delta','est'])}
  </tbody></table>
  <table class="ofp-live-table"><caption>WEIGHTS ${escapeHtml(unit||'KG')}</caption><thead><tr><th scope="col">ITEM</th><th scope="col">PLANNED</th><th scope="col">MAX</th><th scope="col">ACTUAL</th><th scope="col">DELTA</th></tr></thead><tbody>
  ${row('PAX','weights:pax',['planned','max','actual','delta'],['actual'])}${row('BAG/CARGO','weights:bags',['planned','max','actual','delta'])}${row('COMMERCIAL FREIGHT','weights:freight',['planned','max','actual','delta'])}${row('PAYLOAD','weights:payload',['planned','max','actual','delta'])}${row('ZFW','weights:zfw',['planned','max','actual','delta'],['actual'])}${row('TOW','weights:tow',['planned','max','actual','delta'],['actual'])}${row('LDW','weights:ldw',['planned','max','actual','delta'],['actual'])}
  </tbody></table>
  <table class="ofp-live-table"><caption>FUEL ${escapeHtml(unit||'KG')}</caption><thead><tr><th scope="col">ITEM</th><th scope="col">PLANNED</th><th scope="col">ACTUAL</th><th scope="col">DELTA</th></tr></thead><tbody>
  ${row('RAMP / OUT','fuel:ramp',['planned','actual','delta'],['actual'])}${row('TAKEOFF / OFF','fuel:takeoff',['planned','actual','delta'],['actual'])}${row('TRIP','fuel:trip',['planned','actual','delta'])}${row('LANDING / ON','fuel:landing',['planned','actual','delta'],['actual'])}${row('BLOCK IN','fuel:blockin',['planned','actual','delta'],['actual'])}${row('EXTRA / SURPLUS','fuel:extra',['planned','actual','delta'])}
  </tbody></table>
  </div>`;
}
function briefingOfpSetCell(panel, key, text, opts={}){
  const cell = panel.querySelector(`[data-ofp-live="${key}"]`);
  if(!cell) return;
  if(cell.classList.contains('editing')) return; // never clobber an open editor
  cell.textContent = text;
  if(opts.manual){
    cell.classList.add('manual');
    cell.dataset.manualValue = String(opts.manualValue ?? '');
    cell.title = 'Manual override — click to edit';
  }else if(cell.dataset.ofpOverride){
    cell.classList.remove('manual');
    delete cell.dataset.manualValue;
    cell.title = 'Click to enter a manual value';
  }else{
    cell.classList.remove('manual');
    delete cell.dataset.manualValue;
    cell.title = '';
  }
}
function patchBriefingOfpLive(data){
  const panel = $('briefingOfpLivePanel');
  if(!panel) return;
  const stateEl = $('ofpLiveState');
  if(stateEl){ stateEl.textContent = briefingOfpStateLabel(data.state); stateEl.className = 'ofp-live-state ' + briefingOfpCellClass(data.state); }
  const live = data.live || {};
  const unit = briefingOfpUnit(data?.units?.display);
  const manual = data.manual_overrides || {};
  const manualCount = Object.keys(manual).length;
  const manualChip = $('ofpLiveManualChip');
  if(manualChip) manualChip.hidden = manualCount === 0;
  const manualCountEl = $('ofpLiveManualCount');
  if(manualCountEl) manualCountEl.textContent = String(manualCount);
  const clearBtn = $('ofpLiveClearOverrides');
  if(clearBtn) clearBtn.hidden = manualCount === 0;
  const set = (key,text,opts)=>briefingOfpSetCell(panel,key,text,opts);
  if($('ofpLivePhase')) $('ofpLivePhase').textContent = uiWords(live.phase) || '—';
  if($('ofpLiveSource')) $('ofpLiveSource').textContent = String(live.telemetry_source || '—').toUpperCase();
  if($('ofpLiveOp')) $('ofpLiveOp').textContent = String((data.operation||{}).resolved || '—').toUpperCase();
  if($('ofpLiveUpdated')) $('ofpLiveUpdated').textContent = briefingOfpTime(data.updated_utc);
  const times = data.times || {};
  for(const k of ['out','off','on','in']){
    const row = times[k] || {};
    set(`times:${k}:sched`, briefingOfpTime(row.scheduled_utc));
    set(`times:${k}:actual`, briefingOfpTime(row.actual_utc), row.source === 'manual' ? {manual:true, manualValue:manual[`times:${k}`]} : undefined);
    set(`times:${k}:delta`, briefingOfpDelta(row.delta_seconds));
    set(`times:${k}:est`, row.estimated ? 'ESTIMATED' : '');
  }
  const block = times.block || {};
  set('times:block:sched', briefingOfpDuration(block.planned_seconds));
  set('times:block:actual', briefingOfpDuration(block.actual_seconds));
  set('times:block:delta', briefingOfpDelta(block.delta_seconds));
  set('times:block:est', '');
  const weights = data.weights || {};
  const disp = (item,key,digits=0)=>briefingOfpWeight(item?.[key+'_display'] ?? item?.[key], unit, digits);
  const wrow = (key,item,isCount=false,ovrKey=null)=>{ if(!item) return; set(`weights:${key}:planned`, isCount?briefingOfpWeight(item.planned, '', 0):disp(item,'planned')); set(`weights:${key}:max`, disp(item,'max')); set(`weights:${key}:actual`, disp(item,'actual'), (ovrKey && manual[ovrKey] !== undefined) ? {manual:true, manualValue:manual[ovrKey]} : undefined); set(`weights:${key}:delta`, briefingOfpWeight(item.delta_display ?? item.delta, unit, 1)); };
  wrow('pax', weights.passengers, true, 'weights:pax'); wrow('bags', weights.bags_cargo); wrow('freight', weights.commercial_freight);
  wrow('payload', weights.payload); wrow('zfw', weights.zfw, false, 'weights:zfw'); wrow('tow', weights.tow, false, 'weights:tow'); wrow('ldw', weights.ldw, false, 'weights:ldw');
  const fuel = data.fuel || {};
  const frow = (key,item,ovrKey=null)=>{ if(!item) return; set(`fuel:${key}:planned`, disp(item,'planned')); set(`fuel:${key}:actual`, disp(item,'actual'), (ovrKey && manual[ovrKey] !== undefined) ? {manual:true, manualValue:manual[ovrKey]} : undefined); set(`fuel:${key}:delta`, briefingOfpWeight(item.delta_display ?? item.delta, unit, 1)); };
  frow('ramp', fuel.ramp_out, 'fuel:ramp'); frow('takeoff', fuel.takeoff_off, 'fuel:takeoff'); frow('trip', fuel.trip);
  frow('landing', fuel.landing_on, 'fuel:landing'); frow('blockin', fuel.block_in, 'fuel:blockin'); frow('extra', fuel.extra_surplus);
  bindBriefingOfpLiveEditors(panel);
}
function renderBriefingOfpLive(data){
  const panel = $('briefingOfpLivePanel');
  if(!panel) return;
  if(!data?.ok){ if(!panel.querySelector('.ofp-live-tables')) panel.innerHTML = '<div class="network-empty">Live OFP data is unavailable.</div>'; return; }
  if(!panel.querySelector('.ofp-live-tables')){
    briefingOfpLiveRevision = '';
    panel.innerHTML = briefingOfpLiveSkeleton(data);
  }
  if(data.revision && data.revision !== briefingOfpLiveRevision){
    briefingOfpLiveRevision = data.revision;
    patchBriefingOfpLive(data);
  }
}
// Manual override editing (v0.25.65): click an ACTUAL cell to type a value.
// Enter commits, Escape cancels, blur commits.  Empty input removes the
// override.  Overrides are stored server-side (source=manual) and never touch
// phase detection or the recorder.
function bindBriefingOfpLiveEditors(panel){
  if(!panel || panel.dataset.ofpEditorsBound) return;
  panel.dataset.ofpEditorsBound = '1';
  panel.addEventListener('click', event=>{
    const cell = event.target.closest('[data-ofp-override]');
    if(!cell || cell.classList.contains('editing')) return;
    briefingOfpStartEdit(cell);
  });
  const clearBtn = $('ofpLiveClearOverrides');
  if(clearBtn && !clearBtn.dataset.ofpClearBound){
    clearBtn.dataset.ofpClearBound = '1';
    clearBtn.addEventListener('click', async ()=>{
      try{
        const response = await fetch('/api/briefing/ofp-live/overrides', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({clear_all:true}), cache:'no-store'});
        const data = await safeJsonResponse(response);
        if(!data?.ok) throw new Error(data.reason || 'Clear failed');
        showToast('LIVE OFP','OVERRIDES CLEARED','Manual entries removed.','info');
        refreshBriefingOfpLive(true);
      }catch(error){
        showToast('LIVE OFP','CLEAR FAILED',friendlyError(error.message),'warn');
      }
    });
  }
  const copyButtons = panel.querySelectorAll('[data-ofp-copy]');
  copyButtons.forEach(btn=>{
    if(btn.dataset.ofpCopyBound) return;
    btn.dataset.ofpCopyBound = '1';
    btn.addEventListener('click',()=>briefingOfpCopy(btn.dataset.ofpCopy));
  });
  const printButton = panel.querySelector('[data-ofp-print]');
  if(printButton && !printButton.dataset.ofpPrintBound){
    printButton.dataset.ofpPrintBound = '1';
    printButton.addEventListener('click',briefingOfpPrint);
  }
}
function briefingOfpStartEdit(cell){
  if(cell.querySelector('input')) return;
  const key = cell.dataset.ofpOverride;
  const previous = cell.textContent;
  const current = cell.dataset.manualValue !== undefined ? cell.dataset.manualValue : '';
  cell.classList.add('editing');
  cell.innerHTML = `<input class="ofp-ovr-input" value="${escapeHtml(current)}" inputmode="${key && key.startsWith('times:') ? 'numeric' : 'decimal'}" aria-label="Manual ${escapeHtml(key || '')}" autocomplete="off" spellcheck="false">`;
  const input = cell.querySelector('input');
  if(!input) return;
  input.focus();
  input.select();
  let done = false;
  const finish = (commit)=>{
    if(done) return;
    done = true;
    cell.classList.remove('editing');
    if(commit){
      briefingOfpCommitOverride(cell, key, input.value.trim());
    }else{
      cell.textContent = previous;
    }
  };
  input.addEventListener('keydown', event=>{
    if(event.key === 'Enter'){ event.preventDefault(); finish(true); }
    else if(event.key === 'Escape'){ event.preventDefault(); finish(false); }
  });
  input.addEventListener('blur', ()=>finish(true));
}
async function briefingOfpCommitOverride(cell, key, value){
  const previous = cell.dataset.manualValue !== undefined ? cell.dataset.manualValue : '';
  try{
    const body = value === '' ? {clear_key:key} : {overrides:{[key]:value}};
    const response = await fetch('/api/briefing/ofp-live/overrides', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body), cache:'no-store'});
    const data = await safeJsonResponse(response);
    if(!data?.ok) throw new Error(data.reason || 'Override rejected');
    if(data.errors && data.errors[key]){
      showToast('LIVE OFP','OVERRIDE REJECTED',data.errors[key],'warn');
      cell.textContent = previous || '—';
      return;
    }
    refreshBriefingOfpLive(true);
  }catch(error){
    showToast('LIVE OFP','OVERRIDE FAILED',friendlyError(error.message),'warn');
    cell.textContent = previous || '—';
  }
}
async function refreshBriefingOfpLive(force=false){
  if(briefingOfpLiveBusy && !force) return;
  briefingOfpLiveBusy = true;
  const controller = new AbortController();
  briefingOfpLiveAbortController = controller;
  try{
    const response = await fetch('/api/briefing/ofp-live', {cache:'no-store', signal: controller.signal});
    const data = await safeJsonResponse(response);
    briefingOfpLiveData = data;
    if(!briefingOfpLiveOpen) return;
    renderBriefingOfpLive(data);
  }catch(error){
    if(error && error.name === 'AbortError') return;
    const panel = $('briefingOfpLivePanel');
    if(panel && !panel.querySelector('.ofp-live-tables')) panel.innerHTML = `<div class="network-empty">LIVE OFP UNAVAILABLE — ${escapeHtml(friendlyError(error.message))}</div>`;
  }finally{
    briefingOfpLiveBusy = false;
    if(briefingOfpLiveAbortController === controller) briefingOfpLiveAbortController = null;
  }
}
function startBriefingOfpLive(){
  if(!briefingOfpLiveOpen || briefingSection !== 'ofp' || activePage !== 'briefing' || document.hidden) return;
  if(briefingOfpLiveTimer) return;
  refreshBriefingOfpLive(true);
  briefingOfpLiveTimer = setInterval(()=>refreshBriefingOfpLive(false), 2000);
}
function stopBriefingOfpLive(){
  if(briefingOfpLiveTimer){ clearInterval(briefingOfpLiveTimer); briefingOfpLiveTimer = null; }
  if(briefingOfpLiveAbortController){ try{ briefingOfpLiveAbortController.abort(); }catch(_){} briefingOfpLiveAbortController = null; }
  briefingOfpLiveBusy = false;
}
function setBriefingOfpLiveOpen(open){
  briefingOfpLiveOpen = Boolean(open);
  const panel = $('briefingOfpLivePanel');
  if(panel) panel.hidden = !briefingOfpLiveOpen;
  const chip = $('ofpLiveToggle');
  if(chip){ chip.classList.toggle('active', briefingOfpLiveOpen); chip.setAttribute('aria-expanded', briefingOfpLiveOpen ? 'true' : 'false'); }
  if(briefingOfpLiveOpen){
    briefingOfpLiveRevision = '';
    // v0.25.72 (#18): render the comparison tables immediately on open so the
    // stale "standing by — click ◈ LIVE OFP" placeholder never stands in for
    // live data. Planned values from SimBrief fill in on the first (instant)
    // poll; actuals stay "—" until a recording starts.
    if(panel && !panel.querySelector('.ofp-live-tables')){
      panel.innerHTML = briefingOfpLiveSkeleton({state:'waiting', units:{display:(unitPrefs().weight||'kg').toUpperCase()}, live:{phase:'STANDING BY'}, operation:{resolved:'AUTO'}});
    }
    refreshBriefingOfpLive(true);
    startBriefingOfpLive();
  }else{
    stopBriefingOfpLive();
  }
}
function briefingOfpCopy(scope){
  const data = briefingOfpLiveData;
  if(!data?.ok){ showToast('LIVE OFP','COPY','No live OFP data available yet.','warn'); return; }
  const unit = briefingOfpUnit(data?.units?.display) || 'KG';
  const lines = [];
  const times = data.times || {};
  const pad = (s,n)=>String(s||'').padEnd(n);
  if(scope === 'full'){
    lines.push('LIVE OFP COMPLETION — ' + String((data.operation||{}).resolved||'AUTO').toUpperCase());
    lines.push('STATUS ' + briefingOfpStateLabel(data.state) + ' · PHASE ' + String((data.live||{}).phase||'—').toUpperCase() + ' · SOURCE ' + String((data.live||{}).telemetry_source||'—').toUpperCase() + ' · UNITS ' + unit);
    lines.push('');
    lines.push('TIMES         SCHED   ACTUAL  DELTA');
    for(const [label,k] of [['OUT','out'],['OFF','off'],['ON','on'],['IN','in']]){
      const row = times[k] || {};
      lines.push(pad(label,13) + ' ' + briefingOfpTime(row.scheduled_utc) + '   ' + briefingOfpTime(row.actual_utc) + '   ' + briefingOfpDelta(row.delta_seconds));
    }
    const block = times.block || {};
    lines.push(pad('BLOCK',13) + ' ' + briefingOfpDuration(block.planned_seconds) + '   ' + briefingOfpDuration(block.actual_seconds) + '   ' + briefingOfpDelta(block.delta_seconds));
    lines.push('');
    lines.push('WEIGHTS (' + unit + ')  PLANNED    MAX      ACTUAL    DELTA');
    for(const [label,k] of [['PAX','passengers'],['BAG/CARGO','bags_cargo'],['COMMERCIAL FREIGHT','commercial_freight'],['PAYLOAD','payload'],['ZFW','zfw'],['TOW','tow'],['LDW','ldw']]){
      const w = (data.weights||{})[k] || {};
      lines.push(pad(label,19) + ' ' + pad(briefingOfpWeight(w.planned,unit),9) + ' ' + pad(briefingOfpWeight(w.max,unit),8) + ' ' + pad(briefingOfpWeight(w.actual,unit),8) + ' ' + briefingOfpWeight(w.delta,unit,1));
    }
    lines.push('');
    lines.push('FUEL (' + unit + ')     PLANNED    ACTUAL    DELTA');
    for(const [label,k] of [['RAMP/OUT','ramp_out'],['TAKEOFF/OFF','takeoff_off'],['TRIP','trip'],['LANDING/ON','landing_on'],['BLOCK IN','block_in'],['EXTRA/SURPLUS','extra_surplus']]){
      const f = (data.fuel||{})[k] || {};
      lines.push(pad(label,19) + ' ' + pad(briefingOfpWeight(f.planned,unit),9) + ' ' + pad(briefingOfpWeight(f.actual,unit),8) + ' ' + briefingOfpWeight(f.delta,unit,1));
    }
  }else{
    lines.push('ACTUAL TIMES (' + unit + ')');
    for(const [label,k] of [['OUT','out'],['OFF','off'],['ON','on'],['IN','in']]){
      const row = times[k] || {};
      lines.push(label + ' ' + briefingOfpTime(row.actual_utc));
    }
    const block = times.block || {};
    lines.push('BLOCK ' + briefingOfpDuration(block.actual_seconds));
    lines.push('');
    lines.push('ACTUAL WEIGHTS (' + unit + ')');
    for(const [label,k] of [['ZFW','zfw'],['TOW','tow'],['LDW','ldw']]){
      const w = (data.weights||{})[k] || {};
      lines.push(label + ' ' + briefingOfpWeight(w.actual, unit));
    }
    lines.push('');
    lines.push('ACTUAL FUEL (' + unit + ')');
    const fuel = data.fuel || {};
    for(const [label,k] of [['OUT','ramp_out'],['OFF','takeoff_off'],['ON','landing_on'],['IN','block_in'],['TRIP','trip']]){
      const f = fuel[k] || {};
      lines.push(label + ' ' + briefingOfpWeight(f.actual, unit));
    }
  }
  const text = lines.join('\n');
  try{
    navigator.clipboard.writeText(text).then(()=>showToast('LIVE OFP','COPIED', scope==='full' ? 'Full comparison copied.' : 'Actuals copied.','info')).catch(()=>showToast('LIVE OFP','COPY FAILED','Clipboard unavailable.','warn'));
  }catch(_){ showToast('LIVE OFP','COPY FAILED','Clipboard unavailable.','warn'); }
}
async function briefingOfpPrint(){
  const btn = $('ofpLivePrint');
  const original = btn ? btn.textContent : 'PRINT';
  if(btn) btn.textContent = 'PRINTING...';
  try{
    const response = await fetchWithTimeout('/api/briefing/ofp-live/print',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'},10000);
    const data = await safeJsonResponse(response);
    if(!data?.ok) throw new Error(data.error || 'Print failed');
    showToast('LIVE OFP','PRINTED',`Receipt sent to ${String(data.printer||'').toUpperCase()}.`,'info');
  }catch(error){
    showToast('LIVE OFP','PRINT FAILED',friendlyError(error.message),'warn');
  }finally{
    if(btn) btn.textContent = original;
  }
}
document.addEventListener('visibilitychange', ()=>{
  if(document.hidden){ stopBriefingOfpLive(); }
  else if(briefingOfpLiveOpen && briefingSection === 'ofp' && activePage === 'briefing'){ startBriefingOfpLive(); }
});

// ChartFox OAuth popup listener (callback page postMessages back when ready).
let chartfoxOAuthPollTimer = null;
if(typeof window !== 'undefined'){
  window.addEventListener('message', event=>{
    if(!event || !event.data || event.data.type !== 'chartfox_oauth_complete') return;
    if(chartfoxOAuthPollTimer){clearInterval(chartfoxOAuthPollTimer);chartfoxOAuthPollTimer=null;}
    if(event.data.ok){
      showToast('OPS ROOM','CHARTFOX CONNECTED','ChartFox authorization was completed successfully.','info');
    }else{
      showToast('OPS ROOM','CHARTFOX CONNECT FAILED',friendlyError(event.data.detail||'Authorization failed'),'critical');
    }
    refreshChartFoxOAuthStatus().then(()=>loadCharts()).catch(()=>loadCharts());
  });
}

async function refreshChartFoxOAuthStatus(){
  const box=$('hostChartFoxOAuthStatus');
  if(box){
    try{
      const resp=await fetch('/api/charts/chartfox/status',{cache:'no-store'});
      const data=await resp.json();
      if(data.has_token){
        const remaining = data.expires_in_remaining;
        const tail = remaining != null ? ` Token refresh in ${Math.max(0,Math.round(remaining/60))} min.` : '';
        box.innerHTML=`<b>CHARTFOX CONNECTED</b><span>OAuth token ready. Charts appear in Briefing > Charts.${escapeHtml(tail)}</span>`;
      }else{
        box.innerHTML='<b>CHARTFOX NOT CONNECTED</b><span>Use Briefing > Charts to authorize with ChartFox.</span>';
      }
    }catch(error){
      box.innerHTML=`<b>CHARTFOX STATUS CHECK FAILED</b><span>${escapeHtml(friendlyError(error.message))}</span>`;
    }
  }
  return chartfox_oauth_status_direct();
}

async function chartfox_oauth_status_direct(){
  try{const data=await safeJsonResponse(await fetch('/api/charts/chartfox/status',{cache:'no-store'}));return data;}catch(_){return {has_token:false};}
}

async function chartfox_open_authorization_window(){
  const callback = `${window.location.origin}/api/charts/chartfox/callback`;
  try{
    const data=await safeJsonResponse(await fetch('/api/charts/chartfox/authorize',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({redirect_uri:callback}),cache:'no-store'}));
    if(!data.ok)throw new Error(data.error||'Failed to get ChartFox authorization URL');
    const popup = window.open(data.url, 'chartfox_oauth', 'width=700,height=820');
    if(chartfoxOAuthPollTimer) clearInterval(chartfoxOAuthPollTimer);
    chartfoxOAuthPollTimer = setInterval(async()=>{
      const status = await chartfox_oauth_status_direct();
      if(status && status.has_token){
        clearInterval(chartfoxOAuthPollTimer);
        chartfoxOAuthPollTimer = null;
        // v0.25.60: clear stale in-flight dedup entries so loadCharts()
        // makes fresh API calls instead of returning cached failures.
        cfState._fetchingAirports = {};
        // v0.25.60: do NOT auto-close the OAuth popup. The callback page
        // now shows a DONE button the user must click to close it. The
        // chart list still refreshes as soon as the token is available.
        // fire-and-forget toast: must never block loadCharts().
        try{showToast('OPS ROOM','CHARTFOX CONNECTED','ChartFox authorization completed.','info');}catch(_){}
        await loadCharts();
      }
    }, 1200);
    return true;
  }catch(error){
    showToast('OPS ROOM','CONNECT FAILED',friendlyError(error.message),'critical');
    return false;
  }
}

async function chartfox_disconnect(){
  try{
    await safeJsonResponse(await fetch('/api/charts/chartfox/disconnect',{method:'POST',cache:'no-store'}));
    await loadCharts();
  }catch(error){
    showToast('OPS ROOM','DISCONNECT FAILED',friendlyError(error.message),'critical');
  }
}

let chartfoxSearchTimer = null;
let chartfoxSearchAbort = null;
let chartfoxSearchResults = [];
let chartfoxSearchActive = 0;
// v0.25.9: Friendly empty-state helper. Renders the token-based ops-empty-state block.
// Used anywhere a panel could otherwise silently disappear (search with no results,
// ChartFox returning 0 charts, briefing without an OFP, etc.).
function renderOpsEmptyState(container, heading, body, hint){
  if(!container)return;
  container.innerHTML='';
  container.hidden=false;
  const root=document.createElement('div');
  root.className='ops-empty-state';
  if(heading){const h=document.createElement('div');h.className='ops-empty-state-heading';h.textContent=heading;root.appendChild(h);}
  if(body){const p=document.createElement('div');p.className='ops-empty-state-body';p.textContent=body;root.appendChild(p);}
  if(hint){const s=document.createElement('div');s.className='ops-empty-state-hint';s.textContent=hint;root.appendChild(s);}
  container.appendChild(root);
}
function chartfox_render_search_results(){
  const root = $('briefingChartFoxSearchResults');
  if(!root) return;
  if(!chartfoxSearchResults.length){
    const q=($('briefingChartFoxSearch')?.value||'').trim();
    renderOpsEmptyState(
      root,
      'No matching airports',
      q ? `No airports matched "${q}". Try a 4-letter ICAO like KJFK or a city name like Gatwick.` : 'Type at least 2 characters to search ICAO or city name.',
      'CHARTFOX SEARCH'
    );
    return;
  }
  root.innerHTML = chartfoxSearchResults.map(item => {
    const icao = escapeHtml(item.icao_code || item.ident || '');
    const name = escapeHtml(item.name || '');
    const country = escapeHtml(item.iso_a2_country || '');
    const type = escapeHtml(String(item.type || ''));
    return `<button type="button" class="chartfox-search-row" data-cf-search-icao="${icao}"><b>${icao}</b><span>${name}</span><small>${country}${type?` · ${type}`:''}</small></button>`;
  }).join('');
  root.hidden = false;
  root.querySelectorAll('[data-cf-search-icao]').forEach(button=>{
    button.addEventListener('click', ()=>{
      const icao = button.dataset.cfSearchIcao;
      chartfox_load_airport_charts(icao);
      $('briefingChartFoxSearch')?.blur();
      root.hidden = true;
    });
  });
}
async function chartfox_run_search(){
  const input = $('briefingChartFoxSearch');
  const root = $('briefingChartFoxSearchResults');
  if(!input || !root) return;
  const q = (input.value||'').trim();
  if(q.length < 2){chartfoxSearchResults=[];chartfox_render_search_results();return;}
  if(chartfoxSearchAbort && chartfoxSearchAbort.abort) chartfoxSearchAbort.abort();
  if(typeof AbortController !== 'undefined'){
    chartfoxSearchAbort = new AbortController();
  } else {
    chartfoxSearchAbort = {abort:()=>{}};
  }
  const ticket = ++chartfoxSearchActive;
  try{
    const resp = await fetch(`/api/charts/chartfox/search?q=${encodeURIComponent(q)}&page=1&page_size=10`, {cache:'no-store', signal: chartfoxSearchAbort.signal});
    const data = await safeJsonResponse(resp);
    if(ticket !== chartfoxSearchActive) return;
    chartfoxSearchResults = (data.items || []).filter(item => (item.icao_code||item.ident||'').length === 4).slice(0,10);
    chartfox_render_search_results();
  }catch(error){
    if(error && error.name === 'AbortError') return;
    if(ticket !== chartfoxSearchActive) return;
    chartfoxSearchResults = [];
    chartfox_render_search_results();
  }
}

let chartfoxAirportPanels = {}; // icao -> container
function chartfox_register_airport_panel(icao, container){
  chartfoxAirportPanels[icao] = container;
}
function chartfox_active_airport_icao(){
  const active = cfPanel?.querySelector?.('.briefing-chartfox-tab.active');
  return active ? active.dataset.cfAirport : '';
}
function chartfox_ensure_panel_for(icao){
  if(chartfoxAirportPanels[icao]) return chartfoxAirportPanels[icao];
  let container = cfPanel.querySelector(`[data-cf-airport-panel="${CSS.escape(icao)}"]`);
  if(!container){
    // Append a new tab + panel if a searched airport is requested.
    const tabs = cfPanel.querySelector('.briefing-chartfox-tabs');
    if(tabs){
      tabs.insertAdjacentHTML('beforeend', `<button type="button" class="briefing-chartfox-tab" data-cf-airport="${escapeHtml(icao)}">${escapeHtml(icao)}<small>search</small></button>`);
      cfPanel.querySelector('.briefing-chartfox-panels')?.insertAdjacentHTML('beforeend', `<div class="briefing-chartfox-panel hidden" data-cf-airport-panel="${escapeHtml(icao)}"><b>LOADING CHARTFOX CHARTS...</b></div>`);
      container = cfPanel.querySelector(`[data-cf-airport-panel="${CSS.escape(icao)}"]`);
      tabs.querySelectorAll('.briefing-chartfox-tab').forEach(tab=>{
        tab.addEventListener('click', ()=>{
          cfPanel.querySelectorAll('.briefing-chartfox-tab').forEach(t=>t.classList.remove('active'));
          tab.classList.add('active');
          cfPanel.querySelectorAll('.briefing-chartfox-panel').forEach(p=>p.classList.add('hidden'));
          const target = cfPanel.querySelector(`[data-cf-airport-panel="${CSS.escape(tab.dataset.cfAirport)}"]`);
          if(target){target.classList.remove('hidden'); if(!target.dataset.cfLoaded) loadChartFoxGrouped(target, tab.dataset.cfAirport);}
        });
      });
    }
  }
  if(container){chartfox_register_airport_panel(icao, container);}
  return container;
}
async function chartfox_load_airport_charts(icao){
  const norm = String(icao||'').toUpperCase().replace(/[^A-Z0-9]/g,'').slice(0,4);
  if(norm.length !== 4) return;
  const container = chartfox_ensure_panel_for(norm);
  if(!container) return;
  cfPanel.querySelectorAll('.briefing-chartfox-tab').forEach(t=>t.classList.remove('active'));
  cfPanel.querySelector(`.briefing-chartfox-tab[data-cf-airport="${CSS.escape(norm)}"]`)?.classList.add('active');
  cfPanel.querySelectorAll('.briefing-chartfox-panel').forEach(p=>p.classList.add('hidden'));
  container.classList.remove('hidden');
  loadChartFoxGrouped(container, norm);
}

async function loadCharts(){
  cfPanel=$('briefingChartFoxPanel');
  if(!cfPanel)return;
  chartfoxAirportPanels={};
  // v0.25.60: clear stale in-flight dedup entries before any fresh API call.
  // Stale failed promises from a previous (pre-auth) run otherwise block
  // cfInitAirportCharts from making a new API call after reconnect.
  cfState._fetchingAirports = {};
  cfPanel.innerHTML=`<div class="cf-shell">
    <div class="cf-topbar">
      <div class="cf-airport-chip" id="cfAirportChip"><span>--</span><small>SELECT AN AIRPORT</small></div>
      <div class="cf-quick-picks" id="cfQuickPicks" hidden></div>
      <div id="cfPinnedStrip" class="briefing-pinned-strip" hidden><div class="cf-pinned-scroll" id="cfPinnedScroll"></div></div>
      <div class="cf-search-row">
        <input id="briefingChartFoxSearch" class="cf-search-input" type="search" autocomplete="off" placeholder="Search airport: e.g. EGLL, Gatwick, Munich..." aria-controls="briefingChartFoxSearchResults" aria-expanded="false" aria-autocomplete="list" />
        <button id="briefingChartFoxReload" class="cf-reload-btn" type="button" title="Reload ChartFox charts">↻</button>
      </div>
      <div id="briefingChartFoxSearchResults" class="cf-search-results" role="listbox" aria-label="ChartFox airport search" tabindex="-1" hidden></div>
      <div class="cf-connect-bar">
        <span id="briefingChartFoxStatusLine" class="cf-status-line">Loading ChartFox status...</span>
        <button id="briefingChartFoxConnectBtn" class="cf-connect-btn" type="button">CONNECT TO CHARTFOX</button>
        <button id="briefingChartFoxDisconnectBtn" class="cf-disconnect-btn" type="button" hidden>DISCONNECT</button>
      </div>
    </div>
    <div class="cf-tabs" id="cfTabs">
      <button type="button" class="cf-tab" data-cf-tab="STAR">STAR</button>
      <button type="button" class="cf-tab" data-cf-tab="APP">APP</button>
      <button type="button" class="cf-tab" data-cf-tab="TAXI">TAXI</button>
      <button type="button" class="cf-tab" data-cf-tab="SID">SID</button>
      <button type="button" class="cf-tab" data-cf-tab="REF">REF</button>
      <button type="button" class="cf-tab" data-cf-tab="GA">GA</button>
      <span class="cf-tabs-spacer"></span>
      <span class="cf-tabs-hint">CLICK TO TOGGLE CATEGORY</span>
    </div>
    <div class="cf-body">
      <div class="cf-sidebar" id="cfSidebar"><div class="cf-empty">SELECT AN AIRPORT OR USE SEARCH ABOVE</div></div>
      <div class="cf-preview" id="cfPreview">
        <div class="cf-empty">SELECT A CHART TO PREVIEW &middot; OWN POSITION WILL APPEAR HERE WHEN CHART HAS GEO REFERENCE</div>
        <div class="cf-preview-overlay" id="cfPreviewOverlay" hidden><svg viewBox="0 0 40 40" xmlns="http://www.w3.org/2000/svg"><polygon points="20,4 30,32 20,26 10,32" fill="#aaa98d" stroke="#1a2016" stroke-width="2.4" stroke-linejoin="round"/></svg></div>
      </div>
    </div>
  </div>`;
  // v0.25.60: search wiring is the sole responsibility of cfWireSearchBox() which properly
  // handles debounce, keyboard ArrowDown/ArrowUp/Escape/Enter navigation, click-outside
  // dismissal, and focus re-fetch. Duplicate listeners here cause double-firing per keystroke.
  // The loadCharts shell rebuild is async; cfInitAirportCharts wires cfWireSearchBox after it.
  $('briefingChartFoxReload')?.addEventListener('click', ()=>loadCharts());
  $('briefingChartFoxConnectBtn')?.addEventListener('click', ()=>chartfox_open_authorization_window());
  $('briefingChartFoxDisconnectBtn')?.addEventListener('click', async ()=>{if(await uiConfirm('Disconnect ChartFox? You will need to reconnect to use ChartFox charts.', 'DISCONNECT'))chartfox_disconnect();});
  document.addEventListener('click', event=>{
    const root = $('briefingChartFoxSearchResults');
    const input = $('briefingChartFoxSearch');
    if(!root || root.hidden) return;
    if(event.target === root || root.contains(event.target)) return;
    if(event.target === input) return;
    root.hidden = true;
  });

  let briefing = {};
  try{
    const r=await fetch('/api/charts/briefing',{cache:'no-store'});
    const data=await safeJsonResponse(r);
    briefing = data;
  }catch(_){}
  const flight = (briefing && briefing.flight) || {};
  const airports = (briefing && briefing.airports || []).filter(a=>a.icao).map(a=>a.icao);

  const status = await chartfox_oauth_status_direct();
  const statusLine = $('briefingChartFoxStatusLine');
  const disconnectBtn = $('briefingChartFoxDisconnectBtn');
  const connectBtn = $('briefingChartFoxConnectBtn');
  if(statusLine){
    if(status.has_token){
      const remaining = status.expires_in_remaining;
      const minutes = remaining != null ? Math.max(0, Math.round(remaining/60)) : null;
      statusLine.textContent = `ChartFox connected${minutes != null ? ` · token refresh in ${minutes} min` : ''}.`;
      if(disconnectBtn) disconnectBtn.hidden = false;
      if(connectBtn) connectBtn.textContent = 'REAUTHORIZE';
    } else {
      statusLine.textContent = 'ChartFox not connected. Click CONNECT TO CHARTFOX to authorize.';
      if(disconnectBtn) disconnectBtn.hidden = true;
      if(connectBtn) connectBtn.textContent = 'CONNECT TO CHARTFOX';
    }
  }

  // v0.25.9 fix: the older shell repaint (briefing-chartfox-tabs/panels) was throwing a TypeError
  // because those elements do not exist in the cf-shell HTML; the throw aborted loadCharts before
  // cfRenderQuickPicks() could run, leaving the user with no quick-picks and an empty sidebar.
  // The fix is to:
  //   - keep the newer cf-shell already mounted above (it has #cfQuickPicks, cf-search, cf-tabs)
  //   - log the OFP + ChartFox status so any session problem is traceable
  //   - render the quick-pick chips immediately
  //   - auto-load the first available flight airport so the user lands on a populated panel
  //     instead of the "SELECT AN AIRPORT" placeholder. Token status only gates the ChartFox
  //     chart fetch itself, NOT the airport search or the chip rendering.
  console.info('[OPS ROOM][chartfox-init]', {
    has_token: !!status.has_token,
    token_minutes: status.has_token && status.expires_in_remaining != null ? Math.max(0, Math.round(status.expires_in_remaining/60)) : null,
    flight_origin: flight.origin || null,
    flight_destination: flight.destination || null,
    flight_alternate: flight.alternate || null,
    briefing_airports: airports,
  });
  if(typeof cfRenderQuickPicks === 'function') cfRenderQuickPicks();
  // Auto-load the first airport with valid 4-letter ICAO so Charts lands populated.
  const flightIcaos = [flight.origin, flight.destination, flight.alternate].filter(Boolean);
  const autoIcao = flightIcaos.concat(airports).find(candidate => typeof candidate === 'string' && /^[A-Z]{4}$/.test(candidate.toUpperCase()));
  if(autoIcao){
    const norm = String(autoIcao).toUpperCase();
    console.info('[OPS ROOM][chartfox-auto-load]', {icao: norm, source: 'flightPlan'});
    if(typeof cfLoadAirport === 'function') cfLoadAirport(norm);
  }
}

async function loadChartFoxGrouped(container, icao){
  if(!container) return;
  cfInitAirportCharts(container, icao);
}

// v0.25.9: Drive the new cf-* sidebar / preview / pin / overlay UI.
function cfInitAirportCharts(container, icao){
  var cleanIcao = String(icao || '').trim().toUpperCase().slice(0, 4);
  // v0.25.60: in-flight dedup — if a grouped fetch is already in progress
  // for this airport, return the existing promise instead of starting a
  // duplicate.  This guards direct callers (loadChartFoxGrouped, search) as
  // well as cfLoadAirport.
  cfState._fetchingAirports = cfState._fetchingAirports || {};
  if (cfState._fetchingAirports[cleanIcao]) {
    console.warn('[OPS ROOM][chartfox-dedup-hit]', {icao: cleanIcao, returning: 'stale in-flight promise — this may be a failed promise from before auth'});
    return cfState._fetchingAirports[cleanIcao];
  }
  // v0.25.60 diagnostic: log pre-call state to diagnose SESSION EXPIRED false positives.
  console.info('[OPS ROOM][chartfox-pre-call]', {
    icao: cleanIcao,
    fetchingAirportsKeys: Object.keys(cfState._fetchingAirports),
    hasOAuthConnectedFlag: cfState.chartfox_oauth_connected,
    url: '/api/charts/chartfox/grouped/' + encodeURIComponent(cleanIcao),
  });
  // Clear both timers: cfState.previewTimer belongs to the new cf-* overlay, briefingChartOwnshipTimer
  // is the legacy briefing-page ownship poll that the OLD briefingChartViewer iframe path still uses.
  // Cleared together so airport switch can't leave the legacy poll hammering the backend in the background.
  if (cfState.previewTimer) { clearInterval(cfState.previewTimer); cfState.previewTimer = null; }
  if (briefingChartOwnshipTimer) { clearInterval(briefingChartOwnshipTimer); briefingChartOwnshipTimer = null; }
  cfState.pins = cfLoadPins();
  cfState.activeChartId = null;
  cfState.airport = cleanIcao;
  console.info('[OPS ROOM][chartfox-init-airport]', {icao: cfState.airport, has_token: cfState && cfState.chartfox_oauth_connected === true});
  cfWireTabs();
  cfRenderAirportChip(icao);
  container.dataset.cfAirport = icao;
  cfRenderQuickPicks();
  cfRenderPinnedStrip();
  cfWireSearchBox();
  // v0.25.60 diagnostic: perform a real OAuth status check. Runs synchronously
  // before the fetch so cfState.chartfox_oauth_connected is accurate for the API call.
  var _cfOauthCheckDone = chartfox_oauth_status_direct().then(function(st){
    console.info('[OPS ROOM][chartfox-oauth-check]', {icao: cleanIcao, hasToken: st.has_token});
    cfState.chartfox_oauth_connected = !!(st && st.has_token);
  });
  console.time('[OPS ROOM][chartfox-fetch] ' + cleanIcao);
  cfState._lastFetch = fetch(`/api/charts/chartfox/grouped/${encodeURIComponent(cleanIcao)}`,{cache:'no-store'})
    .then(r => safeJsonResponse(r).then(data => {
      const groupCount = (data && data.ok && data.groups) ? data.groups.length : 0;
      const itemCount = (data && data.groups) ? data.groups.flatMap(g => (g && g.charts) || []).length : 0;
      console.info('[OPS ROOM][chartfox-grouped-response]', {icao: cfState.airport, ok: !!(data && data.ok), groupCount, itemCount, error: data && data.error || null});
      console.timeEnd('[OPS ROOM][chartfox-fetch] ' + cleanIcao);
      if (!data || !data.ok) {
        console.warn('[OPS ROOM][chartfox-session-expired]', {
          icao: cfState.airport,
          dataOk: !!(data && data.ok),
          errorMessage: (data && data.error) || '(empty)',
          errorLower: String((data && data.error) || '').toLowerCase(),
          oauthMatch: String((data && data.error) || '').toLowerCase().includes('oauth'),
          cfFetchingAirports: Object.keys(cfState._fetchingAirports || {}),
        });
        // v0.25.60: render errors into the SIDEBAR, not the outer container.
        // Destroying the outer container (cfPanel.innerHTML='') was destroying
        // the entire shell — search bar, tabs, connect bar, preview — leaving
        // nothing but the error message even after OAuth reconnect succeeded.
        const sidebar = $('cfSidebar');
        if (String((data && data.error) || '').toLowerCase().includes('oauth')) {
          if (sidebar) {
            sidebar.innerHTML = '';
            const row = document.createElement('div'); row.className = 'cf-empty';
            const btn = document.createElement('button'); btn.className = 'control-button'; btn.textContent = 'RECONNECT'; btn.type = 'button'; btn.style.marginTop = '.5rem';
            btn.addEventListener('click', () => chartfox_open_authorization_window());
            row.innerHTML = 'CHARTFOX SESSION EXPIRED<br><small></small>';
            row.querySelector('small').appendChild(btn);
            sidebar.appendChild(row);
          }
        } else {
          renderOpsEmptyState(
            sidebar || container,
            `No ChartFox charts for ${escapeHtml(icao)}`,
            'This airport may not have ChartFox coverage yet, or your connection may have lapsed. Use SimBrief or the AIP/FAA chart viewer below for procedure sources.',
            'CHARTFOX GROUPED CHARTS'
          );
        }
        cfState.groups = []; cfState.items = [];
        // v0.25.60: do NOT call cfRenderSidebar() here — the sidebar already
        // shows the SESSION EXPIRED / error message. Calling cfRenderSidebar()
        // would overwrite it with a generic "NO CHARTS AVAILABLE" placeholder
        // since cfState.groups is empty.
        return;
      }
      console.time('[OPS ROOM][chartfox-render] ' + cleanIcao);
      cfState.groups = data.groups || [];
      cfState.items = (data.groups || []).flatMap(g => (g && g.charts) || []);
      cfRenderSidebar();
      cfRenderPinnedStrip();
      const preview = $('cfPreview');
      if (preview) {
        const overlay = $('cfPreviewOverlay');
        if (overlay) overlay.hidden = true;
        preview.innerHTML = `<div class="cf-preview-message">SELECT A CHART TO PREVIEW<br><small>OWN POSITION WILL APPEAR HERE WHEN CHART HAS GEO REFERENCE</small></div><div class="cf-preview-overlay" id="cfPreviewOverlay" hidden><svg viewBox="0 0 40 40" xmlns="http://www.w3.org/2000/svg"><polygon points="20,4 30,32 20,26 10,32" fill="#aaa98d" stroke="#1a2016" stroke-width="2.4" stroke-linejoin="round"/></svg></div>`;
      }
    }))      .catch(error => {
        // v0.25.60: render catch-block errors into sidebar, preserving outer shell.
        const sidebar = $('cfSidebar');
        if (sidebar) {
          sidebar.innerHTML = `<div class="cf-empty">FAILED TO LOAD CHARTFOX CHARTS<br><small>${escapeHtml((error && error.message) || '')}</small></div>`;
        }
      });
  cfState._fetchingAirports[cleanIcao] = cfState._lastFetch;
  cfState._lastFetch.finally(function() { delete cfState._fetchingAirports[cleanIcao]; });
  // Return the fetch promise so callers can track it for in-flight dedup.
  return cfState._lastFetch;
}

function cfRenderAirportChip(icao){
  const chip = $('cfAirportChip'); if (!chip) return;
  const label = String(icao || cfState.airport || '');
  chip.innerHTML = `<span>${escapeHtml(label || '--')}</span><small>&nbsp;CHARTFOX AIRPORT</small>`;
}

// v0.25.16: tabs are sort-promotion, not filter toggle. Click promotes the
// matching category to the top of the sidebar; re-click clears promotion.
const CF_TAB_BUCKETS = {STAR:[5],APP:[6],TAXI:[3],SID:[4],REF:[0,1,2],GA:[99]};
function cfWireTabs(){
  const root = $('cfTabs'); if (!root || root.dataset.cfWired === '1') return;
  root.dataset.cfWired = '1';
  root.querySelectorAll('.cf-tab').forEach(tab => {
    const key = tab.dataset.cfTab; if (!key) return;
    tab.addEventListener('click', () => {
      cfState.promoteTab = (cfState.promoteTab === key) ? null : key;
      root.querySelectorAll('.cf-tab').forEach(t => t.classList.toggle('cf-tab-active', t.dataset.cfTab === cfState.promoteTab));
      cfRenderSidebar();
    });
  });
}

// v0.25.16: every category is always visible. Tabs only mark which category
// has been promoted to the top of the sidebar list.
function cfAllowedTypes(){
  return new Set([0, 1, 2, 3, 4, 5, 6, 99]);
}

function cfRenderSidebar(){
  const sidebar = $('cfSidebar'); if (!sidebar) return;
  if (!cfState.groups || cfState.groups.length === 0) {
    sidebar.innerHTML = `<div class="cf-empty">NO CHARTS AVAILABLE<br><small>TRY A DIFFERENT AIRPORT OR CLICK RELOAD</small></div>`;
    return;
  }
  const allowed = cfAllowedTypes();
  const airportPins = (cfState.pins || []).filter(p => p.icao === cfState.airport);
  // v0.25.16: when a tab is the promote target, hoist its bucket(s) to the
  // top of the sidebar while keeping every other group in natural order.
  const promoteBuckets = (cfState.promoteTab && CF_TAB_BUCKETS[cfState.promoteTab]) || [];
  const orderedGroups = promoteBuckets.length
    ? [
        ...cfState.groups.filter(g => promoteBuckets.includes(Number(g.type))),
        ...cfState.groups.filter(g => !promoteBuckets.includes(Number(g.type))),
      ]
    : cfState.groups;
  const sections = [];
  if (airportPins.length) {
    const pinRows = airportPins.map(p => cfRenderRow({ id: p.id, icao: p.icao, title: p.title, type: p.type, type_key: p.type_key, category: p.category, runways: [] }, true)).join('');      sections.push(`<section class="cf-sidebar-section" data-cf-section="pinned"><header class="cf-group-header">PINNED<small>${airportPins.length} FIXED | ${escapeHtml(cfState.airport || '')}</small></header>${pinRows}</section>`);
  }
  let total = 0;
  for (const g of orderedGroups) {
    const items = (g.charts || []).filter(c => allowed.has(Number(c.type)));
    if (!items.length) continue;      const head = `<header class="cf-group-header">${escapeHtml(g.name || g.type_key || 'CHARTS')}<small>${items.length} CHART${items.length===1?'':'S'}</small></header>`;
    const rows = items.map(c => cfRenderRow(Object.assign({}, c, { category: c.category || g.name || c.type_key }), (cfState.pins || []).some(p => p.id === c.id))).join('');
    sections.push(`<section class="cf-sidebar-section" data-cf-section="group">${head}${rows}</section>`);
    total += items.length;
  }
  if (!sections.length || total === 0) {
    sidebar.innerHTML = `<div class="cf-empty">NO CHARTS AVAILABLE<br><small>TRY A DIFFERENT AIRPORT OR CLICK RELOAD</small></div>`;
    return;
  }
  sidebar.innerHTML = sections.join('');
  sidebar.querySelectorAll('.cf-row[data-cf-chart-id]').forEach(row => {
    row.addEventListener('click', event => {
      if (event.target.closest && event.target.closest('.cf-pin-btn')) return;
      cfSelectChart(row);
    });
    row.addEventListener('keydown', event => {
      if (event.target.closest && event.target.closest('.cf-pin-btn')) return;
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); cfSelectChart(row); }
    });
  });
  sidebar.querySelectorAll('.cf-pin-btn').forEach(btn => {
    btn.addEventListener('click', event => {
      event.preventDefault(); event.stopPropagation();
      const row = btn.closest('.cf-row[data-cf-chart-id]');
      if (row) cfTogglePinFromRow(row);
    });
  });
}

function cfRenderRow(chart, isPinned){
  const id = String(chart.id || '');
  const icao = String(chart.icao || cfState.airport || '');    const titleRaw = chart.title || chart.code || 'Chart';
    const codeRaw = chart.code || '';
    const code = codeRaw ? `<small>&middot; ${escapeHtml(codeRaw)}</small>` : '';
    const typeKey = chart.type_key || '';
    const type = chart.type != null ? String(chart.type) : '';
    const runways = Array.isArray(chart.runways) ? chart.runways.filter(Boolean).map(escapeHtml).join(' / ') : '';    const meta = JSON.stringify({ title: chart.title || '', type: chart.type, type_key: chart.type_key, category: chart.category || chart.group_name || chart.type_key }).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');    const isActive = id && id === cfState.activeChartId;
    // v0.25.60: outer is a div role="button" so the inner pin <button> is valid HTML;
    // browsers would otherwise hoist the inner button out of the outer one and break layout.
    return `<div role="button" tabindex="0" class="cf-row${isActive ? ' cf-row-active' : ''}" data-cf-chart-id="${escapeHtml(id)}" data-cf-chart-meta="${meta}" aria-current="${isActive ? 'true' : 'false'}"><div class="cf-row-info"><div class="cf-row-title">${escapeHtml(titleRaw)}${code}</div><div class="cf-row-meta">${escapeHtml(icao)} &middot; ${escapeHtml(typeKey || type)}${runways?` &middot; RWY ${runways}`:''}</div></div><button type="button" class="cf-pin-btn${isPinned ? ' cf-pin-btn-active' : ''}" data-cf-chart-id="${escapeHtml(id)}" data-cf-chart-meta="${meta}" title="${isPinned ? 'Unpin' : 'Pin'}" aria-label="${isPinned ? 'Unpin chart' : 'Pin chart'}" aria-pressed="${isPinned ? 'true' : 'false'}">${isPinned ? '\u2605' : '\u2606'}</button></div>`;
  }

function cfTogglePinFromRow(row){
  const id = row.dataset.cfChartId;
  if (!id) return;
  let meta = {}; try { meta = JSON.parse(row.dataset.cfChartMeta || '{}'); } catch (_) {}
  const pins = cfState.pins || (cfState.pins = []);
  const idx = pins.findIndex(p => p.id === id);
  if (idx >= 0){ pins.splice(idx, 1); } else {
    pins.push({ id, icao: cfState.airport, title: meta.title, type: meta.type, type_key: meta.type_key, category: meta.category });
  }
  cfSavePins();
  cfRenderSidebar();
  cfRenderPinnedStrip();
}

function cfSelectChart(row){
  const chartId = row.dataset.cfChartId; if (!chartId) return;
  // meta is row-bound: it's parsed from the same row element's data-cf-chart-meta attribute that
  // cfRenderRow wrote, and only flows into LOADING text and the preview-meta line (both escapeHtml'd).
  // Don't accept meta from any other source without re-validating.
  let meta = {}; try { meta = JSON.parse(row.dataset.cfChartMeta || '{}'); } catch (_) {}
  document.querySelectorAll('.cf-row.cf-row-active').forEach(el => el.classList.remove('cf-row-active'));
  row.classList.add('cf-row-active');
  cfState.activeChartId = chartId;          cfRenderPreview(chartId, cfState.airport, meta);
          console.timeEnd('[OPS ROOM][chartfox-render] ' + (meta && meta.id || 'chart'));
  // Update active chip in pinned strip
  cfRenderPinnedStrip();
}

// -- Pinned Charts Strip ---------------------------------------------
/** Returns a CSS class for the chart's category accent bar */
function cfPinCategoryClass(cat) {
  const c = String(cat || '').toLowerCase();
  if (c.includes('airport')) return 'cat-airport';
  if (c.includes('depart') || c.includes('sid')) return 'cat-departure';
  if (c.includes('arrival') || c.includes('star')) return 'cat-arrival';
  if (c.includes('appro') || c.includes('ils')) return 'cat-approach';
  if (c.includes('taxi')) return 'cat-taxi';
  if (c.includes('hold')) return 'cat-holding';
  return '';
}

/** Render the horizontal pinned charts strip above the briefing content */
function cfRenderPinnedStrip() {
  const strip = $('cfPinnedStrip');
  const scroll = $('cfPinnedScroll');
  if (!strip || !scroll) return;
  const pins = cfState.pins || [];
  if (pins.length === 0) {
    strip.hidden = true;
    return;
  }
  strip.hidden = false;

  // Group pins by ICAO, preserving order
  const groups = [];
  const seen = new Set();
  pins.forEach(function(p) {
    const icao = p.icao || '----';
    if (!seen.has(icao)) {
      seen.add(icao);
      groups.push({ icao: icao, charts: [] });
    }
    const g = groups[groups.length - 1];
    if (g.icao === icao) {
      g.charts.push(p);
    } else {
      // find the correct group if ICAOs aren't contiguous
      var found = false;
      for (var i = 0; i < groups.length; i++) {
        if (groups[i].icao === icao) {
          groups[i].charts.push(p);
          found = true;
          break;
        }
      }
      if (!found) {
        groups.push({ icao: icao, charts: [p] });
      }
    }
  });

  var html = '';
  var count = 0;
  groups.forEach(function(group) {
    // ICAO separator chip
    html += '<span class="cf-pinned-icao">' + escapeHtml(group.icao) + '</span>';
    group.charts.forEach(function(p) {
      count++;
      var active = p.id === cfState.activeChartId ? ' active' : '';
      var catClass = cfPinCategoryClass(p.category || p.type_key || '');
      var name = p.title || p.type_title || p.type || 'CHART';
      html += '<span class="cf-pinned-chart' + active + ' ' + catClass + '" data-cf-pin-id="' + escapeAttr(p.id) + '" data-cf-pin-icao="' + escapeAttr(p.icao || '') + '" data-cf-pin-title="' + escapeAttr(name) + '" data-cf-pin-type="' + escapeAttr(p.type || '') + '" data-cf-pin-type-key="' + escapeAttr(p.type_key || '') + '" data-cf-pin-category="' + escapeAttr(p.category || '') + '" title="' + escapeAttr(name) + '">' +
        '<span class="cf-pinned-chart-name">' + escapeHtml(name) + '</span>' +
        '<button class="cf-pinned-unpin" title="Unpin chart">&times;</button>' +
        '</span>';
    });
  });

  scroll.innerHTML = html;

  // Click handler for chips (load chart)
  Array.from(scroll.querySelectorAll('.cf-pinned-chart')).forEach(function(chip) {
    chip.addEventListener('click', function(e) {
      if (e.target.closest('.cf-pinned-unpin')) return;
      var chartId = chip.dataset.cfPinId;
      var icao = chip.dataset.cfPinIcao;
      if (!chartId) return;
      // Load the airport charts if not already loaded
      if (icao && icao !== cfState.airport) {
        cfLoadAirport(icao).then(function() {
          cfState.activeChartId = chartId;
          cfRenderPreview(chartId, icao, {
            title: chip.dataset.cfPinTitle,
            type: chip.dataset.cfPinType,
            type_key: chip.dataset.cfPinTypeKey,
            category: chip.dataset.cfPinCategory
          });
          cfRenderPinnedStrip();
        }).catch(function() {
          // Airport load failed -- chip metadata is enough to render
          cfState.activeChartId = chartId;
          cfRenderPreview(chartId, icao, {
            title: chip.dataset.cfPinTitle,
            type: chip.dataset.cfPinType,
            type_key: chip.dataset.cfPinTypeKey,
            category: chip.dataset.cfPinCategory
          });
          cfRenderPinnedStrip();
        });
      } else {
        cfState.activeChartId = chartId;
        cfRenderPreview(chartId, icao, {
          title: chip.dataset.cfPinTitle,
          type: chip.dataset.cfPinType,
          type_key: chip.dataset.cfPinTypeKey,
          category: chip.dataset.cfPinCategory
        });
        cfRenderPinnedStrip();
      }
    });
  });

  // Click handler for unpin buttons
  // v0.25.60: preventDefault prevents chip click from bubbling to chart load handler
  Array.from(scroll.querySelectorAll('.cf-pinned-unpin')).forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      e.preventDefault();
      var chip = btn.closest('.cf-pinned-chart');
      if (!chip) return;
      var chartId = chip.dataset.cfPinId;
      if (!chartId) return;
      var pins = cfState.pins || (cfState.pins = []);
      var idx = pins.findIndex(function(p) { return p.id === chartId; });
      if (idx >= 0) pins.splice(idx, 1);
      cfSavePins();
      cfRenderPinnedStrip();
      cfRenderSidebar();
    });
  });

  // Render count badge if > 0
  if (count > 0) {
    var badge = document.createElement('span');
    badge.className = 'cf-pinned-count';
    badge.textContent = count + ' pinned';
    scroll.appendChild(badge);
  }
}

/**
 * Auto-pin charts from SimBrief flight plan data.
 * Scans loaded ChartFox items for matching airport, SID, STAR, and ILS charts.
 */
function cfAutoPinFromSimBrief(plan) {
  // Only auto-pin once per flight plan (session flag prevents re-pinning on refresh)
  if (plan && plan._autoPinnedOnce) return;
  if (plan) plan._autoPinnedOnce = true;
  if (!plan || !plan.ok) return;
  // Ensure chart data is loaded for origin and destination airports
  var needLoad = [];
  var originIcao = plan.origin?.icao || '';
  var destIcao = plan.destination?.icao || '';
  if (originIcao && (!cfState.items || !cfState.items.some(function(i) { return i.icao === originIcao; }))) {
    needLoad.push(originIcao);
  }
  if (destIcao && (!cfState.items || !cfState.items.some(function(i) { return i.icao === destIcao; }))) {
    needLoad.push(destIcao);
  }
  if (needLoad.length > 0) {
    // Load missing airports first, then auto-pin
    Promise.all(needLoad.map(function(icao) { return cfLoadAirport(icao).catch(function(){}); })).then(function() {
      cfAutoPinFromSimBrief(plan);
    });
    return;
  }
  if (!cfState.items || cfState.items.length === 0) return;
  var origin = plan.origin?.icao || '';
  var destination = plan.destination?.icao || '';
  var sid = plan.origin?.sid || '';
  var star = plan.destination?.star || '';
  var runway = plan.destination?.runway || '';
  if (!origin && !destination) return;

  var autoPins = [];
  var alreadyPinned = new Set((cfState.pins || []).map(function(p) { return p.id; }));

  // Helper: find charts by ICAO and a matching predicate
  function findChart(icao, predicate) {
    return cfState.items.filter(function(item) {
      return item.icao === icao && predicate(item);
    });
  }

  // Normalize a string for comparison
  function normalize(s) {
    return String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  }

  // 1. Departure airport -- pin the first 'airport' or 'general' chart
  if (origin) {
    var depAirport = findChart(origin, function(item) {
      var cat = String(item.category || item.type_key || '').toLowerCase();
      return cat.includes('airport') || cat.includes('general');
    });
    if (depAirport.length > 0) {
      autoPins.push({ item: depAirport[0], icao: origin });
    }
  }

  // 2. Departure SID -- match SID name in chart title
  if (origin && sid) {
    var sidNorm = normalize(sid);
    var sidCharts = findChart(origin, function(item) {
      var cat = String(item.category || item.type_key || '').toLowerCase();
      if (!cat.includes('depart') && !cat.includes('sid')) return false;
      var title = normalize(item.title || item.name || '');
      return title.includes(sidNorm) || sidNorm.includes(title);
    });
    if (sidCharts.length === 0) {
      // Fallback: any departure chart
      sidCharts = findChart(origin, function(item) {
        var cat = String(item.category || item.type_key || '').toLowerCase();
        return cat.includes('depart') || cat.includes('sid');
      });
    }
    sidCharts.forEach(function(item) { autoPins.push({ item: item, icao: origin }); });
  }

  // 3. Arrival airport -- pin the first 'airport' or 'general' chart
  if (destination) {
    var arrAirport = findChart(destination, function(item) {
      var cat = String(item.category || item.type_key || '').toLowerCase();
      return cat.includes('airport') || cat.includes('general');
    });
    if (arrAirport.length > 0) {
      autoPins.push({ item: arrAirport[0], icao: destination });
    }
  }

  // 4. Arrival STAR -- match STAR name in chart title
  if (destination && star) {
    var starNorm = normalize(star);
    var starCharts = findChart(destination, function(item) {
      var cat = String(item.category || item.type_key || '').toLowerCase();
      if (!cat.includes('arrival') && !cat.includes('star')) return false;
      var title = normalize(item.title || item.name || '');
      return title.includes(starNorm) || starNorm.includes(title);
    });
    if (starCharts.length === 0) {
      starCharts = findChart(destination, function(item) {
        var cat = String(item.category || item.type_key || '').toLowerCase();
        return cat.includes('arrival') || cat.includes('star');
      });
    }
    starCharts.forEach(function(item) { autoPins.push({ item: item, icao: destination }); });
  }

  // 5. Approach ILS -- match runway in chart title
  if (destination && runway) {
    var rwyNorm = normalize(runway);
    var ilsCharts = findChart(destination, function(item) {
      var cat = String(item.category || item.type_key || '').toLowerCase();
      if (!cat.includes('appro') && !cat.includes('ils')) return false;
      var title = normalize(item.title || item.name || '');
      return title.includes(rwyNorm);
    });
    if (ilsCharts.length === 0) {
      // Fallback: any approach chart
      ilsCharts = findChart(destination, function(item) {
        var cat = String(item.category || item.type_key || '').toLowerCase();
        return cat.includes('appro') || cat.includes('ils');
      });
    }
    ilsCharts.forEach(function(item) { autoPins.push({ item: item, icao: destination }); });
  }

  // Deduplicate and add pins
  var added = 0;
  autoPins.forEach(function(entry) {
    var item = entry.item;
    var id = item.id || item.chart_id || '';
    if (!id || alreadyPinned.has(id)) return;
    alreadyPinned.add(id);
    var title = item.title || item.name || 'CHART';
    var category = item.category || item.type_key || '';
    cfState.pins = cfState.pins || [];
    cfState.pins.push({
      id: id,
      icao: entry.icao,
      title: title,
      type: item.type || title,
      type_key: item.type_key || category,
      type_title: item.type_title || title,
      category: category,
      subtype: item.subtype || '',
      subtype_title: item.subtype_title || ''
    });
    added++;
  });

  if (added > 0) {
    cfSavePins();
    cfRenderPinnedStrip();
    cfRenderSidebar();
    notifyOps({source:'BRIEFING',title:'CHARTS PINNED',message:'Auto-pinned ' + added + ' chart(s) from flight plan.',priority:'operational',page:'briefing'}, {read:true});
  }
}

// v0.25.16: pre-check proxy availability before setting iframe src
// so JSON error payloads never render inside the chart pane.
// Uses fetchWithTimeout (defined in opsroom.js) to prevent hanging on
// network stalls, since the status endpoint is lightweight.
// -- PDF.js Canvas Renderer ---------------------------------------------
/** Render a PDF page to the canvas at the current scale */
async function cfRenderPdfPage(pdfDoc, pageNum, canvas, scale) {
  cfPdfState.pageRendering = true;
  try {
    const page = await pdfDoc.getPage(pageNum);
    const viewport = page.getViewport({ scale });
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    cfPdfState.viewport = viewport;
    // v0.25.60: capture native page dimensions at scale=1.0 for annotation anchoring
    cfPdfState.nativeWidth = viewport.width / scale;
    cfPdfState.nativeHeight = viewport.height / scale;
    const ctx = canvas.getContext('2d');
    cfPdfState.ctx = ctx;
    await page.render({ canvasContext: ctx, viewport }).promise;
  } catch(e){ cfPdfState.pageRendering = false; /* render error, silently handled */ }
  cfPdfState.pageRendering = false;
  // v0.25.60: resize annotation canvas to match new PDF dimensions and redraw
  if (cfAnnotation.canvas) {
    cfAnnotation.canvas.width = canvas.width;
    cfAnnotation.canvas.height = canvas.height;
    cfRedrawAnnotations();
  }
  if (cfPdfState.pageNumPending !== null) {
    cfRenderPdfPage(pdfDoc, cfPdfState.pageNumPending, canvas, cfPdfState.scale);
    cfPdfState.pageNumPending = null;
  }
}

/** Queue a PDF page render (handles concurrent renders) */
function cfQueueRenderPdfPage(pdfDoc, num, canvas) {
  if (cfPdfState.pageRendering) {
    cfPdfState.pageNumPending = num;
  } else {
    cfRenderPdfPage(pdfDoc, num, canvas, cfPdfState.scale);
  }
}

/** Apply dark mode CSS filter to the canvas wrapper */
function cfApplyDarkMode(dark) {
  const wrap = $('cfPdfCanvasWrap');
  if (!wrap) return;
  if (dark) {
    wrap.style.filter = 'invert(0.9) hue-rotate(180deg) contrast(1.15) brightness(0.95)';
    wrap.style.background = '#fff';
  } else {
    wrap.style.filter = '';
    wrap.style.background = '';
  }
}

/** Set up PDF.js interactive canvas with zoom/pan/dark mode */
function cfInitPdfCanvas(container, canvas, pdfDoc, chartName, viewUrl, proxyUrl, copyrightHtml, chartId, icao, meta, chart, hasGeoref) {
  cfPdfState.canvas = canvas;
  cfPdfState.container = container;
  cfPdfState.scale = 1.0;
  cfPdfState.panOffset = { x: 0, y: 0 };
  cfPdfState.darkMode = true;

  // Render first page
  cfRenderPdfPage(pdfDoc, 1, canvas, cfPdfState.scale);
  cfPdfState.pageNum = 1;

  // Build toolbar
  const toolbar = document.createElement('div');
  toolbar.className = 'cf-pdf-toolbar';
  const escName = escapeHtml(chartName || 'PDF CHART');
  const escProxy = escapeHtml(proxyUrl);
  const escView = escapeHtml(viewUrl || '#');
  toolbar.innerHTML = '<span class="cf-pdf-toolbar-title">' + escName + '</span>' +
    '<div class="cf-pdf-toolbar-actions">' +
    '<button type="button" class="cf-pdf-tb-btn" id="cfPdfZoomOut" title="Zoom Out">−</button>' +
    '<span class="cf-pdf-zoom-label" id="cfPdfZoomLabel">100%</span>' +
    '<button type="button" class="cf-pdf-tb-btn" id="cfPdfZoomIn" title="Zoom In">+</button>' +
    '<button type="button" class="cf-pdf-tb-btn" id="cfPdfZoomFit" title="Fit to Width">⇔</button>' +
    '<button type="button" class="cf-pdf-tb-btn" id="cfPdfDarkToggle" title="Toggle Dark Mode">◐</button>' +
    '<a class="cf-pdf-tb-btn cf-pdf-link-icon" href="' + escProxy + '" target="_blank" title="Download PDF">↓</a>' +
    (viewUrl ? '<a class="cf-pdf-tb-btn cf-pdf-link-icon" href="' + escView + '" target="_blank" title="Open on ChartFox">↗</a>' : '') +
    '</div>';
  container.prepend(toolbar);

  // Wrap canvas for pan/scroll
  const wrap = document.createElement('div');
  wrap.className = 'cf-pdf-canvas-wrap';
  wrap.id = 'cfPdfCanvasWrap';
  canvas.parentNode.insertBefore(wrap, canvas);
  wrap.appendChild(canvas);

  // Zoom handler
  const doZoom = (delta) => {
    const newScale = Math.min(5.0, Math.max(0.25, cfPdfState.scale + delta));
    cfPdfState.scale = newScale;
    const label = $('cfPdfZoomLabel');
    if (label) label.textContent = Math.round(newScale * 100) + '%';
    cfRenderPdfPage(pdfDoc, cfPdfState.pageNum, canvas, newScale);
    if (cfPdfState.darkMode) cfApplyDarkMode(true);
  };

  // Mouse wheel zoom
  container.addEventListener('wheel', (e) => {
    e.preventDefault();
    doZoom(e.deltaY > 0 ? -0.25 : 0.25);
  }, { passive: false });

  // Pan via click-drag on canvas
  let isPanning = false, startX = 0, startY = 0, origLeft = 0, origTop = 0;
  canvas.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    isPanning = true;
    startX = e.clientX;
    startY = e.clientY;
    origLeft = cfPdfState.panOffset.x;
    origTop = cfPdfState.panOffset.y;
    canvas.style.cursor = 'grabbing';
  });
  var panWrap = wrap; // v0.25.60: pan the wrapper so both PDF + annotation canvases move together
  window.addEventListener('mousemove', (e) => {
    if (!isPanning) return;
    var dx = e.clientX - startX;
    var dy = e.clientY - startY;
    cfPdfState.panOffset.x = origLeft + dx;
    cfPdfState.panOffset.y = origTop + dy;
    panWrap.style.transform = 'translate(' + cfPdfState.panOffset.x + 'px, ' + cfPdfState.panOffset.y + 'px)';
  });
  window.addEventListener('mouseup', () => {
    if (!isPanning) return;
    isPanning = false;
    canvas.style.cursor = '';
  });

  // Toolbar button handlers
  const zoomOut = $('cfPdfZoomOut');
  if (zoomOut) zoomOut.addEventListener('click', () => doZoom(-0.25));
  const zoomIn = $('cfPdfZoomIn');
  if (zoomIn) zoomIn.addEventListener('click', () => doZoom(0.25));
  const zoomFit = $('cfPdfZoomFit');
  if (zoomFit) zoomFit.addEventListener('click', () => {
    const cw = container.clientWidth - 40;
    const ch = container.clientHeight - 60;
    pdfDoc.getPage(1).then(function(p) {
      const vp = p.getViewport({ scale: 1 });
      const fit = Math.min(cw / vp.width, ch / vp.height);
      cfPdfState.scale = fit;
      const label = $('cfPdfZoomLabel');
      if (label) label.textContent = Math.round(fit * 100) + '%';
      cfPdfState.panOffset = { x: 0, y: 0 };
      canvas.style.transform = '';
      cfRenderPdfPage(pdfDoc, cfPdfState.pageNum, canvas, fit);
      if (cfPdfState.darkMode) cfApplyDarkMode(true);
    });
  });
  const darkToggle = $('cfPdfDarkToggle');
  if (darkToggle) darkToggle.addEventListener('click', () => {
    cfPdfState.darkMode = !cfPdfState.darkMode;
    cfApplyDarkMode(cfPdfState.darkMode);
  });

  // Ownship overlay setup for PDF canvas
  if (hasGeoref && chart) {
    const georefs = chart.georefs || [];
    const georef = georefs.find(function(g) { return g && g.tx != null && g.ty != null && g.k != null; }) || georefs[0];
    if (georef) {
      setTimeout(function() {
        if (canvas.width > 0 && canvas.height > 0) {
          cfStartOverlayTimer(canvas, georef);
        }
      }, 300);
    }
  }
}

async function cfRenderPreview(chartId, icao, meta){
  const preview = $('cfPreview'); if (!preview) return;
  preview.innerHTML = '<div class="cf-empty">LOADING ' + escapeHtml((meta && meta.title) || 'CHART') + '\u2026</div><div class="cf-preview-overlay" id="cfPreviewOverlay" hidden><svg viewBox="0 0 40 40" xmlns="http://www.w3.org/2000/svg"><polygon points="20,4 30,32 20,26 10,32" fill="#aaa98d" stroke="#1a2016" stroke-width="2.4" stroke-linejoin="round"/></svg></div>';
  if (cfState.previewTimer) { clearInterval(cfState.previewTimer); cfState.previewTimer = null; }
  try {
    const r = await fetch('/api/charts/chartfox/chart/' + encodeURIComponent(chartId), {cache:'no-store'});
    const data = await safeJsonResponse(r);
    if (!data || !data.ok) {
      preview.innerHTML = '<div class="cf-empty">CHART LOAD FAILED<br><small>' + escapeHtml((data && data.error) || '') + '</small></div><div class="cf-preview-overlay" id="cfPreviewOverlay" hidden></div>';
      return;
    }
    const chart = data.chart || {};
    if (chart.requires_preauth) {
      preview.innerHTML = '<div class="cf-pdf-fallback"><b>PREAUTH REQUIRED</b><p>' + escapeHtml(chart.name || 'Chart') + ' requires a ChartFox disclaimer acceptance before viewing.</p><a class="cf-pdf-link" href="' + escapeAttr(chart.view_url || '#') + '" target="_blank" rel="noopener noreferrer">ACCEPT DISCLAIMER ON CHARTFOX</a></div><div class="cf-preview-overlay" id="cfPreviewOverlay" hidden></div>';
      return;
    }
    // --- Strict 3-step file selection (ChartFox API spec): files[] → source_url → url ---
    // FileType enum: 0=PDF, 1=IMG (first-party mirrors, always static files)
    // ChartUrlType enum: 0=PDF, 1=IMG, 2=HTML (interactive viewer, not directly renderable)
    var targetUrl = null;
    var isPdf = false;

    // Step A: files[] — first-party ChartFox-hosted mirrors (PDF preferred)
    var filesArr = Array.isArray(chart.files) ? chart.files : [];
    if (filesArr.length > 0) {
      var pdfFile = filesArr.find(function(f) { return Number(f.type) === 0; });
      if (pdfFile) { targetUrl = pdfFile.url; isPdf = true; }
      else {
        var imgFile = filesArr.find(function(f) { return Number(f.type) === 1; });
        if (imgFile) targetUrl = imgFile.url;
      }
    }

    // Step B: source_url (direct supplier link, public URL, no auth needed)
    if (!targetUrl && chart.source_url) {
      targetUrl = chart.source_url;
      isPdf = (Number(chart.source_url_type) === 0);
    }

    // v0.25.60: removed endsWith('.pdf') extension guessing — use source_url_type
    // when available. When unavailable, fall through to view_url (unsafe to guess file type).
    if (!targetUrl && chart.url) {
      if (chart.source_url_type != null) {
        targetUrl = chart.url;
        isPdf = (Number(chart.source_url_type) === 0);
      }
      // else: don't guess — leave targetUrl null, chart will show VIEW ON CHARTFOX
    }

    console.info('[OPS ROOM][chartfox-render]', {chartId: chartId, icao: icao, targetUrl: targetUrl ? targetUrl.substring(0, 80) : null, isPdf: isPdf, source_url: chart.source_url, source_url_type: chart.source_url_type, allows_iframe: chart.allows_iframe, requires_preauth: chart.requires_preauth, filesCount: filesArr.length, filesTypes: filesArr.map(function(f){return f.type;}), renderBranch: isHtml ? (canIframeHtml ? 'html-iframe' : 'html-link') : (isPdf ? 'pdf' : 'img')});
    const hasGeoref = Array.isArray(chart.georefs) && chart.georefs.some(function(g) { return g && g.tx != null && g.ty != null && g.k != null; });
    const viewUrl = chart.view_url || '';
    const source = chart.source || {};
    const copyrightText = String(source.copyright_short || source.copyright_status || '').trim();
    const chartName = chart.name || (meta && meta.title) || 'CHART';
    const metaHtml = '<div class="cf-preview-meta-single">' +
      '<span>' + escapeHtml(icao) + ' &middot; ' + escapeHtml(chartName) + (chart.code ? ' &middot; ' + escapeHtml(chart.code) : '') + '</span>' +
      (copyrightText ? '<span class="meta-sep">&bull;</span><span>' + escapeHtml(copyrightText).replace(/&#169;|&amp;#169;/g, '\u00a9') + '</span>' : '') +
      '<span class="meta-sep">&bull;</span><span class="badge-tag">PDF VIEW</span>' +
      '<span class="badge-tag' + (hasGeoref ? ' geo-ok' : '') + '">' + (hasGeoref ? 'GEO REFERENCED \ud83d\udfe2' : 'NO GEO REFERENCE') + '</span>' +
      '</div>';
    const badgeHtml = '';
    const overlayHtml = '<div class="cf-preview-overlay" id="cfPreviewOverlay" hidden><svg viewBox="0 0 40 40" xmlns="http://www.w3.org/2000/svg"><polygon points="20,4 30,32 20,26 10,32" fill="var(--muted)" stroke="#1a2016" stroke-width="2.4" stroke-linejoin="round"/></svg></div><div class="cf-ownship-dot" id="cfOwnshipDot" hidden></div>';
    const proxyUrl = '/api/charts/chartfox/file/' + encodeURIComponent(chartId);
    const copyrightHtml = copyrightText
      ? '<div class="cf-attribution" style="font-size:0.65rem;color:var(--muted, #aaa98d);padding:0.3rem 0.5rem;text-align:right">' + escapeHtml(copyrightText).replace(/&#169;|&amp;#169;/g, '\u00a9') + ' &middot; Charts via ChartFox</div>'
      : '<div class="cf-attribution" style="font-size:0.65rem;color:var(--muted, #aaa98d);padding:0.3rem 0.5rem;text-align:right">Charts via ChartFox</div>';

    // Guard: source_url_type=2 is HTML (interactive viewer).
    // v0.25.60: if allows_iframe && !requires_preauth, embed in iframe.
    // Otherwise show an external link.
    var isHtml = targetUrl && Number(chart.source_url_type) === 2;
    var canIframeHtml = isHtml && chart.allows_iframe && !chart.requires_preauth;

    var contentHtml;

    if (targetUrl && !isHtml) {
      if (isPdf) {
        // --- PDF: render via PDF.js canvas ---
        preview.innerHTML = metaHtml + copyrightHtml + badgeHtml + overlayHtml;
        var pdfContainer = document.createElement('div');
        pdfContainer.className = 'cf-pdf-canvas-container';
        pdfContainer.style.cssText = 'flex:1;overflow:auto;display:flex;flex-direction:column;min-height:0;width:100%';
        preview.appendChild(pdfContainer);
        cfRenderPdfCanvas(proxyUrl, pdfContainer, chartId, chartName, viewUrl);
        return;
      } else {
        // --- IMG: render as image with pan/zoom ---
        contentHtml = '<img class="cf-preview-img" id="cfChartImg" data-cf-chart-id="' + chartId + '" alt="' + escapeHtml(chartName) + '" src="' + escapeHtml(proxyUrl) + '" loading="lazy"/>' + copyrightHtml;
        preview.innerHTML = metaHtml + contentHtml + badgeHtml + overlayHtml;
        var chartImg = $('cfChartImg');
        if (chartImg && hasGeoref) {
          var georefData = (chart.georefs || []).find(function(g) { return g && g.tx != null && g.ty != null && g.k != null; }) || (chart.georefs || [])[0];
          if (georefData) {
            var startOverlayFn = function() { cfStartOverlayTimer(chartImg, georefData); };
            chartImg.addEventListener('load', startOverlayFn, { once: true });
            if (chartImg.complete && chartImg.naturalWidth > 0) startOverlayFn();
          }
        }
      }
    } else if (isHtml && canIframeHtml) {
      // --- HTML interactive viewer: embed in iframe (allows_iframe=true, no preauth) ---
      // v0.25.60: iframe may be blocked by X-Frame-Options on external AIP sites.
      // If load fails, the onerror handler replaces the iframe with an external link.
      var iframeId = 'cfHtmlIframe_' + chartId.replace(/[^a-zA-Z0-9]/g, '');
      var iframeHtml = '<iframe id="' + iframeId + '" class="cf-preview-iframe" src="' + escapeAttr(targetUrl) + '" sandbox="allow-scripts allow-same-origin allow-forms allow-popups" referrerpolicy="no-referrer" title="' + escapeHtml(chartName) + '" onerror="var f=document.getElementById(\'' + iframeId + '\');if(f){f.style.display=\'none\';var fb=f.nextElementSibling;if(fb)fb.hidden=false;}"></iframe>';
      var iframeFallback = '<div class="cf-pdf-fallback" hidden><b>INTERACTIVE CHART</b><p>This chart could not be embedded. Some external sites block iframe embedding.</p><a class="cf-pdf-link" href="' + escapeAttr(targetUrl) + '" target="_blank" rel="noopener noreferrer">OPEN CHART IN BROWSER</a>' + copyrightHtml + '</div>';
      contentHtml = iframeHtml + iframeFallback;
      preview.innerHTML = metaHtml + contentHtml + badgeHtml + overlayHtml;
      // Timeout guard: if iframe hasn't loaded in 8s, show fallback
      setTimeout(function(){
        var ifr = document.getElementById(iframeId);
        var fb = ifr && ifr.nextElementSibling;
        if (ifr && fb && !ifr.contentDocument) {
          // iframe contentDocument is null when blocked (cross-origin or X-Frame-Options)
          // For same-origin pages it would be accessible. Since we can't detect cross-origin
          // load success, we rely on the onerror attribute above for blocked cases.
        }
      }, 8000);
    } else if (isHtml) {
      // --- HTML interactive viewer: show external link (cannot embed) ---
      contentHtml = '<div class="cf-pdf-fallback"><b>INTERACTIVE CHART</b><p>This chart is an interactive viewer page and cannot be rendered directly in OPS ROOM.</p><a class="cf-pdf-link" href="' + escapeAttr(targetUrl) + '" target="_blank" rel="noopener noreferrer">OPEN CHART IN BROWSER</a>' + copyrightHtml + '</div>';
      preview.innerHTML = metaHtml + contentHtml + badgeHtml + overlayHtml;
    } else {
      // --- No renderable URL: show ChartFox external link if view_url exists ---
      if (viewUrl) {
        contentHtml = '<div class="cf-pdf-fallback"><b>CHART AVAILABLE ON CHARTFOX</b><p>This chart cannot be rendered directly.</p><a class="cf-pdf-link" href="' + escapeAttr(viewUrl) + '" target="_blank" rel="noopener noreferrer">VIEW ON CHARTFOX</a>' + copyrightHtml + '</div>';
      } else {
        contentHtml = '<div class="cf-empty">CHART UNAVAILABLE<p style="font-size:0.7rem;color:var(--muted, #aaa98d)">No viewable file was returned for this chart.</p></div>' + copyrightHtml;
      }
      preview.innerHTML = metaHtml + contentHtml + badgeHtml + overlayHtml;
    }
  } catch (error) {
    preview.innerHTML = '<div class="cf-empty">CHART LOAD FAILED<br><small>' + escapeHtml((error && error.message) || '') + '</small></div><div class="cf-preview-overlay" id="cfPreviewOverlay" hidden></div>';
  }
}


function cfStartOverlayTimer(img, georef){
  if (!img || !georef) return;
  const chartId = img && img.dataset ? img.dataset.cfChartId : '';
  if (!chartId || chartId !== cfState.activeChartId) return; // stale image guard (fix #1)
  if (cfState.previewTimer) clearInterval(cfState.previewTimer);
  const update = async () => {
    try {
      const naturalW = img.naturalWidth || img.width || 1;
      const naturalH = img.naturalHeight || img.height || 1;
      const r = await fetch('/api/charts/overlay/compute', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ georeference: georef, display_width_px: naturalW, display_height_px: naturalH }), cache: 'no-store' });
      const data = await r.json();
      if (!data || !data.ok) return;
      const rect = img.getBoundingClientRect();
      const scaleX = (rect.width || naturalW) / naturalW || 1;
      const scaleY = (rect.height || naturalH) / naturalH || 1;
      const overlay = $('cfPreviewOverlay');
      if (!overlay) return;
      overlay.hidden = false;
      overlay.style.left = `${(data.x_px * scaleX).toFixed(1)}px`;
      overlay.style.top = `${(data.y_px * scaleY).toFixed(1)}px`;
      const h = typeof data.heading_deg === 'number' ? data.heading_deg : 0;
      overlay.style.transform = `translate(-50%,-50%) rotate(${h.toFixed(1)}deg)`;
      // v0.25.60: also plot client-side ownship dot when georef data is present
      if (georef && typeof data.lat === 'number' && typeof data.lon === 'number') {
        cfPlotOwnship(georef, data.lon, data.lat, h);
      }
      if (badge) {
        const lat = typeof data.lat === 'number' ? data.lat.toFixed(4) : '?';
        const lon = typeof data.lon === 'number' ? data.lon.toFixed(4) : '?';
        badge.textContent = `LIVE ${String(data.source || 'SIM').toUpperCase()} \u00b7 ${lat}, ${lon} \u00b7 HDG ${Math.round(h)}\u00b0 \u00b7 SPD ${Math.round(data.ground_speed_kts || 0)} KT \u00b7 GEO REF ON`;
      }
    } catch (_) {}
  };
  update();
  cfState.previewTimer = setInterval(update, 2200);
}

function cfLoadPins(){
  try {
    const raw = localStorage.getItem('opsroom.chartfox.pins');
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr : [];
  } catch (_) { return []; }
}function cfSavePins(){
  try{
    const pins = (cfState.pins || []).map(p => ({ id: p.id, icao: p.icao, title: p.title, type: p.type, type_key: p.type_key, category: p.category, type_title: p.type_title, subtype: p.subtype, subtype_title: p.subtype_title }));
    localStorage.setItem('opsroom.chartfox.pins', JSON.stringify(pins));
  } catch (_) {}
}

// v0.25.60 — Geo-Reference Engine: WGS84→EPSG:3857→Chart Canvas Point
/** Transforms WGS84 (Lat/Lon) to EPSG:3857 (Spherical Mercator) */
function wgs84ToEPSG3857(lon, lat) {
  const x = (lon * 20037508.34) / 180;
  let y = Math.log(Math.tan(((90 + lat) * Math.PI) / 360)) / (Math.PI / 180);
  y = (y * 20037508.34) / 180;
  return [x, y];
}

/**
 * Transforms World Coordinate (EPSG:3857) to Relative Chart Canvas Point (0.0 to 1.0)
 * @param {Array} coord - [xWorld, yWorld] in EPSG:3857
 * @param {Object} geoMeta - { tx, ty, k, transform_angle, pdf_page_rotation }
 * @param {Number} renderedHeight - Canvas rendered CSS height in pixels
 */
function worldToChartPoint(coord, geoMeta, renderedHeight) {
  const xWorldTrans = coord[0] - geoMeta.tx;
  const yWorldTrans = coord[1] - geoMeta.ty;
  const kLocal = geoMeta.k / renderedHeight;
  const rad = (geoMeta.transform_angle || 0) * (Math.PI / 180);
  const cosA = Math.cos(rad);
  const sinA = Math.sin(rad);
  const xChart = (1 / kLocal) * (cosA * xWorldTrans + sinA * yWorldTrans);
  const yChart = (1 / kLocal) * (sinA * xWorldTrans - cosA * yWorldTrans);
  return { x: xChart, y: yChart };
}

/**
 * v0.25.60: Plot ownship position on geo-referenced chart.
 * Called by cfStartOverlayTimer when georef data + live telemetry are available.
 */
function cfPlotOwnship(georef, lon, lat, heading) {
  var dot = document.getElementById('cfOwnshipDot');
  if (!dot) return;
  if (!lon || !lat) { dot.hidden = true; return; }
  try {
    // Use actual chart element height, not viewport height, for accurate georef scaling
    var chartEl = document.getElementById('cfPdfCanvas') || document.getElementById('cfChartImg');
    var h = (chartEl && chartEl.offsetHeight) || 600;
    var worldCoord = wgs84ToEPSG3857(lon, lat);
    var pt = worldToChartPoint(worldCoord, georef, h);
    dot.style.left = (pt.x * 100) + '%';
    dot.style.top = (pt.y * 100) + '%';
    dot.style.transform = 'translate(-50%,-50%) rotate(' + (heading || 0) + 'deg)';
    dot.hidden = false;
  } catch (_) { dot.hidden = true; }
}

// v0.25.9: Quick-pick chips for the active OFP's origin / destination / alternate.
// Reads flightPlan and renders chips into #cfQuickPicks so the user can jump straight to a chart pack.
function cfRenderQuickPicks(){
  console.info('[OPS ROOM][cf-quick-picks]', {
    has_plan: typeof flightPlan !== 'undefined' && !!flightPlan,
    plan_ok: flightPlan && flightPlan.ok,
    origin: flightPlan && flightPlan.origin && flightPlan.origin.icao || null,
    destination: flightPlan && flightPlan.destination && flightPlan.destination.icao || null,
    alternate: flightPlan && flightPlan.alternate && flightPlan.alternate.icao || null,
  });
  const root = $('cfQuickPicks'); if(!root) return;
  if (root.dataset.cfWired !== '1'){
    root.dataset.cfWired = '1';
    root.addEventListener('click', (e) => {
      const btn = e.target.closest && e.target.closest('.cf-quick-pick[data-cf-pick-icao]');
      if (!btn) return;
      e.preventDefault();
      const icao = String(btn.dataset.cfPickIcao || '').toUpperCase();
      if (icao) cfLoadAirport(icao);
    });
  }
  // Only flightPlan is a reliable signal here. summary is system status, never the route; the live plan
  // is hydrated into flightPlan by hydrateMasterOfpFromSummary().
  const plan = (typeof flightPlan !== 'undefined' && flightPlan && flightPlan.ok) ? flightPlan : null;
  const items = [];
  if (plan && plan.origin && plan.origin.icao) items.push({ kind:'DEP', icao:String(plan.origin.icao).toUpperCase(), name: plan.origin.name || '', runway: plan.origin.runway || '' });
  if (plan && plan.destination && plan.destination.icao) items.push({ kind:'ARR', icao:String(plan.destination.icao).toUpperCase(), name: plan.destination.name || '', runway: plan.destination.runway || '' });
  if (plan && plan.alternate && plan.alternate.icao) items.push({ kind:'ALT', icao:String(plan.alternate.icao).toUpperCase(), name: plan.alternate.name || '' });
  // de-duplicate by ICAO, prefer the first-kind chip (DEP wins over ARR wins over ALT)
  const seen = new Set();
  const unique = [];
  for (const it of items){
    if (!it.icao || seen.has(it.icao)) continue;
    seen.add(it.icao); unique.push(it);
  }
  if (!unique.length){
    root.innerHTML = '';
    root.hidden = true;
    return;
  }
  const activeIcao = (cfState && cfState.airport) ? String(cfState.airport).toUpperCase() : '';
  root.hidden = false;
  root.innerHTML = unique.map(it => `<button type="button" class="cf-quick-pick${it.icao === activeIcao ? ' cf-quick-pick-active' : ''}" data-cf-pick-icao="${escapeHtml(it.icao)}" title="${escapeHtml((it.name || '') + (it.runway ? ' \u00b7 RWY ' + it.runway : ''))}"><b class="cf-quick-pick-kind cf-quick-pick-kind-${escapeHtml(it.kind.toLowerCase())}">${escapeHtml(it.kind)}</b><span class="cf-quick-pick-icao">${escapeHtml(it.icao)}</span>${it.name ? `<small class="cf-quick-pick-name">${escapeHtml(it.name)}</small>` : ''}</button>`).join('');
}

// v0.25.9: Wire the existing #briefingChartFoxSearch input + #briefingChartFoxSearchResults dropdown.
// Click-outside-to-close, ESC to close, Enter to load first result, debounce ~200 ms.
function cfWireSearchBox(){
  const input = $('briefingChartFoxSearch'); if(!input || input.dataset.cfWired === '1') return;
  const results = $('briefingChartFoxSearchResults');
  input.dataset.cfWired = '1';
  cfState.searchSeq = 0;
  cfState.searchDebounce = null;
  let activeIndex = -1;
  const highlight = (idx) => {
    if (!results) return;
    const rows = results.querySelectorAll('.cf-result');
    rows.forEach((row, i) => row.setAttribute('aria-selected', String(i === idx)));
    rows.forEach((row, i) => row.classList.toggle('cf-result-hover', i === idx));
    activeIndex = idx;
    if (idx >= 0 && rows[idx]) rows[idx].scrollIntoView({ block: 'nearest' });
  };
  input.addEventListener('input', () => {
    const q = String(input.value || '').trim();
    if (cfState.searchDebounce) clearTimeout(cfState.searchDebounce);
    if (!q || q.length < 2){ cfHideSearchResults(); return; }
    cfState.searchDebounce = setTimeout(() => cfHandleSearchFetch(q), 200);
  });
  input.addEventListener('keydown', (e) => {
    if (!results) return;
    const rows = results.querySelectorAll('.cf-result');
    if (e.key === 'Escape'){ cfHideSearchResults(); input.blur(); e.preventDefault(); return; }
    if (e.key === 'ArrowDown'){ highlight(Math.min(rows.length - 1, activeIndex + 1)); e.preventDefault(); return; }
    if (e.key === 'ArrowUp'){ highlight(Math.max(-1, activeIndex - 1)); e.preventDefault(); return; }
    if (e.key === 'Enter'){
      const pick = rows[activeIndex >= 0 ? activeIndex : 0];
      const icao = pick ? pick.dataset.cfPickIcao : (rows[0] && rows[0].dataset.cfPickIcao) || String(input.value || '').trim().toUpperCase();
      if (icao){ cfLoadAirport(icao); cfHideSearchResults(); input.value = icao; e.preventDefault(); }
      return;
    }
  });
  input.addEventListener('focus', () => {
    const q = String(input.value || '').trim();
    if (q.length >= 2) cfHandleSearchFetch(q);
  });
}

// v0.25.9: Fetch the airport-search dropdown from the same DB VATSIM FIDS uses (/api/airports).
// Sequenced to drop stale responses when the user is typing fast.
async function cfHandleSearchFetch(q){
  const results = $('briefingChartFoxSearchResults'); if(!results) return;
  const seq = ++cfState.searchSeq;
  try{
    const r = await fetch(`/api/airports?q=${encodeURIComponent(q)}&limit=10`, { cache: 'no-store' });
    const data = await safeJsonResponse(r);
    if (seq !== cfState.searchSeq) return; // stale response
    const items = (data && Array.isArray(data.items)) ? data.items : [];
    console.info('[OPS ROOM][chartfox-search-result]', {
      query: q,
      source: '/api/airports',
      count: items.length,
      sample: items.slice(0, 3).map(it => ({ident: it.ident, name: it.name, country: it.country})),
    });
    if (!items.length){
      results.innerHTML = `<div class="cf-search-empty">NO MATCH FOR ${escapeHtml(q)}</div>`;
      results.hidden = false;
      return;
    }
    results.innerHTML = items.map(it => `<button type="button" class="cf-result" role="option" data-cf-pick-icao="${escapeHtml(it.ident || '')}" aria-selected="false"><b class="cf-result-icao">${escapeHtml(it.ident || '')}</b><span class="cf-result-name">${escapeHtml(it.name || '')}</span><small class="cf-result-meta">${escapeHtml(it.country || '')}${it.type ? ` \u00b7 ${escapeHtml(String(it.type).replace('_', ' '))}` : ''}</small></button>`).join('');
    results.hidden = false;
    results.style.display = 'block';
    const input = $('briefingChartFoxSearch');
    if (input) input.setAttribute('aria-expanded', 'true');
    results.querySelectorAll('.cf-result').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const icao = String(btn.dataset.cfPickIcao || '').toUpperCase();
        if (!icao) return;
        const input = $('briefingChartFoxSearch'); if(input) input.value = icao;
        cfLoadAirport(icao);
        cfHideSearchResults();
      });
    });
  }catch(error){
    if (seq !== cfState.searchSeq) return;
    results.innerHTML = `<div class="cf-search-empty">SEARCH FAILED<small>${escapeHtml((error && error.message) || '')}</small></div>`;
    results.hidden = false;
  }
}

function cfHideSearchResults(){
  const results = $('briefingChartFoxSearchResults');
  if (!results) return;
  results.hidden = true;
  results.innerHTML = '';
  results.style.display = '';
  const input = $('briefingChartFoxSearch');
  if (input) input.setAttribute('aria-expanded', 'false');
}

function cfLoadAirport(icao){
  console.info('[OPS ROOM][chartfox-load-airport]', {icao: String(icao || '').trim().toUpperCase()});
  const clean = String(icao || '').trim().toUpperCase().slice(0, 4);
  if (!clean) return;
  const panel = $('briefingChartFoxPanel');
  if (!panel) { cfHideSearchResults(); return; }
  // Cancel any in-flight search so the previous results don't repaint after navigation.
  cfState.searchSeq = (cfState.searchSeq || 0) + 1;
  if (cfState.searchDebounce) { clearTimeout(cfState.searchDebounce); cfState.searchDebounce = null; }
  cfHideSearchResults();
  // In-flight dedup is handled inside cfInitAirportCharts.
  return cfInitAirportCharts(panel, clean);
}

async function openChartFoxChart(chartId, icao, title){

  if(!viewer || !frame || !chartId) return;
  viewer.dataset.lastChartId = chartId;
  if(label) label.textContent = title || (icao + ' \u00b7 CHART');
  const proxyUrl = `/api/charts/chartfox/file/${encodeURIComponent(chartId)}`;
  frame.src = proxyUrl;
  viewer.hidden = false;
}
async function openAipChart(url,title,overlayAvailable,topLevelUrl='',georef=null){
const label=$('briefingChartOverlay'),overlay=document.querySelector('[data-cf-preview-overlay]');
  if(!viewer||!frame)return;
  if(briefingOwnshipTimer){clearInterval(briefingOwnshipTimer);briefingOwnshipTimer=null;}
  viewer.hidden=false;if(label)label.textContent=title||'CHART';frame.src=url;
  if(own)own.hidden=true;
  if(overlay)overlay.textContent=overlayAvailable?'LIVE POSITION OVERLAY ARMED':'PDF VIEW · GEO OVERLAY NOT AVAILABLE';

  // If chart has georeference data, compute ownship pixel position
  if(georef && overlayAvailable){
    const updateOwnship=async()=>{
      try{
        const frameRect=frame.getBoundingClientRect();
        const r=await fetch('/api/charts/overlay/compute',{
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({
            georeference:georef,
            display_width_px:frameRect.width,
            display_height_px:frameRect.height
          }),
          cache:'no-store'
        });
        const data=await r.json();
        if(data.ok){
          own.hidden=false;
          own.style.left=`${data.x_px}px`;
          own.style.top=`${data.y_px}px`;
          own.style.transform=`rotate(${data.heading_deg||0}deg) translate(-50%,-50%)`;
          if(overlay)overlay.textContent=`LIVE ${String(data.source||'SIM').toUpperCase()} ${Number(data.lat).toFixed(4)}, ${Number(data.lon).toFixed(4)} · OVERLAY ACTIVE`;
        }
      }catch(e){}
    };
    frame.onload=updateOwnship;
    briefingOwnshipTimer=setInterval(updateOwnship,2000);
  }else{
    // Fallback to basic telemetry overlay
    try{
      const r=await fetch('/api/charts/ownship',{cache:'no-store'});const data=await r.json();
      if(overlay)overlay.textContent=data.ok?`LIVE ${String(data.source||'SIM').toUpperCase()} ${Number(data.lat).toFixed(4)}, ${Number(data.lon).toFixed(4)} · OVERLAY ${overlayAvailable?'ARMED':'N/A'}`:'LIVE POSITION STANDBY';
    }catch{}
  }
  viewer.scrollIntoView({behavior:'smooth',block:'start'});
}

function metarAge(seconds){const value=Number(seconds);if(!Number.isFinite(value)||value<0)return 'AGE UNKNOWN';const minutes=Math.floor(value/60),hours=Math.floor(minutes/60);return hours?`${hours}h ${minutes%60}m ago`:`${minutes}m ago`}
function briefingWeatherCard(label, icao, data){
  const metar=data?.metar||{};const decoded=metar.decoded||{};const atis=data?.atis||data?.vatsim_atis||data?.realworld_atis||{};
  const metarRaw=metar.raw||metar.error||'METAR not available';
  let atisText='ATIS not available';
  if(atis?.available&&Array.isArray(atis.items)){
    atisText=atis.items.map(x=>`${x.callsign||'ATIS'} ${x.frequency||''} ${x.atis_code?`INFO ${x.atis_code}`:''}\n${x.text||''}`).join('\n\n');
  }else{
    atisText=atis.text||atis.error||'ATIS not available';
  }
  const atisSource=data?.atis_source==='VATSIM'||atis.source==='VATSIM'?'VATSIM ATIS':(atis.generated?'Generated ATIS':(atis.source||'ATIS'));
  const category=String(decoded.flight_category||metar.flight_category||'UNKNOWN').toUpperCase();
  const rows=[['Wind',decoded.wind],['Visibility',decoded.visibility],['Temperature',decoded.temperature],['Dew point',decoded.dewpoint],['Humidity',decoded.humidity],['Altimeter',decoded.altimeter]].filter(x=>x[1]&&x[1]!=='Not reported');
  const details=rows.length?rows.map(([name,value])=>`<div><span>${escapeHtml(name)}</span><b>${escapeHtml(value)}</b></div>`).join(''):'<div><span>Decoded METAR</span><b>Not available</b></div>';
  return `<article class="briefing-weather-card"><div class="briefing-weather-title"><h3>${escapeHtml(label)} ${escapeHtml(icao||'----')}</h3><small>${escapeHtml(metar.source||'METAR')}</small></div><div class="metar-status"><span class="metar-category ${escapeHtml(category.toLowerCase())}"><i></i>${escapeHtml(category)}</span><time>${escapeHtml(metarAge(decoded.age_seconds??metar.age_seconds))}</time></div><pre class="metar-raw">${escapeHtml(metarRaw)}</pre><div class="metar-details">${details}</div><div class="briefing-atis-block"><span>${escapeHtml(atisSource)}</span><pre>${escapeHtml(atisText)}</pre></div></article>`;
}

async function refreshBriefingWeather(force=false){
  if(!flightPlan?.ok||activePage!=='briefing')return;
  const airports=[['DEP',flightPlan.origin?.icao],['ARR',flightPlan.destination?.icao]].filter(x=>x[1]);
  if(!airports.length)return;
  try{
    const rows=await Promise.all(airports.map(async ([label,icao])=>[label,icao,await fetch(`/api/weather/${encodeURIComponent(icao)}?force_refresh=${force?'true':'false'}`,{cache:'no-store'}).then(r=>r.json())]));
    if($('briefingLiveWeather'))$('briefingLiveWeather').innerHTML=rows.map(([label,icao,data])=>briefingWeatherCard(label,icao,data)).join('');
    if($('briefingWeatherUpdated'))$('briefingWeatherUpdated').textContent=`UPDATED ${new Date().toISOString().slice(11,16)}Z · AUTO 5 MIN`;
  }catch(error){if($('briefingWeatherUpdated'))$('briefingWeatherUpdated').textContent=`WEATHER STANDBY: ${friendlyError(error.message)}`}
}
function startBriefingWeatherTimer(){
  if(briefingWeatherTimer){clearInterval(briefingWeatherTimer);briefingWeatherTimer=null}
  if(activePage==='briefing'){refreshBriefingWeather(false);briefingWeatherTimer=setInterval(()=>refreshBriefingWeather(true),5*60*1000)}
}
async function loadFlight(force=false){
  const buttons = [$('refreshFlight'),$('briefingRefresh'),$('systemFetchSimbrief')].filter(Boolean);
  buttons.forEach(button => {button.disabled=true; button.dataset.label=button.textContent; button.textContent='FETCHING...';});
  if($('simbriefFetchState')) $('simbriefFetchState').textContent = 'CONTACTING SIMBRIEF';
  try{
    const response = await fetch(`/api/simbrief/latest?force_refresh=${force?'true':'false'}&sync_fenix=false`,{cache:'no-store'});
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    flightPlan = await response.json();
    // v0.25.60: wrap every downstream render + side-effect with _safeRender so a
    // single throwing helper surfaces the actual culprit via the on-page trace
    // badge + /api/frontend/log, instead of aborting loadFlight and leaving the
    // Status Board showing the generic JS error message.
    _safeRender('renderActiveFlight', ()=>renderActiveFlight(flightPlan));
    _safeRender('renderBriefing', ()=>renderBriefing(flightPlan));
    if($('simbriefFetchState')) $('simbriefFetchState').textContent = flightPlan.ok ? 'OFP LOADED' : 'FETCH FAILED';
    _safeRender('loadSummary', ()=>bg(()=>loadSummary(false)));
    _safeRender('applyAirlineTheme', ()=>bg(()=>applyAirlineTheme()));
  }catch(error){
    _captureError('loadFlight.catch', error);
    const failure = {ok:false,state:'fault',reason:error.message};
    _safeRender('renderActiveFlight.failure', ()=>renderActiveFlight(failure));
    _safeRender('renderBriefing.failure', ()=>renderBriefing(failure));
    if($('simbriefFetchState')) $('simbriefFetchState').textContent = 'FETCH FAILED';
  }finally{
    buttons.forEach(button => {button.disabled=false; button.textContent=button.dataset.label || 'FETCH OFP';});
  }
}


async function saveAutoFetchOfpSetting(){
  if(!settings)return;
  try{const enabled=!!$('autoFetchOfpToggle')?.checked;const r=await fetch('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({integrations:{simbrief_auto_load:enabled}})});const d=await safeJsonResponse(r);settings=d.settings||settings;showToast('SIMBRIEF','AUTO-FETCH OFP '+(enabled?'ENABLED':'DISABLED'),'Preference saved','information')}
  catch(e){showToast('SIMBRIEF','AUTO-FETCH SAVE FAILED',friendlyError(e.message),'critical')}
}

function renderAirlineBrandingSettings(data=airlineBrandingState){
  if(!$('airlineBrandingState'))return;
  const brand=data||resolvedAirlineBranding(flightPlan);
  $('airlineBrandingState').innerHTML=brand?`${airlineBrandHtml(brand,'medium',true)}<span>${brand.custom_filename?`Custom logo: ${escapeHtml(brand.custom_filename)}`:(brand.logo_available?'Packaged airline logo ready':'Monogram fallback')}</span>`:'<span>Airline branding disabled</span>';
  if($('airlineLogoRemove'))$('airlineLogoRemove').disabled=!data?.custom_logo_available&&!data?.custom_filename;
}
async function saveAirlineBrandingSetting(){
  const enabled=$('airlineBrandingToggle')?.checked!==false;
  const override=cleanAirlineCode($('airlineIcaoOverride')?.value);
  try{
    const r=await fetch('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({interface:{airline_branding_enabled:enabled,airline_icao_override:override}})});
    const d=await safeJsonResponse(r);settings=d.settings||settings;
    await loadAirlineBranding();renderAirlineBrandingSettings();
    renderActiveFlight(flightPlan||null);renderBriefing(flightPlan||null);
    showToast('SETTINGS','AIRLINE BRANDING SAVED',enabled?'Airline logos and monograms are active.':'Airline branding is disabled.','information');
  }catch(e){showToast('SETTINGS','AIRLINE BRANDING SAVE FAILED',friendlyError(e.message),'critical')}
}
async function uploadAirlineLogo(file){
  if(!file)return;if(file.size>2*1024*1024){showToast('AIRLINE BRANDING','LOGO TOO LARGE','Maximum size is 2 MB.','critical');return}
  const reader=new FileReader();reader.onload=async()=>{try{const r=await fetch('/api/airline-branding/logo',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:file.name,data_url:reader.result})});airlineBrandingState=await safeJsonResponse(r);renderAirlineBrandingSettings();renderActiveFlight(flightPlan||null);renderBriefing(flightPlan||null)}catch(e){showToast('AIRLINE BRANDING','LOGO UPLOAD FAILED',friendlyError(e.message),'critical')}};reader.readAsDataURL(file)
}
async function removeAirlineLogo(){try{airlineBrandingState=await safeJsonResponse(await fetch('/api/airline-branding/logo',{method:'DELETE'}));renderAirlineBrandingSettings();renderActiveFlight(flightPlan||null);renderBriefing(flightPlan||null)}catch(e){showToast('AIRLINE BRANDING','LOGO REMOVE FAILED',friendlyError(e.message),'critical')}}

async function saveFinanceCareerSetting(){
  if(!settings)return;
  const enabled=!!$('financeCareerToggle')?.checked;
  try{
    const r=await fetch('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({interface:{finance_career_enabled:enabled}})});
    const d=await safeJsonResponse(r);
    settings=d.settings||settings;
    applyModuleVisibility();
    renderModuleVisibilityGrid();
    if(!enabled&&activePage==='finances')showPage('home');
    showToast('SETTINGS',enabled?'FINANCE & CAREER ENABLED':'FINANCE & CAREER DISABLED',enabled?'Career history and PIREP finance are active.':'Existing career history is preserved.','information');
  }catch(e){
    if($('financeCareerToggle'))$('financeCareerToggle').checked=!enabled;
    showToast('SETTINGS','COULD NOT SAVE FINANCE SETTING',friendlyError(e.message),'critical');
  }
}

function applyDeviceScale(value){
  const allowed = ['auto','standard','large','tv'];
  const scale = allowed.includes(value) ? value : 'auto';
  if(scale === 'auto') document.documentElement.removeAttribute('data-display');
  else document.documentElement.dataset.display = scale;
  localStorage.setItem('opsroom-device-scale',scale);
  if($('deviceScale')) $('deviceScale').value = scale;
}

function renderHostConfiguration(data=summary){
  if(!$('hostConfigRows') || !data) return;
  const rows=[
    ['VATSIM IDENTITY',data.integrations?.vatsim?.label || 'NOT SET',stateLamp(data.integrations?.vatsim)],
    ['SIMBRIEF',data.integrations?.simbrief?.label || 'NOT SET',stateLamp(data.integrations?.simbrief)],
    ['HOPPIE',data.integrations?.hoppie?.label || 'NOT SET',stateLamp(data.integrations?.hoppie)],
    ['GSX PRO',data.integrations?.gsx?.label || 'NOT DETECTED',stateLamp(data.integrations?.gsx)],
  ];
  $('hostConfigRows').innerHTML=rows.map(([name,label,lamp])=>`<div><i class="status-lamp lamp-${lamp}"></i><span><b>${escapeHtml(name)}</b><small>${escapeHtml(label)}</small></span></div>`).join('');
}

function fillSettings(data){
  settings = data;
  applyDeviceScale(localStorage.getItem('opsroom-device-scale') || 'auto');if($('hoppieType'))$('hoppieType').value='telex';
  setTerminalHomeStyle(terminalHomeStyle());
  renderEfbHomeStatus();
  if($('autoFetchOfpToggle')) $('autoFetchOfpToggle').checked = data?.integrations?.simbrief_auto_load !== false;
  if($('financeCareerToggle')) $('financeCareerToggle').checked = data?.interface?.finance_career_enabled !== false;
  if($('airlineBrandingToggle')) $('airlineBrandingToggle').checked = data?.interface?.airline_branding_enabled !== false;
  if($('airlineIcaoOverride')) $('airlineIcaoOverride').value = data?.interface?.airline_icao_override || '';
  loadAirlineBranding().then(renderAirlineBrandingSettings);
  if($('groundDepartureCatering')) $('groundDepartureCatering').checked = data?.integrations?.gsx_departure_catering !== false;
  if($('groundDepartureWater')) $('groundDepartureWater').checked = data?.integrations?.gsx_departure_water !== false;
  if($('groundPreferenceState')) $('groundPreferenceState').textContent = 'SAVED';
  applyModuleVisibility();
  renderModuleVisibilityGrid();
  const localHost=['127.0.0.1','localhost','::1'].includes(location.hostname);
  if($('openHostSetup')) $('openHostSetup').hidden=!localHost;
  if($('hostAccessNote')) $('hostAccessNote').textContent=localHost?'Open the desktop host setup to change accounts and integrations.':'Protected settings can only be changed on the simulator computer.';
}

async function loadSettings(){
  const response = await fetch('/api/settings/public',{cache:'no-store'});
  if(!response.ok) throw new Error(`Settings HTTP ${response.status}`);
  fillSettings(await response.json());
}

function renderTerminalAddresses(){
  if(!terminalServerInfo||!$('serverUrls'))return;
  const data=terminalServerInfo,cls=terminalIpVisible?'secret-value revealed':'secret-value concealed';
  const qrCls=terminalIpVisible?'secret-qr revealed':'secret-qr concealed';
  const urls=[`LOCAL: ${data.local_url}`,...data.lan_urls.map(url=>`LAN: ${url}`)];
  $('serverUrls').innerHTML=`<span>AVAILABLE ADDRESSES</span>${urls.map(url=>`<b class="${cls}">${escapeHtml(url)}</b>`).join('')}`;
  if($('serverQr')) $('serverQr').className=qrCls;
  if($('terminalToggleIp')){$('terminalToggleIp').textContent=terminalIpVisible?'HIDE IP':'SHOW IP';$('terminalToggleIp').setAttribute('aria-pressed',terminalIpVisible?'true':'false')}
  $('qrCaption').textContent=data.tablet_ready?(terminalIpVisible?`Open ${data.preferred_url} from the same network.`:'Reveal the address and QR code when you are ready to connect another terminal.'):'Enable LAN / tablet access from the OPS ROOM desktop host, then restart the host.';
}

async function loadServerInfo(){
  try{
    const data = await fetch('/api/server/info',{cache:'no-store'}).then(r=>r.json());
    terminalServerInfo=data;
    $('lanStateLabel').textContent = data.tablet_ready ? 'TABLET READY' : (data.lan_enabled ? 'NO LAN ADDRESS' : 'LOCAL ONLY');
    renderTerminalAddresses();
    $('serverQr').src = `/api/server/qr.png?t=${Date.now()}`;
  }catch(error){
    $('lanStateLabel').textContent = 'FAULT';
    $('serverUrls').innerHTML = `<span>SERVER INFORMATION</span><b>${escapeHtml(friendlyError(error.message))}</b>`;
  }
}


function formatMinutes(value){
  const total = Number(value);
  if(!Number.isFinite(total)) return '---';
  const h = Math.floor(total / 60);
  const m = Math.round(total % 60);
  return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}`;
}

async function loadDispatchContext(){
  try{
    const [contextResponse, activeResponse] = await Promise.all([fetch('/api/dispatch/context',{cache:'no-store'}), fetch('/api/dispatch/active',{cache:'no-store'})]);
    if(!contextResponse.ok) throw new Error(`HTTP ${contextResponse.status}`);
    dispatchContextData = await contextResponse.json();
    if(activeResponse.ok) activeDispatchRoute = (await activeResponse.json()).route || null;
    const msfs = dispatchContextData.msfs?.airport?.ident;
    const sb = dispatchContextData.simbrief?.origin?.icao;
    $('dispatchUseMsfs').disabled = !msfs;
    $('dispatchUseSimbrief').disabled = !sb;
    $('dispatchSourceNote').textContent = sb ? `SIMBRIEF ${sb} AVAILABLE${msfs?` / MSFS ${msfs} AVAILABLE`:''}` : (msfs ? `MSFS ${msfs} AVAILABLE` : 'Enter a departure ICAO or connect MSFS.');
    $('dispatchOriginState').textContent = sb ? `SIMBRIEF ${sb}` : (msfs ? `MSFS ${msfs}` : 'MANUAL ICAO REQUIRED');
  }catch(error){
    $('dispatchSourceNote').textContent = `CONTEXT UNAVAILABLE: ${friendlyError(error.message)}`;
  }
}

function controllerText(rows){
  if(!rows?.length) return 'NO LOCAL ATC';
  return rows.slice(0,3).map(item=>`${item.callsign} ${item.frequency}`).join(' / ');
}

function simbriefDispatchUrl(row){
  const now=new Date(Date.now()+30*60*1000);
  const durationMinutes=Math.max(0,Number(row.estimated_minutes)||0);
  const months=['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
  const date=`${String(now.getUTCDate()).padStart(2,'0')}${months[now.getUTCMonth()]}${String(now.getUTCFullYear()).slice(-2)}`;
  const params=new URLSearchParams({
    orig:String(row.origin||''),
    dest:String(row.destination||''),
    type:String(row.simbrief?.type||dispatchContextData?.simbrief?.aircraft?.icao||'A320'),
    date,
    deph:String(now.getUTCHours()),
    depm:String(now.getUTCMinutes()),
    steh:String(Math.floor(durationMinutes/60)),
    stem:String(Math.round(durationMinutes%60)),
    units:unitPrefs().weight==='kg'?'KGS':'LBS',
    find_sidstar:'1',
    stepclimbs:'1',
    maps:'detail'
  });
  const current=dispatchContextData?.simbrief||{};
  const callsign=String(current.callsign||'').trim().toUpperCase();
  const match=callsign.match(/^([A-Z]{2,3})([0-9A-Z]+)$/);
  if(match){params.set('airline',match[1]);params.set('fltnum',match[2]);params.set('callsign',callsign)}
  const registration=current.aircraft?.registration;
  if(registration)params.set('reg',registration);
  if(row.simbrief?.route)params.set('route',row.simbrief.route);
  if(row.simbrief?.flight_level)params.set('fl',String(row.simbrief.flight_level));
  return `https://dispatch.simbrief.com/options/custom?${params.toString()}`;
}

function renderDispatch(data){
  dispatchLoaded = true;
  renderAirlineIdentity('dispatchAirlineIdentity',flightPlan,'medium',true,flightPlan?.callsign||'');
  if(!data?.ok){
    $('dispatchResultCount').textContent = 'SEARCH FAILED';
    $('dispatchResults').innerHTML = `<div class="dispatch-empty fault"><strong>NO ROUTES RETURNED</strong><p>${escapeHtml(data?.reason || 'Dispatch search failed.')}</p></div>`;
    return;
  }
  $('dispatchOriginState').textContent = `${data.origin.ident} / ${String(data.origin_source).toUpperCase()}`;
  $('dispatchNetworkState').textContent = data.network_update ? `VATSIM ${String(data.network_update).slice(11,16)}Z` : 'LIVE NETWORK';
  $('dispatchResultCount').textContent = `${String(data.results.length).padStart(2,'0')} ROUTES / ${data.candidate_count} CANDIDATES`;
  if(!data.results.length){
    $('dispatchResults').innerHTML = '<div class="dispatch-empty"><strong>NO MATCHES</strong><p>Widen the flight time or relax the ATC and weather filters.</p></div>';
    return;
  }
  $('dispatchResults').innerHTML = data.results.map((row,index)=>{
    const wx = row.weather?.raw || row.weather?.label || 'WEATHER UNAVAILABLE';
    const reasons = (row.reasons||[]).map(x=>`<span>${escapeHtml(x)}</span>`).join('');
    const selected = activeDispatchRoute?.origin === row.origin && activeDispatchRoute?.destination === row.destination ? ' selected' : '';
    return `<article class="dispatch-card${selected}" data-route-index="${index}">
      <div class="dispatch-score"><strong>${String(row.score).padStart(2,'0')}</strong><span>SCORE</span></div>
      <div class="dispatch-route"><span>${escapeHtml(row.origin)}</span><i>TO</i><b>${escapeHtml(row.destination)}</b><small>${escapeHtml(row.airport.name)}</small></div>
      <div class="dispatch-metrics">
        <div><span>FLIGHT TIME</span><b>${formatMinutes(row.estimated_minutes)}</b></div>
        <div><span>DISTANCE</span><b>${formatDistance(row.distance_nm)}</b></div>
        <div><span>TRAFFIC</span><b>${row.traffic.departures} DEP / ${row.traffic.arrivals} ARR</b></div>
        <div><span>ARRIVAL ATC</span><b>${escapeHtml(controllerText(row.controllers))}</b></div>
      </div>
      <div class="dispatch-weather"><span>METAR</span><b>${escapeHtml(wx)}</b></div>
      <div class="dispatch-reasons">${reasons || '<span>TIME MATCH</span>'}</div>
      ${(row.notam_alert&&row.notam_alert.length)?`<div class="dispatch-notam-alert"><span>NOTAM</span><b>${escapeHtml(row.notam_alert.join(' · '))}</b></div>`:''}
      <div class="dispatch-actions"><button type="button" data-select-route="${index}">SELECT ROUTE</button><a href="/vatsim-fids?airport=${encodeURIComponent(row.destination)}" target="_blank" rel="noreferrer">VIEW FIDS</a><a href="${escapeHtml(simbriefDispatchUrl(row))}" target="_blank" rel="noreferrer">OPEN SIMBRIEF</a></div>
    </article>`;
  }).join('');
  document.querySelectorAll('[data-select-route]').forEach(button=>button.addEventListener('click',()=>selectDispatchRoute(data.results[Number(button.dataset.selectRoute)])));
}

async function searchDispatch(force=false){
  const button = $('dispatchSearch');
  button.disabled = true; button.textContent = 'SEARCHING NETWORK...';
  $('dispatchResultCount').textContent = 'WORKING';
  try{
    const params = new URLSearchParams({
      origin: $('dispatchOrigin').value.trim().toUpperCase(),
      origin_source: dispatchSource,
      target_minutes: $('dispatchDuration').value,
      tolerance_minutes: '35',
      aircraft: $('dispatchAircraft').value,
      atc: $('dispatchAtc').value,
      weather: $('dispatchWeather').value,
      limit: '16',
      force_refresh: force ? 'true' : 'false',
    });
    const response = await fetch(`/api/dispatch/recommendations?${params}`,{cache:'no-store'});
    const data = await response.json();
    if(!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    renderDispatch(data);
  }catch(error){renderDispatch({ok:false,reason:error.message})}
  finally{button.disabled=false;button.textContent='SEARCH ROUTES'}
}

async function selectDispatchRoute(route){
  try{
    const response=await fetch('/api/dispatch/active',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(route)});
    const data=await response.json();
    if(!response.ok)throw new Error(data.detail||`HTTP ${response.status}`);
    activeDispatchRoute=data.route;
    document.querySelectorAll('.dispatch-card').forEach(card=>card.classList.toggle('selected',card.querySelector('.dispatch-route b')?.textContent===route.destination));
    $('dispatchResultCount').textContent=`SELECTED ${route.origin} TO ${route.destination}`;
  }catch(error){$('dispatchResultCount').textContent=`SELECT FAILED: ${friendlyError(error.message)}`}
}

// v0.25.60: Dispatch tab switching
function switchDispatchTab(tabName,evt){
  document.querySelectorAll('.dispatch-tab-btn').forEach(function(btn){btn.classList.remove('active');});
  if(evt&&evt.currentTarget)evt.currentTarget.classList.add('active');
  document.querySelectorAll('.dispatch-tab-content').forEach(function(content){content.style.display='none';});
  if(tabName==='active-plan'){
    var ap=document.getElementById('dispatch-tab-active-plan');
    if(ap)ap.style.display='block';
  }else if(tabName==='realworld-search'){
    var rs=document.getElementById('dispatch-tab-realworld-search');
    if(rs)rs.style.display='block';
  }
}

// v0.25.60: Real-world flight search via local FR24 + ADSBDB enrichment pipeline
function clearRealworldInputs(){
  var fields=['rw-origin','rw-dest','rw-callsign','rw-aircraft'];
  for(var i=0;i<fields.length;i++){
    var el=$(fields[i]);if(el)el.value='';
  }
}

async function performRealworldSearch(){
  var origin=($('rw-origin').value||'').trim().toUpperCase();
  var dest=($('rw-dest').value||'').trim().toUpperCase();
  var callsign=($('rw-callsign').value||'').trim().toUpperCase();
  var aircraft=($('rw-aircraft').value||'').trim().toUpperCase();
  var includeGA=$('rw-include-ga')?$('rw-include-ga').checked:false;
  var includeGliders=$('rw-include-gliders')?$('rw-include-gliders').checked:false;
  var container=$('rw-results-container');
  if(!container)return;
  container.innerHTML='<div class="rw-loading">Searching live flight data...</div>';
  try{
    var params=new URLSearchParams();
    if(origin)params.set('origin',origin);
    if(dest)params.set('destination',dest);
    if(callsign)params.set('callsign',callsign);
    if(aircraft)params.set('aircraft',aircraft);
    if(includeGA)params.set('include_ga','true');
    if(includeGliders)params.set('include_gliders','true');
    // v0.25.60: use local pipeline (full ADSBDB enrichment) and fall back to VPS
    var apiUrl=window.location.origin+'/api/v1/realworld/search?'+params.toString();
    var resp=await fetch(apiUrl,{method:'GET',headers:{'Accept':'application/json'}});
    if(!resp.ok)throw new Error('HTTP '+resp.status+': '+resp.statusText);
    var data=await resp.json();
    if(data.status==='success'&&data.flights&&data.flights.length>0){
      renderRealworldResults(data.flights);
    }else{
      container.innerHTML='<div class="rw-no-results">No active real-world departures found matching criteria.</div>';
    }
    clearRealworldInputs();
  }catch(err){
    clearRealworldInputs();
    console.error('Real-World Search Error:',err);
    container.innerHTML='<div class="rw-error">Real-world search error: '+err.message+'</div>';
  }
}

function renderRealworldResults(flights){
  var container=$('rw-results-container');
  if(!container)return;
  container.innerHTML='';
  flights.forEach(function(flight){
    // v0.25.60: temporary debug output to verify backend→frontend field contract
    console.log("REALWORLD FLIGHT CARD DATA", flight);
    var card=document.createElement('div');
    card.className='rw-flight-card';
    var cs=flight.callsign||'';
    var eobt=flight.eobt_utc||'';
    var origIcao=flight.origin||'';
    var destIcao=flight.destination||'';
    var origName=flight.origin_name||'';
    var destName=flight.destination_name||'';
    var airline=flight.airline_name||'';
    var actype=flight.aircraft_type||'';
    var reg=flight.registration||'';
    var altFt=Number(flight.altitude_ft);
    var fl=Number.isFinite(altFt)&&altFt>0?'FL'+String(Math.round(altFt/100)):'';
    var speed=Number(flight.speed_kt);
    var speedStr=Number.isFinite(speed)?Math.round(speed)+' kt':'';
    var status=flight.status||'';
    var trackingSrc=flight.tracking_source||'';
    var identitySrc=flight.identity_source||'';
    var canDispatch=flight.can_dispatch!==false;
    var canSimbrief=flight.can_simbrief!==false;

    // ── Route display ──
    var hasRoute=!!(origIcao||destIcao);
    var routeHtml='';
    if(hasRoute){
      var origDisplay=origIcao||'----';
      if(origName&&origName!==origIcao)origDisplay+=' ('+origName+')';
      var destDisplay=destIcao||'----';
      if(destName&&destName!==destIcao)destDisplay+=' ('+destName+')';
      routeHtml='<div class="rw-card-route">'+
        '<span>'+escapeHtml(origDisplay)+'</span>'+
        '<span class="rw-route-arrow">&#10132;</span>'+
        '<span>'+escapeHtml(destDisplay)+'</span>'+
      '</div>';
    }else{
      routeHtml='<div class="rw-card-route rw-route-unavailable"><span>Route unavailable</span></div>';
    }

    // ── Airline ──
    var airlineHtml=airline?'<div class="rw-card-airline">'+escapeHtml(airline)+'</div>':'';

    // ── Aircraft ──
    var aircraftParts=[];
    if(actype)aircraftParts.push(escapeHtml(actype));
    if(reg)aircraftParts.push(escapeHtml(reg));
    var aircraftHtml=aircraftParts.length?'<div class="rw-card-aircraft">'+aircraftParts.join(' \u00b7 ')+'</div>':'';

    // ── Telemetry ──
    var telemParts=[];
    if(fl)telemParts.push(fl);
    if(speedStr)telemParts.push(speedStr);
    if(status)telemParts.push(escapeHtml(status));
    var telemHtml=telemParts.length?'<div class="rw-card-telemetry">'+telemParts.join(' \u00b7 ')+'</div>':'';

    // ── Data sources ──
    var srcParts=[];
    if(trackingSrc)srcParts.push('Tracking: '+escapeHtml(trackingSrc));
    if(identitySrc)srcParts.push('Identity: '+escapeHtml(identitySrc));
    var srcHtml=srcParts.length?'<div class="rw-card-source">'+srcParts.join(' \u00b7 ')+'</div>':'';

    // ── Actions ──
    var actionsHtml='<div class="rw-card-actions">';
    if(canDispatch&&origIcao&&destIcao){
      actionsHtml+='<button class="btn-secondary" onclick="importToActiveDispatch(\''+escapeHtml(cs)+'\',\''+escapeHtml(origIcao)+'\',\''+escapeHtml(destIcao)+'\')">IMPORT TO DISPATCH</button>';
    }
    if(canSimbrief){
      actionsHtml+='<button class="btn-primary" onclick="launchSimBriefFromRW(\''+escapeHtml(cs)+'\',\''+escapeHtml(origIcao)+'\',\''+escapeHtml(destIcao)+'\',\''+escapeHtml(eobt)+'\',\''+escapeHtml(actype)+'\')">OPEN IN SIMBRIEF</button>';
    }
    actionsHtml+='</div>';

    card.innerHTML=
      '<div class="rw-card-header">'+
        '<span class="rw-callsign">'+(cs?escapeHtml(cs):'UNKNOWN')+'</span>'+
        (eobt?'<span class="rw-eobt">EOBT: '+escapeHtml(eobt)+' UTC</span>':'')+
      '</div>'+
      airlineHtml+
      routeHtml+
      aircraftHtml+
      telemHtml+
      srcHtml+
      actionsHtml;
    container.appendChild(card);
  });
}

function importToActiveDispatch(callsign,orig,dest){
  var elCallsign=$('dispatch-callsign');
  var elOrigin=$('dispatchOrigin');
  var elDest=$('dispatch-destination');
  if(elCallsign)elCallsign.value=callsign;
  if(elOrigin)elOrigin.value=orig;
  if(elDest)elDest.value=dest;
  switchDispatchTab('active-plan');
}

function launchSimBriefFromRW(callsign,orig,dest,eobt,actype){
  var match=callsign.match(/^([A-Z]{2,3})([0-9A-Z]+)$/);
  var airline=match?match[1]:'';
  var fltnum=match?match[2]:'';
  var params=new URLSearchParams();
  if(airline)params.set('airline',airline);
  if(fltnum)params.set('fltnum',fltnum);
  if(callsign)params.set('callsign',callsign);
  if(orig)params.set('orig',orig);
  if(dest)params.set('dest',dest);
  if(actype)params.set('basetype',actype);
  if(eobt)params.set('deptime',eobt.replace(':',''));
  window.open('https://dispatch.simbrief.com/options/custom?'+params.toString(),'_blank');
}

function watchValue(value,suffix=''){
  const number=Number(value);
  return Number.isFinite(number)?`${Math.round(number).toLocaleString()}${suffix}`:`---${suffix}`;
}
function fcuValue(ap,key,format){
  // v0.25.72 (#15): a raw 0 on an unset FCU field renders as "---", never as
  // a real 0. Only a locked mode (e.g. HDG engaged at exactly north) proves a
  // 0 is a genuine selection.
  const n=Number(ap[key]);
  if(!Number.isFinite(n))return '---';
  const modeKey={selected_altitude_ft:'ALT',selected_heading_deg:'HDG',selected_speed_kts:'SPD',selected_vertical_speed_fpm:'VS'}[key];
  if(n===0&&!(ap.modes||[]).includes(modeKey))return '---';
  return format(n);
}

function watchTime(value){
  if(!value)return '----Z';
  const d=new Date(value);
  return Number.isNaN(d.getTime())?'----Z':`${String(d.getUTCHours()).padStart(2,'0')}:${String(d.getUTCMinutes()).padStart(2,'0')}Z`;
}

function setInputUnlessEditing(id,value){
  const el=$(id);if(!el||document.activeElement===el||value==null)return;el.value=String(Math.round(Number(value)));
}
function renderFlightWatch(data){
  if(!data?.ok){
    $('watchLive').hidden=true;$('watchStandby').hidden=false;renderAirlineIdentity('watchAirlineIdentity',null);
    $('watchStandby').querySelector('header span:last-child').textContent='STANDBY';
    $('watchStandby').querySelector('p').textContent='Start Microsoft Flight Simulator and load a flight. OPS ROOM will connect automatically.';
    return;
  }
  $('watchStandby').hidden=true;$('watchLive').hidden=false;
  const t=data.telemetry||{}, f=data.flight||{}, ap=t.autopilot||{};
  renderAirlineIdentity('watchAirlineIdentity',{...f,airline_branding:flightPlan?.airline_branding||f.airline_branding},'small',true,[f.aircraft,f.registration].filter(Boolean).join(' · '));
  $('watchPhase').textContent=data.phase||'LIVE';
  $('watchOrigin').textContent=f.origin||'----';$('watchDestination').textContent=f.destination||'----';$('watchCallsign').textContent=f.callsign||'---';
  $('watchRemaining').textContent=f.remaining_nm==null?'---':formatDistance(f.remaining_nm);
  $('watchEta').textContent=watchTime(f.eta_utc);
  $('watchNearest').textContent=data.nearest_airport?`${data.nearest_airport.icao} ${formatDistance(data.nearest_airport.distance_nm)}`:'----';
  const progress=Number(f.progress);const pct=Number.isFinite(progress)?Math.max(0,Math.min(100,progress*100)):0;
  $('watchProgressBar').style.width=`${pct}%`;$('watchProgressText').textContent=Number.isFinite(progress)?`${Math.round(pct)}% COMPLETE`:'NO ROUTE DATA';
  const displayAltitude=t.indicated_altitude_ft??t.altitude_ft;
  const trueAltitude=Number(t.altitude_ft);
  const indicatedAltitude=Number(displayAltitude);
  const altitudeDetail=[];
  if(Number.isFinite(trueAltitude) && (!Number.isFinite(indicatedAltitude) || Math.abs(trueAltitude-indicatedAltitude)>50)) altitudeDetail.push(`TRUE ${formatAltitude(trueAltitude)}`);
  if(Number.isFinite(Number(t.agl_ft))) altitudeDetail.push(`AGL ${formatAltitude(t.agl_ft)}`);
  $('watchAltitude').textContent=formatAltitude(displayAltitude);
  $('watchAltitudeDetail').textContent=altitudeDetail.length?altitudeDetail.join(' · '):'ALTITUDE VALID';
  const tas=t.true_airspeed_kts??t.true_air_speed_kts??t.tas_kts;
  const mach=t.mach_number??t.mach;
  const airspeedDetail=[`GS ${formatSpeed(t.ground_speed_kts)}`];
  if(Number.isFinite(Number(tas))) airspeedDetail.push(`TAS ${formatSpeed(tas)}`);
  else if(Number.isFinite(Number(mach))) airspeedDetail.push(`M ${Number(mach).toFixed(2)}`);
  $('watchIas').textContent=formatSpeed(t.indicated_speed_kts);$('watchGs').textContent=airspeedDetail.join(' · ');
  const heading=Number(t.heading_deg), track=Number(t.track_deg);
  $('watchHeading').textContent=watchValue(t.heading_deg,'°');
  $('watchTrack').textContent=(Number.isFinite(heading)&&Number.isFinite(track)&&Math.abs((((track-heading+540)%360)-180))<=1.0)?'TRACK ALIGNED':`TRACK ${watchValue(t.track_deg,'°')}`;
  $('watchVs').textContent=formatVerticalSpeed(t.vertical_speed_fpm);
  $('watchGroundState').textContent=t.on_ground?'ON GROUND':'AIRBORNE';$('watchFuel').textContent=formatWeightFromLb(t.fuel_total_lb);
  const fuelFlow=t.fuel_flow_pph??t.fuel_flow_lb_per_hr??t.fuel_flow_lbs_per_hour??t.fuel_flow_total_pph;
  const endurance=t.fuel_endurance_minutes??t.endurance_minutes;
  const fuelDetail=[];
  if(Number.isFinite(Number(fuelFlow))) fuelDetail.push(`FF ${Math.round(Number(fuelFlow)).toLocaleString()} LB/H`);
  if(Number.isFinite(Number(endurance))) fuelDetail.push(`END ${Math.floor(Number(endurance)/60)}:${String(Math.round(Number(endurance)%60)).padStart(2,'0')}`);
  $('watchFuelDetail').textContent=fuelDetail.length?fuelDetail.join(' · '):'ON BOARD';
  $('watchAp').textContent=ap.ap1===true?'AP1 ON':ap.ap1===false?'OFF':ap.engaged===true?'MODE ACTIVE':'---';
  $('watchApModes').textContent=(ap.modes||[]).length?(ap.modes||[]).join(' / '):(ap.engagement_source==='active_modes'?'MODE DETECTED':'NO ACTIVE MODES');
  $('watchUpdated').textContent=watchTime(data.updated_utc);
  $('fcuAltitudeRead').textContent=fcuValue(ap,'selected_altitude_ft',formatAltitude);
  $('fcuHeadingRead').textContent=fcuValue(ap,'selected_heading_deg',v=>watchValue(v,'°'));
  $('fcuSpeedRead').textContent=fcuValue(ap,'selected_speed_kts',formatSpeed);
  $('fcuVsRead').textContent=fcuValue(ap,'selected_vertical_speed_fpm',formatVerticalSpeed);
  const support=ap.control_support||{},adapter=t.aircraft_adapter||{},adapterStatus=t.adapter_status||{};
  $('fcuSupportState').textContent=adapter.supported?`${adapter.label||adapter.key} · READ ONLY`:(support.label||'READ ONLY TARGETS');
  const notes=[];
  if(adapter.supported)notes.push(`${String(adapter.label||adapter.key).toUpperCase()} ADAPTER ${adapterStatus.active?'ACTIVE':'GENERIC FALLBACK'}`);
  if(adapter.supported&&!adapterStatus.lvar_offsets_installed)notes.push('ADD-ON LVAR MAPPINGS NOT INSTALLED. OPEN BLACK BOX TO INSTALL.');
  if(!f.origin||!f.destination)notes.push('LOAD A SIMBRIEF OFP FOR ROUTE PROGRESS');
  if(ap.engagement_source==='active_modes'&&!ap.master)notes.push('AP ENGAGEMENT DERIVED FROM ACTIVE MODES');
  if(data.phase==='APPROACH')notes.push('APPROACH PHASE DETECTED');
  if(data.stale)notes.push(`DATA HOLD ${data.stale_seconds||0} SEC`);
  $('watchNotes').innerHTML=(notes.length?notes:['LIVE TELEMETRY NORMAL']).map(text=>`<div><i class="status-lamp lamp-${text.includes('NORMAL')?'green':'amber'}"></i><span>${escapeHtml(text)}</span></div>`).join('');
}

async function loadFlightWatch(force=false){
  if(watchBusy)return;watchBusy=true;
  try{
    const response=await fetch(`/api/flight-watch?force_refresh=${force?'true':'false'}`,{cache:'no-store'});
    const data=await response.json();if(!response.ok)throw new Error(data.detail||`HTTP ${response.status}`);renderFlightWatch(data);
  }catch(error){renderFlightWatch({ok:false,reason:error.message})}
  finally{watchBusy=false}
}
function setWatchStreamState(state,label){
  const el=$('watchStreamState'); if(!el)return;
  const lamp=el.querySelector('i'); lamp.className=`status-lamp lamp-${state}`;
  el.lastChild.textContent=label;
}
function stopWatchPolling(){
  if(watchPollTimer){clearInterval(watchPollTimer);watchPollTimer=null}
  if(watchFallbackTimer){clearTimeout(watchFallbackTimer);watchFallbackTimer=null}
}
function startWatchPolling(){
  if(activePage!=='watch'||watchPollTimer)return;
  setWatchStreamState('amber','LIVE POLL 5 HZ');
  loadFlightWatch(false);
  watchPollTimer=setInterval(()=>{if(activePage==='watch')loadFlightWatch(false)},200);
}
function stopFlightWatchStream(){
  if(watchReconnectTimer){clearTimeout(watchReconnectTimer);watchReconnectTimer=null}
  stopWatchPolling();
  if(watchSocket){const socket=watchSocket;watchSocket=null;try{socket.close()}catch{}}
}
function startFlightWatchStream(){
  if(activePage!=='watch')return;
  if(watchReconnectTimer){clearTimeout(watchReconnectTimer);watchReconnectTimer=null}
  if(watchSocket){try{watchSocket.close()}catch{}watchSocket=null}
  setWatchStreamState('amber','CONNECTING LIVE');
  const scheme=location.protocol==='https:'?'wss':'ws';
  const socket=new WebSocket(`${scheme}://${location.host}/ws/flight-watch`); watchSocket=socket;
  watchFallbackTimer=setTimeout(()=>{if(socket.readyState!==WebSocket.OPEN)startWatchPolling()},2500);
  socket.onopen=()=>{stopWatchPolling();setWatchStreamState('green','LIVE 5 HZ')};
  socket.onmessage=event=>{try{const payload=JSON.parse(event.data);renderFlightWatch(payload);setWatchStreamState(payload.stale?'amber':'green',payload.stale?'DATA HOLD':'LIVE 5 HZ')}catch{}};
  socket.onerror=()=>{setWatchStreamState('amber','FALLBACK POLLING');startWatchPolling()};
  socket.onclose=()=>{if(watchSocket===socket)watchSocket=null;if(activePage==='watch'){startWatchPolling();watchReconnectTimer=setTimeout(startFlightWatchStream,5000)}};
}


function frequencyText(value){
  const number=Number(value);return Number.isFinite(number)?number.toFixed(3):'---.---';
}
function renderRadiosBase(data){
  const radios=data.radios||{};
  for(const radio of [1,2]){
    const row=radios[`com${radio}`]||{};
    $(`com${radio}Active`).textContent=frequencyText(row.active_mhz);
    $(`com${radio}Standby`).textContent=frequencyText(row.standby_mhz);
    $(`com${radio}Tx`).textContent=row.transmit?'TX':'RX';
    $(`com${radio}Tx`).classList.toggle('transmit',!!row.transmit);
  }
  const available=Object.keys(radios).length>0;
  $('networkRadioState').textContent=available?'SIMCONNECT LIVE':'SIMCONNECT STANDBY';
  const current=data.current_station;
  $('currentStation').textContent=current?`${current.callsign}  ${current.frequency}`:'NOT IDENTIFIED';
  $('currentStationDetail').textContent=current?`${current.radio} ACTIVE / ${current.facility||'ATC'}`:'No online controller matches the active COM frequencies.';if($('commsActiveFrequency'))$('commsActiveFrequency').textContent=`ACTIVE FREQUENCY: ${current?`${current.callsign} ${current.frequency}`:'ACTIVE COM FREQUENCY'}`;
  const next=data.next_station;
  nextSuggestedFrequency=next?.frequency||null;
  $('nextStation').textContent=next?`${next.callsign||'ATC'}  ${next.frequency}`:'NO SUGGESTION';
  $('nextStationDetail').textContent=next?(next.confirmed?`CONFIRMED FROM VPILOT MESSAGE: ${next.detail||''}`:`SUGGESTED: ${next.detail||''}`):'ATC instructions always take priority.';
  $('nextToCom1').disabled=!nextSuggestedFrequency;
  $('nextToCom2').disabled=!nextSuggestedFrequency;
}
async function tuneRadio(radio,frequency,target='standby'){
  const button=document.querySelector(`.radio-tune[data-radio="${radio}"]`);
  if(button){button.disabled=true;button.textContent='TUNING...'}
  try{
    const response=await fetchWithTimeout('/api/radios/tune',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({radio,frequency,target})},6000);
    const data=await safeJsonResponse(response);
    await loadNetwork(false);
    const pending=data.pending_readback&&!data.verified;
    notifyOps({source:'RADIO CONTROL',title:`COM${radio} ${target.toUpperCase()} ${pending?'SENT':'SET'}`,message:pending?`Frequency ${frequency} MHz sent, readback pending`:`Frequency ${frequency} MHz verified`,priority:'information',page:'network',tag:`tune-${radio}-${target}-${frequency}-${Date.now()}`});
  }catch(e){
    $('networkLiveState').textContent=`TUNE FAILED: ${friendlyError(e.message)}`;
  }finally{
    if(button){button.disabled=false;button.textContent='SET'}
  }
}

async function swapRadioControl(radio){
  const button=document.querySelector(`.radio-swap[data-radio="${radio}"]`);
  if(button){button.disabled=true;button.textContent='SWAPPING...'}
  try{
    const response=await fetch('/api/radios/swap',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({radio})});
    const data=await response.json();if(!response.ok)throw new Error(data.detail||`HTTP ${response.status}`);
    await loadNetwork(false);
  }catch(error){$('networkRadioState').textContent=`SWAP FAILED: ${friendlyError(error.message)}`}
  finally{if(button){button.disabled=false;button.textContent='SWAP'}}
}

function renderNetwork(data){
  networkLoaded=true;
  const identity=data.identity||{}, flight=data.flight||{};
  $('networkUpdate').textContent=data.network_update?`VATSIM ${String(data.network_update).slice(11,19)}Z`:'VATSIM LIVE DATA';
  $('networkIdentityState').textContent=identity.online?'ONLINE':identity.configured?'CID OFFLINE':'CID NOT SET';
  const identityLabel = identity.callsign || (streamerModeEnabled() && identity.cid ? 'VATSIM IDENTITY' : identity.cid) || 'NO IDENTITY';
  const cidValue = sensitiveValueHtml(identity.cid || '---', networkCidVisible, 'VATSIM CID');
  $('networkIdentity').innerHTML=`<div class="network-ident-main"><i class="status-lamp lamp-${identity.online?'green':identity.configured?'amber':'off'}"></i><strong>${escapeHtml(identityLabel)}</strong><span>${identity.online?'CONNECTED TO VATSIM':identity.configured?'NOT CURRENTLY ONLINE':'SET CID ON HOST'}</span></div><div class="network-register"><div><span>CID</span>${cidValue}</div><div><span>SERVER</span><b>${escapeHtml(identity.server||'---')}</b></div><div><span>ROUTE</span><b>${escapeHtml(flight.origin||'----')} TO ${escapeHtml(flight.destination||'----')}</b></div><div><span>AIRCRAFT</span><b>${escapeHtml(flight.aircraft||'---')}</b></div></div>`;
  const bridge=data.vpilot_bridge||{};
  $('networkVpilotState').textContent=bridge.label||'PLUGIN REQUIRED';
  $('networkVpilot').innerHTML=`<div class="network-ident-main"><i class="status-lamp lamp-${bridge.connected?'green':'amber'}"></i><strong>VPILOT BRIDGE</strong><span>${bridge.connected?'Online and ready':'Start or restart vPilot after installing the bridge'}</span></div>`;
  renderRadios(data);
  const stations=data.active_stations||[];
  $('networkStationCount').textContent=`${String(stations.length).padStart(2,'0')} STATIONS`;
  $('networkStations').innerHTML=stations.length?stations.map(controllerCard).join(''):'<div class="network-empty">NO CONTROLLERS MATCH THE ACTIVE ORIGIN, DESTINATION OR NEAREST AIRPORT</div>';
  const controllers=data.controllers||[];
  $('networkControllerCount').textContent=`${String(controllers.length).padStart(2,'0')} SHOWN / ${data.counts?.controllers||0} ONLINE`;
  $('networkControllers').innerHTML=controllers.length?controllers.map(controllerCard).join(''):'<div class="network-empty">NO CONTROLLERS MATCH THE FILTER</div>';
}
function controllerCard(row){
  const atis=(row.atis||[]).join(' ');
  return `<article class="network-controller${row.relevant?' relevant':''}"><div><strong>${escapeHtml(row.callsign)}</strong><span>${escapeHtml(row.facility)}</span></div><b>${escapeHtml(row.frequency||'---.---')}</b><small>${escapeHtml(row.name||'')}</small><div class="controller-tune"><button type="button" data-controller-frequency="${escapeHtml(row.frequency||'')}" data-radio="1">COM1 STBY</button><button type="button" data-controller-frequency="${escapeHtml(row.frequency||'')}" data-radio="2">COM2 STBY</button></div>${atis?`<p>${escapeHtml(atis)}</p>`:''}</article>`;
}
async function loadNetwork(force=false){
  $('networkRefresh').disabled=true;$('networkRefresh').textContent='REFRESHING...';
  try{
    const q=$('networkQuery')?.value.trim()||'';
    const [network,bridge]=await Promise.all([fetch(`/api/network?force_refresh=${force?'true':'false'}&q=${encodeURIComponent(q)}`,{cache:'no-store'}).then(async r=>{const d=await r.json();if(!r.ok)throw new Error(d.detail||`HTTP ${r.status}`);return d}),fetch('/api/vpilot/bridge/status',{cache:'no-store'}).then(r=>r.json())]);
    network.vpilot_bridge=bridge;renderNetwork(network);
  }catch(error){$('networkControllers').innerHTML=`<div class="network-empty fault">NETWORK UNAVAILABLE: ${escapeHtml(friendlyError(error.message))}</div>`}
  finally{$('networkRefresh').disabled=false;$('networkRefresh').textContent='REFRESH NETWORK'}
}

function messageTime(value){
  if(!value)return '--:--';const d=new Date(value);return Number.isNaN(d.getTime())?'--:--':d.toISOString().slice(11,16);
}
function notificationStore(){try{return JSON.parse(localStorage.getItem('opsroom-notifications-v2')||'[]')||[]}catch{return []}}
function saveNotifications(){localStorage.setItem('opsroom-notifications-v2',JSON.stringify(notificationItems.slice(-200)))}
function markNotificationsRead(){notificationItems=notificationItems.map(item=>({...item,read:true}));notificationUnread=0;saveNotifications();updateNotificationUi()}
function notificationSound(priority='operational'){
  if(settings?.interface?.notification_sound===false)return;
  try{const AudioContext=window.AudioContext||window.webkitAudioContext;if(!AudioContext)return;const ctx=new AudioContext();const osc=ctx.createOscillator(),gain=ctx.createGain();osc.frequency.value=priority==='critical'?880:priority==='atc'?700:520;gain.gain.setValueAtTime(.055,ctx.currentTime);gain.gain.exponentialRampToValueAtTime(.001,ctx.currentTime+.22);osc.connect(gain);gain.connect(ctx.destination);osc.start();osc.stop(ctx.currentTime+.23);osc.onended=()=>ctx.close()}catch{}
}
function updateNotificationUi(){
  $('notificationBadge').hidden=notificationUnread<=0;$('notificationBadge').textContent=notificationUnread>99?'99+':String(notificationUnread);if($('efbNotificationBadge')){$('efbNotificationBadge').hidden=notificationUnread<=0;$('efbNotificationBadge').textContent=notificationUnread>99?'99+':String(notificationUnread);}if($('efbModuleNotificationBadge')){$('efbModuleNotificationBadge').hidden=notificationUnread<=0;$('efbModuleNotificationBadge').textContent=notificationUnread>99?'99+':String(notificationUnread);}
  const rows=notificationItems.slice().reverse();$('notificationHistory').innerHTML=rows.length?rows.map(item=>`<article data-priority="${escapeHtml(item.priority||'operational')}"><div><time>${messageTime(item.time)}Z · ${escapeHtml(item.source||'OPS ROOM')}</time><strong>${escapeHtml(item.title||'NOTIFICATION')}</strong><p>${escapeHtml(item.message||'')}</p>${item.page?`<button type="button" data-notification-page="${escapeHtml(item.page)}">OPEN ${escapeHtml(String(item.page).toUpperCase())}</button>`:''}</div></article>`).join(''):'<div class="network-empty">NO NOTIFICATIONS</div>';
}
function flashDocumentTitle(title){clearInterval(notificationTitleTimer);const original='OPS ROOM | Operations Control Centre';let on=false;notificationTitleTimer=setInterval(()=>{document.title=on?original:`! ${title}`;on=!on},700);setTimeout(()=>{clearInterval(notificationTitleTimer);document.title=original},7000)}
function importantNotification(item){if(settings?.interface?.important_notifications_only===false)return true;const source=String(item?.source||'').toUpperCase();return item?.priority==='critical'||source.includes('VPILOT')||source.includes('HOPPIE')||source.includes('ATC HANDOFF')}
function notifyOps(item,{silent=false,read=false}={}){
  silent = true;
  if(!importantNotification(item))return;
  const normalized={id:item.id||`${Date.now()}-${Math.random().toString(16).slice(2)}`,time:item.time||new Date().toISOString(),source:item.source||'OPS ROOM',title:item.title||'NOTIFICATION',message:item.message||'',priority:item.priority||'operational',page:item.page||'status',persistent:!!item.persistent,tag:item.tag||'',read:read||!!item.read};
  if(notificationItems.some(x=>x.id===normalized.id||(normalized.tag&&x.tag===normalized.tag&&x.title===normalized.title)))return;
  notificationItems.push(normalized);notificationItems=notificationItems.slice(-200);if(!normalized.read)notificationUnread++;saveNotifications();updateNotificationUi();
  if(!silent){
    resetToastButtons();notificationToastAction='';$('opsToastSource').textContent=normalized.source;$('opsToastFrom').textContent=normalized.title;$('opsToastText').textContent=normalized.message;$('opsToast').dataset.priority=normalized.priority;$('opsToast').hidden=false;notificationToastPage=normalized.page;clearTimeout(notificationToastTimer);notificationToastTimer=setTimeout(()=>{$('opsToast').hidden=true},normalized.persistent?20000:10000);notificationSound(normalized.priority);flashDocumentTitle(normalized.title);
    if(normalized.priority==='critical'||normalized.priority==='atc')fetch('/api/host/attention',{method:'POST'}).catch(()=>{});
    if(settings?.interface?.notifications&&settings?.interface?.native_notifications!==false&&'Notification' in window&&Notification.permission==='granted'){try{new Notification(`${normalized.source}: ${normalized.title}`,{body:normalized.message,tag:normalized.tag||normalized.id,requireInteraction:normalized.priority==='critical'})}catch{}}
  }
}
async function pollNotifications(){try{const r=await fetch(`/api/notifications?after=${encodeURIComponent(lastServerNotificationId)}&limit=100`,{cache:'no-store'});const d=await r.json();for(const item of d.items||[])notifyOps(item);if(d.latest_id)lastServerNotificationId=d.latest_id}catch{}}
function toggleNotifications(event){if(event){event.preventDefault();event.stopPropagation()}const drawer=$('notificationDrawer');if(!drawer)return;const open=drawer.hidden;drawer.hidden=!open;if(open){markNotificationsRead();if(settings?.interface?.native_notifications!==false&&'Notification' in window&&Notification.permission==='default')Notification.requestPermission().catch(()=>{})}}
function closeNotifications(){if($('notificationDrawer'))$('notificationDrawer').hidden=true}
function bindNotificationButton(id){
  const button=$(id);if(!button)return;
  const handler=event=>{
    if(event.type==='click'&&button.dataset.opsLastPointer&&Date.now()-Number(button.dataset.opsLastPointer)<450){event.preventDefault();event.stopPropagation();return}
    if(event.type==='pointerdown')button.dataset.opsLastPointer=String(Date.now());
    toggleNotifications(event);
  };
  button.addEventListener('pointerdown',handler,{passive:false});
  button.addEventListener('click',handler);
}

let opsWakeLock=null;
let opsNoSleepVideo=null;
let opsNoSleepActive=false;
const OPS_NOSLEEP_MP4='data:video/mp4;base64,AAAAHGZ0eXBNNFYgAAACAGlzb21pc28yYXZjMQAAAAhmcmVlAAAGF21kYXTeBAAAbGliZmFhYyAxLjI4AABCAJMgBDIARwAAArEGBf//rdxF6b3m2Ui3lizYINkj7u94MjY0IC0gY29yZSAxNDIgcjIgOTU2YzhkOCAtIEguMjY0L01QRUctNCBBVkMgY29kZWMgLSBDb3B5bGVmdCAyMDAzLTIwMTQgLSBodHRwOi8vd3d3LnZpZGVvbGFuLm9yZy94MjY0Lmh0bWwgLSBvcHRpb25zOiBjYWJhYz0wIHJlZj0zIGRlYmxvY2s9MTowOjAgYW5hbHlzZT0weDE6MHgxMTEgbWU9aGV4IHN1Ym1lPTcgcHN5PTEgcHN5X3JkPTEuMDA6MC4wMCBtaXhlZF9yZWY9MSBtZV9yYW5nZT0xNiBjaHJvbWFfbWU9MSB0cmVsbGlzPTEgOHg4ZGN0PTAgY3FtPTAgZGVhZHpvbmU9MjEsMTEgZmFzdF9wc2tpcD0xIGNocm9tYV9xcF9vZmZzZXQ9LTIgdGhyZWFkcz02IGxvb2thaGVhZF90aHJlYWRzPTEgc2xpY2VkX3RocmVhZHM9MCBucj0wIGRlY2ltYXRlPTEgaW50ZXJsYWNlZD0wIGJsdXJheV9jb21wYXQ9MCBjb25zdHJhaW5lZF9pbnRyYT0wIGJmcmFtZXM9MCB3ZWlnaHRwPTAga2V5aW50PTI1MCBrZXlpbnRfbWluPTI1IHNjZW5lY3V0PTQwIGludHJhX3JlZnJlc2g9MCByY19sb29rYWhlYWQ9NDAgcmM9Y3JmIG1idHJlZT0xIGNyZj0yMy4wIHFjb21wPTAuNjAgcXBtaW49MCBxcG1heD02OSBxcHN0ZXA9NCB2YnZfbWF4cmF0ZT03NjggdmJ2X2J1ZnNpemU9MzAwMCBjcmZfbWF4PTAuMCBuYWxfaHJkPW5vbmUgZmlsbGVyPTAgaXBfcmF0aW89MS40MCBhcT0xOjEuMDAAgAAAAFZliIQL8mKAAKvMnJycnJycnJycnXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXiEASZACGQAjgCEASZACGQAjgAAAAAdBmjgX4GSAIQBJkAIZACOAAAAAB0GaVAX4GSAhAEmQAhkAI4AhAEmQAhkAI4AAAAAGQZpgL8DJIQBJkAIZACOAIQBJkAIZACOAAAAABkGagC/AySEASZACGQAjgAAAAAZBmqAvwMkhAEmQAhkAI4AhAEmQAhkAI4AAAAAGQZrAL8DJIQBJkAIZACOAAAAABkGa4C/AySEASZACGQAjgCEASZACGQAjgAAAAAZBmwAvwMkhAEmQAhkAI4AAAAAGQZsgL8DJIQBJkAIZACOAIQBJkAIZACOAAAAABkGbQC/AySEASZACGQAjgCEASZACGQAjgAAAAAZBm2AvwMkhAEmQAhkAI4AAAAAGQZuAL8DJIQBJkAIZACOAIQBJkAIZACOAAAAABkGboC/AySEASZACGQAjgAAAAAZBm8AvwMkhAEmQAhkAI4AhAEmQAhkAI4AAAAAGQZvgL8DJIQBJkAIZACOAAAAABkGaAC/AySEASZACGQAjgCEASZACGQAjgAAAAAZBmiAvwMkhAEmQAhkAI4AhAEmQAhkAI4AAAAAGQZpAL8DJIQBJkAIZACOAAAAABkGaYC/AySEASZACGQAjgCEASZACGQAjgAAAAAZBmoAvwMkhAEmQAhkAI4AAAAAGQZqgL8DJIQBJkAIZACOAIQBJkAIZACOAAAAABkGawC/AySEASZACGQAjgAAAAAZBmuAvwMkhAEmQAhkAI4AhAEmQAhkAI4AAAAAGQZsAL8DJIQBJkAIZACOAAAAABkGbIC/AySEASZACGQAjgCEASZACGQAjgAAAAAZBm0AvwMkhAEmQAhkAI4AhAEmQAhkAI4AAAAAGQZtgL8DJIQBJkAIZACOAAAAABkGbgCvAySEASZACGQAjgCEASZACGQAjgAAAAAZBm6AnwMkhAEmQAhkAI4AhAEmQAhkAI4AhAEmQAhkAI4AhAEmQAhkAI4AAAAhubW9vdgAAAGxtdmhkAAAAAAAAAAAAAAAAAAAD6AAABDcAAQAAAQAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAwAAAzB0cmFrAAAAXHRraGQAAAADAAAAAAAAAAAAAAABAAAAAAAAA+kAAAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAALAAAACQAAAAAAAkZWR0cwAAABxlbHN0AAAAAAAAAAEAAAPpAAAAAAABAAAAAAKobWRpYQAAACBtZGhkAAAAAAAAAAAAAAAAAAB1MAAAdU5VxAAAAAAALWhkbHIAAAAAAAAAAHZpZGUAAAAAAAAAAAAAAABWaWRlb0hhbmRsZXIAAAACU21pbmYAAAAUdm1oZAAAAAEAAAAAAAAAAAAAACRkaW5mAAAAHGRyZWYAAAAAAAAAAQAAAAx1cmwgAAAAAQAAAhNzdGJsAAAAr3N0c2QAAAAAAAAAAQAAAJ9hdmMxAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAALAAkABIAAAASAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAGP//AAAALWF2Y0MBQsAN/+EAFWdCwA3ZAsTsBEAAAPpAADqYA8UKkgEABWjLg8sgAAAAHHV1aWRraEDyXyRPxbo5pRvPAyPzAAAAAAAAABhzdHRzAAAAAAAAAAEAAAAeAAAD6QAAABRzdHNzAAAAAAAAAAEAAAABAAAAHHN0c2MAAAAAAAAAAQAAAAEAAAABAAAAAQAAAIxzdHN6AAAAAAAAAAAAAAAeAAADDwAAAAsAAAALAAAACgAAAAoAAAAKAAAACgAAAAoAAAAKAAAACgAAAAoAAAAKAAAACgAAAAoAAAAKAAAACgAAAAoAAAAKAAAACgAAAAoAAAAKAAAACgAAAAoAAAAKAAAACgAAAAoAAAAKAAAACgAAAAoAAAAKAAAAiHN0Y28AAAAAAAAAHgAAAEYAAANnAAADewAAA5gAAAO0AAADxwAAA+MAAAP2AAAEEgAABCUAAARBAAAEXQAABHAAAASMAAAEnwAABLsAAATOAAAE6gAABQYAAAUZAAAFNQAABUgAAAVkAAAFdwAABZMAAAWmAAAFwgAABd4AAAXxAAAGDQAABGh0cmFrAAAAXHRraGQAAAADAAAAAAAAAAAAAAACAAAAAAAABDcAAAAAAAAAAAAAAAEBAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAkZWR0cwAAABxlbHN0AAAAAAAAAAEAAAQkAAADcAABAAAAAAPgbWRpYQAAACBtZGhkAAAAAAAAAAAAAAAAAAC7gAAAykBVxAAAAAAALWhkbHIAAAAAAAAAAHNvdW4AAAAAAAAAAAAAAABTb3VuZEhhbmRsZXIAAAADi21pbmYAAAAQc21oZAAAAAAAAAAAAAAAJGRpbmYAAAAcZHJlZgAAAAAAAAABAAAADHVybCAAAAABAAADT3N0YmwAAABnc3RzZAAAAAAAAAABAAAAV21wNGEAAAAAAAAAAQAAAAAAAAAAAAIAEAAAAAC7gAAAAAAAM2VzZHMAAAAAA4CAgCIAAgAEgICAFEAVBbjYAAu4AAAADcoFgICAAhGQBoCAgAECAAAAIHN0dHMAAAAAAAAAAgAAADIAAAQAAAAAAQAAAkAAAAFUc3RzYwAAAAAAAAAbAAAAAQAAAAEAAAABAAAAAgAAAAIAAAABAAAAAwAAAAEAAAABAAAABAAAAAIAAAABAAAABgAAAAEAAAABAAAABwAAAAIAAAABAAAACAAAAAEAAAABAAAACQAAAAIAAAABAAAACgAAAAEAAAABAAAACwAAAAIAAAABAAAADQAAAAEAAAABAAAADgAAAAIAAAABAAAADwAAAAEAAAABAAAAEAAAAAIAAAABAAAAEQAAAAEAAAABAAAAEgAAAAIAAAABAAAAFAAAAAEAAAABAAAAFQAAAAIAAAABAAAAFgAAAAEAAAABAAAAFwAAAAIAAAABAAAAGAAAAAEAAAABAAAAGQAAAAIAAAABAAAAGgAAAAEAAAABAAAAGwAAAAIAAAABAAAAHQAAAAEAAAABAAAAHgAAAAIAAAABAAAAHwAAAAQAAAABAAAA4HN0c3oAAAAAAAAAAAAAADMAAAAaAAAACQAAAAkAAAAJAAAACQAAAAkAAAAJAAAACQAAAAkAAAAJAAAACQAAAAkAAAAJAAAACQAAAAkAAAAJAAAACQAAAAkAAAAJAAAACQAAAAkAAAAJAAAACQAAAAkAAAAJAAAACQAAAAkAAAAJAAAACQAAAAkAAAAJAAAACQAAAAkAAAAJAAAACQAAAAkAAAAJAAAACQAAAAkAAAAJAAAACQAAAAkAAAAJAAAACQAAAAkAAAAJAAAACQAAAAkAAAAJAAAACQAAAAkAAACMc3RjbwAAAAAAAAAfAAAALAAAA1UAAANyAAADhgAAA6IAAAO+AAAD0QAAA+0AAAQAAAAEHAAABC8AAARLAAAEZwAABHoAAASWAAAEqQAABMUAAATYAAAE9AAABRAAAAUjAAAFPwAABVIAAAVuAAAFgQAABZ0AAAWwAAAFzAAABegAAAX7AAAGFwAAAGJ1ZHRhAAAAWm1ldGEAAAAAAAAAIWhkbHIAAAAAAAAAAG1kaXJhcHBsAAAAAAAAAAAAAAAALWlsc3QAAAAlqXRvbwAAAB1kYXRhAAAAAQAAAABMYXZmNTUuMzMuMTAw';
function ensureNoSleepVideo(){
  if(opsNoSleepVideo)return opsNoSleepVideo;
  const video=document.createElement('video');
  video.setAttribute('muted','');video.muted=true;
  video.setAttribute('loop','');video.loop=true;
  video.setAttribute('playsinline','');video.setAttribute('webkit-playsinline','');
  video.setAttribute('aria-hidden','true');
  video.style.cssText='position:fixed;left:-1px;top:-1px;width:1px;height:1px;opacity:0;pointer-events:none;';
  const source=document.createElement('source');source.src=OPS_NOSLEEP_MP4;source.type='video/mp4';
  video.appendChild(source);
  (document.body||document.documentElement).appendChild(video);
  opsNoSleepVideo=video;
  return video;
}
function startNoSleepFallback(){
  const video=ensureNoSleepVideo();
  let attempt;
  try{attempt=video.play();}catch(error){attempt=Promise.reject(error);}
  if(attempt&&typeof attempt.then==='function'){
    attempt.then(()=>{opsNoSleepActive=true;setKeepAwakeState('active','Keep Awake active','Fallback video keep-awake active (non-secure context).');})
      .catch(error=>{opsNoSleepActive=false;const message=String(error?.name||'')==='NotAllowedError'?'User action required':friendlyError(error?.message||error?.name||'Keep Awake fallback failed');setKeepAwakeState('pending',message,message);});
  }else{opsNoSleepActive=true;setKeepAwakeState('active','Keep Awake active','Fallback video keep-awake active (non-secure context).');}
}
function stopNoSleepFallback(){opsNoSleepActive=false;if(opsNoSleepVideo){try{opsNoSleepVideo.pause();opsNoSleepVideo.removeAttribute('src');opsNoSleepVideo.load();}catch{}}}
function setKeepAwakeState(state,label,detail=''){keepAwakeState={state,label,detail};updateKeepAwakeUi()}
function updateKeepAwakeUi(){
  const buttons=['efbKeepAwake','efbModuleKeepAwake'].map(id=>$(id)).filter(Boolean);
  buttons.forEach(button=>{button.textContent=keepAwakeWanted?(keepAwakeState.state==='active'?'KEEP AWAKE ON':'KEEP AWAKE ...'):'KEEP AWAKE';button.classList.toggle('keep-awake-active',keepAwakeWanted&&keepAwakeState.state==='active');button.title=keepAwakeState.detail||keepAwakeState.label||''});
}
async function requestOpsWakeLock(userAction=false){
  if(!keepAwakeWanted&&!userAction)return;
  if(!('wakeLock' in navigator)||!window.isSecureContext){startNoSleepFallback();return}
  try{
    if(opsWakeLock){setKeepAwakeState('active','Keep Awake active','Screen Wake Lock is already active.');return}
    opsWakeLock=await navigator.wakeLock.request('screen');
    stopNoSleepFallback();
    setKeepAwakeState('active','Keep Awake active','Screen Wake Lock active.');
    opsWakeLock.addEventListener('release',()=>{opsWakeLock=null;if(keepAwakeWanted)setKeepAwakeState(document.visibilityState==='visible'?'pending':'off',document.visibilityState==='visible'?'User action required':'Keep Awake paused','Wake lock was released by the browser.');});
  }catch(error){
    startNoSleepFallback();
  }
}
async function releaseOpsWakeLock(){stopNoSleepFallback();try{if(opsWakeLock){const lock=opsWakeLock;opsWakeLock=null;await lock.release()}}catch{}setKeepAwakeState('off','Keep Awake off','')}
async function toggleKeepAwake(){keepAwakeWanted=!keepAwakeWanted;localStorage.setItem(KEEP_AWAKE_KEY,keepAwakeWanted?'1':'0');if(keepAwakeWanted)await requestOpsWakeLock(true);else await releaseOpsWakeLock()}
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'&&keepAwakeWanted)requestOpsWakeLock(false)});
window.addEventListener('focus',()=>{if(keepAwakeWanted)requestOpsWakeLock(false)});

function showPrivateMessageAlert(message){notifyOps({id:`vpilot-${message.id}`,source:'VPILOT PRIVATE MESSAGE',title:message.from||'ATC',message:message.message||'',priority:'atc',page:'network',tag:`vpilot-${message.id}`,persistent:true})}


function formatBytes(value){
  const n=Number(value)||0;
  if(n>=1024*1024*1024)return `${(n/(1024*1024*1024)).toFixed(2)} GB`;
  if(n>=1024*1024)return `${(n/(1024*1024)).toFixed(1)} MB`;
  if(n>=1024)return `${(n/1024).toFixed(0)} KB`;
  return `${Math.round(n)} B`;
}

function renderStorageStatus(data){
  const box=$('storageStatus');
  if(!box)return;
  const items=data?.items||{};
  const logs=items.logs?.bytes||0, diagnostics=items.diagnostics?.bytes||0, map=items.map_cache?.bytes||0, logbook=items.logbook?.bytes||0;
  box.className=`maintenance-box ${logs>1024*1024*1024?'waiting':'ready'}`;
  box.innerHTML=`<b>LOCAL STORAGE</b><p>Logs ${formatBytes(logs)} · Diagnostics ${formatBytes(diagnostics)} · Map cache ${formatBytes(map)} · Logbook ${formatBytes(logbook)}</p>`;
}

async function loadStorageStatus(){
  if(!$('storageStatus'))return;
  try{
    const response=await fetch('/api/diagnostics/storage',{cache:'no-store'});
    const data=await safeJsonResponse(response);
    renderStorageStatus(data);
  }catch(error){
    $('storageStatus').className='maintenance-box fault';
    $('storageStatus').innerHTML=`<b>LOCAL STORAGE</b><p>${escapeHtml(friendlyError(error.message))}</p>`;
  }
}

async function clearLocalStorage(mapCache=false){
  const message=mapCache?'Clear OPS ROOM logs, diagnostics ZIPs and map cache? Settings, secrets and logbook are preserved.':'Clear OPS ROOM logs and diagnostics ZIPs? Settings, secrets and logbook are preserved.';
  if(!(await uiConfirm(message, 'CLEAR')))return;
  try{
    const response=await fetch('/api/diagnostics/clear-local-cache',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({logs:true,diagnostics:true,map_cache:mapCache})});
    const data=await safeJsonResponse(response);
    renderStorageStatus(data.status);
    notifyOps({source:'OPS ROOM',title:'STORAGE CLEANED',message:`Recovered ${formatBytes(data.removed_bytes||0)} from local logs/cache.`,priority:'operational',page:'system'}, {read:true});
  }catch(error){alert(`Storage cleanup failed: ${friendlyError(error.message)}`)}
}

// -- Printer / Thermal POS Compatibility ----------------------------------
async function loadPrinterStatus(){
  const box=$('printerBox');
  if(!box)return;
  try{
    const resp=await fetch('/api/printer/status',{cache:'no-store'});
    const data=await safeJsonResponse(resp);
    const sel=$('printerSelect');
    if(sel&&data.printers&&data.printers.length){
      const cur=settings.printing?.printer_name||'';
      sel.innerHTML=data.printers.map(p=>`<option value="${escapeHtml(p)}"${p===cur?' selected':''}>${escapeHtml(p)}</option>`).join('');
    }
    const st=$('printerStatus');
    if(st)st.textContent=data.available?'PRINTER SYSTEM AVAILABLE -- '+(data.printers||[]).length+' PRINTER(S)':'PRINTER SYSTEM -- NONE DETECTED';
    if(st)st.className=data.available?'setting-good':'setting-fault';
  }catch(e){
    const st=$('printerStatus');
    if(st){st.textContent='PRINTER SYSTEM -- ERROR';st.className='setting-fault';}
  }
}

async function testPrinter(){
  const name=$('printerSelect')?.value;
  if(!name)return notifyOps({source:'OPS ROOM',title:'NO PRINTER',message:'Select a printer first.',priority:'operational',page:'system'},{read:true});
  const btn=$('printerTestBtn');
  if(btn)btn.textContent='PRINTING...';
  try{
    const resp=await fetch('/api/printer/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({printer_name:name})});
    const data=await safeJsonResponse(resp);
    const r=$('printerResult');
    if(r)r.textContent=data.success?'? TEST RECEIPT SENT':'? PRINT FAILED: '+(data.error||'unknown');
  }catch(e){
    const r=$('printerResult');
    if(r)r.textContent='? ERROR: '+friendlyError(e.message);
  }finally{if(btn)btn.textContent='TEST PRINT';}
}

function initPrinterSettings(){
  const enabled=$('printerEnabled');
  const cpdlc=$('printerCpdlcAuto');
  if(enabled)enabled.checked=settings.printing?.enabled===true;
  if(cpdlc)cpdlc.checked=settings.printing?.cpdlc_auto_print!==false;
  const sel=$('printerSelect');
  if(sel&&settings.printing?.printer_name)sel.value=settings.printing.printer_name;
  ['printerEnabled','printerCpdlcAuto','printerSelect'].forEach(id=>{
    const el=$(id);
    if(!el)return;
    el.addEventListener('change',()=>{
      if(!settings.printing)settings.printing={};
      settings.printing.enabled=$('printerEnabled')?.checked||false;
      settings.printing.cpdlc_auto_print=$('printerCpdlcAuto')?.checked!==false;
      settings.printing.printer_name=$('printerSelect')?.value||'';
      saveSettingsWithDebounce();
    });
  });
  loadPrinterStatus();
}

// v0.25.60: Virtual thermal receipt preview
async function previewPrinterReceipt(){
  const btn = $('printerPreviewBtn');
  if (btn) btn.textContent = 'GENERATING...';
  try {
    const kind = ($('printerPreviewKind') && $('printerPreviewKind').value) || 'cpdlc';
    const sample = kind === 'custom'
      ? 'OPS ROOM CUSTOM RECEIPT PREVIEW\n\nTYPE your own content here to check how it fits on an 80mm thermal roll.\n\nEND OF PREVIEW'
      : '';
    const resp = await fetch('/api/printer/preview', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({content: sample, type: kind})
    });
    if (!resp.ok) throw new Error('Preview API returned ' + resp.status);
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || 'Preview generation failed');
    const body = $('printerPreviewBody');
    if (body) body.innerHTML = data.html || '<p style="color:var(--muted);text-align:center;padding:2rem">No preview data</p>';
    const modal = $('printerPreviewModal');
    if (modal) modal.classList.add('open');
    _printerPreviewRaw = data.raw_lines || [];
  } catch (e) {
    notifyOps({source:'OPS ROOM',title:'PREVIEW FAILED',message:e.message||'Unknown error',priority:'operational',page:'system'},{read:true});
  }
  if (btn) btn.textContent = 'PREVIEW RECEIPT';
}

let _printerPreviewRaw = [];

function initPrinterPreviewModal(){
  const modal = $('printerPreviewModal');
  if (!modal || modal.dataset.previewInit === '1') return;
  modal.dataset.previewInit = '1';

  const close = function(){ modal.classList.remove('open'); };
  $('printerPreviewClose')?.addEventListener('click', close);
  $('printerPreviewCloseBtn')?.addEventListener('click', close);
  modal.addEventListener('click', function(e){ if (e.target === modal) close(); });

  $('printerPreviewCopyBtn')?.addEventListener('click', function(){
    const text = _printerPreviewRaw.join('\n');
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function(){
        const btn = $('printerPreviewCopyBtn');
        if (btn) { btn.textContent = 'COPIED!'; setTimeout(function(){ btn.textContent = 'COPY RAW TEXT'; }, 2000); }
      }).catch(function(){});
    }
  });

  $('printerPreviewBtn')?.addEventListener('click', previewPrinterReceipt);
}

function showUpdateAvailableToast(data){
  if(!data?.update_available||!data.manifest)return;
  const version=String(data.latest_version||'');
  if(lastUpdatePromptVersion===version)return;
  lastUpdatePromptVersion=version;
  pendingUpdateManifest=data.manifest;
  notificationToastAction='update-now';
  notificationToastPage='system';
  if($('opsToastSource'))$('opsToastSource').textContent='OPS ROOM UPDATE';
  if($('opsToastFrom'))$('opsToastFrom').textContent=`v${version} AVAILABLE`;
  if($('opsToastText'))$('opsToastText').textContent=data.message||'A new OPS ROOM update is available.';
  if($('opsToastOpen'))$('opsToastOpen').textContent='UPDATE NOW';
  if($('opsToastClose'))$('opsToastClose').textContent='LATER';
  if($('opsToast')){$('opsToast').dataset.priority='operational';$('opsToast').hidden=false;}
  clearTimeout(notificationToastTimer);
  notificationToastTimer=setTimeout(()=>{if($('opsToast'))$('opsToast').hidden=true;notificationToastAction='';},30000);
  notificationSound('operational');
  flashDocumentTitle(`OPS ROOM v${version} update`);
}

function resetToastButtons(){
  if($('opsToastOpen'))$('opsToastOpen').textContent='OPEN';
  if($('opsToastClose'))$('opsToastClose').textContent='DISMISS';
}
function hideOpsToast(){
  clearTimeout(notificationToastTimer);
  if($('opsToast'))$('opsToast').hidden=true;
  notificationToastAction='';
  notificationToastPage='status';
}
function clearUpdatePrompts(remoteVersion=''){
  pendingUpdateManifest=null;
  if(!remoteVersion||lastUpdatePromptVersion===String(remoteVersion))lastUpdatePromptVersion='';
  notificationItems=notificationItems.map(item=>String(item.tag||'').startsWith('update-')?{...item,read:true}:item);
  notificationUnread=notificationItems.filter(item=>!item.read).length;
  saveNotifications();
  updateNotificationUi();
  if(notificationToastAction==='update-now')hideOpsToast();
}

function renderUpdaterStatus(data){
  const box=$('updaterBox');
  if(!box)return;
  if(!data?.enabled){
    $('updaterState').textContent='DISABLED';
    box.className='maintenance-box waiting';
    box.innerHTML='<b>UPDATES DISABLED</b><p>Automatic update checks are disabled in settings.</p>';
    return;
  }
  const installed=data.installed_version||data.current_version||'';
  const remote=data.remote_version||data.latest_version||'';
  const manifestUrl=data.manifest_url||'';
  const decision=data.decision||'';
  if(data.update_available){
    $('updaterState').textContent=`v${data.latest_version} AVAILABLE`;
    const notes=data.release_notes_url?` <a href="${escapeHtml(data.release_notes_url)}" target="_blank" rel="noreferrer">Release notes</a>`:'';
    box.className='maintenance-box ready';
    box.innerHTML=`<b>OPS ROOM v${escapeHtml(data.latest_version)} AVAILABLE</b><p>${escapeHtml(data.message||'A newer OPS ROOM release is ready.')} ${notes}</p><dl class="update-diagnostics"><dt>INSTALLED</dt><dd>v${escapeHtml(installed)}</dd><dt>REMOTE</dt><dd>v${escapeHtml(remote)}</dd><dt>DECISION</dt><dd>${escapeHtml(decision||'update_available')}</dd><dt>MANIFEST</dt><dd>${escapeHtml(manifestUrl||'default')}</dd></dl><div class="inline-actions"><button id="updateNow" class="control-button primary-control" type="button">UPDATE NOW</button><button id="updateLater" class="control-button" type="button">LATER</button></div>`;
    $('updateNow')?.addEventListener('click',()=>startUpdate(data.manifest));
    $('updateLater')?.addEventListener('click',()=>{box.innerHTML='<b>UPDATE POSTPONED</b><p>You can check again from System when ready.</p>';$('updaterState').textContent='POSTPONED'});
  }else{
    $('updaterState').textContent='UP TO DATE';
    box.className='maintenance-box ready';
    box.innerHTML=`<b>OPS ROOM IS UP TO DATE</b><p>Installed version v${escapeHtml(installed)}. Remote version ${remote?`v${escapeHtml(remote)}`:'not reported'} is not newer.</p><dl class="update-diagnostics"><dt>INSTALLED</dt><dd>v${escapeHtml(installed)}</dd><dt>REMOTE</dt><dd>${remote?`v${escapeHtml(remote)}`:'--'}</dd><dt>DECISION</dt><dd>${escapeHtml(decision||'remote_not_newer')}</dd><dt>MANIFEST</dt><dd>${escapeHtml(manifestUrl||'default')}</dd></dl>`;
  }
}


async function loadStartupConsole(){
  const box = $('startupConsoleLog');
  if(!box) return;
  try{
    const response = await fetch('/api/system/console?lines=220',{cache:'no-store'});
    const data = await safeJsonResponse(response);
    box.textContent = (data.lines||[]).join('\n') || 'No startup log entries yet.';
    box.scrollTop = box.scrollHeight;
  }catch(error){
    box.textContent = `Startup console unavailable: ${friendlyError(error.message)}`;
  }
}

async function checkUpdates(force=false, quiet=false){
  if(!$('updaterBox'))return;
  try{
    $('updaterState').textContent='CHECKING';
    const response=await fetch(`/api/updater/status?force=${force?'true':'false'}`,{cache:'no-store'});
    const data=await safeJsonResponse(response);
    renderUpdaterStatus(data);
    if(data.update_available){notifyOps({source:'OPS ROOM UPDATE',title:`v${data.latest_version} AVAILABLE`,message:data.message||'A new OPS ROOM release is available. Update now or later from System.',priority:'operational',page:'system',persistent:true,tag:`update-${data.latest_version}`});if(quiet||activePage!=='system')showUpdateAvailableToast(data)}else{clearUpdatePrompts(data.remote_version||data.latest_version||'');}
  }catch(error){
    if(!quiet){
      $('updaterState').textContent='CHECK FAILED';
      $('updaterBox').className='maintenance-box fault';
      $('updaterBox').innerHTML=`<b>UPDATE CHECK FAILED</b><p>${escapeHtml(friendlyError(error.message))}</p>`;
    }
  }
}

async function startUpdate(manifest){
  if(!manifest||!(await uiConfirm('Download and install this OPS ROOM update now? The app will close, replace files, then restart.', 'INSTALL')))return;
  try{
    $('updaterState').textContent='DOWNLOADING';
    $('updaterBox').className='maintenance-box waiting';
    $('updaterBox').innerHTML='<b>DOWNLOADING UPDATE</b><p>Downloading and verifying the release package from GitHub. Do not close OPS ROOM.</p>';
    const prepared=await safeJsonResponse(await fetch('/api/updater/prepare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({manifest})}));
    $('updaterState').textContent='INSTALLING';
    $('updaterBox').innerHTML='<b>STARTING UPDATER</b><p>OPS ROOM will close now. A visible OPS ROOM Updater window will show install progress and restart the app automatically.</p>';
    await safeJsonResponse(await fetch('/api/updater/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({package:prepared.package,version:prepared.version,updater:prepared.updater})}));
  }catch(error){
    $('updaterState').textContent='FAILED';
    $('updaterBox').className='maintenance-box fault';
    $('updaterBox').innerHTML=`<b>UPDATE FAILED</b><p>${escapeHtml(friendlyError(error.message))}</p>`;
  }
}

function renderComms(data){
  const bridge=data.bridge||{};
  $('commsBridgeLabel').textContent=bridge.label||'PLUGIN REQUIRED';
  $('commsLiveState').querySelector('i').className=`status-lamp lamp-${bridge.connected?'green':'amber'}`;
  $('commsLiveState').lastChild.textContent=bridge.connected?(bridge.network_connected?'VPILOT ONLINE':'BRIDGE ONLINE'):'STANDBY';
  $('commsBridgeStatus').innerHTML=`<div class="network-ident-main"><i class="status-lamp lamp-${bridge.connected?'green':'amber'}"></i><strong>${escapeHtml(bridge.detail||'VPILOT BRIDGE')}</strong><span>${bridge.network_connected?'CONNECTED TO VATSIM':bridge.connected?'VPILOT IS NOT CONNECTED TO THE NETWORK':'INSTALL FROM DESKTOP HOST'}</span></div>`;
  const messages=(data.messages||[]).slice().reverse();
  $('commsMessageCount').textContent=`${messages.length} messages`;
  $('commsMessages').innerHTML=messages.length?messages.map(item=>{const radio=item.type==='radio_message';const peer=item.outbound?(radio?'FREQUENCY':item.to):(item.from||item.type.toUpperCase());return `<article class="comms-message ${item.outbound?'outbound':'inbound'} ${radio?'radio':''}"><time>${messageTime(item.received_utc)}Z</time><div><span>${radio?'RADIO':(item.outbound?'TO':'FROM')} ${escapeHtml(peer||'')}</span><p>${escapeHtml(item.message||item.type)}</p></div>${!item.outbound&&item.from&&!radio?`<button type="button" data-reply-to="${escapeHtml(item.from)}">REPLY</button>`:''}</article>`}).join(''):'<div class="network-empty">No vPilot messages received</div>';setCommsSendMode(commsSendMode);
  const privateMessages=(data.messages||[]).filter(item=>item.type==='private_message'&&!item.outbound);
  if(!vpilotInitialized){privateMessages.forEach(item=>knownPrivateMessageIds.add(item.id));vpilotInitialized=true}
  else privateMessages.forEach(item=>{if(!knownPrivateMessageIds.has(item.id)){knownPrivateMessageIds.add(item.id);showPrivateMessageAlert(item)}});
}
async function loadComms(force=false){
  try{
    const response=await fetch(`/api/vpilot/messages?limit=150&after_id=${force?0:lastVpilotEventId}`,{cache:'no-store'});
    const data=await response.json();if(!response.ok)throw new Error(data.detail||`HTTP ${response.status}`);
    const ids=(data.events||[]).map(item=>Number(item.id)||0);if(ids.length)lastVpilotEventId=Math.max(lastVpilotEventId,...ids);
    renderComms(data);
  }catch(error){$('commsSendState').textContent=`COMMS UNAVAILABLE: ${friendlyError(error.message)}`}
}
function startVpilotPolling(){
  if(vpilotPollTimer)return;vpilotPollTimer=setInterval(()=>loadComms(false),2000);loadComms(false);
}
function startVpilotStream(){
  if(vpilotReconnectTimer){clearTimeout(vpilotReconnectTimer);vpilotReconnectTimer=null}
  if(vpilotSocket){try{vpilotSocket.close()}catch{}vpilotSocket=null}
  const scheme=location.protocol==='https:'?'wss':'ws';
  const socket=new WebSocket(`${scheme}://${location.host}/ws/vpilot`);vpilotSocket=socket;
  socket.onopen=()=>{if(vpilotPollTimer){clearInterval(vpilotPollTimer);vpilotPollTimer=null}};
  socket.onmessage=event=>{try{const data=JSON.parse(event.data);const ids=(data.events||[]).map(item=>Number(item.id)||0);if(ids.length)lastVpilotEventId=Math.max(lastVpilotEventId,...ids);renderComms(data)}catch{}};
  socket.onerror=()=>startVpilotPolling();
  socket.onclose=()=>{if(vpilotSocket===socket)vpilotSocket=null;startVpilotPolling();vpilotReconnectTimer=setTimeout(startVpilotStream,5000)};
}
function currentCommsRadioTarget(){
  try{
    const active=$('currentStation')?.textContent||'';
    if(active&&!active.includes('NOT IDENTIFIED'))return active;
  }catch{}
  return 'ACTIVE COM FREQUENCY';
}
function setCommsSendMode(mode){
  commsSendMode=mode==='radio'?'radio':'private';
  const panel=document.querySelector('.comms-compose-panel');
  if(panel)panel.dataset.sendMode=commsSendMode;
  document.querySelectorAll('[data-comms-send-mode]').forEach(b=>b.classList.toggle('active',(b.dataset.commsSendMode||'private')===commsSendMode));
  if($('commsComposeTitle'))$('commsComposeTitle').textContent=commsSendMode==='radio'?'TUNED FREQUENCY':'PRIVATE MESSAGE';
  if($('commsRecipient'))$('commsRecipient').placeholder=commsSendMode==='radio'?'ACTIVE FREQUENCY':'RECIPIENT CALLSIGN';
  if($('commsSend'))$('commsSend').textContent=commsSendMode==='radio'?'TRANSMIT':'SEND';
  if($('commsActiveFrequency'))$('commsActiveFrequency').textContent=`ACTIVE FREQUENCY: ${currentCommsRadioTarget()}`;
}
async function sendCommsMessage(){
  const message=$('commsMessage').value.trim();
  if(!message){$('commsSendState').textContent='MESSAGE IS REQUIRED';return}
  const payload={message};
  let path='/api/vpilot/messages/send';
  if(commsSendMode==='radio'){
    path='/api/vpilot/messages/send-radio';
  }else{
    const to=$('commsRecipient').value.trim().toUpperCase();
    if(!to){$('commsSendState').textContent='RECIPIENT AND MESSAGE ARE REQUIRED';return}
    payload.to=to;
  }
  $('commsSend').disabled=true;$('commsSend').textContent='QUEUING...';
  try{const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const data=await response.json();if(!response.ok)throw new Error(data.detail||`HTTP ${response.status}`);$('commsSendState').textContent=commsSendMode==='radio'?'RADIO MESSAGE QUEUED FOR ACTIVE FREQUENCY':'MESSAGE QUEUED FOR VPILOT';$('commsMessage').value=''}catch(error){$('commsSendState').textContent=`SEND FAILED: ${friendlyError(error.message)}`}finally{$('commsSend').disabled=false;setCommsSendMode(commsSendMode)}
}
async function sendVpilotAction(action,enabled=null){
  try{const response=await fetch('/api/vpilot/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,enabled})});const data=await response.json();if(!response.ok)throw new Error(data.detail||`HTTP ${response.status}`);$('commsSendState').textContent=`${action.toUpperCase()} QUEUED`}catch(error){$('commsSendState').textContent=`ACTION FAILED: ${friendlyError(error.message)}`}
}


function baseMapStyle(feature,resolution){
  const kind=String(feature.get('pmap:kind')||feature.get('kind')||feature.get('class')||'').toLowerCase();
  const geom=feature.getGeometry()?.getType?.()||'';
  const name=String(feature.get('name')||feature.get('name:en')||'');
  if(geom.includes('Polygon')){
    if(kind.includes('water')||kind.includes('ocean')||kind.includes('lake')||kind.includes('river')) return new ol.style.Style({fill:new ol.style.Fill({color:'#101d25'})});
    if(kind.includes('park')||kind.includes('forest')||kind.includes('wood')) return new ol.style.Style({fill:new ol.style.Fill({color:'#202923'})});
    if(kind.includes('building')) return new ol.style.Style({fill:new ol.style.Fill({color:'#303236'})});
    return new ol.style.Style({fill:new ol.style.Fill({color:'#1b1d20'})});
  }
  if(geom.includes('Line')){
    const boundary=kind.includes('boundary');
    const major=/(motorway|trunk|primary|highway)/.test(kind);
    const water=kind.includes('river')||kind.includes('stream');
    return new ol.style.Style({stroke:new ol.style.Stroke({color:water?'#24475b':boundary?'#77736c':major?'#716d67':'#45474a',width:boundary?1.15:major?1.35:.7,lineDash:boundary?[5,4]:undefined})});
  }
  if(geom.includes('Point')&&name&&resolution<18000){
    const important=/(city|capital|state|country)/.test(kind);
    return new ol.style.Style({text:new ol.style.Text({text:name,font:`${important?'700':'400'} ${important?'11':'9'}px B612, Arial, sans-serif`,fill:new ol.style.Fill({color:important?'#d8d5cd':'#a7a6a1'}),stroke:new ol.style.Stroke({color:'#17191b',width:3}),overflow:false})});
  }
  return null;
}
function makeVectorLayer(style,zIndex,options={}){return new ol.layer.Vector({source:new ol.source.Vector(),style,zIndex,declutter:!!options.declutter,updateWhileAnimating:!!options.updateWhileAnimating,updateWhileInteracting:!!options.updateWhileInteracting})}
function planeIcon(color,outline='#101214'){
  const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 36 36"><path d="M18 2.5c1.3 0 2 1.1 2.1 3.1l.6 8.2 10.1 5.7v3l-10-2.5-.5 7.4 4.1 3v2.1L18 30.9l-6.4 1.6v-2.1l4.1-3-.5-7.4-10 2.5v-3l10.1-5.7.6-8.2c.1-2 0.8-3.1 2.1-3.1z" fill="${color}" stroke="${outline}" stroke-width="1.4" stroke-linejoin="round"/></svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}
const trafficPlaneIcon=planeIcon('#e9e5dc');
const ownPlaneIcon=planeIcon('#59c9df','#f3f0e8');
function trafficStyle(feature,own=false){
  const zoom=olMap?.getView()?.getZoom?.()||2;
  const label=String(feature.get('label')||'');
  return new ol.style.Style({
    image:new ol.style.Icon({src:own?ownPlaneIcon:trafficPlaneIcon,anchor:[.5,.5],rotation:Number(feature.get('heading')||0)*Math.PI/180,rotateWithView:true,scale:own?.78:.55}),
    text:new ol.style.Text({text:own||zoom>=6.2?label:'',offsetX:own?16:13,offsetY:1,textAlign:'left',font:`700 ${own?'12':'10'}px B612 Mono, Consolas, monospace`,fill:new ol.style.Fill({color:own?'#8de8f5':'#ece8df'}),stroke:new ol.style.Stroke({color:'#111315',width:4})})
  });
}
function controllerStyle(feature){
  const facility=Number(feature.get('facility')||0);
  const zoom=olMap?.getView()?.getZoom?.()||2;
  const radius=facility>=7?8:facility===6?7:6;
  const points=facility>=7?4:facility===6?6:20;
  return new ol.style.Style({
    image:new ol.style.RegularShape({points,radius,angle:Math.PI/4,fill:new ol.style.Fill({color:facility>=7?'#338eb8':'#3ba8c6'}),stroke:new ol.style.Stroke({color:'#d9f4fa',width:1.25})}),
    text:new ol.style.Text({text:zoom>=3.5?String(feature.get('label')||''):'',offsetX:10,textAlign:'left',font:'700 11px B612 Mono, Consolas, monospace',fill:new ol.style.Fill({color:'#8fdaea'}),stroke:new ol.style.Stroke({color:'#111315',width:4})})
  });
}
function coverageStyle(feature){
  const facility=Number(feature.get('facility')||0);
  const isCentre=facility>=7;
  return new ol.style.Style({fill:new ol.style.Fill({color:isCentre?'rgba(48,132,176,.09)':'rgba(65,166,190,.07)'}),stroke:new ol.style.Stroke({color:isCentre?'rgba(79,177,219,.70)':'rgba(82,190,211,.55)',width:isCentre?1.5:1,lineDash:isCentre?[8,5]:[4,5]})});
}
// v0.25.60: FAA NMS NOTAM layer styling -- FDC/TFR red, runway closures
// amber, obstacles orange, everything else blue. Respects mapNotamFilter.
let mapNotamFilter='all';
function notamStyle(feature){
  const classification=String(feature.get('classification')||'').toUpperCase();
  const qcode=String(feature.get('qcode')||'').toUpperCase();
  const geometry=feature.getGeometry()?.getType?.()||'';
  const isFdc=classification==='FDC'||qcode.startsWith('QRT');
  const isRwy=qcode.startsWith('QMR');
  const isObst=classification==='OBSTACLES'||qcode.startsWith('QOB')||/(CRANE|OBST)/.test(String(feature.get('text')||''));
  const isAirspace=qcode.startsWith('QRT')||qcode.startsWith('QTT');
  if(mapNotamFilter==='fdc'&&!isFdc)return null;
  if(mapNotamFilter==='rwy'&&!isRwy)return null;
  if(mapNotamFilter==='obst'&&!isObst)return null;
  if(mapNotamFilter==='nav'&&!(qcode.startsWith('QNV')||qcode.startsWith('QNA')))return null;
  if(mapNotamFilter==='airspace'&&!isAirspace)return null;
  const fill=isFdc?'rgba(224,60,52,.24)':isRwy?'rgba(240,190,60,.22)':isObst?'rgba(255,150,60,.30)':'rgba(90,170,220,.18)';
  const stroke=isFdc?'#ff5b52':isRwy?'#f0be3c':isObst?'#ff9640':'#5aaade';
  if(geometry.includes('Polygon')){
    return new ol.style.Style({fill:new ol.style.Fill({color:fill}),stroke:new ol.style.Stroke({color:stroke,width:isFdc?2.2:1.4,lineDash:isFdc?[8,5]:undefined})});
  }
  return new ol.style.Style({image:new ol.style.Circle({radius:isFdc?7:5,fill:new ol.style.Fill({color:stroke}),stroke:new ol.style.Stroke({color:'#0d1112',width:1.6})})});
}
// v0.25.60: fetch NMS GeoJSON NOTAMs around the current map viewport.
let mapNotamRequestSeq=0;
async function loadNotamLayer(){
  if(!olMap||!olNotamLayer)return;
  const src=olNotamLayer.getSource();if(!src)return;
  const on=mapLayerChecked('mapLayerNotams',false);
  if(!on){src.clear();if($('mapNotamFilters'))$('mapNotamFilters').hidden=true;return}
  if($('mapNotamFilters'))$('mapNotamFilters').hidden=false;
  const requestId=++mapNotamRequestSeq;
  const center=ol.proj.toLonLat(olMap.getView().getCenter());
  // Radius from the visible viewport diagonal (NM), capped to protect the
  // proxy -- so the layer stays in sync while panning/zooming.
  let radius=40;
  try{
    const parts=currentBboxParam().split(',').map(Number);
    if(parts.length===4&&parts.every(Number.isFinite)){
      const cLat=(parts[1]+parts[3])/2,cLon=(parts[0]+parts[2])/2;
      radius=Math.max(10,Math.min(200,Math.round(mapDistanceNm(cLat,cLon,parts[1],parts[2]))));
    }
  }catch{}
  updateMapAviationStatus('NOTAM LAYER LOADING');
  try{
    const r=await fetch(`/api/nms/notams?latitude=${Number(center[1]).toFixed(4)}&longitude=${Number(center[0]).toFixed(4)}&radius=${radius}`,{cache:'no-store'});
    const d=await safeJsonResponse(r);
    if(requestId!==mapNotamRequestSeq)return;
    if(!d?.ok){updateMapAviationStatus('NOTAM LAYER UNAVAILABLE');return}
    src.clear();
    const raw=Array.isArray(d.features)?d.features:[];
    const reader=new ol.format.GeoJSON();
    raw.forEach(item=>{
      let feature;
      try{feature=reader.readFeature(item,{dataProjection:'EPSG:4326',featureProjection:'EPSG:3857'})}catch{return}
      if(!feature)return;
      const props=item.properties||{};const core=props.coreNOTAMData||{};const notam=core.notam||{};
      const classification=String(notam.classification||props.classification||'').toUpperCase();
      const qcode=String(notam.selectionCode||props.selectionCode||'').toUpperCase();
      const text=String(notam.text||props.text||'');
      const ident=String(notam.number||notam.id||'NOTAM');
      const location=String(notam.icaoLocation||notam.location||props.icaoLocation||'');
      feature.set('classification',classification);
      feature.set('qcode',qcode);
      feature.set('text',text);
      feature.set('title',`${ident} · ${location||'NOTAM'}${classification?` [${classification}]`:''}`);
      feature.set('notamText',text);
      src.addFeature(feature);
    });
    olNotamLayer.changed();
    updateMapAviationStatus(`NOTAM LAYER: ${src.getFeatures().length} ACTIVE`);
  }catch(e){if(requestId===mapNotamRequestSeq)updateMapAviationStatus(`NOTAM LAYER LIMITED: ${friendlyError(e.message)}`)}
}
function applyMapNotamFilter(value){
  mapNotamFilter=String(value||'all');
  document.querySelectorAll('[data-notam-filter]').forEach(b=>b.classList.toggle('active',b.dataset.notamFilter===mapNotamFilter));
  olNotamLayer?.changed();
}

function mapLayerChecked(id,defaultValue=false){const el=$(id);return el?!!el.checked:!!defaultValue}
function syncMapNotamToggle(){const btn=$('mapNotamToggle');if(!btn)return;const on=mapLayerChecked('mapLayerNotams',false);btn.classList.toggle('active',on);btn.setAttribute('aria-pressed',on?'true':'false')}
// v0.25.65: runway/taxiway closure marker deployment control (Briefing ->
// NOTAMS). ARM deploys the current NOTAM-closure SimObject plan into MSFS
// (threshold X's + hold-short barrier lines); CLEAR ALL removes everything
// this session spawned. The map keeps its NOTAM overlay; this control is the
// in-sim deployment arm, not a map layer.
let closureDeployBusy = false;
let closureDeployState = {enabled:false, plan:null, spawn:null, lastError:''};
function closureDeploySetStatus(text){
  const status=$('closureDeployStatus');
  if(status && status.textContent!==String(text||''))status.textContent=String(text||'');
}
async function refreshClosureDeploy(forceDeploy=false){
  if(closureDeployBusy)return;
  const toggle=$('closureDeployToggle');
  if(!toggle)return;
  closureDeployBusy=true;
  try{
    const data=await safeJsonResponse(await fetch('/api/simobjects/notam-closures',{cache:'no-store'}));
    closureDeployState={enabled:!!data?.enabled,plan:data?.plan||null,spawn:data?.spawn||null};
    // v0.25.65: auto-deploy config + Community package install status readout.
    let cfg={};
    try{
      cfg=await safeJsonResponse(await fetch('/api/simobjects/install-status',{cache:'no-store'}));
      const instEl=$('closureDeployInstall');
      if(instEl){
        const folders=Array.isArray(cfg?.community_folders)?cfg.community_folders:[];
        const detected=folders.filter(f=>f?.exists);
        const installed=folders.filter(f=>f?.exists&&f?.installed);
        if(detected.length&&installed.length<detected.length){
          instEl.hidden=false;
          instEl.textContent=`PACKAGE: ${installed.length}/${detected.length} COMMUNITY FOLDERS HAVE CLOSURE MARKERS — REINSTALL`;
        }else{
          instEl.hidden=true;
        }
      }
    }catch(err){/* config readout is best-effort */}
    const plan=closureDeployState.plan,spawn=closureDeployState.spawn;
    const placed=Array.isArray(plan?.placed)?plan.placed.length:0;
    const enabled=!!data?.enabled;
    const radius=Number(cfg?.auto_deploy_radius_nm ?? data?.radius_nm ?? 50);
    const gate=Number(cfg?.auto_deploy_altitude_gate_ft ?? 15000);
    toggle.classList.toggle('active',enabled);
    toggle.setAttribute('aria-pressed',enabled?'true':'false');
    toggle.textContent=enabled?'DEPLOYED — TAP TO REMOVE':'DEPLOY IN SIM';
    const simBit=(spawn?.ok===false)?` · SIM FAULT: ${spawn.reason||'failed'}`:'';
    const cfgBit=` · AUTO · ${radius} NM · SKIP >${gate.toLocaleString()} FT`;
    // v0.25.66: nearest-marker distance from the user aircraft explains why
    // deployed markers can be out of sight (the sim culls AI objects beyond a
    // few NM, so markers far from the aircraft are not rendered).
    const prox=data?.proximity||{};
    const nearest=prox?.nearest;
    const proxBit=(prox?.ok&&nearest)?` · NEAREST MARKER ${nearest.distance_nm} NM AWAY`:'';
    closureDeploySetStatus(enabled?`CLOSURE MARKERS — DEPLOYED · ${placed} PLACED${cfgBit}${simBit}${proxBit}`:`CLOSURE MARKERS — OFF · ${placed} PLANNED${cfgBit}${simBit}`);
  }catch(error){
    closureDeployState.lastError=friendlyError(error.message);
    closureDeploySetStatus(`CLOSURE MARKERS — UNAVAILABLE: ${closureDeployState.lastError}`);
  }finally{
    closureDeployBusy=false;
  }
}
async function toggleClosureDeploy(){
  if(closureDeployBusy)return;
  closureDeployBusy=true;
  const toggle=$('closureDeployToggle');
  try{
    const next=!closureDeployState.enabled;
    const res=await fetch('/api/simobjects/notam-closures',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:next})});
    const data=await safeJsonResponse(res);
    closureDeployState.enabled=!!data?.enabled;
    closureDeploySetStatus('CLOSURE MARKERS — '+(data?.enabled?'DEPLOYED':'REMOVED'));
    if(toggle){
      toggle.classList.toggle('active',!!data?.enabled);
      toggle.setAttribute('aria-pressed',data?.enabled?'true':'false');
      toggle.textContent=data?.enabled?'DEPLOYED — TAP TO REMOVE':'DEPLOY IN SIM';
    }
    // The spawn-triggering status GET runs AFTER the busy flag clears (below)
    // - calling refreshClosureDeploy() here would hit its closureDeployBusy
    // guard and return immediately, leaving the toggle showing DEPLOYED while
    // nothing is actually spawned (the dead manual deploy the user reported).
  }catch(error){
    closureDeployState.lastError=friendlyError(error.message);
    closureDeploySetStatus(`CLOSURE MARKERS — FAILED: ${closureDeployState.lastError}`);
  }finally{
    closureDeployBusy=false;
  }
  if(closureDeployState.enabled)await refreshClosureDeploy();
}
async function clearClosureDeploy(){
  if(closureDeployBusy)return;
  closureDeployBusy=true;
  const toggle=$('closureDeployToggle');
  try{
    const res=await fetch('/api/simobjects/notam-closures/clear',{method:'POST'});
    const data=await safeJsonResponse(res);
    const cleared=data?.clear||{};
    const removed=Number(cleared.removed||0);
    closureDeploySetStatus(`CLOSURE MARKERS — CLEARED (${removed} objects removed${cleared.reason==='ok'?'':' · '+String(cleared.reason||'')})`);
    if(toggle){
      toggle.classList.remove('active');
      toggle.setAttribute('aria-pressed','false');
      toggle.textContent='DEPLOY IN SIM';
    }
    closureDeployState.enabled=false;
    await refreshClosureDeploy();
  }catch(error){
    closureDeployState.lastError=friendlyError(error.message);
    closureDeploySetStatus(`CLOSURE MARKERS — CLEAR FAILED: ${closureDeployState.lastError}`);
  }finally{
    closureDeployBusy=false;
  }
}
function bindClosureDeploy(){
  $('closureDeployToggle')?.addEventListener('click',toggleClosureDeploy);
  $('closureDeployClear')?.addEventListener('click',clearClosureDeploy);
  if(document.querySelector('[data-briefing-section="notams"]'))refreshClosureDeploy(false);
}
function updateMapAviationStatus(text){const el=$('mapAviationStatus');if(!el)return;const next=String(text||'');if(el.textContent!==next)el.textContent=next}

function surfaceZoomMode(zoom=null){
  // `Number(null)` is 0. Treating the default null as an explicit zoom made
  // every layer-style call resolve to `none`, while labels (which pass a real
  // zoom) still rendered. Only honour an actually supplied numeric zoom.
  const supplied=zoom!==null&&zoom!==undefined&&zoom!==''&&Number.isFinite(Number(zoom));
  const z=supplied?Number(zoom):(olMap?.getView()?.getZoom?.()||2);
  if(z<12.9)return 'none';
  if(z<14.2)return 'runway';
  if(z<15.25)return 'taxi';
  return 'full';
}
function scheduleAviationRefresh(delay=220){
  if(activePage !== 'map')return;
  if(mapAviationRefreshTimer)clearTimeout(mapAviationRefreshTimer);
  mapAviationRefreshTimer=setTimeout(()=>{mapAviationRefreshTimer=null;if(activePage==='map')refreshAviationLayers();},delay);
}
function cancelSurfaceRenderTimers(){
  if(mapSurfaceRenderTimer){try{cancelAnimationFrame(mapSurfaceRenderTimer)}catch{}try{clearTimeout(mapSurfaceRenderTimer)}catch{}mapSurfaceRenderTimer=null;}
}
function maybeCullSurfaceForZoom(zoom=null){
  const mode=surfaceZoomMode(zoom);
  if(mode===mapSurfaceDetailMode)return false;
  mapSurfaceDetailMode=mode;
  if(mode==='none'&&mapSurfaceLoadedIcao){
    cancelSurfaceRenderTimers();
    olRunwaySurfaceLayer?.getSource()?.clear();
    olTaxiSurfaceLayer?.getSource()?.clear();
    olSurfaceLabelLayer?.getSource()?.clear();
    mapSurfaceLoadedIcao='';
    mapSurfaceAutoIcao='';
    mapSurfaceLoadingIcao='';
    mapSurfaceRequestSeq++;
    updateMapAviationStatus('AVIATION LAYERS READY · ZOOM IN FOR SURFACE');
    return true;
  }
  olRunwaySurfaceLayer?.changed();olTaxiSurfaceLayer?.changed();
  return false;
}

function mapSurfaceStatusText(){
  if(!mapLayerChecked('mapLayerSurface',true)&&!mapLayerChecked('mapLayerRunways',true))return 'SURFACE LAYER OFF';
  if(mapSurfaceLoadedIcao)return `LOCAL SURFACE ACTIVE: ${mapSurfaceLoadedIcao}`;
  return 'MAP READY';
}
function airportStyle(feature){
  const zoom=olMap?.getView()?.getZoom?.()||2;
  const runway=Number(feature.get('longestRunwayFt')||0);
  const routeAirport=!!feature.get('routeAirport');
  const label=String(feature.get('label')||'');
  if(!routeAirport&&zoom<5.1&&runway<8500)return null;
  const showLabel=routeAirport||zoom>=6.5||(zoom>=5.2&&runway>=7000);
  return new ol.style.Style({
    image:new ol.style.Circle({radius:routeAirport?6:zoom>=7?5:4,fill:new ol.style.Fill({color:routeAirport?'#f0d283':'#d9d5cc'}),stroke:new ol.style.Stroke({color:'#111315',width:2})}),
    text:new ol.style.Text({text:showLabel?label:'',offsetX:8,textAlign:'left',font:`700 ${routeAirport?'12':'10'}px B612 Mono, Consolas, monospace`,fill:new ol.style.Fill({color:routeAirport?'#f4dda2':'#f0ede4'}),stroke:new ol.style.Stroke({color:'#111315',width:4})})
  });
}
function navaidStyle(feature){
  const kind=String(feature.get('kind')||'NAV');
  const zoom=olMap?.getView()?.getZoom?.()||2;
  const label=String(feature.get('label')||'');
  return new ol.style.Style({
    image:new ol.style.RegularShape({points:kind==='VOR'?3:4,radius:4.6,angle:Math.PI/4,fill:new ol.style.Fill({color:kind==='VOR'?'#d7be68':'#b9d5f0'}),stroke:new ol.style.Stroke({color:'#101214',width:1.2})}),
    text:new ol.style.Text({text:zoom>=7?label:'',offsetX:9,textAlign:'left',font:'700 9px B612 Mono, Consolas, monospace',fill:new ol.style.Fill({color:'#e7dfc8'}),stroke:new ol.style.Stroke({color:'#111315',width:3})})
  });
}
function waypointStyle(feature){
  const zoom=olMap?.getView()?.getZoom?.()||2;
  return new ol.style.Style({image:new ol.style.RegularShape({points:4,radius:3.4,angle:Math.PI/4,fill:new ol.style.Fill({color:'#9cc4df'}),stroke:new ol.style.Stroke({color:'#111315',width:1})}),text:new ol.style.Text({text:zoom>=8.5?String(feature.get('label')||''):'',offsetX:8,textAlign:'left',font:'700 8px B612 Mono, Consolas, monospace',fill:new ol.style.Fill({color:'#bedcee'}),stroke:new ol.style.Stroke({color:'#111315',width:3})})});
}
function airwayStyle(feature){return new ol.style.Style({stroke:new ol.style.Stroke({color:'rgba(114,197,224,.30)',width:1.1,lineDash:[7,6]}),text:new ol.style.Text({text:(olMap?.getView()?.getZoom?.()||2)>=7?String(feature.get('label')||''):'',font:'700 9px B612 Mono, Consolas, monospace',fill:new ol.style.Fill({color:'#81d7e9'}),stroke:new ol.style.Stroke({color:'#111315',width:3})})});}
function boundaryStyle(feature){return new ol.style.Style({fill:new ol.style.Fill({color:'rgba(69,149,171,.045)'}),stroke:new ol.style.Stroke({color:'rgba(100,205,226,.24)',width:1,lineDash:[8,7]}),text:new ol.style.Text({text:(olMap?.getView()?.getZoom?.()||2)>=7?String(feature.get('label')||''):'',font:'700 8px B612 Mono, Consolas, monospace',fill:new ol.style.Fill({color:'#78d6e8'}),stroke:new ol.style.Stroke({color:'#111315',width:3})})});}
function runwaySurfaceStyle(feature,resolution){
  if(!feature||!mapLayerChecked('mapLayerRunways',true)||surfaceZoomMode()==='none')return null;
  const kind=String(feature.get('kind')||''),polygon=kind==='runway-surface'||feature.getGeometry()?.getType?.()==='Polygon';
  if(polygon)return new ol.style.Style({zIndex:80,fill:new ol.style.Fill({color:'rgba(48,53,57,.97)'}),stroke:new ol.style.Stroke({color:'rgba(239,244,245,.96)',width:2.2,lineJoin:'miter'})});
  if(kind==='runway-threshold')return new ol.style.Style({zIndex:84,stroke:new ol.style.Stroke({color:'#f7f9f9',width:2.4,lineCap:'butt'})});
  return [
    new ol.style.Style({zIndex:81,stroke:new ol.style.Stroke({color:'rgba(4,6,7,.98)',width:5.5,lineCap:'butt',lineJoin:'miter'})}),
    new ol.style.Style({zIndex:82,stroke:new ol.style.Stroke({color:'rgba(247,249,249,.94)',width:1.6,lineDash:[12,12],lineCap:'butt',lineJoin:'miter'})})
  ];
}
function taxiSurfaceStyle(feature,resolution){
  if(!feature||!mapLayerChecked('mapLayerSurface',true)||surfaceZoomMode()==='none')return null;
  const mode=surfaceZoomMode(),major=!!feature.get('majorTaxi');
  if(mode==='runway'&&!major)return null;
  const widthM=Math.max(7,Number(feature.get('widthFt')||45)*.3048),res=Math.max(.12,Number(resolution)||1);
  const px=Math.max(major?2.4:1.5,Math.min(major?6.2:4.1,widthM/res*.12));
  const inner=major?'#f4c82d':'#aa8b28';
  return [
    new ol.style.Style({zIndex:60,stroke:new ol.style.Stroke({color:'rgba(2,4,5,.97)',width:px+2.4,lineCap:'round',lineJoin:'round'})}),
    new ol.style.Style({zIndex:61,stroke:new ol.style.Stroke({color:inner,width:px,lineCap:'round',lineJoin:'round'})}),
    new ol.style.Style({zIndex:62,stroke:new ol.style.Stroke({color:major?'rgba(255,238,126,.82)':'rgba(232,202,82,.48)',width:Math.max(.65,px*.13),lineCap:'round',lineJoin:'round'})})
  ];
}
function surfaceStyle(feature,resolution){
  return String(feature.get('kind')||'').startsWith('runway')?runwaySurfaceStyle(feature,resolution):taxiSurfaceStyle(feature,resolution);
}
function runwayPolygonFromLine(geometry,widthM){
  const coords=geometry?.getCoordinates?.()||[];if(coords.length<2)return null;
  const a=coords[0],b=coords[coords.length-1],dx=b[0]-a[0],dy=b[1]-a[1],length=Math.hypot(dx,dy);if(!length)return null;
  const half=Math.max(14,Number(widthM)||45)/2,nx=-dy/length*half,ny=dx/length*half;
  return new ol.geom.Polygon([[[a[0]+nx,a[1]+ny],[b[0]+nx,b[1]+ny],[b[0]-nx,b[1]-ny],[a[0]-nx,a[1]-ny],[a[0]+nx,a[1]+ny]]]);
}
function runwayCrossLine(geometry,widthM,fraction){
  const coords=geometry?.getCoordinates?.()||[];if(coords.length<2)return null;
  const a=coords[0],b=coords[coords.length-1],dx=b[0]-a[0],dy=b[1]-a[1],length=Math.hypot(dx,dy);if(!length)return null;
  const f=Math.max(0,Math.min(1,Number(fraction)||0)),cx=a[0]+dx*f,cy=a[1]+dy*f,half=Math.max(12,Number(widthM)||45)*.43,nx=-dy/length*half,ny=dx/length*half;
  return new ol.geom.LineString([[cx+nx,cy+ny],[cx-nx,cy-ny]]);
}
function runwayThresholdStripes(geometry,widthM,fraction,reverse=false){
  const coords=geometry?.getCoordinates?.()||[];if(coords.length<2)return [];
  const a=coords[0],b=coords[coords.length-1],dx=b[0]-a[0],dy=b[1]-a[1],length=Math.hypot(dx,dy);if(!length)return [];
  const ux=dx/length,uy=dy/length,nx=-uy,ny=ux,cx=a[0]+dx*fraction,cy=a[1]+dy*fraction,half=Math.max(12,Number(widthM)||45)*.34,stripeLen=Math.max(12,Math.min(28,length*.035)),dir=reverse?-1:1;
  const result=[];for(const offset of [-.72,-.43,-.14,.14,.43,.72]){const sx=cx+nx*half*offset,sy=cy+ny*half*offset;result.push(new ol.geom.LineString([[sx,sy],[sx+ux*stripeLen*dir,sy+uy*stripeLen*dir]]))}return result;
}
function runwayEndLabelFeature(geometry,label,fraction,flip=false){
  const coords=geometry?.getCoordinates?.()||[];if(coords.length<2||!label)return null;
  const a=coords[0],b=coords[coords.length-1],dx=b[0]-a[0],dy=b[1]-a[1],angle=Math.atan2(dy,dx),point=geometry.getCoordinateAt(Math.max(.04,Math.min(.96,fraction)));
  return new ol.Feature({geometry:new ol.geom.Point(point),kind:'runway-end-label',label:String(label).replace(/^RWY\s*/i,''),rotation:angle+(flip?Math.PI:0),title:`RWY ${label}`});
}
function surfaceLabelStyle(feature){
  const kind=String(feature.get('kind')||''),zoom=olMap?.getView()?.getZoom?.()||2,mode=surfaceZoomMode(zoom);
  if(mode==='none')return null;
  const label=String(feature.get('label')||'').trim();if(!label)return null;
  if(kind==='runway-end-label'){
    if(!mapLayerChecked('mapLayerRunways',true)||zoom<13.6)return null;
    return new ol.style.Style({zIndex:90,text:new ol.style.Text({text:label,font:`900 ${zoom>=16?16:13}px B612 Mono, Consolas, monospace`,rotation:Number(feature.get('rotation'))||0,rotateWithView:true,fill:new ol.style.Fill({color:'#ffffff'}),stroke:new ol.style.Stroke({color:'#15191b',width:3.4}),overflow:true})});
  }
  if(kind==='taxi-label'){
    if(!mapLayerChecked('mapLayerSurface',true)||!mapLayerChecked('mapLayerTaxiLabels',true)||zoom<14.45)return null;
    return new ol.style.Style({text:new ol.style.Text({text:label,font:'900 10px B612 Mono, Consolas, monospace',fill:new ol.style.Fill({color:'#ffea00'}),backgroundFill:new ol.style.Fill({color:'rgba(3,6,8,.94)'}),backgroundStroke:new ol.style.Stroke({color:'rgba(255,231,0,.92)',width:1}),padding:[2,6,2,6],stroke:new ol.style.Stroke({color:'#050607',width:2.3}),overflow:false})});
  }
  return null;
}
function currentBboxParam(){if(!olMap)return '';const extent=olMap.getView().calculateExtent(olMap.getSize());const a=ol.proj.transformExtent(extent,'EPSG:3857','EPSG:4326');return a.map(x=>Number(x.toFixed(5))).join(',')}
function mapDistanceNm(lat1,lon1,lat2,lon2){
  const values=[lat1,lon1,lat2,lon2].map(Number);if(!values.every(Number.isFinite))return Infinity;
  const [aLat,aLon,bLat,bLon]=values.map((value,index)=>index%2===0?value*Math.PI/180:value);
  const dLat=(values[2]-values[0])*Math.PI/180,dLon=(values[3]-values[1])*Math.PI/180;
  const h=Math.sin(dLat/2)**2+Math.cos(aLat)*Math.cos(bLat)*Math.sin(dLon/2)**2;
  return 3440.065*2*Math.atan2(Math.sqrt(h),Math.sqrt(Math.max(0,1-h)));
}
function airportLookupBboxParam(zoom=null){
  if(!olMap)return '';
  const center=ol.proj.toLonLat(olMap.getView().getCenter());
  const visible=ol.proj.transformExtent(olMap.getView().calculateExtent(olMap.getSize()),'EPSG:3857','EPSG:4326');
  const z=Number.isFinite(Number(zoom))?Number(zoom):(olMap.getView().getZoom()||2);
  let halfLon=Math.max(Math.abs(visible[2]-visible[0])*.75,.01),halfLat=Math.max(Math.abs(visible[3]-visible[1])*.75,.01);
  if(surfaceZoomMode(z)!=='none'){
    halfLat=Math.max(halfLat,.18);
    halfLon=Math.max(halfLon,.24/Math.max(.35,Math.cos(Number(center[1]||0)*Math.PI/180)));
  }
  return [center[0]-halfLon,center[1]-halfLat,center[0]+halfLon,center[1]+halfLat].map(value=>Number(value.toFixed(5))).join(',');
}
function rememberMapAirport(item){
  const ident=String(item?.ident||item?.icao||'').trim().toUpperCase();
  if(!ident)return null;
  const previous=mapAirportIndex.get(ident)||{};
  const row={...previous,...item,ident,icao:ident};
  if(Number.isFinite(Number(row.lat))&&Number.isFinite(Number(row.lon)))mapAirportIndex.set(ident,row);
  else if(!mapAirportIndex.has(ident))mapAirportIndex.set(ident,row);
  return row;
}
function routeSurfaceAirports(){
  return (mapData?.airports||[]).map(item=>rememberMapAirport({ident:item.ident||item.icao,lat:item.lat,lon:item.lon,name:item.name||'',longest_runway_ft:99999,routeAirport:true})).filter(Boolean);
}
function airportNearMapCenter(item,maxNm=30){
  if(!olMap||!item||!Number.isFinite(Number(item.lat))||!Number.isFinite(Number(item.lon)))return false;
  const center=ol.proj.toLonLat(olMap.getView().getCenter());
  return mapDistanceNm(center[1],center[0],Number(item.lat),Number(item.lon))<=maxNm;
}
function chooseSurfaceAirport(items=[]){
  if(!olMap)return null;
  const pool=[];
  for(const item of [...(items||[]),...routeSurfaceAirports()]){const row=rememberMapAirport(item);if(row&&!pool.some(existing=>existing.ident===row.ident))pool.push(row)}
  if(mapSelectedAirportIcao)return mapAirportIndex.get(mapSelectedAirportIcao)||{ident:mapSelectedAirportIcao,icao:mapSelectedAirportIcao,name:mapSelectedAirportTitle};
  if(mapSurfaceLoadedIcao){const loaded=mapAirportIndex.get(mapSurfaceLoadedIcao);if(!loaded||airportNearMapCenter(loaded,12))return loaded||{ident:mapSurfaceLoadedIcao,icao:mapSurfaceLoadedIcao}}
  const ownIdent=String(mapData?.ownship?.nearest_airport||'').trim().toUpperCase();
  if(ownIdent&&Number.isFinite(Number(mapData?.ownship?.lat))&&Number.isFinite(Number(mapData?.ownship?.lon))){
    const ownDistance=(()=>{const center=ol.proj.toLonLat(olMap.getView().getCenter());return mapDistanceNm(center[1],center[0],Number(mapData.ownship.lat),Number(mapData.ownship.lon))})();
    if(ownDistance<=32)return mapAirportIndex.get(ownIdent)||{ident:ownIdent,icao:ownIdent,lat:Number(mapData.ownship.lat),lon:Number(mapData.ownship.lon),name:ownIdent};
  }
  const center=ol.proj.toLonLat(olMap.getView().getCenter());
  const ranked=pool.filter(item=>Number.isFinite(Number(item.lat))&&Number.isFinite(Number(item.lon))).map(item=>({...item,__distance:mapDistanceNm(center[1],center[0],Number(item.lat),Number(item.lon))})).sort((a,b)=>a.__distance-b.__distance||(Number(b.longest_runway_ft)||0)-(Number(a.longest_runway_ft)||0));
  const route=ranked.find(item=>item.routeAirport&&item.__distance<=32);if(route)return route;
  return ranked[0]&&ranked[0].__distance<=38?ranked[0]:null;
}

function boundaryFeature(item){
  const minLon=Number(item.min_lon),minLat=Number(item.min_lat),maxLon=Number(item.max_lon),maxLat=Number(item.max_lat);
  if(![minLon,minLat,maxLon,maxLat].every(Number.isFinite)||minLon===maxLon||minLat===maxLat)return null;
  const pts=[[minLon,minLat],[maxLon,minLat],[maxLon,maxLat],[minLon,maxLat],[minLon,minLat]].map(p=>ol.proj.fromLonLat(p));
  return new ol.Feature({geometry:new ol.geom.Polygon([pts]),label:item.name||item.type||'BOUNDARY',title:`BOUNDARY ${item.name||item.type||''}${item.source==='openaip'?' · SOURCE: OpenAIP':''}`});
}
async function maybeAutoLoadAirportSurface(items,zoom){
  const surfaceEnabled=mapLayerChecked('mapLayerSurface',true)||mapLayerChecked('mapLayerRunways',true);
  if(!olMap||!surfaceEnabled){clearAirportSurface('SURFACE LAYER OFF');return}
  if(maybeCullSurfaceForZoom(zoom))return;
  if(surfaceZoomMode(zoom)==='none'){updateMapAviationStatus('AVIATION LAYERS READY · ZOOM IN FOR SURFACE');return}
  const airport=chooseSurfaceAirport(items);
  if(!airport?.ident){updateMapAviationStatus(mapSurfaceLoadedIcao?`LOCAL SURFACE ACTIVE: ${mapSurfaceLoadedIcao}`:'SURFACE DB READY · SEARCHING NEAREST AIRPORT');return}
  const ident=String(airport.ident).toUpperCase();mapSurfaceTargetIcao=ident;
  if(ident===mapSurfaceLoadedIcao){updateMapAviationStatus(`LOCAL SURFACE ACTIVE: ${ident}`);return}
  if(ident===mapSurfaceLoadingIcao)return;
  await loadAirportSurface(ident,{auto:true,animate:false});
}
async function refreshAviationLayers(){
  if(activePage !== 'map' || !olMap)return;
  if(mapAviationBusy){mapAviationRefreshPending=true;return}
  mapAviationBusy=true;
  try{
    const bbox=currentBboxParam();const zoom=olMap.getView().getZoom()||2;
    if(!mapSurfaceLoadedIcao&&!mapSurfaceLoadingIcao)updateMapAviationStatus('LOADING AVIATION LAYERS');
    const airportOn=mapLayerChecked('mapLayerAirports',true),navaidOn=mapLayerChecked('mapLayerNavaids',false),waypointOn=mapLayerChecked('mapLayerWaypoints',false),airwayOn=mapLayerChecked('mapLayerAirways',false),boundaryOn=mapLayerChecked('mapLayerBoundaries',false);
    const surfaceEnabled=mapLayerChecked('mapLayerSurface',true)||mapLayerChecked('mapLayerRunways',true);
    const needAirportLookup=(airportOn&&zoom>=4)||(surfaceEnabled&&surfaceZoomMode(zoom)!=='none');
    olAirportLayer?.setVisible(airportOn);olNavaidLayer?.setVisible(navaidOn);olWaypointLayer?.setVisible(waypointOn);olAirwayLayer?.setVisible(airwayOn);olBoundaryLayer?.setVisible(boundaryOn);olRunwaySurfaceLayer?.setVisible(mapLayerChecked('mapLayerRunways',true));olTaxiSurfaceLayer?.setVisible(mapLayerChecked('mapLayerSurface',true));olSurfaceLabelLayer?.setVisible(surfaceEnabled);
    let airportItems=routeSurfaceAirports();
    if(needAirportLookup){
      const lookupBbox=surfaceEnabled&&surfaceZoomMode(zoom)!=='none'?airportLookupBboxParam(zoom):bbox;
      const limit=surfaceZoomMode(zoom)!=='none'?1800:zoom<5.2?220:zoom<7?650:1400;
      const r=await fetch(`/api/livemap/layers/airports?bbox=${encodeURIComponent(lookupBbox)}&limit=${limit}`,{cache:'no-store'});const d=await safeJsonResponse(r);
      const fetched=(d.items||[]).filter(item=>Number.isFinite(Number(item.lat))&&Number.isFinite(Number(item.lon))).map(rememberMapAirport).filter(Boolean);
      for(const item of fetched)if(!airportItems.some(existing=>existing.ident===item.ident))airportItems.push(item);
    }
    const src=olAirportLayer.getSource();src.clear();
    if(airportOn)airportItems.filter(item=>!item.routeAirport).filter(item=>zoom>=5.8||(Number(item.longest_runway_ft)||0)>=6000).forEach(item=>{const f=pointFeature(item,item.ident,`${item.ident} · ${item.name||'Airport'}`);f.set('airportLayer',true);f.set('longestRunwayFt',Number(item.longest_runway_ft)||0);f.set('routeAirport',!!item.routeAirport);src.addFeature(f)});
    if(navaidOn&&zoom>=5.6){
      const r=await fetch(`/api/livemap/layers/navaids?bbox=${encodeURIComponent(bbox)}&limit=${zoom<7?450:1500}`,{cache:'no-store'});const d=await r.json();const navSrc=olNavaidLayer.getSource();navSrc.clear();
      (d.items||[]).forEach(item=>{if(!Number.isFinite(Number(item.lat))||!Number.isFinite(Number(item.lon)))return;const f=pointFeature(item,item.ident,`${item.kind||'NAV'} ${item.ident} · ${item.name||''}`);f.set('kind',item.kind||'NAV');navSrc.addFeature(f)});
    } else olNavaidLayer?.getSource()?.clear();
    if(waypointOn&&zoom>=7.2){
      const r=await fetch(`/api/livemap/layers/waypoints?bbox=${encodeURIComponent(bbox)}&limit=${zoom<9?700:2500}`,{cache:'no-store'});const d=await r.json();const fixSrc=olWaypointLayer.getSource();fixSrc.clear();
      (d.items||[]).forEach(item=>{if(!Number.isFinite(Number(item.lat))||!Number.isFinite(Number(item.lon)))return;fixSrc.addFeature(pointFeature(item,item.ident,`FIX ${item.ident||''} · ${item.name||''}`))});
    } else olWaypointLayer?.getSource()?.clear();
    if(airwayOn&&zoom>=5.6){
      const r=await fetch(`/api/livemap/layers/airways?bbox=${encodeURIComponent(bbox)}&limit=${zoom<7?800:2500}`,{cache:'no-store'});const d=await r.json();const airwaySrc=olAirwayLayer.getSource();airwaySrc.clear();
      (d.items||[]).forEach(item=>{if(!Number.isFinite(Number(item.from_lat))||!Number.isFinite(Number(item.from_lon))||!Number.isFinite(Number(item.to_lat))||!Number.isFinite(Number(item.to_lon)))return;airwaySrc.addFeature(new ol.Feature({geometry:new ol.geom.LineString([ol.proj.fromLonLat([Number(item.from_lon),Number(item.from_lat)]),ol.proj.fromLonLat([Number(item.to_lon),Number(item.to_lat)])]),label:item.name,title:`AIRWAY ${item.name||''}`}))});
    } else olAirwayLayer?.getSource()?.clear();
    if(boundaryOn&&zoom>=5){
      const r=await fetch(`/api/livemap/layers/airspaces?bbox=${encodeURIComponent(bbox)}&limit=900`,{cache:'no-store'});const d=await r.json();const boundarySrc=olBoundaryLayer.getSource();boundarySrc.clear();
      (d.items||[]).forEach(item=>{const f=boundaryFeature(item);if(f)boundarySrc.addFeature(f)});
      if(d.source==='openaip'||d.source==='mixed'){olBoundaryLayer.getSource().setAttributions('Airspace © OpenAIP (CC BY-NC)');updateMapAviationStatus(`OPENAIP BOUNDARIES: ${Number(d.openaip?.count||0)} AIRSPACES${d.openaip?.local_count?` + LOCAL ${Number(d.openaip.local_count)}`:''}`)}
      else olBoundaryLayer.getSource().setAttributions([]);
    } else {olBoundaryLayer?.getSource()?.clear();olBoundaryLayer?.getSource()?.setAttributions([])}
    // v0.25.60: keep the live NOTAM layer in sync with the viewport (only
    // fires when the NOTAMS layer toggle is on).
    if(mapLayerChecked('mapLayerNotams',false)){try{await loadNotamLayer()}catch(e){console.warn('NOTAM layer:',e)}}
    await maybeAutoLoadAirportSurface(airportItems,zoom);
    if(!mapSurfaceLoadingIcao&&$('mapAviationStatus')?.textContent?.startsWith('LOADING'))updateMapAviationStatus(mapSurfaceStatusText());
  }catch(e){updateMapAviationStatus(`AVIATION LAYERS LIMITED: ${friendlyError(e.message)}`)}
  finally{
    mapAviationBusy=false;
    if(mapAviationRefreshPending){mapAviationRefreshPending=false;scheduleAviationRefresh(0)}
  }
}
function clearAirportSurface(reason=''){
  cancelSurfaceRenderTimers();
  mapSurfaceRequestSeq++;
  olRunwaySurfaceLayer?.getSource()?.clear();
  olTaxiSurfaceLayer?.getSource()?.clear();
  olSurfaceLabelLayer?.getSource()?.clear();
  mapSurfaceLoadedIcao='';
  mapSurfaceAutoIcao='';
  mapSurfaceLoadingIcao='';
  olBaseLayer?.setOpacity(1);olRasterFallbackLayer?.setOpacity(.48);
  if(reason)updateMapAviationStatus(reason);
}
function taxiLabelBudget(label,zoomMode){
  if(!label)return 0;
  if(zoomMode==='full')return label.length<=2?4:3;
  if(zoomMode==='taxi')return label.length<=2?2:1;
  return 0;
}
function shouldKeepTaxiLabel(label,feature,labelState){
  if(!label)return false;
  // Build the full candidate set once; the label style controls visibility by current zoom.
  // This prevents labels being permanently omitted when the surface first loads at runway zoom.
  const budget=taxiLabelBudget(label,'full');
  if(budget<=0)return false;
  const geom=feature.getGeometry();
  const extent=geom?.getExtent?.();
  if(!extent)return false;
  const center=ol.extent.getCenter(extent);
  const bucket=700; // metres in web mercator, enough to avoid A A A A clutter while keeping useful references.
  const key=`${label}:${Math.round(center[0]/bucket)}:${Math.round(center[1]/bucket)}`;
  if(labelState.cells.has(key))return false;
  const count=labelState.counts.get(label)||0;
  if(count>=budget)return false;
  labelState.cells.add(key);
  labelState.counts.set(label,count+1);
  return true;
}
function lineMidpoint(geometry){
  try{return geometry.getCoordinateAt(.5)}catch{return ol.extent.getCenter(geometry.getExtent())}
}
function addAirportSurfaceFeatures(data,requestId,ident){
  if(requestId!==mapSurfaceRequestSeq||String(ident||'').toUpperCase()!==mapSurfaceLoadingIcao)return false;
  cancelSurfaceRenderTimers();
  const runwaySrc=olRunwaySurfaceLayer.getSource(),taxiSrc=olTaxiSurfaceLayer.getSource(),labelSrc=olSurfaceLabelLayer.getSource();
  const zoom=olMap?.getView()?.getZoom?.()||2;
  mapSurfaceDetailMode=surfaceZoomMode(zoom);
  const runways=[],taxiways=[],labels=[];
  (data.runways||[]).forEach(rwy=>{
    if(!Number.isFinite(Number(rwy.primary_lon))||!Number.isFinite(Number(rwy.primary_lat))||!Number.isFinite(Number(rwy.secondary_lon))||!Number.isFinite(Number(rwy.secondary_lat)))return;
    const geometry=new ol.geom.LineString([ol.proj.fromLonLat([Number(rwy.primary_lon),Number(rwy.primary_lat)]),ol.proj.fromLonLat([Number(rwy.secondary_lon),Number(rwy.secondary_lat)])]);
    const widthFt=Number(rwy.width_ft)||150,polygon=runwayPolygonFromLine(geometry,widthFt*.3048);
    if(polygon){const surface=new ol.Feature({geometry:polygon,kind:'runway-surface',label:rwy.name||'',title:`RWY ${rwy.name||''}`,widthFt});runways.push(surface)}
    const centerline=new ol.Feature({geometry,kind:'runway-centerline',label:rwy.name||'',title:`RWY ${rwy.name||''}`,widthFt});runways.push(centerline);
    const thresholdA=runwayCrossLine(geometry,widthFt*.3048,.055),thresholdB=runwayCrossLine(geometry,widthFt*.3048,.945);
    if(thresholdA)runways.push(new ol.Feature({geometry:thresholdA,kind:'runway-threshold',title:`RWY ${rwy.name||''}`}));
    if(thresholdB)runways.push(new ol.Feature({geometry:thresholdB,kind:'runway-threshold',title:`RWY ${rwy.name||''}`}));
    runwayThresholdStripes(geometry,widthFt*.3048,.07,false).forEach(mark=>runways.push(new ol.Feature({geometry:mark,kind:'runway-threshold',title:`RWY ${rwy.name||''}`})));
    runwayThresholdStripes(geometry,widthFt*.3048,.93,true).forEach(mark=>runways.push(new ol.Feature({geometry:mark,kind:'runway-threshold',title:`RWY ${rwy.name||''}`})));
    const fallbackNames=String(rwy.name||'').split('/').map(value=>value.trim()).filter(Boolean),primaryName=String(rwy.primary_name||fallbackNames[0]||'').trim(),secondaryName=String(rwy.secondary_name||fallbackNames[1]||'').trim();
    const endA=runwayEndLabelFeature(geometry,primaryName,.115,false),endB=runwayEndLabelFeature(geometry,secondaryName,.885,true);
    if(endA)labels.push(endA);if(endB)labels.push(endB);
  });
  const labelState={cells:new Set(),counts:new Map()};
  const rawTaxi=(data.taxiways||[]);
  for(const t of rawTaxi){
    const coords=Array.isArray(t.points)&&t.points.length>=2?t.points.map(point=>ol.proj.fromLonLat([Number(point[0]),Number(point[1])])).filter(point=>point.every(Number.isFinite)):[ol.proj.fromLonLat([Number(t.start_lon),Number(t.start_lat)]),ol.proj.fromLonLat([Number(t.end_lon),Number(t.end_lat)])];
    if(coords.length<2||coords.some(point=>!point.every(Number.isFinite)))continue;
    const label=String(t.name||'').trim(),geometry=new ol.geom.LineString(coords);
    const width=Number(t.width_ft)||0;
    const f=new ol.Feature({geometry,kind:'taxi',label,title:label?`TWY ${label}`:'TWY'});
    f.set('majorTaxi',!!label||width>=70);f.set('widthFt',width||45);f.set('pathType',String(t.type||''));
    taxiways.push(f);
    if(label&&shouldKeepTaxiLabel(label,f,labelState))labels.push(new ol.Feature({geometry:new ol.geom.Point(lineMidpoint(geometry)),kind:'taxi-label',label,title:`TWY ${label}`}));
  }
  // Replace the previous airport atomically after the full, already-merged
  // geometry set is ready. This prevents the visible surface disappearing
  // while the next airport payload is fetched or classified.
  runwaySrc.clear();taxiSrc.clear();labelSrc.clear();runwaySrc.addFeatures(runways);taxiSrc.addFeatures(taxiways);labelSrc.addFeatures(labels);
  finishSurfaceLoad(data,ident,requestId);
  return true;
}
function finishSurfaceLoad(data,ident,requestId){
  if(requestId!==mapSurfaceRequestSeq||String(ident).toUpperCase()!==mapSurfaceLoadingIcao)return;
  const loaded=String(data.airport?.ident||ident).toUpperCase();
  rememberMapAirport({...data.airport,ident:loaded,icao:loaded});
  mapSurfaceLoadedIcao=loaded;mapSurfaceTargetIcao=loaded;
  if(data.__auto)mapSurfaceAutoIcao=loaded;
  const suffix=data.source==='built-in'?'BUILT-IN RUNWAYS':'LOCAL SURFACE';
  const raw=Number(data.raw_taxi_segment_count||0),merged=Number(data.taxi_polyline_count||data.taxiways?.length||0);
  const runwayFeatures=olRunwaySurfaceLayer?.getSource()?.getFeatures?.()||[],renderedRunways=runwayFeatures.filter(feature=>String(feature.get('kind')||'')==='runway-surface').length,renderedTaxiways=olTaxiSurfaceLayer?.getSource()?.getFeatures()?.length||0;
  const txt=`${loaded} SURFACE · ${renderedRunways} RWY · ${renderedTaxiways}/${merged} TAXI LINES${raw?` (${raw} SEGMENTS)`:''} · ${suffix}`;
  $('mapSelected').textContent=txt;
  updateMapAviationStatus(`LOCAL SURFACE ACTIVE: ${loaded}`);
  mapSurfaceLoadingIcao='';mapSurfaceRenderTimer=null;
  olBaseLayer?.setOpacity(.42);olRasterFallbackLayer?.setOpacity(.16);
  olRunwaySurfaceLayer?.changed();olTaxiSurfaceLayer?.changed();olSurfaceLabelLayer?.changed();
}

async function loadAirportSurface(icao,options={}){
  const ident=String(icao||'').trim().toUpperCase();
  if(!olMap||!ident||(mapLayerChecked('mapLayerSurface',true)===false&&mapLayerChecked('mapLayerRunways',true)===false))return;
  if(surfaceZoomMode()==='none'&&options.auto)return;
  mapSurfaceTargetIcao=ident;
  if(!options.auto&&mapSelectedAirportIcao===ident&&mapSelectedAirportTitle)$('mapSelected').textContent=mapSelectedAirportTitle;
  if(ident===mapSurfaceLoadedIcao&&!options.force){olRunwaySurfaceLayer?.changed();olTaxiSurfaceLayer?.changed();olSurfaceLabelLayer?.changed();return;}
  cancelSurfaceRenderTimers();const requestId=++mapSurfaceRequestSeq;mapSurfaceLoadingIcao=ident;
  updateMapAviationStatus(`LOCAL SURFACE LOADING: ${ident}`);
  try{
    let d=mapSurfaceCache.get(ident);
    if(!d){const r=await fetch(`/api/livemap/airport-surface?icao=${encodeURIComponent(ident)}`,{cache:'no-store'});d=await safeJsonResponse(r);if(d&&d.ok)mapSurfaceCache.set(ident,d);}
    if(requestId!==mapSurfaceRequestSeq||ident!==mapSurfaceLoadingIcao)return;
    if(!d?.ok){const msg=d?.message||'Airport surface unavailable';$('mapSelected').textContent=`SURFACE LIMITED: ${escapeHtml(msg)}`;updateMapAviationStatus(`SURFACE LIMITED: ${friendlyError(msg)}`);mapSurfaceLoadingIcao='';return;}
    d.__auto=!!options.auto;addAirportSurfaceFeatures(d,requestId,ident);
    if(options.animate!==false&&d.airport&&Number.isFinite(Number(d.airport.lon))&&Number.isFinite(Number(d.airport.lat)))olMap.getView().animate({center:ol.proj.fromLonLat([Number(d.airport.lon),Number(d.airport.lat)]),zoom:Math.max(16,olMap.getView().getZoom()||0),duration:260});
  }catch(e){if(requestId===mapSurfaceRequestSeq){$('mapSelected').textContent=`SURFACE UNAVAILABLE: ${friendlyError(e.message)}`;updateMapAviationStatus(`SURFACE UNAVAILABLE: ${friendlyError(e.message)}`);mapSurfaceLoadingIcao='';}}
}

function restoreMapView(){
  try{
    const saved=JSON.parse(localStorage.getItem('opsroom-map-view-v2')||'null');
    if(saved&&Array.isArray(saved.center)&&Number.isFinite(saved.zoom)){
      mapHasStoredView=true;
      return {center:ol.proj.fromLonLat(saved.center),zoom:Math.max(2,Math.min(19,saved.zoom)),rotation:Number(saved.rotation)||0};
    }
  }catch{}
  return {center:ol.proj.fromLonLat([0,25]),zoom:2};
}
function saveMapView(){
  if(!olMap)return;
  const center=olMap.getView().getCenter();
  if(!center)return;
  const zoom=olMap.getView().getZoom()||2;
  maybeCullSurfaceForZoom(zoom);
  const lonLat=ol.proj.toLonLat(center);
  localStorage.setItem('opsroom-map-view-v2',JSON.stringify({center:[Number(lonLat[0].toFixed(5)),Number(lonLat[1].toFixed(5))],zoom:Number(zoom.toFixed(2)),rotation:Number((olMap.getView().getRotation()||0).toFixed(5))}));
  mapHasStoredView=true;
  renderMapControllerList();
  scheduleAviationRefresh(260);
}
function initOnlineMap(){
  if(olMap||!window.ol)return;
  const initial=restoreMapView();
  olRasterFallbackLayer=new ol.layer.Tile({source:new ol.source.OSM({crossOrigin:'anonymous',attributions:[]}),opacity:.48,zIndex:-1,visible:true});
  olBaseLayer=new ol.layer.VectorTile({source:new ol.source.VectorTile({format:new ol.format.MVT(),url:'/api/map/tile/{z}/{x}/{y}.mvt',maxZoom:15,attributions:'© Protomaps · © OpenStreetMap contributors'}),style:baseMapStyle,zIndex:0,visible:true});
  olCoverageLayer=makeVectorLayer(coverageStyle,8);
  olRouteLayer=makeVectorLayer(new ol.style.Style({stroke:new ol.style.Stroke({color:'#70d4e5',width:2.7,lineDash:[10,6]})}),10);
  olRouteAirportLayer=makeVectorLayer(airportStyle,20,{declutter:true});
  olAirportLayer=makeVectorLayer(airportStyle,19,{declutter:true});
  olControllerLayer=makeVectorLayer(controllerStyle,25);
  olTrafficLayer=makeVectorLayer(feature=>trafficStyle(feature,false),30);
  olOwnshipLayer=makeVectorLayer(feature=>trafficStyle(feature,true),40);
  olNavaidLayer=makeVectorLayer(navaidStyle,22);
  olWaypointLayer=makeVectorLayer(waypointStyle,21);
  olAirwayLayer=makeVectorLayer(airwayStyle,9);
  olBoundaryLayer=makeVectorLayer(boundaryStyle,7);
  olNotamLayer=makeVectorLayer(notamStyle,8);
  olNotamLayer.setVisible(mapLayerChecked('mapLayerNotams',false));
  olRunwaySurfaceLayer=new ol.layer.Vector({source:new ol.source.Vector({wrapX:false}),style:runwaySurfaceStyle,zIndex:34,renderMode:'vector',renderBuffer:1200,updateWhileAnimating:true,updateWhileInteracting:true});
  olTaxiSurfaceLayer=new ol.layer.Vector({source:new ol.source.Vector({wrapX:false}),style:taxiSurfaceStyle,zIndex:33,renderMode:'vector',renderBuffer:1200,updateWhileAnimating:true,updateWhileInteracting:true});
  olSurfaceLayer=olTaxiSurfaceLayer;
  olSurfaceLabelLayer=makeVectorLayer(surfaceLabelStyle,35,{declutter:true,updateWhileAnimating:true,updateWhileInteracting:true});
  olMap=new ol.Map({target:'liveMap',layers:[olRasterFallbackLayer,olBaseLayer,olBoundaryLayer,olNotamLayer,olAirwayLayer,olCoverageLayer,olRouteLayer,olTaxiSurfaceLayer,olRunwaySurfaceLayer,olSurfaceLabelLayer,olAirportLayer,olRouteAirportLayer,olWaypointLayer,olNavaidLayer,olControllerLayer,olTrafficLayer,olOwnshipLayer],view:new ol.View({center:initial.center,zoom:initial.zoom,minZoom:2,maxZoom:19,enableRotation:true,rotation:initial.rotation||0}),controls:ol.control.defaults.defaults({attribution:false,zoom:true,rotate:true}).extend([new ol.control.Attribution({collapsible:false})])});
  mapAutoFramePending=!mapHasStoredView;
  olMap.on('moveend',()=>{saveMapView();});
  olMap.on('singleclick',event=>{
    const features=[];olMap.forEachFeatureAtPixel(event.pixel,feature=>features.push(feature),{hitTolerance:8});
    const airport=features.find(feature=>feature.get('airportLayer'));
    if(airport&&airport.get('label')){
      const ident=String(airport.get('label')).toUpperCase();
      mapSelectedAirportIcao=ident;mapSurfaceTargetIcao=ident;
      mapSelectedAirportTitle=String(airport.get('title')||ident);
      $('mapSelected').textContent=mapSelectedAirportTitle;
      loadAirportSurface(ident,{auto:false,animate:true,force:true});
      return;
    }
    const selected=features.find(feature=>feature.get('title'));const title=selected?.get('title');const item=selected?.get('sourceItem');
    if(item?.callsign){$('mapSelected').innerHTML=`${airlineBrandHtml(item,'small',false)} <span>${escapeHtml(title||item.callsign)}</span>`}else $('mapSelected').textContent=title||mapSelectedAirportTitle||'SELECT A MAP SYMBOL';
  });
  olMap.on('pointermove',event=>{if(event.dragging)return;let interactive=false;olMap.forEachFeatureAtPixel(event.pixel,feature=>{if(feature.get('title'))interactive=true},{hitTolerance:7});const target=olMap.getTargetElement();if(target)target.style.cursor=interactive?'pointer':'crosshair'});
  setTimeout(()=>olMap.updateSize(),60);setTimeout(()=>olMap.updateSize(),300);
}
function pointFeature(item,label,title){return new ol.Feature({geometry:new ol.geom.Point(ol.proj.fromLonLat([Number(item.lon),Number(item.lat)])),label,title,heading:Number(item.heading_deg||item.heading||0),facility:Number(item.facility||0),callsign:item.callsign||'',frequency:item.frequency||'',sourceItem:item})}
function coverageFeature(item){
  if(item.coverage_geojson){
    try{const feature=new ol.format.GeoJSON().readFeature({type:'Feature',geometry:item.coverage_geojson,properties:{}},{dataProjection:'EPSG:4326',featureProjection:'EPSG:3857'});feature.set('facility',Number(item.facility||0));feature.set('title',`${item.callsign||'ATC'} ${item.frequency||''} · VATSPY SECTOR`);return feature}catch{}
  }
  if(!Number.isFinite(Number(item.lat))||!Number.isFinite(Number(item.lon)))return null;
  const center=ol.proj.fromLonLat([Number(item.lon),Number(item.lat)]);const latitude=Number(item.lat)||0;const scale=Math.max(.25,Math.cos(latitude*Math.PI/180));const radius=Math.max(4,Number(item.coverage_nm)||30)*1852/scale;
  return new ol.Feature({geometry:new ol.geom.Circle(center,radius),facility:Number(item.facility||0),title:`${item.callsign||'ATC'} ${item.frequency||''} ${item.facility_label||''} ESTIMATED COVERAGE ${Math.round(Number(item.coverage_nm)||0)} NM`});
}

function renderMapControllerList(){
  const target=$('mapControllerList');if(!target||!mapData)return;
  const rows=(mapData.controllers||[]).filter(item=>{
    if(!item.mapped||!Number.isFinite(Number(item.lat))||!Number.isFinite(Number(item.lon)))return true;
    if(!olMap)return true;const size=olMap.getSize();if(!size)return true;return ol.extent.containsCoordinate(olMap.getView().calculateExtent(size),ol.proj.fromLonLat([Number(item.lon),Number(item.lat)]));
  }).sort((a,b)=>(Number(b.facility)||0)-(Number(a.facility)||0)||String(a.callsign).localeCompare(String(b.callsign))).slice(0,40);
  target.innerHTML=rows.length?rows.map(item=>`<button type="button" data-map-controller="${escapeHtml(item.callsign)}" ${item.mapped?'':'data-unmapped="1"'}><b>${escapeHtml(item.callsign)}</b><span>${escapeHtml(item.frequency||'---')}</span><small>${escapeHtml(item.facility_label||'ATC')} · ${escapeHtml(item.coverage_kind||'ONLINE')}${item.mapped?'':' · POSITION PENDING'}</small></button>`).join(''):'<div class="network-empty">NO ONLINE CONTROLLERS</div>';
}


function unwrapRouteLongitudes(route){
  const rows=(route||[]).filter(x=>Number.isFinite(Number(x.lat))&&Number.isFinite(Number(x.lon))).map(x=>({lat:Number(x.lat),lon:Number(x.lon),ident:x.ident||x.name||''}));
  if(!rows.length)return [];
  const out=[];let offset=0;let prev=rows[0].lon;out.push({...rows[0],lonUnwrapped:rows[0].lon});
  for(let i=1;i<rows.length;i++){
    const lon=rows[i].lon;let adjusted=lon+offset;let delta=adjusted-prev;
    if(delta>180){offset-=360;adjusted=lon+offset;}
    else if(delta<-180){offset+=360;adjusted=lon+offset;}
    out.push({...rows[i],lonUnwrapped:adjusted});prev=adjusted;
  }
  return out;
}
function routeFeaturesForMap(route){
  const unwrapped=unwrapRouteLongitudes(route);if(unwrapped.length<2)return [];
  const segments=[[]];
  for(let i=0;i<unwrapped.length;i++){
    const p=unwrapped[i];
    if(i>0&&Math.abs(p.lonUnwrapped-unwrapped[i-1].lonUnwrapped)>120)segments.push([]);
    const wrapped=((p.lonUnwrapped+540)%360)-180;
    segments[segments.length-1].push(ol.proj.fromLonLat([wrapped,p.lat]));
  }
  return segments.filter(seg=>seg.length>1).map(seg=>new ol.Feature({geometry:new ol.geom.LineString(seg),title:'SIMBRIEF ROUTE'}));
}

function updateOwnshipFeature(ownship){
  const src=olOwnshipLayer?.getSource?.();
  if(!src)return;
  if(!ownship||!Number.isFinite(Number(ownship.lat))||!Number.isFinite(Number(ownship.lon))){
    if(ownshipAnimFrame){cancelAnimationFrame(ownshipAnimFrame);ownshipAnimFrame=null}
    ownshipAnimTarget=null;ownshipLastLonLat=null;olOwnshipFeature=null;src.clear();return;
  }
  const lonLat=[Number(ownship.lon),Number(ownship.lat)];
  const target=ol.proj.fromLonLat(lonLat);
  const label=ownship.callsign||'OWN';
  const title=`${label} · OWN AIRCRAFT`;
  if(!olOwnshipFeature){
    olOwnshipFeature=pointFeature(ownship,label,title);
    src.clear();src.addFeature(olOwnshipFeature);
    ownshipLastLonLat=lonLat;ownshipAnimTarget=target;return;
  }
  olOwnshipFeature.set('label',label);
  olOwnshipFeature.set('title',title);
  olOwnshipFeature.set('heading',Number(ownship.heading_deg||ownship.track_deg||0));
  const geom=olOwnshipFeature.getGeometry();
  const start=geom?.getCoordinates?.()||target;
  const dist=Math.hypot(target[0]-start[0],target[1]-start[1]);
  if(!Number.isFinite(dist)||dist>250000){geom.setCoordinates(target);ownshipLastLonLat=lonLat;ownshipAnimTarget=target;return;}
  const started=performance.now();
  const duration=Math.max(350,Math.min(1400,dist/40));
  if(ownshipAnimFrame)cancelAnimationFrame(ownshipAnimFrame);
  ownshipAnimTarget=target;ownshipLastLonLat=lonLat;
  const step=(ts)=>{
    const k=Math.max(0,Math.min(1,(ts-started)/duration));
    const eased=1-Math.pow(1-k,3);
    geom.setCoordinates([start[0]+(target[0]-start[0])*eased,start[1]+(target[1]-start[1])*eased]);
    if(k<1&&ownshipAnimTarget===target)ownshipAnimFrame=requestAnimationFrame(step);else ownshipAnimFrame=null;
  };
  ownshipAnimFrame=requestAnimationFrame(step);
}
function liveFlightLabel(data){
  const route=data?.flight?.origin&&data?.flight?.destination?`${data.flight.callsign||'FLIGHT'} ${data.flight.origin} TO ${data.flight.destination}`:'NO ACTIVE ROUTE';
  const live=data?.ownship?.nearest_airport?` · LIVE ${data.ownship.nearest_airport}`:'';
  const stale=data?.flight?.route_stale?' · ROUTE STALE':'';
  return `${route}${live}${stale}`;
}
function updatePointLayer(source,cache,items,keyFn,labelFn,titleFn,filterFn=null){
  const keep=new Set();for(const item of (items||[])){if(filterFn&&!filterFn(item))continue;const key=String(keyFn(item)||'');if(!key||!Number.isFinite(Number(item.lat))||!Number.isFinite(Number(item.lon)))continue;keep.add(key);let feature=cache.get(key);if(!feature){feature=pointFeature(item,labelFn(item),titleFn(item));feature.setId(key);cache.set(key,feature);source.addFeature(feature)}else{feature.getGeometry()?.setCoordinates(ol.proj.fromLonLat([Number(item.lon),Number(item.lat)]));feature.set('label',labelFn(item));feature.set('title',titleFn(item));feature.set('heading',Number(item.heading_deg||item.heading||0));feature.set('facility',Number(item.facility||0));feature.set('sourceItem',item);feature.changed()}}for(const [key,feature] of cache){if(!keep.has(key)){source.removeFeature(feature);cache.delete(key)}}
}
function trafficVisibleAtCurrentZoom(item){const zoom=olMap?.getView()?.getZoom?.()||2;if(zoom<11.5)return true;const size=olMap?.getSize?.();if(!size)return true;const extent=olMap.getView().calculateExtent(size),buffer=ol.extent.buffer(extent,Math.max(3000,ol.extent.getWidth(extent)*.18));return ol.extent.containsCoordinate(buffer,ol.proj.fromLonLat([Number(item.lon),Number(item.lat)]))}
function renderMap(data){
  mapData=data;renderAirlineIdentity('mapAirlineIdentity',flightPlan,'small',true,data?.ownship?[data.ownship.aircraft,data.ownship.altitude_ft?`${Math.round(Number(data.ownship.altitude_ft)).toLocaleString()} FT`:'',data.ownship.groundspeed_kts?`${Math.round(Number(data.ownship.groundspeed_kts))} KT`:''].filter(Boolean).join(' · '):'');if(!data?.ok)return;initOnlineMap();if(!olMap){$('mapLiveState').textContent='MAP LIBRARY UNAVAILABLE';return}
  // The base layers are independent of traffic/navdata/surface refreshes. Keep
  // them visible even when a heavy aviation request fails or is being replaced.
  olRasterFallbackLayer?.setVisible(true);olBaseLayer?.setVisible(true);
  document.querySelectorAll('[data-map-mode]').forEach(b=>b.classList.toggle('active',b.dataset.mapMode===mapMode));
  const route=(data.route||[]).filter(x=>Number.isFinite(Number(x.lat))&&Number.isFinite(Number(x.lon)));
  const routeSource=olRouteLayer.getSource();routeSource.clear();routeFeaturesForMap(route).forEach(f=>routeSource.addFeature(f));
  const routeAirportSource=olRouteAirportLayer.getSource();routeAirportSource.clear();olRouteAirportLayer.setVisible(mapLayerChecked('mapLayerAirports',true));if(mapLayerChecked('mapLayerAirports',true))(data.airports||[]).forEach(x=>{const f=pointFeature(x,x.icao||x.ident||'',`${x.icao||x.ident||''} ${x.name||''}`);f.set('airportLayer',true);f.set('routeAirport',true);f.set('longestRunwayFt',99999);routeAirportSource.addFeature(f)});
  const controllerSource=olControllerLayer.getSource();const coverageSource=olCoverageLayer.getSource();coverageSource.clear();
  if($('mapLayerControllers')?.checked)updatePointLayer(controllerSource,mapControllerFeatures,data.controllers||[],x=>x.callsign,x=>`${x.callsign||''} ${x.frequency||''}`,x=>`${x.callsign||''} ${x.frequency||''} · ${x.facility_label||'ATC'} · ${x.position_source||''}${x.atis?` · ${x.atis}`:''}`,x=>x.mapped);else{controllerSource.clear();mapControllerFeatures.clear()}
  if($('mapLayerCoverage')?.checked&&(olMap?.getView()?.getZoom?.()||2)<11)(data.controllers||[]).filter(x=>Number(x.facility)>1).forEach(x=>{const f=coverageFeature(x);if(f)coverageSource.addFeature(f)});
  const fmtTrafficTitle=x=>{const alt=Number.isFinite(Number(x.altitude_ft))?`${Math.round(Number(x.altitude_ft)).toLocaleString()} FT`:'ALT ---';const gs=Number.isFinite(Number(x.groundspeed_kts))?`${Math.round(Number(x.groundspeed_kts))} KT`:'GS ---';const hdg=Number.isFinite(Number(x.heading_deg))?`${Math.round(Number(x.heading_deg))}°`:'---';const route=[x.origin,x.destination].filter(Boolean).join('-')||'NO ROUTE';return `${x.callsign||'TRAFFIC'} ${x.aircraft||''} · ${route} · ${alt} · ${gs} · HDG ${hdg}`};
  const trafficSource=olTrafficLayer.getSource();if($('mapLayerTraffic')?.checked)updatePointLayer(trafficSource,mapTrafficFeatures,data.traffic||[],x=>x.callsign,x=>x.callsign||'',fmtTrafficTitle,trafficVisibleAtCurrentZoom);else{trafficSource.clear();mapTrafficFeatures.clear()}
  updateOwnshipFeature(data.ownship);
  $('mapCounts').textContent=`${data.counts?.traffic||0} AIRCRAFT / ${data.counts?.controllers||0} ATC`;$('mapFlight').textContent=liveFlightLabel(data);$('mapLiveState').textContent=data.ownship?'LIVE POSITION':'NETWORK MAP';
  if(mapMode==='follow')applyMapView(data,false);else if(mapAutoFramePending){applyMapView(data,true);mapAutoFramePending=false}
  renderMapControllerList();
}
function applyMapView(data,force=false){
  if(!olMap)return;document.querySelectorAll('[data-map-mode]').forEach(b=>b.classList.toggle('active',b.dataset.mapMode===mapMode));
  if(mapMode==='follow'&&data?.ownship){const view=olMap.getView();view.animate({center:ol.proj.fromLonLat([Number(data.ownship.lon),Number(data.ownship.lat)]),zoom:force?Math.max(12,view.getZoom()||12):view.getZoom(),duration:450});return}
  if(!force)return;
  let features=[];
  if(data?.ownship&&mapMode!=='route')features=[...olOwnshipLayer.getSource().getFeatures()];
  else if(mapMode==='route')features=[...olRouteLayer.getSource().getFeatures(),...olRouteAirportLayer.getSource().getFeatures(),...olAirportLayer.getSource().getFeatures(),...olOwnshipLayer.getSource().getFeatures()];
  else features=[...olTrafficLayer.getSource().getFeatures(),...olControllerLayer.getSource().getFeatures(),...olRouteAirportLayer.getSource().getFeatures(),...olAirportLayer.getSource().getFeatures(),...olOwnshipLayer.getSource().getFeatures()];
  const source=new ol.source.Vector({features});const extent=source.getExtent();if(extent&&extent.every(Number.isFinite)&&extent[0]!==Infinity)olMap.getView().fit(extent,{padding:[60,60,60,60],maxZoom:mapMode==='route'?8:5,duration:250});
}
function setMapMode(mode,reset=true){mapMode=mode;localStorage.setItem('opsroom-map-mode',mode);if(reset){mapAutoFramePending=true;applyMapView(mapData||{},true);mapAutoFramePending=false}}
function resetMapView(){localStorage.removeItem('opsroom-map-view-v2');mapHasStoredView=false;mapAutoFramePending=true;if(olMap)olMap.getView().setRotation(0);applyMapView(mapData||{},true);mapAutoFramePending=false}
function resetMapNorthUp(){if(!olMap)return;olMap.getView().animate({rotation:0,duration:220});setTimeout(saveMapView,260);$('mapSelected').textContent='MAP ORIENTATION RESET NORTH UP'}
function mapCenterOnAircraft(){
  if(!olMap)return;
  const own=mapData?.ownship;
  if(own&&Number.isFinite(Number(own.lat))&&Number.isFinite(Number(own.lon))){
    olMap.getView().animate({center:ol.proj.fromLonLat([Number(own.lon),Number(own.lat)]),zoom:Math.max(12,olMap.getView().getZoom()||12),duration:450});
    $('mapSelected').textContent=`OWN AIRCRAFT · ${Number(own.lat).toFixed(4)}, ${Number(own.lon).toFixed(4)}`;
    return;
  }
  const geom=olOwnshipFeature?.getGeometry?.();
  if(geom){const coord=geom.getCoordinates();olMap.getView().animate({center:coord,zoom:Math.max(12,olMap.getView().getZoom()||12),duration:450});$('mapSelected').textContent='OWN AIRCRAFT';return;}
  $('mapSelected').textContent='NO AIRCRAFT POSITION AVAILABLE';
}
function setMapCheckbox(id,value){const el=$(id);if(el)el.checked=!!value}
function applyMapPreset(preset){
  const mapPresets={
    clean:{mapLayerTraffic:true,mapLayerControllers:true,mapLayerCoverage:false,mapLayerAirports:true,mapLayerRunways:true,mapLayerSurface:true,mapLayerTaxiLabels:true,mapLayerStandLabels:true,mapLayerNavaids:false,mapLayerWaypoints:false,mapLayerAirways:false,mapLayerBoundaries:false,mapLayerNotams:false},
    route:{mapLayerTraffic:true,mapLayerControllers:true,mapLayerCoverage:false,mapLayerAirports:true,mapLayerRunways:true,mapLayerSurface:true,mapLayerTaxiLabels:true,mapLayerStandLabels:true,mapLayerNavaids:true,mapLayerWaypoints:false,mapLayerAirways:true,mapLayerBoundaries:false,mapLayerNotams:false},
    airport:{mapLayerTraffic:true,mapLayerControllers:false,mapLayerCoverage:false,mapLayerAirports:true,mapLayerRunways:true,mapLayerSurface:true,mapLayerTaxiLabels:true,mapLayerStandLabels:true,mapLayerNavaids:false,mapLayerWaypoints:false,mapLayerAirways:false,mapLayerBoundaries:false,mapLayerNotams:false},
    network:{mapLayerTraffic:true,mapLayerControllers:true,mapLayerCoverage:true,mapLayerAirports:false,mapLayerRunways:false,mapLayerSurface:false,mapLayerTaxiLabels:false,mapLayerStandLabels:false,mapLayerNavaids:false,mapLayerWaypoints:false,mapLayerAirways:false,mapLayerBoundaries:true,mapLayerNotams:false}
  };
  const cfg=mapPresets[preset]||mapPresets.clean;Object.entries(cfg).forEach(([id,value])=>setMapCheckbox(id,value));
  document.querySelectorAll('[data-map-preset]').forEach(button=>button.classList.toggle('active',button.dataset.mapPreset===preset));syncMapNotamToggle();
  if(!mapLayerChecked('mapLayerRunways',true)&&!mapLayerChecked('mapLayerSurface',true))clearAirportSurface('SURFACE LAYER OFF');
  if(mapData)renderMap(mapData);
  if(preset==='airport'){
    const target=chooseSurfaceAirport([]);
    if(target?.ident)loadAirportSurface(target.ident,{auto:false,animate:false,force:true});
    else scheduleAviationRefresh(0);
  }else scheduleAviationRefresh(60);
}
async function loadMap(force=false){try{const r=await fetch(`/api/map/live?force_refresh=${force?'true':'false'}&traffic_limit=900`,{cache:'no-store'});const d=await r.json();if(!r.ok)throw new Error(d.detail||`HTTP ${r.status}`);renderMap(d)}catch(e){$('mapLiveState').textContent=`MAP STANDBY: ${friendlyError(e.message)}`}}
function stopMapStream(){if(mapReconnectTimer){clearTimeout(mapReconnectTimer);mapReconnectTimer=null}if(mapPollTimer){clearInterval(mapPollTimer);mapPollTimer=null}if(mapSurfaceRenderTimer){clearTimeout(mapSurfaceRenderTimer);mapSurfaceRenderTimer=null}if(mapAviationRefreshTimer){clearTimeout(mapAviationRefreshTimer);mapAviationRefreshTimer=null}if(mapSocket){const x=mapSocket;mapSocket=null;try{x.close()}catch{}}}
function startMapPolling(){if(mapPollTimer||activePage!=='map')return;loadMap(false);mapPollTimer=setInterval(()=>{if(activePage==='map')loadMap(false)},3000)}
function startMapStream(){if(activePage!=='map')return;stopMapStream();initOnlineMap();setTimeout(()=>olMap?.updateSize(),50);setTimeout(()=>olMap?.updateSize(),300);$('mapLiveState').textContent='CONNECTING';const scheme=location.protocol==='https:'?'wss':'ws';const socket=new WebSocket(`${scheme}://${location.host}/ws/map`);mapSocket=socket;socket.onopen=()=>{$('mapLiveState').textContent='LIVE MAP';if(mapPollTimer){clearInterval(mapPollTimer);mapPollTimer=null}};socket.onmessage=e=>{try{if(activePage==='map')renderMap(JSON.parse(e.data))}catch(error){reportFrontendError('map.render', error?.stack || error?.message || error)}};socket.onerror=()=>startMapPolling();socket.onclose=()=>{if(mapSocket===socket)mapSocket=null;if(activePage==='map'){startMapPolling();mapReconnectTimer=setTimeout(startMapStream,5000)}}}

function procedureProgressKey(){const profile=proceduresData?.profile?.key||'auto';const callsign=flightPlan?.callsign||'session';return `opsroom-procedures:${profile}:${callsign}`}
function readProcedureProgress(){try{return JSON.parse(localStorage.getItem(procedureProgressKey())||'{}')||{}}catch{return {}}}
function writeProcedureProgress(value){localStorage.setItem(procedureProgressKey(),JSON.stringify(value))}
function procedurePhaseComplete(phase,progress){return !!phase?.items?.length&&phase.items.every(item=>progress?.[phase.key]?.[item.key])}
function nextIncompleteProcedurePhase(currentKey){const phases=proceduresData?.phases||[],progress=readProcedureProgress(),start=Math.max(0,phases.findIndex(x=>x.key===currentKey));for(let offset=1;offset<=phases.length;offset++){const phase=phases[(start+offset)%phases.length];if(!procedurePhaseComplete(phase,progress))return phase}return null}
function renderProcedures(data){
  proceduresData=data;if(!data?.ok)return;$('procedureLiveState').textContent=`${data.flight_phase||'STANDBY'} · ${data.profile?.label||'PROFILE'}`;$('procedureAircraft').textContent=data.aircraft||'AIRCRAFT NOT DETECTED';$('procedureSource').textContent=data.profile?.source||'OPS ROOM GENERIC PROFILE';
  const select=$('procedureProfile');const existing=[...select.options].map(x=>x.value);(data.available_profiles||[]).forEach(item=>{if(!existing.includes(item.key)){const option=document.createElement('option');option.value=item.key;option.textContent=item.label;select.appendChild(option)}});if(!select.dataset.userSelected)select.value=data.profile?.key===data.profile?.detected?'':data.profile?.key||'';
  const flightPhase=data.flight_phase||'';if(!procedurePhase||!data.phases?.some(x=>x.key===procedurePhase))procedurePhase=data.recommended_phase||data.phases?.[0]?.key||'';else if($('procedureFollowPhase').checked&&flightPhase&&flightPhase!==lastProcedureFlightPhase){procedurePhase=data.recommended_phase||procedurePhase}lastProcedureFlightPhase=flightPhase;
  const progress=readProcedureProgress();$('procedurePhaseTabs').innerHTML=(data.phases||[]).map(phase=>{const complete=procedurePhaseComplete(phase,progress);return `<button type="button" data-procedure-phase="${escapeHtml(phase.key)}" class="${phase.key===procedurePhase?'active ':''}${complete?'complete':''}"><span>${escapeHtml(phase.label)}</span><small>${complete?'?':phase.items?.length||0}</small></button>`}).join('');
  const phase=(data.phases||[]).find(x=>x.key===procedurePhase)||data.phases?.[0];if(!phase)return;const phaseProgress=progress[phase.key]||{};const complete=(phase.items||[]).filter(item=>phaseProgress[item.key]).length;$('procedurePhaseTitle').textContent=phase.label;$('procedureProgress').textContent=`${complete} / ${phase.items?.length||0}`;$('procedureNotice').textContent=data.notice||'';$('procedureChecklist').innerHTML=(phase.items||[]).map((item,index)=>`<label class="procedure-row ${phaseProgress[item.key]?'complete':''}"><input type="checkbox" data-procedure-item="${escapeHtml(item.key)}" ${phaseProgress[item.key]?'checked':''}/><span class="procedure-index">${String(index+1).padStart(2,'0')}</span><b>${escapeHtml(item.text)}</b>${item.note?`<small>${escapeHtml(item.note)}</small>`:''}</label>`).join('');
}
async function loadProcedures(){try{const profile=$('procedureProfile')?.value||'';const r=await fetch(`/api/procedures?profile=${encodeURIComponent(profile)}`,{cache:'no-store'});const d=await r.json();if(!r.ok)throw new Error(d.detail||`HTTP ${r.status}`);renderProcedures(d)}catch(error){$('procedureLiveState').textContent=`CHECKLIST UNAVAILABLE: ${friendlyError(error.message)}`}}
function startProcedures(){stopProcedures();loadProcedures();loadNonNormal();procedureTimer=setInterval(()=>{if(activePage==='procedures'){loadProcedures();loadNonNormal()}},5000)}
function stopProcedures(){if(procedureTimer){clearInterval(procedureTimer);procedureTimer=null}}
function resetProcedure(all=false){const progress=readProcedureProgress();if(all)writeProcedureProgress({});else{delete progress[procedurePhase];writeProcedureProgress(progress)}if(proceduresData)renderProcedures(proceduresData)}
function handleProcedureItemChange(input){
  const phase=(proceduresData?.phases||[]).find(x=>x.key===procedurePhase);if(!phase)return;const progress=readProcedureProgress();progress[procedurePhase]=progress[procedurePhase]||{};progress[procedurePhase][input.dataset.procedureItem]=input.checked;writeProcedureProgress(progress);const completed=procedurePhaseComplete(phase,progress);renderProcedures(proceduresData);
  if(completed){notifyOps({source:'PROCEDURES',title:'SECTION COMPLETE',message:phase.label,priority:'information',page:'procedures',tag:`proc-${procedureProgressKey()}-${phase.key}`});if($('procedureAutoAdvance').checked){clearTimeout(procedureAdvanceTimer);procedureAdvanceTimer=setTimeout(()=>{const next=nextIncompleteProcedurePhase(phase.key);if(next){procedurePhase=next.key;renderProcedures(proceduresData);$('procedureChecklist').scrollTop=0}else notifyOps({source:'PROCEDURES',title:'PROCEDURE COMPLETE',message:`All sections complete for ${proceduresData.profile?.label||'selected profile'}`,priority:'operational',page:'procedures',persistent:true,tag:`proc-all-${procedureProgressKey()}`})},550)}}
}

function qrhProgressKey(){const profile=qrhData?.profile?.family||'generic';const condition=qrhSelectedCondition||qrhData?.selected?.key||'none';const callsign=flightPlan?.callsign||'session';return `opsroom-qrh:${profile}:${condition}:${callsign}`}
function readQrhProgress(){try{return JSON.parse(localStorage.getItem(qrhProgressKey())||'{}')||{}}catch{return {}}}
function writeQrhProgress(value){localStorage.setItem(qrhProgressKey(),JSON.stringify(value))}
function qrhSeverityLabel(value){const text=String(value||'advisory').toUpperCase();return text==='CRITICAL'?'CRITICAL':text==='WARNING'?'WARNING':'ADVISORY'}
function renderNonNormal(data){
  qrhData=data;if(!data?.ok)return;
  $('qrhState').textContent=data.profile?.label||'QRH';$('qrhNotice').textContent=data.notice||'';
  const select=$('qrhProfile');const existing=[...select.options].map(x=>x.value);(data.available_profiles||[]).forEach(item=>{if(!existing.includes(item.key)){const option=document.createElement('option');option.value=item.key;option.textContent=item.label;select.appendChild(option)}});if(!select.dataset.userSelected)select.value=data.profile?.key===data.profile?.detected?'':data.profile?.key||'';
  $('qrhSuggestions').innerHTML=(data.suggestions||[]).length?(data.suggestions||[]).map(item=>`<button type="button" data-qrh-condition="${escapeHtml(item.key)}" class="qrh-suggestion ${escapeHtml(item.severity)}"><b>${escapeHtml(item.title)}</b><span>${escapeHtml(item.reason)}</span></button>`).join(''):'<div class="network-empty">NO TELEMETRY SUGGESTIONS</div>';
  $('qrhConditionList').innerHTML=(data.conditions||[]).map(item=>`<button type="button" data-qrh-condition="${escapeHtml(item.key)}" class="${item.key===(data.selected?.key||'')?'active ':''}${escapeHtml(item.severity)}"><span><b>${escapeHtml(item.title)}</b><small>${escapeHtml(item.category)} · ${escapeHtml(qrhSeverityLabel(item.severity))}</small></span><em>${escapeHtml(item.summary)}</em></button>`).join('')||'<div class="network-empty">NO MATCHING CHECKLISTS</div>';
  qrhSelectedCondition=data.selected?.key||'';renderQrhDetail(data.selected);
}
function renderQrhDetail(condition){
  if(!condition){$('qrhTitle').textContent='SELECT NON-NORMAL CHECKLIST';$('qrhSeverity').textContent='READY';$('qrhMemory').innerHTML='';$('qrhChecklist').innerHTML='<div class="network-empty">OPEN A QRH CONDITION FROM THE LIST.</div>';return;}
  const severity=qrhSeverityLabel(condition.severity);$('qrhTitle').textContent=condition.title;$('qrhSeverity').textContent=severity;$('qrhSeverity').className=`${String(condition.severity||'advisory').toLowerCase()}`;
  const progress=readQrhProgress();
  $('qrhMemory').innerHTML=(condition.memory_items||[]).length?`<div class="qrh-memory-title">MEMORY / IMMEDIATE ACTIONS</div>${condition.memory_items.map((item,index)=>`<label class="qrh-row memory ${progress[item.key]?'complete':''}"><input type="checkbox" data-qrh-item="${escapeHtml(item.key)}" ${progress[item.key]?'checked':''}/><span>${String(index+1).padStart(2,'0')}</span><b>${escapeHtml(item.text)}</b>${item.note?`<small>${escapeHtml(item.note)}</small>`:''}</label>`).join('')}`:'';
  $('qrhChecklist').innerHTML=(condition.sections||[]).map(section=>`<div class="qrh-section ${escapeHtml(section.kind||'qrh')}"><h3>${escapeHtml(section.title)}</h3>${(section.items||[]).map((item,index)=>`<label class="qrh-row ${progress[item.key]?'complete':''}"><input type="checkbox" data-qrh-item="${escapeHtml(item.key)}" ${progress[item.key]?'checked':''}/><span>${String(index+1).padStart(2,'0')}</span><b>${escapeHtml(item.text)}</b>${item.note?`<small>${escapeHtml(item.note)}</small>`:''}</label>`).join('')}</div>`).join('');
}
async function loadNonNormal(){try{const profile=$('qrhProfile')?.value||'';const q=qrhQuery||$('qrhSearch')?.value||'';const condition=qrhSelectedCondition||'';const url=`/api/procedures/non-normal?profile=${encodeURIComponent(profile)}&q=${encodeURIComponent(q)}&condition=${encodeURIComponent(condition)}`;const r=await fetch(url,{cache:'no-store'});const d=await r.json();if(!r.ok)throw new Error(d.detail||`HTTP ${r.status}`);renderNonNormal(d)}catch(error){$('qrhState').textContent=`QRH UNAVAILABLE: ${friendlyError(error.message)}`}}
function searchNonNormal(){qrhQuery=($('qrhSearch')?.value||'').trim();qrhSelectedCondition='';loadNonNormal()}
function clearNonNormalSearch(){qrhQuery='';$('qrhSearch').value='';qrhSelectedCondition='';loadNonNormal()}
function handleQrhItemChange(input){const progress=readQrhProgress();progress[input.dataset.qrhItem]=input.checked;writeQrhProgress(progress);renderQrhDetail(qrhData?.selected)}

function logbookRoute(entry){const f=entry?.flight||{};return `${f.origin||'----'} TO ${f.destination||'----'}`}
function logbookAircraft(entry){const f=entry?.flight||{},a=entry?.aircraft||{};return f.aircraft_icao||a.model||a.type||a.title||'AIRCRAFT'}
function logbookDate(value){if(!value)return '----';const d=new Date(value);return Number.isNaN(d.getTime())?'----':d.toLocaleDateString('en-GB',{day:'2-digit',month:'short',year:'numeric',timeZone:'UTC'}).toUpperCase()}
function logbookElapsed(start,end=null){if(!start)return '---';const a=new Date(start).getTime(),b=end?new Date(end).getTime():Date.now();if(!Number.isFinite(a)||!Number.isFinite(b)||b<a)return '---';return duration((b-a)/1000)}
function logbookTime(value){return value?utcHm(value):'----'}
function landingRate(value){const n=Number(value);return Number.isFinite(n)?`${Math.round(n)} FPM`:'NOT RECORDED'}
function money(value,symbol=''){const n=Number(value);return Number.isFinite(n)?`${symbol}${Math.round(n).toLocaleString()}`:'---'}
function renderLogbookStatistics(stats){stats=stats||{};const finance=stats.finance||{},totals=finance.totals||{},symbol=finance.symbol||'';$('logbookCount').textContent=`${String(stats.flights||0).padStart(2,'0')} FLIGHTS`;$('logbookStatistics').innerHTML=`<div><span>BLOCK TIME</span><b>${duration(stats.block_seconds)||'---'}</b></div><div><span>AIRBORNE</span><b>${duration(stats.airborne_seconds)||'---'}</b></div><div><span>DISTANCE</span><b>${formatDistance(stats.distance_nm)}</b></div><div><span>FUEL USED</span><b>${formatWeightFromLb(stats.fuel_used_lb)}</b></div><div><span>AVG LANDING</span><b>${stats.average_landing_rate_fpm?`-${Math.round(Math.abs(stats.average_landing_rate_fpm))} FPM`:'---'}</b></div><div><span>COMPLETE</span><b>${stats.complete||0}</b></div>${stats.top_airline?`<div class="logbook-top-airline"><span>MOST FLOWN</span><b>${airlineBrandHtml(stats.top_airline,'small',false)} ${escapeHtml(stats.top_airline.name||stats.top_airline.code||'---')}</b><small>${stats.top_airline.flights||0} flights</small></div>`:''}${finance.currency?`<div><span>AIRLINE BAL</span><b>${money(finance.airline_balance,symbol)}</b></div><div><span>PILOT BAL</span><b>${money(finance.pilot_balance,symbol)}</b></div><div><span>TOTAL PROFIT</span><b>${money(totals.airline_profit,symbol)}</b></div><div><span>SERVICE COSTS</span><b>${money((Number(totals.gsx_service_costs)||0)+(Number(totals.estimated_service_costs)||0),symbol)}</b></div>`:''}`}
function renderLogbookActive(active){
  const recording=!!active;$('logbookLiveState').textContent=recording?'RECORDER ACTIVE':'RECORDER ARMED';$('logbookActiveState').textContent=recording?'RECORDING':'NOT RECORDING';$('logbookStart').disabled=recording;$('logbookFinalize').disabled=!recording;$('logbookDiscard').disabled=!recording;
  if(!recording){$('logbookActive').innerHTML='<div class="network-empty">The recorder starts automatically when engines are running, the aircraft moves, or the flight is already airborne.</div>';return}
  const f=active.flight||{},t=active.times||{},m=active.metrics||{},fuel=active.fuel||{},events=operationalEvents((active.events||[]).slice().reverse().map(x=>({...x,text:x.detail})),'logbook',8);
  $('logbookActive').innerHTML=`<div class="logbook-active-ident">${airlineBrandHtml(f,'medium',false)}<strong>${escapeHtml(f.callsign||'Unassigned')}</strong><b>${escapeHtml(logbookRoute(active))}</b><span>${escapeHtml(logbookAircraft(active))}${f.registration?` · ${escapeHtml(f.registration)}`:''}</span></div><div class="logbook-active-grid"><div><span>Elapsed</span><b>${logbookElapsed(t.block_out||active.started_utc)}</b></div><div><span>Off blocks</span><b>${logbookTime(t.block_out)}</b></div><div><span>Takeoff</span><b>${logbookTime(t.takeoff)}</b></div><div><span>Landing</span><b>${logbookTime(t.landing)}</b></div><div><span>Distance</span><b>${formatDistance(m.distance_nm)}</b></div><div><span>Fuel used</span><b>${fuel.used_lb!=null?formatWeightFromLb(fuel.used_lb):'Live'}</b></div></div><div class="logbook-event-list">${events.length?events.map(x=>`<div><time>${logbookTime(x.time)}</time><b>${escapeHtml(x.kind)}</b><span>${escapeHtml(x.text)}</span></div>`).join(''):'<div class="network-empty">Waiting for flight activity</div>'}</div>`;
}
function renderLogbookEntries(entries){
  entries=entries||[];$('logbookEntries').innerHTML=entries.length?entries.map(entry=>{const f=entry.flight||{},m=entry.metrics||{},d=entry.debrief||{},dur=entry.durations||{};return `<button type="button" class="logbook-entry ${entry.id===selectedLogbookId?'active':''}" data-logbook-entry="${escapeHtml(entry.id)}"><span class="logbook-entry-date">${logbookDate(entry.started_utc)}</span>${airlineBrandHtml(f,'small',false)}<strong>${escapeHtml(f.callsign||'NO CALLSIGN')}</strong><b>${escapeHtml(logbookRoute(entry))}</b><span>${escapeHtml(logbookAircraft(entry))}</span><span>${duration(dur.block_seconds)}</span><span class="landing-grade">${escapeHtml(d.landing_grade||'NO LANDING')}</span><em>${d.score??0}</em></button>`}).join(''):'<div class="network-empty">NO COMPLETED FLIGHTS</div>';
}
function financeMiniHtml(entry){const fin=entry?.finance;if(!fin||!fin.ok)return '';const sym=fin.symbol||'';const air=fin.airline||{},pilot=fin.pilot||{},open=fin.opening_balance||{},close=fin.closing_balance||{};return `<div class="debrief-finance"><h3>FINANCE</h3><div><span>AIRLINE</span><b>${money(open.airline,sym)} ? ${money(close.airline,sym)}</b><small>${money(air.profit,sym)} flight result</small></div><div><span>PILOT</span><b>${money(open.pilot,sym)} ? ${money(close.pilot,sym)}</b><small>${money(pilot.pay,sym)} flight pay</small></div><div><span>REVENUE</span><b>${money(air.revenue?.total,sym)}</b><small>Pax + cargo</small></div><div><span>COSTS</span><b>${money(air.costs?.total,sym)}</b><small>Fuel, services, fees</small></div></div>`}
function renderLogbookDetail(entry){
  if(!entry){$('logbookDetailTitle').textContent='SELECT A RECORD';$('logbookDetail').innerHTML='<div class="network-empty">Select a flight to inspect its timings, fuel, touchdown and event timeline.</div>';$('logbookEditor').hidden=true;return}
  const f=entry.flight||{},t=entry.times||{},dur=entry.durations||{},m=entry.metrics||{},fuel=entry.fuel||{},d=entry.debrief||{},events=entry.events||[];
  const displayEvents=operationalEvents(events.slice().reverse().map(x=>({...x,text:x.detail})),'logbook',80).reverse();
  $('logbookDetailTitle').textContent=`${f.callsign||'Flight'} · ${logbookRoute(entry)}`;$('logbookDetail').innerHTML=`<div class="debrief-score"><strong>${d.score??0}</strong><span>Flight score</span><b>${escapeHtml(d.landing_grade||'Not graded')}</b></div><div class="debrief-grid"><div><span>Off / on blocks</span><b>${logbookTime(t.block_out)} / ${logbookTime(t.block_in)}</b></div><div><span>Takeoff / landing</span><b>${logbookTime(t.takeoff)} / ${logbookTime(t.landing)}</b></div><div><span>Block / airborne</span><b>${duration(dur.block_seconds)} / ${duration(dur.airborne_seconds)}</b></div><div><span>Actual / planned distance</span><b>${formatDistance(m.distance_nm)} / ${formatDistance(f.distance_nm)}</b></div><div><span>Fuel used / planned</span><b>${formatWeightFromLb(fuel.used_lb)} / ${f.planned_trip_fuel!=null?formatPlanWeight(f.planned_trip_fuel,f.fuel_units):'---'}</b></div><div><span>Landing rate</span><b>${landingRate(m.landing_rate_fpm)}</b></div><div><span>Touchdown speed</span><b>${formatSpeed(m.touchdown_speed_kts)}</b></div><div><span>Maximum altitude</span><b>${formatAltitude(m.max_altitude_ft)}</b></div><div><span>Maximum ground speed</span><b>${formatSpeed(m.max_ground_speed_kts)}</b></div><div><span>Climb / descent peak</span><b>${formatVerticalSpeed(m.max_climb_fpm)} / ${formatVerticalSpeed(m.max_descent_fpm)}</b></div></div>${financeMiniHtml(entry)}<div class="debrief-events">${displayEvents.map(x=>`<div><time>${logbookTime(x.time)}</time><b>${escapeHtml(x.kind)}</b><span>${escapeHtml(x.text)}</span></div>`).join('')}</div>`;
  $('logbookEditor').hidden=false;$('logbookRating').value=String(entry.rating||0);$('logbookNotes').value=entry.notes||'';
}
function renderLogbook(data){
  logbookData=data;renderLogbookStatistics(data.statistics);renderLogbookActive(data.active);const entries=data.entries||[];if(selectedLogbookId&&!entries.some(x=>x.id===selectedLogbookId))selectedLogbookId='';if(!selectedLogbookId&&entries.length)selectedLogbookId=entries[0].id;renderLogbookEntries(entries);renderLogbookDetail(entries.find(x=>x.id===selectedLogbookId));
}
async function loadLogbook(){
  try{
    const q=$('logbookQuery')?.value||'',encoded=encodeURIComponent(q);
    $('logbookExportCsv').href=`/api/logbook/export.csv?q=${encoded}`;
    $('logbookExportJson').href=`/api/logbook/export.json?q=${encoded}`;
    $('logbookExportPdf').href=`/api/logbook/export.pdf?q=${encoded}`;
    const r=await fetch(`/api/logbook?limit=200&q=${encoded}`,{cache:'no-store'});
    const d=await safeJsonResponse(r);
    renderLogbook(d);
  }catch(e){
    $('logbookLiveState').textContent=`LOGBOOK UNAVAILABLE: ${friendlyError(e.message)}`;
    renderLogbook({ok:false,recording:false,active:null,entries:[],count:0,statistics:{}});
  }
}
function startLogbook(){stopLogbook();loadLogbook();logbookTimer=setInterval(()=>{if(activePage==='logbook')loadLogbook()},4000)}
function stopLogbook(){if(logbookTimer){clearInterval(logbookTimer);logbookTimer=null}}
async function logbookCommand(path,method='POST'){
  $('logbookLiveState').textContent='Working...';
  try{const r=await fetchWithTimeout(path,{method},6000);await safeJsonResponse(r);$('logbookLiveState').textContent='Done'}
  catch(e){$('logbookLiveState').textContent=`Could not complete: ${friendlyError(e.message)}`}
  finally{setTimeout(loadLogbook,250)}
}
async function saveLogbookEntry(){
  if(!selectedLogbookId)return;
  try{
    const r=await fetch(`/api/logbook/${encodeURIComponent(selectedLogbookId)}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({rating:Number($('logbookRating').value),notes:$('logbookNotes').value})});
    await safeJsonResponse(r);$('logbookLiveState').textContent='DEBRIEF SAVED';await loadLogbook();
  }catch(e){$('logbookLiveState').textContent=`SAVE FAILED: ${friendlyError(e.message)}`}
}
async function deleteLogbookEntry(){if(!selectedLogbookId||!(await uiConfirm('Delete this flight record permanently?', 'DELETE')))return;const id=selectedLogbookId;selectedLogbookId='';await logbookCommand(`/api/logbook/${encodeURIComponent(id)}`,'DELETE')}

function blackBoxAdapterStatusText(data){
  const adapter=data?.current_adapter||{},fsuipc=data?.fsuipc||{},module=fsuipc.lvar_module||{},pmdg=data?.pmdg777||{};
  const label=adapter.supported?adapter.label:'GENERIC MSFS AIRCRAFT';
  const mappingCount=Number(fsuipc.registry_mapping_count||0),catalogCount=Number(data?.catalog?.mapping_count||0);
  const mapped=fsuipc.mappings_installed?`${mappingCount}/${catalogCount||mappingCount} CURATED MAPPINGS`:'MAPPINGS NOT INSTALLED';
  const wasm=module.detected?`LVAR MODULE READY${Number(module.lvar_count)?` · ${Number(module.lvar_count).toLocaleString()} DISCOVERED`:''}`:(fsuipc.found?'LVAR MODULE NOT YET VERIFIED':'FSUIPC7 NOT FOUND');
  let pmdgText='PMDG SDK STANDBY';
  if((pmdg.options_found||[]).length&&!pmdg.eula?.accepted)pmdgText='PMDG SDK EULA ACCEPTANCE REQUIRED';
  else if(pmdg.sdk?.receiving)pmdgText='PMDG 777 SDK RECEIVING';
  else if(pmdg.broadcast_enabled)pmdgText='PMDG BROADCAST ENABLED · WAITING FOR 777';
  else if((pmdg.options_found||[]).length)pmdgText='PMDG BROADCAST DISABLED';
  return {label,mapped,wasm,pmdgText};
}
function renderBlackBoxAdapterStatus(data){
  blackBoxAdapterData=data||{};
  const target=$('blackBoxAdapterStatus'),button=$('blackBoxInstallAdapters');if(!target||!button)return;
  const text=blackBoxAdapterStatusText(data),adapter=data?.current_adapter||{},fsuipc=data?.fsuipc||{},pmdg=data?.pmdg777||{};
  const healthy=!!(fsuipc.mappings_installed&&fsuipc.lvar_module?.detected);
  const adapterMode=adapter.supported?(healthy?'READY':'SETUP REQUIRED'):'GENERIC FALLBACK';
  target.innerHTML=`<b>${escapeHtml(text.label)} · ${escapeHtml(adapterMode)}</b><span>${escapeHtml(text.wasm)}</span><span>${escapeHtml(text.mapped)}</span><span>${escapeHtml(text.pmdgText)}</span>`;
  target.classList.toggle('ready',healthy);
  target.classList.toggle('warning',!healthy);
  button.disabled=blackBoxAdapterBusy;
  button.textContent=blackBoxAdapterBusy?'INSTALLING...':(healthy?'REPAIR / REFRESH ADAPTERS':'INSTALL / REPAIR ADD-ON ADAPTERS');
  button.title=(pmdg.options_found||[]).length&&!pmdg.broadcast_enabled?'Also enables PMDG 777 SDK data broadcasting safely.':'Installs compact FSUIPC LVar mappings and configures PMDG 777 when present.';
}
async function loadBlackBoxAdapterStatus(force=false){
  const now=Date.now();if(!force&&blackBoxAdapterData&&now-blackBoxAdapterLoadedAt<5000)return blackBoxAdapterData;
  try{const data=await safeJsonResponse(await fetch('/api/blackbox/adapters/status',{cache:'no-store'}));blackBoxAdapterLoadedAt=now;renderBlackBoxAdapterStatus(data);return data}
  catch(e){const target=$('blackBoxAdapterStatus');if(target)target.innerHTML=`<b>AIRCRAFT ADAPTER STATUS UNAVAILABLE</b><span>${escapeHtml(friendlyError(e.message))}</span>`;return null}
}
function formatFsuipcLogBytes(bytes){const b=Number(bytes)||0;if(b===0)return'0 B';const units=['B','KB','MB','GB','TB'];const idx=Math.min(units.length-1,Math.floor(Math.log(b)/Math.log(1024)));return`${(b/Math.pow(1024,idx)).toFixed(b<1024*1024?0:idx>=2?2:1)} ${units[idx]}`}
let blackBoxFsuipcLogLoadedAt=0,blackBoxFsuipcLogData=null;
function renderBlackBoxFsuipcLog(data){
  const target=$('blackBoxFsuipcLog'),sizeEl=$('blackBoxFsuipcLogSize'),note=$('blackBoxFsuipcLogNote'),button=$('blackBoxReduceFsuipcLog');
  if(!target||!sizeEl||!button)return;
  if(!data){sizeEl.textContent='FSUIPC not detected';button.disabled=true;return}
  const total=Number(data.total_size||0),noisy=Array.isArray(data.noisy_keys)&&data.noisy_keys.length>0,pending=Boolean(data.cleanup_pending);
  let files='';
  if(Array.isArray(data.files)){const list=data.files.filter(f=>f.exists&&f.size>1024);if(list.length){files=' · '+list.map(f=>{const short=String(f.path).split(/[\\/]/).pop();return`${short} (${formatFsuipcLogBytes(f.size)})`}).slice(0,3).join(', ')}}
  sizeEl.textContent=`Tracked log size: ${formatFsuipcLogBytes(total)}${noisy?' · loud logging switches are ON':''}${pending?' · cleanup needed':''}${files}`;
  target.classList.toggle('warning',noisy||pending);
  button.disabled=false;
  if(note)note.textContent=pending?'One or more oversized or legacy OPS ROOM log files still consume disk. Trim retries cleanup without stopping FSUIPC.':noisy?'Loud FSUIPC logging switches detected. Trim silences them and clears oversized logs without making full-size copies.':'FSUIPC logging switches are quiet and no oversized tracked log remains.';
}
async function loadBlackBoxFsuipcLogStatus(force=false){
  const now=Date.now();if(!force&&blackBoxFsuipcLogData&&now-blackBoxFsuipcLogLoadedAt<5000)return blackBoxFsuipcLogData;
  try{const data=await safeJsonResponse(await fetch('/api/blackbox/fsuipc-log/status',{cache:'no-store'}));blackBoxFsuipcLogLoadedAt=now;blackBoxFsuipcLogData=data;renderBlackBoxFsuipcLog(data);return data}
  catch(e){const target=$('blackBoxFsuipcLog');if(target){target.classList.add('warning');const sizeEl=$('blackBoxFsuipcLogSize');if(sizeEl)sizeEl.textContent='Log status unavailable'}return null}
}
async function reduceBlackBoxFsuipcLog(){
  const button=$('blackBoxReduceFsuipcLog');if(!button||button.disabled)return;
  const original=button.textContent;button.disabled=true;button.textContent='TRIMMING...';
  try{const payload=await safeJsonResponse(await fetch('/api/blackbox/fsuipc-log/reduce',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rotate_logs:true,max_bytes:50*1024*1024})}));
    if(payload?.ok===false)throw new Error(payload?.reason||'FSUIPC log trim failed');
    blackBoxFsuipcLogData=payload?.after||null;blackBoxFsuipcLogLoadedAt=Date.now();renderBlackBoxFsuipcLog(blackBoxFsuipcLogData);
    const note=$('blackBoxFsuipcLogNote'),reclaimed=Number(payload?.bytes_reclaimed||0),restart=payload?.restart_required?' Restart or reload FSUIPC for the quiet settings to take effect.':'';
    if(payload?.cleanup_complete){if(note&&payload?.restart_message)note.textContent=payload.restart_message;showToast('FSUIPC LOG','CLEANUP COMPLETE',`${payload.changed_keys?.length||0} switches silenced · ${formatFsuipcLogBytes(reclaimed)} reclaimed.${restart}`,'success')}
    else if(payload?.cleanup_status==='failed'){if(note)note.textContent='Cleanup failed for one or more files. No affected file was reported as reclaimed; check permissions and retry after closing FSUIPC.';showToast('FSUIPC LOG','TRIM FAILED',`One or more files could not be inspected or cleaned. ${formatFsuipcLogBytes(reclaimed)} was reclaimed from other files.${restart}`,'critical')}
    else{const remaining=payload?.remaining_files?.length||payload?.pending_files?.length||0;if(note)note.textContent=`Cleanup is pending for ${remaining||'one or more'} locked file${remaining===1?'':'s'}. Close FSUIPC after the flight and retry; OPS ROOM did not stop it.`;showToast('FSUIPC LOG','CLEANUP PENDING',`${formatFsuipcLogBytes(reclaimed)} reclaimed; locked or inaccessible files still remain. Retry after the flight.${restart}`,'critical')}
  }catch(e){showToast('FSUIPC LOG','TRIM FAILED',friendlyError(e.message),'critical')}
  finally{button.disabled=false;button.textContent=original}
}
async function requestPmdgSdkEulaAcceptance(){
  const dialog=$('pmdgSdkEulaDialog'),text=$('pmdgSdkEulaText'),check=$('pmdgSdkEulaCheck'),accept=$('pmdgSdkEulaAccept'),cancel=$('pmdgSdkEulaCancel'),close=$('pmdgSdkEulaClose');
  if(!dialog||!text||!check||!accept)return false;
  try{const payload=await safeJsonResponse(await fetch('/api/blackbox/adapters/pmdg-eula',{cache:'no-store'}));text.textContent=payload.text||'PMDG 777 SDK EULA text is unavailable.'}
  catch(e){showToast('PMDG 777 SDK','EULA UNAVAILABLE',friendlyError(e.message),'critical');return false}
  check.checked=false;accept.disabled=true;
  return await new Promise(resolve=>{
    let completed=false;const finish=value=>{if(completed)return;completed=true;dialog.close();cleanup();resolve(value)};
    const onCheck=()=>{accept.disabled=!check.checked};const onAccept=()=>{if(check.checked)finish(true)};const onCancel=()=>finish(false);const onNativeCancel=event=>{event.preventDefault();finish(false)};
    const cleanup=()=>{check.removeEventListener('change',onCheck);accept.removeEventListener('click',onAccept);cancel?.removeEventListener('click',onCancel);close?.removeEventListener('click',onCancel);dialog.removeEventListener('cancel',onNativeCancel)};
    check.addEventListener('change',onCheck);accept.addEventListener('click',onAccept);cancel?.addEventListener('click',onCancel);close?.addEventListener('click',onCancel);dialog.addEventListener('cancel',onNativeCancel);dialog.showModal();
  });
}
async function installBlackBoxAdapters(){
  if(blackBoxAdapterBusy)return;
  const status=await loadBlackBoxAdapterStatus(true);
  if(status?.msfs_running&&!(await uiConfirm('Microsoft Flight Simulator is currently running. OPS ROOM can install the compact mappings now, but you must close and restart MSFS and FSUIPC7 before testing them. Continue?', 'INSTALL')))return;
  let acceptPmdgEula=false;
  if((status?.pmdg777?.options_found||[]).length&&!status?.pmdg777?.eula?.accepted){acceptPmdgEula=await requestPmdgSdkEulaAcceptance();if(!acceptPmdgEula)return}
  blackBoxAdapterBusy=true;renderBlackBoxAdapterStatus(status||{});
  try{
    const response=await fetch('/api/blackbox/adapters/install',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({include_pmdg:true,accept_pmdg_sdk_eula:acceptPmdgEula})});
    const result=await safeJsonResponse(response);blackBoxAdapterLoadedAt=0;await loadBlackBoxAdapterStatus(true);
    const lvars=result?.lvar_offsets||{},pmdg=result?.pmdg777||{};
    const parts=[lvars.mapping_count?`${lvars.mapping_count} compact LVar mappings installed`:'LVar mapping unchanged'];
    if(pmdg.installed)parts.push(pmdg.changed_paths?.length?'PMDG 777 data broadcast enabled':'PMDG 777 data broadcast already enabled');
    showToast('BLACK BOX ADAPTERS','INSTALLATION COMPLETE',parts.join(' · '),'normal');
    if(result.restart_required||result.msfs_was_running)alert(result.restart_message||'Close and restart MSFS and FSUIPC7 before testing the adapters.');
  }catch(e){showToast('BLACK BOX ADAPTERS','INSTALLATION FAILED',friendlyError(e.message),'critical');await loadBlackBoxAdapterStatus(true)}
  finally{blackBoxAdapterBusy=false;renderBlackBoxAdapterStatus(blackBoxAdapterData||{})}
}
function bbHumanLabel(key){const labels={battery:'BATTERY',battery_1:'BATTERY 1',battery_2:'BATTERY 2',apu_master:'APU MASTER',apu_selector:'APU SELECTOR',apu_running:'APU',engine_mode:'ENGINE MODE',engine_1_master:'ENGINE 1 MASTER',engine_2_master:'ENGINE 2 MASTER',engine_3_master:'ENGINE 3 MASTER',engine_4_master:'ENGINE 4 MASTER',hyd_green_pressure:'GREEN HYD PRESS',hyd_blue_pressure:'BLUE HYD PRESS',hyd_yellow_pressure:'YELLOW HYD PRESS',pack_1:'PACK 1',pack_2:'PACK 2',seatbelt_sign:'SEAT BELTS',seatbelt_selector:'SEAT BELTS',beacon:'BEACON',landing_light_left:'LEFT LANDING LIGHT',landing_light_right:'RIGHT LANDING LIGHT',gear_handle:'GEAR HANDLE',autobrake:'AUTOBRAKE',flap_handle:'FLAP HANDLE',speedbrake_handle:'SPEEDBRAKE',spoilers_armed:'SPOILERS ARMED',parking_brake:'PARKING BRAKE',irs_1:'IRS 1',irs_2:'IRS 2',irs_3:'IRS 3',master_warning:'MASTER WARNING',master_caution:'MASTER CAUTION',door_1l:'DOOR 1L',door_1r:'DOOR 1R',cargo_fwd:'FWD CARGO DOOR',cargo_aft:'AFT CARGO DOOR'};return labels[key]||String(key||'').replace(/^pulse_/,'').replace(/_/g,' ').toUpperCase()}
function bbHumanValue(key,value){if(value==null)return 'N/A';if(typeof value==='boolean')return value?'ON':'OFF';const enums={engine_mode:{0:'CRANK',1:'NORM',2:'IGN/START'},apu_selector:{0:'OFF',1:'ON',2:'START'},seatbelt_selector:{0:'OFF',1:'AUTO',2:'ON'},seatbelt_sign:{0:'OFF',1:'ON'},gear_handle:{0:'UP',1:'DOWN'},flap_handle:{0:'UP',1:'1',2:'2 / 5',3:'3 / 15',4:'FULL / 20',5:'25',6:'30'},irs_1:{0:'OFF',1:'NAV',2:'ATT'},irs_2:{0:'OFF',1:'NAV',2:'ATT'},irs_3:{0:'OFF',1:'NAV',2:'ATT'},autobrake:{0:'RTO',1:'OFF',2:'DISARM',3:'1',4:'2',5:'3',6:'4',7:'MAX AUTO'}};const n=Number(value);if(Number.isFinite(n)&&enums[key]?.[Math.round(n)]!=null)return enums[key][Math.round(n)];if(Number.isFinite(n)){if(key.includes('pressure'))return `${Math.round(n).toLocaleString()} PSI`;if(key.includes('percent')||key.includes('handle'))return `${Math.round(n)}%`;return Math.abs(n)>=10?Math.round(n).toLocaleString():n.toFixed(1)}return String(value)}

function blackBoxTime(seconds){seconds=Math.max(0,Number(seconds)||0);const h=Math.floor(seconds/3600),m=Math.floor((seconds%3600)/60),s=Math.floor(seconds%60);return h?`${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`:`${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`}
function blackBoxFlightLabel(row){const f=row?.flight||{},route=[f.origin,f.destination].filter(Boolean).join(' ? ');return `${f.callsign||'FLIGHT'}${route?' · '+route:''}`}
function blackBoxTechnicalDetails(detail,id){const file=detail?.file||'---',schema=detail?.schema??'---',categories=detail?.provider_categories||detail?.capability_manifest?.providers||{},sourceParts=[categories.core?'Flight path':null,categories.controls?'Controls':null,categories.engines?'Engines':null].filter(Boolean);const source=sourceParts.length?sourceParts.join(', '):(detail?.last_provider?'Recorded':'Saving');return `<details class="blackbox-technical"><summary>More details</summary><div><span>Saved file</span><code>${escapeHtml(file)}</code></div><div><span>Recording tag</span><code title="${escapeHtml(id||'')}">${escapeHtml(id||'---')}</code></div><div><span>What was captured</span><code>${escapeHtml(source)} · ${escapeHtml(String(schema))}</code></div></details>`}
function blackBoxHealthLabel(value){const v=String(value||'').toUpperCase();return v==='OK'||v==='GOOD'?'Good':v==='WAITING'?'Starting up':v==='PARTIAL'||v==='PARTIAL_RECORDING'?'Partial':v==='STALLED'||v==='TIMEOUT'||v==='STALE'?'Telemetry lost':'Recording'}
function blackBoxSourceLabel(providers){const cats=providers||{};const parts=[cats.core?'Flight path':null,cats.controls?'Controls':null,cats.engines?'Engines':null].filter(Boolean);return parts.length?parts.join(', '):'Connecting to simulator'}
function blackBoxActiveItem(status){const id=status?.active?.recording_id;return (blackBoxData?.items||[]).find(row=>row.recording_id===id)||null}
function renderBlackBoxRecorder(status){
  const active=status?.active,item=blackBoxActiveItem(status),flight=item?.flight||{};
  $('blackBoxState').textContent=status?.replay_active?'Replaying in simulator':active?'Recording * Live':'Ready to record';
  if(active){
    const label=blackBoxFlightLabel(item||{}),health=blackBoxHealthLabel(active.data_health),quality=Number(active.data_quality),sourceText=blackBoxSourceLabel(active.provider_categories);
    const staleBanner=active.stale?`<div class="blackbox-stale-banner">STALE · TELEMETRY LOST — ${Number(active.stale_seconds||0).toFixed(0)}s without a fresh sample. The recorder is retrying FSUIPC / SimConnect; recording resumes automatically when telemetry returns.</div>`:'';
    $('blackBoxRecorder').innerHTML=`<div class="blackbox-live blackbox-fdr-live"><i></i><div><b>Recording * ${escapeHtml(active.phase||'flight')}</b><strong>${escapeHtml(label)}</strong><span>${blackBoxTime(active.elapsed_seconds)} elapsed · ${Number(active.sample_count||0).toLocaleString()} samples</span><small>${Number(active.actual_hz||0).toFixed(1)} samples/sec · capturing: ${escapeHtml(sourceText)} · quality: <em class="bb-health-${health.toLowerCase().replace(/\s+/g,'-')}">${escapeHtml(health)}</em>${Number.isFinite(quality)?` · ${quality.toFixed(1)}% valid`:''}</small></div><button id="blackBoxStopFdr" class="control-button" type="button">STOP RECORDING</button></div>${staleBanner}`;
  }else{
    $('blackBoxRecorder').innerHTML=`<div class="blackbox-ready"><b>Automatic flight-data recording</b><span>Starts when engines are running on the ground</span><small>Records flight path, motion, controls, engines and available aircraft systems through FSUIPC or SimConnect.</small></div>`;
  }
}
function renderBlackBoxLibrary(items){
  $('blackBoxCount').textContent=`${items.length} flight${items.length===1?'':'s'}`;
  if(selectedBlackBoxId&&!items.some(x=>x.recording_id===selectedBlackBoxId))selectedBlackBoxId='';
  if(!selectedBlackBoxId&&items.length)selectedBlackBoxId=items[0].recording_id;
  $('blackBoxRecordings').innerHTML=items.length?items.map(row=>{
    const active=String(row.state||'').toUpperCase()==='RECORDING',quality=Number(row.data_quality);
    return `<button type="button" class="blackbox-recording ${row.recording_id===selectedBlackBoxId?'active':''}" data-blackbox-id="${escapeHtml(row.recording_id)}"><time>${escapeHtml(logbookDate(row.started_utc))}${active?' · LIVE':''}</time>${airlineBrandHtml(row.flight||row,'small',false)}<strong>${escapeHtml(blackBoxFlightLabel(row))}</strong><span>${blackBoxTime(row.duration_seconds)} · ${Number(row.sample_count||0).toLocaleString()} samples</span><em>${active?'FDR':(Number.isFinite(quality)?quality.toFixed(1)+'%':'---')}</em></button>`
  }).join(''):'<div class="network-empty">No Black Box recordings yet.</div>';
}
function blackBoxExtent(rows,key){const values=rows.map(x=>Number(x[key])).filter(Number.isFinite);return values.length?[Math.min(...values),Math.max(...values)]:[0,1]}
function blackBoxFrameAt(cursor){const rows=blackBoxSamples;if(!rows.length)return null;let lo=0,hi=rows.length-1;while(lo<hi){const mid=Math.floor((lo+hi+1)/2);if(Number(rows[mid].elapsed||0)<=cursor)lo=mid;else hi=mid-1}return rows[lo]}
function blackBoxCurrentFrame(){return blackBoxFrameAt(blackBoxPlayback.cursor)||blackBoxSamples.at(-1)||null}
function blackBoxCanvasContext(){const canvas=$('blackBoxCanvas');if(!canvas)return null;const ctx=canvas.getContext('2d'),dpr=Math.max(1,Math.min(2,window.devicePixelRatio||1)),rect=canvas.getBoundingClientRect(),w=Math.max(600,Math.round(rect.width*dpr)),h=Math.max(360,Math.round(rect.height*dpr));if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h}ctx.clearRect(0,0,w,h);ctx.fillStyle='#070a0c';ctx.fillRect(0,0,w,h);return {canvas,ctx,dpr,w,h}}
function blackBoxWindowRows(seconds=600){
  if(!blackBoxSamples.length)return [];
  const end=Number(blackBoxPlayback.cursor||blackBoxSamples.at(-1)?.elapsed||0),start=Math.max(0,end-seconds);
  let rows=blackBoxSamples.filter(row=>Number(row.elapsed||0)>=start&&Number(row.elapsed||0)<=end+.001);
  if(rows.length<2)rows=blackBoxSamples;
  if(rows.length>2400){const step=rows.length/2400;rows=Array.from({length:2400},(_,i)=>rows[Math.min(rows.length-1,Math.floor(i*step))])}
  return rows;
}
function bbValue(row,key,digits=0,suffix=''){const n=Number(row?.[key]);return Number.isFinite(n)?`${n.toFixed(digits)}${suffix}`:'NOT AVAILABLE'}
function bbDrawEmpty(ctx,w,h,dpr,text='SELECT A BLACK BOX RECORDING'){ctx.fillStyle='#8b969c';ctx.font=`${14*dpr}px B612 Mono`;ctx.textAlign='center';ctx.fillText(text,w/2,h/2)}
function bbClipText(ctx,text,maxWidth){
  const raw=String(text??'');if(ctx.measureText(raw).width<=maxWidth)return raw;
  let value=raw;while(value.length>1&&ctx.measureText(value+'...').width>maxWidth)value=value.slice(0,-1);return value+'...';
}
function bbPanelGrid(pack,panels){
  const {ctx,dpr,w,h}=pack,pad=18*dpr,gap=12*dpr,cols=w/dpr>=980?2:1,rows=Math.ceil(panels.length/cols),cardW=(w-pad*2-gap*(cols-1))/cols,cardH=(h-pad*2-gap*(rows-1))/rows;
  panels.forEach((panel,index)=>{
    const col=index%cols,rowIndex=Math.floor(index/cols),x=pad+col*(cardW+gap),y=pad+rowIndex*(cardH+gap),header=38*dpr,plotTop=y+header,plotBottom=y+cardH-20*dpr,plotH=Math.max(32*dpr,plotBottom-plotTop),plotLeft=x+12*dpr,plotRight=x+cardW-12*dpr;
    const values=[];panel.series.forEach(series=>panel.rows.forEach(row=>{const n=Number(row[series.key]);if(Number.isFinite(n))values.push(n)}));
    let min=panel.min??(values.length?Math.min(...values):0),max=panel.max??(values.length?Math.max(...values):1);if(min===max){min-=1;max+=1}const margin=(max-min)*.08||1;min-=margin;max+=margin;
    ctx.fillStyle='#091014';ctx.fillRect(x,y,cardW,cardH);ctx.strokeStyle='#26343b';ctx.lineWidth=dpr;ctx.strokeRect(x,y,cardW,cardH);
    ctx.font=`700 ${10*dpr}px B612 Mono`;ctx.textAlign='left';ctx.fillStyle='#d4dcde';ctx.fillText(bbClipText(ctx,panel.label,cardW*.42),x+12*dpr,y+17*dpr);
    const current=panel.rows.at(-1)||{};let legendX=x+12*dpr;ctx.font=`700 ${9*dpr}px B612 Mono`;
    panel.series.forEach((series,si)=>{const value=Number(current[series.key]),label=`${series.label} ${Number.isFinite(value)?value.toFixed(series.digits??0)+(series.suffix||panel.unit||''):'---'}`;ctx.fillStyle=series.color||['#62d7e8','#d276a6','#d7c76a'][si%3];const clipped=bbClipText(ctx,label,cardW/(panel.series.length||1)-10*dpr);ctx.fillText(clipped,legendX,y+32*dpr);legendX+=cardW/(panel.series.length||1)});
    ctx.font=`${8*dpr}px B612 Mono`;ctx.textAlign='right';ctx.fillStyle='#718087';ctx.fillText(`${max.toFixed(panel.axisDigits??0)}${panel.unit||''}`,plotRight,plotTop+9*dpr);ctx.fillText(`${min.toFixed(panel.axisDigits??0)}${panel.unit||''}`,plotRight,plotBottom);
    for(let g=0;g<=3;g++){const gy=plotTop+plotH*g/3;ctx.strokeStyle='#17242a';ctx.beginPath();ctx.moveTo(plotLeft,gy);ctx.lineTo(plotRight,gy);ctx.stroke()}
    const first=Number(panel.rows[0]?.elapsed||0),last=Number(panel.rows.at(-1)?.elapsed||first+1),span=Math.max(.001,last-first);
    panel.series.forEach((series,si)=>{ctx.strokeStyle=series.color||['#62d7e8','#d276a6','#d7c76a'][si%3];ctx.lineWidth=(series.width||1.6)*dpr;ctx.beginPath();let begun=false;panel.rows.forEach(sample=>{const value=Number(sample[series.key]);if(!Number.isFinite(value))return;const px=plotLeft+(Number(sample.elapsed||first)-first)/span*(plotRight-plotLeft),py=plotBottom-(value-min)/(max-min)*plotH;begun?ctx.lineTo(px,py):ctx.moveTo(px,py);begun=true});if(begun)ctx.stroke()});
  });
}
function drawBlackBoxFlight(pack){const rows=blackBoxWindowRows(600);if(rows.length<2)return bbDrawEmpty(pack.ctx,pack.w,pack.h,pack.dpr,'WAITING FOR LIVE FLIGHT DATA');bbPanelGrid(pack,[
  {label:'ALTITUDE / RADIO HEIGHT',rows,unit:' FT',series:[{key:'altitude_ft',label:'ALT',color:'#62d7e8'},{key:'radio_altitude_ft',label:'RA',color:'#d7c76a'}]},
  {label:'AIR / GROUND SPEED',rows,unit:' KT',series:[{key:'indicated_speed_kts',label:'IAS',color:'#62d7e8'},{key:'ground_speed_kts',label:'GS',color:'#d276a6'}]},
  {label:'VERTICAL SPEED',rows,unit:' FPM',series:[{key:'vertical_speed_fpm',label:'VS',color:'#62d7e8'}]},
  {label:'ATTITUDE / LOAD',rows,series:[{key:'pitch_deg',label:'PITCH',digits:1,suffix:'°',color:'#62d7e8'},{key:'bank_deg',label:'BANK',digits:1,suffix:'°',color:'#d276a6'},{key:'g_force',label:'G',digits:2,color:'#d7c76a'}]}
])}
function bbMetricCard(pack,entry,index,totalCols=3){
  const {ctx,dpr,w,h}=pack,pad=18*dpr,gap=12*dpr,cols=w/dpr>=980?totalCols:(w/dpr>=650?2:1),rows=Math.ceil(entry.total/cols),cardW=(w-pad*2-gap*(cols-1))/cols,cardH=(h-pad*2-gap*(rows-1))/rows,x=pad+(index%cols)*(cardW+gap),y=pad+Math.floor(index/cols)*(cardH+gap),value=Number(entry.value),available=Number.isFinite(value),barX=x+12*dpr,barY=y+cardH-27*dpr,barW=cardW-24*dpr,barH=10*dpr;
  ctx.fillStyle='#091014';ctx.fillRect(x,y,cardW,cardH);ctx.strokeStyle='#26343b';ctx.strokeRect(x,y,cardW,cardH);ctx.textAlign='left';ctx.font=`700 ${9*dpr}px B612 Mono`;ctx.fillStyle='#87959b';ctx.fillText(bbClipText(ctx,entry.label,cardW-24*dpr),x+12*dpr,y+18*dpr);
  ctx.font=`700 ${16*dpr}px B612 Mono`;ctx.fillStyle=available?'#eef3f2':'#718087';const text=available?`${value.toFixed(entry.digits??(Math.abs(entry.max)<=2?2:0))}${entry.suffix||''}`:'N/A';ctx.fillText(text,x+12*dpr,y+44*dpr);
  ctx.fillStyle='#10191d';ctx.fillRect(barX,barY,barW,barH);ctx.strokeStyle='#2b3b43';ctx.strokeRect(barX,barY,barW,barH);
  if(available){if(entry.signed){const zero=barX+barW*(-entry.min)/(entry.max-entry.min),target=barX+barW*(Math.max(entry.min,Math.min(entry.max,value))-entry.min)/(entry.max-entry.min);ctx.strokeStyle='#63737a';ctx.beginPath();ctx.moveTo(zero,barY);ctx.lineTo(zero,barY+barH);ctx.stroke();ctx.fillStyle=entry.color||'#d276a6';ctx.fillRect(Math.min(zero,target),barY+2*dpr,Math.max(1*dpr,Math.abs(target-zero)),barH-4*dpr)}else{ctx.fillStyle=entry.color||'#62d7e8';ctx.fillRect(barX+2*dpr,barY+2*dpr,Math.max(0,Math.min(1,(value-entry.min)/(entry.max-entry.min)))*(barW-4*dpr),barH-4*dpr)}}
}
function renderBlackBoxControlsView(row){
  const target=$('blackBoxControlsView');if(!target)return;
  if(!row){target.innerHTML=`<div class="blackbox-empty-state">Waiting for live flight controls data...</div>`;return}
  // Correct em dash (U+2014) as the unavailable readout; replaces the legacy mojibake
  // fallback (Task 9.4 / Property 13). Kept as an escape so the source stays ASCII-clean.
  const DASH='\u2014';
  // Task 9.1 - availability helper. avail(...candidates) -> {value, ok}: ok is true ONLY for a
  // finite number, so a fresh authoritative 0 is available (0 renders as 0) while missing /
  // non-finite telemetry is unavailable and is NEVER clamped to a neutral mid-scale. This
  // replaces the old clamp(NaN,-1,1)->0 / clamp(NaN,0,100)->50 behaviour that fabricated a neutral.
  const avail=(...candidates)=>{for(const v of candidates){if(v===null||v===undefined)continue;const n=Number(v);if(Number.isFinite(n))return{value:n,ok:true}}return{value:NaN,ok:false}};
  const clampN=(v,min,max)=>Math.max(min,Math.min(max,v));
  const fmt=(value,digits=0,suffix='')=>Number.isFinite(Number(value))?`${Number(value).toFixed(digits)}${suffix}`:DASH;
  // Task 9.2 - canonical-scale defensive guard. The provider fix guarantees stick axes in
  // [-1,1]; if any not-yet-migrated adapter still emits a legacy x100 value (|v|>1.5) divide by
  // 100 and log once. Canonical values (|v|<=1.5) pass through untouched.
  const logLegacyScaleOnce=(raw)=>{try{const g=(typeof globalThis!=='undefined')?globalThis:null;if(g&&g.__bbLegacyStickScaleWarned)return;if(g)g.__bbLegacyStickScaleWarned=true;if(typeof console!=='undefined'&&console&&typeof console.warn==='function')console.warn('[BlackBox] sidestick value '+raw+' exceeds canonical [-1,1]; treating as legacy x100 (divide by 100)')}catch(_e){/* logging must never break rendering */}};
  const canonicalStick=(a)=>{if(a.ok&&Math.abs(a.value)>1.5){logLegacyScaleOnce(a.value);return{value:a.value/100,ok:true}}return a};
  // Task 9.3 - provenance-driven, role-aware labels. Degrades gracefully when control_provenance
  // is absent (older rows / generic path): falls back to today's generic labels. Never conflates
  // seat/role and never fabricates an FO signal from the captain.
  const provenance=(row.control_provenance&&typeof row.control_provenance==='object')?row.control_provenance:null;
  const roleOf=(field)=>{const p=provenance&&provenance[field];return(p&&typeof p.role==='string')?p.role:''};
  const THROTTLE_ROLE_LABEL={commanded_tla:'TLA',physical_lever:'LEVER',engine_response:'ENGINE',mapped_input:'INPUT'};

  // Sidestick / yoke - captain plus INDEPENDENT first officer (never synthesised from captain).
  const captX=canonicalStick(avail(row.pilot_aileron_input,row.aileron_position));
  const captY=canonicalStick(avail(row.pilot_elevator_input,row.elevator_position));
  const foX=canonicalStick(avail(row.pilot_aileron_input_fo));
  const foY=canonicalStick(avail(row.pilot_elevator_input_fo));
  const captOk=captX.ok&&captY.ok;
  const foPresent=foX.ok||foY.ok;
  const foOk=foX.ok&&foY.ok;
  const sidestickUnavailable=!captOk&&!foPresent;
  const stickScale=1.3;const stickMarker=(ax,ay,variant)=>{const cx=clampN(ax.value,-1,1)*40*stickScale,cy=-clampN(ay.value,-1,1)*40*stickScale,sfx=variant?` ${variant}`:'';return `<path d="M${cx-4} ${cy-4} L${cx+4} ${cy+4} M${cx+4} ${cy-4} L${cx-4} ${cy+4}" class="bb-crosshair-trail${sfx}"/><circle cx="${cx}" cy="${cy}" r="3.2" class="bb-crosshair-dot${sfx}"/><circle cx="${cx}" cy="${cy}" r="6.5" class="bb-crosshair-halo${sfx}"/>`};
  let crosshairInner;
  if(sidestickUnavailable){crosshairInner=`<text x="0" y="3" text-anchor="middle" class="bb-crosshair-unavailable">${DASH}</text>`}
  else if(foPresent){crosshairInner=(captOk?stickMarker(captX,captY,'capt'):'')+(foOk?stickMarker(foX,foY,'fo'):'')}
  else{crosshairInner=stickMarker(captX,captY,'')}
  const sidestickHead=foPresent
    ? `<span>SIDESTICK CAPT / FO</span><span class="bb-readout-group"><b class="capt">CAPT ${fmt(captX.ok?captX.value:NaN,2)} / ${fmt(captY.ok?captY.value:NaN,2)}</b><b class="fo">FO ${fmt(foX.ok?foX.value:NaN,2)} / ${fmt(foY.ok?foY.value:NaN,2)}</b></span>`
    : `<span>SIDESTICK / YOKE</span><span class="bb-readout-group"><b>X ${fmt(captX.ok?captX.value:NaN,2)}</b><b>Y ${fmt(captY.ok?captY.value:NaN,2)}</b></span>`;

  // Thrust levers - independent per engine, labelled by verified role from control_provenance.
  const engineCount=Math.max(1,Math.min(4,Number(row.engine_count)||2));
  const throttles=[];
  for(let i=1;i<=engineCount;i++){
    const pf=`pilot_throttle_${i}_percent`,ef=`throttle_${i}_percent`;
    let a=avail(row[pf]),field=pf;
    // A pilot lever is authoritative only when it actually has a validated source. For aircraft
    // with no pilot-lever mapping (e.g. Fenix) pilot_throttle_i_percent arrives as a fabricated
    // 0.0 (finite -> avail-ok) with NO control_provenance entry, which would mask the populated
    // engine throttle_i_percent. So fall back to throttle_i_percent when the pilot field is
    // absent, OR is a zero with no provenance (an unmapped/fabricated neutral, not a real idle).
    const pilotHasProvenance=!!(provenance&&provenance[pf]);
    const pilotIsZero=a.ok&&Math.abs(Number(a.value))<=1e-6;
    if(!a.ok||(pilotIsZero&&!pilotHasProvenance)){const b=avail(row[ef]);if(b.ok){a=b;field=ef}}
    throttles.push({i,a,label:(THROTTLE_ROLE_LABEL[roleOf(field)]||'LVR')})}
  const lerFill=value=>{const v=clampN(value,-25,110);return Math.round(Math.max(0,(v-(-25))/(110-(-25)))*100)};
  const throttleHead=value=>100-lerFill(value);
  const leverHtml=throttles.map(t=>t.a.ok
    ? `<div class="bb-throttle-stack"><span class="bb-throttle-label">${t.label} ${t.i}</span><div class="bb-throttle-track"><div class="bb-throttle-fill" style="height:${lerFill(t.a.value)}%"></div><div class="bb-throttle-handle" style="top:${throttleHead(t.a.value)}%"></div><div class="bb-throttle-reverse-mark"></div></div><b class="bb-readout">${fmt(t.a.value,0,'%')}</b></div>`
    : `<div class="bb-throttle-stack bb-unavailable" aria-disabled="true" style="opacity:.4"><span class="bb-throttle-label">${t.label} ${t.i}</span><div class="bb-throttle-track"><div class="bb-throttle-fill" style="height:0%"></div></div><b class="bb-readout">${DASH}</b></div>`
  ).join('');
  const throttleReadouts=throttles.map(t=>`<b>${t.i} ${t.a.ok?fmt(t.a.value,0,'%'):DASH}</b>`).join('');

  // Rudder - pedal input primary; label PEDAL vs SURFACE to match the field actually shown.
  let rud=avail(row.pilot_rudder_input),rudLabel='PEDAL';
  if(!rud.ok){const rp=avail(row.rudder_position);if(rp.ok){rud=rp;rudLabel='SURFACE'}}
  const rudderOk=rud.ok;
  const rudderPosV=rudderOk?clampN(rud.value,-1,1):0;
  const rudderLeftInput=rudderOk?clampN(-rudderPosV,0,1):0;
  const rudderRightInput=rudderOk?clampN(rudderPosV,0,1):0;

  // Brakes - independent left/right.
  const brakeLeft=avail(row.brake_left_percent,row.brake_percent);
  const brakeRight=avail(row.brake_right_percent,row.brake_percent);
  const brakeRail=(side,a)=>a.ok
    ? `<div class="bb-brake-rail"><span>${side}</span><div class="bb-brake-track"><div class="bb-brake-fill" style="height:${clampN(a.value,0,100)}%"></div></div><b>${fmt(a.value,0,'%')}</b></div>`
    : `<div class="bb-brake-rail bb-unavailable" aria-disabled="true" style="opacity:.4"><span>${side}</span><div class="bb-brake-track"><div class="bb-brake-fill" style="height:0%"></div></div><b>${DASH}</b></div>`;
  const brakeBars=brakeRail('L',brakeLeft)+brakeRail('R',brakeRight);

  // Flight surfaces - spoiler, flaps handle, flap detent (each independent).
  const spoiler=avail(row.spoiler_actual_percent,row.spoiler_percent,row.spoiler_handle_position);
  const flapPct=avail(row.flap_handle_percent,row.flap_percent);
  const flapIdx=avail(row.flap_index);
  const spoilerN=spoiler.ok?clampN(spoiler.value,0,100):0;
  const flapPctN=flapPct.ok?clampN(flapPct.value,0,100):0;
  const spoilerRail=spoiler.ok
    ? `<div class="bb-scale-rail"><span>SPOILER</span><div class="bb-scale-track"><div class="bb-scale-fill" style="height:${spoilerN}%"></div><div class="bb-scale-handle" style="bottom:${spoilerN}%"></div></div><b>${fmt(spoiler.value,0,'%')}</b></div>`
    : `<div class="bb-scale-rail bb-unavailable" aria-disabled="true" style="opacity:.4"><span>SPOILER</span><div class="bb-scale-track"><div class="bb-scale-fill" style="height:0%"></div></div><b>${DASH}</b></div>`;
  const flapRail=flapPct.ok
    ? `<div class="bb-scale-rail"><span>FLAPS</span><div class="bb-scale-track"><div class="bb-scale-fill bell" style="height:${flapPctN}%"></div><div class="bb-scale-handle bell" style="bottom:${flapPctN}%"></div></div><b>${fmt(flapPct.value,0,'%')}</b></div>`
    : `<div class="bb-scale-rail bb-unavailable" aria-disabled="true" style="opacity:.4"><span>FLAPS</span><div class="bb-scale-track"><div class="bb-scale-fill bell" style="height:0%"></div></div><b>${DASH}</b></div>`;
  // Flap detent indicator. Prefer the ACTIVE adapter's validated flap_handle enum label
  // (addon_event_meta.flap_handle.values keyed by addon_state.flap_handle) so the detent shown
  // matches the aircraft's own detent naming - e.g. the Fenix S_FC_FLAPS enum
  // (0->UP, 1->1, 2->2, 3->3, 4->FULL). This avoids the off-by-one that appears when the raw
  // generic FLAPS_HANDLE_INDEX enumerates the intermediate 1+F step differently from the lever
  // detent. Fall back to the numeric flap_index only when no adapter enum is available. Scoped to
  // present adapter metadata, so no detent is fabricated for aircraft that do not expose one.
  const bbMeta=(row.addon_event_meta&&typeof row.addon_event_meta==='object')?row.addon_event_meta:{};
  const bbAddon=(row.addon_state&&typeof row.addon_state==='object')?row.addon_state:{};
  const flapDetent=(()=>{
    const m=bbMeta.flap_handle,rawN=Number(bbAddon.flap_handle);
    if(m&&m.values&&Number.isFinite(rawN)&&m.values[String(Math.round(rawN))]!=null){return{ok:true,text:String(m.values[String(Math.round(rawN))])}}
    if(flapIdx.ok)return{ok:true,text:String(Math.round(flapIdx.value))};
    return{ok:false,text:DASH};
  })();
  const flapPosRail=flapDetent.ok
    ? `<div class="bb-scale-rail"><span>FLAP POS</span><div class="bb-scale-track plain"><b class="bb-flap-notch">${flapDetent.text}</b></div><b>${flapDetent.text}</b></div>`
    : `<div class="bb-scale-rail bb-unavailable" aria-disabled="true" style="opacity:.4"><span>FLAP POS</span><div class="bb-scale-track plain"><b class="bb-flap-notch">${DASH}</b></div><b>${DASH}</b></div>`;

  // Landing gear.
  const gear=avail(row.gear_percent);
  const gearOk=gear.ok;
  const gearPctN=gearOk?clampN(gear.value,0,100):0;
  const gearLabel=!gearOk?DASH:(gearPctN>=99?'DOWN & LOCKED':gearPctN<=1?'UP & LOCKED':'IN TRANSITION');
  const gearPhase=(gearOk&&(gearPctN>=99||gearPctN<=1))?'set':'transitioning';
  const gearHandle=row.gear_handle_down===true?'DOWN':row.gear_handle_down===false?'UP':DASH;

  target.innerHTML=`
    <div class="bb-controls-grid">
      <section class="bb-widget bb-widget-crosshair${sidestickUnavailable?' bb-unavailable':''}"${sidestickUnavailable?' aria-disabled="true" style="opacity:.4"':''}>
        <div class="bb-widget-head">${sidestickHead}</div>
        <svg class="bb-crosshair" viewBox="-50 -50 100 100" preserveAspectRatio="xMidYMid meet" aria-label="Sidestick position crosshair${foPresent?' (captain and first officer)':''}">
          <line x1="-40" y1="0" x2="40" y2="0" class="bb-crosshair-axis"/>
          <line x1="0" y1="-40" x2="0" y2="40" class="bb-crosshair-axis"/>
          <circle cx="0" cy="0" r="40" class="bb-crosshair-bowl"/>
          <circle cx="0" cy="0" r="28" class="bb-crosshair-ring"/>
          <path d="M -40 0 L -34 0 M 40 0 L 34 0 M 0 -40 L 0 -34 M 0 40 L 0 34" class="bb-crosshair-tick"/>
          ${crosshairInner}
        </svg>
        ${foPresent?`<div class="bb-crosshair-legend"><span class="capt">CAPT</span><span class="fo">FO</span></div>`:''}
      </section>

      <section class="bb-widget bb-widget-throttles">
        <div class="bb-widget-head"><span>THRUST LEVERS</span><span class="bb-readout-group">${throttleReadouts}</span></div>
        <div class="bb-throttle-levers">${leverHtml}</div>
      </section>

      <section class="bb-widget bb-widget-rudder${rudderOk?'':' bb-unavailable'}"${rudderOk?'':' aria-disabled="true" style="opacity:.4"'}>
        <div class="bb-widget-head"><span>RUDDER ${rudLabel}</span><span class="bb-readout-group"><b>POS ${rudderOk?fmt(rudderPosV,2):DASH}</b></span></div>
        <div class="bb-rudder-block">
          <div class="bb-pedal-rail"><span>L DEF</span><div class="bb-pedal-track"><div class="bb-pedal-fill" style="height:${Math.round(rudderLeftInput*100)}%"></div><div class="bb-pedal-handle" style="bottom:${Math.round(rudderLeftInput*100)}%"></div></div><b>${rudderOk?fmt(rudderLeftInput*100,0,'%'):DASH}</b></div>
          <div class="bb-pedal-rail"><span>R DEF</span><div class="bb-pedal-track"><div class="bb-pedal-fill" style="height:${Math.round(rudderRightInput*100)}%"></div><div class="bb-pedal-handle" style="bottom:${Math.round(rudderRightInput*100)}%"></div></div><b>${rudderOk?fmt(rudderRightInput*100,0,'%'):DASH}</b></div>
          <svg class="bb-rudder-svg" viewBox="0 0 100 50" preserveAspectRatio="xMidYMid meet" aria-label="Rudder deflection">
            <path d="M50 5 L50 45" class="bb-rudder-axis"/>
            ${rudderOk?`<path d="M50 25 A 25 25 0 0 ${rudderPosV>=0?1:0} ${50+rudderPosV*45*1.3} 25" fill="none" class="bb-rudder-arc"/><circle cx="${50+rudderPosV*45*1.3}" cy="25" r="3" class="bb-rudder-dot"/>`:''}
          </svg>
        </div>
      </section>

      <section class="bb-widget bb-widget-brakes">
        <div class="bb-widget-head"><span>BRAKES</span><span class="bb-readout-group"><b>L ${brakeLeft.ok?fmt(brakeLeft.value,0,'%'):DASH}</b><b>R ${brakeRight.ok?fmt(brakeRight.value,0,'%'):DASH}</b></span></div>
        <div class="bb-brake-gauges">${brakeBars}</div>
      </section>

      <section class="bb-widget bb-widget-spoiler-flap">
        <div class="bb-widget-head"><span>FLIGHT SURFACES</span><span class="bb-readout-group"><b>SPL ${spoiler.ok?fmt(spoiler.value,0,'%'):DASH}</b><b>FLP ${flapPct.ok?fmt(flapPct.value,0,'%'):DASH}</b></span></div>
        <div class="bb-scale-row">
          ${spoilerRail}
          ${flapRail}
          ${flapPosRail}
        </div>
      </section>

      <section class="bb-widget bb-widget-gear${gearOk?'':' bb-unavailable'}"${gearOk?'':' aria-disabled="true" style="opacity:.4"'}>
        <div class="bb-widget-head"><span>LANDING GEAR</span><span class="bb-readout-group"><b>${gearLabel}</b></span></div>
        <div class="bb-gear-block">
          <div class="bb-gear-piston ${gearPhase}">
            <div class="bb-gear-strut" style="height:${gearPctN}%"></div>
            <div class="bb-gear-wheel" style="bottom:${gearPctN*0.92}%"></div>
          </div>
          <div class="bb-gear-readouts">
            <article><span>EXTENDED</span><b>${gearOk?gearPctN.toFixed(0)+'%':DASH}</b></article>
            <article><span>STATUS</span><b>${gearLabel}</b></article>
            <article><span>HANDLE</span><b>${gearHandle}</b></article>
          </div>
        </div>
      </section>
    </div>`;
}
function renderBlackBoxEnginesView(row){
  const target=$('blackBoxEnginesView');if(!target)return;
  if(!row){target.innerHTML=`<div class="blackbox-empty-state">Waiting for live engine data...</div>`;return}
  // Degree sign as an escape so the source stays ASCII-clean (Property 13 / no mojibake).
  const DEG='\u00b0',MID='\u00b7';
  // Availability helper (mirrors Controls Task 9.1): ok is true ONLY for a finite number, so a
  // stopped engine's real 0 is AVAILABLE (renders 0) while a null / non-finite value (including a
  // running engine whose all-zero standard block was nulled upstream) is unavailable and renders a
  // dimmed "N/A" - never a fabricated zero.
  const avail=(...c)=>{for(const v of c){if(v===null||v===undefined)continue;const n=Number(v);if(Number.isFinite(n))return{value:n,ok:true}}return{value:NaN,ok:false}};
  const clampN=(v,min,max)=>Math.max(min,Math.min(max,v));
  // Provenance-driven thrust-lever role label (LEVER vs TLA vs ENGINE); degrades to LEVER when
  // control_provenance is absent (older rows / generic path). Never conflates roles.
  const provenance=(row.control_provenance&&typeof row.control_provenance==='object')?row.control_provenance:null;
  const roleOf=(field)=>{const p=provenance&&provenance[field];return(p&&typeof p.role==='string')?p.role:''};
  const THROTTLE_ROLE_LABEL={commanded_tla:'TLA',physical_lever:'LEVER',engine_response:'ENGINE',mapped_input:'INPUT'};

  // PMDG 777 engine source (cite PMDG Documentation/SDK/PMDG_777X_SDK.h + design section 6 / LVC9):
  // N1/N2 render from engine_{i}_n{1,2}_percent, populated from the validated 7X7X_engine{1,2}_N{1,2}
  // L:Vars. EGT / fuel flow render ONLY from the validated top-level engine_{i}_egt_c /
  // engine_{i}_fuel_flow_pph fields (sourced from L:Vars / SimVars). They are NEVER fabricated or
  // derived from PMDG_777X_Data, which exposes no N1/N2/EGT/fuel-flow gauges - when absent they
  // render unavailable ("N/A"). Twin-engine count comes from engine_count.

  // Gauge maxima are LABELED DISPLAY HINTS for arc/bar proportion only (Req 2.11, LVC7): a value
  // beyond a hint clamps visually while the numeric readout always shows the true value. No
  // redline / caution threshold is asserted where per-aircraft limits are unverified.
  const HINT={n1:110,n2:110,egt:1000,ff:9000,leverMin:-25,leverMax:110};

  const engineCount=Math.max(1,Math.min(4,Number(row.engine_count)||2));

  // Shared header - aggregate / most-relevant values.
  const aggN1=avail(row.engine_n1_percent),aggEgt=avail(row.engine_egt_c),aggFf=avail(row.fuel_flow_pph),fuel=avail(row.fuel_total_lb);
  const aggReadout=(a,digits,suffix)=>a.ok?`${a.value.toFixed(digits)}${suffix}`:'N/A';
  const header=`
    <section class="bb-engines-header bb-widget" role="group" aria-label="Engine summary">
      <div class="bb-widget-head"><span>ENGINES ${MID} ${engineCount}</span>
        <span class="bb-readout-group">
          <b data-metric="agg-n1">N1 ${aggReadout(aggN1,1,'%')}</b>
          <b data-metric="agg-egt">EGT ${aggReadout(aggEgt,0,DEG+'C')}</b>
          <b data-metric="agg-ff">FF ${aggReadout(aggFf,0,' PPH')}</b>
          <b data-metric="agg-fuel">FUEL ${aggReadout(fuel,0,' LB')}</b>
        </span>
      </div>
    </section>`;

  // Primary N1 arc gauge (semicircle r=40 centred at 50,50; 180deg left -> 0deg right).
  const arcGauge=(a,hintMax)=>{
    const frac=a.ok?clampN(a.value/hintMax,0,1):0;
    const ang=(180-frac*180)*Math.PI/180,ex=(50+40*Math.cos(ang)).toFixed(2),ey=(50-40*Math.sin(ang)).toFixed(2);
    const val=a.ok?`<path class="bb-engine-arc-val" d="M10 50 A40 40 0 0 1 ${ex} ${ey}" fill="none"/><circle class="bb-engine-arc-dot" cx="${ex}" cy="${ey}" r="3.4"/>`:'';
    return `<div class="bb-engine-primary${a.ok?'':' bb-unavailable'}" role="group" aria-label="N1 ${a.ok?a.value.toFixed(1)+' percent':'unavailable'}"${a.ok?'':' aria-disabled="true"'}>
      <svg class="bb-engine-arc" viewBox="0 0 100 62" preserveAspectRatio="xMidYMid meet" aria-label="N1 gauge, display hint max ${hintMax} percent">
        <path class="bb-engine-arc-track" d="M10 50 A40 40 0 0 1 90 50" fill="none"/>
        ${val}
      </svg>
      <div class="bb-engine-arc-readout"><b class="bb-readout" data-metric="n1">${a.ok?a.value.toFixed(1)+'%':'N/A'}</b><span>N1 ${MID} hint ${hintMax}%</span></div>
    </div>`;
  };

  // Secondary horizontal bars (N2 / EGT / FUEL FLOW).
  const bar=(a,hintMax,label,digits,suffix,metric,unitWord)=>{
    const frac=a.ok?clampN(a.value/hintMax,0,1):0;
    return `<div class="bb-engine-bar ${metric}${a.ok?'':' bb-unavailable'}" role="group" aria-label="${label} ${a.ok?a.value.toFixed(digits)+' '+unitWord:'unavailable'}, display hint max ${hintMax}"${a.ok?'':' aria-disabled="true"'}>
      <span class="bb-engine-bar-label">${label}</span>
      <div class="bb-engine-bar-track"><div class="bb-engine-bar-fill" style="width:${Math.round(frac*100)}%"></div></div>
      <b class="bb-readout" data-metric="${metric}">${a.ok?a.value.toFixed(digits)+suffix:'N/A'}</b>
    </div>`;
  };

  // Matching thrust lever (canonical -25..110 scale; role-labelled from control_provenance).
  const leverBar=(a,field,i)=>{
    const label=THROTTLE_ROLE_LABEL[roleOf(field)]||'LEVER';
    const frac=a.ok?clampN((a.value-HINT.leverMin)/(HINT.leverMax-HINT.leverMin),0,1):0;
    return `<div class="bb-engine-bar lever${a.ok?'':' bb-unavailable'}" role="group" aria-label="Thrust lever ${i} ${label} ${a.ok?a.value.toFixed(0)+' percent':'unavailable'}"${a.ok?'':' aria-disabled="true"'}>
      <span class="bb-engine-bar-label">${label} ${i}</span>
      <div class="bb-engine-bar-track"><div class="bb-engine-bar-fill" style="width:${Math.round(frac*100)}%"></div></div>
      <b class="bb-readout" data-metric="lever">${a.ok?a.value.toFixed(0)+'%':'N/A'}</b>
    </div>`;
  };

  let columns='';
  for(let i=1;i<=engineCount;i++){
    const n1=avail(row[`engine_${i}_n1_percent`]);
    const n2=avail(row[`engine_${i}_n2_percent`]);
    const egt=avail(row[`engine_${i}_egt_c`]);
    const ff=avail(row[`engine_${i}_fuel_flow_pph`]);
    const leverField=`throttle_${i}_percent`;
    const lever=avail(row[leverField],row[`pilot_throttle_${i}_percent`]);
    // Truthful engine run state (color + text; no fabricated threshold). engine_i_running is a
    // validated bool: true -> RUN, false -> OFF, null/undefined -> N/A.
    const running=row[`engine_${i}_running`];
    const status=running===true?{t:'RUN',c:'run'}:running===false?{t:'OFF',c:'off'}:{t:'N/A',c:'na'};
    columns+=`
      <section class="bb-engine-column bb-widget" role="group" aria-label="Engine ${i}" data-engine="${i}">
        <div class="bb-widget-head"><span>ENG ${i}</span><span class="bb-engine-status ${status.c}">${status.t}</span></div>
        ${arcGauge(n1,HINT.n1)}
        ${bar(n2,HINT.n2,'N2',1,'%','n2','percent')}
        ${bar(egt,HINT.egt,'EGT',0,DEG+'C','egt','celsius')}
        ${bar(ff,HINT.ff,'FUEL FLOW',0,' PPH','ff','pounds per hour')}
        ${leverBar(lever,leverField,i)}
      </section>`;
  }

  target.innerHTML=`${header}<div class="bb-engines-grid">${columns}</div>`;
}
function renderBlackBoxSystemsView(row){
  const target=$('blackBoxSystemsView');if(!target)return;
  if(!row){target.innerHTML=`<div class="blackbox-empty-state">Waiting for live systems data...</div>`;return}
  // Middot separator + degree sign as escapes so the source stays ASCII-clean (Property 13 / no mojibake).
  const MID='\u00b7',DEG='\u00b0',DASH='\u2014';
  // Minimal local HTML escaper (kept local like the Controls/Engines helpers so this renderer is
  // self-contained). Dynamic strings (adapter label, phase, AP modes, enum labels) are escaped.
  const esc=(s)=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  // addon_event_meta carries the adapter's validated labels + enum value maps. For PMDG this is the
  // SDK-documented _PMDG_META / _PMDG_META_VALUES set produced by pmdg777_sdk._decode, with
  // source:"PMDG 777 SDK" provenance (cite PMDG Documentation/SDK/PMDG_777X_SDK.h). The redesign only
  // READS these maps to regroup / re-prioritise; it NEVER renames, re-scales, or collapses them, so
  // doors (DOOR_state), autobrake (BRAKES_AutobrakeSelector), seatbelt (SIGNS_SeatBeltsSelector),
  // flaps handle (FCTL_Flaps_Lever), gear (GEAR_Lever) and master warning/caution stay intact.
  const meta=(row.addon_event_meta&&typeof row.addon_event_meta==='object')?row.addon_event_meta:{};
  const addon=(row.addon_state&&typeof row.addon_state==='object')?row.addon_state:{};

  // Domain sections in operational-priority order (warnings/cautions first, then autoflight and the
  // remaining systems). Each key is matched to the FIRST section whose keys[] lists it or whose
  // test() accepts it, so a key never duplicates across sections.
  const SECTIONS=[
    {id:'warnings',label:'WARNINGS / ECAM',keys:['master_warning','master_caution','stall_warning','overspeed_warning'],test:k=>/_warning$|_caution$|^fire_|^gpws|^tcas|^ecam/.test(k)},
    {id:'autoflight',label:'FLIGHT GUIDANCE / AUTOFLIGHT',keys:['autopilot','ap1','ap2','flight_director','autothrottle','lnav','vnav','flch','loc','app','ap_modes','ap_selected_altitude_ft','ap_selected_speed_kts','ap_selected_heading_deg','ap_selected_mach','ap_selected_vertical_speed_fpm'],test:k=>/^ap_|^mcp_|^fcu_|^athr/.test(k)},
    {id:'gearbrakes',label:'GEAR / BRAKES',keys:['gear_handle','parking_brake','autobrake','on_ground','spoilers_armed','speedbrake_handle'],test:k=>/^gear|brake|antiskid|spoiler|speedbrake/.test(k)},
    {id:'electrical',label:'ELECTRICAL / APU',keys:['battery','battery_1','battery_2','apu_master','apu_selector','apu_running','external_power_1','external_power_2'],test:k=>/^batt|^apu|^gen|generator|^bus_|^elec|external_power|^idg|^rat_/.test(k)},
    {id:'hydraulics',label:'HYDRAULICS',keys:[],test:k=>/^hyd/.test(k)},
    {id:'pneumatics',label:'PNEUMATICS / AIR',keys:['pack_1','pack_2'],test:k=>/^pack|bleed|^duct|pressuri|^air_|^cabin|^cond|xbleed/.test(k)},
    {id:'fuel',label:'FUEL',keys:['engine_mode','engine_1_master','engine_2_master','engine_3_master','engine_4_master'],test:k=>/^fuel|crossfeed|x_?feed|boost_pump|_master$/.test(k)},
    {id:'lights',label:'LIGHTS / SIGNS',keys:['beacon','strobe','taxi_light','landing_light_left','landing_light_right','seatbelt_selector','seatbelt_sign'],test:k=>/light$|^light_|_light_|beacon|strobe|seatbelt|no_smoking|^signs?_|_sign$/.test(k)},
    {id:'doors',label:'DOORS',keys:['door_1l','door_1r','cargo_fwd','cargo_aft'],test:k=>/^door|^cargo|^exit/.test(k)},
    {id:'other',label:'OTHER SYSTEMS',keys:[],test:()=>true},
  ];
  const sectionOf=(key)=>{for(const s of SECTIONS){if(s.keys.includes(key))return s.id;if(s.test&&s.test(key))return s.id}return 'other'};

  // State language. States: normal | off | clear | caution | warning | unavailable.
  //   unavailable (null / non-finite where a number is expected) -> dimmed "NOT PROVIDED" +
  //     aria-disabled, NEVER a fabricated OFF/CLEAR (Req 2.13 - a system the aircraft does not
  //     expose is never manufactured).
  //   a validated false / 0 -> OFF (or CLEAR for a warning) and is SHOWN.
  //   caution/warning -> amber/red token PLUS the text word (never colour alone).
  const isWarnKey=(key,label)=>/_warning$|_caution$/.test(key)||/WARNING|CAUTION/.test(label);
  const isCautionKey=(key,label)=>/_caution$/.test(key)||/CAUTION/.test(label);
  const numOf=(v)=>{const n=Number(v);return Number.isFinite(n)?n:null};
  const labelOf=(key)=>{const m=meta[key];return (m&&typeof m.label==='string'&&m.label)?m.label:bbHumanLabel(key)};
  function resolve(key,value,label,opts){
    opts=opts||{};
    if(value===null||value===undefined)return{text:'NOT PROVIDED',state:'unavailable'};
    // Warnings / cautions: explicit text word + severity colour.
    if(opts.warn||isWarnKey(key,label)){
      const n=numOf(value),active=(value===true)||(typeof value==='string'&&value.toUpperCase()==='ACTIVE')||(n!=null&&n>0);
      if(active)return{text:'ACTIVE',state:(opts.caution||isCautionKey(key,label))?'caution':'warning'};
      return{text:'CLEAR',state:'clear'};
    }
    // Explicit core boolean text overrides (ENGAGED/DISENGAGED, SET/RELEASED, YES/NO, ...).
    if(value===true&&opts.on)return{text:opts.on,state:'normal'};
    if(value===false&&opts.off)return{text:opts.off,state:'off'};
    // AP modes list.
    if(opts.list&&Array.isArray(value))return value.length?{text:esc(value.join(' '+MID+' ')),state:'normal'}:{text:'NONE',state:'off'};
    // Numeric core readouts (selected ALT/SPD/HDG).
    if(opts.num){const n=numOf(value);return n==null?{text:'NOT PROVIDED',state:'unavailable'}:{text:esc(String(Math.round(n))+(opts.suffix||'')),state:'normal'}}
    // Adapter enum value map (PMDG SDK-documented maps preserved EXACTLY - e.g. door CLOSED, flaps 15).
    const m=meta[key],n=numOf(value);
    if(m&&m.values&&n!=null&&m.values[String(Math.round(n))]!=null)return{text:esc(m.values[String(Math.round(n))]),state:'normal'};
    // Generic booleans.
    if(value===true)return{text:'ON',state:'normal'};
    if(value===false)return{text:'OFF',state:'off'};
    // Fallback to the existing generic human formatter (handles autobrake MAX AUTO, seatbelt, PSI, %, ...).
    return{text:esc(bbHumanValue(key,value)),state:'normal'};
  }

  // Collect entries into per-section buckets.
  const buckets={};for(const s of SECTIONS)buckets[s.id]=[];
  const seen=new Set();
  const push=(sectionId,key,label,res,source)=>{buckets[sectionId].push({key,label,text:res.text,state:res.state,warnActive:res.state==='warning'||res.state==='caution',source:source||''});seen.add(key)};

  // Core FDR system fields - always shown (unavailable when absent, distinguished from off/clear).
  const CORE=[
    {k:'autopilot',label:'AUTOPILOT',sec:'autoflight',on:'ENGAGED',off:'DISENGAGED'},
    {k:'flight_director',label:'FLIGHT DIRECTOR',sec:'autoflight',on:'ON',off:'OFF'},
    {k:'autothrottle',label:'AUTOTHROTTLE',sec:'autoflight',on:'ACTIVE',off:'OFF'},
    {k:'ap_modes',label:'AP MODES',sec:'autoflight',list:true},
    {k:'ap_selected_altitude_ft',label:'SELECTED ALT',sec:'autoflight',num:true,suffix:' FT'},
    {k:'ap_selected_speed_kts',label:'SELECTED SPEED',sec:'autoflight',num:true,suffix:' KT'},
    {k:'ap_selected_heading_deg',label:'SELECTED HEADING',sec:'autoflight',num:true,suffix:DEG},
    {k:'stall_warning',label:'STALL WARNING',sec:'warnings',warn:true},
    {k:'overspeed_warning',label:'OVERSPEED',sec:'warnings',warn:true},
    {k:'parking_brake',label:'PARKING BRAKE',sec:'gearbrakes',on:'SET',off:'RELEASED'},
    {k:'on_ground',label:'ON GROUND',sec:'gearbrakes',on:'YES',off:'NO'},
  ];
  for(const c of CORE){const res=resolve(c.k,row[c.k],c.label,c);push(c.sec,c.k,c.label,res,'')}

  // Adapter add-on states, grouped by domain. Present-but-null -> unavailable; skip pulses/buttons
  // and anything a core field already covers. Never manufacture a key the adapter did not expose.
  for(const key of Object.keys(addon)){
    if(seen.has(key)||key.startsWith('pulse_')||key.endsWith('_button'))continue;
    const label=labelOf(key);
    const res=resolve(key,addon[key],label,{});
    const source=(meta[key]&&typeof meta[key].source==='string')?meta[key].source:'';
    push(sectionOf(key),key,label,res,source);
  }

  // Header (full width above the grid): adapter identity + flight phase at a glance.
  const bbDetail=(typeof blackBoxDetail!=='undefined')?blackBoxDetail:null;
  const adapter=row.aircraft_adapter||bbDetail?.aircraft_adapter||bbDetail?.capability_manifest?.aircraft_adapter||{};
  const adapterLabel=esc(adapter.label||adapter.key||'GENERIC');
  const phase=esc(String(row.phase||DASH).toUpperCase());
  const header=`
    <section class="bb-systems-header bb-widget" role="group" aria-label="Systems summary">
      <div class="bb-widget-head"><span>SYSTEMS ${MID} ${adapterLabel}</span><span class="bb-readout-group"><b>PHASE ${phase}</b></span></div>
    </section>`;

  const rowHtml=(item)=>{
    const stateClass=item.state==='normal'?'':' '+item.state;
    const aria=item.state==='unavailable'?' aria-disabled="true"':'';
    const title=item.source?` title="${esc(item.source)}"`:'';
    return `<div class="bb-sys-row" data-sys-key="${esc(item.key)}"><span class="bb-sys-label">${esc(item.label)}</span><b class="bb-sys-value${stateClass}" data-sys-state="${item.state}"${title}${aria}>${item.text}</b></div>`;
  };

  let sectionsHtml='';
  for(const s of SECTIONS){
    const items=buckets[s.id];if(!items.length)continue;
    // Operationally-useful-first: active warnings/cautions bubble to the top of their section.
    items.sort((a,b)=>(b.warnActive-a.warnActive));
    sectionsHtml+=`<section class="bb-widget bb-systems-section" role="group" aria-label="${esc(s.label)}"><div class="bb-widget-head"><span>${esc(s.label)}</span></div><div class="bb-systems-rows">${items.map(rowHtml).join('')}</div></section>`;
  }

  target.innerHTML=`${header}<div class="bb-systems-grid">${sectionsHtml}</div>`;
}
function drawBlackBoxControls(pack){
  // The Controls view is now rendered as an HTML/SVG engineering telemetry panel
  // (see renderBlackBoxControlsView). This legacy canvas path is kept only for
  // direct canvas callers that may exist for replay without the events overlay
  // toggle; in production drawBlackBox routes directly to the SVG renderer.
  const row=blackBoxCurrentFrame();
  if(!row)return bbDrawEmpty(pack.ctx,pack.w,pack.h,pack.dpr,'WAITING FOR LIVE FLIGHT DATA');
  renderBlackBoxControlsView(row);
}
function drawBlackBoxControls(pack){
  // The Controls view is now rendered as an HTML/SVG engineering telemetry panel
  // (see renderBlackBoxControlsView). This legacy canvas path is kept only for
  // direct canvas callers that may exist for replay without the events overlay
  // toggle; in production drawBlackBox routes directly to the SVG renderer.
  const row=blackBoxCurrentFrame();
  if(!row)return bbDrawEmpty(pack.ctx,pack.w,pack.h,pack.dpr,'WAITING FOR LIVE FLIGHT DATA');
  renderBlackBoxControlsView(row);
}
function drawBlackBoxEngines(pack){
  // The Engines view is now rendered as an HTML/SVG engine-centric instrument panel
  // (see renderBlackBoxEnginesView). The legacy canvas bbMetricCard wall - with its fixed,
  // unverified N1/EGT/FF ranges - is retired; this shim is kept only for any direct canvas
  // caller and delegates to the SVG renderer, exactly as drawBlackBoxControls does.
  const row=blackBoxCurrentFrame();
  if(!row)return bbDrawEmpty(pack.ctx,pack.w,pack.h,pack.dpr,'WAITING FOR LIVE FLIGHT DATA');
  renderBlackBoxEnginesView(row);
}
function drawBlackBoxSystems(pack){
  // The Systems view is now rendered as an HTML grouped systems panel (see
  // renderBlackBoxSystemsView). The legacy canvas card-wall - with its fixed 8-key cap and weak
  // grouping - is retired; this shim is kept only for any direct canvas caller and delegates to the
  // HTML renderer, exactly as drawBlackBoxEngines does (in production drawBlackBox routes directly).
  const row=blackBoxCurrentFrame();
  if(!row)return bbDrawEmpty(pack.ctx,pack.w,pack.h,pack.dpr,'WAITING FOR LIVE FLIGHT DATA');
  renderBlackBoxSystemsView(row);
}
function drawBlackBoxTrack(pack){
  const rows=blackBoxSamples.filter(x=>Number.isFinite(Number(x.lat))&&Number.isFinite(Number(x.lon)));
  if(rows.length<2)return bbDrawEmpty(pack.ctx,pack.w,pack.h,pack.dpr,'WAITING FOR POSITION DATA');
  const {ctx,dpr,w,h}=pack,
  planned=(blackBoxDetail?.flight?.navlog||[]).filter(x=>Number.isFinite(Number(x.lat))&&Number.isFinite(Number(x.lon))),
  [minLon,maxLon]=blackBoxExtent(rows,'lon'),[minLat,maxLat]=blackBoxExtent(rows,'lat'),pad=52*dpr;
  if(planned.length>1){const[pLo,pHi]=blackBoxExtent(planned,'lon'),[pLa,pHa]=blackBoxExtent(planned,'lat'),
  aLo=minLon,aHi=maxLon,k=3;
  if(pLo<aLo&&aHi-pLo<=aHi-aLo*k)minLon=pLo;if(pHi>aHi&&pHi-aLo<=aHi-aLo*k)maxLon=pHi;
  if(pLa<minLat&&maxLat-pLa<=maxLat-minLat*k)minLat=pLa;if(pHa>maxLat&&pHa-minLat<=maxLat-minLat*k)maxLat=pHa}
  spanLon=Math.max(.0001,maxLon-minLon),spanLat=Math.max(.0001,maxLat-minLat),
  scale=Math.min((w-pad*2)/spanLon,(h-pad*2)/spanLat),
  map=row=>[pad+(Number(row.lon)-minLon)*scale,h-pad-(Number(row.lat)-minLat)*scale];
  ctx.strokeStyle='#1d2a30';
  for(let i=1;i<6;i++){ctx.beginPath();ctx.moveTo(pad,(h-pad*2)*i/6+pad);ctx.lineTo(w-pad,(h-pad*2)*i/6+pad);ctx.stroke();ctx.beginPath();ctx.moveTo((w-pad*2)*i/6+pad,pad);ctx.lineTo((w-pad*2)*i/6+pad,h-pad);ctx.stroke()}
  if(planned.length>1){ctx.save();ctx.strokeStyle='#efbd47';ctx.lineWidth=1.2*dpr;ctx.setLineDash([5,4]);ctx.beginPath();planned.forEach((x,i)=>{const [px,py]=map(x);i?ctx.lineTo(px,py):ctx.moveTo(px,py)});ctx.stroke();ctx.restore()}
  ctx.strokeStyle='#318cff';ctx.lineWidth=2*dpr;ctx.beginPath();rows.forEach((row,i)=>{const [x,y]=map(row);i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();
  const current=blackBoxCurrentFrame()||rows.at(-1),[cx,cy]=map(current),heading=(Number(current.heading_deg)||0)*Math.PI/180;
  ctx.save();ctx.translate(cx,cy);ctx.rotate(heading);ctx.fillStyle='#62d7e8';ctx.beginPath();ctx.moveTo(0,-10*dpr);ctx.lineTo(7*dpr,8*dpr);ctx.lineTo(0,4*dpr);ctx.lineTo(-7*dpr,8*dpr);ctx.closePath();ctx.fill();ctx.restore();
const start=planned.length>1?map(planned[0]):map(rows[0]),end=planned.length>1?map(planned.at(-1)):map(rows.at(-1));ctx.fillStyle='#d7c76a';
for(const point of [start,end]){ctx.beginPath();ctx.arc(point[0],point[1],4*dpr,0,Math.PI*2);ctx.fill()}
ctx.fillStyle='#aab5ba';ctx.font=`${10*dpr}px B612 Mono`;ctx.textAlign='left';
ctx.fillText(bbClipText(ctx,`START · ${blackBoxDetail?.flight?.origin||'----'}`,170*dpr),start[0]+7*dpr,start[1]-7*dpr);
ctx.fillText(bbClipText(ctx,`END · ${blackBoxDetail?.flight?.destination||'----'}`,170*dpr),end[0]+7*dpr,end[1]-7*dpr);
  ctx.fillText(bbClipText(ctx,`CURRENT ${Number(current.heading_deg||0).toFixed(0)}° · ${Number(current.ground_speed_kts||0).toFixed(0)} KT`,220*dpr),cx+10*dpr,cy+16*dpr);
  if(planned.length>1){ctx.fillStyle='#efbd47';ctx.font=`${8*dpr}px B612 Mono`;ctx.fillText('PLANNED',12,12);ctx.fillStyle='#318cff';ctx.fillText('ACTUAL',80,12)}
}
function renderBlackBoxEvents(){const target=$('blackBoxEventsView');if(!target)return;const rows=[...blackBoxEvents].sort((a,b)=>Number(a.elapsed||0)-Number(b.elapsed||0));target.innerHTML=rows.length?rows.map(row=>`<button type="button" data-bb-event-time="${Number(row.elapsed||0)}"><time>T+ ${blackBoxTime(row.elapsed)}</time><b>${escapeHtml(row.kind||'EVENT')}</b><span>${escapeHtml(row.detail||'')}</span></button>`).join(''):'<div class="network-empty">No recorded events yet.</div>'}
function blackBoxRenderSignature(view,row){
  const state={
    view,
    recording:selectedBlackBoxId,
    cursor:Number(blackBoxPlayback.cursor||0),
    samples:blackBoxSamples.length,
    events:blackBoxEvents.length,
    row:row||null,
  };
  if(view==='events')state.eventRows=blackBoxEvents;
  try{return JSON.stringify(state,(_key,value)=>typeof value==='number'&&!Number.isFinite(value)?String(value):value)}
  catch{return `${view}|${selectedBlackBoxId}|${Number(blackBoxPlayback.cursor||0)}|${Number(row?.elapsed??-1)}|${blackBoxSamples.length}|${blackBoxEvents.length}`}
}
function drawBlackBox(){
  const events=blackBoxView==='events',controls=blackBoxView==='controls',engines=blackBoxView==='engines',systems=blackBoxView==='systems';
  const domView=events||controls||engines||systems;
  const canvas=$('blackBoxCanvas'),eventsView=$('blackBoxEventsView'),controlsView=$('blackBoxControlsView'),enginesView=$('blackBoxEnginesView'),systemsView=$('blackBoxSystemsView');
  if(canvas)canvas.hidden=domView;
  if(eventsView)eventsView.hidden=!events;
  if(controlsView)controlsView.hidden=!controls;
  if(enginesView)enginesView.hidden=!engines;
  if(systemsView)systemsView.hidden=!systems;

  const row=blackBoxCurrentFrame(),signature=blackBoxRenderSignature(blackBoxView,row),unchanged=blackBoxPlayback.renderSignature===signature;
  if(domView){
    if(unchanged)return;
    blackBoxPlayback.renderSignature=signature;
    if(events)renderBlackBoxEvents();
    else if(controls)renderBlackBoxControlsView(row);
    else if(engines)renderBlackBoxEnginesView(row);
    else renderBlackBoxSystemsView(row);
    renderBlackBoxInstruments(row);
    return;
  }

  const pack=blackBoxCanvasContext();if(!pack)return;
  if(blackBoxView==='track')drawBlackBoxTrack(pack);else drawBlackBoxFlight(pack);
  if(!unchanged){blackBoxPlayback.renderSignature=signature;renderBlackBoxInstruments(row)}
}
function renderBlackBoxInstruments(row){if(!row){$('blackBoxInstruments').innerHTML='';return}if(blackBoxData?.status?.active?.stale){$('blackBoxInstruments').innerHTML=`<div class="blackbox-stale-instruments"><b>STALE</b><span>TELEMETRY LOST — ${Number(blackBoxData.status.active.stale_seconds||0).toFixed(0)}s</span><small>The last good frame is kept for review, but no new samples are arriving. Recording resumes automatically when a telemetry source recovers.</small></div>`;return}const value=(key,digits=0,suffix='')=>Number.isFinite(Number(row[key]))?`${Number(row[key]).toFixed(digits)}${suffix}`:'---';$('blackBoxInstruments').innerHTML=[['ALT',value('altitude_ft',0,' FT')],['RA',value('radio_altitude_ft',0,' FT')],['IAS',value('indicated_speed_kts',0,' KT')],['GS',value('ground_speed_kts',0,' KT')],['VS',value('vertical_speed_fpm',0,' FPM')],['HDG',value('heading_deg',0,'°')],['PITCH',value('pitch_deg',1,'°')],['BANK',value('bank_deg',1,'°')],['G',value('g_force',2,'')],['PHASE',String(row.phase||'---')]].map(([a,b])=>`<div><span>${a}</span><b>${escapeHtml(b)}</b></div>`).join('')}
function renderBlackBoxLiveSummary(status,detail=blackBoxDetail){const target=$('blackBoxLiveSummary');if(!target)return;const active=status?.active,selectedActive=active&&active.recording_id===selectedBlackBoxId;if(selectedActive){const source=blackBoxSourceLabel(active.provider_categories),health=blackBoxHealthLabel(active.data_health);target.innerHTML=`<article><span>Status</span><b>Recording · ${escapeHtml(active.phase||'flight')}</b></article><article><span>Elapsed</span><b>${blackBoxTime(active.elapsed_seconds)}</b></article><article><span>Capture rate</span><b>${Number(active.actual_hz||0).toFixed(1)} samples/sec</b></article><article><span>What is captured</span><b title="${escapeHtml(source)}">${escapeHtml(source)}</b></article><article><span>Quality</span><b>${escapeHtml(health)}</b></article><article><span>Samples being saved</span><b>${Number(active.buffer_samples||0)} queued · ${Number(active.ring_samples||0)} written</b></article>`}else if(detail){const count=Array.isArray(detail.capabilities)?detail.capabilities.length:Number(detail.capability_manifest?.counts?.core||0)+Number(detail.capability_manifest?.counts?.controls||0)+Number(detail.capability_manifest?.counts?.engines||0)+Number(detail.capability_manifest?.counts?.systems||0);const source=blackBoxSourceLabel(detail.provider_categories||detail.capability_manifest?.providers||{});target.innerHTML=`<article><span>Status</span><b>${escapeHtml(detail.state?String(detail.state).toLowerCase().replace(/^\w/,c=>c.toUpperCase()):'Saved')}</b></article><article><span>Duration</span><b>${blackBoxTime(detail.duration_seconds)}</b></article><article><span>Samples</span><b>${Number(detail.sample_count||0).toLocaleString()}</b></article><article><span>Quality</span><b>${Number.isFinite(Number(detail.data_quality))?Number(detail.data_quality).toFixed(1)+'%':'---'}</b></article><article><span>What was captured</span><b title="${escapeHtml(source)}">${escapeHtml(source)}</b></article><article><span>Parameters available</span><b>${Number.isFinite(count)?count:'---'}</b></article>`}else target.innerHTML='<div class="network-empty">Select a recording. Active flight data updates automatically.</div>'}
function renderBlackBoxReplayDiagnostics(replay){const target=$('blackBoxReplayDiagnostics');if(!target)return;if(!replay?.active){target.hidden=true;target.innerHTML='';return}target.hidden=false;const smoothLabel=String(replay.interpolation||'').toUpperCase().includes('HERMITE')?'Smooth motion (cubic)':'Smooth motion';const clockLabel=String(replay.clock_source||'').toUpperCase().includes('SIMCONNECT')?'Synced to simulator frames':String(replay.clock_source||'Steady clock');target.innerHTML=`<span>In-simulator replay</span><b>${escapeHtml(clockLabel)}</b><small>${Number(replay.frame_callbacks_per_second||0).toFixed(1)} frames/sec shown · ${Number(replay.writes_per_second||0).toFixed(1)} updates/sec to aircraft · ${Number(replay.write_latency_ms||0).toFixed(2)} ms per update · ${Number(replay.dropped_updates||0)} skipped frames · ${escapeHtml(smoothLabel)}</small>`}
function blackBoxStopAnimation(){
  if(blackBoxPlayback.raf)cancelAnimationFrame(blackBoxPlayback.raf);
  blackBoxPlayback.raf=0;
  blackBoxPlayback.lastMono=0;
}
function blackBoxStartAnimation(){
  if(activePage!=='blackbox'||!blackBoxPlayback.playing||blackBoxPlayback.raf)return;
  blackBoxPlayback.raf=requestAnimationFrame(blackBoxAnimate);
}
function blackBoxAnimate(now){
  blackBoxPlayback.raf=0;
  if(activePage!=='blackbox'||!blackBoxPlayback.playing)return;
  const max=Number($('blackBoxTimeline')?.max||0);
  if(!blackBoxPlayback.lastMono)blackBoxPlayback.lastMono=now;
  blackBoxPlayback.cursor+=(now-blackBoxPlayback.lastMono)/1000*blackBoxPlayback.speed;
  blackBoxPlayback.lastMono=now;
  if(blackBoxPlayback.cursor>=max){
    if(blackBoxPlayback.loop&&max>0)blackBoxPlayback.cursor%=max;
    else{
      blackBoxPlayback.cursor=max;
      blackBoxPlayback.playing=false;
      blackBoxStopAnimation();
      $('blackBoxPlay').textContent='PLAY REVIEW';
    }
  }
  if($('blackBoxTimeline'))$('blackBoxTimeline').value=String(blackBoxPlayback.cursor);
  if(!blackBoxPlayback.lastDraw||now-blackBoxPlayback.lastDraw>=100){blackBoxPlayback.lastDraw=now;drawBlackBox()}
  if(blackBoxPlayback.playing)blackBoxStartAnimation();
}
async function selectBlackBox(id){selectedBlackBoxId=id;blackBoxPlayback.playing=false;blackBoxStopAnimation();blackBoxRenderSig="";$('blackBoxPlay').textContent='PLAY REVIEW';try{const [detailRes,samplesRes]=await Promise.all([fetch(`/api/blackbox/${encodeURIComponent(id)}`,{cache:'no-store'}),fetch(`/api/blackbox/${encodeURIComponent(id)}/samples?max_points=18000`,{cache:'no-store'})]);const detail=await safeJsonResponse(detailRes),payload=await safeJsonResponse(samplesRes);blackBoxDetail=detail;blackBoxEvents=detail.events||[];blackBoxSamples=payload.samples||[];const active=String(detail.state||'').toUpperCase()==='RECORDING',duration=Number(detail.duration_seconds||blackBoxSamples.at(-1)?.elapsed||0);blackBoxPlayback.cursor=active?duration:0;blackBoxLiveLastElapsed=Number(blackBoxSamples.at(-1)?.elapsed??-1);$('blackBoxTimeline').max=String(Math.max(.01,duration));$('blackBoxTimeline').value=String(blackBoxPlayback.cursor);$('blackBoxReplayTitle').textContent=blackBoxFlightLabel(detail);renderAirlineIdentity('blackBoxAirlineIdentity',detail.flight||detail,'small',true,[detail.flight?.aircraft,detail.flight?.registration].filter(Boolean).join(' · '));$('blackBoxReplayState').textContent=`${active?'LIVE · ':''}${Number(detail.sample_count||0).toLocaleString()} SAMPLES · ${blackBoxTime(duration)}`;$('blackBoxDownloads').innerHTML=(active?'<span class="field-note">The crash-safe .opsbb file will be available when TAXI IN closes the recording.</span>':`<a class="control-button" href="/api/blackbox/${encodeURIComponent(id)}/download" download>OPSBB</a><a class="control-button" href="/api/blackbox/${encodeURIComponent(id)}/export.csv" download>CSV</a><a class="control-button" href="/api/blackbox/${encodeURIComponent(id)}/export.gpx" download>GPX</a><a class="control-button" href="/api/blackbox/${encodeURIComponent(id)}/export.kml" download>KML</a>`)+blackBoxTechnicalDetails(detail,id);renderBlackBoxLibrary(blackBoxData?.items||[]);renderBlackBoxLiveSummary(blackBoxData?.status||{},detail);drawBlackBox()}catch(e){$('blackBoxReplayState').textContent=`LOAD FAILED: ${friendlyError(e.message)}`}}
async function loadBlackBoxPreferences(){try{const d=await safeJsonResponse(await fetch('/api/blackbox/preferences',{cache:'no-store'})),v=d.integrations||{};if($('blackBoxEnabled'))$('blackBoxEnabled').checked=v.black_box_enabled!==false;if($('blackBoxAutoRecord'))$('blackBoxAutoRecord').checked=v.black_box_auto_record!==false;if($('blackBoxMaxHz'))$('blackBoxMaxHz').value=String(v.black_box_max_hz||30)}catch{}}
async function saveBlackBoxPreferences(){try{const d=await safeJsonResponse(await fetch('/api/blackbox/preferences',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({black_box_enabled:$('blackBoxEnabled')?.checked!==false,black_box_auto_record:$('blackBoxAutoRecord')?.checked!==false,black_box_max_hz:Number($('blackBoxMaxHz')?.value||30)})})),v=d.integrations||{};if($('blackBoxEnabled'))$('blackBoxEnabled').checked=v.black_box_enabled!==false;if($('blackBoxAutoRecord'))$('blackBoxAutoRecord').checked=v.black_box_auto_record!==false;$('blackBoxState').textContent='Black Box settings saved'}catch(e){showToast('BLACK BOX','SETTINGS NOT SAVED',friendlyError(e.message),'critical')}}
let blackBoxRenderSig="";let blackBoxLiveBusy=false;function blackBoxSig(){return `${$('blackBoxTabs')?.querySelector('.active')?.dataset?.view||''}|${selectedBlackBoxId}|${blackBoxSamples.length}|${blackBoxEvents.length}|${Math.round(blackBoxPlayback.cursor*100)}`}
async function loadBlackBoxLive(){if(blackBoxLiveBusy)return;blackBoxLiveBusy=true;const active=blackBoxData?.status?.active;if(!active||active.recording_id!==selectedBlackBoxId){blackBoxLiveBusy=false;return}try{const url=`/api/blackbox/live?recording_id=${encodeURIComponent(selectedBlackBoxId)}&after_elapsed=${Math.max(-1,blackBoxLiveLastElapsed)}&max_points=5000`,payload=await safeJsonResponse(await fetch(url,{cache:'no-store'}));const incoming=payload.samples||[];let changed=incoming.length>0||(payload.events||[]).length>0;if(incoming.length){const known=new Set(blackBoxSamples.slice(-6000).map(row=>`${row.elapsed}|${row.utc||''}`));for(const row of incoming){const key=`${row.elapsed}|${row.utc||''}`;if(!known.has(key)){blackBoxSamples.push(row);known.add(key)}}if(blackBoxSamples.length>18000)blackBoxSamples=blackBoxSamples.slice(-18000);blackBoxLiveLastElapsed=Number(blackBoxSamples.at(-1)?.elapsed??blackBoxLiveLastElapsed);if(!blackBoxPlayback.playing&&!blackBoxData?.replay?.active){blackBoxPlayback.cursor=blackBoxLiveLastElapsed;$('blackBoxTimeline').value=String(blackBoxPlayback.cursor)}}const eventKeys=new Set(blackBoxEvents.map(row=>`${row.elapsed}|${row.kind}|${row.detail}`));for(const row of payload.events||[]){const key=`${row.elapsed}|${row.kind}|${row.detail}`;if(!eventKeys.has(key)){blackBoxEvents.push(row);eventKeys.add(key)}}const liveStatus=payload.status||blackBoxData.status;blackBoxData.status=liveStatus;const duration=Number(liveStatus?.active?.elapsed_seconds||blackBoxLiveLastElapsed||0);const sig=blackBoxSig();if(sig!==blackBoxRenderSig||changed){blackBoxRenderSig=sig;$('blackBoxTimeline').max=String(Math.max(.01,duration));$('blackBoxReplayState').textContent=`LIVE · ${Number(liveStatus?.active?.sample_count||blackBoxSamples.length).toLocaleString()} SAMPLES · ${blackBoxTime(duration)}`;renderBlackBoxRecorder(liveStatus);renderBlackBoxLiveSummary(liveStatus,blackBoxDetail)}}catch{}finally{blackBoxLiveBusy=false}}
async function loadBlackBox(force=false){if(blackBoxLoadBusy)return;blackBoxLoadBusy=true;try{const now=Date.now();await loadBlackBoxAdapterStatus(force);await loadBlackBoxFsuipcLogStatus(force);const needLibrary=force||!blackBoxData||now-Number(blackBoxData._loadedAt||0)>900;if(needLibrary){const d=await safeJsonResponse(await fetch('/api/blackbox/recordings?limit=300',{cache:'no-store'}));d._loadedAt=now;blackBoxData=d;renderBlackBoxRecorder(d.status||{});renderBlackBoxLibrary(d.items||[]);const replay=d.replay||{};$('blackBoxSimReplay').disabled=!selectedBlackBoxId||!!replay.active||String(blackBoxDetail?.state||'').toUpperCase()==='RECORDING';$('blackBoxSimStop').disabled=!replay.active;renderBlackBoxReplayDiagnostics(replay);if(replay.active){blackBoxPlayback.playing=false;blackBoxStopAnimation();blackBoxPlayback.cursor=Number(replay.cursor||0);if($('blackBoxTimeline'))$('blackBoxTimeline').value=String(blackBoxPlayback.cursor);$('blackBoxPlay').textContent=replay.playing?'PAUSE IN-SIM':'PLAY IN-SIM';$('blackBoxReplayState').textContent=`IN-SIM ${replay.playing?'PLAYING':'PAUSED'} · ${blackBoxTime(replay.cursor)} / ${blackBoxTime(replay.duration)}`}else if($('blackBoxPlay')&&!blackBoxPlayback.playing)$('blackBoxPlay').textContent='PLAY REVIEW';if(selectedBlackBoxId&&(!blackBoxDetail||blackBoxDetail.recording_id!==selectedBlackBoxId))await selectBlackBox(selectedBlackBoxId);renderBlackBoxLiveSummary(d.status||{},blackBoxDetail)}await loadBlackBoxLive()}catch(e){$('blackBoxState').textContent=`BLACK BOX UNAVAILABLE: ${friendlyError(e.message)}`}finally{blackBoxLoadBusy=false}}
let blackBoxFullTimer=null;
function scheduleBlackBoxPoll(delay=200){
  if(blackBoxTimer)clearTimeout(blackBoxTimer);
  const cadence=Math.max(200,Number(delay)||200);
  blackBoxTimer=setTimeout(async()=>{
    if(activePage==='blackbox'){
      await loadBlackBoxLive();
      const sig=blackBoxSig();
      if(sig!==blackBoxRenderSig){blackBoxRenderSig=sig;if(!blackBoxPlayback.playing)drawBlackBox()}
      scheduleBlackBoxPoll(200);
    }
  },cadence);
}
function scheduleBlackBoxFullRefresh(){if(blackBoxFullTimer)clearTimeout(blackBoxFullTimer);blackBoxFullTimer=setTimeout(async()=>{if(activePage==='blackbox'){await loadBlackBox(false)};scheduleBlackBoxFullRefresh()},5000)}
function startBlackBox(){
  stopBlackBox();
  loadBlackBoxPreferences();
  loadBlackBox(true).finally(()=>{scheduleBlackBoxPoll(200);scheduleBlackBoxFullRefresh()});
  const pulse=$('blackBoxLivePulse');if(pulse)pulse.classList.remove('paused');
}
function stopBlackBox(){
  if(blackBoxTimer){clearTimeout(blackBoxTimer);blackBoxTimer=null}
  if(blackBoxFullTimer){clearTimeout(blackBoxFullTimer);blackBoxFullTimer=null}
  blackBoxPlayback.playing=false;
  blackBoxStopAnimation();
  blackBoxLoadBusy=false;
  const pulse=$('blackBoxLivePulse');if(pulse)pulse.classList.add('paused');
}
async function startInSimReplay(){if(!selectedBlackBoxId)return;const warning='In-simulator replay will take control of your aircraft and move it through the recorded flight path. Before you continue:\n\n* Disconnect from any online network (VATSIM, IVAO, etc.)\n* Load the same aircraft you flew in the recording\n* Park near where the recording started\n\nOPS ROOM will not move your camera. Click OK to begin.';if(!(await uiConfirm(warning, 'START REPLAY')))return;try{const r=await fetch(`/api/blackbox/${encodeURIComponent(selectedBlackBoxId)}/replay/start`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({speed:Number($('blackBoxSpeed').value||1),loop:$('blackBoxLoop').checked,cursor:Number($('blackBoxTimeline').value||0)})});await safeJsonResponse(r);await loadBlackBox(true)}catch(e){showToast('BLACK BOX','COULD NOT START IN-SIMULATOR REPLAY',friendlyError(e.message),'critical')}}
async function controlInSim(payload){try{const r=await fetch('/api/blackbox/replay/control',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});await safeJsonResponse(r);await loadBlackBox(true)}catch(e){showToast('BLACK BOX','COULD NOT CONTROL THE REPLAY',friendlyError(e.message),'critical')}}
async function stopInSimReplay(){try{await safeJsonResponse(await fetch('/api/blackbox/replay/stop',{method:'POST'}));await loadBlackBox(true)}catch(e){showToast('BLACK BOX','COULD NOT RELEASE THE AIRCRAFT',friendlyError(e.message),'critical')}}

async function loadFinances(){
  if(!financeCareerEnabled())return;
  try{const r=await fetch('/api/economy/status',{cache:'no-store'});const d=await r.json();if(!r.ok)throw new Error(d.detail||`HTTP ${r.status}`);renderFinances(d)}
  catch(e){if($('financeState'))$('financeState').textContent=`FINANCES UNAVAILABLE: ${friendlyError(e.message)}`}
}
function rankStr(row){return row?`${escapeHtml(row.label)} · ${row.pireps} PIREPs / ${row.block_hours}h`:'MAX RANK'}
function rankInsignia(key){const spec={cadet:[1,'cadet'],junior_first_officer:[2,'junior'],first_officer:[2,'first-officer'],senior_first_officer:[3,'senior-first-officer'],captain:[4,'captain'],senior_captain:[4,'senior-captain'],training_captain:[4,'training-captain'],line_check_captain:[4,'line-check'],base_captain:[4,'base-captain'],fleet_captain:[4,'fleet-captain']}[String(key||'').toLowerCase()]||[1,'cadet'];return `<i class="rank-insignia rank-${spec[1]}" aria-hidden="true">${Array.from({length:spec[0]},()=>'<u></u>').join('')}</i>`}
function financeFareSettingsFromUi(){return {auto:!!$('financeFareAuto')?.checked,economy_fare:$('financeEconomyFare')?.value||null,business_fare:$('financeBusinessFare')?.value||null,first_fare:$('financeFirstFare')?.value||null,cargo_rate:$('financeCargoRate')?.value||null,economy_pct:$('financeEconomyPct')?.value||90,business_pct:$('financeBusinessPct')?.value||10,first_pct:$('financeFirstPct')?.value||0}}
function finiteNumberOrUndefined(value){
  if(value === null || value === undefined || value === '') return undefined;
  const n = Number(value);
  return Number.isFinite(n) ? n : undefined;
}
function financeOperationFromUi(){
  const value = String($('financeOperationType')?.value || 'auto').toLowerCase();
  return ['auto','passenger','freighter','combi','ferry'].includes(value) ? value : 'auto';
}
function financeCommercialFreightFromUi(){
  const raw = $('financeCommercialFreight')?.value;
  if(raw === null || raw === undefined || String(raw).trim() === '') return undefined;
  const n = Number(raw);
  return Number.isFinite(n) && n >= 0 ? n : undefined;
}
// v0.25.65: operation-aware load model. Explicit zero passengers stays zero,
// the combined SimBrief cargo is cargo_hold_total (BAGS/CARGO), commercial
// freight comes from the manual field or SimBrief's verified freight_added,
// and plan trip fuel is normalized to LB for the estimator.
function financeMetaFromPlan(){
  const plan=flightPlan||{},ofp=plan.ofp||plan,general=ofp?.general||{},origin=ofp.origin||{},destination=ofp.destination||{},weights=ofp.weights||{},fuel=ofp.fuel||{};
  const distance=finiteNumberOrUndefined(general.route_distance||general.distance||ofp.distance_nm||plan.distance_nm)||300;
  const blockSeconds=finiteNumberOrUndefined(general.block_time_seconds||general.est_block_time_seconds)||(general.block_time?String(general.block_time).split(':').reduce((a,b)=>a*60+Number(b||0),0):null)||Math.max(1800,distance/430*3600+1800);
  const weightUnits=String(weights.units||plan.weights?.units||'').toUpperCase();
  const fuelUnits=String(fuel.units||plan.fuel?.units||'').toUpperCase();
  const pax=finiteNumberOrUndefined(general.passengers||weights.pax_count||weights.passengers||plan.weights?.passengers);
  const cargoHold=finiteNumberOrUndefined(weights.cargo||weights.payload_cargo||plan.weights?.cargo);
  const manualFreight=financeCommercialFreightFromUi();
  const freight=manualFreight!==undefined?manualFreight:finiteNumberOrUndefined(weights.freight_added||plan.weights?.freight_added);
  const tripFuel=finiteNumberOrUndefined(fuel.plan_ramp||fuel.trip||fuel.enroute_burn||plan.fuel?.trip);
  const tripFuelLb=tripFuel===undefined?undefined:(String(fuelUnits).startsWith('KG')?tripFuel/0.45359237:tripFuel);
  return {flight:{
    origin:origin.icao_code||origin.icao||plan.origin?.icao||plan.origin||'',
    destination:destination.icao_code||destination.icao||plan.destination?.icao||plan.destination||'',
    aircraft_icao:general.aircraft_icao||ofp.aircraft?.icao||plan.aircraft_icao||'',
    passengers:pax,
    cargo:cargoHold,
    cargo_hold_total:cargoHold,
    commercial_freight_weight:freight,
    payload:finiteNumberOrUndefined(weights.payload||plan.weights?.payload),
    weight_units:weightUnits,
    fuel_units:fuelUnits,
    operation_type_requested:financeOperationFromUi(),
    distance_nm:distance,
    planned_trip_fuel:tripFuelLb
  },durations:{block_seconds:blockSeconds},finance_options:{fare_settings:financeFareSettingsFromUi()}};
}
async function loadFinanceEstimate(){if(!$('financeEstimate')||!financeCareerEnabled())return;try{const payload=financeMetaFromPlan();const r=await fetch('/api/economy/estimate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const d=await safeJsonResponse(r);renderFinanceEstimate(d)}catch(e){$('financeEstimate').innerHTML=`<div class="network-empty">ESTIMATE UNAVAILABLE: ${escapeHtml(friendlyError(e.message))}</div>`}}
function financeCostSource(value){const key=String(value||'').toLowerCase();if(key==='gsx')return 'GSX receipt';if(key==='estimated-from-departure')return 'Estimated from departure';if(key==='estimated-from-arrival')return 'Estimated from arrival';if(key==='ops-room-estimate')return 'OPS ROOM estimate';return key==='mixed'?'GSX + estimate':key==='estimated'?'Estimated':key||'Not available'}
function renderFinanceEstimate(d){
  if(!d?.ok){if($('financeEstimate'))$('financeEstimate').innerHTML='<div class="network-empty">Finance & Career is disabled in Settings.</div>';return}
  const sym=d.symbol||'',air=d.airline||{},pilot=d.pilot||{},route=d.route||{},pax=d.passengers||{},fares=d.fares||{},costs=air.costs||{};
  const depSource=financeCostSource(costs.ground_services_departure_source),arrSource=financeCostSource(costs.ground_services_arrival_source);
  const opLabel=String(d.operation?.resolved||'auto').toUpperCase();
  const freightHtml=(d.commercial_freight_weight!==null&&d.commercial_freight_weight!==undefined)?`<article><span>Commercial freight</span><b>${numberOr(d.commercial_freight_weight)} ${escapeHtml(unitPrefs().weight.toUpperCase())}</b><small>${d.commercial_freight_weight>0?`Freight revenue ${money(d.commercial_freight_revenue,d.symbol)}`:'No revenue-generating freight'}</small></article>`:'';
  const paxHtml=pax.total!==undefined&&pax.total!==null?`<b>${pax.total}</b><small>Economy ${pax.economy||0} · Business ${pax.business||0} · First ${pax.first||0}</small>`:`<b>—</b><small>No passenger load for this operation</small>`;
  $('financeEstimate').innerHTML=`<div class="finance-statement-grid"><article><span>Flight plan</span><b>${escapeHtml(route.origin||'----')} ? ${escapeHtml(route.destination||'----')}</b><small>${Number(route.distance_nm||0).toFixed(0)} NM planned distance</small></article><article><span>Operation</span><b>${escapeHtml(opLabel)}</b><small>${escapeHtml(d.operation?.reason||'Automatic classification')}</small></article><article><span>Passenger plan</span>${paxHtml}</article>${freightHtml}<article><span>Automatic fare plan</span><b>${money(fares.economy,sym)} / ${money(fares.business,sym)} / ${money(fares.first,sym)}</b><small>Economy · Business · First</small></article><article><span>Expected revenue</span><b>${money(air.revenue?.total,sym)}</b><small>Passengers ${money(air.revenue?.passenger,sym)} · Cargo ${money(air.revenue?.cargo,sym)}</small></article><article><span>Expected operating cost</span><b>${money(costs.total,sym)}</b><small>Fuel ${money(costs.fuel,sym)} · Services ${money(costs.ground_services,sym)}</small></article><article><span>Expected flight result</span><b class="${Number(air.profit)>=0?'profit-positive':'profit-negative'}">${money(air.profit,sym)}</b><small>Estimate before the flight is posted</small></article><article><span>Estimated pilot pay</span><b>${money(pilot.pay,sym)}</b><small>${escapeHtml(pilot.rank?.label||'Pilot')} · current pay model</small></article><article><span>Ground-service basis</span><b>${money(costs.ground_services,sym)}</b><small>Departure ${money(costs.ground_services_departure,sym)} · ${escapeHtml(depSource)}<br>Arrival ${money(costs.ground_services_arrival,sym)} · ${escapeHtml(arrSource)}</small></article></div>`
}

function renderFinances(data){
  renderAirlineIdentity('financeAirlineIdentity',flightPlan,'large',true,flightPlan?.callsign||'AIRLINE ACCOUNT');
  if(!data?.enabled){
    if($('financeState'))$('financeState').textContent='Disabled in Settings';
    if($('financeSummary'))$('financeSummary').innerHTML='<div class="network-empty">Finance & Career is disabled. Existing history is preserved.</div>';
    return;
  }
  const career=data.career||{},tot=data.totals||{},rank=data.rank||{},cur=rank.current||{},next=rank.next||null,progress=rank.progress||{},fare=career.fare_settings||{},sym=data.symbol||'';
  const latest=(data.ledger||[])[0],st=latest?.statement||{},air=st.airline||{},pilot=st.pilot||{},route=st.route||{};
  const satis=st.passenger_satisfaction||{};
  if($('financeState'))$('financeState').textContent=`Active · ${data.currency||'EUR'}`;
  // v0.25.16: satisfaction cards integrated into finance summary
  const satisHtml=latest&&satis&&typeof satis.score==='number'?`<article><span>Passenger satisfaction</span><b class="${satis.score>=75?'profit-positive':satis.score>=50?'':'profit-negative'}">${satis.score}%</b><small>${escapeHtml(satis.category||'N/A')} · mult ${Number(satis.revenue_multiplier||1).toFixed(2)}x</small></article>`:'';
  const lifetimeSatisHtml=(()=>{
    const scores=(data.ledger||[]).map(e=>{const s=(e.statement||{}).passenger_satisfaction||{};return typeof s.score==='number'?s.score:null}).filter(s=>s!==null);
    if(!scores.length)return'';
    const avg=Math.round(scores.reduce((a,b)=>a+b,0)/scores.length);
    return`<article><span>Avg passenger satisfaction</span><b class="${avg>=75?'profit-positive':avg>=50?'':'profit-negative'}">${avg}%</b><small>Lifetime average · ${scores.length} flights</small></article>`;
  })();
  const latestHtml=latest?`<section><h3>Latest completed flight</h3><div class="finance-kpi-row"><article><span>Flight</span><b>${escapeHtml(route.origin||'----')} \u2192 ${escapeHtml(route.destination||'----')}</b><small>${escapeHtml(latest.callsign||'Recorded flight')}</small></article><article><span>Revenue</span><b>${money(air.revenue?.total,sym)}</b><small>Passengers and cargo</small></article><article><span>Operating cost</span><b>${money(air.costs?.total,sym)}</b><small>Fuel, services, fees and reserves</small></article><article><span>Flight result</span><b class="${Number(air.profit)>=0?'profit-positive':'profit-negative'}">${money(air.profit,sym)}</b><small>Pilot pay ${money(pilot.pay,sym)}</small></article>${satisHtml}</div></section>`:`<section><h3>Latest completed flight</h3><div class="network-empty">No completed finance statement yet.</div></section>`;
  if($('financeSummary'))$('financeSummary').innerHTML=`<div class="finance-dual-ledger">${latestHtml}<section><h3>Career</h3><div class="finance-kpi-row"><article><span>Airline balance</span><b>${money(data.airline_balance,sym)}</b></article><article><span>Pilot wallet</span><b>${money(data.pilot_balance,sym)}</b></article><article><span>Lifetime revenue</span><b>${money(tot.airline_revenue,sym)}</b></article><article><span>Lifetime operating cost</span><b>${money(tot.airline_costs,sym)}</b></article>${lifetimeSatisHtml}</div></section></div>`;
  if($('financeRank'))$('financeRank').innerHTML=`<div class="rank-current"><span>Current position</span><b>${escapeHtml(cur.label||'Cadet')}</b><small>${progress.pireps||0} completed flights · ${Number(progress.block_hours||0).toFixed(1)} block hours</small></div><div class="rank-progress"><span>Next position</span><b>${rankStr(next)}</b><small>${progress.pireps||0}/${progress.next_pireps||0} flights · ${Number(progress.block_hours||0).toFixed(1)}/${progress.next_block_hours||0} block hours</small><i style="width:${Math.max(0,Math.min(100,Number(progress.percent)||0))}%"></i></div>`;
  if($('financeRanks')){try{const ladder=[...(rank.ladder||[])].reverse();$('financeRanks').innerHTML=ladder.map(r=>`<article class="${r.key===cur.key?'active':''}"><span>${rankInsignia(r.key)}</span><b>${escapeHtml(r.label)}</b><small>${r.pireps} completed flights · ${r.block_hours} block hours${r.key===cur.key?' · Current position':''}</small></article>`).join('')}catch(e){$('financeRanks').innerHTML='<div class="network-empty">Rank history is temporarily unavailable.</div>'}}
  if($('financeLedger'))$('financeLedger').innerHTML=(data.ledger||[]).length?(data.ledger||[]).slice(0,16).map(item=>{const row=item.statement||{},rowAir=row.airline||{},rowPilot=row.pilot||{},rowRoute=row.route||{};return `<div><time>${messageTime(item.time)}Z</time><b>${escapeHtml(item.callsign||'Flight')} · ${escapeHtml(rowRoute.origin||'----')} ? ${escapeHtml(rowRoute.destination||'----')}</b><span>Result ${money(rowAir.profit,sym)} · Pilot pay ${money(rowPilot.pay,sym)}</span></div>`}).join(''):'<div class="network-empty">No completed flight statements yet.</div>';
  if($('financeSetupCurrency'))$('financeSetupCurrency').value=data.currency||'EUR';
  if($('financeSetupPace'))$('financeSetupPace').value=career.progression_pace||'standard';
  if($('financeFareAuto'))$('financeFareAuto').checked=fare.auto!==false;
  for(const [id,key] of [['financeEconomyFare','economy_fare'],['financeBusinessFare','business_fare'],['financeFirstFare','first_fare'],['financeCargoRate','cargo_rate'],['financeEconomyPct','economy_pct'],['financeBusinessPct','business_pct'],['financeFirstPct','first_pct']]){if($(id))$(id).value=fare[key]??''}
  loadFinanceEstimate();
}

async function saveFinanceSetup(reset=false){
  try{const payload={currency:$('financeSetupCurrency')?.value||'EUR',progression_pace:$('financeSetupPace')?.value||'standard',fare_settings:financeFareSettingsFromUi(),reset};const r=await fetch('/api/economy/configure',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const d=await r.json();if(!r.ok)throw new Error(d.detail||`HTTP ${r.status}`);await loadFinances();}
  catch(e){if($('financeState'))$('financeState').textContent=`SAVE FAILED: ${friendlyError(e.message)}`}
}
function startFinances(){loadFinances();bg(()=>loadFinanceEstimate())}


function cpdlcContext(){
  const airportId=value=>{if(!value)return '----';if(typeof value==='string')return value.toUpperCase();return String(value.icao||value.icao_code||value.iata||value.name||'----').toUpperCase()};
  const origin=airportId(flightPlan?.origin);
  const destination=airportId(flightPlan?.destination);
  const aircraft=String(flightPlan?.aircraft?.icao||flightPlan?.aircraft_icao||flightPlan?.aircraft?.name||flightPlan?.aircraft||'----').toUpperCase();
  const callsign=String(flightPlan?.callsign||summary?.callsign||'CALLSIGN').toUpperCase();
  const atc=($('cpdlcFacility')?.value||'').trim().toUpperCase();
  return {origin,destination,aircraft,callsign,atc,station:atc};
}
function cpdlcValue(id){return ($(`cpdlcField_${id}`)?.value||'').trim().toUpperCase()}
function selectedCpdlcTemplate(){return CPDLC_TEMPLATES.find(t=>t.id===$('cpdlcTemplate')?.value)||CPDLC_TEMPLATES[0]}
function renderCpdlcCategories(){
  const cat=$('cpdlcCategory');if(!cat)return;
  const cats=[...new Set(CPDLC_TEMPLATES.map(t=>t.cat))];
  const prev=cat.value;cat.innerHTML=cats.map(x=>`<option value="${escapeHtml(x)}">${escapeHtml(x)}</option>`).join('');
  cat.value=cats.includes(prev)?prev:cats[0];renderCpdlcTemplates();
}
function renderCpdlcTemplates(){
  const sel=$('cpdlcTemplate'),cat=$('cpdlcCategory')?.value;if(!sel)return;
  const items=CPDLC_TEMPLATES.filter(t=>t.cat===cat);const prev=sel.value;
  sel.innerHTML=items.map(t=>`<option value="${escapeHtml(t.id)}">${escapeHtml(t.label)}</option>`).join('');
  sel.value=items.some(t=>t.id===prev)?prev:items[0]?.id||'';renderCpdlcFields();
}
function renderCpdlcFields(){
  const box=$('cpdlcTemplateFields');if(!box)return;const template=selectedCpdlcTemplate(),ctx=cpdlcContext();
  const defaults={station:ctx.atc||ctx.origin,atc:ctx.atc,stand:'',atis:'',runway:'',sid:'',star:'',remarks:'',direction:'',intersection:'',level:'',level_from:'',level_to:'',reason:'',waypoint:'',route:'',offset:'5',side:'LEFT',distance:'20',speed:'',mach:'',approach:'ILS',position:'',time:'',next:'',eta:'',message:''};
  box.innerHTML=(template.fields||[]).map(id=>{const label=CPDLC_FIELD_LABELS[id]||id.toUpperCase();const wide=['remarks','route','message','reason'].includes(id);const value=defaults[id]||'';const tag=['remarks','route','message'].includes(id)?`<textarea id="cpdlcField_${id}" rows="2" maxlength="240">${escapeHtml(value)}</textarea>`:`<input id="cpdlcField_${id}" maxlength="80" value="${escapeHtml(value)}" />`;return `<label class="${wide?'wide':''}">${escapeHtml(label)}${tag}</label>`}).join('');
  $('cpdlcTemplateState').textContent=(template.phase||'AUTO').toUpperCase();
}
function autofillCpdlcTemplate(){
  const ctx=cpdlcContext();
  if($('cpdlcField_station')&&!$('cpdlcField_station').value)$('cpdlcField_station').value=ctx.atc||ctx.origin;
  if($('cpdlcField_atc')&&!$('cpdlcField_atc').value)$('cpdlcField_atc').value=ctx.atc||ctx.origin;
  if($('cpdlcField_stand')&&!$('cpdlcField_stand').value)$('cpdlcField_stand').value='STAND';
  if($('cpdlcField_level')&&!$('cpdlcField_level').value)$('cpdlcField_level').value='FL380';
  if($('cpdlcField_level_from')&&!$('cpdlcField_level_from').value)$('cpdlcField_level_from').value='FL360';
  if($('cpdlcField_level_to')&&!$('cpdlcField_level_to').value)$('cpdlcField_level_to').value='FL380';
  if($('cpdlcField_time')&&!$('cpdlcField_time').value)$('cpdlcField_time').value=new Date().toISOString().slice(11,16)+'Z';
}
function transferCpdlcToMailbox(){
  const template=selectedCpdlcTemplate();if(!template)return;const ctx=cpdlcContext();
  (template.fields||[]).forEach(id=>ctx[id]=cpdlcValue(id));
  const to=(template.to==='station'?(ctx.station||ctx.atc):(ctx.atc||ctx.station||$('cpdlcFacility')?.value||'')).trim().toUpperCase();
  const message=String(template.build(ctx)||'').replace(/\n{3,}/g,'\n\n').trim();
  const sendType=String(template.sendType||'cpdlc').toLowerCase();
  if($('hoppieType'))$('hoppieType').value=sendType;if($('hoppieTo'))$('hoppieTo').value=to;if($('hoppieMessage'))$('hoppieMessage').value=message;
  $('hoppieCommandState').textContent=`DRAFT READY: ${template.label.toUpperCase()} · ${sendType.toUpperCase()}`;
}
function initCpdlcTemplates(){renderCpdlcCategories();if($('hoppieType'))$('hoppieType').value='telex';}

function renderHoppieBase(data){
  $('hoppieConfigured').textContent=data.configured?'CODE READY':'CODE NOT SET';$('hoppieLiveState').textContent=data.active?'HOPPIE ACTIVE':data.configured?'HOPPIE READY':'HOPPIE STANDBY';
  const logUrl=data.callsign?`http://www.hoppie.nl/acars/system/callsign.html?network=VATSIM&callsign=${encodeURIComponent(data.callsign)}`:'';
  if($('hoppieLogLink')){$('hoppieLogLink').disabled=!logUrl;$('hoppieLogLink').dataset.href=logUrl;}
  $('hoppieStatus').innerHTML=`<div><span>CALLSIGN</span><b>${escapeHtml(data.callsign||'NOT SET')}</b><small>${escapeHtml(data.callsign_source||'')}</small></div><div><span>POLLING</span><b>${data.active?'ACTIVE':'STOPPED'}</b><small>${data.next_poll?`NEXT ${messageTime(data.next_poll)}Z`:''}</small></div><div><span>CURRENT ATC</span><b>${escapeHtml(data.current_atc||'NONE')}</b></div><div><span>NEXT ATC</span><b>${escapeHtml(data.next_atc||'NONE')}</b></div>${data.last_error?`<div class="wide fault"><span>LAST ERROR</span><b>${escapeHtml(friendlyError(data.last_error))}</b></div>`:''}`;
  const field=$('hoppieCallsign');if(document.activeElement!==field)field.value=data.callsign_override||'';$('cpdlcAuthority').textContent=data.current_atc?`CDA ${data.current_atc}`:'NO DATA AUTHORITY';
  const messages=data.messages||[];$('hoppieMessageCount').textContent=`${messages.length} messages`;$('hoppieMessages').innerHTML=messages.length?messages.map(item=>{const replies=Array.isArray(item.reply_options)?item.reply_options:[];const text=item.message||item.display||item.packet||'';const meta=item.type==='cpdlc'&&item.min?`<small>REF ${escapeHtml(item.min)} ${item.response?`· EXPECTS ${escapeHtml(item.response)}`:''}</small>`:'';return `<article class="datalink-message ${item.direction==='OUT'?'outbound':'inbound'}"><header><time>${messageTime(item.time)}Z</time><b>${escapeHtml(item.type.toUpperCase())}</b><span>${escapeHtml(item.direction==='OUT'?`TO ${item.to}`:`FROM ${item.from}`)}</span>${meta}</header><p>${escapeHtml(text)}</p>${item.type==='cpdlc'&&item.direction==='IN'&&replies.length?`<div class="cpdlc-replies">${replies.map(r=>`<button type="button" data-cpdlc-reply="${escapeHtml(r)}" data-message-id="${escapeHtml(item.id)}">${escapeHtml(r)}</button>`).join('')}</div>`:''}</article>`}).join(''):'<div class="network-empty">No datalink messages</div>';
}
async function loadHoppie(){try{const r=await fetch('/api/hoppie/status',{cache:'no-store'});const d=await r.json();if(!r.ok)throw new Error(d.detail||`HTTP ${r.status}`);renderHoppie(d)}catch(e){$('hoppieCommandState').textContent=`DATALINK UNAVAILABLE: ${friendlyError(e.message)}`}}
function stopHoppieConsole(){if(hoppieReconnectTimer){clearTimeout(hoppieReconnectTimer);hoppieReconnectTimer=null}if(hoppiePollTimer){clearInterval(hoppiePollTimer);hoppiePollTimer=null}if(hoppieSocket){const x=hoppieSocket;hoppieSocket=null;try{x.close()}catch{}}}
function startHoppiePolling(){if(hoppiePollTimer||activePage!=='datalink')return;loadHoppie();hoppiePollTimer=setInterval(()=>{if(activePage==='datalink')loadHoppie()},2500)}
function startHoppieConsole(){if(activePage!=='datalink')return;stopHoppieConsole();const scheme=location.protocol==='https:'?'wss':'ws';const socket=new WebSocket(`${scheme}://${location.host}/ws/hoppie`);hoppieSocket=socket;socket.onopen=()=>{if(hoppiePollTimer){clearInterval(hoppiePollTimer);hoppiePollTimer=null}};socket.onmessage=e=>{try{renderHoppie(JSON.parse(e.data))}catch{}};socket.onerror=startHoppiePolling;socket.onclose=()=>{if(hoppieSocket===socket)hoppieSocket=null;if(activePage==='datalink'){startHoppiePolling();hoppieReconnectTimer=setTimeout(startHoppieConsole,5000)}}}
async function hoppieCommand(path,payload=null){$('hoppieCommandState').textContent='TRANSMITTING';try{const r=await fetch(path,{method:'POST',headers:payload?{'Content-Type':'application/json'}:{},body:payload?JSON.stringify(payload):undefined});const d=await r.json();if(!r.ok||d.ok===false)throw new Error(d.detail||d.error||`HTTP ${r.status}`);$('hoppieCommandState').textContent='Sent';renderHoppie(d.messages?d:await (await fetch('/api/hoppie/status',{cache:'no-store'})).json())}catch(e){$('hoppieCommandState').textContent=`FAILED: ${friendlyError(e.message)}`}finally{setTimeout(loadHoppie,350)}}

function groundToneClass(tone){return ['ready','active','complete','waiting','fault'].includes(tone)?`ground-${tone}`:'ground-off'}
function groundServiceButton(key,label){const actionable=['boarding','deboarding','catering','refuel','water','lavatory','cleaning','deice','pushback','jetway','stairs','gpu'].includes(key);return actionable?`<button type="button" data-gsx-service="${escapeHtml(key)}">${escapeHtml(label)}</button>`:''}
function gsxOfficialClientUrl(remote){if(!remote||!remote.port)return '';const protocol=location.protocol==='https:'?'https:':'http:';return `${protocol}//${location.hostname}:${remote.port}/`}
function renderGroundAutomation(auto){
  auto=auto||{};
  const stage=String(auto.stage||'READY').toUpperCase();
  const requiresChoice=/ACTION REQUIRED|DIRECTION|CHOICE/.test(stage+' '+String(auto.detail||''));
  const layout=$('groundLayout')||document.querySelector('#page-ground .ground-layout');
  if(layout)layout.classList.toggle('needs-choice',requiresChoice);
  $('groundAutoState').textContent=auto.running?'Services in progress':friendlyStage(stage);
  $('groundAutoDetail').textContent=friendlyDetail(auto.detail||'Ground services are ready.','ground');
  ['groundDepartureStart','groundArrivalStart','groundFullTurnaroundStart'].forEach(id=>{const b=$(id);if(b)b.disabled=!!auto.running});$('groundAutoStop').disabled=!auto.running;
  ['groundDepartureCatering','groundDepartureWater'].forEach(id=>{const input=$(id);if(input)input.disabled=!!auto.running});
  const items=operationalEvents((auto.history||[]).slice().reverse(),'ground-auto',8);$('groundAutoTimeline').innerHTML=items.length?items.map(x=>`<div><time>${messageTime(x.time)}Z</time><b>${escapeHtml(x.kind)}</b><span>${escapeHtml(x.text)}</span></div>`).join(''):'<div class="network-empty">No recent service activity</div>';
}
async function loadGroundAutomation(){try{const r=await fetch('/api/gsx/automation/status',{cache:'no-store'});renderGroundAutomation(await r.json())}catch{}}
async function saveGroundPreferences(){
  const state=$('groundPreferenceState');
  if(state)state.textContent='SAVING';
  const catering=$('groundDepartureCatering')?.checked!==false,water=$('groundDepartureWater')?.checked!==false;
  try{
    const r=await fetch('/api/ground/preferences',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({gsx_departure_catering:catering,gsx_departure_water:water})});
    const d=await safeJsonResponse(r);
    settings=settings||{};settings.integrations={...(settings.integrations||{}),...(d.integrations||{})};
    if($('groundDepartureCatering'))$('groundDepartureCatering').checked=settings.integrations.gsx_departure_catering!==false;
    if($('groundDepartureWater'))$('groundDepartureWater').checked=settings.integrations.gsx_departure_water!==false;
    if(state)state.textContent='SAVED';
  }catch(e){
    if($('groundDepartureCatering'))$('groundDepartureCatering').checked=settings?.integrations?.gsx_departure_catering!==false;
    if($('groundDepartureWater'))$('groundDepartureWater').checked=settings?.integrations?.gsx_departure_water!==false;
    if(state)state.textContent='SAVE FAILED';
    showToast('GROUND CONTROL','COULD NOT SAVE DEPARTURE OPTIONS',friendlyError(e.message),'critical');
  }
}
function renderGroundBase(data){
  renderAirlineIdentity('groundAirlineIdentity',flightPlan,'small',true,[flightPlan?.callsign,flightPlan?.aircraft,flightPlan?.registration].filter(Boolean).join(' · '));
  const connected=Boolean(data.connected);const server=data.control_server||{},official=data.official_remote||server.official||{};$('groundConnectionState').textContent=connected?'GSX connected':data.installed?'Waiting for GSX':'GSX not detected';$('groundLiveState').textContent=connected?'GSX connected':'GSX standby';
  const officialUrl=gsxOfficialClientUrl(official);const officialOnline=Boolean(official.reachable);
  const layout=$('groundLayout')||document.querySelector('#page-ground .ground-layout');
  if(layout){layout.classList.toggle('official-online',officialOnline);layout.classList.toggle('fallback-mode',!officialOnline)}
  if($('gsxOfficialState'))$('gsxOfficialState').textContent=officialOnline?'Connected':'Not available';
  const frame=$('gsxOfficialFrame'),placeholder=$('gsxOfficialPlaceholder');
  if(frame&&placeholder){if(officialOnline&&officialUrl){if(frame.src!==officialUrl)frame.src=officialUrl;frame.hidden=false;placeholder.hidden=true}else{frame.hidden=true;placeholder.hidden=false}}
  const p=data.progress||{},serviceState=key=>String((data.services||{})[key]?.state||'').toUpperCase(),hasNumber=value=>value!==null&&value!==undefined&&value!==''&&Number.isFinite(Number(value)),readCount=(current,total)=>hasNumber(current)&&hasNumber(total)&&Number(total)>0?`${Number(current)} / ${Number(total)}`:'-- / --',readPercent=(value,state)=>hasNumber(value)?`${Math.round(Number(value))}%`:(/COMPLETE/.test(state)?'COMPLETE':(/ACTIVE|PROGRESS|RUNNING/.test(state)?'ACTIVE':'--'));
  const boardingState=serviceState('boarding'),deboardingState=serviceState('deboarding'),deboardTarget=hasNumber(p.passengers_deboarding_target)?p.passengers_deboarding_target:p.passengers_target;$('groundOverview').innerHTML=`<div><span>GSX Pro</span><b>${connected?'Connected':'Standby'}</b></div><div><span>Boarding</span><b>${readCount(p.passengers_boarding_total,p.passengers_target)}</b></div><div><span>Deboarding</span><b>${readCount(p.passengers_deboarding_total,deboardTarget)!=='-- / --'?readCount(p.passengers_deboarding_total,deboardTarget):(/COMPLETE/.test(deboardingState)?'Complete':(/ACTIVE|PROGRESS|RUNNING/.test(deboardingState)?'In progress':'-- / --'))}</b></div><div><span>Baggage unload</span><b>${readPercent(p.deboarding_cargo_percent,deboardingState)}</b></div><div><span>Baggage load</span><b>${readPercent(p.boarding_cargo_percent,boardingState)}</b></div><div><span>Live panel</span><b>${officialOnline?'Connected':'Unavailable'}</b></div>`;
  const order=['boarding','deboarding','catering','refuel','jetway','stairs','gpu','water','lavatory','cleaning','deice','pushback'],services=data.services||{};$('groundServices').innerHTML=order.map(key=>{const item=services[key]||{label:uiWords(key),state:'Not available',tone:'off'};const label=uiWords(item.label);const state=friendlyStage(item.state);return `<article class="ground-service ${groundToneClass(item.tone)}"><div class="ground-service-head"><i></i><b>${escapeHtml(label)}</b></div><strong>${escapeHtml(state)}</strong>${groundServiceButton(key,key==='pushback'?'Prepare pushback':`Request ${label}`)}</article>`}).join('');
  const menu=data.menu||{};$('gsxMenuState').textContent=menu.available?(uiWords(menu.title||'Ready')):'Closed';$('gsxMenu').innerHTML=menu.available&&Array.isArray(menu.options)&&menu.options.length?`<div class="gsx-menu-title">${escapeHtml(uiWords(menu.title||'GSX menu'))}</div><div class="gsx-menu-grid">${menu.options.map((option,index)=>`<button type="button" data-gsx-index="${index}"><span>${String(index+1).padStart(2,'0')}</span><b>${escapeHtml(option)}</b></button>`).join('')}</div>`:`<div class="network-empty">${escapeHtml(friendlyDetail(menu.reason||'Open the GSX menu to view the available choices.','ground'))}</div>`;
  const events=operationalEvents((data.events||[]),'ground',30);$('groundEventCount').textContent=`${events.length} events`;$('groundEvents').innerHTML=events.length?events.map(item=>`<div><time>${messageTime(item.time)}Z</time><b>${escapeHtml(item.kind)}</b><span>${escapeHtml(item.text)}</span></div>`).join(''):'<div class="network-empty">No recent ground activity</div>';if(data.reason&&!connected)$('groundCommandState').textContent=friendlyDetail(data.reason,'ground');
}
async function loadGroundReceipts(){try{const r=await fetch('/api/gsx/receipts?limit=40',{cache:'no-store'});const d=await r.json();$('groundReceiptCount').textContent=`${Number(d.count||0)} receipts`;$('groundReceipts').innerHTML=(d.items||[]).length?(d.items||[]).map(x=>`<a href="${escapeHtml(x.url)}" target="_blank" rel="noreferrer"><span>${escapeHtml(x.category.toUpperCase())}</span><b>${escapeHtml(x.airport||'----')}</b><time>${messageTime(x.modified_utc)}Z</time></a>`).join(''):'<div class="network-empty">No GSX receipts found</div>'}catch(e){$('groundReceipts').innerHTML=`<div class="network-empty">RECEIPTS UNAVAILABLE: ${escapeHtml(friendlyError(e.message))}</div>`}}
async function loadGround(force=false){if(groundBusy)return;groundBusy=true;try{const r=await fetch(`/api/gsx/status?force_refresh=${force?'true':'false'}`,{cache:'no-store'});const d=await r.json();if(!r.ok)throw new Error(d.detail||`HTTP ${r.status}`);renderGround(d);await Promise.all([loadGroundAutomation(),loadGroundReceipts()])}catch(e){$('groundConnectionState').textContent='Unavailable';$('groundCommandState').textContent=`GSX unavailable: ${friendlyError(e.message)}`}finally{groundBusy=false}}
function stopGroundControl(){if(groundReconnectTimer){clearTimeout(groundReconnectTimer);groundReconnectTimer=null}if(groundTimer){clearInterval(groundTimer);groundTimer=null}if(groundSocket){const x=groundSocket;groundSocket=null;try{x.close()}catch{}}}
function startGroundPolling(){if(groundTimer||activePage!=='ground')return;loadGround(false);groundTimer=setInterval(()=>{if(activePage==='ground')loadGround(false)},1500)}
function startGroundControl(){if(activePage!=='ground')return;stopGroundControl();const scheme=location.protocol==='https:'?'wss':'ws';const socket=new WebSocket(`${scheme}://${location.host}/ws/gsx`);groundSocket=socket;socket.onopen=()=>{if(groundTimer){clearInterval(groundTimer);groundTimer=null}$('groundLiveState').textContent='Live'};socket.onmessage=e=>{try{renderGround(JSON.parse(e.data));loadGroundAutomation()}catch{}};socket.onerror=startGroundPolling;socket.onclose=()=>{if(groundSocket===socket)groundSocket=null;if(activePage==='ground'){startGroundPolling();groundReconnectTimer=setTimeout(startGroundControl,5000)}}}
async function groundCommand(path,payload=null){$('groundCommandState').textContent='Working...';try{const r=await fetch(path,{method:'POST',headers:payload?{'Content-Type':'application/json'}:{},body:payload?JSON.stringify(payload):undefined});const d=await r.json();if(!r.ok)throw new Error(d.detail||`HTTP ${r.status}`);$('groundCommandState').textContent=d.requires_selection?(friendlyDetail(d.reason||'Pilot selection required','ground')):d.selected?`Selected ${d.selected}`:'Done';if(d.menu)renderGround({...await (await fetch('/api/gsx/status?force_refresh=true',{cache:'no-store'})).json(),menu:d.menu})}catch(e){$('groundCommandState').textContent=`Could not complete: ${friendlyError(e.message)}`}finally{setTimeout(()=>loadGround(true),450)}}
async function groundAutomation(start,mode='DEPARTURE'){const path=start?'/api/gsx/automation/start':'/api/gsx/automation/stop';try{const r=await fetch(path,{method:'POST',headers:start?{'Content-Type':'application/json'}:{},body:start?JSON.stringify({mode}):undefined});const d=await r.json();if(!r.ok)throw new Error(d.detail||`HTTP ${r.status}`);renderGroundAutomation(d);$('groundCommandState').textContent=start?'Services started':'Services stopped'}catch(e){$('groundCommandState').textContent=`Could not start services: ${friendlyError(e.message)}`}}


async function loadAnnouncements(){
  if(announcerLoadBusy)return;announcerLoadBusy=true;
  try{
    const response=await fetchWithTimeout(`/api/announcements/status?since=${announcerLastRevision}&t=${Date.now()}`,{cache:'no-store'},2500);const data=await safeJsonResponse(response);
    announcerLastRevision=Number(data.revision??announcerLastRevision);
    $('announcerState').textContent=data.muted?'Muted':data.paused?'Paused':data.enabled?(data.audio_configured?'Automatic':'Audio unavailable'):'Off';
    $('announcerPause').textContent=data.paused?'Resume':'Pause';$('announcerMute').textContent=data.muted?'Unmute':'Mute';$('announcerHotkeys').textContent=`Shortcuts · Pause ${data.pause_hotkey||'Ctrl+Alt+P'} · Mute ${data.mute_hotkey||'Ctrl+Alt+M'}`;if($('announcerVolume')&&document.activeElement!==$('announcerVolume'))$('announcerVolume').value=Number(data.volume??80);if($('announcerVolumeValue'))$('announcerVolumeValue').textContent=`${Number(data.volume??80)}%`;
    const statusError=String(data.last_error||'');const persistentError=statusError&&!/timed out|timeout|expired|abort/i.test(statusError);
    const playing=data.playing?friendlyAnnouncementName(data.last_event||'Cabin audio'):'Standby';
    renderAirlineIdentity('announcerAirlineIdentity',{callsign:data.callsign,airline:data.airline,airline_branding:flightPlan?.airline_branding},'small',true,`Announcement source: ${data.airline||'AUTO'}`);
    $('announcerStatus').innerHTML=`<div><span>Automation</span><b>${data.enabled?'On':'Off'}</b></div><div><span>Airline</span><b>${escapeHtml(data.airline||'Automatic')}</b><small>${escapeHtml(friendlyAirlineSource(data.airline_source))}</small></div><div><span>Callsign</span><b>${escapeHtml(data.callsign||'--')}</b></div><div><span>Now playing</span><b>${escapeHtml(playing)}</b></div>${!data.audio_configured?`<div class="wide fault"><span>Cabin audio</span><b>No announcement audio is configured</b></div>`:''}${persistentError?`<div class="wide fault"><span>Audio unavailable</span><b>${escapeHtml(friendlyError(statusError))}</b></div>`:''}`;
    const overrideField=$('announcerAirlineOverride');
    if(document.activeElement!==overrideField)overrideField.value=data.airline_override||'';
    $('announcerAirlineState').textContent=data.airline_override?`Using ${data.airline_override}`:'Automatic from flight plan';
    const events=operationalEvents((data.events||[]).slice().reverse(),'announcer',35);$('announcerEventCount').textContent=`${events.length} events`;$('announcerEvents').innerHTML=events.length?events.map(x=>`<div><time>${messageTime(x.time)}Z</time><b>${escapeHtml(x.kind)}</b><span>${escapeHtml(x.text)}</span></div>`).join(''):'<div class="network-empty">No recent announcements</div>';
  }catch(error){
    // Never surface transient polling failures as Announcer FAULT. Audio playback
    // is host-worker driven; a browser status poll timing out only means the UI
    // snapshot is stale. Keep the last good panel content visible.
    if($('announcerState'))$('announcerState').textContent='Connection delayed';
    if($('announcerStatus')&&!$('announcerStatus').innerHTML.trim())$('announcerStatus').innerHTML='<div class="wide waiting"><span>Announcements</span><b>Loading current status...</b></div>';
  }finally{announcerLoadBusy=false}
}
async function playAnnouncement(event){
  try{const response=await fetchWithTimeout('/api/announcements/play',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event,force:true})},2500);await safeJsonResponse(response)}catch(error){alert(`Announcement unavailable: ${friendlyError(error.message)}`)}finally{loadAnnouncements();applyAirlineTheme()}
}
async function startBoardingAudio(){
  try{const response=await fetchWithTimeout('/api/announcements/boarding-trigger',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason:'manual boarding audio'})},2500);const data=await safeJsonResponse(response);if(data.ok===false)throw new Error(data.reason||'Boarding audio blocked')}catch(error){alert(`Boarding audio unavailable: ${friendlyError(error.message)}`)}finally{loadAnnouncements();applyAirlineTheme()}
}
async function stopAnnouncement(){try{await fetchWithTimeout('/api/announcements/stop',{method:'POST'},3500)}catch{}loadAnnouncements()}
async function pauseAnnouncement(){try{await fetchWithTimeout('/api/announcements/pause',{method:'POST'},3500);}catch{}loadAnnouncements()}
async function muteAnnouncement(){try{await fetchWithTimeout('/api/announcements/mute',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})},3500)}catch{}loadAnnouncements()}
async function setAnnouncementVolume(value){const volume=Math.max(0,Math.min(100,Number(value)||0));if($('announcerVolumeValue'))$('announcerVolumeValue').textContent=`${volume}%`;try{await fetch('/api/announcements/volume',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({volume})})}catch{}setTimeout(loadAnnouncements,250)}
async function saveAnnouncementAirlineOverride(clear=false){
  const field=$('announcerAirlineOverride');
  const airline=clear?'':field.value.toUpperCase().replace(/[^A-Z0-9]/g,'').slice(0,4);
  $('announcerAirlineState').textContent='Saving...';
  try{
    const response=await fetch('/api/announcements/airline-override',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({airline})});
    const data=await response.json();if(!response.ok)throw new Error(data.detail||`HTTP ${response.status}`);
    field.value=data.airline_override||'';
    $('announcerAirlineState').textContent=data.airline_override?`Using ${data.airline_override}`:'Automatic from flight plan';
  }catch(error){$('announcerAirlineState').textContent=`Could not save: ${friendlyError(error.message)}`}
  finally{loadAnnouncements();applyAirlineTheme()}
}

function renderRadios(data){
  const previous=lastNextStationKey;renderRadiosBase(data);const next=data.next_station;const key=next?`${next.callsign||''}-${next.frequency||''}-${next.confirmed?'1':'0'}`:'';if(key&&key!==previous&&next.confirmed)notifyOps({source:'ATC HANDOFF',title:`NEXT ${next.callsign||'ATC'} ${next.frequency||''}`,message:next.detail||'Controller frequency received from vPilot message',priority:'atc',page:'network',tag:`handoff-${key}`,persistent:true});lastNextStationKey=key;
}
function renderHoppie(data){
  renderHoppieBase(data);const inbound=(data.messages||[]).filter(x=>x.direction==='IN');if(!hoppieInitialized){inbound.forEach(x=>knownHoppieMessageIds.add(String(x.id)));hoppieInitialized=true}else inbound.forEach(x=>{const id=String(x.id);if(!knownHoppieMessageIds.has(id)){knownHoppieMessageIds.add(id);notifyOps({source:'HOPPIE DATALINK',title:`MESSAGE FROM ${x.from||'ATC'}`,message:x.message||x.display||x.packet||'',priority:x.type==='cpdlc'?'atc':'operational',page:'datalink',tag:`hoppie-${id}`,persistent:x.type==='cpdlc'})}})
}
function renderGround(data){
  renderGroundBase(data);const events=data.events||[];if(!gsxInitialized){events.forEach(x=>knownGsxEventKeys.add(`${x.time}-${x.kind}-${x.text}`));gsxInitialized=true}else events.forEach(x=>{const key=`${x.time}-${x.kind}-${x.text}`;if(!knownGsxEventKeys.has(key)){knownGsxEventKeys.add(key);const text=String(x.text||'');if(/complete|completed|finished|boarding|deboard|pushback|fuel/i.test(text))notifyOps({source:'GSX GROUND',title:String(x.kind||'GROUND EVENT').toUpperCase(),message:text,priority:'operational',page:'ground',tag:`gsx-${key}`})}})
}
function prepCanvas(canvas,minHeight=140){
  if(!canvas)return null;const rect=canvas.getBoundingClientRect(),ratio=Math.max(1,window.devicePixelRatio||1);canvas.width=Math.max(300,Math.round(rect.width*ratio));canvas.height=Math.max(minHeight,Math.round(rect.height*ratio));const ctx=canvas.getContext('2d');ctx.setTransform(ratio,0,0,ratio,0,0);const w=canvas.width/ratio,h=canvas.height/ratio;ctx.clearRect(0,0,w,h);ctx.fillStyle='#080b07';ctx.fillRect(0,0,w,h);return {ctx,w,h}
}
function drawEmptyChart(canvas,text='NO TELEMETRY'){const state=prepCanvas(canvas);if(!state)return;state.ctx.fillStyle='#8f9279';state.ctx.font='11px B612 Mono';state.ctx.fillText(text,12,24)}
function drawLineChart(canvas,samples,series,options={}){
  const state=prepCanvas(canvas);if(!state)return;const {ctx,w,h}=state,pad={l:48,r:14,t:18,b:27};const xKey=options.xKey||'elapsed_seconds',xScale=Number(options.xScale??1),xSuffix=options.xSuffix??(xKey==='elapsed_seconds'?'m':'');
  const points=(samples||[]).filter(s=>Number.isFinite(Number(s[xKey]))&&series.some(x=>Number.isFinite(Number(s[x.key]))));if(!points.length){ctx.fillStyle='#8f9279';ctx.font='11px B612 Mono';ctx.fillText(options.empty||'NO TELEMETRY',12,24);return}
  const xValues=points.map(x=>Number(x[xKey])*xScale);let xmin=Math.min(...xValues),xmax=Math.max(...xValues);if(xmin===xmax){xmin-=.5;xmax+=.5}const xPixel=value=>options.reverseX?pad.l+(xmax-value)/(xmax-xmin)*(w-pad.l-pad.r):pad.l+(value-xmin)/(xmax-xmin)*(w-pad.l-pad.r);
  const values=[];series.forEach(x=>points.forEach(p=>{const v=Number(p[x.key]);if(Number.isFinite(v))values.push(v)}));let ymin=Math.min(...values),ymax=Math.max(...values);if(options.includeZero){ymin=Math.min(0,ymin);ymax=Math.max(0,ymax)}if(ymin===ymax){ymin-=1;ymax+=1}const margin=(ymax-ymin)*.08;ymin-=margin;ymax+=margin;
  ctx.strokeStyle='#30352b';ctx.lineWidth=1;ctx.font='9px B612 Mono';for(let i=0;i<=4;i++){const y=pad.t+(h-pad.t-pad.b)*i/4;ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(w-pad.r,y);ctx.stroke();ctx.fillStyle='#8f9279';ctx.textAlign='right';ctx.fillText(Math.round(ymax-(ymax-ymin)*i/4),pad.l-5,y+3)}
  ctx.textAlign='center';for(let i=0;i<=4;i++){const x=pad.l+(w-pad.l-pad.r)*i/4,value=options.reverseX?xmax-(xmax-xmin)*i/4:xmin+(xmax-xmin)*i/4;ctx.fillStyle='#8f9279';const label=Math.abs(value)<10?value.toFixed(1):Math.round(value);ctx.fillText(`${label}${xSuffix}`,x,h-8)}
  const colors=['#70d4e5','#efbd47','#d98bd1','#7de38d'];series.forEach((item,idx)=>{ctx.strokeStyle=colors[idx%colors.length];ctx.lineWidth=1.5;ctx.beginPath();let begun=false;points.forEach(p=>{const v=Number(p[item.key]),rawX=Number(p[xKey]);if(!Number.isFinite(v)||!Number.isFinite(rawX))return;const xv=rawX*xScale,x=xPixel(xv),y=pad.t+(ymax-v)/(ymax-ymin)*(h-pad.t-pad.b);if(!begun){ctx.moveTo(x,y);begun=true}else ctx.lineTo(x,y)});ctx.stroke();ctx.fillStyle=colors[idx%colors.length];ctx.textAlign='left';ctx.fillText(item.label||item.key,pad.l+idx*92,11)})
}
function drawTrackChart(canvas,samples,route=[]){
  const actual=(samples||[]).filter(x=>Number.isFinite(Number(x.lat))&&Number.isFinite(Number(x.lon))),planned=(route||[]).filter(x=>Number.isFinite(Number(x.lat))&&Number.isFinite(Number(x.lon)));if(!actual.length){drawEmptyChart(canvas);return}const state=prepCanvas(canvas,160);if(!state)return;const {ctx,w,h}=state,p=18,all=[...actual,...planned],lats=all.map(x=>Number(x.lat)),lons=all.map(x=>Number(x.lon));let minLat=Math.min(...lats),maxLat=Math.max(...lats),minLon=Math.min(...lons),maxLon=Math.max(...lons);if(minLat===maxLat){minLat-=.01;maxLat+=.01}if(minLon===maxLon){minLon-=.01;maxLon+=.01}const point=x=>[p+(Number(x.lon)-minLon)/(maxLon-minLon)*(w-2*p),h-p-(Number(x.lat)-minLat)/(maxLat-minLat)*(h-2*p)];
  if(planned.length>1){ctx.save();ctx.strokeStyle='#efbd47';ctx.lineWidth=1.2;ctx.setLineDash([5,4]);ctx.beginPath();planned.forEach((x,i)=>{const [px,py]=point(x);if(i)ctx.lineTo(px,py);else ctx.moveTo(px,py)});ctx.stroke();ctx.restore()}
  ctx.strokeStyle='#70d4e5';ctx.lineWidth=1.7;ctx.beginPath();actual.forEach((x,i)=>{const [px,py]=point(x);if(i)ctx.lineTo(px,py);else ctx.moveTo(px,py)});ctx.stroke();const first=actual[0],last=actual[actual.length-1];[first,last].forEach((x,i)=>{const [px,py]=point(x);ctx.fillStyle=i?'#e16452':'#3dff55';ctx.beginPath();ctx.arc(px,py,4,0,Math.PI*2);ctx.fill()});ctx.font='9px B612 Mono';ctx.fillStyle='#efbd47';ctx.fillText('PLANNED',12,12);ctx.fillStyle='#70d4e5';ctx.fillText('ACTUAL',80,12)
}
function drawPhaseTimeline(canvas,samples){
  const rows=(samples||[]).filter(x=>x.phase&&Number.isFinite(Number(x.elapsed_seconds)));if(!rows.length){drawEmptyChart(canvas,'NO PHASE DATA');return}const state=prepCanvas(canvas);if(!state)return;const {ctx,w,h}=state,end=Math.max(Number(rows.at(-1).elapsed_seconds)||1,1),segments=[];let start=Number(rows[0].elapsed_seconds)||0,phase=rows[0].phase;rows.slice(1).forEach(row=>{const elapsed=Number(row.elapsed_seconds)||0;if(row.phase!==phase){segments.push({start,end:elapsed,phase});start=elapsed;phase=row.phase}});segments.push({start,end,phase});const colors=['#1b7f91','#9b6b1d','#2b7a3d','#7b4173','#6b7280','#854d0e'];ctx.font='8px B612 Mono';segments.forEach((seg,i)=>{const x=8+seg.start/end*(w-16),right=8+seg.end/end*(w-16),width=Math.max(2,right-x);ctx.fillStyle=colors[i%colors.length];ctx.fillRect(x,36,width,42);if(width>45){ctx.save();ctx.beginPath();ctx.rect(x,36,width,42);ctx.clip();ctx.fillStyle='#fff';ctx.fillText(String(seg.phase).slice(0,18),x+4,60);ctx.restore()}});ctx.fillStyle='#8f9279';ctx.fillText('0',8,h-10);ctx.textAlign='right';ctx.fillText(end<120?`${Math.round(end)}s`:`${Math.round(end/60)}m`,w-8,h-10);ctx.textAlign='left'
}
async function loadLogbookTelemetry(entryId){
  if(!entryId)return;try{let payload=selectedTelemetryCache.get(entryId);if(!payload){const r=await fetch(`/api/logbook/${encodeURIComponent(entryId)}/telemetry?max_points=2400`,{cache:'no-store'});payload=await r.json();if(!r.ok)throw new Error(payload.detail||`HTTP ${r.status}`);selectedTelemetryCache.set(entryId,payload)}if(entryId!==selectedLogbookId)return;const samples=payload.samples||[],masterApproach=Array.isArray(payload.analysis?.approach?.profile)?payload.analysis.approach.profile:[],rawApproach=samples.filter(x=>Number.isFinite(Number(x.distance_to_touchdown_nm))&&Number(x.distance_to_touchdown_nm)<=20&&Number(x.seconds_to_touchdown)<=0&&Number(x.ground_speed_kts)<=250&&(!Number.isFinite(Number(x.approach_agl_ft))||Number(x.approach_agl_ft)<=5000)).sort((a,b)=>Number(b.distance_to_touchdown_nm)-Number(a.distance_to_touchdown_nm)),approach=(masterApproach.length?masterApproach:rawApproach).filter(x=>Number.isFinite(Number(masterApproach.length?x.nm_to_threshold:x.distance_to_touchdown_nm))).sort((a,b)=>Number(masterApproach.length?b.nm_to_threshold:b.distance_to_touchdown_nm)-Number(masterApproach.length?a.nm_to_threshold:a.distance_to_touchdown_nm)),approachX=masterApproach.length?'nm_to_threshold':'distance_to_touchdown_nm',landing=samples.filter(x=>Number.isFinite(Number(x.seconds_to_touchdown))&&Number(x.seconds_to_touchdown)>=-90&&Number(x.seconds_to_touchdown)<=60);$('logbookCharts').hidden=!samples.length;requestAnimationFrame(()=>{
    drawLineChart($('chartAltitude'),samples,[{key:'altitude_ft',label:'ACTUAL'},{key:'planned_cruise_altitude_ft',label:'PLAN'}],{xScale:1/60});
    drawLineChart($('chartSpeed'),samples,[{key:'ias_kts',label:'IAS'},{key:'ground_speed_kts',label:'GS'}],{xScale:1/60});
    drawLineChart($('chartVerticalSpeed'),samples,[{key:'vertical_speed_fpm',label:'VS'}],{xScale:1/60,includeZero:true});
    drawLineChart($('chartFuel'),samples,[{key:'fuel_total_lb',label:'FUEL'}],{xScale:1/60});
    drawLineChart($('chartCrossTrack'),samples,[{key:'cross_track_nm',label:'XTE'}],{xScale:1/60,includeZero:true});
    drawPhaseTimeline($('chartPhases'),samples);drawTrackChart($('chartTrack'),samples,payload.route||[]);
    // Match the Full PIREP master: use the runway-aware, continuous, binned
    // approach profile produced by pirep_analysis instead of raw distance data.
    drawLineChart($('chartApproachAltitude'),approach,[{key:'approach_agl_ft',label:'ACTUAL'},{key:'ideal_3deg_agl_ft',label:'3 DEG'}],{xKey:approachX,xSuffix:'nm',reverseX:true});
    drawLineChart($('chartGlidepath'),approach,[{key:'glidepath_deviation_ft',label:'DEV'}],{xKey:approachX,xSuffix:'nm',includeZero:true,reverseX:true});
    drawLineChart($('chartApproachSpeed'),approach,[{key:'ias_kts',label:'IAS'},{key:'ground_speed_kts',label:'GS'}],{xKey:approachX,xSuffix:'nm',reverseX:true});
    drawLineChart($('chartApproachVs'),approach,[{key:'vertical_speed_fpm',label:'VS'}],{xKey:approachX,xSuffix:'nm',includeZero:true,reverseX:true});
    drawLineChart($('chartLandingAttitude'),landing,[{key:'pitch_deg',label:'PITCH'},{key:'bank_deg',label:'BANK'}],{xKey:'seconds_to_touchdown',xSuffix:'s',includeZero:true});
    drawLineChart($('chartLandingG'),landing,[{key:'g_force',label:'G'}],{xKey:'seconds_to_touchdown',xSuffix:'s'});
    drawLineChart($('chartTouchdown'),landing,[{key:'radio_altitude_ft',label:'RAD ALT'},{key:'ground_contact_plot',label:'GROUND'}],{xKey:'seconds_to_touchdown',xSuffix:'s',includeZero:true});
  })}catch(e){$('logbookCharts').hidden=true}
}

function renderLogbookDetailAdvanced(entry){
  if(!entry){$('logbookCharts').hidden=true;return}const f=entry.flight||{},t=entry.times||{},dur=entry.durations||{},m=entry.metrics||{},fuel=entry.fuel||{},d=entry.debrief||{},events=entry.events||[],violations=entry.violations||[];
  $('logbookDetailTitle').textContent=`${f.callsign||'FLIGHT'} · ${logbookRoute(entry)}`;$('logbookDetail').innerHTML=`<div class="debrief-airline-hero">${airlineBrandHtml(f,'large',true)}<div><strong>${escapeHtml(f.callsign||'FLIGHT')}</strong><span>${escapeHtml(logbookRoute(entry))}</span><small>${escapeHtml(logbookAircraft(entry))}${f.registration?` · ${escapeHtml(f.registration)}`:''}</small></div></div><div class="debrief-source">FLIGHT ANALYSIS</div><div class="debrief-score"><strong>${d.score??0}</strong><span>OPS ROOM SCORE</span><b>${escapeHtml(d.landing_grade||'NOT GRADED')}</b></div><div class="debrief-grid"><div><span>BLOCK OUT / IN</span><b>${logbookTime(t.block_out)} / ${logbookTime(t.block_in)}</b></div><div><span>TAKEOFF / LANDING</span><b>${logbookTime(t.takeoff)} / ${logbookTime(t.landing)}</b></div><div><span>BLOCK / AIRBORNE</span><b>${duration(dur.block_seconds)} / ${duration(dur.airborne_seconds)}</b></div><div><span>ACTUAL / PLANNED DIST</span><b>${formatDistance(m.distance_nm)} / ${formatDistance(f.distance_nm)}</b></div><div><span>FUEL USED / PLANNED</span><b>${formatWeightFromLb(fuel.used_lb)} / ${f.planned_trip_fuel!=null?formatPlanWeight(f.planned_trip_fuel,f.fuel_units):'---'}</b></div><div><span>LANDING RATE / G</span><b>${landingRate(m.landing_rate_fpm)} / ${m.touchdown_g!=null?Number(m.touchdown_g).toFixed(2):'--'} G</b></div><div><span>TOUCHDOWN SPEEDS</span><b>${formatSpeed(m.touchdown_speed_kts)} · ${m.touchdowns||0} CONTACTS</b></div><div><span>MAX ALT / IAS / GS</span><b>${formatAltitude(m.max_altitude_ft)} / ${formatSpeed(m.max_ias_kts)} / ${formatSpeed(m.max_ground_speed_kts)}</b></div><div><span>MAX CLIMB / DESCENT</span><b>${formatVerticalSpeed(m.max_climb_fpm)} / ${formatVerticalSpeed(m.max_descent_fpm)}</b></div><div><span>CROSS TRACK AVG / MAX</span><b>${m.average_cross_track_nm!=null?Number(m.average_cross_track_nm).toFixed(1):'--'} / ${m.max_cross_track_nm!=null?Number(m.max_cross_track_nm).toFixed(1):'--'} NM</b></div></div>${financeMiniHtml(entry)}<div class="debrief-violations"><strong>${violations.length} DETECTED DEVIATIONS</strong>${violations.length?violations.map(x=>`<div><time>${logbookTime(x.time)}</time><b>${escapeHtml(x.title)}</b><span>${escapeHtml(x.detail)} · -${x.penalty||0}</span></div>`).join(''):'<div><span>NO AUTOMATIC DEVIATIONS DETECTED</span></div>'}</div><div class="debrief-events">${events.slice(-100).map(x=>`<div><time>${logbookTime(x.time)}</time><b>${escapeHtml(x.kind)}</b><span>${escapeHtml(x.detail)}</span></div>`).join('')}</div>`;
  $('logbookEditor').hidden=false;$('logbookRating').value=String(entry.rating||0);$('logbookNotes').value=entry.notes||'';$('logbookSelectedPdf').href=`/api/logbook/${encodeURIComponent(entry.id)}/export.pdf`; $('logbookSelectedPdf').setAttribute('download',`OPS_ROOM_PIREP_${String(entry.id||'').slice(0,8)}.pdf`); $('logbookSelectedPdf').removeAttribute('target');$('logbookOpenPirep').href=`/pirep/${encodeURIComponent(entry.id)}`;
  const blackBoxButton=$('logbookBlackBox'),blackBoxSummary=entry.black_box||null;
  if(blackBoxButton){blackBoxButton.hidden=!blackBoxSummary;blackBoxButton.disabled=!blackBoxSummary;blackBoxButton.dataset.recordingId=blackBoxSummary?.recording_id||'';blackBoxButton.textContent=blackBoxSummary?'BLACK BOX REPLAY':'NO BLACK BOX RECORDING'}
  loadLogbookTelemetry(entry.id)
}
const renderLogbookDetailLegacy=renderLogbookDetail;
renderLogbookDetail=function(entry){if(!entry){renderLogbookDetailLegacy(entry);$('logbookCharts').hidden=true;return}renderLogbookDetailAdvanced(entry)};

const OBS_PREFS_KEY='opsroom-obs-overlay-v1';
function obsSelectedFields(){return [...document.querySelectorAll('#obsFieldSet input[type=checkbox]:checked')].map(x=>x.value)}
function saveObsPrefs(){try{localStorage.setItem(OBS_PREFS_KEY,JSON.stringify({view:$('obsView')?.value,layout:$('obsLayout')?.value,position:$('obsPosition')?.value,width:$('obsWidth')?.value,height:$('obsHeight')?.value,accent:$('obsAccent')?.value,opacity:$('obsOpacity')?.value,scale:$('obsScale')?.value,transparent:$('obsTransparent')?.checked,labels:$('obsLabels')?.checked,showLogo:$('obsShowLogo')?.checked,brandingMode:$('obsBrandingMode')?.value,logoPosition:$('obsLogoPosition')?.value,logoSize:$('obsLogoSize')?.value,fields:obsSelectedFields()}))}catch{}}
function restoreObsPrefs(){try{const p=JSON.parse(localStorage.getItem(OBS_PREFS_KEY)||'{}');obsBrandingPreferencePresent=Boolean(p.brandingMode);const values={obsView:p.view,obsLayout:p.layout,obsPosition:p.position,obsWidth:p.width,obsHeight:p.height,obsAccent:p.accent,obsOpacity:p.opacity,obsScale:p.scale,obsBrandingMode:p.brandingMode,obsLogoPosition:p.logoPosition,obsLogoSize:p.logoSize};for(const [id,value] of Object.entries(values))if(value!=null&&$(id))$(id).value=value;if(typeof p.transparent==='boolean')$('obsTransparent').checked=p.transparent;if(typeof p.labels==='boolean')$('obsLabels').checked=p.labels;if(typeof p.showLogo==='boolean')$('obsShowLogo').checked=p.showLogo;if(Array.isArray(p.fields)){const set=new Set(p.fields);document.querySelectorAll('#obsFieldSet input[type=checkbox]').forEach(x=>x.checked=set.has(x.value))}}catch{}}
function obsSourceUrl(){
  const params=new URLSearchParams({
    view:$('obsView')?.value||'flight',layout:$('obsLayout')?.value||'strip',position:$('obsPosition')?.value||'center',
    transparent:$('obsTransparent')?.checked!==false?'1':'0',labels:$('obsLabels')?.checked!==false?'1':'0',
    accent:$('obsAccent')?.value||'#76c4d3',opacity:String(Number($('obsOpacity')?.value||94)/100),scale:String(Number($('obsScale')?.value||100)/100),
    fields:obsSelectedFields().join(','),logo:$('obsShowLogo')?.checked?'1':'0',branding:$('obsBrandingMode')?.value||'active_airline',
    logo_position:$('obsLogoPosition')?.value||'left',logo_size:$('obsLogoSize')?.value||'72'
  });
  return `${location.origin}/obs?${params.toString()}`
}
function updateObsTools(){
  if(!$('obsUrl'))return;
  $('obsOpacityValue').textContent=`${$('obsOpacity').value}%`;$('obsScaleValue').textContent=`${$('obsScale').value}%`;$('obsLogoSizeValue').textContent=`${$('obsLogoSize').value} px`;
  saveObsPrefs();const url=obsSourceUrl();$('obsUrl').textContent=url;$('obsOpenSource').href=url;
  const width=Math.max(320,Number($('obsWidth')?.value||1280)),height=Math.max(120,Number($('obsHeight')?.value||260));
  $('obsPreview').style.height=`${Math.max(180,Math.min(520,Math.round(760*height/width)))}px`;
  $('obsPreview').src=`${url}&preview=1&t=${Date.now()}`;
  $('obsPreviewState').textContent=String($('obsView').value||'flight').replaceAll('_',' ').toUpperCase();
}
async function copyObsUrl(){const url=obsSourceUrl();try{await navigator.clipboard.writeText(url);$('obsCopyUrl').textContent='COPIED'}catch{window.prompt('Copy OBS browser-source URL',url)}setTimeout(()=>$('obsCopyUrl').textContent='COPY SOURCE URL',1400)}
async function loadObsBranding(){try{const r=await fetch('/api/obs/branding',{cache:'no-store'});obsBranding=await r.json();if(!obsBrandingPreferencePresent&&obsBranding.logo_available&&$('obsBrandingMode')){$('obsBrandingMode').value='custom';obsBrandingPreferencePresent=true}const mode=$('obsBrandingMode')?.value||obsBranding.default_mode||'active_airline',air=obsBranding.airline||{};$('obsLogoName').textContent=mode==='custom'?(obsBranding.logo_available?(obsBranding.filename||'CUSTOM LOGO'):'CUSTOM LOGO NOT SET'):mode==='ops_room'?'OPS ROOM':`${air.name||air.code||'ACTIVE AIRLINE'}${air.logo_available?' · LOGO READY':' · MONOGRAM'}`;$('obsBrandingState').textContent=mode==='custom'?(obsBranding.logo_available?'CUSTOM READY':'CUSTOM MISSING'):(mode==='ops_room'?'OPS ROOM':(air.code||'AIRLINE AUTO'));$('obsRemoveLogo').disabled=!obsBranding.logo_available;updateObsTools()}catch{$('obsBrandingState').textContent='UNAVAILABLE'}}
async function uploadObsLogo(file){if(!file)return;obsBrandingPreferencePresent=true;if($('obsBrandingMode'))$('obsBrandingMode').value='custom';if(file.size>2*1024*1024){$('obsBrandingState').textContent='MAX 2 MB';return}const reader=new FileReader();reader.onload=async()=>{try{$('obsBrandingState').textContent='UPLOADING';const r=await fetch('/api/obs/logo',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:file.name,data_url:reader.result})});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Upload failed');obsBranding=d;$('obsShowLogo').checked=true;await loadObsBranding()}catch(e){$('obsBrandingState').textContent=friendlyError(e.message)}};reader.readAsDataURL(file)}
async function removeObsLogo(){try{const r=await fetch('/api/obs/logo',{method:'DELETE'});if(!r.ok)throw new Error('Remove failed');await loadObsBranding()}catch(e){$('obsBrandingState').textContent=friendlyError(e.message)}}


let performanceProfiles = [];
let selectedPerformanceProfile = null;

function numberInput(id, fallback=0){
  const value = Number($(id)?.value);
  return Number.isFinite(value) ? value : fallback;
}

async function loadPerformanceProfiles(){
  if(performanceProfiles.length) return;
  try{
    const data = await fetch('/api/performance/profiles', {cache:'no-store'}).then(r=>r.json());
    performanceProfiles = data.profiles || [];
    const select = $('perfAircraft');
    if(select){
      select.innerHTML = performanceProfiles.map(p=>`<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)} (${escapeHtml(p.icao||'')})</option>`).join('');
      const preferred = performanceProfiles.find(p=>String(flightPlan?.aircraft?.icao || flightPlan?.aircraft_icao || '').toUpperCase().includes(String(p.icao||'').toUpperCase())) || performanceProfiles.find(p=>/A320|A20N|A321|B777|B77|A350/i.test(`${p.name} ${p.icao}`)) || performanceProfiles[0];
      if(preferred) select.value = preferred.id;
      selectedPerformanceProfile = preferred || null;
    }
    updatePerformanceFlaps();
    if($('performanceState')) $('performanceState').textContent = `${performanceProfiles.length} PROFILES LOADED`;
  }catch(error){
    if($('performanceState')) $('performanceState').textContent = friendlyError(error.message);
  }
}

function updatePerformanceFlaps(){
  const profile = performanceProfiles.find(p=>p.id === $('perfAircraft')?.value) || performanceProfiles[0];
  selectedPerformanceProfile = profile || null;
  const mode = $('perfMode')?.value || 'takeoff';
  const flaps = (mode === 'landing' ? profile?.landing_flaps : profile?.takeoff_flaps) || [];
  const select = $('perfFlap');
  if(select) select.innerHTML = flaps.length ? flaps.map(f=>`<option value="${escapeHtml(f)}">${escapeHtml(f)}</option>`).join('') : '<option value="">AUTO</option>';
  if(profile && $('perfWeight')){
    const w = mode === 'landing' ? profile.weights?.max_lw_kg : profile.weights?.max_tow_kg;
    if(w && (!$('perfWeight').value || Number($('perfWeight').value) <= 1)) $('perfWeight').value = Math.round(Number(w)*0.9);
  }
}


function selectTlrRunway(mode){
  const tlr=flightPlan?.tlr||{};
  const bucket=mode==='landing'?tlr.landing:tlr.takeoff;
  const runways=Array.isArray(bucket?.runways)?bucket.runways:[];
  if(!runways.length)return null;
  const planned=String(mode==='landing'?(flightPlan?.destination?.runway||''):(flightPlan?.origin?.runway||'')).replace(/^RWY/i,'').toUpperCase();
  return runways.find(r=>String(r.runway||'').replace(/^RWY/i,'').toUpperCase()===planned)||runways[0];
}
function tlrSpeedSummary(mode){
  const row=selectTlrRunway(mode);
  if(!row)return null;
  const flex=row.flex_temperature||row.assumed_temperature||row.max_temperature||'';
  const speedText=mode==='landing'
    ? `VREF ${row.speeds_vref||row.speed_vref||'---'} / VAPP ${row.speeds_vapp||row.speed_vapp||'---'}`
    : `V1 ${row.speeds_v1||'---'} / VR ${row.speeds_vr||'---'} / V2 ${row.speeds_v2||'---'}${flex?` / FLEX ${flex}`:''}`;
  const detailText=[
    `RWY ${row.runway||'not provided'}`,
    row.flap_setting?`FLAPS ${row.flap_setting}`:'',
    row.thrust_setting?`THR ${row.thrust_setting}`:'',
    flex?`TEMP ${flex}`:'',
    row.distance_margin?`MARGIN ${row.distance_margin}`:''
  ].filter(Boolean).join(' · ');
  return {row, speedText, detailText};
}

function renderPerformanceTlr(){
  const box=$('performanceTlr');
  if(!box)return;
  const mode=$('perfMode')?.value||'takeoff';
  const tlr=tlrSpeedSummary(mode);
  if(!tlr){box.hidden=true;box.innerHTML='';return;}
  box.innerHTML=`<strong>SIMBRIEF TLR DETAILS</strong><span>${escapeHtml(tlr.detailText)}</span><span>OPS ROOM calculator is primary; TLR shown as cross-check.</span>`;
  box.hidden=false;
}
function fillPerformanceFromSimbrief(){
  if(!flightPlan?.ok) return;
  const weights = flightPlan.weights || flightPlan.weight || {};
  const mode = $('perfMode')?.value || 'takeoff';
  const tow = Number(weights.takeoff_kg || weights.tow_kg || flightPlan.takeoff_weight_kg || 0);
  const lw = Number(weights.landing_kg || weights.lw_kg || flightPlan.landing_weight_kg || 0);
  const zfw = Number(weights.zfw_kg || weights.zfw || 0);
  if($('perfWeight')) $('perfWeight').value = Math.round((mode === 'landing' ? lw : tow) || tow || lw || Number($('perfWeight').value) || 0);renderPerformanceTlr();
  // ZFW / CG from SimBrief weights (CG is % MAC — the V-speed + trim model needs it).
  if($('perfCg')){
    const cg = Number(weights.zfwcg ?? weights.zfw_cg ?? 0);
    if(cg > 0) $('perfCg').value = cg;
  }
  if(flightPlan.origin?.elevation_ft && mode !== 'landing') $('perfElevation').value = Math.round(Number(flightPlan.origin.elevation_ft)||0);
  if(flightPlan.destination?.elevation_ft && mode === 'landing') $('perfElevation').value = Math.round(Number(flightPlan.destination.elevation_ft)||0);
  // Runway + weather from the departure/destination station: the OFP/METAR
  // already carry these, so the only thing the pilot must type is ZFW (+CG).
  const origin = flightPlan.origin || {};
  const dest = flightPlan.destination || {};
  const station = mode === 'landing' ? dest : origin;
  if(station.runway && $('perfRunwayLength')) $('perfRunwayLength').value = Math.round(Number(station.runway_length_m || station.runway_length || 0) || Number($('perfRunwayLength').value) || 0);
  if(station.runway && $('perfRunwayHeading')) $('perfRunwayHeading').value = Math.round(Number(station.runway_heading || station.runway_deg || 0) || Number($('perfRunwayHeading').value) || 0);
  const wx = station.weather || origin.weather || {};
  if(wx.temp_c != null && $('perfOat')) $('perfOat').value = Math.round(Number(wx.temp_c));
  if(wx.qnh_hpa != null && $('perfQnh')) $('perfQnh').value = Math.round(Number(wx.qnh_hpa));
  if(wx.wind_dir != null && $('perfWindDir')) $('perfWindDir').value = Math.round(Number(wx.wind_dir));
  if(wx.wind_kt != null && $('perfWindSpeed')) $('perfWindSpeed').value = Math.round(Number(wx.wind_kt));
}

async function calculatePerformance(){
  await loadPerformanceProfiles();
  const payload = {
    mode: $('perfMode')?.value || 'takeoff',
    aircraft: $('perfAircraft')?.value,
    weight_kg: numberInput('perfWeight', 0),
    runway_length_m: numberInput('perfRunwayLength', 0),
    runway_heading: numberInput('perfRunwayHeading', 0),
    wind_dir: numberInput('perfWindDir', 0),
    wind_speed: numberInput('perfWindSpeed', 0),
    oat_c: numberInput('perfOat', 15),
    qnh_hpa: numberInput('perfQnh', 1013),
    elevation_ft: numberInput('perfElevation', 0),
    slope_pct: numberInput('perfSlope', 0),
    condition: $('perfCondition')?.value || 'dry',
    flap: $('perfFlap')?.value || '',
    cg_pct: ($('perfCg')?.value === '' || $('perfCg')?.value == null) ? null : numberInput('perfCg', null),
    anti_ice: $('perfAntiIce')?.value === 'true',
    packs_on: $('perfPacks')?.value === 'true'
  };
  const box = $('performanceResult');
  try{
    const result = await fetch('/api/performance/calculate', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)}).then(async r=>{if(!r.ok)throw new Error((await r.json()).detail||'Performance calculation failed'); return r.json()});
    const tlr = tlrSpeedSummary(result.mode || payload.mode);
    const localSpeeds = result.mode === 'landing' ? `VREF ${result.speeds.vref_kt} / VAPP ${result.speeds.vapp_kt}` : `V1 ${result.speeds.v1_kt} / VR ${result.speeds.vr_kt} / V2 ${result.speeds.v2_kt}${result.speeds.flex_or_assumed_c?` / FLEX ${result.speeds.flex_or_assumed_c}`:''}`;
    // OPS ROOM is the primary speed source (own calculator); SimBrief TLR is
    // shown as a cross-check when present, never as the headline.
    const speeds = localSpeeds;
    const speedSource = 'OPS ROOM';
    const extra = [];
    if(result.recommended_flap) extra.push(`<div><span>FLAP</span><b>${escapeHtml(result.recommended_flap)}</b></div>`);
    if(result.speeds.pitch_trim != null) extra.push(`<div><span>PITCH TRIM</span><b>${escapeHtml(String(result.speeds.pitch_trim))} UP</b></div>`);
    if(result.speeds.flex_or_assumed_c != null) extra.push(`<div><span>FLEX TEMP</span><b>${escapeHtml(String(result.speeds.flex_or_assumed_c))} °C</b></div>`);
    if(tlr) extra.push(`<div><span>TLR CROSS-CHECK</span><b>${escapeHtml(tlr.speedText)}</b></div>`);
    if(box) box.innerHTML = `<div><span>STATUS</span><b>${escapeHtml(result.status)}</b></div><div><span>REQUIRED</span><b>${result.distances.factored_required_m} M</b></div><div><span>MARGIN</span><b>${result.distances.runway_margin_m ?? '---'} M</b></div><div><span>SPEEDS · ${escapeHtml(speedSource)}</span><b>${escapeHtml(speeds)}</b></div>${extra.join('')}`;
    if($('performanceWarnings')) $('performanceWarnings').innerHTML = (result.warnings||[]).map(w=>`<div>* ${escapeHtml(w)}</div>`).join('') || `<div>${escapeHtml(result.source || '')}</div>`;
    if($('performanceState')) $('performanceState').textContent = `${result.aircraft.icao || ''} ${result.mode.toUpperCase()} ${result.status}`;renderPerformanceTlr();
  }catch(error){
    if(box) box.innerHTML = `<div><span>STATUS</span><b>FAULT</b></div><div><span>REQUIRED</span><b>---</b></div><div><span>MARGIN</span><b>---</b></div><div><span>SPEEDS</span><b>---</b></div>`;
    if($('performanceWarnings')) $('performanceWarnings').innerHTML = `<div>${escapeHtml(friendlyError(error.message))}</div>`;
  }
}

async function startPerformance(){
  await loadPerformanceProfiles();
  renderPerformanceTlr();
}


function bugReportModuleLabel(){
  const label = PAGE_LABELS[activePage] || String(activePage || 'OPS ROOM').toUpperCase();
  return label.replace('OPS ROOM HOME','HOME');
}

function bugReportSetStatus(text, kind=''){
  const box = $('bugReportPreview');
  if(!box) return;
  box.textContent = text || '';
  box.classList.toggle('ok', kind === 'ok');
  box.classList.toggle('fault', kind === 'fault');
}

function bugReportPayload(){
  return {
    activePage,
    module: $('bugReportModule')?.value || bugReportModuleLabel(),
    contact: $('bugReportContact')?.value || '',
    userDescription: $('bugReportDescription')?.value || '',
    expectedResult: $('bugReportExpected')?.value || '',
    stepsToReproduce: $('bugReportSteps')?.value || '',
    includeDiagnosticsZip: $('bugReportIncludeZip')?.checked !== false,
    lastError: lastFrontendError || '',
    route: flightPlan?.ok ? `${flightPlan.origin?.icao || flightPlan.origin || '----'}-${flightPlan.destination?.icao || flightPlan.destination || '----'}` : '',
    aircraft: flightPlan?.aircraft?.icao || flightPlan?.aircraft_icao || flightPlan?.aircraft || '',
    airport: summary?.nearest_airport || ''
  };
}

function openBugReport(){
  if($('bugReportModule')) $('bugReportModule').value = bugReportModuleLabel();
  if($('bugReportOverlay')) $('bugReportOverlay').hidden = false;
  if($('bugReportModal')) $('bugReportModal').hidden = false;
  bugReportSetStatus('Ready. Describe the issue, then send or download diagnostics.');
  setTimeout(()=>$('bugReportDescription')?.focus(),60);
}

function closeBugReport(){
  if($('bugReportOverlay')) $('bugReportOverlay').hidden = true;
  if($('bugReportModal')) $('bugReportModal').hidden = true;
}

function setBugReportBusy(busy){
  const on = Boolean(busy);
  $('bugReportModal')?.classList.toggle('busy', on);
  ['bugReportSend','bugReportCopy','bugReportDownload'].forEach(id=>{const el=$(id); if(el) el.disabled = on;});
  // Reflect the in-flight (send/copy/download) state on the footer Report Bug FAB so the
  // trigger shows a busy/disabled state during a send and is re-enabled on completion/error.
  const fab = $('bugReportButton');
  if(fab){
    fab.classList.toggle('is-sending', on);
    fab.disabled = on;
    if(on) fab.setAttribute('aria-busy','true'); else fab.removeAttribute('aria-busy');
  }
}

async function copyBugReportSummary(){
  setBugReportBusy(true);
  bugReportSetStatus('Generating report summary...');
  try{
    const response = await fetch('/api/diagnostics/bug-report/summary',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(bugReportPayload())});
    const data = await safeJsonResponse(response);
    await navigator.clipboard.writeText(data.summaryText || '');
    bugReportSetStatus(`Copied report ${data.report?.reportId || ''} to clipboard.`, 'ok');
  }catch(error){
    bugReportSetStatus(`Copy failed: ${friendlyError(error.message)}`, 'fault');
  }finally{
    setBugReportBusy(false);
  }
}

async function downloadBugReportZip(){
  setBugReportBusy(true);
  bugReportSetStatus('Creating diagnostics ZIP...');
  try{
    const response = await fetch('/api/diagnostics/bug-report/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(bugReportPayload())});
    if(!response.ok){
      let detail = '';
      try{ detail = (await response.json()).detail || ''; }catch{}
      throw new Error(detail || `HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const disposition = response.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename\*?=(?:UTF-8''|\")?([^\";]+)/i);
    const filename = match ? decodeURIComponent(match[1].replace(/\"/g,'')) : `OPS_ROOM_Diagnostics_${Date.now()}.zip`;
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1200);
    bugReportSetStatus(`Downloaded ${filename}.`, 'ok');
  }catch(error){
    bugReportSetStatus(`Download failed: ${friendlyError(error.message)}`, 'fault');
  }finally{
    setBugReportBusy(false);
  }
}

async function sendBugReport(){
  const payload = bugReportPayload();
  if(!payload.userDescription.trim() && !(await uiConfirm('Send a bug report without a description? Useful reports should say what happened.', 'SEND'))) return;
  if(payload.includeDiagnosticsZip && !(await uiConfirm('Send this bug report with redacted OPS ROOM diagnostics and recent logs?', 'SEND'))) return;
  setBugReportBusy(true);
  bugReportSetStatus('Sending bug report and diagnostics...');
  try{
    const response = await fetch('/api/diagnostics/bug-report/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const data = await safeJsonResponse(response);
    if(!data.ok) throw new Error(data.error || 'Bug report was not accepted by the endpoint.');
    const fileLine = data.diagnosticsFileUrl ? `\nDiagnostics uploaded to Google Drive.` : '';
    bugReportSetStatus(`Report sent. ID: ${data.reportId || 'received'}${fileLine}`, 'ok');
  }catch(error){
    bugReportSetStatus(`Send failed: ${friendlyError(error.message)}\nUse DOWNLOAD ZIP or COPY REPORT as fallback.`, 'fault');
  }finally{
    setBugReportBusy(false);
  }
}

window.addEventListener('error', event=>{
  lastFrontendError = `${event.message || 'Script error'} ${event.filename || ''}:${event.lineno || ''}`.trim();
});
window.addEventListener('unhandledrejection', event=>{
  const reason = event.reason?.message || event.reason || 'Unhandled promise rejection';
  lastFrontendError = String(reason).slice(0,500);
});


function scratchpadDefaultFields(){return {callsign:'',aircraft:'',departure:'',destination:'',flight_level:'',route:'',ramp_position:'',atis:'',runway:'',initial_altitude:'',sid_transition:'',departure_frequency:'',squawk:'',taxi:'',metar:'',notes:'',blank_text:''}}
function scratchpadModeForPage(page){return page==='blank'?'blank':'template'}
function setScratchpadState(text){if($('scratchpadState'))$('scratchpadState').textContent=text}
function scratchpadControlsReady(){return !!($('scratchpadCanvas')&&$('scratchpadTemplate')&&$('scratchpadBlank'))}
async function startScratchpad(){if(!scratchpadControlsReady())return;bindScratchpadCanvas();if(!scratchpadPeriodicSaveTimer)scratchpadPeriodicSaveTimer=setInterval(()=>{if(activePage==='scratchpad'&&scratchpadDirty&&!scratchpadDrawing&&!scratchpadSaving)saveScratchpad()},15000);await loadScratchpadPage(scratchpadPage);setTimeout(resizeScratchpadCanvas,60)}
async function loadScratchpadPage(page){if(scratchpadDirty&&!scratchpadDrawing)await saveScratchpad();scratchpadPage=page||'departure';document.querySelectorAll('[data-scratchpad-page]').forEach(b=>b.classList.toggle('active',b.dataset.scratchpadPage===scratchpadPage));try{const response=await fetch(`/api/scratchpad/page/${encodeURIComponent(scratchpadPage)}`,{cache:'no-store'});const incoming=await safeJsonResponse(response);if(!scratchpadDrawing&&!scratchpadDirty){scratchpadData=incoming;scratchpadData.fields={...scratchpadDefaultFields(),...(scratchpadData.fields||{})};scratchpadData.strokes=Array.isArray(scratchpadData.strokes)?scratchpadData.strokes:[];renderScratchpad()}setScratchpadState('AUTOSAVE READY')}catch(error){setScratchpadState('LOAD FAILED');console.warn(error)}}
function renderScratchpad(){const blank=scratchpadPage==='blank'||scratchpadData.mode==='blank';$('scratchpadTemplate').hidden=blank;$('scratchpadBlank').hidden=!blank;document.querySelectorAll('[data-scratch-field]').forEach(el=>{const key=el.dataset.scratchField;el.value=scratchpadData.fields?.[key]||''});$('scratchpadUpdated').textContent=scratchpadData.updated_at?`SAVED ${messageTime(scratchpadData.updated_at)}Z`:'NOT SAVED YET';resizeScratchpadCanvas();drawScratchpad()}
function collectScratchpadFields(){const fields=scratchpadDefaultFields();document.querySelectorAll('[data-scratch-field]').forEach(el=>{fields[el.dataset.scratchField]=el.value||''});return fields}
function scheduleScratchpadSave(delay=1200){if(activePage!=='scratchpad')return;scratchpadDirty=true;setScratchpadState(scratchpadDrawing?'WRITING':'SAVE PENDING');clearTimeout(scratchpadSaveTimer);scratchpadSaveTimer=setTimeout(()=>{if(!scratchpadDrawing)saveScratchpad();else scheduleScratchpadSave(1200)},Math.max(900,delay))}
async function saveScratchpad(){if(scratchpadDrawing){scheduleScratchpadSave(1400);return}if(scratchpadSaving)return;scratchpadSaving=true;try{scratchpadData.fields=collectScratchpadFields();const strokesSnapshot=JSON.parse(JSON.stringify(scratchpadData.strokes||[]));const response=await fetch(`/api/scratchpad/page/${encodeURIComponent(scratchpadPage)}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:scratchpadModeForPage(scratchpadPage),fields:scratchpadData.fields,strokes:strokesSnapshot})});const saved=await safeJsonResponse(response);scratchpadDirty=false;scratchpadData.updated_at=saved.updated_at||scratchpadData.updated_at;setScratchpadState('SAVED');$('scratchpadUpdated').textContent=scratchpadData.updated_at?`SAVED ${messageTime(scratchpadData.updated_at)}Z`:'SAVED'}catch(error){setScratchpadState('SAVE FAILED');console.warn(error)}finally{scratchpadSaving=false}}
function bindScratchpadCanvas(){if(scratchpadCanvasReady)return;scratchpadCanvasReady=true;document.querySelectorAll('[data-scratch-field]').forEach(el=>el.addEventListener('input',()=>scheduleScratchpadSave(1200)));document.querySelectorAll('[data-scratchpad-page]').forEach(b=>b.addEventListener('click',()=>loadScratchpadPage(b.dataset.scratchpadPage)));$('scratchpadType')?.addEventListener('click',()=>setScratchpadTool('type'));$('scratchpadPen')?.addEventListener('click',()=>setScratchpadTool('pen'));$('scratchpadEraser')?.addEventListener('click',()=>setScratchpadTool('eraser'));$('scratchpadUndo')?.addEventListener('click',()=>{(scratchpadData.strokes||[]).pop();drawScratchpad();scheduleScratchpadSave(1200)});$('scratchpadClearInk')?.addEventListener('click',async()=>{if(await uiConfirm('Clear handwriting from this scratchpad page?', 'CLEAR')){scratchpadData.strokes=[];drawScratchpad();scheduleScratchpadSave(1200)}});$('scratchpadClearPage')?.addEventListener('click',clearScratchpadPage);$('scratchpadAutofill')?.addEventListener('click',autofillScratchpadFromFlight);$('scratchpadSize')?.addEventListener('input',()=>{});const canvas=$('scratchpadCanvas');canvas.addEventListener('pointerdown',scratchpadPointerDown);canvas.addEventListener('pointermove',scratchpadPointerMove);canvas.addEventListener('pointerup',scratchpadPointerUp);canvas.addEventListener('pointercancel',scratchpadPointerUp);window.addEventListener('resize',()=>{if(activePage==='scratchpad'&&!scratchpadDrawing)resizeScratchpadCanvas()});window.addEventListener('beforeunload',()=>{if(scratchpadDirty&&!scratchpadDrawing){try{navigator.sendBeacon(`/api/scratchpad/page/${encodeURIComponent(scratchpadPage)}`,new Blob([JSON.stringify({mode:scratchpadModeForPage(scratchpadPage),fields:collectScratchpadFields(),strokes:scratchpadData.strokes||[]})],{type:'application/json'}))}catch(_){}}});setScratchpadTool('type')}
function setScratchpadTool(tool){if(!['type','pen','eraser'].includes(tool))tool='type';scratchpadTool=tool;$('scratchpadType')?.classList.toggle('primary-control',tool==='type');$('scratchpadPen')?.classList.toggle('primary-control',tool==='pen');$('scratchpadEraser')?.classList.toggle('primary-control',tool==='eraser');const canvas=$('scratchpadCanvas');if(canvas){canvas.dataset.tool=tool;canvas.style.pointerEvents=tool==='type'?'none':'auto';canvas.style.touchAction=tool==='type'?'auto':'none';canvas.setAttribute('aria-hidden',tool==='type'?'true':'false')}const wrap=canvas?.parentElement;if(wrap)wrap.dataset.scratchpadMode=tool}
function scratchpadPoint(event){const canvas=$('scratchpadCanvas');const rect=canvas.getBoundingClientRect();const w=Math.max(1,rect.width||canvas.clientWidth||1),h=Math.max(1,rect.height||canvas.clientHeight||1);return {x:Math.max(0,Math.min(1,(event.clientX-rect.left)/w)),y:Math.max(0,Math.min(1,(event.clientY-rect.top)/h))}}
function scratchpadPointerDown(event){if(activePage!=='scratchpad'||scratchpadTool==='type')return;event.preventDefault();clearTimeout(scratchpadSaveTimer);const canvas=$('scratchpadCanvas');canvas?.setPointerCapture?.(event.pointerId);scratchpadDrawing=true;scratchpadDirty=true;scratchpadCurrentStroke={tool:scratchpadTool,width:Number($('scratchpadSize')?.value||4),points:[scratchpadPoint(event)]};(scratchpadData.strokes||(scratchpadData.strokes=[])).push(scratchpadCurrentStroke);setScratchpadState(`WRITING ${String(event.pointerType||'POINTER').toUpperCase()}`);drawScratchpad()}
function scratchpadPointerMove(event){if(!scratchpadDrawing||!scratchpadCurrentStroke)return;event.preventDefault();scratchpadCurrentStroke.points.push(scratchpadPoint(event));drawScratchpad()}
function scratchpadPointerUp(event){if(!scratchpadDrawing)return;event.preventDefault();scratchpadDrawing=false;scratchpadCurrentStroke=null;scheduleScratchpadSave(1400)}
function resizeScratchpadCanvas(){const canvas=$('scratchpadCanvas'),wrap=canvas?.parentElement;if(!canvas||!wrap)return;const rect=wrap.getBoundingClientRect();const scale=window.devicePixelRatio||1;const width=Math.max(300,Math.round(rect.width));const height=Math.max(420,Math.round(rect.height));if(canvas.width!==Math.round(width*scale)||canvas.height!==Math.round(height*scale)){canvas.width=Math.round(width*scale);canvas.height=Math.round(height*scale);canvas.style.width=`${width}px`;canvas.style.height=`${height}px`;const ctx=canvas.getContext('2d');ctx.setTransform(scale,0,0,scale,0,0);drawScratchpad()}}
function drawScratchpad(){const canvas=$('scratchpadCanvas');if(!canvas)return;const ctx=canvas.getContext('2d');const rect=canvas.getBoundingClientRect();const w=Math.max(1,rect.width||canvas.clientWidth||1),h=Math.max(1,rect.height||canvas.clientHeight||1);ctx.clearRect(0,0,w,h);ctx.lineCap='round';ctx.lineJoin='round';for(const stroke of scratchpadData.strokes||[]){const points=stroke.points||[];if(!points.length)continue;ctx.globalCompositeOperation=stroke.tool==='eraser'?'destination-out':'source-over';ctx.strokeStyle=stroke.tool==='eraser'?'rgba(0,0,0,1)':'#f2f0e5';ctx.lineWidth=Number(stroke.width||4);ctx.beginPath();ctx.moveTo(points[0].x*w,points[0].y*h);if(points.length===1){ctx.arc(points[0].x*w,points[0].y*h,Math.max(1,Number(stroke.width||4)/2),0,Math.PI*2);ctx.fillStyle=ctx.strokeStyle;ctx.fill()}else{for(const point of points.slice(1))ctx.lineTo(point.x*w,point.y*h);ctx.stroke()}}ctx.globalCompositeOperation='source-over'}
async function clearScratchpadPage(){if(!(await uiConfirm('Clear typed notes and handwriting from this scratchpad page?', 'CLEAR')))return;try{const response=await fetch(`/api/scratchpad/page/${encodeURIComponent(scratchpadPage)}`,{method:'DELETE'});scratchpadData=await safeJsonResponse(response);scratchpadData.fields={...scratchpadDefaultFields(),...(scratchpadData.fields||{})};renderScratchpad();setScratchpadState('PAGE CLEARED')}catch(error){setScratchpadState('CLEAR FAILED')}}
function autofillScratchpadFromFlight(){const plan=flightPlan||{};const ofp=plan.ofp||plan;const general = ofp?.general || {};const origin=ofp.origin||{};const destination=ofp.destination||{};const fields={...scratchpadDefaultFields(),...collectScratchpadFields()};const airline=general.icao_airline||general.airline||'';const flightNo=general.flight_number||general.flight||'';fields.callsign=fields.callsign||(airline&&flightNo?`${airline}${flightNo}`:'')||ofp.callsign||plan.callsign||'';fields.aircraft=fields.aircraft||general.aircraft_icao||general.aircraft||'';fields.departure=fields.departure||origin.icao_code||origin.icao||'';fields.destination=fields.destination||destination.icao_code||destination.icao||'';fields.flight_level=fields.flight_level||general.initial_altitude||general.cruise_profile||'';fields.route=fields.route||(ofp.navlog&&ofp.navlog.route)||ofp.route||general.route||'';scratchpadData.fields=fields;renderScratchpad();scheduleScratchpadSave()}

async function loadCameraBridgeStatus(){if(!$('cameraBridgeBox'))return;try{const response=await fetch('/api/camera/bridge/status',{cache:'no-store'});const data=await safeJsonResponse(response);renderCameraBridgeStatus(data);if(data?.target?.view)syncCameraControls(data.target.view);if(!cameraBridgeTimer)cameraBridgeTimer=setInterval(loadCameraBridgeStatus,3500)}catch(error){if($('cameraBridgeState'))$('cameraBridgeState').textContent='FAULT';$('cameraBridgeBox').className='maintenance-box fault';$('cameraBridgeBox').innerHTML=`<b>NATIVE WASM CAMERA</b><p>${escapeHtml(friendlyError(error.message))}</p>`}}
function cameraStatusTargetName(data,status){return status.target||data?.target?.callsign||'none'}
function renderCameraBridgeStatus(data){const status=data?.status||{};const brokerLoaded=!!(data?.broker_loaded||status.loaded);const nativeLoaded=!!(data?.native_api_loaded||status.native_api_loaded);const running=!!(data?.running||nativeLoaded);const state=status.state||status.camera_state||status.phase||(nativeLoaded?'API READY':(brokerLoaded?'BROKER READY':'STANDBY'));if($('cameraBridgeState'))$('cameraBridgeState').textContent=String(state).toUpperCase();$('cameraBridgeBox').className=`maintenance-box ${nativeLoaded?'ready':(data.available?'waiting':'fault')}`;const target=cameraStatusTargetName(data,status);const match=status.match||'none';const mode=status.mode||data?.target?.view?.mode||cameraViewState.mode;const activation=data?.native_api_activation_message||status.native_api_activation_message||'';$('cameraBridgeBox').innerHTML=`<b>MSFS 2024 CAMERA BRIDGE</b><p>${escapeHtml(data.message||status.message||'Waiting for bridge status.')}</p><p>Target: ${escapeHtml(target)} · Match: ${escapeHtml(match)} · Mode: ${escapeHtml(String(mode).replaceAll('_',' ').toUpperCase())}</p>${activation&&!nativeLoaded?`<p>${escapeHtml(activation)}</p>`:''}`}
async function startCameraBridge(){try{const response=await fetch('/api/camera/bridge/start',{method:'POST'});const data=await safeJsonResponse(response);renderCameraBridgeStatus(data);if(data.ok===false)alert(data.error||'Native bridge is not ready. Copy ops-room-bridge into MSFS 2024 Community, restart MSFS, then check Bridge status.')}catch(error){alert(`Camera bridge failed: ${friendlyError(error.message)}`)}}
async function releaseCameraBridge(){try{const response=await fetch('/api/camera/bridge/release',{method:'POST'});const data=await safeJsonResponse(response);renderCameraBridgeStatus(data);notifyOps({source:'CAMERA BRIDGE',title:'CAMERA RELEASED',message:'OPS ROOM stopped watching and requested return to the user aircraft.',priority:'advisory'})}catch(error){alert(`Camera release failed: ${friendlyError(error.message)}`)}}
async function resetCameraBridgeView(){cameraViewState={mode:'tail_follow',distance:55,height:10,sideOffset:0,pitch:-7,orbitAngle:180,smoothing:0.35};syncCameraControls(cameraViewState);try{const response=await fetch('/api/camera/reset-view',{method:'POST'});const data=await safeJsonResponse(response);if(data?.target?.view)syncCameraControls(data.target.view);await loadCameraBridgeStatus()}catch(error){alert(`Reset view failed: ${friendlyError(error.message)}`)}}
async function recenterCameraBridge(){cameraViewState.sideOffset=0;cameraViewState.orbitAngle=180;syncCameraControls(cameraViewState);await sendCameraViewNow()}
function readCameraControls(){const read=(name,fallback)=>{const el=document.querySelector(`[data-camera-control="${name}"]`);const v=el?Number(el.value):Number(fallback);return Number.isFinite(v)?v:fallback};return {mode:cameraViewState.mode,distance:read('distance',cameraViewState.distance),height:read('height',cameraViewState.height),sideOffset:read('sideOffset',cameraViewState.sideOffset),pitch:read('pitch',cameraViewState.pitch),orbitAngle:read('orbitAngle',cameraViewState.orbitAngle),smoothing:read('smoothing',cameraViewState.smoothing)}}
function syncCameraControls(view){cameraViewState={...cameraViewState,...(view||{})};document.querySelectorAll('[data-camera-mode]').forEach(button=>{const active=button.dataset.cameraMode===cameraViewState.mode;button.classList.toggle('primary-control',active);button.setAttribute('aria-pressed',active?'true':'false')});Object.entries(cameraViewState).forEach(([key,value])=>{const el=document.querySelector(`[data-camera-control="${key}"]`);if(el&&String(el.value)!==String(value))el.value=value})}
async function sendCameraViewNow(){cameraViewState=readCameraControls();try{const response=await fetch('/api/camera/view',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cameraViewState)});const data=await safeJsonResponse(response);if(data?.target?.view)syncCameraControls(data.target.view);await loadCameraBridgeStatus()}catch(error){console.warn('Camera view update failed',error)}}
function scheduleCameraViewUpdate(){clearTimeout(cameraViewSaveTimer);cameraViewSaveTimer=setTimeout(sendCameraViewNow,180)}
function bindCameraControls(){document.querySelectorAll('[data-camera-mode]').forEach(button=>button.addEventListener('click',()=>{cameraViewState.mode=button.dataset.cameraMode||'tail_follow';syncCameraControls(cameraViewState);scheduleCameraViewUpdate()}));document.querySelectorAll('[data-camera-control]').forEach(input=>input.addEventListener('input',()=>{cameraViewState=readCameraControls();scheduleCameraViewUpdate()}));syncCameraControls(cameraViewState)}
async function showCameraBridgeLog(){try{const response=await fetch('/api/camera/bridge/log?lines=180',{cache:'no-store'});const data=await safeJsonResponse(response);const box=$('cameraBridgeLogText');box.hidden=!box.hidden;box.textContent=(data.lines||[]).join('\n')||'No camera bridge log yet.'}catch(error){alert(`Log read failed: ${friendlyError(error.message)}`)}}


function formatFeet(value){
  const n = Number(value);
  return Number.isFinite(n) ? `${Math.round(n)} FT` : '----';
}
function raasUnitFromData(data){
  const raw = String(data?.raas_unit || data?.unit_code || data?.last_callout_unit || 'ft').trim().toLowerCase();
  return raw.startsWith('m') ? 'm' : 'ft';
}
function raasUnitCode(data){
  return raasUnitFromData(data)==='m' ? 'M' : 'FT';
}
function formatRaasDistance(valueFt, data){
  const n = Number(valueFt);
  if(!Number.isFinite(n)) return '----';
  if(raasUnitFromData(data)==='m') return `${Math.round(n*0.3048)} M`;
  return `${Math.round(n)} FT`;
}
function renderRaasUnitButtons(unit){
  const selected = String(unit||'ft').toLowerCase().startsWith('m') ? 'm' : 'ft';
  document.querySelectorAll('[data-raas-unit]').forEach(button=>{
    const active = button.dataset.raasUnit === selected;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
}

// v0.25.60 — RAAS global toast. Poll interval is 5s; the freshness window must
// have comfortable headroom above it (3x), otherwise any poll/fetch delay or
// backend processing time between the runway event and the created_epoch stamp
// blows through the window and the toast is silently dropped as stale.
const RAAS_TOAST_FRESH_SECONDS = 15;
// Set localStorage opsroom-raas-debug=1 to log why a toast was gated.
const RAAS_TOAST_DEBUG = (()=>{try{return localStorage.getItem('opsroom-raas-debug')==='1'}catch(e){return false}})();
function showRaasCenterToast(data, force=false){
  const type = String(data?.last_callout_type||'').toLowerCase();
  if(!data || (data.suppress_center_toast && type !== 'test')){
    if(RAAS_TOAST_DEBUG) console.warn('[RAAS] toast gated: suppress_center_toast=true type='+type);
    return;
  }
  const created = Number(data.raas_event_created_epoch||0);
  const active = data.raas_event_active !== false;
  if(!active || !created || (Date.now()/1000-created)>RAAS_TOAST_FRESH_SECONDS){
    if(RAAS_TOAST_DEBUG) console.warn('[RAAS] toast gated: active='+active+' created='+created+' age='+(created?(Date.now()/1000-created).toFixed(1):'n/a')+'s (window '+RAAS_TOAST_FRESH_SECONDS+'s)');
    return;
  }
  if(!force){
    if(!data.toast_id || data.toast_id === lastRaasToastId){
      if(RAAS_TOAST_DEBUG) console.warn('[RAAS] toast gated: dedup toast_id='+data.toast_id+' last='+lastRaasToastId);
      return;
    }
    lastRaasToastId = data.toast_id;
  }else if(data.toast_id){
    lastRaasToastId = data.toast_id;
  }
  const raasText = formatRaasGlobalText(data);
  if(!raasText){
    if(RAAS_TOAST_DEBUG) console.warn('[RAAS] toast gated: empty text type='+type+' last_callout='+String(data.last_callout||'').slice(0,60)+' display='+String(data.display||'').slice(0,60));
    return;
  }
  showRaasGlobalAlert(raasText, data.last_callout_priority || 'advisory');
}



function formatRaasGlobalText(data){
  const type = String(data.last_callout_type || '').toLowerCase();
  const raw = String(type === 'test' ? (data.display || data.last_callout || '') : (data.last_callout || data.display || '')).trim();
  const okCode = `RAAS-OK-${raasUnitCode(data)}`;
  if(type === 'test') return okCode;
  if(!raw || /^RAAS-(STBY|OK-(M|FT)|UNAV|FAULT|OFF)$/i.test(raw)) return '';
  let text = raw.toUpperCase();
  text = text.replace(/^APPROACHING RUNWAY\s+/, 'APP RWY ');
  text = text.replace(/^ON RUNWAY\s+/, 'ON RWY ');
  text = text.replace(/^RUNWAY AWARENESS OK$/, okCode);
  return text;
}
function showRaasGlobalAlert(text, priority='advisory'){
  const el = $('raasGlobalAlert');
  if(!el || !text) return;
  el.textContent = text;
  el.dataset.priority = String(priority||'advisory').toLowerCase();
  el.hidden = false;
  el.classList.remove('show');
  void el.offsetWidth;
  el.classList.add('show');
  clearTimeout(raasGlobalTimer);
  raasGlobalTimer = setTimeout(()=>{el.classList.remove('show'); setTimeout(()=>{el.hidden=true}, 250)}, 4400);
}

function showLandingToast(data){
  if(!data?.id||data.id===lastLandingToastId)return;
  lastLandingToastId=data.id;
  const landingNumber=value=>value===null||value===undefined||value===''?null:(Number.isFinite(Number(value))?Number(value):null);
  const rate=landingNumber(data.landing_rate_fpm),absRate=rate!=null?Math.round(Math.abs(rate)):null;
  const quality=absRate==null?'LANDING':absRate<=120?'SMOOTH':absRate<=240?'FIRM':absRate<=450?'HARD':'VERY HARD';
  const fpm=rate!=null?`${Math.round(rate)} FPM`:'-- FPM';
  const cells=[
    ['RATE',fpm],
    ['G-FORCE',landingNumber(data.touchdown_g)!=null?`${landingNumber(data.touchdown_g).toFixed(2)} G`:'--'],
    ['SPEED',landingNumber(data.touchdown_speed_kts)!=null?`${Math.round(landingNumber(data.touchdown_speed_kts))} KT`:'--'],
    ['TD POINT',landingNumber(data.touchdown_distance_ft)!=null?`${Math.round(landingNumber(data.touchdown_distance_ft)).toLocaleString()} FT`:'--'],
    ['CENTERLINE',landingNumber(data.touchdown_centerline_deviation_ft)!=null?`${Math.round(Math.abs(landingNumber(data.touchdown_centerline_deviation_ft)))} FT`:'--'],
    ['ATTITUDE',`${landingNumber(data.touchdown_pitch_deg)!=null?landingNumber(data.touchdown_pitch_deg).toFixed(1):'--'}° / ${landingNumber(data.touchdown_bank_deg)!=null?landingNumber(data.touchdown_bank_deg).toFixed(1):'--'}°`],
  ];
  const bounce=Number(data.bounce_count)>0?`<div class="landing-toast-warning">BOUNCE ${escapeHtml(String(data.bounce_severity||'DETECTED').toUpperCase())}</div>`:'';
  const toast=$('landingToast'),text=$('landingToastText');
  if(!toast||!text)return;
  text.innerHTML=`<div class="landing-toast-head"><span>LANDING</span><strong>${escapeHtml(quality)}</strong></div><div class="landing-toast-grid">${cells.map(([k,v])=>`<div><small>${escapeHtml(k)}</small><b>${escapeHtml(v)}</b></div>`).join('')}</div>${bounce}`;
  toast.hidden=false;
}
async function pollLandingResult(){
  try{
    const r=await fetch('/api/logbook/landing-latest',{cache:'no-store'});
    if(!r.ok){console.warn('[landing] poll HTTP '+r.status);return;}
    const d=await r.json();
    if(!landingMonitorPrimed){
      landingMonitorPrimed=true;
      landingMonitorStartedAt=Date.now();
      // Prime against a timestamp boundary rather than presence/absence: a
      // landing recorded around app boot must still toast instead of being
      // silently absorbed as the baseline.
      const ts=landingRecordEpoch(d);
      if(d?.id && ts && ts>=landingMonitorStartedAt-20000){ showLandingToast(d); startLandingBurst(); return; }
      lastLandingToastId=d?.id||null;
      return;
    }
    showLandingToast(d);
    startLandingBurst();
  }catch(err){ console.warn('[landing] poll failed', err); }
}
function landingRecordEpoch(d){
  if(!d) return 0;
  const raw=String(d.updated_utc||d.landing_utc||'');
  const ts=Date.parse(raw);
  return Number.isFinite(ts)?ts:0;
}
function startLandingBurst(){
  if(landingBurstTimer) return;
  clearInterval(landingMonitorTimer);
  landingMonitorTimer=setInterval(pollLandingResult,2000);
  landingBurstTimer=setTimeout(()=>{
    clearInterval(landingMonitorTimer);
    landingMonitorTimer=setInterval(pollLandingResult,10000);
    landingBurstTimer=null;
  },15000);
}
function startLandingMonitor(){
  if(landingMonitorTimer)return;
  pollLandingResult();
  landingMonitorTimer=setInterval(pollLandingResult,10000);
}


const RAAS_CLIENT_CLIPS={
  '0':'0.opus','1':'1.opus','2':'2.opus','3':'3.opus','4':'4.opus','5':'5.opus','6':'6.opus','7':'7.opus','8':'8.opus','9':'9.opus',
  '30':'30.opus',rwy:'rwy.opus',rwys:'rwys.opus',on_rwy:'on_rwy.opus',on_twy:'on_twy.opus',twy:'twy.opus',left:'left.opus',right:'right.opus',center:'center.opus',
  rmng:'rmng.opus',feet:'feet.opus',meters:'meters.opus',hundred:'hundred.opus',thousand:'thousand.opus',caution:'caution.opus',short_rwy:'short_rwy.opus',
  too_high:'too_high.opus',too_fast:'too_fast.opus',unstable:'unstable.opus',long_land:'long_land.opus',deep_land:'deep_land.opus',apch:'apch.opus'
};
function raasSpeakBrowser(text){
  try{
    if(!('speechSynthesis' in window)) return false;
    const u=new SpeechSynthesisUtterance(String(text||'Runway Awareness OK'));
    u.rate=0.96; u.volume=1;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
    return true;
  }catch(_){return false}
}
function raasRunwayClipKeys(runway){
  let text=String(runway||'').toUpperCase().replace(/^RWY\s*/,'').replace(/^RUNWAY\s*/,'').trim();
  let suffix='';
  if(/[LRC]$/.test(text)){suffix=text.slice(-1); text=text.slice(0,-1)}
  text=text.padStart(2,'0').slice(-2);
  const keys=text.split('');
  if(suffix==='L') keys.push('left');
  if(suffix==='R') keys.push('right');
  if(suffix==='C') keys.push('center');
  return keys;
}
function raasNumberClipKeys(value){
  const n=Math.max(0,Math.round(Number(value||0)/100)*100);
  if(n>=1000){
    const thousands=Math.floor(n/1000), remainder=n%1000;
    const keys=String(thousands).split('').concat(['thousand']);
    if(remainder){
      if(remainder>=100 && remainder%100===0) keys.push(...String(remainder/100).split(''),'hundred');
      else keys.push(...String(remainder).split(''));
    }
    return keys;
  }
  if(n>=100 && n%100===0) return String(n/100).split('').concat(['hundred']);
  return String(n).split('');
}
function raasClientSegmentKeys(data){
  const type=String(data?.last_callout_type||'').toLowerCase();
  const runway=String(data?.active_runway||data?.runway?.runway||'');
  if(type==='test') return [];
  if(type==='approaching_runway') return ['apch','rwy',...raasRunwayClipKeys(runway)];
  if(type==='on_runway') return ['on_rwy',...raasRunwayClipKeys(runway)];
  if(type==='taxiway_takeoff') return ['caution','on_twy'];
  if(type==='short_runway') return ['caution','short_rwy'];
  if(type==='remaining'){
    const unit=String(data?.last_callout_unit || data?.unit_code || 'FT').toUpperCase()==='M'?'meters':'feet';
    let value=Number(data?.last_callout_distance_value);
    if(!Number.isFinite(value)){
      const ft=Number(data?.last_callout_distance_ft||data?.runway?.remaining_spoken_ft||0);
      value=unit==='meters'?ft*0.3048:ft;
    }
    return [...raasNumberClipKeys(value),unit,'rmng'];
  }
  if(type==='unstable') return ['unstable'];
  if(type==='too_fast') return ['too_fast'];
  if(type==='too_high') return ['too_high'];
  if(type==='long_landing') return ['long_land'];
  if(type==='deep_landing') return ['deep_land'];
  return [];
}
function raasPlayClipFile(filename){
  return new Promise((resolve,reject)=>{
    const audio=new Audio(`/api/raas/audio/${encodeURIComponent(filename)}?t=${Date.now()}`);
    audio.preload='auto';
    audio.onended=()=>resolve(true);
    audio.onerror=()=>reject(new Error('clip failed'));
    audio.play().then(()=>{}).catch(reject);
  });
}
async function tryRaasClientAudio(data){
  if(!data || !data.toast_id || data.toast_id===lastRaasClientAudioToastId) return;
  const audio=data.audio||{};
  const type=String(data.last_callout_type||'').toLowerCase();
  const hostState=String(audio.state||'').toUpperCase();
  const clientRequired=!!data.client_audio_required || hostState==='DISPLAY_ONLY' || hostState==='FAILED';
  if(!clientRequired || type==='test') return;
  lastRaasClientAudioToastId=data.toast_id;
  const text=String(data.last_callout||data.display||'').trim();
  const keys=raasClientSegmentKeys(data);
  const vp=audio.voice_pack_status||{};
  if(!keys.length || !vp.available){raasSpeakBrowser(text); return;}
  try{
    for(const key of keys){
      const file=RAAS_CLIENT_CLIPS[key];
      if(!file) throw new Error(`missing ${key}`);
      await raasPlayClipFile(file);
    }
  }catch(_){
    raasSpeakBrowser(text);
  }
}

function renderRaas(data, options={}){
  if(!data) return;
  const state = data.state || 'STANDBY';
  let display = data.display || 'RAAS-STBY';
  const liveDisplay = formatRaasGlobalText(data);
  if(liveDisplay) display = liveDisplay;
  const audioOk = !!(data.audio?.voice_pack_status?.available);
  if(data.ok === false && /^RAAS-FAULT$/i.test(display) && audioOk) display = 'RAAS-CHECK';
  const unit = raasUnitFromData(data);
  renderRaasUnitButtons(unit);
  if($('raasPanelState')) $('raasPanelState').textContent = state;
  if($('raasDisplayText')) $('raasDisplayText').textContent = display;
  if($('raasStatusLabel')) $('raasStatusLabel').textContent = data.enabled === false ? 'OFF' : (data.ok === false ? 'CHECK' : (data.running ? 'ACTIVE' : 'STANDBY'));
  if($('raasStatusLamp')) $('raasStatusLamp').className = data.ok === false ? 'off' : (data.enabled === false ? 'off' : 'active');
  if($('raasToggle')) $('raasToggle').textContent = data.enabled === false ? 'ENABLE' : 'DISABLE';

  const rwy = data.runway || {};
  if($('raasSource')) $('raasSource').textContent = data.telemetry_source || data.source_priority || 'FSUIPC FIRST';
  if($('raasRunway')) $('raasRunway').textContent = data.active_runway || rwy.runway || '----';
  if($('raasAlong')) $('raasAlong').textContent = formatRaasDistance(rwy.along_ft_live ?? rwy.along_ft, data);
  if($('raasCross')) $('raasCross').textContent = formatRaasDistance(rwy.cross_ft_live ?? rwy.cross_ft, data);
  if($('raasRemaining')) $('raasRemaining').textContent = formatRaasDistance(rwy.remaining_ft, data);
  if($('raasMessage')){
    const debug = rwy.runway ? `End ${rwy.selected_runway_end||rwy.runway} · Hdg ${rwy.aircraft_heading_deg ?? '--'}° · Track ${rwy.aircraft_track_deg ?? '--'}° ${rwy.track_valid===false?'IGNORED':''} · Ref ${rwy.effective_direction_deg ?? '--'}° ${rwy.effective_direction_source||''} · RWY ${rwy.runway_heading_deg ?? '--'}° · Δ ${rwy.heading_delta_deg ?? '--'}° · Along ${formatRaasDistance(rwy.along_ft_live ?? rwy.along_ft, data)} · Cross ${formatRaasDistance(rwy.cross_ft_live ?? rwy.cross_ft, data)} · Edge ${formatRaasDistance(rwy.edge_distance_ft, data)} · Rem ${formatRaasDistance(rwy.remaining_ft, data)} · Inside ${rwy.inside?'TRUE':'FALSE'} · Approaching ${rwy.approaching?'TRUE':'FALSE'} · Phase ${(rwy.phase||'--').toString().toUpperCase()} · Eval ${rwy.eval_hz||data.eval_hz||'--'}Hz · UI ${rwy.ui_hz||data.ui_hz||'--'}Hz · End lock ${rwy.end_lock_active?'ON':'OFF'}${rwy.end_lock_reason?' '+rwy.end_lock_reason:''}` : '';
    $('raasMessage').innerHTML = `<b>${escapeHtml(display)}</b><p>${escapeHtml(data.message || data.last_callout || '')}</p>${debug?`<small class="raas-debug-line">${escapeHtml(debug)}</small>`:''}`;
  }

  const audio = data.audio || {};
  const vp = audio.voice_pack_status || {};
  if($('raasAudioState')) $('raasAudioState').textContent = 'VOICE PACK';
  if($('raasVoicePack')) $('raasVoicePack').textContent = vp.available ? 'Voice pack loaded' : 'Voice pack not loaded';
  if($('raasVoicePath') && !$('raasVoicePath').matches(':focus')) $('raasVoicePath').value = data?.audio?.configured_voice_path || vp.path || '';
  showRaasCenterToast(data, !!options.forceToast);
  tryRaasClientAudio(data);
}

async function loadRaas(){
  try{
    const res = await fetchWithTimeout('/api/raas/status', {}, 3500);
    const data = await safeJsonResponse(res);
    renderRaas(data);
  }catch(error){
    if($('raasPanelState')) $('raasPanelState').textContent = 'OFFLINE';
    if($('raasDisplayText')) $('raasDisplayText').textContent = 'RAAS-CHECK';
    if($('raasMessage')) $('raasMessage').innerHTML = `<b>RAAS OFFLINE</b><p>${escapeHtml(friendlyError(error.message))}</p>`;
  }
}
function startRaas(){
  startGlobalRaasListener();
  stopRaas();
  loadRaas();
  raasTimer = setInterval(()=>{ if(activePage==='raas') loadRaas(); }, 500);
}
async function testRaas(){
  try{
    const res = await fetchWithTimeout('/api/raas/test', {method:'POST'}, 3500);
    const data = await safeJsonResponse(res);
    renderRaas(data, {forceToast:true});
  }catch(error){showToast('RUNWAY AWARENESS','TEST FAILED',friendlyError(error.message),'critical')}
}
async function saveRaasVoicePath(){
  const path = $('raasVoicePath')?.value || '';
  try{
    const res = await fetchWithTimeout('/api/raas/voice-path',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})},3500);
    const data = await safeJsonResponse(res);
    renderRaas(data);
    notifyOps({source:'RUNWAY AWARENESS',title:'VOICE FOLDER SAVED',message:path || 'Default voice-pack search paths restored.',priority:'advisory'});
  }catch(error){alert(`Voice folder update failed: ${friendlyError(error.message)}`)}
}

async function saveRaasUnit(unit){
  const selected = String(unit||'ft').toLowerCase().startsWith('m') ? 'm' : 'ft';
  renderRaasUnitButtons(selected);
  try{
    const res = await fetchWithTimeout('/api/raas/unit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({unit:selected})},3500);
    const data = await safeJsonResponse(res);
    renderRaas(data);
  }catch(error){showToast('RUNWAY AWARENESS','UNIT CHANGE FAILED',friendlyError(error.message),'critical')}
}

async function toggleRaas(){
  try{
    const enabled = $('raasToggle')?.textContent === 'ENABLE';
    const res = await fetchWithTimeout('/api/raas/enabled', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled})}, 3500);
    renderRaas(await safeJsonResponse(res));
  }catch(error){showToast('RUNWAY AWARENESS','TOGGLE FAILED',friendlyError(error.message),'critical')}
}

function toggleCameraBridgeFloatPanel(){const panel=$('cameraBridgeFloatPanel'),button=$('cameraBridgeFloatToggle');if(!panel)return;const collapsed=panel.classList.toggle('is-collapsed');if(button){button.setAttribute('aria-expanded',collapsed?'false':'true');button.textContent=collapsed?'SHOW CAMERA PANEL':'HIDE CAMERA PANEL'}try{localStorage.setItem('opsroom_camera_panel_collapsed',collapsed?'1':'0')}catch{}}
function restoreCameraBridgeFloatPanel(){const panel=$('cameraBridgeFloatPanel'),button=$('cameraBridgeFloatToggle');if(!panel)return;let collapsed=false;try{collapsed=localStorage.getItem('opsroom_camera_panel_collapsed')==='1'}catch{}panel.classList.toggle('is-collapsed',collapsed);if(button){button.setAttribute('aria-expanded',collapsed?'false':'true');button.textContent=collapsed?'SHOW CAMERA PANEL':'HIDE CAMERA PANEL'}}

function setup(){
  restoreObsPrefs();
  $('bugReportButton')?.addEventListener('click',openBugReport);
  $('bugReportClose')?.addEventListener('click',closeBugReport);
  $('bugReportOverlay')?.addEventListener('click',closeBugReport);
  $('bugReportCopy')?.addEventListener('click',copyBugReportSummary);
  $('bugReportDownload')?.addEventListener('click',downloadBugReportZip);
  $('bugReportSend')?.addEventListener('click',sendBugReport);
  document.addEventListener('keydown',event=>{if(event.key==='Escape' && !$('bugReportModal')?.hidden) closeBugReport();});
  document.querySelectorAll('[data-page]').forEach(button => button.addEventListener('click',()=>showPage(button.dataset.page)));
  $('moduleButton').addEventListener('click',toggleClassicRail);
  $('railScrim').addEventListener('click',()=>{$('rail').classList.remove('open');$('railScrim').classList.remove('open')});
  $('probeMsfs').addEventListener('click',()=>loadSummary(true));
  $('refreshFlight').addEventListener('click',()=>loadFlight(true));
  $('briefingRefresh').addEventListener('click',()=>loadFlight(true));
  $('deviceScale').addEventListener('change',event=>applyDeviceScale(event.target.value));
  $('terminalHomeStyle')?.addEventListener('change',event=>setTerminalHomeStyle(event.target.value));
  $('perfAircraft')?.addEventListener('change',updatePerformanceFlaps);
  $('perfMode')?.addEventListener('change',()=>{updatePerformanceFlaps();fillPerformanceFromSimbrief();renderPerformanceTlr();});
  $('perfCalculate')?.addEventListener('click',calculatePerformance);
  $('perfFromSimbrief')?.addEventListener('click',()=>{fillPerformanceFromSimbrief();calculatePerformance()});
  $('openFidsLink')?.addEventListener('click',event=>{event.preventDefault(); const w=window.open('/vatsim-fids','opsroom-fids'); if(w) w.focus();});
  $('efbClassicMode')?.addEventListener('click',()=>{setTerminalHomeStyle('classic');showPage('home')});
  $('efbFullscreen')?.addEventListener('click',toggleFullscreen);
  $('efbModuleFullscreen')?.addEventListener('click',toggleFullscreen);
  $('terminalFullscreen')?.addEventListener('click',toggleFullscreen);
  $('efbRefreshOfp')?.addEventListener('click',()=>loadFlight(true));
  ['obsView','obsLayout','obsPosition','obsTransparent','obsLabels','obsShowLogo','obsWidth','obsHeight','obsAccent','obsOpacity','obsScale','obsLogoPosition','obsLogoSize'].forEach(id=>{const el=$(id);el?.addEventListener('change',updateObsTools);el?.addEventListener('input',updateObsTools)});
  document.querySelectorAll('#obsFieldSet input').forEach(el=>el.addEventListener('change',updateObsTools));
  $('obsCopyUrl')?.addEventListener('click',copyObsUrl);$('obsRefreshPreview')?.addEventListener('click',updateObsTools);

  $('obsBrandingMode')?.addEventListener('change',()=>{obsBrandingPreferencePresent=true;loadObsBranding();updateObsTools()});
  $('obsLogoFile')?.addEventListener('change',event=>uploadObsLogo(event.target.files?.[0]));$('obsRemoveLogo')?.addEventListener('click',removeObsLogo);
  $('terminalToggleIp')?.addEventListener('click',()=>{terminalIpVisible=!terminalIpVisible;renderTerminalAddresses()});
  $('checkUpdates')?.addEventListener('click',()=>checkUpdates(true,false));
  $('clearLocalLogs')?.addEventListener('click',()=>clearLocalStorage(false));
  $('clearLocalCache')?.addEventListener('click',()=>clearLocalStorage(true));
  $('refreshStartupConsole')?.addEventListener('click',loadStartupConsole);
  restoreCameraBridgeFloatPanel();
  $('cameraBridgeFloatToggle')?.addEventListener('click',toggleCameraBridgeFloatPanel);
  $('cameraBridgeStart')?.addEventListener('click',startCameraBridge);
  $('cameraBridgeRelease')?.addEventListener('click',releaseCameraBridge);
  $('cameraBridgeResetView')?.addEventListener('click',resetCameraBridgeView);
  $('cameraBridgeRecenter')?.addEventListener('click',recenterCameraBridge);
  $('cameraBridgeRefresh')?.addEventListener('click',loadCameraBridgeStatus);
  $('cameraBridgeLog')?.addEventListener('click',showCameraBridgeLog);
  $('raasTest')?.addEventListener('click',testRaas);
  $('raasPanelTest')?.addEventListener('click',testRaas);
  $('raasRefresh')?.addEventListener('click',loadRaas);
  $('raasToggle')?.addEventListener('click',toggleRaas);
  $('raasVoicePathSave')?.addEventListener('click',saveRaasVoicePath);
  document.querySelectorAll('[data-raas-unit]').forEach(button=>button.addEventListener('click',()=>saveRaasUnit(button.dataset.raasUnit || 'ft')));
  bindCameraControls();
  $('dispatchSearch').addEventListener('click',()=>searchDispatch(true));
  $('dispatchUseMsfs').addEventListener('click',()=>{dispatchSource='msfs';const code=dispatchContextData?.msfs?.airport?.ident||'';$('dispatchOrigin').value=code;$('dispatchOriginState').textContent=code?`MSFS ${code}`:'MSFS UNAVAILABLE'});
  $('dispatchUseSimbrief').addEventListener('click',()=>{dispatchSource='simbrief';const code=dispatchContextData?.simbrief?.origin?.icao||'';$('dispatchOrigin').value=code;$('dispatchOriginState').textContent=code?`SIMBRIEF ${code}`:'SIMBRIEF UNAVAILABLE'});
  $('dispatchOrigin').addEventListener('input',event=>{event.target.value=event.target.value.toUpperCase().replace(/[^A-Z0-9]/g,'').slice(0,4);dispatchSource='manual'});
  $('watchRefresh').addEventListener('click',()=>startFlightWatchStream());
  $('networkRefresh').addEventListener('click',()=>loadNetwork(true));
  $('networkFilterButton').addEventListener('click',()=>loadNetwork(false));
  $('networkQuery').addEventListener('keydown',event=>{if(event.key==='Enter')loadNetwork(false)});
  document.querySelectorAll('.radio-tune').forEach(button=>button.addEventListener('click',()=>{const radio=Number(button.dataset.radio);tuneRadio(radio,$(`com${radio}Frequency`).value,'standby')}));
  document.querySelectorAll('.radio-swap').forEach(button=>button.addEventListener('click',()=>swapRadioControl(Number(button.dataset.radio))));
  $('nextToCom1').addEventListener('click',()=>{if(nextSuggestedFrequency){$('com1Frequency').value=nextSuggestedFrequency;tuneRadio(1,nextSuggestedFrequency,'standby')}});
  $('nextToCom2').addEventListener('click',()=>{if(nextSuggestedFrequency){$('com2Frequency').value=nextSuggestedFrequency;tuneRadio(2,nextSuggestedFrequency,'standby')}});
  document.querySelector('.network-layout').addEventListener('click',event=>{const sensitive=event.target.closest('[data-sensitive]');if(sensitive){toggleSensitiveField(sensitive.dataset.sensitive);return}const button=event.target.closest('[data-controller-frequency]');if(button)tuneRadio(Number(button.dataset.radio),button.dataset.controllerFrequency,'standby')});
  $('commsSend').addEventListener('click',sendCommsMessage);document.querySelectorAll('[data-comms-send-mode]').forEach(button=>button.addEventListener('click',()=>setCommsSendMode(button.dataset.commsSendMode||'private')));
  $('commsModeCOn').addEventListener('click',()=>sendVpilotAction('mode_c',true));
  $('commsModeCOff').addEventListener('click',()=>sendVpilotAction('mode_c',false));
  $('commsIdent').addEventListener('click',()=>sendVpilotAction('ident'));
  $('commsMessages').addEventListener('click',event=>{const button=event.target.closest('[data-reply-to]');if(button){$('commsRecipient').value=button.dataset.replyTo;$('commsMessage').focus()}});
  $('opsToastOpen').addEventListener('click',()=>{
    $('opsToast').hidden=true;
    if(notificationToastAction==='update-now'&&pendingUpdateManifest){const manifest=pendingUpdateManifest;notificationToastAction='';pendingUpdateManifest=null;startUpdate(manifest);return;}
    notificationToastAction='';showPage(notificationToastPage||'status');
  });
  $('opsToastClose').addEventListener('click',()=>{notificationToastAction='';$('opsToast').hidden=true});['efbKeepAwake','efbModuleKeepAwake'].forEach(id=>$(id)?.addEventListener('click',toggleKeepAwake));updateKeepAwakeUi();['notificationButton','efbNotificationButton','efbModuleNotificationButton'].forEach(bindNotificationButton);$('notificationClose')?.addEventListener('click',closeNotifications);document.addEventListener('click',event=>{const drawer=$('notificationDrawer');if(!drawer||drawer.hidden)return;if(event.target.closest('#notificationDrawer,#notificationButton,#efbNotificationButton,#efbModuleNotificationButton'))return;drawer.hidden=true},{capture:true});$('notificationClear')?.addEventListener('click',markNotificationsRead);$('notificationHistory')?.addEventListener('click',event=>{const b=event.target.closest('[data-notification-page]');if(b){$('notificationDrawer').hidden=true;markNotificationsRead();showPage(b.dataset.notificationPage)}});
  document.querySelectorAll('[data-map-mode]').forEach(button=>button.addEventListener('click',()=>setMapMode(button.dataset.mapMode,true)));
  $('mapResetView').addEventListener('click',resetMapView);$('mapNorthUp')?.addEventListener('click',resetMapNorthUp);$('mapCenterAircraft')?.addEventListener('click',mapCenterOnAircraft);
  ['mapLayerTraffic','mapLayerControllers','mapLayerCoverage','mapLayerAirports','mapLayerRunways','mapLayerSurface','mapLayerTaxiLabels','mapLayerStandLabels','mapLayerNavaids','mapLayerWaypoints','mapLayerAirways','mapLayerBoundaries'].forEach(id=>$(id)?.addEventListener('change',()=>{document.querySelectorAll('[data-map-preset]').forEach(b=>b.classList.remove('active'));if(id==='mapLayerSurface'||id==='mapLayerRunways'||id==='mapLayerTaxiLabels'||id==='mapLayerStandLabels'){olRunwaySurfaceLayer?.changed();olTaxiSurfaceLayer?.changed();olSurfaceLabelLayer?.changed();if(!mapLayerChecked('mapLayerSurface',true)&&!mapLayerChecked('mapLayerRunways',true)){clearAirportSurface('SURFACE LAYER OFF');}}if(mapData)renderMap(mapData);scheduleAviationRefresh(80)}));
  $('mapLayerNotams')?.addEventListener('change',()=>{document.querySelectorAll('[data-map-preset]').forEach(b=>b.classList.remove('active'));loadNotamLayer();if(mapData)renderMap(mapData);syncMapNotamToggle();});
  $('mapNotamToggle')?.addEventListener('click',()=>{const box=$('mapLayerNotams');if(box){box.checked=!box.checked;box.dispatchEvent(new Event('change'));}syncMapNotamToggle();});
  syncMapNotamToggle();
  document.querySelectorAll('[data-notam-filter]').forEach(button=>button.addEventListener('click',()=>applyMapNotamFilter(button.dataset.notamFilter||'all')));
  document.querySelectorAll('[data-map-preset]').forEach(button=>button.addEventListener('click',()=>applyMapPreset(button.dataset.mapPreset||'clean')));
  $('mapControllerList').addEventListener('click',event=>{const button=event.target.closest('[data-map-controller]');if(!button||!mapData||!olMap)return;const item=(mapData.controllers||[]).find(x=>x.callsign===button.dataset.mapController);if(item?.mapped&&Number.isFinite(Number(item.lat))&&Number.isFinite(Number(item.lon))){olMap.getView().animate({center:ol.proj.fromLonLat([Number(item.lon),Number(item.lat)]),zoom:Math.max(6,olMap.getView().getZoom()||6),duration:250});$('mapSelected').textContent=`${item.callsign} ${item.frequency} · ${item.facility_label} · ${item.position_source||''}`}else if(item){$('mapSelected').textContent=`${item.callsign} IS ONLINE · POSITION COULD NOT YET BE RESOLVED`}});
  $('mapRefresh').addEventListener('click',()=>loadMap(true));
  $('hoppiePing').addEventListener('click',()=>hoppieCommand('/api/hoppie/ping'));
  $('hoppiePoll').addEventListener('click',()=>hoppieCommand('/api/hoppie/poll'));
  $('hoppieLogLink')?.addEventListener('click',()=>{const url=$('hoppieLogLink').dataset.href;if(url)window.open(url,'_blank','noopener,noreferrer')});
  $('hoppieStop').addEventListener('click',()=>hoppieCommand('/api/hoppie/stop'));
  $('hoppieCallsignApply').addEventListener('click',()=>hoppieCommand('/api/hoppie/callsign',{callsign:$('hoppieCallsign').value}));
  $('hoppieCallsignAuto').addEventListener('click',()=>{$('hoppieCallsign').value='';hoppieCommand('/api/hoppie/callsign',{callsign:''})});
  $('cpdlcLogon').addEventListener('click',()=>hoppieCommand('/api/hoppie/cpdlc/logon',{atc:$('cpdlcFacility').value}));initCpdlcTemplates();$('cpdlcCategory')?.addEventListener('change',renderCpdlcTemplates);$('cpdlcTemplate')?.addEventListener('change',renderCpdlcFields);$('cpdlcAutofill')?.addEventListener('click',autofillCpdlcTemplate);$('cpdlcTransfer')?.addEventListener('click',transferCpdlcToMailbox);$('cpdlcClearTemplate')?.addEventListener('click',()=>{renderCpdlcFields();$('hoppieCommandState').textContent='READY'});
  $('hoppieSend').addEventListener('click',()=>{const type=$('hoppieType').value||'cpdlc';hoppieCommand('/api/hoppie/send',{type,to:$('hoppieTo').value,message:$('hoppieMessage').value})});
  document.querySelectorAll('[data-hoppie-info]').forEach(button=>button.addEventListener('click',()=>hoppieCommand('/api/hoppie/info',{kind:button.dataset.hoppieInfo,station:$('hoppieStation').value})));
  $('hoppieMessages').addEventListener('click',event=>{const button=event.target.closest('[data-cpdlc-reply]');if(button)hoppieCommand('/api/hoppie/cpdlc/reply',{message_id:button.dataset.messageId,reply:button.dataset.cpdlcReply})});
  $('groundRefresh').addEventListener('click',()=>loadGround(true));
  $('groundDepartureStart')?.addEventListener('click',()=>groundAutomation(true,'DEPARTURE'));$('groundArrivalStart')?.addEventListener('click',()=>groundAutomation(true,'ARRIVAL'));$('groundFullTurnaroundStart')?.addEventListener('click',()=>groundAutomation(true,'FULL_TURNAROUND'));
  ['groundDepartureCatering','groundDepartureWater'].forEach(id=>$(id)?.addEventListener('change',saveGroundPreferences));
  $('groundAutoStop').addEventListener('click',()=>groundAutomation(false));
  $('groundOpenMenu').addEventListener('click',()=>groundCommand('/api/gsx/menu/open'));
  $('groundRelease').addEventListener('click',()=>groundCommand('/api/gsx/release'));
  $('groundServices').addEventListener('click',event=>{
    const button=event.target.closest('[data-gsx-service]');
    if(!button)return;
    const service=button.dataset.gsxService;
    groundCommand('/api/gsx/service',{service});
  });
  $('gsxMenu').addEventListener('click',event=>{const button=event.target.closest('[data-gsx-index]');if(button)groundCommand('/api/gsx/menu/select',{index:Number(button.dataset.gsxIndex)})});
  $('announcerRefresh').addEventListener('click',loadAnnouncements);
  $('announcerStop').addEventListener('click',stopAnnouncement);
  $('announcerPause').addEventListener('click',pauseAnnouncement);
  $('announcerMute').addEventListener('click',muteAnnouncement);$('announcerVolume')?.addEventListener('input',event=>{if($('announcerVolumeValue'))$('announcerVolumeValue').textContent=`${event.target.value}%`});$('announcerVolume')?.addEventListener('change',event=>setAnnouncementVolume(event.target.value));
  $('announcerAirlineApply').addEventListener('click',()=>saveAnnouncementAirlineOverride(false));
  $('announcerAirlineClear').addEventListener('click',()=>saveAnnouncementAirlineOverride(true));
  $('announcerAirlineOverride').addEventListener('input',event=>{event.target.value=event.target.value.toUpperCase().replace(/[^A-Z0-9]/g,'').slice(0,4)});
  $('announcerAirlineOverride').addEventListener('keydown',event=>{if(event.key==='Enter')saveAnnouncementAirlineOverride(false)});
  document.querySelectorAll('[data-announcement]').forEach(button=>button.addEventListener('click',()=>playAnnouncement(button.dataset.announcement)));document.querySelectorAll('[data-boarding-audio]').forEach(button=>button.addEventListener('click',startBoardingAudio));
  $('procedureProfile').addEventListener('change',event=>{event.target.dataset.userSelected='1';procedurePhase='';loadProcedures()});
  $('procedureFollowPhase').addEventListener('change',()=>{lastProcedureFlightPhase='';if($('procedureFollowPhase').checked&&proceduresData){procedurePhase=proceduresData.recommended_phase;lastProcedureFlightPhase=proceduresData.flight_phase||'';renderProcedures(proceduresData)}});$('procedureAutoAdvance').checked=localStorage.getItem('opsroom-procedure-auto-advance')!=='0';$('procedureAutoAdvance').addEventListener('change',()=>localStorage.setItem('opsroom-procedure-auto-advance',$('procedureAutoAdvance').checked?'1':'0'));
  $('procedurePhaseTabs').addEventListener('click',event=>{const button=event.target.closest('[data-procedure-phase]');if(button){procedurePhase=button.dataset.procedurePhase;$('procedureFollowPhase').checked=false;renderProcedures(proceduresData)}});
  $('procedureChecklist').addEventListener('change',event=>{const input=event.target.closest('[data-procedure-item]');if(input)handleProcedureItemChange(input)});
  $('procedureResetPhase').addEventListener('click',()=>resetProcedure(false));
  $('procedureResetAll').addEventListener('click',()=>resetProcedure(true));
  $('qrhProfile').addEventListener('change',event=>{event.target.dataset.userSelected='1';qrhSelectedCondition='';loadNonNormal()});
  $('qrhSearchButton').addEventListener('click',searchNonNormal);
  $('qrhSearch').addEventListener('keydown',event=>{if(event.key==='Enter')searchNonNormal()});
  $('qrhClearSearch').addEventListener('click',clearNonNormalSearch);
  $('qrhConditionList').addEventListener('click',event=>{const button=event.target.closest('[data-qrh-condition]');if(button){qrhSelectedCondition=button.dataset.qrhCondition;loadNonNormal()}});
  $('qrhSuggestions').addEventListener('click',event=>{const button=event.target.closest('[data-qrh-condition]');if(button){qrhSelectedCondition=button.dataset.qrhCondition;loadNonNormal();$('qrhChecklist').scrollIntoView({behavior:'smooth',block:'start'})}});
  $('qrhMemory').addEventListener('change',event=>{const input=event.target.closest('[data-qrh-item]');if(input)handleQrhItemChange(input)});
  $('qrhChecklist').addEventListener('change',event=>{const input=event.target.closest('[data-qrh-item]');if(input)handleQrhItemChange(input)});
  $('logbookRefresh').addEventListener('click',loadLogbook);
  $('logbookStart').addEventListener('click',()=>logbookCommand('/api/logbook/start'));
  $('logbookFinalize').addEventListener('click',()=>logbookCommand('/api/logbook/finalize'));
  $('logbookScoringRules')?.addEventListener('click',()=>window.open('/scoring-rules','_blank','noopener'));
  $('landingToastClose')?.addEventListener('click',()=>{if($('landingToast'))$('landingToast').hidden=true});
  $('logbookDiscard').addEventListener('click',()=>{const btn=$('logbookDiscard');if(btn.dataset.armed==='1'){delete btn.dataset.armed;btn.textContent='Discard active';btn.classList.remove('danger-control');logbookCommand('/api/logbook/active','DELETE')}else{btn.dataset.armed='1';btn.textContent='CONFIRM DISCARD?';btn.classList.add('danger-control');setTimeout(()=>{if(btn.dataset.armed==='1'){delete btn.dataset.armed;btn.textContent='Discard active';btn.classList.remove('danger-control')}},4000)}});
  $('logbookSearch').addEventListener('click',loadLogbook);
  $('logbookQuery').addEventListener('keydown',event=>{if(event.key==='Enter')loadLogbook()});
  $('logbookEntries').addEventListener('click',event=>{const button=event.target.closest('[data-logbook-entry]');if(!button)return;selectedLogbookId=button.dataset.logbookEntry;renderLogbook(logbookData)});
  $('logbookSave').addEventListener('click',saveLogbookEntry);
  $('logbookDelete').addEventListener('click',deleteLogbookEntry);
  $('logbookBlackBox')?.addEventListener('click',event=>{const id=event.currentTarget.dataset.recordingId;if(!id)return;selectedBlackBoxId=id;blackBoxSamples=[];showPage('blackbox');selectBlackBox(id)});
  $('blackBoxRefresh')?.addEventListener('click',()=>{loadBlackBoxPreferences();loadBlackBox(true)});
  $('blackBoxInstallAdapters')?.addEventListener('click',installBlackBoxAdapters);
  $('blackBoxReduceFsuipcLog')?.addEventListener('click',reduceBlackBoxFsuipcLog);
  ['blackBoxEnabled','blackBoxAutoRecord','blackBoxMaxHz'].forEach(id=>$(id)?.addEventListener('change',saveBlackBoxPreferences));
  $('blackBoxRecordings')?.addEventListener('click',event=>{const button=event.target.closest('[data-blackbox-id]');if(button)selectBlackBox(button.dataset.blackboxId)});
  document.querySelectorAll('[data-blackbox-view]').forEach(button=>button.addEventListener('click',()=>{blackBoxView=button.dataset.blackboxView||'flight';document.querySelectorAll('[data-blackbox-view]').forEach(item=>item.classList.toggle('active',item===button));drawBlackBox()}));
  $('blackBoxEventsView')?.addEventListener('click',event=>{const row=event.target.closest('[data-bb-event-time]');if(!row)return;blackBoxPlayback.cursor=Number(row.dataset.bbEventTime||0);blackBoxPlayback.lastMono=0;if($('blackBoxTimeline'))$('blackBoxTimeline').value=String(blackBoxPlayback.cursor);drawBlackBox()});
  $('blackBoxPlay')?.addEventListener('click',async()=>{if(!blackBoxSamples.length)return;const replay=blackBoxData?.replay||{};if(replay.active){try{await safeJsonResponse(await fetch('/api/blackbox/replay/control',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({playing:!replay.playing})}));await loadBlackBox()}catch(e){showToast('BLACK BOX','COULD NOT CONTROL THE REPLAY',friendlyError(e.message),'critical')}return}blackBoxPlayback.playing=!blackBoxPlayback.playing;blackBoxPlayback.lastMono=0;$('blackBoxPlay').textContent=blackBoxPlayback.playing?'PAUSE REVIEW':'PLAY REVIEW';if(blackBoxPlayback.playing)blackBoxStartAnimation();else blackBoxStopAnimation();drawBlackBox()});
  $('blackBoxStop')?.addEventListener('click',()=>{blackBoxPlayback.playing=false;blackBoxStopAnimation();blackBoxPlayback.cursor=0;$('blackBoxPlay').textContent='PLAY REVIEW';if($('blackBoxTimeline'))$('blackBoxTimeline').value='0';drawBlackBox()});
  $('blackBoxTimeline')?.addEventListener('input',event=>{blackBoxPlayback.cursor=Number(event.target.value||0);blackBoxPlayback.lastMono=0;drawBlackBox();if(blackBoxData?.replay?.active){if(blackBoxSeekTimer)clearTimeout(blackBoxSeekTimer);blackBoxSeekTimer=setTimeout(()=>fetch('/api/blackbox/replay/control',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({cursor:blackBoxPlayback.cursor})}).then(()=>loadBlackBox(true)).catch(()=>{}),180)}});
  $('blackBoxSpeed')?.addEventListener('change',event=>{blackBoxPlayback.speed=Math.max(.1,Number(event.target.value)||1);if(blackBoxData?.replay?.active)fetch('/api/blackbox/replay/control',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({speed:blackBoxPlayback.speed})}).catch(()=>{})});
  $('blackBoxLoop')?.addEventListener('change',event=>{blackBoxPlayback.loop=!!event.target.checked;if(blackBoxData?.replay?.active)fetch('/api/blackbox/replay/control',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({loop:blackBoxPlayback.loop})}).catch(()=>{})});
  $('blackBoxSimReplay')?.addEventListener('click',startInSimReplay);
  $('blackBoxSimStop')?.addEventListener('click',async()=>{try{await safeJsonResponse(await fetch('/api/blackbox/replay/stop',{method:'POST'}));await loadBlackBox()}catch(e){showToast('BLACK BOX','COULD NOT STOP THE REPLAY',friendlyError(e.message),'critical')}});
  document.addEventListener('click',async(event)=>{const btn=event.target.closest('#blackBoxStopFdr');if(!btn)return;try{await safeJsonResponse(await fetch('/api/blackbox/stop',{method:'POST'}));await loadBlackBox(true);showToast('BLACK BOX','RECORDING STOPPED','Flight data recording stopped by user.','standard')}catch(e){showToast('BLACK BOX','COULD NOT STOP RECORDING',friendlyError(e.message),'critical')}});
  $('financeSaveSetup')?.addEventListener('click',()=>saveFinanceSetup(false));
  $('financeResetCareer')?.addEventListener('click',async()=>{if(await uiConfirm('Reset the OPS ROOM finance career and balances?', 'RESET'))saveFinanceSetup(true)});
  $('autoFetchOfpToggle')?.addEventListener('change',saveAutoFetchOfpSetting);
  $('financeCareerToggle')?.addEventListener('change',saveFinanceCareerSetting);
  $('airlineBrandingToggle')?.addEventListener('change',saveAirlineBrandingSetting);
  $('airlineIcaoApply')?.addEventListener('click',saveAirlineBrandingSetting);
  $('airlineIcaoOverride')?.addEventListener('keydown',event=>{if(event.key==='Enter')saveAirlineBrandingSetting()});
  $('airlineLogoFile')?.addEventListener('change',event=>uploadAirlineLogo(event.target.files?.[0]));
  $('airlineLogoRemove')?.addEventListener('click',removeAirlineLogo);
}


document.addEventListener('fullscreenchange',()=>{
  if($('efbFullscreen')) $('efbFullscreen').textContent = document.fullscreenElement ? 'EXIT FULLSCREEN' : 'FULLSCREEN';
  if($('terminalFullscreen')) $('terminalFullscreen').textContent = document.fullscreenElement ? 'EXIT FULLSCREEN' : 'FULLSCREEN';
  if($('efbModuleFullscreen')) $('efbModuleFullscreen').textContent = document.fullscreenElement ? 'EXIT FULLSCREEN' : 'FULLSCREEN';
});

function bg(fn){try{const p=fn();if(p&&p.catch)p.catch(()=>{})}catch(_){}}
// v0.25.60: global runtime-error trap. Any synchronous throw anywhere in a
// render path is caught by _safeRender, logged with kind+stack to console,
// shipped to /api/frontend/log via sendBeacon, and surfaces a clickable red
// badge in the bottom-left of the page that copies the full trace. This is
// what was missing when the user kept seeing
// a generic JS error in the Status Board with no way to know what was
// actually throwing.
function _captureError(kind, err){
  try{
    const e = err || {};
    const message = String(e && (e.message || e) || 'unknown error').slice(0, 400);
    const stack = String(e && e.stack || '').slice(0, 2400);
    try{ console.error('[OPS ROOM][' + kind + ']', e); }catch(_){}
    if(typeof window === 'undefined') return;
    if(!window.__opsroomErrors__) window.__opsroomErrors__ = [];
    window.__opsroomErrors__.push({kind:kind, message:message, stack:stack, time:Date.now()});
    if(window.__opsroomErrors__.length > 8) window.__opsroomErrors__.shift();
    try{ document.body && (document.body.dataset.opsroomLastError = JSON.stringify({kind:kind,message:message,stack:stack,ts:Date.now()})); }catch(_){}
    try{
      let badge = document.getElementById('__opsroomErrBadge');
      if(badge){ try{ badge.remove(); }catch(_){} }
      // v0.25.60: bottom-left error badge rendering removed per user request.
      // Errors are still logged to console and stored in window.__opsroomErrors__
      // for developer diagnostics via the browser console.
    }catch(_){}
    try{
      if(typeof navigator !== 'undefined' && navigator.sendBeacon){
        navigator.sendBeacon('/api/frontend/log', new Blob([JSON.stringify({kind:kind,message:message,stack:stack,ts:Date.now()})], {type:'application/json'}));
      }
    }catch(_){}
  }catch(_){}
}
function _safeRender(_label, fn){
  try{ return fn(); }
  catch(err){ _captureError(_label, err); }
}
function _isOpsroomError(e){
  // Only capture errors that originate from OPS ROOM's own code so benign
  // favicon / source-map / CDN noise does not waste the 8-slot ring buffer.
  try{
    if(!e) return true;
    const file = String(e.filename || (e.error && e.error.fileName) || '');
    if(file && !file.includes('/static/opsroom.js') && !file.includes('opsroom')) return false;
    return true;
  }catch(_){ return true; }
}
// v0.25.60: unhandledrejection and window.error listeners disabled —
// bottom-left error badge removed from user-facing production build.
// Errors are still captured via _captureError for console logging.
// if(typeof window !== 'undefined'){
//   try{ window.addEventListener('error', e => { if(_isOpsroomError(e)) _captureError('window.error', (e && (e.error || e.message)) || e); }); }catch(_){}
//   try{ window.addEventListener('unhandledrejection', e => { if(_isOpsroomError(e && e.reason)) _captureError('unhandled.rejection', (e && e.reason) || e); }); }catch(_){}
// }
function preloadModulesOnce(){
  bg(()=>loadSummary(false));
  bg(()=>loadFlightWatch(false));
  bg(()=>loadGroundControl(false));
  bg(()=>loadAnnouncements());
  bg(()=>loadLogbook());
  if(financeCareerEnabled()){bg(()=>loadFinances());bg(()=>loadFinanceEstimate());}
  bg(()=>loadNetwork(false));
  bg(()=>loadComms(false));
  bg(()=>loadRaas());
}
function startBackgroundModuleRefresh(){
  preloadModulesOnce();
  setInterval(preloadModulesOnce, 15000);
}

async function boot(){
  applyAirlineTheme();
  applyDeviceScale(localStorage.getItem('opsroom-device-scale') || 'auto');if($('hoppieType'))$('hoppieType').value='telex';setTerminalHomeStyle(terminalHomeStyle());setRailCollapsed(localStorage.getItem(RAIL_COLLAPSED_KEY)==='1');notificationItems=notificationStore();notificationUnread=notificationItems.filter(item=>!item.read).length;updateClock(); setInterval(updateClock,1000); setup();setCommsSendMode('private');updateNotificationUi();requestOpsWakeLock();pollNotifications();notificationTimer=setInterval(pollNotifications,2500);startGlobalRaasListener();startLandingMonitor();
  try{await loadSettings();}catch(error){console.error(error)}
  initPrinterSettings();
  initPrinterPreviewModal();
  if(settings?.updates?.check_on_startup!==false) setTimeout(()=>checkUpdates(false,true),2500);
  await Promise.all([loadSummary(false),loadServerInfo(),loadDispatchContext()]);
  const requestedStyle = urlRequestedHomeStyle();
  if(requestedStyle) setTerminalHomeStyle(requestedStyle);
  const hash = (location.hash || '').slice(1);
  let initialRaw = hash || 'home';
  const initial = initialRaw === 'traffic' ? 'fids' : initialRaw === 'comms' ? 'network' : initialRaw;
  showPage(initial);
  hydrateMasterOfpFromSummary(summary, 'boot-summary');
  if(hasSimbriefConfigured() && settings?.integrations?.simbrief_auto_load !== false){
    // Always render cached/master OFP first, then run the Status Board master fetch
    // in the background. Do not require hidden user-id fields in public settings;
    // the backend owns the real SimBrief identity.
    renderActiveFlight(flightPlan||simbriefStatusPlan(summary)||null);
    renderBriefing(flightPlan||simbriefStatusPlan(summary)||null);
    setTimeout(()=>autoFetchMasterOFP('browser-refresh'), 50);
  }
  else {renderActiveFlight(flightPlan||null); renderBriefing(flightPlan||null);}
  startBackgroundModuleRefresh();
  setInterval(()=>loadSummary(false),30000);
  setInterval(loadServerInfo,60000);
  setInterval(()=>{if(activePage==='network')loadNetwork(false)},5000);
  startVpilotStream();
  if('serviceWorker' in navigator){
    navigator.serviceWorker.getRegistrations?.().then(regs=>regs.forEach(reg=>reg.unregister())).catch(()=>{});
  }
}
boot();

// -- Printer / Thermal POS Compatibility (v0.25.16) --------------------------
async function loadPrinterStatus() {
  const box = $('printerBox');
  if (!box) return;
  try {
    const status = await safeJsonResponse(await fetch('/api/printer/status', {cache:'no-store'}));
    const printers = status.printers || [];
    const sel = $('printerSelect');
    if (sel) {
      const currentVal = sel.value;
      sel.innerHTML = '<option value="">No printer selected</option>' +
        printers.map(p => `<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)} (${escapeHtml(p.port || '')})</option>`).join('');
      if (currentVal) sel.value = currentVal;
    }
    const enabled = settings?.printing?.enabled || false;
    const cpdlcAuto = settings?.printing?.cpdlc_auto_print !== false;
    const printerName = settings?.printing?.printer_name || '';
    if ($('printerEnabled')) $('printerEnabled').checked = enabled;
    if ($('printerCpdlcAuto')) $('printerCpdlcAuto').checked = cpdlcAuto;
    if ($('printerSelect')) $('printerSelect').value = printerName;
    const count = printers.length;
    $('printerStatus').textContent = count > 0 ? `${count} printer(s) detected` : 'No printers detected';
    $('printerStatus').style.color = count > 0 ? 'var(--green, #74ff7a)' : 'var(--muted, #aaa98d)';
  } catch (e) {
    $('printerStatus').textContent = 'Printer check unavailable';
  }
}
async function savePrinterSettings() {
  const payload = {
    printing: {
      enabled: !!($('printerEnabled')?.checked),
      printer_name: $('printerSelect')?.value || '',
      cpdlc_auto_print: !!($('printerCpdlcAuto')?.checked),
      network_auto_print: false,
      paper_width_mm: 80,
    }
  };
  try {
    const res = await fetch('/api/settings', {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
    const data = await safeJsonResponse(res);
    settings = data.settings || settings;
    $('printerResult').textContent = 'SAVED';
    $('printerResult').className = 'ok';
  } catch (e) {
    $('printerResult').textContent = 'SAVE FAILED';
    $('printerResult').className = 'err';
  }
  setTimeout(() => { if ($('printerResult')) $('printerResult').textContent = ''; }, 2000);
}
async function testPrinter() {
  const name = $('printerSelect')?.value;
  if (!name) { $('printerResult').textContent = 'Select a printer first'; $('printerResult').className = 'err'; return; }
  try {
    const res = await fetch('/api/printer/test', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({printer_name: name})});
    const data = await safeJsonResponse(res);
    $('printerResult').textContent = data.ok ? 'TEST PRINT SENT' : 'TEST FAILED';
    $('printerResult').className = data.ok ? 'ok' : 'err';
  } catch (e) {
    $('printerResult').textContent = 'TEST FAILED';
    $('printerResult').className = 'err';
  }
  setTimeout(() => { if ($('printerResult')) $('printerResult').textContent = ''; }, 3000);
}
// Wire printer events
document.addEventListener('change', function(e) {
  if (e.target.id === 'printerSelect' || e.target.id === 'printerEnabled' || e.target.id === 'printerCpdlcAuto') {
    savePrinterSettings();
  }
});
document.addEventListener('click', function(e) {
  if (e.target.id === 'printerTestBtn') testPrinter();
  if (e.target.id === 'printerRefreshBtn') loadPrinterStatus();
});

// -- PDF.js Canvas Chart Renderer (v0.25.16) ---------------------------------
let cfPdfRenderer = null;
async function cfRenderPdfCanvas(proxyUrl, container, chartId, chartName, viewUrl, _cfPdfRetries) {
  // v0.25.60: retry guard for zero-width container (max 10 frames)
  _cfPdfRetries = _cfPdfRetries || 0;
  if (!window.pdfjsLib) {
    container.innerHTML = `<div class="cf-empty">PDF RENDERER UNAVAILABLE<br><small>PDF.js library did not load</small></div>`;
    return;
  }
  // v0.25.60: retry guard for zero-width container (max 30 frames, ~500ms).
  // Also check parent preview — if the whole ChartFox panel is hidden,
  // don't waste frames retrying.
  var _pw = 0;
  var _previewEl = document.getElementById('cfPreview');
  if (_previewEl) { _pw = _previewEl.offsetWidth || _previewEl.clientWidth || 0; }
  if ((container.offsetWidth || container.clientWidth || 0) < 10) {
    if (_cfPdfRetries >= 30 || (_cfPdfRetries >= 6 && _pw < 10)) {
      var openLink0 = viewUrl ? '<br><a class="cf-pdf-link" href="' + escapeHtml(viewUrl) + '" target="_blank" rel="noopener noreferrer">OPEN CHART ON CHARTFOX</a>' : '';
      if (_pw < 10 && _cfPdfRetries >= 6) {
        container.innerHTML = '<div class="cf-empty">CHARTFOX PANEL IS HIDDEN<br><small>Switch to the Charts tab in Briefing to view charts.</small>' + openLink0 + '</div>';
      } else {
        container.innerHTML = '<div class="cf-empty">CHART VIEWER AREA NOT VISIBLE<br><small>The chart display area is hidden or has zero width. Try resizing the window.</small>' + openLink0 + '</div>';
      }
      return;
    }
    requestAnimationFrame(function() {
      cfRenderPdfCanvas(proxyUrl, container, chartId, chartName, viewUrl, _cfPdfRetries + 1);
    });
    return;
  }
  try {
    // v0.25.60: fetch the proxy URL, validate HTTP + content-type + PDF magic,
    // then pass ArrayBuffer to PDF.js -- prevents "Invalid PDF structure"
    // when the backend returns JSON errors instead of PDF bytes.
    const resp = await fetch(proxyUrl);
    if (!resp.ok) {
      var errText = '';
      try { errText = await resp.text(); } catch (_) {}
      var openLink = viewUrl ? '<a class="cf-pdf-link" href="' + escapeHtml(viewUrl) + '" target="_blank" rel="noopener noreferrer">OPEN CHART ON CHARTFOX</a>' : '';
      container.innerHTML = '<div class="cf-empty">PDF FETCH FAILED (HTTP ' + resp.status + ')<br><small>' + escapeHtml(errText.slice(0, 200) || '') + '</small>' + openLink + '</div>';
      return;
    }
    var ct = String(resp.headers.get('content-type') || '');
    var buf = await resp.arrayBuffer();
    // v0.25.60: detect JSON iframe redirect before rejecting as error
    if (ct.includes('json')) {
      try {
        var decoder = new TextDecoder();
        var jsonText = decoder.decode(new Uint8Array(buf));
        var jsonData = JSON.parse(jsonText);
        if (jsonData.render_mode === 'iframe' && jsonData.redirect_url) {
          var iframeNotice = '<div class="cf-iframe-notice">' +
            '<h3>WEB VIEW REQUIRED FOR THIS CHART PROVIDER</h3>' +
            '<p>This chart provider requires direct authorization or web frame rendering.</p>' +
            '<a href="' + escapeHtml(jsonData.redirect_url) + '" target="_blank" class="cf-pdf-link">OPEN CHART IN CHARTFOX FRAME &nearr;</a>' +
            '</div>';
          container.innerHTML = iframeNotice;
          return;
        }
      } catch (_) {}
      var bodyPreview = '';
      try { bodyPreview = new TextDecoder().decode(new Uint8Array(buf).slice(0, 200)); } catch (_) {}
      var openLink2 = viewUrl ? '<br><a class="cf-pdf-link" href="' + escapeHtml(viewUrl) + '" target="_blank" rel="noopener noreferrer">OPEN CHART ON CHARTFOX</a>' : '';
      container.innerHTML = '<div class="cf-empty">UNEXPECTED RESPONSE<br><small>Expected PDF, got ' + escapeHtml(ct) + '. ' + escapeHtml(bodyPreview) + '</small>' + openLink2 + '</div>';
      return;
    }
    if (ct.includes('html') || ct.includes('text/plain')) {
      var bodyPreview = '';
      try { bodyPreview = new TextDecoder().decode(new Uint8Array(buf).slice(0, 200)); } catch (_) {}
      var openLink2 = viewUrl ? '<br><a class="cf-pdf-link" href="' + escapeHtml(viewUrl) + '" target="_blank" rel="noopener noreferrer">OPEN CHART ON CHARTFOX</a>' : '';
      container.innerHTML = '<div class="cf-empty">UNEXPECTED RESPONSE<br><small>Expected PDF, got ' + escapeHtml(ct) + '. ' + escapeHtml(bodyPreview) + '</small>' + openLink2 + '</div>';
      return;
    }
    // Validate PDF magic bytes
    var head = new Uint8Array(buf).slice(0, Math.min(64, buf.byteLength));
    var headStr = '';
    for (var i = 0; i < head.length; i++) { headStr += String.fromCharCode(head[i]); }
    if (headStr.indexOf('%PDF-') !== 0) {
      var openLink3 = viewUrl ? '<br><a class="cf-pdf-link" href="' + escapeHtml(viewUrl) + '" target="_blank" rel="noopener noreferrer">OPEN CHART ON CHARTFOX</a>' : '';
      container.innerHTML = '<div class="cf-empty">NOT A VALID PDF<br><small>First bytes: ' + escapeHtml(headStr.slice(0, 60)) + '</small>' + openLink3 + '</div>';
      return;
    }
    const pdf = await pdfjsLib.getDocument(buf).promise;
    const page = await pdf.getPage(1);
    const wrap = document.createElement('div');
    wrap.className = 'cf-pdf-canvas-wrap';
    wrap.id = 'cfPdfCanvasWrap';
    container.innerHTML = '';
    container.appendChild(wrap);

    const canvas = document.createElement('canvas');
    canvas.id = 'cfPdfCanvas';
    wrap.appendChild(canvas);
    const ctx = canvas.getContext('2d');

    // Calculate scale to fit width
    const wrapRect = wrap.getBoundingClientRect();
    const vp = page.getViewport({scale: 1.0});
    // v0.25.60: multiply by devicePixelRatio (minimum 2.0x) for crisp rendering on HiDPI/Retina displays.
    // CSS sizes remain at logical pixels; canvas backing store scales to physical pixels.
    const dpr = Math.max(window.devicePixelRatio || 1, 3.0);
    const logicalScale = (wrapRect.width - 20) / vp.width;
    const viewport = page.getViewport({scale: logicalScale * dpr});
    canvas.width = Math.floor(viewport.width);
    canvas.height = Math.floor(viewport.height);
    canvas.style.width = Math.floor(viewport.width / dpr) + 'px';
    canvas.style.height = Math.floor(viewport.height / dpr) + 'px';
    wrap.style.height = Math.min((viewport.height / dpr) + 4, window.innerHeight * 0.75) + 'px';

    await page.render({canvasContext: ctx, viewport: viewport}).promise;

    // Zoom + Pan state
    let zoom = 1.0, panX = 0, panY = 0;
    let isDragging = false, dragStartX = 0, dragStartY = 0, dragPanX = 0, dragPanY = 0;
    let darkMode = true;
    // v0.25.60: apply dark mode CSS class immediately to prevent white flash
    wrap.classList.add('dark-mode');

    function applyTransform() {
      canvas.style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})`;
    }
    wrap.addEventListener('wheel', function(ev) {
      ev.preventDefault();
      const delta = ev.deltaY > 0 ? 0.9 : 1.1;
      zoom = Math.max(0.25, Math.min(zoom * delta, 5.0));
      applyTransform();
    }, {passive: false});
    wrap.addEventListener('mousedown', function(ev) {
      if (ev.button !== 0 || cfAnnotation.active) return;
      isDragging = true;
      dragStartX = ev.clientX;
      dragStartY = ev.clientY;
      dragPanX = panX;
      dragPanY = panY;
    });
    window.addEventListener('mousemove', function(ev) {
      if (!isDragging) return;
      panX = dragPanX + (ev.clientX - dragStartX);
      panY = dragPanY + (ev.clientY - dragStartY);
      applyTransform();
    });
    window.addEventListener('mouseup', function() { isDragging = false; });

    // Create toolbar
    const tb = document.createElement('div');
    tb.className = 'cf-pdf-toolbar';
    tb.innerHTML = `
      <span class="toolbar-group">
        <button class="cf-pdf-zoom-out" type="button">−</button>
        <span class="zoom-level" id="cfPdfZoomLevel">100%</span>
        <button class="cf-pdf-zoom-in" type="button">+</button>
        <button class="cf-pdf-zoom-reset" type="button">FIT</button>
        <button class="cf-pdf-dark-toggle" type="button" id="cfPdfDarkToggle">${darkMode ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>' : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>'}</button>
        <a class="cf-pdf-link" href="${escapeHtml(proxyUrl)}" target="_blank" rel="noopener noreferrer">OPEN PDF</a>
        <span class="cf-annot-sep">|</span>
        <button class="cf-annot-tool" id="cfAnnotPen" title="Draw">✏️</button>
        <button class="cf-annot-tool" id="cfAnnotHighlighter" title="Highlight">🖍️</button>
        <button class="cf-annot-tool" id="cfAnnotEraser" title="Erase">🧹</button>
        <select class="cf-annot-color" id="cfAnnotColor">
          <option value="#ff3333" selected>🔴</option>
          <option value="#efbd47">🟡</option>
          <option value="#00ccff">🔵</option>
          <option value="#ffffff">⚪</option>
          <option value="#ffff00">🟡</option>
        </select>
        <button class="cf-annot-tool" id="cfAnnotClear" title="Clear All">🗑️</button>
      </span>`;
    container.insertBefore(tb, wrap);

    tb.querySelector('.cf-pdf-zoom-in').onclick = () => { zoom = Math.min(zoom * 1.25, 5.0); applyTransform(); updateZoomLabel(); };
    tb.querySelector('.cf-pdf-zoom-out').onclick = () => { zoom = Math.max(zoom * 0.8, 0.25); applyTransform(); updateZoomLabel(); };
    tb.querySelector('.cf-pdf-zoom-reset').onclick = () => { zoom = 1.0; panX = 0; panY = 0; applyTransform(); updateZoomLabel(); };
    tb.querySelector('.cf-pdf-dark-toggle').onclick = () => {
      darkMode = !darkMode;
      wrap.classList.toggle('dark-mode', darkMode);
      tb.querySelector('.cf-pdf-dark-toggle').textContent = darkMode ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>' : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
    };
    function updateZoomLabel() {
      const lbl = document.getElementById('cfPdfZoomLevel');
      if (lbl) lbl.textContent = Math.round(zoom * 100) + '%';
    }
    // v0.25.60: wire annotation tools integrated into PDF toolbar
    var annotPen = tb.querySelector('#cfAnnotPen');
    var annotHighlighter = tb.querySelector('#cfAnnotHighlighter');
    var annotEraser = tb.querySelector('#cfAnnotEraser');
    var annotColorSel = tb.querySelector('#cfAnnotColor');
    var annotClear = tb.querySelector('#cfAnnotClear');
    var allAnnotTools = [annotPen, annotHighlighter, annotEraser];
    if (annotPen) annotPen.onclick = function() {
      var wasActive = annotPen.classList.contains('active');
      allAnnotTools.forEach(function(t) { t.classList.remove('active'); });
      if (wasActive) { cfAnnotation.active = false; cfAnnotation.tool = 'pen'; }
      else { annotPen.classList.add('active'); cfAnnotation.active = true; cfAnnotation.tool = 'pen'; }
      updateAnnotCanvasPointer();
    };
    if (annotHighlighter) annotHighlighter.onclick = function() {
      var wasActive = annotHighlighter.classList.contains('active');
      allAnnotTools.forEach(function(t) { t.classList.remove('active'); });
      if (wasActive) { cfAnnotation.active = false; cfAnnotation.tool = 'highlighter'; }
      else { annotHighlighter.classList.add('active'); cfAnnotation.active = true; cfAnnotation.tool = 'highlighter'; }
      updateAnnotCanvasPointer();
    };
    if (annotEraser) annotEraser.onclick = function() {
      var wasActive = annotEraser.classList.contains('active');
      allAnnotTools.forEach(function(t) { t.classList.remove('active'); });
      if (wasActive) { cfAnnotation.active = false; cfAnnotation.tool = 'eraser'; }
      else { annotEraser.classList.add('active'); cfAnnotation.active = true; cfAnnotation.tool = 'eraser'; }
      updateAnnotCanvasPointer();
    };
    if (annotColorSel) annotColorSel.onchange = function() { cfAnnotation.color = annotColorSel.value; };
    if (annotClear) annotClear.onclick = function() {
      cfAnnotation.strokes = []; cfAnnotation.undoStack = []; cfAnnotation.currentStroke = null;
      cfSaveAnnotations(); cfRedrawAnnotations();
    };
    function updateAnnotCanvasPointer() {
      var c = document.getElementById('cfAnnotOverlay');
      if (c) c.style.pointerEvents = cfAnnotation.active ? 'auto' : 'none';
    }

    cfPdfRenderer = { pdf, page, canvas, wrap, zoom, panX, panY, darkMode, destroy: () => { container.innerHTML = ''; } };
    // v0.25.60: init annotation overlay after successful render
    cfInitAnnotationOverlay(container, chartId);
    // v0.25.60: auto-fit chart to fill expanded viewer
    setTimeout(function(){ cfAutoFitToScreen(); }, 100);
  } catch (e) {
    const openLink = viewUrl ? '<a class="cf-pdf-link" href="' + escapeHtml(viewUrl) + '" target="_blank" rel="noopener noreferrer">OPEN CHART ON CHARTFOX</a>' : '';
    container.innerHTML = '<div class="cf-empty">PDF LOAD FAILED<br><small>' + escapeHtml(e.message || '') + '</small>' + openLink + '</div>';
  }
}

// v0.25.60 — Annotation/Scratchpad Overlay (ported from Scratchpad module)
// Transparent canvas overlay for pen/highlighter/eraser on top of chart viewer
function cfInitAnnotationOverlay(previewContainer, chartId) {
  if (!previewContainer || !chartId) return;
  // Remove previous overlay if any
  var oldOverlay = document.getElementById('cfAnnotOverlay');
  if (oldOverlay) oldOverlay.remove();
  // v0.25.60: toolbar is now integrated into PDF toolbar — only create canvas overlay here
  // Reset state for new chart
  cfAnnotation.lastChartId = chartId;
  cfAnnotation.strokes = cfLoadAnnotations(chartId);
  cfAnnotation.undoStack = [];
  cfAnnotation.currentStroke = null;
  cfAnnotation.active = false;
  // Create overlay canvas
  var canvas = document.createElement('canvas');
  canvas.id = 'cfAnnotOverlay';
  canvas.className = 'cf-annot-canvas';
  canvas.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;z-index:15;pointer-events:none;';
  // Insert inside the preview container so it overlays the chart
  var pdfWrap = previewContainer.querySelector('.cf-pdf-canvas-wrap');
  if (pdfWrap) {
    pdfWrap.style.position = 'relative';
    pdfWrap.appendChild(canvas);
  } else {
    // v0.25.60: create wrapper for pan sync if not present
    var autoWrap = document.createElement('div');
    autoWrap.id = 'cfPdfCanvasWrap';
    autoWrap.style.cssText = 'position:relative;overflow:hidden';
    previewContainer.style.position = 'relative';
    previewContainer.appendChild(autoWrap);
    autoWrap.appendChild(canvas);
  }
  // Size canvas to match container
  function resizeAnnotCanvas() {
    var rect = (pdfWrap || previewContainer).getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;
    cfRedrawAnnotations();
  }
  resizeAnnotCanvas();
  window.addEventListener('resize', resizeAnnotCanvas);
  cfAnnotation.canvas = canvas;
  cfAnnotation.ctx = canvas.getContext('2d');
  cfAnnotation.active = false;
  cfRedrawAnnotations();
  // v0.25.60: toolbar wiring is now in cfRenderPdfCanvas; only mouse drawing events here
  // Mouse drawing events
  canvas.addEventListener('mousedown', cfAnnotStart);
  canvas.addEventListener('mousemove', cfAnnotMove);
  canvas.addEventListener('mouseup', cfAnnotEnd);
  canvas.addEventListener('mouseleave', cfAnnotEnd);
}

// v0.25.60: Convert pointer event to chart canvas internal-pixel and normalised coordinates.
// Accounts for CSS display scale vs actual canvas pixel resolution.
function getChartCanvasCoordinates(e, canvas) {
  var rect = canvas.getBoundingClientRect();
  var clientX = e.clientX || (e.touches && e.touches[0] ? e.touches[0].clientX : 0);
  var clientY = e.clientY || (e.touches && e.touches[0] ? e.touches[0].clientY : 0);
  // CSS-to-internal pixel scaling (handles CSS transform:scale on wrapper)
  var scaleX = canvas.width / rect.width;
  var scaleY = canvas.height / rect.height;
  var canvasX = (clientX - rect.left) * scaleX;
  var canvasY = (clientY - rect.top) * scaleY;
  // v0.25.60: Normalise against the overlay canvas dimensions so that
  // normalisation and rendering use the same denominator, eliminating the
  // cursor-offset bug.  Stored strokes are canvas-relative; reloaded strokes
  // drawn before this fix (nativeWidth/nativeHeight basis) will be slightly
  // offset on first redraw but will be re-saved in the new basis on next edit.
  var rx = canvasX / (canvas.width || 1);
  var ry = canvasY / (canvas.height || 1);
  return { x: canvasX, y: canvasY, rx: rx, ry: ry };
}

function cfAnnotStart(e) {
  e.stopPropagation();
  e.preventDefault();
  if (!cfAnnotation.active) return;
  var coords = getChartCanvasCoordinates(e, cfAnnotation.canvas);
  cfAnnotation.currentStroke = {
    tool: cfAnnotation.tool === 'highlighter' ? 'highlighter' : (cfAnnotation.tool === 'eraser' ? 'eraser' : 'pen'),
    color: cfAnnotation.color,
    width: cfAnnotation.width,
    points: [{ x: coords.x, y: coords.y, rx: coords.rx, ry: coords.ry }]
  };
}

function cfAnnotMove(e) {
  if (!cfAnnotation.currentStroke || !cfAnnotation.active) return;
  var coords = getChartCanvasCoordinates(e, cfAnnotation.canvas);
  cfAnnotation.currentStroke.points.push({ x: coords.x, y: coords.y, rx: coords.rx, ry: coords.ry });
  cfRedrawAnnotations();
  // Draw current stroke on top
  var ctx = cfAnnotation.ctx;
  var stroke = cfAnnotation.currentStroke;
  var pts = stroke.points;
  if (pts.length < 2) return;
  var last = pts[pts.length - 2];
  var curr = pts[pts.length - 1];
  ctx.save();
  ctx.globalCompositeOperation = stroke.tool === 'eraser' ? 'destination-out' : 'source-over';
  ctx.globalAlpha = stroke.tool === 'highlighter' ? 0.4 : cfAnnotation.opacity;
  ctx.strokeStyle = stroke.tool === 'eraser' ? 'rgba(0,0,0,1)' : stroke.color;
  ctx.lineWidth = stroke.width;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.beginPath();
  var lrx = last.rx !== undefined ? last.rx : (last.x || 0);
  var lry = last.ry !== undefined ? last.ry : (last.y || 0);
  ctx.moveTo(lrx * cfAnnotation.canvas.width, lry * cfAnnotation.canvas.height);
  var crx = curr.rx !== undefined ? curr.rx : (curr.x || 0);
  var cry = curr.ry !== undefined ? curr.ry : (curr.y || 0);
  ctx.lineTo(crx * cfAnnotation.canvas.width, cry * cfAnnotation.canvas.height);
  ctx.stroke();
  ctx.restore();
}

function cfAnnotEnd() {
  if (!cfAnnotation.currentStroke) return;
  cfAnnotation.strokes.push(cfAnnotation.currentStroke);
  cfAnnotation.undoStack = []; // clear redo on new stroke
  cfSaveAnnotations(cfAnnotation.lastChartId, cfAnnotation.strokes);
  cfAnnotation.currentStroke = null;
  cfRedrawAnnotations();
}

function cfAnnotUndo() {
  if (cfAnnotation.strokes.length === 0) return;
  cfAnnotation.undoStack.push(cfAnnotation.strokes.pop());
  cfSaveAnnotations(cfAnnotation.lastChartId, cfAnnotation.strokes);
  cfRedrawAnnotations();
}

function cfRedrawAnnotations() {
  // v0.25.60: migrate any legacy (v1) saved strokes into the canvas-relative
  // basis once, once the overlay canvas is sized to the rendered PDF canvas.
  if (cfAnnotation._legacyPending && cfAnnotation.lastChartId) {
    cfMigrateLegacyAnnotations(cfAnnotation.lastChartId);
  }
  var ctx = cfAnnotation.ctx;
  if (!ctx) return;
  ctx.clearRect(0, 0, cfAnnotation.canvas.width, cfAnnotation.canvas.height);
  (cfAnnotation.strokes || []).forEach(function(stroke) {
    var pts = stroke.points;
    if (pts.length < 2) return;
    ctx.save();
    ctx.globalCompositeOperation = stroke.tool === 'eraser' ? 'destination-out' : 'source-over';
    ctx.globalAlpha = stroke.tool === 'highlighter' ? 0.4 : (cfAnnotation.opacity || 0.85);
    ctx.strokeStyle = stroke.tool === 'eraser' ? 'rgba(0,0,0,1)' : (stroke.color || '#efbd47');
    ctx.lineWidth = stroke.width || 3.5;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.beginPath();
    ctx.moveTo(pts[0].rx * cfAnnotation.canvas.width, pts[0].ry * cfAnnotation.canvas.height);
    for (var i = 1; i < pts.length; i++) {
      ctx.lineTo(pts[i].rx * cfAnnotation.canvas.width, pts[i].ry * cfAnnotation.canvas.height);
    }
    ctx.stroke();
    ctx.restore();
  });
}

// Annotation storage format (v0.25.60+):
//   { v: 2, strokes: [ { tool, color, width, points: [{x,y,rx,ry}] } ] }
// Version 2 stores rx/ry normalized against the overlay canvas size
// (canvas.width / canvas.height) -- the same denominator used at render
// time. Pre-v0.25.60 saved strokes (bare array, v1) normalized rx/ry
// against the PDF *native* page size (cfPdfState.nativeWidth/Height). On
// load we detect the bare-array (v1) format and transform each point once
// into the v2 canvas-relative basis before rendering, so old annotations
// stay pinned where they were originally drawn instead of shifting.
var CF_ANNOT_FORMAT_VERSION = 2;

function cfLoadAnnotations(chartId) {
  try {
    var key = 'opsroom-cf-annot-' + chartId;
    var raw = localStorage.getItem(key);
    if (!raw) return [];
    var data = JSON.parse(raw);
    if (data && typeof data === 'object' && Array.isArray(data.strokes)) {
      // v2 (or later): canvas-relative coordinates, render as-is.
      cfAnnotation._legacyPending = (data.v || 0) < CF_ANNOT_FORMAT_VERSION && data.v !== undefined ? cfNeedsLegacyTransform(data.strokes) : false;
      if ((data.v || 0) < CF_ANNOT_FORMAT_VERSION && cfAnnotation._legacyPending) {
        return data.strokes;
      }
      cfAnnotation._legacyPending = false;
      return data.strokes;
    }
    if (Array.isArray(data)) {
      // v1 legacy format (bare array, native-page-relative rx/ry).
      cfAnnotation._legacyPending = cfNeedsLegacyTransform(data);
      return data;
    }
    return [];
  } catch (_) { return []; }
}

function cfNeedsLegacyTransform(strokes) {
  // Any stroke with a point whose rx/ry is plausibly native-relative (i.e.
  // exceeds the canvas-relative range) is legacy. Canvas-relative rx/ry is
  // always within [0,1]; native-relative values can exceed 1 when the PDF
  // page is larger than the displayed canvas, but at minimum values below
  // 0 or above 1 that are not tiny float artifacts indicate the old basis.
  for (var i = 0; i < (strokes || []).length; i++) {
    var pts = (strokes[i] || {}).points || [];
    for (var j = 0; j < pts.length; j++) {
      var p = pts[j];
      var rxx = p.rx !== undefined ? p.rx : 0;
      var ryy = p.ry !== undefined ? p.ry : 0;
      if (rxx < -0.0001 || rxx > 1.0001 || ryy < -0.0001 || ryy > 1.0001) {
        return true;
      }
    }
  }
  return false;
}

// Convert legacy (native-page-relative) strokes to the v2 canvas-relative
// basis once, then re-save. Must only run when the overlay canvas is sized
// to the PDF canvas (canvas.width === PDF canvas internal width) and the
// native page dimensions are known from a real render.
function cfMigrateLegacyAnnotations(chartId) {
  if (!cfAnnotation._legacyPending) return;
  var canvas = cfAnnotation.canvas;
  if (!canvas || !canvas.width || !canvas.height) return;
  if (!cfPdfState.viewport || !cfPdfState.nativeWidth || !cfPdfState.nativeHeight) return;
  // Safety: only migrate when the canvas is sized to the PDF canvas, not the
  // temporary CSS-rect sizing from resizeAnnotCanvas.
  if (Math.abs(canvas.width - cfPdfState.viewport.width) > 1) return;

  var scaleX = cfPdfState.nativeWidth / canvas.width;
  var scaleY = cfPdfState.nativeHeight / canvas.height;
  var strokes = cfAnnotation.strokes || [];
  for (var i = 0; i < strokes.length; i++) {
    var pts = strokes[i].points || [];
    for (var j = 0; j < pts.length; j++) {
      if (pts[j].rx !== undefined) pts[j].rx = pts[j].rx * scaleX;
      if (pts[j].ry !== undefined) pts[j].ry = pts[j].ry * scaleY;
    }
  }
  cfAnnotation._legacyPending = false;
  cfSaveAnnotations(chartId, strokes);
  cfRedrawAnnotations();
}

function cfSaveAnnotations(chartId, strokes) {
  try {
    var key = 'opsroom-cf-annot-' + chartId;
    var payload = { v: CF_ANNOT_FORMAT_VERSION, strokes: (strokes || []).slice(-500) }; // cap at 500 strokes
    localStorage.setItem(key, JSON.stringify(payload));
  } catch (_) {}
}

// v0.25.60 — Auto-fit chart to screen on load and window resize
function cfAutoFitToScreen() {
  var canvas = document.getElementById('cfPdfCanvas');
  if (!canvas || !cfPdfRenderer) return;
  var wrap = document.getElementById('cfPdfCanvasWrap');
  if (!wrap) return;
  var rect = wrap.getBoundingClientRect();
  var canvasW = canvas.offsetWidth;
  var canvasH = canvas.offsetHeight;
  if (canvasW <= 0 || canvasH <= 0) return;
  var scaleX = (rect.width - 20) / canvasW;
  var scaleY = (rect.height - 10) / canvasH;
  var fitScale = Math.min(scaleX, scaleY, 1.0); // never exceed 100%
  cfPdfRenderer.zoom = fitScale;
  cfPdfRenderer.panX = 0;
  cfPdfRenderer.panY = 0;
  canvas.style.transform = 'translate(0px, 0px) scale(' + fitScale + ')';
}

// -- Pin/star bookmarking fix (v0.25.16) -------------------------------------
// cfLoadPins and cfSavePins already exist. Add a restore check on page load.
function cfRestorePins() {
  try {
    cfState.pins = cfLoadPins();
  } catch (_) { cfState.pins = []; }
}
// Call restore after pin definition (the existing cfLoadPins function is already correct)
// The fix is ensuring cfState.pins is initialized from localStorage on every page load.
// This is already handled at cfInitAirpor
