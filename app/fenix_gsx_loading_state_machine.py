"""OPS ROOM v0.20.0 Fenix/GSX loading state machine.

Purpose
-------
Fixes the Fenix departure loading deadlock where fuel/refuel/catering complete,
but passengers/cargo stay at zero and GSX boarding is never advanced.

Important invariant
-------------------
The GSX boarding action is one-shot. Once boarding has been requested during a
loading session, this state machine will never request it again until reset().

This module is deliberately dependency-free so it can be dropped into the OPS
ROOM backend and called from the existing Fenix/GSX polling loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
import time
from typing import Any, Iterable, Mapping, Optional


class FenixGsxLoadingPhase(str, Enum):
    IDLE = "FENIX_LOADING_IDLE"
    STARTED = "FENIX_LOADING_STARTED"
    WAITING_REFUEL_CATERING = "WAITING_REFUEL_CATERING"
    READY_FOR_BOARDING = "READY_FOR_BOARDING"
    BOARDING_REQUESTED = "BOARDING_REQUESTED"
    MONITORING_BOARDING = "MONITORING_BOARDING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


@dataclass(frozen=True)
class GsxMenuEntry:
    """One visible GSX menu row."""

    index: int
    label: str
    disabled: bool = False


@dataclass(frozen=True)
class FenixGsxLoadingSnapshot:
    """Normalized per-poll state from Fenix EFB/LVars and GSX remote/menu.

    Values should be best-effort. Unknown values may be passed as None.
    """

    aircraft_family: str = ""
    loading_active: bool = False
    fenix_loading_started: bool = False

    fuel_target_reached: Optional[bool] = None
    refuel_complete: Optional[bool] = None
    catering_complete: Optional[bool] = None

    pax_loaded: Optional[int] = None
    pax_target: Optional[int] = None
    cargo_loaded: Optional[float] = None
    cargo_target: Optional[float] = None

    # Official GSX Remote API v2 service board signals. These are deliberately
    # separated from pax/cargo progress so a cargo/fuel/catering update can never
    # be mistaken for passenger boarding.
    boarding_service_active: bool = False
    boarding_service_available: bool = False

    gsx_status_text: str = ""
    gsx_menu_entries: tuple[GsxMenuEntry, ...] = ()

    now: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        # v0.20.0 field fix: the live GSX poll path may pass dict-style
        # menu rows directly into the snapshot constructor. Normalize them here
        # so the phase machine never faults on entry.label / entry.disabled.
        object.__setattr__(self, "gsx_menu_entries", tuple(_coerce_menu_entries(self.gsx_menu_entries or ())))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "FenixGsxLoadingSnapshot":
        """Build from existing dict-style OPS ROOM status objects."""

        def _bool(key: str) -> Optional[bool]:
            value = data.get(key)
            if value is None:
                return None
            return bool(value)

        def _int(key: str) -> Optional[int]:
            value = data.get(key)
            if value in (None, ""):
                return None
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return None

        def _float(key: str) -> Optional[float]:
            value = data.get(key)
            if value in (None, ""):
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        menu_raw = data.get("gsx_menu_entries") or data.get("menu_entries") or []
        entries = tuple(_coerce_menu_entries(menu_raw))
        return cls(
            aircraft_family=str(data.get("aircraft_family") or data.get("aircraft") or ""),
            loading_active=bool(data.get("loading_active") or data.get("fenix_loading_active")),
            fenix_loading_started=bool(data.get("fenix_loading_started") or data.get("loading_started")),
            fuel_target_reached=_bool("fuel_target_reached"),
            refuel_complete=_bool("refuel_complete"),
            catering_complete=_bool("catering_complete"),
            pax_loaded=_int("pax_loaded"),
            pax_target=_int("pax_target"),
            cargo_loaded=_float("cargo_loaded"),
            cargo_target=_float("cargo_target"),
            boarding_service_active=bool(data.get("boarding_service_active")),
            boarding_service_available=bool(data.get("boarding_service_available")),
            gsx_status_text=str(data.get("gsx_status_text") or data.get("status_text") or ""),
            gsx_menu_entries=entries,
            now=float(data.get("now") or time.monotonic()),
        )


@dataclass(frozen=True)
class FenixGsxLoadingDecision:
    """Action requested by the state machine."""

    phase: FenixGsxLoadingPhase
    action: str = "none"
    menu_index: Optional[int] = None
    reason: str = ""
    changed: bool = False
    diagnostic: dict[str, Any] = field(default_factory=dict)


_BOARDING_POSITIVE_RE = re.compile(
    r"\b(request|start|begin|continue|resume)?\s*(boarding|board\s+passengers|passenger\s+boarding)\b",
    re.I,
)
_BOARDING_NEGATIVE_RE = re.compile(
    r"\b(deboarding|de-board|unboard|stop\s+boarding|cancel\s+boarding|boarding\s+completed|boarding\s+complete)\b",
    re.I,
)
_REFUEL_DONE_RE = re.compile(r"\b(refuel(?:ling|ing)?|fuel)\b.*\b(done|complete|completed|target\s+reached|finished)\b", re.I)
_CATERING_DONE_RE = re.compile(r"\bcatering\b.*\b(done|complete|completed|finished)\b", re.I)
_BOARDING_ACTIVE_RE = re.compile(r"\b(boarding|boarding\s+in\s+progress|passengers\s+boarding)\b", re.I)
_COMPLETE_RE = re.compile(r"\b(loading\s+complete|boarding\s+complete|boarding\s+completed|ready\s+for\s+pushback|services\s+complete)\b", re.I)


class FenixGsxLoadingStateMachine:
    """Stateful controller for one Fenix/GSX departure loading session."""

    def __init__(
        self,
        *,
        refuel_catering_timeout_s: float = 20 * 60,
        boarding_start_timeout_s: float = 7 * 60,
        loading_complete_timeout_s: float = 60 * 60,
    ) -> None:
        self.refuel_catering_timeout_s = float(refuel_catering_timeout_s)
        self.boarding_start_timeout_s = float(boarding_start_timeout_s)
        self.loading_complete_timeout_s = float(loading_complete_timeout_s)
        self.reset()

    def reset(self) -> None:
        self.phase = FenixGsxLoadingPhase.IDLE
        self.phase_started_at = time.monotonic()
        self.session_started_at = self.phase_started_at
        self.boarding_action_sent = False
        self.last_boarding_menu_index: Optional[int] = None
        self.failure_reason = ""
        self._last_decision_key: tuple[Any, ...] | None = None

    def update(self, snapshot: FenixGsxLoadingSnapshot | Mapping[str, Any]) -> FenixGsxLoadingDecision:
        if not isinstance(snapshot, FenixGsxLoadingSnapshot):
            snapshot = FenixGsxLoadingSnapshot.from_mapping(snapshot)

        previous = self.phase
        reason = ""
        action = "none"
        menu_index: Optional[int] = None

        if not _is_fenix(snapshot.aircraft_family):
            self.reset()
            return self._decision(snapshot, previous, reason="non-Fenix aircraft, state idle")

        if not snapshot.loading_active and not snapshot.fenix_loading_started:
            self.reset()
            return self._decision(snapshot, previous, reason="loading inactive")

        if self.phase == FenixGsxLoadingPhase.IDLE:
            self._transition(FenixGsxLoadingPhase.STARTED, snapshot.now)
            reason = "Fenix loading session detected"

        if self.phase == FenixGsxLoadingPhase.STARTED:
            self._transition(FenixGsxLoadingPhase.WAITING_REFUEL_CATERING, snapshot.now)
            reason = "waiting for refuel/catering phase"

        if self.phase == FenixGsxLoadingPhase.WAITING_REFUEL_CATERING:
            if self._timed_out(snapshot.now, self.refuel_catering_timeout_s):
                self._fail(snapshot.now, "refuel/catering phase timeout")
            elif self._refuel_and_catering_complete(snapshot):
                if self._boarding_progressing(snapshot):
                    self._transition(FenixGsxLoadingPhase.MONITORING_BOARDING, snapshot.now)
                    reason = "boarding already active after refuel/catering"
                else:
                    self._transition(FenixGsxLoadingPhase.READY_FOR_BOARDING, snapshot.now)
                    reason = "refuel/catering complete; ready to request passenger boarding"

        if self.phase == FenixGsxLoadingPhase.READY_FOR_BOARDING:
            # v0.24.26: READY_FOR_BOARDING must not become a dead-end.
            # Fenix/GSX can complete loading without keeping an official menu
            # row visible, so Fenix-readable progress is authoritative here.
            if self._loading_complete(snapshot):
                self._transition(FenixGsxLoadingPhase.COMPLETE, snapshot.now)
                reason = "Fenix EFB loading complete while waiting for GSX boarding menu"
            elif self._boarding_progressing(snapshot):
                self._transition(FenixGsxLoadingPhase.MONITORING_BOARDING, snapshot.now)
                reason = "boarding/load already moving while waiting for GSX menu"
            else:
                boarding_entry = _find_boarding_entry(snapshot.gsx_menu_entries)
                if snapshot.boarding_service_available and not self.boarding_action_sent:
                    self.boarding_action_sent = True
                    self._transition(FenixGsxLoadingPhase.BOARDING_REQUESTED, snapshot.now)
                    action = "gsx_service_trigger"
                    reason = "one-shot GSX Remote API Boarding trigger"
                elif boarding_entry and not self.boarding_action_sent:
                    self.boarding_action_sent = True
                    self.last_boarding_menu_index = boarding_entry.index
                    self._transition(FenixGsxLoadingPhase.BOARDING_REQUESTED, snapshot.now)
                    action = "gsx_menu_pick"
                    menu_index = boarding_entry.index
                    reason = f"one-shot GSX boarding request via menu index {boarding_entry.index}: {boarding_entry.label}"
                elif self.boarding_action_sent:
                    self._transition(FenixGsxLoadingPhase.BOARDING_REQUESTED, snapshot.now)
                    reason = "boarding already requested, suppressing duplicate action"
                else:
                    reason = "waiting for official GSX boarding menu option"

        if self.phase == FenixGsxLoadingPhase.BOARDING_REQUESTED:
            if self._loading_complete(snapshot):
                self._transition(FenixGsxLoadingPhase.COMPLETE, snapshot.now)
                reason = "Fenix EFB loading complete after GSX boarding request"
            elif self._timed_out(snapshot.now, self.boarding_start_timeout_s):
                self._fail(snapshot.now, "boarding did not start after one-shot request")
            elif self._boarding_progressing(snapshot):
                self._transition(FenixGsxLoadingPhase.MONITORING_BOARDING, snapshot.now)
                reason = "boarding progress detected"

        if self.phase == FenixGsxLoadingPhase.MONITORING_BOARDING:
            if self._timed_out(snapshot.now, self.loading_complete_timeout_s):
                self._fail(snapshot.now, "loading completion timeout")
            elif self._loading_complete(snapshot):
                self._transition(FenixGsxLoadingPhase.COMPLETE, snapshot.now)
                reason = "Fenix/GSX loading complete"

        if self.phase == FenixGsxLoadingPhase.FAILED:
            reason = self.failure_reason or reason or "Fenix/GSX loading failed"

        return self._decision(snapshot, previous, action=action, menu_index=menu_index, reason=reason)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "boarding_action_sent": self.boarding_action_sent,
            "last_boarding_menu_index": self.last_boarding_menu_index,
            "failure_reason": self.failure_reason,
            "phase_elapsed_s": round(time.monotonic() - self.phase_started_at, 1),
            "session_elapsed_s": round(time.monotonic() - self.session_started_at, 1),
        }

    def _transition(self, phase: FenixGsxLoadingPhase, now: float) -> None:
        if phase != self.phase:
            self.phase = phase
            self.phase_started_at = now

    def _fail(self, now: float, reason: str) -> None:
        self.failure_reason = reason
        self._transition(FenixGsxLoadingPhase.FAILED, now)

    def _timed_out(self, now: float, timeout_s: float) -> bool:
        return (now - self.phase_started_at) > timeout_s

    def _decision(
        self,
        snapshot: FenixGsxLoadingSnapshot,
        previous: FenixGsxLoadingPhase,
        *,
        action: str = "none",
        menu_index: Optional[int] = None,
        reason: str = "",
    ) -> FenixGsxLoadingDecision:
        diag = self.diagnostics()
        diag.update(
            {
                "aircraft_family": snapshot.aircraft_family,
                "fuel_target_reached": snapshot.fuel_target_reached,
                "refuel_complete": snapshot.refuel_complete,
                "catering_complete": snapshot.catering_complete,
                "pax_loaded": snapshot.pax_loaded,
                "pax_target": snapshot.pax_target,
                "cargo_loaded": snapshot.cargo_loaded,
                "cargo_target": snapshot.cargo_target,
                "boarding_service_active": snapshot.boarding_service_active,
                "boarding_service_available": snapshot.boarding_service_available,
                "gsx_status_text": snapshot.gsx_status_text,
            }
        )
        return FenixGsxLoadingDecision(
            phase=self.phase,
            action=action,
            menu_index=menu_index,
            reason=reason,
            changed=(self.phase != previous),
            diagnostic=diag,
        )

    @staticmethod
    def _refuel_and_catering_complete(snapshot: FenixGsxLoadingSnapshot) -> bool:
        text = snapshot.gsx_status_text or ""
        refuel_done = snapshot.refuel_complete is True or snapshot.fuel_target_reached is True or bool(_REFUEL_DONE_RE.search(text))
        catering_done = snapshot.catering_complete is True or bool(_CATERING_DONE_RE.search(text))

        # Some Fenix flows do not expose catering as a separate value. If fuel is
        # complete and GSX is no longer reporting active catering, allow progression.
        if refuel_done and snapshot.catering_complete is None and "catering" not in text.lower():
            catering_done = True

        return bool(refuel_done and catering_done)

    @staticmethod
    def _pax_and_cargo_still_zero(snapshot: FenixGsxLoadingSnapshot) -> bool:
        pax_zero = snapshot.pax_loaded in (None, 0)
        cargo_zero = snapshot.cargo_loaded in (None, 0, 0.0)
        pax_target_known = snapshot.pax_target is None or snapshot.pax_target > 0
        cargo_target_known = snapshot.cargo_target is None or snapshot.cargo_target >= 0
        return bool(pax_zero and cargo_zero and pax_target_known and cargo_target_known)

    @staticmethod
    def _boarding_progressing(snapshot: FenixGsxLoadingSnapshot) -> bool:
        # Boarding progress must mean passenger boarding. Cargo/fuel/catering
        # progress is not enough: that regression caused pax 0/target to jump to
        # MONITORING_BOARDING and skip the actual GSX Boarding trigger.
        if snapshot.boarding_service_active:
            return True
        if snapshot.pax_loaded is not None and snapshot.pax_loaded > 0:
            return True
        text = snapshot.gsx_status_text or ""
        active_phrase = re.search(r"\b(boarding\s+in\s+progress|passengers\s+boarding|pax\s+[1-9]\d*\s*/\s*\d+)\b", text, re.I)
        return bool(active_phrase and not _BOARDING_NEGATIVE_RE.search(text))

    @staticmethod
    def _loading_complete(snapshot: FenixGsxLoadingSnapshot) -> bool:
        pax_complete = snapshot.pax_target is not None and snapshot.pax_loaded is not None and snapshot.pax_target > 0 and snapshot.pax_loaded >= snapshot.pax_target
        cargo_complete = snapshot.cargo_target is not None and snapshot.cargo_loaded is not None and snapshot.cargo_loaded >= snapshot.cargo_target
        fuel_blocking = snapshot.fuel_target_reached is False or snapshot.refuel_complete is False
        # GSX status text such as "boarding complete" is only a hint. It must not
        # advance the Fenix phase to COMPLETE by itself, because the Fenix EFB can
        # still be in LOADING AIRCRAFT while GSX passenger counters have reached
        # their target. The outer coordinator performs the safe settle/fallback.
        text = snapshot.gsx_status_text or ""
        gsx_complete_hint = bool(_COMPLETE_RE.search(text))
        if pax_complete and not fuel_blocking and (snapshot.cargo_target in (None, 0) or cargo_complete or gsx_complete_hint):
            return True
        if gsx_complete_hint and not fuel_blocking and pax_complete:
            return True
        return False


def _coerce_menu_entries(raw: Iterable[Any]) -> Iterable[GsxMenuEntry]:
    for fallback_index, item in enumerate(raw):
        if isinstance(item, GsxMenuEntry):
            yield item
            continue
        if isinstance(item, Mapping):
            label = str(item.get("label") or item.get("text") or item.get("title") or "")
            index = item.get("index", fallback_index)
            disabled = bool(item.get("disabled") or item.get("is_disabled"))
        else:
            label = str(item)
            index = fallback_index
            disabled = False
        try:
            index = int(index)
        except (TypeError, ValueError):
            index = fallback_index
        yield GsxMenuEntry(index=index, label=label.strip(), disabled=disabled)


def _find_boarding_entry(entries: Iterable[Any]) -> Optional[GsxMenuEntry]:
    # Be defensive: production callers can provide GsxMenuEntry, dict rows,
    # plain labels, or mixed lists depending on whether the source is the
    # official GSX Remote API, the legacy menu file, or OPS ROOM's own cache.
    for entry in _coerce_menu_entries(entries):
        label = entry.label or ""
        if entry.disabled:
            continue
        if _BOARDING_NEGATIVE_RE.search(label):
            continue
        if _BOARDING_POSITIVE_RE.search(label):
            return entry
    return None


def _is_fenix(aircraft_family: str) -> bool:
    value = (aircraft_family or "").lower()
    return "fenix" in value or "fnx" in value or "a320" in value or "a321" in value
