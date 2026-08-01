from __future__ import annotations

"""Read-only PMDG 777 SDK data broadcast client.

The PMDG data block is consumed through the official SimConnect Client Data
channel.  OPS ROOM requests the documented 684-byte data structure and parses
only a compact set of stable fields used by Flight Watch and Black Box.
"""

import ctypes
from ctypes import c_uint32, c_void_p, Structure
import os
import struct
import threading
import time
from typing import Any

PMDG_DATA_NAME = b"PMDG_777X_Data"
PMDG_DATA_ID = 0x504D4447
PMDG_DATA_DEFINITION = 0x504D4448
REQUEST_ID = 0x4F527770
PMDG_DATA_SIZE = 684
SIMCONNECT_CLIENT_DATA_PERIOD_ON_SET = 1
SIMCONNECT_CLIENT_DATA_REQUEST_FLAG_CHANGED = 1
SIMCONNECT_RECV_ID_CLIENT_DATA = 16

_LOCK = threading.RLock()
_STOP = threading.Event()
_THREAD: threading.Thread | None = None
_LAST_RAW: bytes | None = None
_LAST_SNAPSHOT: dict[str, Any] = {}
_LAST_RECEIVED = 0.0
_LAST_ERROR = ""
_CONNECTED = False
_DLL_PATH = ""


def _eula_accepted() -> bool:
    try:
        from .pmdg777_eula import accepted
        return bool(accepted())
    except Exception:
        return False


class SimRecv(Structure):
    _fields_ = [("dwSize", c_uint32), ("dwVersion", c_uint32), ("dwID", c_uint32)]


class SimRecvClientData(Structure):
    _fields_ = [
        ("dwSize", c_uint32), ("dwVersion", c_uint32), ("dwID", c_uint32),
        ("dwRequestID", c_uint32), ("dwObjectID", c_uint32), ("dwDefineID", c_uint32), ("dwFlags", c_uint32),
        ("dwentrynumber", c_uint32), ("dwoutof", c_uint32), ("dwDefineCount", c_uint32),
        ("dwData", c_uint32 * 1),
    ]


CALLBACK = ctypes.WINFUNCTYPE(None, ctypes.POINTER(SimRecv), c_uint32, c_void_p) if os.name == "nt" else None


def _u8(raw: bytes, offset: int) -> int:
    return raw[offset] if 0 <= offset < len(raw) else 0


def _bool(raw: bytes, offset: int) -> bool:
    return bool(_u8(raw, offset))


def _u16(raw: bytes, offset: int) -> int:
    return struct.unpack_from("<H", raw, offset)[0] if offset + 2 <= len(raw) else 0


def _i16(raw: bytes, offset: int) -> int:
    return struct.unpack_from("<h", raw, offset)[0] if offset + 2 <= len(raw) else 0


def _f32(raw: bytes, offset: int) -> float:
    return float(struct.unpack_from("<f", raw, offset)[0]) if offset + 4 <= len(raw) else 0.0


def _bools(raw: bytes, offset: int, count: int) -> list[bool]:
    return [_bool(raw, offset + index) for index in range(count)]


def _u8s(raw: bytes, offset: int, count: int) -> list[int]:
    return [_u8(raw, offset + index) for index in range(count)]


def _text(raw: bytes, offset: int, size: int) -> str:
    return raw[offset:offset + size].split(b"\0", 1)[0].decode("ascii", "ignore").strip()


def _decode(raw: bytes) -> dict[str, Any]:
    ap_annun = _bools(raw, 356, 2)
    doors = _u8s(raw, 467, 16)
    checklist = _bools(raw, 588, 10)
    model_labels = {1:"777-200",2:"777-200ER",3:"777-300",4:"777-200LR",5:"777F",6:"777-300ER"}
    autobrake_labels = {0:"RTO",1:"OFF",2:"DISARM",3:"1",4:"2",5:"3",6:"4",7:"MAX AUTO"}
    seatbelt_labels = {0:"OFF",1:"AUTO",2:"ON"}
    door_labels = {0:"OPEN",1:"CLOSED",2:"CLOSED/ARMED",3:"CLOSING",4:"OPENING"}
    flap_labels = {0:"UP",1:"1",2:"5",3:"15",4:"20",5:"25",6:"30"}
    speedbrake_raw = _u8(raw, 420)
    speedbrake_pct = 0.0 if speedbrake_raw <= 25 else min(100.0, (speedbrake_raw - 25.0) * 100.0 / 75.0)
    ap_modes = [name for name, active in (
        ("LNAV", _bool(raw,359)), ("VNAV",_bool(raw,360)), ("FLCH",_bool(raw,361)),
        ("HDG HOLD",_bool(raw,362)), ("VS/FPA",_bool(raw,363)), ("ALT HOLD",_bool(raw,364)),
        ("LOC",_bool(raw,365)), ("APP",_bool(raw,366)),
    ) if active]
    systems = {
        "battery_master": _bool(raw,37),
        "apu_selector": _u8(raw,41),
        "apu_generator": _bool(raw,40),
        "apu_running": _bool(raw,586),
        "external_power_switches": _bools(raw,47,2),
        "external_power_on": _bools(raw,49,2),
        "hyd_primary_engine_pumps": _bools(raw,82,2),
        "hyd_demand_electric_pumps": _u8s(raw,86,2),
        "seatbelt_selector": _u8(raw,99),
        "seatbelt_label": seatbelt_labels.get(_u8(raw,99), str(_u8(raw,99))),
        "landing_lights": _bools(raw,109,3),
        "beacon_light": _bool(raw,112),
        "taxi_light": _bool(raw,118),
        "strobe_light": _bool(raw,119),
        "engine_start_selectors": _u8s(raw,140,2),
        "fuel_pumps_forward": _bools(raw,148,2),
        "fuel_pumps_aft": _bools(raw,150,2),
        "fuel_pumps_center": _bools(raw,152,2),
        "gear_lever": _u8(raw,212),
        "autobrake_selector": _u8(raw,222),
        "autobrake_label": autobrake_labels.get(_u8(raw,222), str(_u8(raw,222))),
        "master_warning": any(_bools(raw,389,2)),
        "master_caution": any(_bools(raw,391,2)),
        "engine_fuel_controls_run": _bools(raw,422,2),
        "parking_brake": _bool(raw,424),
        "doors": [{"index": index, "state": state, "label": door_labels.get(state,str(state))} for index,state in enumerate(doors)],
        "cockpit_door_open": _bool(raw,483),
        "engine_start_valves": _bools(raw,484,2),
        "duct_pressure_psi": [_f32(raw,488), _f32(raw,492)],
        "irs_aligned": _bool(raw,512),
    }
    autopilot = {
        "engaged": any(ap_annun), "ap1": ap_annun[0], "ap2": ap_annun[1],
        "flight_director": any(_bools(raw,325,2)),
        "autothrottle": _bool(raw,358),
        "selected_speed_kts": _f32(raw,308) if _f32(raw,308) >= 10.0 else None,
        "selected_mach": _f32(raw,308) if 0.0 < _f32(raw,308) < 10.0 else None,
        "selected_heading_deg": _u16(raw,314),
        "selected_altitude_ft": _u16(raw,316),
        "selected_vertical_speed_fpm": _i16(raw,318),
        "modes": ap_modes,
    }
    addon_state = {
        "battery": systems["battery_master"], "apu_selector": systems["apu_selector"], "apu_running": systems["apu_running"],
        "external_power_1": systems["external_power_on"][0], "external_power_2": systems["external_power_on"][1],
        "seatbelt_selector": systems["seatbelt_selector"], "beacon": systems["beacon_light"], "taxi_light": systems["taxi_light"],
        "strobe": systems["strobe_light"], "gear_handle": systems["gear_lever"], "autobrake": systems["autobrake_selector"],
        "master_warning": systems["master_warning"], "master_caution": systems["master_caution"],
        "flap_handle": _u8(raw,421), "speedbrake_handle": speedbrake_raw,
        "engine_1_master": systems["engine_fuel_controls_run"][0], "engine_2_master": systems["engine_fuel_controls_run"][1],
        "parking_brake": systems["parking_brake"], "ap1": ap_annun[0], "ap2": ap_annun[1], "autothrottle": _bool(raw,358),
        "lnav": _bool(raw,359), "vnav": _bool(raw,360), "flch": _bool(raw,361), "loc": _bool(raw,365), "app": _bool(raw,366),
        "mcp_speed": _f32(raw,308), "mcp_heading": _u16(raw,314), "mcp_altitude": _u16(raw,316), "mcp_vs": _i16(raw,318),
        "door_1l": doors[0], "door_1r": doors[1], "cargo_fwd": doors[10], "cargo_aft": doors[11],
    }
    pulse_state = {
        "ap1_button": _bool(raw,338), "ap2_button": _bool(raw,339), "lnav_button": _bool(raw,342), "vnav_button": _bool(raw,343),
        "flch_button": _bool(raw,344), "loc_button": _bool(raw,348), "app_button": _bool(raw,349),
    }
    return {
        "ok": True, "source": "PMDG 777 SDK", "received_monotonic": time.monotonic(),
        "aircraft_model": model_labels.get(_u8(raw,542), f"MODEL {_u8(raw,542)}"),
        "systems": systems, "autopilot": autopilot, "addon_state": addon_state, "addon_pulses": pulse_state,
        "controls": {
            "flap_index": _u8(raw,421), "flap_label": flap_labels.get(_u8(raw,421), str(_u8(raw,421))),
            "spoiler_percent": speedbrake_pct, "spoilers_armed": speedbrake_raw == 25,
            "parking_brake": systems["parking_brake"], "gear_handle": systems["gear_lever"],
        },
        "flight_management": {
            "flight_number": _text(raw,576,9), "v1": _u8(raw,547), "vr": _u8(raw,548), "v2": _u8(raw,549),
            "takeoff_flaps": _u8(raw,546), "landing_flaps": _u8(raw,556), "landing_vref": _u8(raw,557),
            "cruise_altitude_ft": _u16(raw,558), "distance_to_tod_nm": _f32(raw,568), "distance_to_destination_nm": _f32(raw,572),
            "checklists_complete": checklist,
        },
    }


def _candidate_dll_paths() -> list[str]:
    try:
        from .simconnect_position import _candidate_library_paths
        return [str(path) for path in _candidate_library_paths() if path.is_file()]
    except Exception:
        return []


def _bind(dll: Any, name: str) -> Any:
    fn = getattr(dll, f"SimConnect_{name}", None) or getattr(dll, name, None)
    if fn is None:
        raise AttributeError(f"SimConnect_{name} export not found")
    return fn


def _run() -> None:
    global _LAST_RAW, _LAST_SNAPSHOT, _LAST_RECEIVED, _LAST_ERROR, _CONNECTED, _DLL_PATH
    if os.name != "nt" or CALLBACK is None:
        with _LOCK: _LAST_ERROR = "PMDG SDK reader is Windows-only"
        return
    while not _STOP.is_set():
        h = c_void_p()
        try:
            paths = _candidate_dll_paths()
            if not paths:
                raise FileNotFoundError("SimConnect.dll was not found")
            _DLL_PATH = paths[0]
            dll = ctypes.WinDLL(_DLL_PATH)
            Open = _bind(dll,"Open"); Close = _bind(dll,"Close")
            Map = _bind(dll,"MapClientDataNameToID"); Add = _bind(dll,"AddToClientDataDefinition")
            Request = _bind(dll,"RequestClientData"); Dispatch = _bind(dll,"CallDispatch")
            Open.argtypes=[ctypes.POINTER(c_void_p),ctypes.c_char_p,c_void_p,c_uint32,c_void_p,c_uint32]; Open.restype=ctypes.c_long
            Close.argtypes=[c_void_p]; Close.restype=ctypes.c_long
            Map.argtypes=[c_void_p,ctypes.c_char_p,c_uint32]; Map.restype=ctypes.c_long
            Add.argtypes=[c_void_p,c_uint32,c_uint32,c_uint32,ctypes.c_float,c_uint32]; Add.restype=ctypes.c_long
            Request.argtypes=[c_void_p,c_uint32,c_uint32,c_uint32,c_uint32,c_uint32,c_uint32,c_uint32,c_uint32]; Request.restype=ctypes.c_long
            Dispatch.argtypes=[c_void_p,CALLBACK,c_void_p]; Dispatch.restype=ctypes.c_long
            hr=Open(ctypes.byref(h),b"OPS ROOM PMDG 777 SDK",None,0,None,0)
            if hr < 0: raise ConnectionError(f"SimConnect_Open failed ({hr})")
            if Map(h,PMDG_DATA_NAME,PMDG_DATA_ID) < 0: raise ConnectionError("PMDG client-data name is unavailable")
            if Add(h,PMDG_DATA_DEFINITION,0,PMDG_DATA_SIZE,0.0,0) < 0: raise ConnectionError("PMDG client-data definition failed")
            if Request(h,PMDG_DATA_ID,REQUEST_ID,PMDG_DATA_DEFINITION,SIMCONNECT_CLIENT_DATA_PERIOD_ON_SET,SIMCONNECT_CLIENT_DATA_REQUEST_FLAG_CHANGED,0,0,0) < 0:
                raise ConnectionError("PMDG client-data subscription failed")
            with _LOCK: _CONNECTED=True; _LAST_ERROR=""

            @CALLBACK
            def callback(p_data: ctypes.POINTER(SimRecv), _cb: int, _context: c_void_p) -> None:
                global _LAST_RAW, _LAST_SNAPSHOT, _LAST_RECEIVED
                try:
                    base = p_data.contents
                    if int(base.dwID) != SIMCONNECT_RECV_ID_CLIENT_DATA:
                        return
                    recv = ctypes.cast(p_data, ctypes.POINTER(SimRecvClientData)).contents
                    if int(recv.dwRequestID) != REQUEST_ID:
                        return
                    address = ctypes.addressof(recv) + SimRecvClientData.dwData.offset
                    available = max(0, int(recv.dwSize) - SimRecvClientData.dwData.offset)
                    if available < PMDG_DATA_SIZE:
                        return
                    raw = ctypes.string_at(address, PMDG_DATA_SIZE)
                    snapshot = _decode(raw)
                    with _LOCK:
                        _LAST_RAW=raw; _LAST_SNAPSHOT=snapshot; _LAST_RECEIVED=time.monotonic()
                except Exception:
                    return

            while not _STOP.wait(0.02):
                hr = Dispatch(h, callback, None)
                if hr < 0: raise ConnectionError(f"SimConnect_CallDispatch failed ({hr})")
        except Exception as exc:
            with _LOCK:
                _CONNECTED=False; _LAST_ERROR=f"{type(exc).__name__}: {exc}"
            _STOP.wait(2.0)
        finally:
            if h.value:
                try: Close(h)
                except Exception: pass
            with _LOCK: _CONNECTED=False


def start() -> None:
    global _THREAD
    if not _eula_accepted():
        return
    with _LOCK:
        if _THREAD and _THREAD.is_alive(): return
        _STOP.clear(); _THREAD=threading.Thread(target=_run,name="OpsRoom-PMDG777SDK",daemon=True); _THREAD.start()


def shutdown() -> None:
    _STOP.set()


def snapshot() -> dict[str, Any]:
    if not _eula_accepted():
        return {}
    start()
    with _LOCK:
        result = dict(_LAST_SNAPSHOT)
        age = time.monotonic() - _LAST_RECEIVED if _LAST_RECEIVED else None
        if result:
            result["age_seconds"] = round(age or 0.0,3)
            result["fresh"] = bool(age is not None and age <= 5.0)
        return result


def status() -> dict[str, Any]:
    eula_ok = _eula_accepted()
    with _LOCK:
        age = time.monotonic() - _LAST_RECEIVED if _LAST_RECEIVED else None
        return {
            "connected": bool(_CONNECTED) if eula_ok else False,
            "receiving": bool(eula_ok and _LAST_SNAPSHOT and age is not None and age <= 5.0),
            "eula_accepted": eula_ok,
            "last_received_age_seconds": round(age,2) if age is not None and eula_ok else None,
            "aircraft_model": _LAST_SNAPSHOT.get("aircraft_model") if _LAST_SNAPSHOT and eula_ok else None,
            "reason": ("PMDG 777 SDK EULA acceptance required" if not eula_ok else (_LAST_ERROR or ("Waiting for PMDG data broadcast" if not _LAST_SNAPSHOT else ""))),
            "dll": _DLL_PATH or None, "data_block_size": PMDG_DATA_SIZE,
        }
