"""Regression tests for the flight load & operation model -- v0.25.65.

Runs without external network access (pure unit tests), matching the
plain-Python PASS/FAIL harness style of test_realworld.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from app.load_model import (
    convert_weight_value,
    finish_load_for_operation,
    load_composition,
    resolve_operation_type,
    weight_to_kg,
)

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if condition:
        PASS += 1
        return True
    FAIL += 1
    print(f"  FAIL {name}" + (f" -- {detail}" if detail else ""))
    return False


# ---------------------------------------------------------------------------
# Operation resolution
# ---------------------------------------------------------------------------

def test_explicit_zero_passengers_stays_zero():
    r = resolve_operation_type({"passengers": 0, "cargo": 0})
    check("zero-pax resolves ferry", r["resolved"] == "ferry")
    check("zero-pax preserved as zero", r["passengers"] == 0)


def test_explicit_zero_passengers_never_capacity_fallback():
    r = resolve_operation_type({"passengers": 0, "cargo": 3000})
    check("zero-pax+cargo resolves freighter", r["resolved"] == "freighter")
    check("zero-pax never estimated", r["passengers"] == 0)
    check("freighter derived confidence", r["confidence"] == "derived")


def test_missing_passengers_legacy_fallback():
    r = resolve_operation_type({"cargo": 500})
    check("missing pax allows fallback", r["resolved"] == "passenger")
    check("missing pax fallback confidence", r["confidence"] == "fallback")
    check("missing pax remains None", r["passengers"] is None)


def test_pax_plus_cargo_resolves_passenger():
    r = resolve_operation_type({"passengers": 110, "cargo": 1650})
    check("pax>0+cargo resolves passenger", r["resolved"] == "passenger")
    check("pax+cargo not combi automatically", r["resolved"] != "combi")


def test_explicit_combi_selection():
    r = resolve_operation_type({"passengers": 40, "cargo": 12000}, requested_type="combi")
    check("combi manual selection honored", r["resolved"] == "combi")
    check("combi verified confidence", r["confidence"] == "verified")


def test_explicit_freighter_selection_with_missing_pax():
    r = resolve_operation_type({}, requested_type="freighter")
    check("explicit freighter honored", r["resolved"] == "freighter")
    check("explicit freighter never fallback pax", r["passengers"] is None)


def test_unknown_requested_type_falls_back_to_auto():
    r = resolve_operation_type({"passengers": 3}, requested_type="hovercraft")
    check("unknown requested type -> auto", r["requested"] == "auto")
    check("auto resolution applies", r["resolved"] == "passenger")


# ---------------------------------------------------------------------------
# Load composition / baggage vs freight
# ---------------------------------------------------------------------------

def test_verified_simbrief_split_passenger_plan():
    # Real payload shape: pax 110, bag 15 kg each, freight 0, cargo 1650.
    plan = {
        "weights": {
            "passengers": 110,
            "bag_count": 110,
            "bag_weight": 15,
            "freight_added": 0,
            "cargo": 1650,
            "payload": 10450,
            "units": "KGS",
        }
    }
    load = load_composition(plan)
    check("verified split source", load["load_breakdown_source"] == "verified-simbrief-split")
    check("baggage weight = pax*bags", load["baggage_weight"] == 1650.0)
    check("commercial freight is zero (bags only)", load["commercial_freight_weight"] == 0)
    check("cargo hold total preserved", load["cargo_hold_total"] == 1650.0)
    check("baggage not labelled freight", load["commercial_freight_weight"] != load["cargo_hold_total"])


def test_verified_split_with_belly_freight():
    plan = {"weights": {"passengers": 110, "bag_weight": 15, "freight_added": 800, "cargo": 2450, "units": "KGS"}}
    load = load_composition(plan)
    check("belly freight detected", load["commercial_freight_weight"] == 800)
    check("split still verified", load["load_breakdown_source"] == "verified-simbrief-split")


def test_freighter_plan_inferred_freight():
    plan = {"weights": {"passengers": 0, "freight_added": 12000, "cargo": 12000, "units": "KGS"}}
    load = load_composition(plan)
    r = resolve_operation_type({"passengers": 0, "cargo": 12000})
    finished = finish_load_for_operation(load, r)
    check("freighter hold becomes commercial freight", finished["commercial_freight_weight"] == 12000)
    check("freighter source is verified or inferred", finished["load_breakdown_source"] in ("verified-simbrief-split", "inferred-freighter-hold"))


def test_unknown_split_stays_unknown():
    plan = {"weights": {"passengers": 110, "cargo": 1650, "units": "KGS"}}
    load = load_composition(plan)
    check("no split stays combined", load["load_breakdown_source"] == "combined-simbrief-cargo")
    check("freight unknown when no split", load["commercial_freight_weight"] is None)
    check("baggage unknown when no split", load["baggage_weight"] is None)


def test_inconsistent_freight_signal_not_trusted():
    plan = {"weights": {"passengers": 110, "bag_weight": 15, "freight_added": 9999, "cargo": 1650, "units": "KGS"}}
    load = load_composition(plan)
    check("inconsistent split not trusted", load["load_breakdown_source"] == "combined-simbrief-cargo")
    check("freight not fabricated", load["commercial_freight_weight"] is None)


def test_manual_override_is_verified_source():
    payload = {"passengers": 110, "cargo": 1650, "commercial_freight_weight": 400}
    load = load_composition(payload)
    check("manual freight override honored", load["commercial_freight_weight"] == 400)
    check("manual override source", load["load_breakdown_source"] == "manual-override")


def test_flat_finance_payload_shape():
    payload = {"passengers": 0, "cargo_hold_total": 12000, "weight_units": "LBS"}
    load = load_composition(payload)
    check("flat payload cargo hold read", load["cargo_hold_total"] == 12000)
    check("flat payload units read", load["weight_units"] == "LBS")


def test_zero_values_survive_payload():
    payload = {"passengers": 0, "cargo": 0}
    check("zero passengers preserved", load_composition(payload)["passengers_count"] == 0)
    check("zero cargo preserved", load_composition(payload)["cargo_hold_total"] == 0)


# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------

def test_kg_and_lb_normalize_equivalently():
    kg = weight_to_kg(1000, "KGS")["normalized_kg"]
    lb = weight_to_kg(2204.62262185, "LBS")["normalized_kg"]
    check("1000 kg == 2204.6 lb", kg is not None and lb is not None and abs(kg - lb) < 0.01)


def test_conversion_metadata_present():
    meta = weight_to_kg(2205, "LBS")
    check("conversion applied flag", meta["conversion_applied"] is True)
    check("source unit preserved", meta["source_unit"] == "LBS")
    check("normalized kg present", meta["normalized_kg"] is not None)


def test_no_conversion_for_kg():
    meta = weight_to_kg(5444, "KGS")
    check("kg stays kg", meta["conversion_applied"] is False)
    check("kg value unchanged", meta["normalized_kg"] == 5444)


def test_unknown_unit_never_guessed():
    meta = weight_to_kg(100, "FURLONGS")
    check("unknown unit yields None", meta["normalized_kg"] is None)
    check("unknown unit no conversion", meta["conversion_applied"] is False)


def test_missing_value_no_conversion():
    meta = weight_to_kg(None, "LBS")
    check("missing value yields None", meta["normalized_kg"] is None)


def test_display_conversion_kg_to_lb():
    meta = convert_weight_value(1000, "KGS", "LBS")
    check("kg->lb converts", meta["converted_unit"] == "LBS" and abs(meta["converted_value"] - 2204.62) < 0.05)
    check("kg->lb applied", meta["conversion_applied"] is True)


def test_display_conversion_lb_to_kg():
    meta = convert_weight_value(2204.62262185, "LBS", "KGS")
    check("lb->kg converts", abs(meta["converted_value"] - 1000) < 0.01)


def test_zero_value_conversion():
    meta = convert_weight_value(0, "KGS", "LBS")
    check("zero converts without error", meta["converted_value"] == 0)


def test_ferry_has_no_commercial_revenue_signal():
    load = load_composition({"passengers": 0, "cargo": 0})
    check("ferry cargo hold zero", load["cargo_hold_total"] == 0)
    check("ferry freight none", load["commercial_freight_weight"] is None)


def main() -> None:
    test_explicit_zero_passengers_stays_zero()
    test_explicit_zero_passengers_never_capacity_fallback()
    test_missing_passengers_legacy_fallback()
    test_pax_plus_cargo_resolves_passenger()
    test_explicit_combi_selection()
    test_explicit_freighter_selection_with_missing_pax()
    test_unknown_requested_type_falls_back_to_auto()
    test_verified_simbrief_split_passenger_plan()
    test_verified_split_with_belly_freight()
    test_freighter_plan_inferred_freight()
    test_unknown_split_stays_unknown()
    test_inconsistent_freight_signal_not_trusted()
    test_manual_override_is_verified_source()
    test_flat_finance_payload_shape()
    test_zero_values_survive_payload()
    test_kg_and_lb_normalize_equivalently()
    test_conversion_metadata_present()
    test_no_conversion_for_kg()
    test_unknown_unit_never_guessed()
    test_missing_value_no_conversion()
    test_display_conversion_kg_to_lb()
    test_display_conversion_lb_to_kg()
    test_zero_value_conversion()
    test_ferry_has_no_commercial_revenue_signal()

    print("=" * 60)
    total = PASS + FAIL
    print(f"RESULTS: {PASS}/{total} PASS, {FAIL} FAIL")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
