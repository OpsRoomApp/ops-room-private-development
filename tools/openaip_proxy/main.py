"""OPS ROOM - OpenAIP enrichment proxy (server-side).

The desktop never needs an OpenAIP key when this proxy is configured: the
desktop sends its bbox to this service, and this service performs the OpenAIP
API call with the server-side key. This mirrors the existing OpenSky VPS proxy
pattern (admin.opsroom.live/api/v1/...) - a public HTTPS endpoint; auth is
optional.

Contract (must match app/openaip_client.py):

    GET /openaip/airspaces?bbox=<west,south,east,north>&limit=<n>
    Header: x-opsroom-proxy-token: <OPENAIP_PROXY_TOKEN>   (optional)

Responses pass the OpenAIP payload through unchanged (GeoJSON
FeatureCollection or legacy JSON), so the desktop parser works identically for
proxy and direct sources.

Environment:
    OPENAIP_API_KEY       required - the server-side OpenAIP API key
    OPENAIP_PROXY_TOKEN   optional - when set, the desktop must present it;
                                    when unset the endpoint is public HTTPS
                                    (same as the realworld-search proxy)
    OPENAIP_CACHE_DIR     optional - disk cache dir (default: ./cache)
    OPENAIP_CACHE_TTL     optional - seconds (default 3600)
    HOST / PORT           optional - bind (default 0.0.0.0:8000)

Run:
    uvicorn main:app --host 0.0.0.0 --port 8000

Put it behind TLS (reverse proxy / Caddy / nginx).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

_LOGGER = logging.getLogger("openaip_proxy")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

API_V3_BASE = "https://api.openaip.net/api/v3"
API_V2_BASE = "https://api.openaip.net/api"

MAX_BBOX_SPAN_LON = 40.0
MAX_BBOX_SPAN_LAT = 24.0
MAX_LIMIT = 1200
UPSTREAM_TIMEOUT = 10.0

_CACHE_LOCK = threading.RLock()
_CACHE: dict[str, dict[str, Any]] = {}
_LAST_DISK_SWEEP: float = 0.0

app = FastAPI(title="OPS ROOM OpenAIP Proxy", version="1.0.0")


def _required_env(name: str) -> str:
    value = str(os.getenv(name, "") or "").strip()
    if not value:
        raise RuntimeError(f"{name} is not set")
    return value


def _proxy_token() -> str:
    return str(os.getenv("OPENAIP_PROXY_TOKEN", "") or "").strip()


def _cache_dir() -> Path:
    path = Path(str(os.getenv("OPENAIP_CACHE_DIR", "cache") or "cache")).resolve()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


def _cache_ttl() -> int:
    try:
        return max(60, int(os.getenv("OPENAIP_CACHE_TTL", "3600")))
    except (TypeError, ValueError):
        return 3600


def _cache_key(bbox: str, limit: int) -> str:
    return hashlib.sha256(f"{bbox}|{limit}".encode("utf-8")).hexdigest()[:24]


def _read_cache(key: str, ttl: int) -> dict[str, Any] | None:
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and time.time() - hit.get("at", 0) < ttl:
            return hit.get("payload")
    path = _cache_dir() / f"{key}.json"
    try:
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if float(payload.get("at") or 0) > time.time() - ttl:
                return payload.get("payload")
    except (OSError, ValueError):
        pass
    return None


def _sweep_disk_cache() -> None:
    """Age-based cleanup of the proxy disk cache (at most once per hour)."""
    global _LAST_DISK_SWEEP
    now = time.time()
    if now - _LAST_DISK_SWEEP < 3600.0:
        return
    _LAST_DISK_SWEEP = now
    ttl = _cache_ttl()
    try:
        for file_path in _cache_dir().glob("*.json"):
            try:
                if file_path.stat().st_mtime < now - ttl * 2:
                    file_path.unlink(missing_ok=True)
            except OSError:
                continue
    except OSError:
        pass


def _write_cache(key: str, payload: Any) -> None:
    _sweep_disk_cache()
    with _CACHE_LOCK:
        _CACHE[key] = {"at": time.time(), "payload": payload}
        if len(_CACHE) > 400:
            cutoff = time.time() - _cache_ttl()
            for stale in [k for k, v in _CACHE.items() if v.get("at", 0) < cutoff]:
                _CACHE.pop(stale, None)
    try:
        (_cache_dir() / f"{key}.json").write_text(
            json.dumps({"at": time.time(), "payload": payload}), encoding="utf-8")
    except OSError:
        pass


def _upstream_get(url: str, params: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    """Upstream GET with one 429 retry (honoring Retry-After when present)."""
    headers = {"x-openaip-api-key": key, "Accept": "application/json",
               "User-Agent": "opsroom-map-enrichment-proxy/1.0"}
    for attempt in (1, 2):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=UPSTREAM_TIMEOUT)
        except requests.Timeout:
            raise RuntimeError(f"{label} upstream timeout")
        except requests.RequestException as exc:
            raise RuntimeError(f"{label} upstream network error: {type(exc).__name__}")
        if resp.status_code == 429 and attempt == 1:
            delay = 1.0
            retry_after = resp.headers.get("Retry-After")
            try:
                delay = min(10.0, max(0.5, float(retry_after)))
            except (TypeError, ValueError):
                pass
            _LOGGER.warning("%s rate limited, retrying in %.1fs", label, delay)
            time.sleep(delay)
            continue
        if resp.status_code in (401, 403):
            raise RuntimeError(f"{label} upstream auth failed (HTTP {resp.status_code})")
        if not resp.ok:
            raise RuntimeError(f"{label} upstream HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError:
            raise RuntimeError(f"{label} upstream returned non-JSON")
    raise RuntimeError(f"{label} upstream rate limited after retry")


def _parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    try:
        a = [float(x.strip()) for x in str(bbox).split(",")]
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="bbox must be 4 comma-separated numbers")
    if len(a) != 4:
        raise HTTPException(status_code=400, detail="bbox must be west,south,east,north")
    min_lon, min_lat, max_lon, max_lat = a
    if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180):
        raise HTTPException(status_code=400, detail="lon out of range")
    if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
        raise HTTPException(status_code=400, detail="lat out of range")
    if min_lon >= max_lon or min_lat >= max_lat:
        raise HTTPException(status_code=400, detail="bbox min must be < max")
    if (max_lon - min_lon) > MAX_BBOX_SPAN_LON or (max_lat - min_lat) > MAX_BBOX_SPAN_LAT:
        raise HTTPException(status_code=400, detail="bbox span too large")
    return min_lon, min_lat, max_lon, max_lat


@app.exception_handler(RuntimeError)
def _on_runtime_error(_request: Request, exc: RuntimeError) -> JSONResponse:
    _LOGGER.warning("proxy error: %s", exc)
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "openaip-proxy",
        "key_configured": bool(os.getenv("OPENAIP_API_KEY", "")),
        "token_configured": bool(_proxy_token()),
        "cache_keys": len(_CACHE),
        "time": time.time(),
    }


@app.get("/openaip/airspaces")
def airspaces(bbox: str = Query(...), limit: int = Query(900),
              x_opsroom_proxy_token: str = Header(default="", alias="x-opsroom-proxy-token")) -> Any:
    expected = _proxy_token()
    if expected and not hmac.compare_digest(x_opsroom_proxy_token or "", expected):
        raise HTTPException(status_code=401, detail="invalid proxy token")
    key = str(os.getenv("OPENAIP_API_KEY", "") or "").strip()
    if not key:
        raise HTTPException(status_code=500, detail="server OpenAIP key is not configured")
    min_lon, min_lat, max_lon, max_lat = _parse_bbox(bbox)
    limit = max(1, min(int(limit or 900), MAX_LIMIT))

    cache_key = _cache_key(bbox, limit)
    cached = _read_cache(cache_key, _cache_ttl())
    if cached is not None:
        return cached

    params_v3 = {"bbox": f"{min_lon},{min_lat},{max_lon},{max_lat}", "limit": limit}
    try:
        payload = _upstream_get(f"{API_V3_BASE}/airspaces", params_v3, key, "v3")
    except Exception:
        # Legacy v2 fallback (center + radius).
        center_lon = (min_lon + max_lon) / 2.0
        center_lat = (min_lat + max_lat) / 2.0
        radius_km = max(1.0, math.hypot(max_lon - min_lon, max_lat - min_lat) * 111.0 / 2.0)
        payload = _upstream_get(
            f"{API_V2_BASE}/airspaces",
            {"lat": round(center_lat, 5), "lon": round(center_lon, 5),
             "radius": round(radius_km, 1), "format": "json"},
            key, "v2")

    if not isinstance(payload, dict):
        payload = {"type": "FeatureCollection", "features": []}
    _write_cache(cache_key, payload)
    return payload
