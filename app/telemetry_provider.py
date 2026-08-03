from __future__ import annotations

"""Exclusive-source MSFS telemetry for OPS ROOM.

The recorder, Flight Watch and announcement triggers use exactly one core
telemetry source per app session: FSUIPC7 when it is present and complete,
otherwise SimConnect. Core flight fields are never mixed between providers.
This mirrors stable ACARS/PIREP clients: one coherent sample, one provider,
one timestamp.
"""

import importlib.util
import math
import os
import struct
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from statistics import median
from typing import Any

from .settings_store import load_settings
from .fsuipc_manager import autostart_if_configured, locate_fsuipc, close_fsuipc7
try:
    from .fsuipc_manager import _is_running as _fsuipc_process_running
except Exception:  # pragma: no cover
    def _fsuipc_process_running() -> bool:
        return False
from .simconnect_position import read_position, simconnect_diagnostics, _sanitize_telemetry

_MSFS_PROCESS_NAMES = ("FlightSimulator.exe", "FlightSimulator2024.exe", "MicrosoftFlightSimulator.exe")
_LAST_SIM_PROCESS_STATE: bool | None = None
_SIM_PROCESS_CHECK_AT = 0.0
_LAST_FSUIPC_AUTOCLOSE_AT = 0.0
_TELEMETRY_SETTINGS_CACHE: dict[str, Any] = {}
_TELEMETRY_SETTINGS_CACHE_AT = 0.0


def _sim_process_running() -> bool:
    """Return whether MSFS is running, with a short process-query cache."""
    global _LAST_SIM_PROCESS_STATE, _SIM_PROCESS_CHECK_AT
    if os.name != "nt":
        return True
    now = time.monotonic()
    if _LAST_SIM_PROCESS_STATE is not None and now - _SIM_PROCESS_CHECK_AT < 2.0:
        return bool(_LAST_SIM_PROCESS_STATE)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    running = False
    for name in _MSFS_PROCESS_NAMES:
        try:
            out = subprocess.check_output(["tasklist", "/FI", f"IMAGENAME eq {name}"], text=True, stderr=subprocess.DEVNULL, timeout=1.5, creationflags=flags)
            if name.lower() in out.lower():
                running = True
                break
        except Exception:
            continue
    _LAST_SIM_PROCESS_STATE = running
    _SIM_PROCESS_CHECK_AT = now
    return running


def _telemetry_settings() -> dict[str, Any]:
    """Avoid reading settings.json for every 5 Hz telemetry consumer."""
    global _TELEMETRY_SETTINGS_CACHE, _TELEMETRY_SETTINGS_CACHE_AT
    now = time.monotonic()
    if _TELEMETRY_SETTINGS_CACHE and now - _TELEMETRY_SETTINGS_CACHE_AT < 2.0:
        return _TELEMETRY_SETTINGS_CACHE
    _TELEMETRY_SETTINGS_CACHE = load_settings()
    _TELEMETRY_SETTINGS_CACHE_AT = now
    return _TELEMETRY_SETTINGS_CACHE


def _handle_sim_process_lost(settings: dict[str, Any]) -> dict[str, Any]:
    """Hard invalidation path used when FSUIPC7 is alive but MSFS is not."""
    global _CACHE, _CACHE_TIME, _SOURCE_LOCK, _SOURCE_LOCK_REASON, _LAST_SIM_PROCESS_STATE, _LAST_FSUIPC_AUTOCLOSE_AT
    _CACHE = None
    _CACHE_TIME = 0.0
    _SOURCE_LOCK = None
    _SOURCE_LOCK_REASON = "MSFS process not running; telemetry invalidated"
    _LAST_SIM_PROCESS_STATE = False
    integrations = settings.get("integrations", {}) if isinstance(settings.get("integrations"), dict) else {}
    if bool(integrations.get("fsuipc_auto_close_on_sim_close", False)):
        now = time.monotonic()
        if now - _LAST_FSUIPC_AUTOCLOSE_AT > 20.0:
            _LAST_FSUIPC_AUTOCLOSE_AT = now
            try:
                close_fsuipc7(force=bool(integrations.get("fsuipc_force_close_on_sim_close", False)))
            except Exception:
                pass
    return {
        "ok": False,
        "source": "unavailable",
        "telemetry_complete": False,
        "telemetry_valid": False,
        "sim_process_running": False,
        "reason": "MSFS process is not running; ignoring stale FSUIPC/SimConnect telemetry",
    }

_LOCK = threading.RLock()
_CACHE: dict[str, Any] | None = None
_CACHE_TIME = 0.0
_CACHE_SECONDS = 0.18
_FSUIPC_OPEN = False
_FSUIPC_LAST_ERROR = ""
_FSUIPC_LAST_OK = 0.0
_FSUIPC_RETRY_AFTER = 0.0
_FSUIPC_AUTOSTART_AFTER = 0.0
_FSUIPC_LAST_RAW_OFFSETS: dict[str, Any] = {}
_FSUIPC_LAST_REJECTED_SAMPLE: dict[str, Any] = {}
_FSUIPC_LAST_REJECTED_AT = 0.0
_SOURCE_LOCK: str | None = None
_SOURCE_LOCK_REASON = ""
_LAST_GOOD_BY_SOURCE: dict[str, dict[str, Any]] = {}
_LAST_GOOD_TIME_BY_SOURCE: dict[str, float] = {}
_FSUIPC_FINGERPRINT: tuple[Any, ...] | None = None
_FSUIPC_LAST_CHANGE = 0.0
_FSUIPC_STALE_SINCE = 0.0
_FSUIPC_RECOVERY_SINCE = 0.0
_FSUIPC_BACKGROUND_PROBE_AFTER = 0.0
_FSUIPC_RECOVERY_GOOD_SAMPLES = 0
_FSUIPC_LAST_BACKGROUND_PROBE_REASON = ""
_FSUIPC_BACKGROUND_PROBE_INTERVAL = 3.0
_FSUIPC_RECOVERY_HOLD_SECONDS = 8.0
_FSUIPC_IO_LOCK = threading.RLock()
_RECOVERY_THREAD: threading.Thread | None = None
_RECOVERY_STOP = threading.Event()
_RECOVERY_WAKE = threading.Event()
_SIM_HEARTBEAT: dict[str, Any] = {}
_SIM_HEARTBEAT_AT = 0.0
_SIM_HEARTBEAT_FINGERPRINT: tuple[Any, ...] | None = None
_SIM_HEARTBEAT_LAST_CHANGE = 0.0
_TELEMETRY_STALE_SECONDS = 30.0
_FAILOVER_ACTIVE = False
_FAILOVER_REASON = ""
_FILTER_HISTORY: dict[str, deque[dict[str, Any]]] = {}
_FILTER_LAST: dict[str, dict[str, Any]] = {}
_FILTER_LAST_AT: dict[str, float] = {}

_REQUIRED_FLIGHT_FIELDS = ("lat", "lon", "altitude_ft", "ground_speed_kts", "indicated_speed_kts", "on_ground")


def reset_source_lock(reason: str = "manual reset") -> None:
    """Allow the next telemetry read to choose FSUIPC7 or SimConnect again.

    This is used when a new recorder session starts, after reconnect, or by
    tests. It does not clear the FSUIPC connection itself.
    """
    global _SOURCE_LOCK, _SOURCE_LOCK_REASON, _CACHE, _CACHE_TIME, _FSUIPC_FINGERPRINT, _FSUIPC_LAST_CHANGE, _FSUIPC_STALE_SINCE, _FSUIPC_RECOVERY_SINCE, _FSUIPC_BACKGROUND_PROBE_AFTER, _FSUIPC_RECOVERY_GOOD_SAMPLES, _FSUIPC_LAST_BACKGROUND_PROBE_REASON, _FAILOVER_ACTIVE, _FAILOVER_REASON, _SIM_HEARTBEAT_FINGERPRINT, _SIM_HEARTBEAT_LAST_CHANGE, _FILTER_HISTORY, _FILTER_LAST, _FILTER_LAST_AT
    with _LOCK:
        _SOURCE_LOCK = None
        _SOURCE_LOCK_REASON = reason
        _CACHE = None
        _CACHE_TIME = 0.0
        _FSUIPC_FINGERPRINT = None
        _FSUIPC_LAST_CHANGE = 0.0
        _FSUIPC_STALE_SINCE = 0.0
        _FSUIPC_RECOVERY_SINCE = 0.0
        _FSUIPC_BACKGROUND_PROBE_AFTER = 0.0
        _FSUIPC_RECOVERY_GOOD_SAMPLES = 0
        _FSUIPC_LAST_BACKGROUND_PROBE_REASON = ""
        _SIM_HEARTBEAT_FINGERPRINT = None
        _SIM_HEARTBEAT_LAST_CHANGE = 0.0
        _FAILOVER_ACTIVE = False
        _FAILOVER_REASON = ""
        _FILTER_HISTORY.clear()
        _FILTER_LAST.clear()
        _FILTER_LAST_AT.clear()


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _fsuipc_ground_decision(*, raw_on_ground: bool, radio_altitude_ft: float | None, ground_speed_kts: float | None, indicated_speed_kts: float | None, parking_brake: bool | None = None) -> tuple[bool, bool, bool, list[str]]:
    """Return (on_ground, ground_safe, confirmed_airborne, warnings).

    FSUIPC offset 0x0366 is the simulator's raw SIM ON GROUND flag. It is
    useful, but it must not be the only proof used by OPS ROOM state machines.
    A single contradictory sample can occur during aircraft/loading/GSX state
    changes, so we cross-check it against documented FSUIPC speed and radio
    height offsets before recorder, RAAS and announcements consume it.
    """
    ra = 0.0 if radio_altitude_ft is None else float(radio_altitude_ft)
    gs = 0.0 if ground_speed_kts is None else float(ground_speed_kts)
    ias = 0.0 if indicated_speed_kts is None else float(indicated_speed_kts)
    warnings: list[str] = []
    on_ground = bool(raw_on_ground)

    # Ground-safe override: 0x0366 can briefly say airborne while parked or
    # while GSX/Fenix is manipulating state. With zero/near-zero radio height
    # and no motion, treating that as airborne corrupts recorder/RAAS.
    if not raw_on_ground and ((ra <= 12.0 and gs <= 8.0 and ias <= 45.0) or (parking_brake is True and gs <= 8.0 and ias <= 45.0)):
        on_ground = True
        warnings.append("FSUIPC 0x0366 reported airborne, but radio height/speed/brake state indicate aircraft is on ground")

    # Opposite contradiction: if 0x0366 is still ground while the aircraft is
    # clearly flying, let airborne consumers see a coherent state.
    if raw_on_ground and ra >= 100.0 and gs >= 70.0 and ias >= 60.0:
        on_ground = False
        warnings.append("FSUIPC 0x0366 reported on-ground, but radio height/speed indicate aircraft is airborne")

    ground_safe = bool(on_ground or (ra <= 15.0 and gs <= 10.0 and ias <= 45.0))
    confirmed_airborne = bool((not on_ground) and ra >= 30.0 and gs >= 55.0 and ias >= 45.0)
    return on_ground, ground_safe, confirmed_airborne, warnings


_PYUIPC_IMPORT_PATH = ""
_PYUIPC_IMPORT_ERROR = ""


def _pyuipc_search_paths() -> list[Path]:
    paths: list[Path] = []
    try:
        located = locate_fsuipc()
        if located:
            paths.append(located.parent)
    except Exception:
        pass
    settings = _telemetry_settings().get("integrations", {})
    user = str(settings.get("fsuipc_path") or "").strip()
    if user:
        paths.append(Path(user).expanduser().parent)
    for raw in (
        r"C:\FSUIPC7",
        r"C:\Program Files\FSUIPC7",
        r"C:\Program Files (x86)\FSUIPC7",
        str(Path.home() / "FSUIPC7"),
    ):
        paths.append(Path(raw))
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def _import_pyuipc() -> Any:
    """Import pyuipc, adding common FSUIPC7 install folders if needed.

    The Windows FSUIPC IPC bridge is a compiled extension named pyuipc. On some
    systems it is installed in the Python environment, on others it is placed near
    the FSUIPC7 installation. Running FSUIPC7.exe is not enough; OPS ROOM must be
    able to import pyuipc and open the IPC connection.
    """
    global _PYUIPC_IMPORT_PATH, _PYUIPC_IMPORT_ERROR
    try:
        import pyuipc  # type: ignore
        _PYUIPC_IMPORT_PATH = str(getattr(pyuipc, "__file__", "built-in"))
        _PYUIPC_IMPORT_ERROR = ""
        return pyuipc
    except Exception as first_exc:
        _PYUIPC_IMPORT_ERROR = f"{type(first_exc).__name__}: {first_exc}"
    for path in _pyuipc_search_paths():
        try:
            if path.is_dir() and str(path) not in sys.path:
                sys.path.insert(0, str(path))
            import pyuipc  # type: ignore
            _PYUIPC_IMPORT_PATH = str(getattr(pyuipc, "__file__", path))
            _PYUIPC_IMPORT_ERROR = ""
            return pyuipc
        except Exception as exc:
            _PYUIPC_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
            continue
    raise ImportError(_PYUIPC_IMPORT_ERROR or "pyuipc module not found")


def _pyuipc_available() -> bool:
    if importlib.util.find_spec("pyuipc") is not None:
        return True
    for path in _pyuipc_search_paths():
        try:
            if not path.is_dir():
                continue
            if list(path.glob("pyuipc*.pyd")) or list(path.glob("pyuipc*.py")):
                return True
        except OSError:
            continue
    return False


def _open_fsuipc(module: Any) -> None:
    global _FSUIPC_OPEN
    if _FSUIPC_OPEN:
        return
    module.open(getattr(module, "SIM_ANY", 0))
    _FSUIPC_OPEN = True


def _close_fsuipc(module: Any | None = None) -> None:
    global _FSUIPC_OPEN
    if module is not None and _FSUIPC_OPEN:
        try:
            module.close()
        except Exception:
            pass
    _FSUIPC_OPEN = False


def _fsuipc_rejected_sample(result: dict[str, Any], raw_offsets: dict[str, Any], now: float) -> dict[str, Any]:
    """Record a bad FSUIPC sample without killing the IPC provider.

    Earlier v0.24.x builds treated a single out-of-range value as provider death. In live
    testing FSUIPC7 and pyuipc were present, but one decoded sample was rejected
    before raw values were exposed. This path keeps the bridge open, stores the
    raw offsets, reports exact failed fields, and lets the source selector retry
    FSUIPC on the next sample while temporarily using SimConnect if needed.
    """
    global _FSUIPC_LAST_ERROR, _FSUIPC_LAST_REJECTED_SAMPLE, _FSUIPC_LAST_REJECTED_AT
    invalid_fields = list(result.get("telemetry_invalid_fields") or [])
    if not invalid_fields:
        for field in _REQUIRED_FLIGHT_FIELDS:
            value = result.get(field)
            if value is None:
                invalid_fields.append(field)
        lat = _num(result.get("lat")); lon = _num(result.get("lon"))
        if lat is not None and not (-90.0 <= lat <= 90.0) and "lat" not in invalid_fields:
            invalid_fields.append("lat")
        if lon is not None and not (-180.0 <= lon <= 180.0) and "lon" not in invalid_fields:
            invalid_fields.append("lon")
    raw_by_field = {
        "lat": {"0x0560_lat_raw": raw_offsets.get("0x0560_lat_raw")},
        "lon": {"0x0568_lon_raw": raw_offsets.get("0x0568_lon_raw")},
        "altitude_ft": {"0x3324_indicated_alt_raw": raw_offsets.get("0x3324_indicated_alt_raw"), "0x0570_plane_alt_raw": raw_offsets.get("0x0570_plane_alt_raw"), "0x6020_gps_alt_m": raw_offsets.get("0x6020_gps_alt_m")},
        "indicated_altitude_ft": {"0x3324_indicated_alt_raw": raw_offsets.get("0x3324_indicated_alt_raw")},
        "pressure_altitude_ft": {"0x0570_plane_alt_raw": raw_offsets.get("0x0570_plane_alt_raw"), "0x6020_gps_alt_m": raw_offsets.get("0x6020_gps_alt_m")},
        "agl_ft": {"0x31E4_radio_height_raw": raw_offsets.get("0x31E4_radio_height_raw")},
        "radio_altitude_ft": {"0x31E4_radio_height_raw": raw_offsets.get("0x31E4_radio_height_raw")},
        "ground_speed_kts": {"0x02B4_ground_speed_raw": raw_offsets.get("0x02B4_ground_speed_raw")},
        "indicated_speed_kts": {"0x02BC_ias_raw": raw_offsets.get("0x02BC_ias_raw")},
        "true_speed_kts": {"0x02B8_tas_raw": raw_offsets.get("0x02B8_tas_raw")},
        "mach": {"0x11C6_mach_raw": raw_offsets.get("0x11C6_mach_raw")},
        "vertical_speed_fpm": {"0x02C8_vertical_speed_raw": raw_offsets.get("0x02C8_vertical_speed_raw")},
        "heading_deg": {"0x0580_heading_raw": raw_offsets.get("0x0580_heading_raw")},
        "track_deg": {"0x0580_heading_raw": raw_offsets.get("0x0580_heading_raw")},
        "pitch_deg": {"0x0578_pitch_raw": raw_offsets.get("0x0578_pitch_raw")},
        "bank_deg": {"0x057C_bank_raw": raw_offsets.get("0x057C_bank_raw")},
        "sim_rate": {"0x0C1A_sim_rate_raw": raw_offsets.get("0x0C1A_sim_rate_raw")},
    }
    invalid_values = {
        field: {"decoded": result.get(field), "raw": raw_by_field.get(field, {})}
        for field in invalid_fields
    }
    detail = "FSUIPC sample rejected: " + (", ".join(invalid_fields[:8]) if invalid_fields else str(result.get("reason") or "outside valid limits"))
    rejected = dict(result)
    rejected.update({
        "ok": False,
        "source": "fsuipc7",
        "sample_rejected": True,
        "provider_dead": False,
        "reason": detail,
        "fsuipc_raw_offsets": dict(raw_offsets),
        "fsuipc_invalid_fields": invalid_fields,
        "fsuipc_invalid_values": invalid_values,
        "sampled_monotonic": now,
    })
    _FSUIPC_LAST_ERROR = detail
    _FSUIPC_LAST_REJECTED_SAMPLE = dict(rejected)
    _FSUIPC_LAST_REJECTED_AT = now
    return rejected


def _read_fsuipc_unlocked() -> dict[str, Any]:
    """Read a single FSUIPC7 core flight sample from documented offsets.

    The offsets used here are the same stable standard fields ACARS clients use:
    position, altitude, speed, vertical speed, heading, on-ground and total fuel.
    OPS ROOM does not fall back to SimConnect values inside this sample.
    """
    global _FSUIPC_LAST_ERROR, _FSUIPC_LAST_OK, _FSUIPC_RETRY_AFTER, _FSUIPC_LAST_RAW_OFFSETS
    now = time.monotonic()
    if now < _FSUIPC_RETRY_AFTER:
        return {"ok": False, "reason": _FSUIPC_LAST_ERROR or "FSUIPC retry back-off active", "source": "fsuipc7"}
    pyuipc = None
    try:
        pyuipc = _import_pyuipc()
        _open_fsuipc(pyuipc)
        requests = [
            (0x0560, "l"),  # latitude, signed 8-byte fixed point
            (0x0568, "l"),  # longitude, signed 8-byte fixed point
            (0x0570, "l"),  # PLANE ALTITUDE, signed 8-byte fixed point metres
            (0x3324, "d"),  # INDICATED ALTITUDE, signed 4-byte feet/metres per 0x0C18
            (0x0C18, "H"),  # user altitude unit flag, 2 = metres
            (0x6020, "F"),  # GPS POSITION ALT, FLOAT64 metres, diagnostic/fallback only
            (0x31E4, "d"),  # radio altitude, signed 4-byte metres * 65536
            (0x02B4, "d"),  # ground speed, signed 4-byte metres/second * 65536
            (0x02BC, "u"),  # IAS, unsigned 4-byte knots * 128
            (0x02B8, "u"),  # TAS, unsigned 4-byte knots * 128
            (0x11C6, "H"),  # Mach * 20480
            (0x02C8, "d"),  # vertical speed, signed 4-byte metres/second * 256
            (0x0580, "u"),  # true heading, unsigned 4-byte angle
            (0x0578, "d"),  # pitch, signed 4-byte angle
            (0x057C, "d"),  # bank, signed 4-byte angle
            (0x11BA, "h"),  # normal acceleration, approximately value / 625
            (0x126C, "u"),  # total fuel quantity weight, pounds
            (0x0E90, "H"),  # ambient wind speed, knots
            (0x0E92, "H"),  # ambient wind direction * 360 / 65536
            (0x0366, "H"),  # sim on ground, 0 airborne / 1 ground
            (0x0C1A, "H"),  # simulation rate * 256
            (0x0264, "H"),  # paused
            (0x05DC, "H"),  # slew active
            (0x04A8, "F"),  # elapsed simulated seconds, frame-updated; stops in pause/menu
            (0x0588, "F"),  # last LLAPBH update elapsed real seconds
            (0x3364, "b"),  # simulator loading/reloading indicator
            (0x3365, "b"),  # menu/dialogue state
            (0x0BC8, "H"),  # parking brake position, 0 off / high value on
            (0x0894, "H"),  # engine 1 combustion
            (0x092C, "H"),  # engine 2 combustion
            (0x07BC, "u"),  # autopilot master
            (0x07C4, "u"),  # autopilot NAV1 lock
            (0x07C8, "u"),  # autopilot heading lock
            (0x07CC, "H"),  # autopilot heading value degrees*65536/360
            (0x07D0, "u"),  # autopilot altitude lock
            (0x07D4, "d"),  # autopilot target altitude metres*65536
            (0x07DC, "u"),  # autopilot airspeed hold
            (0x07E2, "H"),  # autopilot airspeed hold var, knots
            (0x07E4, "u"),  # autopilot mach hold
            (0x07E8, "u"),  # autopilot mach hold var
            (0x07EC, "u"),  # autopilot vertical hold
            (0x07F2, "h"),  # autopilot vertical speed hold var
            (0x0810, "u"),  # autothrottle/throttle arm
            (0x2EE0, "u"),  # flight director active
            # FDR extended standard offsets documented by FSUIPC7.
            (0x088C, "h"),  # engine 1 throttle -4096..16384
            (0x0924, "h"),  # engine 2 throttle -4096..16384
            (0x0898, "H"),  # engine 1 N1, 16384=100%
            (0x0930, "H"),  # engine 2 N1, 16384=100%
            (0x0896, "H"),  # engine 1 N2, 16384=100%
            (0x092E, "H"),  # engine 2 N2, 16384=100%
            (0x08BE, "H"),  # engine 1 EGT, 16384=860C
            (0x0956, "H"),  # engine 2 EGT, 16384=860C
            (0x08A0, "H"),  # engine 1 corrected fuel flow, approx /128 PPH
            (0x0938, "H"),  # engine 2 corrected fuel flow, approx /128 PPH
            (0x0BB2, "h"),  # elevator -16383..16383
            (0x0BB6, "h"),  # aileron -16383..16383
            (0x0BBA, "h"),  # rudder -16383..16383
            (0x0BC4, "H"),  # left brake 0..32767
            (0x0BC6, "H"),  # right brake 0..32767
            (0x0BD0, "d"),  # spoiler handle 0..16383
            (0x0BE0, "d"),  # left trailing-edge flap 0..16383
            (0x0BEC, "d"),  # nose gear 0..16383
            (0x0BF0, "d"),  # right gear 0..16383
            (0x0BF4, "d"),  # left gear 0..16383
            (0x0BFC, "b"),  # flap handle index
            (0x0AEC, "H"),  # number of engines
            (0x09BC, "h"), (0x0A54, "h"),  # engine 3/4 throttle
            (0x09C8, "H"), (0x0A60, "H"),  # engine 3/4 N1
            (0x09C6, "H"), (0x0A5E, "H"),  # engine 3/4 N2
            (0x09EE, "H"), (0x0A86, "H"),  # engine 3/4 EGT
            (0x09D0, "H"), (0x0A68, "H"),  # engine 3/4 corrected fuel flow
            (0x09C4, "H"), (0x0A5C, "H"),  # engine 3/4 combustion
            (0x3328, "h"), (0x332A, "h"), (0x332C, "h"),  # post-cal elevator/aileron/rudder input
            (0x3330, "h"), (0x3332, "h"), (0x3334, "h"), (0x3336, "h"),  # post-cal throttle inputs
            (0x3412, "h"), (0x3414, "h"), (0x3416, "h"), (0x3418, "h"),  # spoiler/flap/brake axes
        ]
        values = pyuipc.read(requests)
        if not isinstance(values, (list, tuple)) or len(values) != len(requests):
            raise RuntimeError("FSUIPC returned an incomplete offset block")
        (
            lat_raw, lon_raw, plane_alt_raw, indicated_alt_raw, altitude_unit_raw, gps_altitude_m,
            radio_alt_raw, gs_raw, ias_raw, tas_raw, mach_raw, vs_raw,
            hdg_raw, pitch_raw, bank_raw, g_raw, fuel_lb_raw, wind_speed_raw,
            wind_dir_raw, ground_raw, rate_raw, pause_raw, slew_raw,
            sim_elapsed_raw, position_update_raw, loading_raw, menu_raw, parking_raw,
            eng1_raw, eng2_raw, ap_master_raw, ap_nav_raw, ap_hdg_lock_raw,
            ap_hdg_raw, ap_alt_lock_raw, ap_alt_raw, ap_spd_lock_raw, ap_spd_raw,
            ap_mach_lock_raw, ap_mach_raw, ap_vs_lock_raw, ap_vs_raw, ap_at_raw, ap_fd_raw,
            throttle1_raw, throttle2_raw, n1_1_raw, n1_2_raw, n2_1_raw, n2_2_raw,
            egt1_raw, egt2_raw, ff1_raw, ff2_raw, elevator_raw, aileron_raw, rudder_raw,
            brake_left_raw, brake_right_raw, spoiler_raw, flap_position_raw,
            gear_nose_raw, gear_right_raw, gear_left_raw, flap_index_raw,
            engine_count_raw, throttle3_raw, throttle4_raw, n1_3_raw, n1_4_raw, n2_3_raw, n2_4_raw,
            egt3_raw, egt4_raw, ff3_raw, ff4_raw, eng3_raw, eng4_raw,
            elevator_axis_raw, aileron_axis_raw, rudder_axis_raw,
            throttle1_axis_raw, throttle2_axis_raw, throttle3_axis_raw, throttle4_axis_raw,
            spoiler_axis_raw, flap_axis_raw, brake_left_axis_raw, brake_right_axis_raw,
        ) = values
        raw_offsets = {
            "0x0560_lat_raw": lat_raw,
            "0x0568_lon_raw": lon_raw,
            "0x0570_plane_alt_raw": plane_alt_raw,
            "0x3324_indicated_alt_raw": indicated_alt_raw,
            "0x0C18_altitude_unit_raw": altitude_unit_raw,
            "0x6020_gps_alt_m": gps_altitude_m,
            "0x31E4_radio_height_raw": radio_alt_raw,
            "0x02B4_ground_speed_raw": gs_raw,
            "0x02BC_ias_raw": ias_raw,
            "0x02B8_tas_raw": tas_raw,
            "0x11C6_mach_raw": mach_raw,
            "0x02C8_vertical_speed_raw": vs_raw,
            "0x0580_heading_raw": hdg_raw,
            "0x0578_pitch_raw": pitch_raw,
            "0x057C_bank_raw": bank_raw,
            "0x0366_sim_on_ground_raw": ground_raw,
            "0x0BC8_parking_brake_raw": parking_raw,
            "0x0C1A_sim_rate_raw": rate_raw,
            "0x0264_paused_raw": pause_raw,
            "0x05DC_slew_raw": slew_raw,
            "0x04A8_sim_elapsed_seconds": sim_elapsed_raw,
            "0x0588_position_update_seconds": position_update_raw,
            "0x3364_loading_raw": loading_raw,
            "0x3365_menu_raw": menu_raw,
            "0x07BC_ap_master_raw": ap_master_raw,
            "0x07C4_ap_nav_lock_raw": ap_nav_raw,
            "0x07C8_ap_heading_lock_raw": ap_hdg_lock_raw,
            "0x07CC_ap_heading_raw": ap_hdg_raw,
            "0x07D0_ap_alt_lock_raw": ap_alt_lock_raw,
            "0x07D4_ap_alt_raw": ap_alt_raw,
            "0x07DC_ap_speed_lock_raw": ap_spd_lock_raw,
            "0x07E2_ap_speed_raw": ap_spd_raw,
            "0x07E4_ap_mach_lock_raw": ap_mach_lock_raw,
            "0x07E8_ap_mach_raw": ap_mach_raw,
            "0x07EC_ap_vs_lock_raw": ap_vs_lock_raw,
            "0x07F2_ap_vs_raw": ap_vs_raw,
            "0x0810_autothrottle_raw": ap_at_raw,
            "0x2EE0_flight_director_raw": ap_fd_raw,
            "0x088C_throttle1_raw": throttle1_raw, "0x0924_throttle2_raw": throttle2_raw,
            "0x0898_n1_1_raw": n1_1_raw, "0x0930_n1_2_raw": n1_2_raw,
            "0x0896_n2_1_raw": n2_1_raw, "0x092E_n2_2_raw": n2_2_raw,
            "0x08BE_egt1_raw": egt1_raw, "0x0956_egt2_raw": egt2_raw,
            "0x08A0_ff1_raw": ff1_raw, "0x0938_ff2_raw": ff2_raw,
            "0x0BB2_elevator_raw": elevator_raw, "0x0BB6_aileron_raw": aileron_raw,
            "0x0BBA_rudder_raw": rudder_raw, "0x0BC4_brake_left_raw": brake_left_raw,
            "0x0BC6_brake_right_raw": brake_right_raw, "0x0BD0_spoiler_raw": spoiler_raw,
            "0x0BE0_flap_position_raw": flap_position_raw, "0x0BEC_gear_nose_raw": gear_nose_raw,
            "0x0BF0_gear_right_raw": gear_right_raw, "0x0BF4_gear_left_raw": gear_left_raw,
            "0x0BFC_flap_index_raw": flap_index_raw,
            "0x0AEC_engine_count_raw": engine_count_raw,
            "0x09BC_throttle3_raw": throttle3_raw, "0x0A54_throttle4_raw": throttle4_raw,
            "0x09C8_n1_3_raw": n1_3_raw, "0x0A60_n1_4_raw": n1_4_raw,
            "0x09C6_n2_3_raw": n2_3_raw, "0x0A5E_n2_4_raw": n2_4_raw,
            "0x09EE_egt3_raw": egt3_raw, "0x0A86_egt4_raw": egt4_raw,
            "0x09D0_ff3_raw": ff3_raw, "0x0A68_ff4_raw": ff4_raw,
            "0x3328_elevator_axis_raw": elevator_axis_raw, "0x332A_aileron_axis_raw": aileron_axis_raw,
            "0x332C_rudder_axis_raw": rudder_axis_raw, "0x3330_throttle1_axis_raw": throttle1_axis_raw,
            "0x3332_throttle2_axis_raw": throttle2_axis_raw, "0x3334_throttle3_axis_raw": throttle3_axis_raw,
            "0x3336_throttle4_axis_raw": throttle4_axis_raw, "0x3412_spoiler_axis_raw": spoiler_axis_raw,
            "0x3414_flap_axis_raw": flap_axis_raw, "0x3416_brake_left_axis_raw": brake_left_axis_raw,
            "0x3418_brake_right_axis_raw": brake_right_axis_raw,
        }
        _FSUIPC_LAST_RAW_OFFSETS = dict(raw_offsets)
        lat = float(lat_raw) * 90.0 / (10001750.0 * 65536.0 * 65536.0)
        lon = float(lon_raw) * 360.0 / (65536.0 ** 4)
        radio_altitude_ft = float(radio_alt_raw) / 65536.0 * 3.280839895
        ground_speed_kts = float(gs_raw) / 65536.0 * 1.943844492
        indicated_speed_kts = float(ias_raw) / 128.0
        true_speed_kts = float(tas_raw) / 128.0
        vertical_speed_fpm = float(vs_raw) / 256.0 * 196.850394
        heading_deg = (float(hdg_raw) * 360.0 / (65536.0 ** 2)) % 360.0
        parking_brake = int(parking_raw or 0) > 1000
        engine_count = max(1, min(4, int(engine_count_raw or 2)))
        engines_running = bool(int(eng1_raw or 0) or int(eng2_raw or 0) or int(eng3_raw or 0) or int(eng4_raw or 0))
        engine_1_running = bool(int(eng1_raw or 0)); engine_2_running = bool(int(eng2_raw or 0))
        engine_3_running = bool(int(eng3_raw or 0)); engine_4_running = bool(int(eng4_raw or 0))
        def pct_16384(value: Any) -> float:
            return max(0.0, min(130.0, float(value or 0) * 100.0 / 16384.0))
        engine_1_n1 = pct_16384(n1_1_raw); engine_2_n1 = pct_16384(n1_2_raw); engine_3_n1 = pct_16384(n1_3_raw); engine_4_n1 = pct_16384(n1_4_raw)
        engine_1_n2 = pct_16384(n2_1_raw); engine_2_n2 = pct_16384(n2_2_raw); engine_3_n2 = pct_16384(n2_3_raw); engine_4_n2 = pct_16384(n2_4_raw)
        engine_1_egt = max(0.0, float(egt1_raw or 0) * 860.0 / 16384.0); engine_2_egt = max(0.0, float(egt2_raw or 0) * 860.0 / 16384.0)
        engine_3_egt = max(0.0, float(egt3_raw or 0) * 860.0 / 16384.0); engine_4_egt = max(0.0, float(egt4_raw or 0) * 860.0 / 16384.0)
        engine_1_ff = max(0.0, float(ff1_raw or 0) / 128.0); engine_2_ff = max(0.0, float(ff2_raw or 0) / 128.0)
        engine_3_ff = max(0.0, float(ff3_raw or 0) / 128.0); engine_4_ff = max(0.0, float(ff4_raw or 0) / 128.0)
        # Some advanced aircraft do not mirror engine data into standard offsets.
        # Do not turn unsupported all-zero running-engine blocks into believable values.
        if engine_1_running and max(engine_1_n1, engine_1_n2, engine_1_egt, engine_1_ff) <= 0.01:
            engine_1_n1 = engine_1_n2 = engine_1_egt = engine_1_ff = None
        if engine_2_running and max(engine_2_n1, engine_2_n2, engine_2_egt, engine_2_ff) <= 0.01:
            engine_2_n1 = engine_2_n2 = engine_2_egt = engine_2_ff = None
        if engine_3_running and max(engine_3_n1, engine_3_n2, engine_3_egt, engine_3_ff) <= 0.01:
            engine_3_n1 = engine_3_n2 = engine_3_egt = engine_3_ff = None
        if engine_4_running and max(engine_4_n1, engine_4_n2, engine_4_egt, engine_4_ff) <= 0.01:
            engine_4_n1 = engine_4_n2 = engine_4_egt = engine_4_ff = None
        def axis_16384(value: Any) -> float | None:
            try:
                n=float(value)
                return max(-1.0,min(1.0,n/16384.0))
            except Exception:
                return None
        def axis_percent(value: Any, signed: bool=False) -> float | None:
            try:
                n=float(value)
                if signed: return max(-25.0,min(100.0,n*100.0/16384.0))
                return max(0.0,min(100.0,n*100.0/16384.0))
            except Exception:
                return None
        sim_on_ground_raw = int(ground_raw or 0)
        def _finite(v: Any) -> float | None:
            try:
                n = float(v)
                return n if n == n and abs(n) != float("inf") else None
            except Exception:
                return None
        plane_alt_ft = None
        try:
            plane_alt_ft = float(plane_alt_raw) / (65536.0 ** 2) * 3.280839895
        except Exception:
            pass
        indicated_alt_ft = _finite(indicated_alt_raw)
        if indicated_alt_ft is not None and int(altitude_unit_raw or 0) == 2:
            indicated_alt_ft *= 3.280839895
        gps_altitude_ft = None
        try:
            gps_altitude_ft = float(gps_altitude_m) * 3.280839895
        except Exception:
            pass
        airborne_like = bool(max(0.0, radio_altitude_ft) > 1000.0 and (ground_speed_kts > 100.0 or indicated_speed_kts > 100.0))
        altitude_candidates = []
        for source_name, value, confidence in (
            ("0x3324_indicated_altitude", indicated_alt_ft, "high"),
            ("0x0570_plane_altitude", plane_alt_ft, "high"),
            ("0x6020_gps_altitude", gps_altitude_ft, "diagnostic_fallback"),
        ):
            n = _finite(value)
            if n is None or not (-2000.0 <= n <= 100000.0):
                continue
            if airborne_like and (abs(n) < 500.0 or n + 1000.0 < max(0.0, radio_altitude_ft)):
                continue
            altitude_candidates.append((source_name, n, confidence))
        if altitude_candidates:
            altitude_source, altitude_ft, altitude_confidence = altitude_candidates[0]
            altitude_unreliable = False
        else:
            altitude_source, altitude_ft, altitude_confidence = "none", None, "invalid"
            altitude_unreliable = True
        validated_on_ground, ground_safe, confirmed_airborne, ground_warnings = _fsuipc_ground_decision(
            raw_on_ground=bool(sim_on_ground_raw),
            radio_altitude_ft=max(0.0, radio_altitude_ft),
            ground_speed_kts=ground_speed_kts,
            indicated_speed_kts=indicated_speed_kts,
            parking_brake=parking_brake,
        )
        ap_selected_alt_ft = (float(ap_alt_raw) / 65536.0 * 3.280839895) if ap_alt_raw is not None else None
        ap_selected_heading_deg = (float(ap_hdg_raw) * 360.0 / 65536.0) % 360.0 if ap_hdg_raw is not None else None
        ap_selected_speed_kts = float(ap_spd_raw) if ap_spd_raw is not None else None
        ap_selected_mach = (float(ap_mach_raw) / 65536.0) if ap_mach_raw is not None else None
        ap_selected_vs_fpm = float(ap_vs_raw) if ap_vs_raw is not None else None
        # Standard FSUIPC AP/FCU offsets are not complete for every complex
        # aircraft. Never present default zeroes as confirmed selected targets
        # while airborne, because that made Flight Watch look broken in Fenix.
        if airborne_like:
            if ap_selected_alt_ft is not None and ap_selected_alt_ft <= 100.0:
                ap_selected_alt_ft = None
            if not int(ap_hdg_lock_raw or 0) and ap_selected_heading_deg is not None and abs(ap_selected_heading_deg) < 0.01:
                ap_selected_heading_deg = None
            if not int(ap_spd_lock_raw or 0) and ap_selected_speed_kts is not None and ap_selected_speed_kts <= 1.0:
                ap_selected_speed_kts = None
            if not int(ap_mach_lock_raw or 0) and ap_selected_mach is not None and ap_selected_mach <= 0.001:
                ap_selected_mach = None
            if not int(ap_vs_lock_raw or 0) and ap_selected_vs_fpm is not None and abs(ap_selected_vs_fpm) < 1.0:
                ap_selected_vs_fpm = None
        result = {
            "ok": -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0,
            "lat": lat,
            "lon": lon,
            "altitude_ft": altitude_ft,
            "indicated_altitude_ft": indicated_alt_ft if not altitude_unreliable else None,
            "pressure_altitude_ft": altitude_ft,
            "altitude_source": altitude_source,
            "altitude_confidence": altitude_confidence,
            "altitude_unreliable": bool(altitude_unreliable),
            "altitude_candidates": {"0x3324_indicated_ft": indicated_alt_ft, "0x0570_plane_ft": plane_alt_ft, "0x6020_gps_ft": gps_altitude_ft},
            "agl_ft": max(0.0, radio_altitude_ft),
            "radio_altitude_ft": max(0.0, radio_altitude_ft),
            "ground_speed_kts": ground_speed_kts,
            "indicated_speed_kts": indicated_speed_kts,
            "true_speed_kts": true_speed_kts,
            "mach": float(mach_raw) / 20480.0,
            "vertical_speed_fpm": vertical_speed_fpm,
            "heading_deg": heading_deg,
            "track_deg": heading_deg,
            "pitch_deg": -float(pitch_raw) * 360.0 / (65536.0 ** 2),
            "bank_deg": -float(bank_raw) * 360.0 / (65536.0 ** 2),
            "g_force": float(g_raw) / 625.0,
            "fuel_total_lb": max(0.0, float(fuel_lb_raw)),
            "engine_count": engine_count,
            "fuel_flow_pph": sum(v for v in (engine_1_ff, engine_2_ff, engine_3_ff, engine_4_ff)[:engine_count] if v is not None) if any(v is not None for v in (engine_1_ff, engine_2_ff, engine_3_ff, engine_4_ff)[:engine_count]) else None,
            "engine_n1_percent": max([v for v in (engine_1_n1, engine_2_n1, engine_3_n1, engine_4_n1)[:engine_count] if v is not None], default=None),
            "engine_n2_percent": max([v for v in (engine_1_n2, engine_2_n2, engine_3_n2, engine_4_n2)[:engine_count] if v is not None], default=None),
            "engine_egt_c": max([v for v in (engine_1_egt, engine_2_egt, engine_3_egt, engine_4_egt)[:engine_count] if v is not None], default=None),
            "engine_1_n1_percent": engine_1_n1, "engine_2_n1_percent": engine_2_n1,
            "engine_1_n2_percent": engine_1_n2, "engine_2_n2_percent": engine_2_n2,
            "engine_1_egt_c": engine_1_egt, "engine_2_egt_c": engine_2_egt,
            "engine_1_fuel_flow_pph": engine_1_ff, "engine_2_fuel_flow_pph": engine_2_ff,
            "engine_3_n1_percent": engine_3_n1, "engine_4_n1_percent": engine_4_n1,
            "engine_3_n2_percent": engine_3_n2, "engine_4_n2_percent": engine_4_n2,
            "engine_3_egt_c": engine_3_egt, "engine_4_egt_c": engine_4_egt,
            "engine_3_fuel_flow_pph": engine_3_ff, "engine_4_fuel_flow_pph": engine_4_ff,
            # Standard engine lever offsets represent the simulator/aircraft
            # state. Post-calibration axis offsets are recorded separately as
            # pilot inputs; zero is a valid idle/neutral value and is never used
            # as a missing-data sentinel.
            "throttle_1_percent": axis_percent(throttle1_raw, signed=True),
            "throttle_2_percent": axis_percent(throttle2_raw, signed=True),
            "throttle_3_percent": axis_percent(throttle3_raw, signed=True),
            "throttle_4_percent": axis_percent(throttle4_raw, signed=True),
            "pilot_throttle_1_percent": axis_percent(throttle1_axis_raw, signed=True),
            "pilot_throttle_2_percent": axis_percent(throttle2_axis_raw, signed=True),
            "pilot_throttle_3_percent": axis_percent(throttle3_axis_raw, signed=True),
            "pilot_throttle_4_percent": axis_percent(throttle4_axis_raw, signed=True),
            "elevator_position": max(-1.0, min(1.0, float(elevator_raw or 0) / 16383.0)),
            "aileron_position": max(-1.0, min(1.0, float(aileron_raw or 0) / 16383.0)),
            "rudder_position": max(-1.0, min(1.0, float(rudder_raw or 0) / 16383.0)),
            "actual_elevator_percent": max(-100.0, min(100.0, float(elevator_raw or 0) * 100.0 / 16383.0)),
            "actual_aileron_percent": max(-100.0, min(100.0, float(aileron_raw or 0) * 100.0 / 16383.0)),
            "actual_rudder_percent": max(-100.0, min(100.0, float(rudder_raw or 0) * 100.0 / 16383.0)),
            "pilot_elevator_input": axis_16384(elevator_axis_raw),
            "pilot_aileron_input": axis_16384(aileron_axis_raw),
            "pilot_rudder_input": axis_16384(rudder_axis_raw),
            # First-officer sidestick axes flow through the recording schema unchanged. FSUIPC
            # exposes no generic per-seat FO stick (Live-validation checkpoint LVC5), so the
            # generic path leaves them None; only a validated per-seat adapter fills them.
            "pilot_aileron_input_fo": None,
            "pilot_elevator_input_fo": None,
            "brake_percent": max(max(float(brake_left_raw or 0), float(brake_right_raw or 0)) * 100.0 / 32767.0, axis_percent(brake_left_axis_raw) or 0.0, axis_percent(brake_right_axis_raw) or 0.0),
            "brake_left_percent": max(float(brake_left_raw or 0) * 100.0 / 32767.0, axis_percent(brake_left_axis_raw) or 0.0),
            "brake_right_percent": max(float(brake_right_raw or 0) * 100.0 / 32767.0, axis_percent(brake_right_axis_raw) or 0.0),
            "spoiler_percent": max(0.0, min(100.0, float(spoiler_raw or 0) * 100.0 / 16383.0)),
            "flap_handle_percent": axis_percent(flap_axis_raw),
            "flap_index": max(0, int(flap_index_raw or 0)),
            "gear_percent": max(0.0, min(100.0, max(float(gear_nose_raw or 0), float(gear_right_raw or 0), float(gear_left_raw or 0)) * 100.0 / 16383.0)),
            "wind_speed_kts": max(0.0, float(wind_speed_raw)),
            "wind_direction_deg": (float(wind_dir_raw) * 360.0 / 65536.0) % 360.0,
            "on_ground": bool(validated_on_ground),
            "sim_on_ground_raw": sim_on_ground_raw,
            "ground_safe": bool(ground_safe),
            "confirmed_airborne": bool(confirmed_airborne),
            "telemetry_warnings": ground_warnings,
            "fsuipc_raw_offsets": dict(raw_offsets),
            "sim_rate": max(0.0, float(rate_raw) / 256.0),
            "paused": bool(int(pause_raw)),
            "slew_active": bool(int(slew_raw)),
            "simulator_elapsed_seconds": _finite(sim_elapsed_raw),
            "aircraft_position_update_seconds": _finite(position_update_raw),
            "simulator_loading": bool(int(loading_raw or 0)),
            "simulator_menu_state": int(menu_raw or 0),
            # NOTE: FSUIPC7 exposes no reliable standard offset for APU RPM/running
            # state, so apu_running is intentionally NOT surfaced here (inventing an
            # offset would risk misreading an unrelated byte). The APU-start recording
            # trigger is fed by the generic SimConnect provider (APU PCT RPM / APU
            # switches) and by the aircraft adapter enrichment (e.g. Fenix apu_master).
            "systems": {"parking_brake": parking_brake, "engines_running": engines_running, "engine1_running": engine_1_running, "engine2_running": engine_2_running, "engine3_running": engine_3_running, "engine4_running": engine_4_running},
            "parking_brake": parking_brake,
            "engines_running": engines_running,
            "autopilot": {
                "master": bool(int(ap_master_raw or 0)),
                "engaged": bool(int(ap_master_raw or 0) or int(ap_nav_raw or 0) or int(ap_hdg_lock_raw or 0) or int(ap_alt_lock_raw or 0) or int(ap_spd_lock_raw or 0) or int(ap_mach_lock_raw or 0) or int(ap_vs_lock_raw or 0)),
                "flight_director": bool(int(ap_fd_raw or 0)),
                "autothrottle": bool(int(ap_at_raw or 0)),
                "selected_altitude_ft": ap_selected_alt_ft,
                "selected_heading_deg": ap_selected_heading_deg,
                "selected_speed_kts": ap_selected_speed_kts,
                "selected_mach": ap_selected_mach,
                "selected_vertical_speed_fpm": ap_selected_vs_fpm,
                "modes": [name for name, active in (("NAV", ap_nav_raw), ("HDG", ap_hdg_lock_raw), ("ALT", ap_alt_lock_raw), ("SPD", ap_spd_lock_raw), ("MACH", ap_mach_lock_raw), ("VS", ap_vs_lock_raw)) if bool(int(active or 0))],
                "source": "fsuipc_standard_offsets",
            },
            "provider_categories": {"core": "FSUIPC7", "controls": "FSUIPC7 STANDARD/AXIS OFFSETS", "engines": "FSUIPC7 STANDARD ENGINE OFFSETS", "systems": "FSUIPC7 STANDARD OFFSETS"},
            "source": "fsuipc7",
            "sampled_monotonic": now,
        }
        result = _sanitize_telemetry(result)
        if not result.get("ok") or result.get("telemetry_valid") is False:
            return _fsuipc_rejected_sample(result, raw_offsets, now)
        _FSUIPC_LAST_ERROR = ""
        _FSUIPC_LAST_OK = now
        return result
    except Exception as exc:
        _close_fsuipc(pyuipc)
        detail = f"{type(exc).__name__}: {exc}"
        if not _pyuipc_available():
            detail = "pyuipc bridge is not importable/bundled; install optional FSUIPC Python bridge or rebuild with requirements_fsuipc_optional.txt"
        _FSUIPC_LAST_ERROR = detail
        _FSUIPC_RETRY_AFTER = now + 5.0
        return {"ok": False, "reason": _FSUIPC_LAST_ERROR, "source": "fsuipc7"}

def _altitude_from(sample: dict[str, Any]) -> float | None:
    for key in ("altitude_ft", "indicated_altitude_ft", "pressure_altitude_ft"):
        value = _num(sample.get(key))
        if value is not None:
            return value
    return None



def _read_fsuipc() -> dict[str, Any]:
    """Serialize pyuipc open/read/close without holding the main telemetry lock."""
    with _FSUIPC_IO_LOCK:
        return _read_fsuipc_unlocked()

def _distance_nm(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    r = 3440.065
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = math.radians(b_lat - a_lat), math.radians(b_lon - a_lon)
    h = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * r * math.asin(min(1.0, math.sqrt(max(0.0, h))))


def _median_field(rows: list[dict[str, Any]], key: str, fallback: Any = None) -> Any:
    values = [_num(row.get(key)) for row in rows]
    clean = [value for value in values if value is not None]
    return median(clean) if clean else fallback


def _circular_mean(values: list[float], fallback: float | None = None) -> float | None:
    if not values:
        return fallback
    x = sum(math.cos(math.radians(value)) for value in values)
    y = sum(math.sin(math.radians(value)) for value in values)
    if abs(x) < 1e-9 and abs(y) < 1e-9:
        return fallback
    result = math.degrees(math.atan2(y, x)) % 360.0
    return 0.0 if abs(result - 360.0) < 1e-6 else result


def _recent_window(rows: list[dict[str, Any]], now: float, seconds: float, limit: int = 24) -> list[dict[str, Any]]:
    selected = [row for row in rows if now - float(row.get("_filter_time") or now) <= seconds]
    return selected[-limit:] or rows[-1:]


def _condition_sample(sample: dict[str, Any], source: str) -> dict[str, Any]:
    """Produce a stable operational sample for either telemetry provider.

    Filtering is time based, not frame-count based. Raw touchdown channels are
    preserved while phase, announcement and PIREP consumers receive validated
    values with stationary deadbands and physical rate limits.
    """
    result = dict(sample)
    raw_keys = (
        "lat", "lon", "altitude_ft", "indicated_altitude_ft", "agl_ft",
        "radio_altitude_ft", "ground_speed_kts", "indicated_speed_kts",
        "vertical_speed_fpm", "heading_deg", "track_deg", "pitch_deg",
        "bank_deg", "g_force",
    )
    for key in raw_keys:
        result[f"raw_{key}"] = sample.get(key)
    if not result.get("ok") or result.get("telemetry_hold"):
        return result

    now = _num(result.get("sampled_monotonic")) or time.monotonic()
    last = _FILTER_LAST.get(source)
    last_at = _FILTER_LAST_AT.get(source, 0.0)
    dt = max(0.05, now - last_at) if last and last_at else 0.0
    if dt > 5.0 or result.get("simulator_loading") or result.get("simulator_menu_state"):
        _FILTER_HISTORY.pop(source, None)
        last = None
        dt = 0.0

    notes: list[str] = []
    lat, lon = _num(result.get("lat")), _num(result.get("lon"))
    gs = max(0.0, _num(result.get("ground_speed_kts")) or 0.0)
    ias = max(0.0, _num(result.get("indicated_speed_kts")) or 0.0)
    on_ground = result.get("on_ground") is True

    if last and dt > 0.0:
        p_lat, p_lon = _num(last.get("lat")), _num(last.get("lon"))
        if lat is not None and lon is not None and p_lat is not None and p_lon is not None:
            delta = _distance_nm(p_lat, p_lon, lat, lon)
            previous_gs = max(0.0, _num(last.get("ground_speed_kts")) or 0.0)
            expected = max(gs, previous_gs) * dt / 3600.0
            if on_ground and gs < 1.2 and delta < 0.02:
                result["lat"], result["lon"] = p_lat, p_lon
                notes.append("stationary position held")
            elif delta > max(0.22, expected * 4.0 + 0.05):
                result["lat"], result["lon"] = p_lat, p_lon
                notes.append(f"position spike rejected ({delta:.2f} nm)")

        previous_alt = _num(last.get("altitude_ft"))
        current_alt = _num(result.get("altitude_ft"))
        vs = abs(_num(result.get("vertical_speed_fpm")) or 0.0)
        if current_alt is not None and previous_alt is not None:
            max_change = max(260.0, vs * dt / 60.0 * 2.5 + 180.0)
            if abs(current_alt - previous_alt) > max_change:
                result["altitude_ft"] = previous_alt
                result["indicated_altitude_ft"] = _num(last.get("indicated_altitude_ft")) or previous_alt
                notes.append("altitude spike rejected")
            elif on_ground and gs < 1.2 and abs(current_alt - previous_alt) < 25.0:
                result["altitude_ft"] = previous_alt
                result["indicated_altitude_ft"] = _num(last.get("indicated_altitude_ft")) or previous_alt

        previous_gs = max(0.0, _num(last.get("ground_speed_kts")) or 0.0)
        if abs(gs - previous_gs) > max(28.0, 12.0 + 18.0 * dt):
            result["ground_speed_kts"] = previous_gs
            gs = previous_gs
            notes.append("ground-speed spike rejected")
        previous_ias = max(0.0, _num(last.get("indicated_speed_kts")) or 0.0)
        if abs(ias - previous_ias) > max(24.0, 10.0 + 15.0 * dt):
            result["indicated_speed_kts"] = previous_ias
            ias = previous_ias
            notes.append("airspeed spike rejected")
        previous_vs = _num(last.get("vertical_speed_fpm")) or 0.0
        current_vs = _num(result.get("vertical_speed_fpm")) or 0.0
        if abs(current_vs - previous_vs) > max(2200.0, 1200.0 + 3500.0 * dt):
            result["vertical_speed_fpm"] = previous_vs
            notes.append("vertical-speed candidate held")
    history = _FILTER_HISTORY.setdefault(source, deque(maxlen=64))
    result["_filter_time"] = now
    history.append(dict(result))
    rows = list(history)
    short = _recent_window(rows, now, 0.75, 12)
    medium = _recent_window(rows, now, 1.4, 24)

    filtered_gs = float(_median_field(short, "ground_speed_kts", result.get("ground_speed_kts")) or 0.0)
    if on_ground or filtered_gs < 15.0:
        result["ground_speed_kts"] = 0.0 if filtered_gs < 0.9 else filtered_gs
    else:
        result["ground_speed_kts"] = filtered_gs

    raw_vs_values = [_num(row.get("raw_vertical_speed_fpm")) for row in medium]
    raw_vs_values = [value for value in raw_vs_values if value is not None]
    if len(raw_vs_values) < 3 and last and abs((raw_vs_values[-1] if raw_vs_values else 0.0) - (_num(last.get("vertical_speed_fpm")) or 0.0)) > 2200.0:
        filtered_vs = float(_num(last.get("vertical_speed_fpm")) or 0.0)
    else:
        filtered_vs = float(median(raw_vs_values) if raw_vs_values else (_num(result.get("vertical_speed_fpm")) or 0.0))
    result["vertical_speed_fpm"] = 0.0 if abs(filtered_vs) < 90.0 else filtered_vs
    for key in ("altitude_ft", "indicated_altitude_ft", "indicated_speed_kts", "pitch_deg", "bank_deg"):
        value = _median_field(short, key, result.get(key))
        if value is not None:
            result[key] = float(value)
    if (_num(result.get("radio_altitude_ft")) or 0.0) > 50.0:
        for key in ("radio_altitude_ft", "agl_ft"):
            value = _median_field(short, key, result.get(key))
            if value is not None:
                result[key] = max(0.0, float(value))

    heading_values = [_num(row.get("heading_deg")) for row in short]
    heading = _circular_mean([v for v in heading_values if v is not None], _num(result.get("heading_deg")))
    if heading is not None:
        result["heading_deg"] = heading
    track_values = [_num(row.get("track_deg")) for row in short]
    track = _circular_mean([v for v in track_values if v is not None], _num(result.get("track_deg")))
    if track is not None:
        result["track_deg"] = track

    result.pop("_filter_time", None)
    result["telemetry_conditioned"] = True
    result["telemetry_filter_notes"] = notes
    _FILTER_LAST[source] = dict(result)
    _FILTER_LAST_AT[source] = now
    return result

def _complete_snapshot(sample: dict[str, Any], source: str) -> tuple[bool, str]:
    if not sample.get("ok"):
        return False, str(sample.get("reason") or f"{source} not available")
    if sample.get("telemetry_valid") is False:
        return False, str(sample.get("reason") or f"{source} telemetry outside valid limits")
    lat = _num(sample.get("lat")); lon = _num(sample.get("lon"))
    if lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return False, f"{source} missing valid aircraft position"
    if abs(lat) < 0.001 and abs(lon) < 0.001:
        return False, f"{source} reported loading-screen/default position"
    altitude = _altitude_from(sample)
    if sample.get("altitude_unreliable") or str(sample.get("altitude_confidence") or "").lower() == "invalid":
        return False, f"{source} altitude source unreliable ({sample.get('altitude_source') or 'unknown'})"
    if altitude is None or not (-2000 <= altitude <= 100000):
        return False, f"{source} missing valid altitude"
    gs = _num(sample.get("ground_speed_kts")); ias = _num(sample.get("indicated_speed_kts"))
    if gs is None or gs < 0 or gs > 900:
        return False, f"{source} missing valid ground speed"
    if ias is None or ias < 0 or ias > 800:
        return False, f"{source} missing valid indicated speed"
    if not isinstance(sample.get("on_ground"), bool):
        return False, f"{source} missing on-ground state"
    sampled = _num(sample.get("sampled_monotonic"))
    if sampled is not None and time.monotonic() - sampled > _TELEMETRY_STALE_SECONDS:
        return False, f"{source} telemetry sample stale"
    return True, ""


def _mark_complete(sample: dict[str, Any], source: str) -> dict[str, Any]:
    result = dict(sample)
    result["ok"] = True
    result["source"] = source
    result["telemetry_complete"] = True
    result["telemetry_valid"] = True
    result["telemetry_mode"] = f"{source}-only"
    result["sim_process_running"] = _sim_process_running()
    result.setdefault("sampled_monotonic", time.monotonic())
    result = _condition_sample(result, source)
    _LAST_GOOD_BY_SOURCE[source] = dict(result)
    _LAST_GOOD_TIME_BY_SOURCE[source] = time.monotonic()
    return result


def _stale_result(source: str, reason: str) -> dict[str, Any]:
    sample = _LAST_GOOD_BY_SOURCE.get(source)
    age = time.monotonic() - _LAST_GOOD_TIME_BY_SOURCE.get(source, 0.0)
    if sample and age <= _TELEMETRY_STALE_SECONDS:
        # A short provider hiccup is not a frozen simulator. Preserve the last
        # coherent sample for display, but flag it as held so the recorder does
        # not insert duplicate points or advance flight/announcement gates.
        held = dict(sample)
        held.update({
            "stale": False,
            "ok": True,
            "telemetry_complete": True,
            "telemetry_fresh": True,
            "telemetry_hold": True,
            "provider_degraded": True,
            "data_age_seconds": round(age, 1),
            "reason": f"Brief {source} interruption; holding last coherent sample: {reason}",
        })
        return held
    return {"ok": False, "source": source, "telemetry_complete": False, "telemetry_valid": False, "telemetry_fresh": False, "stale": True, "reason": reason}


def _maybe_autostart_fsuipc(enabled: bool) -> None:
    global _FSUIPC_AUTOSTART_AFTER
    if not enabled:
        return
    now = time.monotonic()
    if now < _FSUIPC_AUTOSTART_AFTER:
        return
    _FSUIPC_AUTOSTART_AFTER = now + 45.0
    try:
        autostart_if_configured()
    except Exception:
        pass


def _read_simconnect() -> dict[str, Any]:
    sim = read_position(force=False)
    if sim.get("ok"):
        sim = _sanitize_telemetry(dict(sim))
        sim["source"] = "simconnect"
        sim.setdefault("sampled_monotonic", time.monotonic())
    return sim


def _fingerprint(sample: dict[str, Any]) -> tuple[Any, ...]:
    def rounded(key: str, digits: int) -> Any:
        value = _num(sample.get(key))
        return round(value, digits) if value is not None else None
    # FSUIPC 0x04A8 is the strongest freshness signal: simulated elapsed
    # seconds advances frame-by-frame and stops in pause/menu. Coarse flight
    # values are retained as fallback without allowing tiny numeric jitter to
    # masquerade as a fresh simulator.
    return (
        rounded("simulator_elapsed_seconds", 1),
        rounded("aircraft_position_update_seconds", 1),
        rounded("lat", 4), rounded("lon", 4), rounded("altitude_ft", -1),
        rounded("ground_speed_kts", 0), rounded("indicated_speed_kts", 0),
        bool(sample.get("on_ground")) if isinstance(sample.get("on_ground"), bool) else None,
        rounded("vertical_speed_fpm", -2), rounded("heading_deg", 0),
        bool(sample.get("simulator_loading")), int(sample.get("simulator_menu_state") or 0),
    )


def _airborne_or_moving(sample: dict[str, Any]) -> bool:
    return bool(sample.get("on_ground") is False or (_num(sample.get("ground_speed_kts")) or 0.0) >= 25.0 or (_num(sample.get("indicated_speed_kts")) or 0.0) >= 55.0 or (_num(sample.get("radio_altitude_ft")) or 0.0) >= 80.0)


def _sim_heartbeat(now: float, force: bool = False) -> dict[str, Any]:
    global _SIM_HEARTBEAT, _SIM_HEARTBEAT_AT, _SIM_HEARTBEAT_FINGERPRINT, _SIM_HEARTBEAT_LAST_CHANGE
    if not force and _SIM_HEARTBEAT and now - _SIM_HEARTBEAT_AT < 0.8:
        return dict(_SIM_HEARTBEAT)
    sample = _read_simconnect()
    valid, _reason = _complete_snapshot(sample, "simconnect")
    if valid:
        fp = _fingerprint(sample)
        if _SIM_HEARTBEAT_FINGERPRINT is None or fp != _SIM_HEARTBEAT_FINGERPRINT:
            _SIM_HEARTBEAT_FINGERPRINT = fp
            _SIM_HEARTBEAT_LAST_CHANGE = now
        _SIM_HEARTBEAT = dict(sample)
        _SIM_HEARTBEAT["data_unchanged_seconds"] = round(max(0.0, now - (_SIM_HEARTBEAT_LAST_CHANGE or now)), 1)
    else:
        _SIM_HEARTBEAT = {}
    _SIM_HEARTBEAT_AT = now
    return dict(_SIM_HEARTBEAT)


def _contradicts(fsuipc: dict[str, Any], sim: dict[str, Any]) -> bool:
    if not sim:
        return False
    f_alt, s_alt = _altitude_from(fsuipc), _altitude_from(sim)
    f_gs, s_gs = _num(fsuipc.get("ground_speed_kts")) or 0.0, _num(sim.get("ground_speed_kts")) or 0.0
    if fsuipc.get("on_ground") is True and sim.get("on_ground") is False and s_gs >= 55.0:
        return True
    if f_alt is not None and s_alt is not None and abs(s_alt - f_alt) >= 500.0 and s_gs >= 40.0:
        return True
    if abs(s_gs - f_gs) >= 45.0 and max(s_gs, f_gs) >= 55.0:
        return True
    return False


def _assess_fsuipc_freshness(sample: dict[str, Any], now: float) -> tuple[bool, float, dict[str, Any], bool]:
    global _FSUIPC_FINGERPRINT, _FSUIPC_LAST_CHANGE, _FSUIPC_STALE_SINCE
    systems = sample.get("systems") if isinstance(sample.get("systems"), dict) else {}
    paused = bool(
        sample.get("paused") or sample.get("active_pause") or systems.get("paused") or systems.get("active_pause")
        or sample.get("simulator_loading") or int(sample.get("simulator_menu_state") or 0)
    )
    fp = _fingerprint(sample)
    if _FSUIPC_FINGERPRINT is None or fp != _FSUIPC_FINGERPRINT:
        _FSUIPC_FINGERPRINT = fp
        _FSUIPC_LAST_CHANGE = now
        _FSUIPC_STALE_SINCE = 0.0
        return True, 0.0, {}, False
    unchanged = max(0.0, now - (_FSUIPC_LAST_CHANGE or now))
    if paused:
        return True, unchanged, {}, False
    heartbeat = _sim_heartbeat(now, force=unchanged >= 5.0) if unchanged >= 5.0 else {}
    expected_motion = _airborne_or_moving(sample) or _airborne_or_moving(_LAST_GOOD_BY_SOURCE.get("fsuipc7") or {}) or _airborne_or_moving(heartbeat)
    contradiction = _contradicts(sample, heartbeat)
    sim_unchanged = float(heartbeat.get("data_unchanged_seconds") or 0.0) if heartbeat else 0.0
    # The SimConnect heartbeat may begin a few seconds after FSUIPC stops
    # advancing.  Compare its unchanged age with the same freeze window instead
    # of demanding a second full 30-second wait.
    heartbeat_tracks_same_stall = bool(
        heartbeat
        and not contradiction
        and sim_unchanged >= max(5.0, unchanged - 8.0)
    )
    simulator_stalled = bool(
        expected_motion
        and unchanged >= _TELEMETRY_STALE_SECONDS
        and (not heartbeat or heartbeat_tracks_same_stall)
        and not contradiction
    )
    stale = bool(expected_motion and unchanged >= _TELEMETRY_STALE_SECONDS)
    if stale and not _FSUIPC_STALE_SINCE:
        _FSUIPC_STALE_SINCE = now
    return not stale, unchanged, heartbeat, simulator_stalled



def _probe_preferred_fsuipc(sim_sample: dict[str, Any], now: float, *, force: bool = False) -> dict[str, Any] | None:
    """Probe and restore preferred FSUIPC while SimConnect remains active.

    Startup fallback and runtime failover use the same recovery path. A single
    successful open is not enough: require several coherent fresh samples over
    a short hold period, then switch atomically without touching recorder state.
    """
    global _SOURCE_LOCK, _SOURCE_LOCK_REASON, _FAILOVER_ACTIVE, _FAILOVER_REASON
    global _FSUIPC_RECOVERY_SINCE, _FSUIPC_BACKGROUND_PROBE_AFTER
    global _FSUIPC_RECOVERY_GOOD_SAMPLES, _FSUIPC_LAST_BACKGROUND_PROBE_REASON

    if not force and now < _FSUIPC_BACKGROUND_PROBE_AFTER:
        return None
    _FSUIPC_BACKGROUND_PROBE_AFTER = now + _FSUIPC_BACKGROUND_PROBE_INTERVAL
    fsuipc = _read_fsuipc()
    valid, reason = _complete_snapshot(fsuipc, "fsuipc7")
    if not valid:
        _FSUIPC_RECOVERY_SINCE = 0.0
        _FSUIPC_RECOVERY_GOOD_SAMPLES = 0
        _FSUIPC_LAST_BACKGROUND_PROBE_REASON = reason
        return None

    fresh, _unchanged, heartbeat, simulator_stalled = _assess_fsuipc_freshness(fsuipc, now)
    comparison = heartbeat or sim_sample
    if simulator_stalled or not fresh or _contradicts(fsuipc, comparison):
        _FSUIPC_RECOVERY_SINCE = 0.0
        _FSUIPC_RECOVERY_GOOD_SAMPLES = 0
        _FSUIPC_LAST_BACKGROUND_PROBE_REASON = (
            "FSUIPC sample is not yet fresh/coherent with SimConnect"
        )
        return None

    if not _FSUIPC_RECOVERY_SINCE:
        _FSUIPC_RECOVERY_SINCE = now
        _FSUIPC_RECOVERY_GOOD_SAMPLES = 1
    else:
        _FSUIPC_RECOVERY_GOOD_SAMPLES += 1
    stable_seconds = max(0.0, now - _FSUIPC_RECOVERY_SINCE)
    _FSUIPC_LAST_BACKGROUND_PROBE_REASON = (
        f"FSUIPC recovery candidate {_FSUIPC_RECOVERY_GOOD_SAMPLES} samples / {stable_seconds:.1f}s"
    )
    if stable_seconds < _FSUIPC_RECOVERY_HOLD_SECONDS or _FSUIPC_RECOVERY_GOOD_SAMPLES < 3:
        return None

    _SOURCE_LOCK = "fsuipc7"
    _SOURCE_LOCK_REASON = "FSUIPC7 fresh and stable; preferred source restored"
    _FAILOVER_ACTIVE = False
    _FAILOVER_REASON = ""
    _FSUIPC_RECOVERY_SINCE = 0.0
    _FSUIPC_RECOVERY_GOOD_SAMPLES = 0
    _FSUIPC_LAST_BACKGROUND_PROBE_REASON = "FSUIPC7 restored"
    # Rebase only the destination provider's conditioning window. Recorder,
    # fuel and phase state are preserved by their owning modules.
    _FILTER_HISTORY.pop("fsuipc7", None)
    _FILTER_LAST.pop("fsuipc7", None)
    _FILTER_LAST_AT.pop("fsuipc7", None)
    result = _mark_complete(fsuipc, "fsuipc7")
    result.update({
        "telemetry_fresh": True,
        "source_recovered": True,
        "previous_source": "simconnect",
        "telemetry_gap": True,
    })
    return result



def _fsuipc_recovery_loop() -> None:
    """Recover preferred FSUIPC away from all user-facing telemetry requests."""
    global _CACHE, _CACHE_TIME, _FSUIPC_LAST_BACKGROUND_PROBE_REASON
    while not _RECOVERY_STOP.is_set():
        _RECOVERY_WAKE.wait(_FSUIPC_BACKGROUND_PROBE_INTERVAL)
        _RECOVERY_WAKE.clear()
        if _RECOVERY_STOP.is_set():
            break
        try:
            settings = _telemetry_settings()
            enabled = bool(settings.get("integrations", {}).get("fsuipc_enabled", True))
            with _LOCK:
                source = _SOURCE_LOCK
                sim = dict(_CACHE or {}) if (_CACHE or {}).get("source") == "simconnect" else {}
            if not enabled or source != "simconnect":
                continue
            recovered = _probe_preferred_fsuipc(sim, time.monotonic(), force=True)
            if recovered is not None:
                recovered = _enrich_addon_telemetry(recovered)
                with _LOCK:
                    _CACHE = dict(recovered)
                    _CACHE_TIME = time.monotonic()
        except Exception as exc:
            _FSUIPC_LAST_BACKGROUND_PROBE_REASON = f"FSUIPC recovery waiting: {type(exc).__name__}: {exc}"


def start_telemetry_engine() -> None:
    global _RECOVERY_THREAD
    with _LOCK:
        if _RECOVERY_THREAD and _RECOVERY_THREAD.is_alive():
            return
        _RECOVERY_STOP.clear()
        _RECOVERY_THREAD = threading.Thread(target=_fsuipc_recovery_loop, name="OpsRoom-TelemetryRecovery", daemon=True)
        _RECOVERY_THREAD.start()


def shutdown_telemetry_engine() -> None:
    _RECOVERY_STOP.set()
    _RECOVERY_WAKE.set()

def reselect_telemetry(reason: str = "manual telemetry reselection") -> dict[str, Any]:
    """Re-test FSUIPC first without blocking normal module telemetry reads."""
    global _FSUIPC_RETRY_AFTER, _FSUIPC_BACKGROUND_PROBE_AFTER
    global _FSUIPC_RECOVERY_SINCE, _FSUIPC_RECOVERY_GOOD_SAMPLES
    global _SOURCE_LOCK, _SOURCE_LOCK_REASON, _CACHE, _CACHE_TIME, _FSUIPC_LAST_BACKGROUND_PROBE_REASON
    try:
        _close_fsuipc(_import_pyuipc())
    except Exception:
        _close_fsuipc()
    _FSUIPC_RETRY_AFTER = 0.0
    _FSUIPC_BACKGROUND_PROBE_AFTER = 0.0
    _FSUIPC_RECOVERY_SINCE = 0.0
    _FSUIPC_RECOVERY_GOOD_SAMPLES = 0
    reset_source_lock(reason)
    settings = _telemetry_settings()
    if bool(settings.get("integrations", {}).get("fsuipc_enabled", True)):
        fsuipc = _read_fsuipc()
        valid, detail = _complete_snapshot(fsuipc, "fsuipc7")
        if valid:
            with _LOCK:
                _SOURCE_LOCK = "fsuipc7"
                _SOURCE_LOCK_REASON = "FSUIPC7 selected by telemetry reselection"
                result = _mark_complete(fsuipc, "fsuipc7")
                result["telemetry_fresh"] = True
                result = _enrich_addon_telemetry(result)
                _CACHE = dict(result)
                _CACHE_TIME = time.monotonic()
                return result
        _FSUIPC_LAST_BACKGROUND_PROBE_REASON = detail
    # Keep the current SimConnect stream responsive; the background worker will
    # continue controlled FSUIPC retries without a second blocking attempt here.
    sim = _sim_heartbeat(time.monotonic(), force=False)
    valid, detail = _complete_snapshot(sim, "simconnect")
    if valid:
        with _LOCK:
            _SOURCE_LOCK = "simconnect"
            _SOURCE_LOCK_REASON = "FSUIPC7 unavailable during reselection; SimConnect retained"
            result = _mark_complete(sim, "simconnect")
            result.update({"telemetry_fresh": True, "fsuipc_unavailable_reason": _FSUIPC_LAST_BACKGROUND_PROBE_REASON or None})
            result = _enrich_addon_telemetry(result)
            _CACHE = dict(result)
            _CACHE_TIME = time.monotonic()
        _RECOVERY_WAKE.set()
        return result
    _RECOVERY_WAKE.set()
    return {"ok": False, "source": "unavailable", "telemetry_complete": False, "telemetry_valid": False, "telemetry_fresh": False, "reason": detail}

_ADDON_OFFSET_CACHE_KEY: tuple[tuple[int, str], ...] = ()
_ADDON_OFFSET_CACHE_VALUES: list[Any] = []
_ADDON_OFFSET_CACHE_AT = 0.0


def _read_addon_offsets(requests: list[tuple[int, str]]) -> list[Any]:
    """Read the compact OPS ROOM LVar-to-offset block through pyuipc.

    This never scans or logs the simulator's full LVar catalogue. Only the
    currently active aircraft adapter's curated offsets are requested.

    The FSUIPC WASM mirrors each LVar into its offset as a 4-byte float32
    (size code ``F``, FSUIPC7 "Adding Lvars to Offsets" guide). The bundled
    pyuipc build reads format letter ``f`` as an 8-byte double, which swallows
    the neighbouring offset and yields denormal garbage. We therefore read the
    raw 32-bit word (``u``) and reinterpret the bit pattern as float32.
    """
    global _ADDON_OFFSET_CACHE_KEY, _ADDON_OFFSET_CACHE_VALUES, _ADDON_OFFSET_CACHE_AT
    key = tuple((int(offset), str(fmt)) for offset, fmt in requests)
    now = time.monotonic()
    if key == _ADDON_OFFSET_CACHE_KEY and now - _ADDON_OFFSET_CACHE_AT < 0.2:
        return list(_ADDON_OFFSET_CACHE_VALUES)
    if not key:
        return []
    # pyuipc 'f' = 8-byte double in the bundled build; the WASM LVar block is
    # 4-byte float32. Read raw u32 and reinterpret the bits as float32.
    read_key = tuple((offset, "u" if fmt == "f" else fmt) for offset, fmt in key)
    with _FSUIPC_IO_LOCK:
        pyuipc = _import_pyuipc()
        _open_fsuipc(pyuipc)
        values = pyuipc.read(list(read_key))
    if not isinstance(values, (list, tuple)) or len(values) != len(read_key):
        raise RuntimeError("FSUIPC returned an incomplete aircraft-adapter offset block")
    values = list(values)
    for i, (_, fmt) in enumerate(key):
        if fmt == "f":
            try:
                raw = int(values[i]) & 0xFFFFFFFF
                values[i] = struct.unpack("<f", struct.pack("<I", raw))[0]
            except Exception:
                values[i] = None
    _ADDON_OFFSET_CACHE_KEY = key
    _ADDON_OFFSET_CACHE_VALUES = list(values)
    _ADDON_OFFSET_CACHE_AT = now
    return list(values)


_SIMCONNECT_LVAR_SESSION: Any = None
_SIMCONNECT_LVAR_REQUESTS: dict[str, Any] = {}

def _read_simconnect_lvars(requests: list[tuple[str, str]]) -> list[Any]:
    """Read L:Vars directly through SimConnect, bypassing FSUIPC WASM offsets.

    Uses the same SimConnect session as the GSX remote LVar reader. Each
    ``(lvar_name, format)`` tuple is read via ``SimConnect.RequestList.Request``
    which supports MSFS L:Var names as byte-string tokens. Requests are cached
    per session to avoid recreating SimConnect client data areas on every call.
    """
    global _SIMCONNECT_LVAR_SESSION, _SIMCONNECT_LVAR_REQUESTS
    if not requests:
        return []
    from .simconnect_position import _ensure_session, simconnect_diagnostics, _note_session_read_result
    try:
        diagnostics = simconnect_diagnostics()
        sm, _aq = _ensure_session(diagnostics)
    except Exception:
        _note_session_read_result(False)
        return []
    if sm is None:
        return []
    if id(sm) != _SIMCONNECT_LVAR_SESSION:
        _SIMCONNECT_LVAR_REQUESTS.clear()
        _SIMCONNECT_LVAR_SESSION = id(sm)
    from SimConnect.RequestList import Request  # type: ignore
    values: list[Any] = []
    for lvar, fmt in requests:
        try:
            # v0.25.59: "f"/"float" are not valid SimConnect units tokens. Passing
            # them makes AddToDataDefinition fail and every L:Var read raise
            # SIMCONNECT_EXCEPTION_UNRECOGNIZED_ID (log flood + no data).
            # Normalise to the correct generic float units token defensively.
            units = (fmt or "Number").strip()
            if units.lower() in ("f", "float"):
                units = "Number"
            req = _SIMCONNECT_LVAR_REQUESTS.get(lvar)
            if req is None:
                sm_name = f"L:{lvar}" if not lvar.startswith("L:") else lvar
                req = Request((sm_name.encode("ascii"), units.encode("ascii")), sm, _time=100, _settable=True, _attemps=3)
                _SIMCONNECT_LVAR_REQUESTS[lvar] = req
            raw = req.value
            values.append(None if raw is None else float(raw))
        except Exception:
            values.append(None)
    # v0.25.60: session self-heal — every L:Var read coming back None (broken
    # SimConnect dispatch thread) counts as a session failure so the shared
    # session is rebuilt instead of serving a dead connection forever.
    if requests:
        if any(v is not None for v in values):
            _note_session_read_result(True)
        else:
            _note_session_read_result(False)
    return values


def _enrich_addon_telemetry(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict) or not result.get("ok"):
        return result
    try:
        from .addon_telemetry import enrich_telemetry
        return enrich_telemetry(result, _read_addon_offsets, _read_simconnect_lvars)
    except Exception as exc:
        enriched = dict(result)
        enriched["adapter_status"] = {
            "active": False, "mode": "GENERIC FALLBACK",
            "reason": f"Aircraft adapter enrichment failed: {type(exc).__name__}: {exc}",
        }
        return enriched


def read_telemetry(force: bool = False, stream: str = "full") -> dict[str, Any]:
    """Return one telemetry snapshot.

    ``stream='minimal'`` returns a slim snapshot that only queries the SimVars
    essential for the Black Box record loop and in-sim replay (lat/lon,
    altitude, attitude, ground-speeds, engine-running flags, parking brake,
    basic surface config).  All other telemetry consumers should keep the
    default ``stream='full'`` so the full pleasant detail panel does not
    regress.
    """
    global _CACHE, _CACHE_TIME, _SOURCE_LOCK, _SOURCE_LOCK_REASON, _FAILOVER_ACTIVE, _FAILOVER_REASON, _FSUIPC_RECOVERY_SINCE
    if stream == "minimal":
        from .simconnect_position import read_position_minimal
        result = read_position_minimal(force=force)
        if not isinstance(result, dict):
            return {"ok": False, "telemetry_complete": False, "telemetry_fresh": False, "source": "simconnect-minimal", "minimal": True}
        result.setdefault("addon_state", {})
        result.setdefault("addon_event_meta", {})
        result.setdefault("adapter_status", {"active": False, "mode": "GENERIC FALLBACK", "reason": "minimal stream skips adapter enrichment"})
        result["telemetry_complete"] = bool(result.get("ok"))
        result["telemetry_fresh"] = bool(result.get("ok"))
        result["minimal"] = True
        return result
    now = time.monotonic()
    with _LOCK:
        if not force and _CACHE is not None and now - _CACHE_TIME < _CACHE_SECONDS:
            return dict(_CACHE)
        settings = _telemetry_settings()
        if not _sim_process_running():
            result = _handle_sim_process_lost(settings)
            result = _enrich_addon_telemetry(result); _CACHE = dict(result); _CACHE_TIME = time.monotonic(); return result
        fsuipc_enabled = bool(settings.get("integrations", {}).get("fsuipc_enabled", True))
        _maybe_autostart_fsuipc(fsuipc_enabled)

        if _SOURCE_LOCK == "fsuipc7":
            fsuipc = _read_fsuipc()
            valid, reason = _complete_snapshot(fsuipc, "fsuipc7")
            if valid:
                fresh, unchanged, heartbeat, simulator_stalled = _assess_fsuipc_freshness(fsuipc, now)
                if fresh:
                    result = _mark_complete(fsuipc, "fsuipc7")
                    result.update({"telemetry_fresh": True, "provider_connected": True, "data_unchanged_seconds": round(unchanged, 1)})
                else:
                    sim = heartbeat or _sim_heartbeat(now, force=force)
                    sim_valid, sim_reason = _complete_snapshot(sim, "simconnect")
                    if simulator_stalled:
                        result = {"ok": False, "source": "simulator", "telemetry_complete": False, "telemetry_valid": False, "telemetry_fresh": False, "provider_connected": True, "stale": True, "simulator_stalled": True, "reason": f"MSFS simulator data has not advanced for {unchanged:.1f}s; recording and automation are paused until fresh data returns", "telemetry_gap": True}
                    elif sim_valid:
                        _SOURCE_LOCK = "simconnect"
                        _FAILOVER_ACTIVE = True
                        _FAILOVER_REASON = f"FSUIPC7 data frozen for {unchanged:.1f}s while SimConnect remained fresh"
                        _SOURCE_LOCK_REASON = _FAILOVER_REASON
                        result = _mark_complete(sim, "simconnect")
                        result.update({"telemetry_mode": "simconnect-fallback", "telemetry_fresh": True, "failover_active": True, "failover_reason": _FAILOVER_REASON, "fsuipc_connected": True, "fsuipc_data_stale": True, "telemetry_gap": True})
                    else:
                        result = {"ok": False, "source": "simulator", "telemetry_complete": False, "telemetry_valid": False, "telemetry_fresh": False, "provider_connected": True, "stale": True, "simulator_stalled": True, "reason": f"MSFS/telemetry data has not advanced for {unchanged:.1f}s; SimConnect did not return a fresh heartbeat ({sim_reason})", "telemetry_gap": True}
            else:
                sim = _sim_heartbeat(now, force=force)
                sim_valid, sim_reason = _complete_snapshot(sim, "simconnect")
                if sim_valid:
                    _SOURCE_LOCK = "simconnect"; _FAILOVER_ACTIVE = True; _FAILOVER_REASON = reason
                    result = _mark_complete(sim, "simconnect")
                    result.update({"telemetry_mode": "simconnect-fallback", "failover_active": True, "failover_reason": reason, "telemetry_gap": True})
                else:
                    result = _stale_result("fsuipc7", f"{reason}; SimConnect: {sim_reason}")
            result = _enrich_addon_telemetry(result); _CACHE = dict(result); _CACHE_TIME = time.monotonic(); return result

        if _SOURCE_LOCK == "simconnect":
            # Don't force-read SimConnect on recording-loop cycles. The 0.8s
            # _sim_heartbeat cache avoids ~300+ individual SimVar requests/sec
            # through the Python wrapper which causes MSFS stutter.
            sim = _sim_heartbeat(now, force=force)
            valid, reason = _complete_snapshot(sim, "simconnect")
            sim_unchanged = float(sim.get("data_unchanged_seconds") or 0.0) if valid else 0.0
            sim_frozen = bool(valid and _airborne_or_moving(sim) and sim_unchanged >= _TELEMETRY_STALE_SECONDS)
            if valid and not sim_frozen:
                result = _mark_complete(sim, "simconnect")
                result.update({"telemetry_fresh": True, "data_unchanged_seconds": round(sim_unchanged, 1)})
            elif sim_frozen:
                result = {
                    "ok": False, "source": "simulator", "telemetry_complete": False,
                    "telemetry_valid": False, "telemetry_fresh": False,
                    "provider_connected": True, "stale": True, "simulator_stalled": True,
                    "reason": f"MSFS/SimConnect data has not advanced for {sim_unchanged:.1f}s; recording and automation are paused until fresh data returns",
                    "telemetry_gap": True,
                }
            else:
                result = _stale_result("simconnect", reason)
            # Preferred-source recovery runs in OpsRoom-TelemetryRecovery and
            # never blocks Flight Watch, Announcer, RAAS or browser requests.
            if fsuipc_enabled:
                result.update({
                    "failover_active": _FAILOVER_ACTIVE,
                    "failover_reason": _FAILOVER_REASON or None,
                    "fsuipc_connected": bool(_FSUIPC_OPEN),
                    "fsuipc_data_stale": bool(_FAILOVER_ACTIVE),
                })
            result = _enrich_addon_telemetry(result); _CACHE = dict(result); _CACHE_TIME = time.monotonic(); return result

        fsuipc = _read_fsuipc() if fsuipc_enabled else {"ok": False, "reason": "FSUIPC preference disabled", "source": "fsuipc7"}
        valid, reason = _complete_snapshot(fsuipc, "fsuipc7")
        if valid:
            _SOURCE_LOCK = "fsuipc7"; _SOURCE_LOCK_REASON = "FSUIPC7 detected with complete flight sample"
            _assess_fsuipc_freshness(fsuipc, now)
            result = _mark_complete(fsuipc, "fsuipc7"); result["telemetry_fresh"] = True
            result = _enrich_addon_telemetry(result); _CACHE = dict(result); _CACHE_TIME = time.monotonic(); return result
        sim = _read_simconnect()
        sim_valid, sim_reason = _complete_snapshot(sim, "simconnect")
        if sim_valid:
            _SOURCE_LOCK = "simconnect"; _SOURCE_LOCK_REASON = "FSUIPC7 unavailable; SimConnect complete flight sample detected"
            result = _mark_complete(sim, "simconnect"); result.update({"telemetry_fresh": True, "fsuipc_unavailable_reason": reason})
            result = _enrich_addon_telemetry(result); _CACHE = dict(result); _CACHE_TIME = time.monotonic(); return result
        result = {"ok": False, "source": "unavailable", "telemetry_complete": False, "telemetry_valid": False, "telemetry_fresh": False, "reason": f"No complete aircraft telemetry sample. FSUIPC7: {reason}; SimConnect: {sim_reason}"}
        result = _enrich_addon_telemetry(result); _CACHE = dict(result); _CACHE_TIME = time.monotonic(); return result

def telemetry_diagnostics(probe: bool = False) -> dict[str, Any]:
    settings = _telemetry_settings()
    enabled = bool(settings.get("integrations", {}).get("fsuipc_enabled", True))
    if probe:
        _RECOVERY_WAKE.set()
    sample = read_telemetry(force=False) if probe else (_CACHE or {})
    return {
        "preference": "FSUIPC7 ONLY WHEN AVAILABLE, OTHERWISE SIMCONNECT ONLY" if enabled else "SIMCONNECT ONLY",
        "active_source": sample.get("source") or _SOURCE_LOCK or "not sampled",
        "source_lock": _SOURCE_LOCK,
        "source_lock_reason": _SOURCE_LOCK_REASON or None,
        "failover_active": _FAILOVER_ACTIVE,
        "failover_reason": _FAILOVER_REASON or None,
        "fsuipc_data_last_change_age_seconds": round(max(0.0, time.monotonic() - _FSUIPC_LAST_CHANGE), 1) if _FSUIPC_LAST_CHANGE else None,
        "fsuipc_data_stale": bool(_FSUIPC_STALE_SINCE),
        "fsuipc_recovery_pending": bool(_SOURCE_LOCK == "simconnect" and _FSUIPC_RECOVERY_SINCE),
        "fsuipc_recovery_good_samples": int(_FSUIPC_RECOVERY_GOOD_SAMPLES),
        "fsuipc_recovery_status": _FSUIPC_LAST_BACKGROUND_PROBE_REASON or None,
        "sim_process_running": _sim_process_running(),
        "fsuipc": {
            "enabled": enabled,
            "process_running": _fsuipc_process_running(),
            "python_bridge_available": _pyuipc_available(),
            "python_bridge_path": _PYUIPC_IMPORT_PATH or None,
            "python_bridge_import_error": _PYUIPC_IMPORT_ERROR or None,
            "candidate_paths": [str(x) for x in _pyuipc_search_paths()],
            "connected": bool(_FSUIPC_OPEN and _FSUIPC_LAST_OK),
            "ipc_open": bool(_FSUIPC_OPEN),
            "last_error": _FSUIPC_LAST_ERROR or None,
            "last_success_age_seconds": round(max(0.0, time.monotonic() - _FSUIPC_LAST_OK), 1) if _FSUIPC_LAST_OK else None,
            "sample_rejected": bool(_FSUIPC_LAST_REJECTED_SAMPLE and _FSUIPC_LAST_REJECTED_AT >= _FSUIPC_LAST_OK),
            "last_rejected_sample_age_seconds": round(max(0.0, time.monotonic() - _FSUIPC_LAST_REJECTED_AT), 1) if _FSUIPC_LAST_REJECTED_AT else None,
            "last_rejected_fields": _FSUIPC_LAST_REJECTED_SAMPLE.get("fsuipc_invalid_fields") if _FSUIPC_LAST_REJECTED_SAMPLE else None,
            "last_rejected_values": _FSUIPC_LAST_REJECTED_SAMPLE.get("fsuipc_invalid_values") if _FSUIPC_LAST_REJECTED_SAMPLE else None,
            "last_rejected_reason": _FSUIPC_LAST_REJECTED_SAMPLE.get("reason") if _FSUIPC_LAST_REJECTED_SAMPLE else None,
            "raw_offsets": _FSUIPC_LAST_RAW_OFFSETS or (sample.get("fsuipc_raw_offsets") if isinstance(sample, dict) else None),
            "altitude": {
                "source": sample.get("altitude_source") if isinstance(sample, dict) else None,
                "confidence": sample.get("altitude_confidence") if isinstance(sample, dict) else None,
                "unreliable": sample.get("altitude_unreliable") if isinstance(sample, dict) else None,
                "candidates": sample.get("altitude_candidates") if isinstance(sample, dict) else None,
            },
            "ground_decision": {
                "sim_on_ground_raw": (_FSUIPC_LAST_RAW_OFFSETS or {}).get("0x0366_sim_on_ground_raw") if _FSUIPC_LAST_RAW_OFFSETS else (sample.get("sim_on_ground_raw") if isinstance(sample, dict) else None),
                "on_ground": sample.get("on_ground") if isinstance(sample, dict) else None,
                "ground_safe": sample.get("ground_safe") if isinstance(sample, dict) else None,
                "confirmed_airborne": sample.get("confirmed_airborne") if isinstance(sample, dict) else None,
                "warnings": sample.get("telemetry_warnings") if isinstance(sample, dict) else None,
            },
        },
        "simconnect": simconnect_diagnostics(),
    }
