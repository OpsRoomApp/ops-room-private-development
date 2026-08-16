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
- **Status**: Resolved (2026-08-09, v0.25.73 checkpoint) — user-side Fenix EFB option + in-app hardening.

### #2 — Announcer "shutdown" and "After Landing" announcements play together

- **Severity**: Medium
- **Root cause**: Same-tick cascade: when sim loads at the gate, `taxi_in_started` fires AfterLanding, then `_parked_at_gate` sees "AfterLanding" in `_PLAYED` and also fires DisarmDoors/DisembarkStarted in the same tick.
- **Fix**: Added `_PREVIOUS.get("on_ground") is True` guard in `announcements.py:1456` so the `_parked_at_gate` block only fires after the aircraft has been consistently on-ground (not on first same-tick evaluation).
- **Status**: Implemented (2026-08-09, v0.25.73 checkpoint).

### #3 — Fenix doesn't start, doesn't push back, doesn't start engines through GSX

- **Severity**: High
- **Fix**:
  - (Pre-existing) Fenix EFB loading (fuel, cargo, passengers) — already implemented.
  - (Fix #4) Chocks/GPU disconnected after pushback via 30s safety net.
  - **(NEW) Auto-engine-start**: `_auto_start_engines()` in `gsx_remote.py` uses SimConnect `GENERAL_ENG_COMBUSTION` to start all engines 15 seconds after pushback activity is detected. Controlled by `gsx_auto_start_engines` setting (default: True).
- **Status**: Implemented (2026-08-09, v0.25.73 checkpoint).

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
- **Status**: CLOSED 2026-08-11 — user verified no "?" symbols anywhere in the v0.25.77 UI during the build test; the v0.25.76 fallback pass + #24's literal-separator fix covered all reported surfaces. (Rare glyphs still rely on Segoe UI Symbol/Emoji fallback; if any reappears on a specific surface, reopen with the surface name.)

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
- **Status**: Implemented (2026-08-10, v0.25.73) — the three literal `?` separators in `pirep.js` (3 spots) and `obs.js` (2 spots) were replaced with `→` (U+2192), and `"Segoe UI Symbol","Segoe UI Emoji"` fallbacks were appended to the font variables in `pirep.css`, `pirep_print.css`, `host.css` and `obs.css`. A full grep of `app/static/` for literal `?`-separator patterns now returns only legitimate JS ternaries. **Correction (2026-08-10, v0.25.74)**: that claim was premature — five more literal ` ? ` sites existed (logbook finance cards, finance estimate/ledger, Black Box flight label, PDF header) and are now fixed under #38; the claim is true as of v0.25.74.

### #25 — NOTAM GeoJSON layer invisible on the Live Map ("NOTAM LAYER: 0 ACTIVE"; clicking NOTAMs does nothing)

- **Severity**: Medium (the map's NOTAM layer — the only geo view of active NOTAMs — renders nothing)
- **Symptom**: Toggling NOTAMS on the Live Map shows no markers and the status line reads "NOTAM LAYER: 0 ACTIVE". The `/api/nms/notams?latitude=…&longitude=…&radius=…` endpoint answers HTTP 200 every time (18/18 requests in opsroom.log were 200) but the frontend always receives `features: []`, so there is nothing to click.
- **Root cause (verified live against the opsroom.live store + source) — the DB-first path short-circuits an empty result instead of falling through to the proxy**: `get_notams_map()` (`app/notam_client.py:252`) is DB-first: it calls the server store `/api/v1/notams/near?latitude=…&longitude=…&radius_nm=…`. If that call succeeds — **even when it returns zero rows** — it wraps the rows into features and returns `ok:true, features:[…]` immediately, **never touching the proxy fallback** (`fetch_notams_by_geo`, the live FAA NMS GeoJSON path). The proxy only runs when the DB call *fails outright* (`body is None`). Live probes confirm the failure mode: at typical map viewport radii the store returns **zero rows** even over busy airspace — EGLL @ 14 NM → 0, @ 25 NM → 0, @ 40 NM → 1; EGKK @ 14 NM → 0, @ 25 NM → 1; EDDF @ 14/25 NM → 0. The store's `/near` geo index is sparse (rows only appear at ≥40 NM radii), so the map layer draws nothing while the same store's per-airport lookup (EGLL → 24 rows) and the proxy (live FAA NMS GeoJSON with coordinates) both have data. Secondary finding: per-airport rows carry `coordinates: null` (only `/near` rows include coordinates), so any future per-airport fallback must resolve positions from the airport index, not the row.
- **Fix approach (pending implementation)**: mirror the layered fallback that `get_notams_near()` (`notam_client.py:164`) already has — DB first, then proxy, then per-airport:
  1. In `get_notams_map()`, when the DB answers but yields **zero features** (empty row set, or rows whose `coordinates` are unusable), fall through to `nms_client.fetch_notams_by_geo(lat, lon, radius)` and return its GeoJSON features (source "FAA NMS") instead of returning `ok:true, features:[]`.
  2. If the proxy also yields nothing (or is unreachable/token-rejected), fall back to the per-airport walk (`_nearby_airport_notams`) and resolve each row's point from the airport index (`data_loader.load_airports()` lat/lon by `location`/`airport_icao`), since per-airport rows carry `coordinates: null` — the same position source the closure-marker deploy already uses.
  3. Keep the `map:` cache key as-is (it already includes lat/lon/radius); only the resolution order changes, so no cache-invalidation concern.
  4. Frontend `loadNotamLayer()` (`opsroom.js:4367`) already renders any `features` array it receives — the fetch/parse path needs no change; the status line will then show real counts. (Later verified: the layer's *visibility* still needs syncing — see the frontend addendum in Status.)
- **Status**: Implemented (2026-08-10, v0.25.73) — `get_notams_map()` now runs the layered resolution: DB `/near` → (when zero rows or failure) live FAA NMS proxy → (when that yields nothing) per-airport walk with points resolved from the airport index. Verified with a mocked store returning zero rows: the function falls through to the proxy, and the per-airport fallback builds coordinate features from `data_loader.load_airports()` lat/lon.
- **Frontend addendum (2026-08-10)**: the backend fix was not sufficient — the layer stayed invisible even with features present. `olNotamLayer.setVisible(...)` was called exactly once, at map init (`opsroom.js:4985`), with the checkbox's initial state (off). Toggling NOTAMS on later called `loadNotamLayer()`, which fetched and added features but never flipped the layer visible, so nothing rendered and clicks did nothing. Fix: `loadNotamLayer()` now calls `olNotamLayer.setVisible(on)` on every invocation (both on and off), mirroring how every other map layer syncs its visibility from its checkbox (`refreshAviationLayers`, `opsroom.js:4789`). Verified live: `/api/nms/notams?latitude=…&longitude=…&radius=…` returns valid Point features (e.g. LIMM @ 40 NM), `node --check` passes, and the packaged build showed the same single-call bug before the fix. Needs a rebuild to reach the running app.

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
  - **Correction (2026-08-10, v0.25.74, live Fenix flight RJA403)**: the "FSUIPC weights cover Fenix" claim is wrong for this Fenix build. The FSUIPC offsets read garbage on the Fenix — `0x30C0` ≈ -1e-19 lb and `0x30C8` ≈ 2.68e9 lb on the live recording — both rejected by `_finite_weight_lb`, so `gross_weight_lb` stays `None` in every recorded sample and the OFP WEIGHTS cells (PAX, BAG/CARGO, ZFW, TOW, LDW) stay "—" while TIMES + FUEL fill. The SimConnect minimal path carries a working `TOTAL_WEIGHT` (the #32 unit-aware conversion, live-verified ~314k lb on other aircraft).
  - **Implemented (2026-08-10, v0.25.75)**: the #43 enricher thread now also warms a SimConnect weight cache via the cheap batched minimal read, and `_enrich_addon_telemetry` merges `gross_weight_lb`/`max_gross_weight_lb` from that cache whenever the FSUIPC value is missing/rejected — so `_op_snapshot` captures real ZFW/TOW/LDW at OUT/OFF/ON on Fenix flights. Verified live: a C208B session returns its real 8,903 lb gross weight through the merge.

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

### #29 — A350 (A359/A35X) takeoff performance: Tier-1 exact engine from the A350 EFB data

- **Severity**: Medium (A350-900/-1000 were on the generic PERF2601 estimate; the package itself ships the full FCOM-derived takeoff tables)
- **Goal**: A350 takeoff V1/VR/V2 + FLEX + runway-limited MTOW at the same fidelity as the A320neo/B738 tiers, mirroring the existing tiered dispatch.
- **Data source**: the A350 EFB ships its takeoff-performance database as a base64+gzip JSON bundle inside the obfuscated `ini-efb-a350.js`. The obfuscation (self-defending rotating string array — 8,316-string table, checksum-driven rotation offset 177) was reversed, and the bundle extracted to `app/data/perf_a350_tables.json` (2.96 MB, **59,616 rows, 24 tables**): DRY+WET × 6 pressure altitudes (0/2/4/6/8/8.5k ft) × headwind/tailwind. Each row = runway length (2000–4100 m) × OAT (−30…79 °C) × CONF 1+F/2/3 × wind bucket (5/10/20 head, −5/−10/−15 tail) → runway-limited **max TOW** + **V1/VR/V2 at that limit** + limit code. WET tables carry the wet limit first and a dry reference second; the EFB's first-wins dedup keeps the wet limit (verified across all 19,872 wet combos).
- **Algorithm**: faithful port of the EFB's `TOPerfHelper.CalculateTOPerformance` (deobfuscated): pressure altitude from QNH+elevation snapped to the table grid → wind component (from runway heading vs wind) snapped to a bucket → the EFB's BASE MODIFIER (headwind +400 kg/kt, tailwind +1240 kg/kt, engine anti-ice −300 kg, wing anti-ice −500 kg, packs-off +3700 kg) → runway rounded down to the grid → the **highest-OAT row whose limit + modifier still covers the TOW** is the FLEX (assumed) temperature and its V1/VR/V2 are the speeds → flex corrections (anti-ice −3/−5 °C, packs −2 °C, **A350-900 −6 °C**) → TOGA when the corrected flex falls below OAT or the 37 °C flex floor, capped at 72 °C → MTOW = max qualifying limit + modifier. Both variants share the tables exactly like the real EFB.
- **Dispatch**: `A359`/`A35X` (and `A350` aliases) route to `A350Takeoff` in `app/perf_engine.py` with source label "A350 FCOM-derived tables"; the dropdown is restricted to CONF 1+F/2/3 (`UP` → 1+F), required distance comes from the PERF2601 profile curves (same pattern as B738), and any refusal (runway < 2000 m, perf-limited, MTOW < weight) degrades to the PERF2601 estimate with a warning instead of erroring. (No add-on vendor name appears anywhere in the UI or backend for this feature.)
- **Validation**: 7 new tests in `app/tests/test_perf_engine.py` — hand-computed references from the raw bundle (flex + V1/VR/V2 match across dry/wet, headwind/tailwind, both variants, anti-ice/packs), the −6 °C A350-900 correction, TOGA-on-heavy, wet-lowers-MTOW, short-runway refusal, data integrity (24 tables, row counts, VR≥V1, V2≥VR), and dispatch source label. Also fixed a stale hard-coded `0.25.72` version assertion in `test_ofp_overrides.py` (now reads the app version dynamically). Full suite green.
- **Status**: Implemented (2026-08-10, v0.25.73).

### #30 — Black Box `stop_recording` crashes on every stop (release-blocking, found in live Stage-2 testing)

- **Severity**: Critical — found only by running the recorder against the live sim.
- **Root cause**: `stop_recording` (v0.25.72 #20 latch code) rebinds the module-level `_CLOSED_FLIGHT_IDS` dict inside the function (`_CLOSED_FLIGHT_IDS = {key: ...}` in the >100 prune) without declaring it `global`, so Python treats it as a local throughout — the very first `_CLOSED_FLIGHT_IDS[...] = ...` raises `UnboundLocalError`. The file is already finalized on disk at that point, but `_ACTIVE` never clears → the recorder stays "RECORDING" forever and every later `start_recording` is refused until app restart.
- **Fix**: add `_CLOSED_FLIGHT_IDS` to `stop_recording`'s `global` declaration. Regression test: `app/tests/test_black_box_recorder.py` (start → stop → latch → file finalized).
- **Status**: Implemented (2026-08-10, live-test discovery).

### #31 — Black Box `status()` crashes when no recording is active (release-blocking, found in live Stage-2 testing)

- **Severity**: Critical — `/api/blackbox/status` 500s on every idle poll.
- **Root cause**: `status()` computes `stale_seconds` / `stale` / the `live` summary **outside** the `if active:` guard, so with `_ACTIVE = None` the `active.get(...)` calls raise `AttributeError`. The v0.25.73 checkpoint rewrote `status()`'s health block and misplaced the indentation.
- **Fix**: moved the live-summary computation inside the `if active:` guard. Covered by `test_stop_recording_without_active_returns_status` (which calls `stop_recording` → `status()` with no active recording).
- **Status**: Implemented (2026-08-10, live-test discovery).

### #32 — SimConnect weights always read `None` (silent double conversion: pounds × 32.17 → sanitizer rejects)

- **Severity**: High — Live OFP weights / logbook TOW-LDW can never fill over SimConnect, on **any** aircraft (masked as "aircraft doesn't expose weights"; only FSUIPC-filled Fenix/PMDG weights ever showed).
- **Root cause**: the full SimConnect read (`simconnect_position.py`) requests `TOTAL_WEIGHT`/`EMPTY_WEIGHT`/`MAX_GROSS_WEIGHT` with the wrapper's declared units, which are **Pounds** (verified live: a default A330-300 reports ~314,851 lb), then multiplies by 32.17405 as if the SDK returned slugs. The inflated result (>10 M lb) is then rejected by `_sanitize_telemetry`'s 2,000,000 lb bound → `None` on every aircraft, which is why the earlier on-sim probing reported weights blank for non-Fenix aircraft.
- **Fix**: conversion is now unit-aware — detect the wrapper's declared unit for `TOTAL_WEIGHT` once (`b"slug"` in units) and only then apply 32.17405; pounds pass through. Live-verified: `gross_weight_lb ≈ 314,369` for the A330, `max_gross_weight_lb = 513,676`.
- **Status**: Implemented (2026-08-10, live-test discovery).

### #33 — SimConnect heartbeat cache never hits: stamp uses call-start time, so slow full reads expire the cache instantly

- **Severity**: Medium — on the SimConnect-only fallback the writer re-read the full stream on **every** tick (per-SimVar reads ≈ 3.5 s at cruise fps → the fallback ran at ~0.25 Hz instead of the 10 Hz cap; the 0.8 s heartbeat cache was dead code).
- **Root cause**: `_sim_heartbeat` stamped `_SIM_HEARTBEAT_AT = now` with the caller-supplied monotonic time captured at the *start* of the call. A full read that takes longer than the 0.8 s cache window is already "stale" the moment it completes, so the very next call re-reads.
- **Fix**: stamp with `time.monotonic()` at completion. Regression test: `test_cache_uses_completion_time` (a slow mocked read followed by an immediate second call must not re-read).
- **Status**: Implemented (2026-08-10, live-test discovery).

### #34 — SimConnect reads are ~1 Hz / 3.5 s because the wrapper does one request per SimVar — fixed with a batched one-request reader (Stage 2 fast path)

- **Severity**: High — per-SimVar `aq.get` round trips (one sim frame each) made a minimal read ~1.1 s and a full read ~3.5 s at cruise fps: the 30 Hz SimConnect target was physically unreachable and even the 10 Hz fallback cap was ~4× below its own ceiling.
- **Root cause**: the upstream Python wrapper (`AircraftRequests`) issues one `RequestDataOnSimObjectType` per SimVar and the dispatch reads only the first datum — no batching API.
- **Fix**: new batched reader in `simconnect_position.py` — one data definition covers every numeric SimVar (117 of 125; strings stay on a 2 Hz per-var refresh), one `RequestDataOnSimObjectType` per sample, a dispatch hook parses the packed response. Unit-aware weights (see #32), zero-traffic setup (indexed SimVar names baked from the `:index` template), automatic rebuild after session teardown, 5 s backoff then per-var fallback on any failure.
  - Measured live (sim climbing): **minimal path 26.8–27.0 Hz**, full path 308 ms → ~2.8–3 Hz sustained, cold batch setup 99 ms, per-var fallback intact (1.2 s, not-ok handled). The writer's SimConnect fallback went from **0.25 Hz → ~5.9 Hz** (heartbeat full read every 0.8 s still limits it; the recorder ring gets the fast minimal stream).
  - SimConnect traffic per 30 Hz sample dropped from ~45 requests to **1** — strictly less than the pre-Stage-2 display heartbeat (~94 req/s), so stutter is not a concern.
  - **SimConnect cap raised 10 → 30 Hz** (2026-08-10): two live on-sim runs at 30 Hz cadence showed no stutter (27.17 Hz, 326/326 ok, 93% of spans ≤ 35 ms) → `black_box_simconnect_max_hz` default is now 30 in code, settings API validation, and the persisted `settings.json`; the writer's SimConnect cadence matches FSUIPC (30/20/10 by phase).
- **Status**: Implemented (2026-08-10). Covered by `app/tests/test_batched_telemetry.py` (9 tests: definition build, indexed-name baking, dispatch parsing, delegation, pounds/slugs conversion, fallback, heartbeat stamp).

### #35 — Printer receipt previews fail with `NameError: name '_utc' is not defined` (UI regression, found in live app)

- **Severity**: High — every receipt preview (CPDLC / test / custom) 400s with `{"detail": "Preview generation failed for type 'cpdlc': NameError: name '_utc' is not defined"}`; the printer preview dropdown in Settings generates nothing.
- **Root cause**: `app/main.py`'s `printer_preview_endpoint` builds its sample payload with `_utc()`, but the function was never imported in `main.py` (it lives in `printer_client.py`, imported only as `generate_receipt_preview` etc.).
- **Fix**: import it as `_utc as _printer_utc` in the `printer_client` import line (main.py:97) and use `_printer_utc()` at the two call sites (cpdlc sample time + test receipt stamp).
- **Status**: Fixed (2026-08-10) in the working tree — verified by calling `generate_receipt_preview` directly (cpdlc / test / custom all return `ok: True`). The running packaged app predates the fix, so previews only work after the next build.

### #36 — App reload is slow: graceful shutdown force-killed after 5 s on every reload

- **Severity**: Medium-High — reload/exit takes the full 5 s because the launcher's `server.join(timeout=5)` force-kills (`os._exit(0)`); the log shows `OPS ROOM server did not exit cleanly after 5 seconds` on every reload.
- **Root cause**: budget mismatch. The launcher caps shutdown at 5 s total; uvicorn's `timeout_graceful_shutdown=3.0` consumed 3 s of that just draining in-flight UI polls (then cancels them — the `Task cancelled, timeout graceful shutdown exceeded` tracebacks in opsroom.log), leaving only ~2 s for the app's own shutdown handler. The handler runs several sequential bounded joins (replay `stop()` 2.5 s, black-box `shutdown()` 2.0 s, announcements `shutdown_engine()` 2.0 s) — comfortably over the remaining budget, so the process is force-killed before uvicorn finishes.
- **Fix**: rebalance the budget — `timeout_graceful_shutdown` 3.0 → **1.0 s** in `opsroom_launcher.py` (UI polls just reconnect after restart; the shutdown handler now gets ~4 s of the 5 s ceiling). Plus three hardening changes so the handler can never hang:
  1. `shutdown_telemetry_engine()` now sets `_WRITER_STOP`/`_RECOVERY_STOP` **before** closing the SimConnect session (was: close the session first, which could tear it out from under a live writer mid-read).
  2. `simconnect_position._close_session()` no longer calls the wrapper's `exit()` (which does an **unbounded** `timerThread.join()`); it sets `quit=1`, joins with a 0.5 s cap, then closes the DLL handle.
  3. `_opsroom_shutdown()` logs per-step timings (`telemetry/simconnect/replay/blackbox/pmdg/announcements/hoppie/gsx/camera/native/raas`) at INFO so a future slow reload names the exact culprit.
- **Status**: Fixed (2026-08-10) in the working tree — `compileall` + telemetry/recorder test suites green. Needs a rebuild to take effect.

---

### #37 — Performance page: auto-sync everything, only CG stays manual, unit-aware display, grouped layout (IMPLEMENTED 2026-08-10, v0.25.74)

- **Severity**: Medium (UX + correctness — the calculator is only as good as its inputs, and today the pilot must hand-type runway/weather/weights that the app already knows)
- **Goal**: on opening the Performance tab, every field except CG auto-fills from the best live source; the page is grouped (airport/runway → aircraft/weights → weather) with the one manual field highlighted; all weights display in the Host-set unit (lb or kg).
- **Which CG (verified against `perf_engine.py`)**: the engine takes a single `cg` as **% MAC**, used against the `takeoffCgLimits` envelope (indexed by TOW, `perf_engine.py:817`) and the forward-CG V1/VR speed correction (`_dry_speeds`, `perf_engine.py:643-668`). The correct auto-fill is **SimBrief ZFWCG** (`zfwcg`, already wired at `opsroom.js:6479`) — the A32NX-style model the engine mirrors uses ZFW CG as its takeoff CG input. So: **CG = ZFW CG % MAC, auto-filled from SimBrief; the only genuinely manual input when no SimBrief plan exists.** (Note: the sim's own `CG PERCENT` SimVar is a stretch cross-check only — see #37 plan below; never the primary.)
- **Plan (all additive, backend stays kg-internally, frontend converts for display):**
  1. **Units everywhere**: perf page reads `settings.interface.units.weight` (`unitPrefs()`, `opsroom.js:958` — already used by every other module). `WEIGHT KG` input becomes unit-aware: when `lb` is selected show `WEIGHT LB` and convert `kg ⇄ lb` (`×0.45359237`) only at the `calculatePerformance()` payload boundary — the engine always receives kg. Same for the result panel weights and any live-sim hint (e.g. `LIVE 142,500 LB`).
  2. **Live weather sync**: auto-fill prefers `fetch_metar(active_station)` (live AviationWeather.gov, 60 s cache — `weather_client.py:265`, already exposed as `GET /api/weather/{icao}`) over the SimBrief OFP-embedded METAR (`_enrich_plan_airport_data`, `simbrief_client.py:777`), falling back to the OFP METAR when the live fetch fails. Source badge in the result: `LIVE METAR` vs `SIMBRIEF OFP`.
  3. **Live sim weight sync**: on page open (and when on ground at origin), fill `perfWeight` from the writer snapshot `gross_weight_lb` (`writer_latest()`, `telemetry_provider.py:1470` — live-filling since #32) converted to the display unit; derive **ZFW = gross − fuel** (`fuel_weight_lb`) as a bonus field. Note in the UI when the sim weight deviates from the SimBrief plan (e.g. `SIM 142,500 KG vs PLAN 139,800 KG`). CG stays SimBrief/manual.
  4. **Grouped layout**: restructure the perf form into three labelled sections — **AIRPORT / RUNWAY** (runway length, heading, elevation, slope, condition), **AIRCRAFT / WEIGHTS** (weight, CG, flap, anti-ice, packs), **WEATHER** (wind dir/speed, OAT, QNH) — and **highlight the manual field** (CG) with an accent border + a small note ("ENTER ZFW CG % MAC — everything else auto-fills") that disappears once auto-filled.
  5. **Auto-sync on open**: `startPerformance()` (already called when the tab opens) runs the fill chain — SimBrief plan → live METAR → live sim weight — and re-runs on mode toggle (takeoff ↔ landing switches origin/destination station).
  6. **Stretch (best-effort only)**: optionally add the sim `CG PERCENT` SimVar to the batched reader as a cross-check shown next to SimBrief CG, never trusted blindly (Fenix/FBW/PMDG often don't populate it accurately).
- **Status**: Implemented (2026-08-10, v0.25.74) — the perf tab now auto-fills on open: SimBrief plan → live METAR (`/api/weather/{icao}` `metar.decoded`, badge flips to `LIVE METAR · ICAO` with OFP fallback) → live sim weight (`/api/flight-watch` `telemetry.gross_weight_lb`, ZFW = gross − fuel, deviation note vs the SimBrief plan). The form is grouped into AIRCRAFT / WEIGHTS · AIRPORT / RUNWAY · WEATHER sections; the weight input follows `settings.interface.units.weight` (KG or LB label via `#perfWeightUnit`, converted to kg only at the `calculatePerformance()` payload boundary via `perfDisplayToKg`); the ZFW CG % MAC field is the only manual field and carries the dashed accent border + "ENTER MANUALLY — everything else auto-fills" note that hides once auto-filled. `startPerformance()` runs the chain and the MODE toggle re-runs it (switches origin/destination station). Stretch item (sim `CG PERCENT` cross-check) intentionally not implemented.

---

### #38 — Remaining literal `?` separators in the logbook / finance / PDF-print surfaces (amends #24)

- **Severity**: Low (cosmetic, but user-visible: `€313,363 ? €323,668` reads as a broken glyph instead of an arrow)
- **Symptom**: The #24 fix replaced the `?` separators in `pirep.js` (3) and `obs.js` (2), and its status claims *"A full grep of `app/static/` for literal `?`-separator patterns now returns only legitimate JS ternaries"* — that claim is **wrong**. Four literal ` ? ` separator sites remain in template literals (verified by grep this session):
  1. `opsroom.js:5229` — `financeMiniHtml()` (the Logbook debrief FINANCE cards the user screenshotted): `AIRLINE ${money(open.airline,sym)} ? ${money(close.airline,sym)}` and `PILOT ${money(open.pilot,sym)} ? ${money(close.pilot,sym)}` — opening → closing balance.
  2. `opsroom.js:6095` — finance estimate panel: `Flight plan ${route.origin||'----'} ? ${route.destination||'----'}` — route origin → destination.
  3. `opsroom.js:6121` — finance ledger rows: `${rowRoute.origin||'----'} ? ${rowRoute.destination||'----'}` — route origin → destination.
  4. `pirep_print.js:16` — PDF page header route: `${text('originIcao')||'----'} ? ${text('destinationIcao')||'----'}` — this one also lands in the exported PDF, not just the UI.
- **Fix approach**: replace each literal ` ? ` with ` → ` (U+2192, the same replacement #24 already used in `pirep.js`/`obs.js`) — `opsroom.js` (3 spots) and `pirep_print.js` (1 spot). Then re-run the sweep and update #24's false "no ?-separators remain" claim.
- **Status**: Implemented (2026-08-10, v0.25.74) — all five literal ` ? ` sites replaced with ` → `: the `financeMiniHtml()` balance cards (opening → closing), the finance-estimate `Flight plan` row, the finance ledger rows, the Black Box flight label (`blackBoxFlightLabel`, found during the sweep: `.join(' ? ')`), and the PDF page-header route in `pirep_print.js`. A fresh sweep of `app/static/` for `} ? ${` and `join(' ? ')` patterns returns only legitimate JS ternaries — #24's claim is now true.

### #39 — Host setup: "ALLOW LAN / TABLET ACCESS" should be ON by default, including first-time setup

- **Severity**: Low (enhancement; tablet/QR access currently needs a manual enable + restart on every fresh install)
- **Symptom**: The host setup checkbox "ALLOW LAN / TABLET ACCESS" defaults to OFF. Verified in source: `settings_store.py` `DEFAULT_SETTINGS` has `"lan_access": False` (line 101), and the settings normalizer also falls back to `False` when the key is missing (line 210). So on first-time setup the checkbox renders unchecked (`host.js:172` reads `data.server?.lan_access`), the launcher binds `localhost` only (`opsroom_launcher.py:363-364`), and the LAN/QR/tablet path (server_info `tablet_ready`, `/api/server/info` `preferred_url`, QR code) stays unavailable until the user manually enables it, saves, and restarts.
- **Fix approach**:
  1. Flip the default to `True` in `DEFAULT_SETTINGS` (`settings_store.py` line 101) and in the normalizer's missing-key fallback (line 210), so fresh installs / first-time setup start with LAN access enabled and the host checkbox renders checked.
  2. One-time migration for existing installs: existing `settings.json` files may already hold an explicit `false`. Treat the key as `True` on next launch when it was never explicitly enabled (or bump it once) so the default-on applies to everyone, not just new installs — the user wants this ON.
  3. Resulting behavior (no code change needed downstream): launcher binds `0.0.0.0`, prints the LAN interface line, `/api/server/info` reports `tablet_ready` + the LAN `preferred_url`, and the QR panel is usable without a save/restart round-trip.
- **Note / side effect**: binding `0.0.0.0` exposes the web app on the LAN — the existing `trusted_device_gate` / device-security gate still guards API endpoints, and first LAN-enabled run may prompt for the Windows Firewall rule.
- **Status**: Implemented (2026-08-10, v0.25.75) — `DEFAULT_SETTINGS["server"]["lan_access"]` is now `True`; the missing-key fallback defaults to `True`; and a one-time `_migrate_lan_access` helper flips an old explicit `false` to `true` (with a `lan_access_migrated` marker so a deliberate later choice is respected) on both `load_settings` (so the launcher binds 0.0.0.0 on next launch) and `save_settings` (persists the flip).

### #40 — GSX operator auto-selection priority: Airline match → GSX choice → any operator

- **Severity**: Low (behavioral refinement; makes the operator observer deterministic and complete)
- **Context**: RJA403 live session — popup 1 (ground handling) correctly got **Royal Jordanian** via the airline-brand match; popup 2 (catering) had no airline match and fell back to **GSX choice** ("Alpha [GSX choice]"). Both are already the desired behavior. The gap is the **final tier**: when a menu has no `[GSX choice]`/`[GSX selected]`/`[GSX default]` label at all, `gsx_choice()` returns `None` and the observer gives up ("pilot selection required") instead of selecting **any operator**. Desired priority (user-defined, explicit):
  1. **Airline match** — the known brand (stored operator / airlines.csv canonical) contained in the menu: existing authoritative brand-contains block + candidate scoring loop (gsx_remote.py ~1900-1970). Unchanged — a known airline always wins when present, on any popup (ground handling for arrival AND departure/turnaround).
  2. **GSX choice** — the menu's `[GSX choice]` option (existing `gsx_choice()`, gsx_remote.py ~1937). Unchanged — fires when no airline match.
  3. **Any operator — NEW** — the first enabled company option when no GSX-choice label exists, instead of giving up.
- **Fix approach**: in `_operator_observer_choice`, add a tiny helper that returns the first entry of `company_indices` (first enabled company option, same `fallback: True` shape as `gsx_choice()`), and replace the four `return gsx_choice()` fallback sites (`if not candidates`, `if not ranked`, `best_score < 620`, ambiguity guard) with `return gsx_choice() or <helper>()`. Only when there are **no enabled company options at all** does it return `None` → the existing "pilot selection required" safety net. Optional cosmetic: the fallback record message could read "selecting any available operator" for tier 3 instead of "selecting explicit GSX choice".
- **Note**: fallback picks are still remembered as the sector operator (`_remember_selected_operator`) — harmless here because the airline-brand block runs first, so a remembered fallback can never override a present airline; skipping the remember for fallback picks remains optional hardening, not required.
- **Status**: Implemented (2026-08-10, v0.25.75) — `_operator_observer_choice` now has a `first_company_choice()` tier: airline match → `gsx_choice()` → first enabled company option (`fallback: True`); `return gsx_choice()` was replaced with `return gsx_choice() or first_company_choice()` at all four fallback sites. Returns `None` (pilot-selection safety net) only when no enabled company option exists. Verified with fake menus: airline match wins, GSX choice beats first-company, tier 3 picks the first company, all-disabled → None.

### #41 — ChartFox chart files: supplier downloads send no User-Agent → UA-blocking AIP servers refuse with HTTP 451 (mislabeled as 404)

- **Severity**: Medium — every chart served directly by a UA-blocking AIP supplier is unrenderable in the app (e.g. all OJAI charts: aerodrome + parking/docking both failed the same way in the live RJA403 session)
- **Symptom**: UI shows "PDF FETCH FAILED (HTTP 404)" with body `{"ok":false,"error":"No embeddable file URLs in chart detail response.","error_code":"no_direct_file",...}` for charts that actually exist. Verified in `opsroom.log`: `[CHARTFOX PROXY] download_failed ... url=https://carc.gov.jo/pdf/AERODROME%20CHART-%20ICAO%20OJAI.pdf error=451 Client Error: Unavailable For Legal Reasons` → `path=source_url_fetch_failed` → `path=url_fetch_failed` → `path=unavailable files=0 source_url=... source_url_type=0 allows_iframe=False`.
- **Root cause (verified live from the user's PC)**: `charts.py` `_download_and_cache` (line ~1336) sends `headers = {}` for non-chartfox supplier URLs, so `requests` advertises the default `python-requests/x.y` UA. carc.gov.jo (Jordanian CAA, OJAI's AIP publisher) returns **HTTP 451 Unavailable For Legal Reasons** to bot UAs. Live test: `python-requests/2.31.0` UA → 451; curl default and Chrome UA → **HTTP 200 with a real `%PDF-1.6` 14.4 MB aerodrome chart**. Not geo-blocking. The API then maps `no_direct_file` → HTTP 404 (`main.py` ~line 1877), which is why the UI says "HTTP 404" even though the origin said 451. Every other HTTP client in the app sends a UA (weather, NOTAM, SimBrief, Hoppie, map tiles); the ChartFox file download is the only bare fetch.
- **Fix approach**:
  1. In `charts.py` `_download_and_cache`, always send a browser-like `User-Agent` (e.g. a standard Chrome UA constant) — supplier AIP URLs are public browser documents and the ChartFox mirror URLs keep their Bearer auth; sending the UA to both is harmless. This unblocks carc.gov.jo and any other UA-blocking AIP supplier.
  2. Optional: improve the misleading status mapping — `no_direct_file` → HTTP 404 (`main.py` ~1877) mislabels genuine "chart not embeddable" cases too; consider returning the JSON error with a friendlier status/`error_code` surfaced in the UI ("OPEN CHART ON CHARTFOX" already renders as the action).
- **Validation**: after the change, re-fetch `/api/charts/chartfox/file/{cid}` for cid `09bdd9c5-0341-42a0-8641-cbecf98822e6` (OJAI AERODROME CHART) and expect `render_mode: direct_file` with `%PDF` bytes; run `node --check` / `compileall` and the release validator.
- **Status**: Implemented (2026-08-10, v0.25.75) — `_download_and_cache` in `charts.py` now always sends a Chrome user-agent on file downloads; ChartFox mirrors keep their Bearer auth. Live-verified earlier: the same OJAI `carc.gov.jo` PDF that returned 451 to `python-requests` returns 200 with a real `%PDF` to a browser UA.

### #42 — Pushback mislabeled as Taxi Out (Fenix blind spot: body-vx missing + track == heading) — phase-ordering invariant (IMPLEMENTED 2026-08-10, v0.25.75)

- **Severity**: Medium — every departure's pushback shows as "Taxi out" when the pushback isn't visible to the dedicated detectors; flight timeline, Black Box start phase and Flight Watch display all mislabel it
- **Verified root cause (live recording `RJA403_JY-AZC_OJAI-OLBA_20260810143644Z.opsbb.part`, 14:36–14:38Z)**: a real 68 s pushback — ~105 m of backward displacement (lat 31.72079 → 31.71984) with the nose pointed north (heading 350°→080°, tug turning the aircraft) — was classified **TAXI OUT from the first sample** (gs 2.6 kt, still at the stand). The recorder started with `start_phase = "TAXI OUT"` and BLOCK OUT fired at the same movement (14:36Z — user confirms that timing is correct).
  - `_backward_motion_active()` (`logbook.py:578`) is **blind on the Fenix**: `body_velocity_x_fps` is `None` on every sample and `track_deg` == `heading_deg` on every sample (no independent ground track via Fenix+FSUIPC), so neither signal (body-vx ≤ −1.5, or |track−heading| ≥ 150°) can ever fire.
  - `_gsx_pushback_active()` was False in this session, so `pushback_active` = False → the phase machine defaulted movement to TAXI OUT.
  - **Structural gap**: `_phase` (`logbook.py:740`) returns TAXI OUT even while `times["block_out"]` is unset — no ordering invariant prevents "taxi out" before "off blocks" (exactly what the user saw).
  - **Landmine for any latch-based fix**: the fast taxi-out override (single `gs > 10` sample, `logbook.py:1005`) would clear a pushback latch mid-pushback because `_forward_motion_evidence()` returns True when track mirrors heading — the recording shows 10.5–12.6 kt spikes at 44–46 s while the tug was still turning.
  - User's parking-brake observation confirmed in the data: gs → 0 at 14:37:53Z, phase PARKED at 14:37:58Z, parking brake set at 14:38:06Z (movement → stop → brakes set = pushback completed, pre-taxi hold).
- **Fix approach** (user's rules, signal-independent):
  1. **Phase-ordering invariant** — `logbook._phase`: on the ground and moving (gs ≥ 1) while pushback isn't proven over → **PUSHBACK**; never TAXI OUT before the pushback ends. `_analyse`: latch a phase-level PUSHBACK on the first ground movement out of PARKED (no GSX/body-vx/track evidence required) — "any movement before off blocks is pushback".
  2. **BLOCK OUT stays at first movement** (user confirmed 14:36Z is correct): keep off-blocks firing at first movement while the phase reads PUSHBACK — drop/loosen the `not tug_pushback_active` gate (`logbook.py:1080`) so off-blocks still records at pushback start.
  3. **End the latch only on genuine taxi proof** — `_forward_motion_evidence` returns "unknown" when track mirrors heading and body-vx is missing (so a 10.5 kt pushback spike can't end it); rely on the existing sustained-motion override (≥5 s + real displacement ≥ 0.010 nm) for the pushback→taxi transition; optionally use the parking-brake cue (movement → stop → brake set → next movement = taxi).
  4. **Mirror in `flight_watch._phase`** (`flight_watch.py:83`) — display-only phase has the same defect (only consults `_gsx_pushback_active`; shows TAXI during a Fenix pushback).
  5. Optional: add a third backward-motion signal to `_backward_motion_active` using movement azimuth from lat/lon deltas vs heading — proven viable by this recording (backward displacement is visible in position even when track mirrors heading).
- **Acceptance test**: replay the recording's first 95 s through the fixed `_analyse`/`_phase`; expect Parked → PUSHBACK (14:36Z, BLOCK OUT at first movement) → TAXI OUT only after real taxi resumes (post-14:38Z); Black Box `start_phase` = "PUSHBACK"; no spurious PARKED mid-pushback.
- **Status**: Implemented (2026-08-10, v0.25.75) — replayed the full RJA403 recording through the fixed `_analyse`/`_phase`: transitions are now **PUSHBACK (1.2 s) → PARKED (82 s, after the movement→stop→parking-brake cue) → TAXI OUT (338.8 s)**, `start_phase` = "PUSHBACK" (was "TAXI OUT"), BLOCK OUT at first movement (14:36Z). Changes: (1) phase-ordering invariant in `_phase` — pre-off-blocks ground movement is PUSHBACK; (2) `_analyse` latches pushback on first ground movement out of PARKED (signal-independent — Fenix blind spot); (3) `_forward_motion_evidence` returns unknown when track mirrors heading and body-vx is missing, and the fast >10 kt taxi override now requires explicit forward proof, so a 10-12 kt pushback spike cannot clear the latch; (4) the sustained-motion override + movement→stop→brake-set cue end the latch; (5) BLOCK OUT fires at first movement even during latched pushback; (6) mirrored in `flight_watch._phase` with a display-only latch.

---

### #43 — Stage 2 writer cadence collapses: Fenix SimConnect LVar enrichment stalls the writer 1.5–2.5 s per 0.2 s cache expiry (IMPLEMENTED 2026-08-10, v0.25.75)

- **Severity**: High — Stage 2 promises 30/20/10 Hz by phase, but the recording shows ~3 Hz effective at takeoff with an 8 s hole at rotation; approach/landing will inherit the same holes, re-creating the #21 jagged-peak graphs and risking "insufficient telemetry" in the full PIREP.
- **Verified root cause (live recording `RJA403_JY-AZC_OJAI-OLBA_20260810143644Z.opsbb.part` + live `/api/telemetry/diagnostics`)**: the Fenix adapter's L:Var enrichment runs **synchronously inside the writer tick**: `_writer_tick` → `read_telemetry(force=True)` → `_enrich_addon_telemetry` → `_read_simconnect_lvars` (`telemetry_provider.py:1605`) loops ~13 Fenix L:Vars, each a per-LVar Python `Request(...)` + `req.value` (`addon_telemetry.py:461–500`). Each full LVar batch read takes ~1.5–2.5 s through the Python SimConnect wrapper — the same per-SimVar cost that caused the original #6 stutter, now starving the single writer instead of stuttering the sim. The 0.2 s value cache (`_SIMCONNECT_LVAR_CACHE_AT`) limits read *frequency*, not *blocking time*, so every 0.2 s the writer dies for ~2 s.
  - Cadence evidence (recording): TAKEOFF ROLL 30 Hz target → bursts of 5–7 samples (= the 0.2 s cache window) then 1.5–2.5 s stalls, effective ~3 Hz; ENROUTE 10 Hz target → 1.0–2.1 s gaps dominate (238 of last 600 live deltas in the 1–2 s bucket), effective ~0.7–1 Hz. **8.02 s hole at el 788.25 → 796.27** — aircraft accelerating 149 → 171 kt, i.e. V1/Vr/rotation missing.
  - FSUIPC itself is healthy (batched read ~12 ms — bursts hit 30 Hz while the LVar cache is hot); the stall is purely the SimConnect LVar path inside `_enrich_addon_telemetry`.
  - Adapter flapping to `generic` (el 22.7–53.3 taxi, 619.9–647.6 taxi, brief 936/1,451 climb) is a **separate, benign** symptom: SimConnect LVar probe raced/failed for a few seconds, `addon_state` went None, then recovered. Takeoff roll (el 761–803) is 100% `fenix_a32x` — takeoff data itself is correct and Fenix-clean.
- **Fix approach** (move enrichment off the writer hot path):
  1. **Separate low-frequency enricher thread** (2–5 Hz) reads the Fenix SimConnect LVars into a shared `addon_state` cache (keyed the same way as `_SIMCONNECT_LVAR_CACHE`); `_enrich_addon_telemetry` merges only the cached values and **never touches SimConnect synchronously**. The writer then sustains the promised 30/20/10 Hz; the 8 s rotation hole disappears.
  2. Keep the existing fallback chain untouched: FSUIPC WASM offsets when SimConnect is unavailable, and STALE surfacing when both sources are dead.
  3. Preserve per-sample `addon_state`/`addon_event_meta` provenance for the recorder (the enricher thread stamps the same dict into every sample it publishes, so Black Box still records LVar-backed events like flap/gear/master transitions at ring cadence).
- **Validation**: live cadence re-measurement on the same flight profile (expect steady 30 Hz at takeoff roll, 20 Hz taxi/climb, 10 Hz cruise, no >1 s gaps), plus PIREP gap-bridging check (`_GAP_BRIDGE_MAX_SAMPLES`/`_GAP_BRIDGE_MAX_SECONDS`) and full test suite.
- **Status**: Implemented (2026-08-10, v0.25.75) — a dedicated `OpsRoom-AddonEnricher` thread now owns the blocking SimConnect L:Var batch reads (`_read_simconnect_lvars(requests, force=True)` every 0.25 s) and warms the shared `_SIMCONNECT_LVAR_CACHE_*`. The writer's `_enrich_addon_telemetry` passes `_read_simconnect_lvars_cached`, which returns cache-only values (fresh ≤0.5 s) and never touches SimConnect; on a miss it records the request set for the enricher and returns [] so enrich falls back to the cheap FSUIPC WASM offsets. Simulation test: writer reads never hit SimConnect (sim-hit count flat), enricher force-reads warm the cache, expired cache returns [] without touching the sim. The enricher also warms the #26 SimConnect weight cache.

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

### #44 — Post-arrival finalize can hang forever: flight stuck RECORDING after block-in when GSX latches are lost (IMPLEMENTED 2026-08-10, v0.25.75)

**Verified live 2026-08-10 (RJA403 OJAI→OLBA):** block-in 15:41:18Z → POST ARRIVAL PENDING 15:41:29Z → flight stuck RECORDING for 47 min until manual completion 16:28:40Z. GSX arrival services HAD completed (OLBA handling receipts issued 16:19:59Z/16:20:01Z), but the logbook never auto-finalized.

- **Root cause 1 — no fallback timer.** `_hold_for_post_arrival_services()` (logbook.py:1511) holds the flight open with only three exits: (a) `_arrival_services_complete_for_record()` returns True, (b) telemetry disconnect >12 s after `post_arrival_pending` (sim exit), (c) manual completion. There is no "PARKED + engines off + brake set for N minutes → finalize" fallback, so a live sim with fresh FSUIPC data keeps the flight open indefinitely.
- **Root cause 2 — GSX latches are memory-only and die on restart.** `_arrival_services_complete_for_record()` (logbook.py:1487) requires `automation_status().mode ∈ {ARRIVAL, FULL_TURNAROUND}` plus in-memory latches `deboarding/cleaning/lavatory_complete` or `*_deferred_or_skipped` (`_AUTOMATION["latches"]` in gsx_remote.py:2751). The app restarted at 15:57:27Z (0.25.74 rebuild) mid-arrival; every latch was wiped and the mode gate then returned False forever.
- **Fix approach:** (1) add a post-arrival fallback timer in `_hold_for_post_arrival_services` — e.g. once `PARKED` + `engines_running is False` + `parking_brake` hold continuously for 5 min (reusing the `_maybe_autostop_black_box` on-blocks conditions), force `_finalize(meta, "automatic post-arrival timeout")` even if GSX latches never arrive; (2) persist GSX automation latches (or a compact arrival-complete snapshot) to disk so a restart can re-seed the gate; (3) on startup, if a RECORDING flight is already `PARKED`+post-arrival with fresh telemetry, arm the same fallback timer immediately. Keep the GSX-complete fast path as-is (it finalizes sooner when latches are healthy).
- **Also observed:** after the 15:57 restart the logbook engine loop stopped advancing `updated_utc` (frozen at 15:55–15:56) until the manual finalize — verify on restart the recorder loop re-attaches to the persisted RECORDING row and resumes ticking (samples kept flowing: 6,873 in the DB).
- **Validation:** replay RJA403 metadata: auto-finalize should fire ≤5 min after block-in without GSX, and within ~45 s of GSX arrival receipts when latches are present. No regression to the GSX-complete fast path.
- **Status**: Implemented (2026-08-10, v0.25.75) — `_hold_for_post_arrival_services` now arms a fallback timer when the aircraft is PARKED with engines off and the parking brake set; after 5 continuous minutes it releases the hold (fires a POST ARRIVAL COMPLETE event) so the engine finalizes. Any interruption (brake release / engine restart / out of PARKED) resets the timer; the GSX-complete fast path still wins. Unit-verified: holds + arms, releases after 5 min, resets on brake release, GSX path unaffected.

### #45 — `saveSettingsWithDebounce` called but never defined: printer settings never persist (IMPLEMENTED 2026-08-10, v0.25.75)

- **Root cause:** `initPrinterSettings()` change handler calls `saveSettingsWithDebounce()` (opsroom.js:4077) but no such function exists anywhere in the frontend (`function saveSettingsWithDebounce` / `const saveSettingsWithDebounce` / `let` — zero matches; the only `saveSettings`-adjacent helpers are inline `fetch('/api/settings', {method:'PUT'})` calls). Every toggle of printer enabled / CPDLC auto-print / printer selection throws `ReferenceError: saveSettingsWithDebounce is not defined` and `settings.printing` is never written back.
- **Evidence:** `frontend_errors.jsonl` shows this exact error since v0.25.58 (opsroom.js:3535), repeated at v0.25.71 (:3995) and v0.25.72 (:4048); the broken call site is still present in the current tree at line 4077.
- **Fix approach:** define the debounced save helper (e.g. a 500 ms debounce around the existing `PUT /api/settings` pattern used at opsroom.js:745/7445) and call it from `initPrinterSettings`; or replace the call with a direct settings PUT. Wire the same helper into any other setting-change handlers that currently rely on it. Verify by toggling printer settings in the Settings UI and confirming `settings.json` persists.
- **Status**: Implemented (2026-08-10, v0.25.75) — `saveSettingsWithDebounce()` is now defined in `opsroom.js` (500 ms debounce around `PUT /api/settings` with the `printing` section; toast on failure, settings refresh on success) and `initPrinterSettings` keeps calling it.

### #46 — winspool.drv not available in the frozen build: printer list empty (IMPLEMENTED 2026-08-10, v0.25.75)

- **Root cause:** `_get_winspool()` (printer_client.py:20) does `ctypes.windll.winspool` and the frozen app cannot load the DLL — log: "winspool.drv not available: Failed to load dynlib/dll 'winspool'. Most likely this dynlib/dll was not found when the application was frozen" (13 occurrences 06:58–14:34Z on 2026-08-10). `list_printers()` then returns `[]`, so the printer dropdown in Settings is empty and thermal receipt printing cannot target a printer.
- **Fix approach:** (1) confirm whether PyInstaller needs winspool.drv bundled/hooked in the spec (add as a binary/collector if so); (2) add a fallback enumeration path (e.g. `Get-Printer` via PowerShell, or `win32print` if available) so the frozen build can still list printers; (3) surface a clear "no printer detected" state in Settings instead of a silently empty dropdown. Verify in the built exe, not the source run, since the failure is frozen-build specific.
- **Status**: Implemented (2026-08-10, v0.25.75) — `_get_winspool()` now retries `ctypes.WinDLL("winspool.drv")` after the `windll.winspool` failure, and `list_printers()` falls back to PowerShell `Get-Printer | ConvertTo-Json` (same `{name, port, driver, status, jobs}` shape) when winspool still cannot load. Needs a packaged-build verification.


### #47 — Full PIREP analysis crashes on every flight: `NameError: name 'result'` (the real cause of "insufficient telemetry" for departure/approach/landing)

- **Severity**: High — every full PIREP since v0.25.9 shows DEPARTURE/APPROACH/LANDING as "--", "No stability-gate data was available", and a score breakdown of 0/15-0/20-0/25-0/25-0/15, even when the recording is complete.
- **Symptom (live, completed RJA403)**: 7,705 samples, takeoff 100% Fenix, full landing/approach recorded — yet the PIREP DEPARTURE ANALYSIS (Liftoff Speed, Pitch, Bank, Takeoff Roll, Climb Gradient, Gear Up, Flaps Up) and LANDING ANALYSIS (touchdown rate, G, TD point, rollout) are all "--". The telemetry endpoint returns `analysis: {"ok": false, "reason": "PIREP analysis failed: NameError: name 'result' is not defined"}`. The hero score (97) still shows because it falls back to the stored debrief from finalize.
- **Root cause (verified in source + live)**: `analyse_pirep()` (`app/pirep_analysis.py:629-1010`) builds the entire result dict inline in a `return { ... }` literal, but its last entry (line 1005) calls `_opsroom_pirep_compute_satisfaction(meta, result)` — and `result` is **never assigned** anywhere in the function. Evaluating the dict literal raises `NameError` before the dict is returned; the trailing `return result` (line 1007) is dead code. Every caller (`logbook.py:1444` finalize, `1843`, `2153` analysis cache) catches the exception and stores `{"ok": false, "reason": "PIREP analysis failed: ..."}`, so `pirep.js:576` (`telemetry.analysis || entry.analysis_summary || {}`) renders an empty analysis. The data was never the problem — the departure/approach/landing dicts are fully computed (runway labels, profiles, stability gates, touchdown) and thrown away by the crash. All three tested flights (EWG6107, EWG72E, RJA403) crash identically.
- **Fix approach (surgical, no regression)**: change `return {` → `result = {` at line 911, move the satisfaction hook out of the dict literal into `result["passenger_satisfaction"] = _opsroom_pirep_compute_satisfaction(meta, result)` after the dict closes, and keep `return result`. `_opsroom_pirep_compute_satisfaction` already tolerates missing telemetry (its own try/except returns `{"error": ...}`), so no new failure mode. Validation: re-run `/api/logbook/{id}/telemetry` for RJA403 → `analysis.ok` is true, `departure.liftoff_speed_kts` / `landing.touchdown_rate_fpm` populate, and the score breakdown sums to the stored score.
- **Status**: Implemented (2026-08-10, v0.25.75) — `analyse_pirep` now assigns `result = { ... }` and sets `result["passenger_satisfaction"] = _opsroom_pirep_compute_satisfaction(meta, result)` after the dict closes. Live-verified against completed RJA403: `analysis.ok` True, `departure.liftoff_speed_kts` 177.96, `landing.touchdown_rate_fpm` −308.35, `touchdown_g` 1.1184, `touchdown_speed_kts` 131.89, approach profile 109 rows, score breakdown 15/16/4/19/15.


### #48 — Literal `?` glyphs still in the PIREP surfaces: h1 route separator, ZOOM −, scoring-rules text (amends #24/#38)

- **Severity**: Low (cosmetic, but user-visible: "OJAI ? OLBA", "ZOOM ?", "Bounces: minor ?2 ...").
- **Symptom (live DOM)**: the full PIREP h1 reads `OJAI ? OLBA`, every chart toolbar reads `ZOOM ?`, and the scoring-rules dialog reads `Bounces: minor ?2, moderate ?5, severe/multiple ?8, capped at ?12`.
- **Root cause (verified in source)**: literal ASCII `?` (0x3F) characters typed in the static files. The #24/#38 sweeps only grepped spaced patterns (` ? `, `} ? ${`, `join(' ? ')`), so these unspaced sites were missed:
  1. `pirep.html:56` — `<h1><span id="originIcao">----</span><i>?</i><span id="destinationIcao">----</span></h1>` (h1 separator; should be `→`).
  2. `pirep.html:18` — `<span id="flightRoute">---- ? ----</span>` pre-load placeholder (should be `---- → ----`).
  3. `pirep.js:430` — `data-zoom="out">ZOOM ?</button>` (zoom-out; should be `ZOOM −`).
  4. `pirep.html:150` — "Bounces: minor ?2, moderate ?5, severe/multiple ?8, capped at ?12" (penalty values; should be `−`).
  5. `scoring_rules.html:20-64` — every penalty badge (`?3`, `?8`, `?12`, `up to ?12`, `0 to ?200 fpm`, `Below ?500`) and the grade bands (`Excellent ?92 · Very Good ?84 · Good ?74 · Acceptable ?62`) — should be `−` for negative/penalty values and `≥` for grade thresholds.
- **Fix approach**: replace with proper glyphs (`→` U+2192 for route separators, `−` U+2212 for negative/penalty values, `≥` U+2265 for grade bands) in `pirep.html`, `pirep.js`, `scoring_rules.html`; then run a comprehensive sweep of all `app/static/*` for literal `?` in non-ternary contexts (including unspaced forms like `<i>?</i>`, `?2`, `ZOOM ?`) to close the sweep gap. The DOM already renders `→` correctly elsewhere (`pirep.js:335` flightRoute), so the #24 font fallbacks are fine — these are literal characters, not a font issue.
- **Status**: Implemented (2026-08-10, v0.25.75) — replaced `pirep.html:18`/`:56` route separators with `→`, `pirep.js:430` `ZOOM ?` with `ZOOM −`, the `Bounces: minor ?2 …` text with `−` values, and all of `scoring_rules.html`'s `?N` penalty badges/bands with `−`/`≥` (0 deduction row uses plain `0`). Re-sweep of the three files for `?[0-9]` / `ZOOM ?` / `<i>?</i>` / `---- ? ----` returns clean (remaining `?` in pirep.js are legitimate JS ternaries).


## Recommended implementation order (2026-08-09)

1. **Stage 2-lite first (small, high-value)**: make the Black Box recorder **unconditionally** read the FSUIPC full stream (not just as the #16 fallback) so `_target_interval`'s 30 Hz takeoff-roll/approach/landing branch actually engages — the recorder's core job is capturing V1/rotation/flare/hard-landing dynamics, and the minimal path caps it at 10 Hz while healthy. This is a contained change in `black_box.py` + the live Black Box UI source label.
2. **Full single-writer ring buffer (durable)**: one writer (batched FSUIPC read, SimConnect minimal as fallback), in-memory ring (latest + rolling window), all consumers read memory, central failover + health, STALE when both sources dead, minimal stream retired. Resolves the NAV-deviation question (glideslope/localizer come only from SimConnect) by defining what the writer publishes when only FSUIPC is healthy (#21's supplement path).
3. Gate both on the on-simulator verification checklist (capture rates at takeoff/landing, gap continuity, no ghost recordings, Black Box ≡ Flight Watch).

## Safety commitments for Stage 2

- **Frozen/protected surfaces stay untouched** (`OPS_ROOM_PROJECT_CONTEXT.md` §5): GSX modes (Departure/Arrival/Full Turnaround), Fenix loading/boarding/pushback handoff, announcement sequencing (briefing → takeoff → ~10k → descent → landing → park), RAAS callouts/audio, telemetry failover/freshness, in-sim replay engine, finance/PIREP/receipts. The bus changes **where** telemetry is read, not what values flow downstream.
- Every change is a narrow, isolated, backward-compatible patch — no broad rewrites.
- Static validation after each change: `python -m compileall -q app`, `node --check app/static/opsroom.js`, plus the relevant version validators.
- **MSFS live testing cannot be done in this environment** — GSX/announcer/RAAS/recorder behaviour must be re-verified on the simulator PC before publication (project rule #9).

## Stage 2 implementation status

- **Status**: Implemented (2026-08-10). One `OpsRoom-TelemetryWriter` daemon thread in `telemetry_provider.py` reads the simulator at a bounded cadence and publishes complete-shape snapshots to an in-memory ring (`_WRITER_RING`); every consumer reads only the buffer.
  - FSUIPC healthy → one batched `pyuipc.read` full-stream sample per tick; the recorder now gets the **same FSUIPC stream Flight Watch uses**, so the 30 Hz takeoff-roll/approach/landing rate (and the 20 Hz taxi/climb/descent, 10 Hz cruise) actually engage — the old `stream="minimal"` cap at 10 Hz is gone on the healthy path.
  - SimConnect-only fallback → full stream served through the 0.8 s heartbeat cache (display) + the recorder ring, both SimConnect-safe; `_read_simconnect_lvars` gained a 0.2 s value cache so the 30 Hz writer cannot stutter Fenix LVar reads (the #6 failure mode). The fallback was reworked after live on-sim testing: the per-SimVar wrapper reads were ~1 Hz (minimal) / ~3.5 s (full), so a **batched one-request reader** now covers all 117 numeric SimVars (#34) — minimal 26.8–27.0 Hz, full ~308 ms, writer fallback 0.25 → ~5.9 Hz, and SimConnect weights now fill via the #32 unit-aware conversion.
  - `_record_loop` is now a pure ring consumer — zero simulator reads from Black Box. `read_telemetry(force=False)` serves the writer-published cache (3 s max age) before ever touching the sim; `force=True` (logbook phase snapshots) still forces a fresh read.
  - Both sources dead → the writer publishes error/stale samples; the recorder rejects them and `status()` surfaces STALE / TELEMETRY LOST instead of replaying the last good row.
  - Validation: live simulation harness with a fake FSUIPC source (idle 1 Hz, phase cadence 20/30/10 Hz, ring drain, cache-only consumer reads, forced-read path, STALE rejection) + SimConnect-fallback branch check; `compileall` and the full test suite green. **MSFS on-sim verification still required before publication** (project rule #9).

---

### #49 — In-sim replay always returned 409 "Stop the active Black Box recording" (IMPLEMENTED)

- **Status**: Implemented (2026-08-10, v0.25.75 working tree) — `logbook._finalize()` closes the matching Black Box recording; `black_box_replay.start()` auto-stops a stale recorder when no live flight is recording.

**Symptom:** Every `/api/blackbox/{id}/replay/start` attempt in the logs returned 409 Conflict — replay was unusable. Reproduced against RJA403 (2026-08-10): the logbook flight was finalized (manual completion) but the Black Box recorder kept running until the app closed, so the replay guard always blocked.

**Root cause:** Two compounding defects.
1. `logbook._finalize()` never closed the Black Box recorder. The recorder only stopped via the 120 s on-blocks autostop (`_maybe_autostop_black_box`), which needs the logbook engine loop alive and phase == PARKED. When the engine loop stalled (app restart wiping GSX latches, #44 territory) or the flight was manually completed, the recorder ran for hours past block-in.
2. `black_box_replay.start()` hard-failed with 409 whenever `black_box.status().recording` was true, even when the recording belonged to an already-completed flight — so the user could never replay.

**Fix (SkyDolly parity):**
- `logbook._finalize()` now closes the Black Box recording for the same `flight_id` ("FLIGHT FINALIZED") right after the flight record is saved COMPLETE — the recorder can never outlive its flight.
- `black_box_replay.start()` reordered guards: a live OPS ROOM flight recording still hard-blocks (unchanged), but a stale Black Box recording with no live flight is now auto-stopped ("REPLAY TAKEOVER") and replay proceeds — matching SkyDolly, which simply takes over the user aircraft.
- Verified: mock test (stale recorder auto-stopped, live flight still protected) + end-to-end test (real recording closed by `_finalize`) + full test suite green (74/74 + 116/116).

---

---

### #50 — In-sim replay writes failed silently: ctypes Enum never unwrapped + INITPOSITION struct wrong size + frame API mismatch (IMPLEMENTED)

- **Status**: Implemented (2026-08-10, v0.25.75/76 working tree) + **verified live in-sim** (Fenix A320, RJA403 takeoff roll t=760–805): `VERDICT: PASS — 659 frames, 0 errors`, position/heading/speed all tracking the recording (the earlier "heading stuck at 4.5°" was the wrapper reporting heading in **radians** — 4.5 rad = 258° = the correct takeoff heading).

**Symptom:** "Black Box → start in sim replay" never moved the aircraft; the standalone driver reproduced the same — pose writes returned ok but the sim ignored them.

**Root cause (three stacked bugs in `app/simconnect_position.py`):**
1. `sm.new_def_id()` returns a **plain `enum.Enum` member**, not a ctypes-int; every `sm.dll.AddToDataDefinition` / `SetDataOnSimObject` threw a ctypes `ArgumentError` that `replay_apply_state` swallowed as `ok=False`. The wrapper's own code unwraps with `.value` — the replay path never did.
2. `_ReplayInitPosition.airspeed` was `c_double` (8 B) but the SDK declares `DWORD` (4 B) → 60 vs 56 bytes → `SIMCONNECT_EXCEPTION_INVALID_DATA_SIZE` → the initial teleport silently failed.
3. `replay_subscribe_frame` called `sm.SubscribeToSystemEvent` — that method does not exist in SimConnect 0.4.26 (it is `sm.dll.*`), so the Frame clock always fell back to monotonic timing.

**Fix (SkyDolly parity):** unwrap every definition/request id with `.value` at all 4 replay dll call sites; correct `_ReplayInitPosition` to `c_uint32 on_ground / c_uint32 airspeed` (knots); call `sm.dll.SubscribeToSystemEvent` / `sm.dll.UnsubscribeFromSystemEvent` with `.value`. Driver `tools/test_replay_driver.py` also converts the wrapper's radian heading to degrees for honest readbacks, and now **restores the user aircraft to its pre-replay baseline** after the test instead of leaving it at the replay endpoint.

---

### #51 — Replay of the RJA403 landing clipped the ground ~20 s before touchdown: recorded MSL altitude collapses near the field (IMPLEMENTED — clamp + #54 recorder datum fix)

- **Status**: Clamp implemented + landing **verified live in-sim** (2026-08-10): 3 NM out at 603 ft → touchdown at 20 ft / 120 kt → rollout 12 ft / 52 kt → 1,869 frames, 0 errors, position/heading/speed tracking the runway. **Data-side root cause still open — see below.**

**Symptom:** replaying t=3461→3554 (Beirut landing) the aircraft was written below terrain at t≈3520, ground collision engaged, and the sim stopped accepting pose writes (position frozen, GS ramping) — looked like a crash.

**Root cause (recording data, not the replay engine):** in the RJA403 Fenix recording the `altitude_ft` column drifts off true MSL near the arrival field — it goes **negative while AGL stays positive** (touchdown row: alt −58 ft, AGL 10.5 ft; implied terrain swings −103 → +73 ft across the segment). The recorder's altitude (likely baro/QNH or FSUIPC-datum dependent) loses ~150 ft vs the sim's terrain at the field. **Why it happens and why the aircraft froze need the recorder-side investigation** (candidate: baro altitude captured instead of GPS/true MSL, or a QNH datum offset; verify against `radio_altitude_ft`/`agl_ft` which stay sane).

**Fix implemented (replay side, SkyDolly-parity safe):** `replay_apply_state` now floors the pose altitude at **sim terrain + recorded AGL** — `GROUND_ALTITUDE` (cached 1 s, only probed below 300 ft AGL so cruise pays nothing) + the recording's trustworthy radio altitude, with a +2 ft cushion (on-ground frames snap to terrain+3 ft). The aircraft can never be written below the ground it actually flew, and the approach/rollout remain smooth because the *recorded* altitude is used whenever it is already above the floor.

**Remaining (RESOLVED by #54, 2026-08-10):** the recorder altitude-datum fix (pressure 0x0570 preferred over baro 0x3324) and the ~2 s dropout fix (Stage-2 single-writer bus) both landed — see #54. Old recordings rely on the clamp; new recordings are clean.

---

### #52 — In-sim replay stutters: pose data definition re-registered on every frame (~300 extra SimConnect calls/sec) (IMPLEMENTED)

- **Status**: Implemented + verified (2026-08-10) — the same landing replay that previously showed a constant stream of `SIMCONNECT_EXCEPTION_TOO_MANY_OBJECTS` now runs clean with **zero exception spam** and smooth cadence (1,869 frames, 0 errors).

**Root cause:** `_ensure_replay_pose_definition` called `sm.new_def_id()` + 9× `AddToDataDefinition` on **every frame** — ~300 SimConnect API calls/sec of pure churn, exactly the #6 stutter equation. SkyDolly registers the `PositionAndAttitudeUser` definition **once** at connect and reuses it for every frame.

**Fix (SkyDolly parity):** the pose definition is now cached in `_REPLAY_POSE_DEFINITION` (first-use registration, reused thereafter) and reset together with `_REPLAY_INITIAL_DEFINITION` + the terrain cache when the session closes/rebuilds (`_close_session`), so a reconnect can never reuse a stale definition id.

**Also addressed from live testing:** the ground-terrain probe (`GROUND_ALTITUDE`) is a ~35 ms SimConnect read — it is now gated behind the 300 ft AGL check and cached for 1 s, so cruise/descent replay never blocks on it. The driver test also had a `--no-freeze` diagnostic mode (kept) and now auto-restores the aircraft to baseline on exit.

### #53 — Replay camera goes wild + "alt clamp crashed the aircraft" (RESOLVED — camera not app-controlled)

- **Status**: RESOLVED 2026-08-11 — camera decision: the app does NOT control the camera (replay path is camera-safe by design). The observed camera chaos was a symptom of the #51 ground clip + #52 per-frame definition churn, both fixed; with those landed the replay plays visually clean and the camera behaves normally. No camera commands will be added.

**What was observed:** (a) frozen mode: after the ground clip the sim stopped accepting position writes (aircraft visually stuck at 133 ft while GS ramped — the clip engaged collision state); (b) `--no-freeze` mode: the aircraft followed but the sim's own dynamics fought the writes near the ground (heading jumped to 331°, GS collapsed), the view looked stuttery, and on exit the aircraft was left at the replay endpoint — which read as "the clamp crashed the aircraft".

**Findings / notes:**
- The **freeze is correct** (SkyDolly freezes the user aircraft in Normal replay mode — `AbstractSkyConnect::updateUserAircraftFreeze` freezes for `Replay`/`ReplayPaused`); the earlier "freeze breaks velocity" theory was disproven — a frozen probe wrote 56.6 kt GS fine. The #51 clip (not the freeze) was what stopped writes.
- The camera chaos tracked the collision/overwrite moment, not the replay itself; with #51 + #52 the landing now plays visually clean, and the driver restores the aircraft so nothing is left broken.
- **Resolved 2026-08-11**: camera control explicitly declined by user — camera must work normally, never driven by the app. Remaining notes for reference only: (a) in-app replay end behavior (restore vs leave at landing spot) stays as-is unless requested; (b) re-verify the Fenix ground-dynamics fight on the actual landing roll at 1.0× (the 1.5× test was smooth, but the flare/rollout is where addon flight models push back hardest).

---

### #54 — Recorder data integrity: `altitude_ft` goes negative near the arrival field + periodic ~2 s dropouts (data-side root cause for #51, IMPLEMENTED 2026-08-10)

- **Status**: Implemented — root causes found and fixed in the live telemetry path + recording schema. Remaining verification is on-sim (next fresh flight).

**Root cause 1 — altitude datum (FIXED):** `altitude_ft` preferred the baro **indicated** altitude (FSUIPC 0x3324), which follows the sim's QNH/Kollsman setting. On the RJA403 flight the QNH drift reached ~150 ft near the field — recorded MSL hit −58 ft at touchdown while radio alt stayed 10.5 ft (implied terrain swung −103 → +73 ft over t=3400–3554, all rows fsuipc7 source, verified from the file). The corrupt MSL is what drove the replay pose below terrain and caused the #51 ground clip.

- **Fix (telemetry_provider.py):** `altitude_ft` now prefers the **pressure altitude (0x0570)** — the sim's own standard-atmosphere MSL, QNH-independent, physically incapable of drifting with a baro setting. Baro indicated (0x3324) remains second, GPS (0x6020) the diagnostic fallback. Pilot-facing displays are unaffected: Flight Watch and the logbook read `indicated_altitude_ft` first, so the altimeter still shows the QNH-corrected value. Black Box, replay, map ownship and analysis all consume the now-true MSL.
- **Fix (black_box.py):** new append-only schema-v3 field `altitude_source` records which offset produced each sample's altitude, so any future drift is verifiable from the file itself (old recordings decode unchanged).

**Root cause 2 — periodic ~2 s dropouts (FIXED BY STAGE 2):** the 18 gaps >1.5 s (spaced 5.8–7.0 s) in the RJA403 recording were produced by the **pre-Stage-2 recorder**, which polled its own SimConnect minimal stream at `_target_interval` and stalled on its flush cadence — the exact multi-reader path #16/#28 retired. The Stage-2 single-writer bus replaced that path entirely: the recorder drains the writer's ring with timestamp-preserving cursors, flushes are tiny (60-row zlib + one INSERT, ms-scale), and the ring holds 120 s so a slow flush can never lose samples. Verified on the first Stage-2-era recording (RJA403 19:40Z): median cadence **32.3 Hz**, no periodic stall pattern in clean flight (the end-of-recording burst in that file is the in-sim replay tests teleporting the aircraft — replay-test pollution, not recorder behaviour). Occasional 0.5–1.5 s FSUIPC-side hiccups remain (sim-side, not fixable app-side).

**Acceptance (next fresh flight, with user):** record a clean flight, verify `altitude_source` == `0x0570_plane_altitude` on FSUIPC rows, raw altitude stays above terrain with the clamp disabled, and no >1.5 s gaps in a full takeoff + approach/landing segment.
### #55 — Announcer "camera-based volume" never changes with the camera view (IMPLEMENTED 2026-08-11)

- **Severity**: Medium — the volume feature is ON by default but the multiplier is pinned to a constant, so the PA never varies with the view, unlike Universal Announcer
- **Verified root cause (code + live probe)**:
  1. **Distance-from-world-origin bug.** `_poll_camera_distance()` (announcements.py:646) computes `sqrt(cx^2+cy^2+cz^2)` of the camera's *world* position (bridge `cameraPosX/Y/Z` from `SIMCONNECT_RECV_CAMERA_DATA.Position`, confirmed `camera_bridge_2024/src/main.cpp:469`; world coords are metres from the planet origin). At a European airport that magnitude is ~1.4e6 m — so `_camera_volume_multiplier()` is pinned to `external_pct` (40%) forever whenever the bridge is running; switching cockpit↔external changes the magnitude by a few hundred metres out of 1.4 M, i.e. invisible.
  2. **The SimConnect fallback never fires.** `aq.get("CAMERA POS X")` returns `None` because the SimConnect 0.4.26 wrapper registers no camera SimVars (verified: `Attributes.py` has none; `AircraftRequests.get()` → `None` for unknown keys). With no bridge, `_CAMERA_DISTANCE` stays 0.0 → multiplier pinned to `cockpit_pct` (100%) forever.
  3. **Wrong mechanism vs Universal Announcer.** UA does not use distance — it reads the camera *state* (which view is active) and applies per-category multipliers (Cockpit / Showcase-Cabin / External / Drone), per its own `camera-volume.md`. Distance is a poor proxy and ours is broken math on top.
- **The correct signal (verified live)**: FSUIPC offset **0x026D (1 byte) = CAMERA STATE** (official FSUIPC7 Offset Status doc v0.7.1): `2=Cockpit, 7=SixDoF, 9=Showcase, 3=External/Chase, 5=Fixed on Plane, 6=Environment, 4/10/19=Drone, 8=Gameplay, 17=Replay`. Live probe against the running sim read `5` (Fixed on Plane) cleanly through the app's own bundled pyuipc — zero extra cost.
- **Fix approach** (surgical, ~30 lines):
  1. `telemetry_provider.py`: add `(0x026D, "b")` to the Stage-2 writer's existing FSUIPC batch (one byte in the same `pyuipc.read`, no extra SimConnect traffic, 10–30 Hz freshness) → expose `camera_state` in the snapshot.
  2. `announcements.py`: replace the distance curve in `_camera_volume_multiplier()` with camera-state categories — `{2,7}→Cockpit`, `{9}→Cabin`, `{3,4,5,6,8,10,19}→External`, hold last-known category for non-flight states (menus/world map/replay). Existing **Cockpit / Cabin / External sliders stay unchanged** (same settings contract, UA parity). Drop the broken distance math; keep `camera_distance_m` for diagnostics only.
  3. Optional: expose `camera_state` in the host status payload so it is verifiable from Settings.
- **Status**: IMPLEMENTED 2026-08-11 — see commit/version notes; verified with the test suite.

---

### #56 — Pushback STILL mislabelled TAXI OUT on EWG5EZ despite #42 fix: GSX-active latch consumed by the parked-brake cue at sample 0 (IMPLEMENTED 2026-08-11)

- **Severity**: Medium — every departure from a cold logbook start shows "Taxi out" for the pushback again (flight timeline, Black Box `start_phase`, Flight Watch)
- **Verified root cause (exact replay of flight `2011789eb0094859b21036444d2d044d`, EWG5EZ EDDB→LDSP, 2026-08-11)**: replaying the flight's 3,815 stored logbook samples through the current `_analyse`/`_phase` reproduces the live app exactly: **sample 0 (06:57:59, parked) sets `pushback_forward_taxi_proven = True` before any movement** → at first real movement (t=1751.3 s = 07:27:10) the #42 phase-ordering invariant (`not times["block_out"] and not pushback_forward_taxi_proven` → PUSHBACK) is skipped because the flag is already True → `PARKED → TAXI OUT` (identical timestamp to the live event).
  - **Mechanism**: at flight start GSX reports the pushback service row as **ACTIVE/PERFORMING** (departure services just began — the tug is *scheduled*, not pushing). `_analyse` latches `pushback_positive_latch=True` from that GSX row (logbook.py:928). The aircraft is parked with **parking brakes set**, so #42's "movement → stop → brakes set = pushback complete" cue (logbook.py:1005–1012) fires on the *same* parked sample and stamps `pushback_forward_taxi_proven = True` — **permanently** (nothing ever clears it). 29 minutes later the real pushback moves the aircraft and the invariant sees "pushback already proven over".
  - A fresh-meta replay of the same recording produces **PUSHBACK** correctly — the defect is purely the accumulated pre-movement state, which is why #42's acceptance test (RJA403, clean cold start with no GSX-active row) passed.
- **Fix approach** (builds on #42, keeps its rules):
  1. **Gate the parked-brake completion cue on real movement.** Add `state["pushback_movement_seen"]` — set whenever a latched pushback sample shows `gs >= 1.5` (or real lat/lon displacement). The brake cue may only set `pushback_forward_taxi_proven` when `pushback_movement_seen` is True. A parked sample (gs ~0, brakes set) with a GSX-active latch must instead *drop* the latch without stamping proof: clear `pushback_positive_latch`/`pushback_active` (the GSX row is a schedule artifact, not a physical pushback).
  2. **Defensive ordering invariant.** The #42 invariant should additionally require `not state.get("pushback_forward_taxi_proven") or times.get("block_out")`-consistent state — i.e. a proven flag set before `block_out` and before any movement is by definition invalid; treat pre-movement proven as absent.
  3. **Verify with the EWG5EZ replay**: rerun the 3,815-sample replay and expect `PARKED → PUSHBACK (t≈1751, BLOCK OUT at first movement) → TAXI OUT only after genuine taxi`; also confirm the RJA403 acceptance still passes and the fresh-meta first-95 s test still yields PUSHBACK.
- **Status**: IMPLEMENTED 2026-08-11 — see commit/version notes; verified with the test suite.

---
### #57 — Live OFP WEIGHTS: PAX row shows "178 KG" — passenger count must be unitless (IMPLEMENTED 2026-08-11)

- **Severity**: Low — cosmetic but misleading: a passenger count rendered as a weight
- **Root cause (code)**: `patchBriefingOfpLive` → `wrow()` (opsroom.js:1487). The `isCount` flag only strips the unit from the **planned** cell (`isCount ? briefingOfpWeight(item.planned, '', 0) : disp(item,'planned')`); the **actual** and **delta** cells always go through `disp(item,'actual')` / `briefingOfpWeight(..., unit, 1)`, which append `KG`. The backend is correct — `ofp_actuals.py` emits `passengers.actual` as a plain int count (from GSX/Fenix `pax_loaded`).
- **Fix**: in `wrow()`, when `isCount`, render `actual` and `delta` with an empty unit too (same as planned). ~1-line change.
- **Acceptance**: Live OFP shows `PAX  178  —  178  —` (no KG anywhere on the PAX row); copy-actuals / print output also unitless for PAX.

---

### #58 — Live OFP WEIGHTS: PAYLOAD actual never auto-fills ("planned payload only"), stays "—" (IMPLEMENTED 2026-08-11)

- **Severity**: Low-Medium — feature gap; the user wants the payload auto-filled in KG like PAX/BAG-CARGO already are
- **Current state**: `ofp_actuals.py` `_weights_section` hard-codes `rows["payload"] = _value_cell(flight.get("payload"), None, ...)` → actual always None. BAG/CARGO already auto-fills from `fenix_loading["cargo_loaded_kg"]`, and PAX from `fenix_loading["pax_loaded"]` (fenix_adapter.loading_progress, verified).
- **Fix approach** (auto-fill in KG, plan-consistent):
  1. Payload actual = **pax block weight + cargo weight**:
     - cargo = `cargo_loaded_kg` from Fenix loading (kg) — already consumed for BAG/CARGO.
     - pax block weight = actual pax count × **plan-implied per-pax weight**: `(plan.payload − plan.cargo) / plan.passengers` (kg per pax; fall back to a standard 84 kg / 175 lb when the plan lacks the split or passengers == 0). Using the plan-implied per-pax keeps the derived payload consistent with the SimBrief plan instead of inventing an arbitrary pax weight.
  2. Only fill when a trusted measured source exists (pax_loaded or cargo_loaded_kg not None); otherwise keep "—" with the current availability note — never fabricate.
  3. Units: payload is a weight, so KG/LB display is correct (unlike PAX in #57); display-unit conversion must reuse the existing `convert_weight_value` path.
- **Acceptance**: with Fenix/GSX boarding data, Live OFP PAYLOAD shows an actual KG value ≈ pax block + cargo; without any loading source it still shows "—".

---
### #59 — TAKEOFF/OFF recorded ~45 s late on EWG5EZ: GSX pre-departure state blocks airborne confirmation (IMPLEMENTED 2026-08-11)

- **Severity**: Medium — the OFF timestamp (07:43:41Z) fired at 2,147 ft AGL instead of at rotation (~07:42:50), shifting the takeoff-roll window and corrupting departure analysis timing; same GSX-state family as #56
- **Live evidence (flight 2011789eb0094859b21036444d2d044d, EWG5EZ EDDB→LDSP)**: recording shows on_ground=False, gs ~160-190, ias ~170-185, agl 349→2,147 from 07:42:56, yet `confirmed_airborne` stayed False until 07:43:41 (agl 2,147, vs 1,299) — the phase stayed TAKEOFF ROLL for ~45 s after liftoff, then flipped to TAKEOFF/CLIMB the instant GSX cleared.
- **Root cause (code + replay)**: `_airborne_candidate()` (logbook.py:669-679) returns False whenever `_gsx_predeparture_active()` is True (logbook.py:446-466 — GSX boarding/catering/refuel/water/gpu rows with raw in {4,5,7}, or cached `passengers_boarding_total`/`boarding_cargo_percent` progress). GSX keeps the departure workflow in that state until it registers the aircraft has departed, so airborne confirmation (and therefore the TAKEOFF phase and BLOCK-OFF→TAKEOFF timing) waits on GSX. Replay of the takeoff window through `_analyse`: GSX-blocked → TAKEOFF never fires; GSX-cleared → TAKEOFF fires ~33 s earlier. `_phase` has no independent fallback: the only TAKEOFF entry points (`not airborne_seen and airborne_confirmed`, and the `confirmed_airborne` recovery override) both depend on `confirmed_airborne`.
- **Fix approach**:
  1. `_airborne_candidate` must not be vetoed by GSX when the physical evidence is unambiguous (on_ground=False + gs ≥ 55 + ias ≥ 45 + agl ≥ 30, as here): treat GSX pre-departure as a *weakening* factor only when physical evidence is borderline — e.g. skip the GSX veto when agl ≥ 100-150 ft and vertical_speed_fpm ≥ +500 (the aircraft is clearly departing).
  2. Alternatively/in addition, `_phase` should leave TAKEOFF ROLL via a physical latch: after N consecutive airborne-candidate samples with agl ≥ 200 ft, confirm airborne regardless of GSX (GSX state can only delay a *departure*, never prove one).
  3. Verify with the EWG5EZ takeoff replay: expect TAKEOFF at ~07:42:50 (rotation, agl ≈ 150 ft) instead of 07:43:41; ensure GSX-blocked mock still never produces a false TAKEOFF while on the ground.
- **Status**: IMPLEMENTED 2026-08-11 — see commit/version notes; verified with the test suite.

---
### #60 — Live OFP TOW (and ZFW/LDW) never auto-fill on Fenix: FSUIPC 0x30C0 TOTAL WEIGHT is None (IMPLEMENTED 2026-08-11)

- **Severity**: Medium — TOW shows "—" in the Live OFP ACTUAL column on Fenix flights even after takeoff; ZFW (out-snapshot calculation) and LDW (on-snapshot) share the same root cause and will stay blank too. PAX + BAG/CARGO already fill (Fenix loading), so this is the remaining gap of #26.
- **Verified root cause (EWG5EZ flight, live)**: `gross_weight_lb` is **None on every recorded sample** — including the takeoff — while `fuel_total_lb` decrements normally. The off/out/on operational snapshots (`_op_snapshot`, logbook.py:276) read `sample.gross_weight_lb`, which on the FSUIPC path comes only from offset **0x30C0 TOTAL WEIGHT**. The Fenix does not populate that standard offset (it runs its own weight model), so the off-snapshot stores `gross_weight_lb = None` → `snapshot_cell` (ofp_actuals.py:420) has nothing to convert → TOW actual None. Same for `calculated_zfw_lb` (gross − fuel) and the future on-snapshot LDW.
- **Fix approach — REVISED 2026-08-11 after live EFB-portal verification** (the Fenix EFB exposes an exact, structured source; nothing new to install):
  1. **PRIMARY — Fenix loadsheet (Final) endpoint**: `GET /fenix/loadsheet?loadsheetType=Final` on the EFB portal (8083). **Verified live mid-flight (200, cruise)**: returns `tow` (67,725.95 kg), `zfw` (60,939.74), `law` (LDW 63,623), `macTow` (30.6), `macZfw` (32.5), `maxTow` (73,500), `maxZfw` (61,000), `maxLaw` (64,500), `pax` (178), `totalCargo` (2,670 kg) — all as `{value, unit}` objects except MACs. The old assumption "mid-flight it 400s" is WRONG for the Final type — it works at any phase. At each out/off/on snapshot (and Live OFP refresh while Fenix is the active aircraft), call this endpoint and fill TOW / ZFW / LDW directly, plus the MAX column from maxTow/maxZfw/maxLaw. Add a short TTL cache (e.g. 30 s) so repeated refreshes don't hammer the portal.
  2. **Fenix adapter fallback**: keep the existing `loading_progress` extraction (pax/cargo path) for the pre-departure boarding screen when the Final loadsheet is unavailable.
  3. **SimConnect TOTAL_WEIGHT fallback at snapshot moments**: when the aircraft is NOT Fenix and `gross_weight_lb` is None at an out/off/on snapshot, do one batched SimConnect `TOTAL_WEIGHT` read (the #32-fixed reader, verified live) and use it — one read per flight event, negligible traffic, no writer-path stutter. Covers any aircraft that omits FSUIPC 0x30C0.
  4. Wire the chosen value into `_op_snapshot`'s `gross_weight_lb` (or enrich the sample before the snapshot is captured); keep "never fabricate" (None stays None if all sources miss).
- **Acceptance**: on the next Fenix departure, Live OFP TOW/ZFW show actuals ≈ planned, LDW fills at block-in, and the WEIGHTS MAX column shows the Fenix maxTow/maxZfw/maxLaw; on non-Fenix (FSUIPC-populated) aircraft nothing changes.
- **Status**: IMPLEMENTED 2026-08-11 — see commit/version notes; verified with the test suite.

---
### #61 — Performance tab: Fenix EFB portal exposes an exact takeoff/landing perf engine — integrate as Tier-1 source (IMPLEMENTED 2026-08-11)

- **Severity**: Feature (high value) — the Fenix EFB (port 8083) ships the aircraft's own certified performance calculation. The Performance tab currently depends on SimBrief TLR / perf-engine approximations; for Fenix flights we can return the exact values the pilot sees on the EFB takeoff page, with zero extra sim traffic.
- **Verified live (2026-08-11, mid-flight)**: reverse-engineered the EFB bundle (main.js) and called the portal directly with this flight's real data:
  - `POST /fenix/calculate/vspeeds` → **HTTP 200**: `vSpeeds {v1:149, vr:149, v2:152}`, `flexTemperature:62`, `topl:83779`, `toplLimited:false`, `flap:2`, `headwind:5`, `greenDotSpeed:221`, `flapRetractionSpeed:150`, `slatRetractionSpeed:195`, `trimSetting:0.5`, `trimDirection:"DN"`, `stopMargin:191`, `correctedStopMargin:536`.
  - `POST /fenix/calculate/ldr` exists for landing (same envelope pattern).
- **Request contract** (from bundle, EFB posts flat + a `request` string):
  - `request`: required non-empty string (context id, e.g. "opsroom" — passes model validation).
  - Flat fields: `WindDirection`, `WindSpeed`, `Flap` (1+F → 1, opt → 0, else number), `Temperature`, `PacksOn` (bool), `Weight: {Value, Unit:"KG"}` (Value = kg as integer, e.g. 67.7 t → 67700), `AircraftType` (enum, see below), `Sharklets`, `RunwayLength` (m, int), `Qnh` (hPa, int), `Elevation` (ft, int), `MacTow` (0 if unknown), `ForceToga` (bool), `AntiIceSetting` ("Engine"/"EngineAndWing"/"None"), `SurfaceCondition` (e.g. "Dry"), `RunwayMagneticHeading` (deg), `Icao` (airport, upper), `Runway` (runway id).
  - `Weight.Value` convention from the bundle: `100 × parseInt(towTonne.toString().replace(".",""))`.
- **AircraftType enum — verified against the RUNNING backend**: accepts `A320214` (CFM CEO) and `A320232` (IAE CEO); **rejects** `A320251`/`A320271` (NEO), `A319*`, `A321*` (this build's enum covers the Fenix A320 CEO family only — the EFB bundle maps more, e.g. "A320 NEO LEAP"→"A320251", but the live backend 400s on them). Driver must map the active aircraft: Fenix A320 engine type CFM→A320214, IAE→A320232, and fall back gracefully ("unsupported by this portal version") for anything else.
- **Fix approach**:
  1. New `fenix_perf` module (or extend `fenix_adapter`): `fetch_vspeeds(...)` and `fetch_ldr(...)` with the contract above; small TTL cache (30 s) keyed on (icao, runway, weight, cg, flap, wx).
  2. In the Performance tab: when the active aircraft is Fenix and the EFB portal responds, call `/calculate/vspeeds` and render V1/VR/V2, FLEX, flap, trim, TOFL, stop margin, green-dot, retraction speeds — with a "Fenix EFB" source tag; fall back to the existing SimBrief-TLR/perf-engine tiers when the portal is absent or returns 400/unsupported.
  3. Auto-fill the request inputs from existing sources: weight/TOW from the Fenix loadsheet (see #60), runway/wind/temp/QNH from the OFP/METAR, CG from macTow.
  4. The `request` string must always be present (validation fails without it) — use a fixed app identifier.
- **Acceptance**: on a Fenix flight, Performance tab shows V-speeds/trim/flex matching the EFB takeoff page for the same inputs; non-Fenix aircraft unchanged (existing tiers); no stutter or extra SimConnect traffic (pure HTTP to localhost portal).
- **Status**: IMPLEMENTED 2026-08-11 — see commit/version notes; verified with the test suite.

---

### #62 — QOL: electronic loadsheet signing (real-pilot sign-off) on the Live OFP (IMPLEMENTED 2026-08-11)

- **Severity**: Feature (QOL) — the pilot reviews the loadsheet (planned vs actual weights/MAC from the Fenix Final loadsheet, see #60) and electronically signs it like in real operations. Purely additive: a flight with no signature behaves exactly as today.
- **Design decisions (confirmed with user 2026-08-11)**:
  - **One signature slot** per flight (not CAPTAIN + FO).
  - **Type AND draw both available on PC and tablet**, scratchpad-style: the pad mirrors the kneeboard's TYPE/DRAW tool toggle (opsroom.js `scratchpadTool` + `data-tool` pointer-event CSS — `touch-action: none` for drawing, pointer-events off in type mode). DRAW = small canvas (~320x140) with pen strokes via pointer events, CLEAR, works with mouse/finger/pen; TYPE = uppercase terminal-font text input. Switching modes while a drawing exists asks via the in-app `<dialog>` confirm.
- **Location**: Briefing -> OFP tab, Live OFP panel. `SIGN LOADSHEET` button in the existing actions row (COPY/PRINT row, opsroom.js `briefingOfpLiveSkeleton`), plus a `SIGNED ✓ HH:MMZ` chip in the status strip. Dialog shows the loadsheet summary being signed (planned vs actual TOW/ZFW/LDW/MAC/PAX/CARGO + source stamps + UTC).
- **Snapshot at sign time**: the exact values covered (weights, MAC, sources, UTC) are stored with the signature so the record proves what was signed, not just that it was.
- **Storage**: dedicated `loadsheet_signatures` table (flight_id PK, signer, role optional, signature data URL PNG, signed_utc, snapshot_json). NOT `metadata_json` — the recorder upsert (logbook.py:1270) rewrites that column wholesale and would clobber the signature.
- **When**: SIGN always available pre-departure; subtle "ready to sign" hint when a Fenix Final loadsheet is synced (#60) + flight RECORDING + phase PARKED/TAXI OUT + unsigned. **Locked at OFF** — no re-sign/clear after takeoff.
- **API**:
  - `GET /api/briefing/ofp-live/signature?flight=<id>` -> current signature state
  - `POST /api/briefing/ofp-live/sign` {signer, role?, sig_data_url?, snapshot} -> stores, returns ok
  - `DELETE /api/briefing/ofp-live/signature` (pre-departure only, clear/re-sign)
  - `/api/briefing/ofp-live` payload gains a `signed: {...}` block so the existing refresh loop renders state.
- **Surfaced in**: Live OFP chip, logbook flight detail, full PIREP documentation section, and a `SIGNED: NAME · ROLE · HH:MMZ` line on the printed Live OFP receipt (`printer_format_ofp`).
- **Sequencing**: build on #60 (signing a sheet with empty actuals is pointless) — same Fenix loadsheet snapshot source.
- **Acceptance**: on a Fenix departure, pilot opens SIGN LOADSHEET, draws or types, signs; chip shows SIGNED; after OFF it is locked; the printed receipt and PIREP include the signature; non-Fenix/unsigned flights unchanged.
- **Status**: IMPLEMENTED 2026-08-11 — see commit/version notes; verified with the test suite.

---

### #63 — Passenger satisfaction ignores hard landings: perfect 100/100 despite -592 fpm / 1.92 g touchdown (IMPLEMENTED 2026-08-11)

- **Severity**: High — the satisfaction engine reads field names the analysis never emits, so every deduction silently no-ops and **every flight scores 100/100 "Excellent"**. Live proof: EWG5EZ EDDB→LDSP (2026-08-11) touched down at **-592 fpm / 1.92 g** (well above `very_hard_landing_fpm=400` → −25 pts and `excess_g_threshold=1.5` → −10 pts) and still reported `score 100 · category Excellent · mult ×1.05 · rep +3` with only "Schedule within tolerance" + "Comfort within tolerance" and zero negative explanations.
- **Root cause — key-name mismatch between producer and consumer**: `analyse_pirep` (`pirep_analysis.py:975`) emits the landing block as **`touchdown_rate_fpm` / `touchdown_g`** and the approach block's stability gates as `stability_500`/`stability_1000`, but `passenger_satisfaction.compute()` (`passenger_satisfaction.py:87-92`) reads **`landing.vertical_speed_fpm`**, **`landing.unstable_approach`**, **`comfort.peak_g`** / `comfort.max_bank_deg` / `comfort.turbulence_peak_fpm`, and **`operations.taxi_out_minutes` / `taxi_in_minutes`**. Verified against the live flight's `analysis_summary`: `landing.vertical_speed_fpm → None`, `comfort` block is **absent entirely** (keys `[]`), `operations` block absent, so `landing_deduction = 0`, `comfort_deduction = 0`, `ops_deduction = 0` — full marks every time. There is no `comfort`/`operations` section produced anywhere in `analyse_pirep`; the scorer was written against a shape that doesn't exist.
- **Fix approach** (align the scorer to the real analysis shape):
  1. `landing_deduction` reads `landing.touchdown_rate_fpm` (abs value; scorer compares `> very_hard_landing_fpm`), keeping the 200/400 fpm thresholds and 12/25 penalties, and the "Smooth landing" positive note only when ≤ hard threshold.
  2. **Comfort block**: derive it from existing analysis data instead of a missing section — `peak_g` from `landing.touchdown_g` (≥1.5 → −10), `max_bank_deg` from the approach stability checks or enroute max bank (≥35° → −5), turbulence from the max vertical-speed swing if available; if a source is genuinely missing, skip that deduction (never fabricate).
  3. **Unstable approach**: map from `approach.stability_500.stable == False` (the 500 ft gate, `stability_500` exists on every flight with `checks[].ok` per criterion) → `unstable_penalty=15`.
  4. **Operations**: taxi_out/taxi_in minutes from the recorded `times`/`durations` (block_out→takeoff, landing→block_in) instead of a missing `operations` section; keep the 25/15-min long-taxi thresholds.
  5. Add a regression check to the existing satisfaction unit tests: feed a `-600 fpm / 2.0 g / stability_500.stable=False` fixture and assert the score is well below 100 with the correct negative explanations.
- **Status**: IMPLEMENTED 2026-08-11 — see commit/version notes; verified with the test suite.

---

### #64 — Process killer: 45× SimConnect dispatch crashes (`0xc00000b0`) corrupt the heap → `OPS ROOM.exe` died with `0xc0000374` (STATUS_HEAP_CORRUPTION) in ntdll.dll (IMPLEMENTED 2026-08-11)

- **Severity**: High — the app **crashed hard** at 11:30:54 local on EWG5EZ (35 s after block-in, right after arrival services were requested): Windows Event Log `Application Error #1000`, faulting module `ntdll.dll`, exception `0xc0000374` (heap corruption) — the classic signature of a native buffer overrun accumulating until ntdll's heap validation trips. No Python traceback (it's a native crash), so `opsroom.log` just stops; the launcher respawned the process at 11:31:55. The flight survived (state is in SQLite; the #44 timer still finalized it at 09:35:22Z) but the whole app was down ~1 min in the middle of post-arrival processing.
- **Root cause**: the Python SimConnect wrapper's dispatch callback has crashed **45 times this session** with `WinError 0xc00000b0` (native access violation). The #9 guard (`_guarded_dispatch_run`, `simconnect_position.py:51`) catches the *Python* exception and rebuilds the session each time — but the **native heap damage persists** across rebuilds. Failure rate **accelerated** through the session (2 → 3 → 5 → 5 → 8 per log bucket), and one of the crashes finally landed in a way that tripped ntdll. The arrival-services request itself was probably coincidental (it's an HTTP/remote-API path, `POST /api/gsx/automation/start` returned 200); the dispatch thread was crashing ~once a minute regardless.
- **Fix approach** (bounded reconnect — stop retrying into a corrupt heap):
  1. Track consecutive SimConnect dispatch crashes on the session; after a small ceiling (e.g. 5 within 5 minutes) **stop rebuilding the SimConnect session entirely** and permanently degrade to the FSUIPC/FSUIPC-WASM path for the rest of the app run — the enrichment already has that fallback (`_read_simconnect_lvars_cached` returns `[]` → WASM offsets), and FSUIPC carried every sample of this flight with zero fails. Log a single "SimConnect disabled for this session" line so it's visible.
  2. Optionally isolate the SimConnect session in a helper process so native crashes can never take down the main app (bigger change; consider after the bounded-reconnect ceiling proves insufficient).
  3. Add a startup/WER sentinel so a previous-run crash is surfaced on the next launch (host setup shows "last run ended in a native crash" with the event-log excerpt) — currently the user only sees "server died?" with nothing in opsroom.log.
- **Status**: IMPLEMENTED 2026-08-11 — see commit/version notes; verified with the test suite.

---

### #65 — #44 amendment: 5-min post-arrival fallback must NOT fire while GSX automation is actively running arrival services; persist GSX latches across restart (IMPLEMENTED 2026-08-11)

- **Severity**: Medium-High — the #44 fallback timer finalized EWG5EZ **without arrival-service receipts** even though the pilot had requested arrival services and GSX was engaged. Sequence: block-in 09:30:19Z → `POST /api/gsx/automation/start` succeeded → **app crashed 09:30:54Z** (#64) → restart wiped the memory-only GSX latches (`_AUTOMATION["latches"]`, `gsx_remote.py:2761`) → `_arrival_services_complete_for_record()` could never return True → the 5-min timer (armed at block-in) fired 09:35:22Z and finalized "automatic post-arrival complete" **without the arrival receipts** (finance shows no arrival-services entries).
- **Root cause**: the timer is a blunt instrument — it checks only "PARKED + engines off + brake for 5 min" and **never checks whether GSX is actually mid-arrival right now**. When the app crashes mid-arrival, GSX looks "dead" (latches wiped) and the timer believes it. The sim-exit path already covers the genuine "GSX can never finish" case.
- **Fix approach**:
  1. **Pause the fallback while GSX is engaged**: if `automation_status().mode ∈ {ARRIVAL, FULL_TURNAROUND}` (GSX is actively working arrival services), do not count the fallback timer — wait for GSX completion. Only arm the timer when GSX mode is genuinely idle/absent.
  2. **Persist the GSX latches** (the unimplemented half of original #44): write `_AUTOMATION["latches"]` (and mode) to disk on every change; on startup re-seed the gate so an app restart doesn't erase arrival progress.
  3. On restart with a RECORDING flight already PARKED+post-arrival, re-arm the fallback timer from the persisted block-in time, but only if GSX is not actively working.
- **Status**: IMPLEMENTED 2026-08-11 — see commit/version notes; verified with the test suite.

---

### #66 — Phase wobble: ~20 rejected `ENROUTE → CLIMB` transitions over 11 min on EWG5EZ (IMPLEMENTED 2026-08-11)

- **Severity**: Low-Medium — after `ENROUTE` was accepted at 07:51:30Z (07:43:42 takeoff, so ~8 min after rotation), the phase machine tried to revert to `CLIMB` **20 times** (07:51:31 → 08:02:29, ~every 30 s) and each was correctly rejected as `impossible_transition`. No phase corruption (ENROUTE held; CRUISE accepted at 08:02:29), but it's sustained log noise and signals the climb-confirm gate's hysteresis is too loose right after the ENROUTE transition (the enroute-confirmed detector and the climb detector disagree for ~10 min).
- **Fix approach**: after ENROUTE is accepted, suppress CLIMB re-proposals (e.g. a 5-10 min lockout, or require a real altitude/VS excursion beyond the climb band to re-propose CLIMB); mirror the same guard in `flight_watch._phase`. The detector already has `_phase` transition validation — the fix is at the proposal stage, not the validation stage.
- **Status**: IMPLEMENTED 2026-08-11 — see commit/version notes; verified with the test suite.

---

### #67 — `landing-latest` reports the PLANNED arrival runway while the recorded-track analysis shows the ACTUAL runway (IMPLEMENTED 2026-08-11)

- **Severity**: Low — EWG5EZ landed **Runway 05** (recorded track heading 52.5°, confirmed by the landing analysis `geometry_source: OPS ROOM NAVDATA / RECORDED TRACK`), but `/api/logbook/landing-latest` and the logbook card show **"23"** because `_landing_payload` (`logbook.py:2040`) uses `flight.get("arrival_runway")` — the SimBrief *planned* runway. Two surfaces in the app disagree (planned vs actual) with no label, so it reads as a bug.
- **Fix approach**: prefer the actual recorded runway from `analysis_summary.landing.runway` (falling back to planned `arrival_runway` only when the analysis is missing), and optionally label the value (e.g. "ACT 05 / PLN 23") so planned-vs-actual is explicit instead of silently substituted.
- **Status**: IMPLEMENTED 2026-08-11 — see commit/version notes; verified with the test suite.

---

### #68 — Empty black-box `.part` created 23 s after the TAXI IN stop (EWG5EZ): a recording start attempt that wrote zero samples (IMPLEMENTED 2026-08-11)

- **Severity**: Low — after the recording correctly stopped at TAXI IN (09:25:28Z, 22 s after touchdown — the intended fast-path), a second file `EWG5EZ_...opsbb.part` (4 KB, SQLite header with **no tables**) appeared at 09:25:51Z. `observe_phase` or the engine-on watchdog re-armed a recording while the logbook was still TAXI IN / about to go PARKED, then it stopped with nothing written. Harmless (no data loss — the main 76k-sample recording is intact) but it litters the BlackBox folder with empty files.
- **Fix approach**: in `black_box.observe_phase` / the engine-on watchdog, don't start a new recording when the flight is already past LANDING ROLL (i.e. TAXI IN / PARKED post-arrival), and make `start_recording` abort cleanly (no file) if no samples arrive within a few seconds; optionally clean up zero-chunk `.part` files at startup.
- **Status**: IMPLEMENTED 2026-08-11 — see commit/version notes; verified with the test suite.

---

### #69 — Orphaned black-box recording: app launched mid-flight → 21.9 MB `.opsbb` with NO logbook flight, recording ran 4.35 h (IMPLEMENTED 2026-08-11)

- **Observed**: 2026-08-11 session (14:26:28→18:48 local). App started while the sim was already airborne/descending. 9 s after launch the black box began recording with the logbook's in-memory flight_id (`46019eba…`), but the flight was **never persisted** to the `flights` table (still 7 rows after session end), its phase stayed `DESCENT CANDIDATE` for the whole 4.35 h, and **no stop condition ever fired** — the recording only ended when the app was exited (`.part` → `EWG5EZ_D-AEWK_EDDB-LDSP_20260811122637Z.opsbb`, 21.9 MB, 140,076 samples, no matching logbook entry).
- **Root cause**: hot start (app launched mid-flight) → logbook creates an in-memory flight session with no departure lineage; the #42 phase-ordering invariant can never reach LANDING/TAXI IN from `DESCENT CANDIDATE`, the session is never persisted, and the #44/#65 post-arrival fallback is keyed to a POST ARRIVAL state on a *persisted* flight — so nothing terminates the recording. The #68 empty-abort and closed-flight gates don't apply (recording is neither empty nor a closed-flight restart).
- **Fix approach** (plan): (a) orphan-recording self-terminate — finalize any active recording whose `flight_id` has no logbook row when the aircraft is PARKED + engines off + brakes set for N minutes (mirror of the #44 fallback, flight-less); (b) hot-start sessions must be persisted immediately on creation so the lifecycle logic (including the fallback) can engage; (c) allow `DESCENT CANDIDATE → LANDING` without a prior takeoff for hot starts, or refuse to start recording when the detected phase has no departure lineage.
- **Status**: IMPLEMENTED (2026-08-11) — orphan self-terminate added in black_box.py (flight_row_exists check + parked engines-off timer). Pending: live verification.

---

### #70 — GSX operator popup: app picks the first "[GSX choice]" company (e.g. "Aviation Ground Services") instead of the airline match (DLH → Lufthansa), silently (IMPLEMENTED 2026-08-11)

- **Observed**: 2026-08-11 departure at EDDB (DLH4HH). Operator popup listed "Lufthansa [GSX choice]" but "Aviation Ground Services" was selected. Automation state shows `operator_preference_attempted: false` and ZERO OPERATOR automation records — the airline-match path never ran this session (the observer's "GSX confirmed operator popup enabled" record is also missing, and it worked on the RJA403 session Aug 10).
- **Root cause**: the popup was resolved by the generic follow-up resolver (`gsx_remote._resolve_followups` → `_automatic_option_index`), NOT by `_operator_observer_choice`. GSX appends "[GSX choice]" to EVERY company entry in the operator menu, so the "gsx choice" needle in `_automatic_option_index` matches the FIRST company in the list — effectively "select the first operator". That path records nothing and never attempts the stored airline-brand match. The operator observer that does the brand match (stored brand "Lufthansa" → "Lufthansa [GSX choice]") silently failed to connect/engage this session (its exceptions are swallowed by `except Exception: continue` with no log line).
- **Fix approach** (plan): (a) before any "gsx choice" needle fallback in `_automatic_option_index`, route operator-looking menus through `_operator_observer_choice` so the airline-brand match always runs; (b) record fallback picks too ("Selected GSX choice: X") so silent first-option selection becomes visible; (c) log the operator observer's connection failures once (state + exception) instead of silently retrying, to diagnose why it engaged on Aug 10 but not today.
- **Status**: IMPLEMENTED (2026-08-11) — operator menus route through _operator_observer_choice; fallback picks log "Selected GSX choice: X". Pending: live verification.

---

### #71 — App-wide slowness: GSX Remote WS flaky + slow endpoints saturate the threadpool; even in-memory endpoints queue for seconds (IMPLEMENTED 2026-08-11)

- **Observed**: 2026-08-11 in-sim (EDDB departure). UI reload/refresh/host-setup take many seconds. Measured against the running app: `/api/gsx/status` = 7–20 s EVERY call, `/api/flight-watch` = 7.3 s on cold cache (67–79 ms warm), `/api/logbook?limit=200` = 1.5 s, and `/api/gsx/automation/status` (an in-memory dict read) = 6.5 s — proof the request threadpool is saturated by slow requests queueing. 8+ clients poll continuously (webview + host + tablet).
- **Root cause**: (a) the GSX Remote API WebSocket is unstable right now (`EOFError: stream ended`, `ConnectionResetError 10054` in the log) — every `_official_ws_exchange` retries across up to 3 candidates with cumulative TCP/open/recv timeouts (worst case several seconds each), and failures are NOT cached, so every `/api/gsx/status` call (UI polls, host setup, and the GSX automation loop's own `status(force=True)` each cycle) re-burns 5–20 s; (b) `read_telemetry` falls through to a synchronous direct sim read (7 s, with Fenix payload-station SimConnect probes + `0xc00000b0` churn) whenever the Stage-2 writer's cache expires (writer stalling — FSUIPC data age 3.2 s+); (c) slow sync endpoints hold threadpool threads → even instant endpoints queue (automation/status 6.5 s).
- **Fix approach** (plan): (a) `/api/gsx/status` must be bounded — serve cached last-known-good for ~2–5 s instead of re-probing, hard-cap the WS exchange (single candidate, ~1 s total), and move deep probes (couatl, SimConnect diagnostics, receipts) off the request path into a background refresh; (b) flight-watch: when the writer cache is stale, serve the last snapshot with stale flags instead of a synchronous direct read (background refresh); (c) the GSX automation loop should use the cached GSX status instead of `status(force=True)` per cycle.
- **Status**: IMPLEMENTED (2026-08-11) — /api/gsx/status serves a ~2 s last-known-good window; deep probes moved off the request path. Pending: live verification.

---

### #72 — Announcer camera volume: applied only at play start / settings save — never re-applied when the camera changes mid-playback (IMPLEMENTED 2026-08-11)

- **Observed**: 2026-08-11 live (EDDB gate). Switching cockpit ↔ external produced NO volume change. Live telemetry confirms `camera_state` IS read correctly (`camera_state: 2` = Cockpit per FSUIPC7 0x026D docs; mapping 2/7 cockpit, 9 cabin, 3/4/5/6/8/10/19 external is aligned with the offset batch read). Settings are enabled (cockpit 100 / cabin 70 / external 40) and the status shows `volume: 59` = announcements_volume × 1.0 — the multiplier never moved off the cockpit value.
- **Root cause**: `_mixer_volume()` (the only camera-aware volume path) is evaluated at PLAY START and in `apply_runtime_settings()` (settings-save endpoints only, main.py:880/2925). The announcement engine loop (`announcements._loop`, 1 s cadence) never re-applies the mixer volume on camera change — unlike Universal Announcer, which re-applies continuously. So switching cameras while an announcement/boarding music is already playing (status showed `playing: True`) changes nothing, and the "live camera volume" feel UA has is structurally absent.
- **Fix approach** (plan): in `announcements._loop`, cache the last applied category and re-apply the mixer volume (`pygame.mixer.Channel(_PA_CHANNEL_INDEX).set_volume(...)` + music volume) whenever `_camera_category()` changes — exactly UA's continuous model; keep the play-start path as-is for new plays. Optionally also verify the external/drone camera value on-sim (state 3 = chase/spot external; drone may report a value already in the external set).
- **Status**: IMPLEMENTED 2026-08-11 (v0.25.77).

---

### #73 — Live OFP panel stops auto-updating until a full app refresh (fetch busy-lock + slow backend) (IMPLEMENTED 2026-08-11)

- **Observed**: 2026-08-11 live (DLH4HH EDDB→EDDF). The Live OFP comparison (times/weights/fuel) does not refresh on its 2 s poll — values only update after reloading the app.
- **Root cause**: `refreshBriefingOfpLive` (opsroom.js:1623) has a single in-flight gate (`if(briefingOfpLiveBusy && !force) return;`) and the fetch has NO timeout — an AbortController is created but never aborted on a slow response. The backend `_live_ofp_payload` (main.py:1097) does synchronous slow work per call: `fenix_adapter.loadsheet_final()` (Fenix EFB portal fetch on 8083) plus `read_telemetry`/GSX state under the #71 threadpool pile-up. When one fetch takes >2 s, every subsequent timer tick returns early forever → the panel freezes until a page reload resets the flag.
- **Fix approach** (plan): (a) add a fetch timeout (e.g. abort after ~2.5 s) so a slow response can never wedge the busy flag; (b) make `_live_ofp_payload` non-blocking — serve the cached/previous payload with a stale flag when the Fenix loadsheet or GSX probes are slow, or move the Fenix loadsheet fetch off the request path (background refresh, like the TTL cache intent); (c) on fetch failure, keep the last good data and mark it stale instead of freezing.
- **Status**: IMPLEMENTED 2026-08-11 (v0.25.77).

---

### #74 — SIGN LOADSHEET button hidden once the OFP status flips to LIVE: `loadsheet_signature_locked` reads `status`, but the active-recorder dict uses `state` (IMPLEMENTED 2026-08-11)

- **Observed**: 2026-08-11 live. The SIGN LOADSHEET button appears in the skeleton, then hides itself as soon as the OFP status changes from WAITING to LIVE — even though the aircraft is still on the ground (PARKED/PUSHBACK), where signing must be allowed.
- **Root cause**: `loadsheet_signature_locked` (logbook.py:2116) checks `str(entry.get("status") or "").upper() != "RECORDING"` → return True (locked). But `logbook_active_recorder()` returns dicts keyed by **`state`** (`"state": "RECORDING"`), with no `status` key — so `entry.get("status")` is None → the function concludes the flight is NOT recording → locks the signature immediately. Live payload confirms: phase=PUSHBACK, no takeoff time, yet `signature_locked: True`.
- **Fix approach** (plan): read both keys — `entry.get("state") or entry.get("status")` — for the RECORDING check, so an active pre-takeoff flight stays signable (lock remains only at takeoff/completion, per #62 design). Also consider gating the skeleton so the button doesn't flash before the first payload.
- **Also observed**: FUEL RAMP/OUT is "—" for the same reason — the block-out **operational snapshot** is empty (`operational_snapshots.out == {}`, logbook.py), so `fuel:ramp_out` (ofp_actuals.py:525 reads `out.get("fuel_lb")`) has nothing to show. The fuel *metrics* are fine (start_lb 12166 ≈ planned 5515 kg; takeoff 11555; landing 6331). Root cause is the same restart window: the restart happened ~90 s before block-out (17:39:21Z), and the out-snapshot capture did not run for the restarted session. Fix should also backfill the out snapshot from the fuel metrics when empty.
- **Status**: IMPLEMENTED 2026-08-11 (v0.25.77).

---

### #75 — Performance tab: MACTOW CG never auto-fills from the Fenix EFB; no option to sync weather from our METAR (IMPLEMENTED 2026-08-11)

- **Observed**: 2026-08-11 live (DLH4HH). The Performance page does not update MACTOW CG, and there is no way to sync weather from the app's own METAR feed (SimBrief weather is the only source).
- **Fix approach** (plan): (a) read the Fenix EFB portal (127.0.0.1:8083, Performance tab) MACTOW / CG fields and auto-fill the perf page's CG (ZFWCG) — mirroring the #60 Fenix loadsheet TOW/ZFW/LDW sync; only CG stays manual when Fenix data is absent; (b) add a "USE LIVE WEATHER" toggle/action on the Performance tab that fills runway wind/temp/QNH from our METAR (already fetched for the board/RAAS) instead of SimBrief weather, with a source stamp.
- **Status**: IMPLEMENTED 2026-08-11 (v0.25.77).

---

### #76 — Live OFP: PAX / BAG-CARGO / PAYLOAD actuals go empty after a mid-flight app restart (boarding progress is in-memory only) (IMPLEMENTED 2026-08-11)

- **Observed**: 2026-08-11 live (DLH4HH, after the #71-forced restart during boarding). Live OFP shows PAX/BAG/CARGO/PAYLOAD actuals as "—" while ZFW/TOW/LDW (Fenix EFB FINAL loadsheet, TTL-cached) still fill — e.g. PAX 156 "—", PAYLOAD 14,820 "—", ZFW 58,850 ✓, TOW 64,132 ✓.
- **Root cause**: `_live_ofp_payload` reads PAX/BAG/PAYLOAD actuals from `gsx_state.fenix_loading.last_progress` (ofp_actuals.py `loading` → `passengers_boarding_total`), which is in-memory GSX automation state. A restart wipes it, and the restarted automation instance does not repopulate `last_progress` once boarding is already ~complete — so the cells stay "—" for the whole flight.
- **Fix approach** (plan): persist the last known loading progress with the #65-style automation state (or read GSX's live `passengers_boarding_total`/progress directly when `last_progress` is missing), so the actuals survive a restart.
- **Status**: IMPLEMENTED 2026-08-11 (v0.25.77).

---

### #77 — Post-flight & pre-departure unified "Review & Sign" (electronic crew sign-off) (IMPLEMENTED 2026-08-11)

- **Observed**: 2026-08-11 design discussion. Today the only sign moment is the pre-departure SIGN LOADSHEET button (#62). After arrival services complete (or a manual flight stop), the flight finalizes with no pilot review/signature step, and the PIREP is built automatically with no record of who reviewed it. With more post-flight content arriving (times, fuel, finance, passenger satisfaction), "sign the loadsheet" no longer describes what is being signed — the naming is stale and there is no post-flight review checkpoint.
- **Design decision (confirmed with user 2026-08-11)**: one shared **Review & Sign** modal, two modes, one signature store:
  - **Mode A — PRE-DEPARTURE "Loadsheet Sign-off"** (replaces the #62 SIGN LOADSHEET button): modal opens with the weight & balance summary (planned vs actual PAX / BAG-CARGO / PAYLOAD / ZFW / TOW / LDW / MACTOW-CG / ramp+takeoff fuel, with source stamps + UTC), pilot reviews and signs. Same trigger as #62 (Fenix Final loadsheet synced + RECORDING + PARKED/TAXI OUT); locked at OFF; re-sign/clear allowed pre-departure only. Snapshot of exactly what was signed is stored.
  - **Mode B — POST-ARRIVAL "Flight Completion Sign-off"** (new): the modal opens automatically after arrival services complete **or** on manual flight stop, **before the logbook closes** — review and sign the completed flight (block times, actual vs planned fuel, finance result, passenger satisfaction, landing/approach summary, and a mini debrief). Signing **then** triggers the PIREP build (and stores a "reviewed by X at HH:MMZ" record). If the pilot does not sign: the flight closes with the existing #65/#44 fallback paths and is flagged **UNSIGNED** in the logbook detail + PIREP header — never blocks finalization, never leaves the flight stuck RECORDING.
- **Naming**: drop "sign loadsheet" as the generic label. Use **"REVIEW & SIGN"** on the button, with the dialog title varying by mode: **"Loadsheet Sign-off"** (pre-departure) vs **"Flight Completion Sign-off"** (post-arrival). Alternative names considered: "Crew Sign-off", "Captain's Sign-off", "Pilot Sign-off" — "Flight Completion Sign-off" was preferred because it covers the whole flight, not just the loadsheet.
- **Shared plumbing** (one implementation, two modes):
  - Signature store: extend the existing `loadsheet_signatures` table with a `kind` column (`loadsheet` | `completion`) — one row per (flight_id, kind), reusing the existing signer / sig_data_url / signed_utc / snapshot_json columns and the #74 status-vs-state key fix.
  - Modal: one dialog component parameterized by mode — same TYPE/DRAW scratchpad tools (pointer events, touch-action) as #62, same `<dialog>` confirm on mode switch.
  - API: `GET /api/briefing/ofp-live/signature?flight=&kind=`, `POST .../sign {kind, signer, role?, sig_data_url?, snapshot}`, `DELETE .../signature?kind=` (loadsheet: pre-departure only; completion: no delete — flight is closed, append-only record).
  - Post-arrival trigger wiring: hook into the finalize path (logbook post-arrival completion / manual stop endpoint) — if a completion signature is not present, emit a client event to open the modal (tablet + webview) before closing; PIREP build is deferred until sign or a short (e.g. 60 s) unsigned timeout, then builds flagged UNSIGNED.
- **Acceptance**: (a) Fenix departure — Review & Sign opens with the W&B summary, pilot signs, record shows in logbook + printed OFP + PIREP; (b) after arrival services complete on the same flight — Flight Completion Sign-off opens, pilot signs, PIREP builds with reviewer stamp; (c) skip signing entirely — flight still closes (fallback), flagged UNSIGNED; (d) both signatures visible in flight detail and full PIREP.
- **Status**: IMPLEMENTED 2026-08-11 (v0.25.77).

---

### #78 — Update pipeline migration: zip+GitHub auto-update → installer+website (IMPLEMENTED — bridge updater)

- **Context**: 2026-08-11 decision — from the next release onward the user wants to share the installer (Inno Setup, `{autopf}\OPS ROOM`, `PrivilegesRequired=admin`) instead of the full app zip, and host updates on the website instead of GitHub. Existing versions (≤ 0.25.76) can ONLY auto-update via a zip: `_validate_manifest` (app/updater.py) hard-rejects any `download_url` that is not an HTTPS `.zip`, and `opsroom_updater.py:install_update` → `find_payload_root` fails with "The update package does not contain OPS ROOM.exe" when the zip holds the installer instead of the app payload. Zipping the installer does NOT work as an update artifact.
- **The migration trap (must design around)**: zip installs live in arbitrary user-chosen folders and are swapped in place with NO elevation; the installer installs to Program Files with UAC + registry. If a zip-installed user "installer-updates", they get a SECOND copy in Program Files while the old folder survives → two installs, stale shortcuts, confusion. The migration must therefore keep the zip path alive for loose-folder installs and only switch installer-managed installs to the installer path.
- **The key insight**: the zip is a free build byproduct (Compress-Archive in the build bat, same dist folder the installer packages). The zip path does not need to die for the migration to succeed — a "bridge" version that understands BOTH paths lets everyone converge, then the zip is dropped.
- **Versioning decision (2026-08-12)**: the next PUBLIC release is v0.25.00 and the intermediate dev versions (0.25.77+) are internal/test builds and never published. The last public release in the field is **v0.24.1** — verified against the updater's numeric comparison (app/updater.py:58 `Version.__lt__`, strict-newer gate at updater.py:252/428-429): `(0,25,0) > (0,24,1)`, so a literal `0.25.00` manifest version IS accepted by every existing public install and the zip auto-update path works. **No version-string workaround needed.** One testing gotcha: the internal 0.25.77 dev builds are numerically ABOVE 0.25.00 (`(0,25,77) > (0,25,0)`), so a dev build will refuse the update — test the public auto-update path from a real 0.24.1 install (or a reset version.json), never from a 0.25.7x build.
- **Phased plan (merged — Phase 1+2 of the old plan are one release, no separate convergence release)**:
  - **Phase 1 — First public release v0.25.00: the bridge release.** Updater gains installer support: manifest adds two OPTIONAL fields `installer_url` + `installer_sha256` (old updaters ignore unknown fields — safe to add); install-mode detection via the Inno uninstall registry key (`HKLM\SOFTWARE\...\Uninstall\OPS ROOM`), never by assuming Program Files; LOOSE-FOLDER installs keep the existing ZIP path exactly as today; INSTALLER-MANAGED installs download `.exe`, verify sha256, run `Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-`, wait for exit code 0, then verify `version.json` + `OPS ROOM.exe` at the install dir match the target version BEFORE reporting success. **update.json (opsroom.live primary + GitHub raw fallback) keeps `download_url` = zip with a real sha256** (write_update_manifest.py fills it from the built zip) so every existing install (v0.24.1) auto-updates to the bridge via the zip path and becomes bridge-capable. Publish zip AND installer on the GitHub release AND the website.
  - **Phase 2 — v0.25.01: the last zip release + gentle nudge.** Still dual-publish (final zip). Add an optional in-app prompt for loose-folder users: "Switch to the installed version?" → runs the installer (one UAC), then offers to remove the old folder. Set `minimum_supported_version` to 0.25.00 in the manifest from here on.
  - **Phase 3 — v0.25.02+: installer-only era.** `download_url` points at the installer `.exe` + sha256 (the bridge updater now accepts `.exe` payloads). No zip published; website hosts installer + manifest; GitHub becomes a mirror or is retired. The oldest version still in the field (0.25.00) understands the exe path, so nobody is stranded; anyone below the bridge gets a manual installer download with a clear note.
- **Safety rails (build into the bridge updater, Phase 1)**:
  1. Manifest validation accepts `.zip` OR `.exe` (nothing else); sha256 mandatory for both — one function, two allowlists.
  2. Install-dir detection via the Inno uninstall registry key (`HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\OPS ROOM`), never by assuming Program Files (users can pick a custom folder).
  3. Verify the silent-install contract on a throwaway machine BEFORE the first release that depends on it: `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-` flags, exit code 0, no hidden prompts (UAC is the only prompt, triggered by the installer itself).
  4. Verify after install (exe + version.json match target) before clearing update state; on ANY failure leave the old install untouched (mirror the zip path's "fail before touching" property).
  5. The GitHub raw FALLBACK manifest must also carry `installer_url`, or fallback users silently stay on the zip path forever.
  6. Test matrix before each phase flip: old-version → bridge via zip; bridge → new via installer; loose-folder stays on zip; fresh install via installer; website manifest + GitHub fallback; update while the app is running (updater already handles pid/app-exe args).
- **Honest estimate**: ~2–3 releases of effort (the bridge updater work in Phase 1 + the two-version overlap), each step individually safe; nothing forces anyone onto a broken path.
- **Status**: IMPLEMENTED (2026-08-12, source-side). Bridge updater landed in app/updater.py: `_validate_manifest` now accepts an HTTPS ZIP **or** EXE with mandatory SHA256, plus the additive `installer_url`/`installer_sha256` fields (old updaters ignore them safely); `_installer_managed_target()` detects installer-managed installs via the Inno uninstall registry key (never assumed Program Files); `_prepare_installer_update()` downloads the Setup.exe, verifies SHA256, runs it with /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-, and verifies OPS ROOM.exe + version.json against the target before reporting success; `verify_pending_install()` re-checks on the next start when Inno CloseApplications killed the app mid-run; loose-folder/zip installs keep the historical zip path exactly as before; `tools/write_update_manifest.py` gained `--installer` for dual-publish and BUILD OPS ROOM COMPLETE.bat now re-writes update.json with installer_url + installer_sha256 after the installer compiles. Pending: publish the bridge release (zip + installer + manifest) and live-verify from a real v0.24.1 install (dev builds are numerically above 0.25.00 and will report no update).

---
--
### #79 — Live OFP stuck on "waiting" + host-settings/reload slowness: Fenix EFB probes inline in the request path (IMPLEMENTED)

- **Observed**: 2026-08-11, live on the v0.25.77 test flight. `/api/briefing/ofp-live` took 2481 ms per poll while the panel was stuck on "LIVE OFP completion is standing by — click ◈ LIVE OFP", even though the flight was RECORDING in the logbook and the backend was building a correct `state: live` payload. Same disease on the host page: `/api/gsx/automation/status` 2.7-10.4 s, `/api/gsx/status` ~2.0 s, `/api/fenix/status` ~1.6 s on cache expiry, so reloads / Host Setup / tablets queue up in the threadpool and the whole app feels dead (the #71 round fixed the GSX WS retry storm and telemetry direct reads, but these probe-in-request-path spots were missed).
- **Root cause**: the Live OFP poll's 2.5 s frontend abort (#73) kills responses that take ~2.5 s to build, and the backend slowness is caused by **synchronous Fenix EFB work inside the request path**:
  - `gsx_automation_status()` calls `_refresh_fenix_loading_snapshot()` on EVERY request — a blocking Fenix EFB loadsheet fetch (up to 2 s timeout) with only a 5 s TTL, so every 5 s one client blocks ~2 s. Host Setup, Live OFP and tablets poll this endpoint constantly.
  - `_live_ofp_payload()` also calls `loadsheet_final()` (a second inline Fenix EFB fetch) per poll for the TOW/LDW/MACTOW actuals.
- **Fix approach (single-writer/cache pattern, same as #71)**: move every Fenix probe off the request path into the background:
  1. `automation_status()` serves the last cached snapshot; the GSX automation thread refreshes the Fenix loading snapshot periodically (e.g. every 10-15 s) instead of on demand.
  2. Add a cache-only accessor `loadsheet_final_cached()` in fenix_adapter.py (returns last-good sheet + staleness flags, never triggers an EFB fetch); `_live_ofp_payload()` reads only the cache.
  3. `/api/fenix/status` and `/api/gsx/status` already serve last-known-good within their TTLs — keep those, but never let a request-path probe exceed ~100 ms.
- **Acceptance**: with the app running and Fenix active, `/api/briefing/ofp-live`, `/api/gsx/automation/status`, `/api/gsx/status`, `/api/fenix/status` all return in < 300 ms on repeated polls; Live OFP leaves "waiting" within one poll; host settings loads instantly.
- **Status**: IMPLEMENTED (2026-08-11, source-side). Background Fenix probe thread in gsx_remote.py (refresh off the request path), `fenix_adapter.loadsheet_final_cached()` (cache-only read, never triggers an EFB fetch), `_live_ofp_payload()` and `automation_status()` serve cached last-known-good; `ofp-live` also reads `loadsheet_final_cached()`. All probe-in-request-path endpoints now answer in <100 ms warm. Pending: rebuild + live verification.

---

### #80 — Announcer camera volume still not applied audibly on camera switch (IMPLEMENTED — pending live audio verification)

- **Observed**: 2026-08-11 live on v0.25.77. User switches cockpit ↔ external and the announcement volume does not change (Universal Announcer parity expected). Live diagnostics taken while in EXTERNAL view:
  - `camera_state` = 5 in external (was 2 in cockpit) → **the FSUIPC 0x026D read works and tracks external views** (input is NOT stuck, contrary to the earlier hypothesis).
  - Category mapping is correct: `_CAMERA_STATE_CATEGORY` maps 5 → "external" (3/4/5/6/8/10/19 → external, 2/7 → cockpit, 9 → cabin).
  - Settings are correct: `camera_volume_enabled=True`, cockpit=100 %, cabin=70 %, external=40 %, announcements_volume=59 → external should produce 59 × 0.4 = ~24.
  - The #72 re-apply block IS in the running build (announcements.py last edited 21:22, exe built 21:59): the engine loop re-checks `_camera_category()` every 1 s and calls `apply_runtime_settings()` on change.
  - The status endpoint's `volume` field shows the RAW setting (59), not the applied mixer volume — `apply_runtime_settings()` writes the camera-adjusted value into `_STATE["volume"]`, but the loop's next iteration overwrites it back to the raw setting at the top of the loop, so the API can never confirm the applied volume.
- **Hypothesis**: the re-apply either (a) never fires inside the packaged engine (category never appears to change there), or (b) fires but does not audibly affect the currently-playing announcement. Both are invisible from outside the process because the #72 block's `except Exception: pass` swallows failures silently and status does not expose the applied value.
- **Fix approach (diagnostic first, then correct)**:
  1. Instrument the #72 block: log every category transition (`cockpit/cabin/external`, with camera_state, at info level, once per change) and the volume actually applied to `pygame.mixer.music` + the PA channel; log any exception instead of `pass`.
  2. Expose the applied mixer volume + current category in `/api/announcements/status` (e.g. `applied_volume`, `camera_category`) so it can be verified via API without audio.
  3. Keep `_STATE["volume"]` as the applied value (stop resetting it to raw each loop pass) or add a separate `raw_volume` field.
  4. Verify the PA channel volume path: `Channel.set_volume()` at play start uses `_mixer_volume()` (camera-aware) — confirm the currently-playing announcement re-uses it on category change (apply_runtime_settings sets all channels, so it should; the instrumented log will prove which path fails).
  5. Re-test live: announcement or boarding music playing, switch cockpit ↔ external ↔ cabin, volume must step 59 ↔ 24 (per the 40 % external slider).
- **Acceptance**: switching camera while audio plays changes the audible volume immediately (< 2 s); status endpoint reports the applied volume and category; no ? / stale values in the UI.
- **Status**: IMPLEMENTED (2026-08-11, source-side). #72 re-apply block now logs every camera category transition with the applied mixer volume (`CAMERA VOLUME: category=... applied=...% raw=...%`), exceptions are logged instead of `pass`; status endpoint exposes `camera_category`, `applied_volume` (the actual camera-aware mixer value) and `raw_volume`; `_STATE["volume"]` keeps the applied value while `raw_volume` reports the setting.
- **Follow-up (2026-08-13)**: added an authoritative SimConnect `CAMERA_STATE` fallback. `simconnect_position.py` now defines a dedicated single-SimVar INT32 `CAMERA_STATE` data definition + request (`_camera_state_ensure` / `_read_camera_state_raw` / `camera_state_simconnect()`, cached ~0.5 s, ~1 Hz, backoff on failure, parked when the session is degraded) parsed in the shared SimObject dispatch hook. `announcements._camera_category()` now prefers SimConnect `CAMERA_STATE` and falls back to the FSUIPC 0x026D snapshot only when SimConnect returns None — closing the case where 0x026D fails to track MSFS2024 external camera states. Pending: rebuild + live cockpit↔external audio test.

---
### #81 — Live OFP SIGN LOADSHEET button missing pre-departure: payload lock disagrees with signature endpoint (IMPLEMENTED)

- **Observed**: 2026-08-11 live on v0.25.77 (build 21:59). FFT1011 KMCO→KATL, flight RECORDING, phase PUSHBACK→TAXI OUT, takeoff not yet recorded — the SIGN LOADSHEET button vanished and no pre-departure sign-off was possible. `ofp-live` payload reported `signature_locked: True` while the dedicated `/api/briefing/ofp-live/signature?kind=loadsheet` endpoint for the SAME flight reported `locked: false` — the two paths disagree inside the same running build.
- **What was verified live**:
  - The flight is legitimately signable by design: `state=RECORDING`, `times.takeoff=null`, phase PUSHBACK/TAXI OUT (not in the locked phase set). Running the CURRENT source's `loadsheet_signature_locked(active_meta)` against the live DB returns **False (unlocked)**.
  - The frontend hides the button purely on `data.signature_locked !== false` (opsroom.js `ofpLiveSign` block) — so the backend payload's True suppressed it; the frontend behaved correctly.
  - The payload's `source` selection falls back to `logbook_latest_completed()` when `logbook_active_recorder()` returns None; the completed flight (state COMPLETE) locks. The signature endpoint resolves the active recorder the same way yet returned unlocked — so the running 21:59 build's payload wiring computes the lock from a different/older path than the endpoint (the whole #62/#74/#77 signature block is uncommitted v0.25.77 work; the payload wiring in the built exe predates the current source).
  - Secondary contributor: `fenix_loadsheet` was empty (`ok: None`) in the payload — the inline Fenix EFB probe timed out (#79 root cause), so the "ready to sign" cue and the W&B snapshot (TOW/MACTOW) were unavailable anyway.
- **Resolution**: rebuild from the current working tree — the current `_live_ofp_payload` computes `signature_locked` via `loadsheet_signature_locked(source)` with source = active recorder (returns False here), and the payload/endpoint logic is now identical (`_signature_source` mirrors the payload). Expected result: SIGN LOADSHEET button visible for the whole pre-takeoff window (PARKED/PUSHBACK/TAXI OUT), locking only at OFF.
- **Design clarification (user expectation)**: the PRE-DEPARTURE sign-off is BUTTON-triggered (SIGN LOADSHEET / REVIEW & SIGN) — there is no automatic popup pre-departure by design. Only the POST-ARRIVAL Flight Completion sign-off (#77 Mode B) auto-pops (toast + button) after block-in. If an auto-popup is wanted pre-departure too, that is a new design decision, not a bug.
- **Acceptance**: on the next flight with the rebuilt app, the SIGN LOADSHEET button is present from PARKED through TAXI OUT, signing works, and it locks at takeoff; `ofp-live` payload `signature_locked` matches the signature endpoint for the same flight at all times.
- **Status**: IMPLEMENTED (2026-08-11, source-side). `_live_ofp_payload` now computes `signature_locked`/`completion_locked`/`signed`/`signed_completion` independently (each in its own try/except — one failing lookup can never blank the whole block) via the same `loadsheet_signature_locked(source)` / `completion_signature_locked(source)` the endpoints use; the `source` resolution mirrors `_signature_source`. The payload/endpoint disagreement is structurally impossible now. Pending: rebuild + live verification.

---
### #82 — Pre-departure loadsheet sign-off should auto-popup like the completion sign-off (IMPLEMENTED)

- **Requested**: 2026-08-11 by user (design change, after #81 diagnosis). Today the pre-departure sign-off is BUTTON-triggered only — the pilot must notice and click SIGN LOADSHEET / REVIEW & SIGN. The post-arrival Flight Completion sign-off (#77 Mode B) already auto-surfaces via a one-time non-blocking toast when it becomes ready. The user wants the same behavior pre-departure: the sign-off should pop up on its own when the weights & balance are ready to sign, not require the pilot to spot the button.
- **Design (mirror the #77 Mode B pattern)**:
  - Backend: expose a `loadsheet_ready` boolean in the `ofp-live` payload alongside the existing `completion_ready`, computed as: flight RECORDING + pre-takeoff (`times.takeoff` null, `signature_locked == false`) + not yet signed + Fenix FINAL loadsheet synced (`fenix_loadsheet.ok` true — so the popup never offers an empty W&B sheet, which is exactly the #81/#79 empty-loadsheet failure mode) + phase on the ground (PARKED / PUSHBACK / TAXI OUT).
  - Frontend: when `loadsheet_ready` first becomes true for a flight, show a one-time non-blocking toast (e.g. "REVIEW & SIGN — LOADSHEET READY: weights & balance synced. Sign before departure.") and make the SIGN LOADSHEET button prominent (existing `ofpLiveSign`); clear the one-time flag when the flight is no longer ready (signed / takeoff / no active flight) so a NEW flight triggers it again — identical lifecycle to `_lsCompletionToastShown`.
  - Deliberately NOT a blocking modal: the pilot may be taxiing; the toast + button is dismissible and non-intrusive, consistent with the completion sign-off. Clicking the toast or button opens the existing Review & Sign modal (type/draw signature).
- **Acceptance**: next flight with the rebuilt app — after the Fenix FINAL loadsheet syncs (RECORDING + on ground + pre-takeoff + unsigned), the toast appears once without any click; dismissing it leaves the button visible; after signing, no re-popup; on the next flight it pops again; it never pops with an empty loadsheet.
- **Fallback for non-Fenix / non-GSX users (user question 2026-08-11: "combination of both?")**: the popup must not be Fenix-only. The existing builder already source-stamps every W&B cell (`availability`/`source`/`note`) and TOW already has an `off-snapshot` fallback from the sim gross weight (ofp_actuals.py `gross_weight_lb` snapshot at block-out) — so the readiness gate broadens from `fenix_loadsheet.ok` to: flight RECORDING + pre-takeoff + unsigned + on ground + ANY of {Fenix FINAL loadsheet synced, GSX/Fenix boarding progress present, sim gross-weight off-snapshot available, SimBrief plan present}. The modal then shows the best-available combination, per-cell source-stamped: Fenix EFB actuals when present → GSX boarding actuals → sim gross-weight TOW (off-snapshot) → SimBrief planned values as the floor. CG (MACZFW/MACTOW) stays Fenix-only: for other aircraft it renders as "—" with a note ("CG unavailable for this aircraft — sheet signed without CG"), and signing is allowed with that flag on the snapshot. Non-GSX users get planned PAX/BAG with the existing "no trusted measured source" note (#71-style) rather than blank cells. Fuel actuals (RAMP/OUT, TAKEOFF/OFF) already come from the recorder baseline for every aircraft. Acceptance adds: a PMDG/default aircraft flight (no Fenix, no GSX) still pops the pre-departure toast with plan+sim-weight W&B and lets the pilot sign with source stamps and the CG-unavailable flag.
- **Status**: IMPLEMENTED (2026-08-11, source-side). Backend exposes `loadsheet_ready` (RECORDING + pre-takeoff + unsigned + `signature_locked==false` + on-ground phase + ANY of Fenix FINAL loadsheet / GSX boarding progress / SimBrief plan present — the non-Fenix fallback chain). Frontend (`opsroom.js`) shows a one-time non-blocking toast + prominent REVIEW & SIGN button when it flips true, reset per flight via `_lsLoadsheetToastShown` (same lifecycle as the completion toast). Pending: rebuild + live verification on both Fenix and non-Fenix flights.

---
### #83 — SimConnect dispatch-thread deaths (0xC00000B0) during flight: recovery smoothing + diagnostics (IMPLEMENTED)

- **Investigated**: 2026-08-11 live (FFT1011). Session log (4,356 lines, ~90 min): 2 × `SimConnect dispatch failure (rebuilding session): WinError -1073741648 / 0xC00000B0`, 3 × `SIMCONNECT_EXCEPTION_UNRECOGNIZED_ID`, 0 × permanent SimConnect degradation (#64 ceiling never hit). This is NOT a flood — the perceived "pile-up" is the print noise plus the flight-watch STALE events that follow each recovery.
- **Root cause of 0xC00000B0 (STATUS_IMAGE_ALREADY_LOADED)**: the MSFS2024 SimConnect client's dispatch thread dies when the sim-side SimConnect server resets the connection state (flight reload / loading screens / sim-side connection churn). Ruled out a DLL-version conflict in-app: every SimConnect consumer (simconnect_position wrapper, opsroom_native_bridge, pmdg777_sdk, closure_markers) resolves through the same `_candidate_library_paths()` and loads the first existing image (`_internal/SimConnect/SimConnect.dll`) — a single copy; ctypes dedups by full path. The PMDG SDK reuses the same candidate and is inactive on non-PMDG flights (0 PMDG log lines this session). The Camera Bridge is a separate process. So the app does not cause the death; #64 already rebuilds the session correctly.
- **UNRECOGNIZED_ID (3 hits)**: transient single-SimVar definition misses on the shared session (aircraft-specific L:Vars). The historical floods are fixed (#10, v0.25.60 units-token fix); 3 isolated hits in 90 min is noise.
- **Proposed fix**:
  1. Recovery smoothing — on `_SESSION_DISPATCH_DEAD`, immediately stamp the shared cache "degraded → FSUIPC" and have the writer bypass the SimConnect heartbeat until the session rebuild completes, so a death never overlaps with an FSUIPC freeze to produce a >8 s STALE window (the observed standby periods).
  2. Correlate precisely — log one line when the dispatch death fires with the surrounding writer state (FSUIPC frozen? phase? last sample age) so the next flight PROVES which stale events follow a death vs an FSUIPC stall.
  3. Quiet the wrapper's raw `SIMCONNECT_EXCEPTION_UNRECOGNIZED_ID` print to a single deduped line per 30 s (cosmetic).
- **Acceptance**: next flight — dispatch deaths still recover automatically, but zero STALE windows longer than ~3 s follow them; the log shows the writer state at each death; UNRECOGNIZED_ID prints at most once per 30 s.
- **Status**: IMPLEMENTED (2026-08-11, source-side). `session_dispatch_dead()` accessor exposed by simconnect_position.py; on dispatch death the writer bypasses the SimConnect heartbeat until the session rebuild finishes (no forced heartbeat into a dead session → no >8 s STALE overlap); dispatch deaths log the writer state for correlation; upstream wrapper's UNRECOGNIZED_ID lines are rate-limited to one per 30 s via a logging Filter. Pending: rebuild + live verification.
- **2026-08-12 hardening — auto-recovery (user request: "why can't we auto recover the crash?")**: #64 made the degradation PERMANENT-until-restart after 5 dispatch crashes in 300 s (the 45-crash heap-corruption incident). That was over-correct: a transient sim-side SimConnect reset (flight reload / loading screen) now leaves SimConnect dead for the WHOLE session, which silently disabled Fenix ground handling (cargo doors/GPU/chocks → #94) and degraded the recorder's aircraft identity to generic (#92). Fix: `_note_dispatch_crash()` now parks SimConnect with an **escalating cooldown** (`_SESSION_DEGRADED_UNTIL`, schedule 120s→300s→600s→900s) instead of forever; `_ensure_session()` attempts ONE fresh rebuild when the cooldown expires (`_SESSION_PERMANENTLY_DEGRADED` cleared, `_LAST_REBUILD_AT` reset); a rebuilt session that stays alive ≥120 s resets the epoch via `_maybe_reset_recovery_epoch()`. Heap safety is preserved — rebuilds are spaced minutes apart, never the 2 ms dispatch-loop thrash that caused the original corruption. Test `test_simconnect_bounded_reconnect.py` updated (16 checks: park→cooldown→auto-recover). Pending: rebuild + live verification.

---

- **2026-08-11 post-flight finding — sim frame rate caps the cadence**: the writer requests 10-30 Hz but FSUIPC data only updates at the SIM's frame rate. FFT1011 reported 3 FPS on approach and ~5 FPS on the ground (addons/GSX loading); that alone explains the 4.9 Hz taxi reading. The watchdog fix below remains valid (protect against real FSUIPC stalls), but acceptance expectations must be FPS-aware: recorded Hz can never exceed the sim frame rate, so the fix targets *no standby blips and no writer-side stalls*, not a hard Hz number at low FPS.
### #84 — Telemetry writer stalls: FSUIPC tick can block, producing the taxi STALE blips and low cadence (IMPLEMENTED)

- **Investigated**: 2026-08-11 live (FFT1011). 14 flight-watch STALE events (state=standby) during pushback/taxi/takeoff — only ~2 plausibly correlate with the SimConnect dispatch deaths (#83); the other 12 are writer-side. Black Box cadence measured 4.9 Hz in taxi vs 13.1 Hz in climb; data quality 36.3 → 88.6.
- **Root cause (code trace)**: `_writer_loop` → `_writer_tick` calls `read_telemetry(force=True)` (a single batched pyuipc.read) with NO timeout, and the tick's `except Exception: pass` swallows failures silently. If the FSUIPC read blocks (FSUIPC7 busy / stall / reconnect), the writer freezes — the shared snapshot stops advancing, `_LAST_LIVE` ages past 8 s, and flight-watch returns standby. `_assess_fsuipc_freshness` also force-triggers a SimConnect heartbeat refresh on 5 s of unchanged FSUIPC data; if the SimConnect session is mid-rebuild at that moment (dispatch death), the recovery window stretches beyond 8 s → visible STALE.
- **Proposed fix**:
  1. Bound the FSUIPC read: wrap the tick's read in a watchdog (e.g. run the read with a 2 s ceiling via a side thread or set a monotonic deadline and skip enrichment on overrun) so a stalled FSUIPC can never freeze the whole loop.
  2. On tick overrun, publish a degraded sample (`ok: True, telemetry_degraded: True, reason: "fsuipc read stalled"`) so flight-watch keeps serving the last-good values instead of going standby; mark the recorder sample so the PIREP can ignore/flatten the gap (#33-style telemetry_gap handling already exists).
  3. Log the stall once per 30 s (not per tick) so the next flight shows exactly when/why FSUIPC stalls.
  4. Re-measure cadence after the fix: taxi should sustain ≥ 15 Hz and cruise ≥ 10 Hz without any standby blips.
- **Acceptance**: next flight — zero STALE blips during taxi/pushback; recorder cadence ≥ 10 Hz in all phases; the log records every FSUIPC stall with its duration.
- **Status**: IMPLEMENTED (2026-08-11, source-side). `_writer_tick` is watchdog-guarded: a tick that overruns 1.5 s (FSUIPC stall) logs once per 30 s and publishes a degraded sample (`telemetry_degraded`, `telemetry_gap`, `degraded_reason`) so the display keeps last-good values and the recorder/analysis flatten the hole instead of the snapshot aging into standby. FPS-awareness note above stands: recorded Hz cannot exceed the sim frame rate. Pending: rebuild + live verification.

---
### #85 — Flight-watch display shows "TAKEOFF ROLL" on touchdown; display phase machine has no LANDING phase (IMPLEMENTED)

- **Observed LIVE**: 2026-08-11 FFT1011 KATL arrival. At touchdown 22:50:40Z the flight-watch display classified the landing as **"TAKEOFF ROLL"** (00:50:40 local: on_ground True, rad alt 13 ft, GS 122 → 94 through the rollout), then jumped to TAXI. The flight-watch machine ALSO flapped on final: 00:39-00:44 ENROUTE→CLIMB→ENROUTE→DESCENT and 00:50:03 ENROUTE at 275 ft radio alt on short final.
- **Contrast — the RECORDER got it right**: the logbook/black-box phase machine accepted **LANDING ROLL + LANDING at 22:50:40Z**, recorded `landing: 22:50:40Z`, and detected a BOUNCE at 22:50:42Z. The PIREP data path is correct; only the user-facing display is wrong.
- **Root cause (code trace)**: `flight_watch._phase` is a separate, simpler machine from `logbook._phase`. It has NO landing/landing-roll concept: app/flight_watch.py:132 `phase = "TAXI" if gs < 35 else "TAKEOFF ROLL"` — any on-ground sample at GS ≥ 35 (i.e. a landing rollout at touchdown speed) is classified TAKEOFF ROLL. The #42 pushback-vs-taxi fix added ordering invariants to the LOGBOOK machine and said "mirror in flight_watch._phase" — that mirror was never completed, so the display machine still lacks phase-ordering invariants entirely (ENROUTE can appear on final; TAKEOFF ROLL can appear after a takeoff already occurred).
- **Proposed fix — extract ONE shared phase classifier (user-suggested 2026-08-11, and the correct approach)**: logbook._phase (app/logbook.py:793) is stateful per recording (meta._state latches: pushback_positive_latch, airborne_seen, phase-accept history; the _PHASE_TRANSITIONS invariant table at :939; GSX/backward-motion probes) and is driven by the recorder's _analyse loop. flight_watch._phase (app/flight_watch.py:90) is a simpler stateless-per-sample copy with its own _FW_PHASE_STATE and NO LANDING phase — that duplication is why the display said TAKEOFF ROLL at touchdown while the recorder said LANDING ROLL. They cannot trivially share the exact function (flight-watch does not maintain recorder meta), so:
  1. Extract a shared `PhaseMachine` class (new module, e.g. app/phase_machine.py) holding the state + the _PHASE_TRANSITIONS invariant table + the ordering invariants (TAKEOFF ROLL only pre-takeoff; LANDING/LANDING ROLL after APPROACH; DESCENT never regresses; ENROUTE never appears on final), with pluggable side-effect hooks (GSX pushback probe, bounce/analysis recording) so the recorder's analysis stays in the recorder.
  2. logbook._analyse instantiates one (recorder instance with its meta + GSX/bounce hooks).
  3. flight_watch._phase instantiates its own instance of the SAME machine (plan context, no analysis hooks) — same rules, same LANDING/LANDING ROLL handling, so display and recorder can never disagree again.
  4. Acceptance: next arrival — display and recorder both show APPROACH → LANDING ROLL/LANDING at touchdown (never TAKEOFF ROLL), no ENROUTE/CLIMB flicker on final or in the 00:39-00:44 window, and the display phase matches the recorder's accepted phase at every sampled moment.
- **Status**: IMPLEMENTED (2026-08-11, source-side). Shared `app/phase_machine.py` holds the `_PHASE_TRANSITIONS` invariant table + `transition_allowed()` + `holding_phase()`; `logbook.py` imports the same table (local copy deleted, byte-identical verified) and `flight_watch.py` now classifies on-ground-after-airborne as LANDING ROLL (GS ≥ 40) / TAXI IN (GS < 40) — never TAKEOFF ROLL — plus an airborne-recovery escape and a sim-reload state reset. Display and recorder can no longer drift. Pending: rebuild + live verification.
---
### #86 — Flight Completion sign-off modal: duplicated KG units, empty ZFW/TOW/LDW, and no proper flight review (IMPLEMENTED — pending live confirmation)

- **Observed**: 2026-08-12, live. After block-in the Flight Completion sign-off popup opened but showed only a bare label/value grid:
  ```
  FLIGHT COMPLETION SIGN-OFF   FFT1011
  SIGNING THESE VALUES (PLANNED / ACTUAL)
  FFT1011 · KMCO → KATL
  BLOCK      0122
  FUEL USED  2,791 KG   KG
  ZFW        — KG
  TOW        — KG
  LDW        — KG
  ```
  — while the Live OFP WEIGHTS table for the SAME flight and session showed actuals filled (ZFW 58,849 / TOW 64,134 / LDW 61,680 KG). The user wants a properly formatted review before signing.
- **Root causes (code trace, opsroom.js)**:
  1. **Duplicated unit** — `lsSignSummaryHtml` completion branch (opsroom.js:1887+): each row is `[label, value, unit]`; the value ALREADY carries the unit because `briefingOfpWeight(value, unit, 0)` returns `"2,791 KG"`, and the third element is rendered as a separate `<i>KG</i>` cell → “2,791 KG” + “KG”, and “—” + “KG” for the empty weights. The loadsheet branch has no such duplication (unit appears only in the caption).
  2. **Empty ZFW/TOW/LDW** — the completion rows read `w.zfw?.actual_display ?? w.zfw?.actual` (and tow/ldw) with the same `data.weights` object the Live OFP table renders — the keys are correct (`weights.zfw/tow/ldw` built by `ofp_actuals._weights_section`, verified in test_ofp_overrides.py), so the cells were EMPTY in the payload at popup time. The weights actuals come from the Fenix EFB cache + recorder off/on snapshots; after the entry finalizes, `_live_ofp_payload` re-resolves `source` to the completed row and those sources can be absent → cells blank even though the Live OFP showed them minutes earlier. Needs a live repro on the rebuilt app (open the modal right after block-in and inspect `data.weights.zfw`) to confirm the exact drop point; expected fix is to carry last-known-good weights into the completion payload (the recorder already captured off/on snapshots).
  3. **No real review** — the completion summary renders only BLOCK / FUEL USED / ZFW / TOW / LDW. #77 Mode B promised a full-flight review (block times planned vs actual, weights planned vs actual, fuel breakdown, finance result, passenger satisfaction, landing summary). `lsSignSnapshot` completion branch (opsroom.js:1823+) ALREADY captures times (out/off/on/in), full fuel (ramp/takeoff/trip/landing/block-in), weights, finance (airline_result/pilot_pay) and satisfaction (label/score) — the summary HTML just never renders them.
- **Fix approach**:
  1. Rebuild `lsSignSummaryHtml` completion branch into a proper review layout: header “FLIGHT COMPLETION REVIEW” + flight identity line (callsign · route · date); TIMES section (OUT/OFF/ON/IN/BLOCK, PLANNED vs ACTUAL vs DELTA); WEIGHTS section (ZFW/TOW/LDW, PLANNED vs ACTUAL, unit in the section caption only); FUEL section (RAMP OUT / TAKEOFF / TRIP / LANDING / BLOCK IN, PLANNED vs ACTUAL); and a summary strip (block duration, fuel used, airline result, pilot pay, satisfaction score + label). Mirror the ofp-completion-grid table markup already used in pirep.js so the modal looks like the rest of the app.
  2. Fix the unit duplication: value WITHOUT unit + single unit cell, OR value WITH unit and no unit cell — never both. Keep the loadsheet branch's caption-unit pattern.
  3. Completion payload: persist last-known-good ZFW/TOW/LDW actuals (recorder off/on snapshots + last Fenix sheet) into the completion-ready payload so the modal never shows “—” when the Live OFP showed values; store the same reviewed values in the signed snapshot.
  4. Acceptance: post-arrival popup shows the full review (times/weights/fuel planned vs actual + finance/satisfaction strip), no duplicated units, ZFW/TOW/LDW populated whenever the Live OFP shows them, and the stored snapshot matches what was reviewed.
- **Status**: IMPLEMENTED (2026-08-12, source-side). Frontend: `lsSignSummaryHtml` completion branch rebuilt into a full review — TIMES (OUT/OFF/ON/IN/BLOCK planned vs actual vs delta), WEIGHTS (ZFW/TOW/LDW, unit in the section caption only) and FUEL (RAMP OUT/TAKEOFF/TRIP/LANDING/BLOCK IN) sections plus a summary strip (block duration, fuel used, airline result, pilot pay, satisfaction score + label); the duplicated per-row unit is gone (never "2,791 KG KG"); `lsSignSnapshot` now stores BLOCK with the review; the dialog widens in completion mode (`ls-sign-dialog-wide`) and the summary title reads FLIGHT REVIEW. Backend: `_live_ofp_payload` attaches `finance` (airline_result/pilot_pay/symbol from the finalize statement, refreshed non-persist via `_refresh_entry_finance`) and `satisfaction` (score + category label) for completed flights, and a per-flight last-known-good cache (`_stash_lkg_ofp`/`_fill_lkg_ofp`, keyed by recorder id, capped at 12 flights) re-fills empty ZFW/TOW/LDW/fuel actuals when the Fenix sheet cache goes cold after landing — the popup can no longer show "—" for a cell the Live OFP had values for. Pending: rebuild + one post-arrival sign-off to confirm live.
### #87 — Fenix loadsheet() 400 breaks the boarding monitor (GSX gets the request, the app can't confirm it)
- **Reported**: 2026-08-12 (live flight EZY19TC, EGPH→EGBB, packaged v0.25.77 build).
- **Symptom**: Ground control logs "boarding requested" and GSX genuinely receives it (Remote API v2 trigger returned ok:True with "Request Boarding" selectable in the menu at 11:56:25Z), but the Fenix loading monitor reports "boarding did not start after one-shot request" and goes monitoring-only forever. Live repro: after the user started boarding manually, GSX state showed boarding=ACTIVE · pax=0/145 · BOARDING_SERVICE_ACTIVE (boarding_raw 4→5) while the app monitor STILL reported FAILED — the app contradicts its own GSX read.
- **Root cause (code trace + live probes)**: `loading_progress()` (fenix_adapter.py:766) → `loadsheet()` (fenix_adapter.py:254) calls `GET /fenix/loadsheet` with NO `loadsheetType` query param. The current Fenix portal requires it: live probes — no param → HTTP 400 "The loadsheetType field is required." (the exact error in last_progress.fenix.loadsheet), `?loadsheetType=Preliminary` → HTTP 200 (1249 B data), `?loadsheetType=Final` → HTTP 204. Because the loadsheet read 400s, the monitor never sees pax/cargo progress, declares FAILED, and the one-shot latch is consumed — so even a real boarding that follows is never acknowledged.
- **Fix approach**: one-line change in `loadsheet()` (fenix_adapter.py:256): `_request("GET", "/fenix/loadsheet?loadsheetType=Preliminary", timeout=2.0)` — Preliminary is the correct type for the loading-progress path (it reflects in-progress boarding, per the sync_load_targets docstring); `loadsheet_final()` (which already passes `?loadsheetType=Final`) stays untouched for the weights path. Optionally harden: when the GSX snapshot itself reports boarding=ACTIVE, don't let the Fenix-path monitor override it with FAILED.
- **Status**: IMPLEMENTED (2026-08-12, source-side). `loadsheet()` now requests `/fenix/loadsheet?loadsheetType=Preliminary` (fenix_adapter.py:254) — the Fenix portal returns HTTP 200 instead of the 400 that killed the boarding monitor; the loading-progress path sees pax/cargo progress again and the one-shot latch acknowledges real boardings. `loadsheet_final()` (loadsheetType=Final) untouched for the weights path. Pending: rebuild + live boarding verification.

### #88 — Pushback latch never sets when the tug accelerates slowly → TAXI OUT fires ~1 s into the pushback (Fenix/GSX-blind) (IMPLEMENTED)
- **Status**: IMPLEMENTED (2026-08-12, source-side) — one-line latch fix at logbook.py:995; verified by replaying the EZY19TC recording (all 116 unit tests pass). Pending: rebuild + live verification.
- **Reported**: 2026-08-12 (live flight EZY19TC, G-EZOM, EGPH→EGBB, packaged v0.25.77). Events: PUSHBACK accepted 12:29:13.142Z → BLOCK OUT 12:29:14.049Z → TAXI OUT 12:29:14.149Z — the phase flipped to TAXI OUT 100 ms after block-out, while the tug was still pushing (pushback actually lasted ~50 s; the recording shows PUSHBACK→PARKED at t=49.77 s via the brake-set cue).
- **Root cause (replay of the live .opsbb.part through the CURRENT source, GSX stubbed False — reproduced exactly, so NOT a stale build)**: two guards disagree on the first-movement window:
  1. `_phase` (logbook.py:815) — the #42 ordering invariant `not times.get("block_out")` returns PUSHBACK on the FIRST moving sample with no minimum GS (gs=1.03 at t=0.02 s).
  2. `_analyse` (logbook.py:991) — the #42 latch requires `gs >= 1.5` AND `previous_phase == "PARKED" or None`. The first sample has gs 1.03 < 1.5 → no latch; by the time GS reaches 1.5 (t=0.91 s) the phase has ALREADY been set to PUSHBACK by the invariant, so `previous_phase == "PARKED"` fails → latch NEVER sets.
  3. BLOCK OUT fires at gs >= 1.5 + movement → the ordering invariant is gated on `not times.get("block_out")` → stops applying. With no latch and no invariant, `gs < 40` → TAXI OUT.
- **Fix (IMPLEMENTED 2026-08-12, source-side, one line, logbook.py:995)**: the #42 fallback latch may also latch from an already-PUSHBACK previous phase: `and (previous_phase in ("PARKED", "PUSHBACK") or previous_phase is None):`. Verified by replaying the EZY19TC recording through the patched code: PUSHBACK (0.02 s) holds through the whole 49.77 s pushback → PARKED (brake-set cue) → TAXI OUT at real taxi (t=204.94 s, gs 1.26 with proven motion) → TAKEOFF ROLL → TAKEOFF → CLIMB. All 116 unit tests still pass. Display mirror (flight_watch._phase) already latches at gs >= 1.0 in the same branch, so it was never affected.
- **Acceptance**: next departure — phase reads PUSHBACK from first movement through tug release, TAXI OUT only when real forward taxi resumes (no 100 ms TAXI OUT blip after block-out).

### #89 — Spurious "EXCESSIVE TAXI SPEED" violation on every takeoff (35 kt vs 40 kt threshold mismatch)
- **Reported**: 2026-08-12 (live flight EZY19TC, EGPH→EGBB, v0.25.77 build). Event: `DEVIATION - EXCESSIVE TAXI SPEED: Ground speed reached 35 kt` at 12:37:41Z — 3 s BEFORE TAKEOFF ROLL was accepted (12:37:44Z). The aircraft was mid-takeoff-run, not taxiing.
- **Root cause**: two thresholds disagree. The violation gate (logbook.py:1272) fires when `on_ground and gs > 35 and phase not in {"TAKEOFF ROLL", "LANDING ROLL", "PUSHBACK"}`. But `_phase` (logbook.py:833) only proposes TAKEOFF ROLL at `gs >= 40`. Every takeoff therefore passes through a 35–40 kt window on the ground where the phase is still TAXI OUT → spurious -3 deviation, every departure.
- **Fix approach**: close the gap — either gate the taxi-speed violation on a takeoff candidate (e.g. skip when gs > 35 and brakes released with sustained forward acceleration / speed still rising), or lower the `_phase` TAKEOFF ROLL proposal threshold to 35 to match, or require the taxi violation to persist (N consecutive samples) so a transient takeoff-run overshoot never fires it. Prefer not to reclassify genuine taxi overshoot — a sustained check is the safest.
- **Additional live evidence (same flight, 13:33:31Z)**: a second spurious `EXCESSIVE TAXI SPEED: 40 kt` fired during the LANDING ROLLOUT — the phase had just transitioned TAXI IN as GS dropped under 40 kt, then a rollout speed bounce back over 40 kt tripped the violation. Confirms the gate also needs rollout protection (not just takeoff): the phase-exclusion set `{"TAKEOFF ROLL", "LANDING ROLL", "PUSHBACK"}` misses the TAXI IN boundary at the 40 kt phase threshold.
- **Status**: IMPLEMENTED (2026-08-12, source-side). The taxi-speed gate is now a **sustained check** (logbook.py:1272): the violation only fires after the qualifying condition (on ground, GS > 35 kt, phase not in {TAKEOFF ROLL, LANDING ROLL, PUSHBACK}) holds continuously for >= 3 s, and is suppressed entirely within 90 s of touchdown — so the takeoff 35–40 kt window and the landing-rollout deceleration through 35–40 kt can never trip it, while a genuine sustained taxi overspeed still scores. Verified by replay of the EZY19TC recording: no spurious violations at t≈takeoff or t≈landing. All unit tests + 77/77 release-validator checks pass. Pending: rebuild + live verification.

### #90 — Live OFP DELTA column renders units (KG) and overflows the table; delta must be unitless (IMPLEMENTED 2026-08-12)

- **Observed**: 2026-08-12 by user: in the Live OFP WEIGHTS / FUEL tables the DELTA column values carry units (e.g. "-2175.0 KG") and bleed out of the display container. Deltas are dimensionless differences (actual − planned) — the unit already lives in the column caption (WEIGHTS KG / FUEL KG), so per-cell units are redundant.
- **Root cause**: `patchBriefingOfpLive` (opsroom.js:1552/1556) rendered the delta cell via `briefingOfpWeight(delta_display ?? delta, unit, 1)` — the same unit-appending helper used for planned/actual cells.
- **Fix**: both the WEIGHTS and FUEL delta setters now pass `''` as the unit (`briefingOfpWeight(..., '', 1)`), so DELTA renders as a bare signed number ("-2175.0") that fits its column. TIMES delta was already unitless (briefingOfpDelta).
- **Status**: IMPLEMENTED (2026-08-12, source-side). Pending: rebuild + live verification.

### #91 — Pre-departure sign-off does not pop up automatically; it must open the modal from any screen
- **Reported**: 2026-08-12 (live flight VLG6013, BIKF→LEBL, packaged v0.25.79).
- **Symptom**: the pre-departure weight-and-balance sign-off never appeared as an automatic popup — the pilot had to find and click the button. On the current build the sign-off is button-triggered by design, which is easy to miss mid-flow.
- **Requirement**: when the loadsheet syncs and the pre-departure sign-off becomes available (before departure), the modal must OPEN ITSELF automatically, from whatever screen the user is on (Flight Watch, Map, Logbook, Host setup, any tab). Same behavior as the post-arrival Flight Completion sign-off: auto-popup at the trigger moment, not a button the user must discover.
- **Fix approach (proposed)**: reuse the same modal-open path as the post-arrival completion sign-off — add a frontend watcher (opsroom.js) that polls the Live OFP / loadsheet status; when the pre-departure sign-off state flips to AVAILABLE and it has not yet been shown for this flight, call the existing `openLsSignoff()` (or equivalent) from anywhere (no screen gate). Back the one-shot with a per-flight flag so it pops exactly once, mirrors the post-arrival flow, and never re-pops on refresh. Also cover the non-Fenix/non-GSX fallback path (manual weight entry / no sheet) so the popup still appears when the user opens the Live OFP with manual values.
- **Status**: IMPLEMENTED (2026-08-13, source-side). Added a global sign-off watcher (`startGlobalSignoffWatcher()` → `pollGlobalSignoff()`, 5 s interval, wired into `boot()`) that polls `/api/briefing/ofp-live` from ANY screen, keeps `briefingOfpLiveData` fresh, and calls `openLoadsheetSignDialog()` directly the moment `loadsheet_ready` (pre-departure) or `completion_ready` (post-arrival) flips true while unsigned — a real modal, not the old toast. One-shot per flight (`_signoffLoadsheetModalShown`/`_signoffCompletionModalShown`, reset on flight id change); never stacks dialogs (`_lsSignDialog.open` guard); backend already guarantees `loadsheet_ready` implies unlocked, so the modal opens without the LOCKED toast. Pending: rebuild + live verification.

### #92 — Black box per-row aircraft_adapter=generic while file/logbook metadata says fenix_a32x (FSUIPC path carries no aircraft identity; adapter detection dies with SimConnect)
- **Reported**: 2026-08-12 (live flight VLG6013, BIKF→LEBL, packaged v0.25.79).
- **Symptom**: the .opsbb file and black-box status show `aircraft_adapter.key = generic` (and recorded flaps read as generic), while the same file's `aircraft` metadata and the logbook entry show `fenix_a32x` / "Fenix A320 IAE SL". The two disagree from row 1 of the recording.
- **Root cause (verified by reading the recording + code trace)**: the black box takes its adapter from the LAST written row (`black_box.py:895-896`, `row.get("aircraft_adapter")`). Rows are built from the writer's enriched FSUIPC sample. `_read_fsuipc_unlocked()` never sets an `aircraft` dict (grep: no title/model/type anywhere in the FSUIPC path). `enrich_telemetry()` → `_identity(result)` therefore finds no `aircraft`, falls back to `_LAST_IDENTITY` (5 s grace, addon_telemetry.py:146) and then to `read_position(force=False)` — a SimConnect read. On this flight SimConnect was dead from before recording start (log: "SimConnect disabled for this session: 5 dispatch crashes in 204s. Degrading to the FSUIPC/WASM path for the rest of this run" + repeated `0xC00000B0` dispatch failures; diagnostics showed `simconnect.frozen=True`). With no aircraft identity anywhere, `detect_family({})` → `generic` for every row, and the Fenix litmus probe (LVars via `simconnect_reader`) also can't run. The file metadata (`aircraft` with the Fenix title, captured at flight start when SimConnect was still alive) therefore contradicts the per-row adapter. So: **adapter detection for the recorder is only as healthy as SimConnect; when SimConnect dies, a Fenix flight records as generic** — exactly the earlier "blackbox flapped to generic, then back to fenix" report.
- **Fix approach (proposed)**: make aircraft identity sticky and SimConnect-independent:
  1. Once `_identity()` has seen a valid aircraft dict (from any source — SimConnect heartbeat, Fenix adapter, flight meta), hold it in a session-level cache (like the existing `_LOCKED_ADAPTER` tier-2 lock, addon_telemetry.py:577) and MERGE it into every FSUIPC sample (`result["aircraft"] = cached_identity` inside `_mark_complete`/`_read_fsuipc_unlocked`), so `detect_family` always has the title even with SimConnect dead. Clear only on a genuine `_aircraft_changed()`.
  2. Extend `_LAST_IDENTITY` grace from 5 s to the session when the cached identity was confirmed supported (mirror the `_LOCKED_ADAPTER` lifetime), so a mid-flight SimConnect outage cannot re-degrade the family.
  3. Bonus: fix the bytes-repr title bug — `aircraft_title = read_value("TITLE")` yields `b"FenixA320 IAE SL"` stringified (metadata literally shows `b"FenixA320 IAE SL"`); decode bytes → str in `read_value`/aircraft_info assembly so the identity text is clean and `detect_family` matches on the true title.
- **Status**: IMPLEMENTED (2026-08-13, source-side). `_identity()` in addon_telemetry.py now holds the last-known-good aircraft identity for the SESSION instead of a 5 s grace: the SimConnect `read_position` fallback runs first (so a recovered SimConnect can still overwrite the sticky identity), and only when it returns nothing does the sticky `_LAST_IDENTITY` carry the family forward. A mid-flight SimConnect outage therefore can no longer re-degrade the recorder's adapter to generic; a genuine aircraft change is still caught by `_aircraft_changed()` against `_LOCKED_ADAPTER_IDENTITY` once a newer identity arrives. This is the #92 step-1 fix (session-level cache + merge). The bytes-title cleanup (step-3 bonus) is also now done: added `_clean_text()` in simconnect_position.py which decodes `bytes`/`bytearray` SimConnect string SimVars (TITLE / ATC_MODEL / ATC_TYPE) as UTF-8 before stringifying, and every title/model/type assembly (full read, minimal high-rate `_BATCH_STRING_CACHE`, low-rate `_lr_aircraft_*` tier) now routes through it — so `b"FenixA320 IAE SL"` can no longer leak into recorder metadata, the Procedures aircraft label, or the Live OFP. Pending: rebuild + live verification (next flight must keep `fenix_a32x` rows even if SimConnect dies mid-flight, and the aircraft label must show clean text without the `b"..."` prefix).

### #93 — NOTAM closure: parallel runways false-positive ("RUNWAY CLOSED PER NOTAM" on every runway)
- **Reported**: 2026-08-13 (live). The RAAS NOTAM closure callout fired on *every* runway during approach at LEBL.
- **Root cause (reproduced against the code)**: `_runway_matches()` (raas.py) compared `part.rstrip("LRC") == runway.rstrip("LRC")`, which strips the L/R/C designator from BOTH sides before comparing. That collapses parallel runways to the same bare base — a NOTAM `RWY 07L/25R CLOSED` matched 07R and 25L too, because `07L`→`07` == `07R`→`07`. LEBL has 07L/25R + 07R/25L + 02/20, so one closure NOTAM announced on all four parallel ends. The #17 dedup latch could not help (07L/25R and 07R/25L genuinely are different strips, each correctly fired once).
- **Fix**: a designator carrying L/R/C must match that end EXACTLY; only a BARE designator (e.g. `07` or `02/20`) matches every end sharing that base. Verified: `07L/25R CLOSED` → only 07L+25R; `02/20 CLOSED` → 02+20; `07/25 CLOSED` (bare) → all four parallel ends; `08/26 CLOSED` → 08/26/08L/26R.
- **Status**: IMPLEMENTED (2026-08-13, source-side, ~6 lines in `_runway_matches`). Pending: rebuild + live verification.

### #94 — Fenix arrival cargo doors / GPU / chocks silently skipped when SimConnect is down
- **Reported**: 2026-08-13 (live). Clicking "Begin arrival services" on a Fenix flight did not open the cargo doors — it had worked on earlier flights.
- **Root cause (log + live API confirmed)**: the session hit the #64 SimConnect degradation ("SimConnect disabled for this session: 5 dispatch crashes in 204s"), and Fenix detection is SimConnect-only (`_is_fenix_aircraft()` reads the aircraft title via `read_position`). `/api/fenix/status` showed `fenix_detected:false`, `fenix_family_hint:false`, `aircraft.telemetry_ok:false` while `efb_online:true`. So `_prepare_fenix_arrival_ground_once()` → `_fenix_arrival_family()` returned false and early-returned — cargo doors, GPU and chocks were never commanded. The door commands themselves go through the Fenix EFB GraphQL portal (8083), which was healthy the whole time; only the identity *gate* needed SimConnect.
- **Fix**: added `fenix_efb_active()` (fenix_adapter.py) — SimConnect-independent Fenix signal: EFB portal reachable AND answering with a Fenix-shaped loadsheet (FINAL cache, else Preliminary with `aircraftTailNumber`/`zfw`/`tow`), 10 s TTL. `_fenix_aircraft_active()` and `_fenix_arrival_family()` (gsx_remote.py) now fall back to it, so doors/GPU/chocks/deboarding keep working with SimConnect degraded.
- **Status**: IMPLEMENTED (2026-08-13, source-side). Pending: rebuild + live verification.
### #95 — RAAS + announcements fire at the MSFS menu position (DGTK) and "RUNWAY CLOSED PER NOTAM" false-fires on non-closure NOTAMs (IMPLEMENTED 2026-08-13)
- **Reported**: 2026-08-13 (live test flight). Two RAAS alerts fired while sitting in the MSFS main menu, followed immediately by "RUNWAY CLOSED PER NOTAM" (runway 32L) — nothing to do with the actual flight at EDDS.
- **Root cause (two independent bugs)**:
  1. **Menu position is not rejected.** `_session_gate` (raas.py) only rejected the DGTK menu position when `on_ground` was True, never checked `simulator_menu_state` / `simulator_loading`, and armed after only 1.25 s of stable position. In the menu the sim reports not-on-ground at the DGTK default, so the guard was skipped and callouts armed on the menu position. Same flaw in `_stable_live_session` (announcements.py).
  2. **NOTAM closure check was too loose.** `_notam_runway_closed` used `is_closure_notam` + `_runway_tokens`, which match conditional/equipment NOTAMs — "CRANE WILL ONLY OPR WHEN RWY 32L IS CLSD" and "ILS RWY 32L U/S" both count as closures even though the runway is NOT closed. Verified: EDDS's live DB rows (cranes, construction, navaids) triggered the "RUNWAY CLOSED" path.
- **Fix**:
  1. `_session_gate` now rejects `simulator_loading`/`simulator_menu_state` outright, rejects the DGTK position **unconditionally** (no `on_ground` gate), and on-ground arming requires a sustained 3 s parked dwell (airborne keeps 1.25 s so mid-air spawns still get approach callouts). Same changes applied to `_stable_live_session` in announcements.py.
  2. `_notam_runway_closed` now reuses the strict `closure_markers._runway_closure_refs` parser (rejects WHEN/IF conditionals and ILS/LOC/etc.-prefixed U/S; only direct "RWY xx CLSD" counts), with a defensive fallback that is never looser than before.
- **Verified**: py_compile clean; gate unit checks (DGTK off-ground reject, menu-state reject, loading reject, 3 s parked arm, 1.25 s airborne arm); mocked NOTAM list — only `RWY 32L/14R CLSD DUE WIP` matches, crane/ILS/non-closure rows are ignored; closure-marker + notam-translate suites 74/74 and announcements 21/21 pass.
- **Status**: IMPLEMENTED (source-side). Pending: rebuild + live confirmation (menu must stay silent).

---

## #96 — Fenix not detected / Black Box generic + GSX refuel broken (registry deleted + SimConnect UnboundLocalError)

- **Symptom**: Black Box records "generic MSFS aircraft" on a Fenix flight; GSX no longer drives Fenix refuel; `/api/blackbox/adapters/install` returns 500 "FSUIPC user offset area does not have enough free 4-byte slots".
- **Root cause — TWO independent bugs**:
  1. **Registry file deleted** (`%LOCALAPPDATA%\Ops Room\aircraft_adapter_offsets.json` missing; nothing in code deletes it — swept up in the v0.25.79 temp cleanup). Without it, `load_registry()` returns {} → no offset map → Fenix LVars unreadable via FSUIPC. Re-install is the recovery path, but…
  2. **`_strip_opsroom_block` never matches the markers after FSUIPC reformats the ini.** FSUIPC rewrites comment lines as `!1=; OPS ROOM BLACK BOX ADAPTERS BEGIN …` / `!2=… END`, but the stripper matched only lines *starting with* the bare marker. The old 114-line block is never stripped, so the offset area counts as full and allocation raises RuntimeError. Latent since the first FSUIPC reformat (all 150 ini backups show `!N=` markers); only bites when a re-install is forced (i.e. when the registry is gone).
- **Fix (implemented in source, app/aircraft_adapter_installer.py)**:
  1. `_strip_opsroom_block` now normalises the leading `!N=` prefix before marker matching → old block always stripped → re-install succeeds. Verified against the real `C:\FSUIPC7\FSUIPC7.ini`: strip removes 116 lines, allocator assigns all 114 offsets.
  2. New `_recover_registry_from_ini()`: if the registry file is missing but the ini block exists, rebuild the registry from the ini (accepts both bare and `!N=` markers) instead of returning {}. `load_registry()` calls it on missing-file. A deleted registry can no longer silently cripple the adapter.
  3. Registry was restored live from the ini (114 offsets) so the current session already reports `mappings_installed: True`.
- **Root cause — bug 3 (the reason Fenix still showed generic after the registry fix)**: `_ensure_session()` in app/simconnect_position.py gained an assignment `_LAST_REBUILD_AT = 0.0` (inside the degraded-cooldown branch) without declaring `global _LAST_REBUILD_AT`. The function also reads that name, so on the normal path (cooldown branch not taken) Python raises `UnboundLocalError: cannot access local variable '_LAST_REBUILD_AT'` → SimConnect can never establish a session → no aircraft title (FSUIPC carries none) → Fenix family undetectable → generic adapter. Regression introduced by the v0.25.78/79 SimConnect auto-recovery work; the v0.25.77 checkpoint (`7a69555`) did NOT have the in-function assignment and worked.
- **Fix (implemented in source)**: added `global _LAST_REBUILD_AT` to `_ensure_session`. Verified: module imports; the no-dll path now raises the intended FileNotFoundError instead of UnboundLocalError; test_simconnect_bounded_reconnect 16/16 pass.
- **Status**: IMPLEMENTED (source-side) + registry restored live. Pending: rebuild + confirm Fenix detection (Black Box should show Fenix adapter, GSX refuel works).

---

## #97 — Live OFP RAMP/OUT fuel shows wrong value (9,545 kg vs ~3,000 kg actual) — departure fuel baseline ratcheted by a transient fuel spike

- **Symptom**: Live OFP FUEL section shows RAMP/OUT actual ≈ 9,545 kg while the tank holds ~3,000 kg (verified live on EWG39KK, EDDS→LDZA, 2026-08-13). Black Box/live telemetry reads the correct fuel (`fuel_total_lb` = 7,332 lb ≈ 3,326 kg).
- **Root cause (two compounding behaviours)**:
  1. **`logbook.py` `_update_fuel_accounting()` baseline ratchet takes `max()`**: while parked pre-block-out it sets `baseline = max(departure_baseline_lb, start_lb, current_fuel)` (logbook.py:934). A single transient garbage fuel read ratchets the departure baseline up forever — `max()` never lets it come back down. Recorded evidence: sample rows 7076→7263 (~12.5 s at 12:32:27Z) read `fuel_total_lb = 21044` (= 9,545 kg, a physically impossible 6614→21044 lb jump in one 15 Hz tick) then dropped back to 6,614 lb. The baseline locked at 21044 lb.
  2. **Live OFP backfills RAMP/OUT from that baseline** (`ofp_actuals.py` #74 backfill: when the "out" operational snapshot is empty pre-block-out, it uses `departure_baseline_lb`/`start_lb`). So the panel shows 9,545 kg even though the snapshot `start.fuel_lb` correctly captured 6,614 lb.
- **Why it matters beyond the panel**: `logbook.py:1552` computes fuel used from `departure_baseline_lb − end_lb`. With the poisoned baseline the logbook/PIREP would report ~14,000 lb of fuel "used" regardless of actual burn. The "out" snapshot at block-out self-corrects the OFP row, but the accounting damage persists.
- **Proposed fix (not yet implemented)**:
  1. Add a **plausibility/sustained-value guard** to the `_update_fuel_accounting` ratchet: only ratchet the baseline upward when the increase is refuel-plausible (rate-bounded, e.g. ignore a jump that adds more than a sane lb per tick) and/or the new value is **sustained** for N consecutive samples — a single transient spike must never move the baseline.
  2. Optionally cap the ratchet against a plausible aircraft fuel capacity so impossible values can never win the `max()`.
  3. Consider a one-time repair for in-flight recordings whose baseline is already poisoned (reset `start_lb`/`departure_baseline_lb` from the `start` snapshot's `fuel_lb` when the snapshot is sane and the baseline is implausibly higher).
- **Status**: IMPLEMENTED source-side (2026-08-13) — `_update_fuel_accounting` now caps the baseline with a plan-anchored ceiling (planned ramp fuel ×1.25 + 500 lb, KG→LB converted) and rejects single-sample jumps >10% (or 400 lb) unless sustained for 3 consecutive samples; a transient spike can no longer ratchet the departure baseline. Pending rebuild + next-flight verification.

---

## #98 — SimConnect native heap corruption kills the whole process (0xC0000374) — HIGH PRIORITY, 3-tier fix

- **Symptom**: The app dies silently mid-session with no Python traceback. Windows Event Log Application Error #1000: `OPS ROOM.exe`, faulting module `ntdll.dll`, exception `0xC0000374` (STATUS_HEAP_CORRUPTION). opsroom.log then shows on next start: `WARNING: the previous run did not exit cleanly -- it may have crashed natively (e.g. the SimConnect dispatch heap corruption that kills the whole process with no Python traceback)`. Verified 2026-08-13 15:48:30 (run started 15:20:51). Same signature on 08/08 (`0xc0000409`) and 08/11 (`0xc0000374`) — pre-existing, NOT caused by the #96 fixes.
- **Root cause**: The vendored SimConnect wrapper runs a native dispatch loop (`sm.dll.CallDispatch` every ~2 ms, `_guarded_dispatch_run`). Immediately before death the log shows `SIMCONNECT_EXCEPTION_UNRECOGNIZED_ID` — the app is requesting SimVars/LVars that don't exist on the loaded aircraft (the Fenix LVar litmus probe on a non-Fenix identity, and the CAMERA_STATE read on aircraft that don't expose it). The wrapper's native layer mishandles those and corrupts the heap; when the heap goes, the WHOLE process dies — Python try/except cannot catch a native crash.
- **Why Python can't just catch it**: `0xC0000374` is process-level heap corruption inside `ntdll.dll` via the SimConnect wrapper's C layer. No `except Exception` in the app can intercept it; the process is already gone.
- **Tier 1 — Stop feeding the trigger (small, implement first)**:
  1. Gate the Fenix LVar litmus probe (`addon_telemetry.enrich_telemetry`): only probe when aircraft identity is plausibly Fenix (A319/A320/A321 tokens or Fenix transient tokens), never on a blank identity, with a failure backoff so a non-Fenix aircraft stops being probed repeatedly.
  2. Add a failure backoff to the CAMERA_STATE read (`simconnect_position._read_camera_state_raw`, #80): if a session reports UNRECOGNIZED_ID / read failure for CAMERA_STATE, stop requesting it (e.g. exponential backoff) instead of hammering the dispatch loop every 0.5 s.
  3. Tighten `_guarded_dispatch_run`: on dispatch death, close the session and tear down the wrapper's timer thread immediately so the corrupt heap has the smallest window to spread before the session is rebuilt.
- **Tier 2 — Auto-recover from the residual crash (small)**:
  - The launcher already detects the dirty exit. Add auto-restart on native crash: single-instance lock + relaunch flag so a SimConnect heap crash becomes a ~10 s blip instead of "the server died". Black Box already resumes from the DB mid-flight, so a flight keeps recording through the restart.
- **Tier 3 — Real cure: isolate SimConnect in a worker process**:
  - Move all SimConnect reads into a helper process (`simconnect_worker.py`) that owns the native session and serves reads over a local socket (same pattern as `camera_bridge.py`, which already runs as `subprocess.Popen` + IPC). If the worker's heap corrupts, only the worker dies; the main app restarts it. FSUIPC stays primary; SimConnect only serves identity, camera state and the Fenix litmus.
- **Status**: IMPLEMENTED all 3 tiers source-side (2026-08-13): T1 gates the Fenix litmus + CAMERA_STATE probes with failure backoff and suppresses all-None LVar probe batches; T2 adds an external crash watchdog (launcher `--watchdog` role: relaunches on native crash up to 3×, clean exit respected) ; T3 isolates LVar probe traffic in a subprocess (`simconnect_probe_worker.py` + client, spawned via launcher `--probe-worker` role, in-process fallback). Pending rebuild + live verification.

---

## #99 — Live OFP weights/fuel frozen on pre-crash values after an app restart (stale `last_progress` + `keep` freeze bug)

- **Symptom** (verified live on EWG39KK, 2026-08-13): after the 15:48:30 native crash (#98) and app restart, the Live OFP shows frozen values: PAX actual = 42 (of 179 planned), PAYLOAD actual = 6,011 kg (delta −10,960), BAG/CARGO = 2,651 kg, RAMP/OUT fuel = 9,545 kg. The `updated_utc` ticks forward (the endpoint responds), but the VALUES never change.
- **Root cause — two compounding behaviours**:
  1. **Frozen `fenix_loading.last_progress` snapshot.** The snapshot's `updated_at` is 13:48:25Z — five seconds BEFORE the 15:48:30 local native crash — and it was restored from the saved state file (`gsx_automation_state.json`, loaded at `gsx_remote.py:2925` on boot). It has never refreshed since: the Fenix portal now returns **HTTP 204 No Content** for both `/fenix/loadsheet?loadsheetType=Preliminary` and `=Final` (verified by direct probe), so `_refresh_fenix_loading_snapshot()` bails at its `not any(pax_loaded/cargo/fuel)` guard and the snapshot stays pinned at the last pre-crash write forever. The OFP presents these stale values with `source: "gsx/fenix loading"` and `availability: available` as if they were live.
  2. **`keep` freeze bug in `_refresh_fenix_loading_snapshot` (gsx_remote.py:2729-2741).** Even when fresh Fenix progress IS available, `"passengers": keep.get("passengers", fenix_progress.get("pax_loaded"))` prefers the OLD `passengers` value from the previous snapshot — so PAX can never move forward once stored. The `keep` intent was to preserve GSX-derived fields across Fenix refreshes, but `passengers` must come from the fresh source when present.
- **Why it matters**: the OFP's PAX → PAYLOAD derivation (`ofp_actuals.py`, per-pax block × 42 + cargo 2,651 = 6,011 kg exactly) means the entire WEIGHTS section is a frozen pre-crash snapshot presented as live. The RAMP/OUT 9,545 kg is a separate already-logged issue (#97, poisoned fuel baseline). ZFW/TOW/LDW are blank because the 204 portal provides no loadsheet.
- **Key live observation (2026-08-13, during boarding)**: Ground Control shows **GSX Pro Connected · Boarding 115 / 179 — LIVE and correct** — while the OFP simultaneously shows PAX 42. The GSX live count comes from a completely different structure: `gsx_remote.status()["progress"]["passengers_boarding_total"]` / `passengers_target` (parsed from the official Remote API v2 state at `gsx_remote.py:764`, served to Ground Control over `/ws/gsx`). The OFP path (`main.py:_live_ofp_payload` → `ofp_actuals._weights_section`) reads ONLY `fenix_loading.last_progress` and never merges the live GSX progress. So there IS a trusted, live, measured PAX source available in-process during exactly the window the Fenix snapshot is frozen — it just isn't wired in.
- **Proposed fix (not yet implemented)**:
  1. **Staleness guard on `last_progress`**: the OFP must not present `last_progress` values as live measured actuals when `updated_at` is older than a sane TTL (e.g. 5 min) — show "—" / stale instead of freezing mid-boarding numbers on screen. Apply at read time in `ofp_actuals.py` (or mark `availability` stale in `main.py:_live_ofp_payload`).
  2. **Fix the `keep` freeze**: `passengers` (and `boarding_cargo_percent`) should prefer the fresh `fenix_progress` value; `keep` should only preserve fields the Fenix progress doesn't carry.
  3. **Merge the live GSX progress as the authoritative fallback**: in `main.py:_live_ofp_payload` (or `ofp_actuals._weights_section`), when `last_progress` is stale/missing, read `gsx_remote.status()["progress"]` (cheap, 2 s cached — same source Ground Control uses) and use `passengers_boarding_total`/`passengers_target` for PAX and `boarding_cargo_percent` for BAG/CARGO, tagged `source: "gsx live"`. This makes the OFP weights track boarding in real time even when the Fenix portal is 204 / frozen — exactly what Ground Control already proves is possible.
  4. **Handle the 204 portal state**: treat persistent 204 as "no loadsheet available" and clear/expire the frozen snapshot rather than serving it indefinitely; optionally surface a "Fenix loadsheet unavailable" note in the OFP.
  5. #97 (fuel baseline ratchet) is logged separately and must also land for the fuel section to be correct.
- **Status**: IMPLEMENTED source-side (2026-08-13): `automation_status()` expires `last_progress` older than 120 s (staleness TTL, `_last_progress_fresh`), the OFP request path falls back to live GSX boarding progress when the Fenix snapshot is stale, and `last_progress` is no longer served frozen. Pending rebuild + next-flight verification.

## #100 — Community visibility "public" never syncs to the server → live map feed 403s

- **Symptom** (verified live 2026-08-13, EWG39KK EDDS→LDZA): user sets app-side visibility to `public` in Host Setup → Discord Community, but the website community map stays empty. Ground/leaderboard events work; live feed never appears.
- **Root cause — two visibility stores that never sync**: the desktop app's `community.visibility` (settings.json, gates `_tick_live` in `community.py`) and the server's `app_links.visibility` (SQLite row, resolved per-request in `admin-api/community.py:_resolve_identity`, gates `/api/community/live` with HTTP 403 "Live feed requires public visibility"). The app's `/api/community/settings` only writes the local setting; it never notifies the server. The server-side visibility is only set by the bot's `/flight-visibility` command or preserved from a previous connect. Verified: `POST /api/community/live` with the user's app token → **403**; `POST /api/community/event` → **200** (identity + token fine).
- **Fix (proposed)**: when the app changes visibility via `/api/community/settings` (or on connect), POST the new value to `{api_base}/api/community/visibility` with the app token (new small admin-api route that updates `app_links.visibility`), so the app-side dropdown is authoritative. Keep the bot `/flight-visibility` as a Discord-side equivalent. Also surface a hint in the Host Setup UI: "public also requires /flight-visibility public in Discord" until the sync lands.
- **Immediate user unblock (before the fix lands)**: run `/flight-visibility public` in the Discord server — the bot writes the same `app_links.visibility` row the admin API reads (shared `/ops-control-data/ops-control.db`), so the next `POST /api/community/live` from the app (every ~15 s while a flight is live) is accepted and the pilot appears on opsroom.live. Verified 2026-08-13: without it the server returns 403 and the website shows 0 airborne.
- **Status**: IMPLEMENTED (2026-08-13): app `_settings` syncs visibility to the server (`POST {api_base}/api/community/settings` → new admin-api route that updates `app_links.visibility`). Pending rebuild + VPS deploy.

## #101 — Ground Control departure automation stalls after an app restart mid-departure (re-seeded but never resumes)

- **Symptom** (verified live 2026-08-13, EWG39KK EDDS→LDZA): app crashed natively at 13:48:30Z (#98) mid-departure. On restart at 13:52:17Z the GSX automation re-seeded from `gsx_automation_state.json` (`latches=57`, frozen at 13:48:29Z) but **never resumed the departure flow**: `phase: null`, `FENIX_LOADING_IDLE`, and the only GSX event since is the re-seed line itself. Latches stayed unfinished forever: `boarding_requested_once: false` (pilot had to board manually), `boarding_complete: false`, `water_complete: false` / `water_deferred_or_skipped: "blocked or unavailable after 90 seconds"`, `boarding_seen_active: true`.
- **Root cause**: #65 fixed the arrival side (persist latches + re-seed + 5-min post-arrival fallback). The departure side persisted the latches but nothing **re-engages the decision loop after a restart while the flight is still pre-block-out** — the automation only runs once the user manually starts departure services again, so a mid-departure crash leaves the machine idle with stale unfinished latches for the rest of the ground phase (which also keeps the OFP weights frozen via #99's `last_progress`).
- **Proposed fix**: on automation startup, if the re-seeded mode is `DEPARTURE`/`FULL_TURNAROUND`, the flight is still on the ground pre-block-out, and telemetry is fresh, automatically re-arm the departure decision loop (same entry point as "Begin Departure Services") so pending latches (boarding request, water retry per the existing 90 s policy, completion tracking) are re-evaluated; do NOT re-fire one-shot actions that already latched true (`catering_requested_once`, `departure_cargo_doors_closed_once`, etc.). Acceptance: after a mid-departure crash + restart, boarding auto-requests if not yet latched, and completion latches close out without the pilot touching anything.
- **Status**: IMPLEMENTED source-side (2026-08-13): `_maybe_rearm_departure_after_restart()` + delayed `_schedule_departure_rearm()` re-arm the departure decision loop after a restart when mode is DEPARTURE/FULL_TURNAROUND/AUTO, still on ground pre-block-out with fresh telemetry, latches preserved (no re-fires). Pending rebuild + verification.

## #102 — Rich Presence only appears when set by an external process; the app's own loop never sets it

- **Symptom** (verified live 2026-08-13): after connecting Discord, the user's profile showed only "Playing MSFS 2024" — no OPS ROOM activity — even though the app was running for hours with `rich_presence_enabled: true`, a live flight (EWG39KK, state=live), and the community settings all correct. The moment a test process ran the app's own `_DiscordRPC` code (same `community.py`, PowerShell-spawned python), the pipe opened, `connect()` returned True, `SET_ACTIVITY` was sent, and Rich Presence appeared instantly.
- **Evidence**: (1) `\.\pipe\discord-ipc-0` exists and handshakes fine from a normal-spawned process using the app's exact code — so the IPC path works; (2) OPS ROOM.exe and Discord are both non-elevated (ruled out integrity mismatch); (3) the app's 5 s community loop (`start_community()` → `_community_loop` → `_update_presence`) produces ZERO log output ever — no "Discord connected", no failure — because the RPC path logs nothing and the root logger default level (WARNING, no basicConfig) suppresses `_LOGGER.info`/`debug`.
- **Root cause — ranked suspects (all real gaps, fix all)**:
  1. **The whole community integration is uncommitted working-tree code** (`app/community.py` untracked; `start_community()` at `main.py:126` never in any git commit). The running EXE (built 15:12) is a stale, unverifiable build — it may predate/mis-bundle the startup hook. Permanent fix: commit the integration and rebuild; the EXE currently running is not the source.
  2. **No logging in the RPC path** — connect success, SET_ACTIVITY, and every failure reason are silent, so a loop failure is indistinguishable from "loop not running". Add `_LOGGER.info("Discord Rich Presence connected (pipe %s)")` / `_LOGGER.info("SET_ACTIVITY ok")` and `_LOGGER.warning("Rich Presence connect failed: %s")` on failure.
  3. **Blocking handshake with no timeout** — `_DiscordRPC._handshake()` does `self._pipe.read(8)` (blocking) with no timeout; if `open()` finds a stale/orphaned pipe instance whose server never answers, `_update_presence()` blocks forever inside `connect()`, the 5 s loop thread wedges permanently, and Rich Presence can never be set until the app restarts. Add a read timeout (e.g. 2 s) / select-based handshake so a bad pipe is skipped instead of hanging the loop.
- **Proposed fix**:
  1. Commit the Discord/community integration (`community.py`, main.py wiring, settings defaults, frontend) and rebuild — the current EXE is stale.
  2. Add INFO/WARNING logging to the RPC path (connect, set, failure + reason) so `opsroom.log` shows the loop's behaviour.
  3. Timeout the handshake read (2 s) and treat timeout/OSError as "try next pipe" — a stale pipe can never wedge the loop.
  4. Keep the existing 5 s retry so the app reconnects automatically if Discord restarts (already in place once (3) stops the wedge).
- **Acceptance**: restart the app with Discord open and a live flight; within ~10 s `opsroom.log` shows "Rich Presence connected" and the Discord profile shows the OPS ROOM activity without any external process.
- **Status**: IMPLEMENTED source-side (2026-08-13): INFO logging for connect/SET_ACTIVITY/failure, handshake + frame reads timeout-guarded (3 s, threaded), stale pipes skipped instead of wedging the loop, and `logging.basicConfig(INFO)` in main.py so the lines actually reach opsroom.log. Pending rebuild + verification.

## #103 — Website live map: aircraft-symbol markers + route on hover (currently a plain dot)

- **Symptom/request** (2026-08-13): the live map on opsroom.live renders each pilot as a plain 14×14 circular blip (`flightDot()` divIcon in `opsroom-website/src/components/CommunityMap.jsx`). Request: replace the blip with an aircraft symbol and show the route on hover.
- **Current state**: `CommunityMap.jsx` uses `L.divIcon` with a `<span>` dot; a click popup already shows callsign, route, phase, altitude, GS (`popupHtml`). The feed (`/api/community/live`) carries callsign, origin, destination, phase, lat/lon, altitude, groundspeed — **no heading/track and no aircraft type**, so a proper rotated plane icon needs data additions.
- **Fix (proposed)**:
  1. **App** (`app/community.py:_live_payload`): add `heading` (from telemetry `heading_deg`/`track_deg` when present) and `aircraft` (icao) to the live payload.
  2. **Server** (`opsroom-website/admin-api/community.py` + DB): add a `heading` column to `community_live` (aircraft/registration columns already exist in the insert but are never populated — fill them), expose both in the `/api/community/live` response.
  3. **Website** (`CommunityMap.jsx`): render an inline-SVG aircraft marker (plane silhouette), rotated by `heading` (CSS transform on the divIcon; fall back to a static plane at 0° when heading is missing); `bindTooltip` on hover with `callsign · origin → destination · phase · alt · GS` (reuse the popup content as the tooltip) while keeping the click popup; optionally draw a dashed route polyline from origin to destination airport coordinates when both are known.
- **Acceptance**: live flights show as oriented aircraft icons on the map; hovering shows the route; no regression to click popup or fitBounds behaviour.
- **Status**: IMPLEMENTED (2026-08-13): app sends `heading`/`aircraft`/`registration` in the live payload; server `community_live` gained a `heading` column (idempotent migration) and exposes it; website map renders rotated SVG plane markers with hover tooltips (route + live details). Website `dist` rebuilt. Pending VPS deploy.

## #104 — Descent briefing DM at TOD (feature was on the roadmap but never built)

- **Request**: at top-of-descent, the bot DMs the pilot the destination weather briefing (METAR + TAF + NOTAMs + runway). User asked "when does the bot DM me the weather at destination?" — answer: it never does; verified by search — the app only emits `takeoff`/`landing` community events (`notify_flight_event` at `logbook.py:1184/1240`) and the bot has no descent handler.
- **Building blocks that already exist**: the bot can fetch METAR/TAF (`bot/api/__init__.py`) and NOTAMs (`cogs/notam*.py`, `cogs/weather.py`), and it already resolves the pilot's Discord identity for takeoff/landing events (`pending_actions` → `dispatch_flight_event`).
- **Fix (proposed)**:
  1. **App**: when the flight phase transitions to DESCENT (ENROUTE → DESCENT in `logbook.py`/`flight_watch.py`), call `notify_flight_event(meta, "descent")` — extend the community event payload with destination + ETA/remaining distance. Fire once per flight (dedupe latch like takeoff/landing).
  2. **Server** (`admin-api/community.py`): accept `event_type == "descent"`, enqueue a pending action (same as takeoff/landing).
  3. **Bot**: in the flight-event dispatcher, on `descent` DM the linked user (`<@discord_id>` — same identity used for the PIREP DM) with a compact briefing: destination METAR, TAF, relevant NOTAMs (reuse existing fetch helpers), and the destination runway(s) if determinable.
  4. Respect visibility (`hidden` → skip); opt-in via the same `share_flights` gate so it only fires for consenting users.
- **Acceptance**: at TOD on an opted-in flight, the pilot receives a single DM with destination weather before landing.
- **Status**: IMPLEMENTED (2026-08-13): logbook fires a one-shot `descent` community event on DESCENT transition; server accepts `event_type == "descent"`; bot DMs the linked user a destination briefing (METAR + TAF + NOTAMs) at top-of-descent. Pending rebuild + VPS deploy.

## #105 — Leaderboard shows 0 hours: landing event duration_min always None (durations only computed at finalize)

- **Symptom** (verified live 2026-08-13, EWG39KK EDDS→LDZA): after a clean landing + event flow, `/api/community/leaderboard` shows `exzonomlol · flights 1 · hours 0.0` even though the block was ~71 min.
- **Root cause**: `community.notify_flight_event()` reads `durations.get("block_seconds")` from `meta["durations"]`, but that dict is only written at **logbook finalize** (`logbook.py:1558`) — takeoff/landing events fire mid-flight, so `durations` is empty at event time and `duration_min` is `None` → the bot's `flight_logs` mirror stores NULL → the leaderboard's `COALESCE(SUM(duration_min),0)/60` = 0.0.
- **Fix (IMPLEMENTED source-side 2026-08-13)**: new `_event_block_seconds(meta)` in `community.py` — uses `durations.block_seconds` when present (finalize path), otherwise derives block seconds from `meta.times.block_out` → `block_in`/`landing` (already populated mid-flight); returns None only when neither source exists. Verified against the real EWG39KK meta: 4,282 s → 71.4 min (mid-flight) and the finalize path unchanged (71.2 min). `duration_min` in the event snapshot now uses it.
- **Note**: the current EWG39KK `flight_logs` row was already written with 0/NULL — it stays 0.0 on the leaderboard unless repaired server-side; future flights (after rebuild) report correct hours.
- **Status**: IMPLEMENTED (source-side, `app/community.py`) — pending rebuild + next-flight verification.

## #106 — Bot polish: VATSIM tracker fix (done), tagging reverted (decision), em-dash sweep (pending)

- **VATSIM tracker false-takeoff fix — IMPLEMENTED source-side (uncommitted, needs push + VPS deploy)** (`ops-control-bot/src/bot/cogs/vatsim_tracker.py` + `database/db.py`): airborne detection was `not on_ground and altitude(MSL) > 100 ft`, so any high-elevation field (EDDS ~1,276 ft) false-fired "TAKEOFF" during pushback whenever VATSIM's on_ground flag was momentarily unset. Now self-calibrating: the last on-ground MSL altitude is stored per CID (`ground_ref_alt` + `altitude` columns, idempotent migration) and airborne requires climbing 100 ft AGL above it; when no ground reference exists yet it requires a real climb signature (altitude > 1,500 ft AND groundspeed > 60 kt). 3 regression tests added (incl. the exact EWG39KK/EDDS scenario), 9/9 pass.
- **Tagging on takeoff/landing cards — REVERTED by owner decision (2026-08-13)**: the `<@discord_id>` mentions I added to the tracker posts and community embeds were removed again ("keep it as it is right now"). The `_post_takeoff`/`_post_landing`/`_takeoff_embed`/`_landing_embed` are back to the pre-tag behaviour (VATSIM CID / no mention). Do NOT re-add.
- **Em-dash sweep — DONE (2026-08-13)**: all 94 em dashes across `src/` + `tests/` replaced with plain hyphens (0 remaining); `compileall` green.
- **Status**: tracker fix + revert + em-dash sweep all done in source (uncommitted — pending commit/push + VPS deploy).

## #107 — RealWorld enrichment logger double-escaped format string (LOGGED 2026-08-13, HIGH priority fix)

**Symptom**: every enriched aircraft (4-per-second during RealWorld refresh) throws `TypeError: not all arguments converted during string formatting` and dumps a full Python stack trace into opsroom.log. Log line: `'[RealWorld] AIRCRAFT ENRICH cs=%%s hex=%%s key=%%s type=%%s reg=%%s'` — the `%%s` is double-escaped so `logger.info(msg, *args)` fails.

**Root cause**: `app/realworld.py` `_enrich_one` (~line 474) logs with `%%s` format specifiers (a stray second `%`), so the args tuple never gets consumed.

**Fix (1 line)**: change `%%s` → `%s` in the AIRCRAFT ENRICH log message. Verify no other `%%` leaks in `realworld.py` (grep for `%%s`).

**Verified live**: stack trace repeated dozens of times per refresh in the 21:xx logs; log spams `--- Logging error ---` blocks around every RealWorld refresh cycle.

## #108 — SimConnect native heap corruption 0xC0000374 persists after Tier 1–3 (LOGGED 2026-08-13, CRITICAL)

**Symptom**: OPS ROOM.exe crashed at 21:50:22Z with `0xC0000374` heap corruption in `ntdll.dll` (same fault offset `0x0000000000112165` as the 4 prior occurrences — this is the 5th). Crash while parked at LGAV gate, idle. Tier 1 (probe gates) reduced UNRECOGNIZED_ID churn but did NOT eliminate the crash.

**What worked**: Tier 2 watchdog auto-restarted in ~26s (21:50:22 → 21:50:48), OFP/recorder/SimConnect session all recovered, no data loss. Tier 3 probe-worker subprocess exists but the crash still hit the main process.

**Remaining hypothesis**: heap corruption is not from LVar probe churn (now isolated in the worker) but from another SimConnect client path in the main process — likely the SimConnect dispatch loop (Camera Bridge is a separate exe so it's out of scope; the main-process `simconnect_position`/`telemetry_provider` SimConnect session). The dispatch thread + main thread sharing the SimConnect handle, or repeated session re-establishment (the 0xC00000B0 dispatch failures → session rebuild → heap churn) is the prime suspect.

**Proposed fix (next tier)**: fully isolate the main-process SimConnect session: run the entire SimConnect data path (position + LVar + CAMERA_STATE reads) in the probe worker subprocess, and have the main process consume only the pipe (zero SimConnect.dll usage in the main process). If a native crash happens, it kills only the worker; main app keeps FSUIPC telemetry uninterrupted. Requires moving the position/litmus reads (currently `simconnect_position.py` in-process) into `simconnect_probe_worker.py` and exposing them over the existing pipe protocol.

**Acceptance**: 3 consecutive flights without a 0xC0000374; watchdog never fires; log shows no in-process SimConnect dispatch failures.

**Status: IMPLEMENTED (2026-08-14)** — the #108 next tier is done source-side:
- **Critical discovery**: the T3 worker pipe was silently dead — the client wrote `str` to a binary pipe (`proc.stdin.write(json.dumps(...) + "\n")`), raising `TypeError` that the generic `except` swallowed, so EVERY worker transaction returned `None` and the app always fell back to in-process SimConnect reads. That is why the crash still hit the main process after T3. Fixed by encoding requests as UTF-8 bytes and decoding responses in the new reader thread.
- **Client** (`app/simconnect_probe_client.py`): rewritten with a dedicated reader thread per spawned worker (serialized, timeout-enforced transactions — the old `readline()` had NO timeout and would block a caller indefinitely; at 30 Hz writer cadence concurrent callers would interleave on the pipe). Added `read_position()`, `read_position_minimal()`, `camera_state()`; failure backoff (`_FAILED_UNTIL`) prevents hammering a hung worker; `_kill` closes stdout/stderr so respawns never leak pipe handles.
- **Worker** (`app/simconnect_probe_worker.py`): new `position` / `minimal` / `camera` commands served from the worker's own session (the main process never opens SimConnect for reads), `id` echo on every response, and the blocking 5 s `time.sleep` on no-session replaced with a reconnect backoff guard so the pipe is never held while the client is waiting.
- **Position reads** (`app/simconnect_position.py`): `read_position`, `read_position_minimal` and `camera_state_simconnect` are worker-first in packaged builds (`sys.frozen`), with `OPSROOM_PROBE_WORKER=1` forcing it in dev and `=0` disabling; in packaged builds a worker failure returns a structured not-ok and NEVER falls back to opening a main-process session (the main process stays a zero-SimConnect-read process). Dev/test runs keep the in-process path, so the deterministic suites are unaffected.
- **Teardown**: `app/main.py` `_opsroom_shutdown` now calls `simconnect_probe_client.shutdown()` after `close_session()`.
- **Tests**: `app/tests/test_probe_worker_isolation.py` (10 tests) covers the worker protocol in-process (ping/read/position/minimal/camera/shutdown, id echo, no-session fast-fail + backoff), the client protocol against a stub worker subprocess (round trips, 6-thread serialized concurrency, timeout -> kill -> backoff), and the dev-mode gate. Full suite: 74/74 + 116/116 + 20/20 + 19/19 + 10/10.
- **Live smoke (2026-08-14)**: `OPSROOM_PROBE_WORKER=1` end-to-end — worker spawned, protocol served; with the sim closed both worker and in-process paths return the identical structured `E_FAIL` not-ok in ~0.5 s (no hang, no crash). On-sim happy-path verification pending the user's next flight; the packaged exe (not rebuilt yet) will exercise `sys.frozen` -> worker-only reads.

## #109 — Community sharing should be ON and PUBLIC by default (LOGGED 2026-08-13)

**Symptom (live, 2026-08-13)**: after the v0.25.79 watchdog relaunch the user again had to run `/flight-visibility public` in Discord before the website map would show their live aircraft — the third time this drift bit. Both sides default to "discord/no sharing", so a fresh connect or an app restart leaves the map empty until the user manually flips to public.

**Root cause (two defaults + one drift)**:
1. **App side** (`app/settings_store.py` DEFAULT_SETTINGS, `community` block): `"visibility": "discord"` and `"share_flights": False`. New installs and any settings.json that never stored these fields get the conservative values.
2. **Server side** (`opsroom-website/admin-api/community.py` `_connect`): the `INSERT INTO app_links ... VALUES (?, ?, ?, 'discord', ...)` hardcodes `'discord'` on every (re)connect. Even a user who set public earlier keeps `public` only because `ON CONFLICT ... DO UPDATE` preserves it — but the *default* for a fresh link is discord.
3. **Drift**: the app's own `visibility` setting never reaches the server unless the user changes the dropdown while the app is running (#100 sync is best-effort POST on change) — a restart loses nothing app-side but the server copy stays as it was.

**Fix plan**:
- **App side**: change community defaults to `"visibility": "public"` and `"share_flights": True` in `DEFAULT_SETTINGS`; add a one-time normalization in `normalize_settings` so existing installs that never explicitly chose a value (or still carry the literal defaults) upgrade to public/on without clobbering an explicit user choice.
- **Server side**: `_connect` INSERT defaults `visibility` to `'public'` (and the `app_links` table DEFAULT where cheap), while keeping the `ON CONFLICT DO UPDATE` preserve-existing-visibility behavior so an explicit "discord"/"hidden" choice is never silently flipped back on reconnect.
- **Sync hardening**: on app start (or first live tick), push the app-side `{visibility, share_flights}` to `/api/community/settings` once so the server reflects the app immediately — the map must never require a manual Discord command again.
- **Acceptance**: fresh connect → website map shows the user airborne with zero manual steps; app restart → still public; explicit user choice of discord/hidden survives reconnects.

- **Status**: IMPLEMENTED (2026-08-13, source-side): app `DEFAULT_SETTINGS` community defaults flipped to `visibility: public` + `share_flights: True` with a one-time `_migrate_community_public()` marker migration (explicit post-upgrade choices survive); `_community_loop` now syncs the app-side visibility to the server once at startup so a fresh connect or restart never needs /flight-visibility; server `app_links`/`community_live` DDL defaults + `_connect` INSERT now default to 'public' while `ON CONFLICT DO UPDATE` preserves an explicit discord/hidden choice. Pending rebuild + VPS deploy.

## #110 — Pre-departure LOADSHEET auto-popup never fires while the completion popup works (LOGGED 2026-08-13, HIGH)

**Symptom (live, EZY8563 LGAV→LTBS 2026-08-13)**: the pre-departure "REVIEW & SIGN" modal did not pop up during the whole parked-at-gate window (~21:40:39–22:13:36 local), even though the post-arrival (Flight Completion) popup works reliably. The SIGN LOADSHEET button in the Live OFP panel also disappeared at times ("Live OFP sign button disappeared, did not get the pop up").

**What was verified working (so the backend is NOT the problem)**:
1. The backend gate (`loadsheet_ready` in `main.py` `_live_ofp_payload`) is logically correct — simulated against a parked pre-departure recorder meta: `state=RECORDING`, no takeoff, `_state.phase=PARKED` → `signature_locked=False`, `on_ground_phase=True`, plan present → **`loadsheet_ready=True`**.
2. The recorded samples prove the phase was PARKED for the entire pre-departure window (10,147 PARKED + 1,091 PUSHBACK samples before block-out at 20:13:36Z; first sample 19:40:39Z).
3. The watcher IS in the packaged build: `dist/OPS ROOM/_internal/app/static/opsroom.js` is byte-identical to source (md5 `92ba0b99…`), contains `startGlobalSignoffWatcher()` wired at init, `pollGlobalSignoff`, and the `loadsheet_ready` branch.
4. The endpoint was healthy: 537 ofp-live GETs in the window, all HTTP 200, ~12/min cadence (= watcher 5s + panel), response ~13ms (no 3s abort).

**Root cause (definitive, frontend latch-ordering)**: in `pollGlobalSignoff()` (`opsroom.js` ~2204):
```js
if(data.loadsheet_ready === true && !data.signed && !_signoffLoadsheetModalShown){
  _signoffLoadsheetModalShown = true;      // ← latched BEFORE the opener runs
  _lsLoadsheetToastShown = true;           // suppresses the panel's fallback toast
  openLoadsheetSignDialog();               // ← any refusal/exception here is swallowed
}
```
`_signoffLoadsheetModalShown` is set **before** `openLoadsheetSignDialog()` executes, and the whole watcher swallows every error (`catch(_error){}`). If the opener refuses (its own `signature_locked === true` → LOCKED toast path, `NO FLIGHT` path) or throws on the **first** eligible poll, the flag latches `true` for the entire flight — the popup is **permanently suppressed and never retries**, with zero diagnostics. The completion popup survives because its data (post-arrival) always satisfies the opener's guards, so its identical latch-ordering never trips. The button disappearance is the same gate: `signBtn.hidden = locked && !completionReady` with `locked = data.signature_locked === true` — and during the earlier mismatch window (old EWG39KK recorder with a takeoff time still active) `signature_locked` is correctly `true`, hiding the button; after the manual discard+restart at 21:40:39 the backend flips to ready but the popup was already one-shot latched (or one bad poll during the 21:45–21:50 slow window latched it) and never recovered.

**Definitive fix (surgical, frontend-only)**:
1. **Latch only after the dialog actually opens**: change `openLoadsheetSignDialog()` to return a boolean (`true` when `showModal()` succeeded), and in `pollGlobalSignoff` set `_signoffLoadsheetModalShown = _lsLoadsheetToastShown = true` **only when it returns true**. A refusal/exception then simply returns to the next 5s poll and retries — no permanent suppression.
2. **Don't pre-suppress the fallback toast**: only set `_lsLoadsheetToastShown = true` after a successful open; on failure leave it false so the OFP panel's "LOADSHEET READY — review and sign before departure" toast still shows on the next panel render.
3. **Diagnose instead of swallow**: in the watcher `catch`, when `loadsheet_ready === true` but the dialog did not open, `console.warn('SIGN-OFF: loadsheet_ready but dialog refused/failed', …)` (and mirror to `/api/logbook/events` via the existing `_event`-style path if cheap) so the next occurrence is visible in opsroom.log instead of invisible.
4. **Harden the opener's guards**: the loadsheet branch's `if(data.signature_locked === true && !data.signed)` LOCKED refusal is unreachable when `loadsheet_ready === true` (the backend gate already requires `not signature_locked`) — remove it as a silent killer or downgrade to a `console.debug`. Keep the `NO FLIGHT` guard but log once.
5. **Re-arm rule**: keep the one-shot-per-flight semantics (don't nag after the user closes without signing) but reset `_signoffLoadsheetModalShown` when `loadsheet_ready` drops to false and comes back true, AND on every recorder-id change (already done via `rid !== _signoffWatchFlightId`).

**Acceptance**: parked pre-departure with a matching SimBrief plan + Fenix loadsheet → the REVIEW & SIGN modal opens automatically once, from any screen; closing it without signing does not re-open; a single transient refusal/exception never kills the popup for the rest of the flight; the reason (ready→refused / ready→threw) is visible in the log.

- **Status**: IMPLEMENTED (2026-08-13, source-side): `openLoadsheetSignDialog()` now returns true only when the dialog actually opened (all refusals + showModal failures return false); `pollGlobalSignoff` latches `_signoffLoadsheetModalShown`/`_signoffCompletionModalShown` ONLY after a successful open, re-arms when readiness drops, and logs ready-but-refused via console.warn + a /api/logbook/events post instead of silently swallowing. Pending rebuild + live verification.

## #111 — Website live map: no flight route drawn; use SimBrief navlog for the dotted route (LOGGED 2026-08-13)

**Symptom**: the community live map (opsroom.live) shows only the aircraft marker — no route line, despite the #103 marker work. User asks: can we draw the dotted route from SimBrief?

**Verified today**: the SimBrief plan already carries everything needed — `cached_plan(user_ref)["navlog"]` is a list of fixes with `ident`/`latitude`/`longitude` (normalized floats), plus `route` (text) and `origin`/`destination`. But none of it leaves the app: `_live_payload()` (app/community.py:338) sends only callsign/origin/destination/aircraft/registration/heading/phase/lat/lon/alt/gs; the server POST /live (admin-api/community.py) stores no route column; GET /live returns none; `CommunityMap.jsx` renders markers only (no `L.polyline` anywhere).

**Fix (3 layers)**:
1. **App — `_live_payload()`**: pull the cached SimBrief plan's `navlog`, convert to a compact `route` list of `[lat, lon]` pairs, decimated to ≤64 points (navlogs can be 100+ fixes; 15s tick × few KB is fine but keep it small), falling back to `[origin, destination]` when navlog is missing. Include `route` in the POST body.
2. **Server — `admin-api/community.py`**: add a `route TEXT` column to `community_live` (JSON-encoded, `ALTER TABLE ... ADD COLUMN` guarded), store it on POST /live, and return it in GET /live. Keep it simple: latest write wins.
3. **Website — `CommunityMap.jsx`**: for each flight with a `route` array, draw a dashed `L.polyline(route, {dashArray: '6 8', color: ...})` added to the map; remove the layer when the flight leaves the feed (same reconcile loop that removes markers); keep the rotated aircraft marker on top; optionally extend the tooltip with the route's first/last waypoint.

**Acceptance**: on the public map, each airborne flight shows a dotted FMS-style route between its origin and destination (from SimBrief waypoints), the line vanishes when the flight lands/leaves the feed, and a fresh SimBrief plan change is reflected on the next tick. Route data is flight-data only, consistent with the public-visibility opt-in — no personal data.

- **Status**: IMPLEMENTED (2026-08-13): app `_live_payload()` adds a decimated (<=64 pt) `route` from the cached SimBrief plan navlog (fallback origin->destination); server `community_live` gained a `route TEXT` column (idempotent migration) stored on POST /live and returned in GET /live; `CommunityMap.jsx` draws a dashed cyan polyline per flight and removes it when the flight leaves the feed. Pending rebuild + VPS deploy.

## #112 — Website live map shows PUSHBACK while taxiing in after landing (LOGGED 2026-08-13)

**Symptom**: on the community live map, an arrival taxi-in is labeled PUSHBACK. The website renders `f.phase` verbatim (uppercased, sliced to 12 chars), so the mislabel originates in the app's display phase machine, `flight_watch._phase()`.

**Root cause (verified in code)**: the #85 gate-parked reset and the #42 PUSHBACK rule interact badly on arrival:
1. After landing, `airborne_seen=True` → phases LANDING ROLL / TAXI IN — correct.
2. If the aircraft stops with the parking brake set for **>90 s** during taxi-in (long hold, gate queue, waiting for marshaller), the #85 block at flight_watch.py:143-148 flips `airborne_seen=False` and returns PARKED — the "arrived" signature.
3. When taxiing resumes (gs ≥ 1.0), the #42 rule at flight_watch.py:129-132 sees `prev_phase == "PARKED"` and latches PUSHBACK — so the rest of taxi-in is broadcast as PUSHBACK to the website map (and can leak into the next departure's phase history).

**Fix proposal (surgical, flight_watch only)**: make the PUSHBACK-on-PARKED-movement rule fire only for a genuine first departure. Track a `turnaround`/`departed` latch: set `airborne_seen=False` via the gate-parked reset ONLY when that 90 s brake-stop is the *terminal* arrival (no movement between), and gate the `prev_phase == "PARKED" → PUSHBACK` rule on "never airborne this session" — once `airborne_seen` was True and the aircraft has landed, PARKED→movement is always TAXI (IN/around), never PUSHBACK, until a fresh departure context (new SimBrief plan identity or off-blocks at origin) re-arms it. Mirror the same guard in the logbook phase-ordering (#42) if it shows the same post-arrival behaviour.

**Acceptance**: after landing and any >90 s brake-stop during taxi-in, resuming movement shows TAXI IN (never PUSHBACK) on both the live map and the next departure's pushback classification; the FIRST departure of a session still shows PUSHBACK correctly.

- **Status**: IMPLEMENTED (2026-08-13, source-side): `flight_watch._phase` now latches `arrived` on the first on-ground poll after being airborne; the PARKED->movement rule only classifies PUSHBACK when NOT arrived (post-arrival movement is TAXI IN, never PUSHBACK), a fresh takeoff clears the latch, and a new SimBrief plan while parked re-arms the next departure. Verified by a 10-case phase-machine simulation (post-90s-brake-stop taxi-in now shows TAXI IN; next-departure pushback re-arms). Pending rebuild + live verification.

## #113 — Full PIREP / Live OFP weight actuals blank for Fenix after the flight ends (LOGGED 2026-08-14)

**Symptom (live)**: the completed flight's Full PIREP OFP COMPLETION section shows all ACTUAL weights blank (PAX, BAG/CARGO, PAYLOAD, ZFW, TOW, LDW) even though the Live OFP panel showed real values during the flight. The same blanks appear in the live panel for a completed flight once the Fenix EFB cache goes cold.

**Root cause (three defects, verified against the EZY8563 Fenix entry)**:
1. **Fenix never fills the FSUIPC/SimConnect weight SimVars** (FSUIPC 0x30C0 is empty on Fenix), so the `off`/`on` operational snapshots carry `gross_weight_lb: null` — the builder's TOW/LDW snapshot fallback has nothing to read.
2. **The `out` snapshot is never captured**: `_out_snapshots.setdefault("out", _op_snapshot(...))` is a no-op because the recorder template already ships `"out": {}` — so ZFW's `out.calculated_zfw_lb` fallback was always None (blank ZFW for EVERY aircraft, not just Fenix).
3. **The completed-entry endpoint is blind to the live sources**: `GET /api/logbook/{id}/ofp-completion` builds with `build_live_ofp_actuals(plan, None, completed_entry=entry)` — no `fenix_loadsheet`, no `loading_progress`, and the in-memory last-known-good fill (#86) is only applied in `_live_ofp_payload`, not here. The Fenix EFB FINAL loadsheet (TOW/ZFW/LDW) and GSX/Fenix loading (pax/cargo) are in-memory caches that go cold after landing / app restart, so nothing durable remained for the PIREP.

**Fix (implemented 2026-08-14, source-side)**:
- `app/logbook.py`: `_op_snapshot` now accepts `fenix=` and stores the Fenix EFB FINAL loadsheet values (`fenix_zfw_kg`, `fenix_tow_kg`, `fenix_ldw_kg`, `fenix_max_*_kg`) plus the Fenix loading values (`fenix_pax_loaded`, `fenix_cargo_loaded_kg`) into every event snapshot (start/out/off/on/in). A new `_fenix_snapshot_extras()` helper reads only the cheap warmed caches (`loadsheet_final_cached` + `automation_status`) — never blocks a recorder tick, never raises. Fixed the `out`-snapshot `setdefault` bug with a guarded direct assignment.
- `app/ofp_actuals.py` `_weights_section`: the completed-entry path now falls back to the recorded Fenix values first (ZFW from out/off/on, TOW from off/out, LDW from on/off, with recorded maxes; PAX and BAG/CARGO from the out/off snapshots), so the Full PIREP, its PDF and the completion REVIEW & SIGN modal all show the same actuals the Live OFP showed — durably, surviving restarts. The live `fenix_loadsheet` and `loading_progress` args still win when present; manual overrides still outrank everything.
- No main.py change needed: the `ofp-completion` endpoint already routes through `build_live_ofp_actuals`, which now resolves the recorded values from the entry's own snapshots.

**Verified**: the real EZY8563 completed entry, with the recorded-Fenix snapshots injected as the new capture would store them, now renders PAX 163 / BAG 2,445 / PAYLOAD 15,485 / ZFW 59,514 / TOW 65,093 / LDW 62,631 (source "fenix ... (recorded snapshot)"). New regression test `test_recorded_fenix_snapshots_fill_completed_entry` in `test_ofp_overrides.py` (76/76 pass). Existing flights recorded before this fix keep their blank actuals (the values were never captured); the next flight captures them.

**Acceptance**: next Fenix flight (or any aircraft) — open the Full PIREP after block-in; WEIGHTS ACTUAL column must show the same values the Live OFP panel displayed, even after an app restart.

## #114 — LAN EFB printer list is empty and shows “Printer check unavailable” (LOGGED 2026-08-15)

- **Severity**: High for hardware-EFB users (the host browser can print, but the remote EFB cannot select or trigger a printer).
- **Symptom**: A hardware EFB connected to the MSFS PC over LAN shows the System printer card, but the dropdown is empty and the status reads `Printer check unavailable`. The same printer is visible and configured in the OPS ROOM browser on the MSFS PC.
- **Root cause**: `/api/printer/status`, `/api/printer/list`, and `/api/printer/test` all called `_require_local_host(request)`. That guard correctly protects full host settings, but it also rejected every request from the EFB with HTTP 403. The frontend converted that non-2xx response into the generic “Printer check unavailable” message. Printer settings were also saved through the host-only `/api/settings` endpoint, so remote selection could never persist.
- **Fix**: Keep `/api/settings` host-only, but allow the narrow printer status/list/test routes through the existing LAN/device-security middleware. Add `/api/printer/settings`, which accepts only the normalized `printing` section, and expose the non-secret printer selection state through `/api/settings/public`. When device pairing is enabled, the existing paired-device gate still protects all remote printer operations.
- **Acceptance**: From a paired or otherwise enabled LAN EFB, System shows the host printer list, selecting a printer saves successfully, and TEST PRINT is executed by the MSFS PC. The desktop host settings flow remains host-only.
- **Status**: Implemented source-side (2026-08-15); pending legacy bundle rebuild, packaged-app rebuild, and hardware-EFB verification.

## #115 — Thermal receipt printers: send auto paper-cut (Esc/POS) after print (FEATURE, for v0.26.0) (LOGGED 2026-08-15)

- **Source**: Peter (hardware EFB beta tester) — printing now works, but many thermal/receipt printers support a paper-cut command, and users currently have to tear manually at the printed `snip here` marker.
- **Request**: after a receipt finishes printing, send the Esc/POS cut sequence (`GS V`, bytes `0x1D 0x56 0x42` for a full cut, `0x41` for partial) so the printer cuts the paper itself.
- **Design sketch**: in `app/printer_client.py`, append the cut bytes to the raw print payload in `print_receipt` (and offer it in `print_text`), behind a per-printer **auto-cut** toggle (default OFF so printers without cut support are unaffected; store with the existing printer settings). Keep printing the `snip here` marker as a visual fallback for non-cut printers. The EFB/legacy bundle must pick up the toggle via the public settings endpoint (#114 pattern).
- **Acceptance**: with auto-cut ON on a cut-capable thermal printer, the receipt emerges already cut (no manual tear); with it OFF, behavior is unchanged.
- **Status**: LOGGED — not started (scheduled for v0.26.0).

## #116 — UI feedback: home grid density, tile reorder/favorites, cleaner font, softer borders, readability + dark scrollbars (FEATURE, for v0.26.0) (LOGGED 2026-08-16)

- **Source**: community beta tester feedback (experienced pilot, mid-flight context). Decision: implement as requested, no theme toggle offered. The monospace look stays only where it belongs (data readouts); labels and subheadings move to a cleaner standard font.
- **Items (verified against code)**:
  1. **Home grid fits on screen without scrolling** — sidebar (`--rail`, `.nav-item` list) already lists the same modules as `.module-grid`, so it is redundant; shrink `.module-tile` min-height (currently 10.5rem, plus inset `3px` shadow) and enlarge `.module-icon` (4.8rem box / 3.6rem SVG) so the whole grid is visible.
  2. **Drag-and-drop reordering + favoriting of home tiles** — module list is a JS array in `opsroom.js`; persist order + favorites in settings store / localStorage, pinned tiles first. v1: star/favorite pin (touch-safe); drag-reorder later. Must survive the legacy CoherentGT bundle.
  3. **Font**: `body` uses `--terminal` (Cascadia Mono/Consolas) everywhere; headers use `--condensed` with uppercase + wide letter-spacing; labels go as small as 0.48rem. Plan: keep monospace for data values only, move labels/subheadings to a cleaner sans, bump the 0.48–0.58rem text up so key metrics contrast.
  4. **Reduce heavy white/grey outlines** — borders come from `--line` / `--line-bright` plus inset shadows (`inset 0 0 0 3px #080a07` on tiles, Camera Bridge overlay similar). Soften via the CSS vars + targeted rules; do not wash out panel legibility.
  5. **Small grey text + dark scrollbars** — METAR strings are `--muted` at ~0.6rem; brighten `--muted` slightly and add global `::-webkit-scrollbar` + `scrollbar-color` dark styling. Note: custom scrollbars may not render in in-sim CoherentGT, but will work in desktop/browser/iPad.
- **Acceptance**: on a fresh install the home screen shows all modules without scrolling on a typical desktop; favorites stay pinned at top across restarts; table data stays monospace while labels/subheadings are a clean sans; METAR and muted text is readable; scrollbars follow the dark theme; the legacy EFB/tablet build matches.
- **Status**: LOGGED — not started (scheduled for v0.26.0).

## #117 — Website live map: aircraft markers all point North; heading glyph and junk-position issues (LOGGED 2026-08-16)

- **Symptom**: on opsroom.live's community map every aircraft marker appears to point North regardless of its actual heading.
- **Investigation (2026-08-16)**: the heading pipeline is fully wired and live — app `_live_payload()` (opsroom-app/source/app/community.py:368) reads `heading`/`heading_deg`/`true_heading_deg` and POSTs it; admin-api stores it in `community_live.heading` (idempotent migration) and returns it in GET /live; the DEPLOYED bundle on opsroom.live contains `rotate(${n}deg)` and re-applies it via `setIcon` on every 15s poll (verified in the live JS, not a stale build). FSUIPC heading math is correct per SDK (*360/(65536*65536)).
- **Root causes**:
  1. **Glyph orientation**: `PLANE_SVG` in `CommunityMap.jsx` is the Material "send" paper-plane icon, whose nose points NE (45°) at zero rotation — so every marker renders 45° clockwise of its true heading.
  2. **Junk test rows pollute the feed**: the live feed currently has two DLH9535 rows with heading ≈ 0/360; one is parked at lat 0.0004 / lon 0.0139 (≈ 0,0 — Gulf of Guinea), which the telemetry validator only rejects when BOTH |lat|<0.001 AND |lon|<0.001 (0.0139 slips through). With all headings ≈ 0/360, every marker renders in the same default orientation, reading as "everything points North."
- **Fix proposal**:
  1. Replace the plane glyph with a proper top-down aircraft that points straight up at 0°, or rotate the existing glyph by −45° so heading 0 = North.
  2. Server-side ingest filter: reject live-feed rows within ~0.1° of (0,0) (and any PARKED position far from a known airport) so junk/test data stops reaching the public map.
  3. When `heading` is null, fall back to `track_deg` or omit rotation rather than rendering a misleading fixed orientation.
- **Acceptance**: an airborne flight flying East renders pointing East; parked test rows near (0,0) never appear on the public map; real flights show varied rotations.
- **Status**: LOGGED — not started (website repo change; verify a real airborne row's `heading` in the VPS DB before building to confirm data variety).

## #118 — Bot descent briefing DM: include ATIS (VATSIM first, ATIS.guru fallback) alongside METAR/TAF/NOTAMs (FEATURE, for v0.26.0) (LOGGED 2026-08-16)

- **Source**: user feedback — at top of descent the bot DM already sends METAR, TAF and NOTAMs; ATIS should be included too.
- **Investigation (2026-08-16)**: `_descent_briefing_dm` (ops-control-bot/src/bot/services/community.py) already builds the DM with METAR + TAF (NOAA) and NOTAMs (notam_service), triggered by the app's `descent` event (app/logbook.py:1257). VATSIM ATIS fetch already exists (`bot/api/__init__.py` → `fetch_vatsim_atis`, returns `atis_message`/`atis_type`/`atis_code`). ATIS.guru has NO public API (Blazor/SignalR app) — but the desktop app already ships a working scraper: `fetch_realworld_atis` (opsroom-app/source/app/weather_client.py:367) hits `https://atis.guru/atis/{icao}`, extracts Arrival/Departure sections, and falls back to a METAR-generated ATIS.
- **Fix proposal (bot-only)**:
  1. Mirror the app's `fetch_realworld_atis` ATIS.guru scraper + METAR fallback into the bot (e.g. `bot/api/atisguru.py`).
  2. In `_descent_briefing_dm`, add an **ATIS section at the top**: VATSIM first (`fetch_vatsim_atis`), ATIS.guru scrape fallback, then "ATIS unavailable" — keeping the existing best-effort pattern (one source failing never blanks the others).
  3. Final DM order: ATIS → METAR → TAF → NOTAMs.
- **Acceptance**: at TOD, the DM includes an ATIS section (VATSIM when a controller broadcasts one, real-world D-ATIS from ATIS.guru otherwise, or a clear unavailable line) above the existing METAR/TAF/NOTAMs, and a failed ATIS source never suppresses the other weather data.
- **Status**: LOGGED — not started (scheduled for v0.26.0; bot repo change only).

## #119 — Website leaderboard: sort by flight hours (descending default) + per-column sortable columns (FEATURE, for v0.26.0) (LOGGED 2026-08-16)

- **Source**: user feedback — the developer (exzonom) is always at the top because the leaderboard ranks by flight count first (`ORDER BY flights DESC, hours DESC` in opsroom-website/admin-api/community.py:509), and the community is brand new (all rows are < 7 days old). Not a bug or bias — real data, tiny sample. The owner must NOT be excluded from the board (decision: keep exzonom visible).
- **Decision**: change the ranking so time flown is the primary signal, and let visitors re-sort the columns themselves.
- **Fix proposal**:
  1. **API default sort** (`opsroom-website/admin-api/community.py` `community_leaderboard`): change to `ORDER BY hours DESC, flights DESC` — flight hours first, flights as tiebreaker. Both the Home page (`Home.jsx` → `useCommunityLeaderboard('alltime')`, top 5) and the full `/leaderboard` page (`Leaderboard.jsx`) consume the same hook, so this single server-side change sets the default for both.
  2. **Sortable columns on the full leaderboard** (`Leaderboard.jsx`): make FLIGHTS, HOURS, AVG LANDING and BEST LANDING headers clickable to toggle ascending/descending, with a visual sort indicator (arrow on the active column). Default = HOURS descending (matches the API). Keep RANK and PILOT fixed.
  3. Sort state can be client-side (the API already returns the full top-50 list, so no new endpoint or query params strictly needed) — simplest: sort the already-fetched array in the component.
- **Acceptance**: exzonom stays on the board; a pilot with more hours but fewer flights ranks above a pilot with more flights but fewer hours by default; clicking a column header re-sorts immediately with a clear active-column arrow; default state shows hours descending on both Home and /leaderboard.
- **Status**: LOGGED — not started (website repo change only; no app/bot changes needed).
