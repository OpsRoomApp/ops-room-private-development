# 09 — SIM Closure Markers Feature Spec

**Status:** Planned (v0.25.x) · **Type:** Feature spec · **Owner:** OPS ROOM

**Goal:** When the live FAA NOTAM feed reports a runway or taxiway closure at the
airport the pilot is at, place realistic closure markers — **X markers, a lighted
X on trailer, and low-profile barriers** — inside Microsoft Flight Simulator at the
correct real-world positions, and remove them when the closure clears.

This spec is the design reference for the implementation. It was written after
verifying the actual SDKs and codebase on the build machine (see Feasibility).

---

## 1. Verified feasibility (ground truth, not assumptions)

| Component | Finding |
|---|---|
| MSFS 2020 SDK | `C:\MSFS SDK` — SimConnect SDK, WASM, Tools (incl. Blender glTF exporter `Tools/Blender/io_scene_gltf2_msfs.zip`), Schemas |
| MSFS 2024 SDK | `C:\MSFS 2024 SDK` — SimConnect SDK, WASM, Tools/Blender/addons (newer exporter), SharedAssets, ModelBehaviorDefs. **Partial install: no samples or documentation** (the official 2024 "SimObject Spawner" sample is not on disk) |
| SimConnect AI API (2020 `SimConnect.h`) | Exposes `AICreateSimulatedObject`, `AIRemoveObject`, `AIReleaseControl`, `AICreateNonATCAircraft`, `AICreateParkedATCAircraft` — everything needed for runtime spawn/remove |
| App SimConnect session | `app/simconnect_position.py` — hardened, single shared session, lock-serialized, self-healing (v0.25.60). The spawner reuses this infra; never opens a second connection |
| App Python wrapper | `SimConnect` PyPI package (`from SimConnect import AircraftRequests, SimConnect`) + bundled `SimConnect.dll`. **Phase 0 must confirm it exposes AI spawn calls** (or use the DLL-level ctypes pattern already proven in `pmdg777_sdk.py`) |
| Runway geometry | `app/aviation_data.py` loads `runway_end` (both thresholds with lat/lon/heading/name, e.g. `08L/26R`) from the local simulator nav DB |
| Taxiway geometry | Same source, `taxi_path` table with `name` column + polyline topology (`get_airport_surface` returns merged taxiways). The same data drives the Live Map surface layers |
| NOTAM data | Live server-side DB (78k+ NOTAMs) served via `/api/v1/notams/{icao}`; briefing rows carry full text + qcode + classification |
| In-sim delivery | The app currently ships **no** Community-folder package (the WASM native bridge exists as a Client Data channel pattern in `opsroom_native_bridge.py` but no in-sim package is bundled) |

**Verdict:** fully feasible. ~1 week of focused work to a first usable version.

---

## 2. Architecture decision

### Path A — SimConnect AI SimObjects (**v1, this spec's target**)

**IMPLEMENTED (v0.25.65).** Assets ship as `SimObjects/Misc/<NAME>/` packages
(category `StaticObject` — the exact category the OPS ROOM Bridge and the FNX
cone use for SimConnect-spawned static objects, proven in-sim on MSFS 2024).

- Spawn sequence per marker:
  1. `SimConnect_AICreateSimulatedObject(title, init_position, request_id)` —
     `SIMCONNECT_DATA_INITPOSITION` carries lat/lon/alt/heading, `onGround=1`.
     The python SimConnect lib binds it as `dll.AICreateSimulatedObject` with
     the correct 4-arg signature; the handle is passed BY VALUE (never
     `byref`), matching the native bridge's proven in-sim path.
  2. The object ID arrives asynchronously (`SIMCONNECT_RECV_ID_ASSIGNED_OBJECT_ID`
     → the lib writes `SIMCONNECT_OBJECT_ID` env var); the spawner captures it
     per request into a registry.
- Remove sequence: `SimConnect_AIRemoveObject(object_id)` (3 args, handle by
  value) for every captured ID — `remove_markers()`.
- **Works in both MSFS 2020 and 2024** (SimConnect is fully supported in 2024;
  the SDK export name `SimConnect_AICreateSimulatedObject` is identical in both
  SDK headers).
- **Pure Python in the app** — the package builder (`package/build_package.py`)
  regenerates manifest.json/layout.json from the Blender exports.

### Path B — MSFS 2024 native SimObject Spawner (**v2, optional later**)

- The 2024 SDK ships an official WASM "SimObject Spawner" sample (not installed —
  requires the full SDK or the sample's source). It spawns/moves SimObjects natively
  with fewer quirks and no AI-object limits.
- Integration pattern already exists: Python → SimConnect Client Data → in-sim WASM
  (`opsroom_native_bridge.py` is the template).
- Only for 2024 users; keep Path A as the 2020-compatible fallback.

---

## 3. Asset pipeline (Blender bpy)

### 3.1 Models (one bpy script per asset, headless: `blender -b -P make_marker_x.py`)

| Asset | bpy recipe (geometry + material) |
|---|---|
| **X marker** | Two crossed flat boards (scaled cubes rotated ±45°), orange/red material, ~30 lines |
| **Lighted X on trailer** | X frame + trailer box + 4 cylinder wheels + **emissive material** on the X (MSFS glTF honors emission; lights at night) |
| **Low-profile barrier** | Long striped box, orange/white segment materials (classic A-frame barricade) |

Real-world sizing: an X marker is ~1.8 m tall, barriers ~1 m. Use real meters in
Blender (glTF exports in meters).

### 3.2 Export & packaging

**IMPLEMENTED (v0.25.65).**

1. Blender headless bpy scripts (`tools/simobjects/blender/*.py`) export each
   model as plain glTF + bin into `package/closure-markers/Model/<NAME>/`.
2. `package/inject_lights.py` bakes `ASOBO_macro_light` node extensions into
   every LOD0 and `_LOD1` glTF (schema verified in both SDKs): 44 amber LED
   fixtures + red hub beacon on the lighted X, red beacons on the barricades.
   No `light.xml` needed.
3. `package/build_package.py` restructures `Model/` into the shipped package
   and regenerates `manifest.json` + `layout.json` (FILETIME dates):

```
closure-markers/
  manifest.json                # content_type MISC
  layout.json                  # path/size/date per file (SimObjects/ tree only)
  SimObjects/Misc/<NAME>/      # one folder per title:
    sim.cfg                    # [fltsim.0] title + [General] category=StaticObject
    model/model.cfg + gltf/bin # LOD0 + _LOD1
```

4. `python tools/simobjects/package/build_package.py --install` copies the
   built package into the MSFS Community folder (2024 LocalCache first, 2020
   `%APPDATA%` fallback). `Model/` stays in the repo as the re-export source.

---

## 4. NOTAM → closure detection

### 4.1 Inputs

- Per-airport briefing rows from the server DB (`notams_live` →
  `notam_client.route_notams`), which carry `text`, `qcode`, `classification`,
  `category` (Runways / Airport surface / …), `effective_utc`, `expires_utc`,
  `is_cancelled`.

### 4.2 Patterns (text regex, case-insensitive)

- Runway: `RWY 08L CLSD`, `RWY 08L/26R CLSD`, `RWY 04/22 CLSD`,
  `RUNWAY 08L CLOSED`
- Taxiway: `TWY A CLSD`, `TWY A AND B CLSD`, `TWY A BTN RWY 08L AND RWY 26R CLSD`
- Partial: `RWY 08L CLSD SOUTH OF TWY A`, `RWY 08R 50% WIDTH CLSD`

### 4.3 qcode assist (not authoritative on its own)

- `QMR…` → runway subject · `QIC…`/`QCA…` → taxiway/airport surface
- Third letter `C` signals closure (e.g. `QMRLC`). Confirm against live samples in
  Phase 2 — the FAA feed's qcode quality varies; **text regex is the primary signal**.

### 4.4 Filtering

- Only rows where `is_cancelled == 'N'` and the effective window covers **now**
  (the server already gates on this; the client double-checks `expires_utc`).
- Only `classification in {DOM, INTL, FDC}` relevant rows (FDC carries US TFRs,
  not closures — skip `QRT`/TFR content).

---

## 5. Marker placement geometry

### 5.1 Runway closures (primary, solid)

- `runway_end` rows give both thresholds: lat/lon, heading, name (`08L`, `26R`).
- Placement (real-world convention): an **X at each threshold**, just before the
  threshold marking, oriented facing the runway direction; **lighted X trailer**
  instead when it is night at the airport (see 5.3).
- Full closure of both directions → 2 markers. Directional closure
  (`RWY 08L CLSD` where 26R open) → 1 marker at the closed end (v1 places both
  ends when the NOTAM names the pair; refine directional logic in Phase 2 with
  live samples).

### 5.2 Taxiway closures (supported by `taxi_path`)

- Match the NOTAM taxiway name (`TWY A`) against `taxi_path.name` rows for the
  airport; find the taxiway polyline (start/end nodes).
- Placement: an **X (or barrier) at each end of the closed taxiway segment where
  it meets a runway or another open taxiway**; barriers along the segment for
  "closed between X and Y" NOTAMs.
- If `taxi_path.name` is empty/unmatched, log and skip (no guess placement).

### 5.3 Day/night

- Read sim local time via SimConnect (Phase 0 confirms the exact var — `ZULU_TIME`
  + timezone offset, or `LOCAL_TIME` if exposed). Night (sun below horizon by
  sim clock) → spawn `marker_x_lighted`, else `marker_x`.

### 5.4 Altitude & orientation

- Spawn at airport elevation + ~0.05 m (on-ground), heading = runway end heading
  (markers face the runway). Barriers oriented across the taxiway width.

---

## 6. Spawner module & lifecycle

New module `app/closure_markers.py` (mirrors `raas.py` style: guarded, never
raises, diagnostics everywhere).

### 6.1 Reconcile loop

Desired set (from §4/§5) is compared against the live object registry every:

- **App start + sim connected** (SimStart event — the session already subscribes)
- **Airport change** (telemetry ICAO changes — re-use the app's current-airport
  tracking; RAAS/telemetry already know the airport)
- **NOTAM refresh** (the existing briefing refresh cycle, e.g. every 5–10 min)
- **Manual toggle** in the UI
- **Sim disconnect / SimStop** → remove all objects, clear registry

Diff → spawn missing, remove stale, reposition moved (remove+recreate; the AI API
has no reliable "move", `AISetObjectPosition` is not verified in the header).

### 6.2 Concurrency & safety

- All SimConnect calls through the existing `_LOCK` and shared session.
- Object registry: `{marker_id: (object_id, kind, position)}`, max cap (e.g. 50
  objects) to respect AI-object limits.
- Dry-run mode: `settings "closure_markers_dry_run": true` logs exactly what
  would spawn (works without a sim — enables CI validation).

### 6.3 UI

- Settings: `closure_markers_enabled` (default off — opt-in), `closure_markers_lighted`
  (default on), `closure_markers_dry_run` (default off).
- Status row in the integrations panel: `CLOSURE MARKERS · 2 RWY · 1 TWY · SPAWNED 3`
  plus errors.

---

## 7. Phases & effort

| Phase | Deliverable | Effort |
|---|---|---|
| **0 — Verify** | pySimConnect AI-method availability in the build venv (or DLL-level fallback); confirm spawn var for local time; one manual spawn+release+remove test with a stock object in-sim | ~½ day |
| **1 — Assets** | bpy scripts ×3 → MSFS glTF export → SimObject package → Community folder; manual in-sim placement check | 1–2 days |
| **2 — Closures** | NOTAM closure parser (§4) + geometry lookup (§5) + placement rules; validated against the live DB's real closures | 1–2 days |
| **3 — Spawner + UI** | `closure_markers.py` reconcile loop, registry, cleanup; settings + status row; edge cases (sim off, airport change, connect/disconnect) | 1–2 days |
| **4 — 2024 native** *(optional)* | WASM SimObject spawner via Client Data for 2024-only users | later |

**Definition of done (v1):** with MSFS loaded at an airport that has a live closure
NOTAM, the correct markers appear at the correct ends; when the closure expires,
they disappear; nothing in the existing telemetry/RAAS/bridge paths changes.

---

## 8. Accepted caveats & limits

1. **No collision** — markers are visual only; the aircraft can fly through them.
   (Acceptable: real-world closures are marked visually; pilots do not land on
   closed surfaces.)
2. **Local-only** — other players/VATSIM observers do not see them (SimConnect
   cannot share scenery objects).
3. **AI-object quirks** — LOD pop-in at distance, AI object-count limits, possible
   visual jitter if control release is imperfect (mitigated by `AIReleaseControl`).
4. **Taxiway accuracy** — depends on the local sim nav DB `taxi_path` data; the
   same data already powers the Live Map surface layers and is considered accurate.

---

## 9. Validation strategy

- **Unit (CI-style):** NOTAM parser tests (fixture closure texts incl. the
  "NOTAM CANCELLED" cases) · geometry matching (fake airport surface rows) ·
  desired-set diff logic · day/night decision.
- **Dry-run integration:** `closure_markers_dry_run` logs planned placements
  against real DB closures for real airports — no sim needed, runs in CI.
- **Manual in-sim checklist (Phase 1/3):** spawn → visible at threshold → correct
  orientation → release holds position → remove on expiry → no regressions in
  RAAS/telemetry (validate via the app's existing release-gate tooling).

---

## 10. Open questions (resolve in Phase 0/2)

1. **RESOLVED** — the python SimConnect lib binds `AICreateSimulatedObject` /
   `AIRemoveObject` with correct argtypes (verified in
   `site-packages/SimConnect/Attributes.py`); the spawner uses the lib binding
   with the handle passed by value.
2. **RESOLVED** — `SimObjects/Misc` + `category = StaticObject` works for
   SimConnect-spawned static objects (proven by the FNX cone and the OPS ROOM
   Bridge in-sim on this machine).
3. Open — day/night choice of lighted vs. plain X is currently not used; the
   lighted X is spawned for hold-short lines and the plain mats at thresholds.
4. Open — parser relies on text regex (`is_closure_notam` + `RWY/TWY` refs);
   qcode assist was not needed for the current feed.
5. **RESOLVED** — the deploy toggle lives in Briefing → NOTAMS; the spawner
   re-plans on every toggle/GET (fire-and-forget, idempotent) and removes on
   toggle-off / CLEAR ALL.
