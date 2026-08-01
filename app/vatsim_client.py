from __future__ import annotations

import threading
import time
from typing import Any

import requests

VATSIM_DATA_URL = "https://data.vatsim.net/v3/vatsim-data.json"
# The feed is generated every 15 seconds; matching it keeps the split-flap refresh meaningful.
CACHE_SECONDS = 15

_lock = threading.Lock()
_cache: dict[str, Any] | None = None
_cache_time = 0.0
_cache_error: str | None = None


def get_vatsim_data(force: bool = False) -> dict[str, Any]:
    global _cache, _cache_time, _cache_error
    now = time.time()
    with _lock:
        if not force and _cache is not None and now - _cache_time < CACHE_SECONDS:
            data = dict(_cache)
            data["_cache"] = {"age_seconds": round(now - _cache_time, 1), "error": _cache_error, "cache_seconds": CACHE_SECONDS}
            return data
        try:
            response = requests.get(VATSIM_DATA_URL, timeout=12)
            response.raise_for_status()
            _cache = response.json()
            _cache_time = time.time()
            _cache_error = None
        except Exception as exc:
            _cache_error = str(exc)
            if _cache is None:
                raise RuntimeError(f"Could not fetch VATSIM data: {exc}") from exc
        data = dict(_cache)
        data["_cache"] = {"age_seconds": round(time.time() - _cache_time, 1), "error": _cache_error, "cache_seconds": CACHE_SECONDS}
        return data
