from __future__ import annotations

from datetime import datetime, timezone
import re
import time
from typing import Any

from .data_loader import haversine_nm, load_airports, match_airline, nearest_airports
from .settings_store import load_settings
from .simbrief_client import cached_plan
from .telemetry_provider import read_telemetry
from .vatspy_boundaries import find_boundary, centroid as boundary_centroid, status as boundary_status
from .vatsim_client import get_vatsim_data
from .weather_client import fetch_metar
from .charts import openaip_key


_OPENAIP_RUNTIME_CACHE: dict[str, Any] = {}


def _openaip_runtime() -> dict[str, Any]:
    """Live OpenAIP enrichment runtime status; additive and never fatal.

    Memoized for a short window so the 2.5s map stream does not re-read the
    settings file on every tick.
    """
    now = time.monotonic()
    if now - float(_OPENAIP_RUNTIME_CACHE.get("at") or 0) < 10.0:
        return _OPENAIP_RUNTIME_CACHE.get("value") or {"healthy": None, "active": False, "counters": {}}
    try:
        from .openaip_client import status as openaip_status
        value = openaip_status()
    except Exception:
        value = {"healthy": None, "active": False, "counters": {}}
    _OPENAIP_RUNTIME_CACHE["value"] = value
    _OPENAIP_RUNTIME_CACHE["at"] = now
    return value


FACILITY_NAMES = {
    0: "UNKNOWN",
    1: "OBSERVER",
    2: "FSS",
    3: "DELIVERY",
    4: "GROUND",
    5: "TOWER",
    6: "APPROACH",
    7: "CENTRE",
}


def _coverage_nm(facility: int, visual_range: Any) -> float:
    supplied = _num(visual_range)
    defaults = {1: 0.0, 2: 350.0, 3: 8.0, 4: 10.0, 5: 30.0, 6: 90.0, 7: 300.0}
    value = supplied if supplied and supplied > 0 else defaults.get(facility, 40.0)
    return max(4.0, min(float(value), 600.0))


def _num(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _clean_point(lat: Any, lon: Any) -> tuple[float, float] | None:
    y, x = _num(lat), _num(lon)
    if y is None or x is None or not (-90 <= y <= 90) or not (-180 <= x <= 180):
        return None
    return y, x


def _flight_plan() -> dict[str, Any] | None:
    settings = load_settings()
    user = str(settings.get("identity", {}).get("simbrief_user_id") or "")
    return cached_plan(user) if user else None


def _route_points(plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not plan:
        return []
    result: list[dict[str, Any]] = []
    for item in plan.get("navlog") or []:
        if not isinstance(item, dict):
            continue
        point = _clean_point(item.get("latitude"), item.get("longitude"))
        if not point:
            continue
        result.append({
            "ident": str(item.get("ident") or "").upper(),
            "name": str(item.get("name") or ""),
            "type": str(item.get("type") or ""),
            "lat": point[0],
            "lon": point[1],
            "altitude_ft": _num(item.get("altitude_ft")),
        })
    if result:
        return result
    for key in ("origin", "destination"):
        airport = plan.get(key) or {}
        point = _clean_point(airport.get("latitude"), airport.get("longitude"))
        if point:
            result.append({"ident": airport.get("icao") or key.upper(), "name": airport.get("name") or "", "type": key, "lat": point[0], "lon": point[1]})
    return result


def _pilot_row(row: dict[str, Any], own_cid: str, own_position: dict[str, Any] | None) -> dict[str, Any] | None:
    point = _clean_point(row.get("latitude"), row.get("longitude"))
    if not point:
        return None
    fp = row.get("flight_plan") if isinstance(row.get("flight_plan"), dict) else {}
    distance = None
    if own_position and own_position.get("ok"):
        distance = haversine_nm(float(own_position["lat"]), float(own_position["lon"]), point[0], point[1])
    return {
        "callsign": str(row.get("callsign") or "").upper(),
        "airline": match_airline(str(row.get("callsign") or "")),
        "cid": str(row.get("cid") or ""),
        "lat": point[0],
        "lon": point[1],
        "altitude_ft": _num(row.get("altitude")),
        "groundspeed_kts": _num(row.get("groundspeed")),
        "heading_deg": _num(row.get("heading")),
        "aircraft": str(fp.get("aircraft_short") or fp.get("aircraft_faa") or ""),
        "origin": str(fp.get("departure") or "").upper(),
        "destination": str(fp.get("arrival") or "").upper(),
        "distance_nm": round(distance, 1) if distance is not None else None,
        "own": bool(own_cid and str(row.get("cid") or "") == own_cid),
    }


def build_live_map(force: bool = False, traffic_limit: int = 900) -> dict[str, Any]:
    settings = load_settings()
    own_cid = str(settings.get("identity", {}).get("vatsim_cid") or "")
    position = read_telemetry(force=False)
    plan = _flight_plan()
    data = get_vatsim_data(force=force)

    pilots: list[dict[str, Any]] = []
    for row in data.get("pilots") or []:
        if not isinstance(row, dict):
            continue
        item = _pilot_row(row, own_cid, position)
        if item:
            pilots.append(item)
    pilots.sort(key=lambda x: (not x.get("own"), x.get("distance_nm") is None, x.get("distance_nm") or 999999))
    pilots = pilots[: max(50, min(int(traffic_limit), 1600))]

    airport_db = load_airports()
    atis_rows = [row for row in (data.get("atis") or []) if isinstance(row, dict)]

    def airport_point_for_callsign(callsign: str) -> tuple[float, float, str] | None:
        parts = [part for part in callsign.upper().split("_") if part]
        candidates = []
        if parts:
            candidates.extend([parts[0], re.sub(r"[^A-Z0-9]", "", parts[0])])
        compact = re.sub(r"[^A-Z0-9]", "", callsign.upper())
        if len(compact) >= 4:
            candidates.append(compact[:4])
        for candidate in candidates:
            airport = airport_db.get(candidate)
            if airport:
                return airport.lat, airport.lon, airport.ident
        # VATSIM ATIS records include coordinates and normally share the airport
        # prefix even though controller records themselves have no position.
        prefix = parts[0] if parts else ""
        for atis in atis_rows:
            atis_call = str(atis.get("callsign") or "").upper()
            if prefix and atis_call.startswith(prefix):
                point = _clean_point(atis.get("latitude"), atis.get("longitude"))
                if point:
                    return point[0], point[1], prefix
        return None

    controllers: list[dict[str, Any]] = []
    for row in data.get("controllers") or []:
        if not isinstance(row, dict):
            continue
        callsign = str(row.get("callsign") or "").upper()
        facility = int(row.get("facility") or 0)
        text_atis = row.get("text_atis") if isinstance(row.get("text_atis"), list) else []
        point = _clean_point(row.get("latitude"), row.get("longitude"))
        coverage_geojson = None
        position_source = "vatsim"
        airport_code = None

        if not point or (abs(point[0]) < 0.01 and abs(point[1]) < 0.01):
            resolved = airport_point_for_callsign(callsign)
            if resolved:
                point = (resolved[0], resolved[1])
                airport_code = resolved[2]
                position_source = "airport"

        if facility in {2, 7} or callsign.endswith(("_CTR", "_FSS")):
            boundary = find_boundary(callsign)
            if boundary:
                coverage_geojson = boundary.get("geometry")
                centre = boundary_centroid(coverage_geojson or {})
                if centre:
                    point = centre
                    position_source = "vatspy-boundary"

        item = {
            "callsign": callsign,
            "frequency": str(row.get("frequency") or ""),
            "facility": facility,
            "facility_label": FACILITY_NAMES.get(facility, "ATC"),
            "visual_range_nm": _num(row.get("visual_range")),
            "coverage_nm": round(_coverage_nm(facility, row.get("visual_range")), 1),
            "lat": point[0] if point else None,
            "lon": point[1] if point else None,
            "mapped": bool(point),
            "position_source": position_source if point else "unresolved",
            "airport": airport_code,
            "coverage_geojson": coverage_geojson,
            "coverage_kind": "VATSPY SECTOR" if coverage_geojson else "ESTIMATED RANGE",
            "atis": " ".join(str(line) for line in text_atis if line)[:800],
        }
        # Never discard an online controller: unmapped positions remain visible
        # in the controller list and can resolve on the next VATSpy cache update.
        controllers.append(item)

    airport_codes: list[str] = []
    for key in ("origin", "destination", "alternate"):
        code = str((plan or {}).get(key, {}).get("icao") or "").upper()
        if code and code not in airport_codes:
            airport_codes.append(code)
    if position.get("ok"):
        for airport, _distance in nearest_airports(float(position["lat"]), float(position["lon"]), limit=6):
            if airport.ident not in airport_codes:
                airport_codes.append(airport.ident)
    airports: list[dict[str, Any]] = []
    for code in airport_codes:
        ap = airport_db.get(code)
        if not ap:
            continue
        airports.append({
            "icao": ap.ident,
            "name": ap.name,
            "lat": ap.lat,
            "lon": ap.lon,
            "role": "origin" if code == str((plan or {}).get("origin", {}).get("icao") or "").upper() else "destination" if code == str((plan or {}).get("destination", {}).get("icao") or "").upper() else "alternate" if code == str((plan or {}).get("alternate", {}).get("icao") or "").upper() else "nearby",
        })

    weather = {}
    for code in airport_codes[:3]:
        try:
            metar = fetch_metar(code, force=False)
            weather[code] = metar if isinstance(metar, dict) else {"raw": str(metar or "")}
        except Exception:
            continue

    ownship = None
    live_airport = None
    route_stale = False
    if position.get("ok"):
        nearest = nearest_airports(float(position["lat"]), float(position["lon"]), limit=1)
        if nearest:
            ap, distance_nm = nearest[0]
            live_airport = {"icao": ap.ident, "name": ap.name, "distance_nm": round(float(distance_nm), 1)}
        route_codes = {str((plan or {}).get(key, {}).get("icao") or "").upper() for key in ("origin", "destination", "alternate")} - {""}
        if live_airport and route_codes and live_airport["icao"] not in route_codes and float(live_airport.get("distance_nm") or 999) <= 15.0:
            route_stale = True
        ownship = {
            "lat": float(position["lat"]),
            "lon": float(position["lon"]),
            "heading_deg": _num(position.get("heading_deg")),
            "track_deg": _num(position.get("track_deg")),
            "altitude_ft": _num(position.get("indicated_altitude_ft") or position.get("altitude_ft")),
            "groundspeed_kts": _num(position.get("ground_speed_kts")),
            "callsign": str((plan or {}).get("callsign") or "OWN AIRCRAFT"),
            "nearest_airport": live_airport["icao"] if live_airport else None,
            "nearest_airport_distance_nm": live_airport["distance_nm"] if live_airport else None,
        }

    general = data.get("general") if isinstance(data.get("general"), dict) else {}
    return {
        "ok": True,
        "ownship": ownship,
        "route": _route_points(plan),
        "flight": {
            "callsign": (plan or {}).get("callsign"),
            "origin": (plan or {}).get("origin", {}).get("icao"),
            "destination": (plan or {}).get("destination", {}).get("icao"),
            "alternate": (plan or {}).get("alternate", {}).get("icao"),
            "live_airport": live_airport,
            "route_stale": route_stale,
        },
        "traffic": pilots,
        "controllers": controllers,
        "airports": airports,
        "atc_boundaries": boundary_status(),
        "weather": weather,
        "counts": {"traffic": len(pilots), "controllers": len(controllers), "route_points": len(_route_points(plan))},
        "vatsim_update": general.get("update_timestamp"),
        "openaip": {
            "configured": True,  # default VPS proxy endpoint is baked into the client
            "role": "metadata/vector overlay provider",
            "enabled": bool(settings.get("integrations", {}).get("openaip_map_enabled", True)),
            "runtime": _openaip_runtime(),
        },
        "updated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
