from __future__ import annotations

import base64
import csv
import io
import json
import math
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.request
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .data_loader import haversine_nm, nearest_airport, load_airports
from .notifications import publish
from .settings_store import app_data_dir, load_settings
from .simbrief_client import cached_plan
from .telemetry_provider import read_telemetry, telemetry_diagnostics, reset_source_lock
from .pirep_analysis import analyse_pirep
from .aircraft_adapters import detect_adapter
from .airline_branding import resolve_airline_branding, logo_data_uri

_LOCK = threading.RLock()
_STOP = threading.Event()
_THREAD: threading.Thread | None = None
_DB_NAME = "logbook.sqlite3"

# v0.25.72 (#21): short-TTL in-memory PIREP analysis cache (see telemetry()).
_ANALYSIS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_ANALYSIS_CACHE_TTL = 30.0
_SCHEMA = 5
_STANDBY_SAMPLES: list[dict[str, Any]] = []


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _epoch(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _elapsed(start: str | None, end: str | None) -> int | None:
    a, b = _epoch(start), _epoch(end)
    return int(round(b - a)) if a is not None and b is not None and b >= a else None


def _number(value: Any) -> float | None:
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _number(value)
        if number is not None:
            return number
    return None


def _sample_complete_for_recording(sample: dict[str, Any]) -> tuple[bool, str]:
    lat, lon = _number(sample.get("lat")), _number(sample.get("lon"))
    if lat is None or lon is None or abs(lat) < 0.001 and abs(lon) < 0.001:
        return False, "invalid position"
    if not _altitude_reliable(sample):
        return False, "missing or unreliable altitude"
    if _number(sample.get("ground_speed_kts")) is None:
        return False, "missing ground speed"
    if _number(sample.get("ias_kts")) is None:
        return False, "missing indicated speed"
    if not isinstance(sample.get("on_ground"), bool):
        return False, "missing on-ground state"
    return True, ""


def _text(value: Any, limit: int = 200) -> str:
    return str(value or "").strip()[:limit]


def _db_path() -> Path:
    return app_data_dir() / _DB_NAME


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=20, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS flights(
                id TEXT PRIMARY KEY,
                started_utc TEXT NOT NULL,
                completed_utc TEXT,
                status TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                rating INTEGER NOT NULL DEFAULT 0,
                notes TEXT NOT NULL DEFAULT '',
                updated_utc TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_flights_started ON flights(started_utc DESC);
            CREATE INDEX IF NOT EXISTS idx_flights_status ON flights(status);
            CREATE TABLE IF NOT EXISTS samples(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                flight_id TEXT NOT NULL REFERENCES flights(id) ON DELETE CASCADE,
                sampled_utc TEXT NOT NULL,
                elapsed_seconds REAL NOT NULL,
                data_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_samples_flight_time ON samples(flight_id, elapsed_seconds);
            -- #62: electronic loadsheet signature. One slot per flight; the
            -- snapshot_json captures the exact values signed (weights, MAC,
            -- sources, UTC) so the record proves what was signed. Deliberately
            -- NOT in flights.metadata_json: the recorder upsert rewrites that
            -- column wholesale and would clobber the signature.
            CREATE TABLE IF NOT EXISTS loadsheet_signatures(
                flight_id TEXT PRIMARY KEY REFERENCES flights(id) ON DELETE CASCADE,
                signer TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT '',
                sig_data_url TEXT NOT NULL DEFAULT '',
                signed_utc TEXT NOT NULL,
                snapshot_json TEXT NOT NULL DEFAULT '{}'
            );
            -- #77: post-arrival Flight Completion sign-off. Kept as its own
            -- table (same shape as loadsheet_signatures) so the pre-departure
            -- loadsheet row and the post-arrival completion row coexist per
            -- flight without a PRIMARY KEY migration on live databases.
            CREATE TABLE IF NOT EXISTS completion_signatures(
                flight_id TEXT PRIMARY KEY REFERENCES flights(id) ON DELETE CASCADE,
                signer TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT '',
                sig_data_url TEXT NOT NULL DEFAULT '',
                signed_utc TEXT NOT NULL,
                snapshot_json TEXT NOT NULL DEFAULT '{}'
            );
            """
        )
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema',?)", (str(_SCHEMA),))
    _migrate_json_once()



def _backup_corrupt_db(reason: Exception) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = _db_path()
    for suffix in ("", "-wal", "-shm"):
        src = Path(str(base) + suffix)
        if src.exists():
            try:
                dst = src.with_name(src.name + f".corrupt-{stamp}")
                shutil.move(str(src), str(dst))
            except Exception:
                pass
    try:
        (app_data_dir() / f"logbook-recovery-{stamp}.txt").write_text(f"{type(reason).__name__}: {reason}\n", encoding="utf-8")
    except Exception:
        pass


def _init_db_safe() -> None:
    try:
        _init_db()
    except sqlite3.DatabaseError as exc:
        _backup_corrupt_db(exc)
        _init_db()


def _migrate_json_once() -> None:
    legacy = app_data_dir() / "logbook.json"
    if not legacy.exists():
        return
    marker = app_data_dir() / "logbook-json-migrated.txt"
    if marker.exists():
        return
    try:
        raw = json.loads(legacy.read_text(encoding="utf-8"))
        rows = []
        active = raw.get("active") if isinstance(raw, dict) else None
        if isinstance(active, dict):
            rows.append(active)
        rows.extend(x for x in (raw.get("entries") or []) if isinstance(x, dict))
        with _connect() as conn:
            for entry in rows:
                entry_id = str(entry.get("id") or uuid.uuid4().hex)
                status_value = "RECORDING" if entry is active else str(entry.get("status") or "COMPLETE")
                entry.pop("_last_sample", None)
                entry.pop("_airborne_seen", None)
                conn.execute(
                    "INSERT OR IGNORE INTO flights(id,started_utc,completed_utc,status,metadata_json,rating,notes,updated_utc) VALUES(?,?,?,?,?,?,?,?)",
                    (entry_id, entry.get("started_utc") or _utc_now(), entry.get("completed_utc"), status_value, json.dumps(entry), int(entry.get("rating") or 0), str(entry.get("notes") or ""), entry.get("updated_utc") or _utc_now()),
                )
        marker.write_text(f"Migrated {len(rows)} legacy records at {_utc_now()}\n", encoding="utf-8")
    except Exception as exc:
        marker.write_text(f"Migration failed safely: {type(exc).__name__}: {exc}\n", encoding="utf-8")


def _current_plan() -> dict[str, Any] | None:
    settings = load_settings()
    ref = str(settings.get("identity", {}).get("simbrief_user_id") or "")
    return cached_plan(ref) if ref else None


def _airport_at(t: dict[str, Any]) -> dict[str, Any] | None:
    lat, lon = _number(t.get("lat")), _number(t.get("lon"))
    if lat is None or lon is None:
        return None
    item = nearest_airport(lat, lon)
    if not item:
        return None
    airport, distance = item
    return {"icao": airport.ident, "name": airport.name, "distance_nm": round(distance, 1)}


def _first_text(*values: Any) -> str | None:
    """Return the first non-empty string among values (backward-compatible key fallback)."""
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _resolve_plan_operation(weights: dict[str, Any]) -> dict[str, Any]:
    try:
        from .load_model import resolve_operation_type
        flight = {
            "passengers": weights.get("passengers"),
            "cargo": weights.get("cargo"),
            "cargo_hold_total": weights.get("cargo"),
            "commercial_freight_weight": weights.get("freight_added"),
            "weight_units": weights.get("units"),
        }
        return resolve_operation_type(flight, "auto")
    except Exception:
        return {"resolved": "auto", "reason": "operation resolution unavailable", "confidence": "unavailable"}


def _plan_load(weights: dict[str, Any]) -> dict[str, Any]:
    try:
        from .load_model import load_composition
        return load_composition({"weights": weights})
    except Exception:
        return {"load_breakdown_source": "combined-simbrief-cargo"}


def _ofp_plan_nested(p: dict[str, Any]) -> dict[str, Any]:
    """Immutable nested OFP plan reference stored with the recorder."""
    aircraft = p.get("aircraft") if isinstance(p.get("aircraft"), dict) else {}
    times = p.get("times") if isinstance(p.get("times"), dict) else {}
    fuel = p.get("fuel") if isinstance(p.get("fuel"), dict) else {}
    weights = p.get("weights") if isinstance(p.get("weights"), dict) else {}
    origin = p.get("origin") if isinstance(p.get("origin"), dict) else {}
    destination = p.get("destination") if isinstance(p.get("destination"), dict) else {}
    fuel_keys = ("ramp", "takeoff", "trip", "landing", "reserve", "alternate", "extra")
    weight_keys = ("passengers", "cargo", "payload", "zfw", "tow", "ldw", "freight_added", "max_zfw", "max_tow", "max_ldw", "oew")
    return {
        "identity": {
            "request_id": _text(p.get("request_id"), 40),
            "sequence_id": _text(p.get("sequence_id"), 40),
            "plan_id": _text(p.get("plan_id"), 40),
            "generated_utc": _text(p.get("generated_utc"), 40),
            "fetched_utc": _text(p.get("fetched_utc"), 40),
            "callsign": _text(p.get("callsign"), 20),
            "origin": _text(origin.get("icao"), 4).upper(),
            "destination": _text(destination.get("icao"), 4).upper(),
            "scheduled_out": _first_text(times.get("scheduled_out"), times.get("scheduled_out_utc")),
            "registration": _text(aircraft.get("registration"), 20).upper(),
        },
        "times": {key: times.get(key) for key in ("scheduled_out", "scheduled_off", "scheduled_on", "scheduled_in")},
        "fuel": {key: _number(fuel.get(key)) for key in fuel_keys} | {"units": _text(fuel.get("units"), 8).upper()},
        "weights": {key: _number(weights.get(key)) for key in weight_keys} | {"units": _text(weights.get("units"), 8).upper()},
        "load": _plan_load(weights),
        "units": {"fuel": _text(fuel.get("units"), 8).upper(), "weight": _text(weights.get("units"), 8).upper()},
    }


def _op_snapshot(sample: dict[str, Any], at: str, estimated: bool = False) -> dict[str, Any]:
    """Immutable operational snapshot captured at an event moment.

    Reads only what the sample carries at that instant; missing optional
    weights stay None (never fabricated).  Once stored, a snapshot is never
    overwritten by later samples.
    """
    fuel_lb = _number(sample.get("fuel_total_lb"))
    gross = _number(sample.get("gross_weight_lb"))
    return {
        "time_utc": at,
        "telemetry_source": _text(sample.get("source")),
        "fuel_lb": fuel_lb,
        "gross_weight_lb": gross,
        "empty_weight_lb": _number(sample.get("empty_weight_lb")),
        "payload_weight_lb": _number(sample.get("payload_weight_lb")),
        "calculated_zfw_lb": round(gross - fuel_lb, 1) if gross is not None and fuel_lb is not None and gross >= fuel_lb else None,
        "max_zero_fuel_weight_lb": _number(sample.get("max_zero_fuel_weight_lb")),
        "max_takeoff_weight_lb": _number(sample.get("max_takeoff_weight_lb")),
        "max_landing_weight_lb": _number(sample.get("max_landing_weight_lb")),
        "estimated": bool(estimated),
        "confidence": "estimated" if estimated else "verified",
    }


def _plan_snapshot(plan: dict[str, Any] | None) -> dict[str, Any]:
    p = plan or {}
    aircraft = p.get("aircraft") if isinstance(p.get("aircraft"), dict) else {}
    fuel = p.get("fuel") if isinstance(p.get("fuel"), dict) else {}
    weights = p.get("weights") if isinstance(p.get("weights"), dict) else {}
    times = p.get("times") if isinstance(p.get("times"), dict) else {}
    navlog = []
    for item in p.get("navlog") or []:
        if not isinstance(item, dict):
            continue
        lat, lon = _number(item.get("latitude")), _number(item.get("longitude"))
        if lat is not None and lon is not None:
            navlog.append({"ident": _text(item.get("ident"), 12).upper(), "lat": lat, "lon": lon, "altitude_ft": _number(item.get("altitude_ft"))})
    bag_count = _number(weights.get("bag_count"))
    bag_weight = _number(weights.get("bag_weight"))
    baggage_total = round(bag_count * bag_weight, 1) if bag_count is not None and bag_weight is not None else None
    return {
        "callsign": _text(p.get("callsign"), 20),
        "airline": _text(p.get("airline"), 4).upper(),
        "airline_branding": resolve_airline_branding(p),
        "origin": _text((p.get("origin") or {}).get("icao"), 4).upper() if isinstance(p.get("origin"), dict) else "",
        "destination": _text((p.get("destination") or {}).get("icao"), 4).upper() if isinstance(p.get("destination"), dict) else "",
        "departure_runway": _text((p.get("origin") or {}).get("runway"), 12).upper() if isinstance(p.get("origin"), dict) else "",
        "arrival_runway": _text((p.get("destination") or {}).get("runway"), 12).upper() if isinstance(p.get("destination"), dict) else "",
        "alternate": _text((p.get("alternate") or {}).get("icao"), 4).upper() if isinstance(p.get("alternate"), dict) else "",
        "route": _text(p.get("route"), 5000),
        "navlog": navlog,
        "aircraft_icao": _text(aircraft.get("icao"), 12).upper(),
        "registration": _text(aircraft.get("registration"), 20).upper(),
        "cruise_altitude_ft": _number(p.get("cruise_altitude_ft")),
        "distance_nm": _number(p.get("distance_nm")),
        "ete_seconds": _number(p.get("ete_seconds")),
        "block_time_seconds": _number(p.get("block_time_seconds")),
        "scheduled_out_utc": _first_text(times.get("scheduled_out"), times.get("scheduled_out_utc")),
        "scheduled_off_utc": _first_text(times.get("scheduled_off"), times.get("scheduled_off_utc")),
        "scheduled_on_utc": _first_text(times.get("scheduled_on"), times.get("scheduled_on_utc")),
        "scheduled_in_utc": _first_text(times.get("scheduled_in"), times.get("scheduled_in_utc")),
        "fuel_units": _text(fuel.get("units"), 8).upper(),
        "planned_ramp_fuel": _number(fuel.get("ramp")),
        "planned_takeoff_fuel": _number(fuel.get("takeoff")),
        "planned_trip_fuel": _number(fuel.get("trip")),
        "planned_landing_fuel": _number(fuel.get("landing")),
        "planned_reserve_fuel": _number(fuel.get("reserve")),
        "planned_alternate_fuel": _number(fuel.get("alternate")),
        "planned_extra_fuel": _number(fuel.get("extra")),
        "weight_units": _text(weights.get("units"), 8).upper(),
        "passengers": _number(weights.get("passengers")),
        "cargo": _number(weights.get("cargo")),
        "cargo_hold_total": _number(weights.get("cargo")),
        "baggage_weight": baggage_total,
        "commercial_freight_weight": _number(weights.get("freight_added")),
        "payload": _number(weights.get("payload")),
        "planned_zfw": _number(weights.get("zfw")),
        "planned_tow": _number(weights.get("tow")),
        "planned_ldw": _number(weights.get("ldw")),
        "planned_max_zfw": _number(weights.get("max_zfw")),
        "planned_max_tow": _number(weights.get("max_tow")),
        "planned_max_ldw": _number(weights.get("max_ldw")),
        "operation_type_requested": _text(p.get("operation_type_requested")) or "auto",
        "operation_type_resolved": _resolve_plan_operation(weights).get("resolved", "auto"),
        "ofp_plan": _ofp_plan_nested(p),
    }


def _aircraft_snapshot(t: dict[str, Any]) -> dict[str, Any]:
    a = t.get("aircraft") if isinstance(t.get("aircraft"), dict) else {}
    base = {"title": _text(a.get("title"), 160), "model": _text(a.get("model"), 80), "type": _text(a.get("type"), 40)}
    adapter = t.get("aircraft_adapter") if isinstance(t.get("aircraft_adapter"), dict) else detect_adapter(base)
    base["adapter"] = {"key": adapter.get("key"), "label": adapter.get("label"), "telemetry_mode": "standard + verified enrichment"}
    return base


def _position(t: dict[str, Any]) -> dict[str, Any]:
    return {"lat": _number(t.get("lat")), "lon": _number(t.get("lon")), "altitude_ft": _number(t.get("indicated_altitude_ft")) or _number(t.get("altitude_ft"))}


def _event(meta: dict[str, Any], kind: str, detail: str, at: str | None = None, severity: str = "info") -> None:
    events = meta.setdefault("events", [])
    events.append({"time": at or _utc_now(), "kind": kind.upper()[:30], "detail": detail[:300], "severity": severity})
    del events[:-300]


def _violation(meta: dict[str, Any], key: str, title: str, detail: str, penalty: int, at: str) -> None:
    violations = meta.setdefault("violations", [])
    state = meta.setdefault("_state", {})
    seen = state.setdefault("violations_seen", {})
    # Repeated conditions are rate-limited while still counting meaningful recurrences.
    last = _epoch(seen.get(key))
    now = _epoch(at) or time.time()
    if last is not None and now - last < 60:
        return
    seen[key] = at
    violations.append({"time": at, "key": key, "title": title, "detail": detail[:300], "penalty": max(0, int(penalty))})
    del violations[:-200]
    _event(meta, "DEVIATION", f"{title}: {detail}", at, "warning")


def _sample(t: dict[str, Any], now: str) -> dict[str, Any]:
    systems = t.get("systems") if isinstance(t.get("systems"), dict) else {}
    autopilot = t.get("autopilot") if isinstance(t.get("autopilot"), dict) else {}
    return {
        "time": now,
        "source": t.get("source"),
        "lat": _number(t.get("lat")), "lon": _number(t.get("lon")),
        "altitude_ft": None if t.get("altitude_unreliable") else _first_number(t.get("indicated_altitude_ft"), t.get("altitude_ft")),
        "pressure_altitude_ft": None if t.get("altitude_unreliable") else _number(t.get("pressure_altitude_ft")),
        "altitude_unreliable": bool(t.get("altitude_unreliable")),
        "altitude_confidence": t.get("altitude_confidence"),
        "altitude_source": t.get("altitude_source"),
        "agl_ft": _number(t.get("agl_ft")), "radio_altitude_ft": _number(t.get("radio_altitude_ft")),
        "ias_kts": _number(t.get("indicated_speed_kts")), "tas_kts": _number(t.get("true_speed_kts")), "mach": _number(t.get("mach")),
        "ground_speed_kts": _number(t.get("ground_speed_kts")), "vertical_speed_fpm": _number(t.get("vertical_speed_fpm")),
        "raw_ground_speed_kts": _number(t.get("raw_ground_speed_kts")), "raw_vertical_speed_fpm": _number(t.get("raw_vertical_speed_fpm")),
        "heading_deg": _number(t.get("heading_deg")), "track_deg": _number(t.get("track_deg")),
        "body_velocity_x_fps": _number(t.get("body_velocity_x_fps")),
        "pitch_deg": _number(t.get("pitch_deg")), "bank_deg": _number(t.get("bank_deg")), "g_force": _number(t.get("g_force")),
        "raw_g_force": _number(t.get("raw_g_force")), "raw_radio_altitude_ft": _number(t.get("raw_radio_altitude_ft")),
        "fuel_total_lb": _number(t.get("fuel_total_lb")), "fuel_flow_pph": _number(t.get("fuel_flow_pph")),
        "flap_index": _number(t.get("flap_index")), "flap_percent": _number(t.get("flap_percent")),
        "gear_percent": _number(t.get("gear_percent")), "spoiler_percent": _number(t.get("spoiler_percent")),
        "reverser_percent": _number(t.get("reverser_percent")), "brake_percent": _number(t.get("brake_percent")),
        "engine_n1_percent": _number(t.get("engine_n1_percent")),
        "localizer_deviation": _number(t.get("localizer_deviation")), "glideslope_deviation": _number(t.get("glideslope_deviation")),
        "on_ground": t.get("on_ground") if isinstance(t.get("on_ground"), bool) else None, "ground_safe": bool(t.get("ground_safe", False)), "confirmed_airborne": bool(t.get("confirmed_airborne", False)), "sim_on_ground_raw": t.get("sim_on_ground_raw"), "weight_on_wheels": t.get("weight_on_wheels") if isinstance(t.get("weight_on_wheels"), bool) else (t.get("wow") if isinstance(t.get("wow"), bool) else None), "parking_brake": systems.get("parking_brake"), "engines_running": systems.get("engines_running"),
        "autopilot": autopilot.get("engaged"), "autothrottle": autopilot.get("autothrottle"),
        "wind_speed_kts": _number(t.get("wind_speed_kts")), "wind_direction_deg": _number(t.get("wind_direction_deg")),
        "sim_rate": _number(t.get("sim_rate")) or 1.0, "paused": bool(t.get("paused")), "slew_active": bool(t.get("slew_active")),
        "telemetry_gap": bool(t.get("telemetry_gap")), "telemetry_hold": bool(t.get("telemetry_hold")),
        "stall_warning": bool(t.get("stall_warning")), "overspeed_warning": bool(t.get("overspeed_warning")),
    }


def _telemetry_confirms_airborne(t: dict[str, Any]) -> bool:
    if t.get("confirmed_airborne") is True:
        return True
    if t.get("on_ground") is not False:
        return False
    gs = _number(t.get("ground_speed_kts")) or 0.0
    ias = _number(t.get("indicated_speed_kts")) or _number(t.get("ias_kts")) or 0.0
    agl = _number(t.get("radio_altitude_ft"))
    if agl is None:
        agl = _number(t.get("agl_ft")) or 0.0
    return bool(gs >= 55.0 and ias >= 45.0 and agl >= 30.0)


def _gsx_predeparture_active() -> bool:
    """Return True when GSX says the aircraft is still being serviced/boarded."""
    try:
        from .gsx_remote import status as gsx_status
        gsx = gsx_status(force=False)
    except Exception:
        return False, False
    if not gsx.get("ok") or not gsx.get("connected"):
        return False, False
    services = gsx.get("services") or {}
    progress = gsx.get("progress") or {}
    pax = int(progress.get("passengers_boarding_total") or 0)
    cargo = float(progress.get("boarding_cargo_percent") or 0)
    for key in ("boarding", "catering", "refuel", "water", "gpu"):
        try:
            raw = int(((services.get(key) or {}).get("raw")) or 0)
        except Exception:
            raw = 0
        if raw in {4, 5, 7}:
            return True
    return bool(pax > 0 or cargo > 0)


def _v0259_phase_transition_log(prev, new, **meta):
    try:
        import logging as _logging_v0259
        _logging_v0259.getLogger('opsroom.logbook').info(
            '[PHASE TRANSITION] %s -> %s pushback_active=%s pushback_completed=%s gs=%s meta=%s',  # v0.25.9: info-level
            prev, new,
            meta.get('pushback_active'),
            meta.get('pushback_completed'),
            meta.get('ground_speed_kts'),
            {k: v for k, v in (meta or {}).items() if k in ('taxi_out_gs_counter', 'taxi_out_motion_logged', 'pushback_forward_taxi_proven')},
        )
    except Exception:
        pass


def _v0259_pushback_diagnostic(state):
    if not isinstance(state, dict):
        state = {}
    return {
        'pushback_active': bool(state.get('pushback_active')),
        'pushback_completed': bool(state.get('pushback_completed')),
        'pushback_started_at': state.get('pushback_started_at'),
        'pushback_completed_at': state.get('pushback_completed_at'),
        'taxi_out_started_at': state.get('taxi_out_started_at'),
        'taxi_out_motion_logged': bool(state.get('taxi_out_motion_logged')),
        'taxi_out_gs_counter': int(state.get('taxi_out_gs_counter') or 0),
        'pushback_forward_taxi_proven': bool(state.get('pushback_forward_taxi_proven')),
    }


def _v0259_assert_taxi_out_eligible(state, ground_speed_kts):
    diag = _v0259_pushback_diagnostic(state)
    if diag['pushback_active'] and not diag['pushback_completed']:
        return False, 'pushback_active'
    if ground_speed_kts is None or ground_speed_kts <= 5.0:
        if not diag['pushback_forward_taxi_proven']:
            return False, 'gs_below_5kt_no_motion_proof'
    return True, 'ok'


def _gsx_pushback_active() -> bool:
    """Return dedicated GSX pushback evidence without treating wait status as completion.

    The return value remains the public boolean used by the existing phase
    callers.  The current observation's explicit-clear bit is retained on the
    function for ``_analyse`` so the per-recording latch can distinguish a
    completed/disconnected tug from an unavailable cache or read failure.

    v0.25.9: memoized for 1s to keep the per-tick phase evaluation from
    hammering the GSX status IPC on the hot path.
    """
    _md = getattr(_gsx_pushback_active, "_memo", None)
    if _md is not None and (time.monotonic() - _md[0]) < 1.0:
        setattr(_gsx_pushback_active, "_last_explicit_clear", _md[2])
        return _md[1]
    _val, _explicit = _gsx_pushback_active_inner()
    setattr(_gsx_pushback_active, "_memo", (time.monotonic(), _val, _explicit))
    setattr(_gsx_pushback_active, "_last_explicit_clear", _explicit)
    return _val


def _gsx_pushback_active_inner() -> tuple[bool, bool]:
    """Companion inner compute for _gsx_pushback_active.

    Returns ``(pushback_active, last_explicit_clear)`` so the memo can replay
    both the boolean and the latch bit used by ``_analyse``.
    """
    setattr(_gsx_pushback_active_inner, "_last_explicit_clear_seen", False)
    try:
        from .gsx_remote import status as gsx_status
        gsx = gsx_status(force=False)
    except Exception:
        return False
    if not gsx.get("ok") or not gsx.get("connected"):
        return False

    # Only the dedicated row is physical-pushback evidence.  In particular,
    # the broader departure workflow is deliberately never consulted here.
    row = (gsx.get("services") or {}).get("pushback")
    if not isinstance(row, dict):
        return False, False

    try:
        raw = int(row.get("raw") or 0)
    except Exception:
        raw = 0

    def token(value: Any) -> str:
        return str(value or "").strip().upper().replace("-", "_").replace(" ", "_")

    states = {token(row.get("state")), token(row.get("remote_state"))}
    text = " ".join(
        str(row.get(name) or "")
        for name in ("status_text", "state_text", "waiting_reason", "detail", "progress_text")
    ).lower()
    explicit_clear = bool(states & {"COMPLETE", "COMPLETED", "FINISHED", "DISCONNECTED", "TUG_DISCONNECTED", "CLEAR", "CLEARED"})
    if not explicit_clear:
        explicit_clear = bool(re.search(r'(?<!\w)(?:completed|complete|finished|disconnected|tug\s+clear|pushback\s+clear)(?!\w)', text))
    if explicit_clear:
        return False, True

    # Official Remote rows preserve their semantic state in ``remote_state``
    # even when waiting normalizes their display raw/state to COMPLETING/7.
    # Generic waiting text is contextual and is never negative evidence.
    if states & {"ACTIVE", "PERFORMING", "IN_PROGRESS"}:
        return True, False
    return bool(raw == 5 and str(row.get("source") or "").lower() == "official-remote-api-v2"), False


def _backward_motion_active(sample: dict[str, Any]) -> bool:
    """Detect any tug pushing the aircraft backward (GSX, default or third-party).

    Two independent telemetry signals are combined so ordinary forward taxi is
    never mistaken for pushback:

    1. MSFS ``VELOCITY_BODY_X`` is positive forward; a sustained negative value
       while on the ground means the aircraft is being pushed backward.
    2. When moving slowly on the ground, a ground track ~180 degrees opposite
       the nose heading means the aircraft is travelling tail-first.

    The tug speed guard (0.5-5 kt) matches the physical envelope of a pushback
    tug; anything faster is self-powered taxi and handled by the existing
    TAXI OUT logic.
    """
    if sample.get("on_ground") is not True and sample.get("ground_safe") is not True:
        return False
    gs = _number(sample.get("ground_speed_kts")) or 0.0
    # v0.25.72 (#12): MSFS ground speed routinely reads 6-10 kt while a tug is
    # pushing, so the tug envelope is raised from 5 kt to 10 kt.
    if gs < 0.5 or gs > 10.0:
        return False
    body_vx = _number(sample.get("body_velocity_x_fps"))
    if body_vx is not None and body_vx <= -1.5:
        return True
    heading = _number(sample.get("heading_deg"))
    track = _number(sample.get("track_deg"))
    if heading is None or track is None:
        return False
    delta = abs(((track - heading) + 180.0) % 360.0 - 180.0)
    return delta >= 150.0


def _forward_motion_evidence(sample: dict[str, Any]) -> bool | None:
    """True when the aircraft is moving forward (not being pushed tail-first).

    Returns None when the direction data is unavailable — callers treat None
    as "do not block" so missing body-velocity/track data never freezes the
    phase, while explicit backward motion (body X strongly negative or track
    ~180° opposite the nose) always blocks a fast-taxi override.
    """
    body_vx = _number(sample.get("body_velocity_x_fps"))
    if body_vx is not None and abs(body_vx) > 2.0:
        return body_vx > 0.0
    heading = _number(sample.get("heading_deg"))
    track = _number(sample.get("track_deg"))
    if heading is None or track is None:
        return None
    delta = abs(((track - heading) + 180.0) % 360.0 - 180.0)
    if delta < 2.0 and body_vx is None:
        # #42: Fenix/FSUIPC exposes no independent ground track (track exactly
        # mirrors heading) and no body velocity — direction is UNKNOWN, not
        # forward. Treating it as forward let a fast pushback spike (10-12 kt
        # while the tug turns the aircraft) clear a latched pushback.
        return None
    return delta < 90.0


def _altitude_reliable(sample: dict[str, Any]) -> bool:
    if sample.get("altitude_unreliable") is True:
        return False
    if str(sample.get("altitude_confidence") or "").lower() in {"invalid", "unreliable"}:
        return False
    alt = _number(sample.get("altitude_ft"))
    agl = _number(sample.get("radio_altitude_ft"))
    if agl is None:
        agl = _number(sample.get("agl_ft"))
    gs = _number(sample.get("ground_speed_kts")) or 0.0
    ias = _number(sample.get("ias_kts")) or _number(sample.get("indicated_speed_kts")) or 0.0
    if alt is None:
        return False
    if agl is not None and agl > 1000 and (gs > 100 or ias > 100) and (abs(alt) < 500 or alt + 1000 < agl):
        return False
    return True


def _sample_ground_safe(sample: dict[str, Any]) -> bool:
    if sample.get("on_ground") is True or sample.get("ground_safe") is True:
        return True
    gs = _number(sample.get("ground_speed_kts")) or 0.0
    ias = _number(sample.get("ias_kts")) or 0.0
    agl = _number(sample.get("radio_altitude_ft"))
    if agl is None:
        agl = _number(sample.get("agl_ft")) or 0.0
    if gs <= 10.0 and ias <= 45.0 and agl <= 20.0:
        return True
    if _gsx_predeparture_active() and gs <= 12.0 and agl <= 25.0:
        return True
    return False


def _airborne_candidate(sample: dict[str, Any]) -> bool:
    if sample.get("on_ground") is not False:
        return False
    gs = _number(sample.get("ground_speed_kts")) or 0.0
    ias = _number(sample.get("ias_kts")) or 0.0
    agl = _number(sample.get("radio_altitude_ft"))
    if agl is None:
        agl = _number(sample.get("agl_ft")) or 0.0
    physically_airborne = bool(gs >= 55.0 and ias >= 45.0 and agl >= 30.0)
    if not physically_airborne:
        return False
    # #59: GSX pre-departure state (boarding/catering/refuel rows, cached
    # boarding progress) must NEVER veto airborne confirmation once the
    # physical evidence is unambiguous — GSX keeps its departure workflow open
    # until it registers the aircraft has departed, which delayed the OFF
    # timestamp ~45 s on EWG5EZ (phase stayed TAKEOFF ROLL to 2,147 ft AGL).
    # GSX can only *weaken* a borderline candidate (agl < 150 ft); a clear
    # climb is confirmed by physics alone. GSX can delay a departure, never
    # prove or disprove one.
    if agl >= 150.0 or (sample.get("vertical_speed_fpm") or 0.0) >= 500.0:
        return True
    if _gsx_predeparture_active():
        return False
    return True


def _confirmed_airborne_from_recent(recent: list[dict[str, Any]]) -> bool:
    usable = [x for x in recent[-5:] if isinstance(x, dict)]
    if len(usable) >= 3 and all(_airborne_candidate(x) for x in usable[-3:]):
        return True
    current = usable[-1] if usable else {}
    agl = _number(current.get("radio_altitude_ft"))
    if agl is None:
        agl = _number(current.get("agl_ft")) or 0.0
    # Allow a manual mid-air start only if the aircraft is undeniably airborne.
    return bool(_airborne_candidate(current) and agl >= 500.0)


def _new_meta(t: dict[str, Any], plan: dict[str, Any] | None, manual: bool) -> dict[str, Any]:
    now = _utc_now(); airport = _airport_at(t); fuel = _number(t.get("fuel_total_lb"))
    meta = {
        "id": uuid.uuid4().hex, "state": "RECORDING", "started_utc": now, "updated_utc": now, "manual_start": bool(manual),
        "telemetry_source": t.get("source") or "unknown", "telemetry_diagnostics": telemetry_diagnostics(False),
        "flight": _plan_snapshot(plan), "aircraft": _aircraft_snapshot(t),
        "times": {"block_out": None, "takeoff": None, "landing": None, "block_in": None},
        "airports": {"start": airport, "takeoff": None, "landing": None, "end": None},
        "positions": {"start": _position(t), "takeoff": None, "landing": None, "end": None},
        "fuel": {"start_lb": fuel, "departure_baseline_lb": fuel, "takeoff_lb": None, "landing_lb": None, "end_lb": None, "current_lb": fuel, "used_lb": 0.0},
        "operational_snapshots": {"start": {}, "out": {}, "off": {}, "on": {}, "in": {}},
        "metrics": {"distance_nm": 0.0, "max_altitude_ft": None if t.get("altitude_unreliable") else _first_number(t.get("indicated_altitude_ft"), t.get("altitude_ft")), "max_ias_kts": _number(t.get("indicated_speed_kts")), "max_ground_speed_kts": _number(t.get("ground_speed_kts")), "max_climb_fpm": max(0.0, _number(t.get("vertical_speed_fpm")) or 0.0), "max_descent_fpm": min(0.0, _number(t.get("vertical_speed_fpm")) or 0.0), "max_bank_deg": abs(_number(t.get("bank_deg")) or 0.0), "max_g": _number(t.get("g_force")), "min_g": _number(t.get("g_force")), "landing_rate_fpm": None, "touchdown_speed_kts": None, "touchdown_g": None, "touchdowns": 0, "bounce_count": 0, "bounce_penalty": 0, "bounce_severity": None, "max_cross_track_nm": None, "average_cross_track_nm": None},
        "events": [], "violations": [], "notes": "", "rating": 0,
        "_state": {"last_sample": None, "airborne_seen": False, "approach_seen": False, "cross_track_sum": 0.0, "cross_track_count": 0, "connection_lost_at": None, "violations_seen": {}, "fuel_used_accum_lb": 0.0, "fuel_last_lb": fuel, "fuel_last_source": str(t.get("source") or "")},
    }
    _event(meta, "RECORDING", "Manual flight recording started" if manual else "Automatic flight recording started", now)
    snapshots = meta["operational_snapshots"]
    snapshots["start"] = _op_snapshot(t, now)
    if _telemetry_confirms_airborne(t):
        meta["hot_start"] = True
        meta["_state"]["airborne_seen"] = True
        meta["_state"]["confirmed_airborne_seen"] = True
        if manual:
            meta["times"]["block_out"] = now; meta["times"]["takeoff"] = now
            meta["positions"]["takeoff"] = _position(t); meta["airports"]["takeoff"] = airport; meta["fuel"]["takeoff_lb"] = fuel
            # Manual mid-air starts: departure values are estimated, never exact.
            snapshots["out"] = _op_snapshot(t, now, estimated=True)
            snapshots["off"] = _op_snapshot(t, now, estimated=True)
            _event(meta, "AIRBORNE", "Manual recording began after confirmed airborne telemetry; departure times are estimated", now, "warning")
        else:
            # #69: automatic hot start (app launched mid-flight / recorder joined
            # an already-airborne session). The phase machine must be allowed to
            # reach LANDING without a recorded takeoff, or the session stays in
            # DESCENT CANDIDATE forever and the flight never finalizes (the
            # 4.35 h orphan). Departure times stay unset (unknown, not estimated).
            _event(meta, "AIRBORNE", "Automatic recording began mid-flight (hot start); departure times are unavailable", now, "warning")
    elif manual:
        _event(meta, "PREBLOCK", "Manual recording initialized on ground/pre-departure state; takeoff will remain unset until confirmed", now)
    return meta


def _route_xte_nm(lat: float, lon: float, route: list[dict[str, Any]]) -> float | None:
    if len(route) < 2:
        return None
    best = None
    for a, b in zip(route, route[1:]):
        lat1, lon1, lat2, lon2 = _number(a.get("lat")), _number(a.get("lon")), _number(b.get("lat")), _number(b.get("lon"))
        if None in (lat1, lon1, lat2, lon2):
            continue
        scale = max(0.15, math.cos(math.radians((lat1 + lat2 + lat) / 3.0)))
        ax, ay = lon1 * 60 * scale, lat1 * 60
        bx, by = lon2 * 60 * scale, lat2 * 60
        px, py = lon * 60 * scale, lat * 60
        dx, dy = bx - ax, by - ay
        denom = dx * dx + dy * dy
        t = 0.0 if denom == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / denom))
        dist = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
        best = dist if best is None else min(best, dist)
    return best


def _phase(sample: dict[str, Any], meta: dict[str, Any]) -> str:
    gs = sample.get("ground_speed_kts") or 0.0
    agl = sample.get("agl_ft")
    vs = sample.get("vertical_speed_fpm") or 0.0
    state = meta.get("_state") or {}
    times = meta.get("times") or {}
    airborne_confirmed = bool(sample.get("confirmed_airborne"))
    airborne_seen = bool(state.get("airborne_seen") or times.get("takeoff"))

    # The per-recording latch is updated in _analyse before phase selection.
    # Consult it before any fresh GSX read so a transient unavailable/cache
    # sample cannot demote tug movement to TAXI OUT.
    pushback_active = bool(state.get("pushback_positive_latch") or state.get("pushback_active") or sample.get("pushback_active"))
    if not pushback_active and not state.get("pushback_forward_taxi_proven"):
        pushback_active = _gsx_pushback_active() or _backward_motion_active(sample)
    if sample.get("on_ground") is True or sample.get("ground_safe") is True:
        if pushback_active and gs <= 10.0:
            return "PUSHBACK"
        if gs < 1:
            return "PARKED"
        if times.get("landing") or airborne_seen:
            return "LANDING ROLL" if gs >= 40 else "TAXI IN"
        # #42: phase-ordering invariant — TAXI OUT must never precede BLOCK OUT.
        # Any pre-off-blocks ground movement is a pushback, regardless of whether
        # the dedicated GSX/body-vx/track signals can see it (Fenix cannot).
        # #56 hardening: a "pushback proven" flag set before any physical
        # movement (parked sample with a GSX-active row, tug merely scheduled)
        # is invalid — treat it as absent so the invariant still yields
        # PUSHBACK at the first real movement.
        if not times.get("block_out") and not (state.get("pushback_forward_taxi_proven") and state.get("pushback_movement_seen")):
            return "PUSHBACK"
        if gs < 40:
            return "TAXI OUT"
        return "TAKEOFF ROLL"

    if not airborne_confirmed and not airborne_seen:
        # Telemetry uncertainty is a sample-quality condition, not a flight phase.
        # Do not let a single non-ground/non-airborne sample block the normal
        # TAXI OUT -> TAKEOFF ROLL -> TAKEOFF chain.
        previous_phase = str(state.get("phase") or "").upper()
        state["telemetry_uncertain"] = True
        if gs >= 40:
            return "TAKEOFF ROLL"
        if gs >= 1:
            return previous_phase if previous_phase in {"PUSHBACK", "TAXI OUT", "TAKEOFF ROLL"} else "TAXI OUT"
        return previous_phase if previous_phase in _PHASE_TRANSITIONS else "PARKED"

    if not airborne_seen and airborne_confirmed:
        # Always enter the airborne sequence through TAKEOFF.  A raw ENROUTE
        # classification here used to be rejected from TAXI OUT and left the
        # recorder stuck on the ground for the entire flight.
        return "TAKEOFF"

    previous_phase = str(state.get("phase") or "").upper()
    if agl is not None and agl < 2000 and vs < -150:
        return "APPROACH"
    if agl is not None and agl < 3000 and previous_phase in {"APPROACH", "DESCENT"} and vs > 500:
        return "GO-AROUND"
    if agl is not None and agl < 2000 and vs > 300:
        return "INITIAL CLIMB"
    cruise = _number((meta.get("flight") or {}).get("cruise_altitude_ft"))
    alt = _number(sample.get("altitude_ft"))
    if alt is None:
        return str(state.get("phase") or "ENROUTE")
    if previous_phase == "DESCENT":
        # Step-downs, vectoring level-offs and holds after TOD are still descent.
        # Do not bounce back to CRUISE solely because VS is near zero above 10k.
        if vs > 700 and agl is not None and agl < 5000:
            return "GO-AROUND"
        return "DESCENT"
    if previous_phase in {"GO-AROUND", "MISSED APPROACH"}:
        if vs > 150:
            return "MISSED APPROACH"
        if agl is not None and agl < 3000 and vs < -150:
            return "APPROACH"
        return "ENROUTE"
    if vs > 300 and (not cruise or alt < cruise - 1000):
        state["descent_candidate_count"] = 0
        state.pop("descent_candidate_alt_ft", None)
        # #66: once ENROUTE is settled, never bounce back to CLIMB. The climb
        # detector keeps firing for minutes after a slow top-of-climb (observed:
        # 20 rejected ENROUTE -> CLIMB proposals on EWG5EZ) because vs stays
        # >300 while the aircraft slowly approaches cruise. Only a genuine
        # climb excursion (strong sustained climb well below cruise) may
        # re-propose CLIMB from ENROUTE.
        if previous_phase == "ENROUTE":
            if vs > 900 and (not cruise or alt < cruise - 3000):
                return "CLIMB"
            return "ENROUTE"
        return "CLIMB"

    # v0.24.17: do not declare descent from a single VNAV/ATC restriction
    # correction. Require sustained downward trend plus altitude loss/hysteresis.
    if airborne_seen and vs < -450:
        # A descent candidate is only meaningful after a real climb/cruise
        # segment. This rejects the short-lived bad telemetry sequence that can
        # otherwise produce TAKEOFF -> DESCENT within a few seconds.
        if float(state.get("airborne_elapsed_s") or 0.0) < 240.0 or previous_phase not in {"CLIMB", "CRUISE", "ENROUTE", "DESCENT CANDIDATE", "DESCENT"}:
            state["descent_candidate_count"] = 0
            state.pop("descent_candidate_alt_ft", None)
            return previous_phase or "CLIMB"
        count = int(state.get("descent_candidate_count") or 0) + 1
        first_alt = state.get("descent_candidate_alt_ft")
        if first_alt is None:
            first_alt = alt
        state["descent_candidate_count"] = count
        state["descent_candidate_alt_ft"] = first_alt
        loss = max(0.0, float(first_alt or alt) - float(alt))
        below_cruise = bool(cruise and alt < cruise - 1200)
        confirmed = count >= 4 and (loss >= 700.0 or below_cruise or alt < 18000)
        if previous_phase == "DESCENT" or confirmed:
            return "DESCENT"
        return "DESCENT CANDIDATE" if previous_phase in {"CRUISE", "ENROUTE", "DESCENT CANDIDATE"} else previous_phase or "ENROUTE"
    if vs > -100:
        if previous_phase != "DESCENT":
            state["descent_candidate_count"] = 0
            state.pop("descent_candidate_alt_ft", None)

    if alt > 10000 and abs(vs) < 350:
        return "CRUISE"
    return "ENROUTE"


# #85: the phase-transition invariant table is SHARED with flight_watch so
# the display and recorder can never drift on legal phase ordering. Content is
# byte-identical to the local table this replaces (verified).
from .phase_machine import _PHASE_TRANSITIONS, transition_allowed as _phase_transition_allowed  # noqa: E402


def _update_fuel_accounting(meta: dict[str, Any], current: dict[str, Any]) -> None:
    """Maintain a refuelling-safe departure baseline and cumulative fuel burn."""
    state = meta.setdefault("_state", {})
    times = meta.setdefault("times", {})
    fuel = meta.setdefault("fuel", {})
    current_fuel = _number(current.get("fuel_total_lb"))
    if current_fuel is None:
        return
    fuel["current_lb"] = current_fuel
    source_now = str(current.get("source") or "")
    source_prev = str(state.get("fuel_last_source") or "")
    last_fuel = _number(state.get("fuel_last_lb"))
    if not times.get("block_out") and current.get("on_ground") is not False:
        candidates = (
            _number(fuel.get("departure_baseline_lb")),
            _number(fuel.get("start_lb")),
            current_fuel,
        )
        baseline = max(value for value in candidates if value is not None)
        fuel["departure_baseline_lb"] = baseline
        fuel["start_lb"] = baseline
        state["fuel_used_accum_lb"] = 0.0
        fuel["used_lb"] = 0.0
    else:
        # A provider switch can introduce harmless unit/rounding differences.
        # Reset only the point-to-point comparator; never erase accumulated burn.
        if source_prev and source_now and source_prev != source_now:
            last_fuel = current_fuel
        if last_fuel is not None:
            decrease = last_fuel - current_fuel
            if 0.0 < decrease <= max(1500.0, last_fuel * 0.12):
                state["fuel_used_accum_lb"] = float(state.get("fuel_used_accum_lb") or 0.0) + decrease
        fuel["used_lb"] = round(max(0.0, float(state.get("fuel_used_accum_lb") or 0.0)), 1)
    state["fuel_last_lb"] = current_fuel
    state["fuel_last_source"] = source_now


def _analyse(meta: dict[str, Any], current: dict[str, Any], previous: dict[str, Any] | None) -> bool:
    now = current["time"]; state = meta.setdefault("_state", {}); metrics = meta.setdefault("metrics", {}); times = meta.setdefault("times", {}); fuel = meta.setdefault("fuel", {})
    airport = _airport_at(current); gs = current.get("ground_speed_kts") or 0.0; vs = current.get("vertical_speed_fpm") or 0.0; agl = current.get("agl_ft")
    previous_phase = state.get("phase")
    pushback_observed = _gsx_pushback_active() or _backward_motion_active(current)
    pushback_explicit_clear = bool(getattr(_gsx_pushback_active, "_last_explicit_clear", False))
    pushback_latched = bool(state.get("pushback_positive_latch") or state.get("pushback_active"))
    if pushback_observed and not state.get("pushback_forward_taxi_proven"):
        # Positive dedicated evidence is durable within this recording.  Cache
        # misses and unavailable GSX samples are intentionally not clear signals.
        pushback_latched = True
        state["pushback_positive_latch"] = True
        state["pushback_active"] = True
        state["pushback_seen"] = True
    elif pushback_explicit_clear and pushback_latched:
        pushback_latched = False
        state["pushback_positive_latch"] = False
        state["pushback_active"] = False
        state["pushback_completed"] = True
        state["pushback_completed_at"] = now

    # #56: a GSX-active pushback row while parked with the brake set is a
    # schedule artifact (the tug is *scheduled*, not pushing), not a physical
    # pushback. Record real physical movement on a latched pushback so the
    # completion cues below can never be fooled by a parked sample.
    if pushback_latched and (gs or 0.0) >= 1.5:
        state["pushback_movement_seen"] = True

    # #42: phase-ordering invariant — the aircraft cannot taxi out before off
    # blocks. Any ground movement out of PARKED before block-out is a pushback.
    # Fenix is blind to the dedicated signals (no body-vx, track == heading),
    # so this fallback is deliberately signal-independent.
    if (not pushback_latched and not state.get("pushback_forward_taxi_proven")
            and not times.get("block_out")
            and current.get("on_ground") is not False
            and (gs or 0.0) >= 1.5
            and (previous_phase == "PARKED" or previous_phase is None)):
        pushback_latched = True
        state["pushback_positive_latch"] = True
        state["pushback_active"] = True
        state["pushback_seen"] = True

    # Independent TAXI OUT proof is evaluated even if GSX still reports a stale
    # pushback row. Forward movement at normal taxi speed with the brake released
    # and real displacement is stronger physical evidence than a cached service
    # state. This normally resolves TAXI OUT within 5-8 seconds.
    grounded = current.get("on_ground") is not False
    brake_released = current.get("parking_brake") is False
    candidate = state.get("taxi_motion_candidate") if isinstance(state.get("taxi_motion_candidate"), dict) else None
    now_epoch = _epoch(now) or time.time()
    taxi_speed = float(gs or 0.0)

    # Fast taxi-out override: ground speed above the tug envelope with forward
    # motion evidence is real taxi movement and overrides any stale GSX
    # pushback state.  A tug pushing an aircraft stays below ~10 kt and pushes
    # it backward — so a forward-moving sample above the envelope proves the
    # aircraft is taxiing under its own power (v0.25.72, #12: gate raised from
    # 5 kt and now direction-gated so a 6-7 kt pushback sample can never
    # demote a latched pushback).
    forward_motion = _forward_motion_evidence(current)
    gs_counter = int(state.get("taxi_out_gs_counter") or 0)
    # #42: the fast override needs EXPLICIT forward proof (forward_motion is
    # True), not just "not known backward". On the Fenix the direction is
    # unknown (track mirrors heading, no body-vx), so only the sustained-motion
    # override (>=5 s + real displacement) may end a latched pushback — a
    # 10-12 kt pushback spike can never clear it.
    if grounded and brake_released and taxi_speed > 10.0 and forward_motion is True:
        gs_counter += 1
        state["taxi_out_gs_counter"] = gs_counter
        if gs_counter >= 1 and pushback_latched:
            state["pushback_completed"] = True
            state["pushback_completed_at"] = now
            if not state.get("taxi_out_gs_logged"):
                _event(meta, "TAXI OUT", f"Taxi-out confirmed (GS >10kt, forward motion); overriding stale pushback", now)
                state["taxi_out_gs_logged"] = True
            state["pushback_forward_taxi_proven"] = True
            state["pushback_movement_seen"] = True
            pushback_latched = False
            state["pushback_positive_latch"] = False
            state["pushback_active"] = False
    else:
        gs_counter = 0
        state["taxi_out_gs_counter"] = gs_counter

    if grounded and brake_released and taxi_speed > 5.0:
        if candidate is None:
            candidate = {"epoch": now_epoch, "lat": current.get("lat"), "lon": current.get("lon"), "max_speed": taxi_speed}
            state["taxi_motion_candidate"] = candidate
        candidate["max_speed"] = max(float(candidate.get("max_speed") or 0.0), taxi_speed)
        elapsed = max(0.0, now_epoch - float(candidate.get("epoch") or now_epoch))
        distance_nm = None
        if None not in (_number(candidate.get("lat")), _number(candidate.get("lon")), _number(current.get("lat")), _number(current.get("lon"))):
            distance_nm = haversine_nm(float(candidate["lat"]), float(candidate["lon"]), float(current["lat"]), float(current["lon"]))
        # A tug normally remains below ordinary taxi speed. At >=8 kt, five
        # seconds plus displacement can override even a stale dedicated row.
        taxi_proven = elapsed >= 5.0 and ((distance_nm is not None and distance_nm >= 0.010) or (distance_nm is None and elapsed >= 8.0))
        stale_override = taxi_proven and (not pushback_observed or float(candidate.get("max_speed") or 0.0) >= 8.0)
        if stale_override:
            if pushback_latched or state.get("pushback_seen"):
                state["pushback_completed"] = True
                state["pushback_completed_at"] = now
                if not state.get("taxi_out_motion_logged"):
                    _event(meta, "TAXI OUT", f"Forward taxi movement confirmed ({taxi_speed:.1f} kt); stale GSX pushback state ignored", now)
                    state["taxi_out_motion_logged"] = True
                state["pushback_forward_taxi_proven"] = True
                state["pushback_movement_seen"] = True
            pushback_latched = False
            state["pushback_positive_latch"] = False
            state["pushback_active"] = False
    elif taxi_speed < 1.2 or current.get("parking_brake") is True:
        state.pop("taxi_motion_candidate", None)
        if pushback_latched and current.get("parking_brake") is True:
            if state.get("pushback_movement_seen"):
                # #42: movement -> full stop -> parking brakes set = pushback
                # complete (the pilot always parks the aircraft after the tug
                # releases). Next ground movement is genuine taxi.
                state["pushback_completed"] = True
                state["pushback_completed_at"] = now
                state["pushback_forward_taxi_proven"] = True
                pushback_latched = False
                state["pushback_positive_latch"] = False
                state["pushback_active"] = False
            else:
                # #56: the GSX-active row at flight start (tug *scheduled*, not
                # pushing) latches on a parked sample with the brake set. No
                # physical movement ever happened, so this is NOT pushback
                # completion — drop the latch without stamping forward-taxi
                # proof. The #42 ordering invariant re-latches on the first real
                # movement (gs >= 1.5) and the phase machine yields PUSHBACK.
                pushback_latched = False
                state.pop("pushback_positive_latch", None)
                state.pop("pushback_active", None)

    current["pushback_active"] = bool(pushback_latched)
    if _sample_ground_safe(current) and not _airborne_candidate(current):
        current["on_ground"] = True
        current["ground_safe"] = True
        current["confirmed_airborne"] = False
    # Ground refuelling raises the baseline until block-out; after block-out,
    # only sample-to-sample decreases count as burn.
    _update_fuel_accounting(meta, current)
    recent = state.setdefault("recent_samples", [])
    recent.append(dict(current)); del recent[:-45]
    airborne_confirmed = _confirmed_airborne_from_recent(recent)
    current["confirmed_airborne"] = bool(airborne_confirmed)
    if airborne_confirmed:
        if not state.get("airborne_started_epoch"):
            state["airborne_started_epoch"] = _epoch(now) or 0.0
        state["airborne_elapsed_s"] = max(0.0, (_epoch(now) or 0.0) - float(state.get("airborne_started_epoch") or 0.0))
    current["ground_safe"] = bool(_sample_ground_safe(current) and not airborne_confirmed)
    if current["ground_safe"]:
        current["on_ground"] = True
    if recent:
        recent[-1].update({"confirmed_airborne": current["confirmed_airborne"], "ground_safe": current["ground_safe"], "on_ground": current.get("on_ground")})
    phase = _phase(current, meta)
    previous_phase_upper = str(previous_phase or "").upper()
    if current.get("confirmed_airborne") and previous_phase_upper in {"TAXI OUT", "TAKEOFF ROLL", "PUSHBACK"}:
        phase = "TAKEOFF"
        _event(meta, "PHASE_RECOVERY", f"from={previous_phase} to=TAKEOFF reason=airborne_detected", now)
    elif current.get("confirmed_airborne") and previous_phase_upper == "TAKEOFF" and (float(vs or 0.0) > 150.0 or float(agl or 0.0) >= 600.0):
        phase = "CLIMB"
    elif current.get("confirmed_airborne") and previous_phase_upper in {"TAKEOFF", "INITIAL CLIMB", "CLIMB"} and float(state.get("airborne_elapsed_s") or 0.0) >= 90.0 and float(agl or 0.0) >= 2500.0 and abs(float(vs or 0.0)) < 500.0:
        phase = "ENROUTE"
    if phase == "TELEMETRY UNCERTAIN":
        state["telemetry_uncertain"] = True
        phase = str(previous_phase or "PARKED")
    if not _phase_transition_allowed(str(previous_phase) if previous_phase else None, phase):
        reason = "too_soon_after_takeoff" if str(previous_phase or "").upper() in {"TAKEOFF", "TAKEOFF ROLL", "INITIAL CLIMB"} and phase in {"DESCENT CANDIDATE", "DESCENT"} else "impossible_transition"
        last_reject = state.get("last_phase_reject") or {}
        if last_reject.get("from") != previous_phase or last_reject.get("to") != phase or ((_epoch(now) or 0) - float(last_reject.get("epoch") or 0)) > 30:
            _event(meta, "PHASE_REJECTED", f"from={previous_phase} to={phase} reason={reason}", now, "warning")
            state["last_phase_reject"] = {"from": previous_phase, "to": phase, "epoch": _epoch(now) or 0}
        phase = str(previous_phase or "PARKED")
    elif phase != previous_phase and previous_phase:
        reason = "climb_confirmed" if phase == "CLIMB" and previous_phase_upper in {"TAKEOFF", "INITIAL CLIMB"} else ("enroute_confirmed" if phase == "ENROUTE" and previous_phase_upper in {"CLIMB", "INITIAL CLIMB", "TAKEOFF"} else "validated_transition")
        _event(meta, "PHASE_ACCEPTED", f"from={previous_phase} to={phase} reason={reason}", now)
    current["phase"] = phase
    if recent:
        recent[-1]["phase"] = phase
    if phase != previous_phase:
        state["phase"] = phase; _event(meta, phase, f"Flight phase changed to {phase}", now)
    if phase == "APPROACH": state["approach_seen"] = True
    if state.get("approach_seen") and phase in {"GO-AROUND", "MISSED APPROACH", "CLIMB", "INITIAL CLIMB"} and not times.get("landing") and vs > 500:
        if not state.get("go_around_recorded"):
            state["go_around_recorded"] = True; _event(meta, "GO-AROUND", "Climb detected after an established approach", now, "warning")

    for key, val, mode in (("max_altitude_ft", current.get("altitude_ft"), "max"), ("max_ias_kts", current.get("ias_kts"), "max"), ("max_ground_speed_kts", gs, "max"), ("max_climb_fpm", vs, "max"), ("max_descent_fpm", vs, "min")):
        if val is not None:
            old = _number(metrics.get(key)); metrics[key] = val if old is None else (max(old, val) if mode == "max" else min(old, val))
    bank = abs(current.get("bank_deg") or 0.0); metrics["max_bank_deg"] = max(_number(metrics.get("max_bank_deg")) or 0.0, bank)
    g = current.get("g_force")
    if g is not None:
        metrics["max_g"] = max(_number(metrics.get("max_g")) or g, g); metrics["min_g"] = min(_number(metrics.get("min_g")) or g, g)

    if previous and None not in (previous.get("lat"), previous.get("lon"), current.get("lat"), current.get("lon")):
        delta = haversine_nm(previous["lat"], previous["lon"], current["lat"], current["lon"])
        dt = max(0.1, (_epoch(now) or 0) - (_epoch(previous.get("time")) or 0))
        expected = max(previous.get("ground_speed_kts") or 0, gs) * dt / 3600
        if delta <= max(2.0, expected * 5 + .5):
            metrics["distance_nm"] = round((_number(metrics.get("distance_nm")) or 0) + delta, 2)
        else:
            state["last_path_filter"] = f"ignored path jump {delta:.1f} nm"

    route = (meta.get("flight") or {}).get("navlog") or []
    if current.get("lat") is not None and current.get("lon") is not None and len(route) > 1:
        xte = _route_xte_nm(current["lat"], current["lon"], route)
        if xte is not None:
            current["cross_track_nm"] = round(xte, 2)
            state["cross_track_sum"] = (state.get("cross_track_sum") or 0) + xte; state["cross_track_count"] = (state.get("cross_track_count") or 0) + 1
            metrics["max_cross_track_nm"] = max(_number(metrics.get("max_cross_track_nm")) or 0, xte)
            metrics["average_cross_track_nm"] = round(state["cross_track_sum"] / state["cross_track_count"], 2)

    systems_moving = current.get("engines_running") or current.get("parking_brake") is False
    # #42: BLOCK OUT stays at FIRST movement — including the start of a pushback.
    # The user confirmed off-blocks firing at pushback start (14:36Z) is correct,
    # and the phase-ordering invariant guarantees "taxi out" can never precede
    # it. The confirmed_airborne branch is intentionally never gated here.
    if not times.get("block_out") and ((current.get("confirmed_airborne") and not _gsx_predeparture_active()) or (current.get("on_ground") is True and gs >= 1.5 and systems_moving)):
        times["block_out"] = now; _out_snapshots = meta.setdefault("operational_snapshots", {}); _out_snapshots.setdefault("out", _op_snapshot(current, now)); _event(meta, "BLOCK OUT", f"Movement began near {(airport or {}).get('icao','unknown station')}", now)
    previous_ground = previous.get("on_ground") if previous else None
    previous_airborne = bool(previous and previous.get("confirmed_airborne"))
    if not times.get("takeoff") and current.get("confirmed_airborne"):
        times["takeoff"] = now; meta["positions"]["takeoff"] = {"lat": current.get("lat"), "lon": current.get("lon"), "altitude_ft": current.get("altitude_ft")}; meta["airports"]["takeoff"] = airport; fuel["takeoff_lb"] = current.get("fuel_total_lb"); meta["operational_snapshots"]["off"] = _op_snapshot(current, now); state["airborne_seen"] = True; state["confirmed_airborne_seen"] = True
        _event(meta, "TAKEOFF", f"Airborne near {(airport or {}).get('icao','departure')}", now)
    if current.get("confirmed_airborne"):
        state["airborne_seen"] = True; state["confirmed_airborne_seen"] = True
    if times.get("landing") and not current.get("on_ground"):
        agl_now = _number(current.get("raw_radio_altitude_ft")) or _number(current.get("radio_altitude_ft")) or _number(current.get("agl_ft")) or 0.0
        state["post_touchdown_airborne_peak_agl_ft"] = max(float(state.get("post_touchdown_airborne_peak_agl_ft") or 0.0), float(agl_now))
    if state.get("airborne_seen") and current.get("on_ground") and (previous_ground is False or previous_airborne):
        if not times.get("landing"):
            metrics["touchdowns"] = 1
        airborne_rates = []
        for row in state.get("recent_samples", []):
            if row.get("on_ground"):
                continue
            value = _number(row.get("raw_vertical_speed_fpm"))
            if value is None:
                value = _number(row.get("vertical_speed_fpm"))
            if value is not None and -3000 <= float(value) <= 500:
                airborne_rates.append(value)
        rate = None
        if airborne_rates:
            last_rates = airborne_rates[-5:]
            rate = sorted(last_rates)[len(last_rates)//2]
        if rate is None:
            rate = (_number(previous.get("raw_vertical_speed_fpm")) or previous.get("vertical_speed_fpm")) if previous else (_number(current.get("raw_vertical_speed_fpm")) or vs)
        g_values = [(_number(x.get("raw_g_force")) if _number(x.get("raw_g_force")) is not None else _number(x.get("g_force"))) for x in state.get("recent_samples", [])[-8:]]
        g_values.append(_number(current.get("raw_g_force")) if _number(current.get("raw_g_force")) is not None else _number(current.get("g_force")))
        g_values = [g for g in g_values if g is not None and 0.2 <= g <= 4.0]
        touchdown_g = max(g_values) if g_values else current.get("g_force")
        if not times.get("landing"):
            touchdown_attitude = previous if isinstance(previous, dict) and not bool(previous.get("on_ground")) else current
            touchdown_position = current if None not in (_number(current.get("lat")), _number(current.get("lon"))) else touchdown_attitude
            times["landing"] = now
            meta["positions"]["landing"] = {
                "lat": touchdown_position.get("lat"),
                "lon": touchdown_position.get("lon"),
                "altitude_ft": touchdown_position.get("altitude_ft"),
            }
            meta["airports"]["landing"] = airport
            fuel["landing_lb"] = current.get("fuel_total_lb")
            meta["operational_snapshots"]["on"] = _op_snapshot(current, now)
            touchdown_speed = (_number(previous.get("raw_ground_speed_kts")) or previous.get("ground_speed_kts")) if previous else (_number(current.get("raw_ground_speed_kts")) or gs)
            metrics["landing_rate_fpm"] = rate
            metrics["touchdown_speed_kts"] = touchdown_speed
            metrics["touchdown_g"] = touchdown_g
            metrics["touchdown_pitch_deg"] = _number(touchdown_attitude.get("pitch_deg"))
            metrics["touchdown_bank_deg"] = _number(touchdown_attitude.get("bank_deg"))
            metrics["touchdown_sample"] = {
                "time": now,
                "lat": touchdown_position.get("lat"),
                "lon": touchdown_position.get("lon"),
                "altitude_ft": touchdown_position.get("altitude_ft"),
                "pitch_deg": metrics.get("touchdown_pitch_deg"),
                "bank_deg": metrics.get("touchdown_bank_deg"),
                "ground_speed_kts": touchdown_speed,
            }
            _event(meta, "LANDING", f"Touchdown near {(airport or {}).get('icao','destination')} at {round(rate or 0)} fpm", now)
        else:
            peak_agl = float(state.pop("post_touchdown_airborne_peak_agl_ft", 0.0) or 0.0)
            wow_confirmed = previous.get("weight_on_wheels") is False if previous else False
            # Ignore 1–2 ft radio-altimeter noise. A second contact requires a
            # meaningful rebound or an explicit WOW-off sample.
            if peak_agl >= 3.0 or wow_confirmed:
                bounce_count = int(metrics.get("bounce_count") or 0) + 1
                metrics["bounce_count"] = bounce_count
                metrics["touchdowns"] = int(metrics.get("touchdowns") or 1) + 1
                severity = "SEVERE" if peak_agl >= 12.0 or bounce_count >= 3 else "MODERATE" if peak_agl >= 5.0 else "MINOR"
                penalty = {"MINOR": 2, "MODERATE": 5, "SEVERE": 8}[severity]
                remaining = max(0, 12 - int(metrics.get("bounce_penalty") or 0))
                applied = min(penalty, remaining)
                metrics["bounce_penalty"] = int(metrics.get("bounce_penalty") or 0) + applied
                metrics["bounce_severity"] = severity
                _event(meta, "BOUNCE", f"{severity.lower()} rebound {peak_agl:.1f} ft; penalty -{applied}", now, "warning")
                if applied:
                    _violation(meta, f"bounce-{bounce_count}", "BOUNCED LANDING", f"{severity.title()} rebound after touchdown ({peak_agl:.1f} ft)", applied, now)

    landing_epoch = _epoch(times.get("landing"))
    now_epoch = _epoch(now)
    if landing_epoch and now_epoch and 0 <= now_epoch - landing_epoch <= 1.2:
        g_now = _number(current.get("g_force"))
        if g_now is not None and 0.2 <= g_now <= 4.0:
            old_g = _number(metrics.get("touchdown_g"))
            metrics["touchdown_g"] = max(old_g if old_g is not None else g_now, g_now)

    altitude = _number(current.get("altitude_ft"))
    ias = _number(current.get("ias_kts"))
    agl_for_speed = _number(current.get("radio_altitude_ft")) or _number(current.get("agl_ft"))
    if _altitude_reliable(current) and altitude is not None and ias is not None and current.get("confirmed_airborne") and altitude < 10000 and ias > 255:
        _violation(meta, "speed-below-10k", "SPEED BELOW 10,000 FT", f"IAS reached {round(ias)} kt", 4, now)
    elif not _altitude_reliable(current) and ias is not None and ias > 255 and agl_for_speed is not None and agl_for_speed > 10000:
        state["last_suppressed_deviation"] = "speed-below-10k suppressed because altitude source was unreliable but AGL was above 10,000 ft"
    if current.get("on_ground") and gs > 35 and phase not in {"TAKEOFF ROLL", "LANDING ROLL", "PUSHBACK"}: _violation(meta, "taxi-speed", "EXCESSIVE TAXI SPEED", f"Ground speed reached {round(gs)} kt", 3, now)
    if current.get("overspeed_warning"): _violation(meta, "overspeed", "OVERSPEED WARNING", "Simulator overspeed warning was active", 10, now)
    if current.get("stall_warning"): _violation(meta, "stall", "STALL WARNING", "Simulator stall warning was active", 20, now)
    if current.get("slew_active"): _violation(meta, "slew", "SLEW MODE", "Slew mode was used during the recording", 20, now)
    if current.get("paused"): _violation(meta, "pause", "SIMULATION PAUSED", "A pause or position freeze was detected", 1, now)
    if abs((current.get("sim_rate") or 1) - 1) > .05: _violation(meta, "sim-rate", "SIMULATION RATE", f"Simulation rate was {current.get('sim_rate'):.2f}x", 4, now)
    if bank > (25 if agl is not None and agl < 1000 else 60): _violation(meta, "bank", "EXCESSIVE BANK", f"Bank angle reached {bank:.1f}°", 4, now)
    pitch = current.get("pitch_deg")
    if pitch is not None and (pitch > 30 or pitch < -20): _violation(meta, "pitch", "EXCESSIVE PITCH", f"Pitch reached {pitch:.1f}°", 4, now)
    if phase == "APPROACH" and agl is not None and agl < 1000:
        unstable = []
        if vs < -1100: unstable.append(f"VS {round(vs)} fpm")
        if bank > 20: unstable.append(f"bank {bank:.0f}°")
        if (current.get("gear_percent") is not None and current.get("gear_percent") < 90): unstable.append("gear not down")
        if unstable: _violation(meta, "unstable-approach", "UNSTABLE APPROACH", ", ".join(unstable), 6, now)
    if previous and current.get("fuel_total_lb") is not None and previous.get("fuel_total_lb") is not None:
        increase = current["fuel_total_lb"] - previous["fuel_total_lb"]
        same_source = str(current.get("source") or "") == str(previous.get("source") or "")
        if times.get("block_out") and current.get("confirmed_airborne") and same_source and increase > max(100, previous["fuel_total_lb"] * .01):
            _violation(meta, "refuelling", "IN-FLIGHT FUEL INCREASE", f"Fuel increased by approximately {round(increase)} lb", 15, now)
        if current.get("confirmed_airborne") and previous["fuel_total_lb"] > 50 and current["fuel_total_lb"] <= 1:
            _violation(meta, "fuel-exhaustion", "FUEL EXHAUSTION", "Usable fuel reached zero while airborne", 30, now)

    state["last_sample"] = current
    if times.get("landing") and current.get("on_ground") and gs < 1 and current.get("parking_brake") is True and current.get("engines_running") is False:
        if not times.get("block_in"):
            times["block_in"] = now; meta["airports"]["end"] = airport; meta["positions"]["end"] = {"lat": current.get("lat"), "lon": current.get("lon"), "altitude_ft": current.get("altitude_ft")}; fuel["end_lb"] = current.get("fuel_total_lb"); meta["operational_snapshots"]["in"] = _op_snapshot(current, now)
            _event(meta, "BLOCK IN", f"Aircraft parked at {(airport or {}).get('icao','destination')}", now)
        return True
    return False


def _grade(rate: Any) -> str:
    value = abs(_number(rate) or 0)
    if not value: return "NOT RECORDED"
    if value <= 100: return "EXCELLENT"
    if value <= 200: return "GOOD"
    if value <= 300: return "ACCEPTABLE"
    if value <= 450: return "FIRM"
    return "HARD"


def _score(meta: dict[str, Any]) -> int:
    times = meta.get("times") or {}; base = 70 + (8 if times.get("block_out") else 0) + (8 if times.get("takeoff") else 0) + (8 if times.get("landing") else 0) + (6 if times.get("block_in") else 0)
    rate = abs(_number((meta.get("metrics") or {}).get("landing_rate_fpm")) or 0)
    if rate: base += 8 if rate <= 200 else 4 if rate <= 350 else 0 if rate <= 500 else -8
    penalties = sum(int(v.get("penalty") or 0) for v in meta.get("violations") or [])
    return max(0, min(100, int(base - penalties)))


def _save_flight(meta: dict[str, Any], status_value: str | None = None) -> None:
    meta["updated_utc"] = _utc_now()
    clean = dict(meta)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO flights(id,started_utc,completed_utc,status,metadata_json,rating,notes,updated_utc)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                started_utc=excluded.started_utc,
                completed_utc=excluded.completed_utc,
                status=excluded.status,
                metadata_json=excluded.metadata_json,
                rating=excluded.rating,
                notes=excluded.notes,
                updated_utc=excluded.updated_utc
            """,
            (meta["id"], meta["started_utc"], meta.get("completed_utc"), status_value or meta.get("state") or "RECORDING", json.dumps(clean, separators=(",", ":"), ensure_ascii=False), int(meta.get("rating") or 0), str(meta.get("notes") or ""), meta["updated_utc"]),
        )


def _insert_sample(flight_id: str, sample: dict[str, Any], started_utc: str) -> None:
    elapsed = max(0.0, (_epoch(sample["time"]) or 0) - (_epoch(started_utc) or 0))
    with _connect() as conn:
        conn.execute("INSERT INTO samples(flight_id,sampled_utc,elapsed_seconds,data_json) VALUES(?,?,?,?)", (flight_id, sample["time"], elapsed, json.dumps(sample, separators=(",", ":"))))


def _active_row() -> tuple[sqlite3.Row, dict[str, Any]] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM flights WHERE status='RECORDING' ORDER BY started_utc DESC LIMIT 1").fetchone()
    if not row: return None
    return row, json.loads(row["metadata_json"])


def get_active_recorder() -> dict[str, Any] | None:
    """Return the active recorder's metadata dict (or None).

    Public read-only accessor used by the live OFP endpoint; never mutates
    recorder state.
    """
    row = _active_row()
    if not row:
        return None
    _db_row, meta = row
    return meta


def _boarding_started() -> bool:
    try:
        from .announcements import boarding_phase_active
        return bool(boarding_phase_active())
    except Exception:
        return False


def _apu_running(systems: dict[str, Any]) -> bool:
    """Best-available APU-running detection from the telemetry ``systems`` dict.

    The core FSUIPC/SimConnect provider does not currently expose a dedicated APU
    field (telemetry ``systems`` carries parking_brake, engines_running and
    engine1..4_running only). Rather than invent a field, this reads the APU
    defensively across the plausible names an add-on/SDK provider could surface:
    a boolean apu/apu_running/apu_master/apu_generator, or an APU speed
    (apu_n1_percent / apu_n_percent / apu_rpm_percent) at/above a running
    threshold. When no APU field is present it returns False and behaviour is
    unchanged.
    """
    if not isinstance(systems, dict):
        return False
    for key in ("apu_running", "apu_avail", "apu_available", "apu_generator", "apu_gen", "apu_master", "apu_on", "apu"):
        if systems.get(key) is True:
            return True
    for key in ("apu_n1_percent", "apu_n2_percent", "apu_n_percent", "apu_rpm_percent", "apu_rpm"):
        n = _number(systems.get(key))
        if n is not None and n >= 80.0:
            return True
    return False


def _powered_or_user_ready(t: dict[str, Any]) -> bool:
    systems = t.get("systems") if isinstance(t.get("systems"), dict) else {}
    # Do not treat beacon, parking brake release, restored FSUIPC telemetry or
    # small loading-screen movement as flight intent. Auto recording starts only
    # after GSX/OPS ROOM boarding has begun, the APU is running, or an engine is
    # actually running.
    return bool(systems.get("engines_running") or _apu_running(systems) or _boarding_started())


def _telemetry_ready(t: dict[str, Any]) -> bool:
    if t.get("telemetry_hold"):
        return
    if not t.get("ok") or t.get("telemetry_complete") is False or t.get("telemetry_fresh") is False or t.get("stale"):
        _STANDBY_SAMPLES.clear(); return False
    probe = _sample(t, _utc_now())
    complete, _ = _sample_complete_for_recording(probe)
    if not complete:
        _STANDBY_SAMPLES.clear(); return False
    lat, lon = _number(t.get("lat")), _number(t.get("lon"))
    if lat is None or lon is None or abs(lat) < 0.001 and abs(lon) < 0.001:
        _STANDBY_SAMPLES.clear(); return False
    gs = _number(t.get("ground_speed_kts")) or 0.0
    agl = _number(t.get("agl_ft"))
    # Ignore airborne/teleport starts unless the user manually starts recording.
    if not bool(t.get("on_ground", True)) and (agl is None or agl > 80):
        _STANDBY_SAMPLES.clear(); return False
    sample = {"lat": lat, "lon": lon, "time": time.monotonic(), "on_ground": bool(t.get("on_ground", True)), "gs": gs}
    _STANDBY_SAMPLES.append(sample); del _STANDBY_SAMPLES[:-8]
    if len(_STANDBY_SAMPLES) < 4:
        return False
    # Must be stable and plausibly loaded into the sim, not a loading transition.
    span = haversine_nm(_STANDBY_SAMPLES[0]["lat"], _STANDBY_SAMPLES[0]["lon"], _STANDBY_SAMPLES[-1]["lat"], _STANDBY_SAMPLES[-1]["lon"])
    stable_ground = all(x["on_ground"] for x in _STANDBY_SAMPLES[-4:]) and span < 0.08
    return bool(stable_ground or _powered_or_user_ready(t))


def _origin_gate_ok(t: dict[str, Any], plan: dict[str, Any] | None) -> bool:
    """Hard gate against loading-screen/teleport starts.

    If a SimBrief OFP is loaded, auto-recording is allowed only when the
    aircraft is physically near the planned origin. Without an OFP we still
    allow recording, but only after _telemetry_ready has proven stable ground
    samples and the aircraft is powered/ready.
    """
    origin_code = _text(((plan or {}).get("origin") or {}).get("icao"), 4).upper() if isinstance((plan or {}).get("origin"), dict) else ""
    if not origin_code:
        return True
    lat, lon = _number(t.get("lat")), _number(t.get("lon"))
    if lat is None or lon is None:
        return False
    airport = load_airports().get(origin_code)
    if not airport:
        return True
    return haversine_nm(lat, lon, airport.lat, airport.lon) <= 8.0


def _valid_recording_sample(current: dict[str, Any], previous: dict[str, Any] | None) -> tuple[bool, str]:
    complete, reason = _sample_complete_for_recording(current)
    if not complete:
        return False, reason
    if current.get("slew_active"):
        return False, "slew mode active"
    # Do not reject a whole recorder sample because of a position/altitude jump.
    # Those checks are path-analysis filters only. Rejecting the whole sample
    # froze fuel, phase and live status when the previous position was stale.
    return True, ""


def _replay_guarded() -> bool:
    try:
        from .replay_guard import is_active
        return bool(is_active())
    except Exception:
        return False


def _should_start(t: dict[str, Any]) -> bool:
    if _replay_guarded():
        return False
    if not _telemetry_ready(t):
        return False
    if not bool(t.get("on_ground", True)):
        return False
    gs = _number(t.get("ground_speed_kts")) or 0.0
    systems = t.get("systems") if isinstance(t.get("systems"), dict) else {}
    brake = systems.get("parking_brake_set")
    if brake is None:
        brake = systems.get("parking_brake")
    movement_valid = gs >= 2.5 and (_powered_or_user_ready(t) or brake is False)
    if not movement_valid:
        return False
    plan = _current_plan()
    if _origin_gate_ok(t, plan):
        return True
    # If origin matching is uncertain/wrong but the aircraft is clearly taxiing
    # with valid live telemetry, allow the recorder to start instead of silently
    # missing the flight. The reason stays internal in the logbook events.
    if gs >= 8.0 and (_powered_or_user_ready(t) or brake is False):
        return True
    return False


def _start(t: dict[str, Any], manual: bool) -> dict[str, Any]:
    if _replay_guarded():
        return {"ok": False, "replay_suppressed": True, "reason": "In-simulator replay is active"}
    existing = _active_row()
    if existing: return existing[1]
    reset_source_lock("new recorder session")
    fresh = read_telemetry(True)
    if fresh.get("ok") and fresh.get("telemetry_complete") is not False:
        t = fresh
    meta = _new_meta(t, _current_plan(), manual)
    meta.setdefault("_state", {})["path_baseline_reset"] = True
    _save_flight(meta, "RECORDING")
    _insert_sample(meta["id"], _sample(t, meta["started_utc"]), meta["started_utc"])
    return meta


def _finalize(meta: dict[str, Any], reason: str, t: dict[str, Any] | None = None) -> dict[str, Any]:
    now = _utc_now(); times = meta.setdefault("times", {}); fuel = meta.setdefault("fuel", {})
    if not times.get("block_in"): times["block_in"] = now
    if t and t.get("ok"):
        meta["airports"]["end"] = _airport_at(t); meta["positions"]["end"] = _position(t); fuel["end_lb"] = _number(t.get("fuel_total_lb"))
    state = meta.get("_state") or {}; last = state.get("last_sample") or {}
    if fuel.get("end_lb") is None: fuel["end_lb"] = _number(last.get("fuel_total_lb"))
    flight = meta.setdefault("flight", {}); airports = meta.get("airports") or {}
    if not flight.get("origin"): flight["origin"] = _text(((airports.get("takeoff") or airports.get("start") or {}).get("icao")), 4).upper()
    if not flight.get("destination"): flight["destination"] = _text(((airports.get("landing") or airports.get("end") or {}).get("icao")), 4).upper()
    a, b = _number(fuel.get("departure_baseline_lb") or fuel.get("start_lb")), _number(fuel.get("end_lb"))
    accumulated = _number(fuel.get("used_lb"))
    if accumulated is None:
        accumulated = round(max(0, a-b), 1) if a is not None and b is not None else None
    fuel["used_lb"] = accumulated
    meta["completed_utc"] = now; meta["completion_reason"] = reason; meta["state"] = "COMPLETE" if times.get("takeoff") and times.get("landing") and _elapsed(times.get("takeoff"), times.get("landing")) and _elapsed(times.get("takeoff"), times.get("landing")) >= 60 else "INCOMPLETE"
    meta["durations"] = {"block_seconds": _elapsed(times.get("block_out") or meta.get("started_utc"), times.get("block_in")), "airborne_seconds": _elapsed(times.get("takeoff"), times.get("landing"))}
    meta["debrief"] = {"score": _score(meta), "landing_grade": _grade((meta.get("metrics") or {}).get("landing_rate_fpm")), "scoring_model": "OPS ROOM PIREP PRO V1"}
    _event(meta, "COMPLETED", f"Flight record closed ({reason})", now)
    meta.pop("_state", None); _save_flight(meta, meta["state"])
    # Replay-blocking fix: closing the logbook flight must also close the Black
    # Box recorder for the same flight. Previously the recorder only stopped via
    # the 120s on-blocks autostop, so a manual completion (or an app restart
    # that stalled the engine loop) left it recording for hours — and every
    # in-sim replay attempt returned 409 "Stop the active Black Box recording".
    try:
        from .black_box import status as _bb_status, stop_recording as _bb_stop
        bb = _bb_status()
        if bb.get("recording") and str((bb.get("active") or {}).get("flight_id") or "") == str(meta.get("id") or ""):
            _bb_stop("FLIGHT FINALIZED")
    except Exception:
        pass
    try:
        analysis = analyse_pirep(meta, _raw_samples(meta["id"]))
        if analysis.get("ok"):
            meta["analysis_summary"] = analysis
            landing_analysis = analysis.get("landing") if isinstance(analysis.get("landing"), dict) else {}
            metrics = meta.setdefault("metrics", {})
            for target, source in (
                ("touchdown_distance_ft", "touchdown_distance_ft"),
                ("touchdown_centerline_deviation_ft", "touchdown_centerline_deviation_ft"),
                ("rollout_distance_ft", "rollout_distance_ft"),
            ):
                value = _number(landing_analysis.get(source))
                if value is not None:
                    metrics[target] = value
            if _number(metrics.get("touchdown_pitch_deg")) is None:
                metrics["touchdown_pitch_deg"] = _number(landing_analysis.get("touchdown_pitch_deg"))
            if _number(metrics.get("touchdown_bank_deg")) is None:
                metrics["touchdown_bank_deg"] = _number(landing_analysis.get("touchdown_bank_deg"))
            meta["debrief"]["score"] = int((analysis.get("score") or {}).get("overall") or meta["debrief"]["score"])
            meta["debrief"]["landing_grade"] = str((analysis.get("score") or {}).get("grade") or meta["debrief"]["landing_grade"])
            meta["debrief"]["score_breakdown"] = (analysis.get("score") or {}).get("breakdown") or {}
            _save_flight(meta, meta["state"])
    except Exception:
        pass
    invoices = _matching_gsx_receipts(meta)
    if invoices:
        meta["gsx_invoices"] = invoices
    try:
        from .economy import finance_enabled, post_flight
        # Previous entries are used only for rank/pay context. The finance
        # poster is idempotent by flight id, so manual finalization retries do
        # not double-credit a career. Disabled careers preserve historical data
        # but do not add a finance section to this PIREP.
        if finance_enabled():
            post_flight(meta, _rows("", 5000))
        else:
            meta.pop("finance", None)
        _save_flight(meta, meta["state"])
    except Exception as exc:
        meta.setdefault("finance", {"ok": False, "reason": f"{type(exc).__name__}: {exc}"})
        _save_flight(meta, meta["state"])
    return meta


def _arrival_services_complete_for_record() -> bool:
    """Return True when post-arrival GSX automation has actually finished.

    Flight finance must wait for arrival/turnaround invoices where possible, so
    block-in is not enough to close the PIREP automatically.
    """
    try:
        from .gsx_remote import automation_status
        status = automation_status()
    except Exception:
        return False
    mode = str(status.get("mode") or "").upper()
    if mode not in {"ARRIVAL", "FULL_TURNAROUND"}:
        return False
    latches = status.get("latches") if isinstance(status.get("latches"), dict) else {}
    if not (latches.get("deboarding_complete") or latches.get("deboarding_deferred_or_skipped")):
        return False
    required = ("cleaning", "lavatory")
    for key in required:
        if not (latches.get(f"{key}_complete") or latches.get(f"{key}_deferred_or_skipped")):
            return False
    return True


def _hold_for_post_arrival_services(meta: dict[str, Any], t: dict[str, Any] | None = None) -> bool:
    times = meta.setdefault("times", {})
    if not times.get("landing") or not times.get("block_in"):
        return False
    state = meta.setdefault("_state", {})
    if _arrival_services_complete_for_record():
        completed_at = state.get("arrival_services_completed_at")
        if not completed_at:
            completed_at = _utc_now()
            state["arrival_services_completed_at"] = completed_at
            if state.get("post_arrival_pending") and not state.get("post_arrival_complete_event"):
                state["post_arrival_complete_event"] = True
                _event(meta, "ARRIVAL SERVICES", "Arrival services complete; capturing final receipts", completed_at)
            return True
        # GSX writes the final handling JSON/HTML shortly after the service state
        # closes. Keep the recorder alive briefly so the first Finance statement
        # normally includes arrival receipts without a manual refresh.
        if (_epoch(_utc_now()) or 0.0) - (_epoch(completed_at) or 0.0) < 45.0:
            return True
        return False
    if not state.get("post_arrival_pending"):
        state["post_arrival_pending"] = True
        state["post_arrival_pending_since"] = _utc_now()
        _event(meta, "POST ARRIVAL PENDING", "Parked at gate; waiting for arrival services, sim exit, or manual completion", _utc_now(), "info")

    # #44: fallback timer — the flight must never hang RECORDING forever. GSX
    # arrival latches live in memory and die on an app restart (verified live:
    # RJA403 stuck 47 minutes until manual completion), and arrival services may
    # never run at all. Once the aircraft has been PARKED with every engine off
    # and the parking brake set for 5 minutes, release the hold so the engine
    # finalizes without arrival-service receipts. The GSX-complete fast path
    # above still wins whenever the latches are healthy.
    phase_up = str(state.get("phase") or "").upper()
    engines_off = bool(t and t.get("engines_running") is False)
    parking_brake = bool(t and t.get("parking_brake"))
    settled = phase_up == "PARKED" and engines_off and parking_brake
    # #65: GSX automation actively working arrival services must pause the
    # fallback timer — the pilot requested services and GSX is mid-work; only
    # a genuinely idle/absent GSX should be time-boxed. The #44 fallback is a
    # last resort for "GSX never runs" / "GSX lost", not a race against a
    # running arrival. (With latches persisted across restart, the GSX-complete
    # fast path above also survives an app restart mid-arrival.)
    gsx_working = False
    try:
        from .gsx_remote import automation_status as _gsx_auto_status
        _mode = str((_gsx_auto_status() or {}).get("mode") or "").upper()
        gsx_working = _mode in {"ARRIVAL", "FULL_TURNAROUND"}
    except Exception:
        gsx_working = False
    if gsx_working:
        state.pop("post_arrival_settled_since_epoch", None)
        state["post_arrival_gsx_paused"] = True
        return True
    if settled:
        since_epoch = state.get("post_arrival_settled_since_epoch")
        if since_epoch is None:
            state["post_arrival_settled_since_epoch"] = _epoch(_utc_now()) or time.time()
        elif (time.time() - float(since_epoch)) >= 300.0:  # 5 minutes on blocks
            if not state.get("post_arrival_timeout_fired"):
                state["post_arrival_timeout_fired"] = True
                _event(meta, "POST ARRIVAL COMPLETE", "Parked 5 minutes with engines off and parking brake set; finalizing without arrival-service receipts", _utc_now())
            return False
    else:
        state.pop("post_arrival_settled_since_epoch", None)
    return True


def _maybe_autostop_black_box(meta: dict[str, Any], sample: dict[str, Any], state: dict[str, Any]) -> None:
    """Stop the Black Box recording 2 minutes after the aircraft is "on blocks".

    "On blocks" means the logbook has reached PARKED (post-arrival), with the
    parking brake set and every engine confirmed off.  Once those three
    conditions hold continuously for 120 seconds, the Black Box file for the
    resolved flight id is closed.  Any of those conditions breaking - the
    parking brake releasing, an engine restart, the logbook leaving PARKED -
    resets the timer.  This is independent of, and never interferes with, the
    logbook block_in / finalize flow; it only closes the separate
    app/black_box.py recording for this flight id.
    """
    phase_up = str(state.get("phase") or "").upper()
    engines_off = sample.get("engines_running") is False
    parking_brake = bool(sample.get("parking_brake"))
    now_epoch = _epoch(sample.get("time")) or time.time()
    on_blocks = phase_up == "PARKED" and engines_off and parking_brake
    if not on_blocks:
        # Engine restart, parking brake release, or out of PARKED: reset the timer.
        state.pop("on_blocks_since_epoch", None)
        state.pop("black_box_autostopped", None)
        return
    since = state.get("on_blocks_since_epoch")
    if since is None:
        state["on_blocks_since_epoch"] = now_epoch
        return
    if state.get("black_box_autostopped") or (now_epoch - float(since)) < 120.0:
        return
    try:
        from .black_box import status as _bb_status, stop_recording as _bb_stop
        bb = _bb_status()
        active = bb.get("active") or {}
        if bb.get("recording") and str(active.get("flight_id") or "") == str(meta.get("id") or ""):
            _bb_stop("ON BLOCKS 120S")
            _event(meta, "BLACK BOX", "Recording stopped 120s after on-blocks (engines off + parking brake + PARKED)", _utc_now())
    except Exception:
        pass
    state["black_box_autostopped"] = True


def _engine_iteration() -> None:
    if _replay_guarded():
        return
    t = read_telemetry(False); active = _active_row()
    if not active:
        if _should_start(t): _start(t, False)
        return
    _, meta = active
    state = meta.setdefault("_state", {})

    # Short provider interruptions hold the last display sample for up to the
    # centralized freeze threshold. Do not write that duplicate point, advance
    # phases or announce telemetry loss during the hold window.
    if t.get("telemetry_hold"):
        return

    if not t.get("ok") or t.get("telemetry_complete") is False or t.get("telemetry_fresh") is False or t.get("stale"):
        state["valid_sample_streak"] = 0
        lost = state.get("connection_lost_at")
        if not lost:
            state["connection_lost_at"] = _utc_now(); _save_flight(meta, "RECORDING")
        elif state.get("post_arrival_pending") and (_epoch(_utc_now()) or 0) - (_epoch(lost) or 0) > 12:
            _event(meta, "SIM EXIT", "Telemetry disconnected after parking; completing the flight with available post-arrival data", _utc_now(), "warning")
            _finalize(meta, "sim exit after arrival", None)
        elif (_epoch(_utc_now()) or 0) - (_epoch(lost) or 0) > 8 and not state.get("connection_alerted"):
            state["connection_alerted"] = True; _event(meta, "TELEMETRY LOST", str(t.get("reason") or "No complete aircraft telemetry sample"), _utc_now(), "warning"); _save_flight(meta, "RECORDING")
            publish("TELEMETRY", "RECORDING INTERRUPTED", str(t.get("reason") or "Telemetry unavailable"), priority="critical", page="logbook", tag=f"lost-{meta['id']}", persistent=True)
        return

    source_now = str(t.get("source") or "")
    source_previous = str(state.get("telemetry_source") or "")
    if t.get("telemetry_gap") and not state.get("telemetry_gap_open"):
        state["telemetry_gap_open"] = True
        _event(meta, "TELEMETRY GAP", str(t.get("failover_reason") or "Primary telemetry source became stale"), _utc_now(), "warning")
    if source_previous and source_now and source_now != source_previous:
        _event(meta, "TELEMETRY SOURCE", f"Recording continued through {source_now}", _utc_now(), "info")
    if state.get("telemetry_gap_open") and not t.get("telemetry_gap") and t.get("telemetry_fresh") is not False:
        state["telemetry_gap_open"] = False
        _event(meta, "TELEMETRY RESTORED", f"Fresh simulator data restored through {source_now or 'active provider'}", _utc_now(), "info")
    state["telemetry_source"] = source_now
    sample = _sample(t, _utc_now()); previous = state.get("last_sample") if isinstance(state.get("last_sample"), dict) else None
    valid, reason = _valid_recording_sample(sample, previous)
    if not valid:
        state["valid_sample_streak"] = 0
        lost = state.get("connection_lost_at")
        if not lost:
            state["connection_lost_at"] = _utc_now()
        elif (_epoch(_utc_now()) or 0) - (_epoch(lost) or 0) > 8 and not state.get("connection_alerted"):
            state["connection_alerted"] = True
            _event(meta, "TELEMETRY LOST", f"Recorder sample incomplete: {reason}", _utc_now(), "warning")
        last_bad = state.get("last_invalid_sample_reason")
        state["last_invalid_sample_reason"] = reason
        if last_bad != reason:
            _event(meta, "TELEMETRY FILTER", f"Ignored invalid sample: {reason}", sample["time"], "warning")
        _save_flight(meta, "RECORDING")
        return

    # Require several stable valid samples before reporting a restore. This keeps
    # provider flapping from producing lost/restored spam and prevents phase or
    # deviation analysis from running on half-valid samples.
    state["valid_sample_streak"] = int(state.get("valid_sample_streak") or 0) + 1
    if state.get("connection_lost_at") and state["valid_sample_streak"] >= 3:
        was_alerted = bool(state.get("connection_alerted"))
        state.pop("connection_lost_at", None)
        state.pop("connection_alerted", None)
        state.pop("last_invalid_sample_reason", None)
        if was_alerted:
            _event(meta, "TELEMETRY RESTORED", f"Recording continued through {t.get('source')}", _utc_now())

    meta["telemetry_source"] = t.get("source") or meta.get("telemetry_source")
    done = _analyse(meta, sample, previous)
    try:
        from .black_box import observe_phase as black_box_observe_phase
        black_box_observe_phase(meta["id"], str(sample.get("phase") or state.get("phase") or ""), meta, telemetry_hint=t)
    except Exception:
        pass
    _maybe_autostop_black_box(meta, sample, state)
    _insert_sample(meta["id"], sample, meta["started_utc"])
    if done:
        if _hold_for_post_arrival_services(meta, t):
            _save_flight(meta, "RECORDING")
        else:
            _finalize(meta, "automatic post-arrival complete", t)
    else: _save_flight(meta, "RECORDING")

def _engine_loop() -> None:
    """Record at the configured rate, automatically increasing detail near the runway.

    Takeoff roll, initial climb, approach, flare and landing are sampled at up to 20 Hz.
    Cruise stays at the user's configured interval to keep long-flight databases compact.
    """
    while not _STOP.is_set():
        settings = load_settings()
        configured = _number(settings.get("integrations", {}).get("telemetry_sample_seconds")) or 1.0
        interval = max(0.1, min(configured, 5.0))
        try:
            active = _active_row()
            if active:
                state = active[1].get("_state") or {}
                phase = str(state.get("phase") or "").upper()
                last = state.get("last_sample") if isinstance(state.get("last_sample"), dict) else {}
                agl = _number(last.get("radio_altitude_ft"))
                if agl is None:
                    agl = _number(last.get("agl_ft"))
                if phase in {"TAKEOFF ROLL", "INITIAL CLIMB", "APPROACH", "FLARE", "LANDING ROLL"} or (agl is not None and agl <= 3000):
                    high_rate = _number(settings.get("integrations", {}).get("telemetry_high_rate_seconds")) or 0.05
                    interval = max(0.045, min(high_rate, 0.25))
        except Exception:
            pass
        if _STOP.wait(interval):
            break
        try:
            _engine_iteration()
        except Exception:
            continue


def start_engine() -> None:
    global _THREAD
    _init_db()
    with _LOCK:
        if _THREAD and _THREAD.is_alive(): return
        _STOP.clear(); _THREAD = threading.Thread(target=_engine_loop, name="OpsRoom-AdvancedRecorder", daemon=True); _THREAD.start()


def stop_engine() -> None: _STOP.set()


def _attach_airline_branding(meta: dict[str, Any]) -> dict[str, Any]:
    flight = meta.get("flight") if isinstance(meta.get("flight"), dict) else {}
    meta["flight"] = flight
    try:
        branding = resolve_airline_branding(flight, callsign=str(flight.get("callsign") or ""), airline_code=str(flight.get("airline") or ""))
    except Exception:
        branding = {"enabled": True, "code": "", "name": "OPS ROOM", "logo_url": None, "logo_available": False, "fallback": "generic"}
    flight["airline_branding"] = branding
    return meta


def _public(meta: dict[str, Any]) -> dict[str, Any]:
    result = _attach_airline_branding(json.loads(json.dumps(meta))); state = result.pop("_state", {})
    if result.get("state") == "RECORDING" and isinstance(state, dict):
        result["current_phase"] = str(state.get("phase") or "")
        result["telemetry_source"] = str(state.get("telemetry_source") or "")
        result["telemetry_gap_open"] = bool(state.get("telemetry_gap_open"))
        last = state.get("last_sample") or {}; fuel = result.setdefault("fuel", {}); current = _number(last.get("fuel_total_lb"))
        fuel["current_lb"] = current
        if _number(fuel.get("used_lb")) is None:
            start = _number(fuel.get("departure_baseline_lb") or fuel.get("start_lb"))
            fuel["used_lb"] = round(max(0, start-current), 1) if start is not None and current is not None else None
    result["sample_count"] = _sample_count(result.get("id"))
    try:
        from .black_box import recording_for_flight
        result["black_box"] = recording_for_flight(str(result.get("id") or ""))
    except Exception:
        result["black_box"] = None
    return result


def _raw_samples(flight_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT elapsed_seconds,data_json FROM samples WHERE flight_id=? ORDER BY elapsed_seconds", (flight_id,)).fetchall()
    return [{"elapsed_seconds": row["elapsed_seconds"], **json.loads(row["data_json"])} for row in rows]


def _matching_gsx_receipts(meta: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        from .gsx_receipts import recent_invoice_items
        times = meta.get("times") if isinstance(meta.get("times"), dict) else {}
        flight = meta.get("flight") if isinstance(meta.get("flight"), dict) else {}
        aircraft = meta.get("aircraft") if isinstance(meta.get("aircraft"), dict) else {}
        return recent_invoice_items(
            meta.get("started_utc"), meta.get("completed_utc"), limit=60,
            takeoff_utc=times.get("takeoff"), landing_utc=times.get("landing"),
            origin=str(flight.get("origin") or ""),
            destination=str(flight.get("destination") or ""),
            tail=str(aircraft.get("registration") or aircraft.get("tail") or flight.get("registration") or ""),
        )
    except Exception:
        return []


def _refresh_entry_receipts(meta: dict[str, Any], *, persist: bool = False) -> dict[str, Any]:
    """Attach receipts found after recorder start/finalisation.

    GSX writes catering/handling receipts outside the narrow recorder window.
    Re-scan on PIREP open so historical flights can display newly matched JSON
    receipts without requiring the flight to be re-recorded.
    """
    invoices = _matching_gsx_receipts(meta)
    if not invoices:
        return meta
    previous_ids = {str(x.get("receipt_id") or x.get("filename") or "") for x in (meta.get("gsx_invoices") or []) if isinstance(x, dict)}
    current_ids = {str(x.get("receipt_id") or x.get("filename") or "") for x in invoices if isinstance(x, dict)}
    if current_ids == previous_ids:
        return meta
    meta["gsx_invoices"] = invoices
    meta["receipts_refreshed_utc"] = _utc_now()
    try:
        from .economy import finance_enabled, reconcile_flight
        # Idempotent by flight id. This also posts a statement when a completed
        # PIREP never received one during finalisation.
        if finance_enabled():
            reconcile_flight(meta, _rows("", 5000))
    except Exception as exc:
        meta["receipt_reconciliation_warning"] = f"{type(exc).__name__}: {exc}"
    if persist and meta.get("id"):
        try:
            with _connect() as conn:
                conn.execute(
                    "UPDATE flights SET metadata_json=?,updated_utc=? WHERE id=? AND status!='RECORDING'",
                    (json.dumps(meta, separators=(",", ":")), meta["receipts_refreshed_utc"], str(meta.get("id"))),
                )
        except Exception:
            pass
    return meta


def _finance_invoice_ids(statement: dict[str, Any] | None) -> set[str]:
    if not isinstance(statement, dict):
        return set()
    airline = statement.get("airline") if isinstance(statement.get("airline"), dict) else {}
    invoices = airline.get("invoices") if isinstance(airline.get("invoices"), list) else []
    return {str(item.get("receipt_id") or item.get("filename") or "") for item in invoices if isinstance(item, dict)}


def _refresh_entry_finance(meta: dict[str, Any], *, persist: bool = False) -> dict[str, Any]:
    """Recover missing finance and reconcile receipts when a PIREP is opened."""
    if not meta.get("id") or str(meta.get("state") or meta.get("status") or "").upper() == "RECORDING":
        return meta
    try:
        from .economy import finance_enabled, reconcile_flight
        if not finance_enabled():
            return meta
        statement = meta.get("finance") if isinstance(meta.get("finance"), dict) else {}
        attached = {str(item.get("receipt_id") or item.get("filename") or "") for item in (meta.get("gsx_invoices") or []) if isinstance(item, dict)}
        if statement.get("ok") and attached == _finance_invoice_ids(statement):
            return meta
        result = reconcile_flight(meta, _rows("", 5000))
        if isinstance(result, dict):
            meta["finance"] = result
        meta["finance_refreshed_utc"] = _utc_now()
        if persist:
            with _connect() as conn:
                conn.execute(
                    "UPDATE flights SET metadata_json=?,updated_utc=? WHERE id=? AND status!='RECORDING'",
                    (json.dumps(meta, separators=(",", ":")), meta["finance_refreshed_utc"], str(meta.get("id"))),
                )
    except Exception as exc:
        meta["finance_refresh_warning"] = f"{type(exc).__name__}: {exc}"
    return meta


def _refresh_entry_analysis(meta: dict[str, Any], *, persist: bool = False) -> dict[str, Any]:
    """Rebuild legacy/missing Full PIREP analysis from stored recorder samples."""
    if not meta.get("id") or str(meta.get("state") or meta.get("status") or "").upper() == "RECORDING":
        return meta
    existing = meta.get("analysis_summary") if isinstance(meta.get("analysis_summary"), dict) else {}
    try:
        current_version = int(existing.get("version") or 0)
    except Exception:
        current_version = 0
    if current_version >= 2 and existing.get("ok"):
        return meta
    try:
        analysis = analyse_pirep(meta, _raw_samples(str(meta.get("id"))))
    except Exception as exc:
        analysis = {"ok": False, "version": 2, "reason": f"PIREP analysis failed: {type(exc).__name__}: {exc}"}
    meta["analysis_summary"] = analysis
    meta["analysis_refreshed_utc"] = _utc_now()
    if analysis.get("ok"):
        landing = analysis.get("landing") if isinstance(analysis.get("landing"), dict) else {}
        metrics = meta.setdefault("metrics", {})
        for key in ("touchdown_distance_ft", "touchdown_centerline_deviation_ft", "rollout_distance_ft"):
            value = _number(landing.get(key))
            if value is not None:
                metrics[key] = value
            else:
                # Do not preserve legacy fabricated zero geometry.
                metrics.pop(key, None)
        if _number(metrics.get("touchdown_pitch_deg")) is None:
            metrics["touchdown_pitch_deg"] = _number(landing.get("touchdown_pitch_deg"))
        if _number(metrics.get("touchdown_bank_deg")) is None:
            metrics["touchdown_bank_deg"] = _number(landing.get("touchdown_bank_deg"))
        debrief = meta.setdefault("debrief", {})
        score = analysis.get("score") if isinstance(analysis.get("score"), dict) else {}
        if score.get("overall") is not None:
            debrief["score"] = int(score.get("overall"))
        if score.get("grade"):
            debrief["landing_grade"] = str(score.get("grade"))
        if isinstance(score.get("breakdown"), dict):
            debrief["score_breakdown"] = score.get("breakdown")
    if persist:
        try:
            with _connect() as conn:
                conn.execute(
                    "UPDATE flights SET metadata_json=?,updated_utc=? WHERE id=? AND status!='RECORDING'",
                    (json.dumps(meta, separators=(",", ":")), meta["analysis_refreshed_utc"], str(meta.get("id"))),
                )
        except Exception:
            pass
    return meta


def get_entry(entry_id: str) -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM flights WHERE id=?", (entry_id,)).fetchone()
    if not row:
        raise KeyError("Flight record not found")
    meta = _refresh_entry_receipts(json.loads(row["metadata_json"]), persist=True)
    meta = _refresh_entry_analysis(meta, persist=True)
    meta = _refresh_entry_finance(meta, persist=True)
    meta["rating"] = row["rating"]
    meta["notes"] = row["notes"]
    meta["sample_count"] = _sample_count(entry_id)
    # #62/#77: attach both sign-off records so logbook detail and the full
    # PIREP can render what was signed (snapshot included).
    meta["signed"] = get_loadsheet_signature(entry_id)
    meta["signed_completion"] = get_loadsheet_signature(entry_id, kind="completion")
    return _attach_airline_branding(meta)


# ── #62/#77: electronic crew sign-off ───────────────────────────────────
# Two signature slots per flight, one table each (no PK migration on live
# DBs): ``loadsheet_signatures`` (pre-departure weight & balance, #62) and
# ``completion_signatures`` (post-arrival Flight Completion sign-off, #77).
# Each snapshot_json stores the exact values the pilot signed (planned vs
# actual weights/MAC/sources + UTC, or the completed-flight summary), so the
# record proves what was signed, not just that something was signed.

_SIGNATURE_TABLES = {
    "loadsheet": "loadsheet_signatures",
    "completion": "completion_signatures",
}


def _signature_table(kind: str) -> str:
    return _SIGNATURE_TABLES.get(str(kind or "").strip().lower(), "loadsheet_signatures")


def get_loadsheet_signature(flight_id: str | None, kind: str = "loadsheet") -> dict[str, Any] | None:
    """Return the stored signature dict for a flight/kind, or None if unsigned.

    ``kind`` is ``loadsheet`` (pre-departure, #62) or ``completion``
    (post-arrival, #77). Never raises on a legacy database that predates the
    table — an unsigned flight is the same as a flight with no signature.
    """
    if not flight_id:
        return None
    table = _signature_table(kind)
    try:
        with _connect() as conn:
            row = conn.execute(f"SELECT * FROM {table} WHERE flight_id=?", (str(flight_id),)).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row:
        return None
    try:
        snapshot = json.loads(row["snapshot_json"])
    except Exception:
        snapshot = {}
    return {
        "flight_id": str(row["flight_id"]),
        "kind": kind,
        "signer": str(row["signer"]),
        "role": str(row["role"] or ""),
        "sig_data_url": str(row["sig_data_url"] or ""),
        "signed_utc": str(row["signed_utc"]),
        "snapshot": snapshot if isinstance(snapshot, dict) else {},
    }


def set_loadsheet_signature(flight_id: str, signer: str, role: str = "", sig_data_url: str = "", snapshot: dict[str, Any] | None = None, kind: str = "loadsheet") -> dict[str, Any]:
    """Store (or replace) the signature for a flight/kind. Returns the stored dict."""
    if not flight_id:
        raise ValueError("No flight id provided for signature")
    table = _signature_table(kind)
    signer = str(signer or "").strip()[:80] or "UNSIGNED"
    role = str(role or "").strip()[:40]
    sig_data_url = str(sig_data_url or "").strip()[:200000]  # PNG data URL guard
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    signed_utc = _utc_now()
    with _connect() as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO {table}(flight_id, signer, role, sig_data_url, signed_utc, snapshot_json) VALUES(?,?,?,?,?,?)",
            (str(flight_id), signer, role, sig_data_url, signed_utc, json.dumps(snapshot, default=str)),
        )
    return {
        "flight_id": str(flight_id),
        "kind": kind,
        "signer": signer,
        "role": role,
        "sig_data_url": sig_data_url,
        "signed_utc": signed_utc,
        "snapshot": snapshot,
    }


def clear_loadsheet_signature(flight_id: str | None, kind: str = "loadsheet") -> bool:
    """Remove the signature for a flight/kind. Returns True if one was removed."""
    if not flight_id:
        return False
    table = _signature_table(kind)
    with _connect() as conn:
        cur = conn.execute(f"DELETE FROM {table} WHERE flight_id=?", (str(flight_id),))
        return cur.rowcount > 0


def completion_signature_locked(entry: dict[str, Any] | None) -> bool:
    """#77: the Flight Completion sign-off is open only post-arrival.

    Allowed while the flight is RECORDING in a post-arrival state (block-in
    recorded, parked at the gate) or after it completed. Locked for any
    pre-departure / enroute state, matching the real-world window: the crew
    reviews and signs after arrival services, before the logbook closes.
    """
    if not isinstance(entry, dict):
        return True
    state_value = str(entry.get("state") or entry.get("status") or "").upper()
    times = entry.get("times") if isinstance(entry.get("times"), dict) else {}
    if not times.get("block_in"):
        return True
    phase = str(entry.get("phase") or (entry.get("_state") or {}).get("phase") or "").upper()
    if state_value in {"COMPLETE", "INCOMPLETE"}:
        return False
    if state_value != "RECORDING":
        return True
    # Post-arrival pending: on the ground after block-in, PARKED/TAXI IN.
    return phase not in {"PARKED", "TAXI IN"}


def loadsheet_signature_locked(entry: dict[str, Any] | None) -> bool:
    """#62: the signature is locked once the flight has taken off (or ended).

    Re-sign/clear is only allowed pre-departure. A completed flight or any
    recorded takeoff time means the sheet is closed for signing.
    """
    if not isinstance(entry, dict):
        return True
    # #74: the active recorder dict uses ``state`` ("RECORDING"), while persisted
    # rows use ``status``. Reading only ``status`` made every live pre-takeoff
    # flight look non-recording and locked the signature at LIVE. Read both.
    state_value = str(entry.get("state") or entry.get("status") or "").upper()
    if state_value != "RECORDING":
        return True
    times = entry.get("times") if isinstance(entry.get("times"), dict) else {}
    if times.get("takeoff"):
        return True
    phase = str(entry.get("phase") or (entry.get("_state") or {}).get("phase") or "").upper()
    return phase in {"TAKEOFF", "INITIAL CLIMB", "CLIMB", "ENROUTE", "DESCENT", "APPROACH", "LANDING", "TAXI IN"}


def _sample_count(flight_id: str | None) -> int:
    if not flight_id: return 0
    with _connect() as conn: return int(conn.execute("SELECT COUNT(*) FROM samples WHERE flight_id=?", (flight_id,)).fetchone()[0])


def flight_row_exists(flight_id: str | None) -> bool:
    """#69: True when a logbook flight row exists for ``flight_id``.

    Used by the Black Box orphan watchdog: an active recording whose flight has
    no logbook row (ad-hoc ``blackbox-*`` starts, hot starts that never
    persisted) must self-terminate on-blocks instead of recording forever.
    """
    if not flight_id:
        return False
    try:
        with _connect() as conn:
            return conn.execute("SELECT 1 FROM flights WHERE id=? LIMIT 1", (str(flight_id),)).fetchone() is not None
    except Exception:
        return True  # on DB trouble, don't force-stop recordings


def _rows(query: str = "", limit: int = 1000) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM flights WHERE status!='RECORDING' ORDER BY started_utc DESC LIMIT ?", (max(1, min(limit, 5000)),)).fetchall()
        # #62/#77: one batch read for all signatures instead of a per-row
        # lookup. The completion table (post-arrival sign-off) is read too and
        # attached as ``signed_completion``.
        try:
            signed_rows = conn.execute(
                "SELECT flight_id, signer, role, signed_utc, snapshot_json FROM loadsheet_signatures"
            ).fetchall() if rows else []
        except sqlite3.OperationalError:
            signed_rows = []
        try:
            completion_rows = conn.execute(
                "SELECT flight_id, signer, role, signed_utc, snapshot_json FROM completion_signatures"
            ).fetchall() if rows else []
        except sqlite3.OperationalError:
            completion_rows = []
    signatures: dict[str, dict[str, Any]] = {}
    completions: dict[str, dict[str, Any]] = {}
    for sig in signed_rows:
        try:
            snap = json.loads(sig["snapshot_json"])
        except Exception:
            snap = {}
        signatures[str(sig["flight_id"])] = {
            "flight_id": str(sig["flight_id"]),
            "signer": str(sig["signer"]),
            "role": str(sig["role"] or ""),
            "signed_utc": str(sig["signed_utc"]),
            "snapshot": snap if isinstance(snap, dict) else {},
        }
    for sig in completion_rows:
        try:
            snap = json.loads(sig["snapshot_json"])
        except Exception:
            snap = {}
        completions[str(sig["flight_id"])] = {
            "flight_id": str(sig["flight_id"]),
            "signer": str(sig["signer"]),
            "role": str(sig["role"] or ""),
            "signed_utc": str(sig["signed_utc"]),
            "snapshot": snap if isinstance(snap, dict) else {},
        }
    entries = []
    q = query.strip().upper()
    for row in rows:
        try:
            meta = json.loads(row["metadata_json"])
        except Exception:
            continue
        meta["rating"] = row["rating"]; meta["notes"] = row["notes"]; meta["sample_count"] = _sample_count(meta.get("id"))
        meta["signed"] = signatures.get(str(meta.get("id") or ""))
        meta["signed_completion"] = completions.get(str(meta.get("id") or ""))
        if q:
            flight = meta.get("flight") or {}; aircraft = meta.get("aircraft") or {}
            hay = " ".join(str(x or "") for x in [flight.get("callsign"), flight.get("origin"), flight.get("destination"), flight.get("registration"), flight.get("aircraft_icao"), aircraft.get("title"), row["notes"]]).upper()
            if q not in hay: continue
        entries.append(_attach_airline_branding(meta))
    return entries


def _stats(entries: list[dict[str, Any]]) -> dict[str, Any]:
    rates = [abs(v) for e in entries if (v := _number((e.get("metrics") or {}).get("landing_rate_fpm"))) is not None]
    stats = {"flights": len(entries), "complete": sum(e.get("state") == "COMPLETE" or e.get("status") == "COMPLETE" for e in entries), "block_seconds": sum(int((e.get("durations") or {}).get("block_seconds") or 0) for e in entries), "airborne_seconds": sum(int((e.get("durations") or {}).get("airborne_seconds") or 0) for e in entries), "distance_nm": round(sum(_number((e.get("metrics") or {}).get("distance_nm")) or 0 for e in entries), 1), "fuel_used_lb": round(sum(_number((e.get("fuel") or {}).get("used_lb")) or 0 for e in entries), 1), "average_landing_rate_fpm": round(sum(rates)/len(rates), 1) if rates else None, "violations": sum(len(e.get("violations") or []) for e in entries)}
    airline_counts: dict[str, dict[str, Any]] = {}
    for entry in entries:
        flight = entry.get("flight") if isinstance(entry.get("flight"), dict) else {}
        brand = flight.get("airline_branding") if isinstance(flight.get("airline_branding"), dict) else resolve_airline_branding(flight, callsign=str(flight.get("callsign") or ""), airline_code=str(flight.get("airline") or ""))
        code = str(brand.get("code") or "").upper()
        if code:
            bucket = airline_counts.setdefault(code, {**brand, "flights": 0})
            bucket["flights"] = int(bucket.get("flights") or 0) + 1
    stats["top_airline"] = max(airline_counts.values(), key=lambda item: (int(item.get("flights") or 0), str(item.get("code") or "")), default=None)
    try:
        from .economy import finance_enabled, public_status
        if finance_enabled():
            econ = public_status(entries)
            stats["finance"] = {"currency": econ.get("currency"), "symbol": econ.get("symbol"), "airline_balance": econ.get("airline_balance"), "pilot_balance": econ.get("pilot_balance"), "totals": econ.get("totals") or {}, "average_profit_per_flight": econ.get("average_profit_per_flight")}
            stats["rank"] = econ.get("rank")
    except Exception:
        pass
    return stats


def status(limit: int = 100, query: str = "") -> dict[str, Any]:
    _init_db_safe(); entries = _rows(query, limit); all_entries = _rows("", 5000); active = _active_row()
    return {"ok": True, "recording": bool(active), "active": _public(active[1]) if active else None, "entries": entries, "count": len(entries), "statistics": _stats(all_entries), "storage_path": str(_db_path()), "storage_engine": "SQLite WAL", "telemetry": telemetry_diagnostics(False), "updated_utc": _utc_now()}


def _landing_payload(meta: dict[str, Any], row_id: str, updated_utc: str | None = None) -> dict[str, Any] | None:
    times = meta.get("times") if isinstance(meta.get("times"), dict) else {}
    if not times.get("landing"):
        return None
    metrics = meta.get("metrics") if isinstance(meta.get("metrics"), dict) else {}
    analysis = meta.get("analysis_summary") if isinstance(meta.get("analysis_summary"), dict) else {}
    landing_analysis = analysis.get("landing") if isinstance(analysis.get("landing"), dict) else {}
    flight = meta.get("flight") if isinstance(meta.get("flight"), dict) else {}
    aircraft = meta.get("aircraft") if isinstance(meta.get("aircraft"), dict) else {}
    landing_id = f"{row_id}:{times.get('landing')}"
    # #67: prefer the ACTUAL recorded runway from the landing analysis (the
    # recorded-track heading), falling back to the SimBrief planned runway only
    # when the analysis has no landing geometry. Keep both so the UI can label
    # planned-vs-actual instead of silently substituting.
    actual_runway = landing_analysis.get("runway")
    planned_runway = flight.get("arrival_runway")
    runway = actual_runway or planned_runway
    return {
        "ok": True,
        "id": landing_id,
        "landing_utc": times.get("landing"),
        "updated_utc": updated_utc or meta.get("updated_utc"),
        "callsign": flight.get("callsign"),
        "runway": runway,
        "planned_runway": planned_runway,
        "runway_source": "recorded track" if actual_runway else ("planned" if planned_runway else None),
        "aircraft": flight.get("aircraft_icao") or aircraft.get("model") or aircraft.get("title"),
        "landing_rate_fpm": metrics.get("landing_rate_fpm"),
        "touchdown_g": metrics.get("touchdown_g"),
        "touchdown_speed_kts": metrics.get("touchdown_speed_kts"),
        "touchdown_pitch_deg": metrics.get("touchdown_pitch_deg") if _number(metrics.get("touchdown_pitch_deg")) is not None else landing_analysis.get("touchdown_pitch_deg"),
        "touchdown_bank_deg": metrics.get("touchdown_bank_deg") if _number(metrics.get("touchdown_bank_deg")) is not None else landing_analysis.get("touchdown_bank_deg"),
        "touchdown_distance_ft": landing_analysis.get("touchdown_distance_ft") if _number(landing_analysis.get("touchdown_distance_ft")) is not None else metrics.get("touchdown_distance_ft"),
        "touchdown_centerline_deviation_ft": landing_analysis.get("touchdown_centerline_deviation_ft") if _number(landing_analysis.get("touchdown_centerline_deviation_ft")) is not None else metrics.get("touchdown_centerline_deviation_ft"),
        "bounce_count": metrics.get("bounce_count", 0),
        "bounce_severity": metrics.get("bounce_severity"),
        "bounce_penalty": metrics.get("bounce_penalty", 0),
        "active_recording": meta.get("state") == "RECORDING",
    }


def latest_landing() -> dict[str, Any]:
    """Return the newest landing, including the active recording immediately after touchdown."""
    _init_db_safe()
    active = _active_row()
    if active:
        active_payload = _landing_payload(active[1], str(active[0]["id"]), active[0]["updated_utc"])
        if active_payload:
            return active_payload
    with _connect() as conn:
        rows = conn.execute("SELECT id, metadata_json, updated_utc FROM flights WHERE status!='RECORDING' ORDER BY completed_utc DESC, started_utc DESC LIMIT 12").fetchall()
    for row in rows:
        try:
            meta = json.loads(row["metadata_json"])
        except (TypeError, ValueError):
            continue
        payload = _landing_payload(meta, str(row["id"]), row["updated_utc"])
        if payload:
            return payload
    return {"ok": True, "id": None}

def latest_completed() -> dict[str, Any] | None:
    """Return the full metadata of the most recent completed flight, or None.

    Used by the live OFP endpoint after block-in so the completion panel keeps
    showing final values once the active recorder has been finalized.
    """
    _init_db_safe()
    with _connect() as conn:
        rows = conn.execute("SELECT id, metadata_json, updated_utc FROM flights WHERE status!='RECORDING' ORDER BY completed_utc DESC, started_utc DESC LIMIT 1").fetchall()
    if not rows:
        return None
    row = rows[0]
    try:
        meta = json.loads(row["metadata_json"])
    except (TypeError, ValueError):
        return None
    meta["updated_utc"] = str(row["updated_utc"] or "")
    return _attach_airline_branding(meta)

def start_departure_services(reason: str = "Begin Departure Services") -> dict[str, Any]:
    """Start/arm one recorder session from the GSX departure workflow."""
    if _replay_guarded():
        return {"ok": False, "replay_suppressed": True, "reason": "In-simulator replay is active"}
    existing = _active_row()
    if existing:
        return {"ok": True, "already_recording": True, "active": _public(existing[1])}
    try:
        t = read_telemetry(False)
    except Exception as exc:
        t = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    pending = not bool(t.get("ok") and t.get("telemetry_complete") is not False and t.get("telemetry_fresh") is not False and not t.get("stale"))
    if pending:
        t = {"ok": True, "source": "departure-services-pending", "telemetry_complete": False, "on_ground": True, "ground_speed_kts": 0.0}
    active = _start(t, False)
    if not active.get("id"):
        return active
    active.setdefault("_state", {})["departure_services_start"] = True
    if pending:
        active["_state"]["manual_pending_telemetry"] = True
        _event(active, "RECORDING PENDING", f"{reason}; waiting for valid telemetry", _utc_now(), "warning")
    else:
        _event(active, "DEPARTURE SERVICES", f"{reason}; flight recording started", _utc_now())
    _save_flight(active, "RECORDING")
    return {"ok": True, "already_recording": False, "recording_pending": pending, "active": _public(active)}


def start_manual() -> dict[str, Any]:
    if _replay_guarded():
        return {"ok": False, "replay_suppressed": True, "reason": "In-simulator replay is active"}
    existing = _active_row()
    if existing:
        return {"ok": True, "already_recording": True, "active": _public(existing[1])}
    try:
        t = read_telemetry(False)
    except Exception as exc:
        t = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    pending = False
    if not t.get("ok"):
        pending = True
        t = {"ok": True, "source": "manual-pending", "telemetry_complete": False, "reason": t.get("reason"), "on_ground": True, "ground_speed_kts": 0.0}
    active = _start(t, True)
    if not active.get("id"):
        return active
    if pending:
        active.setdefault("_state", {})["manual_pending_telemetry"] = True
        _event(active, "RECORDING_PENDING", "Manual recording armed; waiting for valid telemetry", _utc_now(), "warning")
        _save_flight(active, "RECORDING")
    return {"ok": True, "already_recording": False, "recording_pending": pending, "active": _public(active)}


def finalize_active() -> dict[str, Any]:
    active = _active_row()
    if not active:
        raise ValueError("No active flight is being recorded")
    # Manual completion must never wait on a provider reconnect. Use the cached
    # telemetry snapshot when available and otherwise finalize from the last
    # recorder sample already stored in the flight metadata.
    try:
        t = read_telemetry(False)
    except Exception:
        t = {}
    return {"ok": True, "entry": _finalize(active[1], "manual completion", t if t.get("ok") else None)}


def discard_active() -> dict[str, Any]:
    active = _active_row()
    if not active:
        raise ValueError("No active flight is being recorded")
    flight_id = active[1]["id"]
    # Hard recovery path: no telemetry, GSX or status calls are permitted here.
    with _connect() as conn:
        conn.execute("DELETE FROM samples WHERE flight_id=?", (flight_id,))
        conn.execute("DELETE FROM flights WHERE id=?", (flight_id,))
    return {"ok": True, "discarded_id": flight_id}


def force_discard_active() -> dict[str, Any]:
    """Clear every orphaned active recorder row without touching completed PIREPs."""
    with _connect() as conn:
        rows = conn.execute("SELECT id FROM flights WHERE status='RECORDING'").fetchall()
        ids = [str(row[0]) for row in rows]
        for flight_id in ids:
            conn.execute("DELETE FROM samples WHERE flight_id=?", (flight_id,))
        conn.execute("DELETE FROM flights WHERE status='RECORDING'")
    return {"ok": True, "discarded_ids": ids, "count": len(ids)}


def update_entry(entry_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM flights WHERE id=? AND status!='RECORDING'", (entry_id,)).fetchone()
        if not row: raise KeyError("Flight record not found")
        meta = json.loads(row["metadata_json"]); notes = _text(payload.get("notes", row["notes"]), 4000); rating = max(0, min(5, int(payload.get("rating", row["rating"]) or 0)))
        meta["notes"] = notes; meta["rating"] = rating; meta["updated_utc"] = _utc_now()
        conn.execute("UPDATE flights SET metadata_json=?,notes=?,rating=?,updated_utc=? WHERE id=?", (json.dumps(meta, separators=(",", ":")), notes, rating, meta["updated_utc"], entry_id))
    return {"ok": True, "entry": meta}


def delete_entry(entry_id: str) -> dict[str, Any]:
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM flights WHERE id=? AND status!='RECORDING'", (entry_id,))
        if not cursor.rowcount: raise KeyError("Flight record not found")
    return {"ok": True, "deleted_id": entry_id}


def telemetry(entry_id: str, max_points: int = 1800) -> dict[str, Any]:
    with _connect() as conn:
        flight = conn.execute("SELECT * FROM flights WHERE id=?", (entry_id,)).fetchone()
        if not flight:
            raise KeyError("Flight record not found")
        rows = conn.execute("SELECT elapsed_seconds,data_json FROM samples WHERE flight_id=? ORDER BY elapsed_seconds", (entry_id,)).fetchall()
    meta = json.loads(flight["metadata_json"])
    flight_data = meta.get("flight") or {}
    route = flight_data.get("navlog") or []
    cruise = _number(flight_data.get("cruise_altitude_ft"))
    landing_position = (meta.get("positions") or {}).get("landing") or {}
    landing_lat = _number(landing_position.get("lat")); landing_lon = _number(landing_position.get("lon"))
    landing_epoch = _epoch((meta.get("times") or {}).get("landing"))
    raw_samples = []
    for row in rows:
        try:
            raw_samples.append({"elapsed_seconds": row["elapsed_seconds"], **json.loads(row["data_json"])})
        except Exception:
            continue
    # v0.25.72 (#21): short-TTL analysis cache. analyse_pirep re-runs the full
    # sanitizer and NOTAM footnotes on every request, and for a still-RECORDING
    # flight nothing was cached — each chart/PIREP load repeated it. 30 s keeps
    # repeated loads cheap while staying fresh for an active flight.
    analysis_cache_key = f"analysis:{entry_id}"
    cached_analysis = _ANALYSIS_CACHE.get(analysis_cache_key)
    if cached_analysis and time.time() - cached_analysis[0] <= _ANALYSIS_CACHE_TTL:
        analysis = cached_analysis[1]
    else:
        try:
            analysis = analyse_pirep(meta, raw_samples)
        except Exception as exc:
            analysis = {"ok": False, "reason": f"PIREP analysis failed: {type(exc).__name__}: {exc}"}
        _ANALYSIS_CACHE[analysis_cache_key] = (time.time(), analysis)
        if len(_ANALYSIS_CACHE) > 200:
            # Prune in place — a bare-name rebind would make _ANALYSIS_CACHE a
            # local and break the read at the top of this function (#23).
            # Build the kept items first: clearing before reading would drop
            # every recent entry.
            cutoff = time.time() - _ANALYSIS_CACHE_TTL
            kept = {key: value for key, value in _ANALYSIS_CACHE.items() if value[0] >= cutoff}
            _ANALYSIS_CACHE.clear()
            _ANALYSIS_CACHE.update(kept)
    total = len(rows); stride = max(1, math.ceil(total / max(50, min(max_points, 5000))))
    selected = [raw_samples[i] for i in range(0, total, stride)]
    if raw_samples and (not selected or selected[-1]["elapsed_seconds"] != raw_samples[-1]["elapsed_seconds"]):
        selected.append(raw_samples[-1])
    samples: list[dict[str, Any]] = []
    for source_item in selected:
        item = dict(source_item)
        if cruise is not None:
            item["planned_cruise_altitude_ft"] = cruise
        sampled_epoch = _epoch(item.get("time"))
        if landing_epoch is not None and sampled_epoch is not None:
            item["seconds_to_touchdown"] = round(sampled_epoch - landing_epoch, 2)
        lat, lon = _number(item.get("lat")), _number(item.get("lon"))
        if None not in (lat, lon, landing_lat, landing_lon):
            distance = haversine_nm(lat, lon, landing_lat, landing_lon)
            item["distance_to_touchdown_nm"] = round(distance, 3)
            actual_agl = _number(item.get("radio_altitude_ft"))
            if actual_agl is None:
                actual_agl = _number(item.get("agl_ft"))
            expected_agl = distance * 6076.12 * math.tan(math.radians(3.0))
            item["ideal_3deg_agl_ft"] = round(expected_agl, 1)
            if actual_agl is not None:
                # v0.25.72 (#21): MSFS RADIO_HEIGHT is not clamped like a real
                # radio altimeter (it reads 20-30k ft at altitude), so samples
                # above 5,000 ft AGL are never approach data — null them so the
                # approach charts can't draw absurd peaks from the en-route
                # descent that happens to pass within 20 NM of the runway.
                if actual_agl > 5000.0:
                    item["approach_agl_ft"] = None
                    item["glidepath_deviation_ft"] = None
                else:
                    item["approach_agl_ft"] = round(actual_agl, 1)
                    if distance <= 25:
                        item["glidepath_deviation_ft"] = round(actual_agl - expected_agl, 1)
        item["ground_contact_plot"] = 25.0 if item.get("on_ground") else 0.0
        samples.append(item)
    return {
        "ok": True,
        "entry_id": entry_id,
        "total_samples": total,
        "returned_samples": len(samples),
        "downsample_stride": stride,
        "route": route,
        "landing_position": landing_position,
        "samples": samples,
        "analysis": analysis,
    }


def entry_ids() -> list[str]:
    """Every stored flight id, oldest first (lightweight single-column read).

    Used to prune derived stores (e.g. manual OFP overrides) whose keys are
    Logbook entry ids, so data for deleted flights does not accumulate.
    Returns [] on any failure -- pruning callers treat that as "keep
    everything" via their own guards.
    """
    try:
        with _connect() as conn:
            return [str(row[0]) for row in conn.execute("SELECT id FROM flights ORDER BY started_utc ASC")]
    except Exception:
        return []


def _manual_overrides(entry_id: str | None) -> dict[str, Any]:
    """Stored manual OFP overrides for an entry; empty when there are none.

    Read-only peek at the live OFP override store (the live panel is the only
    writer).  Exports attach the result as an extra key or trailing column and
    never overwrite existing values, so pilot corrections survive into the
    permanent record without altering any legacy field.
    """
    try:
        from .ofp_overrides import get_overrides

        return dict(get_overrides(str(entry_id or "")))
    except Exception:
        return {}


_EXPORT_VERSION: str | None = None


def _export_version() -> str:
    """Current app version for export stamps, read from ``version.json``.

    Exports carry the real build label instead of a hardcoded release string
    that would go stale.  Falls back to the previous label only when the
    version file is missing (dev checkouts) so exports stay truthful.
    """
    global _EXPORT_VERSION
    if _EXPORT_VERSION is None:
        try:
            raw = (Path(__file__).resolve().parent.parent / "version.json").read_text(encoding="utf-8")
            _EXPORT_VERSION = str(json.loads(raw).get("version") or "0.25.9")
        except Exception:
            _EXPORT_VERSION = "0.25.9"
    return _EXPORT_VERSION


def export_json(query: str = "") -> bytes:
    entries = _rows(query, 5000)
    for entry in entries:
        overrides = _manual_overrides(entry.get("id"))
        if overrides:
            entry["manual_overrides"] = overrides
    payload = {"product": "OPS ROOM", "version": _export_version(), "schema": _SCHEMA, "exported_utc": _utc_now(), "query": query, "entries": entries}
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def export_csv(query: str = "") -> bytes:
    entries = _rows(query, 5000); output = io.StringIO(newline="")
    fields = ["date_utc","callsign","origin","destination","aircraft","registration","status","telemetry_source","block_out_utc","takeoff_utc","landing_utc","block_in_utc","block_seconds","airborne_seconds","distance_nm","fuel_used_lb","landing_rate_fpm","touchdown_speed_kts","touchdowns","score","landing_grade","violations","rating","notes","manual_overrides"]
    writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader()
    for e in entries:
        f=e.get("flight") or {}; a=e.get("aircraft") or {}; t=e.get("times") or {}; d=e.get("durations") or {}; m=e.get("metrics") or {}; fuel=e.get("fuel") or {}; de=e.get("debrief") or {}
        overrides = _manual_overrides(e.get("id"))
        writer.writerow({"date_utc":(e.get("started_utc") or "")[:10],"callsign":f.get("callsign"),"origin":f.get("origin"),"destination":f.get("destination"),"aircraft":f.get("aircraft_icao") or a.get("model") or a.get("title"),"registration":f.get("registration"),"status":e.get("state") or e.get("status"),"telemetry_source":e.get("telemetry_source"),"block_out_utc":t.get("block_out"),"takeoff_utc":t.get("takeoff"),"landing_utc":t.get("landing"),"block_in_utc":t.get("block_in"),"block_seconds":d.get("block_seconds"),"airborne_seconds":d.get("airborne_seconds"),"distance_nm":m.get("distance_nm"),"fuel_used_lb":fuel.get("used_lb"),"landing_rate_fpm":m.get("landing_rate_fpm"),"touchdown_speed_kts":m.get("touchdown_speed_kts"),"touchdowns":m.get("touchdowns"),"score":de.get("score"),"landing_grade":de.get("landing_grade"),"violations":len(e.get("violations") or []),"rating":e.get("rating",0),"notes":e.get("notes",""),"manual_overrides":json.dumps(overrides, separators=(",", ":")) if overrides else ""})
    return output.getvalue().encode("utf-8-sig")


def _chart_drawing(
    samples: list[dict[str, Any]],
    keys: list[tuple[str, str]],
    title: str,
    width: float,
    height: float,
    *,
    x_key: str = "elapsed_seconds",
    x_scale: float = 1.0 / 60.0,
):
    from reportlab.graphics.charts.lineplots import LinePlot
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.lib import colors

    drawing = Drawing(width, height)
    drawing.add(String(0, height - 12, title, fontName="Helvetica-Bold", fontSize=9))
    chart = LinePlot(); chart.x = 35; chart.y = 20; chart.height = height - 48; chart.width = width - 45
    series: list[list[tuple[float, float]]] = []
    for key, _label in keys:
        points = []
        for sample in samples:
            x = _number(sample.get(x_key)); y = _number(sample.get(key))
            if x is not None and y is not None:
                points.append((x * x_scale, y))
        series.append(points)
    chart.data = series
    all_x = [point[0] for values in series for point in values]
    chart.xValueAxis.valueMin = min(all_x or [0.0])
    chart.xValueAxis.valueMax = max(all_x or [1.0])
    if chart.xValueAxis.valueMin == chart.xValueAxis.valueMax:
        chart.xValueAxis.valueMax += 1.0
    chart.lines.strokeWidth = 1.2
    chart.xValueAxis.labelTextFormat = "%0.1f" if (chart.xValueAxis.valueMax - chart.xValueAxis.valueMin) < 10 else "%0.0f"
    chart.yValueAxis.labelTextFormat = "%0.0f"
    chart.xValueAxis.labels.fontSize = 6; chart.yValueAxis.labels.fontSize = 6
    palette = [colors.HexColor("#1b7f91"), colors.HexColor("#9b6b1d"), colors.HexColor("#7b4173"), colors.HexColor("#2b7a3d")]
    legend_x = 5
    for idx, (_key, label) in enumerate(keys):
        chart.lines[idx].strokeColor = palette[idx % len(palette)]
        drawing.add(String(legend_x, height - 23, label, fontName="Helvetica", fontSize=6.5, fillColor=palette[idx % len(palette)]))
        legend_x += max(34, 5 * len(label) + 12)
    drawing.add(chart)
    return drawing


def _track_drawing(samples: list[dict[str, Any]], width: float, height: float, route: list[dict[str, Any]] | None = None):
    from reportlab.graphics.shapes import Drawing, String, PolyLine, Circle
    from reportlab.lib import colors
    actual = [(float(s["lon"]), float(s["lat"])) for s in samples if s.get("lat") is not None and s.get("lon") is not None]
    planned = [(float(s["lon"]), float(s["lat"])) for s in (route or []) if s.get("lat") is not None and s.get("lon") is not None]
    drawing = Drawing(width, height)
    drawing.add(String(0, height - 12, "PLANNED ROUTE / ACTUAL GROUND TRACK", fontName="Helvetica-Bold", fontSize=9))
    if len(actual) < 2:
        drawing.add(String(8, height / 2, "Insufficient position samples", fontName="Helvetica", fontSize=8))
        return drawing
    all_points = [*actual, *planned]
    min_lon, max_lon = min(p[0] for p in all_points), max(p[0] for p in all_points)
    min_lat, max_lat = min(p[1] for p in all_points), max(p[1] for p in all_points)
    lon_span, lat_span = max(max_lon - min_lon, 1e-5), max(max_lat - min_lat, 1e-5)
    pad, plot_top = 12, height - 22
    plot_w, plot_h = width - 2 * pad, plot_top - pad
    def project(points):
        return [(pad + (lon - min_lon) / lon_span * plot_w, pad + (lat - min_lat) / lat_span * plot_h) for lon, lat in points]
    if len(planned) >= 2:
        projected_plan = project(planned)
        drawing.add(PolyLine([value for point in projected_plan for value in point], strokeColor=colors.HexColor("#9b6b1d"), strokeWidth=1.0, strokeDashArray=[3, 2]))
    projected = project(actual)
    drawing.add(PolyLine([value for point in projected for value in point], strokeColor=colors.HexColor("#1b7f91"), strokeWidth=1.4))
    drawing.add(Circle(projected[0][0], projected[0][1], 2.5, fillColor=colors.HexColor("#2b7a3d"), strokeColor=None))
    drawing.add(Circle(projected[-1][0], projected[-1][1], 2.5, fillColor=colors.HexColor("#a33a2b"), strokeColor=None))
    return drawing


def _phase_timeline_drawing(samples: list[dict[str, Any]], width: float, height: float):
    from reportlab.graphics.shapes import Drawing, String, Rect
    from reportlab.lib import colors
    drawing = Drawing(width, height)
    drawing.add(String(0, height - 12, "FLIGHT PHASE TIMELINE", fontName="Helvetica-Bold", fontSize=9))
    rows = [(float(s.get("elapsed_seconds") or 0), str(s.get("phase") or "")) for s in samples if s.get("phase")]
    if not rows:
        drawing.add(String(8, height / 2, "No phase samples", fontName="Helvetica", fontSize=8))
        return drawing
    end = max(rows[-1][0], 1.0); y = 18; bar_h = 18
    palette = [colors.HexColor("#1b7f91"), colors.HexColor("#9b6b1d"), colors.HexColor("#2b7a3d"), colors.HexColor("#7b4173"), colors.HexColor("#6b7280")]
    segments = []
    seg_start, seg_phase = rows[0]
    for elapsed, phase in rows[1:]:
        if phase != seg_phase:
            segments.append((seg_start, elapsed, seg_phase)); seg_start, seg_phase = elapsed, phase
    segments.append((seg_start, end, seg_phase))
    for idx, (a, b, phase) in enumerate(segments):
        x = 4 + a / end * (width - 8); w = max(1.5, (b - a) / end * (width - 8))
        color = palette[idx % len(palette)]
        drawing.add(Rect(x, y, w, bar_h, fillColor=color, strokeColor=None))
        if w > 34:
            drawing.add(String(x + 2, y + 5, phase[:20], fontName="Helvetica", fontSize=5.8, fillColor=colors.white))
    end_label = f"{end:.0f} sec" if end < 120 else f"{end / 60.0:.0f} min"
    drawing.add(String(4, 6, "0", fontName="Helvetica", fontSize=6))
    drawing.add(String(width - 42, 6, end_label, fontName="Helvetica", fontSize=6))
    return drawing



def _analysis_xy_drawing(
    rows: list[dict[str, Any]],
    x_key: str,
    y_keys: list[tuple[str, str]],
    title: str,
    width: float,
    height: float,
):
    """Compact XY drawing used by the detailed PIREP analysis pages."""
    from reportlab.graphics.charts.lineplots import LinePlot
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.lib import colors

    drawing = Drawing(width, height)
    drawing.add(String(0, height - 12, title, fontName="Helvetica-Bold", fontSize=9))
    chart = LinePlot()
    chart.x, chart.y = 36, 22
    chart.width, chart.height = width - 48, height - 52
    series: list[list[tuple[float, float]]] = []
    for key, _label in y_keys:
        points: list[tuple[float, float]] = []
        for row in rows:
            x, y = _number(row.get(x_key)), _number(row.get(key))
            if x is not None and y is not None:
                points.append((x, y))
        series.append(points)
    chart.data = series
    all_x = [x for line in series for x, _y in line]
    if not all_x:
        drawing.add(String(8, height / 2, "Insufficient telemetry", fontName="Helvetica", fontSize=8))
        return drawing
    if x_key in {'lateral_deviation_ft', 'deviation_ft'}:
        limit = max(250.0, min(4000.0, max(abs(v) for v in all_x) * 1.18))
        step = 500.0 if limit <= 1500 else 1000.0
        limit = math.ceil(limit / step) * step
        chart.xValueAxis.valueMin = -limit
        chart.xValueAxis.valueMax = limit
    else:
        chart.xValueAxis.valueMin = min(all_x)
        chart.xValueAxis.valueMax = max(all_x)
        if chart.xValueAxis.valueMin == chart.xValueAxis.valueMax:
            chart.xValueAxis.valueMax += 1
    chart.xValueAxis.labels.fontSize = 6
    chart.yValueAxis.labels.fontSize = 6
    chart.xValueAxis.labelTextFormat = "%0.1f"
    chart.yValueAxis.labelTextFormat = "%0.0f"
    palette = [colors.HexColor("#376ec8"), colors.HexColor("#d34a46"), colors.HexColor("#2e9f64")]
    legend_x = 6
    for index, (_key, label) in enumerate(y_keys):
        chart.lines[index].strokeColor = palette[index % len(palette)]
        chart.lines[index].strokeWidth = 1.4
        drawing.add(String(legend_x, height - 23, label, fontName="Helvetica", fontSize=6.5, fillColor=palette[index % len(palette)]))
        legend_x += max(45, len(label) * 4 + 16)
    drawing.add(chart)
    return drawing


def _runway_analysis_drawing(data: dict[str, Any], title: str, width: float, height: float, landing: bool = False):
    from reportlab.graphics.shapes import Drawing, String, Rect, Line, PolyLine, Circle
    from reportlab.lib import colors

    drawing = Drawing(width, height)
    drawing.add(String(0, height - 12, title, fontName="Helvetica-Bold", fontSize=9))
    length = max(3000.0, _number(data.get("runway_length_ft")) or 8000.0)
    runway_width = max(80.0, _number(data.get("runway_width_ft")) or 150.0)
    path = [x for x in (data.get("runway_path") or []) if _number(x.get("along_ft")) is not None and _number(x.get("deviation_ft")) is not None]
    left, right, bottom = 20.0, width - 12.0, 24.0
    runway_y, runway_h = 42.0, max(45.0, height - 78.0)
    runway_w = right - left
    drawing.add(Rect(left, runway_y, runway_w, runway_h, fillColor=colors.HexColor("#4b535a"), strokeColor=colors.HexColor("#8b969b"), strokeWidth=.6))
    if landing:
        tdz_w = min(runway_w * .45, 3000.0 / length * runway_w)
        drawing.add(Rect(left, runway_y, tdz_w, runway_h, fillColor=colors.Color(.12,.42,.24,.35), strokeColor=None))
        aim_x = left + min(1000.0, length) / length * runway_w
        drawing.add(Rect(aim_x - 2, runway_y + runway_h * .25, 4, runway_h * .5, fillColor=colors.white, strokeColor=None))
        drawing.add(Rect(aim_x + 7, runway_y + runway_h * .25, 4, runway_h * .5, fillColor=colors.white, strokeColor=None))
    drawing.add(Line(left, runway_y + runway_h / 2, right, runway_y + runway_h / 2, strokeColor=colors.white, strokeWidth=.7, strokeDashArray=[8, 6]))
    for thousand in range(0, int(length // 1000) + 1):
        x = left + min(thousand * 1000.0, length) / length * runway_w
        drawing.add(Line(x, runway_y - 3, x, runway_y, strokeColor=colors.HexColor("#7c878c"), strokeWidth=.4))
        drawing.add(String(x - 5, bottom - 2, f"{thousand}k", fontName="Helvetica", fontSize=5.8, fillColor=colors.HexColor("#69767b")))
    cross_extent = max(runway_width, 200.0, max((abs(float(x["deviation_ft"])) for x in path), default=0.0) * 1.25)
    points: list[float] = []
    for row in path:
        along = max(0.0, min(length, float(row["along_ft"])))
        deviation = float(row["deviation_ft"])
        x = left + along / length * runway_w
        y = runway_y + runway_h / 2 - deviation / cross_extent * runway_h * .46
        points.extend([x, y])
    if len(points) >= 4:
        drawing.add(PolyLine(points, strokeColor=colors.HexColor("#3478d4"), strokeWidth=1.6))
    if landing:
        along = max(0.0, min(length, _number(data.get("touchdown_distance_ft")) or 0.0))
        deviation = _number(data.get("touchdown_centerline_deviation_ft")) or 0.0
        marker_x = left + along / length * runway_w
        marker_y = runway_y + runway_h / 2 - deviation / cross_extent * runway_h * .46
    elif len(points) >= 2:
        marker_x, marker_y = points[-2], points[-1]
    else:
        marker_x = marker_y = None
    if marker_x is not None:
        drawing.add(Circle(marker_x, marker_y, 4.3, fillColor=colors.HexColor("#21b66b"), strokeColor=colors.white, strokeWidth=1))
    drawing.add(String(left, height - 28, "THRESHOLD", fontName="Helvetica", fontSize=6.4, fillColor=colors.HexColor("#66747a")))
    drawing.add(String(right - 36, height - 28, "RUNWAY END", fontName="Helvetica", fontSize=6.4, fillColor=colors.HexColor("#66747a")))
    drawing.add(String(width / 2 - 35, 5, f"{length:,.0f} FT x {runway_width:,.0f} FT", fontName="Helvetica", fontSize=6.5, fillColor=colors.HexColor("#66747a")))
    return drawing


def _metric_table(rows: list[tuple[str, Any]], columns: int = 4):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle
    cells: list[list[str]] = []
    flat: list[str] = []
    for label, value in rows:
        flat.extend([str(label).upper(), str(value if value not in (None, "") else "-")])
    per_row = columns * 2
    for offset in range(0, len(flat), per_row):
        row = flat[offset : offset + per_row]
        row.extend([""] * (per_row - len(row)))
        cells.append(row)
    widths = []
    for _ in range(columns):
        widths.extend([24 * 2.83465, 31 * 2.83465])
    table = Table(cells, colWidths=widths[:per_row])
    commands = [
        ("GRID", (0,0), (-1,-1), .25, colors.HexColor("#9aa4a7")),
        ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 7),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("PADDING", (0,0), (-1,-1), 4),
    ]
    for col in range(0, per_row, 2):
        commands.append(("BACKGROUND", (col,0), (col,-1), colors.HexColor("#e7edef")))
        commands.append(("FONTNAME", (col,0), (col,-1), "Helvetica-Bold"))
    table.setStyle(TableStyle(commands))
    return table


def _fmt_metric(value: Any, suffix: str = "", digits: int = 0) -> str:
    number = _number(value)
    if number is None:
        return "-"
    units = load_settings().get("interface", {}).get("units", {})
    s = str(suffix or "").upper()
    if s in {"FT", "FEET"} and units.get("altitude") == "m":
        number *= 0.3048; suffix = "M"
    elif s in {"FPM", "FT/MIN"} and units.get("vertical_speed") == "mps":
        number *= 0.00508; suffix = "M/S"
    elif s in {"KT", "KTS", "KNOTS"} and units.get("speed") == "kmh":
        number *= 1.852; suffix = "KM/H"
    elif s in {"NM"} and units.get("distance") == "km":
        number *= 1.852; suffix = "KM"
    elif s in {"LB", "LBS"} and units.get("weight") == "kg":
        number *= 0.45359237; suffix = "KG"
    text = f"{number:,.{digits}f}"
    return f"{text} {suffix}".strip()



# v0.20.0 fixed-layout graphical PIREP. The interactive browser report remains
# the primary debrief, while this export mirrors the same dark analysis hierarchy.
def _unit_pref(kind: str) -> str:
    units = load_settings().get("interface", {}).get("units", {})
    if kind == "weight":
        return "KG" if units.get("weight") == "kg" else "LB"
    return ""


def _fuel_value(value_lb: Any) -> float | None:
    n = _number(value_lb)
    if n is None:
        return None
    return n * 0.45359237 if _unit_pref("weight") == "KG" else n


def _fuel_label(label: str = "FUEL") -> str:
    return f"{label} ({_unit_pref('weight')})"


def _samples_with_fuel_units(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted = []
    for row in samples:
        item = dict(row)
        if _number(item.get("fuel_total_lb")) is not None:
            item["fuel_total_display"] = _fuel_value(item.get("fuel_total_lb"))
        if _number(item.get("fuel_used_lb")) is not None:
            item["fuel_used_display"] = _fuel_value(item.get("fuel_used_lb"))
        converted.append(item)
    return converted


def _pdf_v(value: Any) -> float | None:
    return _number(value)


def _pdf_series(rows: list[dict[str, Any]], x_key: str, y_key: str, limit: int = 900) -> list[tuple[float, float]]:
    points = []
    for row in rows:
        x, y = _pdf_v(row.get(x_key)), _pdf_v(row.get(y_key))
        if x is not None and y is not None:
            points.append((x, y))
    if len(points) <= limit:
        return points
    step = max(1, len(points) // limit)
    reduced = points[::step]
    if reduced[-1] != points[-1]:
        reduced.append(points[-1])
    return reduced


def _pdf_extent(values: list[float], include_zero: bool = False, pad: float = .07) -> tuple[float, float]:
    clean = [float(x) for x in values if math.isfinite(float(x))]
    if not clean:
        return 0.0, 1.0
    lo, hi = min(clean), max(clean)
    if include_zero:
        lo, hi = min(lo, 0.0), max(hi, 0.0)
    if lo == hi:
        lo -= 1.0; hi += 1.0
    margin = (hi - lo) * pad
    return lo - margin, hi + margin


def _pdf_color(hex_value: str):
    from reportlab.lib.colors import HexColor
    return HexColor(hex_value)


def _pdf_base_page(c, title: str, route: str, page_no: int, page_total: int, score: Any = None) -> None:
    from reportlab.lib.pagesizes import A4, landscape
    width, height = landscape(A4)
    c.setFillColor(_pdf_color('#07090a')); c.rect(0, 0, width, height, stroke=0, fill=1)
    c.setStrokeColor(_pdf_color('#353c42')); c.setLineWidth(.7); c.line(22, height - 44, width - 22, height - 44)
    c.setFillColor(_pdf_color('#f4f1e9')); c.setFont('Helvetica-Bold', 12); c.drawString(24, height - 28, 'OPS ROOM')
    c.setFillColor(_pdf_color('#68c8d9')); c.setFont('Helvetica-Bold', 7.5); c.drawString(96, height - 28, 'FLIGHT ANALYSIS')
    c.setFillColor(_pdf_color('#f4f1e9')); c.setFont('Helvetica-Bold', 15); c.drawCentredString(width / 2, height - 28, title)
    c.setFillColor(_pdf_color('#9ba4aa')); c.setFont('Helvetica', 8); c.drawRightString(width - 24, height - 28, route)
    c.setFillColor(_pdf_color('#778188')); c.setFont('Helvetica', 6.5); c.drawString(24, 13, f'OPS ROOM v{_export_version()}')
    c.drawRightString(width - 24, 13, f'PAGE {page_no} / {page_total}')
    if score is not None:
        c.setFillColor(_pdf_color('#68c8d9')); c.setFont('Helvetica-Bold', 10); c.drawRightString(width - 24, height - 53, f'SCORE {score} / 100')


def _pdf_card(c, x: float, y: float, w: float, h: float, title: str = '', subtitle: str = '') -> tuple[float, float, float, float]:
    c.setFillColor(_pdf_color('#0f1214')); c.setStrokeColor(_pdf_color('#2b3237')); c.setLineWidth(.7)
    c.roundRect(x, y, w, h, 8, stroke=1, fill=1)
    if title:
        c.setFillColor(_pdf_color('#dfe3e5')); c.setFont('Helvetica-Bold', 8); c.drawString(x + 14, y + h - 19, title.upper())
    if subtitle:
        c.setFillColor(_pdf_color('#8f999f')); c.setFont('Helvetica', 7); c.drawRightString(x + w - 14, y + h - 19, subtitle)
    return x + 14, y + 12, w - 28, h - (34 if title else 24)


def _pdf_metric_strip(c, metrics: list[tuple[str, str]], x: float, y: float, w: float, h: float) -> None:
    if not metrics:
        return
    c.setStrokeColor(_pdf_color('#2a3035')); c.setLineWidth(.6); c.line(x, y + h, x + w, y + h)
    cell = w / len(metrics)
    for index, (label, value) in enumerate(metrics):
        left = x + index * cell
        if index:
            c.line(left, y + 5, left, y + h - 5)
        c.setFillColor(_pdf_color('#a8b0b5')); c.setFont('Helvetica', 6.4); c.drawString(left + 8, y + h - 15, str(label))
        c.setFillColor(_pdf_color('#f5f2e9')); c.setFont('Helvetica-Bold', 12.2); c.drawString(left + 8, y + 10, str(value))


def _pdf_line_chart(c, x: float, y: float, w: float, h: float, rows: list[dict[str, Any]], x_key: str,
                    series: list[tuple[str, str, str, str]], title: str, x_label: str = '', include_zero: bool = False) -> None:
    # series entries: key, label, colour, axis ('left' or 'right')
    ix, iy, iw, ih = _pdf_card(c, x, y, w, h, title)
    left_series = [item for item in series if item[3] != 'right']
    right_series = [item for item in series if item[3] == 'right']
    x_factor = (1.0 / 60.0) if x_key == 'elapsed_seconds' else 1.0
    if x_key == 'elapsed_seconds':
        x_label = (x_label or 'ELAPSED SECONDS').replace('SECONDS', 'MINUTES').replace('SEC', 'MIN')
    prepared = {key: [(px * x_factor, py) for px, py in _pdf_series(rows, x_key, key)] for key, _label, _colour, _axis in series}
    all_x = [px for points in prepared.values() for px, _py in points]
    if not all_x:
        c.setFillColor(_pdf_color('#89949a')); c.setFont('Helvetica-Bold', 8); c.drawCentredString(ix + iw / 2, iy + ih / 2, 'INSUFFICIENT TELEMETRY')
        return
    x_lo, x_hi = _pdf_extent(all_x)
    left_values = [py for key, _l, _c, _a in left_series for _px, py in prepared[key]]
    right_values = [py for key, _l, _c, _a in right_series for _px, py in prepared[key]]
    l_lo, l_hi = _pdf_extent(left_values, include_zero=include_zero)
    r_lo, r_hi = _pdf_extent(right_values, include_zero=include_zero) if right_values else (0.0, 1.0)
    plot_x, plot_y, plot_w, plot_h = ix + 39, iy + 24, iw - (72 if right_values else 52), ih - 42
    c.setStrokeColor(_pdf_color('#2d3338')); c.setLineWidth(.45); c.setFont('Helvetica', 5.8)
    for n in range(6):
        yy = plot_y + plot_h * n / 5
        c.line(plot_x, yy, plot_x + plot_w, yy)
        left_value = l_lo + (l_hi - l_lo) * n / 5
        c.setFillColor(_pdf_color('#879198')); c.drawRightString(plot_x - 5, yy - 2, f'{left_value:,.0f}')
        if right_values:
            right_value = r_lo + (r_hi - r_lo) * n / 5
            c.setFillColor(_pdf_color('#ff6364')); c.drawString(plot_x + plot_w + 5, yy - 2, f'{right_value:,.0f}')
    for n in range(7):
        xx = plot_x + plot_w * n / 6
        value = x_lo + (x_hi - x_lo) * n / 6
        c.setFillColor(_pdf_color('#879198')); c.drawCentredString(xx, plot_y - 12, f'{value:,.0f}')
    def map_point(px: float, py: float, axis: str) -> tuple[float, float]:
        xx = plot_x + (px - x_lo) / max(1e-9, x_hi - x_lo) * plot_w
        lo, hi = (r_lo, r_hi) if axis == 'right' else (l_lo, l_hi)
        yy = plot_y + (py - lo) / max(1e-9, hi - lo) * plot_h
        return xx, yy
    legend_x = ix + 3
    for key, label, colour, axis in series:
        points = prepared[key]
        if len(points) >= 2:
            c.setStrokeColor(_pdf_color(colour)); c.setLineWidth(1.6)
            path = c.beginPath()
            first = True
            for px, py in points:
                xx, yy = map_point(px, py, axis)
                if first: path.moveTo(xx, yy); first = False
                else: path.lineTo(xx, yy)
            c.drawPath(path, stroke=1, fill=0)
        c.setStrokeColor(_pdf_color(colour)); c.setLineWidth(1.8); c.line(legend_x, iy + ih - 9, legend_x + 10, iy + ih - 9)
        c.setFillColor(_pdf_color('#bdc4c8')); c.setFont('Helvetica', 6.2); c.drawString(legend_x + 14, iy + ih - 11, label)
        legend_x += 18 + max(34, len(label) * 4.2)
    if x_label:
        c.setFillColor(_pdf_color('#7f8a90')); c.setFont('Helvetica', 5.8); c.drawCentredString(plot_x + plot_w / 2, iy + 2, x_label)


def _pdf_xy_chart(c, x: float, y: float, w: float, h: float, rows: list[dict[str, Any]], x_key: str,
                  y_key: str, title: str, colour: str = '#8b63e8', x_zero: bool = False) -> None:
    _pdf_line_chart(c, x, y, w, h, rows, x_key, [(y_key, 'AIRCRAFT PATH', colour, 'left')], title, include_zero=x_zero)


def _pdf_runway_chart(c, x: float, y: float, w: float, h: float, data: dict[str, Any], title: str, landing: bool) -> None:
    ix, iy, iw, ih = _pdf_card(c, x, y, w, h, title, f"RWY {data.get('runway') or '----'}")
    length = max(3000.0, _pdf_v(data.get('runway_length_ft')) or 8000.0)
    width_ft = max(80.0, _pdf_v(data.get('runway_width_ft')) or 150.0)
    path = [row for row in (data.get('runway_path') or []) if _pdf_v(row.get('along_ft')) is not None and _pdf_v(row.get('deviation_ft')) is not None]
    max_dev = max([width_ft * .8] + [abs(float(row.get('deviation_ft') or 0.0)) for row in path])
    cross = max(width_ft * 1.75, min(width_ft * 5.0, max_dev * 1.18), 260.0)
    runway_x, runway_w = ix + 34, iw - 68
    plot_y, plot_h = iy + 30, max(58, ih - 68)
    centre_y = plot_y + plot_h / 2.0
    def x_at(feet: float, clamp: bool = True) -> float:
        value = max(0.0, min(length, feet)) if clamp else feet
        return runway_x + value / length * runway_w
    def y_at(dev: float) -> float:
        return centre_y - dev / cross * (plot_h / 2.0)
    top_y, bottom_y = y_at(width_ft / 2.0), y_at(-width_ft / 2.0)
    threshold_offset = max(0.0, _pdf_v(data.get('displaced_threshold_ft')) or 0.0)
    threshold_x = x_at(threshold_offset)
    lda = _pdf_v(data.get('lda_ft')) or max(0.0, length - threshold_offset)

    c.setStrokeColor(_pdf_color('#30383e')); c.setLineWidth(.45)
    for dev in (-width_ft, -width_ft/2, 0.0, width_ft/2, width_ft):
        yy = y_at(dev); c.line(runway_x, yy, runway_x + runway_w, yy)
    c.setFillColor(_pdf_color('#6b7a86')); c.setFont('Helvetica', 5.8)
    c.drawRightString(runway_x - 4, y_at(width_ft/2)-2, f'L {width_ft/2:.0f}ft')
    c.drawRightString(runway_x - 4, y_at(0)-2, 'CL')
    c.drawRightString(runway_x - 4, y_at(-width_ft/2)-2, f'R {width_ft/2:.0f}ft')

    c.setFillColor(_pdf_color('#56616d')); c.setStrokeColor(_pdf_color('#dfe4e6')); c.setLineWidth(.45); c.rect(runway_x, top_y, runway_w, bottom_y - top_y, stroke=1, fill=1)
    if threshold_offset > 1:
        c.setFillColor(_pdf_color('#6e7b89')); c.rect(runway_x, top_y, threshold_x - runway_x, bottom_y - top_y, stroke=0, fill=1)
        c.setStrokeColor(_pdf_color('#e5e8e9')); c.setLineWidth(.45); c.line(threshold_x, top_y, threshold_x, bottom_y)
    if landing:
        c.setFillColor(_pdf_color('#225b3d')); c.rect(threshold_x, top_y, max(0, x_at(min(length, threshold_offset + 3000)) - threshold_x), bottom_y - top_y, stroke=0, fill=1)
    c.setStrokeColor(_pdf_color('#e8ecee')); c.setLineWidth(.55); c.setDash(7, 8); c.line(runway_x, y_at(0), runway_x + runway_w, y_at(0)); c.setDash()
    c.setFillColor(_pdf_color('#e5e8e9'))
    for i in range(-4, 5):
        if i == 0: continue
        yy = y_at(i * width_ft / 12.0)
        if top_y < yy < bottom_y:
            c.rect(threshold_x + 2, yy - .75, max(2.8, runway_w * .0055), 1.5, stroke=0, fill=1)
    if landing:
        def pair(distance_ft: float, bar_w: float, bar_h: float):
            if threshold_offset + distance_ft >= length: return
            xx = x_at(threshold_offset + distance_ft)
            c.rect(xx - bar_w / 2, y_at(width_ft * .22) - bar_h / 2, bar_w, bar_h, stroke=0, fill=1)
            c.rect(xx - bar_w / 2, y_at(-width_ft * .22) - bar_h / 2, bar_w, bar_h, stroke=0, fill=1)
        pair(1000.0, max(12, runway_w * .040), 3.4)
        for d in (500.0, 1500.0, 2000.0, 2500.0): pair(d, max(5, runway_w * .012), 1.9)
    rwy = str(data.get('runway') or '').replace('RWY', '').strip().upper(); opposite = str(data.get('opposite_runway') or '').replace('RWY', '').strip().upper()
    c.setFillColor(_pdf_color('#f1f4f5')); c.setFont('Helvetica-Bold', max(6, min(11, (bottom_y-top_y)*.22)))
    def draw_ident(text: str, xx: float, yy: float, angle: float):
        c.saveState(); c.translate(xx, yy); c.rotate(angle); c.drawCentredString(0, -3, text); c.restoreState()
    if rwy: draw_ident(rwy, min(threshold_x + max(18, runway_w*.038), x_at(threshold_offset+420)), y_at(0), -90)
    if opposite: draw_ident(opposite, max(runway_x+runway_w-max(18, runway_w*.038), x_at(length-420)), y_at(0), 90)
    for thousand in range(0, int(length // 1000) + 1):
        xx = x_at(thousand * 1000.0)
        c.setStrokeColor(_pdf_color('#7c878c')); c.line(xx, bottom_y, xx, bottom_y - 3)
        c.setFillColor(_pdf_color('#69767b')); c.setFont('Helvetica', 5.8); c.drawCentredString(xx, iy + 10, f'{thousand * 1000}')
    def mapped(row):
        return x_at(float(row.get('along_ft') or 0), clamp=False), y_at(float(row.get('deviation_ft') or 0))
    display = [row for row in path if -450.0 <= float(row.get('along_ft') or 0) <= length + 450.0 and abs(float(row.get('deviation_ft') or 0)) <= cross * .98]
    if len(display) >= 2:
        c.setStrokeColor(_pdf_color('#3e8cf5')); c.setLineWidth(1.15); pth = c.beginPath()
        for idx, row in enumerate(display):
            xx, yy = mapped(row)
            if idx == 0: pth.moveTo(xx, yy)
            else: pth.lineTo(xx, yy)
        c.drawPath(pth, stroke=1, fill=0)
        c.setFillColor(_pdf_color('#f2b94b'))
        for row in display[:180]:
            if abs(float(row.get('deviation_ft') or 0)) > width_ft / 2.0:
                xx, yy = mapped(row); c.circle(xx, yy, 1.2, stroke=0, fill=1)
    if landing:
        marker = {'along_ft': _pdf_v(data.get('touchdown_distance_ft')) or 0, 'deviation_ft': _pdf_v(data.get('touchdown_centerline_deviation_ft')) or 0}; label = 'TD'
    elif path:
        target = _pdf_v(data.get('liftoff_distance_ft'))
        marker = min(path, key=lambda row: abs(float(row.get('along_ft') or 0) - target)) if target is not None else path[-1]; label = 'LO'
    else:
        marker = None; label = ''
    if marker:
        xx, yy = mapped(marker); c.setFillColor(_pdf_color('#2bcf72')); c.setStrokeColor(_pdf_color('#ffffff')); c.setLineWidth(.65); c.circle(xx, yy, 4.0, stroke=1, fill=1)
        c.setFillColor(_pdf_color('#071012')); c.setFont('Helvetica-Bold', 4.1); c.drawCentredString(xx, yy-1.4, label)
    c.setFillColor(_pdf_color('#8f999f')); c.setFont('Helvetica', 6); c.drawString(runway_x, iy + 2, 'THRESHOLD')
    c.drawRightString(runway_x + runway_w, iy + 2, f'{lda:,.0f} FT LDA  |  {length:,.0f} FT x {width_ft:,.0f} FT')


def _pdf_route_chart(c, x: float, y: float, w: float, h: float, samples: list[dict[str, Any]], route: list[dict[str, Any]]) -> None:
    ix, iy, iw, ih = _pdf_card(c, x, y, w, h, 'ACTUAL TRACK / PLANNED ROUTE')
    actual_ll = [(float(row['lon']), float(row['lat'])) for row in samples if _pdf_v(row.get('lat')) is not None and _pdf_v(row.get('lon')) is not None]
    planned_ll = [(float(row['lon']), float(row['lat'])) for row in route if _pdf_v(row.get('lat')) is not None and _pdf_v(row.get('lon')) is not None]
    if len(actual_ll) < 2:
        c.setFillColor(_pdf_color('#89949a')); c.setFont('Helvetica-Bold', 8); c.drawCentredString(ix + iw / 2, iy + ih / 2, 'INSUFFICIENT POSITION DATA'); return
    all_ll = actual_ll + planned_ll
    lat0 = sum(lat for _lon, lat in all_ll) / max(1, len(all_ll))
    scale_lon = max(.15, math.cos(math.radians(lat0)))
    def to_xy(item: tuple[float, float]) -> tuple[float, float]:
        lon, lat = item
        return lon * 60.0 * scale_lon, lat * 60.0
    actual = [to_xy(p) for p in actual_ll]
    planned = [to_xy(p) for p in planned_ll]
    all_points = actual + planned
    min_x, max_x = min(v[0] for v in all_points), max(v[0] for v in all_points)
    min_y, max_y = min(v[1] for v in all_points), max(v[1] for v in all_points)
    span_x, span_y = max(max_x - min_x, 1e-6), max(max_y - min_y, 1e-6)
    pad = 10
    plot_x, plot_y, plot_w, plot_h = ix + pad, iy + pad, iw - pad * 2, ih - pad * 2
    scale = min(plot_w / span_x, plot_h / span_y)
    used_w, used_h = span_x * scale, span_y * scale
    off_x, off_y = plot_x + (plot_w - used_w) / 2.0, plot_y + (plot_h - used_h) / 2.0
    def point(item): return off_x + (item[0] - min_x) * scale, off_y + (item[1] - min_y) * scale
    c.setStrokeColor(_pdf_color('#343b40')); c.rect(plot_x, plot_y, plot_w, plot_h, stroke=1, fill=0)
    for data, colour, dash in ((planned, '#7d8790', True), (actual, '#68c8d9', False)):
        if len(data) < 2: continue
        c.setStrokeColor(_pdf_color(colour)); c.setLineWidth(1.5); c.setDash(6, 4) if dash else c.setDash()
        pth = c.beginPath()
        for idx, item in enumerate(data):
            xx, yy = point(item)
            if idx == 0: pth.moveTo(xx, yy)
            else: pth.lineTo(xx, yy)
        c.drawPath(pth, stroke=1, fill=0); c.setDash()
    for item, colour in ((actual[0], '#2bcf72'), (actual[-1], '#ff595b')):
        xx, yy = point(item); c.setFillColor(_pdf_color(colour)); c.circle(xx, yy, 3.5, stroke=0, fill=1)
    c.setFillColor(_pdf_color('#7f8a90')); c.setFont('Helvetica', 5.8); c.drawString(ix + 3, iy + 3, 'Aspect-ratio preserved')


def _pdf_phase_strip(c, x: float, y: float, w: float, h: float, samples: list[dict[str, Any]]) -> None:
    rows = [(float(row.get('elapsed_seconds') or 0), str(row.get('phase') or '')) for row in samples if row.get('phase')]
    if not rows: return
    segments = []; start, phase = rows[0]
    for elapsed, current in rows[1:]:
        if current != phase:
            segments.append((start, elapsed, phase)); start, phase = elapsed, current
    end = max(rows[-1][0], 1.0); segments.append((start, end, phase))
    colours = ['#315e6b','#394f7a','#6a4f86','#825634','#476744','#79524d','#655c35','#3f5968']
    c.setFillColor(_pdf_color('#101315')); c.setStrokeColor(_pdf_color('#2b3237')); c.rect(x, y, w, h, stroke=1, fill=1)
    for idx, (a, b, name) in enumerate(segments):
        left = x + a / end * w; sw = max(1, (b - a) / end * w)
        c.setFillColor(_pdf_color(colours[idx % len(colours)])); c.rect(left, y, sw, h, stroke=0, fill=1)
        if sw > 50:
            c.setFillColor(_pdf_color('#ffffff')); c.setFont('Helvetica-Bold', 5.5); c.drawCentredString(left + sw / 2, y + h / 2 - 2, name[:18])


def _pdf_text_metrics(data: dict[str, Any], items: list[tuple[str, str, int]]) -> list[tuple[str, str]]:
    result = []
    for label, key, digits in items:
        value = _pdf_v(data.get(key))
        result.append((label, '-' if value is None else f'{value:,.{digits}f}'))
    return result


def _build_detailed_pdf(entries: list[dict[str, Any]], telemetry_map: dict[str, dict[str, Any]]) -> bytes:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas
    buffer = io.BytesIO(); width, height = landscape(A4); c = canvas.Canvas(buffer, pagesize=(width, height), pageCompression=1)
    page_total = 5
    for entry in entries:
        f = entry.get('flight') or {}; a = entry.get('aircraft') or {}; d = entry.get('durations') or {}; m = entry.get('metrics') or {}; fuel = entry.get('fuel') or {}; times = entry.get('times') or {}; de = entry.get('debrief') or {}
        telemetry_payload = telemetry_map.get(entry.get('id')) or {}; samples = telemetry_payload.get('samples') or []; route = telemetry_payload.get('route') or []; analysis = telemetry_payload.get('analysis') or entry.get('analysis_summary') or {}
        dep = analysis.get('departure') or {}; enr = analysis.get('enroute') or {}; app = analysis.get('approach') or {}; land = analysis.get('landing') or {}; score = analysis.get('score') or de
        callsign = f.get('callsign') or 'FLIGHT'; origin = f.get('origin') or '----'; destination = f.get('destination') or '----'; route_label = f'{callsign}  |  {origin} > {destination}'
        score_value = score.get('overall', de.get('score', '-')) if isinstance(score, dict) else de.get('score', '-')

        # Page 1 - full flight overview
        _pdf_base_page(c, 'FLIGHT OVERVIEW', route_label, 1, page_total, score_value)
        x0, y0, content_w = 24, 42, width - 48
        _pdf_card(c, x0, height - 152, content_w, 92, '', '')
        c.setFillColor(_pdf_color('#f5f2e9')); c.setFont('Helvetica-Bold', 32); c.drawString(x0 + 18, height - 105, origin)
        c.setFillColor(_pdf_color('#68c8d9')); c.setFont('Helvetica-Bold', 20); c.drawCentredString(x0 + 150, height - 105, '>')
        c.setFillColor(_pdf_color('#f5f2e9')); c.setFont('Helvetica-Bold', 32); c.drawString(x0 + 185, height - 105, destination)
        c.setFillColor(_pdf_color('#9da6ac')); c.setFont('Helvetica', 8); aircraft = f.get('aircraft_icao') or a.get('type') or a.get('model') or a.get('title') or '-'; registration = f.get('registration') or '-'
        c.drawString(x0 + 18, height - 132, f'{aircraft}  |  {registration}  |  {str(entry.get("telemetry_source") or "-").upper()}')
        c.setFillColor(_pdf_color('#68c8d9')); c.setFont('Helvetica-Bold', 34); c.drawRightString(x0 + content_w - 20, height - 103, str(score_value))
        c.setFillColor(_pdf_color('#a4adb2')); c.setFont('Helvetica-Bold', 7); c.drawRightString(x0 + content_w - 20, height - 124, str(score.get('grade') or de.get('landing_grade') or 'NOT GRADED'))
        overview_metrics = [('BLOCK', _fmt_duration(d.get('block_seconds'))),('AIRBORNE', _fmt_duration(d.get('airborne_seconds'))),('DISTANCE', _fmt_metric(m.get('distance_nm'), 'NM', 1)),('FUEL USED', _fmt_metric(fuel.get('used_lb'), 'LB')),('LANDING', _fmt_metric(m.get('landing_rate_fpm'), 'FPM')),('TOUCHDOWN G', f"{(_pdf_v(m.get('touchdown_g')) or 0):.2f} G")]
        _pdf_metric_strip(c, overview_metrics, x0, height - 214, content_w, 52)
        _pdf_line_chart(c, x0, 104, content_w, 258, samples, 'elapsed_seconds', [('altitude_ft','ALTITUDE (FT)','#3b8df7','left'),('ground_speed_kts','GROUNDSPEED (KT)','#ff4d4f','right')], 'ALTITUDE / GROUNDSPEED PROFILE', 'ELAPSED SECONDS', include_zero=True)
        _pdf_phase_strip(c, x0, 72, content_w, 24, samples)
        c.setFillColor(_pdf_color('#9ca5aa')); c.setFont('Helvetica', 6.5); c.drawString(x0, 58, f"TAKEOFF {str(times.get('takeoff') or '-')[11:19]} UTC  |  LANDING {str(times.get('landing') or '-')[11:19]} UTC  |  SAMPLES {entry.get('sample_count') or 0}")
        c.showPage()

        # Page 2 - departure
        _pdf_base_page(c, 'DEPARTURE ANALYSIS', route_label, 2, page_total, score_value)
        _pdf_xy_chart(c, 24, 274, 252, 250, dep.get('lateral_profile') or [], 'deviation_ft', 'distance_nm', 'LATERAL PROFILE', '#8b63e8', True)
        _pdf_line_chart(c, 292, 274, width - 316, 250, dep.get('climb_profile') or [], 'distance_nm', [('altitude_agl_ft','ALTITUDE AGL (FT)','#3b8df7','left'),('ground_speed_kts','GROUNDSPEED (KT)','#ff4d4f','right')], 'CLIMB PROFILE', 'DISTANCE FLOWN (NM)', include_zero=True)
        _pdf_runway_chart(c, 24, 106, width - 48, 150, dep, 'TAKEOFF RUNWAY PROFILE', False)
        dep_metrics = [('LIFTOFF SPEED',_fmt_metric(dep.get('liftoff_speed_kts'),'KT')),('PITCH',_fmt_metric(dep.get('liftoff_pitch_deg'),'DEG',1)),('BANK',_fmt_metric(dep.get('liftoff_bank_deg'),'DEG',1)),('TAKEOFF ROLL',_fmt_metric(dep.get('takeoff_roll_ft'),'FT')),('CLIMB GRADIENT',_fmt_metric(dep.get('climb_gradient_ft_nm'),'FT/NM')),('CLIMB RATE',_fmt_metric(dep.get('average_initial_climb_fpm'),'FPM')),('MAX CL DEV',_fmt_metric(dep.get('max_centerline_deviation_ft'),'FT'))]
        _pdf_metric_strip(c, dep_metrics, 24, 42, width - 48, 52)
        c.showPage()

        # Page 3 - enroute and fuel
        _pdf_base_page(c, 'ENROUTE / FUEL ANALYSIS', route_label, 3, page_total, score_value)
        _pdf_route_chart(c, 24, 272, 360, 252, samples, route)
        _pdf_line_chart(c, 400, 272, width - 424, 252, _samples_with_fuel_units(samples), 'elapsed_seconds', [('fuel_total_display',_fuel_label('FUEL REMAINING'),'#68c8d9','left')], 'FUEL PROFILE', 'ELAPSED MINUTES')
        _pdf_line_chart(c, 24, 104, width - 48, 150, samples, 'elapsed_seconds', [('vertical_speed_fpm','VERTICAL SPEED (FPM)','#8b63e8','left'),('cross_track_nm','CROSS TRACK (NM)','#f2b94b','right')], 'VERTICAL SPEED / ROUTE DEVIATION', 'ELAPSED SECONDS', include_zero=True)
        enr_metrics = [('PLANNED DIST',_fmt_metric(enr.get('planned_distance_nm'),'NM',1)),('ACTUAL DIST',_fmt_metric(enr.get('actual_distance_nm'),'NM',1)),('DIST VAR',_fmt_metric(enr.get('distance_variance_nm'),'NM',1)),('PLANNED FUEL',_fmt_metric(enr.get('planned_trip_fuel'),'LB')),('ACTUAL FUEL',_fmt_metric(enr.get('actual_fuel_used_lb'),'LB')),('FUEL VAR',_fmt_metric(enr.get('fuel_variance'),'LB'))]
        _pdf_metric_strip(c, enr_metrics, 24, 42, width - 48, 50)
        c.showPage()

        # Page 4 - approach
        _pdf_base_page(c, 'APPROACH ANALYSIS', route_label, 4, page_total, score_value)
        _pdf_xy_chart(c, 24, 254, 252, 270, app.get('profile') or [], 'lateral_deviation_ft', 'nm_to_threshold', 'LATERAL PROFILE', '#8b63e8', True)
        _pdf_line_chart(c, 292, 254, width - 316, 270, app.get('profile') or [], 'nm_to_threshold', [('approach_agl_ft','ALTITUDE AGL (FT)','#3b8df7','left'),('ground_speed_kts','GROUNDSPEED (KT)','#ff4d4f','right'),('ideal_3deg_agl_ft','3 DEG PATH','#7f91a3','left')], 'APPROACH PROFILE', 'NM TO THRESHOLD', include_zero=True)
        gates = [('1000 FT', app.get('stability_1000') or {}), ('500 FT', app.get('stability_500') or {})]
        gx = 24
        for label, gate in gates:
            stable = gate.get('stable'); colour = '#2bcf72' if stable is True else '#ff6767' if stable is False else '#89949a'
            _pdf_card(c, gx, 116, 386, 116, f'STABILITY GATE {label}', 'STABLE' if stable is True else 'UNSTABLE' if stable is False else 'NO DATA')
            c.setFillColor(_pdf_color(colour)); c.rect(gx + 12, 128, 4, 82, stroke=0, fill=1)
            checks = gate.get('checks') or []
            for idx, check in enumerate(checks[:6]):
                row_y = 196 - idx * 13
                c.setFillColor(_pdf_color('#9ca5aa')); c.setFont('Helvetica', 6.2); c.drawString(gx + 26, row_y, str(check.get('label') or 'CHECK'))
                c.setFillColor(_pdf_color('#f4f1e9' if check.get('ok') else '#ff7f77')); c.setFont('Helvetica-Bold', 6.6); c.drawRightString(gx + 370, row_y, str(check.get('value') or '-'))
            gx += 406
        app_metrics = [('MAX LAT DEV',_fmt_metric(app.get('max_lateral_deviation_ft'),'FT')),('MAX VERT DEV',_fmt_metric(app.get('max_glidepath_deviation_ft'),'FT')),('GEAR DOWN',_fmt_metric(app.get('gear_down_distance_nm'),'NM',1)),('LANDING FLAP',_fmt_metric(app.get('landing_flap_distance_nm'),'NM',1)),('RUNWAY',str(app.get('runway') or '----'))]
        _pdf_metric_strip(c, app_metrics, 24, 42, width - 48, 58)
        c.showPage()

        # Page 5 - landing and review
        _pdf_base_page(c, 'LANDING ANALYSIS', route_label, 5, page_total, score_value)
        _pdf_runway_chart(c, 24, 344, width - 48, 180, land, 'TOUCHDOWN / ROLLOUT RUNWAY PROFILE', True)
        land_metrics = [('RATE',_fmt_metric(land.get('touchdown_rate_fpm'),'FPM')),('G-FORCE',_fmt_metric(land.get('touchdown_g'),'G',2)),('TD POINT',_fmt_metric(land.get('touchdown_distance_ft'),'FT')),('RUNWAY USED',_fmt_metric(land.get('touchdown_percent'),'%',1)),('ROLLOUT',_fmt_metric(land.get('rollout_distance_ft'),'FT')),('SPEED',_fmt_metric(land.get('touchdown_speed_kts'),'KT')),('PITCH',_fmt_metric(land.get('touchdown_pitch_deg'),'DEG',1)),('BANK',_fmt_metric(land.get('touchdown_bank_deg'),'DEG',1))]
        _pdf_metric_strip(c, land_metrics, 24, 280, width - 48, 52)
        landing_window = [row for row in samples if _pdf_v(row.get('seconds_to_touchdown')) is not None and -90 <= float(row.get('seconds_to_touchdown')) <= 60]
        _pdf_line_chart(c, 24, 82, 390, 180, landing_window, 'seconds_to_touchdown', [('pitch_deg','PITCH','#3b8df7','left'),('bank_deg','BANK','#8b63e8','left')], 'LANDING ATTITUDE', 'SECONDS FROM TOUCHDOWN', include_zero=True)
        _pdf_line_chart(c, 430, 82, width - 454, 180, landing_window, 'seconds_to_touchdown', [('g_force','G-FORCE','#2bcf72','left'),('radio_altitude_ft','RADIO ALT (FT)','#68c8d9','right')], 'TOUCHDOWN DETAIL', 'SECONDS FROM TOUCHDOWN', include_zero=True)
        flags = entry.get('violations') or []
        c.setFillColor(_pdf_color('#9ca5aa')); c.setFont('Helvetica', 6.5); c.drawString(24, 57, f"{len(flags)} RECORDED DEVIATIONS  |  TOUCHDOWNS {land.get('touchdowns') or m.get('touchdowns') or '-'}  |  GRADE {score.get('grade') or de.get('landing_grade') or '-'}")
        c.showPage()
    c.save(); return buffer.getvalue()


def _browser_candidates() -> list[str]:
    """Return installed Chromium-family browsers suitable for printing the Full PIREP DOM."""
    configured = str(os.environ.get("OPSROOM_BROWSER_EXE") or "").strip()
    candidates: list[str] = [configured] if configured else []
    if os.name == "nt":
        roots = [
            os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"),
            os.environ.get("LOCALAPPDATA"),
        ]
        suffixes = [
            r"Microsoft\Edge\Application\msedge.exe",
            r"Google\Chrome\Application\chrome.exe",
            r"Chromium\Application\chrome.exe",
        ]
        for base in roots:
            if base:
                candidates.extend(str(Path(base) / suffix) for suffix in suffixes)
    for name in ("msedge", "microsoft-edge", "google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    result: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        if not value:
            continue
        path = str(Path(value).expanduser())
        key = os.path.normcase(os.path.abspath(path))
        if key not in seen and Path(path).is_file():
            seen.add(key); result.append(path)
    return result


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _devtools_json(url: str, timeout: float = 0.6) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "OPS ROOM PDF Renderer"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - loopback DevTools endpoint
        return json.loads(response.read().decode("utf-8", "replace"))


def _stop_pdf_browser(process: subprocess.Popen[bytes] | None) -> None:
    """Stop Chromium and its crash-handler children before profile cleanup."""
    if process is None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3.0,
                creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
                check=False,
            )
        except Exception:
            pass
    if process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=1.5)
        except Exception:
            try:
                process.kill()
                process.wait(timeout=1.0)
            except Exception:
                pass


def _pdf_renderer_log(lines: list[str]) -> None:
    """Persist the last renderer attempt without interrupting PDF delivery."""
    try:
        path = app_data_dir() / "pirep-pdf-renderer.log"
        stamp = _utc_now()
        path.write_text(stamp + "\n" + "\n".join(str(line) for line in lines[-80:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def _pirep_snapshot_html(entry_id: str, settings_payload: dict[str, Any] | None = None) -> str:
    """Build the exact Full PIREP page as one self-contained HTML document.

    The normal interactive page remains unchanged. For PDF export we inject the
    already-stored entry, telemetry and public unit settings, then inline the same
    CSS and JavaScript used by /pirep/{id}. The headless browser therefore never
    needs to navigate to localhost or race asynchronous API calls.
    """
    entry = get_entry(entry_id)
    flight_branding = ((entry.get("flight") or {}).get("airline_branding") or {}) if isinstance(entry.get("flight"), dict) else {}
    embedded_logo = logo_data_uri(flight_branding)
    if embedded_logo:
        flight_branding["logo_data_uri"] = embedded_logo
    telemetry_payload = telemetry(entry_id, max_points=5000)
    public_settings = settings_payload if isinstance(settings_payload, dict) else {
        "interface": dict((load_settings().get("interface") or {})),
    }
    static_dir = Path(__file__).resolve().parent / "static"
    template = (static_dir / "pirep.html").read_text(encoding="utf-8")
    css_text = (static_dir / "pirep.css").read_text(encoding="utf-8")
    js_text = (static_dir / "pirep.js").read_text(encoding="utf-8")
    print_css = (static_dir / "pirep_print.css").read_text(encoding="utf-8")
    print_js = (static_dir / "pirep_print.js").read_text(encoding="utf-8")
    try:
        from .ofp_actuals import build_live_ofp_actuals, plan_from_entry
        ofp_completion = build_live_ofp_actuals(plan_from_entry(entry), None, completed_entry=entry, overrides=_manual_overrides(entry_id))
    except Exception:
        ofp_completion = {"ok": False, "state": "unavailable", "reason": "OFP completion build failed"}
    payload = json.dumps(
        {"entry": entry, "telemetry": telemetry_payload, "settings": public_settings, "ofp_completion": ofp_completion},
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    template = template.replace('<link rel="icon" href="/static/favicon.svg" type="image/svg+xml" />', "")
    template = template.replace('<link rel="icon" href="/static/favicon-32.png" sizes="32x32" />', "")
    # Version-agnostic asset inlining: the cache-busting ?v= query on the
    # pirep.css/pirep.js tags changes between releases, so an exact-string
    # replace silently no-ops once the version bumps and the PDF renders
    # without any CSS or scripts. Match the tag regardless of the version value
    # and warn loudly if it is ever missing instead of failing silently.
    # NOTE: the replacements are passed as callables, never as literal strings,
    # because pirep.js contains backslash sequences (e.g. /^RWY\s*/i) that
    # re.sub would interpret as escape codes and reject with "bad escape".
    css_tag = re.search(r'<link rel="stylesheet" href="/static/pirep\.css\?v=[^"]*">', template)
    js_tag = re.search(r'<script src="/static/pirep\.js\?v=[^"]*"></script>', template)
    if not css_tag or not js_tag:
        import logging as _logging_pdf_snapshot

        _logging_pdf_snapshot.getLogger("opsroom.logbook").warning(
            "Full PIREP PDF snapshot: pirep.css/pirep.js asset tag not found in pirep.html "
            "(cache-bust version or tag format changed?) -- PDF may render unstyled/broken"
        )
    template = re.sub(
        r'<link rel="stylesheet" href="/static/pirep\.css\?v=[^"]*">',
        lambda _m: f"<style>\n{css_text}\n</style>\n<style>\n{print_css}\n</style>",
        template,
        count=1,
    )
    template = re.sub(
        r'<script src="/static/pirep\.js\?v=[^"]*"></script>',
        lambda _m: f"<script>window.__OPSROOM_PIREP_PRELOADED__={payload};</script>\n<script>\n{js_text}\n</script>\n<script>\n{print_js}\n</script>",
        template,
        count=1,
    )
    return template


def _render_full_pirep_pdf_html(html_text: str, timeout_seconds: float = 60.0) -> bytes | None:
    """Print a self-contained Full PIREP through Edge/Chrome DevTools.

    Chromium is launched at about:blank and receives the HTML with
    Page.setDocumentContent. This avoids managed-browser localhost blocking, proxy
    policy, API-fetch races and the previous temporary-profile cleanup failure.
    """
    if not str(html_text or "").strip():
        return None
    diagnostics: list[str] = []
    for browser in _browser_candidates():
        deadline = time.monotonic() + max(20.0, float(timeout_seconds))
        diagnostics.append(f"browser={browser}")
        with tempfile.TemporaryDirectory(prefix="opsroom-pirep-pdf-", ignore_cleanup_errors=True) as temp_dir:
            profile = Path(temp_dir) / "browser-profile"
            port = _free_local_port()
            command = [
                browser,
                "--headless=new",
                "--disable-gpu",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-breakpad",
                "--disable-crash-reporter",
                "--no-crash-upload",
                "--disable-default-apps",
                "--disable-sync",
                "--hide-scrollbars",
                "--no-first-run",
                "--no-default-browser-check",
                "--remote-allow-origins=*",
                f"--remote-debugging-port={port}",
                "--remote-debugging-address=127.0.0.1",
                f"--user-data-dir={profile}",
                "--window-size=1600,1000",
                "about:blank",
            ]
            if os.name != "nt":
                command.insert(1, "--no-sandbox")
            creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0
            process: subprocess.Popen[bytes] | None = None
            try:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags,
                )
                page: dict[str, Any] | None = None
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        pages = _devtools_json(f"http://127.0.0.1:{port}/json/list")
                        candidates = [row for row in pages if isinstance(row, dict) and row.get("type") == "page"] if isinstance(pages, list) else []
                        page = candidates[0] if candidates else None
                        if page and page.get("webSocketDebuggerUrl"):
                            break
                    except Exception:
                        pass
                    time.sleep(0.12)
                if not page or not page.get("webSocketDebuggerUrl"):
                    diagnostics.append("devtools-page-unavailable")
                    continue
                try:
                    from websockets.sync.client import connect  # type: ignore
                except Exception as exc:
                    diagnostics.append(f"websockets-import={type(exc).__name__}:{exc}")
                    continue
                with connect(
                    str(page["webSocketDebuggerUrl"]),
                    open_timeout=2.5,
                    close_timeout=0.8,
                    ping_interval=None,
                    origin="http://localhost",
                    max_size=None,
                ) as ws:
                    sequence = 0

                    def call(method: str, params: dict[str, Any] | None = None, wait: float = 3.0) -> dict[str, Any]:
                        nonlocal sequence
                        sequence += 1
                        command_id = sequence
                        ws.send(json.dumps({"id": command_id, "method": method, "params": params or {}}))
                        until = min(deadline, time.monotonic() + max(0.3, wait))
                        while time.monotonic() < until:
                            try:
                                raw = ws.recv(timeout=min(0.5, max(0.05, until - time.monotonic())))
                            except TimeoutError:
                                continue
                            message = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8", "replace"))
                            if isinstance(message, dict) and int(message.get("id") or -1) == command_id:
                                return message
                        return {}

                    call("Page.enable")
                    call("Runtime.enable")
                    tree = call("Page.getFrameTree", wait=3.0)
                    frame_id = str((((tree.get("result") or {}).get("frameTree") or {}).get("frame") or {}).get("id") or "")
                    if not frame_id:
                        diagnostics.append("frame-id-unavailable")
                        continue
                    loaded = call("Page.setDocumentContent", {"frameId": frame_id, "html": html_text}, wait=12.0)
                    if loaded.get("error"):
                        diagnostics.append(f"set-content={loaded.get('error')}")
                        continue
                    ready = False
                    last_state: Any = None
                    while time.monotonic() < deadline:
                        response = call(
                            "Runtime.evaluate",
                            {
                                "expression": "({ready:Boolean(window.__OPSROOM_PDF_READY__),pirepReady:Boolean(window.__OPSROOM_PIREP_READY__),state:document.readyState,error:(document.getElementById('errorText')||{}).textContent||'',pages:document.querySelectorAll('.pdf-page').length})",
                                "returnByValue": True,
                            },
                            wait=1.0,
                        )
                        last_state = (((response.get("result") or {}).get("result") or {}).get("value"))
                        if isinstance(last_state, dict) and last_state.get("ready") is True:
                            ready = True
                            break
                        time.sleep(0.12)
                    if not ready:
                        diagnostics.append(f"pirep-not-ready={last_state}")
                        continue
                    call(
                        "Runtime.evaluate",
                        {
                            "expression": "Promise.all([document.fonts?document.fonts.ready:Promise.resolve(),new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(true))))])",
                            "awaitPromise": True,
                            "returnByValue": True,
                        },
                        wait=4.0,
                    )
                    printed = call(
                        "Page.printToPDF",
                        {
                            "printBackground": True,
                            "displayHeaderFooter": False,
                            "preferCSSPageSize": True,
                            "marginTop": 0,
                            "marginBottom": 0,
                            "marginLeft": 0,
                            "marginRight": 0,
                        },
                        wait=max(8.0, deadline - time.monotonic()),
                    )
                    encoded = str(((printed.get("result") or {}).get("data")) or "")
                    if encoded:
                        data = base64.b64decode(encoded)
                        if len(data) > 5000 and data.startswith(b"%PDF-"):
                            diagnostics.append(f"success-bytes={len(data)}")
                            _pdf_renderer_log(diagnostics)
                            return data
                    diagnostics.append(f"print-failed={printed.get('error') or 'empty-data'}")
            except Exception as exc:
                diagnostics.append(f"exception={type(exc).__name__}:{exc}")
            finally:
                _stop_pdf_browser(process)
                if os.name == "nt":
                    time.sleep(0.15)
    _pdf_renderer_log(diagnostics or ["no-supported-browser-found"])
    return None


def _render_full_pirep_pdf(render_url: str, timeout_seconds: float = 32.0) -> bytes | None:
    """Legacy compatibility wrapper retained for callers outside this module."""
    return None


def export_entry_pdf(
    entry_id: str,
    render_url: str | None = None,
    settings_payload: dict[str, Any] | None = None,
) -> bytes:
    entries = [e for e in _rows("", 5000) if e.get("id") == entry_id]
    if not entries:
        raise KeyError("Flight record not found")
    html_text = _pirep_snapshot_html(entry_id, settings_payload=settings_payload)
    rendered = _render_full_pirep_pdf_html(html_text)
    if rendered:
        return rendered
    raise RuntimeError(
        "Full PIREP PDF renderer unavailable. See pirep-pdf-renderer.log in the OPS ROOM data folder for diagnostics."
    )


def export_pdf(query: str = "") -> bytes:
    return _build_pdf(_rows(query, 5000), detailed=False, telemetry_map={})


def _build_pdf(entries: list[dict[str, Any]], detailed: bool, telemetry_map: dict[str, dict[str, Any]]) -> bytes:
    if detailed:
        return _build_detailed_pdf(entries, telemetry_map)
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, CondPageBreak
    buffer=io.BytesIO(); pagesize=A4 if detailed else landscape(A4); doc=SimpleDocTemplate(buffer,pagesize=pagesize,rightMargin=12*mm,leftMargin=12*mm,topMargin=12*mm,bottomMargin=12*mm,title="OPS ROOM PIREP")
    styles=getSampleStyleSheet(); styles.add(ParagraphStyle(name='OpsSmall',parent=styles['BodyText'],fontSize=7.5,leading=9));    story=[Paragraph("OPS ROOM - FLIGHT DEBRIEF / PIREP" if detailed else "OPS ROOM - LOGBOOK EXPORT", styles['Title']),Paragraph(f"Generated {_utc_now()} - OPS ROOM v{_export_version()}",styles['OpsSmall']),Spacer(1,6)]
    if not entries: story.append(Paragraph("No completed flights are available.",styles['BodyText']))
    for index,e in enumerate(entries):
        f=e.get('flight') or {}; a=e.get('aircraft') or {}; t=e.get('times') or {}; d=e.get('durations') or {}; m=e.get('metrics') or {}; fuel=e.get('fuel') or {}; de=e.get('debrief') or {}
        if detailed:
            story.append(Paragraph(f"{f.get('callsign') or 'FLIGHT'} - {f.get('origin') or '----'} TO {f.get('destination') or '----'}",styles['Heading1']))
            summary=[["Aircraft",f.get('aircraft_icao') or a.get('model') or a.get('title') or '-',"Registration",f.get('registration') or '-'],["Telemetry",e.get('telemetry_source') or '-',"Status",e.get('state') or e.get('status') or '-'],["Block time",_fmt_duration(d.get('block_seconds')),"Airborne",_fmt_duration(d.get('airborne_seconds'))],["Distance",f"{m.get('distance_nm') or 0:.1f} NM","Fuel used",_fmt_metric(fuel.get('used_lb'), 'LB')],["Touchdown",f"{m.get('landing_rate_fpm') if m.get('landing_rate_fpm') is not None else '-'} FPM", "Score",f"{de.get('score','-')} / 100"]]
            table=Table(summary,colWidths=[26*mm,55*mm,26*mm,55*mm]); table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.25,colors.grey),('BACKGROUND',(0,0),(0,-1),colors.HexColor('#e9eff0')),('BACKGROUND',(2,0),(2,-1),colors.HexColor('#e9eff0')),('FONTNAME',(0,0),(-1,-1),'Helvetica'),('FONTSIZE',(0,0),(-1,-1),8),('VALIGN',(0,0),(-1,-1),'TOP'),('PADDING',(0,0),(-1,-1),4)])); story += [table,Spacer(1,7)]
            telemetry_payload = telemetry_map.get(e.get('id')) or {}
            samples = telemetry_payload.get("samples") or []
            route = telemetry_payload.get("route") or []
            if samples:
                story.append(_chart_drawing(samples,[('altitude_ft','Actual'),('planned_cruise_altitude_ft','Planned cruise')],"ALTITUDE PROFILE (FT) - TIME IN MINUTES",175*mm,48*mm)); story.append(Spacer(1,3))
                story.append(_chart_drawing(samples,[('ias_kts','IAS'),('ground_speed_kts','GS')],"SPEED PROFILE (KT)",175*mm,48*mm)); story.append(Spacer(1,3))
                story.append(_chart_drawing(samples,[('vertical_speed_fpm','VS')],"VERTICAL SPEED (FPM)",175*mm,48*mm)); story.append(Spacer(1,3))
                story.append(_chart_drawing(_samples_with_fuel_units(samples),[('fuel_total_display',_fuel_label('Fuel remaining'))],_fuel_label('FUEL REMAINING'),175*mm,48*mm)); story.append(Spacer(1,3))
                if any(s.get('cross_track_nm') is not None for s in samples):
                    story.append(_chart_drawing(samples,[('cross_track_nm','Cross track')],"ROUTE CROSS-TRACK DEVIATION (NM)",175*mm,48*mm)); story.append(Spacer(1,3))
                story.append(_track_drawing(samples,175*mm,64*mm,route)); story.append(Spacer(1,4))
                story.append(_phase_timeline_drawing(samples,175*mm,48*mm)); story.append(Spacer(1,5))
                approach = [s for s in samples if s.get('distance_to_touchdown_nm') is not None and 0 <= float(s.get('distance_to_touchdown_nm')) <= 20 and (s.get('seconds_to_touchdown') is None or float(s.get('seconds_to_touchdown')) <= 0)]
                if approach:
                    approach = sorted(approach,key=lambda x: float(x.get('distance_to_touchdown_nm') or 0),reverse=True)
                    story.append(_chart_drawing(approach,[('approach_agl_ft','Actual AGL'),('ideal_3deg_agl_ft','Ideal 3 deg')],"FINAL APPROACH PROFILE (FT AGL VS NM TO TOUCHDOWN)",175*mm,48*mm,x_key='distance_to_touchdown_nm',x_scale=1.0)); story.append(Spacer(1,3))
                    story.append(_chart_drawing(approach,[('glidepath_deviation_ft','Deviation')],"3-DEGREE PATH DEVIATION (FT)",175*mm,48*mm,x_key='distance_to_touchdown_nm',x_scale=1.0)); story.append(Spacer(1,3))
                    story.append(_chart_drawing(approach,[('ias_kts','IAS'),('ground_speed_kts','GS')],"FINAL APPROACH SPEED (KT)",175*mm,48*mm,x_key='distance_to_touchdown_nm',x_scale=1.0)); story.append(Spacer(1,3))
                    story.append(_chart_drawing(approach,[('vertical_speed_fpm','VS')],"FINAL APPROACH VERTICAL SPEED (FPM)",175*mm,48*mm,x_key='distance_to_touchdown_nm',x_scale=1.0)); story.append(Spacer(1,3))
                landing_window = [s for s in samples if s.get('seconds_to_touchdown') is not None and -90 <= float(s.get('seconds_to_touchdown')) <= 60]
                if landing_window:
                    story.append(_chart_drawing(landing_window,[('pitch_deg','Pitch'),('bank_deg','Bank')],"LANDING ATTITUDE (DEG) - SECONDS FROM TOUCHDOWN",175*mm,48*mm,x_key='seconds_to_touchdown',x_scale=1.0)); story.append(Spacer(1,3))
                    story.append(_chart_drawing(landing_window,[('g_force','G force')],"LANDING G-FORCE",175*mm,48*mm,x_key='seconds_to_touchdown',x_scale=1.0)); story.append(Spacer(1,3))
                    story.append(_chart_drawing(landing_window,[('radio_altitude_ft','Radio alt'),('ground_contact_plot','Ground contact')],"TOUCHDOWN / BOUNCE DETAIL",175*mm,48*mm,x_key='seconds_to_touchdown',x_scale=1.0)); story.append(Spacer(1,5))
            analysis_data = telemetry_payload.get("analysis") or e.get("analysis_summary") or {}
            if analysis_data.get("ok"):
                dep = analysis_data.get("departure") or {}
                enroute = analysis_data.get("enroute") or {}
                approach_data = analysis_data.get("approach") or {}
                landing_data = analysis_data.get("landing") or {}
                score_data = analysis_data.get("score") or {}

                story.append(PageBreak())
                story.append(Paragraph("DEPARTURE ANALYSIS", styles['Heading1']))
                story.append(Paragraph(
                    f"Runway {dep.get('runway') or '-'} · heading {_fmt_metric(dep.get('heading_deg'), 'deg', 1)} · geometry {analysis_data.get('geometry_source') or 'telemetry-derived'}",
                    styles['OpsSmall'],
                ))
                story.append(Spacer(1, 5))
                dep_pair = Table([
                    [
                        _analysis_xy_drawing(dep.get('lateral_profile') or [], 'deviation_ft', [('distance_nm','Aircraft path')], 'LATERAL PROFILE - DEVIATION FT / DISTANCE NM', 84*mm, 66*mm),
                        _analysis_xy_drawing(dep.get('climb_profile') or [], 'distance_nm', [('altitude_agl_ft','Altitude AGL'),('ground_speed_kts','Groundspeed')], 'CLIMB PROFILE - DISTANCE NM', 84*mm, 66*mm),
                    ]
                ], colWidths=[87*mm,87*mm])
                dep_pair.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))
                story.append(dep_pair)
                story.append(Spacer(1,4))
                story.append(_runway_analysis_drawing(dep, 'TAKEOFF RUNWAY PROFILE', 175*mm, 63*mm, landing=False))
                story.append(Spacer(1,5))
                story.append(_metric_table([
                    ('Liftoff speed', _fmt_metric(dep.get('liftoff_speed_kts'), 'kt')),
                    ('Pitch', _fmt_metric(dep.get('liftoff_pitch_deg'), 'deg', 1)),
                    ('Bank', _fmt_metric(dep.get('liftoff_bank_deg'), 'deg', 1)),
                    ('Takeoff roll', _fmt_metric(dep.get('takeoff_roll_ft'), 'ft')),
                    ('Roll use', _fmt_metric(dep.get('takeoff_roll_percent'), '%', 1)),
                    ('Climb gradient', _fmt_metric(dep.get('climb_gradient_ft_nm'), 'ft/NM')),
                    ('Climb rate', _fmt_metric(dep.get('average_initial_climb_fpm'), 'fpm')),
                    ('Max centreline deviation', _fmt_metric(dep.get('max_centerline_deviation_ft'), 'ft')),
                    ('Gear up', str(dep.get('gear_up_time') or '-')[11:19]),
                    ('Flaps up', str(dep.get('flaps_up_time') or '-')[11:19]),
                ], columns=3))

                story.append(PageBreak())
                story.append(Paragraph("ENROUTE AND FUEL ANALYSIS", styles['Heading1']))
                enroute_rows = [
                    ('Planned distance', _fmt_metric(enroute.get('planned_distance_nm'), 'NM', 1)),
                    ('Actual distance', _fmt_metric(enroute.get('actual_distance_nm'), 'NM', 1)),
                    ('Distance variance', _fmt_metric(enroute.get('distance_variance_nm'), 'NM', 1)),
                    ('Planned trip fuel', _fmt_metric(enroute.get('planned_trip_fuel'), 'LB')),
                    ('Actual fuel used', _fmt_metric(enroute.get('actual_fuel_used_lb'), 'LB')),
                    ('Fuel variance', _fmt_metric(enroute.get('fuel_variance'), 'LB')),
                    ('Planned block', _fmt_duration(enroute.get('planned_block_seconds'))),
                    ('Actual block', _fmt_duration(enroute.get('actual_block_seconds'))),
                    ('Planned airborne', _fmt_duration(enroute.get('planned_airborne_seconds'))),
                    ('Actual airborne', _fmt_duration(enroute.get('actual_airborne_seconds'))),
                ]
                story.append(_metric_table(enroute_rows, columns=3))
                story.append(Spacer(1,7))
                phase_fuel = enroute.get('fuel_burn_by_phase_lb') or {}
                if phase_fuel:
                    phase_rows = [["PHASE", _fuel_label('FUEL BURN')]] + [[str(key), _fmt_metric(value, 'LB', 0)] for key, value in phase_fuel.items()]
                    phase_table = Table(phase_rows, colWidths=[70*mm,45*mm], repeatRows=1)
                    phase_table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1c353b')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),.25,colors.grey),('FONTSIZE',(0,0),(-1,-1),7),('PADDING',(0,0),(-1,-1),4)]))
                    story.append(phase_table)
                story.append(Spacer(1,8))
                breakdown = score_data.get('breakdown') or {}
                score_rows = [["AREA", "SCORE", "MAXIMUM"]]
                maxima = {'departure':15,'enroute':20,'approach':25,'landing':25,'integrity':15}
                for key, maximum in maxima.items():
                    score_rows.append([key.upper(), str(breakdown.get(key, 0)), str(maximum)])
                score_rows.append(["OVERALL", str(score_data.get('overall', '-')), str(score_data.get('grade', '-'))])
                score_table = Table(score_rows, colWidths=[70*mm,35*mm,45*mm], repeatRows=1)
                score_table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1c353b')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),.25,colors.grey),('FONTSIZE',(0,0),(-1,-1),8),('PADDING',(0,0),(-1,-1),5)]))
                story.append(Paragraph("OPS ROOM SCORE BREAKDOWN", styles['Heading2']))
                story.append(score_table)

                story.append(PageBreak())
                story.append(Paragraph("APPROACH ANALYSIS", styles['Heading1']))
                story.append(Paragraph(
                    f"Runway {approach_data.get('runway') or '-'} · heading {_fmt_metric(approach_data.get('heading_deg'), 'deg', 1)}",
                    styles['OpsSmall'],
                ))
                story.append(Spacer(1,5))
                approach_pair = Table([
                    [
                        _analysis_xy_drawing(approach_data.get('profile') or [], 'lateral_deviation_ft', [('nm_to_threshold','Aircraft path')], 'LATERAL PROFILE - CENTRELINE DEVIATION', 84*mm, 69*mm),
                        _analysis_xy_drawing(approach_data.get('profile') or [], 'nm_to_threshold', [('approach_agl_ft','Actual AGL'),('ideal_3deg_agl_ft','3-degree path')], 'VERTICAL PROFILE - NM TO THRESHOLD', 84*mm, 69*mm),
                    ]
                ], colWidths=[87*mm,87*mm])
                approach_pair.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))
                story.append(approach_pair)
                story.append(Spacer(1,5))
                story.append(_metric_table([
                    ('Max lateral deviation', _fmt_metric(approach_data.get('max_lateral_deviation_ft'), 'ft')),
                    ('Max glidepath deviation', _fmt_metric(approach_data.get('max_glidepath_deviation_ft'), 'ft')),
                    ('Gear down', _fmt_metric(approach_data.get('gear_down_distance_nm'), 'NM', 1)),
                    ('Landing flap', _fmt_metric(approach_data.get('landing_flap_distance_nm'), 'NM', 1)),
                ], columns=2))
                story.append(Spacer(1,7))
                gate_rows = [["GATE", "STATUS", "DISTANCE", "CHECKS"]]
                for gate_key in ('stability_1000','stability_500'):
                    gate = approach_data.get(gate_key) or {}
                    status_text = 'STABLE' if gate.get('stable') is True else 'UNSTABLE' if gate.get('stable') is False else 'NO DATA'
                    checks = ', '.join(f"{x.get('label')}: {x.get('value')}" for x in (gate.get('checks') or []))
                    gate_rows.append([f"{gate.get('target_agl_ft') or '-'} FT", status_text, _fmt_metric(gate.get('distance_nm'), 'NM', 1), checks])
                gate_table = Table(gate_rows, colWidths=[25*mm,28*mm,28*mm,94*mm], repeatRows=1)
                gate_table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1c353b')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),.25,colors.grey),('FONTSIZE',(0,0),(-1,-1),6.5),('VALIGN',(0,0),(-1,-1),'TOP'),('PADDING',(0,0),(-1,-1),4)]))
                story.append(Paragraph("STABILITY GATES", styles['Heading2']))
                story.append(gate_table)

                story.append(PageBreak())
                story.append(Paragraph("LANDING ANALYSIS", styles['Heading1']))
                story.append(Paragraph(
                    f"Runway {landing_data.get('runway') or '-'} · touchdown zone, centreline and rollout derived from recorded position samples",
                    styles['OpsSmall'],
                ))
                story.append(Spacer(1,5))
                story.append(_runway_analysis_drawing(landing_data, 'TOUCHDOWN AND ROLLOUT RUNWAY PROFILE', 175*mm, 86*mm, landing=True))
                story.append(Spacer(1,7))
                story.append(_metric_table([
                    ('Touchdown rate', _fmt_metric(landing_data.get('touchdown_rate_fpm'), 'fpm')),
                    ('Touchdown G', _fmt_metric(landing_data.get('touchdown_g'), 'G', 2)),
                    ('Touchdown point', _fmt_metric(landing_data.get('touchdown_distance_ft'), 'ft')),
                    ('Runway used', _fmt_metric(landing_data.get('touchdown_percent'), '%', 1)),
                    ('Centreline deviation', _fmt_metric(landing_data.get('touchdown_centerline_deviation_ft'), 'ft')),
                    ('Touchdown speed', _fmt_metric(landing_data.get('touchdown_speed_kts'), 'kt')),
                    ('Touchdown pitch', _fmt_metric(landing_data.get('touchdown_pitch_deg'), 'deg', 1)),
                    ('Touchdown bank', _fmt_metric(landing_data.get('touchdown_bank_deg'), 'deg', 1)),
                    ('Touchdowns', str(landing_data.get('touchdowns') or '-')),
                    ('Rollout', _fmt_metric(landing_data.get('rollout_distance_ft'), 'ft')),
                    ('Distance remaining', _fmt_metric(landing_data.get('distance_remaining_at_touchdown_ft'), 'ft')),
                    ('Max rollout deviation', _fmt_metric(landing_data.get('max_rollout_deviation_ft'), 'ft')),
                ], columns=3))
            events=e.get('events') or []
            story.append(CondPageBreak(45*mm))
            story.append(Paragraph("EVENTS AND DEVIATIONS",styles['Heading2']))
            # Deviation detection already emits a DEVIATION event, so use the unified
            # event timeline here instead of duplicating every violation row.
            rows=[["UTC","TYPE","DETAIL"]]+[[str(x.get('time') or '')[11:19],x.get('title') or x.get('kind'),x.get('detail')] for x in events[-80:]]
            tab=Table(rows,colWidths=[24*mm,40*mm,115*mm],repeatRows=1); tab.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1c353b')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),.2,colors.grey),('FONTSIZE',(0,0),(-1,-1),7),('VALIGN',(0,0),(-1,-1),'TOP')])) ; story.append(tab)
            if e.get('notes'): story += [Spacer(1,6),Paragraph("PILOT NOTES",styles['Heading2']),Paragraph(str(e['notes']).replace('\n','<br/>'),styles['OpsSmall'])]
        else:
            if index==0:
                story.append(Paragraph(f"{len(entries)} completed records · {_fmt_duration(sum(int((x.get('durations') or {}).get('block_seconds') or 0) for x in entries))} total block time",styles['Heading2']))
                rows=[["DATE","CALLSIGN","ROUTE","AIRCRAFT","BLOCK","AIR","DIST NM",f"FUEL {_unit_pref('weight')}","LAND FPM","SCORE","DEV"]]
            rows.append([(e.get('started_utc') or '')[:10],f.get('callsign') or '-',f"{f.get('origin') or '----'}-{f.get('destination') or '----'}",f.get('aircraft_icao') or a.get('model') or '-',_fmt_duration(d.get('block_seconds')),_fmt_duration(d.get('airborne_seconds')),round(m.get('distance_nm') or 0),round(fuel.get('used_lb') or 0),round(m.get('landing_rate_fpm') or 0) if m.get('landing_rate_fpm') is not None else '-',de.get('score','-'),len(e.get('violations') or [])])
    if not detailed and entries:
        widths=[22*mm,24*mm,25*mm,26*mm,20*mm,20*mm,18*mm,20*mm,20*mm,15*mm,12*mm]; table=Table(rows,colWidths=widths,repeatRows=1); table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1c353b')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),.2,colors.grey),('FONTSIZE',(0,0),(-1,-1),6.5),('VALIGN',(0,0),(-1,-1),'TOP'),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f2f5f5')])])) ; story.append(table)
    doc.build(story); return buffer.getvalue()


def _fmt_duration(seconds: Any) -> str:
    try: total=max(0,int(seconds or 0))
    except: total=0
    return f"{total//3600:02d}:{(total%3600)//60:02d}"


_init_db_safe()
