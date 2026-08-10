"""Regression tests for the NOTAM plain-English translation layer -- v0.25.65.

Covers the ICAO/FAA contraction dictionary (including the corpus-derived
additions), word-boundary safety, the ambiguous-token guard and the
conservative closure classifier.  Plain-Python PASS/FAIL harness, no network.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from app.notam_translate import _CONTRACTIONS, expand, expand_row, is_closure_notam  # noqa: E402

PASS = 0
FAIL = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {label}" + (f" -- {detail}" if detail else ""))


# ── Corpus-derived additions (v0.25.65) ─────────────────────────────────────
_NEW = {
    "AD": "Aerodrome",
    "AIP": "Aeronautical Information Publication",
    "AIRAC": "Aeronautical Information Regulation And Control",
    "ALS": "Approach Lighting System",
    "AMDT": "Amendment",
    "CAT": "Category",
    "CHG": "Change",
    "COORD": "Coordinates",
    "DA": "Decision Altitude",
    "DEG": "Degrees",
    "DOD": "Department Of Defense",
    "FLW": "Follow",
    "HGT": "Height",
    "IAC": "Instrument Approach Chart",
    "ICAO": "International Civil Aviation Organization",
    "INOP": "Inoperative",
    "KHZ": "Kilohertz",
    "LIT": "Lighted",
    "LPV": "Localizer Performance With Vertical Guidance",
    "LVP": "Low Visibility Procedures",
    "MAX": "Maximum",
    "MOCA": "Minimum Obstruction Clearance Altitude",
    "MRA": "Minimum Reception Altitude",
    "NM": "Nautical Miles",
    "OCA": "Obstacle Clearance Altitude",
    "OCH": "Obstacle Clearance Height",
    "REF": "Reference",
    "RNAV": "Area Navigation",
    "RNP": "Required Navigation Performance",
    "RVR/VIS": "Runway Visual Range/Visibility",
    "SID": "Standard Instrument Departure",
    "STAR": "Standard Terminal Arrival Route",
    "SUP": "Supplement",
    "WGS": "World Geodetic System",
}
for token, expected in _NEW.items():
    check(f"new entry {token} expands", expand(token) == expected, f"{expand(token)!r}")
    check(f"new entry {token} present in dict", _CONTRACTIONS.get(token) == expected)

# ── Word-boundary safety (no partial-token expansion) ───────────────────────
check("MAX only expands as a full token", "Maximum" in expand("MAX HGT 125FT") and "MAXIMUM" in expand("MAXIMUM"), expand("MAX HGT 125FT MAXIMUM"))
check("CAT does not touch CATEGORY", expand("CAT III") == "Category III" and expand("CATEGORY") == "CATEGORY")
check("AD does not touch ADJACENT", expand("AD") == "Aerodrome" and expand("ADJ") == "Adjacent")
check("NM does not touch NMRS", expand("NM") == "Nautical Miles" and expand("NMRS") == "NMRS")
check("compound RVR/VIS expands once", expand("RVR/VIS 550M") == "Runway Visual Range/Visibility 550M")

# ── Ambiguous tokens stay untouched (deliberately omitted) ──────────────────
for token in ("AB", "CD", "DL", "FRD", "US", "LT", "INT"):
    check(f"ambiguous {token} left as-is", expand(token) == token, expand(token))

# ── Existing entries unchanged (spot check) ─────────────────────────────────
check("CLSD still Closed", expand("RWY 08R/26L CLSD") == "Runway 08R/26L Closed")
check("U/S still Unserviceable", expand("TWY YANKEE U/S") == "Taxiway YANKEE Unserviceable")
check("WIP still Work In Progress", "Work In Progress" in expand("CLSD DUE WIP"))
check("BTN still Between", expand("BTN") == "Between")
check("WEF still With Effect From", expand("WEF 1200") == "With Effect From 1200")

# ── Closure classification (conservative: can only ADD warnings) ────────────
check("RWY CLSD is a closure", is_closure_notam("RWY 08R/26L CLSD DUE WIP") is True)
check("TWY CLSD is a closure", is_closure_notam("TWY YANKEE CLSD") is True)
check("RWY U/S is a closure", is_closure_notam("RWY 06 U/S") is True)
check("ILS U/S still classified closure-related (display only)", is_closure_notam("ILS RWY 08R/26L U/S") is True)
check("plain English RWY mention is not a closure", is_closure_notam("RWY 09L PAINTED THR MARKINGS REMOVED") is False)
check("steel plate TWY obstruction is not a closure", is_closure_notam("STEEL PLATE TWY ALPHA 65M WEST A12") is False)
check("no surface reference is not a closure", is_closure_notam("SOME NOTAM CLSD") is False)

# ── Real corpus texts expand without crashing and stay readable ─────────────
real = [
    "ILS RWY 08R/26L U/S DUE MAINT, SUBJECT TO OPERATIONAL AND WEATHER CONSTRAINTS",
    "TWY YANKEE CLSD DUE WIP",
    "LIT CRANE OPR AT PSN 512741N 0002747W (HEATHROW). MAX HGT 125FT AGL, 203FT AMSL.",
    "RWY 09L/27R REDUCED RWY DECLARED DISTANCES AND LGT DUE PHASE 3 OF RWY RESURFACING WORKS",
]
for text in real:
    out = expand(text)
    check(f"real text expands ({text[:30]}...) ", isinstance(out, str) and len(out) > 0, out)
check("expand_row adds translated_text only when different", "translated_text" in expand_row({"text": "RWY 08R CLSD"}), "")
check("expand_row leaves identical text alone", "translated_text" not in expand_row({"text": "plain english only"}), "")

# ── v0.25.65 second-pass dictionary additions ────────────────────────────────
_second_pass = {
    "MSL": "Mean Sea Level",
    "HAT": "Height Above Threshold",
    "IAP": "Instrument Approach Procedure",
    "MDA": "Minimum Descent Altitude",
    "GPS": "Global Positioning System",
    "TEMP": "Temporary",
    "INTL": "International",
    "THRU": "Through",
    "AD2": "Aerodrome Section (AIP Part 2)",
    "TWY/EXIT": "Taxiway Exit",
}
for token, expected in _second_pass.items():
    out = expand(token)
    check(f"second pass expands {token}", out == expected, out)
check("second pass: contraction mid-text", expand("LIT 203FT AGL, 305FT MSL") == "Lighted 203Feet Above Ground Level, 305Feet Mean Sea Level", expand("LIT 203FT AGL, 305FT MSL"))
check("second pass: H24 now expands (digit token)", expand("H24") == "Continuous (24 hours)", expand("H24"))
check("second pass: numeric tokens untouched", expand("1200 08R 26L") == "1200 08R 26L", expand("1200 08R 26L"))
# Letter+digit adjacency: unspaced forms stay unexpanded (safe), spaced forms
# still expand (no regression on the common "WEF 1200" shape).
check("second pass: unspaced WEF1200 passes through", expand("WEF1200") == "WEF1200", expand("WEF1200"))
check("second pass: spaced WEF 1200 still expands", expand("WEF 1200") == "With Effect From 1200", expand("WEF 1200"))
check("second pass: THRU window", expand("WEF 1200 TIL 1500 THRU 10 AUG") == "With Effect From 1200 TIL 1500 Through 10 AUG", expand("WEF 1200 TIL 1500 THRU 10 AUG"))

# ── Empty / oversized guards ────────────────────────────────────────────────
check("empty expand -> empty", expand("") == "")
check("oversized expand passes through", expand("X" * 30000) == "X" * 30000)

print(f"\nRESULTS: {PASS}/{PASS + FAIL} PASS, {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
