"""Regression tests for #64/#98/#108 -- bounded SimConnect reconnect + parking.

#108 (2026-08-13): the main app process parks SimConnect PERMANENTLY on the
first dispatch death (crash ceiling of 1). Every session rebuild on the same
process heap re-opens the corrupt native session that trips ntdll 0xC0000374
(observed live: crash 1 s after a cooldown-triggered SIM OPEN). Only the
probe WORKER subprocess keeps the escalating-cooldown auto-recovery, because
it owns a fresh native heap per process and is respawned on death.

Plain-Python PASS/FAIL harness, no network, no SimConnect import.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest import mock

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
    scp._SESSION_DEGRADED_UNTIL = 0.0
    scp._SESSION_DEGRADATION_EPOCHS = 0
    # Test isolation: other test modules in the same process may have set these
    # to recent real-monotonic values; the cooldown/backoff checks below must
    # start from a clean slate or they spuriously refuse to rebuild.
    scp._LAST_REBUILD_AT = 0.0
    scp._SESSION_STARTED = 0.0
    scp._SESSION_DISPATCH_DEAD = False
    scp._SESSION_SM = None
    scp._SESSION_AQ = None


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


def _as_main_process():
    """Force _is_probe_worker_process() to False (normal app process)."""
    return mock.patch.object(scp, "_is_probe_worker_process", return_value=False)


def _as_worker_process():
    """Force _is_probe_worker_process() to True (isolated probe subprocess)."""
    return mock.patch.object(scp, "_is_probe_worker_process", return_value=True)


# --- MAIN PROCESS: permanent park on the FIRST dispatch death --------------
_reset()
with _as_main_process():
    orig_monotonic = time.monotonic
    try:
        t = 100.0
        time.monotonic = _fake_monotonic([t])
        # Single crash must park the main process immediately (ceiling 1).
        result = scp._note_dispatch_crash()
        check("main: first crash returns True", result)
        check("main: permanently degraded after first crash", scp._SESSION_PERMANENTLY_DEGRADED)
        check("main: crash count reset for next window", scp._SESSION_CRASH_COUNT == 0)
    finally:
        time.monotonic = orig_monotonic

# --- MAIN PROCESS: _ensure_session never auto-recovers after the park ------
_reset()
with _as_main_process():
    orig_monotonic = time.monotonic
    try:
        t = 500.0
        time.monotonic = _fake_monotonic([t])
        scp._note_dispatch_crash()
        check("main: parked before ensure_session", scp._SESSION_PERMANENTLY_DEGRADED)
        # Immediately after the park: refuse with the permanent message.
        try:
            scp._ensure_session({"dll_path": "irrelevant"})
            check("main: during park raises", False, "expected ConnectionError")
        except ConnectionError as exc:
            check("main: permanent park message", "permanently parked" in str(exc), str(exc))
        # Long after any conceivable cooldown: STILL refuse -- the main process
        # never rebuilds on the damaged heap (#108). Only an app restart resets.
        time.monotonic = _fake_monotonic([t + 100000.0])
        try:
            scp._ensure_session({"dll_path": ""})
            check("main: never auto-recovers", False, "expected ConnectionError")
        except ConnectionError:
            check("main: never auto-recovers", True)
        check("main: still degraded after time passes", scp._SESSION_PERMANENTLY_DEGRADED)
    finally:
        time.monotonic = orig_monotonic

# --- WORKER PROCESS: keeps the escalating cooldown + auto-recovery ----------
_reset()
with _as_worker_process():
    orig_monotonic = time.monotonic
    try:
        t = 200.0
        time.monotonic = _fake_monotonic([t + i * 1.0 for i in range(scp._SESSION_CRASH_CEILING)])
        result = False
        for _ in range(scp._SESSION_CRASH_CEILING):
            result = scp._note_dispatch_crash()
        final_now = t + scp._SESSION_CRASH_CEILING - 1
        check("worker: degraded at ceiling", scp._SESSION_PERMANENTLY_DEGRADED)
        check("worker: final call returns True", result)
        check("worker: cooldown scheduled", scp._SESSION_DEGRADED_UNTIL > final_now)
        check(
            "worker: first cooldown is the epoch-0 value",
            abs(scp._SESSION_DEGRADED_UNTIL - (final_now + scp._SESSION_DEGRADE_COOLDOWNS[0])) < 1e-6,
        )
        # Extra crashes while parked do NOT extend the cooldown, flag stays set.
        parked_until = scp._SESSION_DEGRADED_UNTIL
        scp._note_dispatch_crash()
        check("worker: while parked stays degraded", scp._SESSION_PERMANENTLY_DEGRADED)
        check("worker: cooldown unchanged", abs(scp._SESSION_DEGRADED_UNTIL - parked_until) < 1e-6)
        # During cooldown: refuse.
        time.monotonic = _fake_monotonic([t + 1.0])
        try:
            scp._ensure_session({"dll_path": "irrelevant"})
            check("worker: during cooldown raises", False, "expected ConnectionError")
        except ConnectionError as exc:
            check("worker: during cooldown parked/retry message", "parked" in str(exc) or "auto-retry" in str(exc))
        check("worker: during cooldown still degraded", scp._SESSION_PERMANENTLY_DEGRADED)
        # Past cooldown: worker clears the parked flag and proceeds to rebuild.
        time.monotonic = _fake_monotonic([parked_until + 1.0])
        proceeded = False
        try:
            scp._ensure_session({"dll_path": ""})
        except FileNotFoundError:
            proceeded = True  # reached the DLL-path guard -> recovery got past the parked check
        except ConnectionError:
            proceeded = False
        check("worker: after cooldown recovery proceeded", proceeded)
        check("worker: after cooldown parked flag cleared", not scp._SESSION_PERMANENTLY_DEGRADED)
    finally:
        time.monotonic = orig_monotonic

# --- WORKER: window reset -- old crashes do not count against a fresh window --
_reset()
with _as_worker_process():
    orig_monotonic = time.monotonic
    try:
        time.monotonic = _fake_monotonic([0.0, 1.0, 2000.0, 2001.0])
        scp._note_dispatch_crash()
        scp._note_dispatch_crash()
        check("worker: window reset count restarted", scp._SESSION_CRASH_COUNT == 2)
        scp._note_dispatch_crash()
        scp._note_dispatch_crash()
        check("worker: not degraded after fresh-window crashes", not scp._SESSION_PERMANENTLY_DEGRADED)
    finally:
        time.monotonic = orig_monotonic
        _reset()

print(f"\n{scp.__name__}: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
