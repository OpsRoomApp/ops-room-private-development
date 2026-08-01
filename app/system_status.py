from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from .data_loader import logo_status, nearest_airport, stand_sources_status
from .settings_store import load_settings
from .simbrief_client import status as simbrief_status
from .simconnect_position import simconnect_diagnostics
from .telemetry_provider import read_telemetry, telemetry_diagnostics, reselect_telemetry
from .vpilot_bridge import bridge_status
from .vpilot_installer import bridge_installation_status


def detect_gsx_root(configured: str = "") -> dict[str, Any]:
    candidates: list[Path] = []
    if configured.strip():
        candidates.append(Path(configured.strip()))

    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\FSDreamTeam") as key:
                root, _ = winreg.QueryValueEx(key, "root")
                if root:
                    candidates.append(Path(str(root)))
        except OSError:
            pass

    candidates.append(Path(r"C:\Program Files (x86)\Addon Manager"))
    checked: list[str] = []
    for candidate in candidates:
        text = str(candidate)
        if text.lower() in {item.lower() for item in checked}:
            continue
        checked.append(text)
        gsx_package = candidate / "MSFS" / "fsdreamteam-gsx-pro"
        menu_file = gsx_package / "html_ui" / "InGamePanels" / "FSDT_GSX_Panel" / "menu"
        if gsx_package.exists():
            return {
                "detected": True,
                "root": text,
                "package": str(gsx_package),
                "menu_file": str(menu_file),
                "menu_file_exists": menu_file.exists(),
            }
    return {"detected": False, "root": None, "checked": checked}


def process_running(image_name: str) -> bool:
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


@lru_cache(maxsize=1)
def asset_summary() -> dict[str, Any]:
    return {"logos": logo_status(), "stands": stand_sources_status()}


def build_system_summary(probe_simconnect: bool = False) -> dict[str, Any]:
    settings = load_settings()
    sim_diag = simconnect_diagnostics()
    # Routine status refreshes use the short telemetry cache. The user-facing
    # Reconnect/Probe action performs a genuine provider reselection, testing
    # preferred FSUIPC first and retaining SimConnect only when FSUIPC is not healthy.
    position = reselect_telemetry("Status Board reconnect") if probe_simconnect else read_telemetry(force=False)
    gsx = detect_gsx_root(settings["integrations"].get("gsx_root", ""))
    vpilot_running = process_running("vPilot.exe")
    bridge = bridge_status()
    bridge_install = bridge_installation_status()
    assets = asset_summary()
    sb = simbrief_status(settings["identity"].get("simbrief_user_id", ""))

    sim_connected = bool(position and position.get("ok"))
    sim_reason = None if sim_connected else (position or {}).get("reason")
    nearest_code = None
    if sim_connected:
        nearest = nearest_airport(float(position["lat"]), float(position["lon"]))
        if nearest:
            nearest_code = nearest[0].ident
    telemetry_diag = telemetry_diagnostics(False)
    fsuipc_diag = telemetry_diag.get("fsuipc") if isinstance(telemetry_diag.get("fsuipc"), dict) else {}
    if sim_connected:
        telemetry_detail = "Live simulator telemetry"
    elif fsuipc_diag.get("process_running") and not fsuipc_diag.get("python_bridge_available"):
        telemetry_detail = "FSUIPC7.exe is running, but the pyuipc bridge is missing from OPS ROOM runtime"
    elif fsuipc_diag.get("process_running") and fsuipc_diag.get("last_error"):
        telemetry_detail = "FSUIPC7.exe is running, IPC not open: " + str(fsuipc_diag.get("last_error"))[:120]
    else:
        telemetry_detail = str((position or {}).get("reason") or "Waiting for Microsoft Flight Simulator")[:140]
    return {
        "version": "0.25.55",
        "position": position if sim_connected else None,
        "nearest_airport": nearest_code,
        "product": "OPS ROOM",
        "subtitle": "OPERATIONS CONTROL CENTRE",
        "integrations": {
            "msfs": {
                "state": "connected" if sim_connected else "standby",
                "label": "CONNECTED" if sim_connected else "STANDBY",
                "detail": telemetry_detail if not sim_connected else "Live simulator telemetry",
                "diagnostics": {"simconnect": sim_diag, "telemetry": telemetry_diag},
            },
            "telemetry": {
                "state": "connected" if sim_connected else "standby",
                "label": str(position.get("source") or "UNAVAILABLE").upper() if sim_connected else "UNAVAILABLE",
                "detail": telemetry_detail,
                "diagnostics": telemetry_diag,
            },
            "vatsim": {
                "state": "configured" if settings["identity"].get("vatsim_cid") else "unconfigured",
                "label": "CID SET" if settings["identity"].get("vatsim_cid") else "NOT SET",
            },
            "simbrief": sb,
            "vpilot": {
                "state": "connected" if bridge.get("connected") else ("running" if vpilot_running else "standby"),
                "label": "BRIDGE ONLINE" if bridge.get("connected") else ("RESTART VPILOT" if bridge_install.get("installed") else "BRIDGE NOT INSTALLED"),
                "detail": "",
                "diagnostics": {"bridge": bridge, "installation": bridge_install},
            },
            "hoppie": {
                "state": "configured" if settings["integrations"].get("hoppie_configured") else "unconfigured",
                "label": "CODE SAVED" if settings["integrations"].get("hoppie_configured") else "NOT SET",
            },
            "gsx": {
                "state": "detected" if gsx.get("detected") else "standby",
                "label": "DETECTED" if gsx.get("detected") else "NOT DETECTED",
                "detail": "",
                "diagnostics": gsx,
            },
        },
        "assets": assets,
        "settings": {"interface": settings.get("interface", {}), "integrations": {"hoppie_configured": settings.get("integrations", {}).get("hoppie_configured", False)}},
        "settings_path": str((Path(os.getenv("LOCALAPPDATA") or Path.home()) / "Ops Room" / "settings.json")),
    }
