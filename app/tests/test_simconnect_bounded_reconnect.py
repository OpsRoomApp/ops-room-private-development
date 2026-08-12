"""Regression tests for #64 -- bounded SimConnect reconnect.

After a small ceiling of consecutive dispatch crashes within a short window,
the session must be permanently degraded (never rebuilt again this run)
instead of retrying into a progressively corrupt native heap.

Plain-Python PASS/FAIL harness, no network, no SimConnect import.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# Import the module functions under test directly (they are pure counter logic).
import app.simconnect_position as scp  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if condition:
        PASS += 1
        return True
    FAIL += 1
    print(f"  FAIL {name}" + (f" -- {detail}" if detail else ""))
    return False


def _reset() -> None:
    scp._SESSION_CRASH_COUNT = 0
    scp._SESSION_CRASH_WINDOW_START = 0.0
    scp._SESSION_PERMANENTLY_DEGRADED = False


def _fake_monotonic(seq):
    """Return a callable that hands out preset monotonic() values in order,
    repeating the last value once the sequence is exhausted."""
    it = iter(seq)
    last = [None]

    def fake():
        try:
            last[0] = next(it)
        except StopIteration:
            pass
        return last[0]

    return fake


# --- 1. Under the ceiling: session survives and keeps rebuilding ------------
_reset()
orig_monotonic = time.monotonic
try:
    t = 100.0
    time.monotonic = _fake_monotonic([t + i * 10.0 for i in range(scp._SESSION_CRASH_CEILING - 1)])
    degraded = False
    for _ in range(scp._SESSION_CRASH_CEILING - 1):
        degraded = degraded or scp._note_dispatch_crash()
    check("under ceiling: not permanently degraded", not scp._SESSION_PERMANENTLY_DEGRADED)
    check("under ceiling: calls return False", not degraded)
finally:
    time.monotonic = orig_monotonic

# --- 2. At the ceiling: permanent degradation flips --------------------------
_reset()
orig_monotonic = time.monotonic
try:
    t = 200.0
    time.monotonic = _fake_monotonic([t + i * 1.0 for i in range(scp._SESSION_CRASH_CEILING)])
    result = False
    for _ in range(scp._SESSION_CRASH_CEILING):
        result = scp._note_dispatch_crash()
    check("at ceiling: permanently degraded", scp._SESSION_PERMANENTLY_DEGRADED)
    check("at ceiling: final call returns True", result)
    # Idempotent: further crashes keep it degraded and still report True.
    check("at ceiling: stays degraded", scp._note_dispatch_crash() and scp._SESSION_PERMANENTLY_DEGRADED)
finally:
    time.monotonic = orig_monotonic

# --- 3. Window reset: old crashes do not count against a fresh window -------
_reset()
orig_monotonic = time.monotonic
try:
    # Two crashes just inside the window, then a big gap (fresh window), then
    # two more crashes -- all below the ceiling -> not degraded.
    time.monotonic = _fake_monotonic([0.0, 1.0, 2000.0, 2001.0])
    scp._note_dispatch_crash()
    scp._note_dispatch_crash()
    check("window reset: count restarted", scp._SESSION_CRASH_COUNT == 2)
    scp._note_dispatch_crash()
    scp._note_dispatch_crash()
    check("window reset: not degraded after fresh-window crashes", not scp._SESSION_PERMANENTLY_DEGRADED)
finally:
    time.monotonic = orig_monotonic

# --- 4. _ensure_session refuses to rebuild once degraded --------------------
_reset()
scp._SESSION_PERMANENTLY_DEGRADED = True
try:
    scp._ensure_session({"dll_path": "irrelevant"})
    check("ensure_session raises when degraded", False, "expected ConnectionError")
except ConnectionError as exc:
    check("ensure_session raises when degraded", "disabled" in str(exc))
finally:
    _reset()

print(f"\n{scp.__name__}: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
