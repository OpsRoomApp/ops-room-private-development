from __future__ import annotations

import atexit
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .settings_store import app_data_dir

STATUS_FILE = "camera_bridge_2024_status.json"
LOG_FILE = "camera_bridge_2024.log"
BRIDGE_EXE = "OPS ROOM Camera Bridge 2024.exe"
_PROCESS: subprocess.Popen | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_path() -> Path:
    path = app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path / LOG_FILE


def _status_path() -> Path:
    return app_data_dir() / STATUS_FILE


def _candidate_paths() -> list[Path]:
    """Return every place the bridge EXE can reasonably live.

    This is intentionally broad because public-beta users may run OPS ROOM as:
    - a PyInstaller one-folder package,
    - a PyInstaller one-file extraction,
    - a source/project checkout,
    - or a manually copied Camera Bridge beside OPS ROOM.exe.
    """
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    roots.append(Path.cwd())
    roots.append(Path(__file__).resolve().parents[1])
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))

    candidates: list[Path] = []
    for root in roots:
        candidates.extend([
            root / BRIDGE_EXE,
            root / "bin" / BRIDGE_EXE,
            root / "camera_bridge_2024" / BRIDGE_EXE,
            root / "camera_bridge_2024" / "build" / "Release" / BRIDGE_EXE,
            root / "camera_bridge_2024" / "build" / BRIDGE_EXE,
            root / "_internal" / BRIDGE_EXE,
            root / "_internal" / "camera_bridge_2024" / BRIDGE_EXE,
            root / "_internal" / "camera_bridge_2024" / "build" / "Release" / BRIDGE_EXE,
        ])
    # Preserve order, remove duplicates.
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def _bridge_path() -> Path | None:
    for candidate in _candidate_paths():
        if candidate.exists():
            return candidate
    return None


def _process_running() -> bool:
    global _PROCESS
    if _PROCESS is not None:
        if _PROCESS.poll() is None:
            return True
        _PROCESS = None
    return False


def _read_status() -> dict[str, Any]:
    path = _status_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}



def _write_status(state: str, message: str, running: bool = False) -> None:
    payload = {
        "updated_at": _now(),
        "running": bool(running),
        "state": state,
        "message": message,
        "target": "",
        "match": "",
    }
    try:
        path = _status_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass


def _taskkill_bridge_processes() -> None:
    """Best-effort cleanup for orphaned bridge processes on Windows.

    The MSFS 2024 Camera Bridge is an external helper EXE. If OPS ROOM exits
    before the Python Popen handle is cleaned up, or if the handle was lost after
    a restart, the bridge can remain in Task Manager. Use taskkill as a final
    safety net during explicit Stop/Release and application shutdown.
    """
    if os.name != "nt":
        return
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/IM", BRIDGE_EXE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        pass

def bridge_status() -> dict[str, Any]:
    bridge = _bridge_path()
    status = _read_status()
    process_running = _process_running()
    status_running = bool(status.get("running"))
    return {
        "ok": True,
        "mode": "legacy_external_camera_bridge",
        "external_exe": True,
        "native_wasm_disabled": True,
        "available": bool(bridge),
        "path": str(bridge) if bridge else "",
        "running": bool(process_running or status_running),
        "process_owned_by_opsroom": process_running,
        "status": status,
        "log_path": str(_log_path()),
        "status_path": str(_status_path()),
        "message": status.get("message") or ("Legacy Camera Bridge ready" if bridge else "OPS ROOM Camera Bridge 2024.exe was not found in the app folder. Build it or place it beside OPS ROOM.exe."),
    }


def start_bridge() -> dict[str, Any]:
    global _PROCESS
    bridge = _bridge_path()
    if not bridge:
        checked = [str(p) for p in _candidate_paths()]
        return {
            "ok": False,
            "available": False,
            "running": False,
            "error": "OPS ROOM Camera Bridge 2024.exe was not found. Build the camera bridge and place it beside OPS ROOM.exe or under camera_bridge_2024\\build\\Release.",
            "checked_paths": checked,
        }
    if _process_running():
        data = bridge_status()
        data["ok"] = True
        data["message"] = data.get("message") or "Camera Bridge is already running."
        return data
    env = os.environ.copy()
    env.setdefault("OPSROOM_CAMERA_TARGET_URL", "http://127.0.0.1:8080/api/camera/target")
    env.setdefault("OPSROOM_CAMERA_STATUS_PATH", str(_status_path()))
    env.setdefault("OPSROOM_CAMERA_LOG_PATH", str(_log_path()))
    try:
        _PROCESS = subprocess.Popen([str(bridge)], cwd=str(bridge.parent), env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as exc:
        return {"ok": False, "available": True, "running": False, "path": str(bridge), "error": str(exc)}
    data = bridge_status()
    data["ok"] = True
    data["message"] = "Camera Bridge start command sent. It may show WAITING SIMCONNECT until MSFS 2024 is loaded into a flight."
    return data


def stop_bridge() -> dict[str, Any]:
    global _PROCESS
    stopped_owned = False
    if _PROCESS is not None and _PROCESS.poll() is None:
        try:
            _PROCESS.terminate()
            try:
                _PROCESS.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    _PROCESS.kill()
                    _PROCESS.wait(timeout=2)
                except Exception:
                    pass
            stopped_owned = True
        except Exception:
            try:
                os.kill(_PROCESS.pid, signal.SIGTERM)
                stopped_owned = True
            except Exception:
                pass
    _PROCESS = None

    # Public beta safeguard: if the bridge was orphaned, the Popen handle may no
    # longer exist even though the EXE is still running. Clean it up so closing
    # OPS ROOM or pressing Stop does not leave the helper in Task Manager.
    _taskkill_bridge_processes()
    _write_status(
        "STOPPED",
        "Camera Bridge stopped by OPS ROOM." if stopped_owned else "Camera Bridge cleanup completed by OPS ROOM.",
        running=False,
    )
    return bridge_status()



def cleanup_on_exit() -> None:
    try:
        stop_bridge()
    except Exception:
        pass


atexit.register(cleanup_on_exit)

def log_tail(lines: int = 120) -> dict[str, Any]:
    path = _log_path()
    if not path.exists():
        return {"ok": True, "lines": [], "path": str(path)}
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 96_000), os.SEEK_SET)
            text = handle.read().decode("utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "error": str(exc), "path": str(path)}
    return {"ok": True, "lines": text.splitlines()[-max(20, min(int(lines), 800)):], "path": str(path)}
