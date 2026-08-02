"""Real-world flight data model – v0.25.58.

Normalisation, classification, ranking, deduplication, and dispatch/Simbrief
eligibility helpers for the Real World Search pipeline.
"""

from __future__ import annotations

import logging
import re
from typing import Any

_log = logging.getLogger("opsroom.realworld.model")

# ── Field schema ────────────────────────────────────────────────────────────

FLIGHT_FIELDS: tuple[str, ...] = (
    "callsign", "callsign_icao", "callsign_iata",
    "airline_name", "airline_icao", "airline_iata", "airline_callsign",
    "aircraft_type", "aircraft_icao_type", "aircraft_manufacturer",
    "registration", "mode_s",
    "origin_icao", "origin_iata", "origin_name", "origin_city", "origin_country",
    "destination_icao", "destination_iata", "destination_name",
    "destination_city", "destination_country",
    "latitude", "longitude", "altitude_ft", "flight_level",
    "ground_speed", "speed_kt", "heading", "vertical_rate",
    "status", "category",
    "last_seen", "eobt_utc", "eobt",
    "tracking_source", "identity_source", "route_source", "enrichment_source",
    "has_route", "can_dispatch", "can_simbrief",
    "simbrief_url", "simbrief_available",
    "rank_score",
)

# ── Aircraft classification ─────────────────────────────────────────────────

# Recognised ICAO type-code prefixes / patterns → category
_AIRLINE_PREFIXES: tuple[str, ...] = (
    "A",  # Airbus family: A20N, A21N, A319, A332, A346, A359, A388 ...
    "B",  # Boeing family: B38M, B739, B748, B77W, B788 ...
    "E",  # Embraer E-Jets: E170, E190, E195 ...
    "C",  # C-Series / Airbus A220: CRJ family handled separately below
    "RJ",  # Regional jets
)
_CARGO_PREFIXES: tuple[str, ...] = ("B74", "B75", "B76", "B77", "MD1", "DC1", "AN1")
_BUSINESS_PATTERNS: tuple[str, ...] = (
    "CITATION", "GULFSTREAM", "FALCON", "GLEX", "GLF", "C56X", "C68A",
    "C525", "C550", "C560", "C680", "C700", "C750",
    "FA7X", "FA8X", "E55P", "H25B", "LJ35", "LJ45", "LJ60",
    "PC12", "PC24", "P180", "PRM1", "SF50", "TBM",
)
_GLIDER_PATTERNS: tuple[str, ...] = (
    "GLID", "GLIM", "ASK", "DG-", "DG8", "LS4", "LS8", "VENTUS",
    "DUODISCUS", "NIMBUS", "K21", "K8", "K13", "JANUS", "ARCUS", "DISCUS",
    "SF25", "SF28", "STEM", "TWIN", "PZL",
)
_MILITARY_PATTERNS: tuple[str, ...] = (
    "C130", "C17 ", "C5 ", "C5M", "KC13", "KC46", "E3 ", "E7 ", "E8 ",
    "F15", "F16", "F18", "F22", "F35", "SU", "MIG", "TYPH",
    "HARRIER", "TORNADO", "A10", "B1", "B2", "B52", "H60",
    "H47", "H53", "V22", "P3", "P8", "C160", "C27", "C295",
    "A400", "CN23", "U28", "TEX2", "T6", "T38", "HAWK",
)
_HELICOPTER_PATTERNS: tuple[str, ...] = (
    "R22", "R44", "R66", "EC1", "EC2", "EC3", "EC4", "EC5",
    "B06", "B20", "B40", "BK1", "H12", "H13", "H14", "H15",
    "A10", "AS3", "AS5", "SA3", "S76", "S92", "AW1", "AW3",
    "ENST", "HU26", "MD52", "MD90", "NH90",
)


def classify_aircraft(type_str: str | None, callsign: str | None = None) -> str:
    """Classify an aircraft into a stable category.

    Returns one of:
        AIRLINE, BUSINESS, CARGO, GLIDER, GENERAL_AVIATION,
        MILITARY, HELICOPTER, UNKNOWN

    Never raises – malformed / missing input → UNKNOWN.
    """
    t = str(type_str or "").strip().upper()
    if not t:
        return "UNKNOWN"

    # ── Gliders (explicit designators) ──
    if any(p in t for p in _GLIDER_PATTERNS):
        return "GLIDER"

    # ── Business / private jets (check before military to avoid false C5/C17 matches) ──
    if any(p in t for p in _BUSINESS_PATTERNS):
        return "BUSINESS"

    # ── Military patterns ──
    if any(t.startswith(p) for p in _MILITARY_PATTERNS):
        return "MILITARY"

    # ── Helicopters ──
    if any(t.startswith(p) for p in _HELICOPTER_PATTERNS):
        return "HELICOPTER"

    # ── Cargo variants (B748, B77F etc.) ──
    if t.endswith("F") or t.endswith("8F"):
        # Boeing freighters: B74x, B75x, B76x, B77x → check prefix
        if any(t.startswith(p) for p in _CARGO_PREFIXES):
            return "CARGO"

    # ── Airlines ──
    # Most 3-4 char ICAO type codes starting with A/B/E (e.g. A21N, B38M, A359, B748)
    if len(t) == 4 and t.isalnum():
        if any(t.startswith(p) for p in _AIRLINE_PREFIXES):
            return "AIRLINE"

    # ── Additional heuristics ──
    # "BOEING 737-800" etc.
    if "BOEING" in t or "AIRBUS" in t or "EMBRAER" in t or "BOMBARDIER" in t:
        return "AIRLINE"

    # Generic / visual flight rules aircraft
    if any(w in t for w in ("C172", "C152", "C182", "PA28", "PA44", "DA40", "DA42",
                             "SR20", "SR22", "DV20", "DR40", "P28", "AA5",
                             "C150", "C210", "BE3", "BE5", "BE7", "BE9",
                             "P68", "BN2", "DHC6", "AN2")):
        return "GENERAL_AVIATION"

    # Glider / motorglider heuristics
    if any(w in t for w in ("GLIDER", "GLID", "MOTORGLIDER", "SAILPLANE")):
        return "GLIDER"

    return "UNKNOWN"


# ── Ranking ─────────────────────────────────────────────────────────────────

def compute_ranking(flight: dict[str, Any]) -> int:
    """Assign a rank score.  Higher = more operationally relevant."""
    score = 0
    if flight.get("has_route") or (flight.get("origin_icao") and flight.get("destination_icao")):
        score += 40
    if flight.get("airline_name"):
        score += 30
    if flight.get("aircraft_type"):
        score += 15
    if flight.get("registration"):
        score += 10
    if flight.get("altitude_ft") and float(flight.get("altitude_ft") or 0) > 0:
        score += 5
    return score


# ── Dispatch / SimBrief eligibility ─────────────────────────────────────────

def compute_dispatch_eligibility(flight: dict[str, Any]) -> None:
    """Set can_dispatch and can_simbrief boolean flags in-place."""
    flight["can_dispatch"] = bool(
        flight.get("origin_icao")
        and flight.get("destination_icao")
        and flight.get("callsign")
    )
    flight["can_simbrief"] = bool(
        flight.get("origin_icao")
        and flight.get("destination_icao")
        and flight.get("callsign")
    )


# ── SimBrief URL builder ────────────────────────────────────────────────────

def build_simbrief_url(flight: dict[str, Any]) -> str | None:
    """Build a dispatch.simbrief.com/options/custom URL, or None."""
    callsign = str(flight.get("callsign") or "").strip()
    if not callsign:
        return None
    params: dict[str, str] = {}

    # Parse callsign into airline prefix + flight number
    m = re.match(r"^([A-Z]{2,3})([0-9A-Z]+)$", callsign)
    if m:
        params["airline"] = m.group(1)
        params["fltnum"] = m.group(2)
        params["callsign"] = callsign
    else:
        params["callsign"] = callsign

    orig = str(flight.get("origin_icao") or "").strip()
    dest = str(flight.get("destination_icao") or "").strip()
    if orig:
        params["orig"] = orig
    if dest:
        params["dest"] = dest

    actype = str(flight.get("aircraft_icao_type") or flight.get("aircraft_type") or "").strip()
    if actype and len(actype) <= 4:
        params["basetype"] = actype

    if not params:
        return None
    return "https://dispatch.simbrief.com/options/custom?" + "&".join(
        f"{k}={v}" for k, v in params.items()
    )


def compute_simbrief(flight: dict[str, Any]) -> None:
    """Set simbrief_url and simbrief_available flags in-place."""
    url = build_simbrief_url(flight)
    flight["simbrief_url"] = url
    flight["simbrief_available"] = bool(url)
    if not url:
        flight["can_simbrief"] = False


# ── Normalisation helpers ───────────────────────────────────────────────────

def _safe_float(val: Any) -> float | None:
    try:
        v = float(val)
        return v if v == v else None  # NaN → None
    except (TypeError, ValueError):
        return None


def normalise_fr24(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a raw FR24 dict into the canonical flight model.  Returns None on
    completely unusable input."""
    if not isinstance(raw, dict):
        return None
    cs = str(raw.get("callsign") or raw.get("flight") or "").strip()
    if not cs:
        return None
    alt = _safe_float(raw.get("altitude") or raw.get("alt"))
    flight: dict[str, Any] = {
        "callsign": cs.upper(),
        "mode_s": str(raw.get("hex") or raw.get("icao24") or "").upper().strip() or None,
        "registration": str(raw.get("reg") or raw.get("registration") or "").strip() or None,
        "aircraft_type": str(raw.get("type") or raw.get("aircraft") or "").strip() or None,
        "altitude_ft": int(alt) if alt is not None else None,
        "speed_kt": _safe_float(raw.get("speed") or raw.get("gspeed")),
        "heading": _safe_float(raw.get("heading") or raw.get("track")),
        "latitude": _safe_float(raw.get("lat") or raw.get("latitude")),
        "longitude": _safe_float(raw.get("lon") or raw.get("longitude")),
        "vertical_rate": _safe_float(raw.get("vrate") or raw.get("vr")),
        "status": str(raw.get("status") or "").strip() or None,
        "tracking_source": "FR24",
        "airline_name": str(raw.get("airline") or "").strip() or None,
        "origin_icao": str(raw.get("orig") or raw.get("from") or "").strip().upper() or None,
        "destination_icao": str(raw.get("dest") or raw.get("to") or "").strip().upper() or None,
    }
    # Clean empty strings to None
    for k in ("origin_icao", "destination_icao", "airline_name", "aircraft_type",
              "registration", "mode_s", "status"):
        if flight.get(k) == "":
            flight[k] = None
    if flight.get("altitude_ft") is not None and flight["altitude_ft"] > 0:
        flight["flight_level"] = f"FL{int(flight['altitude_ft'] // 100)}"
    flight["has_route"] = bool(flight.get("origin_icao") and flight.get("destination_icao"))
    flight.setdefault("category", classify_aircraft(flight.get("aircraft_type"), flight.get("callsign")))
    flight.setdefault("rank_score", compute_ranking(flight))
    compute_dispatch_eligibility(flight)
    compute_simbrief(flight)
    return flight


def normalise_adsb(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a raw ADSB.lol/fi dict into the canonical model."""
    if not isinstance(raw, dict):
        return None
    cs = str(raw.get("flight") or raw.get("callsign") or "").strip()
    if not cs and not raw.get("hex"):
        return None
    alt = _safe_float(raw.get("alt_baro") or raw.get("alt_geom") or raw.get("altitude"))
    flight: dict[str, Any] = {
        "callsign": cs.upper() if cs else None,
        "mode_s": str(raw.get("hex") or raw.get("icao24") or "").upper().strip() or None,
        "registration": str(raw.get("r") or raw.get("registration") or "").strip() or None,
        "aircraft_type": str(raw.get("t") or raw.get("type") or "").strip() or None,
        "altitude_ft": int(alt) if alt is not None else None,
        "speed_kt": _safe_float(raw.get("gs") or raw.get("speed")),
        "heading": _safe_float(raw.get("track") or raw.get("heading")),
        "latitude": _safe_float(raw.get("lat") or raw.get("latitude")),
        "longitude": _safe_float(raw.get("lon") or raw.get("longitude")),
        "vertical_rate": _safe_float(raw.get("baro_rate") or raw.get("geom_rate")),
        "status": None,
        "tracking_source": "ADSB",
    }
    for k in ("origin_icao", "destination_icao", "airline_name", "aircraft_type",
              "registration", "mode_s", "status"):
        if flight.get(k) == "":
            flight[k] = None
    if flight.get("altitude_ft") is not None and flight["altitude_ft"] > 0:
        flight["flight_level"] = f"FL{int(flight['altitude_ft'] // 100)}"
    flight["has_route"] = False
    flight.setdefault("category", classify_aircraft(flight.get("aircraft_type"), flight.get("callsign")))
    flight.setdefault("rank_score", compute_ranking(flight))
    compute_dispatch_eligibility(flight)
    compute_simbrief(flight)
    return flight


# ── ADSBDB data application ─────────────────────────────────────────────────

def apply_adsbdb_aircraft(flight: dict[str, Any], ac_data: dict[str, Any]) -> None:
    """Enrich a flight record with ADSBDB aircraft / registration metadata."""
    if not ac_data or not isinstance(ac_data, dict):
        return
    # ADSBDB wraps aircraft data under "aircraft" key after unwrapping
    a = ac_data.get("aircraft") or ac_data
    for src_key, dst_key in (
        ("type", "aircraft_type"),
        ("icao_type", "aircraft_icao_type"),
        ("manufacturer", "aircraft_manufacturer"),
        ("registration", "registration"),
        ("registered_owner", None),
    ):
        val = str(a.get(src_key) or "").strip()
        if val and dst_key and not flight.get(dst_key):
            flight[dst_key] = val
    # Identity source
    if not flight.get("identity_source"):
        flight["identity_source"] = "ADSBDB"
    # Backfill aircraft_type from icao_type if we got it
    if not flight.get("aircraft_type"):
        flight["aircraft_type"] = flight.get("aircraft_icao_type")
    if flight.get("aircraft_type") and not flight.get("category"):
        flight["category"] = classify_aircraft(flight["aircraft_type"], flight.get("callsign"))


def apply_adsbdb_route(flight: dict[str, Any], route_data: dict[str, Any]) -> None:
    """Enrich a flight record with ADSBDB route / callsign origin-destination data.

    Handles both ADSBDB response formats:
      - Callsign endpoint: {"flightroute": {"origin": {...}, "destination": {...}, ...}}
      - Already-unwrapped data with "route" key
      - Flat origin/destination string fields
    """
    if not route_data or not isinstance(route_data, dict):
        return

    # ADSBDB callsign endpoint returns data under "flightroute"; also try "route"
    r = route_data.get("flightroute") or route_data.get("route") or route_data
    if not isinstance(r, dict):
        return

    # Helper to get airport field across both naming conventions
    def _a_val(apt: dict, *keys: str) -> str:
        for k in keys:
            v = str(apt.get(k) or "").strip()
            if v:
                return v
        return ""

    for src_key in ("origin", "destination"):
        airport = r.get(src_key)
        if isinstance(airport, dict):
            icao = _a_val(airport, "icao_code", "icao")
            iata = _a_val(airport, "iata_code", "iata")
            name = _a_val(airport, "name")
            city = _a_val(airport, "municipality")
            country = _a_val(airport, "country_name", "country")

            # Use explicit assignment (not setdefault) because normalise_fr24
            # sets these keys to None, and setdefault won't overwrite None.
            if icao and not flight.get(f"{src_key}_icao"):
                flight[f"{src_key}_icao"] = icao
            if iata and not flight.get(f"{src_key}_iata"):
                flight[f"{src_key}_iata"] = iata
            if name and not flight.get(f"{src_key}_name"):
                flight[f"{src_key}_name"] = name
            if city and not flight.get(f"{src_key}_city"):
                flight[f"{src_key}_city"] = city
            if country and not flight.get(f"{src_key}_country"):
                flight[f"{src_key}_country"] = country
        elif isinstance(airport, str) and airport.strip():
            if not flight.get(f"{src_key}_icao"):
                flight[f"{src_key}_icao"] = airport.strip().upper()

    # Airline metadata
    airline = r.get("airline")
    if isinstance(airline, dict):
        for src_k, dst_k in (
            ("name", "airline_name"),
            ("icao_code", "airline_icao"),
            ("iata_code", "airline_iata"),
            ("icao", "airline_icao"),  # fallback
            ("iata", "airline_iata"),  # fallback
            ("callsign", "airline_callsign"),
        ):
            val = str(airline.get(src_k) or "").strip()
            if val and not flight.get(dst_k):
                flight[dst_k] = val

    # Route source
    if not flight.get("route_source"):
        flight["route_source"] = "ADSBDB"

    # Recompute derived fields
    flight["has_route"] = bool(flight.get("origin_icao") and flight.get("destination_icao"))
    compute_dispatch_eligibility(flight)
    compute_simbrief(flight)


# ── Boolean parser ──────────────────────────────────────────────────────────

def _parse_bool(val: str | None) -> bool:
    """Safely parse boolean strings.  'false', '0', 'no', 'off' → False."""
    v = str(val or "").strip().lower()
    if v in ("true", "1", "yes", "on"):
        return True
    return False


# ── Deduplication ───────────────────────────────────────────────────────────

DEDUP_PREFER_FIRST = "first"

_anon_counter: int = 0


def _anon_key() -> str:
    global _anon_counter
    _anon_counter += 1
    return f"__anon__{_anon_counter}"


def dedup_identity(flight: dict[str, Any]) -> str:
    """Return a stable deduplication key for a flight.

    Priority: mode_s → registration → callsign → anonymous unique key.
    Never returns an empty string.
    """
    mode_s = str(flight.get("mode_s") or "").strip().upper()
    if mode_s:
        return f"ms:{mode_s}"
    reg = str(flight.get("registration") or "").strip().upper().replace("-", "").replace(" ", "")
    if reg:
        return f"reg:{reg}"
    cs = str(flight.get("callsign") or "").strip().upper().replace(" ", "")
    if cs:
        return f"cs:{cs}"
    return _anon_key()


# ── Field-level merge ───────────────────────────────────────────────────────

def merge_flights(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    """Merge two flight records, preferring non-null values from primary,
    backfilling from secondary for missing fields."""
    merged = dict(secondary)
    for k, v in primary.items():
        if v is not None and v != "":
            merged[k] = v
    return merged
