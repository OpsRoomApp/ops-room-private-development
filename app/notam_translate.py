"""
OPS ROOM -- NOTAM plain-English translation layer (v0.25.63).

Live FAA NMS data confirmed the API's ``notamTranslation`` field comes back
empty in real responses -- the raw ``text`` field is what we get, and it is
genuinely dense ICAO/FAA contraction prose:

    27 RWY END ID LGT U/S
    SECN OF TXL Z EAST OF ACFT STAND G10 CLSD

This module is a maintainable, rules-based expander over the standard ICAO
Doc 8400 contraction set -- explicitly NOT a full-NLP undertaking. It is
applied for display purposes only; the raw ``text`` always remains available.

Design notes:
  * Token-level, case-insensitive replacement (word-boundary safe).
  * Exact-match lookup -- no prefix guessing, so ``RWYS`` and ``RWY`` are
    separate entries and nothing inside a longer token is touched.
  * ``is_closure_notam`` is the shared conservative signal used by the
    Dispatch badges and the RAAS cross-reference (RWY/TWY + CLSD/CLOSED).
"""

from __future__ import annotations

import re
from typing import Any

# ICAO Doc 8400 / FAA contraction -> plain English. Ambiguous contractions
# (CLR, LT, INT ...) are deliberately omitted rather than guessed wrong.
_CONTRACTIONS: dict[str, str] = {
    "RWYS": "Runways",
    "TWYS": "Taxiways",
    "UNAVBL": "Unavailable",
    "NOTAM": "Notice to Air Missions",
    "SIGMET": "Significant Meteorological Information",
    "HIRL": "High Intensity Runway Lights",
    "ACFT": "Aircraft",
    "AMSL": "Above Mean Sea Level",
    "OBSTN": "Obstruction",
    "AVGAS": "Aviation Gasoline",
    "AVBL": "Available",
    "CLSD": "Closed",
    "DLY": "Daily",
    "EMERG": "Emergency",
    "EST": "Estimated",
    "H24": "Continuous (24 hours)",
    "HDG": "Heading",
    "HLDG": "Holding",
    "LGTD": "Lighted",
    "LNDG": "Landing",
    "OBSC": "Obscured",
    "OBST": "Obstacle",
    "OCNL": "Occasional",
    "OPR": "Operator",
    "OPS": "Operations",
    "PAX": "Passengers",
    "PERM": "Permanent",
    "PSN": "Position",
    "RWY": "Runway",
    "SECN": "Section",
    "SKED": "Scheduled",
    "TWY": "Taxiway",
    "U/S": "Unserviceable",
    "UNL": "Unlimited",
    "WIP": "Work In Progress",
    "AGL": "Above Ground Level",
    "APCH": "Approach",
    "APN": "Apron",
    "ARR": "Arrival",
    "ATIS": "Automatic Terminal Information Service",
    "BDRY": "Boundary",
    "BFR": "Before",
    "BLDG": "Building",
    "BRG": "Bearing",
    "BTN": "Between",
    "CLR": "Clearance",
    "CNL": "Cancelled",
    "COM": "Communication",
    "CTA": "Control Area",
    "CTR": "Control Zone",
    "DEP": "Departure",
    "DH": "Decision Height",
    "DME": "Distance Measuring Equipment",
    "ELEV": "Elevation",
    "ENG": "Engine",
    "FL": "Flight Level",
    "FM": "From",
    "FREQ": "Frequency",
    "FT": "Feet",
    "GND": "Ground",
    "IFR": "Instrument Flight Rules",
    "ILS": "Instrument Landing System",
    "IMC": "Instrument Meteorological Conditions",
    "INBD": "Inbound",
    "LGT": "Light",
    "LGTS": "Lights",
    "LNAV": "Lateral Navigation",
    "LOC": "Localizer",
    "LDA": "Landing Distance Available",
    "MNT": "Maintain",
    "MKR": "Marker",
    "MLG": "Main Landing Gear",
    "MSG": "Message",
    "NGT": "Night",
    "NML": "Normal",
    "OVC": "Overcast",
    "PWR": "Power",
    "RCL": "Runway Centerline",
    "RVR": "Runway Visual Range",
    "SFC": "Surface",
    "TODA": "Takeoff Distance Available",
    "TORA": "Takeoff Run Available",
    "TWR": "Tower",
    "TXL": "Taxiway Link",
    "UNREL": "Unreliable",
    "VFR": "Visual Flight Rules",
    "VIS": "Visibility",
    "VMC": "Visual Meteorological Conditions",
    "VOR": "VHF Omnidirectional Range",
    "WDI": "Wind Direction Indicator",
    "WEF": "With Effect From",
    "WI": "Within",
    "WID": "Wide",
    "WX": "Weather",
    "ABV": "Above",
    "ADJ": "Adjacent",
    "AFIS": "Aerodrome Flight Information Service",
    "FMS": "Flight Management System",
}

_TOKEN_RE = re.compile(r"[A-Za-z]+(?:/[A-Za-z]+)*")


def expand(text: Any) -> str:
    """Return the NOTAM text with known contractions expanded to plain
    English. Unknown tokens (runway idents, frequencies, time windows) are
    passed through untouched."""
    if not text:
        return ""
    raw = str(text)
    if len(raw) > 20000:  # never expand an absurdly large blob
        return raw

    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        return _CONTRACTIONS.get(token.upper(), token)

    return _TOKEN_RE.sub(_replace, raw)


def expand_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of a NOTAM row with ``translated_text`` added
    (only when it differs from the raw text)."""
    out = dict(row)
    raw = str(row.get("text") or "")
    translated = expand(raw)
    if translated.strip() != raw.strip():
        out["translated_text"] = translated
    return out


def is_closure_notam(text: Any) -> bool:
    """Conservative closure signal: a runway/taxiway reference combined with a
    closed/unserviceable marker. Used by Dispatch badges and the RAAS
    cross-reference -- it can only ADD warnings, never remove one."""
    upper = str(text or "").upper()
    closed = any(word in upper for word in ("CLSD", "CLOSED", "U/S"))
    surface = bool(re.search(r"\b(RWY|TWY|RWS)\b", upper))
    return closed and surface
