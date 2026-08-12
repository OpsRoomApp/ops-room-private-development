"""Fenix EFB takeoff performance engine (#61).

The Fenix EFB portal (localhost:8083) ships the aircraft's own certified
takeoff calculation. ``POST /fenix/calculate/vspeeds`` returns the exact
V1/VR/V2, FLEX temperature, TOFL, trim and retraction speeds the pilot sees
on the EFB takeoff page -- the Tier-1 source for a Fenix A320 flight.

Contract (reverse-engineered from the EFB bundle and verified live against a
running backend):

* ``request`` -- required non-empty string (validation fails without it).
* Flat fields: ``WindDirection``, ``WindSpeed``, ``Flap`` (1+F -> 1,
  opt -> 0, else number), ``Temperature``, ``PacksOn`` (bool),
  ``Weight: {Value, Unit: "KG"}`` (kg as integer), ``AircraftType``
  (enum: A320214 CFM CEO / A320232 IAE CEO), ``Sharklets``, ``RunwayLength``
  (m, int), ``Qnh`` (hPa, int), ``Elevation`` (ft, int), ``MacTow``
  (0 if unknown), ``ForceToga`` (bool), ``AntiIceSetting``
  ("Engine"/"EngineAndWing"/"None"), ``SurfaceCondition`` (e.g. "Dry"),
  ``RunwayMagneticHeading`` (deg), ``Icao`` (airport, upper), ``Runway``.

The result is TTL-cached (30 s on success, 5 s on failure) keyed on the full
input set so repeated Performance-tab refreshes never hammer the portal, and
never touches SimConnect/FSUIPC (pure HTTP to localhost).
"""

from __future__ import annotations

import threading
import time
from typing import Any

from .fenix_adapter import _number, _request

# Fenix A320 CEO engine-type enum accepted by the live backend. NEO / A319 /
# A321 variants are NOT served by this portal version and must fall back to
# the built-in engines (the driver reports "unsupported" rather than guessing).
AIRCRAFT_TYPE_CFM = "A320214"
AIRCRAFT_TYPE_IAE = "A320232"

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()
_TTL_SUCCESS = 30.0
_TTL_FAILURE = 5.0


def _cache_key(payload: dict[str, Any]) -> str:
    parts = []
    for key in (
        "AircraftType", "RunwayLength", "Weight", "MacTow", "Temperature", "Qnh",
        "Elevation", "WindDirection", "WindSpeed", "Flap", "PacksOn",
        "AntiIceSetting", "SurfaceCondition", "RunwayMagneticHeading", "Icao",
        "Runway", "Sharklets", "ForceToga",
    ):
        parts.append(f"{key}={payload.get(key)}")
    return "|".join(parts)


def _flap_value(flap: Any) -> int:
    """Map a takeoff flap label to the Fenix ``Flap`` integer contract.

    1+F -> 1, opt -> 0, plain numeric labels pass through; anything else
    (CONF 2, FLAPS 2, ...) is reduced to its first digit when possible.
    """
    text = str(flap or "").strip().upper()
    if not text:
        return 0
    if text in {"1+F", "1F"}:
        return 1
    if text in {"OPT", "OPTIMAL"}:
        return 0
    for ch in text:
        if ch.isdigit():
            return int(ch)
    return 0


def _anti_ice_setting(anti_ice: Any) -> str:
    if anti_ice is True:
        return "EngineAndWing"
    if isinstance(anti_ice, str):
        text = anti_ice.strip().lower()
        if "wing" in text or "both" in text:
            return "EngineAndWing"
        if "engine" in text:
            return "Engine"
    return "None"


def _surface_condition(condition: Any) -> str:
    text = str(condition or "dry").strip().lower()
    return {
        "wet": "Wet",
        "contaminated": "Contaminated",
        "snow": "Snow",
        "slush": "Slush",
    }.get(text, "Dry")


def aircraft_type_from_title(title: str | None) -> str | None:
    """Map the Fenix A320 title (e.g. 'Fenix A320 CFM') to the portal enum."""
    text = str(title or "").upper()
    if "A320" not in text and "A20N" not in text and "A319" not in text and "A321" not in text and "A21N" not in text:
        return None
    if "IAE" in text:
        return AIRCRAFT_TYPE_IAE
    if "CFM" in text or "LEAP" in text:
        return AIRCRAFT_TYPE_CFM
    return None


def fetch_takeoff(
    *,
    weight_kg: float,
    runway_length_m: float,
    qnh_hpa: float,
    elevation_ft: float,
    oat_c: float,
    wind_dir: float,
    wind_speed: float,
    flap: Any,
    packs_on: bool,
    anti_ice: Any,
    surface_condition: str,
    runway_heading: float,
    icao: str,
    runway: str,
    aircraft_type: str,
    mac_tow: float | None = None,
    force_toga: bool = False,
) -> dict[str, Any]:
    """Call the Fenix EFB takeoff calculator and return normalized values.

    Never fatal: returns ``ok=False`` with a reason when the portal is absent
    or the calculator refuses (unsupported aircraft type, bad input).
    """
    payload: dict[str, Any] = {
        "request": "opsroom",
        "WindDirection": float(wind_dir or 0),
        "WindSpeed": float(wind_speed or 0),
        "Flap": _flap_value(flap),
        "Temperature": float(oat_c if oat_c is not None else 15),
        "PacksOn": bool(packs_on),
        "Weight": {"Value": int(round(weight_kg or 0)), "Unit": "KG"},
        "AircraftType": str(aircraft_type or ""),
        "Sharklets": False,
        "RunwayLength": int(round(runway_length_m or 0)),
        "Qnh": int(round(qnh_hpa or 1013)),
        "Elevation": int(round(elevation_ft or 0)),
        "MacTow": float(mac_tow or 0),
        "ForceToga": bool(force_toga),
        "AntiIceSetting": _anti_ice_setting(anti_ice),
        "SurfaceCondition": _surface_condition(surface_condition),
        "RunwayMagneticHeading": float(runway_heading or 0),
        "Icao": str(icao or "").upper(),
        "Runway": str(runway or "").upper(),
    }
    key = _cache_key(payload)
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None and now - cached[0] < _TTL_SUCCESS:
            return dict(cached[1])

    result: dict[str, Any] = {"ok": False, "reason": "Fenix EFB takeoff calculation unavailable"}
    try:
        status_code, _text, parsed = _request("POST", "/fenix/calculate/vspeeds", payload, timeout=2.5)
        if 200 <= status_code < 300 and isinstance(parsed, dict) and isinstance(parsed.get("vSpeeds"), dict):
            vs = parsed["vSpeeds"] or {}
            result = {
                "ok": True,
                "status_code": status_code,
                "v1_kt": _number(vs.get("v1")),
                "vr_kt": _number(vs.get("vr")),
                "v2_kt": _number(vs.get("v2")),
                "flex_c": _number(parsed.get("flexTemperature")),
                "topl": _number(parsed.get("topl")),
                "topl_limited": bool(parsed.get("toplLimited")),
                "flap": parsed.get("flap"),
                "headwind_kt": _number(parsed.get("headwind")),
                "green_dot_kt": _number(parsed.get("greenDotSpeed")),
                "flap_retraction_kt": _number(parsed.get("flapRetractionSpeed")),
                "slat_retraction_kt": _number(parsed.get("slatRetractionSpeed")),
                "trim": _number(parsed.get("trimSetting")),
                "trim_direction": str(parsed.get("trimDirection") or "").upper(),
                "stop_margin": _number(parsed.get("stopMargin")),
                "corrected_stop_margin": _number(parsed.get("correctedStopMargin")),
            }
    except Exception as exc:
        result = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}

    ttl = _TTL_SUCCESS if result.get("ok") else _TTL_FAILURE
    with _CACHE_LOCK:
        _CACHE[key] = (now, result)
    return result
