from __future__ import annotations

import json
import math
import re
import threading
import time
from pathlib import Path
from typing import Any

import requests

from .settings_store import app_data_dir

URL = "https://raw.githubusercontent.com/vatsimnetwork/vatspy-data-project/master/Boundaries.geojson"
_CACHE_TTL = 7 * 24 * 3600
_LOCK = threading.RLock()
_MEMORY: list[dict[str, Any]] | None = None
_LAST_ATTEMPT = 0.0
_LAST_ERROR = ""


def _path() -> Path:
    folder = app_data_dir() / "vatspy"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "Boundaries.geojson"


def _norm(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _tokens(properties: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for key, value in properties.items():
        if isinstance(value, (str, int)):
            n = _norm(value)
            if 2 <= len(n) <= 24:
                result.add(n)
            for part in re.split(r"[^A-Z0-9]+", str(value).upper()):
                if 2 <= len(part) <= 12:
                    result.add(part)
        key_n = _norm(key)
        if key_n:
            result.add(key_n)
    return result


def _load_file(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    features = raw.get("features") if isinstance(raw, dict) else None
    return [f for f in (features or []) if isinstance(f, dict) and isinstance(f.get("geometry"), dict)]


def load_boundaries(force: bool = False) -> list[dict[str, Any]]:
    global _MEMORY, _LAST_ATTEMPT, _LAST_ERROR
    with _LOCK:
        if _MEMORY is not None and not force:
            return _MEMORY
        path = _path()
        age = time.time() - path.stat().st_mtime if path.exists() else 10**12
        should_fetch = force or age > _CACHE_TTL
        if should_fetch and time.monotonic() - _LAST_ATTEMPT > 60:
            _LAST_ATTEMPT = time.monotonic()
            try:
                response = requests.get(URL, timeout=12, headers={"User-Agent": "OPS-ROOM/0.13"})
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
                    raise ValueError("VATSpy boundary response was not valid GeoJSON")
                temp = path.with_suffix(".tmp")
                temp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
                temp.replace(path)
                _LAST_ERROR = ""
            except Exception as exc:
                _LAST_ERROR = f"{type(exc).__name__}: {exc}"
        try:
            _MEMORY = _load_file(path) if path.exists() else []
        except Exception as exc:
            _LAST_ERROR = f"{type(exc).__name__}: {exc}"
            _MEMORY = []
        return _MEMORY


def _iter_points(coords: Any):
    if isinstance(coords, list):
        if len(coords) >= 2 and all(isinstance(x, (int, float)) for x in coords[:2]):
            yield float(coords[0]), float(coords[1])
        else:
            for child in coords:
                yield from _iter_points(child)


def centroid(geometry: dict[str, Any]) -> tuple[float, float] | None:
    points = list(_iter_points(geometry.get("coordinates")))
    if not points:
        return None
    # Arithmetic centroid is sufficient for map-label placement. Sector polygon
    # rendering uses the original geometry, so no operational shape is inferred.
    lon = sum(p[0] for p in points) / len(points)
    lat = sum(p[1] for p in points) / len(points)
    if math.isfinite(lat) and math.isfinite(lon):
        return lat, lon
    return None


def find_boundary(callsign: str) -> dict[str, Any] | None:
    features = load_boundaries()
    call = str(callsign or "").upper()
    bases = []
    stripped = re.sub(r"_(CTR|FSS|APP|DEP|TWR|GND|DEL)$", "", call)
    for candidate in (call, stripped, call.split("_")[0], stripped.split("_")[0]):
        n = _norm(candidate)
        if n and n not in bases:
            bases.append(n)
    best: tuple[int, dict[str, Any]] | None = None
    for feature in features:
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        tokens = _tokens(props)
        score = 0
        for base in bases:
            if base in tokens:
                score = max(score, 100 + len(base))
            elif any(token.startswith(base) or base.startswith(token) for token in tokens if len(token) >= 3):
                score = max(score, 40 + min(len(base), max((len(t) for t in tokens), default=0)))
        if score and (best is None or score > best[0]):
            best = (score, feature)
    return best[1] if best else None


def status() -> dict[str, Any]:
    path = _path()
    return {
        "available": bool(load_boundaries()),
        "features": len(_MEMORY or []),
        "cache_path": str(path),
        "cache_age_hours": round((time.time() - path.stat().st_mtime) / 3600, 1) if path.exists() else None,
        "last_error": _LAST_ERROR or None,
        "source": "VATSIM VATSpy Data Project / Boundaries.geojson",
    }
