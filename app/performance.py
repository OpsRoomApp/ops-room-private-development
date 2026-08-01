from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA = Path(__file__).resolve().parent / "data" / "performance_profiles.json"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(str(value).replace(",", ""))
    except Exception:
        return default


@lru_cache(maxsize=1)
def database() -> dict[str, Any]:
    try:
        return json.loads(_DATA.read_text(encoding="utf-8"))
    except Exception:
        return {"profiles": []}


def profiles() -> dict[str, Any]:
    db = database()
    items = []
    for p in db.get("profiles", []):
        items.append({
            "id": p.get("id"),
            "icao": p.get("icao"),
            "name": p.get("name"),
            "summary": p.get("summary", ""),
            "weights": p.get("weights", {}),
            "takeoff_flaps": [x.get("label") for x in p.get("takeoff", {}).get("flaps", [])],
            "landing_flaps": [x.get("label") for x in p.get("landing", {}).get("flaps", [])],
        })
    return {"ok": True, "count": len(items), "profiles": items, "source": db.get("source", "OPS ROOM")}


def _norm_key(value: Any) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def _profile(profile_id: str | None) -> dict[str, Any]:
    data = database().get("profiles", [])
    if not data:
        raise ValueError("No aircraft performance profiles are available")
    raw_key = str(profile_id or "").strip()
    key = _norm_key(raw_key)
    if key:
        # Exact ID / ICAO / name match first.
        for p in data:
            values = [_norm_key(p.get("id")), _norm_key(p.get("icao")), _norm_key(p.get("name"))]
            if key in values:
                return p
        # Common user input such as A320 should match A320 CEO before falling back.
        for p in data:
            icao = _norm_key(p.get("icao"))
            if icao.startswith(key) or key.startswith(icao):
                return p
        for p in data:
            haystack = _norm_key(" ".join(str(p.get(k) or "") for k in ("id", "icao", "name")))
            if key and key in haystack:
                return p
        raise ValueError(f"No performance profile matches {raw_key!r}")
    return data[0]


def _interp(points: list[dict[str, Any]], x: float, xkey: str, ykey: str) -> float:
    pts = sorted([(float(p[xkey]), float(p[ykey])) for p in points if p.get(xkey) is not None and p.get(ykey) is not None])
    if not pts:
        raise ValueError("Profile does not contain usable performance points")
    if x <= pts[0][0]:
        x0, y0 = pts[0]
        x1, y1 = pts[1] if len(pts) > 1 else pts[0]
    elif x >= pts[-1][0]:
        x0, y0 = pts[-2] if len(pts) > 1 else pts[-1]
        x1, y1 = pts[-1]
    else:
        for a, b in zip(pts, pts[1:]):
            if a[0] <= x <= b[0]:
                x0, y0 = a
                x1, y1 = b
                break
    if x1 == x0:
        return y0
    return y0 + (x - x0) * (y1 - y0) / (x1 - x0)


def _isa_temp_c(elevation_ft: float) -> float:
    return 15.0 - 1.98 * (elevation_ft / 1000.0)


def _wind_components(runway_heading: float, wind_dir: float, wind_speed: float) -> tuple[float, float]:
    if wind_speed <= 0:
        return 0.0, 0.0
    diff = math.radians((wind_dir - runway_heading + 180) % 360 - 180)
    head = wind_speed * math.cos(diff)
    cross = abs(wind_speed * math.sin(diff))
    return head, cross


def _condition_factor(condition: str, landing: bool = False) -> float:
    c = str(condition or "dry").lower()
    if "contam" in c or "snow" in c or "slush" in c or "ice" in c or "rcc 3" in c or "rcc 2" in c:
        return 1.38 if landing else 1.30
    if "wet" in c or "frost" in c or "damp" in c or "rcc 5" in c:
        return 1.18 if landing else 1.12
    return 1.0


def _flap_factor(flaps: list[dict[str, Any]], selected: str, takeoff: bool) -> float:
    if not flaps:
        return 1.0
    selected = str(selected or "").strip().upper()
    item = None
    if selected:
        for f in flaps:
            if str(f.get("label", "")).strip().upper() == selected:
                item = f
                break
    if item is None:
        item = flaps[-1] if takeoff else flaps[-1]
    if takeoff:
        pct = _num(item.get("distance_adjust_pct"), 0)
        return max(0.85, 1.0 + (pct / 100.0))
    pct = _num(item.get("distance_ratio_pct"), 100)
    if pct <= 1:
        return 1.0
    return max(0.85, pct / 100.0)


def calculate(payload: dict[str, Any]) -> dict[str, Any]:
    p = _profile(payload.get("aircraft") or payload.get("profile_id"))
    mode = str(payload.get("mode") or "takeoff").lower()
    runway_length_m = _num(payload.get("runway_length_m"), 0)
    runway_heading = _num(payload.get("runway_heading"), 0)
    wind_dir = _num(payload.get("wind_dir"), runway_heading)
    wind_speed = _num(payload.get("wind_speed"), 0)
    oat_c = _num(payload.get("oat_c"), 15)
    qnh = _num(payload.get("qnh_hpa"), 1013)
    elevation_ft = _num(payload.get("elevation_ft"), 0)
    slope_pct = _num(payload.get("slope_pct"), 0)
    condition = str(payload.get("condition") or "dry")
    headwind, crosswind = _wind_components(runway_heading, wind_dir, wind_speed)
    pressure_alt = elevation_ft + (1013.25 - qnh) * 27.0
    density_alt = pressure_alt + 120.0 * (oat_c - _isa_temp_c(elevation_ft))
    warnings: list[str] = []
    weights = p.get("weights", {})

    if mode.startswith("land"):
        weight = _num(payload.get("weight_kg"), _num(weights.get("max_lw_kg"), 0) * 0.92)
        landing = p.get("landing", {})
        required = _interp(landing.get("points", []), weight, "weight_kg", "distance_m")
        # Blend in high-elevation distance reference around the middle landing weight where available.
        elev_pts = landing.get("elevation_points", [])
        if elev_pts and density_alt > 500:
            elev_ref = _interp(elev_pts, min(max(density_alt, 0), 10000), "elevation_ft", "distance_m")
            mid_ref = _interp(landing.get("points", []), weight, "weight_kg", "distance_m")
            required *= max(1.0, elev_ref / max(mid_ref, 1.0))
        required *= _flap_factor(landing.get("flaps", []), str(payload.get("flap") or ""), False)
        required *= _condition_factor(condition, landing=True)
        if headwind >= 0:
            required *= max(0.88, 1.0 - min(headwind, 40) * 0.004)
        else:
            required *= 1.0 + min(abs(headwind), 20) * 0.045
        required *= max(0.88, 1.0 + max(slope_pct, -2) * 0.03)
        if str(payload.get("reverse") or "normal").lower().startswith("idle"):
            required *= 1.08
        if str(payload.get("autobrake") or "").lower() in {"low", "1"}:
            required *= 1.05
        vref = max(95, _num(p.get("vr_isa_kt"), 140) - 22 + (weight - _num(weights.get("max_lw_kg"), weight) * 0.82) / 1000.0 * 0.12)
        add = min(_num(landing.get("vapp_max_add_kt"), 15), max(5, max(headwind, 0) / max(_num(landing.get("headwind_divide"), 3), 1)))
        vapp = vref + add
        if weight > _num(weights.get("max_lw_kg"), weight + 1):
            warnings.append("Landing weight is above profile MLW")
        if headwind < _num(landing.get("max_tailwind_landing_kt"), -15):
            warnings.append("Tailwind exceeds profile landing limit")
        result_type = "landing"
        speeds = {"vref_kt": round(vref), "vapp_kt": round(vapp)}
    else:
        weight = _num(payload.get("weight_kg"), _num(weights.get("max_tow_kg"), 0) * 0.92)
        takeoff = p.get("takeoff", {})
        isa = _interp(takeoff.get("points", []), weight, "weight_kg", "isa_m")
        hot = _interp(takeoff.get("points", []), weight, "weight_kg", "hot_m")
        isa_delta = oat_c - _isa_temp_c(elevation_ft)
        ref = max(_num(takeoff.get("isa_plus_reference_c"), 15), 1)
        blend = min(max(isa_delta / ref, 0), 1.5)
        required = isa + (hot - isa) * min(blend, 1.0)
        if blend > 1.0:
            required *= 1.0 + (blend - 1.0) * 0.08
        alt_corr = _num(takeoff.get("alt_8000_correction_pct"), 120)
        required *= 1.0 + max(density_alt, 0) / 8000.0 * max((alt_corr - 100.0) / 100.0, 0.0)
        required *= _flap_factor(takeoff.get("flaps", []), str(payload.get("flap") or ""), True)
        required *= _condition_factor(condition, landing=False)
        if headwind >= 0:
            required *= max(0.86, 1.0 - min(headwind, 40) * 0.005)
        else:
            required *= 1.0 + min(abs(headwind), 20) * 0.035
        required *= max(0.90, 1.0 + slope_pct * 0.055)
        if bool(payload.get("anti_ice")):
            required *= 1.035
        if bool(payload.get("packs_on")):
            required *= 1.018
        vr = _num(p.get("vr_isa_kt"), 140) + (weight - _num(weights.get("max_tow_kg"), weight) * 0.82) / 1000.0 * 0.16 + max(isa_delta, 0) * 0.03
        v1 = vr - (6 if runway_length_m and runway_length_m - required < 700 else 4)
        v2 = vr + 5
        flex = min(_num(takeoff.get("tflex_max_isa_c"), 55) + _isa_temp_c(elevation_ft), max(oat_c, oat_c + max(0, runway_length_m - required) / 120.0)) if runway_length_m else None
        if weight > _num(weights.get("max_tow_kg"), weight + 1):
            warnings.append("Takeoff weight is above profile MTOW")
        if crosswind > _num(takeoff.get("max_crosswind_kt"), 35):
            warnings.append("Crosswind exceeds profile takeoff limit")
        if headwind < _num(takeoff.get("max_tailwind_takeoff_kt"), -10):
            warnings.append("Tailwind exceeds profile takeoff limit")
        result_type = "takeoff"
        speeds = {"v1_kt": round(v1), "vr_kt": round(vr), "v2_kt": round(v2)}
        if flex is not None:
            speeds["flex_or_assumed_c"] = round(flex)

    required_factored = required * (1.15 if mode.startswith("land") else 1.0)
    margin = runway_length_m - required_factored if runway_length_m else None
    status = "OK"
    if runway_length_m and margin is not None:
        if margin < 0:
            status = "NO GO"
        elif margin < max(250, runway_length_m * 0.08):
            status = "TIGHT"
    return {
        "ok": True,
        "mode": result_type,
        "aircraft": {"id": p.get("id"), "icao": p.get("icao"), "name": p.get("name")},
        "inputs": {"weight_kg": round(weight), "runway_length_m": runway_length_m, "condition": condition, "headwind_kt": round(headwind, 1), "crosswind_kt": round(crosswind, 1), "density_altitude_ft": round(density_alt)},
        "distances": {"required_m": round(required), "factored_required_m": round(required_factored), "runway_margin_m": None if margin is None else round(margin)},
        "speeds": speeds,
        "status": status,
        "warnings": warnings,
        "source": "PERF2601-derived sim estimate; cross-check with aircraft EFB",
    }
