from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .data_loader import haversine_nm, load_airports, nearest_airport
from .settings_store import load_settings
from .simbrief_client import cached_plan
from .telemetry_provider import read_telemetry
from .vatsim_client import get_vatsim_data
from .vpilot_bridge import bridge_status

FACILITIES = {0: "UNKNOWN", 1: "OBS", 2: "FSS", 3: "DEL", 4: "GND", 5: "TWR", 6: "APP", 7: "CTR"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _airport_prefixes(code: str) -> set[str]:
    code = code.upper()
    prefixes = {code} if code else set()
    if len(code) == 4 and code[0] in {"K", "C", "P"}:
        prefixes.add(code[1:])
    return prefixes


def _station_matches(callsign: str, airports: set[str]) -> bool:
    stem = callsign.upper().split("_", 1)[0]
    return any(stem in _airport_prefixes(code) for code in airports if code)


def _frequency_number(value: Any) -> float | None:
    try:
        return round(float(str(value).strip()), 3)
    except (TypeError, ValueError):
        return None


def _current_station(rows: list[dict[str, Any]], radios: dict[str, Any]) -> dict[str, Any] | None:
    active = []
    for key in ("com1", "com2"):
        freq = _frequency_number((radios.get(key) or {}).get("active_mhz"))
        if freq is not None:
            active.append((key, freq))
    for key, freq in active:
        match = next((row for row in rows if (f := _frequency_number(row.get("frequency"))) is not None and abs(f - freq) < 0.006), None)
        if match:
            return {**match, "radio": key.upper(), "tuned_frequency": f"{freq:.3f}"}
    return None


def _controller_airport(row: dict[str, Any]) -> str:
    callsign = str(row.get("callsign") or "").upper()
    return callsign.split("_", 1)[0]


def _fallback_unicom() -> dict[str, Any]:
    return {
        "callsign": "UNICOM",
        "frequency": "122.800",
        "facility": "ADVISORY",
        "source": "uncontrolled_fallback",
        "confirmed": False,
        "fallback": True,
        "com2_monitor": {"callsign": "GUARD", "frequency": "121.500", "note": "Monitor only. Do not transmit unless required."},
        "detail": "No relevant online ATC found. Set COM1 to UNICOM 122.800 and COM2 to Guard 121.500 monitor only.",
    }


def _phase_context(position: dict[str, Any], origin: str, destination: str) -> str:
    on_ground = bool(position.get("on_ground"))
    gs = float(position.get("ground_speed_kts") or 0.0)
    airports = load_airports()
    dist_o = dist_d = None
    if position.get("ok"):
        if origin and origin in airports:
            a = airports[origin]; dist_o = haversine_nm(float(position["lat"]), float(position["lon"]), a.lat, a.lon)
        if destination and destination in airports:
            a = airports[destination]; dist_d = haversine_nm(float(position["lat"]), float(position["lon"]), a.lat, a.lon)
    if on_ground and (dist_o is not None and dist_o < 15) and not (dist_d is not None and dist_d < 10 and destination != origin):
        return "ORIGIN_GROUND"
    if on_ground and dist_d is not None and dist_d < 20 and destination:
        return "DESTINATION_GROUND"
    if dist_d is not None and dist_d < 90:
        return "ARRIVAL"
    if dist_o is not None and dist_o < 80:
        return "DEPARTURE"
    return "ENROUTE"


def _suggest_next(
    rows: list[dict[str, Any]],
    active_stations: list[dict[str, Any]],
    current: dict[str, Any] | None,
    position: dict[str, Any],
    origin: str,
    destination: str,
) -> dict[str, Any] | None:
    bridge = bridge_status()
    handoff = bridge.get("handoff")
    if isinstance(handoff, dict) and handoff.get("frequency"):
        freq = _frequency_number(handoff.get("frequency"))
        station = next((row for row in rows if freq is not None and (f := _frequency_number(row.get("frequency"))) is not None and abs(f - freq) < 0.006), None)
        return {
            "callsign": (station or {}).get("callsign") or handoff.get("from") or "ATC",
            "frequency": f"{freq:.3f}" if freq is not None else str(handoff.get("frequency")),
            "facility": (station or {}).get("facility"),
            "source": "handoff_message",
            "confirmed": True,
            "detail": handoff.get("message"),
        }

    context = _phase_context(position, origin, destination)
    candidates = [row for row in active_stations if not current or row.get("callsign") != current.get("callsign")]
    if not candidates:
        return _fallback_unicom()

    def pick(airport: str, facilities: list[int]) -> dict[str, Any] | None:
        prefixes = _airport_prefixes(airport)
        for fac in facilities:
            for row in candidates:
                if int(row.get("facility_code") or 0) != fac:
                    continue
                if _controller_airport(row) in prefixes:
                    return row
        return None

    chosen = None
    if context == "ORIGIN_GROUND":
        chosen = pick(origin, [3, 4, 5, 6, 7])
    elif context == "DESTINATION_GROUND":
        chosen = pick(destination, [4, 5, 6, 7])
    elif context == "ARRIVAL":
        chosen = pick(destination, [6, 5, 4, 7])
    elif context == "DEPARTURE":
        chosen = pick(origin, [6, 5, 7, 4, 3])

    if chosen is None:
        # Centres/FSS are route-wide fallback, but avoid suggesting destination ground before departure.
        centre = next((row for row in candidates if int(row.get("facility_code") or 0) in {7, 2}), None)
        chosen = centre or candidates[0]

    if not chosen:
        return _fallback_unicom()
    return {
        "callsign": chosen.get("callsign"),
        "frequency": chosen.get("frequency"),
        "facility": chosen.get("facility"),
        "source": "phase_aware_network_suggestion",
        "confirmed": False,
        "context": context,
        "detail": f"Suggested for {context.replace('_',' ').title()} using origin, destination, aircraft position and controller type. Follow ATC instructions if different.",
    }


def build_network_status(force: bool = False, query: str = "") -> dict[str, Any]:
    settings = load_settings()
    cid = _text(settings.get("identity", {}).get("vatsim_cid"))
    data = get_vatsim_data(force=force)
    pilots = data.get("pilots", []) or []
    controllers = data.get("controllers", []) or []
    atis_rows = data.get("atis", []) or []
    pilot = next((row for row in pilots if _text(row.get("cid")) == cid), None) if cid else None

    user_ref = _text(settings.get("identity", {}).get("simbrief_user_id"))
    plan = cached_plan(user_ref) if user_ref else None
    fp = pilot.get("flight_plan") if isinstance(pilot, dict) and isinstance(pilot.get("flight_plan"), dict) else {}
    origin = _text((plan or {}).get("origin", {}).get("icao") or fp.get("departure")).upper()
    destination = _text((plan or {}).get("destination", {}).get("icao") or fp.get("arrival")).upper()

    position = read_telemetry(force=False)
    nearest = None
    if position.get("ok"):
        hit = nearest_airport(float(position["lat"]), float(position["lon"]))
        if hit:
            nearest = {"icao": hit[0].ident, "name": hit[0].name, "distance_nm": round(hit[1], 1)}
    relevant_airports = {origin, destination, (nearest or {}).get("icao", "")}

    atis_by_callsign = {str(row.get("callsign") or "").upper(): row for row in atis_rows}
    rows: list[dict[str, Any]] = []
    query_u = query.strip().upper()
    for row in controllers:
        callsign = _text(row.get("callsign")).upper()
        if not callsign:
            continue
        name = _text(row.get("name"))
        frequency = _text(row.get("frequency"))
        if query_u and query_u not in callsign and query_u not in name.upper() and query_u not in frequency:
            continue
        facility_num = int(row.get("facility") or 0)
        atis = atis_by_callsign.get(callsign, {})
        text_atis = atis.get("text_atis") or []
        if isinstance(text_atis, str):
            text_atis = [text_atis]
        relevant = _station_matches(callsign, relevant_airports)
        rows.append({
            "callsign": callsign,
            "frequency": frequency,
            "name": name,
            "facility": FACILITIES.get(facility_num, str(facility_num)),
            "facility_code": facility_num,
            "visual_range": row.get("visual_range"),
            "logon_time": row.get("logon_time"),
            "atis": [str(item) for item in text_atis if str(item).strip()],
            "relevant": relevant,
        })
    rows.sort(key=lambda item: (not item["relevant"], -item["facility_code"], item["callsign"]))

    active_stations = [row for row in rows if row["relevant"]]
    radios = position.get("radios") if position.get("ok") else {}
    current_station = _current_station(rows, radios or {})
    next_station = _suggest_next(rows, active_stations, current_station, position, origin, destination)
    general = data.get("general") if isinstance(data.get("general"), dict) else {}
    return {
        "ok": True,
        "network_update": general.get("update_timestamp"),
        "identity": {
            "configured": bool(cid),
            "cid": cid or None,
            "online": bool(pilot),
            "callsign": _text((pilot or {}).get("callsign")) or None,
            "name": _text((pilot or {}).get("name")) or None,
            "server": _text((pilot or {}).get("server")) or None,
            "rating": (pilot or {}).get("rating"),
            "last_updated": (pilot or {}).get("last_updated"),
        },
        "flight": {
            "origin": origin or None,
            "destination": destination or None,
            "aircraft": _text(fp.get("aircraft_short") or fp.get("aircraft_faa")) or (plan or {}).get("aircraft", {}).get("icao"),
            "altitude": _text(fp.get("altitude")) or None,
            "route": _text(fp.get("route")) or (plan or {}).get("route"),
        },
        "nearest_airport": nearest,
        "radios": radios or {},
        "current_station": current_station,
        "next_station": next_station,
        "active_stations": active_stations,
        "controllers": rows[:150],
        "counts": {"pilots": len(pilots), "controllers": len(controllers), "atis": len(atis_rows)},
        "updated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
