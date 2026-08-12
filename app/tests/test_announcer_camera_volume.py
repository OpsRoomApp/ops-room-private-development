"""Regression tests for #55 -- announcer camera volume.

The old multiplier derived volume from the camera's WORLD position
(``sqrt(cx^2+cy^2+cz^2)`` ~1.4e6 m from the planet origin), so it was pinned
to a constant and never varied with the view. The fix reads FSUIPC 0x026D
CAMERA STATE from the shared telemetry snapshot and applies the Cockpit /
Cabin / External slider per the active camera category (Universal Announcer
parity). Non-flight states hold the last-known category.

Plain-Python PASS/FAIL harness, no network, no audio init.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import app.announcements as ann  # noqa: E402

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


_FIXTURES = [
    # (camera_state, expected_category)
    (2, "cockpit"), (7, "cockpit"),
    (9, "cabin"),
    (3, "external"), (4, "external"), (5, "external"),
    (6, "external"), (8, "external"), (10, "external"), (19, "external"),
    (0, None),       # menu / unknown -> hold
    (17, None),      # replay -> hold
    (99, None),      # unmapped -> hold
]

# --- 1. Category mapping -----------------------------------------------
for state, expected in _FIXTURES:
    if expected is None:
        continue
    check(
        f"state {state} -> {expected}",
        ann._CAMERA_STATE_CATEGORY.get(state) == expected,
    )

# --- 2. Hold behaviour: 0/17 keep the last-known category ----------------
ann._CAMERA_CATEGORY = None
check("hold: default is cockpit before any state", ann._camera_category() == "cockpit")

ann._CAMERA_CATEGORY = "external"
check("hold: menu state (0) keeps last-known", ann._camera_category() == "external")
check("hold: replay state (17) keeps last-known", ann._camera_category() == "external")

ann._CAMERA_CATEGORY = "cabin"
check("hold: unmapped state keeps last-known", ann._camera_category() == "cabin")

# --- 3. Fresh mapped state overrides the hold ----------------------------
_orig_settings = ann.load_settings
_orig_telemetry = ann.read_telemetry


def _with(state: int, enabled: bool = True):
    ann.read_telemetry = lambda force=False: {"camera_state": state}
    ann.load_settings = lambda: {"integrations": {
        "camera_volume_enabled": enabled,
        "camera_volume_cockpit": 100,
        "camera_volume_cabin": 70,
        "camera_volume_external": 40,
    }}


try:
    _with(9)   # cabin
    ann._CAMERA_CATEGORY = "cabin"
    check("mapped state 9 refreshes to cabin", ann._camera_category() == "cabin")
    _with(2)   # cockpit
    ann._CAMERA_CATEGORY = "cabin"
    check("mapped state 2 refreshes to cockpit", ann._camera_category() == "cockpit")
    _with(5)   # external
    ann._CAMERA_CATEGORY = "cockpit"
    check("mapped state 5 refreshes to external", ann._camera_category() == "external")

    # --- 4. Multiplier picks the right slider --------------------------------
    _with(2)   # cockpit
    ann._CAMERA_CATEGORY = None
    check("multiplier: cockpit state -> 1.0", abs(ann._camera_volume_multiplier() - 1.0) < 1e-9)
    _with(9)   # cabin
    ann._CAMERA_CATEGORY = None
    check("multiplier: cabin state -> 0.7", abs(ann._camera_volume_multiplier() - 0.7) < 1e-9)
    _with(5)   # external
    ann._CAMERA_CATEGORY = None
    check("multiplier: external state -> 0.4", abs(ann._camera_volume_multiplier() - 0.4) < 1e-9)
    _with(17, enabled=False)  # feature off
    ann._CAMERA_CATEGORY = None
    check("multiplier: feature disabled -> 1.0", abs(ann._camera_volume_multiplier() - 1.0) < 1e-9)
finally:
    ann.load_settings = _orig_settings
    ann.read_telemetry = _orig_telemetry

print(f"\n{ann.__name__}: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
