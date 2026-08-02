from __future__ import annotations

"""ChartFox-powered chart provider layer for OPS ROOM.

OAuth 2.0 PKCE (public client) + ChartFox API v2 grouped/endpoints.
v0.25.9: Removed unsupported ``charts:geos`` scope. Public grants allow
only ``charts:index charts:view charts:files charts:view_source_url``
plus oauth:user:name / oauth:telemetry:view / airports:view.
"""

import base64
import hashlib
import json
import logging
import math
import os
import re
import secrets
import shutil
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.parse import urlencode

import requests

from .settings_store import app_data_dir, load_settings
from .telemetry_provider import read_telemetry

_LOGGER = logging.getLogger("opsroom.charts")

_CHARTFOX_SCOPE = "charts:index charts:view charts:files charts:view_source_url"
# charts:geos is NOT included — ChartFox server returns 403 for this scope
# on the OPS ROOM client registration as of 2026-07-29.  Georef data will be
# absent from chart responses until ChartFox enables the scope.

# ---------------------------------------------------------------------------
# v0.25.17: thread-safe runtime diagnostics for ChartFox API interactions.
# Every _chartfox_api_request call automatically updates these metrics.
# ---------------------------------------------------------------------------
_METRICS_LOCK = threading.RLock()
_METRICS: dict = {
    "total": 0, "success": 0, "failed": 0,
    "auth_failures": 0, "rate_limits": 0, "network_failures": 0, "timeouts": 0,
    "cache_hits": 0, "cache_misses": 0, "cache_refreshes": 0,
    "response_times_ms": [],  # rolling window, last 200
    "last_success_ts": None, "last_failure_ts": None,
    "last_error_msg": None, "last_error_status": None, "last_endpoint": None,
    "last_success_endpoint": None,
}
_METRICS_HISTORY: list[dict] = []  # last 40 API calls for debug endpoint
_METRICS_MAX_TIMES = 200
_METRICS_MAX_HISTORY = 40


def _chartfox_record_metrics(method: str, path: str, ok: bool, elapsed_ms: float,
                             status_code: int | None = None,
                             error_msg: str | None = None,
                             is_cache_hit: bool = False) -> None:
    """Thread-safe metrics recorder called after every ChartFox API interaction."""
    ts = time.time()
    with _METRICS_LOCK:
        m = _METRICS
        m["total"] = (m["total"] or 0) + 1
        if ok:
            m["success"] = (m["success"] or 0) + 1
            m["last_success_ts"] = ts
            m["last_success_endpoint"] = f"{method} {path}"
        else:
            m["failed"] = (m["failed"] or 0) + 1
            m["last_failure_ts"] = ts
            m["last_error_msg"] = error_msg[:500] if error_msg else None
            m["last_error_status"] = status_code
            m["last_endpoint"] = f"{method} {path}"
            if status_code == 401 or status_code == 403:
                m["auth_failures"] = (m["auth_failures"] or 0) + 1
            elif status_code == 429:
                m["rate_limits"] = (m["rate_limits"] or 0) + 1
            elif status_code is None and error_msg and "timeout" in error_msg.lower():
                m["timeouts"] = (m["timeouts"] or 0) + 1
            elif status_code is None:
                m["network_failures"] = (m["network_failures"] or 0) + 1
        # cache tracking
        if is_cache_hit:
            m["cache_hits"] = (m["cache_hits"] or 0) + 1
        else:
            m["cache_misses"] = (m["cache_misses"] or 0) + 1
        # rolling response times
        times = m.setdefault("response_times_ms", [])
        times.append(round(elapsed_ms, 1))
        if len(times) > _METRICS_MAX_TIMES:
            m["response_times_ms"] = times[-_METRICS_MAX_TIMES:]
        # history for debug endpoint
        entry = {
            "time": ts,
            "method": method, "path": path,
            "ok": ok, "elapsed_ms": round(elapsed_ms, 1),
            "status": status_code,
            "error": error_msg[:200] if error_msg else None,
            "cache_hit": is_cache_hit,
        }
        _METRICS_HISTORY.append(entry)
        if len(_METRICS_HISTORY) > _METRICS_MAX_HISTORY:
            _METRICS_HISTORY[:] = _METRICS_HISTORY[-_METRICS_MAX_HISTORY:]


def _chartfox_metrics_snapshot() -> dict:
    """Return a thread-safe snapshot of the current runtime metrics.
    Never exposes secrets, tokens, or raw response bodies."""
    with _METRICS_LOCK:
        m = dict(_METRICS)
        times = list(m.get("response_times_ms") or [])
        history = list(_METRICS_HISTORY)
    avg_ms = round(sum(times) / len(times), 1) if times else None
    return {
        "healthy": m.get("failed", 0) < max(m.get("total", 1), 1) * 0.5,
        "counters": {
            "total": m.get("total", 0), "success": m.get("success", 0),
            "failed": m.get("failed", 0), "auth_failures": m.get("auth_failures", 0),
            "rate_limits": m.get("rate_limits", 0),
            "network_failures": m.get("network_failures", 0),
            "timeouts": m.get("timeouts", 0),
            "cache_hits": m.get("cache_hits", 0),
            "cache_misses": m.get("cache_misses", 0),
        },
        "performance": {
            "avg_response_ms": avg_ms,
            "min_response_ms": round(min(times), 1) if times else None,
            "max_response_ms": round(max(times), 1) if times else None,
            "sample_count": len(times),
        },
        "last_success": {
            "timestamp": m.get("last_success_ts"),
            "endpoint": m.get("last_success_endpoint"),
        } if m.get("last_success_ts") else None,
        "last_error": {
            "timestamp": m.get("last_failure_ts"),
            "endpoint": m.get("last_endpoint"),
            "status": m.get("last_error_status"),
            "message": m.get("last_error_msg"),
        } if m.get("last_failure_ts") else None,
        "recent_calls": history[-20:] if history else [],
    }

def _chartfox_reset_metrics() -> None:
    """v0.25.58: reset all runtime metrics to zero. Called after successful
    OAuth callback and on disconnect so stale failure counts don't persist
    across sessions and block the healthy/fresh calculation."""
    with _METRICS_LOCK:
        m = _METRICS
        m.update({"total": 0, "success": 0, "failed": 0,
                   "auth_failures": 0, "rate_limits": 0,
                   "network_failures": 0, "timeouts": 0,
                   "cache_hits": 0, "cache_misses": 0,
                   "response_times_ms": [],
                   "last_success_ts": None, "last_failure_ts": None,
                   "last_error_msg": None, "last_error_status": None,
                   "last_endpoint": None, "last_success_endpoint": None})
        _METRICS_HISTORY.clear()


_CHART_TYPE_NAMES = {0: "Airport", 1: "General", 2: "Textual",
                     3: "Ground Layout", 4: "SID", 5: "STAR",
                     6: "Approach", 7: "Transition", 99: "Briefing"}

_CHART_TYPE_ORDER = {3: 1, 4: 2, 5: 3, 6: 4, 7: 5,
                     1: 6, 2: 7, 99: 8, 0: 9}


def _chart_type_name(key):
    try:
        return _CHART_TYPE_NAMES.get(int(key), f"Type {key}")
    except (TypeError, ValueError):
        return "Charts"


def _chart_type_order(key):
    try:
        return _CHART_TYPE_ORDER.get(int(key), 99)
    except (TypeError, ValueError):
        return 99


def _normalise_chart_overview(item):
    raw_meta = item.get("meta") or []
    runways = []
    for entry in raw_meta:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("type_key") or "").lower() == "runways":
            for value in (entry.get("value") or []):
                if value:
                    runways.append(str(value))
    try:
        type_code = int(item.get("type"))
    except (TypeError, ValueError):
        type_code = None
    return {"id": str(item.get("id") or ""),
            "title": str(item.get("name") or item.get("code") or "Chart"),
            "code": str(item.get("code") or ""),
            "type": type_code,
            "type_key": str(item.get("type_key") or ""),
            "category": str(item.get("type_key") or "Charts"),
            "view_url": str(item.get("view_url") or ""),
            "url": str(item.get("view_url") or ""),
            "airport_icao": str(item.get("airport_icao") or ""),
            "runways": runways,
            "meta": raw_meta,
            "has_georeferences": bool(item.get("has_georeferences")),
            "requires_preauth": None,
            "allows_iframe": None,
            "provider": "ChartFox"}


def _normalise_chart_detail(data):
    files = []
    for entry in (data.get("files") or []):
        if not isinstance(entry, dict):
            continue
        try:
            ftype = int(entry.get("type"))
        except (TypeError, ValueError):
            ftype = None
        files.append({"type": ftype,
                      "type_label": {0: "PDF", 1: "IMG"}.get(ftype or -1, "HTML"),
                      "url": str(entry.get("url") or "")})
    georefs = []
    for entry in (data.get("georefs") or []):
        if not isinstance(entry, dict):
            continue
        georefs.append({"tx": entry.get("tx"), "ty": entry.get("ty"),
                        "k": entry.get("k"),
                        "transform_angle": entry.get("transform_angle"),
                        "pdf_page_rotation": entry.get("pdf_page_rotation"),
                        "page": entry.get("page")})
    source = data.get("source") if isinstance(data.get("source"), dict) else {}
    return {"id": str(data.get("id") or ""), "parent_id": data.get("parent_id"),
            "airport_icao": str(data.get("airport_icao") or ""),
            "name": str(data.get("name") or ""), "code": str(data.get("code") or ""),
            "type": data.get("type"), "type_key": str(data.get("type_key") or ""),
            "view_url": str(data.get("view_url") or ""),
            "url": str(data.get("url") or ""),
            "source_url": data.get("source_url"),
            "source_url_type": data.get("source_url_type"),
            "source_uuid": data.get("source_uuid"),
            "meta": data.get("meta") or [],
            "source": {"id": source.get("id"), "name": source.get("name"),
                       "display_name": source.get("display_name"),
                       "url": source.get("url"),
                       "iso_a2_countries": source.get("iso_a2_countries") or [],
                       "copyright_short": source.get("copyright_statement_short"),
                       "copyright_long": source.get("copyright_statement_long"),
                       "copyright_status": source.get("copyright_status_description")},
            "files": files, "georefs": georefs,
            "requires_preauth": bool(data.get("requires_preauth")),
            "allows_iframe": bool(data.get("allows_iframe")),
            "has_georeferences": bool(data.get("has_georeferences")),
            "provider": "ChartFox"}


def _text(value, default=""):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return default
    return str(value).strip()


def _number(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalise_airport(icao):
    return re.sub(r"[^A-Z0-9]", "", str(icao or "").upper())[:4]


def _settings_integrations():
    data = load_settings().get("integrations", {})
    return data if isinstance(data, dict) else {}


_CHARTFOX_AUTH_BASE = "https://api.chartfox.org/oauth"
_CHARTFOX_API_BASE = "https://api.chartfox.org"
# v0.25.9: client_id default. Live overrides come from
# Settings Store (integrations.chartfox_oauth_client_id) via _chartfox_client_id().
_CHARTFOX_CLIENT_ID_DEFAULT = "019f9162-61b5-734f-973d-bb80f02fbbfb"
_OAUTH_STATE_LOCK = threading.RLock()


def _chartfox_client_id() -> str:
    """Resolve the active ChartFox OAuth 2 client_id.

    Precedence:
      1. _settings_integrations()["chartfox_oauth_client_id"] (Settings Store override)
      2. _CHARTFOX_CLIENT_ID_DEFAULT (built-in fallback for ships that have not
         yet registered a client_id with ChartFox)

    The result is memoized against fetch time; callers can pass ``force=True``
    to re-read settings (used after hot-reload of the integration config).
    """
    return _resolve_chartfox_client_id(force=False)[0]


def _chartfox_client_id_source() -> str:
    """Whether the client_id is from Settings ("settings") or fallback ("fallback")."""
    return _resolve_chartfox_client_id(force=False)[1]


_CLIENT_ID_CACHE: tuple[float, tuple[str, str]] | None = None
_CLIENT_ID_CACHE_TTL_SECONDS = 5.0


def _resolve_chartfox_client_id(force: bool = False) -> tuple[str, str]:
    """Internal helper returned as (client_id, source). Memoized for 5s to keep the
    refresh-path (called on every 401) out of the settings-store hot path."""
    global _CLIENT_ID_CACHE
    now = time.monotonic()
    if not force and _CLIENT_ID_CACHE is not None and (now - _CLIENT_ID_CACHE[0]) < _CLIENT_ID_CACHE_TTL_SECONDS:
        return _CLIENT_ID_CACHE[1]
    try:
        s = _settings_integrations() or {}
        override = str(s.get("chartfox_oauth_client_id", "") or "").strip()
        if override:
            value = (override, "settings")
        else:
            value = (_CHARTFOX_CLIENT_ID_DEFAULT, "fallback")
    except Exception:
        value = (_CHARTFOX_CLIENT_ID_DEFAULT, "fallback")
    _CLIENT_ID_CACHE = (now, value)
    return value
_OAUTH_STATE_TTL_SECONDS = 15 * 60
_OAUTH_STATE: dict = {}


def _generate_code_verifier():
    return secrets.token_urlsafe(64)[:128]


def _code_challenge_from_verifier(verifier):
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _chartfox_oauth_settings():
    s = _settings_integrations()
    return {"redirect_uri": str(s.get("chartfox_oauth_redirect_uri", "") or "").strip()}


def _chartfox_oauth_token_file():
    return app_data_dir() / "chartfox_oauth_token.json"


def _chartfox_oauth_state_file():
    return app_data_dir() / "chartfox_oauth_state.json"


def _chartfox_load_token():
    path = _chartfox_oauth_token_file()
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _chartfox_save_token(token):
    path = _chartfox_oauth_token_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(token, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _chartfox_load_states():
    path = _chartfox_oauth_state_file()
    if not path.is_file():
        return dict(_OAUTH_STATE)
    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle) or {}
        if not isinstance(raw, dict):
            return dict(_OAUTH_STATE)
        now = time.time()
        return {k: v for k, v in raw.items() if float(v.get("expires_at", 0)) > now}
    except (OSError, json.JSONDecodeError):
        return dict(_OAUTH_STATE)


def _chartfox_persist_states():
    path = _chartfox_oauth_state_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(_OAUTH_STATE, handle, separators=(",", ":"))
    except OSError:
        pass


def _chartfox_seen_states():
    with _OAUTH_STATE_LOCK:
        merged = _chartfox_load_states()
        merged.update(_OAUTH_STATE)
        now = time.time()
        active = {k: v for k, v in merged.items() if float(v.get("expires_at", 0)) > now}
        _OAUTH_STATE.clear()
        _OAUTH_STATE.update(active)
        return active


def _request_redirect_uri(redirect_uri=""):
    cleaned = str(redirect_uri or "").strip().rstrip("/")
    if cleaned:
        return cleaned
    return _chartfox_oauth_settings()["redirect_uri"].rstrip("/")


def _derive_redirect_uri_from_host(host_header, port):
    if not host_header:
        return None
    allowed = ("127.", "::1", "localhost", "10.", "192.168.", "169.254.",
               "172.16.", "172.17.", "172.18.", "172.19.", "172.20.",
               "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
               "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.")
    lower = host_header.lower().split(":")[0]
    if not any(lower.startswith(p.lower()) for p in allowed) and lower not in {"localhost", "::1"}:
        return None
    return f"http://{host_header}:{port}"


def _chartfox_bearer_redirect_uri(redirect):
    parsed = urlparse(redirect)
    path = parsed.path or ""
    if path.endswith("/api/charts/chartfox/callback") or path.endswith("/api/chartfox/oauth/callback"):
        return redirect
    if path.endswith("/"):
        return f"{redirect}api/charts/chartfox/callback"
    return f"{redirect}/api/charts/chartfox/callback"


def _persist_token_if_scope_complete(new_token: dict[str, Any]) -> dict[str, Any]:
    """v0.25.9: gate ChartFox token persistence on the requested-scope set.

    Both the OAuth callback and the refresh-token path funnel through this. If
    the granted scope is a strict subset of the requested scope, the on-disk
    token file is cleared and the broken credential is NOT persisted — otherwise
    the next /api/charts/chartfox/* call would 403 mid-stream and the SPA would
    see partial chart loading.

    RFC 6749 §4.1.4 says the ``scope`` parameter is OPTIONAL in the token
    response when the server grants the full requested scope, and REQUIRED when
    granting a subset. We treat an empty/missing ``scope`` as "all four scopes
    granted" and trust the HTTP 200 — this matches ChartFox's behaviour
    (verified 2024-XX-XX) where the /token endpoint omits ``scope`` on success.

    Returns:
        {"ok": True, requested_scopes, granted_scopes, missing_scopes: [], [empty_echo_trust]}
            when the token is saved.
        {"ok": False, "scope_mismatch": True, requested_scopes, granted_scopes,
            missing_scopes} when refused; the token file has been cleared.
    """
    granted_scope = str((new_token or {}).get("scope") or "")
    requested_set = set(_CHARTFOX_SCOPE.split())
    granted_set = set(granted_scope.split()) if granted_scope else set()
    missing = sorted(requested_set - granted_set)
    # v0.25.9 empty-echo trust: ChartFox omits `scope` on a full grant per RFC 6749 §4.1.4.
    # Empty echo -> full grant presumed. Strict-subset echo -> refused.
    if not granted_set:
        _LOGGER.info("[CHARTFOX OAUTH] granted_scope_echo=empty trusting_http_200 - all %d scopes presumed granted",
                     len(requested_set))
    elif not requested_set.issubset(granted_set):
        _LOGGER.warning("[CHARTFOX OAUTH] scope_mismatch refused-persist missing=%s granted=%s",
                        missing, sorted(granted_set))
        _chartfox_save_token({})
        return {"ok": False, "scope_mismatch": True,
                "requested_scopes": sorted(requested_set),
                "granted_scopes": sorted(granted_set),
                "missing_scopes": missing}
    new_token["issued_at"] = time.time()
    _chartfox_save_token(new_token)
    return {"ok": True,
            "requested_scopes": sorted(requested_set),
            "granted_scopes": sorted(granted_set),
            "missing_scopes": missing,
            **({"empty_echo_trust": True} if not granted_set else {})}


def chartfox_oauth_authorize_url(redirect_uri="", host_header="", port=8080):
    redirect = _request_redirect_uri(redirect_uri) or _derive_redirect_uri_from_host(host_header, port) or ""
    redirect = _chartfox_bearer_redirect_uri(redirect) if redirect else ""
    if not redirect:
        return {"ok": False, "error": "No redirect URI is configured."}
    state = uuid.uuid4().hex
    code_verifier = _generate_code_verifier()
    code_challenge = _code_challenge_from_verifier(code_verifier)
    expires_at = time.time() + _OAUTH_STATE_TTL_SECONDS
    with _OAUTH_STATE_LOCK:
        _chartfox_seen_states()
        _OAUTH_STATE[state] = {"redirect_uri": redirect, "code_verifier": code_verifier, "expires_at": expires_at}
        _chartfox_persist_states()
    params = {"client_id": _chartfox_client_id(), "redirect_uri": redirect,
              "response_type": "code", "state": state,
              "code_challenge": code_challenge, "code_challenge_method": "S256",
              "scope": _CHARTFOX_SCOPE}
    url = f"{_CHARTFOX_AUTH_BASE}/authorize?{urlencode(params)}"
    _LOGGER.info("[CHARTFOX OAUTH] requested_scopes=%s redirect_uri=%s state=%s",
                 _CHARTFOX_SCOPE, redirect, state)
    return {"ok": True, "url": url, "state": state, "redirect_uri": redirect,
            "scope": _CHARTFOX_SCOPE, "requested_scopes": _CHARTFOX_SCOPE.split()}


def chartfox_oauth_callback(code, state):
    with _OAUTH_STATE_LOCK:
        _chartfox_seen_states()
        stored = _OAUTH_STATE.pop(state, None)
    redirect = stored.get("redirect_uri") if stored else _chartfox_oauth_settings()["redirect_uri"]
    code_verifier = stored.get("code_verifier") if stored else None
    if not code_verifier:
        with _OAUTH_STATE_LOCK:
            _chartfox_persist_states()
        return {"ok": False, "error": "Invalid or expired OAuth state. Please try connecting again."}
    try:
        resp = requests.post(f"{_CHARTFOX_AUTH_BASE}/token",
                             data={"grant_type": "authorization_code", "code": code,
                                   "redirect_uri": redirect, "client_id": _chartfox_client_id(),
                                   "code_verifier": code_verifier},
                             timeout=30, headers={"Accept": "application/json"})
        if not resp.ok:
            _LOGGER.warning("[CHARTFOX OAUTH] token_exchange_failed http=%s detail=%s",
                            resp.status_code, resp.text[:500])
            return {"ok": False, "error": f"Token exchange failed: HTTP {resp.status_code}",
                    "detail": resp.text[:500]}
        token = resp.json()
        granted_scope = str(token.get("scope") or "")
        _LOGGER.info("[CHARTFOX OAUTH] granted_scope=%s requested_scope=%s token_type=%s expires_in=%s",
                     granted_scope, _CHARTFOX_SCOPE, token.get("token_type"), token.get("expires_in"))
        gate = _persist_token_if_scope_complete(token)
        with _OAUTH_STATE_LOCK:
            _chartfox_persist_states()
        if not gate.get("ok"):
            return {"ok": False,
                    "error": f"ChartFox granted a subset of the requested scopes. Missing: {gate['missing_scopes']}. Reconnect ChartFox from Briefing > Charts.",
                    "scope_mismatch": True,
                    "redirect_uri": redirect, "requested_scopes": gate["requested_scopes"],
                    "granted_scopes": gate["granted_scopes"], "missing_scopes": gate["missing_scopes"]}
        _chartfox_reset_metrics()
        return {"ok": True, "token_type": token.get("token_type"),
                "scope": token.get("scope"), "expires_in": token.get("expires_in"),
                "redirect_uri": redirect, "requested_scopes": gate["requested_scopes"],
                "granted_scopes": gate["granted_scopes"], "missing_scopes": gate["missing_scopes"]}
    except requests.RequestException as exc:
        _LOGGER.warning("[CHARTFOX OAUTH] token_exchange_request_exception=%s", exc)
        return {"ok": False, "error": f"Token exchange request failed: {exc}"}


def chartfox_diagnostics() -> dict:
    """v0.25.17: OAuth config + runtime metrics (counters, performance, errors).
    Returns structured JSON suitable for user-facing diagnostic display."""
    try:
        client_id = _chartfox_client_id()
        source = _chartfox_client_id_source()
    except Exception as exc:
        client_id = f"<error: {type(exc).__name__}: {exc}>"
        source = "error"
    if isinstance(client_id, str) and len(client_id) >= 8:
        masked = f"{client_id[:4]}***{client_id[-4:]}"
    else:
        masked = "****"
    token = _chartfox_load_token()
    with _OAUTH_STATE_LOCK:
        pending_state_count = len(_OAUTH_STATE)
    status = chartfox_oauth_status()
    runtime = _chartfox_metrics_snapshot()
    # v0.25.17: reuse chartfox_oauth_status() which now correctly handles
    # empty-echo trust (ChartFox omits `scope` on full grant per RFC 6749 §4.1.4).
    granted_scopes_list = status.get("granted_scopes", [])
    return {
        "ok": True,
        "auth_base": _CHARTFOX_AUTH_BASE,
        "client_id_masked": masked,
        "client_id_source": source,
        "redirect_uri": _chartfox_oauth_settings().get("redirect_uri", "") or "http://localhost:8080/api/charts/chartfox/callback",
        "requested_scopes": _CHARTFOX_SCOPE.split(),
        "scope": _CHARTFOX_SCOPE,
        "token": {
            "has_token": bool(isinstance(token, dict) and token.get("access_token")),
            "granted_scopes": granted_scopes_list,
            "expires_in_remaining": status.get("expires_in_remaining"),
        },
        "pending_oauth_state_count": pending_state_count,
        "runtime": runtime,
        "hints": [
            "invalid_client on /authorize means ChartFox does not recognize this client_id. Verify it is registered at chartfox.org.",
            "If you set Settings -> integrations.chartfox_oauth_client_id to override, it must be an exact match with the registered app.",
            "redirect_uri must match a URI registered with the ChartFox app.",
            "After updating client_id, click Reconnect ChartFox in Briefing > Charts to rebuild the authorize URL.",
        ],
    }


def chartfox_debug(chart_id: str = "", airport: str = "") -> dict:
    """v0.25.58: enhanced debug endpoint with live API response inspection.

    Pass ?chart_id=UUID to include the raw ChartFox API detail response,
    the proxy render-mode decision, and source_url/files[] inspection.
    Pass ?airport=ICAO to include grouped charts for that airport.

    Redacts all secrets automatically. Intended for developer troubleshooting."""
    diag = chartfox_diagnostics()
    runtime = diag.get("runtime") or _chartfox_metrics_snapshot()
    token = _chartfox_load_token()
    status = chartfox_oauth_status()
    cache_stats = {}
    try:
        search_info = _chartfox_airport_search_cached.cache_info()
        detail_info = _chartfox_chart_detail_cached.cache_info()
        grouped_info = _chartfox_airport_grouped_charts_cached.cache_info()
        cache_stats = {
            "search": {"hits": search_info.hits, "misses": search_info.misses, "currsize": search_info.currsize, "maxsize": search_info.maxsize},
            "detail": {"hits": detail_info.hits, "misses": detail_info.misses, "currsize": detail_info.currsize, "maxsize": detail_info.maxsize},
            "grouped": {"hits": grouped_info.hits, "misses": grouped_info.misses, "currsize": grouped_info.currsize, "maxsize": grouped_info.maxsize},
        }
    except Exception:
        cache_stats = {"error": "cache_info not available"}

    # ── live API response inspection ──
    api_inspection: dict = {}
    cid = re.sub(r"[^A-Za-z0-9\-]", "", str(chart_id or "").strip())[:64]
    ap = _normalise_airport(airport or "")

    if cid:
        # Fetch the raw chart detail from ChartFox API.
        # Note: _chartfox_api_request auto-updates runtime metrics.
        # This is intentional — the debug snapshot reflects live state.
        t0 = time.monotonic()
        raw_result = _chartfox_api_request("GET", f"/v2/charts/{cid}", timeout=15)
        api_elapsed = round((time.monotonic() - t0) * 1000, 1)

        if raw_result.get("ok"):
            raw_data = raw_result.get("data")
            if not isinstance(raw_data, dict) or not raw_data:
                api_inspection = {
                    "chart_id": cid,
                    "api_call_ok": True,
                    "api_elapsed_ms": api_elapsed,
                    "warning": "ChartFox API returned ok but the response body was empty or not a dict.",
                }
            else:
                normalized = _normalise_chart_detail(raw_data)

                # Inspect source_url and files[] for debugging
                source_url = str(raw_data.get("source_url") or "")
                source_url_type = raw_data.get("source_url_type")
                raw_files = raw_data.get("files") or []
                allows_iframe = bool(raw_data.get("allows_iframe"))
                view_url = str(raw_data.get("view_url") or "")

                # Determine the render mode the proxy would pick
                files_pdf = [f for f in raw_files if isinstance(f, dict) and f.get("type") == 0]
                files_img = [f for f in raw_files if isinstance(f, dict) and f.get("type") == 1]
                render_mode = "unavailable"
                render_source = "none"
                if files_pdf:
                    render_mode = "direct_file"
                    render_source = f"files[].type=0 (PDF) → {files_pdf[0].get('url', '')[:80]}"
                elif files_img:
                    render_mode = "direct_file"
                    render_source = f"files[].type=1 (IMG) → {files_img[0].get('url', '')[:80]}"
                elif source_url and source_url_type in (0, 1):
                    render_mode = "direct_file"
                    render_source = f"source_url (type={source_url_type}) → {source_url[:80]}"
                elif allows_iframe and view_url:
                    render_mode = "iframe"
                    render_source = f"allows_iframe → {view_url[:80]}"

                api_inspection = {
                    "chart_id": cid,
                    "api_call_ok": True,
                    "api_elapsed_ms": api_elapsed,
                    "chart_name": normalized.get("name", ""),
                    "chart_code": normalized.get("code", ""),
                    "airport_icao": normalized.get("airport_icao", ""),
                    "type": normalized.get("type"),
                    "type_key": normalized.get("type_key", ""),
                    "render_mode": render_mode,
                    "render_source": render_source,
                    "source_url": source_url[:200] if source_url else None,
                    "source_url_type": source_url_type,
                    "allows_iframe": allows_iframe,
                    "view_url": view_url[:200] if view_url else None,
                    "requires_preauth": bool(raw_data.get("requires_preauth")),
                    "has_georeferences": bool(raw_data.get("has_georeferences")),
                    "files_count": len(raw_files),
                    "files": [{"type": f.get("type"), "url": str(f.get("url", ""))[:120]}
                              for f in raw_files[:10] if isinstance(f, dict)],
                    "source": {
                        "name": (raw_data.get("source") or {}).get("name", ""),
                        "display_name": (raw_data.get("source") or {}).get("display_name", ""),
                        "copyright_short": (raw_data.get("source") or {}).get("copyright_statement_short", ""),
                    } if raw_data.get("source") else None,
                }
        else:
            api_inspection = {
                "chart_id": cid,
                "api_call_ok": False,
                "api_elapsed_ms": api_elapsed,
                "error": raw_result.get("error", "Unknown error")[:300],
                "detail": raw_result.get("detail", "")[:300] if isinstance(raw_result.get("detail"), str) else "",
            }

    if ap:
        # Fetch grouped charts for the airport (includes per-chart preview data)
        grouped = chartfox_airport_grouped_charts(ap)
        group_count = len(grouped.get("groups", []))
        total_charts = len(grouped.get("items", []))
        # Sample first 3 charts with render-mode hints
        sample_charts: list = []
        for item in grouped.get("items", [])[:3]:
            if isinstance(item, dict):
                sample_charts.append({
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "code": item.get("code"),
                    "type": item.get("type"),
                    "type_key": item.get("type_key"),
                })
        api_inspection["airport"] = {
            "icao": ap,
            "api_call_ok": grouped.get("ok", False),
            "groups_count": group_count,
            "total_charts": total_charts,
            "sample_charts": sample_charts,
            "error": grouped.get("error", "") if not grouped.get("ok") else None,
        }

    return {
        **diag,
        "runtime": runtime,
        "oauth": {
            "configured": status.get("configured"),
            "has_token": status.get("has_token"),
            "expires_in_remaining": status.get("expires_in_remaining"),
            "scopes_granted": status.get("granted_scopes"),
            "scopes_missing": status.get("missing_scopes"),
            "token_issued_at": token.get("issued_at") if isinstance(token, dict) else None,
            "token_type": token.get("token_type") if isinstance(token, dict) else None,
        },
        "cache": {
            **cache_stats,
            "cache_hits": runtime["counters"]["cache_hits"],
            "cache_misses": runtime["counters"]["cache_misses"],
            "cache_refreshes": runtime["counters"].get("cache_refreshes", 0),
            "file_reads": _chartfox_cache_reads,
            "file_hits": _chartfox_cache_hits,
            "file_writes": _chartfox_cache_writes,
        },
        "api_inspection": api_inspection if api_inspection else None,
        "api_inspection_hint": (
            "Add ?chart_id=UUID to inspect a specific chart, or ?airport=ICAO for grouped charts. "
            "Example: /api/charts/chartfox/debug?chart_id=6872384f-a9d3-4513-a1e5-d2e99e2b9dfb"
        ) if not api_inspection else None,
        "recent_errors": [c for c in runtime.get("recent_calls", []) if not c.get("ok")][-10:] if runtime.get("recent_calls") else [],
        "version": "v0.25.58",
        "build": "public-release",
        "uptime_seconds": round(time.monotonic(), 1),
    }


def chartfox_oauth_disconnect():
    _chartfox_save_token({})
    _chartfox_reset_metrics()
    with _OAUTH_STATE_LOCK:
        _OAUTH_STATE.clear()
        try:
            _chartfox_oauth_state_file().unlink(missing_ok=True)
        except OSError:
            pass
    return {"ok": True}


def chartfox_oauth_status():
    token = _chartfox_load_token()
    if token:
        try:
            now = time.time()
            expires_at = float(token.get("issued_at", now)) + float(token.get("expires_in", 0))
            remaining = max(0, int(expires_at - now))
        except (TypeError, ValueError):
            remaining = None
    else:
        remaining = None
    with _OAUTH_STATE_LOCK:
        _chartfox_seen_states()
        active_count = len(_OAUTH_STATE)
    granted_scope = str(token.get("scope") or "")
    granted_set = set(granted_scope.split()) if granted_scope else set()
    requested_set = set(_CHARTFOX_SCOPE.split())
    # v0.25.17 empty-echo trust: when ChartFox omits `scope` on a full grant
    # (per RFC 6749 §4.1.4), report all requested scopes as granted so the
    # front-end and diagnostics never show an empty granted set when the
    # token is actually valid.
    if not granted_set and bool(token.get("access_token")):
        granted_set = requested_set
    return {"ok": True, "configured": True,
            "has_token": bool(token.get("access_token")),
            "client_id_configured": True, "client_secret_configured": False,
            "redirect_uri": _chartfox_oauth_settings()["redirect_uri"],
            "scope": _CHARTFOX_SCOPE, "requested_scopes": _CHARTFOX_SCOPE.split(),
            "granted_scopes": sorted(granted_set),
            "missing_scopes": sorted(requested_set - granted_set),
            "features_partial": bool(granted_set and granted_set != requested_set),
            "expires_in_remaining": remaining, "pending_state_count": active_count}


def _chartfox_api_request(method, path, params=None, **kwargs):
    """v0.25.17: every call auto-updates the thread-safe runtime metrics."""
    t0 = time.monotonic()
    token = _chartfox_load_token()
    access_token = token.get("access_token")
    if not access_token:
        _chartfox_record_metrics(method, path, False, (time.monotonic() - t0) * 1000,
                                 status_code=401, error_msg="No ChartFox OAuth access token")
        return {"ok": False, "error": "No ChartFox OAuth access token. Connect via Briefing > Charts tab."}
    headers = dict(kwargs.pop("headers", {}))
    headers.setdefault("Accept", "application/json")
    headers["Authorization"] = f"Bearer {access_token}"
    timeout = kwargs.pop("timeout", 20)
    try:
        resp = requests.request(method, f"{_CHARTFOX_API_BASE}{path}",
                                headers=headers, params=params or None, timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        _chartfox_record_metrics(method, path, False, (time.monotonic() - t0) * 1000,
                                 error_msg=f"{type(exc).__name__}: {exc}")
        return {"ok": False, "error": f"ChartFox API request failed: {exc}"}
    elapsed_ms = (time.monotonic() - t0) * 1000
    if resp.status_code == 401 and token.get("refresh_token"):
        try:
            refresh_resp = requests.post(f"{_CHARTFOX_AUTH_BASE}/token",
                                         data={"grant_type": "refresh_token",
                                               "refresh_token": token.get("refresh_token"),
                                               "client_id": _chartfox_client_id()},
                                         timeout=30, headers={"Accept": "application/json"})
            if refresh_resp.ok:
                new_token = refresh_resp.json()
                new_token.setdefault("refresh_token", token.get("refresh_token"))
                new_token["issued_at"] = time.time()
                refresh_gate = _persist_token_if_scope_complete(new_token)
                if not refresh_gate.get("ok"):
                    _chartfox_record_metrics(method, path, False, elapsed_ms,
                                             status_code=401, error_msg="Refresh token scope reduced")
                    return {"ok": False,
                            "error": f"ChartFox refresh token has reduced scope. Missing: {refresh_gate['missing_scopes']}. Reconnect ChartFox from Briefing > Charts.",
                            "scope_mismatch": True,
                            "missing_scopes": refresh_gate["missing_scopes"]}
                headers["Authorization"] = f"Bearer {new_token.get('access_token', '')}"
                t_retry = time.monotonic()
                resp = requests.request(method, f"{_CHARTFOX_API_BASE}{path}",
                                        headers=headers, params=params or None, timeout=timeout, **kwargs)
                elapsed_ms += (time.monotonic() - t_retry) * 1000
            else:
                _chartfox_save_token({})
                _chartfox_record_metrics(method, path, False, elapsed_ms,
                                         status_code=401, error_msg="Token refresh rejected")
                return {"ok": False, "error": "ChartFox OAuth token expired and refresh failed. Reconnect from Briefing > Charts."}
        except requests.RequestException as exc:
            _chartfox_record_metrics(method, path, False, elapsed_ms,
                                     error_msg=f"Refresh request failed: {exc}")
            return {"ok": False, "error": "ChartFox OAuth token expired and refresh request failed."}
    elif resp.status_code == 401:
        _chartfox_save_token({})
        _chartfox_record_metrics(method, path, False, elapsed_ms, status_code=401,
                                 error_msg="Token expired, no refresh token")
        return {"ok": False, "error": "ChartFox OAuth token expired. Reconnect from Briefing > Charts."}
    if not resp.ok:
        _chartfox_record_metrics(method, path, False, elapsed_ms,
                                 status_code=resp.status_code, error_msg=resp.text[:200])
        return {"ok": False, "error": f"ChartFox API error: HTTP {resp.status_code}", "detail": resp.text[:500]}
    try:
        data = resp.json()
    except ValueError:
        _chartfox_record_metrics(method, path, False, elapsed_ms,
                                 error_msg="Non-JSON response body")
        return {"ok": False, "error": "ChartFox returned a non-JSON response", "detail": resp.text[:500]}
    _chartfox_record_metrics(method, path, True, elapsed_ms, status_code=resp.status_code)
    return {"ok": True, "data": data}


@lru_cache(maxsize=128)
def _chartfox_airport_search_cached(query, page, page_size):
    params = {"page": max(1, page), "query": query.strip()[:120]} if query.strip() else {"page": max(1, page)}
    if page_size:
        params["per_page"] = max(1, min(int(page_size), 40))
    result = _chartfox_api_request("GET", "/v2/airports", params=params, timeout=10)
    if not result.get("ok"):
        return result
    payload = result.get("data") or {}
    rows = payload.get("data") or []
    cleaned = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        cleaned.append({"id": item.get("id"),
                        "ident": str(item.get("ident") or item.get("icao_code") or ""),
                        "icao_code": str(item.get("icao_code") or item.get("ident") or ""),
                        "iata_code": item.get("iata_code") or "",
                        "name": str(item.get("name") or ""),
                        "type": item.get("type"),
                        "latitude": item.get("latitude"), "longitude": item.get("longitude"),
                        "elevation_ft": item.get("elevation_ft"),
                        "iso_a2_country": item.get("iso_a2_country") or "",
                        "has_charts": bool(item.get("has_charts"))})
    return {"ok": True, "query": query,
            "page": payload.get("current_page") or max(1, page),
            "last_page": payload.get("last_page") or 1,
            "per_page": payload.get("per_page") or len(cleaned),
            "total": payload.get("total") or len(cleaned),
            "items": cleaned}


def chartfox_airport_search(query, page=1, page_size=10):
    cleaned = re.sub(r"\s+", " ", str(query or "").strip())[:120]
    if not cleaned:
        return {"ok": True, "items": [], "query": "", "page": 1, "total": 0}
    return _chartfox_airport_search_cached(cleaned.lower(), int(page), int(page_size))


@lru_cache(maxsize=128)
def _chartfox_chart_detail_cached(chart_id: str) -> dict:
    """Cached wrapper around chartfox_chart_detail.  chart_id must be a
    stable, normalised string so the LRU cache key matches across calls."""
    return chartfox_chart_detail(chart_id)


def chartfox_chart_detail(chart_id):
    cid = re.sub(r"[^A-Za-z0-9\-]", "", str(chart_id or "").strip())[:64]
    if not cid:
        return {"ok": False, "error": "ChartFox chart id is required."}
    result = _chartfox_api_request("GET", f"/v2/charts/{cid}", timeout=15)
    if not result.get("ok"):
        return result
    return {"ok": True, "chart": _normalise_chart_detail(result.get("data") or {})}


@lru_cache(maxsize=64)
def _chartfox_airport_grouped_charts_cached(icao: str) -> dict:
    """Cached wrapper around chartfox_airport_grouped_charts.  icao must be
    a normalised, uppercase string so the LRU cache key matches."""
    return chartfox_airport_grouped_charts(icao)


def chartfox_airport_grouped_charts(icao):
    airport = _normalise_airport(icao)
    if not airport:
        return {"ok": False, "airport": icao, "items": [], "groups": [], "error": "No airport ICAO provided"}
    result = _chartfox_api_request("GET", f"/v2/airports/{airport}/charts/grouped", timeout=20)
    if not result.get("ok"):
        return {"ok": False, "airport": airport, "items": [], "groups": [], "error": result.get("error")}
    payload = result.get("data") or {}
    bucket_map = {}
    source = payload.get("data") if isinstance(payload.get("data"), dict) else (
        payload if isinstance(payload, dict) else {})
    if isinstance(source, dict):
        for raw_key, raw_list in source.items():
            try:
                bucket_key = int(str(raw_key).strip())
            except (TypeError, ValueError):
                continue
            if not isinstance(raw_list, list):
                continue
            bucket_map[bucket_key] = [item for item in raw_list if isinstance(item, dict)]
    elif isinstance(payload, list):
        bucket_map.setdefault(0, []).extend(item for item in payload if isinstance(item, dict))
    groups = []
    all_items = []
    for bucket_key in sorted(bucket_map.keys(), key=lambda v: (_chart_type_order(v), _chart_type_name(v))):
        items = bucket_map[bucket_key]
        if not items:
            continue
        group_name = _chart_type_name(bucket_key)
        group_entry = {"name": group_name,
                       "type_key": group_name.upper().replace(" ", "_"),
                       "type": bucket_key,
                       "order": _chart_type_order(bucket_key),
                       "charts": []}
        for chart in items:
            overview = _normalise_chart_overview(chart)
            group_entry["charts"].append(overview)
            all_items.append(overview)
        groups.append(group_entry)
    return {"ok": True, "airport": airport, "provider": "ChartFox",
            "items": all_items, "groups": groups}


def briefing_charts():
    from .simbrief_client import cached_plan
    settings = load_settings()
    user = str(settings.get("identity", {}).get("simbrief_user_id") or "")
    plan = cached_plan(user) if user else None
    if not plan or not plan.get("ok"):
        return {"ok": False, "items": [], "airports": [], "message": "No SimBrief OFP is currently cached"}
    airports = []
    for role, key in (("origin", "origin"), ("destination", "destination"), ("alternate", "alternate")):
        icao = _normalise_airport((plan.get(key) or {}).get("icao"))
        if icao and all(existing != icao for existing, _ in airports):
            airports.append((icao, role))
    return {"ok": True,
            "flight": {"callsign": plan.get("callsign"),
                       "origin": (plan.get("origin") or {}).get("icao"),
                       "destination": (plan.get("destination") or {}).get("icao"),
                       "alternate": (plan.get("alternate") or {}).get("icao")},
            "airports": [{"icao": icao, "role": role} for icao, role in airports],
            "items": [], "source_links": [], "providers": [],
            "message": "ChartFox charts loaded from the ChartFox section above"}


_EPSG3857_HALF_CIRCUMFERENCE = 20037508.34


def _lonlat_to_epsg3857(lon, lat):
    x = lon * _EPSG3857_HALF_CIRCUMFERENCE / 180.0
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * _EPSG3857_HALF_CIRCUMFERENCE / math.pi
    return x, y


def _chartfox_georef_to_pixel(lon, lat, tx, ty, k, angle_deg,
                              display_width_px, display_height_px):
    world_x, world_y = _lonlat_to_epsg3857(lon, lat)
    x_wt = world_x - tx
    y_wt = world_y - ty
    k_local = k / display_height_px
    angle = math.radians(angle_deg)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    inv_k = 1.0 / k_local
    x_chart = inv_k * (cos_a * x_wt + sin_a * y_wt)
    y_chart = inv_k * (sin_a * x_wt - cos_a * y_wt)
    return x_chart * display_width_px, y_chart * display_height_px


def _chartfox_overlay_compute(georef, display_width_px, display_height_px):
    try:
        tx = float(georef.get("tx") or 0)
        ty = float(georef.get("ty") or 0)
        k = float(georef.get("k") or 1)
        angle = float(georef.get("transform_angle") or 0)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Invalid georeference parameters"}
    tel = read_telemetry(force=False)
    lon = _number(tel.get("lon"))
    lat = _number(tel.get("lat"))
    if lon is None or lat is None:
        return {"ok": False, "error": "No live position available"}
    try:
        px, py = _chartfox_georef_to_pixel(lon, lat, tx, ty, k, angle,
                                            display_width_px, display_height_px)
    except (ValueError, ZeroDivisionError) as exc:
        return {"ok": False, "error": f"Overlay computation failed: {exc}"}
    return {"ok": True, "x_px": round(px, 1), "y_px": round(py, 1),
            "lat": round(lat, 6), "lon": round(lon, 6),
            "heading_deg": _number(tel.get("heading_deg")) or _number(tel.get("track_deg")) or 0,
            "ground_speed_kts": _number(tel.get("ground_speed_kts")) or 0,
            "page": georef.get("page"),
            "pdf_page_rotation": georef.get("pdf_page_rotation") or georef.get("pdf_rotation_angle") or 0,
            "scope_warning": "v0.25.58: charts:geos scope not available (ChartFox returns 403); georefs still parsed from chart detail responses"}


def ownship_overlay_status():
    tel = read_telemetry(force=False)
    return {"ok": bool(tel.get("ok")),
            "source": tel.get("source"),
            "lat": tel.get("lat"), "lon": tel.get("lon"),
            "heading_deg": tel.get("heading_deg") or tel.get("track_deg"),
            "altitude_ft": tel.get("altitude_ft") or tel.get("indicated_altitude_ft"),
            "ground_speed_kts": tel.get("ground_speed_kts"),
            "overlay_available": False,
            "message": "Live position available; chart overlay requires georef params per chart. v0.25.58: charts:geos scope not available from ChartFox."}


# ---------------------------------------------------------------------------
# AIRAC-aware chart file cache (28-day cycle)
# ---------------------------------------------------------------------------

# Reference: 2023-01-26 = AIRAC cycle 2301. We use a monotonic cycle counter
# (days since epoch // 28) for cache folders -- simpler than YYCC format and
# never drifts across 14-cycle years or leap years.
_AIRAC_EPOCH = date(2023, 1, 26)
_CHARTFOX_CACHE_DIR = app_data_dir() / "chartfox_cache"
_last_prune_cycle: int = -1
# v0.25.58: file-cache read/write counters for debug endpoint.
_chartfox_cache_reads: int = 0
_chartfox_cache_hits: int = 0
_chartfox_cache_writes: int = 0


def _airac_cycle() -> int:
    """Return the current monotonic AIRAC cycle number."""
    delta = date.today() - _AIRAC_EPOCH
    return delta.days // 28


def _airac_seconds_remaining() -> int:
    """Seconds until the start of the next AIRAC cycle (for Cache-Control max-age)."""
    today = date.today()
    delta = today - _AIRAC_EPOCH
    current_cycle_start = _AIRAC_EPOCH + timedelta(days=(delta.days // 28) * 28)
    next_cycle_start = current_cycle_start + timedelta(days=28)
    next_utc = datetime.combine(next_cycle_start, datetime.min.time(), tzinfo=timezone.utc)
    remaining = (next_utc - datetime.now(timezone.utc)).total_seconds()
    return max(600, int(remaining))  # at least 10 minutes


def _chartfox_cache_path(chart_id: str, ext: str) -> Path:
    """Path where a fetched chart file should be cached."""
    cycle = _airac_cycle()
    return _CHARTFOX_CACHE_DIR / f"cycle_{cycle}" / f"{chart_id}.{ext}"


def _chartfox_cache_get(chart_id: str) -> tuple[bytes | None, str | None, str | None]:
    """Try to read a cached chart file. Returns (body, content_type, filename) or (None, None, None).

    v0.25.58 (round 2): iterates ALL cached chunks and sniffs bytes (with a
    small BOM/whitespace tolerance) before returning. Mismatched chunks are
    QUARANTINED (renamed with a `.quarantine_` prefix) rather than silently
    unlinked — this preserves forensic data if a transient ChartFox bug
    cached a disclaimer page that was actually usable for another purpose.
    Quarantined files are then ignored on subsequent reads.
    """
    global _chartfox_cache_reads, _chartfox_cache_hits
    _chartfox_cache_reads += 1
    current = _airac_cycle()
    for cycle in (current, current - 1):
        folder = _CHARTFOX_CACHE_DIR / f"cycle_{cycle}"
        if not folder.is_dir():
            continue
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for path in entries:
            try:
                name = path.name
            except OSError:
                continue
            if not path.is_file():
                continue
            if name.startswith(".quarantine_"):
                continue
            try:
                ext = path.suffix.lstrip(".").lower()
                if ext not in ("pdf", "png", "jpg"):
                    continue
                body = path.read_bytes()
                if not body:
                    continue
                sniff = body[:64].lstrip()
                if sniff.startswith(b"%PDF-"):
                    actual_ext, mt = "pdf", "application/pdf"
                elif sniff.startswith(b"\x89PNG\r\n\x1a\n"):
                    actual_ext, mt = "png", "image/png"
                elif sniff.startswith(b"\xff\xd8\xff"):
                    actual_ext, mt = "jpg", "image/jpeg"
                else:
                    _LOGGER.warning("[CHARTFOX CACHE] quarantining unknown cached chunk path=%s",
                                    name)
                    try:
                        path.rename(path.with_name(".quarantine_" + name))
                    except OSError:
                        pass
                    continue
                if ext != actual_ext:
                    _LOGGER.warning("[CHARTFOX CACHE] quarantining mime/extension mismatch path=%s "
                                    "detected=%s", name, actual_ext)
                    try:
                        path.rename(path.with_name(".quarantine_" + name))
                    except OSError:
                        pass
                    continue
                # Only return a chunk that matches the requested chart_id.
                if not name.startswith(chart_id + "."):
                    continue
                _chartfox_cache_hits += 1
                return body, mt, name
            except Exception:
                pass
    return None, None, None


def _chartfox_cache_put(chart_id: str, ext: str, body: bytes) -> None:
    """Save a fetched chart file to the cache atomically."""
    global _chartfox_cache_writes
    _chartfox_cache_writes += 1
    folder = _CHARTFOX_CACHE_DIR / f"cycle_{_airac_cycle()}"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{chart_id}.{ext}"
    tmp = folder / f".tmp_{chart_id}.{ext}"
    try:
        tmp.write_bytes(body)
        os.replace(str(tmp), str(dest))
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        _LOGGER.warning("[CHARTFOX CACHE] write failed for %s/%s", _airac_cycle(), chart_id)


def _chartfox_cache_prune() -> None:
    """Remove cache folders older than 3 cycles (84 days). Called once per AIRAC boundary."""
    current = _airac_cycle()
    try:
        if not _CHARTFOX_CACHE_DIR.is_dir():
            return
        for entry in sorted(_CHARTFOX_CACHE_DIR.iterdir()):
            if not entry.is_dir() or not entry.name.startswith("cycle_"):
                continue
            try:
                cycle_num = int(entry.name.split("_")[1])
            except (IndexError, ValueError):
                continue
            if cycle_num < current - 2:
                shutil.rmtree(entry, ignore_errors=True)
                _LOGGER.info("[CHARTFOX CACHE] pruned stale cycle %s", entry.name)
    except FileNotFoundError:
        pass


def chartfox_force_cache_cleanup() -> dict:
    """v0.25.58: delete ALL cached ChartFox temp files (chart PDFs, images, stale
    download artifacts from previous builds). Returns a summary dict."""
    try:
        if not _CHARTFOX_CACHE_DIR.is_dir():
            return {"ok": True, "deleted_bytes": 0, "deleted_files": 0, "cycles": 0}
        total_bytes = 0
        total_files = 0
        cycles = 0
        for entry in sorted(_CHARTFOX_CACHE_DIR.iterdir()):
            if not entry.is_dir() or not entry.name.startswith("cycle_"):
                continue
            cycles += 1
            for f in entry.iterdir():
                try:
                    total_bytes += f.stat().st_size
                    total_files += 1
                except OSError:
                    pass
            shutil.rmtree(entry, ignore_errors=True)
        _LOGGER.info("[CHARTFOX CACHE] force cleanup: removed %d files (%d bytes) across %d cycles",
                     total_files, total_bytes, cycles)
        return {"ok": True, "deleted_bytes": total_bytes, "deleted_files": total_files, "cycles": cycles}
    except Exception as exc:
        _LOGGER.warning("[CHARTFOX CACHE] force cleanup failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def chartfox_chart_file_proxy(chart_id: str, use_cache: bool = True) -> dict:
    """v0.25.17: fetch the best chart file for embedding through the local
    proxy, with corrected priority order based on ground-truth testing.

    Priority:
      1. chart.files[] (type 0 PDF > type 1 IMG) — ChartFox-hosted mirrors.
         Bearer auth required.
      2. chart.source_url with chart.source_url_type 0 (PDF) or 1 (IMG) —
         direct supplier file. Public URL, no auth needed.
      3. chart.allows_iframe + chart.view_url — ChartFox view page.
         NOTE: chartfox.org sends X-Frame-Options: SAMEORIGIN as of
         2026-07-25, so this path is almost always blocked by the
         browser. Kept as last-resort documented fallback.
      4. Genuinely unavailable.

    Returns on success (direct_file):
      {"ok": True, "render_mode": "direct_file", "body": bytes,
       "content_type": str, "filename": str, "cached": bool,
       "chart_name": str, "airport_icao": str, "copyright_short": str}

    Returns on iframe fallback:
      {"ok": True, "render_mode": "iframe", "redirect_url": str,
       "chart_name": str, "airport_icao": str, "copyright_short": str}

    Returns on failure:
      {"ok": False, "error": str, "error_code": str,
       "render_mode": "unavailable", ...}
    """
    cid = re.sub(r"[^A-Za-z0-9\-]", "", str(chart_id or "").strip())[:64]
    if not cid:
        return {"ok": False, "error": "ChartFox chart id is required.",
                "error_code": "invalid_request", "render_mode": "unavailable"}

    # Check cache first
    if use_cache:
        cached_body, cached_ct, cached_fn = _chartfox_cache_get(cid)
        if cached_body is not None:
            _LOGGER.info("[CHARTFOX PROXY] path=cache cid=%s ct=%s size=%d",
                         cid, cached_ct, len(cached_body))
            return {"ok": True, "render_mode": "direct_file",
                    "body": cached_body, "content_type": cached_ct,
                    "filename": cached_fn or f"{cid}.pdf", "cached": True,
                    "chart_name": "", "airport_icao": "", "copyright_short": ""}

    # Fetch chart detail from ChartFox API
    detail = _chartfox_chart_detail_cached(cid)
    if not detail.get("ok"):
        _LOGGER.warning("[CHARTFOX PROXY] path=api_failed cid=%s error=%s",
                        cid, detail.get("error", ""))
        return {"ok": False, "error": detail.get("error", "Chart detail fetch failed"),
                "error_code": "api_call_failed", "render_mode": "unavailable"}
    chart = detail.get("chart") or {}
    chart_name = chart.get("name") or ""
    airport_icao = chart.get("airport_icao") or ""
    source = chart.get("source") or {}
    copyright_short = str(source.get("copyright_short") or "").strip()
    all_files = chart.get("files") or []
    source_url = str(chart.get("source_url") or "").strip()
    raw_type = chart.get("source_url_type")
    try:
        source_url_type = int(raw_type) if raw_type is not None else None
    except (TypeError, ValueError):
        source_url_type = None
    allows_iframe = bool(chart.get("allows_iframe"))
    view_url = str(chart.get("view_url") or "").strip()

    # ------------------------------------------------------------------
    # Helper: download and cache a file from an arbitrary URL.
    # Returns the success dict or None on failure.
    # ------------------------------------------------------------------
    def _download_and_cache(url: str, is_pdf: bool) -> dict | None:
        token = _chartfox_load_token()
        access_token = token.get("access_token")
        headers = {}
        # Only send Bearer auth for chartfox.org URLs (files[] mirrors).
        # Supplier URLs like NATS AIP are public and don't need auth.
        if "chartfox.org" in url.lower() or "chartfox" in url.lower():
            if not access_token:
                _LOGGER.warning("[CHARTFOX PROXY] auth_missing for chartfox URL cid=%s", cid)
                return None
            headers["Authorization"] = f"Bearer {access_token}"
        try:
            resp = requests.get(url, headers=headers, timeout=30, stream=False)
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            _LOGGER.warning("[CHARTFOX PROXY] download_timeout cid=%s url=%s", cid, url[:80])
            return None
        except requests.RequestException as exc:
            _LOGGER.warning("[CHARTFOX PROXY] download_failed cid=%s url=%s error=%s",
                            cid, url[:80], exc)
            return None
        # v0.25.58 (round 2): the previous additive gate (reject if claimed
        # PDF but bytes weren't) is replaced with a sniff-and-set gate that
        # makes the BYTES the source of truth for ext/content_type. ChartFox
        # sometimes mis-types a JPEG as a PDF in files[].type, and we'd
        # otherwise cache the wrong extension with the wrong content-type.
        # Tolerance: small BOM/whitespace prefix that some ChartFox mirrors
        # prepend is allowed via lstrip() before the magic-byte check.
        sniff = resp.content[:64].lstrip()
        if sniff.startswith(b"%PDF-"):
            ext, ct = "pdf", "application/pdf"
        elif sniff.startswith(b"\x89PNG\r\n\x1a\n"):
            ext, ct = "png", "image/png"
        elif sniff.startswith(b"\xff\xd8\xff"):
            ext, ct = "jpg", "image/jpeg"
        else:
            _LOGGER.warning("[CHARTFOX PROXY] not_a_known_file cid=%s url=%s declared_ct=%s first32=%r",
                            cid, url[:80], resp.headers.get("content-type", ""), sniff[:32])
            return None
        fn = f"{chart_name or 'chart'}.{ext}"
        # Cache
        global _last_prune_cycle
        current_cycle = _airac_cycle()
        if _last_prune_cycle != current_cycle:
            _chartfox_cache_prune()
            _last_prune_cycle = current_cycle
        try:
            _chartfox_cache_put(cid, ext, resp.content)
        except Exception:
            _LOGGER.debug("[CHARTFOX CACHE] write failed for %s", cid)
        return {"body": resp.content, "content_type": ct, "filename": fn, "ext": ext}

    # --- Path 1: files[] — first-party ChartFox-hosted mirrors ---
    files_pdf_url = None
    files_img_url = None
    for f in all_files:
        if not isinstance(f, dict):
            continue
        ftype = f.get("type")
        furl = str(f.get("url") or "").strip()
        if not furl:
            continue
        if ftype == 0 and not files_pdf_url:
            files_pdf_url = furl
        elif ftype == 1 and not files_img_url:
            files_img_url = furl
    target_url = files_pdf_url or files_img_url
    if target_url:
        is_pdf = bool(files_pdf_url)
        dl = _download_and_cache(target_url, is_pdf)
        if dl:
            _LOGGER.info("[CHARTFOX PROXY] path=files_direct cid=%s type=%s ct=%s size=%d name=%s",
                         cid, dl["ext"], dl["content_type"], len(dl["body"]), chart_name)
            return {"ok": True, "render_mode": "direct_file",
                    "body": dl["body"], "content_type": dl["content_type"],
                    "filename": dl["filename"],
                    "chart_name": chart_name, "airport_icao": airport_icao,
                    "copyright_short": copyright_short, "cached": False}
        # files[] existed but download failed
        _LOGGER.warning("[CHARTFOX PROXY] path=files_download_failed cid=%s", cid)
        # Do NOT fall through to source_url — files[] was present but
        # the download failed, which is a different failure mode than
        # "no files available at all". Return the error.
        return {"ok": False, "error": "ChartFox file download failed.",
                "error_code": "file_fetch_failed", "render_mode": "unavailable"}
    if all_files:
        _LOGGER.warning("[CHARTFOX PROXY] path=files_no_usable_type cid=%s files=%d",
                        cid, len(all_files))

    # --- Path 2: source_url with type 0 (PDF) or 1 (IMG) ---
    # These are direct supplier URLs (e.g. NATS AIP PDFs) that are
    # publicly accessible and embeddable. No auth needed.
    if source_url and source_url_type in (0, 1):
        is_pdf = (source_url_type == 0)
        dl = _download_and_cache(source_url, is_pdf)
        if dl:
            _LOGGER.info("[CHARTFOX PROXY] path=source_url_direct cid=%s type=%s ct=%s size=%d name=%s source=%s",
                         cid, dl["ext"], dl["content_type"], len(dl["body"]),
                         chart_name, source_url[:80])
            return {"ok": True, "render_mode": "direct_file",
                    "body": dl["body"], "content_type": dl["content_type"],
                    "filename": dl["filename"],
                    "chart_name": chart_name, "airport_icao": airport_icao,
                    "copyright_short": copyright_short, "cached": False}
        _LOGGER.warning("[CHARTFOX PROXY] path=source_url_fetch_failed cid=%s type=%s url=%s",
                        cid, source_url_type, source_url[:80])

    # --- Path 3: chart.url — primary URL field (last-resort fallback) ---
    chart_url = str(chart.get("url") or "").strip()
    if chart_url:
        is_pdf_url = chart_url.lower().endswith('.pdf')
        dl = _download_and_cache(chart_url, is_pdf_url)
        if dl:
            _LOGGER.info("[CHARTFOX PROXY] path=url_fallback cid=%s ext=%s ct=%s size=%d name=%s url=%s",
                         cid, dl["ext"], dl["content_type"], len(dl["body"]),
                         chart_name, chart_url[:80])
            return {"ok": True, "render_mode": "direct_file",
                    "body": dl["body"], "content_type": dl["content_type"],
                    "filename": dl["filename"],
                    "chart_name": chart_name, "airport_icao": airport_icao,
                    "copyright_short": copyright_short, "cached": False}
        _LOGGER.warning("[CHARTFOX PROXY] path=url_fetch_failed cid=%s url=%s", cid, chart_url[:80])

    # --- Path 4: allows_iframe + view_url — ChartFox view page ---
    # NOTE: As of 2026-07-25, chartfox.org sends X-Frame-Options: SAMEORIGIN
    # on its viewer page, so this path is almost always blocked by the
    # browser. It is kept as a documented last-resort fallback.
    if allows_iframe and view_url:
        _LOGGER.info("[CHARTFOX PROXY] path=iframe_fallback cid=%s view_url=%s name=%s "
                     "(note: chartfox.org sends X-Frame-Options: SAMEORIGIN, "
                     "this will likely be blocked by the browser)",
                     cid, view_url, chart_name)
        return {"ok": True, "render_mode": "iframe", "redirect_url": view_url,
                "chart_name": chart_name, "airport_icao": airport_icao,
                "copyright_short": copyright_short}

    # --- Path 5: genuinely unavailable ---
    _LOGGER.warning("[CHARTFOX PROXY] path=unavailable cid=%s files=%d source_url=%s source_url_type=%s allows_iframe=%s view_url=%s name=%s",
                    cid, len(all_files),
                    source_url[:60] if source_url else "none",
                    source_url_type, allows_iframe, view_url, chart_name)
    return {"ok": False, "error": "No embeddable file URLs in chart detail response.",
            "error_code": "no_direct_file", "render_mode": "unavailable",
            "chart_name": chart_name, "airport_icao": airport_icao,
            "copyright_short": copyright_short, "allows_iframe": allows_iframe,
            "view_url": view_url, "source_url": source_url,
            "source_url_type": source_url_type}


def chartfox_chart_file_status(chart_id: str) -> dict:
    """v0.25.17: lightweight pre-check that determines the render mode for
    a chart WITHOUT downloading the file. Same priority as
    chartfox_chart_file_proxy(): files[] → source_url (type 0/1) →
    allows_iframe/view_url → unavailable.

    Returns:
      {"ok": True, "render_mode": "direct_file", "content_type": str,
       "chart_name": str, "airport_icao": str, "copyright_short": str,
       "source": str}
      {"ok": True, "render_mode": "iframe", "redirect_url": str,
       "chart_name": str, "airport_icao": str, "copyright_short": str}
      {"ok": True, "render_mode": "unavailable", "error": str,
       "error_code": str, ...}
    """
    cid = re.sub(r"[^A-Za-z0-9\-]", "", str(chart_id or "").strip())[:64]
    if not cid:
        return {"ok": True, "render_mode": "unavailable",
                "error": "ChartFox chart id is required.",
                "error_code": "invalid_request"}

    # Check if we have a cached file already
    cached_body, cached_ct, _ = _chartfox_cache_get(cid)
    if cached_body is not None:
        return {"ok": True, "render_mode": "direct_file",
                "content_type": cached_ct or "application/pdf",
                "chart_name": "", "airport_icao": "", "copyright_short": "",
                "source": "cache"}

    # Fetch chart detail
    detail = _chartfox_chart_detail_cached(cid)
    if not detail.get("ok"):
        return {"ok": True, "render_mode": "unavailable",
                "error": detail.get("error", "Chart detail fetch failed"),
                "error_code": "api_call_failed"}
    chart = detail.get("chart") or {}
    chart_name = chart.get("name") or ""
    airport_icao = chart.get("airport_icao") or ""
    source = chart.get("source") or {}
    copyright_short = str(source.get("copyright_short") or "").strip()
    files = chart.get("files") or []
    source_url = str(chart.get("source_url") or "").strip()
    raw_type = chart.get("source_url_type")
    try:
        source_url_type = int(raw_type) if raw_type is not None else None
    except (TypeError, ValueError):
        source_url_type = None
    allows_iframe = bool(chart.get("allows_iframe"))
    view_url = str(chart.get("view_url") or "").strip()

    # Path 1: files[] available → direct_file
    usable_files = []
    for f in files:
        if not isinstance(f, dict):
            continue
        ftype = f.get("type")
        furl = str(f.get("url") or "").strip()
        if furl and ftype is not None:
            usable_files.append((ftype, furl))
    if usable_files:
        has_pdf = any(ft == 0 for ft, _ in usable_files)
        ct = "application/pdf" if has_pdf else "image/png"
        return {"ok": True, "render_mode": "direct_file",
                "content_type": ct,
                "chart_name": chart_name, "airport_icao": airport_icao,
                "copyright_short": copyright_short, "source": "files"}

    # Path 2: source_url with type 0 (PDF) or 1 (IMG)
    if source_url and source_url_type in (0, 1):
        ct = "application/pdf" if source_url_type == 0 else "image/png"
        return {"ok": True, "render_mode": "direct_file",
                "content_type": ct,
                "chart_name": chart_name, "airport_icao": airport_icao,
                "copyright_short": copyright_short, "source": "source_url"}

    # Path 3: allows_iframe + view_url
    # NOTE: chartfox.org sends X-Frame-Options: SAMEORIGIN so this
    # is almost always blocked by the browser.
    if allows_iframe and view_url:
        return {"ok": True, "render_mode": "iframe",
                "redirect_url": view_url,
                "chart_name": chart_name, "airport_icao": airport_icao,
                "copyright_short": copyright_short}

    # Path 4: genuinely unavailable
    return {"ok": True, "render_mode": "unavailable",
            "error": "This chart has no embeddable file URLs.",
            "error_code": "no_direct_file",
            "chart_name": chart_name, "airport_icao": airport_icao,
            "copyright_short": copyright_short,
            "allows_iframe": allows_iframe,
            "view_url": view_url}


def openaip_key():
    s = _settings_integrations()
    user_key = str(s.get("openaip_api_key", "") or "").strip()
    return user_key or "f07fd970bc2dff1f61590e8fff85466f"
