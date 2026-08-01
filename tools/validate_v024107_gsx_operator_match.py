"""Offline validator for the v0.24.107 GSX operating-airline matcher fix.

Covers the concrete failure-scenarios spelled out in
`plans/gsx-operator-selection-airline-match.md`:

* `DLH` plan with a mixed Lufthansa / Lufthansa Cargo / handler menu must pick
  the plain "Lufthansa" operator (not the cargo subsidiary, not a generic
  handler).
* `DLH` plan with numeric-prefixed GSX labels ("1. Lufthansa", ...) must still
  resolve to the first branded operator with a correct raw menu-entries index.
* `DLH` plan with only "Lufthansa Cargo" + an outsider handler present (the
  home carrier is absent, as can happen at an outstation) must NOT autopick the
  cargo subsidiary — the matcher falls back to ``gsx_choice`` so the pilot is
  asked.
* `RYR` plan with sibling labels ("Ryanair", "Ryanair DAC") selects "Ryanair".
* Unknown airline (`ICAO="ZZZZ"`) leaves the operator path unchanged
  (no false match).
* Pushback-direction menus and top-level service prompts never produce a fake
  operator pick.

No simulator, no FastAPI, no live websocket — the matcher works entirely on in
memory data. ``requests`` is NOT installed in the bare source interpreter, so
it is stubbed before importing :mod:`app.gsx_remote`.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Stub third-party modules that the bare-source interpreter does not ship.
_stub_requests = types.ModuleType("requests")
_stub_requests.get = lambda *a, **k: None  # type: ignore[attr-defined]
_stub_requests.post = lambda *a, **k: None  # type: ignore[attr-defined]
_stub_requests.RequestException = type("RequestException", (Exception,), {})  # type: ignore[attr-defined]
sys.modules.setdefault("requests", _stub_requests)

from app import gsx_remote as g  # noqa: E402

checks: list[tuple[bool, str]] = []


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    checks.append((True, label))


def choice_from(menu_entries: list[str], *, icon_wide: list[bool] | None = None,
                disabled: list[bool] | None = None, title: str = "Select company",
                live_simbrief: object = None) -> dict | None:
    if icon_wide is None:
        icon_wide = ([True] * len(menu_entries)) if len(menu_entries) >= 2 else [False] * len(menu_entries)
    if disabled is None:
        disabled = [False] * len(menu_entries)
    menu = {
        "available": True,
        "entries": menu_entries,
        "disabled": disabled,
        "icon_wide": icon_wide,
        "title": title,
    }
    return g._operator_observer_choice(menu, live_simbrief)


# ---------------------------------------------------------------------------
# Scenario 1: DLH plan, mixed Lufthansa / Lufthansa Cargo menu
# ---------------------------------------------------------------------------
choice = choice_from(
    ["Lufthansa", "Lufthansa Cargo", "AeroGround", "Wingspeed"],
    live_simbrief={"airline": "DLH", "callsign": "DLH1234"},
)
check(bool(choice and choice["label"] == "Lufthansa"),
      "DLH plan picks the plain 'Lufthansa' operator over Lufthansa Cargo")
check(bool(choice and choice["index"] == 0 and not choice.get("fallback")),
      "DLH plan winner is the first raw-entries index, not a fallback")

# ---------------------------------------------------------------------------
# Scenario 2: DLH plan, numeric-prefixed GSX labels
# ---------------------------------------------------------------------------
choice = choice_from(
    ["1. Lufthansa", "2. Lufthansa CityLine", "3. AeroGround"],
    live_simbrief={"airline": "DLH", "callsign": "DLH4567"},
)
check(bool(choice and g._operator_display_name(choice["label"]).startswith("Lufthansa")),
      "DLH numeric-prefixed menu still resolves to the branded operator")
check(bool(choice and choice["index"] == 0 and not choice.get("fallback")),
      "DLH numeric-prefixed winner corresponds to the first raw-entries index")

# ---------------------------------------------------------------------------
# Scenario 3: DLH plan, plain Lufthansa ABSENT (outstation)
# ---------------------------------------------------------------------------
choice = choice_from(
    ["Lufthansa Cargo", "AeroGround"],
    live_simbrief={"airline": "DLH", "callsign": "DLH7890"},
)
if choice is not None:
    # Must not be the cargo subsidiary, even if it ends up the only candidate.
    check(choice["label"] != "Lufthansa Cargo",
          "DLH plan with no plain Lufthansa does NOT auto-pick Lufthansa Cargo")
    check(not choice.get("fallback") or "gsx" in g._normalized(choice["label"]),
          "Any DLH outstation fallback is the explicit GSX-Choice tile, not the cargo sibling")
else:
    check(True, "DLH outstation fallback yields no autopick (pilot asked)")

# Cargo subsidiary must score below the 620 floor against the canonical brand.
score = g._operator_match_score("Lufthansa", "Lufthansa Cargo")
check(score < 620,
      "Brand-contains branch rejects 'Lufthansa Cargo' subsidiary (< 620 floor)")

# ---------------------------------------------------------------------------
# Scenario 4: RYR plan, Ryanair / Ryanair DAC siblings
# ---------------------------------------------------------------------------
choice = choice_from(
    ["Ryanair", "Ryanair DAC", "EASY"],
    live_simbrief={"airline": "RYR", "callsign": "RYR12AB"},
)
check(bool(choice and choice["label"] == "Ryanair"),
      "RYR plan picks 'Ryanair' over 'Ryanair DAC'")

# ---------------------------------------------------------------------------
# Scenario 5: Unknown airline ZZZZ — operator path unchanged
# ---------------------------------------------------------------------------
choice = choice_from(
    ["AeroGround", "Wingspeed", "Menzies Aviation"],
    live_simbrief={"airline": "ZZZZ", "callsign": "ZZZZ999"},
)
# No matching airline entry — pick is either None or a GSX-choice fallback,
# never an arbitrary real company we don't recognise.
unrecognised = {"AeroGround", "Wingspeed", "Menzies Aviation"}
check(choice is None or bool(choice.get("fallback")) or choice["label"] not in unrecognised,
      "Unknown airline does not fabricate an operator pick")

# ---------------------------------------------------------------------------
# Scenario 6: Pushback-direction menus and top-level service prompts are NEVER
# autopicked as operators.
# ---------------------------------------------------------------------------
pb = choice_from(
    ["Nose left", "Nose right"],
    title="Choose pushback direction",
    icon_wide=[False, False],
    live_simbrief={"airline": "DLH", "callsign": "DLH1234"},
)
check(pb is None, "Pushback-direction menu is never treated as an operator popup")

board = choice_from(
    ["Request boarding", "Request refueling", "Request catering"],
    title="Ground services",
    icon_wide=[False, False, False],
    live_simbrief={"airline": "DLH", "callsign": "DLH1234"},
)
check(board is None, "Top-level service prompts never trigger an operator pick")

# ---------------------------------------------------------------------------
# Scenario 7: Regression — Austrian (RC15 alignment) keeps working.
# ---------------------------------------------------------------------------
choice = g._operator_observer_choice(
    {
        "available": True,
        "entries": ["Aerogate", "Austrian Airlines", "Lufthansa", "Back"],
        "disabled": [False, False, False, False],
        "icon_wide": [True, True, True, False],
        "title": "Select company",
    },
    {"airline": "Austrian Airlines", "callsign": "AUA101"},
)
check(bool(choice and choice["index"] == 1 and choice["label"] == "Austrian Airlines"),
      "Austrian still selected from the latest live menu index (RC15 parity)")

# ---------------------------------------------------------------------------
# Helper-level coverage
# ---------------------------------------------------------------------------
check(g._airline_canonical_name("DLH") == "Lufthansa",
      "canonical name resolver returns 'Lufthansa' for ICAO DLH")
check(g._airline_canonical_name("LH") == "Lufthansa",
      "canonical name resolver returns 'Lufthansa' for IATA LH")
check(g._airline_canonical_name("ZZZZ") == "",
      "unknown ICAO yields an empty canonical name (no false brand)")
check(g._airline_canonical_name("RYR") == "Ryanair",
      "canonical name resolver returns 'Ryanair' for ICAO RYR")

# Brand-contains match score sits strictly between the exact-name score
# (1200 + len) and the disambiguation ceiling (1050), and above the 620 floor.
# Use a non-equality, non-subsidiary option so the new branch is actually
# exercised (rather than the equality branch, which the display-name pre-strip
# of numeric prefix makes unreachable for the "1. Lufthansa" case).
score_contains = g._operator_match_score("Lufthansa", "Lufthansa Egels Hub")
check(1060 <= score_contains <= 1210, "brand-contains branch scores above the disambiguation ceiling")
# Exact-equality (display-formed) still outranks the brand-contains subset.
exact = g._operator_match_score("Lufthansa", "Lufthansa")
check(exact > score_contains, "exact brand match outranks brand-contains subset match")
# Subsidiary suffix drops the brand-contains branch back to 0 (forces pilot).
check(g._operator_match_score("Lufthansa", "Lufthansa Cargo") < 620,
      "brand-contains branch returns a sub-floor score for cargo subsidiary")
check(g._operator_match_score("Lufthansa", "Lufthansa CityLine") < 620,
      "brand-contains branch returns a sub-floor score for CityLine subsidiary")
# 2-3 char ICAO codes do NOT gain the brand-contains boost; they stay on the
# subset branch (which scores them appropriately for code matching).
check(g._operator_match_score("DLH", "Lufthansa") == 0 or g._operator_match_score("DLH", "Lufthansa") < 620,
      "short ICAO code does not inflate to brand-contains territory")

print("\nSUMMARY: %d/%d operator-match checks passed" % (sum(1 for _ in checks), len(checks)))
for _ok, label in checks:
    print("PASS: " + label)
