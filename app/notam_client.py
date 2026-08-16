"""
OPS ROOM -- FAA NMS NOTAM database client (v0.25.65).

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

import json
import os
import threading
import time
from pathlib import Path
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
    version = "0.25.1"
    try:
        raw = (Path(__file__).resolve().parent.parent / "version.json").read_text(encoding="utf-8")
        version = str(json.loads(raw).get("version") or version)
    except Exception:  # pragma: no cover - defensive version read
        pass
    headers = {"Accept": "application/json", "User-Agent": f"OPS ROOM/{version} (notam db client)"}
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
    # v0.25.67: round the key coords to ~2 km buckets so the aircraft taxiing
    # around an airport reuses the cached geo result instead of refetching on
    # every ~100 m of movement (the per-airport fallback below does one HTTP
    # round-trip per nearby airport - it must not re-run on every metre).
    key = f"geo:{latitude / 0.02:.0f},{longitude / 0.02:.0f},{radius:.0f}"
    hit = _cache_get(key)
    if hit is not None:
        return hit

    body = _db_get(f"/near?latitude={latitude}&longitude={longitude}&radius_nm={radius}")
    db_answered = body is not None
    rows = _rows_from(body) if db_answered else []
    source = "FAA NMS DB"
    proxy_answered = False
    if not rows:
        proxy = nms_client.fetch_notams_by_geo(latitude, longitude, radius)
        proxy_answered = bool(proxy.get("ok"))
        if proxy_answered:
            rows = nms_client.normalize_geo_notams(proxy.get("features") or [])
            source = "FAA NMS"
    if not rows:
        # v0.25.67: the server geo query can return an empty set while the
        # per-airport lookup still has rows (observed at EGKK: /near = 0,
        # /airport = 2), and the NMS proxy can reject the shared token. Fall
        # back to per-airport fetches for every airport inside the radius so
        # the closure-marker deploy and the geo NOTAM layer never report "0
        # NOTAMs" at an airport that actually has them.
        rows = _nearby_airport_notams(latitude, longitude, radius)
        if rows:
            source = "FAA NMS DB (per-airport)"
    if not rows:
        if db_answered or proxy_answered:
            # A live source answered and has nothing within radius -- "0
            # NOTAMs" is the honest result, not an error.
            result = {"ok": True, "notams": [], "source": source, "count": 0}
        else:
            result = {"ok": False, "notams": [], "source": "", "error": "NOTAM service unreachable"}
        return _cache_set(key, result)
    result: dict[str, Any] = {"ok": True, "notams": rows, "source": source, "count": len(rows)}
    return _cache_set(key, result)


def _nearby_airport_notams(latitude: float, longitude: float, radius_nm: float) -> list[dict[str, Any]]:
    """NOTAM rows for every airport inside the radius via per-airport fetches.

    v0.25.68 geo fallback used by :func:`get_notams_near` when the server's
    geo query returns nothing (or the NMS proxy rejects the token): walk the
    cached airport index, keep every airport within ``radius_nm``, fetch its
    NOTAMs through the normal (DB-first) per-airport path and deduplicate
    across airports. Cheap after the first call: the airport index and every
    per-airport result are cached.
    """
    from . import data_loader
    from .navdata import haversine_nm

    try:
        airports = data_loader.load_airports()
    except Exception:  # pragma: no cover - defensive navdata path
        return []
    nearby: list[str] = []
    for ident, ap in airports.items():
        try:
            alat, alon = float(ap.lat), float(ap.lon)
        except (TypeError, ValueError, AttributeError):
            continue
        if haversine_nm(latitude, longitude, alat, alon) <= float(radius_nm or 0.0):
            nearby.append(str(ident).upper())
    nearby.sort()
    # v0.25.67: parallel per-airport fetches (the serial version took ~6-8 s
    # for a 50 NM radius; with a small pool it completes in ~1 s and the
    # result is cached). get_notams is cache-first and degrades gracefully.
    from concurrent.futures import ThreadPoolExecutor

    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        future_map = {pool.submit(get_notams, icao): icao for icao in nearby}
        for future in future_map:
            try:
                results[future_map[future]] = future.result()
            except Exception:  # pragma: no cover - per-airport guard
                results[future_map[future]] = {"ok": False, "notams": []}
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for icao in sorted(results):
        for row in results[icao].get("notams") or []:
            if not isinstance(row, dict):
                continue
            dedup_key = (str(row.get("id") or row.get("number") or icao), str(row.get("text") or "")[:200])
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            copy_row = dict(row)
            copy_row.setdefault("airport_icao", icao)
            rows.append(copy_row)
    return rows


def _map_features_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Wrap briefing-shaped NOTAM rows into the GeoJSON Point feature shape the
    Live Map layer consumes (properties.coreNOTAMData.notam.*)."""
    features: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        coords = row.get("coordinates")
        if not (isinstance(coords, list) and len(coords) == 2):
            # Per-airport rows carry coordinates: null -- resolve from the
            # airport index so they can still be placed on the map (#25).
            icao = str(row.get("airport_icao") or row.get("icao_location") or row.get("location") or "").upper()
            if icao:
                try:
                    from . import data_loader
                    ap = data_loader.load_airports().get(icao)
                    if ap is not None:
                        coords = [float(ap.lat), float(ap.lon)]
                except Exception:
                    coords = None
        if not (isinstance(coords, list) and len(coords) == 2):
            continue
        try:
            point_lat = float(coords[0])
            point_lon = float(coords[1])
        except (TypeError, ValueError):
            continue
        location = str(row.get("location") or row.get("icao_location") or row.get("airport_icao") or "").upper()
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
    return features


def get_notams_map(latitude: float, longitude: float, radius_nm: float = 40.0) -> dict[str, Any]:
    """GeoJSON features for the Live Map NOTAM layer -- database first, proxy
    fallback, then per-airport (#25).

    The map frontend (loadNotamLayer in opsroom.js) reads
    ``properties.coreNOTAMData.notam.{id, number, classification,
    selectionCode, text, icaoLocation, location}`` with a Point geometry, so
    rows are wrapped back into exactly that shape. Never raises.

    v0.25.73 (#25): the server's /near geo index is sparse at typical map
    viewport radii (10-25 NM), so an *empty but successful* DB answer used to
    short-circuit with ``ok:true, features:[]`` and the proxy was never
    consulted. Now an empty DB result falls through to the live FAA NMS proxy
    and then to the per-airport walk (with positions resolved from the
    airport index), mirroring get_notams_near().
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

    db_answered = False
    proxy_answered = False
    features: list[dict[str, Any]] = []
    source = ""

    body = _db_get(f"/near?latitude={lat_v}&longitude={lon_v}&radius_nm={radius}")
    if body is not None:
        db_answered = True
        features = _map_features_from_rows(_rows_from(body))
        if features:
            source = "FAA NMS DB"

    if not features:
        proxy = nms_client.fetch_notams_by_geo(lat_v, lon_v, radius)
        proxy_answered = bool(proxy.get("ok"))
        if proxy_answered:
            proxy_features = proxy.get("features") or []
            if proxy_features:
                features = proxy_features
                source = "FAA NMS"

    if not features:
        rows = _nearby_airport_notams(lat_v, lon_v, radius)
        if rows:
            features = _map_features_from_rows(rows)
            if features:
                source = "FAA NMS DB (per-airport)"

    if not features:
        if db_answered or proxy_answered:
            # A live source answered and has nothing within radius -- "0
            # NOTAMs" is the honest result, not an error.
            result = {"ok": True, "features": [], "source": source, "count": 0}
        else:
            result = {"ok": False, "features": [], "source": "", "error": "NOTAM service unreachable"}
        return _cache_set(key, result)
    result = {"ok": True, "source": source, "features": features, "count": len(features)}
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
