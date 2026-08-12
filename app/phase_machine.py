"""Shared flight-phase transition invariants (#85).

The logbook recorder and the flight-watch display each run their own phase
classifier, but WHAT MAY FOLLOW WHAT must be a single shared source of truth.
This table is that invariant layer: TAKEOFF ROLL can never follow APPROACH,
LANDING ROLL is the only legal on-ground phase after the aircraft has been
airborne, and ENROUTE can never appear on short final. Both classifiers use
``transition_allowed`` so a misclassifying proposal is rejected and the last
accepted phase is held instead of flickering the UI.
"""
from __future__ import annotations

from typing import Any

_PHASE_TRANSITIONS: dict[str, set[str]] = {
    # PARKED -> TAXI IN is a deliberate recovery transition. It is used when a
    # temporary frozen provider falsely reported PARKED before fresh telemetry
    # proved the aircraft was still taxiing after landing.
    "PARKED": {"PARKED", "PUSHBACK", "TAXI OUT", "TAKEOFF ROLL", "TAXI IN"},
    "PUSHBACK": {"PUSHBACK", "PARKED", "TAXI OUT", "TAKEOFF ROLL"},
    "TAXI OUT": {"TAXI OUT", "PUSHBACK", "TAKEOFF ROLL", "TAKEOFF", "PARKED"},
    "TAKEOFF ROLL": {"TAKEOFF ROLL", "TAKEOFF", "INITIAL CLIMB", "CLIMB"},
    "TAKEOFF": {"TAKEOFF", "INITIAL CLIMB", "CLIMB"},
    "INITIAL CLIMB": {"INITIAL CLIMB", "CLIMB", "ENROUTE", "CRUISE"},
    "CLIMB": {"CLIMB", "INITIAL CLIMB", "ENROUTE", "CRUISE"},
    "ENROUTE": {"ENROUTE", "CRUISE", "DESCENT CANDIDATE", "DESCENT"},
    "CRUISE": {"CRUISE", "ENROUTE", "DESCENT CANDIDATE", "DESCENT"},
    "DESCENT CANDIDATE": {"DESCENT CANDIDATE", "DESCENT", "ENROUTE", "CRUISE"},
    "DESCENT": {"DESCENT", "APPROACH", "GO-AROUND", "MISSED APPROACH"},
    "APPROACH": {"APPROACH", "DESCENT", "LANDING ROLL", "GO-AROUND", "MISSED APPROACH", "INITIAL CLIMB"},
    "GO-AROUND": {"GO-AROUND", "MISSED APPROACH", "CLIMB", "ENROUTE", "DESCENT", "APPROACH"},
    "MISSED APPROACH": {"MISSED APPROACH", "CLIMB", "ENROUTE", "DESCENT", "APPROACH"},
    "LANDING ROLL": {"LANDING ROLL", "TAXI IN", "PARKED"},
    "TAXI IN": {"TAXI IN", "PARKED"},
}


def transition_allowed(previous: str | None, current: str) -> bool:
    """#85: True when ``current`` may legally follow ``previous``.

    ``previous`` None or equal to ``current`` is always allowed. Unknown
    previous phases fall back to allowing anything (the first proposal of a
    session has no history to constrain it).
    """
    if not previous or previous == current:
        return True
    return current in _PHASE_TRANSITIONS.get(str(previous).upper(), {current})


_GROUND_PHASES = {"PARKED", "PUSHBACK", "TAXI OUT", "TAXI IN", "LANDING ROLL", "TAKEOFF ROLL", "TAXI"}


def holding_phase(previous: str | None, proposal: str, state: dict[str, Any]) -> str:
    """#85: accept ``proposal`` only when the transition is legal.

    On a rejected proposal the last accepted phase (``state["phase"]``) is
    held so the display never flickers into an illegal phase (e.g. ENROUTE on
    short final, TAKEOFF ROLL on touchdown). One recovery escape: a ground
    phase held while the aircraft is provably airborne (``proposal`` airborne)
    is accepted — mirrors the recorder's telemetry-uncertain recovery so a
    stuck latch can never pin the display to the ground.
    """
    if transition_allowed(previous, proposal):
        state["phase"] = proposal
        return proposal
    if previous in _GROUND_PHASES and proposal not in _GROUND_PHASES:
        state["phase"] = proposal
        return proposal
    return str(state.get("phase") or previous or proposal)
