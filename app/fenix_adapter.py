from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .settings_store import load_settings
from .simbrief_client import cached_plan
from .simconnect_position import read_position

DEFAULT_BASE_URL = "http://127.0.0.1:8083"
_CACHE: dict[str, Any] | None = None
_CACHE_TIME = 0.0
_LAST_SYNC: dict[str, Any] = {}

# Detection hysteresis (hold-last-known-good). Ground Control / GSX reads
# fenix_detected / fenix_controlled_loading at several call sites and reacts
# to the most recent read, so a single slow or failed EFB HTTP round-trip (a
# scene-load stutter, a busy EFB, ordinary localhost jitter) must not flip
# Fenix detection off for that one read. We hold the last confirmed True for a
# grace window and only report False after that many consecutive negative
# reads, mirroring the _STICKY_FAMILY pattern in addon_telemetry.py. A
# genuinely different aircraft (raw stays negative past the grace window and
# streak) still clears the hold promptly.
_FENIX_STICKY_GRACE_SECONDS = 12.0
_FENIX_STICKY_MAX_NEGATIVE = 3

_STICKY_DETECTED: bool | None = None
_STICKY_DETECTED_AT = 0.0
_STICKY_DETECTED_NEGATIVE = 0
_STICKY_CONTROLLED: bool | None = None
_STICKY_CONTROLLED_AT = 0.0
_STICKY_CONTROLLED_NEGATIVE = 0
# status() can be read from the GSX monitor thread and API request threads
# concurrently; guard the sticky read-modify-write so a lost update cannot
# extend the hold past its grace window.
_STICKY_LOCK = threading.Lock()


def _sticky_bool(
    raw: bool,
    sticky: bool | None,
    at: float,
    negatives: int,
    now: float,
) -> tuple[bool, float, int]:
    """Return the held (stabilized) value plus the updated sticky bookkeeping.

    A confirmed ``raw=True`` resets the hold. ``raw=False`` keeps reporting True
    while the last confirmed state is younger than the grace window and the
    consecutive-negative streak is under the cap; once either bound is crossed
    it reports False and clears the hold so a genuine aircraft change is
    detected promptly.
    """
    if raw:
        return True, now, 0
    if sticky is True and (now - at) < _FENIX_STICKY_GRACE_SECONDS and negatives < _FENIX_STICKY_MAX_NEGATIVE:
        return True, at, negatives + 1
    return False, now, 0



def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _base_url() -> str:
    raw = str(load_settings().get("integrations", {}).get("fenix_efb_url") or DEFAULT_BASE_URL).strip()
    if not raw:
        raw = DEFAULT_BASE_URL
    return raw.rstrip("/")


def _request(method: str, path: str, payload: Any | None = None, timeout: float = 1.8) -> tuple[int, str, Any]:
    url = f"{_base_url()}{path}"
    body = None
    headers = {"Accept": "application/json, text/plain, */*", "User-Agent": "OPS ROOM/0.20.0 Fenix adapter"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
    with urllib.request.urlopen(req, timeout=timeout) as response:
        text = response.read().decode("utf-8", errors="replace")
        parsed: Any = None
        if text.strip():
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = text
        return int(getattr(response, "status", 200)), text, parsed


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _number(value)
    return int(round(number)) if number is not None else None


def _is_fenix_aircraft() -> tuple[bool, dict[str, Any]]:
    try:
        telemetry = read_position(force=False)
    except Exception:
        telemetry = {}
    aircraft = telemetry.get("aircraft") if isinstance(telemetry, dict) else {}
    adapter = telemetry.get("aircraft_adapter") if isinstance(telemetry, dict) else {}
    haystack = " ".join(str((aircraft or {}).get(k) or "") for k in ("title", "model", "type")).upper()
    detected = (adapter or {}).get("key") == "fenix" or "FENIX" in haystack or "FNX" in haystack
    return bool(detected), {"telemetry_ok": bool(telemetry.get("ok")), "aircraft": aircraft or {}, "adapter": adapter or {}}


_FENIX_FAMILY_RE = re.compile(r"\b(A319|A320|A321|A20N|A21N)\b", re.I)


def _airbus_narrowbody_family_hint(aircraft_info: dict[str, Any]) -> tuple[bool, str]:
    aircraft = aircraft_info.get("aircraft") if isinstance(aircraft_info, dict) else {}
    adapter = aircraft_info.get("adapter") if isinstance(aircraft_info, dict) else {}
    raw = " ".join(
        str(value or "")
        for value in (
            (aircraft or {}).get("title"),
            (aircraft or {}).get("model"),
            (aircraft or {}).get("type"),
            (adapter or {}).get("name"),
            (adapter or {}).get("key"),
        )
    ).upper()
    match = _FENIX_FAMILY_RE.search(raw)
    return bool(match), match.group(1).upper() if match else ""


def _last_sync_success_recent(max_age_s: float = 900.0) -> bool:
    try:
        if not _LAST_SYNC or not _LAST_SYNC.get("targets"):
            return False
        raw_time = str(_LAST_SYNC.get("time") or "")
        if not raw_time:
            return False
        stamp = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - stamp).total_seconds()
        return 0.0 <= age <= max_age_s
    except Exception:
        return False


def _plan_from_opsroom() -> dict[str, Any] | None:
    settings = load_settings()
    user = str(settings.get("identity", {}).get("simbrief_user_id") or "")
    return cached_plan(user) if user else None


def _fenix_cabin_capacity_hint(pax_count: int | None = None) -> int | None:
    """Best-effort Fenix economy cabin size for the booked-seat string.

    The Fenix EFB writes a full cabin booked-seat map, for example an A320 with
    179 planned passengers sends 179 `true` values and one `false` for the empty
    seat.  Keep this conservative: use the detected Fenix variant when available,
    otherwise only apply the common A320 180-seat shape when it is a clear fit.
    """
    try:
        _detected, info = _is_fenix_aircraft()
        aircraft = info.get("aircraft") if isinstance(info, dict) else {}
        adapter = info.get("adapter") if isinstance(info, dict) else {}
        title = " ".join(str((aircraft or {}).get(k) or "") for k in ("title", "model", "type"))
        title = (title + " " + str((adapter or {}).get("name") or "")).upper()
    except Exception:
        title = ""
    if "A319" in title:
        return 156
    if "A321" in title or "A21N" in title:
        return 220
    if "A320" in title or "A20N" in title or "FENIX" in title or "FNX" in title:
        return 180
    if pax_count is not None and 0 < int(pax_count) <= 180:
        return 180
    return None


def _targets_from_plan(plan: dict[str, Any] | None) -> dict[str, Any]:
    plan = plan or {}
    fuel = plan.get("fuel") if isinstance(plan.get("fuel"), dict) else {}
    weights = plan.get("weights") if isinstance(plan.get("weights"), dict) else {}
    # Fenix captured payload used Fuel.Target and Cargo.Target in kg. SimBrief normalizer
    # stores plan_ramp as ramp fuel. Prefer ramp, then takeoff, and cargo/payload.
    fuel_target = _int(fuel.get("ramp") or fuel.get("takeoff"))
    cargo_target = _int(weights.get("cargo") or weights.get("payload"))
    pax_count = _int(weights.get("passengers"))
    units = str((fuel.get("units") or weights.get("units") or "")).upper()
    if units in {"LBS", "LB", "POUNDS"}:
        if fuel_target is not None:
            fuel_target = int(round(fuel_target * 0.45359237))
        if cargo_target is not None:
            cargo_target = int(round(cargo_target * 0.45359237))
    seat_capacity = _fenix_cabin_capacity_hint(pax_count)
    return {
        "fuel_kg": fuel_target,
        "cargo_kg": cargo_target,
        "pax_count": pax_count,
        "seat_capacity": seat_capacity,
        "source": "opsroom_simbrief" if plan else "none",
        "plan_id": plan.get("plan_id"),
        "callsign": plan.get("callsign"),
        "origin": ((plan.get("origin") or {}).get("icao") if isinstance(plan.get("origin"), dict) else None),
        "destination": ((plan.get("destination") or {}).get("icao") if isinstance(plan.get("destination"), dict) else None),
    }




def loading_targets(plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the Fenix loading targets OPS ROOM would use, without starting anything."""
    return _targets_from_plan(plan or _plan_from_opsroom())


def loading_signature(plan: dict[str, Any] | None = None) -> str:
    """Stable per-flight signature used to make Fenix GSX loading idempotent.

    This deliberately uses the planned load targets and SimBrief identifiers rather
    than transient GSX passenger counters, because those counters can briefly reset
    to zero while Fenix/GSX is already loading.
    """
    targets = loading_targets(plan)
    parts = [
        str(targets.get("plan_id") or ""),
        str(targets.get("callsign") or ""),
        str(targets.get("fuel_kg") or ""),
        str(targets.get("cargo_kg") or ""),
        str(targets.get("pax_count") or ""),
    ]
    signature = "|".join(parts).strip("|")
    return signature or "fenix-current-flight"

def simbrief() -> dict[str, Any]:
    try:
        status_code, _text, parsed = _request("GET", "/fenix/simbrief", timeout=2.0)
        return {"ok": True, "status_code": status_code, "data": parsed, "base_url": _base_url()}
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}", "base_url": _base_url()}


def loadsheet() -> dict[str, Any]:
    # #87: the Fenix portal requires loadsheetType. Preliminary is the correct
    # type for the loading-progress path (it reflects in-progress boarding);
    # the weights path uses loadsheet_final() which passes loadsheetType=Final.
    # #114: Fenix emits Preliminary once a loadsheet is generated (dispatch /
    # loading start) and Final only after pax/cargo boarding and refuelling
    # complete. HTTP 204 (or an empty body) therefore means "no loadsheet of
    # this type generated yet" -- a soft, retryable state, never a failure.
    try:
        status_code, _text, parsed = _request("GET", "/fenix/loadsheet?loadsheetType=Preliminary", timeout=2.0)
        if status_code == 204 or parsed in (None, "", [], {}):
            return {"ok": True, "status_code": status_code, "data": None,
                    "pending": True, "base_url": _base_url()}
        return {"ok": True, "status_code": status_code, "data": parsed, "base_url": _base_url()}
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}", "base_url": _base_url()}


_LOADSHEET_FINAL_CACHE: dict[str, Any] | None = None
_LOADSHEET_FINAL_AT = 0.0
_LOADSHEET_FINAL_TTL = 30.0
_LOADSHEET_FINAL_FAIL_TTL = 5.0


def loadsheet_final(force: bool = False) -> dict[str, Any]:
    """Fetch the Fenix EFB FINAL loadsheet weights (#60).

    ``GET /fenix/loadsheet?loadsheetType=Final`` returns the aircraft's exact
    TOW / ZFW / LDW plus maxes and MACs at ANY flight phase (verified live:
    HTTP 200 during cruise). This is the trusted source that fixes the Live
    OFP TOW/ZFW/LDW actuals that FSUIPC 0x30C0 never fills on Fenix.

    Weights arrive as ``{value, unit}`` objects; MACs are plain numbers.
    TTL-cached (30 s on success, 5 s on failure) so repeated Live OFP
    refreshes never hammer the portal. Never fatal: returns ``ok=False`` when
    the portal is absent or the payload is not a Final loadsheet.
    """
    global _LOADSHEET_FINAL_CACHE, _LOADSHEET_FINAL_AT
    now = time.monotonic()
    if not force and _LOADSHEET_FINAL_CACHE and now - _LOADSHEET_FINAL_AT < _LOADSHEET_FINAL_TTL:
        return dict(_LOADSHEET_FINAL_CACHE)

    def _weight(data: dict[str, Any], key: str) -> float | None:
        value = data.get(key)
        if isinstance(value, dict):
            return _number(value.get("value"))
        return _number(value)

    result: dict[str, Any] = {"ok": False, "reason": "Fenix Final loadsheet unavailable"}
    ttl = _LOADSHEET_FINAL_FAIL_TTL
    try:
        status_code, _text, parsed = _request("GET", "/fenix/loadsheet?loadsheetType=Final", timeout=2.5)
        data = parsed if isinstance(parsed, dict) else {}
        tow = _weight(data, "tow")
        zfw = _weight(data, "zfw")
        law = _weight(data, "law")
        if 200 <= status_code < 300 and (tow is not None or zfw is not None or law is not None):
            result = {
                "ok": True,
                "status_code": status_code,
                "tow_kg": tow,
                "zfw_kg": zfw,
                "law_kg": law,
                "mac_tow": _number(data.get("macTow")),
                "mac_zfw": _number(data.get("macZfw")),
                "max_tow_kg": _weight(data, "maxTow"),
                "max_zfw_kg": _weight(data, "maxZfw"),
                "max_law_kg": _weight(data, "maxLaw"),
                "pax": _int(_weight(data, "pax")),
                "total_cargo_kg": _weight(data, "totalCargo"),
                "base_url": _base_url(),
            }
            ttl = _LOADSHEET_FINAL_TTL
    except Exception as exc:
        result = {"ok": False, "reason": f"{type(exc).__name__}: {exc}", "base_url": _base_url()}
    _LOADSHEET_FINAL_CACHE = result
    _LOADSHEET_FINAL_AT = now
    return dict(result)


def loadsheet_final_cached() -> dict[str, Any]:
    """#71-followup: read the FINAL loadsheet cache WITHOUT touching the portal.

    The background Fenix probe thread keeps this cache warm; request paths
    (Live OFP payload, perf page) must never block on the EFB fetch again.
    Returns the cached sheet or an honest "not cached yet" result.
    """
    if _LOADSHEET_FINAL_CACHE is not None:
        return dict(_LOADSHEET_FINAL_CACHE)
    return {"ok": False, "reason": "Fenix loadsheet not cached yet; background refresh in progress", "base_url": _base_url()}


_EFB_ACTIVE_CACHE: tuple[float, bool] | None = None
_EFB_ACTIVE_TTL = 10.0


def fenix_efb_active() -> bool:
    """#94: SimConnect-independent Fenix signal for ground handling.

    Returns True when the Fenix EFB portal (8083) is reachable AND answers
    with a Fenix-shaped loadsheet. This is the fallback detection source for
    GSX arrival/boarding door/GPU/chocks commands: those commands go through
    the EFB GraphQL portal anyway, so they never need SimConnect — only the
    old identity probe did, and it silently disabled Fenix handling whenever
    SimConnect was degraded.
    """
    global _EFB_ACTIVE_CACHE
    now = time.monotonic()
    if _EFB_ACTIVE_CACHE and now - _EFB_ACTIVE_CACHE[0] < _EFB_ACTIVE_TTL:
        return _EFB_ACTIVE_CACHE[1]
    active = False
    try:
        st = status(force=False)
        if st.get("efb_online"):
            final = loadsheet_final_cached()
            if final.get("ok"):
                active = True
            else:
                prelim = loadsheet()
                data = prelim.get("data") if prelim.get("ok") else {}
                if isinstance(data, dict) and (
                    data.get("aircraftTailNumber") or data.get("zfw") is not None or data.get("tow") is not None
                ):
                    active = True
    except Exception:
        active = False
    _EFB_ACTIVE_CACHE = (now, active)
    return active


def status(force: bool = False) -> dict[str, Any]:
    global _CACHE, _CACHE_TIME
    global _STICKY_DETECTED, _STICKY_DETECTED_AT, _STICKY_DETECTED_NEGATIVE
    global _STICKY_CONTROLLED, _STICKY_CONTROLLED_AT, _STICKY_CONTROLLED_NEGATIVE
    now = time.monotonic()
    if not force and _CACHE and now - _CACHE_TIME < 3.0:
        return dict(_CACHE)
    raw_detected, aircraft_info = _is_fenix_aircraft()
    family_hint, aircraft_family = _airbus_narrowbody_family_hint(aircraft_info)
    recent_sync = _last_sync_success_recent()
    probe = simbrief()
    efb_online = bool(probe.get("ok"))
    raw_controlled = bool(efb_online and (raw_detected or (family_hint and recent_sync)))
    # Hold-last-known-good: a single failed probe or degraded identity read must
    # not flip Fenix detection off for Ground Control / GSX. The reported values
    # are the stabilized ones; the raw probe outcome stays observable below.
    with _STICKY_LOCK:
        detected, _STICKY_DETECTED_AT, _STICKY_DETECTED_NEGATIVE = _sticky_bool(
            raw_detected, _STICKY_DETECTED, _STICKY_DETECTED_AT, _STICKY_DETECTED_NEGATIVE, now
        )
        _STICKY_DETECTED = detected
        fenix_controlled_loading, _STICKY_CONTROLLED_AT, _STICKY_CONTROLLED_NEGATIVE = _sticky_bool(
            raw_controlled, _STICKY_CONTROLLED, _STICKY_CONTROLLED_AT, _STICKY_CONTROLLED_NEGATIVE, now
        )
        _STICKY_CONTROLLED = fenix_controlled_loading
    if detected:
        detection_mode = "strict"
    elif fenix_controlled_loading:
        detection_mode = "efb_online_family_recent_sync"
    elif efb_online and family_hint:
        detection_mode = "efb_online_family_no_recent_sync"
    else:
        detection_mode = "not_fenix_controlled"
    data = {
        "ok": True,
        "fenix_detected": detected,
        "fenix_detected_raw": raw_detected,
        "efb_online": efb_online,
        "base_url": _base_url(),
        "simbrief_available": efb_online,
        "aircraft": aircraft_info,
        "fenix_family_hint": family_hint,
        "aircraft_family": aircraft_family,
        "last_sync_success_recent": recent_sync,
        "fenix_controlled_loading": fenix_controlled_loading,
        "fenix_controlled_loading_raw": raw_controlled,
        "detection_mode": detection_mode,
        "sticky_grace_seconds": _FENIX_STICKY_GRACE_SECONDS,
        "sticky_detected_negative_streak": _STICKY_DETECTED_NEGATIVE,
        "sticky_controlled_negative_streak": _STICKY_CONTROLLED_NEGATIVE,
        "last_sync": dict(_LAST_SYNC),
        "reason": None if probe.get("ok") else probe.get("reason"),
    }
    _CACHE = data
    _CACHE_TIME = now
    return dict(data)


def _graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    status_code, _text, parsed = _request("POST", "/graphql", {"query": query, "variables": variables}, timeout=2.0)
    errors = parsed.get("errors") if isinstance(parsed, dict) else None
    ok = bool(200 <= status_code < 300 and not errors)
    reason = ""
    if errors:
        try:
            reason = "; ".join(str(item.get("message") or item) for item in errors if item)
        except Exception:
            reason = str(errors)
    return {"ok": ok, "status_code": status_code, "data": parsed, "errors": errors or [], "reason": reason}


def _write_float(name: str, value: float) -> dict[str, Any]:
    return _graphql(
        'mutation ($name: String!, $value: Float!) { dataRef { writeFloat(name: $name, value: $value) { __typename } } }',
        {"name": name, "value": float(value)},
    )


def _write_string(name: str, value: str) -> dict[str, Any]:
    return _graphql(
        'mutation ($name: String!, $value: String!) { dataRef { writeString(name: $name, value: $value) { __typename } } }',
        {"name": name, "value": str(value)},
    )


def _write_bool(name: str, value: bool) -> dict[str, Any]:
    return _graphql(
        'mutation ($name: String!, $value: Boolean!) { dataRef { writeBool(name: $name, value: $value) { __typename } } }',
        {"name": name, "value": bool(value)},
    )


def _write_fenix_float(name: str, variable: str, value: float) -> dict[str, Any]:
    """Write a Fenix dataref using the same literal-name mutation shape captured from the Fenix EFB HAR."""
    return _graphql(
        f'mutation (${variable}: Float!) {{ dataRef {{ writeFloat(name: "{name}", value: ${variable}) __typename }} }}',
        {variable: float(value)},
    )


def _write_fenix_string(name: str, variable: str, value: str) -> dict[str, Any]:
    """Write a Fenix string dataref using the same literal-name mutation shape captured from the Fenix EFB HAR."""
    return _graphql(
        f'mutation (${variable}: String!) {{ dataRef {{ writeString(name: "{name}", value: ${variable}) __typename }} }}',
        {variable: str(value)},
    )


def _write_fenix_bool(name: str, variable: str, value: bool) -> dict[str, Any]:
    """Write a Fenix boolean dataref using the same literal-name mutation shape captured from the Fenix EFB HAR."""
    return _graphql(
        f'mutation (${variable}: Boolean!) {{ dataRef {{ writeBool(name: "{name}", value: ${variable}) __typename }} }}',
        {variable: bool(value)},
    )



def set_cargo_door(door: str, open_door: bool = True) -> dict[str, Any]:
    """Operate Fenix cargo doors through the EFB GraphQL dataref API.

    Captured Fenix EFB traffic uses literal writeBool names
    `doors.cargo.forward`, `doors.cargo.aft` and `doors.cargo.bulk`. The
    verified manual EFB command uses ``true`` for the open action. This is
    intentionally Fenix-only and never falls back to generic FSUIPC exits.
    """
    key = str(door or "").strip().lower()
    if key in {"fwd", "front", "forward", "cargo1", "cargo 1"}:
        name, variable = "doors.cargo.forward", "fwdC"
    elif key in {"aft", "rear", "back", "cargo2", "cargo 2"}:
        name, variable = "doors.cargo.aft", "aftC"
    elif key in {"bulk", "cargo3", "cargo 3"}:
        name, variable = "doors.cargo.bulk", "bulkC"
    else:
        return {"ok": False, "reason": f"Unsupported Fenix cargo door: {door}"}
    value = bool(open_door)
    try:
        result = _write_fenix_bool(name, variable, value)
        result.update({"door": key, "dataref": name, "value": value, "open_requested": bool(open_door)})
        return result
    except Exception as exc:
        return {"ok": False, "door": key, "dataref": name, "value": value, "reason": f"{type(exc).__name__}: {exc}"}


def set_entry_door(door: str, open_door: bool = True) -> dict[str, Any]:
    """Operate a verified Fenix passenger entry door through GraphQL."""
    key = str(door or "").strip().lower()
    names = {
        "d1l": "doors.entry.d1l", "d1r": "doors.entry.d1r",
        "d2l": "doors.entry.d2l", "d2r": "doors.entry.d2r",
        "d4l": "doors.entry.d4l", "d4r": "doors.entry.d4r",
    }
    name = names.get(key)
    if not name:
        return {"ok": False, "reason": f"Unsupported Fenix entry door: {door}"}
    try:
        variable = key.replace("d", "door", 1)
        result = _write_fenix_bool(name, variable, bool(open_door))
        result.update({"door": key, "dataref": name, "value": bool(open_door), "open_requested": bool(open_door)})
        return result
    except Exception as exc:
        return {"ok": False, "door": key, "dataref": name, "value": bool(open_door), "reason": f"{type(exc).__name__}: {exc}"}



def set_ground_power(connected: bool = True) -> dict[str, Any]:
    """Set the Fenix EFB external ground-power state without toggling it."""
    try:
        result = _write_fenix_bool("groundservice.groundpower", "gpu", bool(connected))
        result.update({"dataref": "groundservice.groundpower", "value": bool(connected), "connected_requested": bool(connected)})
        return result
    except Exception as exc:
        return {"ok": False, "dataref": "groundservice.groundpower", "value": bool(connected), "reason": f"{type(exc).__name__}: {exc}"}


def set_chocks(set_chocks: bool = True) -> dict[str, Any]:
    """Set the Fenix EFB chocks state without toggling it."""
    try:
        result = _write_fenix_bool("fenix.efb.chocks", "chocks", bool(set_chocks))
        result.update({"dataref": "fenix.efb.chocks", "value": bool(set_chocks), "set_requested": bool(set_chocks)})
        return result
    except Exception as exc:
        return {"ok": False, "dataref": "fenix.efb.chocks", "value": bool(set_chocks), "reason": f"{type(exc).__name__}: {exc}"}

def start_deboarding() -> dict[str, Any]:
    """Start the Fenix arrival deboarding task once for the current session."""
    status_code, _text, parsed = _request("POST", "/fenix/tasks/startDeboarding", {}, timeout=3.5)
    return {"ok": 200 <= status_code < 300, "status_code": status_code, "response": parsed, "base_url": _base_url(), "mode": "fenix_efb_deboarding"}

def _iso_to_epoch(value: Any) -> int | None:
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        return int(datetime.fromisoformat(text).timestamp())
    except Exception:
        return None


def _flight_timestamp_json(plan: dict[str, Any] | None) -> str | None:
    """Build the small Fenix flight timestamp object seen in the Fenix EFB import flow.

    The EFB accepts this as a string dataref. Missing times are left as 0/blank so
    this remains best-effort and does not block boarding if SimBrief time data is absent.
    """
    if not isinstance(plan, dict):
        return None
    times = plan.get("times") if isinstance(plan.get("times"), dict) else {}
    sched_out = _iso_to_epoch(times.get("scheduled_out")) or 0
    sched_off = _iso_to_epoch(times.get("scheduled_off")) or sched_out
    sched_on = _iso_to_epoch(times.get("scheduled_on")) or 0
    sched_in = _iso_to_epoch(times.get("scheduled_in")) or sched_on
    generated = int(_number(plan.get("generated_timestamp")) or time.time())
    eobt = ""
    if sched_out:
        try:
            eobt = datetime.fromtimestamp(sched_out, tz=timezone.utc).strftime("%H:%M")
        except Exception:
            eobt = ""
    payload = {
        "fenixTimes": {
            "scheduledOut": str(sched_out or 0),
            "scheduledIn": str(sched_in or 0),
            "estimatedIn": str(sched_on or sched_in or 0),
            "estimatedOut": str(sched_out or 0),
            "estimatedOn": str(sched_on or sched_in or 0),
            "estimatedOff": str(sched_off or sched_out or 0),
            "adc": "-1",
            "adcR": "-1",
            "adcS": "0",
            "comp": str(plan.get("airline") or "JST"),
            "delayProcessed": "0",
            "eobt": eobt,
            "in": "",
            "off": "",
            "out": "",
            "on": "",
            "phase": "parked",
            "prelimEdno": str((generated // 10) % 1000000000),
        }
    }
    return json.dumps(payload, separators=(",", ":"))


def _stable_index_shuffle(indices: list[int], seed: str) -> list[int]:
    """Deterministically shuffle seat indices without changing on refresh."""
    decorated: list[tuple[str, int]] = []
    for idx in indices:
        digest = hashlib.sha256(f"{seed}|{idx}".encode("utf-8", errors="ignore")).hexdigest()
        decorated.append((digest, idx))
    decorated.sort()
    return [idx for _digest, idx in decorated]


def _balanced_booked_indices(capacity: int, pax: int, seed: str) -> set[int]:
    """Return a balanced, random-looking Fenix seat assignment.

    Fenix expects a full booked-seat map. A sequential map front-loads the cabin
    and can move the CG outside the envelope. Split the cabin into forward/mid/aft
    zones, allocate proportionally, then use a stable hash shuffle inside each
    zone so the result is realistic but repeatable for a flight.
    """
    capacity = max(0, int(capacity))
    pax = max(0, min(int(pax), capacity))
    if pax <= 0 or capacity <= 0:
        return set()
    # Three roughly equal longitudinal cabin zones. Use integer cut points so it
    # works for A319/A320/A321 capacities without hard-coding row layouts.
    cuts = [0, capacity // 3, (capacity * 2) // 3, capacity]
    zones = [list(range(cuts[i], cuts[i + 1])) for i in range(3)]
    chosen: set[int] = set()
    remainders: list[tuple[float, int]] = []
    remaining = pax
    for zone_index, zone in enumerate(zones):
        exact = pax * (len(zone) / capacity) if capacity else 0
        count = int(exact)
        remainders.append((exact - count, zone_index))
        take = min(count, len(zone), remaining)
        for idx in _stable_index_shuffle(zone, f"{seed}|zone{zone_index}")[:take]:
            chosen.add(idx)
        remaining -= take
    # Spread leftover passengers by largest proportional remainder, not front-to-back.
    for _frac, zone_index in sorted(remainders, reverse=True):
        if remaining <= 0:
            break
        available = [idx for idx in _stable_index_shuffle(zones[zone_index], f"{seed}|extra{zone_index}") if idx not in chosen]
        if available:
            chosen.add(available[0])
            remaining -= 1
    if remaining > 0:
        available = [idx for idx in _stable_index_shuffle(list(range(capacity)), f"{seed}|spill") if idx not in chosen]
        for idx in available[:remaining]:
            chosen.add(idx)
    return chosen


def _booked_array_string(pax_count: int | None, seat_capacity: int | None = None, seed: str = "") -> str | None:
    if pax_count is None or pax_count <= 0:
        return None
    pax = max(0, int(pax_count))
    capacity = int(seat_capacity or 0)
    if capacity > 0 and capacity >= pax:
        seed = seed or f"fenix|{capacity}|{pax}"
        booked = _balanced_booked_indices(capacity, pax, seed)
        return ",".join("true" if idx in booked else "false" for idx in range(capacity))
    # Fallback to the older proven OPS ROOM style when the cabin size is unknown.
    return ",".join("true" for _ in range(pax))


def _generate_loadsheet(loadsheet_type: str = "Preliminary") -> dict[str, Any]:
    status_code, _text, parsed = _request("POST", f"/fenix/loadsheet/generate?type={loadsheet_type}", {}, timeout=4.5)
    return {"ok": 200 <= status_code < 300, "status_code": status_code, "data": parsed, "type": loadsheet_type}


def sync_load_targets(plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Prepare the Fenix EFB for normal GSX boarding using the HAR-confirmed sequence.

    v0.20.0 is intentionally based on the well-tested v0.18.19 RC2 flow, with the
    Fenix-specific writes corrected to match the normal Fenix EFB GSX boarding trace:
    cargo, canonical refuel target, booked passenger array, ATC/GND init message,
    preliminary loadsheet, boardingStatus=inProg, mass balance locked, then
    /fenix/tasks/startGsxBoarding.
    """
    global _LAST_SYNC, _CACHE, _CACHE_TIME
    plan_obj = plan or _plan_from_opsroom()
    targets = _targets_from_plan(plan_obj)
    fuel_kg, cargo_kg, pax_count = targets.get("fuel_kg"), targets.get("cargo_kg"), targets.get("pax_count")
    if fuel_kg is None and cargo_kg is None:
        return {"ok": False, "reason": "No SimBrief fuel/cargo target is available", "targets": targets}
    writes: list[dict[str, Any]] = []
    try:
        # Warm/read the Fenix SimBrief endpoint first, like the EFB does. The result
        # is diagnostic only; Fenix can return a compact/obfuscated payload across builds.
        try:
            writes.append({"name": "GET /fenix/simbrief", "result": simbrief()})
        except Exception as exc:
            writes.append({"name": "GET /fenix/simbrief", "result": {"ok": False, "reason": str(exc)}})

        flight_json = _flight_timestamp_json(plan_obj)
        if flight_json:
            writes.append({"name": "fenix.efb.flightTimestampJSON", "result": _write_fenix_string("fenix.efb.flightTimestampJSON", "flightDetailsJSON", flight_json)})

        if cargo_kg is not None:
            writes.append({"name": "fenix.efb.plannedCargoKg", "result": _write_fenix_float("fenix.efb.plannedCargoKg", "plannedCargoKg", float(cargo_kg))})
        if fuel_kg is not None:
            # HAR-confirmed Fenix dataref. The old underscore variant did not match the EFB.
            writes.append({"name": "aircraft.refuel.fuelTarget.kg", "result": _write_fenix_float("aircraft.refuel.fuelTarget.kg", "refuelTargetKg", float(fuel_kg))})

        seat_seed = "|".join(str(targets.get(k) or "") for k in ("plan_id", "callsign", "origin", "destination", "pax_count", "seat_capacity"))
        booked = _booked_array_string(None if pax_count is None else int(pax_count), targets.get("seat_capacity"), seat_seed)
        if booked:
            writes.append({"name": "fenix.efb.passengers.booked.string", "result": _write_fenix_string("fenix.efb.passengers.booked.string", "bookedArrayString", booked)})
            # Fenix EFB writes this twice in the captured normal flow; repeat once for parity.
            writes.append({"name": "fenix.efb.passengers.booked.string", "result": _write_fenix_string("fenix.efb.passengers.booked.string", "bookedArrayString", booked)})

        ground_init = json.dumps({
            "PaxCount": "" if pax_count is None else str(int(pax_count)),
            "Payload": "" if cargo_kg is None else str(int(cargo_kg)),
            "Fuel": "" if fuel_kg is None else str(int(fuel_kg)),
        }, separators=(",", ":"))
        writes.append({"name": "aircraft.atsu.ground.init", "result": _write_fenix_string("aircraft.atsu.ground.init", "atsuGroundServicesInitMessage", ground_init)})
        writes.append({"name": "aircraft.atsu.ground.init", "result": _write_fenix_string("aircraft.atsu.ground.init", "atsuGroundServicesInitMessage", ground_init)})

        try:
            writes.append({"name": "fenix/loadsheet/generate?type=Preliminary", "result": _generate_loadsheet("Preliminary")})
        except Exception as exc:
            writes.append({"name": "fenix/loadsheet/generate?type=Preliminary", "result": {"ok": False, "reason": str(exc)}})

        writes.append({"name": "fenix.efb.simbriefPlanImported", "result": _write_fenix_bool("fenix.efb.simbriefPlanImported", "simbriefPlanImported", True)})
        writes.append({"name": "fenix.efb.boardingStatus", "result": _write_fenix_string("fenix.efb.boardingStatus", "boardingStatus", "inProg")})
        writes.append({"name": "fenix.efb.massBalancePlannedEditable", "result": _write_fenix_bool("fenix.efb.massBalancePlannedEditable", "massBalancePlannedEditable", False)})
        if cargo_kg is not None:
            writes.append({"name": "fenix.efb.plannedCargoKg", "result": _write_fenix_float("fenix.efb.plannedCargoKg", "plannedCargoKg", float(cargo_kg))})

        _LAST_SYNC = {"time": _utc(), "targets": targets, "writes": writes, "sequence": "fenix_normal_gsx_boarding_har"}
        _CACHE = None
        _CACHE_TIME = 0.0
        return {"ok": True, "targets": targets, "writes": writes, "sequence": "fenix_normal_gsx_boarding_har"}
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}", "targets": targets, "writes": writes}




def _iter_leaf_values(value: Any, path: tuple[str, ...] = ()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _iter_leaf_values(child, (*path, str(key)))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            yield from _iter_leaf_values(child, (*path, str(index)))
    else:
        yield path, value


def _numeric_candidates(data: Any, *, required: tuple[str, ...], preferred: tuple[str, ...], exclude: tuple[str, ...] = ()) -> list[tuple[int, float, str]]:
    candidates: list[tuple[int, float, str]] = []
    for path, value in _iter_leaf_values(data):
        key = ".".join(path).lower().replace("_", " ").replace("-", " ")
        if not all(term in key for term in required):
            continue
        if exclude and any(term in key for term in exclude):
            continue
        number = _number(value)
        if number is None:
            continue
        score = sum(3 for term in preferred if term in key) + min(len(key), 120) // 120
        if score <= 0 and preferred:
            continue
        candidates.append((score, float(number), key))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates


def _best_numeric(data: Any, *, required: tuple[str, ...], preferred: tuple[str, ...], exclude: tuple[str, ...] = ()) -> tuple[float | None, str]:
    candidates = _numeric_candidates(data, required=required, preferred=preferred, exclude=exclude)
    if not candidates:
        return None, ""
    _score, value, key = candidates[0]
    return value, key


def loading_progress(plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Best-effort read of Fenix EFB loading progress.

    The Fenix remote payload has changed between builds, so this intentionally
    searches the returned loadsheet recursively and falls back to SimBrief
    targets when current values are unavailable. Unknown values stay None.
    """
    targets = _targets_from_plan(plan or _plan_from_opsroom())
    result: dict[str, Any] = {"ok": False, "targets": targets, "source": "fenix_loadsheet"}
    sheet = loadsheet()
    result["loadsheet"] = {k: v for k, v in sheet.items() if k != "data"}
    if sheet.get("pending"):
        # #114: the portal answered but has not generated a loadsheet yet
        # (Preliminary appears at dispatch/loading start; Final after loading
        # completes). Soft state -- consumers wait on the numeric fields and
        # never treat "not generated yet" as a hard failure.
        result.update({"ok": True, "pending": True,
                       "reason": sheet.get("reason") or "Fenix Preliminary loadsheet not generated yet"})
        return result
    data = sheet.get("data") if sheet.get("ok") else None
    if data is None:
        result["reason"] = sheet.get("reason") or "Fenix loadsheet unavailable"
        return result

    fuel_target = _number(targets.get("fuel_kg"))
    cargo_target = _number(targets.get("cargo_kg"))
    pax_target = _int(targets.get("pax_count"))

    fuel_loaded, fuel_key = _best_numeric(
        data,
        required=("fuel",),
        preferred=("current", "actual", "loaded", "onboard", "on board", "quantity", "total"),
        exclude=("target", "planned", "plan", "required", "speed", "rate"),
    )
    fuel_target_from_efb, fuel_target_key = _best_numeric(
        data,
        required=("fuel",),
        preferred=("target", "planned", "plan", "required"),
        exclude=("speed", "rate"),
    )
    if fuel_target is None and fuel_target_from_efb is not None:
        fuel_target = fuel_target_from_efb

    cargo_loaded, cargo_key = _best_numeric(
        data,
        required=("cargo",),
        preferred=("current", "actual", "loaded", "boarded", "load", "total"),
        exclude=("target", "planned", "plan", "required", "speed", "rate"),
    )
    cargo_target_from_efb, cargo_target_key = _best_numeric(
        data,
        required=("cargo",),
        preferred=("target", "planned", "plan", "required"),
        exclude=("speed", "rate"),
    )
    if cargo_target is None and cargo_target_from_efb is not None:
        cargo_target = cargo_target_from_efb

    pax_loaded, pax_key = _best_numeric(
        data,
        required=("pax",),
        preferred=("current", "actual", "loaded", "boarded", "count", "total"),
        exclude=("target", "planned", "plan", "required"),
    )
    if pax_loaded is None:
        pax_loaded, pax_key = _best_numeric(
            data,
            required=("passenger",),
            preferred=("current", "actual", "loaded", "boarded", "count", "total"),
            exclude=("target", "planned", "plan", "required"),
        )
    pax_target_from_efb, pax_target_key = _best_numeric(
        data,
        required=("pax",),
        preferred=("target", "planned", "plan", "required"),
    )
    if pax_target is None and pax_target_from_efb is not None:
        pax_target = int(round(pax_target_from_efb))

    fuel_target_reached = None
    if fuel_loaded is not None and fuel_target is not None and fuel_target > 0:
        tolerance = max(25.0, fuel_target * 0.01)
        fuel_target_reached = fuel_loaded >= (fuel_target - tolerance)

    aircraft_loaded = False
    try:
        for path, value in _iter_leaf_values(data):
            key = ".".join(path).lower().replace("_", " ").replace("-", " ")
            text = str(value).strip().lower()
            if "aircraft loaded" in key or "aircraft loaded" in text:
                if value is True or text in {"true", "1", "yes", "loaded", "aircraft loaded"} or "aircraft loaded" in text:
                    aircraft_loaded = True
                    break
    except Exception:
        aircraft_loaded = False

    result.update({
        "ok": True,
        "fuel_loaded_kg": None if fuel_loaded is None else round(fuel_loaded, 1),
        "fuel_target_kg": None if fuel_target is None else round(float(fuel_target), 1),
        "fuel_target_reached": fuel_target_reached,
        "aircraft_loaded": aircraft_loaded,
        "cargo_loaded_kg": None if cargo_loaded is None else round(cargo_loaded, 1),
        "cargo_target_kg": None if cargo_target is None else round(float(cargo_target), 1),
        "pax_loaded": None if pax_loaded is None else int(round(pax_loaded)),
        "pax_target": pax_target,
        "keys": {
            "fuel_loaded": fuel_key,
            "fuel_target": fuel_target_key,
            "cargo_loaded": cargo_key,
            "cargo_target": cargo_target_key,
            "pax_loaded": pax_key,
            "pax_target": pax_target_key,
        },
    })
    return result


def start_gsx_boarding(plan: dict[str, Any] | None = None, *, sync_first: bool = True) -> dict[str, Any]:
    targets = _targets_from_plan(plan or _plan_from_opsroom())
    fuel_kg, cargo_kg = targets.get("fuel_kg"), targets.get("cargo_kg")
    if fuel_kg is None and cargo_kg is None:
        raise RuntimeError("No SimBrief fuel/cargo target is available for Fenix GSX loading")
    sync_result: dict[str, Any] | None = None
    if sync_first:
        sync_result = sync_load_targets(plan)
    payload = {
        "Fuel": {"Target": "" if fuel_kg is None else str(int(fuel_kg)), "LoadSpeedPerSecond": 0},
        "Cargo": {"Target": "" if cargo_kg is None else str(int(cargo_kg)), "LoadSpeedPerSecond": 0},
        "UpdateInterval": 0,
    }
    status_code, _text, parsed = _request("POST", "/fenix/tasks/startGsxBoarding", payload, timeout=3.5)
    return {
        "ok": 200 <= status_code < 300,
        "status_code": status_code,
        "payload": payload,
        "targets": targets,
        "sync": sync_result,
        "response": parsed,
        "base_url": _base_url(),
        "mode": "fenix_efb_gsx_loading",
    }
