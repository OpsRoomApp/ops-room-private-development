const $ = id => document.getElementById(id);
// v0.25.73 (#8 sweep): in-app confirm modal — WebView2 silently blocks native
// window.confirm(), so confirm-gated host actions use a real <dialog> instead.
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

// v0.25.69: hard client-side timeout on host-page fetches. The boot chain
// (loadSettings + the status Promise.all) is blocked by whichever backend
// call is slowest; a stalled endpoint (e.g. /api/system/summary waiting on
// the telemetry lock during a SimConnect/FSUIPC connect) used to freeze the
// whole host console for minutes and look like a hang. Abort after 10 s so
// the page always renders and marks the slow widget FAULT instead.
async function fet(url, options = {}, timeoutMs = 10000){
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),timeoutMs);
  try{return await fetch(url,{...options,signal:controller.signal})}
  finally{clearTimeout(timer)}
}
let preferredUrl = '';
let hostSettings = null;
let hostServerInfo = null;
let hostIpVisible = false;
const HOST_MODULE_LABELS={status:'Status',fids:'VATSIM FIDS',dispatch:'Dispatch',briefing:'Briefing',scratchpad:'Scratchpad',watch:'Flight Watch',performance:'Performance',raas:'Runway Awareness',network:'Network',map:'Live Map',datalink:'Datalink',ground:'Ground Control',announcer:'Announcer',procedures:'Procedures',logbook:'Logbook',obs:'OBS Tools',system:'Settings'};
function escapeHtml(value){return String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function lamp(state){if(['connected','running','detected','configured','loaded'].includes(state))return'green';if(['standby','cached'].includes(state))return'amber';if(['fault','failed'].includes(state))return'red';return'off'}
function friendlyError(value){const text=String(value||'').replace(/\b(?:OSError|RuntimeError|ConnectionError|TimeoutError|Exception):?\s*/gi,'').replace(/\[WinError[^\]]*\]/gi,'').replace(/\b-?2147\d+\b/g,'').replace(/\s{2,}/g,' ').trim();return text&&text.length<120?text:'Operation unavailable. Open Diagnostics for technical details.'}
function compactConnectionState(item){const state=String(item?.state||'').toLowerCase();if(['connected','running','detected','configured','loaded'].includes(state))return'READY';if(['standby','cached'].includes(state))return'STANDBY';if(['fault','failed'].includes(state))return'ATTENTION';return'OFFLINE'}
function renderAddresses(){if(!hostServerInfo)return;const info=hostServerInfo;const secretClass=hostIpVisible?'secret-value revealed':'secret-value concealed';const qrClass=hostIpVisible?'secret-qr revealed':'secret-qr concealed';$('preferredUrl').textContent=info.preferred_url;$('preferredUrl').className=secretClass;$('hostUrls').innerHTML=[`LOCAL: ${info.local_url}`,...info.lan_urls.map(x=>`LAN: ${x}`)].map(x=>`<b class="${secretClass}">${escapeHtml(x)}</b>`).join('');$('hostSettingsUrls').innerHTML=[`LOCAL: ${info.local_url}`,...info.lan_urls.map(x=>`LAN: ${x}`)].map(x=>`<b class="${secretClass}">${escapeHtml(x)}</b>`).join('');$('hostQr').className=qrClass;$('toggleIp').textContent=hostIpVisible?'HIDE':'SHOW';$('toggleIp').setAttribute('aria-pressed',hostIpVisible?'true':'false');$('toggleIp').title=hostIpVisible?'Conceal network addresses and QR code':'Reveal network addresses and QR code'}
function tick(){const now=new Date();$('hostClock').textContent=`${now.toISOString().slice(11,19)} UTC`}
function showHostPage(name){document.querySelectorAll('.host-page').forEach(x=>x.classList.toggle('active',x.id===`host-page-${name}`));document.querySelectorAll('.host-tab').forEach(x=>x.classList.toggle('active',x.dataset.hostPage===name));history.replaceState(null,'',name==='settings'?'#settings':'#status')}
function setBusy(button,busy,label){if(!button)return;button.disabled=busy;if(busy){button.dataset.label=button.textContent;button.textContent=label}else button.textContent=button.dataset.label||button.textContent}
function showSaveToast(message='Settings saved'){let toast=document.getElementById('hostSaveToast');if(!toast){toast=document.createElement('div');toast.id='hostSaveToast';toast.className='host-save-toast';toast.hidden=true;document.body.appendChild(toast)}toast.textContent=message;toast.hidden=false;clearTimeout(showSaveToast.timer);showSaveToast.timer=setTimeout(()=>toast.hidden=true,2600)}
async function applyAirlineTheme(){try{const data=await fet('/api/interface/theme',{cache:'no-store'}).then(r=>r.json());document.body.classList.remove('airline-theme','airline-theme-full','airline-theme-accent-only');if(!data.active)return;document.body.classList.add('airline-theme');document.body.classList.add(data.mode==='accent'?'airline-theme-accent-only':'airline-theme-full');document.documentElement.style.setProperty('--amber',data.accent||'#71b4c3');document.documentElement.style.setProperty('--amber-pale',data.accent_pale||'#d3edf2');document.documentElement.style.setProperty('--line',data.line||'#59676d');document.documentElement.style.setProperty('--airline-bg-image',`url(${data.background_url})`);document.documentElement.style.setProperty('--airline-overlay-start',data.overlay_start||'rgba(0,0,0,.68)');document.documentElement.style.setProperty('--airline-overlay-end',data.overlay_end||'rgba(0,0,0,.78)')}catch{document.body.classList.remove('airline-theme','airline-theme-full','airline-theme-accent-only')}}
async function refresh(probe=false){
  const probeButtons=[$('hostProbeMsfs'),$('hostSetupProbe')]; probeButtons.forEach(b=>setBusy(b,probe,'PROBING...'));
  try{
    const [summary,server]=await Promise.all([
      fet(`/api/system/summary?probe_simconnect=${probe?'true':'false'}`,{cache:'no-store'}).then(r=>r.json()),
      fet('/api/server/info',{cache:'no-store'}).then(r=>r.json())
    ]);
    const names={msfs:'MSFS / TELEMETRY',telemetry:'TELEMETRY SOURCE',vatsim:'VATSIM IDENTITY',simbrief:'SIMBRIEF',vpilot:'VPILOT',hoppie:'HOPPIE',gsx:'GSX PRO'};
    $('hostConnections').innerHTML=Object.entries(summary.integrations).map(([key,item])=>`<div class="host-row"><i class="lamp ${lamp(item.state)}"></i><b>${names[key]||key.toUpperCase()}</b><span>${compactConnectionState(item)}</span></div>`).join('');
    if($('hostTelemetryStatus')){const t=summary.integrations?.telemetry||{};$('hostTelemetryStatus').innerHTML=`<b>${escapeHtml(t.label||'NOT SAMPLED')}</b><span>${escapeHtml(t.detail||'FSUIPC7 FIRST / SIMCONNECT FALLBACK')}</span>`;}
    const fault=Object.values(summary.integrations).some(item=>['fault','failed'].includes(item.state));
    $('hostSystemLamp').innerHTML=`<i class="lamp ${fault?'red':'green'}"></i>${fault?'SYSTEM ATTENTION':'SYSTEM NORMAL'}`;
    hostServerInfo=server;preferredUrl=server.preferred_url;renderAddresses();
    $('hostLanState').textContent=server.tablet_ready?'READY':'LOCAL ONLY';
    $('accessNote').textContent=server.tablet_ready?'Scan this code from a device connected to the same network.':'Enable LAN / tablet access in System Setup, restart OPS ROOM, and allow the Windows Firewall rule.';

    $('hostQr').src=`/api/server/qr.png?t=${Date.now()}`;$('hostPairingCode').value=server.pairing_code||'PAIRING OFF';$('hostSecurityState').textContent=server.device_security_enabled?'PAIRING REQUIRED':'PAIRING OFF';
  }catch(error){$('serverState').textContent='FAULT';$('hostLanState').textContent='FAULT';$('hostSystemLamp').innerHTML='<i class="lamp red"></i>SYSTEM ATTENTION'}
  finally{probeButtons.forEach(b=>setBusy(b,false,'PROBE MSFS'))}
}

function _setInputSensitiveState(input, concealed){
  if(!input)return;
  if(!input.dataset.originalType) input.dataset.originalType = input.getAttribute('type') || 'text';
  input.classList.toggle('streamer-secret', concealed);
  input.type = concealed ? 'password' : (input.dataset.originalType || 'text');
}

function _setFieldConcealed(input, concealed){
  if(!input)return;
  const wrap=input.parentElement;
  _setInputSensitiveState(input, concealed);
  if(!wrap)return;
  let button=wrap.querySelector('.streamer-reveal-button');
  if(concealed && !button){
    button=document.createElement('button');button.type='button';button.className='streamer-reveal-button';button.textContent='SHOW';
    button.addEventListener('click',async()=>{
      const isConcealed=input.classList.contains('streamer-secret') || input.type === 'password';
      if(!isConcealed){
        _setInputSensitiveState(input, true);
        button.textContent='SHOW';
        return;
      }
      if(document.getElementById('hostStreamerMode')?.checked && !(await uiConfirm('Streamer Mode is enabled. This may reveal sensitive information on stream or in screenshots. Reveal anyway?', 'REVEAL')))return;
      _setInputSensitiveState(input, false);
      button.textContent='HIDE';
      setTimeout(()=>{if(document.getElementById('hostStreamerMode')?.checked){_setInputSensitiveState(input, true);button.textContent='SHOW'}},60000);
    });
    wrap.appendChild(button);
  }
  if(button){
    button.hidden=!concealed;
    button.textContent=(input.classList.contains('streamer-secret') || input.type === 'password')?'SHOW':'HIDE';
  }
}

function applyStreamerMode(data){
  const enabled=!!data?.interface?.streamer_mode;
  ['hostVatsimCid','hostSimbriefId','hostHoppieCallsign','hostGsxRoot','hostVpilotRoot','hostAnnouncementsRoot','hostFsuipcPath','hostSurfaceDbPath'].forEach(id=>{
    const input=$(id);
    _setFieldConcealed(input,enabled);
    if(enabled){
      _setInputSensitiveState(input,true);
      const button=input?.parentElement?.querySelector('.streamer-reveal-button');
      if(button){button.hidden=false;button.textContent='SHOW'}
    }
  });
}
function renderHostModuleVisibility(data){
  const grid=$('hostModuleVisibilityGrid');
  if(!grid)return;
  const visible=data?.interface?.module_visibility||{};
  grid.innerHTML=Object.entries(HOST_MODULE_LABELS).map(([key,label])=>`<label><input type="checkbox" data-host-module-visible="${escapeHtml(key)}" ${visible[key]===false?'':'checked'} /> ${escapeHtml(label)}</label>`).join('');
}

async function refreshSurfaceStatus(force=false){
  const box=$('hostSurfaceStatus');
  if(!box)return;
  try{
    const response=await fet(force?'/api/livemap/surface/rescan':'/api/livemap/status',{method:force?'POST':'GET',cache:'no-store'});
    const data=await response.json();
    const surf=data.surface||{};
    const ready=!!surf.available;
    box.innerHTML=`<b>${ready?'SURFACE DATA READY':'SURFACE DATA NOT DETECTED'}</b><span>${escapeHtml(surf.message||data.message||'Local airport surface data is optional.')}${surf.path?' · '+escapeHtml(surf.path):''}</span>`;
  }catch(error){box.innerHTML=`<b>SURFACE CHECK FAILED</b><span>${escapeHtml(friendlyError(error.message))}</span>`}
}

function collectHostModuleVisibility(){
  const out={};
  document.querySelectorAll('[data-host-module-visible]').forEach(input=>out[input.dataset.hostModuleVisible]=input.checked);
  return out;
}
function fillSettings(data){
  hostSettings=data;
  $('hostVatsimCid').value=data.identity?.vatsim_cid||'';
  $('hostSimbriefId').value=data.identity?.simbrief_user_id||'';
  $('hostSimbriefAuto').checked=data.integrations?.simbrief_auto_load!==false;
  $('hostHoppieCode').value=''; $('hostClearHoppie').checked=false;
  $('hostHoppieCallsign').value=data.integrations?.hoppie_callsign_override||'';
  $('hostHoppieAutoPoll').checked=data.integrations?.hoppie_auto_poll!==false;
  $('hostGsxRoot').value=data.integrations?.gsx_root||'';
  $('hostVpilotRoot').value=data.integrations?.vpilot_root||'';
   $('hostAnnouncementsEnabled').checked=!!data.integrations?.announcements_enabled;
   $('hostAnnouncementsRoot').value=data.integrations?.announcements_root||'';
   $('hostAnnouncementsVolume').value=data.integrations?.announcements_volume??80;
   $('hostCameraVolumeEnabled').checked=!!data.integrations?.camera_volume_enabled;
   $('hostCameraVolumeCockpit').value=data.integrations?.camera_volume_cockpit??100;
   $('hostCameraVolumeCabin').value=data.integrations?.camera_volume_cabin??70;
   $('hostCameraVolumeExternal').value=data.integrations?.camera_volume_external??40;
  $('hostAnnouncementsCallsign').value=data.integrations?.announcements_callsign_override||'';
  $('hostAnnouncementsAirline').value=data.integrations?.announcements_airline_override||'';
  $('hostAnnouncementsHotkeysEnabled').checked=data.integrations?.announcements_hotkeys_enabled!==false;if($('hostAirlineTheme'))$('hostAirlineTheme').checked=data.interface?.airline_theme_enabled!==false;if($('hostAirlineThemeMode'))$('hostAirlineThemeMode').value=data.interface?.airline_theme_mode||'full';if($('hostAirlineThemeIntensity')){$('hostAirlineThemeIntensity').value=data.interface?.airline_theme_intensity??38; if($('hostAirlineThemeIntensityLabel'))$('hostAirlineThemeIntensityLabel').textContent=`${$('hostAirlineThemeIntensity').value}%`;}
  $('hostAnnouncementsPauseHotkey').value=data.integrations?.announcements_pause_hotkey||'CTRL+ALT+P';
  $('hostAnnouncementsMuteHotkey').value=data.integrations?.announcements_mute_hotkey||'CTRL+ALT+M';
  $('hostGsxAutomation').checked=data.integrations?.gsx_automation_enabled!==false;
  $('hostGsxAutoPushback').checked=!!(data.integrations?.gsx_auto_prepare_after_services ?? data.integrations?.gsx_auto_pushback);if($('hostGsxBeaconPushback'))$('hostGsxBeaconPushback').checked=!!data.integrations?.gsx_prepare_on_beacon;$('hostFsuipcEnabled').checked=data.integrations?.fsuipc_enabled!==false;if($('hostFsuipcAutostart'))$('hostFsuipcAutostart').checked=data.integrations?.fsuipc_autostart!==false;if($('hostFsuipcPath'))$('hostFsuipcPath').value=data.integrations?.fsuipc_path||'';$('hostTelemetryInterval').value=data.integrations?.telemetry_sample_seconds??1; if($('hostOpenAipKey'))$('hostOpenAipKey').value=data.integrations?.openaip_api_key||''; if($('hostAipChartsEnabled'))$('hostAipChartsEnabled').checked=data.integrations?.aip_charts_enabled!==false; if($('hostOpenAipMapEnabled'))$('hostOpenAipMapEnabled').checked=data.integrations?.openaip_map_enabled!==false; if($('hostRaasNotamCallouts'))$('hostRaasNotamCallouts').checked=data.integrations?.raas_notam_callouts!==false; if($('hostNotamNotifications'))$('hostNotamNotifications').checked=data.integrations?.notam_notifications!==false; if($('hostSurfaceAutoDetect'))$('hostSurfaceAutoDetect').checked=data.integrations?.local_surface_db_auto_detect!==false; if($('hostSurfaceDbPath'))$('hostSurfaceDbPath').value=data.integrations?.local_surface_db_path||''; refreshSurfaceStatus(false);
  $('hostLanAccess').checked=!!data.server?.lan_access;
  $('hostDeviceSecurity').checked=!!data.server?.device_security_enabled;
  $('hostServerPort').value=data.server?.port||8080;
  $('hostStartPage').value=data.interface?.start_page==='traffic'?'fids':(data.interface?.start_page||'status');
  $('hostNotifications').checked=!!data.interface?.notifications;$('hostNotificationSound').checked=data.interface?.notification_sound!==false;$('hostNativeNotifications').checked=data.interface?.native_notifications!==false;$('hostImportantNotifications').checked=data.interface?.important_notifications_only!==false;if($('hostStreamerMode'))$('hostStreamerMode').checked=!!data.interface?.streamer_mode;applyStreamerMode(data);
  renderHostModuleVisibility(data);
  const units=data.interface?.units||{};
  $('hostUnitWeight').value=units.weight||'kg';
  $('hostUnitDistance').value=units.distance||'nm';
  $('hostUnitAltitude').value=units.altitude||'ft';
  $('hostUnitSpeed').value=units.speed||'kt';
  $('hostUnitVertical').value=units.vertical_speed||'fpm';
}
async function loadSettings(){const response=await fet('/api/settings',{cache:'no-store'});if(!response.ok)throw new Error(`Settings HTTP ${response.status}`);fillSettings(await response.json())}
async function saveSettings(event){
  event.preventDefault(); $('hostSaveState').textContent='SAVING';
  const wasSetupCompleted = !!(hostSettings?.interface?.setup_completed);
  const payload={identity:{vatsim_cid:$('hostVatsimCid').value.trim(),simbrief_user_id:$('hostSimbriefId').value.trim()},integrations:{gsx_root:$('hostGsxRoot').value.trim(),vpilot_root:$('hostVpilotRoot').value.trim(),simbrief_auto_load:$('hostSimbriefAuto').checked,announcements_enabled:$('hostAnnouncementsEnabled').checked,announcements_root:$('hostAnnouncementsRoot').value.trim(),announcements_volume:Number($('hostAnnouncementsVolume').value||80),announcements_callsign_override:$('hostAnnouncementsCallsign').value.trim().toUpperCase(),announcements_airline_override:$('hostAnnouncementsAirline').value.trim().toUpperCase(),announcements_hotkeys_enabled:$('hostAnnouncementsHotkeysEnabled').checked,announcements_pause_hotkey:$('hostAnnouncementsPauseHotkey').value.trim().toUpperCase(),announcements_mute_hotkey:$('hostAnnouncementsMuteHotkey').value.trim().toUpperCase(),camera_volume_enabled:$('hostCameraVolumeEnabled').checked,camera_volume_cockpit:Number($('hostCameraVolumeCockpit').value||100),camera_volume_cabin:Number($('hostCameraVolumeCabin').value||70),camera_volume_external:Number($('hostCameraVolumeExternal').value||40),gsx_automation_enabled:$('hostGsxAutomation').checked,gsx_auto_pushback:$('hostGsxAutoPushback').checked,gsx_auto_prepare_after_services:$('hostGsxAutoPushback').checked,gsx_prepare_on_beacon:$('hostGsxBeaconPushback')?$('hostGsxBeaconPushback').checked:false,hoppie_callsign_override:$('hostHoppieCallsign').value.trim().toUpperCase(),hoppie_auto_poll:$('hostHoppieAutoPoll').checked,fsuipc_enabled:$('hostFsuipcEnabled').checked,fsuipc_autostart:$('hostFsuipcAutostart')?$('hostFsuipcAutostart').checked:true,fsuipc_path:$('hostFsuipcPath')?$('hostFsuipcPath').value.trim():'',telemetry_sample_seconds:Number($('hostTelemetryInterval').value||1),openaip_api_key:$('hostOpenAipKey')?$('hostOpenAipKey').value.trim():'',aip_charts_enabled:$('hostAipChartsEnabled')?$('hostAipChartsEnabled').checked:true,openaip_map_enabled:$('hostOpenAipMapEnabled')?$('hostOpenAipMapEnabled').checked:true,local_surface_db_auto_detect:$('hostSurfaceAutoDetect')?$('hostSurfaceAutoDetect').checked:true,local_surface_db_path:$('hostSurfaceDbPath')?$('hostSurfaceDbPath').value.trim():'',raas_notam_callouts:$('hostRaasNotamCallouts')?$('hostRaasNotamCallouts').checked:true,notam_notifications:$('hostNotamNotifications')?$('hostNotamNotifications').checked:true},server:{lan_access:$('hostLanAccess').checked,port:Number($('hostServerPort').value||8080),device_security_enabled:$('hostDeviceSecurity').checked},interface:{start_page:$('hostStartPage').value,notifications:$('hostNotifications').checked,notification_sound:$('hostNotificationSound').checked,native_notifications:$('hostNativeNotifications').checked,important_notifications_only:$('hostImportantNotifications').checked,streamer_mode:$('hostStreamerMode')?$('hostStreamerMode').checked:false,airline_theme_enabled:$('hostAirlineTheme')?$('hostAirlineTheme').checked:true,airline_theme_mode:$('hostAirlineThemeMode')?$('hostAirlineThemeMode').value:'full',airline_theme_intensity:$('hostAirlineThemeIntensity')?Number($('hostAirlineThemeIntensity').value||38):38,module_visibility:collectHostModuleVisibility(),units:{weight:$('hostUnitWeight').value,distance:$('hostUnitDistance').value,altitude:$('hostUnitAltitude').value,speed:$('hostUnitSpeed').value,vertical_speed:$('hostUnitVertical').value}},hoppie_logon_code:$('hostHoppieCode').value,clear_hoppie:$('hostClearHoppie').checked};
  try{const response=await fetch('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const data=await response.json();if(!response.ok)throw new Error(data.detail||`HTTP ${response.status}`);fillSettings(data.settings);$('hostSaveState').textContent=data.restart_required?'SAVED, RESTART REQUIRED':'SAVED';showSaveToast(data.restart_required?'Settings saved. Restart required for server changes.':'Settings saved');if(!wasSetupCompleted && data.settings?.interface?.setup_completed){try{window.open('/','_blank');}catch(_){}}await Promise.all([refresh(false),refreshVpilotInstall(),applyAirlineTheme()])}catch(error){$('hostSaveState').textContent=`SAVE FAILED: ${friendlyError(error.message)}`}
}
async function fetchOfp(buttons){buttons.forEach(b=>setBusy(b,true,'FETCHING...'));try{const result=await fetch('/api/simbrief/latest?force_refresh=true',{cache:'no-store'}).then(r=>r.json());$('hostSaveState').textContent=result.ok?'OFP LOADED':`OFP FAILED: ${friendlyError(result.reason||'UNKNOWN ERROR')}`;await Promise.all([refresh(false),refreshVpilotInstall()])}catch(error){$('hostSaveState').textContent=`OFP FAILED: ${friendlyError(error.message)}`}finally{buttons.forEach(b=>setBusy(b,false,'FETCH OFP'))}}

async function refreshSecurity(){try{const response=await fet('/api/security/status',{cache:'no-store'});const data=await response.json();if(!response.ok)throw new Error(data.detail||'Security status unavailable');$('hostPairingCode').value=data.enabled?data.pairing_code:'PAIRING OFF';$('hostSecurityState').textContent=data.enabled?'PAIRING REQUIRED':'PAIRING OFF';const items=data.devices||[];$('hostTrustedDevices').innerHTML=items.length?items.map(x=>`<div><b>${escapeHtml(x.name||'LAN DEVICE')}</b><span>${escapeHtml(x.address||'')}</span><small>LAST SEEN ${escapeHtml(String(x.last_seen_utc||'').replace('T',' ').slice(0,19))} UTC</small><button type="button" data-revoke-device="${escapeHtml(x.id)}">REVOKE</button></div>`).join(''):'<span>NO TRUSTED DEVICES</span>'}catch(error){$('hostTrustedDevices').innerHTML=`<span>${escapeHtml(friendlyError(error.message))}</span>`}}
async function rotatePairing(){const response=await fetch('/api/security/rotate',{method:'POST'});const data=await response.json();if(!response.ok)throw new Error(data.detail||'Pairing code could not be rotated');$('hostPairingCode').value=data.pairing_code;await refresh(false)}
async function revokeAllDevices(){if(!(await uiConfirm('Revoke every paired LAN device?', 'REVOKE')))return;await fetch('/api/security/devices',{method:'DELETE'});await refreshSecurity()}
async function refreshVpilotInstall(){
  try{
    const response=await fet('/api/vpilot/install/status',{cache:'no-store'});const data=await response.json();if(!response.ok)throw new Error(data.detail||`HTTP ${response.status}`);
    $('hostVpilotInstallState').textContent=data.installed?'BRIDGE INSTALLED':data.api_found?'READY TO INSTALL':'VPILOT NOT FOUND';
    $('hostVpilotInstallDetail').innerHTML=`<b>${escapeHtml(data.vpilot_root||'NO PATH')}</b><span>API: ${data.api_found?'FOUND':'NOT FOUND'} / PLUGIN: ${data.installed?'INSTALLED':'NOT INSTALLED'}${data.vpilot_running?' / VPILOT RUNNING':''}</span>`;
    $('hostRemoveVpilot').disabled=!data.installed;
  }catch(error){$('hostVpilotInstallState').textContent='CHECK FAILED';$('hostVpilotInstallDetail').textContent=friendlyError(error.message)}
}
async function installVpilotBridge(){
  setBusy($('hostInstallVpilot'),true,'INSTALLING...');$('hostVpilotInstallState').textContent='BUILDING BRIDGE';
  try{const response=await fetch('/api/vpilot/install',{method:'POST'});const data=await response.json();if(!response.ok||!data.ok)throw new Error(data.reason||data.detail||`HTTP ${response.status}`);$('hostSaveState').textContent=data.message||'VPILOT BRIDGE INSTALLED'}catch(error){$('hostSaveState').textContent=`VPILOT INSTALL FAILED: ${friendlyError(error.message)}`}finally{setBusy($('hostInstallVpilot'),false,'INSTALL / UPDATE BRIDGE');await refreshVpilotInstall();await refresh(false)}
}
async function removeVpilotBridge(){
  setBusy($('hostRemoveVpilot'),true,'REMOVING...');
  try{const response=await fetch('/api/vpilot/install',{method:'DELETE'});const data=await response.json();if(!response.ok||!data.ok)throw new Error(data.reason||data.detail||`HTTP ${response.status}`);$('hostSaveState').textContent=data.message||'VPILOT BRIDGE REMOVED'}catch(error){$('hostSaveState').textContent=`REMOVE FAILED: ${friendlyError(error.message)}`}finally{setBusy($('hostRemoveVpilot'),false,'REMOVE BRIDGE');await refreshVpilotInstall();await refresh(false)}
}
document.querySelectorAll('[data-host-page]').forEach(button=>button.addEventListener('click',()=>showHostPage(button.dataset.hostPage)));
$('openSetup').addEventListener('click',()=>showHostPage('settings'));
$('toggleIp').addEventListener('click',()=>{hostIpVisible=!hostIpVisible;renderAddresses()});
$('hostRotatePairing').addEventListener('click',()=>rotatePairing().catch(error=>$('hostSaveState').textContent=friendlyError(error.message)));
$('hostRevokeDevices').addEventListener('click',revokeAllDevices);
$('hostTrustedDevices').addEventListener('click',async event=>{const button=event.target.closest('[data-revoke-device]');if(!button)return;await fetch(`/api/security/devices/${encodeURIComponent(button.dataset.revokeDevice)}`,{method:'DELETE'});await refreshSecurity()});
$('hostSettingsForm').addEventListener('submit',saveSettings);
$('hostReloadSettings').addEventListener('click',async()=>{try{await loadSettings();$('hostSaveState').textContent='RELOADED'}catch(error){$('hostSaveState').textContent=`LOAD FAILED: ${friendlyError(error.message)}`}});
$('hostProbeMsfs').addEventListener('click',()=>refresh(true)); $('hostSetupProbe').addEventListener('click',()=>refresh(true));
$('hostFetchOfp').addEventListener('click',()=>fetchOfp([$('hostFetchOfp'),$('hostSetupFetch')])); $('hostSetupFetch').addEventListener('click',()=>fetchOfp([$('hostFetchOfp'),$('hostSetupFetch')]));
$('hostInstallVpilot').addEventListener('click',installVpilotBridge);
$('hostRemoveVpilot').addEventListener('click',removeVpilotBridge); if($('hostSurfaceRescan'))$('hostSurfaceRescan').addEventListener('click',()=>refreshSurfaceStatus(true));
$('copyUrl').addEventListener('click',async()=>{if(!preferredUrl)return;try{await navigator.clipboard.writeText(preferredUrl);$('copyUrl').textContent='COPIED'}catch{window.prompt('Copy OPS ROOM address',preferredUrl)}setTimeout(()=>$('copyUrl').textContent='COPY LAN ADDRESS',1400)});if($('hostAirlineThemeIntensity'))$('hostAirlineThemeIntensity').addEventListener('input',()=>{if($('hostAirlineThemeIntensityLabel'))$('hostAirlineThemeIntensityLabel').textContent=`${$('hostAirlineThemeIntensity').value}%`});
async function boot(){applyAirlineTheme();tick();setInterval(tick,1000);showHostPage(location.hash==='#settings'?'settings':'status');try{await loadSettings()}catch(error){$('hostSaveState').textContent=`LOAD FAILED: ${friendlyError(error.message)}`}await Promise.all([refresh(false),refreshVpilotInstall(),refreshSecurity(),refreshSurfaceStatus(false)]);setInterval(()=>refresh(false),10000);setInterval(refreshVpilotInstall,15000);setInterval(refreshSecurity,15000)}
boot();
