"""OPS ROOM -- flight load & operation model (v0.25.65).

Pure, dependency-free helpers shared by the Finance & Career estimator, the
Logbook plan snapshot and the live OFP completion builder.

Domain rules (v0.25.65):
  * A normal passenger flight often carries baggage, mail, belly freight and
    company material.  PAX > 0 and cargo > 0 does NOT mean COMBI.
  * SimBrief exposes a *verified* baggage/freight split when present:
        weights.freight_added  == commercial freight
        pax_count * bag_weight == checked baggage
    and ``weights.cargo`` == combined hold (bags + freight).  The split is only
    trusted when the cross-check ``cargo ~= baggage + freight`` passes; on any
    mismatch the combined value is kept and the split stays unknown.
  * Explicit zero passenger data is preserved (zero is a valid value).  Missing
    passenger data is distinct from explicit zero and may use a legacy
    capacity fallback -- but never for an explicit freighter or ferry.
"""

from __future__ import annotations

import math
from typing import Any

OPERATION_TYPES = ("auto", "passenger", "freighter", "combi", "ferry")

_WEIGHT_UNIT_ALIASES = {
    "LB": "LBS",
    "LBS": "LBS",
    "POUND": "LBS",
    "POUNDS": "LBS",
    "KG": "KGS",
    "KGS": "KGS",
    "KILOGRAM": "KGS",
    "KILOGRAMS": "KGS",
}

_KG_PER_LB = 0.45359237


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        n = float(str(value).replace(",", "").strip())
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def weight_unit_key(unit: Any) -> str | None:
    """Return a canonical weight-unit key (``LBS`` or ``KGS``) or None.

    Never infers a unit from magnitude.  Unknown units return None so callers
    can treat the value as unitless rather than guess.
    """
    key = str(unit or "").strip().upper()
    return _WEIGHT_UNIT_ALIASES.get(key)


# ---------------------------------------------------------------------------
# Operation resolution
# ---------------------------------------------------------------------------

def resolve_operation_type(
    flight: dict[str, Any] | None,
    requested_type: str = "auto",
) -> dict[str, Any]:
    """Resolve the operation type from explicit data + an optional user request.

    Returns::

        {"requested": ..., "resolved": ..., "reason": ..., "confidence": ...,
         "passengers": <int|None>, "cargo_hold_total": <float|None>}

    ``confidence`` is one of ``verified`` (explicit data), ``derived``
    (inferred from the load profile) or ``fallback`` (legacy estimate used).
    A legitimate zero passenger count never triggers a capacity estimate.
    """
    flight = flight if isinstance(flight, dict) else {}
    requested = str(requested_type or "auto").strip().lower()
    if requested not in OPERATION_TYPES:
        requested = "auto"

    passengers = None
    for key in ("passengers", "pax", "pax_count"):
        value = _num(flight.get(key))
        if value is not None:
            passengers = value
            break

    cargo_hold = None
    for key in ("cargo_hold_total", "cargo"):
        value = _num(flight.get(key))
        if value is not None:
            cargo_hold = value
            break

    base = {
        "requested": requested,
        "passengers": int(round(passengers)) if passengers is not None else None,
        "cargo_hold_total": cargo_hold,
    }

    if requested != "auto":
        base.update(
            resolved=requested,
            reason="explicit operation selection",
            confidence="verified",
        )
        return base

    if passengers is not None:
        if passengers > 0:
            base.update(resolved="passenger", reason="explicit passenger count greater than zero", confidence="verified")
            return base
        # Explicit zero passengers: never a capacity fallback.
        if cargo_hold is not None and cargo_hold > 0:
            base.update(resolved="freighter", reason="explicit zero passengers with positive cargo-hold load", confidence="derived", source_note="inferred from freighter OFP")
            return base
        base.update(resolved="ferry", reason="explicit zero passengers with no cargo-hold load", confidence="derived")
        return base

    # Passenger data is genuinely absent.
    base.update(
        resolved="passenger",
        reason="passenger data absent; legacy capacity estimate applies",
        confidence="fallback",
    )
    return base


# ---------------------------------------------------------------------------
# Load composition (baggage vs commercial freight)
# ---------------------------------------------------------------------------

def _pick(source: dict[str, Any], weights: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in source:
            value = _num(source.get(key))
            if value is not None:
                return value
        if key in weights:
            value = _num(weights.get(key))
            if value is not None:
                return value
    return None


def load_composition(source: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a plan or flight-payload dict into a load composition.

    Accepts both shapes:
      * the normalized SimBrief plan (``weights`` nested: ``passengers``,
        ``cargo``, ``payload``, ``freight_added``, ``bag_count``,
        ``bag_weight``, ``units``);
      * the Finance payload ``flight`` object (flat keys such as
        ``commercial_freight_weight``, ``cargo_hold_total``, ``weight_units``).

    ``cargo`` is always interpreted as the combined hold total (BAGS/CARGO)
    unless a verified split exists -- baggage is never automatically called
    commercial freight.
    """
    source = source if isinstance(source, dict) else {}
    weights = source.get("weights") if isinstance(source.get("weights"), dict) else {}

    passengers = _pick(source, weights, "passengers", "pax", "pax_count")
    bag_count = _pick(source, weights, "bag_count")
    bag_weight = _pick(source, weights, "bag_weight")
    freight = _pick(source, weights, "freight_added", "commercial_freight_weight")
    cargo_hold = _pick(source, weights, "cargo_hold_total", "cargo")
    payload = _pick(source, weights, "payload")

    units_raw = None
    for key in ("weight_units", "units"):
        if key in source and source.get(key) is not None:
            units_raw = source.get(key)
            break
        if key in weights and weights.get(key) is not None:
            units_raw = weights.get(key)
            break
    units = weight_unit_key(units_raw)

    baggage = None
    if passengers is not None and bag_weight is not None and passengers >= 0:
        baggage = round(passengers * bag_weight, 1)

    composition = {
        "passengers_count": int(round(passengers)) if passengers is not None else None,
        "baggage_weight": baggage,
        "commercial_freight_weight": None,
        "cargo_hold_total": cargo_hold,
        "payload_weight": payload,
        "weight_units": units,
        "load_breakdown_source": "combined-simbrief-cargo",
        "note": "no verified baggage/freight split",
    }

    # Verified split: cargo ~= baggage + freight_added (SimBrief's own numbers).
    if freight is not None and cargo_hold is not None:
        combined = (baggage if baggage is not None else 0.0) + freight
        tolerance = max(5.0, abs(cargo_hold) * 0.01)
        if abs(combined - cargo_hold) <= tolerance:
            composition.update(
                baggage_weight=baggage,
                commercial_freight_weight=freight,
                load_breakdown_source="verified-simbrief-split",
                note="baggage and freight split verified against SimBrief cargo total",
            )
            return composition
        # Freight-only OFP (no passenger baggage signal): freight == cargo.
        if baggage is None and abs(freight - cargo_hold) <= tolerance:
            composition.update(
                commercial_freight_weight=freight,
                load_breakdown_source="verified-simbrief-split",
                note="freight-only split verified against SimBrief cargo total",
            )
            return composition
        # Freight signal present but inconsistent with cargo: keep combined.
        composition["note"] = "freight signal inconsistent with cargo total; split not trusted"

    # Explicit frontend override is the only other verified source.
    explicit_freight = _pick(source, weights, "commercial_freight_weight")
    if explicit_freight is not None and composition.get("commercial_freight_weight") is None:
        composition.update(
            commercial_freight_weight=explicit_freight,
            load_breakdown_source="manual-override",
            note="commercial freight entered manually",
        )
    return composition


def finish_load_for_operation(
    composition: dict[str, Any],
    resolution: dict[str, Any],
) -> dict[str, Any]:
    """Apply operation-aware inference to a load composition (pure).

    For a resolved freighter whose split is unknown, the combined cargo-hold
    load may be treated as commercial freight -- with metadata showing it was
    inferred from a freighter OFP.
    """
    result = dict(composition)
    resolved = str((resolution or {}).get("resolved") or "auto")
    if (
        resolved == "freighter"
        and result.get("commercial_freight_weight") is None
        and result.get("cargo_hold_total") is not None
    ):
        result["commercial_freight_weight"] = result["cargo_hold_total"]
        result["load_breakdown_source"] = "inferred-freighter-hold"
        result["note"] = "combined cargo-hold treated as commercial freight (freighter OFP)"
    return result


# ---------------------------------------------------------------------------
# Unit conversion (weights + fuel share the same LB/KG unit family)
# ---------------------------------------------------------------------------

def weight_to_kg(value: Any, unit: Any) -> dict[str, Any]:
    """Convert a value to kilograms with conversion metadata.

    Returns ``{"source_value": ..., "source_unit": ..., "normalized_kg": ...,
    "conversion_applied": bool}``.  A missing/unknown unit returns
    ``normalized_kg`` None (never a guessed conversion).
    """
    number = _num(value)
    if number is None:
        return {"source_value": None, "source_unit": None, "normalized_kg": None, "conversion_applied": False}
    key = weight_unit_key(unit)
    if key is None:
        return {"source_value": number, "source_unit": str(unit or "").upper() or None, "normalized_kg": None, "conversion_applied": False}
    if key == "KGS":
        return {"source_value": number, "source_unit": "KGS", "normalized_kg": round(number, 4), "conversion_applied": False}
    return {"source_value": number, "source_unit": "LBS", "normalized_kg": round(number * _KG_PER_LB, 4), "conversion_applied": True}


def convert_weight_value(value: Any, from_unit: Any, to_unit: Any) -> dict[str, Any]:
    """Convert a weight between units with full metadata.

    ``to_unit`` falls back to ``from_unit`` when it is not a recognized unit.
    A conversion is never applied twice: the result unit is always ``to_unit``
    and the caller must not re-convert.
    """
    number = _num(value)
    if number is None:
        return {"source_value": None, "source_unit": None, "normalized_kg": None, "converted_value": None, "converted_unit": None, "conversion_applied": False}
    to_key = weight_unit_key(to_unit)
    from_key = weight_unit_key(from_unit)
    if to_key is None:
        to_key = from_key
    if to_key is None:
        return {"source_value": number, "source_unit": None, "normalized_kg": None, "converted_value": None, "converted_unit": None, "conversion_applied": False}
    normalized = weight_to_kg(number, from_key)
    kg = normalized["normalized_kg"]
    if kg is None:
        return {"source_value": number, "source_unit": from_key, "normalized_kg": None, "converted_value": None, "converted_unit": to_key, "conversion_applied": False}
    if to_key == "KGS":
        converted = kg
    else:
        converted = kg / _KG_PER_LB
    return {
        "source_value": number,
        "source_unit": from_key,
        "normalized_kg": round(kg, 4),
        "converted_value": round(converted, 4),
        "converted_unit": to_key,
        "conversion_applied": from_key != to_key,
    }


def planned_value_with_units(
    value: Any,
    unit: Any,
    display_unit: Any,
) -> dict[str, Any]:
    """Build the comparison object used by the live OFP endpoint for one value.

    Returns ``{planned_value, planned_unit, display_value, display_unit,
    availability, raw_value}`` where ``display_value`` is converted to the
    requested display unit (or kept as-is when units are unknown).
    """
    number = _num(value)
    if number is None:
        return {"availability": "unavailable", "raw_value": None, "planned_value": None, "planned_unit": str(unit or "").upper() or None, "display_value": None, "display_unit": str(display_unit or "").upper() or None}
    conversion = convert_weight_value(number, unit, display_unit)
    return {
        "availability": "available",
        "raw_value": number,
        "planned_value": number,
        "planned_unit": conversion["source_unit"],
        "display_value": conversion["converted_value"] if conversion["converted_value"] is not None else number,
        "display_unit": conversion["converted_unit"] or conversion["source_unit"],
        "conversion_applied": conversion["conversion_applied"],
    }
