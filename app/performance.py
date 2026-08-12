from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from .perf_engine import A320NeoTakeoff, A350Takeoff, B738Takeoff, generic_takeoff_speeds, vref_for_profile, _num

_DATA = Path(__file__).resolve().parent / "data" / "performance_profiles.json"


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
        modeled = _modeled_flaps(p)
        takeoff_flaps = [x.get("label") for x in p.get("takeoff", {}).get("flaps", [])]
        if modeled is not None:
            takeoff_flaps = [label for label in takeoff_flaps if label in modeled] or takeoff_flaps
        items.append({
            "id": p.get("id"),
            "icao": p.get("icao"),
            "name": p.get("name"),
            "summary": p.get("summary", ""),
            "weights": p.get("weights", {}),
            "takeoff_flaps": takeoff_flaps,
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


# ---------------------------------------------------------------------------
# Engine dispatch
# ---------------------------------------------------------------------------

# Aircraft that use the A320neo FCOM-derived limiting-factor engine (the A32NX
# tables model the A320-251N; the rest of the family scales by weight).
# Normalized (alnum) ICAO keys.  "A320 CEO" -> "A320CEO", hence the
# variant entries below; the raw profile data uses display-style names.
_A320_FAMILY_ICAOS = {"A20N", "A318", "A319", "A320", "A320CEO", "A321", "A21N"}
# Aircraft that use the komed3 B738 tables (B738 exact; the rest of the 737
# family scales its weight into the table range).
_B738_FAMILY_ICAOS = {"B738", "B736", "B737", "BBJ1", "BBJ2", "B739"}
# Aircraft that use the A350 FCOM-derived tables (A359 exact with the -900
# flex correction; A35X is the -1000; both share the same tables).
_A350_FAMILY_ICAOS = {"A359", "A35X", "A350"}

_FLAP_CONF = {"1+F": 1, "2": 2, "3": 3}
_B738_FLAP_INDEX = {"1": 0, "5": 1, "15": 2}

# Flap settings each tier engine actually models -- the PERF2601 profiles
# list every flap, but the FCOM-derived engines only cover the standard
# takeoff configs.  The dropdown + flap recommendation are restricted to
# these for the tier engines so the recommendation never suggests a flap
# the engine cannot compute.
_A320_MODELED_FLAPS = ["1+F", "2", "3"]
_B738_MODELED_FLAPS = ["1", "5", "15"]
_A350_MODELED_FLAPS = ["1+F", "2", "3"]


def _modeled_flaps(profile: dict[str, Any]) -> list[str] | None:
    icao = _norm_key(profile.get("icao"))
    if icao in _A320_FAMILY_ICAOS:
        return _A320_MODELED_FLAPS
    if icao in _B738_FAMILY_ICAOS:
        return _B738_MODELED_FLAPS
    if icao in _A350_FAMILY_ICAOS:
        return _A350_MODELED_FLAPS
    return None


def _flap_label_to_conf(profile: dict[str, Any], flap: str) -> tuple[str, int | None]:
    """Map a profile flap label to an engine config index.

    Returns (canonical label, config index or None when the flap is not a
    takeoff config the engine models)."""
    flap = str(flap or "").strip().upper()
    icao = _norm_key(profile.get("icao"))
    if icao in _A320_FAMILY_ICAOS or icao in _A350_FAMILY_ICAOS:
        if flap in _FLAP_CONF:
            return flap, _FLAP_CONF[flap]
        if flap in ("UP", "0"):
            # zero-flap takeoff is modelled as the least-beneficial config
            return "1+F", 1
        return flap, None
    if icao in _B738_FAMILY_ICAOS:
        if flap in _B738_FLAP_INDEX:
            return flap, _B738_FLAP_INDEX[flap]
        return flap, None
    return flap, None


def _recommend_flap(profile: dict[str, Any], takeoff_flaps: list[dict[str, Any]], weight: float,
                    runway_length_m: float, *, isa_m: float, hot_m: float, isa_delta: float,
                    ref_c: float, density_alt: float, condition: str, headwind: float, slope_pct: float,
                    anti_ice: bool, packs_on: bool, allowed_labels: list[str] | None = None) -> tuple[str | None, float]:
    """Pick the flap setting whose adjusted required distance fits the runway.

    ``allowed_labels`` restricts the candidate set (the tier engines only
    model the standard takeoff configs).  Returns (label, required distance)."""
    candidates = []
    for f in takeoff_flaps:
        label = str(f.get("label") or "").strip().upper()
        if not label:
            continue
        if allowed_labels is not None and label not in allowed_labels:
            continue
        blend = min(max(isa_delta / max(ref_c, 1), 0), 1.0)
        required = isa_m + (hot_m - isa_m) * min(blend, 1.0)
        if blend > 1.0:
            required *= 1.0 + (blend - 1.0) * 0.08
        required *= _flap_factor(takeoff_flaps, label, True)
        required *= _condition_factor(condition, landing=False)
        if headwind >= 0:
            required *= max(0.86, 1.0 - min(headwind, 40) * 0.005)
        else:
            required *= 1.0 + min(abs(headwind), 20) * 0.035
        required *= max(0.90, 1.0 + slope_pct * 0.055)
        if anti_ice:
            required *= 1.035
        if packs_on:
            required *= 1.018
        candidates.append((required, label))
    if not candidates:
        return None, 0.0
    candidates.sort(key=lambda item: item[0])
    best_required, best_label = candidates[0]
    if runway_length_m and best_required <= runway_length_m:
        return best_label, best_required
    return best_label, best_required


def _profile_required_distance(profile: dict[str, Any], weight: float, runway_length_m: float, *,
                               headwind: float, oat_c: float, qnh: float, elevation_ft: float,
                               slope_pct: float, condition: str, flap: str, recommended_flap: str | None,
                               anti_ice: bool, anti_ice_wing: bool, packs_on: bool) -> float | None:
    """Required takeoff distance from the PERF2601 profile curves.

    The table-based engines (B738, A350) give V-speeds/limits only; the
    distance curves come from the profile data (same path as Tier 3)."""
    takeoff = profile.get("takeoff", {})
    try:
        isa_m = _interp(takeoff.get("points", []), weight, "weight_kg", "isa_m")
        hot_m = _interp(takeoff.get("points", []), weight, "weight_kg", "hot_m")
    except ValueError:
        return runway_length_m * 1.25
    elevation = float(elevation_ft)
    isa_delta = oat_c - _isa_temp_c(elevation)
    pressure_alt = elevation + (1013.25 - qnh) * 27.0
    density_alt = pressure_alt + 120.0 * (oat_c - _isa_temp_c(elevation))
    ref = max(_num(takeoff.get("isa_plus_reference_c"), 15), 1)
    blend = min(max(isa_delta / ref, 0), 1.5)
    required = isa_m + (hot_m - isa_m) * min(blend, 1.0)
    if blend > 1.0:
        required *= 1.0 + (blend - 1.0) * 0.08
    alt_corr = _num(takeoff.get("alt_8000_correction_pct"), 120)
    required *= 1.0 + max(density_alt, 0) / 8000.0 * max((alt_corr - 100.0) / 100.0, 0.0)
    flap_choice = flap if flap else (recommended_flap or "")
    required *= _flap_factor(takeoff.get("flaps", []), flap_choice, True)
    required *= _condition_factor(condition, landing=False)
    if headwind >= 0:
        required *= max(0.86, 1.0 - min(headwind, 40) * 0.005)
    else:
        required *= 1.0 + min(abs(headwind), 20) * 0.035
    required *= max(0.90, 1.0 + slope_pct * 0.055)
    if anti_ice:
        required *= 1.035
    if packs_on:
        required *= 1.018
    return required


def _takeoff_tier1_a320(profile: dict[str, Any], weight: float, runway_length_m: float, *,
                        headwind: float, oat_c: float, qnh: float, elevation_ft: float, slope_pct: float,
                        condition: str, flap: str, anti_ice_engine: bool, anti_ice_wing: bool,
                        packs_on: bool, cg: float | None, recommended_flap: str | None) -> dict[str, Any]:
    icao = _norm_key(profile.get("icao"))
    weights = profile.get("weights", {})
    mtow = _num(weights.get("max_tow_kg"), 79_000)
    oew = _num(weights.get("oew_kg"), 42_500)
    family = icao != "A20N"
    weight_scale = (mtow / 79_000.0) if family else 1.0
    eng = A320NeoTakeoff(weight_scale=weight_scale, oew_kg=oew, mtow_kg=mtow)

    wet = "wet" in str(condition or "dry").lower()
    conf_choice = flap if flap else (recommended_flap or "")
    _, conf = _flap_label_to_conf(profile, conf_choice)

    # Try the requested/recommended config first; if it cannot make the
    # runway, fall back to the optimum-config pass (never hard-fail on a
    # single config — the recommendation is a PERF2601-flavoured guess).
    result = None
    if conf is not None:
        result = eng.calculate(
            tow=weight, conf=conf, tora=runway_length_m, slope=slope_pct, wind=headwind,
            elevation=elevation_ft, qnh=qnh, oat=oat_c,
            anti_ice_engine=anti_ice_engine, anti_ice_wing=anti_ice_wing, packs=packs_on,
            wet=wet, cg=cg)
    if result is None or not (result.get("speeds") or {}).get("v1_kt"):
        result = eng.calculate_opt_config(
            tow=weight, tora=runway_length_m, slope=slope_pct, wind=headwind,
            elevation=elevation_ft, qnh=qnh, oat=oat_c,
            anti_ice_engine=anti_ice_engine, anti_ice_wing=anti_ice_wing, packs=packs_on,
            wet=wet, cg=cg)

    required = eng.required_tora(
        tow=weight, conf=(conf if conf is not None else 2), slope=slope_pct, wind=headwind,
        elevation=elevation_ft, qnh=qnh, oat=oat_c, anti_ice_wing=anti_ice_wing, packs=packs_on)
    if required is None:
        required = runway_length_m * 1.25

    speeds = result.get("speeds") or {}
    v1, vr, v2 = speeds.get("v1_kt"), speeds.get("vr_kt"), speeds.get("v2_kt")
    if v1 is None or vr is None or v2 is None:
        raise ValueError(result.get("error") or "Takeoff not possible under these conditions")

    speeds_out = {"v1_kt": round(v1), "vr_kt": round(vr), "v2_kt": round(v2)}
    if result.get("flex") is not None:
        speeds_out["flex_or_assumed_c"] = round(result.get("flex"))
    if cg is not None and result.get("stab_trim") is not None:
        speeds_out["pitch_trim"] = result["stab_trim"]

    if family:
        source = "A320neo FCOM-derived model, family-scaled"
    else:
        source = "A320neo FCOM-derived model (A32NX)"

    return {
        "speeds": speeds_out,
        "required_m": round(required),
        "config": result.get("conf"),
        "config_flaps": result.get("configs"),
        "mtow": round(min(result.get("mtow") or 0, mtow)),
        "flex": result.get("flex"),
        "limiting": result.get("oatLimitingFactor"),
        "source": source,
    }


def _takeoff_tier1_b738(profile: dict[str, Any], weight: float, runway_length_m: float, *,
                        headwind: float, oat_c: float, qnh: float, elevation_ft: float, slope_pct: float,
                        condition: str, flap: str, anti_ice_engine: bool, anti_ice_wing: bool,
                        packs_on: bool, cg: float | None, recommended_flap: str | None) -> dict[str, Any]:
    icao = _norm_key(profile.get("icao"))
    weights = profile.get("weights", {})
    family = icao != "B738"
    # The komed3 tables are indexed in absolute weight buckets.  The B738
    # itself passes its real TOW through (the engine extrapolates above 65 t);
    # family members (B736/B737/BBJ/B739) scale their TOW into the B738
    # weight range by their own MTOW so the tables stay meaningful.
    if family:
        mtow = _num(weights.get("max_tow_kg"), 79_000)
        scale = 65_000.0 / max(mtow, 65_000.0)
        engine_weight = weight * scale
    else:
        engine_weight = weight
        scale = 1.0

    wet = "wet" in str(condition or "dry").lower()
    engine = B738Takeoff()
    flap_choice = flap if flap else (recommended_flap or "")
    _, flap_index = _flap_label_to_conf(profile, flap_choice)

    # Try the requested/recommended flap first; if that config cannot
    # make the runway, let the engine pick the best workable config.
    # (PERF2601 flap factors can prefer a high flap the komed3 tables
    # reject at this weight, so never hard-fail on the recommendation.)
    result = None
    if flap_index is not None:
        result = engine.calculate(
            tow=engine_weight, flap_index=flap_index, tora_m=runway_length_m,
            elevation_ft=elevation_ft, qnh_hpa=qnh, oat_c=oat_c, wet=wet)
    if result is None or not (result.get("speeds") or {}).get("v1_kt"):
        result = engine.calculate_all_flaps(
            tow=engine_weight, tora_m=runway_length_m,
            elevation_ft=elevation_ft, qnh_hpa=qnh, oat_c=oat_c, wet=wet)

    speeds = result.get("speeds") or {}
    v1, vr, v2 = speeds.get("v1_kt"), speeds.get("vr_kt"), speeds.get("v2_kt")
    if v1 is None or vr is None or v2 is None:
        raise ValueError(result.get("error") or "Takeoff not possible under these conditions")

    speeds_out = {"v1_kt": round(v1), "vr_kt": round(vr), "v2_kt": round(v2)}
    if cg is not None:
        # Boeing 737NG stabilizer trim approximation from CG % MAC
        speeds_out["pitch_trim"] = round(max(0.0, min(8.0, 8.0 - (cg - 15.0) * 0.28)), 1)

    if family:
        source = "B737-800 V-speed tables (komed3), family-scaled"
    else:
        source = "B737-800 V-speed tables (komed3)"
    return {
        "speeds": speeds_out,
        "required_m": _profile_required_distance(
            profile, weight, runway_length_m, headwind=headwind, oat_c=oat_c, qnh=qnh,
            elevation_ft=elevation_ft, slope_pct=slope_pct, condition=condition, flap=flap,
            recommended_flap=recommended_flap, anti_ice=anti_ice_engine, anti_ice_wing=anti_ice_wing,
            packs_on=packs_on),
        "config": flap_index,
        "config_flaps": result.get("configs"),
        "mtow": round(min(weight * (1.0 / scale if family else 1.0), _num(weights.get("max_tow_kg"), 79_000))),
        "flex": None,
        "limiting": None,
        "source": source,
    }


def _takeoff_tier1_a350(profile: dict[str, Any], weight: float, runway_length_m: float, *,
                        headwind: float, oat_c: float, qnh: float, elevation_ft: float, slope_pct: float,
                        condition: str, flap: str, anti_ice_engine: bool, anti_ice_wing: bool,
                        packs_on: bool, cg: float | None, recommended_flap: str | None) -> dict[str, Any]:
    icao = _norm_key(profile.get("icao"))
    weights = profile.get("weights", {})
    mtow = _num(weights.get("max_tow_kg"), 308_000)
    variant = "A350-900" if icao == "A359" else "A350-1000"
    wet = "wet" in str(condition or "dry").lower()
    engine = A350Takeoff(variant=variant)

    conf_choice = flap if flap else (recommended_flap or "")
    _, conf = _flap_label_to_conf(profile, conf_choice)

    # Try the requested/recommended config first; if it cannot make the
    # runway, fall back to the optimum-config pass (never hard-fail on a
    # single config -- the recommendation is a PERF2601-flavoured guess).
    result = None
    if conf is not None:
        result = engine.calculate(
            tow=weight, conf=conf, tora=runway_length_m, slope=slope_pct, wind=headwind,
            elevation=elevation_ft, qnh=qnh, oat=oat_c,
            anti_ice_engine=anti_ice_engine, anti_ice_wing=anti_ice_wing, packs=packs_on,
            wet=wet, cg=cg)
    if result is None or not (result.get("speeds") or {}).get("v1_kt"):
        result = engine.calculate_opt_config(
            tow=weight, tora=runway_length_m, slope=slope_pct, wind=headwind,
            elevation=elevation_ft, qnh=qnh, oat=oat_c,
            anti_ice_engine=anti_ice_engine, anti_ice_wing=anti_ice_wing, packs=packs_on,
            wet=wet, cg=cg)

    speeds = result.get("speeds") or {}
    v1, vr, v2 = speeds.get("v1_kt"), speeds.get("vr_kt"), speeds.get("v2_kt")
    if v1 is None or vr is None or v2 is None:
        raise ValueError(result.get("error") or "Takeoff not possible under these conditions")

    speeds_out = {"v1_kt": round(v1), "vr_kt": round(vr), "v2_kt": round(v2)}
    if result.get("flex") is not None:
        speeds_out["flex_or_assumed_c"] = round(result.get("flex"))

    return {
        "speeds": speeds_out,
        "required_m": _profile_required_distance(
            profile, weight, runway_length_m, headwind=headwind, oat_c=oat_c, qnh=qnh,
            elevation_ft=elevation_ft, slope_pct=slope_pct, condition=condition, flap=flap,
            recommended_flap=recommended_flap, anti_ice=anti_ice_engine, anti_ice_wing=anti_ice_wing,
            packs_on=packs_on),
        "config": result.get("conf"),
        "config_flaps": result.get("configs"),
        "mtow": round(min(result.get("mtow") or 0, mtow)),
        "flex": result.get("flex"),
        "limiting": None,
        "source": "A350 FCOM-derived tables",
    }


def _fenix_takeoff_result(
    profile: dict[str, Any],
    weight: float,
    runway_length_m: float,
    runway_heading: float,
    wind_dir: float,
    wind_speed: float,
    oat_c: float,
    qnh: float,
    elevation_ft: float,
    condition: str,
    flap: str,
    recommended_flap: str | None,
    cg: float | None,
    anti_ice: bool,
    packs_on: bool,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """#61: exact Fenix EFB takeoff calculation when a Fenix A320 is active.

    Returns None (built-in engines continue) unless the active aircraft is a
    detected Fenix A320, the EFB portal is reachable and the engine type is
    supported by the portal's calculator.
    """
    if _norm_key(profile.get("icao")) not in _A320_FAMILY_ICAOS:
        return None
    try:
        from .fenix_adapter import status as _fenix_status
        if not bool((_fenix_status() or {}).get("fenix_detected")):
            return None
    except Exception:
        return None
    try:
        from .fenix_perf import aircraft_type_from_title, fetch_takeoff
        from .telemetry_provider import read_telemetry
        tel = read_telemetry(force=False) or {}
        aircraft = tel.get("aircraft") if isinstance(tel.get("aircraft"), dict) else {}
        title = aircraft.get("title") or tel.get("aircraft_title") or ""
        aircraft_type = aircraft_type_from_title(str(title))
        if not aircraft_type:
            return None
        return fetch_takeoff(
            weight_kg=weight,
            runway_length_m=runway_length_m,
            qnh_hpa=qnh,
            elevation_ft=elevation_ft,
            oat_c=oat_c,
            wind_dir=wind_dir,
            wind_speed=wind_speed,
            flap=flap or recommended_flap or "",
            packs_on=packs_on,
            anti_ice=anti_ice,
            surface_condition=condition,
            runway_heading=runway_heading,
            icao=str(profile.get("icao") or ""),
            runway=str(payload.get("runway") or ""),
            aircraft_type=aircraft_type,
            mac_tow=cg,
        )
    except Exception:
        return None


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
    flap = str(payload.get("flap") or "")
    cg = payload.get("cg_pct")
    if cg is None or cg == "":
        cg = None
    else:
        try:
            cg = float(cg)
        except (TypeError, ValueError):
            cg = None
    headwind, crosswind = _wind_components(runway_heading, wind_dir, wind_speed)
    pressure_alt = elevation_ft + (1013.25 - qnh) * 27.0
    density_alt = pressure_alt + 120.0 * (oat_c - _isa_temp_c(elevation_ft))
    warnings: list[str] = []
    weights = p.get("weights", {})
    icao = _norm_key(p.get("icao"))

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
        required *= _flap_factor(landing.get("flaps", []), flap, False)
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
        vref = vref_for_profile(p, weight)
        add = min(_num(landing.get("vapp_max_add_kt"), 15), max(5, max(headwind, 0) / max(_num(landing.get("headwind_divide"), 3), 1)))
        vapp = vref + add
        if weight > _num(weights.get("max_lw_kg"), weight + 1):
            warnings.append("Landing weight is above profile MLW")
        if headwind < _num(landing.get("max_tailwind_landing_kt"), -15):
            warnings.append("Tailwind exceeds profile landing limit")
        result_type = "landing"
        speeds = {"vref_kt": round(vref), "vapp_kt": round(vapp)}
        required_factored = required * 1.15
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
            "inputs": {"weight_kg": round(weight), "runway_length_m": runway_length_m, "condition": condition,
                       "headwind_kt": round(headwind, 1), "crosswind_kt": round(crosswind, 1),
                       "density_altitude_ft": round(density_alt), "cg_pct": cg},
            "distances": {"required_m": round(required), "factored_required_m": round(required_factored),
                          "runway_margin_m": None if margin is None else round(margin)},
            "speeds": speeds,
            "status": status,
            "warnings": warnings,
            "source": "PERF2601-derived sim estimate; cross-check with aircraft EFB",
        }

    # ---- takeoff ----------------------------------------------------------
    weight = _num(payload.get("weight_kg"), _num(weights.get("max_tow_kg"), 0) * 0.92)
    takeoff = p.get("takeoff", {})
    isa = _interp(takeoff.get("points", []), weight, "weight_kg", "isa_m")
    hot = _interp(takeoff.get("points", []), weight, "weight_kg", "hot_m")
    isa_delta = oat_c - _isa_temp_c(elevation_ft)
    ref = max(_num(takeoff.get("isa_plus_reference_c"), 15), 1)
    anti_ice = bool(payload.get("anti_ice"))
    packs_on = bool(payload.get("packs_on"))
    recommended_flap, _ = _recommend_flap(
        p, takeoff.get("flaps", []), weight, runway_length_m,
        isa_m=isa, hot_m=hot, isa_delta=isa_delta, ref_c=ref,
        density_alt=density_alt, condition=condition, headwind=headwind,
        slope_pct=slope_pct, anti_ice=anti_ice, packs_on=packs_on,
        allowed_labels=_modeled_flaps(p))

    # Tier 1 / Tier 2 engine paths for the FCOM-derived families.  If the
    # exact-data engine refuses (e.g. runway below its data floor), fall back
    # to the PERF2601 generic path with a warning rather than a hard error.
    tier_result = None
    tier_fallback_reason = None
    if icao in _A320_FAMILY_ICAOS:
        try:
            tier_result = _takeoff_tier1_a320(
                p, weight, runway_length_m, headwind=headwind, oat_c=oat_c, qnh=qnh,
                elevation_ft=elevation_ft, slope_pct=slope_pct, condition=condition, flap=flap,
                anti_ice_engine=anti_ice, anti_ice_wing=False, packs_on=packs_on, cg=cg,
                recommended_flap=recommended_flap)
        except ValueError as tier_exc:
            tier_fallback_reason = str(tier_exc)
    elif icao in _B738_FAMILY_ICAOS:
        try:
            tier_result = _takeoff_tier1_b738(
                p, weight, runway_length_m, headwind=headwind, oat_c=oat_c, qnh=qnh,
                elevation_ft=elevation_ft, slope_pct=slope_pct, condition=condition, flap=flap,
                anti_ice_engine=anti_ice, anti_ice_wing=False, packs_on=packs_on, cg=cg,
                recommended_flap=recommended_flap)
        except ValueError as tier_exc:
            tier_fallback_reason = str(tier_exc)
    elif icao in _A350_FAMILY_ICAOS:
        try:
            tier_result = _takeoff_tier1_a350(
                p, weight, runway_length_m, headwind=headwind, oat_c=oat_c, qnh=qnh,
                elevation_ft=elevation_ft, slope_pct=slope_pct, condition=condition, flap=flap,
                anti_ice_engine=anti_ice, anti_ice_wing=False, packs_on=packs_on, cg=cg,
                recommended_flap=recommended_flap)
        except ValueError as tier_exc:
            tier_fallback_reason = str(tier_exc)
    if tier_fallback_reason:
        warnings.append(f"EXACT ENGINE REFUSED ({tier_fallback_reason}); using PERF2601 estimate")

    if tier_result is not None:
        required = tier_result["required_m"]
        speeds = tier_result["speeds"]
        source = tier_result["source"]
        engine_note = []
        if tier_result.get("flex") is not None:
            engine_note.append(f"FLEX {round(tier_result['flex'])}")
        if tier_result.get("limiting"):
            engine_note.append(f"LIMIT {tier_result['limiting'].replace('_', ' ').upper()}")
        if tier_result.get("mtow"):
            engine_note.append(f"MTOW {tier_result['mtow']:,} KG")
        if engine_note:
            warnings.append(" · ".join(engine_note))
    else:
        # Tier 3: PERF2601 distance curves + vr_isa anchored speeds.
        blend = min(max(isa_delta / ref, 0), 1.5)
        required = isa + (hot - isa) * min(blend, 1.0)
        if blend > 1.0:
            required *= 1.0 + (blend - 1.0) * 0.08
        alt_corr = _num(takeoff.get("alt_8000_correction_pct"), 120)
        required *= 1.0 + max(density_alt, 0) / 8000.0 * max((alt_corr - 100.0) / 100.0, 0.0)
        required *= _flap_factor(takeoff.get("flaps", []), flap if flap else (recommended_flap or ""), True)
        required *= _condition_factor(condition, landing=False)
        if headwind >= 0:
            required *= max(0.86, 1.0 - min(headwind, 40) * 0.005)
        else:
            required *= 1.0 + min(abs(headwind), 20) * 0.035
        required *= max(0.90, 1.0 + slope_pct * 0.055)
        if anti_ice:
            required *= 1.035
        if packs_on:
            required *= 1.018
        margin_for_speed = runway_length_m - required
        g = generic_takeoff_speeds(p, weight, isa_delta, margin_for_speed)
        speeds = dict(g)
        if cg is not None:
            # Generic pitch-trim approximation from CG % MAC (nose-up units).
            speeds["pitch_trim"] = round(max(0.0, min(9.0, 9.0 - (cg - 15.0) * 0.25)), 1)
        source = "PERF2601-derived sim estimate; cross-check with aircraft EFB"

    # #61: when the Fenix EFB portal is live, its certified takeoff engine is
    # the exact Tier-1 source for V-speeds / FLEX / trim / retraction speeds.
    # The required-distance margin keeps our FCOM/PERF2601 distance engine
    # (the Fenix TOPL unit is undocumented, so it is surfaced as a reference
    # only and never trusted for the OK/TIGHT/NO-GO margin), keeping the
    # go/no-go decision honest.
    fenix = None
    try:
        fenix = _fenix_takeoff_result(
            p, weight, runway_length_m, runway_heading, wind_dir, wind_speed,
            oat_c, qnh, elevation_ft, condition, flap, recommended_flap,
            cg, anti_ice, packs_on, payload,
        )
    except Exception:
        fenix = None
    if fenix and fenix.get("ok"):
        for speed_key, fenix_key in (("v1_kt", "v1_kt"), ("vr_kt", "vr_kt"), ("v2_kt", "v2_kt"), ("flex_or_assumed_c", "flex_c")):
            if fenix.get(fenix_key) is not None:
                speeds[speed_key] = round(float(fenix[fenix_key]), 1)
        trim_n = None
        if fenix.get("trim") is not None:
            trim_n = round(float(fenix["trim"]), 1)
            # Signed pitch trim: positive = UP, negative = DN (the frontend
            # renders the direction from the sign).
            speeds["pitch_trim"] = -trim_n if str(fenix.get("trim_direction") or "").upper() == "DN" else trim_n
        source = "Fenix EFB (exact aircraft engine)"
        if fenix.get("flex_c") is not None:
            warnings.append(f"EFB FLEX {round(float(fenix['flex_c']))} °C")
        if fenix.get("flap") is not None:
            warnings.append(f"EFB CONF {fenix['flap']}")
        if trim_n is not None:
            warnings.append(f"EFB TRIM {trim_n} {str(fenix.get('trim_direction') or '').upper() or 'UP'}")
        if fenix.get("green_dot_kt") is not None:
            warnings.append(f"EFB GREEN DOT {round(float(fenix['green_dot_kt']))} KT")
        if fenix.get("flap_retraction_kt") is not None:
            warnings.append(f"EFB FLAP RETRACT {round(float(fenix['flap_retraction_kt']))} KT")
        if fenix.get("slat_retraction_kt") is not None:
            warnings.append(f"EFB SLAT RETRACT {round(float(fenix['slat_retraction_kt']))} KT")
        if fenix.get("corrected_stop_margin") is not None:
            warnings.append(f"EFB STOP MARGIN {round(float(fenix['corrected_stop_margin']))} M")

    if recommended_flap and not flap:
        warnings.append(f"RECOMMENDED FLAP {recommended_flap}")

    required_factored = required
    margin = runway_length_m - required_factored if runway_length_m else None
    status = "OK"
    if runway_length_m and margin is not None:
        if margin < 0:
            status = "NO GO"
        elif margin < max(250, runway_length_m * 0.08):
            status = "TIGHT"
    if weight > _num(weights.get("max_tow_kg"), weight + 1):
        warnings.append("Takeoff weight is above profile MTOW")
    if crosswind > _num(takeoff.get("max_crosswind_kt"), 35):
        warnings.append("Crosswind exceeds profile takeoff limit")
    if headwind < _num(takeoff.get("max_tailwind_takeoff_kt"), -10):
        warnings.append("Tailwind exceeds profile takeoff limit")
    result_type = "takeoff"

    return {
        "ok": True,
        "mode": result_type,
        "aircraft": {"id": p.get("id"), "icao": p.get("icao"), "name": p.get("name")},
        "inputs": {"weight_kg": round(weight), "runway_length_m": runway_length_m, "condition": condition,
                   "headwind_kt": round(headwind, 1), "crosswind_kt": round(crosswind, 1),
                   "density_altitude_ft": round(density_alt), "cg_pct": cg},
        "distances": {"required_m": round(required), "factored_required_m": round(required_factored),
                      "runway_margin_m": None if margin is None else round(margin)},
        "speeds": speeds,
        "recommended_flap": recommended_flap,
        "status": status,
        "warnings": warnings,
        "source": source,
    }
