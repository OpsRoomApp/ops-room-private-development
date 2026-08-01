from __future__ import annotations

import hashlib
import logging
import random
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

import requests

_LOGGER = logging.getLogger("opsroom.hoppie")

from .settings_store import load_secrets, load_settings, save_settings
from .simbrief_client import cached_plan
from .vpilot_bridge import bridge_status
from .printer_client import print_receipt, format_cpdlc_receipt

ENDPOINT = "https://www.hoppie.nl/acars/system/connect.html"
_LOCK = threading.RLock()
_STOP = threading.Event()
_THREAD: threading.Thread | None = None
_ACTIVE = False
_MESSAGES: list[dict[str, Any]] = []
_SEEN: set[str] = set()
_LAST_ERROR = ""
_LAST_POLL: str | None = None
_NEXT_POLL: str | None = None
_CURRENT_ATC = ""
_NEXT_ATC = ""
_MIN = 1


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _callsign() -> tuple[str, str]:
    settings = load_settings()
    override = str(settings.get("integrations", {}).get("hoppie_callsign_override") or "").upper().strip()
    if override:
        return override, "OVERRIDE"
    bridge = bridge_status()
    callsign = str(bridge.get("callsign") or "").upper().strip()
    if callsign:
        return callsign, "VPILOT"
    user = str(settings.get("identity", {}).get("simbrief_user_id") or "")
    plan = cached_plan(user) if user else None
    callsign = str((plan or {}).get("callsign") or "").upper().strip()
    return (callsign, "SIMBRIEF") if callsign else ("", "NOT SET")


def _logon() -> str:
    return str(load_secrets().get("hoppie_logon_code") or "")


def _next_min() -> int:
    global _MIN
    with _LOCK:
        value = _MIN
        _MIN = 1 if _MIN >= 9999 else _MIN + 1
        return value


def _format_cpdlc_payload(payload: str) -> str:
    """Render Hoppie CPDLC/PDC payloads for humans without losing the raw packet.

    Hoppie /data2 payloads use @ as CPDLC field separators/placeholders.
    For display we turn the common PDC/clearance fields into readable lines, but
    the raw packet and message reference stay attached to the message object so
    WILCO/UNABLE/ROGER replies can reference the original uplink.
    """
    text = str(payload or "").replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return ""
    clean = " ".join(part.strip() for part in text.replace("@", " ").split())
    upper = clean.upper()
    if " PDC " in f" {upper} " or upper.startswith("DEPART REQUEST STATUS") or "REQUEST BEING PROCESSED" in upper or "RCD " in upper:
        # Keep status messages compact, then line-break the meaningful fields.
        for token in (" RCD RECEIVED ", " RCD REJECTED ", " REQUEST BEING PROCESSED ", " TYPE MISMATCH ", " UPDATE RCD AND RESEND ", " STANDBY "):
            clean = re.sub(token, "\n" + token.strip() + "\n", clean, flags=re.I)
        # PDC clearance fields.
        clean = re.sub(r"\s+(CLRD TO)\s+", r"\n\1 ", clean, flags=re.I)
        clean = re.sub(r"\s+(OFF)\s+", r"\n\1 ", clean, flags=re.I)
        clean = re.sub(r"\s+(VIA)\s+", r" \1 ", clean, flags=re.I)
        clean = re.sub(r"\s+(SQUAWK)\s+", r"\n\1 ", clean, flags=re.I)
        clean = re.sub(r"\s+(NEXT FREQ)\s+", r"\n\1 ", clean, flags=re.I)
        clean = re.sub(r"\s+(CLRD FL\d{2,3}|CLRD [0-9]{4,5}|START-UP APPROVED)\s*", r"\n\1", clean, flags=re.I)
        clean = re.sub(r"\n{2,}", "\n", clean).strip()
        return clean
    return "\n".join(part.strip() for part in text.split("@") if part.strip())


def _reply_options(response_code: str, payload: str) -> list[str]:
    code = str(response_code or "").upper().strip()
    text = str(payload or "").upper()
    if code == "WU":
        return ["WILCO", "UNABLE", "STANDBY"]
    if code == "AN":
        return ["AFFIRM", "NEGATIVE", "STANDBY"]
    if code in {"R", "RR"}:
        return ["ROGER", "STANDBY"]
    if "REQUEST BEING PROCESSED" in text or "RCD REJECTED" in text:
        return ["ROGER"]
    if "PDC" in text or "CLRD TO" in text:
        return ["WILCO", "UNABLE", "ROGER"]
    return []


def _record(direction: str, from_: str, to: str, type_: str, packet: str, raw: str = "") -> dict[str, Any]:
    digest = hashlib.sha1(f"{direction}|{from_}|{to}|{type_}|{packet}|{raw}".encode("utf-8", "ignore")).hexdigest()
    with _LOCK:
        if direction == "IN" and digest in _SEEN:
            return {}
        _SEEN.add(digest)
        item = {
            "id": digest[:12],
            "time": _utc(),
            "direction": direction,
            "from": from_,
            "to": to,
            "type": type_.lower(),
            "packet": packet,
            "raw_packet": packet,
            "display": packet.replace("@", "\n"),
            "message": packet.replace("@", "\n"),
            "reply_options": [],
        }
        if type_.lower() == "cpdlc":
            item.update(_parse_cpdlc(packet))
        _MESSAGES.append(item)
        del _MESSAGES[:-200]
        # Auto-print CPDLC if printer is enabled in settings
        _auto_print_if_configured(item)
        return item


def _split_data2(packet: str) -> tuple[str, str, str, str] | None:
    if not str(packet or "").startswith("/data2/"):
        return None
    rest = str(packet)[7:]
    pieces = rest.split("/")
    if not pieces:
        return None
    min_value = pieces[0].strip()
    # Common uplink: /data2/<min>/<response>/<payload>
    # Response/downlink: /data2/<min>/<mrn>/<response>/<payload>
    # Legacy/free text from some clients: /data2/<min>///<payload>
    if len(pieces) >= 4:
        mrn = pieces[1].strip()
        response = pieces[2].strip().upper()
        payload = "/".join(pieces[3:])
        return min_value, mrn, response, payload
    if len(pieces) >= 3:
        response = pieces[1].strip().upper()
        payload = "/".join(pieces[2:])
        return min_value, "", response, payload
    return min_value, "", "", "/".join(pieces[1:])


def _parse_cpdlc(packet: str) -> dict[str, Any]:
    result: dict[str, Any] = {"min": "", "mrn": "", "response": "", "message": packet.replace("@", "\n"), "payload": packet}
    split = _split_data2(packet)
    if split:
        min_value, mrn, response, payload = split
        rendered = _format_cpdlc_payload(payload)
        result.update({
            "min": min_value,
            "mrn": mrn,
            "response": response,
            "payload": payload,
            "message": rendered,
            "display": rendered,
            "reply_options": _reply_options(response, payload),
        })
    message = str(result.get("message") or "").strip().upper()
    global _CURRENT_ATC, _NEXT_ATC
    if message.startswith("LOGON ACCEPTED"):
        _CURRENT_ATC = "ACCEPTED"
    match = re.search(r"HANDOVER\s+([A-Z0-9]{3,8})", message)
    if match:
        _NEXT_ATC = match.group(1)
    return result


def _parse_poll(text: str, own_callsign: str) -> list[dict[str, Any]]:
    text = (text or "").strip()
    if not text.lower().startswith("ok"):
        raise RuntimeError(text or "Hoppie returned an empty response")
    payload = text[2:].strip()
    results: list[dict[str, Any]] = []
    i = 0
    while i < len(payload):
        while i < len(payload) and payload[i].isspace():
            i += 1
        if i >= len(payload) or payload[i] != "{":
            break
        start = i + 1
        depth = 1
        i += 1
        while i < len(payload) and depth:
            if payload[i] == "{": depth += 1
            elif payload[i] == "}": depth -= 1
            i += 1
        block = payload[start:i - 1].strip()
        match = re.match(r"(\S+)\s+(\S+)\s+\{(.*)\}\s*$", block, re.S)
        if not match:
            continue
        from_, type_, packet = match.groups()
        item = _record("IN", from_.upper(), own_callsign, type_, packet, raw=block)
        if item:
            if item.get("type") == "cpdlc" and str(item.get("message") or "").upper().startswith("LOGON ACCEPTED"):
                global _CURRENT_ATC
                _CURRENT_ATC = from_.upper()
            results.append(item)
    return results


def _request(to: str, type_: str, packet: str = "") -> str:
    callsign, _ = _callsign()
    logon = _logon()
    if not callsign:
        raise RuntimeError("Hoppie callsign is not available. Load SimBrief, connect vPilot, or set an override.")
    if not logon:
        raise RuntimeError("Hoppie logon code is not configured in the desktop Host")
    response = requests.post(
        ENDPOINT,
        data={"logon": logon, "from": callsign, "to": to or "SERVER", "type": type_, "packet": packet},
        timeout=15,
        headers={"User-Agent": "OPS ROOM/0.23.4 Hoppie client"},
    )
    response.raise_for_status()
    text = response.text.strip()
    if text.lower().startswith("error"):
        raise RuntimeError(text)
    return text


def _activate() -> None:
    global _ACTIVE
    _ACTIVE = True
    start_polling()


def ping() -> dict[str, Any]:
    global _LAST_ERROR
    try:
        result = _request("SERVER", "ping", "")
        _LAST_ERROR = ""
        return {"ok": result.lower().startswith("ok"), "response": result}
    except Exception as exc:
        _LAST_ERROR = f"{type(exc).__name__}: {exc}"
        return {"ok": False, "error": _LAST_ERROR}


def send_message(to: str, type_: str, packet: str) -> dict[str, Any]:
    global _LAST_ERROR
    type_ = str(type_ or "telex").lower()
    if type_ not in {"telex", "cpdlc", "progress", "position", "inforeq"}:
        raise ValueError("Unsupported Hoppie message type")
    to = str(to or "SERVER").upper().strip()
    packet = str(packet or "").strip()
    if not packet:
        raise ValueError("Message text is required")
    try:
        response = _request(to, type_, packet)
        if not response.lower().startswith("ok"):
            raise RuntimeError(response)
        callsign, _ = _callsign()
        _record("OUT", callsign, to, type_, packet)
        _LAST_ERROR = ""
        _activate()
        return {"ok": True, "response": response}
    except Exception as exc:
        _LAST_ERROR = f"{type(exc).__name__}: {exc}"
        raise


def request_info(kind: str, station: str) -> dict[str, Any]:
    kind = str(kind or "").lower()
    if kind not in {"metar", "taf", "shorttaf", "vatatis", "peatis", "ivaoatis"}:
        raise ValueError("Unsupported information request")
    station = str(station or "").upper().strip()
    if not station:
        raise ValueError("Station is required")
    return send_message("SERVER", "inforeq", f"{kind} {station}")


def build_pdc_request(callsign: str, aircraft: str, destination: str, departure: str = "", stand: str = "", atis: str = "") -> str:
    callsign = re.sub(r"[^A-Z0-9]", "", str(callsign or "").upper()) or "CALLSIGN"
    aircraft = re.sub(r"[^A-Z0-9]", "", str(aircraft or "").upper()) or "ACFT"
    destination = re.sub(r"[^A-Z0-9]", "", str(destination or "").upper()) or "DEST"
    departure = re.sub(r"[^A-Z0-9]", "", str(departure or "").upper())
    stand = re.sub(r"[^A-Z0-9-]", "", str(stand or "").upper()) or "STAND"
    atis = re.sub(r"[^A-Z0-9]", "", str(atis or "").upper()) or "-"
    middle = f"{callsign} {aircraft} TO {destination}"
    if departure:
        middle += f" AT {departure}"
    middle += f" STAND {stand} ATIS {atis}"
    return f"REQUEST PREDEP CLEARANCE\n{middle}"


def pdc_request(station: str, aircraft: str = "", destination: str = "", departure: str = "", stand: str = "", atis: str = "") -> dict[str, Any]:
    station = re.sub(r"[^A-Z0-9]", "", str(station or departure or "").upper())
    if not station:
        raise ValueError("PDC station is required")
    callsign, _source = _callsign()
    packet = build_pdc_request(callsign, aircraft, destination, departure, stand, atis)
    result = send_message(station, "telex", packet)
    result["pdc"] = {"station": station, "type": "telex", "message": packet, "status": "SENT TO HOPPIE / WAITING FOR ATC RESPONSE"}
    return result


def cpdlc_send(to: str, message: str, mrn: str = "", response: str = "") -> dict[str, Any]:
    min_value = _next_min()
    text = str(message or "").strip().upper().replace("\n", "@").replace("/", "-")
    packet = f"/data2/{min_value}/{str(mrn or '').strip()}/{str(response or '').strip().upper()}/{text}"
    result = send_message(str(to or "").upper(), "cpdlc", packet)
    result["min"] = min_value
    return result


def cpdlc_logon(atc: str) -> dict[str, Any]:
    global _CURRENT_ATC, _NEXT_ATC
    atc = str(atc or "").upper().strip()
    if not atc:
        raise ValueError("ATC facility is required")
    _NEXT_ATC = atc
    result = cpdlc_send(atc, "REQUEST LOGON")
    result["status"] = "LOGON REQUEST SENT"
    return result


def cpdlc_reply(message_id: str, reply: str) -> dict[str, Any]:
    reply = str(reply or "").upper().strip()
    if reply not in {"WILCO", "UNABLE", "STANDBY", "ROGER", "AFFIRM", "NEGATIVE"}:
        raise ValueError("Unsupported CPDLC response")
    with _LOCK:
        source = next((item for item in reversed(_MESSAGES) if item.get("id") == message_id), None)
    if not source:
        raise ValueError("The referenced CPDLC message is no longer available")
    # For a pilot response to an uplink, the outgoing CPDLC message must carry
    # the controller message reference in the MRN field. The response itself does
    # not ask for another response, so use N. Sending WU/AN again causes many
    # ATC-side clients to treat the reply as a new request or reject it as a
    # type mismatch.
    response_code = "N"
    result = cpdlc_send(str(source.get("from") or ""), reply, mrn=str(source.get("min") or ""), response=response_code)
    result["referenced_message_id"] = source.get("id")
    result["referenced_min"] = source.get("min")
    return result


def poll_once() -> dict[str, Any]:
    global _LAST_POLL, _LAST_ERROR
    callsign, _ = _callsign()
    try:
        response = _request("SERVER", "poll", "")
        received = _parse_poll(response, callsign)
        _LAST_POLL = _utc()
        _LAST_ERROR = ""
        return {"ok": True, "received": len(received), "response": response}
    except Exception as exc:
        _LAST_ERROR = f"{type(exc).__name__}: {exc}"
        return {"ok": False, "error": _LAST_ERROR}


def _loop() -> None:
    global _NEXT_POLL
    while not _STOP.is_set():
        settings = load_settings().get("integrations", {})
        if not _ACTIVE or not bool(settings.get("hoppie_auto_poll", True)):
            _NEXT_POLL = None
            _STOP.wait(2.0)
            continue
        wait = random.uniform(45.0, 75.0)
        _NEXT_POLL = datetime.fromtimestamp(time.time() + wait, timezone.utc).isoformat().replace("+00:00", "Z")
        if _STOP.wait(wait):
            break
        poll_once()


def _auto_print_if_configured(item: dict[str, Any]) -> None:
    """Auto-print a CPDLC message if the printer is enabled in settings."""
    try:
        settings = load_settings()
        printing = settings.get("printing", {})
        if not printing.get("enabled", False):
            return
        if not printing.get("cpdlc_auto_print", True):
            return
        printer_name = str(printing.get("printer_name", "") or "").strip()
        if not printer_name:
            return
        if item.get("type") != "cpdlc":
            return
        receipt_lines = format_cpdlc_receipt(item)
        # Fire and forget — don't block the polling loop
        threading.Thread(
            target=lambda: print_receipt(printer_name, receipt_lines, title="CPDLC RECEIPT"),
            name="OpsRoom-Print",
            daemon=True,
        ).start()
    except Exception as exc:
        # Silently ignore print errors — they must never break CPDLC
        _LOGGER.debug("Auto-print failed: %s", exc)


def start_polling() -> None:
    global _THREAD
    with _LOCK:
        if _THREAD and _THREAD.is_alive():
            return
        _STOP.clear()
        _THREAD = threading.Thread(target=_loop, name="OpsRoom-Hoppie", daemon=True)
        _THREAD.start()


def stop_polling() -> None:
    global _ACTIVE
    _ACTIVE = False


def set_callsign_override(value: str) -> dict[str, Any]:
    settings = load_settings()
    cleaned = "".join(ch for ch in str(value or "").upper() if ch.isalnum())[:16]
    settings.setdefault("integrations", {})["hoppie_callsign_override"] = cleaned
    save_settings(settings)
    return status()


def status() -> dict[str, Any]:
    callsign, source = _callsign()
    settings = load_settings().get("integrations", {})
    with _LOCK:
        return {
            "ok": True,
            "configured": bool(_logon()),
            "callsign": callsign,
            "callsign_source": source,
            "callsign_override": str(settings.get("hoppie_callsign_override") or ""),
            "active": _ACTIVE,
            "auto_poll": bool(settings.get("hoppie_auto_poll", True)),
            "last_poll": _LAST_POLL,
            "next_poll": _NEXT_POLL,
            "last_error": _LAST_ERROR,
            "current_atc": _CURRENT_ATC,
            "next_atc": _NEXT_ATC,
            "messages": list(reversed(_MESSAGES[-100:])),
            "warning": "Do not use another Hoppie client with the same callsign while OPS ROOM polling is active.",
        }
