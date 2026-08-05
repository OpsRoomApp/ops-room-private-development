"""
OPS ROOM -- FAA NMS NOTAM database client (v0.25.63).

Thin client for the opsroom.live server-side NOTAM store
(``/api/v1/notams/...``, admin-api/notams.py). The server refreshes its copy
of the FAA NMS NOTAM set on a fixed schedule (1 bulk pull / 24h + 1
incremental pull / 3 min), so every per-airport / geo query here costs ZERO
FAA quota.

The server already maps store rows into the briefing row shape the rest of
the app consumes (same shape as ``nms_client.normalize_nms_feature``), so
rows pass through unchanged with the source relabelled ``FAA NMS DB``.

Prefers the database and falls back to the existing NMS proxy client
(nms_client.py) when the DB endpoints are not deployed yet, so this module is
safe to ship before the server-side store goes live.

Env overrides (all optional):
  OPSROOM_NOTAM_API_URL -- base URL, default https://opsroom.live
  OPSROOM_NOTAM_TOKEN   -- shared token (optional; the public endpoints do
                           not require one, but sending it is harmless)
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

import requests

from . import nms_client

_NOTAM_CACHE_TTL = 300.0  # 5 minutes -- protects our own server from hammering
_NOTAM_TIMEOUT = (4.0, 8.0)

_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()


def _cache_get(key: str) -> dict[str, Any] | None:
    hit = _cache.get(key)
    if not hit:
        return None
    ts, value = hit
    if time.time() - ts <= _NOTAM_CACHE_TTL:
        return value
    return None


def _cache_set(key: str, value: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        if len(_cache) > 128:
            _cache.clear()
        _cache[key] = (time.time(), value)
    return value


def _config() -> dict[str, str]:
    base = os.environ.get("OPSROOM_NOTAM_API_URL", "").strip() or "https://opsroom.live"
    return {
        "base_url": base.rstrip("/"),
        "token": os.environ.get("OPSROOM_NOTAM_TOKEN", "").strip(),
    }


def _headers() -> dict[str, str]:
    cfg = _config()
    headers = {"Accept": "application/json", "User-Agent": "OPS ROOM/0.24.107 (notam db client)"}
    if cfg["token"]:
        headers["Authorization"] = f"Bearer {cfg['token']}"
    return headers


def _db_get(path: str) -> dict[str, Any] | None:
    """GET a DB endpoint; None on any transport/HTTP failure (caller falls
    back to the proxy)."""
    cfg = _config()
    url = f"{cfg['base_url']}/api/v1/notams{path}"
    try:
        resp = requests.get(url, headers=_headers(), timeout=_NOTAM_TIMEOUT)
        if resp.status_code != 200:
            return None
        body = resp.json()
        if not isinstance(body, dict):
            return None
        return body
    except Exception:
        return None


def _rows_from(body: dict[str, Any]) -> list[dict[str, Any]]:
    rows = body.get("notams") or []
    return [dict(r) for r in rows if isinstance(r, dict)]


def _valid_icao(icao: str) -> bool:
    return len(icao) == 4 and icao.isalpha()


def get_notams(icao: str, classification: str = "", feature: str = "") -> dict[str, Any]:
    """Active NOTAMs for an airport -- database first, NMS proxy fallback.

    Returns briefing-shaped rows (``{"ok": True, "notams": [...], "source":
    "FAA NMS DB" | "FAA NMS", "count": ...}``). Never raises.
    """
    icao = str(icao or "").strip().upper()
    if not _valid_icao(icao):
        return {"ok": False, "notams": [], "source": "", "error": "Invalid ICAO"}
    key = f"db:{icao}:{str(classification or '').upper()}:{str(feature or '')}"
    hit = _cache_get(key)
    if hit is not None:
        return hit

    body = _db_get(f"/{icao}")
    if body is not None:
        rows = _rows_from(body)
        if classification:
            wanted = str(classification).upper()
            rows = [r for r in rows if str(r.get("classification") or "").upper() == wanted]
        for row in rows:
            row["source"] = "FAA NMS DB"
        result: dict[str, Any] = {"ok": True, "notams": rows, "source": "FAA NMS DB", "count": len(rows)}
        return _cache_set(key, result)

    # Fallback: existing proxy path (GeoJSON), normalized to briefing rows.
    proxy = nms_client.fetch_notams_by_location(icao, classification=classification, feature=feature)
    if not proxy.get("ok"):
        result = {"ok": False, "notams": [], "source": "", "error": proxy.get("error", "NOTAM unavailable")}
        return _cache_set(key, result)
    rows = nms_client.normalize_geo_notams(proxy.get("features") or [])
    result = {"ok": True, "notams": rows, "source": "FAA NMS", "count": len(rows)}
    return _cache_set(key, result)


def get_notams_near(lat: float, lon: float, radius_nm: float = 25.0) -> dict[str, Any]:
    """Active NOTAMs within a radius of a point -- database first, proxy
    fallback. Used by the TFR proximity monitor and geo lookups. Returns
    briefing-shaped rows. Never raises."""
    try:
        latitude = float(lat)
        longitude = float(lon)
    except (TypeError, ValueError):
        return {"ok": False, "notams": [], "source": "", "error": "Invalid coordinates"}
    radius = max(1.0, min(float(radius_nm or 25), 200.0))
    key = f"geo:{latitude:.3f},{longitude:.3f},{radius:.0f}"
    hit = _cache_get(key)
    if hit is not None:
        return hit

    body = _db_get(f"/near?latitude={latitude}&longitude={longitude}&radius_nm={radius}")
    if body is not None:
        rows = _rows_from(body)
        for row in rows:
            row["source"] = "FAA NMS DB"
        result: dict[str, Any] = {"ok": True, "notams": rows, "source": "FAA NMS DB", "count": len(rows)}
        return _cache_set(key, result)

    proxy = nms_client.fetch_notams_by_geo(latitude, longitude, radius)
    if not proxy.get("ok"):
        result = {"ok": False, "notams": [], "source": "", "error": proxy.get("error", "NOTAM unavailable")}
        return _cache_set(key, result)
    rows = nms_client.normalize_geo_notams(proxy.get("features") or [])
    result = {"ok": True, "notams": rows, "source": "FAA NMS", "count": len(rows)}
    return _cache_set(key, result)


def get_notams_map(latitude: float, longitude: float, radius_nm: float = 40.0) -> dict[str, Any]:
    """GeoJSON features for the Live Map NOTAM layer -- database first, proxy
    fallback.

    The map frontend (loadNotamLayer in opsroom.js) reads
    ``properties.coreNOTAMData.notam.{id, number, classification,
    selectionCode, text, icaoLocation, location}`` with a Point geometry, so
    DB rows are wrapped back into exactly that shape. Never raises.
    """
    try:
        lat_v = float(latitude)
        lon_v = float(longitude)
    except (TypeError, ValueError):
        return {"ok": False, "features": [], "source": "", "error": "Invalid coordinates"}
    radius = max(1.0, min(float(radius_nm or 40), 200.0))
    key = f"map:{lat_v:.3f},{lon_v:.3f},{radius:.0f}"
    hit = _cache_get(key)
    if hit is not None:
        return hit

    body = _db_get(f"/near?latitude={lat_v}&longitude={lon_v}&radius_nm={radius}")
    if body is not None:
        features: list[dict[str, Any]] = []
        for row in _rows_from(body):
            coords = row.get("coordinates")
            if not (isinstance(coords, list) and len(coords) == 2):
                continue
            try:
                point_lat = float(coords[0])
                point_lon = float(coords[1])
            except (TypeError, ValueError):
                continue
            location = str(row.get("location") or row.get("icao_location") or "").upper()
            notam = {
                "id": str(row.get("nms_id") or ""),
                "number": str(row.get("id") or ""),
                "classification": str(row.get("classification") or ""),
                "selectionCode": str(row.get("qcode") or ""),
                "text": str(row.get("text") or ""),
                "icaoLocation": location,
                "location": location,
            }
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [point_lon, point_lat]},
                    "properties": {"coreNOTAMData": {"notam": notam}},
                }
            )
        result: dict[str, Any] = {"ok": True, "source": "FAA NMS DB", "features": features, "count": len(features)}
        return _cache_set(key, result)

    proxy = nms_client.fetch_notams_by_geo(lat_v, lon_v, radius)
    if not proxy.get("ok"):
        result = {"ok": False, "features": [], "source": "", "error": proxy.get("error", "NOTAM unavailable")}
        return _cache_set(key, result)
    result = {"ok": True, "source": "FAA NMS", "features": proxy.get("features") or [], "count": proxy.get("count", 0)}
    return _cache_set(key, result)


def route_notams(origin: str, destination: str, alternates: list[str]) -> dict[str, Any]:
    """DB-first route fetch mirroring ``nms_client.route_notams`` output shape
    (the ``notams_live`` briefing enrichment): dep / arr / alternates are each
    resolved against the server store, scoped, deduped and sorted. Each
    per-airport fetch degrades to the proxy, so a store outage still answers.

    Failure degrades to ``{"ok": False}`` -- the caller keeps SimBrief data.
    """
    origin = str(origin or "").upper().strip()
    destination = str(destination or "").upper().strip()
    alternates = [str(a or "").upper().strip() for a in alternates]
    codes: list[str] = []
    for code in [origin, destination, *alternates]:
        value = str(code or "").upper().strip()
        if len(value) == 4 and value not in codes:
            codes.append(value)
    if not codes:
        return {"ok": False, "error": "No flight airports available", "notams": [], "sources": []}

    rows: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    unavailable = 0
    for index, code in enumerate(codes):
        result = get_notams(code)
        if not result.get("ok"):
            unavailable += 1
            sources.append({"name": f"FAA NMS · {code}", "state": "unavailable", "detail": result.get("error", "")})
            continue
        scope_key, scope = nms_client._scope_for_icao(code, origin or "", destination or "", alternates)
        for row in result.get("notams") or []:
            row = dict(row)
            row["scope_key"] = scope_key
            row["scope"] = scope
            row["source_order"] = index
            rows.append(row)
        sources.append({"name": f"FAA NMS · {code}", "state": "ok", "count": result.get("count", 0)})

    if not rows:
        state = "unavailable" if unavailable else "empty"
        return {"ok": True, "state": state, "notams": [], "sources": sources, "count": 0}

    # Dedupe identical (id, location, text) pairs.
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        key = (str(row.get("id") or "").upper(), str(row.get("location") or "").upper(), str(row.get("text") or "")[:80].upper())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    order = {"departure": 0, "destination": 1, "alternate": 2, "enroute": 3}
    deduped.sort(key=lambda row: (order.get(str(row.get("scope_key")), 9), int(row.get("source_order") or 0)))
    return {"ok": True, "state": "ok", "notams": deduped, "sources": sources, "count": len(deduped)}
