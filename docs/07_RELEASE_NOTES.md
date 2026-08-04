# OPS ROOM — Release Notes: v0.24.1 → v0.25.61

> **How to keep this file current:** every time a build changes something,
> add a line under the matching section below (or a new section for a brand
> new feature) and bump the "Latest build" note at the top. Keep it brief and
> user-facing — this is the source material for Flightsim.to / GitHub release
> notes.

**Latest build:** v0.25.61 — Release Migration (stable public release)

---

## The big picture

Since the v0.24.1 public beta, OPS ROOM has grown from a flight-prep and
ground-workflow companion into a full operations control centre. The headline
additions are a **built-in flight data recorder** (Black Box), **real-world
flight tracking** (Real World Search), an **optional pilot career and airline
economy system**, a **detailed airport map**, **live NOTAMs**, and a large
amount of under-the-hood reliability work. Everything from v0.24.1 — RAAS,
GSX workflows, the briefing, the logbook, PIREPs, the iPad/EFB interface —
is still there and works the same way.

---

## New modules

### Black Box — flight data recorder (new)
- Automatically records every flight from taxi-out to taxi-in (and starts at
  engine start / pushback / taxi-out, whichever comes first).
- Captures position, altitude, speed, vertical speed, attitude, G-loading,
  controls, throttles, flaps, gear, spoilers, brakes, fuel, engines,
  autopilot state, warnings and flight phase — up to 30 samples per second
  during dynamic phases.
- A full **Flight Data Recorder (FDR) workstation** with live-updating
  Flight, Controls, Engines, Systems, Track and Events tabs — no page reloads.
- The Controls tab is an engineering-style instrument panel: moving
  sidestick/yoke crosshair, animated throttle levers, rudder pedals, brake
  gauges, spoiler/flap scales and a landing-gear indicator.
- **Replay your flight** in the browser (route animation, timeline seek,
  pause/play, loop, 0.25–8× speed) or **inside the simulator** (camera-safe —
  OPS ROOM never moves your camera; it only repositions the aircraft).
- Export any recording as CSV, GPX, KML or the native `.opsbb` format.
- Recordings survive crashes and shutdowns, are named like
  `EWG7278_D-AEWK_EDDM-LOWI_20260718T172341Z.opsbb`, and are linked to the
  matching Logbook entry (one-click replay from the Logbook page).
- Recording is protected: replay never interferes with a live flight, and
  automatic/manual recording is suppressed during replay.
- **Deep add-on aircraft support** for Fenix A32X, PMDG 777, iniBuilds
  A300/A340/A350 and FlyByWire A32NX/A380X — more real systems data where the
  aircraft exposes it, never fabricated values. PMDG 777 uses the official
  SDK with an opt-in licence agreement.
- FSUIPC7 logging is automatically silenced and trimmed at startup so log
  files no longer balloon to gigabytes during a flight.

### Real World Search (new)
- Live aircraft and flight tracking with real-world schedule lookups.
- Multi-term search, exact-match ranking and automatic background enrichment
  (aircraft type/registration details) that never blocks a search result.
- Cold-start bootstrap and background refresh so results appear fast and stay
  fresh.

### Finances / Pilot Career (new, optional)
- A career mode you can switch off completely in Settings.
- **Airline economy** and a separate **pilot wallet**, with a starting
  balance and currency of your choice (EUR / USD / GBP).
- Per-flight revenue (passengers, cargo), fuel, ground handling, airport
  fees, reserves, airline profit and pilot pay — using real GSX receipts when
  available, sensible estimates otherwise.
- A **pilot rank ladder** (Cadet → Fleet Captain) with relaxed/standard/
  realistic progression, XP and block-hour tracking.
- Preflight cost estimates, fare controls (auto/economy/business/first +
  cargo), and a full financial statement in every PIREP.
- Works with or without GSX.

### Live Map — detailed airport surface (new)
- Click any airport to load a **detailed airport surface**: runways, taxiways,
  aprons and stands, rendered from your local simulator nav database or the
  built-in global aviation database.
- Zoom-driven overlays: runways appear first, taxiways and labels as you zoom
  in. Runways are drawn as real paved surfaces with centreline and threshold
  markings.
- Persistent airport selection, honest loading/error status, and refresh
  during panning/zooming without erasing your route airports.

---

## Briefing & flight planning

- **One shared SimBrief flight plan** across Status Board, Briefing, Dispatch
  and Flight Watch, auto-loaded at startup (toggle in Settings).
- Briefing is now organised into tabs: **Overview, Weather, NOTAMs, OFP,
  SIGMETs and SIGWX**.
- **Real SIGWX charts** discovered automatically inside the SimBrief PDF —
  no more hunting for them in the OFP.
- Weather is decoded for you: flight category (VFR/MVFR/IFR/LIFR), wind,
  visibility, temperature, dew point and altimeter, refreshed every 5 minutes.
- **NOTAM cards** with correct scope (departure/destination/alternate/
  en-route), full effective/expiry dates and permanent/estimated-expiry
  status.
- **Live NOTAMs from the real FAA NOTAM system** (global coverage), routed
  through your own server so no third-party credentials sit on your PC. In
  the Notams and Hazards tabs you can switch between **Live**, **Flight plan
  (SimBrief)** and **Combined** sources — Live is the default.
- Charts are fetched by the local app and shown in a clean grouped viewer
  (ChartFox / SimBrief / AIP-FAA sources).
- Interactive PIREP/briefing charts with zoom, pan and reset.

## Ground operations (GSX + Fenix)

- Guided **Departure, Arrival and Full Turnaround** workflows for GSX Pro.
- **Fenix EFB integration**: OPS ROOM hands passenger/cargo/fuel loading to
  Fenix with balanced, deterministic seat assignment; coordinates chocks,
  GPU, doors and cargo doors during supported flows.
- Your **airline is preferred automatically** at GSX operator prompts (with
  alias handling like BAW / British Airways / Speedbird).
- **Verified pushback handoff**: OPS ROOM confirms GSX reached the
  pushback-prep state before proceeding — and never chooses your pushback
  direction.
- Arrival services run in a reliable sequence: deboarding, then cleaning,
  lavatory and potable water as GSX makes them available.
- **GSX receipts** (handling, fuel, catering, passenger bus) are read
  automatically and turned into accurate departure/arrival costs in PIREPs,
  with sensible estimates when receipts are missing.
- Non-GSX users keep full manual operation with OPS ROOM cost estimates.

## Announcements

- Airline audio packs with literal event matching — each recording is used
  only for its named announcement (aircraft, local-time and refuelling
  variants; random pick between equivalent numbered clips).
- Boarding music and welcome, serialized take-off cabin sequence, after-
  take-off, descent, landing and disembarkation calls.
- Announcements keep playing through temporary telemetry interruptions and
  recover the correct cabin state afterwards.

## Flight monitoring & PIREPs

- **FSUIPC7-preferred telemetry** with automatic SimConnect fallback and
  recovery. Frozen/stale data is detected and the app switches to a fresh
  source rather than showing wrong values.
- SimConnect session **self-healing**: if the connection breaks mid-flight,
  OPS ROOM tears it down and rebuilds it.
- Cleaned-up speed, altitude, vertical-speed and position signals for steadier
  phase detection and cleaner reports.
- **Detailed browser PIREPs**: flight profile, approach stability, landing and
  bounce analysis, scoring, events and a full finance statement — plus a
  **Full PIREP PDF** that prints exactly what you see on screen.
- Landing results card, a persistent landing-result toast, and runway
  diagrams in reports.
- Recorder/fuel logic handles refuelling on the ground and provider switches
  without false in-flight fuel warnings.

## Runway awareness (RAAS)

- Approaching-runway alerts, on-runway alerts and remaining-runway callouts,
  with the approaching trigger now based on distance from the physical runway
  edge for earlier, more consistent timing.
- FT/M unit toggle with saved setting; voice-pack support with
  text-to-speech fallback.
- Pushback is recognised for **any tug** — GSX, the default tug or third-
  party services — so the safety briefing no longer fires while you're simply
  being pushed back.

## Airline identity & streaming

- OPS ROOM resolves your airline (from SimBrief, callsign, database or your
  own override) and shows its **logo** across Briefing, Status Board,
  Dispatch, Flight Watch, Logbook, PIREP/PDF, Finance, Ground Control,
  Announcer and Live Map.
- **OBS branding modes**: Active Airline, Custom Logo (for virtual airlines)
  or OPS ROOM, plus a **GSX ground-handling OBS overlay** showing live
  service progress, route, pax/bags/cargo and invoices.
- Experimental MSFS 2024 **Camera Bridge** improvements.

## Interface & usability

- Airbus/MCDU-inspired cockpit typography, a cleaner status board, and
  user-facing wording throughout (no more developer labels in the console).
- A compact flight header on the Briefing, cleaner module navigation, and
  keyboard focus indicators for accessibility.
- **NOTAM layer on the Live Map** (off by default) with classification
  filter chips — overlay real-world NOTAMs and TFRs on your route.
- **TFR/FDC proximity alerts**: OPS ROOM watches your position against real
  airspace NOTAMs and alerts you through the existing notification/toast and
  audio system when you get close to a Temporary Flight Restriction.
- iPad / EFB / browser-friendly responsive layouts.

## Updater & installation

- Visible **OPS ROOM Updater** window showing progress during installation.
- Safer downloads (`.part` files, empty-download rejection, integrity
  checks, SHA-256-verified manifests).
- Update infrastructure migrated to **opsroom.live** with GitHub as the
  automatic fallback.
- Windows installer generation (Inno Setup) with correct version naming.

## Reliability & performance highlights

- Faster module loading: pages show cached data immediately while live data
  refreshes in the background.
- Fixed a performance hotspot where the add-on adapter registry was re-read
  from disk on every telemetry sample — now cached and invalidated only when
  it changes.
- Status Board advisories never show raw errors — unusual conditions read as
  plain operational messages.
- Approach charts and PIREP analyses exclude unreliable samples instead of
  producing spiky, misleading graphs.

---

## Quick version timeline (for reference)

| Build | Focus |
| --- | --- |
| v0.24.1 | Baseline public beta: RAAS, updater, Camera Bridge, GSX, briefing |
| v0.24.2 → v0.24.10 | GSX arrival/turnaround safety, Live Map aviation DB, backend-managed charts |
| v0.24.11 → v0.24.29 | Fenix/GSX loading protection, announcer fixes, **Finances & Pilot Career**, auto-OFP |
| v0.24.31 → v0.24.40 | Arrival integrity, console refinement, telemetry failover, PIREP continuity |
| v0.24.44 → v0.24.49 | Report integrity, briefing fidelity (SIGWX/SIGMET/NOTAMs), Full PIREP PDF |
| v0.24.100 → v0.24.109 | **Black Box** flight data recorder + replay, airport surface map, airline identity, add-on aircraft adapters |
| v0.25.11 → v0.25.17 | Public-release migration, polish pass |
| v0.25.20 | Update infrastructure moves to opsroom.live (GitHub fallback) |
| v0.25.47 → v0.25.58 | **Real World Search** pipeline: FR24 discovery + ADSBDB enrichment hardening |
| v0.25.60 | Reliability pass: pushback detection, Status Board NOTAMs, SimConnect self-healing, Black Box auto-record |
| v0.25.61 | **Live FAA NMS NOTAMs**: default source in Briefing NOTAMs (Live / Flight plan / Combined switch), Status Board live rows, TFR/FDC proximity alerts |

---

*OPS ROOM is for flight simulation only. Not for real-world aviation use.*
