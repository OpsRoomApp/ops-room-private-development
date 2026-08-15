"""#108 next tier — probe worker isolation tests.

Covers the isolation that makes SimConnect crash recovery automatic for BOTH
FSUIPC and non-FSUIPC users:

1. Worker protocol in-process (ping / read / position / minimal / camera /
   shutdown, id echo, no-session fast-fail + reconnect backoff) with the
   SimConnect internals stubbed.
2. Client protocol against a stub worker subprocess (spawn, reader thread,
   serialized transactions, response parsing, shutdown).
3. Client timeout -> worker kill -> backoff recovery when the worker hangs.
4. Dev-mode gate: read_position/read_position_minimal/camera stay on the
   in-process path outside packaged builds unless OPSROOM_PROBE_WORKER=1.
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
import unittest
from unittest import mock

from app import simconnect_position as scp
from app import simconnect_probe_client as client
from app import simconnect_probe_worker as worker


# ── Worker protocol (in-process, SimConnect internals stubbed) ───────────────

class WorkerProtocol(unittest.TestCase):
    def _run_worker(self, commands: list[str]) -> list[dict]:
        stdin = io.StringIO("\n".join(commands) + "\n")
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdin", stdin), mock.patch.object(sys, "stdout", stdout):
            rc = worker.run()
        self.assertEqual(rc, 0)
        return [json.loads(line) for line in stdout.getvalue().strip().splitlines()]

    def test_ping_and_shutdown_echo_id(self) -> None:
        lines = self._run_worker([
            json.dumps({"cmd": "ping", "id": 7}),
            json.dumps({"cmd": "shutdown", "id": 8}),
        ])
        self.assertEqual(lines[0]["pong"], True)
        self.assertEqual(lines[0]["id"], 7)
        self.assertEqual(lines[1]["bye"], True)
        self.assertEqual(lines[1]["id"], 8)

    def test_unknown_and_bad_json_are_errors(self) -> None:
        lines = self._run_worker([
            json.dumps({"cmd": "nope", "id": 1}),
            "not-json",
            json.dumps({"cmd": "shutdown", "id": 2}),
        ])
        self.assertEqual(lines[0]["ok"], False)
        self.assertEqual(lines[1]["ok"], False)

    def test_position_minimal_camera(self) -> None:
        fake_position = {
            "ok": True, "lat": 51.47, "lon": -0.46, "altitude_ft": 4000.0,
            "indicated_altitude_ft": 3950.0, "agl_ft": 3800.0,
            "indicated_speed_kts": 240.0, "ground_speed_kts": 250.0,
            "on_ground": False, "source": "simconnect",
            "aircraft": {"title": "T", "model": "M", "type": "T"},
        }
        fake_minimal = dict(fake_position)
        fake_minimal.update({"source": "simconnect-minimal", "minimal": True})
        with mock.patch.object(scp, "_read_position_uncached", return_value=dict(fake_position)):
            with mock.patch.object(scp, "_read_position_minimal_uncached", return_value=dict(fake_minimal)):
                with mock.patch.object(scp, "camera_state_simconnect", return_value=5):
                    lines = self._run_worker([
                        json.dumps({"cmd": "position", "id": 3}),
                        json.dumps({"cmd": "minimal", "id": 4}),
                        json.dumps({"cmd": "camera", "id": 5}),
                        json.dumps({"cmd": "shutdown", "id": 6}),
                    ])
        self.assertTrue(lines[0]["ok"])
        self.assertEqual(lines[0]["id"], 3)
        self.assertAlmostEqual(lines[0]["lat"], 51.47)
        self.assertEqual(lines[0]["source"], "simconnect")
        self.assertTrue(lines[1]["ok"])
        self.assertEqual(lines[1]["id"], 4)
        self.assertEqual(lines[1]["source"], "simconnect-minimal")
        self.assertEqual(lines[1]["minimal"], True)
        self.assertTrue(lines[2]["ok"])
        self.assertEqual(lines[2]["id"], 5)
        self.assertEqual(lines[2]["value"], 5)

    def test_lvar_read(self) -> None:
        fake_sm = object()
        with mock.patch.object(worker, "_session", return_value=fake_sm):
            with mock.patch.object(worker, "_read_lvars", return_value=[1.0, None, 3.0]):
                lines = self._run_worker([
                    json.dumps({"cmd": "read", "requests": [["A", "Number"], ["B", "Number"], ["C", "Number"]], "id": 9}),
                    json.dumps({"cmd": "shutdown", "id": 10}),
                ])
        self.assertTrue(lines[0]["ok"])
        self.assertEqual(lines[0]["id"], 9)
        self.assertEqual(lines[0]["values"], [1.0, None, 3.0])

    def test_no_session_fast_fail_and_backoff(self) -> None:
        with mock.patch.object(worker, "_session", return_value=None):
            lines = self._run_worker([
                json.dumps({"cmd": "read", "requests": [["A", "Number"]], "id": 1}),
                json.dumps({"cmd": "read", "requests": [["A", "Number"]], "id": 2}),
                json.dumps({"cmd": "shutdown", "id": 3}),
            ])
        # First attempt tries to connect and fails fast...
        self.assertEqual(lines[0]["ok"], False)
        self.assertEqual(lines[0]["error"], "no-simconnect")
        # ...the second attempt inside the reconnect backoff answers
        # immediately without blocking the pipe.
        self.assertEqual(lines[1]["ok"], False)
        self.assertEqual(lines[1]["error"], "no-simconnect")


# ── Client protocol (stub worker subprocess) ─────────────────────────────────

_STUB_WORKER = "\n".join([
    "import json, sys",
    "for line in sys.stdin:",
    "    line = line.strip()",
    "    if not line:",
    "        continue",
    "    try:",
    "        msg = json.loads(line)",
    "    except Exception:",
    "        sys.stdout.write(json.dumps({'ok': False, 'error': 'bad-json'}) + chr(10))",
    "        sys.stdout.flush()",
    "        continue",
    "    cmd = msg.get('cmd')",
    "    rid = msg.get('id')",
    "    if cmd == 'shutdown':",
    "        sys.stdout.write(json.dumps({'ok': True, 'bye': True, 'id': rid}) + chr(10))",
    "        sys.stdout.flush()",
    "        break",
    "    if cmd == 'ping':",
    "        resp = {'ok': True, 'pong': True}",
    "    elif cmd == 'read':",
    "        resp = {'ok': True, 'values': [42.0]}",
    "    elif cmd == 'position':",
    "        resp = {'ok': True, 'lat': 51.47, 'lon': -0.46, 'altitude_ft': 4000.0, 'source': 'simconnect'}",
    "    elif cmd == 'minimal':",
    "        resp = {'ok': True, 'lat': 51.47, 'lon': -0.46, 'source': 'simconnect-minimal', 'minimal': True}",
    "    elif cmd == 'camera':",
    "        resp = {'ok': True, 'value': 5}",
    "    else:",
    "        resp = {'ok': False, 'error': 'unknown-cmd'}",
    "    resp['id'] = rid",
    "    sys.stdout.write(json.dumps(resp) + chr(10))",
    "    sys.stdout.flush()",
])


class ClientProtocol(unittest.TestCase):
    def setUp(self) -> None:
        self._old_cmd = client._worker_command
        client._worker_command = staticmethod(lambda: [sys.executable, "-c", _STUB_WORKER])
        self._reset_state()

    def tearDown(self) -> None:
        client.shutdown()
        client._worker_command = self._old_cmd
        self._reset_state()

    def _reset_state(self) -> None:
        client._PROC = None
        client._QUEUE = None
        client._READER_THREAD = None
        client._FAILED_UNTIL = 0.0
        client._TXN_COUNTER = 0

    def test_round_trips(self) -> None:
        self.assertTrue(client.ping())
        self.assertEqual(client.read_lvars([("A", "Number")]), [42.0])
        pos = client.read_position()
        self.assertIsNotNone(pos)
        self.assertTrue(pos["ok"])
        self.assertAlmostEqual(pos["lat"], 51.47)
        mini = client.read_position_minimal()
        self.assertIsNotNone(mini)
        self.assertTrue(mini["ok"])
        self.assertEqual(mini["source"], "simconnect-minimal")
        self.assertEqual(client.camera_state(), 5)

    def test_serialized_concurrent_transactions(self) -> None:
        results: list[bool] = []
        lock = threading.Lock()

        def worker_fn() -> None:
            ok = client.ping() and client.read_position() is not None
            with lock:
                results.append(ok)

        threads = [threading.Thread(target=worker_fn) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(results), 6)
        self.assertTrue(all(results))

    def test_hung_worker_times_out_kills_and_backs_off(self) -> None:
        slow_stub = "\n".join([
            "import json, sys, time",
            "for line in sys.stdin:",
            "    try:",
            "        msg = json.loads(line.strip())",
            "    except Exception:",
            "        continue",
    "    if msg.get('cmd') == 'shutdown':",
    "        break",
    "    time.sleep(10.0)",
])
        client._worker_command = staticmethod(lambda: [sys.executable, "-c", slow_stub])
        start = time.monotonic()
        resp = client._transact({"cmd": "ping"}, timeout=1.0)
        elapsed = time.monotonic() - start
        self.assertIsNone(resp)
        self.assertLess(elapsed, 3.0)
        # Backoff is armed: subsequent calls return fast, no repeated stalls.
        start = time.monotonic()
        self.assertFalse(client.ping())
        self.assertLess(time.monotonic() - start, 1.0)


# ── Dev-mode gate ────────────────────────────────────────────────────────────

class DevModeGate(unittest.TestCase):
    def test_worker_disabled_outside_frozen(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            if os.getenv("OPSROOM_PROBE_WORKER"):
                del os.environ["OPSROOM_PROBE_WORKER"]
            self.assertFalse(scp._worker_reads_enabled())
            self.assertIsNone(scp._worker_read_position())
            self.assertIsNone(scp._worker_read_minimal())
            self.assertIsNone(scp._worker_camera_state())

    def test_env_override(self) -> None:
        with mock.patch.dict(os.environ, {"OPSROOM_PROBE_WORKER": "1"}):
            self.assertTrue(scp._worker_reads_enabled())
        with mock.patch.dict(os.environ, {"OPSROOM_PROBE_WORKER": "0"}):
            self.assertFalse(scp._worker_reads_enabled())


if __name__ == "__main__":
    unittest.main()
