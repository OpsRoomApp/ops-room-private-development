from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

_LOCK = threading.RLock()
_ITEMS: list[dict[str, Any]] = []
_MAX = 300


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def publish(source: str, title: str, message: str, *, priority: str = "operational", page: str = "status", tag: str = "", persistent: bool = False) -> dict[str, Any]:
    item = {
        "id": f"{int(time.time()*1000)}-{uuid.uuid4().hex[:8]}",
        "time": _utc_now(),
        "source": str(source or "OPS ROOM").upper()[:40],
        "title": str(title or "NOTIFICATION")[:100],
        "message": str(message or "")[:600],
        "priority": priority if priority in {"information", "operational", "atc", "critical"} else "operational",
        "page": str(page or "status")[:30],
        "tag": str(tag or "")[:80],
        "persistent": bool(persistent),
    }
    with _LOCK:
        if tag:
            for existing in reversed(_ITEMS[-50:]):
                if existing.get("tag") == tag and existing.get("title") == item["title"]:
                    return existing
        _ITEMS.append(item)
        del _ITEMS[:-_MAX]
    return item


def status(after: str = "", limit: int = 100) -> dict[str, Any]:
    with _LOCK:
        items = list(_ITEMS)
    if after:
        found = False
        selected = []
        for item in items:
            if found:
                selected.append(item)
            elif item.get("id") == after:
                found = True
        if not found:
            selected = items[-limit:]
    else:
        selected = items[-limit:]
    return {"ok": True, "items": selected[-max(1, min(int(limit), 300)):], "latest_id": items[-1]["id"] if items else None}
