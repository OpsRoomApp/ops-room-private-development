"""ADSBDB API client – v0.25.50.

Lightweight async client for the ADSBDB REST API with connection pooling,
timeouts, retry, and rate-limit awareness.

Official docs: https://www.adsbdb.com/
Repository:    https://github.com/mrjackwills/adsbdb
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

_log = logging.getLogger("opsroom.realworld.adsbdb")

BASE_URL = "https://api.adsbdb.com/v0"
DEFAULT_TIMEOUT = 4.0
MAX_RETRIES = 2
RETRY_BACKOFF = 0.5  # seconds, multiplicative

# Rolling-window rate limiter (conservative – 1 req / 200 ms)
_rate_lock = asyncio.Lock()
_last_request: float = 0.0
_MIN_INTERVAL: float = 0.22  # seconds between requests

# In-flight dedup: map<key, asyncio.Event>
_pending: dict[str, asyncio.Event] = {}
_pending_results: dict[str, Any] = {}


async def _rate_limit() -> None:
    global _last_request
    async with _rate_lock:
        now = time.monotonic()
        delay = _MIN_INTERVAL - (now - _last_request)
        if delay > 0:
            await asyncio.sleep(delay)
        _last_request = time.monotonic()


async def _get(
    endpoint: str,
    timeout: float = DEFAULT_TIMEOUT,
    dedup_key: str | None = None,
) -> dict[str, Any] | None:
    """Internal GET with dedup, rate limiting, retry, and error handling.

    Returns the JSON response dict or None on any failure.
    Cancellation-safe: always signals waiting tasks and cleans up, even on
    asyncio.CancelledError (Python 3.9+).
    """
    # Dedup in-flight requests
    if dedup_key:
        if dedup_key in _pending:
            try:
                await _pending[dedup_key].wait()
            except asyncio.CancelledError:
                # We were cancelled while waiting — let the initiator finish
                return None
            return _pending_results.get(dedup_key)
        evt = asyncio.Event()
        _pending[dedup_key] = evt

    result: dict[str, Any] | None = None
    try:
        url = f"{BASE_URL}{endpoint}"
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                await _rate_limit()
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.get(url, headers={"Accept": "application/json"})
                    if resp.status_code == 404:
                        result = None
                        break
                    if resp.status_code == 429:
                        _log.warning("[ADSBDB] Rate limited (429) — backing off")
                        await asyncio.sleep(2.0 * (attempt + 1))
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    if isinstance(data, dict):
                        # ADSBDB wraps all responses in a "response" key — unwrap it
                        result = data.get("response", data)
                        if not isinstance(result, dict):
                            result = data
                    else:
                        result = None
                    break
            except (httpx.TimeoutException, httpx.HTTPError, json.JSONDecodeError) as exc:
                last_exc = exc
                _log.debug("[ADSBDB] Request attempt %d failed: %s", attempt + 1, exc)
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_BACKOFF * (2 ** attempt))
            except Exception as exc:
                last_exc = exc
                _log.debug("[ADSBDB] Unexpected error: %s", exc)
                break
        else:
            _log.warning("[ADSBDB] All retries exhausted for %s: %s", endpoint, last_exc)
            result = None
    finally:
        # CRITICAL: always signal and clean up, even on CancelledError
        if dedup_key:
            _pending_results[dedup_key] = result
            _pending[dedup_key].set()
            # Schedule cleanup
            try:
                loop = asyncio.get_running_loop()
                loop.call_later(10, lambda: _pending.pop(dedup_key, None))
                loop.call_later(10, lambda: _pending_results.pop(dedup_key, None))
            except RuntimeError:
                _pending.pop(dedup_key, None)
                _pending_results.pop(dedup_key, None)
    return result


# ── Public API ──────────────────────────────────────────────────────────────

async def get_aircraft(identifier: str) -> dict[str, Any] | None:
    """Look up aircraft by Mode-S hex or registration."""
    ident = identifier.strip().upper()
    if not ident:
        return None
    return await _get(f"/aircraft/{ident}", dedup_key=f"ac:{ident}")


async def get_callsign(callsign: str) -> dict[str, Any] | None:
    """Look up callsign route / airline information."""
    cs = callsign.strip().upper()
    if not cs:
        return None
    return await _get(f"/callsign/{cs}", dedup_key=f"cs:{cs}")


async def get_aircraft_with_callsign(mode_s: str, callsign: str) -> dict[str, Any] | None:
    """Combined aircraft + callsign enrichment lookup."""
    ms = mode_s.strip().upper()
    cs = callsign.strip().upper()
    if not ms:
        return None
    endpoint = f"/aircraft/{ms}"
    if cs:
        endpoint += f"?callsign={cs}"
    return await _get(endpoint, dedup_key=f"ac_cs:{ms}:{cs}")


async def get_airline(identifier: str) -> dict[str, Any] | None:
    """Look up airline by ICAO or IATA code."""
    ident = identifier.strip().upper()
    if not ident:
        return None
    return await _get(f"/airline/{ident}", dedup_key=f"al:{ident}")


async def health_check() -> bool:
    """Quick check whether ADSBDB is reachable."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{BASE_URL}/online")
            return resp.status_code == 200
    except Exception:
        return False
