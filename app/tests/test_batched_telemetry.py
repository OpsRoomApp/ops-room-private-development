"""Stage-2 batched SimConnect reader tests (v0.25.75).

Pins the one-request batch machinery (definition build, indexed SimVar name
baking, dispatch-response parsing, weights unit handling, per-var fallback)
and the heartbeat-cache completion-time stamp without needing a live sim.

The live on-sim verification (measured ~27 Hz minimal, ~30 Hz FSUIPC, weights
in pounds) is covered by the simulation harness and the fix-list checklist.
"""

from __future__ import annotations

import threading
import time
import unittest
from ctypes import POINTER, c_double, c_void_p, cast
from typing import Any

from app import simconnect_position as scp
from app import telemetry_provider as tp


class _EnumLike:
    def __init__(self, value: int) -> None:
        self.value = value

    def __repr__(self) -> str:  # pragma: no cover
        return f"SIMCONNECT_DATA_REQUEST_ID.Request{self.value}"


class _FakeDll:
    def __init__(self) -> None:
        self.defined: list[tuple[Any, Any]] = []

    def AddToDataDefinition(self, _h: Any, _def_id: Any, simvar: bytes, units: bytes, _dtype: Any, _a: Any, _b: Any) -> int:
        self.defined.append((simvar, units))
        return 0

    def RequestDataOnSimObjectType(self, _h: Any, _req_id: Any, _def_id: Any, _a: Any, _b: Any) -> int:
        return 0


class _FakeSm:
    def __init__(self) -> None:
        self.dll = _FakeDll()
        self.hSimConnect = 0
        self.handle_simobject_event: Any = None
        self._ops_batch_handler_installed = False
        self._counter = 0

    def new_def_id(self) -> _EnumLike:
        self._counter += 1
        return _EnumLike(self._counter)

    def new_request_id(self) -> _EnumLike:
        self._counter += 1
        return _EnumLike(self._counter)

    def IsHR(self, _hr: int, _value: int) -> bool:
        return True


class _FakeReq:
    def __init__(self, simvar: bytes, units: bytes) -> None:
        self.definitions = [(simvar, units)]


class _FakeAq:
    TABLE: dict[str, tuple[bytes, bytes]] = {
        "PLANE_LATITUDE": (b"PLANE LATITUDE", b"Degrees"),
        "PLANE_LONGITUDE": (b"PLANE LONGITUDE", b"Degrees"),
        "PLANE_ALTITUDE": (b"PLANE ALTITUDE", b"Feet"),
        "PRESSURE_ALTITUDE": (b"PRESSURE ALTITUDE", b"Meters"),
        "AIRSPEED_INDICATED": (b"AIRSPEED INDICATED", b"Knots"),
        "GROUND_VELOCITY": (b"GROUND VELOCITY", b"Knots"),
        "TOTAL_WEIGHT": (b"TOTAL WEIGHT", b"Pounds"),
        "MAX_GROSS_WEIGHT": (b"MAX GROSS WEIGHT", b"Pounds"),
        "EMPTY_WEIGHT": (b"EMPTY WEIGHT", b"Pounds"),
        "SIM_ON_GROUND": (b"SIM ON GROUND", b"Bool"),
        "GENERAL_ENG_COMBUSTION:index": (b"GENERAL ENG COMBUSTION:index", b"Bool"),
        "TURB_ENG_REVERSE_NOZZLE_PERCENT:index": (b"TURB ENG REVERSE NOZZLE PERCENT:index", b"Percent"),
        # Intentionally absent: INDICATED_ALTITUDE_CALIBRATED -> must be skipped.
    }

    def find(self, name: str) -> Any:
        key = name
        if ":" in name and not name.endswith(":index"):
            key = name.split(":", 1)[0] + ":index"
        entry = self.TABLE.get(key)
        if entry is None:
            return None
        if ":" in name and not name.endswith(":index"):
            index = name.split(":", 1)[1]
            simvar = entry[0].replace(b":index", b":" + index.encode())
            return _FakeReq(simvar, entry[1])
        return _FakeReq(*entry)

    def get(self, _name: str) -> Any:
        return None


def _values_dict() -> dict[str, Any]:
    return {
        "PLANE_LATITUDE": 51.47, "PLANE_LONGITUDE": -0.46, "PLANE_ALTITUDE": 1234.0,
        "INDICATED_ALTITUDE": 1200.0, "PRESSURE_ALTITUDE": 380.0,
        "AIRSPEED_INDICATED": 250.0, "GROUND_VELOCITY": 260.0,
        "AIRSPEED_TRUE": 265.0, "AIRSPEED_MACH": 0.42,
        "PLANE_HEADING_DEGREES_MAGNETIC": 90.0, "PLANE_HEADING_DEGREES_GYRO": 91.0,
        "GPS_GROUND_MAGNETIC_TRACK": 92.0, "VERTICAL_SPEED": 500.0,
        "PLANE_ALT_ABOVE_GROUND": 1150.0, "RADIO_HEIGHT": 1150.0,
        "PLANE_PITCH_DEGREES": 2.0, "PLANE_BANK_DEGREES": 0.0, "G_FORCE": 1.0,
        "SIM_ON_GROUND": 0.0, "FLAPS_HANDLE_INDEX": 1.0, "GEAR_TOTAL_PCT_EXTENDED": 0.0,
        "SPOILERS_HANDLE_POSITION": 0.0, "FLAPS_HANDLE_PERCENT": 0.0,
        "AMBIENT_WIND_VELOCITY": 15.0, "AMBIENT_WIND_DIRECTION": 260.0, "SIMULATION_RATE": 1.0,
        "IS_LATITUDE_LONGITUDE_FREEZE_ON": 0.0, "IS_SLEW_ACTIVE": 0.0,
        "STALL_WARNING": 0.0, "OVERSPEED_WARNING": 0.0, "BRAKE_PARKING_POSITION": 0.0,
        "VELOCITY_BODY_X": 0.0, "VELOCITY_BODY_Y": 0.0, "VELOCITY_BODY_Z": 0.0,
        "GENERAL_ENG_COMBUSTION:1": 1.0, "GENERAL_ENG_COMBUSTION:2": 1.0,
        "GENERAL_ENG_COMBUSTION:3": 0.0, "GENERAL_ENG_COMBUSTION:4": 0.0,
        "TURB_ENG_REVERSE_NOZZLE_PERCENT:1": 0.0, "TURB_ENG_REVERSE_NOZZLE_PERCENT:2": 0.0,
        "TOTAL_WEIGHT": 314851.0, "EMPTY_WEIGHT": 266759.0, "MAX_GROSS_WEIGHT": 513676.0,
    }


class BatchDefinition(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _FakeSm()
        self.aq = _FakeAq()
        self._old_state = dict(scp._BATCH_STATE)
        scp._BATCH_STATE.update({"sm_id": None, "def_id": None, "request_id": None, "names": [], "result": None, "done": None, "backoff_until": 0.0})

    def tearDown(self) -> None:
        scp._BATCH_STATE.update(self._old_state)

    def test_ensure_builds_one_definition_and_bakes_indexed_names(self) -> None:
        ok = scp._batch_ensure(self.sm, self.aq)
        self.assertTrue(ok)
        names = scp._BATCH_STATE["names"]
        self.assertIn("PLANE_LATITUDE", names)
        # Unknown SimVar is skipped without failing the whole batch.
        self.assertNotIn("INDICATED_ALTITUDE_CALIBRATED", names)
        # Indexed SimVars are defined with the concrete index baked in.
        defined_bytes = [simvar for simvar, _units in self.sm.dll.defined]
        self.assertIn(b"GENERAL ENG COMBUSTION:1", defined_bytes)
        self.assertIn(b"TURB ENG REVERSE NOZZLE PERCENT:2", defined_bytes)
        # Pounds-declared weights -> no slug conversion.
        self.assertFalse(scp._BATCH_STATE.get("weights_in_slugs"))
        # Definitions are reused within the same session.
        self.assertTrue(scp._batch_ensure(self.sm, self.aq))

    def test_ensure_detects_slug_weights(self) -> None:
        self.aq.TABLE = dict(self.aq.TABLE)
        self.aq.TABLE["TOTAL_WEIGHT"] = (b"TOTAL WEIGHT", b"Slugs")
        ok = scp._batch_ensure(self.sm, self.aq)
        self.assertTrue(ok)
        self.assertTrue(scp._BATCH_STATE.get("weights_in_slugs"))

    def test_read_returns_none_when_not_ready_or_backed_off(self) -> None:
        self.assertIsNone(scp._batch_read(self.sm))  # no definition yet
        scp._batch_ensure(self.sm, self.aq)
        scp._BATCH_STATE["backoff_until"] = time.monotonic() + 60.0
        self.assertIsNone(scp._batch_read(self.sm))  # backoff skips instantly


class BatchDispatch(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _FakeSm()
        self.aq = _FakeAq()
        self._old_state = dict(scp._BATCH_STATE)
        scp._batch_ensure(self.sm, self.aq)
        scp._BATCH_STATE["request_id"] = _EnumLike(7)

    def tearDown(self) -> None:
        scp._BATCH_STATE.update(self._old_state)

    def _obj_data(self, request_id: int, count: int, values: list[float]) -> Any:
        class _Obj:
            pass
        obj = _Obj()
        obj.dwRequestID = request_id
        obj.dwDefineCount = count
        arr = (c_double * len(values))(*values)
        obj.dwData = cast(arr, c_void_p)
        return obj

    def test_handler_parses_batch_response(self) -> None:
        done = scp._BATCH_STATE["done"]
        names = scp._BATCH_STATE["names"]
        values = [float(i) for i in range(len(names))]
        obj = self._obj_data(7, len(names), values)
        self.sm.handle_simobject_event(obj)
        self.assertTrue(done.is_set())
        self.assertEqual(scp._BATCH_STATE["result"], values)

    def test_handler_delegates_non_batch_request(self) -> None:
        delegated: list[int] = []
        orig = self.sm.handle_simobject_event

        def delegating(pObjData: Any) -> None:
            delegated.append(int(pObjData.dwRequestID))
            orig(pObjData)

        self.sm.handle_simobject_event = delegating
        obj = self._obj_data(99, 1, [1.0])
        self.sm.handle_simobject_event(obj)
        self.assertEqual(delegated, [99])


class MinimalBatchSample(unittest.TestCase):
    def setUp(self) -> None:
        self.sm = _FakeSm()
        self.aq = _FakeAq()
        self._old_ensure = scp._ensure_session
        self._old_read = scp._batch_read
        self._old_diag = scp.simconnect_diagnostics
        self._old_state = dict(scp._BATCH_STATE)
        scp._ensure_session = lambda _d: (self.sm, self.aq)
        scp.simconnect_diagnostics = lambda: {"dll_path": "C:/fake/SimConnect.dll"}

    def tearDown(self) -> None:
        scp._ensure_session = self._old_ensure
        scp._batch_read = self._old_read
        scp.simconnect_diagnostics = self._old_diag
        scp._BATCH_STATE.update(self._old_state)

    def test_batch_sample_shape_with_pounds_weights(self) -> None:
        scp._batch_read = lambda _sm: _values_dict()
        scp._BATCH_STATE["weights_in_slugs"] = False
        sample = scp.read_position_minimal(force=True)
        self.assertTrue(sample.get("ok"))
        self.assertEqual(sample["source"], "simconnect-minimal")
        self.assertTrue(sample.get("minimal"))
        self.assertAlmostEqual(sample["altitude_ft"], 1234.0)
        self.assertAlmostEqual(sample["pressure_altitude_ft"], 380.0 * 3.280839895)
        self.assertAlmostEqual(sample["gross_weight_lb"], 314851.0)  # pounds, not slugs
        self.assertAlmostEqual(sample["max_gross_weight_lb"], 513676.0)
        self.assertTrue(sample["engines_running"])
        self.assertTrue(sample["engine1_running"])
        self.assertFalse(sample["engine3_running"])
        self.assertAlmostEqual(sample["heading_deg"], 90.0)

    def test_batch_sample_converts_slugs_when_declared(self) -> None:
        values = _values_dict()
        # Realistic slug-scale raw values (a ~315k lb aircraft is ~9.8k slugs).
        values["TOTAL_WEIGHT"] = 9800.0
        values["EMPTY_WEIGHT"] = 8291.0
        values["MAX_GROSS_WEIGHT"] = 15966.0
        scp._batch_read = lambda _sm: values
        # Declare slugs on the fake wrapper's table so _batch_ensure derives
        # the conversion from the actual units (never hard-coded).
        self.aq.TABLE = dict(self.aq.TABLE)
        self.aq.TABLE["TOTAL_WEIGHT"] = (b"TOTAL WEIGHT", b"Slugs")
        sample = scp.read_position_minimal(force=True)
        self.assertTrue(sample.get("ok"))
        self.assertAlmostEqual(sample["gross_weight_lb"], round(9800.0 * 32.17405, 1))
        self.assertAlmostEqual(sample["max_gross_weight_lb"], round(15966.0 * 32.17405, 1))

    def test_per_var_fallback_when_batch_fails(self) -> None:
        scp._batch_read = lambda _sm: None
        scp._BATCH_STATE["weights_in_slugs"] = False
        sample = scp.read_position_minimal(force=True)
        # Fake aq.get returns None for everything -> not-ok, but no exception.
        self.assertFalse(sample.get("ok"))


class HeartbeatCacheStamp(unittest.TestCase):
    def test_cache_uses_completion_time(self) -> None:
        old_read = tp._read_simconnect
        old_heartbeat = tp._SIM_HEARTBEAT
        old_at = tp._SIM_HEARTBEAT_AT
        old_fp = tp._SIM_HEARTBEAT_FINGERPRINT
        old_lc = tp._SIM_HEARTBEAT_LAST_CHANGE
        try:
            calls: list[float] = []

            def fake_read() -> dict[str, Any]:
                calls.append(time.monotonic())
                time.sleep(0.05)  # simulate a full read longer than the cache window
                return {
                    "ok": True, "lat": 51.47, "lon": -0.46, "altitude_ft": 5000.0,
                    "ground_speed_kts": 250.0, "indicated_speed_kts": 240.0,
                    "on_ground": False, "source": "simconnect",
                }

            tp._read_simconnect = fake_read
            tp._SIM_HEARTBEAT = {}
            tp._SIM_HEARTBEAT_AT = 0.0
            tp._SIM_HEARTBEAT_FINGERPRINT = None
            tp._SIM_HEARTBEAT_LAST_CHANGE = 0.0

            tp._sim_heartbeat(time.monotonic(), force=False)
            self.assertEqual(len(calls), 1)
            # Immediately after the (slow) read completes, a second call must
            # hit the cache - the stamp is the completion time, not the start.
            tp._sim_heartbeat(time.monotonic(), force=False)
            self.assertEqual(len(calls), 1)
        finally:
            tp._read_simconnect = old_read
            tp._SIM_HEARTBEAT = old_heartbeat
            tp._SIM_HEARTBEAT_AT = old_at
            tp._SIM_HEARTBEAT_FINGERPRINT = old_fp
            tp._SIM_HEARTBEAT_LAST_CHANGE = old_lc


if __name__ == "__main__":
    unittest.main()
