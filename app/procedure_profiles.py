from __future__ import annotations

from typing import Any


def item(key: str, text: str, note: str = "") -> dict[str, str]:
    return {"key": key, "text": text, "note": note}


def rows(prefix: str, values: list[str | tuple[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for index, value in enumerate(values, start=1):
        if isinstance(value, tuple):
            text, note = value
        else:
            text, note = value, ""
        result.append(item(f"{prefix}_{index:02d}", text, note))
    return result


def profile(key: str, label: str, source: str, phases: dict[str, list[str | tuple[str, str]]]) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "source": source,
        "phases": {phase: rows(f"{key}_{phase}", values) for phase, values in phases.items()},
    }


FENIX_A320 = profile(
    "fenix_a320",
    "FENIX A320 / A321",
    "Condensed from JDs CL A320 Fenix 1.31.1 supplied by the user",
    {
        "preflight": [
            "Parking brake set, landing gear down and engine masters off",
            "Batteries on, external power connected or APU started",
            "ADIRS selectors set to NAV and alignment monitored",
            "Emergency lights armed, signs and exterior lights set for the stand",
            "Fuel quantity, payload and loading checked against the OFP",
            "MCDU INIT, route, flight plan and secondary flight plan reviewed",
            "MCDU performance, thrust reduction, acceleration and engine-out data entered",
            "Takeoff data and V-speeds cross-checked on both sides",
            "Departure clearance, weather and departure briefing completed",
        ],
        "before_start": [
            "Windows, doors and service panels confirmed closed",
            "Fuel pumps on and APU bleed or pneumatic source configured",
            "Seat-belt signs on and beacon on",
            "Takeoff flaps and pitch trim set",
            "Speedbrake lever retracted and parking brake or chocks confirmed",
            "Pushback and start clearance obtained",
        ],
        "after_start": [
            "Engine mode selector returned to NORM",
            "APU bleed and APU set as required after engine stabilisation",
            "Anti-ice selected as required",
            "ECAM status checked with no unresolved start abnormalities",
            "Flight controls checked full and free",
            "Pitch trim, rudder trim and takeoff flap setting verified",
        ],
        "taxi": [
            "Nose light set to TAXI and runway turnoff lights as required",
            "Brakes checked shortly after movement",
            "Flight instruments and heading indications cross-checked",
            "Takeoff configuration test completed",
            "Taxi routing and runway entry point confirmed",
        ],
        "before_takeoff": [
            "Cabin crew advised and cabin ready received",
            "Autobrake MAX selected",
            "Ground spoilers armed and takeoff flaps confirmed",
            "TCAS set to TA/RA and transponder operating",
            "Exterior lights and packs configured for takeoff",
            "ECAM takeoff memo reviewed with no blue items",
            "Runway, departure and initial cleared altitude verified",
        ],
        "after_takeoff": [
            "Landing gear up and indicated",
            "Flaps retracted on schedule and speedbrake disarmed",
            "Packs and APU configuration normalised",
            "Nose and runway lights set for climb",
            "Altimeters set to standard passing transition altitude",
        ],
        "climb_cruise": [
            "Climb mode, managed guidance and cleared altitude monitored",
            "Seat-belt signs and exterior lights set as required",
            "Fuel, route progress and ECAM systems reviewed",
            "Cruise altitude and destination weather monitored",
        ],
        "descent": [
            "Arrival and approach inserted and discontinuities resolved",
            "Destination ATIS, runway and landing weather reviewed",
            "PERF APPR page completed with QNH, temperature, wind and minima",
            "Landing performance, autobrake and flap configuration selected",
            "Approach and missed-approach briefing completed",
            "Seat-belt signs on and cabin advised before descent",
        ],
        "approach": [
            "Altimeters cross-checked at transition level",
            "Approach phase activated or managed deceleration confirmed",
            "LS display selected when required and approach guidance checked",
            "Ground spoilers armed and autobrake confirmed",
            "Landing gear and flaps extended within placard speeds",
            "Go-around altitude and procedure confirmed",
        ],
        "landing": [
            "Landing gear down with three green indications",
            "Landing flap and target speed confirmed",
            "ECAM landing memo reviewed with no blue items",
            "Cabin crew advised and stable-approach criteria monitored",
        ],
        "after_landing": [
            "Ground spoilers disarmed and flaps retracted",
            "Weather radar and predictive windshear off",
            "TCAS set to standby and transponder set for ground operation",
            "Landing and strobe lights off; taxi lights set",
            "APU started when required for the stand",
        ],
        "shutdown": [
            "Parking brake set or chocks confirmed",
            "Engine masters off and beacon off after engines stop",
            "Fuel pumps and seat-belt signs off",
            "External power or APU supply established as required",
            "ADIRS, oxygen, emergency lights and batteries secured as appropriate",
            "Post-flight ECAM status and technical log reviewed",
        ],
    },
)


PMDG_737 = profile(
    "pmdg_737",
    "PMDG 737NG",
    "Condensed from PMDG 737NG Checklist BritishAvgeek V3 supplied by the user",
    {
        "preflight": [
            "Parking brake set and landing gear lever down",
            "Battery and standby power on; emergency exit lights armed",
            "Ground power connected and IRS selectors set to NAV",
            "Warning systems tested, yaw damper and window heat on",
            "Electric hydraulic pumps and passenger signs set",
            "FMC route, performance and departure entered and checked",
            "Pressurisation cruise and landing altitudes set",
            "Radios, transponder, MCP and flight directors set",
            "Fuel, loading and takeoff data completed",
        ],
        "before_start": [
            "APU started, generators on and APU bleed established",
            "Packs and isolation valve configured for start",
            "Doors closed, equipment clear and chocks removed",
            "Anti-collision light on",
            "Pushback and start clearance obtained",
        ],
        "after_start": [
            "Generators on and engine start switches set AUTO or CONT as required",
            "Probe heat on and wing or engine anti-ice set as required",
            "Bleeds, packs, recirculation fans and isolation valve set",
            "APU bleed and APU off when no longer required",
            "Flaps and stabiliser trim set for takeoff",
            "Flight controls checked full and free",
            "Autothrottle armed and warning recall considered",
        ],
        "taxi": [
            "Taxi light on and autobrake set to RTO",
            "Brakes, compass and gyro checked",
            "V-speeds and MCP or navigation data verified",
            "Takeoff clearance and runway entry instructions understood",
        ],
        "before_takeoff": [
            "Position lights set strobe and steady",
            "Landing and runway turnoff lights on; taxi light off",
            "Transponder set TA/RA and traffic display on",
            "Clock started and runway confirmed",
            "Takeoff configuration and departure modes checked",
        ],
        "after_takeoff": [
            "Landing gear up, then gear lever off when appropriate",
            "Autobrake off and engine start switches normalised",
            "Flaps retracted on schedule",
            "Runway turnoff lights off",
            "Cabin pressure checked and altimeters set standard",
        ],
        "climb_cruise": [
            "Landing lights off above 10,000 ft and signs as required",
            "Cruise systems, fuel and pressurisation monitored",
            "Arrival weather and expected runway reviewed",
        ],
        "descent": [
            "Destination weather and arrival data obtained",
            "Pressurisation landing altitude, radios and ILS data set",
            "Landing flap and VREF selected in the FMC",
            "Autobrake, minima and missed-approach altitude set",
            "Approach briefing and warning recall completed",
            "Altimeters set to local pressure below transition level",
        ],
        "approach": [
            "Navigation course and frequency checked",
            "Flaps extended on schedule and speedbrake armed",
            "Approach mode armed when required",
            "Landing gear down and confirmed",
            "Engine start switches set CONT or AUTO as required",
            "Landing flap, go-around altitude and automation confirmed",
        ],
        "landing": [
            "Landing gear down and landing flap confirmed",
            "Speedbrake armed and autobrake selected",
            "Landing clearance confirmed and go-around readiness maintained",
        ],
        "after_landing": [
            "Flaps up and speedbrake retracted",
            "Transponder and position lights set for ground operation",
            "Landing and runway turnoff lights off; taxi light on",
            "APU started and bleed established if required",
            "Probe heat, anti-ice and engine start switches normalised",
        ],
        "shutdown": [
            "Parking brake set and ground equipment or chocks in position",
            "Fuel control levers cutoff and anti-collision light off",
            "Fuel pumps, passenger signs and flight directors off as required",
            "Isolation valve opened and electrical source transferred",
            "Disembarkation monitored and aircraft secured",
        ],
    },
)


PMDG_777 = profile(
    "pmdg_777",
    "PMDG 777",
    "Condensed from JD CL B777 PMDG 2024 v1.37.3 supplied by the user",
    {
        "preflight": [
            "Battery, bus ties and electrical power established",
            "ADIRU on and primary flight computers normal and guarded",
            "Hydraulic, fuel, anti-ice, bleed and air-conditioning panels set",
            "Emergency lights armed, passenger signs and lighting set",
            "FMC position, route, departure, performance and takeoff data completed",
            "Tablet or EFB loads, fuel, payload and performance cross-checked",
            "Landing altitude, pressurisation and oxygen systems checked",
            "Flight deck displays, clocks, radios and transponder configured",
            "Preflight checklist completed",
        ],
        "before_start": [
            "Doors and service equipment clear; chocks removed",
            "Hydraulic panel and fuel pumps set for start",
            "Beacon on and passenger signs set",
            "CDU preflight complete with takeoff speeds displayed",
            "Pushback and start clearance obtained",
            "Parking brake set or released as coordinated with pushback",
        ],
        "after_start": [
            "Generators verified on with no fault indications",
            "Start selectors returned to normal and engine indications stable",
            "Packs, bleeds and APU set for taxi",
            "Anti-ice selected as required",
            "Flight controls checked and takeoff flaps set",
            "Takeoff trim, autobrake and transponder confirmed",
        ],
        "taxi": [
            "Taxi light and runway turnoff lights set as required",
            "Parking brake released and brakes or steering checked",
            "Flight instruments and heading indications cross-checked",
            "Taxi route, runway and departure clearance reviewed",
        ],
        "before_takeoff": [
            "Autobrake RTO and speedbrake armed",
            "Landing lights, strobe and transponder set for departure",
            "FMA takeoff modes and LNAV or VNAV arming verified",
            "Takeoff configuration warning check completed",
            "Runway, heading and cleared altitude verified",
            "Before takeoff checklist completed",
        ],
        "after_takeoff": [
            "Landing gear up and flaps retracted on schedule",
            "Autobrake off and climb thrust confirmed",
            "Exterior lights set for climb",
            "Altimeters set to standard at transition altitude",
            "After takeoff checklist completed",
        ],
        "climb_cruise": [
            "Climb guidance and pressurisation monitored",
            "Fuel, route progress and systems checked",
            "Top of descent verified and arrival planning started",
            "Landing performance and FMC approach configuration reviewed before descent",
        ],
        "descent": [
            "Arrival, approach and destination weather reviewed",
            "Landing data, flap and VREF correction selected",
            "Approach briefing and missed approach completed",
            "Descent path and drag messages monitored",
            "Altimeters set to local pressure below transition level",
            "Landing lights and passenger signs set as required",
        ],
        "approach": [
            "Autobrake and landing data confirmed",
            "ILS or approach navigation data checked",
            "Flaps extended on schedule and approach mode verified on FMA",
            "Landing gear down and speedbrake armed",
            "Missed-approach altitude preselected when operationally appropriate",
            "Stable approach criteria and landing system annunciations monitored",
        ],
        "landing": [
            "Speedbrakes armed, landing gear down and landing flap set",
            "Autobrake selected and landing clearance confirmed",
            "Target speed and wind correction checked",
            "Go-around readiness maintained until touchdown",
        ],
        "after_landing": [
            "Landing and strobe lights off; taxi lights set",
            "Speedbrake down, autobrake off and flaps up",
            "Transponder set for ground operation",
            "Weather radar and terrain or traffic overlays set as required",
            "APU started when required for parking",
        ],
        "shutdown": [
            "Parking brake set and APU or external power available",
            "Fuel control switches cutoff and beacon off",
            "Electric hydraulic pumps and fuel pumps off",
            "Passenger signs, flight directors and transponder set for parking",
            "ADIRU, emergency lights, packs, APU and battery secured as required",
            "Shutdown and securing checklists completed",
        ],
    },
)


BOEING_787 = profile(
    "boeing_787",
    "BOEING 787",
    "Condensed from JD CL Boeing 787 2023 v1.33.7 supplied by the user",
    {
        "preflight": [
            "Battery and external power established; electrical synoptic checked",
            "ADIRU, hydraulic demand pumps and fuel panel configured",
            "Emergency lighting, passenger signs and exterior lighting set",
            "FMC position, route, departure and performance data completed",
            "Electronic checklist and EICAS messages reviewed",
            "Air-conditioning, pressurisation, oxygen and anti-ice panels checked",
            "Takeoff data, weight and balance and EFB performance verified",
            "Radios, transponder, displays and flight controls configured",
        ],
        "before_start": [
            "Doors closed and ground equipment clear",
            "Fuel pumps and hydraulic systems configured",
            "Beacon on and passenger signs set",
            "Takeoff flaps and trim set",
            "Pushback and start clearance obtained",
        ],
        "after_start": [
            "Engine indications stable and generators online",
            "APU, packs and bleeds set for taxi",
            "Anti-ice selected as required",
            "Flight controls checked and takeoff configuration verified",
            "Autobrake RTO and transponder set",
        ],
        "taxi": [
            "Taxi lights set and brakes checked",
            "Flight instruments and heading indications checked",
            "Taxi route and departure clearance reviewed",
            "Electronic before takeoff checklist prepared",
        ],
        "before_takeoff": [
            "Landing lights and strobe set for departure",
            "Takeoff modes and flight director annunciations verified",
            "Runway and initial altitude confirmed",
            "Takeoff configuration normal and checklist complete",
        ],
        "after_takeoff": [
            "Landing gear up and flaps retracted on schedule",
            "Autobrake off and climb thrust confirmed",
            "Lights and passenger signs set for climb",
            "Altimeters set to standard",
        ],
        "climb_cruise": [
            "Climb and cruise systems monitored",
            "Fuel and route progress checked",
            "Arrival weather and top of descent reviewed",
            "Landing performance prepared before descent",
        ],
        "descent": [
            "Arrival and approach loaded and checked",
            "Landing data, minima and autobrake selected",
            "Approach briefing and missed approach reviewed",
            "Altimeters and exterior lights set at the appropriate levels",
        ],
        "approach": [
            "Navigation source and approach modes checked",
            "Flaps extended on schedule",
            "Speedbrake armed and landing gear down",
            "Landing configuration, target speed and go-around altitude confirmed",
        ],
        "landing": [
            "Landing checklist complete and gear down",
            "Landing flap, speedbrake and autobrake confirmed",
            "Stable approach and landing clearance monitored",
        ],
        "after_landing": [
            "Flaps up and speedbrake retracted",
            "Landing and strobe lights off; taxi lights set",
            "Transponder and weather radar set for ground operation",
            "APU started as required",
        ],
        "shutdown": [
            "Parking brake set and electrical source established",
            "Fuel control switches cutoff and beacon off",
            "Fuel pumps, hydraulics and passenger signs set for parking",
            "ADIRU, packs, emergency lights and batteries secured as required",
            "Electronic shutdown and secure checklists completed",
        ],
    },
)


INIBUILDS_A350 = profile(
    "inibuilds_a350",
    "INIBUILDS A350",
    "Condensed from INI A350 checklist supplied by the user",
    {
        "preflight": [
            "Engine masters off, parking brake set and gear lever down",
            "Batteries and external power on; electrical system checked",
            "ADIRS set to NAV and alignment monitored",
            "Oxygen, emergency lights, signs and lighting configured",
            "Fuel, payload and loading data checked",
            "OIS or MFD flight plan, performance and takeoff data completed",
            "Weather radar, predictive windshear and anti-ice set for the stand",
            "Departure briefing and clearance completed",
        ],
        "before_start": [
            "Windows and doors closed and service equipment clear",
            "Fuel pumps on and APU bleed configured",
            "Beacon on and passenger signs set",
            "Takeoff flaps, trim and speedbrake position checked",
            "Pushback and start clearance obtained",
        ],
        "after_start": [
            "Engine start selector normal and engine indications stable",
            "APU bleed and APU set as required",
            "Anti-ice selected as required",
            "ECAM status checked",
            "Flight controls, trims and takeoff configuration verified",
        ],
        "taxi": [
            "Taxi and runway turnoff lights set",
            "Brakes and steering checked",
            "Flight instruments cross-checked",
            "Takeoff configuration test completed",
        ],
        "before_takeoff": [
            "Cabin crew advised and cabin ready received",
            "Ground spoilers armed and autobrake selected",
            "TCAS and transponder set for flight",
            "Landing lights and strobe on",
            "ECAM takeoff memo reviewed with no unresolved items",
        ],
        "after_takeoff": [
            "Landing gear up and flaps retracted on schedule",
            "Speedbrake disarmed and climb configuration normal",
            "Exterior lights set for climb",
            "Altimeters set to standard",
        ],
        "climb_cruise": [
            "Climb or cruise guidance and systems monitored",
            "Fuel, route progress and destination weather reviewed",
            "Arrival planning started before top of descent",
        ],
        "descent": [
            "Arrival and approach entered and checked",
            "Destination ATIS and runway reviewed",
            "Landing performance, minima and PERF approach data set",
            "Approach and missed-approach briefing completed",
            "Seat-belt signs and cabin preparation completed",
        ],
        "approach": [
            "Altimeters cross-checked",
            "Approach guidance and navigation displays checked",
            "Ground spoilers armed and autobrake confirmed",
            "Landing gear and flaps extended within limits",
            "Go-around altitude and procedure confirmed",
        ],
        "landing": [
            "Landing gear down and landing flap set",
            "ECAM landing memo reviewed",
            "Cabin crew advised and stable criteria monitored",
        ],
        "after_landing": [
            "Flaps retracted and spoilers disarmed",
            "Weather radar and predictive windshear off",
            "TCAS or transponder set for ground operation",
            "Landing and strobe lights off; taxi lights set",
            "APU started as required",
        ],
        "shutdown": [
            "Parking brake or chocks confirmed",
            "Engine masters off and beacon off",
            "Fuel pumps and passenger signs off",
            "External power or APU established as required",
            "ADIRS, emergency lighting and batteries secured as appropriate",
        ],
    },
)


FBW_A380X = profile(
    "fbw_a380x",
    "FBW A380X",
    "Condensed from FBW A380X Full SOP Checklist supplied by the user",
    {
        "preflight": [
            "Engine masters off, thrust levers idle and reversers stowed",
            "Parking brake set, gear lever down and flaps or speedbrake retracted",
            "All batteries on, external power connected or APU started",
            "ADIRS, oxygen, emergency lights, signs and lighting configured",
            "Fuel, cargo, passengers and loading checked against the OFP",
            "MFD flight plan, route, performance and takeoff data completed",
            "Overhead, instrument panels and pedestal scanned",
            "Departure weather, clearance and briefing completed",
        ],
        "before_start": [
            "Doors and service panels closed and ground equipment clear",
            "Fuel pumps on and APU bleed or pneumatic supply configured",
            "Beacon on and passenger signs set",
            "Takeoff flaps and trim set",
            "Pushback and start clearance obtained",
        ],
        "after_start": [
            "Engine start selector normal and engine indications stable",
            "APU bleed and APU set as required",
            "Anti-ice selected as required",
            "ECAM status and memo checked",
            "Flight controls, trims and takeoff configuration verified",
        ],
        "taxi": [
            "Taxi lights and runway turnoff lights set",
            "Brakes and steering checked",
            "Flight instruments cross-checked",
            "Takeoff configuration test completed",
        ],
        "before_takeoff": [
            "Cabin crew advised and cabin ready received",
            "Ground spoilers armed and autobrake selected",
            "TCAS and transponder set for flight",
            "Landing lights and strobe set",
            "ECAM takeoff memo reviewed with no unresolved items",
        ],
        "after_takeoff": [
            "Landing gear up and flaps retracted on schedule",
            "Speedbrake disarmed and climb configuration normal",
            "Exterior lights set for climb",
            "Altimeters set to standard",
        ],
        "climb_cruise": [
            "Climb and cruise systems monitored",
            "Fuel and route progress checked",
            "Destination weather and arrival planning reviewed",
        ],
        "descent": [
            "Arrival and approach entered and verified",
            "Destination weather, ATIS and runway reviewed",
            "Landing performance, minima and approach data set",
            "Approach and missed-approach briefing completed",
            "Seat-belt signs and cabin preparation completed",
        ],
        "approach": [
            "Altimeters and approach navigation cross-checked",
            "Ground spoilers armed and autobrake confirmed",
            "Landing gear and flaps extended within limits",
            "Approach checklist and go-around setup completed",
        ],
        "landing": [
            "Landing gear down and landing flap set",
            "ECAM landing memo reviewed",
            "Cabin crew advised and stable approach monitored",
        ],
        "after_landing": [
            "Flaps retracted and spoilers disarmed",
            "Weather radar and predictive windshear off",
            "TCAS or transponder set for ground operation",
            "Landing and strobe lights off; taxi lights set",
            "APU started as required",
        ],
        "shutdown": [
            "Parking brake or chocks confirmed",
            "Engine masters off and beacon off",
            "Fuel pumps and passenger signs off",
            "External power or APU established as required",
            "ADIRS, emergency lights, oxygen and batteries secured as appropriate",
        ],
    },
)


A340_600 = profile(
    "a340_600",
    "AIRBUS A340-600",
    "Condensed from Airbus A340-600 Normal Procedures checklist supplied by the user",
    {
        "preflight": [
            "Cockpit preparation completed by both pilots",
            "Gear pins and covers removed",
            "Signs set and ADIRS selectors at NAV",
            "Fuel quantity and takeoff data cross-checked",
            "Barometric references set on both sides",
        ],
        "before_start": [
            "Windows and doors closed",
            "Beacon on, thrust levers idle and parking brake as required",
            "Pushback and start clearance obtained",
        ],
        "after_start": [
            "Anti-ice set as required",
            "ECAM status checked",
            "Takeoff trims set",
        ],
        "taxi": [
            "Flight controls and flight instruments checked by both pilots",
            "Taxi routing and runway entry confirmed",
        ],
        "before_takeoff": [
            "Departure briefing confirmed",
            "Flaps, V-speeds and flex temperature cross-checked",
            "ATC clearance confirmed",
            "ECAM takeoff memo reviewed with no blue items",
            "Cabin crew advised, lights on and packs configured",
            "Radar, TCAS and predictive windshear set",
        ],
        "after_takeoff": [
            "Landing gear up and flaps retracted",
            "Packs and APU configuration normalised",
            "Barometric references set on both sides",
        ],
        "climb_cruise": [
            "Climb and cruise systems, fuel and route progress monitored",
            "Arrival and weather reviewed before descent",
        ],
        "descent": [
            "Arrival, landing performance and approach data prepared",
            "Approach and missed-approach briefing completed",
        ],
        "approach": [
            "Briefing confirmed and ECAM status checked",
            "Seat-belt signs on, minima and QNH set on both sides",
        ],
        "landing": [
            "Autothrust at speed or off as planned and autobrake as required",
            "ECAM landing memo reviewed with no blue items",
            "Landing gear down, signs on, cabin ready, spoilers armed and flaps set",
            "Cabin crew advised",
        ],
        "after_landing": [
            "Flaps retracted and spoilers disarmed",
            "Radar and predictive windshear off",
            "APU started as required",
        ],
        "shutdown": [
            "APU bleed on as required and engines off",
            "Seat-belt signs, fuel pumps and exterior lights off as appropriate",
            "Parking brake and chocks as required",
            "TCAS standby, ADIRS and oxygen off",
            "Emergency lights, batteries and APU secured as required",
            "Technical log completed",
        ],
    },
)


ADDON_PROFILES = {
    value["key"]: value
    for value in (FENIX_A320, PMDG_737, PMDG_777, BOEING_787, INIBUILDS_A350, FBW_A380X, A340_600)
}
