# OPS ROOM — Database, Cache & Storage Schemas

**Version:** v0.25.59
**Last Updated:** 2026-07-31

---

## 1. Persistence Architecture Overview

OPS ROOM uses a layered persistence model:

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 1: localStorage (WebView2 browser)                    │
│  ───────────────────────────────────────────────────────────│
│  Keys: or_settings, cf_pins, cf_dark_mode, cf_annot_*,       │
│        or_cache, or_logs                                     │
│  Purpose: UI state, user preferences, annotation strokes     │
│  Lifetime: Survives app restart; cleared on WebView2 cache   │
│           reset at startup (ClearBrowsingDataAsync)          │
└──────────────────────────────────────────────────────────────┘
                              │
┌──────────────────────────────▼───────────────────────────────┐
│  Layer 2: App Data Directory (filesystem)                    │
│  ───────────────────────────────────────────────────────────│
│  Location: %APPDATA%/OPS ROOM/                               │
│  Files: settings.json, version.json, update.json,            │
│         chartfox_token.json, opsroom.log,                    │
│         logbook.db (SQLite), black_box/*.sqlite3             │
│  Purpose: Persistent app state, credentials, recordings      │
│  Lifetime: Never auto-cleared (user-managed)                 │
└──────────────────────────────────────────────────────────────┘
                              │
┌──────────────────────────────▼───────────────────────────────┐
│  Layer 3: In-Memory Caches (Python module-level dicts)        │
│  ───────────────────────────────────────────────────────────│
│  Purpose: Avoid redundant network calls within runtime        │
│  Lifetime: App process lifetime (cleared on restart)          │
│  Examples: _AIRPORT_INDEX, _ROUTE_CACHE, _CACHE (proxy)      │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. App Data Directory (`%APPDATA%/OPS ROOM/`)

### Path Resolution

```python
def app_data_dir() -> Path:
    """Returns the OPS ROOM app data directory."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", ""))
    else:
        base = Path.home() / ".config"
    return base / "OPS ROOM"
```

### File Inventory

| File | Format | Purpose | Schema |
|---|---|---|---|
| `settings.json` | JSON | Full settings object | `{ identity: {vatsim_cid, simbrief_user_id}, integrations: {hoppie_configured, announcements_enabled, ...}, server: {port, lan_enabled, ...}, interface: {setup_completed, ...} }` |
| `chartfox_token.json` | JSON | OAuth2 token | `{ access_token, refresh_token, expires_at, scope, token_type }` |
| `version.json` | JSON | Build version manifest | `{ version: "0.25.59", build: "public-release" }` |
| `update.json` | JSON | Latest fetched update manifest | `{ version, download_url, sha256, release_notes }` |
| `update_state.json` | JSON | Staged update state | `{ staged_version, staged_path, ready: bool }` |
| `opsroom.log` | Plain text | Rotating application log | Timestamped log lines (UTF-8, errors=replace) |
| `logbook.db` | SQLite | Flight logbook | `entries(id, date, origin, destination, callsign, aircraft, duration, score, notes, ...)` |
| `black_box/*.sqlite3` | SQLite | Flight recordings | Telemetry samples with timestamps |
| `cache/charts/` | Directory | ChartFox cached chart files | PDF/IMG files keyed by chart UUID |

---

## 3. SQLite Schemas

### Logbook (`logbook.db`)

```sql
CREATE TABLE IF NOT EXISTS entries (
    id TEXT PRIMARY KEY,           -- UUID
    date TEXT NOT NULL,            -- ISO 8601 date
    origin TEXT NOT NULL,          -- ICAO code
    destination TEXT NOT NULL,     -- ICAO code
    callsign TEXT,                 -- Flight callsign
    aircraft TEXT,                 -- Aircraft type (e.g., "A320")
    duration_min INTEGER,         -- Flight duration in minutes
    score REAL,                    -- PIREP score (0-100)
    notes TEXT,                    -- Free-text notes
    raw_data JSON,                 -- Full telemetry summary
    created_at TEXT NOT NULL,     -- ISO 8601 timestamp
    updated_at TEXT NOT NULL      -- ISO 8601 timestamp
);
```

### Black Box Recordings (`black_box/{recording_id}.sqlite3`)

```sql
CREATE TABLE IF NOT EXISTS samples (
    ts REAL NOT NULL,              -- Unix timestamp (seconds)
    lat REAL,                      -- Latitude
    lon REAL,                      -- Longitude
    alt REAL,                      -- Altitude (feet)
    hdg REAL,                      -- Heading (degrees)
    ias REAL,                      -- Indicated airspeed (knots)
    gs REAL,                       -- Ground speed (knots)
    vs REAL,                       -- Vertical speed (ft/min)
    mach REAL,                     -- Mach number
    on_ground INTEGER,             -- 0 or 1
    com1 REAL,                     -- COM1 active frequency
    com2 REAL,                     -- COM2 active frequency
    xpdr INTEGER,                  -- Transponder code
    gear REAL,                     -- Gear position
    flaps REAL,                    -- Flaps position
    spoilers REAL,                 -- Spoiler position
    parking_brake INTEGER,         -- 0 or 1
    ail REAL,                      -- Aileron position (FO stick, schema v2)
    ele REAL,                      -- Elevator position (FO stick, schema v2)
    rud REAL,                      -- Rudder position (FO stick, schema v2)
    PRIMARY KEY (ts)
);
```

### Recording Metadata Table

```sql
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
-- Keys: callsign, origin, destination, aircraft, started_at, ended_at, schema_version
```

---

## 4. In-Memory Caches (Python)

### Airport Index (`_AIRPORT_INDEX`)

| Property | Value |
|---|---|
| **Module** | `app/realworld.py` |
| **Type** | `dict[str, tuple[float, float]]` |
| **Key** | ICAO or IATA code (upper) |
| **Value** | `(latitude, longitude)` float tuple |
| **TTL** | ∞ (loaded once at module import) |
| **Source** | `app/data/airports.csv` (~60K airports) |
| **Size** | ~60K entries, ~2MB in memory |
| **Invalidation** | Never — CSV doesn't change between builds |

### Route DB Cache (`_ROUTE_CACHE`)

| Property | Value |
|---|---|
| **Module** | `app/realworld.py` |
| **Type** | `dict[str, tuple[float, str, str]]` |
| **Key** | callsign (upper) |
| **Value** | `(timestamp, origin_icao, destination_icao)` |
| **TTL** | 6 hours (`_ROUTE_CACHE_TTL = 6 * 3600`) |
| **Source** | `https://api.adsbdb.com/v0/callsign/{cs}` |
| **Eviction** | Lazy — expired entries removed on access |
| **Write** | `_route_cache_put(callsign, origin, dest)` |

### OpenSky Proxy Cache (`_CACHE`)

| Property | Value |
|---|---|
| **Module** | `opsroom-website/admin-api/opensky.py` |
| **Type** | `dict[str, dict[str, Any]]` |
| **Key** | `{origin}\|{dest}\|{callsign}\|{aircraft}` |
| **Value** | `{timestamp: float, data: dict}` (full API response) |
| **TTL** | 60 seconds (`_CACHE_TTL`) |
| **Source** | OpenSky Network API (departure + states/all) |
| **Eviction** | Lazily checked on access |
| **Size** | No explicit limit (default dict growth, bounded by diverse key space) |

### ChartFox Chart Cache

| Property | Value |
|---|---|
| **Module** | `app/charts.py` |
| **Type** | `@lru_cache` on detail/grouped endpoints |
| **Key** | Chart UUID or airport ICAO |
| **TTL** | Per-function `lru_cache(maxsize=128)` |
| **Eviction** | LRU — least recently used dropped when full |
| **Location** | Server memory (not disk) |

### Module Preloader Cache

| Property | Value |
|---|---|
| **Module** | `app/module_preloader.py` |
| **Purpose** | Prewarm caches on startup to eliminate cold fetch on first module switch |
| **Registered endpoints** | `briefing`, `dispatch_context`, `flight_watch`, `ground_preferences`, `black_box_status`, `dispatch_recommendations` |
| **Prewarm** | `_preloader_prewarm_all()` runs in background thread on startup |

---

## 5. Frontend `localStorage` Schemas

### `or_settings`

```json
{
  "identity": {
    "vatsim_cid": "1234567",
    "simbrief_user_id": "12345"
  },
  "integrations": {
    "hoppie_configured": true,
    "simbrief_auto_load": true,
    "announcements_enabled": false,
    "gsx_departure_catering": true,
    "gsx_departure_water": true
  },
  "server": {
    "port": 8080,
    "lan_enabled": false
  },
  "interface": {
    "setup_completed": true,
    "rail_collapsed": false,
    "classic_rail": false,
    "terminal_style": "efb",
    "streamer_mode": false
  },
  "updates": {
    "enabled": true,
    "check_on_startup": true
  }
}
```

### `cf_pins`

```json
["6872384f-a9d3-4513-a1e5-d2e99e2b9dfb", "abcc6779-f73a-48f2-b168-79f41fe99d3f"]
```

Array of ChartFox chart UUIDs pinned by the user.

### `cf_dark_mode`

```json
"true"
```

String `"true"` or `"false"`. Controls the `cf-canvas-dark` CSS filter class.

### `cf_annot_{chart_uuid}`

```json
{
  "strokes": [
    {
      "tool": "pen",
      "color": "#efbd47",
      "width": 3.5,
      "opacity": 0.85,
      "points": [
        {"rx": 0.123, "ry": 0.456, "t": 1785360000},
        {"rx": 0.234, "ry": 0.567, "t": 1785360001}
      ]
    }
  ],
  "version": 2
}
```

Strokes are stored as normalized PDF-page ratios (`rx`, `ry` relative to native dimensions) for coordinate anchoring across zoom levels.

### `or_cache`

```json
{
  "metar": { "EDDF": { "ts": 1785360000, "data": "..." } },
  "atis": { "EDDF": { "ts": 1785360000, "data": {...} } }
}
```

General-purpose frontend cache. Keys are arbitrary; values have `ts` (timestamp) and `data` fields.

### `or_logs`

```json
[
  { "ts": 1785360000, "entry": "OPS ROOM v0.25.59 started" },
  { "ts": 1785360000, "entry": "SimConnect connected: MSFS 2024" }
]
```

Startup and operational log entries, visible in the host console.

---

## 6. Cache Invalidation Policies

### On App Restart

| Cache | Cleared? | Reason |
|---|---|---|
| `localStorage` entries | **Yes** (WebView2 `ClearBrowsingDataAsync` on startup) | Prevents stale UI state, pinned charts, annotations from old versions |
| App data files | **No** | Persistent — settings, logbook, recordings survive restarts |
| Python in-memory caches | **Yes** (process restart) | Inherent — module-level dicts created fresh on import |
| ChartFox chart files in `cache/charts/` | **Yes** (background daemon cleanup on startup) | Prevents accumulation of stale PDFs across versions |

### On Version Update

| Cache | Action |
|---|---|
| `or_settings` | Preserved (loaded from server `settings.json`), not localStorage |
| `cf_pins` | Cleared by WebView2 cache reset; users re-pin after update |
| `cf_annot_*` | Cleared by WebView2 cache reset |
| `logbook.db` | **Preserved** — migrated if schema changes (additive columns only) |
| `black_box/*.sqlite3` | **Preserved** — never auto-deleted |
| `chartfox_token.json` | Preserved — token may still be valid across versions |
| `_ROUTE_CACHE` | Cleared (process restart) — acceptable; routes are stable and re-fetched lazily |

### Manual Cleanup

Users can clear logs and diagnostics from the System page:

```python
# POST /api/diagnostics/clear-local-cache
{
  "logs": true,        # Delete opsroom.log rotation archives
  "diagnostics": true, # Delete cached diagnostic ZIPs
  "map_cache": false   # Preserve OpenLayers tile cache (expensive to rebuild)
}
```

---

## 7. Key Namespace Summary

| Namespace | Layer | Key Format | Example |
|---|---|---|---|
| `cf_pins` | localStorage | Static key | `cf_pins` |
| `cf_dark_mode` | localStorage | Static key | `cf_dark_mode` |
| `cf_annot_*` | localStorage | `cf_annot_{uuid}` | `cf_annot_6872384f-a9d3-4513-a1e5-d2e99e2b9dfb` |
| `or_settings` | localStorage | Static key | `or_settings` |
| `or_cache` | localStorage | Static key | `or_cache` |
| `or_logs` | localStorage | Static key | `or_logs` |
| `_AIRPORT_INDEX` | Python memory | `{icao}` | `"EDDF"` |
| `_ROUTE_CACHE` | Python memory | `{callsign}` | `"DLH400"` |
| `_CACHE` (proxy) | Python memory | `{origin}\|{dest}\|{callsign}\|{aircraft}` | `"EDDF\|\|DLH400\|"` |
| `logbook.db` | SQLite | `entries.id` | UUID |
| `black_box/*.sqlite3` | SQLite | `samples.ts` | Unix timestamp (float) |
| `chartfox_token.json` | Filesystem | Static filename | `chartfox_token.json` |
| `settings.json` | Filesystem | Static filename | `settings.json` |

---

## 8. Spatial Proximity Cache (Haversine)

Not a traditional cache — the Haversine formula is computed on-demand per flight. It does use the **airport index** (`_AIRPORT_INDEX`) for coordinate lookup, which is a one-time load from `airports.csv`.

```python
_EARTH_RADIUS_NM = 3440.065  # nautical miles

def _haversine_nm(lat1, lon1, lat2, lon2):
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return _EARTH_RADIUS_NM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
```

No caching needed — the computation is pure math with no external I/O.

---

## 9. Storage Maintenance Best Practices

1. **ChartFox cache cleanup runs on every cold start** — background daemon thread, non-blocking
2. **FSUIPC log mitigation runs on startup** — best-effort, never blocks if share-locked
3. **Manual cache clearing available** from System page or via API
4. **WebView2 cache reset at startup** prevents stale UI from old builds
5. **Recording files never auto-deleted** — user-managed to prevent data loss
6. **Log rotation** via `RotatingTextLog` with size-based rollover
