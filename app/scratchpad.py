from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .settings_store import app_data_dir

SCRATCHPAD_DIR = "scratchpad"
MAX_PAYLOAD_BYTES = 2_500_000
PAGE_IDS = {"departure", "arrival", "blank"}

DEFAULT_FIELDS: dict[str, str] = {
    "callsign": "",
    "aircraft": "",
    "departure": "",
    "destination": "",
    "flight_level": "",
    "route": "",
    "ramp_position": "",
    "atis": "",
    "runway": "",
    "initial_altitude": "",
    "sid_transition": "",
    "departure_frequency": "",
    "squawk": "",
    "taxi": "",
    "metar": "",
    "notes": "",
    "blank_text": "",
}


def _dir() -> Path:
    path = app_data_dir() / SCRATCHPAD_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _page_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_-]", "", str(value or "").strip().lower())[:40]
    return normalized if normalized in PAGE_IDS else "departure"


def _page_path(page_id: str) -> Path:
    return _dir() / f"{_page_id(page_id)}.json"


def _default_page(page_id: str) -> dict[str, Any]:
    page_id = _page_id(page_id)
    return {
        "ok": True,
        "page_id": page_id,
        "mode": "blank" if page_id == "blank" else "template",
        "fields": dict(DEFAULT_FIELDS),
        "strokes": [],
        "updated_at": None,
        "schema": 1,
    }


def _sanitize_fields(raw: Any) -> dict[str, str]:
    fields = dict(DEFAULT_FIELDS)
    if isinstance(raw, dict):
        for key in fields:
            if key in raw:
                fields[key] = str(raw.get(key) or "")[:12000]
    return fields


def _sanitize_strokes(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for stroke in raw[:3000]:
        if not isinstance(stroke, dict):
            continue
        tool = str(stroke.get("tool") or "pen").lower()
        if tool not in {"pen", "eraser"}:
            tool = "pen"
        try:
            width = float(stroke.get("width") or 3)
        except (TypeError, ValueError):
            width = 3.0
        points = []
        for point in stroke.get("points") or []:
            if not isinstance(point, dict):
                continue
            try:
                x = max(0.0, min(1.0, float(point.get("x"))))
                y = max(0.0, min(1.0, float(point.get("y"))))
            except (TypeError, ValueError):
                continue
            points.append({"x": round(x, 5), "y": round(y, 5)})
            if len(points) >= 3000:
                break
        if len(points) >= 1:
            cleaned.append({"tool": tool, "width": max(1.0, min(width, 48.0)), "points": points})
    return cleaned


def scratchpad_get_page(page_id: str) -> dict[str, Any]:
    page_id = _page_id(page_id)
    path = _page_path(page_id)
    if not path.exists():
        return _default_page(page_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return _default_page(page_id)
    page = _default_page(page_id)
    if isinstance(data, dict):
        page["mode"] = "blank" if str(data.get("mode") or page["mode"]).lower() == "blank" else "template"
        page["fields"] = _sanitize_fields(data.get("fields"))
        page["strokes"] = _sanitize_strokes(data.get("strokes"))
        page["updated_at"] = data.get("updated_at") or None
    return page


def scratchpad_save_page(page_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    page_id = _page_id(page_id)
    mode = "blank" if str((payload or {}).get("mode") or "").lower() == "blank" or page_id == "blank" else "template"
    page = {
        "ok": True,
        "page_id": page_id,
        "mode": mode,
        "fields": _sanitize_fields((payload or {}).get("fields")),
        "strokes": _sanitize_strokes((payload or {}).get("strokes")),
        "updated_at": _now(),
        "schema": 1,
    }
    encoded = json.dumps(page, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        # Keep text, drop oldest strokes until the page is under the limit.
        while page["strokes"] and len(json.dumps(page, ensure_ascii=False).encode("utf-8")) > MAX_PAYLOAD_BYTES:
            page["strokes"].pop(0)
    path = _page_path(page_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(page, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return page


def scratchpad_clear_page(page_id: str) -> dict[str, Any]:
    page_id = _page_id(page_id)
    try:
        _page_path(page_id).unlink(missing_ok=True)
    except OSError:
        pass
    return _default_page(page_id)


def scratchpad_status() -> dict[str, Any]:
    pages = [scratchpad_get_page(pid) for pid in ("departure", "arrival", "blank")]
    return {"ok": True, "pages": pages, "storage_path": str(_dir())}
