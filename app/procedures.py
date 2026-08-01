from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .flight_watch import build_flight_watch
from .procedure_profiles import ADDON_PROFILES
from .settings_store import load_settings
from .simbrief_client import cached_plan


def _item(key: str, text: str, note: str = "") -> dict[str, str]:
    return {"key": key, "text": text, "note": note}


COMMON_PHASES = [
    ("preflight", "PREFLIGHT"),
    ("before_start", "BEFORE START"),
    ("after_start", "AFTER START"),
    ("taxi", "TAXI"),
    ("before_takeoff", "BEFORE TAKEOFF"),
    ("after_takeoff", "AFTER TAKEOFF"),
    ("climb_cruise", "CLIMB / CRUISE"),
    ("descent", "DESCENT"),
    ("approach", "APPROACH"),
    ("landing", "LANDING"),
    ("after_landing", "AFTER LANDING"),
    ("shutdown", "SHUTDOWN"),
]


GENERIC_JET = {
    "key": "generic_jet",
    "label": "GENERIC JET",
    "source": "OPS ROOM generic normal-procedure framework",
    "phases": {
        "preflight": [
            _item("documents", "Aircraft documents and dispatch reviewed"),
            _item("power", "Electrical power established"),
            _item("fuel", "Fuel and payload checked against flight plan"),
            _item("navigation", "Navigation and route entered"),
            _item("performance", "Takeoff performance and departure data set"),
            _item("briefing", "Departure and emergency briefing complete"),
        ],
        "before_start": [
            _item("doors", "Doors and service panels closed"),
            _item("beacon", "Beacon on"),
            _item("parking_brake", "Parking brake or chocks confirmed"),
            _item("clearance", "Pushback and start clearance obtained"),
            _item("transponder", "Transponder set for departure"),
        ],
        "after_start": [
            _item("generators", "Generators and pneumatic systems normal"),
            _item("anti_ice", "Anti-ice set as required"),
            _item("controls", "Flight controls checked"),
            _item("flaps", "Takeoff flaps and trim set"),
            _item("status", "Aircraft status reviewed"),
        ],
        "taxi": [
            _item("brakes", "Brakes checked"),
            _item("instruments", "Flight instruments checked"),
            _item("takeoff_config", "Takeoff configuration checked"),
            _item("cabin", "Cabin secure indication received"),
        ],
        "before_takeoff": [
            _item("runway", "Runway and departure verified"),
            _item("lights", "Exterior lights set"),
            _item("transponder_airborne", "Transponder and traffic system set"),
            _item("configuration", "Takeoff configuration normal"),
        ],
        "after_takeoff": [
            _item("gear", "Landing gear up"),
            _item("flaps_up", "Flaps retracted on schedule"),
            _item("climb_power", "Climb power and automation checked"),
            _item("lights_climb", "Exterior lights set for climb"),
        ],
        "climb_cruise": [
            _item("altimeters", "Altimeters set for cruise level"),
            _item("fuel_progress", "Fuel and route progress checked"),
            _item("systems_cruise", "Systems and pressurisation checked"),
            _item("arrival_review", "Arrival and weather monitored"),
        ],
        "descent": [
            _item("arrival", "Arrival and approach loaded"),
            _item("weather", "Destination weather and ATIS reviewed"),
            _item("landing_data", "Landing performance and minima set"),
            _item("approach_brief", "Approach and missed approach briefed"),
            _item("seatbelts", "Seat-belt signs set as required"),
        ],
        "approach": [
            _item("altimeters_approach", "Altimeters cross-checked"),
            _item("approach_mode", "Approach guidance and navigation source checked"),
            _item("landing_config", "Landing configuration selected"),
            _item("go_around", "Go-around altitude and procedure confirmed"),
            _item("stable", "Stable approach criteria monitored"),
        ],
        "landing": [
            _item("gear_down", "Landing gear down and indicated"),
            _item("flaps_landing", "Landing flap selected"),
            _item("spoilers", "Speedbrake or spoilers armed"),
            _item("autobrake", "Autobrake or braking plan set"),
            _item("clearance_landing", "Landing clearance confirmed"),
        ],
        "after_landing": [
            _item("spoilers_disarm", "Speedbrake or spoilers disarmed"),
            _item("flaps_retract", "Flaps retracted"),
            _item("transponder_ground", "Transponder set for ground operation"),
            _item("lights_taxi", "Exterior lights set for taxi"),
            _item("apu", "APU or ground power prepared as required"),
        ],
        "shutdown": [
            _item("park", "Parking brake or chocks confirmed"),
            _item("engines_off", "Engines shut down"),
            _item("beacon_off", "Beacon off"),
            _item("fuel_pumps", "Fuel pumps off"),
            _item("seatbelts_off", "Seat-belt signs off"),
            _item("secure", "Aircraft secured and post-flight status reviewed"),
        ],
    },
}


def _profile(base: dict[str, Any], key: str, label: str, substitutions: dict[str, str] | None = None) -> dict[str, Any]:
    substitutions = substitutions or {}
    phases: dict[str, list[dict[str, str]]] = {}
    for phase_key, rows in base["phases"].items():
        phases[phase_key] = []
        for row in rows:
            copied = dict(row)
            copied["text"] = substitutions.get(copied["key"], copied["text"])
            phases[phase_key].append(copied)
    return {"key": key, "label": label, "source": "OPS ROOM generic aircraft-family framework", "phases": phases}


AIRBUS = _profile(
    GENERIC_JET,
    "airbus",
    "AIRBUS FAMILY",
    {
        "navigation": "MCDU route, INIT and flight plan pages checked",
        "performance": "PERF takeoff data and V-speeds entered",
        "status": "ECAM status and memo reviewed",
        "takeoff_config": "Takeoff config test normal",
        "configuration": "Takeoff memo has no unresolved items",
        "approach_mode": "FMGS approach guidance and LS display checked as applicable",
        "spoilers": "Ground spoilers armed",
    },
)

BOEING = _profile(
    GENERIC_JET,
    "boeing",
    "BOEING FAMILY",
    {
        "navigation": "FMC route, departure and performance pages checked",
        "performance": "Takeoff reference speeds and thrust data entered",
        "status": "EICAS messages reviewed",
        "takeoff_config": "Takeoff configuration warning check complete",
        "approach_mode": "Approach mode and navigation source checked",
        "spoilers": "Speedbrake armed",
    },
)

TURBOPROP = _profile(
    GENERIC_JET,
    "turboprop",
    "TURBOPROP / REGIONAL",
    {
        "climb_power": "Climb power and propeller settings checked",
        "generators": "Generators, bleeds and propeller systems normal",
        "anti_ice": "Engine, propeller and airframe anti-ice set as required",
        "landing_config": "Landing configuration and condition levers set",
    },
)

GA = _profile(
    GENERIC_JET,
    "general_aviation",
    "GENERAL AVIATION",
    {
        "navigation": "Navigation equipment and route checked",
        "performance": "Takeoff distance, weight and balance checked",
        "generators": "Engine instruments and electrical system normal",
        "transponder_airborne": "Transponder and traffic equipment set",
        "climb_power": "Climb power and mixture or propeller settings checked",
        "landing_config": "Landing configuration and mixture or propeller controls set",
    },
)

PROFILES = {p["key"]: p for p in (GENERIC_JET, AIRBUS, BOEING, TURBOPROP, GA)}
PROFILES.update(ADDON_PROFILES)


def _detect_profile(aircraft_text: str) -> str:
    value = aircraft_text.upper()
    # Addon-specific detection is evaluated before aircraft-family fallback.
    if "FENIX" in value and any(token in value for token in ("A320", "A321", "A20N", "A21N")):
        return "fenix_a320"
    if "PMDG" in value and any(token in value for token in ("737", "B737", "B738", "B739")):
        return "pmdg_737"
    if "PMDG" in value and any(token in value for token in ("777", "B777", "77W", "77F", "77L")):
        return "pmdg_777"
    if any(token in value for token in ("A380X", "FBW A380", "FLYBYWIRE A380")):
        return "fbw_a380x"
    if any(token in value for token in ("INIBUILDS A350", "INI A350", "A350-900", "A350-1000", "A359", "A35K")):
        return "inibuilds_a350"
    if any(token in value for token in ("A340-600", "A340 600", "A346")):
        return "a340_600"
    if any(token in value for token in ("BOEING 787", "B787", "787-8", "787-9", "787-10", "B78X")):
        return "boeing_787"
    if any(token in value for token in ("AIRBUS", "A318", "A319", "A320", "A321", "A330", "A340", "A350", "A380", "FENIX", "A32NX")):
        return "airbus"
    if any(token in value for token in ("BOEING", "B737", "B738", "B739", "B747", "B757", "B767", "B777", "B787", "PMDG", "77F", "77W")):
        return "boeing"
    if any(token in value for token in ("ATR", "Q400", "DASH", "SAAB", "TURBOPROP", "KING AIR", "TBM", "PC-12")):
        return "turboprop"
    if any(token in value for token in ("CESSNA", "PIPER", "CIRRUS", "DIAMOND", "BONANZA", "VISION JET", "SR22", "C172", "DA40", "DA62")):
        return "general_aviation"
    return "generic_jet"

def _phase_key(flight_phase: str) -> str:
    phase = (flight_phase or "").upper()
    if phase == "PARKED":
        return "preflight"
    if phase in {"TAXI", "TAKEOFF ROLL"}:
        return "taxi" if phase == "TAXI" else "before_takeoff"
    if phase in {"INITIAL CLIMB", "CLIMB"}:
        return "after_takeoff"
    if phase in {"CRUISE", "ENROUTE"}:
        return "climb_cruise"
    if phase == "DESCENT":
        return "descent"
    if phase == "APPROACH":
        return "approach"
    return "preflight"


def build_procedures(profile_override: str = "") -> dict[str, Any]:
    watch = build_flight_watch(force=False)
    telemetry = watch.get("telemetry") if isinstance(watch.get("telemetry"), dict) else {}
    aircraft = telemetry.get("aircraft") if isinstance(telemetry.get("aircraft"), dict) else {}
    settings = load_settings()
    user_ref = str(settings.get("identity", {}).get("simbrief_user_id") or "")
    plan = cached_plan(user_ref) if user_ref else None
    plan_aircraft = (plan or {}).get("aircraft") if isinstance((plan or {}).get("aircraft"), dict) else {}
    aircraft_text = " ".join(
        str(value or "")
        for value in (
            aircraft.get("title"), aircraft.get("model"), aircraft.get("type"),
            plan_aircraft.get("icao"), plan_aircraft.get("name"), plan_aircraft.get("registration"),
        )
    ).strip()
    detected = _detect_profile(aircraft_text)
    selected = profile_override if profile_override in PROFILES else detected
    profile = PROFILES[selected]
    flight_phase = str(watch.get("phase") or "STANDBY")
    phases = []
    for key, label in COMMON_PHASES:
        phases.append({"key": key, "label": label, "items": profile["phases"].get(key, [])})
    return {
        "ok": True,
        "profile": {"key": profile["key"], "label": profile["label"], "source": profile.get("source", ""), "detected": detected},
        "available_profiles": [{"key": value["key"], "label": value["label"]} for value in PROFILES.values()],
        "aircraft": aircraft_text or "AIRCRAFT NOT DETECTED",
        "flight_phase": flight_phase,
        "recommended_phase": _phase_key(flight_phase),
        "phases": phases,
        "notice": "Simulation aid only. Source material has been condensed for simulator workflow; use the approved aircraft documentation when required.",
        "updated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
