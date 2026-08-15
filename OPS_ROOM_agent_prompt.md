# OPS ROOM — Multi-Repo Fix & Feature Work Order

You are working across three related codebases that make up the OPS ROOM ecosystem. Read this entire
document before touching any code. It is organized so each task states *where* to work, *what's wrong
today* (with the specific files/functions already identified), *what "done" looks like*, and *what must
not break*. Follow it in order — later tasks (especially the bot moderation/ticket work) depend on the
database-migration discipline defined in the ground rules below.

---

## 0. Ground rules — read first, apply everywhere

**0.1 — Check for skills first.** Before starting, look for a `.kiro/skills` directory at the root of
each repo you touch (app, website, bot). If it exists, read whatever skill files are inside and follow
their conventions for that codebase before writing any code. If it doesn't exist for a given repo, proceed
with the conventions already established in that repo's existing code (match existing style, naming, and
patterns — don't introduce a new framework, formatter, or architecture unless a task explicitly calls
for it).

**0.2 — Directories.** These are local working copies that push to the corresponding GitHub repos. Work
directly in these folders:

| Component | Local path | Pushes to |
|---|---|---|
| Desktop app | `E:\Ops Room Project\OPS_ROOM_v0_24_106_PUBLIC_BETA_BLACK_BOX_RC4_SOURCE_READY\OPS_ROOM_v0_24_106_SOURCE\opsroom-app\source` | `OpsRoomApp/ops-room-private-development` |
| Website + admin panel | `E:\Ops Room Project\OPS_ROOM_v0_24_106_PUBLIC_BETA_BLACK_BOX_RC4_SOURCE_READY\opsroom-website` | `OpsRoomApp/ops-room-website` |
| Discord bot | `E:\Ops Room Project\OPS_ROOM_v0_24_106_PUBLIC_BETA_BLACK_BOX_RC4_SOURCE_READY\ops-control-bot` | `OpsRoomApp/ops-control-bot` |

File paths and function names cited below were confirmed against the current `main` branch of each GitHub
repo. Re-verify against the actual local files before editing — line numbers may have drifted, and the
local copy is the ground truth, not my notes.

**0.3 — Do not break what already works.** Every task below is additive or corrective to a live,
in-use product. Before changing a file:
- Run/read enough of the surrounding code to understand what currently depends on it.
- Don't rename existing public function signatures, API routes, DB columns, WebSocket/IPC event names,
  CSS class names, or config keys unless a task explicitly requires it — other code and the deployed
  VPS instance rely on these staying stable.
- Where you must change a shared function's behavior, prefer additive changes (new optional parameter,
  new field) over rewrites.
- After each task, sanity-check the feature you touched still works end-to-end, not just that it compiles.

**0.4 — Database migrations are NOT optional, and must be idempotent.** The bot repo already has the
correct pattern for this in `src/bot/database/db.py`: a `CREATE TABLE IF NOT EXISTS` block for fresh
databases, plus a list of idempotent `ALTER TABLE ... ADD COLUMN` statements (wrapped so a "duplicate
column" error is swallowed) that runs automatically on every bot startup via `init_db()` /
`migrate_pending_actions()`. **This is the only mechanism you're allowed to use for schema changes.**

Rule: **any new column or table you need, for any task in this document, must be added to that
idempotent migration list — not just to the `CREATE TABLE` statement.** The `CREATE TABLE IF NOT EXISTS`
only fires on a brand-new database; the production database at `/opt/ops-control-bot/data/ops-control.db`
on the VPS already exists, so it will only ever pick up new columns through the `ALTER TABLE` migration
list. If you add a column to the `CREATE TABLE` block and forget the matching migration line, the
deployed bot will crash or silently misbehave on next restart — this exact failure mode has happened
before and cost significant manual VPS diagnosis time. Do not let it happen again. After writing each
migration line, trace through `init_db()` mentally (or with a test) confirming it runs cleanly against
**both** a fresh DB and a DB that already has the old schema.

The `admin-api` service mounts the *same* SQLite file read-write via a shared Docker volume
(`/opt/ops-control-bot/data` → `/ops-control-data` in `docker-compose.yml`). Any schema change the bot
needs for tickets/moderation/etc. must be written with admin-api's queries in mind too — check
`admin-api/discord.py` for existing queries against `tickets`/`bugs`/`users` before changing those tables.

**0.5 — Docker Compose / Dockerfiles must be fully wired, never left commented out.** If a task requires
a new service, volume, port, or environment variable in `docker-compose.yml` or a `Dockerfile` (in either
the website repo or the bot repo), it must be added live and active. Do not add new blocks as `#`
commented-out scaffolding "for later" — that has caused hours of debugging before because a required
service silently wasn't running. (The existing commented-out `postgres`/`redis` blocks already in the
bot's `docker-compose.yml` are pre-existing placeholders — leave those alone, don't uncomment them, but
do not add any *new* commented blocks following that pattern.) Every new env var must be added to the
relevant `.env.example` file with a sensible placeholder/comment, and referenced in `docker-compose.yml`
with a safe default via `${VAR:-default}` where a default makes sense, matching the existing style in
`website-repo/docker-compose.yml`.

**0.6 — Config over hardcoding.** Anything that plausibly differs between dev and prod (channel IDs,
role IDs, retention windows, API base URLs, feature toggles) goes in `.env` / `config.py`, following the
existing patterns in `bot/config.py` and `admin-api/config.py`. Never hardcode a Discord ID, guild ID, or
secret in source.

**0.7 — At the end of your work, produce a deployment report.** Once all tasks are complete, output a
single consolidated section titled `## VPS / Deployment Actions Required` listing, precisely:
- Every new `.env` variable added (for both the bot and the website/admin-api), what it's for, and
  whether it's required or optional with a safe default.
- Any new Docker volumes, ports, or services that need `docker compose up -d --build` to take effect,
  and which compose file(s) they're in.
- Confirmation that DB migrations are automatic on next bot restart, and explicitly state there is
  **nothing manual required** on the SQLite schema (if this is not true because of some edge case you
  hit, say exactly what manual step is needed and why it couldn't be automated).
- Any GitHub OAuth App / Discord Developer Portal configuration steps the user must do outside the
  codebase (e.g. registering a Discord OAuth redirect URI, generating a bot permission, creating new
  channel IDs to paste into `.env`).
- Any one-time backfill needed for existing open tickets/data, if applicable.

If a task needs zero VPS action, say so explicitly rather than omitting it, so the user knows nothing
was missed.

---

## PART A — Desktop App (`opsroom-app`)

### A1. Black Box recorder causing simulator stutter

**Files:** `app/black_box.py`, `app/simconnect_position.py`, `app/telemetry_provider.py`

**Diagnosis (confirmed):** The Black Box record loop (`_record_loop` in `black_box.py`) polls at up to
30 Hz during critical phases (takeoff roll, initial climb, approach, flare, landing roll, or any time
below 1000ft AGL — see `_target_interval`) and 20 Hz during taxi/climb/descent. Each poll calls
`read_telemetry(force=True, stream="minimal")`, which routes to
`read_position_minimal()` → `_read_position_minimal_uncached()` in `simconnect_position.py`. That function
reads **~40 distinct SimVars** one at a time via sequential `aq.get(name)` calls on a Python
`SimConnect.AircraftRequests` session created with `_time=125` (a 125ms per-variable refresh window).

That `_time` value governs how often *each individual variable* is re-subscribed at the SimConnect level —
it is not a global throttle. With ~40 concurrently-tracked variables, MSFS ends up streaming roughly
40 vars ÷ 0.125s ≈ 320 variable updates/sec continuously while a recording is active, which is the same
order of magnitude the codebase's own comment in `telemetry_provider.py` already flags as the cause of
measurable MSFS stutter for the *main* telemetry poller (that poller was fixed with a shared 0.8s cache —
the Black Box path deliberately bypasses that cache "by design" because it needs uncached freshness).

**What to do:**
1. Reduce the number of *distinct* SimConnect variable subscriptions active during a Black Box recording,
   without reducing the actual flight-dynamics data fidelity that black-box analysis needs. Concretely:
   - Split the current single `_read_position_minimal_uncached()` variable set into a "high-rate" tier
     (position, attitude, speeds, vertical speed — the things that genuinely change every frame and need
     20–30 Hz) and a "low-rate" tier (engine running flags, parking brake, flap/gear/spoiler position,
     wind, sim rate, pause/slew state — things that change rarely and don't need to be re-subscribed at
     the same rate as attitude data).
   - Poll the low-rate tier at a much lower fixed rate (e.g. 1–2 Hz) independent of `_target_interval`,
     and merge its last-known value into each high-rate sample rather than re-reading it every cycle.
   - This should cut concurrent SimConnect subscriptions during recording by roughly half or more without
     losing any field currently written to the `.opsbb` file.
2. Investigate whether `AircraftRequests`' internal `_time` can be set per-variable (some SimConnect
   Python wrapper versions support this) so high-churn vars (lat/lon/attitude) keep a tight period while
   low-churn vars use a longer one, as an alternative/complement to the tiering above. Check the installed
   `SimConnect` package's actual API surface before assuming this is available — don't guess.
3. Confirm whether batching multiple `SIMCONNECT_DATA_DEFINITION` fields into a single
   `RequestDataOnSimObject` call (instead of N separate `Request` objects, which is what
   `AircraftRequests.get()` does under the hood per-variable) is feasible with the currently vendored
   SimConnect wrapper. If the wrapper doesn't expose this cleanly, don't attempt a deep rewrite of the
   SimConnect wrapper itself — stay within `simconnect_position.py`.
4. Re-verify the actual achieved Hz via the existing `status()`/`diagnose()` telemetry (there's already
   an `actual_hz` field computed in `black_box.py`'s `status()`) before and after your change, and note
   the before/after numbers in your summary.

**Must not break:** the full (`stream="full"`) telemetry path used by the rest of the app (FIDS, PIREP,
GSX, RAAS, dispatch, replay) — do not touch its caching. The Black Box replay feature
(`black_box_replay.py`) reads from the same recorded schema (`FIELDS` list in `black_box.py`) — do not
remove or rename any field currently in `FIELDS`, only change *how often* the underlying SimVars are
fetched. Recording file format/schema version must stay backward compatible (bump `_SCHEMA_VERSION`
only if you truly change the stored row shape, and if you do, follow the existing append-only pattern
already used for the v1→v2 schema bump, visible in the comments around the `FIELDS` list).

**RESOLVED (2026-08-10) — superseded by Stage 2 (single-writer telemetry bus, see `BUG_FIX_TASKS.md`
#34 / "Implementation Plan — Stage 2"):** the Black Box record loop (`_record_loop`) no longer touches
the simulator at all. One `OpsRoom-TelemetryWriter` thread reads the sim and publishes to an in-memory
ring; the recorder is a pure ring consumer. FSUIPC (healthy) is one batched read per sample at 30/20/10 Hz
by phase; the SimConnect fallback uses a single batched `RequestDataOnSimObject` covering all 117 numeric
SimVars (one request per sample, ~27 Hz live-verified, no stutter) instead of ~40 sequential `aq.get`
calls. The per-variable `_time`/subscription mechanics described above no longer apply to the recorder
path. The `.opsbb` schema (`FIELDS`) is unchanged.

---

### A2. Briefing → Charts: pen/annotation drawing offset from cursor

**File:** `app/static/opsroom.js` — functions `getChartCanvasCoordinates`, `cfAnnotStart`, `cfAnnotMove`,
`cfRedrawAnnotations`, and the resize handler `resizeAnnotCanvas` inside the chart annotation setup block.

**Diagnosis (confirmed):** `getChartCanvasCoordinates()` normalizes each point as
`rx = canvasX / cfPdfState.nativeWidth` and `ry = canvasY / cfPdfState.nativeHeight` — i.e. normalized
against the PDF's *native* pixel resolution. But every place that later draws a point —
`cfAnnotMove()` and `cfRedrawAnnotations()` — renders with
`pts[i].rx * cfAnnotation.canvas.width` and `pts[i].ry * cfAnnotation.canvas.height`, where
`cfAnnotation.canvas.width/height` is the **overlay canvas's own CSS pixel size** (set in
`resizeAnnotCanvas()` to `rect.width`/`rect.height` of its wrapper), not the PDF's native resolution.
Those two denominators are only equal by coincidence at a specific zoom level — at any other zoom, or
after a window resize, the stored/replayed point lands in the wrong place relative to where the cursor
actually was. That's the offset.

**Fix:** Pick one consistent coordinate basis for both normalization and rendering, and use it
everywhere in this annotation subsystem:
- Simplest correct fix: normalize `rx`/`ry` against `canvas.width`/`canvas.height` (the same values used
  at render time) instead of `nativeWidth`/`nativeHeight`, i.e. make `getChartCanvasCoordinates` and the
  render functions agree on the same denominator. Since the overlay canvas is resized to track its
  wrapper on both zoom and window-resize (`resizeAnnotCanvas` + the `resize` listener), this keeps ink
  visually pinned under the cursor at draw time and correctly repositioned on any subsequent resize,
  because `cfRedrawAnnotations()` is already called after every resize.
- If there's a reason `nativeWidth`/`nativeHeight` normalization was chosen deliberately (e.g. to persist
  annotations in a zoom/pan-independent PDF-page coordinate space so saved strokes stay correctly
  positioned across sessions even if the viewer resizes between saves) — that's a reasonable *goal*, but
  the implementation must then also render with `nativeWidth`/`nativeHeight` as the multiplier
  (transforming that fixed coordinate space into the current canvas size via a single explicit scale
  factor `canvas.width / nativeWidth` applied consistently), not mix the two bases as it does today.
  Check `cfSaveAnnotations`/`cfLoadAnnotations` (persists to `localStorage` per chart ID) to see which
  basis existing *saved* strokes are stored in before deciding — you may need to keep the stored format
  as PDF-native-relative for backward compatibility with already-saved annotations, and instead fix only
  the *rendering* multiplier to match, rather than changing what's persisted.
- Also check whether the underlying PDF/chart canvas itself is transformed via CSS
  (`canvas.style.transform = 'translate(...) scale(...)'`, used in `cfAutoFitToScreen` for the base
  chart canvas, separate from the annotation overlay) — confirm the annotation overlay canvas and the
  base chart canvas are always sized/positioned in lockstep (same wrapper, same rect) so pan/zoom on the
  chart doesn't desync the two independently of the rx/ry bug above.

**Test explicitly:** draw at multiple zoom levels (below 100%, at 100%, above 100%), pan the chart and
draw again, resize the app window mid-session and draw again, reload a chart with previously-saved
annotations and confirm they render in the same place they were drawn (not just that new strokes track
correctly). Also test eraser and highlighter tools, since they share the same coordinate path.

---

### A3. Add a "Join Discord" button to the top bar

**File:** `app/static/index.html` (header markup), plus matching CSS in `app/static/opsroom.css`
(or wherever `.efb-header-actions` / `.notification-button` are styled) and any JS wiring if the button
needs an open-external-link handler consistent with how other external links are opened in this app
(check how existing outbound links, e.g. the SimBrief "OPEN IN SIMBRIEF" buttons in the dispatch module,
open URLs — desktop apps sometimes need `shell.openExternal` or similar rather than a plain `<a>` if this
is an Electron-style host; match whatever pattern is already used).

**What to do:** Add a Discord icon button in `.efb-header-actions`, positioned immediately to the left of
`#efbNotificationButton` (i.e. "next to the notification bell" — confirm with the user's phrasing whether
they want it left or right of the bell; default to left of the bell, before the notification button, matching
typical top-bar icon ordering, and easy to swap either way). Link target:
`https://discord.gg/Dv6fNAjhAt`. Use a proper Discord glyph (inline SVG, consistent with how the bell icon
is done inline as SVG in the same file — do not pull in an external icon font/image dependency for this).
Match the existing button's sizing, hover state, and accessibility attributes
(`aria-label="Join Discord"`, keyboard-focusable, same as the notification button's `aria-label` pattern).

There are actually **three** near-identical notification button instances in `index.html`
(`#efbNotificationButton`, `#efbModuleNotificationButton`, `#notificationButton`) for different layout
contexts (main EFB header, per-module header, and a third context). Confirm with visual/manual testing
which one is the actual persistent top bar the user means, and add the Discord button to that one — don't
blanket-add it to all three unless they're all simultaneously visible in different views and all three
currently duplicate the same top-bar role.

**Must not break:** notification bell click behavior/drawer toggle, and don't change `.efb-header-actions`
flex layout in a way that pushes the profile pill (`.efb-profile-pill`) off-screen at smaller window sizes.

---

### A4. Dispatch module: amber/gold over-dominant, and aircraft type field shows raw ADS-B ICAO instead of type

**Files:** `app/static/opsroom.css` (search for `.dispatch-*` class rules — they start around the
`.dispatch-search-panel` block), `app/airline_branding.py`, `app/static/opsroom.js`
(`renderRealworldResults`, `renderDispatch`), `app/flight_model.py`
(`normalise_adsb`, `apply_adsbdb_aircraft`), `app/adsbdb_client.py`.

**A4a — Color dominance (confirmed):** The app has a global `--amber` CSS variable
(`#efbd47` by default) used app-wide as *one of several* accent colors, alongside green/red status
colors, mixed sparingly. In the Dispatch module specifically, `var(--amber)` / `var(--amber-pale)` is used
far more densely than in comparable modules — it's the color for labels, borders, score numbers, route
text, the primary action button background, hover states, and badges nearly everywhere in
`.dispatch-form`, `.dispatch-card`, `.dispatch-score`, `.dispatch-route`, `.dispatch-metrics`, and
`.dispatch-actions`. That's why it reads as visually dominant compared to other modules that reserve
amber for genuine emphasis/alerts and otherwise use the neutral text/line palette.

Reference `app/assets/brand/opsroom_brand_identity_board.png` for the correct brand palette and which
colors are meant to be primary vs. accent-only. Rework the Dispatch module's CSS so that:
- Amber is reserved for genuine emphasis (e.g. the primary "SEARCH ROUTES" action button, active/selected
  state, and maybe the score number) — not the default color for every label, border, and static text
  element.
- Neutral/muted tones (the existing `--text`, `--muted`, `--line` variables already used elsewhere)
  become the default for labels, borders, and body text within `.dispatch-*` classes, matching the
  restraint used in e.g. the briefing/procedures panels.
- This must still respect the **airline livery theming system** already in `airline_branding.py` /
  `host.css` (`.airline-theme`, `--airline-bg-image`, `--airline-overlay-start/end`): when an airline
  livery/background is active, the module's accent should continue to derive from that airline's theme
  colors as it does elsewhere in the app; when no airline is set, it should fall back to the *default*
  app accent scheme used everywhere else — not a dispatch-specific amber-heavy override. Check how other
  modules (briefing, procedures) already integrate with `.airline-theme` and follow the same pattern here
  rather than inventing a new one.

**A4b — Aircraft type field bug (needs live verification, not just a code read):** The "Real World"
tab within Dispatch (`renderRealworldResults` in `opsroom.js`, backed by `/api/v1/realworld/search`,
sourced from `app/realworld.py` + `app/flight_model.py` + `app/adsbdb_client.py`) is supposed to display
each flight's aircraft type (e.g. "A320", "B738") in the `.rw-card-aircraft` line. The field is sourced
from `flight.aircraft_type`, which is populated in `flight_model.py` by:
- `normalise_adsb()`, from the raw ADS-B feed's `t`/`type` key, and
- `apply_adsbdb_aircraft()`, which enriches from ADSBDB's aircraft lookup, mapping its `type` key to
  `aircraft_type` and its `icao_type` key to a separate `aircraft_icao_type` field, falling back to the
  latter only if the former is empty.

There is already a temporary debug line in `renderRealworldResults`
(`console.log("REALWORLD FLIGHT CARD DATA", flight)`) left in from a prior debugging pass at this exact
spot — use it. Run the app against a live ADS-B feed (or capture a real API response from
`/api/v1/realworld/search`), and inspect the actual JSON payload for a flight where the aircraft-type
display is wrong. Confirm precisely which field is landing in `aircraft_type` — the likely culprit is a
naming collision between "ICAO **aircraft type designator**" (e.g. "A320", what should be displayed) and
"ICAO **24-bit address / Mode-S hex**" (e.g. "A0F3C1", what ADS-B providers and ADSBDB both also loosely
call an "icao"/"hex" field in different parts of their schemas) — i.e. the wrong ICAO is being mapped
into `aircraft_type` somewhere in the raw-feed parsing or the ADSBDB response unwrapping. Trace the exact
field from raw provider response through `normalise_adsb`/`apply_adsbdb_aircraft` to the rendered value
and fix the specific mis-mapped key — do not guess at a fix without confirming against a real payload
first, since the field name in the live ADS-B/ADSBDB response may not match assumptions from reading the
client code alone.

**Must not break:** the rest of the ADS-B/real-world traffic pipeline (route display, registration,
airline name, telemetry line, "IMPORT TO DISPATCH" / "OPEN IN SIMBRIEF" actions which also consume
`actype`) — trace all consumers of `flight.aircraft_type` and `flight.aircraft_icao_type` before renaming
or restructuring either field, since `launchSimBriefFromRW` also passes `actype` through to SimBrief as
`basetype`.

---

## PART B — Discord Bot (`ops-control-bot`)

### B1. Ticket system: channel not deleted on close, no reason prompt, ugly transcript

**Files:** `src/bot/cogs/ticket_system.py`, `src/bot/services/ticket_transcript.py`,
`src/bot/database/db.py` (migrations), `.env.example`, `docker-compose.yml`.

**Diagnosis (confirmed):** The delete-on-close logic **already exists** — `close_ticket()` in
`ticket_system.py` calls `channel.delete()` after a successful transcript delivery. But it's gated:
`close_ticket_with_transcript()` in `ticket_transcript.py` returns `transcript_status = "failed"` (which
deliberately *preserves* the channel instead of deleting it, so nothing is lost) whenever
`TICKET_TRANSCRIPT_CHANNEL_ID` is unset or the bot can't post to that channel. **First, check whether
`TICKET_TRANSCRIPT_CHANNEL_ID` is actually set in the VPS `.env` today** — if it isn't, that alone
explains the reported bug and is a config fix, not a code fix. Fix the code robustness regardless (see
below), but call this out explicitly in your final report so the user checks their live `.env`.

**What to build:**
1. **Close reason modal.** Change the "Close Ticket" button handler so staff are prompted with a
   `discord.ui.Modal` (short text input, optional or required — make it required with a sensible min
   length) asking for a close reason before the close proceeds. Store the reason on the ticket row (new
   `close_reason TEXT` column — add via the idempotent migration list per rule 0.4) and include it in the
   transcript and the close-log embed (`log_ticket_closed`).
2. **Make channel deletion reliable.** Don't weaken the "preserve on transcript failure" safety net (it's
   correct behavior to not silently lose a transcript) — instead, make failure less likely and more
   visible: retry transcript delivery once on transient failure, and if `TICKET_TRANSCRIPT_CHANNEL_ID` is
   simply unset, treat that as a distinct, clearly-logged configuration error (not a generic "failed")
   so it's obvious in logs/the ephemeral response why the channel wasn't deleted, rather than a silent
   preserve.
3. **Redesign the transcript** so it's actually readable by non-technical users, and move delivery from
   "upload an HTML file to a Discord channel" to a **hosted transcript page on opsroom.live**:
   - Bot side: on close, instead of (or in addition to) posting the HTML transcript file to Discord, POST
     the transcript data (messages, author, timestamps, embeds, attachments metadata, ticket
     metadata — subject, priority, creator, assigned staff, opened/closed timestamps, closed-by, close
     reason) to a new authenticated endpoint on `admin-api` (see B-website section below for the API
     side). Keep a fallback: if the website endpoint is unreachable, still fall back to the current
     Discord-upload behavior so a transcript is never fully lost.
   - The bot should then post a clean, well-formatted embed in place of the raw HTML dump — ticket
     number, subject, participants, duration, close reason, and a link to the hosted transcript page
     (e.g. `https://opsroom.live/transcripts/{ticket_id}`), plus a note that the link expires in 14 days.
   - Also DM the ticket creator the same link (there's already a `transcript_dm_sent` column and DM logic
     pattern to follow — check how it's used today before adding a parallel path).
4. **Delete the channel** once the transcript has been durably delivered (Discord-side upload, hosted
   endpoint, or both per your fallback design) — same as today's logic, just make the success condition
   include the new hosted-transcript path.

**DB migration:** add `close_reason TEXT` to `tickets` (and `bugs` if reason should apply there too —
confirm bug-close flow should get the same treatment; the current code closes bug channels without any
transcript workflow at all, so decide and note in your report whether bugs get reasons+transcripts too or
stay as-is). Add every new column through the idempotent `ALTER TABLE` list in `db.py`, per rule 0.4.

**Must not break:** ticket **claim** flow, the bug-report close flow (unless you deliberately extend it,
per above), idempotent double-close handling (already there — don't remove the "already closed" no-op
check), and the existing `log_event`/`log_ticket_closed` audit trail.

---

### B2. Full moderation suite

**Files:** new `src/bot/cogs/moderation.py` (or split into `moderation.py` +
`automod.py` if that's cleaner — match how e.g. `weather.py`/`weather_group.py` are already split in this
codebase), `src/bot/database/db.py` (new tables/columns), `.env.example`, `docker-compose.yml`,
`src/bot/utils/permissions.py` (extend existing permission-check patterns rather than duplicating them).

**Scope — build all of the following:**

*Core actions* (slash commands, staff-permission-gated using the existing `_is_staff`-style pattern
already used in `ticket_system.py` / `permissions.py`):
- `/warn <user> <reason>` — logs a warning, DMs the user the reason, posts to mod-log.
- `/kick <user> <reason>`
- `/ban <user> <reason> [delete_message_days]`
- `/unban <user_id> <reason>`
- `/timeout <user> <duration> <reason>` (Discord native timeout) and `/untimeout <user>`
- `/mute <user> <reason>` / `/unmute <user>` if you want a role-based mute in addition to native timeout
  (useful for durations Discord's native timeout doesn't support, or a permanent mute) — decide based on
  whether native timeout alone covers the need, and note your reasoning in the report.
- `/modcase <user>` — show a user's full moderation history (see "case history" below).

*Automod* (event-listener based, configurable — see admin panel task C4 for the config UI):
- Spam detection (message-rate threshold per user per channel window).
- Excessive mentions (mass-mention/raid pattern).
- Link filtering (domain allowlist/blocklist, configurable).
- Excessive caps / repeated-character spam.
- Each automod trigger should have a configurable action (delete + warn, timeout, or just log) and be
  toggleable per rule, not just globally on/off.

*Logging:*
- A persistent mod-log channel (configurable via `.env`/admin panel, same pattern as
  `LOG_CHANNEL_ID`/`BUG_REPORTS_CHANNEL_ID` already in `.env.example`) that receives an embed for every
  moderation action (manual or automod-triggered), including actor, target, reason, and timestamp.
- Store every action in a new `moderation_cases` table (user_id, guild_id, action_type, reason,
  moderator_id, created_at, expires_at nullable for timeouts/mutes, active boolean) so history is
  queryable later (both by `/modcase` and by the admin panel — see C4).

*Appeal system* (per the "both web + DM" decision):
- A **public web form** on opsroom.live (no login required, since a banned user has no way to
  authenticate via the bot/Discord) where a user can submit an appeal referencing their Discord user ID
  or username, the action being appealed, and their statement. This needs a new admin-api endpoint +
  website page — coordinate with Part C.
- A **DM-based path**: the bot DMs a banned/timed-out user (where technically possible — note that a ban
  prevents future DMs unless sent at ban time, so send the appeal-form link and instructions **at the
  moment the ban/timeout is issued**, not after) with the same web-form link and a short explanation.
- Both paths feed into the same `appeals` table/review queue, surfaced in the admin panel (C4) for staff
  to approve/deny with a resulting action (e.g. approve → unban/untimeout automatically via a call from
  admin-api back to the bot, or a pending-action row the bot's existing dispatcher already knows how to
  poll — check `PENDING_ACTION_POLL_SECONDS`/`pending_actions` table, since this exact "admin panel
  queues an action, bot dispatcher executes it" pattern already exists for other admin actions; reuse it
  here instead of building a new bot↔admin-api channel).

**DB migrations:** new `moderation_cases` and `appeals` tables, added via the same `CREATE TABLE IF NOT
EXISTS` + nothing-else-needed pattern only for genuinely new tables (new tables are safe on every startup
via `IF NOT EXISTS` — it's *columns added to existing tables* that need the `ALTER TABLE` migration list;
don't confuse the two). If you add any column to an *existing* table (`users`, `tickets`, etc.) for this
feature, that column goes in the `ALTER TABLE` list per rule 0.4.

**Must not break:** existing `/purge` (fold it into the moderation cog's command group for consistency
if that's a clean move, but don't change its existing behavior/permission level), and existing role-based
permission checks used elsewhere (`MODERATOR_ROLE_ID` already exists in `.env.example` — reuse it as the
base moderation permission rather than inventing a parallel role concept).

---

### B3. VATSIM event reminders

**Files:** extend `src/bot/cogs/vatsim.py` or add `src/bot/cogs/vatsim_events.py`.

Poll the VATSIM events API on a schedule (background task, matching the polling-loop pattern already used
elsewhere in the bot, e.g. `PENDING_ACTION_POLL_SECONDS`-style config). Auto-post new upcoming events to a
configurable events channel, and send a reminder (channel ping and/or role ping — configurable) a
configurable number of minutes before start (default 30). Avoid duplicate posts on bot restart — track
posted/reminded event IDs in a small new table.

---

### B4. Reaction-role panel

**Files:** extend `src/bot/cogs/roles_cog.py`.

Add a persistent message with either reaction-based or button-based role toggles (match whichever
paradigm `roles_cog.py` already partially supports — check its current `/roles` implementation before
choosing) covering the existing role categories already handled manually (simulator, network, beta
tester). Must survive bot restarts (persistent `discord.ui.View` with `custom_id`s registered on startup,
consistent with how `SupportPanelView` in `ticket_system.py` already does this — follow that exact
pattern).

---

### B5. Changelog auto-announce

**Files:** `src/bot/services/github_release.py`, `src/bot/cogs/releases.py`.

The bot's own README already flags this as built-but-unwired: *"GitHub release service ready but not yet
wired to auto-announce."* Wire it: on a new GitHub release being detected (poll on the same interval
pattern used for `/latest`, or use a webhook if `github_release.py` already supports one — check before
building polling from scratch), auto-post a formatted announcement to `DISCORD_ANNOUNCEMENT_CHANNEL`
with the version, release notes summary, and download link, reusing the existing `/changelog`/`/latest`
formatting logic rather than duplicating it.

---

### B6. Where2Fly — verify readiness, don't rebuild

**File:** `src/bot/services/routes/where2fly.py`.

This is **already fully implemented**: it reads `WHERE2FLY_API_TOKEN` from config, calls the documented
`POST /api/search` endpoint with bearer auth, and the bot already falls back gracefully to the local
route engine when the token is empty (confirmed in the module's own docstring and `config.py` usage).

Your job here is verification, not construction:
1. Confirm `WHERE2FLY_ENABLED`, `WHERE2FLY_API_TOKEN`, `WHERE2FLY_API_BASE_URL`, and
   `WHERE2FLY_TIMEOUT_SECONDS` are all present in `.env.example` with correct defaults (they should be —
   double check).
2. Confirm `/randomroute` in `randomroute.py` correctly prefers the Where2Fly provider when a token is
   present and falls back cleanly when it's not, and that the "Suggested Operator / Suggested Callsign"
   attribution requirement from Where2Fly's terms (already noted in the module's docstring) is actually
   honored in the command's output formatting.
3. Write/confirm a test (check `tests/test_where2fly.py`, extend if thin) that exercises both the
   token-present and token-absent paths without requiring a real API key (mock the HTTP call).
4. Do **not** add any new required configuration beyond the API key itself. If you find the architecture
   is *not* actually ready for a drop-in key (e.g. missing error handling for a rate-limit response, or
   the attribution text is missing from output), fix that gap now so that literally pasting a token into
   `.env` is the only remaining step, and say so explicitly in your final report.

---

## PART C — Website + Admin Panel (`opsroom-website`)

### C1. Hosted ticket transcripts (public link, PDF export, 14-day expiry)

**Files:** new endpoints in `admin-api/` (e.g. new `admin-api/transcripts.py` router, following the
existing router pattern in `discord.py`/`releases.py`), new public page(s) in `admin/src/pages` or the
main site's `src/pages` (public, unauthenticated — decide which app these belong in: since they must be
publicly viewable without login per the "public link" decision, and the main `opsroom-website` app is the
public-facing one while `admin/` is the staff-only SPA, these transcript *viewer* pages likely belong in
the main website's routing, not the admin SPA — the *management/administration* of transcripts, if any,
can live in the admin SPA), `docker-compose.yml` (new volume for stored transcripts), `.env.example`.

**What to build:**
1. New admin-api endpoint(s) to receive a transcript payload from the bot (see B1) and store it — decide
   file-based (e.g. `/opt/opsroom-transcripts/{ticket_id}.json` + rendered artifacts, mirroring the
   existing `/opt/opsroom-releases` volume pattern already used for release ZIPs) vs. DB-based
   (new `admin-api` SQLite table). File-based following the releases pattern is likely simplest and most
   consistent with this codebase's existing conventions — but your call, just be consistent with existing
   patterns rather than introducing a third storage paradigm.
2. A public page at `https://opsroom.live/transcripts/{ticket_id}` (or similar) rendering the transcript
   in the same clean, on-brand visual style as the rest of the public site (reuse `Layout`/`SEO`
   components from `src/components`, per the site's existing structure) — clear message bubbles,
   author names/avatars if available, timestamps, and the ticket metadata header (subject, priority,
   participants, opened/closed times, close reason). This replaces the current raw-HTML-dump look
   entirely.
3. A "Download PDF" button on that page that generates/fetches a PDF version of the transcript
   server-side (admin-api endpoint) — reuse any existing PDF-generation dependency if one's already in
   `admin-api/requirements.txt`, otherwise add a lightweight one consistent with a Python/FastAPI stack.
4. **14-day auto-expiry:** a scheduled cleanup job (background task in admin-api, or a cron-style loop —
   match whatever scheduling pattern, if any, already exists in admin-api; otherwise a simple
   `asyncio` background task started alongside the FastAPI app is fine) that deletes transcripts older
   than 14 days (configurable via `.env`, e.g. `TRANSCRIPT_RETENTION_DAYS=14`). After expiry, the public
   URL should return a clear "this transcript has expired" page, not a raw 404.
5. New Docker volume for transcript storage, wired into `docker-compose.yml` for the `admin-api` service
   (and the main `opsroom-website` service if it also needs read access to serve the public pages —
   depends on your architecture choice above), following the existing volume-mounting style already used
   for `/opt/opsroom-releases`.

**Must not break:** the existing `/opt/opsroom-releases` release pipeline and its volume mounts, and the
existing GitHub-mirror fallback behavior for update manifests (unrelated system, just don't cross wires
between the two volumes).

---

### C2 + C3. Admin panel overhaul — Discord section + Discord OAuth login

**Files:** `admin/src/pages` (Discord-related pages), `admin/src/components`, `admin-api/discord.py`,
`admin-api/auth.py`, `docker-compose.yml`, `.env.example`.

**C2 — Visual overhaul of the Discord section.** The current admin-api already exposes a fairly complete
Discord data surface (`/status`, `/analytics`, `/tickets`, `/bugs`, `/announcements`, `/pending-actions`,
`/users`, `/beta-testers`, `/audit-logs`). Rework the corresponding admin frontend pages for these to
look and function better — apply the same design-quality bar as the rest of the admin dashboard (check
`admin/src/components` for the existing design system/tokens and reuse them, don't invent a new visual
language for just this section). At minimum this should include real charts/graphs where the API already
returns time-series-shaped data (`/analytics`), a proper filterable/sortable table for tickets and bugs
(rather than whatever's there now), and clear status indicators for `/status`.

Extend the Discord section with the new capabilities this work order adds elsewhere:
- **Bot health/uptime graph** — historical view, not just the current snapshot.
- **Ticket volume & response-time analytics** — average time-to-claim, time-to-close, volume by
  priority/day — computed from the `tickets` table (now enriched with `close_reason` from B1) via a new
  or extended `/analytics`-style endpoint.
- **Moderation case history view** — per-user case list (from `moderation_cases`, B2), and a global
  recent-actions feed.
- **Automod configuration UI** — CRUD for the automod rules/thresholds from B2 (currently would otherwise
  be `.env`-only; make it panel-configurable, writing to the bot's DB or a config table the bot reads on
  each check, whichever is cleaner given how automod state is stored in B2).
- **Appeal review queue** — list of pending appeals (from `appeals`, B2) with approve/deny actions that
  route through the existing `pending_actions` dispatcher pattern back to the bot.
- **Announcement scheduling + templates** — extend the existing `create_announcement`/`/announcement`
  flow with a "send at" scheduled time and a small saved-template picker, rather than only immediate send.
- **Audit log export/filtering** — extend `/audit-logs` with proper date-range and type filters (there's
  already an `/audit-logs/types` endpoint to build the filter UI from) and a CSV export button.
- **Staff/allowlist management UI** — a screen to view/add/remove entries in the Discord user-ID allowlist
  (from C3 below) without hand-editing `.env`. Note: since the allowlist is currently an `.env` var,
  decide whether to move it to a small DB table (recommended, so the panel can actually manage it live
  without a redeploy) or keep it `.env`-only with the panel just displaying current values read-only and
  instructing a redeploy for changes — the former is clearly better UX and is the intent behind adding a
  management UI at all, so migrate `APPROVED_GITHUB_USERS`/`APPROVED_DISCORD_USERS` to a DB-backed
  allowlist table if that's not excessive scope creep for this task; if you do, keep `.env` as a
  first-boot seed so existing deployments aren't locked out on upgrade.

**C3 — Discord OAuth login, allowlisted by Discord user ID.** Mirror the existing GitHub OAuth pattern in
`admin-api/auth.py` exactly (authorize redirect → callback with state validation → JWT session in an
httpOnly secure cookie) as a **second, parallel** login option — do not remove or replace GitHub OAuth,
both must work side by side per the earlier decision. New env vars: `DISCORD_CLIENT_ID`,
`DISCORD_CLIENT_SECRET`, `DISCORD_REDIRECT_URI`, `APPROVED_DISCORD_USERS` (comma-separated Discord user
IDs, same shape as `APPROVED_GITHUB_USERS`). The login page should offer both "Sign in with GitHub" and
"Sign in with Discord" buttons. Use the same rate-limiting and audit-logging (`_rate_limit`, `_audit_log`)
already present in `auth.py` for the new flow rather than writing parallel logic.

**Must not break:** existing GitHub OAuth sessions/cookies for already-logged-in staff, and the existing
`verify_session` dependency used by every other admin-api router — both auth methods must produce a
session shape that `verify_session` accepts identically, so downstream routers don't need to know which
provider a session came from.

---

### C4. Public appeal form

**Files:** new public page in the main website (`src/pages`), new admin-api endpoint.

A simple, unauthenticated form (Discord username or user ID, which action is being appealed if known,
and a free-text statement) that submits into the same `appeals` table/queue from B2. Include basic abuse
protection (rate-limit by IP, matching the existing `_rate_limit` pattern in `auth.py`) since it's public
and unauthenticated.

---

### C5. Licenses/pricing panel overhaul

**Files:** `admin-api/licenses.py`, `admin-api/pricing.py`, and their corresponding `admin/src/pages`.

Apply the same visual-quality pass as C2 to these existing panels — bring them in line with the rest of
the overhauled admin dashboard's design system. Scope here is presentation/UX, not new functionality,
unless while reviewing the existing endpoints you find an obvious gap (e.g. no edit history, no
validation) worth flagging — if so, note it in your final report as a suggestion rather than silently
expanding scope.

---

## Final reminder

Re-read rule 0.7 before you consider this done. The deployment report is not optional — every task in
this document touches either a database schema, an environment variable, or a Docker service, and the
user has explicitly said the single biggest pain point from prior work was undocumented/incomplete VPS
steps. A task is not complete until its deployment implications are captured in that final report.
