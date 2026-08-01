from __future__ import annotations

"""Camera-safe, simulator-frame-synchronised Black Box replay controller."""

import logging
from bisect import bisect_right
import math
import threading
import time
from typing import Any

_LOG = logging.getLogger(__name__)

from . import black_box, logbook
from .replay_guard import activate as replay_guard_activate, release as replay_guard_release
from .simconnect_position import (
    replay_apply_state, replay_subscribe_frame, replay_unsubscribe_frame,
    replay_wait_frame, replay_is_frame_subscribed, replay_set_freeze,
    get_sim_rate, set_sim_rate, replay_read_sensor, replay_set_zulu,
)

# v0.25.9: SkyDolly parity enums (mirror SkyDolly/src/Kernel/include/Kernel/Replay.h).
# Default to OFF/None so existing callers' behaviour is unchanged.
_TIME_MODE_NONE = "None"
_TIME_MODE_SIMULATION_TIME = "SimulationTime"
_TIME_MODE_CREATION_REAL_WORLD_TIME = "CreationRealWorldTime"
_TIME_MODES = (_TIME_MODE_NONE, _TIME_MODE_SIMULATION_TIME, _TIME_MODE_CREATION_REAL_WORLD_TIME)

_SPEED_UNIT_ABSOLUTE = "Absolute"
_SPEED_UNIT_PERCENT = "Percent"
_SPEED_UNITS = (_SPEED_UNIT_ABSOLUTE, _SPEED_UNIT_PERCENT)

_SEEK_MODE_BEGIN = "Begin"
_SEEK_MODE_END = "End"
_SEEK_MODE_CURRENT = "Current"
_SEEK_MODE_BACKWARD = "Backward"
_SEEK_MODE_FORWARD = "Forward"
_SEEK_MODES = (_SEEK_MODE_BEGIN, _SEEK_MODE_END, _SEEK_MODE_CURRENT, _SEEK_MODE_BACKWARD, _SEEK_MODE_FORWARD)
# Seek modes that warrant a recorder event-state reset (SkyDolly's resetEventStates
# is called from onSeek and onStartReplay; "Current" means "stay on this timestamp"
# without crossing sample boundaries, so it does NOT require a reset).
_SEEK_MODE_RESET = {_SEEK_MODE_BEGIN, _SEEK_MODE_END, _SEEK_MODE_BACKWARD, _SEEK_MODE_FORWARD}


def _coerce_unit(unit: Any) -> str:
    text = str(unit or _SPEED_UNIT_ABSOLUTE).strip()
    return text if text in _SPEED_UNITS else _SPEED_UNIT_ABSOLUTE


def _to_speed_multiplier(value: Any, unit: Any, default: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number) or number <= 0.0:
        return default
    unit_norm = _coerce_unit(unit)
    multiplier = number / 100.0 if unit_norm == _SPEED_UNIT_PERCENT else number
    return max(.1, min(16.0, multiplier))


def _coerce_time_mode(mode: Any) -> str:
    text = str(mode or _TIME_MODE_NONE).strip()
    return text if text in _TIME_MODES else _TIME_MODE_NONE


def _coerce_seek_mode(mode: Any, default: str = _SEEK_MODE_CURRENT) -> str:
    text = str(mode or default).strip()
    return text if text in _SEEK_MODES else default


def _to_speed_percent(speed_multiplier: Any) -> float:
    try:
        n = float(speed_multiplier)
    except (TypeError, ValueError):
        return 100.0
    if not math.isfinite(n) or n <= 0.0:
        return 100.0
    return round(max(1.0, min(1600.0, n * 100.0)), 2)


def _reset_event_states() -> None:
    """SkyDolly parity: drop recorder detector state so spurious events don't fire during replay.

    Equivalent to SkyDolly MSFSSimConnectPlugin::resetEventStates({StartReplay|Seek}).
    Best-effort: if the recorder module isn't loaded we still mark the timestamp so callers
    can tell we attempted the reset.
    """
    try:
        from . import black_box as _bb
        _bb.reset_event_states()
    except Exception:
        pass
    with _LOCK:
        _STATE["last_event_reset_mono"] = time.monotonic()
    try:
        with _LOCK:
            active_id = _STATE.get("recording_id")
        _LOG.info("black_box_replay reset_event_states active_recording=%s", active_id)
    except Exception:
        pass


def _apply_time_sync_locked(rows: list[dict[str, Any]], time_mode: str) -> dict[str, Any]:
    """SkyDolly parity: synchronise simulator Zulu date/time to the recording's first frame.

    Mirrors SkyDolly SkyConnect::onSendZuluDateTime. ``time_mode`` is one of
    _TIME_MODES. ``None`` short-circuits to a no-op so start() never blocks the
    replay path on a missing or offline SimConnect session.

    OPS ROOM Black Box frames carry the recording-time ISO-8601 UTC string
    in ``row["utc"]`` (see app.black_box._normalize -> row = {"elapsed": ...,
    "utc": _utc_now()}), so we parse that into year / day-of-year / hour /
    minute, matching the SkyConnect field set the SimConnect API expects
    (ZULU_YEAR / ZULU_DAY_OF_YEAR / ZULU_HOURS / ZULU_MINUTES).
    """
    if not rows:
        return {"ok": True, "skipped": True, "fields_set": 0, "reason": "no_rows"}
    if time_mode == _TIME_MODE_NONE:
        return {"ok": True, "skipped": True, "fields_set": 0, "reason": "time_mode_off"}
    first = rows[0] or {}
    iso_utc = first.get("utc")
    if not isinstance(iso_utc, str) or not iso_utc:
        return {"ok": False, "reason": "first-frame utc is missing"}
    try:
        from datetime import datetime
        cleaned = iso_utc.replace("Z", "+00:00") if iso_utc.endswith("Z") else iso_utc
        dt = datetime.fromisoformat(cleaned)
        year = int(dt.year)
        day_of_year = int(dt.timetuple().tm_yday)
        hour = int(dt.hour)
        minute = int(dt.minute)
    except Exception as exc:
        return {"ok": False, "reason": f"first-frame utc parse failed: {type(exc).__name__}: {exc}"}
    try:
        result = replay_set_zulu(year, day_of_year, hour, minute)
    except Exception as exc:
        return {"ok": False, "reason": f"replay_set_zulu raised: {type(exc).__name__}: {exc}"}
    if not isinstance(result, dict) or not result.get("ok"):
        return result if isinstance(result, dict) else {"ok": False, "reason": "no_result"}
    with _LOCK:
        _STATE["time_sync_writes"] = int(_STATE.get("time_sync_writes") or 0) + 1
        _STATE["time_sync_last_mono"] = time.monotonic()
    try:
        _LOG.info("black_box_replay time_sync time_mode=%s fields_set=%s utc=%s",
                  time_mode, result.get("fields_set"), iso_utc)
    except Exception:
        pass
    return {"ok": True, "fields_set": result.get("fields_set"), "utc": iso_utc,
            "year": year, "day_of_year": day_of_year, "hour": hour, "minute": minute,
            "time_mode": time_mode}


def _sample_replay_sensor_locked() -> None:
    """SkyDolly parity ReplaySensor: refresh the lightweight altitude sample.

    Writes into ``_STATE["replay_sensor"]``. Caller MUST hold ``_LOCK`` so the
    dict swap is atomic with the rest of the per-frame state updates. Never
    raises; offline/no-session returns are kept as ``synchronized_with_sim=False``.

    ``synchronized_with_sim`` is True iff the live SimConnect read succeeded
    (``sensor.ok``); it does NOT imply the user aircraft position matches the
    replayed pose. Downstream consumers should compare
    ``sensor.altitude_ft`` against the current ``_STATE[\"last_frame\"][\"altitude_ft\"]``
    (with an AGL/altitude confidence tolerance) before raising a divergence alert.
    """
    try:
        sensor = replay_read_sensor()
        if isinstance(sensor, dict):
            _STATE["replay_sensor"] = {
                "altitude_ft": sensor.get("altitude_ft"),
                "altitude_agl_ft": sensor.get("altitude_agl_ft"),
                "synchronized_with_sim": bool(sensor.get("ok")),
                "sampled_monotonic": sensor.get("sampled_monotonic"),
                "source": sensor.get("source"),
            }
    except Exception:
        pass


_LOCK = threading.RLock()
_STOP = threading.Event()
_THREAD: threading.Thread | None = None
_FRAME_SUBSCRIBED = False
_ROWS: list[dict[str, Any]] = []
_TIMES: list[float] = []

_STATE: dict[str, Any] = {
    "active": False, "recording_id": None, "playing": False, "cursor": 0.0,
    "duration": 0.0, "speed": 1.0, "speed_percent": 100.0, "speed_unit": _SPEED_UNIT_ABSOLUTE,
    "loop": False, "last_error": None,
    "last_frame": None, "camera_safe": True, "interpolation": "HERMITE + QUATERNION SLERP",
    "clock_source": "STANDBY", "frame_callbacks_per_second": 0.0,
    "writes_per_second": 0.0, "dropped_updates": 0, "write_latency_ms": 0.0,
    "write_latency_max_ms": 0.0, "event_rejections": [], "aq_rejections": [], "seeking": False,
    # SkyDolly parity: TimeMode (None/SimulationTime/CreationRealWorldTime), SeekMode,
    # and the active ReplaySensor reading.
    "time_mode": _TIME_MODE_NONE, "last_seek_mode": None, "last_event_reset_mono": 0.0,
    "replay_sensor": {"altitude_ft": None, "altitude_agl_ft": None, "synchronized_with_sim": False, "sampled_monotonic": None},
    "time_sync_writes": 0, "time_sync_last_mono": 0.0,
}

_LINEAR_FIELDS = {
    "agl_ft", "radio_altitude_ft", "indicated_speed_kts", "true_speed_kts",
    "ground_speed_kts", "mach", "vertical_speed_fpm", "g_force", "flap_percent",
    "gear_percent", "spoiler_percent", "reverser_percent", "brake_percent",
    "aileron_position", "elevator_position", "rudder_position", "throttle_1_percent",
    "throttle_2_percent", "fuel_total_lb", "fuel_flow_pph", "engine_n1_percent",
    "engine_n2_percent", "engine_egt_c", "engine_1_n1_percent", "engine_2_n1_percent",
    "engine_1_n2_percent", "engine_2_n2_percent", "engine_1_egt_c", "engine_2_egt_c",
    "engine_1_fuel_flow_pph", "engine_2_fuel_flow_pph", "wind_speed_kts", "sim_rate",
    "body_velocity_x_fps", "body_velocity_y_fps", "body_velocity_z_fps",
}
_ANGLE_FIELDS = {"track_deg", "wind_direction_deg"}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _lerp(a: Any, b: Any, t: float) -> Any:
    av, bv = _number(a), _number(b)
    if av is None:
        return b
    if bv is None:
        return a
    return av + (bv - av) * t


def _angle(a: Any, b: Any, t: float) -> Any:
    av, bv = _number(a), _number(b)
    if av is None:
        return b
    if bv is None:
        return a
    delta = (bv - av + 180.0) % 360.0 - 180.0
    return (av + delta * t) % 360.0


def _unwrap(reference: float, value: float) -> float:
    return reference + ((value - reference + 180.0) % 360.0 - 180.0)


def _hermite_value(rows: list[dict[str, Any]], times: list[float], index: int, cursor: float, key: str, *, angle: bool = False) -> Any:
    """Time-aware cubic Hermite interpolation with bounded endpoint tangents.

    Values are read directly from the four neighbouring rows.  This keeps the
    visual-frame replay path O(1); the previous implementation rebuilt a full
    20k+ sample value array for every coordinate on every simulator frame.
    """
    p0 = _number(rows[index].get(key)); p1 = _number(rows[index + 1].get(key))
    if p0 is None or p1 is None:
        return p1 if p0 is None else p0
    t0, t1 = times[index], times[index + 1]
    span = max(0.0001, t1 - t0)
    u = max(0.0, min(1.0, (cursor - t0) / span))
    pm = _number(rows[index - 1].get(key)) if index > 0 else p0
    pp = _number(rows[index + 2].get(key)) if index + 2 < len(rows) else p1
    tm = times[index - 1] if index > 0 else t0 - span
    tp = times[index + 2] if index + 2 < len(times) else t1 + span
    if pm is None: pm = p0
    if pp is None: pp = p1
    if angle:
        p1 = _unwrap(p0, p1); pm = _unwrap(p0, pm); pp = _unwrap(p1, pp)
    m0 = (p1 - pm) / max(0.0001, t1 - tm) * span
    m1 = (pp - p0) / max(0.0001, tp - t0) * span
    h00 = 2*u*u*u - 3*u*u + 1
    h10 = u*u*u - 2*u*u + u
    h01 = -2*u*u*u + 3*u*u
    h11 = u*u*u - u*u
    result = h00*p0 + h10*m0 + h01*p1 + h11*m1
    # Prevent spline overshoot from creating airport-scale jumps between noisy points.
    margin = max(abs(p1 - p0) * .35, 1e-9)
    result = max(min(p0, p1) - margin, min(max(p0, p1) + margin, result))
    return result % 360.0 if angle else result


def _quat_from_euler(pitch: float, bank: float, heading: float) -> tuple[float, float, float, float]:
    # Aerospace ZYX: heading (yaw), pitch, then bank (roll).
    roll = math.radians(bank); pit = math.radians(pitch); yaw = math.radians(heading)
    cr, sr = math.cos(roll/2), math.sin(roll/2)
    cp, sp = math.cos(pit/2), math.sin(pit/2)
    cy, sy = math.cos(yaw/2), math.sin(yaw/2)
    return (
        cr*cp*cy + sr*sp*sy,
        sr*cp*cy - cr*sp*sy,
        cr*sp*cy + sr*cp*sy,
        cr*cp*sy - sr*sp*cy,
    )


def _quat_slerp(a: tuple[float, float, float, float], b: tuple[float, float, float, float], t: float) -> tuple[float, float, float, float]:
    dot = sum(x*y for x, y in zip(a, b))
    if dot < 0.0:
        b = tuple(-x for x in b); dot = -dot
    dot = max(-1.0, min(1.0, dot))
    if dot > .9995:
        q = tuple(x + (y-x)*t for x, y in zip(a, b))
        norm = math.sqrt(sum(x*x for x in q)) or 1.0
        return tuple(x/norm for x in q)
    theta = math.acos(dot); sin_theta = math.sin(theta)
    wa = math.sin((1-t)*theta)/sin_theta; wb = math.sin(t*theta)/sin_theta
    return tuple(wa*x + wb*y for x, y in zip(a, b))


def _euler_from_quat(q: tuple[float, float, float, float]) -> tuple[float, float, float]:
    w, x, y, z = q
    sinr = 2*(w*x + y*z); cosr = 1 - 2*(x*x + y*y)
    bank = math.degrees(math.atan2(sinr, cosr))
    sinp = max(-1.0, min(1.0, 2*(w*y - z*x)))
    pitch = math.degrees(math.asin(sinp))
    siny = 2*(w*z + x*y); cosy = 1 - 2*(y*y + z*z)
    heading = math.degrees(math.atan2(siny, cosy)) % 360.0
    return pitch, bank, heading


def _frame_at(cursor: float) -> dict[str, Any] | None:
    with _LOCK:
        rows, times = _ROWS, _TIMES
    if not rows:
        return None
    if cursor <= times[0]:
        return dict(rows[0])
    if cursor >= times[-1]:
        return dict(rows[-1])
    index = max(0, min(len(rows)-2, bisect_right(times, cursor)-1))
    a, b = rows[index], rows[index+1]
    span = max(0.0001, times[index+1]-times[index])
    t = max(0.0, min(1.0, (cursor-times[index])/span))
    frame = dict(a if t < .5 else b)
    # Smooth geographic trajectory/altitude from recorded control points.
    frame["lat"] = _hermite_value(rows, times, index, cursor, "lat")
    frame["lon"] = _hermite_value(rows, times, index, cursor, "lon", angle=True)
    # On the runway, cubic vertical tangents can magnify tiny recorder/scenery
    # altitude noise into visible hopping. Keep the lateral path smooth but use
    # a bounded linear altitude blend while both control points are on-ground.
    if bool(a.get("on_ground")) and bool(b.get("on_ground")):
        frame["altitude_ft"] = _lerp(a.get("altitude_ft"), b.get("altitude_ft"), t)
    else:
        frame["altitude_ft"] = _hermite_value(rows, times, index, cursor, "altitude_ft")
    for key in _LINEAR_FIELDS:
        frame[key] = _lerp(a.get(key), b.get(key), t)
    for key in _ANGLE_FIELDS:
        frame[key] = _angle(a.get(key), b.get(key), t)
    attitude_a = [_number(a.get(k)) for k in ("pitch_deg", "bank_deg", "heading_deg")]
    attitude_b = [_number(b.get(k)) for k in ("pitch_deg", "bank_deg", "heading_deg")]
    if all(value is not None for value in (*attitude_a, *attitude_b)):
        q = _quat_slerp(_quat_from_euler(*attitude_a), _quat_from_euler(*attitude_b), t)  # type: ignore[arg-type]
        frame["pitch_deg"], frame["bank_deg"], frame["heading_deg"] = _euler_from_quat(q)
    else:
        frame["pitch_deg"] = _lerp(a.get("pitch_deg"), b.get("pitch_deg"), t)
        frame["bank_deg"] = _lerp(a.get("bank_deg"), b.get("bank_deg"), t)
        frame["heading_deg"] = _angle(a.get("heading_deg"), b.get("heading_deg"), t)
    frame["elapsed"] = cursor
    return frame


def _normal_recording_active() -> bool:
    try:
        from .logbook import status as logbook_status
        return bool(logbook_status().get("recording"))
    except Exception:
        return False


def _reanchor_locked(cursor: float, now: float | None = None) -> None:
    _STATE["cursor"] = max(0.0, min(float(cursor), float(_STATE.get("duration") or 0.0)))
    _STATE["anchor_cursor"] = _STATE["cursor"]
    _STATE["started_mono"] = now if now is not None else time.monotonic()


def start(recording_id: str, *, speed: float = 1.0, loop: bool = False, start_elapsed: float = 0.0, force: bool = False,
          time_mode: str = _TIME_MODE_NONE, speed_unit: str = _SPEED_UNIT_ABSOLUTE,
          seek_mode: str = _SEEK_MODE_BEGIN) -> dict[str, Any]:
    """Start an in-simulator replay of a recorded Black Box flight.

    SkyDolly parity kwargs (all optional, all default to OFF/identity so existing
    callers keep their behaviour verbatim):
      - time_mode: "None" (default) / "SimulationTime" / "CreationRealWorldTime"
      - speed_unit: "Absolute" (default, treats ``speed`` as a 0.1x..16x multiplier)
                     / "Percent" (treats ``speed`` as 10..1600 percent)
      - seek_mode: applied to the initial cursor anchor; one of
                   "Begin" / "End" / "Current" (default) / "Backward" / "Forward"
    """
    global _THREAD, _ROWS, _TIMES, _FRAME_SUBSCRIBED
    # Complete any active flight first so the PIREP is finalised before replay
    try:
        logbook.finalize_active()
    except Exception:
        pass
    if status().get("active"):
        stop()
    if black_box.status().get("recording"):
        return {"ok": False, "detail": "Stop the active Black Box recording before replay."}
    if _normal_recording_active() and not force:
        return {"ok": False, "detail": "A live OPS ROOM flight recording is active. Complete it first before in-simulator replay."}
    rows = list(black_box.iter_samples(recording_id))
    if len(rows) < 2:
        return {"ok": False, "detail": "The selected Black Box recording has insufficient samples."}
    rows.sort(key=lambda row: float(row.get("elapsed") or 0.0))
    times = [float(row.get("elapsed") or 0.0) for row in rows]
    cursor = max(times[0], min(float(start_elapsed), times[-1]))
    # Capture the pilot's current SIMULATION_RATE so we can restore it on stop.
    # This matches SkyDolly's convention of leaving the simulator exactly as
    # the user had it (a 4x-time-acceleration flight returns to 4x after the
    # replay, not to 1x).
    saved_sim_rate = get_sim_rate()
    speed_unit_norm = _coerce_unit(speed_unit)
    speed_multiplier = _to_speed_multiplier(speed, speed_unit_norm)
    time_mode_norm = _coerce_time_mode(time_mode)
    initial_seek_mode = _coerce_seek_mode(seek_mode, default=_SEEK_MODE_BEGIN)
    # SkyDolly parity: reset recorder event state on StartReplay so spurious
    # TOUCHDOWN/LIFTOFF events do not fire from the very first freeze pose.
    _reset_event_states()
    with _LOCK:
        _STATE["saved_sim_rate"] = saved_sim_rate
        _STATE["speed_unit"] = speed_unit_norm
        _STATE["speed_percent"] = _to_speed_percent(speed_multiplier)
        _STATE["time_mode"] = time_mode_norm
        _STATE["last_seek_mode"] = initial_seek_mode
    replay_guard_activate("BLACK BOX IN-SIM REPLAY")
    # SkyDolly parity TimeMode: synchronise simulator Zulu date/time to the
    # recording's first frame. Best-effort; offline dev-mode still records
    # the attempt without raising. Never blocks start() - the function returns
    # {"ok": True, "skipped": True} when time_mode == "None" or rows is empty.
    _apply_time_sync_locked(rows, time_mode_norm)
    frozen = replay_set_freeze(True)
    if not frozen.get("ok"):
        replay_guard_release(4.0)
        return {"ok": False, "detail": f"Could not freeze the simulator aircraft: {frozen.get('reason')}"}
    with _LOCK:
        _ROWS = rows; _TIMES = times
    first = _frame_at(cursor)
    positioned = replay_apply_state(first or {}, initial=True)
    if not positioned.get("ok"):
        replay_set_freeze(False); replay_guard_release(4.0)
        with _LOCK:
            _ROWS = []; _TIMES = []
        return {"ok": False, "detail": f"Could not position the aircraft: {positioned.get('reason')}"}
    clock_result = replay_subscribe_frame()
    _FRAME_SUBSCRIBED = clock_result.get("ok", False)
    now = time.monotonic()
    with _LOCK:
        _STATE.update({
            "active": True, "recording_id": recording_id, "playing": True,
            "cursor": cursor, "duration": times[-1], "speed": speed_multiplier,
            "loop": bool(loop), "last_error": None, "last_frame": first,
            "clock_source": clock_result.get("source") or "MONOTONIC FALLBACK",
            "clock_detail": clock_result.get("reason"), "frame_callbacks_per_second": 0.0,
            "writes_per_second": 0.0, "dropped_updates": 0,
            "write_latency_ms": positioned.get("latency_ms") or 0.0,
            "write_latency_max_ms": positioned.get("latency_ms") or 0.0,
            "event_rejections": [], "aq_rejections": [],
            "started_mono": now, "anchor_cursor": cursor, "seeking": False,
            "metrics_started": now, "metrics_frames": 0, "metrics_writes": 1,
            "metrics_latency_total": float(positioned.get("latency_ms") or 0.0),
            "metrics_latency_count": 1,
        })
        _STOP.clear()
        _THREAD = threading.Thread(target=_loop, name="OpsRoom-BlackBox-Replay", daemon=True)
        _THREAD.start()
    return status()


def _loop() -> None:
    fallback_next = time.monotonic()
    last_frame_event = time.monotonic()
    while not _STOP.is_set():
        subscribed = _FRAME_SUBSCRIBED
        frame_event = False
        event_mono = time.monotonic()
        try:
            frame_event, event_mono = replay_wait_frame(.12)
        except Exception:
            frame_event = False
        if frame_event:
            last_frame_event = event_mono
        else:
            # The fallback is only used after the Frame event has actually gone
            # silent. It sends the current target pose only; it never bursts old
            # frames to catch up. Brief pauses remain still and do not create a
            # second unsynchronised writer.
            now = time.monotonic()
            if subscribed and now - last_frame_event < .35:
                continue
            wait = fallback_next - now
            if wait > 0 and _STOP.wait(min(wait, .05)):
                break
            fallback_next = max(fallback_next + 1/60.0, time.monotonic())
            event_mono = time.monotonic()
        with _LOCK:
            if not _STATE.get("active"):
                return
            if _STATE.get("seeking"):
                continue
            _STATE["metrics_frames"] = int(_STATE.get("metrics_frames") or 0) + (1 if frame_event else 0)
            playing = bool(_STATE.get("playing"))
            wrapped = False
            if playing:
                cursor = float(_STATE.get("anchor_cursor") or 0.0) + (event_mono - float(_STATE.get("started_mono") or event_mono)) * float(_STATE.get("speed") or 1.0)
                duration = float(_STATE.get("duration") or 0.0)
                if cursor >= duration:
                    if _STATE.get("loop") and duration > 0:
                        cursor %= duration; wrapped = True
                        _reanchor_locked(cursor, event_mono)
                    else:
                        cursor = duration; _STATE["playing"] = False
                _STATE["cursor"] = cursor
            cursor = float(_STATE.get("cursor") or 0.0)
        frame = _frame_at(cursor)
        if frame is None:
            continue
        started = time.perf_counter()
        result = replay_apply_state(frame, initial=wrapped, apply_controls=True)
        processing = time.perf_counter() - started
        with _LOCK:
            _STATE["last_frame"] = frame
            if not result.get("ok"):
                _STATE["last_error"] = result.get("reason"); _STATE["playing"] = False
            else:
                latency = float(result.get("latency_ms") or processing*1000.0)
                _STATE["metrics_writes"] = int(_STATE.get("metrics_writes") or 0) + 1
                _STATE["metrics_latency_total"] = float(_STATE.get("metrics_latency_total") or 0.0) + latency
                _STATE["metrics_latency_count"] = int(_STATE.get("metrics_latency_count") or 0) + 1
                _STATE["write_latency_max_ms"] = max(float(_STATE.get("write_latency_max_ms") or 0.0), latency)
                _STATE["event_rejections"] = result.get("event_rejections") or []
                _STATE["aq_rejections"] = result.get("aq_rejections") or []
                if processing > .05:
                    _STATE["dropped_updates"] = int(_STATE.get("dropped_updates") or 0) + max(0, int(processing/.0167)-1)
            now = time.monotonic(); window = now - float(_STATE.get("metrics_started") or now)
            if window >= 1.0:
                _STATE["frame_callbacks_per_second"] = round(int(_STATE.get("metrics_frames") or 0)/window, 1)
                _STATE["writes_per_second"] = round(int(_STATE.get("metrics_writes") or 0)/window, 1)
                count = max(1, int(_STATE.get("metrics_latency_count") or 0))
                _STATE["write_latency_ms"] = round(float(_STATE.get("metrics_latency_total") or 0.0)/count, 3)
                _STATE["metrics_started"] = now; _STATE["metrics_frames"] = 0; _STATE["metrics_writes"] = 0
                _STATE["metrics_latency_total"] = 0.0; _STATE["metrics_latency_count"] = 0
                _sample_replay_sensor_locked()


def control(*, playing: bool | None = None, cursor: float | None = None, speed: float | None = None, loop: bool | None = None,
          seek_mode: str | None = None, speed_unit: str | None = None) -> dict[str, Any]:
    """Pause/resume/seek/loop/speed control for an active in-simulator replay.

    SkyDolly parity kwargs (all optional):
      - seek_mode: "Begin" / "End" / "Current" (default) / "Backward" / "Forward".
        SkyDolly's onSeek(timestamp, SeekMode) signals whether the user is
        scrubbing back to start, jumping to end, holding current position, etc.
        Begin/End/Backward/Forward trigger a recorder event-state reset so
        events don't fire from stale state on the destination samples.
      - speed_unit: "Absolute" (default; ``speed`` is a multiplier) or "Percent"
        (treats ``speed`` as percent of real-time).
    """
    seek_frame = None; resume_after_seek = False; reset_on_seek = False
    coerced_seek = None
    with _LOCK:
        if not _STATE.get("active"):
            return {"ok": False, "detail": "No in-simulator replay is active."}
        now = time.monotonic()
        # SkyDolly parity: derive a cursor from seek_mode when the caller did
        # not supply one. "Begin" -> 0.0, "End" -> duration, "Backward" -> cursor-30s,
        # "Forward" -> cursor+30s. "Current" leaves the cursor untouched.
        if cursor is None and seek_mode is not None:
            coerced_seek = _coerce_seek_mode(seek_mode, default=_SEEK_MODE_CURRENT)
            if coerced_seek != _SEEK_MODE_CURRENT:
                current_cursor = float(_STATE.get("cursor") or 0.0)
                duration = float(_STATE.get("duration") or 0.0)
                step_seconds = 30.0  # SkyDolly default seek-step
                if coerced_seek == _SEEK_MODE_BEGIN:
                    cursor = 0.0
                elif coerced_seek == _SEEK_MODE_END:
                    cursor = duration
                elif coerced_seek == _SEEK_MODE_BACKWARD:
                    cursor = max(0.0, current_cursor - step_seconds)
                elif coerced_seek == _SEEK_MODE_FORWARD:
                    cursor = current_cursor + step_seconds
                    if duration > 0.0:
                        cursor = min(duration, cursor)
        if cursor is not None:
            resume_after_seek = bool(_STATE.get("playing")) if playing is None else bool(playing)
            _STATE["playing"] = False; _STATE["seeking"] = True
            _reanchor_locked(float(cursor), now)
            seek_frame = _frame_at(float(_STATE["cursor"]))
        if seek_mode is not None:
            coerced = coerced_seek or _coerce_seek_mode(seek_mode, default=_SEEK_MODE_CURRENT)
            _STATE["last_seek_mode"] = coerced
            if cursor is not None:
                reset_on_seek = coerced in _SEEK_MODE_RESET
        else:
            _STATE["last_seek_mode"] = _SEEK_MODE_CURRENT
        if speed_unit is not None:
            _STATE["speed_unit"] = _coerce_unit(speed_unit)
        if speed is not None:
            unit_norm = _STATE.get("speed_unit") or _SPEED_UNIT_ABSOLUTE
            multiplier = _to_speed_multiplier(speed, unit_norm)
            _STATE["speed"] = multiplier
            _STATE["speed_percent"] = _to_speed_percent(multiplier)
        if loop is not None:
            _STATE["loop"] = bool(loop)
        if playing is not None and cursor is None:
            _STATE["playing"] = bool(playing)
            _reanchor_locked(float(_STATE.get("cursor") or 0.0), now)
    if reset_on_seek:
        _reset_event_states()
    if seek_frame is not None:
        result = replay_apply_state(seek_frame, initial=True, apply_controls=True)
        # Allow attached/detached cameras and the scenery loader two visual frames
        # to settle before resuming the replay clock.
        subscribed = _FRAME_SUBSCRIBED
        if subscribed:
            for _ in range(2):
                try: replay_wait_frame(.08)
                except Exception: break
        else:
            time.sleep(.04)
        with _LOCK:
            _STATE["last_frame"] = seek_frame; _STATE["seeking"] = False
            if result.get("ok"):
                _STATE["playing"] = resume_after_seek
                _reanchor_locked(float(_STATE.get("cursor") or 0.0))
            else:
                _STATE["last_error"] = result.get("reason"); _STATE["playing"] = False
    return status()


def stop() -> dict[str, Any]:
    global _THREAD, _ROWS, _TIMES, _FRAME_SUBSCRIBED
    with _LOCK:
        was_active = bool(_STATE.get("active")); _STOP.set(); thread = _THREAD
    if was_active:
        replay_unsubscribe_frame()
    if thread and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=2.5)
    unfreeze = replay_set_freeze(False) if was_active else {"ok": True, "frozen": False}
    saved_rate = _STATE.get("saved_sim_rate") if was_active else None
    if was_active and saved_rate is not None:
        set_sim_rate(saved_rate)
    with _LOCK:
        _STATE.update({"active": False, "recording_id": None, "playing": False, "cursor": 0.0, "duration": 0.0, "last_frame": None, "seeking": False, "clock_source": "STANDBY"})
        _ROWS = []; _TIMES = []; _THREAD = None; _FRAME_SUBSCRIBED = False; _STOP.clear()
    replay_guard_release(4.0)
    return {"ok": bool(unfreeze.get("ok")), "stopped": True, "unfreeze": unfreeze, "recorder_guard_cooldown_seconds": 4.0}


def status() -> dict[str, Any]:
    with _LOCK:
        state = dict(_STATE); frame = dict(state.get("last_frame") or {})
    for key in ("started_mono", "anchor_cursor", "metrics_started", "metrics_frames", "metrics_writes", "metrics_latency_total", "metrics_latency_count"):
        state.pop(key, None)
    state["last_frame"] = frame
    return {"ok": True, **state}


def shutdown() -> None:
    stop()
