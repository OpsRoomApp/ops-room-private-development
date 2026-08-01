from __future__ import annotations

import re
import threading
import time
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

_LOCK = threading.RLock()
_STATE: dict[str, Any] = {
    "last_heartbeat": 0.0,
    "data": {},
    "capabilities": [],
    "events": deque(maxlen=500),
    "messages": deque(maxlen=250),
    "commands": deque(maxlen=100),
    "next_event_id": 1,
    "next_command_id": 1,
    "handoff": None,
}
_FREQ_RE = re.compile(r"(?<!\d)(1(?:1[8-9]|2\d|3[0-6])\.\d{3})(?!\d)")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _next_id(key: str) -> int:
    value = int(_STATE.get(key) or 1)
    _STATE[key] = value + 1
    return value


def _handoff_from_message(sender: str, message: str, received_utc: str) -> dict[str, Any] | None:
    text = str(message or "")
    lowered = text.lower()
    if not any(word in lowered for word in ("contact", "monitor", "frequency", "freq", "tune")):
        return None
    match = _FREQ_RE.search(text)
    if not match:
        return None
    frequency = float(match.group(1))
    return {
        "frequency": f"{frequency:.3f}",
        "from": str(sender or "").upper(),
        "message": text,
        "received_utc": received_utc,
        "source": "vpilot_private_message",
        "confirmed": True,
    }


def record_heartbeat(payload: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        _STATE["last_heartbeat"] = time.monotonic()
        current = dict(_STATE.get("data") or {})
        current.update(dict(payload or {}))
        _STATE["data"] = current
        if isinstance(payload.get("capabilities"), list):
            _STATE["capabilities"] = list(payload["capabilities"])
    return bridge_status()


def record_event(payload: dict[str, Any]) -> dict[str, Any]:
    event_type = str(payload.get("type") or "event").strip().lower()
    received_utc = str(payload.get("received_utc") or _utc_now())
    with _LOCK:
        event = dict(payload)
        event["id"] = _next_id("next_event_id")
        event["type"] = event_type
        event["received_utc"] = received_utc
        _STATE["events"].append(event)

        data = dict(_STATE.get("data") or {})
        if event_type == "network_connected":
            data.update({
                "network_connected": True,
                "cid": payload.get("cid"),
                "callsign": payload.get("callsign"),
                "type_code": payload.get("type_code"),
                "selcal": payload.get("selcal"),
                "observer_mode": bool(payload.get("observer_mode")),
            })
        elif event_type == "network_disconnected":
            data["network_connected"] = False
        elif event_type == "session_ended":
            data["network_connected"] = False
        _STATE["data"] = data

        if event_type in {"private_message", "radio_message", "broadcast_message", "command_result", "selcal"}:
            message = {
                "id": event["id"],
                "type": event_type,
                "from": str(payload.get("from") or "").upper(),
                "to": str(payload.get("to") or "").upper(),
                "message": str(payload.get("message") or ""),
                "frequencies": list(payload.get("frequencies") or []),
                "success": payload.get("success"),
                "received_utc": received_utc,
                "outbound": bool(payload.get("outbound", False)),
            }
            _STATE["messages"].append(message)
            if event_type == "private_message" and not message["outbound"]:
                handoff = _handoff_from_message(message["from"], message["message"], received_utc)
                if handoff:
                    _STATE["handoff"] = handoff
    return {"ok": True, "event_id": event["id"]}


def queue_command(action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    action = str(action or "").strip().lower()
    status = bridge_status()
    if not status.get("connected"):
        raise ValueError("The OPS ROOM vPilot bridge is not online")
    if not status.get("network_connected"):
        raise ValueError("vPilot is not connected to the VATSIM network")
    allowed = {"send_private_message", "send_radio_message", "set_mode_c", "squawk_ident"}
    if action not in allowed:
        raise ValueError(f"Unsupported vPilot action: {action}")
    command_payload = dict(payload or {})
    if action == "send_private_message":
        recipient = str(command_payload.get("to") or "").strip().upper()
        message = str(command_payload.get("message") or "").strip()
        if not recipient or not message:
            raise ValueError("Recipient and message are required")
        if len(message) > 450:
            raise ValueError("Private message is too long")
        command_payload = {"to": recipient, "message": message}
    elif action == "send_radio_message":
        message = str(command_payload.get("message") or "").strip()
        if not message:
            raise ValueError("Message is required")
        if len(message) > 450:
            raise ValueError("Radio message is too long")
        command_payload = {"message": message}
    elif action == "set_mode_c":
        command_payload = {"enabled": bool(command_payload.get("enabled"))}

    with _LOCK:
        command = {
            "id": _next_id("next_command_id"),
            "action": action,
            "payload": command_payload,
            "created_utc": _utc_now(),
        }
        _STATE["commands"].append(command)
    return {"ok": True, "command": deepcopy(command)}


def poll_commands(limit: int = 20) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    with _LOCK:
        while _STATE["commands"] and len(items) < max(1, min(int(limit), 50)):
            items.append(dict(_STATE["commands"].popleft()))
    return {"ok": True, "commands": items, "server_utc": _utc_now()}


def message_status(limit: int = 100, after_id: int = 0) -> dict[str, Any]:
    with _LOCK:
        messages = [deepcopy(item) for item in _STATE["messages"]]
        events = [deepcopy(item) for item in _STATE["events"] if int(item.get("id") or 0) > int(after_id or 0)]
        handoff = deepcopy(_STATE.get("handoff"))
    limit = max(1, min(int(limit), 250))
    return {
        "ok": True,
        "messages": messages[-limit:],
        "events": events[-limit:],
        "handoff": handoff,
        "bridge": bridge_status(),
        "updated_utc": _utc_now(),
    }


def bridge_status() -> dict[str, Any]:
    with _LOCK:
        age = time.monotonic() - float(_STATE.get("last_heartbeat") or 0.0) if _STATE.get("last_heartbeat") else None
        connected = age is not None and age < 15.0
        data = deepcopy(_STATE.get("data") or {})
        capabilities = deepcopy(_STATE.get("capabilities") or [])
        handoff = deepcopy(_STATE.get("handoff"))
        unread = len([item for item in _STATE["messages"] if item.get("type") == "private_message" and not item.get("outbound")])
    network_connected = bool(data.get("network_connected"))
    callsign = data.get("callsign")
    if connected and callsign:
        detail = f"{callsign}{' / OBSERVER' if data.get('observer_mode') else ''}"
    elif connected:
        detail = data.get("version") or "Plugin connected to OPS ROOM"
    else:
        detail = "Install the OPS ROOM vPilot bridge from the desktop host."
    return {
        "ok": True,
        "connected": connected,
        "network_connected": network_connected,
        "observer_mode": bool(data.get("observer_mode")),
        "state": "connected" if connected else "standby",
        "label": "BRIDGE ONLINE" if connected else "PLUGIN REQUIRED",
        "detail": detail,
        "age_seconds": round(age, 1) if age is not None else None,
        "data": data,
        "capabilities": capabilities,
        "handoff": handoff,
        "message_count": unread,
        "updated_utc": _utc_now(),
    }
