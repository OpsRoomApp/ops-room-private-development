from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .settings_store import load_settings

PLUGIN_NAME = "OpsRoom.VPilotBridge.dll"
API_NAME = "RossCarlson.Vatsim.Vpilot.Plugins.dll"
SOURCE_NAME = "OPSROOM.VPilotBridge.cs"


def _process_running(image_name: str) -> bool:
    if os.name != "nt":
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/NH"],
            capture_output=True,
            text=True,
            timeout=2,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return image_name.lower() in result.stdout.lower()
    except Exception:
        return False


def _vpilot_roots() -> list[Path]:
    settings = load_settings()
    configured = str(settings.get("integrations", {}).get("vpilot_root") or "").strip()
    roots: list[Path] = []
    if configured:
        roots.append(Path(os.path.expandvars(configured.strip().strip(chr(34)))))
    local = os.getenv("LOCALAPPDATA")
    if local:
        roots.append(Path(local) / "vPilot")
    # Preserve order while deduplicating.
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root).lower()
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _find_api(root: Path) -> Path | None:
    direct = root / API_NAME
    if direct.is_file():
        return direct
    for candidate in (root / "bin" / API_NAME, root / "Plugins" / API_NAME):
        if candidate.is_file():
            return candidate
    try:
        return next(root.glob(f"**/{API_NAME}"), None)
    except OSError:
        return None


def _source_path() -> Path | None:
    candidates = [
        Path(__file__).resolve().parent.parent / "vpilot_plugin" / SOURCE_NAME,
        Path(sys.executable).resolve().parent / "vpilot_plugin" / SOURCE_NAME,
    ]
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        candidates.append(Path(mei) / "vpilot_plugin" / SOURCE_NAME)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _compiler_candidates() -> list[Path]:
    if os.name != "nt":
        return []
    windows = Path(os.getenv("WINDIR") or r"C:\Windows")
    return [
        windows / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe",
        windows / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe",
    ]


def _reference_candidates(name: str) -> list[Path]:
    paths: list[Path] = []
    windows = Path(os.getenv("WINDIR") or r"C:\Windows")
    paths.extend([
        windows / "Microsoft.NET" / "Framework" / "v4.0.30319" / name,
        windows / "Microsoft.NET" / "Framework64" / "v4.0.30319" / name,
    ])
    program_x86 = Path(os.getenv("ProgramFiles(x86)") or r"C:\Program Files (x86)")
    ref_root = program_x86 / "Reference Assemblies" / "Microsoft" / "Framework" / ".NETFramework"
    if ref_root.exists():
        for folder in sorted(ref_root.glob("v4.*"), reverse=True):
            paths.append(folder / name)
    return paths


def _find_reference(name: str) -> Path | None:
    return next((path for path in _reference_candidates(name) if path.is_file()), None)


def bridge_installation_status() -> dict[str, Any]:
    checked: list[str] = []
    for root in _vpilot_roots():
        checked.append(str(root))
        api = _find_api(root) if root.exists() else None
        plugin = root / "Plugins" / PLUGIN_NAME
        if root.exists() or api:
            return {
                "ok": True,
                "supported": os.name == "nt",
                "vpilot_root": str(root),
                "api_path": str(api) if api else None,
                "api_found": bool(api),
                "plugin_path": str(plugin),
                "installed": plugin.is_file(),
                "vpilot_running": _process_running("vPilot.exe"),
                "source_found": bool(_source_path()),
                "checked": checked,
            }
    fallback = _vpilot_roots()[0] if _vpilot_roots() else Path("vPilot")
    return {
        "ok": True,
        "supported": os.name == "nt",
        "vpilot_root": str(fallback),
        "api_path": None,
        "api_found": False,
        "plugin_path": str(fallback / "Plugins" / PLUGIN_NAME),
        "installed": False,
        "vpilot_running": _process_running("vPilot.exe"),
        "source_found": bool(_source_path()),
        "checked": checked,
    }


def install_bridge() -> dict[str, Any]:
    status = bridge_installation_status()
    if os.name != "nt":
        return {**status, "ok": False, "reason": "The vPilot bridge can only be built and installed on Windows."}
    root = Path(str(status.get("vpilot_root") or ""))
    api_value = status.get("api_path")
    api = Path(str(api_value)) if api_value else None
    source = _source_path()
    compiler = next((path for path in _compiler_candidates() if path.is_file()), None)
    web_extensions = _find_reference("System.Web.Extensions.dll")
    net_http = _find_reference("System.Net.Http.dll")
    missing = []
    if not root.exists(): missing.append("vPilot installation")
    if not api or not api.is_file(): missing.append(API_NAME)
    if not source: missing.append(SOURCE_NAME)
    if not compiler: missing.append(".NET Framework C# compiler")
    if not web_extensions: missing.append("System.Web.Extensions.dll")
    if not net_http: missing.append("System.Net.Http.dll")
    if missing:
        return {**status, "ok": False, "reason": "Missing: " + ", ".join(missing)}

    plugins = root / "Plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    target = plugins / PLUGIN_NAME
    with tempfile.TemporaryDirectory(prefix="opsroom-vpilot-") as tmp:
        output = Path(tmp) / PLUGIN_NAME
        command = [
            str(compiler), "/nologo", "/target:library", "/optimize+", "/platform:anycpu",
            f"/out:{output}", f"/reference:{api}", f"/reference:{web_extensions}", f"/reference:{net_http}", str(source),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0 or not output.is_file():
            detail = (result.stdout + "\n" + result.stderr).strip()
            return {**status, "ok": False, "reason": "Bridge compilation failed", "compiler_output": detail[-8000:]}
        try:
            shutil.copy2(output, target)
        except PermissionError:
            return {**status, "ok": False, "reason": "vPilot is using the existing bridge. Close vPilot, then install again.", "restart_required": True}

    updated = bridge_installation_status()
    return {
        **updated,
        "ok": True,
        "installed": True,
        "restart_required": bool(updated.get("vpilot_running")),
        "message": "Bridge installed. Restart vPilot to load it." if updated.get("vpilot_running") else "Bridge installed. Start vPilot to load it.",
    }


def remove_bridge() -> dict[str, Any]:
    status = bridge_installation_status()
    target = Path(str(status.get("plugin_path") or ""))
    if not target.is_file():
        return {**status, "ok": True, "installed": False, "message": "Bridge is not installed."}
    try:
        target.unlink()
    except PermissionError:
        return {**status, "ok": False, "reason": "Close vPilot before removing the bridge.", "restart_required": True}
    return {**bridge_installation_status(), "ok": True, "installed": False, "message": "Bridge removed."}
