"""OpenAIP enrichment client for the OPS ROOM live map.

v0.25.x: the previously dormant OpenAIP scaffolding becomes an *optional*
enrichment source for the ``/api/livemap/layers/airspaces`` layer. This module:

* routes through the owner's VPS proxy (default URL baked into the build,
  mirroring the existing OpenSky VPS proxy pattern), keeping the API key
  server-side; no token or user configuration is required
* silently falls back to a direct OpenAIP key only when one is embedded
  (managed build secret or optional user setting)
* fetches airspace polygons for the current map viewport (bbox)
* caches responses on disk with a TTL to respect provider rate limits
* retries 429 responses once with backoff
* reports runtime status/metadata so the map can label its data source
* never raises into the caller - failures degrade to "not ok" and the caller
  falls back to the built-in local aviation database

OpenAIP is a community-maintained, CC BY-NC 4.0 licensed database. Data from
this module is a visualization/planning supplement and must never be presented
as an authoritative FAA/regulated source.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .settings_store import app_data_dir, load_settings

_API_V3_BASE = "https://api.openaip.net/api/v3"
_API_V2_BASE = "https://api.openaip.net/api"

# Default owner VPS proxy endpoint, baked into the build. Mirrors the existing
# VPS proxy pattern the FAA NMS integration uses (opsroom.live/api/v1/...) -
# the OpenAIP key lives only on the server, and the public endpoint needs no
# token by default.
_DEFAULT_PROXY_URL = "https://opsroom.live/api/v1/openaip/airspaces"

# Response cache TTL. Airspace data changes on AIRAC cycles, so a day is safe
# and keeps us well under provider rate limits. Override via env if needed.
_CACHE_TTL_SECONDS = 60 * 60 * 24
_CACHE_DIR_NAME = "openaip"

_REQUEST_TIMEOUT = 8.0
# The default VPS proxy endpoint is baked in, so every install attempts it.
# Fail fast (4s) so a dead/unreachable proxy can never stall the map before
# the caller falls back to the local aviation DB.
_PROXY_REQUEST_TIMEOUT = 4.0
# Failed fetches are remembered briefly so repeat map refreshes fall back to
# the local database instantly instead of stalling on the network every time.
_FAILURE_CACHE_TTL_SECONDS = 10 * 60
# A transient proxy outage should be retried much sooner than an auth failure.
_PROXY_FAILURE_RETRY_SECONDS = 60
_MAX_LIMIT = 1200
_MAX_TOTAL_RING_POINTS = 60000
_MAX_RINGS_PER_ITEM = 32

# Maximum viewport span (degrees) we will request from the provider. The map
# already guards airspace fetches behind zoom >= 5, but keep a hard ceiling so
# a world-view request can never happen.
_MAX_BBOX_SPAN_LON = 40.0
_MAX_BBOX_SPAN_LAT = 24.0

_LOCK = threading.RLock()
_METRICS: dict[str, Any] = {
    "total": 0, "success": 0, "failed": 0,
    "rate_limited": 0, "cache_hits": 0, "network_failures": 0, "timeouts": 0,
    "last_error": None, "last_error_ts": None, "last_error_status": None,
    "last_success_ts": None, "last_fetched_ts": None, "last_region": None,
}


def _settings_integrations() -> dict[str, Any]:
    data = load_settings().get("integrations", {})
    return data if isinstance(data, dict) else {}


def _resolved_key() -> str:
    """User-configured key wins; otherwise fall back to the managed key."""
    try:
        from .managed_keys import get_secret
        managed = get_secret("openaip_key", env="OPENAIP_API_KEY")
    except Exception:
        managed = ""
    return str(_settings_integrations().get("openaip_api_key", "") or "").strip() or managed


def _resolved_proxy() -> tuple[str, str]:
    """Owner VPS proxy (url, token).

    The endpoint URL is baked into the build by default (like the OpenSky VPS
    proxy), so the enrichment layer works with zero configuration. An optional
    token is sent only when configured (settings > env > managed build
    secrets); the default public endpoint requires none. A configured token is
    an OPS ROOM credential and must never be logged or exposed to the browser.
    """
    integrations = _settings_integrations()
    url = str(integrations.get("openaip_proxy_url", "") or "").strip()
    token = str(integrations.get("openaip_proxy_token", "") or "").strip()
    if not url:
        url = str(os.getenv("OPENAIP_PROXY_URL", "") or "").strip()
    if not token:
        token = str(os.getenv("OPENAIP_PROXY_TOKEN", "") or "").strip()
    if not url or not token:
        try:
            from .managed_keys import get_secret
            url = url or get_secret("openaip_proxy_url", env="OPENAIP_PROXY_URL")
            token = token or get_secret("openaip_proxy_token", env="OPENAIP_PROXY_TOKEN")
        except Exception:
            pass
    if not url:
        url = _DEFAULT_PROXY_URL
    return url.rstrip("/"), token


def openaip_enabled() -> bool:
    """True when the map toggle is on.

    The default VPS proxy endpoint is baked into the build (mirroring the
    OpenSky proxy pattern), so no key, token, or user configuration is required
    for the enrichment layer to be live.
    """
    enabled_flag = _settings_integrations().get("openaip_map_enabled", True)
    try:
        return bool(enabled_flag)
    except Exception:
        return True


def _cache_dir() -> Path:
    path = app_data_dir() / _CACHE_DIR_NAME
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


def _cache_file(region_key: str) -> Path:
    safe = re.sub(r"[^0-9a-zA-Z_,.\-]", "_", region_key)
    return _cache_dir() / f"airspaces_{safe}.json"


_LAST_SWEEP: float = 0.0


def _sweep_cache() -> None:
    """Age-based cleanup of the OpenAIP disk cache (at most once per hour)."""
    global _LAST_SWEEP
    now = time.time()
    if now - _LAST_SWEEP < 3600.0:
        return
    _LAST_SWEEP = now
    try:
        directory = _cache_dir()
        for pattern, max_age in (("airspaces_*.json", _CACHE_TTL_SECONDS * 2),
                                 ("_failed_*.json", _FAILURE_CACHE_TTL_SECONDS * 2)):
            for file_path in directory.glob(pattern):
                try:
                    if file_path.stat().st_mtime < now - max_age:
                        file_path.unlink(missing_ok=True)
                except OSError:
                    continue
    except OSError:
        pass


def _record(ok: bool, **fields: Any) -> None:
    with _LOCK:
        m = _METRICS
        m["total"] = (m["total"] or 0) + 1
        if ok:
            m["success"] = (m["success"] or 0) + 1
            m["last_success_ts"] = time.time()
        else:
            m["failed"] = (m["failed"] or 0) + 1
            m["last_error"] = str(fields.get("error") or "unknown")[:300]
            m["last_error_ts"] = time.time()
            m["last_error_status"] = fields.get("status")
        for key, value in fields.items():
            if key in ("rate_limited", "cache_hits", "network_failures", "timeouts"):
                m[key] = (m[key] or 0) + 1
            elif key in ("last_fetched_ts", "last_region") and value is not None:
                m[key] = value


def _parse_bbox(bbox: str | None) -> tuple[float, float, float, float] | None:
    if not bbox:
        return None
    try:
        a = [float(x.strip()) for x in str(bbox).split(",")]
        if len(a) != 4:
            return None
        min_lon, min_lat, max_lon, max_lat = a
        if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180):
            return None
        if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
            return None
        if min_lon >= max_lon or min_lat >= max_lat:
            return None
        return min_lon, min_lat, max_lon, max_lat
    except (TypeError, ValueError):
        return None


def _region_key(b: tuple[float, float, float, float]) -> str:
    return ",".join(f"{v:.4f}" for v in b)


def _alt_ft(value: Any) -> int | None:
    """Best-effort conversion of an OpenAIP altitude string to feet.

    Handles 'FL095', 'FL 95', 'A075', '2500 ft', 'SFC'/'GND' and plain ints.
    Returns None when the value cannot be interpreted.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return int(round(float(value)))
        except (TypeError, ValueError):
            return None
    text = str(value).strip().upper()
    if not text:
        return None
    if text in ("SFC", "GND", "0", "0 FT"):
        return 0
    m = re.match(r"^FL\s*(\d{2,3})$", text)
    if m:
        return int(m.group(1)) * 100
    m = re.match(r"^A0?(\d{2,4})$", text)
    if m:
        return int(m.group(1)) * 100
    m = re.match(r"^(\d+)\s*(FT|FEET)?$", text)
    if m:
        return int(m.group(1))
    return None


def _first_text(mapping: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            text = str(value).strip()
            if text and text.lower() not in ("none", "null", "unknown"):
                return text
    return ""


def _polygon_parts(geometry: Any) -> list[list[list[list[float]]]]:
    """Split a GeoJSON Polygon/MultiPolygon into parts.

    Each returned part is a list of rings ``[[[lon,lat],...], ...]`` where the
    first ring is the outer boundary and the remainder are holes. MultiPolygon
    parts are kept separate so disjoint airspaces render as distinct polygons.
    """
    if not isinstance(geometry, dict):
        return []
    geom_type = str(geometry.get("type") or "")
    coords = geometry.get("coordinates")
    raw_parts: list[Any] = []
    if geom_type == "Polygon" and isinstance(coords, list):
        raw_parts.append(coords)
    elif geom_type == "MultiPolygon" and isinstance(coords, list):
        raw_parts.extend(p for p in coords if isinstance(p, list))
    parts: list[list[list[list[float]]]] = []
    total = 0
    for raw_part in raw_parts:
        if len(parts) >= _MAX_RINGS_PER_ITEM:
            break
        rings: list[list[list[float]]] = []
        for raw_ring in raw_part[:_MAX_RINGS_PER_ITEM]:
            if not isinstance(raw_ring, list):
                continue
            ring: list[list[float]] = []
            for pair in raw_ring:
                if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                    continue
                lon = float(pair[0])
                lat = float(pair[1])
                if -180 <= lon <= 180 and -90 <= lat <= 90:
                    ring.append([round(lon, 6), round(lat, 6)])
            if len(ring) >= 4:  # closed ring needs at least 4 points
                rings.append(ring)
                total += len(ring)
        if rings:
            parts.append(rings)
        if total > _MAX_TOTAL_RING_POINTS:
            break
    return parts


def _normalise_feature(feature: Any, fetched_ts: str) -> list[dict[str, Any]]:
    """Convert one GeoJSON feature into one normalized item per polygon part."""
    if not isinstance(feature, dict):
        return []
    props = feature.get("properties")
    props = props if isinstance(props, dict) else {}
    parts = _polygon_parts(feature.get("geometry"))
    if not parts:
        parts = _polygon_parts(props.get("geometry"))
    if not parts:
        # No usable polygon; skip rather than degrade the layer visually.
        return []
    frequencies: list[str] = []
    raw_freq = props.get("frequencies") if isinstance(props.get("frequencies"), list) else props.get("frequency")
    if isinstance(raw_freq, list):
        frequencies = [str(x).strip() for x in raw_freq if str(x or "").strip()]
    elif raw_freq is not None and str(raw_freq).strip():
        frequencies = [str(raw_freq).strip()]
    upper_raw = props.get("upperLimit", props.get("upper", props.get("upper_alt")))
    lower_raw = props.get("lowerLimit", props.get("lower", props.get("lower_alt")))
    base_id = _first_text(props, "id", "openAIPId") or _first_text(props, "name", "designator")
    items: list[dict[str, Any]] = []
    for index, part in enumerate(parts):
        all_points = [p for ring in part for p in ring]
        lats = [p[1] for p in all_points]
        lons = [p[0] for p in all_points]
        items.append({
            "id": f"{base_id}#{index}" if base_id else f"openair-{index}",
            "name": _first_text(props, "name", "designator", "id"),
            "type": _first_text(props, "type", "typeKey"),
            "cls": _first_text(props, "icaoClass", "class"),
            "upper": str(upper_raw) if upper_raw not in (None, "") else "",
            "upper_ref": _first_text(props, "upperReference", "upper_ref"),
            "lower": str(lower_raw) if lower_raw not in (None, "") else "",
            "lower_ref": _first_text(props, "lowerReference", "lower_ref"),
            "min_altitude": _alt_ft(lower_raw),
            "max_altitude": _alt_ft(upper_raw),
            "frequency": ", ".join(frequencies),
            "min_lat": round(min(lats), 6) if lats else None,
            "min_lon": round(min(lons), 6) if lons else None,
            "max_lat": round(max(lats), 6) if lats else None,
            "max_lon": round(max(lons), 6) if lons else None,
            "rings": part,
            "source": "openaip",
            "source_label": "OpenAIP",
            "fetched_at": fetched_ts,
        })
    return items


def _parse_payload(payload: Any, fetched_ts: str) -> list[dict[str, Any]]:
    features: list[Any] = []
    if isinstance(payload, dict):
        candidate = payload.get("features")
        if isinstance(candidate, list):
            features = candidate
        elif isinstance(payload.get("items"), list):
            features = payload["items"]
        elif isinstance(payload.get("airspaces"), list):
            features = payload["airspaces"]
    elif isinstance(payload, list):
        features = payload
    items: list[dict[str, Any]] = []
    for feature in features:
        if isinstance(feature, dict):
            items.extend(_normalise_feature(feature, fetched_ts))
    return items


def _write_failed_marker(cache_path: Path, reason: str, error: str) -> None:
    """Persist a negative-cache marker next to the region cache file."""
    try:
        cache_path.with_name("_failed_" + cache_path.name).write_text(json.dumps({
            "failed": True,
            "reason": reason,
            "error": str(error or "")[:300],
            "fetched_at_ts": time.time(),
        }), encoding="utf-8")
    except OSError:
        pass


def _http_get(url: str, params: dict[str, Any], headers: dict[str, Any], label: str,
              timeout: float = _REQUEST_TIMEOUT) -> Any:
    """GET with one 429 retry (honoring Retry-After when present)."""
    for attempt in (1, 2):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        except requests.Timeout:
            _record(False, error=f"{label} timeout", timeouts=1)
            raise
        except requests.RequestException as exc:
            _record(False, error=f"{label} {type(exc).__name__}: {exc}", network_failures=1)
            raise
        if resp.status_code == 429 and attempt == 1:
            _record(False, error=f"{label} rate_limited", status=429, rate_limited=1)
            delay = 1.0
            retry_after = resp.headers.get("Retry-After")
            try:
                delay = min(10.0, max(0.5, float(retry_after)))
            except (TypeError, ValueError):
                pass
            time.sleep(delay)
            continue
        if resp.status_code in (401, 403):
            _record(False, error=f"{label} auth http={resp.status_code}", status=resp.status_code)
            raise PermissionError(f"{label} auth failed: HTTP {resp.status_code}")
        if not resp.ok:
            _record(False, error=f"{label} http={resp.status_code}", status=resp.status_code)
            raise RuntimeError(f"{label} HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError:
            _record(False, error=f"{label} non-json", status=resp.status_code)
            raise RuntimeError(f"{label} returned a non-JSON response")
    _record(False, error=f"{label} rate_limited_retry_exhausted", status=429, rate_limited=1)
    raise RuntimeError(f"{label} rate limited after retry")


def airspaces(bbox: str | None, limit: int = 900, force: bool = False) -> dict[str, Any]:
    """Fetch airspace polygons for a bbox, using the disk cache when fresh.

    Returns:
        {"ok": True, "source": "openaip", "items": [...], "count": n,
         "cached": bool, "fetched_at": iso, "meta": {...}}
        or {"ok": False, "source": "openaip", "items": [], "reason": "...",
            "error": "..."}
    """
    if not openaip_enabled():
        return {"ok": False, "source": "openaip", "items": [], "reason": "not_configured",
                "error": "OpenAIP is not enabled (enable the map toggle)."}
    _sweep_cache()
    b = _parse_bbox(bbox)
    if not b:
        return {"ok": False, "source": "openaip", "items": [], "reason": "bad_bbox",
                "error": "Invalid or missing bounding box."}
    min_lon, min_lat, max_lon, max_lat = b
    if (max_lon - min_lon) > _MAX_BBOX_SPAN_LON or (max_lat - min_lat) > _MAX_BBOX_SPAN_LAT:
        return {"ok": False, "source": "openaip", "items": [], "reason": "bbox_too_large",
                "error": "Viewport too large for OpenAIP airspace fetch."}
    limit = max(1, min(int(limit or 900), _MAX_LIMIT))
    proxy_url, proxy_token = _resolved_proxy()
    direct_key = _resolved_key()
    region = _region_key(b)
    fetched_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    cache_path = _cache_file(region)

    failed_path = cache_path.with_name("_failed_" + cache_path.name)
    if not force:
        # Negative cache: remember failures briefly (including auth problems and
        # genuinely empty regions) so repeat refreshes fall back instantly.
        try:
            if failed_path.is_file():
                cached = json.loads(failed_path.read_text(encoding="utf-8"))
                if isinstance(cached, dict) and cached.get("failed"):
                    age = time.time() - float(cached.get("fetched_at_ts") or 0)
                    marker_reason = str(cached.get("reason") or "request_failed")
                    ttl = (_PROXY_FAILURE_RETRY_SECONDS if marker_reason == "proxy_failed"
                           else _FAILURE_CACHE_TTL_SECONDS)
                    if 0 <= age <= ttl:
                        _record(False, error="cached_failure", last_region=region)
                        return {"ok": False, "source": "openaip", "items": [],
                                "reason": marker_reason,
                                "error": str(cached.get("error") or "cached failure")}
        except (OSError, ValueError, TypeError):
            pass
        try:
            if cache_path.is_file():
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(cached, dict) and float(cached.get("fetched_at_ts") or 0) > time.time() - _CACHE_TTL_SECONDS:
                    items = cached.get("items") or []
                    _record(True, cache_hits=1, last_region=region)
                    return {"ok": True, "source": "openaip", "items": items, "count": len(items),
                            "cached": True, "fetched_at": str(cached.get("fetched_at") or fetched_ts),
                            "meta": {"cached": True, "region": region, "via": "cache"}}
        except (OSError, ValueError, TypeError):
            pass

    via = "proxy"
    proxy_error: Exception | None = None
    items: list[dict[str, Any]] = []
    proxy_headers = {"Accept": "application/json", "User-Agent": "opsroom-map-enrichment/0.1"}
    if proxy_token:
        # Optional token; the default public endpoint requires none.
        proxy_headers["x-opsroom-proxy-token"] = proxy_token
    try:
        payload = _http_get(
            proxy_url,
            {"bbox": f"{min_lon},{min_lat},{max_lon},{max_lat}", "limit": limit},
            proxy_headers,
            "openaip proxy",
            timeout=_PROXY_REQUEST_TIMEOUT)
        items = _parse_payload(payload, fetched_ts)
    except Exception as exc:
        proxy_error = exc
    if not items and not direct_key and proxy_error:
        _write_failed_marker(cache_path, "proxy_failed", str(proxy_error))
        return {"ok": False, "source": "proxy", "items": [],
                "reason": "proxy_failed", "error": f"{proxy_error}"}
    if not items and direct_key:
        via = "proxy-fallback-direct" if proxy_error else "direct"
        try:
            payload = _http_get(
                f"{_API_V3_BASE}/airspaces",
                {"bbox": f"{min_lon},{min_lat},{max_lon},{max_lat}", "limit": limit},
                {"x-openaip-api-key": direct_key, "Accept": "application/json",
                 "User-Agent": "opsroom-map-enrichment/0.1"},
                "openaip")
            items = _parse_payload(payload, fetched_ts)
        except PermissionError as exc:
            # A rejected key is rejected on every endpoint - do not double the latency.
            _write_failed_marker(cache_path, "auth_failed", str(exc))
            return {"ok": False, "source": "openaip", "items": [],
                    "reason": "auth_failed", "error": str(exc)}
        except Exception as exc:
            # Defensive v2 fallback (legacy endpoint) before giving up entirely.
            center_lon = (min_lon + max_lon) / 2.0
            center_lat = (min_lat + max_lat) / 2.0
            radius_km = max(1.0, math.hypot(max_lon - min_lon, max_lat - min_lat) * 111.0 / 2.0)
            try:
                payload = _http_get(
                    f"{_API_V2_BASE}/airspaces",
                    {"lat": round(center_lat, 5), "lon": round(center_lon, 5),
                     "radius": round(radius_km, 1), "format": "json"},
                    {"x-openaip-api-key": direct_key, "Accept": "application/json",
                     "User-Agent": "opsroom-map-enrichment/0.1"},
                    "openaip")
                items = _parse_payload(payload, fetched_ts)
            except Exception as fallback_exc:
                _record(False, error=f"{exc} | fallback: {fallback_exc}")
                _write_failed_marker(cache_path, "request_failed", str(exc))
                return {"ok": False, "source": "openaip", "items": [],
                        "reason": "request_failed", "error": f"{exc}"}
    if not items:
        # Intentionally negative-cache genuinely empty regions (e.g. mid-ocean)
        # for a short window so repeat refreshes don't hammer the provider.
        _record(False, error="no airspace polygons parsed")
        _write_failed_marker(cache_path, "empty",
                             "OpenAIP returned no airspace polygons for this viewport.")
        return {"ok": False, "source": "openaip", "items": [], "reason": "empty",
                "error": "OpenAIP returned no airspace polygons for this viewport."}
    try:
        cache_payload = {"fetched_at": fetched_ts, "fetched_at_ts": time.time(), "items": items}
        cache_path.write_text(json.dumps(cache_payload), encoding="utf-8")
        failed_path.unlink(missing_ok=True)
    except OSError:
        pass
    _record(True, last_region=region, last_fetched_ts=time.time())
    return {"ok": True, "source": "openaip", "items": items, "count": len(items),
            "cached": False, "fetched_at": fetched_ts,
            "meta": {"cached": False, "region": region, "via": via}}


def status() -> dict[str, Any]:
    """Runtime status for the map status block. Never exposes keys or tokens."""
    with _LOCK:
        m = dict(_METRICS)
    try:
        cached_regions = len(list(_cache_dir().glob("airspaces_*.json")))
    except OSError:
        cached_regions = 0
    total = m.get("total") or 0
    failed = m.get("failed") or 0
    healthy = None if total == 0 else (failed < max(total, 1) * 0.5)
    proxy_url, _proxy_token = _resolved_proxy()
    return {
        "configured": True,  # default VPS proxy endpoint is baked into the client
        "enabled": openaip_enabled(),
        "proxy": {
            "configured": bool(proxy_url),
            "host": urlparse(proxy_url).netloc if proxy_url else "",
        },
        "active": bool(m.get("last_success_ts")),
        "healthy": healthy,
        "role": "airspace polygon enrichment provider",
        "counters": {
            "total": total, "success": m.get("success") or 0, "failed": failed,
            "rate_limited": m.get("rate_limited") or 0,
            "cache_hits": m.get("cache_hits") or 0,
            "network_failures": m.get("network_failures") or 0,
            "timeouts": m.get("timeouts") or 0,
        },
        "cached_regions": cached_regions,
        "last_success_ts": m.get("last_success_ts"),
        "last_fetched_ts": m.get("last_fetched_ts"),
        "last_region": m.get("last_region"),
        "last_error": m.get("last_error"),
        "last_error_ts": m.get("last_error_ts"),
        "last_error_status": m.get("last_error_status"),
        "attribution": "Airspace data © OpenAIP (CC BY-NC)",
    }
