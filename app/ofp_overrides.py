"""OPS ROOM -- manual override store for the live OFP completion panel.

The live OFP builder (``ofp_actuals.py``) is deliberately pure: it renders
phase-detection and telemetry values, never writes them.  Manual overrides are
the sanctioned way a pilot corrects an actual OUT/OFF/ON/IN time, a weight or
a fuel reading without touching the recorder or phase detection.

This module owns that small writable side:

* a strict whitelist of override keys (``times:*``, ``weights:*``, ``fuel:*``);
* strict value validation (HHMM / full-ISO for times, finite numbers for
  weights and fuel);
* one override set per recorder id, persisted to
  ``app_data_dir()/ofp_overrides.json`` so overrides survive app restarts.

The GET endpoint merges the active recorder's overrides into the payload with
``source="manual"``; the POST endpoint writes them.  No telemetry, no phase
detection, no recorder mutation happens here.
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_LOGGER = logging.getLogger("opsroom.ofp_overrides")

# Whitelist.  Keys mirror the frontend ``data-ofp-live`` cell keys minus the
# trailing ``:actual`` column, so the frontend and backend agree by contract.
_TIME_KEYS = {"times:out", "times:off", "times:on", "times:in"}
_WEIGHT_KEYS = {"weights:pax", "weights:zfw", "weights:tow", "weights:ldw"}
_FUEL_KEYS = {"fuel:ramp", "fuel:takeoff", "fuel:landing", "fuel:blockin"}
ALL_KEYS = _TIME_KEYS | _WEIGHT_KEYS | _FUEL_KEYS

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?$")
_HHMM_RE = re.compile(r"^(\d{2}):?(\d{2})Z?$")

_lock = threading.Lock()
_store: dict[str, dict[str, Any]] = {}
_load_attempted = False
_store_path: Path | None = None


def store_path() -> Path:
    global _store_path
    if _store_path is None:
        try:
            from .settings_store import app_data_dir

            _store_path = app_data_dir() / "ofp_overrides.json"
        except Exception:
            _store_path = Path("ofp_overrides.json")
    return _store_path


def _load() -> dict[str, dict[str, Any]]:
    global _load_attempted
    if _load_attempted:
        return _store
    _load_attempted = True
    try:
        path = store_path()
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for rid, values in raw.items():
                    if isinstance(rid, str) and isinstance(values, dict):
                        _store[rid] = {k: v for k, v in values.items() if k in ALL_KEYS}
    except Exception as exc:
        _LOGGER.debug("ofp_overrides load skipped: %s", exc)
    return _store


def _persist() -> None:
    try:
        path = store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_store, indent=2), encoding="utf-8")
    except Exception as exc:
        _LOGGER.debug("ofp_overrides persist skipped: %s", exc)


def _normalize_time(value: Any) -> str | None:
    """Normalize a manual time to ``HHMM`` or a full ``Z`` ISO timestamp."""
    raw = str(value or "").strip()
    if not raw:
        return None
    if _ISO_RE.match(raw):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            return None
    match = _HHMM_RE.match(raw)
    if not match:
        return None
    hh, mm = int(match.group(1)), int(match.group(2))
    if hh > 23 or mm > 59:
        return None
    return f"{hh:02d}{mm:02d}"


def _normalize_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, 4)


def normalize_value(key: str, value: Any) -> tuple[Any, str | None]:
    """Return (normalized, None) on success or (None, error) on failure."""
    if key in _TIME_KEYS:
        normalized = _normalize_time(value)
        if normalized is None:
            return None, "time must be HHMM (e.g. 1617) or a full ISO timestamp"
        return normalized, None
    number = _normalize_number(value)
    if number is None:
        return None, "must be a finite number"
    if number < 0:
        return None, "must not be negative"
    return number, None


def validate_overrides(values: Any) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate an incoming override map; returns (valid, errors)."""
    if not isinstance(values, dict):
        return {}, {"overrides": "expected an object of key/value pairs"}
    valid: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for key, value in values.items():
        key = str(key or "").strip()
        if key not in ALL_KEYS:
            errors[key] = "unknown override key"
            continue
        normalized, error = normalize_value(key, value)
        if error is not None or normalized is None:
            errors[key] = error or "invalid value"
            continue
        valid[key] = normalized
    return valid, errors


def get_overrides(recorder_id: str) -> dict[str, Any]:
    if not recorder_id:
        return {}
    with _lock:
        return dict(_load().get(str(recorder_id)) or {})


def set_overrides(recorder_id: str, values: Any) -> tuple[dict[str, Any], dict[str, str]]:
    """Merge validated overrides into the recorder's set; returns (all, errors)."""
    valid, errors = validate_overrides(values)
    if not recorder_id:
        return {}, {"recorder": "no active or completed recorder to attach overrides to"}
    if not valid:
        return get_overrides(recorder_id), errors
    with _lock:
        current = dict(_load().get(str(recorder_id)) or {})
        current.update(valid)
        _store[str(recorder_id)] = current
        _persist()
        return dict(current), errors


def remove_override(recorder_id: str, key: str) -> dict[str, Any]:
    key = str(key or "").strip()
    with _lock:
        current = dict(_load().get(str(recorder_id)) or {})
        current.pop(key, None)
        if current:
            _store[str(recorder_id)] = current
        else:
            _store.pop(str(recorder_id), None)
        _persist()
        return dict(current)


def clear_overrides(recorder_id: str) -> None:
    with _lock:
        _store.pop(str(recorder_id), None)
        _persist()


def prune_orphaned(known_ids: Iterable[str]) -> int:
    """Drop override sets whose recorder id is no longer a known flight.

    Overrides are keyed by the Logbook recorder/entry id. Once a flight is
    deleted (or never made it into the Logbook), its override set is
    unreachable and would accumulate forever in ``ofp_overrides.json``. Call
    with the current set of valid flight ids (e.g. ``logbook.entry_ids()``)
    at app startup. Returns the number of override sets removed.
    """
    known = {str(item) for item in known_ids if item}
    removed = 0
    with _lock:
        _load()
        for rid in [str(rid) for rid in _store if str(rid) not in known]:
            _store.pop(rid, None)
            removed += 1
        if removed:
            _persist()
    return removed
