# OPS ROOM 0.25.73

## 0.25.73: Performance calculator, PIREP/OFP fixes and the confirm() sweep

- **First-party performance calculator for the whole fleet.** The Performance
  tab no longer depends on SimBrief TLR. A new tiered engine
  (`app/perf_engine.py`) ports the FlyByWire A32NX limiting-factor model
  (A320neo, exact) and the komed3 B737-800 tables (B738, exact), scales them
  across every other A32x/737 variant, and falls back to the PERF2601 curves
  for the rest of the dropdown — V1/VR/V2 or VLS/VREF, flap recommendation,
  flex/assumed temp, runway-required distance, pitch trim, takeoff and
  landing modes. SimBrief auto-fills ZFW/ZFWCG/runway/wind/temp/QNH.
- **Full PIREP is back (critical fix).** The telemetry endpoint 500'd on
  every flight because the analysis-cache prune rebound the module-level
  name; it now prunes in place and the report builds.
- **No more "?" in the UI.** Literal `?` separators in PIREP and OBS were
  replaced with proper arrows, and PIREP/OBS/host surfaces gained
  `Segoe UI Symbol` / `Segoe UI Emoji` font fallbacks.
- **NOTAM layer on the Live Map.** The map now falls through an empty
  database answer to the live FAA NMS proxy and then to a per-airport walk
  with airport-index coordinates, so NOTAMs render and are clickable.
- **Live OFP weights fill on every provider.** The FSUIPC read now carries
  the standard total/max-gross weight offsets, and a TTL-guarded Fenix
  loadsheet snapshot publishes PAX/BAG-CARGO even before GSX automation
  engages — TOW, LDW, ZFW, PAX and cargo all populate.
- **Receipt preview dropdown.** Settings → Thermal/POS printer lets you
  preview every wired kind (CPDLC, LIVE OFP, PRINTER TEST, GSX RECEIPT)
  through the real formatters, byte-identical to what prints.
- **confirm() sweep complete.** WebView2 silently blocks native
  `window.confirm()`; every confirm-gated action now uses an in-app
  `<dialog>` modal (delete record, scratchpad clears, finance reset, update
  install, black box replay, streamer-mode warnings, bug-report send,
  ChartFox disconnect, LAN device revoke).

## 0.25.72 (Release Candidate): RC hardening

- **Closure-marker lights toned down.** Beacon and LED chase intensity cut
  10x (15000 → 1500) so markers stay visible from distance without blinding
  glare; the far-draw-distance recipe (MinProjSize + Range) is unchanged.
- **App-bundled package refreshed.** The Community installer now ships the
  SDK-compiled GroundVehicle layout (lighted X + Type III barricades with
  systems.cfg light systems) instead of reverting to the legacy static-only
  build on every launch — deploy-in-sim placements keep their lights and
  chase animations.
- **Cleaner shutdown.** Graceful-shutdown timeout bounds the exit wait and
  the HTTP middleware no longer floods the log with cancellation
  tracebacks on exit.

## 0.25.72: Closure markers that land where the taxiway is — and only where they should

- **Taxiway X markers are placed on the real taxiway geometry.** The deploy
  plan reads the actual taxiway segments of the closed taxiway from the
  local surface database and places the X mats at the segment centroid with
  the segment heading, instead of dropping them at the airport reference
  point (which could sit hundreds of metres off the closed line).
- **Crane/obstacle NOTAMs no longer close runways.** Real FAA NMS feeds
  carry phrases like "CRANE WILL ONLY OPR WHEN RWY 09L/27R IS CLSD" — a
  vehicle that operates *if* the runway is closed, not a closure. The parser
  now skips conditional WHEN/IF constructions on both runways and taxiways,
  so X mats are never placed on fully operational runways (verified against
  the live EGLL feed, which previously produced five false closures).
- **NOTAMs are back in the briefing.** The live-NOTAM enrichment now runs on
  the public server-side NOTAM store without requiring an NMS proxy token
  (previously that gate silently showed 0 live NOTAMs), and when the store
  is unreachable the per-airport fallback populates closures reliably
  (64 live NOTAMs at the briefing where 0 were shown before).
- **OFP-less briefings still show live closures.** When no SimBrief OFP is
  loaded, the briefing falls back to position-based NOTAMs instead of
  silently showing an empty list.
- **Deploy-in-sim no longer goes dead after one use.** The empty-plan cause
  of the one-shot deploy is gone, and the fallback fetches are parallelised
  (cold ~1.3 s, cached instantly) so the app stays responsive while
  briefing and deploying.

## 0.25.72: Faster, cleaner shutdown

- **App reloads no longer hang for five seconds.** The SimConnect wrapper's
  dispatch thread is now closed cleanly on shutdown (telemetry and marker
  sessions), which stops the `OS error: WinError 0xc00000b0` flood that
  blocked a graceful exit and forced the launcher's force-kill every reload.

## 0.25.72: Closure-marker MSFS package refresh

- New models for the portable lighted X trailer and the Type III
  barricades, exported with the official Asobo MSFS 2024 format:
  lamp fixtures stand proud of the rods, the barricade beacon sits on the
  dome at reduced intensity, and the X frame carries its safety-yellow
  colour scheme.
- Chase/flashing light pass via engine-side street-light effects with
  staggered phases (deterministic, random phase locked off).

## Carried from 0.25.66

- Live FAA NMS NOTAMs with source selector (Live / Flight plan / Combined),
  briefing enrichment and Status Board live rows; TFR/FDC proximity alerting
  (opt-in); server-side NOTAM store so no FAA quota is touched locally.
- Runway/taxiway closure markers from live NOTAMs: threshold X mats, taxiway
  X mats, alternating orange/white Type III barricades across hold-short
  lines, and the portable lighted X trailer — all shipped as an MSFS
  Community package that setup installs into the 2020 and 2024 folders.
- Pushback detection (GSX and non-GSX), SimConnect self-healing, Black Box
  auto-record start/stop, RAAS global overlay.

## 0.25.72 verified scope

- Taxiway-marker placement on segment geometry (centroid + heading) with
  safe name matching, plus airport-centroid fallback.
- Conditional (WHEN/IF) closure suppression for runway and taxiway
  references; equipment-U/S suppression carried over.
- Live-NOTAM briefing on the public DB store with the NMS proxy as an
  optional token-gated fallback; per-airport parallel fallback,
  deduplication, coarsened cache and precise ok semantics (legit-empty vs
  full outage).
- Briefing with and without a SimBrief OFP loaded.
- SimConnect session teardown on shutdown (fast reload, no error flood).
- Full release identity 0.25.72: version metadata, source manifest,
  updater fallback, UI labels and cache-busters, build scripts, installer
  and MSFS Community package version.

Aircraft compatibility, simulator fallback behaviour and online network
etiquette follow the same conventions as previous public releases.
