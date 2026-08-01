from __future__ import annotations

import ctypes
import json
import math
import os
import threading
import time
from ctypes import byref, c_char, c_double, c_float, c_uint32, c_void_p, Structure
from pathlib import Path
from typing import Any

from .camera_state import get_target
from .simconnect_position import _candidate_library_paths  # local packaging helper

MAGIC = 0x4F505342
VERSION = 15
SIMCONNECT_CLIENTDATA_MAX_SIZE = 8192
BRIDGE_STATUS_CHART_TEXT_SIZE = 3072
SIMCONNECT_OBJECT_ID_USER = 0
SIMCONNECT_PERIOD_NEVER = 0
SIMCONNECT_PERIOD_ONCE = 1
SIMCONNECT_PERIOD_SECOND = 4
SIMCONNECT_RECV_ID_SIMOBJECT_DATA = 8
SIMCONNECT_DATATYPE_FLOAT64 = 4

# Legacy client-data IDs are kept only for parsing old bridge status if a user has
# an old package installed. v0.23.18 uses SimConnect Client Data for WASM heartbeat/status.
CID_COMMAND = 0x4F523501
CID_STATUS = 0x4F523502
DEF_COMMAND = 501
DEF_STATUS = 502
REQ_COMMAND = 601
REQ_STATUS = 602
DEF_USER_POSITION = 906
REQ_USER_POSITION = 907
SIMCONNECT_CLIENT_DATA_PERIOD_ONCE = 1
SIMCONNECT_CLIENT_DATA_PERIOD_SECOND = 4
SIMCONNECT_CLIENT_DATA_REQUEST_FLAG_CHANGED = 1
SIMCONNECT_CLIENT_DATA_SET_FLAG_DEFAULT = 0
SIMCONNECT_RECV_ID_CLIENT_DATA = 16
SIMCONNECT_RECV_ID_ASSIGNED_OBJECT_ID = 17
SIMCONNECT_RECV_ID_EXCEPTION = 1
REQ_NATIVE_API_HARNESS = 904
REQ_NATIVE_API_HARNESS_EX1 = 904
REQ_NATIVE_API_HARNESS_LEGACY = 905
NATIVE_API_HARNESS_TITLE = b"OPS ROOM Native API Harness"
NATIVE_API_ACTIVATION_MIN_INTERVAL = 30.0
NATIVE_API_ACTIVATION_FAIL_COOLDOWN = 45.0
_SIMCONNECT_EXCEPTION_NAMES = {
    1: "ERROR", 2: "SIZE_MISMATCH", 3: "UNRECOGNIZED_ID", 4: "UNOPENED", 5: "VERSION_MISMATCH",
    6: "TOO_MANY_GROUPS", 7: "NAME_UNRECOGNIZED", 8: "TOO_MANY_EVENT_NAMES", 9: "EVENT_ID_DUPLICATE",
    10: "TOO_MANY_MAPS", 11: "TOO_MANY_OBJECTS", 12: "TOO_MANY_REQUESTS", 18: "INVALID_DATA_TYPE",
    19: "INVALID_DATA_SIZE", 20: "DATA_ERROR", 21: "INVALID_ARRAY", 22: "CREATE_OBJECT_FAILED",
    23: "LOAD_FLIGHTPLAN_FAILED", 24: "OPERATION_INVALID_FOR_OBJECT_TYPE", 25: "ILLEGAL_OPERATION",
    31: "OUT_OF_BOUNDS", 33: "OBJECT_OUTSIDE_REALITY_BUBBLE", 34: "OBJECT_CONTAINER", 35: "OBJECT_AI",
    36: "OBJECT_ATC", 37: "OBJECT_SCHEDULE",
}

# Optional MSFS 2024 SimConnect CommBus constants retained for future camera/charts commands.
# v0.23.18 heartbeat does not require these exports because the bundled SimConnect.dll may not expose them.
SIMCONNECT_RECV_ID_COMM_BUS = 44
SIMCONNECT_COMM_BUS_BROADCAST_TO_WASM = 1 << 1
EVENT_STATUS = 9001
EVENT_STATUS_NAME = b"OPSROOM.BRIDGE.STATUS"
EVENT_PING_NAME = b"OPSROOM.BRIDGE.PING"
EVENT_COMMAND_NAME = b"OPSROOM.BRIDGE.COMMAND"
EVENT_CHARTS_NAME = b"OPSROOM.BRIDGE.CHARTS"

_RUNNING = False
_THREAD: threading.Thread | None = None
_LOCK = threading.Lock()
_SEQ = 0
_CHART_SEQ = 0
_CHART_AIRPORT = ""
_LAST_STATUS: dict[str, Any] = {"connected": False, "state": "STANDBY", "message": "Native bridge host not started"}
_LAST_ERROR = ""
_SIMCONNECT_DLL_PATH = ""
_SIMCONNECT_OPEN_HRESULT: int | None = None
_SIMCONNECT_RETRY_COUNT = 0
_CLIENT_DATA_SUBSCRIBED = False
_COMMAND_DATA_READY = False
_COMMAND_SENT_SEQ = 0
_COMMAND_LAST_SEND = 0.0
NATIVE_WASM_CHARTS_ENABLED = True
_NATIVE_API_ACTIVATION_ATTEMPTED = False
_NATIVE_API_ACTIVATION_HR: int | None = None
_NATIVE_API_ACTIVATION_MESSAGE = "Native API SimObject harness has not been requested yet"
_NATIVE_API_LAST_ACTIVATION = 0.0
_NATIVE_API_OBJECT_ID: int | None = None
_NATIVE_API_ACTIVATION_FAILED = False
_NATIVE_API_LAST_EXCEPTION: int | None = None
_NATIVE_API_LAST_EXCEPTION_SEND_ID: int | None = None
_NATIVE_API_LAST_EXCEPTION_INDEX: int | None = None
_NATIVE_API_CREATE_SEND_IDS: dict[int, str] = {}
_NATIVE_API_CREATE_REQUEST_METHOD: dict[int, str] = {}
_NATIVE_API_LAST_CREATE_SEND_ID: int | None = None
_NATIVE_API_LAST_CREATE_METHOD = ""
_NATIVE_API_FORCE_LEGACY_NEXT = False
_NATIVE_API_STATUS_LATCHED = False
_USER_POSITION: dict[str, float] | None = None
_USER_POSITION_UPDATED_AT = 0.0
_USER_POSITION_SOURCE = "none"
_USER_POSITION_MESSAGE = "User aircraft position has not been received on the native bridge SimConnect client yet"
_POSITION_DATA_READY = False
_USER_POSITION_REQUEST_COUNT = 0
_USER_POSITION_LAST_REQUEST_AT = 0.0
_USER_POSITION_LAST_REQUEST_HR: int | None = None
_USER_POSITION_LAST_REQUEST_MESSAGE = "User aircraft position request has not been sent yet"
_NATIVE_API_ACTIVATION_GATE = "waiting_for_user_position"
_FALLBACK_POSITION_THREAD: threading.Thread | None = None
_FALLBACK_POSITION_STARTED_AT = 0.0
_FALLBACK_POSITION_MESSAGE = "fallback position read not started"



class SimConnectDataInitPosition(Structure):
    _fields_ = [
        ("Latitude", c_double),
        ("Longitude", c_double),
        ("Altitude", c_double),
        ("Pitch", c_double),
        ("Bank", c_double),
        ("Heading", c_double),
        ("OnGround", c_uint32),
        ("Airspeed", c_uint32),
    ]

class BridgeCommand(Structure):
    _pack_ = 8
    _fields_ = [
        ("magic", c_uint32), ("version", c_uint32), ("seq", c_uint32), ("command", c_uint32),
        ("callsign", c_char * 32), ("label", c_char * 48), ("airport", c_char * 8),
        ("latitude", c_double), ("longitude", c_double), ("altitude_ft", c_double), ("object_id", c_double),
        ("released", c_uint32), ("mode", c_char * 24),
        ("distance", c_double), ("height", c_double), ("sideOffset", c_double), ("pitch", c_double),
        ("orbitAngle", c_double), ("smoothing", c_double), ("chartSeq", c_uint32), ("chartAirport", c_char * 8),
    ]


class BridgeStatus(Structure):
    _pack_ = 8
    _fields_ = [
        ("magic", c_uint32), ("version", c_uint32), ("seq", c_uint32),
        ("loaded", c_uint32), ("connected", c_uint32), ("cameraActive", c_uint32), ("chartReady", c_uint32),
        ("state", c_char * 32), ("message", c_char * 256), ("target", c_char * 32), ("match", c_char * 96),
        ("chartAirport", c_char * 8), ("chartCount", c_uint32), ("chartText", c_char * BRIDGE_STATUS_CHART_TEXT_SIZE),
    ]



if ctypes.sizeof(BridgeStatus) > SIMCONNECT_CLIENTDATA_MAX_SIZE:
    raise RuntimeError(f"BridgeStatus exceeds SimConnect Client Data max size: {ctypes.sizeof(BridgeStatus)} > {SIMCONNECT_CLIENTDATA_MAX_SIZE}")
if ctypes.sizeof(BridgeCommand) > SIMCONNECT_CLIENTDATA_MAX_SIZE:
    raise RuntimeError(f"BridgeCommand exceeds SimConnect Client Data max size: {ctypes.sizeof(BridgeCommand)} > {SIMCONNECT_CLIENTDATA_MAX_SIZE}")

class SimRecv(Structure):
    _fields_ = [("dwSize", c_uint32), ("dwVersion", c_uint32), ("dwID", c_uint32)]


class SimRecvClientData(Structure):
    _fields_ = [
        ("dwSize", c_uint32), ("dwVersion", c_uint32), ("dwID", c_uint32),
        ("dwRequestID", c_uint32), ("dwObjectID", c_uint32), ("dwDefineID", c_uint32), ("dwFlags", c_uint32),
        ("dwentrynumber", c_uint32), ("dwoutof", c_uint32), ("dwDefineCount", c_uint32),
        ("dwData", c_uint32 * 1),
    ]


class SimRecvSimobjectData(Structure):
    _fields_ = [
        ("dwSize", c_uint32), ("dwVersion", c_uint32), ("dwID", c_uint32),
        ("dwRequestID", c_uint32), ("dwObjectID", c_uint32), ("dwDefineID", c_uint32), ("dwFlags", c_uint32),
        ("dwentrynumber", c_uint32), ("dwoutof", c_uint32), ("dwDefineCount", c_uint32),
        ("dwData", c_uint32 * 1),
    ]


class UserPositionWire(Structure):
    _pack_ = 8
    _fields_ = [
        ("latitude", c_double),
        ("longitude", c_double),
        ("altitude_ft", c_double),
        ("heading_deg", c_double),
        ("agl_ft", c_double),
        ("on_ground", c_double),
    ]


class SimRecvCommBusFixed(Structure):
    _fields_ = [
        ("dwSize", c_uint32), ("dwVersion", c_uint32), ("dwID", c_uint32),
        ("dwRequestID", c_uint32), ("dwArraySize", c_uint32),
        ("dwEntryNumber", c_uint32), ("dwOutOf", c_uint32),
        ("uEventID", c_uint32), ("rgData", c_char * 1),
    ]


CALLBACK = ctypes.WINFUNCTYPE(None, ctypes.POINTER(SimRecv), c_uint32, c_void_p) if os.name == "nt" else None


def _text(raw: Any) -> str:
    try:
        value = bytes(raw).split(b"\0", 1)[0]
        return value.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def _b(value: Any, limit: int) -> bytes:
    return str(value or "").encode("utf-8", "ignore")[: max(0, limit - 1)]


def _num(value: Any, fallback: float = math.nan) -> float:
    try:
        n = float(value)
        return n if math.isfinite(n) else fallback
    except Exception:
        return fallback


def _clean_callsign(value: Any) -> str:
    text = str(value or "").upper().strip()
    return "".join(ch for ch in text if ch.isalnum())[:31]


def _dll_path() -> Path | None:
    for candidate in _candidate_library_paths():
        if candidate.is_file():
            return candidate
    return None


class _SimConnectApi:
    pass


def _bind(dll: Any, short_name: str) -> Any:
    sdk_name = f"SimConnect_{short_name}"
    fn = getattr(dll, sdk_name, None)
    if fn is None:
        fn = getattr(dll, short_name, None)
    if fn is None:
        raise AttributeError(f"SimConnect.dll export {sdk_name} was not found")
    return fn


def _bind_optional(dll: Any, short_name: str) -> Any | None:
    try:
        return _bind(dll, short_name)
    except AttributeError:
        return None


def _load_dll() -> Any:
    path = _dll_path()
    if not path:
        raise FileNotFoundError("SimConnect.dll not found for native bridge host")
    dll = ctypes.WinDLL(str(path))
    api = _SimConnectApi()
    api.Open = _bind(dll, "Open")
    api.Open.argtypes = [ctypes.POINTER(c_void_p), ctypes.c_char_p, c_void_p, c_uint32, c_void_p, c_uint32]
    api.Open.restype = ctypes.c_long
    api.Close = _bind(dll, "Close")
    api.Close.argtypes = [c_void_p]
    api.Close.restype = ctypes.c_long
    api.MapClientDataNameToID = _bind_optional(dll, "MapClientDataNameToID")
    if api.MapClientDataNameToID is not None:
        api.MapClientDataNameToID.argtypes = [c_void_p, ctypes.c_char_p, c_uint32]
        api.MapClientDataNameToID.restype = ctypes.c_long
    api.CreateClientData = _bind_optional(dll, "CreateClientData")
    if api.CreateClientData is not None:
        api.CreateClientData.argtypes = [c_void_p, c_uint32, c_uint32, c_uint32]
        api.CreateClientData.restype = ctypes.c_long
    api.AddToClientDataDefinition = _bind_optional(dll, "AddToClientDataDefinition")
    if api.AddToClientDataDefinition is not None:
        api.AddToClientDataDefinition.argtypes = [c_void_p, c_uint32, c_uint32, c_uint32, c_float, c_uint32]
        api.AddToClientDataDefinition.restype = ctypes.c_long
    api.RequestClientData = _bind_optional(dll, "RequestClientData")
    if api.RequestClientData is not None:
        api.RequestClientData.argtypes = [c_void_p, c_uint32, c_uint32, c_uint32, c_uint32, c_uint32, c_uint32, c_uint32, c_uint32]
        api.RequestClientData.restype = ctypes.c_long
    api.SetClientData = _bind_optional(dll, "SetClientData")
    if api.SetClientData is not None:
        api.SetClientData.argtypes = [c_void_p, c_uint32, c_uint32, c_uint32, c_uint32, c_uint32, c_void_p]
        api.SetClientData.restype = ctypes.c_long
    api.AddToDataDefinition = _bind_optional(dll, "AddToDataDefinition")
    if api.AddToDataDefinition is not None:
        api.AddToDataDefinition.argtypes = [c_void_p, c_uint32, ctypes.c_char_p, ctypes.c_char_p, c_uint32, c_float, c_uint32]
        api.AddToDataDefinition.restype = ctypes.c_long
    api.RequestDataOnSimObject = _bind_optional(dll, "RequestDataOnSimObject")
    if api.RequestDataOnSimObject is not None:
        api.RequestDataOnSimObject.argtypes = [c_void_p, c_uint32, c_uint32, c_uint32, c_uint32, c_uint32, c_uint32, c_uint32, c_uint32]
        api.RequestDataOnSimObject.restype = ctypes.c_long
    api.GetLastSentPacketID = _bind_optional(dll, "GetLastSentPacketID")
    if api.GetLastSentPacketID is not None:
        api.GetLastSentPacketID.argtypes = [c_void_p, ctypes.POINTER(c_uint32)]
        api.GetLastSentPacketID.restype = ctypes.c_long
    api.SubscribeToCommBusEvent = _bind_optional(dll, "SubscribeToCommBusEvent")
    if api.SubscribeToCommBusEvent is not None:
        api.SubscribeToCommBusEvent.argtypes = [c_void_p, c_uint32, ctypes.c_char_p]
        api.SubscribeToCommBusEvent.restype = ctypes.c_long
    api.UnsubscribeToCommBusEvent = _bind_optional(dll, "UnsubscribeToCommBusEvent")
    if api.UnsubscribeToCommBusEvent is not None:
        api.UnsubscribeToCommBusEvent.argtypes = [c_void_p, c_uint32]
        api.UnsubscribeToCommBusEvent.restype = ctypes.c_long
    api.CallCommBusEvent = _bind_optional(dll, "CallCommBusEvent")
    if api.CallCommBusEvent is not None:
        api.CallCommBusEvent.argtypes = [c_void_p, ctypes.c_char_p, c_uint32, c_uint32, ctypes.c_char_p]
        api.CallCommBusEvent.restype = ctypes.c_long
    api.AICreateSimulatedObject = _bind_optional(dll, "AICreateSimulatedObject")
    if api.AICreateSimulatedObject is not None:
        api.AICreateSimulatedObject.argtypes = [c_void_p, ctypes.c_char_p, SimConnectDataInitPosition, c_uint32]
        api.AICreateSimulatedObject.restype = ctypes.c_long
    # MSFS 2024 EX1 is documented for modular SimObjects as well as legacy SimObjects.
    # Prefer it for the OPS ROOM SimObject harness, then fall back to legacy export.
    api.AICreateSimulatedObject_EX1 = _bind_optional(dll, "AICreateSimulatedObject_EX1")
    if api.AICreateSimulatedObject_EX1 is not None:
        api.AICreateSimulatedObject_EX1.argtypes = [c_void_p, ctypes.c_char_p, ctypes.c_char_p, SimConnectDataInitPosition, c_uint32]
        api.AICreateSimulatedObject_EX1.restype = ctypes.c_long
    api.CallDispatch = _bind(dll, "CallDispatch")
    api.CallDispatch.argtypes = [c_void_p, CALLBACK, c_void_p]
    api.CallDispatch.restype = ctypes.c_long
    return api


def _command_from_target() -> BridgeCommand:
    global _SEQ
    target = get_target()
    view = target.get("view") if isinstance(target.get("view"), dict) else {}
    _SEQ += 1
    c = BridgeCommand()
    c.magic = MAGIC
    c.version = VERSION
    c.seq = _SEQ
    released = bool(target.get("released")) or str(target.get("command") or "").lower() == "release"
    with _LOCK:
        chart_seq = _CHART_SEQ
        chart_airport = _CHART_AIRPORT[:7]
    callsign = _clean_callsign(target.get("callsign") or target.get("label") or target.get("target"))
    object_id_value = _num(target.get("object_id") or target.get("objectId") or target.get("simObjectId") or target.get("sim_object_id"))
    c.command = 3 if released else (1 if callsign or math.isfinite(object_id_value) else (20 if chart_seq and chart_airport else 0))
    c.callsign = _b(callsign, 32)
    c.label = _b(target.get("label") or callsign, 48)
    c.airport = _b(str(target.get("airport") or "").upper()[:7], 8)
    c.latitude = _num(target.get("latitude"))
    c.longitude = _num(target.get("longitude"))
    c.altitude_ft = _num(target.get("altitude"))
    c.object_id = object_id_value
    c.released = 1 if released else 0
    c.mode = _b(str(view.get("mode") or "tail_follow")[:23], 24)
    c.distance = max(5.0, min(1200.0, _num(view.get("distance"), 45.0)))
    c.height = max(-50.0, min(500.0, _num(view.get("height"), 9.0)))
    c.sideOffset = max(-600.0, min(600.0, _num(view.get("sideOffset"), 0.0)))
    c.pitch = max(-89.0, min(45.0, _num(view.get("pitch"), -7.0)))
    c.orbitAngle = _num(view.get("orbitAngle"), 180.0) % 360.0
    c.smoothing = max(0.0, min(0.98, _num(view.get("smoothing"), 0.35)))
    c.chartSeq = chart_seq
    c.chartAirport = _b(chart_airport, 8)
    return c


def _command_payload() -> dict[str, Any]:
    cmd = _command_from_target()
    return {
        "source": "opsroom-host",
        "version": "0.23.22",
        "seq": int(cmd.seq),
        "command": "release" if int(cmd.released) else "ping",
        "callsign": _text(cmd.callsign),
        "label": _text(cmd.label),
        "airport": _text(cmd.airport),
        "mode": _text(cmd.mode),
        "chart_seq": int(cmd.chartSeq),
        "chart_airport": _text(cmd.chartAirport),
    }


def _update_status(st: BridgeStatus) -> None:
    global _NATIVE_API_STATUS_LATCHED
    if st.magic != MAGIC:
        return
    chart_text = _text(st.chartText)
    items = []
    for line in chart_text.splitlines():
        parts = line.split("|")
        if len(parts) >= 5 and parts[0] == "CHART":
            item = {
                "category": parts[1],
                "guid": parts[2],
                "name": parts[3],
                "type": parts[4],
                "title": parts[3] or parts[4],
            }
            if len(parts) > 5: item["provider"] = parts[5]
            if len(parts) > 6:
                try: item["pages"] = int(parts[6] or 0)
                except Exception: item["pages"] = 0
            if len(parts) > 7: item["geo_referenced"] = str(parts[7]).strip() in {"1", "true", "TRUE"}
            if len(parts) > 8: item["size"] = parts[8]
            items.append(item)
    state_text = _text(st.state) or "READY"
    message_text = _text(st.message)
    if state_text.upper().startswith(("API_", "CHARTS_", "CAMERA_")) or "native API WASM system" in message_text or chart_text.startswith("API_READY|"):
        _NATIVE_API_STATUS_LATCHED = True
    with _LOCK:
        _LAST_STATUS.clear()
        _LAST_STATUS.update({
            "ok": True,
            "connected": bool(st.connected),
            "loaded": bool(st.loaded),
            "transport": "client_data",
            "camera_active": bool(st.cameraActive),
            "chart_ready": bool(st.chartReady),
            "chart_count": int(st.chartCount),
            "state": state_text,
            "message": message_text,
            "target": _text(st.target),
            "match": _text(st.match),
            "chart_airport": _text(st.chartAirport),
            "chart_text": chart_text,
            "chart_items": items,
            "seq": int(st.seq),
            "updated_at_monotonic": time.monotonic(),
            "last_error": _LAST_ERROR,
            "simconnect_connected": True,
            "client_data_subscribed": _CLIENT_DATA_SUBSCRIBED,
            "simconnect_dll_path": _SIMCONNECT_DLL_PATH,
            "simconnect_open_hresult": _SIMCONNECT_OPEN_HRESULT,
            "simconnect_retry_count": _SIMCONNECT_RETRY_COUNT,
        })


def _commbus_text(raw: ctypes.POINTER(SimRecv), recv: SimRecv) -> tuple[int, str, int, int]:
    fixed = ctypes.cast(raw, ctypes.POINTER(SimRecvCommBusFixed)).contents
    offset = SimRecvCommBusFixed.rgData.offset
    size = max(0, int(recv.dwSize) - offset)
    if size <= 0:
        return int(fixed.uEventID), "", int(fixed.dwEntryNumber), int(fixed.dwOutOf)
    data = ctypes.string_at(ctypes.addressof(raw.contents) + offset, size).split(b"\0", 1)[0]
    return int(fixed.uEventID), data.decode("utf-8", "replace"), int(fixed.dwEntryNumber), int(fixed.dwOutOf)


_LAST_COMMAND_SIGNATURE = ""

def _target_signature_for_command() -> str:
    target = get_target()
    view = target.get("view") if isinstance(target.get("view"), dict) else {}
    with _LOCK:
        chart_seq = _CHART_SEQ
        chart_airport = _CHART_AIRPORT
    parts = [
        str(target.get("command") or ""), str(bool(target.get("released"))),
        str(target.get("callsign") or target.get("label") or target.get("target") or ""),
        str(target.get("latitude") or ""), str(target.get("longitude") or ""), str(target.get("altitude") or ""),
        str(target.get("object_id") or target.get("simObjectId") or target.get("sim_object_id") or ""),
        str(view.get("mode") or ""), str(view.get("distance") or ""), str(view.get("height") or ""),
        str(view.get("sideOffset") or ""), str(view.get("pitch") or ""), str(view.get("orbitAngle") or ""),
        str(chart_seq), str(chart_airport),
    ]
    return "|".join(parts)

def _send_command_data(dll: Any, h: Any, force: bool = False) -> None:
    global _COMMAND_SENT_SEQ, _COMMAND_LAST_SEND, _LAST_ERROR, _LAST_COMMAND_SIGNATURE
    if dll is None or not h or not getattr(h, "value", None):
        return
    if getattr(dll, "SetClientData", None) is None:
        return
    sig = _target_signature_for_command()
    now = time.monotonic()
    if not force and sig == _LAST_COMMAND_SIGNATURE and now - _COMMAND_LAST_SEND < 1.0:
        return
    cmd = _command_from_target()
    # Do not spam idle/no-target commands unless there is a chart request or release.
    if not cmd.chartSeq and not cmd.released and not _text(cmd.callsign) and not math.isfinite(float(cmd.object_id)):
        return
    try:
        hr = dll.SetClientData(h, CID_COMMAND, DEF_COMMAND, SIMCONNECT_CLIENT_DATA_SET_FLAG_DEFAULT, 0, ctypes.sizeof(cmd), byref(cmd))
        if hr == 0:
            _COMMAND_SENT_SEQ = int(cmd.seq)
            _COMMAND_LAST_SEND = now
            _LAST_COMMAND_SIGNATURE = sig
        else:
            _LAST_ERROR = f"SetClientData command failed {hr}"
    except Exception as exc:
        _LAST_ERROR = f"SetClientData command exception: {exc}"




def _status_is_from_native_api() -> bool:
    with _LOCK:
        state = str(_LAST_STATUS.get("state") or "").upper()
        message = str(_LAST_STATUS.get("message") or "")
        chart_text = str(_LAST_STATUS.get("chart_text") or "")
    if _NATIVE_API_STATUS_LATCHED:
        return True
    if state.startswith("API_") or state.startswith("CHARTS_") or state.startswith("CAMERA_"):
        return True
    return "native API WASM system" in message or chart_text.startswith("API_READY|")


def _is_valid_user_position(data: dict[str, float] | None) -> bool:
    if not data:
        return False
    try:
        lat = float(data.get("lat", math.nan))
        lon = float(data.get("lon", math.nan))
        alt = float(data.get("altitude_ft", math.nan))
    except Exception:
        return False
    return (
        math.isfinite(lat) and math.isfinite(lon) and math.isfinite(alt)
        and -90.0 <= lat <= 90.0
        and -180.0 <= lon <= 180.0
        and -2000.0 <= alt <= 100000.0
        and not (abs(lat) < 0.000001 and abs(lon) < 0.000001)
    )


def _update_user_position_from_wire(wire: UserPositionWire) -> None:
    global _USER_POSITION, _USER_POSITION_UPDATED_AT, _USER_POSITION_SOURCE, _USER_POSITION_MESSAGE
    data = {
        "lat": float(wire.latitude),
        "lon": float(wire.longitude),
        "altitude_ft": float(wire.altitude_ft),
        "heading_deg": float(wire.heading_deg) % 360.0 if math.isfinite(float(wire.heading_deg)) else 0.0,
        "agl_ft": float(wire.agl_ft),
        "on_ground": float(wire.on_ground),
    }
    if not _is_valid_user_position(data):
        _USER_POSITION_MESSAGE = "Waiting for sane user aircraft lat/lon/alt from native bridge SimConnect client"
        return
    _USER_POSITION = data
    _USER_POSITION_UPDATED_AT = time.monotonic()
    _USER_POSITION_SOURCE = "same_client_simconnect"
    _USER_POSITION_MESSAGE = "ok"


def _request_user_position(dll: Any, h: Any) -> None:
    global _LAST_ERROR, _USER_POSITION_REQUEST_COUNT, _USER_POSITION_LAST_REQUEST_AT, _USER_POSITION_LAST_REQUEST_HR, _USER_POSITION_LAST_REQUEST_MESSAGE
    if not _POSITION_DATA_READY or getattr(dll, "RequestDataOnSimObject", None) is None:
        _USER_POSITION_LAST_REQUEST_MESSAGE = "SimConnect user-position data definition is not ready"
        return
    try:
        _USER_POSITION_REQUEST_COUNT += 1
        _USER_POSITION_LAST_REQUEST_AT = time.monotonic()
        hr = dll.RequestDataOnSimObject(h, REQ_USER_POSITION, DEF_USER_POSITION, SIMCONNECT_OBJECT_ID_USER, SIMCONNECT_PERIOD_ONCE, 0, 0, 0, 0)
        _USER_POSITION_LAST_REQUEST_HR = int(hr)
        if int(hr) != 0:
            _USER_POSITION_LAST_REQUEST_MESSAGE = f"RequestDataOnSimObject user position failed {int(hr)}"
            _LAST_ERROR = _USER_POSITION_LAST_REQUEST_MESSAGE
        else:
            _USER_POSITION_LAST_REQUEST_MESSAGE = "RequestDataOnSimObject user position ONCE request sent"
    except Exception as exc:
        _USER_POSITION_LAST_REQUEST_MESSAGE = f"RequestDataOnSimObject user position exception: {exc}"
        _LAST_ERROR = _USER_POSITION_LAST_REQUEST_MESSAGE


def _set_user_position_from_dict(data: dict[str, Any], source: str) -> bool:
    global _USER_POSITION, _USER_POSITION_UPDATED_AT, _USER_POSITION_SOURCE, _USER_POSITION_MESSAGE
    pos = {
        "lat": float(data.get("lat")),
        "lon": float(data.get("lon")),
        "altitude_ft": float(data.get("altitude_ft") if data.get("altitude_ft") is not None else data.get("indicated_altitude_ft")),
        "heading_deg": float(data.get("heading_deg") if data.get("heading_deg") is not None else data.get("track_deg") or 0.0) % 360.0,
        "agl_ft": float(data.get("agl_ft") if data.get("agl_ft") is not None else data.get("radio_altitude_ft") or 0.0),
        "on_ground": 1.0 if bool(data.get("on_ground")) else 0.0,
    }
    if not _is_valid_user_position(pos):
        return False
    _USER_POSITION = pos
    _USER_POSITION_UPDATED_AT = time.monotonic()
    _USER_POSITION_SOURCE = source
    _USER_POSITION_MESSAGE = f"ok ({source})"
    return True


def _target_position_fallback() -> dict[str, float] | None:
    try:
        target = get_target()
    except Exception:
        return None
    lat = _num(target.get("latitude") or target.get("lat"))
    lon = _num(target.get("longitude") or target.get("lon"))
    alt = _num(target.get("altitude") or target.get("altitude_ft"), 0.0)
    if lat is None or lon is None or not math.isfinite(lat) or not math.isfinite(lon):
        return None
    return {
        "lat": lat,
        "lon": lon,
        "altitude_ft": alt if math.isfinite(alt) else 0.0,
        "heading_deg": _num(target.get("heading") or target.get("heading_deg") or target.get("track_deg"), 0.0) % 360.0,
        "agl_ft": _num(target.get("agl_ft"), 0.0),
        "on_ground": 0.0,
    }


def _start_fallback_position_read() -> None:
    """Start one non-blocking fallback read through the existing safe telemetry wrapper.

    The native activation loop must not call read_position() synchronously because
    that can block the backend during MSFS startup. A single daemon worker gives
    us a fallback position if same-client RequestDataOnSimObject is delayed or
    rejected, while the bridge dispatch loop remains responsive.
    """
    global _FALLBACK_POSITION_THREAD, _FALLBACK_POSITION_STARTED_AT, _FALLBACK_POSITION_MESSAGE
    if _is_valid_user_position(_USER_POSITION):
        return
    if _FALLBACK_POSITION_THREAD is not None and _FALLBACK_POSITION_THREAD.is_alive():
        return
    now = time.monotonic()
    if _FALLBACK_POSITION_STARTED_AT and now - _FALLBACK_POSITION_STARTED_AT < 10.0:
        return
    _FALLBACK_POSITION_STARTED_AT = now
    _FALLBACK_POSITION_MESSAGE = "fallback position read started"

    def _worker() -> None:
        global _FALLBACK_POSITION_MESSAGE
        try:
            from .simconnect_position import read_position
            data = read_position(force=True)
            if isinstance(data, dict) and data.get("ok") and _set_user_position_from_dict(data, "simconnect_position_fallback"):
                _FALLBACK_POSITION_MESSAGE = "fallback position read succeeded"
            else:
                _FALLBACK_POSITION_MESSAGE = "fallback position read returned no sane user aircraft position"
        except Exception as exc:
            _FALLBACK_POSITION_MESSAGE = f"fallback position read failed: {type(exc).__name__}: {exc}"

    _FALLBACK_POSITION_THREAD = threading.Thread(target=_worker, name="OpsRoom-NativeActivationPositionFallback", daemon=True)
    _FALLBACK_POSITION_THREAD.start()


def _native_api_activation_position() -> tuple[SimConnectDataInitPosition | None, str]:
    """Return a safe current-position spawn point for the native API SimObject.

    This deliberately uses the same SimConnect handle as the bridge host. v0.23.18
    called simconnect_position.read_position() from inside the activation loop,
    which opened a second SimConnect path during MSFS startup and could block the
    backend exactly when the sim was unstable.
    """
    global _NATIVE_API_ACTIVATION_GATE
    now = time.monotonic()
    if not _is_valid_user_position(_USER_POSITION):
        target_pos = _target_position_fallback()
        if target_pos and _is_valid_user_position(target_pos):
            _NATIVE_API_ACTIVATION_GATE = "target_position_fallback"
            data = target_pos
        else:
            if _USER_POSITION_REQUEST_COUNT >= 3 or (_USER_POSITION_LAST_REQUEST_AT and now - _USER_POSITION_LAST_REQUEST_AT > 2.5):
                _start_fallback_position_read()
            _NATIVE_API_ACTIVATION_GATE = "waiting_for_user_position"
            return None, _USER_POSITION_MESSAGE
    elif now - _USER_POSITION_UPDATED_AT > 20.0:
        # A stale but sane position is still better than never spawning the local
        # system harness. The SimObject is just the owner of systems.cfg; it does
        # not need precision flight telemetry for initial placement.
        _NATIVE_API_ACTIVATION_GATE = "stale_user_position_allowed"
        data = _USER_POSITION or {}
    else:
        _NATIVE_API_ACTIVATION_GATE = "fresh_user_position"
        data = _USER_POSITION or {}
    pos = SimConnectDataInitPosition()
    pos.Latitude = float(data["lat"])
    pos.Longitude = float(data["lon"])
    pos.Altitude = float(data["altitude_ft"])
    pos.Pitch = 0.0
    pos.Bank = 0.0
    pos.Heading = float(data.get("heading_deg", 0.0)) % 360.0
    agl = float(data.get("agl_ft", math.nan))
    on_ground = float(data.get("on_ground", 0.0))
    if (math.isfinite(agl) and agl < 50.0) or on_ground >= 0.5:
        pos.OnGround = 1
        pos.Airspeed = 0
    else:
        pos.OnGround = 0
        pos.Airspeed = 1
    return pos, "ok"


def _broker_status_loaded() -> bool:
    with _LOCK:
        return bool(_LAST_STATUS.get("loaded") and _LAST_STATUS.get("connected") and _LAST_STATUS.get("updated_at_monotonic"))


def _sim_exception_name(value: int | None) -> str:
    if value is None:
        return "UNKNOWN"
    return _SIMCONNECT_EXCEPTION_NAMES.get(int(value), f"EXCEPTION_{int(value)}")


def _remember_last_packet_id(dll: Any, h: Any, method: str, request_id: int) -> int | None:
    global _NATIVE_API_LAST_CREATE_SEND_ID
    getter = getattr(dll, "GetLastSentPacketID", None)
    if getter is None:
        return None
    try:
        packet = c_uint32(0)
        hr = getter(h, byref(packet))
        if int(hr) == 0 and int(packet.value):
            send_id = int(packet.value)
            _NATIVE_API_CREATE_SEND_IDS[send_id] = method
            _NATIVE_API_CREATE_REQUEST_METHOD[int(request_id)] = method
            _NATIVE_API_LAST_CREATE_SEND_ID = send_id
            return send_id
    except Exception:
        return None
    return None


def _native_create_method_order(dll: Any) -> list[tuple[str, Any, int]]:
    creator_ex1 = getattr(dll, "AICreateSimulatedObject_EX1", None)
    creator_legacy = getattr(dll, "AICreateSimulatedObject", None)
    methods: list[tuple[str, Any, int]] = []
    if _NATIVE_API_FORCE_LEGACY_NEXT:
        if creator_legacy is not None:
            methods.append(("SimConnect_AICreateSimulatedObject", creator_legacy, REQ_NATIVE_API_HARNESS_LEGACY))
        if creator_ex1 is not None:
            methods.append(("SimConnect_AICreateSimulatedObject_EX1", creator_ex1, REQ_NATIVE_API_HARNESS_EX1))
    else:
        if creator_ex1 is not None:
            methods.append(("SimConnect_AICreateSimulatedObject_EX1", creator_ex1, REQ_NATIVE_API_HARNESS_EX1))
        if creator_legacy is not None:
            methods.append(("SimConnect_AICreateSimulatedObject", creator_legacy, REQ_NATIVE_API_HARNESS_LEGACY))
    return methods


def _activate_native_api_harness(dll: Any, h: Any, *, force: bool = False) -> None:
    global _NATIVE_API_ACTIVATION_ATTEMPTED, _NATIVE_API_ACTIVATION_HR, _NATIVE_API_ACTIVATION_MESSAGE, _NATIVE_API_LAST_ACTIVATION, _NATIVE_API_ACTIVATION_FAILED, _NATIVE_API_LAST_CREATE_METHOD, _NATIVE_API_FORCE_LEGACY_NEXT
    if dll is None or not h or not getattr(h, "value", None):
        return
    if _status_is_from_native_api() and not force:
        return
    if not _broker_status_loaded() and not force:
        _NATIVE_API_ACTIVATION_MESSAGE = "Waiting for standalone broker heartbeat before native API SimObject activation"
        return
    now = time.monotonic()
    cooldown = NATIVE_API_ACTIVATION_FAIL_COOLDOWN if _NATIVE_API_ACTIVATION_FAILED else NATIVE_API_ACTIVATION_MIN_INTERVAL
    if not force and now - _NATIVE_API_LAST_ACTIVATION < cooldown:
        return

    init, reason = _native_api_activation_position()
    if init is None:
        _NATIVE_API_ACTIVATION_MESSAGE = reason
        return

    methods = _native_create_method_order(dll)
    if not methods:
        _NATIVE_API_ACTIVATION_HR = None
        _NATIVE_API_ACTIVATION_MESSAGE = "No SimConnect AI object creation export available; native API SimObject harness cannot be spawned"
        return

    _NATIVE_API_LAST_ACTIVATION = now
    _NATIVE_API_ACTIVATION_ATTEMPTED = True
    _NATIVE_API_ACTIVATION_FAILED = False
    last_message = ""
    for method, creator, request_id in methods:
        try:
            if method.endswith("_EX1"):
                hr = creator(h, NATIVE_API_HARNESS_TITLE, b"", init, request_id)
            else:
                hr = creator(h, NATIVE_API_HARNESS_TITLE, init, request_id)
            _NATIVE_API_ACTIVATION_HR = int(hr)
            _NATIVE_API_LAST_CREATE_METHOD = method
            send_id = _remember_last_packet_id(dll, h, method, request_id)
            if int(hr) == 0:
                packet_note = f"; send_id={send_id}" if send_id is not None else ""
                if method.endswith("_EX1"):
                    _NATIVE_API_FORCE_LEGACY_NEXT = False
                _NATIVE_API_ACTIVATION_MESSAGE = f"Requested OPS ROOM Native API SimObject harness through {method}{packet_note}"
                return
            last_message = f"{method} returned HRESULT {int(hr)}"
        except Exception as exc:
            last_message = f"{method} exception: {type(exc).__name__}: {exc}"
    _NATIVE_API_ACTIVATION_FAILED = True
    _NATIVE_API_ACTIVATION_MESSAGE = last_message or "Native API SimObject harness activation failed"


def _update_status_from_commbus(payload_text: str) -> None:
    global _LAST_ERROR, _NATIVE_API_STATUS_LATCHED
    try:
        payload = json.loads(payload_text or "{}")
    except Exception as exc:
        _LAST_ERROR = f"CommBus status JSON parse failed: {exc}: {payload_text[:160]}"
        return
    state = str(payload.get("state") or "READY").upper()
    message = str(payload.get("message") or "OPS ROOM WASM CommBus heartbeat received")
    chart_text = str(payload.get("chart_text") or "")
    if state.startswith(("API_", "CHARTS_", "CAMERA_")) or "native API WASM system" in message or chart_text.startswith("API_READY|"):
        _NATIVE_API_STATUS_LATCHED = True
    chart_items = payload.get("chart_items") if isinstance(payload.get("chart_items"), list) else []
    with _LOCK:
        _LAST_STATUS.clear()
        _LAST_STATUS.update({
            "ok": state not in {"ERROR", "FAILED"},
            "connected": True,
            "loaded": True,
            "transport": "commbus",
            "camera_active": bool(payload.get("camera_active")),
            "chart_ready": bool(payload.get("chart_ready")),
            "chart_count": int(payload.get("chart_count") or 0),
            "state": state,
            "message": message,
            "detail": str(payload.get("detail") or ""),
            "target": str(payload.get("target") or ""),
            "match": str(payload.get("match") or "CommBus heartbeat"),
            "chart_airport": str(payload.get("chart_airport") or ""),
            "chart_text": chart_text,
            "chart_items": chart_items,
            "seq": int(payload.get("seq") or 0),
            "wasm_version": str(payload.get("version") or ""),
            "updated_at_monotonic": time.monotonic(),
            "last_error": _LAST_ERROR,
        })


def _loop() -> None:
    global _RUNNING, _LAST_ERROR, _SIMCONNECT_DLL_PATH, _SIMCONNECT_OPEN_HRESULT, _SIMCONNECT_RETRY_COUNT, _CLIENT_DATA_SUBSCRIBED, _COMMAND_DATA_READY, _COMMAND_SENT_SEQ, _COMMAND_LAST_SEND, _POSITION_DATA_READY
    if os.name != "nt":
        with _LOCK:
            _LAST_STATUS.update({"connected": False, "state": "UNSUPPORTED", "message": "Native bridge host is Windows-only"})
        return
    while _RUNNING:
        h = c_void_p()
        dll = None
        cb = None
        commbus_enabled = False
        try:
            dll_path = _dll_path()
            _SIMCONNECT_DLL_PATH = str(dll_path) if dll_path else ""
            dll = _load_dll()
            hr = dll.Open(byref(h), b"OPS ROOM Native Bridge Host ClientData", None, 0, None, 0)
            _SIMCONNECT_OPEN_HRESULT = int(hr)
            if hr != 0 or not h.value:
                _SIMCONNECT_RETRY_COUNT += 1
                _CLIENT_DATA_SUBSCRIBED = False
                _COMMAND_DATA_READY = False
                _COMMAND_SENT_SEQ = 0
                _COMMAND_LAST_SEND = 0.0
                _LAST_ERROR = f"SimConnect_Open failed {hr}"
                with _LOCK:
                    _LAST_STATUS.update({
                        "connected": False,
                        "simconnect_connected": False,
                        "state": "HOST WAITING",
                        "message": "OPS ROOM bridge host could not open SimConnect yet. Start or reload MSFS, then wait for retry.",
                        "transport": "client_data",
                    })
                time.sleep(3)
                continue
            _LAST_ERROR = ""

            required = [
                ("MapClientDataNameToID", dll.MapClientDataNameToID),
                ("CreateClientData", getattr(dll, "CreateClientData", None)),
                ("AddToClientDataDefinition", dll.AddToClientDataDefinition),
                ("RequestClientData", dll.RequestClientData),
                ("SetClientData", getattr(dll, "SetClientData", None)),
            ]
            missing = [name for name, fn in required if fn is None]
            if missing:
                _LAST_ERROR = "SimConnect.dll missing Client Data functions: " + ", ".join(missing)
                with _LOCK:
                    _LAST_STATUS.update({"connected": False, "state": "HOST ERROR", "message": _LAST_ERROR})
                time.sleep(3)
                continue

            dll.MapClientDataNameToID(h, b"OPSROOM.BRIDGE.STATUS", CID_STATUS)
            # Either side may start first. Creating the area here makes RequestClientData safe
            # even before the WASM starts publishing to it. Default permissions keep the
            # shared block writable by the WASM publisher.
            try:
                dll.CreateClientData(h, CID_STATUS, ctypes.sizeof(BridgeStatus), 0)
            except Exception:
                pass
            dll.AddToClientDataDefinition(h, DEF_STATUS, 0, ctypes.sizeof(BridgeStatus), 0.0, 0)

            # Command channel: OPS ROOM publishes, the WASM module subscribes.
            dll.MapClientDataNameToID(h, b"OPSROOM.BRIDGE.COMMAND", CID_COMMAND)
            try:
                dll.CreateClientData(h, CID_COMMAND, ctypes.sizeof(BridgeCommand), 0)
            except Exception:
                pass
            dll.AddToClientDataDefinition(h, DEF_COMMAND, 0, ctypes.sizeof(BridgeCommand), 0.0, 0)
            _COMMAND_DATA_READY = True
            _COMMAND_SENT_SEQ = 0
            _COMMAND_LAST_SEND = 0.0

            _POSITION_DATA_READY = False
            if getattr(dll, "AddToDataDefinition", None) is not None and getattr(dll, "RequestDataOnSimObject", None) is not None:
                try:
                    for datum, units in (
                        (b"PLANE LATITUDE", b"degrees"),
                        (b"PLANE LONGITUDE", b"degrees"),
                        (b"PLANE ALTITUDE", b"feet"),
                        (b"PLANE HEADING DEGREES TRUE", b"degrees"),
                        (b"PLANE ALT ABOVE GROUND", b"feet"),
                        (b"SIM ON GROUND", b"Bool"),
                    ):
                        dll.AddToDataDefinition(h, DEF_USER_POSITION, datum, units, SIMCONNECT_DATATYPE_FLOAT64, 0.0, 0)
                    _POSITION_DATA_READY = True
                except Exception as pos_exc:
                    _LAST_ERROR = f"Native bridge user-position definition setup failed: {pos_exc}"

            # Subscribe to changes and also ask once immediately. The one-shot request
            # catches the case where the standalone WASM wrote its load status before
            # the OPS ROOM host finished subscribing.
            req_hr = dll.RequestClientData(h, CID_STATUS, REQ_STATUS, DEF_STATUS, SIMCONNECT_CLIENT_DATA_PERIOD_SECOND, SIMCONNECT_CLIENT_DATA_REQUEST_FLAG_CHANGED, 0, 0, 0)
            once_hr = dll.RequestClientData(h, CID_STATUS, REQ_STATUS, DEF_STATUS, SIMCONNECT_CLIENT_DATA_PERIOD_ONCE, 0, 0, 0, 0)
            _CLIENT_DATA_SUBSCRIBED = req_hr == 0 or once_hr == 0
            if req_hr != 0 and once_hr != 0:
                _LAST_ERROR = f"RequestClientData failed {req_hr}; once request failed {once_hr}"

            # The Charts/Camera WASM is a documented system module, so it must
            # be owned by a spawned SimObject. Do not spawn immediately on
            # SimConnect open because MSFS may still be loading. The dispatch loop
            # below waits for the broker heartbeat plus a sane user-aircraft
            # position before requesting the classic SimObject harness.

            # Optional only. v0.23.18 heartbeat does not depend on CommBus because
            # some bundled SimConnect.dll builds do not export the MSFS 2024 CommBus functions.
            if dll.SubscribeToCommBusEvent is not None and dll.CallCommBusEvent is not None:
                try:
                    sub_hr = dll.SubscribeToCommBusEvent(h, EVENT_STATUS, EVENT_STATUS_NAME)
                    commbus_enabled = sub_hr == 0
                    if sub_hr != 0:
                        _LAST_ERROR = f"Optional SubscribeToCommBusEvent failed {sub_hr}"
                except Exception as exc:
                    _LAST_ERROR = f"Optional CommBus setup skipped: {exc}"

            def _cb(raw, size, ctx):
                global _NATIVE_API_ACTIVATION_FAILED, _NATIVE_API_LAST_EXCEPTION, _NATIVE_API_LAST_EXCEPTION_SEND_ID, _NATIVE_API_LAST_EXCEPTION_INDEX, _NATIVE_API_OBJECT_ID, _NATIVE_API_ACTIVATION_MESSAGE, _NATIVE_API_FORCE_LEGACY_NEXT, _LAST_ERROR
                try:
                    recv = raw.contents
                    if recv.dwID == SIMCONNECT_RECV_ID_ASSIGNED_OBJECT_ID:
                        global _NATIVE_API_OBJECT_ID, _NATIVE_API_ACTIVATION_MESSAGE
                        try:
                            class _AssignedObject(Structure):
                                _fields_ = [("dwSize", c_uint32), ("dwVersion", c_uint32), ("dwID", c_uint32), ("dwRequestID", c_uint32), ("dwObjectID", c_uint32)]
                            assigned = ctypes.cast(raw, ctypes.POINTER(_AssignedObject)).contents
                            if assigned.dwRequestID in (REQ_NATIVE_API_HARNESS_EX1, REQ_NATIVE_API_HARNESS_LEGACY, REQ_NATIVE_API_HARNESS):
                                _NATIVE_API_OBJECT_ID = int(assigned.dwObjectID)
                                _NATIVE_API_ACTIVATION_FAILED = False
                                _NATIVE_API_FORCE_LEGACY_NEXT = False
                                _NATIVE_API_ACTIVATION_MESSAGE = f"OPS ROOM Native API SimObject harness assigned object ID {int(assigned.dwObjectID)}"
                        except Exception:
                            pass
                    elif recv.dwID == SIMCONNECT_RECV_ID_EXCEPTION:
                        try:
                            class _ExceptionRecv(Structure):
                                _fields_ = [("dwSize", c_uint32), ("dwVersion", c_uint32), ("dwID", c_uint32), ("dwException", c_uint32), ("dwSendID", c_uint32), ("dwIndex", c_uint32)]
                            ex = ctypes.cast(raw, ctypes.POINTER(_ExceptionRecv)).contents
                            send_id = int(ex.dwSendID)
                            method = _NATIVE_API_CREATE_SEND_IDS.get(send_id)
                            if method:
                                _NATIVE_API_LAST_EXCEPTION = int(ex.dwException)
                                _NATIVE_API_LAST_EXCEPTION_SEND_ID = send_id
                                _NATIVE_API_LAST_EXCEPTION_INDEX = int(ex.dwIndex)
                                _NATIVE_API_ACTIVATION_FAILED = True
                                if method.endswith("_EX1") and int(ex.dwException) == 22:
                                    _NATIVE_API_FORCE_LEGACY_NEXT = True
                                _NATIVE_API_ACTIVATION_MESSAGE = f"SimConnect exception {int(ex.dwException)} ({_sim_exception_name(int(ex.dwException))}) for native API harness {method}; send_id={send_id} index={int(ex.dwIndex)}"
                            else:
                                _LAST_ERROR = f"Unrelated SimConnect exception {int(ex.dwException)} ({_sim_exception_name(int(ex.dwException))}); send_id={send_id} index={int(ex.dwIndex)}"
                        except Exception:
                            pass
                    elif recv.dwID == SIMCONNECT_RECV_ID_SIMOBJECT_DATA:
                        msg = ctypes.cast(raw, ctypes.POINTER(SimRecvSimobjectData)).contents
                        if msg.dwRequestID == REQ_USER_POSITION and msg.dwDefineCount:
                            wire = UserPositionWire.from_address(ctypes.addressof(msg.dwData))
                            _update_user_position_from_wire(wire)
                    elif recv.dwID == SIMCONNECT_RECV_ID_CLIENT_DATA:
                        msg = ctypes.cast(raw, ctypes.POINTER(SimRecvClientData)).contents
                        if msg.dwRequestID == REQ_STATUS and msg.dwDefineCount:
                            st = BridgeStatus.from_address(ctypes.addressof(msg.dwData))
                            _update_status(st)
                    elif recv.dwID == SIMCONNECT_RECV_ID_COMM_BUS and commbus_enabled:
                        event_id, text, entry_number, out_of = _commbus_text(raw, recv)
                        if event_id == EVENT_STATUS:
                            if out_of in (0, 1) or entry_number == 0:
                                _update_status_from_commbus(text)
                except Exception as exc:
                    _LAST_ERROR = f"bridge dispatch callback failed: {exc}"
            cb = CALLBACK(_cb)

            with _LOCK:
                _LAST_STATUS.update({
                    "connected": True,
                    "simconnect_connected": True,
                    "loaded": False,
                    "state": "HOST CONNECTED",
                    "transport": "client_data",
                    "message": "Bridge host connected to SimConnect. Waiting for WASM load status.",
                    "commbus_optional": commbus_enabled,
                    "client_data_subscribed": _CLIENT_DATA_SUBSCRIBED,
                    "command_data_ready": _COMMAND_DATA_READY,
                })

            last_once_request = 0.0
            last_user_position_request = 0.0
            while _RUNNING:
                try:
                    dll.CallDispatch(h, cb, None)
                    now = time.monotonic()
                    if now - last_once_request >= 2.0:
                        last_once_request = now
                        try:
                            dll.RequestClientData(h, CID_STATUS, REQ_STATUS, DEF_STATUS, SIMCONNECT_CLIENT_DATA_PERIOD_ONCE, 0, 0, 0, 0)
                        except Exception as req_exc:
                            _LAST_ERROR = f"RequestClientData once retry failed: {req_exc}"
                    if now - last_user_position_request >= 1.0:
                        last_user_position_request = now
                        _request_user_position(dll, h)
                    _activate_native_api_harness(dll, h, force=False)
                    _send_command_data(dll, h, False)
                except Exception as exc:
                    _LAST_ERROR = f"CallDispatch failed: {exc}"
                    break
                time.sleep(0.05)
        except Exception as exc:
            _LAST_ERROR = str(exc)
            with _LOCK:
                _LAST_STATUS.update({"connected": False, "state": "HOST ERROR", "message": _LAST_ERROR})
            time.sleep(3)
        finally:
            if dll is not None and h.value:
                try:
                    if commbus_enabled and getattr(dll, "UnsubscribeToCommBusEvent", None) is not None:
                        dll.UnsubscribeToCommBusEvent(h, EVENT_STATUS)
                except Exception:
                    pass
                try:
                    dll.Close(h)
                except Exception:
                    pass

def start() -> None:
    global _RUNNING, _THREAD
    if _THREAD and _THREAD.is_alive():
        return
    _RUNNING = True
    _THREAD = threading.Thread(target=_loop, name="OpsRoom-NativeBridgeHost", daemon=True)
    _THREAD.start()


def stop() -> None:
    global _RUNNING
    _RUNNING = False


def status() -> dict[str, Any]:
    with _LOCK:
        data = dict(_LAST_STATUS)
    age = None
    if data.get("updated_at_monotonic"):
        age = round(time.monotonic() - float(data["updated_at_monotonic"]), 1)
    data["age_seconds"] = age
    data["thread_running"] = bool(_THREAD and _THREAD.is_alive())
    data["last_error"] = _LAST_ERROR
    data["simconnect_dll_path"] = _SIMCONNECT_DLL_PATH
    data["simconnect_open_hresult"] = _SIMCONNECT_OPEN_HRESULT
    data["simconnect_retry_count"] = _SIMCONNECT_RETRY_COUNT
    data["client_data_subscribed"] = _CLIENT_DATA_SUBSCRIBED
    data["command_data_ready"] = _COMMAND_DATA_READY
    data["command_sent_seq"] = _COMMAND_SENT_SEQ
    data["native_api_activation_attempted"] = _NATIVE_API_ACTIVATION_ATTEMPTED
    data["native_api_activation_hr"] = _NATIVE_API_ACTIVATION_HR
    data["native_api_activation_message"] = _NATIVE_API_ACTIVATION_MESSAGE
    data["native_api_object_id"] = _NATIVE_API_OBJECT_ID
    data["native_api_activation_failed"] = _NATIVE_API_ACTIVATION_FAILED
    data["native_api_last_exception"] = _NATIVE_API_LAST_EXCEPTION
    data["native_api_last_exception_name"] = _sim_exception_name(_NATIVE_API_LAST_EXCEPTION) if _NATIVE_API_LAST_EXCEPTION is not None else ""
    data["native_api_last_exception_send_id"] = _NATIVE_API_LAST_EXCEPTION_SEND_ID
    data["native_api_last_exception_index"] = _NATIVE_API_LAST_EXCEPTION_INDEX
    data["native_api_last_create_method"] = _NATIVE_API_LAST_CREATE_METHOD
    data["native_api_last_create_send_id"] = _NATIVE_API_LAST_CREATE_SEND_ID
    data["native_api_force_legacy_next"] = _NATIVE_API_FORCE_LEGACY_NEXT
    data["native_api_status_latched"] = _NATIVE_API_STATUS_LATCHED
    data["native_api_loaded"] = _status_is_from_native_api()
    data["position_data_ready"] = _POSITION_DATA_READY
    data["user_position_request_count"] = _USER_POSITION_REQUEST_COUNT
    data["user_position_last_request_hr"] = _USER_POSITION_LAST_REQUEST_HR
    data["user_position_last_request_age_seconds"] = round(time.monotonic() - _USER_POSITION_LAST_REQUEST_AT, 1) if _USER_POSITION_LAST_REQUEST_AT else None
    data["user_position_last_request_message"] = _USER_POSITION_LAST_REQUEST_MESSAGE
    data["native_activation_gate"] = _NATIVE_API_ACTIVATION_GATE
    data["native_activation_position_source"] = _USER_POSITION_SOURCE
    data["native_activation_position_age_seconds"] = round(time.monotonic() - _USER_POSITION_UPDATED_AT, 1) if _USER_POSITION_UPDATED_AT else None
    data["native_activation_position_message"] = _USER_POSITION_MESSAGE
    data["native_activation_fallback_position_message"] = _FALLBACK_POSITION_MESSAGE
    if _USER_POSITION:
        data["native_activation_position"] = {
            "lat": round(float(_USER_POSITION.get("lat", 0.0)), 6),
            "lon": round(float(_USER_POSITION.get("lon", 0.0)), 6),
            "altitude_ft": round(float(_USER_POSITION.get("altitude_ft", 0.0)), 1),
            "heading_deg": round(float(_USER_POSITION.get("heading_deg", 0.0)), 1),
        }
    if data.get("state") == "HOST CONNECTED" and not data.get("loaded"):
        data["ready"] = False
    else:
        data["ready"] = bool(data.get("loaded") and data.get("connected"))
    return data


def request_charts(airport: str) -> dict[str, Any]:
    global _CHART_SEQ, _CHART_AIRPORT, _LAST_COMMAND_SIGNATURE
    airport = "".join(ch for ch in str(airport or "").upper() if ch.isalnum())[:7]
    with _LOCK:
        _CHART_SEQ += 1
        _CHART_AIRPORT = airport
        _LAST_COMMAND_SIGNATURE = ""
    data = status()
    data.update({
        "chart_ready": bool(data.get("chart_ready")),
        "chart_airport": airport,
        "requested_airport": airport,
        "chart_request_seq": _CHART_SEQ,
        "native_charts_enabled": True,
        "state": "CHARTS_REQUESTED",
        "message": f"Chart request for {airport} queued for OPS ROOM native WASM API system.",
    })
    return data
