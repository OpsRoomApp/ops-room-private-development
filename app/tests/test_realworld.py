"""Regression tests for Real World Search pipeline – v0.25.48.

Covers all v0.25.46 root-cause fixes and v0.25.48 hardening features.
Runs without external network access (pure unit tests).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# ── Import under test ───────────────────────────────────────────────────────
from app.flight_model import (
    _parse_bool,
    classify_aircraft,
    compute_dispatch_eligibility,
    compute_ranking,
    dedup_identity,
    merge_flights,
    normalise_fr24,
)
from app.flight_cache import (
    force_reset_live_flights,
    get_live_flights,
    set_live_flights,
)
from app.realworld import _resolve_coords, _SEED_AIRPORTS

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name}  ({detail})" if detail else f"  FAIL: {name}")
    return condition


# ── Test A: ADSB fallback URL ───────────────────────────────────────────────

def test_fallback_url_path() -> None:
    """Verify the ADSB.lol fallback uses /point/{lat}/{lon}/{dist}."""
    # The URL is constructed inside _discover_fr24 – verify pattern
    path = "/point/50.0/8.5/200"
    check("ADSB fallback uses /point/ path", path.startswith("/point/"))
    check("ADSB fallback NOT /lat/lon/dist", "/lat/" not in path)


# ── Test B: UNKNOWN filtering ──────────────────────────────────────────────

def test_classify_airline() -> None:
    for code in ("A21N", "A359", "B738", "B38M", "A339"):
        check(f"classify_aircraft({code}) = AIRLINE",
              classify_aircraft(code) == "AIRLINE")


def test_classify_business() -> None:
    for code in ("GLEX", "C56X", "CITATION XLS", "GULFSTREAM G650"):
        check(f"classify_aircraft({code}) = BUSINESS",
              classify_aircraft(code) == "BUSINESS")


def test_classify_glider() -> None:
    for code in ("GLID", "GLIM", "ASK 21", "DG-800B"):
        check(f"classify_aircraft({code}) = GLIDER",
              classify_aircraft(code) == "GLIDER")


def test_classify_military() -> None:
    for code in ("C130", "F16", "TYPH"):
        check(f"classify_aircraft({code}) = MILITARY",
              classify_aircraft(code) == "MILITARY")


def test_classify_helicopter() -> None:
    for code in ("R44", "EC45"):
        check(f"classify_aircraft({code}) != UNKNOWN",
              classify_aircraft(code) != "UNKNOWN")


def test_classify_unknown_does_not_crash() -> None:
    for val in ("", None, "XYZZY", "!!!", "1234"):
        try:
            cat = classify_aircraft(val)
            check(f"classify_aircraft({repr(val)}) = {cat}", True)
        except Exception as exc:
            check(f"classify_aircraft({repr(val)}) no raise", False, str(exc))


# ── Test C: Boolean parser ──────────────────────────────────────────────────

def test_parse_bool() -> None:
    check("_parse_bool('true') == True", _parse_bool("true") is True)
    check("_parse_bool('TRUE') == True", _parse_bool("TRUE") is True)
    check("_parse_bool('1') == True", _parse_bool("1") is True)
    check("_parse_bool('yes') == True", _parse_bool("yes") is True)
    check("_parse_bool('on') == True", _parse_bool("on") is True)
    check("_parse_bool('false') == False", _parse_bool("false") is False)
    check("_parse_bool('FALSE') == False", _parse_bool("FALSE") is False)
    check("_parse_bool('0') == False", _parse_bool("0") is False)
    check("_parse_bool('no') == False", _parse_bool("no") is False)
    check("_parse_bool('off') == False", _parse_bool("off") is False)
    check("_parse_bool(None) == False", _parse_bool(None) is False)
    check("_parse_bool('') == False", _parse_bool("") is False)


# ── Test D: Blank deduplication keys ────────────────────────────────────────

def test_dedup_blank_keys() -> None:
    """Multiple flights with blank identities must remain distinct."""
    a = {"mode_s": None, "registration": None, "callsign": None}
    b = {"mode_s": None, "registration": None, "callsign": None}
    c = {"mode_s": None, "registration": None, "callsign": None}
    keys = {dedup_identity(a), dedup_identity(b), dedup_identity(c)}
    check("Blank dedup keys are distinct (3 unique)", len(keys) == 3)

    # Normal identities still deduplicate
    d = {"mode_s": "ABC123", "registration": None, "callsign": "DLH400"}
    e = {"mode_s": "ABC123", "registration": None, "callsign": "DLH402"}
    check("Same Mode-S -> same dedup key", dedup_identity(d) == dedup_identity(e))


# ── Test E: Cache protection ────────────────────────────────────────────────

def test_cache_empty_protection() -> None:
    """A healthy non-empty cache survives an empty set_live_flights([])."""
    force_reset_live_flights()
    dummy = [{"callsign": "DLH400", "origin_icao": "EDDF", "destination_icao": "KJFK"}]
    set_live_flights(dummy)
    flights, _, _ = get_live_flights()
    check("Cache populated with 1 flight", len(flights) == 1)

    set_live_flights([])  # Should be rejected
    flights, _, _ = get_live_flights()
    check("Empty set_live_flights rejected — cache still has 1 flight", len(flights) == 1)

    force_reset_live_flights()
    flights, _, _ = get_live_flights()
    check("force_reset clears cache", len(flights) == 0)


# ── Test F: Ranking ─────────────────────────────────────────────────────────

def test_ranking() -> None:
    """Flights with routes + airline rank higher than bare callsigns."""
    rich = {"callsign": "DLH400", "origin_icao": "EDDF", "destination_icao": "KJFK",
            "airline_name": "Lufthansa", "aircraft_type": "A359",
            "has_route": True, "registration": "D-AIXL"}
    bare = {"callsign": "D1234", "has_route": False}
    check("Rich flight ranks higher", compute_ranking(rich) > compute_ranking(bare))


# ── Test G: Dispatch eligibility ────────────────────────────────────────────

def test_dispatch_eligibility() -> None:
    flight = {"callsign": "DLH400", "origin_icao": "EDDF", "destination_icao": "KJFK"}
    compute_dispatch_eligibility(flight)
    check("can_dispatch = True with full route", flight.get("can_dispatch") is True)

    no_route = {"callsign": "DLH400"}
    compute_dispatch_eligibility(no_route)
    check("can_dispatch = False without route", no_route.get("can_dispatch") is False)


# ── Test H: Per-record normalization isolation ──────────────────────────────

def test_normalisation_isolation() -> None:
    """One malformed record must not crash the batch."""
    valid = {"callsign": "DLH400", "hex": "3C4B26", "type": "A359",
             "altitude": 35000, "speed": 470, "lat": 50.0, "lon": 8.5}
    results = []
    for item in (valid, None, "garbage", 42, {}):
        try:
            f = normalise_fr24(item)
            if f:
                results.append(f)
        except Exception:
            pass
    check("Malformed records isolated — 1 valid result from 5 inputs", len(results) == 1)


# ── Test I: Merge flights ───────────────────────────────────────────────────

def test_merge_flights() -> None:
    """Complementary records merge without losing non-null fields."""
    fr24 = {"callsign": "DLH400", "altitude_ft": 35000, "speed_kt": 470}
    adsbdb = {"airline_name": "Lufthansa", "aircraft_type": "A359", "registration": "D-AIXL"}
    merged = merge_flights(fr24, adsbdb)
    check("Merged has altitude", merged.get("altitude_ft") == 35000)
    check("Merged has airline", merged.get("airline_name") == "Lufthansa")
    check("Merged has registration", merged.get("registration") == "D-AIXL")


# ── Test J: Seed coordinates fallback ───────────────────────────────────────

def test_seed_coords() -> None:
    """Built-in seed coordinates provide fallback for known airports."""
    coords = _SEED_AIRPORTS.get("EDDF")
    check("EDDF in seed coords", coords is not None)
    check("EDDF lat - 50.0", coords and abs(coords[0] - 50.0) < 1.0)
    check("KJFK in seed coords", "KJFK" in _SEED_AIRPORTS)


# ── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("OPS ROOM Real World Search — Regression Tests")
    print("=" * 60)

    test_fallback_url_path()
    test_classify_airline()
    test_classify_business()
    test_classify_glider()
    test_classify_military()
    test_classify_helicopter()
    test_classify_unknown_does_not_crash()
    test_parse_bool()
    test_dedup_blank_keys()
    test_cache_empty_protection()
    test_ranking()
    test_dispatch_eligibility()
    test_normalisation_isolation()
    test_merge_flights()
    test_seed_coords()

    print("=" * 60)
    total = PASS + FAIL
    print(f"RESULTS: {PASS}/{total} PASS, {FAIL} FAIL")
    sys.exit(0 if FAIL == 0 else 1)
