from __future__ import annotations

import json
import math
import os
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .settings_store import app_data_dir, load_settings
from .load_model import resolve_operation_type, load_composition, finish_load_for_operation, weight_to_kg, weight_unit_key

CAREER_FILE = "economy_career.json"
# v0.25.9: passenger-satisfaction weights resolution. Source precedence is:
#   1. meta["passenger_satisfaction_weights"]  (per-flight override)
#   2. load_settings()["integrations"]["passenger_satisfaction"]  (Settings Store)
#   3. passenger_satisfaction.DEFAULT_WEIGHTS
_SATIS_WEIGHTS: dict[str, Any] | None = None


def _opsroom_satis_weights(meta: dict[str, Any] | None) -> dict[str, Any]:
    """Resolve the passenger-satisfaction weight dict. Cached at module level so
    the settings_store lookup only fires once per process."""
    global _SATIS_WEIGHTS
    if isinstance((meta or {}).get("passenger_satisfaction_weights"), dict) and (meta or {}).get("passenger_satisfaction_weights"):
        return meta["passenger_satisfaction_weights"]
    if _SATIS_WEIGHTS is None:
        try:
            from .passenger_satisfaction import DEFAULT_WEIGHTS as _SATIS_DEFAULT
            _SATIS_WEIGHTS = (load_settings().get("integrations") or {}).get("passenger_satisfaction") or _SATIS_DEFAULT
        except Exception:
            _SATIS_WEIGHTS = {}
    return _SATIS_WEIGHTS or {}
SUPPORTED_CURRENCIES = {"EUR": "€", "USD": "$", "GBP": "£"}
STARTING_BALANCE = 250000.0
PILOT_STARTING_BALANCE = 50000.0

RANK_ORDER = [
    ("cadet", "Cadet"),
    ("junior_first_officer", "Junior First Officer"),
    ("first_officer", "First Officer"),
    ("senior_first_officer", "Senior First Officer"),
    ("captain", "Captain"),
    ("senior_captain", "Senior Captain"),
    ("training_captain", "Training Captain"),
    ("line_check_captain", "Line Check Captain"),
    ("base_captain", "Base Captain"),
    ("fleet_captain", "Fleet Captain"),
]
RANK_THRESHOLDS = {
    "relaxed": [(0, 0), (2, 4), (5, 10), (10, 20), (20, 40), (30, 70), (45, 100), (60, 150), (85, 220), (120, 300)],
    "standard": [(0, 0), (3, 5), (8, 15), (15, 30), (25, 60), (40, 100), (60, 150), (85, 220), (120, 320), (175, 450)],
    "realistic": [(0, 0), (5, 10), (15, 35), (30, 75), (60, 150), (100, 250), (150, 400), (225, 600), (325, 850), (500, 1250)],
}
PACE_MULTIPLIERS = {"relaxed": 0.65, "standard": 1.0, "realistic": 1.75}
RANK_PAY_MULTIPLIERS = {
    "cadet": 1.00,
    "junior_first_officer": 1.06,
    "first_officer": 1.14,
    "senior_first_officer": 1.22,
    "captain": 1.38,
    "senior_captain": 1.50,
    "training_captain": 1.62,
    "line_check_captain": 1.74,
    "base_captain": 1.90,
    "fleet_captain": 2.10,
}

SIM_CURRENCY_TO_USD = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27}


def _convert_major_currency(amount: float, source: str, target: str) -> float | None:
    source = str(source or "").upper()
    target = str(target or "").upper()
    if source == target:
        return amount
    if source not in SIM_CURRENCY_TO_USD or target not in SIM_CURRENCY_TO_USD:
        return None
    return amount * SIM_CURRENCY_TO_USD[source] / SIM_CURRENCY_TO_USD[target]


HUB_AIRPORTS = {
    "EDDF", "EGLL", "EHAM", "LFPG", "LEMD", "LEBL", "LIRF", "LOWW", "LSZH", "EKCH", "ESSA", "ENGM", "EIDW", "EPWA",
    "KATL", "KLAX", "KJFK", "KORD", "KDFW", "KDEN", "KSFO", "KMIA", "KSEA", "KBOS", "CYYZ", "CYVR", "MMMX",
    "OMDB", "OTHH", "OEJN", "VIDP", "VABB", "WSSS", "VHHH", "RJTT", "RKSI", "YSSY", "NZAA",
    "SBGR", "SCEL", "SKBO", "MPTO", "SAEZ", "FACT", "FAOR",
}


def finance_enabled() -> bool:
    """Return the app-wide Finance & Career feature state.

    The career file is intentionally left untouched when disabled so existing
    balances and history return exactly as they were if the user re-enables it.
    """
    try:
        interface = load_settings().get("interface", {})
        return bool(interface.get("finance_career_enabled", True))
    except Exception:
        return True


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _path() -> Path:
    return app_data_dir() / CAREER_FILE


def _num(value: Any) -> float | None:
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def _safe_text(value: Any, limit: int = 80) -> str:
    return str(value or "").strip()[:limit]


def _icao(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("icao", "ident", "code"):
            txt = _safe_text(value.get(key), 4).upper()
            if txt:
                return txt
        return ""
    txt = _safe_text(value, 4).upper()
    return txt if re_fullmatch_icao(txt) else txt


def re_fullmatch_icao(value: str) -> bool:
    return len(str(value or "")) == 4 and str(value or "").isalnum()


def _default_career(currency: str = "EUR", pace: str = "standard") -> dict[str, Any]:
    currency = str(currency or "EUR").upper()
    if currency not in SUPPORTED_CURRENCIES:
        currency = "EUR"
    pace = str(pace or "standard").lower()
    if pace not in PACE_MULTIPLIERS:
        pace = "standard"
    return {
        "ok": True,
        "enabled": True,
        "created_utc": _utc(),
        "updated_utc": _utc(),
        "currency": currency,
        "symbol": SUPPORTED_CURRENCIES[currency],
        "progression_pace": pace,
        "mode": "career",
        "fare_settings": {
            "auto": True,
            "economy_fare": None,
            "business_fare": None,
            "first_fare": None,
            "cargo_rate": None,
            "economy_pct": 90,
            "business_pct": 10,
            "first_pct": 0,
        },
        "airline_balance": STARTING_BALANCE,
        "pilot_balance": PILOT_STARTING_BALANCE,
        "totals": {
            "airline_revenue": 0.0,
            "airline_costs": 0.0,
            "airline_profit": 0.0,
            "gsx_service_costs": 0.0,
            "estimated_service_costs": 0.0,
            "fuel_costs": 0.0,
            "pilot_pay": 0.0,
            "xp": 0,
            "finance_flights": 0,
        },
        "ledger": [],
        "version": 1,
    }


def _merge_career(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = _default_career((raw or {}).get("currency", "EUR"), (raw or {}).get("progression_pace", "standard"))
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k == "totals" and isinstance(v, dict):
                base["totals"].update(v)
            elif k == "fare_settings" and isinstance(v, dict):
                base.setdefault("fare_settings", {}).update(v)
            elif k == "ledger" and isinstance(v, list):
                base["ledger"] = v[-1500:]
            else:
                base[k] = v
    base["currency"] = str(base.get("currency") or "EUR").upper()
    if base["currency"] not in SUPPORTED_CURRENCIES:
        base["currency"] = "EUR"
    base["symbol"] = SUPPORTED_CURRENCIES[base["currency"]]
    base["progression_pace"] = str(base.get("progression_pace") or "standard").lower()
    if base["progression_pace"] not in PACE_MULTIPLIERS:
        base["progression_pace"] = "standard"
    for key in ("airline_balance", "pilot_balance"):
        fallback = STARTING_BALANCE if key == "airline_balance" else PILOT_STARTING_BALANCE
        base[key] = float(_num(base.get(key)) if _num(base.get(key)) is not None else fallback)
    return base


def load_career() -> dict[str, Any]:
    path = _path()
    if not path.exists():
        return _default_career()
    try:
        return _merge_career(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return _default_career()


def save_career(career: dict[str, Any]) -> dict[str, Any]:
    clean = _merge_career(career)
    clean["updated_utc"] = _utc()
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="economy-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(clean, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        try:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        except OSError:
            pass
    return clean


def _clean_fare_settings(raw: dict[str, Any] | None, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = dict(fallback or {})
    if not isinstance(raw, dict):
        return settings
    settings["auto"] = bool(raw.get("auto", settings.get("auto", True)))
    for key in ("economy_fare", "business_fare", "first_fare", "cargo_rate"):
        val = _num(raw.get(key))
        settings[key] = round(max(0.0, val), 2) if val is not None else settings.get(key)
    for key in ("economy_pct", "business_pct", "first_pct"):
        val = _num(raw.get(key))
        if val is not None:
            settings[key] = int(max(0, min(100, round(val))))
    total = int(settings.get("economy_pct") or 0) + int(settings.get("business_pct") or 0) + int(settings.get("first_pct") or 0)
    if total <= 0:
        settings.update({"economy_pct": 90, "business_pct": 10, "first_pct": 0})
    elif total != 100:
        # Normalize gently while preserving user intent.
        settings["economy_pct"] = int(round((int(settings.get("economy_pct") or 0) / total) * 100))
        settings["business_pct"] = int(round((int(settings.get("business_pct") or 0) / total) * 100))
        settings["first_pct"] = max(0, 100 - int(settings["economy_pct"]) - int(settings["business_pct"]))
    return settings


def configure(currency: str = "EUR", progression_pace: str = "standard", reset: bool = False, fare_settings: dict[str, Any] | None = None) -> dict[str, Any]:
    if reset or not _path().exists():
        career = _default_career(currency, progression_pace)
        career["fare_settings"] = _clean_fare_settings(fare_settings, career.get("fare_settings"))
        return save_career(career)
    career = load_career()
    if not career.get("ledger"):
        career["currency"] = str(currency or career.get("currency") or "EUR").upper()
        career["progression_pace"] = str(progression_pace or career.get("progression_pace") or "standard").lower()
    else:
        # Keep currency/balance stable once the career has posted ledger entries.
        career["progression_pace"] = str(progression_pace or career.get("progression_pace") or "standard").lower()
    career["fare_settings"] = _clean_fare_settings(fare_settings, career.get("fare_settings"))
    return save_career(career)


def _route_distance_nm(meta: dict[str, Any]) -> float:
    metrics = meta.get("metrics") if isinstance(meta.get("metrics"), dict) else {}
    flight = meta.get("flight") if isinstance(meta.get("flight"), dict) else {}
    return float(_num(metrics.get("distance_nm")) or _num(flight.get("distance_nm")) or 300.0)


def _block_hours(meta: dict[str, Any]) -> float:
    dur = meta.get("durations") if isinstance(meta.get("durations"), dict) else {}
    return max(0.0, float(_num(dur.get("block_seconds")) or _num(dur.get("airborne_seconds")) or 3600.0) / 3600.0)


def _passenger_count(meta: dict[str, Any]) -> int:
    flight = meta.get("flight") if isinstance(meta.get("flight"), dict) else {}
    for key in ("passengers", "pax", "pax_count"):
        n = _num(flight.get(key))
        if n is not None:
            return int(round(max(0.0, n)))
    # Passenger data is genuinely absent.  An explicit freighter/ferry never
    # receives a capacity estimate (a 777F must never become 280 passengers).
    resolution = resolve_operation_type(flight, flight.get("operation_type_requested") or "auto")
    if resolution["resolved"] in ("freighter", "ferry"):
        return 0
    aircraft = " ".join(str(x or "") for x in (flight.get("aircraft_icao"), (meta.get("aircraft") or {}).get("title"))).upper()
    if any(code in aircraft for code in ("A388", "A380", "B77", "777", "B78", "787", "A35", "A350", "A33", "A340")):
        return 280
    if any(code in aircraft for code in ("A32", "A320", "A321", "B73", "737")):
        return 150
    return 90


def _operation_resolution(meta: dict[str, Any]) -> dict[str, Any]:
    flight = meta.get("flight") if isinstance(meta.get("flight"), dict) else {}
    return resolve_operation_type(flight, flight.get("operation_type_requested") or "auto")


def _commercial_freight_kg(meta: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """Return (commercial freight kg, resolved load composition).

    Only revenue-generating freight counts.  Checked passenger baggage and the
    combined BAGS/CARGO hold are never charged as freight on passenger ops.
    """
    flight = meta.get("flight") if isinstance(meta.get("flight"), dict) else {}
    resolution = _operation_resolution(meta)
    load = finish_load_for_operation(load_composition(flight), resolution)
    value = load.get("commercial_freight_weight")
    if value is None:
        return 0.0, load
    units = load.get("weight_units") or weight_unit_key(flight.get("weight_units"))
    kg = weight_to_kg(value, units).get("normalized_kg")
    return (max(0.0, kg) if kg is not None else 0.0), load


def _cargo_kg(meta: dict[str, Any]) -> float:
    flight = meta.get("flight") if isinstance(meta.get("flight"), dict) else {}
    cargo = _num(flight.get("cargo")) or _num(flight.get("planned_cargo")) or 0.0
    units = str(flight.get("weight_units") or "").upper()
    if cargo and units in {"LBS", "LB"}:
        return cargo * 0.45359237
    return cargo


def _airport_tier(origin: str, destination: str) -> str:
    if origin in HUB_AIRPORTS and destination in HUB_AIRPORTS:
        return "high"
    if origin in HUB_AIRPORTS or destination in HUB_AIRPORTS:
        return "medium-high"
    return "medium"


def _distance_band(distance_nm: float) -> str:
    if distance_nm < 500:
        return "short"
    if distance_nm < 1800:
        return "medium"
    if distance_nm < 3600:
        return "long"
    return "ultra"


def _base_economy_fare(distance_nm: float) -> float:
    band = _distance_band(distance_nm)
    if band == "short":
        return 55.0 + distance_nm * 0.12
    if band == "medium":
        return 105.0 + distance_nm * 0.16
    if band == "long":
        return 260.0 + distance_nm * 0.13
    return 480.0 + distance_nm * 0.10


def _demand_multiplier(tier: str, distance_nm: float) -> float:
    mult = {"high": 1.16, "medium-high": 1.08, "medium": 1.0, "low": 0.88}.get(tier, 1.0)
    if 250 <= distance_nm <= 1800:
        mult += 0.04
    return mult


def _cabin_split(meta: dict[str, Any], fare_settings: dict[str, Any] | None = None) -> dict[str, int]:
    pax = _passenger_count(meta)
    settings = fare_settings or {}
    if any(_num(settings.get(k)) is not None for k in ("economy_pct", "business_pct", "first_pct")):
        econ_pct = max(0, int(settings.get("economy_pct") or 0))
        bus_pct = max(0, int(settings.get("business_pct") or 0))
        first_pct = max(0, int(settings.get("first_pct") or 0))
        total_pct = max(1, econ_pct + bus_pct + first_pct)
        business = round(pax * bus_pct / total_pct)
        first = round(pax * first_pct / total_pct)
    else:
        distance = _route_distance_nm(meta)
        if distance >= 1800 or pax >= 220:
            business = round(pax * 0.14)
            first = round(pax * 0.03)
        else:
            business = round(pax * 0.10)
            first = 0
    economy = max(0, pax - business - first)
    return {"economy": economy, "business": business, "first": first, "total": pax}


def _invoice_in_career_currency(item: dict[str, Any], career_currency: str) -> dict[str, Any] | None:
    career_currency = str(career_currency or "EUR").upper()
    source_currency = str(item.get("currency") or "").upper()
    amount = _num(item.get("amount"))
    approx_amount = _num(item.get("approx_amount"))
    approx_currency = str(item.get("approx_currency") or "").upper()
    if approx_amount is not None and approx_currency == career_currency:
        converted = approx_amount
    elif approx_amount is not None and approx_currency:
        # GSX receipts can use local currencies outside the career currency
        # set (for example GIP/GI£) while also supplying a USD reference.
        # Prefer that audited reference and convert it to the selected career
        # currency rather than dropping a valid receipt as unsupported.
        converted = _convert_major_currency(approx_amount, approx_currency, career_currency)
    elif amount is not None and source_currency:
        converted = _convert_major_currency(amount, source_currency, career_currency)
    else:
        converted = _num(item.get("converted_amount") or item.get("amount_home"))
    if converted is None or converted < 0:
        return None
    return {
        "operator": _safe_text(item.get("operator") or item.get("source") or "GSX"),
        "airline": _safe_text(item.get("airline"), 100),
        "service": _safe_text(item.get("service") or item.get("category") or "Ground Handling"),
        "category": _safe_text(item.get("category") or item.get("service") or "Handling"),
        "phase": str(item.get("phase") or "unknown").lower(),
        "airport": _safe_text(item.get("airport"), 4).upper(),
        "tail": _safe_text(item.get("tail"), 16).upper(),
        "amount": round(converted, 2),
        "source_currency": source_currency or career_currency,
        "source_amount": round(amount, 2) if amount is not None else None,
        "display_amount": _safe_text(item.get("display_amount"), 60),
        "approx_currency": approx_currency,
        "approx_amount": round(approx_amount, 2) if approx_amount is not None else None,
        "line_items": item.get("line_items") if isinstance(item.get("line_items"), list) else [],
        "taxes": item.get("taxes") if isinstance(item.get("taxes"), list) else [],
        "url": _safe_text(item.get("url"), 240),
        "issued_utc": _safe_text(item.get("issued_utc") or item.get("modified_utc"), 40),
    }


def _service_cost(meta: dict[str, Any], pax: int, cargo_kg: float, tier: str, currency: str) -> dict[str, Any]:
    """Return departure and arrival ground costs without double-counting fuel."""
    invoices: list[dict[str, Any]] = []
    for raw in (meta.get("gsx_invoices") or meta.get("ground_invoices") or []):
        if isinstance(raw, dict):
            converted = _invoice_in_career_currency(raw, currency)
            if converted:
                invoices.append(converted)
    ground = [item for item in invoices if str(item.get("category") or item.get("service") or "").lower() != "fuel"]
    fuel = [item for item in invoices if str(item.get("category") or item.get("service") or "").lower() == "fuel"]
    dep_actual = round(sum(item["amount"] for item in ground if item.get("phase") in {"departure", "unknown"}), 2)
    arr_actual = round(sum(item["amount"] for item in ground if item.get("phase") == "arrival"), 2)
    estimate_total = round(({"high": 820, "medium-high": 680, "medium": 520, "low": 380}.get(tier, 520) + pax * 5.2 + cargo_kg * 0.09), 2)
    if dep_actual > 0 and arr_actual > 0:
        dep, arr = dep_actual, arr_actual
        dep_source = arr_source = "gsx"
    elif dep_actual > 0:
        dep = dep_actual
        arr = round(max(220.0, dep_actual * 0.50), 2)
        dep_source, arr_source = "gsx", "estimated-from-departure"
    elif arr_actual > 0:
        arr = arr_actual
        dep = round(max(350.0, arr_actual * 1.65), 2)
        dep_source, arr_source = "estimated-from-arrival", "gsx"
    else:
        dep = round(estimate_total * 0.62, 2)
        arr = round(estimate_total - dep, 2)
        dep_source = arr_source = "ops-room-estimate"
    return {
        "total": round(dep + arr, 2),
        "departure": dep,
        "arrival": arr,
        "departure_source": dep_source,
        "arrival_source": arr_source,
        "source": "gsx" if dep_source == arr_source == "gsx" else "mixed" if "gsx" in {dep_source, arr_source} else "estimated",
        "fuel_invoice_total": round(sum(item["amount"] for item in fuel), 2),
        "invoices": invoices,
    }

def current_rank(completed_pireps: int, block_hours: float, pace: str = "standard") -> dict[str, Any]:
    pace_key = str(pace or "standard").lower()
    thresholds = RANK_THRESHOLDS.get(pace_key) or RANK_THRESHOLDS["standard"]
    ladder = []
    for (key, label), (pireps, hours) in zip(RANK_ORDER, thresholds):
        ladder.append({"key": key, "label": label, "pireps": int(pireps), "block_hours": int(hours), "pay_multiplier": RANK_PAY_MULTIPLIERS.get(key, 1.0)})
    achieved = ladder[0]
    for row in ladder:
        if completed_pireps >= row["pireps"] and block_hours >= row["block_hours"]:
            achieved = row
    next_rank = None
    for row in ladder:
        if row["key"] == achieved["key"]:
            continue
        if completed_pireps < row["pireps"] or block_hours < row["block_hours"]:
            next_rank = row
            break
    progress = {"pireps": completed_pireps, "block_hours": round(block_hours, 1)}
    if next_rank:
        progress.update({"next_pireps": next_rank["pireps"], "next_block_hours": next_rank["block_hours"], "percent": round(min(1.0, min(completed_pireps / max(1, next_rank["pireps"]), block_hours / max(1, next_rank["block_hours"]))) * 100, 1)})
    else:
        progress.update({"next_pireps": completed_pireps, "next_block_hours": round(block_hours, 1), "percent": 100.0})
    return {"current": achieved, "next": next_rank, "progress": progress, "ladder": ladder}


def estimate_statement(meta: dict[str, Any], career: dict[str, Any] | None = None, previous_entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if not finance_enabled():
        return {"ok": False, "enabled": False, "disabled": True, "reason": "Finance & Career is disabled in Settings"}
    career = _merge_career(career or load_career())
    flight = meta.get("flight") if isinstance(meta.get("flight"), dict) else {}
    origin = _icao(flight.get("origin"))
    destination = _icao(flight.get("destination"))
    distance = max(1.0, _route_distance_nm(meta))
    block = max(0.25, _block_hours(meta))
    fare_settings = _clean_fare_settings((meta.get("finance_options") or {}).get("fare_settings") if isinstance(meta.get("finance_options"), dict) else None, career.get("fare_settings"))
    resolution = _operation_resolution(meta)
    operation = {
        "requested": resolution["requested"],
        "resolved": resolution["resolved"],
        "reason": resolution["reason"],
        "confidence": resolution["confidence"],
    }
    freight_kg, load = _commercial_freight_kg(meta)
    cargo_hold_total = load.get("cargo_hold_total")
    commercial_freight = load.get("commercial_freight_weight")
    is_passenger_operation = operation["resolved"] in ("passenger", "combi")
    pax_split = _cabin_split(meta, fare_settings) if is_passenger_operation else {"economy": 0, "business": 0, "first": 0, "total": 0}
    pax = pax_split["total"]
    cargo = max(0.0, _cargo_kg(meta))
    tier = _airport_tier(origin, destination)
    demand = _demand_multiplier(tier, distance)
    econ_fare = _base_economy_fare(distance) * demand
    auto_fares = bool(fare_settings.get("auto", True))
    fares = {"economy": round(econ_fare, 2), "business": round(econ_fare * 3.2, 2), "first": round(econ_fare * 6.5, 2)}
    if not auto_fares:
        for key, default in (("economy", fares["economy"]), ("business", fares["business"]), ("first", fares["first"])):
            custom = _num(fare_settings.get(f"{key}_fare"))
            if custom is not None and custom > 0:
                fares[key] = round(custom, 2)
    passenger_revenue = round(pax_split["economy"] * fares["economy"] + pax_split["business"] * fares["business"] + pax_split["first"] * fares["first"], 2) if is_passenger_operation else 0.0
    cargo_rate = _num(fare_settings.get("cargo_rate"))
    effective_freight_rate = (0.18 + distance * 0.00055) * demand if (auto_fares or not cargo_rate) else cargo_rate
    cargo_revenue = round(freight_kg * effective_freight_rate, 2)
    fuel_lb = _num((meta.get("fuel") or {}).get("used_lb")) or _num(flight.get("planned_trip_fuel")) or distance * 11.0
    fuel_kg = max(0.0, fuel_lb * 0.45359237)
    modeled_fuel_cost = round(fuel_kg * 0.86, 2)
    service_costs = _service_cost(meta, pax, cargo, tier, career["currency"])
    fuel_cost = service_costs["fuel_invoice_total"] if service_costs["fuel_invoice_total"] > 0 else modeled_fuel_cost
    service_cost = service_costs["total"]
    service_source = service_costs["source"]
    invoices = service_costs["invoices"]
    airport_fee = round(({"high": 1200, "medium-high": 900, "medium": 650, "low": 420}.get(tier, 650) + pax * 1.6), 2)
    crew_maintenance = round(450 + block * 430 + distance * 0.28, 2)
    airline_costs = round(fuel_cost + service_cost + airport_fee + crew_maintenance, 2)
    satisfaction_applicable = is_passenger_operation
    entries = previous_entries or []
    completed = sum(1 for e in entries if (e.get("state") == "COMPLETE" or e.get("status") == "COMPLETE"))
    block_hours_total = sum((_num((e.get("durations") or {}).get("block_seconds")) or 0.0) / 3600.0 for e in entries)
    rank = current_rank(completed, block_hours_total, career.get("progression_pace"))
    pay_mult = float(rank.get("current", {}).get("pay_multiplier") or 1.0)
    score = _num((meta.get("debrief") or {}).get("score")) or 75.0
    # Career pay is deliberately meaningful: fixed duty pay plus block-time
    # and distance components, then the existing rank multiplier.
    pilot_base = 225 + block * 240 + distance * 0.09
    pilot_bonus = 0.0
    if score >= 85:
        pilot_bonus += 110
    elif score >= 75:
        pilot_bonus += 60
    rate = abs(_num((meta.get("metrics") or {}).get("landing_rate_fpm")) or 0.0)
    if 0 < rate <= 250:
        pilot_bonus += 70
    pilot_pay = round((pilot_base + pilot_bonus) * pay_mult, 2)
    xp = int(max(35, min(175, round(score + (15 if distance < 500 else 30 if distance < 1800 else 45) + (10 if score >= 80 else 0)))))
    # v0.25.9+: passenger satisfaction revenue weighting applies to passenger
    # revenue ONLY.  Commercial freight revenue, reimbursements and unrelated
    # income are never satisfaction-scaled, and freighter/ferry operations
    # have no passenger satisfaction at all.
    _satis_mult = 1.0
    _satis_rep = 0
    try:
        from .passenger_satisfaction import compute as _satis_compute
        _satis_in = (meta or {}).get('passenger_satisfaction')
        if not isinstance(_satis_in, dict) or 'score' not in _satis_in:
            _satis_in = _satis_compute(
                {
                    'departure_delay_minutes': (meta or {}).get('departure_delay_minutes'),
                    'arrival_delay_minutes': (meta or {}).get('arrival_delay_minutes'),
                    'emergency_events': (meta or {}).get('emergency_events') or (meta or {}).get('emergency_count'),
                },
                (meta or {}).get('pirep') or {},
                _opsroom_satis_weights(meta),
            )
        _satis_mult = float(_satis_in.get('revenue_multiplier') or 1.0)
        _satis_rep = int(_satis_in.get('reputation_delta') or 0)
        _satis_out = {**_satis_in,
                      'applied_revenue_multiplier': _satis_mult if satisfaction_applicable else 1.0,
                      'applied_reputation_delta': _satis_rep}
    except Exception as _satis_e:
        _satis_out = {'error': f"{type(_satis_e).__name__}: {_satis_e}"}
    if not satisfaction_applicable:
        _satis_mult = 1.0
        _satis_rep = 0
    passenger_revenue_before = round(passenger_revenue, 2)
    passenger_revenue_after = round(passenger_revenue * _satis_mult, 2)
    airline_revenue = round(passenger_revenue_after + cargo_revenue, 2)
    airline_profit = round(airline_revenue - airline_costs, 2)

    return {
        "ok": True,
        "currency": career["currency"],
        "symbol": career["symbol"],
        "route": {"origin": origin, "destination": destination, "distance_nm": round(distance, 1), "demand": tier, "distance_band": _distance_band(distance)},
        "operation": operation,
        "load_breakdown_source": str(load.get("load_breakdown_source") or "combined-simbrief-cargo"),
        "satisfaction_applicable": satisfaction_applicable,
        "passengers": pax_split,
        "fare_settings": fare_settings,
        "fares": fares,
        "cargo_kg": round(freight_kg, 1),
        "cargo_hold_total": round(cargo_hold_total, 1) if cargo_hold_total is not None else None,
        "commercial_freight_weight": round(commercial_freight, 1) if commercial_freight is not None else None,
        "passenger_revenue_before_satisfaction": passenger_revenue_before,
        "passenger_revenue_after_satisfaction": passenger_revenue_after,
        "commercial_freight_revenue": round(cargo_revenue, 2),
        "total_revenue": round(airline_revenue, 2),
        "effective_freight_rate_per_kg": round(effective_freight_rate, 4),
        "airline": {
            "revenue": {"passenger": passenger_revenue_after, "cargo": round(cargo_revenue, 2), "total": round(airline_revenue, 2)},
            "costs": {"fuel": fuel_cost, "fuel_source": "gsx" if service_costs["fuel_invoice_total"] > 0 else "ops-room-estimate", "ground_services": service_cost, "ground_services_source": service_source, "ground_services_departure": service_costs["departure"], "ground_services_arrival": service_costs["arrival"], "ground_services_departure_source": service_costs["departure_source"], "ground_services_arrival_source": service_costs["arrival_source"], "airport_fees": airport_fee, "crew_maintenance": crew_maintenance, "total": airline_costs},
            "profit": airline_profit,
            "invoices": invoices,
        },
        "pilot": {"pay": pilot_pay, "xp": xp, "rank": rank.get("current")},
        "passenger_satisfaction": _satis_out,
        "reputation_delta": _satis_rep,
    }


def post_flight(meta: dict[str, Any], previous_entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if not finance_enabled():
        meta.pop("finance", None)
        return {"ok": False, "enabled": False, "disabled": True, "reason": "Finance & Career is disabled in Settings"}
    career = load_career()
    flight_id = str(meta.get("id") or "")
    # Never post the same flight twice. Return existing statement if present.
    for item in career.get("ledger") or []:
        if item.get("flight_id") == flight_id:
            return meta.get("finance") if isinstance(meta.get("finance"), dict) else item.get("statement", {})
    statement = estimate_statement(meta, career, previous_entries)
    opening_airline = float(career.get("airline_balance") or STARTING_BALANCE)
    opening_pilot = float(career.get("pilot_balance") if _num(career.get("pilot_balance")) is not None else PILOT_STARTING_BALANCE)
    statement["opening_balance"] = {"airline": round(opening_airline, 2), "pilot": round(opening_pilot, 2)}
    closing_airline = opening_airline + float(statement["airline"]["profit"])
    closing_pilot = opening_pilot + float(statement["pilot"]["pay"])
    statement["closing_balance"] = {"airline": round(closing_airline, 2), "pilot": round(closing_pilot, 2)}
    career["airline_balance"] = closing_airline
    career["pilot_balance"] = closing_pilot
    totals = career.setdefault("totals", {})
    totals["airline_revenue"] = round(float(totals.get("airline_revenue") or 0) + float(statement["airline"]["revenue"]["total"]), 2)
    totals["airline_costs"] = round(float(totals.get("airline_costs") or 0) + float(statement["airline"]["costs"]["total"]), 2)
    totals["airline_profit"] = round(float(totals.get("airline_profit") or 0) + float(statement["airline"]["profit"]), 2)
    if statement["airline"]["costs"].get("ground_services_source") == "gsx":
        totals["gsx_service_costs"] = round(float(totals.get("gsx_service_costs") or 0) + float(statement["airline"]["costs"]["ground_services"]), 2)
    else:
        totals["estimated_service_costs"] = round(float(totals.get("estimated_service_costs") or 0) + float(statement["airline"]["costs"]["ground_services"]), 2)
    totals["fuel_costs"] = round(float(totals.get("fuel_costs") or 0) + float(statement["airline"]["costs"]["fuel"]), 2)
    totals["pilot_pay"] = round(float(totals.get("pilot_pay") or 0) + float(statement["pilot"]["pay"]), 2)
    totals["xp"] = int(totals.get("xp") or 0) + int(statement["pilot"].get("xp") or 0)
    totals["finance_flights"] = int(totals.get("finance_flights") or 0) + 1
    career.setdefault("ledger", []).append({"flight_id": flight_id, "time": _utc(), "callsign": (meta.get("flight") or {}).get("callsign"), "route": statement.get("route"), "statement": statement})
    career["ledger"] = career["ledger"][-1500:]
    save_career(career)
    meta["finance"] = statement
    return statement


def reconcile_flight(meta: dict[str, Any], previous_entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Reconcile a posted flight when late GSX receipts are discovered.

    Only operational costs and attached invoices are refreshed. Passenger/cargo
    revenue, pilot pay, XP and rank remain exactly as originally posted. Career
    balances and totals receive the cost/profit delta once, keyed by flight id.
    """
    if not finance_enabled():
        return {"ok": False, "enabled": False, "reason": "Finance & Career is disabled in Settings"}
    flight_id = str(meta.get("id") or "")
    if not flight_id:
        return {"ok": False, "reason": "Flight id is missing"}
    career = load_career()
    ledger = career.get("ledger") if isinstance(career.get("ledger"), list) else []
    ledger_index = next((index for index, item in enumerate(ledger) if str(item.get("flight_id") or "") == flight_id), None)
    if ledger_index is None:
        return post_flight(meta, previous_entries)

    old_statement = ledger[ledger_index].get("statement") if isinstance(ledger[ledger_index], dict) else None
    if not isinstance(old_statement, dict):
        return {"ok": False, "reason": "Existing Finance statement is unavailable"}
    fresh = estimate_statement(meta, career, previous_entries)
    if not fresh.get("ok"):
        return fresh

    old_airline = old_statement.get("airline") if isinstance(old_statement.get("airline"), dict) else {}
    old_costs = old_airline.get("costs") if isinstance(old_airline.get("costs"), dict) else {}
    fresh_airline = fresh.get("airline") if isinstance(fresh.get("airline"), dict) else {}
    fresh_costs = fresh_airline.get("costs") if isinstance(fresh_airline.get("costs"), dict) else {}

    statement = deepcopy(old_statement)
    statement.setdefault("airline", {})["costs"] = deepcopy(fresh_costs)
    statement["airline"]["invoices"] = deepcopy(fresh_airline.get("invoices") or [])
    revenue_total = float(_num(((statement.get("airline") or {}).get("revenue") or {}).get("total")) or 0.0)
    new_cost_total = float(_num(fresh_costs.get("total")) or 0.0)
    old_cost_total = float(_num(old_costs.get("total")) or 0.0)
    old_profit = float(_num(old_airline.get("profit")) or (revenue_total - old_cost_total))
    new_profit = round(revenue_total - new_cost_total, 2)
    statement["airline"]["profit"] = new_profit
    statement["reconciled_utc"] = _utc()
    statement["reconciliation_reason"] = "Late GSX service receipts"

    opening = statement.get("opening_balance") if isinstance(statement.get("opening_balance"), dict) else {}
    closing = statement.get("closing_balance") if isinstance(statement.get("closing_balance"), dict) else {}
    opening_airline = float(_num(opening.get("airline")) or (float(career.get("airline_balance") or 0.0) - old_profit))
    statement["closing_balance"] = {
        "airline": round(opening_airline + new_profit, 2),
        "pilot": round(float(_num(closing.get("pilot")) or _num(opening.get("pilot")) or career.get("pilot_balance") or 0.0), 2),
    }

    profit_delta = new_profit - old_profit
    cost_delta = new_cost_total - old_cost_total
    career["airline_balance"] = round(float(career.get("airline_balance") or 0.0) + profit_delta, 2)
    totals = career.setdefault("totals", {})
    totals["airline_costs"] = round(float(totals.get("airline_costs") or 0.0) + cost_delta, 2)
    totals["airline_profit"] = round(float(totals.get("airline_profit") or 0.0) + profit_delta, 2)
    totals["fuel_costs"] = round(
        float(totals.get("fuel_costs") or 0.0)
        + float(_num(fresh_costs.get("fuel")) or 0.0)
        - float(_num(old_costs.get("fuel")) or 0.0),
        2,
    )

    old_ground = float(_num(old_costs.get("ground_services")) or 0.0)
    new_ground = float(_num(fresh_costs.get("ground_services")) or 0.0)
    old_source = str(old_costs.get("ground_services_source") or "").lower()
    new_source = str(fresh_costs.get("ground_services_source") or "").lower()
    old_bucket = "gsx_service_costs" if old_source == "gsx" else "estimated_service_costs"
    new_bucket = "gsx_service_costs" if new_source == "gsx" else "estimated_service_costs"
    totals[old_bucket] = round(max(0.0, float(totals.get(old_bucket) or 0.0) - old_ground), 2)
    totals[new_bucket] = round(float(totals.get(new_bucket) or 0.0) + new_ground, 2)

    ledger[ledger_index]["statement"] = statement
    ledger[ledger_index]["reconciled_utc"] = statement["reconciled_utc"]
    career["ledger"] = ledger[-1500:]
    save_career(career)
    meta["finance"] = statement
    return statement


def summary(entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if not finance_enabled():
        return {"ok": True, "enabled": False, "disabled": True, "reason": "Finance & Career is disabled in Settings", "ledger": []}
    career = load_career()
    entries = entries or []
    completed = sum(1 for e in entries if (e.get("state") == "COMPLETE" or e.get("status") == "COMPLETE"))
    block_hours = sum((_num((e.get("durations") or {}).get("block_seconds")) or 0.0) / 3600.0 for e in entries)
    rank = current_rank(completed, block_hours, career.get("progression_pace"))
    totals = deepcopy(career.get("totals") or {})
    finance_flights = int(totals.get("finance_flights") or 0)
    avg_profit = (float(totals.get("airline_profit") or 0.0) / finance_flights) if finance_flights else 0.0
    return {
        "ok": True,
        "enabled": True,
        "career": career,
        "currency": career["currency"],
        "symbol": career["symbol"],
        "airline_balance": round(float(career.get("airline_balance") or 0.0), 2),
        "pilot_balance": round(float(career.get("pilot_balance") or 0.0), 2),
        "totals": totals,
        "average_profit_per_flight": round(avg_profit, 2),
        "rank": rank,
        "ledger": list(reversed(career.get("ledger") or []))[:80],
    }


def public_status(entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    data = summary(entries)
    # Keep the API compact; no private data here, just career/economy stats.
    return data
