from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any

@dataclass(frozen=True)
class AircraftAdapter:
    key: str
    label: str
    target_write: bool
    ap1_toggle: bool = True
    autothrottle_toggle: bool = True
    ap2_toggle: bool = False
    note: str = ""

# OPS ROOM does not guess unpublished L-vars. Add-on adapters stay read-only
# until the vendor publishes a stable interface or a dedicated WASM bridge is
# implemented and tested against that aircraft.
PROFILES = (
    (("INIBUILDS", "A350", "A300", "A310", "A320NEO V2"), AircraftAdapter("inibuilds", "INIBUILDS / READ ONLY TARGETS", False, note="FCU target writes require a verified iniBuilds adapter.")),
    (("FENIX", "FNX"), AircraftAdapter("fenix", "FENIX / READ ONLY TARGETS", False, note="Fenix FCU target writes require a verified aircraft interface.")),
    (("PMDG", "B77", "B73"), AircraftAdapter("pmdg", "PMDG / READ ONLY TARGETS", False, note="PMDG target control requires the matching PMDG SDK adapter.")),
    (("FSLABS", "FLIGHT SIM LABS"), AircraftAdapter("fslabs", "FSLABS / READ ONLY TARGETS", False, note="FSLabs target control requires a verified aircraft interface.")),
    (("AEROSOFT", "AEROSOFT A"), AircraftAdapter("aerosoft", "AEROSOFT / READ ONLY TARGETS", False, note="Aerosoft target control requires a verified aircraft interface.")),
    (("FLYBYWIRE", "A32NX", "A380X"), AircraftAdapter("flybywire", "FLYBYWIRE / READ ONLY TARGETS", False, note="FlyByWire L-vars need a WASM/Gauge API bridge, not plain SimConnect.")),
)
GENERIC = AircraftAdapter("generic", "GENERIC SIMCONNECT", True, note="Standard MSFS target events are available for compatible aircraft.")

def detect_adapter(aircraft: dict[str, Any] | None) -> dict[str, Any]:
    aircraft = aircraft or {}
    haystack = " ".join(str(aircraft.get(k) or "") for k in ("title", "model", "type")).upper()
    for needles, profile in PROFILES:
        if any(needle in haystack for needle in needles):
            return asdict(profile)
    return asdict(GENERIC)
