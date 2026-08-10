# In-Sim Verification Checklist — Closure Markers + OFP Live (v0.25.65)

Copy-paste this when you land. Everything here needs a **normal session with DevMode**
(career mode hard-blocks DevMode — do it outside the career flight).

---

## 0. Prereqs (before launching)

- [ ] Land and **fully exit MSFS** (it caches the SimObject index at startup — a restart is mandatory).
- [ ] Relaunch MSFS in **normal mode**, DevMode enabled.
- [ ] Confirm the package is installed:
  - **2024:** `%LOCALAPPDATA%\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache\Packages\Community\closure-markers`
  - **2020 Store:** `%LOCALAPPDATA%\Packages\Microsoft.FlightSimulator_8wekyb3d8bbwe\LocalCache\Packages\Community\closure-markers`
  - **2020 Steam:** `%APPDATA%\Microsoft Flight Simulator\Packages\Community\closure-markers`
- [ ] (Optional sanity check, runs without the sim):
      `cd opsroom-app\source\tools\simobjects\package && python verify_package.py` → expect 4/4 OK, 0 problems.

---

## A. Package loads + models render (the old bug — empty geometry)

- [ ] DevMode → **SimObject spawner** → search `closure-markers` → the `ORS` objects should list.
- [ ] Spawn **each** of:
  - `ORS CLOSURE MARKER X RUNWAY`
  - `ORS CLOSURE MARKER X TAXIWAY`
  - `ORS CLOSURE BARRIER LOW ORANGE` / `WHITE`
  - `ORS CLOSURE LIGHTED X TRAILER`
- [ ] Open the **model debug panel** for each spawn. **This is the pass/fail check:**
  - OLD bug: `static vertex count: 0` / `static face count: 0` on every LOD.
  - FIXED: **non-zero** counts — barricade ~3.2k verts, X-trailer ~21k (compare to Fenix A32X Cone: 960 verts / 1562 faces as a known-good reference).
- [ ] Visually confirm:
  - Barricades: real 3D rails, beveled edges, **diagonal orange/white stripes** across the front face, red beacon dome on top.
  - Lighted X trailer: vertical X (not horizontal), symmetric arms, **20 amber LED fixtures + red center beacon** at the hub.
  - X mats (runway/taxiway): flat white/black mats, visible at threshold size.

---

## B. End-to-end deploy from the app (Briefing → NOTAMs)

- [ ] Load a SimBrief flight plan (e.g. EGGK → anywhere) so route NOTAMs are pulled.
- [ ] App → **Briefing → NOTAMs** → the closure panel shows `DEPLOY IN SIM` + `REMOVE` + one-line status.
- [ ] Click **DEPLOY IN SIM**. Expect the status to flip to `CLOSURE MARKERS — DEPLOYED · N PLACED`.
- [ ] Fly / slew to the closed feature. Known good case: **EGKK** NOTAM `TWY YANKEE CLSD` + runway closures → expect:
  - **X marker at each runway threshold** of a closed runway.
  - **Orange/white barrier lines across the runway at every taxiway hold-short entry** (alternating colors).
  - Red center beacon on the X trailer **emissive at night** (check at dusk/night to see the glow).
- [ ] Confirm nothing spawns **above 15,000 ft** (auto-deploy is altitude-gated) and markers **despawn when you fly beyond the 50 NM radius**.
- [ ] Click **REMOVE** → status `CLOSURE MARKERS — CLEARED (N objects removed)`; verify all objects are gone in-sim.

---

## C. OFP live panel + manual overrides (no DevMode needed — doable mid-flight)

- [ ] Briefing → OFP → click **◈ LIVE OFP**.
- [ ] Click an **ACTUAL** cell (e.g. OUT) → type `1617Z` → Enter → amber ✎ highlight + MANUAL chip appears, BLOCK/DELTA recompute.
- [ ] Type a fuel value → TRIP / SURPLUS update.
- [ ] Confirm the **SimBrief iframe never flickers/reloads** while editing (2-second polling must not touch it).
- [ ] **CLEAR OVERRIDES** resets everything.

---

## What to report back

1. Model debug panel numbers for each object (or a screenshot) — verts/faces must be non-zero.
2. Whether the spawner lists `closure-markers` in **both** 2020 and 2024.
3. Deploy status line text after DEPLOY + after REMOVE.
4. Screenshot of the X at a closed threshold / barriers at a hold-short line.
5. Any `SIM FAULT:` line in the app log during deploy (that error was the old empty-model bug; should be gone).

If anything above fails, capture the exact status text / console line — it maps 1:1 to the
error classifier (`LimitExceeded` → quota, `InvalidParameter` → config bug, capacity errors → retry).
