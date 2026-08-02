"""ADSBDB API client – v0.25.58.

Lightweight async client for the ADSBDB REST API with a shared pooled
connection, timeouts, retry, rate-limit awareness, and a global 429
circuit breaker so a rate-limited API can never stall the pipeline.

Official docs: https://www.adsbdb.com/
Repository:    https://github.com/mrjackwills/adsbdb
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

import httpx

_log = logging.getLogger("opsroom.realworld.adsbdb")

BASE_URL = "https://api.adsbdb.com/v0"
DEFAULT_TIMEOUT = 4.0
MAX_RETRIES = 2
RETRY_BACKOFF = 0.5  # seconds, multiplicative

# Rolling-window rate limiter (conservative – 1 req / 500 ms).
# Tunable via ADSBDB_MIN_INTERVAL_SECONDS for stricter provider limits.
_rate_lock = asyncio.Lock()
_last_request: float = 0.0
_MIN_INTERVAL: float = float(os.environ.get("ADSBDB_MIN_INTERVAL_SECONDS", "0.5"))

# Global 429 circuit breaker: after a 429, refuse ALL requests until cooldown.
_RATE_LIMIT_COOLDOWN = float(os.environ.get("ADSBDB_RATE_LIMIT_COOLDOWN_SECONDS", "30"))
_rate_limit_until: float = 0.0

# Max concurrent in-flight ADSBDB requests.
MAX_CONCURRENT = int(os.environ.get("ADSBDB_MAX_CONCURRENT", "5"))
_semaphore = asyncio.Semaphore(MAX_CONCURRENT)

# Shared pooled client (created lazily on first use, reused for all requests).
_client: httpx.AsyncClient | None = None
_client_lock = asyncio.Lock()

# In-flight dedup: map<key, asyncio.Event>
_pending: dict[str, asyncio.Event] = {}
_pending_results: dict[str, Any] = {}


def is_rate_limited() -> bool:
    """True when the global 429 circuit breaker is active.

    Enrichment callers use this to skip network lookups entirely and fall
    back to cache-only behaviour while ADSBDB cools down.
    """
    return time.monotonic() < _rate_limit_until


async def _get_shared_client() -> httpx.AsyncClient:
    """Return the shared pooled client, creating it on first use."""
    global _client
    if _client is not None and not _client.is_closed:
        return _client
    async with _client_lock:
        if _client is None or _client.is_closed:
            _client = httpx.AsyncClient(
                timeout=DEFAULT_TIMEOUT,
                limits=httpx.Limits(
                    max_connections=MAX_CONCURRENT,
                    max_keepalive_connections=MAX_CONCURRENT,
                ),
                headers={"Accept": "application/json"},
                follow_redirects=True,
            )
    return _client


async def _rate_limit() -> None:
    """Serialise requests to respect the provider's rolling window."""
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

    Cancellation-safe: the dedup entry is registered inside the try block so
    ``finally`` always signals waiting tasks and cleans up, even on
    asyncio.CancelledError (Python 3.9+).  This prevents a cancelled request
    from leaving a never-set event that future waiters hang on forever.
    """
    # Global 429 circuit breaker: fail fast while the API is cooling down.
    if is_rate_limited():
        return None

    result: dict[str, Any] | None = None
    registered = False
    try:
        # Dedup registration lives inside try so cleanup is guaranteed.
        if dedup_key:
            if dedup_key in _pending:
                try:
                    await _pending[dedup_key].wait()
                except asyncio.CancelledError:
                    # We were cancelled while waiting — let the initiator finish.
                    return None
                return _pending_results.get(dedup_key)
            _pending[dedup_key] = asyncio.Event()
            registered = True

        url = f"{BASE_URL}{endpoint}"
        client = await _get_shared_client()
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                await _rate_limit()
                async with _semaphore:
                    resp = await client.get(url, timeout=timeout)
                if resp.status_code == 404:
                    result = None
                    break
                if resp.status_code == 429:
                    global _rate_limit_until
                    _rate_limit_until = time.monotonic() + _RATE_LIMIT_COOLDOWN
                    _log.warning(
                        "[ADSBDB] Rate limited (429) — circuit breaker engaged for %.0fs",
                        _RATE_LIMIT_COOLDOWN,
                    )
                    result = None
                    break
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
        # CRITICAL: always signal and clean up, even on CancelledError.
        if dedup_key and registered:
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
    if is_rate_limited():
        return False
    try:
        client = await _get_shared_client()
        async with _semaphore:
            resp = await client.get(f"{BASE_URL}/online", timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False
