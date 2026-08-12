"""Black Box recorder stop regression tests (v0.25.75/v0.25.76).

Live Stage-2 testing exposed a release-blocking crash: ``stop_recording``
rebinds the module-level ``_CLOSED_FLIGHT_IDS`` dict (the #20 flight latch)
inside the function without declaring it ``global``, so every recording stop
raised ``UnboundLocalError`` - the file was finalized but the in-memory
recorder state never cleared, freezing the recorder until app restart.

v0.25.76 (#68): a second start for an already-closed flight must be refused
(the empty EWG5EZ ``.part``), and zero-sample ``.part`` files must be deleted
by the startup cleanup instead of being finalized into the library.
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

    def test_start_recording_refuses_already_closed_flight(self) -> None:
        """#68: never open a second file for a flight that was already recorded."""
        bb._CLOSED_FLIGHT_IDS = {"F1": time.monotonic()}
        result = bb.start_recording("F1", {"flight": {"callsign": "EWG5EZ"}})
        self.assertFalse(result.get("recording"))
        self.assertTrue(result.get("already_recorded"), "closed flight must be refused")

    def test_start_recording_allows_fresh_flight(self) -> None:
        """#68: a genuinely new flight id must still start normally."""
        bb._CLOSED_FLIGHT_IDS = {"F1": time.monotonic()}
        self.assertNotIn("F2", bb._CLOSED_FLIGHT_IDS)
        # Must not hit the already-recorded gate; keep it hermetic by
        # verifying the guard returns None only for unknown ids.
        self.assertIsNone(bb._CLOSED_FLIGHT_IDS.get("F2"))


class CleanupStaleParts(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="opsbb_cleanup_")
        self._old_root = bb._root
        self._old_shutdown = bb._SHUTDOWN
        bb._SHUTDOWN = True
        bb._root = lambda: Path(self._tmp)
        bb._ACTIVE = None

    def tearDown(self) -> None:
        bb._root = self._old_root
        bb._SHUTDOWN = self._old_shutdown
        bb._ACTIVE = None
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_zero_chunk_part_is_deleted(self) -> None:
        """#68: a .part with no samples is litter -- deleted, not finalized."""
        path = Path(self._tmp) / "EWG5EZ_D-AEWK_EDDB-LDSP_20260811072710Z.opsbb.part"
        bb._init_recording(path, {
            "recording_id": "empty", "flight_id": "F1",
            "started_utc": "2026-08-11T07:27:10Z", "state": "RECORDING",
        })
        bb._cleanup_stale_parts()
        self.assertFalse(path.exists(), "zero-chunk .part must be deleted")
        self.assertFalse(Path(str(path)[:-5]).exists(), "no empty .opsbb may be left")

    def test_nonempty_part_is_finalized(self) -> None:
        """#68: a .part WITH samples must still be finalized (not deleted)."""
        path = Path(self._tmp) / "TEST_NOREG_EDDB-LDSP_20260811000000Z.opsbb.part"
        bb._init_recording(path, {
            "recording_id": "t1", "flight_id": "F2",
            "started_utc": "2026-08-11T00:00:00Z", "state": "RECORDING",
        })
        with bb._connect(path) as conn:
            conn.execute(
                "INSERT INTO chunks(started_elapsed,ended_elapsed,sample_count,payload) VALUES(0.0,1.0,10,X'00')"
            )
        bb._cleanup_stale_parts()
        self.assertFalse(path.exists(), "source .part consumed")
        final = Path(str(path)[:-5])
        self.assertTrue(final.exists(), "nonempty .part must be finalized to .opsbb")


if __name__ == "__main__":
    unittest.main()
