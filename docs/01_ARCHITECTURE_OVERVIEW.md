# OPS ROOM — Architecture Overview & System Blueprint

**Version:** v0.25.48  
**Last Updated:** 2026-07-31

---

## 1. System Concept & Scope

**OPS ROOM** is a Windows-native flight simulation operations centre — a desktop application that brings airline-grade dispatch, real-time telemetry tracking, chart briefing, ACARS messaging, and real-world flight schedule hydration into a single integrated cockpit companion. It connects directly to Microsoft Flight Simulator (MSFS 2020 / 2024) via SimConnect and to the VATSIM online network, providing a unified interface that spans pre-flight planning, in-flight monitoring, and post-flight analysis.

### Core Use Cases

| Use Case | Modules Involved | External Dependencies |
|---|---|---|
| **Pre-Flight Dispatch** | Dispatch form, SimBrief auto-fetch, Real-World Schedules search | SimBrief API, OpenSky Network, FlightRadar24, ADSB.lol/fi |
| **Chart Briefing** | Charts module (ChartFox OAuth), PDF.js rendering, geo-referencing | ChartFox API v2 |
| **Real-Time Telemetry** | Flight Watch, Black Box recording, Systems dashboard | SimConnect (MSFS), FSUIPC |
| **ACARS / CPDLC** | Network/Comms module, Hoppie ACARS client, thermal printer | Hoppie ACARS network |
| **ATC / VATSIM** | VATSIM FIDS board, vPilot bridge, METAR/ATIS display | VATSIM data feed, vPilot |
| **Procedures & Checklists** | SOP engine, non-normal profiles, economy scoring | — |
| **Post-Flight Analysis** | PIREP generation, logbook, Black Box replay | — |
| **Real-World Schedule Search** | Dispatch → Real-World Schedules tab | FR24, ADSB.lol/fi, adsbdb.com, OpenSky proxy |

---

## 2. System Topology

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         Flight Simulator (MSFS 2020/2024)                  │
│                              SimConnect API                                │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │
                ┌───────────────┴───────────────┐
                │                               │
    ┌───────────▼───────────┐     ┌─────────────▼─────────────┐
    │  Camera Bridge 2024    │     │   OPS ROOM Desktop App     │
    │  (C++ / SimConnect)    │     │   (Python 3.11 / FastAPI)  │
    │  MSFS camera control   │     │   Embedded WebView2 SPA    │
    └───────────────────────┘     └─────────────┬───────────────┘
                                                │
                        ┌───────────────────────┼───────────────────────┐
                        │                       │                       │
            ┌───────────▼───────┐   ┌───────────▼───────┐   ┌───────────▼───────┐
            │  ChartFox API v2   │   │  OpenSky Proxy     │   │  VATSIM Data Feed  │
            │  (OAuth2 PKCE)     │   │  admin.opsroom.live│   │  (Public JSON)     │
            │  charts, geo-ref   │   │  /api/v1/          │   │  METAR, ATIS, FIDS │
            └────────────────────┘   │  realworld-search  │   └───────────────────┘
                                     └─────────┬─────────┘
                                               │ OAuth2 client_credentials
                                     ┌─────────▼─────────┐
                                     │  OpenSky Network   │
                                     │  opensky-network   │
                                     │  .org API          │
                                     └───────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│                          External Data Providers                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ FlightRadar24 │  │  ADSB.lol    │  │  ADSB.fi     │  │  adsbdb.com  │ │
│  │ (FR24 API)   │  │  (v2)        │  │  (v2/v3)     │  │  (Route DB)  │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘ │
│  ┌──────────────┐  ┌──────────────┐                                      │
│  │  SimBrief API │  │ Hoppie ACARS │                                      │
│  └──────────────┘  └──────────────┘                                      │
└──────────────────────────────────────────────────────────────────────────┘
```

### Key Architectural Principle

The desktop app (`opsroom-app`) communicates with the OpenSky proxy (`admin.opsroom.live`) via **unauthenticated public HTTPS**. All OpenSky OAuth2 credentials (`OPENSKY_CLIENT_ID`, `OPENSKY_CLIENT_SECRET`) reside **exclusively** on the VPS backend. The desktop app never sees, stores, or handles these credentials — it queries a public proxy endpoint that handles authentication internally.

---

## 3. Tech Stack

### Desktop Application (`opsroom-app`)

| Layer | Technology | Version / Notes |
|---|---|---|
| **Runtime** | Python | 3.11 |
| **Web Framework** | FastAPI | 0.115+ |
| **ASGI Server** | Uvicorn | 0.30+ |
| **HTTP Client** | httpx, requests | Async + sync dual-stack |

### Python Dependencies (`requirements_shipping.txt`)

| Package | Version | Purpose |
|---|---|---|
| `fastapi` | >=0.115.0, <1.0 | Web framework, REST routes, WebSocket |
| `uvicorn` | >=0.30.0, <1.0 | ASGI server |
| `websockets` | >=12.0, <16.0 | WebSocket protocol |
| `requests` | >=2.31.0, <3.0 | Synchronous HTTP (FR24 session) |
| `httpx` | >=0.28.0, <1.0 | Async HTTP (ADSB, Route DB, OpenSky proxy) |
| `SimConnect` | ==0.4.26 | MSFS SimConnect SDK bindings |
| `pywebview` | ==6.2.1 | Embedded WebView2 browser control |
| `pygame` | >=2.5.2, <3.0 | Audio engine for RAAS, announcements |
| `qrcode[pil]` | >=8.0, <9.0 | QR code for server info |
| `reportlab` | >=4.2, <5.0 | PDF generation (PIREP, logbook export) |
| `pystray` | >=0.19.5, <1.0 | System tray icon |
| `PyMuPDF` | >=1.24, <2.0 | PDF manipulation utilities |
| `tzdata` | >=2025.2, <2027.0 | IANA timezone database |
| `FlightRadarAPI` | >=1.5.0 | Unofficial FR24 API wrapper |
| **Browser Engine** | Microsoft Edge WebView2 | Embedded Chromium |
| **Simulator Bridge** | SimConnect (MSFS SDK) | Native Windows |
| **Database** | SQLite (via stdlib `sqlite3`) | Local app data |
| **PDF Rendering** | PDF.js | Bundled static library |
| **CSS Framework** | Vanilla CSS Grid + Flexbox | Custom design system |
| **Packaging** | PyInstaller | One-folder bundle |
| **Installer** | Inno Setup 7 | Optional additive step |

### Website Backend (`opsroom-website`)

| Layer | Technology | Version / Notes |
|---|---|---|
| **Runtime** | Python | 3.11 |
| **Web Framework** | FastAPI | 0.115+ |
| **Container** | Docker + Docker Compose | Production VPS |
| **Reverse Proxy** | Nginx | SSL termination |
| **Auth (Admin)** | GitHub OAuth App | JWT session tokens |
| **OpenSky Auth** | OAuth2 Client Credentials | Keycloak realm |

### Frontend (SPA)

| Layer | Technology |
|---|---|
| **Language** | Vanilla JavaScript (ES6+) |
| **State Management** | Global vanilla objects (`opsState`, `cfState`) + `localStorage` |
| **DOM Updates** | Direct element manipulation (no virtual DOM) |
| **Real-Time** | WebSocket (native `WebSocket` API) |
| **Maps** | OpenLayers |
| **Charts** | PDF.js + HTML5 Canvas (annotation layer) |
| **Styling** | Vanilla CSS with custom properties (design tokens) |

---

## 4. Module Inventory (`app/` — 62 Python Files)

| Module | Lines | Responsibility |
|---|---|---|
| `main.py` | ~2600 | FastAPI application factory, 170+ routes, WebSocket, subsystem orchestration |
| `charts.py` | 1582 | ChartFox OAuth2 PKCE flow, v2 API proxy, chart file serving, cache, geo-ref computation |
| `realworld.py` | ~560 | Multi-provider flight search engine, field-level hydration |
| `system_status.py` | 149 | Health checks, diagnostics, build info, GSX root detection |
| `updater.py` | 525 | Dual-channel update manifest polling, download, staging |
| `settings_store.py` | — | App data directory, settings load/save, Hoppie code management |
| `simconnect_position.py` | — | MSFS telemetry (position, radios, cameras, autopilot) |
| `telemetry_provider.py` | — | Telemetry abstraction layer, provider selection |
| `simbrief_client.py` | — | SimBrief OFP fetch, parse, cache |
| `hoppie_client.py` | — | ACARS/CPDLC message dispatch over Hoppie network |
| `vatsim_client.py` | — | VATSIM FIDS/METAR/ATIS data fetching |
| `vpilot_bridge.py` | — | vPilot Mode C, Ident, frequency sync |
| `gsx_remote.py` | — | GSX Pro integration state machine and automation |
| `black_box.py` | — | Flight recording engine (Schema v2) |
| `black_box_replay.py` | — | Recording replay with time-synced playback |
| `printer_client.py` | — | ESC/POS thermal printer engine, receipt preview |
| `raas.py` | — | Virtual Runway Awareness and Advisory System |
| `raas_audio.py` | — | vRAAS audio clip management |
| `announcements.py` | — | Cabin announcement dispatch engine |
| `announcement_hotkeys.py` | — | Global hotkey service for announcements |
| `dispatch_engine.py` | — | Dispatch route recommendations |
| `dispatch_state.py` | — | Active dispatch persistence |
| `flight_watch.py` | — | Real-time flight watch dashboard |
| `procedures.py` | — | SOP/checklist engine |
| `performance.py` | — | Takeoff/landing performance calculator |
| `economy.py` | — | Finance and career scoring module |
| `logbook.py` | — | Flight logbook with CSV/JSON/PDF export |
| `scratchpad.py` | — | Persistent text scratchpad |
| `camera_bridge.py` | — | Camera Bridge 2024 process manager |
| `camera_state.py` | — | Camera view state (target, zoom, offset) |
| `obs_branding.py` | — | OBS overlay logo management |
| `airline_branding.py` | — | Airline identity resolution and branding |
| `airline_theme.py` | — | Dynamic theme palette from airline livery |
| `navdata.py` | — | Compact MSFS runway cache |
| `map_data.py` | — | Live map data pipeline |
| `map_tiles.py` | — | Map tile serving |
| `network_status.py` | — | VATSIM/IVAO network status |
| `board_logic.py` | — | Traffic board logic and ranking |
| `briefing_data.py` | — | Operational briefing aggregation |
| `bug_report.py` | — | Diagnostics ZIP generation |
| `device_security.py` | — | LAN device pairing and trust |
| `server_info.py` | — | QR code and server info |
| `storage_maintenance.py` | — | Log/cache cleanup |
| `module_preloader.py` | — | Cache prewarming on startup |
| `fenix_adapter.py` | — | Fenix A320 adapter |
| `pmdg777_sdk.py` | — | PMDG 777 SDK integration |
| `pmdg777_eula.py` | — | PMDG 777 EULA gate |
| `weather_client.py` | — | METAR/ATIS fetch (VATSIM + real-world) |
| `pirep_analysis.py` | — | PIREP scoring and analysis |
| `aviation_data.py` | — | Aviation reference data |
| `fsuipc_manager.py` | — | FSUIPC7 lifecycle and log management |
| `gsx_receipts.py` | — | GSX receipt file management |
| `host_attention.py` | — | Flash host window on ATC alert |
| `logging_utils.py` | — | Log rotation, privacy redaction |
| `managed_keys.py` | — | Build-time API key injection |
| `non_normal_profiles.py` | — | Non-normal checklist profiles |
| `notifications.py` | — | Notification status |
| `passenger_satisfaction.py` | — | Passenger satisfaction scoring |
| `procedure_profiles.py` | — | Aircraft-specific procedure profiles |
| `replay_guard.py` | — | Prevents replay during active recording |
| `vatspy_boundaries.py` | — | VATSpy FIR boundary data |
| `vpilot_installer.py` | — | vPilot bridge installer |
| `data_loader.py` | — | Airport data loader and search |
| `aircraft_adapter_catalog.py` | — | Aircraft adapter registry |
| `aircraft_adapter_installer.py` | — | Adapter installation |
| `aircraft_adapters.py` | — | Adapter runtime |
| `addon_telemetry.py` | — | Addon telemetry |
| `fenix_gsx_loading_state_machine.py` | — | Fenix GSX loading state |

---

## 5. Static Assets (`app/static/`)

| File | Lines | Purpose |
|---|---|---|
| `opsroom.js` | 6925 | Global state engine, all module UI logic, ChartFox rendering, real-world search, comms, WebSocket handling |
| `opsroom.css` | ~2363 | Design system, dark theme, chart viewer layout, systems grid, responsive behaviour |
| `app.js` | — | ATIS/FIDS display SPA |
| `host.js` | — | Host settings and configuration management |
| `host.css` | — | Host console styles |
| `index.html` | 987 | Single-page app shell with all module containers |
| `host.html` | — | Host console HTML |
| `traffic_board.html` | — | VATSIM FIDS standalone view |
| `obs.html` / `obs.css` / `obs.js` | — | OBS Studio overlay |
| `pirep.html` / `pirep.css` / `pirep.js` | — | PIREP viewer |
| `pirep_print.css` / `pirep_print.js` | — | PIREP print stylesheet |
| `scoring_rules.html` | — | Scoring rules reference |
| `service-worker.js` | — | PWA offline caching |
| `styles.css` | — | Shared base styles |
| `pdf.min.js` | — | PDF.js library |
| `pdf.worker.min.js` | — | PDF.js web worker |

---

## 6. Environment Configuration & Security Model

### Desktop App Environment Variables

The desktop app requires **zero secrets** to function. It ships as a compiled binary with no embedded credentials.

| Variable | Purpose | Required? | Default |
|---|---|---|---|
| `OPSROOM_VPS_URL` | Override the OpenSky proxy endpoint | No | `https://admin.opsroom.live/api/v1/realworld-search` |

**Removed variables** (no effect if set): `OPSROOM_VPS_USER`, `OPSROOM_VPS_PASS`

### Website VPS Environment Variables

All secrets on the website are loaded from `.env` at container startup. No fallback defaults exist in source code.

| Variable | Purpose | Required? |
|---|---|---|
| `OPENSKY_CLIENT_ID` | OpenSky Network OAuth2 client ID | Yes |
| `OPENSKY_CLIENT_SECRET` | OpenSky Network OAuth2 client secret | Yes |
| `GITHUB_CLIENT_ID` | GitHub OAuth App client ID (for admin panel) | Yes |
| `GITHUB_CLIENT_SECRET` | GitHub OAuth App client secret | Yes |
| `JWT_SECRET` | JWT signing key for admin sessions | Yes |
| `STRIPE_SECRET_KEY` | Stripe secret key (payment features) | No |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook secret | No |
| `APPROVED_GITHUB_USERS` | Comma-separated GitHub usernames for admin access | Yes |

### Security Isolation

```
┌─────────────────────────────────────────────┐
│  Desktop App (compiled .exe)                 │
│  ─────────────────────────────────────────  │
│  • Zero embedded secrets                     │
│  • Public-only API calls                     │
│  • ChartFox token: user-scoped, OAuth2,      │
│    stored in local app data (not source)     │
│  • OpenSky: queried via public proxy         │
└─────────────────────────────────────────────┘
                    │  HTTPS (no auth)
                    ▼
┌─────────────────────────────────────────────┐
│  Website VPS (admin.opsroom.live)            │
│  ─────────────────────────────────────────  │
│  • All secrets in .env (never committed)     │
│  • OAuth2 client_credentials for OpenSky     │
│  • OAuth2 authorization_code for GitHub     │
│  • JWT sessions for admin panel              │
└─────────────────────────────────────────────┘
```

---

## 7. Process Lifecycle

```
opsroom_launcher.py (462 lines)
        │
        ├─▶ Load settings from app data directory
        ├─▶ Start FSUIPC7 if configured
        ├─▶ Boot FastAPI via uvicorn on localhost:{port}
        ├─▶ Launch WebView2 browser → localhost:{port}
        ├─▶ Warm SimBrief OFP cache (background thread)
        ├─▶ Start telemetry engine
        ├─▶ Run ChartFox cache cleanup (background daemon)
        ├─▶ Recover interrupted Black Box recordings
        ├─▶ Prewarm module caches
        ├─▶ Start announcement engine
        ├─▶ Start logbook engine
        ├─▶ Start RAAS
        └─▶ Register shutdown handlers
```

---

## 8. Design Tokens

The application uses a consistent dark theme:

| Token | Typical Value | Usage |
|---|---|---|
| `--color-ops-bg-dark` | `#0b0e11` | Page backgrounds |
| `--color-ops-border` | `#1f2833` | Card/panel borders |
| `--amber` | `#efbd47` | Accent highlights (borders only, never fills) |
| `--text` | `#e6e6e6` | Primary text |
| `--muted` | `#aaa98d` | Secondary/muted text |
| `--line` | `#65684e` | Default borders |
| `--condensed` | `"B612", sans-serif` | Headers, labels |
| `--terminal` | `"B612 Mono", monospace` | Data displays, logs |

**Card convention:** Background `#12161c`, border `1px solid #1f2833`, border-radius `4px`, padding `0.75rem–1rem`, no negative margins.
