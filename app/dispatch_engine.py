from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from .data_loader import Airport, airport_to_dict, haversine_nm, load_airports, nearest_airport
from .settings_store import load_settings
from .simbrief_client import cached_plan
from .simconnect_position import read_position
from .vatsim_client import get_vatsim_data
from .weather_client import fetch_metar

AIRCRAFT_PROFILES: dict[str, dict[str, Any]] = {
    "ga": {"label": "GENERAL AVIATION", "speed": 125, "overhead": 12, "types": {"small_airport", "medium_airport", "large_airport"}, "max_nm": 650, "simbrief_type": "C172", "flight_level": 100},
    "turboprop": {"label": "TURBOPROP", "speed": 275, "overhead": 22, "types": {"medium_airport", "large_airport"}, "max_nm": 1400, "simbrief_type": "DH8D", "flight_level": 240},
    "regional": {"label": "REGIONAL JET", "speed": 405, "overhead": 27, "types": {"medium_airport", "large_airport"}, "max_nm": 2100, "simbrief_type": "E190", "flight_level": 330},
    "narrowbody": {"label": "NARROWBODY", "speed": 445, "overhead": 32, "types": {"medium_airport", "large_airport"}, "max_nm": 3600, "simbrief_type": "A320", "flight_level": 350},
    "widebody": {"label": "WIDEBODY", "speed": 475, "overhead": 38, "types": {"large_airport"}, "max_nm": 7000, "simbrief_type": "B77W", "flight_level": 370},
    "business": {"label": "BUSINESS JET", "speed": 430, "overhead": 22, "types": {"medium_airport", "large_airport"}, "max_nm": 3200, "simbrief_type": "C700", "flight_level": 410},
}

ATC_SUFFIXES = ("_DEL", "_GND", "_TWR", "_APP", "_DEP", "_CTR", "_FSS")


def _airport_prefixes(icao: str) -> set[str]:
    icao = icao.upper()
    prefixes = {icao}
    if len(icao) == 4 and icao[0] in {"K", "C", "P"}:
        prefixes.add(icao[1:])
    return prefixes


def _controllers_for(icao: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    prefixes = _airport_prefixes(icao)
    rows: list[dict[str, Any]] = []
    for controller in data.get("controllers", []) or []:
        callsign = str(controller.get("callsign") or "").upper()
        if not callsign.endswith(ATC_SUFFIXES):
            continue
        stem = callsign.split("_", 1)[0]
        if stem not in prefixes:
            continue
        rows.append({
            "callsign": callsign,
            "frequency": str(controller.get("frequency") or ""),
            "facility": controller.get("facility"),
            "visual_range": controller.get("visual_range"),
        })
    rows.sort(key=lambda x: x["callsign"])
    return rows


def _traffic_by_airport(data: dict[str, Any]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for key in ("pilots", "prefiles"):
        for pilot in data.get(key, []) or []:
            fp = pilot.get("flight_plan") if isinstance(pilot, dict) else None
            if not isinstance(fp, dict):
                continue
            dep = str(fp.get("departure") or "").upper()
            arr = str(fp.get("arrival") or "").upper()
            if dep:
                counts.setdefault(dep, {"departures": 0, "arrivals": 0})["departures"] += 1
            if arr:
                counts.setdefault(arr, {"departures": 0, "arrivals": 0})["arrivals"] += 1
    return counts


def _resolve_origin(origin: str, source: str) -> tuple[Airport | None, str, dict[str, Any]]:
    airports = load_airports()
    origin = origin.strip().upper()
    source = source.strip().lower() or "auto"
    if origin:
        resolved = source if source in {"msfs", "simbrief"} else "manual"
        return airports.get(origin), resolved, {"requested": origin}

    settings = load_settings()
    user_ref = str(settings.get("identity", {}).get("simbrief_user_id") or "")
    plan = cached_plan(user_ref) if user_ref else None
    if source in {"simbrief", "auto"} and plan and plan.get("ok"):
        code = str(plan.get("origin", {}).get("icao") or "").upper()
        if code in airports:
            return airports[code], "simbrief", {"callsign": plan.get("callsign"), "destination": plan.get("destination", {}).get("icao")}

    if source in {"msfs", "auto"}:
        position = read_position(force=False)
        if position.get("ok"):
            hit = nearest_airport(float(position["lat"]), float(position["lon"]))
            if hit:
                return hit[0], "msfs", {"distance_nm": round(hit[1], 1), "position": {"lat": position["lat"], "lon": position["lon"]}}

    return None, source, {}


def dispatch_context() -> dict[str, Any]:
    settings = load_settings()
    user_ref = str(settings.get("identity", {}).get("simbrief_user_id") or "")
    plan = cached_plan(user_ref) if user_ref else None
    position = read_position(force=False)
    msfs = None
    if position.get("ok"):
        hit = nearest_airport(float(position["lat"]), float(position["lon"]))
        if hit:
            msfs = {"airport": airport_to_dict(hit[0]), "distance_nm": round(hit[1], 1)}
    return {
        "ok": True,
        "msfs": msfs,
        "simbrief": {
            "available": bool(plan and plan.get("ok")),
            "origin": plan.get("origin") if plan else None,
            "destination": plan.get("destination") if plan else None,
            "callsign": plan.get("callsign") if plan else None,
            "aircraft": plan.get("aircraft") if plan else None,
            "route": plan.get("route") if plan else None,
        },
        "profiles": {key: {k: v for k, v in value.items() if k != "types"} for key, value in AIRCRAFT_PROFILES.items()},
    }


def _weather_batch(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(candidates)))) as pool:
        jobs = {pool.submit(fetch_metar, row["destination"], False): row["destination"] for row in candidates}
        for future in as_completed(jobs):
            code = jobs[future]
            try:
                results[code] = future.result()
            except Exception as exc:
                results[code] = {"ok": False, "error": str(exc), "icao": code}
    return results


def _weather_score(weather: dict[str, Any], preference: str) -> tuple[float, bool, str]:
    if not weather.get("ok"):
        return 2.0, preference == "any", "WEATHER UNAVAILABLE"
    category = str(weather.get("flight_category") or "").upper()
    wind = weather.get("wind_speed")
    try:
        wind_value = float(wind) if wind is not None else 0.0
    except (TypeError, ValueError):
        wind_value = 0.0
    if preference == "vmc":
        allowed = category in {"VFR", "MVFR", ""}
        return (10.0 if category == "VFR" else 6.0 if category == "MVFR" else 3.0), allowed, category or "UNKNOWN"
    if preference == "avoid_strong_wind":
        allowed = wind_value < 25
        return max(1.0, 10.0 - max(0.0, wind_value - 10.0) * 0.35), allowed, f"WIND {round(wind_value)} KT"
    return (8.0 if category == "VFR" else 7.0 if category == "MVFR" else 6.0 if category else 3.0), True, category or "UNKNOWN"


def discover_routes(
    *,
    origin: str = "",
    origin_source: str = "auto",
    target_minutes: int = 120,
    tolerance_minutes: int = 35,
    aircraft: str = "narrowbody",
    atc: str = "prefer",
    weather: str = "any",
    limit: int = 16,
    force: bool = False,
) -> dict[str, Any]:
    profile = AIRCRAFT_PROFILES.get(aircraft, AIRCRAFT_PROFILES["narrowbody"])
    target_minutes = max(25, min(int(target_minutes), 720))
    tolerance_minutes = max(15, min(int(tolerance_minutes), 180))
    limit = max(4, min(int(limit), 30))
    origin_airport, resolved_source, source_detail = _resolve_origin(origin, origin_source)
    if not origin_airport:
        return {"ok": False, "reason": "No valid departure airport is available. Enter an ICAO code, load a SimBrief OFP, or connect MSFS.", "results": []}

    data = get_vatsim_data(force=force)
    traffic = _traffic_by_airport(data)
    origin_atc = _controllers_for(origin_airport.ident, data)
    airports = load_airports().values()
    rough: list[dict[str, Any]] = []
    min_minutes = max(20, target_minutes - tolerance_minutes)
    max_minutes = target_minutes + tolerance_minutes

    for destination in airports:
        if destination.ident == origin_airport.ident or destination.type == "closed":
            continue
        if destination.type not in profile["types"]:
            continue
        distance_nm = haversine_nm(origin_airport.lat, origin_airport.lon, destination.lat, destination.lon)
        if distance_nm > float(profile["max_nm"]):
            continue
        estimated_minutes = int(round(float(profile["overhead"]) + distance_nm / float(profile["speed"]) * 60.0))
        if estimated_minutes < min_minutes or estimated_minutes > max_minutes:
            continue
        duration_error = abs(estimated_minutes - target_minutes)
        duration_score = max(0.0, 40.0 * (1.0 - duration_error / max(tolerance_minutes, 1)))
        destination_atc = _controllers_for(destination.ident, data)
        if atc == "require_arrival" and not destination_atc:
            continue
        if atc == "require_both" and (not destination_atc or not origin_atc):
            continue
        atc_score = (10.0 if origin_atc else 0.0) + (15.0 if destination_atc else 0.0)
        counts = traffic.get(destination.ident, {"departures": 0, "arrivals": 0})
        traffic_total = counts["departures"] + counts["arrivals"]
        traffic_score = min(20.0, math.log2(traffic_total + 1.0) * 4.5)
        suitability = 5.0 if destination.type == "large_airport" else 4.0 if destination.type == "medium_airport" else 2.5
        rough.append({
            "origin": origin_airport.ident,
            "destination": destination.ident,
            "airport": airport_to_dict(destination),
            "distance_nm": round(distance_nm),
            "estimated_minutes": estimated_minutes,
            "duration_delta_minutes": estimated_minutes - target_minutes,
            "controllers": destination_atc,
            "origin_controllers": origin_atc,
            "traffic": counts,
            "score_base": duration_score + atc_score + traffic_score + suitability,
            "score_components": {"duration": round(duration_score, 1), "atc": round(atc_score, 1), "traffic": round(traffic_score, 1), "suitability": suitability},
            "simbrief": {"type": profile.get("simbrief_type", "A320"), "route": "", "flight_level": profile.get("flight_level")},
        })

    rough.sort(key=lambda row: (-row["score_base"], abs(row["duration_delta_minutes"]), row["destination"]))
    weather_candidates = rough[: max(limit, 12)]
    weather_data = _weather_batch(weather_candidates) if weather_candidates else {}
    final: list[dict[str, Any]] = []
    for row in weather_candidates:
        wx = weather_data.get(row["destination"], {"ok": False})
        wx_score, allowed, wx_label = _weather_score(wx, weather)
        if not allowed:
            continue
        row["weather"] = {
            "ok": bool(wx.get("ok")),
            "category": wx.get("flight_category"),
            "raw": wx.get("raw"),
            "wind_speed": wx.get("wind_speed"),
            "label": wx_label,
            "error": wx.get("error"),
        }
        row["score_components"]["weather"] = round(wx_score, 1)
        row["score"] = max(0, min(100, int(round(row.pop("score_base") + wx_score))))
        reasons: list[str] = []
        if row["controllers"]:
            reasons.append("ARRIVAL ATC ONLINE")
        if origin_atc:
            reasons.append("DEPARTURE ATC ONLINE")
        if row["traffic"]["arrivals"] + row["traffic"]["departures"]:
            reasons.append("ACTIVE VATSIM TRAFFIC")
        if abs(row["duration_delta_minutes"]) <= 10:
            reasons.append("CLOSE TIME MATCH")
        if wx.get("ok"):
            reasons.append(f"{wx_label} WEATHER")
        row["reasons"] = reasons[:4]
        final.append(row)
    final.sort(key=lambda row: (-row["score"], abs(row["duration_delta_minutes"]), row["destination"]))

    timestamp = data.get("general", {}).get("update_timestamp") if isinstance(data.get("general"), dict) else None
    return {
        "ok": True,
        "origin": airport_to_dict(origin_airport),
        "origin_source": resolved_source,
        "origin_source_detail": source_detail,
        "profile": {"id": aircraft, "label": profile["label"], "speed_kts": profile["speed"], "overhead_minutes": profile["overhead"]},
        "filters": {"target_minutes": target_minutes, "tolerance_minutes": tolerance_minutes, "atc": atc, "weather": weather},
        "origin_controllers": origin_atc,
        "network_update": timestamp,
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "results": final[:limit],
        "candidate_count": len(rough),
    }
