# OPS ROOM 0.25.60

OPS ROOM 0.25.60 is a public reliability release that hardens flight-phase
detection, the Status Board, the simulator telemetry session and Black Box
auto-recording.

## 0.25.60: Reliability Pass

Highlights in this build:

- Pushback is now recognised for any tug — GSX, the default tug or any
  third-party pushback service. Backward body motion and heading/track
  reversal are detected independently of GSX, so the safety briefing no longer
  fires when the aircraft is simply being pushed back.
- The Status Board advisories panel is crash-proofed and more useful: the
  flight-identity line no longer throws when a flight plan has no raw OFP
  envelope, and up to three departure and three arrival route NOTAMs from the
  loaded flight plan are shown beneath the system notices.
- The SimConnect session heals itself: if the connection's dispatch loop
  breaks mid-session, repeated failed reads tear the session down and a fresh
  one is created, instead of serving a dead connection and silently falling
  back to generic aircraft data.
- Flight Watch no longer shows fabricated FCU selections: when the aircraft
  adapter is inactive, the zero-valued generic autopilot offsets are presented
  as no data instead of a misleading "0 FT / 0°".
- The full-screen RAAS CHECK overlay works again on every module after the
  previous toast cleanup pass accidentally hid it.
- Black Box auto-recording starts at the earliest of engine start, pushback or
  taxi-out, and stops on blocks with the engines off — the watchdog that
  detects engine start now runs from app startup and between recordings.

Behavioural compatibility:

- Black Box recording schema v2 is unchanged; existing recordings still load
  and replay normally.
- Real World Search keeps its cache-first pipeline: FR24 discovery and ADSBDB
  enrichment run in the background and never block a search request.
- The ChartFox browser, Dispatch, Briefing, Logbook and Settings pages behave
  the same as in the prior release.
- Public release identity, build channels and acknowledgements stay in sync
  across the .md and .txt copies.

This build is a stable public release. Refresh the Black Box recordings and
Status Board pages after upgrading.

## 0.25.60 verified scope

- Pushback detection (GSX and non-GSX), Status Board advisories and NOTAMs.
- SimConnect session self-healing and Flight Watch FCU presentation.
- RAAS global overlay and Black Box auto-record start/stop.
- Installer generation with correct version naming.

Aircraft compatibility, simulator fallback behaviour and online network
etiquette follow the same conventions as previous public releases.
