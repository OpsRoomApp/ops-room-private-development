"""Real-world flight cache – v0.25.48.

In-memory caches with TTL, empty-cache protection, and request deduplication.
Separate stores for live flights, routes, and aircraft metadata.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

_log = logging.getLogger("opsroom.realworld.cache")

# ── TTL constants (seconds) ─────────────────────────────────────────────────

TTL_LIVE = 120       # Live flight positions
TTL_ROUTE = 3600     # Callsign → route (1 hour)
TTL_AIRCRAFT = 86400  # Aircraft metadata (24 hours)

# ── Live flight cache ───────────────────────────────────────────────────────

_live_flights: list[dict[str, Any]] = []
_live_updated: float = 0.0
_live_lock = threading.Lock()


def set_live_flights(flights: list[dict[str, Any]]) -> None:
    """Update the live flight cache.  Empty-cache protection: a zero-length
    list will NOT overwrite an existing healthy non-empty cache.  Call
    force_reset_live_flights() if you really need to clear the cache."""
    global _live_flights, _live_updated
    with _live_lock:
        if not flights and _live_flights:
            _log.warning("[Cache] Refusing to overwrite healthy cache (%d flights) with empty result",
                         len(_live_flights))
            return
        _live_flights = list(flights)
        _live_updated = time.monotonic()


def force_reset_live_flights() -> None:
    """Explicitly clear the live flight cache (e.g. confirmed zero-aircraft response)."""
    global _live_flights, _live_updated
    with _live_lock:
        _live_flights = []
        _live_updated = 0.0


def get_live_flights() -> tuple[list[dict[str, Any]], float, bool]:
    """Return (flights, age_seconds, is_stale).

    is_stale is True when the cache has exceeded TTL_LIVE.
    """
    with _live_lock:
        if not _live_flights:
            return [], 0.0, True
        age = time.monotonic() - _live_updated
        return list(_live_flights), age, age > TTL_LIVE


def live_cache_age() -> float:
    with _live_lock:
        if not _live_updated:
            return 0.0
        return time.monotonic() - _live_updated


def live_cache_count() -> int:
    with _live_lock:
        return len(_live_flights)


# ── Route cache ─────────────────────────────────────────────────────────────

_route_cache: dict[str, tuple[dict[str, Any], float]] = {}
_route_lock = threading.Lock()


def get_route(callsign: str) -> dict[str, Any] | None:
    cs = callsign.strip().upper()
    with _route_lock:
        entry = _route_cache.get(cs)
        if entry is None:
            return None
        data, ts = entry
        if time.monotonic() - ts > TTL_ROUTE:
            _route_cache.pop(cs, None)
            return None
        return data


def set_route(callsign: str, data: dict[str, Any]) -> None:
    cs = callsign.strip().upper()
    if not cs or not data:
        return
    with _route_lock:
        _route_cache[cs] = (dict(data), time.monotonic())


# ── Aircraft metadata cache ─────────────────────────────────────────────────

_aircraft_cache: dict[str, tuple[dict[str, Any], float]] = {}
_aircraft_lock = threading.Lock()


def get_aircraft_meta(key: str) -> dict[str, Any] | None:
    k = key.strip().upper()
    with _aircraft_lock:
        entry = _aircraft_cache.get(k)
        if entry is None:
            return None
        data, ts = entry
        if time.monotonic() - ts > TTL_AIRCRAFT:
            _aircraft_cache.pop(k, None)
            return None
        return data


def set_aircraft_meta(key: str, data: dict[str, Any]) -> None:
    k = key.strip().upper()
    if not k or not data:
        return
    with _aircraft_lock:
        _aircraft_cache[k] = (dict(data), time.monotonic())


# ── Stats accessor ──────────────────────────────────────────────────────────

def all_stats() -> dict[str, Any]:
    """Return a snapshot of cache state for diagnostics."""
    with _live_lock:
        live_age = time.monotonic() - _live_updated if _live_updated else 0.0
        live_count = len(_live_flights)
        live_stale = live_age > TTL_LIVE if _live_updated else True
    with _route_lock:
        route_count = len(_route_cache)
    with _aircraft_lock:
        ac_count = len(_aircraft_cache)
    return {
        "live_count": live_count,
        "live_age_seconds": round(live_age, 1),
        "live_stale": live_stale,
        "live_ttl": TTL_LIVE,
        "route_cached": route_count,
        "aircraft_cached": ac_count,
    }
