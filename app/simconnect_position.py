from __future__ import annotations

import importlib.util
import logging
import math
from ctypes import POINTER, Structure, byref, c_double, c_int32, c_uint32, cast, sizeof
import os
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any

from .aircraft_adapters import detect_adapter


def _clean_text(value: Any) -> str:
    """Decode SimConnect string SimVars that arrive as bytes (#92).

    The vendored SimConnect wrapper returns the TITLE / ATC_MODEL / ATC_TYPE
    string SimVars as ``bytes`` on some builds; ``str(b"FenixA320")`` produces
    the literal ``b"FenixA320"`` text that leaked into recorder metadata, the
    Procedures aircraft label and the Live OFP. Decode bytes first, then strip.
    """
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8", "replace").strip()
        except Exception:
            pass
    return str(value or "").strip()

class _SimConnectLogRateLimit(logging.Filter):
    """#83: rate-limit the upstream wrapper's per-exception warn lines.

    The vendored SimConnect package logs every dispatch exception (e.g.
    SIMCONNECT_EXCEPTION_UNRECOGNIZED_ID) through its own logger; on some
    aircraft/sessions a handful leak per tick. This keeps at most one line per
    exception text per interval so the operator log stays readable while the
    first occurrence is still visible.
    """

    def __init__(self, interval: float = 30.0) -> None:
        super().__init__()
        self._interval = interval
        self._last: dict[str, float] = {}

    def filter(self, record: logging.LogRecord) -> bool:
        msg = str(getattr(record, "msg", ""))
        if "EXCEPTION" not in msg.upper():
            return True
        now = time.monotonic()
        if now - self._last.get(msg, -1e9) >= self._interval:
            self._last[msg] = now
            return True
        return False


def _install_log_rate_limit() -> None:
    try:
        logger = logging.getLogger("SimConnect.SimConnect")
        if not any(isinstance(f, _SimConnectLogRateLimit) for f in logger.filters):
            logger.addFilter(_SimConnectLogRateLimit())
    except Exception:
        pass


# SimConnect is optional in source/development mode. The standalone Windows
# package includes it and its native DLL. Access is serialized because the
# upstream Python wrapper is not designed for concurrent connection attempts.
_LOCK = threading.Lock()
_CACHE: dict[str, Any] | None = None
_CACHE_TIME = 0.0
_CACHE_SECONDS = 0.18
_SESSION_SM: Any | None = None
_SESSION_AQ: Any | None = None
_SESSION_STARTED = 0.0
_REPLAY_POSE_DEFINITION: Any | None = None
_REPLAY_INITIAL_DEFINITION: Any | None = None
_REPLAY_POSE_SESSION_ID: int | None = None
_REPLAY_OPTIONAL_LAST: dict[str, float | int] = {}

# v0.25.60: session self-heal. The upstream SimConnect wrapper's dispatch
# thread can break mid-session (repeated ``OS error: WinError 0xc00000b0``
# floods with every read returning None). Consecutive failed reads tear the
# session down so the next ``_ensure_session`` builds a fresh connection
# instead of serving a dead one forever.
_SESSION_CONSECUTIVE_FAILURES = 0
_SESSION_MAX_CONSECUTIVE_FAILURES = 25

# v0.25.72 (#9): the upstream wrapper's dispatch loop prints ``OS error: ...``
# on every failed CallDispatch (its loop sleeps 2 ms, so a dying dispatch
# thread floods the log at ~500 lines/sec). We replace the loop with a guarded
# version that prints once, then tears the session down after a short run of
# consecutive errors so reads fail fast and the next ``_ensure_session``
# rebuilds. A rebuild backoff prevents thrashing when the wrapper keeps dying.
_SESSION_DISPATCH_DEAD = False
_LAST_REBUILD_AT = 0.0
_REBUILD_BACKOFF_SECONDS = 30.0
_DISPATCH_ERROR_LIMIT = 10

# v0.25.76 (#64): the native SimConnect wrapper's dispatch thread crashes with
# 0xc00000b0 and the native heap damage persists across session rebuilds — 45
# crashes on EWG5EZ finally tripped ntdll heap validation (0xc0000374) and
# killed the whole process. After a small ceiling of dispatch crashes within a
# short window we stop rebuilding entirely and permanently degrade to the
# FSUIPC/WASM path for the rest of the run, instead of retrying into a corrupt
# heap forever. Reset only by an app restart.
_SESSION_CRASH_COUNT = 0
_SESSION_CRASH_WINDOW_START = 0.0
_SESSION_CRASH_CEILING = 5
_SESSION_CRASH_WINDOW_SECONDS = 300.0
_SESSION_PERMANENTLY_DEGRADED = False

# #64 follow-up: auto-recover the degradation instead of staying off until an
# app restart. After the crash ceiling, SimConnect is parked for an escalating
# cooldown; when the cooldown expires, ONE fresh rebuild is attempted. If the
# sim-side connection has recovered (loading screen done / session reset), the
# session re-establishes and the epoch resets. If it crashes again, the next
# cooldown is longer. This keeps the heap-safety of #64 (no 2 ms dispatch-loop
# thrash) while restoring SimConnect automatically.
#
# #108 (2026-08-13): the cooldown auto-recovery is now scoped to the probe
# WORKER subprocess only (fresh native heap per process). The MAIN app process
# parks SimConnect permanently after the crash ceiling — every rebuild on the
# same damaged heap re-opens the session that trips ntdll 0xC0000374 (observed
# live: 4 session rebuilds in 10 min, crash 1 s after a cooldown-triggered
# SIM OPEN). Main-process reads now come from the worker pipe / FSUIPC / HTTP
# bridge paths; only an app restart resets the main-process park.
_SESSION_DEGRADED_UNTIL = 0.0
_SESSION_DEGRADATION_EPOCHS = 0
_SESSION_DEGRADE_COOLDOWNS = (120.0, 300.0, 600.0, 900.0)
# A rebuilt session must stay alive this long before the degradation epoch is
# reset (proves the recovery attempt actually stuck rather than a brief blip).
_SESSION_RECOVERY_HEALTHY_SECONDS = 120.0


def _note_dispatch_crash() -> bool:
    """Count a dispatch-thread death and decide whether to park SimConnect.

    Returns True once the crash ceiling is reached, so callers can stop
    retrying into a corrupt heap for the current cooldown.

    #108 (2026-08-13): in the MAIN app process the park is permanent — the
    first dispatch death parks SimConnect for the rest of the run (crash
    ceiling of 1). Every session rebuild on the same process heap re-opens
    the corrupt native session that trips ntdll 0xC0000374; the live crash
    happened on the 4th rebuild (SIM OPEN 21:50:21 -> crash 21:50:22), well
    before the old ceiling of 5 was ever reached. The probe WORKER subprocess
    keeps its own crash ceiling (5 / escalating cooldown) because it owns a
    fresh native heap per process and is respawned on death.
    """
    global _SESSION_CRASH_COUNT, _SESSION_CRASH_WINDOW_START, _SESSION_PERMANENTLY_DEGRADED
    global _SESSION_DEGRADED_UNTIL, _SESSION_DEGRADATION_EPOCHS
    now = time.monotonic()
    if now - _SESSION_CRASH_WINDOW_START > _SESSION_CRASH_WINDOW_SECONDS:
        _SESSION_CRASH_COUNT = 0
        _SESSION_CRASH_WINDOW_START = now
    _SESSION_CRASH_COUNT += 1
    ceiling = _SESSION_CRASH_CEILING if _is_probe_worker_process() else 1
    if _SESSION_CRASH_COUNT >= ceiling:
        if not _SESSION_PERMANENTLY_DEGRADED:
            cooldown = _SESSION_DEGRADE_COOLDOWNS[min(_SESSION_DEGRADATION_EPOCHS, len(_SESSION_DEGRADE_COOLDOWNS) - 1)]
            _SESSION_DEGRADED_UNTIL = now + cooldown
            _SESSION_DEGRADATION_EPOCHS += 1
            print(
                "SimConnect parked: "
                f"{_SESSION_CRASH_COUNT} dispatch crash(es) in "
                f"{int(now - _SESSION_CRASH_WINDOW_START)}s. "
                + (
                    f"Permanently parked for this run (heap safety); "
                    "FSUIPC + worker probe paths remain active."
                    if not _is_probe_worker_process()
                    else f"Degrading to the FSUIPC/WASM path for {int(cooldown)}s; "
                    "SimConnect will be retried automatically after the cooldown."
                )
            )
        _SESSION_PERMANENTLY_DEGRADED = True
        # Start a fresh crash window for the next recovery attempt.
        _SESSION_CRASH_COUNT = 0
        _SESSION_CRASH_WINDOW_START = now
        return True
    return False


def _guarded_dispatch_run(sm: Any) -> None:
    """Replacement for the upstream SimConnect wrapper's ``_run`` loop.

    Keeps the identical CallDispatch cadence while healthy, but suppresses the
    per-error print flood and marks the session dead after a short run of
    consecutive OSErrors so the health counters can rebuild it quickly. Each
    death is counted (#64); past the crash ceiling the session is never
    rebuilt again this run.
    """
    global _SESSION_DISPATCH_DEAD
    errors = 0
    while getattr(sm, "quit", 0) == 0:
        try:
            sm.dll.CallDispatch(sm.hSimConnect, sm.my_dispatch_proc_rd, None)
            time.sleep(0.002)
            errors = 0
        except OSError as err:
            errors += 1
            if errors == 1:
                print(f"SimConnect dispatch failure (rebuilding session): {err}")
            if errors >= _DISPATCH_ERROR_LIMIT:
                _SESSION_DISPATCH_DEAD = True
                _note_dispatch_crash()
                # #83: log the death with the session's age so the operator log
                # can correlate a dispatch death with writer/telemetry state.
                age = round(time.monotonic() - _SESSION_STARTED, 1) if _SESSION_STARTED else None
                print(
                    f"SimConnect session degraded: dispatch dead after {errors} consecutive errors "
                    f"(session age {age}s) — FSUIPC held until the session rebuilds"
                )
                sm.quit = 1
                try:
                    sm.dll.Close(sm.hSimConnect)
                except Exception:
                    pass
                return

# Single-session Frame event subscription (SkyDolly approach — one SimConnect session)
_REPLAY_FRAME_COND = threading.Condition()
_REPLAY_FRAME_SUBSCRIBED = False
_REPLAY_FRAME_EVENT_ID: Any | None = None
_REPLAY_FRAME_ORIG_HANDLER: Any | None = None
_REPLAY_FRAME_LAST_MONO = 0.0

# Cached sim terrain under the aircraft (GROUND_ALTITUDE, feet MSL). The
# recording's own MSL altitude can drift off true terrain near the arrival
# field (baro/QNH datum), so pose altitude is floored at terrain + recorded
# AGL to prevent the replay from being written below the ground.
_REPLAY_GROUND_FT: float | None = None
_REPLAY_GROUND_MONO = 0.0
_REPLAY_GROUND_INTERVAL = 1.0
_REPLAY_GROUND_LOCK = threading.Lock()
_REPLAY_GROUND_AGL_FLOOR = 300.0  # only probe terrain below this AGL (ft)

# v0.25.60 — Two-tier Black Box polling: low-rate SimVars (engine flags,
# parking brake, flaps, gear, spoilers, wind, sim rate, pause/slew, reverser,
# body velocity, stall/overspeed, aircraft info) are cached and refreshed at
# ~2 Hz independent of the high-rate (position/attitude/speed) loop.  This
# roughly halves the concurrent SimConnect subscription count during recording
# without losing any field written to the .opsbb file.
_LOW_RATE_CACHE: dict[str, Any] = {}
_LOW_RATE_CACHE_TIME: float = 0.0
_LOW_RATE_INTERVAL: float = 0.5  # refresh low-rate vars every 500 ms (2 Hz)

# ── Batched minimal reader (Stage 2 SimConnect fast path) ────────────────────
# The per-SimVar ``aq.get`` path costs one request/response round trip per
# SimVar (~1 sim frame each). A minimal sample reads ~45 numeric SimVars that
# way, and because the read takes longer than the wrapper's 125 ms per-var
# value cache, every read re-fetches everything (measured ~1 Hz fresh). The
# batched path defines every numeric minimal-path SimVar as one data
# definition and requests them in a single SimConnect call - one frame of
# latency per sample, which is what makes 30 Hz SimConnect reads possible
# without stutter. String SimVars (aircraft title/model/type) stay on a 2 Hz
# per-var refresh because they cannot share a FLOAT64 batch.
_BATCH_STATE: dict[str, Any] = {
    "sm_id": None,
    "def_id": None,
    "request_id": None,
    "names": [],
    "result": None,
    "done": None,
    "backoff_until": 0.0,
}
_BATCH_NAMES: list[str] = [
    # High-rate tier (position / attitude / speeds) - read every sample.
    "PLANE_LATITUDE", "PLANE_LONGITUDE", "PLANE_ALTITUDE",
    "INDICATED_ALTITUDE", "INDICATED_ALTITUDE_CALIBRATED", "PRESSURE_ALTITUDE",
    "AIRSPEED_INDICATED", "GROUND_VELOCITY", "AIRSPEED_TRUE", "AIRSPEED_MACH",
    "PLANE_HEADING_DEGREES_MAGNETIC", "PLANE_HEADING_DEGREES_GYRO",
    "GPS_GROUND_MAGNETIC_TRACK", "VERTICAL_SPEED",
    "PLANE_ALT_ABOVE_GROUND", "RADIO_HEIGHT", "PLANE_PITCH_DEGREES",
    "PLANE_BANK_DEGREES", "G_FORCE",
    # Low-rate tier (numeric) - engine flags, surfaces, wind, sim rate.
    "SIM_ON_GROUND", "FLAPS_HANDLE_INDEX", "GEAR_TOTAL_PCT_EXTENDED",
    "SPOILERS_HANDLE_POSITION", "FLAPS_HANDLE_PERCENT",
    "AMBIENT_WIND_VELOCITY", "AMBIENT_WIND_DIRECTION", "SIMULATION_RATE",
    "IS_LATITUDE_LONGITUDE_FREEZE_ON", "IS_SLEW_ACTIVE", "STALL_WARNING",
    "OVERSPEED_WARNING", "BRAKE_PARKING_POSITION",
    "VELOCITY_BODY_X", "VELOCITY_BODY_Y", "VELOCITY_BODY_Z",
    # Indexed engine / reverser SimVars.
    "GENERAL_ENG_COMBUSTION:1", "GENERAL_ENG_COMBUSTION:2",
    "GENERAL_ENG_COMBUSTION:3", "GENERAL_ENG_COMBUSTION:4",
    "TURB_ENG_REVERSE_NOZZLE_PERCENT:1", "TURB_ENG_REVERSE_NOZZLE_PERCENT:2",
    # Flight-model weights (slugs -> lb).
    "TOTAL_WEIGHT", "EMPTY_WEIGHT", "MAX_GROSS_WEIGHT",
    # Full-stream numeric SimVars (controls / autopilot / radios / engines /
    # systems / fuel) - one definition covers the whole stream so the full
    # read costs one frame instead of ~75 per-SimVar round trips.
    "AILERON_LEFT_DEFLECTION_PCT", "AILERON_RIGHT_DEFLECTION_PCT",
    "AILERON_POSITION", "ELEVATOR_DEFLECTION_PCT", "ELEVATOR_POSITION",
    "RUDDER_DEFLECTION_PCT", "RUDDER_PEDAL_POSITION", "RUDDER_POSITION",
    "YOKE_X_POSITION", "YOKE_Y_POSITION", "BRAKE_LEFT_POSITION",
    "BRAKE_RIGHT_POSITION", "SPOILERS_LEFT_POSITION", "SPOILERS_RIGHT_POSITION",
    "TRAILING_EDGE_FLAPS_LEFT_PERCENT",
    "AUTOPILOT_AIRSPEED_HOLD", "AUTOPILOT_AIRSPEED_HOLD_VAR",
    "AUTOPILOT_ALTITUDE_LOCK", "AUTOPILOT_ALTITUDE_LOCK_VAR",
    "AUTOPILOT_APPROACH_HOLD", "AUTOPILOT_DISENGAGED",
    "AUTOPILOT_FLIGHT_DIRECTOR_ACTIVE", "AUTOPILOT_FLIGHT_DIRECTOR_ACTIVE:1",
    "AUTOPILOT_FLIGHT_DIRECTOR_ACTIVE:2", "AUTOPILOT_FLIGHT_LEVEL_CHANGE",
    "AUTOPILOT_HEADING_LOCK", "AUTOPILOT_HEADING_LOCK_DIR",
    "AUTOPILOT_MACH_HOLD", "AUTOPILOT_MACH_HOLD_VAR",
    "AUTOPILOT_MANAGED_SPEED_IN_MACH", "AUTOPILOT_MANAGED_THROTTLE_ACTIVE",
    "AUTOPILOT_MASTER", "AUTOPILOT_NAV1_LOCK", "AUTOPILOT_THROTTLE_ARM",
    "AUTOPILOT_VERTICAL_HOLD", "AUTOPILOT_VERTICAL_HOLD_VAR",
    "COM_ACTIVE_FREQUENCY:1", "COM_ACTIVE_FREQUENCY:2",
    "COM_STANDBY_FREQUENCY:1", "COM_STANDBY_FREQUENCY:2",
    "COM_TRANSMIT:1", "COM_TRANSMIT:2", "NAV_CDI:1", "NAV_GSI:1",
    "ENG_FUEL_FLOW_PPH:1", "ENG_FUEL_FLOW_PPH:2", "ENG_FUEL_FLOW_PPH:3", "ENG_FUEL_FLOW_PPH:4",
    "GENERAL_ENG_EXHAUST_GAS_TEMPERATURE:1", "GENERAL_ENG_EXHAUST_GAS_TEMPERATURE:2",
    "GENERAL_ENG_EXHAUST_GAS_TEMPERATURE:3", "GENERAL_ENG_EXHAUST_GAS_TEMPERATURE:4",
    "GENERAL_ENG_THROTTLE_LEVER_POSITION:1", "GENERAL_ENG_THROTTLE_LEVER_POSITION:2",
    "GENERAL_ENG_THROTTLE_LEVER_POSITION:3", "GENERAL_ENG_THROTTLE_LEVER_POSITION:4",
    "TURB_ENG_FUEL_FLOW_PPH:1", "TURB_ENG_FUEL_FLOW_PPH:2",
    "TURB_ENG_FUEL_FLOW_PPH:3", "TURB_ENG_FUEL_FLOW_PPH:4",
    "TURB_ENG_N1:1", "TURB_ENG_N1:2", "TURB_ENG_N1:3", "TURB_ENG_N1:4",
    "TURB_ENG_N2:1", "TURB_ENG_N2:2", "TURB_ENG_N2:3", "TURB_ENG_N2:4",
    "NUMBER_OF_ENGINES", "APU_GENERATOR_SWITCH", "APU_PCT_RPM", "APU_SWITCH",
    "ELECTRICAL_AVIONICS_BUS_VOLTAGE", "ELECTRICAL_MASTER_BATTERY",
    "EXTERNAL_POWER_ON", "LIGHT_BEACON", "LIGHT_LOGO", "CABIN_SEATBELTS_ALERT_SWITCH",
    "FUEL_TOTAL_QUANTITY", "FUEL_TOTAL_QUANTITY_WEIGHT", "FUEL_WEIGHT_PER_GALLON",
]
_BATCH_STRING_CACHE: dict[str, Any] = {"t": 0.0, "title": "", "model": "", "type": ""}
_BATCH_STRING_INTERVAL: float = 0.5

# #80: dedicated single-SimVar CAMERA_STATE read. The FSUIPC 0x026D camera
# offset does not reliably track MSFS2024 external camera states, so the
# announcer camera-volume path falls back to the authoritative SimConnect
# CAMERA_STATE enum. This is one INT32 SimVar, one definition, one request at
# ~1 Hz — negligible traffic and fully independent of the numeric batch above
# (which is FLOAT64 and cannot carry the enum).
_CAMERA_STATE_STATE: dict[str, Any] = {
    "sm_id": None,
    "def_id": None,
    "request_id": None,
    "done": None,
    "result": None,
    "backoff_until": 0.0,
    "cache_until": 0.0,
    "cached_value": None,
}


def _camera_state_ensure(sm: Any) -> bool:
    """Define the CAMERA_STATE enum data definition on the current session."""
    if _CAMERA_STATE_STATE.get("sm_id") == id(sm) and _CAMERA_STATE_STATE.get("def_id") is not None:
        return True
    # #98 T1: a session that cannot define CAMERA_STATE (SIMCONNECT_EXCEPTION_
    # NAME_UNRECOGNIZED on some aircraft/sessions) must not be retried on every
    # announcer tick — that definition churn feeds the dispatch loop that ends
    # in native heap corruption. Park the attempt for 30 s.
    if time.monotonic() < float(_CAMERA_STATE_STATE.get("backoff_until") or 0.0):
        return False
    _CAMERA_STATE_STATE.update({"sm_id": None, "def_id": None, "request_id": None, "done": None, "result": None})
    try:
        from SimConnect.Constants import SIMCONNECT_UNUSED  # type: ignore
        from SimConnect.Enum import SIMCONNECT_DATATYPE  # type: ignore

        def_id = sm.new_def_id()
        request_id = sm.new_request_id()
        hr = sm.dll.AddToDataDefinition(
            sm.hSimConnect, def_id.value, b"CAMERA_STATE", b"Enum",
            SIMCONNECT_DATATYPE.SIMCONNECT_DATATYPE_INT32, 0, SIMCONNECT_UNUSED,
        )
        if not sm.IsHR(hr, 0):
            _CAMERA_STATE_STATE["backoff_until"] = time.monotonic() + 30.0
            return False
        _CAMERA_STATE_STATE.update({
            "sm_id": id(sm), "def_id": def_id, "request_id": request_id,
            "done": threading.Event(), "result": None, "backoff_until": 0.0,
        })
        # Ensure the shared SimObject dispatch hook is installed so the
        # camera-state response is parsed (the same handler also serves the
        # numeric batch).
        _install_batch_dispatch(sm)
        return True
    except Exception:
        _CAMERA_STATE_STATE.update({"sm_id": None, "def_id": None, "request_id": None, "done": None})
        return False


def _read_camera_state_raw(sm: Any) -> int | None:
    """One-request CAMERA_STATE read; None on failure (caller falls back)."""
    if _CAMERA_STATE_STATE.get("sm_id") != id(sm) or _CAMERA_STATE_STATE.get("def_id") is None:
        return None
    if time.monotonic() < float(_CAMERA_STATE_STATE.get("backoff_until") or 0.0):
        return None
    try:
        from SimConnect.Enum import SIMCONNECT_SIMOBJECT_TYPE  # type: ignore

        done = _CAMERA_STATE_STATE["done"]
        _CAMERA_STATE_STATE["result"] = None
        done.clear()
        hr = sm.dll.RequestDataOnSimObjectType(
            sm.hSimConnect,
            _CAMERA_STATE_STATE["request_id"].value,
            _CAMERA_STATE_STATE["def_id"].value,
            0,
            SIMCONNECT_SIMOBJECT_TYPE.SIMCONNECT_SIMOBJECT_TYPE_USER,
        )
        if not sm.IsHR(hr, 0):
            return None
        if not done.wait(timeout=0.2):
            _CAMERA_STATE_STATE["backoff_until"] = time.monotonic() + 5.0
            return None
        result = _CAMERA_STATE_STATE.get("result")
        _CAMERA_STATE_STATE["result"] = None
        return int(result) if result is not None else None
    except Exception:
        return None


def _camera_state_read_in_process() -> int | None:
    """Raw in-process CAMERA_STATE read, never routed through the worker.

    Used by the probe worker's ``camera`` handler and by
    ``camera_state_simconnect``'s non-worker fallback. The worker MUST NOT
    call the public function: in packaged builds it routes through the probe
    client, which spawns a NEW worker to answer the same request, which does
    the same -- an unbounded probe-worker fork bomb (observed live 2026-08-14:
    ~80 OPS ROOM.exe --probe-worker processes chained parent->child).
    """
    if _SESSION_PERMANENTLY_DEGRADED or _SESSION_DISPATCH_DEAD:
        return None
    value: int | None = None
    try:
        with _LOCK:
            diagnostics = simconnect_diagnostics()
            if not diagnostics.get("dll_path"):
                value = None
            else:
                sm, _aq = _ensure_session(diagnostics)
                if _camera_state_ensure(sm):
                    value = _read_camera_state_raw(sm)
    except Exception:
        value = None
    return value


def camera_state_simconnect() -> int | None:
    """Public, cached CAMERA_STATE read for the announcer volume path (#80).

    Returns the SimConnect camera-state enum (2 cockpit, 3/4/5/6 external,
    7 sixdof, 9 showcase/cabin, ...) or None when SimConnect is unavailable
    (degraded/parked/not loaded) so the caller falls back to FSUIPC 0x026D.
    Cached ~0.5 s so a 1 Hz poll never exceeds one cheap request per second.

    #108 next tier: in packaged builds the read goes through the probe worker
    (the main process never opens SimConnect for reads); source/dev runs keep
    the in-process path unless ``OPSROOM_PROBE_WORKER=1``.
    """
    global _CAMERA_STATE_STATE
    now = time.monotonic()
    if _CAMERA_STATE_STATE.get("cached_value") is not None and now < float(_CAMERA_STATE_STATE.get("cache_until") or 0.0):
        return int(_CAMERA_STATE_STATE["cached_value"])
    if _is_probe_worker_process():
        # Inside the probe worker itself: read in-process directly. Routing
        # through the probe client here would spawn a NEW worker to serve the
        # same request, and that worker would do the same -- fork bomb.
        value = _camera_state_read_in_process()
        _CAMERA_STATE_STATE["cached_value"] = value
        _CAMERA_STATE_STATE["cache_until"] = now + (0.5 if value is not None else 2.0)
        return value
    worker_value = _worker_camera_state()
    if worker_value is not None:
        _CAMERA_STATE_STATE["cached_value"] = worker_value
        _CAMERA_STATE_STATE["cache_until"] = now + 0.5
        return worker_value
    if _worker_reads_enabled():
        # Packaged build: the worker is the only SimConnect client for reads -
        # never fall back to opening a main-process session here.
        _CAMERA_STATE_STATE["cached_value"] = None
        _CAMERA_STATE_STATE["cache_until"] = now + 2.0
        return None
    value = _camera_state_read_in_process()
    _CAMERA_STATE_STATE["cached_value"] = value
    _CAMERA_STATE_STATE["cache_until"] = now + (0.5 if value is not None else 2.0)
    return value


class _ReplayPose(Structure):
    # Matches SkyDolly's PositionAndAttitudeUser: lat/lon/alt/pitch/bank/heading + velocity body X/Y/Z
    _fields_ = [
        ("latitude", c_double), ("longitude", c_double), ("altitude_ft", c_double),
        ("pitch_deg", c_double), ("bank_deg", c_double), ("heading_deg", c_double),
        ("velocity_body_x", c_double), ("velocity_body_y", c_double), ("velocity_body_z", c_double),
    ]


class _ReplayInitPosition(Structure):
    # Matches SkyDolly's SIMCONNECT_DATA_INITPOSITION: lat/lon/alt/pitch/bank/heading + onGround + airspeed
    # SDK layout: 6x double, then DWORD OnGround, DWORD Airspeed (knots).
    _fields_ = [
        ("latitude", c_double), ("longitude", c_double), ("altitude", c_double),
        ("pitch", c_double), ("bank", c_double), ("heading", c_double),
        ("on_ground", c_uint32), ("airspeed", c_uint32),
    ]


def _candidate_library_paths() -> list[Path]:
    """Return likely locations of the 64-bit SimConnect.dll.

    PyInstaller one-folder builds place collected package data below
    ``_internal``. Source installs keep the DLL beside SimConnect.py. Explicitly
    resolving the DLL avoids relying on Windows' process search path.
    """
    candidates: list[Path] = []

    try:
        spec = importlib.util.find_spec("SimConnect")
        if spec and spec.origin:
            candidates.append(Path(spec.origin).resolve().parent / "SimConnect.dll")
    except Exception:
        pass

    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        mei_path = Path(mei)
        candidates.extend(
            [
                mei_path / "SimConnect" / "SimConnect.dll",
                mei_path / "SimConnect.dll",
            ]
        )

    exe_dir = Path(sys.executable).resolve().parent
    candidates.extend(
        [
            exe_dir / "_internal" / "SimConnect" / "SimConnect.dll",
            exe_dir / "SimConnect" / "SimConnect.dll",
            exe_dir / "SimConnect.dll",
        ]
    )

    # Preserve order while removing duplicate paths.
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def get_sim_rate() -> float | None:
    """Read the simulator's current SIMULATION_RATE via the existing session.

    Used by the Black Box in-sim replay controller to preserve any pilot-set
    time acceleration (e.g. 2x / 4x) across a replay session, matching the
    SkyDolly convention of leaving the sim exactly as the user had it.
    """
    with _LOCK:
        if _SESSION_AQ is None:
            return None
        try:
            value = _SESSION_AQ.get("SIMULATION_RATE")
            return float(value) if value is not None else None
        except Exception:
            return None


def replay_set_zulu(year: int | None, day_of_year: int | None, hour: int | None, minute: int | None) -> dict[str, Any]:
    """SkyDolly-parity TimeMode: synchronize simulator zulu time.

    Called by black_box_replay when ``time_mode in {SimulationTime,
    CreationRealWorldTime}`` so the in-sim clock matches the recorded flight's
    zulu date/time during playback. Returns ok=False when SimConnect is
    offline (development mode) — never raises.

    The IDF datetime values follow SkyDolly's SkyConnect::onSendZuluDateTime
    semantics: month is implicit (current sim-date month), day is 1..365.
    """
    with _LOCK:
        if _SESSION_AQ is None:
            return {"ok": False, "reason": "no_session", "source": "OFFLINE"}
        try:
            sent = 0
            if year is not None:
                _SESSION_AQ.set("ZULU_YEAR", int(year)); sent += 1
            if day_of_year is not None:
                _SESSION_AQ.set("ZULU_DAY_OF_YEAR", int(day_of_year)); sent += 1
            if hour is not None:
                _SESSION_AQ.set("ZULU_HOURS", int(hour)); sent += 1
            if minute is not None:
                _SESSION_AQ.set("ZULU_MINUTES", int(minute)); sent += 1
            return {"ok": True, "fields_set": sent, "source": "AIRCRAFT_REQUESTS"}
        except Exception as exc:
            return {"ok": False, "reason": f"zulu_write_failed: {type(exc).__name__}: {exc}"}


def replay_read_sensor() -> dict[str, Any]:
    """SkyDolly-parity ReplaySensor: read the *real* simulator altitude/AGL during replay.

    Lets callers detect a mismatch between the replayed pose and the actual
    simulator state (e.g. when SkyDolly's onStopReplay unfreezes but the user
    aircraft was slammed onto terrain by Add-on Aircraft, or when the camera
    bridge left the user aircraft in a divergent position). SkyDolly keeps a
    separately-requested lightweight altitude sensor online throughout replay
    (see SkyDolly SimConnectReplaySensor + MSFSSimConnectPlugin::replay()).

    Implementation: opportunistic single-shot read against the existing
    AircraftRequests session via standard altitude SimVars. Returns ok=False
    when SimConnect is offline (development mode) — callers must handle that.
    """
    with _LOCK:
        if _SESSION_AQ is None:
            return {"ok": False, "reason": "no_session", "source": "OFFLINE"}
        try:
            altitude = _SESSION_AQ.get("PLANE_ALTITUDE")
            agl = _SESSION_AQ.get("PLANE_ALT_ABOVE_GROUND")
            return {
                "ok": True,
                "altitude_ft": float(altitude) if altitude is not None else None,
                "altitude_agl_ft": float(agl) if agl is not None else None,
                "sampled_monotonic": time.monotonic(),
                "source": "AIRCRAFT_REQUESTS",
            }
        except Exception as exc:
            return {"ok": False, "reason": f"sensor_read_failed: {type(exc).__name__}: {exc}"}


def set_sim_rate(rate: float) -> bool:
    """Restore the SIMULATION_RATE the user had before in-sim replay began.

    No-op when the rate is None (we never overwrite an unspecified value),
    when we are not connected, or when the underlying SimConnect call fails.
    """
    if rate is None:
        return False
    with _LOCK:
        if _SESSION_AQ is None:
            return False
        try:
            _SESSION_AQ.set("SIMULATION_RATE", float(rate))
            return True
        except Exception:
            return False


def session_dispatch_dead() -> bool:
    """#83: True while the SimConnect dispatch thread is dead (rebuilding).

    Consumers (telemetry writer) use this to avoid forcing reads into a broken
    session and to hold the last good source until the rebuild completes.
    """
    return bool(_SESSION_DISPATCH_DEAD)


def simconnect_diagnostics() -> dict[str, Any]:
    candidates = _candidate_library_paths()
    try:
        importable = importlib.util.find_spec("SimConnect") is not None
    except Exception:
        importable = False
    existing = [str(path) for path in candidates if path.is_file()]
    return {
        "frozen": bool(getattr(sys, "frozen", False)),
        "session_connected": bool(_SESSION_SM is not None and getattr(_SESSION_SM, "ok", False)),
        "session_age_seconds": round(max(0.0, time.monotonic() - _SESSION_STARTED), 1) if _SESSION_STARTED else None,
        "python_package_importable": importable,
        "dll_found": bool(existing),
        "dll_path": existing[0] if existing else None,
        "checked_paths": [str(path) for path in candidates],
        "executable": str(Path(sys.executable).resolve()),
    }



def _connect_with_timeout(sm: Any, timeout_seconds: float = 8.0) -> None:
    """Connect the upstream wrapper without its unbounded busy-wait loop."""
    _install_log_rate_limit()
    from ctypes import byref
    from ctypes.wintypes import LPCSTR

    err = sm.dll.Open(
        byref(sm.hSimConnect), LPCSTR(b"OPS ROOM"), None, 0, 0, 0
    )
    if not sm.IsHR(err, 0):
        raise ConnectionError(f"SimConnect_Open failed with HRESULT {err}")

    sm.dll.SubscribeToSystemEvent(
        sm.hSimConnect, sm.dll.EventID.EVENT_SIM_START, b"SimStart"
    )
    sm.dll.SubscribeToSystemEvent(
        sm.hSimConnect, sm.dll.EventID.EVENT_SIM_STOP, b"SimStop"
    )
    sm.dll.SubscribeToSystemEvent(
        sm.hSimConnect, sm.dll.EventID.EVENT_SIM_PAUSED, b"Paused"
    )
    sm.dll.SubscribeToSystemEvent(
        sm.hSimConnect, sm.dll.EventID.EVENT_SIM_UNPAUSED, b"Unpaused"
    )

    sm.timerThread = threading.Thread(target=sm._run, name="OpsRoom-SimConnect", daemon=True)
    sm.timerThread.start()
    deadline = time.monotonic() + timeout_seconds
    while not sm.ok and time.monotonic() < deadline:
        time.sleep(0.01)
    if not sm.ok:
        raise TimeoutError("Timed out waiting for the SimConnect OPEN event")

def _close_session() -> None:
    global _SESSION_SM, _SESSION_AQ, _SESSION_STARTED, _SESSION_CONSECUTIVE_FAILURES, _SESSION_DISPATCH_DEAD
    global _REPLAY_POSE_DEFINITION, _REPLAY_INITIAL_DEFINITION, _REPLAY_GROUND_FT
    # Replay definitions and the terrain cache are bound to the session's
    # SimConnect handle — drop them when the session is rebuilt.
    _REPLAY_POSE_DEFINITION = None
    _REPLAY_INITIAL_DEFINITION = None
    _REPLAY_GROUND_FT = None
    if _SESSION_SM is not None:
        try:
            sm = _SESSION_SM
            # The wrapper's ``exit()`` does an UNBOUNDED ``timerThread.join()``;
            # if the dispatch thread is blocked inside CallDispatch (sim not
            # delivering frames), that join hangs and the launcher force-kills
            # the app after 5 s (the slow-reload symptom). Set the quit flag
            # ourselves, join with a hard cap, then close the DLL handle.
            try:
                sm.quit = 1
            except Exception:
                pass
            try:
                if sm.timerThread is not None and sm.timerThread.is_alive():
                    sm.timerThread.join(timeout=0.5)
            except Exception:
                pass
            try:
                sm.dll.Close(sm.hSimConnect)
            except Exception:
                pass
        except Exception:
            pass
    _SESSION_SM = None
    _SESSION_AQ = None
    _SESSION_STARTED = 0.0
    _SESSION_CONSECUTIVE_FAILURES = 0
    _SESSION_DISPATCH_DEAD = False


def close_session() -> None:
    """Tear down the shared SimConnect session cleanly (v0.25.68).

    Public wrapper for app shutdown: without it the SimConnect wrapper's
    dispatch thread keeps polling a dead connection during teardown, flooding
    the log with ``OS error: WinError 0xc00000b0`` and blocking a clean exit
    (the launcher then force-kills after 5 s -- the "reload takes forever"
    symptom). Calling this stops the timer thread so uvicorn can exit fast.
    """
    _close_session()


def _note_session_read_result(ok: bool) -> None:
    """Track read health so a broken SimConnect session is rebuilt (v0.25.60)."""
    global _SESSION_CONSECUTIVE_FAILURES, _LAST_REBUILD_AT
    if _SESSION_SM is None:
        return
    if _SESSION_DISPATCH_DEAD:
        # The dispatch loop itself detected death — fail fast instead of
        # burning read attempts against a dead connection (v0.25.72, #9).
        _LAST_REBUILD_AT = time.monotonic()
        _close_session()
        return
    if ok:
        _SESSION_CONSECUTIVE_FAILURES = 0
        return
    _SESSION_CONSECUTIVE_FAILURES += 1
    if _SESSION_CONSECUTIVE_FAILURES >= _SESSION_MAX_CONSECUTIVE_FAILURES:
        _LAST_REBUILD_AT = time.monotonic()
        _close_session()


def _maybe_reset_recovery_epoch() -> None:
    """Reset the escalating cooldown once a rebuilt session proves healthy."""
    global _SESSION_DEGRADATION_EPOCHS
    if _SESSION_DEGRADATION_EPOCHS and _SESSION_STARTED and time.monotonic() - _SESSION_STARTED >= _SESSION_RECOVERY_HEALTHY_SECONDS:
        _SESSION_DEGRADATION_EPOCHS = 0


def _is_probe_worker_process() -> bool:
    """True when running inside the isolated probe worker subprocess.

    The worker owns its own process (fresh native heap), so its session may
    safely recover after a dispatch crash — if it corrupts, only the worker
    dies and the client respawns it. The MAIN app process must NEVER rebuild:
    every rebuild after a dispatch death re-opens SimConnect on the same
    (already damaged) heap, which is what trips ntdll 0xC0000374 (#98, #108).
    """
    return "--probe-worker" in sys.argv


def _ensure_session(diagnostics: dict[str, Any]) -> tuple[Any, Any]:
    global _SESSION_SM, _SESSION_AQ, _SESSION_STARTED, _SESSION_PERMANENTLY_DEGRADED
    global _LAST_REBUILD_AT  # assigned inside the degraded-cooldown branch below
    if _SESSION_PERMANENTLY_DEGRADED:
        now = time.monotonic()
        if _is_probe_worker_process():
            # Worker process: a fresh heap per process, so one guarded recovery
            # attempt after the cooldown is safe (its death is contained and
            # the client respawns it with a clean heap anyway).
            if now < _SESSION_DEGRADED_UNTIL:
                remaining = max(0.0, _SESSION_DEGRADED_UNTIL - now)
                raise ConnectionError(
                    "SimConnect parked after repeated dispatch crashes; "
                    f"auto-retry in {remaining:.0f}s (FSUIPC/WASM active meanwhile)."
                )
            _SESSION_PERMANENTLY_DEGRADED = False
            _LAST_REBUILD_AT = 0.0
            print("SimConnect recovery attempt: crash cooldown expired, rebuilding the session")
        else:
            # Main app process: permanently parked for the rest of this run.
            # Rebuilding on the same heap is exactly what produced the
            # 0xC0000374 heap-corruption crashes (observed: SIM OPEN at
            # 21:50:21 -> crash at 21:50:22 after a cooldown-triggered
            # rebuild). All reads now come from the worker subprocess
            # (LVars) / FSUIPC (telemetry) / the HTTP bridge (GSX, camera).
            raise ConnectionError(
                "SimConnect permanently parked for this run after dispatch crashes "
                "(heap safety); FSUIPC + worker probe paths remain active."
            )
    if _SESSION_SM is not None and _SESSION_AQ is not None and getattr(_SESSION_SM, "ok", False) and not _SESSION_DISPATCH_DEAD:
        _maybe_reset_recovery_epoch()
        return _SESSION_SM, _SESSION_AQ
    _close_session()
    now = time.monotonic()
    if now - _LAST_REBUILD_AT < _REBUILD_BACKOFF_SECONDS:
        # v0.25.72 (#9): a session that died is not retried immediately — the
        # wrapper keeps dying, so a 30 s backoff avoids a connect/rebuild thrash
        # loop. Reads return not-ok during this window (FSUIPC failover handles
        # it) instead of blocking on dead SimConnect.
        remaining = max(0.0, _REBUILD_BACKOFF_SECONDS - (now - _LAST_REBUILD_AT))
        raise ConnectionError(f"SimConnect session unhealthy; rebuild deferred {remaining:.0f}s")
    from SimConnect import AircraftRequests, SimConnect  # type: ignore
    library_path = diagnostics.get("dll_path")
    if not library_path:
        raise FileNotFoundError("SimConnect.dll was not found in the packaged runtime.")
    sm = SimConnect(auto_connect=False, library_path=str(library_path))
    # v0.25.72 (#9): install the guarded dispatch loop before the thread starts
    # so a dying dispatch thread can never flood the log again.
    sm._run = types.MethodType(_guarded_dispatch_run, sm)
    _connect_with_timeout(sm)
    aq = AircraftRequests(sm, _time=125)
    _SESSION_SM = sm
    _SESSION_AQ = aq
    _SESSION_STARTED = time.monotonic()
    return sm, aq




def _finite_number(value: Any) -> float | None:
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _bounded_number(value: Any, low: float, high: float, *, wrap: float | None = None) -> float | None:
    n = _finite_number(value)
    if n is None:
        return None
    if wrap:
        n = n % wrap
    return n if low <= n <= high else None


def _sanitize_telemetry(result: dict[str, Any]) -> dict[str, Any]:
    """Reject MSFS loading-screen/corrupt SimConnect values before UI/logic use."""
    data = dict(result or {})
    if not data.get("ok"):
        return data

    rejected: list[str] = []
    critical: list[str] = []

    def set_bounded(key: str, low: float, high: float, *, wrap: float | None = None, critical_key: bool = False):
        value = data.get(key)
        clean = _bounded_number(value, low, high, wrap=wrap)
        if value is not None and clean is None:
            rejected.append(key)
            if critical_key:
                critical.append(key)
        data[key] = clean

    set_bounded("lat", -90.0, 90.0, critical_key=True)
    set_bounded("lon", -180.0, 180.0, critical_key=True)
    set_bounded("altitude_ft", -2000.0, 100000.0, critical_key=True)
    set_bounded("indicated_altitude_ft", -2000.0, 100000.0, critical_key=True)
    set_bounded("pressure_altitude_ft", -5000.0, 100000.0)
    set_bounded("agl_ft", -100.0, 100000.0, critical_key=True)
    set_bounded("radio_altitude_ft", -100.0, 100000.0)
    set_bounded("indicated_speed_kts", 0.0, 800.0, critical_key=True)
    set_bounded("true_speed_kts", 0.0, 900.0)
    set_bounded("ground_speed_kts", 0.0, 900.0, critical_key=True)
    set_bounded("mach", 0.0, 1.2)
    set_bounded("vertical_speed_fpm", -18000.0, 18000.0)
    set_bounded("heading_deg", 0.0, 360.0, wrap=360.0)
    set_bounded("track_deg", 0.0, 360.0, wrap=360.0)
    set_bounded("pitch_deg", -90.0, 90.0)
    set_bounded("bank_deg", -180.0, 180.0)
    set_bounded("g_force", -3.0, 7.0)
    set_bounded("flap_index", 0.0, 20.0)
    set_bounded("flap_percent", 0.0, 100.0)
    set_bounded("gear_percent", 0.0, 100.0)
    set_bounded("spoiler_percent", 0.0, 100.0)
    set_bounded("wind_speed_kts", 0.0, 250.0)
    set_bounded("wind_direction_deg", 0.0, 360.0, wrap=360.0)
    set_bounded("sim_rate", 0.0, 16.0)
    set_bounded("fuel_flow_pph", 0.0, 250000.0)
    set_bounded("fuel_total_gal", 0.0, 250000.0)
    set_bounded("fuel_total_lb", 0.0, 2000000.0)
    set_bounded("fuel_weight_lb", 0.0, 2000000.0)
    set_bounded("gross_weight_lb", 0.0, 2000000.0)
    set_bounded("empty_weight_lb", 0.0, 2000000.0)
    set_bounded("payload_weight_lb", 0.0, 2000000.0)
    set_bounded("max_gross_weight_lb", 0.0, 2000000.0)
    set_bounded("engine_n1_percent", 0.0, 130.0)
    set_bounded("reverser_percent", 0.0, 120.0)
    set_bounded("brake_percent", 0.0, 120.0)
    set_bounded("aileron_position", -1.2, 1.2)
    set_bounded("elevator_position", -1.2, 1.2)
    set_bounded("rudder_position", -1.2, 1.2)
    set_bounded("throttle_1_percent", -25.0, 110.0)
    set_bounded("throttle_2_percent", -25.0, 110.0)
    set_bounded("body_velocity_x_fps", -5000.0, 5000.0)
    set_bounded("body_velocity_y_fps", -5000.0, 5000.0)
    set_bounded("body_velocity_z_fps", -5000.0, 5000.0)

    if data.get("indicated_altitude_ft") is None and data.get("altitude_ft") is not None:
        data["indicated_altitude_ft"] = data["altitude_ft"]
    if data.get("altitude_ft") is None and data.get("indicated_altitude_ft") is not None:
        data["altitude_ft"] = data["indicated_altitude_ft"]
    if data.get("radio_altitude_ft") is None and data.get("agl_ft") is not None:
        data["radio_altitude_ft"] = data["agl_ft"]
    if data.get("agl_ft") is None and data.get("radio_altitude_ft") is not None:
        data["agl_ft"] = data["radio_altitude_ft"]


    # Altitude coherence: a zero/near-zero barometric altitude while radio altitude
    # is thousands of feet and the aircraft is airborne is not a valid sample.
    # This protects Flight Watch, recorder deviations, RAAS and PIREP charts from
    # FSUIPC/GPS altitude offsets that temporarily return 0.
    alt_check = data.get("altitude_ft")
    agl_check = data.get("radio_altitude_ft") if data.get("radio_altitude_ft") is not None else data.get("agl_ft")
    gs_check = data.get("ground_speed_kts") or 0.0
    ias_check = data.get("indicated_speed_kts") or 0.0
    airborne_like = bool((data.get("on_ground") is False or gs_check > 100.0 or ias_check > 100.0) and (agl_check or 0.0) > 1000.0)
    if airborne_like and alt_check is not None and (abs(float(alt_check)) < 500.0 or float(alt_check) + 1000.0 < float(agl_check or 0.0)):
        data["altitude_unreliable"] = True
        data["altitude_confidence"] = "invalid"
        data.setdefault("telemetry_warnings", [])
        if isinstance(data["telemetry_warnings"], list):
            data["telemetry_warnings"].append("Altitude rejected: near-zero/barometric altitude contradicted airborne radio altitude")
        data["altitude_ft"] = None
        data["indicated_altitude_ft"] = None
        critical.append("altitude_ft")
        if "altitude_ft" not in rejected:
            rejected.append("altitude_ft")
    elif data.get("altitude_confidence") is None:
        data["altitude_confidence"] = "standard"
        data["altitude_unreliable"] = False

    # Radios and autopilot nested fields need the same guard because UI renders them directly.
    radios = data.get("radios")
    if isinstance(radios, dict):
        for radio_key, row in list(radios.items()):
            if not isinstance(row, dict):
                continue
            for freq_key in ("active_mhz", "standby_mhz"):
                value = row.get(freq_key)
                clean = _bounded_number(value, 118.0, 136.99)
                if value is not None and clean is None:
                    rejected.append(f"radios.{radio_key}.{freq_key}")
                row[freq_key] = clean
    autopilot = data.get("autopilot")
    if isinstance(autopilot, dict):
        for key, low, high in (
            ("selected_altitude_ft", -1500.0, 60000.0),
            ("selected_heading_deg", 0.0, 360.0),
            ("selected_speed_kts", 0.0, 700.0),
            ("selected_mach", 0.0, 1.0),
            ("selected_vertical_speed_fpm", -12000.0, 12000.0),
        ):
            value = autopilot.get(key)
            clean = _bounded_number(value, low, high, wrap=360.0 if key == "selected_heading_deg" else None)
            if value is not None and clean is None:
                rejected.append(f"autopilot.{key}")
            # v0.25.72 (#15): a raw 0 on an unset FCU field is not a real target
            # — treat it as unset at any altitude so the readout renders "---"
            # instead of 0 (and stops flapping when sources alternate). A locked
            # heading of exactly 0 (north) is a genuine selection and is kept.
            modes = autopilot.get("modes") if isinstance(autopilot.get("modes"), list) else []
            if key in {"selected_altitude_ft", "selected_speed_kts", "selected_vertical_speed_fpm"} and clean is not None and abs(clean) < 0.5:
                clean = None
            elif key == "selected_heading_deg" and clean is not None and abs(clean) < 0.01 and "HDG" not in modes:
                clean = None
            autopilot[key] = clean

    lat, lon = data.get("lat"), data.get("lon")
    if lat is None or lon is None:
        data["ok"] = False
        data["reason"] = "MSFS telemetry contains invalid aircraft position"
    # Loading screen / corrupt variables may return absurd values for altitude/speed. Treat those samples as invalid.
    if critical:
        data["ok"] = False
        data["telemetry_valid"] = False
        data["telemetry_invalid_fields"] = rejected
        data["reason"] = f"MSFS telemetry sample rejected: {', '.join(critical[:6])}"
    else:
        data["telemetry_valid"] = True
        data["telemetry_invalid_fields"] = rejected
    return data


def _read_position_uncached() -> dict[str, Any]:
    mock_lat = os.getenv("VATSIM_BOARD_MOCK_LAT")
    mock_lon = os.getenv("VATSIM_BOARD_MOCK_LON")
    if mock_lat and mock_lon:
        try:
            return {
                "ok": True,
                "lat": float(mock_lat),
                "lon": float(mock_lon),
                "altitude_ft": 10000.0,
                "indicated_altitude_ft": 9950.0,
                "pressure_altitude_ft": 10120.0,
                "agl_ft": 9500.0,
                "indicated_speed_kts": 250.0,
                "ground_speed_kts": 270.0,
                "heading_deg": 90.0,
                "track_deg": 91.0,
                "vertical_speed_fpm": 500.0,
                "pitch_deg": 3.0,
                "bank_deg": 0.0,
                "g_force": 1.0,
                "radio_altitude_ft": 9500.0,
                "true_speed_kts": 278.0,
                "mach": 0.45,
                "on_ground": False,
                "flap_index": 0.0,
                "flap_percent": 0.0,
                "gear_percent": 0.0,
                "spoiler_percent": 0.0,
                "wind_speed_kts": 15.0,
                "wind_direction_deg": 260.0,
                "sim_rate": 1.0,
                "paused": False,
                "slew_active": False,
                "stall_warning": False,
                "overspeed_warning": False,
                "fuel_flow_pph": 4200.0,
                "fuel_total_lb": 12000.0,
                "aircraft": {"title": "OPS ROOM MOCK AIRCRAFT", "model": "A320", "type": "A320"},
                "autopilot": {"master": True, "engaged": True, "engagement_source": "master", "ap1": True, "ap2": None, "autothrottle": True, "flight_director": True, "selected_altitude_ft": 33000.0, "selected_heading_deg": 90.0, "selected_speed_kts": 280.0, "selected_vertical_speed_fpm": 500.0, "managed_speed_mach": False, "selected_mach": None, "modes": ["HDG", "ALT"]},
                "radios": {
                    "com1": {"active_mhz": 131.375, "standby_mhz": 122.800, "transmit": True},
                    "com2": {"active_mhz": 122.800, "standby_mhz": 121.500, "transmit": False},
                },
                "source": "mock-env",
            }
        except ValueError:
            pass

    diagnostics = simconnect_diagnostics()
    try:
        import SimConnect  # noqa: F401  # type: ignore
    except Exception as exc:
        return {"ok": False, "reason": f"Python SimConnect package is not importable: {exc}", "diagnostics": diagnostics}

    if not diagnostics.get("dll_path"):
        return {"ok": False, "reason": "SimConnect.dll was not found in the packaged runtime.", "diagnostics": diagnostics}
    if _SESSION_DISPATCH_DEAD:
        # v0.25.72 (#9): fail fast instead of polling a dead connection — the
        # guarded dispatch loop already flagged the session for rebuild.
        _close_session()
        return {"ok": False, "reason": "SimConnect dispatch thread failed; session closed for rebuild", "diagnostics": simconnect_diagnostics()}

    try:
        _sm, aq = _ensure_session(diagnostics)

        # Stage 2 batched fast path: one request serves every numeric SimVar
        # in the full stream (~100 SimVars), so a full read costs one sim
        # frame instead of ~75 per-SimVar round trips (~3.5 s at cruise fps).
        # Strings and dynamic indexed vars (e.g. PAYLOAD_STATION_WEIGHT:n)
        # fall back to per-SimVar reads below.
        _batch_values = None
        if _batch_ensure(_sm, aq):
            _batch_values = _batch_read(_sm)

        def read_value(name: str) -> Any:
            if _batch_values is not None and name in _batch_values:
                return _batch_values[name]
            try:
                return aq.get(name)
            except Exception:
                return None

        lat = read_value("PLANE_LATITUDE")
        lon = read_value("PLANE_LONGITUDE")
        altitude = read_value("PLANE_ALTITUDE")
        indicated_altitude = read_value("INDICATED_ALTITUDE")
        if indicated_altitude is None:
            indicated_altitude = read_value("INDICATED_ALTITUDE_CALIBRATED")
        pressure_altitude_m = read_value("PRESSURE_ALTITUDE")
        if lat is None or lon is None:
            return {"ok": False, "reason": "MSFS is connected, but no user-aircraft position is available. Load into a flight and retry.", "diagnostics": simconnect_diagnostics()}

        indicated_speed = read_value("AIRSPEED_INDICATED")
        ground_speed = read_value("GROUND_VELOCITY")
        heading = read_value("PLANE_HEADING_DEGREES_MAGNETIC")
        gyro_heading = read_value("PLANE_HEADING_DEGREES_GYRO")
        track = read_value("GPS_GROUND_MAGNETIC_TRACK")
        vertical_speed = read_value("VERTICAL_SPEED")
        agl = read_value("PLANE_ALT_ABOVE_GROUND")
        radio_altitude = read_value("RADIO_HEIGHT")
        on_ground = read_value("SIM_ON_GROUND")
        true_speed = read_value("AIRSPEED_TRUE")
        mach = read_value("AIRSPEED_MACH")
        pitch = read_value("PLANE_PITCH_DEGREES")
        bank = read_value("PLANE_BANK_DEGREES")
        g_force = read_value("G_FORCE")
        flap_index = read_value("FLAPS_HANDLE_INDEX")
        flap_percent = read_value("TRAILING_EDGE_FLAPS_LEFT_PERCENT")
        gear_percent = read_value("GEAR_TOTAL_PCT_EXTENDED")
        spoiler_percent = read_value("SPOILERS_HANDLE_POSITION")
        wind_speed = read_value("AMBIENT_WIND_VELOCITY")
        wind_direction = read_value("AMBIENT_WIND_DIRECTION")
        sim_rate = read_value("SIMULATION_RATE")
        paused = read_value("IS_LATITUDE_LONGITUDE_FREEZE_ON")
        slew_active = read_value("IS_SLEW_ACTIVE")
        stall_warning = read_value("STALL_WARNING")
        overspeed_warning = read_value("OVERSPEED_WARNING")
        engine_count = read_value("NUMBER_OF_ENGINES")
        fuel_flow1 = read_value("TURB_ENG_FUEL_FLOW_PPH:1")
        fuel_flow2 = read_value("TURB_ENG_FUEL_FLOW_PPH:2")
        fuel_flow3 = read_value("TURB_ENG_FUEL_FLOW_PPH:3")
        fuel_flow4 = read_value("TURB_ENG_FUEL_FLOW_PPH:4")
        if fuel_flow1 is None: fuel_flow1 = read_value("ENG_FUEL_FLOW_PPH:1")
        if fuel_flow2 is None: fuel_flow2 = read_value("ENG_FUEL_FLOW_PPH:2")
        if fuel_flow3 is None: fuel_flow3 = read_value("ENG_FUEL_FLOW_PPH:3")
        if fuel_flow4 is None: fuel_flow4 = read_value("ENG_FUEL_FLOW_PPH:4")
        fuel_quantity = read_value("FUEL_TOTAL_QUANTITY")
        fuel_weight = read_value("FUEL_WEIGHT_PER_GALLON")
        engine_n1_1 = read_value("TURB_ENG_N1:1")
        engine_n1_2 = read_value("TURB_ENG_N1:2")
        engine_n1_3 = read_value("TURB_ENG_N1:3")
        engine_n1_4 = read_value("TURB_ENG_N1:4")
        engine_n2_1 = read_value("TURB_ENG_N2:1")
        engine_n2_2 = read_value("TURB_ENG_N2:2")
        engine_n2_3 = read_value("TURB_ENG_N2:3")
        engine_n2_4 = read_value("TURB_ENG_N2:4")
        engine_egt_1 = read_value("GENERAL_ENG_EXHAUST_GAS_TEMPERATURE:1")
        engine_egt_2 = read_value("GENERAL_ENG_EXHAUST_GAS_TEMPERATURE:2")
        engine_egt_3 = read_value("GENERAL_ENG_EXHAUST_GAS_TEMPERATURE:3")
        engine_egt_4 = read_value("GENERAL_ENG_EXHAUST_GAS_TEMPERATURE:4")
        reverse_1 = read_value("TURB_ENG_REVERSE_NOZZLE_PERCENT:1")
        reverse_2 = read_value("TURB_ENG_REVERSE_NOZZLE_PERCENT:2")
        brake_left = read_value("BRAKE_LEFT_POSITION")
        brake_right = read_value("BRAKE_RIGHT_POSITION")
        aileron_position = read_value("AILERON_POSITION")
        elevator_position = read_value("ELEVATOR_POSITION")
        rudder_position = read_value("RUDDER_POSITION")
        # Complex add-on flight models may not mirror actual surface positions
        # into the generic variables above. The pilot-input axes are standard
        # SimVars and provide a useful FDR fallback for Fenix/PMDG/iniBuilds.
        yoke_x_position = read_value("YOKE_X_POSITION")
        yoke_y_position = read_value("YOKE_Y_POSITION")
        rudder_pedal_position = read_value("RUDDER_PEDAL_POSITION")
        throttle_1 = read_value("GENERAL_ENG_THROTTLE_LEVER_POSITION:1")
        throttle_2 = read_value("GENERAL_ENG_THROTTLE_LEVER_POSITION:2")
        throttle_3 = read_value("GENERAL_ENG_THROTTLE_LEVER_POSITION:3")
        throttle_4 = read_value("GENERAL_ENG_THROTTLE_LEVER_POSITION:4")
        aileron_left_pct = read_value("AILERON_LEFT_DEFLECTION_PCT")
        aileron_right_pct = read_value("AILERON_RIGHT_DEFLECTION_PCT")
        elevator_pct = read_value("ELEVATOR_DEFLECTION_PCT")
        rudder_pct = read_value("RUDDER_DEFLECTION_PCT")
        flap_handle_percent = read_value("FLAPS_HANDLE_PERCENT")
        spoiler_left = read_value("SPOILERS_LEFT_POSITION")
        spoiler_right = read_value("SPOILERS_RIGHT_POSITION")
        body_velocity_x = read_value("VELOCITY_BODY_X")
        body_velocity_y = read_value("VELOCITY_BODY_Y")
        body_velocity_z = read_value("VELOCITY_BODY_Z")
        localizer_deviation = read_value("NAV_CDI:1")
        glideslope_deviation = read_value("NAV_GSI:1")
        # Autopilot values are read from the standard SimConnect surface. Many
        # advanced aircraft drive their panel through custom systems, so OPS ROOM
        # also derives engagement from the active standard AP modes when the
        # generic AUTOPILOT MASTER flag is not mirrored by the aircraft.
        ap_altitude = read_value("AUTOPILOT_ALTITUDE_LOCK_VAR")
        ap_heading = read_value("AUTOPILOT_HEADING_LOCK_DIR")
        ap_speed = read_value("AUTOPILOT_AIRSPEED_HOLD_VAR")
        ap_mach = read_value("AUTOPILOT_MACH_HOLD_VAR")
        ap_vs = read_value("AUTOPILOT_VERTICAL_HOLD_VAR")
        ap_master = read_value("AUTOPILOT_MASTER")
        ap_disengaged = read_value("AUTOPILOT_DISENGAGED")
        ap_fd = read_value("AUTOPILOT_FLIGHT_DIRECTOR_ACTIVE")
        ap_fd1 = read_value("AUTOPILOT_FLIGHT_DIRECTOR_ACTIVE:1")
        ap_fd2 = read_value("AUTOPILOT_FLIGHT_DIRECTOR_ACTIVE:2")
        ap_at = read_value("AUTOPILOT_THROTTLE_ARM")
        ap_managed_throttle = read_value("AUTOPILOT_MANAGED_THROTTLE_ACTIVE")
        ap_managed_mach = read_value("AUTOPILOT_MANAGED_SPEED_IN_MACH")
        ap_mode_values = {
            "HDG": read_value("AUTOPILOT_HEADING_LOCK"),
            "NAV": read_value("AUTOPILOT_NAV1_LOCK"),
            "ALT": read_value("AUTOPILOT_ALTITUDE_LOCK"),
            "VS": read_value("AUTOPILOT_VERTICAL_HOLD"),
            "SPD": read_value("AUTOPILOT_AIRSPEED_HOLD"),
            "MACH": read_value("AUTOPILOT_MACH_HOLD"),
            "FLC": read_value("AUTOPILOT_FLIGHT_LEVEL_CHANGE"),
            "APP": read_value("AUTOPILOT_APPROACH_HOLD"),
        }
        aircraft_title = read_value("TITLE")
        aircraft_model = read_value("ATC_MODEL")
        aircraft_type = read_value("ATC_TYPE")
        com1_active = read_value("COM_ACTIVE_FREQUENCY:1")
        com1_standby = read_value("COM_STANDBY_FREQUENCY:1")
        com2_active = read_value("COM_ACTIVE_FREQUENCY:2")
        com2_standby = read_value("COM_STANDBY_FREQUENCY:2")
        com1_transmit = read_value("COM_TRANSMIT:1")
        com2_transmit = read_value("COM_TRANSMIT:2")
        engine1 = read_value("GENERAL_ENG_COMBUSTION:1")
        engine2 = read_value("GENERAL_ENG_COMBUSTION:2")
        engine3 = read_value("GENERAL_ENG_COMBUSTION:3")
        engine4 = read_value("GENERAL_ENG_COMBUSTION:4")
        parking_brake = read_value("BRAKE_PARKING_POSITION")
        beacon_light = read_value("LIGHT_BEACON")
        logo_light = read_value("LIGHT_LOGO")
        seatbelt_switch = read_value("CABIN_SEATBELTS_ALERT_SWITCH")
        battery_master = read_value("ELECTRICAL_MASTER_BATTERY")
        external_power = read_value("EXTERNAL_POWER_ON")
        avionics_bus = read_value("ELECTRICAL_AVIONICS_BUS_VOLTAGE")
        # Standard APU SimVars. APU PCT RPM (Percent) is the primary running
        # signal: an APU that has begun its start spool-up already reads above a
        # few percent, so a small threshold counts APU START as running. The
        # generator/master switches are honoured as a defensive fallback when a
        # given aircraft does not mirror APU PCT RPM into the generic SimVar.
        apu_pct_rpm = read_value("APU_PCT_RPM")
        apu_generator_switch = read_value("APU_GENERATOR_SWITCH")
        apu_switch = read_value("APU_SWITCH")
        fuel_total_lb = None
        try:
            if fuel_quantity is not None and fuel_weight is not None:
                fuel_total_lb = float(fuel_quantity) * float(fuel_weight)
        except (TypeError, ValueError):
            fuel_total_lb = None

        # v0.25.65 supplemental weight telemetry (optional; never fabricated).
        # v0.25.75 (#32): the wrapper requests TOTAL_WEIGHT in the units it
        # declares (measured live: Pounds - an A330-300 reports ~315k lb). The
        # old code unconditionally multiplied by 32.17405 (slugs -> lb), which
        # double-converted pounds and the sanitizer rejected the inflated
        # result, so SimConnect weights always read None. Convert only when
        # the wrapper actually declares slugs; pass pounds straight through.
        _SLUG_TO_LB = 32.17405
        try:
            _weight_req = aq.find("TOTAL_WEIGHT")
            _weight_units = _weight_req.definitions[0][1].lower() if (_weight_req is not None and getattr(_weight_req, "definitions", None)) else b"pounds"
            _slug_weights = b"slug" in _weight_units
        except Exception:
            _slug_weights = False
        _weight_scale = _SLUG_TO_LB if _slug_weights else 1.0
        total_weight_raw = _finite_number(read_value("TOTAL_WEIGHT"))
        empty_weight_raw = _finite_number(read_value("EMPTY_WEIGHT"))
        max_gross_weight_raw = _finite_number(read_value("MAX_GROSS_WEIGHT"))
        fuel_weight_lb = _finite_number(read_value("FUEL_TOTAL_QUANTITY_WEIGHT"))
        station_count = _finite_number(read_value("PAYLOAD_STATION_COUNT"))
        payload_station_lb = None
        if station_count is not None and 0 < station_count <= 64:
            payload_station_total = 0.0
            payload_station_ok = True
            for station_index in range(1, int(station_count) + 1):
                station_weight = _finite_number(read_value(f"PAYLOAD_STATION_WEIGHT:{station_index}"))
                if station_weight is None or station_weight < 0.0:
                    payload_station_ok = False
                    break
                payload_station_total += float(station_weight)
            if payload_station_ok and payload_station_total > 0.0:
                payload_station_lb = round(payload_station_total * _weight_scale, 1)
        gross_weight_lb = round(total_weight_raw * _weight_scale, 1) if total_weight_raw is not None else None
        empty_weight_lb = round(empty_weight_raw * _weight_scale, 1) if empty_weight_raw is not None else None
        max_gross_weight_lb = round(max_gross_weight_raw * _weight_scale, 1) if max_gross_weight_raw is not None else None

        def bool_value(value: Any) -> bool | None:
            try:
                return bool(round(float(value))) if value is not None else None
            except (TypeError, ValueError):
                return None

        def position_16k(value: Any) -> float | None:
            """Normalize an SDK ``Position`` control value to -1..1.

            The standard yoke, pedal and generic surface input SimVars are
            requested in their documented 16K position unit. Do not interpret a
            raw value of ``1`` as full deflection; it is only one position step.
            """
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(number) or not -32768.0 <= number <= 32768.0:
                return None
            return max(-1.0, min(1.0, number / 16384.0))

        def position_32k_percent(value: Any) -> float | None:
            """Normalize the documented 0..32K brake position to 0..100%."""
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(number) or not 0.0 <= number <= 32768.0:
                return None
            return max(0.0, min(100.0, number * 100.0 / 32768.0))

        def sdk_percent(value: Any, *, signed: bool = False) -> float | None:
            """Normalize an SDK ``Percent`` value, which is already 0..100."""
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(number):
                return None
            low = -25.0 if signed else 0.0
            high = 110.0 if signed else 100.0
            return max(low, min(high, number)) if low <= number <= high else None

        def percent_over_100(value: Any, *, signed: bool = False) -> float | None:
            """Convert SDK ``Percent Over 100`` values (0..1) to percent."""
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(number):
                return None
            low = -1.0 if signed else 0.0
            if not low <= number <= 1.0:
                return None
            return number * 100.0

        # For FBW add-ons the pilot animation inputs often remain useful even
        # when the generic actual-surface input is fixed at zero. Prefer the
        # pilot input when it exists; actual deflection is recorded separately.
        pilot_aileron_fdr = position_16k(yoke_x_position)
        pilot_elevator_fdr = position_16k(yoke_y_position)
        pilot_rudder_fdr = position_16k(rudder_pedal_position)
        raw_aileron_deflection = position_16k(aileron_position)
        raw_elevator_deflection = position_16k(elevator_position)
        raw_rudder_deflection = position_16k(rudder_position)
        # Complex add-on aircraft (Fenix, etc.) may expose a flat YOKE_X/Y
        # while the actual surface deflection carries valid control input.
        # When the yoke reads neutral but the surface shows real movement,
        # prefer the surface as the pilot input. This only applies on the
        # SimConnect-only fallback path (FSUIPC axis offsets unavailable).
        if pilot_aileron_fdr is not None and raw_aileron_deflection is not None:
            if abs(pilot_aileron_fdr) <= 0.001 and abs(raw_aileron_deflection) > 0.001:
                pilot_aileron_fdr = raw_aileron_deflection
        if pilot_elevator_fdr is not None and raw_elevator_deflection is not None:
            if abs(pilot_elevator_fdr) <= 0.001 and abs(raw_elevator_deflection) > 0.001:
                pilot_elevator_fdr = raw_elevator_deflection
        aileron_fdr = pilot_aileron_fdr if pilot_aileron_fdr is not None else raw_aileron_deflection
        elevator_fdr = pilot_elevator_fdr if pilot_elevator_fdr is not None else raw_elevator_deflection
        rudder_fdr = pilot_rudder_fdr if pilot_rudder_fdr is not None else raw_rudder_deflection
        brake_left_fdr = position_32k_percent(brake_left)
        brake_right_fdr = position_32k_percent(brake_right)
        brake_fdr = max([value for value in (brake_left_fdr, brake_right_fdr) if value is not None], default=None)
        throttle_1_fdr = sdk_percent(throttle_1, signed=True)
        throttle_2_fdr = sdk_percent(throttle_2, signed=True)
        throttle_3_fdr = sdk_percent(throttle_3, signed=True)
        throttle_4_fdr = sdk_percent(throttle_4, signed=True)
        actual_aileron_pct = None
        actual_parts = [percent_over_100(v, signed=True) for v in (aileron_left_pct, aileron_right_pct)]
        actual_parts = [v for v in actual_parts if v is not None]
        if actual_parts:
            actual_aileron_pct = max(actual_parts, key=lambda v: abs(v))
        actual_elevator_pct = percent_over_100(elevator_pct, signed=True)
        actual_rudder_pct = percent_over_100(rudder_pct, signed=True)
        flap_handle_fdr = percent_over_100(flap_handle_percent)
        spoiler_actual_fdr = max([v for v in (percent_over_100(spoiler_left), percent_over_100(spoiler_right)) if v is not None], default=None)
        flap_actual_fdr = percent_over_100(flap_percent)
        spoiler_handle_fdr = percent_over_100(spoiler_percent)

        # Some complex add-ons expose standard engine SimVars as permanent zeroes
        # while the engine is demonstrably running. Preserve true zeroes for an
        # engine that is off, but mark the all-zero running block unavailable so
        # the FDR can fall back to FSUIPC or a documented aircraft adapter.
        engine_running_flags = [bool_value(engine1), bool_value(engine2), bool_value(engine3), bool_value(engine4)]
        engine_groups = [
            [engine_n1_1, engine_n2_1, engine_egt_1, fuel_flow1],
            [engine_n1_2, engine_n2_2, engine_egt_2, fuel_flow2],
            [engine_n1_3, engine_n2_3, engine_egt_3, fuel_flow3],
            [engine_n1_4, engine_n2_4, engine_egt_4, fuel_flow4],
        ]
        for index, (running, values) in enumerate(zip(engine_running_flags, engine_groups)):
            finite = []
            for value in values:
                try:
                    number = float(value)
                    if math.isfinite(number):
                        finite.append(number)
                except (TypeError, ValueError):
                    pass
            if running is True and finite and max(abs(value) for value in finite) <= 0.001:
                engine_groups[index] = [None, None, None, None]
        (engine_n1_1, engine_n2_1, engine_egt_1, fuel_flow1), (engine_n1_2, engine_n2_2, engine_egt_2, fuel_flow2), (engine_n1_3, engine_n2_3, engine_egt_3, fuel_flow3), (engine_n1_4, engine_n2_4, engine_egt_4, fuel_flow4) = engine_groups

        # Defensive APU-running derivation. Missing SimVars leave apu_running
        # False rather than raising, so behaviour is unchanged when no APU data
        # is exposed. APU PCT RPM above ~1% (spool-up) OR either APU switch on.
        apu_rpm_pct = _finite_number(apu_pct_rpm)
        apu_running = bool(
            (apu_rpm_pct is not None and apu_rpm_pct > 1.0)
            or bool_value(apu_generator_switch)
            or bool_value(apu_switch)
        )

        master_flag = bool_value(ap_master)
        active_modes = [name for name, value in ap_mode_values.items() if bool_value(value)]
        mode_engaged = bool(active_modes)
        ap_engaged = bool(master_flag or mode_engaged)
        engagement_source = "master" if master_flag else "active_modes" if mode_engaged else "none"
        pressure_altitude_ft = None
        try:
            if pressure_altitude_m is not None:
                pressure_altitude_ft = float(pressure_altitude_m) * 3.280839895
        except (TypeError, ValueError):
            pass

        aircraft_info = {
            "title": _clean_text(aircraft_title),
            "model": _clean_text(aircraft_model),
            "type": _clean_text(aircraft_type),
        }
        adapter = detect_adapter(aircraft_info)

        return {
            "ok": True,
            "lat": float(lat),
            "lon": float(lon),
            "altitude_ft": float(altitude) if altitude is not None else None,
            "indicated_altitude_ft": float(indicated_altitude) if indicated_altitude is not None else (float(altitude) if altitude is not None else None),
            "pressure_altitude_ft": pressure_altitude_ft,
            "agl_ft": float(agl) if agl is not None else None,
            "radio_altitude_ft": float(radio_altitude) if radio_altitude is not None else (float(agl) if agl is not None else None),
            "indicated_speed_kts": float(indicated_speed) if indicated_speed is not None else None,
            "true_speed_kts": float(true_speed) if true_speed is not None else None,
            "mach": float(mach) if mach is not None else None,
            "ground_speed_kts": float(ground_speed) if ground_speed is not None else None,
            "heading_deg": float(heading) if heading is not None else (float(gyro_heading) if gyro_heading is not None else None),
            "track_deg": float(track) if track is not None else None,
            "vertical_speed_fpm": float(vertical_speed) if vertical_speed is not None else None,
            "pitch_deg": float(pitch) if pitch is not None else None,
            "bank_deg": float(bank) if bank is not None else None,
            "g_force": float(g_force) if g_force is not None else None,
            "on_ground": bool(round(float(on_ground))) if on_ground is not None else None,
            "flap_index": float(flap_index) if flap_index is not None else None,
            "flap_percent": flap_actual_fdr,
            "gear_percent": float(gear_percent) if gear_percent is not None else None,
            "spoiler_percent": spoiler_handle_fdr,
            "wind_speed_kts": float(wind_speed) if wind_speed is not None else None,
            "wind_direction_deg": float(wind_direction) if wind_direction is not None else None,
            "sim_rate": float(sim_rate) if sim_rate is not None else 1.0,
            "paused": bool_value(paused),
            "slew_active": bool_value(slew_active),
            "stall_warning": bool_value(stall_warning),
            "overspeed_warning": bool_value(overspeed_warning),
            "engine_count": max(1, min(4, int(float(engine_count)))) if engine_count is not None else 2,
            "fuel_flow_pph": sum(float(v) for v in (fuel_flow1, fuel_flow2, fuel_flow3, fuel_flow4) if v is not None) if any(v is not None for v in (fuel_flow1, fuel_flow2, fuel_flow3, fuel_flow4)) else None,
            "fuel_total_gal": float(fuel_quantity) if fuel_quantity is not None else None,
            "fuel_total_lb": fuel_total_lb,
            "fuel_weight_lb": fuel_weight_lb,
            "gross_weight_lb": gross_weight_lb,
            "empty_weight_lb": empty_weight_lb,
            "payload_weight_lb": payload_station_lb,
            "max_gross_weight_lb": max_gross_weight_lb,
            "engine_n1_percent": max([float(v) for v in (engine_n1_1, engine_n1_2, engine_n1_3, engine_n1_4) if v is not None], default=None),
            "engine_n2_percent": max([float(v) for v in (engine_n2_1, engine_n2_2, engine_n2_3, engine_n2_4) if v is not None], default=None),
            "engine_egt_c": max([float(v) for v in (engine_egt_1, engine_egt_2, engine_egt_3, engine_egt_4) if v is not None], default=None),
            "engine_1_n1_percent": float(engine_n1_1) if engine_n1_1 is not None else None,
            "engine_2_n1_percent": float(engine_n1_2) if engine_n1_2 is not None else None,
            "engine_1_n2_percent": float(engine_n2_1) if engine_n2_1 is not None else None,
            "engine_2_n2_percent": float(engine_n2_2) if engine_n2_2 is not None else None,
            "engine_1_egt_c": float(engine_egt_1) if engine_egt_1 is not None else None,
            "engine_2_egt_c": float(engine_egt_2) if engine_egt_2 is not None else None,
            "engine_1_fuel_flow_pph": float(fuel_flow1) if fuel_flow1 is not None else None,
            "engine_2_fuel_flow_pph": float(fuel_flow2) if fuel_flow2 is not None else None,
            "engine_3_n1_percent": float(engine_n1_3) if engine_n1_3 is not None else None,
            "engine_4_n1_percent": float(engine_n1_4) if engine_n1_4 is not None else None,
            "engine_3_n2_percent": float(engine_n2_3) if engine_n2_3 is not None else None,
            "engine_4_n2_percent": float(engine_n2_4) if engine_n2_4 is not None else None,
            "engine_3_egt_c": float(engine_egt_3) if engine_egt_3 is not None else None,
            "engine_4_egt_c": float(engine_egt_4) if engine_egt_4 is not None else None,
            "engine_3_fuel_flow_pph": float(fuel_flow3) if fuel_flow3 is not None else None,
            "engine_4_fuel_flow_pph": float(fuel_flow4) if fuel_flow4 is not None else None,
            "reverser_percent": max([float(v) for v in (reverse_1, reverse_2) if v is not None], default=None),
            "brake_percent": brake_fdr,
            "aileron_position": aileron_fdr,
            "elevator_position": elevator_fdr,
            "rudder_position": rudder_fdr,
            "pilot_aileron_input": pilot_aileron_fdr,
            "pilot_elevator_input": pilot_elevator_fdr,
            "pilot_rudder_input": pilot_rudder_fdr,
            # First-officer sidestick axes are carried through the schema but MSFS does not
            # expose a generic per-seat FO stick (Live-validation checkpoint LVC5): the generic
            # SimConnect path leaves them None, and only a validated per-seat adapter fills them.
            "pilot_aileron_input_fo": None,
            "pilot_elevator_input_fo": None,
            "actual_aileron_percent": actual_aileron_pct,
            "actual_elevator_percent": actual_elevator_pct,
            "actual_rudder_percent": actual_rudder_pct,
            "throttle_1_percent": throttle_1_fdr,
            "throttle_2_percent": throttle_2_fdr,
            "throttle_3_percent": throttle_3_fdr,
            "throttle_4_percent": throttle_4_fdr,
            "pilot_throttle_1_percent": throttle_1_fdr,
            "pilot_throttle_2_percent": throttle_2_fdr,
            "pilot_throttle_3_percent": throttle_3_fdr,
            "pilot_throttle_4_percent": throttle_4_fdr,
            "brake_left_percent": brake_left_fdr,
            "brake_right_percent": brake_right_fdr,
            "flap_handle_percent": flap_handle_fdr,
            "spoiler_actual_percent": spoiler_actual_fdr,
            "body_velocity_x_fps": float(body_velocity_x) if body_velocity_x is not None else None,
            "body_velocity_y_fps": float(body_velocity_y) if body_velocity_y is not None else None,
            "body_velocity_z_fps": float(body_velocity_z) if body_velocity_z is not None else None,
            "localizer_deviation": float(localizer_deviation) if localizer_deviation is not None else None,
            "glideslope_deviation": float(glideslope_deviation) if glideslope_deviation is not None else None,
            "aircraft": aircraft_info,
            "aircraft_adapter": adapter,
            "systems": {
                "engine1_running": bool_value(engine1),
                "engine2_running": bool_value(engine2),
                "engine3_running": bool_value(engine3),
                "engine4_running": bool_value(engine4),
                "engines_running": bool(bool_value(engine1) or bool_value(engine2) or bool_value(engine3) or bool_value(engine4)),
                "apu_running": apu_running,
                "parking_brake": bool_value(parking_brake),
                "beacon_light": bool_value(beacon_light),
                "logo_light": bool_value(logo_light),
                "seatbelt_switch": bool_value(seatbelt_switch),
                "battery_master": bool_value(battery_master),
                "external_power": bool_value(external_power),
                "avionics_powered": (float(avionics_bus) > 3.0) if avionics_bus is not None else None,
            },
            "autopilot": {
                "master": master_flag,
                "engaged": ap_engaged,
                "engagement_source": engagement_source,
                "ap1": master_flag,
                "ap2": None,
                "disengaged": bool_value(ap_disengaged),
                "flight_director": bool_value(ap_fd1) if ap_fd1 is not None else (bool_value(ap_fd) if ap_fd is not None else bool_value(ap_fd2)),
                "autothrottle": bool_value(ap_at),
                "managed_throttle": bool_value(ap_managed_throttle),
                "selected_altitude_ft": float(ap_altitude) if ap_altitude is not None else None,
                "selected_heading_deg": float(ap_heading) if ap_heading is not None else None,
                "selected_speed_kts": float(ap_speed) if ap_speed is not None else None,
                "selected_mach": float(ap_mach) if ap_mach is not None else None,
                "selected_vertical_speed_fpm": float(ap_vs) if ap_vs is not None else None,
                "managed_speed_mach": bool_value(ap_managed_mach),
                "modes": active_modes,
                "control_support": {
                    "generic_targets": bool(adapter.get("target_write")),
                    "target_write": bool(adapter.get("target_write")),
                    "ap_master": bool(adapter.get("ap1_toggle", True)),
                    "autothrottle": bool(adapter.get("autothrottle_toggle", True)),
                    "ap2": bool(adapter.get("ap2_toggle", False)),
                    "adapter": adapter.get("key"),
                    "label": adapter.get("label"),
                    "note": adapter.get("note"),
                },
            },
            "radios": {
                "com1": {
                    "active_mhz": float(com1_active) if com1_active is not None else None,
                    "standby_mhz": float(com1_standby) if com1_standby is not None else None,
                    "transmit": bool(round(float(com1_transmit))) if com1_transmit is not None else None,
                },
                "com2": {
                    "active_mhz": float(com2_active) if com2_active is not None else None,
                    "standby_mhz": float(com2_standby) if com2_standby is not None else None,
                    "transmit": bool(round(float(com2_transmit))) if com2_transmit is not None else None,
                },
            },
            "provider_categories": {
                "core": "SIMCONNECT",
                "controls": "SIMCONNECT STANDARD INPUT/CONTROL SIMVARS",
                "engines": "SIMCONNECT INDEXED ENGINE SIMVARS",
                "systems": "SIMCONNECT STANDARD SIMVARS",
                "adapter": str(adapter.get("label") or adapter.get("key") or "GENERIC"),
            },
            "source": "simconnect",
            "sampled_monotonic": time.monotonic(),
            "diagnostics": simconnect_diagnostics(),
        }
    except (ConnectionError, TimeoutError, FileNotFoundError) as exc:
        _close_session()
        return {"ok": False, "reason": f"MSFS is not connected to SimConnect yet: {exc}", "diagnostics": diagnostics}
    except Exception as exc:
        _close_session()
        return {"ok": False, "reason": f"SimConnect position read failed: {type(exc).__name__}: {exc}", "diagnostics": diagnostics}


def _batch_ensure(sm: Any, aq: Any) -> bool:
    """Define the one data definition that covers every numeric minimal SimVar.

    Units are copied from the wrapper's own request table (via ``aq.find``) so
    the batched values need exactly the same conversions as the per-var path.
    Rebuilds automatically after a session tear-down / rebuild.
    """
    if _BATCH_STATE.get("sm_id") == id(sm) and _BATCH_STATE.get("def_id") is not None:
        return True
    _BATCH_STATE.update({"sm_id": None, "def_id": None, "request_id": None, "result": None, "done": None})
    try:
        from SimConnect.Constants import SIMCONNECT_UNUSED  # type: ignore
        from SimConnect.Enum import SIMCONNECT_DATATYPE, SIMCONNECT_SIMOBJECT_TYPE  # type: ignore

        specs: list[tuple[str, bytes, bytes]] = []
        for name in _BATCH_NAMES:
            # Skip SimVars the wrapper's request table does not know (e.g.
            # INDICATED_ALTITUDE_CALIBRATED); the per-var path returns None
            # for those too, so the sample shape stays identical.
            # For indexed SimVars, look up the ``:index`` template (no
            # setIndex/redefine round trip) and bake the concrete index into
            # the SimVar name bytes - keeps batch setup zero-traffic.
            if ":" in name:
                base, index = name.split(":", 1)
                req = aq.find(base + ":index")
                if req is None or not getattr(req, "definitions", None):
                    continue
                simvar = req.definitions[0][0].replace(b":index", (b":" + index.encode()))
                specs.append((name, simvar, req.definitions[0][1]))
                continue
            req = aq.find(name)
            if req is None or not getattr(req, "definitions", None):
                continue
            specs.append((name, req.definitions[0][0], req.definitions[0][1]))
        if not specs:
            return False
        def_id = sm.new_def_id()
        request_id = sm.new_request_id()
        for _name, simvar, units in specs:
            hr = sm.dll.AddToDataDefinition(
                sm.hSimConnect, def_id.value, simvar, units,
                SIMCONNECT_DATATYPE.SIMCONNECT_DATATYPE_FLOAT64, 0, SIMCONNECT_UNUSED,
            )
            if not sm.IsHR(hr, 0):
                return False
        done = threading.Event()
        weight_units = next((units for name, _simvar, units in specs if name == "TOTAL_WEIGHT"), b"Pounds")
        _BATCH_STATE.update({
            "sm_id": id(sm), "def_id": def_id, "request_id": request_id,
            "names": [spec[0] for spec in specs],
            "weights_in_slugs": b"slug" in weight_units.lower(),
            "result": None, "done": done,
            "backoff_until": 0.0,
        })
        _install_batch_dispatch(sm)
        return True
    except Exception:
        _BATCH_STATE.update({"sm_id": None, "def_id": None, "request_id": None, "done": None})
        return False


def _install_batch_dispatch(sm: Any) -> None:
    """Hook the session's SimObject-data dispatch to parse batched responses.

    Same pattern the app already uses for the replay Frame handler: wrap
    ``handle_simobject_event`` and delegate anything that is not our batch
    request to the original implementation.
    """
    if getattr(sm, "_ops_batch_handler_installed", False):
        return
    orig = getattr(sm, "handle_simobject_event", None)

    def handler(pObjData: Any) -> None:
        try:
            # #80: CAMERA_STATE single INT32 request (independent of the numeric
            # FLOAT64 batch above).
            cam_req = _CAMERA_STATE_STATE.get("request_id")
            cam_done = _CAMERA_STATE_STATE.get("done")
            cam_req_int = getattr(cam_req, "value", cam_req)
            if cam_req_int is not None and cam_done is not None and int(pObjData.dwRequestID) == int(cam_req_int):
                n = int(getattr(pObjData, "dwDefineCount", 0) or 0)
                if n == 1:
                    _CAMERA_STATE_STATE["result"] = int(cast(pObjData.dwData, POINTER(c_int32))[0])
                    cam_done.set()
                return
            request_id = _BATCH_STATE.get("request_id")
            done = _BATCH_STATE.get("done")
            request_id_int = getattr(request_id, "value", request_id)
            if request_id is not None and done is not None and int(pObjData.dwRequestID) == int(request_id_int):
                n = int(getattr(pObjData, "dwDefineCount", 0) or 0)
                names = _BATCH_STATE.get("names") or []
                if n == len(names):
                    values = cast(pObjData.dwData, POINTER(c_double * n)).contents
                    _BATCH_STATE["result"] = [float(v) for v in values]
                    done.set()
                return
        except Exception:
            pass
        if orig is not None:
            try:
                orig(pObjData)
            except Exception:
                pass

    sm.handle_simobject_event = handler
    sm._ops_batch_handler_installed = True


def _batch_read(sm: Any) -> dict[str, Any] | None:
    """One-request read of every numeric minimal SimVar (one sim frame)."""
    if _BATCH_STATE.get("sm_id") != id(sm) or _BATCH_STATE.get("def_id") is None:
        return None
    if time.monotonic() < float(_BATCH_STATE.get("backoff_until") or 0.0):
        return None
    try:
        from SimConnect.Enum import SIMCONNECT_SIMOBJECT_TYPE  # type: ignore

        done = _BATCH_STATE["done"]
        _BATCH_STATE["result"] = None
        done.clear()
        hr = sm.dll.RequestDataOnSimObjectType(
            sm.hSimConnect,
            _BATCH_STATE["request_id"].value,
            _BATCH_STATE["def_id"].value,
            0,
            SIMCONNECT_SIMOBJECT_TYPE.SIMCONNECT_SIMOBJECT_TYPE_USER,
        )
        if not sm.IsHR(hr, 0):
            return None
        if not done.wait(timeout=0.2):
            # The request failed server-side (e.g. an aircraft lacks a batched
            # SimVar). Back off briefly, then the per-var path takes over.
            _BATCH_STATE["backoff_until"] = time.monotonic() + 5.0
            return None
        result = _BATCH_STATE.get("result")
        _BATCH_STATE["result"] = None
        if result is None or len(result) != len(_BATCH_STATE.get("names") or []):
            return None
        return dict(zip(_BATCH_STATE["names"], result))
    except Exception:
        return None


def _read_position_minimal_batch(sm: Any, aq: Any, diagnostics: dict[str, Any]) -> dict[str, Any] | None:
    """Batched one-request minimal sample; ``None`` means fall back to per-var.

    Returns exactly the same sample shape as the per-var minimal path
    (``source: "simconnect-minimal"``), so consumers cannot tell the
    difference. String SimVars (aircraft title/model/type) are refreshed at
    2 Hz from the per-var path because they cannot share a FLOAT64 batch.
    """
    try:
        if not _batch_ensure(sm, aq):
            return None
        values = _batch_read(sm)
        if values is None:
            return None

        def num(key: str) -> float | None:
            try:
                value = values.get(key)
                return float(value) if value is not None else None
            except (TypeError, ValueError):
                return None

        def bval(value: Any) -> bool | None:
            try:
                return bool(round(float(value))) if value is not None else None
            except (TypeError, ValueError):
                return None

        lat = num("PLANE_LATITUDE")
        lon = num("PLANE_LONGITUDE")
        if lat is None or lon is None:
            return {"ok": False, "reason": "MSFS is connected, but no user-aircraft position is available. Load into a flight and retry.", "diagnostics": simconnect_diagnostics()}

        altitude = num("PLANE_ALTITUDE")
        indicated_altitude = num("INDICATED_ALTITUDE")
        if indicated_altitude is None:
            indicated_altitude = num("INDICATED_ALTITUDE_CALIBRATED")
        if indicated_altitude is None:
            indicated_altitude = altitude
        pressure_altitude = num("PRESSURE_ALTITUDE")
        heading = num("PLANE_HEADING_DEGREES_MAGNETIC")
        if heading is None:
            heading = num("PLANE_HEADING_DEGREES_GYRO")

        # String aircraft info at 2 Hz from the per-var path (not batchable).
        now = time.monotonic()
        if now - float(_BATCH_STRING_CACHE.get("t") or 0.0) >= _BATCH_STRING_INTERVAL:
            try:
                _BATCH_STRING_CACHE.update({
                    "t": now,
                    "title": _clean_text(aq.get("TITLE")),
                    "model": _clean_text(aq.get("ATC_MODEL")),
                    "type": _clean_text(aq.get("ATC_TYPE")),
                })
            except Exception:
                pass
        aircraft_info = {
            "title": str(_BATCH_STRING_CACHE.get("title") or ""),
            "model": str(_BATCH_STRING_CACHE.get("model") or ""),
            "type": str(_BATCH_STRING_CACHE.get("type") or ""),
        }

        engine_flags = [num(f"GENERAL_ENG_COMBUSTION:{i}") for i in (1, 2, 3, 4)]
        engines_running = any(bval(v) is True for v in engine_flags)
        reverser_percent: float | None = None
        for value in (num("TURB_ENG_REVERSE_NOZZLE_PERCENT:1"), num("TURB_ENG_REVERSE_NOZZLE_PERCENT:2")):
            if value is not None and math.isfinite(value):
                reverser_percent = max(reverser_percent or 0.0, value)

        # The wrapper declares TOTAL_WEIGHT in pounds (measured live: an
        # A330-300 reports ~315k lb). Some wrapper versions request slugs, so
        # convert only when the declared unit actually is slugs - never
        # double-convert (that made SimConnect weights always read None).
        slug_to_lb = 32.17405
        weight_scale = slug_to_lb if _BATCH_STATE.get("weights_in_slugs") else 1.0
        gross_weight_lb_raw = num("TOTAL_WEIGHT")
        empty_weight_lb_raw = num("EMPTY_WEIGHT")
        max_gross_weight_lb_raw = num("MAX_GROSS_WEIGHT")

        return {
            "ok": True,
            "lat": lat, "lon": lon,
            "altitude_ft": altitude,
            "indicated_altitude_ft": indicated_altitude,
            "pressure_altitude_ft": (pressure_altitude * 3.280839895) if pressure_altitude is not None else None,
            "agl_ft": num("PLANE_ALT_ABOVE_GROUND"),
            "radio_altitude_ft": num("RADIO_HEIGHT") if num("RADIO_HEIGHT") is not None else num("PLANE_ALT_ABOVE_GROUND"),
            "indicated_speed_kts": num("AIRSPEED_INDICATED"),
            "true_speed_kts": num("AIRSPEED_TRUE"),
            "ground_speed_kts": num("GROUND_VELOCITY"),
            "mach": num("AIRSPEED_MACH"),
            "heading_deg": heading,
            "track_deg": num("GPS_GROUND_MAGNETIC_TRACK"),
            "vertical_speed_fpm": num("VERTICAL_SPEED"),
            "pitch_deg": num("PLANE_PITCH_DEGREES"),
            "bank_deg": num("PLANE_BANK_DEGREES"),
            "g_force": num("G_FORCE"),
            "on_ground": bval(num("SIM_ON_GROUND")),
            "flap_index": num("FLAPS_HANDLE_INDEX"),
            "flap_percent": None,
            "flap_handle_percent": num("FLAPS_HANDLE_PERCENT"),
            "gear_percent": num("GEAR_TOTAL_PCT_EXTENDED"),
            "spoiler_percent": num("SPOILERS_HANDLE_POSITION"),
            "wind_speed_kts": num("AMBIENT_WIND_VELOCITY"),
            "wind_direction_deg": num("AMBIENT_WIND_DIRECTION"),
            "sim_rate": num("SIMULATION_RATE") if num("SIMULATION_RATE") is not None else 1.0,
            "paused": bval(num("IS_LATITUDE_LONGITUDE_FREEZE_ON")),
            "slew_active": bval(num("IS_SLEW_ACTIVE")),
            "stall_warning": bval(num("STALL_WARNING")),
            "overspeed_warning": bval(num("OVERSPEED_WARNING")),
            "engines_running": engines_running,
            "engine1_running": bval(engine_flags[0]), "engine2_running": bval(engine_flags[1]),
            "engine3_running": bval(engine_flags[2]), "engine4_running": bval(engine_flags[3]),
            "parking_brake": bval(num("BRAKE_PARKING_POSITION")),
            "reverser_percent": reverser_percent,
            "body_velocity_x_fps": num("VELOCITY_BODY_X"),
            "body_velocity_y_fps": num("VELOCITY_BODY_Y"),
            "body_velocity_z_fps": num("VELOCITY_BODY_Z"),
            "gross_weight_lb": round(gross_weight_lb_raw * weight_scale, 1) if gross_weight_lb_raw is not None else None,
            "empty_weight_lb": round(empty_weight_lb_raw * weight_scale, 1) if empty_weight_lb_raw is not None else None,
            "max_gross_weight_lb": round(max_gross_weight_lb_raw * weight_scale, 1) if max_gross_weight_lb_raw is not None else None,
            "fuel_flow_pph": None,
            "fuel_total_lb": None,
            "aircraft": aircraft_info,
            "autopilot": None,
            "aircraft_adapter": detect_adapter(aircraft_info),
            "source": "simconnect-minimal",
            "minimal": True,
        }
    except Exception:
        return None


def _read_low_rate_tier(aq: Any) -> dict[str, Any]:
    """Read the slow-changing SimVars (engine flags, surfaces, wind, sim rate).

    This is called at ~2 Hz rather than every Black Box sample cycle.  Merging
    its last-known values into each high-rate sample roughly halves the number
    of concurrent SimConnect subscriptions during recording.
    """
    def read_value(name: str) -> Any:
        try:
            return aq.get(name)
        except Exception:
            return None
    return {
        "_lr_on_ground": read_value("SIM_ON_GROUND"),
        "_lr_flap_index": read_value("FLAPS_HANDLE_INDEX"),
        "_lr_gear_percent": read_value("GEAR_TOTAL_PCT_EXTENDED"),
        "_lr_spoiler_percent": read_value("SPOILERS_HANDLE_POSITION"),
        "_lr_flap_handle_percent": read_value("FLAPS_HANDLE_PERCENT"),
        "_lr_wind_speed": read_value("AMBIENT_WIND_VELOCITY"),
        "_lr_wind_direction": read_value("AMBIENT_WIND_DIRECTION"),
        "_lr_sim_rate": read_value("SIMULATION_RATE"),
        "_lr_paused": read_value("IS_LATITUDE_LONGITUDE_FREEZE_ON"),
        "_lr_slew_active": read_value("IS_SLEW_ACTIVE"),
        "_lr_stall_warning": read_value("STALL_WARNING"),
        "_lr_overspeed_warning": read_value("OVERSPEED_WARNING"),
        "_lr_parking_brake": read_value("BRAKE_PARKING_POSITION"),
        "_lr_body_velocity_x": read_value("VELOCITY_BODY_X"),
        "_lr_body_velocity_y": read_value("VELOCITY_BODY_Y"),
        "_lr_body_velocity_z": read_value("VELOCITY_BODY_Z"),
        "_lr_engine1": read_value("GENERAL_ENG_COMBUSTION:1"),
        "_lr_engine2": read_value("GENERAL_ENG_COMBUSTION:2"),
        "_lr_engine3": read_value("GENERAL_ENG_COMBUSTION:3"),
        "_lr_engine4": read_value("GENERAL_ENG_COMBUSTION:4"),
        "_lr_reverser_1": read_value("TURB_ENG_REVERSE_NOZZLE_PERCENT:1"),
        "_lr_reverser_2": read_value("TURB_ENG_REVERSE_NOZZLE_PERCENT:2"),
        "_lr_aircraft_title": read_value("TITLE"),
        "_lr_aircraft_model": read_value("ATC_MODEL"),
        "_lr_aircraft_type": read_value("ATC_TYPE"),
    }


def _read_position_minimal_uncached() -> dict[str, Any]:
    """Black Box essentials — v0.25.60 two-tier polling.

    High-rate vars (position, attitude, speeds) are read every call (~20
    SimConnect subscriptions).  Low-rate vars (engine flags, surfaces, wind,
    sim rate, aircraft info) are served from a module-level cache refreshed at
    ~2 Hz, roughly halving total SimConnect subscription load during recording
    without dropping any field from the .opsbb file.
    """
    global _LOW_RATE_CACHE, _LOW_RATE_CACHE_TIME

    mock_lat = os.getenv("VATSIM_BOARD_MOCK_LAT")
    mock_lon = os.getenv("VATSIM_BOARD_MOCK_LON")
    if mock_lat and mock_lon:
        try:
            return {
                "ok": True,
                "lat": float(mock_lat), "lon": float(mock_lon),
                "altitude_ft": 10000.0, "indicated_altitude_ft": 9950.0,
                "pressure_altitude_ft": 10120.0, "agl_ft": 9500.0, "radio_altitude_ft": 9500.0,
                "indicated_speed_kts": 250.0, "ground_speed_kts": 270.0,
                "true_speed_kts": 278.0, "mach": 0.45,
                "heading_deg": 90.0, "track_deg": 91.0,
                "vertical_speed_fpm": 500.0, "pitch_deg": 3.0, "bank_deg": 0.0, "g_force": 1.0,
                "on_ground": False, "flap_index": 0.0, "flap_percent": 0.0, "flap_handle_percent": 0.0,
                "gear_percent": 0.0, "spoiler_percent": 0.0,
                "wind_speed_kts": 15.0, "wind_direction_deg": 260.0,
                "sim_rate": 1.0, "paused": False, "slew_active": False,
                "stall_warning": False, "overspeed_warning": False,
                "fuel_flow_pph": 4200.0, "fuel_total_lb": 12000.0,
                "aircraft": {"title": "OPS ROOM MOCK AIRCRAFT", "model": "A320", "type": "A320"},
                "autopilot": {
                    "master": True, "engaged": True, "engagement_source": "master",
                    "ap1": True, "ap2": None, "autothrottle": True, "flight_director": True,
                    "selected_altitude_ft": 33000.0, "selected_heading_deg": 90.0,
                    "selected_speed_kts": 280.0, "selected_vertical_speed_fpm": 500.0,
                    "managed_speed_mach": False, "selected_mach": None, "modes": ["HDG", "ALT"],
                },
                "engine1_running": True, "engine2_running": True, "engine3_running": False, "engine4_running": False,
                "engines_running": True,
                "reverser_percent": 0.0,
                "body_velocity_x_fps": 0.0, "body_velocity_y_fps": 0.0, "body_velocity_z_fps": 0.0,
                "source": "mock-env",
                "minimal": True,
            }
        except ValueError:
            pass

    diagnostics = simconnect_diagnostics()
    try:
        import SimConnect  # noqa: F401  # type: ignore
    except Exception as exc:
        return {"ok": False, "reason": f"Python SimConnect package is not importable: {exc}", "diagnostics": diagnostics}

    if not diagnostics.get("dll_path"):
        return {"ok": False, "reason": "SimConnect.dll was not found in the packaged runtime.", "diagnostics": diagnostics}
    if _SESSION_DISPATCH_DEAD:
        # v0.25.72 (#9): fail fast instead of polling a dead connection — the
        # guarded dispatch loop already flagged the session for rebuild.
        _close_session()
        return {"ok": False, "reason": "SimConnect dispatch thread failed; session closed for rebuild", "diagnostics": simconnect_diagnostics()}

    try:
        _sm, aq = _ensure_session(diagnostics)

        # Stage 2 batched fast path: one request for every numeric minimal
        # SimVar (one sim frame per sample) instead of ~45 per-SimVar round
        # trips. Falls back to the per-var reads below on any failure.
        batch_sample = _read_position_minimal_batch(_sm, aq, diagnostics)
        if batch_sample is not None:
            return batch_sample

        def read_value(name: str) -> Any:
            try:
                return aq.get(name)
            except Exception:
                return None

        # ── High-rate tier: read every call (position, attitude, speeds) ──
        lat = read_value("PLANE_LATITUDE")
        lon = read_value("PLANE_LONGITUDE")
        altitude = read_value("PLANE_ALTITUDE")
        indicated_altitude = read_value("INDICATED_ALTITUDE") or read_value("INDICATED_ALTITUDE_CALIBRATED")
        pressure_altitude_m = read_value("PRESSURE_ALTITUDE")
        if lat is None or lon is None:
            return {"ok": False, "reason": "MSFS is connected, but no user-aircraft position is available. Load into a flight and retry.", "diagnostics": simconnect_diagnostics()}

        indicated_speed = read_value("AIRSPEED_INDICATED")
        ground_speed = read_value("GROUND_VELOCITY")
        true_speed = read_value("AIRSPEED_TRUE")
        mach = read_value("AIRSPEED_MACH")
        heading = read_value("PLANE_HEADING_DEGREES_MAGNETIC") or read_value("PLANE_HEADING_DEGREES_GYRO")
        track = read_value("GPS_GROUND_MAGNETIC_TRACK")
        vertical_speed = read_value("VERTICAL_SPEED")
        agl = read_value("PLANE_ALT_ABOVE_GROUND")
        radio_altitude = read_value("RADIO_HEIGHT")
        pitch = read_value("PLANE_PITCH_DEGREES")
        bank = read_value("PLANE_BANK_DEGREES")
        g_force = read_value("G_FORCE")

        # ── Low-rate tier: refresh cache at 2 Hz, merge last-known on every call ──
        now = time.monotonic()
        if now - _LOW_RATE_CACHE_TIME >= _LOW_RATE_INTERVAL:
            _LOW_RATE_CACHE = _read_low_rate_tier(aq)
            _LOW_RATE_CACHE_TIME = now
        lr = _LOW_RATE_CACHE

        def _lr(key: str) -> Any:
            return lr.get(key) if lr else None

        def bool_value(value: Any) -> bool | None:
            try:
                return bool(round(float(value))) if value is not None else None
            except (TypeError, ValueError):
                return None

        engine1_running = bool_value(_lr("_lr_engine1"))
        engine2_running = bool_value(_lr("_lr_engine2"))
        engine3_running = bool_value(_lr("_lr_engine3"))
        engine4_running = bool_value(_lr("_lr_engine4"))
        engines_running = any(value is True for value in (engine1_running, engine2_running, engine3_running, engine4_running))
        reverser_percent = None
        for value in (_lr("_lr_reverser_1"), _lr("_lr_reverser_2")):
            try:
                if value is not None:
                    percent = float(value)
                    if math.isfinite(percent):
                        reverser_percent = max(reverser_percent or 0.0, percent)
            except (TypeError, ValueError):
                pass

        aircraft_info = {
            "title": _clean_text(_lr("_lr_aircraft_title")),
            "model": _clean_text(_lr("_lr_aircraft_model")),
            "type": _clean_text(_lr("_lr_aircraft_type")),
        }
        adapter = detect_adapter(aircraft_info)

        return {
            "ok": True,
            "lat": float(lat), "lon": float(lon),
            "altitude_ft": float(altitude) if altitude is not None else None,
            "indicated_altitude_ft": float(indicated_altitude) if indicated_altitude is not None else (float(altitude) if altitude is not None else None),
            "pressure_altitude_ft": (float(pressure_altitude_m) * 3.280839895) if pressure_altitude_m is not None else None,
            "agl_ft": float(agl) if agl is not None else None,
            "radio_altitude_ft": float(radio_altitude) if radio_altitude is not None else (float(agl) if agl is not None else None),
            "indicated_speed_kts": float(indicated_speed) if indicated_speed is not None else None,
            "true_speed_kts": float(true_speed) if true_speed is not None else None,
            "ground_speed_kts": float(ground_speed) if ground_speed is not None else None,
            "mach": float(mach) if mach is not None else None,
            "heading_deg": float(heading) if heading is not None else None,
            "track_deg": float(track) if track is not None else None,
            "vertical_speed_fpm": float(vertical_speed) if vertical_speed is not None else None,
            "pitch_deg": float(pitch) if pitch is not None else None,
            "bank_deg": float(bank) if bank is not None else None,
            "g_force": float(g_force) if g_force is not None else None,
            "on_ground": bool(round(float(_lr("_lr_on_ground")))) if _lr("_lr_on_ground") is not None else None,
            "flap_index": float(_lr("_lr_flap_index")) if _lr("_lr_flap_index") is not None else None,
            "flap_percent": None,
            "flap_handle_percent": float(_lr("_lr_flap_handle_percent")) if _lr("_lr_flap_handle_percent") is not None else None,
            "gear_percent": float(_lr("_lr_gear_percent")) if _lr("_lr_gear_percent") is not None else None,
            "spoiler_percent": float(_lr("_lr_spoiler_percent")) if _lr("_lr_spoiler_percent") is not None else None,
            "wind_speed_kts": float(_lr("_lr_wind_speed")) if _lr("_lr_wind_speed") is not None else None,
            "wind_direction_deg": float(_lr("_lr_wind_direction")) if _lr("_lr_wind_direction") is not None else None,
            "sim_rate": float(_lr("_lr_sim_rate")) if _lr("_lr_sim_rate") is not None else 1.0,
            "paused": bool_value(_lr("_lr_paused")),
            "slew_active": bool_value(_lr("_lr_slew_active")),
            "stall_warning": bool_value(_lr("_lr_stall_warning")),
            "overspeed_warning": bool_value(_lr("_lr_overspeed_warning")),
            "engines_running": engines_running,
            "engine1_running": engine1_running, "engine2_running": engine2_running,
            "engine3_running": engine3_running, "engine4_running": engine4_running,
            "parking_brake": bool_value(_lr("_lr_parking_brake")),
            "reverser_percent": reverser_percent,
            "body_velocity_x_fps": float(_lr("_lr_body_velocity_x")) if _lr("_lr_body_velocity_x") is not None else None,
            "body_velocity_y_fps": float(_lr("_lr_body_velocity_y")) if _lr("_lr_body_velocity_y") is not None else None,
            "body_velocity_z_fps": float(_lr("_lr_body_velocity_z")) if _lr("_lr_body_velocity_z") is not None else None,
            "fuel_flow_pph": None,
            "fuel_total_lb": None,
            "aircraft": aircraft_info,
            "autopilot": None,
            "aircraft_adapter": adapter,
            "source": "simconnect-minimal",
            "minimal": True,
        }
    except Exception as exc:
        return {"ok": False, "reason": f"Minimal SimConnect position read failed: {exc}", "diagnostics": simconnect_diagnostics()}


def _worker_reads_enabled() -> bool:
    """True when the main process routes SimConnect READS through the worker.

    #108 next tier: in packaged builds the main process NEVER opens SimConnect
    for reads - position, identity and camera all come from the probe worker
    subprocess, which owns its own native heap and is respawned on death. That
    is what eliminates the 0xC0000374 heap-corruption class for every user,
    with or without FSUIPC. Source/dev runs keep the in-process read path
    (simpler to debug, and the crash class is packaged-app-specific) unless
    ``OPSROOM_PROBE_WORKER=1`` explicitly enables the worker for live
    verification. ``OPSROOM_PROBE_WORKER=0`` forces it off.
    """
    flag = os.getenv("OPSROOM_PROBE_WORKER", "").strip().lower()
    if flag == "1":
        return True
    if flag == "0":
        return False
    return bool(getattr(sys, "frozen", False))


def _worker_read_position() -> dict[str, Any] | None:
    """Full position sample through the probe worker; None = worker unavailable."""
    if not _worker_reads_enabled():
        return None
    try:
        from .simconnect_probe_client import read_position as _worker_read
        return _worker_read()
    except Exception:
        return None


def _worker_read_minimal() -> dict[str, Any] | None:
    """Minimal position sample through the probe worker; None = unavailable."""
    if not _worker_reads_enabled():
        return None
    try:
        from .simconnect_probe_client import read_position_minimal as _worker_read
        return _worker_read()
    except Exception:
        return None


def _worker_camera_state() -> int | None:
    """CAMERA_STATE enum through the probe worker; None = unavailable."""
    if not _worker_reads_enabled():
        return None
    try:
        from .simconnect_probe_client import camera_state as _worker_camera
        return _worker_camera()
    except Exception:
        return None


def read_position_minimal(force: bool = False) -> dict[str, Any]:
    """Light-perimeter SimConnect read used by the Black Box record loop.

    ``read_position_minimal`` deliberately bypasses the shared position cache
    the full ``read_position()`` uses.  Writing the slim minimal result into
    the same slot would poison later non-forced callers (Flight Watch, PIREP,
    GSX, RAAS) - they would receive a sparse minimal shape and treat any
    absent field as ``None``.  The Black Box record loop is the only caller
    and always passes ``force=True``, so this function is always fresh and
    non-poisoning by design.

    #108 next tier: in packaged builds this reads through the probe worker so
    the main process never opens SimConnect. If the worker is unavailable the
    read fails fast (never opens a main-process session in packaged builds);
    source/dev runs keep the in-process path.
    """
    worker_result = _worker_read_minimal()
    if worker_result is not None:
        return _sanitize_telemetry(worker_result)
    if _worker_reads_enabled():
        return {
            "ok": False,
            "reason": "SimConnect worker unavailable; reads are worker-isolated in this build",
            "diagnostics": simconnect_diagnostics(),
            "minimal": True,
        }
    with _LOCK:
        result = _sanitize_telemetry(_read_position_minimal_uncached())
        _note_session_read_result(bool(result.get("ok")))
        return result


def read_position(force: bool = False) -> dict[str, Any]:
    """Read the current user-aircraft position from MSFS.

    Failures are returned as structured data so the FIDS remains usable with
    manual airport selection. A very short cache prevents duplicate connection
    attempts when several endpoints are requested together.

    #108 next tier: in packaged builds the read goes through the probe worker
    (the main process never opens SimConnect for reads); source/dev runs keep
    the in-process path unless ``OPSROOM_PROBE_WORKER=1``.
    """
    global _CACHE, _CACHE_TIME
    now = time.monotonic()
    with _LOCK:
        if not force and _CACHE is not None and now - _CACHE_TIME < _CACHE_SECONDS:
            return dict(_CACHE)
        worker_result = _worker_read_position()
        if worker_result is not None:
            result = _sanitize_telemetry(worker_result)
        elif _worker_reads_enabled():
            result = {
                "ok": False,
                "reason": "SimConnect worker unavailable; reads are worker-isolated in this build",
                "diagnostics": simconnect_diagnostics(),
            }
        else:
            result = _sanitize_telemetry(_read_position_uncached())
            _note_session_read_result(bool(result.get("ok")))
        _CACHE = dict(result)
        _CACHE_TIME = time.monotonic()
        return result



def _normalize_com_frequency(value: Any) -> float:
    try:
        frequency = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Frequency must be a number such as 131.375") from exc
    if not 118.0 <= frequency <= 136.99:
        raise ValueError("COM frequency must be between 118.000 and 136.990 MHz")
    # MSFS supports 25 kHz and 8.33 kHz channel displays. Five-kHz display
    # precision covers both without changing a channel entered by the user.
    return round(round(frequency * 200.0) / 200.0, 3)


def _bcd16_com_value(frequency_mhz: float) -> int:
    """Return the legacy BCD value used by COM*_RADIO_SET events.

    This fallback is only used if the modern *_SET_HZ event is unavailable.
    Legacy BCD events cannot represent every 8.33 kHz channel.
    """
    digits = f"{frequency_mhz:.2f}".replace(".", "")
    digits = digits[-4:]
    value = 0
    for digit in digits:
        value = (value << 4) | int(digit)
    return value


def _send_sim_event(sm: Any, event_name: str, value: int = 0) -> bool:
    from ctypes.wintypes import DWORD

    event = None
    # Different SimConnect Python builds accept either str or bytes. Try both.
    for key in (event_name, event_name.encode("ascii")):
        try:
            event = sm.map_to_sim_event(key)
        except Exception:
            event = None
        if event is not None:
            break
    if event is None:
        return False
    for payload in (DWORD(int(value)), int(value)):
        try:
            if sm.send_event(event, payload):
                return True
        except Exception:
            continue
    return False


def set_radio_frequency(radio: int, frequency_mhz: Any, target: str = "standby") -> dict[str, Any]:
    """Tune COM1 or COM2 through SimConnect.

    v0.20.0 separates command dispatch from readback verification. Some
    aircraft tune correctly but publish stale radio readback for a few seconds;
    the UI must not remain stuck on TUNING while waiting for strict verification.
    """
    global _CACHE, _CACHE_TIME
    if radio not in {1, 2}:
        raise ValueError("Radio must be 1 or 2")
    target = str(target or "standby").lower()
    if target not in {"standby", "active"}:
        raise ValueError("Target must be standby or active")
    frequency = _normalize_com_frequency(frequency_mhz)
    if os.getenv("VATSIM_BOARD_MOCK_LAT") and os.getenv("VATSIM_BOARD_MOCK_LON"):
        return {"ok": True, "sent": True, "verified": True, "pending_readback": False, "radio": radio, "target": target, "frequency_mhz": frequency, "event": "MOCK_RADIO_SET", "telemetry": read_position(force=True)}

    diagnostics = simconnect_diagnostics()
    with _LOCK:
        sm, _aq = _ensure_session(diagnostics)
        prefix = "COM" if radio == 1 else "COM2"
        modern = f"{prefix}_{'STBY_' if target == 'standby' else ''}RADIO_SET_HZ"
        legacy = f"{prefix}_{'STBY_' if target == 'standby' else ''}RADIO_SET"
        candidates = [(modern, int(round(frequency * 1_000_000.0))), (legacy, _bcd16_com_value(frequency))]
        for event_name, payload in candidates:
            if _send_sim_event(sm, event_name, payload):
                _CACHE = None
                _CACHE_TIME = 0.0
                return {
                    "ok": True,
                    "sent": True,
                    "verified": False,
                    "pending_readback": True,
                    "radio": radio,
                    "target": target,
                    "frequency_mhz": frequency,
                    "event": event_name,
                    "reason": "Radio event was sent; readback verification will continue through /api/radios.",
                }
    raise RuntimeError(f"MSFS rejected {modern} and {legacy}")


def swap_radio(radio: int) -> dict[str, Any]:
    global _CACHE, _CACHE_TIME
    if radio not in {1, 2}:
        raise ValueError("Radio must be 1 or 2")
    if os.getenv("VATSIM_BOARD_MOCK_LAT") and os.getenv("VATSIM_BOARD_MOCK_LON"):
        return {"ok": True, "radio": radio, "event": "MOCK_RADIO_SWAP", "telemetry": read_position(force=True)}
    diagnostics = simconnect_diagnostics()
    with _LOCK:
        sm, _aq = _ensure_session(diagnostics)
        event_name = "COM_STBY_RADIO_SWAP" if radio == 1 else "COM2_RADIO_SWAP"
        if not _send_sim_event(sm, event_name, 0):
            raise RuntimeError(f"MSFS rejected {event_name}")
        _CACHE = None
        _CACHE_TIME = 0.0
    time.sleep(0.12)
    state = read_position(force=True)
    return {"ok": True, "radio": radio, "event": event_name, "telemetry": state}



def _normalize_autopilot_target(kind: str, value: Any) -> tuple[str, int]:
    kind = str(kind or "").strip().lower()
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("The selected value must be numeric") from exc
    if kind == "altitude":
        if not -1500 <= number <= 60000:
            raise ValueError("Selected altitude must be between -1500 and 60000 ft")
        return "AP_ALT_VAR_SET_ENGLISH", int(round(number))
    if kind == "heading":
        return "HEADING_BUG_SET", int(round(number)) % 360
    if kind == "speed":
        if not 60 <= number <= 700:
            raise ValueError("Selected speed must be between 60 and 700 kt")
        return "AP_SPD_VAR_SET", int(round(number))
    if kind in {"vertical_speed", "vs"}:
        if not -12000 <= number <= 12000:
            raise ValueError("Selected vertical speed must be between -12000 and 12000 fpm")
        return "AP_VS_VAR_SET_ENGLISH", int(round(number))
    raise ValueError("Target must be altitude, heading, speed, or vertical_speed")


def set_autopilot_target(kind: str, value: Any) -> dict[str, Any]:
    global _CACHE, _CACHE_TIME
    current = read_position(force=True)
    if not current.get("ok"):
        raise RuntimeError(current.get("reason") or "SimConnect is unavailable")
    support = (current.get("autopilot") or {}).get("control_support") or {}
    if not support.get("target_write"):
        raise RuntimeError(support.get("note") or "FCU target control is read-only for this aircraft")
    event_name, event_value = _normalize_autopilot_target(kind, value)
    if os.getenv("VATSIM_BOARD_MOCK_LAT") and os.getenv("VATSIM_BOARD_MOCK_LON"):
        return {"ok": True, "target": kind, "value": event_value, "event": f"MOCK_{event_name}", "telemetry": read_position(force=True)}
    diagnostics = simconnect_diagnostics()
    with _LOCK:
        sm, aq = _ensure_session(diagnostics)
        sent = _send_sim_event(sm, event_name, event_value)
        # Standard AP SimVars are settable on many default aircraft. This
        # fallback is useful when a panel ignores the corresponding key event.
        if not sent:
            simvar = {
                "altitude": "AUTOPILOT_ALTITUDE_LOCK_VAR",
                "heading": "AUTOPILOT_HEADING_LOCK_DIR",
                "speed": "AUTOPILOT_AIRSPEED_HOLD_VAR",
                "vertical_speed": "AUTOPILOT_VERTICAL_HOLD_VAR",
                "vs": "AUTOPILOT_VERTICAL_HOLD_VAR",
            }[str(kind).lower()]
            try:
                sent = bool(aq.set(simvar, event_value))
                event_name = f"SIMVAR:{simvar}"
            except Exception:
                sent = False
        if not sent:
            raise RuntimeError(f"The current aircraft rejected {event_name}")
        _CACHE = None
        _CACHE_TIME = 0.0
    time.sleep(0.15)
    return {"ok": True, "target": kind, "value": event_value, "event": event_name, "telemetry": read_position(force=True)}


def set_autopilot_action(action: str, enabled: Any = None) -> dict[str, Any]:
    """Request AP1 or autothrottle state and verify the aircraft response.

    The standard AUTO_THROTTLE_ARM event is a toggle event. It must never be
    sent with an assumed ON/OFF parameter. We read the actual aircraft state,
    send one transition only when required, then confirm the result.
    """
    global _CACHE, _CACHE_TIME
    action = str(action or "").strip().lower()
    current = read_position(force=True)
    if not current.get("ok"):
        raise RuntimeError(current.get("reason") or "SimConnect is unavailable")
    autopilot = current.get("autopilot") or {}

    if action in {"ap1_toggle", "ap1", "ap_master", "master"}:
        state_key = "ap1"
        current_state = bool(autopilot.get(state_key))
        desired = (not current_state) if enabled is None else bool(enabled)
    elif action in {"autothrottle_toggle", "autothrottle", "athr", "a_t"}:
        state_key = "autothrottle"
        current_state = bool(autopilot.get(state_key))
        desired = (not current_state) if enabled is None else bool(enabled)
    elif action == "ap2":
        raise ValueError("AP2 requires a verified aircraft-specific adapter.")
    else:
        raise ValueError("Action must be ap1_toggle, autothrottle_toggle, or ap2")

    if current_state == desired:
        return {
            "ok": True,
            "verified": True,
            "action": action,
            "requested": desired,
            "enabled": current_state,
            "event": "NO CHANGE REQUIRED",
            "telemetry": current,
        }

    if os.getenv("VATSIM_BOARD_MOCK_LAT") and os.getenv("VATSIM_BOARD_MOCK_LON"):
        mock = dict(current)
        mock_ap = dict(mock.get("autopilot") or {})
        mock_ap[state_key] = desired
        if state_key == "ap1":
            mock_ap["master"] = desired
        mock["autopilot"] = mock_ap
        return {"ok": True, "verified": True, "action": action, "requested": desired, "enabled": desired, "event": "MOCK", "telemetry": mock}

    diagnostics = simconnect_diagnostics()
    method = ""
    sent = False
    with _LOCK:
        sm, aq = _ensure_session(diagnostics)
        if state_key == "ap1":
            event_name = "AUTOPILOT_ON" if desired else "AUTOPILOT_OFF"
            sent = _send_sim_event(sm, event_name, 0)
            method = event_name
        else:
            # First attempt the settable SimVar. This is deterministic where the
            # aircraft supports it. If ignored, fall back to one toggle event.
            try:
                sent = bool(aq.set("AUTOPILOT_THROTTLE_ARM", 1 if desired else 0))
                if sent:
                    method = "SIMVAR:AUTOPILOT_THROTTLE_ARM"
            except Exception:
                sent = False
            if not sent:
                sent = _send_sim_event(sm, "AUTO_THROTTLE_ARM", 0)
                method = "AUTO_THROTTLE_ARM"
        if not sent:
            raise RuntimeError("The current aircraft rejected the autopilot command")
        _CACHE = None
        _CACHE_TIME = 0.0

    state = current
    actual = current_state
    for _ in range(5):
        time.sleep(0.3)
        state = read_position(force=True)
        actual = bool((state.get("autopilot") or {}).get(state_key)) if state.get("ok") else actual
        if actual == desired:
            break

    if actual != desired:
        with _LOCK:
            sm, _aq = _ensure_session(diagnostics)
            if state_key == "ap1":
                # Some aircraft ignore the explicit ON/OFF event but accept the
                # standard master toggle. Send it once only after verification.
                fallback_sent = _send_sim_event(sm, "AP_MASTER", 0)
                if fallback_sent:
                    method += " -> AP_MASTER"
            else:
                # AUTO_THROTTLE_ARM is toggle-only. Send one fallback toggle only
                # after the deterministic SimVar attempt failed to change state.
                fallback_sent = _send_sim_event(sm, "AUTO_THROTTLE_ARM", 0)
                if fallback_sent:
                    method += " -> AUTO_THROTTLE_ARM"
            _CACHE = None
            _CACHE_TIME = 0.0
        for _ in range(5):
            time.sleep(0.3)
            state = read_position(force=True)
            actual = bool((state.get("autopilot") or {}).get(state_key)) if state.get("ok") else actual
            if actual == desired:
                break

    return {
        "ok": True,
        "verified": actual == desired,
        "action": action,
        "requested": desired,
        "enabled": actual,
        "event": method,
        "telemetry": state,
    }


def autopilot_state(force: bool = False) -> dict[str, Any]:
    telemetry = read_position(force=force)
    if not telemetry.get("ok"):
        return {"ok": False, "reason": telemetry.get("reason", "SimConnect is not available"), "autopilot": {}}
    return {"ok": True, "autopilot": telemetry.get("autopilot") or {}, "aircraft": telemetry.get("aircraft") or {}, "sampled_monotonic": telemetry.get("sampled_monotonic")}


def radio_state(force: bool = False) -> dict[str, Any]:
    telemetry = read_position(force=force)
    if not telemetry.get("ok"):
        return {"ok": False, "reason": telemetry.get("reason", "SimConnect is not available"), "radios": {}}
    return {"ok": True, "radios": telemetry.get("radios") or {}, "sampled_monotonic": telemetry.get("sampled_monotonic")}


def replay_subscribe_frame() -> dict[str, Any]:
    """Subscribe to the SimConnect Frame system event on the *primary* session.

    SkyDolly approach — one SimConnect session drives both telemetry reads and
    replay writes.  The replay ``_loop`` waits on ``replay_wait_frame()``.
    """
    global _REPLAY_FRAME_SUBSCRIBED, _REPLAY_FRAME_EVENT_ID, _REPLAY_FRAME_ORIG_HANDLER, _REPLAY_FRAME_LAST_MONO
    with _LOCK:
        if _REPLAY_FRAME_SUBSCRIBED:
            replay_unsubscribe_frame()
        diagnostics = simconnect_diagnostics()
        try:
            sm, _aq = _ensure_session(diagnostics)
            event_id = sm.map_to_sim_event(b"Frame")
            _REPLAY_FRAME_ORIG_HANDLER = sm.handle_id_event
            _REPLAY_FRAME_LAST_MONO = time.monotonic()

            def handler(event: Any) -> None:
                try:
                    if int(event.uEventID) == int(event_id.value):
                        with _REPLAY_FRAME_COND:
                            _REPLAY_FRAME_LAST_MONO = time.monotonic()
                            _REPLAY_FRAME_COND.notify_all()
                except Exception:
                    pass
                try:
                    _REPLAY_FRAME_ORIG_HANDLER(event)
                except Exception:
                    pass

            sm.handle_id_event = handler
            hr = sm.dll.SubscribeToSystemEvent(sm.hSimConnect, event_id.value, b"Frame")
            if not sm.IsHR(hr, 0):
                sm.handle_id_event = _REPLAY_FRAME_ORIG_HANDLER
                raise RuntimeError(f"SimConnect rejected Frame subscription ({hr})")
            _REPLAY_FRAME_EVENT_ID = event_id
            _REPLAY_FRAME_SUBSCRIBED = True
            return {"ok": True, "source": "SIMCONNECT FRAME"}
        except Exception as exc:
            return {"ok": False, "source": "MONOTONIC FALLBACK", "reason": f"{type(exc).__name__}: {exc}"}


def replay_unsubscribe_frame() -> None:
    """Unsubscribe from the Frame system event and restore the original handler."""
    global _REPLAY_FRAME_SUBSCRIBED, _REPLAY_FRAME_EVENT_ID, _REPLAY_FRAME_ORIG_HANDLER
    with _LOCK:
        if _REPLAY_FRAME_EVENT_ID is not None:
            try:
                sm, _ = _ensure_session(simconnect_diagnostics())
                sm.dll.UnsubscribeFromSystemEvent(sm.hSimConnect, _REPLAY_FRAME_EVENT_ID.value)
                if _REPLAY_FRAME_ORIG_HANDLER is not None:
                    sm.handle_id_event = _REPLAY_FRAME_ORIG_HANDLER
            except Exception:
                pass
        _REPLAY_FRAME_SUBSCRIBED = False
        _REPLAY_FRAME_EVENT_ID = None
        _REPLAY_FRAME_ORIG_HANDLER = None


def replay_wait_frame(timeout: float = 0.12) -> tuple[bool, float]:
    """Wait for a Frame event or timeout.

    Returns ``(was_signaled, monotonic_timestamp)``.
    SkyDolly-style: the replay thread sleeps here, woken by the Frame callback.
    """
    with _REPLAY_FRAME_COND:
        notified = _REPLAY_FRAME_COND.wait(timeout=timeout)
        return notified, _REPLAY_FRAME_LAST_MONO


def replay_is_frame_subscribed() -> bool:
    return _REPLAY_FRAME_SUBSCRIBED


def replay_set_freeze(enabled: bool) -> dict[str, Any]:
    """Freeze/unfreeze the user aircraft axes without pausing the sim."""
    diagnostics = simconnect_diagnostics()
    with _LOCK:
        try:
            sm, _aq = _ensure_session(diagnostics)
            from SimConnect import AircraftEvents  # type: ignore
            events = AircraftEvents(sm)
            value = 1 if enabled else 0
            for name in ("FREEZE_LATITUDE_LONGITUDE_SET", "FREEZE_ALTITUDE_SET", "FREEZE_ATTITUDE_SET"):
                event = events.find(name)
                if event is None:
                    raise RuntimeError(f"SimConnect event {name} is unavailable")
                event(value)
            return {"ok": True, "frozen": bool(enabled)}
        except Exception as exc:
            return {"ok": False, "frozen": False, "reason": f"{type(exc).__name__}: {exc}"}


_REPLAY_POSE_DEFINITION: Any | None = None


def _ensure_replay_pose_definition(sm: Any) -> Any:
    """Register the replay pose data definition once per session and reuse it.

    SkyDolly parity: the 9-FLOAT64 pose definition is registered a single time
    at first use and reused for every frame.  Registering per frame cost ~300
    extra SimConnect calls/sec (new_def_id + 9x AddToDataDefinition) which
    stuttered the sim during replay.
    """
    global _REPLAY_POSE_DEFINITION
    if _REPLAY_POSE_DEFINITION is not None:
        return _REPLAY_POSE_DEFINITION
    from SimConnect.Enum import SIMCONNECT_DATATYPE  # type: ignore
    from SimConnect.Constants import SIMCONNECT_UNUSED  # type: ignore
    definition = sm.new_def_id()
    definitions = (
        (b"PLANE LATITUDE", b"degrees"),
        (b"PLANE LONGITUDE", b"degrees"),
        (b"PLANE ALTITUDE", b"feet"),
        (b"PLANE PITCH DEGREES", b"degrees"),
        (b"PLANE BANK DEGREES", b"degrees"),
        (b"PLANE HEADING DEGREES TRUE", b"degrees"),
        (b"VELOCITY BODY X", b"feet per second"),
        (b"VELOCITY BODY Y", b"feet per second"),
        (b"VELOCITY BODY Z", b"feet per second"),
    )
    for name, units in definitions:
        hr = sm.dll.AddToDataDefinition(
            sm.hSimConnect, definition.value, name, units,
            SIMCONNECT_DATATYPE.SIMCONNECT_DATATYPE_FLOAT64, 0, SIMCONNECT_UNUSED,
        )
        if not sm.IsHR(hr, 0):
            raise RuntimeError(f"Could not define replay pose variable {name.decode()}")
    _REPLAY_POSE_DEFINITION = definition
    return definition


def _replay_ground_altitude_ft(sm: Any, aq: Any) -> float | None:
    """Cached terrain elevation under the aircraft (feet MSL), refreshed every 0.5 s.

    The wrapper's ``GROUND_ALTITUDE`` request is meters and costs ~35 ms per read,
    so it is cached: the replay floor only needs terrain that is a few seconds
    stale, not frame-fresh.
    """
    global _REPLAY_GROUND_FT, _REPLAY_GROUND_MONO
    now = time.monotonic()
    if _REPLAY_GROUND_FT is not None and now - _REPLAY_GROUND_MONO < _REPLAY_GROUND_INTERVAL:
        return _REPLAY_GROUND_FT
    try:
        meters = aq.get("GROUND_ALTITUDE")
        if meters is None:
            return _REPLAY_GROUND_FT
        value = float(meters) * 3.280839895
        with _REPLAY_GROUND_LOCK:
            _REPLAY_GROUND_FT = value
            _REPLAY_GROUND_MONO = now
        return value
    except Exception:
        return _REPLAY_GROUND_FT


def _replay_clamped_altitude(frame: dict[str, Any], altitude_ft: float, sm: Any, aq: Any) -> float:
    """Floor pose altitude so the aircraft is never written below the terrain.

    Some recordings (Fenix-era FSUIPC altitude) drift off true MSL near the
    arrival field, going negative while AGL stays positive.  The sim terrain
    under the aircraft is a safe floor: airborne frames ride at terrain + the
    recorded AGL (correct height over the surface), on-ground frames snap to
    just above the surface so the wheels meet the runway.

    The terrain probe is only issued while the aircraft is near the surface
    (AGL below ``_REPLAY_GROUND_AGL_FLOOR``) and is cached, so cruise replay
    never pays the ~35 ms SimConnect read.
    """
    agl = _finite_number(frame.get("agl_ft"))
    on_ground = bool(frame.get("on_ground"))
    if not on_ground and (agl is None or agl < 0 or agl > _REPLAY_GROUND_AGL_FLOOR):
        return altitude_ft
    ground = _replay_ground_altitude_ft(sm, aq)
    if ground is None:
        return altitude_ft
    if on_ground:
        return max(altitude_ft, ground + 3.0)
    return max(altitude_ft, ground + float(agl) + 2.0)


def _ensure_replay_initial_definition(sm: Any) -> Any:
    """Register Initial Position data definition using SIMCONNECT_DATATYPE_INITPOSITION.

    SkyDolly reference: ``SimConnect_AddToDataDefinition(handle, defId, "Initial Position", nullptr, SIMCONNECT_DATATYPE_INITPOSITION)``
    """
    global _REPLAY_INITIAL_DEFINITION
    if _REPLAY_INITIAL_DEFINITION is not None:
        return _REPLAY_INITIAL_DEFINITION
    from SimConnect.Enum import SIMCONNECT_DATATYPE
    from SimConnect.Constants import SIMCONNECT_UNUSED
    definition = sm.new_def_id()
    hr = sm.dll.AddToDataDefinition(
        sm.hSimConnect, definition.value, b"Initial Position", None,
        SIMCONNECT_DATATYPE.SIMCONNECT_DATATYPE_INITPOSITION, 0, SIMCONNECT_UNUSED,
    )
    if not sm.IsHR(hr, 0):
        raise RuntimeError("Could not define Initial Position data definition")
    _REPLAY_INITIAL_DEFINITION = definition
    return definition


def replay_apply_state(frame: dict[str, Any], *, initial: bool = False, apply_controls: bool = False) -> dict[str, Any]:
    """Apply one coherent replay frame without issuing camera commands.

    Seven pose fields (lat, lon, alt, pitch, bank, true heading) plus body
    velocity (X, Y, Z) are sent in one ``SetDataOnSimObject`` block as 9
    FLOAT64 values — matching SkyDolly's ``PositionAndAttitudeUser`` layout.
    Controls use SimConnect KEY EVENTS (``TransmitClientEvent``) for primary
    surfaces and ``aq.set()`` for throttle/engine combustion.
    """
    diagnostics = simconnect_diagnostics()
    started = time.perf_counter()
    with _LOCK:
        try:
            sm, aq = _ensure_session(diagnostics)
            lat = _finite_number(frame.get("lat")); lon = _finite_number(frame.get("lon"))
            alt = _finite_number(frame.get("altitude_ft")); pitch = _finite_number(frame.get("pitch_deg"))
            bank = _finite_number(frame.get("bank_deg")); heading = _finite_number(frame.get("heading_deg"))
            if None in (lat, lon, alt, pitch, bank, heading):
                raise ValueError("Replay frame does not contain a complete position and attitude pose")
            if initial:
                from SimConnect.Constants import SIMCONNECT_OBJECT_ID_USER  # type: ignore
                from SimConnect.Enum import SIMCONNECT_DATA_SET_FLAG  # type: ignore
                _REPLAY_OPTIONAL_LAST.clear()
                airspeed = max(0.0, _finite_number(frame.get("indicated_speed_kts")) or _finite_number(frame.get("ground_speed_kts")) or 0.0)
                init_pos = _ReplayInitPosition(
                    float(lat), float(lon), float(alt),
                    float(pitch), float(bank), float(heading),
                    1 if frame.get("on_ground") else 0, int(round(airspeed)),
                )
                definition = _ensure_replay_initial_definition(sm)
                hr = sm.dll.SetDataOnSimObject(
                    sm.hSimConnect, definition.value, SIMCONNECT_OBJECT_ID_USER,
                    SIMCONNECT_DATA_SET_FLAG(0), 0, sizeof(init_pos), byref(init_pos),
                )
                if not sm.IsHR(hr, 0):
                    raise RuntimeError(f"SimConnect rejected the initial replay position ({hr})")
            else:
                from SimConnect.Enum import SIMCONNECT_DATA_SET_FLAG  # type: ignore
                from SimConnect.Constants import SIMCONNECT_OBJECT_ID_USER  # type: ignore
                definition = _ensure_replay_pose_definition(sm)
                wrapped_heading = ((float(heading) % 360.0) + 360.0) % 360.0
                # Floor the pose against the sim terrain + recorded AGL so a
                # drifting MSL datum cannot write the aircraft below the ground
                # (clip / ground-collision takeover during landing replay).
                alt = _replay_clamped_altitude(frame, float(alt), sm, aq)
                vx = _finite_number(frame.get("body_velocity_x_fps"))
                vy = _finite_number(frame.get("body_velocity_y_fps"))
                vz = _finite_number(frame.get("body_velocity_z_fps"))
                if vx is None:
                    # Fenix-era recordings do not carry body velocities; derive
                    # forward speed from the recorded ground speed so the sim's
                    # velocity and flight instruments follow the replay.
                    gs_kts = _finite_number(frame.get("ground_speed_kts")) or 0.0
                    vx = gs_kts * 1.68781  # knots -> feet per second
                    vy = 0.0 if vy is None else float(vy)
                    vs_fpm = _finite_number(frame.get("vertical_speed_fpm"))
                    # Body Z is down-positive; climb (positive vs_fpm) is negative vz.
                    vz = (-float(vs_fpm) / 60.0) if vs_fpm is not None else 0.0
                else:
                    vy = 0.0 if vy is None else float(vy)
                    vz = 0.0 if vz is None else float(vz)
                pose = _ReplayPose(float(lat), float(lon), float(alt), float(pitch), float(bank), wrapped_heading, float(vx), float(vy), float(vz))
                hr = sm.dll.SetDataOnSimObject(
                    sm.hSimConnect, definition.value, SIMCONNECT_OBJECT_ID_USER,
                    SIMCONNECT_DATA_SET_FLAG(0), 0, sizeof(pose), byref(pose),
                )
                if not sm.IsHR(hr, 0):
                    raise RuntimeError(f"SimConnect rejected the atomic replay pose ({hr})")

            if apply_controls:
                # --- KEY EVENTS path (SkyDolly: TransmitClientEvent for primary surfaces) ---
                event_rejections: list[str] = []
                event_writes = 0
                event_candidates: list[tuple[str, int]] = []

                def add_event(name: str, scaled: int, threshold: int = 1) -> None:
                    prev = _REPLAY_OPTIONAL_LAST.get(name)
                    if prev is None or abs(int(prev) - scaled) >= threshold:
                        event_candidates.append((name, scaled))

                # Rudder, elevator, aileron: -1..1 → -16384..16384, sign negated (SkyDolly convention)
                v = _finite_number(frame.get("rudder_position"))
                if v is not None:
                    add_event("AXIS_RUDDER_SET", max(-16384, min(16384, int(round(-v * 16384)))), 50)
                v = _finite_number(frame.get("elevator_position"))
                if v is not None:
                    add_event("AXIS_ELEVATOR_SET", max(-16384, min(16384, int(round(-v * 16384)))), 50)
                v = _finite_number(frame.get("aileron_position"))
                if v is not None:
                    add_event("AXIS_AILERONS_SET", max(-16384, min(16384, int(round(-v * 16384)))), 50)

                # Spoilers: 0..1 → 0..16384
                v = _finite_number(frame.get("spoiler_percent"))
                if v is not None:
                    pct = float(v) / 100.0 if float(v) > 1.2 else float(v)
                    add_event("SPOILERS_SET", max(0, min(16384, int(round(pct * 16384)))), 50)

                # Flaps: integer index
                v = _finite_number(frame.get("flap_index"))
                if v is not None:
                    add_event("FLAPS_INDEX_SET", int(round(float(v))), 0)

                # Gear: GEAR_UP or GEAR_DOWN event
                v = _finite_number(frame.get("gear_percent"))
                if v is not None:
                    gear_event = "GEAR_DOWN" if float(v) >= 50.0 else "GEAR_UP"
                    gear_int = 1 if float(v) >= 50.0 else 0
                    prev = _REPLAY_OPTIONAL_LAST.get("GEAR_EVENT")
                    if prev is None or int(prev) != gear_int:
                        event_candidates.append((gear_event, 1))

                # Send KEY EVENTS
                for name, scaled in event_candidates:
                    try:
                        from SimConnect import AircraftEvents
                        ev = AircraftEvents(sm).find(name)
                        if ev is not None:
                            ev(scaled)
                            _REPLAY_OPTIONAL_LAST[name] = scaled
                            event_writes += 1
                        else:
                            event_rejections.append(name)
                    except Exception:
                        event_rejections.append(name)

                # --- aq.set path (throttle, engine combustion, gear) ---
                aq_rejections: list[str] = []
                aq_writes = 0

                def add(name: str, value: Any, transform=lambda x: x, threshold: float = 0.01, fallback_event: str | None = None) -> None:
                    n = _finite_number(value)
                    if n is None:
                        return
                    converted = float(transform(n))
                    previous = _REPLAY_OPTIONAL_LAST.get(name)
                    if previous is None or abs(float(previous) - converted) >= threshold:
                        try:
                            ok = aq.set(name, converted)
                            if ok is False:
                                raise RuntimeError("rejected")
                            _REPLAY_OPTIONAL_LAST[name] = converted
                            aq_writes += 1
                        except Exception:
                            if fallback_event:
                                try:
                                    from SimConnect import AircraftEvents
                                    ev = AircraftEvents(sm).find(fallback_event)
                                    if ev is not None:
                                        ev(max(0, min(16384, int(round(converted / 100.0 * 16384)))))
                                        _REPLAY_OPTIONAL_LAST[name] = converted
                                        aq_writes += 1
                                    else:
                                        aq_rejections.append(name)
                                except Exception:
                                    aq_rejections.append(name)
                            else:
                                aq_rejections.append(name)

                add("GENERAL_ENG_THROTTLE_LEVER_POSITION:1", frame.get("throttle_1_percent"), threshold=.2, fallback_event="KEY_THROTTLE_SET")
                add("GENERAL_ENG_THROTTLE_LEVER_POSITION:2", frame.get("throttle_2_percent"), threshold=.2, fallback_event="KEY_THROTTLE_SET")
                add("GEAR_HANDLE_POSITION", 1.0 if (v is not None and float(v) >= 50.0) else 0.0, threshold=.5)
                for index in range(1, 5):
                    add(f"GENERAL_ENG_COMBUSTION:{index}", 1.0 if frame.get(f"engine_{index}_running") else 0.0, threshold=.5)

            return {
                "ok": True, "pose_writes": 1,
                "event_writes": event_writes if apply_controls else 0,
                "event_rejections": event_rejections if apply_controls else [],
                "aq_writes": aq_writes if apply_controls else 0,
                "aq_rejections": aq_rejections if apply_controls else [],
                "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
                "atomic": not initial, "initial": bool(initial),
            }
        except Exception as exc:
            return {"ok": False, "reason": f"{type(exc).__name__}: {exc}", "latency_ms": round((time.perf_counter() - started) * 1000.0, 3)}

