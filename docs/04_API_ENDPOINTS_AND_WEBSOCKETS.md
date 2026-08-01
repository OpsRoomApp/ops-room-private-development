# OPS ROOM v0.25.48 — Complete API & WebSocket Specification

> **Exhaustive reference** for every REST endpoint and WebSocket message type across both `opsroom-app` (desktop) and `opsroom-website` (proxy).

---

## 1. Desktop App REST API (`localhost:{port}`)

All endpoints are served by the embedded FastAPI host. Endpoints marked "Local" require `127.0.0.1` or `::1` origin.

### 1.1 Real-World Flight Search

#### `GET /api/v1/realworld/search`

Search live real-world flights across FlightRadar24, ADSB.lol, and ADSB.fi with automatic field-level hydration. **All parameters are optional.**

| Parameter | Type | Max Length | Behaviour |
|---|---|---|---|
| `origin` | string | 4 | ICAO code. Blank = match all origins, but absent = no bounding-box optimisation |
| `dest` | string | 4 | Destination ICAO. Blank = match all destinations |
| `callsign` | string | 20 | Prefix + substring match. `DLH` matches `DLH400`, `DLH8PK`, `EDW123DLH` |
| `aircraft` | string | 10 | Partial aircraft type match. `A320` matches `A20N`, `A321` |

**Example Request:**
```bash
curl "http://localhost:8080/api/v1/realworld/search?origin=EDDF&callsign=DLH"
```

**Success Response (200):** Flat JSON array — NOT wrapped in `{status, count, flights}`.

```json
[
  {
    "callsign": "DLH8PK",
    "origin": "EDDF",
    "destination": "EDDL",
    "aircraft": "A320",
    "eobt": "14:25z",
    "status": "ON GROUND"
  },
  {
    "callsign": "DLH400",
    "origin": "EDDF",
    "destination": "KJFK",
    "aircraft": "B748",
    "eobt": "AIRBORNE",
    "status": "AIRBORNE"
  }
]
```

**Empty Response (200):**
```json
[]
```

An empty array is not an error — it means no flights matched the search criteria.

**Error States:**

| HTTP Status | Condition | Frontend Behaviour |
|---|---|---|
| 200 | Success (with or without results) | Renders results or "no results" UI |
| 500 | Internal server error (provider failure, unhandled exception) | Shows `"Search failed: HTTP 500"` error UI |

**Notes:**
- The response is returned from the local server, not the website proxy
- The local server aggregates FR24 + ADSB.lol + ADSB.fi and hydrates locally
- The EOBT field is hydrated from OpenSky proxy when FR24 doesn't provide `departure_scheduled_time`

---

### 1.2 System & Status

#### `GET /api/status`
Full system status, version, uptime, subsystem health. No auth required.

**Response (200):**
```json
{
  "ok": true,
  "version": "0.25.48",
  "build": "public-release",
  "uptime_seconds": 410789.2,
  "subsystems": {
    "telemetry": "CONNECTED",
    "simconnect": "ACTIVE",
    "vatsim": "ONLINE",
    "hoppie": "CONNECTED",
    "gsx": "RUNNING",
    "raas": "ACTIVE"
  }
}
```

#### `GET /api/system/summary`
Concise system summary for dashboards. Local-only.

#### `GET /api/system/console?lines=220`
Readable console log tail for the System page. Redacts private IPs. Max 600 lines.

#### `GET /api/diagnostics/cache`
Module preloader cache diagnostics.

#### `GET /api/diagnostics/storage`
Storage usage and file manifest. Local-only.

---

### 1.3 ChartFox Integration

#### `GET /api/charts/chartfox/debug`
Full OAuth/auth/cache/runtime diagnostic dump. Local-only.

**Response (200):**
```json
{
  "ok": true,
  "auth_base": "https://api.chartfox.org/oauth",
  "client_id_masked": "019f***bbfb",
  "token": {
    "has_token": true,
    "granted_scopes": ["charts:files", "charts:index", "charts:view", "charts:view_source_url"],
    "expires_in_remaining": 31535918
  },
  "runtime": {
    "healthy": true,
    "counters": { "total": 16, "success": 14, "failed": 2, "auth_failures": 2 }
  }
}
```

#### `GET /api/charts/chartfox/callback`
OAuth2 redirect callback handler. Receives `?code=...&state=...` from ChartFox after user authentication.

#### `GET /api/charts/chartfox/proxy/grouped/{icao}`
Proxy grouped charts for an ICAO airport. Requires valid ChartFox token. Local-only.

**Response:** ChartFox API v2 grouped chart listing (categories: General, SID, STAR, Approach, etc.).

#### `GET /api/charts/chartfox/proxy/chart/{chart_id}`
Proxy single chart detail. Includes `files[]`, `source_url`, `source_url_type`, `georefs`, `allows_iframe`. Local-only.

#### `GET /api/charts/chartfox/proxy/file?url=...`
Stream chart file binary (PDF/IMG). The `url` parameter must be a ChartFox-issued file URL. Local-only.

**Response:** Binary stream with appropriate `Content-Type` (`application/pdf` or `image/*`).

---

### 1.4 SimBrief Integration

#### `POST /api/simbrief/fetch`
Fetch and parse SimBrief OFP by user ID. Local-only.

**Request:**
```json
{ "user_id": "12345" }
```

**Response:**
```json
{
  "ok": true,
  "callsign": "DLH400",
  "origin": { "icao": "EDDF" },
  "destination": { "icao": "KJFK" },
  "alternate": { "icao": "KBOS" },
  "files": { "plan_html": "...", "plan_text": "...", "plan_pdf": "..." }
}
```

#### `GET /api/simbrief/pinned`
Get currently pinned flight plan. Local-only.

---

### 1.5 Printer / POS Thermal

#### `GET /api/printer/status`
Printer system health, available printers list. Local-only.

#### `GET /api/printer/list`
Raw printer enumeration from Windows spooler.

#### `POST /api/printer/test`
Send test receipt to named printer.

**Request:** `{ "printer_name": "EPSON TM-T88V" }`

#### `POST /api/printer/preview`
Generate virtual 80mm thermal receipt preview HTML.

**Request:**
```json
{ "content": "CPDLC CLEARANCE TEXT", "type": "cpdlc" }
```

**Response:**
```json
{
  "ok": true,
  "raw_lines": ["line 1", "line 2"],
  "html": "<div class=\"printer-receipt\">...</div>",
  "line_count": 24,
  "width": 42,
  "receipt_type": "cpdlc",
  "generated_at": "2026-07-31T12:00:00Z"
}
```

---

### 1.6 Updates

#### `GET /api/updates/check`
Check for available updates (dual-channel: opsroom.live → GitHub fallback). Local-only.

**Response:**
```json
{
  "ok": true,
  "update_available": false,
  "current_version": "0.25.48",
  "latest_version": "0.25.48",
  "channel": "stable"
}
```

#### `POST /api/updates/install`
Download and stage update ZIP. Local-only.

---

### 1.7 Black Box

#### `GET /api/blackbox/diagnose`
Black Box telemetry buffer diagnostics (buffer size, recording state, write throughput).

#### `GET /api/blackbox/status`
Recording state (`RECORDING` / `STOPPED`), duration, file size.

---

### 1.8 VATSIM / Network

#### `GET /api/vatsim/fids/{icao}`
VATSIM FIDS data for an airport. Public.

#### `GET /api/vatsim/metar/{icao}`
VATSIM METAR string. Public.

---

### 1.9 Settings

#### `GET /api/settings`
Load full settings object. Local-only.

#### `PUT /api/settings`
Save settings. Merges incoming sections (`identity`, `integrations`, `server`, `interface`). Returns `restart_required: true` if the server port changed.

---

### 1.10 Settings Endpoints

#### `GET /api/settings`

Load the full settings object. Local-only.

```bash
curl http://localhost:8080/api/settings
```

**Response (200):**
```json
{
  "identity": { "vatsim_cid": "1234567", "simbrief_user_id": "12345" },
  "integrations": { "hoppie_configured": true, "announcements_enabled": false },
  "server": { "port": 8080, "lan_enabled": false },
  "interface": { "setup_completed": true, "terminal_style": "efb" }
}
```

**Error States:** 403 (not localhost), 500 (settings file corrupted).

#### `PUT /api/settings`

Save settings. Merges incoming sections. Local-only.

```bash
curl -X PUT http://localhost:8080/api/settings \
  -H "Content-Type: application/json" \
  -d '{"server": {"port": 8090}}'
```

**Response (200):**
```json
{ "ok": true, "settings": { ... }, "restart_required": false }
```

If the server port changed, `restart_required` is `true`. The frontend prompts the user to restart.

### 1.11 Updater Endpoints

#### `GET /api/updates/check`

Dual-channel update check. Local-only.

```bash
curl "http://localhost:8080/api/updates/check?force=true"
```

**Response (200 — no update):**
```json
{
  "ok": true,
  "update_available": false,
  "current_version": "0.25.48",
  "latest_version": "0.25.48",
  "channel": "stable"
}
```

**Response (200 — update available):**
```json
{
  "ok": true,
  "update_available": true,
  "current_version": "0.24.00",
  "latest_version": "0.25.48",
  "manifest": { "version": "0.25.48", "download_url": "...", "sha256": "..." }
}
```

**Error States:** Both channels unreachable → `update_available: false` with `error` field. No 500 raised.

#### `POST /api/updates/install`

Download and stage update ZIP. Local-only.

**Request:** `{ "manifest": { ... } }` (from check response) or `{}` (auto-detects).

**Response (200):**
```json
{ "ok": true, "staged_version": "0.25.48", "staged_path": "..." }
```

### 1.12 SimBrief Endpoints

#### `POST /api/simbrief/fetch`

Fetch and parse SimBrief OFP. Local-only.

```bash
curl -X POST http://localhost:8080/api/simbrief/fetch \
  -H "Content-Type: application/json" \
  -d '{"user_id": "12345"}'
```

**Response (200):**
```json
{
  "ok": true,
  "callsign": "DLH400",
  "origin": { "icao": "EDDF", "name": "Frankfurt" },
  "destination": { "icao": "KJFK", "name": "New York JFK" },
  "alternate": { "icao": "KBOS", "name": "Boston" },
  "dep_icao": "EDDF",
  "arr_icao": "KJFK",
  "altn_icao": "KBOS",
  "files": {
    "plan_html": "<html>...",
    "plan_text": "ROUTE ...",
    "plan_pdf": "..."
  }
}
```

**Error States:** 400 (invalid/missing user_id), 502 (SimBrief API unreachable), 404 (no OFP found).

#### `GET /api/simbrief/pinned`

Get the currently auto-pinned flight plan. Local-only. Returns `{ ok, callsign, dep_icao, arr_icao, altn_icao }` or `{ ok: false, reason: "..." }` if no plan is pinned.

### 1.13 Black Box Endpoints

#### `GET /api/blackbox/status`

Recording state and file info.

**Response (200):**
```json
{
  "ok": true,
  "state": "RECORDING",
  "recording_id": "abc123",
  "duration_seconds": 3600,
  "file_size_bytes": 52428800,
  "schema_version": 2
}
```

**States:** `RECORDING`, `STOPPED`, `PAUSED`, `RECOVERING` (interrupted recording recovery on startup).

#### `GET /api/blackbox/diagnose`

Telemetry buffer diagnostics: buffer size, sample rate, write throughput, dropped samples count.

#### `GET /api/blackbox/recordings`

List all saved recordings: `[{ id, date, origin, destination, callsign, duration, size }]`.

#### `GET /api/blackbox/recording/{id}`

Get recording metadata and sample count. Query `?format=csv` or `?format=gpx` or `?format=kml` for export.

### 1.14 Additional Endpoints (Summary)

| Path | Method | Purpose |
|---|---|---|
| `/api/position` | GET | Current aircraft position from SimConnect |
| `/api/radio` | GET | Radio state (COM1/2, NAV1/2, XPDR) |
| `/api/autopilot` | GET/POST | Autopilot state get/set |
| `/api/scratchpad` | GET/POST | Scratchpad text persistence |
| `/api/dispatch/context` | GET | Dispatch recommendations |
| `/api/dispatch/active` | GET/POST | Active dispatch plan management |
| `/api/flight-watch` | GET | Real-time flight watch dashboard |
| `/api/procedures` | GET | SOP/checklist data |
| `/api/performance` | POST | Takeoff/landing performance calculation |
| `/api/economy/status` | GET | Finance/career status |
| `/api/logbook/*` | GET/POST/DELETE | Flight logbook CRUD + export |
| `/api/navdata/airport/{icao}` | GET | Runway/COM navdata |
| `/api/raas/status` | GET/POST | RAAS status and control |
| `/api/camera-bridge/status` | GET/POST | Camera Bridge 2024 control |
| `/api/announcements/*` | GET/POST | Announcement engine control |
| `/api/gsx/*` | GET/POST | GSX Pro status and automation |
| `/api/hoppie/*` | GET/POST | Hoppie ACARS send/receive |
| `/api/vpilot/*` | GET/POST | vPilot bridge control |
| `/api/security/*` | GET/POST/DELETE | Device pairing and trust |
| `/api/obs/branding` | GET/POST | OBS overlay branding |
| `/api/airline-branding/*` | GET/POST/DELETE | Airline identity branding |
| `/api/bug-report/*` | GET/POST | Bug report diagnostics |
| `/api/server-info` | GET | Server info + QR code |

---

## 2. Website Proxy REST API (`admin.opsroom.live`)

### 2.1 Real-World Schedule Proxy

#### `GET /api/v1/realworld-search`

Public endpoint. No authentication required from the desktop app. The proxy handles OpenSky OAuth2 internally.

| Parameter | Type | Max Length | Behaviour |
|---|---|---|---|
| `origin` | string | 4 | ICAO code. Triggers departure search at OpenSky. |
| `dest` | string | 4 | Filter by destination ICAO |
| `callsign` | string | 20 | Filter by callsign (substring match) |
| `aircraft` | string | 10 | Filter by aircraft type (ICAO24 hex → type lookup) |

**Example Request:**
```bash
curl "https://admin.opsroom.live/api/v1/realworld-search?origin=EDDF&callsign=DLH400"
```

**Success Response (200):**
```json
{
  "status": "success",
  "count": 1,
  "flights": [
    {
      "callsign": "DLH8PK",
      "origin": "EDDF",
      "destination": "EDDL",
      "firstSeen": 1785360000,
      "lastSeen": 1785363600,
      "icao24": "3C6441",
      "eobt_utc": "14:25"
    }
  ]
}
```

**Rate Limiting & Error Handling:**

| HTTP Status | Condition | Desktop App Fallback |
|---|---|---|
| 200 | Success | Renders or hydrates EOBT |
| 200 (empty `flights`) | No matching departures | EOBT falls through to altitude state |
| 502 | Proxy or OpenSky upstream failure | EOBT → `"AIRBORNE"` / `"ON GROUND"` |
| 429 / timeout | Rate limit or network failure | Same as 502 — graceful fallback |

**Caching:** Server-side 60-second TTL, keyed by full parameter set. The cache is the primary defense against OpenSky rate limits (free tier: ~1 request / 10 seconds per endpoint).

### 2.2 OpenSky OAuth2 Token Flow

The proxy uses OAuth2 Client Credentials:

```bash
curl -X POST "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=${OPENSKY_CLIENT_ID}" \
  -d "client_secret=${OPENSKY_CLIENT_SECRET}"
```

**Correct realm:** `opensky-network` (NOT `master`). Using `master` results in Keycloak `invalid_client` errors.

The token is short-lived and re-fetched on expiry. The desktop app **never** sees or handles these credentials — they exist only on the VPS.

---

## 3. WebSocket Specification

### Endpoint

```
ws://localhost:8080/ws
```

### Connection

```javascript
var ws = new WebSocket('ws://' + window.location.host + '/ws');
```

No authentication required for local connections. LAN connections must pass device pairing gate.

### Server → Client Message Types

#### Telemetry Frame
```json
{
  "type": "telemetry",
  "lat": 52.134,
  "lon": 13.690,
  "alt": 35000,
  "hdg": 270,
  "ias": 280,
  "gs": 450,
  "vs": 0,
  "mach": 0.78,
  "on_ground": false,
  "com1": "121.500",
  "com2": "122.800",
  "xpdr": "2000",
  "squawk_mode_c": true,
  "timestamp": 1785400000.0
}
```

#### ACARS / CPDLC Message
```json
{
  "type": "acars",
  "direction": "IN",
  "from": "EDDF_CTR",
  "to": "DLH123",
  "message": "CLIMB FL350",
  "msg_type": "cpdlc",
  "time": "2026-07-31T12:00:00Z"
}
```

#### ATC Handoff Alert
```json
{
  "type": "atc_handoff",
  "from": "EDDF_CTR",
  "to": "EDDM_APP",
  "frequency": "120.775",
  "time": "2026-07-31T12:05:00Z"
}
```

#### System Status
```json
{
  "type": "status",
  "subsystem": "simconnect",
  "state": "CONNECTED",
  "detail": "MSFS 2024"
}
```

### Auto-Reconnect Behaviour

- On close: 2-second backoff before reconnect attempt
- On error: log, show amber `RECONNECTING` badge
- Maximum retries: infinite (background polling)
- Connection badge: green `CONNECTED` / amber `RECONNECTING` / red `DISCONNECTED`

---

## 4. OAuth2 Flow Reference

### ChartFox (Desktop App)

| Step | URL | Method |
|---|---|---|
| Authorize | `https://api.chartfox.org/oauth/authorize?client_id=019f9162-...&redirect_uri=http://localhost:8080/api/charts/chartfox/callback&scope=...&code_challenge=...` | Browser redirect |
| Callback | `http://localhost:8080/api/charts/chartfox/callback?code=...&state=...` | GET |
| Token Exchange | `https://api.chartfox.org/oauth/token` | POST (server-side) |

**Client ID:** `019f9162-61b5-734f-973d-bb80f02fbbfb` (public, not a secret)  
**Scopes:** `charts:index charts:view charts:files charts:view_source_url`  
**Flow:** Authorization Code + PKCE (public client, no client secret)

### OpenSky Network (Website Proxy)

| Step | URL | Method |
|---|---|---|
| Token | `https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token` | POST |

**Grant type:** `client_credentials`  
**Credentials:** `OPENSKY_CLIENT_ID` + `OPENSKY_CLIENT_SECRET` (from `.env` on VPS)  
**Realm:** `opensky-network` (corrected from `master`)  
**Usage:** Departure search (`/api/flights/departure`), states search (`/api/states/all`)
