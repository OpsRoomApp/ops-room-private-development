"""OPS ROOM -- live OFP actuals builder (v0.25.65).

Builds the comparison payload for BRIEFING -> OFP "live completion" from:

  * the cached SimBrief plan (``cached_plan``);
  * the active (or most recent completed) Logbook recorder metadata, which
    carries the plan snapshot + immutable ``operational_snapshots``.

This module is deliberately pure: no I/O, no telemetry reads.  The endpoint in
``main.py`` supplies the inputs.  All raw numbers and ISO UTC timestamps are
returned; the frontend performs presentation formatting only.
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .load_model import convert_weight_value, resolve_operation_type, weight_unit_key
from .ofp_overrides import ALL_KEYS as OVERRIDE_KEYS

_EVENT_KEYS = {"out": "block_out", "off": "takeoff", "on": "landing", "in": "block_in"}

_SNAPSHOT_KEYS = {"out": "out", "off": "off", "on": "on", "in": "in"}

_PLAN_TIMES_KEYS = {
    "out": ("scheduled_out", "scheduled_out_utc"),
    "off": ("scheduled_off", "scheduled_off_utc"),
    "on": ("scheduled_on", "scheduled_on_utc"),
    "in": ("scheduled_in", "scheduled_in_utc"),
}


def _num(value: Any) -> float | None:
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def _utc_epoch(iso: Any) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, OSError, OverflowError):
        return None


def _manual_time_to_iso(value: Any, reference_utc: Any) -> str | None:
    """Resolve a manual time entry (HHMM or full ISO) to ISO UTC.

    A bare ``HHMM`` entry takes the calendar date from ``reference_utc``
    (preferring the scheduled event time, then the recorder start) so a pilot
    typing ``1617Z`` lands on the correct UTC day.  Full ISO values (with or
    without a ``Z`` suffix) are passed through after normalization.
    """
    raw = str(value or "").strip()
    if not raw:
        return None
    compact = raw.replace("Z", "").replace("z", "")
    if re.fullmatch(r"\d{2}:?\d{2}", compact):
        try:
            hh = int(compact[:2])
            mm = int(compact[-2:])
        except (TypeError, ValueError):
            return None
        if hh > 23 or mm > 59:
            return None
        epoch = _utc_epoch(reference_utc)
        if epoch is None:
            epoch = datetime.now(timezone.utc).timestamp()
        base = datetime.fromtimestamp(epoch, tz=timezone.utc)
        resolved = base.replace(hour=hh, minute=mm, second=0, microsecond=0)
        # Midnight crossing: a time far earlier than the reference (e.g. the
        # pilot types 0005 for an event after a 2350 scheduled time) belongs to
        # the NEXT UTC day, not an absurd negative delta on the reference day.
        if (epoch - resolved.timestamp()) > 12 * 3600:
            resolved = resolved + timedelta(days=1)
        return resolved.isoformat().replace("+00:00", "Z")
    epoch = _utc_epoch(raw)
    return _iso(epoch) if epoch is not None else None


def _revision(payload: dict[str, Any]) -> str:
    try:
        return hashlib.sha1(json_dumps_sorted(payload).encode("utf-8", "ignore")).hexdigest()[:12]
    except Exception:
        return "0"


def json_dumps_sorted(payload: Any) -> str:
    import json

    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _display_unit(plan_units: str | None, settings_override: str | None = None) -> str | None:
    """Resolve the display unit: explicit host setting wins, else plan units."""
    override = weight_unit_key(settings_override)
    plan = weight_unit_key(plan_units)
    if override:
        return override
    return plan


def _value_cell(
    planned: Any,
    actual: Any,
    unit: Any,
    display_unit: Any,
    *,
    max_value: Any = None,
    source: str = "phase-detection",
    availability_note: str = "",
) -> dict[str, Any]:
    """One comparison cell: planned/actual/delta converted to the display unit."""
    planned_n = _num(planned)
    actual_n = _num(actual)
    max_n = _num(max_value)
    cell = {
        "planned": planned_n,
        "actual": actual_n,
        "max": max_n,
        "planned_unit": str(unit or "").upper() or None,
        "actual_unit": str(unit or "").upper() or None,
        "delta": round(actual_n - planned_n, 4) if planned_n is not None and actual_n is not None else None,
        "source": source,
        "availability": "available" if actual_n is not None else "unavailable",
    }
    if availability_note:
        cell["note"] = availability_note
    # Display conversion (backend-owned; frontend renders only).
    if display_unit:
        planned_d = convert_weight_value(planned_n, unit, display_unit) if planned_n is not None else None
        actual_d = convert_weight_value(actual_n, unit, display_unit) if actual_n is not None else None
        max_d = convert_weight_value(max_n, unit, display_unit) if max_n is not None else None
        cell["planned_display"] = planned_d["converted_value"] if planned_d else None
        cell["actual_display"] = actual_d["converted_value"] if actual_d else None
        cell["max_display"] = max_d["converted_value"] if max_d else None
        cell["display_unit"] = display_unit
    else:
        cell["planned_display"] = planned_n
        cell["actual_display"] = actual_n
        cell["max_display"] = max_n
        cell["display_unit"] = str(unit or "").upper() or None
    # Delta in the display unit (frontends render this directly; the raw
    # ``delta`` above stays in the plan unit for machine consumers).
    _pd = _num(cell.get("planned_display"))
    _ad = _num(cell.get("actual_display"))
    cell["delta_display"] = round(_ad - _pd, 4) if _pd is not None and _ad is not None else None
    return cell


def _plan_identity(plan: dict[str, Any] | None) -> dict[str, Any]:
    plan = plan if isinstance(plan, dict) else {}
    origin = plan.get("origin") if isinstance(plan.get("origin"), dict) else {}
    destination = plan.get("destination") if isinstance(plan.get("destination"), dict) else {}
    times = plan.get("times") if isinstance(plan.get("times"), dict) else {}
    aircraft = plan.get("aircraft") if isinstance(plan.get("aircraft"), dict) else {}
    return {
        "request_id": str(plan.get("request_id") or ""),
        "sequence_id": str(plan.get("sequence_id") or ""),
        "plan_id": str(plan.get("plan_id") or ""),
        "generated_utc": str(plan.get("generated_utc") or ""),
        "callsign": str(plan.get("callsign") or ""),
        "origin": str(origin.get("icao") or ""),
        "destination": str(destination.get("icao") or ""),
        "scheduled_out": str(times.get("scheduled_out") or times.get("scheduled_out_utc") or ""),
        "registration": str(aircraft.get("registration") or ""),
    }


def _recorder_identity(recorder: dict[str, Any] | None) -> dict[str, Any]:
    recorder = recorder if isinstance(recorder, dict) else {}
    ofp_plan = recorder.get("ofp_plan") if isinstance(recorder.get("ofp_plan"), dict) else {}
    # Real recorders/completed entries carry the nested plan reference inside
    # their ``flight`` snapshot (``flight.ofp_plan``); synthetic/legacy shapes
    # may expose it at the top level.  Accept both so identity matching never
    # collapses to "mismatch" for an otherwise valid recording.
    if not ofp_plan:
        flight = recorder.get("flight") if isinstance(recorder.get("flight"), dict) else {}
        ofp_plan = flight.get("ofp_plan") if isinstance(flight.get("ofp_plan"), dict) else {}
    identity = ofp_plan.get("identity") if isinstance(ofp_plan.get("identity"), dict) else {}
    return {
        "id": str(recorder.get("id") or ""),
        "started_utc": str(recorder.get("started_utc") or ""),
        "callsign": str(identity.get("callsign") or ""),
        "origin": str(identity.get("origin") or ""),
        "destination": str(identity.get("destination") or ""),
        "scheduled_out": str(identity.get("scheduled_out") or ""),
        "request_id": str(identity.get("request_id") or ""),
    }


def _flight_match(plan_identity: dict[str, Any], recorder_identity: dict[str, Any]) -> tuple[bool, str]:
    if not plan_identity or not recorder_identity:
        return False, "missing identity"
    if plan_identity.get("request_id") and recorder_identity.get("request_id"):
        if plan_identity["request_id"] == recorder_identity["request_id"]:
            return True, "request_id"
        return False, "request_id mismatch"
    if plan_identity.get("callsign") and recorder_identity.get("callsign"):
        same_route = plan_identity["origin"] == recorder_identity["origin"] and plan_identity["destination"] == recorder_identity["destination"]
        same_time = bool(plan_identity.get("scheduled_out")) and plan_identity["scheduled_out"] == recorder_identity["scheduled_out"]
        if same_route and (same_time or plan_identity.get("callsign") == recorder_identity["callsign"]):
            return True, "callsign+route"
    return False, "no matching plan identity"


def _manual_section(overrides: dict[str, Any] | None, prefix: str) -> dict[str, Any]:
    """Pull ``prefix:*`` entries out of the flat override map."""
    out: dict[str, Any] = {}
    for key, value in (overrides or {}).items():
        if isinstance(key, str) and key.startswith(prefix + ":"):
            out[key[len(prefix) + 1 :]] = value
    return out


def _times_section(plan: dict[str, Any], recorder: dict[str, Any], overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    plan = plan if isinstance(plan, dict) else {}
    plan_times = plan.get("times") if isinstance(plan.get("times"), dict) else {}
    plan_block = _num(plan.get("block_time_seconds")) or _num(plan.get("ete_seconds"))
    recorder_times = recorder.get("times") if isinstance(recorder.get("times"), dict) else {}
    snapshots = recorder.get("operational_snapshots") if isinstance(recorder.get("operational_snapshots"), dict) else {}
    manual = _manual_section(overrides, "times")
    started_utc = recorder.get("started_utc") or (recorder.get("_state") or {}).get("started_utc")
    rows: dict[str, Any] = {}
    for key, event_key in _EVENT_KEYS.items():
        scheduled = None
        for name in _PLAN_TIMES_KEYS[key]:
            scheduled = plan_times.get(name)
            if scheduled:
                break
        sched_epoch = _utc_epoch(scheduled)
        snapshot = snapshots.get(_SNAPSHOT_KEYS[key]) if isinstance(snapshots.get(_SNAPSHOT_KEYS[key]), dict) else {}
        manual_val = manual.get(key)
        if manual_val is not None:
            actual_utc = _manual_time_to_iso(manual_val, scheduled or recorder_times.get(event_key) or started_utc)
            source = "manual"
            estimated = False
        else:
            actual_utc = _iso(_utc_epoch(recorder_times.get(event_key)))
            source = "phase-detection"
            estimated = bool(snapshot.get("estimated"))
        actual_epoch = _utc_epoch(actual_utc)
        # v0.25.72 (#13): deltas are rounded to whole minutes so the display
        # matches the minute-precision times (1754Z vs 1735Z -> +19, not +1909).
        delta = int(round((actual_epoch - sched_epoch) / 60.0)) * 60 if sched_epoch is not None and actual_epoch is not None else None
        rows[key] = {
            "scheduled_utc": _iso(sched_epoch),
            "actual_utc": actual_utc,
            "delta_seconds": delta,
            "estimated": estimated,
            "source": source,
        }
        if manual_val is not None:
            rows[key]["manual"] = True
    in_epoch = _utc_epoch(rows.get("in", {}).get("actual_utc"))
    out_epoch = _utc_epoch(rows.get("out", {}).get("actual_utc"))
    actual_block = int(round(in_epoch - out_epoch)) if in_epoch is not None and out_epoch is not None and in_epoch >= out_epoch else None
    rows["block"] = {
        "planned_seconds": int(round(plan_block)) if plan_block is not None else None,
        "actual_seconds": actual_block,
        # v0.25.72 (#13): whole-minute delta for BLOCK too.
        "delta_seconds": (int(round((actual_block - int(round(plan_block))) / 60.0)) * 60) if actual_block is not None and plan_block is not None else None,
        "source": "phase-detection",
    }
    return rows


def _weights_section(
    plan: dict[str, Any],
    recorder: dict[str, Any],
    display_unit: str | None,
    overrides: dict[str, Any] | None = None,
    loading_progress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    flight = recorder.get("flight") if isinstance(recorder.get("flight"), dict) else {}
    snapshots = recorder.get("operational_snapshots") if isinstance(recorder.get("operational_snapshots"), dict) else {}
    off = snapshots.get("off") if isinstance(snapshots.get("off"), dict) else {}
    on = snapshots.get("on") if isinstance(snapshots.get("on"), dict) else {}
    out = snapshots.get("out") if isinstance(snapshots.get("out"), dict) else {}
    weight_unit = flight.get("weight_units")
    if not weight_unit:
        ofp = flight.get("ofp_plan") if isinstance(flight.get("ofp_plan"), dict) else {}
        units = ofp.get("units") if isinstance(ofp.get("units"), dict) else {}
        weight_unit = units.get("weight")
    manual = _manual_section(overrides, "weights")
    manual_weights = {k: v for k, v in manual.items() if k in {"zfw", "tow", "ldw"}}
    loading = loading_progress if isinstance(loading_progress, dict) else {}
    fenix_loading = loading.get("fenix") if isinstance(loading.get("fenix"), dict) else {}
    manual_pax = manual.get("pax")

    def actual_for(key: str, source: dict[str, Any]) -> Any:
        return source.get(key) if isinstance(source, dict) else None

    def manual_cell(planned: Any, manual_value: Any, *, max_value: Any = None) -> dict[str, Any]:
        """Build a cell whose actual value is a manual entry.

        The manual value is stored in the display unit (that is what the pilot
        typed); it is converted back into the plan weight unit for comparison
        and the raw lb equivalent is retained as ``actual_lb``.
        """
        display_key = weight_unit_key(display_unit) or weight_unit_key(weight_unit) or "LBS"
        plan_key = weight_unit_key(weight_unit) or display_key
        manual_n = _num(manual_value)
        actual_plan = None
        if manual_n is not None:
            if display_key == plan_key:
                actual_plan = manual_n
            else:
                converted = convert_weight_value(manual_n, display_key, plan_key)
                actual_plan = converted.get("converted_value") if converted else None
        cell = _value_cell(planned, actual_plan, weight_unit, display_unit, max_value=max_value, source="manual")
        cell["manual"] = True
        cell["manual_value"] = manual_n
        converted = convert_weight_value(manual_n, display_key, "LBS") if manual_n is not None else {"converted_value": None}
        cell["actual_lb"] = converted.get("converted_value") if converted else None
        return cell

    def snapshot_cell(planned: Any, lb_value: Any, source: dict[str, Any], *, max_value: Any = None, source_name: str = "snapshot") -> dict[str, Any]:
        """Build a cell whose actual value is a snapshot value stored in lb.

        The snapshot lb value is converted into the plan's weight unit before
        comparison; the raw lb is retained as ``actual_lb``.
        """
        lb = _num(lb_value)
        actual_plan = None
        if lb is not None:
            plan_key = weight_unit_key(weight_unit) or "LBS"
            converted = convert_weight_value(lb, "LBS", plan_key)
            actual_plan = converted.get("converted_value") if converted else None
        cell = _value_cell(planned, actual_plan, weight_unit, display_unit, max_value=max_value, source=source_name)
        cell["actual_lb"] = lb
        return cell

    rows: dict[str, Any] = {}
    if manual_pax is not None:
        pax_n = _num(manual_pax)
        rows["passengers"] = {
            "planned": flight.get("passengers"),
            "actual": pax_n,
            "max": None,
            "availability": "available" if pax_n is not None else "unavailable",
            "source": "manual",
            "note": "manual override",
            "manual": True,
            "manual_value": pax_n,
        }
    else:
        # v0.25.71: GSX/Fenix boarding progress is a trusted measured source
        # for the PAX count. The planned value is never shown as an actual.
        gsx_pax = _num(loading.get("passengers")) or _num(loading.get("passengers_boarding_total"))
        fenix_pax = _num(fenix_loading.get("pax_loaded"))
        live_pax = fenix_pax if fenix_pax is not None else (gsx_pax if gsx_pax is not None else None)
        if live_pax is not None:
            rows["passengers"] = {
                "planned": flight.get("passengers"),
                "actual": int(round(live_pax)),
                "max": None,
                "availability": "available",
                "source": "gsx/fenix loading",
                "note": "live boarding count",
            }
        else:
            rows["passengers"] = {
                "planned": flight.get("passengers"),
                "actual": None,
                "max": None,
                "availability": "unavailable",
                "source": "no trusted measured source",
                "note": "planned PAX is never presented as a measured actual",
            }
    # BAG/CARGO actual from Fenix cargo loaded (kg) when available; otherwise
    # from GSX cargo percent applied to the planned hold total.
    fenix_cargo_kg = _num(fenix_loading.get("cargo_loaded_kg"))
    cargo_percent = _num(loading.get("boarding_cargo_percent"))
    planned_cargo = _num(flight.get("cargo_hold_total"))
    cargo_actual = None
    cargo_source = ""
    if fenix_cargo_kg is not None:
        plan_key = weight_unit_key(weight_unit) or "KGS"
        converted = convert_weight_value(fenix_cargo_kg, "KGS", plan_key)
        cargo_actual = converted.get("converted_value") if converted else None
        cargo_source = "gsx/fenix loading"
    elif cargo_percent is not None and planned_cargo is not None:
        cargo_actual = round(planned_cargo * cargo_percent / 100.0, 4)
        cargo_source = "gsx/fenix loading"
    rows["bags_cargo"] = _value_cell(
        flight.get("cargo_hold_total"),
        cargo_actual,
        weight_unit,
        display_unit,
        availability_note="combined hold; no trusted measured actual" if cargo_actual is None else "measured from live loading",
        source=cargo_source or "no trusted measured source",
    )
    rows["commercial_freight"] = _value_cell(flight.get("commercial_freight_weight"), None, weight_unit, display_unit, availability_note="freight actual requires manual/GSX source")
    rows["payload"] = _value_cell(flight.get("payload"), None, weight_unit, display_unit, availability_note="planned payload only")
    if "zfw" in manual_weights:
        rows["zfw"] = manual_cell(flight.get("planned_zfw"), manual_weights["zfw"])
    else:
        rows["zfw"] = snapshot_cell(flight.get("planned_zfw"), actual_for("calculated_zfw_lb", out), out, source_name="out-snapshot calculation")
    if "tow" in manual_weights:
        rows["tow"] = manual_cell(flight.get("planned_tow"), manual_weights["tow"], max_value=flight.get("planned_max_tow"))
    else:
        rows["tow"] = snapshot_cell(flight.get("planned_tow"), actual_for("gross_weight_lb", off), off, max_value=flight.get("planned_max_tow"), source_name="off-snapshot")
    if "ldw" in manual_weights:
        rows["ldw"] = manual_cell(flight.get("planned_ldw"), manual_weights["ldw"], max_value=flight.get("planned_max_ldw"))
    else:
        rows["ldw"] = snapshot_cell(flight.get("planned_ldw"), actual_for("gross_weight_lb", on), on, max_value=flight.get("planned_max_ldw"), source_name="on-snapshot")
    return rows


def _fuel_section(plan: dict[str, Any], recorder: dict[str, Any], display_unit: str | None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    flight = recorder.get("flight") if isinstance(recorder.get("flight"), dict) else {}
    snapshots = recorder.get("operational_snapshots") if isinstance(recorder.get("operational_snapshots"), dict) else {}
    out = snapshots.get("out") if isinstance(snapshots.get("out"), dict) else {}
    off = snapshots.get("off") if isinstance(snapshots.get("off"), dict) else {}
    on = snapshots.get("on") if isinstance(snapshots.get("on"), dict) else {}
    inn = snapshots.get("in") if isinstance(snapshots.get("in"), dict) else {}
    fuel_unit = flight.get("fuel_units")
    if not fuel_unit:
        ofp = flight.get("ofp_plan") if isinstance(flight.get("ofp_plan"), dict) else {}
        units = ofp.get("units") if isinstance(ofp.get("units"), dict) else {}
        fuel_unit = units.get("fuel")
    manual = _manual_section(overrides, "fuel")
    planned = {
        "ramp": flight.get("planned_ramp_fuel"),
        "takeoff": flight.get("planned_takeoff_fuel"),
        "trip": flight.get("planned_trip_fuel"),
        "landing": flight.get("planned_landing_fuel"),
        "reserve": flight.get("planned_reserve_fuel"),
        "alternate": flight.get("planned_alternate_fuel"),
        "extra": flight.get("planned_extra_fuel"),
    }
    actual_lb = {
        "out": out.get("fuel_lb"),
        "off": off.get("fuel_lb"),
        "on": on.get("fuel_lb"),
        "in": inn.get("fuel_lb"),
    }

    def to_plan_unit(lb_value: Any) -> float | None:
        lb = _num(lb_value)
        if lb is None:
            return None
        plan_key = weight_unit_key(fuel_unit) or "LBS"
        converted = convert_weight_value(lb, "LBS", plan_key)
        return converted.get("converted_value") if converted else None

    def manual_to_plan(manual_value: Any) -> float | None:
        """Manual fuel is entered in the display unit; convert to plan unit."""
        value = _num(manual_value)
        if value is None:
            return None
        plan_key = weight_unit_key(fuel_unit) or "LBS"
        display_key = weight_unit_key(display_unit) or plan_key
        if display_key == plan_key:
            return value
        converted = convert_weight_value(value, display_key, plan_key)
        return converted.get("converted_value") if converted else None

    actual_plan = {key: to_plan_unit(value) for key, value in actual_lb.items()}
    manual_plan = {
        "out": manual_to_plan(manual.get("ramp")),
        "off": manual_to_plan(manual.get("takeoff")),
        "on": manual_to_plan(manual.get("landing")),
        "in": manual_to_plan(manual.get("blockin")),
    }
    for key in ("out", "off", "on", "in"):
        if manual_plan[key] is not None:
            actual_plan[key] = manual_plan[key]
    trip_actual = None
    if actual_plan["off"] is not None and actual_plan["on"] is not None and actual_plan["off"] >= actual_plan["on"]:
        trip_actual = round(actual_plan["off"] - actual_plan["on"], 1)
    surplus = None
    if actual_plan["in"] is not None and planned["reserve"] is not None and planned["alternate"] is not None:
        surplus = round(actual_plan["in"] - (planned["reserve"] + planned["alternate"]), 1)

    def cell(p_key: str | None, a_key: str | None, note: str = "", manual_key: str | None = None) -> dict[str, Any]:
        manual_present = manual_key is not None and manual.get(manual_key) is not None
        source = "manual" if manual_present else "phase-detection"
        row = _value_cell(
            planned.get(p_key) if p_key else None,
            actual_plan.get(a_key) if a_key else None,
            fuel_unit,
            display_unit,
            availability_note="" if manual_present else note,
            source=source,
        )
        if a_key:
            row["actual_lb"] = _num(actual_lb.get(a_key))
        if manual_present:
            row["manual"] = True
            row["manual_value"] = _num(manual.get(manual_key))
            if note:
                row["note"] = note
        return row

    return {
        "ramp_out": cell("ramp", "out", manual_key="ramp"),
        "takeoff_off": cell("takeoff", "off", manual_key="takeoff"),
        "trip": _value_cell(planned.get("trip"), trip_actual, fuel_unit, display_unit, source="off-on subtraction"),
        "landing_on": cell("landing", "on", manual_key="landing"),
        "block_in": cell(None, "in", note="planned block-in value unavailable; actual only", manual_key="blockin"),
        "extra_surplus": _value_cell(planned.get("extra"), surplus, fuel_unit, display_unit, source="in-fuel minus planned reserve+alternate", availability_note="surplus definition: block-in fuel minus planned reserve and alternate"),
    }


def _plan_flight(plan: dict[str, Any]) -> dict[str, Any]:
    """Build a flight-shaped dict straight from the normalized SimBrief plan.

    Used for the ``waiting`` state (plan loaded, recording not started yet):
    the sections below read planned values off ``recorder.flight``, so this
    helper synthesizes that shape from the plan so the panel can show PLANNED
    times/fuel/weights (with actuals unavailable) before any event occurs.
    """
    plan = plan if isinstance(plan, dict) else {}
    fuel = plan.get("fuel") if isinstance(plan.get("fuel"), dict) else {}
    weights = plan.get("weights") if isinstance(plan.get("weights"), dict) else {}
    operation = resolve_operation_type(
        {
            "passengers": weights.get("passengers"),
            "cargo": weights.get("cargo"),
            "cargo_hold_total": weights.get("cargo"),
            "commercial_freight_weight": weights.get("freight_added"),
            "weight_units": weights.get("units"),
        },
        str(plan.get("operation_type_requested") or "auto"),
    )
    return {
        "fuel_units": _text(fuel.get("units")).upper() or None,
        "weight_units": _text(weights.get("units")).upper() or None,
        "passengers": _num(weights.get("passengers")),
        "cargo_hold_total": _num(weights.get("cargo")),
        "commercial_freight_weight": _num(weights.get("freight_added")),
        "payload": _num(weights.get("payload")),
        "planned_ramp_fuel": _num(fuel.get("ramp")),
        "planned_takeoff_fuel": _num(fuel.get("takeoff")),
        "planned_trip_fuel": _num(fuel.get("trip")),
        "planned_landing_fuel": _num(fuel.get("landing")),
        "planned_reserve_fuel": _num(fuel.get("reserve")),
        "planned_alternate_fuel": _num(fuel.get("alternate")),
        "planned_extra_fuel": _num(fuel.get("extra")),
        "planned_zfw": _num(weights.get("zfw")),
        "planned_tow": _num(weights.get("tow")),
        "planned_ldw": _num(weights.get("ldw")),
        "planned_max_zfw": _num(weights.get("max_zfw")),
        "planned_max_tow": _num(weights.get("max_tow")),
        "planned_max_ldw": _num(weights.get("max_ldw")),
        "operation_type_requested": _text(plan.get("operation_type_requested")) or "auto",
        "operation_type_resolved": operation.get("resolved") or "auto",
        "block_time_seconds": _num(plan.get("block_time_seconds")) or _num(plan.get("ete_seconds")),
        "ete_seconds": _num(plan.get("ete_seconds")),
    }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _operation_section(flight: dict[str, Any]) -> dict[str, Any]:
    resolved = str(flight.get("operation_type_resolved") or "auto")
    requested = str(flight.get("operation_type_requested") or "auto")
    try:
        resolution = resolve_operation_type(
            {
                "passengers": flight.get("passengers"),
                "cargo": flight.get("cargo_hold_total"),
                "cargo_hold_total": flight.get("cargo_hold_total"),
                "commercial_freight_weight": flight.get("commercial_freight_weight"),
                "weight_units": flight.get("weight_units"),
            },
            requested,
        )
        resolved = resolution["resolved"]
    except Exception:
        pass
    return {"requested": requested, "resolved": resolved, "reason": str(flight.get("operation_type_resolved") and ""), "source": "plan-snapshot"}


def _completeness(payload: dict[str, Any]) -> dict[str, Any]:
    missing: list[str] = []
    times = payload.get("times") or {}
    for key in ("out", "off", "on", "in"):
        if not times.get(key, {}).get("actual_utc"):
            missing.append(f"time:{key}")
    fuel = payload.get("fuel") or {}
    if not fuel.get("takeoff_off", {}).get("actual"):
        missing.append("fuel:takeoff")
    if not fuel.get("landing_on", {}).get("actual"):
        missing.append("fuel:landing")
    if not fuel.get("trip", {}).get("actual"):
        missing.append("fuel:trip")
    weights = payload.get("weights") or {}
    if not weights.get("tow", {}).get("actual"):
        missing.append("weight:tow")
    if not weights.get("ldw", {}).get("actual"):
        missing.append("weight:ldw")
    all_times = all(times.get(key, {}).get("actual_utc") for key in ("out", "off", "on", "in"))
    all_fuel = fuel.get("trip", {}).get("actual") is not None
    return {
        "times": "complete" if all_times else "partial",
        "fuel": "complete" if all_fuel else "partial",
        "weights": "partial",
        "missing_fields": missing[:20],
    }


def build_live_ofp_actuals(
    plan: dict[str, Any] | None,
    recorder: dict[str, Any] | None,
    completed_entry: dict[str, Any] | None = None,
    settings_override_unit: str | None = None,
    telemetry_fresh: bool | None = None,
    overrides: dict[str, Any] | None = None,
    loading_progress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the full live OFP comparison payload (pure).

    ``recorder`` is the active recorder metadata; ``completed_entry`` is the
    most recent completed entry metadata (used after block-in so the panel
    keeps showing final values).  Exactly one should be provided per state.

    ``overrides`` is an optional flat map of manual entries (keys from
    ``ofp_overrides.ALL_KEYS``, e.g. ``times:out``, ``weights:zfw``,
    ``fuel:ramp``) that outrank telemetry/phase detection for the affected
    cells and are marked ``source=manual``.

    ``loading_progress`` is an optional GSX/Fenix loading snapshot
    (``gsx_remote.automation_status()["fenix_loading"]["last_progress"]``)
    used to fill the measured PAX and BAG/CARGO actuals while boarding is in
    progress.  It never overrides a manual entry; it only replaces the
    otherwise-unavailable actual cells.
    """
    plan = plan if isinstance(plan, dict) else {}
    overrides = overrides if isinstance(overrides, dict) else {}
    overrides = {k: v for k, v in overrides.items() if isinstance(k, str) and k in OVERRIDE_KEYS}
    source = completed_entry if completed_entry is not None else recorder
    if not isinstance(plan, dict) or not plan.get("ok"):
        return {"ok": True, "state": "no-plan", "revision": "0", "updated_utc": None, "reason": "No SimBrief flight plan loaded"}

    if source is None:
        # v0.25.66: the WAITING state still renders the PLANNED values from the
        # SimBrief plan (scheduled times, planned fuel/weights) with actuals
        # unavailable -- the panel is no longer an empty wall of dashes until a
        # recorder starts.
        flight = _plan_flight(plan)
        display_unit = _display_unit(flight.get("fuel_units") or flight.get("weight_units"), settings_override_unit)
        plan_identity = _plan_identity(plan)
        waiting: dict[str, Any] = {
            "ok": True,
            "state": "waiting",
            "revision": "0",
            "updated_utc": None,
            "reason": "Flight plan loaded; waiting for an active recorder",
            "plan_identity": plan_identity,
            "recorder_identity": {},
            "flight_match": False,
            "operation": _operation_section(flight),
            "live": {
                "phase": "STANDING BY",
                "telemetry_source": "",
                "telemetry_fresh": bool(telemetry_fresh) if telemetry_fresh is not None else None,
            },
            "units": {
                "weight": weight_unit_key(flight.get("weight_units")) or "KGS",
                "fuel": weight_unit_key(flight.get("fuel_units")) or "KGS",
                "display": display_unit,
            },
            # No active recorder yet: manual overrides from a previous flight
            # must never leak into a fresh plan's sections.
            "manual_overrides": {},
            "times": _times_section(plan, {"flight": flight}, {}),
            "weights": _weights_section(plan, {"flight": flight, "operational_snapshots": {}}, display_unit, {}, loading_progress=loading_progress),
            "fuel": _fuel_section(plan, {"flight": flight, "operational_snapshots": {}}, display_unit, {}),
            "completeness": {},
        }
        waiting["completeness"] = _completeness(waiting)
        waiting["revision"] = _revision(waiting)
        return waiting

    plan_identity = _plan_identity(plan)
    recorder_identity = _recorder_identity(source)
    matched, match_reason = _flight_match(plan_identity, recorder_identity)
    if not matched:
        return {
            "ok": True,
            "state": "mismatch",
            "revision": "0",
            "updated_utc": None,
            "reason": f"Active recorder does not match the loaded plan ({match_reason})",
            "plan_identity": plan_identity,
            "recorder_identity": recorder_identity,
            "flight_match": False,
        }

    flight = source.get("flight") if isinstance(source.get("flight"), dict) else {}
    plan_units = flight.get("fuel_units") or flight.get("weight_units")
    display_unit = _display_unit(plan_units, settings_override_unit)
    state = "complete" if completed_entry is not None else ("stale" if telemetry_fresh is False else "live")

    payload = {
        "ok": True,
        "state": state,
        "revision": "0",
        "updated_utc": _iso(None),
        "plan_identity": plan_identity,
        "recorder_identity": recorder_identity,
        "flight_match": True,
        "operation": _operation_section(flight),
        "live": {
            "phase": str(source.get("phase") or (source.get("_state") or {}).get("phase") or "UNKNOWN"),
            "telemetry_source": str(source.get("telemetry_source") or ""),
            "telemetry_fresh": bool(telemetry_fresh) if telemetry_fresh is not None else None,
        },
        "units": {"weight": weight_unit_key(flight.get("weight_units")) or "KGS", "fuel": weight_unit_key(flight.get("fuel_units")) or "KGS", "display": display_unit},
        "manual_overrides": dict(overrides),
        "times": _times_section(plan, source, overrides),
        "weights": _weights_section(plan, source, display_unit, overrides, loading_progress=loading_progress),
        "fuel": _fuel_section(plan, source, display_unit, overrides),
        "completeness": {},
    }
    payload["completeness"] = _completeness(payload)
    payload["revision"] = _revision(payload)
    payload["updated_utc"] = str(source.get("updated_utc") or "")
    return payload


def plan_from_entry(entry: dict[str, Any] | None) -> dict[str, Any]:
    """Rebuild a builder-compatible plan dict from a stored logbook entry.

    A completed entry does not retain the full normalized SimBrief payload; it
    carries the flattened plan snapshot (``entry.flight``) plus the immutable
    nested reference (``entry.flight.ofp_plan``).  This reconstructs exactly
    the keys the live builder reads (identity, scheduled times, planned block,
    fuel and weights), so the PIREP/PDF completion section can reuse the same
    ``build_live_ofp_actuals`` builder instead of duplicating the maths.

    Entries recorded before the snapshot feature simply report ``ok: False``,
    which the builder maps to the honest ``no-plan`` state.
    """
    entry = entry if isinstance(entry, dict) else {}
    flight = entry.get("flight") if isinstance(entry.get("flight"), dict) else {}
    nested = flight.get("ofp_plan") if isinstance(flight.get("ofp_plan"), dict) else {}
    identity = nested.get("identity") if isinstance(nested.get("identity"), dict) else {}
    times = nested.get("times") if isinstance(nested.get("times"), dict) else {}
    fuel = nested.get("fuel") if isinstance(nested.get("fuel"), dict) else {}
    weights = nested.get("weights") if isinstance(nested.get("weights"), dict) else {}
    return {
        "ok": bool(nested),
        "request_id": identity.get("request_id"),
        "sequence_id": identity.get("sequence_id"),
        "plan_id": identity.get("plan_id"),
        "generated_utc": identity.get("generated_utc"),
        "callsign": identity.get("callsign"),
        "origin": {"icao": identity.get("origin")},
        "destination": {"icao": identity.get("destination")},
        "aircraft": {"registration": identity.get("registration")},
        "times": times,
        "fuel": fuel,
        "weights": weights,
        "block_time_seconds": flight.get("block_time_seconds"),
        "ete_seconds": flight.get("ete_seconds"),
    }
