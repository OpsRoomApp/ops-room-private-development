from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .flight_watch import build_flight_watch
from .settings_store import load_settings
from .simbrief_client import cached_plan


def _row(key: str, text: str, note: str = "") -> dict[str, str]:
    return {"key": key, "text": text, "note": note}


def _section(key: str, title: str, items: list[str | tuple[str, str]], kind: str = "qrh") -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    for index, value in enumerate(items, start=1):
        if isinstance(value, tuple):
            text, note = value
        else:
            text, note = value, ""
        rows.append(_row(f"{key}_{index:02d}", text, note))
    return {"key": key, "title": title, "kind": kind, "items": rows}


def _nn(
    key: str,
    title: str,
    category: str,
    severity: str,
    keywords: list[str],
    summary: str,
    memory: list[str | tuple[str, str]],
    sections: list[dict[str, Any]],
    families: tuple[str, ...] = ("airbus", "boeing", "generic"),
) -> dict[str, Any]:
    memory_rows: list[dict[str, str]] = []
    for index, value in enumerate(memory, start=1):
        if isinstance(value, tuple):
            text, note = value
        else:
            text, note = value, ""
        memory_rows.append(_row(f"{key}_memory_{index:02d}", text, note))
    return {
        "key": key,
        "title": title,
        "category": category,
        "severity": severity,
        "keywords": keywords,
        "summary": summary,
        "families": list(families),
        "memory_items": memory_rows,
        "sections": sections,
    }


AIRBUS_COMMON = {
    "label": "AIRBUS FAMILY QRH / ECAM AID",
    "source": "OPS ROOM generalized Airbus non-normal framework for flight simulation. ECAM/QRH remains the authority.",
    "philosophy": [
        "Fly the aircraft, confirm the failure, then work ECAM/QRH deliberately.",
        "Memory actions are shown only for simulator workflow; verify with the aircraft documentation.",
        "After ECAM actions, review STATUS and plan performance, landing distance and approach configuration changes.",
    ],
}

BOEING_COMMON = {
    "label": "BOEING FAMILY QRH AID",
    "source": "OPS ROOM generalized Boeing non-normal framework for flight simulation. The approved QRH remains the authority.",
    "philosophy": [
        "Maintain aircraft control, identify the condition, complete memory items where required, then run the QRH checklist.",
        "Use normal checklists when instructed after the non-normal is complete.",
        "Plan landing distance, approach speed, autobrake/manual-braking strategy and dispatch implications before continuing.",
    ],
}

GENERIC_COMMON = {
    "label": "GENERIC JET NON-NORMAL AID",
    "source": "OPS ROOM generalized non-normal framework for flight simulation. Use the aircraft's own checklist where available.",
    "philosophy": [
        "Aviate, navigate, communicate.",
        "Stabilise the aircraft before troubleshooting unless immediate action is required.",
        "Treat this as a simulator aid, not real-world operational documentation.",
    ],
}


def _shared_conditions(family: str) -> dict[str, dict[str, Any]]:
    airbus = family == "airbus"
    boeing = family == "boeing"
    status_name = "ECAM STATUS" if airbus else ("QRH / EICAS status" if boeing else "status page / checklist")
    automation = "managed/selected guidance" if airbus else ("MCP/FMC guidance" if boeing else "automation")
    fire_button = "fire pushbutton / agent logic" if airbus else ("fire switch / agent logic" if boeing else "fire handle / extinguisher logic")
    thrust_lever = "thrust lever" if airbus else ("thrust lever" if boeing else "power lever")
    config_word = "ECAM" if airbus else ("QRH" if boeing else "aircraft checklist")
    return {
        "rejected_takeoff": _nn(
            "rejected_takeoff",
            "Rejected Takeoff",
            "Takeoff",
            "critical",
            ["rto", "reject", "rejected", "abort", "takeoff", "brakes"],
            "High-speed or low-speed takeoff rejection workflow.",
            [
                "Maintain directional control on runway centreline",
                "Bring thrust/power to idle and use maximum safe braking",
                "Deploy speedbrake/reverse as applicable",
                "Advise ATC when the aircraft is under control",
            ],
            [
                _section("rto_control", "Control and stop", [
                    "Maintain runway centreline and stop the aircraft on the runway or suitable paved surface",
                    "Set parking brake when stopped and assess brake energy / fire risk",
                    "Keep cabin crew and passengers seated until the situation is understood",
                    "If evacuation is possible, keep engines running or shut down only as directed by the evacuation decision path",
                ], "memory"),
                _section("rto_assess", "Assess before taxi or evacuation", [
                    "Identify the rejected-takeoff reason and any aircraft warning",
                    f"Run the applicable {config_word} checklist",
                    "Check brake temperature, tyre condition and runway remaining if the addon provides the data",
                    "Coordinate with ATC before taxiing clear or requesting emergency services",
                    "If continuing the flight, reset takeoff configuration and performance data before another takeoff attempt",
                ]),
            ],
        ),
        "engine_fire": _nn(
            "engine_fire",
            "Engine Fire / Severe Damage",
            "Fire / Engine",
            "critical",
            ["engine fire", "fire", "severe damage", "engine damage", "hot start"],
            "Engine fire or severe-damage handling in flight or on the ground.",
            [
                "Maintain aircraft control and safe flight path",
                (f"Affected {thrust_lever} idle", "Confirm affected side before action"),
                ("Affected engine fuel/control switch or master off", "Do not act without cross-check in multi-crew style operation"),
                (f"Use {fire_button} when directed", "Discharge agent only when appropriate for the simulated aircraft"),
            ],
            [
                _section("eng_fire_stabilise", "Stabilise", [
                    "Fly the aircraft and set a safe altitude, heading and speed",
                    "Confirm affected engine with instruments and warning indications",
                    "Declare PAN/MAYDAY as appropriate and request vectors or return",
                    f"Follow {config_word} actions without skipping confirmation steps",
                ], "memory"),
                _section("eng_fire_continue", "Continue or land", [
                    "Plan single-engine performance, drift-down or return-to-land as required",
                    "Review fuel balance and electrical/hydraulic consequences",
                    f"Review {status_name} and landing-distance/performance penalties",
                    "Brief single-engine approach, go-around expectations and runway choice",
                    "Record the abnormal event in the OPS ROOM debrief notes after the flight",
                ]),
            ],
        ),
        "engine_failure": _nn(
            "engine_failure",
            "Engine Failure / Shutdown",
            "Engine",
            "warning",
            ["engine fail", "engine failure", "shutdown", "flameout", "single engine", "one engine"],
            "Loss of thrust, flameout or intentional engine shutdown handling.",
            [
                "Maintain control and target safe speed",
                "Confirm affected engine",
                "Set thrust on operating engine(s) as required",
                "Follow aircraft checklist before securing systems",
            ],
            [
                _section("eng_fail_initial", "Initial actions", [
                    "Control yaw and roll with rudder/trim as required",
                    "Check flight path, speed and terrain clearance",
                    "Confirm failure using thrust, N1/N2, EGT, fuel flow and warning indications",
                    f"Run the applicable {config_word} checklist",
                ], "memory"),
                _section("eng_fail_plan", "Planning", [
                    "Decide: continue, return, divert or hold for troubleshooting",
                    "Review climb, cruise, drift-down and terrain constraints",
                    "Check fuel balance and crossfeed requirements if applicable",
                    "Set up single-engine approach data and missed approach strategy",
                    "Notify ATC and prepare cabin if landing with degraded capability",
                ]),
            ],
        ),
        "emergency_descent": _nn(
            "emergency_descent",
            "Emergency Descent / Pressurisation",
            "Pressurisation",
            "critical",
            ["emergency descent", "pressurisation", "pressurization", "cabin altitude", "depressurization", "oxygen"],
            "Cabin altitude, decompression or pressurisation failure response.",
            [
                "Crew oxygen masks on / establish communication",
                "Start emergency descent when required and terrain permits",
                "Set safe target altitude considering terrain and ATC",
                "Passenger signs on and advise ATC/cabin when able",
            ],
            [
                _section("ed_memory", "Immediate descent management", [
                    "Use speedbrake as appropriate and avoid exceeding structural limits",
                    "Set transponder/emergency code only if desired for the simulation/network context",
                    "Monitor cabin altitude, differential pressure and aircraft speed",
                    "Level at the minimum safe altitude or ATC-cleared altitude",
                ], "memory"),
                _section("ed_recovery", "After level-off", [
                    f"Complete {config_word} actions and review {status_name}",
                    "Plan diversion if oxygen, pressurisation or passenger condition requires it",
                    "Recalculate fuel and arrival performance after the high-speed descent",
                    "Brief approach and abnormal landing considerations",
                ]),
            ],
        ),
        "smoke_fumes": _nn(
            "smoke_fumes",
            "Smoke / Fumes / Fire Unknown Source",
            "Fire / Smoke",
            "critical",
            ["smoke", "fumes", "burning", "electrical smell", "fire unknown"],
            "Smoke, fumes or suspected fire without immediate source confirmation.",
            [
                "Oxygen masks on if smoke/fumes affect the cockpit",
                "Establish crew communication",
                "Declare emergency and consider nearest suitable landing",
                "Avoid unnecessary troubleshooting delays",
            ],
            [
                _section("smoke_source", "Identify and isolate", [
                    "Maintain aircraft control and safe flight path",
                    "Identify smoke source if obvious: air conditioning, electrical, cargo, cabin, avionics or galley",
                    "Follow aircraft smoke/fumes checklist and avoid random switch selections",
                    "Coordinate with cabin crew for source, severity and passenger condition",
                ], "memory"),
                _section("smoke_land", "Landing preparation", [
                    "Plan immediate diversion or return unless the issue is positively resolved",
                    "Review visibility, oxygen, electrical and pressurisation impacts",
                    "Brief abnormal approach, evacuation criteria and emergency services request",
                    "Keep the checklist open until parked and the aircraft is safe",
                ]),
            ],
        ),
        "unreliable_airspeed": _nn(
            "unreliable_airspeed",
            "Unreliable Airspeed / ADR / Pitot Static",
            "Flight Instruments",
            "critical",
            ["unreliable", "airspeed", "adr", "pitot", "static", "ias disagree", "speed disagree"],
            "Unreliable speed indication or air-data disagreement.",
            [
                "Maintain known safe pitch and thrust/power",
                "Disconnect automation if it is following unreliable data",
                "Avoid abrupt attitude changes",
                "Cross-check standby instruments, GPS groundspeed and other ADR/source data",
            ],
            [
                _section("uas_control", "Stabilise by attitude and thrust", [
                    "Use memory pitch/thrust tables from the aircraft documentation when available",
                    "Do not chase disagreeing speed tapes",
                    "Check altitude, vertical speed and flight path trend",
                    "Select reliable air-data source only when identified by the checklist",
                ], "memory"),
                _section("uas_approach", "Plan continuation", [
                    "Review approach method, configuration and landing distance with unreliable speed",
                    "Use a longer runway and stable weather where possible",
                    "Avoid low-energy approaches and keep the procedure conservative",
                    f"Use {status_name} / QRH notes before committing to landing",
                ]),
            ],
        ),
        "hydraulic_abnormal": _nn(
            "hydraulic_abnormal",
            "Hydraulic System Abnormal",
            "Hydraulics",
            "warning",
            ["hydraulic", "hyd", "green", "blue", "yellow", "pressure", "quantity"],
            "Hydraulic pressure loss, quantity loss or system degradation.",
            [],
            [
                _section("hyd_identify", "Identify affected functions", [
                    "Confirm affected hydraulic system(s) and whether pressure or quantity is lost",
                    f"Run {config_word} actions and avoid resetting pumps unless directed",
                    "Check consequences for flight controls, gear, flaps/slats, brakes, steering and reversers",
                    "Avoid unnecessary configuration changes until landing plan is understood",
                ]),
                _section("hyd_land", "Landing planning", [
                    "Select runway with enough length and emergency services if needed",
                    "Review alternate gear, flap/slat, brake and steering procedures",
                    "Brief higher approach speeds or abnormal flap configuration if required",
                    "After landing, stop on runway if steering or braking is degraded",
                ]),
            ],
        ),
        "electrical_abnormal": _nn(
            "electrical_abnormal",
            "Electrical System Abnormal",
            "Electrical",
            "warning",
            ["electrical", "generator", "battery", "bus", "apu gen", "elec", "power"],
            "Generator, bus, battery or major electrical-source abnormal.",
            [],
            [
                _section("elec_stabilise", "Stabilise electrical supply", [
                    "Confirm which buses and generators are available",
                    "Do not cycle electrical sources repeatedly",
                    f"Follow {config_word} actions and monitor essential displays",
                    "Start APU if permitted and useful for the simulated aircraft condition",
                ]),
                _section("elec_operate", "Operate with degraded capability", [
                    "Review available radios, navigation, autopilot and landing systems",
                    "Preserve battery time if operating on standby/emergency power",
                    "Plan direct routing and a suitable runway if redundancy is reduced",
                    "Record any telemetry interruptions if simulator interfaces are affected",
                ]),
            ],
        ),
        "fuel_abnormal": _nn(
            "fuel_abnormal",
            "Fuel Imbalance / Leak / Low Fuel",
            "Fuel",
            "warning",
            ["fuel", "imbalance", "leak", "low fuel", "crossfeed", "fuel temp"],
            "Fuel imbalance, suspected fuel leak, low fuel state or feed abnormal.",
            [],
            [
                _section("fuel_identify", "Identify the fuel problem", [
                    "Compare total fuel, tank quantities and expected burn",
                    "If leak is suspected, identify whether fuel is decreasing abnormally from one side/tank",
                    f"Use {config_word} before changing pumps or crossfeed",
                    "Check destination, alternate and nearest suitable airports",
                ]),
                _section("fuel_plan", "Plan fuel-critical operation", [
                    "Declare minimum fuel or emergency only when appropriate for the scenario/network",
                    "Avoid unnecessary holding, vectoring or high drag configuration",
                    "Plan landing with emergency services if leak or fuel starvation is suspected",
                    "After landing, keep engines running/shutdown according to fire/leak risk and checklist guidance",
                ]),
            ],
        ),
        "gear_abnormal": _nn(
            "gear_abnormal",
            "Landing Gear Abnormal",
            "Landing Gear",
            "warning",
            ["gear", "landing gear", "gravity extension", "alternate extension", "unsafe gear", "gear disagree"],
            "Gear extension, indication or locking abnormal.",
            [],
            [
                _section("gear_troubleshoot", "Troubleshoot and configure", [
                    "Maintain safe altitude and speed before troubleshooting",
                    "Confirm lever position, indications, hydraulic pressure and circuit status where modelled",
                    f"Run the aircraft {config_word} procedure for alternate/gravity gear extension",
                    "Avoid repeated cycling unless the checklist explicitly directs it",
                ]),
                _section("gear_landing", "Landing planning", [
                    "Request visual inspection if available and useful",
                    "Plan long runway, low crosswind and emergency services",
                    "Brief touchdown attitude, rollout expectations and evacuation criteria",
                    "After landing, stop straight ahead if steering/braking/gear status is uncertain",
                ]),
            ],
        ),
        "flap_slat_abnormal": _nn(
            "flap_slat_abnormal",
            "Flap / Slat / High-Lift Abnormal",
            "Flight Controls",
            "warning",
            ["flap", "slat", "high lift", "flaps locked", "slats locked", "flap asymmetry"],
            "Flap or slat disagreement, asymmetry, lockout or abnormal landing configuration.",
            [],
            [
                _section("flap_control", "Control and stop configuration changes", [
                    "Maintain control and observe speed limits for current configuration",
                    "Stop further flap/slat movement if asymmetry or abnormal movement is suspected",
                    f"Follow {config_word} and determine available landing configuration",
                    "Check go-around performance and higher approach speed implications",
                ]),
                _section("flap_land", "Abnormal landing configuration", [
                    "Select the longest suitable runway and calculate landing distance penalty",
                    "Plan higher approach speed, longer flare and increased rollout distance",
                    "Brief touchdown zone discipline and no unnecessary floating",
                    "Keep automation only if it behaves correctly for the abnormal configuration",
                ]),
            ],
        ),
        "brake_steering_abnormal": _nn(
            "brake_steering_abnormal",
            "Brake / Steering / Tyre Abnormal",
            "Landing Gear",
            "warning",
            ["brake", "steering", "tyre", "tire", "hot brakes", "autobrake", "anti skid", "skid"],
            "Brake, anti-skid, steering, tyre or hot-brake abnormal.",
            [],
            [
                _section("brake_assess", "Assess braking and steering", [
                    "Identify whether normal braking, alternate braking, anti-skid or steering is degraded",
                    "Avoid high taxi speed and sharp turns if tyre/brake issue is suspected",
                    "Check brake temperature indications if available",
                    f"Run {config_word} and plan ground handling before landing or taxi",
                ]),
                _section("brake_land", "Landing and taxi planning", [
                    "Use a long dry runway if possible and avoid unnecessary tailwind",
                    "Plan autobrake/manual braking according to available system",
                    "After landing, use gentle directional control and consider stopping on runway",
                    "Do not taxi to stand if hot brakes, tyre damage or steering failure is likely",
                ]),
            ],
        ),
        "tcas_ra": _nn(
            "tcas_ra",
            "TCAS Resolution Advisory",
            "ATC / Traffic",
            "critical",
            ["tcas", "ra", "resolution", "traffic", "climb now", "descend now"],
            "TCAS RA response and recovery.",
            [
                "Respond immediately to the RA vertical guidance",
                "Disconnect or override vertical automation if necessary",
                "Do not manoeuvre opposite to the RA",
                "Return to clearance only when clear of conflict",
            ],
            [
                _section("tcas_response", "RA response", [
                    "Follow the green/commanded vertical guidance as displayed by the aircraft",
                    "Announce TCAS RA to ATC when workload permits",
                    "Monitor traffic and avoid large lateral manoeuvres unless required for safety",
                    "When clear, return smoothly to assigned altitude and route",
                ], "memory"),
                _section("tcas_after", "After RA", [
                    "Advise ATC when returning to clearance",
                    "Check passenger signs and cabin status after abrupt manoeuvre",
                    "Note the event in the PIREP debrief",
                ]),
            ],
        ),
        "windshear_escape": _nn(
            "windshear_escape",
            "Windshear / GPWS Escape",
            "Terrain / Weather",
            "critical",
            ["windshear", "gpws", "terrain", "pull up", "escape", "sink rate"],
            "Windshear or terrain escape guidance.",
            [
                "Apply maximum available thrust/power",
                "Pitch to escape guidance or safe pitch attitude",
                "Do not change configuration until clear unless required by aircraft guidance",
                "Respect stall warning and terrain clearance priorities",
            ],
            [
                _section("escape_manoeuvre", "Escape manoeuvre", [
                    "Disconnect automation if it prevents immediate escape response",
                    "Follow flight-director escape guidance if valid; otherwise fly attitude manually",
                    "Monitor speed trend, pitch and radio altitude",
                    "Announce go-around/escape and advise ATC when able",
                ], "memory"),
                _section("escape_recover", "Recover and re-plan", [
                    "Climb to safe altitude and clean up only when safely away from terrain/windshear",
                    "Check aircraft limits and passenger/cabin status",
                    "Do not attempt another approach until weather and configuration are reviewed",
                    "Log the escape event in the debrief",
                ]),
            ],
        ),
        "autopilot_flight_director_abnormal": _nn(
            "autopilot_flight_director_abnormal",
            "Autopilot / Flight Director / Autothrottle Abnormal",
            "Automation",
            "advisory",
            ["autopilot", "flight director", "fd", "autothrottle", "autothrust", "athr", "automation", "mcp", "managed"],
            "Unexpected automation behaviour, mode reversion or autothrottle/autothrust failure.",
            [],
            [
                _section("auto_takeover", "Take over manually if required", [
                    "Confirm active modes and aircraft response before making inputs",
                    "Disconnect autopilot or autothrottle/autothrust if the aircraft is not following the intended path",
                    "Set known pitch, thrust and lateral guidance manually",
                    f"Rebuild {automation} only after the aircraft is stable",
                ]),
                _section("auto_continue", "Continue with degraded automation", [
                    "Brief manual or reduced-automation approach if required",
                    "Use raw data / selected modes instead of complex managed guidance when workload is high",
                    "Monitor speed and vertical path closely below 10,000 ft and on final",
                ]),
            ],
        ),
        "evacuation": _nn(
            "evacuation",
            "Evacuation Decision Aid",
            "Ground Emergency",
            "critical",
            ["evac", "evacuation", "evacuate", "cabin fire", "smoke evacuation", "emergency evacuation"],
            "Post-stop evacuation decision support for simulator emergencies.",
            [
                "Stop aircraft and set parking brake if possible",
                "Assess fire/smoke/structural danger and outside conditions",
                "Shut down engines as required before evacuation command",
                "Command evacuation only when it is the safest option in the scenario",
            ],
            [
                _section("evac_decide", "Decision", [
                    "Consider evacuation for uncontrolled fire, heavy smoke, fuel leak, major structural damage or emergency-service instruction",
                    "Avoid evacuation if the risk outside is greater and the aircraft can be secured safely",
                    "Coordinate with cabin crew if simulated/provided",
                    f"Follow aircraft {config_word} evacuation actions",
                ], "memory"),
                _section("evac_secure", "Secure aircraft", [
                    "Set transponder/radios as required for network context",
                    "Engine masters/fuel control switches off when directed",
                    "APU/fire controls and battery/electrical controls handled according to the checklist",
                    "Record evacuation event in the PIREP notes",
                ]),
            ],
        ),
    }


def _family_data(family: str) -> dict[str, Any]:
    if family == "airbus":
        meta = AIRBUS_COMMON
    elif family == "boeing":
        meta = BOEING_COMMON
    else:
        meta = GENERIC_COMMON
    return {**meta, "key": family, "conditions": _shared_conditions(family)}


FAMILIES = {family: _family_data(family) for family in ("airbus", "boeing", "generic")}

PROFILE_TO_FAMILY = {
    "fenix_a320": "airbus",
    "fbw_a380x": "airbus",
    "inibuilds_a350": "airbus",
    "a340_600": "airbus",
    "airbus": "airbus",
    "pmdg_737": "boeing",
    "pmdg_777": "boeing",
    "boeing_787": "boeing",
    "boeing": "boeing",
    "generic_jet": "generic",
    "turboprop": "generic",
    "general_aviation": "generic",
}

AVAILABLE_PROFILES = [
    {"key": "", "label": "AUTO DETECT"},
    {"key": "airbus", "label": "AIRBUS FAMILY"},
    {"key": "boeing", "label": "BOEING FAMILY"},
    {"key": "generic", "label": "GENERIC JET"},
    {"key": "fenix_a320", "label": "FENIX A320/A321"},
    {"key": "fbw_a380x", "label": "FBW A380X"},
    {"key": "inibuilds_a350", "label": "INIBUILDS A350"},
    {"key": "pmdg_737", "label": "PMDG 737NG"},
    {"key": "pmdg_777", "label": "PMDG 777"},
    {"key": "boeing_787", "label": "BOEING 787"},
]


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _detect_profile_text(aircraft_text: str) -> str:
    value = aircraft_text.upper()
    if "FENIX" in value and any(token in value for token in ("A319", "A320", "A321", "A20N", "A21N")):
        return "fenix_a320"
    if any(token in value for token in ("A380X", "FBW A380", "FLYBYWIRE A380")):
        return "fbw_a380x"
    if any(token in value for token in ("INIBUILDS A350", "INI A350", "A350-900", "A350-1000", "A359", "A35K")):
        return "inibuilds_a350"
    if any(token in value for token in ("AIRBUS", "A319", "A320", "A321", "A330", "A340", "A350", "A380", "A32NX", "FSLABS")):
        return "airbus"
    if "PMDG" in value and any(token in value for token in ("737", "B737", "B738", "B739")):
        return "pmdg_737"
    if "PMDG" in value and any(token in value for token in ("777", "B777", "77W", "77F", "77L")):
        return "pmdg_777"
    if any(token in value for token in ("787", "B787", "B78X")):
        return "boeing_787"
    if any(token in value for token in ("BOEING", "B737", "B747", "B757", "B767", "B777", "B787", "PMDG", "77F", "77W")):
        return "boeing"
    return "generic_jet"


def _aircraft_context() -> tuple[str, str, dict[str, Any]]:
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
    detected_profile = _detect_profile_text(aircraft_text)
    return aircraft_text, detected_profile, watch


def _suggestions(family: str, watch: dict[str, Any]) -> list[dict[str, Any]]:
    telemetry = watch.get("telemetry") if isinstance(watch.get("telemetry"), dict) else {}
    phase = str(watch.get("phase") or "").upper()
    on_ground = bool(telemetry.get("on_ground"))
    gs = _num(telemetry.get("ground_speed_kts")) or 0.0
    agl = _num(telemetry.get("agl_ft"))
    vs = _num(telemetry.get("vertical_speed_fpm")) or 0.0
    suggestions: list[dict[str, Any]] = []
    def add(key: str, reason: str, confidence: str = "possible") -> None:
        cond = FAMILIES[family]["conditions"].get(key)
        if cond:
            suggestions.append({"key": key, "title": cond["title"], "severity": cond["severity"], "reason": reason, "confidence": confidence})
    text = " ".join(str(v).lower() for v in telemetry.values() if isinstance(v, (str, int, float, bool)))
    if "fire" in text:
        add("engine_fire", "A fire-related simulator/telemetry indication was seen.", "suggested")
    if any(word in text for word in ("overspeed", "airspeed disagree", "unreliable")):
        add("unreliable_airspeed", "Speed or air-data-related indication detected.")
    if "hyd" in text or "hydraulic" in text:
        add("hydraulic_abnormal", "Hydraulic-related indication detected.")
    if "generator" in text or "electrical" in text or "battery" in text:
        add("electrical_abnormal", "Electrical-related indication detected.")
    if phase == "TAKEOFF ROLL" and on_ground and gs > 80:
        add("rejected_takeoff", "Aircraft is in a high-speed takeoff-roll condition; keep RTO checklist close.")
    if phase == "APPROACH" and agl is not None and agl < 1500 and gs > 100:
        # Gear state naming varies across providers; only suggest when known not down.
        gear = telemetry.get("gear_down") if "gear_down" in telemetry else telemetry.get("landing_gear_down")
        if gear is False:
            add("gear_abnormal", "Approach below 1,500 ft AGL with gear not confirmed down.", "suggested")
    if phase in {"APPROACH", "DESCENT"} and agl is not None and agl < 5000 and vs < -2200:
        add("windshear_escape", "High sink rate near terminal environment; review escape/GPWS actions if warning occurs.")
    # Deduplicate while preserving order.
    seen = set(); result = []
    for item in suggestions:
        if item["key"] not in seen:
            seen.add(item["key"]); result.append(item)
    return result[:4]


def _copy_condition(condition: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": condition["key"],
        "title": condition["title"],
        "category": condition["category"],
        "severity": condition["severity"],
        "summary": condition["summary"],
        "keywords": list(condition.get("keywords", [])),
        "families": list(condition.get("families", [])),
        "memory_items": [dict(row) for row in condition.get("memory_items", [])],
        "sections": [
            {"key": sec["key"], "title": sec["title"], "kind": sec.get("kind", "qrh"), "items": [dict(row) for row in sec.get("items", [])]}
            for sec in condition.get("sections", [])
        ],
    }


def build_non_normal(profile_override: str = "", query: str = "", selected_condition: str = "") -> dict[str, Any]:
    aircraft_text, detected_profile, watch = _aircraft_context()
    selected_profile = profile_override if profile_override in PROFILE_TO_FAMILY or profile_override in {"airbus", "boeing", "generic"} else detected_profile
    family_key = PROFILE_TO_FAMILY.get(selected_profile, selected_profile if selected_profile in FAMILIES else "generic")
    data = FAMILIES.get(family_key, FAMILIES["generic"])
    q = (query or "").strip().lower()
    all_conditions = list(data["conditions"].values())
    if q:
        conditions = [
            c for c in all_conditions
            if q in c["title"].lower()
            or q in c["category"].lower()
            or any(q in kw.lower() for kw in c.get("keywords", []))
            or q in c.get("summary", "").lower()
        ]
    else:
        conditions = all_conditions
    if not conditions:
        conditions = all_conditions
    selected_key = selected_condition if selected_condition in data["conditions"] else (conditions[0]["key"] if conditions else "")
    selected = _copy_condition(data["conditions"][selected_key]) if selected_key else None
    return {
        "ok": True,
        "profile": {"key": selected_profile, "family": family_key, "label": data["label"], "source": data["source"], "detected": detected_profile},
        "available_profiles": AVAILABLE_PROFILES,
        "aircraft": aircraft_text or "AIRCRAFT NOT DETECTED",
        "philosophy": list(data["philosophy"]),
        "conditions": [
            {"key": c["key"], "title": c["title"], "category": c["category"], "severity": c["severity"], "summary": c["summary"], "keywords": c.get("keywords", [])}
            for c in conditions
        ],
        "selected": selected,
        "suggestions": _suggestions(family_key, watch),
        "notice": "For flight simulation use only. This is not real-world aviation documentation and must not replace the aircraft ECAM/EICAS/QRH.",
        "source_note": "User-supplied HughLB Fenix A319/A320/A321, PMDG 737NG and PMDG 777-300ER graphical checklist files were reviewed as simulator context. The non-normal library is generalized and original; the PDFs are not redistributed.",
        "updated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
