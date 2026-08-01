"""Real-World Flight Search pipeline – v0.25.55.

Provider-agnostic discovery, normalisation, ADSBDB enrichment, caching,
search indexing, and diagnostics for the OPS ROOM Real World Schedules feature.

All external providers (FR24, ADSB.lol/fi, OpenSky) are abstracted behind
a single pipeline that degrades gracefully when any provider fails.
ADSBDB is used for enrichment only — never as a hard dependency.
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import math
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from .adsbdb_client import get_aircraft, get_callsign, get_aircraft_with_callsign, health_check
from .flight_cache import (
    TTL_LIVE,
    all_stats as cache_all_stats,
    get_live_flights,
    get_route as cache_get_route,
    get_aircraft_meta as cache_get_aircraft,
    set_live_flights,
    set_route as cache_set_route,
    set_aircraft_meta as cache_set_aircraft,
)
from .flight_model import (
    DEDUP_PREFER_FIRST,
    FLIGHT_FIELDS,
    _parse_bool,
    apply_adsbdb_aircraft,
    apply_adsbdb_route,
    classify_aircraft,
    compute_dispatch_eligibility,
    compute_ranking,
    compute_simbrief,
    dedup_identity,
    merge_flights,
    normalise_adsb,
    normalise_fr24,
)
from .flight_search import build_search_index, index_count, is_index_ready, search_index

_log = logging.getLogger("opsroom.realworld")

router = APIRouter(prefix="/api/v1/realworld", tags=["realworld"])

# ── Built-in seed airport coordinates (fallback when airports.csv is missing) ──
_SEED_AIRPORTS: dict[str, tuple[float, float]] = {
    "EDDF": (50.0333, 8.5706),
    "EGLL": (51.4775, -0.4614),
    "EHAM": (52.3081, 4.7642),
    "LFPG": (49.0097, 2.5479),
    "KJFK": (40.6413, -73.7781),
    "KLAX": (33.9425, -118.4081),
    "OMDB": (25.2532, 55.3657),
    "VHHH": (22.3080, 113.9185),
}

# ── Zone sweep bounds (bounded regional fallback) ──
_ZONE_SWEEP: list[dict[str, Any]] = [
    {"lat": 50.0, "lon": 8.5, "dist": 200, "label": "Central Europe"},
    {"lat": 40.7, "lon": -74.0, "dist": 180, "label": "US Northeast"},
]

# ── Pipeline stats (populated by _refresh_loop) ──
_pipeline_stats: dict[str, Any] = {
    "discovered": 0,
    "normalized": 0,
    "normalization_failed": 0,
    "classified": 0,
    "classification": {},
    "before_dedup": 0,
    "after_dedup": 0,
    "dedup_removed": 0,
    "enrichment_attempted": 0,
    "enrichment_successful": 0,
    "enrichment_failed": 0,
    "enrichment_missing_dest_before": 0,
    "enrichment_recovered_dest": 0,
    "enrichment_missing_origin_before": 0,
    "enrichment_recovered_origin": 0,
    "enrichment_missing_aircraft_before": 0,
    "enrichment_recovered_aircraft": 0,
    "final_available": 0,
    "discovery_strategy": "none",
    "last_refresh_utc": None,
    "last_refresh_status": "never",
}
_stats_lock = threading.Lock()

# Provider health
_provider_health: dict[str, Any] = {
    "fr24": {"request_count": 0, "success_count": 0, "failure_count": 0,
             "last_status_code": None, "last_latency_ms": None,
             "last_success_utc": None, "last_failure_utc": None, "last_error_type": None},
    "adsbdb": {"request_count": 0, "success_count": 0, "failure_count": 0,
               "last_latency_ms": None,
               "last_success_utc": None, "last_failure_utc": None, "last_error_type": None},
}

# Recent errors (bounded ring)
_recent_errors: list[dict[str, Any]] = []
_MAX_ERRORS = 40

# In-progress refresh lock
_refresh_lock = asyncio.Lock()
_refresh_running = False

# ── Helpers ─────────────────────────────────────────────────────────────────

def _clean_str(val: str | None) -> str:
    return str(val or "").strip().upper()


def _is_valid_icao(code: str | None) -> bool:
    c = _clean_str(code)
    return len(c) == 4 and c.isalpha()


def _record_error(stage: str, provider: str, error_type: str, message: str) -> None:
    global _recent_errors
    with _stats_lock:
        _recent_errors.append({
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "provider": provider,
            "error_type": error_type,
            "message": str(message)[:200],
        })
        if len(_recent_errors) > _MAX_ERRORS:
            _recent_errors = _recent_errors[-_MAX_ERRORS:]


def _update_provider_health(provider: str, success: bool, latency_ms: float | None = None,
                            status_code: int | None = None, error_type: str | None = None) -> None:
    ph = _provider_health.get(provider)
    if not ph:
        return
    ph["request_count"] = ph.get("request_count", 0) + 1
    if success:
        ph["success_count"] = ph.get("success_count", 0) + 1
        ph["last_success_utc"] = datetime.now(timezone.utc).isoformat()
        if status_code is not None:
            ph["last_status_code"] = status_code
    else:
        ph["failure_count"] = ph.get("failure_count", 0) + 1
        ph["last_failure_utc"] = datetime.now(timezone.utc).isoformat()
        if error_type:
            ph["last_error_type"] = error_type
    if latency_ms is not None:
        ph["last_latency_ms"] = round(latency_ms, 1)


# ── Airport coordinate resolution ───────────────────────────────────────────

_AIRPORT_INDEX: dict[str, tuple[float, float]] = {}


def _load_airports_csv() -> None:
    """Load airports.csv into _AIRPORT_INDEX (lat/lon keyed by ICAO)."""
    global _AIRPORT_INDEX
    if _AIRPORT_INDEX:
        return
    candidates = [
        Path(__file__).resolve().parent / "data" / "airports.csv",
        Path(os.getcwd()) / "app" / "data" / "airports.csv",
    ]
    for csv_path in candidates:
        try:
            if not csv_path.exists():
                continue
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    icao = str(row.get("icao") or row.get("ICAO") or "").strip().upper()
                    lat = row.get("latitude") or row.get("lat") or ""
                    lon = row.get("longitude") or row.get("lon") or ""
                    try:
                        _AIRPORT_INDEX[icao] = (float(lat), float(lon))
                    except (ValueError, TypeError):
                        continue
            _log.info("[RealWorld] Loaded %d airports from %s", len(_AIRPORT_INDEX), csv_path)
            return
        except Exception as exc:
            _log.warning("[RealWorld] Failed to load airports.csv from %s: %s", csv_path, exc)
    _log.info("[RealWorld] No airports.csv found — using built-in seeds only")


def _resolve_coords(icao: str) -> tuple[float, float] | None:
    """Resolve airport coordinates with fallback hierarchy:
    1. airports.csv index
    2. Built-in seed coordinates
    3. None (triggers zone sweep in discovery)
    """
    _load_airports_csv()
    icao_clean = _clean_str(icao)
    if icao_clean and _AIRPORT_INDEX:
        coords = _AIRPORT_INDEX.get(icao_clean)
        if coords:
            return coords
    seed = _SEED_AIRPORTS.get(icao_clean)
    if seed:
        _log.info("[RealWorld] Using built-in seed coords for %s", icao_clean)
        return seed
    return None


# ── FR24 discovery ──────────────────────────────────────────────────────────

def _build_fr24_bounds(origin_clean: str, dest_clean: str) -> list[dict[str, Any]]:
    """Build bounding-box candidates for FR24 discovery."""
    bounds_list: list[dict[str, Any]] = []
    for icao in (origin_clean, dest_clean):
        if not _is_valid_icao(icao):
            continue
        coords = _resolve_coords(icao)
        if coords:
            bounds_list.append({"lat": coords[0], "lon": coords[1], "dist": 150, "source": icao})
    return bounds_list


async def _discover_fr24(
    origin_clean: str = "",
    dest_clean: str = "",
    callsign: str = "",
) -> list[dict[str, Any]]:
    """Discover flights via FR24 bounding-box search, with fallback to
    ADSB.lol and zone sweep.

    FR24 returns lists (16-element arrays); this function normalises them
    to dicts compatible with normalise_fr24().
    """
    raw: list[dict[str, Any]] = []
    discovery_strategy = "none"
    _log.info("[RealWorld] FR24 DISCOVERY START")

    # FR24 list-index mapping — keys match what normalise_fr24() expects
    _FR24_IDX = {0: "hex", 1: "lat", 2: "lon", 3: "heading", 4: "altitude",
                 5: "speed", 6: "squawk", 7: "radar", 8: "type", 9: "reg",
                 10: "timestamp", 11: "orig", 12: "dest", 13: "flight",
                 14: "vrate", 15: "track"}

    bounds_list = _build_fr24_bounds(origin_clean, dest_clean)
    if bounds_list:
        discovery_strategy = "airports_csv"
        for bounds in bounds_list:
            try:
                t0 = time.monotonic()
                async with httpx.AsyncClient(timeout=6.0) as client:
                    resp = await client.get(
                        "https://data-live.flightradar24.com/zones/fcgi/feed.js",
                        params={"bounds": f"{bounds['lat']-1.5},{bounds['lat']+1.5},"
                                          f"{bounds['lon']-1.5},{bounds['lon']+1.5}"},
                        headers={"Accept": "application/json",
                                 "User-Agent": "OPS-ROOM/0.25.55"},
                    )
                    _update_provider_health("fr24", resp.status_code == 200,
                                            (time.monotonic() - t0) * 1000,
                                            resp.status_code)
                    if resp.status_code == 200:
                        data = resp.json()
                        if isinstance(data, dict):
                            for _k, v in data.items():
                                if isinstance(v, list) and len(v) >= 10:
                                    # Convert FR24 list to dict for normalise_fr24
                                    flight_dict: dict[str, Any] = {}
                                    for idx, key in _FR24_IDX.items():
                                        if idx < len(v):
                                            flight_dict[key] = v[idx]
                                    raw.append(flight_dict)
            except Exception as exc:
                _update_provider_health("fr24", False, error_type=type(exc).__name__)
                _record_error("discovery", "fr24", type(exc).__name__, str(exc))

    # Fallback: zone sweep (if no bounds or FR24 returned nothing)
    if not raw:
        discovery_strategy = "regional_fallback"
        _log.info("[RealWorld] FR24 discovery: zone sweep fallback (%d zones)", len(_ZONE_SWEEP))
        for zone in _ZONE_SWEEP:
            try:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    resp = await client.get(
                        "https://data-live.flightradar24.com/zones/fcgi/feed.js",
                        params={"bounds": f"{zone['lat']-1.5},{zone['lat']+1.5},"
                                          f"{zone['lon']-1.5},{zone['lon']+1.5}"},
                        headers={"Accept": "application/json",
                                 "User-Agent": "OPS-ROOM/0.25.55"},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if isinstance(data, dict):
                            for _k, v in data.items():
                                if isinstance(v, list) and len(v) >= 10:
                                    flight_dict = {}
                                    for idx, key in _FR24_IDX.items():
                                        if idx < len(v):
                                            flight_dict[key] = v[idx]
                                    raw.append(flight_dict)
                await asyncio.sleep(0.2)
            except Exception:
                continue

    # Final fallback: ADSB.lol
    if not raw:
        discovery_strategy = "adsb_fallback"
        _log.info("[RealWorld] Discovery: ADSB.lol fallback")
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.get("https://api.adsb.lol/v2/point/50.0/8.5/200",
                                        headers={"Accept": "application/json"})
                if resp.status_code == 200:
                    data = resp.json()
                    ac_list = data.get("aircraft") or data.get("ac") or []
                    if isinstance(ac_list, list):
                        raw = ac_list
        except Exception as exc:
            _record_error("discovery", "adsb_lol", type(exc).__name__, str(exc))

    # Set discovery strategy in stats
    with _stats_lock:
        _pipeline_stats["discovery_strategy"] = discovery_strategy

    _log.info("[RealWorld] FR24 DISCOVERY COMPLETE flights=%d strategy=%s",
              len(raw), discovery_strategy)
    return raw


# ── Enrichment ──────────────────────────────────────────────────────────────

async def _enrich_batch(flights: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Best-effort ADSBDB enrichment for a batch of flights.  Enrichment
    failures never remove the original FR24 record."""
    attempted = 0
    succeeded = 0
    failed = 0
    missing_dest_before = 0
    recovered_dest = 0
    missing_origin_before = 0
    recovered_origin = 0
    missing_aircraft_before = 0
    recovered_aircraft = 0

    route_ok = 0
    aircraft_ok = 0
    identity_ok = 0

    async def _enrich_one(flight: dict[str, Any]) -> dict[str, Any]:
        nonlocal attempted, succeeded, failed
        nonlocal missing_dest_before, recovered_dest
        nonlocal missing_origin_before, recovered_origin
        nonlocal missing_aircraft_before, recovered_aircraft
        nonlocal route_ok, aircraft_ok, identity_ok

        # Count missing fields before enrichment (save state for accurate recovery)
        had_dest_before = bool(flight.get("destination_icao"))
        had_origin_before = bool(flight.get("origin_icao"))
        had_aircraft_before = bool(flight.get("aircraft_type"))
        if not had_dest_before:
            missing_dest_before += 1
        if not had_origin_before:
            missing_origin_before += 1
        if not had_aircraft_before:
            missing_aircraft_before += 1

        cs = _clean_str(flight.get("callsign") or "")
        mode_s = _clean_str(flight.get("mode_s") or "")

        # Track enrichment result per flight (v0.25.55)
        enrichment_attempted = True
        route_lookup = False
        route_success = False
        aircraft_lookup = False
        aircraft_success = False

        # Try variants: exact + leading-zero variants
        cs_variants = [cs]
        if cs and cs[-1].isdigit():
            digits = re.search(r"(\d+)$", cs)
            if digits:
                num = digits.group(1)
                cs_variants.append(cs[: -len(num)] + num.lstrip("0"))
                if len(num) <= 3:
                    cs_variants.append(cs[: -len(num)] + num.zfill(4))

        # ── Aircraft metadata ──
        ac_key = mode_s or (flight.get("registration") or "").strip().upper()
        if ac_key:
            cached_ac = cache_get_aircraft(ac_key)
            if cached_ac:
                apply_adsbdb_aircraft(flight, cached_ac)
                aircraft_lookup = True
                aircraft_success = True
            else:
                aircraft_lookup = True
                attempted += 1
                try:
                    ac_data = await get_aircraft(ac_key)
                    if ac_data:
                        cache_set_aircraft(ac_key, ac_data)
                        apply_adsbdb_aircraft(flight, ac_data)
                        aircraft_success = True
                        aircraft_ok += 1
                        succeeded += 1
                        _log.info("[RealWorld] AIRCRAFT ENRICH cs=%%s hex=%%s key=%%s type=%%s reg=%%s",
                                  cs, mode_s, ac_key,
                                  flight.get("aircraft_type"), flight.get("registration"))
                    _update_provider_health("adsbdb", True)
                except Exception as exc:
                    failed += 1
                    _update_provider_health("adsbdb", False, error_type=type(exc).__name__)

        # ── Route data ──
        route_data = None
        for variant in cs_variants:
            if not variant:
                continue
            route_lookup = True
            cached_route = cache_get_route(variant)
            if cached_route:
                route_data = cached_route
                route_success = True
                break
            try:
                attempted += 1
                route_data = await get_callsign(variant)
                if route_data:
                    cache_set_route(variant, route_data)
                    route_success = True
                    route_ok += 1
                    succeeded += 1
                    break
                _update_provider_health("adsbdb", True)
            except Exception as exc:
                failed += 1
                _update_provider_health("adsbdb", False, error_type=type(exc).__name__)

        if route_data:
            apply_adsbdb_route(flight, route_data)

        # Count field recovery after enrichment (only count actual recovery)
        if route_data:
            if not had_dest_before and flight.get("destination_icao"):
                recovered_dest += 1
            if not had_origin_before and flight.get("origin_icao"):
                recovered_origin += 1
        if not had_aircraft_before and flight.get("aircraft_type"):
            recovered_aircraft += 1

        # ── Attach per-flight enrichment audit flags (v0.25.55) ──
        flight["enrichment_attempted"] = enrichment_attempted
        flight["enrichment_success"] = route_success or aircraft_success
        flight["route_enriched"] = route_success
        flight["aircraft_enriched"] = aircraft_success
        if route_success and aircraft_success:
            identity_ok += 1

        # Structured log per lookup
        if route_lookup or aircraft_lookup:
            _log.debug(
                "[RealWorld] enrichment cs=%s route=%s/%s ac=%s/%s",
                cs, route_lookup, route_success, aircraft_lookup, aircraft_success)

        if not flight.get("category") or flight.get("category") == "UNKNOWN":
            flight["category"] = classify_aircraft(
                flight.get("aircraft_type"), flight.get("callsign"))

        flight["rank_score"] = compute_ranking(flight)
        compute_dispatch_eligibility(flight)
        compute_simbrief(flight)
        return flight

    tasks = [_enrich_one(f) for f in flights]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    enriched: list[dict[str, Any]] = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            _log.debug("[RealWorld] Enrichment exception for flight %d: %s", i, r)
            enriched.append(flights[i])
        else:
            enriched.append(r)

    with _stats_lock:
        _pipeline_stats["enrichment_attempted"] = (
            _pipeline_stats.get("enrichment_attempted", 0) + attempted)
        _pipeline_stats["enrichment_successful"] = (
            _pipeline_stats.get("enrichment_successful", 0) + succeeded)
        _pipeline_stats["enrichment_failed"] = (
            _pipeline_stats.get("enrichment_failed", 0) + failed)
        _pipeline_stats["enrichment_missing_dest_before"] = (
            _pipeline_stats.get("enrichment_missing_dest_before", 0) + missing_dest_before)
        _pipeline_stats["enrichment_recovered_dest"] = (
            _pipeline_stats.get("enrichment_recovered_dest", 0) + recovered_dest)
        _pipeline_stats["enrichment_missing_origin_before"] = (
            _pipeline_stats.get("enrichment_missing_origin_before", 0) + missing_origin_before)
        _pipeline_stats["enrichment_recovered_origin"] = (
            _pipeline_stats.get("enrichment_recovered_origin", 0) + recovered_origin)
        _pipeline_stats["enrichment_missing_aircraft_before"] = (
            _pipeline_stats.get("enrichment_missing_aircraft_before", 0) + missing_aircraft_before)
        _pipeline_stats["enrichment_recovered_aircraft"] = (
            _pipeline_stats.get("enrichment_recovered_aircraft", 0) + recovered_aircraft)

    _log.info("[RealWorld] Enrichment: %d attempted, %d succeeded, %d failed | "
              "dest: %d missing → %d recovered, origin: %d missing → %d recovered, "
              "aircraft: %d missing → %d recovered",
              attempted, succeeded, failed,
              missing_dest_before, recovered_dest,
              missing_origin_before, recovered_origin,
              missing_aircraft_before, recovered_aircraft)
    return enriched


# ── Deduplication ───────────────────────────────────────────────────────────

def _dedup(flights: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for f in flights:
        key = dedup_identity(f)
        if key in seen:
            seen[key] = merge_flights(f, seen[key])
        else:
            seen[key] = dict(f)
    return list(seen.values())


# ── Filtering ───────────────────────────────────────────────────────────────

def _filter_flights(
    flights: list[dict[str, Any]],
    include_ga: bool = False,
    include_gliders: bool = False,
) -> list[dict[str, Any]]:
    """Filter flight list by category.  UNKNOWN, AIRLINE, BUSINESS, CARGO,
    MILITARY are always visible.  GA and GLIDER are opt-in via checkboxes."""
    def _visible(f: dict[str, Any]) -> bool:
        cat = f.get("category") or "UNKNOWN"
        if cat in ("GENERAL_AVIATION",):
            return include_ga
        if cat in ("GLIDER",):
            return include_gliders
        return True  # AIRLINE, BUSINESS, CARGO, MILITARY, UNKNOWN always visible
    return [f for f in flights if _visible(f)]


# ── Refresh loop ────────────────────────────────────────────────────────────

async def _refresh_loop() -> None:
    """Full refresh cycle: discover → normalise → enrich → dedup → filter → cache → index.

    v0.25.55: all stages instrumented with wall-clock timing.
    """
    global _refresh_running
    async with _refresh_lock:
        t_start = time.monotonic()
        _log.info("[RealWorld] Refresh started")
        attempt_utc = datetime.now(timezone.utc).isoformat()
        _refresh_running = True
        timings: dict[str, float] = {}
        try:
            # ── Discovery ──
            t0 = time.monotonic()
            raw: list[dict[str, Any]] = []
            try:
                raw = await _discover_fr24()
            except Exception as exc:
                _log.error("[RealWorld] Discovery failed: %s", exc)
                _record_error("discovery", "fr24", type(exc).__name__, str(exc))
                raw = []
            timings["discovery_ms"] = round((time.monotonic() - t0) * 1000, 1)

            # ── Normalisation (per-record fault isolation) ──
            t0 = time.monotonic()
            normalized: list[dict[str, Any]] = []
            norm_failed = 0
            for item in raw:
                if not item:
                    continue
                try:
                    f = normalise_fr24(item)
                    if f:
                        normalized.append(f)
                    else:
                        norm_failed += 1
                except Exception:
                    norm_failed += 1
            timings["normalise_ms"] = round((time.monotonic() - t0) * 1000, 1)

            # Category counts
            cat_counts: dict[str, int] = {}
            for f in normalized:
                cat = f.get("category") or "UNKNOWN"
                cat_counts[cat] = cat_counts.get(cat, 0) + 1

            # ── Enrichment ──
            t0 = time.monotonic()
            before_dedup = len(normalized)
            enriched = await _enrich_batch(normalized)
            timings["enrich_ms"] = round((time.monotonic() - t0) * 1000, 1)

            # ── Dedup ──
            t0 = time.monotonic()
            deduped = _dedup(enriched)
            after_dedup = len(deduped)
            timings["dedup_ms"] = round((time.monotonic() - t0) * 1000, 1)

            # ── Filter (default: no GA/glider) ──
            t0 = time.monotonic()
            filter_before = len(deduped)
            filtered = _filter_flights(deduped, include_ga=False, include_gliders=False)
            filter_after = len(filtered)

            # Sort by rank
            filtered.sort(key=lambda f: -(f.get("rank_score") or 0))

            # ── Cache + index ──
            t0 = time.monotonic()
            set_live_flights(filtered)
            build_search_index(filtered)
            timings["cache_index_ms"] = round((time.monotonic() - t0) * 1000, 1)

            # ── Update stats ──
            timings["total_ms"] = round((time.monotonic() - t_start) * 1000, 1)
            with _stats_lock:
                _pipeline_stats.update({
                    "discovered": len(raw),
                    "normalized": len(normalized),
                    "normalization_failed": norm_failed,
                    "classified": len(normalized),
                    "classification": cat_counts,
                    "before_dedup": before_dedup,
                    "after_dedup": after_dedup,
                    "dedup_removed": before_dedup - after_dedup,
                    "filter_before": filter_before,
                    "filter_after": filter_after,
                    "final_available": len(filtered),
                    "last_refresh_utc": datetime.now(timezone.utc).isoformat(),
                    "last_refresh_attempt_utc": attempt_utc,
                    "last_refresh_status": "success",
                    "last_refresh_timings_ms": timings,
                })

            _log.info("[RealWorld] Refresh completed: %d discovered → %d normalised → %d final | timings(ms)=%s",
                      len(raw), len(normalized), len(filtered), timings)
        finally:
            _refresh_running = False


# ── Background refresh scheduler ────────────────────────────────────────────

_refresh_task: asyncio.Task | None = None


async def _background_refresh() -> None:
    """Periodic background refresh loop."""
    while True:
        await _refresh_loop()
        await asyncio.sleep(TTL_LIVE - 10)  # Refresh slightly before cache TTL expires


def start_background_refresh() -> None:
    global _refresh_task
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            _refresh_task = asyncio.ensure_future(_background_refresh())
            _log.info("[RealWorld] Background refresh started")
    except RuntimeError:
        _log.info("[RealWorld] No event loop — background refresh not started")


# Initial warm-up on first import
_load_airports_csv()


# ── Routes ──────────────────────────────────────────────────────────────────

@router.get("/search")
async def realworld_search(
    origin: str | None = None,
    destination: str | None = None,
    callsign: str | None = None,
    aircraft: str | None = None,
    include_ga: str | None = None,
    include_gliders: str | None = None,
):
    """Search real-world flights from the live cache.

    Query params:
      origin, destination (ICAO), callsign, aircraft (ICAO type),
      include_ga, include_gliders (boolean strings)
    """
    origin_clean = _clean_str(origin)
    dest_clean = _clean_str(destination)
    callsign_clean = _clean_str(callsign)
    aircraft_clean = _clean_str(aircraft)
    include_ga_bool = _parse_bool(include_ga)
    include_gliders_bool = _parse_bool(include_gliders)

    try:
        t0 = time.monotonic()
        flights, cache_age, is_stale = get_live_flights()

        _log.info(
            "[RealWorld] SEARCH REQUEST origin=%s dest=%s cs=%s ac=%s ga=%s gl=%s | cache=%d age=%.1fs stale=%s",
            origin_clean or "-", dest_clean or "-", callsign_clean or "-",
            aircraft_clean or "-", include_ga_bool, include_gliders_bool,
            len(flights), cache_age, is_stale)

        # v0.25.55: cold-start bootstrap — call _refresh_loop() directly;
        # it manages its own lock and _refresh_running flag internally.
        if not flights:
            _log.info("[RealWorld] Cold start - awaiting first refresh (max 30s)")
            try:
                await asyncio.wait_for(_refresh_loop(), timeout=30.0)
            except asyncio.TimeoutError:
                _log.warning("[RealWorld] First refresh timed out")
            except Exception as exc:
                _log.error("[RealWorld] First refresh failed: %s", exc, exc_info=True)
            flights, cache_age, is_stale = get_live_flights()

        # v0.25.55: stale cache - fire-and-forget with error callback
        elif is_stale:
            if not _refresh_lock.locked():
                _log.info("[RealWorld] Stale cache (age=%.1fs) - triggering background refresh", cache_age)
                task = asyncio.create_task(_refresh_loop())
                def _on_refresh_done(t):
                    try:
                        t.result()
                    except Exception as exc:
                        _log.error("[RealWorld] Background refresh crashed: %s", exc, exc_info=True)
                task.add_done_callback(_on_refresh_done)
                asyncio.create_task(_refresh_loop())

        # Filter by search params
        q_parts = [p for p in (callsign_clean, origin_clean, dest_clean, aircraft_clean) if p]
        query = " ".join(q_parts) if q_parts else ""

        if query:
            matched = search_index(query)
        else:
            matched = list(flights)

        # Apply category filters
        filtered = _filter_flights(matched, include_ga=include_ga_bool,
                                   include_gliders=include_gliders_bool)

        # Limit to top 100 results
        results = filtered[:100]

        # v0.25.55: add origin/destination flat aliases for frontend compatibility
        # The frontend reads flight.origin / flight.destination (flat strings)
        # but the canonical model uses origin_icao / destination_icao.
        for f in results:
            if not f.get("origin") and f.get("origin_icao"):
                f["origin"] = f["origin_icao"]
            if not f.get("destination") and f.get("destination_icao"):
                f["destination"] = f["destination_icao"]

        elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
        return JSONResponse({
            "status": "success",
            "count": len(results),
            "cache_age_seconds": round(cache_age, 1),
            "cache_stale": is_stale,
            "total_available": len(flights),
            "search_ms": elapsed_ms,
            "flights": results,
        })
    except Exception as exc:
        _log.error("[RealWorld] Search endpoint error: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": "Internal search error", "detail": str(exc)},
        )


# ── Debug enrichment endpoint (v0.25.55) ────────────────────────────────────
# Traces a single callsign through the full enrichment pipeline to identify
# exactly where data is lost.  Local-only; does not expose secrets.

_DEBUG_ROUTER = APIRouter(prefix="/api/v1/realworld-debug", tags=["realworld-debug"])


@_DEBUG_ROUTER.get("/enrichment/{callsign}")
async def debug_enrichment_pipeline(callsign: str):
    """Trace a single callsign through the enrichment pipeline.

    v0.25.55: instrumented with per-stage timing.  Never triggers refresh.
    Returns the state at each stage: raw ADSBDB → normalised → enriched → final.
    """
    t_total = time.monotonic()
    cs = _clean_str(callsign)
    if not cs:
        return JSONResponse(status_code=400, content={"error": "Invalid callsign"})

    result: dict[str, Any] = {
        "callsign_requested": cs,
        "adsbdb_raw": {},
        "after_adsbdb_client_processing": {},
        "after_normalization": {},
        "after_enrichment_merge": {},
        "final_api_output": {},
        "pipeline_checks": {},
    }

    # ── Stage 1: ADSBDB raw lookup ──
    t0 = time.monotonic()
    try:
        adsbdb_raw = await get_callsign(cs)
        ad_time = round((time.monotonic() - t0) * 1000, 1)
        if adsbdb_raw:
            fr = adsbdb_raw.get("flightroute") or adsbdb_raw.get("route") or adsbdb_raw
            result["adsbdb_raw"] = {
                "available": True,
                "latency_ms": ad_time,
                "summary": {
                    "has_flightroute": bool(adsbdb_raw.get("flightroute")),
                    "has_route": bool(adsbdb_raw.get("route")),
                    "origin_icao": (
                        (fr.get("origin") or {}).get("icao_code", "")
                        if isinstance(fr.get("origin"), dict) else str(fr.get("origin") or "")),
                    "destination_icao": (
                        (fr.get("destination") or {}).get("icao_code", "")
                        if isinstance(fr.get("destination"), dict) else str(fr.get("destination") or "")),
                    "airline": (
                        (fr.get("airline") or {}).get("name", "")
                        if isinstance(fr.get("airline"), dict) else ""),
                },
            }
        else:
            result["adsbdb_raw"] = {"available": False, "latency_ms": ad_time}
    except Exception as exc:
        result["adsbdb_raw"] = {"available": False, "error": str(exc)}

    # ── Stage 2: Simulate a minimal FR24 flight + normalise ──
    # v0.25.55: include hex (mode_s) so aircraft identity enrichment is testable
    mock_fr24 = {"flight": cs, "orig": "EDDF", "hex": "3c0000"}
    normalized = normalise_fr24(mock_fr24)
    if normalized:
        result["after_normalization"] = {
            "callsign": normalized.get("callsign"),
            "origin_icao": normalized.get("origin_icao"),
            "destination_icao": normalized.get("destination_icao"),
            "airline_name": normalized.get("airline_name"),
            "aircraft_type": normalized.get("aircraft_type"),
            "registration": normalized.get("registration"),
            "tracking_source": normalized.get("tracking_source"),
            "has_route": normalized.get("has_route"),
            "can_dispatch": normalized.get("can_dispatch"),
            "can_simbrief": normalized.get("can_simbrief"),
        }

    # ── Stage 3: Apply ADSBDB enrichment (route + aircraft identity) ──
    if normalized and adsbdb_raw:
        apply_adsbdb_route(normalized, adsbdb_raw)
        # v0.25.55: also attempt aircraft identity enrichment via mode_s or registration
        ac_raw = None
        ms = normalized.get("mode_s")
        reg = normalized.get("registration")
        ac_key = ms or (reg or "").strip().upper()
        if ac_key:
            try:
                ac_raw = await get_aircraft(ac_key)
            except Exception as exc:
                _log.debug("[RealWorld] Debug enrichment: aircraft lookup failed for %s: %s", ac_key, exc)
        if ac_raw:
            apply_adsbdb_aircraft(normalized, ac_raw)
        result["after_enrichment_merge"] = {
            "callsign": normalized.get("callsign"),
            "origin_icao": normalized.get("origin_icao"),
            "destination_icao": normalized.get("destination_icao"),
            "origin_name": normalized.get("origin_name"),
            "destination_name": normalized.get("destination_name"),
            "airline_name": normalized.get("airline_name"),
            "aircraft_type": normalized.get("aircraft_type"),
            "aircraft_icao_type": normalized.get("aircraft_icao_type"),
            "registration": normalized.get("registration"),
            "route_source": normalized.get("route_source"),
            "identity_source": normalized.get("identity_source"),
            "has_route": normalized.get("has_route"),
            "can_dispatch": normalized.get("can_dispatch"),
            "can_simbrief": normalized.get("can_simbrief"),
            "enrichment_attempted": normalized.get("enrichment_attempted"),
            "enrichment_success": normalized.get("enrichment_success"),
        }

    # ── Stage 4: Frontend-compatible flat aliases ──
    if normalized:
        final = dict(normalized)
        if not final.get("origin") and final.get("origin_icao"):
            final["origin"] = final["origin_icao"]
        if not final.get("destination") and final.get("destination_icao"):
            final["destination"] = final["destination_icao"]
        result["final_api_output"] = {
            "callsign": final.get("callsign"),
            "origin": final.get("origin"),
            "destination": final.get("destination"),
            "origin_icao": final.get("origin_icao"),
            "destination_icao": final.get("destination_icao"),
            "origin_name": final.get("origin_name"),
            "destination_name": final.get("destination_name"),
            "airline_name": final.get("airline_name"),
            "aircraft_type": final.get("aircraft_type"),
            "registration": final.get("registration"),
            "can_dispatch": final.get("can_dispatch"),
            "can_simbrief": final.get("can_simbrief"),
        }

    # ── Pipeline checks ──
    merged = result["after_enrichment_merge"]
    final_api = result["final_api_output"]
    result["pipeline_checks"] = {
        "destination_survived": bool(final_api.get("destination")),
        "origin_survived": bool(final_api.get("origin")),
        "aircraft_type_survived": bool(final_api.get("aircraft_type")),
        "registration_survived": bool(final_api.get("registration")),
        "airline_survived": bool(final_api.get("airline_name")),
        "adsbdb_available": result["adsbdb_raw"].get("available", False),
        "enrichment_applied": bool(merged.get("destination_icao")),
        "frontend_alias_set": bool(final_api.get("destination")),
    }

    # Structured debug log
    _log.debug(
        "[RealWorld] debug enrichment cs=%s | "
        "adsbdb_dest=%s normalized_dest=%s enriched_dest=%s serialized_dest=%s frontend_dest=%s | total_ms=%.1f",
        cs,
        result["adsbdb_raw"].get("summary", {}).get("destination_icao", "?"),
        result.get("after_normalization", {}).get("destination_icao"),
        result.get("after_enrichment_merge", {}).get("destination_icao"),
        result.get("final_api_output", {}).get("destination_icao"),
        result.get("final_api_output", {}).get("destination"),
        (time.monotonic() - t_total) * 1000,
    )

    result["elapsed_ms"] = round((time.monotonic() - t_total) * 1000, 1)
    return JSONResponse(result)


@router.get("/diagnostics")
async def realworld_diagnostics(include_recent_errors: bool = False):
    """Local diagnostics endpoint for the Real World Search pipeline.

    Returns pipeline stats, cache state, provider health, and (optionally)
    recent errors.  No credentials or secrets are exposed.
    """
    cache_stats = cache_all_stats()
    flights, cache_age, is_stale = get_live_flights()

    with _stats_lock:
        stats = dict(_pipeline_stats)

    # Provider reachability overview
    provider_overview: dict[str, Any] = {}
    for pname, pdata in _provider_health.items():
        provider_overview[pname] = {
            "request_count": pdata.get("request_count", 0),
            "success_count": pdata.get("success_count", 0),
            "failure_count": pdata.get("failure_count", 0),
            "last_latency_ms": pdata.get("last_latency_ms"),
            "last_success_utc": str(pdata.get("last_success_utc") or ""),
            "last_failure_utc": str(pdata.get("last_failure_utc") or ""),
            "last_error_type": pdata.get("last_error_type"),
        }

    response: dict[str, Any] = {
        "status": "ok",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "version": "0.25.55",
        "last_successful_refresh_utc": stats.get("last_refresh_utc"),
        "last_refresh_status": stats.get("last_refresh_status"),
        "serving_stale_cache": is_stale and len(flights) > 0,
        "discovery_strategy": stats.get("discovery_strategy", "none"),
        "cache": {
            "raw_count": len(flights),
            "normalized_count": stats.get("normalized", 0),
            "search_index_count": index_count(),
            "cache_age_seconds": round(cache_age, 1),
            "ttl_seconds": TTL_LIVE,
        },
        "providers": provider_overview,
        "pipeline": {
            "discovered": stats.get("discovered", 0),
            "normalized": stats.get("normalized", 0),
            "normalization_failed": stats.get("normalization_failed", 0),
            "classification": stats.get("classification", {}),
            "enrichment_attempted": stats.get("enrichment_attempted", 0),
            "enrichment_successful": stats.get("enrichment_successful", 0),
            "enrichment_failed": stats.get("enrichment_failed", 0),
            "enrichment_recovery": {
                "missing_dest_before": stats.get("enrichment_missing_dest_before", 0),
                "recovered_dest": stats.get("enrichment_recovered_dest", 0),
                "missing_origin_before": stats.get("enrichment_missing_origin_before", 0),
                "recovered_origin": stats.get("enrichment_recovered_origin", 0),
                "missing_aircraft_before": stats.get("enrichment_missing_aircraft_before", 0),
                "recovered_aircraft": stats.get("enrichment_recovered_aircraft", 0),
            },
            "enrichment_route_ok": stats.get("enrichment_route_ok", 0),
            "enrichment_aircraft_ok": stats.get("enrichment_aircraft_ok", 0),
            "enrichment_identity_ok": stats.get("enrichment_identity_ok", 0),
            "dedup_before": stats.get("before_dedup", 0),
            "dedup_after": stats.get("after_dedup", 0),
            "dedup_removed": stats.get("dedup_removed", 0),
            "final_available_count": stats.get("final_available", 0),
            "last_refresh_timings_ms": stats.get("last_refresh_timings_ms", {}),
        },
    }
    if include_recent_errors:
        response["recent_errors"] = list(_recent_errors)
    return JSONResponse(response)
