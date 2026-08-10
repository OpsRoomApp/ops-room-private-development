from __future__ import annotations

import logging
import math
import os
import queue
import re
import subprocess
import threading
import time
from typing import Any

try:
    from .raas_audio import start as _raas_audio_start, queue_callout as _raas_queue_callout, status as _raas_audio_status, set_voice_path as _raas_audio_set_voice_path
except Exception as _raas_audio_import_exc:
    # RAAS must continue to run visually even if the optional host-audio helper
    # fails during startup.
    _AUDIO_IMPORT_MESSAGE = f"RAAS audio import failed: {type(_raas_audio_import_exc).__name__}: {_raas_audio_import_exc}"
    _AUDIO_LOCK = threading.RLock()
    _AUDIO_QUEUE: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=20)
    _AUDIO_THREAD: threading.Thread | None = None
    _AUDIO_RUNNING = False
    _AUDIO_LAST: dict[str, Any] = {"ok": True, "state": "DISPLAY_ONLY", "message": _AUDIO_IMPORT_MESSAGE, "mode": "fallback", "audio_import_error": _AUDIO_IMPORT_MESSAGE}

    def _fallback_tts(text: str) -> bool:
        if os.name != "nt":
            return False
        clean = str(text or "").replace("'", "''")[:180]
        if not clean:
            return False
        script = (
            "try { Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.Rate = -1; $s.Volume = 100; "
            f"$s.Speak('{clean}'); $s.Dispose(); exit 0 }} catch {{ exit 1 }}"
        )
        try:
            result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=12, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return result.returncode == 0
        except Exception:
            return False

    def _raas_audio_start() -> dict[str, Any]:
        return _raas_audio_status()

    def _raas_queue_callout(text: str, event_type: str = "callout", runway: str = "", distance_ft: int | None = None, priority: str = "advisory", distance_value: int | None = None, distance_unit: str = "feet") -> dict[str, Any]:
        spoken = _fallback_tts(str(text or "RAAS"))
        with _AUDIO_LOCK:
            _AUDIO_LAST.update({"state": "PLAYED" if spoken else "DISPLAY_ONLY", "message": str(text or "RAAS"), "event_type": event_type, "priority": priority, "distance_value": distance_value, "distance_unit": distance_unit, "audio_import_error": _AUDIO_IMPORT_MESSAGE})
        return {"ok": True, "queued": False, "audio": _raas_audio_status()}

    def _raas_audio_status() -> dict[str, Any]:
        with _AUDIO_LOCK:
            data = dict(_AUDIO_LAST)
        data.setdefault("voice_pack_status", {"available": False, "message": _AUDIO_IMPORT_MESSAGE, "clip_count": 0, "audio_backend_status": {"tts": "fallback Windows System.Speech" if os.name == "nt" else "display-only outside Windows"}})
        data["thread_running"] = False
        data["queue_depth"] = 0
        return data

    def _raas_audio_set_voice_path(path: str) -> dict[str, Any]:
        # If app.raas_audio failed to import, still persist the path so a
        # restart or fixed package can pick it up. Do not silently ignore SET FOLDER.
        try:
            from .settings_store import load_settings, save_settings
            settings = load_settings()
            settings.setdefault("integrations", {})["raas_voice_path"] = str(path or "").strip().strip('"')
            save_settings(settings)
        except Exception:
            pass
        return _raas_audio_status()

from .navdata import available as navdata_available, project_local, runway_ends_near
from .telemetry_provider import read_telemetry, telemetry_diagnostics
from . import notam_client  # v0.25.65: NOTAM runway-closure cross-reference
from . import notam_translate  # v0.25.65: closure keyword check

_LOG = logging.getLogger("opsroom.raas")

_LOCK = threading.RLock()
_RUNNING = False
_THREAD: threading.Thread | None = None
_ENABLED = True
_LAST_STATUS: dict[str, Any] = {
    "ok": True,
    "state": "STANDBY",
    "display": "RAAS-STBY",
    "message": "Runway monitor engine not started",
    "last_callout": "",
    "active_runway": "",
    "source_priority": "FSUIPC7 FIRST / SIMCONNECT FALLBACK",
}
_LAST_CALLOUT_AT: dict[str, float] = {}
_LAST_TOAST_ID = 0
_LAST_RUNWAY_ON = ""
_LAST_APPROACH_RUNWAY = ""
_REMAINING_THRESHOLDS_FT = [5000, 3000, 1000]
_REMAINING_THRESHOLDS_M = [1500, 1000, 300]
_REMAINING_SPOKEN: set[tuple[str, str, int]] = set()
_LAST_GEOM: dict[str, tuple[float, float, float]] = {}
_AIRBORNE_FINAL_RUNWAYS: set[str] = set()
_EVENT_SPOKEN: dict[str, float] = {}
_RUNWAY_END_LOCK: dict[str, Any] = {}
_RUNWAY_ENCOUNTERS: dict[str, dict[str, Any]] = {}
_GROUND_ALERTS_SUPPRESSED = False
_WAS_ON_GROUND = True
_LAST_LOOP_LAG_MS = 0.0
_RUNWAY_SESSION: dict[str, Any] = {"state": "TAXI_GROUND", "strip": "", "runway": "", "cooldown_until": 0.0, "last_ground": True, "last_inside": False}
_ACTIVE_SESSION_ARMED = False
_ACTIVE_SESSION_FIRST_VALID = 0.0
_ACTIVE_SESSION_LAST_POS: tuple[float, float, float] | None = None
RAAS_FAST_HZ = 20.0
RAAS_FAST_INTERVAL = 1.0 / RAAS_FAST_HZ
RAAS_UI_HZ = 10.0
TRACK_VALID_MIN_GS_KT = 10.0
TAXI_MOVING_MIN_GS_KT = 5.0
GROUND_APPROACH_CROSS_LIMIT_FT = 450.0
GROUND_APPROACH_EDGE_DISTANCE_FT = 300.0
GROUND_APPROACH_ENTRY_THRESHOLD_FT = 2700.0
GROUND_APPROACH_ALERT_EARLY_FT = 135.0
ON_RUNWAY_EDGE_MARGIN_FT = 15.0
CLEAR_RUNWAY_MARGIN_FT = 100.0
VACATED_COOLDOWN_SECONDS = 16.0


def _update_runway_session(*, on_ground: bool, inside: bool, approaching: bool, airborne_approach: bool, strip: str, runway: str, gs: float, now: float) -> dict[str, Any]:
    """Track taxi-out versus landing/vacating runway encounters.

    The callouts still use existing geometry, but this session layer suppresses
    fresh APP/ON calls while the aircraft is vacating after landing. That stops
    runway-exit geometry from being treated as a brand-new taxi-out entry.
    """
    state = str(_RUNWAY_SESSION.get("state") or "TAXI_GROUND")
    last_ground = bool(_RUNWAY_SESSION.get("last_ground", True))
    same_strip = bool(strip and strip == _RUNWAY_SESSION.get("strip"))
    suppress_entry_callouts = False

    # A ground transition while already inside a runway is touchdown/rollout, not
    # taxi-out runway entry. Keep this locked to the physical strip until clear.
    if (not last_ground) and on_ground and inside and runway:
        state = "LANDING_ROLLOUT"
        _RUNWAY_SESSION.update({"strip": strip, "runway": runway, "cooldown_until": 0.0})

    if on_ground:
        if state == "LANDING_ROLLOUT" and not inside:
            state = "VACATING_RUNWAY"
            _RUNWAY_SESSION["cooldown_until"] = now + VACATED_COOLDOWN_SECONDS
        elif state in {"VACATING_RUNWAY", "VACATED_COOLDOWN"}:
            suppress_entry_callouts = True
            if not inside:
                state = "VACATED_COOLDOWN"
            if now >= float(_RUNWAY_SESSION.get("cooldown_until") or 0.0) and not inside and not approaching:
                state = "TAXI_GROUND"
                _RUNWAY_SESSION.update({"strip": "", "runway": "", "cooldown_until": 0.0})
                suppress_entry_callouts = False
        elif state == "TAKEOFF_ROLL" and not inside and gs < 45:
            state = "TAXI_GROUND"

        if state == "TAXI_GROUND":
            if approaching and runway:
                state = "APPROACHING_ENTRY"
                _RUNWAY_SESSION.update({"strip": strip, "runway": runway})
            elif inside and runway:
                state = "ON_RUNWAY"
                _RUNWAY_SESSION.update({"strip": strip, "runway": runway})
        elif state == "APPROACHING_ENTRY" and inside:
            state = "ON_RUNWAY"
        elif state == "ON_RUNWAY" and gs >= 55.0:
            state = "TAKEOFF_ROLL"
    else:
        if airborne_approach:
            state = "FINAL"
            _RUNWAY_SESSION.update({"strip": strip, "runway": runway})
        elif state == "TAKEOFF_ROLL":
            # After takeoff, old ground entry state must not drive taxi callouts.
            _RUNWAY_SESSION.update({"strip": "", "runway": "", "cooldown_until": 0.0})

    if state in {"VACATING_RUNWAY", "VACATED_COOLDOWN"} and (same_strip or not strip or approaching or inside):
        suppress_entry_callouts = True

    _RUNWAY_SESSION.update({
        "state": state,
        "last_ground": bool(on_ground),
        "last_inside": bool(inside),
    })
    return {
        "state": state,
        "suppress_entry_callouts": bool(suppress_entry_callouts),
        "cooldown_remaining_seconds": max(0.0, float(_RUNWAY_SESSION.get("cooldown_until") or 0.0) - now),
        "strip": _RUNWAY_SESSION.get("strip") or strip,
        "runway": _RUNWAY_SESSION.get("runway") or runway,
    }


def _raas_unit_pref() -> str:
    """Return the RAAS presentation unit without changing internal geometry.

    RAAS calculations remain in feet. This preference only controls cockpit
    display text, remaining-distance thresholds, and the spoken distance unit.
    """
    try:
        from .settings_store import load_settings
        settings = load_settings()
        integrations = settings.get("integrations", {}) or {}
        configured = str(integrations.get("raas_unit") or "").strip().lower()
        if configured in {"m", "meter", "meters", "metre", "metres"}:
            return "m"
        if configured in {"ft", "feet", "foot"}:
            return "ft"
        units = (settings.get("interface", {}) or {}).get("units", {}) or {}
        altitude = str(units.get("altitude") or "ft").lower()
        return "m" if altitude in {"m", "meter", "meters", "metre", "metres"} else "ft"
    except Exception:
        return "ft"


def _raas_unit_code() -> str:
    return "M" if _raas_unit_pref() == "m" else "FT"


def _raas_spoken_unit() -> str:
    return "meters" if _raas_unit_pref() == "m" else "feet"


def _raas_ok_code() -> str:
    return f"RAAS-OK-{_raas_unit_code()}"


def _remaining_thresholds() -> list[tuple[float, int, str, str]]:
    if _raas_unit_pref() == "m":
        return [(metres / 0.3048, metres, "M", "meters") for metres in _REMAINING_THRESHOLDS_M]
    return [(float(feet), feet, "FT", "feet") for feet in _REMAINING_THRESHOLDS_FT]


def _num(value: Any, fallback: float | None = None) -> float | None:
    try:
        n = float(value)
        return n if math.isfinite(n) else fallback
    except (TypeError, ValueError):
        return fallback


def _heading_delta(a: float | None, b: float | None) -> float:
    if a is None or b is None:
        return 999.0
    return abs(((float(a) - float(b) + 180.0) % 360.0) - 180.0)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))



def _metric(item: dict[str, Any], key: str, default: float = 999999.0) -> float:
    value = _num(item.get(key), None)
    return default if value is None else value


def _clean_runway_ident(value: Any) -> str:
    return str(value or "").upper().replace("RUNWAY", "").replace("RWY", "").replace("RW", "").strip()


def _planned_matches(planned: str, runway: str) -> bool:
    p = _clean_runway_ident(planned)
    r = _clean_runway_ident(runway)
    if not p or not r:
        return False
    return p == r or p.zfill(2) == r.zfill(2)


def _effective_direction(track: float, heading: float, gs: float) -> tuple[float, str, bool]:
    if gs >= TRACK_VALID_MIN_GS_KT:
        return track % 360.0, "ground_track", True
    return heading % 360.0, "aircraft_heading_low_speed", False


def _session_gate(tel: dict[str, Any], lat: float, lon: float, now: float) -> tuple[bool, str]:
    """Guard against menu/loading/pre-spawn samples without blocking parked aircraft."""
    global _ACTIVE_SESSION_ARMED, _ACTIVE_SESSION_FIRST_VALID, _ACTIVE_SESSION_LAST_POS
    if bool(tel.get("slew_active")):
        _ACTIVE_SESSION_ARMED = False
        _ACTIVE_SESSION_FIRST_VALID = 0.0
        return False, "Slew mode active"
    if bool(tel.get("paused")):
        _ACTIVE_SESSION_ARMED = False
        _ACTIVE_SESSION_FIRST_VALID = 0.0
        return False, "Simulator paused/loading"
    sim_rate = _num(tel.get("sim_rate"), 1.0) or 1.0
    if sim_rate <= 0.01:
        _ACTIVE_SESSION_ARMED = False
        _ACTIVE_SESSION_FIRST_VALID = 0.0
        return False, "Simulator rate is zero"
    # MSFS menu/loading defaults to DGTK (Dibba, Oman). Reject when on ground
    # within 5 NM of that position to prevent false RAAS callouts.
    if bool(tel.get("on_ground")):
        dgtk_ft = math.hypot((lat - 25.618) * 60.0 * 6076.12, (lon - 56.242) * 60.0 * 6076.12 * math.cos(math.radians((lat + 25.618) / 2.0)))
        if dgtk_ft < 30380.0:
            _ACTIVE_SESSION_ARMED = False
            _ACTIVE_SESSION_FIRST_VALID = 0.0
            return False, "MSFS menu/loading position (DGTK)"
    if _ACTIVE_SESSION_ARMED:
        return True, "armed"
    # Arm only after a short period of stable, valid user-aircraft position.
    last = _ACTIVE_SESSION_LAST_POS
    if not last:
        _ACTIVE_SESSION_LAST_POS = (lat, lon, now)
        _ACTIVE_SESSION_FIRST_VALID = now
        return False, "Waiting for stable active-flight position"
    prev_lat, prev_lon, prev_t = last
    moved_ft = math.hypot((lat - prev_lat) * 60.0 * 6076.12, (lon - prev_lon) * 60.0 * 6076.12 * math.cos(math.radians((lat + prev_lat) / 2.0)))
    if moved_ft > 5000.0:
        _ACTIVE_SESSION_LAST_POS = (lat, lon, now)
        _ACTIVE_SESSION_FIRST_VALID = now
        return False, "Position settling after spawn/location jump"
    if now - _ACTIVE_SESSION_FIRST_VALID >= 1.25:
        _ACTIVE_SESSION_ARMED = True
        return True, "armed after stable position"
    return False, "Waiting for active flight session"


def _set_status(**values: Any) -> None:
    global _LAST_STATUS
    with _LOCK:
        previous = dict(_LAST_STATUS)
        now = time.monotonic()
        # Preserve the active callout display for a few seconds. The analysis
        # loop runs much faster than the UI and used to overwrite APP/ON/REM
        # visual messages immediately after audio queued.
        if "display" in values and previous.get("display_expires_at") and now < float(previous.get("display_expires_at") or 0.0):
            values["display"] = previous.get("display")
        merged = previous
        merged.update(values)
        merged["updated_at_monotonic"] = now
        _LAST_STATUS = merged


def _compact_callout_display(text: str, event_type: str, runway: str = "", distance_ft: int | None = None, distance_value: int | None = None, distance_unit: str = "") -> str:
    typ = str(event_type or "").lower()
    rwy = str(runway or "").upper().strip()
    if typ == "test":
        return _raas_ok_code()
    if typ == "approaching_runway" and rwy:
        return f"APP RWY {rwy}"
    if typ == "on_runway" and rwy:
        return f"ON RWY {rwy}"
    if typ == "taxiway_takeoff":
        return "CAUT TWY"
    if typ == "short_runway":
        return "SHORT RWY"
    if typ == "remaining" and (distance_value is not None or distance_ft is not None):
        unit = str(distance_unit or _raas_unit_code()).upper()
        if unit not in {"FT", "M"}:
            unit = _raas_unit_code()
        if distance_value is None:
            raw_ft = float(distance_ft or 0)
            distance_value = int(round(raw_ft * 0.3048)) if unit == "M" else int(round(raw_ft))
        return f"{int(distance_value)} {unit} REM"
    if typ == "too_high":
        return "TOO HIGH"
    if typ == "too_fast":
        return "TOO FAST"
    if typ == "unstable":
        return "UNSTABLE"
    if typ == "long_landing":
        return "LONG LAND"
    if typ == "deep_landing":
        return "DEEP LAND"
    return str(text or "RAAS").upper()


def _callout(text: str, event_type: str, *, runway: str = "", distance_ft: int | None = None, distance_value: int | None = None, distance_unit: str = "", priority: str = "advisory", cooldown: float = 8.0, suppress_center_toast: bool = False) -> None:
    global _LAST_TOAST_ID
    key = f"{event_type}:{runway}:{distance_ft or ''}:{distance_value or ''}:{distance_unit or ''}"
    now = time.monotonic()
    if now - _LAST_CALLOUT_AT.get(key, 0.0) < cooldown:
        return
    _LAST_CALLOUT_AT[key] = now
    _LAST_TOAST_ID += 1
    event_id = f"raas-{_LAST_TOAST_ID}"
    created_epoch = time.time()
    spoken_unit = "meters" if str(distance_unit).upper() == "M" else ("feet" if str(distance_unit).upper() == "FT" else _raas_spoken_unit())
    _raas_queue_callout(text, event_type=event_type, runway=runway, distance_ft=distance_ft, priority=priority, distance_value=distance_value, distance_unit=spoken_unit)
    # v0.25.65: NOTAM cross-reference -- ADD-ONLY. When the aircraft is on or
    # approaching a runway, check whether an active NOTAM closes it and fire
    # an extra warning. Never suppresses or replaces an existing callout.
    if event_type in ("on_runway", "approaching_runway") and runway:
        _maybe_notam_closure_callout(str(runway))
    compact = _compact_callout_display(text, event_type, runway=runway, distance_ft=distance_ft, distance_value=distance_value, distance_unit=distance_unit)
    _set_status(last_callout=text, last_callout_type=event_type, last_callout_priority=priority, last_callout_runway=runway, last_callout_distance_ft=distance_ft, last_callout_distance_value=distance_value, last_callout_unit=(distance_unit or _raas_unit_code()).upper(), toast_id=_LAST_TOAST_ID, raas_event_id=event_id, raas_event_created_epoch=created_epoch, raas_event_active=True, raas_event_log=[f"RAAS_EVENT_CREATED id={event_id}", f"RAAS_AUDIO_QUEUED id={event_id}", f"RAAS_VISUAL_UPDATED id={event_id}"], display=compact, display_expires_at=now + (2.5 if suppress_center_toast else 5.5), suppress_center_toast=bool(suppress_center_toast), client_audio_required=False)


def _runway_name(rwy: dict[str, Any] | None) -> str:
    return str((rwy or {}).get("runway") or "").upper().strip()


def _strip_key(rwy: dict[str, Any] | None) -> str:
    """Stable key for the physical runway strip, independent of selected end."""
    item = rwy or {}
    airport = str(item.get("airport_ident") or item.get("airport") or "").upper().strip()
    names = [
        str(item.get("primary_end_name") or item.get("name_a") or "").upper().strip(),
        str(item.get("secondary_end_name") or item.get("name_b") or "").upper().strip(),
    ]
    names = sorted(x for x in names if x)
    if names:
        return f"{airport}:{'/'.join(names)}"
    return f"{airport}:{_runway_name(item)}"


# ── v0.25.65: NOTAM runway-closure cross-reference (ADD-ONLY) ──────────────
# Determines whether an active NOTAM closes the runway the aircraft is on or
# approaching, and fires an extra warning callout. This integration can only
# ADD a warning -- a missed match must never change RAAS's existing logic.

_NOTAM_CLOSURE_CACHE: dict[str, tuple[float, bool, str, str]] = {}
_NOTAM_CLOSURE_LOCK = threading.Lock()
_NOTAM_CLOSURE_TTL = 900.0  # 15 minutes -- plenty for a taxi/approach phase

# v0.25.72 (#17): once a closure NOTAM has been announced for a physical
# runway strip, it is never announced again until the closure clears (or a
# new NOTAM appears). Keyed by ``airport:physical-strip`` -> announced notam
# id, so 26L then 26R of the same closed runway share one latch.
_NOTAM_ANNOUNCED: dict[str, str] = {}


def _closure_announce_key(airport: str, runway: str) -> str:
    """Physical-strip key for the announced latch (26L/26R/08/26 -> one key)."""
    strip = str(_RUNWAY_SESSION.get("strip") or "")
    if ":" in strip and str(strip).split(":", 1)[0] == str(airport or "").upper().strip():
        return strip
    return f"{str(airport or '').upper().strip()}:{str(runway or '').rstrip('LRC')}"


def _runway_tokens(text_upper: str) -> list[str]:
    """Extract runway identifiers from raw NOTAM text (e.g. RWY 26L, 08L/26R)."""
    return re.findall(r"\bRWY\s*([0-9]{1,2}[LRC]?(?:/[0-9]{1,2}[LRC]?)?)\b", text_upper)


def _runway_matches(token: str, runway: str) -> bool:
    """Does a NOTAM runway token refer to the same physical runway as ours?"""
    token = token.upper()
    runway = runway.upper()
    parts = [part.strip() for part in token.split("/") if part.strip()]
    base = runway.rstrip("LRC")
    if runway in parts:
        return True
    return any(part.rstrip("LRC") == base for part in parts)


def _notam_runway_closed(airport: str, runway: str) -> tuple[bool, str, str]:
    """Best-effort: is there an active closure NOTAM for this runway?

    Returns ``(matched, notam_id, detail)`` — the NOTAM id is the stable
    closure identity the announced-latch keys on (v0.25.72, #17).
    """
    airport = str(airport or "").upper().strip()
    runway = str(runway or "").upper().strip()
    if len(airport) != 4 or not runway:
        return False, "", ""
    key = f"{airport}:{runway}"
    with _NOTAM_CLOSURE_LOCK:
        hit = _NOTAM_CLOSURE_CACHE.get(key)
        if hit and time.time() - hit[0] <= _NOTAM_CLOSURE_TTL:
            return bool(hit[1]), hit[2], hit[3]
    matched = False
    notam_id = ""
    detail = ""
    try:
        package = notam_client.get_notams(airport)
        for row in package.get("notams") or []:
            text = str(row.get("text") or "").upper()
            if not notam_translate.is_closure_notam(text):
                continue
            if any(_runway_matches(token, runway) for token in _runway_tokens(text)):
                matched = True
                notam_id = str(row.get("id") or row.get("number") or row.get("nms_id") or "").strip()
                detail = str(row.get("text") or "")
                break
    except Exception as exc:
        _LOG.debug("RAAS NOTAM check failed for %s: %s", airport, exc)
    with _NOTAM_CLOSURE_LOCK:
        _NOTAM_CLOSURE_CACHE[key] = (time.time(), matched, notam_id, detail)
    if matched:
        # Inspectable match log -- this is exactly the feature that needs
        # real-world regex tuning after launch.
        _LOG.info("RAAS NOTAM cross-ref: RWY %s at %s closed per NOTAM: %s", runway, airport, detail[:200])
    return matched, notam_id, detail


def _notam_callouts_enabled() -> bool:
    """v0.25.65: spoken NOTAM closure call-outs on/off (default on)."""
    try:
        from .settings_store import load_settings

        integrations = load_settings().get("integrations", {}) or {}
        return bool(integrations.get("raas_notam_callouts", True))
    except Exception:
        return True


def _maybe_notam_closure_callout(runway: str) -> None:
    """Run the closure check off the RAAS loop so callouts never stall on
    network I/O, then fire the add-on warning in a daemon thread. The spoken
    call-out is short by design ("RUNWAY CLOSED PER NOTAM") and can be
    disabled via the ``raas_notam_callouts`` setting."""
    def _worker() -> None:
        try:
            if not _notam_callouts_enabled():
                return
            strip = str(_RUNWAY_SESSION.get("strip") or "")
            airport = strip.split(":", 1)[0] if ":" in strip else ""
            closed, notam_id, _detail = _notam_runway_closed(airport, runway)
            # v0.25.72 (#17): announce once per closure NOTAM per physical
            # runway strip. Re-arm only when the closure clears or the NOTAM id
            # changes (a new/updated closure). 26L then 26R of the same closed
            # strip can never announce twice.
            announce_key = _closure_announce_key(airport, runway)
            if closed:
                if _NOTAM_ANNOUNCED.get(announce_key) != notam_id:
                    _callout("RUNWAY CLOSED PER NOTAM", "notam_runway_closed", runway=runway, priority="warning", cooldown=600.0)
                    _NOTAM_ANNOUNCED[announce_key] = notam_id
            else:
                _NOTAM_ANNOUNCED.pop(announce_key, None)
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True).start()


def _encounter_key(rwy: dict[str, Any] | None) -> str:
    return f"{_strip_key(rwy)}:{_runway_name(rwy)}"


def _encounter_for(rwy: dict[str, Any], now: float) -> dict[str, Any]:
    key = _encounter_key(rwy)
    enc = _RUNWAY_ENCOUNTERS.setdefault(key, {"approach": False, "on": False, "created": now, "last_seen": now, "clear_since": 0.0})
    enc["last_seen"] = now
    enc["runway"] = _runway_name(rwy)
    enc["strip"] = _strip_key(rwy)
    return enc


def _cleanup_encounters(active_strip: str, now: float) -> None:
    stale: list[str] = []
    for key, enc in list(_RUNWAY_ENCOUNTERS.items()):
        if enc.get("strip") == active_strip:
            continue
        last = float(enc.get("last_seen") or 0.0)
        clear = float(enc.get("clear_since") or 0.0)
        if now - last > 30.0 or (clear and now - clear > 14.0):
            stale.append(key)
    for key in stale:
        _RUNWAY_ENCOUNTERS.pop(key, None)


def _lock_runway_end(rwy: dict[str, Any], *, reason: str, now: float) -> None:
    _RUNWAY_END_LOCK.clear()
    _RUNWAY_END_LOCK.update({
        "runway": _runway_name(rwy),
        "strip": _strip_key(rwy),
        "reason": reason,
        "locked_at": now,
        "last_seen": now,
    })


def _locked_candidate(analysed: list[dict[str, Any]], now: float) -> dict[str, Any] | None:
    if not _RUNWAY_END_LOCK:
        return None
    runway = str(_RUNWAY_END_LOCK.get("runway") or "")
    strip = str(_RUNWAY_END_LOCK.get("strip") or "")
    for item in analysed:
        if _runway_name(item) == runway and _strip_key(item) == strip:
            _RUNWAY_END_LOCK["last_seen"] = now
            item["end_lock_active"] = True
            item["end_lock_reason"] = _RUNWAY_END_LOCK.get("reason") or "previous stable end"
            return item
    if now - float(_RUNWAY_END_LOCK.get("last_seen") or 0.0) > 8.0:
        _RUNWAY_END_LOCK.clear()
    return None


def _select_best_runway(analysed: list[dict[str, Any]], *, gs: float, on_ground: bool, now: float) -> dict[str, Any]:
    """Choose a stable physical runway/end without reciprocal or intersection flip-flop.

    Ground APP naming is entry-threshold driven. This avoids the common
    reciprocal-end bug where an aircraft holding near the 24L threshold but
    facing generally toward 06R gets labelled as APP/ON RWY 06R.
    """
    moving = gs >= (TRACK_VALID_MIN_GS_KT if on_ground else 45.0)
    active = [x for x in analysed if x.get("inside") or x.get("approaching")]
    pool = active or analysed

    locked = _locked_candidate(pool, now)
    if locked:
        # Preserve an approach-selected end through runway entry and runway
        # intersections unless the candidate has gone geometrically stale.
        if locked.get("inside") or locked.get("approaching") or not moving:
            return locked

    planned = [x for x in pool if x.get("planned_match")]

    # Ground APP outside the runway: use the closest selected-end threshold
    # first, not aircraft heading. The heading can be opposite while the
    # physical entry point is still the other runway end.
    ground_entry = [x for x in pool if x.get("ground_approach")]
    if on_ground and ground_entry:
        chosen = min(
            ground_entry,
            key=lambda x: (
                0 if x.get("planned_match") else 1,
                _metric(x, "threshold_distance_ft", 999999.0),
                _metric(x, "edge_distance_ft", 999999.0),
                abs(_metric(x, "cross_ft_live", 9999.0)),
                _metric(x, "heading_delta_deg", 999.0) / 8.0,
            ),
        )
        _lock_runway_end(chosen, reason="nearest runway entry threshold", now=now)
        chosen["end_lock_active"] = True
        chosen["end_lock_reason"] = _RUNWAY_END_LOCK.get("reason")
        return chosen

    inside = [x for x in pool if x.get("inside")]
    if inside:
        # If a slow/taxiing aircraft has just entered at a threshold and no
        # explicit encounter lock exists, prefer the runway end whose own
        # threshold is closest. This handles line-up turns and 180-degree taxiway
        # headings without flipping to the reciprocal end.
        if on_ground and gs < 45.0:
            entry_inside = [
                x for x in inside
                if bool(x.get("near_selected_threshold")) and not bool(x.get("near_opposite_threshold"))
            ]
            if entry_inside:
                chosen = min(
                    entry_inside,
                    key=lambda x: (
                        0 if x.get("planned_match") else 1,
                        _metric(x, "threshold_distance_ft", 999999.0),
                        abs(_metric(x, "cross_ft_live", 9999.0)),
                        _metric(x, "heading_delta_deg", 999.0) / 8.0,
                    ),
                )
                _lock_runway_end(chosen, reason="runway entry threshold", now=now)
                chosen["end_lock_active"] = True
                chosen["end_lock_reason"] = _RUNWAY_END_LOCK.get("reason")
                return chosen
        chosen = min(
            inside,
            key=lambda x: (
                0 if x.get("planned_match") else 1,
                0 if x.get("end_lock_active") else 1,
                _metric(x, "heading_delta_deg", 999.0),
                abs(_metric(x, "cross_ft_live", 9999.0)),
                _metric(x, "threshold_distance_ft", 999999.0),
            ),
        )
        _lock_runway_end(chosen, reason="inside runway surface", now=now)
        chosen["end_lock_active"] = True
        chosen["end_lock_reason"] = _RUNWAY_END_LOCK.get("reason")
        return chosen

    if planned:
        chosen = min(planned, key=lambda x: (0 if x.get("approaching") else 1, _metric(x, "threshold_distance_ft", 999999.0), _metric(x, "heading_delta_deg", 999.0), abs(_metric(x, "cross_ft_live", 9999.0))))
        if chosen.get("approaching") or chosen.get("inside"):
            _lock_runway_end(chosen, reason="planned runway", now=now)
            chosen["end_lock_active"] = True
            chosen["end_lock_reason"] = _RUNWAY_END_LOCK.get("reason")
        return chosen

    aligned_limit = 55.0 if on_ground else 28.0
    aligned = [x for x in pool if _metric(x, "heading_delta_deg", 999.0) <= aligned_limit]
    if aligned:
        chosen = min(aligned, key=lambda x: (0 if x.get("approaching") else 1, _metric(x, "heading_delta_deg", 999.0), abs(_metric(x, "cross_ft_live", 9999.0)), _metric(x, "threshold_distance_ft", 999999.0)))
        if moving or chosen.get("approaching"):
            _lock_runway_end(chosen, reason="track aligned" if moving else "heading aligned", now=now)
            chosen["end_lock_active"] = True
            chosen["end_lock_reason"] = _RUNWAY_END_LOCK.get("reason")
        return chosen

    chosen = min(pool, key=lambda x: _metric(x, "score", 0.0))
    if chosen.get("inside") or chosen.get("approaching"):
        _lock_runway_end(chosen, reason="geometry stable", now=now)
        chosen["end_lock_active"] = True
        chosen["end_lock_reason"] = _RUNWAY_END_LOCK.get("reason")
    return chosen

def _planned_runway_hint() -> str:
    try:
        from .settings_store import load_settings
        from .simbrief_client import cached_plan
        user = str(load_settings().get("identity", {}).get("simbrief_user_id") or "")
        plan = cached_plan(user) if user else None
    except Exception:
        plan = None
    if not isinstance(plan, dict):
        return ""
    candidates: list[Any] = []
    for key in ("origin", "destination", "alternate", "performance", "tlr", "takeoff", "landing"):
        value = plan.get(key)
        if isinstance(value, dict):
            candidates.extend(value.get(k) for k in ("runway", "runway_ident", "rwy", "deprwy", "arrwy"))
    for value in candidates:
        text = str(value or "").upper().replace("RWY", "").replace("RUNWAY", "").strip()
        if text and len(text) <= 4:
            return text
    return ""


def _rates_for(name: str, along: float, cross: float, now: float) -> tuple[float, float]:
    prev = _LAST_GEOM.get(name)
    _LAST_GEOM[name] = (along, cross, now)
    if not prev:
        return 0.0, 0.0
    pa, pc, pt = prev
    dt = max(0.08, now - pt)
    return (along - pa) / dt, (cross - pc) / dt


def _candidate_analysis(candidate: dict[str, Any], *, lat: float, lon: float, track: float, heading_actual: float, gs: float, agl: float, on_ground: bool, planned: str, now: float) -> dict[str, Any] | None:
    name = _runway_name(candidate)
    if not name:
        return None
    proj = project_local(lat, lon, candidate)
    if proj:
        along, cross = proj
    else:
        along = _num(candidate.get("along_ft"), 999999.0)
        cross = _num(candidate.get("cross_ft"), 999999.0)
        along = 999999.0 if along is None else along
        cross = 999999.0 if cross is None else cross
    length = _num(candidate.get("length_ft"), 0.0) or 0.0
    width = max(60.0, _num(candidate.get("width_ft"), 150.0) or 150.0)
    runway_heading = _num(candidate.get("heading_deg"), 0.0) or 0.0
    effective_dir, direction_source, track_valid = _effective_direction(track, heading_actual, gs)
    hdg_delta = _heading_delta(effective_dir, runway_heading)
    track_delta = _heading_delta(track, runway_heading)
    nose_delta = _heading_delta(heading_actual, runway_heading)
    reciprocal_delta = _heading_delta(effective_dir, (runway_heading + 180.0) % 360.0)
    best_delta = min(hdg_delta, reciprocal_delta)
    along_rate, cross_rate = _rates_for(name, along, cross, now)

    half_width = width / 2.0
    on_margin_cross = half_width + (35.0 if _LAST_RUNWAY_ON == name else ON_RUNWAY_EDGE_MARGIN_FT)
    on_margin_along = 120.0 if _LAST_RUNWAY_ON == name else 80.0
    inside = bool(on_ground and -on_margin_along <= along <= length + on_margin_along and abs(cross) <= on_margin_cross)

    edge_distance = max(0.0, abs(cross) - half_width)
    threshold_distance = math.hypot(along, cross)
    opposite_threshold_distance = math.hypot(max(0.0, length - along), cross) if length else 999999.0
    planned_match = _planned_matches(planned, name)

    # Ground APCH must name the runway end the aircraft is physically
    # approaching. At a hold-short/entry point the nose can point along a
    # taxiway or even toward the reciprocal runway heading, so heading is only a
    # supporting signal. The selected-end threshold distance is the primary
    # discriminator for reciprocal pairs such as 24L/06R.
    nose_toward_entry = nose_delta <= 70.0 or hdg_delta <= 70.0
    # Trigger relative to the physical runway edge, not a fixed centreline
    # distance. The previous 200-ft centreline cap meant a 150-ft-wide runway
    # could not alert until roughly 125 ft from the pavement even though the
    # configured edge distance was 300 ft.
    approach_cross_limit = half_width + GROUND_APPROACH_EDGE_DISTANCE_FT
    near_runway_edge = edge_distance <= GROUND_APPROACH_EDGE_DISTANCE_FT and abs(cross) <= approach_cross_limit
    along_relevant = -500.0 <= along <= length + 500.0
    near_selected_threshold = threshold_distance <= (GROUND_APPROACH_ENTRY_THRESHOLD_FT + GROUND_APPROACH_ALERT_EARLY_FT)
    near_opposite_threshold = opposite_threshold_distance <= GROUND_APPROACH_ENTRY_THRESHOLD_FT
    opposite_end_conflict = bool(near_opposite_threshold and not near_selected_threshold and not planned_match)
    moving_or_pointing = gs >= TAXI_MOVING_MIN_GS_KT or nose_toward_entry
    threshold_entry_approach = bool(
        on_ground and not inside and along_relevant and near_runway_edge and near_selected_threshold and gs <= 60.0
    )
    edge_capture = bool(
        on_ground
        and not inside
        and along_relevant
        and near_runway_edge
        and not opposite_end_conflict
        and moving_or_pointing
        and (cross * cross_rate) < -0.10
        and gs <= 55.0
    )
    ground_threshold_approach = threshold_entry_approach

    final_corridor = max(300.0, min(1200.0, abs(along) * 0.10))
    airborne_approach = bool(
        not on_ground and 30.0 <= agl <= 2000.0 and -12150.0 <= along <= 1200.0 and abs(cross) <= final_corridor and hdg_delta <= 24.0 and gs >= 60.0
    )
    approaching = ground_threshold_approach or edge_capture or airborne_approach
    if airborne_approach:
        _AIRBORNE_FINAL_RUNWAYS.add(name)

    forward = hdg_delta <= reciprocal_delta
    raw_remaining = (length - along) if forward else along
    remaining = _clamp(raw_remaining, 0.0, length if length > 0 else 99999.0)
    if airborne_approach:
        phase = "final"
    elif inside and name in _AIRBORNE_FINAL_RUNWAYS:
        phase = "landing roll"
    elif inside and gs >= 55:
        phase = "takeoff"
    elif on_ground:
        phase = "taxi"
    else:
        phase = "airborne"

    planned_bonus = -600.0 if planned_match else 0.0
    lock_bonus = -500.0 if (_RUNWAY_END_LOCK and _RUNWAY_END_LOCK.get("runway") == name and _RUNWAY_END_LOCK.get("strip") == _strip_key(candidate)) else 0.0
    if inside:
        score = -2000.0 + abs(cross) / 8.0 + hdg_delta / 5.0 + planned_bonus + lock_bonus
    elif approaching:
        score = -800.0 + abs(cross) / 12.0 + edge_distance / 8.0 + hdg_delta / 5.0 + threshold_distance / 1800.0 + planned_bonus + lock_bonus
    else:
        score = abs(cross) / 80.0 + min(threshold_distance, opposite_threshold_distance) / 1800.0 + best_delta / 8.0 + planned_bonus + lock_bonus

    return {
        **candidate,
        "runway": name,
        "selected_runway_end": name,
        "planned_match": planned_match,
        "aircraft_track_deg": round(track, 1),
        "aircraft_heading_deg": round(heading_actual, 1),
        "effective_direction_deg": round(effective_dir, 1),
        "effective_direction_source": direction_source,
        "track_valid": bool(track_valid),
        "runway_heading_deg": round(runway_heading, 1),
        "heading_delta_deg": round(hdg_delta, 1),
        "track_delta_deg": round(track_delta, 1),
        "nose_delta_deg": round(nose_delta, 1),
        "reciprocal_heading_delta_deg": round(reciprocal_delta, 1),
        "along_ft_live": round(along, 1),
        "cross_ft_live": round(cross, 1),
        "along_rate_fps": round(along_rate, 1),
        "cross_rate_fps": round(cross_rate, 1),
        "remaining_ft": round(remaining, 1),
        "inside": inside,
        "approaching": approaching,
        "ground_approach": ground_threshold_approach or edge_capture,
        "airborne_approach": airborne_approach,
        "edge_capture": edge_capture,
        "threshold_entry_approach": threshold_entry_approach,
        "near_selected_threshold": bool(near_selected_threshold),
        "near_opposite_threshold": bool(near_opposite_threshold),
        "opposite_end_conflict": bool(opposite_end_conflict),
        "entry_threshold_limit_ft": GROUND_APPROACH_ENTRY_THRESHOLD_FT + GROUND_APPROACH_ALERT_EARLY_FT,
        "edge_distance_ft": round(edge_distance, 1),
        "threshold_distance_ft": round(threshold_distance, 1),
        "opposite_threshold_distance_ft": round(opposite_threshold_distance, 1),
        "approach_cross_limit_ft": round(approach_cross_limit, 1),
        "on_runway_cross_limit_ft": round(on_margin_cross, 1),
        "phase": phase,
        "direction": "forward" if forward else "opposite",
        "distance_to_threshold_ft": round(threshold_distance, 1),
        "geometry_source": candidate.get("geometry_source") or "OPS ROOM NAVDATA",
        "sample_age_ms": 0,
        "eval_hz": RAAS_FAST_HZ,
        "ui_hz": RAAS_UI_HZ,
        "score": round(score, 3),
    }

def _analyse_once() -> None:
    global _LAST_RUNWAY_ON, _LAST_APPROACH_RUNWAY, _REMAINING_SPOKEN, _GROUND_ALERTS_SUPPRESSED, _WAS_ON_GROUND, _ACTIVE_SESSION_ARMED
    if not navdata_available():
        _set_status(ok=False, state="UNAVAILABLE", display="RAAS-UNAV", message="OPS ROOM runway navdata is not available")
        return
    tel = read_telemetry(force=False)
    now = time.monotonic()
    if not tel.get("ok"):
        _set_status(ok=True, state="WAITING TELEMETRY", display="RAAS-STBY", message=tel.get("reason") or "Waiting for simulator telemetry", telemetry=tel, diagnostics=telemetry_diagnostics(False))
        return

    lat, lon = _num(tel.get("lat")), _num(tel.get("lon"))
    if lat is None or lon is None:
        _set_status(ok=True, state="WAITING POSITION", display="RAAS-STBY", message="Telemetry has no valid lat/lon", telemetry=tel)
        return
    heading_actual = _num(tel.get("heading_deg"), 0.0) or 0.0
    raw_track = _num(tel.get("track_deg"), heading_actual) or heading_actual
    gs = _num(tel.get("ground_speed_kts"), 0.0) or 0.0
    agl = _num(tel.get("agl_ft"), _num(tel.get("radio_altitude_ft"), 0.0)) or 0.0
    on_ground = bool(tel.get("on_ground")) or agl < 18.0
    effective_dir, direction_source, track_valid = _effective_direction(raw_track, heading_actual, gs)

    armed, arm_reason = _session_gate(tel, lat, lon, now)
    if not armed:
        _LAST_RUNWAY_ON = ""
        _LAST_APPROACH_RUNWAY = ""
        _set_status(ok=True, state="STANDBY", display="RAAS-STBY", message=f"Runway Awareness standby: {arm_reason}", telemetry_source=tel.get("source"), telemetry=tel, runway=None, eval_hz=RAAS_FAST_HZ, arm_reason=arm_reason)
        return

    # Departed aircraft must not continue receiving ground RAAS callouts just
    # because it is still close to airport runway geometry. Re-arm only for a
    # true final-approach candidate.
    if _WAS_ON_GROUND and not on_ground and gs >= 55.0:
        _GROUND_ALERTS_SUPPRESSED = True
        _LAST_APPROACH_RUNWAY = ""
        _LAST_RUNWAY_ON = ""
        _REMAINING_SPOKEN = set()
    if on_ground and gs < 30.0 and _GROUND_ALERTS_SUPPRESSED and not _LAST_RUNWAY_ON:
        # After landing/taxi-in, allow normal ground alerts again.
        _GROUND_ALERTS_SUPPRESSED = False
    _WAS_ON_GROUND = on_ground

    # On the ground, do not bias nearby runway-end retrieval by aircraft
    # heading. A taxiing aircraft can face the reciprocal runway direction while
    # physically approaching the other end's threshold. Selection below handles
    # heading only after threshold geometry and encounter locks.
    lookup_track = effective_dir if (not on_ground or gs >= 45.0) else None
    candidates = runway_ends_near(lat, lon, track_deg=lookup_track, max_nm=8.0, limit=32)
    if not candidates:
        _LAST_RUNWAY_ON = ""
        _LAST_APPROACH_RUNWAY = ""
        _set_status(ok=True, state="MONITORING", display=_raas_ok_code(), message="Monitoring, no nearby runway", telemetry_source=tel.get("source"), telemetry=tel, runway=None, eval_hz=RAAS_FAST_HZ)
        return

    planned = _planned_runway_hint()
    analysed = [x for c in candidates if (x := _candidate_analysis(c, lat=lat, lon=lon, track=raw_track, heading_actual=heading_actual, gs=gs, agl=agl, on_ground=on_ground, planned=planned, now=now))]
    if not analysed:
        _set_status(ok=True, state="MONITORING", display=_raas_ok_code(), message="Monitoring, no valid runway geometry", telemetry_source=tel.get("source"), telemetry=tel, runway=None, eval_hz=RAAS_FAST_HZ)
        return

    analysed.sort(key=lambda item: float(item.get("score") or 0.0))
    rwy = _select_best_runway(analysed, gs=gs, on_ground=on_ground, now=now)
    name = _runway_name(rwy)
    strip = _strip_key(rwy)
    inside = bool(rwy.get("inside"))
    approaching = bool(rwy.get("approaching"))
    airborne_approach = bool(rwy.get("airborne_approach"))
    ground_alert_allowed = not _GROUND_ALERTS_SUPPRESSED or airborne_approach
    length = _num(rwy.get("length_ft"), 0.0) or 0.0
    along = _num(rwy.get("along_ft_live"), 0.0) or 0.0
    remaining = _num(rwy.get("remaining_ft"), 0.0) or 0.0
    phase = str(rwy.get("phase") or "taxi")
    runway_session = _update_runway_session(on_ground=on_ground, inside=inside, approaching=approaching, airborne_approach=airborne_approach, strip=strip, runway=name, gs=gs, now=now)
    entry_alert_allowed = ground_alert_allowed and not runway_session.get("suppress_entry_callouts")

    state = "ON RUNWAY" if inside else ("APPROACHING RUNWAY" if approaching else "MONITORING")
    display = _raas_ok_code() if state == "MONITORING" else (f"ON RWY {name}" if inside else f"APP RWY {name}")
    rwy["ground_alerts_suppressed"] = bool((_GROUND_ALERTS_SUPPRESSED and not airborne_approach) or runway_session.get("suppress_entry_callouts"))
    rwy["runway_session_state"] = runway_session.get("state")
    rwy["vacated_cooldown_remaining_seconds"] = round(float(runway_session.get("cooldown_remaining_seconds") or 0.0), 1)
    rwy["encounter_key"] = _encounter_key(rwy)
    rwy["strip_key"] = strip
    rwy["loop_lag_ms"] = round(_LAST_LOOP_LAG_MS, 1)
    rwy["eval_hz"] = RAAS_FAST_HZ
    rwy["ui_hz"] = RAAS_UI_HZ
    rwy["end_lock_active"] = bool(_RUNWAY_END_LOCK and _RUNWAY_END_LOCK.get("runway") == name)
    rwy["end_lock_reason"] = _RUNWAY_END_LOCK.get("reason") if _RUNWAY_END_LOCK else ""

    _set_status(
        ok=True,
        state=state,
        display=display,
        message="Runway Awareness monitoring" + ("; ground callouts suppressed after takeoff" if _GROUND_ALERTS_SUPPRESSED and not airborne_approach else "") + ("; vacating cooldown" if runway_session.get("suppress_entry_callouts") else ""),
        active_runway=name if (inside or approaching) else "",
        runway=rwy,
        runway_candidates=analysed[:4],
        telemetry_source=tel.get("source"),
        telemetry=tel,
        source_priority="FSUIPC7 FIRST / SIMCONNECT FALLBACK",
        planned_runway_hint=planned,
        effective_direction_deg=round(effective_dir, 1),
        effective_direction_source=direction_source,
        track_valid=bool(track_valid),
        runway_lookup_track_deg=round(lookup_track, 1) if lookup_track is not None else None,
        runway_lookup_heading_bias="disabled_on_ground_threshold_mode" if lookup_track is None else "enabled",
        arm_reason=arm_reason,
        eval_hz=RAAS_FAST_HZ,
        ui_hz=RAAS_UI_HZ,
    )

    _cleanup_encounters(strip if (inside or approaching) else "", now)
    if inside or approaching:
        enc = _encounter_for(rwy, now)
    else:
        enc = None

    if approaching and name and entry_alert_allowed and enc is not None and not enc.get("approach"):
        enc["approach"] = True
        _LAST_APPROACH_RUNWAY = name
        _callout(f"Approaching runway {name}", "approaching_runway", runway=name, priority="operational", cooldown=0.0)
    elif not approaching:
        _LAST_APPROACH_RUNWAY = ""

    if inside and name:
        if enc is not None and not enc.get("on") and entry_alert_allowed:
            enc["on"] = True
            _LAST_RUNWAY_ON = name
            _REMAINING_SPOKEN = set()
            _callout(f"On runway {name}", "on_runway", runway=name, priority="operational", cooldown=0.0)
        elif name != _LAST_RUNWAY_ON:
            _LAST_RUNWAY_ON = name
            _REMAINING_SPOKEN = set()
        if ground_alert_allowed and length and length < 5500 and gs > 30:
            _callout("Caution short runway", "short_runway", runway=name, priority="caution", cooldown=45.0)
        if ground_alert_allowed and gs > 35:
            for threshold_ft, display_value, unit_code, spoken_unit in _remaining_thresholds():
                spoken_key = (name, unit_code, int(display_value))
                if remaining <= threshold_ft and length >= threshold_ft + 250 and spoken_key not in _REMAINING_SPOKEN:
                    _REMAINING_SPOKEN.add(spoken_key)
                    _callout(f"{display_value} {spoken_unit} remaining", "remaining", runway=name, distance_ft=int(round(threshold_ft)), distance_value=int(display_value), distance_unit=unit_code, priority="operational", cooldown=1.5)
                    break
        if ground_alert_allowed and phase == "landing roll":
            if along > max(2500.0, length * 0.45):
                _callout("Deep landing", "deep_landing", runway=name, priority="caution", cooldown=120.0)
            if remaining < max(1500.0, length * 0.18) and gs > 80.0:
                _callout("Long landing", "long_landing", runway=name, priority="caution", cooldown=120.0)
    elif _LAST_RUNWAY_ON and not inside:
        old = _LAST_RUNWAY_ON
        _LAST_RUNWAY_ON = ""
        _REMAINING_SPOKEN = set()
        for enc_state in _RUNWAY_ENCOUNTERS.values():
            if enc_state.get("runway") == old and not enc_state.get("clear_since"):
                enc_state["clear_since"] = now

    if ground_alert_allowed and on_ground and gs > 80 and not inside and not approaching:
        _callout("Caution taxiway", "taxiway_takeoff", priority="critical", cooldown=15.0)
    if phase == "final" and name:
        vertical_speed = abs(_num(tel.get("vertical_speed_fpm"), 0.0) or 0.0)
        if agl < 800 and vertical_speed > 1400:
            _callout("Unstable", "unstable", runway=name, priority="caution", cooldown=35.0)


def _loop() -> None:
    global _LAST_LOOP_LAG_MS
    _raas_audio_start()
    _set_status(ok=True, state="READY", display=_raas_ok_code(), message="Runway Awareness ready")
    while _RUNNING:
        started = time.monotonic()
        try:
            if _ENABLED:
                _analyse_once()
            else:
                _set_status(ok=True, state="DISABLED", display="RAAS-OFF", message="Runway Awareness disabled")
        except Exception as exc:
            _set_status(ok=False, state="ERROR", display="RAAS-FAULT", message=f"{type(exc).__name__}: {exc}")
        elapsed = time.monotonic() - started
        _LAST_LOOP_LAG_MS = max(0.0, (elapsed - RAAS_FAST_INTERVAL) * 1000.0)
        time.sleep(max(0.006, RAAS_FAST_INTERVAL - elapsed))


def start() -> dict[str, Any]:
    global _RUNNING, _THREAD
    if _RUNNING and _THREAD and _THREAD.is_alive():
        return status()
    _RUNNING = True
    _THREAD = threading.Thread(target=_loop, name="OpsRoom-RunwayAwareness", daemon=True)
    _THREAD.start()
    return status()


def stop() -> dict[str, Any]:
    global _RUNNING
    _RUNNING = False
    _set_status(ok=True, state="STOPPED", display="RAAS-STBY", message="Runway Awareness stopped")
    return status()


def set_enabled(enabled: bool) -> dict[str, Any]:
    global _ENABLED
    _ENABLED = bool(enabled)
    return status()


def set_voice_path(path: str) -> dict[str, Any]:
    _raas_audio_set_voice_path(path)
    return status()


def set_unit(unit: str) -> dict[str, Any]:
    selected = "m" if str(unit or "").strip().lower() in {"m", "meter", "meters", "metre", "metres"} else "ft"
    from .settings_store import load_settings, save_settings
    settings = load_settings()
    settings.setdefault("integrations", {})["raas_unit"] = selected
    save_settings(settings)
    with _LOCK:
        current_state = str(_LAST_STATUS.get("state") or "")
    if current_state not in {"ERROR", "UNAVAILABLE", "DISABLED", "STOPPED"}:
        _set_status(display=_raas_ok_code(), message="Runway Awareness units set to " + _raas_unit_code())
    return status()


def test() -> dict[str, Any]:
    # Manual test is a single, compact status event. Audio can still speak the
    # full phrase, but the visual alert must show the selected cockpit code.
    display = _raas_ok_code()
    _set_status(ok=True, state="TEST", display=display, message="Runway Awareness OK", last_callout_type="test", last_callout="Runway Awareness OK", last_callout_priority="operational", suppress_center_toast=False, client_audio_required=False)
    _callout("Runway Awareness OK", "test", priority="operational", cooldown=1.5, suppress_center_toast=False)
    return status()


def status() -> dict[str, Any]:
    with _LOCK:
        data = dict(_LAST_STATUS)
    now = time.monotonic()
    data["running"] = bool(_RUNNING and _THREAD and _THREAD.is_alive())
    data["enabled"] = _ENABLED
    data["audio"] = _raas_audio_status()
    data["navdata_available"] = navdata_available()
    data["raas_unit"] = _raas_unit_pref()
    data["unit_code"] = _raas_unit_code()
    data["remaining_thresholds"] = [{"feet": round(feet, 1), "display_value": value, "unit": unit} for feet, value, unit, _spoken in _remaining_thresholds()]
    if data.get("display_expires_at") and now > float(data.get("display_expires_at") or 0.0):
        data["display"] = _raas_ok_code() if data.get("state") not in {"ERROR", "UNAVAILABLE", "DISABLED"} else data.get("display", "RAAS-STBY")
        data["raas_event_active"] = False
    return data
