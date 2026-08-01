# OPS ROOM — Backend, Telemetry & Bridges

**Version:** v0.25.55
**Last Updated:** 2026-07-31

---

## 1. Application Lifecycle & FastAPI Core (`app/main.py`)

### Startup Sequence

`app/main.py` (~2600 lines) is the FastAPI application factory. On startup, it:

1. Creates the `FastAPI(title="OPS ROOM", version="0.25.55")` instance
2. Adds middleware: `GZipMiddleware` (512-byte minimum), `CORSMiddleware` (explicit localhost origins)
3. Mounts static directories: `/static` → `app/static/`, `/assets` → `app/assets/`
4. Includes the `realworld_router` at `/api/v1/realworld`
5. Registers the global `Exception` handler — sanitizes tracebacks, returns `INTERNAL_ERROR` code
6. Runs startup event:
   - Starts telemetry engine
   - Purges stale ChartFox cache files (background daemon thread)
   - Recovers interrupted Black Box recordings
   - Registers module caches with the preloader
   - Prewarms all caches (background thread)
   - Auto-fetches SimBrief OFP if configured (background thread)
   - Silences FSUIPC7 verbose logging (background thread)
7. Runs shutdown event: stops telemetry, Black Box replay/recording, PMDG SDK, announcements, Hoppie, GSX automation, Camera Bridge, RAAS

### Middleware Stack

| Middleware | Order | Purpose |
|---|---|---|
| `GZipMiddleware` | First | Compress responses ≥ 512 bytes |
| `CORSMiddleware` | Second | Allow localhost origins with credentials |
| `static_cache_headers` | HTTP | Add `Cache-Control: public, max-age=86400, immutable` to static assets |
| `trusted_device_gate` | HTTP | Enforce device pairing for LAN access to non-public paths |

### Route Registration

The application registers 170+ routes including:

```python
# Real-world search
app.include_router(realworld_router)  # → /api/v1/realworld/search

# ChartFox OAuth + proxy
@app.get("/api/charts/chartfox/debug")
@app.get("/api/charts/chartfox/callback")
@app.get("/api/charts/chartfox/proxy/grouped/{icao}")
@app.get("/api/charts/chartfox/proxy/chart/{chart_id}")

# Telemetry & simconnect
@app.get("/api/position")
@app.get("/api/radio")
@app.get("/api/autopilot")

# Settings
@app.get("/api/settings")
@app.put("/api/settings")

# System
@app.get("/api/system/summary")
@app.get("/api/system/console")

# SimBrief
@app.post("/api/simbrief/fetch")
@app.get("/api/simbrief/pinned")

# Printer
@app.get("/api/printer/status")
@app.post("/api/printer/test")
@app.post("/api/printer/preview")

# Updater
@app.get("/api/updates/check")
@app.post("/api/updates/install")

# Black Box
@app.get("/api/blackbox/status")
@app.get("/api/blackbox/diagnose")

# And 130+ more routes for VATSIM, procedures, economy, logbook, etc.
```

---

## 2. SimConnect & Telemetry Bridges

### Architecture

```
MSFS 2024 ──SimConnect──▶ simconnect_position.py
                                    │
                            Internal state dict
                            (position, radios, altitude,
                             heading, gear, flaps, camera, autopilot)
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
            WebSocket broadcast            REST API endpoints
            (real-time telemetry)          (/api/position, /api/radio, etc.)
```

### Telemetry Provider (`telemetry_provider.py`)

The abstraction layer supports multiple simulator sources:

- **SimConnect** (MSFS 2020/2024) — primary, full telemetry: position, radios, autopilot, systems, camera
- **FSUIPC** — fallback for legacy sims (P3D, FSX). Provides subset of MSFS telemetry: position, radios, limited systems data. Managed via `app/fsuipc_manager.py`; auto-started if configured. FSUIPC7 verbose logging is silenced at startup to prevent multi-GB log files
- **XPUIPC** — X-Plane bridge via UDP. Limited: position and basic radio data only. No camera control, no advanced systems telemetry. X-Plane users should prefer the SimConnect path via the MSFS SDK compatibility layer where available

> **Platform tier:** MSFS 2020/2024 is the primary target with full telemetry. P3D/FSX support is via FSUIPC with reduced data. X-Plane support is experimental and limited to position/radio. Camera Bridge 2024 is MSFS-only.

Provider selection is automatic based on detected sim, with manual override available.

### Polled Variables (SimConnect)

| Category | Variables | Poll Rate |
|---|---|---|
| Position | `PLANE_LATITUDE`, `PLANE_LONGITUDE`, `PLANE_ALTITUDE`, `GROUND_ALTITUDE` | ~100ms |
| Attitude | `PLANE_PITCH_DEGREES`, `PLANE_BANK_DEGREES`, `PLANE_HEADING_DEGREES_TRUE` | ~100ms |
| Speed | `AIRSPEED_INDICATED`, `GROUND_VELOCITY`, `VERTICAL_SPEED`, `MACH` | ~100ms |
| Radios | `COM1_ACTIVE_FREQUENCY`, `COM1_STANDBY_FREQUENCY`, `COM2_*`, `NAV1_*`, `NAV2_*`, `TRANSPONDER_CODE` | ~250ms |
| Autopilot | `AUTOPILOT_MASTER`, `AUTOPILOT_ALTITUDE_LOCK`, `AUTOPILOT_HEADING_LOCK`, `AUTOPILOT_APPROACH_HOLD` | ~250ms |
| Systems | `GEAR_CENTER_POSITION`, `FLAPS_HANDLE_INDEX`, `SPOILERS_HANDLE_POSITION`, `BRAKE_PARKING_INDICATOR` | ~500ms |
| Camera | View offset (custom camera state) | ~100ms |

### Fallback States

When no simulator is connected, all telemetry fields return zero/null values. The frontend displays "NO SIMCONNECT" / "SIMULATOR NOT CONNECTED" banners. No exceptions are raised — the app remains fully functional for planning and briefing even without an active sim session.

---

## 3. Real-World Flight Search Engine (`app/realworld.py`)

### Overview

The Real-World Schedules search engine queries live flight data from multiple providers, deduplicates results, and hydrates each flight record field-by-field using secondary data sources. This ensures every flight card in the Dispatch → Real-World Schedules tab has complete origin, destination, aircraft type, and estimated departure time — even when the primary provider returns partial data.

### Multi-Provider Architecture

```
User Input (origin, dest, callsign, aircraft — all optional)
        │
        ├──▶ Provider A: FlightRadar24
        │      • Airport resolution from local airports.csv (60K airports)
        │      • haversine bounding box: get_bounds_by_point(lat, lon, 100km)
        │      • get_flights(bounds=b) with browser-identity session headers
        │      • Zone sweep fallback (Europe, North America, Middle East)
        │
        ├──▶ Provider B: ADSB.lol (api.adsb.lol/v2)
        │      • /callsign/{cs} — exact callsign lookup
        │      • /type/{t} — aircraft type sweep
        │      • /lat/{lat}/lon/{lon}/dist/50 — bounding search
        │
        └──▶ Provider C: ADSB.fi (opendata.adsb.fi)
               • /api/v2/callsign/{cs} — exact callsign
               • /api/v2/type/{t} — type sweep
               • /api/v3/lat/{lat}/lon/{lon}/dist/50 — bounding (v3 = newer API)
        │
        ▼ asyncio.gather(*tasks, return_exceptions=True)
        │  (all three providers fire in parallel)
        │
        ▼ Deduplication
        │  • Primary key: hex_id (transponder code) → seen_hex set
        │  • Fallback key: callsign → seen_cs set
        │
        ▼ Flexible Filtering
        │  • callsign: prefix + substring match (DLH → DLH400, DLH8PK)
        │  • aircraft: partial match (A320 → A320, A20N, A321)
        │  • origin/dest: optional — blank = match all
        │
        ▼ Field-Level Hydration (asyncio.gather per flight)
        │  (runs AFTER dedup + filter to minimize costly API calls)
        │
        ▼ Flat JSON Array: [{callsign, origin, destination, aircraft, eobt, status}]
```

### Field-Level Hydration Pipeline

Each flight record is hydrated using a strict priority order. Hydration runs **after** deduplication and filtering — only the records the user actually sees trigger secondary API calls.

| Field | Priority 1 (FR24) | Priority 2 | Priority 3 | Fallback |
|---|---|---|---|---|
| **callsign** | `item.callsign` | ADSB.lol/fi (`flight`/`callsign` key) | — | *(guaranteed by dedup)* |
| **origin** | `item.origin_airport_icao` | Route DB (`api.adsbdb.com/v0/callsign/{cs}`) | Spatial proximity (≤20 NM, ≤10k ft) | Search ICAO |
| **destination** | `item.destination_airport_icao` | Route DB (`api.adsbdb.com`) | — | `"UNKNOWN"` |
| **aircraft** | `item.aircraft_code` | ADSB.lol (`t` type field, from merge) | ADSB.fi | `"A320"` |
| **eobt** | `item.departure_scheduled_time` | OpenSky VPS proxy | — | Live telemetry state (`"AIRBORNE"` / `"ON GROUND"`) |
| **status** | — | — | — | Derived from altitude (>10k ft → `"AIRBORNE"`) |

### Spatial Proximity Check

Uses the **Haversine formula** for great-circle distance:

```
a = sin²(Δlat/2) + cos(lat1)·cos(lat2)·sin²(Δlon/2)
c = 2 · atan2(√a, √(1−a))
d = 3440.065 · c   (nautical miles)
```

An aircraft is inferred to have departed from the search origin if:
- Distance ≤ **20 nautical miles** from the origin airport
- Altitude ≤ **10,000 feet** (or on ground)

This catches aircraft that are airborne and climbing within the terminal area — FR24 may have already dropped their origin field for airborne aircraft, but the spatial check recovers it.

### FR24 Browser Identity Headers

FlightRadar24's unofficial API is protected by Cloudflare bot-detection. The app injects browser-identity headers into the `requests.Session` used by `FlightRadar24API`:

```python
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.flightradar24.com/",
})
fr24.request = session
```

### OpenSky VPS Proxy Integration

For EOBT (Estimated Off-Block Time) hydration, the desktop app queries the website proxy:

```
Desktop App ──▶ GET https://admin.opsroom.live/api/v1/realworld-search
                     ?callsign=DLH400&origin=EDDF
                     (public — no authentication required)
                                   │
                                   ▼
              opsroom-website (admin-api/opensky.py)
                     │  OAuth2 client_credentials
                     │  OPENSKY_CLIENT_ID + OPENSKY_CLIENT_SECRET
                     ▼
              OpenSky Network API
              • Departure search: /api/flights/departure?airport=EDDF&begin=...&end=...
              • Global search: /api/states/all (callsign-only queries)
```

**Website proxy response format:**

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

**Graceful fallback:** If the proxy is unreachable, times out, or returns an error, the EOBT field falls through to the live telemetry state — `"AIRBORNE"` if altitude > 10,000 ft, otherwise `"ON GROUND"`. No unhandled exceptions, no error toasts, no UI disruption.

### Internal Caching Strategy

| Cache | Location | Key | TTL | Purpose |
|---|---|---|---|---|
| **Airport Index** | Module-level `_AIRPORT_INDEX` dict | ICAO/IATA ident | ∞ (loaded once) | Coordinate resolution for bounding boxes |
| **Route DB Cache** | Module-level `_ROUTE_CACHE` dict | callsign (upper) | 6 hours | Avoid redundant `adsbdb.com` calls |
| **OpenSky Proxy Cache** | Website-side `_CACHE` dict | `origin|dest|callsign|aircraft` | 60 seconds | Reduce OpenSky API calls from desktop |
| **FR24 Session** | Per-request | — | Single search | Browser headers for Cloudflare bypass |

---

## 4. Concurrency & Async Architecture

### Execution Model

The application uses a hybrid sync/async model:

| Component | Model | Rationale |
|---|---|---|
| **FastAPI routes** | `async def` | Native async I/O for HTTP, WebSocket |
| **SimConnect polling** | Background `threading.Thread` | SimConnect SDK is synchronous C++ |
| **FR24 API calls** | `loop.run_in_executor()` (thread pool) | FlightRadar24API is synchronous |
| **ADSB fetches** | `httpx.AsyncClient` | Native async HTTP |
| **Route DB / OpenSky proxy** | `httpx.AsyncClient` | Native async HTTP |
| **File I/O (airports.csv, settings)** | Synchronous (module load / startup) | Small files, one-time load |
| **Logger I/O** | Synchronous (stdlib `logging`) | Thread-safe handler |

### Parallel Provider Fetching

All three providers fire simultaneously:

```python
tasks = [
    asyncio.ensure_future(_fr24_fetch(...)),       # Provider A
    asyncio.ensure_future(_adsb_for_path(...)),     # Provider B+C (batched)
]
results = await asyncio.gather(*tasks, return_exceptions=True)
# Exceptions are collected, not raised — one failing provider
# never blocks the others.
```

### Per-Flight Hydration

After deduplication and filtering, each flight is hydrated in parallel:

```python
hydrated = await asyncio.gather(*[
    _hydrate_one_flight(f, search_origin, origin_coords)
    for f in filtered
])
```

This means 50 filtered flights all hydrate simultaneously — Route DB lookups and OpenSky proxy calls for different flights run concurrently.

---

## 5. ChartFox OAuth2 & Chart Proxy (`app/charts.py`)

### OAuth2 PKCE Flow (Public Client)

The desktop app uses the Authorization Code + PKCE flow — appropriate for a public client that cannot securely store a client secret:

1. User clicks "Connect ChartFox" → app generates `code_verifier` + `code_challenge` (SHA-256)
2. Browser opens `https://api.chartfox.org/oauth/authorize?client_id=019f9162-...&redirect_uri=...&code_challenge=...&scope=charts:index charts:view charts:files charts:view_source_url`
3. User authenticates on ChartFox.org
4. ChartFox redirects to `http://localhost:8080/api/charts/chartfox/callback?code=...&state=...`
5. Backend exchanges `code` + `code_verifier` for Bearer token at `https://api.chartfox.org/oauth/token`
6. Token (access + refresh) stored in app data directory (`settings.json`)

**Scopes requested:** `charts:index charts:view charts:files charts:view_source_url`

### Chart API Proxy

All ChartFox API calls are proxied through the local FastAPI server:

```python
# Grouped charts for an airport
GET /api/charts/chartfox/proxy/grouped/{icao}
  → GET https://api.chartfox.org/v2/airports/{icao}/charts/grouped
     Authorization: Bearer <token>

# Single chart detail (includes files[], source_url, georefs)
GET /api/charts/chartfox/proxy/chart/{chart_id}
  → GET https://api.chartfox.org/v2/charts/{chart_id}
     Authorization: Bearer <token>

# Chart file binary (PDF/IMG)
GET /api/charts/chartfox/proxy/file?url=<encoded_url>
  → GET <chartfox_file_url>
     Authorization: Bearer <token>
```

### Geo-Reference Overlay Computation

When a chart has `georefs` data (requires `charts:geos` scope), the backend computes WGS84 → canvas transformations:

```python
def _chartfox_overlay_compute(georefs, chart_width, chart_height):
    """Compute transformation parameters from geo-reference metadata."""
    # georefs[i] = {tx, ty, k, transform_angle, pdf_page_rotation, page}
    # Returns normalized {tx, ty, k, transform_angle} for the frontend
```

The frontend then uses these parameters to plot the aircraft's real-time position as a pulsing green dot on the chart canvas.

---

## 6. Other Key Backend Modules

### Updater (`app/updater.py` — 525 lines)

Dual-channel auto-updater that polls two manifest URLs:

```python
PRIMARY_MANIFEST_URL = "https://opsroom.live/api/update.json"
FALLBACK_MANIFEST_URL = "https://raw.githubusercontent.com/OpsRoomApp/ops-room-releases/main/update.json"
DOWNLOAD_TIMEOUT = 25  # seconds per attempt
DEFAULT_VERSION = "0.25.55"
```

The `Version` dataclass parses and compares semantic versions. `check_for_update()` tries primary first, falls back to GitHub on any error (DNS, timeout, HTTP error, invalid JSON). `prepare_update()` downloads and verifies the ZIP SHA-256 before staging.

### Black Box Recorder (`app/black_box.py`)

Recording Schema v2 captures:
- Telemetry stream (position, attitude, speed, systems)
- FO sidestick fields (extended schema v2)
- PMDG SDK enrichment (door/flap enum labels)
- FSUIPC log tail

Exports: CSV, GPX, KML. Recovery of interrupted recordings on startup.

### Hoppie ACARS Client (`app/hoppie_client.py`)

Background thread polls Hoppie ACARS network. Supports:
- CPDLC message dispatch (logon, send, reply)
- PDC (Pre-Departure Clearance) requests
- Auto-print via thermal printer integration
- WebSocket push to frontend Comms module

### GSX Pro Integration (`app/gsx_remote.py`)

State machine monitors GSX Pro process:
- States: idle → boarding → refueling → pushback → deboarding
- Automation: auto-start sequence from SimBrief plan
- **READ-ONLY** — never modifies GSX state
- Receipt file management via `gsx_receipts.py`

### Thermal Printer Engine (`app/printer_client.py`)

- **Protocols:** ESC/POS (USB raw), TCP socket (IP printers), Windows spooler
- **Features:** Printer enumeration, test print, CPDLC auto-print, 80mm receipt preview
- **Preview:** Virtual thermal receipt HTML generated at `POST /api/printer/preview`

### RAAS / vRAAS (`app/raas.py`, `app/raas_audio.py`)

Virtual Runway Awareness and Advisory System:
- Runway proximity alerts
- Takeoff/landing callouts
- Configurable voice path
- Unit selection (feet/metres)
- Global hotkey toggle
