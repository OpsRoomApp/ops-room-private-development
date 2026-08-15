from __future__ import annotations

import random
import queue
import math
import re
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore
from typing import Any

from .settings_store import load_settings
from .simbrief_client import cached_plan
from .telemetry_provider import read_telemetry

_AUDIO_EXTENSIONS = {".ogg", ".wav", ".mp3"}
# Announcement filenames are an explicit operational contract.  Every base
# filename is a distinct event; bracketed suffixes are variants of that event
# only.  Never cross-map one cabin call to another.
_CABIN_ANNOUNCEMENT_EVENTS = {
    "ArmDoors", "DisarmDoors", "BoardingStarted", "BoardingWelcome",
    "BoardingMusic", "BoardingComplete", "PreSafetyBriefing",
    "SafetyBriefing", "CallCabinSecureTakeoff", "CabinDimTakeoff",
    "CrewSeatsTakeoff", "AfterTakeoff", "FastenSeatbelt", "Turbulence",
    "DescentSeatbelts", "CallCabinSecureLanding", "CabinDimLanding",
    "CrewSeatsLanding", "AfterLanding", "DisembarkStarted",
}
_EVENT_TAG_RE = re.compile(r"\[([^\]]+)\]")
_AIRCRAFT_TAGS = {"A319", "A320", "A321"}
_DAYPART_TAGS = {"MORNING", "AFTERNOON", "EVENING", "NIGHT", "DAY"}
_ARRIVAL_EVENTS = {
    "DescentSeatbelts", "CallCabinSecureLanding", "CabinDimLanding",
    "CrewSeatsLanding", "AfterLanding", "DisarmDoors", "DisembarkStarted",
}

_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_STOP = threading.Event()
_CAMERA_DISTANCE: float = 0.0
_CAMERA_LAST_POLL: float = 0.0

# #55: FSUIPC 0x026D CAMERA STATE -> volume category (Universal Announcer
# parity). 2 Cockpit, 7 SixDoF, 9 Showcase/Cabin, 3 External/Chase,
# 5 Fixed on Plane, 6 Environment, 4/10/19 Drone, 8 Gameplay.
# Non-flight states (0 unknown/menu, 17 replay) hold the last-known category
# instead of snapping the volume while tabbing out or replaying.
_CAMERA_STATE_CATEGORY = {
    2: "cockpit", 7: "cockpit",
    9: "cabin",
    3: "external", 4: "external", 5: "external", 6: "external",
    8: "external", 10: "external", 19: "external",
}
_CAMERA_STATE_HOLD = {0, 17}
_CAMERA_CATEGORY: str | None = None
_STATE: dict[str, Any] = {
    "running": False,
    "enabled": False,
    "playing": False,
    "paused": False,
    "muted": False,
    "last_file": None,
    "last_event": None,
    "last_error": None,
    "events": [],
    "airline": "DEFAULT",
    "callsign": "",
    "airline_source": "DEFAULT",
    "available_files": 0,
    "volume": 80,
}
_PLAYED: set[str] = set()
_PREVIOUS: dict[str, Any] = {}
_EVER_AIRBORNE = False
_ARRIVAL_COMPLETE = False
_SCAN_CACHE: dict[str, Any] = {"root": None, "time": 0.0, "count": 0}
_READY_SAMPLES: list[dict[str, Any]] = []
_BOARDING_PHASE_ACTIVE = False
_BOARDING_MUSIC_ACTIVE = False
_NEXT_WELCOME_AT = 0.0
_BOARDING_WELCOME_MIN_SECONDS = 300.0
_BOARDING_WELCOME_MAX_SECONDS = 600.0
_BOARDING_MUSIC_DUE_AT = 0.0
_CURRENT_PA_SOUND: Any = None
_MUSIC_CHANNEL_VOLUME = 0.40
_MUSIC_DUCK_LEVEL = 0.08
_MUSIC_DUCKED = False
_PA_CHANNEL_INDEX = 1
_AUDIO_HARD_STOPPED = False
_SESSION_READY = False
_SESSION_GROUND_STABLE_SAMPLES = 0
_SESSION_AIRBORNE_SAMPLES = 0
_TAKEOFF_ROLL_SEEN = False
_TAKEOFF_CONFIRMED = False
_LAST_SUPPRESSED_REASON = ""
_LAST_SUPPRESSED_AT = 0.0
_AUDIO_QUEUE: "queue.Queue[dict[str, Any]]" = queue.Queue(maxsize=64)
_QUEUED_EVENTS: set[str] = set()
_AUDIO_FAILURES = 0
_AUDIO_CIRCUIT_OPEN_UNTIL = 0.0
_ANN_AIRBORNE_STARTED_AT = 0.0
_ANN_DESCENT_SAMPLES = 0
_ANN_VALID_PHASE = "GROUND"
_TAXI_OUT_SUSTAINED_SAMPLES = 0
_AUTO_TELEMETRY_SUSPENDED = False
_RECORDER_PHASE_CACHE: tuple[float, str] = (0.0, "")
_SEATBELT_SIMVAR_CHANGED = False
_BOARDING_MOVEMENT_SAMPLES = 0




def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _record(kind: str, text: str) -> None:
    _STATE["events"].append({"time": _utc(), "kind": kind, "text": text})
    _STATE["events"] = _STATE["events"][-80:]
    # A monotonic revision lets the UI distinguish a genuinely new cached
    # snapshot from a repeated poll without touching playback/trigger logic.
    _STATE["revision"] = int(_STATE.get("revision") or 0) + 1
    _STATE["updated_utc"] = _utc()


def _clean_callsign(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())[:16]


def _clean_airline(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())[:4]



def _plan_for_announcements() -> dict[str, Any]:
    settings = load_settings()
    user = str(settings.get("identity", {}).get("simbrief_user_id") or "")
    plan = cached_plan(user) if user else None
    return dict(plan or {}) if isinstance(plan, dict) else {}


def _aircraft_variant() -> str:
    plan = _plan_for_announcements()
    ofp = plan.get("ofp") if isinstance(plan.get("ofp"), dict) else plan
    general = ofp.get("general") if isinstance(ofp.get("general"), dict) else {}
    aircraft = ofp.get("aircraft") if isinstance(ofp.get("aircraft"), dict) else {}
    values = [
        general.get("aircraft_icao"), general.get("aircraft"),
        aircraft.get("icao_code"), aircraft.get("icao"), aircraft.get("name"),
        plan.get("aircraft_icao"), plan.get("aircraft"),
    ]
    try:
        telemetry = read_telemetry(force=False)
        values.extend([telemetry.get("aircraft_type"), telemetry.get("aircraft_title"), telemetry.get("title"), telemetry.get("type")])
    except Exception:
        pass
    text = " ".join(str(x or "").upper() for x in values)
    if re.search(r"\bA319\b|\bA19N\b", text):
        return "A319"
    if re.search(r"\bA321\b|\bA21N\b", text):
        return "A321"
    if re.search(r"\bA320\b|\bA20N\b", text):
        return "A320"
    return ""


def _airport_time(event: str) -> datetime:
    plan = _plan_for_announcements()
    ofp = plan.get("ofp") if isinstance(plan.get("ofp"), dict) else plan
    endpoint_name = "destination" if event in _ARRIVAL_EVENTS else "origin"
    endpoint = ofp.get(endpoint_name) if isinstance(ofp.get(endpoint_name), dict) else plan.get(endpoint_name)
    endpoint = endpoint if isinstance(endpoint, dict) else {}
    for key in ("timezone_id", "timezone_name", "iana_timezone", "tz"):
        value = str(endpoint.get(key) or "").strip()
        if value and ZoneInfo is not None:
            try:
                return datetime.now(ZoneInfo(value))
            except Exception:
                pass
    for key in ("utc_offset", "timezone", "timezone_offset"):
        value = endpoint.get(key)
        try:
            offset = float(value)
        except (TypeError, ValueError):
            continue
        if abs(offset) > 24.0:
            offset /= 3600.0
        if -14.0 <= offset <= 14.0:
            try:
                return datetime.now(timezone(timedelta(hours=offset)))
            except Exception:
                pass
    return datetime.now().astimezone()


def _local_daypart(event: str) -> str:
    hour = _airport_time(event).hour
    if 5 <= hour < 12:
        return "Morning"
    if 12 <= hour < 17:
        return "Afternoon"
    if 17 <= hour < 22:
        return "Evening"
    return "Night"


def _refueling_active() -> bool:
    try:
        raw = int(_PREVIOUS.get("gsx_refuel") or 0)
    except Exception:
        raw = 0
    if raw in {4, 5, 7}:
        return True
    try:
        from .gsx_remote import status as gsx_status
        row = ((gsx_status(force=False).get("services") or {}).get("refuel") or {})
        raw = int(row.get("raw") or 0)
        state = str(row.get("state") or "").upper()
        return raw in {4, 5, 7} or state in {"REQUESTED", "PERFORMING", "COMPLETING", "WAITING", "ACTIVE"}
    except Exception:
        return False


def _parse_event_filename(path: Path) -> tuple[str, set[str], int | None]:
    stem = path.stem
    base = stem.split("[", 1)[0].strip()
    tags = {str(tag).strip().upper() for tag in _EVENT_TAG_RE.findall(stem) if str(tag).strip()}
    numbered = [int(tag) for tag in tags if tag.isdigit()]
    return base, tags, numbered[-1] if numbered else None


def _compatible_event_files(event: str, files: list[Path]) -> list[Path]:
    """Return the best variants of one exact announcement event.

    Base filenames are literal operational events. Context tags only refine
    selection *inside* that exact event. Numbered suffixes remain equivalent
    alternatives and are deliberately left for random choice by playback.
    """
    exact: list[tuple[Path, set[str], int | None]] = []
    for path in files:
        base, tags, number = _parse_event_filename(path)
        if base.lower() == event.lower():
            exact.append((path, tags, number))
    if not exact:
        return []

    aircraft = _aircraft_variant().upper()
    daypart = _local_daypart(event).upper()
    refueling = _refueling_active()

    compatible: list[tuple[Path, set[str], int | None]] = []
    for path, tags, number in exact:
        aircraft_tags = tags & _AIRCRAFT_TAGS
        refuel_tag = bool(tags & {"REFUELING", "REFUELLING"})
        if aircraft_tags and (not aircraft or aircraft not in aircraft_tags):
            continue
        if refuel_tag and not refueling:
            continue
        compatible.append((path, tags, number))

    if not compatible:
        # Never cross to a different event or wrong aircraft. A completely
        # generic file of this same event is the only safe final fallback.
        generic = [
            path for path, tags, _number in exact
            if not (tags & (_AIRCRAFT_TAGS | _DAYPART_TAGS | {"REFUELING", "REFUELLING"}))
        ]
        return sorted(generic)

    # Refuelling is an operationally distinct version of the same event.
    # When it is active and a matching refuelling recording exists, restrict
    # selection to that group before evaluating aircraft/daypart variants.
    if refueling:
        refuel_group = [row for row in compatible if row[1] & {"REFUELING", "REFUELLING"}]
        if refuel_group:
            compatible = refuel_group
    else:
        compatible = [row for row in compatible if not (row[1] & {"REFUELING", "REFUELLING"})]

    scored: list[tuple[int, Path]] = []
    for path, tags, _number in compatible:
        aircraft_tags = tags & _AIRCRAFT_TAGS
        daypart_tags = tags & _DAYPART_TAGS
        score = 0

        if aircraft_tags:
            score += 100
        elif aircraft:
            score += 20

        if daypart_tags:
            day_match = daypart in daypart_tags
            if not day_match and daypart in {"MORNING", "AFTERNOON"} and "DAY" in daypart_tags:
                day_match = True
            if not day_match:
                continue
            score += 60
        else:
            score += 10

        if tags & {"REFUELING", "REFUELLING"}:
            score += 40
        scored.append((score, path))

    if not scored:
        # Prefer a generic same-event candidate. If this event only has other
        # daypart variants, use one of those rather than returning a different
        # base event or silently substituting another operational call.
        generic = [
            path for path, tags, _number in compatible
            if not (tags & (_AIRCRAFT_TAGS | _DAYPART_TAGS))
        ]
        return sorted(generic or [path for path, _tags, _number in compatible])

    best = max(score for score, _path in scored)
    return sorted(path for score, path in scored if score == best)


def _telemetry_ready(t: dict[str, Any]) -> bool:
    if t.get("sim_process_running") is False:
        _invalidate_auto_session("Simulator closed; announcement session reset"); return False
    if not t.get("ok") or t.get("telemetry_valid") is False or t.get("telemetry_fresh") is False or t.get("stale"):
        _suspend_auto_session(str(t.get("reason") or "Announcements paused — simulator data unavailable")); return False
    if t.get("paused") or t.get("slew_active"):
        _READY_SAMPLES.clear(); return False
    lat, lon = t.get("lat"), t.get("lon")
    try:
        lat = float(lat); lon = float(lon)
        alt = float(t.get("altitude_ft") if t.get("altitude_ft") is not None else t.get("indicated_altitude_ft"))
        gs = float(t.get("ground_speed_kts") or 0.0)
        agl = float(t.get("agl_ft") if t.get("agl_ft") is not None else 0.0)
    except (TypeError, ValueError):
        _READY_SAMPLES.clear(); return False
    if abs(lat) < .001 and abs(lon) < .001:
        _READY_SAMPLES.clear(); return False
    if not (-2000 <= alt <= 100000) or not (-100 <= agl <= 100000) or not (0 <= gs <= 900):
        _READY_SAMPLES.clear(); return False
    systems = t.get("systems") if isinstance(t.get("systems"), dict) else {}
    powered = bool(systems.get("battery_master") or systems.get("avionics_powered") or systems.get("engines_running") or systems.get("beacon_light"))
    on_ground = bool(t.get("on_ground", True))
    _READY_SAMPLES.append({"lat": lat, "lon": lon, "on_ground": on_ground, "gs": gs, "agl": agl, "time": time.monotonic()}); del _READY_SAMPLES[:-6]
    if powered:
        return True
    # Fenix and several complex aircraft do not reliably publish generic
    # battery/beacon/engine SimVars. Once the active recorder proves an
    # airborne flight, valid position/altitude telemetry is authoritative.
    phase = _active_recorder_phase()
    airborne_phases = {"TAKEOFF", "INITIAL CLIMB", "CLIMB", "ENROUTE", "CRUISE", "DESCENT", "APPROACH", "FINAL APPROACH", "GO AROUND", "MISSED APPROACH"}
    if not on_ground and (phase in airborne_phases or agl >= 100.0 or gs >= 55.0):
        return True
    if len(_READY_SAMPLES) < 4:
        return False
    span = math.hypot((_READY_SAMPLES[-1]["lat"]-_READY_SAMPLES[0]["lat"])*60, (_READY_SAMPLES[-1]["lon"]-_READY_SAMPLES[0]["lon"])*60)
    return on_ground and gs < 2 and span < .08


def _record_suppressed(reason: str) -> None:
    global _LAST_SUPPRESSED_REASON, _LAST_SUPPRESSED_AT
    now = time.monotonic()
    if reason != _LAST_SUPPRESSED_REASON or now - _LAST_SUPPRESSED_AT > 30.0:
        _record("SUPPRESSED", reason)
        _LAST_SUPPRESSED_REASON = reason
        _LAST_SUPPRESSED_AT = now



def _suspend_auto_session(reason: str) -> None:
    """Pause flight-trigger evaluation without forgetting the active flight."""
    global _AUTO_TELEMETRY_SUSPENDED
    _READY_SAMPLES.clear()
    if not _AUTO_TELEMETRY_SUSPENDED:
        _record("FLIGHT AUTOMATION", reason)
    _AUTO_TELEMETRY_SUSPENDED = True


def _resume_from_active_recorder(t: dict[str, Any]) -> bool:
    global _SESSION_READY, _TAKEOFF_CONFIRMED, _EVER_AIRBORNE, _ANN_VALID_PHASE
    if t.get("on_ground") is not False:
        return False
    try:
        from .logbook import status as logbook_status
        active = (logbook_status(limit=1).get("active") or {})
    except Exception:
        active = {}
    phase = str(active.get("current_phase") or "").upper()
    airborne = {"TAKEOFF", "INITIAL CLIMB", "CLIMB", "ENROUTE", "CRUISE", "DESCENT", "APPROACH", "GO AROUND", "MISSED APPROACH"}
    if not active or phase not in airborne:
        return False
    _SESSION_READY = True
    _TAKEOFF_CONFIRMED = True
    _EVER_AIRBORNE = True
    _ANN_VALID_PHASE = "DESCENT" if phase in {"DESCENT", "APPROACH"} else "CRUISE" if phase in {"ENROUTE", "CRUISE"} else "CLIMB"
    try:
        altitude = float(t.get("altitude_ft") if t.get("altitude_ft") is not None else t.get("indicated_altitude_ft") or 0.0)
        _PREVIOUS["altitude"] = altitude
        _PREVIOUS["agl"] = float(t.get("agl_ft") or 0.0)
        _PREVIOUS["on_ground"] = False
    except Exception:
        pass
    _record("TELEMETRY RESTORED", f"Announcement automation resumed from {phase.replace('_', ' ').title()}")
    return True


def _invalidate_auto_session(reason: str) -> None:
    """Drop stale automatic state when live sim telemetry is not valid.

    Manual one-shot buttons still work, but auto PA must never trust cached
    recorder/FSUIPC/GSX state after the simulator closes or telemetry goes stale.
    """
    global _SESSION_READY, _SESSION_GROUND_STABLE_SAMPLES, _SESSION_AIRBORNE_SAMPLES
    global _TAKEOFF_ROLL_SEEN, _TAKEOFF_CONFIRMED, _EVER_AIRBORNE, _ARRIVAL_COMPLETE
    _SESSION_READY = False
    _SESSION_GROUND_STABLE_SAMPLES = 0
    _SESSION_AIRBORNE_SAMPLES = 0
    _TAKEOFF_ROLL_SEEN = False
    _TAKEOFF_CONFIRMED = False
    _EVER_AIRBORNE = False
    _ARRIVAL_COMPLETE = False
    _READY_SAMPLES.clear()
    for key in (
        "departure_cabin_sequence_started", "departure_cabin_sequence_started_at",
        "pushback_active_seen", "pushback_completed", "post_pushback_briefed",
        "post_pushback_brake_set", "recorder_phase", "flight_phase", "phase",
    ):
        _PREVIOUS.pop(key, None)
    _stop_boarding_music(reason)
    try:
        if _STATE.get("playing") and _STATE.get("last_event") not in {"BoardingMusic"}:
            _mixer_stop_all(quit_mixer=False)
            _STATE["playing"] = False
            _STATE["paused"] = False
    except Exception:
        pass
    _record_suppressed(reason)


def _auto_sim_live(t: dict[str, Any] | None = None) -> bool:
    global _AUTO_TELEMETRY_SUSPENDED
    sample = t if isinstance(t, dict) else read_telemetry(force=False)
    if sample.get("sim_process_running") is False:
        _invalidate_auto_session("Simulator closed; announcement session reset")
        return False
    if sample.get("telemetry_hold"):
        return False
    if not sample.get("ok") or sample.get("telemetry_valid") is False or sample.get("telemetry_fresh") is False or sample.get("stale"):
        _suspend_auto_session(str(sample.get("reason") or "Flight announcements paused — simulator data unavailable"))
        return False
    if _AUTO_TELEMETRY_SUSPENDED:
        _AUTO_TELEMETRY_SUSPENDED = False
        _record("FLIGHT AUTOMATION", "Simulator data restored — flight announcements resumed")
    return True


def _stable_live_session(t: dict[str, Any]) -> bool:
    """Gate automatic cabin calls until the aircraft is really in the sim world."""
    global _SESSION_READY, _SESSION_GROUND_STABLE_SAMPLES
    if _SESSION_READY:
        return True
    if t.get("ok") and t.get("telemetry_valid") is not False and t.get("telemetry_fresh") is not False and t.get("on_ground") is False:
        if _resume_from_active_recorder(t):
            return True
    if not t.get("ok") or t.get("telemetry_valid") is False:
        _SESSION_GROUND_STABLE_SAMPLES = 0
        return False
    if t.get("paused") or t.get("slew_active"):
        _SESSION_GROUND_STABLE_SAMPLES = 0
        return False
    if not isinstance(t.get("on_ground"), bool):
        _SESSION_GROUND_STABLE_SAMPLES = 0
        return False
    try:
        lat = float(t.get("lat") or 0)
        lon = float(t.get("lon") or 0)
        gs = float(t.get("ground_speed_kts") or 0)
        agl = float(t.get("agl_ft") if t.get("agl_ft") is not None else 0)
    except Exception:
        _SESSION_GROUND_STABLE_SAMPLES = 0
        return False
    if abs(lat) < .001 and abs(lon) < .001:
        _SESSION_GROUND_STABLE_SAMPLES = 0
        return False
    # v0.25.79: the MSFS main menu / world map / loading screens are not a
    # flight -- reject them outright so no announcement can ever arm from them.
    if t.get("simulator_loading") or int(t.get("simulator_menu_state") or 0):
        _SESSION_GROUND_STABLE_SAMPLES = 0
        return False
    # MSFS menu/loading defaults to DGTK (Dibba, Oman). Reject UNCONDITIONALLY
    # (not just when on-ground): in the menu the sim may report not-on-ground,
    # but the position still sits at DGTK and must never arm announcements.
    dgtk_ft = math.hypot((lat - 25.618) * 60.0 * 6076.12, (lon - 56.242) * 60.0 * 6076.12 * math.cos(math.radians((lat + 25.618) / 2.0)))
    if dgtk_ft < 30380.0:
        _SESSION_GROUND_STABLE_SAMPLES = 0
        return False
    # Auto-PA lifecycle starts only from a sane loaded on-ground session. This
    # suppresses MSFS world-map/loading/spawn telemetry spikes.
    if bool(t.get("on_ground")) and agl <= 120.0 and gs <= 35.0:
        _SESSION_GROUND_STABLE_SAMPLES += 1
    else:
        _SESSION_GROUND_STABLE_SAMPLES = 0
    if _SESSION_GROUND_STABLE_SAMPLES >= 4:
        _SESSION_READY = True
        _record("SESSION", "Announcement auto-trigger gate armed after stable on-ground telemetry")
        return True
    return False


def _confirmed_airborne_sample(t: dict[str, Any], *, on_ground: bool, agl: float, gs: float, ias: float, vs: float) -> bool:
    if bool(t.get("confirmed_airborne")):
        return True
    return bool((not on_ground) and agl >= 120.0 and gs >= 70.0 and ias >= 55.0 and vs > -1500.0)


def _boarding_audio_allowed() -> bool:
    # Boarding audio is only pre-departure. Once the flight has been airborne or
    # a landing/deboarding call has occurred, jetway/stairs mean arrival service.
    if _EVER_AIRBORNE or _ARRIVAL_COMPLETE:
        return False
    if _PREVIOUS.get("confirmed_departure_movement") or _PREVIOUS.get("pushback_active_seen"):
        return False
    if any(event in _PLAYED for event in ("AfterLanding", "DisembarkStarted", "CrewSeatsLanding")):
        return False
    return True

def _announcement_identity() -> tuple[str, str, str]:
    settings = load_settings()
    integrations = settings.get("integrations", {})
    airline_override = _clean_airline(integrations.get("announcements_airline_override"))
    callsign_override = _clean_callsign(integrations.get("announcements_callsign_override"))

    user = str(settings.get("identity", {}).get("simbrief_user_id") or "")
    plan = cached_plan(user) if user else None
    plan_callsign = _clean_callsign((plan or {}).get("callsign"))
    callsign = callsign_override or plan_callsign

    if airline_override:
        return airline_override, callsign, "AIRLINE OVERRIDE"
    letters = "".join(ch for ch in callsign if ch.isalpha())
    if len(letters) >= 3:
        return letters[:3], callsign, "CALLSIGN OVERRIDE" if callsign_override else "SIMBRIEF"
    return "DEFAULT", callsign, "DEFAULT"


def _root() -> Path | None:
    raw = str(load_settings().get("integrations", {}).get("announcements_root") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_dir() else None


def _package_root() -> Path:
    # Source: <package>/app/announcements.py -> <package>
    # PyInstaller one-folder: user-editable assets live beside OPS ROOM.exe,
    # not inside _internal. This keeps announcement packs accessible to users.
    if getattr(sys, "frozen", False):
        try:
            return Path(sys.executable).resolve().parent
        except Exception:
            pass
    return Path(__file__).resolve().parents[1]


def _built_in_announcement_roots() -> list[Path]:
    candidates = [
        _package_root() / "Announcements",
        Path.cwd() / "Announcements",
    ]
    result: list[Path] = []
    seen: set[str] = set()
    for folder in candidates:
        try:
            key = str(folder.resolve()).lower()
        except Exception:
            key = str(folder).lower()
        if key not in seen and folder.is_dir():
            seen.add(key)
            result.append(folder)
    return result


def _folder_audio_count(folder: Path) -> int:
    if not folder.is_dir():
        return 0
    try:
        return sum(1 for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in _AUDIO_EXTENSIONS)
    except Exception:
        return 0


def _announcement_pack_notice(root: Path | None, airline: str) -> dict[str, Any]:
    roots: list[Path] = []
    if root:
        roots.append(root)
    roots.extend(_built_in_announcement_roots())
    default_available = any(_folder_audio_count(candidate / "Default") or _folder_audio_count(candidate / "DEFAULT") for candidate in roots)
    raw_airline = str(airline or "").strip().upper()
    if not raw_airline or raw_airline.startswith("DEFA"):
        return {
            "airline_pack_available": True,
            "using_default_announcements": True,
            "announcement_notice": "Using default announcement pack." if default_available else "No default announcement pack found.",
        }
    airline = _clean_airline(raw_airline)
    airline_available = any(_folder_audio_count(candidate / airline) for candidate in roots)
    using_default = not airline_available and default_available
    if using_default:
        notice = "No announcement pack was found for this airline. OPS ROOM is using the default announcement pack."
    elif airline_available:
        notice = "Airline announcement pack loaded."
    else:
        notice = "No announcement audio pack was found. Add an airline pack or restore Announcements\\Default."
    return {
        "airline_pack_available": airline_available,
        "using_default_announcements": using_default,
        "announcement_notice": notice,
    }


def _event_folders(root: Path | None, airline: str) -> list[Path]:
    folders: list[Path] = []
    if root:
        if airline and airline.upper() != "DEFAULT":
            folders.append(root / airline)
        folders.extend([root / "Default", root / "DEFAULT", root])
    for built_root in _built_in_announcement_roots():
        if airline and airline.upper() != "DEFAULT":
            folders.append(built_root / airline)
        folders.extend([built_root / "Default", built_root / "DEFAULT", built_root])
    result: list[Path] = []
    seen: set[str] = set()
    for folder in folders:
        try:
            key = str(folder.resolve()).lower()
        except Exception:
            key = str(folder).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(folder)
    return result


def _files_for_event(event: str) -> list[Path]:
    root = _root()
    airline, _callsign, _source = _announcement_identity()
    for folder in _event_folders(root, airline):
        if not folder.is_dir():
            continue
        hits = [
            p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in _AUDIO_EXTENSIONS
        ]
        result = _compatible_event_files(event, hits)
        if result:
            return result
    return []


def _poll_camera_distance() -> float:
    global _CAMERA_DISTANCE, _CAMERA_LAST_POLL
    now = time.monotonic()
    if now - _CAMERA_LAST_POLL < 1.5:
        return _CAMERA_DISTANCE
    _CAMERA_LAST_POLL = now
    distance: float | None = None
    try:
        from .camera_bridge import _status_path as _cb_status_path
        status_path = _cb_status_path()
        if status_path.exists():
            raw = json.loads(status_path.read_text(encoding="utf-8"))
            cx = float(raw.get("cameraPosX") or 0)
            cy = float(raw.get("cameraPosY") or 0)
            cz = float(raw.get("cameraPosZ") or 0)
            if cx or cy or cz:
                distance = math.sqrt(cx * cx + cy * cy + cz * cz)
    except Exception:
        pass
    if distance is None:
        try:
            from .simconnect_position import simconnect_diagnostics, _ensure_session
            diag = simconnect_diagnostics()
            if diag.get("session_connected"):
                _, aq = _ensure_session(diag)
                px = float(aq.get("CAMERA POS X") or 0)
                py = float(aq.get("CAMERA POS Y") or 0)
                pz = float(aq.get("CAMERA POS Z") or 0)
                if px or py or pz:
                    distance = math.sqrt(px * px + py * py + pz * pz)
                else:
                    ex = float(aq.get("EYEPOINT X") or 0)
                    ey = float(aq.get("EYEPOINT Y") or 0)
                    ez = float(aq.get("EYEPOINT Z") or 0)
                    if ex or ey or ez:
                        distance = math.sqrt(ex * ex + ey * ey + ez * ez)
        except Exception:
            pass
    if distance is not None:
        _CAMERA_DISTANCE = distance
    return _CAMERA_DISTANCE

_LAST_CAMERA_CATEGORY: str = "cockpit"  # #72: re-apply trigger for camera volume


def _camera_category() -> str:
    """Volume category from the shared snapshot's ``camera_state`` (#55).

    The Stage-2 writer already reads FSUIPC 0x026D at its 10-30 Hz cadence, so
    this is a pure cache read -- zero extra SimConnect/FSUIPC traffic. Non-flight
    camera states (menus, world map, replay) hold the last-known category so the
    PA volume does not snap while tabbing out.
    """
    global _CAMERA_CATEGORY
    # #80: prefer the authoritative SimConnect CAMERA_STATE; the FSUIPC 0x026D
    # offset does not reliably track MSFS2024 external camera states, so it is
    # only the fallback. Both map through the same category table.
    state: int | None = None
    try:
        from .simconnect_position import camera_state_simconnect
        sc_state = camera_state_simconnect()
        if sc_state is not None and sc_state in _CAMERA_STATE_CATEGORY:
            state = int(sc_state)
    except Exception:
        state = None
    if state is None:
        try:
            state = int((read_telemetry(force=False) or {}).get("camera_state") or 0)
        except Exception:
            state = 0
    category = _CAMERA_STATE_CATEGORY.get(state)
    if category:
        _CAMERA_CATEGORY = category
        return category
    # Unknown/menu/replay state: hold the last-known category, defaulting to
    # the cockpit (the pilot view at startup) before any state has been seen.
    return _CAMERA_CATEGORY or "cockpit"


def _camera_volume_multiplier() -> float:
    """Camera-view volume based on the ACTIVE CAMERA STATE (UA parity, #55).

    The category decides which of the three existing sliders applies -- Cockpit
    (states 2/7), Cabin (9) or External (3/4/5/6/8/10/19). The old world-distance
    curve is gone: it computed ``sqrt(cx^2+cy^2+cz^2)`` of the camera's WORLD
    position (~1.4e6 m from the planet origin at a European airport), so the
    multiplier was pinned to the external floor forever. The three sliders
    (`camera_volume_cockpit`, `camera_volume_cabin`, `camera_volume_external`)
    keep their existing 0-100 % semantics so user configurations carry over.
    """
    settings = load_settings().get("integrations", {})
    if not bool(settings.get("camera_volume_enabled", False)):
        return 1.0
    cockpit_pct = max(0.0, min(int(settings.get("camera_volume_cockpit", 100)) / 100.0, 1.0))
    cabin_pct = max(0.0, min(int(settings.get("camera_volume_cabin", 70)) / 100.0, 1.0))
    external_pct = max(0.0, min(int(settings.get("camera_volume_external", 40)) / 100.0, 1.0))
    pct = {"cockpit": cockpit_pct, "cabin": cabin_pct, "external": external_pct}.get(_camera_category(), external_pct)
    return max(0.0, min(pct, 1.0))

def _mixer_volume() -> tuple[float, bool]:
    volume = int(load_settings().get("integrations", {}).get("announcements_volume", 80)) / 100.0
    multiplier = _camera_volume_multiplier()
    volume = volume * multiplier
    return max(0.0, min(volume, 1.0)), bool(_STATE.get("muted"))


def _set_music_relative(multiplier: float) -> None:
    try:
        import pygame  # type: ignore
        if not pygame.mixer.get_init():
            return
        volume, muted = _mixer_volume()
        pygame.mixer.music.set_volume(0.0 if muted else max(0.0, min(volume * _MUSIC_CHANNEL_VOLUME * multiplier, 1.0)))
    except Exception:
        pass


def _duck_music_for(seconds: float, reason: str = "PA") -> None:
    global _MUSIC_DUCKED
    if not _BOARDING_MUSIC_ACTIVE:
        return
    _MUSIC_DUCKED = True
    _set_music_relative(_MUSIC_DUCK_LEVEL)
    def restore() -> None:
        global _MUSIC_DUCKED
        time.sleep(max(0.8, float(seconds or 0) + 0.35))
        with _LOCK:
            if _BOARDING_MUSIC_ACTIVE and not _pa_busy():
                _MUSIC_DUCKED = False
                _set_music_relative(1.0)
                _record("MIX", f"Boarding music restored after {reason}")
    threading.Thread(target=restore, name="OpsRoom-Announcement-Duck", daemon=True).start()


def _ensure_mixer():
    import pygame  # type: ignore
    if not pygame.mixer.get_init():
        pygame.mixer.init()
    if pygame.mixer.get_num_channels() <= _PA_CHANNEL_INDEX:
        pygame.mixer.set_num_channels(_PA_CHANNEL_INDEX + 4)
    return pygame


def _pa_channel():
    pygame = _ensure_mixer()
    return pygame.mixer.Channel(_PA_CHANNEL_INDEX)


def _pa_busy() -> bool:
    try:
        return bool(_pa_channel().get_busy())
    except Exception:
        return False


def _record_completion_later(event: str, seconds: float) -> None:
    def complete() -> None:
        time.sleep(max(0.1, float(seconds or 0) + 0.15))
        with _LOCK:
            # Do not depend on last_event here. Automation can queue the next
            # event while this one is still playing; completion belongs to the
            # actual sound duration, not to the latest queued event label.
            if not _pa_busy():
                _PREVIOUS[f"completed_{event}_at"] = time.monotonic()
                _record("COMPLETE", f"{event} playback complete")
    threading.Thread(target=complete, name="OpsRoom-Announcement-Complete", daemon=True).start()


def _play_file(path: Path, event: str) -> dict[str, Any]:
    global _CURRENT_PA_SOUND
    try:
        _record("QUEUED", f"{event}: {path.name}")
        pygame = _ensure_mixer()
        volume, muted = _mixer_volume()
        channel = pygame.mixer.Channel(_PA_CHANNEL_INDEX)
        channel.set_volume(0.0 if muted else volume)
        _record("STARTING", f"{event}: mixer channel {_PA_CHANNEL_INDEX}")
        sound = pygame.mixer.Sound(str(path))
        length = float(sound.get_length() or 0.0)
        if _BOARDING_MUSIC_ACTIVE and event not in {"BoardingMusic"}:
            _duck_music_for(length, event)
        _CURRENT_PA_SOUND = sound
        channel.play(sound)
        _STATE.update({"playing": True, "paused": False, "last_file": str(path), "last_event": event, "last_error": None})
        _record("PLAYING", f"{event}: {path.name} ({length:.1f}s)")
        _record_completion_later(event, length)
        return {"ok": True, "event": event, "file": str(path), "channel": "pa", "duration_seconds": length}
    except Exception as exc:
        _STATE["last_error"] = f"{type(exc).__name__}: {exc}"
        _record("FAILED", f"{event}: {_STATE['last_error']}")
        return {"ok": False, "reason": _STATE["last_error"]}



def _mixer_stop_all(*, quit_mixer: bool = False) -> None:
    """Stop every pygame audio path OPS ROOM may own.

    BoardingMusic uses pygame.mixer.music while PA calls use a mixer Channel. Older
    builds only stopped one path, which allowed music to survive STOP/MUTE/Exit.
    """
    try:
        import pygame  # type: ignore
        if not pygame.mixer.get_init():
            return
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass
        try:
            pygame.mixer.stop()
        except Exception:
            pass
        try:
            for index in range(max(8, int(pygame.mixer.get_num_channels() or 0))):
                try:
                    pygame.mixer.Channel(index).stop()
                except Exception:
                    pass
        except Exception:
            pass
        if quit_mixer:
            try:
                pygame.mixer.quit()
            except Exception:
                pass
    except Exception:
        pass


def _drain_audio_queue() -> None:
    try:
        while True:
            _AUDIO_QUEUE.get_nowait()
    except queue.Empty:
        pass
    with _LOCK:
        _QUEUED_EVENTS.clear()


def hard_kill_audio(reason: str = "hard stop", *, shutdown: bool = False) -> dict[str, Any]:
    global _BOARDING_PHASE_ACTIVE, _BOARDING_MUSIC_ACTIVE, _NEXT_WELCOME_AT, _BOARDING_MUSIC_DUE_AT, _AUDIO_HARD_STOPPED, _CURRENT_PA_SOUND
    _drain_audio_queue()
    with _LOCK:
        _BOARDING_PHASE_ACTIVE = False
        _BOARDING_MUSIC_ACTIVE = False
        _NEXT_WELCOME_AT = 0.0
        _BOARDING_MUSIC_DUE_AT = 0.0
        _CURRENT_PA_SOUND = None
        _AUDIO_HARD_STOPPED = True
        _STATE["playing"] = False
        _STATE["paused"] = False
        _mixer_stop_all(quit_mixer=shutdown)
        _record("KILL", f"Audio engine stopped ({reason})")
    return {"ok": True, "hard_stopped": True, "shutdown": shutdown}


def _next_boarding_welcome_delay() -> float:
    return random.uniform(_BOARDING_WELCOME_MIN_SECONDS, _BOARDING_WELCOME_MAX_SECONDS)


def _start_boarding_music(reason: str = "boarding") -> None:
    """Schedule boarding ambience 30 seconds after boarding is detected."""
    global _BOARDING_PHASE_ACTIVE, _BOARDING_MUSIC_ACTIVE, _NEXT_WELCOME_AT, _BOARDING_MUSIC_DUE_AT, _AUDIO_HARD_STOPPED
    if _AUDIO_HARD_STOPPED:
        _record("BLOCKED", f"Boarding audio suppressed after STOP ({reason})")
        return
    if not _boarding_audio_allowed():
        return
    now = time.monotonic()
    if not _BOARDING_PHASE_ACTIVE:
        _BOARDING_PHASE_ACTIVE = True
        _BOARDING_MUSIC_DUE_AT = now + 30.0
        _NEXT_WELCOME_AT = now + _next_boarding_welcome_delay()
        _record("BOARDING", f"Boarding phase started ({reason}); music starts in 30 seconds")
        _record("MUSIC TIMER", "BoardingMusic due in 30s")
    elif not _BOARDING_MUSIC_ACTIVE and not _BOARDING_MUSIC_DUE_AT:
        _BOARDING_MUSIC_DUE_AT = now + 10.0
        _record("MUSIC TIMER", "BoardingMusic timer re-armed for active boarding phase")


def _start_boarding_music_now(reason: str = "boarding") -> None:
    global _BOARDING_MUSIC_ACTIVE
    if _BOARDING_MUSIC_ACTIVE or not _BOARDING_PHASE_ACTIVE or not _boarding_audio_allowed():
        return
    files = _files_for_event("BoardingMusic")
    if not files:
        _record("MUSIC", "No BoardingMusic file found; continuing with welcome timer only")
        return
    try:
        pygame = _ensure_mixer()
        volume, muted = _mixer_volume()
        pygame.mixer.music.set_volume(0.0 if muted else max(0.0, min(volume * _MUSIC_CHANNEL_VOLUME * (_MUSIC_DUCK_LEVEL if _MUSIC_DUCKED else 1.0), 1.0)))
        path = random.choice(files)
        pygame.mixer.music.load(str(path))
        pygame.mixer.music.play(loops=-1)
        _BOARDING_MUSIC_ACTIVE = True
        _STATE.update({"playing": True, "paused": False, "last_file": str(path), "last_event": "BoardingMusic", "last_error": None})
        _record("MUSIC", f"Boarding music started ({reason}): {path.name}")
    except Exception as exc:
        _STATE["last_error"] = f"{type(exc).__name__}: {exc}"
        _record("FAULT", _STATE["last_error"])


def trigger_boarding_service(reason: str = "jetway/stairs requested") -> dict[str, Any]:
    """Start boarding ambience from an explicit jetway/stairs request when pre-departure only."""
    global _AUDIO_HARD_STOPPED, _ARRIVAL_COMPLETE
    if "manual" in str(reason).lower():
        _AUDIO_HARD_STOPPED = False
    if not _boarding_audio_allowed():
        _record("BLOCKED", f"Boarding audio blocked outside pre-departure phase: {reason}")
        status = dict(_STATE)
        status.update({"ok": False, "blocked": True, "reason": "Boarding audio is only allowed before departure"})
        return status
    _start_boarding_music(reason)
    status = dict(_STATE)
    status["ok"] = bool(_BOARDING_PHASE_ACTIVE)
    status["trigger"] = reason
    status["music_starts_in_seconds"] = 30
    status["next_welcome_seconds"] = int(max(0, _NEXT_WELCOME_AT - time.monotonic()))
    return status

def _stop_boarding_music(reason: str = "completed") -> None:
    global _BOARDING_PHASE_ACTIVE, _BOARDING_MUSIC_ACTIVE, _NEXT_WELCOME_AT, _BOARDING_MUSIC_DUE_AT
    if not _BOARDING_PHASE_ACTIVE and not _BOARDING_MUSIC_ACTIVE:
        return
    _BOARDING_PHASE_ACTIVE = False
    _NEXT_WELCOME_AT = 0.0
    _BOARDING_MUSIC_DUE_AT = 0.0
    if _BOARDING_MUSIC_ACTIVE:
        try:
            pygame = _ensure_mixer()
            pygame.mixer.music.stop()
        except Exception:
            pass
    _BOARDING_MUSIC_ACTIVE = False
    _record("MUSIC", f"Boarding audio stopped ({reason})")

def _dequeue_audio_event() -> bool:
    """Play at most one queued PA event from the background worker.

    API routes and automation triggers must never block on pygame/mixer. They
    enqueue here, and this worker performs the slow/fragile audio work.
    """
    global _AUDIO_FAILURES, _AUDIO_CIRCUIT_OPEN_UNTIL
    if _pa_busy():
        return False
    try:
        item = _AUDIO_QUEUE.get_nowait()
    except queue.Empty:
        return False
    event = str(item.get("event") or "")
    with _LOCK:
        _QUEUED_EVENTS.discard(event)
    try:
        if time.monotonic() < _AUDIO_CIRCUIT_OPEN_UNTIL:
            _record("AUDIO SKIPPED", f"{event}: audio circuit breaker active")
            return True
        path = Path(str(item.get("file") or ""))
        if not path.is_file():
            files = _files_for_event(event)
            path = random.choice(files) if files else path
        if not path.is_file():
            _STATE["last_error"] = f"No compatible {event} file found"
            _record("AUDIO FAILED", _STATE["last_error"])
            return True
        result = _play_file(path, event)
        if result.get("ok"):
            _AUDIO_FAILURES = 0
            if item.get("record") and not item.get("manual"):
                _PLAYED.add(event)
            if item.get("manual"):
                _STATE["mode"] = "automatic"
                _record("MANUAL", f"Manual one-shot queued and played: {event}")
        else:
            _AUDIO_FAILURES += 1
            if _AUDIO_FAILURES >= 3:
                _AUDIO_CIRCUIT_OPEN_UNTIL = time.monotonic() + 20.0
                _record("AUDIO CIRCUIT", "Audio backend failed repeatedly; pausing playback attempts for 20 seconds")
        return True
    except Exception as exc:
        _AUDIO_FAILURES += 1
        _STATE["last_error"] = f"{type(exc).__name__}: {exc}"
        _record("AUDIO FAILED", f"{event}: {_STATE['last_error']}")
        if _AUDIO_FAILURES >= 3:
            _AUDIO_CIRCUIT_OPEN_UNTIL = time.monotonic() + 20.0
        return True


def play_event(event: str, force: bool = False, *, manual: bool = False, record: bool = True) -> dict[str, Any]:
    event = str(event or "").strip()
    # Backward-compatible API names are canonicalized before file discovery;
    # file selection still remains exact to the canonical base filename.
    event = {"Landing": "AfterLanding", "BoardingCompleted": "BoardingComplete"}.get(event, event)
    if not event:
        return {"ok": False, "reason": "Announcement event is required"}
    if event not in _CABIN_ANNOUNCEMENT_EVENTS:
        _record("ANN_SKIPPED", f"{event}: non-cabin GSX/service event has no audio path")
        return {"ok": True, "skipped": True, "event": event, "reason": "Non-cabin service event; audio not required"}
    with _LOCK:
        if not manual and not force and event in _PLAYED:
            return {"ok": True, "skipped": True, "reason": "Already played in this flight", "event": event}
        if not manual and not force and event in _QUEUED_EVENTS:
            return {"ok": True, "queued": True, "skipped": True, "reason": "Already queued in this flight", "event": event}
        files = _files_for_event(event)
        if not files:
            _record("AUDIO FAILED", f"{event}: no compatible file found")
            return {"ok": False, "reason": f"No compatible {event} file found", "event": event}
        item = {"event": event, "file": str(random.choice(files)), "manual": bool(manual), "record": bool(record), "queued_at": _utc()}
        # v0.24.28: do not add avoidable latency. If the PA channel and queue
        # are idle, play this clip now; queue only when another PA clip is active
        # or sequencing has already put an item in front of it.
        if not _pa_busy() and _AUDIO_QUEUE.empty():
            result = _play_file(Path(str(item.get("file") or "")), event)
            if result.get("ok"):
                if not manual and record:
                    _PLAYED.add(event)
                _STATE.update({"last_event": event, "last_error": None})
                _record("ANN_PLAY_IMMEDIATE", f"{event} played immediately from {'manual' if manual else 'automation'}")
                return {"ok": True, "playing": True, "event": event}
        try:
            _AUDIO_QUEUE.put_nowait(item)
        except queue.Full:
            return {"ok": False, "reason": "Announcement queue is full", "event": event}
        if not manual and record:
            _QUEUED_EVENTS.add(event)
        _STATE.update({"last_event": event, "last_error": None})
        _record("ANN_QUEUE_ACCEPTED", f"{event} queued from {'manual' if manual else 'automation'}")
        return {"ok": True, "queued": True, "event": event}


def stop_audio() -> dict[str, Any]:
    return hard_kill_audio("user stop", shutdown=False)


def shutdown_engine() -> dict[str, Any]:
    _STOP.set()
    result = hard_kill_audio("application shutdown", shutdown=True)
    try:
        thread = _THREAD
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
    except Exception:
        pass
    _STATE["running"] = False
    return result



def toggle_pause() -> dict[str, Any]:
    try:
        pygame = _ensure_mixer()
        if not _STATE.get("playing"):
            return {"ok": False, "reason": "No announcement is currently playing"}
        channel = pygame.mixer.Channel(_PA_CHANNEL_INDEX)
        if _STATE.get("paused"):
            pygame.mixer.music.unpause()
            channel.unpause()
            _STATE["paused"] = False
            _record("RESUME", "Announcement audio resumed")
        else:
            pygame.mixer.music.pause()
            channel.pause()
            _STATE["paused"] = True
            _record("PAUSE", "Announcement audio paused")
        return {"ok": True, "paused": bool(_STATE.get("paused"))}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def set_muted(muted: bool | None = None) -> dict[str, Any]:
    desired = (not bool(_STATE.get("muted"))) if muted is None else bool(muted)
    _STATE["muted"] = desired
    try:
        import pygame  # type: ignore
        if pygame.mixer.get_init():
            volume = int(load_settings().get("integrations", {}).get("announcements_volume", 80)) / 100.0
            pygame.mixer.music.set_volume(0.0 if desired else max(0.0, min(volume * _MUSIC_CHANNEL_VOLUME, 1.0)))
            for index in range(max(8, int(pygame.mixer.get_num_channels() or 0))):
                try:
                    pygame.mixer.Channel(index).set_volume(0.0 if desired else max(0.0, min(volume if index == _PA_CHANNEL_INDEX else volume * _MUSIC_CHANNEL_VOLUME, 1.0)))
                except Exception:
                    pass
    except Exception:
        pass
    _record("MUTE" if desired else "UNMUTE", "Announcement audio muted" if desired else "Announcement audio restored")
    return {"ok": True, "muted": desired}


def apply_runtime_settings() -> dict[str, Any]:
    """Apply settings that can change while the audio engine is already running."""
    volume = int(load_settings().get("integrations", {}).get("announcements_volume", 80)) / 100.0
    muted = bool(_STATE.get("muted"))
    volume = volume * _camera_volume_multiplier()
    _STATE["volume"] = int(round(volume * 100))
    try:
        import pygame  # type: ignore
        if pygame.mixer.get_init():
            pygame.mixer.music.set_volume(0.0 if muted else max(0.0, min(volume * _MUSIC_CHANNEL_VOLUME * (_MUSIC_DUCK_LEVEL if _MUSIC_DUCKED else 1.0), 1.0)))
            for index in range(max(8, int(pygame.mixer.get_num_channels() or 0))):
                try:
                    pygame.mixer.Channel(index).set_volume(0.0 if muted else max(0.0, min(volume if index == _PA_CHANNEL_INDEX else volume * _MUSIC_CHANNEL_VOLUME, 1.0)))
                except Exception:
                    pass
    except ModuleNotFoundError:
        # Source/dev environments may not have pygame installed. The packaged app does.
        pass
    except Exception as exc:
        _STATE["last_error"] = f"{type(exc).__name__}: {exc}"
        return {"ok": False, "reason": _STATE["last_error"], "volume": _STATE["volume"], "muted": muted}
    return {"ok": True, "volume": _STATE["volume"], "muted": muted}

def reset_flight() -> None:
    global _EVER_AIRBORNE, _ARRIVAL_COMPLETE, _AUDIO_HARD_STOPPED
    global _SESSION_READY, _SESSION_GROUND_STABLE_SAMPLES, _SESSION_AIRBORNE_SAMPLES, _TAKEOFF_ROLL_SEEN, _TAKEOFF_CONFIRMED, _ANN_AIRBORNE_STARTED_AT, _ANN_DESCENT_SAMPLES, _ANN_VALID_PHASE, _TAXI_OUT_SUSTAINED_SAMPLES, _BOARDING_MOVEMENT_SAMPLES
    with _LOCK:
        _PLAYED.clear()
        _QUEUED_EVENTS.clear()
        _PREVIOUS.clear()
        _READY_SAMPLES.clear()
        _EVER_AIRBORNE = False
        _ARRIVAL_COMPLETE = False
        _AUDIO_HARD_STOPPED = False
        _SESSION_READY = False
        _SESSION_GROUND_STABLE_SAMPLES = 0
        _SESSION_AIRBORNE_SAMPLES = 0
        _TAKEOFF_ROLL_SEEN = False
        _TAKEOFF_CONFIRMED = False
        _ANN_AIRBORNE_STARTED_AT = 0.0
        _ANN_DESCENT_SAMPLES = 0
        _ANN_VALID_PHASE = "GROUND"
        _TAXI_OUT_SUSTAINED_SAMPLES = 0
        _BOARDING_MOVEMENT_SAMPLES = 0
        _stop_boarding_music("flight reset")
    _drain_audio_queue()
    with _LOCK:
        _record("RESET", "Flight announcement sequence reset")


def _auto_play(event: str, *, force: bool = False, repeatable: bool = False) -> dict[str, Any]:
    return play_event(event, force=force, manual=False, record=not repeatable)


def _altitude_reliable(t: dict[str, Any]) -> bool:
    try:
        if t.get("altitude_unreliable") is True:
            return False
        if str(t.get("altitude_confidence") or "").lower() in {"invalid", "unreliable"}:
            return False
        alt = float(t.get("altitude_ft") if t.get("altitude_ft") is not None else t.get("indicated_altitude_ft"))
        agl = float(t.get("radio_altitude_ft") if t.get("radio_altitude_ft") is not None else t.get("agl_ft") or 0.0)
        gs = float(t.get("ground_speed_kts") or 0.0)
        ias = float(t.get("indicated_speed_kts") or 0.0)
        if agl > 1000 and (gs > 100 or ias > 100) and (abs(alt) < 500 or alt + 1000 < agl):
            return False
        return True
    except Exception:
        return False


def _gsx_boarding_status(gsx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return passenger-boarding state without letting bags impersonate pax.

    GSX can publish a stale legacy raw value beside a fresher Remote API row. An
    explicit pax counter below target always wins: boarding is still active and
    cannot be completed by bags 100%, cargo completion or a waiting Departure
    request.
    """
    if gsx is None:
        try:
            from .gsx_remote import status as gsx_status
            gsx = gsx_status(force=False)
        except Exception:
            gsx = {}
    services = gsx.get("services") if isinstance(gsx, dict) and isinstance(gsx.get("services"), dict) else {}
    progress = gsx.get("progress") if isinstance(gsx, dict) and isinstance(gsx.get("progress"), dict) else {}
    row = services.get("boarding") if isinstance(services, dict) and isinstance(services.get("boarding"), dict) else {}
    try:
        raw = int(row.get("raw") or 0)
    except Exception:
        raw = 0
    state = str(row.get("remote_state") or row.get("state") or "").strip().lower().replace("-", "_").replace(" ", "_")
    text = " ".join(str(row.get(key) or "") for key in ("progress_text", "status_text", "waiting_reason", "label"))

    def _number(value: Any) -> float | None:
        try:
            result = float(value)
            return result if math.isfinite(result) else None
        except Exception:
            return None

    current = _number(progress.get("passengers_boarding_total"))
    total = _number(progress.get("passengers_target"))
    row_progress = row.get("progress") if isinstance(row.get("progress"), dict) else {}
    if current is None:
        current = _number(row_progress.get("current", row_progress.get("done")))
    if total is None or total <= 0:
        total = _number(row_progress.get("total", row_progress.get("target")))
    match = re.search(r"(?:pax|passengers?)\s*(?::|=)?\s*(\d+)\s*/\s*(\d+)", text, re.I)
    if match:
        current = float(match.group(1))
        total = float(match.group(2))

    explicit_incomplete = bool(total is not None and total > 0 and current is not None and current < total)
    explicit_complete = bool(total is not None and total > 0 and current is not None and current >= total)
    active = bool(
        explicit_incomplete
        or raw in {4, 5, 7}
        or state in {"requested", "performing", "completing", "waiting", "active", "in_progress"}
    )
    complete = bool(
        explicit_complete
        or (not explicit_incomplete and (raw == 6 or state in {"completed", "bypassed"}))
    )
    return {
        "raw": raw, "state": state, "current": current, "total": total,
        "active": active and not complete, "complete": complete,
        "explicit_incomplete": explicit_incomplete,
    }


def _service_is_physical_departure_active(row: dict[str, Any] | None) -> bool:
    if not isinstance(row, dict):
        return False
    try:
        raw = int(row.get("raw") or 0)
    except Exception:
        raw = 0
    state = str(row.get("remote_state") or row.get("state") or "").strip().lower().replace("-", "_").replace(" ", "_")
    waiting = bool(row.get("waiting"))
    text = " ".join(str(row.get(key) or "") for key in ("status_text", "progress_text", "waiting_reason", "label")).lower()
    # Remote API may expose a waiting Departure row through a legacy raw value
    # that resembles COMPLETING. A requested service waiting for Boarding is not
    # physical pushback and must not stop cabin audio or arm the doors.
    if waiting or state in {"available", "requested", "waiting"}:
        return False
    if re.search(r"waiting\s+for\s+(?:passenger\s+)?boarding|departure\s+service\s+has\s+been\s+requested", text):
        return False
    if state in {"performing", "completing", "active", "in_progress"}:
        return True
    return raw in {5, 7}


def _gsx_pushback_active_status() -> bool:
    try:
        from .gsx_remote import status as gsx_status
        gsx = gsx_status(force=False)
    except Exception:
        return False
    if not gsx.get("ok") or not gsx.get("connected"):
        return False
    boarding = _gsx_boarding_status(gsx)
    if boarding.get("explicit_incomplete"):
        return False
    services = gsx.get("services") or {}
    return any(_service_is_physical_departure_active(services.get(key)) for key in ("pushback", "departure"))



def _confirmed_departure_movement(pushback_active: bool, on_ground: bool, ground_speed_kts: float) -> bool:
    global _BOARDING_MOVEMENT_SAMPLES
    gs = max(0.0, float(ground_speed_kts or 0.0))
    if on_ground and gs >= 1.5:
        _BOARDING_MOVEMENT_SAMPLES += 1
    elif gs <= 0.8:
        _BOARDING_MOVEMENT_SAMPLES = 0
    return bool(pushback_active or _BOARDING_MOVEMENT_SAMPLES >= 3)

def _engines_off(systems: dict[str, Any]) -> bool:
    if systems.get("engines_running") is True:
        return False
    engines = systems.get("engines")
    if isinstance(engines, list) and engines:
        return not any(bool(x) for x in engines)
    n1 = systems.get("n1_percent") or systems.get("engine_n1_percent")
    if isinstance(n1, (list, tuple)) and n1:
        try:
            return max(float(x or 0) for x in n1) < 3.0
        except Exception:
            pass
    return not bool(systems.get("engines_running"))


def _service_boarding_timers() -> None:
    global _NEXT_WELCOME_AT
    now = time.monotonic()
    if not _BOARDING_PHASE_ACTIVE or not _boarding_audio_allowed():
        return
    if not _BOARDING_MUSIC_ACTIVE and _BOARDING_MUSIC_DUE_AT and now >= _BOARDING_MUSIC_DUE_AT:
        _start_boarding_music_now("independent boarding timer elapsed")
    if not _BOARDING_MUSIC_ACTIVE and _BOARDING_MUSIC_DUE_AT and now >= _BOARDING_MUSIC_DUE_AT + 15.0:
        _record("MUSIC", "Boarding music due but inactive; retrying")
        _start_boarding_music_now("independent retry after due timer")
    if _NEXT_WELCOME_AT and now >= _NEXT_WELCOME_AT:
        _auto_play("BoardingWelcome", force=True, repeatable=True)
        _NEXT_WELCOME_AT = now + _next_boarding_welcome_delay()


def _completed(event: str) -> bool:
    return bool(_PREVIOUS.get(f"completed_{event}_at"))


def _crossed_down(previous: float, current: float, gate: float, *, tolerance: float = 150.0) -> bool:
    return previous > gate + tolerance and current <= gate


def _parked_at_gate(on_ground: bool, gs: float, parking_brake: bool, systems: dict[str, Any]) -> bool:
    return bool(on_ground and gs < 0.8 and parking_brake and _engines_off(systems))


def _active_recorder_phase() -> str:
    global _RECORDER_PHASE_CACHE
    now = time.monotonic()
    cached_at, cached_phase = _RECORDER_PHASE_CACHE
    if now - cached_at < 0.75:
        return cached_phase
    phase = ""
    try:
        from .logbook import status as logbook_status
        active = (logbook_status(limit=1).get("active") or {})
        phase = str(active.get("current_phase") or "").upper()
    except Exception:
        phase = ""
    _RECORDER_PHASE_CACHE = (now, phase)
    return phase


def _trigger_from_telemetry(t: dict[str, Any]) -> None:
    global _EVER_AIRBORNE, _ARRIVAL_COMPLETE, _NEXT_WELCOME_AT, _BOARDING_MUSIC_DUE_AT
    global _SESSION_AIRBORNE_SAMPLES, _TAKEOFF_ROLL_SEEN, _TAKEOFF_CONFIRMED, _ANN_AIRBORNE_STARTED_AT, _ANN_DESCENT_SAMPLES, _ANN_VALID_PHASE, _BOARDING_MOVEMENT_SAMPLES
    if not _auto_sim_live(t):
        return
    if not _telemetry_ready(t):
        return
    if not _stable_live_session(t):
        _record_suppressed("Announcements waiting for a stable flight session")
        return
    systems = t.get("systems") or {}
    if not isinstance(t.get("on_ground"), bool):
        _record_suppressed("Auto announcements waiting for validated on-ground state")
        return
    on_ground = bool(t.get("on_ground"))
    gs = float(t.get("ground_speed_kts") or 0)
    ias = float(t.get("indicated_speed_kts") or 0)
    agl = float(t.get("agl_ft") or 0)
    vs = float(t.get("vertical_speed_fpm") or 0)
    engines = bool(systems.get("engines_running"))
    parking_brake = systems.get("parking_brake_set")
    if parking_brake is None:
        parking_brake = systems.get("parking_brake")
    parking_brake = bool(parking_brake)
    seatbelt_switch = systems.get("seatbelt_switch")
    global _SEATBELT_SIMVAR_CHANGED
    previous_seatbelt = _PREVIOUS.get("seatbelt_switch")
    if isinstance(seatbelt_switch, bool) and isinstance(previous_seatbelt, bool) and seatbelt_switch != previous_seatbelt:
        _SEATBELT_SIMVAR_CHANGED = True
    previous_ground = _PREVIOUS.get("on_ground")
    previous_agl = float(_PREVIOUS.get("agl") or 0)
    previous_altitude = float(_PREVIOUS.get("altitude") or 0)
    altitude_raw = float(t.get("altitude_ft") if t.get("altitude_ft") is not None else t.get("indicated_altitude_ft") or 0.0)
    altitude = altitude_raw if _altitude_reliable(t) else 0.0
    recorder_phase = _active_recorder_phase() or str(t.get("recorder_phase") or t.get("flight_phase") or t.get("phase") or t.get("movement_phase") or "").upper()

    if on_ground and engines and gs >= 35.0:
        _TAKEOFF_ROLL_SEEN = True

    confirmed_airborne = _confirmed_airborne_sample(t, on_ground=on_ground, agl=agl, gs=gs, ias=ias, vs=vs)
    if confirmed_airborne and (_TAKEOFF_ROLL_SEEN or previous_ground is True or _PREVIOUS.get("takeoff_roll_seen")):
        _SESSION_AIRBORNE_SAMPLES += 1
    elif on_ground:
        _SESSION_AIRBORNE_SAMPLES = 0
    if _SESSION_AIRBORNE_SAMPLES >= 3:
        _EVER_AIRBORNE = True
        _TAKEOFF_CONFIRMED = True
        if not _ANN_AIRBORNE_STARTED_AT:
            _ANN_AIRBORNE_STARTED_AT = now if 'now' in locals() else time.monotonic()

    # Keep an independent, monotonic cabin phase guard. Once descent is
    # confirmed, level-offs must remain DESCENT; do not bounce back to CRUISE.
    if on_ground:
        _ANN_VALID_PHASE = "GROUND"
        _ANN_DESCENT_SAMPLES = 0
    elif _TAKEOFF_CONFIRMED:
        if recorder_phase in {"DESCENT", "APPROACH", "FINAL APPROACH"}:
            _ANN_VALID_PHASE = "DESCENT"
            _ANN_DESCENT_SAMPLES = max(_ANN_DESCENT_SAMPLES, 4)
        elif _ANN_VALID_PHASE == "DESCENT":
            # Step descents, holds and level-offs during arrival stay descent.
            _ANN_VALID_PHASE = "DESCENT"
        elif _ANN_VALID_PHASE in {"GROUND", "TAKEOFF", "INITIAL CLIMB"} or vs > 150:
            _ANN_VALID_PHASE = "INITIAL CLIMB"
        elif altitude >= 10000 and abs(vs) < 350:
            _ANN_VALID_PHASE = "CRUISE"
        elif _ANN_VALID_PHASE not in {"CRUISE", "ENROUTE", "DESCENT"} and altitude < 10000:
            _ANN_VALID_PHASE = "CLIMB"
        if _ANN_VALID_PHASE != "DESCENT":
            if vs < -300 and _ANN_VALID_PHASE in {"CRUISE", "ENROUTE"} and _ANN_AIRBORNE_STARTED_AT and time.monotonic() - _ANN_AIRBORNE_STARTED_AT >= 240.0 and _altitude_reliable(t) and altitude < previous_altitude - 20.0:
                _ANN_DESCENT_SAMPLES += 1
            elif vs > -100:
                _ANN_DESCENT_SAMPLES = 0
            if _ANN_DESCENT_SAMPLES >= 4:
                _ANN_VALID_PHASE = "DESCENT"

    if abs(float(t.get("lat") or 0)) < .001 and abs(float(t.get("lon") or 0)) < .001:
        return

    now = time.monotonic()
    boarding_status_live = _gsx_boarding_status()
    boarding_explicitly_incomplete = bool(boarding_status_live.get("explicit_incomplete"))
    pushback_active_live = _gsx_pushback_active_status()
    if pushback_active_live:
        _PREVIOUS["pushback_active_seen"] = True
        _PREVIOUS["pushback_completed"] = False
        _PREVIOUS["post_pushback_brake_set"] = False
        _PREVIOUS["post_pushback_briefed"] = False
    elif _PREVIOUS.get("pushback_active_seen") and not _PREVIOUS.get("pushback_completed"):
        _PREVIOUS["pushback_completed"] = True
        _PREVIOUS["pushback_completed_at"] = now
    if _BOARDING_PHASE_ACTIVE and not _boarding_audio_allowed():
        _stop_boarding_music("arrival phase")
    if _BOARDING_PHASE_ACTIVE and _boarding_audio_allowed():
        if not _BOARDING_MUSIC_ACTIVE and _BOARDING_MUSIC_DUE_AT and now >= _BOARDING_MUSIC_DUE_AT:
            _start_boarding_music_now("boarding request delay elapsed")
        if not _BOARDING_MUSIC_ACTIVE and _BOARDING_MUSIC_DUE_AT and now >= _BOARDING_MUSIC_DUE_AT + 15.0:
            _record("MUSIC", "Boarding music was due but not active; retrying once")
            _start_boarding_music_now("boarding retry after due timer")
        if _NEXT_WELCOME_AT and now >= _NEXT_WELCOME_AT:
            _auto_play("BoardingWelcome", force=True, repeatable=True)
            _NEXT_WELCOME_AT = now + _next_boarding_welcome_delay()

    # Boarding ambience ends only after authoritative GSX pushback activity or
    # sustained physical movement. One noisy FSUIPC ground-speed sample, tug
    # presence, an AVAILABLE/REQUESTED service or a label containing “pushback”
    # must never stop/re-arm the music loop.
    confirmed_departure_movement = _confirmed_departure_movement(pushback_active_live, on_ground, gs)
    if confirmed_departure_movement:
        _PREVIOUS["confirmed_departure_movement"] = True
    if _BOARDING_PHASE_ACTIVE and on_ground and confirmed_departure_movement:
        _stop_boarding_music("departure movement")

    if on_ground and "ArmDoors" not in _PLAYED and confirmed_departure_movement and not boarding_explicitly_incomplete:
        if _files_for_event("ArmDoors"):
            _auto_play("ArmDoors")

    powered_for_taxi = bool(engines or systems.get("battery_master") or systems.get("avionics_powered") or systems.get("beacon_light"))
    global _TAXI_OUT_SUSTAINED_SAMPLES
    taxi_motion = bool(on_ground and powered_for_taxi and not pushback_active_live and gs > 5.0 and gs < 35.0)
    _TAXI_OUT_SUSTAINED_SAMPLES = _TAXI_OUT_SUSTAINED_SAMPLES + 1 if taxi_motion else 0
    true_taxi_out = bool(taxi_motion and _TAXI_OUT_SUSTAINED_SAMPLES >= 3)
    taxi_after_pushback = bool(on_ground and not pushback_active_live and gs > 5.0 and gs < 35.0 and (_PREVIOUS.get("pushback_completed") or _PREVIOUS.get("pushback_active_seen")))
    recorder_phase = _active_recorder_phase() or str(t.get("recorder_phase") or t.get("flight_phase") or t.get("phase") or t.get("movement_phase") or "").upper()
    recorder_taxi_out = recorder_phase in {"TAXI_OUT", "TAXI OUT"}
    departure_cabin_trigger = bool(recorder_taxi_out or true_taxi_out or taxi_after_pushback)
    if _PREVIOUS.get("pushback_active_seen") and on_ground and parking_brake and gs < 1.0:
        _PREVIOUS["post_pushback_brake_set"] = True

    # v0.24.14: deterministic departure cabin sequence. The old independent
    # triggers could play Crew Seats immediately and skip Cabin Dim if the UI or
    # GSX state lagged. Start once at true taxi-out, then use fixed offsets.
    if departure_cabin_trigger and not _TAKEOFF_ROLL_SEEN and not _PREVIOUS.get("departure_cabin_sequence_started"):
        if (not _PREVIOUS.get("pushback_active_seen")) or _PREVIOUS.get("pushback_completed") or recorder_taxi_out:
            _PREVIOUS["departure_cabin_sequence_started"] = True
            _PREVIOUS["departure_cabin_sequence_started_at"] = now
            _PREVIOUS["post_pushback_briefed"] = True
            _record("TAXI_OUT_DETECTED_FAST", "reason=gs_sustained_after_pushback")
            _record("ANN_SAFETY_BRIEFING_QUEUED", "reason=taxi_out")
            _auto_play("SafetyBriefing")

    # v0.24.26: cabin takeoff PA is a serial chain, not independent timers.
    # SafetyBriefing can be several minutes long; CabinDim/CrewSeats must wait
    # until the previous PA has completed and must never cut it off.
    if _PREVIOUS.get("departure_cabin_sequence_started") and not _TAKEOFF_ROLL_SEEN:
        if "SafetyBriefing" in _PLAYED and _completed("SafetyBriefing") and "CabinDimTakeoff" not in _PLAYED and "CabinDimTakeoff" not in _QUEUED_EVENTS:
            _record("ANN_CABIN_DIM_QUEUED", "reason=safety_briefing_complete")
            _auto_play("CabinDimTakeoff")
        if "CabinDimTakeoff" in _PLAYED and _completed("CabinDimTakeoff") and "CrewSeatsTakeoff" not in _PLAYED and "CrewSeatsTakeoff" not in _QUEUED_EVENTS:
            _record("ANN_CREW_SEATS_TAKEOFF_QUEUED", "reason=cabin_dim_complete")
            _auto_play("CrewSeatsTakeoff")
    if _TAKEOFF_CONFIRMED and not on_ground and agl > 1000 and vs > 100:
        _stop_boarding_music("airborne")
    # Keep AfterTakeoff at the original 10,000 ft gate. The earlier v0.24.23
    # change to 1,000 ft AGL was too early; missed after-takeoff calls were
    # caused by recorder/phase recovery problems, not by this altitude gate.
    if _TAKEOFF_CONFIRMED and not on_ground and altitude_raw >= 10000.0:
        if "AfterTakeoff" not in _PLAYED:
            _record("ANN_AFTER_TAKEOFF_QUEUED", "reason=ten_thousand_ft")
        _auto_play("AfterTakeoff")

    descent_phase = recorder_phase in {"DESCENT", "APPROACH", "FINAL APPROACH"} or _ANN_VALID_PHASE == "DESCENT"
    descent_confirmed = _TAKEOFF_CONFIRMED and not on_ground and descent_phase and ("AfterTakeoff" in _PLAYED or altitude_raw < 10000.0)
    if descent_confirmed and _altitude_reliable(t):
        crossed_10000 = _crossed_down(previous_altitude, altitude, 10000.0)
        below_10000_late = altitude <= 10000.0 and "DescentSeatbelts" not in _PLAYED
        simvar_on_edge = bool(_SEATBELT_SIMVAR_CHANGED and seatbelt_switch is True and previous_seatbelt is not True)
        if simvar_on_edge or crossed_10000 or below_10000_late:
            reason = "seatbelt_simvar" if simvar_on_edge else "descent_10000ft"
            _record("ANN_DESCENT_SEATBELTS_QUEUED", f"reason={reason}")
            _auto_play("DescentSeatbelts")
        # Optional airline-pack calls are separate literal events. They are
        # sequenced only when the exact files exist and never substitute for
        # DescentSeatbelts or CrewSeatsLanding.
        if altitude <= 8000.0 and "DescentSeatbelts" in _PLAYED and "CallCabinSecureLanding" not in _PLAYED and "CallCabinSecureLanding" not in _QUEUED_EVENTS and _files_for_event("CallCabinSecureLanding"):
            _record("ANN_CABIN_SECURE_LANDING_QUEUED", "reason=descent_below_8000ft")
            _auto_play("CallCabinSecureLanding")
        if altitude <= 6000.0 and "CabinDimLanding" not in _PLAYED and "CabinDimLanding" not in _QUEUED_EVENTS and _files_for_event("CabinDimLanding"):
            secure_ready = not _files_for_event("CallCabinSecureLanding") or "CallCabinSecureLanding" in _PLAYED or "CallCabinSecureLanding" in _QUEUED_EVENTS
            if secure_ready:
                _record("ANN_CABIN_DIM_LANDING_QUEUED", "reason=descent_below_6000ft")
                _auto_play("CabinDimLanding")
        crossed_5000 = _crossed_down(previous_altitude, altitude, 5000.0)
        below_5000_late = altitude <= 5000.0 and "CrewSeatsLanding" not in _PLAYED
        landing_prep_ready = (
            (not _files_for_event("CallCabinSecureLanding") or "CallCabinSecureLanding" in _PLAYED or "CallCabinSecureLanding" in _QUEUED_EVENTS)
            and (not _files_for_event("CabinDimLanding") or "CabinDimLanding" in _PLAYED or "CabinDimLanding" in _QUEUED_EVENTS)
        )
        if (crossed_5000 or below_5000_late) and landing_prep_ready and ("DescentSeatbelts" in _PLAYED or "DescentSeatbelts" in _QUEUED_EVENTS):
            _record("ANN_CREW_SEATS_LANDING_QUEUED", "reason=landing_5000ft")
            _auto_play("CrewSeatsLanding")

    if _TAKEOFF_CONFIRMED and previous_ground is False and on_ground:
        _ARRIVAL_COMPLETE = True
        _stop_boarding_music("landing")
    taxi_in_started = bool(_TAKEOFF_CONFIRMED and on_ground and gs < 40 and "AfterLanding" not in _PLAYED and not pushback_active_live)
    if taxi_in_started:
        _ARRIVAL_COMPLETE = True
        _record("ANN_AFTER_LANDING_QUEUED", "reason=taxi_in_phase")
        _auto_play("AfterLanding")
        _stop_boarding_music("taxi in")
    if _TAKEOFF_CONFIRMED and _parked_at_gate(on_ground, gs, parking_brake, systems) and "AfterLanding" in _PLAYED and _PREVIOUS.get("on_ground") is True:
        _ARRIVAL_COMPLETE = True
        _auto_play("DisarmDoors")
        _auto_play("DisembarkStarted")

    if seatbelt_switch is True and _PREVIOUS.get("seatbelt_switch") is not True and _TAKEOFF_CONFIRMED and not descent_confirmed:
        # Use the generic sign-on call only outside the planned descent flow.
        # DescentSeatbelts owns the normal 10,000 ft arrival announcement.
        _auto_play("FastenSeatbelt")
    _PREVIOUS.update({"on_ground": on_ground, "engines": engines, "gs": gs, "agl": agl, "altitude": altitude if 'altitude' in locals() else 0.0, "seatbelt_switch": seatbelt_switch, "parking_brake": parking_brake, "takeoff_roll_seen": _TAKEOFF_ROLL_SEEN, "pushback_active_live": pushback_active_live})


def _trigger_from_gsx() -> None:
    """Trigger ground-service cabin audio independently of flight telemetry."""
    try:
        from .gsx_remote import status as gsx_status
        gsx = gsx_status(force=False)
    except Exception:
        return
    if not gsx.get("ok") or not gsx.get("connected"):
        return
    services = gsx.get("services") or {}
    values = {key: (services.get(key) or {}).get("raw") for key in ("boarding", "deboarding", "refuel", "catering", "departure", "pushback", "jetway", "stairs")}
    previous = {key: _PREVIOUS.get(f"gsx_{key}") for key in values}
    global _AUDIO_HARD_STOPPED, _ARRIVAL_COMPLETE
    if values.get("boarding") not in {4, 5}:
        # Allow a future, newly-entered boarding phase after the current one has ended.
        _AUDIO_HARD_STOPPED = False

    boarding_info = _gsx_boarding_status(gsx)
    pax_now = int(boarding_info.get("current") or 0)
    pax_target = int(boarding_info.get("total") or 0)
    pax_prev = int(_PREVIOUS.get("gsx_pax_boarding_total") or 0)
    boarding_progress_started = bool(boarding_info.get("active") and pax_now > 0)
    if boarding_progress_started and _AUDIO_HARD_STOPPED:
        # A previous STOP must not suppress a later real GSX boarding phase forever.
        _AUDIO_HARD_STOPPED = False
        _record("AUDIO", "Boarding audio re-armed by real GSX passenger progress")
    first_boarding_progress = bool(boarding_progress_started and pax_prev <= 0)
    if boarding_progress_started and not _BOARDING_PHASE_ACTIVE and _boarding_audio_allowed():
        _start_boarding_music("GSX passenger boarding progress")
    elif boarding_progress_started and _BOARDING_PHASE_ACTIVE and not _BOARDING_MUSIC_ACTIVE and _BOARDING_MUSIC_DUE_AT:
        _record("BOARDING", f"GSX boarding progress {pax_now}/{pax_target or '---'}; music timer armed")
    if first_boarding_progress and not _PREVIOUS.get("boarding_welcome_attempted"):
        # BoardingWelcome variant selection already prefers [Refueling] while
        # refuelling is active. If that variant is absent it falls back to the
        # normal aircraft/daypart/generic BoardingWelcome and the music timer
        # continues regardless, so a missing variation can never block boarding.
        _PREVIOUS["boarding_welcome_attempted"] = True
        welcome = _auto_play("BoardingWelcome", force=True)
        if not welcome.get("ok"):
            _record("BOARDING", "No compatible welcome recording; boarding music continues")
    # Do not start boarding music from jetway/stairs or service-request states.
    # The timer starts only after GSX confirms passenger boarding is in progress.
    boarding_complete_now = bool(boarding_info.get("complete"))
    boarding_complete_before = bool(_PREVIOUS.get("gsx_boarding_complete"))
    if boarding_complete_now and not boarding_complete_before:
        _stop_boarding_music("GSX passenger boarding complete")
        _auto_play("BoardingComplete")
    if _TAKEOFF_CONFIRMED and _ARRIVAL_COMPLETE and values["deboarding"] in {4, 5} and previous["deboarding"] not in {4, 5}:
        _ARRIVAL_COMPLETE = True
        _stop_boarding_music("GSX deboarding")
        _auto_play("DisembarkStarted")
    # Ground-service changes are log/status only. Announcer is cabin/passenger PA,
    # not a GSX service voiceover system; missing refuel/catering files must never
    # fault the Announcer page.
    if _SESSION_READY and values["refuel"] in {4, 5} and previous["refuel"] not in {4, 5}:
        _record("GROUND", "Refuelling service active (no cabin audio event)")
    if _SESSION_READY and values["catering"] in {4, 5} and previous["catering"] not in {4, 5}:
        _record("GROUND", "Catering service active (no cabin audio event)")
    pushback_active = bool(
        not boarding_info.get("explicit_incomplete")
        and any(_service_is_physical_departure_active(services.get(key)) for key in ("pushback", "departure"))
    )
    previous_pushback = bool(_PREVIOUS.get("gsx_physical_pushback_active"))
    if pushback_active and not previous_pushback:
        _stop_boarding_music("pushback start")
        _PREVIOUS["pushback_active_seen"] = True
        _PREVIOUS["post_pushback_brake_set"] = False
        _PREVIOUS["post_pushback_briefed"] = False
    if previous_pushback and not pushback_active:
        _PREVIOUS["pushback_completed"] = True

    _PREVIOUS.update({f"gsx_{key}": value for key, value in values.items()})
    _PREVIOUS["gsx_pax_boarding_total"] = pax_now
    _PREVIOUS["gsx_boarding_complete"] = boarding_complete_now
    _PREVIOUS["gsx_physical_pushback_active"] = pushback_active


def _audio_roots(root: Path | None = None) -> list[Path]:
    roots = []
    if root:
        roots.append(root)
    roots.extend(_built_in_announcement_roots())
    result: list[Path] = []
    seen: set[str] = set()
    for folder in roots:
        try:
            key = str(folder.resolve()).lower()
        except Exception:
            key = str(folder).lower()
        if key not in seen and folder.is_dir():
            seen.add(key)
            result.append(folder)
    return result


def _available_file_count(root: Path | None) -> int:
    roots = _audio_roots(root)
    if not roots:
        return 0
    now = time.monotonic()
    key = "|".join(str(x.resolve()) for x in roots)
    if _SCAN_CACHE.get("root") == key and now - float(_SCAN_CACHE.get("time") or 0) < 30:
        return int(_SCAN_CACHE.get("count") or 0)
    count = 0
    for folder in roots:
        count += sum(1 for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in _AUDIO_EXTENSIONS)
    _SCAN_CACHE.update({"root": key, "time": now, "count": count})
    return count


def _loop() -> None:
    _STATE["running"] = True
    while not _STOP.wait(1.0):
        try:
            integrations = load_settings().get("integrations", {})
            enabled = bool(integrations.get("announcements_enabled", False))
            _STATE["enabled"] = enabled
            _STATE["volume"] = max(0, min(int(integrations.get("announcements_volume", 80) or 80), 100))
            _STATE["airline_override"] = _clean_airline(integrations.get("announcements_airline_override"))
            _STATE["callsign_override"] = _clean_callsign(integrations.get("announcements_callsign_override"))
            _STATE["hotkeys_enabled"] = bool(integrations.get("announcements_hotkeys_enabled", True))
            _STATE["pause_hotkey"] = str(integrations.get("announcements_pause_hotkey", "CTRL+ALT+P"))
            _STATE["mute_hotkey"] = str(integrations.get("announcements_mute_hotkey", "CTRL+ALT+M"))
            root = _root()
            airline, callsign, source = _announcement_identity()
            _STATE["airline"] = airline
            _STATE["callsign"] = callsign
            _STATE["airline_source"] = source
            _STATE["available_files"] = _available_file_count(root)
            _STATE["audio_configured"] = bool(_audio_roots(root))
            audio_ready = bool(_audio_roots(root))
            if audio_ready:
                # Manual announcements are allowed even when automatic cabin announcements are disabled.
                _dequeue_audio_event()
            if enabled and audio_ready:
                _service_boarding_timers()
                _trigger_from_gsx()
                _trigger_from_telemetry(read_telemetry(force=False))
            if audio_ready:
                _dequeue_audio_event()
            # #72: re-apply the camera-aware mixer volume whenever the camera
            # category changes, even mid-playback (Universal Announcer parity).
            # Previously the volume was only applied at play start / settings
            # save, so switching cockpit -> external did nothing while an
            # announcement or boarding music was playing.
            try:
                category = _camera_category()
                if category != _LAST_CAMERA_CATEGORY:
                    _LAST_CAMERA_CATEGORY = category
                    applied = apply_runtime_settings()
                    # #80: one line per actual category transition so the log
                    # shows the camera -> volume mapping working (or not).
                    raw_setting = int(load_settings().get("integrations", {}).get("announcements_volume", 80) or 80)
                    applied_vol = applied.get("volume") if isinstance(applied, dict) else _STATE.get("volume")
                    print(f"CAMERA VOLUME: category={category} applied={applied_vol}% raw={raw_setting}%")
            except Exception:
                pass
            try:
                import pygame  # type: ignore
                if pygame.mixer.get_init() and not pygame.mixer.music.get_busy() and not _pa_busy() and not _STATE.get("paused"):
                    _STATE["playing"] = False
            except Exception:
                pass
        except Exception as exc:
            _STATE["last_error"] = f"{type(exc).__name__}: {exc}"
    _STATE["running"] = False


def start_engine() -> None:
    global _THREAD
    with _LOCK:
        if _THREAD and _THREAD.is_alive():
            return
        _STOP.clear()
        _THREAD = threading.Thread(target=_loop, name="OpsRoom-Announcements", daemon=True)
        _THREAD.start()


def boarding_phase_active() -> bool:
    with _LOCK:
        return bool(_BOARDING_PHASE_ACTIVE)


def audio_healthcheck() -> dict[str, Any]:
    root = _root()
    roots = _audio_roots(root)
    info = {
        "pygame_available": False,
        "mixer_initialized": False,
        "worker_alive": bool(_THREAD and _THREAD.is_alive()),
        "audio_roots": [str(x) for x in roots],
        "available_files": _available_file_count(root),
        "last_error": _STATE.get("last_error"),
    }
    try:
        import pygame  # type: ignore
        info["pygame_available"] = True
        info["mixer_initialized"] = bool(pygame.mixer.get_init())
        if not info["mixer_initialized"] and roots:
            try:
                _ensure_mixer()
                info["mixer_initialized"] = True
            except Exception as exc:
                info["last_error"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        info["last_error"] = f"{type(exc).__name__}: {exc}"
    return info


def status() -> dict[str, Any]:
    """Return a pure cached Announcer snapshot.

    This route is intentionally read-only and non-blocking. It must never start
    the engine, load settings, scan folders, inspect SimBrief, import pygame, or
    wait for the audio worker. If the worker/audio path is busy, the browser still
    gets the last known state immediately.
    """
    now = time.monotonic()
    state = dict(_STATE)
    events = list(state.get("events") or [])[-80:]
    state["events"] = events
    available_files = int(state.get("available_files") or 0)
    airline = str(state.get("airline") or "DEFAULT")
    audio_health = {
        "worker_alive": bool(_THREAD and _THREAD.is_alive()),
        "pygame_available": None,
        "mixer_initialized": None,
        "available_files": available_files,
        "last_error": state.get("last_error"),
        "boarding_phase_active": bool(_BOARDING_PHASE_ACTIVE),
        "boarding_music_active": bool(_BOARDING_MUSIC_ACTIVE),
        "boarding_music_due_in_seconds": int(max(0, _BOARDING_MUSIC_DUE_AT - now)) if _BOARDING_MUSIC_DUE_AT else None,
        "audio_hard_stopped": bool(_AUDIO_HARD_STOPPED),
        "queued_events": _AUDIO_QUEUE.qsize(),
        "audio_circuit_breaker_seconds": int(max(0, _AUDIO_CIRCUIT_OPEN_UNTIL - now)),
        "camera_volume_enabled": bool(load_settings().get("integrations", {}).get("camera_volume_enabled", False)),
        "camera_distance_m": round(_CAMERA_DISTANCE, 1),
        # #80: expose the ACTUAL applied mixer volume (camera-aware) and the
        # current camera category so the camera-volume path is verifiable via
        # the API — previously only the raw setting was visible, so a camera
        # switch that failed to re-apply was indistinguishable from a working
        # one. Both are cheap cache reads; never a blocking probe.
        "camera_category": _camera_category(),
        "applied_volume": int(round(_mixer_volume()[0] * 100.0)),
        "raw_volume": int(state.get("volume") or 80),
    }
    return {
        "ok": True,
        **state,
        "revision": int(state.get("revision") or 0),
        "updated_utc": state.get("updated_utc"),
        "enabled": bool(state.get("enabled")),
        "playing": bool(state.get("playing")),
        "paused": bool(state.get("paused")),
        "muted": bool(state.get("muted")),
        "volume": int(state.get("volume") or 80),
        "airline": airline,
        "callsign": str(state.get("callsign") or ""),
        "airline_source": str(state.get("airline_source") or "DEFAULT"),
        "available_files": available_files,
        "audio_configured": bool(state.get("audio_configured") or available_files > 0),
        "airline_pack_available": bool(available_files > 0 and airline not in {"", "DEFAULT"}),
        "using_default_announcements": bool(airline in {"", "DEFAULT"} or available_files > 0),
        "announcement_notice": "Announcement status is a cached snapshot; audio playback is handled only by the background worker.",
        "audio_health": audio_health,
        "played": sorted(_PLAYED),
        "boarding_phase_active": bool(_BOARDING_PHASE_ACTIVE),
        "boarding_music_active": bool(_BOARDING_MUSIC_ACTIVE),
        "built_in_default_available": None,
        "airline_override": str(state.get("airline_override") or ""),
        "callsign_override": str(state.get("callsign_override") or ""),
        "hotkeys_enabled": bool(state.get("hotkeys_enabled", True)),
        "pause_hotkey": str(state.get("pause_hotkey") or "CTRL+ALT+P"),
        "mute_hotkey": str(state.get("mute_hotkey") or "CTRL+ALT+M"),
        "compatible_format": "Airline folders with OGG, WAV or MP3 audio; built-in Announcements/Default can be used as fallback",
    }
