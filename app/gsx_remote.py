from __future__ import annotations

import json
import os
import re
import configparser
import threading
import time
import socket
import urllib.request
from urllib.parse import urlparse, urlunparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .settings_store import load_settings, app_data_dir
from .data_loader import nearest_airport, callsign_prefix, load_airlines
from .simbrief_client import cached_plan
from .fenix_adapter import (
    status as fenix_status,
    start_gsx_boarding as fenix_start_gsx_boarding,
    loading_signature as fenix_loading_signature,
    loading_targets as fenix_loading_targets,
    loading_progress as fenix_loading_progress,
    set_cargo_door as fenix_set_cargo_door,
    set_entry_door as fenix_set_entry_door,
    set_ground_power as fenix_set_ground_power,
    set_chocks as fenix_set_chocks,
    start_deboarding as fenix_start_deboarding,
)
from .fenix_gsx_loading_state_machine import FenixGsxLoadingStateMachine, FenixGsxLoadingSnapshot, GsxMenuEntry
from .simconnect_position import _LOCK as SIM_LOCK, _ensure_session, _send_sim_event, simconnect_diagnostics, read_position
from .telemetry_provider import read_telemetry

REG_PATH = r"SOFTWARE\FSDreamTeam"
REG_VALUE = "root"
DEFAULT_ROOT = Path(r"C:\Program Files (x86)\Addon Manager")
MENU_RELATIVE = Path("MSFS") / "fsdreamteam-gsx-pro" / "html_ui" / "InGamePanels" / "FSDT_GSX_Panel" / "menu"

LVAR = {
    "couatl": "L:FSDT_GSX_COUATL_STARTED",
    "menu_open": "L:FSDT_GSX_MENU_OPEN",
    "menu_choice": "L:FSDT_GSX_MENU_CHOICE",
    "jetway": "L:FSDT_GSX_JETWAY",
    "jetway_operation": "L:FSDT_GSX_OPERATEJETWAYS_STATE",
    "stairs": "L:FSDT_GSX_STAIRS",
    "stairs_operation": "L:FSDT_GSX_OPERATESTAIRS_STATE",
    "refuel": "L:FSDT_GSX_REFUELING_STATE",
    "catering": "L:FSDT_GSX_CATERING_STATE",
    "boarding": "L:FSDT_GSX_BOARDING_STATE",
    "deboarding": "L:FSDT_GSX_DEBOARDING_STATE",
    "departure": "L:FSDT_GSX_DEPARTURE_STATE",
    "gpu": "L:FSDT_GSX_GPU_STATE",
    "pushback": "L:FSDT_GSX_PUSHBACK_STATUS",
    "deice": "L:FSDT_GSX_DEICE_STATE",
    "lavatory": "L:FSDT_GSX_LAVATORY_STATE",
    "water": "L:FSDT_GSX_WATER_STATE",
    "cleaning": "L:FSDT_GSX_CLEANING_STATE",
    "pax_target": "L:FSDT_GSX_NUMPASSENGERS",
    "pax_board": "L:FSDT_GSX_NUMPASSENGERS_BOARDING_TOTAL",
    "pax_deboard": "L:FSDT_GSX_NUMPASSENGERS_DEBOARDING_TOTAL",
    "cargo_board": "L:FSDT_GSX_BOARDING_CARGO_PERCENT",
    "cargo_deboard": "L:FSDT_GSX_DEBOARDING_CARGO_PERCENT",
}

SERVICE_KEYS = ("boarding", "deboarding", "catering", "refuel", "water", "lavatory", "cleaning", "deice", "departure", "gpu")
SERVICE_LABELS = {
    "boarding": "BOARDING",
    "deboarding": "DEBOARDING",
    "catering": "CATERING",
    "refuel": "REFUELLING",
    "water": "WATER",
    "lavatory": "LAVATORY",
    "cleaning": "CLEANING",
    "deice": "DE-ICING",
    "departure": "DEPARTURE",
    "gpu": "GPU",
    "jetway": "JETWAY",
    "stairs": "STAIRS",
    "pushback": "PUSHBACK",
}
STATE_LABELS = {
    0: "UNKNOWN",
    1: "AVAILABLE",
    2: "NOT AVAILABLE",
    3: "BYPASSED",
    4: "REQUESTED",
    5: "ACTIVE",
    6: "COMPLETED",
    7: "COMPLETING",
}
STATE_TONES = {0: "off", 1: "ready", 2: "fault", 3: "off", 4: "waiting", 5: "active", 6: "complete", 7: "waiting"}

ALIASES = {
    "boarding": ("request boarding", "start boarding", "begin boarding", "continue boarding", "resume boarding", "board passengers", "passenger boarding"),
    "deboarding": ("request deboarding", "deboarding"),
    "catering": ("request catering", "catering"),
    "refuel": ("request refueling", "request refuelling", "request refuel", "fuel truck", "fuel service", "refuel aircraft", "refueling", "refuelling", "fuel"),
    "water": ("request water", "water service", "water"),
    "lavatory": ("request lavatory", "lavatory service", "lavatory"),
    "cleaning": ("request cleaning", "cleaning service", "cleaning"),
    "deice": ("request de-icing", "request deicing", "de-icing", "deicing"),
    "pushback": ("prepare for pushback", "request pushback", "start pushback", "pushback", "departure"),
    "jetway": ("operate jetways", "operate jetway", "jetways", "jetway"),
    "stairs": ("operate stairs", "stairs"),
    "gpu": ("operate gpu", "ground power unit", "ground power", "gpu"),
}
ADDITIONAL_ALIASES = ("additional services", "more services", "next page")
CONTINUE_PUSHBACK_ALIASES = ("continue pushback", "continue push-back", "continue push back", "resume pushback", "resume push-back", "continue departure", "resume departure")

_LOCK = threading.RLock()
_CACHE: dict[str, Any] | None = None
_CACHE_TIME = 0.0
_LOG: list[dict[str, Any]] = []
_LAST_RECORD: tuple[str, str, float] | None = None
_LAST_AUTOMATION_RECORD: tuple[str, str, float] | None = None
_LVAR_REQUESTS: dict[str, Any] = {}
_LVAR_SESSION_ID: int | None = None
_STABLE_VALUES: dict[str, Any] = {}
_STABLE_UPDATED: dict[str, float] = {}
_LAST_CONNECTED_TIME = 0.0
_LAST_SELECTED_OPERATOR = ""
_LAST_SELECTED_OPERATOR_FLIGHT = ""
# Authoritative operating-airline brand resolved EARLY (at SimBrief-fetch time)
# and stored durably as callsign -> operator brand. This is the top-priority
# GSX operator/handler match source.
_OPERATOR_STORE_FILE = "gsx_operator.json"
_STORED_OPERATOR: dict[str, Any] | None = None
_STORED_OPERATOR_LOCK = threading.RLock()
_LAST_BEACON_STATE: bool | None = None
_LAST_BEACON_PUSHBACK = 0.0
_OFFICIAL_CACHE: dict[str, Any] | None = None
_OFFICIAL_CACHE_TIME = 0.0
_OFFICIAL_STATE: dict[str, Any] = {}
_OFFICIAL_URL = ""
_AUTOMATION_REQUESTED_MONO: dict[str, float] = {}
_AUTOMATION_LOCK = threading.RLock()
_AUTOMATION_STOP = threading.Event()
_AUTOMATION_THREAD: threading.Thread | None = None
_OPERATOR_OBSERVER_THREAD: threading.Thread | None = None
_OPERATOR_OBSERVER_STOP = threading.Event()
_OPERATOR_OBSERVER_CONNECTED = threading.Event()
_OPERATOR_OBSERVER_LOCK = threading.RLock()
_OPERATOR_OBSERVER_SEQUENCE = 0
_PUSHBACK_KEEPALIVE_THREAD: threading.Thread | None = None
_PUSHBACK_KEEPALIVE_STOP = threading.Event()
_PUSHBACK_KEEPALIVE_LAST = 0.0
_PUSHBACK_ACTIVE_SINCE = 0.0
_AUTOMATION: dict[str, Any] = {
    "running": False,
    "stage": "IDLE",
    "detail": "READY",
    "started_at": None,
    "updated_at": None,
    "requested": [],
    "requested_at": {},
    "history": [],
    "mode": "AUTO",
}
_FENIX_GSX_MACHINE = FenixGsxLoadingStateMachine()
_FENIX_LOADING_STATE: dict[str, Any] = {
    "state": "FENIX_LOADING_IDLE",
    "phase": "FENIX_LOADING_IDLE",
    "signature": None,
    "started_at": None,
    "started_mono": 0.0,
    "targets": {},
    "last_progress": {},
    "last_decision": {},
    "last_gsx_action": {},
    "failure_reason": "",
    "boarding_action_sent": False,
    "menu_open_requested_mono": 0.0,
}
_FENIX_SNAPSHOT_REFRESH_AT = 0.0  # monotonic TTL for the Live OFP loadsheet snapshot
_MOCK_STATE: dict[str, Any] = {
    "boarding": 5,
    "deboarding": 1,
    "catering": 6,
    "refuel": 5,
    "water": 1,
    "lavatory": 1,
    "cleaning": 1,
    "deice": 2,
    "departure": 1,
    "gpu": 5,
    "jetway": 1,
    "stairs": 0,
    "pushback": 0,
    "pax_target": 184,
    "pax_board": 112,
    "pax_deboard": 0,
    "cargo_board": 67,
    "cargo_deboard": 0,
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _record(kind: str, text: str) -> None:
    global _LAST_RECORD
    now = time.monotonic()
    if _LAST_RECORD and _LAST_RECORD[0] == kind and _LAST_RECORD[1] == text and now - _LAST_RECORD[2] < 20.0:
        return
    _LAST_RECORD = (kind, text, now)
    _LOG.append({"time": _utc(), "kind": kind, "text": text})
    del _LOG[:-80]


def _configured_root() -> Path | None:
    raw = str(load_settings().get("integrations", {}).get("gsx_root") or "").strip()
    if raw:
        return Path(raw).expanduser()
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH) as key:
                value, _ = winreg.QueryValueEx(key, REG_VALUE)
                if value:
                    return Path(str(value))
        except OSError:
            pass
    return DEFAULT_ROOT


def menu_path() -> Path:
    root = _configured_root() or DEFAULT_ROOT
    return root / MENU_RELATIVE


def _clean_menu_line(value: str) -> str:
    value = value.replace("\x00", "").strip()
    value = re.sub(r"\s+", " ", value)
    return value


def read_menu() -> dict[str, Any]:
    if os.getenv("OPSROOM_GSX_MOCK") == "1":
        return {
            "available": True,
            "title": "ACTIVATE GROUND SERVICES",
            "options": ["Request Boarding", "Request Catering", "Request Refueling", "Request Pushback", "Operate Jetways"],
            "updated": _utc(),
        }
    path = menu_path()
    if not path.is_file():
        return {"available": False, "title": "NO GSX MENU", "options": [], "reason": "GSX menu file is not available"}
    lines: list[str] = []
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            lines = [_clean_menu_line(x) for x in path.read_text(encoding=encoding, errors="strict").splitlines()]
            break
        except (UnicodeError, OSError):
            continue
    lines = [x for x in lines if x]
    if not lines:
        return {"available": False, "title": "EMPTY GSX MENU", "options": [], "reason": "GSX menu file is empty"}
    try:
        updated = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")
    except OSError:
        updated = _utc()
    return {"available": True, "title": lines[0], "options": lines[1:], "updated": updated}


def _lvar_request(sm: Any, name: str) -> Any:
    global _LVAR_SESSION_ID
    session_id = id(sm)
    if _LVAR_SESSION_ID != session_id:
        _LVAR_REQUESTS.clear()
        _LVAR_SESSION_ID = session_id
    request = _LVAR_REQUESTS.get(name)
    if request is None:
        from SimConnect.RequestList import Request  # type: ignore
        request = Request((name.encode("ascii"), b"Number"), sm, _time=100, _settable=True)
        _LVAR_REQUESTS[name] = request
    return request


def _read_value(sm: Any, name: str) -> float | None:
    try:
        value = _lvar_request(sm, name).value
        return None if value is None else float(value)
    except Exception:
        return None


def _write_value(sm: Any, name: str, value: float) -> bool:
    try:
        request = _lvar_request(sm, name)
        request.value = float(value)
        return True
    except Exception:
        return False


def _state_entry(key: str, raw: Any) -> dict[str, Any]:
    if raw is None:
        return {"key": key, "label": SERVICE_LABELS.get(key, key.upper()), "raw": None, "state": "NO DATA", "tone": "off"}
    numeric = int(round(float(raw)))
    return {
        "key": key,
        "label": SERVICE_LABELS.get(key, key.upper()),
        "raw": numeric,
        "state": STATE_LABELS.get(numeric, f"STATE {numeric}"),
        "tone": STATE_TONES.get(numeric, "waiting"),
    }


def _binary_entry(key: str, raw: Any, active_label: str = "ACTIVE", inactive_label: str = "STANDBY") -> dict[str, Any]:
    numeric = int(round(float(raw or 0))) if raw is not None else None
    active = bool(numeric) if numeric is not None else False
    return {
        "key": key,
        "label": SERVICE_LABELS.get(key, key.upper()),
        "raw": numeric,
        "state": active_label if active else ("NO DATA" if numeric is None else inactive_label),
        "tone": "active" if active else "off",
    }


def _mock_status() -> dict[str, Any]:
    services = {key: _state_entry(key, _MOCK_STATE.get(key)) for key in SERVICE_KEYS}
    services["jetway"] = _binary_entry("jetway", _MOCK_STATE.get("jetway"), "CONNECTED", "DISCONNECTED")
    services["stairs"] = _binary_entry("stairs", _MOCK_STATE.get("stairs"), "POSITIONED", "STOWED")
    services["pushback"] = _binary_entry("pushback", _MOCK_STATE.get("pushback"), "ACTIVE", "STANDBY")
    return {
        "ok": True,
        "installed": True,
        "connected": True,
        "couatl_started": 1,
        "services": services,
        "progress": {
            "passengers_target": _MOCK_STATE["pax_target"],
            "passengers_boarding_total": _MOCK_STATE["pax_board"],
            "passengers_deboarding_total": _MOCK_STATE["pax_deboard"],
            "boarding_cargo_percent": _MOCK_STATE["cargo_board"],
            "deboarding_cargo_percent": _MOCK_STATE["cargo_deboard"],
        },
        "menu": read_menu(),
        "official_remote": _official_status(force=False),
        "control_server": _control_server_status(),
        "events": list(reversed(_LOG[-30:])),
        "sampled_at": _utc(),
        "source": "mock",
    }


def _couatl_addons_ini_path() -> Path:
    base = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "Virtuali" / "CouatlAddons.ini"


def _remote_port_from_couatl_ini() -> tuple[int | None, str]:
    """Read GSX Remote API port as documented in the GSX 4.0.8 manual.

    Couatl Remote API v2 serves HTTP and WebSocket on the same localhost port.
    The manual says clients should read [gsx] remote_server_port from
    %APPDATA%\\Virtuali\\CouatlAddons.ini and fall back to 8744 when missing.
    """
    path = _couatl_addons_ini_path()
    try:
        if not path.is_file():
            return None, f"CouatlAddons.ini not found at {path}"
        parser = configparser.ConfigParser()
        parser.read(path, encoding="utf-8")
        raw = parser.get("gsx", "remote_server_port", fallback="").strip()
        if not raw:
            return None, f"remote_server_port missing in {path}; using default 8744"
        port = int(raw)
        if not (1 <= port <= 65535):
            return None, f"remote_server_port out of range in {path}: {raw!r}"
        return port, f"remote_server_port read from {path}"
    except Exception as exc:
        return None, f"{type(exc).__name__} reading {path}: {exc}; using default 8744"


def _remote_port() -> int:
    settings = load_settings().get("integrations", {})
    raw = settings.get("gsx_remote_port")
    try:
        if str(raw or "").strip():
            port = int(raw)
            if 1 <= port <= 65535:
                return port
    except (TypeError, ValueError):
        pass
    port, _reason = _remote_port_from_couatl_ini()
    return int(port or 8744)


def _remote_port_diagnostics() -> dict[str, Any]:
    settings = load_settings().get("integrations", {})
    raw = str(settings.get("gsx_remote_port") or "").strip()
    ini_port, ini_reason = _remote_port_from_couatl_ini()
    if raw:
        try:
            port = int(raw)
            return {"port": port, "source": "OPS ROOM settings", "couatl_ini": str(_couatl_addons_ini_path()), "ini_reason": ini_reason}
        except Exception as exc:
            return {"port": int(ini_port or 8744), "source": "CouatlAddons.ini/default", "settings_error": f"{type(exc).__name__}: {exc}", "couatl_ini": str(_couatl_addons_ini_path()), "ini_reason": ini_reason}
    return {"port": int(ini_port or 8744), "source": "CouatlAddons.ini" if ini_port else "default", "couatl_ini": str(_couatl_addons_ini_path()), "ini_reason": ini_reason}


def _normalise_remote_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urlparse(raw)
    if not parsed.hostname:
        return ""
    scheme = "https" if parsed.scheme == "https" else "http"
    netloc = parsed.netloc
    return urlunparse((scheme, netloc, parsed.path or "/", "", "", ""))


def _official_candidates() -> list[str]:
    settings = load_settings().get("integrations", {})
    port = _remote_port()
    configured = _normalise_remote_url(str(settings.get("gsx_remote_url") or ""))
    candidates = []
    if configured:
        candidates.append(configured)
    candidates.extend([f"http://127.0.0.1:{port}/", f"http://localhost:{port}/"])
    result = []
    seen = set()
    for url in candidates:
        key = url.rstrip("/").lower()
        if key not in seen:
            seen.add(key); result.append(url.rstrip("/") + "/")
    return result


def _ws_url(http_url: str) -> str:
    parsed = urlparse(http_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, parsed.path or "/", "", "", ""))


def _client_url_for(url: str) -> str:
    """URL the browser/iPad should use. JS may replace host with location.hostname."""
    parsed = urlparse(url)
    port = parsed.port or _remote_port()
    return f"http://127.0.0.1:{port}/"


def _official_http_reachable(url: str, timeout: float = 0.28) -> bool:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "OPS ROOM GSX probe"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= int(response.status) < 500
    except Exception:
        return False



def _apply_official_patch(state: dict[str, Any], path: str, value: Any) -> None:
    """Apply a GSX Remote API JSON-pointer style patch to the cached snapshot.

    The official API can send either /handlerData as a whole object or nested
    paths such as /handlerData/aircraft/refueling. Keeping this nested shape is
    required so handler.set echo verification works correctly.
    """
    parts = [part for part in str(path or "").strip("/").split("/") if part]
    if not parts:
        return
    if len(parts) == 1:
        if value is None:
            state.pop(parts[0], None)
        else:
            state[parts[0]] = value
        return
    cursor: Any = state
    for position, next_part in enumerate(parts[:-1]):
        part = next_part.replace("~1", "/").replace("~0", "~")
        if isinstance(cursor, dict):
            child = cursor.get(part)
            if not isinstance(child, (dict, list)):
                following = parts[position + 1] if position + 1 < len(parts) else ""
                child = [] if following.isdigit() else {}
                cursor[part] = child
            cursor = child
        elif isinstance(cursor, list) and part.isdigit():
            index = int(part)
            if index < 0 or index >= len(cursor):
                return
            cursor = cursor[index]
        else:
            return
    final = parts[-1].replace("~1", "/").replace("~0", "~")
    if isinstance(cursor, dict):
        if value is None:
            cursor.pop(final, None)
        else:
            cursor[final] = value
    elif isinstance(cursor, list) and final.isdigit():
        index = int(final)
        if 0 <= index < len(cursor):
            if value is None:
                cursor.pop(index)
            else:
                cursor[index] = value


def _official_handler_data_from_state(state: dict[str, Any]) -> dict[str, Any]:
    handler_data = state.get("handlerData")
    return handler_data if isinstance(handler_data, dict) else {}

def _official_ws_exchange(command: dict[str, Any] | None = None, timeout: float = 0.75) -> dict[str, Any]:
    global _OFFICIAL_STATE, _OFFICIAL_URL
    last_error = ""
    for url in _official_candidates():
        # Fast TCP check avoids a long WebSocket attempt when the server is down.
        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or _remote_port()
        try:
            with socket.create_connection((host, port), timeout=0.20):
                pass
        except OSError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue
        try:
            from websockets.sync.client import connect  # type: ignore
            ws_uri = _ws_url(url)
            state = dict(_OFFICIAL_STATE) if _OFFICIAL_URL == url else {}
            hello: dict[str, Any] = {}
            result_msg: dict[str, Any] = {}
            with connect(ws_uri, open_timeout=0.45, close_timeout=0.15, ping_interval=None, proxy=None) as ws:
                ws.send(json.dumps({"type": "subscribe", "channels": ["state", "prompts", "toasts"]}))
                if command:
                    ws.send(json.dumps(command))
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    try:
                        raw = ws.recv(timeout=max(0.02, min(0.18, deadline - time.monotonic())))
                    except TimeoutError:
                        continue
                    except Exception:
                        break
                    try:
                        msg = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode("utf-8", "ignore"))
                    except Exception:
                        continue
                    msg_type = msg.get("type")
                    if msg_type == "hello":
                        hello = msg
                    elif msg_type == "snapshot":
                        state = {k: v for k, v in msg.items() if k not in {"type", "v", "ts", "id"}}
                    elif msg_type == "patch":
                        _apply_official_patch(state, str(msg.get("path") or ""), msg.get("value"))
                    elif msg_type == "event" and msg.get("topic") == "engine":
                        hello["gsxRunning"] = bool(msg.get("gsxRunning"))
                    elif msg_type == "result":
                        result_msg = msg
                _OFFICIAL_STATE = state
                _OFFICIAL_URL = url
                return {"ok": True, "url": url, "ws_url": ws_uri, "hello": hello, "state": state, "result": result_msg}
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue
    return {"ok": False, "reason": last_error or "GSX official remote is not reachable"}


REMOTE_SERVICE_IDS = {
    "boarding": "Boarding",
    "deboarding": "Deboarding",
    "catering": "Catering",
    "refuel": "Refueling",
    "water": "Water",
    "lavatory": "Lavatory",
    "cleaning": "Cleaning",
    "deice": "DeIce",
    "pushback": "Departure",
    "departure": "Departure",
    "gpu": "GPU",
    "jetway": "OperateJetways",
    "stairs": "OperateStairs",
}
REMOTE_ID_TO_KEY = {v.lower(): k for k, v in REMOTE_SERVICE_IDS.items()}
REMOTE_ID_TO_KEY.update({
    "refueling": "refuel",
    "refuelling": "refuel",
    "operatejetways": "jetway",
    "operatestairs": "stairs",
    "departure": "departure",
    "deice": "deice",
})
REMOTE_STATE_TO_RAW = {
    "available": 1,
    "requested": 4,
    "performing": 5,
    "completing": 7,
    "completed": 6,
    "bypassed": 3,
    "unavailable": 2,
    "unknown": 0,
}


def _remote_service_key(service_id: Any, display_name: Any = "") -> str:
    raw = _normalized(str(service_id or display_name or "")).replace(" ", "")
    if raw in REMOTE_ID_TO_KEY:
        return REMOTE_ID_TO_KEY[raw]
    text = _normalized(str(display_name or service_id or ""))
    for key, aliases in ALIASES.items():
        if _matching_index([text], aliases) is not None:
            return key
    if "fuel" in text:
        return "refuel"
    if "cater" in text:
        return "catering"
    if "board" in text and "deboard" not in text:
        return "boarding"
    if "deboard" in text or "unload" in text:
        return "deboarding"
    return raw or str(service_id or display_name or "service").lower()


def _strip_progress_markup(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ").replace("•", " · ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _collect_progress_text(value: Any, out: list[str], depth: int = 0) -> None:
    if depth > 3 or value is None:
        return
    if isinstance(value, dict):
        for key in ("progressText", "progress_text", "statusText", "stateText", "message", "text", "label", "displayName", "value", "current", "total", "done"):
            if key in value:
                _collect_progress_text(value.get(key), out, depth + 1)
        for key in ("progress", "detail", "details", "pax", "passengers", "bags", "baggage", "cargo"):
            if key in value:
                _collect_progress_text(value.get(key), out, depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for item in value[:24]:
            _collect_progress_text(item, out, depth + 1)
        return
    text = _strip_progress_markup(value)
    if text:
        out.append(text)


def _remote_progress_text(svc: dict[str, Any]) -> str:
    values: list[str] = []
    _collect_progress_text(svc, values)
    joined = " · ".join(dict.fromkeys(values))
    return _strip_progress_markup(joined)


def _remote_state_entry(key: str, svc: dict[str, Any]) -> dict[str, Any]:
    state = str(svc.get("state") or "unknown").strip().lower()
    raw_value = svc.get("stateRaw", svc.get("rawState", svc.get("raw")))
    try:
        raw = int(raw_value) if raw_value is not None else REMOTE_STATE_TO_RAW.get(state, 0)
    except (TypeError, ValueError):
        raw = REMOTE_STATE_TO_RAW.get(state, 0)
    label = str(svc.get("displayName") or SERVICE_LABELS.get(key, key.upper()))
    progress = svc.get("progress") if isinstance(svc.get("progress"), dict) else {}
    waiting = bool(svc.get("waiting"))
    progress_text = _remote_progress_text(svc)
    status_text = str(svc.get("statusText") or svc.get("stateText") or progress_text or "").strip()
    waiting_reason = str(svc.get("waitingReason") or svc.get("reason") or "").strip()
    if waiting and raw in {1, 4, 5}:
        raw = 7 if state in {"requested", "performing", "completing"} else raw
    entry = _state_entry(key, raw)
    entry.update({
        "label": label,
        "remote_id": svc.get("id"),
        "remote_state": state,
        "can_trigger": bool(svc.get("canTrigger")),
        "waiting": waiting,
        "status_text": status_text,
        "progress_text": progress_text,
        "waiting_reason": waiting_reason,
        "progress": progress,
        "source": "official-remote-api-v2",
    })
    return entry




def _remote_progress_numbers(svc: dict[str, Any]) -> tuple[float, float, str]:
    pr = svc.get("progress") if isinstance(svc.get("progress"), dict) else {}
    unit = str(pr.get("unit") or "").lower()
    cur = total = 0.0
    for cur_key, total_key in (("current", "total"), ("done", "total"), ("value", "max")):
        try:
            if pr.get(total_key) is not None:
                cur = float(pr.get(cur_key) or 0)
                total = float(pr.get(total_key) or 0)
                break
        except Exception:
            cur = total = 0.0
    detail = svc.get("detail") if isinstance(svc.get("detail"), dict) else {}
    for obj in (detail, svc):
        for key in ("pax", "passengers", "bags", "baggage", "cargo"):
            item = obj.get(key) if isinstance(obj, dict) else None
            if isinstance(item, dict):
                try:
                    dcur = float(item.get("done", item.get("current", item.get("loaded", 0))) or 0)
                    dtotal = float(item.get("total", item.get("target", 0)) or 0)
                    if dtotal > 0:
                        return dcur, dtotal, key
                except Exception:
                    pass
    return cur, total, unit


def _official_services_from_state(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    services_obj = state.get("services")
    if isinstance(services_obj, dict):
        iterable = list(services_obj.values())
    elif isinstance(services_obj, list):
        iterable = services_obj
    else:
        return {}, {}
    services: dict[str, Any] = {}
    progress: dict[str, Any] = {}
    for item in iterable:
        if not isinstance(item, dict):
            continue
        key = _remote_service_key(item.get("id"), item.get("displayName"))
        services[key] = _remote_state_entry(key, item)
        progress_text = _remote_progress_text(item)
        cur, total, unit = _remote_progress_numbers(item)
        if key == "boarding":
            pax_match = re.search(r"(?:pax|passengers?)\s*(?::|=)?\s*(\d+)\s*/\s*(\d+)", progress_text, re.I)
            bags_match = re.search(r"(?:bags?|baggage|cargo)\s*(?::|=)?\s*(\d{1,3})\s*%", progress_text, re.I)
            if pax_match:
                progress["passengers_boarding_total"] = int(pax_match.group(1))
                progress["passengers_target"] = int(pax_match.group(2))
            elif total > 0 and ("pax" in unit or "pass" in unit or unit == ""):
                progress["passengers_boarding_total"] = int(cur)
                progress["passengers_target"] = int(total)
            elif total > 0:
                progress["boarding_cargo_percent"] = int(max(0, min(100, round(100.0 * cur / total))))
            if bags_match:
                progress["boarding_cargo_percent"] = int(max(0, min(100, int(bags_match.group(1)))))
        elif key == "deboarding":
            pax_match = re.search(r"(?:pax|passengers?)\s*(?::|=)?\s*(\d+)\s*/\s*(\d+)", progress_text, re.I)
            bags_match = re.search(r"(?:bags?|baggage|cargo)\s*(?::|=)?\s*(\d{1,3})\s*%", progress_text, re.I)
            if pax_match:
                progress["passengers_deboarding_total"] = int(pax_match.group(1))
                progress["passengers_deboarding_target"] = int(pax_match.group(2))
                progress.setdefault("passengers_target", int(pax_match.group(2)))
            elif total > 0 and ("pax" in unit or "pass" in unit or unit == ""):
                progress["passengers_deboarding_total"] = int(cur)
                progress["passengers_deboarding_target"] = int(total)
                progress.setdefault("passengers_target", int(total))
            elif total > 0:
                progress["deboarding_cargo_percent"] = int(max(0, min(100, round(100.0 * cur / total))))
            if bags_match:
                progress["deboarding_cargo_percent"] = int(max(0, min(100, int(bags_match.group(1)))))
    # An omitted GSX total means "not published", not zero.  Keeping these as
    # None lets the UI show Active/Complete or -- / -- instead of a misleading
    # 0 / 0 while Fenix/GSX performs an otherwise valid arrival unload.
    progress.setdefault("passengers_target", None)
    progress.setdefault("passengers_boarding_total", None)
    progress.setdefault("passengers_deboarding_total", None)
    progress.setdefault("boarding_cargo_percent", None)
    progress.setdefault("deboarding_cargo_percent", None)
    return services, progress


def _menu_entry_label(entry: Any) -> str:
    if isinstance(entry, dict):
        for key in ("label", "text", "title", "name", "displayName"):
            value = entry.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return str(entry).strip()
    return str(entry or "").strip()



def _official_menu_from_state(state: dict[str, Any]) -> dict[str, Any]:
    menu = state.get("menu") if isinstance(state.get("menu"), dict) else {}
    raw_entries = list(menu.get("entries") or [])
    raw_options = [_menu_entry_label(x) for x in raw_entries]
    options = [x for x in raw_options if x.strip()]
    option_indices = [i for i, label in enumerate(raw_options) if label.strip()]
    raw_disabled = list(menu.get("disabled") or [])
    raw_icon_wide = list(menu.get("iconWide") or [])
    raw_icons = list(menu.get("icons") or [])
    raw_icons_svg = list(menu.get("iconsSvg") or [])
    title = str(menu.get("title") or menu.get("header") or "GSX MENU")
    shown = bool(state.get("menuShown"))
    common = {
        "title": title,
        "options": options if shown else [],
        "entries": raw_entries,
        "raw_options": raw_options,
        "option_indices": option_indices,
        "raw_disabled": raw_disabled,
        "raw_icon_wide": raw_icon_wide,
        "raw_icons": raw_icons,
        "raw_icons_svg": raw_icons_svg,
        "menu_shown": shown,
        "updated": _utc(),
        "source": "official-remote-api-v2",
    }
    if shown and options:
        return {"available": True, **common}
    return {
        "available": False,
        **common,
        "reason": "GSX official menu is closed",
    }

def _official_status(force: bool = False) -> dict[str, Any]:
    global _OFFICIAL_CACHE, _OFFICIAL_CACHE_TIME
    now = time.monotonic()
    if not force and _OFFICIAL_CACHE is not None and now - _OFFICIAL_CACHE_TIME < 0.8:
        return dict(_OFFICIAL_CACHE)
    port = _remote_port()
    exchange = _official_ws_exchange(timeout=0.45)
    if exchange.get("ok"):
        state = exchange.get("state") or {}
        hello = exchange.get("hello") or {}
        url = str(exchange.get("url") or f"http://127.0.0.1:{port}/")
        parsed = urlparse(url)
        menu = _official_menu_from_state(state)
        services, progress = _official_services_from_state(state)
        handler_data = _official_handler_data_from_state(state)
        startup = state.get("startup") if isinstance(state.get("startup"), dict) else {}
        result = {
            "reachable": True,
            "ws_connected": True,
            "protocol": "official-remote-api-v2",
            "provider": "remote-v2",
            "port": parsed.port or port,
            "port_diagnostics": _remote_port_diagnostics(),
            "url_backend": url,
            "client_url": _client_url_for(url),
            "gsx_running": bool(hello.get("gsxRunning", True)),
            "menu_shown": bool(state.get("menuShown")),
            "menu": menu,
            "services": services,
            "progress": progress,
            "handlerData": handler_data,
            "aircraft_handler": handler_data.get("aircraft") if isinstance(handler_data.get("aircraft"), dict) else {},
            "gate_handler": handler_data.get("gate") if isinstance(handler_data.get("gate"), dict) else {},
            "status_html_available": bool(state.get("statusHtml")),
            "services_available": bool(services),
            "startup": dict(startup),
            "startup_active": bool(startup.get("active")),
            "startup_sid": str(startup.get("sid") or ""),
            "sampled_at": _utc(),
        }
    else:
        # Keep an HTTP/TCP probe so the UI can still embed the official remote even if a snapshot was not collected.
        reachable_url = ""
        for candidate in _official_candidates():
            if _official_http_reachable(candidate):
                reachable_url = candidate; break
        parsed = urlparse(reachable_url or f"http://127.0.0.1:{port}/")
        result = {
            "reachable": bool(reachable_url),
            "ws_connected": False,
            "protocol": "official-remote-api-v2",
            "port": parsed.port or port,
            "port_diagnostics": _remote_port_diagnostics(),
            "url_backend": reachable_url or f"http://127.0.0.1:{port}/",
            "client_url": _client_url_for(reachable_url or f"http://127.0.0.1:{port}/"),
            "gsx_running": False,
            "menu_shown": False,
            "startup": {},
            "startup_active": False,
            "startup_sid": "",
            "menu": {"available": False, "title": "GSX MENU", "options": [], "reason": exchange.get("reason") or "GSX official remote is offline"},
            "reason": exchange.get("reason"),
            "sampled_at": _utc(),
        }
    _OFFICIAL_CACHE, _OFFICIAL_CACHE_TIME = result, now
    return dict(result)


def _official_command(verb: str, args: dict[str, Any] | None = None, timeout: float = 0.95) -> dict[str, Any]:
    command = {"type": "command", "verb": verb}
    if args:
        command["args"] = args
    result = _official_ws_exchange(command, timeout=timeout)
    if not result.get("ok"):
        return {"ok": False, "reason": result.get("reason") or "GSX official remote command failed"}
    result_msg = result.get("result") or {}
    if isinstance(result_msg, dict) and result_msg:
        if result_msg.get("ok") is False:
            code = str(result_msg.get("code") or result_msg.get("error") or "remote_error")
            detail = str(result_msg.get("message") or result_msg.get("reason") or code)
            return {"ok": False, "verb": verb, "reason": detail, "code": code, "result": result_msg}
    state = result.get("state") or {}
    status = _official_status(force=True)
    return {"ok": True, "verb": verb, "menu": _official_menu_from_state(state), "official_remote": status, "result": result_msg}


def _control_server_status() -> dict[str, Any]:
    official = _official_status(force=False)
    if official.get("reachable"):
        return {"reachable": True, "protocol": "official-remote-api-v2", "port": official.get("port", 8744), "official": official}
    try:
        with socket.create_connection(("127.0.0.1", _remote_port()), timeout=0.18):
            return {"reachable": True, "protocol": "websocket", "port": _remote_port(), "official": official}
    except OSError:
        return {"reachable": False, "protocol": "websocket", "port": _remote_port(), "official": official}



def _maybe_beacon_pushback() -> None:
    global _LAST_BEACON_STATE, _LAST_BEACON_PUSHBACK
    settings = load_settings().get("integrations", {})
    if not settings.get("gsx_prepare_on_beacon", False):
        return
    try:
        pos = read_telemetry(force=False)
        systems = pos.get("systems") if isinstance(pos.get("systems"), dict) else {}
        beacon = systems.get("beacon_light")
        if beacon is None:
            return
        now = time.monotonic()
        rising = beacon is True and _LAST_BEACON_STATE is not True
        _LAST_BEACON_STATE = bool(beacon)
        if not rising or now - _LAST_BEACON_PUSHBACK < 90:
            return
        if not pos.get("ok") or not bool(pos.get("on_ground", True)):
            return
        if float(pos.get("ground_speed_kts") or 0) > 3:
            return
        _LAST_BEACON_PUSHBACK = now
        threading.Thread(target=lambda: call_service("pushback", automate=True), name="OpsRoom-GSX-BeaconPushback", daemon=True).start()
        _record("AUTO", "Beacon on detected, preparing pushback")
    except Exception as exc:
        _record("AUTO", f"Beacon pushback skipped: {type(exc).__name__}")

def status(force: bool = False) -> dict[str, Any]:
    global _CACHE, _CACHE_TIME
    with _LOCK:
        if os.getenv("OPSROOM_GSX_MOCK") == "1":
            return _mock_status()
        now = time.monotonic()
        if not force and _CACHE is not None and now - _CACHE_TIME < 0.8:
            return dict(_CACHE)
        root = _configured_root()
        installed = bool(root and (root / "MSFS" / "fsdreamteam-gsx-pro").exists())
        official = _official_status(force=force)
        official_menu = (official.get("menu") or {}) if isinstance(official.get("menu"), dict) else {}
        current_menu = official_menu if official_menu.get("available") else read_menu()
        official_connected = bool(official.get("reachable") and (official.get("gsx_running") or official.get("ws_connected")))
        official_services = (official.get("services") or {}) if isinstance(official.get("services"), dict) else {}
        if official_connected and official_services:
            result = {
                "ok": True,
                "installed": installed or bool(official.get("reachable")),
                "connected": True,
                "couatl_started": 1 if official.get("gsx_running") else 0,
                "services": official_services,
                "progress": official.get("progress") or {},
                "menu": current_menu,
                "official_remote": official,
                "control_server": _control_server_status(),
                "events": list(reversed(_LOG[-30:])),
                "arrival_gate_flow": _arrival_gate_flow_status(),
                "sampled_at": _utc(),
                "source": "official-remote-api-v2",
            }
            _CACHE, _CACHE_TIME = result, now
            return dict(result)
        diagnostics = simconnect_diagnostics()
        if not diagnostics.get("session_connected") and not diagnostics.get("dll_found"):
            result = {
                "ok": bool(official_connected),
                "installed": installed or bool(official.get("reachable")),
                "connected": official_connected,
                "reason": "SimConnect is not available" if not official_connected else "Using official GSX Remote API; SimConnect service LVars are unavailable",
                "services": {},
                "progress": {},
                "menu": current_menu,
                "official_remote": official,
                "control_server": _control_server_status(),
                "events": list(reversed(_LOG[-30:])),
                "sampled_at": _utc(),
            }
            _CACHE, _CACHE_TIME = result, now
            return dict(result)
        values: dict[str, Any] = {}
        try:
            with SIM_LOCK:
                sm, _aq = _ensure_session(diagnostics)
                for key, lvar in LVAR.items():
                    values[key] = _read_value(sm, lvar)
        except Exception as exc:
            result = {
                "ok": bool(official_connected),
                "installed": installed or bool(official.get("reachable")),
                "connected": official_connected,
                "reason": f"{type(exc).__name__}: {exc}" if not official_connected else f"Using official GSX Remote API; SimConnect LVar read failed: {type(exc).__name__}: {exc}",
                "services": {},
                "progress": {},
                "menu": current_menu,
                "official_remote": official,
                "control_server": _control_server_status(),
                "events": list(reversed(_LOG[-30:])),
                "sampled_at": _utc(),
            }
            _CACHE, _CACHE_TIME = result, now
            return dict(result)

        # LVar reads can briefly return None while SimConnect or Couatl is busy.
        # Hold the last confirmed value for a few seconds so the browser does not
        # flash between ONLINE, STANDBY and NO DATA on every sample.
        global _LAST_CONNECTED_TIME
        stable_now = time.monotonic()
        for key, value in list(values.items()):
            if value is not None:
                _STABLE_VALUES[key] = value
                _STABLE_UPDATED[key] = stable_now
            elif key in _STABLE_VALUES and stable_now - _STABLE_UPDATED.get(key, 0.0) <= 8.0:
                values[key] = _STABLE_VALUES[key]

        services = {key: _state_entry(key, values.get(key)) for key in SERVICE_KEYS}
        services["jetway"] = _binary_entry("jetway", values.get("jetway"), "CONNECTED", "DISCONNECTED")
        services["stairs"] = _binary_entry("stairs", values.get("stairs"), "POSITIONED", "STOWED")
        services["pushback"] = _binary_entry("pushback", values.get("pushback"), "ACTIVE", "STANDBY")
        couatl = int(round(values.get("couatl") or 0))
        if couatl > 0:
            _LAST_CONNECTED_TIME = stable_now
        connected = couatl > 0 or (bool(_LAST_CONNECTED_TIME) and stable_now - _LAST_CONNECTED_TIME <= 8.0) or official_connected
        if connected:
            _maybe_beacon_pushback()
        result = {
            "ok": True,
            "installed": installed or bool(official.get("reachable")),
            "connected": connected,
            "couatl_started": couatl,
            "services": services,
            "progress": {
                "passengers_target": int(values.get("pax_target") or 0),
                "passengers_boarding_total": int(values.get("pax_board") or 0),
                "passengers_deboarding_total": int(values.get("pax_deboard") or 0),
                "boarding_cargo_percent": max(0, min(100, int(values.get("cargo_board") or 0))),
                "deboarding_cargo_percent": max(0, min(100, int(values.get("cargo_deboard") or 0))),
            },
            "menu": current_menu,
            "official_remote": official,
            "control_server": _control_server_status(),
            "events": list(reversed(_LOG[-30:])),
            "arrival_gate_flow": _arrival_gate_flow_status(),
            "sampled_at": _utc(),
            "source": "simconnect-lvars",
        }
        _CACHE, _CACHE_TIME = result, now
        return dict(result)


def _invalidate() -> None:
    global _CACHE, _CACHE_TIME
    _CACHE = None
    _CACHE_TIME = 0.0


def _invalidate_official() -> None:
    global _OFFICIAL_CACHE, _OFFICIAL_CACHE_TIME, _OFFICIAL_STATE, _OFFICIAL_URL
    _OFFICIAL_CACHE = None
    _OFFICIAL_CACHE_TIME = 0.0
    _OFFICIAL_STATE = {}
    _OFFICIAL_URL = ""


def _legacy_gsx_passenger_target(authoritative_target: Any, *, force: bool = False) -> dict[str, Any]:
    """Reconcile the documented writable GSX passenger target on legacy GSX.

    New GSX builds expose the official Remote API and are intentionally left
    untouched. Older builds publish boarding progress through SimConnect LVars;
    for those builds GSX documents FSDT_GSX_NUMPASSENGERS as writable by an
    aircraft/add-on to replace GSX's estimated passenger number.
    """
    try:
        target = int(round(float(authoritative_target)))
    except (TypeError, ValueError):
        return {"ok": False, "skipped": True, "reason": "No authoritative passenger target"}
    if target <= 0:
        return {"ok": False, "skipped": True, "reason": "Passenger target is not positive"}

    official = _official_status(force=False)
    if official.get("reachable") and official.get("ws_connected") and official.get("protocol") == "official-remote-api-v2":
        # A newly connected Remote API session can briefly have no service snapshot.
        # Treat the connection itself as authoritative so the proven modern path is
        # never touched by the legacy LVar compatibility shim.
        return {"ok": True, "skipped": True, "source": "official-remote-api-v2", "target": target}

    now = time.monotonic()
    last_write = float(_AUTOMATION_REQUESTED_MONO.get("legacy_gsx_pax_target_write") or 0.0)
    if not force and now - last_write < 4.0:
        return {"ok": True, "deferred": True, "source": "simconnect-lvars", "target": target}

    diagnostics = simconnect_diagnostics()
    try:
        with SIM_LOCK:
            sm, _aq = _ensure_session(diagnostics)
            current = _read_value(sm, LVAR["pax_target"])
            if current is not None and int(round(current)) == target:
                _set_latch("legacy_gsx_pax_target", target)
                return {"ok": True, "already_set": True, "source": "simconnect-lvars", "target": target, "readback": int(round(current))}
            written = _write_value(sm, LVAR["pax_target"], target)
            readback = _read_value(sm, LVAR["pax_target"]) if written else None
    except Exception as exc:
        return {"ok": False, "source": "simconnect-lvars", "target": target, "reason": f"{type(exc).__name__}: {exc}"}

    _AUTOMATION_REQUESTED_MONO["legacy_gsx_pax_target_write"] = now
    if not written:
        return {"ok": False, "source": "simconnect-lvars", "target": target, "reason": "GSX passenger target LVar write failed"}
    _set_latch("legacy_gsx_pax_target", target)
    _invalidate()
    verified = readback is not None and int(round(readback)) == target
    if force or not _get_latch("legacy_gsx_pax_target_logged"):
        _set_latch("legacy_gsx_pax_target_logged", True)
        _automation_record("LEGACY GSX", f"Passenger target reconciled to SimBrief/Fenix value {target}")
    return {
        "ok": True,
        "source": "simconnect-lvars",
        "target": target,
        "readback": None if readback is None else int(round(readback)),
        "verified": verified,
    }


def _wait_for_menu(previous_updated: str | None = None, timeout: float = 5.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    latest = read_menu()
    while time.monotonic() < deadline:
        latest = read_menu()
        if latest.get("available") and (not previous_updated or latest.get("updated") != previous_updated):
            return latest
        time.sleep(0.15)
    return latest


def open_menu() -> dict[str, Any]:
    official = _official_status(force=True)
    official_menu = (official.get("menu") or {}) if isinstance(official.get("menu"), dict) else {}
    if official_menu.get("available") and official_menu.get("options"):
        return {"ok": True, "menu": official_menu, "existing": True, "official_remote": official}
    if official.get("reachable"):
        command = _official_command("menu.toggle", timeout=1.15)
        menu = command.get("menu") or {}
        if menu.get("available") and menu.get("options"):
            _record("MENU", f"Opened {menu.get('title') or 'GSX menu'} through official Remote API")
            _invalidate()
            return {"ok": True, "menu": menu, "official_remote": command.get("official_remote") or official}
    existing = read_menu()
    if existing.get("available") and existing.get("options"):
        return {"ok": True, "menu": existing, "existing": True}
    if os.getenv("OPSROOM_GSX_MOCK") == "1":
        _record("MENU", "GSX menu opened")
        return {"ok": True, "menu": read_menu()}
    diagnostics = simconnect_diagnostics()
    last_menu = read_menu()
    for attempt in range(2):
        previous = last_menu.get("updated")
        with SIM_LOCK:
            sm, _aq = _ensure_session(diagnostics)
            # GSX external control flow: disable the toolbar/menu event first,
            # then request the external menu through the GSX LVar.
            _send_sim_event(sm, "EXTERNAL_SYSTEM_TOGGLE", 4)
            time.sleep(0.25)
            if not _write_value(sm, LVAR["menu_open"], 1):
                raise RuntimeError("GSX rejected the menu-open command")
        last_menu = _wait_for_menu(previous, 8.0)
        if last_menu.get("available") and last_menu.get("options"):
            break
        time.sleep(0.5)
    if last_menu.get("available") and last_menu.get("options"):
        _record("MENU", f"Opened {last_menu.get('title') or 'GSX menu'}")
    else:
        _record("MENU", "GSX menu did not publish options")
    _invalidate()
    return {"ok": bool(last_menu.get("available")), "menu": last_menu}


def select_menu(index: int) -> dict[str, Any]:
    """Select a GSX menu item safely.

    GSX menus can refresh between read and pick. Never raise a hard ValueError
    for an out-of-range stale index during automation; return a safe result so
    the flow can re-read the live menu or continue monitoring.
    """
    try:
        index = int(index)
    except (TypeError, ValueError):
        return {"ok": False, "requires_selection": False, "reason": "GSX menu selection index is invalid", "menu": _active_menu(prefer_official=True)}

    official = _official_status(force=True)
    official_menu = (official.get("menu") or {}) if isinstance(official.get("menu"), dict) else {}
    if official_menu.get("available") and official_menu.get("options"):
        options = list(official_menu.get("options") or [])
        if index < 0 or index >= len(options):
            _record("MENU", "GSX menu changed before selection; stale index ignored")
            return {"ok": False, "menu_changed": True, "reason": "GSX menu changed before selection; retrying/monitoring", "menu": official_menu, "official_remote": official}
        selected = str(options[index])
        command = _official_command("menu.pick", {"index": index}, timeout=1.10)
        if command.get("ok"):
            _record("SELECT", selected)
            _invalidate()
            return {"ok": True, "selected": selected, "menu": command.get("menu") or official_menu, "official_remote": command.get("official_remote") or official}
        _record("MENU", str(command.get("reason") or "GSX official menu pick failed"))
        return {"ok": False, "selected": selected, "menu": official_menu, "reason": str(command.get("reason") or "GSX official menu pick failed"), "official_remote": official}

    menu = read_menu()
    options = list(menu.get("options") or [])
    if index < 0 or index >= len(options):
        _record("MENU", "GSX menu changed before selection; stale index ignored")
        return {"ok": False, "menu_changed": True, "reason": "GSX menu changed before selection; retrying/monitoring", "menu": menu}
    selected = str(options[index])
    if os.getenv("OPSROOM_GSX_MOCK") == "1":
        _record("SELECT", selected)
        return {"ok": True, "selected": selected, "menu": read_menu()}
    previous = menu.get("updated")
    diagnostics = simconnect_diagnostics()
    with SIM_LOCK:
        sm, _aq = _ensure_session(diagnostics)
        _send_sim_event(sm, "EXTERNAL_SYSTEM_TOGGLE", 4)
        if not _write_value(sm, LVAR["menu_choice"], index):
            return {"ok": False, "selected": selected, "menu": menu, "reason": "GSX rejected the menu choice"}
    time.sleep(0.25)
    next_menu = _wait_for_menu(previous, 5.0)
    _record("SELECT", selected)
    _invalidate()
    return {"ok": True, "selected": selected, "menu": next_menu}




def select_menu_by_label(expected: str, aliases: tuple[str, ...] = ()) -> dict[str, Any]:
    """Re-read the live GSX menu and pick the intended visible label.

    This prevents a stale numeric index from selecting the wrong item when GSX
    refreshes or reorders the menu between discovery and selection.
    """
    menu = _active_menu(prefer_official=True)
    options = list(menu.get("options") or [])
    if not options:
        return {"ok": False, "menu_changed": True, "reason": "GSX menu is no longer available", "menu": menu}
    wanted = _normalized(expected)
    choices = tuple(x for x in (expected, *aliases) if str(x or "").strip())
    index = None
    if choices:
        index = _matching_index(options, tuple(str(x) for x in choices))
    if index is None and wanted:
        normalized = [_normalized(str(x)) for x in options]
        for i, item in enumerate(normalized):
            if item == wanted or wanted in item or item in wanted:
                index = i
                break
    if index is None:
        _record("MENU", f"GSX menu changed before selection; wanted '{expected}'")
        return {"ok": False, "menu_changed": True, "reason": f"GSX menu changed before selecting {expected}; continuing monitor", "menu": menu}
    return select_menu(index)

def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _matching_index(options: list[str], aliases: tuple[str, ...]) -> int | None:
    normalized = [_normalized(x) for x in options]
    for alias in aliases:
        needle = _normalized(alias)
        for index, option in enumerate(normalized):
            if needle == option or needle in option:
                return index
    return None


_DEPARTURE_FORBIDDEN_SERVICES = {"deboarding", "cleaning", "lavatory"}
_DEPARTURE_FORBIDDEN_WORDS = (
    "deboarding", "deboard", "unloading", "unload",
    "cleaning", "clean", "lavatory", "toilet", "arrival service",
)


def _automation_mode() -> str:
    with _AUTOMATION_LOCK:
        return str(_AUTOMATION.get("mode") or "").upper()


def _departure_mode_active() -> bool:
    return _automation_mode() == "DEPARTURE"


def _option_forbidden_in_departure(label: str) -> bool:
    norm = _normalized(label)
    if not norm:
        return False
    if any(word in norm for word in _DEPARTURE_FORBIDDEN_WORDS):
        return True
    for service in _DEPARTURE_FORBIDDEN_SERVICES:
        if _matching_index([label], ALIASES.get(service, ())) is not None:
            return True
    return False


def _departure_guard_result(service: str, reason: str | None = None) -> dict[str, Any]:
    label = SERVICE_LABELS.get(service, service.upper())
    message = reason or f"Departure mode blocked arrival-only GSX service {label}"
    _automation_record("GUARD", message)
    return {"ok": True, "blocked": True, "departure_guard": True, "service": service, "reason": message}


def _looks_like_pushback_direction(title: str, options: list[str]) -> bool:
    title_n = _normalized(title)
    normalized = [_normalized(option) for option in options]
    direction_words = ("left", "right", "straight", "nose", "tail", "facing", "east", "west", "north", "south", "clockwise", "counterclockwise")
    if "direction" in title_n or "facing" in title_n:
        return True
    hits = sum(1 for option in normalized if any(word in option for word in direction_words))
    return hits >= 2



def _operator_prompt(title: str) -> bool:
    title_n = _normalized(title)
    return any(word in title_n for word in ("operator", "handling", "handler", "ground handler", "service provider", "choose company", "select company"))


def _airline_aliases_from_database(code: str) -> set[str]:
    aliases: set[str] = set()
    code_n = str(code or "").strip().upper()
    if not code_n:
        return aliases
    try:
        import csv
        csv_path = Path(__file__).resolve().parent / "data" / "airlines.csv"
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if str(row.get("ICAO") or "").strip().upper() == code_n or str(row.get("IATA") or "").strip().upper() == code_n:
                    for key in ("Name", "ICAO", "IATA", "Callsign"):
                        val = str(row.get(key) or "").strip()
                        if val and val not in {"-", "N/A"}:
                            aliases.add(val)
                    break
    except Exception:
        pass
    return aliases


_OPERATOR_SUBSIDIARY_SUFFIXES = {
    "cargo", "cityline", "technik", "systems", "regional", "express",
    "cargo airlines", "group", "training", "executive", "charter",
}


def _airline_canonical_name(code: str) -> str:
    """Return the authoritative brand Name (CSV) for an ICAO/IATA code.

    Matches ICAO first, then IATA — the same order as
    `_airline_aliases_from_database`. Filters out placeholders ("-", "N/A",
    "Private flight"). Returns an empty string if no canonical brand exists.
    """
    code_n = str(code or "").strip().upper()
    if not code_n:
        return ""
    try:
        import csv
        csv_path = Path(__file__).resolve().parent / "data" / "airlines.csv"
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if str(row.get("ICAO") or "").strip().upper() == code_n or str(row.get("IATA") or "").strip().upper() == code_n:
                    name = str(row.get("Name") or "").strip()
                    if name and name not in {"-", "N/A", "Private flight"}:
                        return name
                    break
    except Exception:
        pass
    return ""


def _operator_store_path() -> Path:
    return app_data_dir() / _OPERATOR_STORE_FILE


def _is_real_operator_brand(name: str, code: str) -> bool:
    """A usable brand is a real airline name, not empty/generic/the raw code."""
    text = str(name or "").strip()
    norm = _normalized(text)
    if not norm:
        return False
    if norm in {"ops room", "opsroom"}:
        return False
    if "general aviation" in norm or "unknown" in norm:
        return False
    code_n = _normalized(str(code or ""))
    if code_n and norm == code_n:
        return False
    return True


def warm_operator_from_simbrief_plan(plan: dict) -> dict:
    """Resolve the operating-airline brand EARLY and store it durably.

    Called at SimBrief-fetch/startup time. Resolves the brand primarily from the
    authoritative plan["airline_branding"]["name"] (e.g. ICAO DLH -> "Lufthansa"),
    then from airlines.csv via the ICAO/IATA code. Stores callsign -> brand to
    memory and a small JSON file. Exception-safe: never raises into startup.
    """
    global _STORED_OPERATOR
    try:
        if not isinstance(plan, dict):
            return {}
        callsign = str(plan.get("callsign") or "").strip().upper()
        code = str(plan.get("airline") or "").strip().upper()
        if not code and callsign:
            code = str(callsign_prefix(callsign) or "").upper()
        branding = plan.get("airline_branding") if isinstance(plan.get("airline_branding"), dict) else {}
        brand_name = str(branding.get("name") or "").strip()
        brand = brand_name if _is_real_operator_brand(brand_name, code) else ""
        if not brand and code:
            brand = _airline_canonical_name(code)
        if not brand and code:
            try:
                airline = load_airlines().get(code)
                if airline and str(airline.name or "").strip():
                    candidate = str(airline.name).strip()
                    if _is_real_operator_brand(candidate, code):
                        brand = candidate
            except Exception:
                pass
        record = {
            "callsign": callsign,
            "airline_code": code,
            "operator_brand": brand,
            "resolved_utc": _utc(),
        }
        with _STORED_OPERATOR_LOCK:
            _STORED_OPERATOR = dict(record)
        try:
            path = _operator_store_path()
            temp = path.with_name(path.name + ".tmp")
            temp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            os.replace(temp, path)
        except Exception:
            pass
        # Tell GSX to show the operator popup instead of auto-selecting.
        # Sent early so the preference is active before any GSX service session
        # begins at this airport.
        try:
            _official_command(
                "handler.set",
                {"target": "gate", "name": "autoSelectOperator", "value": False},
                timeout=1.0,
            )
        except Exception:
            pass
        return record
    except Exception:
        return {}


def stored_operator_brand() -> str:
    """Return the early-resolved operator brand from memory, loading JSON if empty.

    Cheap and exception-safe. Returns an empty string when nothing is stored.
    """
    global _STORED_OPERATOR
    try:
        with _STORED_OPERATOR_LOCK:
            current = _STORED_OPERATOR
        if isinstance(current, dict):
            return str(current.get("operator_brand") or "").strip()
        path = _operator_store_path()
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                with _STORED_OPERATOR_LOCK:
                    _STORED_OPERATOR = dict(data)
                return str(data.get("operator_brand") or "").strip()
    except Exception:
        return ""
    return ""


def refresh_stored_operator_from_cache() -> dict:
    """Lazily warm the stored operator from the cached SimBrief plan.

    Lets the observer warm the brand when startup had not resolved it yet.
    Exception-safe.
    """
    try:
        settings = load_settings()
        user = str(settings.get("identity", {}).get("simbrief_user_id") or "").strip()
        if not user:
            return {}
        plan = cached_plan(user)
        if isinstance(plan, dict) and plan.get("ok"):
            return warm_operator_from_simbrief_plan(plan)
    except Exception:
        return {}
    return {}


def _operator_preference_candidates() -> list[str]:
    values: set[str] = set()
    try:
        settings = load_settings()
        user = str(settings.get("identity", {}).get("simbrief_user_id") or "")
        plan = cached_plan(user) if user else None
        for path in (("airline",), ("airline_code",), ("icao_airline",), ("callsign",), ("general", "icao_airline"), ("general", "airline"), ("general", "callsign")):
            cur: Any = plan or {}
            for key in path:
                cur = cur.get(key) if isinstance(cur, dict) else None
            if cur:
                text = str(cur).strip()
                values.add(text)
                prefix = re.match(r"([A-Za-z]{2,4})", text)
                if prefix:
                    values.add(prefix.group(1).upper())
    except Exception:
        pass
    try:
        tel = read_telemetry(force=False)
        for key in ("title", "aircraft_title", "aircraft", "livery", "model"):
            val = tel.get(key)
            if isinstance(val, str) and val.strip():
                values.add(val.strip())
    except Exception:
        pass
    for code in list(values):
        if len(code.strip()) in {2, 3, 4}:
            values.update(_airline_aliases_from_database(code))
    # Well-known operator aliases where GSX labels commonly use brand text, not just ICAO.
    alias_map = {
        "EZY": {"easyJet", "Easy Jet", "EASY"},
        "EJU": {"easyJet Europe", "easyJet", "EASY"},
        "EZS": {"easyJet Switzerland", "easyJet", "EASY"},
        "BAW": {"British Airways", "Speedbird"},
        "DLH": {"Lufthansa"},
        "RYR": {"Ryanair"},
        "SWR": {"Swiss", "Swiss International"},
        "AFR": {"Air France"},
        "KLM": {"KLM"},
    }
    for code, aliases in alias_map.items():
        if code in {v.upper() for v in values}:
            values.update(aliases)
    cleaned = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        norm = _normalized(text)
        if len(norm) < 2 or norm in seen:
            continue
        seen.add(norm)
        cleaned.append(text)
    cleaned.sort(key=lambda x: (0 if len(x) <= 4 else 1, -len(x)))
    return cleaned




def _current_operator_flight_signature() -> str:
    """Stable flight identity; an operator is reusable only on this exact sector."""
    try:
        plan = cached_plan() or {}
    except Exception:
        plan = {}
    pieces: list[str] = []
    for path in (
        ("airline",), ("airline_code",), ("icao_airline",), ("callsign",),
        ("flight_number",), ("origin", "icao"), ("origin", "icao_code"),
        ("destination", "icao"), ("destination", "icao_code"),
        ("aircraft", "registration"), ("general", "icao_airline"),
        ("general", "flight_number"), ("general", "callsign"),
    ):
        cur: Any = plan
        for key in path:
            cur = cur.get(key) if isinstance(cur, dict) else None
        if cur:
            value = str(cur).strip().upper()
            if value and value not in pieces:
                pieces.append(value)
    return "|".join(pieces)

def _remember_selected_operator(option: str) -> None:
    global _LAST_SELECTED_OPERATOR, _LAST_SELECTED_OPERATOR_FLIGHT
    text = str(option or "").strip()
    if not text:
        return
    _LAST_SELECTED_OPERATOR = text
    _LAST_SELECTED_OPERATOR_FLIGHT = _current_operator_flight_signature()
    _set_latch("selected_gsx_operator", text)



def _reusable_selected_operator() -> str:
    current = _current_operator_flight_signature()
    if not _LAST_SELECTED_OPERATOR:
        return ""
    # Unknown identity is never safe to reuse across sectors.
    if not current or not _LAST_SELECTED_OPERATOR_FLIGHT:
        return ""
    if _LAST_SELECTED_OPERATOR_FLIGHT != current:
        return ""
    return _LAST_SELECTED_OPERATOR

def _preferred_operator_option_index(title: str, options: list[str]) -> int | None:
    if not _operator_prompt(title) or not options:
        return None
    menu = {
        "available": True,
        "title": title,
        "raw_options": list(options),
        "raw_disabled": [False] * len(options),
        "raw_icon_wide": [False] * len(options),
        "options": list(options),
    }
    choice = _operator_observer_choice(menu, None)
    if not choice:
        _set_latch("operator_preference_attempted", "ambiguous")
        _automation_record("OPERATOR", "No clear airline-matched GSX operator; keeping the GSX current/default choice")
        return None
    _automation_record("OPERATOR", f"Matched operating-airline operator: {choice['label']}")
    return int(choice["index"])

_OPERATOR_LEGAL_WORDS = {
    "ag", "gmbh", "mbh", "ltd", "limited", "plc", "llc", "inc",
    "incorporated", "corp", "corporation", "company", "co", "sa", "sas",
    "spa", "srl", "bv", "nv", "group", "holding", "holdings", "airways",
    "airlines", "airline",
}
_OPERATOR_MENU_WORDS = (
    "operator", "handling", "handler", "ground handler", "service provider",
    "choose company", "select company", "select a company", "company selection",
)
_OPERATOR_NAV_WORDS = (
    "cancel", "back", "return", "abort", "close", "more services",
    "additional services", "previous page", "next page",
)
_OPERATOR_DIRECTION_WORDS = (
    "left", "right", "straight", "nose left", "nose right", "tail left",
    "tail right", "facing", "clockwise", "counterclockwise",
)


def _operator_display_name(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^\s*\d+\s*[.)\-:]?\s*", "", text)
    text = re.sub(r"[\[(]\s*gsx\s+(?:choice|selected|default)\s*[\])]", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" -–—:;,.()[]")
    return text


def _operator_core_words(value: Any) -> list[str]:
    words = _normalized(_operator_display_name(value)).split()
    return [word for word in words if word not in _OPERATOR_LEGAL_WORDS]


def _operator_core(value: Any) -> str:
    return " ".join(_operator_core_words(value))


def _operator_menu_arrays(menu: dict[str, Any]) -> tuple[list[str], list[bool], list[bool]]:
    raw_options = list(menu.get("raw_options") or [])
    if not raw_options:
        raw_entries = list(menu.get("entries") or [])
        raw_options = [_menu_entry_label(entry) for entry in raw_entries]
    if not raw_options:
        raw_options = [str(option or "") for option in list(menu.get("options") or [])]
    raw_disabled = list(menu.get("raw_disabled") or [])
    raw_icon_wide = list(menu.get("raw_icon_wide") or [])
    disabled = [bool(raw_disabled[i]) if i < len(raw_disabled) else False for i in range(len(raw_options))]
    icon_wide = [bool(raw_icon_wide[i]) if i < len(raw_icon_wide) else False for i in range(len(raw_options))]
    return raw_options, disabled, icon_wide


def _operator_company_indices(menu: dict[str, Any]) -> list[int]:
    options, disabled, _wide = _operator_menu_arrays(menu)
    title_n = _normalized(str(menu.get("title") or ""))
    result: list[int] = []
    for index, label in enumerate(options):
        norm = _normalized(label)
        if not norm or disabled[index]:
            continue
        if any(word in norm for word in _OPERATOR_NAV_WORDS):
            continue
        if _is_top_level_service_option(label):
            continue
        if ("pushback" in title_n or "direction" in title_n or "facing" in title_n) and any(word in norm for word in _OPERATOR_DIRECTION_WORDS):
            continue
        result.append(index)
    return result


def _probable_operator_menu(menu: dict[str, Any]) -> bool:
    if not isinstance(menu, dict) or not menu.get("available"):
        return False
    options, _disabled, icon_wide = _operator_menu_arrays(menu)
    company_indices = _operator_company_indices(menu)
    if not company_indices:
        return False
    title_n = _normalized(str(menu.get("title") or ""))
    if any(word in title_n for word in _OPERATOR_MENU_WORDS):
        return True
    wide_company_count = sum(1 for i in company_indices if i < len(icon_wide) and icon_wide[i])
    if wide_company_count >= 2:
        return True
    has_gsx_choice = any("gsx choice" in _normalized(options[i]) or "gsx selected" in _normalized(options[i]) for i in company_indices)
    return bool(has_gsx_choice and len(company_indices) >= 2)


def _collect_operator_identity_values(value: Any, out: list[str], depth: int = 0, key_hint: str = "") -> None:
    if depth > 4 or value is None:
        return
    if isinstance(value, dict):
        preferred = (
            "airline", "airlinename", "airline_name", "icao_airline", "airlineicao",
            "airline_icao", "iata_airline", "airlineiata", "callsign", "flight_number",
            "flightnumber", "operator",
        )
        for key, item in value.items():
            key_n = _normalized(str(key)).replace(" ", "")
            if key_n in preferred or any(token in key_n for token in ("airline", "callsign")):
                _collect_operator_identity_values(item, out, depth + 1, key_n)
        return
    if isinstance(value, (list, tuple)):
        for item in value[:20]:
            _collect_operator_identity_values(item, out, depth + 1, key_hint)
        return
    if isinstance(value, (str, int)):
        text = str(value).strip()
        if text and len(text) <= 120:
            out.append(text)


def _operator_observer_candidates(live_simbrief: Any = None) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        raw = str(value or "").strip()
        norm = _normalized(raw)
        if len(norm) < 2 or norm in seen:
            return
        seen.add(norm)
        ordered.append(raw)

    live_values: list[str] = []
    _collect_operator_identity_values(live_simbrief, live_values)
    for value in live_values:
        add(value)

    # RC10's known-working SimBrief/cache/livery discovery remains the fallback.
    for value in _operator_preference_candidates():
        add(value)

    codes: list[str] = []
    for value in list(ordered):
        compact = re.sub(r"[^A-Za-z0-9]", "", value).upper()
        match = re.match(r"^([A-Z]{2,4})(?=\d|$)", compact)
        if match and match.group(1) not in codes:
            codes.append(match.group(1))
        if 2 <= len(compact) <= 4 and compact not in codes:
            codes.append(compact)
    for code in codes:
        add(code)
        for alias in sorted(_airline_aliases_from_database(code), key=lambda item: (-len(item), item.lower())):
            add(alias)

    remembered = _reusable_selected_operator()
    if remembered:
        remembered_n = _normalized(remembered)
        ordered = [remembered, *[item for item in ordered if _normalized(item) != remembered_n]]

    # The authoritative operating-airline brand from airlines.csv is placed at
    # the FRONT of the candidate list (above live values, codes, DB aliases AND
    # the remembered selection) so the airline-of-record outranks everything
    # else when matching a GSX handler menu in the current sector.
    canonical_brand = ""
    for value in live_values:
        compact = re.sub(r"[^A-Za-z0-9]", "", str(value)).upper()
        match = re.match(r"^([A-Z]{2,4})(?=\d|$)", compact)
        code = match.group(1) if match else (compact if 2 <= len(compact) <= 4 else "")
        if not code:
            continue
        brand = _airline_canonical_name(code)
        if brand:
            canonical_brand = brand
            break
    if canonical_brand:
        brand_n = _normalized(canonical_brand)
        ordered = [canonical_brand, *[item for item in ordered if _normalized(item) != brand_n]]

    # The authoritative operator brand resolved EARLY at SimBrief-fetch time
    # (callsign -> brand, e.g. "Lufthansa") is placed at the very FRONT of the
    # ordered candidate list, above every other source, so it outranks the wide
    # pollutable candidate net when matching a GSX handler menu.
    stored_brand = stored_operator_brand()
    if stored_brand:
        stored_n = _normalized(stored_brand)
        if stored_n:
            ordered = [stored_brand, *[item for item in ordered if _normalized(item) != stored_n]]
    return ordered


def _operator_match_score(candidate: str, option: str) -> int:
    cand_name = _operator_display_name(candidate)
    opt_name = _operator_display_name(option)
    cand_n = _normalized(cand_name)
    opt_n = _normalized(opt_name)
    if not cand_n or not opt_n:
        return 0
    if cand_n == opt_n:
        return 1200 + len(cand_n)

    cand_words = _operator_core_words(cand_name)
    opt_words = _operator_core_words(opt_name)
    if not cand_words or not opt_words:
        return 0
    cand_core = " ".join(cand_words)
    opt_core = " ".join(opt_words)
    if cand_core == opt_core:
        return 1100 + len(cand_core)

    cand_set = set(cand_words)
    opt_set = set(opt_words)

    # Authoritative brand-contains match. Fires only for single-token brands
    # of length >= 4 (real brand names like "Lufthansa"/"Ryanair", not 2-3 char
    # ICAO codes like DLH/RYR which stay on the subset branches below). The
    # brand must appear as a whole word in the option. Subsidiary-suffixed
    # siblings (e.g. "Lufthansa Cargo" vs brand "Lufthansa") are explicitly
    # rejected here so a cargo/station-only handler is never auto-picked.
    if len(cand_words) == 1 and len(cand_words[0]) >= 4 and cand_core in opt_set:
        extras = opt_set - cand_set
        if not (extras & _OPERATOR_SUBSIDIARY_SUFFIXES):
            return 1180 + len(cand_core)
        return 0

    if len(cand_core.replace(" ", "")) in {2, 3, 4} and cand_core in opt_set:
        return 900
    if cand_set.issubset(opt_set):
        extras = len(opt_set - cand_set)
        return 820 + 20 * len(cand_set) - 90 * extras
    if opt_set.issubset(cand_set):
        extras = len(cand_set - opt_set)
        return 760 + 18 * len(opt_set) - 35 * extras

    cand_compact = "".join(cand_words)
    opt_compact = "".join(opt_words)
    if len(cand_compact) >= 5 and cand_compact in opt_compact:
        return max(500, 720 - 25 * max(0, len(opt_compact) - len(cand_compact)))
    overlap = len(cand_set & opt_set)
    if overlap:
        return int(420 * overlap / max(1, len(cand_set | opt_set)))
    return 0


def _brand_contained(brand_n: str, display_n: str) -> bool:
    """Whole-word-ish containment of a normalized brand inside a display name.

    Both inputs are already `_normalized` (space-separated lowercase tokens).
    Accepts an exact match or the brand appearing as a contiguous whole-word
    run inside the option label.
    """
    if not brand_n or not display_n:
        return False
    if brand_n == display_n:
        return True
    return f" {brand_n} " in f" {display_n} "


def _operator_observer_choice(menu: dict[str, Any], live_simbrief: Any = None) -> dict[str, Any] | None:
    if not _probable_operator_menu(menu):
        return None
    options, disabled, _wide = _operator_menu_arrays(menu)
    company_indices = _operator_company_indices(menu)

    def gsx_choice() -> dict[str, Any] | None:
        # This is the only fallback. Never select the first company blindly.
        for raw_index in company_indices:
            if raw_index >= len(options) or disabled[raw_index]:
                continue
            norm = _normalized(options[raw_index])
            if "gsx choice" in norm or "gsx selected" in norm or "gsx default" in norm:
                return {
                    "index": raw_index,
                    "label": str(options[raw_index]),
                    "candidate": "GSX choice",
                    "score": 0,
                    "fallback": True,
                }
        return None

    def first_company_choice() -> dict[str, Any] | None:
        # #40 tier 3 (user-defined priority: airline match -> GSX choice -> any
        # operator): when the menu has no airline match and no [GSX choice]
        # label, select the first enabled company option instead of giving up
        # ("pilot selection required"). Returns None only when there are no
        # enabled company options at all, keeping the pilot-selection safety net.
        for raw_index in company_indices:
            if raw_index >= len(options) or disabled[raw_index]:
                continue
            return {
                "index": raw_index,
                "label": str(options[raw_index]),
                "candidate": "first available operator",
                "score": 0,
                "fallback": True,
            }
        return None

    candidates = _operator_observer_candidates(live_simbrief)

    # Authoritative brand contains-match shortcut. The early-resolved operating
    # airline brand (or, if none was stored, the first authoritative candidate)
    # is matched "not too strictly": any enabled company option whose display
    # name CONTAINS the brand as a whole word is eligible. Prefer the plainest
    # option (fewest extra core words beyond the brand, then shortest label) so
    # mainline "Lufthansa" wins over "Lufthansa Cargo"/"Lufthansa CityLine";
    # a subsidiary-only match is still accepted. This runs BEFORE the existing
    # scoring loop; when nothing contains the brand it falls through unchanged.
    brand = stored_operator_brand()
    if not brand and candidates:
        brand = candidates[0]
    brand_n = _normalized(brand)
    if brand_n:
        brand_word_count = len(_operator_core_words(brand))
        brand_matches: list[tuple[int, int, int, str]] = []
        for raw_index in company_indices:
            if raw_index >= len(options) or disabled[raw_index]:
                continue
            label = str(options[raw_index] or "")
            display_n = _normalized(_operator_display_name(label))
            if not _brand_contained(brand_n, display_n):
                continue
            extra = max(0, len(_operator_core_words(label)) - brand_word_count)
            brand_matches.append((extra, len(label), raw_index, label))
        if brand_matches:
            brand_matches.sort(key=lambda item: (item[0], item[1], item[2]))
            _extra, _label_len, chosen_index, chosen_label = brand_matches[0]
            _automation_record(
                "OPERATOR",
                f"Authoritative operator brand match: brand='{brand}', menu label='{chosen_label}', index={chosen_index}",
            )
            return {
                "index": chosen_index,
                "label": chosen_label,
                "candidate": brand,
                "score": 2000,
                "fallback": False,
            }

    if not candidates:
        return gsx_choice() or first_company_choice()
    ranked: list[tuple[int, int, int, str]] = []
    for raw_index in company_indices:
        if raw_index >= len(options) or disabled[raw_index]:
            continue
        label = str(options[raw_index] or "")
        best_score = 0
        best_candidate = ""
        for candidate_index, candidate in enumerate(candidates):
            score = _operator_match_score(candidate, label) - min(candidate_index, 80)
            if score > best_score:
                best_score = score
                best_candidate = candidate
        if best_score:
            # Prefer the shorter plain brand when scores are otherwise equal.
            ranked.append((best_score, -len(_operator_core_words(label)), -raw_index, best_candidate))
    if not ranked:
        return gsx_choice() or first_company_choice()
    ranked.sort(reverse=True)
    best_score, _shortness, negative_index, matched_candidate = ranked[0]
    raw_index = -negative_index
    second_score = ranked[1][0] if len(ranked) > 1 else 0
    if best_score < 620:
        return gsx_choice() or first_company_choice()
    if best_score < 1050 and second_score and best_score - second_score < 35:
        return gsx_choice() or first_company_choice()
    brand = candidates[0] if candidates else matched_candidate
    _automation_record(
        "OPERATOR",
        f"Candidate-resolved operator: airline='{brand}', candidate='{matched_candidate}', menu label='{str(options[raw_index])}', index={raw_index}, score={best_score}",
    )
    return {
        "index": raw_index,
        "label": str(options[raw_index]),
        "candidate": matched_candidate,
        "score": best_score,
        "fallback": False,
    }


def _operator_menu_fingerprint(menu: dict[str, Any]) -> str:
    options, disabled, icon_wide = _operator_menu_arrays(menu)
    payload = {
        "title": str(menu.get("title") or ""),
        "options": options,
        "disabled": disabled,
        "icon_wide": icon_wide,
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _operator_observer_active(session_generation: int) -> bool:
    with _AUTOMATION_LOCK:
        return bool(
            _AUTOMATION.get("running")
            and int(_AUTOMATION.get("session_generation") or 0) == int(session_generation)
        )


def _next_operator_command_id(session_generation: int) -> str:
    global _OPERATOR_OBSERVER_SEQUENCE
    with _OPERATOR_OBSERVER_LOCK:
        _OPERATOR_OBSERVER_SEQUENCE += 1
        return f"ops-operator-{int(session_generation)}-{_OPERATOR_OBSERVER_SEQUENCE}"


def _operator_observer_running() -> bool:
    with _OPERATOR_OBSERVER_LOCK:
        return bool(
            _OPERATOR_OBSERVER_THREAD
            and _OPERATOR_OBSERVER_THREAD.is_alive()
            and not _OPERATOR_OBSERVER_STOP.is_set()
        )


def _operator_observer_ready() -> bool:
    return bool(_operator_observer_running() and _OPERATOR_OBSERVER_CONNECTED.is_set())


def _operator_observer_worker(session_generation: int) -> None:
    current_menu_fingerprint = ""
    attempted_decisions: set[str] = set()
    popup_prepared = False
    popup_prepare_attempted_mono = 0.0
    while not _OPERATOR_OBSERVER_STOP.is_set() and _operator_observer_active(session_generation):
        connected = False
        for url in _official_candidates():
            if _OPERATOR_OBSERVER_STOP.is_set() or not _operator_observer_active(session_generation):
                return
            parsed = urlparse(url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or _remote_port()
            try:
                with socket.create_connection((host, port), timeout=0.20):
                    pass
            except OSError:
                continue
            try:
                from websockets.sync.client import connect  # type: ignore
                state: dict[str, Any] = {}
                pending: dict[str, Any] | None = None
                with connect(_ws_url(url), open_timeout=0.45, close_timeout=0.15, ping_interval=None, proxy=None) as ws:
                    connected = True
                    _OPERATOR_OBSERVER_CONNECTED.set()
                    ws.send(json.dumps({"type": "subscribe", "channels": ["state"]}))
                    # Immediately tell GSX to show the operator popup instead of
                    # auto-selecting.  Sent on every observer connect so a GSX
                    # restart does not lose the preference.
                    try:
                        cmd_id = _next_operator_command_id(session_generation)
                        ws.send(json.dumps({
                            "type": "command", "id": cmd_id, "verb": "handler.set",
                            "args": {"target": "gate", "name": "autoSelectOperator", "value": False},
                        }))
                    except Exception:
                        pass
                    while not _OPERATOR_OBSERVER_STOP.is_set() and _operator_observer_active(session_generation):
                        msg: dict[str, Any] | None = None
                        try:
                            raw = ws.recv(timeout=0.20)
                            msg = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode("utf-8", "ignore"))
                        except TimeoutError:
                            pass
                        except Exception:
                            break

                        if isinstance(msg, dict):
                            msg_type = str(msg.get("type") or "")
                            if msg_type == "snapshot":
                                state = {key: value for key, value in msg.items() if key not in {"type", "v", "ts", "id"}}
                            elif msg_type == "patch":
                                _apply_official_patch(state, str(msg.get("path") or ""), msg.get("value"))
                            elif msg_type == "result" and pending and str(msg.get("id") or "") == str(pending.get("id") or ""):
                                if pending.get("kind") == "handler_set":
                                    popup_prepared = bool(msg.get("ok"))
                                    if popup_prepared:
                                        _automation_record("OPERATOR", "GSX confirmed operator popup enabled (autoSelectOperator=false)")
                                    pending = None
                                else:
                                    decision_key = str(pending.get("decision_key") or "")
                                    if decision_key:
                                        attempted_decisions.add(decision_key)
                                    if bool(msg.get("ok")):
                                        selected = str(pending.get("label") or "").strip()
                                        _remember_selected_operator(selected)
                                        _set_latch("operator_preference_attempted", True)
                                        mode_text = "GSX choice" if pending.get("fallback") else "operating-airline match"
                                        _automation_record("OPERATOR", f"GSX confirmed operator ({mode_text}): {selected}")
                                    else:
                                        error = msg.get("error") if isinstance(msg.get("error"), dict) else {}
                                        detail = str(error.get("message") or error.get("code") or "menu.pick was refused")
                                        _automation_record("OPERATOR", f"GSX operator selection was not accepted: {detail}")
                                    pending = None

                        if pending:
                            if time.monotonic() - float(pending.get("sent_mono") or 0.0) > 2.5:
                                _automation_record("OPERATOR", "GSX operator selection confirmation timed out; keeping the live GSX choice")
                                decision_key = str(pending.get("decision_key") or "")
                                if decision_key:
                                    attempted_decisions.add(decision_key)
                                pending = None
                            continue

                        handler_data = state.get("handlerData") if isinstance(state.get("handlerData"), dict) else {}
                        gate_data = handler_data.get("gate") if isinstance(handler_data.get("gate"), dict) else {}
                        now_mono = time.monotonic()
                        if gate_data and not popup_prepared and now_mono - popup_prepare_attempted_mono >= 2.0:
                            popup_prepare_attempted_mono = now_mono
                            command_id = _next_operator_command_id(session_generation)
                            ws.send(json.dumps({
                                "type": "command", "id": command_id, "verb": "handler.set",
                                "args": {"target": "gate", "name": "autoSelectOperator", "value": False},
                            }))
                            pending = {"kind": "handler_set", "id": command_id, "sent_mono": now_mono}
                            continue

                        menu = _official_menu_from_state(state)
                        if not _probable_operator_menu(menu):
                            # A later service can legitimately show the exact same
                            # company list. Reset only after the current menu closes
                            # or changes, so each new popup is handled once.
                            current_menu_fingerprint = ""
                            attempted_decisions.clear()
                            continue
                        fingerprint = _operator_menu_fingerprint(menu)
                        if fingerprint != current_menu_fingerprint:
                            current_menu_fingerprint = fingerprint
                            attempted_decisions.clear()
                        live_simbrief = handler_data.get("simbrief") if isinstance(handler_data, dict) else None
                        identity_key = json.dumps(live_simbrief or {}, ensure_ascii=True, sort_keys=True, default=str)
                        decision_key = fingerprint + "|" + identity_key
                        if decision_key in attempted_decisions:
                            continue
                        choice = _operator_observer_choice(menu, live_simbrief)
                        if not choice:
                            attempted_decisions.add(decision_key)
                            _set_latch("operator_preference_attempted", "no_clear_match")
                            _automation_record("OPERATOR", "No clear airline match and no explicit GSX choice was available; pilot selection is required")
                            continue

                        # Re-read the same live state immediately before sending. The
                        # index is the raw position in the latest menu.entries array.
                        latest_menu = _official_menu_from_state(state)
                        if _operator_menu_fingerprint(latest_menu) != fingerprint:
                            continue
                        command_id = _next_operator_command_id(session_generation)
                        ws.send(json.dumps({
                            "type": "command",
                            "id": command_id,
                            "verb": "menu.pick",
                            "args": {"index": int(choice["index"])},
                        }))
                        pending = {
                            "kind": "menu_pick",
                            "id": command_id,
                            "label": choice["label"],
                            "index": int(choice["index"]),
                            "fingerprint": fingerprint,
                            "decision_key": decision_key,
                            "fallback": bool(choice.get("fallback")),
                            "sent_mono": time.monotonic(),
                        }
                        if choice.get("fallback"):
                            _automation_record("OPERATOR", f"No clear airline match; selecting explicit GSX choice: {choice['label']}")
                        else:
                            _automation_record("OPERATOR", f"Selecting operating-airline GSX operator: {choice['label']}")
            except Exception:
                continue
            finally:
                _OPERATOR_OBSERVER_CONNECTED.clear()
        if not connected:
            _OPERATOR_OBSERVER_STOP.wait(0.35)
        else:
            _OPERATOR_OBSERVER_STOP.wait(0.15)


def _start_operator_observer(session_generation: int) -> None:
    global _OPERATOR_OBSERVER_THREAD
    with _OPERATOR_OBSERVER_LOCK:
        previous = _OPERATOR_OBSERVER_THREAD
        _OPERATOR_OBSERVER_STOP.set()
    if previous and previous.is_alive():
        previous.join(timeout=0.6)
    with _OPERATOR_OBSERVER_LOCK:
        _OPERATOR_OBSERVER_STOP.clear()
        _OPERATOR_OBSERVER_CONNECTED.clear()
        _OPERATOR_OBSERVER_THREAD = threading.Thread(
            target=_operator_observer_worker,
            args=(int(session_generation),),
            name="OpsRoom-GSX-OperatorObserver",
            daemon=True,
        )
        _OPERATOR_OBSERVER_THREAD.start()


def _stop_operator_observer() -> None:
    _OPERATOR_OBSERVER_STOP.set()
    _OPERATOR_OBSERVER_CONNECTED.clear()


_TOP_LEVEL_SERVICE_WORDS = (
    "request boarding", "start boarding", "request deboarding", "request refueling", "request refuelling",
    "request refuel", "request catering", "request water", "request lavatory", "request cleaning",
    "request de icing", "request deicing", "prepare for pushback", "request pushback", "start pushback",
    "operate jetway", "operate jetways", "operate stairs", "operate gpu", "ground power",
)


def _is_top_level_service_option(label: str) -> bool:
    norm = _normalized(label)
    if not norm:
        return False
    if any(word in norm for word in _TOP_LEVEL_SERVICE_WORDS):
        return True
    # Also block exact service alias labels that GSX may show on its main menu.
    for key, aliases in ALIASES.items():
        if key in {"pushback", "jetway", "stairs", "gpu"}:
            continue
        if _matching_index([label], aliases) is not None and ("request" in norm or norm in {_normalized(a) for a in aliases}):
            return True
    return False


def _non_service_candidates(normalized: list[str], options: list[str], cancel_words: tuple[str, ...]) -> list[int]:
    return [
        i for i, option in enumerate(normalized)
        if not any(word in option for word in cancel_words) and not _is_top_level_service_option(options[i])
    ]


def _fenix_controlled_session_active() -> bool:
    return bool(_get_latch("fenix_controlled_session"))


def _block_if_fenix_refuel(service: str) -> dict[str, Any] | None:
    if service != "refuel" or not _fenix_controlled_session_active():
        return None
    # Do not mark refuel complete here. Fenix still needs its EFB loading task to
    # drive the first valid fuel load. This guard only prevents OPS ROOM from
    # launching a separate/duplicate generic GSX refuel from the service plan,
    # manual automation or follow-up resolver.
    _set_latch("generic_refuel_blocked_by_fenix", True)
    reason = "Generic GSX refuel blocked: Fenix EFB loading task owns the first refuel request"
    _automation_record("GSX_BLOCK", "service=refuel reason=fenix_controlled_preloading")
    return {"ok": True, "blocked": True, "already_requested": True, "service": service, "reason": reason}

def _automatic_option_index(title: str, options: list[str], service: str = "") -> int | None:
    """Choose a default for GSX follow-up prompts.

    OPS ROOM should clear all routine GSX prompts automatically. The only prompt
    intentionally left to the pilot is pushback direction/parking orientation.
    """
    if not options:
        return None
    normalized = [_normalized(option) for option in options]
    title_n = _normalized(title)
    cancel_words = ("cancel", "abort", "back", "return", "no thanks", "stop", "close")
    if service in {"pushback", "departure"} and _looks_like_pushback_direction(title, options):
        return None
    if service in {"deboarding", "cleaning", "lavatory", "water", "catering"} and _arrival_mode_active() and _looks_like_gate_selection(title, options):
        detected_index = _detected_stand_menu_index(title, options)
        return detected_index
    operator_index = _preferred_operator_option_index(title, options)
    if operator_index is not None:
        return operator_index
    preferred = (
        "automatic", "recommended", "default", "gsx choice", "gsx selected",
        "use gsx", "select automatically", "auto select", "yes", "confirm",
        "complete service", "complete", "finish service", "finish", "continue", "ok", "board crew", "crew included", "with crew", "selected",
    )
    for needle in preferred:
        for index, option in enumerate(normalized):
            if needle in option and not any(word in option for word in cancel_words) and not _is_top_level_service_option(options[index]):
                return index
    candidates = _non_service_candidates(normalized, options, cancel_words)
    if len(candidates) == 1:
        return candidates[0]
    # For non-pushback sub-prompts, take the first safe non-service option.
    # Never pick top-level Request Refueling/Boarding/etc here; those are new
    # services, not follow-up answers.
    if service not in {"pushback", "departure"}:
        # Operator/handler prompts must never fall back to the first company in
        # the menu. Prefer the flight airline above, then an explicit GSX/Auto
        # choice. If neither exists, leave the prompt to the pilot.
        if any(word in title_n for word in ("operator", "handling", "handler", "company")):
            return None
        if any(word in title_n for word in ("vehicle", "truck", "crew", "confirm", "complete", "continue", "select")):
            return candidates[0] if len(candidates) == 1 else None
        return None
    # Pushback sub-prompts that are not direction choices, e.g. operator/tug/crew,
    # can still be resolved automatically.
    if any(word in title_n for word in ("operator", "handling", "handler", "company")):
        return None
    if any(word in title_n for word in ("vehicle", "tug", "crew", "truck")):
        return candidates[0] if len(candidates) == 1 else None
    return None


def _resolve_followups(initial: dict[str, Any], service: str, max_steps: int = 8) -> dict[str, Any]:
    current = initial
    selections: list[str] = []
    for _ in range(max_steps):
        menu = current.get("menu") or _active_menu(prefer_official=True)
        options = list(menu.get("options") or [])
        if not menu.get("available") or not options:
            break

        operator_menu = _probable_operator_menu(menu)
        if operator_menu and str(menu.get("source") or "") == "official-remote-api-v2" and _operator_observer_ready():
            # The observer owns only the operator popup. It cannot alter the
            # service command result, requested latches, Fenix loading, or the
            # Departure sequence. Delayed menus are resolved on its live socket.
            _automation_record("OPERATOR", "Live GSX operator menu detected; resolving on the independent observer")
            break

        # The menu file can remain on the service list for a moment after GSX
        # accepted a command. Do not interpret that stale list as a new prompt.
        if _matching_index(options, ALIASES.get(service, ())) is not None and any(
            word in _normalized(str(menu.get("title") or "")) for word in ("ground services", "main menu")
        ):
            break

        if operator_menu:
            handler_data = _official_handler_data_from_state(dict(_OFFICIAL_STATE))
            live_simbrief = handler_data.get("simbrief") if isinstance(handler_data, dict) else None
            operator_choice = _operator_observer_choice(menu, live_simbrief)
            if operator_choice:
                wanted = str(operator_choice.get("label") or "")
                index = next((i for i, option in enumerate(options) if str(option) == wanted), None)
            else:
                index = None
        else:
            index = _automatic_option_index(str(menu.get("title") or ""), options, service)

        if index is None:
            reason = "GSX requires pilot choice. Select the pushback direction in the GSX control surface."
            if operator_menu:
                reason = "Select the handling operator in the live GSX menu; no clear airline match or explicit GSX choice was available."
            elif _arrival_mode_active() and _looks_like_gate_selection(str(menu.get("title") or ""), options):
                detected = dict(_AUTOMATION.get("arrival_stand") or {})
                if not detected:
                    detected = _detect_arrival_stand()
                    with _AUTOMATION_LOCK:
                        _AUTOMATION["arrival_stand"] = detected
                reason = "Select/confirm the destination gate in the live GSX menu, then continue arrival services. OPS ROOM will not reuse the departure gate."
                if detected.get("ok"):
                    stand = detected.get("stand") or {}
                    reason = f"Detected {stand.get('label') or 'stand'} near the aircraft, but GSX needs live gate confirmation. Select the matching destination gate in GSX."
            return {
                "ok": True,
                "automated": bool(selections),
                "requires_selection": True,
                "reason": reason,
                "menu": menu,
                "selections": selections,
            }
        expected = str(options[index])
        if _is_top_level_service_option(expected):
            reason = f"GSX follow-up resolver stopped before selecting top-level service option: {expected}"
            _automation_record("GSX_BLOCK", reason)
            return {"ok": True, "automated": bool(selections), "blocked": True, "requires_selection": False, "reason": reason, "menu": menu, "selections": selections}
        if _departure_mode_active() and _option_forbidden_in_departure(expected):
            reason = f"Departure mode blocked GSX follow-up option: {expected}. GSX appears to be in an arrival/turnaround state; stopping this automatic pick and continuing monitor."
            _automation_record("GUARD", reason)
            return {"ok": True, "automated": bool(selections), "blocked": True, "departure_guard": True, "requires_selection": False, "reason": reason, "menu": menu, "selections": selections}
        selections.append(expected)
        current = select_menu_by_label(expected)
        if current.get("ok") and operator_menu:
            _remember_selected_operator(expected)
            _set_latch("operator_preference_attempted", True)
        if not current.get("ok"):
            return {**current, "ok": True, "automated": bool(selections), "selections": selections, "requires_selection": False, "reason": current.get("reason") or "GSX menu changed; continuing monitor"}
        time.sleep(0.2)
    return {**current, "ok": True, "automated": True, "selections": selections}


def _active_menu(prefer_official: bool = True) -> dict[str, Any]:
    if prefer_official:
        official = _official_status(force=True)
        menu = official.get("menu") if isinstance(official.get("menu"), dict) else {}
        if menu.get("available") and menu.get("options"):
            return menu
    return read_menu()


def _find_service_through_pages(service: str, initial_menu: dict[str, Any] | None = None, max_pages: int = 4) -> tuple[int | None, dict[str, Any]]:
    menu = initial_menu if isinstance(initial_menu, dict) and initial_menu.get("options") else _active_menu(prefer_official=True)
    for _ in range(max_pages):
        options = list(menu.get("options") or [])
        index = _matching_index(options, ALIASES[service])
        if index is not None:
            return index, menu
        additional = _matching_index(options, ADDITIONAL_ALIASES)
        if additional is None:
            return None, menu
        selected = select_menu_by_label(str(options[additional]), ADDITIONAL_ALIASES)
        if not selected.get("ok"):
            return None, selected.get("menu") or menu
        menu = selected.get("menu") or _active_menu(prefer_official=True)
    return None, menu


def _official_service_id(service: str) -> str:
    return REMOTE_SERVICE_IDS.get(service, service[:1].upper() + service[1:])


def _official_remote_ready() -> bool:
    official = _official_status(force=True)
    return bool(official.get("reachable") and official.get("ws_connected") and official.get("gsx_running"))


def _trigger_service_remote_v2(service: str, automate: bool = True) -> dict[str, Any]:
    if _departure_mode_active() and service in _DEPARTURE_FORBIDDEN_SERVICES:
        return _departure_guard_result(service)
    blocked = _block_if_fenix_refuel(service)
    if blocked:
        return blocked
    service_id = _official_service_id(service)
    snap = status(force=True)
    services = snap.get("services") or {}
    entry = services.get(service) if isinstance(services, dict) else None
    raw = None
    if isinstance(entry, dict):
        raw = entry.get("raw")
    progress = snap.get("progress") or {}
    current_session_seen = bool(service in set(_AUTOMATION.get("requested") or []) or _get_latch(f"{service}_seen_active"))
    if raw in {4, 5, 7} or (raw == 6 and current_session_seen) or (service == "boarding" and _boarding_active_or_progress(raw, progress)):
        _mark_service_requested(service)
        return {"ok": True, "provider": "remote-v2", "already_active": True, "already_requested": True, "service": service, "remote_service": service_id, "raw": raw}
    command = _official_command("service.trigger", {"service": service_id}, timeout=1.8)
    if not command.get("ok"):
        return {"ok": False, "provider": "remote-v2", "service": service, "remote_service": service_id, "reason": command.get("reason") or "GSX Remote API refused the service request", "result": command.get("result") or {}, "code": command.get("code")}
    _record("SELECT", f"{service_id} [Remote API v2]")
    _invalidate()
    result: dict[str, Any] = {"ok": True, "provider": "remote-v2", "service": service, "remote_service": service_id, "menu": command.get("menu") or {}, "official_remote": command.get("official_remote") or {}}
    if automate:
        # Preserve the old working behavior of clearing routine GSX prompts, but
        # route every selection through the current live menu and the departure
        # safety guard. This also covers GSX's "complete service"/"continue"
        # prompts without ever selecting deboarding during departure.
        follow = _resolve_followups(result, service)
        result.update({k: v for k, v in follow.items() if k not in {"ok"}})
    if service in {"pushback", "departure"}:
        try:
            _start_pushback_direction_keepalive()
        except Exception:
            pass
    return result


def call_service(service: str, automate: bool = True) -> dict[str, Any]:
    service = str(service or "").strip().lower()
    if service not in ALIASES:
        raise ValueError("Unsupported GSX service")
    if _departure_mode_active() and service in _DEPARTURE_FORBIDDEN_SERVICES:
        return _departure_guard_result(service)
    blocked = _block_if_fenix_refuel(service)
    if blocked:
        return blocked
    if _official_remote_ready():
        remote = _trigger_service_remote_v2(service, automate=automate)
        if remote.get("ok") or remote.get("provider") == "remote-v2":
            return remote
    opened = open_menu()
    menu = opened.get("menu") or {}
    options = list(menu.get("options") or [])
    if not options:
        return {"ok": False, "requires_selection": False, "reason": "GSX did not publish a menu. Open the GSX toolbar once and retry.", "menu": menu}
    index = _matching_index(options, ALIASES[service])
    if index is None:
        activation = _matching_index(options, ("activate ground services", "activate services"))
        if activation is not None:
            selected = select_menu_by_label(str(options[activation]), ("activate ground services", "activate services"))
            menu = selected.get("menu") or _active_menu(prefer_official=True)
    index, menu = _find_service_through_pages(service, menu)
    if index is None:
        return {
            "ok": False,
            "requires_selection": False,
            "reason": f"{SERVICE_LABELS.get(service, service.upper())} is not available in this GSX state",
            "menu": menu,
        }
    expected_label = str(list((menu or {}).get("options") or [])[index]) if index is not None and index < len(list((menu or {}).get("options") or [])) else SERVICE_LABELS.get(service, service.upper())
    result = select_menu_by_label(expected_label, ALIASES[service])
    if not result.get("ok"):
        return {"ok": False, "requires_selection": False, "reason": result.get("reason") or "GSX menu changed before selection", "menu": result.get("menu") or menu}
    if automate:
        result = _resolve_followups(result, service)
    # Boarding music is now triggered only after GSX reports passenger boarding
    # actually in progress. A service request alone can happen while refuelling or
    # catering is still active, so it must not arm the cabin music timer.
    if service in {"pushback", "departure"} and result.get("ok"):
        try:
            # Do not stop all announcements here, only end boarding ambience.
            from .announcements import _stop_boarding_music  # type: ignore
            _stop_boarding_music("pushback prep")
        except Exception:
            pass
        # Keep the direction selection menu alive even for manual Ground Control
        # button calls. OPS ROOM must not choose the direction, only reopen/continue
        # the GSX menu every 60 seconds until the pilot selects one or pushback starts.
        try:
            _start_pushback_direction_keepalive()
        except Exception:
            pass
    return result


def _automation_record(stage: str, detail: str) -> None:
    global _LAST_AUTOMATION_RECORD
    now = time.monotonic()
    if _LAST_AUTOMATION_RECORD and _LAST_AUTOMATION_RECORD[0] == stage and _LAST_AUTOMATION_RECORD[1] == detail and now - _LAST_AUTOMATION_RECORD[2] < 25.0:
        return
    _LAST_AUTOMATION_RECORD = (stage, detail, now)
    with _AUTOMATION_LOCK:
        _AUTOMATION["stage"] = stage
        _AUTOMATION["detail"] = detail
        _AUTOMATION["updated_at"] = _utc()
        history = list(_AUTOMATION.get("history") or [])
        history.append({"time": _utc(), "stage": stage, "detail": detail})
        _AUTOMATION["history"] = history[-40:]
    _record("AUTO", f"{stage}: {detail}")


def _keep_pushback_direction_available_once() -> str:
    """Refresh the GSX pushback direction menu after GSX/Remote hides it.

    GSX can close/minimise the official remote menu while it is waiting for the
    pilot to select pushback direction. OPS ROOM should not choose the direction,
    but it can reopen the menu and select Continue Pushback so the direction
    choices stay available.
    """
    menu = _active_menu(prefer_official=True)
    options = list(menu.get("options") or [])
    title = str(menu.get("title") or "")
    if menu.get("available") and _looks_like_pushback_direction(title, options):
        return "direction-visible"

    opened = open_menu()
    menu = opened.get("menu") or _active_menu(prefer_official=True)
    options = list(menu.get("options") or [])
    title = str(menu.get("title") or "")
    if menu.get("available") and _looks_like_pushback_direction(title, options):
        return "direction-visible"

    index = _matching_index(options, CONTINUE_PUSHBACK_ALIASES)
    if index is None:
        return "continue-not-found"

    selected = select_menu_by_label(str(options[index]), CONTINUE_PUSHBACK_ALIASES)
    next_menu = selected.get("menu") or _active_menu(prefer_official=True)
    next_options = list(next_menu.get("options") or [])
    next_title = str(next_menu.get("title") or "")
    if next_menu.get("available") and _looks_like_pushback_direction(next_title, next_options):
        return "direction-refreshed"
    return "continue-selected"


def _pushback_has_started() -> bool:
    try:
        snapshot = status(force=True)
        services = snapshot.get("services") or {}
        pushback_raw = ((services.get("pushback") or {}).get("raw"))
        departure_raw = ((services.get("departure") or {}).get("raw"))
        try:
            pushback_raw = int(pushback_raw) if pushback_raw is not None else None
        except Exception:
            pushback_raw = None
        try:
            departure_raw = int(departure_raw) if departure_raw is not None else None
        except Exception:
            departure_raw = None
        # GSX has left the waiting-for-direction stage once the pushback service
        # itself becomes active. Departure state 6 is also treated as no longer
        # requiring direction keep-alive.
        if pushback_raw not in {None, 0}:
            return True
        if departure_raw == 6:
            return True
    except Exception:
        pass
    return False


def _pushback_direction_keepalive_loop(interval_seconds: float = 60.0, max_minutes: float = 30.0) -> None:
    deadline = time.monotonic() + max(60.0, max_minutes * 60.0)
    while not _PUSHBACK_KEEPALIVE_STOP.is_set() and time.monotonic() < deadline:
        try:
            if _pushback_has_started():
                _automation_record("PUSHBACK", "Pushback started; direction keep-alive stopped")
                break
            outcome = _keep_pushback_direction_available_once()
            if outcome == "direction-refreshed":
                _automation_record("PUSHBACK", "Pushback direction menu refreshed; waiting for pilot direction")
            elif outcome == "direction-visible":
                _automation_record("PUSHBACK", "Pushback direction menu available; waiting for pilot direction")
            elif outcome == "continue-selected":
                _automation_record("PUSHBACK", "Continue Pushback selected; waiting for pilot direction")
            elif outcome == "continue-not-found":
                _automation_record("PUSHBACK", "Waiting for GSX pushback direction prompt")
        except Exception as exc:
            _automation_record("PUSHBACK", f"Pushback direction keep-alive skipped: {type(exc).__name__}: {exc}")
        if _PUSHBACK_KEEPALIVE_STOP.wait(interval_seconds):
            break


def _start_pushback_direction_keepalive() -> None:
    """Direction prompt keep-alive is intentionally disabled.

    Re-opening/refreshing GSX direction menus after pushback is requested can
    interfere with GSX's own pushback state machine. OPS ROOM now monitors
    pushback passively after the prompt/action is presented.
    """
    global _PUSHBACK_KEEPALIVE_LAST
    _PUSHBACK_KEEPALIVE_STOP.set()
    _PUSHBACK_KEEPALIVE_LAST = time.monotonic()
    _automation_record("PUSHBACK", "Pushback direction keep-alive disabled; monitoring passively")

def _stop_pushback_direction_keepalive() -> None:
    _PUSHBACK_KEEPALIVE_STOP.set()


def _refresh_fenix_loading_snapshot() -> None:
    """Best-effort live loadsheet snapshot for the Live OFP panel.

    ``last_progress`` is normally written only by the Fenix GSX decision loop
    (``_sync_fenix_loading_state``) once the Fenix loading task has started.
    Before that the Live OFP saw an empty map and showed blank PAX/BAG-CARGO
    actuals even though the Fenix EFB loadsheet already reports boarded pax,
    loaded cargo and fuel. This fills ``last_progress`` directly from the
    loadsheet, TTL-guarded so the (up to 2 s) loadsheet read happens at most
    once every few seconds and never blocks or crashes the status call.
    """
    global _FENIX_SNAPSHOT_REFRESH_AT
    now = time.monotonic()
    if now - _FENIX_SNAPSHOT_REFRESH_AT < 5.0:
        return
    _FENIX_SNAPSHOT_REFRESH_AT = now
    try:
        if not _fenix_loading_available():
            return
        fenix_progress = _fenix_progress_safe()
        if not isinstance(fenix_progress, dict) or not fenix_progress.get("ok"):
            return
        if not any(fenix_progress.get(k) is not None for k in ("pax_loaded", "cargo_loaded_kg", "fuel_loaded_kg")):
            return
        with _AUTOMATION_LOCK:
            last = _FENIX_LOADING_STATE.get("last_progress")
            if not isinstance(last, dict):
                last = {}
            keep = {k: last.get(k) for k in ("passengers", "target", "boarding_raw", "boarding_cargo_percent") if k in last}
            _FENIX_LOADING_STATE["last_progress"] = {
                **keep,
                "passengers": keep.get("passengers", fenix_progress.get("pax_loaded")),
                "target": keep.get("target", fenix_progress.get("pax_target")),
                "boarding_cargo_percent": keep.get("boarding_cargo_percent", 0),
                "fenix": fenix_progress,
                "updated_at": _utc(),
            }
    except Exception:
        # The Live OFP must never be blocked or broken by a loadsheet refresh.
        pass


def automation_status() -> dict[str, Any]:
    _refresh_fenix_loading_snapshot()
    with _AUTOMATION_LOCK:
        payload = {"ok": True, **{key: (list(value) if isinstance(value, list) else value) for key, value in _AUTOMATION.items()}}
        payload["fenix_loading"] = dict(_FENIX_LOADING_STATE)
        return payload


def _service_raw(snapshot: dict[str, Any], key: str) -> int | None:
    value = ((snapshot.get("services") or {}).get(key) or {}).get("raw")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _request_once(service: str) -> dict[str, Any]:
    if _departure_mode_active() and service in _DEPARTURE_FORBIDDEN_SERVICES:
        return _departure_guard_result(service)
    blocked = _block_if_fenix_refuel(service)
    if blocked:
        return blocked
    if _get_latch(f"{service}_complete") or _get_latch(f"{service}_deferred_or_skipped"):
        return {"ok": True, "already_complete": True, "already_requested": True, "service": service}
    if service == "refuel" and _get_latch("refuel_complete_or_fenix_complete"):
        return {"ok": True, "already_complete": True, "already_requested": True, "service": service}
    try:
        snap_now = status(force=True)
        raw_now = _service_raw(snap_now, service)
        progress_now = snap_now.get("progress") or {}
        current_session_seen = bool(service in set(_AUTOMATION.get("requested") or []) or _get_latch(f"{service}_seen_active"))
        if raw_now in {4, 5, 7} or (raw_now == 6 and current_session_seen) or (service == "boarding" and _boarding_active_or_progress(raw_now, progress_now)):
            _mark_service_requested(service)
            return {"ok": True, "already_active": True, "already_requested": True, "raw": raw_now}
    except Exception:
        pass
    with _AUTOMATION_LOCK:
        requested = set(_AUTOMATION.get("requested") or [])
        if service in requested:
            return {"ok": True, "already_requested": True}
    retry_at = _AUTOMATION_REQUESTED_MONO.get(f"{service}_retry_after")
    if retry_at is not None and time.monotonic() < retry_at:
        return {"ok": False, "retrying": True, "service": service, "reason": "waiting for GSX service availability"}
    result = call_service(service, automate=True)
    if result.get("requires_selection"):
        _automation_record("ACTION REQUIRED", result.get("reason") or "Select the required GSX option in the control surface")
        if service in {"pushback", "departure"}:
            _start_pushback_direction_keepalive()
        return result
    if not result.get("ok"):
        reason = str(result.get("reason") or f"{service} is not available")
        low = reason.lower()
        if "did not publish" in low or "menu" in low or "not available" in low or "unavailable" in low or "refused" in low:
            _AUTOMATION_REQUESTED_MONO[f"{service}_retry_after"] = time.monotonic() + 5.0
        _automation_record("WAITING", f"{SERVICE_LABELS.get(service, service.upper())} is not available yet; OPS ROOM will retry")
    else:
        _AUTOMATION_REQUESTED_MONO.pop(f"{service}_retry_after", None)
        _mark_service_requested(service)
        _automation_record("REQUESTED", f"{SERVICE_LABELS.get(service, service.upper())} requested")
    return result


def _recent_request_age(service: str) -> float | None:
    started = _AUTOMATION_REQUESTED_MONO.get(service)
    return None if started is None else max(0.0, time.monotonic() - started)


def _boarding_active_or_progress(boarding_raw: int | None, progress: dict[str, Any]) -> bool:
    try:
        pax = int(progress.get("passengers_boarding_total") or 0)
    except Exception:
        pax = 0
    # Cargo percentage alone must not mean passenger boarding is active. Fenix can
    # have cargo/fuel/catering progress while pax remain 0/target, and treating
    # that as boarding active skips the actual GSX Boarding trigger.
    return bool(pax > 0 or boarding_raw in {4, 5, 6, 7})


def _latches() -> dict[str, Any]:
    latches = _AUTOMATION.get("latches")
    if not isinstance(latches, dict):
        latches = {}
        _AUTOMATION["latches"] = latches
    return latches


def _set_latch(name: str, value: Any = True) -> None:
    with _AUTOMATION_LOCK:
        latches = dict(_AUTOMATION.get("latches") or {})
        latches[name] = value
        _AUTOMATION["latches"] = latches
        _AUTOMATION["updated_at"] = _utc()


def _get_latch(name: str, default: Any = None) -> Any:
    with _AUTOMATION_LOCK:
        return (dict(_AUTOMATION.get("latches") or {})).get(name, default)


def _fenix_aircraft_active() -> bool:
    try:
        fstat = fenix_status(force=False)
    except Exception:
        return False
    aircraft = fstat.get("aircraft") if isinstance(fstat.get("aircraft"), dict) else {}
    adapter = aircraft.get("adapter") if isinstance(aircraft.get("adapter"), dict) else {}
    return bool(fstat.get("fenix_detected") or fstat.get("fenix_controlled_loading") or adapter.get("key") == "fenix")


def _close_fenix_cargo_doors_once(latch_name: str, reason: str) -> bool:
    if _get_latch(latch_name):
        return False
    if not _fenix_aircraft_active():
        return False
    results: list[str] = []
    all_ok = True
    for door in ("forward", "aft", "bulk"):
        try:
            result = fenix_set_cargo_door(door, False)
            ok = bool(result.get("ok"))
            all_ok = all_ok and ok
            results.append(f"cargo.{door}={'OK' if ok else result.get('reason') or 'FAILED'}")
        except Exception as exc:
            all_ok = False
            results.append(f"cargo.{door}={type(exc).__name__}")
    if all_ok:
        _set_latch(latch_name, {"time": _utc(), "reason": reason})
    _automation_record("FENIX DOORS", f"Cargo doors {'closed' if all_ok else 'close retry required'} ({reason}): " + "; ".join(results))
    return all_ok


def _progress_text_for_service(snap: dict[str, Any], service: str) -> str:
    row = ((snap.get("services") or {}).get(service) or {})
    parts = [row.get("progress_text"), row.get("status_text"), row.get("waiting_reason"), row.get("state"), row.get("label")]
    return " · ".join(str(x) for x in parts if x is not None and str(x).strip())


def _deboarding_complete_confirmed(snap: dict[str, Any], raw: int | None) -> bool:
    # GSX can retain COMPLETED/BYPASSED from an earlier airport/session. Do not
    # let that stale state skip this arrival's passenger deboarding.
    seen_active = bool(_get_latch("deboarding_seen_active") or _get_latch("deboarding_seen_performing"))
    requested_now = _recent_request_age("deboarding") is not None
    if raw in {3, 6} and seen_active:
        return True
    text = _progress_text_for_service(snap, "deboarding").lower()
    if seen_active and any(token in text for token in ("invoice", "completed", "complete", "finished")):
        return True
    row = ((snap.get("services") or {}).get("deboarding") or {})
    if seen_active and str(row.get("remote_state") or "").lower() in {"completed", "bypassed"}:
        return True
    progress = snap.get("progress") or {}
    try:
        pax = int(progress.get("passengers_deboarding_total") or 0)
        target = int(progress.get("passengers_deboarding_target") or progress.get("passengers_target") or 0)
    except Exception:
        pax = target = 0
    if requested_now and target > 0 and pax >= target:
        return True
    if raw in {4, 5, 7}:
        _set_latch("deboarding_seen_performing", {"time": _utc(), "raw": raw})
        return False
    # Remote API v2 can remove the Deboarding row and leave only the invoice after
    # completion. If OPS ROOM requested/observed the service and it has disappeared
    # for a short settling window, treat that as completion instead of deadlocking.
    age = _recent_request_age("deboarding")
    if _get_latch("deboarding_seen_performing") and raw in {None, 0, 1, 2} and age is not None and age > 20.0:
        return True
    return False


def _arrival_bags_complete(snap: dict[str, Any], deboarding_raw: int | None) -> bool:
    if _deboarding_complete_confirmed(snap, deboarding_raw):
        return True
    progress = snap.get("progress") if isinstance(snap.get("progress"), dict) else snap
    try:
        if float(progress.get("deboarding_cargo_percent") or 0.0) >= 100.0:
            return True
    except Exception:
        pass
    text = _progress_text_for_service(snap, "deboarding")
    if not text and isinstance(snap, dict):
        # Some callers pass the flattened progress snapshot rather than full service status.
        text = str(snap.get("progress_text") or snap.get("status_text") or "")
    return bool(re.search(r"(?:bags?|baggage|cargo)\s*(?::|=)?\s*100\s*%", text, re.I))


def _coordinate_arrival_cargo_doors_closed(snap: dict[str, Any], deboarding_raw: int | None) -> None:
    """Close Fenix cargo doors two minutes after authoritative unload completion.

    The timer is an isolated door action. It cannot change deboarding, cleaning,
    lavatory, GPU, chocks or any service-request sequencing.
    """
    if not _arrival_mode_active() or _get_latch("arrival_cargo_doors_closed_once"):
        return
    complete = _arrival_bags_complete(snap, deboarding_raw)
    due = float(_get_latch("arrival_cargo_doors_close_due_mono") or 0.0)
    if not complete:
        if due:
            _set_latch("arrival_cargo_doors_close_due_mono", 0.0)
            _set_latch("arrival_cargo_doors_close_armed_at", "")
        return
    now_mono = time.monotonic()
    if not due:
        due = now_mono + 120.0
        _set_latch("arrival_cargo_doors_close_due_mono", due)
        _set_latch("arrival_cargo_doors_close_armed_at", _utc())
        _automation_record("FENIX", "Arrival baggage unload complete; cargo doors will close in 2 minutes")
        return
    if now_mono >= due:
        _close_fenix_cargo_doors_once("arrival_cargo_doors_closed_once", "arrival bags/unloading complete + 2 minute handling delay")


def _coordinate_departure_cargo_doors_closed(
    fenix_progress: dict[str, Any] | None = None,
    gsx_progress: dict[str, Any] | None = None,
    boarding_raw: int | None = None,
    snap: dict[str, Any] | None = None,
) -> None:
    if _get_latch("departure_cargo_doors_closed_once"):
        return
    complete = False
    fenix_progress = fenix_progress if isinstance(fenix_progress, dict) else _fenix_progress_safe()
    if fenix_progress.get("ok"):
        try:
            loaded = float(fenix_progress.get("cargo_loaded_kg"))
            target = float(fenix_progress.get("cargo_target_kg"))
            complete = target > 0 and loaded >= target
        except Exception:
            complete = False
    progress = gsx_progress if isinstance(gsx_progress, dict) else {}
    if not complete:
        try:
            complete = float(progress.get("boarding_cargo_percent") or 0.0) >= 100.0
        except Exception:
            complete = False
    if not complete and isinstance(snap, dict):
        complete = bool(re.search(r"(?:bags?|baggage|cargo)\s*(?::|=)?\s*100\s*%", _progress_text_for_service(snap, "boarding"), re.I))
    # A current-session Boarding completion is also authoritative when structured
    # cargo progress is absent. This is not used until the boarding service was
    # actually observed active, preventing stale raw=6 from closing doors early.
    if not complete and boarding_raw == 6 and _get_latch("boarding_seen_active"):
        complete = True
    if complete:
        _close_fenix_cargo_doors_once("departure_cargo_doors_closed_once", "departure bags/loading complete")


def _mark_service_requested(service: str) -> None:
    with _AUTOMATION_LOCK:
        requested = set(_AUTOMATION.get("requested") or [])
        requested.add(service)
        _AUTOMATION["requested"] = sorted(requested)
        requested_at = dict(_AUTOMATION.get("requested_at") or {})
        requested_at.setdefault(service, _utc())
        _AUTOMATION["requested_at"] = requested_at
        _AUTOMATION_REQUESTED_MONO.setdefault(service, time.monotonic())
        latches = dict(_AUTOMATION.get("latches") or {})
        latches[f"{service}_requested_once"] = True
        _AUTOMATION["latches"] = latches


def _mark_service_complete(service: str) -> None:
    _set_latch(f"{service}_complete", True)


def _mark_service_deferred(service: str, reason: str) -> None:
    with _AUTOMATION_LOCK:
        latches = dict(_AUTOMATION.get("latches") or {})
        latches[f"{service}_deferred_or_skipped"] = reason or True
        _AUTOMATION["latches"] = latches
        _AUTOMATION["updated_at"] = _utc()


def _update_completion_latches(raws: dict[str, int | None]) -> None:
    requested = set(_AUTOMATION.get("requested") or [])
    for key, raw in raws.items():
        if raw in {4, 5, 7}:
            _set_latch(f"{key}_seen_active", True)
        if raw in {3, 6} and _get_latch(f"{key}_seen_active"):
            _mark_service_complete(key)


def _service_pending_after_request(service: str, raw: int | None) -> bool:
    age = _recent_request_age(service)
    if service == "water" and _departure_mode_active() and age is not None and not _get_latch("water_seen_active"):
        # GSX commonly leaves Water at COMPLETED/UNAVAILABLE from an older stand
        # session. A successful command is not considered acknowledged until the
        # current session publishes REQUESTED/PERFORMING. Hold the service chain
        # long enough for one isolated safeguard retry instead of silently
        # skipping potable water.
        if age < 35.0:
            return True
    if _arrival_mode_active() and service in {"deboarding", "cleaning", "lavatory"} and age is not None and not _get_latch(f"{service}_seen_active"):
        # A successful current-session request is monotonic. GSX may take time to
        # publish REQUESTED/PERFORMING, and clearing the latch during that delay
        # creates duplicate trucks/invoices. Keep the request pending instead.
        stale_or_idle = raw in {None, 0, 1, 2, 3, 6}
        if stale_or_idle:
            sequence_age = max(0.0, time.monotonic() - float(_AUTOMATION_REQUESTED_MONO.get("arrival_cabin_sequence_started") or time.monotonic()))
            if sequence_age >= 150.0 and service != "deboarding":
                _mark_service_deferred(service, "GSX did not make the service available in this arrival session")
                _automation_record("SERVICE SKIPPED", f"{SERVICE_LABELS.get(service, service.upper())} was not available for this arrival")
                return False
            return True
    if service == "water" and age is not None and age > 90.0 and raw not in {4, 5, 7}:
        # Potable water can be blocked by stand geometry. Do not abandon an active
        # service; only release the chain when GSX never makes it active.
        _mark_service_deferred("water", "blocked or unavailable after 90 seconds")
        return False
    if raw in {4, 5, 7}:
        return True
    if age is None:
        return False
    # If LVars do not update immediately, hold the automation briefly rather than
    # rushing into boarding/pushback. Then continue so a missing optional truck
    # cannot deadlock the flow forever.
    if raw in {None, 0, 1}:
        return age < (120.0 if service in {"refuel", "catering", "boarding", "deboarding"} else 60.0)
    return False


def _needs_request(service: str, raw: int | None) -> bool:
    retry_at = _AUTOMATION_REQUESTED_MONO.get(f"{service}_retry_after")
    if retry_at is not None and time.monotonic() < retry_at:
        return False
    if service in set(_AUTOMATION.get("requested") or []):
        return False
    if _get_latch(f"{service}_requested_once") or _get_latch(f"{service}_complete") or _get_latch(f"{service}_deferred_or_skipped"):
        return False
    if service == "refuel" and (_get_latch("refuel_complete_or_fenix_complete") or _fenix_controlled_session_active()):
        return False
    if _arrival_mode_active() and service in {"deboarding", "cleaning", "lavatory"} and raw in {2, 3, 6}:
        # GSX can carry a completed/unavailable state from an earlier service
        # session. The current arrival session must still issue its own request.
        return True
    if _departure_mode_active() and service == "water" and raw in {2, 3, 6}:
        # A completed/unavailable Water state can be stale from the previous
        # airport. The fresh departure session must issue its own one-shot call.
        return True
    return raw in {None, 0, 1}


def _aircraft_is_parked_for_arrival(position: dict[str, Any] | None = None) -> tuple[bool, str]:
    pos = position if isinstance(position, dict) else read_telemetry(force=False)
    systems = pos.get("systems") if isinstance(pos.get("systems"), dict) else {}
    on_ground = pos.get("on_ground")
    if on_ground is None:
        on_ground = systems.get("on_ground")
    try:
        gs = float(pos.get("ground_speed_kts") or pos.get("ground_speed") or pos.get("gs") or systems.get("ground_speed_kts") or 0.0)
    except Exception:
        gs = 0.0
    parking_brake = bool(pos.get("parking_brake") or systems.get("parking_brake") or systems.get("parking_brake_set"))
    if on_ground is False:
        return False, "aircraft is not on ground"
    if gs > 1.5:
        return False, f"aircraft still moving ({gs:.1f} kt)"
    if not parking_brake and gs > 0.3:
        return False, "aircraft not fully stopped/parked"
    return True, "parked and stopped"


def _detect_turnaround_mode() -> str:
    """Use SimBrief route and current parked state to distinguish arrival.

    Departure is the safe default. Arrival mode is used only when the aircraft is
    on the planned destination airport and is parked/stopped, so descent or taxi-in
    samples cannot trigger an arrival service session early.
    """
    try:
        settings = load_settings()
        user = str(settings.get("identity", {}).get("simbrief_user_id") or "")
        plan = cached_plan(user) if user else None
        destination = str((plan or {}).get("destination", {}).get("icao") or "").upper()
        origin = str((plan or {}).get("origin", {}).get("icao") or "").upper()
        current = _current_airport_position(max_nm=12.0)
        if destination and current.get("ok"):
            nearest_code = str(current.get("icao") or "").upper()
            if current.get("parked") and nearest_code == destination and destination != origin:
                return "ARRIVAL"
    except Exception:
        pass
    return "DEPARTURE"


def _current_airport_position(max_nm: float = 20.0) -> dict[str, Any]:
    try:
        pos = read_telemetry(force=False)
        if not pos.get("ok"):
            return {"ok": False, "reason": "aircraft position unavailable"}
        lat = float(pos["lat"]); lon = float(pos["lon"])
        nearest = nearest_airport(lat, lon)
        ident = nearest[0].ident if nearest and nearest[1] <= max_nm else ""
        parked, parked_reason = _aircraft_is_parked_for_arrival(pos)
        return {
            "ok": bool(ident),
            "icao": ident,
            "lat": lat,
            "lon": lon,
            "heading": pos.get("heading"),
            "nearest_nm": nearest[1] if nearest else None,
            "position": pos,
            "parked": parked,
            "parked_reason": parked_reason,
        }
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}


def _detect_arrival_stand() -> dict[str, Any]:
    current = _current_airport_position(max_nm=12.0)
    if not current.get("ok"):
        return {"ok": False, "message": current.get("reason") or "current airport unavailable"}
    if not current.get("parked"):
        return {"ok": False, "current_airport": current.get("icao"), "message": f"stand detection waiting: {current.get('parked_reason') or 'aircraft is not parked'}"}
    try:
        from . import aviation_data
        detected = aviation_data.nearest_parking(
            str(current.get("icao") or ""),
            float(current.get("lat")),
            float(current.get("lon")),
            heading=current.get("heading"),
            max_m=85.0,
        )
        detected["current_airport"] = current.get("icao")
        return detected
    except Exception as exc:
        return {"ok": False, "current_airport": current.get("icao"), "message": f"stand detection unavailable: {type(exc).__name__}: {exc}"}


def _arrival_mode_active() -> bool:
    with _AUTOMATION_LOCK:
        return str(_AUTOMATION.get("mode") or "").upper() in {"ARRIVAL", "FULL_TURNAROUND"}


def _looks_like_gate_selection(title: str, options: list[str]) -> bool:
    title_n = _normalized(title)
    if any(word in title_n for word in ("parking", "gate", "stand", "select destination", "choose destination")):
        return True
    if len(options) >= 3:
        hits = 0
        for option in options:
            opt = _normalized(str(option))
            if re.search(r"\b(gate|stand|parking|ramp)\b", opt) or re.search(r"\b[a-z] ?\d{1,3}[a-z]?\b", opt):
                hits += 1
        return hits >= max(2, min(5, len(options) // 3))
    return False


def _stand_aliases(stand: dict[str, Any]) -> list[str]:
    label = str(stand.get("label") or "").strip()
    name = str(stand.get("name") or "").strip()
    number = str(stand.get("number") or "").strip()
    suffix = str(stand.get("suffix") or "").strip()
    values = {label}
    compact = f"{name}{number}{suffix}".strip()
    spaced = f"{name} {number}{suffix}".strip()
    for v in (compact, spaced, f"Gate {spaced}".strip(), f"Stand {spaced}".strip(), f"Parking {spaced}".strip()):
        if v:
            values.add(v)
    return [v for v in values if v]


def _detected_stand_menu_index(title: str, options: list[str]) -> int | None:
    if not _arrival_mode_active() or not _looks_like_gate_selection(title, options):
        return None
    with _AUTOMATION_LOCK:
        cached = dict(_AUTOMATION.get("arrival_stand") or {})
    if not cached.get("ok"):
        cached = _detect_arrival_stand()
        with _AUTOMATION_LOCK:
            _AUTOMATION["arrival_stand"] = cached
    if not cached.get("ok") or cached.get("ambiguous") or str(cached.get("confidence") or "") == "low":
        return None
    stand = cached.get("stand") or {}
    aliases = [_normalized(a) for a in _stand_aliases(stand)]
    if not aliases:
        return None
    options_n = [_normalized(o) for o in options]
    matches = []
    for i, opt in enumerate(options_n):
        for alias in aliases:
            if alias and (alias == opt or f" {alias} " in f" {opt} " or alias.replace(" ", "") in opt.replace(" ", "")):
                matches.append(i)
                break
    if len(set(matches)) == 1:
        idx = matches[0]
        _automation_record("ARRIVAL GATE", f"Detected {stand.get('label') or 'stand'} and matched live GSX menu option: {options[idx]}")
        return idx
    return None

def _arrival_gate_flow_status() -> dict[str, Any]:
    """Expose how arrival gate/stand selection will be resolved.

    Users can pre-select/confirm in the live GSX menu. If not, OPS ROOM detects
    the nearest stand after parking and never reuses the departure gate/session.
    """
    with _AUTOMATION_LOCK:
        mode = str(_AUTOMATION.get("mode") or "").upper()
        cached = dict(_AUTOMATION.get("arrival_stand") or {})
    if mode not in {"ARRIVAL", "FULL_TURNAROUND"}:
        return {"mode": mode or "DEPARTURE", "active": False, "message": "Arrival gate selection is armed only for Arrival or Full Turnaround."}
    if cached.get("ok"):
        stand = cached.get("stand") or {}
        return {"mode": mode, "active": True, "selection_source": "detected_current_stand", "current_airport": cached.get("current_airport"), "stand": stand, "confidence": cached.get("confidence"), "message": f"Detected arrival stand {stand.get('label') or stand.get('name') or 'unknown'}; confirm/match in GSX before arrival services."}
    return {"mode": mode, "active": True, "selection_source": "pending", "message": "Select/confirm the destination gate in GSX, or park at stand for OPS ROOM current-stand detection. Departure gate state is not reused."}


def _fenix_loading_available() -> bool:
    try:
        fstat = fenix_status(force=False)
        # v0.24.14: recent Fenix sync is not allowed to be the guard that
        # blocks generic GSX refuelling. If the Fenix EFB is online and the
        # aircraft family hints A319/A320/A321/A20N/A21N/FNX, treat departure
        # loading as Fenix-controlled and keep generic GSX refuel out of the
        # service plan. Sync/start errors are handled later and do not fall back
        # to generic fuel for Fenix.
        family_hint = bool(fstat.get("fenix_family_hint"))
        return bool(
            fstat.get("efb_online")
            and (fstat.get("fenix_detected") or fstat.get("fenix_controlled_loading") or family_hint)
        )
    except Exception:
        return False




def _fenix_aircraft_likely_now() -> bool:
    """Detect a Fenix aircraft without requiring the EFB probe to be online.

    This prevents the generic GSX departure plan from requesting standalone
    refuel during the first automation cycle while the Fenix EFB/status probe is
    still warming up. It is stricter than a plain A320 family hint: the title or
    adapter must actually identify Fenix/FNX.
    """
    try:
        fstat = fenix_status(force=False)
        if fstat.get("fenix_detected") or fstat.get("fenix_controlled_loading"):
            return True
        aircraft_info = fstat.get("aircraft") if isinstance(fstat.get("aircraft"), dict) else {}
        aircraft = aircraft_info.get("aircraft") if isinstance(aircraft_info.get("aircraft"), dict) else {}
        adapter = aircraft_info.get("adapter") if isinstance(aircraft_info.get("adapter"), dict) else {}
        haystack = " ".join(str(v or "") for v in (
            aircraft.get("title"), aircraft.get("model"), aircraft.get("type"),
            adapter.get("key"), adapter.get("name"),
        )).upper()
        return "FENIX" in haystack or "FNX" in haystack
    except Exception:
        return False

def _fenix_signature_safe() -> str:
    try:
        return str(fenix_loading_signature() or "fenix-current-flight")
    except Exception:
        return "fenix-current-flight"


def _fenix_loading_requested() -> bool:
    """True once Fenix EFB loading has been started for the current flight.

    This remains the v0.18.17 one-shot guard, but now understands the v0.20.0
    phase-machine states. A zero passenger/cargo counter must not POST
    startGsxBoarding again.
    """
    current_sig = _fenix_signature_safe()
    active_states = {
        "starting", "started", "monitoring", "complete",
        "FENIX_LOADING_STARTED", "WAITING_REFUEL_CATERING", "READY_FOR_BOARDING",
        "BOARDING_REQUESTED", "MONITORING_BOARDING", "COMPLETE",
    }
    with _AUTOMATION_LOCK:
        state = str(_FENIX_LOADING_STATE.get("state") or _FENIX_LOADING_STATE.get("phase") or "FENIX_LOADING_IDLE")
        phase = str(_FENIX_LOADING_STATE.get("phase") or state)
        signature = str(_FENIX_LOADING_STATE.get("signature") or "")
        if (state in active_states or phase in active_states) and (not signature or signature == current_sig):
            return True
    started = float(_AUTOMATION_REQUESTED_MONO.get("fenix_loading") or 0.0)
    return bool(started and time.monotonic() - started < 14400.0)


def _fenix_loading_age_s() -> float:
    started = float(_AUTOMATION_REQUESTED_MONO.get("fenix_loading") or 0.0)
    if started:
        return max(0.0, time.monotonic() - started)
    with _AUTOMATION_LOCK:
        started = float(_FENIX_LOADING_STATE.get("started_mono") or 0.0)
    return max(0.0, time.monotonic() - started) if started else 0.0


def _reset_fenix_loading_session() -> None:
    _FENIX_GSX_MACHINE.reset()
    with _AUTOMATION_LOCK:
        _FENIX_LOADING_STATE.update({
            "state": "FENIX_LOADING_IDLE",
            "phase": "FENIX_LOADING_IDLE",
            "signature": None,
            "started_at": None,
            "started_mono": 0.0,
            "targets": {},
            "last_progress": {},
            "last_decision": {},
            "last_gsx_action": {},
            "failure_reason": "",
            "boarding_action_sent": False,
            "menu_open_requested_mono": 0.0,
        })
    _AUTOMATION_REQUESTED_MONO.pop("fenix_loading", None)
    _AUTOMATION_REQUESTED_MONO.pop("fenix_boarding_menu", None)


def _fenix_menu_entries(menu: dict[str, Any]) -> list[GsxMenuEntry]:
    entries: list[GsxMenuEntry] = []
    for index, option in enumerate(menu.get("options") or []):
        if isinstance(option, dict):
            label = str(option.get("label") or option.get("text") or option.get("title") or option)
            raw_index = option.get("index", index)
            disabled = bool(option.get("disabled") or option.get("is_disabled"))
        else:
            label = str(option)
            raw_index = index
            disabled = False
        try:
            entry_index = int(raw_index)
        except (TypeError, ValueError):
            entry_index = index
        entries.append(GsxMenuEntry(index=entry_index, label=label.strip(), disabled=disabled))
    return entries


def _service_complete_or_inactive(raw: int | None) -> bool | None:
    if raw is None:
        return None
    if raw in {2, 3, 6}:
        return True
    if raw in {4, 5, 7}:
        return False
    return None


def _fenix_progress_safe() -> dict[str, Any]:
    try:
        return fenix_loading_progress()
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}


def _official_handler_set_aircraft_refueling_false_once() -> None:
    """Best-effort GSX 4.0.9 handler.set guard for study-level Fenix fuel.

    This is deliberately non-fatal. If the remote API does not expose handlerSet
    or rejects the write, OPS ROOM keeps the older proven Fenix EFB loading path
    and still blocks generic GSX refuel in the service plan.
    """
    now = time.monotonic()
    last = float(_AUTOMATION_REQUESTED_MONO.get("fenix_handler_refueling_false") or 0.0)
    if last and now - last < 900.0:
        return
    try:
        probe = _official_ws_exchange(timeout=0.55)
        hello = probe.get("hello") or {}
        caps_raw = hello.get("capabilities") or hello.get("caps") or hello.get("features") or []
        caps_text = " ".join(str(x) for x in caps_raw) if isinstance(caps_raw, (list, tuple, set)) else str(caps_raw)
        if "handlerset" not in caps_text.replace("_", "").lower():
            return
        result = _official_command("handler.set", {"target": "aircraft", "name": "refueling", "value": False}, timeout=0.90)
        _AUTOMATION_REQUESTED_MONO["fenix_handler_refueling_false"] = now
        if result.get("ok"):
            official = result.get("official_remote") if isinstance(result.get("official_remote"), dict) else _official_status(force=True)
            handler_data = official.get("handlerData") if isinstance(official.get("handlerData"), dict) else {}
            aircraft = handler_data.get("aircraft") if isinstance(handler_data.get("aircraft"), dict) else {}
            if aircraft.get("refueling") is False:
                _set_latch("refuel_handled_by_fenix", True)
                _automation_record("FENIX", "GSX handler aircraft.refueling=false confirmed from handlerData echo")
            else:
                _automation_record("FENIX", "GSX handler aircraft.refueling=false accepted; waiting for handlerData echo")
        else:
            _automation_record("FENIX", f"GSX handler aircraft.refueling=false skipped: {result.get('reason') or result.get('code') or 'not accepted'}")
    except Exception as exc:
        _automation_record("FENIX", f"GSX handler aircraft.refueling=false unavailable: {type(exc).__name__}: {exc}")


def _remote_service_row(snap: dict[str, Any], service: str) -> dict[str, Any] | None:
    services = snap.get("services") if isinstance(snap.get("services"), dict) else {}
    row = services.get(service) if isinstance(services, dict) else None
    return row if isinstance(row, dict) else None


def _remote_service_raw_state(row: dict[str, Any] | None) -> tuple[int | None, str]:
    if not isinstance(row, dict):
        return None, ""
    raw = row.get("raw")
    try:
        raw = int(raw) if raw is not None else None
    except Exception:
        raw = None
    state = str(row.get("remote_state") or row.get("state") or "").strip().lower()
    return raw, state


def _boarding_service_active_from_snapshot(snap: dict[str, Any]) -> bool:
    row = _remote_service_row(snap, "boarding")
    raw, state = _remote_service_raw_state(row)
    return bool(raw in {4, 5, 7} or state in {"requested", "performing", "completing"})


def _boarding_service_available_from_snapshot(snap: dict[str, Any]) -> bool:
    row = _remote_service_row(snap, "boarding")
    raw, state = _remote_service_raw_state(row)
    if not isinstance(row, dict):
        return False
    return bool(row.get("can_trigger") or raw == 1 or state == "available")


def _fenix_authoritative_complete(progress: dict[str, Any] | None = None, fenix_progress: dict[str, Any] | None = None) -> bool:
    """Conservative Fenix completion gate.

    Fenix EFB owns the aircraft-loaded state. GSX passenger counts are useful for
    display, but they must not impersonate live Fenix EFB boarded passengers. When
    Fenix does not expose a readable live passenger counter, allow completion only
    after fuel/cargo are at target, GSX boarding is complete, and the Fenix task has
    had a short settle window after startGsxBoarding. This restores the old working
    timing without allowing an immediate false pushback handoff.
    """
    progress = progress or {}
    fenix_progress = fenix_progress if isinstance(fenix_progress, dict) else _fenix_progress_safe()

    def _num(value: Any) -> float | None:
        try:
            n = float(value)
            return n if n == n else None
        except Exception:
            return None

    age = _fenix_loading_age_s()

    gsx_pax_loaded = _num(progress.get("passengers_boarding_total"))
    gsx_pax_target = _num(progress.get("passengers_target"))
    gsx_pax_complete = bool(gsx_pax_target is not None and gsx_pax_target > 0 and gsx_pax_loaded is not None and gsx_pax_loaded >= gsx_pax_target)

    fenix_pax_loaded = _num(fenix_progress.get("pax_loaded"))
    fenix_pax_target = _num(fenix_progress.get("pax_target"))
    if fenix_pax_target is None or fenix_pax_target <= 0:
        fenix_pax_target = gsx_pax_target
    fenix_pax_complete = bool(fenix_pax_target is not None and fenix_pax_target > 0 and fenix_pax_loaded is not None and fenix_pax_loaded >= fenix_pax_target)
    # If the Fenix loadsheet does not expose live pax, fall back to GSX only after
    # a settle window. If it explicitly exposes a lower value, hold.
    if fenix_pax_loaded is None:
        pax_complete = bool(gsx_pax_complete and age >= 35.0)
    else:
        pax_complete = fenix_pax_complete

    fuel_loaded = _num(fenix_progress.get("fuel_loaded_kg"))
    fuel_target = _num(fenix_progress.get("fuel_target_kg"))
    if fuel_target is not None and fuel_target > 0:
        fuel_complete = bool(fuel_loaded is not None and fuel_loaded >= (fuel_target - max(25.0, fuel_target * 0.01)))
    else:
        fuel_complete = fenix_progress.get("fuel_target_reached") is True

    cargo_loaded = _num(fenix_progress.get("cargo_loaded_kg"))
    cargo_target = _num(fenix_progress.get("cargo_target_kg"))
    cargo_pct = _num(progress.get("boarding_cargo_percent"))
    if cargo_target is not None and cargo_target > 0:
        cargo_complete = bool(cargo_loaded is not None and cargo_loaded >= (cargo_target - max(25.0, cargo_target * 0.01)))
    elif cargo_pct is not None and cargo_pct > 0:
        cargo_complete = cargo_pct >= 98.0
    else:
        cargo_complete = True

    # "Aircraft loaded" must never bypass passenger boarding. Fenix/GSX can
    # report cargo/fuel settled while GSX still shows pax 24/156. Treat that as
    # cargo completion only and keep the cabin/boarding sequence active.
    if fenix_progress.get("aircraft_loaded") is True and pax_complete and fuel_complete and cargo_complete and age >= 10.0:
        return True
    complete = bool(pax_complete and fuel_complete and cargo_complete and age >= 20.0)
    # Final handoff only: if Fenix/GSX loading has clearly reached all visible
    # targets but the phase machine keeps reporting MONITORING_BOARDING, accept
    # the loaded state and move to pushback. This does not change the working
    # v0.24.21 start/refuel/loading order.
    if not complete and age >= 20.0 and gsx_pax_complete:
        cargo_by_gsx = cargo_pct is not None and cargo_pct >= 98.0
        if cargo_by_gsx:
            cargo_complete = True
        if fuel_target is not None and fuel_target > 0 and fuel_loaded is not None:
            fuel_complete = bool(fuel_loaded >= (fuel_target - max(50.0, fuel_target * 0.015)))
        if pax_complete and cargo_complete and fuel_complete:
            _automation_record(
                "FENIX_EFB_TARGETS_COMPLETE",
                f"pax={int(gsx_pax_loaded or fenix_pax_loaded or 0)}/{int(gsx_pax_target or fenix_pax_target or 0)} "
                f"cargo={int(cargo_loaded or 0)}/{int(cargo_target or 0)} fuel={int(fuel_loaded or 0)}/{int(fuel_target or 0)}",
            )
            complete = True
    if not complete and gsx_pax_complete and fenix_pax_loaded not in (None, 0):
        _automation_record("FENIX", f"Holding pushback: Fenix EFB pax {int(fenix_pax_loaded)}/{int(fenix_pax_target or 0)} while GSX reports complete")
    elif not complete and gsx_pax_complete and fenix_pax_loaded == 0:
        _automation_record("FENIX", "Holding pushback: GSX boarding complete but Fenix EFB still reports 0 boarded")
    return complete

def _compose_fenix_status_text(
    *,
    boarding_raw: int | None,
    refuel_raw: int | None,
    catering_raw: int | None,
    progress: dict[str, Any],
    fenix_progress: dict[str, Any],
    menu: dict[str, Any],
    boarding_service_active: bool = False,
    boarding_service_available: bool = False,
) -> str:
    parts = [
        f"boarding={STATE_LABELS.get(boarding_raw, boarding_raw)}",
        f"refuel={STATE_LABELS.get(refuel_raw, refuel_raw)}",
        f"catering={STATE_LABELS.get(catering_raw, catering_raw)}",
        f"pax={int(progress.get('passengers_boarding_total') or 0)}/{int(progress.get('passengers_target') or 0)}",
        f"cargo={int(progress.get('boarding_cargo_percent') or 0)}%",
    ]
    if fenix_progress.get("ok"):
        fuel_loaded = fenix_progress.get("fuel_loaded_kg")
        fuel_target = fenix_progress.get("fuel_target_kg")
        if fuel_loaded is not None or fuel_target is not None:
            parts.append(f"fenix_fuel={fuel_loaded if fuel_loaded is not None else '---'}/{fuel_target if fuel_target is not None else '---'}kg")
        if fenix_progress.get("fuel_target_reached") is True:
            parts.append("fuel target reached")
    if boarding_service_active:
        parts.append("BOARDING_SERVICE_ACTIVE")
    elif boarding_service_available:
        parts.append("BOARDING_SERVICE_AVAILABLE")
    if menu.get("available"):
        parts.append("menu=" + str(menu.get("title") or "GSX MENU"))
    return " · ".join(parts)


def _sync_fenix_loading_state(decision: Any, *, progress: dict[str, Any], boarding_raw: int | None, fenix_progress: dict[str, Any]) -> None:
    diag = dict(getattr(decision, "diagnostic", {}) or {})
    phase = str(getattr(getattr(decision, "phase", None), "value", None) or getattr(decision, "phase", "FENIX_LOADING_IDLE"))
    pax = int(progress.get("passengers_boarding_total") or 0)
    target = int(progress.get("passengers_target") or 0)
    with _AUTOMATION_LOCK:
        _FENIX_LOADING_STATE["phase"] = phase
        _FENIX_LOADING_STATE["state"] = phase
        _FENIX_LOADING_STATE["boarding_action_sent"] = bool(diag.get("boarding_action_sent"))
        _FENIX_LOADING_STATE["failure_reason"] = str(diag.get("failure_reason") or "")
        _FENIX_LOADING_STATE["last_progress"] = {
            "passengers": pax,
            "target": target,
            "boarding_raw": boarding_raw,
            "boarding_cargo_percent": int(progress.get("boarding_cargo_percent") or 0),
            "fenix": fenix_progress,
            "updated_at": _utc(),
        }
        _FENIX_LOADING_STATE["last_decision"] = {
            "phase": phase,
            "action": getattr(decision, "action", "none"),
            "menu_index": getattr(decision, "menu_index", None),
            "reason": getattr(decision, "reason", ""),
            "diagnostic": diag,
            "updated_at": _utc(),
        }


def _maybe_open_fenix_boarding_menu() -> dict[str, Any] | None:
    now = time.monotonic()
    with _AUTOMATION_LOCK:
        last = float(_FENIX_LOADING_STATE.get("menu_open_requested_mono") or 0.0)
        if last and now - last < 18.0:
            return None
        _FENIX_LOADING_STATE["menu_open_requested_mono"] = now
    try:
        opened = open_menu()
        if opened.get("ok"):
            _automation_record("FENIX", "GSX menu opened for Fenix boarding handoff")
        return opened.get("menu") if isinstance(opened.get("menu"), dict) else None
    except Exception as exc:
        _automation_record("FENIX", f"Waiting for GSX boarding menu: {type(exc).__name__}: {exc}")
        return None


def _apply_fenix_boarding_decision(decision: Any) -> None:
    action = getattr(decision, "action", "none")
    if action == "gsx_service_trigger":
        try:
            result = _trigger_service_remote_v2("boarding", automate=True)
            _AUTOMATION_REQUESTED_MONO["fenix_boarding_remote"] = time.monotonic()
            _AUTOMATION_REQUESTED_MONO["boarding"] = time.monotonic()
            with _AUTOMATION_LOCK:
                requested = set(_AUTOMATION.get("requested") or [])
                requested.add("FENIX_GSX_BOARDING_REMOTE")
                requested.add("boarding")
                _AUTOMATION["requested"] = sorted(requested)
                requested_at = dict(_AUTOMATION.get("requested_at") or {})
                requested_at["FENIX_GSX_BOARDING_REMOTE"] = _utc()
                requested_at["boarding"] = _utc()
                _AUTOMATION["requested_at"] = requested_at
                _FENIX_LOADING_STATE["boarding_action_sent"] = True
                _FENIX_LOADING_STATE["last_gsx_action"] = {"time": _utc(), "action": "gsx_service_trigger", "result": result}
            if result.get("ok"):
                _automation_record("FENIX", "GSX Boarding triggered once through Remote API v2")
            else:
                _automation_record("FENIX", f"GSX Boarding Remote API trigger failed; monitoring: {result.get('reason') or result.get('code') or 'not accepted'}")
        except Exception as exc:
            with _AUTOMATION_LOCK:
                _FENIX_LOADING_STATE["last_gsx_action"] = {"time": _utc(), "action": "gsx_service_trigger", "reason": f"{type(exc).__name__}: {exc}"}
            _automation_record("FENIX", f"GSX Boarding Remote API trigger unavailable: {type(exc).__name__}: {exc}")
        return
    if action != "gsx_menu_pick":
        return
    # Never trust a cached menu index. GSX menus change quickly while Fenix EFB
    # loading is active. Re-read the current menu and select by label. If the
    # option is gone, keep monitoring Fenix loading instead of failing or falling
    # back into a second normal GSX boarding/refuel request.
    menu = _active_menu(prefer_official=True)
    index, menu = _find_service_through_pages("boarding", menu, max_pages=2)
    if index is None:
        with _AUTOMATION_LOCK:
            _FENIX_LOADING_STATE["last_gsx_action"] = {"time": _utc(), "action": "monitor", "reason": "boarding option not currently visible"}
        _automation_record("FENIX", "Fenix loading active; GSX boarding option not visible, monitoring only")
        return
    try:
        opts = list((menu or {}).get("options") or [])
        expected_label = str(opts[index]) if index is not None and index < len(opts) else "boarding"
        selected = select_menu_by_label(expected_label, ALIASES["boarding"])
        if selected.get("ok"):
            selected = _resolve_followups(selected, "boarding")
        _AUTOMATION_REQUESTED_MONO["fenix_boarding_menu"] = time.monotonic()
        _AUTOMATION_REQUESTED_MONO["boarding"] = time.monotonic()
        with _AUTOMATION_LOCK:
            requested = set(_AUTOMATION.get("requested") or [])
            requested.add("FENIX_GSX_BOARDING_MENU")
            requested.add("boarding")
            _AUTOMATION["requested"] = sorted(requested)
            requested_at = dict(_AUTOMATION.get("requested_at") or {})
            requested_at["FENIX_GSX_BOARDING_MENU"] = _utc()
            requested_at["boarding"] = _utc()
            _AUTOMATION["requested_at"] = requested_at
            _FENIX_LOADING_STATE["boarding_action_sent"] = True
            _FENIX_LOADING_STATE["last_gsx_action"] = {"time": _utc(), "action": "gsx_menu_pick", "menu_index": index, "result": selected}
        _automation_record("FENIX", "GSX boarding handoff requested once through the current live menu")
    except Exception as exc:
        with _AUTOMATION_LOCK:
            _FENIX_LOADING_STATE["last_gsx_action"] = {"time": _utc(), "action": "monitor", "reason": f"{type(exc).__name__}: {exc}"}
        _automation_record("FENIX", f"Fenix loading active; GSX boarding handoff skipped, monitoring only: {type(exc).__name__}: {exc}")



def _boarding_service_complete_from_snapshot(snap: dict[str, Any]) -> bool:
    services = snap.get("services") if isinstance(snap.get("services"), dict) else {}
    row = services.get("boarding") if isinstance(services, dict) else None
    progress = snap.get("progress") if isinstance(snap.get("progress"), dict) else {}

    def _number(value: Any) -> float | None:
        try:
            number = float(value)
            return number if number == number else None
        except Exception:
            return None

    current = _number(progress.get("passengers_boarding_total"))
    total = _number(progress.get("passengers_target"))
    raw = None
    state = ""
    text = ""
    if isinstance(row, dict):
        try:
            raw = int(row.get("raw")) if row.get("raw") is not None else None
        except Exception:
            raw = None
        state = str(row.get("remote_state") or row.get("state") or "").strip().lower()
        row_progress = row.get("progress") if isinstance(row.get("progress"), dict) else {}
        if current is None:
            current = _number(row_progress.get("current", row_progress.get("done")))
        if total is None or total <= 0:
            total = _number(row_progress.get("total", row_progress.get("target")))
        text = " ".join(str(row.get(k) or "") for k in ("progress_text", "status_text", "waiting_reason", "label"))
        match = re.search(r"(?:pax|passengers?)\s*(?::|=)?\s*(\d+)\s*/\s*(\d+)", text, re.I)
        if match:
            current = float(match.group(1))
            total = float(match.group(2))

    # This is the hard passenger-authority rule. An explicit 43/152 always means
    # boarding is incomplete even if bags are 100%, a legacy LVar is stale at 6,
    # or Departure is requested and waiting for Boarding.
    if total is not None and total > 0 and current is not None:
        if current < total:
            return False
        if current >= total:
            return True

    if isinstance(row, dict):
        if raw == 6 or state in {"completed", "bypassed"}:
            return True
        if re.search(r"\b(boarding|passenger\s+boarding)\s+(complete|completed)\b|ready\s+for\s+pushback", text, re.I):
            return True
    return False

def _update_fenix_phase_machine(
    *,
    snap: dict[str, Any],
    boarding_raw: int | None,
    refuel_raw: int | None,
    catering_raw: int | None,
    settings: dict[str, Any],
    fenix_progress: dict[str, Any] | None = None,
) -> Any:
    progress = snap.get("progress") or {}
    menu = snap.get("menu") if isinstance(snap.get("menu"), dict) else {}
    gsx_boarding_complete = _boarding_service_complete_from_snapshot(snap)
    remote_boarding_active = _boarding_service_active_from_snapshot(snap)
    remote_boarding_available = _boarding_service_available_from_snapshot(snap)
    fenix_progress = fenix_progress if isinstance(fenix_progress, dict) else _fenix_progress_safe()
    age = _fenix_loading_age_s()
    fuel_target_reached = fenix_progress.get("fuel_target_reached") if fenix_progress.get("ok") else None
    if fenix_progress.get("ok") and fuel_target_reached is not True:
        try:
            fuel_loaded_kg = float(fenix_progress.get("fuel_loaded_kg"))
            fuel_target_kg = float(fenix_progress.get("fuel_target_kg"))
            if fuel_target_kg > 0 and fuel_loaded_kg >= fuel_target_kg - max(25.0, fuel_target_kg * 0.01):
                fuel_target_reached = True
        except Exception:
            pass
    refuel_complete = True if fuel_target_reached is True else _service_complete_or_inactive(refuel_raw)
    # When Fenix owns refuelling, the GSX refuel LVar can remain idle. Do not
    # deadlock on an idle refuel LVar forever; the actual handoff still waits for
    # a visible boarding option before taking action.
    if refuel_complete is None and age > 90.0:
        refuel_complete = True
    catering_complete = True if not settings.get("gsx_departure_catering", True) else _service_complete_or_inactive(catering_raw)
    if catering_complete is None and not _service_pending_after_request("catering", catering_raw):
        catering_complete = True

    # Do not feed GSX pax counters into the Fenix phase machine as if they were
    # live Fenix EFB boarded counts. GSX progress is logged separately; the Fenix
    # phase machine only receives Fenix-readable passenger progress.
    pax_loaded_raw = fenix_progress.get("pax_loaded") if fenix_progress.get("ok") else None
    pax_target_raw = fenix_progress.get("pax_target") if fenix_progress.get("ok") else None
    if pax_target_raw in (None, 0):
        pax_target_raw = progress.get("passengers_target")
    if gsx_boarding_complete and pax_loaded_raw in (None, ""):
        pax_loaded_raw = progress.get("passengers_boarding_total") or progress.get("passengers_target")
    pax_loaded = None if pax_loaded_raw in (None, "") else int(float(pax_loaded_raw))
    pax_target = None if pax_target_raw in (None, "", 0) else int(float(pax_target_raw))
    if gsx_boarding_complete and pax_target and (pax_loaded is None or pax_loaded < pax_target):
        pax_loaded = pax_target
    cargo_loaded = fenix_progress.get("cargo_loaded_kg") if fenix_progress.get("ok") else None
    cargo_target = fenix_progress.get("cargo_target_kg") if fenix_progress.get("ok") else None
    if cargo_loaded is None:
        cargo_pct = float(progress.get("boarding_cargo_percent") or 0)
        if cargo_pct > 0:
            cargo_loaded = cargo_pct
            cargo_target = 100.0
    if gsx_boarding_complete and (cargo_target in (None, 0) or cargo_loaded in (None, "")):
        cargo_loaded = 100.0
        cargo_target = 100.0

    snapshot = FenixGsxLoadingSnapshot(
        aircraft_family="fenix",
        loading_active=True,
        fenix_loading_started=_fenix_loading_requested(),
        fuel_target_reached=fuel_target_reached,
        refuel_complete=refuel_complete,
        catering_complete=catering_complete,
        pax_loaded=pax_loaded,
        pax_target=pax_target,
        cargo_loaded=cargo_loaded,
        cargo_target=cargo_target,
        boarding_service_active=remote_boarding_active,
        boarding_service_available=remote_boarding_available,
        gsx_status_text=_compose_fenix_status_text(
            boarding_raw=boarding_raw,
            refuel_raw=refuel_raw,
            catering_raw=catering_raw,
            progress=progress,
            fenix_progress=fenix_progress,
            menu=menu,
            boarding_service_active=remote_boarding_active,
            boarding_service_available=remote_boarding_available,
        ),
        gsx_menu_entries=tuple(_fenix_menu_entries(menu)),
    )
    decision = _FENIX_GSX_MACHINE.update(snapshot)

    phase_value = str(getattr(getattr(decision, "phase", None), "value", None) or getattr(decision, "phase", ""))
    # Opening the GSX Remote menu also opens the in-sim GSX menu in MSFS.
    # v0.20.0 keeps this fallback optional and disabled by default for Fenix, because
    # the HAR-confirmed Fenix EFB path should start normal GSX boarding without menu popups.
    if (
        phase_value == "READY_FOR_BOARDING"
        and getattr(decision, "action", "none") == "none"
        and bool(settings.get("gsx_fenix_open_menu_handoff", False))
    ):
        opened_menu = _maybe_open_fenix_boarding_menu()
        if opened_menu and opened_menu.get("options"):
            snapshot = FenixGsxLoadingSnapshot(
                aircraft_family=snapshot.aircraft_family,
                loading_active=snapshot.loading_active,
                fenix_loading_started=snapshot.fenix_loading_started,
                fuel_target_reached=snapshot.fuel_target_reached,
                refuel_complete=snapshot.refuel_complete,
                catering_complete=snapshot.catering_complete,
                pax_loaded=snapshot.pax_loaded,
                pax_target=snapshot.pax_target,
                cargo_loaded=snapshot.cargo_loaded,
                cargo_target=snapshot.cargo_target,
                boarding_service_active=snapshot.boarding_service_active,
                boarding_service_available=snapshot.boarding_service_available,
                gsx_status_text=snapshot.gsx_status_text,
                gsx_menu_entries=tuple(_fenix_menu_entries(opened_menu)),
            )
            decision = _FENIX_GSX_MACHINE.update(snapshot)

    _sync_fenix_loading_state(decision, progress=progress, boarding_raw=boarding_raw, fenix_progress=fenix_progress)
    _apply_fenix_boarding_decision(decision)
    return decision


def _request_fenix_loading_once() -> dict[str, Any]:
    current_sig = _fenix_signature_safe()
    active_states = {
        "starting", "started", "monitoring", "complete",
        "FENIX_LOADING_STARTED", "WAITING_REFUEL_CATERING", "READY_FOR_BOARDING",
        "BOARDING_REQUESTED", "MONITORING_BOARDING", "COMPLETE",
    }
    with _AUTOMATION_LOCK:
        state = str(_FENIX_LOADING_STATE.get("state") or "FENIX_LOADING_IDLE")
        signature = str(_FENIX_LOADING_STATE.get("signature") or "")
        if state in active_states and (not signature or signature == current_sig):
            return {
                "ok": True,
                "already_requested": True,
                "mode": "fenix_efb_gsx_loading",
                "signature": signature or current_sig,
                "state": state,
                "targets": dict(_FENIX_LOADING_STATE.get("targets") or {}),
            }
        _FENIX_GSX_MACHINE.reset()
        _FENIX_LOADING_STATE.update({
            "state": "FENIX_LOADING_STARTED",
            "phase": "FENIX_LOADING_STARTED",
            "signature": current_sig,
            "started_at": _utc(),
            "started_mono": time.monotonic(),
            "targets": {},
            "last_progress": {},
            "last_decision": {},
            "last_gsx_action": {},
            "failure_reason": "",
            "boarding_action_sent": False,
            "menu_open_requested_mono": 0.0,
        })
    try:
        # Legacy GSX builds do not expose the official Remote API and can keep an
        # estimated passenger target even though the Fenix EFB has the SimBrief
        # target. Reconcile only the documented writable GSX passenger LVar before
        # starting the unchanged Fenix EFB GSX task. Modern Remote API builds are
        # explicitly skipped by the helper.
        planned_targets = fenix_loading_targets()
        legacy_pax = _legacy_gsx_passenger_target(planned_targets.get("pax_count"), force=True)
        # Keep the old proven Fenix EFB loading sequence clean.  The optional GSX
        # handler.set(refueling=false) guard is intentionally not sent here because
        # user testing showed the Fenix EFB task itself must own boarding/refuel state.
        result = fenix_start_gsx_boarding()
        result["legacy_passenger_target"] = legacy_pax
    except Exception:
        with _AUTOMATION_LOCK:
            if str(_FENIX_LOADING_STATE.get("signature") or "") == current_sig:
                _FENIX_LOADING_STATE["state"] = "FAILED"
                _FENIX_LOADING_STATE["phase"] = "FAILED"
        raise
    _AUTOMATION_REQUESTED_MONO["fenix_loading"] = time.monotonic()
    with _AUTOMATION_LOCK:
        _FENIX_LOADING_STATE.update({
            "state": "FENIX_LOADING_STARTED",
            "phase": "FENIX_LOADING_STARTED",
            "signature": current_sig,
            "targets": dict(result.get("targets") or {}),
            "started_at": _FENIX_LOADING_STATE.get("started_at") or _utc(),
            "started_mono": _FENIX_LOADING_STATE.get("started_mono") or time.monotonic(),
        })
        requested = set(_AUTOMATION.get("requested") or [])
        requested.add("FENIX_LOADING")
        _AUTOMATION["requested"] = sorted(requested)
        requested_at = dict(_AUTOMATION.get("requested_at") or {})
        requested_at["FENIX_LOADING"] = _utc()
        _AUTOMATION["requested_at"] = requested_at
    return result


def _arrival_session_ready(mode: str) -> bool:
    if mode not in {"ARRIVAL", "FULL_TURNAROUND"}:
        return True
    current = _current_airport_position(max_nm=12.0)
    if not current.get("ok"):
        _automation_record("ARRIVAL GATE", current.get("reason") or "waiting for current arrival airport")
        return False
    with _AUTOMATION_LOCK:
        session_airport = str(_AUTOMATION.get("airport_icao") or "").upper()
        generation = int(_AUTOMATION.get("session_generation") or 1)
    current_airport = str(current.get("icao") or "").upper()
    if session_airport and current_airport and session_airport != current_airport:
        with _AUTOMATION_LOCK:
            _AUTOMATION["session_generation"] = generation + 1
            _AUTOMATION["airport_icao"] = current_airport
            _AUTOMATION["arrival_stand"] = {}
            _AUTOMATION["requested"] = []
            _AUTOMATION["requested_at"] = {}
            _AUTOMATION["latches"] = {"session_generation": generation + 1, "stale_departure_state_cleared": True}
        _AUTOMATION_REQUESTED_MONO.clear()
        _automation_record("ARRIVAL GATE", f"Airport changed {session_airport} → {current_airport}; cleared stale departure/session state")
    elif current_airport and not session_airport:
        with _AUTOMATION_LOCK:
            _AUTOMATION["airport_icao"] = current_airport
    if not current.get("parked"):
        _automation_record("ARRIVAL GATE", f"Waiting for aircraft parked/stopped at arrival stand: {current.get('parked_reason') or 'not parked'}")
        return False
    with _AUTOMATION_LOCK:
        cached = dict(_AUTOMATION.get("arrival_stand") or {})
    if not cached.get("ok"):
        detected = _detect_arrival_stand()
        with _AUTOMATION_LOCK:
            _AUTOMATION["arrival_stand"] = detected
        if detected.get("ok"):
            stand = detected.get("stand") or {}
            _automation_record("ARRIVAL GATE", f"Current arrival stand detected: {stand.get('label') or stand.get('name') or 'unknown'}")
        else:
            _automation_record("ARRIVAL GATE", detected.get("message") or "current stand not uniquely detected; waiting for live GSX confirmation")
    return True


def _cargo_wait_detected(snap: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for svc in ((snap.get("services") or {}).values() if isinstance(snap.get("services"), dict) else []):
        if not isinstance(svc, dict):
            continue
        if str(svc.get("label") or "").lower().find("deboard") < 0 and str(svc.get("remote_id") or "").lower().find("deboard") < 0:
            # Cargo waits during unloading/deboarding are the only arrival door case handled here.
            pass
        for key in ("status_text", "waiting_reason", "remote_state", "label"):
            val = svc.get(key)
            if val:
                texts.append(str(val))
    menu = snap.get("menu") if isinstance(snap.get("menu"), dict) else {}
    texts.append(str(menu.get("title") or ""))
    texts.extend(str(x) for x in menu.get("options") or [])
    joined = " | ".join(texts).lower()
    if not joined:
        return []
    required: list[str] = []
    patterns = (("cargo 1", "cargo 1"), ("cargo 2", "cargo 2"), ("main cargo", "main cargo"), ("cargo door", "cargo"), ("cargo hold", "cargo"), ("baggage door", "cargo"))
    if any(word in joined for word in ("waiting", "open", "door", "cargo", "baggage", "loader")):
        for label, needle in patterns:
            if needle in joined:
                required.append(label)
    return sorted(set(required))


def _coordinate_arrival_cargo_doors(snap: dict[str, Any], *, proactive: bool = False) -> None:
    """Arrival cargo-door coordinator.

    Cargo doors are a required arrival-prep step before unloading, not merely a
    reaction to a GSX wait prompt. For Fenix, use the verified EFB GraphQL datarefs
    for forward and aft cargo doors. Unknown aircraft remain manual and must not be
    silently treated as complete.
    """
    if not _arrival_mode_active():
        return
    if _get_latch("cargo_doors_open_requested_once"):
        return
    required = _cargo_wait_detected(snap)
    if proactive and not required:
        required = ["cargo 1", "cargo 2"]
    if not required:
        return
    try:
        fstat = fenix_status(force=False)
    except Exception:
        fstat = {}
    _set_latch("cargo_doors_open_requested_once", {"doors": required, "time": _utc(), "proactive": bool(proactive)})
    if fstat.get("fenix_detected") or fstat.get("fenix_controlled_loading") or fstat.get("fenix_family_hint"):
        joined = " ".join(required).lower()
        doors: set[str] = set()
        if any(x in joined for x in ("cargo 1", "forward", "main")):
            doors.add("forward")
        if any(x in joined for x in ("cargo 2", "aft")):
            doors.add("aft")
        if not doors:
            doors.update({"forward", "aft"})
        results = []
        for door in sorted(doors):
            result = fenix_set_cargo_door(door, True)
            results.append(f"{door}={'OK' if result.get('ok') else result.get('reason') or 'FAILED'}")
        _automation_record("FENIX DOORS", "Arrival cargo doors opened via Fenix EFB GraphQL before unloading: " + "; ".join(results))
        return
    # GSX cargo LVars are wait/indicator state, not door commands. Only a verified
    # aircraft adapter/handler command may be used here. Unknown aircraft stay manual.
    _automation_record("ACTION REQUIRED", "Open cargo door(s) before arrival unloading: " + ", ".join(required) + "; no verified aircraft cargo-door command is available for this adapter")


def _fenix_arrival_family() -> bool:
    try:
        fstat = fenix_status(force=False)
    except Exception:
        fstat = {}
    aircraft = fstat.get("aircraft") if isinstance(fstat.get("aircraft"), dict) else {}
    adapter = aircraft.get("adapter") if isinstance(aircraft.get("adapter"), dict) else {}
    return bool(fstat.get("fenix_detected") or fstat.get("fenix_controlled_loading") or fstat.get("fenix_family_hint") or adapter.get("key") == "fenix")


def _fenix_arrival_state_once(latch: str, label: str, action) -> bool:
    if _get_latch(latch):
        return True
    try:
        result = action()
        ok = bool(result.get("ok"))
        if ok:
            _set_latch(latch, {"time": _utc()})
        else:
            _automation_record("FENIX ARRIVAL", f"{label} command will retry: {result.get('reason') or 'rejected'}")
        return ok
    except Exception as exc:
        _automation_record("FENIX ARRIVAL", f"{label} command will retry: {type(exc).__name__}")
        return False


def _prepare_fenix_arrival_ground_once(reason: str = "arrival services") -> None:
    """Connect ground power/chocks and open cargo doors immediately."""
    if not _arrival_mode_active() or not _fenix_arrival_family():
        return
    gpu = _fenix_arrival_state_once("arrival_gpu_connected", "GPU", lambda: fenix_set_ground_power(True))
    chocks = _fenix_arrival_state_once("arrival_chocks_set", "chocks", lambda: fenix_set_chocks(True))
    fwd = _fenix_arrival_state_once("arrival_cargo_forward_open", "forward cargo door", lambda: fenix_set_cargo_door("forward", True))
    aft = _fenix_arrival_state_once("arrival_cargo_aft_open", "aft cargo door", lambda: fenix_set_cargo_door("aft", True))
    if fwd and aft:
        _set_latch("cargo_doors_open_requested_once", {"time": _utc(), "reason": reason})
    if gpu and chocks and fwd and aft and not _get_latch("arrival_ground_setup_logged"):
        _set_latch("arrival_ground_setup_logged", True)
        _automation_record("FENIX ARRIVAL", "GPU and chocks set; forward and aft cargo doors opened")


def _coordinate_fenix_arrival_entry_doors(snap: dict[str, Any], deboarding_raw: int | None) -> None:
    """Open D1L 30 s and D4L 60 s after the accepted Deboarding request."""
    if not _arrival_mode_active() or not _fenix_arrival_family():
        return
    age = _recent_request_age("deboarding")
    active = deboarding_raw in {4, 5, 7}
    if age is None and active:
        # Recovery after an OPS ROOM restart: the real request predates this
        # process, so do not impose another full minute on an active service.
        _AUTOMATION_REQUESTED_MONO["deboarding"] = time.monotonic() - 60.0
        age = 60.0
    if age is None:
        return
    if age >= 30.0:
        _fenix_arrival_state_once("arrival_d1l_open", "D1L", lambda: fenix_set_entry_door("d1l", True))
    if age >= 60.0:
        _fenix_arrival_state_once("arrival_d4l_open", "D4L", lambda: fenix_set_entry_door("d4l", True))


def _coordinate_arrival_fenix_deboarding(deboarding_raw: int | None = None) -> None:
    """Start the Fenix EFB deboarding task only after the passenger-door schedule.

    The Fenix task can manage entry doors itself, so starting it immediately defeats
    the requested D1L +30 s / D4L +60 s sequence.  GSX Deboarding is still requested
    at once; the aircraft-side task begins once both door gates have elapsed.
    """
    if not _arrival_mode_active() or _get_latch("fenix_arrival_deboarding_started"):
        return
    age = _recent_request_age("deboarding")
    if age is None and deboarding_raw in {4, 5, 7}:
        # Recovery after an OPS ROOM restart: the live service predates this
        # process, so consider the door schedule elapsed rather than delaying it.
        _AUTOMATION_REQUESTED_MONO["deboarding"] = time.monotonic() - 60.0
        age = 60.0
    if age is None or age < 60.0:
        return
    retry_at = _AUTOMATION_REQUESTED_MONO.get("fenix_arrival_deboarding_retry_after")
    if retry_at is not None and time.monotonic() < retry_at:
        return
    try:
        fstat = fenix_status(force=False)
    except Exception:
        fstat = {}
    aircraft = fstat.get("aircraft") if isinstance(fstat.get("aircraft"), dict) else {}
    adapter = aircraft.get("adapter") if isinstance(aircraft.get("adapter"), dict) else {}
    family = bool(fstat.get("fenix_detected") or fstat.get("fenix_controlled_loading") or adapter.get("key") == "fenix")
    if not family:
        return
    try:
        result = fenix_start_deboarding()
        if result.get("ok"):
            _set_latch("fenix_arrival_deboarding_started", {"time": _utc()})
            _AUTOMATION_REQUESTED_MONO.pop("fenix_arrival_deboarding_retry_after", None)
            _automation_record("FENIX DEBOARDING", "Fenix arrival deboarding started after the passenger-door sequence")
        else:
            _AUTOMATION_REQUESTED_MONO["fenix_arrival_deboarding_retry_after"] = time.monotonic() + 10.0
            _automation_record("FENIX DEBOARDING", f"Fenix arrival deboarding is not ready; retrying ({result.get('status_code') or result.get('reason') or 'rejected'})")
    except Exception as exc:
        _AUTOMATION_REQUESTED_MONO["fenix_arrival_deboarding_retry_after"] = time.monotonic() + 10.0
        _automation_record("FENIX DEBOARDING", f"Fenix arrival deboarding is not ready; retrying ({type(exc).__name__})")


_ARRIVAL_SERVICE_SETTINGS = {
    "deboarding": "gsx_arrival_deboarding",
    "cleaning": "gsx_arrival_cleaning",
    "lavatory": "gsx_arrival_lavatory",
}
# Potable water is departure-only. On arrival it can block the rear-stairs work
# area and delay deboarding without adding a useful cabin-turnaround step.
_ARRIVAL_CABIN_SERVICES = ("cleaning", "lavatory")


def _arrival_service_enabled(service: str, settings: dict[str, Any]) -> bool:
    return bool(settings.get(_ARRIVAL_SERVICE_SETTINGS.get(service, ""), True))


def _arrival_service_row(snap: dict[str, Any], service: str) -> dict[str, Any]:
    services = snap.get("services") if isinstance(snap.get("services"), dict) else {}
    row = services.get(service) if isinstance(services, dict) else None
    return row if isinstance(row, dict) else {}


def _arrival_service_can_trigger(snap: dict[str, Any], service: str, raw: int | None) -> bool:
    """Respect Remote API v2 canTrigger; retain legacy/menu fallback support."""
    row = _arrival_service_row(snap, service)
    state = str(row.get("remote_state") or row.get("state") or "").strip().lower()
    remote_v2 = bool(row.get("source") == "official-remote-api-v2" or str(snap.get("provider") or "").lower() == "remote-v2")
    if remote_v2:
        return bool(row.get("can_trigger") or raw == 1 or state == "available")
    return raw in {None, 0, 1}


def _arrival_service_complete_current(snap: dict[str, Any], service: str, raw: int | None) -> bool:
    if _get_latch(f"{service}_complete"):
        return True
    if service == "deboarding" and _deboarding_complete_confirmed(snap, raw):
        _mark_service_complete(service)
        return True
    row = _arrival_service_row(snap, service)
    state = str(row.get("remote_state") or row.get("state") or "").strip().lower()
    requested_now = bool(service in set(_AUTOMATION.get("requested") or []) or _get_latch(f"{service}_requested_once"))
    live_active = bool(raw in {4, 5, 7} or state in {"requested", "performing", "completing"})
    if live_active:
        # A live GSX service is authoritative even when the service.trigger reply
        # was lost or arrived before OPS ROOM could store its local request latch.
        # Adopt it into the current arrival session and wait for a real terminal
        # transition; never let an availability timeout declare active Cleaning done.
        if not requested_now:
            _mark_service_requested(service)
        _set_latch(f"{service}_seen_active", True)
        return False
    if not requested_now:
        return False
    age = _recent_request_age(service)
    # service.trigger acknowledges before GSX publishes the resulting service patch.
    # A stale COMPLETED/BYPASSED row from the previous airport must not close the
    # current session. Require this session to observe REQUESTED/PERFORMING first.
    if _get_latch(f"{service}_seen_active") and (raw in {3, 6} or state in {"completed", "bypassed"}):
        _mark_service_complete(service)
        return True
    # Remote API active-only progress fields disappear after completion. If a service
    # was observed active and then disappears/returns idle, treat that as completion.
    if _get_latch(f"{service}_seen_active") and age is not None and age > 20.0 and raw in {None, 0, 1, 2}:
        _mark_service_complete(service)
        return True
    return False


def _arm_arrival_services(settings: dict[str, Any]) -> list[str]:
    enabled = [service for service in ("deboarding", *_ARRIVAL_CABIN_SERVICES) if _arrival_service_enabled(service, settings)]
    if not _get_latch("arrival_services_armed"):
        _set_latch("arrival_services_armed", {"time": _utc(), "services": enabled})
        for service in enabled:
            _set_latch(f"{service}_armed", True)
        _AUTOMATION_REQUESTED_MONO.setdefault("arrival_services_armed", time.monotonic())
        _AUTOMATION_REQUESTED_MONO.setdefault("arrival_cabin_sequence_started", time.monotonic())
        labels = ", ".join(SERVICE_LABELS.get(service, service.upper()) for service in enabled)
        _automation_record("ARRIVAL SERVICES", f"Armed {labels}; each service will be requested when GSX makes it available")
    return enabled


def _request_arrival_service_when_available(
    snap: dict[str, Any], service: str, raw: int | None
) -> dict[str, Any]:
    """Issue every enabled arrival request once, then let GSX coordinate it.

    Current GSX versions accept Deboarding, Cleaning and Lavatory together and
    internally hold Cleaning until deboarding permits it. The first attempt is
    therefore intentionally not blocked by a stale canTrigger snapshot. If GSX
    explicitly refuses the command, a later retry is allowed only when the live
    service becomes triggerable; accepted commands remain monotonic.
    """
    if _arrival_service_complete_current(snap, service, raw):
        return {"ok": True, "complete": True, "service": service}
    if service in set(_AUTOMATION.get("requested") or []) or _get_latch(f"{service}_requested_once"):
        return {"ok": True, "already_requested": True, "service": service}
    if _get_latch(f"{service}_deferred_or_skipped"):
        return {"ok": True, "deferred": True, "service": service}
    first_attempt = not _get_latch(f"{service}_initial_request_attempted")
    if first_attempt:
        _set_latch(f"{service}_initial_request_attempted", {"time": _utc()})
        return _request_once(service)
    if not _arrival_service_can_trigger(snap, service, raw):
        return {"ok": False, "waiting_availability": True, "service": service}
    return _request_once(service)


def _arrival_deboarding_started(snap: dict[str, Any], raw: int | None) -> bool:
    if raw in {4, 5, 7} or _get_latch("deboarding_seen_active") or _get_latch("deboarding_seen_performing"):
        return True
    progress = snap.get("progress") if isinstance(snap.get("progress"), dict) else {}
    try:
        return int(progress.get("passengers_deboarding_total") or 0) > 0
    except Exception:
        return False


def _maybe_retry_arrival_cleaning_once(snap: dict[str, Any], deboarding_raw: int | None, cleaning_raw: int | None) -> None:
    """One-shot Cleaning safeguard five minutes after deboarding starts.

    Cleaning is requested with the rest of the arrival package. Some GSX sessions
    acknowledge Deboarding/Lavatory but silently drop the first Cleaning trigger.
    Retry exactly once only when Cleaning has never been acknowledged in this
    session; GSX remains responsible for waiting until deboarding permits entry.
    """
    if not _arrival_deboarding_started(snap, deboarding_raw):
        return
    started = _AUTOMATION_REQUESTED_MONO.setdefault("arrival_deboarding_started_at", time.monotonic())
    if time.monotonic() - float(started) < 300.0:
        return
    if _get_latch("cleaning_safeguard_attempted"):
        return
    row = _arrival_service_row(snap, "cleaning")
    live_state = str(row.get("remote_state") or row.get("state") or "").strip().lower()
    acknowledged = bool(
        _get_latch("cleaning_seen_active")
        or _get_latch("cleaning_complete")
        or cleaning_raw in {4, 5, 7}
        or live_state in {"requested", "performing", "completing"}
    )
    if acknowledged:
        return
    _set_latch("cleaning_safeguard_attempted", {"time": _utc()})
    _set_latch("cleaning_deferred_or_skipped", False)
    _AUTOMATION_REQUESTED_MONO.pop("cleaning_retry_after", None)
    _automation_record("CLEANING", "Cleaning was not acknowledged; sending one final request")
    # Bypass the local requested-once latch for this single safeguard attempt.
    # The latch records that OPS ROOM sent the first command; it does not prove
    # that GSX accepted/published Cleaning in the current arrival session.
    result = call_service("cleaning", automate=True)
    if result.get("ok"):
        _mark_service_requested("cleaning")
        _automation_record("REQUESTED", "CLEANING requested (final safeguard)")
    elif result.get("requires_selection"):
        _automation_record("ACTION REQUIRED", result.get("reason") or "Select Cleaning in GSX")
    else:
        _automation_record("CLEANING", "GSX did not accept the final Cleaning request")


def _maybe_defer_unavailable_arrival_service(
    snap: dict[str, Any], service: str, raw: int | None
) -> bool:
    """Never convert an enabled cabin service into completion by timeout alone.

    GSX may briefly publish Cleaning/Lavatory as unavailable while its vehicle is
    requested, approaching or waiting for a work area. RC18 treated that transient
    state as a skipped service after deboarding and could finish Arrival while the
    cleaning crew was visibly still working. Disabled services are completed by the
    settings branch; enabled services now remain pending until GSX publishes a real
    completed/bypassed transition after current-session activity.
    """
    if service not in _ARRIVAL_CABIN_SERVICES:
        return False
    if _get_latch(f"{service}_complete"):
        return False
    row = _arrival_service_row(snap, service)
    state = str(row.get("remote_state") or row.get("state") or "").strip().lower()
    if raw in {4, 5, 7} or state in {"requested", "performing", "completing"}:
        if service not in set(_AUTOMATION.get("requested") or []):
            _mark_service_requested(service)
        _set_latch(f"{service}_seen_active", True)
    return False


def _arrival_receipt_signatures() -> set[tuple[str, str, str]]:
    try:
        from .gsx_receipts import list_receipts
        rows = list((list_receipts(limit=200) or {}).get("items") or [])
    except Exception:
        return set()
    return {
        (str(row.get("category") or ""), str(row.get("filename") or row.get("json_filename") or ""), str(row.get("issued_utc") or row.get("modified_utc") or ""))
        for row in rows if isinstance(row, dict)
    }


def _finalize_arrival_handling_invoice() -> bool:
    """Close GSX's pending Arrival handling invoice without touching Turnaround.

    GSX Remote API builds can run the documented Couatl restart command. Legacy
    builds are not driven through fragile menu/keyboard automation; they receive a
    clear manual finalisation message and the completed Arrival session is released.
    """
    if _get_latch("arrival_invoice_finalized") or _get_latch("arrival_invoice_manual_required"):
        return True
    if _get_latch("arrival_invoice_finalization_started"):
        return False

    official = _official_status(force=True)
    remote_ready = bool(official.get("reachable") and official.get("ws_connected") and official.get("protocol") == "official-remote-api-v2")
    if not remote_ready:
        _set_latch("arrival_invoice_manual_required", True)
        _automation_record(
            "ACTION REQUIRED",
            "Arrival services complete. This GSX version has no Remote API restart command; restart GSX/Couatl manually to generate the pending handling invoice.",
        )
        return True

    _set_latch("arrival_invoice_finalization_started", {"time": _utc()})
    before_receipts = _arrival_receipt_signatures()
    pre_sid = str(official.get("startup_sid") or "")
    _automation_record("FINALIZING INVOICE", "Arrival services complete; restarting GSX/Couatl to publish the handling invoice")
    _stop_operator_observer()

    # A Couatl restart can close the command socket before the acknowledgement is
    # returned. Treat the command response as one signal and confirm the restart
    # independently from the official engine/startup lifecycle below.
    command = _official_command("command.run", {"command": "RESTART_COUATL"}, timeout=1.8)
    command_accepted = bool(command.get("ok"))
    restart_seen = False
    ready_since = 0.0
    started = time.monotonic()
    deadline = started + 90.0
    last_status_note = 0.0

    while time.monotonic() < deadline and not _AUTOMATION_STOP.is_set():
        _invalidate()
        _invalidate_official()
        current = _official_status(force=True)
        now = time.monotonic()
        current_sid = str(current.get("startup_sid") or "")
        reachable = bool(current.get("reachable") and current.get("ws_connected"))
        running = bool(current.get("gsx_running"))
        startup_active = bool(current.get("startup_active"))
        sid_changed = bool(pre_sid and current_sid and current_sid != pre_sid)
        if sid_changed or not reachable or not running or startup_active:
            restart_seen = True
        ready = bool(reachable and running and not startup_active)
        if ready:
            if ready_since <= 0.0:
                ready_since = now
            # Prefer observed lifecycle/sid evidence. A confirmed command may restart
            # too quickly to expose the short offline state, so accept a stable ready
            # connection after a conservative settle period in that case.
            if (restart_seen and (sid_changed or now - ready_since >= 2.0)) or (command_accepted and now - started >= 8.0 and now - ready_since >= 2.0):
                break
        else:
            ready_since = 0.0
        if now - last_status_note >= 12.0:
            last_status_note = now
            _automation_record("FINALIZING INVOICE", "Waiting for GSX/Couatl to restart and reconnect")
        time.sleep(1.0)
    else:
        _set_latch("arrival_invoice_manual_required", True)
        reason = str(command.get("reason") or "GSX did not return to a ready Remote API state")
        _automation_record("ACTION REQUIRED", f"Automatic GSX invoice finalization was not confirmed: {reason}. Restart GSX/Couatl manually and recheck receipts.")
        return True

    # The restart resets GSX runtime handler preferences. Restore the one OPS ROOM
    # deliberately controls; a later service session's observer will verify it again.
    try:
        _official_command(
            "handler.set",
            {"target": "gate", "name": "autoSelectOperator", "value": False},
            timeout=1.0,
        )
    except Exception:
        pass

    new_receipts: set[tuple[str, str, str]] = set()
    receipt_deadline = time.monotonic() + 15.0
    while time.monotonic() < receipt_deadline and not _AUTOMATION_STOP.is_set():
        new_receipts = _arrival_receipt_signatures() - before_receipts
        if any(category.lower() == "handling" for category, _filename, _stamp in new_receipts):
            break
        time.sleep(1.0)

    handling_count = sum(1 for category, _filename, _stamp in new_receipts if category.lower() == "handling")
    _set_latch("arrival_invoice_finalized", {"time": _utc(), "new_handling_receipts": handling_count})
    if handling_count:
        _automation_record("READY", f"Arrival services complete; GSX restarted and {handling_count} handling invoice{'s' if handling_count != 1 else ''} imported")
    else:
        _automation_record("READY", "Arrival services complete; GSX restarted and receipts rescanned")
    return True


def _maybe_retry_departure_water_once(raw: int | None) -> None:
    """Retry Water once when GSX accepted a call but never acknowledged it."""
    if not _departure_mode_active() or _get_latch("water_seen_active") or _get_latch("water_complete"):
        return
    age = _recent_request_age("water")
    if age is None or age < 10.0 or _get_latch("water_safeguard_attempted"):
        return
    _set_latch("water_safeguard_attempted", {"time": _utc(), "raw": raw})
    _automation_record("WATER", "Potable Water was not acknowledged; sending one final current-session request")
    result = call_service("water", automate=True)
    if result.get("ok"):
        _AUTOMATION_REQUESTED_MONO["water"] = time.monotonic()
        _automation_record("REQUESTED", "POTABLE WATER requested (final safeguard)")
    elif result.get("requires_selection"):
        _automation_record("ACTION REQUIRED", result.get("reason") or "Select Potable Water in GSX")
    else:
        _automation_record("WATER", "GSX did not accept the final Potable Water request")


def _service_plan_for_mode(mode: str, settings: dict[str, Any], raws: dict[str, int | None], fenix_loading: bool) -> list[tuple[str, int | None, bool]]:
    if mode == "FULL_TURNAROUND":
        # Arrival services are coordinated independently and armed together. Once
        # they finish, Full Turnaround continues into the proven departure prep.
        return [
            ("catering", raws.get("catering"), bool(settings.get("gsx_departure_catering", True))),
            ("refuel", raws.get("refuel"), bool(settings.get("gsx_departure_refuel", True)) and not fenix_loading),
        ]
    if mode == "DEPARTURE":
        return [
            ("catering", raws.get("catering"), bool(settings.get("gsx_departure_catering", True))),
            ("refuel", raws.get("refuel"), bool(settings.get("gsx_departure_refuel", True)) and not fenix_loading),
            ("water", raws.get("water"), bool(settings.get("gsx_departure_water", True))),
        ]
    return []


def _automation_cycle(mode: str) -> bool:
    if mode == "AUTO":
        detected = _detect_turnaround_mode()
        with _AUTOMATION_LOCK:
            _AUTOMATION["mode"] = detected
        mode = detected
        _automation_record("MODE", f"Detected {mode.replace('_', ' ').title()} mode")
    arrival_mode = mode in {"ARRIVAL", "FULL_TURNAROUND"}
    departure_mode = mode in {"DEPARTURE", "FULL_TURNAROUND"}
    if arrival_mode and not _arrival_session_ready(mode):
        return False
    snap = status(force=True)
    services = snap.get("services") or {}
    progress = snap.get("progress") or {}
    settings = load_settings().get("integrations", {})
    fenix_aircraft_likely = bool(departure_mode and settings.get("gsx_fenix_auto_load", True) and _fenix_aircraft_likely_now())
    fenix_available_now = bool(departure_mode and _fenix_loading_available() and settings.get("gsx_fenix_auto_load", True))
    if fenix_available_now or fenix_aircraft_likely:
        if not _fenix_controlled_session_active():
            _set_latch("fenix_controlled_session", True)
            _automation_record("FENIX_SESSION_LATCHED", "reason=aircraft_family")
    fenix_loading = bool(departure_mode and settings.get("gsx_fenix_auto_load", True) and (fenix_available_now or fenix_aircraft_likely or _fenix_controlled_session_active()))
    if fenix_loading and str(snap.get("source") or "") == "simconnect-lvars":
        planned_pax = fenix_loading_targets().get("pax_count")
        legacy_pax = _legacy_gsx_passenger_target(planned_pax)
        try:
            authoritative_pax = int(round(float(planned_pax)))
        except (TypeError, ValueError):
            authoritative_pax = 0
        if authoritative_pax > 0:
            # Use the authoritative SimBrief/Fenix target immediately in this cycle
            # while the SimConnect readback cache catches up. The live boarded count
            # remains GSX's documented running counter.
            progress = dict(progress)
            progress["passengers_target"] = authoritative_pax
            snap = dict(snap)
            snap["progress"] = progress
            if not legacy_pax.get("ok") and not legacy_pax.get("deferred"):
                _automation_record("LEGACY GSX", f"Passenger-target reconciliation will retry: {legacy_pax.get('reason') or 'unknown error'}")
    raws = {key: _service_raw(snap, key) for key in ("boarding", "deboarding", "catering", "refuel", "water", "lavatory", "cleaning", "pushback")}
    _update_completion_latches(raws)
    # Track when pushback first becomes active so the 30s-delayed chocks/GPU
    # disconnect can fire even if the direction menu is never visible.
    global _PUSHBACK_ACTIVE_SINCE
    pushback_raw = raws.get("pushback")
    if pushback_raw is not None and pushback_raw != 0:
        if _PUSHBACK_ACTIVE_SINCE == 0.0:
            _PUSHBACK_ACTIVE_SINCE = time.monotonic()
    # Do not mutate the GSX aircraft refueling handler in the normal Fenix EFB flow.
    # Generic GSX refuel is already blocked by the service plan and request guards.
    # Leaving handler.set opt-in avoids disrupting the Fenix EFB startGsxBoarding task.
    if fenix_loading and bool(settings.get("gsx_fenix_handler_set_refuel_false", False)):
        _official_handler_set_aircraft_refueling_false_once()

    if arrival_mode:
        enabled_arrival = _arm_arrival_services(settings)
        deboarding_enabled = "deboarding" in enabled_arrival
        if deboarding_enabled:
            # GPU/chocks and cargo access are immediate. Passenger doors use the
            # requested 30/60-second timing from the first accepted Deboarding call.
            _prepare_fenix_arrival_ground_once("arrival services started")
            _request_arrival_service_when_available(snap, "deboarding", raws.get("deboarding"))
            _coordinate_fenix_arrival_entry_doors(snap, raws.get("deboarding"))
            _coordinate_arrival_fenix_deboarding(raws.get("deboarding"))
            _coordinate_arrival_cargo_doors_closed(snap, raws.get("deboarding"))
        else:
            _mark_service_complete("deboarding")

        # Request the arrival package together. GSX coordinates vehicle/work-area
        # conflicts internally and holds Cleaning until passenger deboarding permits it.
        for key in _ARRIVAL_CABIN_SERVICES:
            if key not in enabled_arrival:
                _mark_service_complete(key)
                continue
            _request_arrival_service_when_available(snap, key, raws.get(key))

        deboarding_confirmed = (
            not deboarding_enabled
            or _arrival_service_complete_current(snap, "deboarding", raws.get("deboarding"))
        )
        if deboarding_confirmed:
            _AUTOMATION_REQUESTED_MONO.setdefault("arrival_deboarding_complete_at", time.monotonic())
            _coordinate_arrival_cargo_doors_closed(snap, raws.get("deboarding"))

        for key in _ARRIVAL_CABIN_SERVICES:
            if key in enabled_arrival:
                _arrival_service_complete_current(snap, key, raws.get(key))
                _maybe_defer_unavailable_arrival_service(snap, key, raws.get(key))

        if "cleaning" in enabled_arrival:
            _maybe_retry_arrival_cleaning_once(snap, raws.get("deboarding"), raws.get("cleaning"))

        arrival_pending: list[str] = []
        if deboarding_enabled and not _get_latch("deboarding_complete"):
            arrival_pending.append("deboarding")
        for key in _ARRIVAL_CABIN_SERVICES:
            if key not in enabled_arrival:
                continue
            if not _get_latch(f"{key}_complete") and not _get_latch(f"{key}_deferred_or_skipped"):
                arrival_pending.append(key)

        if arrival_pending:
            waiting_labels = ", ".join(SERVICE_LABELS.get(key, key.upper()) for key in arrival_pending)
            _automation_record("ARRIVAL SERVICES", f"Armed and monitoring: {waiting_labels}")
            return False

        _automation_record("ARRIVAL SERVICES", "Deboarding and cabin services complete")
        if mode == "ARRIVAL":
            return _finalize_arrival_handling_invoice()

    if departure_mode:
        _ensure_departure_recorder_started("Departure portion of ground-service session")
    service_plan = _service_plan_for_mode(mode, settings, raws, fenix_loading)
    _automation_record("SERVICING", "Coordinating GSX services in locked OPS ROOM sequence")
    for key, raw, enabled in service_plan:
        if not enabled:
            continue
        if mode == "DEPARTURE" and key in _DEPARTURE_FORBIDDEN_SERVICES:
            _automation_record("GUARD", f"Departure mode blocked arrival-only service {SERVICE_LABELS.get(key, key.upper())}")
            continue
        if _needs_request(key, raw):
            _request_once(key)
    if mode == "DEPARTURE" and bool(settings.get("gsx_departure_water", True)):
        _maybe_retry_departure_water_once(raws.get("water"))
    pending = [
        key for key, raw, enabled in service_plan
        if enabled and not (mode == "DEPARTURE" and key in _DEPARTURE_FORBIDDEN_SERVICES) and _service_pending_after_request(key, raw)
    ]
    if pending:
        _automation_record("SERVICING", "Waiting for " + ", ".join(SERVICE_LABELS.get(k, k.upper()) for k in pending))
        return False

    if departure_mode:
        boarding = raws.get("boarding")
        if fenix_loading and settings.get("gsx_departure_boarding", True):
            if not _fenix_loading_requested():
                try:
                    result = _request_fenix_loading_once()
                    targets = result.get("targets") or {}
                    if not result.get("already_requested"):
                        _set_latch("fenix_loading_started_once", True)
                        _automation_record("FENIX", f"Fenix EFB GSX loading started once: fuel {targets.get('fuel_kg') or '---'} kg, cargo {targets.get('cargo_kg') or '---'} kg")
                except Exception as exc:
                    _automation_record("FENIX", f"Fenix EFB loading failed; generic GSX refuel/boarding remains blocked for this Fenix-controlled departure: {type(exc).__name__}: {exc}")
                return False
            if _fenix_loading_requested():
                fenix_progress_snapshot = _fenix_progress_safe()
                decision = _update_fenix_phase_machine(
                    snap=snap,
                    boarding_raw=boarding,
                    refuel_raw=raws.get("refuel"),
                    catering_raw=raws.get("catering"),
                    settings=settings,
                    fenix_progress=fenix_progress_snapshot,
                )
                diag = getattr(decision, "diagnostic", {}) or {}
                phase = str(getattr(getattr(decision, "phase", None), "value", None) or getattr(decision, "phase", "FENIX"))
                pax = int(progress.get("passengers_boarding_total") or 0)
                target = int(progress.get("passengers_target") or 0)
                authoritative_complete = _fenix_authoritative_complete(progress, fenix_progress_snapshot)
                _coordinate_departure_cargo_doors_closed(fenix_progress_snapshot, progress, boarding, snap)
                if _get_latch("fenix_targets_complete") and _get_latch("fenix_pushback_armed_after_loading"):
                    # Loading completion is a one-way transition within this service
                    # session. GSX can remove finished passenger counters (120/120 ->
                    # 0/---); that must not reopen boarding and strand the armed timer.
                    _set_latch("boarding_complete", True)
                    _set_latch("refuel_complete_or_fenix_complete", True)
                    if bool(settings.get("gsx_auto_prepare_after_services", settings.get("gsx_auto_pushback", True))):
                        armed_at = _AUTOMATION_REQUESTED_MONO.get("fenix_pushback_armed_after_loading")
                        if armed_at is None:
                            _AUTOMATION_REQUESTED_MONO["fenix_pushback_armed_after_loading"] = time.monotonic()
                            armed_at = _AUTOMATION_REQUESTED_MONO["fenix_pushback_armed_after_loading"]
                        remaining = max(0, int(round(60.0 - (time.monotonic() - float(armed_at)))))
                        if remaining > 0:
                            _automation_record("PUSHBACK_ARMED_AFTER_LOADING", f"delay=60s remaining={remaining}s")
                            return False
                        _automation_record("PUSHBACK_REQUESTED_AFTER_LOADING", "Verified loading-complete latch; delay elapsed")
                        if not _coordinate_verified_pushback_handoff(snap):
                            return False
                    else:
                        _automation_record("READY", "Fenix loading complete, pushback remains manual")
                    return True
                if not _get_latch("departure_boarding_entry_doors_opened") and (boarding in {4, 5, 7} or pax > 0):
                    door_results = [fenix_set_entry_door("d1l", True), fenix_set_entry_door("d4l", True)]
                    if all(bool(item.get("ok")) for item in door_results):
                        _set_latch("departure_boarding_entry_doors_opened", True)
                        _automation_record("FENIX DOORS", "Boarding started; D1L and D4L opened")
                    else:
                        _automation_record("FENIX DOORS", "Boarding started; passenger-door command will retry")
                if phase == "FAILED":
                    _automation_record("FENIX", f"Fenix loading monitor reported: {diag.get('failure_reason') or getattr(decision, 'reason', 'waiting for progress')}; monitoring only")
                    return False
                if boarding == 6 and not authoritative_complete and phase != "COMPLETE":
                    _automation_record("FENIX", "GSX boarding reports complete, waiting for Fenix EFB load reconciliation before pushback")
                    return False
                passenger_boarding_complete = _boarding_service_complete_from_snapshot(snap)
                if (phase == "COMPLETE" or authoritative_complete) and not passenger_boarding_complete:
                    _automation_record(
                        "FENIX",
                        f"Cargo/fuel targets settled; passenger boarding continues {pax}/{target or '---'}",
                    )
                    return False
                if phase == "COMPLETE" or authoritative_complete:
                    _set_latch("boarding_complete", True)
                    _set_latch("refuel_complete_or_fenix_complete", True)
                    _set_latch("fenix_targets_complete", True)
                    _automation_record(
                        "FENIX_EFB_TARGETS_COMPLETE",
                        f"pax={int(fenix_progress_snapshot.get('pax_loaded') or progress.get('passengers_boarding_total') or 0)}/"
                        f"{int(fenix_progress_snapshot.get('pax_target') or progress.get('passengers_target') or 0)} "
                        f"cargo={int(fenix_progress_snapshot.get('cargo_loaded_kg') or 0)}/"
                        f"{int(fenix_progress_snapshot.get('cargo_target_kg') or 0)} "
                        f"fuel={int(fenix_progress_snapshot.get('fuel_loaded_kg') or 0)}/"
                        f"{int(fenix_progress_snapshot.get('fuel_target_kg') or 0)}",
                    )
                    _automation_record("FENIX_GSX_LOADING_COMPLETE", "Fenix EFB targets settled; loading handoff complete")
                    _coordinate_departure_cargo_doors_closed(fenix_progress_snapshot, progress, boarding, snap)
                    if bool(settings.get("gsx_auto_prepare_after_services", settings.get("gsx_auto_pushback", True))):
                        armed_at = _AUTOMATION_REQUESTED_MONO.get("fenix_pushback_armed_after_loading")
                        if armed_at is None:
                            _AUTOMATION_REQUESTED_MONO["fenix_pushback_armed_after_loading"] = time.monotonic()
                            _set_latch("fenix_pushback_armed_after_loading", True)
                            _automation_record("PUSHBACK_ARMED_AFTER_LOADING", "delay=60s")
                            return False
                        remaining = max(0, int(round(60.0 - (time.monotonic() - armed_at))))
                        if remaining > 0:
                            _automation_record("PUSHBACK_ARMED_AFTER_LOADING", f"delay=60s remaining={remaining}s")
                            return False
                        _automation_record("PUSHBACK_REQUESTED_AFTER_LOADING", "Fenix loading complete delay elapsed")
                        if not _coordinate_verified_pushback_handoff(snap):
                            return False
                    else:
                        _automation_record("READY", "Fenix loading complete, pushback remains manual")
                    return True
                detail = getattr(decision, "reason", "") or phase.replace("_", " ").title()
                suffix = f" · passengers {pax}/{target}" if target else ""
                _automation_record("FENIX", f"{phase}: {detail}{suffix}")
                return False
        if _needs_request("boarding", boarding) and settings.get("gsx_departure_boarding", True):
            _automation_record("BOARDING", "Requesting departure boarding")
            _request_once("boarding")
            return False
        if boarding in {4, 5, 7} or _service_pending_after_request("boarding", boarding):
            pax = int(progress.get("passengers_boarding_total") or 0)
            target = int(progress.get("passengers_target") or 0)
            _automation_record("BOARDING", f"Passengers {pax} / {target}" if target else "Boarding in progress")
            return False
        if boarding == 6 or not settings.get("gsx_departure_boarding", True):
            _mark_service_complete("boarding")
            if bool(settings.get("gsx_auto_prepare_after_services", settings.get("gsx_auto_pushback", True))):
                _automation_record("PUSHBACK", "Services complete; requesting verified GSX pushback preparation")
                if not _coordinate_verified_pushback_handoff(snap):
                    return False
            else:
                _automation_record("READY", "Departure services complete, pushback remains manual")
            return True
    _automation_record("READY", "Arrival services complete")
    return True


def _pushback_direction_menu_visible() -> bool:
    try:
        menu = _active_menu(prefer_official=True)
    except Exception:
        return False
    return bool(menu.get("available") and _looks_like_pushback_direction(str(menu.get("title") or ""), list(menu.get("options") or [])))


def _pushback_handoff_confirmed(snap: dict[str, Any]) -> bool:
    raw = _service_raw(snap, "pushback")
    if raw in {4, 5, 7} or _pushback_has_started():
        return True
    return _pushback_direction_menu_visible()


def _pushback_menu_fallback_once() -> dict[str, Any]:
    if _get_latch("pushback_menu_fallback_attempted"):
        return {"ok": False, "already_attempted": True}
    _set_latch("pushback_menu_fallback_attempted", {"time": _utc()})
    try:
        index, menu = _find_service_through_pages("pushback")
        options = list((menu or {}).get("options") or [])
        if index is None or index >= len(options):
            return {"ok": False, "reason": "Prepare for Push-back and Departure was not present in the live GSX menu"}
        label = str(options[index])
        result = select_menu_by_label(label, ALIASES["pushback"])
        if result.get("ok"):
            _automation_record("PUSHBACK", "Opened GSX pushback-direction selection using the live menu label")
        return result
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}


def _coordinate_verified_pushback_handoff(snap: dict[str, Any]) -> bool:
    if _pushback_handoff_confirmed(snap):
        if _pushback_direction_menu_visible():
            if _fenix_loading_requested() and not _get_latch("fenix_ground_removed_after_pushback"):
                _set_latch("fenix_ground_removed_after_pushback", True)
                try:
                    fenix_set_chocks(False)
                    _automation_record("FENIX", "Chocks removed for pushback")
                except Exception as exc:
                    _automation_record("FENIX", f"Failed to remove chocks: {type(exc).__name__}: {exc}")
                try:
                    fenix_set_ground_power(False)
                    _automation_record("FENIX", "GPU disconnected for pushback")
                except Exception as exc:
                    _automation_record("FENIX", f"Failed to disconnect GPU: {type(exc).__name__}: {exc}")
            _automation_record("PUSHBACK", "Pushback is ready; select the direction in GSX")
        else:
            _automation_record("PUSHBACK", "GSX confirmed the departure/pushback service")
        return True
    age = _recent_request_age("pushback")
    if age is None:
        result = _request_once("pushback")
        if not result.get("ok") and not result.get("requires_selection"):
            return False
        age = _recent_request_age("pushback") or 0.0
    if age >= 5.0 and not _get_latch("pushback_menu_fallback_attempted"):
        _pushback_menu_fallback_once()
        try:
            snap = status(force=True)
        except Exception:
            pass
        if _pushback_handoff_confirmed(snap):
            _automation_record("PUSHBACK", "Pushback is ready; select the direction in GSX")
            return True
    if age >= 20.0 and not _get_latch("pushback_action_required_logged"):
        _set_latch("pushback_action_required_logged", True)
        _automation_record("ACTION REQUIRED", "GSX did not open pushback preparation automatically; select Prepare for Push-back and Departure in GSX")
    return False


def _ensure_departure_recorder_started(reason: str) -> None:
    # A new departure-services session is also the authoritative boundary for a
    # new cabin-announcement flight. Clear stale arrival/airborne latches once,
    # without touching the proven trigger order after the session begins.
    if not _get_latch("announcement_departure_session_reset"):
        try:
            from .announcements import reset_flight
            reset_flight()
            _set_latch("announcement_departure_session_reset", True)
            _automation_record("CABIN", "Departure announcement sequence ready")
        except Exception as exc:
            _automation_record("CABIN", f"Announcement session reset will retry: {type(exc).__name__}")
            return
    if _get_latch("departure_recorder_started"):
        return
    try:
        from .logbook import start_departure_services
        result = start_departure_services(reason=reason)
        if result.get("ok"):
            _set_latch("departure_recorder_started", True)
            _automation_record("RECORDER", "Flight recording armed from departure services")
    except Exception as exc:
        _automation_record("RECORDER", f"Recorder start will retry: {type(exc).__name__}")


def _automation_loop() -> None:
    try:
        with _AUTOMATION_LOCK:
            mode = str(_AUTOMATION.get("mode") or "AUTO").upper()
        _automation_record("START", f"Ground service automation started in {mode.replace('_', ' ').title()} mode")
        while not _AUTOMATION_STOP.wait(1.5):
            try:
                if _automation_cycle(mode):
                    break
                with _AUTOMATION_LOCK:
                    mode = str(_AUTOMATION.get("mode") or mode).upper()
            except Exception as exc:
                # A polling/Fenix/GSX snapshot exception must not kill the service thread
                # or rebuild the completed service plan. Keep durable latches intact.
                _automation_record("FAULT", f"{type(exc).__name__}: {exc}; continuing current GSX session")
                continue
            # 30s after pushback first becomes active, forcibly disconnect Fenix
            # chocks and GPU as a safety net when the direction-menu trigger path
            # (in _coordinate_verified_pushback_handoff) does not fire.
            try:
                if _PUSHBACK_ACTIVE_SINCE > 0 and not _get_latch("fenix_ground_removed_after_pushback"):
                    if time.monotonic() - _PUSHBACK_ACTIVE_SINCE >= 30.0:
                        _set_latch("fenix_ground_removed_after_pushback", True)
                        try:
                            fenix_set_chocks(False)
                            _automation_record("FENIX", "Chocks removed (30s after pushback)")
                        except Exception as exc2:
                            _automation_record("FENIX", f"Chocks removal failed: {type(exc2).__name__}: {exc2}")
                        try:
                            fenix_set_ground_power(False)
                            _automation_record("FENIX", "GPU disconnected (30s after pushback)")
                        except Exception as exc3:
                            _automation_record("FENIX", f"GPU disconnect failed: {type(exc3).__name__}: {exc3}")
            except Exception:
                pass
    finally:
        with _AUTOMATION_LOCK:
            _AUTOMATION["running"] = False
            _AUTOMATION["updated_at"] = _utc()


def start_automation(mode: str = "AUTO") -> dict[str, Any]:
    global _AUTOMATION_THREAD
    settings = load_settings().get("integrations", {})
    if not bool(settings.get("gsx_automation_enabled", True)):
        raise RuntimeError("GSX automation is disabled in Host settings")
    with _AUTOMATION_LOCK:
        if _AUTOMATION_THREAD and _AUTOMATION_THREAD.is_alive():
            return automation_status()
        _AUTOMATION_STOP.clear()
        _stop_pushback_direction_keepalive()
        _PUSHBACK_KEEPALIVE_STOP.clear()
        _AUTOMATION_REQUESTED_MONO.clear()
        _reset_fenix_loading_session()
        mode = str(mode or "AUTO").upper().replace(" ", "_")
        if mode not in {"AUTO", "DEPARTURE", "ARRIVAL", "FULL_TURNAROUND"}:
            mode = "AUTO"
        current = _current_airport_position(max_nm=20.0)
        arrival_stand = _detect_arrival_stand() if mode in {"ARRIVAL", "FULL_TURNAROUND"} else {}
        session_generation = int(_AUTOMATION.get("session_generation") or 0) + 1
        _AUTOMATION.update({
            "running": True,
            "stage": "STARTING",
            "detail": "Initialising",
            "started_at": _utc(),
            "updated_at": _utc(),
            "requested": [],
            "requested_at": {},
            "history": [],
            "mode": mode,
            "airport_icao": current.get("icao") or "",
            "arrival_stand": arrival_stand,
            "stale_gate_guard": True,
            "session_generation": session_generation,
            "latches": {
                "session_generation": session_generation,
                "catering_requested_once": False,
                "catering_complete": False,
                "boarding_requested_once": False,
                "boarding_complete": False,
                "deboarding_requested_once": False,
                "deboarding_complete": False,
                "arrival_services_armed": False,
                "deboarding_armed": False,
                "cleaning_armed": False,
                "lavatory_armed": False,
                "water_armed": False,
                "cargo_doors_open_requested_once": False,
                "fenix_arrival_deboarding_started": False,
                "fenix_loading_started_once": False,
                "fenix_controlled_session": False,
                "refuel_handled_by_fenix": False,
                "refuel_complete_or_fenix_complete": False,
                "cleaning_requested_once": False,
                "cleaning_complete": False,
                "cleaning_safeguard_attempted": False,
                "lavatory_requested_once": False,
                "lavatory_complete": False,
                "water_requested_once": False,
                "water_safeguard_attempted": False,
                "water_complete": False,
                "water_deferred_or_skipped": False,
                "arrival_fenix_doors_opened_once": False,
                "arrival_gpu_connected": False,
                "arrival_chocks_set": False,
                "arrival_cargo_forward_open": False,
                "arrival_cargo_aft_open": False,
                "arrival_d1l_open": False,
                "arrival_d4l_open": False,
                "arrival_cargo_doors_closed_once": False,
                "arrival_cargo_doors_close_due_mono": 0.0,
                "arrival_cargo_doors_close_armed_at": "",
                "pushback_menu_fallback_attempted": False,
                "departure_recorder_started": False,
                "announcement_departure_session_reset": False,
                "departure_cargo_doors_closed_once": False,
                "departure_boarding_entry_doors_opened": False,
                "fenix_ground_removed_after_pushback": False,
                "operator_preference_attempted": False,
                "legacy_gsx_pax_target": 0,
                "legacy_gsx_pax_target_logged": False,
                "arrival_invoice_finalization_started": False,
                "arrival_invoice_finalized": False,
                "arrival_invoice_manual_required": False,
                "airport_icao": current.get("icao") or "",
                "mode": mode,
            },
        })
        if mode == "DEPARTURE":
            _ensure_departure_recorder_started("Begin Departure Services")
        _AUTOMATION_THREAD = threading.Thread(target=_automation_loop, name="OpsRoom-GSX-Automation", daemon=True)
    # Tell GSX to show the operator popup instead of auto-selecting, covering
    # the case where startup/SimBrief-fetch ran before GSX was reachable.
    try:
        _official_command(
            "handler.set",
            {"target": "gate", "name": "autoSelectOperator", "value": False},
            timeout=1.0,
        )
    except Exception:
        pass
    # Start the isolated observer first. The proven automation loop waits 1.5
    # seconds before its first service cycle, giving the observer time to ask
    # GSX for a visible operator popup without delaying the user-facing request.
    try:
        _start_operator_observer(session_generation)
    except Exception as exc:
        _stop_operator_observer()
        _automation_record("OPERATOR", f"Operator observer unavailable; RC10 service automation continues unchanged: {type(exc).__name__}")
    _AUTOMATION_THREAD.start()
    return automation_status()


def stop_automation() -> dict[str, Any]:
    _AUTOMATION_STOP.set()
    _stop_operator_observer()
    with _AUTOMATION_LOCK:
        _AUTOMATION["running"] = False
        _AUTOMATION["stage"] = "STOPPED"
        _AUTOMATION["detail"] = "Ground service automation stopped"
        _AUTOMATION["updated_at"] = _utc()
    _record("AUTO", "Ground service automation stopped")
    return automation_status()


def release_control() -> dict[str, Any]:
    official = _official_status(force=True)
    if official.get("reachable"):
        _official_command("menu.close", timeout=0.5)
    if os.getenv("OPSROOM_GSX_MOCK") == "1":
        _record("RELEASE", "GSX external menu control released")
        return {"ok": True}
    diagnostics = simconnect_diagnostics()
    with SIM_LOCK:
        sm, _aq = _ensure_session(diagnostics)
        _write_value(sm, LVAR["menu_open"], 0)
        _send_sim_event(sm, "EXTERNAL_SYSTEM_TOGGLE", 1)
    _record("RELEASE", "GSX external menu control released")
    _invalidate()
    return {"ok": True}
