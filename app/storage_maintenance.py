from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .settings_store import app_data_dir


def _size(path: Path) -> int:
    try:
        if path.is_file():
            return path.stat().st_size
        total = 0
        for item in path.rglob("*"):
            try:
                if item.is_file():
                    total += item.stat().st_size
            except OSError:
                continue
        return total
    except OSError:
        return 0


def _remove_contents(path: Path) -> int:
    removed = 0
    if not path.exists():
        return removed
    for item in path.iterdir():
        try:
            removed += _size(item)
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
        except OSError:
            continue
    return removed


def storage_status() -> dict[str, Any]:
    base = app_data_dir()
    items = {
        "logs": base / "logs",
        "diagnostics": base / "diagnostics",
        "map_cache": base / "map_cache",
        "logbook": base / "logbook.sqlite3",
    }
    details = {name: {"path": str(path), "bytes": _size(path)} for name, path in items.items()}
    return {
        "ok": True,
        "app_data_dir": str(base),
        "items": details,
        "total_bytes": sum(item["bytes"] for item in details.values()),
    }


def clear_local_logs_cache(*, logs: bool = True, diagnostics: bool = True, map_cache: bool = False) -> dict[str, Any]:
    base = app_data_dir()
    removed: dict[str, int] = {}
    if logs:
        removed["logs"] = _remove_contents(base / "logs")
    if diagnostics:
        removed["diagnostics"] = _remove_contents(base / "diagnostics")
    if map_cache:
        removed["map_cache"] = _remove_contents(base / "map_cache")
    return {"ok": True, "removed": removed, "removed_bytes": sum(removed.values()), "status": storage_status()}
