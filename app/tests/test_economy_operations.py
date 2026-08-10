"""Regression tests for operation-aware Finance & Career estimation -- v0.25.65.

Runs without external network access and never touches the real career file
(a career dict is passed in; finance_enabled is stubbed).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import app.economy as economy

PASS = 0
FAIL = 0

CAREER = {
    "currency": "EUR",
    "progression_pace": "standard",
    "fare_settings": {"auto": True},
    "airline_balance": 250000.0,
    "pilot_balance": 50000.0,
    "totals": {},
    "ledger": [],
}


def check(name: str, condition: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if condition:
        PASS += 1
        return True
    FAIL += 1
    print(f"  FAIL {name}" + (f" -- {detail}" if detail else ""))
    return False


def _meta(flight_extra=None, **root):
    flight = {"origin": "EDDF", "destination": "EGLL", "distance_nm": 400, "aircraft_icao": "A320"}
    if isinstance(flight_extra, dict):
        flight.update(flight_extra)
    meta = {"flight": flight, "durations": {"block_seconds": 3600}, "debrief": {"score": 80}}
    meta.update(root)
    return meta


def _estimate(**kw):
    return economy.estimate_statement(_meta(**kw), CAREER)


def setup() -> None:
    economy.finance_enabled = lambda: True


def test_passenger_with_bags_only_no_freight_revenue():
    s = _estimate(flight_extra={"passengers": 110, "cargo": 1650, "weight_units": "KGS"})
    check("passenger op resolved", s["operation"]["resolved"] == "passenger")
    check("bags do not generate freight revenue", s["commercial_freight_revenue"] == 0)
    check("passenger revenue present", s["passenger_revenue_before_satisfaction"] > 0)
    check("baggage labelled combined", s["load_breakdown_source"] == "combined-simbrief-cargo")


def test_passenger_explicit_belly_freight_revenue():
    s = _estimate(flight_extra={"passengers": 110, "cargo": 1650, "commercial_freight_weight": 400, "weight_units": "KGS"})
    check("explicit belly freight generates revenue", s["commercial_freight_revenue"] > 0)
    check("manual override source", s["load_breakdown_source"] == "manual-override")


def test_freighter_zero_pax_freight_revenue():
    s = _estimate(flight_extra={"passengers": 0, "cargo": 12000, "weight_units": "KGS"})
    check("freighter op resolved", s["operation"]["resolved"] == "freighter")
    check("freighter zero passengers", s["passengers"]["total"] == 0)
    check("freighter zero passenger revenue", s["passenger_revenue_before_satisfaction"] == 0)
    check("freighter freight revenue", s["commercial_freight_revenue"] > 0)
    check("freighter satisfaction not applicable", s["satisfaction_applicable"] is False)


def test_freighter_satisfaction_ignored():
    s = _estimate(flight_extra={"passengers": 0, "cargo": 12000, "weight_units": "KGS"}, passenger_satisfaction={"score": 90, "revenue_multiplier": 0.5, "reputation_delta": 2})
    check("freighter multiplier forced to 1.0", s["passenger_satisfaction"]["applied_revenue_multiplier"] == 1.0)
    check("freighter total equals cargo revenue", s["total_revenue"] == s["commercial_freight_revenue"])


def test_combi_independent_revenues():
    s = _estimate(flight_extra={"passengers": 40, "cargo": 2450, "commercial_freight_weight": 800, "weight_units": "KGS", "operation_type_requested": "combi"})
    check("combi op resolved", s["operation"]["resolved"] == "combi")
    check("combi passenger revenue", s["passenger_revenue_before_satisfaction"] > 0)
    check("combi freight revenue", s["commercial_freight_revenue"] > 0)
    check("combi total = pax + freight", round(s["total_revenue"], 2) == round(s["passenger_revenue_after_satisfaction"] + s["commercial_freight_revenue"], 2))


def test_satisfaction_modifies_passenger_revenue_only():
    s = _estimate(
        flight_extra={"passengers": 110, "cargo": 2450, "freight_added": 800, "bag_weight": 15, "weight_units": "KGS", "operation_type_requested": "combi"},
        passenger_satisfaction={"score": 90, "revenue_multiplier": 0.5, "reputation_delta": 2},
    )
    check("verified split used", s["load_breakdown_source"] == "verified-simbrief-split")
    check("pax revenue halved", s["passenger_revenue_after_satisfaction"] == round(s["passenger_revenue_before_satisfaction"] * 0.5, 2))
    check("freight revenue untouched by satisfaction", s["commercial_freight_revenue"] > 0)


def test_ferry_zero_revenue():
    s = _estimate(flight_extra={"passengers": 0, "cargo": 0, "weight_units": "KGS"})
    check("ferry op resolved", s["operation"]["resolved"] == "ferry")
    check("ferry zero passenger revenue", s["passenger_revenue_before_satisfaction"] == 0)
    check("ferry zero freight revenue", s["commercial_freight_revenue"] == 0)
    check("ferry total revenue zero", s["total_revenue"] == 0)
    check("ferry satisfaction not applicable", s["satisfaction_applicable"] is False)


def test_zero_passengers_preserved():
    s = _estimate(flight_extra={"passengers": 0, "cargo": 500, "weight_units": "KGS"})
    check("zero pax stays zero", s["passengers"]["total"] == 0)
    check("zero pax not estimated", s["operation"]["reason"] != "explicit passenger count greater than zero")


def test_legacy_fallback_only_when_pax_missing():
    s = _estimate(flight_extra={"cargo": 500, "weight_units": "KGS"})
    check("missing pax uses fallback", s["operation"]["confidence"] == "fallback")
    check("fallback pax estimated", s["passengers"]["total"] > 0)


def test_freighter_with_missing_pax_never_fallback():
    s = _estimate(flight_extra={"operation_type_requested": "freighter", "cargo": 12000, "weight_units": "KGS"})
    check("explicit freighter resolved", s["operation"]["resolved"] == "freighter")
    check("explicit freighter zero pax", s["passengers"]["total"] == 0)


def test_lb_input_normalized():
    kg = _estimate(flight_extra={"passengers": 0, "cargo": 2204.62, "weight_units": "LBS"})
    lbs = _estimate(flight_extra={"passengers": 0, "cargo": 1000, "weight_units": "KGS"})
    check("LBS and KGS freight normalize equivalently", abs(kg["commercial_freight_revenue"] - lbs["commercial_freight_revenue"]) < 0.5)


def test_legacy_key_surfaces_preserved():
    s = _estimate(flight_extra={"passengers": 110, "cargo": 1650, "weight_units": "KGS"})
    check("legacy airline.revenue present", isinstance(s["airline"]["revenue"], dict))
    check("legacy passengers dict present", isinstance(s["passengers"], dict))
    check("legacy cargo_kg present", "cargo_kg" in s)


def test_revenue_breakdown_fields_exposed():
    s = _estimate(flight_extra={"passengers": 110, "cargo": 1650, "weight_units": "KGS"})
    for key in ("passenger_revenue_before_satisfaction", "passenger_revenue_after_satisfaction", "commercial_freight_revenue", "total_revenue", "effective_freight_rate_per_kg", "operation", "satisfaction_applicable"):
        check(f"exposed field {key}", key in s)


def main() -> None:
    setup()
    test_passenger_with_bags_only_no_freight_revenue()
    test_passenger_explicit_belly_freight_revenue()
    test_freighter_zero_pax_freight_revenue()
    test_freighter_satisfaction_ignored()
    test_combi_independent_revenues()
    test_satisfaction_modifies_passenger_revenue_only()
    test_ferry_zero_revenue()
    test_zero_passengers_preserved()
    test_legacy_fallback_only_when_pax_missing()
    test_freighter_with_missing_pax_never_fallback()
    test_lb_input_normalized()
    test_legacy_key_surfaces_preserved()
    test_revenue_breakdown_fields_exposed()

    print("=" * 60)
    total = PASS + FAIL
    print(f"RESULTS: {PASS}/{total} PASS, {FAIL} FAIL")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
