# OPS ROOM 0.25.61

OPS ROOM 0.25.61 brings live, real-world NOTAMs into the briefing, on top of
the reliability hardening from the 0.25.60 pass.

## 0.25.61: Live NOTAMs

- The Briefing → NOTAMs tab now prefers **live FAA NMS NOTAMs** whenever the
  live service is reachable, with a source selector: **Live / Flight plan /
  Combined**. Flight-plan NOTAMs are never replaced — they stay one click away.
- Live NOTAMs for your departure, destination and alternates are enriched into
  the briefing and marked with a "LIVE" chip; the Status Board shows the
  closest live route NOTAMs as well.
- Optional **TFR/FDC proximity alerts**: OPS ROOM watches the airspace around
  your live aircraft and raises a notification when a new Temporary Flight
  Restriction or FDC entry appears (opt-in).
- The live-NOTAM credentials stay on the OPS ROOM server — nothing is stored
  on your machine, and every live-NOTAM path falls back gracefully to the
  flight-plan data if the service is unreachable.

## Reliability pass (carried from 0.25.60)

- Pushback is recognised for any tug — GSX, the default tug or any third-party
  service — with backward motion and heading reversal detected independently
  of GSX.
- The SimConnect session heals itself mid-flight: a broken dispatch loop is
  torn down and rebuilt instead of serving a dead connection.
- Black Box auto-recording starts at the earliest of engine start, pushback or
  taxi-out and stops on blocks with the engines off; the engine-start watchdog
  runs from app launch.
- Flight Watch no longer shows fabricated autopilot selections when the
  aircraft adapter is inactive, and the full-screen RAAS CHECK overlay works
  again on every module.
- Status Board advisories are crash-proofed and show up to three departure and
  three arrival route NOTAMs from the loaded flight plan.

## 0.25.61 verified scope

- Live NOTAM source selector, briefing enrichment and Status Board live rows.
- TFR/FDC proximity alerting (opt-in).
- Pushback detection (GSX and non-GSX), SimConnect self-healing, Black Box
  auto-record start/stop, RAAS global overlay.
- Installer generation with correct version naming.

Aircraft compatibility, simulator fallback behaviour and online network
etiquette follow the same conventions as previous public releases.
