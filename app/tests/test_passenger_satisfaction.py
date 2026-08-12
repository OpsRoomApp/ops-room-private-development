"""Regression tests for #63 -- passenger satisfaction must read the REAL
analysis shape (touchdown_rate_fpm / touchdown_g / approach.stability_500),
not the fictional keys the scorer used to read.

Plain-Python PASS/FAIL harness, no network.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from app.passenger_satisfaction import compute, DEFAULT_WEIGHTS  # noqa: E402

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


def _clean_pirep() -> dict:
    """Real analysis_summary shape produced by analyse_pirep (EWG5EZ-shaped)."""
    return {
        "landing": {
            "touchdown_rate_fpm": -592.09,
            "touchdown_g": 1.92,
            "touchdown_speed_kts": 134.3,
            "touchdowns": 1,
            "bounce_count": 0,
        },
        "approach": {
            "stability_500": {
                "available": True,
                "stable": False,
                "checks": [
                    {"key": "lateral", "label": "Lateral path", "ok": True, "value": "143 ft"},
                    {"key": "vertical", "label": "Vertical path", "ok": True, "value": "86 ft"},
                    {"key": "sink", "label": "Descent rate", "ok": True, "value": "-551 fpm"},
                    {"key": "bank", "label": "Bank", "ok": True, "value": "0.4 deg"},
                    {"key": "speed", "label": "Speed", "ok": True, "value": "139 kt"},
                ],
            },
            "stability_1000": {"available": True, "stable": False},
        },
    }


def test_hard_landing_scores_below_100() -> None:
    meta = {"times": {"block_out": "2026-08-11T07:27:10Z", "takeoff": "2026-08-11T07:43:41Z",
                      "landing": "2026-08-11T09:25:06Z", "block_in": "2026-08-11T09:30:19Z"}}
    result = compute(meta, _clean_pirep())
    score = result["score"]
    check("hard landing (-592 fpm) drops score below 100", score < 100, f"score={score}")
    check("landing breakdown not full marks", result["breakdown"]["landing"] < DEFAULT_WEIGHTS["landing_max"], f"{result['breakdown']}")
    check("comfort breakdown not full marks", result["breakdown"]["comfort"] < DEFAULT_WEIGHTS["comfort_max"], f"{result['breakdown']}")
    neg = " ".join(result["explanations"]["negative"]).lower()
    check("negative explanation mentions hard landing", "landing" in neg, neg)
    check("negative explanation mentions excess g", "excess g" in neg, neg)
    check("no 'smooth landing' for a hard landing", "smooth" not in neg, neg)
    check("no 'comfort within tolerance' with 1.92g", not any("comfort within" in e.lower() for e in result["explanations"]["positive"]), str(result["explanations"]))


def test_smooth_landing_scores_high() -> None:
    pirep = _clean_pirep()
    pirep["landing"]["touchdown_rate_fpm"] = -121.0
    pirep["landing"]["touchdown_g"] = 1.12
    pirep["approach"]["stability_500"]["stable"] = True
    result = compute({}, pirep)
    check("smooth landing still scores high", result["score"] >= 90, f"score={result['score']}")
    pos = " ".join(result["explanations"]["positive"]).lower()
    check("smooth landing noted positively", "smooth" in pos, pos)


def test_unstable_approach_penalty() -> None:
    pirep = _clean_pirep()
    pirep["landing"]["touchdown_rate_fpm"] = -150.0
    pirep["landing"]["touchdown_g"] = 1.1
    # stability_500 available but unstable -> penalty regardless of soft landing
    result = compute({}, pirep)
    neg = " ".join(result["explanations"]["negative"]).lower()
    check("unstable approach adds negative", "unstable" in neg, neg)


def test_missing_telemetry_never_breaks() -> None:
    result = compute({}, {})
    check("empty pirep still returns a score", 0 <= result["score"] <= 100, f"{result}")
    check("empty pirep no crash", "error" not in result, str(result))


def test_old_key_fallback() -> None:
    # Callers that still pass the old shape (vertical_speed_fpm / comfort.peak_g)
    # must keep working.
    pirep = {
        "landing": {"vertical_speed_fpm": -450.0, "unstable_approach": True},
        "comfort": {"peak_g": 1.7},
    }
    result = compute({}, pirep)
    check("legacy shape still penalized", result["breakdown"]["landing"] < DEFAULT_WEIGHTS["landing_max"], f"{result['breakdown']}")
    check("legacy comfort g still penalized", result["breakdown"]["comfort"] < DEFAULT_WEIGHTS["comfort_max"], f"{result['breakdown']}")


def test_taxi_times_derived_from_recorded_times() -> None:
    # 16.5 min taxi out (07:27:10 -> 07:43:41) and 5.2 min taxi in -> no long-taxi penalties
    meta = {"times": {"block_out": "2026-08-11T07:27:10Z", "takeoff": "2026-08-11T07:43:41Z",
                      "landing": "2026-08-11T09:25:06Z", "block_in": "2026-08-11T09:30:19Z"}}
    pirep = _clean_pirep()
    pirep["landing"]["touchdown_rate_fpm"] = -130.0
    pirep["landing"]["touchdown_g"] = 1.1
    pirep["approach"]["stability_500"]["stable"] = True
    result = compute(meta, pirep)
    pos = " ".join(result["explanations"]["positive"]).lower()
    check("efficient taxi out noted", "taxi out" in pos, pos)
    neg = " ".join(result["explanations"]["negative"]).lower()
    check("no long taxi penalties", "long taxi" not in neg, neg)


def test_long_taxi_penalty() -> None:
    meta = {"times": {"block_out": "2026-08-11T07:00:00Z", "takeoff": "2026-08-11T07:35:00Z",
                      "landing": "2026-08-11T09:25:00Z", "block_in": "2026-08-11T09:55:00Z"}}
    pirep = _clean_pirep()
    pirep["landing"]["touchdown_rate_fpm"] = -130.0
    pirep["landing"]["touchdown_g"] = 1.1
    pirep["approach"]["stability_500"]["stable"] = True
    result = compute(meta, pirep)
    neg = " ".join(result["explanations"]["negative"]).lower()
    check("35 min taxi out penalized", "long taxi out" in neg, neg)
    check("30 min taxi in penalized", "long taxi in" in neg, neg)


if __name__ == "__main__":
    test_hard_landing_scores_below_100()
    test_smooth_landing_scores_high()
    test_unstable_approach_penalty()
    test_missing_telemetry_never_breaks()
    test_old_key_fallback()
    test_taxi_times_derived_from_recorded_times()
    test_long_taxi_penalty()
    print(f"RESULTS: {PASS}/{PASS + FAIL} PASS, {FAIL} FAIL")
    sys.exit(1 if FAIL else 0)
