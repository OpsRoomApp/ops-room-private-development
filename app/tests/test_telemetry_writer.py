"""Stage-2 single-writer telemetry bus tests (v0.25.75).

Pins the writer's cadence logic, the ring-buffer consumer API and the
"consumers never touch the simulator" cache semantics without needing a live
simulator. The end-to-end writer thread behaviour (fake FSUIPC source -> ring
-> recorder drain -> STALE surfacing) is covered by the standalone simulation
harness and the on-sim verification checklist.
"""

from __future__ import annotations

import time
import unittest

from app import telemetry_provider as tp


def _neutral_sample() -> dict:
    """A complete FSUIPC-shaped sample with no altitude hints (cadence tests)."""
    return {"source": "fsuipc7", "ok": True, "lat": 51.47, "lon": -0.46}


class WriterCadence(unittest.TestCase):
    def setUp(self) -> None:
        self._old_lock = tp._SOURCE_LOCK
        self._old_sample = tp._WRITER_LAST_SAMPLE
        self._old_phase = tp._WRITER_PHASE
        self._old_rec = tp._WRITER_RECORDING

    def tearDown(self) -> None:
        tp._SOURCE_LOCK = self._old_lock
        tp._WRITER_LAST_SAMPLE = self._old_sample
        tp._WRITER_PHASE = self._old_phase
        tp._WRITER_RECORDING = self._old_rec

    def test_idle_interval_is_one_second(self) -> None:
        tp.set_writer_phase("", recording=False)
        self.assertAlmostEqual(tp._writer_interval(), 1.0, places=9)

    def test_phase_cadence_fsuipc(self) -> None:
        tp._SOURCE_LOCK = "fsuipc7"
        tp._WRITER_LAST_SAMPLE = _neutral_sample()
        tp.set_writer_phase("TAXI OUT", recording=True)
        self.assertAlmostEqual(tp._writer_interval(), 0.05, places=9)  # 20 Hz
        tp.set_writer_phase("TAKEOFF ROLL", recording=True)
        self.assertAlmostEqual(tp._writer_interval(), 1.0 / 30.0, places=9)  # 30 Hz
        tp.set_writer_phase("APPROACH", recording=True)
        self.assertAlmostEqual(tp._writer_interval(), 1.0 / 30.0, places=9)
        tp.set_writer_phase("CRUISE", recording=True)
        self.assertAlmostEqual(tp._writer_interval(), 0.1, places=9)  # 10 Hz

    def test_low_agl_forces_thirty_hz(self) -> None:
        tp._SOURCE_LOCK = "fsuipc7"
        sample = {"source": "fsuipc7", "radio_altitude_ft": 950.0}
        tp._WRITER_LAST_SAMPLE = sample
        tp.set_writer_phase("CRUISE", recording=True)
        self.assertAlmostEqual(tp._writer_interval(), 1.0 / 30.0, places=9)

    def test_simconnect_hits_thirty_hz_with_batched_reader(self) -> None:
        tp._SOURCE_LOCK = "simconnect"
        tp._WRITER_LAST_SAMPLE = {"source": "simconnect-minimal"}
        tp.set_writer_phase("TAKEOFF ROLL", recording=True)
        # The batched SimConnect reader sustains 30 Hz (live-verified, no
        # stutter); the cap is black_box_simconnect_max_hz (default 30).
        self.assertAlmostEqual(tp._writer_interval(), 1.0 / 30.0, places=9)

    def test_configured_cap_respected(self) -> None:
        tp._SOURCE_LOCK = "fsuipc7"
        tp._WRITER_LAST_SAMPLE = _neutral_sample()
        tp.set_writer_phase("TAKEOFF ROLL", recording=True)
        # black_box_max_hz default 30 -> 30 Hz; verify interval math only.
        self.assertLessEqual(tp._writer_interval(), 1.0 / 2.0)


class RingBuffer(unittest.TestCase):
    def setUp(self) -> None:
        self._old_start = tp.start_telemetry_writer
        tp.start_telemetry_writer = lambda: None  # no background thread in tests
        self._old_ring = tp._WRITER_RING
        tp._WRITER_RING = tp._WRITER_RING.__class__(maxlen=100)

    def tearDown(self) -> None:
        tp.start_telemetry_writer = self._old_start
        tp._WRITER_RING = self._old_ring

    def test_drain_since_cursor_and_latest(self) -> None:
        now = time.monotonic()
        tp._WRITER_RING.append((now - 3.0, {"ok": True, "n": 0}))
        tp._WRITER_RING.append((now - 2.0, {"ok": True, "n": 1}))
        tp._WRITER_RING.append((now - 1.0, {"ok": False, "n": 2}))
        items = tp.writer_ring_since(now - 2.5)
        self.assertEqual([item[1]["n"] for item in items], [1, 2])
        self.assertEqual(items[-1][0], now - 1.0)
        ts, latest = tp.writer_latest()  # type: ignore[misc]
        self.assertEqual(latest["n"], 2)
        self.assertFalse(latest["ok"])
        # cursor advancement: draining again from the last ts yields nothing
        self.assertEqual(tp.writer_ring_since(items[-1][0]), [])


class CacheSemantics(unittest.TestCase):
    """read_telemetry(force=False) must serve the writer's cache, never the sim."""

    def setUp(self) -> None:
        self._old_read = tp._read_fsuipc
        self._old_proc = tp._sim_process_running
        self._old_lock = tp._SOURCE_LOCK
        self._old_cache = tp._CACHE
        self._old_cache_time = tp._CACHE_TIME
        tp._sim_process_running = lambda: True

    def tearDown(self) -> None:
        tp._read_fsuipc = self._old_read
        tp._sim_process_running = self._old_proc
        tp._SOURCE_LOCK = self._old_lock
        tp._CACHE = self._old_cache
        tp._CACHE_TIME = self._old_cache_time

    def test_fresh_cache_served_without_sim_read(self) -> None:
        tp._SOURCE_LOCK = "fsuipc7"
        tp._CACHE = {"ok": True, "source": "fsuipc7", "lat": 1.0, "lon": 2.0}
        tp._CACHE_TIME = time.monotonic()

        def _boom() -> dict:
            raise AssertionError("consumer read touched the simulator")

        tp._read_fsuipc = _boom
        for _ in range(3):
            result = tp.read_telemetry(force=False)
            self.assertTrue(result["ok"])
            self.assertEqual(result["source"], "fsuipc7")

    def test_aged_cache_falls_through_to_direct_read(self) -> None:
        """Writer-down fallback: after _WRITER_CACHE_MAX_AGE a real read happens."""
        tp._SOURCE_LOCK = None
        tp._CACHE = {"ok": True, "source": "fsuipc7", "lat": 1.0, "lon": 2.0}
        tp._CACHE_TIME = time.monotonic() - tp._WRITER_CACHE_MAX_AGE - 1.0
        sample = {
            "ok": True, "lat": 51.47, "lon": -0.46, "altitude_ft": 1000.0,
            "altitude_source": "test", "altitude_confidence": "valid",
            "indicated_speed_kts": 130.0, "ground_speed_kts": 125.0,
            "on_ground": True,
        }
        tp._read_fsuipc = lambda: dict(sample)
        result = tp.read_telemetry(force=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "fsuipc7")


class WriterTick(unittest.TestCase):
    def setUp(self) -> None:
        self._old_read = tp._read_fsuipc
        self._old_proc = tp._sim_process_running
        self._old_hb = tp._sim_heartbeat
        self._old_lock = tp._SOURCE_LOCK
        self._old_ring = tp._WRITER_RING
        tp._WRITER_RING = tp._WRITER_RING.__class__(maxlen=100)
        tp._sim_process_running = lambda: True
        tp._sim_heartbeat = lambda now, force=False: {}

    def tearDown(self) -> None:
        tp._read_fsuipc = self._old_read
        tp._sim_process_running = self._old_proc
        tp._sim_heartbeat = self._old_hb
        tp._SOURCE_LOCK = self._old_lock
        tp._WRITER_RING = self._old_ring

    def test_fsuipc_tick_publishes_full_shape_to_ring_and_cache(self) -> None:
        tp._SOURCE_LOCK = "fsuipc7"
        sample = {
            "ok": True, "lat": 51.47, "lon": -0.46, "altitude_ft": 1000.0,
            "altitude_source": "test", "altitude_confidence": "valid",
            "indicated_speed_kts": 130.0, "ground_speed_kts": 125.0,
            "on_ground": True, "engines_running": True,
            "aircraft": {"title": "Test Generic", "model": "A320", "type": "A320"},
        }
        tp._read_fsuipc = lambda: dict(sample)
        tp._writer_tick()
        self.assertEqual(len(tp._WRITER_RING), 1)
        ts, ring_item = tp._WRITER_RING[0]
        self.assertGreater(ts, 0.0)
        self.assertTrue(ring_item["ok"])
        self.assertEqual(ring_item["source"], "fsuipc7")
        self.assertEqual(ring_item["lat"], 51.47)
        # cache published for consumers
        self.assertIsNotNone(tp._CACHE)
        self.assertEqual(tp._CACHE.get("source"), "fsuipc7")  # type: ignore[union-attr]
        # error samples are published too (STALE surfacing), not dropped.
        # With no last-good sample the provider reports hard failure (not a
        # brief-hiccup hold), and the recorder's _normalize rejects the row.
        tp._LAST_GOOD_BY_SOURCE.pop("fsuipc7", None)
        tp._LAST_GOOD_TIME_BY_SOURCE.pop("fsuipc7", None)
        tp._read_fsuipc = lambda: {"ok": False, "reason": "dead", "source": "fsuipc7"}
        tp._writer_tick()
        self.assertEqual(len(tp._WRITER_RING), 2)
        self.assertFalse(tp._WRITER_RING[-1][1]["ok"])


class SimConnectBranch(unittest.TestCase):
    def setUp(self) -> None:
        self._old_hb = tp._sim_heartbeat
        self._old_lock = tp._SOURCE_LOCK
        self._old_cache = tp._CACHE
        self._old_cache_time = tp._CACHE_TIME
        self._old_ring = tp._WRITER_RING
        tp._WRITER_RING = tp._WRITER_RING.__class__(maxlen=100)
        tp._sim_heartbeat = lambda now, force=False: {
            "ok": True, "lat": 48.35, "lon": 11.78, "altitude_ft": 1200.0,
            "altitude_source": "simconnect", "altitude_confidence": "valid",
            "indicated_speed_kts": 140.0, "ground_speed_kts": 138.0,
            "on_ground": False, "engines_running": True,
            "aircraft": {"title": "Fenix A320 CFM", "model": "A320", "type": "A320"},
            "source": "simconnect",
        }

    def tearDown(self) -> None:
        tp._sim_heartbeat = self._old_hb
        tp._SOURCE_LOCK = self._old_lock
        tp._CACHE = self._old_cache
        tp._CACHE_TIME = self._old_cache_time
        tp._WRITER_RING = self._old_ring

    def test_simconnect_tick_publishes_full_cache_and_minimal_ring(self) -> None:
        import app.simconnect_position as scp
        old_minimal = scp.read_position_minimal
        scp.read_position_minimal = lambda force=False: {
            "ok": True, "lat": 48.35, "lon": 11.78, "source": "simconnect-minimal",
            "engines_running": True,
        }
        try:
            tp._SOURCE_LOCK = "simconnect"
            tp._CACHE = None
            tp._CACHE_TIME = 0.0
            tp._writer_tick()
            # cache (display) gets the full enriched sample
            self.assertIsNotNone(tp._CACHE)
            self.assertTrue(tp._CACHE.get("ok"))
            self.assertEqual(tp._CACHE.get("source"), "simconnect")
            self.assertTrue(tp._CACHE.get("telemetry_complete"))
            # ring (recorder) gets the minimal sample
            self.assertEqual(len(tp._WRITER_RING), 1)
            self.assertEqual(tp._WRITER_RING[0][1].get("source"), "simconnect-minimal")
        finally:
            scp.read_position_minimal = old_minimal


class LVarCache(unittest.TestCase):
    def test_value_cache_short_circuits_before_simconnect(self) -> None:
        tp._SIMCONNECT_LVAR_CACHE_KEY = (("FOO", "Number"),)
        tp._SIMCONNECT_LVAR_CACHE_VALUES = [42.0]
        tp._SIMCONNECT_LVAR_CACHE_AT = time.monotonic()
        # Fast path returns cached values without importing SimConnect.
        values = tp._read_simconnect_lvars([("FOO", "Number")])
        self.assertEqual(values, [42.0])


if __name__ == "__main__":
    unittest.main()
