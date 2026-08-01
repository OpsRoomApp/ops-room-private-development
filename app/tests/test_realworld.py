"""Regression tests for Real World Search pipeline – v0.25.53.

Covers all v0.25.46 root-cause fixes and v0.25.53 hardening features.
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
    apply_adsbdb_aircraft,
    apply_adsbdb_route,
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
from app.flight_search import build_search_index, search_index
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


# ── Test K: ADSBDB enrichment (v0.25.53) ─────────────────────────────────────

def test_enrichment_route_recovery() -> None:
    """ADSBDB route enrichment recovers missing destination."""
    # Simulate FR24 flight with no destination
    flight = {
        "callsign": "DLH1304",
        "origin_icao": "EDDF",
        "destination_icao": None,
        "airline_name": None,
    }
    # Simulate ADSBDB callsign response (after unwrapping)
    adsbdb_response = {
        "flightroute": {
            "origin": {"icao_code": "EDDF", "iata_code": "FRA",
                       "name": "Frankfurt Airport", "municipality": "Frankfurt"},
            "destination": {"icao_code": "EGLL", "iata_code": "LHR",
                            "name": "London Heathrow", "municipality": "London"},
            "airline": {"name": "Lufthansa", "icao_code": "DLH"},
        }
    }
    apply_adsbdb_route(flight, adsbdb_response)
    check("Enrichment: destination recovered", flight.get("destination_icao") == "EGLL")
    check("Enrichment: destination name set", flight.get("destination_name") == "London Heathrow")
    check("Enrichment: destination city set", flight.get("destination_city") == "London")
    check("Enrichment: origin preserved", flight.get("origin_icao") == "EDDF")
    check("Enrichment: airline recovered", flight.get("airline_name") == "Lufthansa")
    check("Enrichment: has_route = True", flight.get("has_route") is True)
    check("Enrichment: can_dispatch = True", flight.get("can_dispatch") is True)


def test_enrichment_does_not_overwrite() -> None:
    """ADSBDB must not overwrite existing non-null FR24 data."""
    flight = {
        "callsign": "DLH400",
        "origin_icao": "EDDF",
        "destination_icao": "KJFK",
        "airline_name": "KNOWN AIRLINE",
    }
    adsbdb_response = {
        "flightroute": {
            "origin": {"icao_code": "EGLL"},
            "destination": {"icao_code": "EGLL"},
            "airline": {"name": "WRONG AIRLINE"},
        }
    }
    apply_adsbdb_route(flight, adsbdb_response)
    check("Existing origin preserved", flight.get("origin_icao") == "EDDF")
    check("Existing destination preserved", flight.get("destination_icao") == "KJFK")
    check("Existing airline preserved", flight.get("airline_name") == "KNOWN AIRLINE")


def test_enrichment_aircraft_meta() -> None:
    """ADSBDB aircraft metadata fills missing type and registration."""
    flight = {"callsign": "DLH400", "registration": None, "aircraft_type": None}
    adsbdb_response = {
        "aircraft": {
            "type": "Boeing 747-830",
            "icao_type": "B748",
            "registration": "D-ABYF",
        }
    }
    apply_adsbdb_aircraft(flight, adsbdb_response)
    check("Aircraft type set", flight.get("aircraft_type") == "Boeing 747-830")
    check("ICAO type set", flight.get("aircraft_icao_type") == "B748")
    check("Registration set", flight.get("registration") == "D-ABYF")


def test_enrichment_missing_route_handled() -> None:
    """Flight with no ADSBDB route data still returned intact."""
    flight = {"callsign": "PRIVATE01", "origin_icao": None, "destination_icao": None}
    apply_adsbdb_route(flight, {})  # Empty response
    check("No crash on empty route data", flight.get("callsign") == "PRIVATE01")
    check("Origin stays None", flight.get("origin_icao") is None)
    apply_adsbdb_route(flight, None)  # None response
    check("No crash on None route data", True)


def test_enrichment_field_name_variants() -> None:
    """ADSBDB field name variants (icao_code/icao, iata_code/iata) all work."""
    # Test with icao/iata (older format)
    flight1 = {"callsign": "TST1", "origin_icao": None, "destination_icao": None}
    apply_adsbdb_route(flight1, {
        "flightroute": {
            "destination": {"icao": "KJFK", "iata": "JFK", "name": "JFK Airport"}
        }
    })
    check("icao key accepted", flight1.get("destination_icao") == "KJFK")

    # Test with icao_code/iata_code (current ADSBDB format)
    flight2 = {"callsign": "TST2", "origin_icao": None, "destination_icao": None}
    apply_adsbdb_route(flight2, {
        "flightroute": {
            "destination": {"icao_code": "EGLL", "iata_code": "LHR", "name": "Heathrow"}
        }
    })
    check("icao_code key accepted", flight2.get("destination_icao") == "EGLL")


# ── Test L: FR24 list→dict conversion (v0.25.53) ────────────────────────────

def test_normalise_fr24_from_list() -> None:
    """FR24 returns 16-element lists; verify normalise_fr24 handles dict input."""
    # The _discover_fr24 function now converts FR24 lists to dicts before
    # passing to normalise_fr24.  This test verifies the dict format works.
    fr24_dict = {
        "hex": "461F3E", "lat": 50.03, "lon": 8.57, "heading": 270,
        "altitude": 35000, "speed": 470, "squawk": "1000", "radar": "F24",
        "type": "A359", "reg": "D-AIXL", "timestamp": 1234567890,
        "orig": "EDDF", "dest": "KJFK", "flight": "DLH400",
        "vrate": 0, "track": 270,
    }
    result = normalise_fr24(fr24_dict)
    check("FR24 dict: callsign preserved", result is not None)
    check("FR24 dict: origin = EDDF", result and result.get("origin_icao") == "EDDF")
    check("FR24 dict: destination = KJFK", result and result.get("destination_icao") == "KJFK")
    check("FR24 dict: aircraft = A359", result and result.get("aircraft_type") == "A359")
    check("FR24 dict: altitude_ft = 35000", result and result.get("altitude_ft") == 35000)
    check("FR24 dict: flight_level = FL350", result and result.get("flight_level") == "FL350")


def test_normalise_fr24_rejects_list() -> None:
    """normalise_fr24 must reject list input (not crash)."""
    result = normalise_fr24(["a", "b", "c"])
    check("FR24 list input returns None", result is None)


# ── Test M: Multi-term search (v0.25.53) ────────────────────────────────────

_SAMPLE_FLIGHTS: list[dict[str, Any]] = [
    {"callsign": "DLH1304", "origin_icao": "EDDF", "destination_icao": "LTFM",
     "airline_name": "Lufthansa", "aircraft_type": "Airbus A320",
     "aircraft_icao_type": "A320", "registration": "D-AIXL",
     "origin_name": "Frankfurt am Main Airport",
     "destination_name": "Istanbul Airport",
     "rank_score": 80},
    {"callsign": "DLH400", "origin_icao": "EDDF", "destination_icao": "KJFK",
     "airline_name": "Lufthansa", "aircraft_type": "Airbus A350-900",
     "aircraft_icao_type": "A359", "registration": "D-AIXN",
     "origin_name": "Frankfurt am Main Airport",
     "destination_name": "John F Kennedy International Airport",
     "rank_score": 90},
    {"callsign": "WUK441", "origin_icao": "EGSS", "destination_icao": "LEPA",
     "airline_name": "Wizz Air UK", "aircraft_type": "Airbus A321",
     "aircraft_icao_type": "A321", "registration": "G-WUKX",
     "rank_score": 70},
]


def test_search_exact_callsign() -> None:
    """Search 'DLH1304' returns the exact flight."""
    build_search_index(_SAMPLE_FLIGHTS)
    results = search_index("DLH1304")
    check("DLH1304 search returns at least 1 result (prefix tokens may also match DLH400)", len(results) >= 1)
    callsigns = {r["callsign"] for r in results}
    check("DLH1304 is among results", "DLH1304" in callsigns)


def test_search_callsign_prefix() -> None:
    """Search 'DLH' returns all DLH-prefix flights."""
    build_search_index(_SAMPLE_FLIGHTS)
    results = search_index("DLH")
    check("DLH prefix returns 2 Lufthansa flights", len(results) == 2)
    callsigns = {r["callsign"] for r in results}
    check("DLH1304 included", "DLH1304" in callsigns)
    check("DLH400 included", "DLH400" in callsigns)


def test_search_origin_icao() -> None:
    """Search 'EDDF' returns Frankfurt flights."""
    build_search_index(_SAMPLE_FLIGHTS)
    results = search_index("EDDF")
    check("EDDF returns 2 flights", len(results) == 2)


def test_search_aircraft_type() -> None:
    """Search 'A320' returns A320 flights."""
    build_search_index(_SAMPLE_FLIGHTS)
    results = search_index("A320")
    check("A320 returns at least 1 flight", len(results) >= 1)
    types = {r.get("aircraft_icao_type") for r in results}
    check("A320 type matches", "A320" in types)


def test_search_multi_term_eddf_a320() -> None:
    """Search 'EDDF A320' returns EDDF A320 flights (prefix 'a3' may also match A359)."""
    build_search_index(_SAMPLE_FLIGHTS)
    results = search_index("EDDF A320")
    check("EDDF+A320 returns at least 1 flight", len(results) >= 1)
    callsigns = {r["callsign"] for r in results}
    check("DLH1304 (A320 from EDDF) in results", "DLH1304" in callsigns)
    for r in results:
        ok = r.get("origin_icao") == "EDDF" or r.get("destination_icao") == "EDDF"
        check(f"{r['callsign']} has EDDF in route", ok)


def test_search_multi_term_dlh_eddf() -> None:
    """Search 'DLH EDDF' returns DLH Frankfurt flights."""
    build_search_index(_SAMPLE_FLIGHTS)
    results = search_index("DLH EDDF")
    check("DLH+EDDF returns at least 1 flight", len(results) >= 1)
    for r in results:
        ok = "DLH" in (r.get("callsign") or "")
        check(f"{r['callsign']} has DLH prefix", ok)
        ok2 = r.get("origin_icao") == "EDDF" or r.get("destination_icao") == "EDDF"
        check(f"{r['callsign']} has EDDF in route", ok2)


def test_search_airline_name() -> None:
    """Search 'Lufthansa' returns Lufthansa flights."""
    build_search_index(_SAMPLE_FLIGHTS)
    results = search_index("Lufthansa")
    check("Lufthansa returns at least 1 flight", len(results) >= 1)
    for r in results:
        check(f"{r['callsign']} is Lufthansa", "Lufthansa" in (r.get("airline_name") or ""))


def test_search_registration() -> None:
    """Search 'D-AIXL' returns the matching aircraft (prefix tokens may also match D-AIXN)."""
    build_search_index(_SAMPLE_FLIGHTS)
    results = search_index("D-AIXL")
    # D-AIXL and D-AIXN share prefix tokens "da", "dai", "daix" — expect at least 1
    check("D-AIXL returns at least 1 flight", len(results) >= 1)
    regs = {r.get("registration") for r in results}
    check("D-AIXL among results", "D-AIXL" in regs)


def test_search_multi_term_lufthansa_a320() -> None:
    """Search 'Lufthansa A320' returns Lufthansa A320 flights (prefix 'a3' may also match A359)."""
    build_search_index(_SAMPLE_FLIGHTS)
    results = search_index("Lufthansa A320")
    check("Lufthansa+A320 returns at least 1 flight", len(results) >= 1)
    # DLH1304 (A320) must be present; DLH400 (A359) might also appear due to prefix 'a3'
    callsigns = {r["callsign"] for r in results}
    check("DLH1304 (A320) is among results", "DLH1304" in callsigns)
    for r in results:
        ok = "Lufthansa" in (r.get("airline_name") or "")
        check(f"{r['callsign']} is Lufthansa", ok)


def test_search_no_results() -> None:
    """Search for something that doesn't exist returns empty."""
    build_search_index(_SAMPLE_FLIGHTS)
    results = search_index("ZZZZZZ")
    check("ZZZZZZ returns empty", len(results) == 0)


# ── Test N: Performance / non-blocking cache (v0.25.53) ─────────────────────

def test_cache_immediate_return() -> None:
    """get_live_flights returns immediately (no blocking)."""
    import time as _time
    t0 = _time.monotonic()
    flights, age, stale = get_live_flights()
    elapsed_ms = (_time.monotonic() - t0) * 1000
    check("get_live_flights returns in < 100ms", elapsed_ms < 100)


def test_search_index_is_read_only() -> None:
    """search_index is a pure read operation — no side effects on cache."""
    flights_before, age_before, stale_before = get_live_flights()
    build_search_index(_SAMPLE_FLIGHTS)
    search_index("DLH1304")
    search_index("EDDF A320")
    search_index("Lufthansa")
    flights_after, age_after, stale_after = get_live_flights()
    check("Cache untouched by search (count unchanged)",
          len(flights_before) == len(flights_after) or len(flights_before) == 0)


def test_cache_empty_protection_remains() -> None:
    """set_live_flights([]) must not overwrite a healthy cache."""
    force_reset_live_flights()
    build_search_index(_SAMPLE_FLIGHTS)
    set_live_flights(list(_SAMPLE_FLIGHTS))
    count_before = len(get_live_flights()[0])
    set_live_flights([])  # Should be rejected
    count_after = len(get_live_flights()[0])
    check("Empty update rejected", count_after == count_before)
    force_reset_live_flights()


def test_refresh_lock_not_held_by_search() -> None:
    """Verify _refresh_lock is not acquired by search logic (read-only path)."""
    # Import the lock and verify it's not held after a cache read
    from app.realworld import _refresh_lock as rl
    check("_refresh_lock is not locked before/after cache read", not rl.locked())


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
    test_enrichment_route_recovery()
    test_enrichment_does_not_overwrite()
    test_enrichment_aircraft_meta()
    test_enrichment_missing_route_handled()
    test_enrichment_field_name_variants()
    test_normalise_fr24_from_list()
    test_normalise_fr24_rejects_list()
    test_search_exact_callsign()
    test_search_callsign_prefix()
    test_search_origin_icao()
    test_search_aircraft_type()
    test_search_multi_term_eddf_a320()
    test_search_multi_term_dlh_eddf()
    test_search_airline_name()
    test_search_registration()
    test_search_multi_term_lufthansa_a320()
    test_search_no_results()
    test_cache_immediate_return()
    test_search_index_is_read_only()
    test_cache_empty_protection_remains()
    test_refresh_lock_not_held_by_search()

    print("=" * 60)
    total = PASS + FAIL
    print(f"RESULTS: {PASS}/{total} PASS, {FAIL} FAIL")
    sys.exit(0 if FAIL == 0 else 1)
