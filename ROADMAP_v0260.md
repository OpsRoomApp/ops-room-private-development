# OPS ROOM — v0.26.0 Next Update Plan

This doc captures the eight ecosystem features selected for the **v0.26.0**
update cycle, drawn from the 2026-08-13 product-ideation pass. The full
idea list was reviewed against the current app; three ideas already ship
today (listed at the bottom) and voice briefings were dropped because the
current TTS voice sounds unnatural for long read-outs.

---

## Selected for v0.26.0

| # | Feature | Where it lives | Effort | Depends on |
|---|---|---|---|---|
| 1 | Personal flight tracker + cloud logbook ("free Volanta") | app + website | Large | Discord OAuth identity |
| 2 | One-tap Landing Report share card | app + bot + website | Small | Recorder + score (built) |
| 7 | Fleet hangar + per-airframe telemetry | app + website profile | Medium | #1 cloud logbook |
| 12 | In-sim MSFS toolbar panel | app (MSFS SDK gauge) | Large | Telemetry bus (built) |
| 13 | Voice copilot — call-and-response checklists | app | Medium | Procedures + announcer TTS (built) |
| 14 | Replay → shareable video clip | app | Medium | Black Box replay (built) |
| 19 | Fleet wear & tear + maintenance | app | Medium | #7 hangar + economy (built) |
| 21 | Key-moment auto-capture timeline | app | Small | Logbook + recorder phases (built) |

Build order: **2 → 21 → 1 → 7 → 19 → 13 → 14 → 12** — the two cheap
shareable wins first, then the cloud-logbook foundation, the hangar + wear
layer on top of it, the two independent medium bets (copilot, video), and the
in-sim panel last as the immersion capstone.

---

## 1 — Personal flight tracker + cloud logbook ("free Volanta")

**Why.** Volanta is the tracking gold standard, but its best features are
paywalled and its logbook lives behind its own account. OPS ROOM already
records every flight through the Black Box — the hard part (telemetry +
recording) is done; what is missing is the *presentation* and *persistence*
layer that makes a logbook feel like a product.

**Scope.**
- **"My Flights" dashboard** (app): map-traced route per flight, hours, score,
  landing rate, aircraft, origin/destination, date — with search/filter by
  aircraft, airport, month.
- **Lifetime stats page**: total hours, flights, average/best landing rate,
  most-flown route and airframe, busiest month.
- **Cloud sync**: tie the logbook to the existing Discord OAuth identity so it
  survives reinstalls and is readable from the website profile.
- **Website mirror**: a public profile page (`/profile`) rendering the same
  logbook + stats for the linked identity (opt-in).

**Out of scope for v0.26.0.** Multi-sim (X-Plane/DCS) ingestion, and any
export/import of foreign logbooks — OPS ROOM-native only for now.

**Acceptance.** A flight completed in the app appears in "My Flights" with a
correct route trace and stats; reinstalling (or opening the website profile)
after re-linking Discord restores the full history; nothing breaks for users
who never connect Discord (local logbook still works offline).

---

## 2 — One-tap Landing Report share card

**Why.** Landing analysis + replay is a top-5 community wishlist item, and the
share card is the single highest word-of-mouth driver — it is what gets posted
to r/flightsim and brings new users.

**Scope.**
- **Auto-generated card** on parking: landing rate, G-loading, touchdown
  speed, flight result, block time, a small approach-path thumbnail.
- **Shareable link** (`opsroom.live/f/<id>`): a lightweight public page that
  replays the final-approach trace and shows the same card.
- **Discord bot** auto-DM of the card to the linked pilot (opt-in), plus a
  one-tap "share to channel" if `#flights` visibility is enabled.
- Reuse the existing `_stash_lkg_ofp`-style last-known-good cache and the
  landing reconstruction the recorder already produces (no new data capture).

**Acceptance.** After a flight, one click produces a card + public link with no
manual data entry; the link renders correctly from outside the LAN; pilots who
did not connect Discord still get the card locally.

---

## 7 — Fleet hangar + per-airframe telemetry

**Why.** Gamifies ownership the way Volanta's fleet view does, and gives the
leaderboard a "which airframe do I fly best" dimension — a natural retention
layer on top of the cloud logbook.

**Scope.**
- **Fleet hangar**: every tail number/aircraft the pilot has flown, with hours,
  landings, average landing rate, best landing, and total distance.
- **Per-airframe comparison**: "you land the A320 at −412 fpm avg vs −288 fpm
  in the B738" style insights.
- **Hangar on the website profile** alongside the logbook (#1).

**Acceptance.** Selecting an airframe shows its lifetime stats; stats stay
correct across flights; the website profile renders the same hangar.

---

## 12 — In-sim MSFS toolbar panel

**Why.** Removes the "tab out to check the app" friction entirely — the single
highest *perceived* value feature for immersion, and a clear differentiator
versus Volanta/Navigraph.

**Scope.**
- A native in-sim panel (MSFS SDK gauge) shown from the in-game toolbar:
  V-speeds, next waypoint + distance/ETE, fuel remaining, landing rate after
  touchdown, and an OFP snapshot (block/off/on/in times).
- Reads from the existing single-writer telemetry bus and the SimBrief cache —
  no new sim data source.
- Camera-safe by design: read-only, never drives the camera (per the #53
  decision that the app must not control the camera).

**Out of scope for v0.26.0.** In-panel controls (dialing radios/MCDU),
multi-monitor pop-outs, and the WASM instrumentation of non-standard aircraft.

**Acceptance.** The panel opens from the toolbar in MSFS 2020 and 2024, updates
live during a flight, and shows a landing-rate readout within seconds of
touchdown; no impact on frame rate or the existing telemetry cadence.

---

## 13 — Voice copilot: call-and-response checklists

**Why.** The community is actively adopting voice checklist tools (*Checklist
Reader*, *SayIntentions AI copilot*, *Multi Crew Experience*) because running
a checklist single-handed is awkward. OPS ROOM already has the per-aircraft
checklists (Procedures) and TTS (Announcer) — this wires them together.

**Scope.**
- TTS reads each checklist line in order; the pilot advances with a
  "checked" hotkey/voice/button, with a spoken "runway turnoff — checked"
  style confirm, and a skip/abort path.
- Aircraft-specific checklists come from the existing procedure profiles —
  no new content authoring.
- **Short spoken prompts only** (checklist items and callouts), not long
  narrative — this is why the voice-briefing idea (#15) was dropped: the TTS
  voice is fine for terse items but sounds unnatural reading paragraphs.

**Out of scope for v0.26.0.** Speech-recognition ("hands-free voice commands")
and LLM-driven freeform copilot conversation.

**Acceptance.** A full pre-start or after-landing checklist runs end-to-end with
spoken items + confirmation, matched to the detected aircraft profile; a
wrong/absent aircraft falls back to a generic checklist without error.

---

## 14 — Replay → shareable video clip

**Why.** "How do I record and export my replays without killing FPS" is a
perennial top post. The Black Box already reconstructs the flight from
telemetry; exporting that to a postable clip is the natural next step and
turns the share card (#2) into a *moving* share.

**Scope.**
- **"Export clip"** on any recording: render a chosen segment (default: final
  3–5 min approach) to mp4/GIF from the recorded trajectory + a simplified
  render (attitude, path, speed/alt readout), independent of the sim.
- Lightweight, background-threaded export so it never competes with the sim
  for frame time.
- Feeds the same share link surface as #2.

**Out of scope for v0.26.0.** Full cinematic rendering (camera keyframes,
replays inside the 3D world), and 4K/60 export.

**Acceptance.** A recording exports to a playable mp4 in the background; the
clip shows a recognizable approach + touchdown with the correct landing rate;
exporting does not stutter the sim.

---

## 19 — Fleet wear & tear + maintenance

**Why.** Adds consequence to the economy — hard landings, over-speeds and
overweight takeoffs currently only show up as a score number. Tying them to
per-airframe wear (via the #7 hangar) makes the hangar a living system, not a
static stats page.

**Scope.**
- Accumulate **wear per airframe** from landing rate, G-loading, over-speed
  events and overweight takeoffs.
- Surface a maintenance state per airframe (fresh → worn → grounded); a
  "service" action spends from the existing airline balance to restore it.
- Light performance/inspection nudges when an airframe is overdue — cosmetic
  first, no flight-model interference.

**Out of scope for v0.26.0.** Actual failure injection from wear (that is the
separate emergency-training idea), and shared/multi-owner aircraft.

**Acceptance.** A hard landing visibly increases that airframe's wear; servicing
it restores the state and debits the balance; wear persists per tail number
across flights and is visible in the hangar.

---

## 21 — Key-moment auto-capture timeline

**Why.** Makes every logbook entry a story with zero manual effort — the
screenshot "I wish I'd captured that" problem, solved by the phase machine
already in the recorder.

**Scope.**
- Auto-capture a screenshot at key moments: takeoff, milestone altitudes,
  top of descent, and touchdown.
- Present a **flight photo timeline** beside the logbook entry, with
  click-to-enlarge and optional export.
- Reuse the recorder's existing phase transitions to trigger captures (no new
  event source).

**Out of scope for v0.26.0.** Video capture, manual frame scrubbing, and cloud
backup of the image library (local + optional share first).

**Acceptance.** A completed flight shows the captured moments in its logbook
entry; captures are non-blocking and never cost the sim frame time; flights
already in the logbook are unaffected.

---

## Already shipped (do not re-build)

- **Idea 3 — Fly real schedules / dispatch**: the OFP already carries the
  real flight number, route and planned times, and the economy/finance/score
  loop provides the "reason to fly."
- **Idea 5 — VATSIM awareness**: the vPilot bridge, live traffic on the map
  and the community map feed already exist.
- **Idea 10 — Career progression (ranks/achievements/milestones)**: the score,
  passenger-satisfaction and Discord milestone pings already cover this.

## Dropped

- **Idea 15 — Voice briefings (pre-flight / top-of-descent)**: dropped — the
  current TTS voice reads short callouts cleanly but sounds unnatural for
  long narrative briefings. Revisit only if a better voice is adopted.

---

## Notes

- All features are **opt-in** where they touch identity or sharing; the app
  must remain fully functional with no Discord/website connection.
- Data scope stays flight-related (no personal data beyond the pilot's own
  flights), consistent with the existing community-feature privacy stance.
- This doc is a plan only — no code has changed for v0.26.0 yet.
