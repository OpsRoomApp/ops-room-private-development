# OPS ROOM — Frontend Engine, State Management & DOM Mechanics

**Version:** v0.25.61
**Last Updated:** 2026-07-31

---

## 1. Frontend Architecture Overview

The OPS ROOM frontend is a **vanilla JavaScript ES6 Single-Page Application** with no external frameworks. It runs inside an embedded Microsoft Edge WebView2 browser. All module logic lives in a single file (`opsroom.js`, 6925 lines), with supplemental SPA files for specialized views.

### File Inventory

| File | Lines | Purpose |
|---|---|---|
| `opsroom.js` | 6925 | Global state engine, all 30+ module UI controllers, ChartFox rendering, real-world search, WebSocket handling, annotation engine |
| `opsroom.css` | ~2363 | Design system, dark theme, chart viewer layout, systems grid, responsive breakpoints |
| `app.js` | — | Standalone ATIS/FIDS display SPA (VATSIM traffic board) |
| `host.js` | — | Host settings, identity/integration management, configuration UI |
| `host.css` | — | Host console-specific styles |
| `index.html` | 987 | Single HTML shell with all module containers (launcher buttons, display sections) |
| `host.html` | — | Host configuration console HTML |
| `traffic_board.html` | — | VATSIM FIDS standalone view |
| `obs.html` / `obs.js` / `obs.css` | — | OBS Studio overlay (streamer branding) |
| `pirep.html` / `pirep.js` / `pirep.css` | — | PIREP viewer and print stylesheet |
| `service-worker.js` | — | PWA offline caching |

---

## 2. Global State Engine

### State Store Architecture

The application uses plain JavaScript objects as global state stores — no reducers, no immutability guarantees, no virtual DOM diffing:

```javascript
// Primary application state
var opsState = { ... };           // Active module, theme, network status, telemetry snapshot

// ChartFox integration state
var cfState = { ... };            // Pins, search results, current chart, dark mode, annotation, geo data

// Persisted settings (loaded from server on startup)
window.OR_SETTINGS = { ... };     // Identity, integrations, display preferences, interface

// Host-specific state
hostState = { ... };              // VATSIM CID, SimBrief ID, Hoppie code, GSX/vPilot paths
```

### State Flow

```
User action (click, keypress, form submit)
        │
        ▼
Event handler function (e.g., performRealworldSearch)
        │
        ├──▶ fetch() to local FastAPI endpoint
        │       │
        │       ▼ Response JSON
        │
        ├──▶ Update global state object (e.g., opsState.flights = data)
        │
        ▼
render*() function
        │
        ▼
Direct DOM manipulation
        │  • element.innerHTML = template
        │  • element.appendChild(card)
        │  • element.style.display = 'block' / 'none'
        │  • canvas.getContext('2d').drawImage(...)
        │
        ▼
User sees updated UI
```

There is no reconciliation, no shadow DOM, and no diffing — changes are applied directly to the live DOM tree. Module visibility is toggled via `display` property on section elements (e.g., `$('dispatchModule').style.display = 'block'`).

### Local Storage Persistence

Key state is persisted to `localStorage` for survival across app restarts (WebView2 clear is managed at startup):

| localStorage Key | Content | Module |
|---|---|---|
| `or_settings` | Full settings object (identity, integrations, display) | Settings |
| `cf_pins` | ChartFox pinned chart UUIDs (JSON array) | Charts |
| `cf_dark_mode` | Chart viewer dark mode toggle (`"true"` / `"false"`) | Charts |
| `cf_annot_{chart_uuid}` | Annotation stroke paths per chart (JSON) | Charts |
| `or_cache` | General application cache | Global |
| `or_logs` | Startup and operational log entries | Global |

---

## 3. Real-World Schedules UI (`performRealworldSearch`)

### Search Flow

The Dispatch module's "Real-World Schedules" tab queries the **local** FastAPI server (not the website proxy):

```javascript
async function performRealworldSearch(e) {
  if (e) e.preventDefault();
  var params = new URLSearchParams();
  if (origin)    params.set('origin',    origin);
  if (dest)      params.set('dest',      dest);
  if (callsign)  params.set('callsign',  callsign);
  if (aircraft)  params.set('aircraft',  aircraft);

  var apiUrl = '/api/v1/realworld/search?' + params.toString();
  var resp = await fetch(apiUrl, {
    method: 'GET',
    headers: { 'Accept': 'application/json' }
  });
  var data = await resp.json();

  // Response is a FLAT ARRAY — NOT {status, count, flights}
  if (Array.isArray(data) && data.length > 0) {
    renderRealworldResults(data);  // flat array passed directly
  } else {
    container.innerHTML = '<div class="rw-no-results">No active real-world departures found matching criteria.</div>';
  }
}
```

**Key:** The backend returns a flat JSON array `[{callsign, origin, destination, aircraft, eobt, status}]`, not the legacy `{status: "success", count: N, flights: [...]}` wrapper. The frontend checks `Array.isArray(data)` to handle this.

### Input Field Preservation

Search input fields are **not cleared** after a search — the user's search terms remain intact so they can tweak and re-search without retyping. This was an explicit design decision to prevent the frustrating UX pattern of losing typed input on search.

### Parameter Handling

All parameters are optional:

| Input Element ID | Query Key | Behavior |
|---|---|---|
| `rw-origin` | `origin` | ICAO (4 chars). Blank = absent from query → match all origins |
| `rw-dest` | `dest` | ICAO (4 chars). Blank = absent → match all destinations |
| `rw-callsign` | `callsign` | Prefix/substring. `DLH` matches `DLH400`, `DLH8PK` |
| `rw-aircraft` | `aircraft` | Partial match. `A320` matches `A20N`, `A321`. Blank → match all |

### EOBT Rendering & Countdown Ticker

The `eobt` field is a formatted string from the backend. Three possible formats:

| `eobt` Value | Frontend Parsing | Display |
|---|---|---|
| `"14:25z"` | Parsed to nearest future UTC today; if past, rolls to tomorrow | `14:25 UTC` + live countdown (`-45m`, `-1h 30m` in amber; red if overdue) |
| `"AIRBORNE"` | No parsing — string passed through | `AIRBORNE` (grey, no countdown) |
| `"ON GROUND"` | No parsing — string passed through | `ON GROUND` (grey, no countdown) |

**Countdown logic:**

```javascript
if (eobtRaw && /^\d{2}:\d{2}z$/i.test(eobtRaw)) {
  var parts = eobtRaw.match(/^(\d{2}):(\d{2})/i);
  var now = new Date();
  var d = new Date(Date.UTC(
    now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(),
    parseInt(parts[1]), parseInt(parts[2]), 0, 0
  ));
  if (d.getTime() < now.getTime()) d.setUTCDate(d.getUTCDate() + 1);
  eobtMs = d.getTime();
  eobtDisplay = parts[1] + ':' + parts[2] + ' UTC';
}
```

A `setInterval(updateCountdown, 1000)` ticker per flight card updates the countdown badge every second:
- **Green** text when future (`-45m`)
- **Red** text + `rw-eobt-overdue` CSS class when past (`+15m`)

**Timer cleanup:** When `renderRealworldResults` re-renders, all existing `rwCountdownTimers` are cleared via `clearInterval()` to prevent zombie timers.

### Flight Card Actions

Each rendered flight card has two action buttons:

| Button | Function | Behaviour |
|---|---|---|
| **IMPORT TO DISPATCH** | `importToActiveDispatch(callsign, orig, dest)` | Populates the Dispatch form with callsign, origin, destination and switches to active-plan tab |
| **OPEN IN SIMBRIEF** | `launchSimBriefFromRW(callsign, orig, dest, eobt)` | Opens `dispatch.php?orig=...&dest=...&callsign=...&airline=...&fltnum=...` in a new window |

The SimBrief launcher parses the callsign to extract airline ICAO prefix and flight number (e.g., `DLH400` → airline=`DLH`, fltnum=`400`), omitting `----`, `TBD`, and `UNKNOWN` values from the URL.

### Output Schema

```json
[
  {
    "callsign": "DLH8PK",
    "origin": "EDDF",
    "destination": "EDDL",
    "aircraft": "A320",
    "eobt": "14:25z",
    "status": "ON GROUND"
  }
]
```

All six fields are always present. `aircraft` defaults to `"A320"`, `destination` defaults to `"UNKNOWN"`, `eobt` defaults to live telemetry state.

---

## 4. ChartFox PDF Rendering Pipeline

### Architecture

```
ChartFox API ──▶ charts.py proxy ──▶ cfRenderPreview()
                                          │
                          ┌───────────────┼───────────────┐
                          ▼               ▼               ▼
                     files[] PDF    source_url PDF    url .pdf
                          │               │               │
                          └───────────────┼───────────────┘
                                          ▼
                                  cfRenderPdfCanvas()
                                          │
                              ┌───────────┴───────────┐
                              ▼                       ▼
                       PDF.js getDocument     Canvas rendering
                              │                       │
                              ▼                       ▼
                        page.render()         cfAutoFitToScreen()
```

### File Selection Algorithm (3-Step Priority)

```javascript
// Step A: Check files[] array for first-party ChartFox mirrors
if (chartData.files && chartData.files.length > 0) {
  const pdfFile = chartData.files.find(f => f.type === 0); // 0 = PDF
  if (pdfFile) { targetUrl = pdfFile.url; isPdf = true; }
  else {
    const imgFile = chartData.files.find(f => f.type === 1); // 1 = IMG
    if (imgFile) targetUrl = imgFile.url;
  }
}

// Step B: Fallback to source_url (original supplier)
if (!targetUrl && chartData.source_url) {
  targetUrl = chartData.source_url;
  isPdf = (chartData.source_url_type === 0); // 0=PDF, 1=IMG, 2=HTML
}

// Step C: Fallback to primary url field
if (!targetUrl && chartData.url) {
  targetUrl = chartData.url;
  isPdf = targetUrl.toLowerCase().endsWith('.pdf');
}
```

### Ultra-High DPI Canvas Rendering

PDF.js canvas uses a **3.0× minimum device pixel ratio**:

```javascript
const dpr = Math.max(window.devicePixelRatio || 1, 3.0);
const viewport = page.getViewport({ scale: baseScale * dpr });
canvas.width  = Math.floor(viewport.width);
canvas.height = Math.floor(viewport.height);
canvas.style.width  = Math.floor(viewport.width  / dpr) + 'px';
canvas.style.height = Math.floor(viewport.height / dpr) + 'px';
```

### Dark Mode Inversion

```css
.cf-canvas-dark {
  filter: invert(0.9) hue-rotate(180deg) contrast(1.15) brightness(0.95);
}
```

Default mode is **Dark** (sun ☀️ icon toggles to light). Preference persists in `localStorage`.

### Annotation Layer

A transparent `<canvas id="cfAnnotCanvas">` overlays the PDF canvas:

- **Tools:** Pen, Highlighter (40% alpha, composite `source-over`), Eraser (composite `destination-out`)
- **Default pen:** `3.5px` width, `lineCap: 'round'`, `lineJoin: 'round'` (matches Scratchpad feel)
- **Stroke storage:** Normalized PDF-page ratios (`rx`, `ry`) → re-projected on every zoom/pan
- **Persistence:** `localStorage` keyed by `cf_annot_{chart_uuid}`
- **Isolation:** Annotation mode disables chart pan/zoom via `cfPanEnabled = false`

### Zoom & Pan Controls

```
[−] 100% [+] [FIT] [☀️]  — toolbar integrated in chart viewer header
```

- Zoom steps: 25% (±, up to 400%)
- Pan: click-and-drag on canvas wrapper (both PDF + annotation canvases move together)
- Auto-fit: `cfAutoFitToScreen()` on chart load, syncs annotation canvas dimensions

---

## 5. Geo-Referencing Engine

### Coordinate Transformation

```
WGS84 (Lat/Lon) ──▶ EPSG:3857 (Spherical Mercator) ──▶ Canvas pixel (x,y)
```

Uses the standard Web Mercator projection with chart-specific transformation parameters (`tx`, `ty`, `k`, `transform_angle` from `georefs[]`).

### Own-Position Overlay

- `cfPlotOwnship()` renders a pulsing green dot (`.cf-ownship-dot`) at the aircraft's position
- Updates via `cfStartOverlayTimer()` polling at ~500ms intervals using live SimConnect telemetry
- Requires `charts:geos` scope for `georefs` data from ChartFox API
- Status badge: `GEO REFERENCED 🟢` or `NO GEO REFERENCE`

---

## 6. WebSocket & Polling Event Handlers

### Connection Lifecycle

The frontend maintains persistent WebSocket connections to `ws://localhost:8080/ws`:

```javascript
var ws = new WebSocket('ws://' + window.location.host + '/ws');

ws.onopen  = function() { /* update connection badge */ };
ws.onclose = function() { /* schedule auto-reconnect after 2s */ };
ws.onerror = function() { /* log, show warning */ };
ws.onmessage = function(event) {
  var msg = JSON.parse(event.data);
  dispatchWebSocketMessage(msg);
};
```

### Message Types & Handlers

| `type` | Handler | Action |
|---|---|---|
| `telemetry` | `updateTelemetryState(msg)` | Update `opsState` telemetry snapshot, redraw position overlays |
| `acars` | `handleAcarsMessage(msg)` | Push to Comms message log, auto-print if CPDLC and printer configured |
| `atc_handoff` | `handleAtcHandoff(msg)` | Show frequency change alert, highlight new controller |
| `status` | `updateSystemStatus(msg)` | Update system health indicators in status bar |

### Auto-Reconnect

On WebSocket close, a 2-second backoff reconnect is scheduled. The connection badge shows `CONNECTED` (green), `RECONNECTING` (amber), or `DISCONNECTED` (red).

---

## 7. Module Visibility & SPA Routing

The SPA uses display toggling rather than URL hash routing:

```javascript
function switchModule(moduleName) {
  // Hide all modules
  document.querySelectorAll('.ops-module').forEach(function(m) {
    m.style.display = 'none';
  });
  // Show the target
  document.getElementById(moduleName).style.display = 'block';
  // Update active nav highlight
  updateNavHighlight(moduleName);
}
```

Each module is a `<section class="ops-module" id="dispatchModule">` in `index.html`. The launcher buttons on the home screen trigger `switchModule()` calls.

---

## 8. Module Walkthroughs

### Dispatch Module (`#dispatchModule`)

The Dispatch module has two sub-tabs toggled via `switchDispatchTab()`:

**Active Plan Tab (`active-plan`):**
- Reads active dispatch from `dispatchState` (loaded from `GET /api/dispatch/active`)
- Displays callsign, origin ICAO, destination ICAO, alternate ICAO
- SimBrief auto-pins relevant ChartFox charts based on DEP/ARR/ALTN
- Route recommendations from `GET /api/dispatch/context`
- "Import from SimBrief" button triggers `POST /api/simbrief/fetch`

**Real-World Schedules Tab (`realworld-search`):**
- Search form: Origin, Destination, Callsign, Aircraft Type (all optional)
- `performRealworldSearch()` → `GET /api/v1/realworld/search` → `renderRealworldResults()`
- Flight cards with live EOBT countdowns, Import/SimBrief action buttons
- Input fields preserved after search (no clear-on-search UX)

### Flight Tracking Tab (`#flightWatchModule`)

Real-time flight watch dashboard:
- Telemetry stream from WebSocket (`type: "telemetry"`)
- Live position, altitude, heading, speed, vertical speed
- Flight phase detection (taxi, takeoff, climb, cruise, descent, landing)
- Map overlay with aircraft track
- PIREP score estimation in real-time

### Settings Panel (`#settingsPanel`)

Host settings loaded via `GET /api/settings`, saved via `PUT /api/settings`:
- **Identity:** VATSIM CID, SimBrief user ID
- **Integrations:** Hoppie ACARS config, announcements toggle, GSX catering/water preferences
- **Server:** Port configuration, LAN access toggle
- **Interface:** Terminal style (EFB/classic), streamer mode, rail collapse
- **Updates:** Auto-check toggle

Settings changes that modify the server port trigger a `restart_required: true` response — the UI prompts the user to restart.

### Live Status Banners (`#opsStatusBar`)

Footer status bar showing:
- **SimConnect status:** CONNECTED / DISCONNECTED / SIMULATOR NOT CONNECTED
- **VATSIM status:** ONLINE / OFFLINE (with controller count)
- **Hoppie status:** CONNECTED / DISCONNECTED
- **RAAS status:** ACTIVE / STBY / FAULT
- **GSX status:** RUNNING / IDLE (with current service)
- **Version:** `OPS ROOM v0.25.61`

Status updates flow from WebSocket messages and REST polling every 30 seconds. Banners use CSS class toggling: `.status-ok` (green), `.status-warn` (amber), `.status-err` (red).

---

## 9. Chart Viewer Layout

### Container Hierarchy

```
.bridge-charts-panel (flex column)
  └── .cf-shell (flex column, fills parent)
        ├── #cfHeaderBar (search input + category tabs)
        ├── .cf-pinned-bar (horizontal scroll pinned chips)
        ├── .cf-search-results (sidebar chart list)
        └── #cfPreview (flex:1, main chart canvas area)
              ├── .cf-preview-meta-single (chart name, copyright, PDF link, geo badge)
              ├── .cf-pdf-canvas-wrap (PDF.js canvas + annotation canvas)
              ├── .cf-pdf-toolbar ([−] 100% [+] [FIT] [☀️])
              └── .cf-annot-toolbar (pen/highlighter/eraser + color/width selectors)
```

### Responsive Behaviour

- Category tabs: `flex-wrap: wrap; overflow: visible` — never clipped
- Pinned bar: horizontal scroll overflow
- Chart sidebar: collapsible on narrow viewports
- Canvas: fills available space via `flex: 1; min-height: 0`

---

## 9. Core Utility Functions (opsroom.js)

| Function | Purpose |
|---|---|
| `escapeHtml(value)` | HTML-entity encode user-generated strings |
| `escapeAttr(value)` | Attribute-safe escaping |
| `friendlyError(value)` | Strip raw exception text; return user-facing advisory |
| `uiToken(value)` | Convert internal enum to display label |
| `friendlyStage(value)` | Human-readable flight phase label |
| `sensitiveValueHtml(value, visible, label)` | Toggle-sensitive field rendering (streamer mode) |
| `fetchWithTimeout(url, options, timeoutMs)` | Fetch with configurable timeout (default 8s) |
| `safeJsonResponse(response)` | Parse JSON with error handling |
| `reportFrontendError(source, detail)` | Log frontend errors to console + advisory panel |
| `runModuleStart(name, fn)` | Execute module init with error boundary |
