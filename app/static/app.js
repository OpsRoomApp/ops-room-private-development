try{ if(new URLSearchParams(location.search).get('embedded')==='1') document.body.classList.add('embedded-board'); }catch{}
const FIDS_QUERY = new URLSearchParams(window.location.search);
const EMBEDDED_FIDS = FIDS_QUERY.get('embedded') === '1' || window.self !== window.top;
const REQUESTED_AIRPORT = String(FIDS_QUERY.get('airport') || '').toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 4);
const EMBEDDED_DESIGN_WIDTH = 1720;
const FEED_REFRESH_SECONDS = 15;

function applyEmbeddedFit() {
  if (!EMBEDDED_FIDS) return;
  document.body.classList.add('embedded-fids');
  const available = Math.max(320, document.documentElement.clientWidth);
  const scale = Math.min(1, available / EMBEDDED_DESIGN_WIDTH);
  const naturalHeight = Math.max(640, document.documentElement.clientHeight / scale);
  document.documentElement.style.setProperty('--embedded-fids-scale', scale.toFixed(4));
  document.documentElement.style.setProperty('--embedded-fids-board-height', `${Math.max(570, naturalHeight - 282)}px`);
}

const DEFAULT_SETTINGS = {
  theme: 'amber',
  customAccent: '#ffd044',
  animations: true,
  compact: false,
  atisFallback: true,
  textSize: 'large',
  streamerName: '',
  streamerLogo: '',
  upcomingMinutes: 120,
  previousMinutes: 60,
  animationRefreshSeconds: 30,
};

const state = {
  airport: null,
  airportName: '',
  options: [],
  board: null,
  weather: null,
  tab: 'departures',
  sideTab: 'vatsim',
  settings: loadSettings(),
  lastClockText: '',
  renderSeed: 1,
  schedulePhase: false,
  manualAirport: false,
  locationResolved: false,
  locationReason: '',
};

const $ = (id) => document.getElementById(id);
const FLAP_ALPHA = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 /-.:';
const FLAP_NUMERIC = '0123456789';
const FLAP_BLANK = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789     ';

function loadSettings() {
  try {
    const raw = JSON.parse(localStorage.getItem('vtb-settings') || '{}');
    delete raw.obs;
    if(raw.animationRefreshSeconds==null && raw.refreshSeconds!=null) raw.animationRefreshSeconds=raw.refreshSeconds;
    delete raw.refreshSeconds;
    return Object.assign({}, DEFAULT_SETTINGS, raw);
  } catch (_) {
    return Object.assign({}, DEFAULT_SETTINGS);
  }
}

function saveSettings() {
  localStorage.setItem('vtb-settings', JSON.stringify(state.settings));
  applySettings();
}

function applySettings() {
  document.body.classList.toggle('no-animations', !state.settings.animations);
  document.body.classList.toggle('compact', !!state.settings.compact);
  document.body.classList.toggle('animate', !!state.settings.animations);
  document.body.classList.toggle('stand-hidden', !standsAvailable());
  document.body.classList.remove('theme-white', 'theme-green', 'theme-orange', 'theme-custom', 'size-normal', 'size-large', 'size-xlarge');
  if (state.settings.theme && state.settings.theme !== 'amber') document.body.classList.add(`theme-${state.settings.theme}`);
  document.body.classList.add(`size-${state.settings.textSize || 'large'}`);

  if (state.settings.theme === 'custom') {
    const val = normalizeHex(state.settings.customAccent || DEFAULT_SETTINGS.customAccent);
    document.documentElement.style.setProperty('--accent', val);
    document.documentElement.style.setProperty('--accent-soft', hexToRgba(val, 0.18));
  } else {
    document.documentElement.style.removeProperty('--accent');
    document.documentElement.style.removeProperty('--accent-soft');
  }
  renderStreamerBrand();
}

function standsAvailable() {
  return !!state.board?.features?.stands_available;
}

function renderStreamerBrand() {
  const brand = $('streamerBrand');
  const nameEl = $('streamerName');
  const logoEl = $('streamerLogo');
  if (!brand || !nameEl || !logoEl) return;
  const name = (state.settings.streamerName || '').trim();
  const logo = (state.settings.streamerLogo || '').trim();
  nameEl.textContent = name;
  if (logo) {
    logoEl.src = logo;
    logoEl.style.display = '';
  } else {
    logoEl.removeAttribute('src');
    logoEl.style.display = 'none';
  }
  brand.classList.toggle('hidden', !name && !logo);
}

function normalizeHex(value) {
  let v = String(value || '').trim();
  if (!v.startsWith('#')) v = `#${v}`;
  if (/^#[0-9a-fA-F]{6}$/.test(v)) return v;
  return DEFAULT_SETTINGS.customAccent;
}

function hexToRgba(hex, alpha) {
  const h = normalizeHex(hex).slice(1);
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

function normalizeText(s, len) {
  let t = String(s ?? '').toUpperCase().replace(/[^A-Z0-9: /\-.]/g, ' ').replace(/\s+/g, ' ');
  if (len) {
    t = t.trim();
    if (t.length > len) return t.slice(0, len);
    return t.padEnd(len, ' ');
  }
  return t.trim();
}

function seededRandom(seed) {
  const x = Math.sin(seed * 12.9898) * 43758.5453;
  return x - Math.floor(x);
}

function randomFrom(set) {
  return set[Math.floor(Math.random() * set.length)] || ' ';
}

function initialFlapChar(finalChar, seed) {
  if (!state.settings.animations) return finalChar;
  if (finalChar === ' ') return randomFrom(FLAP_BLANK);
  const set = /[0-9]/.test(finalChar) ? FLAP_NUMERIC : FLAP_ALPHA;
  const idx = Math.floor(seededRandom(seed) * set.length) % set.length;
  return set[idx];
}

function flapHTML(text, opts = {}) {
  const size = opts.size || '';
  const len = opts.len || 0;
  const t = normalizeText(text || '', len || undefined) || (len ? ' '.repeat(len) : '---');
  const key = escapeHtml(t);
  const base = state.renderSeed + (opts.seed || 0) + t.length * 13;
  const staticMode = !!opts.static;
  const chars = [...t].map((ch, i) => {
    const blank = ch === ' ';
    const cls = `${blank ? 'flap-char blank' : 'flap-char'}${staticMode ? '' : ' pending'}`;
    const r1 = seededRandom(base + i * 31);
    const r2 = seededRandom(base + i * 47 + 99);
    // More realistic: fewer cycles, constant-ish mechanical rhythm, random per tile.
    const delay = (r1 * 0.22).toFixed(3);
    const frames = 3 + Math.floor(r2 * 5);       // 3-7 flips before settling
    const interval = 72 + Math.floor(seededRandom(base + i * 59) * 35); // 72-107 ms
    const startChar = staticMode ? ch : initialFlapChar(ch, base + i * 101);
    return `<span class="${cls}" data-final="${escapeHtml(ch)}" data-frames="${frames}" data-interval="${interval}" style="--delay:${delay}s"><span class="flap-face">${startChar === ' ' ? '&nbsp;' : escapeHtml(startChar)}</span></span>`;
  }).join('');
  return `<span class="flap-word ${size}" data-text="${key}">${chars}</span>`;
}

function animateFlaps(root = document) {
  const chars = [...root.querySelectorAll('.flap-char.pending')];
  if (!chars.length) return;
  if (!state.settings.animations || document.body.classList.contains('no-animations')) {
    chars.forEach(el => {
      const finalChar = el.dataset.final || ' ';
      const face = el.querySelector('.flap-face');
      if (face) face.innerHTML = finalChar === ' ' ? '&nbsp;' : escapeHtml(finalChar);
      el.classList.remove('pending', 'spin');
    });
    return;
  }

  chars.forEach((el) => {
    el.classList.remove('pending');
    const finalChar = el.dataset.final || ' ';
    const frames = Number(el.dataset.frames || 5);
    const interval = Number(el.dataset.interval || 88);
    const delayText = (el.style.getPropertyValue('--delay') || '0s').trim();
    const delayMs = Math.max(0, parseFloat(delayText) * 1000 || 0) + Math.random() * 55;
    const set = finalChar === ' ' ? FLAP_BLANK : /[0-9]/.test(finalChar) ? FLAP_NUMERIC : FLAP_ALPHA;
    const face = el.querySelector('.flap-face');
    if (!face) return;

    setTimeout(() => {
      el.classList.add('spin');
      let n = 0;
      const timer = setInterval(() => {
        n += 1;
        const nextChar = n >= frames ? finalChar : randomFrom(set);
        face.innerHTML = nextChar === ' ' ? '&nbsp;' : escapeHtml(nextChar);
        if (n >= frames) {
          clearInterval(timer);
          setTimeout(() => el.classList.remove('spin'), 55 + Math.random() * 55);
        }
      }, interval);
    }, delayMs);
  });
}

function hhmm(raw) {
  const s = String(raw || '').padStart(4, '0').slice(-4);
  if (!/^\d{4}$/.test(s)) return '---';
  return `${s.slice(0,2)}:${s.slice(2)}`;
}

function statusClass(s) {
  return String(s || '').toLowerCase().replace(/\s+/g, '-');
}

function rowTime(row) {
  if (row.direction === 'arrival') {
    if (row.eta_min === null || row.eta_min === undefined) return '---';
    const d = new Date(Date.now() + Number(row.eta_min) * 60000);
    return `${String(d.getUTCHours()).padStart(2,'0')}:${String(d.getUTCMinutes()).padStart(2,'0')}`;
  }
  return hhmm(row.deptime);
}

function procedureLabel(row) {
  const p = row.procedure || '---';
  return (!p || p === '---') ? '' : p;
}

async function api(path) {
  const res = await fetch(path, { cache: 'no-store' });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return await res.json();
}

function updateLocationButton(mode, reason = '') {
  const btn = $('detectLocationBtn');
  if (!btn) return;
  btn.classList.remove('connected', 'failed', 'checking');
  btn.title = reason || 'Read the user aircraft position from MSFS via SimConnect';
  if (mode === 'connected') {
    btn.textContent = 'MSFS CONNECTED';
    btn.classList.add('connected');
  } else if (mode === 'checking') {
    btn.textContent = 'CHECKING MSFS...';
    btn.classList.add('checking');
  } else if (mode === 'failed') {
    btn.textContent = 'RETRY MSFS';
    btn.classList.add('failed');
  } else {
    btn.textContent = 'MSFS LOCATION';
  }
}

async function loadOptions(query = '') {
  const data = await api(`/api/airport-options?q=${encodeURIComponent(query)}&limit=12`);
  state.options = data.items || [];
  if (!query) {
    state.locationResolved = data.source === 'simconnect';
    state.locationReason = data.reason || '';
    updateLocationButton(state.locationResolved ? 'connected' : 'failed', state.locationReason);
  }
  renderSuggestions();
  if (!state.airport && data.default_airport) {
    const found = state.options.find(x => x.ident === data.default_airport) || state.options[0];
    if (found) selectAirport(found, false, false);
  }
}

async function detectCurrentLocation({auto = false} = {}) {
  if (auto && (state.manualAirport || state.locationResolved)) return;
  updateLocationButton('checking');
  try {
    const data = await api('/api/current-location');
    if (!data.ok || !data.nearest_airport) {
      state.locationResolved = false;
      state.locationReason = data.reason || 'MSFS location unavailable';
      updateLocationButton('failed', state.locationReason);
      return;
    }
    state.locationResolved = true;
    state.manualAirport = false;
    state.locationReason = '';
    updateLocationButton('connected', data.label || 'MSFS location connected');
    selectAirport(data.nearest_airport, true, false);
  } catch (err) {
    state.locationResolved = false;
    state.locationReason = String(err.message || err);
    updateLocationButton('failed', state.locationReason);
  }
}

function renderSuggestions() {
  const box = $('airportSuggestions');
  const options = state.options || [];
  box.innerHTML = options.map(ap => {
    const meta = ap.source === 'current' ? 'CURRENT' : ap.distance_nm != null ? `${ap.distance_nm} NM` : ap.traffic_count ? `${ap.traffic_count} FLTS` : ap.source.toUpperCase();
    return `<button class="suggestion" data-icao="${escapeHtml(ap.ident)}"><span class="suggestion-code">${escapeHtml(ap.ident)}</span><span class="suggestion-name">${escapeHtml(ap.name)}</span><span class="suggestion-meta">${escapeHtml(meta)}</span></button>`;
  }).join('');
  box.classList.toggle('open', options.length > 0 && document.activeElement === $('airportIcaoInput'));
  [...box.querySelectorAll('button')].forEach(btn => {
    btn.addEventListener('mousedown', ev => {
      ev.preventDefault();
      const ap = state.options.find(x => x.ident === btn.dataset.icao);
      if (ap) selectAirport(ap, true, true);
    });
  });
}

function selectAirport(ap, load = true, manual = true) {
  if (!ap) return;
  state.airport = ap.ident;
  state.airportName = ap.name || ap.ident;
  if (manual) state.manualAirport = true;
  $('airportIcaoInput').value = ap.ident;
  $('airportNameBadge').textContent = ap.name || ap.ident;
  $('airportSuggestions').classList.remove('open');
  if (load) refreshAll(true);
}

async function refreshAll(force = false) {
  if (!state.airport) return;
  try {
    const forceParam = force ? '&force_refresh=true' : '';
    const [board, weather] = await Promise.all([
      api(`/api/board?airport=${encodeURIComponent(state.airport)}&upcoming_minutes=${Number(state.settings.upcomingMinutes||120)}&previous_minutes=${Number(state.settings.previousMinutes||60)}${forceParam}`),
      api(`/api/weather/${encodeURIComponent(state.airport)}${force ? '?force_refresh=true' : ''}`),
    ]);
    state.renderSeed = Date.now() % 100000;
    state.board = board;
    state.weather = weather;
    state.airportName = board.airport?.name || state.airportName;
    $('airportNameBadge').textContent = state.airportName;
    renderAll();
  } catch (err) {
    console.error(err);
    $('airportNameFlap').innerHTML = flapHTML('UNABLE TO LOAD BOARD', {size:'airport-name', len:34, seed:666, static:true});
    $('metarLine').textContent = String(err.message || err);
  }
}

function classifyAtisKind(callsign='') {
  const c = String(callsign || '').toUpperCase();
  if (c.includes('_D_') || c.includes('_DEP')) return 'DEP';
  if (c.includes('_A_') || c.includes('_ARR')) return 'ARR';
  return 'ALL';
}

function parseAtisSummaries() {
  const entries = [];
  for (const a of (state.board?.atis || [])) {
    entries.push({kind: classifyAtisKind(a.callsign), source: 'VATSIM', code: a.atis_code || a.analysis?.atis_code || null, analysis: a.analysis || {}, callsign: a.callsign || ''});
  }
  if (!entries.length && state.settings.atisFallback && state.weather?.realworld_atis?.ok) {
    const rw = state.weather.realworld_atis;
    entries.push({kind:'ALL', source: rw.generated ? 'METAR' : 'REAL', code: rw.atis_code, analysis: {runways: rw.runways || [], qnh: rw.qnh || null, visibility: rw.visibility || null}});
  }
  const byKind = {DEP:null, ARR:null, ALL:null};
  for (const e of entries) {
    if (!byKind[e.kind]) byKind[e.kind] = e;
    if (!byKind.ALL) byKind.ALL = e;
  }
  return byKind;
}

function atisLine(entry) {
  if (!entry) return 'INFO ---   RWY IN USE ---   QNH ---   VISIBILITY ---';
  const info = entry.code ? `INFO ${entry.code}` : 'INFO ---';
  const rw = entry.analysis?.runways?.length ? entry.analysis.runways.slice(0, 4).join(' / ') : '---';
  const qnh = entry.analysis?.qnh || state.weather?.metar?.qnh || '---';
  const visibility = entry.analysis?.visibility || state.weather?.metar?.visibility || '---';
  return `${info}   RWY IN USE ${rw}   QNH ${qnh}   VISIBILITY ${visibility}`;
}

function bestRunwaysAndQnh() {
  const byKind = parseAtisSummaries();
  const best = byKind.ALL || byKind.DEP || byKind.ARR;
  return {
    runways: best?.analysis?.runways || [],
    qnh: best?.analysis?.qnh || state.weather?.metar?.qnh || null,
    visibility: best?.analysis?.visibility || state.weather?.metar?.visibility || null,
    info: best?.code || null,
    source: best?.source || 'NONE',
    sourceTab: best?.source === 'VATSIM' ? 'vatsim' : 'realworld'
  };
}

function renderHeader() {
  const airport = state.board?.airport || { ident: state.airport || '----', name: state.airportName || '' };
  $('airportCodeFlap').innerHTML = flapHTML(airport.ident || '----', { size:'big', len:4, seed:100 });
  // Keep v0.9 tile styling; only place the name left under ICAO and allow more blocks.
  $('airportNameFlap').innerHTML = flapHTML(airport.name || 'UNKNOWN AIRPORT', { size:'airport-name', len:54, seed:120, static:true });
  const metar = state.weather?.metar;
  $('metarLine').textContent = metar?.raw || metar?.error || 'No METAR';

  const byKind = parseAtisSummaries();
  const best = byKind.ALL || byKind.DEP || byKind.ARR;
  $('atisSourceLine').textContent = best ? `${best.source} ATIS` : 'ATIS SUMMARY';
  $('atisDepLine').textContent = atisLine(byKind.DEP || byKind.ALL);
  $('atisArrLine').textContent = atisLine(byKind.ARR || byKind.ALL);

  $('depCount').textContent = state.board?.counts?.departures ?? 0;
  $('arrCount').textContent = state.board?.counts?.arrivals ?? 0;
  $('preCount').textContent = state.board?.counts?.prefiles ?? 0;
}

function renderClock(force = false) {
  const d = new Date();
  const txt = `${String(d.getUTCHours()).padStart(2,'0')}:${String(d.getUTCMinutes()).padStart(2,'0')}Z`;
  if (!force && txt === state.lastClockText) return;
  state.lastClockText = txt;
  // Clock is intentionally static: it changes only when UTC minute changes, without traffic-board cycling.
  $('clockFlap').innerHTML = flapHTML(txt, { size:'clock', len:6, seed:900, static:true });
}

function logoCell(row) {
  const name = row.airline?.name || row.airline?.code || 'Unknown operator';
  const code = row.airline?.code || 'GEN';
  const logo = row.airline?.logo_url ? `<img class="logo" src="${escapeHtml(row.airline.logo_url)}" alt="${escapeHtml(code)}" />` : `<span class="logo-fallback">${escapeHtml(code)}</span>`;
  return `<td class="logo-cell"><div class="logo-wrap" title="${escapeHtml(name)}" aria-label="${escapeHtml(name)}">${logo}</div></td>`;
}

function standCell(row) {
  return standsAvailable() ? `<td class="stand-col">${flapHTML(row.stand || '', { size:'small', len:5, seed:250 })}</td>` : '';
}

function displayStatus(status) {
  const s = String(status || '').toLowerCase();
  if (s.includes('push')) return 'PUSH';
  if (s.includes('board') && !s.includes('deboard')) return 'BOARDING';
  if (s.includes('deboard')) return 'DEBOARD';
  if (s.includes('stand') || s.includes('gate') || s.includes('park')) return 'PARKED';
  if (s.includes('taxi in')) return 'TAXI IN';
  if (s.includes('taxi')) return 'TAXI';
  if (s.includes('take')) return 'TAKEOFF';
  if (s.includes('final')) return 'FINAL';
  if (s.includes('roll')) return 'ROLLOUT';
  if (s.includes('desc')) return 'DESCENT';
  if (s.includes('approach')) return 'APPROACH';
  if (s.includes('climb')) return 'CLIMBING';
  if (s.includes('departed')) return 'DEPARTED';
  if (s.includes('airborne')) return 'ENROUTE';
  if (s.includes('enroute')) return 'ENROUTE';
  if (s.includes('prefiled')) return 'FILED';
  return String(status || '').toUpperCase().slice(0, 10) || '---';
}


function formatScheduleDuration(minutes) {
  const total = Math.max(0, Math.abs(Math.trunc(Number(minutes) || 0)));
  const hours = Math.floor(total / 60);
  const mins = total % 60;
  if (hours <= 0) return `${Math.min(total, 99)}M`;
  if (hours < 10) return `${hours}H${String(mins).padStart(2, '0')}M`;
  const hh = String(Math.min(hours, 99)).padStart(2, '0');
  return `${hh}H${String(mins).padStart(2, '0')}`;
}

function scheduleTimingStatus(row) {
  if (row.direction !== 'departure' || row.prefile) return null;
  if (row.schedule_delta_min === null || row.schedule_delta_min === undefined) return null;
  const delta = Math.trunc(Number(row.schedule_delta_min));
  if (!Number.isFinite(delta) || delta <= 0) return null;
  let delayText = '';
  if (delta < 100) {
    delayText = `DELAYED${delta}M`;
  } else {
    delayText = `DELAY${formatScheduleDuration(delta)}`;
  }
  return { text: delayText, kind: 'delayed' };
}

function statusCell(row, seed) {
  const operational = displayStatus(row.status);
  const timing = scheduleTimingStatus(row);
  const showTiming = !!timing && state.schedulePhase;
  const text = showTiming ? timing.text : operational;
  const kind = showTiming ? timing.kind : 'operational';
  const length = 10;
  const scheduleText = timing?.text || '';
  const scheduleKind = timing?.kind || '';
  return `<td class="schedule-status-cell show-${escapeHtml(kind)}" data-operational="${escapeHtml(operational)}" data-timing="${escapeHtml(scheduleText)}" data-timing-kind="${escapeHtml(scheduleKind)}" data-current="${escapeHtml(text)}" data-seed="${seed}">${flapHTML(text, { size:'tiny status-flap', len:length, seed })}</td>`;
}

function updateScheduleStatusCells() {
  document.querySelectorAll('.schedule-status-cell').forEach(cell => {
    const timing = cell.dataset.timing || '';
    const operational = cell.dataset.operational || '---';
    const showTiming = state.schedulePhase && !!timing;
    const nextText = showTiming ? timing : operational;
    if (cell.dataset.current === nextText) return;

    cell.dataset.current = nextText;
    cell.classList.remove('show-operational', 'show-delayed');
    const kind = showTiming ? 'delayed' : 'operational';
    cell.classList.add(`show-${kind}`);
    const seed = Number(cell.dataset.seed || 0) + state.renderSeed;
    cell.innerHTML = flapHTML(nextText, {
      size: 'tiny status-flap',
      len: 10,
      seed,
    });
    animateFlaps(cell);
  });
}

function rowHTML(row, idx = 0) {
  const seed = idx * 1000 + (row.callsign || '').split('').reduce((a,c)=>a+c.charCodeAt(0),0);
  if (state.tab === 'departures') {
    return `<tr class="data-row${row.is_user ? ' user-flight-row' : ''}" data-callsign="${escapeHtml(row.callsign||'')}" data-lat="${escapeHtml(row.latitude ?? '')}" data-lon="${escapeHtml(row.longitude ?? '')}" data-alt="${escapeHtml(row.altitude ?? '')}">
      ${logoCell(row)}
      <td class="flight-col">${flapHTML(row.callsign, { size:'small', len:8, seed })}</td>
      <td>${flapHTML(row.aircraft || '', { size:'small', len:4, seed:seed+1 })}</td>
      <td>${flapHTML(row.arrival || '', { size:'small', len:4, seed:seed+2 })}</td>
      <td>${flapHTML(rowTime(row), { size:'small', len:5, seed:seed+3 })}</td>
      <td>${flapHTML(procedureLabel(row), { size:'small', len:8, seed:seed+4 })}</td>
      ${standCell(row)}
      ${statusCell(row, seed+9)}
    </tr>`;
  }
  if (state.tab === 'arrivals') {
    return `<tr class="data-row${row.is_user ? ' user-flight-row' : ''}" data-callsign="${escapeHtml(row.callsign||'')}" data-lat="${escapeHtml(row.latitude ?? '')}" data-lon="${escapeHtml(row.longitude ?? '')}" data-alt="${escapeHtml(row.altitude ?? '')}">
      ${logoCell(row)}
      <td class="flight-col">${flapHTML(row.callsign, { size:'small', len:8, seed })}</td>
      <td>${flapHTML(row.aircraft || '', { size:'small', len:4, seed:seed+1 })}</td>
      <td>${flapHTML(row.departure || '', { size:'small', len:4, seed:seed+2 })}</td>
      <td>${flapHTML(rowTime(row), { size:'small', len:5, seed:seed+3 })}</td>
      <td>${flapHTML(procedureLabel(row), { size:'small', len:8, seed:seed+4 })}</td>
      ${standCell(row)}
      <td>${flapHTML(row.distance_nm != null ? `${row.distance_nm}` : '', { size:'tiny', len:5, seed:seed+5 })}</td>
      ${statusCell(row, seed+9)}
    </tr>`;
  }
  return `<tr class="data-row${row.is_user ? ' user-flight-row' : ''}" data-callsign="${escapeHtml(row.callsign||'')}" data-lat="${escapeHtml(row.latitude ?? '')}" data-lon="${escapeHtml(row.longitude ?? '')}" data-alt="${escapeHtml(row.altitude ?? '')}">
    ${logoCell(row)}
    <td class="flight-col">${flapHTML(row.callsign, { size:'small', len:8, seed })}</td>
    <td>${flapHTML(row.aircraft || '', { size:'small', len:4, seed:seed+1 })}</td>
    <td>${flapHTML(row.direction === 'departure' ? 'DEP' : 'ARR', { size:'small', len:3, seed:seed+2 })}</td>
    <td>${flapHTML(row.departure || '', { size:'small', len:4, seed:seed+3 })}</td>
    <td>${flapHTML(row.arrival || '', { size:'small', len:4, seed:seed+4 })}</td>
    <td>${flapHTML(hhmm(row.deptime), { size:'small', len:5, seed:seed+5 })}</td>
    <td>${flapHTML(procedureLabel(row), { size:'small', len:8, seed:seed+6 })}</td>
  </tr>`;
}

function renderTraffic() {
  const body = $('trafficBody');
  const head = $('trafficHead');
  let rows = state.board?.[state.tab] || [];
  const standH = standsAvailable() ? '<th class="stand-col">Stand</th>' : '';
  if (state.tab === 'departures') {
    $('tableTitle').textContent = 'Departures';
    head.innerHTML = `<tr><th>Airline</th><th>Flight</th><th>Type</th><th>To</th><th>Time</th><th>SID</th>${standH}<th>Status</th></tr>`;
  } else if (state.tab === 'arrivals') {
    $('tableTitle').textContent = 'Arrivals';
    head.innerHTML = `<tr><th>Airline</th><th>Flight</th><th>Type</th><th>From</th><th>ETA</th><th>STAR</th>${standH}<th>NM</th><th>Status</th></tr>`;
  } else {
    $('tableTitle').textContent = 'Prefiles';
    head.innerHTML = `<tr><th>Airline</th><th>Flight</th><th>Type</th><th>Dir</th><th>From</th><th>To</th><th>Time</th><th>SID/STAR</th></tr>`;
  }
  if (!rows.length) {
    body.innerHTML = `<tr class="data-row no-traffic"><td colspan="9">${flapHTML('NO TRAFFIC', { size:'small', len:16, seed:777 })}</td></tr>`;
  } else {
    body.innerHTML = rows.map((row, idx) => rowHTML(row, idx)).join('');
  }
  requestAnimationFrame(() => animateFlaps(body));
  [...body.querySelectorAll('tr.data-row')].forEach(tr => {
    tr.addEventListener('click', async () => {
      body.querySelectorAll('tr.data-row').forEach(r => r.classList.remove('selected-camera-row'));
      tr.classList.add('selected-camera-row');
      const payload = {
        callsign: tr.dataset.callsign || '',
        airport: state.airport || '',
        source: 'vatsim-fids',
        label: tr.dataset.callsign || '',
        latitude: Number(tr.dataset.lat || 0),
        longitude: Number(tr.dataset.lon || 0),
        altitude: Number(tr.dataset.alt || 0),
        tab: state.tab
      };
      try {
        const response = await fetch('/api/camera/target', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify(payload)
        });
        const data = await response.json().catch(() => ({}));
        const status = document.getElementById('cameraTargetStatus');
        const bridge = data && typeof data === 'object' ? (data.bridge || {}) : {};
        if(status){
          let message = `WATCH TARGET ${payload.callsign || 'SELECTED'} SENT`;
          if(bridge && bridge.available === false){
            message += ' / BRIDGE NOT INSTALLED';
          }else if(bridge && bridge.running){
            message += ' / BRIDGE READY';
          }else if(bridge && bridge.status && bridge.status.loaded){
            message += ' / WASM READY';
          }else if(bridge && bridge.status && bridge.status.simconnect_connected){
            message += ' / BRIDGE: WAITING WASM';
          }else if(bridge && bridge.status && bridge.status.state){
            message += ` / BRIDGE: ${String(bridge.status.state).toUpperCase()}`;
          }else if(bridge && bridge.message){
            const raw=String(bridge.message).toUpperCase();
            message += raw.includes('WAITING') ? ' / BRIDGE: WAITING WASM' : ` / ${raw.slice(0,48)}`;
          }
          status.textContent = message;
        }
      } catch(e) {
        console.warn('Camera target update failed', e);
      }
    });
  });
}


async function releaseCameraTarget() {
  try {
    const response = await fetch('/api/camera/release', { method:'POST' });
    await response.json().catch(() => ({}));
    const status = document.getElementById('cameraTargetStatus');
    if (status) status.textContent = 'CAMERA RELEASED TO USER AIRCRAFT / CLICK A FLIGHT TO WATCH';
    document.querySelectorAll('tr.data-row').forEach(r => r.classList.remove('selected-camera-row'));
  } catch(e) {
    console.warn('Camera release failed', e);
  }
}

function atisCard(a, kind='vatsim') {
  const text = Array.isArray(a.text_atis) ? a.text_atis.join('\n') : a.text || '';
  const analysis = a.analysis || { runways: a.runways || [], qnh: a.qnh };
  const runways = analysis.runways?.length ? analysis.runways.join(' / ') : '---';
  const qnh = analysis.qnh || '---';
  return `<div class="card">
    <strong>${escapeHtml(a.callsign || a.source || kind.toUpperCase())}</strong>
    ${a.frequency ? `<div class="freq">${escapeHtml(a.frequency)}</div>` : ''}
    ${a.atis_code ? `<div class="key-info">INFO ${escapeHtml(a.atis_code)}</div>` : ''}
    <div class="info-grid"><div class="info-tile"><span>RWY</span><strong>${escapeHtml(runways)}</strong></div><div class="info-tile"><span>QNH</span><strong>${escapeHtml(qnh)}</strong></div></div>
    <div class="atis-text">${escapeHtml(text || 'No station text available.')}</div>
  </div>`;
}

function renderSettings() {
  const customRows = state.settings.theme === 'custom' ? '' : ' hidden';
  return `<div class="card settings-card">
    <div class="setting-row"><label>Colour scheme</label><select id="setTheme"><option value="amber">Amber classic</option><option value="white">White Frankfurt</option><option value="green">Green terminal</option><option value="orange">Orange streamer</option><option value="custom">Custom colour</option></select></div>
    <div class="setting-row custom-colour-row${customRows}"><label>Custom colour</label><input id="setCustomColor" type="color" value="${escapeHtml(normalizeHex(state.settings.customAccent))}"></div>
    <div class="setting-row custom-colour-row${customRows}"><label>Hex code</label><input id="setCustomHex" class="text-setting" maxlength="7" value="${escapeHtml(normalizeHex(state.settings.customAccent))}"></div>
    <div class="setting-row"><label>Board text size</label><select id="setTextSize"><option value="normal">Normal</option><option value="large">Large</option><option value="xlarge">Extra large</option></select></div>
    <div class="setting-row"><label>Split-flap animations</label><input id="setAnimations" type="checkbox"></div>
    <div class="setting-row"><label>VATSIM data refresh</label><strong class="setting-readonly">15 seconds (fixed)</strong></div>
    <div class="setting-row"><label>Animation refresh</label><select id="setAnimationRefreshSeconds"><option value="15">15 seconds</option><option value="30">30 seconds</option><option value="45">45 seconds</option><option value="60">60 seconds</option><option value="90">90 seconds</option><option value="120">120 seconds</option></select></div>
    <div class="setting-row"><label>Upcoming traffic window</label><select id="setUpcomingMinutes"><option value="60">1 hour</option><option value="120">2 hours</option><option value="180">3 hours</option><option value="240">4 hours</option><option value="360">6 hours</option></select></div>
    <div class="setting-row"><label>Previous traffic window</label><select id="setPreviousMinutes"><option value="0">None</option><option value="30">30 minutes</option><option value="60">1 hour</option><option value="90">90 minutes</option><option value="120">2 hours</option></select></div>
    <div class="setting-row"><label>Real ATIS fallback</label><input id="setFallback" type="checkbox"></div>
    <div class="setting-row"><label>Streamer name</label><input id="setStreamerName" class="text-setting" placeholder="e.g. Nishant Aviation" value="${escapeHtml(state.settings.streamerName || '')}"></div>
    <div class="setting-row"><label>Streamer logo URL</label><input id="setStreamerLogo" class="text-setting" placeholder="https://... or data image" value="${escapeHtml(state.settings.streamerLogo || '')}"></div>
    <div class="setting-row"><label>Upload logo locally</label><input id="setStreamerLogoFile" type="file" accept="image/*"></div>
    <div class="setting-actions"><button id="resetSettings" class="secondary-button">Reset settings</button></div>
  </div>`;
}

const cameraBridgeViewDefaults={mode:'tail_follow',distance:45,height:9,sideOffset:0,pitch:-7,orbitAngle:180,smoothing:0.35};
let cameraBridgeViewState={...cameraBridgeViewDefaults};
let cameraBridgeSaveTimer=null;
function cameraBridgeStateLabel(data){
  const status=data?.status||{};const running=!!(data?.running||status.running);
  return String(status.state||status.camera_state||status.phase||(running?'RUNNING':(data?.available===false?'NOT FOUND':'STOPPED'))).toUpperCase();
}
function cameraBridgeTargetName(data){const status=data?.status||{};return status.target||data?.target?.callsign||'none'}
function renderCameraBridgeStatusBox(data){
  const box=$('fidsCameraBridgeBox');if(!box)return;
  const status=data?.status||{};const running=!!(data?.running||status.running);const state=cameraBridgeStateLabel(data);
  const top=$('fidsCameraBridgeState');if(top)top.textContent=state;
  box.className=`camera-bridge-status-box ${data?.available===false?'fault':running?'ready':'waiting'}`;
  const target=cameraBridgeTargetName(data);const match=status.match||'none';const mode=status.mode||data?.target?.view?.mode||cameraBridgeViewState.mode;
  box.innerHTML=`<b>MSFS 2024 NATIVE CAMERA FOLLOW</b><p>${escapeHtml(data?.message||status.message||'Select an aircraft in FIDS, then tune the camera view here.')}</p><p>Bridge: ${data?.available===false?'not found':'installed'} · WASM: ${running?'active':'waiting'} · Target: ${escapeHtml(target)} · Match: ${escapeHtml(match)} · Mode: ${escapeHtml(String(mode).replaceAll('_',' ').toUpperCase())}</p>`;
}
async function refreshCameraBridgePanel(){
  if(!$('fidsCameraBridgeBox'))return;
  try{const data=await api('/api/camera/bridge/status');renderCameraBridgeStatusBox(data);if(data?.target?.view)syncFidsCameraControls(data.target.view)}
  catch{const box=$('fidsCameraBridgeBox');if(box){box.className='camera-bridge-status-box fault';box.innerHTML='<b>NATIVE WASM CAMERA</b><p>Status unavailable.</p>'}const state=$('fidsCameraBridgeState');if(state)state.textContent='FAULT'}
}
function readFidsCameraControls(){
  const read=(name,fallback)=>{const el=document.querySelector(`[data-fids-camera-control="${name}"]`);const v=el?Number(el.value):Number(fallback);return Number.isFinite(v)?v:fallback};
  return {mode:cameraBridgeViewState.mode,distance:read('distance',cameraBridgeViewState.distance),height:read('height',cameraBridgeViewState.height),sideOffset:read('sideOffset',cameraBridgeViewState.sideOffset),pitch:read('pitch',cameraBridgeViewState.pitch),orbitAngle:read('orbitAngle',cameraBridgeViewState.orbitAngle),smoothing:read('smoothing',cameraBridgeViewState.smoothing)};
}
function syncFidsCameraControls(view){
  cameraBridgeViewState={...cameraBridgeViewState,...(view||{})};
  document.querySelectorAll('[data-fids-camera-mode]').forEach(button=>{const active=button.dataset.fidsCameraMode===cameraBridgeViewState.mode;button.classList.toggle('primary-control',active);button.setAttribute('aria-pressed',active?'true':'false')});
  Object.entries(cameraBridgeViewState).forEach(([key,value])=>{const el=document.querySelector(`[data-fids-camera-control="${key}"]`);if(el&&String(el.value)!==String(value))el.value=value});
}
async function sendFidsCameraViewNow(){
  cameraBridgeViewState=readFidsCameraControls();
  try{const data=await api('/api/camera/view',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cameraBridgeViewState)});if(data?.target?.view)syncFidsCameraControls(data.target.view);await refreshCameraBridgePanel()}catch(error){console.warn('Camera view update failed',error)}
}
function scheduleFidsCameraViewUpdate(){clearTimeout(cameraBridgeSaveTimer);cameraBridgeSaveTimer=setTimeout(sendFidsCameraViewNow,180)}
async function showFidsCameraLog(){
  const box=$('fidsCameraBridgeLogText');if(!box)return;
  try{const data=await api('/api/camera/bridge/log?lines=180');box.hidden=!box.hidden;box.textContent=(data.lines||[]).join('\n')||'No camera bridge log yet.'}
  catch{box.hidden=false;box.textContent='Camera Bridge log unavailable.'}
}
function renderCameraBridge(){
  return `<div class="fids-camera-full-panel">
    <div class="fids-camera-status-head"><div><span>MSFS 2024</span><b>NATIVE WASM CAMERA</b></div><strong id="fidsCameraBridgeState">CHECKING</strong></div>
    <div id="fidsCameraBridgeBox" class="camera-bridge-status-box"><b>MSFS 2024 NATIVE CAMERA FOLLOW</b><p>Select aircraft in FIDS, then tune the view here.</p></div>
    <div class="fids-camera-mode-grid" aria-label="Camera mode">
      <button class="secondary-button primary-control" type="button" data-fids-camera-mode="tail_follow">TAIL FOLLOW</button>
      <button class="secondary-button" type="button" data-fids-camera-mode="left_spotter">LEFT SPOTTER</button>
      <button class="secondary-button" type="button" data-fids-camera-mode="right_spotter">RIGHT SPOTTER</button>
      <button class="secondary-button" type="button" data-fids-camera-mode="front_34">FRONT 3/4</button>
      <button class="secondary-button" type="button" data-fids-camera-mode="tower_static">TOWER STATIC</button>
      <button class="secondary-button" type="button" data-fids-camera-mode="orbit">ORBIT</button>
    </div>
    <div class="fids-camera-slider-grid">
      <label>DISTANCE <input data-fids-camera-control="distance" type="range" min="5" max="300" step="1" value="45"></label>
      <label>HEIGHT <input data-fids-camera-control="height" type="range" min="-10" max="120" step="1" value="9"></label>
      <label>SIDE OFFSET <input data-fids-camera-control="sideOffset" type="range" min="-160" max="160" step="1" value="0"></label>
      <label>PITCH <input data-fids-camera-control="pitch" type="range" min="-45" max="20" step="1" value="-7"></label>
      <label>ORBIT ANGLE <input data-fids-camera-control="orbitAngle" type="range" min="0" max="360" step="1" value="180"></label>
      <label>SMOOTHING <input data-fids-camera-control="smoothing" type="range" min="0" max="0.98" step="0.01" value="0.35"></label>
    </div>
    <div class="fids-camera-actions">
      <button id="fidsCameraStart" class="secondary-button primary-control" type="button">START</button>
      <button id="fidsCameraRelease" class="secondary-button danger" type="button">RELEASE</button>
      <button id="fidsCameraReset" class="secondary-button" type="button">RESET</button>
      <button id="fidsCameraRecenter" class="secondary-button" type="button">RECENTER</button>
      <button id="fidsCameraRefresh" class="secondary-button" type="button">REFRESH</button>
      <button id="fidsCameraLog" class="secondary-button" type="button">LOG</button>
    </div>
    <pre id="fidsCameraBridgeLogText" class="fids-camera-log" hidden></pre>
  </div>`;
}
function wireFidsCameraBridgeControls(){
  document.querySelectorAll('[data-fids-camera-mode]').forEach(button=>button.addEventListener('click',()=>{cameraBridgeViewState.mode=button.dataset.fidsCameraMode||'tail_follow';syncFidsCameraControls(cameraBridgeViewState);scheduleFidsCameraViewUpdate()}));
  document.querySelectorAll('[data-fids-camera-control]').forEach(input=>input.addEventListener('input',()=>{cameraBridgeViewState=readFidsCameraControls();scheduleFidsCameraViewUpdate()}));
  $('fidsCameraStart')?.addEventListener('click',async()=>{try{await api('/api/camera/bridge/start',{method:'POST'})}catch{}refreshCameraBridgePanel()});
  $('fidsCameraRelease')?.addEventListener('click',async()=>{try{await api('/api/camera/bridge/release',{method:'POST'})}catch{}refreshCameraBridgePanel()});
  $('fidsCameraReset')?.addEventListener('click',async()=>{cameraBridgeViewState={...cameraBridgeViewDefaults};syncFidsCameraControls(cameraBridgeViewState);try{await api('/api/camera/reset-view',{method:'POST'})}catch{}refreshCameraBridgePanel()});
  $('fidsCameraRecenter')?.addEventListener('click',()=>{cameraBridgeViewState.sideOffset=0;cameraBridgeViewState.orbitAngle=180;syncFidsCameraControls(cameraBridgeViewState);sendFidsCameraViewNow()});
  $('fidsCameraRefresh')?.addEventListener('click',refreshCameraBridgePanel);
  $('fidsCameraLog')?.addEventListener('click',showFidsCameraLog);
  syncFidsCameraControls(cameraBridgeViewState);
}
function renderStandaloneCameraPanel(){
  const panel=$('standaloneCameraPanel'),content=$('standaloneCameraPanelContent');
  if(!panel||!content)return;
  content.innerHTML=renderCameraBridge();
  wireFidsCameraBridgeControls();
  refreshCameraBridgePanel();
}
function showStandaloneCameraPanel(){
  const panel=$('standaloneCameraPanel');
  if(!panel)return;
  renderStandaloneCameraPanel();
  panel.classList.remove('hidden');
}
function hideStandaloneCameraPanel(){
  const panel=$('standaloneCameraPanel');
  if(panel)panel.classList.add('hidden');
}

function renderSide() {
  const box = $('sideContent');
  if (state.sideTab === 'camera') {
    box.innerHTML = `<div class="card settings-card camera-bridge-card"><strong>CAMERA BRIDGE</strong><p class="camera-bridge-note">The full Camera Bridge control panel is opened on the board. It uses the same OPS ROOM backend and does not start a duplicate bridge process.</p><div class="setting-actions"><button id="sideOpenCameraPanel" class="secondary-button" type="button">Open Camera Panel</button></div></div>`;
    $('sideOpenCameraPanel')?.addEventListener('click', showStandaloneCameraPanel);
    showStandaloneCameraPanel();
    return;
  }
  if (state.sideTab === 'settings') {
    box.innerHTML = renderSettings();
    $('setTheme').value = state.settings.theme;
    $('setTextSize').value = state.settings.textSize || 'large';
    $('setAnimations').checked = !!state.settings.animations;
    $('setAnimationRefreshSeconds').value = String(state.settings.animationRefreshSeconds || 30);
    $('setUpcomingMinutes').value = String(state.settings.upcomingMinutes || 120);
    $('setPreviousMinutes').value = String(state.settings.previousMinutes ?? 60);
    $('setFallback').checked = !!state.settings.atisFallback;
    $('setTheme').onchange = e => { state.settings.theme = e.target.value; saveSettings(); renderSide(); };
    $('setCustomColor').oninput = e => { state.settings.customAccent = normalizeHex(e.target.value); saveSettings(); const hex = $('setCustomHex'); if (hex) hex.value = state.settings.customAccent; };
    $('setCustomHex').onchange = e => { state.settings.customAccent = normalizeHex(e.target.value); saveSettings(); renderSide(); };
    $('setTextSize').onchange = e => { state.settings.textSize = e.target.value; saveSettings(); renderAll(); };
    $('setAnimations').onchange = e => { state.settings.animations = e.target.checked; saveSettings(); renderAll(); };
    $('setAnimationRefreshSeconds').onchange = e => { state.settings.animationRefreshSeconds = Number(e.target.value); saveSettings(); scheduleAnimationRefresh(); };
    $('setUpcomingMinutes').onchange = e => { state.settings.upcomingMinutes = Number(e.target.value); saveSettings(); refreshAll(true); };
    $('setPreviousMinutes').onchange = e => { state.settings.previousMinutes = Number(e.target.value); saveSettings(); refreshAll(true); };
    $('setFallback').onchange = e => { state.settings.atisFallback = e.target.checked; saveSettings(); renderAll(); };
    $('setStreamerName').onchange = e => { state.settings.streamerName = e.target.value; saveSettings(); };
    $('setStreamerLogo').onchange = e => { state.settings.streamerLogo = e.target.value; saveSettings(); };
    $('setStreamerLogoFile').onchange = e => {
      const file = e.target.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => { state.settings.streamerLogo = String(reader.result || ''); saveSettings(); renderSide(); };
      reader.readAsDataURL(file);
    };
    $('resetSettings').onclick = () => { state.settings = Object.assign({}, DEFAULT_SETTINGS); saveSettings(); renderAll(); };
    return;
  }
  if (state.sideTab === 'realworld') {
    const rw = state.weather?.realworld_atis;
    const metar = state.weather?.metar;
    box.innerHTML = `${atisCard({ source: rw?.source || 'Real-world station', text: rw?.text || rw?.error || 'No real-world station text available.', runways: rw?.runways || [], qnh: rw?.qnh })}
      <div class="card"><strong>METAR</strong><div class="info-grid"><div class="info-tile"><span>QNH</span><strong>${escapeHtml(metar?.qnh || '---')}</strong></div><div class="info-tile"><span>CAT</span><strong>${escapeHtml(metar?.flight_category || '---')}</strong></div></div><div class="metar-text">${escapeHtml(metar?.raw || metar?.error || 'No METAR')}</div></div>`;
    return;
  }
  const atis = state.board?.atis || [];
  const controllers = state.board?.controllers || [];
  const cards = [];
  if (atis.length) cards.push(...atis.map(a => atisCard(a, 'vatsim')));
  if (controllers.length) cards.push(...controllers.map(c => atisCard(c, 'atc')));
  if (!cards.length && state.settings.atisFallback && state.weather?.realworld_atis?.ok) {
    cards.push(atisCard({ source: state.weather.realworld_atis.source || 'Station information', text: state.weather.realworld_atis.text, runways: state.weather.realworld_atis.runways, qnh: state.weather.realworld_atis.qnh }));
  }
  box.innerHTML = cards.join('') || `<div class="card"><strong>No local station online</strong><div class="atis-text">No VATSIM ATIS or local controller found for this airport.</div></div>`;
}

function renderAll() {
  applySettings();
  renderHeader();
  renderTraffic();
  renderSide();
  requestAnimationFrame(() => animateFlaps(document));
}

function setupEvents() {
  const locationButton = $('detectLocationBtn');
  if (locationButton) locationButton.addEventListener('click', () => detectCurrentLocation({auto:false}));
  const cameraReleaseButton = $('cameraReleaseBtn');
  if (cameraReleaseButton) cameraReleaseButton.addEventListener('click', releaseCameraTarget);
  const standaloneCameraButton = $('standaloneCameraPanelBtn');
  if (standaloneCameraButton) standaloneCameraButton.addEventListener('click', showStandaloneCameraPanel);
  const standaloneCameraClose = $('standaloneCameraClose');
  if (standaloneCameraClose) standaloneCameraClose.addEventListener('click', hideStandaloneCameraPanel);
  const atisSummary = $('topAtisSummary');
  if (atisSummary) {
    atisSummary.addEventListener('click', () => {
      const best = bestRunwaysAndQnh();
      state.sideTab = best.sourceTab || 'vatsim';
      document.querySelectorAll('.side-tab').forEach(b => b.classList.toggle('active', b.dataset.side === state.sideTab));
      renderSide();
      document.querySelector('.info-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }
  $('airportIcaoInput').addEventListener('focus', () => { $('airportIcaoInput').select(); renderSuggestions(); $('airportSuggestions').classList.add('open'); });
  $('airportIcaoInput').addEventListener('input', async (e) => {
    const q = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 4);
    e.target.value = q;
    $('airportNameBadge').textContent = q ? 'Search suggestions...' : (state.airportName || 'Airport name');
    if (q.length >= 1) await loadOptions(q); else await loadOptions('');
  });
  $('airportIcaoInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const q = $('airportIcaoInput').value.toUpperCase();
      const ap = state.options.find(x => x.ident === q) || state.options[0];
      if (ap) selectAirport(ap, true, true);
    }
  });
  document.addEventListener('click', (e) => {
    if (!$('airportComboBox').contains(e.target)) $('airportSuggestions').classList.remove('open');
  });
  document.querySelectorAll('.tab').forEach(btn => btn.addEventListener('click', () => {
    state.tab = btn.dataset.tab;
    document.querySelectorAll('.tab').forEach(b => b.classList.toggle('active', b === btn));
    renderTraffic();
  }));
  document.querySelectorAll('.side-tab').forEach(btn => btn.addEventListener('click', () => {
    state.sideTab = btn.dataset.side;
    document.querySelectorAll('.side-tab').forEach(b => b.classList.toggle('active', b === btn));
    renderSide();
  }));
}

let boardRefreshTimer = null;
let animationRefreshTimer = null;
function scheduleBoardRefresh(){
  if(boardRefreshTimer) clearTimeout(boardRefreshTimer);
  boardRefreshTimer=setTimeout(async()=>{await refreshAll(false);scheduleBoardRefresh()},FEED_REFRESH_SECONDS*1000);
}
function scheduleAnimationRefresh(){
  if(animationRefreshTimer) clearTimeout(animationRefreshTimer);
  const seconds=Math.max(15,Math.min(120,Number(state.settings.animationRefreshSeconds||30)));
  animationRefreshTimer=setTimeout(()=>{
    state.renderSeed+=1;
    renderAll();
    scheduleAnimationRefresh();
  },seconds*1000);
}

async function boot() {
  applyEmbeddedFit();
  window.addEventListener('resize', applyEmbeddedFit, {passive:true});
  applySettings();
  setupEvents();
  renderClock(true);
  setInterval(() => renderClock(false), 15000);
  setInterval(() => {
    state.schedulePhase = !state.schedulePhase;
    updateScheduleStatusCells();
  }, 5000);
  if (REQUESTED_AIRPORT) {
    try {
      const requested = await api(`/api/airport/${encodeURIComponent(REQUESTED_AIRPORT)}`);
      selectAirport(requested, false, true);
      state.locationResolved = false;
      updateLocationButton('failed', 'Dispatch destination selected');
    } catch (_) {
      await loadOptions('');
    }
  } else {
    await loadOptions('');
  }
  await refreshAll(false);
  scheduleBoardRefresh();
  scheduleAnimationRefresh();
  // When FIDS starts before the simulator/flight is ready, keep retrying until
  // SimConnect becomes available. A manually selected airport is never changed.
  setInterval(() => detectCurrentLocation({auto:true}), 20000);
}

boot();
