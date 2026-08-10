# OPS ROOM v0.25.2 Bug Tracker

Reported bugs and tasks for the next patch.

Relevant skills from `.kiro/skills/`:
- `focused-fix` — systematic deep-dive repair across multiple files
- `senior-frontend` — Canvas 2D rendering, DOM manipulation
- `minimalist` — avoid over-engineering, prefer simple correct changes
- `tc-tracker` — track technical change lifecycle across sessions

---

## 1. Announcements Fire in Menu / Loading Screen

**Skills:** `focused-fix`, `minimalist`, `tc-tracker`

**Severity:** Medium (annoying, false alarms)

**Symptoms:** RAAS callouts and cabin announcements trigger while the user is still in the MSFS main menu, aircraft selection, or loading screen — before the flight has started.

**Root Cause:** MSFS defaults the aircraft position to DGTK (Dibba, Oman, ~25.62°N, 56.24°E) when not in an active flight. The existing loading-screen gate (`announcements.py:470`, `abs(lat) < 0.001 and abs(lon) < 0.001`) only catches the 0,0 position during sim load. Once the sim settles at DGTK, every gate check passes (valid lat/lon, on ground, GS near zero, position stable >1.25s), so both RAAS and cabin announcements arm.

### Proposed Fix

Add a **hard-coded MSFS menu exclusion zone** around the DGTK default position. This is the simplest fix that doesn't depend on SimBrief configuration.

**Implementation points:**

| Layer | File | Approx line | Change |
|-------|------|-------------|--------|
| RAAS session gate | `app/raas.py` | `_session_gate()` ~270 | Add check: if position is within 5 NM of DGTK, return False |
| Cabin announcer stable session | `app/announcements.py` | `_stable_live_session()` ~445 | Add same DGTK check alongside the existing 0,0 check |
| (Optional) Telemetry provider | `app/telemetry_provider.py` | ~403 | Could also reject at the telemetry level, but better to keep the gate in each consumer |

**Constants:**
- `MSFS_MENU_LAT = 25.618` (DGTK latitude)
- `MSFS_MENU_LON = 56.242` (DGTK longitude)
- `MSFS_MENU_EXCLUSION_NM = 5.0` (radius around DGTK to suppress announcements)

**Haversine distance** from aircraft position to DGTK: if `distance_nm < MSFS_MENU_EXCLUSION_NM` and aircraft is on the ground → reject.

**Why this is safe:** DGTK (Dibba Airport) is a small regional strip in Oman. No OPS ROOM user operates a Fenix/PMDG airliner out of DGTK. The exclusion zone is small enough to not interfere with real operations (e.g., OMDB/Dubai departures are ~70 NM away).

**Alternative considered (Simbrief origin gate):** Reject until aircraft is at or near the SimBrief origin airport. This is more precise but breaks for users who don't use SimBrief, breaks for pattern work / touch-and-go sessions, and requires additional state management. The DGTK exclusion is simpler and covers the vast majority of false triggers.

### Files to modify (do NOT modify until instructed):
- `app/raas.py` — `_session_gate()` function
- `app/announcements.py` — `_stable_live_session()` function

---

## 2. Resolved: Sim Stutter on Refresh (v0.25.2)

**Status:** ✅ Fixed in v0.25.2

**Root Cause:** `_read_simconnect_lvars()` called `Request.value → get_data()` which polled `time.sleep(0.01)` up to `_attemps=10` times per LVar. With 33 Fenix LVars, this blocked the telemetry `_LOCK` for up to 3.3 seconds, stalling the recording loop, Flask endpoints, and frontend refresh.

**Fix:** `telemetry_provider.py:1349` — added `_attemps=3` to the `Request()` constructor, reducing max polling from 100ms → 30ms per LVar (worst-case ~1s for 33 LVars, typical ~100ms). Confirmed tested and no longer present.

---

## 3. Taxi-Out Detected at Pushback (3 kt Threshold Too Low)

**Skills:** `focused-fix`, `minimalist`, `tc-tracker`

**Severity:** Low (false phase transition)

**Symptoms:** The system detects TAXI OUT during pushback because pushback tugs move the aircraft at ~3 kt, which is equal to the current `TAXI_MOVING_MIN_GS_KT` threshold.

**Root Cause:** The taxi motion threshold is set to 3.0 kt across three systems. Pushback typically moves at 3-4 kt, so the system cannot distinguish pushback motion from genuine taxi motion at the threshold boundary.

**Fix:** Raise the threshold from 3.0 kt to 5.0 kt in all three locations:

| Layer | File | Line | Current | Change |
|-------|------|------|---------|--------|
| RAAS taxi detection | `app/raas.py` | 109 | `TAXI_MOVING_MIN_GS_KT = 3.0` | → `5.0` |
| Cabin announcer taxi motion | `app/announcements.py` | 1445 | `gs > 3.0` | → `gs > 5.0` |
| Cabin announcer post-pushback taxi | `app/announcements.py` | 1448 | `gs > 3.0` | → `gs > 5.0` |
| Logbook gs counter | `app/logbook.py` | 717 | `taxi_speed > 3.0` | → `taxi_speed > 5.0` |
| Logbook motion candidate | `app/logbook.py` | 734 | `taxi_speed > 3.0` | → `taxi_speed > 5.0` |
| Logbook event message | `app/logbook.py` | 724 | `GS >3kt` | → `GS >5kt` |

**Safety:** 5 kt (~9 km/h) is still well below normal taxi speed (15-25 kt) and will not delay any real taxi-out detection. Pushback rarely exceeds 4 kt, so 5 kt provides a clean margin.

---

## 4. Fenix Identified as Generic Aircraft in Black Box

**Skills:** `focused-fix`, `tc-tracker`

**Severity:** High (critical functionality lost)

**Symptoms:** Fenix A32X shows as "GENERIC" in the Black Box systems/controls UI. Sidestick crosshair, throttle levers, flaps, and other aircraft-specific controls don't render or show `—` (no data). The Flight Watch bar shows "GENERIC FALLBACK" instead of "FENIX A319/A320/A321 • READ ONLY".

**Root Cause:** The aircraft identification pipeline has two detection stages with different matching logic:

1. **Legacy `detect_adapter()`** (`app/aircraft_adapters.py:28-34`) — scans SimConnect `TITLE`, `ATC_MODEL`, `ATC_TYPE` for "FENIX", "FNX". Output is stored in telemetry but overridden later.
2. **Primary `detect_family()`** (`app/aircraft_adapter_catalog.py:424-447`) — the authoritative source. Checks same fields for tokens `"FENIX"`, `"FNX32"`, `"FNX A3"`. Returns `"fenix_a32x"` on match, `"generic"` otherwise.
3. **`_stable_family()`** (`app/addon_telemetry.py:35-76`) — wraps `detect_family()` with hysteresis:
   - Tier 1 (5-second grace): If current identity is `"generic"` but contains only Fenix-transient tokens, sticks to Fenix for 5s.
   - Tier 2 (adapter session lock): After confirmed LVar reads, holds Fenix identity indefinitely until aircraft change.

**Likely failure scenario:** Fenix's SimConnect `TITLE` and `ATC_MODEL` fields may return transient/generic values (e.g., "A320", "AIRBUS", "UNKNOWN") during certain phases. The 5-second Tier 1 grace window may expire before the real identity stabilizes, or the session lock may not engage properly because the LVar read path (`_read_simconnect_lvars`) was recently refactored and the lock engagement at `addon_telemetry.py:524-526` may have a logic gap.

**Investigation needed:**

| Check | File | Line | What to verify |
|-------|------|------|----------------|
| Token match for Fenix | `aircraft_adapter_catalog.py` | 428 | Does SimConnect return `"FENIX"`, `"FNX32"`, or `"FNX A3"` in any field? |
| Transient token list | `addon_telemetry.py` | 27-30 | Does SimConnect title contain only items from `_FENIX_TRANSIENT_IDENTITY_TOKENS`? |
| Grace window | `addon_telemetry.py` | 55-63 | Is 5 seconds enough, or does SimConnect never return the real identity? |
| Session lock after LVar | `addon_telemetry.py` | 524-526 | Does the new `_read_simconnect_lvars` path trigger `_lock_adapter_session()`? |
| Adapter overwrite order | `addon_telemetry.py` | 388-395 | Is `result["aircraft_adapter"]` being overwritten correctly? |
| Generic early return | `addon_telemetry.py` | 396-397 | If family is generic, does it return early before any LVar enrichment? |

**Immediate suspect:** `addon_telemetry.py:396-397` — if `detect_family()` returns `"generic"`, the function returns early at line 397 **without** reading Fenix LVars, so `addon_state`, `control_provenance`, and aircraft-specific field overrides never get populated. The session lock at line 524-526 is **after** this early return and never executes.

**Proposed fix:** Add a secondary Fenix detection before the generic early return — if the aircraft title contains any of `_FENIX_TRANSIENT_IDENTITY_TOKENS` and SimConnect is available, attempt the LVar read anyway. If LVars succeed with Fenix-specific values, force the family to `"fenix_a32x"` and lock the session.

---

## 5. Black Box Track Tab — Actual Track Offset from Planned Track

**Skills:** `senior-frontend`, `focused-fix`, `minimalist`, `tc-tracker`

**Severity:** Medium (visual/UX — data is intact, rendering is misleading)

**Symptoms:** The actual aircraft position pointer and recorded track are visibly offset from the planned route on the Track tab Canvas. The planned track appears to start at the correct origin and proceed to the destination, but the actual track (drawn from recorded telemetry samples) does not overlap it as expected.

**Root Cause:** Multiple interacting factors in the Canvas 2D equirectangular projection used by `drawBlackBoxTrack()`:

1. **Bounding box computed from both planned + actual tracks jointly** — The `blackBoxExtent()` function in `opsroom.js:3366-3389` takes the union of both coordinate sets. If the planned route spans thousands of NM (e.g., KJFK→EGLL) but the recording only covers taxi-out + takeoff (first few NM), the bounding box is dominated by the full planned route, and the actual track (which should overlay the origin end) gets compressed into a tiny region near the edge. The planned route itself spans the full chart width, so any offset between planned and actual at the origin end appears greatly amplified.

2. **Equirectangular projection distortion at higher latitudes** — `x = (lon - minLon) * scale`, `y = (maxLat - lat) * scale`. This simple linear mapping treats 1° longitude as equal width at all latitudes, but in reality 1° longitude = ~60 NM × cos(lat). At 50°N, 1° of longitude is ~39 NM, while 1° of latitude is always ~60 NM. The result is that North Atlantic routes (common in airliner ops) are horizontally compressed, making the planned route appear angled differently than the actual flight path.

3. **Planned route is a static polyline of navlog waypoints** — SimBrief navlog waypoints are connected by straight lines in the order listed. Actual flight paths follow ATC vectors, SID/STAR transitions, and intercepts that don't match the great-circle path between waypoints. The planned track shows the filed route, while the actual track shows where the aircraft actually flew — these naturally diverge.

4. **No margin/padding in the extent** — The projection compute bounds are tight to the data. If the planned route includes a waypoint slightly east of the actual track at the origin, the map gets shifted, and the origin end of the actual track appears offset.

**Proposed Fix:**

| Item | Change | File | Lines |
|------|--------|------|-------|
| A | **Decouple bounding boxes:** compute extent separately for planned route (full) and actual track. Use the actual track's extent when drawing the actual track, and overlay the planned route within that same viewport. | `app/static/opsroom.js` | `blackBoxExtent()` → `drawBlackBoxTrack()` ~3366-3389 |
| B | **Add padding:** add 5-10% margin to the bounding box so track lines don't clip at Canvas edges. | `app/static/opsroom.js` | `blackBoxExtent()` ~3366 |
| C | **Optionally, switch from equirectangular to Mercator projection** for the actual positions to reduce latitude distortion. Or keep equirectangular and acknowledge the distortion remains. | `app/static/opsroom.js` | `drawBlackBoxTrack()` |

**Investigation needed on the frontend:**
- Confirm that `drawBlackBoxTrack()` in `opsroom.js:3366` currently uses a single combined extent from `blackBoxExtent()`.
- Determine whether the Canvas auto-scales or uses a fixed viewport.

The core UX issue is that the planned route overpowers the viewport extent, making the short actual track appear tiny and misaligned. Fix A (separate extents) is the highest impact.

---

## 6. Black Box Track Tab — START/END Labels Tied to Aircraft Pointer Instead of Planned Route

**Skills:** `senior-frontend`, `focused-fix`, `minimalist`, `tc-tracker`

**Severity:** Medium (visual/UX — labels move with playback instead of being fixed)

**Symptoms:** The START label (origin airport code) and END label (destination airport code) in the Track tab Canvas are positioned at the first/last point of the **actual recorded track**, not at the origin/destination of the **planned route**. As a result:
- The END label moves with the aircraft during playback (tied to the last recorded sample, which is the current aircraft position), instead of being fixed at the destination airport on the planned route.
- The START label is similarly positioned at the first telemetry sample (which may be at the gate or ramp), not at the origin airport waypoint.

**Root Cause:** In `opsroom.js:3382-3386` (`drawBlackBoxTrack()`):

```js
const start = map(rows[0]), end = map(rows.at(-1));  // rows = telemetry samples
// ...
ctx.fillText(`START · ${origin}`, start[0] + 7*dpr, start[1] - 7*dpr);
ctx.fillText(`END · ${destination}`, end[0] + 7*dpr, end[1] - 7*dpr);
```

`rows` is the actual recorded telemetry samples (`blackBoxSamples`), not the planned navlog waypoints. The text content shows the correct origin/destination ICAO codes, but the position is tied to the first/last actual position, which moves with playback cursor.

Additionally, the same issue applies to the circle markers at line 3383:
```js
for(const point of [start,end]){ ctx.arc(point[0], point[1], 4*dpr, ...) }
```

**Proposed Fix:**

| Item | Change | File | Lines |
|------|--------|------|-------|
| A | **Anchor START label + circle to planned navlog origin** — use `planned[0]` (first navlog waypoint) when available, fall back to current `rows[0]` behavior otherwise. | `app/static/opsroom.js` | 3382, 3383, 3385 |
| B | **Anchor END label + circle to planned navlog destination** — use `planned[planned.length-1]` (last navlog waypoint) when available, fall back to current `rows.at(-1)` behavior. | `app/static/opsroom.js` | 3382, 3383, 3386 |
| C | **Fix the circle markers** — change `for(const point of [start,end])` to iterate over the correct planned-route positions instead of the actual-track positions. | `app/static/opsroom.js` | 3383 |

**Landing zone:**
- `start` variable should be computed as `planned.length >= 1 ? map(planned[0]) : map(rows[0])`
- `end` variable should be computed as `planned.length >= 1 ? map(planned[planned.length-1]) : map(rows.at(-1))`
- The circle-drawing loop and label text are already using these variables, so the fix is limited to lines 3382-3383.

---

## 7. In-Sim Replay Button Does Not Teleport Aircraft (CRITICAL)

**Skills:** `focused-fix`, `tc-tracker`

**Severity:** **Critical** (replay feature non-functional)

**Symptoms:** Clicking "PLAY IN-SIM" in the Black Box Track tab shows a confirmation dialog, the UI updates to show "IN-SIM PLAYING", but the aircraft in Microsoft Flight Simulator does not move — it stays at its current position and attitude. The replay loop diagnostics may show `frame_callbacks_per_second` > 0 indicating the loop is running, but the aircraft ignores the position writes.

**Root Cause — Three interacting failure modes:**

### 1. `sm.set_pos()` (INITPOSITION) relies on a broken 3rd-party wrapper

The initial teleport at `simconnect_position.py:1321` calls `sm.set_pos()` from the third-party SimConnect Python library. This library is distributed as a precompiled DLL + pyc — the source is unavailable. The `set_pos()` method creates a `SIMCONNECT_DATA_INITPOSITION` struct internally and calls `SimConnect_SetDataOnSimObject`. However:

- Many complex add-on aircraft (Fenix, PMDG, iniBuilds, FBW) **explicitly ignore INITPOSITION** because they manage their own flight-model state.
- The struct layout or `SIMCONNECT_DATA_SET_FLAG` may be incorrect for the installed MSFS version.
- There is **no position readback verification** — `set_pos()` returns `ok` but the aircraft may not have moved.
- The SimConnect Python wrapper's internal `SIMCONNECT_DATA_INITPOSITION` definition is opaque and cannot be debugged.

### 2. No custom `SIMCONNECT_DATA_INITPOSITION` ctypes struct

Unlike SkyDolly which defines its own struct and manages the entire SimConnect data flow directly, OPS ROOM delegates the critical initial teleport to an unreliable third-party wrapper. The `SimConnectDataInitPosition` struct that does exist in `opsroom_native_bridge.py:117-127` is only used for the native API SimObject creation harness, not for replay.

### 3. Per-frame streaming may be silently rejected

Even if the initial teleport partially works, the per-frame `SetDataOnSimObject` with custom `_ReplayPose` struct (lat, lon, alt, pitch, bank, heading, velocities) may be rejected by complex add-ons that expect specific SimVars or a specific update sequence.

### Comparative Analysis: SkyDolly's Working Approach

SkyDolly (in `skydolly/`) uses a bulletproof 3-step sequence:

| Step | SkyDolly | OPS ROOM |
|------|----------|----------|
| **1. Freeze** | `FREEZE_LATITUDE_LONGITUDE_SET=1`, `FREEZE_ALTITUDE_SET=1`, `FREEZE_ATTITUDE_SET=1` via `TransmitClientEvent` | Same 3 freeze events via `replay_set_freeze()` |
| **2. INITPOSITION** | Custom ctypes struct with explicit fields. Writes to `SIMCONNECT_OBJECT_ID_USER` via `SimConnect_SetDataOnSimObject` using a known-good DataDefinition (`"Initial Position"` with `SIMCONNECT_DATATYPE_INITPOSITION`). | Delegates to `sm.set_pos()` — opaque 3rd-party wrapper. The DataDefinition is created internally and cannot be inspected. |
| **3. Per-frame pose** | Custom `PositionAndAttitudeUser` DataDefinition with 9 fields (lat, lon, alt, pitch, bank, heading, vel_x, vel_y, vel_z). Written every frame via `SetDataOnSimObject`. Aircraft frozen during replay. | Custom `_ReplayPose` struct with same 9 fields, written every frame via `SetDataOnSimObject` via `sm.dll.SetDataOnSimObject()`. Aircraft frozen during replay. |
| **4. On-ground correction** | **ASRA system:** When `on_ground=true`, continuously reads `Plane Alt Above Ground Minus CG` and adjusts written altitude by the offset to prevent underground placement. | **None.** Uses raw recorded MSL altitude, which may place aircraft underground if terrain elevation differs. |
| **5. Position readback** | **None explicitly** — relies on freeze keeping aircraft in place. | **None** — no verification after write. |
| **6. Frame events** | Uses its own SimConnect session with Frame event subscription. | Uses the primary telemetry SimConnect session for Frame events, which may contend with ongoing telemetry reads. |

**Key difference:** SkyDolly controls its own DataDefinitions end-to-end. OPS ROOM uses a 3rd-party wrapper for step 2. The per-frame write (step 3) is effectively identical.

### Proposed Fix

**Approach:** Replace `sm.set_pos()` with a direct ctypes `SimConnect_SetDataOnSimObject` call using our own `SIMCONNECT_DATA_INITPOSITION` struct, exactly as SkyDolly does.

| Item | Change | File | Lines |
|------|--------|------|-------|
| A | **Define `SIMCONNECT_DATA_INITPOSITION` ctypes struct** — 8 fields: lat(FLOAT64), lon(FLOAT64), alt(FLOAT64), pitch(FLOAT64), bank(FLOAT64), heading(FLOAT64), on_ground(INT32), airspeed(FLOAT64) | `app/simconnect_position.py` | ~1299 (alongside existing `_ReplayPose` struct) |
| B | **Create DataDefinition for Initial Position** — `SimConnect_AddToDataDefinition(h, def_id, "Initial Position", None, SIMCONNECT_DATATYPE_INITPOSITION)` during session setup | `app/simconnect_position.py` | ~1240 (in replay setup area) |
| C | **Replace `sm.set_pos()` with direct `SetDataOnSimObject`** — use the new DataDefinition with `SIMCONNECT_OBJECT_ID_USER` | `app/simconnect_position.py` | ~1321 (the `if initial:` branch) |
| D | **Add on-ground altitude correction** — if `on_ground`, read `Plane Alt Above Ground Minus CG` and subtract from written altitude (mirror SkyDolly's ASRA) | `app/simconnect_position.py` | ~1330 (after INITPOSITION write) |
| E | **Add position readback verification** — after INITPOSITION, read `Plane Latitude`/`Plane Longitude` to confirm the aircraft moved. Log warning if discrepancy > 0.1°. | `app/simconnect_position.py` | ~1325 |
| F | **Dedicated SimConnect session for replay** — create a separate session so replay Frame events don't contend with telemetry reads | `app/simconnect_position.py` | `replay_subscribe_frame()` ~1181 |

**Backend files to modify:**
- `app/simconnect_position.py` — the core replay SimConnect writes
- `app/black_box_replay.py` — main replay controller (minimal changes, mostly plumbing)

**SkyDolly reference files:**
- `skydolly/src/Plugins/Connect/MSFSSimConnectPlugin/src/MSFSSimConnectPlugin.cpp` — `onInitialPositionSetup()` (line 176), `sendAircraftData()` (line 392)
- `skydolly/src/Plugins/Connect/MSFSSimConnectPlugin/src/SimVar/PositionAndAttitude/SimConnectPositionAndAttitudeUser.h` — pose struct
- `skydolly/src/Plugins/Connect/MSFSSimConnectPlugin/src/SimVar/Position/SimConnectPositionCommon.h` — lat/lon/alt
- `skydolly/src/Plugins/Connect/MSFSSimConnectPlugin/src/SimVar/Attitude/SimConnectAttitudeCommon.h` — pitch/bank/heading/velocities
- `skydolly/src/Plugins/Connect/MSFSSimConnectPlugin/src/SimVar/Attitude/SimConnectAttitudeInfo.h` — on_ground field (Bool → INT32)

---

## 8. Black Box Recorder Creates ~100 Separate Recordings Per Flight After Landing (TAXI IN Oscillation)

**Skills:** `focused-fix`, `minimalist`, `tc-tracker`

**Severity:** **High** (data fragmentation, library clutter)

**Symptoms:** After landing and taxiing to the gate, the Black Box library shows dozens to hundreds of separate .opsbb recording entries for what should be a single flight. Each recording has 0–1 samples, and they appear as multiple "ghost" entries alongside the main flight recording.

**Root Cause:** The `observe_phase()` function in `app/black_box.py` has `"TAXI IN"` in **both** the start-trigger set and the stop-trigger condition. This creates a 1-second oscillation during taxi-in:

```
Iteration N (logbook engine loop @ ~1 Hz):
  Phase = TAXI IN
    → Recording active? YES → stop_recording("TAXI IN") → _ACTIVE = None
    → Recording active? NO  → TAXI IN in start-set? YES → start_recording() → _ACTIVE set

Iteration N+1:
  Phase = TAXI IN (still taxiing, flight not finalized)
    → Recording active? YES → stop_recording("TAXI IN") → _ACTIVE = None
    → Recording active? NO  → TAXI IN in start-set? YES → start_recording() → _ACTIVE set
    ...

~One new .opsbb file per second → 60-120 recordings for a 1-2 minute taxi-in
```

**Key code at `app/black_box.py:601`:**
```python
# Line 597-618
if not active and phase_up in {"TAXI OUT", "PUSHBACK", "PARKED", "TAXI IN"}:
    # ^^^^^ TAXI IN should NOT be here
    ...
    start_recording(...)
    return

if phase_up == "TAXI IN" and active and flight_ids_match:
    stop_recording("TAXI IN")
```

`"TAXI IN"` is included in the start-trigger set at line 601, but it is an end-of-flight phase that should only stop recordings. Including it means every stop immediately allows a restart on the next cycle.

**Why the flight isn't finalized:** The logbook's `_analyse()` only finalizes the flight (`_analyse` returns `True`) when ALL of: GS < 1 kt, parking brake set, engines off. During taxi-in the GS is 1-40 kt and engines are running, so the logbook stays in `RECORDING` status, causing `observe_phase()` to be called every cycle.

**Proposed Fix:**

| Item | Change | File | Lines |
|------|--------|------|-------|
| A | **Remove `"TAXI IN"` from the start-trigger set** — prevents restart after stop | `app/black_box.py` | 601 |
| B | **(Optional) Add flight_id stop guard** — after stopping for a flight_id, prevent restarts for that same flight_id until a new flight begins | `app/black_box.py` | 617-618 |

**Landing zone:**
```python
# BEFORE (line 601):
if not active and phase_up in {"TAXI OUT", "PUSHBACK", "PARKED", "TAXI IN"}:

# AFTER:
if not active and phase_up in {"TAXI OUT", "PUSHBACK", "PARKED"}:
```

This is a one-line fix. `"TAXI IN"` is already handled as a stop condition at line 616, so removing it from the start set is safe — recordings will still stop correctly at TAXI IN.

---

## Baseline

v0.25.2 is the stable baseline for all further development. All fixes and features should be built on top of this version.

*Last updated: 2026-07-23*
