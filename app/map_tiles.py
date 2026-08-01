from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

import requests

from .settings_store import app_data_dir, protomaps_key

TILE_URL = "https://api.protomaps.com/tiles/v4/{z}/{x}/{y}.mvt"
CACHE_MAX_AGE = 7 * 24 * 3600
MAX_ZOOM = 15


def _cache_file(z: int, x: int, y: int) -> Path:
    return app_data_dir() / "map_cache" / str(z) / str(x) / f"{y}.mvt"


def tile_status() -> dict[str, Any]:
    return {
        "ok": True,
        "enabled": True,
        "provider": "Protomaps / OpenStreetMap",
        "renderer": "OpenLayers",
        "max_zoom": MAX_ZOOM,
        "key_configured": bool(protomaps_key()),
        "online_required": True,
    }


def get_tile(z: int, x: int, y: int) -> tuple[bytes, dict[str, str]]:
    max_index = (1 << z) - 1 if 0 <= z <= MAX_ZOOM else -1
    if z < 0 or z > MAX_ZOOM or x < 0 or y < 0 or x > max_index or y > max_index:
        raise ValueError("Invalid map tile coordinate")
    key = protomaps_key()
    if not key:
        raise RuntimeError("Protomaps API key is not configured")

    cache = _cache_file(z, x, y)
    if cache.is_file() and time.time() - cache.stat().st_mtime <= CACHE_MAX_AGE:
        return cache.read_bytes(), {"X-OpsRoom-Map-Cache": "HIT", "Cache-Control": "public, max-age=86400"}

    url = TILE_URL.format(z=z, x=x, y=y)
    response = requests.get(
        url,
        params={"key": key},
        timeout=15,
        headers={"User-Agent": "OPS ROOM/0.23.4 map tile proxy"},
    )
    response.raise_for_status()
    content = response.content
    if not content:
        raise RuntimeError("Map provider returned an empty tile")
    cache.parent.mkdir(parents=True, exist_ok=True)
    temp = cache.with_suffix(f".{hashlib.sha1(content[:64]).hexdigest()[:8]}.tmp")
    temp.write_bytes(content)
    temp.replace(cache)
    return content, {"X-OpsRoom-Map-Cache": "MISS", "Cache-Control": "public, max-age=86400"}
