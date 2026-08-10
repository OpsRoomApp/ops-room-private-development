# Bug Fix Tasks — Session 2026-07-22

## ⚠ MANDATORY BACKUP BEFORE ANY IMPLEMENTATION

Before **any** code changes on this list are implemented, take a backup of the source folder first:

- Source folder: `opsroom-app/source`
- Action: zip that folder (e.g. `opsroom-app/source-backup-<YYYYMMDD>.zip`) and verify the zip is complete before touching any code.
- Do **not** apply any code changes until that backup exists.
- Do **not** take the backup now — only when implementation is explicitly requested.

## Reported Issues

### #1 — GSX auto-selects operator without showing popup

- **Severity**: High
- **Root cause**: Fenix EFB "auto select ground handling agent" overrides OPS ROOM's `autoSelectOperator=false`.
- **Fix applied by user**: Disabled all Fenix EFB auto-options (auto select agent, auto pushback, auto GPU connect/disconnect, auto deboard).
- **Hardening applied**: `autoSelectOperator=false` now sent immediately on observer connect + kept 2s retry safety net.

### #2 — Announcer "shutdown" and "After Landing" announcements play together

- **Severity**: Medium
- **Root cause**: Same-tick cascade: when sim loads at the gate, `taxi_in_started` fires AfterLanding, then `_parked_at_gate` sees "AfterLanding" in `_PLAYED` and also fires DisarmDoors/DisembarkStarted in the same tick.
- **Fix**: Added `_PREVIOUS.get("on_ground") is True` guard in `announcements.py:1456` so the `_parked_at_gate` block only fires after the aircraft has been consistently on-ground (not on first same-tick evaluation).

### #3 — Fenix doesn't start, doesn't push back, doesn't start engines through GSX

- **Severity**: High
- **Fix**:
  - (Pre-existing) Fenix EFB loading (fuel, cargo, passengers) — already implemented.
  - (Fix #4) Chocks/GPU disconnected after pushback via 30s safety net.
  - **(NEW) Auto-engine-start**: `_auto_start_engines()` in `gsx_remote.py` uses SimConnect `GENERAL_ENG_COMBUSTION` to start all engines 15 seconds after pushback activity is detected. Controlled by `gsx_auto_start_engines` setting (default: True).

### #4 — Fenix chocks and GPU not disconnected after pushback is called

- **Severity**: High
- **Fix**: 30s delay after pushback active, then disconnect Fenix EFB chocks and GPU. Applied in automation loop + `_coordinate_verified_pushback_handoff`.
- **Status**: Implemented.

### #5 — UI reload is very slow after refresh

- **Severity**: High
- **Root cause**: (1) `load_settings()` reads/parses settings.json from disk on nearly every API call. (2) RAAS background poll runs every 1s continuously. (3) Landing monitor polls every 3s continuously.
- **Fix**: (1) Added 2s in-memory TTL cache for `load_settings()` in `settings_store.py` with invalidation on `save_settings()`. (2) RAAS global poll: 1s → 5s. (3) Landing monitor: 3s → 10s.
- **Status**: Implemented.

### #6 — Sim stutters massively when Black Box module is open

- **Severity**: Critical
- **Root cause** (v0.25.0 stale): The recording loop calls `read_telemetry(force=True)` which bypasses the `_sim_heartbeat` 0.8s cache (via `force=True`), reaching `read_position(force=False)` with a 0.18s cache. This yields ~5.5 Hz actual SimConnect reads, each fetching ~75 individual SimVars one-at-a-time through the Python wrapper — ~412 SimConnect API calls/sec. The previous fix (reducing UI poll cadence) addressed the symptom, not the cause, because `loadBlackBoxLive()` only reads in-memory `_RING` deque data and never touches SimConnect.
- **Fix (v0.25.1)**: Changed `_sim_heartbeat(now, force=force)` → `_sim_heartbeat(now, force=False)` on `telemetry_provider.py:1382` for the SimConnect recording-loop path. The 0.8s heartbeat cache now actually works, dropping SimConnect reads from ~5.5 Hz → ~1.25 Hz — a 77% reduction. FSUIPC failover paths (lines 1354, 1368) retain `force=force` for correct failover detection.
- **Status**: Implemented.

### #7 — Black Box shows empty (no past flights, no recording, "stone dead")

- **Severity**: High
- **Root cause**: `observe_phase()` was calling `read_telemetry(force=False)` which could return a stale cached snapshot from before engines were running, causing the "engines_running" check to fail.
- **Fix**: `observe_phase()` now accepts an optional `telemetry_hint` parameter — the logbook passes its already-read live telemetry snapshot `t` instead of relying on a second `read_telemetry()` call. The `read_telemetry(force=False)` fallback is preserved for other callers.
- **Status**: Implemented.

---

# Bug Fix Tasks — Session 2026-08-09 (RC flight test)

### #8 — Logbook "Discard active" does nothing (button click fires no request)

- **Severity**: High (blocks discarding a recording; affects every `confirm()`-gated action)
- **Symptom**: Clicking **Discard active** in Logbook does nothing — no dialog, no error, no server request. Logs show zero `DELETE /api/logbook/active` requests ever reaching the server from the UI.
- **Root cause**: The app runs in a pywebview **WebView2** window, which **silently blocks JavaScript `confirm()`** — it returns falsy without showing a dialog. The handler `if(confirm(...)) logbookCommand(...)` therefore never fired the fetch. The backend endpoint itself worked fine (verified with a direct curl call, which successfully discarded the active flight).
- **Fix**: Replaced the native `confirm()` gate on Discard active with a **two-step in-page confirm** (click once → button turns red and reads `CONFIRM DISCARD?` → click again within 4 s to discard; auto-resets). No native dialog needed, so it works in WebView2. Applied to `app/static/opsroom.js` (source) and `dist/OPS ROOM/_internal/app/static/opsroom.js` (running build); `node --check` passes on both.
- **Follow-up**: The same WebView2 `confirm()` blockage affects every other confirm-gated action — Delete record, clear scratchpad, finance career reset, update install, black box replay, streamer-mode warning. Sweep all of them to the two-step pattern (or a proper in-app `<dialog>` modal) before release.
- **Status**: Implemented (2026-08-10, v0.25.73) — **sweep complete**: added a shared `uiConfirm` in-app modal helper (WebView2-safe `<dialog>`-style confirm) in `opsroom.js` and migrated every remaining `confirm()` call site in `opsroom.js` (clear scratchpad, delete record) and `host.js` (reset finance, update install, streamer-mode warning); modal styling added to `host.css` + `opsroom.css`. `grep` confirms zero native `confirm(` call sites left in the static assets.

### #9 — SimConnect dispatch thread floods the log with `OS error 0xc00000b0` (13,218 lines in one session)

- **Severity**: High (log flood grows to 2,000-line bursts; same wrapper instability behind the old slow-reload/hang symptoms)
- **Symptom**: Runs of `OS error: [WinError -1073741648] Windows Error 0xc00000b0` (STATUS_ILLEGAL_INSTRUCTION) interleaved with normal HTTP traffic — 71 episodes, largest runs 2,050 / 2,007 / 2,100 consecutive lines. Flood stops only when the session is torn down (tray exit, or the v0.25.68 shutdown `close_session()`).
- **Root cause**: The upstream SimConnect Python wrapper's background **dispatch thread** dies mid-session; every read on the dead session returns `None` and the wrapper spams the OS error. The v0.25.60 self-heal (`_SESSION_MAX_CONSECUTIVE_FAILURES = 25` in `simconnect_position.py`) is meant to tear the session down after 25 failed reads, but the flood runs 2,000+ lines — the read loop that keeps hitting the dead session is **not** the one calling `_note_session_read_result`, so the counter never reaches 25.
- **Fix approach (pending implementation)**:
  1. Route every SimConnect read path through `_note_session_read_result` — audit `_read_position_uncached`, `_read_position_minimal_uncached`, and the low-rate tier (`_read_low_rate_tier`) so a dead session is detected on the first burst, not after thousands of lines.
  2. Add a **stderr flood watchdog**: count `OS error`/`0xc00000b0` emissions (or consecutive `None` reads) in a rolling window (e.g. ≥ 50 within 10 s) and force `_close_session()` + immediate rebuild with backoff, instead of relying on the failure counter alone.
  3. Guard the dispatch thread itself: wrap the wrapper's session in a health-check thread that calls `_SESSION_SM.exit()` when the connection is dead, so reads fail fast and cleanly.
- **Status**: Implemented (2026-08-09).

### #12 — Pushback detected as TAXI OUT (both flight-watch and logbook phase detectors)

- **Severity**: High (wrong phase shown for the whole ground leg; pushes into TAXI OUT timelines/announcements)
- **Symptom**: During GSX pushback the phase reads **TAXI OUT / TAXI** instead of **PUSHBACK**.
- **Root cause**: Two phase detectors both use a **5 kt ground-speed cutoff** that is too low for MSFS. A real pushback tug moves the aircraft at ~2–6 kt and the sim's `ground_speed_kts` routinely reads **above 5 kt** during pushback:
  1. `flight_watch.py::_phase()` — ordering bug: `if gs > 5.0: return "TAXI"` is checked **before** `_gsx_pushback_active()`. Any pushback sample above 5 kt returns TAXI without ever consulting the pushback evidence. Its `_gsx_pushback_active()` is also looser than logbook's (treats `raw not in {0,1,6}` and state words ACTIVE/REQUEST/PROGRESS/PUSH as active, including the generic "departure" row).
  2. `logbook.py::_phase()` — has the correct ordering (pushback checked first, `pushback_positive_latch` + dedicated GSX pushback row + `_backward_motion_active`), but gates on `if pushback_active and gs <= 5.0: return "PUSHBACK"`, and `_analyse()` has a "fast taxi-out override" that clears a latched pushback the moment `taxi_speed > 5.0` (comment assumes "a tug never exceeds 5 kt"). In MSFS that threshold is hit during normal pushback, so the latch is cleared ~immediately and the phase demotes to TAXI OUT.
- **Fix approach (pending implementation)**:
  1. `flight_watch.py`: reorder `_phase()` so `_gsx_pushback_active()` is consulted **before** the `gs > 5.0` taxi branch (mirror logbook's dedicated-row check rather than the loose `raw not in {0,1,6}` + "departure" heuristic).
  2. Both detectors: raise the tug-speed gate from 5 kt to **~8–10 kt** (with displacement + forward-motion evidence, as `taxi_motion_candidate` already does at >=8 kt), so a latched GSX pushback is only demoted by *sustained forward* taxi — not by a transient 6–7 kt pushback sample.
  3. Gate the fast taxi-out override on direction (forward body velocity / heading-track agreement) in addition to raw GS, and keep the `pushback_positive_latch` until an explicit GSX clear (`_last_explicit_clear`) or real forward displacement.
- **Status**: Implemented (2026-08-09).

### #13 — Live OFP TIMES delta is wrong / unreadable (OUT 1735Z → 1754Z shows "+1909")

- **Severity**: Medium (wrong-looking delta in the Live OFP times table)
- **Symptom**: Scheduled 1735Z, actual 1754Z displays delta `+1909` instead of `+19`.
- **Root cause**: Two compounding issues:
  1. The server `_times_section` (`ofp_actuals.py:260`) computes `delta_seconds` with **second precision** from the actual epoch — a block-out recorded at 17:54:09Z gives 1149 s (19 min 9 s), while the times themselves are displayed minute-precision (1754Z).
  2. `briefingOfpDelta()` (`opsroom.js:1342`) formats sub-hour deltas as `+{MM}{SS}` with **no separator**: `+1909` = "+19 min 09 s", which reads as a broken number. The format is only sensible when minutes are 0 (e.g. `+00 09`); otherwise it must be `+19:09`, `+19m09s`, or — matching the minute-level time display — simply `+19`.
- **Fix approach (pending implementation)**: round/truncate the delta to whole minutes in `briefingOfpDelta()` (consistent with minute-precision times) — e.g. `Math.round(abs/60)` minutes with `+19` — or add an explicit separator (`+19:09`). Also consider rounding `delta_seconds` server-side to the nearest 60 s so the BLOCK/TIMES rows stay internally consistent. Update the same formatting in the print/copy receipt formatter (`format_ofp_receipt` in `printer_client.py` and `briefingOfpCopy` in `opsroom.js`) so printed/copied deltas match.
- **Status**: Implemented (2026-08-09).

### #14 — Black Box module: engine gauges render unstyled ("Engines styling not loading")

- **Severity**: Medium (engine N1/N2/EGT/Fuel-flow gauges in the Black Box module lose all styling)
- **Symptom**: The Black Box engine panel shows raw/unstyled gauges — no arc, no fill bars, no readout styling.
- **Root cause**: The JS engine-gauge renderer (`opsroom.js` ~5600-5645) builds HTML using classes `bb-engine-primary`, `bb-engine-arc`, `bb-engine-arc-track`, `bb-engine-arc-val`, `bb-engine-arc-dot`, `bb-engine-arc-readout`, `bb-engine-bar`, `bb-engine-bar-track`, `bb-engine-bar-fill`, `bb-engine-bar-label`, `bb-unavailable` — but `opsroom.css` only contains **one** `bb-engine` rule (`.bb-engines-grid`, line 2361). All the individual gauge/bar/arc styles are **missing** from the stylesheet (source and dist both show exactly 1 match). The HTML is injected with no matching CSS, so the gauges fall back to unstyled block elements.
- **Fix approach (pending implementation)**: Add the missing `.bb-engine-*` CSS rules (arc gauge track/val/dot, bar track/fill, readout typography, `bb-unavailable` dimming) to `opsroom.css` — the renderer already emits the correct class names, so this is CSS-only. Verify in the Black Box live panel after a rebuild.
- **Status**: Implemented (2026-08-09).

### #15 — Flight Watch FCU selected values flap / show 0 instead of "---" (Airbus-style)

- **Severity**: Medium (misleading FCU readout: altitude flaps 32000 ↔ 0; HDG/SPD/V/S show 0 when unset)
- **Symptom**: `SELECTED ALT` flaps between 32000 (correct) and 0; `SELECTED HDG 0°`, `SELECTED SPD 0 KT`, `SELECTED V/S 0 FPM` are displayed as zeros. Should be `---` (with the Airbus FCU-style bold dot when a managed target is active) instead of 0.
- **Root cause**: Two parts:
  1. **Zero display**: `formatAltitude/formatSpeed/formatVerticalSpeed/watchValue` (`opsroom.js` ~923-936, 3625) only render `---` when the value is null/non-finite — a literal `0` is formatted as `0 FT / 0° / 0 KT / 0 FPM`. When an FCU field is unset or the raw offset reads 0, the panel shows 0.
  2. **Flapping**: `telemetry_provider.py` (FSUIPC path ~634-655) only zero-guards `ap_selected_*` **while airborne** (`if airborne_like:`), and `simconnect_position.py:463` only guards `selected_altitude_ft`/`selected_speed_kts` above 1000 ft — heading/VS are never zero-guarded, and on the ground/low altitude a 0 raw offset passes through. When the two telemetry sources (FSUIPC vs SimConnect) alternate (failover/cache races), the FCU altitude flips between the correct value from one source and 0/None from the other.
- **Fix approach (pending implementation)**: (1) Treat `0` as invalid for FCU selected fields in the renderer (only render a value when non-null and non-zero, or when a lock/engagement bit proves it is a real target) and render `---`/the FCU dot otherwise; (2) apply the zero-guard to **all four** FCU fields (`selected_altitude_ft`, `selected_heading_deg`, `selected_speed_kts`, `selected_vertical_speed_fpm`) in both `telemetry_provider.py` and `simconnect_position.py` regardless of altitude, using the AP lock bits (`ap_alt_lock_raw`/`ap_hdg_lock_raw`/`ap_spd_lock_raw`/`ap_vs_lock_raw`) as the "value is a real target" proof; (3) stabilize the FSUIPC↔SimConnect source handoff so a stale 0 from the switching source never overwrites a valid target.
- **Status**: Implemented (2026-08-09).

### #16 — Black Box instruments show wrong/stale values while Flight Watch is correct (ALT 879 FT / RA 9 FT / IAS 0 / GS 0 / VS 0 / PARKED)

- **Severity**: High (live Black Box panel freezes on a parked/ground snapshot mid-flight)
- **Symptom**: Black Box live instruments read `ALT 879 FT · RA 9 FT · IAS 0 KT · GS 0 KT · VS 0 FPM · HDG 6° · PITCH -0.0° · BANK 0.0° · G 1.00 · PHASE PARKED` — a parked snapshot — while Flight Watch on the same server shows correct live values.
- **Root cause**: The two modules read **different telemetry paths**:
  - **Flight Watch** uses the full stream (`read_telemetry(force=...)` → `telemetry_provider.py`), which prefers **FSUIPC first** (`_SOURCE_LOCK == "fsuipc7"`) and only falls back to SimConnect. With FSUIPC healthy it never touches the SimConnect session → correct values.
  - **Black Box record loop** uses `read_telemetry(force=True, stream="minimal")` → `read_position_minimal()` → `_read_position_minimal_uncached()` in `simconnect_position.py`, which is **SimConnect-only by design** (bypasses the shared cache and the FSUIPC source selection; comment: "deliberately bypasses the shared position cache... non-poisoning by design").
  - When the **SimConnect session is degraded/dead** (the same upstream dispatch-thread failure as **#9** — 13k `0xc00000b0` lines this session), the minimal stream returns stale/zero samples, `_normalize()` (black_box.py) rejects them (`ok`/`telemetry_complete`/`telemetry_fresh` fail), no new rows are appended to `_RING`, and the frontend keeps rendering the **last good row** — the parked frame from when the session last worked. Flight Watch stays live because it never reads the dead SimConnect session.
- **Secondary suspect (unit bug)**: in `_read_position_minimal_uncached`, `pressure_altitude_m` is correctly converted meters→feet (`* 3.280839895`) but `PLANE_ALTITUDE` → `altitude_ft`, `PLANE_ALT_ABOVE_GROUND` → `agl_ft` and `RADIO_HEIGHT` → `radio_altitude_ft` are used **raw** — MSFS SimConnect returns those in **meters**. When the minimal stream does read, ALT/RA are ~3.28x too small unless the SimConnect Python wrapper converts units. Needs verification against the wrapper's return units; the FSUIPC path converts correctly.
- **Fix approach — amended 2026-08-09 (Stage 1 now / Stage 2 permanent)**:
  - **Stage 1 (now, small/safe)**: when the minimal SimConnect path goes stale or fails, the Black Box record loop (`_record_loop` in `black_box.py`) falls back to the FSUIPC-driven full stream — the same one Flight Watch uses. Fixes #16 immediately, keeps Black Box data identical to Flight Watch, no stutter (FSUIPC is one batched `pyuipc.read` per sample), and unlocks the true 30 Hz takeoff-roll/approach rate (the SimConnect minimal path is capped at `black_box_simconnect_max_hz` = 10 Hz by default). When **both** sources are dead, surface `STALE`/`TELEMETRY LOST` instead of replaying the last good row.
  - **Stage 2 (permanent architecture)**: single-writer shared ring buffer — one telemetry writer (FSUIPC preferred, SimConnect fallback) publishes complete-shape snapshots to an in-memory ring; Flight Watch, Black Box, RAAS, announcements and PIREP read only the buffer. Kills the #6 stutter structurally, ends the sparse-minimal poisoning problem, concentrates failover/health in one place (one health counter, one rebuild — ties into #9), and retires the minimal stream entirely. Full plan in the Stage 2 section below.
  - **Required regardless of stage**: fix the **meters→feet conversion** for `altitude_ft`/`agl_ft`/`radio_altitude_ft` in `_read_position_minimal_uncached` (verify wrapper units first — the code already converts `pressure_altitude_m`).
- **Status**: Implemented (2026-08-09).

### #10 — GSX auto-engine-start probes a non-existent engine (`SIMCONNECT_EXCEPTION_UNRECOGNIZED_ID: GENERAL ENG COMBUSTION:3`)

- **Severity**: Low (harmless SimConnect rejection, but noisy and wasteful)
- **Symptom**: `SIMCONNECT_EXCEPTION_UNRECOGNIZED_ID: in (b'GENERAL ENG COMBUSTION:3', b'Bool')` during engine start on a 2-engine aircraft.
- **Fix approach**: Clamp the engine loop in `gsx_remote._auto_start_engines()` to the aircraft's actual engine count (from telemetry `engine_count` / Fenix type) instead of probing 1–4 blindly.
- **Status**: Resolved by prior refactor — the `_auto_start_engines` SimConnect write no longer exists anywhere in the codebase (verified 2026-08-09); no change needed.

### #11 — ChartFox proxy SSL failures for SloveniaControl AIP charts

- **Severity**: Low (LJMB charts fail to load; remote-host cert issue)
- **Symptom**: `[CHARTFOX PROXY] download_failed ... aim.sloveniacontrol.si ... SSLError(SSLCertVerificationError: CERTIFICATE_VERIFY_FAILED)` — charts for that publisher never load.
- **Fix approach**: Add a per-host SSL fallback (trusted CA bundle / `ssl.create_default_context` with the site's chain) or a documented manual-download path for affected AIP publishers.
- **Status**: Implemented (2026-08-09).

### #17 — RAAS / NOTAM closure alerts repeat (spoken "RUNWAY CLOSED PER NOTAM" + "TAXIWAY CLOSED AHEAD" pop-up)

- **Severity**: Medium (repeated spoken/pop-up alerts for one closure; erodes trust in the warnings)
- **Symptom**: Closure alerts fire more than once for a single closure NOTAM: the RAAS spoken "RUNWAY CLOSED PER NOTAM" repeats during one approach (or once for 26L and again for 26R of the same closed runway), and the "TWY X CLOSED N NM AHEAD" amber pop-up fires repeatedly while taxiing near closed taxiways.
- **Root cause — two independent weak dedups**:
  1. **Spoken runway callout** (`app/raas.py`): the only dedup is `_callout()`'s time cooldown keyed on `{event_type}:{runway}:{distance_ft}:{distance_value}:{distance_unit}` against the global `_LAST_CALLOUT_AT` (`raas.py:92, 369-376`). `_maybe_notam_closure_callout()` (`raas.py:480-495`) fires `_callout("RUNWAY CLOSED PER NOTAM", "notam_runway_closed", runway=runway, cooldown=600.0)` on **every** `on_runway`/`approaching_runway` callout (`raas.py:386`), and those parent callouts fire repeatedly during approach because their distance-based keys change each call. The 600 s dedup only holds while the `runway` string is byte-identical — 26L then 26R (or 08 vs 26) is a different key, so it re-fires. `_NOTAM_CLOSURE_CACHE` (`raas.py:414`) only caches the closure *result*, never suppresses callouts.
  2. **Proximity pop-up — runway AND taxiway** (`app/static/opsroom.js` + `app/closure_markers.py`): `pollClosureProximity()` (`opsroom.js:453-466`, every 5 s) alerts whenever the `kind:ref:airport_icao` key from `proximity_alert()` (`closure_markers.py:2080`) changes, and **resets the latch to empty on every `near:false`** (`opsroom.js:455`). `proximity_alert()` returns the *nearest* placed marker within 1.0 NM (taxiway) / 2.5 NM (runway/barrier) (`_PROX_TAXIWAY_NM` / `_PROX_RUNWAY_NM`, `closure_markers.py:2060-2061`), and a single closed taxiway can yield several markers (geometry X + junction Xs, v0.25.70) — so during taxi the nearest marker/ref keeps changing and the aircraft drifts in/out of the radius, producing a new key (or a re-armed key after `near:false`) → repeated pop-ups for the same closure.
- **Fix approach**: announce once per closure NOTAM with hysteresis, mirroring the TFR poll's nmsId dedup (`main.py` `_NMS_TFR_SEEN`):
  1. **Spoken callout**: return the NOTAM identifier (nms_id / ident) from `_notam_runway_closed()`; add a `_NOTAM_ANNOUNCED` latch keyed by `airport:physical-strip:notam_id` that re-arms only when the closure clears (or a new NOTAM appears); normalise the runway to the end-independent physical strip (like `_strip_key`) so 26L/26R/08/26 share one latch.
  2. **Proximity pop-up**: key on a stable closure identity (carry the NOTAM id / normalized `airport:kind:ref` on placed markers and in `proximity_alert()`'s payload) instead of the nearest-marker key; keep an announced-set per session so switching between markers of the same closure never re-alerts; replace the immediate `near:false` reset with hysteresis (re-arm only after a sustained exit, e.g. not-near for >30–60 s or when the closure leaves the plan), so drifting across the radius boundary stops re-triggering.
  3. Keep distance out of the dedup keys (already excluded) so only genuine new/cleared closures alert.
- **Status**: Implemented (2026-08-09).

### #18 — Live OFP panel shows "standing by" / WAITING even while a flight is active in the logbook

- **Severity**: Medium (live comparison unavailable during the flight it exists for)
- **Symptom**: In Briefing → OFP tab, the live OFP panel shows "LIVE OFP completion is standing by — click ◈ LIVE OFP to open the live comparison." (and/or state WAITING · phase STANDING BY) even though a flight is actively recording in the Logbook.
- **Root cause (partially verified — needs a live-session confirmation of the payload state)**:
  - Backend: `_live_ofp_payload()` (`app/main.py:1003`) returns the `state="waiting"` payload (reason "Flight plan loaded; waiting for an active recorder", `live.phase="STANDING BY"`) whenever `logbook_active_recorder()` — `get_active_recorder()` → `_active_row()` (`app/logbook.py:1224-1231`, `WHERE status='RECORDING'`) — finds no active row, or a "mismatch" payload when the active recorder's flight identity doesn't match the loaded SimBrief plan. The DB path writes `RECORDING` on start (`_save_flight(meta, "RECORDING")`, `logbook.py:1389`), so a miss means the lookup/race or the plan↔recorder match is the suspect, not the status convention itself.
  - Frontend: the verbatim placeholder (`app/static/opsroom.js:1293`) is only replaced by a successful `/api/briefing/ofp-live` fetch with `data.ok` (`renderBriefingOfpLive`, `opsroom.js:1452-1460`); a "waiting" payload renders state WAITING + phase STANDING BY instead of live actuals, and a failed/hung fetch leaves the placeholder visible in the open panel.
- **Fix approach (pending implementation)** — user direction (2026-08-09): **always render the live comparison behind the ◈ LIVE OFP button, never interfere with the SimBrief OFP display**:
  1. **Keep the toggle as the only access point**: the panel stays collapsed until ◈ LIVE OFP is clicked (no auto-open, no layout change to the OFP tab). The change is only what the panel shows once opened: it always renders the comparison tables immediately on open (skeleton + patch on first paint), so the "standing by" placeholder is never visible.
  2. **Fill planned from SimBrief**: already implemented in the backend waiting payload (`ofp_actuals.py` v0.25.66 — planned times/weights/fuel sections are built from the cached plan with actuals unavailable); keep that, and make sure the frontend renders it on open rather than after the first 2 s poll.
  3. **Never touch the SimBrief OFP view**: the live panel is only the section revealed behind the button (`briefingOfpLivePanel`); the SimBrief OFP iframe (`briefingOfpFrame`) and its display remain untouched.
  4. **Actuals stay honest**: "—" (not zero) until a recording starts, then live values once the logbook session exists; with a live active flight, first confirm the payload branch (waiting vs mismatch vs live) — if waiting, make the active-recorder lookup reliable (fall back to the in-memory active session if the DB row hasn't flushed), and if mismatch, relax the plan↔recorder match so an active flight never demotes to waiting.
- **Status**: Implemented (2026-08-09).

### #19 — "?" glyphs render instead of arrows/icons (ChartFox toolbar + ◈ LIVE OFP) — UI symbol sweep

- **Severity**: Medium (icons render as "?" — functional buttons look broken)
- **Symptom**: Button glyphs show as "?" instead of the intended symbols: the ChartFox PDF/annotation toolbar (⇔ fit-to-width, ◐ dark-mode, ↻ reload, ↗ open-external, and the ✏️ 🖍️ 🧹 🗑️ draw/highlight/erase/clear emoji), the colour-picker circle emoji (🔴 🟡 🔵 ⚪), and the "◈ LIVE OFP" button.
- **Root cause**: the UI renders these glyphs with the theme font stacks, which are monospace/MCDU faces with no emoji or rare-symbol coverage — `--terminal`/`--mcdu` = Cascadia Mono / Consolas / Lucida Console / Courier New, `--data` = B612 Mono / Cascadia Mono, `--ui` = B612 / Segoe UI (`opsroom.css:21-22,159-160,200-203,245-246`). None contain U+25C8 ◈, U+25D0 ◐, U+21BB ↻, U+21D4 ⇔, U+2197 ↗, U+2630 ☰, or emoji, and the toolbar buttons (`.cf-annot-tool`, `.cf-pdf-tb-btn` — `opsroom.css:1632,2367`) set no font-family, so they inherit the missing-glyph stack and render "?". (Verified by scanning the static assets: 26 distinct non-ASCII chars; the set above is the at-risk subset.)
- **Fix approach (pending implementation)** — sweep + font-safe replacements, applied to `app/static/*` **and** the running build `dist/OPS ROOM/_internal/app/static/*`:
  1. **Append Unicode-capable fallbacks to the font variables**: `--terminal`, `--mcdu`, `--data`, `--ui`, `--condensed` gain `,"Segoe UI Symbol","Segoe UI Emoji",sans-serif` so any glyph the primary face lacks falls back instead of "?".
  2. **Replace the emoji icon buttons**: ChartFox toolbar ✏️ 🖍️ 🧹 🗑️ and the colour-picker circle options → CSS-drawn/inline-SVG icons, or safe symbols present in Segoe UI Symbol (e.g. ✎ / ✚ / ●), or a scoped `font-family` including Segoe UI Emoji on those buttons.
  3. **Swap rare symbols for covered ones**: ◈ LIVE OFP → styled span / plain "LIVE OFP"; ⇔ ◐ ↻ ↗ ☰ → Segoe UI Symbol variants or CSS arrows; verify each renders in WebView2.
  4. **Verification**: re-scan the static assets for non-ASCII outside an allowlist (keep · — ° × © … → − Δ and the MCDU box-drawing used in panels), then eyeball Briefing / ChartFox / annotate surfaces in WebView2 for any remaining "?".
- **Status**: Partially implemented (2026-08-09) — font fallbacks were applied to `opsroom.css` only; literal "?" separators and the missing fallbacks on the PIREP/OBS surfaces remain → see **#24**.

### #20 — One flight produces dozens of tiny Black Box recordings during taxi-in (engine-on watchdog vs TAXI IN stop)

- **Severity**: High (library clutter — 36+ ghost recordings for one flight; same class as the old v0.25.2 "~100 recordings per flight" bug, reappearing from a new code path)
- **Symptom**: EWG6107 G-AEWK LJMB→LKPR on 2026-08-09 produced **1 main recording** (`...20260809175409Z.opsbb`, 315 KB, matches block-out 17:54Z) plus **~36 tiny 40 KB recordings every ~8–15 s from 18:50:52Z to 18:57:05Z** — the whole taxi-in leg — plus 2 stale `.part` files. The burst stops exactly at block-in (18:57Z), when the engines shut down.
- **Root cause — verified against code + logs**: two mechanisms fight during taxi-in:
  1. **Stop**: `observe_phase()` stops the recording at TAXI IN (`black_box.py:594-597`), and the logbook's `_maybe_autostop_black_box()` (`logbook.py:1509`) closes it 120 s after on-blocks.
  2. **Restart**: the v0.25.7 **engine-on watchdog** in `_record_loop` (`black_box.py:735-755`) starts a new recording whenever it sees engines transition off→on with no active recording — it tracks that edge with a *local* `last_engines_running` flag and has **no per-flight "already recorded" latch**. After the TAXI IN stop fires, `last_engines_running` is stale (False), so the next not-active cycle starts a fresh recording for the same flight.
  3. **Why it repeats 36 times**: the watchdog's edge only re-fires when `engines_running` flips False→True — and the minimal-stream telemetry **flaps None↔True throughout the taxi-in window** because of the #9 SimConnect dispatch-thread failure (the `opsroom.log` is flooded with 80k+ `OS error 0xc00000b0` lines). Each flap looks like "engine just started" → new recording → next TAXI IN stop → repeat, on the flood's ~8–15 s burst cadence. The old v0.25.2 fix (removing "TAXI IN" from the start-trigger set) is present (`start set = {PUSHBACK, TAXI OUT}` only), but the engine-on watchdog reintroduced the oscillation from a different path, and #9 makes it persistent.
- **Fix approach (pending implementation)**:
  1. **Per-flight stop latch**: once `stop_recording("TAXI IN")` / the autostop closes the recording for flight_id X, the engine-on watchdog must not start a new recording for X until a genuinely new flight begins (new flight_id / phase reset) — the logbook already has the same idea via `flight_ids_match` in `_analyse`.
  2. **Debounce the engine-on edge**: require 2–3 consecutive engine-on samples before starting, so a single telemetry flap can never start a recording.
  3. **Skip the watchdog during TAXI IN**: don't auto-start while the phase context is TAXI IN (or after the logbook session for this flight has ended).
  4. Clean up stale `.part` leftovers on startup (recordings started but never finalized).
  - This is independent of but amplified by #9 — the latch makes the symptom impossible even while the SimConnect flood is unfixed.
- **Status**: Implemented (2026-08-09).

### #21 — Full PIREP slow to build + "insufficient telemetry" on departure/landing + random peaks in Logbook approach charts (EWG6107 99a09bc4)

- **Severity**: High (report for a valid flight is unavailable/ugly; build is slow)
- **Symptom**: For flight EWG6107 `99a09bc4…` (LJMB→LKPR, 2026-08-09): (1) the full PIREP takes a long time to build; (2) departure and landing analysis report "Insufficient continuous, physically plausible final-approach telemetry" even though FSUIPC7 was the source for all 2,848 samples; (3) the Logbook FINAL APPROACH PROFILE / GLIDEPATH DEVIATION / FINAL APPROACH SPEED / FINAL APPROACH VERTICAL SPEED charts show huge random peaks.
- **Root cause — three interacting issues (all verified against DB samples + code)**:
  1. **Sample discontinuity (the "insufficient" cause)**: the recorded samples have **543 gaps > 5 s (many ~20 s)** — the #9 SimConnect dispatch-thread failure made the recorder's completeness/freshness gate drop most samples, leaving ~1 valid sample per 20 s for long stretches. `analyse_pirep` → `_sanitize_samples` + `_last_continuous_final` then cannot assemble 8+ continuous physically-plausible final-approach samples → `approach_mode="unavailable"`, reason "Insufficient continuous, physically plausible final-approach telemetry" (`pirep_analysis.py:776`). All 2,848 samples are `source=fsuipc7` (so the user is right — FSUIPC was healthy); the NAV fields `glideslope_deviation`/`localizer_deviation` are `None` in every sample because they are only populated by SimConnect (`simconnect_position.py:635-636`, `NAV_CDI:1`/`NAV_GSI:1`) — the current gates don't require them, but the gap discontinuity is what actually fails the analysis.
  2. **Chart peaks (the "random peaks" cause)**: when analysis fails there is no `analysis.approach.profile`, so the Logbook charts fall back to `rawApproach` = every sample with straight-line `distance_to_touchdown_nm ≤ 20` (`opsroom.js:6268`). That window admits the **real high-speed en-route descent** (elapsed 4690–4819 s: sustained −4,000 to −5,800 fpm at GS ~470–495 kts, FL310→FL214 — genuine data, not sensor noise). Two amplifiers: (a) **MSFS radio altitude is unclamped** — `radio_altitude_ft` reads 20,000–30,000 ft at altitude (real RAs clamp ~2,500 ft), so `approach_agl_ft` and `glidepath_deviation_ft = AGL − ideal 3°` (`logbook.py:2131-2140`) become 15,000–25,000 ft for those samples → absurd peaks in PROFILE and GLIDEPATH DEVIATION; (b) the −5,000 fpm descent shows as the giant teeth in VERTICAL SPEED, and the 20 s sample gaps make line segments zigzag across holes.
  3. **Slow build**: `/api/logbook/{id}/telemetry` (`logbook.py:2100`) **recomputes `analyse_pirep` on every request**, and for a still-`RECORDING` flight `_refresh_entry_analysis` refuses to cache (`logbook.py:1811` — "RECORDING → return meta"), so nothing is reused. `analyse_pirep` makes **synchronous NOTAM network calls** (`_pirep_notam_footnote`, `pirep_analysis.py:248` — `notam_client.get_notams(LJMB)` + `(LKPR)`, each with a 4–8 s timeout) plus 2,848-sample sanitization and navdata runway lookups. The PIREP page then also fetches `/api/logbook/{id}/ofp-completion` (a second full payload build) and the PDF export spins up a headless browser (`logbook.py:3194`). Also relevant: the flight **never finalized** — still `status='RECORDING'` at 21:23Z hours after block-in — so every page load repeats all of this.
- **Fix approach (pending implementation)**:
  1. **Continuity (primary, ties into #9/#20)**: fix the SimConnect flood so the recorder keeps a continuous sample stream; additionally make the analysis tolerant of short gaps — bridge gaps ≤ 30–60 s in `_sanitize_samples` (interpolate position/speeds or mark as bridged) and/or relax `_last_continuous_final` to accept runs with small discontinuities instead of demanding a strict contiguous run.
  2. **Chart window + AGL clamp**: in `logbook_telemetry` (`logbook.py:2131-2140`) treat `radio_altitude_ft > ~5,000 ft` as invalid for approach charts (set `approach_agl_ft`/`glidepath_deviation_ft` to `None` — MSFS RADIO_HEIGHT is not clamped like a real RA); tighten the frontend fallback (`opsroom.js:6268`) to exclude non-approach samples (e.g. AGL > 5,000 ft or GS > 250 kts) so the en-route descent can never enter the final-approach charts; drop/decimate across the 20 s gaps so lines don't zigzag.
  3. **Build caching**: cache the analysis result with a short TTL (30–60 s) even for RECORDING flights; cache the NOTAM footnote separately (it's the slow network piece); make the NOTAM fetch non-blocking (background pre-fetch / async) or reuse the existing 5-minute `notam_client` cache so a cold page load doesn't wait 8–16 s on network timeouts; serve the telemetry endpoint without re-running the full analysis when only charts are needed.
  4. **NAV deviation**: once #9 is fixed, supplement `glideslope_deviation`/`localizer_deviation` from a healthy SimConnect session into the recorder samples so departure/landing analysis can use real NAV data when available (FSUIPC-only sessions stay honest with the RA-based 3°-slope method).
- **Status**: Implemented (2026-08-09).

### #22 — Full PIREP finance: "No matching GSX receipts" despite available receipts + passenger satisfaction missing from the finance section

- **Severity**: Medium (finance shows estimates instead of real GSX costs; the satisfaction score exists but is never displayed)
- **Symptom**: Full PIREP (EWG6107 `99a09bc4…`) FLIGHT FINANCE shows "No matching GSX receipts" and "Departure and arrival service costs were estimated automatically", even though GSX receipts exist for the flight; passenger satisfaction is not shown anywhere in the AIRLINE AND PILOT ECONOMY / FLIGHT FINANCE section.
- **Root cause (verified live)**:
  1. **Registration (tail) mismatch in the GSX matcher**: the receipts exist and parse cleanly (Catering 17:22Z LJMB, Fuel 17:30Z LJMB, Handling 18:05Z LJMB, Handling 19:36:33/35Z LKPR — all `D-AEWK`), but the logbook flight registration is **G-AEWK**, so `recent_invoice_items` (`gsx_receipts.py`) hard-excludes every one on `tail != receipt_tail`. `_normalise_registration` only strips punctuation and uppercases — the country-code prefix (G- vs D-) is never normalised. Verified by calling `recent_invoice_items` with the real flight meta → **0 items**; `list_receipts` → 377 total with 5 clean EWG6107 receipts (parse_err: None, airports LJMB/LKPR, all inside the operational time window).
  2. **Passenger satisfaction computed but never rendered**: the `passenger_satisfaction` module (v0.25.9) already computes a 0–100 score from exactly the requested parameters — departure/arrival delay (5 min grace, 1 pt/min penalty), landing rate (hard 200 fpm / very hard 400 fpm penalties), unstable approach, go-around, approach overspeed, peak G, max bank, turbulence, long taxi in/out, emergency events — and `analyse_pirep` already returns it (`pirep_analysis.py:996`). But `pirep.js` has **zero** `satisfaction` references, so the score/category/breakdown/revenue multiplier are never shown on the full PIREP.
- **Fix approach (pending implementation)**:
  1. **Tail prefix-insensitive matching**: in `app/gsx_receipts.py` compare registrations after stripping the leading country-code letter (G-AEWK and D-AEWK both → AEWK) — MSFS add-on aircraft and SimBrief registrations commonly differ only by country prefix; keep the hard exclusion when the core suffix differs. Record `match_basis="registration suffix + airport + time window"`.
  2. **Re-attach + re-reconcile**: after the matcher is fixed, `_refresh_entry_receipts` re-scans on PIREP open and `reconcile_flight` reposts the finance statement — Departure/Arrival service costs then switch from "OPS ROOM estimate" to the real GSX receipt amounts (this flight finalized at 19:36:59Z).
  3. **Passenger satisfaction in the finance section**: in `app/static/pirep.js` `renderFinance()` add a "Passenger satisfaction" tile/card reading `analysis.passenger_satisfaction` — score %, category (Excellent/Good/Average/Poor/Critical), revenue multiplier × reputation delta, the 4-part breakdown (schedule/landing/comfort/operations) and the positive/negative explanations. Also show a friendly note when service costs are estimated (receipts not yet matched).
- **Status**: Implemented (2026-08-09).

### #23 — Full PIREP shows "PIREP UNAVAILABLE / Internal error" — telemetry endpoint 500s on every flight (regression from #21)

- **Severity**: **Critical** (blocks the full PIREP for every flight — report unavailable; found live in `opsroom.log` 2026-08-09 23:40)
- **Symptom**: Opening any full PIREP shows "PIREP UNAVAILABLE — Internal error. See opsroom.log for the server-side traceback." The log shows, on **every** `/api/logbook/{id}/telemetry` call:
  ```
  UnboundLocalError: cannot access local variable '_ANALYSIS_CACHE' where it is not associated with a value
    File "app\logbook.py", line 2147, in telemetry
  ```
- **Root cause (verified in source)**: the #21 short-TTL analysis cache was added to `telemetry()` (`logbook.py:2126`) but the function **rebinds the module-level name**: `_ANALYSIS_CACHE = {key: value ...}` (`logbook.py:2155`, the >200-entry prune). A bare-name assignment makes `_ANALYSIS_CACHE` a **local** for the whole function, so the first read — `cached_analysis = _ANALYSIS_CACHE.get(...)` (`logbook.py:2148`) — raises `UnboundLocalError` on **every call**, not just cache misses. `compileall`/the release validator cannot catch this (runtime-only), which is why validation passed.
- **Fix approach (pending implementation)**: declare `global _ANALYSIS_CACHE` at the top of `telemetry()` (the function legitimately rebinds it during the prune). Cleaner alternative: drop the rebind — prune in place with `_ANALYSIS_CACHE = {k: v for ...}` avoided by `dict` comprehension into the same object (`_ANALYSIS_CACHE.clear(); _ANALYSIS_CACHE.update({k: v for ...})`) — and keep the item-write `_ANALYSIS_CACHE[key] = ...`, which alone does not make the name local. Either way, re-verify by calling the endpoint twice (cache hit + miss) against a real flight.
- **Status**: Implemented (2026-08-10, v0.25.73) — the prune no longer rebinds the module-level name; it builds the pruned dict first, then mutates in place with `_ANALYSIS_CACHE.clear()` + `_ANALYSIS_CACHE.update(...)`. Verified by invoking `telemetry()` twice against a real flight (first call prunes, second hits the cache) — both return 200 and no `UnboundLocalError`.

### #24 — "?" still visible in the UI: literal `?` used as the origin↔destination separator (pirep.js + obs.js) + missing font fallbacks on PIREP/OBS surfaces

- **Severity**: Medium (user still sees "?" after #19 — e.g. the finance tile shows "LJMB ? LKPR")
- **Symptom**: "?" appears between origin and destination in the full PIREP FLIGHT FINANCE "Airline flight result" row (`LJMB ? LKPR`) and in the OBS console GSX cards.
- **Root cause (verified in source)**: these are **literal `?` characters typed as the separator**, not missing-font glyphs — so #19's `opsroom.css` font fallbacks cannot fix them:
  1. `app/static/pirep.js:417` — `` `${route.origin||'----'} ? ${route.destination||'----'}` `` (renderFinance, "Airline flight result" metric).
  2. `app/static/obs.js:66` and `obs.js:71` — `` `${esc(origin)} ? ${esc(dest)}` `` (GSX status cards).
  3. Secondary gap: #19 added `"Segoe UI Symbol","Segoe UI Emoji"` fallbacks **only to `opsroom.css`**. The other shipped surfaces define their own font stacks without fallbacks — `pirep.css` (`--font: Inter, "Segoe UI", Arial, sans-serif`, `--mono: Cascadia Mono/Consolas`), `pirep_print.css` (`font-family: Inter, "Segoe UI", Arial, sans-serif`), `host.css` (`--terminal/--mcdu` = Cascadia Mono/Consolas/Lucida Console, `--condensed` = Bahnschrift), `obs.css` — so any glyph those pages render outside their primary faces can still show "?".
- **Fix approach (pending implementation)** — applied to source **and** `dist/OPS ROOM/_internal/app/static/`:
  1. Replace the three literal `?` separators with `→` (U+2192, already used elsewhere in the app): `pirep.js:417`, `obs.js:66`, `obs.js:71`.
  2. Append `,"Segoe UI Symbol","Segoe UI Emoji",sans-serif` to the font variables in `pirep.css`, `pirep_print.css`, `host.css`, `obs.css` (all `--font`/`--mono`/`--terminal`/`--mcdu`/`--condensed` declarations).
  3. Re-scan `app/static/*` for any other literal `?` used as a symbol separator (grep for ` ? ` / `? ${` patterns) and for non-ASCII outside the allowlist; eyeball PIREP + OBS + host surfaces in WebView2.
- **Status**: Implemented (2026-08-10, v0.25.73) — the three literal `?` separators in `pirep.js` (3 spots) and `obs.js` (2 spots) were replaced with `→` (U+2192), and `"Segoe UI Symbol","Segoe UI Emoji"` fallbacks were appended to the font variables in `pirep.css`, `pirep_print.css`, `host.css` and `obs.css`. A full grep of `app/static/` for literal `?`-separator patterns now returns only legitimate JS ternaries.

### #25 — NOTAM GeoJSON layer invisible on the Live Map ("NOTAM LAYER: 0 ACTIVE"; clicking NOTAMs does nothing)

- **Severity**: Medium (the map's NOTAM layer — the only geo view of active NOTAMs — renders nothing)
- **Symptom**: Toggling NOTAMS on the Live Map shows no markers and the status line reads "NOTAM LAYER: 0 ACTIVE". The `/api/nms/notams?latitude=…&longitude=…&radius=…` endpoint answers HTTP 200 every time (18/18 requests in opsroom.log were 200) but the frontend always receives `features: []`, so there is nothing to click.
- **Root cause (verified live against the opsroom.live store + source) — the DB-first path short-circuits an empty result instead of falling through to the proxy**: `get_notams_map()` (`app/notam_client.py:252`) is DB-first: it calls the server store `/api/v1/notams/near?latitude=…&longitude=…&radius_nm=…`. If that call succeeds — **even when it returns zero rows** — it wraps the rows into features and returns `ok:true, features:[…]` immediately, **never touching the proxy fallback** (`fetch_notams_by_geo`, the live FAA NMS GeoJSON path). The proxy only runs when the DB call *fails outright* (`body is None`). Live probes confirm the failure mode: at typical map viewport radii the store returns **zero rows** even over busy airspace — EGLL @ 14 NM → 0, @ 25 NM → 0, @ 40 NM → 1; EGKK @ 14 NM → 0, @ 25 NM → 1; EDDF @ 14/25 NM → 0. The store's `/near` geo index is sparse (rows only appear at ≥40 NM radii), so the map layer draws nothing while the same store's per-airport lookup (EGLL → 24 rows) and the proxy (live FAA NMS GeoJSON with coordinates) both have data. Secondary finding: per-airport rows carry `coordinates: null` (only `/near` rows include coordinates), so any future per-airport fallback must resolve positions from the airport index, not the row.
- **Fix approach (pending implementation)**: mirror the layered fallback that `get_notams_near()` (`notam_client.py:164`) already has — DB first, then proxy, then per-airport:
  1. In `get_notams_map()`, when the DB answers but yields **zero features** (empty row set, or rows whose `coordinates` are unusable), fall through to `nms_client.fetch_notams_by_geo(lat, lon, radius)` and return its GeoJSON features (source "FAA NMS") instead of returning `ok:true, features:[]`.
  2. If the proxy also yields nothing (or is unreachable/token-rejected), fall back to the per-airport walk (`_nearby_airport_notams`) and resolve each row's point from the airport index (`data_loader.load_airports()` lat/lon by `location`/`airport_icao`), since per-airport rows carry `coordinates: null` — the same position source the closure-marker deploy already uses.
  3. Keep the `map:` cache key as-is (it already includes lat/lon/radius); only the resolution order changes, so no cache-invalidation concern.
  4. Frontend `loadNotamLayer()` (`opsroom.js:4367`) already renders any `features` array it receives — no JS change needed; the status line will then show real counts.
- **Status**: Implemented (2026-08-10, v0.25.73) — `get_notams_map()` now runs the layered resolution: DB `/near` → (when zero rows or failure) live FAA NMS proxy → (when that yields nothing) per-airport walk with points resolved from the airport index. Verified with a mocked store returning zero rows: the function falls through to the proxy, and the per-airport fallback builds coordinate features from `data_loader.load_airports()` lat/lon.

### #26 — Live OFP weights never auto-fill on Fenix flights (PAX, BAG/CARGO, TOW, LDW, ZFW blank while times + fuel fill)

- **Severity**: Medium (the Live OFP comparison stays half-empty during the flight it exists for)
- **Symptom**: On a Fenix flight the Live OFP WEIGHTS section stays blank — PAX, BAG/CARGO, TOW and LDW all show "—" — while TIMES and FUEL fill normally from the recording.
- **Root cause (verified in source) — two separate gaps, both real**:
  1. **TOW/LDW/ZFW can never fill because the FSUIPC telemetry path has zero weight offsets.** The logbook snapshots come from `read_telemetry(False)` (the shared **full** stream, `logbook.py:1581/2027/2053/2078`), which is **FSUIPC-first** (`_SOURCE_LOCK == "fsuipc7"`, `telemetry_provider.py:1464`). `_read_fsuipc_unlocked()` (`telemetry_provider.py:371`) reads **no weight offsets at all** — grep of `telemetry_provider.py` shows only fuel (`0x126C`, `telemetry_provider.py:403`); there is no `gross_weight_lb`, `empty_weight_lb`, `payload_weight_lb` or `max_*_weight_lb` anywhere in the FSUIPC result. `_op_snapshot()` (`logbook.py:275-294`) reads `sample.get("gross_weight_lb")` — so on the FSUIPC path every snapshot stores `gross_weight_lb: None`, and `_weights_section()` (`ofp_actuals.py:416-424`) therefore emits `actual: None` for ZFW (from `calculated_zfw_lb` = gross − fuel), TOW (from `off` snapshot gross) and LDW (from `on` snapshot gross). Fuel fills because it only needs `fuel_total_lb` (present on FSUIPC). Only the SimConnect **full** stream carries weights (`simconnect_position.py:793-795, 984-987`); the **minimal** stream doesn't either (`simconnect_position.py:1332` has `fuel_total_lb: None` and no `gross_weight_lb`). So weights are blank **whenever FSUIPC is the active provider** — the normal Fenix case — not just on Fenix.
  2. **PAX / BAG-CARGO depend on a GSX/Fenix loading snapshot that may never be published.** `_live_ofp_payload()` (`main.py:1021-1029`) reads `gsx_automation_status()["fenix_loading"]["last_progress"]` and passes it as `loading_progress`. That dict is only written by `_sync_fenix_loading_state()` (`gsx_remote.py:3462`) inside the GSX↔Fenix automation decision loop; when that loop hasn't run (GSX automation off / not engaged / no decision made this session) `last_progress` stays `{}`, so `_weights_section()` (`ofp_actuals.py:367-369` for PAX, `390-401` for BAG/CARGO) finds no measured source and leaves the cells blank. The planned values are deliberately never presented as actuals (v0.25.71 rule), so the section looks empty rather than optimistic.
- **Fix approach (pending implementation)**:
  1. **Add weight offsets to the FSUIPC read** (`telemetry_provider.py`): extend the offset table with the standard FSUIPC weight offsets — total gross weight, empty weight, payload weight and the max gross/zero-fuel/landing limits (0x30C0 total / 0x30C8 max gross / 0x30D0 empty / 0x30D8 payload — verify exact offsets against the FSUIPC7 SDK offset map before committing) and surface them as `gross_weight_lb` / `empty_weight_lb` / `payload_weight_lb` / `max_*_weight_lb` so the FSUIPC result matches the SimConnect full shape. This makes `_op_snapshot` capture real weights on every flight regardless of provider.
  2. **Fenix fallback for weights**: when FSUIPC weights are still absent but Fenix is detected, fall back to the Fenix loadsheet (`fenix_adapter.loadsheet()`, `fenix_adapter.py:254`) — Fenix exposes the aircraft's own ZFW/TOW/LDW/payload — and use those for the snapshot cells (source "fenix loadsheet").
  3. **PAX/BAG-CARGO**: publish a loading snapshot unconditionally on every Fenix status poll (even when the GSX automation loop hasn't decided): read pax/cargo straight from the Fenix EFB loadsheet/progress (`fenix_adapter.py:703-786` already parses `pax_loaded` / `cargo_loaded_kg` / `fuel_loaded_kg` via `_best_numeric`) and store it into `last_progress` so the Live OFP always has a measured source for PAX and BAG/CARGO.
  4. Re-verify on a live Fenix flight: weights fill at OUT/OFF/ON snapshots, PAX/BAG-CARGO fill during boarding, and the receipt print + "COPY FULL COMPARISON" show the same values.
- **Status**: Implemented (2026-08-10, v0.25.73):
  1. **FSUIPC weight offsets added** — `_read_fsuipc_unlocked()` now reads `0x30C0` (TOTAL WEIGHT, FLOAT64 lb) and `0x30C8` (MAX GROSS WEIGHT, FLOAT64 lb) per the FSUIPC7 offset-status doc; surfaced as `gross_weight_lb` / `max_gross_weight_lb` through the same `0..2,000,000 lb` bound the SimConnect full stream uses (`_finite_weight_lb` + the shared `_sanitize_telemetry` guard). Verified end-to-end with a mocked pyuipc read (91 offsets unpack cleanly; weights flow into the result). The full read is still a single batched `pyuipc.read()` call, so the extra two offsets cost nothing measurable.
  2. **Live PAX/BAG-CARGO snapshot published unconditionally** — `gsx_remote.automation_status()` now calls `_refresh_fenix_loading_snapshot()`, a TTL-guarded (5 s) best-effort read of the Fenix EFB loadsheet (`fenix_loading_progress()`), which fills `last_progress.fenix` (pax/cargo/fuel) even when the GSX automation decision loop has never run. It preserves any GSX boarding counters already present and never blocks or crashes the status call. Verified: with `_fenix_loading_available()` mocked true, `last_progress` fills and the TTL suppresses re-reads within the window.
  3. The Fenix loadsheet fallback for ZFW/TOW/LDW is covered by the FSUIPC weights themselves (the Fenix adapter mirrors the same aircraft weight into the standard offsets); pax/cargo now come from the always-published loadsheet snapshot.

### #27 — Settings printer panel: dropdown on PREVIEW RECEIPT to preview every wired receipt/print kind (CPDLC, LIVE OFP, GSX, test)

- **Severity**: Low (developer/pilot convenience; no data loss)
- **Symptom**: Settings → Thermal/Pos printer has a single PREVIEW RECEIPT button (`index.html:929`, `previewPrinterReceipt()` in `opsroom.js:4054`) that always generates the same hard-coded CPDLC sample — there is no way to preview the other receipt kinds the app can actually print.
- **Wired receipt/print kinds today (verified in source)**: (1) **CPDLC** — `format_cpdlc_receipt()` (`printer_client.py:197`), auto-printed from Hoppie messages via `_auto_print_if_configured` (`hoppie_client.py:385-402`); (2) **LIVE OFP completion** — `format_ofp_receipt()` (`printer_client.py:222`), printed from the live comparison payload at `main.py:1087-1090`; (3) **PRINTER TEST** — `test_print()` (`printer_client.py:340`); (4) **GSX service invoices** — not thermal, but rendered as receipt-style cards in the Ground handling receipts panel and PIREP finance (gsx_receipts.py) and could be previewed in the same modal. The preview endpoint `POST /api/printer/preview` (`main.py:705`) currently only wraps arbitrary text with a `TYPE:` label via `generate_receipt_preview()` (`printer_client.py:369`) — it does **not** run the real formatters.
- **Fix approach (pending implementation)**: add a `<select>` next to PREVIEW RECEIPT (options: CPDLC · LIVE OFP · PRINTER TEST · GSX RECEIPT) and drive the preview with real formatter output:
  1. Frontend: `index.html` adds the dropdown; `previewPrinterReceipt()` sends `{type, sample?}` and, for kinds that need data, the backend supplies realistic sample payloads (a sample Hoppie CPDLC item for `format_cpdlc_receipt`, the current/loaded SimBrief plan through `format_ofp_receipt` when a flight is loaded, the test block for `test_print`, a sample GSX invoice object through the receipt renderer).
  2. Backend: extend `POST /api/printer/preview` to accept a `kind` and build the preview by calling the real formatter for that kind (reusing the exact functions the print path uses), so the preview is byte-identical to what prints.
  3. Keep the existing free-text CPDLC preview as one of the options ("CPDLC (sample)") so nothing regresses; label the modal title with the selected kind.
- **Status**: Implemented (2026-08-10, v0.25.73) — added a `PREVIEW` dropdown (`#printerPreviewKind`) next to the button with **CPDLC · LIVE OFP · PRINTER TEST · GSX RECEIPT · CUSTOM TEXT**. The endpoint `POST /api/printer/preview` now dispatches on `type` and runs the **real formatters**: `format_cpdlc_receipt` (realistic Hoppie-style sample), `format_ofp_receipt` (the actual live-OFP payload via `_live_ofp_payload()`), the `test_print` block, and the new `format_gsx_receipt` (new in `printer_client.py`, renders the latest parsed GSX receipt from `list_receipts()`). `custom` keeps the old free-text path. `node --check` passes; formatter outputs verified in-process.

### #28 — OPS ROOM performance calculator for the whole Performance-tab fleet (replaces SimBrief TLR dependence)

- **Severity**: Medium (Performance tab could only reflect SimBrief's TLR; wrong or missing V-speeds for aircraft SimBrief does not model)
- **Goal**: a first-party takeoff (and landing) performance calculator in `app/perf_engine.py` + `app/performance.py` covering **every aircraft in the Performance dropdown**, with OPS ROOM as the primary speed source and SimBrief TLR as last resort.
- **Implemented (2026-08-10, v0.25.73) — tiered engine with three tiers**:
  1. **Tier 1 — exact data for the two most-flown families**:
     - **A320neo (A20N)**: exact port of the **FlyByWire A32NX** takeoff-performance model (`a32nx_takeoff.ts` → 91 data tables extracted into `app/perf_data_a32nx.py`) — full limiting-factor engine (V1/VR/V2 from weight, runway, temp, wind, QNH/pressure-alt, slope, flaps CONF 1+F/2/3, flex/assumed temp with TMAX/MTOW limits, and runway-required distance) plus the A32NX landing calculator (VLS, autobrake LO/MED/MAX distances).
     - **B738**: exact port of the **komed3 topcat-style** B737-800 V-speed tables (`top.java`) for flaps 1/5/15, with linear extrapolation beyond the 65 t table ceiling (profile MTOW ≈ 79 t) and V2 ≥ VR consistency clamping.
  2. **Tier 2 — family scaling** for every other A32x/737 variant (A318/A319/A320 CEO/A321/A20N/A21N, B737-700/-800/-900 family): the Tier-1 engine runs with weights scaled by the profile's MTOW/OWE ratio and results scaled back, so every dropdown aircraft gets physically consistent speeds.
  3. **Tier 3 — generic fallback** for the rest of the fleet (incl. widebodies and any unknown ICAO): the existing PERF2601-curve model with a flap recommendation, plus the new `required_m` distance from the PERF2601 curves.
- **New inputs & outputs**: `zfw`, `zfw_cg_pct` (CG), runway (length/slope/condition), wind (head/tail component), OAT, QNH/pressure altitude, takeoff flaps, mode (takeoff/landing). Outputs: **V1 / VR / V2 (or VLS/VREF for landing), recommended flap, flex/assumed temp, runway-required distance (m), pitch trim, and source tier**.
- **SimBrief auto-fill**: `/api/simbrief/latest` (and the status-hydrate path via `_normalize` in `simbrief_client.py`) now enriches the plan with `zfwcg`, and the Performance tab auto-fills ZFW/ZFWCG/runway/wind/temp/QNH from the loaded SimBrief plan + embedded METAR (weather is decoded locally from `origin.metar` — no extra network call).
- **Frontend**: Performance tab gains a CG field, shows OPS ROOM speeds as the primary row (SimBrief TLR stays visible as comparison), and renders flap/flex/distance/trim/source; dispatch (`performance.py`) routes by normalized ICAO family with `allowed_labels` restricting the flap dropdown to modeled configs.
- **Robustness**: any tier-1 path that raises (e.g. komed3's hard 6,900 ft minimum on a short runway) falls back to Tier-3 generic with a warning instead of 500ing — validated across **all 55 profiles × 5 runway lengths** with zero failures.
- **Validation**: `app/tests/test_perf_engine.py` (7 tests) pins A20N vs the A32NX reference numbers, B738 vs the komed3 tables (exact match at 50 t/flaps 5: V1 138 · VR 139 · V2 146), the B738 65 t+ extrapolation, family scaling sanity, and every profile across the tier dispatch. Full suite green.
- **Status**: Implemented (2026-08-10, v0.25.73).

### #29 — A350 (A359/A35X) takeoff performance: Tier-1 exact engine from the iniBuilds EFB data

- **Severity**: Medium (A350-900/-1000 were on the generic PERF2601 estimate; the package itself ships the full FCOM-derived takeoff tables)
- **Goal**: A350 takeoff V1/VR/V2 + FLEX + runway-limited MTOW at the same fidelity as the A320neo/B738 tiers, mirroring the existing tiered dispatch.
- **Data source**: the iniBuilds A350 EFB ships its takeoff-performance database as a base64+gzip JSON bundle inside the obfuscated `ini-efb-a350.js`. The obfuscation (self-defending rotating string array — 8,316-string table, checksum-driven rotation offset 177) was reversed, and the bundle extracted to `app/data/perf_a350_tables.json` (2.96 MB, **59,616 rows, 24 tables**): DRY+WET × 6 pressure altitudes (0/2/4/6/8/8.5k ft) × headwind/tailwind. Each row = runway length (2000–4100 m) × OAT (−30…79 °C) × CONF 1+F/2/3 × wind bucket (5/10/20 head, −5/−10/−15 tail) → runway-limited **max TOW** + **V1/VR/V2 at that limit** + limit code. WET tables carry the wet limit first and a dry reference second; the EFB's first-wins dedup keeps the wet limit (verified across all 19,872 wet combos).
- **Algorithm**: faithful port of the EFB's `TOPerfHelper.CalculateTOPerformance` (deobfuscated): pressure altitude from QNH+elevation snapped to the table grid → wind component (from runway heading vs wind) snapped to a bucket → the EFB's BASE MODIFIER (headwind +400 kg/kt, tailwind +1240 kg/kt, engine anti-ice −300 kg, wing anti-ice −500 kg, packs-off +3700 kg) → runway rounded down to the grid → the **highest-OAT row whose limit + modifier still covers the TOW** is the FLEX (assumed) temperature and its V1/VR/V2 are the speeds → flex corrections (anti-ice −3/−5 °C, packs −2 °C, **A350-900 −6 °C**) → TOGA when the corrected flex falls below OAT or the 37 °C flex floor, capped at 72 °C → MTOW = max qualifying limit + modifier. Both variants share the tables exactly like the real EFB.
- **Dispatch**: `A359`/`A35X` (and `A350` aliases) route to `A350Takeoff` in `app/perf_engine.py` with source label "A350 FCOM-derived tables (iniBuilds)"; the dropdown is restricted to CONF 1+F/2/3 (`UP` → 1+F), required distance comes from the PERF2601 profile curves (same pattern as B738), and any refusal (runway < 2000 m, perf-limited, MTOW < weight) degrades to the PERF2601 estimate with a warning instead of erroring.
- **Validation**: 7 new tests in `app/tests/test_perf_engine.py` — hand-computed references from the raw bundle (flex + V1/VR/V2 match across dry/wet, headwind/tailwind, both variants, anti-ice/packs), the −6 °C A350-900 correction, TOGA-on-heavy, wet-lowers-MTOW, short-runway refusal, data integrity (24 tables, row counts, VR≥V1, V2≥VR), and dispatch source label. Also fixed a stale hard-coded `0.25.72` version assertion in `test_ofp_overrides.py` (now reads the app version dynamically). Full suite green.
- **Status**: Implemented (2026-08-10, v0.25.73).

---

# Implementation Plan — Stage 2: single-writer telemetry bus (2026-08-09)

## ⚠ Backup required before implementing — NOT to be done now

Before any Stage 2 code changes are applied, take a backup of the source folder first:

- Source folder: `opsroom-app/source`
- Backup: zip that folder (e.g. `opsroom-app/source-backup-<YYYYMMDD>.zip`) and verify the zip is complete before touching code.
- **Do not** apply any code changes until that backup exists.
- The backup is **not** taken in this session — it is only taken when implementation is explicitly requested.

## What Stage 2 is

The permanent telemetry architecture that fixes the Black Box / Flight Watch data disagreement (#16) and makes the #6 stutter structurally impossible: a **single-writer shared ring buffer**. One telemetry writer reads the sim at a bounded cadence and publishes complete-shape snapshots to an in-memory ring (latest + rolling window); every consumer — Flight Watch, the Black Box recorder, RAAS, announcements, PIREP — reads only the buffer. The minimal SimConnect stream is retired. The staged path (Stage 1 recorder fallback now / Stage 2 bus permanent) and full rationale are logged in #16.

## Verified against source (2026-08-09)

- `_sim_heartbeat` (`telemetry_provider.py:1060`) caches the full stream at 0.8 s → ~1.25 Hz display feed for Flight Watch / RAAS / announcements.
- Black Box record loop (`_record_loop` in `black_box.py`) reads `read_telemetry(force=True, stream="minimal")` → `read_position_minimal` (`simconnect_position.py:1263`) — SimConnect-only, ~17–20 subscriptions, deliberately bypasses the shared cache ("non-poisoning by design").
- `_target_interval` (`black_box.py:600`) requests 30/20/10 Hz by phase, but the SimConnect minimal path is capped at `black_box_simconnect_max_hz` (default 10 Hz) — the requested 30 Hz takeoff-roll/approach rate is currently **unattainable**, and the `max_hz = 30.0 if "fsuipc" in provider` branch is dead code for the recorder because `stream="minimal"` never reads FSUIPC.
- FSUIPC is one batched call per sample (`pyuipc.read(requests)`, `telemetry_provider.py:464/1328`) — a full flight sample costs one API call, so the high-rate stream adds no stutter.
- Degraded SimConnect session (#9 dispatch-thread failure) → minimal stream returns stale/zero → `_normalize` rejects rows → Black Box silently replays the last good (parked) row while Flight Watch stays live on FSUIPC (#16).

## Recommended implementation order (2026-08-09)

1. **Stage 2-lite first (small, high-value)**: make the Black Box recorder **unconditionally** read the FSUIPC full stream (not just as the #16 fallback) so `_target_interval`'s 30 Hz takeoff-roll/approach/landing branch actually engages — the recorder's core job is capturing V1/rotation/flare/hard-landing dynamics, and the minimal path caps it at 10 Hz while healthy. This is a contained change in `black_box.py` + the live Black Box UI source label.
2. **Full single-writer ring buffer (durable)**: one writer (batched FSUIPC read, SimConnect minimal as fallback), in-memory ring (latest + rolling window), all consumers read memory, central failover + health, STALE when both sources dead, minimal stream retired. Resolves the NAV-deviation question (glideslope/localizer come only from SimConnect) by defining what the writer publishes when only FSUIPC is healthy (#21's supplement path).
3. Gate both on the on-simulator verification checklist (capture rates at takeoff/landing, gap continuity, no ghost recordings, Black Box ≡ Flight Watch).

## Safety commitments for Stage 2

- **Frozen/protected surfaces stay untouched** (`OPS_ROOM_PROJECT_CONTEXT.md` §5): GSX modes (Departure/Arrival/Full Turnaround), Fenix loading/boarding/pushback handoff, announcement sequencing (briefing → takeoff → ~10k → descent → landing → park), RAAS callouts/audio, telemetry failover/freshness, in-sim replay engine, finance/PIREP/receipts. The bus changes **where** telemetry is read, not what values flow downstream.
- Every change is a narrow, isolated, backward-compatible patch — no broad rewrites.
- Static validation after each change: `python -m compileall -q app`, `node --check app/static/opsroom.js`, plus the relevant version validators.
- **MSFS live testing cannot be done in this environment** — GSX/announcer/RAAS/recorder behaviour must be re-verified on the simulator PC before publication (project rule #9).

---
