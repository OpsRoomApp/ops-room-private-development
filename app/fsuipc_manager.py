from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from .settings_store import load_settings

COMMON_PATHS = [
    Path(r"C:\FSUIPC7\FSUIPC7.exe"),
    Path(r"C:\Program Files\FSUIPC7\FSUIPC7.exe"),
    Path(r"C:\Program Files (x86)\FSUIPC7\FSUIPC7.exe"),
]


def _is_running() -> bool:
    if os.name != "nt":
        return False
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq FSUIPC7.exe"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return "FSUIPC7.exe" in out
    except Exception:
        return False


def close_fsuipc7(force: bool = False, timeout_seconds: float = 8.0) -> dict[str, Any]:
    """Close FSUIPC7 from OPS ROOM.

    This is intentionally separate from autostart and should only be called from
    an opt-in sim-close guard. It first sends a normal taskkill (WM_CLOSE style)
    and only uses /F when force=True.
    """
    if os.name != "nt":
        return {"ok": True, "closed": False, "reason": "FSUIPC close is Windows-only"}
    if not _is_running():
        return {"ok": True, "closed": False, "running": False, "reason": "FSUIPC7 is not running"}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.run(["taskkill", "/IM", "FSUIPC7.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, creationflags=flags)
        deadline = time.monotonic() + max(1.0, float(timeout_seconds or 8.0))
        while time.monotonic() < deadline:
            if not _is_running():
                return {"ok": True, "closed": True, "forced": False}
            time.sleep(0.25)
        if force:
            subprocess.run(["taskkill", "/F", "/IM", "FSUIPC7.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, creationflags=flags)
            return {"ok": True, "closed": not _is_running(), "forced": True}
        return {"ok": False, "closed": False, "forced": False, "reason": "FSUIPC7 did not exit after close request"}
    except Exception as exc:
        return {"ok": False, "closed": False, "reason": f"{type(exc).__name__}: {exc}"}


def _candidate_paths() -> list[Path]:
    settings = load_settings().get("integrations", {})
    paths: list[Path] = []
    user = str(settings.get("fsuipc_path") or "").strip()
    if user:
        paths.append(Path(user).expanduser())
    for base in (os.getenv("PROGRAMFILES"), os.getenv("PROGRAMFILES(X86)"), os.getenv("LOCALAPPDATA")):
        if base:
            paths.append(Path(base) / "FSUIPC7" / "FSUIPC7.exe")
    paths.extend(COMMON_PATHS)
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path).lower()
        if key not in seen:
            seen.add(key); result.append(path)
    return result


def locate_fsuipc() -> Path | None:
    for path in _candidate_paths():
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def autostart_if_configured() -> dict[str, Any]:
    settings = load_settings().get("integrations", {})
    if not settings.get("fsuipc_enabled", True) or not settings.get("fsuipc_autostart", True):
        return {"ok": True, "started": False, "reason": "FSUIPC autostart disabled"}
    if os.name != "nt":
        return {"ok": True, "started": False, "reason": "FSUIPC autostart is Windows-only"}
    if _is_running():
        return {"ok": True, "started": False, "running": True, "reason": "FSUIPC7 already running"}
    path = locate_fsuipc()
    if not path:
        return {"ok": True, "started": False, "reason": "FSUIPC7 not found"}
    try:
        subprocess.Popen(
            [str(path)],
            cwd=str(path.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)),
        )
        return {"ok": True, "started": True, "path": str(path)}
    except Exception as exc:
        return {"ok": False, "started": False, "reason": f"{type(exc).__name__}: {exc}", "path": str(path)}
