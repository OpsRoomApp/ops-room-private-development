from __future__ import annotations

"""v0.25.9: Lightweight TTL cache + background prewarmer for slow endpoints."""

import logging
import threading
import time
from collections import deque
from typing import Any, Callable

_LOGGER = logging.getLogger("opsroom.preloader")
_LOCK = threading.RLock()
_ENTRIES: dict[str, dict[str, Any]] = {}
_HITS = 0
_MISSES = 0
_RECENT: deque[float] = deque(maxlen=200)
_SOURCES: dict[str, Callable[[], Any]] = {}

PRELOAD_KEYS: list[tuple[str, float]] = [
    ("blackbox.status", 4.0),
    ("flight_watch", 6.0),
    ("dispatch.context", 30.0),
    ("dispatch.recommend", 60.0),
    ("briefing.operational", 120.0),
    ("simbrief.status", 30.0),
    ("logbook.status", 15.0),
    ("netmap.live", 12.0),
    ("ground.services", 8.0),
]


def _key(name: str) -> str:
    return f"module_preloader:{name}"


def get(name: str) -> Any | None:
    global _HITS, _MISSES
    k = _key(name)
    now = time.monotonic()
    with _LOCK:
        entry = _ENTRIES.get(k)
        if not entry or now - entry["fetched_at"] > entry["ttl"]:
            _MISSES += 1
            return None
        _HITS += 1
        return entry["value"]


def set(name: str, value: Any, ttl: float) -> None:
    with _LOCK:
        _ENTRIES[_key(name)] = {"value": value, "fetched_at": time.monotonic(),
                                "ttl": ttl, "err": None}
        _RECENT.append(time.monotonic())


def clear(name=None) -> None:
    with _LOCK:
        if name is None:
            _ENTRIES.clear()
        else:
            _ENTRIES.pop(_key(name), None)


def status(name: str) -> dict[str, Any]:
    k = _key(name)
    now = time.monotonic()
    with _LOCK:
        entry = _ENTRIES.get(k)
        if not entry:
            return {"cached": False, "age_s": None, "ttl_s": None, "err": None}
        age = now - entry["fetched_at"]
        return {"cached": True, "age_s": round(age, 3),
                "ttl_s": entry["ttl"],
                "refresh_in_s": round(max(0.0, entry["ttl"] - age), 3),
                "err": entry.get("err")}


def _preload_one(name: str, fn: Callable[[], Any], ttl: float) -> None:
    started = time.monotonic()
    try:
        value = fn()
    except Exception as exc:
        _LOGGER.warning("[MODULE CACHE preload=%s age=%.2fs status=error err=%s",
                        name, time.monotonic() - started, exc)
        with _LOCK:
            _ENTRIES[_key(name)] = {"value": None, "fetched_at": time.monotonic(),
                                    "ttl": ttl, "err": f"{type(exc).__name__}: {exc}"}
        return
    set(name, value, ttl)
    _LOGGER.info("[MODULE CACHE preload=%s age=%.2fs status=ok ttl=%.0fs",
                 name, time.monotonic() - started, ttl)


def warm(sources: dict[str, Callable[[], Any]]) -> None:
    for name, fn in sources.items():
        ttl = next((t for k, t in PRELOAD_KEYS if k == name), 30.0)
        threading.Thread(target=_preload_one, args=(name, fn, ttl),
                         name=f"OpsRoom-Preload-{name}", daemon=True).start()


def register(name: str, fn: Callable[[], Any]) -> None:
    """v0.25.9: register a refresh factory keyed by name. Called by main.py at startup.
    Sources are drained in prewarm_all() on a background thread.
    """
    _SOURCES[name] = fn


def prewarm_all() -> None:
    """v0.25.9: drain every registered source into the cache. Call from a daemon thread."""
    for name, fn in list(_SOURCES.items()):
        try:
            ttl = next((t for k, t in PRELOAD_KEYS if k == name), 30.0)
            _preload_one(name, fn, ttl)
        except Exception as exc:
            _LOGGER.debug("[PERF] prewarm %s failed: %s", name, exc)


def diagnostics() -> dict[str, Any]:
    now = time.monotonic()
    keys = []
    with _LOCK:
        for k, e in _ENTRIES.items():
            age = now - e["fetched_at"]
            short = k.split(":", 1)[1] if ":" in k else k
            keys.append({"key": short, "age_s": round(age, 3),
                         "ttl_s": e["ttl"],
                         "refresh_in_s": round(max(0.0, e["ttl"] - age), 3),
                         "err": e.get("err")})
    return {"ok": True, "hits": _HITS, "misses": _MISSES,
            "warmed_count": len(_ENTRIES),
            "keys": sorted(keys, key=lambda x: x["key"])}
