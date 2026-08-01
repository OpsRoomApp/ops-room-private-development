from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app.aircraft_adapter_installer as installer


class FsuipcLogCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.exe = self.root / "FSUIPC7.exe"
        self.exe.write_bytes(b"")
        self.ini = self.root / "FSUIPC7.ini"
        self._locate = patch.object(installer, "locate_fsuipc", return_value=self.exe)
        self._locate.start()

    def tearDown(self) -> None:
        self._locate.stop()
        self._temporary.cleanup()

    def _write_quiet_ini(self) -> None:
        sections: dict[str, list[str]] = {}
        for section, key, value in installer._FSUIPC_QUIET_KEYS:
            sections.setdefault(section, []).append(f"{key}={value}")
        text = "\n".join(f"[{section}]\n" + "\n".join(lines) for section, lines in sections.items()) + "\n"
        self.ini.write_text(text, encoding="utf-8")

    @staticmethod
    def _sparse(path: Path, size: int, marker: bytes = b"TAIL") -> None:
        with path.open("wb") as handle:
            handle.seek(size - len(marker))
            handle.write(marker)

    def test_noisy_ini_is_quieted_and_log_tail_is_bounded_without_full_rotation(self) -> None:
        self.ini.write_text("[General]\nLogReads=Yes\nLogEvents=Yes\nLogLvars=Yes\n[WAPI]\nLogLevel=Debug\n", encoding="utf-8")
        log = self.root / "FSUIPC7.log"
        original_size = installer._FSUIPC_DIAGNOSTIC_TAIL_BYTES + 8192
        self._sparse(log, original_size, b"END-MARKER")

        result = installer.reduce_fsuipc_log_size(max_bytes=1024)

        self.assertTrue(result["ok"])
        self.assertTrue(result["cleanup_complete"])
        self.assertEqual(result["cleanup_status"], "complete")
        self.assertEqual(log.stat().st_size, 0)
        tail = self.root / "FSUIPC7.log.opsroom-tail"
        self.assertEqual(tail.stat().st_size, installer._FSUIPC_DIAGNOSTIC_TAIL_BYTES)
        self.assertTrue(tail.read_bytes().endswith(b"END-MARKER"))
        self.assertFalse(list(self.root.glob("*.opsroom-rotated-*")))
        self.assertLess(Path(result["backup"]).stat().st_size, original_size)
        rendered = self.ini.read_text(encoding="utf-8")
        for section, key, value in installer._FSUIPC_QUIET_KEYS:
            self.assertEqual(installer._ini_key_value(rendered, section, key), value)

    def test_legacy_full_rotations_are_reclaimed(self) -> None:
        self._write_quiet_ini()
        legacy = self.root / "FSUIPC7.log.opsroom-rotated-20250101T000000000000Z"
        self._sparse(legacy, installer._FSUIPC_DIAGNOSTIC_TAIL_BYTES + 4096, b"LEGACY-END")
        unrelated = self.root / "Other.log.opsroom-rotated-20250101T000000000000Z"
        unrelated.write_bytes(b"not created by this feature")

        result = installer.reduce_fsuipc_log_size(max_bytes=1024)

        self.assertTrue(result["cleanup_complete"])
        self.assertFalse(legacy.exists())
        self.assertEqual(unrelated.read_bytes(), b"not created by this feature")
        tail = self.root / "FSUIPC7.log.opsroom-tail"
        self.assertLessEqual(tail.stat().st_size, installer._FSUIPC_DIAGNOSTIC_TAIL_BYTES)
        self.assertTrue(tail.read_bytes().endswith(b"LEGACY-END"))
        self.assertEqual(result["after"]["legacy_rotation_size"], 0)

    def test_already_small_logs_are_unchanged(self) -> None:
        self._write_quiet_ini()
        log = self.root / "FSUIPC7.log"
        log.write_bytes(b"small log")

        result = installer.reduce_fsuipc_log_size(max_bytes=1024)

        self.assertTrue(result["cleanup_complete"])
        self.assertFalse(result["ini_changed"])
        self.assertEqual(result["bytes_reclaimed"], 0)
        self.assertEqual(log.read_bytes(), b"small log")
        self.assertFalse((self.root / "FSUIPC7.log.opsroom-tail").exists())
        active = next(item for item in result["log_files"] if item["path"] == str(log))
        self.assertEqual(active["status"], "unchanged")

    def test_locked_truncation_is_pending_and_never_claims_reclamation(self) -> None:
        self._write_quiet_ini()
        log = self.root / "FSUIPC7.log"
        log.write_bytes(b"x" * 2048)

        with patch.object(installer, "_truncate_in_place", side_effect=PermissionError("sharing violation")):
            result = installer.reduce_fsuipc_log_size(max_bytes=1024)

        self.assertTrue(result["ok"])
        self.assertFalse(result["cleanup_complete"])
        self.assertTrue(result["pending"])
        self.assertEqual(result["cleanup_status"], "pending")
        self.assertEqual(result["bytes_reclaimed"], 0)
        self.assertEqual(log.stat().st_size, 2048)
        self.assertFalse((self.root / "FSUIPC7.log.opsroom-tail").exists())
        locked = next(item for item in result["pending_files"] if item["path"] == str(log))
        self.assertEqual(locked["bytes_reclaimed"], 0)

    def test_repeated_cleanup_is_idempotent(self) -> None:
        self.ini.write_text("[General]\nLogReads=Yes\n", encoding="utf-8")
        log = self.root / "FSUIPC7.log"
        self._sparse(log, installer._FSUIPC_DIAGNOSTIC_TAIL_BYTES + 4096)

        first = installer.reduce_fsuipc_log_size(max_bytes=1024)
        backups_after_first = list(self.root.glob("FSUIPC7.ini.opsroom-backup-*"))
        second = installer.reduce_fsuipc_log_size(max_bytes=1024)

        self.assertTrue(first["cleanup_complete"] and second["cleanup_complete"])
        self.assertGreater(first["bytes_reclaimed"], 0)
        self.assertEqual(second["bytes_reclaimed"], 0)
        self.assertFalse(second["ini_changed"])
        self.assertEqual(list(self.root.glob("FSUIPC7.ini.opsroom-backup-*")), backups_after_first)
        self.assertEqual(len(list(self.root.glob("*.opsroom-tail"))), 1)
        self.assertFalse(list(self.root.glob("*.opsroom-rotated-*")))

    def test_status_totals_active_legacy_and_diagnostic_files(self) -> None:
        self._write_quiet_ini()
        (self.root / "FSUIPC7.log").write_bytes(b"a" * 10)
        (self.root / "FSUIPC7.Previous.log").write_bytes(b"b" * 20)
        (self.root / "LVarLog.txt").write_bytes(b"c" * 30)
        (self.root / "FSUIPC7.log.opsroom-rotated-old").write_bytes(b"d" * 40)
        (self.root / "FSUIPC7.log.opsroom-tail").write_bytes(b"e" * 50)

        status = installer.fsuipc_log_status()

        self.assertEqual(status["total_size"], 150)
        self.assertEqual(status["active_size"], 60)
        self.assertEqual(status["legacy_rotation_size"], 40)
        self.assertEqual(status["diagnostic_tail_size"], 50)
        self.assertTrue(status["cleanup_pending"])
        self.assertEqual({item["kind"] for item in status["files"] if item["exists"]}, {"active", "legacy_rotation", "diagnostic_tail"})

    def test_preexisting_oversized_diagnostic_tail_is_bounded(self) -> None:
        self._write_quiet_ini()
        tail = self.root / "FSUIPC7.log.opsroom-tail"
        self._sparse(tail, installer._FSUIPC_DIAGNOSTIC_TAIL_BYTES + 4096, b"TAIL-END")

        result = installer.reduce_fsuipc_log_size(max_bytes=1024)

        self.assertTrue(result["cleanup_complete"])
        self.assertEqual(tail.stat().st_size, installer._FSUIPC_DIAGNOSTIC_TAIL_BYTES)
        self.assertTrue(tail.read_bytes().endswith(b"TAIL-END"))
        self.assertLessEqual(result["after"]["diagnostic_tail_size"], result["after"]["diagnostic_retained_total_limit"])


if __name__ == "__main__":
    unittest.main()
