from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import time

from .data_loader import haversine_nm, load_airports, nearest_airport
from .phase_machine import holding_phase, transition_allowed
from .settings_store import load_settings
from .simbrief_client import cached_plan
from .telemetry_provider import read_telemetry

_LAST_LIVE: dict[str, Any] | None = None
_LAST_LIVE_TIME = 0.0

# #42: display-only pushback latch. Mirrors the logbook phase-ordering
# invariant: the aircraft cannot taxi before off blocks, so ground movement out
# of PARKED is shown as PUSHBACK until genuine taxi proof (sustained >10 kt)
# or parking brakes set. Fenix exposes no body-vx and mirrors heading into
# track, so the dedicated GSX/backward-motion signals stay blind.
_FW_PHASE_STATE: dict[str, Any] = {"phase": None, "pushback": False}
_FW_LOADING_RESET_WINDOW = 8.0  # #85: sim-reload stale window before state reset


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _altitude_reliable(telemetry: dict[str, Any]) -> bool:
    if telemetry.get("altitude_unreliable") is True:
        return False
    if str(telemetry.get("altitude_confidence") or "").lower() in {"invalid", "unreliable"}:
        return False
    alt = _number(telemetry.get("indicated_altitude_ft")) or _number(telemetry.get("altitude_ft"))
    agl = _number(telemetry.get("radio_altitude_ft")) or _number(telemetry.get("agl_ft"))
    gs = _number(telemetry.get("ground_speed_kts")) or 0.0
    ias = _number(telemetry.get("indicated_speed_kts")) or 0.0
    if alt is None:
        return False
    if agl is not None and agl > 1000 and (gs > 100 or ias > 100) and (abs(alt) < 500 or alt + 1000 < agl):
        return False
    return True


def _gsx_pushback_active() -> bool:
    """Dedicated GSX pushback evidence (v0.25.72, #12).

    Mirrors the logbook detector: only the dedicated ``pushback`` service row
    counts as physical pushback evidence (the broad ``departure`` workflow is
    deliberately never consulted), and completed/disconnected tug states are
    explicit clears. Memoized for 1 s so the per-poll phase evaluation does not
    hammer the GSX status IPC.
    """
    _md = getattr(_gsx_pushback_active, "_memo", None)
    if _md is not None and (time.monotonic() - _md[0]) < 1.0:
        return _md[1]
    value = _gsx_pushback_active_inner()
    setattr(_gsx_pushback_active, "_memo", (time.monotonic(), value))
    return value


def _gsx_pushback_active_inner() -> bool:
    try:
        from .gsx_remote import status as gsx_status
        gsx = gsx_status(force=False)
    except Exception:
        return False
    if not gsx.get("ok") or not gsx.get("connected"):
        return False
    row = (gsx.get("services") or {}).get("pushback")
    if not isinstance(row, dict):
        return False
    try:
        raw = int(row.get("raw") or 0)
    except Exception:
        raw = 0

    def token(value: Any) -> str:
        return str(value or "").strip().upper().replace("-", "_").replace(" ", "_")

    states = {token(row.get("state")), token(row.get("remote_state"))}
    if states & {"COMPLETE", "COMPLETED", "FINISHED", "DISCONNECTED", "TUG_DISCONNECTED", "CLEAR", "CLEARED"}:
        return False
    if states & {"ACTIVE", "PERFORMING", "IN_PROGRESS"}:
        return True
    return bool(raw == 5 and str(row.get("source") or "").lower() == "official-remote-api-v2")


def _phase(telemetry: dict[str, Any], plan: dict[str, Any] | None) -> str:
    on_ground = bool(telemetry.get("on_ground"))
    gs = _number(telemetry.get("ground_speed_kts")) or 0.0
    vs = _number(telemetry.get("vertical_speed_fpm")) or 0.0
    agl = _number(telemetry.get("agl_ft"))
    altitude = (_number(telemetry.get("indicated_altitude_ft")) or _number(telemetry.get("altitude_ft")) or 0.0) if _altitude_reliable(telemetry) else 0.0
    cruise = _number((plan or {}).get("cruise_altitude_ft")) or 0.0
    prev_phase = _FW_PHASE_STATE.get("phase")

    if on_ground:
        # #42: the display mirror of the logbook phase-ordering invariant.
        gsx_push = _gsx_pushback_active() and gs <= 10.0
        if gsx_push:
            _FW_PHASE_STATE["pushback"] = True
        latched = bool(_FW_PHASE_STATE.get("pushback"))
        if latched:
            # Genuine taxi proof: sustained >10 kt (a tug stays below the
            # envelope; the RJA403 recording shows 10-12 kt spikes while the tug
            # turns, so a single spike never clears the latch).
            if gs > 10.0:
                _FW_PHASE_STATE["high_gs_polls"] = int(_FW_PHASE_STATE.get("high_gs_polls") or 0) + 1
                if _FW_PHASE_STATE["high_gs_polls"] >= 4:
                    latched = False
                    _FW_PHASE_STATE["pushback"] = False
                    _FW_PHASE_STATE["high_gs_polls"] = 0
            else:
                _FW_PHASE_STATE["high_gs_polls"] = 0
            if latched and telemetry.get("parking_brake") is True:
                # Movement -> stop -> brakes set = pushback complete.
                latched = False
                _FW_PHASE_STATE["pushback"] = False
                _FW_PHASE_STATE["high_gs_polls"] = 0
        if latched:
            _FW_PHASE_STATE["phase"] = "PUSHBACK"
            return "PUSHBACK"
        # Movement out of PARKED before taxi proof is pushback (ordering
        # invariant — Fenix blind spot: no body-vx, track == heading).
        if gs >= 1.0 and (prev_phase == "PARKED" or prev_phase is None):
            _FW_PHASE_STATE["pushback"] = True
            _FW_PHASE_STATE["phase"] = "PUSHBACK"
            return "PUSHBACK"
        if gs < 2.0:
            _FW_PHASE_STATE["phase"] = "PARKED"
            # #85: once parked at the gate after arrival, drop the airborne
            # latch so the NEXT departure classifies normally again. A 90 s
            # stop with the brake set is the "arrived" signature.
            if _FW_PHASE_STATE.get("airborne_seen"):
                _FW_PHASE_STATE["gate_parked_at"] = _FW_PHASE_STATE.get("gate_parked_at") or time.time()
                if telemetry.get("parking_brake") is True and time.time() - _FW_PHASE_STATE["gate_parked_at"] >= 90.0:
                    _FW_PHASE_STATE["airborne_seen"] = False
                    _FW_PHASE_STATE.pop("gate_parked_at", None)
            return "PARKED"
        _FW_PHASE_STATE.pop("gate_parked_at", None)
        # #85: after the aircraft has been airborne, on-ground movement is the
        # landing roll / taxi-in — NEVER TAKEOFF ROLL (FFT1011 showed the
        # display calling the landing rollout TAKEOFF ROLL because this machine
        # had no LANDING concept).
        if _FW_PHASE_STATE.get("airborne_seen"):
            phase = "LANDING ROLL" if gs >= 40 else "TAXI IN"
            _FW_PHASE_STATE["phase"] = phase
            return phase
        if gs > 5.0:
            phase = "TAXI" if gs < 35 else "TAKEOFF ROLL"
            _FW_PHASE_STATE["phase"] = phase
            return phase
        if gs < 35:
            _FW_PHASE_STATE["phase"] = "TAXI"
            return "TAXI"
        _FW_PHASE_STATE["phase"] = "TAKEOFF ROLL"
        return "TAKEOFF ROLL"
    # Airborne: the departure latch must not leak into arrival taxi-in.
    _FW_PHASE_STATE["pushback"] = False
    _FW_PHASE_STATE["high_gs_polls"] = 0
    _FW_PHASE_STATE["airborne_seen"] = True
    # #66: once ENROUTE/CRUISE is settled, never bounce back to CLIMB. The
    # climb detector keeps firing for minutes after a slow top-of-climb (vs
    # stays >250 while the aircraft slowly approaches cruise) which produced a
    # stream of rejected ENROUTE -> CLIMB transitions on EWG5EZ. Only a genuine
    # climb excursion (strong sustained climb well below cruise) may re-propose.
    settled_upper = prev_phase in ("ENROUTE", "CRUISE")
    if agl is not None and agl < 1500 and vs > 150:
        proposal = "INITIAL CLIMB"
    elif agl is not None and agl < 2500 and vs < -150:
        proposal = "APPROACH"
    elif cruise and altitude < cruise - 1500 and vs > 250:
        proposal = (prev_phase or "ENROUTE") if (settled_upper and not (vs > 900 and altitude < cruise - 3000)) else "CLIMB"
    elif vs < -300:
        proposal = "DESCENT" if agl is None or agl > 3500 else "APPROACH"
    elif altitude > 10000 and abs(vs) < 350:
        proposal = "CRUISE"
    elif vs > 250:
        proposal = (prev_phase or "ENROUTE") if (settled_upper and not (vs > 900 and altitude < cruise - 3000)) else "CLIMB"
    else:
        proposal = "ENROUTE"
    # #85: acceptance layer — only legal transitions update the displayed
    # phase (kills the ENROUTE-on-short-final and post-descent CLIMB flickers).
    return holding_phase(prev_phase, proposal, _FW_PHASE_STATE)


def build_flight_watch(force: bool = False) -> dict[str, Any]:
    global _LAST_LIVE, _LAST_LIVE_TIME
    telemetry = read_telemetry(force=force)
    settings = load_settings()
    user_ref = str(settings.get("identity", {}).get("simbrief_user_id") or "")
    plan = cached_plan(user_ref) if user_ref else None
    if not telemetry.get("ok"):
        # #85: a sim reload (loading screen / menu state) is a fresh-flight
        # boundary — drop the airborne latch so the NEXT departure is not
        # misread as a landing roll. Brief stale blips (stale-hold below)
        # intentionally do NOT reset.
        if telemetry.get("simulator_loading") or int(telemetry.get("simulator_menu_state") or 0):
            _FW_PHASE_STATE.clear()
            _FW_PHASE_STATE.update({"phase": None, "pushback": False})
        age = time.monotonic() - _LAST_LIVE_TIME if _LAST_LIVE_TIME else 999.0
        if _LAST_LIVE is not None and age <= 8.0:
            held = dict(_LAST_LIVE)
            held["state"] = "stale"
            held["stale"] = True
            held["stale_seconds"] = round(age, 1)
            held["reason"] = telemetry.get("reason", "Brief SimConnect interruption")
            held["updated_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            return held
        return {
            "ok": False,
            "state": "standby",
            "reason": telemetry.get("reason", "SimConnect is not available"),
            "telemetry": telemetry,
        "telemetry_quality": {"altitude_reliable": _altitude_reliable(telemetry), "altitude_source": telemetry.get("altitude_source"), "altitude_confidence": telemetry.get("altitude_confidence")},
            "plan": plan,
            "updated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    lat = float(telemetry["lat"])
    lon = float(telemetry["lon"])
    airports = load_airports()
    origin_code = str((plan or {}).get("origin", {}).get("icao") or "").upper()
    destination_code = str((plan or {}).get("destination", {}).get("icao") or "").upper()
    origin = airports.get(origin_code)
    destination = airports.get(destination_code)
    direct_nm = None
    remaining_nm = None
    progress = None
    eta_utc = None
    gs = _number(telemetry.get("ground_speed_kts")) or 0.0

    if origin and destination:
        direct_nm = haversine_nm(origin.lat, origin.lon, destination.lat, destination.lon)
        remaining_nm = haversine_nm(lat, lon, destination.lat, destination.lon)
        if direct_nm > 1:
            progress = max(0.0, min(1.0, 1.0 - remaining_nm / direct_nm))
        if gs >= 50:
            eta_utc = (datetime.now(timezone.utc) + timedelta(hours=remaining_nm / gs)).isoformat().replace("+00:00", "Z")

    nearest = nearest_airport(lat, lon)
    phase = _phase(telemetry, plan)
    result = {
        "ok": True,
        "state": "live",
        "stale": False,
        "phase": phase,
        "telemetry": telemetry,
        "telemetry_quality": {"altitude_reliable": _altitude_reliable(telemetry), "altitude_source": telemetry.get("altitude_source"), "altitude_confidence": telemetry.get("altitude_confidence")},
        "nearest_airport": {"icao": nearest[0].ident, "distance_nm": round(nearest[1], 1)} if nearest else None,
        "flight": {
            "callsign": (plan or {}).get("callsign"),
            "origin": origin_code or None,
            "destination": destination_code or None,
            "cruise_altitude_ft": (plan or {}).get("cruise_altitude_ft"),
            "planned_distance_nm": (plan or {}).get("distance_nm"),
            "direct_distance_nm": round(direct_nm, 1) if direct_nm is not None else None,
            "remaining_nm": round(remaining_nm, 1) if remaining_nm is not None else None,
            "progress": round(progress, 4) if progress is not None else None,
            "eta_utc": eta_utc,
        },
        "updated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _LAST_LIVE = result
    _LAST_LIVE_TIME = time.monotonic()
    return result
