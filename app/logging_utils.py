from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 5


def _safe_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def redact_private_ips(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"\b10\.(?:\d{1,3}\.){2}\d{1,3}\b", "[private-ip-hidden]", value)
    value = re.sub(r"\b192\.168\.\d{1,3}\.\d{1,3}\b", "[private-ip-hidden]", value)
    value = re.sub(r"\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b", "[private-ip-hidden]", value)
    return value


def log_policy() -> tuple[int, int]:
    """Return the OPS ROOM log rotation policy.

    Environment variables are accepted for tester/debug builds, but bounded so
    a bad value cannot recreate the 20+ GB public-beta log issue.
    """
    max_mb = _safe_int(os.getenv("OPSROOM_LOG_MAX_MB"), 10, 1, 100)
    backups = _safe_int(os.getenv("OPSROOM_LOG_BACKUPS"), DEFAULT_BACKUP_COUNT, 1, 20)
    return max_mb * 1024 * 1024, backups


class RotatingTextLog:
    """Line-buffered text stream with size-based rollover.

    This is intentionally small and dependency-free because it is installed as
    sys.stdout/sys.stderr very early in the launcher. It keeps OPS ROOM logs
    bounded even when a verbose integration loops for hours.
    """

    def __init__(self, path: Path, max_bytes: int = DEFAULT_MAX_BYTES, backup_count: int = DEFAULT_BACKUP_COUNT):
        self.path = Path(path)
        self.max_bytes = max(256 * 1024, int(max_bytes))
        self.backup_count = max(1, int(backup_count))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = None
        self._trim_oversize_existing()
        self._open()

    @property
    def encoding(self) -> str:
        return "utf-8"

    @property
    def errors(self) -> str:
        return "replace"

    def _open(self) -> None:
        self._handle = self.path.open("a", encoding="utf-8", buffering=1)

    def _close(self) -> None:
        if self._handle is not None:
            try:
                self._handle.close()
            except OSError:
                pass
            self._handle = None

    def _backup_path(self, index: int) -> Path:
        return self.path.with_name(f"{self.path.name}.{index}")

    def _shift_backups(self) -> None:
        for index in range(self.backup_count, 0, -1):
            src = self._backup_path(index)
            if not src.exists():
                continue
            if index >= self.backup_count:
                try:
                    src.unlink()
                except OSError:
                    pass
            else:
                dst = self._backup_path(index + 1)
                try:
                    src.replace(dst)
                except OSError:
                    pass

    def _tail_bytes(self, source: Path, byte_count: int) -> bytes:
        try:
            size = source.stat().st_size
            with source.open("rb") as handle:
                if size > byte_count:
                    handle.seek(-byte_count, os.SEEK_END)
                    data = handle.read(byte_count)
                    if b"\n" in data:
                        data = data.split(b"\n", 1)[1]
                    return data
                return handle.read()
        except OSError:
            return b""

    def _trim_oversize_existing(self) -> None:
        if not self.path.exists():
            return
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size <= self.max_bytes:
            return
        self._shift_backups()
        tail = self._tail_bytes(self.path, min(self.max_bytes // 2, 2 * 1024 * 1024))
        note = (
            f"[OPS ROOM] Previous log was {size / (1024 * 1024):.1f} MB and was trimmed at startup. "
            "Only the recent tail was preserved.\n"
        ).encode("utf-8", errors="replace")
        try:
            self._backup_path(1).write_bytes(note + tail)
            self.path.unlink(missing_ok=True)
        except OSError:
            # Last-resort truncate if replacement cannot be written.
            try:
                self.path.write_text("[OPS ROOM] Oversize log was truncated at startup.\n", encoding="utf-8")
            except OSError:
                pass

    def _rollover_if_needed(self, incoming_bytes: int) -> None:
        try:
            current_size = self.path.stat().st_size if self.path.exists() else 0
        except OSError:
            current_size = 0
        if current_size + max(0, incoming_bytes) <= self.max_bytes:
            return
        self._close()
        self._shift_backups()
        try:
            if self.path.exists():
                self.path.replace(self._backup_path(1))
        except OSError:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
        self._open()

    def write(self, data: str) -> int:
        text = redact_private_ips(str(data))
        encoded_len = len(text.encode("utf-8", errors="replace"))
        if encoded_len:
            self._rollover_if_needed(encoded_len)
        if self._handle is None:
            self._open()
        try:
            self._handle.write(text)
            self._handle.flush()
        except (OSError, ValueError):
            return len(text)
        return len(text)

    def flush(self) -> None:
        if self._handle is not None:
            try:
                self._handle.flush()
            except (OSError, ValueError):
                pass

    def isatty(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

    def close(self) -> None:
        self._close()
