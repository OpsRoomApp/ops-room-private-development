from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import re
from typing import Any

from .data_loader import airport_to_dict, haversine_nm, load_airports, match_airline, nearest_stand, nearest_stands, stands_available, stand_count, stand_sources_status
from .weather_client import analyze_atis_text

MAX_UPCOMING_DEPARTURES = 15
MAX_DEPARTED = 5
MAX_UPCOMING_ARRIVALS = 15
MAX_LANDED = 5
MAX_PREFILES = 30
WINDOW_NEXT_MIN = 120
WINDOW_PREV_MIN = 60


def _flightplan(client: dict[str, Any]) -> dict[str, Any] | None:
    fp = client.get("flight_plan")
    return fp if isinstance(fp, dict) else None


def _aircraft_short(fp: dict[str, Any] | None) -> str:
    if not fp:
        return ""
    return fp.get("aircraft_short") or _parse_aircraft(fp.get("aircraft") or "")


def _parse_aircraft(raw: str) -> str:
    if not raw:
        return ""
    first = raw.split("/", 1)[0].strip()
    return first[-4:] if len(first) > 4 else first




def _route_tokens(route: str) -> list[str]:
    tokens = []
    for token in re.split(r"\s+", route or ""):
        token = token.strip().upper().strip(",.;")
        if not token or token in {"DCT", "DIRECT", "SID", "STAR"}:
            continue
        # Strip speed/level suffixes like REGHI/M085F380.
        token = token.split("/", 1)[0]
        if re.fullmatch(r"[A-Z0-9]{2,10}", token):
            tokens.append(token)
    return tokens


def _procedure_hint(route: str, kind: str) -> str:
    tokens = _route_tokens(route)
    if not tokens:
        return "---"
    if kind == "departure":
        return tokens[0]
    return tokens[-1]


def _distance_to_airport(client: dict[str, Any], airport_ident: str) -> float | None:
    airports = load_airports()
    airport = airports.get(airport_ident.upper())
    if not airport:
        return None
    lat = client.get("latitude")
    lon = client.get("longitude")
    if lat is None or lon is None:
        return None
    try:
        return haversine_nm(float(lat), float(lon), airport.lat, airport.lon)
    except (TypeError, ValueError):
        return None


def _stand_candidates(client: dict[str, Any], airport_ident: str, exclude: set[str] | None = None) -> list[tuple[str, float]]:
    lat = client.get("latitude")
    lon = client.get("longitude")
    if lat is None or lon is None:
        return []
    try:
        gs = float(client.get("groundspeed") or 0)
        alt = float(client.get("altitude") or 0)
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return []
    # Only estimate a stand when the aircraft is very slow/on the ground.
    if gs > 18 or alt > 3000:
        return []
    hits = nearest_stands(airport_ident, lat_f, lon_f, max_distance_nm=0.12, limit=20, exclude=exclude)
    return [(stand.name, dist) for stand, dist in hits]


def _stand_estimate(client: dict[str, Any], airport_ident: str) -> str | None:
    hits = _stand_candidates(client, airport_ident)
    return hits[0][0] if hits else None


def _eta_minutes(distance_nm: float | None, groundspeed: Any) -> int | None:
    if distance_nm is None:
        return None
    try:
        gs = float(groundspeed or 0)
    except (TypeError, ValueError):
        return None
    if gs < 60:
        return None
    return max(0, int(round(distance_nm / gs * 60)))


def _hhmm_to_minutes(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text or len(text) < 3:
        return None
    text = text.zfill(4)[-4:]
    try:
        hh = int(text[:2])
        mm = int(text[2:])
    except ValueError:
        return None
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return hh * 60 + mm


def _relative_minutes_from_now(hhmm: Any, now: datetime | None = None) -> int | None:
    dep_min = _hhmm_to_minutes(hhmm)
    if dep_min is None:
        return None
    now = now or datetime.now(timezone.utc)
    now_min = now.hour * 60 + now.minute
    diff = dep_min - now_min
    # Choose the nearest UTC day. This handles midnight wrap, e.g. 2355 -> 0005.
    if diff < -720:
        diff += 1440
    elif diff > 720:
        diff -= 1440
    return diff


def departure_status(client: dict[str, Any], airport: str, is_prefile: bool) -> str:
    if is_prefile:
        return "Prefiled"
    dist = _distance_to_airport(client, airport)
    try:
        gs = float(client.get("groundspeed") or 0)
        alt = float(client.get("altitude") or 0)
        vs = float(client.get("vertical_speed") or 0)
    except (TypeError, ValueError):
        gs, alt, vs = 0.0, 0.0, 0.0

    if dist is not None and dist <= 3 and alt < 3000:
        if gs <= 2:
            return "Boarding"
        if gs <= 9:
            return "Pushback"
        if gs < 48:
            return "Taxi out"
    # VATSIM position updates are not frame-perfect, so detect the takeoff roll early.
    if dist is not None and dist <= 8 and alt < 1800 and gs >= 48:
        return "Takeoff"
    if dist is not None and dist <= 18 and (alt < 8000 or vs > 400):
        return "Climb"
    if dist is not None and dist <= 35 and alt < 15000:
        return "Departed"
    return "Enroute"


def arrival_status(client: dict[str, Any], airport: str, is_prefile: bool) -> str:
    if is_prefile:
        return "Prefiled"
    dist = _distance_to_airport(client, airport)
    try:
        gs = float(client.get("groundspeed") or 0)
        alt = float(client.get("altitude") or 0)
        vs = float(client.get("vertical_speed") or 0)
    except (TypeError, ValueError):
        gs, alt, vs = 0.0, 0.0, 0.0
    if dist is None:
        return "Enroute"
    # A connected arrival that has parked at the destination remains visible as deboarding.
    if dist <= 3 and gs <= 2 and alt < 3000:
        return "Deboarding"
    if dist <= 4 and 2 < gs <= 35 and alt < 3000:
        return "Taxi in"
    if dist <= 5 and gs > 35 and alt < 1200:
        return "Rollout"
    if dist <= 10 and alt < 3500:
        return "Final"
    if dist <= 40:
        return "Approach"
    if dist <= 140:
        return "Descending" if (alt < 22000 or vs < -300) else "Enroute"
    return "Enroute"


def _build_row(client: dict[str, Any], airport: str, kind: str, is_prefile: bool, now: datetime | None = None, user_cid: str = "", user_callsign: str = "") -> dict[str, Any]:
    fp = _flightplan(client) or {}
    callsign = (client.get("callsign") or "").upper()
    dist = None if is_prefile else _distance_to_airport(client, airport)
    status = departure_status(client, airport, is_prefile) if kind == "departure" else arrival_status(client, airport, is_prefile)
    airline = match_airline(callsign)
    deptime = fp.get("deptime") or ""
    rel = _relative_minutes_from_now(deptime, now)
    eta = None if kind == "departure" else _eta_minutes(dist, client.get("groundspeed"))
    return {
        "callsign": callsign,
        "cid": str(client.get("cid") or ""),
        "is_user": bool((user_cid and str(client.get("cid") or "") == str(user_cid)) or (user_callsign and callsign == str(user_callsign).upper())),
        "airline": airline,
        "aircraft": _aircraft_short(fp),
        "departure": (fp.get("departure") or "").upper(),
        "arrival": (fp.get("arrival") or "").upper(),
        "alternate": (fp.get("alternate") or "").upper(),
        "deptime": deptime,
        "deptime_relative_min": rel,
        # Positive means the current UTC time is after the filed departure
        # time (delayed); negative means it is before it (early).
        "schedule_delta_min": None if rel is None else -int(rel),
        "enroute_time": fp.get("enroute_time") or "",
        "route": fp.get("route") or "",
        "procedure": _procedure_hint(fp.get("route") or "", kind),
        "remarks": fp.get("remarks") or "",
        "status": status,
        "stand": None if is_prefile else _stand_estimate(client, airport),
        "latitude": client.get("latitude"),
        "longitude": client.get("longitude"),
        "prefile": is_prefile,
        "direction": kind,
        "distance_nm": round(dist, 1) if dist is not None else None,
        "eta_min": eta,
        "altitude": client.get("altitude"),
        "groundspeed": client.get("groundspeed"),
        "heading": client.get("heading"),
        "last_updated": client.get("last_updated"),
    }


def _is_departed(row: dict[str, Any]) -> bool:
    return str(row.get("status") or "").lower() in {"departed", "airborne", "enroute"}


def _sort_deptime(row: dict[str, Any]) -> int:
    rel = row.get("deptime_relative_min")
    return 9999 if rel is None else int(rel)


def _assign_unique_stands(rows: list[dict[str, Any]], airport_ident: str) -> None:
    """Assign stands without repeating the same gate number on one board.

    VATSIM aircraft positions and scenery stand coordinates are approximate.
    With a wide stand-matching tolerance, several parked aircraft can otherwise
    snap to the same nearest stand. This routine assigns nearest unused stands
    to the slowest/closest aircraft first and leaves the field blank if it cannot
    find a plausible unique match.
    """
    used: set[str] = set()
    candidates: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        try:
            lat = float(row.get("latitude"))
            lon = float(row.get("longitude"))
            gs = float(row.get("groundspeed") or 0)
            alt = float(row.get("altitude") or 0)
        except (TypeError, ValueError):
            row["stand"] = None
            continue
        if gs > 18 or alt > 3000:
            row["stand"] = None
            continue
        hits = nearest_stands(airport_ident, lat, lon, max_distance_nm=0.12, limit=20)
        if not hits:
            row["stand"] = None
            continue
        row["_stand_hits"] = [(s.name, d) for s, d in hits]
        candidates.append((hits[0][1], row))

    candidates.sort(key=lambda item: item[0])
    for _dist, row in candidates:
        assigned = None
        for name, dist in row.get("_stand_hits") or []:
            if name not in used:
                assigned = name
                used.add(name)
                row["stand_distance_nm"] = round(float(dist), 4)
                break
        if assigned is None:
            hits = row.get("_stand_hits") or []
            if hits:
                assigned = hits[0][0]
        row["stand"] = assigned
        row.pop("_stand_hits", None)


def _select_departures(rows: list[dict[str, Any]], upcoming_minutes: int, previous_minutes: int) -> list[dict[str, Any]]:
    upcoming: list[dict[str, Any]] = []
    departed: list[dict[str, Any]] = []
    for row in rows:
        rel = row.get("deptime_relative_min")
        if _is_departed(row):
            # Keep only recent departed traffic, and cap it.
            if rel is None or -previous_minutes <= int(rel) <= 15:
                departed.append(row)
        else:
            # Next 2 hours, but keep already-at-gate/taxi flights even if the filed time is a little old.
            if rel is None or -30 <= int(rel) <= upcoming_minutes:
                upcoming.append(row)
    departed.sort(key=lambda r: (not bool(r.get("is_user")), _sort_deptime(r), r.get("callsign") or ""))
    upcoming.sort(key=lambda r: (not bool(r.get("is_user")), _sort_deptime(r), r.get("callsign") or ""))
    # Real boards prioritize upcoming scheduled rows; recent departed are retained below them.
    return upcoming[:MAX_UPCOMING_DEPARTURES] + departed[-MAX_DEPARTED:]


def _select_arrivals(rows: list[dict[str, Any]], upcoming_minutes: int) -> list[dict[str, Any]]:
    upcoming: list[dict[str, Any]] = []
    landed: list[dict[str, Any]] = []
    for row in rows:
        status = str(row.get("status") or "").lower()
        eta = row.get("eta_min")
        if status in {"deboarding", "parked", "taxi in", "taxi-in", "rollout", "landed"}:
            landed.append(row)
        elif eta is not None and 0 <= int(eta) <= upcoming_minutes:
            upcoming.append(row)
        elif status in {"final", "approach", "descending"}:
            upcoming.append(row)
    landed.sort(key=lambda r: (not bool(r.get("is_user")), r.get("distance_nm") or 9999, r.get("callsign") or ""))
    upcoming.sort(key=lambda r: (not bool(r.get("is_user")), r.get("eta_min") is None, r.get("eta_min") or 9999, r.get("distance_nm") or 9999))
    return landed[:MAX_LANDED] + upcoming[:MAX_UPCOMING_ARRIVALS]


def _select_prefiles(rows: list[dict[str, Any]], upcoming_minutes: int) -> list[dict[str, Any]]:
    selected = []
    for row in rows:
        rel = row.get("deptime_relative_min")
        if rel is None or -30 <= int(rel) <= upcoming_minutes:
            selected.append(row)
    selected.sort(key=lambda r: (not bool(r.get("is_user")), _sort_deptime(r), r.get("callsign") or ""))
    return selected[:MAX_PREFILES]


def airport_traffic_counts(data: dict[str, Any]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for collection in (data.get("pilots", []) or [], data.get("prefiles", []) or []):
        for client in collection if isinstance(collection, list) else []:
            fp = _flightplan(client)
            if not fp:
                continue
            dep = (fp.get("departure") or "").upper()
            arr = (fp.get("arrival") or "").upper()
            if dep:
                counts[dep] += 1
            if arr:
                counts[arr] += 1
    return counts


def busiest_airports(data: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    airports = load_airports()
    counts = airport_traffic_counts(data)
    rows = []
    for ident, count in counts.items():
        airport = airports.get(ident)
        if airport:
            rows.append((count, airport))
    rows.sort(key=lambda item: (-item[0], item[1].ident))
    # Import locally to avoid circular import.
    from .data_loader import airport_option
    return [airport_option(ap, source="busy", traffic_count=count) for count, ap in rows[:limit]]


def build_board(data: dict[str, Any], airport_ident: str, upcoming_minutes: int = WINDOW_NEXT_MIN, previous_minutes: int = WINDOW_PREV_MIN, user_cid: str = "", user_callsign: str = "") -> dict[str, Any]:
    airport_ident = airport_ident.strip().upper()
    upcoming_minutes = max(30, min(int(upcoming_minutes), 720))
    previous_minutes = max(0, min(int(previous_minutes), 240))
    airports = load_airports()
    airport = airports.get(airport_ident)
    if not airport:
        raise ValueError(f"Unknown airport ICAO: {airport_ident}")

    now = datetime.now(timezone.utc)
    raw_departures: list[dict[str, Any]] = []
    raw_arrivals: list[dict[str, Any]] = []
    prefiles: list[dict[str, Any]] = []

    online_callsigns: set[str] = set()
    for pilot in data.get("pilots", []) or []:
        fp = _flightplan(pilot)
        if not fp:
            continue
        callsign = (pilot.get("callsign") or "").upper()
        online_callsigns.add(callsign)
        dep = (fp.get("departure") or "").upper()
        arr = (fp.get("arrival") or "").upper()
        if dep == airport_ident:
            raw_departures.append(_build_row(pilot, airport_ident, "departure", False, now, user_cid, user_callsign))
        if arr == airport_ident:
            raw_arrivals.append(_build_row(pilot, airport_ident, "arrival", False, now, user_cid, user_callsign))

    for prefile in data.get("prefiles", []) or []:
        fp = _flightplan(prefile)
        if not fp:
            continue
        callsign = (prefile.get("callsign") or "").upper()
        if callsign in online_callsigns:
            continue
        dep = (fp.get("departure") or "").upper()
        arr = (fp.get("arrival") or "").upper()
        if dep == airport_ident:
            prefiles.append(_build_row(prefile, airport_ident, "departure", True, now, user_cid, user_callsign))
        elif arr == airport_ident:
            prefiles.append(_build_row(prefile, airport_ident, "arrival", True, now, user_cid, user_callsign))

    controllers = []
    for c in data.get("controllers", []) or []:
        callsign = (c.get("callsign") or "").upper()
        if callsign.startswith(airport_ident + "_") or callsign == airport_ident:
            controllers.append({
                "callsign": callsign,
                "frequency": c.get("frequency"),
                "facility": c.get("facility"),
                "visual_range": c.get("visual_range"),
                "text_atis": c.get("text_atis") or [],
                "analysis": analyze_atis_text(" ".join(c.get("text_atis") or [])),
            })

    atis = []
    for a in data.get("atis", []) or []:
        callsign = (a.get("callsign") or "").upper()
        if callsign.startswith(airport_ident + "_"):
            atis.append({
                "callsign": callsign,
                "frequency": a.get("frequency"),
                "atis_code": a.get("atis_code"),
                "text_atis": a.get("text_atis") or [],
                "analysis": analyze_atis_text(" ".join(a.get("text_atis") or [])),
            })

    _assign_unique_stands(raw_departures, airport_ident)
    _assign_unique_stands(raw_arrivals, airport_ident)

    departures = _select_departures(raw_departures, upcoming_minutes, previous_minutes)
    arrivals = _select_arrivals(raw_arrivals, upcoming_minutes)
    selected_prefiles = _select_prefiles(prefiles, upcoming_minutes)

    return {
        "airport": airport_to_dict(airport),
        "update_timestamp": (data.get("general") or {}).get("update_timestamp"),
        "cache": data.get("_cache", {}),
        "features": {
            "stands_available": stands_available(),
            "stand_count": stand_count(),
            "stand_sources": stand_sources_status(),
        },
        "windows": {
            "upcoming_minutes": upcoming_minutes,
            "previous_minutes": previous_minutes,
            "max_upcoming_departures": MAX_UPCOMING_DEPARTURES,
            "max_departed": MAX_DEPARTED,
            "max_upcoming_arrivals": MAX_UPCOMING_ARRIVALS,
            "max_landed": MAX_LANDED,
        },
        "counts": {
            "departures": len(departures),
            "arrivals": len(arrivals),
            "prefiles": len(selected_prefiles),
            "controllers": len(controllers),
            "atis": len(atis),
            "raw_departures": len(raw_departures),
            "raw_arrivals": len(raw_arrivals),
            "raw_prefiles": len(prefiles),
        },
        "departures": departures,
        "arrivals": arrivals,
        "prefiles": selected_prefiles,
        "controllers": controllers,
        "atis": atis,
    }
