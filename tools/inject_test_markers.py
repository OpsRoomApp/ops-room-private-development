"""Inject test closure markers at EGKK - corrected set (v0.25.71).

Uses the app's OWN plan_markers logic (with all v0.25.71 fixes) for a
runway 26L closure + taxiway Y closure at the aircraft anchor, so what is
spawned is exactly what the app would deploy:

  - Runway X on 26L at the numbering, SNAPPED onto the centreline (the raw
    LLA the user picked sits ~50 m south of it - in-sim report "way off the
    centerline"); v0.25.75: heading faces the LIGHTED X's lit face at the
    aircraft anchor (bearing from the X to the anchor + 90) so the vertical
    sign reads correctly from the cockpit (the user's manual X is the
    ground truth).
  - Taxiway Y X on the sim-truth line (user markers d8c0000/d8c4000) +
    entry X's (redundant one dropped by code).
  - Full hold-short barrier tier for 26L (v0.25.71): single orange Type III
    barricade rows PARALLEL to the runway edge, sized to span the full
    taxiway (width / sin(entry angle)), pushed out to >= 6 m lateral so no
    barricade straddles the runway, edge-to-edge 3.7 m spacing, nearest
    -first ordering.
  - v0.25.75: all objects (barricades + lighted X included) are now
    Misc/StaticObject in the package, the category of the plain X markers
    that NEVER move - so no SIM DISABLED writes are needed (the old
    GroundVehicle category drove the AI vehicles away no matter what; the
    writes are kept as a harmless no-op for safety).

Usage: python -u tools/inject_test_markers.py
Kill the process (or let it die) to have MSFS reap all spawned objects.
"""
import ctypes
import sys
import time

DLL = r"C:\Users\badgu\AppData\Roaming\Python\Python312\site-packages\SimConnect\SimConnect.dll"
dll = ctypes.WinDLL(DLL)

HANDLE = ctypes.c_void_p

# SIMCONNECT_RECV_ID_ASSIGNED_OBJECT_ID = 12; struct fields after the 12-byte
# header: dwRequestID @12, dwObjectID @16.
_RECV_ID_ASSIGNED_OBJECT_ID = 12
# SIMCONNECT_DATATYPE_INT32 = 1; SIMCONNECT_UNUSED = 0xFFFFFFFF.
_DATATYPE_INT32 = 1
_UNUSED = 0xFFFFFFFF
# Client-side data definition ID for SIM DISABLED (outside lib ranges).
_SIM_DISABLED_DEF = 0x00007FF1

# v0.25.75: all objects are Misc/StaticObject now (the parked category), so
# SIM DISABLED is a no-op - kept empty so the keep-alive loop does nothing.
_GROUND_VEHICLE_TITLES: set[str] = set()

#: request_id -> object_id, filled by the dispatch callback.
ASSIGNED: dict[int, int] = {}

_CB = ctypes.WINFUNCTYPE(None, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint32, ctypes.c_void_p)


@_CB
def _on_dispatch(p_data, cb_data, p_context):
    """Capture SIMCONNECT_RECV_ID_ASSIGNED_OBJECT_ID (request_id -> object_id)."""
    try:
        data = p_data
        dw_id = data[8] | (data[9] << 8) | (data[10] << 16) | (data[11] << 24)
        if dw_id == _RECV_ID_ASSIGNED_OBJECT_ID:
            req = data[12] | (data[13] << 8) | (data[14] << 16) | (data[15] << 24)
            obj = data[16] | (data[17] << 8) | (data[18] << 16) | (data[19] << 24)
            ASSIGNED[req] = obj
    except Exception:
        pass


class _InitPosition(ctypes.Structure):
    _fields_ = [
        ("Latitude", ctypes.c_double),
        ("Longitude", ctypes.c_double),
        ("Altitude", ctypes.c_double),
        ("Pitch", ctypes.c_double),
        ("Bank", ctypes.c_double),
        ("Heading", ctypes.c_double),
        ("OnGround", ctypes.c_uint32),
        ("Airspeed", ctypes.c_uint32),
    ]


def _bind_set_sim_disabled() -> tuple | None:
    """Bind SimConnect_AddToDataDefinition + SetDataOnSimObject on the raw DLL."""
    add_def = getattr(dll, "SimConnect_AddToDataDefinition", None)
    set_data = getattr(dll, "SimConnect_SetDataOnSimObject", None)
    if add_def is None or set_data is None:
        return None
    try:
        add_def.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_float, ctypes.c_uint32]
        add_def.restype = ctypes.c_long
        set_data.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        set_data.restype = ctypes.c_long
    except (AttributeError, TypeError):
        return None
    return add_def, set_data


# SIMCONNECT_RECV_ID_SIMOBJECT_DATA = 8; payload doubles start at byte 20.
_RECV_ID_SIMOBJECT_DATA = 8
USER_POS: dict[str, float] = {}


@_CB
def _on_user_pos(p_data, cb_data, p_context):
    """Capture the user aircraft position (PLANE LATITUDE/LONGITUDE/ALT/HDG)."""
    try:
        data = p_data
        dw_id = data[8] | (data[9] << 8) | (data[10] << 16) | (data[11] << 24)
        if dw_id == _RECV_ID_SIMOBJECT_DATA:
            vals = []
            for k in range(4):
                raw = bytes(data[20 + k * 8: 28 + k * 8])
                vals.append(ctypes.c_double.from_buffer_copy(raw).value)
            USER_POS["lat"], USER_POS["lon"], USER_POS["alt"], USER_POS["hdg"] = vals
    except Exception:
        pass


def _fetch_user_position(handle) -> tuple[float, float] | None:
    """Read the USER aircraft lat/lon via RequestDataOnSimObject (id 0).

    v0.25.75: the lighted X's heading faces the aircraft anchor, so the
    anchor must be the pilot's CURRENT position, not a hardcoded one.
    """
    try:
        add_def = dll.SimConnect_AddToDataDefinition
        add_def.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
                            ctypes.c_char_p, ctypes.c_int, ctypes.c_float, ctypes.c_uint32]
        add_def.restype = ctypes.c_long
        for i, (name, units) in enumerate([(b"PLANE LATITUDE", b"degrees"),
                                           (b"PLANE LONGITUDE", b"degrees"),
                                           (b"PLANE ALTITUDE", b"feet"),
                                           (b"PLANE HEADING DEGREES TRUE", b"degrees")]):
            add_def(handle, 0x4001 + i, name, units, _DATATYPE_INT32, 0.0, _UNUSED)
        req = dll.SimConnect_RequestDataOnSimObject
        req.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                        ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
        req.restype = ctypes.c_long
        hr = req(handle, 0x5001, 0, 0x4001, 0, 0, 0, 0, 0)  # user object, once
        if int(hr) != 0:
            return None
        deadline = time.time() + 3.0
        while time.time() < deadline and "lat" not in USER_POS:
            dll.SimConnect_CallDispatch(handle, _on_user_pos, None)
            time.sleep(0.02)
        if "lat" in USER_POS and USER_POS["lat"] != 0.0:
            return (USER_POS["lat"], USER_POS["lon"])
    except Exception as exc:
        print(f"  user position fetch failed: {exc}")
    return None


def main() -> int:
    handle = HANDLE()
    hr = dll.SimConnect_Open(ctypes.byref(handle), b"OpsRoom Marker Inject", None, 0, None, 0)
    if hr != 0:
        print(f"OPEN FAILED HRESULT {hex(hr & 0xFFFFFFFF)}")
        return 1
    print("SimConnect open OK")
    dll.SimConnect_CallDispatch.argtypes = [ctypes.c_void_p, _CB, ctypes.c_void_p]
    dll.SimConnect_CallDispatch.restype = None

    create_ex1 = getattr(dll, "SimConnect_AICreateSimulatedObject_EX1", None)
    create_legacy = getattr(dll, "SimConnect_AICreateSimulatedObject", None)
    creators = []
    if create_ex1 is not None:
        create_ex1.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, _InitPosition, ctypes.c_uint32]
        create_ex1.restype = ctypes.c_long
        creators.append(("EX1", create_ex1))
    if create_legacy is not None:
        create_legacy.argtypes = [ctypes.c_void_p, ctypes.c_char_p, _InitPosition, ctypes.c_uint32]
        create_legacy.restype = ctypes.c_long
        creators.append(("LEGACY", create_legacy))
    if not creators:
        print("NO CREATORS")
        return 1

    # ── Build the plan exactly like the app would (aircraft anchor) ────────
    sys.path.insert(0, r"E:\Ops Room Project\OPS_ROOM_v0_24_106_PUBLIC_BETA_BLACK_BOX_RC4_SOURCE_READY\OPS_ROOM_v0_24_106_SOURCE\opsroom-app\source")
    from app import closure_markers as cm  # noqa: E402
    from app import navdata  # noqa: E402

    # v0.25.75: anchor = the pilot's CURRENT position (the X faces it, and
    # the taxiway X sits on the segment nearest the pilot). Fall back to the
    # known EGKK parking spot if the sim won't report it.
    anchor = _fetch_user_position(handle) or (51.147611, -0.172481)
    print(f"anchor (user aircraft): {anchor[0]:.6f}, {anchor[1]:.6f}")
    plan = cm.plan_markers(
        [
            {"airport_icao": "EGKK", "kind": "runway", "ref": "26L"},
            {"airport_icao": "EGKK", "kind": "taxiway", "ref": "Y"},
        ],
        anchor=anchor,
    )
    placed = plan["placed"]
    print(f"plan: {len(placed)} placements")

    # Override the runway X with the user-confirmed numbering position,
    # SNAPPED onto the 26L centreline (the raw LLA 51.151,-0.173 sits ~50 m
    # south of the centreline - in-sim report "way off the centerline").
    rwy = navdata.runway_full("EGKK", "26L")
    for p in [x for x in placed if x["kind"] == "runway"]:
        proj = cm._project_onto_runway(51.151, -0.173, rwy)
        if proj:
            xlat, xlon = cm._back_to_latlon(rwy, proj[0], 0.0)
            p["lat"] = round(xlat, 6)
            p["lon"] = round(xlon, 6)
            print(f"runway X snapped to centreline: {xlat:.6f}, {xlon:.6f}")
        p["altitude_ft"] = 195.507
    # Override the taxiway Y on-line X to the SIM-TRUTH line (user markers).
    for p in [x for x in placed if x["kind"] == "taxiway" and x.get("placement") == "taxiway-geometry"]:
        p["lat"] = 51.148346
        p["lon"] = -0.172737

    sim_disabled = _bind_set_sim_disabled()
    spawned = 0

    def set_sim_disabled(request_id: int, title: str) -> None:
        """Write SIM DISABLED=1 on a spawned GroundVehicle so it parks in place."""
        if sim_disabled is None or title not in _GROUND_VEHICLE_TITLES:
            return
        oid = ASSIGNED.get(request_id)
        if not oid:
            return
        add_def, set_data = sim_disabled
        try:
            add_def(handle, _SIM_DISABLED_DEF, b"SIM DISABLED", b"Bool", _DATATYPE_INT32, 0.0, _UNUSED)
            value = ctypes.c_int32(1)
            hr = set_data(handle, oid, _SIM_DISABLED_DEF, 0, 0, ctypes.sizeof(value), ctypes.byref(value))
            print(f"  SIM DISABLED {title} obj={oid} hr={int(hr)}")
        except Exception as exc:
            print(f"  SIM DISABLED FAILED {title}: {exc}")

    def spawn(title: str, lat: float, lon: float, alt: float, hdg: float, tag: str = "") -> None:
        nonlocal spawned
        pos = _InitPosition(Latitude=float(lat), Longitude=float(lon), Altitude=float(alt),
                            Pitch=0.0, Bank=0.0, Heading=float(hdg), OnGround=1, Airspeed=0)
        tb = str(title).encode("utf-8")
        req = 9000 + spawned
        for method, create in creators:
            try:
                if method == "EX1":
                    r = create(handle, ctypes.c_char_p(tb), ctypes.c_char_p(b""), pos, ctypes.c_uint32(req))
                else:
                    r = create(handle, ctypes.c_char_p(tb), pos, ctypes.c_uint32(req))
            except Exception as exc:
                print(f"  {method} exception: {exc}")
                continue
            if int(r) == 0:
                spawned += 1
                # Pump the dispatch briefly so the sim's ASSIGNED_OBJECT_ID
                # notification arrives (it carries the object ID we need for
                # the SIM DISABLED write).
                deadline = time.time() + 2.0
                while time.time() < deadline and req not in ASSIGNED:
                    dll.SimConnect_CallDispatch(handle, _on_dispatch, None)
                    time.sleep(0.02)
                set_sim_disabled(req, title)
                print(f"  SPAWNED {title} {tag} @ {lat:.6f},{lon:.6f} alt={alt:.0f} hdg={hdg:.1f}")
                return
        print(f"  FAILED {title} {tag}")

    for p in placed:
        tag = f"[{p.get('placement')} {p.get('ref') or ''}]"
        spawn(p["object"], p["lat"], p["lon"], p.get("altitude_ft") or 0.0, p.get("heading_deg") or 0.0, tag)

    print(f"Total spawned: {spawned}")
    # v0.25.71: re-apply SIM DISABLED ~2.5 s after the last spawn. Some MSFS
    # 2024 builds re-enable the vehicle AI a moment after creation (the first
    # write can race the object's initialisation), so a second pass after the
    # dust settles parks anything that started moving.
    print("Re-applying SIM DISABLED to all spawned GroundVehicles...")
    time.sleep(2.5)
    reapplied = 0
    for req_id, oid in list(ASSIGNED.items()):
        add_def, set_data = sim_disabled
        try:
            add_def(handle, _SIM_DISABLED_DEF, b"SIM DISABLED", b"Bool", _DATATYPE_INT32, 0.0, _UNUSED)
            value = ctypes.c_int32(1)
            hr = set_data(handle, oid, _SIM_DISABLED_DEF, 0, 0, ctypes.sizeof(value), ctypes.byref(value))
            if int(hr) == 0:
                reapplied += 1
        except Exception:
            pass
    print(f"SIM DISABLED re-applied to {reapplied} object(s)")
    # v0.25.71: the one-shot write (and a single 2.5 s re-apply) did NOT hold
    # - MSFS 2024 re-enables the vehicle AI on a cycle, so the barricades
    # kept driving away (in-sim report: "barricades still moving"). Keep
    # re-writing SIM DISABLED=1 every 3 s for the life of the session.
    print("Keeping SimConnect session alive - re-applying SIM DISABLED every 3s (Ctrl+C to stop)...")
    try:
        while True:
            dll.SimConnect_CallDispatch(handle, _on_dispatch, None)
            time.sleep(3.0)
            for req_id, oid in list(ASSIGNED.items()):
                try:
                    add_def, set_data = sim_disabled
                    add_def(handle, _SIM_DISABLED_DEF, b"SIM DISABLED", b"Bool", _DATATYPE_INT32, 0.0, _UNUSED)
                    value = ctypes.c_int32(1)
                    set_data(handle, oid, _SIM_DISABLED_DEF, 0, 0, ctypes.sizeof(value), ctypes.byref(value))
                except Exception:
                    pass
    except KeyboardInterrupt:
        pass
    finally:
        dll.SimConnect_Close(handle)
    return 0


if __name__ == "__main__":
    sys.exit(main())
