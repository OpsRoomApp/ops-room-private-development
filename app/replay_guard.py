from __future__ import annotations

"""Central runtime guard that prevents replay motion from creating real flights."""

import threading
import time
from typing import Any

_LOCK = threading.RLock()
_ACTIVE = False
_UNTIL = 0.0
_REASON = ""
_STARTED = 0.0


def activate(reason: str = "BLACK BOX REPLAY") -> None:
    global _ACTIVE, _UNTIL, _REASON, _STARTED
    with _LOCK:
        _ACTIVE = True
        _UNTIL = 0.0
        _REASON = str(reason or "BLACK BOX REPLAY")
        _STARTED = time.monotonic()


def release(cooldown_seconds: float = 4.0) -> None:
    global _ACTIVE, _UNTIL
    with _LOCK:
        _ACTIVE = False
        _UNTIL = max(_UNTIL, time.monotonic() + max(0.0, float(cooldown_seconds)))


def is_active() -> bool:
    with _LOCK:
        return bool(_ACTIVE or time.monotonic() < _UNTIL)


def status() -> dict[str, Any]:
    with _LOCK:
        now = time.monotonic()
        return {
            "active": bool(_ACTIVE),
            "guarded": bool(_ACTIVE or now < _UNTIL),
            "cooldown_seconds": round(max(0.0, _UNTIL - now), 2),
            "reason": _REASON,
            "started_seconds_ago": round(max(0.0, now - _STARTED), 2) if _STARTED else None,
        }
