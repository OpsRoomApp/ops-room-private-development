"""
OPS ROOM -- FAA NMS-API thin client (v0.25.60).

The desktop app never talks to the FAA NMS-API directly. All NOTAM queries
flow through the opsroom.live VPS proxy (admin-api/nms.py), which holds the
NMS client KEY/SECRET and the upstream bearer token. This module:

  * resolves the proxy base URL + shared token from settings/env,
  * caches responses (mirroring weather_client.py's TTL cache pattern),
  * normalizes GeoJSON NOTAM features into the briefing row shape that
    briefing_data.py / the frontend already consume,
  * degrades gracefully -- every call returns {"ok": False, ...} instead of
    raising, so existing briefing/status UI is never broken by an NMS outage.

Env overrides (all optional):
  OPSROOM_NMS_PROXY_URL    -- proxy base, default https://opsroom.live
  OPSROOM_NMS_TOKEN        -- shared token (required to enable)
  OPSROOM_NMS_ENABLED      -- "1"/"true" enables; "0"/"false" forces off
  OPSROOM_NMS_TFR_ALERTING -- "1"/"true" enables TFR/FDC proximity alerts
  OPSROOM_NMS_TFR_RADIUS_NM-- geo radius for TFR alerts (default 25)

Configuration is deliberately env-driven (no settings-store block) so the
file stays byte-identical to the frozen release baseline. Credentials for
the FAA NMS-API itself live on the opsroom.live VPS proxy only.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

import requests

_NMS_CACHE_TTL = 120.0
_NMS_TIMEOUT = (4.0, 8.0)


def _app_version() -> str:
    """v0.25.67: user-agent version comes from version.json, never a stale literal."""
    try:
        raw = (Path(__file__).resolve().parent.parent / "version.json").read_text(encoding="utf-8")
        return str(json.loads(raw).get("version") or "0.25.73")
    except Exception:  # pragma: no cover - defensive version read
        return "0.25.73"


_USER_AGENT = f"OPS ROOM/{_app_version()} flight briefing (nms proxy client)"

_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()

def _cache_get(key: str) -> dict[str, Any] | None:
    hit = _cache.get(key)
    if not hit:
        return None
    ts, value = hit
    if time.time() - ts <= _NMS_CACHE_TTL:
        return value
    return None


def _cache_set(key: str, value: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        if len(_cache) > 128:
            _cache.clear()
        _cache[key] = (time.time(), value)
    return value


def _env_flag(name: str) -> bool | None:
    """Tri-state env flag: True/False when set, None when unset."""
    import os

    raw = os.environ.get(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return None


def nms_proxy_config() -> dict[str, str]:
    """Resolve proxy base URL + shared token (env-driven only)."""
    import os

    base = os.environ.get("OPSROOM_NMS_PROXY_URL", "").strip()
    if not base:
        base = "https://opsroom.live"
    base = base.rstrip("/")
    token = os.environ.get("OPSROOM_NMS_TOKEN", "").strip()
    return {"base_url": base, "token": token}


def nms_configured() -> bool:
    """A shared proxy token is configured (the integration can be used)."""
    cfg = nms_proxy_config()
    return bool(cfg["token"])


def nms_enabled() -> bool:
    """Whether the NMS live-NOTAM integration is enabled.

    Defaults to on whenever a token is configured; ``OPSROOM_NMS_ENABLED=0``
    forces it off (e.g. while access is still testing-only on a pilot's PC).
    """
    flag = _env_flag("OPSROOM_NMS_ENABLED")
    if flag is not None:
        return flag
    return nms_configured()


def tfr_alerting_config() -> dict[str, Any]:
    """TFR/FDC proximity alerting config (opt-in via env)."""
    import os

    flag = _env_flag("OPSROOM_NMS_TFR_ALERTING")
    enabled = bool(flag) if flag is not None else False
    try:
        radius = float(os.environ.get("OPSROOM_NMS_TFR_RADIUS_NM", "25"))
    except (TypeError, ValueError):
        radius = 25.0
    return {"enabled": enabled and nms_enabled(), "radius_nm": max(1.0, min(radius, 100.0))}


def _auth_headers() -> dict[str, str]:
    cfg = nms_proxy_config()
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    if cfg["token"]:
        headers["Authorization"] = f"Bearer {cfg['token']}"
    return headers


def _request(path: str, params: dict[str, Any] | None = None, timeout: float = _NMS_TIMEOUT[1]) -> dict[str, Any]:
    """GET the proxy endpoint and return {"ok": ...} always (never raises)."""
    cfg = nms_proxy_config()
    url = f"{cfg['base_url']}/api/v1/nms{path}"
    key = f"{url}?{sorted((str(k) + '=' + str(v)) for k, v in (params or {}).items()) if params else ''}"
    hit = _cache_get(key)
    if hit is not None:
        return hit
    try:
        resp = requests.get(url, params=params or None, headers=_auth_headers(), timeout=timeout)
        if resp.status_code != 200:
            result: dict[str, Any] = {"ok": False, "status": resp.status_code, "error": f"NMS proxy returned HTTP {resp.status_code}"}
            if resp.status_code == 401:
                result["error"] = "NMS proxy rejected the shared token"
            elif resp.status_code == 502:
                result["error"] = "NMS proxy could not reach the FAA NMS-API (upstream unavailable)"
            return _cache_set(key, result)
        body = resp.json()
        if not isinstance(body, dict):
            body = {"ok": True, "data": body}
        body.setdefault("ok", True)
        return _cache_set(key, body)
    except requests.exceptions.Timeout:
        return _cache_set(key, {"ok": False, "error": "NMS proxy request timed out", "timeout": True})
    except Exception as exc:
        return _cache_set(key, {"ok": False, "error": f"NMS proxy unavailable: {type(exc).__name__}"})


def nms_status() -> dict[str, Any]:
    """Proxy diagnostics (no secrets)."""
    result = _request("/status")
    if not result.get("ok"):
        return result
    return result


def fetch_checklist(location: str, classification: str = "") -> dict[str, Any]:
    """Checklist (index) entries for a location."""
    params: dict[str, Any] = {"location": location}
    if classification:
        params["classification"] = classification
    result = _request("/checklist", params)
    if not result.get("ok"):
        return result
    entries = (result.get("data") or {}).get("checklist") or []
    return {"ok": True, "source": "FAA NMS", "location": location, "entries": entries, "count": len(entries)}


def fetch_notams_by_location(location: str, classification: str = "", feature: str = "") -> dict[str, Any]:
    """Full GeoJSON NOTAM query for a location."""
    params: dict[str, Any] = {"location": location}
    if classification:
        params["classification"] = classification
    if feature:
        params["feature"] = feature
    result = _request("/notams", params)
    if not result.get("ok"):
        return result
    features = (result.get("data") or {}).get("geojson") or []
    return {"ok": True, "source": "FAA NMS", "location": location, "features": features, "count": len(features)}


def fetch_notams_by_geo(latitude: float, longitude: float, radius_nm: float) -> dict[str, Any]:
    """Geo-radius NOTAM query (used by the map layer and TFR alerting)."""
    result = _request("/notams", {"latitude": latitude, "longitude": longitude, "radius": radius_nm})
    if not result.get("ok"):
        return result
    features = (result.get("data") or {}).get("geojson") or []
    return {"ok": True, "source": "FAA NMS", "features": features, "count": len(features)}


def fetch_notam_by_id(nms_id: str) -> dict[str, Any]:
    """Single NOTAM by 16-digit nmsId."""
    result = _request(f"/notams/{nms_id}")
    if not result.get("ok"):
        return result
    features = (result.get("data") or {}).get("geojson") or []
    return {"ok": True, "source": "FAA NMS", "features": features, "count": len(features)}


def search_notams(text: str) -> dict[str, Any]:
    """Free-text NOTAM search (exact text, 1-80 chars)."""
    result = _request("/search", {"text": text})
    if not result.get("ok"):
        return result
    features = (result.get("data") or {}).get("geojson") or []
    return {"ok": True, "source": "FAA NMS", "features": features, "count": len(features)}


def fetch_initial_load(classification: str = "") -> dict[str, Any]:
    """Fetch the proxy-side initial-load snapshot (proxy re-serves AIXM; the
    signed URL never leaves the VPS)."""
    path = "/initial-load"
    params: dict[str, Any] = {}
    if classification:
        params["classification"] = classification
    return _request(path, params, timeout=90.0)


# ── GeoJSON → briefing row normalization ─────────────────────────────────


def _qcode_category(selection_code: str | None, text: str | None) -> str:
    qcode = str(selection_code or "").upper()
    if qcode.startswith("QOB") or any(word in (text or "").upper() for word in ("CRANE", "OBST", "WIND TURBINE")):
        return "Obstacles"
    if qcode.startswith("QMR"):
        return "Runways"
    if qcode.startswith("QPI"):
        return "Approach procedures"
    if qcode.startswith(("QIC", "QCA")):
        return "Airport surface"
    if qcode.startswith("QNV") or qcode.startswith("QNA"):
        return "Navigation aids"
    if qcode.startswith(("QRT", "QTT", "QW")) or any(word in (text or "").upper() for word in ("DANGER AREA", "RESTRICTED AREA", "AIRSPACE")):
        return "Airspace"
    return "General"


def normalize_nms_feature(feature: dict[str, Any], scope_key: str = "enroute", scope: str = "En route / FIR") -> dict[str, Any]:
    """Convert one NMS GeoJSON feature into the briefing row shape.

    The output mirrors simbrief_client._normalise_notams() rows exactly so
    briefingNoticeCard / renderStatusNotams render NMS and SimBrief data
    identically, with the source labelled 'FAA NMS'.
    """
    properties = feature.get("properties") if isinstance(feature, dict) else {}
    core = properties.get("coreNOTAMData") if isinstance(properties, dict) else {}
    notam = core.get("notam") if isinstance(core, dict) else {}
    if not isinstance(notam, dict):
        notam = {}

    def _text(value: Any, default: str = "") -> str:
        if value is None:
            return default
        if isinstance(value, (dict, list)):
            return default
        return str(value).strip()

    # Display id: the ICAO NOTAM number (e.g. A5540/26) is what pilots
    # recognise -- NOT the 16-digit nmsId. Prefer number, then series+number,
    # and only fall back to the raw id so Combined-mode dedupe (keyed on
    # id+location) matches SimBrief rows. The nmsId stays in ``nms_id``.
    number = _text(notam.get("number"))
    series = _text(notam.get("series"))
    ident = number or (f"{series}{number}" if series and number else "") or _text(notam.get("id")).upper()

    location = _text(notam.get("icaoLocation") or notam.get("location")).upper()
    text = _text(notam.get("text"))
    effective = _text(notam.get("effectiveStart"))
    expires = _text(notam.get("effectiveEnd"))
    # "PERM" expiry means a permanent NOTAM -- normalise to a None timestamp
    # so the data contract never leaks the literal string.
    permanent = (str(notam.get("estimated") or "").lower() == "true" and not expires) or str(expires or "").upper() == "PERM"
    if permanent:
        expires = ""
    # ICAO format translation (raw A)/B)/C)/E) style body) if present.
    icao_message = ""
    for translation in core.get("notamTranslation") or []:
        if isinstance(translation, dict) and str(translation.get("type") or "").upper() == "ICAO":
            icao_message = _text(translation.get("icao_message"))
            break

    # Coordinates / radius for the map tooltip.
    geometry = feature.get("geometry") if isinstance(feature, dict) else None
    coords: list[float] | None = None
    if isinstance(geometry, dict):
        gtype = geometry.get("type")
        if gtype == "Point":
            raw = geometry.get("coordinates")
            if isinstance(raw, list) and len(raw) >= 2:
                coords = [float(raw[1]), float(raw[0])]  # lat, lon
        elif gtype == "GeometryCollection":
            for sub in geometry.get("geometries") or []:
                if isinstance(sub, dict) and sub.get("type") == "Point":
                    raw = sub.get("coordinates")
                    if isinstance(raw, list) and len(raw) >= 2:
                        coords = [float(raw[1]), float(raw[0])]
                        break

    selection = _text(notam.get("selectionCode") or notam.get("qcode"))
    row: dict[str, Any] = {
        "id": ident or "NMS-NOTAM",
        "nms_id": _text(notam.get("id")),
        "scope_key": scope_key,
        "scope": scope,
        "location": location,
        "location_name": _text(core.get("locationName")) or "",
        "category": _qcode_category(selection, text),
        "status": _text(notam.get("type") or notam.get("status")) or "",
        "qcode": selection,
        "qcode_subject": _text(notam.get("selectionCode")) or "",
        "classification": _text(notam.get("classification")),
        "nrc": "",
        "effective_utc": effective or None,
        "expires_utc": None if permanent else (expires or None),
        "expires_estimated": str(notam.get("estimated") or "").lower() == "true",
        "permanent": bool(permanent),
        "schedule": _text(notam.get("schedule")),
        "coordinates": coords,
        "radius": _text(notam.get("radius")),
        "lower_limit": _text(notam.get("lowerLimit")),
        "upper_limit": _text(notam.get("upperLimit")),
        "text": text[:12000] or (icao_message[:12000] if icao_message else "No NOTAM text was returned."),
        "raw": icao_message[:16000] or text[:16000],
        "source": "FAA NMS",
        "source_order": 0,
    }
    return row


def normalize_geo_notams(features: list[dict[str, Any]], scope_key: str = "enroute", scope: str = "En route / FIR") -> list[dict[str, Any]]:
    return [normalize_nms_feature(f, scope_key, scope) for f in features if isinstance(f, dict)]


def _scope_for_icao(icao: str, origin: str, destination: str, alternates: list[str]) -> tuple[str, str]:
    icao = icao.upper()
    if icao and icao == origin:
        return "departure", f"Departure · {icao}"
    if icao and icao == destination:
        return "destination", f"Destination · {icao}"
    if icao and icao in {str(a).upper() for a in alternates if a}:
        return "alternate", f"Alternate · {icao}"
    return "enroute", f"En route / FIR · {icao}" if icao else "En route / FIR"


def route_notams(origin: str, destination: str, alternates: list[str]) -> dict[str, Any]:
    """Fetch NMS NOTAMs for the flight's dep / arr / alternates and return
    normalized rows with scope_key mapping -- the `notams_live` enrichment.

    Failure degrades to {"ok": False} -- the caller keeps SimBrief data.
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
        result = fetch_notams_by_location(code)
        if not result.get("ok"):
            unavailable += 1
            sources.append({"name": f"FAA NMS · {code}", "state": "unavailable", "detail": result.get("error", "")})
            continue
        scope_key, scope = _scope_for_icao(code, origin or "", destination or "", alternates)
        for feature in result.get("features") or []:
            row = normalize_nms_feature(feature, scope_key, scope)
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
