"""#98 T3 / #108 next tier — client for the isolated SimConnect probe worker.

The worker owns the crash-prone SimConnect traffic (LVar probes, position,
identity and camera reads) in a separate process with its own native heap. If
the native dispatch corrupts, ONLY the worker dies; the client respawns it with
a fresh heap and the app keeps running - with or without FSUIPC.

This module spawns the worker lazily, health-checks it, and respawns it on
death or timeout. Transactions are serialized through a per-process reader
thread so concurrent callers (writer tick at up to 30 Hz, request threads,
enricher) can never interleave on the pipe, and every transaction has a hard
timeout so a hung worker can never block a caller for more than the limit.

Protocol (one JSON object per line, both directions, ``id`` echoed back):
    -> {"cmd": "ping", "id": 1}
    <- {"ok": true, "pong": true, "id": 1}

    -> {"cmd": "read", "requests": [[name, unit], ...], "id": 2}
    <- {"ok": true, "values": [..], "id": 2}

    -> {"cmd": "position", "id": 3}   (full sanitized position sample)
    -> {"cmd": "minimal", "id": 4}    (minimal sanitized sample)
    -> {"cmd": "camera", "id": 5}     ({"ok": bool, "value": int|None})

    -> {"cmd": "shutdown", "id": 6}
    <- {"ok": true, "bye": true, "id": 6}
"""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from typing import Any

_LOGGER_NAME = "opsroom.simconnect_probe"
_LOGGER = logging.getLogger(_LOGGER_NAME)

_PROC: subprocess.Popen | None = None
_PROC_LOCK = threading.Lock()
_QUEUE: queue.Queue | None = None
_READER_THREAD: threading.Thread | None = None
_TRANSACT_LOCK = threading.Lock()
_TXN_COUNTER = 0
_SPAWNED_AT = 0.0
_FAILED_UNTIL = 0.0
_WORKER_MAX_AGE_SECONDS = 1800.0  # recycle the worker periodically (fresh heap)
_CMD_TIMEOUT_SECONDS = 5.0
_FIRST_TXN_TIMEOUT_SECONDS = 14.0  # worker startup + first SimConnect connect
_FAIL_BACKOFF_SECONDS = 10.0


def _worker_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--probe-worker"]
    return [sys.executable, os.path.abspath(sys.argv[0]), "--probe-worker"]


def _start_reader(proc: subprocess.Popen) -> queue.Queue:
    """Dedicated reader thread pushes worker lines into a per-process queue.

    The queue is recreated for every spawned worker so a stale line from a
    killed process can never be mistaken for the next transaction's response.
    """
    global _QUEUE, _READER_THREAD
    q: queue.Queue = queue.Queue()

    def reader() -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                if line:
                    q.put(line.decode("utf-8", "replace"))
        except Exception:
            pass
        finally:
            q.put(None)  # EOF sentinel: the worker process went away

    thread = threading.Thread(target=reader, name="OpsRoom-ProbeReader", daemon=True)
    thread.start()
    _QUEUE = q
    _READER_THREAD = thread
    return q


def _ensure_proc() -> subprocess.Popen | None:
    global _PROC, _SPAWNED_AT, _FAILED_UNTIL
    # A probe worker must NEVER spawn another probe worker. If any code path
    # inside the worker routes a read back through this client, spawning here
    # would create an unbounded parent->child chain of OPS ROOM.exe
    # --probe-worker processes (fork bomb, observed live 2026-08-14: ~85
    # processes, still growing after the main app quit). Reads inside the
    # worker are in-process by design (#108); return None so the caller falls
    # back instead of spawning.
    if "--probe-worker" in sys.argv:
        return None
    now = time.monotonic()
    if now < _FAILED_UNTIL:
        return None
    with _PROC_LOCK:
        if _PROC is not None:
            if _PROC.poll() is None and now - _SPAWNED_AT < _WORKER_MAX_AGE_SECONDS:
                return _PROC
            _kill(_PROC)
            _PROC = None
        if _PROC is None:
            try:
                proc = subprocess.Popen(
                    _worker_command(),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) if os.name == "nt" else 0,
                )
                _PROC = proc
                _SPAWNED_AT = now
                _start_reader(proc)
                return proc
            except Exception as exc:
                _LOGGER.warning("SimConnect probe worker spawn failed: %s", exc)
                _FAILED_UNTIL = now + 30.0
                return None
    return None


def _kill(proc: subprocess.Popen) -> None:
    try:
        if proc.stdin:
            proc.stdin.close()
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=2)
    except Exception:
        pass
    # Closing stdout/stderr ends the reader thread cleanly (EOF sentinel)
    # and releases the pipe handles so respawns never leak file descriptors.
    for _attr in ("stdout", "stderr"):
        try:
            _handle = getattr(proc, _attr, None)
            if _handle is not None:
                _handle.close()
        except Exception:
            pass


def _transact(msg: dict[str, Any], timeout: float | None = None) -> dict[str, Any] | None:
    """Send one request and wait for its response; None on any failure.

    Serialized with ``_TRANSACT_LOCK`` so concurrent callers (the writer tick
    and request threads) never interleave writes/reads on the worker pipe. On
    timeout / EOF / JSON failure the worker is killed and a short backoff is
    armed so callers get fast failures instead of repeated 5 s stalls.
    """
    global _PROC, _TXN_COUNTER, _FAILED_UNTIL
    with _TRANSACT_LOCK:
        proc = _ensure_proc()
        if proc is None or proc.stdin is None or _QUEUE is None:
            return None
        q = _QUEUE
        _TXN_COUNTER += 1
        request = dict(msg)
        request["id"] = _TXN_COUNTER
        if timeout is None:
            timeout = _FIRST_TXN_TIMEOUT_SECONDS if time.monotonic() - _SPAWNED_AT < 20.0 else _CMD_TIMEOUT_SECONDS
        try:
            proc.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
            proc.stdin.flush()
        except Exception:
            _kill(proc)
            with _PROC_LOCK:
                _PROC = None
            _FAILED_UNTIL = time.monotonic() + _FAIL_BACKOFF_SECONDS
            return None
        try:
            line = q.get(timeout=timeout)
        except queue.Empty:
            _kill(proc)
            with _PROC_LOCK:
                _PROC = None
            _FAILED_UNTIL = time.monotonic() + _FAIL_BACKOFF_SECONDS
            return None
        if line is None:  # EOF sentinel: the worker exited
            _kill(proc)
            with _PROC_LOCK:
                _PROC = None
            _FAILED_UNTIL = time.monotonic() + _FAIL_BACKOFF_SECONDS
            return None
        try:
            return json.loads(line)
        except Exception:
            _kill(proc)
            with _PROC_LOCK:
                _PROC = None
            return None


def read_lvars(requests: list[tuple[str, str]]) -> list[Any] | None:
    """Read LVars through the worker; None means 'use in-process fallback'."""
    if not requests:
        return []
    try:
        resp = _transact({"cmd": "read", "requests": [[str(n), str(f)] for n, f in requests]})
        if resp and resp.get("ok") and isinstance(resp.get("values"), list):
            return resp["values"]
    except Exception:
        pass
    return None


def read_position() -> dict[str, Any] | None:
    """Full position sample through the worker; None = worker unavailable.

    The response is already sanitized by the worker (same shape as the
    in-process ``simconnect_position.read_position`` result).
    """
    try:
        resp = _transact({"cmd": "position"})
        if isinstance(resp, dict) and isinstance(resp.get("ok"), bool):
            return resp
    except Exception:
        pass
    return None


def read_position_minimal() -> dict[str, Any] | None:
    """Minimal position sample through the worker; None = worker unavailable."""
    try:
        resp = _transact({"cmd": "minimal"})
        if isinstance(resp, dict) and isinstance(resp.get("ok"), bool):
            return resp
    except Exception:
        pass
    return None


def camera_state() -> int | None:
    """CAMERA_STATE enum through the worker; None = unavailable/not-reported."""
    try:
        resp = _transact({"cmd": "camera"}, timeout=3.0)
        if isinstance(resp, dict) and resp.get("ok") and resp.get("value") is not None:
            return int(resp["value"])
    except Exception:
        pass
    return None


def ping() -> bool:
    try:
        resp = _transact({"cmd": "ping"}, timeout=3.0)
        return bool(resp and resp.get("pong"))
    except Exception:
        return False


def shutdown() -> None:
    global _PROC, _QUEUE, _READER_THREAD
    with _TRANSACT_LOCK:
        with _PROC_LOCK:
            if _PROC is not None:
                try:
                    if _PROC.stdin:
                        _PROC.stdin.write((json.dumps({"cmd": "shutdown", "id": _TXN_COUNTER + 1}) + "\n").encode("utf-8"))
                        _PROC.stdin.flush()
                except Exception:
                    pass
                _kill(_PROC)
                _PROC = None
            _QUEUE = None
            _READER_THREAD = None
