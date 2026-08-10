"""Query all SimObjects near a point via RequestDataOnSimObjectType and print
position + heading for each. Used to find the heading of the user's manually
placed X (ground truth) and to see where spawned objects actually landed.

Usage: python tools/query_simobjects.py [lat] [lon] [radius_m]
"""
import ctypes
import sys
import time

DLL = r"C:\MSFS 2024 SDK\SimConnect SDK\lib\SimConnect.dll"
dll = ctypes.WinDLL(DLL)

LAT = float(sys.argv[1]) if len(sys.argv) > 1 else 51.151
LON = float(sys.argv[2]) if len(sys.argv) > 2 else -0.173
RADIUS = float(sys.argv[3]) if len(sys.argv) > 3 else 1200.0

# SIMCONNECT_RECV_ID values
_RECV_ID_EXCEPTION = 1
_RECV_ID_OPEN = 2
_RECV_ID_SIMOBJECT_DATA_BYTYPE = 9

# SIMCONNECT_DATATYPE_FLOAT64 = 7
_DATATYPE_FLOAT64 = 7
# SIMCONNECT_PERIOD_ONCE = 0 ; flags 0
# SIMCONNECT_SIMOBJECT_TYPE_ALL = 1

REQ = 0x1000
DEF = 0x2000

_CB = ctypes.WINFUNCTYPE(None, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint32, ctypes.c_void_p)

found = []


@_CB
def _on_dispatch(p_data, cb_data, p_context):
    try:
        data = p_data
        dw_size = data[0] | (data[1] << 8) | (data[2] << 16) | (data[3] << 24)
        dw_id = data[8] | (data[9] << 8) | (data[10] << 16) | (data[11] << 24)
        if dw_id == _RECV_ID_SIMOBJECT_DATA_BYTYPE:
            # header: dwSize(4) dwVersion(4) dwID(4) dwRequestID(4) dwObjectID(4)
            req = data[12] | (data[13] << 8) | (data[14] << 16) | (data[15] << 24)
            obj = data[16] | (data[17] << 8) | (data[18] << 16) | (data[19] << 24)
            # payload: 4 doubles (lat, lon, alt_ft, true_heading)
            vals = []
            for k in range(4):
                raw = bytes(data[20 + k * 8: 28 + k * 8])
                vals.append(ctypes.c_double.from_buffer_copy(raw).value)
            found.append({"req": req, "obj": obj, "lat": vals[0], "lon": vals[1],
                          "alt": vals[2], "hdg": vals[3]})
        elif dw_id == _RECV_ID_EXCEPTION:
            exc = data[12] | (data[13] << 8) | (data[14] << 16) | (data[15] << 24)
            print(f"  [exception {exc}]", flush=True)
    except Exception:
        pass


def main() -> int:
    handle = ctypes.c_void_p()
    hr = dll.SimConnect_Open(ctypes.byref(handle), b"OpsRoom Object Query", None, 0, None, 0)
    if hr != 0:
        print(f"SimConnect_Open failed hr={int(hr)}")
        return 1
    print(f"connected; querying objects within {RADIUS:.0f} m of {LAT:.5f}, {LON:.5f}", flush=True)

    add_def = dll.SimConnect_AddToDataDefinition
    add_def.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
                        ctypes.c_char_p, ctypes.c_int, ctypes.c_float, ctypes.c_uint32]
    add_def.restype = ctypes.c_long
    for i, (name, units) in enumerate([
            (b"PLANE LATITUDE", b"degrees"),
            (b"PLANE LONGITUDE", b"degrees"),
            (b"PLANE ALTITUDE", b"feet"),
            (b"PLANE HEADING DEGREES TRUE", b"degrees")]):
        hr = add_def(handle, DEF, name, units, _DATATYPE_FLOAT64, 0.0, 0xFFFFFFFF)
        if hr != 0:
            print(f"AddToDataDefinition {name} failed hr={int(hr)}")

    req_type = dll.SimConnect_RequestDataOnSimObjectType
    req_type.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                         ctypes.c_uint32, ctypes.c_uint32]
    req_type.restype = ctypes.c_long
    hr = req_type(handle, REQ, DEF, int(RADIUS), 1)  # SIMCONNECT_SIMOBJECT_TYPE_ALL
    print(f"RequestDataOnSimObjectType hr={int(hr)}", flush=True)

    dispatch = dll.SimConnect_CallDispatch
    dispatch.argtypes = [ctypes.c_void_p, _CB, ctypes.c_void_p]
    deadline = time.time() + 8.0
    last = 0
    while time.time() < deadline:
        dispatch(handle, _on_dispatch, None)
        time.sleep(0.05)
        if len(found) != last:
            print(f"  ... {len(found)} objects so far", flush=True)
            last = len(found)

    print(f"\n=== {len(found)} sim objects near point ===")
    for o in sorted(found, key=lambda x: (x["lat"] - LAT) ** 2 + (x["lon"] - LON) ** 2):
        print(f"  obj={o['obj']:#x} ({o['obj']}) lat={o['lat']:.6f} lon={o['lon']:.6f} "
              f"alt={o['alt']:.1f} hdg={o['hdg']:.2f}")

    dll.SimConnect_Close(handle)
    return 0


if __name__ == "__main__":
    sys.exit(main())
