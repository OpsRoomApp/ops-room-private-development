"""Regression tests for NOTAM closure marker parsing and placement -- v0.25.65.

Runs without network access; the SimConnect spawner is deliberately not
exercised here (Windows + live simulator required).
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from app import aviation_data  # noqa: E402
from app import closure_markers as cm  # noqa: E402
from app import navdata  # noqa: E402

PASS = 0
FAIL = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS: {label}")
    else:
        FAIL += 1
        print(f"  FAIL: {label} {detail}")


def row(text: str, icao: str = "EGLL") -> dict:
    return {"text": text, "location": icao, "source": "FAA NMS"}


# ── Parsing ──────────────────────────────────────────────────────────────────
markers = cm.parse_active_closures(
    [
        row("RWY 09L/27R CLSD"),
        row("RWY 09/27 CLSD DUE MAINTENANCE"),
        row("TWY A B AND C CLSD"),
        row("TWY ECHO AVBL FOR ACFT VACATING RWY 26L"),  # not a closure
        row("RWY 06 U/S"),
        row("NOTAM WITHOUT SURFACE REFERENCE CLSD"),  # is_closure_notam rejects
    ]
)
runways = sorted({m["ref"] for m in markers if m["kind"] == "runway"})
taxiways = sorted({m["ref"] for m in markers if m["kind"] == "taxiway"})
check("RWY 09L/27R CLSD -> 09L and 27R", runways == ["06", "09", "09L", "27", "27R"], str(runways))
check("TWY A B AND C CLSD -> A, B, C only", taxiways == ["A", "B", "C"], str(taxiways))
check("non-closure TWY availability skipped", all(m["ref"] != "ECHO" for m in markers))
check("U/S counts as closure", "06" in runways)
# Equipment unserviceability ("ILS RWY 08R/26L U/S") is NOT a runway closure --
# placing X's on an operational runway because its ILS is out is a false
# positive caught by the real FAA NMS EGKK feed (v0.25.65).
ils = cm.parse_active_closures([{"text": "ILS RWY 08R/26L U/S DUE MAINT, SUBJECT TO OPERATIONAL AND WEATHER CONSTRAINTS", "location": "EGKK/LGW", "source": "FAA NMS DB"}])
check("equipment U/S never places runway markers", ils == [], str(ils))
ils2 = cm.parse_active_closures([{"text": "LOC RWY 09L U/S", "location": "EGLL", "source": "FAA NMS DB"}])
check("LOC prefix also suppressed", ils2 == [], str(ils2))
plain_u_s = cm.parse_active_closures([{"text": "RWY 06 U/S", "location": "EGLL", "source": "FAA NMS"}])
check("bare RWY U/S still a closure", sorted({m["ref"] for m in plain_u_s}) == ["06"], str(plain_u_s))

# v0.25.68: crane / obstacle NOTAMs that describe a vehicle operating *when*
# a runway is closed are NOT runway closures -- the runway stays open. The
# real FAA NMS EGLL feed had these placing X's on operational runways.
crane = cm.parse_active_closures([{"text": "LIT CRANE OPR BTN 512828N 0002706W (HEATHROW). MAX HGT 136FT AGL, 216FT AMSL. CRANE WILL ONLY OPR WHEN RWY 09L/27R IS CLSD. NO CRANE OPR IN LVP. CRANE REF 20260602162", "location": "EGLL", "source": "FAA NMS DB"}])
check("crane 'WHEN RWY IS CLSD' never places runway markers", crane == [], str(crane))
crane2 = cm.parse_active_closures([{"text": "OPR AT FULL HEIGHT WHEN RWY 09R/27L IS CLSD. OPR AT REDUCED HEIGHT WHEN RWY 09R/27L IS IN OPR", "location": "EGLL", "source": "FAA NMS DB"}])
check("crane 'WHEN RWY IS CLSD' (full/reduced height) suppressed", crane2 == [], str(crane2))
crane3 = cm.parse_active_closures([{"text": "CRANE WILL OPR WHEN RWY 09L/27R IS CLOSED", "location": "EGLL", "source": "FAA NMS DB"}])
check("crane 'WHEN RWY ... IS CLOSED' suppressed", crane3 == [], str(crane3))
cond_twy = cm.parse_active_closures([{"text": "CRANE OPR WHEN TWY ECHO IS CLSD", "location": "EGLL", "source": "FAA NMS DB"}])
check("conditional 'TWY ... IS CLSD' suppressed", cond_twy == [], str(cond_twy))
# A direct closure still parses even when a crane NOTAM is also in the feed.
direct = cm.parse_active_closures([{"text": "RWY 09L/27R CLSD DUE WIP", "location": "EGLL", "source": "FAA NMS DB"}])
check("direct RWY CLSD still a closure", sorted({m["ref"] for m in direct}) == ["09L", "27R"], str(direct))
# "TWY A IS CLSD" (IS between designator and keyword) parses A, never a
# phantom "IS" taxiway (v0.25.68 skip-token hardening).
is_clsd = cm.parse_active_closures([{"text": "TWY A IS CLSD DUE WIP", "location": "EGLL", "source": "FAA NMS"}])
check("TWY A IS CLSD -> A only (no phantom IS)", sorted({m["ref"] for m in is_clsd}) == ["A"], str(is_clsd))
no_keyword = cm.parse_active_closures([{"text": "RWY 08R/26L 145M SOUTH OF RWY CENTRE LINE, PLANT EQUIPMENT PARKED DUE WIP", "location": "EGKK", "source": "FAA NMS DB"}])
check("RWY mention without attached closure keyword skipped", no_keyword == [], str(no_keyword))
check("no-surface CLSD skipped", len([m for m in markers if "SURFACE" in m["raw"].upper()]) == 0)
check("ICAO captured from row", all(m["airport_icao"] == "EGLL" for m in markers))
check("markers carry raw + source", all(m.get("raw") and m.get("source") for m in markers))

# SimBrief briefing rows carry a combined ICAO/IATA value ("EGKK/LGW") -- the
# bare 4-alpha ICAO check used to drop every marker (v0.25.65 hotfix).
combined = cm.parse_active_closures([{"text": "RWY 08L/26R CLSD", "location": "EGKK/LGW", "source": "FAA NMS"}])
check("combined ICAO/IATA location parsed", len(combined) == 2 and all(m["airport_icao"] == "EGKK" for m in combined), str(combined))
prefixed = cm.parse_active_closures([{"text": "RWY 09L CLSD", "location": "EHAM-AMSTERDAM", "source": "FAA NMS"}])
check("prefixed ICAO location parsed", len(prefixed) == 1 and prefixed[0]["airport_icao"] == "EHAM", str(prefixed))
no_icao = cm.parse_active_closures([{"text": "RWY 09L CLSD", "location": "", "source": "FAA NMS"}])
check("missing ICAO stays empty (never guessed)", len(no_icao) == 1 and no_icao[0]["airport_icao"] == "")

# NATO phonetic phraseology: "TWY YANKEE CLSD" means taxiway Y (v0.25.65).
phon = cm.parse_active_closures([{"text": "TWY YANKEE CLSD DUE WIP", "location": "EGKK/LGW", "source": "FAA NMS"}])
check("NATO YANKEE -> taxiway Y", len(phon) == 1 and phon[0]["kind"] == "taxiway" and phon[0]["ref"] == "Y", str(phon))
phon2 = cm.parse_active_closures([{"text": "TWY ALPHA 1 AND ZULU CLSD", "location": "EGLL", "source": "FAA NMS"}])
refs2 = sorted({m["ref"] for m in phon2 if m["kind"] == "taxiway"})
check("NATO ALPHA 1 -> A1, ZULU -> Z", refs2 == ["A1", "Z"], str(refs2))
phon3 = cm.parse_active_closures([{"text": "TWY YANKEE AND ZULU CLSD", "location": "EGLL", "source": "FAA NMS"}])
refs3 = sorted({m["ref"] for m in phon3 if m["kind"] == "taxiway"})
check("NATO Y + Z stay separate (no YZ merge)", refs3 == ["Y", "Z"], str(refs3))

# Cancelled NOTAMs must never place markers (v0.25.65).
cnl = cm.parse_active_closures([{"text": "RWY 09L/27R CLSD DUE WIP. NOTAM CANCELLED", "location": "EGLL", "status": "", "source": "FAA NMS"}])
check("text CANCELLED suppresses markers", cnl == [], str(cnl))
cnl2 = cm.parse_active_closures([{"text": "RWY 09L CLSD", "location": "EGLL", "status": "CNL", "source": "FAA NMS"}])
check("status CNL suppresses markers", cnl2 == [], str(cnl2))
cnl3 = cm.parse_active_closures([{"text": "RWY 09L CLSD DUE WIP. NOTAM CANCELLED", "location": "EGLL", "source": "FAA NMS"}])
check("cancelled with active-looking text still suppressed", cnl3 == [], str(cnl3))

# Radius + altitude gate config defaults.
check("marker_radius_nm default 50", cm.marker_radius_nm() == 50.0, str(cm.marker_radius_nm()))
check("marker_altitude_gate_ft default 15000", cm.marker_altitude_gate_ft() == 15000.0, str(cm.marker_altitude_gate_ft()))

# Empty / malformed input
check("empty input -> []", cm.parse_active_closures([]) == [])
check("None input -> []", cm.parse_active_closures(None) == [])
check("non-dict rows skipped", cm.parse_active_closures([{"text": "x"}, "junk", None]) == [])


# ── Placement (deterministic via in-process stubs) ──────────────────────────
_real_runway_by_name = navdata.runway_by_name
_real_airport = navdata.airport
_real_runway_full = navdata.runway_full
_real_runway_candidates = navdata.runway_candidates

navdata.runway_by_name = lambda icao, name: {
    "threshold_lat": 51.4686,
    "threshold_lon": -0.4550,
    "heading_deg": 91.0,
    "threshold_elevation_ft": 82.0,
}
navdata.airport = lambda icao: {"lat": 51.4700, "lon": -0.4543, "elevation_ft": 83.0}
# Disable the hold-short tier here (no taxiway geometry) so this block tests
# exactly the threshold/centroid placements without depending on real navdata.
navdata.runway_full = lambda icao, ref: None
navdata.runway_candidates = lambda icao: []
# v0.25.67: taxiway markers now prefer real segment geometry; stub it away
# here so this block still exercises the airport-centroid fallback.
_real_tw_segments = aviation_data.taxiway_segments
aviation_data.taxiway_segments = lambda icao: []
try:
    plan = cm.plan_markers(
        [
            {"airport_icao": "EGLL", "kind": "runway", "ref": "09L"},
            {"airport_icao": "EGLL", "kind": "taxiway", "ref": "A"},
        ]
    )
    check("runway marker placed at threshold", plan["count"] == 2 and plan["placed"][0]["placement"] == "runway-threshold", str(plan["count"]))
    # v0.25.76: no anchor -> the LIGHTED X (vertical sign) faces
    # perpendicular to the runway centreline so its flat face runs ALONG it,
    # readable by runway traffic; heading = runway heading + 90 (181.0 here).
    check("runway placement has heading", abs(plan["placed"][0]["heading_deg"] - 181.0) < 0.001)
    # v0.25.76: WITH an anchor the vertical LIGHTED X faces the aircraft:
    # heading = bearing(X -> anchor) - 180 (the lit face, glTF -Z, points at
    # the pilot - the user's manual X is the in-sim ground truth). The stub
    # anchor sits ~155 deg from the X, so the heading lands near 335 deg, NOT
    # the 181 deg no-anchor fallback.
    import math as _m
    plan_anchored = cm.plan_markers(
        [{"airport_icao": "EGLL", "kind": "runway", "ref": "09L"}],
        anchor=(51.4700, -0.4543),
    )
    pa = plan_anchored["placed"][0]
    _kx = 111320.0 * _m.cos(_m.radians(51.47))
    _dx = (-0.4543 - pa["lon"]) * _kx
    _dy = (51.4700 - pa["lat"]) * 111320.0
    _expected = (_m.degrees(_m.atan2(_dx, _dy)) - 180.0) % 360.0
    check("runway X faces the anchor (lit face toward pilot)",
          abs(pa["heading_deg"] - _expected) < 0.01, str(pa["heading_deg"]))
    check("taxiway placed at airport centroid", plan["placed"][1]["placement"] == "airport-centroid")
    check("taxiway altitude offset above field", plan["placed"][1]["altitude_ft"] >= 83.0)
    # v0.25.71: RUNWAY closures deploy the LIGHTED X trailer (visible from
    # far, animates) instead of the plain vinyl mat; TAXIWAY closures keep
    # the plain yellow X mat (user rejected the trailer on taxiways).
    check("runway uses lighted X trailer SimObject", plan["placed"][0]["object"] == cm.SIMOBJECT_TITLE_X_TRAILER)
    check("taxiway uses plain X mat SimObject", plan["placed"][1]["object"] == cm.SIMOBJECT_TITLE_X_TAXIWAY)

    navdata.runway_by_name = lambda icao, name: None
    plan2 = cm.plan_markers([{"airport_icao": "XXXX", "kind": "runway", "ref": "09L"}])
    check("runway without navdata reported unplaced", plan2["count"] == 0 and len(plan2["unplaced"]) == 1, str(plan2))
    check("unplaced carries reason", "reason" in plan2["unplaced"][0])
finally:
    navdata.runway_by_name = _real_runway_by_name
    navdata.airport = _real_airport
    navdata.runway_full = _real_runway_full
    navdata.runway_candidates = _real_runway_candidates
    aviation_data.taxiway_segments = _real_tw_segments

# v0.25.67: taxiway markers place on the ACTUAL taxiway geometry when it
# exists (the ~500 m airport-centroid offset fix) - centroid + heading of
# the matching segments.
_real_tw2 = aviation_data.taxiway_segments
aviation_data.taxiway_segments = lambda icao: [
    {"name": "Y", "start_lat": 51.1520, "start_lon": -0.1650, "end_lat": 51.1525, "end_lon": -0.1640},
    {"name": "Y", "start_lat": 51.1525, "start_lon": -0.1640, "end_lat": 51.1530, "end_lon": -0.1630},
]
try:
    plan3 = cm.plan_markers([{"airport_icao": "EGKK", "kind": "taxiway", "ref": "Y"}])
    p = plan3["placed"][0] if plan3["placed"] else {}
    check("taxiway placed on real geometry", p.get("placement") == "taxiway-geometry", str(plan3))
    check("taxiway geometry position on the taxiway", abs(p.get("lat", 0) - 51.1525) < 0.001 and abs(p.get("lon", 0) - -0.1640) < 0.001, str(p))
    # v0.25.70: X arms cross at 45 deg to the taxiway -> heading = bearing - 45.
    # The stub segments bear ~51.4 deg, so the X heading is ~6.4 deg.
    check("taxiway geometry carries heading", 5.0 < p.get("heading_deg", 0) < 8.0, str(p))
finally:
    aviation_data.taxiway_segments = _real_tw2

# ── Hold-short barrier tier (deterministic via stubbed geometry) ────────────
_real_aviation_source = aviation_data.local_surface_source
_real_taxiway_segments = aviation_data.taxiway_segments



def _rwy_full_dict() -> dict:
    # EGKK-style 08L/26R: width 148 ft, length 8500 ft, primary heading ~83 deg.
    return {
        "airport_ident": "EGKK",
        "runway": "08L/26R",
        "length_ft": 8500.0,
        "width_ft": 148.0,
        "primary": {"name": "08L", "lat": 51.1443, "lon": -0.1790, "heading_deg": 83.0, "elevation_ft": 200.0},
        "secondary": {"name": "26R", "lat": 51.1508, "lon": -0.1550, "heading_deg": 263.0, "elevation_ft": 200.0},
    }


def _taxi_segment(name: str, along_m: float) -> dict:
    # A stub taxiway meeting the runway EDGE: its end sits at cross +22.56 m
    # (the 148 ft runway's half-width) and its start 20 m further out along
    # the perpendicular (cross +42.56 m, outside the v0.25.70 entry band so
    # only the edge endpoint counts as a hit). Bearing 173 deg = 90 deg off
    # the 83 deg runway.
    r = math.radians(83.0)
    cosr, sinr = math.cos(r), math.sin(r)

    def _pt(cross: float) -> tuple[float, float]:
        north_m = along_m * cosr - cross * sinr
        east_m = along_m * sinr + cross * cosr
        lat = 51.1443 + north_m / 111_320.0
        lon = -0.1790 + east_m / (111_320.0 * math.cos(math.radians(51.1443)))
        return lat, lon

    s_lat, s_lon = _pt(42.56)
    e_lat, e_lon = _pt(22.56)
    return {"name": name, "type": "T", "surface": "CONCRETE", "width_ft": 75.0,
            "start_lat": s_lat, "start_lon": s_lon, "end_lat": e_lat, "end_lon": e_lon}


navdata.runway_by_name = lambda icao, name: {
    "threshold_lat": 51.1443,
    "threshold_lon": -0.1790,
    "heading_deg": 83.0,
    "threshold_elevation_ft": 200.0,
}
navdata.runway_full = lambda icao, ref: _rwy_full_dict()
navdata.runway_candidates = lambda icao: []
aviation_data.local_surface_source = lambda: {"available": True, "source": "auto-detected", "message": "stub"}
# Stub taxiways meet the runway edge (cross +22.56 m) at along 600/1100/1600 m.
aviation_data.taxiway_segments = lambda icao: [
    _taxi_segment("A", 600.0),
    _taxi_segment("B", 1100.0),
    _taxi_segment("C", 1600.0),
]
try:
    plan3 = cm.plan_markers([{"airport_icao": "EGKK", "kind": "runway", "ref": "08L"}])
    barrier_kinds = [p["kind"] for p in plan3["placed"]]
    check("hold-short tier places barrier lines", "barrier" in barrier_kinds, str(barrier_kinds))
    barriers = [p for p in plan3["placed"] if p["kind"] == "barrier"]
    check("barrier lines carry geometry_source", all(p.get("geometry_source") for p in barriers))
    check("barrier lines carry placement=hold-short-line", all(p["placement"] == "hold-short-line" for p in barriers))
    # 3 stub entries x 7 barricades each (75 ft taxiway / 3.7 m spacing).
    check("barrier placement spans taxiway width", len(barriers) == 21, str(len(barriers)))
    titles = {p["object"] for p in barriers}
    check("barrier lines use single orange T3 title",
          titles == {cm.SIMOBJECT_TITLE_BARRICADE_T3_ORANGE}, str(titles))
    # v0.25.76: MSFS heading orients the model's glTF +Z axis (clean in-sim
    # ground truth: with heading = row direction the T3's long X axis read
    # PARALLEL to the taxiway), so heading = row + 90 lays the long axis
    # ALONG the row into a continuous "--------" wall perpendicular to the
    # taxiway. Here the row runs perpendicular to the taxiway (bearing
    # 173 + 90 = 263), so the heading is 263 + 90 = 353.
    check("barrier headings along the row",
          all(abs((p["heading_deg"] - 353.0) % 360.0) < 1.0 for p in barriers), str({p["heading_deg"] for p in barriers}))
    # v0.25.70: consecutive barricades are edge-connected with a small gap
    # (3.6 m model width at 3.7 m spacing). placed is ordered by line, 7 per
    # line, so j % 7 == 0 pairs span a line boundary and are skipped.
    check("barrier spacing connects edge-to-edge",
          all(
              abs(cm._dist_m(barriers[j]["lat"], barriers[j]["lon"],
                             barriers[j - 1]["lat"], barriers[j - 1]["lon"]) - cm.BARRIER_SPACING_M) < 0.3
              for j in range(1, len(barriers))
              if j % 7 != 0
          ),
          "",
      )
    # Distinct taxiway names -> distinct hold-short lines (A, B, C).
    alongs = sorted({round(p["lat"], 4) for p in barriers})
    check("multiple taxiway entries produce multiple lines", len(alongs) >= 2, str(alongs))
finally:
    navdata.runway_by_name = _real_runway_by_name
    navdata.runway_full = _real_runway_full
    navdata.runway_candidates = _real_runway_candidates
    aviation_data.local_surface_source = _real_aviation_source
    aviation_data.taxiway_segments = _real_taxiway_segments

# Hold-short without any taxiway geometry still places the threshold X.
aviation_data.taxiway_segments = lambda icao: []
aviation_data.local_surface_source = lambda: {"available": False, "message": "stub none"}
navdata.runway_by_name = lambda icao, name: {
    "threshold_lat": 51.1443,
    "threshold_lon": -0.1790,
    "heading_deg": 83.0,
    "threshold_elevation_ft": 200.0,
}
navdata.runway_full = lambda icao, ref: _rwy_full_dict()
navdata.runway_candidates = lambda icao: []
try:
    plan4 = cm.plan_markers([{"airport_icao": "EGKK", "kind": "runway", "ref": "08L"}])
    kinds4 = [p["kind"] for p in plan4["placed"]]
    check("no taxiway geometry -> threshold X only", kinds4 == ["runway"], str(kinds4))
finally:
    navdata.runway_by_name = _real_runway_by_name
    navdata.runway_full = _real_runway_full
    navdata.runway_candidates = _real_runway_candidates
    aviation_data.taxiway_segments = _real_taxiway_segments
    aviation_data.local_surface_source = _real_aviation_source

# ── Duplicate-row dedupe (v0.25.65) ──────────────────────────────────────────
_dup = cm.parse_active_closures(
    [
        row("RWY 08R/26L CLSD DUE WIP", "EGKK"),
        row("RWY 08R/26L CLSD DUE WIP", "EGKK"),
        row("TWY YANKEE CLSD DUE WIP", "EGKK"),
    ]
)
_rwy = [m for m in _dup if m["kind"] == "runway"]
_twy = [m for m in _dup if m["kind"] == "taxiway"]
check("dedupe: duplicate runway row collapses to one", len(_rwy) == 2, str([m["ref"] for m in _rwy]))
check("dedupe: runway refs split 08R/26L", {m["ref"] for m in _rwy} == {"08R", "26L"}, str([m["ref"] for m in _rwy]))
check("dedupe: taxiway refs still present", len(_twy) == 1 and _twy[0]["ref"] == "Y", str(_twy))
check("dedupe: distinct closures never merge", len(_dup) == 3, str([(m["kind"], m["ref"]) for m in _dup]))
_dup2 = cm.parse_active_closures([row("TWY A CLSD", "EGLL"), row("TWY B CLSD", "EGLL")])
check("dedupe: different taxiways stay separate", len(_dup2) == 2, str([m["ref"] for m in _dup2]))


# ── v0.25.65 proximity alerting ──────────────────────────────────────────────
_plan_real = cm.build_marker_plan
cm.build_marker_plan = lambda: {
    "placed": [
        {"airport_icao": "EGKK", "kind": "runway", "ref": "08R", "lat": 51.1481, "lon": -0.1903},
        {"airport_icao": "EGKK", "kind": "taxiway", "ref": "Y", "lat": 51.1533, "lon": -0.1690},
    ]
}
try:
    near = cm.proximity_alert(lat=51.1490, lon=-0.1900)
    check("proximity: near runway detected", bool(near.get("near")) and near.get("kind") == "runway", str(near))
    far = cm.proximity_alert(lat=51.5000, lon=0.5000)
    check("proximity: far position -> not near", not far.get("near"), str(far))
    twy = cm.proximity_alert(lat=51.1535, lon=-0.1689)
    check("proximity: near taxiway detected", bool(twy.get("near")) and twy.get("kind") == "taxiway" and twy.get("ref") == "Y", str(twy))
    # Barrier (hold-short line on a runway) must use the runway alert radius.
    _plan_real2 = cm.build_marker_plan
    cm.build_marker_plan = lambda: {"placed": [{"airport_icao": "EGKK", "kind": "barrier", "ref": "08R", "lat": 51.1481, "lon": -0.1903}]}
    cm._PROX_PLAN_CACHE.update({"at": 0.0, "placed": []})
    try:
        barrier = cm.proximity_alert(lat=51.1510, lon=-0.1900)  # ~0.2 NM away
        check("proximity: barrier uses runway radius", bool(barrier.get("near")) and barrier.get("kind") == "barrier", str(barrier))
    finally:
        cm.build_marker_plan = _plan_real2
        cm._PROX_PLAN_CACHE.update({"at": 0.0, "placed": []})
    # Disabled channel short-circuits.
    _settings_real = None
    try:
        from app import settings_store as _ss
        _load_real = _ss.load_settings
        _ss.load_settings = lambda: {"integrations": {"notam_notifications": False}}
        off = cm.proximity_alert(lat=51.1490, lon=-0.1900)
        check("proximity: disabled channel -> near=False", not off.get("near"), str(off))
    finally:
        if _load_real is not None:
            _ss.load_settings = _load_real
finally:
    cm.build_marker_plan = _plan_real


# ── v0.25.68: live-NOTAM briefing enrichment runs on the PUBLIC DB store ────
# The server-side NOTAM store (opsroom.live) needs no OPSROOM_NMS_TOKEN, so
# the briefing's live enrichment must not gate on the NMS proxy token being
# configured (that regression silently showed 0 live NOTAMs to users).
import app.briefing_data as bd  # noqa: E402

_route_real = bd.notam_client.route_notams
_nms_enabled_real = bd.nms_client.nms_enabled
_nms_configured_real = bd.nms_client.nms_configured
try:
    plan = {
        "origin": {"icao": "EGKK"},
        "destination": {"icao": "EDDF"},
        "alternates": [{"icao": "EGLL"}],
    }
    fake_rows = [
        {"id": "A1/26", "text": "TWY YANKEE CLSD DUE WIP", "location": "EGKK"},
        {"id": "A2/26", "text": "RWY 07L/25R CLSD", "location": "EDDF"},
    ]

    def _fake_route(*a, **k):
        return {"ok": True, "state": "ok", "notams": [dict(r) for r in fake_rows], "sources": [{"name": "FAA NMS DB", "state": "ok", "count": 2}]}

    bd.notam_client.route_notams = _fake_route
    # NMS proxy is NOT configured / disabled -- the DB path must still run.
    bd.nms_client.nms_enabled = lambda: False
    bd.nms_client.nms_configured = lambda: False
    live = bd._nms_live_briefing(plan)
    check("live briefing runs without NMS token (DB store public)", bool(live.get("ok")) and live.get("enabled") is True, str(live))
    check("live briefing returns DB rows when proxy unconfigured", len(live.get("notams") or []) == 2, str(live.get("count")))
    check("live briefing state ok", live.get("state") == "ok", str(live.get("state")))
finally:
    bd.notam_client.route_notams = _route_real
    bd.nms_client.nms_enabled = _nms_enabled_real
    bd.nms_client.nms_configured = _nms_configured_real

# ── Spawner/remover guards (no Windows/simulator dependency) ─────────────────
sp = cm.spawn_markers([{"object": "X"}], enabled=False)
check("spawn disabled -> ok, 0", sp["ok"] is True and sp["spawned"] == 0)
sp2 = cm.spawn_markers([], enabled=True)
check("spawn empty -> ok, 0", sp2["ok"] is True and sp2["spawned"] == 0)
rm = cm.remove_markers()
check("remove with nothing spawned -> ok, 0", rm["ok"] is True and rm["removed"] == 0, str(rm))

# ── v0.25.66: manual vs auto spawn source tagging ───────────────────────────
# Manual deployments (DEPLOY IN SIM) must survive the auto-deploy radius
# sweep; only auto-deployed markers are despawned outside the radius.
_sesh_real = cm._SESSION
cm._SESSION = cm._SimObjectSession()

try:
    _reg = cm._SESSION.register_spawn
    # Simulate two spawns at the same airport: one manual, one auto.
    _reg(1, "ORS TYPE III BARRICADE ORANGE", {"airport_icao": "EGKK", "ref": "08R/26L", "lat": 51.15, "lon": -0.19}, source="manual")
    _reg(2, "ORS TYPE III BARRICADE WHITE", {"airport_icao": "EGKK", "ref": "08R/26L", "lat": 51.16, "lon": -0.19}, source="auto")
    # Assign captured object IDs as MSFS would after spawn.
    for idx, item in enumerate(cm._SESSION._spawned, start=1):
        item["object_id"] = 1000 + idx
    _spawned = cm._SESSION.spawned()
    check("source tag stored on manual spawn", _spawned[0].get("source") == "manual", str(_spawned[0].get("source")))
    check("source tag stored on auto spawn", _spawned[1].get("source") == "auto", str(_spawned[1].get("source")))
    # Aircraft far away (e.g. 500 NM) -> only the AUTO marker is outside.
    class _FakeDll:
        pass
    class _FakeSm:
        hSimConnect = 1
        dll = _FakeDll()
    def _fake_remove(sm, obj_id, req_id):
        return 0  # HRESULT success
    # Store on the INSTANCE: a function stored on the class would bind as a
    # method and receive ``self`` as an extra argument.
    _FakeSm.dll.SimConnect_AIRemoveObject = _fake_remove
    _saved_windows = cm._is_windows
    _saved_connect = cm._SESSION.connect
    cm._is_windows = lambda: True
    cm._SESSION.connect = lambda: _FakeSm()
    try:
        out = cm.remove_markers_outside_radius(0.0, 0.0, 50.0)
    finally:
        cm._is_windows = _saved_windows
        cm._SESSION.connect = _saved_connect
    remaining = cm._SESSION.spawned()
    check("manual marker survives radius despawn", any(r.get("source") == "manual" for r in remaining), str(remaining))
    # The auto marker is dropped from tracking when it leaves the radius.
    check("auto marker removed by radius despawn", not any(r.get("source") == "auto" for r in remaining), str(remaining))

    # Manual deploy that lands on a previously auto-spawned marker upgrades the
    # tracked entry to ``manual`` so the radius sweep cannot despawn it later.
    cm._SESSION = cm._SimObjectSession()
    cm._SESSION.register_spawn(1, "ORS TYPE III BARRICADE ORANGE", {"airport_icao": "EGKK", "ref": "08R", "lat": 51.15, "lon": -0.19}, source="auto")
    _before = cm._SESSION.spawned()
    check("auto marker starts tagged auto", _before[0].get("source") == "auto")
    # Simulate DEPLOY IN SIM re-spawning the same placement (dedup path).
    class _FakeCreateDll:
        pass
    class _FakeCreateRaw:
        pass
    class _FakeCreateSm:
        hSimConnect = 1
        dll = _FakeCreateDll()
    _FakeCreateDll.SimConnect = _FakeCreateRaw()
    _FakeCreateRaw.SimConnect_AICreateSimulatedObject_EX1 = lambda *a: 0
    _FakeCreateRaw.SimConnect_AICreateSimulatedObject = lambda *a: 0
    _saved_windows2 = cm._is_windows
    _saved_connect2 = cm._SESSION.connect
    cm._is_windows = lambda: True
    cm._SESSION.connect = lambda: _FakeCreateSm()
    try:
        cm.spawn_markers([{"object": "ORS TYPE III BARRICADE ORANGE", "lat": 51.15, "lon": -0.19, "airport_icao": "EGKK", "ref": "08R"}], enabled=True, source="manual")
    finally:
        cm._is_windows = _saved_windows2
        cm._SESSION.connect = _saved_connect2
    _after = cm._SESSION.spawned()
    check("manual dedup upgrades tracked entry to manual", _after[0].get("source") == "manual", str(_after[0].get("source")))
finally:
    cm._SESSION = _sesh_real

print(f"\nRESULTS: {PASS}/{PASS + FAIL} PASS, {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
