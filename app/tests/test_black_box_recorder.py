"""Black Box recorder stop regression tests (v0.25.75).

Live Stage-2 testing exposed a release-blocking crash: ``stop_recording``
rebinds the module-level ``_CLOSED_FLIGHT_IDS`` dict (the #20 flight latch)
inside the function without declaring it ``global``, so every recording stop
raised ``UnboundLocalError`` - the file was finalized but the in-memory
recorder state never cleared, freezing the recorder until app restart.
"""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path

from app import black_box as bb


class StopRecording(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="opsbb_test_")
        self._old_active = bb._ACTIVE
        self._old_shutdown = bb._SHUTDOWN
        self._old_stop = bb._STOP
        self._old_thread = bb._THREAD
        self._old_closed = bb._CLOSED_FLIGHT_IDS
        bb._CLOSED_FLIGHT_IDS = dict(self._old_closed)
        # Keep the test hermetic: no real watchdog/recorder threads.
        bb._SHUTDOWN = True

    def tearDown(self) -> None:
        bb._ACTIVE = self._old_active
        bb._SHUTDOWN = self._old_shutdown
        bb._STOP = self._old_stop
        bb._THREAD = self._old_thread
        bb._CLOSED_FLIGHT_IDS = self._old_closed
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_stop_recording_closes_cleanly_and_latches_flight(self) -> None:
        path = Path(self._tmp) / "TEST_STAGE2_NOREG_RKSS-RKPC_20260810Z.opsbb.part"
        bb._init_recording(path, {
            "recording_id": "t1", "flight_id": "F1",
            "started_utc": "2026-08-10T00:00:00Z", "state": "RECORDING",
        })
        bb._ACTIVE = {
            "id": "t1", "flight_id": "F1", "path": path,
            "started_mono": time.monotonic(), "started_utc": "2026-08-10T00:00:00Z",
            "buffer": [], "sample_count": 0, "attempt_count": 1, "valid_count": 1,
            "last_flush": time.monotonic(), "last_fingerprint": None,
            "capabilities": set(), "last_source": "fsuipc7", "last_sample_utc": None,
            "provider_categories": {}, "aircraft_adapter": None,
            "last_event_row": None, "live_events": [], "addon_event_meta": {},
        }
        result = bb.stop_recording("TEST")
        self.assertTrue(result.get("ok"))
        self.assertIsNone(bb._ACTIVE, "recorder must clear its active state")
        self.assertIn("F1", bb._CLOSED_FLIGHT_IDS, "closed flight must be latched")
        final = Path(str(path)[:-5])  # .part -> .opsbb rename
        self.assertTrue(final.exists(), "recording file must be finalized")

    def test_stop_recording_without_active_returns_status(self) -> None:
        bb._ACTIVE = None
        result = bb.stop_recording("TEST")
        self.assertTrue(result.get("ok"))
        self.assertFalse(result.get("recording"))


if __name__ == "__main__":
    unittest.main()
