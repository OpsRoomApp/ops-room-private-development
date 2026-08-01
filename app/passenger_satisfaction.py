from __future__ import annotations

"""v0.25.9: 0-100% passenger satisfaction scoring for PIREP, Flight Analysis, Finance."""

import logging
from typing import Any

_LOGGER = logging.getLogger("opsroom.satisfaction")

REVENUE_BANDS: list[tuple[int, float, int]] = [
    (90, 1.05, 3),
    (75, 1.00, 0),
    (60, 0.90, -3),
    (40, 0.80, -8),
    ( 0, 0.65, -15),
]

CATEGORY_BANDS: list[tuple[int, str]] = [
    (90, "Excellent"),
    (75, "Good"),
    (60, "Average"),
    (40, "Poor"),
    ( 0, "Critical"),
]

DEFAULT_WEIGHTS: dict[str, Any] = {
    "schedule_max": 20,
    "delay_grace_min": 5.0,
    "delay_penalty_per_min": 1.0,
    "landing_max": 40,
    "hard_landing_fpm": 200, "hard_landing_penalty": 12,
    "very_hard_landing_fpm": 400, "very_hard_landing_penalty": 25,
    "unstable_penalty": 15,
    "go_around_penalty": 10,
    "approach_overspeed_kts": 10, "approach_overspeed_penalty": 5,
    "comfort_max": 25,
    "excess_g_threshold": 1.5, "excess_g_penalty": 10,
    "excess_bank_deg": 35, "excess_bank_penalty": 5,
    "turbulence_peak_fpm": 1500, "turbulence_penalty": 5,
    "operations_max": 15,
    "long_taxi_out_min": 25, "long_taxi_penalty": 5,
    "long_taxi_in_min": 15, "long_taxi_in_penalty": 4,
    "emergency_penalty": 50,
}


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _score_band(s):
    for threshold, label in CATEGORY_BANDS:
        if s >= threshold:
            return label
    return "Critical"


def _revenue_band(s):
    for threshold, mult, rep in REVENUE_BANDS:
        if s >= threshold:
            return mult, rep
    return REVENUE_BANDS[-1][1], REVENUE_BANDS[-1][2]


def compute(meta, pirep, weights=None):
    """Compute passenger satisfaction from flight meta + pirep analysis dict."""
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    meta = meta or {}
    pirep = pirep or {}
    expl_pos, expl_neg = [], []

    dep_delay = max(0.0, _num(meta.get("departure_delay_minutes")) or 0.0)
    arr_delay = max(0.0, _num(meta.get("arrival_delay_minutes")) or 0.0)
    sched_deduction = 0.0
    for d, label in ((dep_delay, "Departure delay"), (arr_delay, "Arrival delay")):
        over = max(0.0, d - float(w["delay_grace_min"]))
        if over > 0:
            sched_deduction += over * float(w["delay_penalty_per_min"])
            expl_neg.append(f"{label} {d:.0f} min")
    schedule_pts = max(0.0, float(w["schedule_max"]) - sched_deduction)
    if schedule_pts >= float(w["schedule_max"]) * 0.85:
        expl_pos.append("Schedule within tolerance")

    landing = pirep.get("landing") or {}
    touchdown_vspeed = _num(landing.get("vertical_speed_fpm"))
    unstable = bool(landing.get("unstable_approach"))
    go_arounds = int(landing.get("go_around_count") or 0)
    approach_overspeed = _num(landing.get("approach_overspeed_kts_above"))
    landing_deduction = 0.0
    if touchdown_vspeed is not None and touchdown_vspeed > float(w["very_hard_landing_fpm"]):
        landing_deduction += float(w["very_hard_landing_penalty"])
        expl_neg.append(f"Very hard landing ({touchdown_vspeed:.0f} fpm)")
    elif touchdown_vspeed is not None and touchdown_vspeed > float(w["hard_landing_fpm"]):
        landing_deduction += float(w["hard_landing_penalty"])
        expl_neg.append(f"Hard landing ({touchdown_vspeed:.0f} fpm)")
    elif touchdown_vspeed is not None and touchdown_vspeed > 0:
        expl_pos.append(f"Smooth landing ({touchdown_vspeed:.0f} fpm)")

    if unstable:
        landing_deduction += float(w["unstable_penalty"])
        expl_neg.append("Unstable approach at 500 ft gate")
    if go_arounds:
        landing_deduction += go_arounds * float(w["go_around_penalty"])
        expl_neg.append(f"{go_arounds} go-around(s)")
    if approach_overspeed and approach_overspeed > float(w["approach_overspeed_kts"]):
        landing_deduction += float(w["approach_overspeed_penalty"])
        expl_neg.append("Approach overspeed")
    landing_pts = max(0.0, float(w["landing_max"]) - landing_deduction)

    comfort = pirep.get("comfort") or {}
    comfort_deduction = 0.0
    g_val = _num(comfort.get("peak_g"))
    bank = _num(comfort.get("max_bank_deg"))
    turb = _num(comfort.get("turbulence_peak_fpm"))
    if g_val is not None and g_val > float(w["excess_g_threshold"]):
        comfort_deduction += float(w["excess_g_penalty"])
        expl_neg.append(f"Excess g ({g_val:.2f}g)")
    if bank is not None and abs(bank) > float(w["excess_bank_deg"]):
        comfort_deduction += float(w["excess_bank_penalty"])
        expl_neg.append(f"Excess bank ({abs(bank):.0f} deg)")
    if turb is not None and abs(turb) > float(w["turbulence_peak_fpm"]):
        comfort_deduction += float(w["turbulence_penalty"])
        expl_neg.append("Turbulence")
    if comfort_deduction <= 0:
        expl_pos.append("Comfort within tolerance")
    comfort_pts = max(0.0, float(w["comfort_max"]) - comfort_deduction)

    ops = pirep.get("operations") or pirep.get("ops") or {}
    ops_deduction = 0.0
    taxi_out = _num(ops.get("taxi_out_minutes"))
    taxi_in = _num(ops.get("taxi_in_minutes"))
    if taxi_out is not None and taxi_out > float(w["long_taxi_out_min"]):
        ops_deduction += float(w["long_taxi_penalty"])
        expl_neg.append(f"Long taxi out ({taxi_out:.0f} min)")
    elif taxi_out is not None:
        expl_pos.append(f"Efficient taxi out ({taxi_out:.0f} min)")
    if taxi_in is not None and taxi_in > float(w["long_taxi_in_min"]):
        ops_deduction += float(w["long_taxi_in_penalty"])
        expl_neg.append(f"Long taxi in ({taxi_in:.0f} min)")
    emergency = int(meta.get("emergency_events") or meta.get("emergency_count") or 0)
    if emergency:
        ops_deduction += emergency * float(w["emergency_penalty"])
        expl_neg.append(f"{emergency} emergency event(s)")
    ops_pts = max(0.0, float(w["operations_max"]) - ops_deduction)

    raw = schedule_pts + landing_pts + comfort_pts + ops_pts
    score = int(max(0, min(100, round(raw))))
    category = _score_band(score)
    multiplier, reputation_delta = _revenue_band(score)

    breakdown = {"schedule": round(schedule_pts, 1),
                 "landing": round(landing_pts, 1),
                 "comfort": round(comfort_pts, 1),
                 "operations": round(ops_pts, 1)}

    out = {"score": score, "category": category,
           "breakdown": breakdown,
           "explanations": {"positive": expl_pos, "negative": expl_neg},
           "revenue_multiplier": multiplier,
           "reputation_delta": reputation_delta,
           "weights_used": w}
    _LOGGER.info("[SATISFACTION] score=%d category=%s mult=%.2f rep=%+d",
                 score, category, multiplier, reputation_delta)
    return out


def explain(score_or_dict):
    if isinstance(score_or_dict, dict):
        d = score_or_dict
    else:
        d = {}
    return {"positive": d.get("explanations", {}).get("positive", []),
            "negative": d.get("explanations", {}).get("negative", [])}
