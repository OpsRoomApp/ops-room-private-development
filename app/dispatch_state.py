from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from .settings_store import app_data_dir

_LOCK = Lock()
_FILE = "dispatch_selection.json"


def _path():
    return app_data_dir() / _FILE


def get_active_dispatch() -> dict[str, Any] | None:
    path = _path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        route = data.get("route")
        return deepcopy(route) if isinstance(route, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def set_active_dispatch(route: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(route, dict):
        raise ValueError("Route selection must be an object")
    origin = str(route.get("origin") or "").strip().upper()
    destination = str(route.get("destination") or "").strip().upper()
    if len(origin) < 3 or len(destination) < 3 or origin == destination:
        raise ValueError("A valid origin and destination are required")
    selected = deepcopy(route)
    selected["origin"] = origin
    selected["destination"] = destination
    selected["selected_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {"route": selected}
    path = _path()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return selected
