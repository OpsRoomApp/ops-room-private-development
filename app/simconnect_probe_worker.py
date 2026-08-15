"""#98 T3 / #108 next tier — SimConnect probe worker (isolated read process).

The Fenix LVar litmus, the addon-enricher LVar probes, and (since the #108
next tier) ALL SimConnect reads - full position, minimal position and camera
state - run in this worker. It owns its OWN SimConnect session and serves
line-delimited JSON reads over stdin/stdout. If the native dispatch corrupts,
ONLY this process dies; the main app respawns it with a fresh heap and keeps
running (FSUIPC stays primary either way, and non-FSUIPC users recover
automatically because their only SimConnect client is this respawnable worker).

Protocol (one JSON object per line, both directions, ``id`` echoed back):
    -> {"cmd": "ping", "id": 1}
    <- {"ok": true, "pong": true, "id": 1}

    -> {"cmd": "read", "requests": [[\"L:FSDT_GSX_NUMPASSENGERS_BOARDING_TOTAL\", \"Number\"], ...], "id": 2}
    <- {"ok": true, "values": [..], "id": 2}            (None per failed read)

    -> {"cmd": "position", "id": 3}   (full sanitized position sample)
    -> {"cmd": "minimal", "id": 4}    (minimal sanitized sample)
    -> {"cmd": "camera", "id": 5}     ({"ok": bool, "value": int|None})

    -> {"cmd": "shutdown", "id": 6}
    <- {"ok": true, "bye": true, "id": 6}
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from typing import Any

logging.basicConfig(level=logging.ERROR, stream=sys.stderr)

_MAX_READ_ATTEMPTS = 3
_RECONNECT_BACKOFF_SECONDS = 5.0
_LVAR_CACHE: dict[tuple[str, str], Any] = {}
_LVAR_REQUESTS: dict[str, Any] = {}
_LVAR_SESSION_ID: int | None = None


def _read_line() -> str | None:
    line = sys.stdin.readline()
    if not line:
        return None
    return line.strip()


def _write(obj: dict[str, Any]) -> None:
    try:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def _session():
    """Create/reuse the worker's own guarded SimConnect session."""
    global _LVAR_SESSION_ID
    from .simconnect_position import _ensure_session, simconnect_diagnostics
    try:
        diagnostics = simconnect_diagnostics()
        sm, _aq = _ensure_session(diagnostics)
        if sm is not None and getattr(sm, "ok", False):
            _LVAR_SESSION_ID = id(sm)
            return sm
    except Exception:
        return None
    return None


def _read_lvars(sm: Any, requests: list[tuple[str, str]]) -> list[Any]:
    global _LVAR_REQUESTS, _LVAR_SESSION_ID
    if id(sm) != _LVAR_SESSION_ID:
        _LVAR_REQUESTS.clear()
        _LVAR_SESSION_ID = id(sm)
    from SimConnect.RequestList import Request  # type: ignore
    values: list[Any] = []
    for lvar, fmt in requests:
        try:
            units = (fmt or "Number").strip()
            if units.lower() in ("f", "float"):
                units = "Number"
            req = _LVAR_REQUESTS.get(lvar)
            if req is None:
                sm_name = f"L:{lvar}" if not lvar.startswith("L:") else lvar
                req = Request((sm_name.encode("ascii"), units.encode("ascii")), sm, _time=100, _settable=True, _attemps=3)
                _LVAR_REQUESTS[lvar] = req
            raw = req.value
            values.append(None if raw is None else float(raw))
        except Exception:
            values.append(None)
    return values


def _loop() -> int:
    last_session: Any = None
    last_attempt = 0.0
    while True:
        line = _read_line()
        if line is None:
            return 0
        try:
            msg = json.loads(line)
        except Exception:
            _write({"ok": False, "error": "bad-json"})
            continue
        cmd = str(msg.get("cmd") or "")
        rid = msg.get("id")

        def respond(payload: dict[str, Any]) -> None:
            try:
                payload["id"] = rid
            except Exception:
                pass
            _write(payload)

        if cmd == "shutdown":
            respond({"ok": True, "bye": True})
            return 0
        if cmd == "ping":
            respond({"ok": True, "pong": True})
            continue
        # #108 next tier: full / minimal position and camera reads now run
        # through this worker too, so the MAIN process never opens SimConnect
        # for reads (zero native-heap exposure; the worker is respawned on
        # death, which is what gives non-FSUIPC users automatic recovery).
        if cmd == "camera":
            value = None
            try:
                # In-process read ONLY -- never camera_state_simconnect():
                # in packaged builds that routes through the probe client,
                # which spawns a NEW worker to answer the same request (fork
                # bomb). The worker owns its own fresh heap, so the raw
                # in-process read is exactly what #108 intended here.
                from .simconnect_position import _camera_state_read_in_process
                value = _camera_state_read_in_process()
            except Exception:
                value = None
            respond({"ok": value is not None, "value": value})
            continue
        if cmd == "position":
            try:
                from .simconnect_position import _read_position_uncached, _sanitize_telemetry
                result = _sanitize_telemetry(_read_position_uncached())
            except Exception as exc:
                result = {"ok": False, "reason": f"worker position read failed: {type(exc).__name__}: {exc}"}
            respond(result)
            continue
        if cmd == "minimal":
            try:
                from .simconnect_position import _read_position_minimal_uncached, _sanitize_telemetry
                result = _sanitize_telemetry(_read_position_minimal_uncached())
                result.setdefault("minimal", True)
            except Exception as exc:
                result = {"ok": False, "reason": f"worker minimal read failed: {type(exc).__name__}: {exc}", "minimal": True}
            respond(result)
            continue
        if cmd != "read":
            respond({"ok": False, "error": "unknown-cmd"})
            continue
        requests = msg.get("requests") or []
        try:
            pairs = [(str(a), str(b)) for a, b in requests]
        except Exception:
            respond({"ok": False, "error": "bad-requests"})
            continue
        if not pairs:
            respond({"ok": True, "values": []})
            continue
        # Reconnect pacing: when there is no live session, respond with an
        # error immediately instead of sleeping on the pipe - the client owns
        # the timeout and killing a sleeping worker would just respawn it.
        sm = last_session
        if sm is None or not getattr(sm, "ok", False):
            now = time.monotonic()
            if now - last_attempt < _RECONNECT_BACKOFF_SECONDS:
                respond({"ok": False, "error": "no-simconnect"})
                continue
            last_attempt = now
            sm = _session()
            last_session = sm
        if sm is None:
            respond({"ok": False, "error": "no-simconnect"})
            continue
        try:
            values = _read_lvars(sm, pairs)
            respond({"ok": True, "values": values})
        except Exception:
            respond({"ok": False, "error": "read-failed"})


def run() -> int:
    threading.current_thread().name = "OpsRoom-ProbeWorker"
    try:
        return _loop()
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(run())
