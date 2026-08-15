# OPS ROOM — UI / UX Improvement List

Catalogue of frontend polish and usability items identified during UI review
(2026-08-10, deep pass across all 20 modules + 6 standalone pages).
Status: PLAN ONLY unless noted otherwise. Nothing here is implemented yet.

Legend:
- **[UX]** usability / information hierarchy
- **[VIS]** visual / styling
- **[ACC]** accessibility
- **[BUG]** actual defect surfaced by the review

---

## Confirmed & agreed

### U-01 — Checked checkboxes render an ✗ instead of a tick [VIS]
Every enabled checkbox shows a literal **X** inside the box. In every other UI an ✗
reads as "no / off / delete", so a *checked* box displaying a cross is confusing.
Fix: render a tick (✓) or a filled/glowing box for the checked state via CSS instead
of the literal "✗" character. Small, safe, high polish-per-line.

### U-02 — Helper / hint text should be sentence case (FMGS register for labels only) [VIS]
The ALL-CAPS treatment is intentional and correct for labels, titles and values —
it's the Airbus FMGS / ops-room design language and should stay. But the same caps
register is applied to *helper text* ("Leave blank to keep saved code", "Overrides
are optional. OPS ROOM does not include announcement audio...", placeholder hints),
which flattens hierarchy: when everything shouts, nothing stands out.
Fix: keep caps for labels/titles/values; drop hints, placeholders and long
descriptions to sentence case so the important text pops.

---

## Open items from the first review pass

### U-03 — Host System Setup: one endless scroll, 12 equally-weighted sections [UX]
IDENTIFICATION, COMMUNICATIONS, VPILOT, CABIN ANNOUNCER, GROUND SERVICES, FLIGHT
TELEMETRY, NOTAM CLOSURES, CHARTS/MAP, LOCAL SERVER, DEVICE SECURITY, BROWSER
CONSOLE, UNITS — each a full-width card, all the same visual weight, nothing
grouped or prioritized.
Proposal: group into logical tabs or a 2-column grid on desktop (ACCOUNTS & COMMS /
SIM INTEGRATION / DISPLAY & UNITS), or make sections collapsible with remembered
open/closed state.

### U-04 — Save action buried at the bottom of the long setup scroll [UX]
SAVE SYSTEM SETTINGS sits at the very bottom, in a row with RELOAD / PROBE MSFS /
FETCH LATEST OFP — four buttons of different purposes mixed together at the end of
a marathon scroll. Proposal: pin the Save bar (sticky footer) and separate
diagnostic buttons from the primary action.

### U-05 — Host Status page: three giant cards for three words [UX]
LOCAL SERVICE / VERSION / ROLE each take a full-width row for a single word
("RUNNING", "0.25.75", "HOST / BRIDGE"). Dead vertical space. Proposal: combine
into one compact strip (label: value inline).

### U-06 — Footer status bar mixes unrelated statuses with no grouping [UX]
`VATSIM NOT SET · SIMBRIEF RJA403 · HOPPIE Connected · GSX Running · SIM FSUIPC7 ·
EFB Keep Awake off` — six unrelated statuses in one flat bar. Proposal: group by
category (network / sim / addons) or drop low-value items like "Keep Awake off".

### U-07 — Redundant / duplicated section labels [UX]
Flight Watch page renders a section header "Flight watch" *inside* the Flight Watch
page (next to "Live / LIVE TELEMETRY NORMAL"); "Flight data" has two stacked header
rows. Same pattern likely elsewhere. Proposal: audit and remove duplicated headers.

### U-08 — "EXPERIMENTAL · SIM-ONLY" badge on the pilot-facing Performance page [UX]
An end user reads "EXPERIMENTAL" as "don't trust this". If the calculator is in
beta, say "BETA" once in Settings instead of branding the pilot-facing page.

### U-09 — "READY" labels that look identical but mean different things [UX]
Host Status lists MSFS/TELEMETRY: READY and TELEMETRY SOURCE: READY — two green
"READY"s that read as the same thing. If they differ, say how; if not, merge.

---

## New findings from the deep pass (all 20 modules + 6 standalone pages)

### U-10 — Logbook event timeline dumps raw phase-machine internals [BUG][UX]
The flight debrief timeline (`renderLogbookDetailAdvanced`, opsroom.js:6375)
renders `events.slice(-100)` RAW, bypassing the `operationalEvents()` filter that
exists and is used everywhere else. Result: the RJA403 debrief shows 20+ entries of
`PHASE_REJECTED · from=ENROUTE to=CLIMB reason=impossible_transition` and
`PHASE_ACCEPTED · from=X to=Y reason=validated_transition` — developer telemetry,
not pilot information. The friendly filter is right there in the code
(`friendlyTimelineEvent` returns null for PHASE_ACCEPTED/PHASE_REJECTED); this one
render path just never calls it.
Fix: run the same `operationalEvents(entry.events, 'general')` filter before
`slice(-100)`. Pilot-visible timeline should show BLOCK OUT / TAKEOFF / LANDING /
BLOCK IN / COMPLETED / DEVIATION — not transition bookkeeping. (The repeated
PHASE_REJECTED churn itself is a separate backend observation worth logging:
~20 rejected ENROUTE→CLIMB transitions suggests the phase machine flaps.)

### U-11 — System page "Startup log" shows raw server access logs (KEPT AS DESIGNED — user-facing transparency)
The Settings page's Startup log section shows hundreds of
`[INFO] GET /api/flight-watch HTTP/1.1 200 OK` lines — raw uvicorn access logs in a
user-facing page. Proposal: show only WARN/ERROR lines (with a "show full log"
toggle), or drop it and point to opsroom.log.

### U-12 — Finance "Latest completed flight" and statements show `---- → ----` [BUG]
The Finances page "Latest completed flight" card and the Recent statements list
render `TEST1 · ---- → ----` and `RJA403 · ---- → ----` for records without route
data (route fallback is `'----'`). Two problems: (1) placeholder route text should
never reach the user (show callsign only, or hide the route), (2) there appear to
be duplicate finance statements (TEST1 and RJA403 posted twice — 17:33Z and 17:32Z)
which suggests a double-post bug worth checking in the economy/finalize path.

### U-13 — Destructive actions are not visually distinct [UX]
"Reset career" (Finances) sits directly next to "Save assumptions"; "DELETE
RECORD" (Logbook) sits next to SAVE DEBRIEF / OPEN FULL PIREP / DOWNLOAD PDF —
all styled as plain same-weight buttons. Proposal: danger buttons get a distinct
treatment (red/amber border, confirm modal) so a stray click can't nuke a career
or a flight record. The app already has an in-app confirm modal (v0.25.73 #8)
used elsewhere — reuse it for destructive actions.

### U-14 — Standalone pages carry stale cache-busters [BUG]
`traffic_board.html` and `obs.html` still reference `?v=0-25-73` (and
`opsroom-board-0-25-73`) while the app is 0.25.75. Any browser that cached the
old FIDS-board / OBS assets will keep serving the stale build — the exact
stale-mix failure mode the service worker was designed to prevent. Fix: bump the
two standalone pages' version query strings with the main bump.

### U-15 — Black Box recordings list can show duplicate/stale entries [UX]
Black Box "Recordings" header reads "0 flights" in one render while the API
returns 5+ recordings (RJA403, EWG6107 ×2, FLIGHT-NOREG, TEST1) — the counter
and list are out of sync on load. Also legacy TEST/FLIGHT-NOREG recordings remain
in the list with no way to tell they're test data. Proposal: sync the counter
with the rendered list; mark or hide clearly non-flight test recordings.

### U-16 — Map module has no obvious empty/loading state [UX]
The Map page renders a bare viewport with a "0% COMPLETE"-style cold start; when
tiles or the NOTAM layer fail, there is no visible fallback explaining what's
missing (consistent with the earlier "NOTAMs not visible on map" reports).
Proposal: an explicit loading → ready → degraded state banner on the map (e.g.
"NOTAM LAYER UNAVAILABLE — check OpenAIP key").

### U-17 — Host status "READY" + tab bar affordance [UX]
The Host page tab bar has a phantom third tab slot (empty bordered box next to
01 STATUS / 02 SYSTEM SETUP). Either fill it (add a third position like
DIAGNOSTICS) or remove the empty slot — an empty interactive-looking box invites
clicks that do nothing.

### U-18 — Announcer/Ground "0 events" empty states are abrupt [UX]
GROUND CONTROL and ANNOUNCER show "0 events" / "0 receipts" with no hint of what
would appear there or that it's healthy. A one-line "Activity will appear here
during flight" turns a dead-looking panel into a calm standby state. (Minor.)

---

### U-19 — "WIP" / "EXPERIMENTAL" chips on the pilot-facing Performance module [UX]
The Performance launcher tile carries a literal `WIP` chip and the page kicker reads
`SIMULATION PERFORMANCE ASSISTANT WIP`; the page header also says
`EXPERIMENTAL · SIM-ONLY`; the camera-bridge status shows `EXPERIMENTAL`. Three
separate "unfinished" markers on pilot-facing UI. Proposal: keep at most one
subtle `BETA` marker, set once in Settings, and drop WIP/EXPERIMENTAL from the
launcher and page headers (the user already decided the calculator ships).

### U-20 — Page-title / kicker register is inconsistent across modules [VIS]
Some page headings are sentence case (`Status board`, `Flight watch`, `Dispatch`),
others ALL CAPS (`PERFORMANCE`, `RUNWAY AWARENESS`, `NETWORK / COMMS`, `Black Box
and replay`). Kickers likewise: some are `CONTROL POSITION NN`, some descriptive
(`AIRPORT MOVEMENT DISPLAY`, `Flight package`, `Cabin audio`), some missing
entirely (Flight watch, NETWORK/COMMS, Finance & career). Proposal: pick one
register per element type (title = title case, kicker = caps label) and apply
across all 20 modules — this is a high-visibility consistency win.

### U-21 — Button-label register is inconsistent [VIS]
Same action rendered differently across pages: `Refresh` (sentence) vs
`REFRESH NOW` / `REFRESH OFP` / `REFRESH PREVIEW` (caps) vs `Reconnect` vs
`RECONNECT`; `Search` vs `SEARCH` vs `SEARCH ROUTES`; `Apply` vs `APPLY`.
Proposal: standardize action buttons to ALL CAPS (matches the FMGS language)
and secondary/quiet links to sentence case.

### U-22 — Classic-console module numbering: REMOVE the numbers (DECIDED 2026-08-10) [UX]
CLARIFIED 2026-08-10: the EFB / iPad launcher (`efb-app`, what tablets see) has NO
numbers and a clean order — that launcher is fine. The numbering quirk exists only
in the CLASSIC console launcher (`module-tile`, index.html:134-150): FLIGHT WATCH
is `05` but PERFORMANCE is `05A` and RUNWAY AWARENESS is `05B`, and they are
rendered 05A → 05B → 05 in the grid; similarly 12 LOGBOOK → 12B BLACK BOX → 12A
FINANCES (12B before 12A). DECISION: remove the numbers entirely from the classic
launcher (delete the `module-number` spans + their CSS rule at opsroom.css:91),
matching the EFB launcher's clean, numberless look. Simple, zero-risk, and kills
the 05A/12B ordering confusion for good.
The launcher numbers FLIGHT WATCH as `05` while PERFORMANCE is `05A` and RUNWAY
AWARENESS is `05B` — yet FLIGHT WATCH (05) appears AFTER 05A/05B in the launcher
grid, and the rail sidebar orders them watch → performance → raas while the
launcher orders performance → raas → watch. Same muddle at 12/12A/12B (LOGBOOK /
FINANCES / BLACK BOX, with 12B displayed before 12A in the rail). If they're
siblings, number them flat (05, 06, 07); if they're sub-modules, nest them
visually instead of using letter suffixes.

### U-23 — iOS / iPad install polish: root icons 404 [BUG][UX]
The running log shows the iPad repeatedly requesting `/apple-touch-icon.png`,
`/apple-touch-icon-precomposed.png` and `/favicon.ico` at the ROOT and getting
404s — iOS probes these paths by convention regardless of the manifest. The real
icons live under `/static/icons/`. Fix: add tiny root-level redirects or copies
(`/apple-touch-icon.png` → static icon, `/favicon.ico` → favicon) so the tablet
gets a proper home-screen icon and no console 404s. (Related to the earlier
"Add to Home Screen" discussion — this is the concrete missing piece.)

### U-24 — Missing airline logos 404 in the network tab (LOW — mostly by design) [BUG]
CLARIFIED 2026-08-10: 3,947 airline logos are packaged and used everywhere; the
observed `/assets/logos/TEST.png` 404 was for a TEST flight record (TEST is not a
real ICAO, so correctly no logo exists) — not a missing collection. The UI already
degrades gracefully (onerror → monogram). Optional polish only: pre-check the code
against the packaged logo set before requesting, to keep the network tab clean.
`/assets/logos/TEST.png` (and any ICAO not in the packaged set) returns 404. The
UI degrades gracefully (`onerror` → monogram), so it's invisible to the user, but
the 404 noise is avoidable: serve a transparent/placeholder PNG for unknown codes
or skip the request when the code isn't in the packaged logo set.

### U-25 — Status vocabulary is inconsistent (STANDBY / WAITING / CHECKING / CONNECTING) [UX]
Across modules the same "not ready yet" state is worded ten different ways
(`STANDBY` ×10, `WAITING` ×3, `CHECKING...`, `CONNECTING`, `READY`, `Checking`,
`Standby`). Mixed registers AND mixed vocabulary for the same state. Proposal:
standardize a small state vocabulary (READY / LIVE / STANDBY / OFFLINE / ERROR)
with consistent color semantics, used identically in every module.

### U-26 — Sub-9px text still used in ~26 selectors not covered by the readable-scale layer [VIS][ACC]
The app has a readable-scale override layer (lines 123–152) that rescues many
labels via `max(.72rem, var(--readable-small))` — good. But ~26 selectors still
render literal sub-9px fonts (0.48–0.55rem = 7.7–8.8px) and are NOT in the
override layer: `.rail-footer` (0.55), `.strip-item small` (0.52–0.55),
`.dispatch-metrics span` / `.dispatch-reasons span` / `.dispatch-notam-alert span`
(0.48), `.watch-route-line>span b` (0.52), `.radio-title span` (0.55),
`.comms-compose-panel label` (0.52), `.ops-toast span` (0.52), `.perf-weather-source`
(0.52), `.performance-grid label` (0.54), `.performance-result span` (0.55),
`.cpdlc-template-grid label` (0.55), `.bb-engine-bar-label` (0.55), `.ofp-live-hint`
(0.54), plus the Black Box gauge labels. On a 1080p browser these are genuinely
hard to read. Proposal: extend the `max(.72rem, var(--readable-small))` treatment
to the remaining selectors (mechanical, low-risk — same pattern already proven).

### U-27 — Scratchpad module missing from the classic launcher [BUG]
SCRATCHPAD is in the sidebar nav and the EFB/iPad launcher, but the CLASSIC
launcher (module-tile grid, 18 tiles) has NO Scratchpad tile — the EFB launcher
has 19 buttons. A classic-console user cannot reach Scratchpad from the launcher
(it still works via the sidebar, so it's inconsistent rather than broken).
Proposal: add the Scratchpad tile to the classic launcher.

### U-28 — Launcher module order differs between EFB and classic [UX]
EFB launcher order: watch → performance → raas. Classic launcher order:
performance → raas → watch. Same three modules, different relative order per
launcher. Proposal: one canonical order used by both (suggest watch → performance
→ raas to match the numbered kicker 05, 05A, 05B).

### U-29 — No form validation styling anywhere [UX][ACC]
Zero `:invalid` / `:error` / field-error CSS in the app; validation is toast-only
(e.g. "OVERRIDE REJECTED"). Textboxes that fail (Hoppie code, ICAO codes, port
numbers, perf CG) give no inline indication of which field is wrong. Proposal: add
a shared invalid-field treatment (red border + hint) driven by `:user-invalid` or
an `.invalid` class, with the toast as backup — a small but real usability gap.

### U-30 — One color token just under WCAG AA contrast [ACC]
`--dim: #74765f` on the page background measures 4.26:1 — just below the 4.5:1 AA
text threshold (muted #aaa98d is fine at 7.7–8.3:1; body text 16.7:1). The dim
token is used for secondary values in several panels. Proposal: lighten --dim by a
few points (e.g. #7d7f69) to clear 4.5:1. One-line token change.

### U-31 — OBS overlay: literal `?` glyphs in the route arrow and progress route [BUG]
`obs.js:38` renders the flight-strip route arrow as a literal `?`
(`<div class="route-arrow">?</div>`) and `obs.js:49` renders the progress overlay's
route separator as `<i>?</i>`. So the OBS overlays display "OJAI ? OLBA" exactly like
the old PIREP h1 bug (#48) — this file was never swept. Fix: `→` (U+2192) for both,
or a CSS-drawn arrow for `.route-arrow`. The CSS already styles `.route-arrow` as
an accent-colored glyph (`font-size:clamp(24px,3.3vw,46px)`), so a real arrow
character will look correct immediately.

### U-32 — OBS overlay: whole overlay blanks to "OPS ROOM UNAVAILABLE" on any one fetch failure [UX]
`render()` (obs.js:76) wraps every view in a try/catch that sets the ENTIRE
overlay to `OPS ROOM UNAVAILABLE`. Unlike renderFlight/Telemetry/Progress/Gsx
(which use per-fetch `.catch`), `renderLanding` and `renderStatus` have NO
try/catch on their single `json()` call — one failed `/api/logbook?limit=1` or
`/api/system/summary` request blanks the whole status/landing overlay for the
entire refresh cycle. Fix: give every view the same per-fetch `.catch(() =>
({}))` fallback pattern so a flaky endpoint degrades gracefully (shows `--`)
instead of nuking the overlay.

### U-33 — OBS overlay: metric grid overflows / clips when many fields are selected [BUG]
The metrics grid is `grid-auto-flow:column;grid-auto-columns:minmax(110px,1fr)`
with no wrapping, and each value has `white-space:nowrap;overflow:hidden;
text-overflow:ellipsis`. Selecting many fields (17 are offered) forces a single
row wider than the card → values clip with ellipsis and the card overflows the
shell (`width:min(100%,1800px)`). The user report "overlays are clipped" matches
this exactly. Fix: cap the number of columns per row (wrap into multiple rows via
`grid-auto-flow:row` + a max columns, or `repeat(auto-fit,minmax(110px,1fr))`)
and/or hide overflow gracefully.

### U-34 — OBS overlay: status/landing cards have large fixed min-widths → clip on narrow sources [BUG]
`.status-card` is `repeat(7,minmax(92px,1fr))` (≈ 644px minimum) and
`.landing-card` is `minmax(185px,1.1fr) repeat(6,minmax(95px,.55fr))` (≈ 755px
minimum). The studio lets users set the OBS source width down to 320px — at
narrow widths these two cards clip badly. Fix: a `@media(max-width:…)` wrap rule
for status/landing cards mirroring the existing 780px rule (which already wraps
flight/landing/status but at too low a breakpoint and with the same fixed
min-widths inside).

### U-35 — OBS overlay: scale > 1 clips at viewport edges (transform-origin) [UX]
The shell scales via `transform:scale(var(--scale));transform-origin:center`.
With scale > 1 (studio allows up to 160%) and a corner position (top-left,
bottom-right), the overlay grows outward from center and clips at the OBS source
edge — text/logo get cut off. Fix: position-aware transform-origin (e.g.
`position-top-left` → `transform-origin:top left`) or cap the scale for corner
positions.

### U-36 — OBS studio preview iframe height formula produces a wrong preview [UX]
`updateObsTools()` sizes the preview as `Math.round(760*height/width)` — for the
defaults (1280×260) that is `760*260/1280 ≈ 154px`, clamped to 180px — so the
preview does NOT match the configured OBS source dimensions, and changing height
barely moves it. The user sees a squashed preview that doesn't represent what OBS
will render. Fix: size the preview to the configured width/height ratio properly
(scale to fit, preserving the aspect ratio the user chose).

## Observations worth a backend look (not UI)

- **U-10b**: ~20 consecutive `PHASE_REJECTED from=ENROUTE to=CLIMB
  reason=impossible_transition` in the RJA403 recording — the phase machine flaps
  between ENROUTE and CLIMB for ~9 minutes (14:56–15:05Z). If that's a sensor
  race (altitude/VS oscillation near the enroute gate), it should be debounced in
  logbook._analyse, not just filtered in the UI.
- **U-12b**: duplicate finance statements for the same flight (TEST1 ×2, RJA403
  ×2 in the Recent statements list) — check economy finalize for a double-post
  path.

## Verification notes
- All pages reviewed on the live 0.25.75 build (Flight Watch, Status, Briefing,
  Dispatch, Datalink, Network, FIDS, Finances, Logbook, System, Black Box, Host
  Status, Host System Setup, plus traffic-board and obs HTML).
- All U-10/U-14 claims verified in source with line numbers (opsroom.js:6375 raw
  events slice; traffic_board.html:12/99 and obs.html:10/14 stale ?v=0-25-73).

### U-37 — Flight Completion sign-off review is too crowded / scattered [UX]
The post-arrival FLIGHT REVIEW modal (opsroom.js `lsSignSummaryHtml` completion
branch, #86) stacks three 4-column tables vertically — TIMES (6 rows), WEIGHTS
(3 rows), FUEL (5 rows) — then a 5-cell summary strip (BLOCK / FUEL USED /
AIRLINE RESULT / PILOT PAY / SATISFACTION) below, inside a 56rem-wide dialog.
Each table repeats its own 4-column header and the rows are tight
(`font-size:.62rem`, `padding:.16rem`), so the modal reads as one dense wall of
numbers with no visual hierarchy or flow — "all over the place".

Proposed redesign (implement in opsroom.js + opsroom.css, one component):
1. **Two-panel layout instead of three stacked tables**: left panel = TIMES
   (tall, 6 rows), right panel = WEIGHTS (top) + FUEL (bottom) — the natural
   reading order for a pilot review (when → how heavy → how much fuel).
2. **Drop the per-table repeated 4-column header**; use a single shared column
   header row per panel, with DELTA rendered as a compact inline chip
   (`+21` in amber) on the actual column instead of a full 4th column.
3. **More breathing room**: raise row font to ~.7rem, increase row padding,
   add clear section spacing and a subtle alternating-row tint.
4. **Summary strip becomes a footer bar**: one horizontal rule + the five
   stats evenly spaced with larger numbers (.85rem), labels beneath, instead
   of five separate bordered cells.
5. Keep the flight identity line as a compact eyebrow above the panels, and
   the sign pad/name/role form unchanged below.
Acceptance: at 56rem the dialog shows all three sections without scrolling,
each panel is visually distinct, and no cell text wraps or overflows.

Status: IMPLEMENTED (2026-08-12, source-side). `lsSignSummaryHtml` completion
branch now emits a two-panel layout (TIMES left, WEIGHTS + FUEL right via
`.ls-sign-panel` / `.ls-sign-panel-right`), and `#lsSignSummary` swaps its
class to `ls-sign-review-wrap` in completion mode so the 3-column
`.ls-sign-grid>div` rule can no longer hijack the review wrapper (that was the
real cause of the "all over the place" look). CSS bumped to `.7rem` rows with
more padding, amber tabular-nums delta values, and the summary strip is now a
footer bar with larger numbers. The loadsheet (pre-departure) branch keeps its
compact 3-column grid. Pending: rebuild + one post-arrival sign-off to view.
