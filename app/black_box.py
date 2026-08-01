from __future__ import annotations

"""OPS ROOM Black Box flight-data recorder.

The recorder is deliberately isolated from the existing logbook and automation
loops. The logbook only publishes validated phase transitions; a dedicated
adaptive telemetry worker records fresh snapshots from TAXI OUT through TAXI IN.
Recordings are stored as independently recoverable .opsbb SQLite files with
compressed chunks and are linked by the existing OPS ROOM flight id.
"""

from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
import csv
import io
import json
import math
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Iterable
import uuid
import zlib

from .settings_store import app_data_dir, load_settings
from .telemetry_provider import read_telemetry
from .simconnect_position import read_position
from .replay_guard import activate as replay_guard_activate, release as replay_guard_release, is_active as replay_guard_active, status as replay_guard_status

_SCHEMA_VERSION = 2
_LOCK = threading.RLock()
_STOP = threading.Event()
_THREAD: threading.Thread | None = None
_ACTIVE: dict[str, Any] | None = None
_RING: deque[dict[str, Any]] = deque(maxlen=18000)
_PHASE_CONTEXT: dict[str, Any] = {"flight_id": None, "phase": "", "meta": {}}

FIELDS = [
    "lat", "lon", "altitude_ft", "agl_ft", "radio_altitude_ft",
    "indicated_speed_kts", "true_speed_kts", "ground_speed_kts", "mach",
    "vertical_speed_fpm", "heading_deg", "track_deg", "pitch_deg", "bank_deg", "g_force",
    "flap_index", "flap_percent", "flap_handle_percent", "gear_percent", "spoiler_percent", "spoiler_actual_percent",
    "reverser_percent", "brake_percent", "brake_left_percent", "brake_right_percent",
    "aileron_position", "elevator_position", "rudder_position",
    "pilot_aileron_input", "pilot_elevator_input", "pilot_rudder_input",
    "actual_aileron_percent", "actual_elevator_percent", "actual_rudder_percent",
    "throttle_1_percent", "throttle_2_percent", "throttle_3_percent", "throttle_4_percent",
    "pilot_throttle_1_percent", "pilot_throttle_2_percent", "pilot_throttle_3_percent", "pilot_throttle_4_percent",
    "body_velocity_x_fps", "body_velocity_y_fps", "body_velocity_z_fps",
    "fuel_total_lb", "fuel_flow_pph", "engine_count", "engine_n1_percent", "engine_n2_percent", "engine_egt_c",
    "engine_1_n1_percent", "engine_2_n1_percent", "engine_3_n1_percent", "engine_4_n1_percent",
    "engine_1_n2_percent", "engine_2_n2_percent", "engine_3_n2_percent", "engine_4_n2_percent",
    "engine_1_egt_c", "engine_2_egt_c", "engine_3_egt_c", "engine_4_egt_c",
    "engine_1_fuel_flow_pph", "engine_2_fuel_flow_pph", "engine_3_fuel_flow_pph", "engine_4_fuel_flow_pph",
    "wind_speed_kts", "wind_direction_deg",
    "on_ground", "parking_brake", "engines_running",
    "engine_1_running", "engine_2_running", "engine_3_running", "engine_4_running",
    "autopilot", "autothrottle", "flight_director", "ap_selected_altitude_ft",
    "ap_selected_heading_deg", "ap_selected_speed_kts", "ap_selected_mach",
    "ap_selected_vertical_speed_fpm", "ap_modes",
    "sim_rate", "paused", "slew_active", "stall_warning", "overspeed_warning",
    "source", "extended_source", "provider_categories", "aircraft_adapter", "addon_state", "phase",
    # Schema v2 (append-only): independent first-officer sidestick axes and additive
    # per-sample control provenance. Appended at the tail so v1 recordings - which persist
    # their own shorter `fields` list - decode row-for-row unchanged and read these as null.
    # `control_provenance` is a dict field: `_normalize` passes dicts through untouched
    # (never coerced/rounded) and `_pack_rows`/`_unpack_rows` round-trip it as JSON.
    "pilot_aileron_input_fo", "pilot_elevator_input_fo", "control_provenance",
]


_CAPABILITY_GROUPS = {
    "core": {"lat", "lon", "altitude_ft", "agl_ft", "radio_altitude_ft", "indicated_speed_kts", "true_speed_kts", "ground_speed_kts", "mach", "vertical_speed_fpm", "heading_deg", "track_deg", "pitch_deg", "bank_deg", "g_force", "on_ground", "phase"},
    "controls": {"pilot_aileron_input", "pilot_elevator_input", "pilot_rudder_input", "pilot_aileron_input_fo", "pilot_elevator_input_fo", "actual_aileron_percent", "actual_elevator_percent", "actual_rudder_percent", "throttle_1_percent", "throttle_2_percent", "throttle_3_percent", "throttle_4_percent", "pilot_throttle_1_percent", "pilot_throttle_2_percent", "pilot_throttle_3_percent", "pilot_throttle_4_percent", "brake_percent", "flap_percent", "flap_handle_percent", "spoiler_percent", "spoiler_actual_percent", "gear_percent"},
    "engines": {"engine_count", "engine_n1_percent", "engine_n2_percent", "engine_egt_c", "fuel_flow_pph", "engine_1_n1_percent", "engine_2_n1_percent", "engine_3_n1_percent", "engine_4_n1_percent", "engine_1_n2_percent", "engine_2_n2_percent", "engine_3_n2_percent", "engine_4_n2_percent", "engine_1_egt_c", "engine_2_egt_c", "engine_3_egt_c", "engine_4_egt_c", "engine_1_fuel_flow_pph", "engine_2_fuel_flow_pph", "engine_3_fuel_flow_pph", "engine_4_fuel_flow_pph"},
    "systems": {"parking_brake", "engines_running", "autopilot", "autothrottle", "flight_director", "ap_selected_altitude_ft", "ap_selected_heading_deg", "ap_selected_speed_kts", "ap_selected_mach", "ap_selected_vertical_speed_fpm", "ap_modes", "stall_warning", "overspeed_warning", "addon_state"},
}

def _capability_manifest(active: dict[str, Any]) -> dict[str, Any]:
    available = set(active.get("capabilities") or set())
    groups = {name: sorted(fields & available) for name, fields in _CAPABILITY_GROUPS.items()}
    return {
        "available_fields": sorted(available),
        "groups": groups,
        "counts": {name: len(fields) for name, fields in groups.items()},
        "providers": dict(active.get("provider_categories") or {}),
        "aircraft_adapter": active.get("aircraft_adapter"),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _root() -> Path:
    path = app_data_dir() / "BlackBox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_id(value: Any) -> str:
    clean = "".join(ch for ch in str(value or "") if ch.isalnum() or ch in "-_")
    return clean[:80] or uuid.uuid4().hex


def _filename_part(value: Any, fallback: str = "") -> str:
    text = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(value or "").strip().upper())
    while "--" in text:
        text = text.replace("--", "-")
    return text.strip("-_")[:32] or fallback


def _new_path(recording_id: str, flight: dict[str, Any], aircraft: dict[str, Any], started_utc: str) -> Path:
    callsign = _filename_part(flight.get("callsign"), "FLIGHT")
    registration = _filename_part(aircraft.get("registration") or flight.get("registration"), "NOREG")
    origin = _filename_part(flight.get("origin"), "----")
    destination = _filename_part(flight.get("destination"), "----")
    stamp = "".join(ch for ch in str(started_utc or "") if ch.isdigit())[:14] or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    base = f"{callsign}_{registration}_{origin}-{destination}_{stamp}Z"[:170]
    final_path = _root() / f"{base}.opsbb"
    path = Path(str(final_path) + ".part")
    if not final_path.exists() and not path.exists():
        return path
    return Path(str(_root() / f"{base}_{_safe_id(recording_id)[-8:]}.opsbb") + ".part")


def _recording_paths() -> list[Path]:
    paths = list(_root().glob("*.opsbb")) + list(_root().glob("*.opsbb.part"))
    return sorted({path.resolve(): path for path in paths}.values(), key=lambda item: item.name)


def _final_path(path: Path) -> Path:
    return Path(str(path)[:-5]) if str(path).lower().endswith(".part") else path


def _path_for(recording_id: str) -> Path:
    # Backward compatibility for Preview 1-3 UUID-named files. New human-readable
    # files are resolved by their internal recording_id metadata.
    legacy = _root() / f"{_safe_id(recording_id)}.opsbb"
    if legacy.is_file():
        return legacy
    legacy_part = Path(str(legacy) + ".part")
    if legacy_part.is_file():
        return legacy_part
    target = str(recording_id or "")
    for path in _recording_paths():
        try:
            if str(_metadata(path).get("recording_id") or "") == target:
                return path
        except Exception:
            continue
    return legacy


@contextmanager
def _connect(path: Path):
    """Open one bounded SQLite transaction and always release the file handle."""
    conn = sqlite3.connect(path, timeout=20, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _init_recording(path: Path, metadata: dict[str, Any]) -> None:
    with _connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS chunks(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_elapsed REAL NOT NULL,
                ended_elapsed REAL NOT NULL,
                sample_count INTEGER NOT NULL,
                payload BLOB NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_elapsed ON chunks(started_elapsed, ended_elapsed);
            CREATE TABLE IF NOT EXISTS events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                elapsed REAL NOT NULL,
                utc TEXT NOT NULL,
                kind TEXT NOT NULL,
                detail TEXT NOT NULL,
                data_json TEXT NOT NULL DEFAULT '{}'
            );
            """
        )
        merged = {"schema": _SCHEMA_VERSION, "fields": FIELDS, **metadata}
        for key, value in merged.items():
            conn.execute("INSERT OR REPLACE INTO metadata(key,value_json) VALUES(?,?)", (str(key), json.dumps(value, ensure_ascii=False, separators=(",", ":"))))


def _metadata(path: Path) -> dict[str, Any]:
    try:
        with _connect(path) as conn:
            rows = conn.execute("SELECT key,value_json FROM metadata").fetchall()
        return {row["key"]: json.loads(row["value_json"]) for row in rows}
    except Exception:
        return {}


def _set_metadata(path: Path, **values: Any) -> None:
    with _connect(path) as conn:
        for key, value in values.items():
            conn.execute("INSERT OR REPLACE INTO metadata(key,value_json) VALUES(?,?)", (key, json.dumps(value, ensure_ascii=False, separators=(",", ":"))))


def _checkpoint(path: Path) -> None:
    """Make a completed .opsbb file self-contained for copy/download.

    Recording uses WAL for low-latency chunk commits. A finished/downloaded file
    is switched back to DELETE journalling after checkpointing so the portable
    .opsbb never depends on sidecar files that a browser download cannot carry.
    """
    conn = sqlite3.connect(path, timeout=20, check_same_thread=False)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.commit()
    finally:
        conn.close()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        try:
            if sidecar.exists() and sidecar.stat().st_size == 0:
                sidecar.unlink()
        except OSError:
            pass


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _sample_value(snapshot: dict[str, Any], key: str) -> Any:
    systems = snapshot.get("systems") if isinstance(snapshot.get("systems"), dict) else {}
    autopilot = snapshot.get("autopilot") if isinstance(snapshot.get("autopilot"), dict) else {}
    aliases = {
        "parking_brake": systems.get("parking_brake"),
        "engines_running": systems.get("engines_running"),
        "engine_1_running": systems.get("engine1_running"),
        "engine_2_running": systems.get("engine2_running"),
        "engine_3_running": systems.get("engine3_running"),
        "engine_4_running": systems.get("engine4_running"),
        "autopilot": autopilot.get("engaged"),
        "autothrottle": autopilot.get("autothrottle"),
        "flight_director": autopilot.get("flight_director"),
        "ap_selected_altitude_ft": autopilot.get("selected_altitude_ft"),
        "ap_selected_heading_deg": autopilot.get("selected_heading_deg"),
        "ap_selected_speed_kts": autopilot.get("selected_speed_kts"),
        "ap_selected_mach": autopilot.get("selected_mach"),
        "ap_selected_vertical_speed_fpm": autopilot.get("selected_vertical_speed_fpm"),
        "ap_modes": autopilot.get("modes"),
    }
    if key in aliases:
        return aliases[key]
    return snapshot.get(key)


_EXTENDED_FIELDS = (
    "flap_percent", "flap_handle_percent", "spoiler_percent", "spoiler_actual_percent", "gear_percent", "reverser_percent",
    "engine_n1_percent", "engine_n2_percent", "fuel_flow_pph",
    "engine_1_n1_percent", "engine_2_n1_percent",
    "engine_1_n2_percent", "engine_2_n2_percent",
    "engine_1_fuel_flow_pph", "engine_2_fuel_flow_pph",
    "body_velocity_x_fps", "body_velocity_y_fps", "body_velocity_z_fps",
    "stall_warning", "overspeed_warning",
    # v0.25.9 (schema v2): independent first-officer sidestick axes appended at
    # the tail so v1 recordings decode unchanged. These keys only carry data when
    # the active aircraft adapter (Fenix, PMDG, iniBuilds, FlyByWire) publishes a
    # generic per-seat FO stick through SimConnect; standard reads leave them
    # null. Adding them here keeps `_EXTENDED_FIELDS` aligned with the FIELDS
    # tail so the recording schema documents the new keys once, in one place.
    "pilot_aileron_input_fo", "pilot_elevator_input_fo",
)




def _normalize(snapshot: dict[str, Any], elapsed: float, phase: str) -> dict[str, Any] | None:
    if not snapshot.get("ok") or snapshot.get("telemetry_complete") is False or snapshot.get("telemetry_fresh") is False or snapshot.get("stale"):
        return None
    lat, lon = _number(snapshot.get("lat")), _number(snapshot.get("lon"))
    if lat is None or lon is None:
        return None
    row: dict[str, Any] = {"elapsed": round(max(0.0, elapsed), 4), "utc": _utc_now()}
    for key in FIELDS:
        value = phase if key == "phase" else _sample_value(snapshot, key)
        if isinstance(value, (bool, list, tuple, dict)) or value is None or key in {"source", "phase"}:
            row[key] = value
        else:
            number = _number(value)
            row[key] = round(number, 6) if number is not None else value
    return row


def _pack_rows(rows: list[dict[str, Any]]) -> bytes:
    compact = [[row.get("elapsed"), row.get("utc"), *[row.get(key) for key in FIELDS]] for row in rows]
    return zlib.compress(json.dumps(compact, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), level=6)


def _unpack_rows(payload: bytes, fields: list[str] | None = None) -> list[dict[str, Any]]:
    keys = fields or FIELDS
    raw = json.loads(zlib.decompress(payload).decode("utf-8"))
    result = []
    for values in raw:
        row = {"elapsed": values[0], "utc": values[1]}
        row.update({key: values[index + 2] if index + 2 < len(values) else None for index, key in enumerate(keys)})
        result.append(row)
    return result


def _flush_locked(active: dict[str, Any]) -> None:
    rows = active.get("buffer") or []
    if not rows:
        return
    payload = _pack_rows(rows)
    with _connect(active["path"]) as conn:
        conn.execute(
            "INSERT INTO chunks(started_elapsed,ended_elapsed,sample_count,payload) VALUES(?,?,?,?)",
            (float(rows[0]["elapsed"]), float(rows[-1]["elapsed"]), len(rows), sqlite3.Binary(payload)),
        )
    active["sample_count"] = int(active.get("sample_count") or 0) + len(rows)
    active["buffer"] = []
    active["last_flush"] = time.monotonic()
    elapsed = max(0.0, time.monotonic() - float(active.get("started_mono") or time.monotonic()))
    capabilities = sorted(active.get("capabilities") or [])
    _set_metadata(
        active["path"], sample_count=int(active["sample_count"]), duration_seconds=round(elapsed, 3),
        capabilities=capabilities, capability_manifest=_capability_manifest(active),
        provider_categories=dict(active.get("provider_categories") or {}), aircraft_adapter=active.get("aircraft_adapter"),
        last_provider=active.get("last_source"), last_sample_utc=active.get("last_sample_utc"),
    )


def _event_locked(active: dict[str, Any], kind: str, detail: str, data: dict[str, Any] | None = None) -> None:
    elapsed = max(0.0, time.monotonic() - float(active["started_mono"]))
    utc = _utc_now()
    payload = dict(data or {})
    with _connect(active["path"]) as conn:
        conn.execute(
            "INSERT INTO events(elapsed,utc,kind,detail,data_json) VALUES(?,?,?,?,?)",
            (elapsed, utc, str(kind), str(detail), json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
        )
    live = active.setdefault("live_events", [])
    live.append({"elapsed": round(elapsed, 3), "utc": utc, "kind": str(kind), "detail": str(detail), "data": payload})
    if len(live) > 120:
        del live[:-120]


def start_recording(flight_id: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    global _ACTIVE, _THREAD
    with _LOCK:
        if _ACTIVE:
            return status()
        if replay_guard_active():
            return {"ok": False, "recording": False, "replay_suppressed": True, "reason": "In-simulator replay is active"}
        recording_id = f"{_safe_id(flight_id)}-{uuid.uuid4().hex[:12]}"
        flight = dict((meta or {}).get("flight") or {})
        aircraft = dict((meta or {}).get("aircraft") or {})
        started_utc = _utc_now()
        path = _new_path(recording_id, flight, aircraft, started_utc)
        metadata = {
            "recording_id": recording_id,
            "flight_id": str(flight_id),
            "started_utc": started_utc,
            "completed_utc": None,
            "state": "RECORDING",
            "start_phase": "TAXI OUT",
            "end_phase": "TAXI IN",
            "flight": flight,
            "aircraft": aircraft,
            "sample_count": 0,
            "data_quality": None,
            "format": "OPS ROOM BLACK BOX",
        }
        _init_recording(path, metadata)
        _ACTIVE = {
            "id": recording_id, "flight_id": str(flight_id), "path": path,
            "started_mono": time.monotonic(), "started_utc": metadata["started_utc"],
            "buffer": [], "sample_count": 0, "attempt_count": 0, "valid_count": 0,
            "last_flush": time.monotonic(), "last_fingerprint": None,
            "capabilities": set(), "last_source": None, "last_sample_utc": None, "provider_categories": {}, "aircraft_adapter": None,
            "last_event_row": None, "live_events": [],
        }
        _STOP.clear()
        _RING.clear()
        _event_locked(_ACTIVE, "RECORDING START", "Recording started at taxi-out")
        _THREAD = threading.Thread(target=_record_loop, name="OpsRoom-BlackBox", daemon=True)
        _THREAD.start()
        return status()


def stop_recording(reason: str = "TAXI IN") -> dict[str, Any]:
    global _ACTIVE, _THREAD
    with _LOCK:
        active = _ACTIVE
        if not active:
            return status()
        _STOP.set()
        thread = _THREAD
    if thread and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=3.0)
    with _LOCK:
        active = _ACTIVE
        if not active:
            return status()
        _flush_locked(active)
        _event_locked(active, "RECORDING STOP", f"Recording stopped at {reason}")
        attempts = max(1, int(active.get("attempt_count") or 0))
        quality = round(100.0 * int(active.get("valid_count") or 0) / attempts, 2)
        completed = _utc_now()
        duration = round(max(0.0, time.monotonic() - float(active["started_mono"])), 3)
        _set_metadata(
            active["path"], state="COMPLETE", completed_utc=completed, duration_seconds=duration,
            sample_count=int(active.get("sample_count") or 0), data_quality=quality, stop_reason=reason,
            capabilities=sorted(active.get("capabilities") or []), capability_manifest=_capability_manifest(active),
            provider_categories=dict(active.get("provider_categories") or {}), aircraft_adapter=active.get("aircraft_adapter"),
            last_provider=active.get("last_source"), last_sample_utc=active.get("last_sample_utc"),
        )
        _checkpoint(active["path"])
        final_path = _final_path(Path(active["path"]))
        if final_path != Path(active["path"]):
            Path(active["path"]).replace(final_path)
            active["path"] = final_path
        finished = {"ok": True, "recording_id": active["id"], "flight_id": active["flight_id"], "path": str(active["path"]), "sample_count": active.get("sample_count"), "duration_seconds": duration, "data_quality": quality}
        _ACTIVE = None
        _THREAD = None
        _STOP.clear()
        return finished


def diagnose() -> dict[str, Any]:
    """Operator-visible recorder status. Joined across settings, telemetry
    and internal state so the UI can answer "why is it not recording?"."""
    try:
        from .settings_store import load_settings
        integrations = load_settings().get("integrations", {})
    except Exception:
        integrations = {}
    enabled = bool(integrations.get("black_box_enabled", True))
    auto = bool(integrations.get("black_box_auto_record", True))
    try:
        from .telemetry_provider import read_telemetry
        tel = read_telemetry(force=False) or {}
    except Exception as exc:
        tel = {"err": f"{type(exc).__name__}: {exc}"}
    try:
        from .aircraft_adapter_installer import adapter_status
        adapter = adapter_status().get("active_profile") if hasattr(adapter_status, "__call__") else None
    except Exception:
        adapter = None
    try:
        from .aircraft_adapter_catalog import detect_aircraft_family
        family = detect_aircraft_family(tel) if isinstance(tel, dict) else None
    except Exception:
        family = None
    aircraft = {
        "source": tel.get("source"),
        "icao": tel.get("aircraft_icao") or tel.get("title"),
        "title": tel.get("aircraft_title"),
        "family_hint": family,
        "on_ground": tel.get("on_ground"),
        "ground_speed_kts": tel.get("ground_speed_kts"),
        "engines_running": tel.get("engines_running"),
        "lat": tel.get("lat"), "lon": tel.get("lon"),
        "altitude_ft": tel.get("altitude_ft"),
    }
    with _LOCK:
        active = _ACTIVE is not None
    if not enabled:
        recorder_state = "DISABLED"
    elif replay_active():
        recorder_state = "SUPPRESSED-REPLAY"
    elif not auto:
        recorder_state = "AUTO-DISABLED"
    elif active:
        recorder_state = "RECORDING"
    elif aircraft.get("engines_running"):
        recorder_state = "PENDING-ENGINE-START"
    else:
        recorder_state = "STANDBY-NO-ENGINE"
    reason_not_recording = None
    if not enabled:
        reason_not_recording = "Black Box integration disabled in settings"
    elif not auto:
        reason_not_recording = "Auto-record disabled in settings"
    elif replay_active():
        reason_not_recording = "Simulator replay is active"
    elif not active and not aircraft.get("engines_running"):
        reason_not_recording = "Awaiting engine start or pushback"
    return {
        "aircraft_detected": aircraft.get("title") or aircraft.get("icao") or
                            family or "UNKNOWN",
        "telemetry": aircraft,
        "profile": adapter or family or "default",
        "recorder_state": recorder_state,
        "reason_not_recording": reason_not_recording,
    }


def reset_event_states() -> dict[str, Any]:
    """Drop recorder detector state so spurious events don't fire during replay.

    SkyDolly parity: MSFSSimConnectPlugin::resetEventStates({StartReplay|Seek}).
    Called by the in-sim replay controller when a freeze pose is applied
    (Start) or when the user seeks across a sample boundary (Seek). Without
    this, the very first freeze pose would be mis-classified as a touchdown
    (because altitude drops from cruise to zero), the autopilot would appear
    to engage en-route, and other detectors would fire from stale state.

    The reset is intentionally narrow: it does NOT cancel the recording
    itself.  If a recording is in progress, only the detector's
    ``last_event_row`` is cleared so the next sample is treated as the
    starting observation rather than a deltas-only follow-up.
    """
    global _PHASE_CONTEXT
    with _LOCK:
        _PHASE_CONTEXT = {"flight_id": None, "phase": "", "meta": {}}
        if _ACTIVE is not None:
            _ACTIVE["last_event_row"] = None
            _ACTIVE["addon_event_meta"] = {}
    return {"ok": True, "reset_at": _utc_now()}


def observe_phase(flight_id: str, phase: str, meta: dict[str, Any] | None = None, telemetry_hint: dict[str, Any] | None = None) -> None:
    """Receive the logbook's already-validated phase without changing it.

    Recording starts when any engine is running on the ground, regardless of
    phase (taxi-out, pushback, parked, etc.). Recording stops at TAXI IN phase,
    or 120 seconds after the last engine shuts down via ``_maybe_autostop_black_box``
    in the logbook engine loop.

    ``telemetry_hint`` is the logbook's already-read snapshot, avoiding a
    second ``read_telemetry`` call whose cache may hold stale pre-engine-start data.
    """
    phase_up = str(phase or "").upper()
    with _LOCK:
        _PHASE_CONTEXT.update({"flight_id": str(flight_id), "phase": phase_up, "meta": meta or {}})
        active = _ACTIVE
    integrations = load_settings().get("integrations", {})
    if replay_active() or not bool(integrations.get("black_box_enabled", True)) or not bool(integrations.get("black_box_auto_record", True)):
        return
    # v0.25.7: Recording start policy changed.
    #   - PUSHBACK (regardless of engine state): pilots get a recording when
    #     GSX/autosave tug starts moving them. Pre-flight coverage preserved.
    #   - ENGINE ON: detected in _record_loop via stream-minimal telemetry so
    #     a hot-start before any logbook phase change is also captured.
    #   - TAXI OUT / PARKED: previously triggered recording here; both routes
    #     are now subsumed by the two paths above (engine-on starts taxi-out
    #     so waiting for the phase transition adds nothing).
    if not active and phase_up == "PUSHBACK":
        try:
            start_recording(str(flight_id), meta)
            return
        except Exception:
            pass
    # Explicit TAXI IN stop is retained as a fast-path for operators who do
    # not rely on the logbook's autostop watcher.
    if phase_up == "TAXI IN" and active and str(active.get("flight_id")) == str(flight_id):
        stop_recording("TAXI IN")


def _target_interval(snapshot: dict[str, Any] | None, phase: str) -> float:
    settings = load_settings().get("integrations", {})
    provider = str((snapshot or {}).get("source") or "").lower()
    agl = _number((snapshot or {}).get("radio_altitude_ft"))
    if agl is None:
        agl = _number((snapshot or {}).get("agl_ft"))
    phase_up = phase.upper()
    # FSUIPC batch reads can sustain the high-rate runway stream. The current
    # Python SimConnect request surface is capped at 10 Hz to avoid queue noise.
    simconnect_max = _number(settings.get("black_box_simconnect_max_hz")) or 10.0
    max_hz = 30.0 if "fsuipc" in provider else max(2.0, min(simconnect_max, 20.0))
    requested = 30.0 if phase_up in {"TAKEOFF ROLL", "INITIAL CLIMB", "APPROACH", "FLARE", "LANDING ROLL"} or (agl is not None and agl <= 1000) else (20.0 if phase_up in {"TAXI OUT", "TAXI IN", "CLIMB", "DESCENT"} else 10.0)
    configured = _number(settings.get("black_box_max_hz")) or 30.0
    hz = max(2.0, min(requested, max_hz, configured))
    return 1.0 / hz


def _fingerprint(row: dict[str, Any]) -> tuple[Any, ...]:
    # Include the fast dynamics, controls and curated add-on state so short
    # aircraft-specific pulses are not discarded as duplicate position frames.
    addon_state = row.get("addon_state") if isinstance(row.get("addon_state"), dict) else {}
    addon_signature = json.dumps(addon_state, sort_keys=True, separators=(",", ":"), default=str) if addon_state else ""
    return tuple(row.get(key) for key in (
        "lat", "lon", "altitude_ft", "ground_speed_kts", "vertical_speed_fpm",
        "pitch_deg", "bank_deg", "heading_deg", "g_force",
        "aileron_position", "elevator_position", "rudder_position",
        "pilot_aileron_input", "pilot_elevator_input", "pilot_rudder_input",
        "pilot_aileron_input_fo", "pilot_elevator_input_fo",
        "throttle_1_percent", "throttle_2_percent", "throttle_3_percent", "throttle_4_percent",
        "pilot_throttle_1_percent", "pilot_throttle_2_percent", "flap_index",
        "gear_percent", "spoiler_percent", "brake_percent",
    )) + (addon_signature,)


def _detect_events_locked(active: dict[str, Any], row: dict[str, Any]) -> None:
    previous = active.get("last_event_row") if isinstance(active.get("last_event_row"), dict) else None
    if previous is None:
        active["last_event_row"] = dict(row)
        return
    def changed_bool(key: str) -> tuple[bool, bool] | None:
        old, new = previous.get(key), row.get(key)
        if old is None or new is None or bool(old) == bool(new):
            return None
        return bool(old), bool(new)
    old_phase, new_phase = str(previous.get("phase") or ""), str(row.get("phase") or "")
    if new_phase and new_phase != old_phase:
        _event_locked(active, "PHASE", new_phase, {"from": old_phase, "to": new_phase})
    ground = changed_bool("on_ground")
    if ground:
        _event_locked(active, "TOUCHDOWN" if ground[1] else "LIFTOFF", "Aircraft touched down" if ground[1] else "Aircraft became airborne")
    for key, label in (("autopilot", "AUTOPILOT"), ("autothrottle", "AUTOTHROTTLE")):
        state = changed_bool(key)
        if state:
            _event_locked(active, label, "engaged" if state[1] else "disengaged")
    for key, label in (("flap_index", "FLAPS"), ("gear_percent", "GEAR"), ("spoiler_percent", "SPOILERS")):
        old, new = _number(previous.get(key)), _number(row.get(key))
        if old is not None and new is not None and abs(new-old) >= (.5 if key == "flap_index" else 10.0):
            _event_locked(active, label, f"{new:.0f}" if key != "flap_index" else f"POSITION {new:.0f}", {"from": old, "to": new})
    for key, label in (("stall_warning", "STALL WARNING"), ("overspeed_warning", "OVERSPEED WARNING")):
        state = changed_bool(key)
        if state and state[1]:
            _event_locked(active, label, "active")
    old_addon = previous.get("addon_state") if isinstance(previous.get("addon_state"), dict) else {}
    new_addon = row.get("addon_state") if isinstance(row.get("addon_state"), dict) else {}
    meta = active.get("addon_event_meta") if isinstance(active.get("addon_event_meta"), dict) else {}
    for key, info in meta.items():
        if key not in new_addon or key not in old_addon:
            continue
        old, new = old_addon.get(key), new_addon.get(key)
        if old == new:
            continue
        label = str((info or {}).get("label") or key).upper()
        kind = str((info or {}).get("kind") or "number").lower()
        values = (info or {}).get("values") if isinstance((info or {}).get("values"), dict) else {}
        if kind == "pulse":
            try:
                active_pulse = bool(new is True or int(round(float(new))) == 1)
            except Exception:
                active_pulse = bool(new)
            if active_pulse:
                _event_locked(active, label, "pressed", {"field": key, "from": old, "to": new})
            continue
        if kind == "bool":
            detail = "ON" if bool(new) else "OFF"
        elif kind == "enum":
            try:
                detail = values.get(str(int(round(float(new))))) or str(int(round(float(new))))
            except Exception:
                detail = str(new)
        else:
            old_n, new_n = _number(old), _number(new)
            if old_n is not None and new_n is not None:
                threshold = 0.5
                if "ALTITUDE" in label: threshold = 50.0
                elif "V/S" in label or "VERTICAL" in label: threshold = 50.0
                if abs(new_n - old_n) < threshold:
                    continue
                detail = f"{new_n:.0f}" if abs(new_n) >= 10 else f"{new_n:.1f}"
            else:
                detail = str(new)
        _event_locked(active, label, detail, {"field": key, "from": old, "to": new})
    old_source, new_source = str(previous.get("source") or ""), str(row.get("source") or "")
    if old_source and new_source and old_source != new_source:
        _event_locked(active, "DATA SOURCE", f"Switched from {old_source} to {new_source}")
    # DATA GAP events were removed at user request: telemetry gaps are an
    # inherent property of a busy simulator (frame drops, scene reloads,
    # add-on stalls) and produced too-frequent noise in the events list.
    # The original "3.0s gap → event, 2.0s gap → close" debouncer limited
    # flooding to one event per idle window, but on a stuttering sim that
    # still produced dozens of repeated "DATA GAP" entries across one flight.
    # The Black Box sample stream remains continuous; only the noisy event
    # entries have been suppressed.
    active["last_event_row"] = dict(row)


def _record_loop() -> None:
    next_run = time.monotonic()
    last_snapshot: dict[str, Any] | None = None
    last_engines_running = False
    while not _STOP.is_set():
        with _LOCK:
            active = _ACTIVE
            phase = str(_PHASE_CONTEXT.get("phase") or "")
        now = time.monotonic()
        # When no recording is active we keep the same daemon thread alive as
        # a low-overhead watchdog: pulls the SlimSet once a second via the
        # ``stream="minimal"`` telemetry route and starts a recording as soon
        # as any engine transitions off -> on, regardless of which phase the
        # logbook is in.  This is the v0.25.7 "engine-on starts recording"
        # behaviour documented on ``observe_phase``.
        if not active:
            if now < next_run:
                _STOP.wait(min(0.5, next_run - now))
                continue
            snapshot: dict[str, Any] | None = None
            try:
                snapshot = read_telemetry(force=True, stream="minimal")
            except Exception:
                snapshot = None
            engines_now = bool(isinstance(snapshot, dict) and snapshot.get("engines_running"))
            if engines_now and not last_engines_running:
                with _LOCK:
                    flight_id = str(_PHASE_CONTEXT.get("flight_id") or "")
                    flight_meta = dict(_PHASE_CONTEXT.get("meta") or {})
                if flight_id:
                    try:
                        start_recording(flight_id, flight_meta)
                    except Exception:
                        pass
            last_engines_running = engines_now
            next_run = now + 1.0
            continue
        if now < next_run:
            _STOP.wait(min(0.05, next_run - now))
            continue
        snapshot: dict[str, Any] | None = None
        try:
            snapshot = read_telemetry(force=True, stream="minimal")
        except Exception:
            snapshot = None
        with _LOCK:
            active = _ACTIVE
            if not active:
                return
            active["attempt_count"] = int(active.get("attempt_count") or 0) + 1
            if isinstance((snapshot or {}).get("addon_event_meta"), dict):
                active["addon_event_meta"] = dict(snapshot["addon_event_meta"])
            elapsed = time.monotonic() - float(active["started_mono"])
            row = _normalize(snapshot or {}, elapsed, phase)
            if row is not None:
                fp = _fingerprint(row)
                # Preserve time-based control/systems changes but skip exact
                # duplicate provider snapshots caused by a slower simulator frame.
                if fp != active.get("last_fingerprint") or elapsed - float(active.get("last_written_elapsed") or -99) >= 0.25:
                    _detect_events_locked(active, row)
                    active["buffer"].append(row)
                    active["last_fingerprint"] = fp
                    active["last_written_elapsed"] = elapsed
                    active["valid_count"] = int(active.get("valid_count") or 0) + 1
                    active["last_source"] = row.get("source")
                    active["last_sample_utc"] = row.get("utc")
                    if isinstance(row.get("provider_categories"), dict): active["provider_categories"] = dict(row["provider_categories"])
                    if row.get("aircraft_adapter") is not None: active["aircraft_adapter"] = row.get("aircraft_adapter")
                    caps = active.setdefault("capabilities", set())
                    caps.update(key for key, value in row.items() if key not in {"elapsed", "utc"} and value is not None)
                    _RING.append(dict(row))
                last_snapshot = snapshot
            if len(active.get("buffer") or []) >= 60 or time.monotonic() - float(active.get("last_flush") or 0) >= 2.0:
                _flush_locked(active)
        interval = _target_interval(snapshot or last_snapshot, phase)
        next_run = max(next_run + interval, time.monotonic())
    with _LOCK:
        if _ACTIVE:
            _flush_locked(_ACTIVE)


def set_replay_active(value: bool) -> None:
    # Compatibility shim for older callers; the central guard also blocks the
    # logbook and every other flight-session entry point.
    if value:
        replay_guard_activate("BLACK BOX IN-SIM REPLAY")
    else:
        replay_guard_release(4.0)


def replay_active() -> bool:
    return replay_guard_active()


def status() -> dict[str, Any]:
    with _LOCK:
        active = dict(_ACTIVE) if _ACTIVE else None
        phase = str(_PHASE_CONTEXT.get("phase") or "")
    live = None
    if active:
        elapsed = max(0.0, time.monotonic() - float(active.get("started_mono") or time.monotonic()))
        samples_now = int(active.get("sample_count") or 0) + len(active.get("buffer") or [])
        attempts = max(1, int(active.get("attempt_count") or 0))
        valid = int(active.get("valid_count") or 0)
        actual_hz = valid / elapsed if elapsed > 0.5 else 0.0
        live = {
            "recording_id": active.get("id"), "flight_id": active.get("flight_id"),
            "started_utc": active.get("started_utc"), "sample_count": samples_now,
            "elapsed_seconds": round(elapsed, 2), "actual_hz": round(actual_hz, 1),
            "phase": phase, "provider": active.get("last_source") or "WAITING",
            "data_quality": round(100.0 * valid / attempts, 1),
            "data_health": "GOOD" if valid / attempts >= .95 else ("DEGRADED" if valid / attempts >= .75 else "CHECK DATA"),
            "buffer_samples": len(active.get("buffer") or []), "ring_samples": len(_RING),
            "capabilities": sorted(active.get("capabilities") or []),
            "provider_categories": dict(active.get("provider_categories") or {}), "aircraft_adapter": active.get("aircraft_adapter"),
            "file": Path(active.get("path")).name if active.get("path") else None,
        }
    return {
        "ok": True, "recording": bool(active), "active": live,
        "replay_active": replay_active(), "replay_guard": replay_guard_status(),
        "ring_samples": len(_RING),        "start_phase": "ENGINE ON / PUSHBACK", "stop_phase": "ON BLOCKS + 2 MIN",
        "auto_stop_window_seconds": 120,
    }


def _recording_summary(path: Path) -> dict[str, Any]:
    meta = _metadata(path)
    if not meta:
        return {"ok": False, "recording_id": path.stem, "state": "CORRUPT", "file": path.name}
    row = {"ok": True, **meta, "recording_id": meta.get("recording_id") or path.stem, "file": _final_path(path).name, "size_bytes": path.stat().st_size}
    with _LOCK:
        active = _ACTIVE if _ACTIVE and Path(_ACTIVE.get("path")) == path else None
        if active:
            elapsed = max(0.0, time.monotonic() - float(active.get("started_mono") or time.monotonic()))
            row.update({"state": "RECORDING", "sample_count": int(active.get("sample_count") or 0)+len(active.get("buffer") or []), "duration_seconds": round(elapsed,2), "data_quality": round(100.0*int(active.get("valid_count") or 0)/max(1,int(active.get("attempt_count") or 0)),1)})
    return row


def list_recordings(limit: int = 200) -> list[dict[str, Any]]:
    rows = [_recording_summary(path) for path in _recording_paths()]
    rows.sort(key=lambda row: str(row.get("started_utc") or ""), reverse=True)
    return rows[:max(1, min(int(limit), 1000))]


def recording_for_flight(flight_id: str) -> dict[str, Any] | None:
    target = str(flight_id or "")
    matches = [row for row in list_recordings(1000) if str(row.get("flight_id") or "") == target]
    return matches[0] if matches else None


def recording(recording_id: str) -> dict[str, Any]:
    path = _path_for(recording_id)
    if not path.is_file():
        raise FileNotFoundError(recording_id)
    summary = _recording_summary(path)
    with _connect(path) as conn:
        events = [dict(row) for row in conn.execute("SELECT elapsed,utc,kind,detail,data_json FROM events ORDER BY elapsed").fetchall()]
        chunks = conn.execute("SELECT COUNT(*) count,COALESCE(SUM(sample_count),0) samples,COALESCE(MAX(ended_elapsed),0) duration FROM chunks").fetchone()
    for row in events:
        try: row["data"] = json.loads(row.pop("data_json"))
        except Exception: row["data"] = {}
    disk_samples = int(chunks["samples"]); disk_duration = float(chunks["duration"] or 0)
    if str(summary.get("state") or "") == "RECORDING":
        summary.update({"events": events, "chunk_count": int(chunks["count"]), "disk_sample_count": disk_samples, "disk_duration_seconds": disk_duration})
    else:
        summary.update({"events": events, "chunk_count": int(chunks["count"]), "sample_count": disk_samples, "duration_seconds": disk_duration})
    return summary


def iter_samples(recording_id: str) -> Iterable[dict[str, Any]]:
    path = _path_for(recording_id)
    if not path.is_file():
        raise FileNotFoundError(recording_id)
    fields = _metadata(path).get("fields") or FIELDS
    with _connect(path) as conn:
        rows = conn.execute("SELECT payload FROM chunks ORDER BY started_elapsed").fetchall()
    for item in rows:
        yield from _unpack_rows(bytes(item["payload"]), list(fields))


def samples(recording_id: str, max_points: int = 5000) -> list[dict[str, Any]]:
    rows = list(iter_samples(recording_id))
    with _LOCK:
        if _ACTIVE and str(_ACTIVE.get("id")) == str(recording_id):
            last_elapsed = float(rows[-1].get("elapsed") or -1.0) if rows else -1.0
            live_rows = [dict(row) for row in _RING if float(row.get("elapsed") or 0.0) > last_elapsed + 1e-6]
            rows.extend(live_rows)
    limit = max(100, min(int(max_points), 50000))
    if len(rows) <= limit:
        return rows
    step = len(rows) / limit
    selected = [rows[min(len(rows) - 1, int(index * step))] for index in range(limit)]
    if selected[-1] is not rows[-1]:
        selected[-1] = rows[-1]
    return selected


def file_path(recording_id: str) -> Path:
    path = _path_for(recording_id)
    if not path.is_file():
        raise FileNotFoundError(recording_id)
    _checkpoint(path)
    return path


def export_csv(recording_id: str) -> bytes:
    out = io.StringIO(newline="")
    columns = ["elapsed", "utc", *FIELDS]
    writer = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(iter_samples(recording_id))
    return out.getvalue().encode("utf-8-sig")


def export_gpx(recording_id: str) -> bytes:
    rows = [row for row in iter_samples(recording_id) if _number(row.get("lat")) is not None and _number(row.get("lon")) is not None]
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<gpx version="1.1" creator="OPS ROOM" xmlns="http://www.topografix.com/GPX/1/1"><trk>', f'<name>{recording_id}</name><trkseg>']
    for row in rows:
        ele_m = (_number(row.get("altitude_ft")) or 0.0) * 0.3048
        parts.append(f'<trkpt lat="{float(row["lat"]):.8f}" lon="{float(row["lon"]):.8f}"><ele>{ele_m:.2f}</ele><time>{row.get("utc")}</time></trkpt>')
    parts.append('</trkseg></trk></gpx>')
    return "".join(parts).encode("utf-8")


def export_kml(recording_id: str) -> bytes:
    coords = []
    for row in iter_samples(recording_id):
        lat, lon = _number(row.get("lat")), _number(row.get("lon"))
        if lat is None or lon is None: continue
        alt_m = (_number(row.get("altitude_ft")) or 0.0) * 0.3048
        coords.append(f"{lon:.8f},{lat:.8f},{alt_m:.2f}")
    text = f'''<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>{recording_id}</name><Placemark><LineString><altitudeMode>absolute</altitudeMode><coordinates>{' '.join(coords)}</coordinates></LineString></Placemark></Document></kml>'''
    return text.encode("utf-8")


def live_snapshot(recording_id: str = "", after_elapsed: float = -1.0, max_points: int = 3000) -> dict[str, Any]:
    """Return incremental live FDR rows without rereading the entire SQLite file."""
    current_status = status()
    active = current_status.get("active") or {}
    active_id = str(active.get("recording_id") or "")
    if not current_status.get("recording") or (recording_id and str(recording_id) != active_id):
        return {"ok": True, "active": False, "status": current_status, "recording_id": active_id, "samples": [], "events": []}
    cutoff = float(after_elapsed or -1.0)
    with _LOCK:
        rows = [dict(row) for row in _RING if float(row.get("elapsed") or 0.0) > cutoff + 1e-6]
        events = [dict(item) for item in ((_ACTIVE or {}).get("live_events") or []) if float(item.get("elapsed") or 0.0) > cutoff + 1e-6]
    limit = max(100, min(int(max_points), 12000))
    if len(rows) > limit:
        rows = rows[-limit:]
    return {"ok": True, "active": True, "status": current_status, "recording_id": active_id, "samples": rows, "events": events}


def recent_ring(max_points: int = 1000) -> list[dict[str, Any]]:
    with _LOCK:
        rows = list(_RING)
    return rows[-max(1, min(int(max_points), 5000)):]


def recover_interrupted() -> None:
    """Close files left in RECORDING state after an application/simulator crash."""
    for path in _recording_paths():
        meta = _metadata(path)
        if meta.get("state") == "RECORDING":
            try:
                with _connect(path) as conn:
                    row = conn.execute("SELECT COALESCE(MAX(ended_elapsed),0) duration,COALESCE(SUM(sample_count),0) samples FROM chunks").fetchone()
                _set_metadata(path, state="INTERRUPTED", completed_utc=_utc_now(), stop_reason="OPS ROOM stopped before TAXI IN", duration_seconds=float(row["duration"] or 0), sample_count=int(row["samples"] or 0))
                _checkpoint(path)
                final_path = _final_path(path)
                if final_path != path and not final_path.exists():
                    path.replace(final_path)
            except Exception:
                pass


def shutdown() -> None:
    if status().get("recording"):
        stop_recording("OPS ROOM SHUTDOWN")
