"""NOTAM runway/taxiway closure markers -> in-simulator SimObject injection.

v0.25.65. Four layers:

  parse_active_closures()  pure NOTAM rows -> conservative marker refs (tested)
  plan_markers()           pure refs -> navdata placements (tested)
  spawn_markers()          guarded SimConnect ``AICreateSimulatedObject`` spawner
  remove_markers()         guarded SimConnect ``AIRemoveObject`` remover

Hold-short tier: for every closed runway, ``plan_markers`` now derives the
real-world barrier deployment -- an X at each threshold (kept), plus
alternating orange/white Type III barricade lines across the runway at
every taxiway entry (hold-short position) and at every runway crossing.
Taxiway geometry comes
from the local Little Navmap DB when available, otherwise from the built-in
``surface_taxi_bundle`` in ``opsroom_aviation.sqlite`` (see
``aviation_data.taxiway_segments``); neither source is required for runway
closures to place threshold X's. Every placement is deterministic and carries
``geometry_source`` so the UI can show where each marker came from.

The spawner reuses the same SimConnect.dll candidate discovery as
``simconnect_position`` but keeps its own lazy session, and degrades to a
status reason (never an exception) when the simulator, the Community package or
the enabled setting is absent. Object IDs returned asynchronously by MSFS are
captured per placement so ``remove_markers`` can clean them up with
``SimConnect_AIRemoveObject``. In-sim verification is still required (listed
in the handoff) -- this module never fabricates a spawn result.

Closures that cannot be parsed are skipped; runway closures without runway
navdata are reported ``unplaced`` rather than guessed.
"""

from __future__ import annotations

import ctypes
import logging
import math
import os
import re
import threading
from typing import Any

from . import aviation_data
from . import navdata
from . import notam_translate

_LOGGER = logging.getLogger("opsroom.closure_markers")

#: Real-world barrier width (Type III barricade, FAA AC 150/5370-2G
#: family): our BARRICADE_T3 model is a single 1.8 m rail. Barrier lines are
#: spaced at this width across the runway so the alternating orange/white
#: barricades sit edge-to-edge.
BARRIER_WIDTH_M = 1.8
#: Default runway width used when navdata lacks width_ft (45 m ~ 148 ft).
DEFAULT_RUNWAY_WIDTH_M = 45.0
#: Default taxiway width used when navdata lacks width_ft (23 m ~ 75 ft -
#: the FAA standard taxiway width for Code C/D airports). Used to size the
#: hold-short barricade line span.
DEFAULT_TAXIWAY_WIDTH_M = 23.0
#: Upper bound for the hold-short line span. Navdata bundles occasionally
#: report implausible taxiway widths (50+ m at EGLL for dual-pavement
#: rows); a barricade line longer than the actual entry would sprawl across
#: the runway, so the span is clamped to a generous real-world max.
MAX_TAXIWAY_ENTRY_WIDTH_M = 30.0
#: Lateral margin beyond the runway edge where a taxiway segment endpoint is
#: still considered an entry point (taxiway half-widths + safety margin).
ENTRY_MARGIN_M = 12.0
#: Minimum distance between two distinct hold-short lines (clusters).
ENTRY_CLUSTER_M = 30.0
#: v0.25.71: two DIFFERENT taxiway names can enter the same runway at nearly
#: the same spot (fragmented geometry splits one entry into ``A`` and ``A1``,
#: dual-pavement rows give the same junction two widths, or adjacent
#: connectors land close together - EGLL A2/A3 hit the 09L edge 29 m apart
#: and their rows overlapped into a staggered double row). Each used to
#: produce its own hold-short line which rendered in-sim as STAGGERED,
#: slightly-offset rows (the EGKK 26L "not a straight line" report). Entries
#: within this 2D distance are merged into a single line, re-centred on the
#: junction mean and sized from the widest entry so the single row still
#: covers every connector (EGLL A2/A3 29 m apart, AB10W fragments 38 m
#: apart).
ENTRY_LINE_MERGE_M = 45.0
#: Junction detection radius for taxiway entry X's: an endpoint of a
#: connecting taxiway within this distance of a closed-taxiway endpoint
#: counts as an entry (LNM fragment endpoints can be a few metres apart).
_ENTRY_JOIN_M = 12.0
#: Minimum angle (deg) between a taxiway segment and the runway for it to
#: count as an ENTRY. Near-parallel segments running along the edge do not
#: enter the runway; their hold-short line would span the runway surface
#: (EHAM S8, v0.25.70).
_ENTRY_MIN_ANGLE_DEG = 10.0
#: v0.25.76: user in-sim review "barricades should be 200-250ft from the
#: runway centerline" - the back-off is now expressed from the runway
#: CENTRELINE (not the edge) at the top of the requested range (250 ft /
#: 76.2 m), so every hold-short row sits 250 ft from the centreline
#: regardless of runway width. The row centre is placed along the TAXIWAY
#: at the point whose centreline-offset is this value (perpendicular walk
#: of (250 ft - half-width) off the edge), so a diagonal row stays ON the
#: pavement (in-sim "going out of the taxiway onto the ground").
HOLD_SHORT_BACKOFF_CL_FT = 250.0
#: v0.25.70: barricade width + small gap, so a hold-short line of T3
#: barricades connects edge-to-edge with a tiny gap (in-sim feedback:
#: "connecting each other, with a very small gap between"). The T3 model
#: is 3.6 m wide (Cube.001 spans -1.8..1.8 in X).
BARRIER_SPACING_M = 3.7
#: v0.25.71: cap per hold-short row. A row long enough to span a 25-30 m
#: taxiway entering at 10-15 deg runs 90-120 m / ~25-33 barricades; cap so a
#: single pathological entry cannot eat the whole deployment budget.
MAX_HOLD_SHORT_ROW_COUNT = 35
#: Hard cap on barrier spawns per plan to keep the sim usable. A full
#: closure at a major airport (every taxiway entry barriered) can need a few
#: hundred; 200 keeps the sim responsive while still showing the full line.
MAX_BARRIER_SPAWNS = 200
#: Distance inside the runway threshold where the closure X sits (feet).
#: In-sim verification at EGKK (v0.25.69 testing) showed the X placed at the
#: physical runway end sits on the edge, not on the numbering: MSFS paints
#: the numbers/threshold ~330-500 ft inside normal runway ends. A displaced
#: threshold (navdata ``displaced_threshold_ft``) pushes the numbering
#: further in, so the X follows the displacement when present.
RUNWAY_X_OFFSET_FT = 400.0

class _InitPosition(ctypes.Structure):
    """SIMCONNECT_DATA_INITPOSITION layout (6 doubles + 2 DWORDs).

    Kept at module level so the argtypes rebind in ``spawn_markers`` and the
    struct construction in ``_ai_create_simobject`` use the same class -- the
    python SimConnect lib expects its own ``SIMCONNECT_DATA_INITPOSITION``
    class, and ctypes refuses to convert between different Structure classes,
    so we rebind with our own class exactly like the native bridge does.
    """

    _fields_ = [
        ("Latitude", ctypes.c_double),
        ("Longitude", ctypes.c_double),
        ("Altitude", ctypes.c_double),
        ("Pitch", ctypes.c_double),
        ("Bank", ctypes.c_double),
        ("Heading", ctypes.c_double),
        ("OnGround", ctypes.c_uint32),
        ("Airspeed", ctypes.c_uint32),
    ]


#: The SimObject package title prefixes installed to the MSFS Community folder
#: (tools/simobjects/package). Title strings in sim.cfg must match exactly.
#: Real-world layout per ICAO/FAA: white vinyl X mats on runways, aviation
#: safety-yellow X mats with black trim on taxiways, alternating orange/white
#: water-filled barriers, and a portable two-wheel trailer with a lighted X.
SIMOBJECT_TITLE_X_RUNWAY = "ORS CLOSURE MARKER X RUNWAY"
SIMOBJECT_TITLE_X_TAXIWAY = "ORS CLOSURE MARKER X TAXIWAY"
SIMOBJECT_TITLE_X_TRAILER = "ORS CLOSURE MARKER X LIGHTED"
SIMOBJECT_TITLE_BARRIER_ORANGE = "ORS CLOSURE BARRIER LOW ORANGE"
SIMOBJECT_TITLE_BARRIER_WHITE = "ORS CLOSURE BARRIER LOW WHITE"
SIMOBJECT_TITLE_BARRICADE_T3_ORANGE = "ORS TYPE III BARRICADE ORANGE"
SIMOBJECT_TITLE_BARRICADE_T3_WHITE = "ORS TYPE III BARRICADE WHITE"

# v0.25.71: RUNWAY closures deploy the LIGHTED X trailer (the portable
# two-wheel trailer with the lighted X - the object that is visible from far
# and animates) instead of the plain vinyl X mat, per in-sim feedback ("the
# lighted X did not get injected"). TAXIWAY closures keep the plain yellow
# vinyl X mat (ORS CLOSURE MARKER X TAXIWAY) - the user explicitly rejected
# replacing the taxiway X with the trailer ("why did you replace taxiway X
# with lighted X too???", in-sim review v0.25.71). The trailer model's X
# arms run along the local X/Z axes exactly like the plain X marker, so the
# (bearing - 45) heading keeps the arms crossing at 45 deg to the runway.
_SIMOBJECT_TITLES = {
    "runway": SIMOBJECT_TITLE_X_TRAILER,
    "taxiway": SIMOBJECT_TITLE_X_TAXIWAY,
}

_RWY_RE = re.compile(r"\bRWY\s+([0-9]{1,2}[LRC]?(?:[/-][0-9]{1,2}[LRC]?)?)\b", re.IGNORECASE)

#: Conditional constructions -- "CRANE WILL ONLY OPR WHEN RWY 09L/27R IS
#: CLSD" describes a vehicle that operates *if* the runway is closed; it
#: does NOT close the runway. A closure keyword is only accepted when the
#: runway reference is a direct statement ("RWY 09L/27R CLSD DUE WIP"), not
#: a condition nested behind WHEN/IF in the same sentence (v0.25.68: real
#: FAA NMS EGLL crane NOTAMs were placing X's on operational runways).
_CONDITIONAL_PRE_RE = re.compile(r"\b(?:WHEN|IF)\b", re.IGNORECASE)

#: Equipment/approach nouns whose ``U/S`` refers to the equipment, not the
#: runway -- "ILS RWY 08R/26L U/S" is an ILS outage, never a runway closure.
#: The noun must directly precede the runway reference for this suppression.
_EQUIPMENT_PREFIX_RE = re.compile(
    r"\b(?:ILS|LOC|DME|NDB|PAPI|VOR|GS|MKR|ALS|RVR|LDA|ATIS|LGT|LGTS|TDZ|RCLL|REIL|HIRL|MIRL|SFL|GLIDESLOPE)\s+RWY\b",
    re.IGNORECASE,
)


def _sentence_prefix_has_conditional(upper: str, ref_index: int) -> bool:
    """True when a WHEN/IF sits between the last sentence boundary and the
    reference -- i.e. the closure keyword is a *condition* attached to
    something else ("CRANE WILL ONLY OPR WHEN RWY 09L/27R IS CLSD"), not a
    direct closure statement. Conservative: only removes the conditional
    phrasing, never a bare "RWY xx CLSD"."""
    start = max(
        upper.rfind(".", 0, ref_index),
        upper.rfind("!", 0, ref_index),
        upper.rfind("?", 0, ref_index),
        upper.rfind("\n", 0, ref_index),
    ) + 1
    return bool(_CONDITIONAL_PRE_RE.search(upper[start:ref_index]))


def _runway_closure_refs(text: str) -> list[str]:
    """Runway refs whose closure keyword is attached to the runway itself.

    A bare ``RWY 09L`` mention is not a closure -- the keyword must follow the
    reference (``RWY 09L/27R CLSD``), and an equipment noun immediately before
    the reference (``ILS RWY 08R/26L U/S``) means the outage belongs to the
    equipment, not the runway. A conditional construction (``CRANE WILL OPR
    WHEN RWY 09L/27R IS CLSD``) describes crane behaviour, never a closure.
    Conservative by design: better to miss a rare phrasing than to place
    runway-closure X's on an operational runway.
    """
    upper = str(text or "").upper()
    if _EQUIPMENT_PREFIX_RE.search(upper):
        return []
    refs: list[str] = []
    for match in _RWY_RE.finditer(str(text or "")):
        ref = match.group(1)
        index = match.start(1)
        tail = upper[index + len(ref) : index + len(ref) + 16]
        if not re.search(r"\b(?:CLSD|CLOSED|U/S)\b", tail):
            continue
        if _sentence_prefix_has_conditional(upper, index):
            continue
        refs.append(ref)
    return refs
_TWY_BLOCK_RE = re.compile(r"\bTWY\s+([^.\n]{1,80}?)(?=\s+(?:CLSD|CLOSED|U/S)\b)", re.IGNORECASE)
#: Phraseology tokens that are never taxiway designators. v0.25.68: without
#: IS/ARE/WAS/WERE/WHEN/IF/O, conditional constructions ("TWY YANKEE IS CLSD")
#: leaked the helper verb in as a bogus designator (a phantom taxiway "IS").
_SKIP_TOKENS = {"AND", "TO", "THRU", "BETWEEN", "RWY", "AERODROME", "IS", "ARE", "WAS", "WERE", "WHEN", "IF", "O", "OF"}
_TWY_TOKEN_RE = re.compile(r"^[A-Z][A-Z0-9]?$", re.IGNORECASE)

#: NATO phonetic words used by NOTAM phraseology for taxiway designators
#: ("TWY YANKEE CLSD" means taxiway Y). Words map to their letter; a
#: following digit merges onto the letter ("ALPHA 1" -> "A1").
_NATO_PHONETIC: dict[str, str] = {
    "ALPHA": "A", "BRAVO": "B", "CHARLIE": "C", "DELTA": "D", "ECHO": "E",
    "FOXTROT": "F", "GOLF": "G", "HOTEL": "H", "INDIA": "I", "JULIET": "J",
    "JULIETT": "J", "KILO": "K", "LIMA": "L", "MIKE": "M", "NOVEMBER": "N",
    "OSCAR": "O", "PAPA": "P", "QUEBEC": "Q", "ROMEO": "R", "SIERRA": "S",
    "TANGO": "T", "UNIFORM": "U", "VICTOR": "V", "WHISKEY": "W", "WHISKY": "W",
    "XRAY": "X", "X-RAY": "X", "YANKEE": "Y", "ZULU": "Z",
}

#: Cancellation markers: a NOTAM whose text or status says cancelled must
#: never place markers, even if it still reads "RWY .. CLSD" (the FAA NMS
#: feed keeps cancelled NOTAMs visible with literal "NOTAM CANCELLED" text).
_CANCEL_RE = re.compile(r"\b(?:CANCELLED|CANCELED|CNL)\b", re.IGNORECASE)


def _row_icao(row: dict[str, Any]) -> str:
    """Best-effort airport ICAO from a NOTAM row.

    SimBrief briefing rows carry a combined ``EGKK/LGW`` value in
    ``location`` (ICAO/IATA), so a bare 4-alpha check silently drops every
    marker. Split on separators and accept the first plausible 4-letter
    ICAO token; also tolerate prefixes like ``EHAM-AMSTERDAM``.
    """
    for key in ("airport_icao", "icao", "icao_location", "icaoLocation", "location", "station", "airport"):
        value = row.get(key) if isinstance(row.get(key), str) else None
        if not value:
            continue
        value_u = value.strip().upper()
        # v0.25.66: airspace NOTAMs ("EDGG LANGEN FIR", "EGTT LONDON FIR/UIR")
        # must never become airport markers - a 4-alpha token split out of
        # them would send X's to a FIR code's "airport" instead of a runway.
        if re.search(r"\b(FIR|UIR)\b", value_u):
            continue
        for token in re.split(r"[\s/|,-]+", value_u):
            token = token.strip()
            if len(token) == 4 and token.isalpha():
                return token
    return ""


def _clean_ref(ref: str) -> str:
    return re.sub(r"\s+", "", str(ref or "")).upper()


def _taxiway_refs(text: str) -> list[str]:
    """Extract taxiway designators, resolving NATO phonetic words.

    NOTAM phraseology is often spelled out ("TWY YANKEE CLSD" = taxiway Y,
    "TWY ALPHA 1 CLSD" = A1). Bare letter/digit tokens keep their existing
    meaning, phonetic words map to their letter, and a digit immediately after
    a letter merges ("A" + "1" -> "A1"). ``AND``/``BETWEEN`` reset the
    pairing so "TWY YANKEE AND ZULU CLSD" yields Y and Z, not YZ. Blocks whose
    designator sits behind a WHEN/IF condition are skipped (v0.25.68).
    """
    refs: list[str] = []
    upper = str(text or "").upper()
    for match in _TWY_BLOCK_RE.finditer(str(text or "")):
        if _sentence_prefix_has_conditional(upper, match.start()):
            continue
        pending_letter: str | None = None
        for raw in re.split(r"[,/&\s]+", match.group(1)):
            token = _clean_ref(raw)
            if not token or token in _SKIP_TOKENS:
                pending_letter = None
                continue
            letter = _NATO_PHONETIC.get(token)
            if letter:
                pending_letter = letter
                refs.append(letter)
                continue
            if token.isdigit() and pending_letter and refs and refs[-1] == pending_letter:
                refs[-1] = pending_letter + token
                pending_letter = None
                continue
            if _TWY_TOKEN_RE.match(token):
                pending_letter = token
                refs.append(token)
                continue
            pending_letter = None
    seen: set[str] = set()
    unique: list[str] = []
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            unique.append(ref)
    return unique


def _notam_active(row: dict[str, Any]) -> bool:
    """A NOTAM row is active only when nothing in it says cancelled.

    The NMS feed retains cancelled NOTAMs whose text still carries the
    original closure wording ("RWY 09L CLSD ... NOTAM CANCELLED"), so the
    closure parser must skip them or it would place markers for NOTAMs that
    no longer apply.
    """
    status = str(row.get("status") or "").upper()
    if "CNL" in status or "CANCEL" in status:
        return False
    text = str(row.get("text") or row.get("translated_text") or "")
    return not bool(_CANCEL_RE.search(text))


def parse_active_closures(notams: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """NOTAM rows -> conservative closure markers (runway/taxiway refs only).

    Reuses ``notam_translate.is_closure_notam`` so this layer can only ADD
    markers, exactly like the Dispatch badges and the RAAS cross-reference.
    Duplicate NOTAM rows (the same closure appearing twice in a feed) collapse
    to a single marker per airport/kind/ref -- the placement would be
    identical, and the spawner dedups by position anyway.
    """
    markers: list[dict[str, Any]] = []
    seen_marker: set[tuple[str, str, str]] = set()
    for row in notams or []:
        if not isinstance(row, dict):
            continue
        if not _notam_active(row):
            continue
        text = str(row.get("text") or row.get("translated_text") or "")
        if not notam_translate.is_closure_notam(text):
            continue
        icao = _row_icao(row)
        for ref in _runway_closure_refs(text):
            for piece in re.split(r"[/-]", ref):
                piece = _clean_ref(piece)
                if not piece:
                    continue
                key = (icao, "runway", piece)
                if key in seen_marker:
                    continue
                seen_marker.add(key)
                markers.append(
                    {"airport_icao": icao, "kind": "runway", "ref": piece, "raw": text[:240], "source": str(row.get("source") or ""), "notam_id": str(row.get("id") or row.get("number") or row.get("nms_id") or "").strip()}
                )
        for piece in _taxiway_refs(text):
            key = (icao, "taxiway", piece)
            if key in seen_marker:
                continue
            seen_marker.add(key)
            markers.append(
                {"airport_icao": icao, "kind": "taxiway", "ref": piece, "raw": text[:240], "source": str(row.get("source") or ""), "notam_id": str(row.get("id") or row.get("number") or row.get("nms_id") or "").strip()}
            )
    return markers


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """True bearing from point 1 to point 2, degrees 0-360 (north = 0).

    Same local-metre-frame convention as the heading math in
    ``_taxiway_geometry`` (dlon scaled by cos(lat) at the midpoint)."""
    dlat = (lat2 - lat1) * 111_320.0
    dlon = (lon2 - lon1) * 111_320.0 * math.cos(math.radians((lat1 + lat2) / 2.0))
    return (math.degrees(math.atan2(dlon, dlat)) + 360.0) % 360.0


def _m_to_deg_lat(m: float) -> float:
    return m / 111_320.0


def _m_to_deg_lon(m: float, lat: float) -> float:
    return m / (111_320.0 * max(0.1, math.cos(math.radians(lat))))


def _line_offset_point(lat: float, lon: float, heading_deg: float, offset_m: float, lat_m: bool = True) -> tuple[float, float]:
    """Point at ``offset_m`` along (lat_m=True: along runway heading) from (lat, lon)."""
    rad = math.radians(heading_deg)
    if lat_m:
        dlat = math.cos(rad) * offset_m
        dlon = math.sin(rad) * offset_m
        return lat + _m_to_deg_lat(dlat), lon + _m_to_deg_lon(dlon, lat)
    dlat = -math.sin(rad) * offset_m
    dlon = math.cos(rad) * offset_m
    return lat + _m_to_deg_lat(dlat), lon + _m_to_deg_lon(dlon, lat)


def _dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return math.hypot((lat2 - lat1) * 111_320.0, (lon2 - lon1) * 111_320.0 * math.cos(math.radians((lat1 + lat2) / 2.0)))


def _project_onto_runway(lat: float, lon: float, rwy: dict[str, Any]) -> tuple[float, float] | None:
    """Project a point onto the runway centerline; returns (along_m, cross_m).

    along_m is distance from the primary threshold along the runway heading;
    cross_m is signed perpendicular distance. ``None`` when geometry is
    missing.
    """
    p = rwy.get("primary")
    s = rwy.get("secondary")
    if not p or not s or p.get("lat") is None or p.get("lon") is None or s.get("lat") is None or s.get("lon") is None:
        return None
    p_lat, p_lon = float(p["lat"]), float(p["lon"])
    heading = float(rwy.get("primary", {}).get("heading_deg") or 0.0)
    dlat = lat - p_lat
    dlon = lon - p_lon
    north_m = dlat * 111_320.0
    east_m = dlon * 111_320.0 * math.cos(math.radians(p_lat))
    rad = math.radians(heading)
    along = east_m * math.sin(rad) + north_m * math.cos(rad)
    cross = east_m * math.cos(rad) - north_m * math.sin(rad)
    return along, cross


def _back_to_latlon(rwy: dict[str, Any], along_m: float, cross_m: float) -> tuple[float, float]:
    p = rwy.get("primary")
    heading = float(rwy.get("primary", {}).get("heading_deg") or 0.0)
    rad = math.radians(heading)
    north_m = along_m * math.cos(rad) - cross_m * math.sin(rad)
    east_m = along_m * math.sin(rad) + cross_m * math.cos(rad)
    lat = float(p["lat"]) + north_m / 111_320.0
    lon = float(p["lon"]) + east_m / (111_320.0 * math.cos(math.radians(float(p["lat"]))))
    return lat, lon


def _runway_half_width_m(rwy: dict[str, Any]) -> float:
    w = rwy.get("width_ft")
    try:
        w = float(w)
    except (TypeError, ValueError):
        w = 0.0
    return (w * 0.3048 / 2.0) if w and w > 0 else DEFAULT_RUNWAY_WIDTH_M / 2.0


def _taxiway_entry_points(rwy: dict[str, Any]) -> list[dict[str, Any]]:
    """Derive hold-short entry points where taxiways meet a closed runway.

    Reads taxi segments via ``aviation_data.taxiway_segments`` (local LNM DB
    first, built-in bundle fallback). A segment endpoint counts as an entry
    only when it lies in a band around the runway EDGE (|cross| within
    ``ENTRY_MARGIN_M`` of the half-width): endpoints mid-runway belong to
    taxiways that CROSS the runway and must not place a hold-short line on
    the runway surface (v0.25.70 -- the in-sim review at EGKK 26L showed
    barricade lines spanning the runway from those). The hold-short point is
    then projected along the taxiway bearing onto the runway edge itself.
    Endpoints are clustered by taxiway name AND side of the centreline so a
    crossing taxiway yields one hold-short line per edge; one barrier line is
    placed per cluster, not per segment.
    """
    icao = str(rwy.get("airport_ident") or "").upper()
    if not icao:
        return []
    segments = aviation_data.taxiway_segments(icao)
    if not segments:
        return []
    half_width = _runway_half_width_m(rwy)
    rwy_heading = float(rwy.get("primary", {}).get("heading_deg") or 0.0)
    length_m = None
    try:
        if rwy.get("length_ft"):
            length_m = float(rwy["length_ft"]) * 0.3048
    except (TypeError, ValueError):
        length_m = None
    hits: list[dict[str, Any]] = []
    for seg in segments:
        name = str(seg.get("name") or "").strip()
        if not name:
            continue
        try:
            w_ft = float(seg.get("width_ft") or 0.0)
        except (TypeError, ValueError):
            w_ft = 0.0
        width_m = (w_ft * 0.3048) if w_ft and w_ft > 0 else DEFAULT_TAXIWAY_WIDTH_M
        for lat_key, lon_key, other_key in (("start_lat", "start_lon", "end"), ("end_lat", "end_lon", "start")):
            lat, lon = seg.get(lat_key), seg.get(lon_key)
            try:
                lat, lon = float(lat), float(lon)
            except (TypeError, ValueError):
                continue
            proj = _project_onto_runway(lat, lon, rwy)
            if proj is None:
                continue
            along, cross = proj
            # v0.25.70: only endpoints AT the runway edge count as entries
            # (|cross| within ENTRY_MARGIN_M of the half-width). Endpoints in
            # the middle of the runway belong to taxiways that CROSS it and
            # would put the hold-short line on the runway surface.
            if abs(abs(cross) - half_width) > ENTRY_MARGIN_M:
                continue
            if length_m is not None and (along < -ENTRY_MARGIN_M or along > length_m + ENTRY_MARGIN_M):
                continue
            try:
                o_lat = float(seg[f"{other_key}_lat"])
                o_lon = float(seg[f"{other_key}_lon"])
            except (TypeError, ValueError, KeyError):
                o_lat, o_lon = lat, lon
            hdg = _bearing(lat, lon, o_lat, o_lon)
            # v0.25.70: reject near-PARALLEL segments (bearing within
            # ``_ENTRY_MIN_ANGLE_DEG`` of the runway). A parallel taxiway
            # running along the edge does not ENTER the runway -- its
            # "hold-short line" would be perpendicular to it, i.e. a line
            # spanning the runway surface (EHAM S8, bearing == runway
            # heading, put barricades across the runway at cross 0..18 m).
            off = abs((hdg - rwy_heading) % 180.0)
            off = min(off, 180.0 - off)
            if off < _ENTRY_MIN_ANGLE_DEG:
                continue
            # The entry carries the taxiway bearing (endpoint -> far end) and
            # width so _barrier_line can build the hold-short line
            # perpendicular to the taxiway, backed off from the runway edge.
            hits.append({
                "name": name, "lat": lat, "lon": lon, "along_m": along, "cross_m": cross,
                "away_lat": o_lat, "away_lon": o_lon, "heading_deg": hdg,
                "width_m": min(width_m, MAX_TAXIWAY_ENTRY_WIDTH_M),
            })
    if not hits:
        return []
    # Cluster by (name, side of the centreline), then greedily by along-
    # position so adjacent fragments of the same taxiway merge into a single
    # hold-short point; each edge of a crossing taxiway stays separate.
    by_name: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for hit in hits:
        by_name.setdefault((hit["name"], 1 if hit["cross_m"] >= 0.0 else -1), []).append(hit)
    entries: list[dict[str, Any]] = []
    for (name, _side), group in sorted(by_name.items(), key=lambda kv: kv[0]):
        group.sort(key=lambda h: h["along_m"])
        clusters: list[list[dict[str, Any]]] = []
        for hit in group:
            placed_cluster = None
            for cluster in clusters:
                # Cluster by 2D distance to the previous hit of the chain, not
                # along-position alone: fragmented LNM segments of one entry
                # (EHAM S1 produced three near-identical hold-short lines a
                # few metres apart) cluster together, while distinct entries
                # of the same taxiway (typically 100 m+ apart) stay separate.
                if _dist_m(cluster[-1]["lat"], cluster[-1]["lon"], hit["lat"], hit["lon"]) <= ENTRY_CLUSTER_M:
                    placed_cluster = cluster
                    break
            if placed_cluster is not None:
                placed_cluster.append(hit)
            else:
                clusters.append([hit])
        for cluster in clusters:
            along = sum(h["along_m"] for h in cluster) / len(cluster)
            # Representative hit: the one nearest the runway edge (the
            # hold-short point is where the taxiway first meets the runway).
            rep = min(cluster, key=lambda h: abs(abs(h["cross_m"]) - half_width))
            # Project the entry onto the runway edge along the taxiway
            # bearing: the hold-short line sits where the taxiway crosses the
            # edge, not at the raw segment endpoint (which can sit a few
            # metres inside or past the edge). Near-parallel segments (no
            # clean edge crossing) keep their endpoint as-is.
            delta_deg = (rep["heading_deg"] - rwy_heading) % 360.0
            delta_rad = math.radians(delta_deg)
            sin_a = math.sin(delta_rad)
            if abs(sin_a) >= 0.15:
                s = 1.0 if rep["cross_m"] >= 0.0 else -1.0
                t = (s * half_width - rep["cross_m"]) / sin_a
                # Clamp to a generous walk: the entry endpoint sits at most
                # ENTRY_MARGIN_M inside the edge, and the shallowest kept
                # entry angle is _ENTRY_MIN_ANGLE_DEG (sin >= 0.17), so the
                # edge crossing is at most ~70 m along the taxiway.
                t = max(-80.0, min(80.0, t))
                along_edge = rep["along_m"] + t * math.cos(delta_rad)
                elat, elon = _back_to_latlon(rwy, along_edge, s * half_width)
            else:
                elat, elon = rep["lat"], rep["lon"]
            entries.append({
                "name": name, "along_m": along,
                "lat": elat, "lon": elon,
                "away_lat": rep["away_lat"], "away_lon": rep["away_lon"],
                "heading_deg": rep["heading_deg"], "width_m": rep["width_m"],
            })
    # v0.25.71: merge hold-short lines that land on top of each other even
    # when they carry DIFFERENT taxiway names (``A``/``A1`` fragments of one
    # entry, dual-pavement rows, or adjacent connectors - EGLL A2/A3 29 m
    # apart, AB10W fragments 38 m apart). Two lines within ENTRY_LINE_MERGE_M
    # of each other rendered as a staggered double row in-sim; one line is
    # kept, RE-CENTRED on the junction mean and sized from the widest entry
    # so the single row still covers every connector.
    entries.sort(key=lambda e: e["along_m"])
    merged: list[dict[str, Any]] = []
    for entry in entries:
        placed_in = None
        for line in merged:
            if _dist_m(line["lat"], line["lon"], entry["lat"], entry["lon"]) <= ENTRY_LINE_MERGE_M:
                placed_in = line
                break
        if placed_in is None:
            merged.append({**entry, "_n": 1})
        else:
            idx = merged.index(placed_in)
            a, b = placed_in, entry
            n = int(a.get("_n", 1))
            merged[idx] = {
                "name": a["name"],
                "along_m": (a["along_m"] * n + b["along_m"]) / (n + 1),
                "lat": (a["lat"] * n + b["lat"]) / (n + 1),
                "lon": (a["lon"] * n + b["lon"]) / (n + 1),
                "away_lat": a["away_lat"],
                "away_lon": a["away_lon"],
                "heading_deg": b["heading_deg"] if b["width_m"] > a["width_m"] else a["heading_deg"],
                "width_m": max(a["width_m"], b["width_m"]),
                "_n": n + 1,
            }
    for line in merged:
        line.pop("_n", None)
    return merged


def _runway_crossing_points(rwy: dict[str, Any]) -> list[dict[str, Any]]:
    """Points where other runways at the same airport cross the closed runway.

    Uses navdata runway centerlines (both schemas). The crossing is the
    closest point on the closed runway to the other runway's centerline where
    the two are within a small distance of each other. Degrades to [] without
    navdata.
    """
    icao = str(rwy.get("airport_ident") or "").upper()
    if not icao:
        return []
    out: list[dict[str, Any]] = []
    for other in navdata.runway_candidates(icao):
        other_full = None
        for name in (str(other.get("name_a") or other.get("primary_end_name") or "").upper(),
                     str(other.get("name_b") or other.get("secondary_end_name") or "").upper()):
            if name:
                other_full = navdata.runway_full(icao, name)
                if other_full:
                    break
        if not other_full:
            continue
        if other_full.get("runway") == rwy.get("runway"):
            continue
        op = other_full.get("primary")
        if op is None or op.get("lat") is None or op.get("lon") is None:
            continue
        # Sample the other runway centerline and find the point closest to ours.
        best: tuple[float, float, float] | None = None  # (along_m, cross_m, min_cross)
        other_heading = float(op.get("heading_deg") or 0.0)
        other_len = None
        try:
            if other_full.get("length_ft"):
                other_len = float(other_full["length_ft"]) * 0.3048
        except (TypeError, ValueError):
            other_len = None
        samples = 40
        for i in range(samples + 1):
            t = (i / samples) * (other_len or 3000.0)
            lat, lon = _line_offset_point(float(op["lat"]), float(op["lon"]), other_heading, t, lat_m=True)
            proj = _project_onto_runway(lat, lon, rwy)
            if proj is None:
                continue
            along, cross = proj
            if best is None or abs(cross) < best[2]:
                best = (along, cross, abs(cross))
        if best is None:
            continue
        along, cross, min_cross = best
        if min_cross > _runway_half_width_m(rwy) + ENTRY_MARGIN_M:
            continue
        other_name = str(other_full.get("runway") or "crossing")
        out.append({"name": other_name, "along_m": along})
    return out


def _barrier_line(line: dict[str, Any], altitude_ft: float, geometry_source: str, rwy: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Barricade line across a taxiway HOLD-SHORT line (or a runway crossing).

    v0.25.70 (in-sim review at EGKK 26L): barricades must sit on the taxiway
    hold-short line -- backed off from the runway edge -- NOT spanned across
    the runway like the old tier (which put the line on the runway, parallel
    to the taxiway). The line is built from a single barricade type (orange
    Type III) spaced BARRIER_SPACING_M apart so the 3.6 m models connect
    edge-to-edge with a small gap.

    v0.25.71 (EGKK 26L in-sim review): back the row off the runway edge -
    ``HOLD_SHORT_BACKOFF_M`` measured PERPENDICULAR off the edge (a walk
    ALONG a shallow taxiway barely clears the edge, which is how the row
    ended up on the runway).

    v0.25.74 (user: "going out of the taxiway onto the ground - the length
    was too long, or the position misplaced"): the v0.25.71-v0.25.73 rows
    ran PARALLEL to the runway and were sized ``width / sin(entry angle)``.
    For a diagonal taxiway that puts the whole row BESIDE the taxiway on
    the grass (the row centre sits at a fixed cross offset, but the taxiway
    only reaches that cross far up the runway) and stretches it 3-4x the
    taxiway width. The row now:
      - runs PERPENDICULAR to the taxiway (across the pavement, like the
        painted hold-short bar), and
      - is centred ON the taxiway centreline at the point where the
        taxiway is ``HOLD_SHORT_BACKOFF_M`` off the runway edge (the centre
        is walked ALONG the taxiway by backoff / sin(entry angle)), and
      - spans exactly the taxiway width (``width_m``), so the ends stay on
        the pavement.
    The barricade heading is the ROW direction (v0.25.74: the X-marker
    ground truth the user confirmed shows MSFS heading = the model's glTF
    +X axis bearing - the runway X at heading 32.6 = bearing 77.6 - 45 has
    arms along the model X axis at 45 deg to the runway). The T3's long
    axis is glTF X, so heading = row direction lays the panels edge-to-edge
    ALONG the row into a continuous "--------" wall (the old row - 90
    heading laid the long axis ACROSS the row = end-on "||||").

    ``line`` carries the taxiway entry geometry (lat/lon at the runway edge,
    ``heading_deg`` = taxiway bearing, ``width_m`` = taxiway width) when it
    is a hold-short line, or only ``along_m`` when it is a runway crossing
    (no taxiway geometry) -- in that case the line spans the closed runway
    at the crossing point, still single-type and edge-connected.
    """
    heading = float(line.get("heading_deg") or 0.0)
    placements: list[dict[str, Any]] = []
    if line.get("heading_deg") is not None and line.get("lat") is not None:
        # Taxiway hold-short line: back off into the taxiway (before the
        # runway surface) then span the taxiway's own width across it.
        width_m = float(line.get("width_m") or DEFAULT_TAXIWAY_WIDTH_M)
        rwy_heading: float | None = None
        if rwy is not None and rwy.get("primary", {}).get("heading_deg") is not None:
            rwy_heading = float(rwy["primary"]["heading_deg"])
        # v0.25.74: row centre on the TAXIWAY centreline, at the point where
        # the taxiway is HOLD_SHORT_BACKOFF_M off the runway edge (measured
        # perpendicular to the runway). Walking the backoff ALONG the taxiway
        # by backoff / sin(entry angle) keeps a diagonal row on the pavement
        # instead of beside it. Capped so a degenerate near-parallel entry
        # cannot walk the row hundreds of metres.
        if rwy_heading is not None:
            entry_angle = abs((heading - rwy_heading) % 180.0)
            entry_angle = min(entry_angle, 180.0 - entry_angle)
            sin_a = max(math.sin(math.radians(max(entry_angle, _ENTRY_MIN_ANGLE_DEG))), 0.17)
        else:
            sin_a = 1.0
        # v0.25.76: the row centre must sit 250 ft from the runway CENTRELINE
        # (user: "200-250ft from the runway centerline"), i.e. a perpendicular
        # walk of (250 ft - half-width) off the EDGE, then walked ALONG the
        # taxiway by /sin(entry angle) so a diagonal row stays on the
        # pavement. Previously the back-off was measured from the edge only.
        half_width = _runway_half_width_m(rwy) if rwy is not None else DEFAULT_RUNWAY_WIDTH_M / 2.0
        backoff_from_edge = max(HOLD_SHORT_BACKOFF_CL_FT * 0.3048 - half_width, 20.0)
        backoff_along = min(backoff_from_edge / sin_a, 200.0)
        e_lat, e_lon = float(line["lat"]), float(line["lon"])
        e_proj = _project_onto_runway(e_lat, e_lon, rwy) if rwy is not None else None
        away_proj = None
        if rwy is not None and line.get("away_lat") is not None:
            away_proj = _project_onto_runway(float(line["away_lat"]), float(line["away_lon"]), rwy)
        # v0.25.74: the taxiway bearing must point INTO the airport (away
        # from the runway). A segment that CROSSES the runway has its far end
        # on the OPPOSITE edge, so the edge-endpoint bearing points ACROSS the
        # runway and walking it pulls the row toward the centreline (seen
        # in-sim/validator: rows spanning cross 3..24 m). Flip the bearing
        # when the far end is not further from the centreline than the entry.
        if away_proj is not None and e_proj is not None and abs(away_proj[1]) <= abs(e_proj[1]):
            heading = (heading + 180.0) % 360.0
        base_lat, base_lon = _line_offset_point(e_lat, e_lon, heading, backoff_along, lat_m=True)
        # v0.25.74: when the segment extends away from the runway, keep the
        # row INSIDE it - clamp the walk to the segment length so a short
        # stub never places the row past the pavement.
        if away_proj is not None and e_proj is not None and abs(away_proj[1]) > abs(e_proj[1]):
            seg_len = _dist_m(e_lat, e_lon, float(line["away_lat"]), float(line["away_lon"]))
            if backoff_along > seg_len - 8.0:
                base_lat, base_lon = _line_offset_point(
                    e_lat, e_lon, heading, max(seg_len - 8.0, 12.0), lat_m=True
                )
        # v0.25.74: row spans exactly the taxiway width (perpendicular to
        # the taxiway), so the ends stay on the pavement - NOT the old
        # width / sin(angle) length that stretched 3-4x wide on shallow
        # entries and dumped the ends on the grass.
        row_len = width_m
        count = max(1, min(int(math.ceil(row_len / BARRIER_SPACING_M)), MAX_HOLD_SHORT_ROW_COUNT))
        # v0.25.74: row direction = PERPENDICULAR to the taxiway (across the
        # pavement, like the painted hold-short bar).
        row_heading = (heading + 90.0) % 360.0
        # v0.25.76: MSFS heading orients the model's glTF +Z axis (the
        # user's clean in-sim observation at EGKK with the static package:
        # with heading = row direction the T3 panels' LONG axis (glTF X, 90
        # deg behind Z) read PARALLEL to the taxiway, i.e. across the row =
        # "||||"). So heading = row + 90 lays the long axis ALONG the row
        # into a connected "--------" wall PERPENDICULAR to the taxiway
        # (the user's requirement).
        barricade_heading = (row_heading + 90.0) % 360.0
        for i in range(count):
            offset = (i - (count - 1) / 2.0) * BARRIER_SPACING_M
            lat, lon = _line_offset_point(base_lat, base_lon, row_heading, offset, lat_m=True)
            placements.append(
                {
                    "airport_icao": line.get("airport_icao"),
                    "kind": "barrier",
                    "ref": line.get("ref"),
                    "lat": round(lat, 7),
                    "lon": round(lon, 7),
                    "heading_deg": round(barricade_heading, 2),
                    "altitude_ft": round(float(altitude_ft or 0.0), 2),
                    "placement": "hold-short-line",
                    "object": SIMOBJECT_TITLE_BARRICADE_T3_ORANGE,
                    "geometry_source": geometry_source,
                }
            )
        return placements
    # Runway crossing (another runway crosses the closed one): span the
    # closed runway at the crossing point, single type, edge-connected.
    if rwy is None:
        return placements
    half_width = _runway_half_width_m(rwy)
    width_m = half_width * 2.0
    count = max(1, int(math.ceil(width_m / BARRIER_SPACING_M)))
    rwy_heading = float(rwy.get("primary", {}).get("heading_deg") or 0.0)
    for i in range(count):
        offset = (i - (count - 1) / 2.0) * BARRIER_SPACING_M
        lat, lon = _back_to_latlon(rwy, float(line["along_m"]), offset)
        placements.append(
            {
                "airport_icao": rwy.get("airport_ident"),
                "kind": "barrier",
                "ref": rwy.get("runway"),
                "lat": round(lat, 7),
                "lon": round(lon, 7),
                "heading_deg": round(rwy_heading, 2),
                "altitude_ft": round(float(altitude_ft or 0.0), 2),
                "placement": "runway-crossing",
                "object": SIMOBJECT_TITLE_BARRICADE_T3_ORANGE,
                "geometry_source": geometry_source,
            }
        )
    return placements


def _taxiway_entry_junctions(icao: str, ref: str, max_entries: int = 8) -> list[tuple[float, float]]:
    """Junction points where other taxiways/connectors meet a closed taxiway.

    Scans segment geometry (LNM DB first, bundle fallback) and returns
    endpoints of NON-matching segments that land within ``_ENTRY_JOIN_M`` of
    an endpoint of a matching segment (the closed taxiway). Endpoints within
    ``_ENTRY_CLUSTER_M`` of each other are merged into one entry (fragmented
    geometry produces several near-identical junction endpoints). Ordered by
    proximity to the taxiway's own centreline footprint; capped at
    ``max_entries`` so a heavily-connected taxiway does not flood the sim.
    """
    ref = str(ref or "").upper().strip()
    if not ref:
        return []
    try:
        segments = aviation_data.taxiway_segments(icao)
    except Exception:  # pragma: no cover - defensive navdata path
        return []
    if not segments:
        return []
    matched = [s for s in segments if str(s.get("name") or "").upper() == ref]
    if not matched:
        matched = [s for s in segments
                   if str(s.get("name") or "").upper().startswith(ref)
                   and str(s.get("name") or "").upper()[len(ref):].isdigit()]
    if not matched:
        return []

    def _ends(seg: dict[str, Any]) -> list[tuple[float, float]]:
        return [(float(seg["start_lat"]), float(seg["start_lon"])),
                (float(seg["end_lat"]), float(seg["end_lon"]))]

    twy_ends = [pt for s in matched for pt in _ends(s)]
    raw: set[tuple[float, float]] = set()
    for seg in segments:
        if seg in matched:
            continue
        name = str(seg.get("name") or "").upper()
        # Only real named taxiways/connectors join a closed taxiway; skip
        # anonymous noise unless it is a short stub right on the line.
        for pt in _ends(seg):
            for tpt in twy_ends:
                if _dist_m(pt[0], pt[1], tpt[0], tpt[1]) <= _ENTRY_JOIN_M:
                    raw.add((round(pt[0], 6), round(pt[1], 6)))
                    break
    if not raw:
        return []
    # Merge nearby endpoints into one entry (fragmented geometry).
    points = sorted(raw)
    clusters: list[list[tuple[float, float]]] = []
    for pt in points:
        placed = False
        for cluster in clusters:
            if _dist_m(pt[0], pt[1], cluster[0][0], cluster[0][1]) <= ENTRY_CLUSTER_M:
                cluster.append(pt)
                placed = True
                break
        if not placed:
            clusters.append([pt])
    entries = [(sum(p[0] for p in c) / len(c), sum(p[1] for p in c) / len(c)) for c in clusters]
    # Order by distance to the closed taxiway centreline footprint, nearest
    # first, so the cap keeps the junctions that visibly touch the taxiway.
    geometry = _taxiway_geometry(icao, ref)
    if geometry:
        centre = (float(geometry["lat"]), float(geometry["lon"]))
        entries.sort(key=lambda e: _dist_m(e[0], e[1], centre[0], centre[1]))
    return entries[:max_entries]


def _taxiway_geometry(icao: str, ref: str, anchor: tuple[float, float] | None = None) -> dict[str, Any] | None:
    """Centroid (or aircraft-nearest segment) + heading of a closed taxiway.

    v0.25.67: taxiway markers used to drop at the airport reference point,
    which can sit ~500 m from the closed taxiway (the in-sim offset report
    at EGKK). When segment geometry exists (local Little Navmap DB first,
    built-in bundle fallback), return the mean of every segment endpoint
    whose name matches the designator (exact match first, then a base
    prefix like ``Y`` matching ``Y1``) plus the heading of the longest
    segment.

    v0.25.69: with ``anchor`` (aircraft lat/lon) place the marker on the
    midpoint of the segment NEAREST the aircraft instead of the whole-
    taxiway endpoint mean. Fragmented taxiway data (EGKK taxiway ``Y`` is
    42 segments spanning two separate regions) pulled the mean to a point
    between the runway and the taxiway; anchoring to the aircraft keeps the
    marker on the taxiway the pilot can actually see. ``None`` when no
    geometry is available - the caller falls back to the airport centroid.
    """
    ref = str(ref or "").upper().strip()
    if not ref:
        return None
    try:
        segments = aviation_data.taxiway_segments(icao)
    except Exception:  # pragma: no cover - defensive navdata path
        return None
    if not segments:
        return None
    matched = [s for s in segments if str(s.get("name") or "").upper() == ref]
    if not matched:
        # Digit-suffix only ("Y" matching "Y1") - a letter-suffixed segment
        # ("AN" for ref "A") is a DIFFERENT taxiway and must never absorb the
        # marker (that would trade a ~500 m centroid error for a wrong-taxiway
        # placement).
        matched = [s for s in segments
                   if str(s.get("name") or "").upper().startswith(ref)
                   and str(s.get("name") or "").upper()[len(ref):].isdigit()]
    if not matched:
        return None
    if anchor is not None:
        a_lat = float(anchor[0])
        a_lon = float(anchor[1])

        def _project(seg: dict[str, Any]) -> tuple[float, float, float, float, float] | None:
            """Point-to-segment projection of the anchor (dist_m, foot_lat,
            foot_lon, heading, seg_len) in a local metre frame."""
            try:
                slat, slon = float(seg["start_lat"]), float(seg["start_lon"])
                elat, elon = float(seg["end_lat"]), float(seg["end_lon"])
            except (KeyError, TypeError, ValueError):
                return None
            kx = 111_320.0 * math.cos(math.radians(a_lat))
            ky = 111_320.0
            ax, ay = (slon - a_lon) * kx, (slat - a_lat) * ky
            bx, by = (elon - a_lon) * kx, (elat - a_lat) * ky
            dx, dy = bx - ax, by - ay
            length_sq = dx * dx + dy * dy
            if length_sq < 1e-9:
                return None
            t = max(0.0, min(1.0, (-ax * dx - ay * dy) / length_sq))
            fx, fy = ax + t * dx, ay + t * dy
            heading = math.degrees(math.atan2(dx, dy)) % 360.0
            return (math.hypot(fx, fy), a_lat + fy / ky, a_lon + fx / kx, heading, math.hypot(dx, dy))

        projected = [p for p in (_project(s) for s in matched) if p is not None]
        if projected:
            # Prefer the MAIN taxiway line: project onto segments at least a
            # quarter of the longest one, and take the nearest foot. The naive
            # "nearest segment midpoint" snapped to short connector stubs next
            # to the parked aircraft (EGKK Y stub 13 m away) instead of the
            # real taxiway 80 m away - the marker looked "right next to the
            # aircraft but not on the taxiway".
            max_len = max(p[4] for p in projected)
            main_line = [p for p in projected if p[4] >= max_len * 0.25]
            pool = main_line if main_line else projected
            best = min(pool, key=lambda p: p[0])
            # v0.25.70: X arms cross at 45 deg to the taxiway (model arms run
            # along local X/Z axes) - in-sim verified at EGKK taxiway Y.
            heading = (best[3] - 45.0) % 180.0
            return {
                "lat": round(best[1], 7),
                "lon": round(best[2], 7),
                "heading_deg": round(heading, 2),
            }
    lats: list[float] = []
    lons: list[float] = []
    best_length = -1.0
    best_heading = 0.0
    for seg in matched:
        try:
            slat, slon = float(seg["start_lat"]), float(seg["start_lon"])
            elat, elon = float(seg["end_lat"]), float(seg["end_lon"])
        except (KeyError, TypeError, ValueError):
            continue
        lats.extend((slat, elat))
        lons.extend((slon, elon))
        dlat = (elat - slat) * 111_320.0
        dlon = (elon - slon) * 111_320.0 * math.cos(math.radians((slat + elat) / 2.0))
        length = math.hypot(dlat, dlon)
        if length > best_length:
            best_length = length
            best_heading = math.degrees(math.atan2(dlon, dlat)) % 360.0
    if not lats:
        return None
    # v0.25.70: X arms cross at 45 deg to the taxiway (model arms run along
    # local X/Z axes) - in-sim verified at EGKK taxiway Y.
    heading = (best_heading - 45.0) % 180.0
    return {
        "lat": round(sum(lats) / len(lats), 7),
        "lon": round(sum(lons) / len(lons), 7),
        "heading_deg": round(heading, 2),
    }


def plan_markers(markers: list[dict[str, Any]] | None, anchor: tuple[float, float] | None = None) -> dict[str, Any]:
    """Marker refs -> placements using navdata + taxiway geometry.

    Runway closures place:
      - an X at each closed threshold (heading faces the aircraft anchor so
        the vertical LIGHTED sign reads correctly from the cockpit; without
        an anchor it faces perpendicular to the runway centreline), and
      - orange/white barrier lines across the runway at every taxiway entry
        (hold-short position) and every runway crossing, when taxiway
        geometry is available from the local LNM DB or the built-in bundle.
    Taxiway closures without geometry place at the airport reference point
    (``placement='airport-centroid'``, documented simplification). Anything
    without navdata is returned as ``unplaced``.

    ``anchor`` (aircraft lat/lon, v0.25.69) is passed to the taxiway
    geometry placement so the X lands on the segment nearest the pilot
    instead of the whole-taxiway endpoint mean (which can sit between the
    runway and the taxiway on fragmented geometry like EGKK taxiway Y).
    """
    placed: list[dict[str, Any]] = []
    unplaced: list[dict[str, Any]] = []
    barriers_spawned = 0
    # v0.25.71: "RWY 09L/27R CLSD" yields two refs for the SAME physical
    # runway, and each ref pass computes the barrier tier in ITS OWN frame -
    # the two passes produced rows offset by 0.6-0.8 m that overlapped in-sim
    # (EGLL 09L/27R: interleaved rows). The barrier tier runs once per
    # physical runway (canonical ``runway`` name); both threshold X's are
    # still placed (they are different positions).
    barriered_runways: set[tuple[str, str]] = set()
    for marker in markers or []:
        icao = str(marker.get("airport_icao") or "").upper()
        kind = str(marker.get("kind") or "")
        ref = str(marker.get("ref") or "").upper()
        if kind == "runway":
            entry = navdata.runway_by_name(icao, ref) if icao else None
            lat = entry.get("threshold_lat") if isinstance(entry, dict) else None
            if entry and lat is not None and entry.get("threshold_lon") is not None:
                # v0.25.70: the X sits on the numbering/threshold, not the
                # physical runway end (in-sim verification at EGKK: the end
                # placement was on the edge, and the runway there is extended
                # past the numbering with an arrowed patch ~100 m before it).
                # Displaced thresholds carry the numbering further in.
                rwy_heading = float(entry.get("heading_deg") or 0.0)
                offset_ft = float(entry.get("displaced_threshold_ft") or 0.0)
                if offset_ft <= 0.0:
                    offset_ft = RUNWAY_X_OFFSET_FT
                xlat, xlon = _line_offset_point(
                    float(lat), float(entry["threshold_lon"]), rwy_heading, offset_ft * 0.3048, lat_m=True
                )
                # v0.25.71: snap the runway X EXACTLY onto the centreline.
                # The threshold lat/lon in navdata can sit a fraction of a
                # metre off the painted line, and in-sim review at EGKK 26L
                # reported the X "off the centerline". Project the offset
                # point onto the runway and force cross = 0 so the X always
                # lands dead-centre regardless of navdata threshold jitter.
                rwy_snap = navdata.runway_full(icao, ref)
                if rwy_snap:
                    proj = _project_onto_runway(xlat, xlon, rwy_snap)
                    if proj:
                        xlat, xlon = _back_to_latlon(rwy_snap, proj[0], 0.0)
                # v0.25.76: RUNWAY closures deploy the LIGHTED X, which is a
                # VERTICAL sign (arms in the model's X-Y plane, face normal =
                # glTF Z). MSFS heading orients the model's glTF +Z axis (the
                # barricade ground truth below confirms the convention), so
                # the sign's FACE points at bearing = heading directly, and
                # the LIT face (glTF -Z, where the lamp fixtures protrude)
                # points at heading + 180. A vertical sign only reads
                # correctly when its face points at the viewer - the user's
                # manual X (in-sim ground truth) faces the aircraft. So the
                # heading is set so the LIT face points at the anchor:
                # heading = bearing(X -> anchor) - 180. Without an anchor the
                # sign faces perpendicular to the runway centreline
                # (heading = runway heading + 90), i.e. its flat face runs
                # ALONG the centreline so runway traffic reads it face-on.
                if anchor is not None:
                    x_heading = (_bearing(xlat, xlon, float(anchor[0]), float(anchor[1])) - 180.0) % 360.0
                else:
                    x_heading = (rwy_heading + 90.0) % 360.0
                placed.append(
                    {
                        "airport_icao": icao,
                        "kind": "runway",
                        "ref": ref,
                        "lat": round(xlat, 7),
                        "lon": round(xlon, 7),
                        "heading_deg": round(x_heading, 2),
                        "altitude_ft": float(entry.get("threshold_elevation_ft") or 0.0),
                        "placement": "runway-threshold",
                        "object": _SIMOBJECT_TITLES["runway"],
                    }
                )
                # v0.25.65 hold-short tier: barriers at taxiway entries + crossings.
                rwy = navdata.runway_full(icao, ref)
                if rwy:
                    # v0.25.71: skip the tier when this physical runway was
                    # already barricaded by its other ref (09L vs 27R).
                    canonical = (icao, str(rwy.get("runway") or ref).upper())
                    if canonical in barriered_runways:
                        rwy = None
                    else:
                        barriered_runways.add(canonical)
                if rwy:
                    source = aviation_data.local_surface_source()
                    geometry_source = "local-lnm" if source.get("available") else "built-in-bundle"
                    threshold_alt = float(entry.get("threshold_elevation_ft") or 0.0)
                    lines: list[dict[str, Any]] = []
                    for tp in _taxiway_entry_points(rwy):
                        # Carry the full hold-short geometry (taxiway bearing,
                        # width, runway-edge point) so _barrier_line can build
                        # the line across the TAXIWAY, not across the runway.
                        lines.append({**tp, "airport_icao": icao, "ref": ref, "geometry_source": geometry_source})
                    for cp in _runway_crossing_points(rwy):
                        lines.append({"name": f"RWY {cp['name']}", "along_m": cp["along_m"], "geometry_source": "navdata-centerline"})
                    # Deduplicate overlapping lines by along-position.
                    seen: set[int] = set()
                    unique_lines: list[dict[str, Any]] = []
                    for line in sorted(lines, key=lambda x: x["along_m"]):
                        bucket = int(round(line["along_m"] / 5.0))
                        if bucket in seen:
                            continue
                        seen.add(bucket)
                        unique_lines.append(line)
                    # v0.25.70: spend the barrier budget where the pilot can
                    # see it. The cap is far smaller than a full closure's
                    # needs (38 lines / ~1000 barricades at EGKK 26L), and
                    # the old ascending along-position order filled it with
                    # entries at the far runway end first. When an anchor
                    # (aircraft position) is available, order lines by
                    # distance along the runway so the nearest entries are
                    # barricaded first and the cap never starves the visible
                    # hold-short lines.
                    anchor_along: float | None = None
                    if anchor is not None:
                        try:
                            proj = _project_onto_runway(float(anchor[0]), float(anchor[1]), rwy)
                            if proj:
                                anchor_along = proj[0]
                        except (TypeError, ValueError):  # pragma: no cover - defensive
                            anchor_along = None
                    ordered_lines = unique_lines
                    if anchor_along is not None:
                        ordered_lines = sorted(
                            unique_lines, key=lambda line: abs(float(line["along_m"]) - anchor_along)
                        )
                    for line in ordered_lines:
                        if barriers_spawned >= MAX_BARRIER_SPAWNS:
                            break
                        count_before = len(placed)
                        placed.extend(_barrier_line(line, threshold_alt, line.get("geometry_source") or geometry_source, rwy))
                        barriers_spawned += len(placed) - count_before
            else:
                unplaced.append({**marker, "ref": ref, "reason": "no runway-end navdata"})
        else:
            airport = navdata.airport(icao) if icao else None
            if not (airport and airport.get("lat") is not None and airport.get("lon") is not None):
                unplaced.append({**marker, "ref": ref, "reason": "no airport navdata"})
                continue
            altitude_ft = float(airport.get("altitude_ft") or airport.get("elevation_ft") or 0.0) + 3.0
            # v0.25.67: place the taxiway X on the ACTUAL closed taxiway
            # (segment geometry) instead of the airport reference point -
            # the centroid can sit ~500 m from the taxiway (the in-sim
            # offset report at EGKK). Falls back to the centroid when no
            # geometry exists.
            geometry = _taxiway_geometry(icao, ref, anchor)
            if geometry:
                placed.append(
                    {
                        "airport_icao": icao,
                        "kind": "taxiway",
                        "ref": ref,
                        "lat": geometry["lat"],
                        "lon": geometry["lon"],
                        "heading_deg": geometry["heading_deg"],
                        "altitude_ft": altitude_ft,
                        "placement": "taxiway-geometry",
                        "object": _SIMOBJECT_TITLES["taxiway"],
                    }
                )
                # v0.25.70: X at every junction where another taxiway meets
                # the closed one, so traffic is warned before entering it
                # (in-sim verified at EGKK taxiway Y). Junctions that sit on
                # top of the main on-line X are skipped - they are the same
                # marker (EGKK Y entry 77 m from the aircraft landed 8 m
                # from the main X and was flagged redundant in-sim).
                main_lat = float(geometry["lat"])
                main_lon = float(geometry["lon"])
                for ejlat, ejlon in _taxiway_entry_junctions(icao, ref):
                    if _dist_m(ejlat, ejlon, main_lat, main_lon) <= ENTRY_CLUSTER_M:
                        continue
                    placed.append(
                        {
                            "airport_icao": icao,
                            "kind": "taxiway",
                            "ref": ref,
                            "lat": round(ejlat, 7),
                            "lon": round(ejlon, 7),
                            "heading_deg": geometry["heading_deg"],
                            "altitude_ft": altitude_ft,
                            "placement": "taxiway-entry",
                            "object": _SIMOBJECT_TITLES["taxiway"],
                        }
                    )
            else:
                placed.append(
                    {
                        "airport_icao": icao,
                        "kind": "taxiway",
                        "ref": ref,
                        "lat": float(airport["lat"]),
                        "lon": float(airport["lon"]),
                        "heading_deg": 0.0,
                        "altitude_ft": altitude_ft,
                        "placement": "airport-centroid",
                        "object": _SIMOBJECT_TITLES["taxiway"],
                    }
                )
    # v0.25.70: "RWY 08R/26L CLSD" yields two refs for the SAME runway, each
    # of which runs the barrier tier -- every barricade used to be placed
    # twice (140 placements for 70 unique barricades at LFPG). Collapse
    # identical placements (same object + position) across the whole plan;
    # the threshold X's for both ends of the runway are different positions
    # and are kept.
    #
    # v0.25.71: the two ref passes project the same physical taxiway entry
    # from OPPOSITE ends, so the duplicate rows can sit 0.6-0.8 m apart
    # (never bit-identical) - a coordinate-rounding key missed them and the
    # sim got two overlapping rows (EGLL 09L/27R: interleaved 0.77/2.93 m
    # spacing). Cluster by 2D distance (<= 2 m, same object) instead; real
    # barricades are 3.7 m apart and hold-short rows >= 20 m apart, so
    # nothing legitimate merges.
    unique_placed: list[dict[str, Any]] = []
    for p in placed:
        duplicate = False
        for u in unique_placed:
            if str(u.get("object") or "") != str(p.get("object") or ""):
                continue
            if _dist_m(
                float(u.get("lat") or 0.0), float(u.get("lon") or 0.0),
                float(p.get("lat") or 0.0), float(p.get("lon") or 0.0),
            ) <= 2.0:
                duplicate = True
                break
        if not duplicate:
            unique_placed.append(p)
    placed = unique_placed
    return {"placed": placed, "unplaced": unplaced, "count": len(placed)}


def _cached_briefing_notams() -> list[dict[str, Any]]:
    """NOTAM rows from the cached operational briefing (never forces a refetch)."""
    try:
        from . import briefing_data

        briefing = briefing_data.operational_briefing(force=False)
        rows = briefing.get("notams") if isinstance(briefing, dict) else []
        return rows if isinstance(rows, list) else []
    except Exception as exc:  # pragma: no cover - defensive status path
        _LOGGER.debug("closure markers: briefing notams unavailable: %s", exc)
        return []


def build_marker_plan(notams: list[dict[str, Any]] | None = None, anchor: tuple[float, float] | None = None) -> dict[str, Any]:
    """Full plan: parse cached briefing NOTAMs (or caller rows) and place them.

    ``anchor`` (aircraft lat/lon) is forwarded to ``plan_markers`` so
    taxiway X markers sit on the segment nearest the pilot (v0.25.69).
    """
    rows = notams if notams is not None else _cached_briefing_notams()
    markers = parse_active_closures(rows)
    plan = plan_markers(markers, anchor=anchor)
    plan["markers"] = markers
    return plan


class _SimObjectSession:
    """Lazy dedicated SimConnect session for spawning closure markers.

    One session per process; MSFS permits multiple SimConnect clients, and
    keeping this separate from the telemetry session avoids touching the
    FSUIPC/SimConnect arbitration or the recorder.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sm: Any = None
        self._error: str | None = None
        #: (request_id, object_id, title) for every object we created this
        #: session, used by ``remove_markers``. MSFS assigns object IDs
        #: asynchronously; the python SimConnect lib surfaces them through the
        #: ``SIMCONNECT_OBJECT_ID`` environment variable (last assigned). We
        #: poll for a *change* after each create request to capture the ID
        #: belonging to that request before the next spawn shifts it.
        self._spawned: list[dict[str, Any]] = []

    def connect(self) -> Any:
        with self._lock:
            if self._sm is not None:
                return self._sm
            try:
                from .simconnect_position import _candidate_library_paths, _connect_with_timeout

                import SimConnect  # type: ignore[import-not-found]

                sm = SimConnect.SimConnect()
                _connect_with_timeout(sm, timeout_seconds=6.0)
                self._sm = sm
                self._error = None
                return sm
            except Exception as exc:
                self._error = f"{type(exc).__name__}: {exc}"
                self._sm = None
                return None

    def register_spawn(self, request_id: int, title: str, marker: dict[str, Any], source: str = "auto") -> None:
        with self._lock:
            self._spawned.append(
                {
                    "request_id": request_id,
                    "object_id": None,
                    "title": title,
                    "airport_icao": marker.get("airport_icao"),
                    "ref": marker.get("ref"),
                    "lat": marker.get("lat"),
                    "lon": marker.get("lon"),
                    "source": "manual" if source == "manual" else "auto",
                }
            )

    def capture_object_id(self, request_id: int, timeout_seconds: float = 2.0) -> int | None:
        """Poll the lib's SIMCONNECT_OBJECT_ID env var for a fresh assigned ID.

        Returns the object ID once it differs from every ID already captured,
        or ``None`` on timeout. Falls back to reading the env var directly
        when the lib has not been observed (e.g. headless test env).
        """
        import os
        import time

        seen = {item.get("object_id") for item in self._spawned}
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            raw = os.environ.get("SIMCONNECT_OBJECT_ID", "")
            try:
                object_id = int(raw)
            except (TypeError, ValueError):
                object_id = None
            if object_id is not None and object_id not in seen and object_id != 0:
                with self._lock:
                    for item in self._spawned:
                        if item["request_id"] == request_id and item.get("object_id") is None:
                            item["object_id"] = object_id
                return object_id
            time.sleep(0.02)
        return None

    def spawned(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._spawned]

    def clear_spawned(self) -> None:
        with self._lock:
            self._spawned.clear()

    def close(self) -> None:
        """Tear down the marker SimConnect session (v0.25.68).

        Stops the wrapper's dispatch thread during app shutdown so it cannot
        flood ``OS error: WinError 0xc00000b0`` and block a clean exit.
        """
        with self._lock:
            sm = self._sm
            self._sm = None
            self._error = None
            self._spawned = []
            if sm is not None:
                try:
                    sm.exit()
                except Exception:
                    pass


def shutdown_markers() -> None:
    """Close the closure-marker SimConnect session (app shutdown)."""
    _SESSION.close()


_SESSION = _SimObjectSession()


def marker_radius_nm() -> float:
    """Configurable auto-deploy radius (default 50 NM, capped 1..200).

    Order of precedence: ``OPSROOM_MARKER_RADIUS_NM`` env var, then the
    persisted ``integrations.marker_radius_nm`` setting.
    """
    radius = 50.0
    try:
        from .settings_store import load_settings

        radius = float(load_settings().get("integrations", {}).get("marker_radius_nm", 50.0) or 50.0)
    except Exception:
        pass
    try:
        env_radius = float(os.environ.get("OPSROOM_MARKER_RADIUS_NM", ""))
        if env_radius > 0:
            radius = env_radius
    except (TypeError, ValueError):
        pass
    return max(1.0, min(radius, 200.0))


def marker_altitude_gate_ft() -> float:
    """Above this AGL altitude markers are not spawned (default 15,000 ft)."""
    gate = 15000.0
    try:
        from .settings_store import load_settings

        gate = float(load_settings().get("integrations", {}).get("marker_altitude_gate_ft", 15000.0) or 15000.0)
    except Exception:
        pass
    try:
        env_gate = float(os.environ.get("OPSROOM_MARKER_ALTITUDE_GATE_FT", ""))
        if env_gate > 0:
            gate = env_gate
    except (TypeError, ValueError):
        pass
    return max(500.0, min(gate, 60000.0))


def marker_proximity_status() -> dict[str, Any]:
    """Nearest placed marker distance from the user aircraft, for the UI.

    Pure read of the live SimConnect position against the current marker plan
    (no spawns, no network). Returns the closest placement and its distance so
    the deploy control can explain why markers may be out of sight (e.g. "the
    aircraft is 412 NM from the nearest marker"). Never raises.
    """
    try:
        from . import simconnect_position

        pos = simconnect_position.read_position(force=False)
        if not isinstance(pos, dict) or not pos.get("ok"):
            return {"ok": False, "reason": "simulator position unavailable"}
        lat = float(pos.get("lat") or 0.0)
        lon = float(pos.get("lon") or 0.0)
        best: dict[str, Any] | None = None
        for item in _prox_placed():
            ilat, ilon = item.get("lat"), item.get("lon")
            if ilat is None or ilon is None:
                continue
            distance = _dist_m(lat, lon, float(ilat), float(ilon)) / 1852.0
            if best is None or distance < best.get("distance_nm", 1e9):
                best = {
                    "distance_nm": round(distance, 1),
                    "kind": str(item.get("kind") or ""),
                    "ref": str(item.get("ref") or ""),
                    "airport_icao": str(item.get("airport_icao") or ""),
                }
        if not best:
            return {"ok": True, "reason": "no markers planned"}
        return {"ok": True, "nearest": best}
    except Exception as exc:  # pragma: no cover - defensive status path
        _LOGGER.warning("closure markers: proximity status failed: %s", exc)
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}



def spawn_markers(placements: list[dict[str, Any]] | None, enabled: bool = False, source: str = "auto") -> dict[str, Any]:
    """Spawn one SimObject per placement via SimConnect ``AICreateSimulatedObject``.

    Guarded end to end: missing setting, no simulator, missing Community
    package or an unknown SimObject title all return ``ok=False`` with a
    reason instead of raising. The spawn result is only authoritative after
    in-sim verification (the AI object request is fire-and-forget; MSFS does
    not acknowledge creation synchronously). Object IDs are captured from the
    asynchronous assignment so ``remove_markers`` can clean up later.

    ``source`` tags each spawn as ``manual`` (user pressed DEPLOY IN SIM) or
    ``auto`` (background auto-deploy). ``remove_markers_outside_radius`` only
    despawns ``auto`` markers, so a manual deployment survives the auto-deploy
    radius sweep until the user explicitly removes it.
    """
    placements = placements or []
    if not enabled:
        return {"ok": True, "spawned": 0, "reason": "disabled", "markers": []}
    if not placements:
        return {"ok": True, "spawned": 0, "reason": "no placements", "markers": []}
    if not _is_windows():
        return {"ok": False, "spawned": 0, "reason": "SimConnect requires Windows", "markers": []}

    sm = _SESSION.connect()
    if sm is None:
        return {"ok": False, "spawned": 0, "reason": _SESSION._error or "SimConnect unavailable", "markers": []}

    dll = getattr(sm, "dll", None)
    # Bind BOTH creation exports, EX1 first -- MSFS 2024 accepts the legacy
    # 4-arg AICreateSimulatedObject only as a fallback, and the native bridge's
    # proven in-sim path is AICreateSimulatedObject_EX1 (h, title, livery,
    # initpos, requestid). The python SimConnect lib's wrapper only binds the
    # legacy export (and exposes no __getattr__), so resolve the RAW ctypes
    # DLL (``dll.SimConnect``) and look up the SDK export names directly, same
    # as opsroom_native_bridge._load_dll. The lib's own argtypes expect its
    # private SIMCONNECT_DATA_INITPOSITION class and a DATA_REQUEST_ID enum;
    # ctypes refuses to convert a different Structure class (and mis-handles
    # the enum slot), so every call would fail in-sim. The bridge's proven
    # pattern sets explicit argtypes -- handle BY VALUE (c_void_p),
    # title/livery, our struct, c_uint32 request ID.
    raw_dll = getattr(dll, "SimConnect", None) if dll is not None else None
    creators: list[tuple[str, Any]] = []
    if raw_dll is not None:
        create_ex1 = getattr(raw_dll, "SimConnect_AICreateSimulatedObject_EX1", None)
        create_legacy = getattr(raw_dll, "SimConnect_AICreateSimulatedObject", None)
        # Symmetry with remove_markers: some lib builds may expose the raw DLL
        # elsewhere, so fall back to the wrapper's legacy binding. Rebinding
        # argtypes on the raw DLL also mutates the wrapper's aliased attribute
        # (same underlying _FuncPtr) -- harmless, since our struct layout and
        # c_char_p/c_uint32 argtypes are field-compatible with the lib's own.
        if create_legacy is None and dll is not None:
            create_legacy = getattr(dll, "AICreateSimulatedObject", None)
        if create_ex1 is not None:
            try:
                create_ex1.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, _InitPosition, ctypes.c_uint32]
                create_ex1.restype = ctypes.c_long
            except (AttributeError, TypeError):  # pragma: no cover - exotic bindings only
                pass
            creators.append(("SimConnect_AICreateSimulatedObject_EX1", create_ex1))
        if create_legacy is not None:
            try:
                create_legacy.argtypes = [ctypes.c_void_p, ctypes.c_char_p, _InitPosition, ctypes.c_uint32]
                create_legacy.restype = ctypes.c_long
            except (AttributeError, TypeError):  # pragma: no cover - exotic bindings only
                pass
            creators.append(("SimConnect_AICreateSimulatedObject", create_legacy))
    if not creators:
        return {"ok": False, "spawned": 0, "reason": "SimConnect AI object creation not exposed", "markers": []}

    spawned: list[dict[str, Any]] = []
    failures: list[str] = []
    skipped_existing = 0
    # Deduplicate against placements already spawned this session so repeated
    # deploy cycles (auto-deploy + manual refresh) never stack duplicate
    # objects. Key: title + rounded position.
    existing = {
        (str(item.get("title") or ""), round(float(item.get("lat") or 0.0), 6), round(float(item.get("lon") or 0.0), 6))
        for item in _SESSION.spawned()
    }
    for index, marker in enumerate(placements):
        title = str(marker.get("object") or _SIMOBJECT_TITLES.get("runway") or "")
        key = (title, round(float(marker.get("lat") or 0.0), 6), round(float(marker.get("lon") or 0.0), 6))
        if key in existing:
            skipped_existing += 1
            # A manual DEPLOY IN SIM that lands on a marker the auto-deploy loop
            # placed earlier must upgrade that entry to ``manual`` so the radius
            # sweep does not despawn the user's explicit deployment later.
            if source == "manual":
                with _SESSION._lock:
                    for item in _SESSION._spawned:
                        if (
                            str(item.get("title") or "") == title
                            and round(float(item.get("lat") or 0.0), 6) == round(float(marker.get("lat") or 0.0), 6)
                            and round(float(item.get("lon") or 0.0), 6) == round(float(marker.get("lon") or 0.0), 6)
                        ):
                            item["source"] = "manual"
            continue
        existing.add(key)
        request_id = index + 1
        try:
            ok, detail = _ai_create_simobject(sm, creators, title, marker, request_id)
            if ok:
                _SESSION.register_spawn(request_id, title, marker, source=source)
                object_id = _SESSION.capture_object_id(request_id, timeout_seconds=2.0)
                # v0.25.70: GroundVehicle-category markers spawn with the
                # vehicle AI running and "drive away" from the hold-short
                # line (in-sim report at EGKK 26L); SIM DISABLED=1 is the
                # documented park-in-place fix (devsupport #3557/#12106) and
                # keeps the [LIGHTS]/fx animation ticking.
                if object_id and title in _GROUND_VEHICLE_TITLES:
                    hr = _ai_set_sim_disabled(sm, object_id, request_id)
                    if hr != 0:
                        _LOGGER.debug("closure markers: SIM DISABLED %s hr=%s", title, hr)
                spawned.append({"request_id": request_id, "title": title, "airport_icao": marker.get("airport_icao"), "ref": marker.get("ref")})
                # v0.25.66: log the exact coordinates sent to the sim so a
                # misplaced deployment is diagnosable from the log alone.
                _LOGGER.info(
                    "closure markers: spawned %s @ %s %s lat=%.6f lon=%.6f alt=%.0f ft hdg=%.0f (source=%s)",
                    title, marker.get("airport_icao"), marker.get("ref"),
                    float(marker.get("lat") or 0.0), float(marker.get("lon") or 0.0),
                    float(marker.get("altitude_ft") or 0.0), float(marker.get("heading_deg") or 0.0),
                    source,
                )
            else:
                failures.append(f"{title} @ {marker.get('airport_icao')} {marker.get('ref')} ({detail})")
                _LOGGER.warning(
                    "closure markers: spawn FAILED %s @ %s %s lat=%.6f lon=%.6f -> %s",
                    title, marker.get("airport_icao"), marker.get("ref"),
                    float(marker.get("lat") or 0.0), float(marker.get("lon") or 0.0), detail,
                )
        except Exception as exc:  # pragma: no cover - per-marker guard
            _LOGGER.warning("closure markers: spawn %s failed: %s", title, exc)
            failures.append(str(title))
    reason = "ok" if not failures else f"failed: {', '.join(failures[:4])}"
    _LOGGER.info(
        "closure markers: deploy source=%s placements=%d spawned=%d skipped_existing=%d failed=%d",
        source, len(placements), len(spawned), skipped_existing, len(failures),
    )
    return {
        "ok": not failures,
        "spawned": len(spawned),
        "skipped_existing": skipped_existing,
        "reason": reason,
        "markers": spawned,
    }


def remove_markers() -> dict[str, Any]:
    """Remove every SimObject this process spawned via ``SimConnect_AIRemoveObject``.

    Safe no-op when the session never connected (``removed=0``). Returns
    ``ok=True`` with ``removed`` count when all tracked objects were removed,
    ``ok=False`` with a reason when the DLL does not expose the removal
    function or the simulator is not running. Object IDs that were never
    captured (e.g. the sim was not connected at spawn time) are skipped and
    reported.
    """
    if not _is_windows():
        return {"ok": False, "removed": 0, "reason": "SimConnect requires Windows", "remaining": []}
    tracked = _SESSION.spawned()
    if not tracked:
        return {"ok": True, "removed": 0, "reason": "nothing spawned this session", "remaining": []}

    sm = _SESSION.connect()
    if sm is None:
        return {"ok": False, "removed": 0, "reason": _SESSION._error or "SimConnect unavailable", "remaining": tracked}

    dll = getattr(sm, "dll", None)
    raw_dll = getattr(dll, "SimConnect", None) if dll is not None else None
    remove_fn = None
    if raw_dll is not None:
        remove_fn = getattr(raw_dll, "SimConnect_AIRemoveObject", None)
    if remove_fn is None:
        remove_fn = getattr(dll, "AIRemoveObject", None) if dll is not None else None
    if remove_fn is None:
        return {"ok": False, "removed": 0, "reason": "SimConnect_AIRemoveObject not exposed", "remaining": tracked}
    # Rebind with explicit argtypes (same rationale as the spawner): the lib's
    # binding expects a DATA_REQUEST_ID enum in slot 3 and ctypes cannot
    # convert a c_uint32 to it, which made removal fail with ValueError.
    try:
        remove_fn.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
        remove_fn.restype = ctypes.c_long
    except (AttributeError, TypeError):  # pragma: no cover - exotic bindings only
        pass

    removed = 0
    remaining: list[dict[str, Any]] = []
    for item in tracked:
        object_id = item.get("object_id")
        if not object_id:
            remaining.append(item)
            continue
        try:
            result = _ai_remove_object(sm, remove_fn, int(object_id), int(item["request_id"]))
            if result == 0:
                removed += 1
            else:
                remaining.append(item)
        except Exception as exc:  # pragma: no cover - per-object guard
            _LOGGER.warning("closure markers: remove %s failed: %s", item.get("title"), exc)
            remaining.append(item)
    _SESSION.clear_spawned()
    reason = "ok" if not remaining else f"{len(remaining)} not removed"
    _LOGGER.info("closure markers: removed %d simobject(s) (%s)", removed, reason)
    return {"ok": not remaining, "removed": removed, "reason": reason, "remaining": remaining}


def remove_markers_outside_radius(lat: float, lon: float, radius_nm: float) -> dict[str, Any]:
    """Remove only the spawned markers that have left the auto-deploy radius.

    Despawns any tracked SimObject whose recorded position is farther than
    ``radius_nm`` from the given point, keeping everything else in the
    session. Safe no-op when nothing is outside.
    """
    tracked = _SESSION.spawned()
    if not tracked:
        return {"ok": True, "removed": 0, "reason": "nothing spawned this session", "remaining": []}
    # Only auto-deployed markers are subject to the radius despawn. Manual
    # deployments (DEPLOY IN SIM) are explicitly placed by the user and stay
    # until REMOVE / CLEAR ALL is pressed, regardless of the aircraft position.
    outside = [
        item
        for item in tracked
        if str(item.get("source") or "auto") == "auto"
        and _dist_m(float(item.get("lat") or 0.0), float(item.get("lon") or 0.0), float(lat or 0.0), float(lon or 0.0)) / 1852.0 > float(radius_nm or 0.0)
    ]
    if not outside:
        return {"ok": True, "removed": 0, "reason": "nothing outside radius", "remaining": tracked}
    if not _is_windows():
        return {"ok": False, "removed": 0, "reason": "SimConnect requires Windows", "remaining": outside}
    sm = _SESSION.connect()
    if sm is None:
        return {"ok": False, "removed": 0, "reason": _SESSION._error or "SimConnect unavailable", "remaining": outside}
    dll = getattr(sm, "dll", None)
    remove_fn = getattr(dll, "AIRemoveObject", None) if dll is not None else None
    if remove_fn is None:
        remove_fn = getattr(dll, "SimConnect_AIRemoveObject", None) if dll is not None else None
    if remove_fn is None:
        return {"ok": False, "removed": 0, "reason": "SimConnect_AIRemoveObject not exposed", "remaining": outside}
    try:
        remove_fn.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
        remove_fn.restype = ctypes.c_long
    except (AttributeError, TypeError):  # pragma: no cover - exotic bindings only
        pass
    outside_keys = {id(item) for item in outside}
    removed = 0
    remaining_all: list[dict[str, Any]] = []
    for item in tracked:
        if id(item) not in outside_keys:
            remaining_all.append(item)
            continue
        object_id = item.get("object_id")
        if not object_id:
            remaining_all.append(item)
            continue
        try:
            result = _ai_remove_object(sm, remove_fn, int(object_id), int(item["request_id"]))
            if result == 0:
                removed += 1
            else:
                remaining_all.append(item)
        except Exception as exc:  # pragma: no cover - per-object guard
            _LOGGER.warning("closure markers: radius remove %s failed: %s", item.get("title"), exc)
            remaining_all.append(item)
    with _SESSION._lock:
        _SESSION._spawned = remaining_all
    reason = "ok" if removed or not outside else f"{len(outside) - removed} not removed"
    return {"ok": True, "removed": removed, "reason": reason, "remaining": remaining_all}


def auto_deploy_cycle() -> dict[str, Any]:
    """One automatic deployment pass: position -> radius NOTAMs -> plan -> spawn.

    Reads the user aircraft position from the shared SimConnect provider,
    fetches active NOTAMs within the configured radius, plans closures and
    spawns anything new (deduplicated). Skips entirely above the altitude gate
    or when the simulator is not running, and despawns markers whose airport
    has left the radius. Returns a status dict; never raises.
    """
    try:
        from . import notam_client
        from . import simconnect_position

        pos = simconnect_position.read_position(force=False)
        if not isinstance(pos, dict) or not pos.get("ok"):
            return {"ok": True, "action": "no-position", "reason": "simulator position unavailable", "spawned": 0}
        lat = float(pos.get("lat") or 0.0)
        lon = float(pos.get("lon") or 0.0)
        agl = float(pos.get("agl_ft") if pos.get("agl_ft") is not None else pos.get("altitude_ft") or 0.0)
        if agl > marker_altitude_gate_ft():
            return {"ok": True, "action": "above-altitude-gate", "reason": f"AGL {agl:.0f} ft above gate", "spawned": 0}
        radius = marker_radius_nm()
        result = notam_client.get_notams_near(lat, lon, radius)
        rows = result.get("notams") if isinstance(result, dict) else None
        plan = build_marker_plan(rows or [], anchor=(lat, lon))
        placed = _placements_within_radius(plan.get("placed") or [], lat, lon, radius)
        # Despawn markers that left the radius before spawning new ones.
        removed = remove_markers_outside_radius(lat, lon, radius)
        spawn = spawn_markers(placed, enabled=True)
        _LOGGER.info(
            "closure markers: auto-deploy pos %.5f,%.5f agl=%.0f ft radius=%.0f NM "
            "planned=%d spawned=%d skipped=%d removed=%d (%s)",
            lat, lon, agl, radius, len(placed), spawn.get("spawned"),
            spawn.get("skipped_existing"), removed.get("removed"),
            spawn.get("reason") or "ok",
        )
        return {
            "ok": bool(spawn.get("ok") or spawn.get("spawned") == 0),
            "action": "deploy",
            "lat": lat,
            "lon": lon,
            "agl_ft": agl,
            "radius_nm": radius,
            "planned": len(placed),
            "spawned": spawn.get("spawned"),
            "skipped_existing": spawn.get("skipped_existing"),
            "removed": removed.get("removed"),
            "reason": spawn.get("reason") or "ok",
        }
    except Exception as exc:  # pragma: no cover - defensive status path
        _LOGGER.warning("closure markers: auto deploy cycle failed: %s", exc)
        return {"ok": False, "action": "error", "reason": f"{type(exc).__name__}: {exc}", "spawned": 0}


def _placements_within_radius(placements: list[dict[str, Any]], lat: float, lon: float, radius_nm: float) -> list[dict[str, Any]]:
    """Drop placements farther than ``radius_nm`` from the given point.

    v0.25.66: the DEPLOY IN SIM plan used to come straight from the
    flight-route briefing, which also carries closures at the route's
    origin/destination (hundreds of NM apart) - markers ended up "far away
    on the world map" (e.g. EDDF/EDDL closures spawned while the pilot sat
    at EGKK). Every deployment is now radius-filtered around the user
    aircraft so only markers near the pilot are actually spawned.
    """
    out: list[dict[str, Any]] = []
    for p in placements or []:
        plat, plon = p.get("lat"), p.get("lon")
        if plat is None or plon is None:
            # Never coerce missing coordinates to (0,0) - that would spawn
            # markers in the Gulf of Guinea instead of skipping them.
            continue
        d_nm = _dist_m(float(plat), float(plon), float(lat or 0.0), float(lon or 0.0)) / 1852.0
        # Same threshold as remove_markers_outside_radius (despawns > radius)
        # so a marker is never spawned and despawned on alternating cycles.
        if d_nm <= float(radius_nm or 0.0):
            out.append(p)
    return out


def deploy_plan() -> dict[str, Any]:
    """Closure placements for the DEPLOY IN SIM control, anchored to the
    user aircraft.

    Tries position-based NOTAMs first (same source as the auto-deploy loop),
    falling back to the cached route briefing when the simulator has no
    position or the geo query is empty. The result is always radius-filtered
    around the aircraft when a position is available, so route-airport
    closures hundreds of NM away are never spawned. Returns the plan dict
    plus ``_source`` (aircraft-position | route-briefing) and ``_anchor``
    (the aircraft lat/lon used for the filter, when known) so the UI and
    logs can say where a deployment actually went.
    """
    source = "route-briefing"
    anchor_lat = anchor_lon = None
    plan: dict[str, Any] = {}
    try:
        from . import notam_client, simconnect_position

        pos = simconnect_position.read_position(force=False)
        if isinstance(pos, dict) and pos.get("ok"):
            anchor_lat = float(pos.get("lat") or 0.0)
            anchor_lon = float(pos.get("lon") or 0.0)
            radius = marker_radius_nm()
            result = notam_client.get_notams_near(anchor_lat, anchor_lon, radius)
            rows = result.get("notams") if isinstance(result, dict) else None
            if result.get("ok") and rows:
                plan = build_marker_plan(rows, anchor=(anchor_lat, anchor_lon))
                source = "aircraft-position"
    except Exception as exc:  # pragma: no cover - defensive status path
        _LOGGER.debug("closure markers: deploy plan position source failed: %s", exc)
    if anchor_lat is None or anchor_lon is None:
        # v0.25.66: never deploy without an anchor - the route briefing carries
        # origin/destination closures that can be hundreds of NM from where the
        # pilot actually is (the "markers far away on the world map" bug). With
        # no aircraft position there is nothing safe to deploy, so return an
        # empty plan instead of resurrecting far-away route markers.
        plan = {"placed": [], "unplaced": [], "markers": [], "count": 0}
        plan["_source"] = source
        plan["_anchor_lat"] = None
        plan["_anchor_lon"] = None
        plan["_reason"] = "no aircraft position - deployment unanchored (route briefing may be far away)"
        _LOGGER.warning(
            "closure markers: deploy plan unanchored (no sim position); "
            "refusing to spawn far-away route markers"
        )
        return plan
    if not plan.get("placed"):
        plan = build_marker_plan()
    placed = _placements_within_radius(plan.get("placed") or [], anchor_lat, anchor_lon, marker_radius_nm())
    plan["placed"] = placed
    plan["count"] = len(placed)
    plan["_source"] = source
    plan["_anchor_lat"] = anchor_lat
    plan["_anchor_lon"] = anchor_lon
    return plan


def _ai_remove_object(sm: Any, remove_fn: Any, object_id: int, request_id: int) -> int:
    """Low-level ``SimConnect_AIRemoveObject`` call (returns HRESULT).

    The handle is passed BY VALUE (HANDLE/c_void_p), exactly like the native
    bridge's proven in-sim AI-object removal path. ``byref`` would hand the
    DLL a pointer-to-handle where it expects the handle itself.
    """
    return remove_fn(
        sm.hSimConnect,
        ctypes.c_uint32(object_id),
        ctypes.c_uint32(request_id),
    )


#: GroundVehicle-category SimObject titles that spawn with the vehicle AI
#: running. Without waypoints the AI follows the sim's internal world paths
#: and the objects "drive away" from their hold-short position (in-sim
#: report at EGKK 26L, v0.25.70). SIM DISABLED=1 is the documented
#: park-in-place workaround (MSFS devsupport #3557 / #12106) and keeps the
#: [LIGHTS] + fx animation ticking because the vehicle stays rendered.
_GROUND_VEHICLE_TITLES = frozenset(
    {
        SIMOBJECT_TITLE_X_TRAILER,
        SIMOBJECT_TITLE_BARRICADE_T3_ORANGE,
        SIMOBJECT_TITLE_BARRICADE_T3_WHITE,
    }
)

#: SIMCONNECT_DATATYPE_INT32 -- boolean SimVars are written as a 32-bit int.
_SIMCONNECT_DATATYPE_INT32 = 1
#: Client-side data definition ID for the SIM DISABLED SimVar (arbitrary
#: value outside the python SimConnect lib's own definition-ID range).
_SIM_DISABLED_DEFINITION_ID = 0x00007FF1


def _ai_set_sim_disabled(sm: Any, object_id: int, request_id: int) -> int:
    """Write SIM DISABLED=1 on a spawned GroundVehicle so it parks in place.

    MSFS devsupport #3557 / #12106: AI ground vehicles created via
    ``SimConnect_AICreateSimulatedObject`` start with the vehicle AI running
    and, without waypoints, follow the sim's internal world paths and drive
    away from the spawn point. Setting the SIM DISABLED SimVar to 1 turns off
    the object's internal simulation (the documented "park them so they do
    not roll around the airport" workaround) while the object stays rendered
    and its [LIGHTS]/fx system keeps running. Returns the HRESULT of the
    write (0 = ok), or a negative sentinel when the DLL does not expose the
    calls.
    """
    raw_dll = getattr(getattr(sm, "dll", None), "SimConnect", None)
    if raw_dll is None:
        return -1
    add_def = getattr(raw_dll, "SimConnect_AddToDataDefinition", None)
    set_data = getattr(raw_dll, "SimConnect_SetDataOnSimObject", None)
    if add_def is None or set_data is None:
        return -2
    try:
        add_def.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_float, ctypes.c_uint32]
        add_def.restype = ctypes.c_long
        set_data.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        set_data.restype = ctypes.c_long
        # DatumID = SIMCONNECT_UNUSED (0xFFFFFFFF) -- no per-datum ID needed.
        add_def(
            sm.hSimConnect,
            ctypes.c_uint32(_SIM_DISABLED_DEFINITION_ID),
            ctypes.c_char_p(b"SIM DISABLED"),
            ctypes.c_char_p(b"Bool"),
            ctypes.c_int(_SIMCONNECT_DATATYPE_INT32),
            ctypes.c_float(0.0),
            ctypes.c_uint32(0xFFFFFFFF),
        )
        value = ctypes.c_int32(1)
        return int(
            set_data(
                sm.hSimConnect,
                ctypes.c_uint32(object_id),
                ctypes.c_uint32(_SIM_DISABLED_DEFINITION_ID),
                ctypes.c_uint32(0),  # SIMCONNECT_DATA_SET_FLAG_DEFAULT
                ctypes.c_uint32(0),  # Reserved
                ctypes.c_uint32(ctypes.sizeof(value)),
                ctypes.byref(value),
            )
        )
    except Exception as exc:  # pragma: no cover - defensive
        _LOGGER.debug("closure markers: SIM DISABLED write failed: %s", exc)
        return -3


def _is_windows() -> bool:
    try:
        import platform

        return platform.system() == "Windows"
    except Exception:  # pragma: no cover
        return False


def _ai_create_simobject(sm: Any, creators: list[tuple[str, Any]], title: str, marker: dict[str, Any], request_id: int) -> tuple[bool, str]:
    """Low-level SimObject creation call with an init position.

    Tries ``SimConnect_AICreateSimulatedObject_EX1`` (5-arg, empty livery)
    first -- the proven in-sim path on MSFS 2024 -- then falls back to the
    legacy 4-arg ``SimConnect_AICreateSimulatedObject``. Returns
    ``(ok, detail)`` where detail carries the HRESULT of the last attempt so
    failures are diagnosable instead of a bare "failed".
    """
    position = _InitPosition(
        Latitude=float(marker.get("lat") or 0.0),
        Longitude=float(marker.get("lon") or 0.0),
        Altitude=float(marker.get("altitude_ft") or 0.0),
        Pitch=0.0,
        Bank=0.0,
        Heading=float(marker.get("heading_deg") or 0.0),
        OnGround=1,
        Airspeed=0,
    )
    title_bytes = title.encode("utf-8")
    last_detail = "no creator available"
    for method, create in creators:
        try:
            if method.endswith("_EX1"):
                result = create(
                    sm.hSimConnect,
                    ctypes.c_char_p(title_bytes),
                    ctypes.c_char_p(b""),  # empty livery -- same as the bridge
                    position,
                    ctypes.c_uint32(request_id),
                )
            else:
                result = create(
                    sm.hSimConnect,
                    ctypes.c_char_p(title_bytes),
                    position,
                    ctypes.c_uint32(request_id),
                )
        except Exception as exc:  # pragma: no cover - per-marker guard
            last_detail = f"{method} exception: {type(exc).__name__}: {exc}"
            continue
        last_detail = f"{method} HRESULT {int(result)}"
        if int(result) == 0:
            return True, last_detail
    return False, last_detail


# ── v0.25.65: closure proximity alerting ───────────────────────────────────
# The frontend polls this lightweight helper (no network, no SimConnect
# spawns) and shows an amber/red pop-up when the aircraft is near a closed
# runway threshold, taxiway or barrier line. Pure distance math over the
# already-cached plan; never raises.

#: Proximity radii for the pop-up (NM). Runway closure markers are the
#: largest footprint, taxiway/barrier markers tighter.
_PROX_RUNWAY_NM = 2.5
_PROX_TAXIWAY_NM = 1.0

#: The frontend polls every ~5s; the plan (navdata SQLite lookups) only needs
#: to rebuild at the same cadence as the auto-deploy loop (30s).
_PROX_PLAN_TTL = 30.0
_PROX_PLAN_CACHE: dict[str, Any] = {"at": 0.0, "placed": []}


def _prox_placed() -> list[dict[str, Any]]:
    import time as _time

    now = _time.time()
    if now - float(_PROX_PLAN_CACHE.get("at") or 0.0) <= _PROX_PLAN_TTL:
        return _PROX_PLAN_CACHE.get("placed") or []
    plan = build_marker_plan()
    placed = plan.get("placed") or []
    # v0.25.72 (#17): thread the closure NOTAM identity onto each placement so
    # the proximity pop-up can key on the closure, not the nearest marker — a
    # single closed taxiway yields several markers (geometry X + junction Xs),
    # and the nearest one changes while taxiing.
    markers = plan.get("markers") or []
    by_ref = {
        (str(m.get("airport_icao") or "").upper(), str(m.get("kind") or ""), str(m.get("ref") or "")): str(m.get("notam_id") or "").strip()
        for m in markers
    }
    for row in placed:
        key = (str(row.get("airport_icao") or "").upper(), str(row.get("kind") or ""), str(row.get("ref") or ""))
        nid = by_ref.get(key)
        if nid:
            row["notam_id"] = nid
    _PROX_PLAN_CACHE.update({"at": now, "placed": placed})
    return placed


def proximity_alert(lat: float | None = None, lon: float | None = None) -> dict[str, Any]:
    """Nearest closed runway/taxiway/barrier to a position, for alerting.

    Accepts explicit coordinates or falls back to the live SimConnect
    position. Returns the closest placement within its kind alert radius with
    distance, kind and identity; ``near=False`` when nothing is close. Skips
    when the NOTAM proximity pop-up channel is disabled in settings.
    """
    try:
        from . import simconnect_position

        if lat is None or lon is None:
            pos = simconnect_position.read_position(force=False)
            if not isinstance(pos, dict) or not pos.get("ok"):
                return {"ok": True, "near": False, "reason": "simulator position unavailable"}
            lat = float(pos.get("lat") or 0.0)
            lon = float(pos.get("lon") or 0.0)
        try:
            from .settings_store import load_settings

            integrations = load_settings().get("integrations", {}) or {}
            if not bool(integrations.get("notam_notifications", True)):
                return {"ok": True, "near": False, "reason": "notam notifications disabled"}
        except Exception:
            pass
        best: dict[str, Any] | None = None
        for item in _prox_placed():
            kind = str(item.get("kind") or "")
            ilat = item.get("lat")
            ilon = item.get("lon")
            if ilat is None or ilon is None:
                continue
            distance = _dist_m(float(lat), float(lon), float(ilat), float(ilon)) / 1852.0
            # Barriers are runway hold-short lines -> runway alert radius.
            limit = _PROX_RUNWAY_NM if kind in ("runway", "barrier") else _PROX_TAXIWAY_NM
            if distance > limit:
                continue
            if best is None or distance < best.get("distance_nm", 1e9):
                # v0.25.72 (#17): stable closure identity — the NOTAM id when
                # available, else the normalized airport:kind:ref. The pop-up
                # dedups on this, so markers of the same closure share one key.
                closure_id = str(item.get("notam_id") or "").strip()
                if not closure_id:
                    closure_id = f"{str(item.get('airport_icao') or '').upper()}:{kind}:{str(item.get('ref') or '')}"
                best = {
                    "distance_nm": round(distance, 2),
                    "kind": kind,
                    "ref": str(item.get("ref") or ""),
                    "airport_icao": str(item.get("airport_icao") or ""),
                    "closure_id": closure_id,
                    "lat": ilat,
                    "lon": ilon,
                }
        if not best:
            return {"ok": True, "near": False, "reason": "no closure within alert radius"}
        return {"ok": True, "near": True, **best}
    except Exception as exc:  # pragma: no cover - defensive status path
        _LOGGER.warning("closure markers: proximity alert failed: %s", exc)
        return {"ok": False, "near": False, "reason": f"{type(exc).__name__}: {exc}"}
