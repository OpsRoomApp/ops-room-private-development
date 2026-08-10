from __future__ import annotations

import base64
import ctypes
import json
import os
import tempfile
import time
from copy import deepcopy
from ctypes import wintypes
from pathlib import Path
from typing import Any

APP_DIR_NAME = "Ops Room"
SETTINGS_FILE = "settings.json"
SECRETS_FILE = "secrets.json"

_SETTINGS_CACHE: dict[str, Any] | None = None
_SETTINGS_CACHE_TIME: float = 0.0

DEFAULT_SETTINGS: dict[str, Any] = {
    "identity": {
        "vatsim_cid": "",
        "simbrief_user_id": "",
    },
    "integrations": {
        "gsx_root": "",
        "gsx_remote_url": "",
        "gsx_remote_port": 8744,
        "vpilot_root": "",
        "hoppie_configured": False,
        "simbrief_auto_load": True,
        "announcements_enabled": False,
        "announcements_root": "",
        "announcements_volume": 80,
        "announcements_callsign_override": "",
        "announcements_airline_override": "",
        "announcements_hotkeys_enabled": True,
        "announcements_pause_hotkey": "CTRL+ALT+P",
        "announcements_mute_hotkey": "CTRL+ALT+M",
        "camera_volume_enabled": True,
        "camera_volume_cockpit": 100,
        "camera_volume_cabin": 70,
        "camera_volume_external": 40,
        "gsx_automation_enabled": True,
        "gsx_auto_pushback": False,
        "gsx_auto_prepare_after_services": True,
        "gsx_prepare_on_beacon": False,
        "gsx_departure_boarding": True,
        "gsx_departure_baggage": True,
        "gsx_departure_refuel": True,
        "gsx_departure_catering": True,
        "gsx_departure_water": True,
        "gsx_departure_cleaning": False,
        "gsx_departure_lavatory": False,
        "gsx_fenix_open_menu_handoff": False,
        "gsx_arrival_deboarding": True,
        "gsx_arrival_unload": True,
        "gsx_arrival_cleaning": True,
        "gsx_arrival_lavatory": True,
        "gsx_arrival_water": False,
        "gsx_arrival_catering": False,
        "gsx_arrival_refuel": False,
        "hoppie_callsign_override": "",
        "hoppie_auto_poll": True,
        "map_online_enabled": True,
        "fsuipc_enabled": True,
        "fsuipc_autostart": True,
        "fsuipc_path": "",
        "telemetry_sample_seconds": 1.0,
        "telemetry_high_rate_seconds": 0.05,
        "black_box_enabled": True,
        "black_box_auto_record": True,
        "black_box_max_hz": 30,
        "black_box_simconnect_max_hz": 30,
        "black_box_replay_fps": 30,
        "aip_charts_enabled": True,
        "openaip_map_enabled": True,
        "openaip_api_key": "",
        "openaip_proxy_url": "",
        "openaip_proxy_token": "",
        "local_surface_db_auto_detect": True,
        "local_surface_db_path": "",
        "chartfox_enabled": True,
        "chartfox_embed_enabled": True,
        "chartfox_api_enabled": False,
        "chartfox_api_base_url": "",
        "chartfox_api_key": "",
        "chartfox_oauth_client_id": "",
        "chartfox_oauth_client_secret": "",
        "chartfox_oauth_redirect_uri": "",
        "raas_voice_path": "",
        "raas_unit": "ft",
        "raas_notam_callouts": True,
        "notam_notifications": True,
        "simobjects_notam_markers": False,
        "marker_radius_nm": 50.0,
        "marker_altitude_gate_ft": 15000.0,
    },
    "server": {
        "lan_access": True,
        "port": 8080,
        "device_security_enabled": False,
        "pairing_code": "",
        "trusted_device_days": 180,
    },
    "bug_report": {
        "enabled": True,
        "provider": "google_apps_script",
        "endpoint": "https://script.google.com/macros/s/AKfycbww__VDAulz5xGlg40osNfNjoho_Xus0TcFK6HUk_mbIOrsBlxrYDt_5d_sUOfboxaJ/exec",
        "secret": "e7eb1adf7e094220a3f5ad89fcf6d01ce4194a0fe4b2452f9415b97d808bbbab",
        "max_log_lines": 500,
        "include_diagnostics_zip": True,
    },
    "printing": {
        "enabled": False,
        "printer_name": "",
        "cpdlc_auto_print": True,
        "network_auto_print": False,
        "paper_width_mm": 80,
    },
    "updates": {
        "enabled": True,
        "check_on_startup": True,
        "manifest_url": "https://opsroom.live/api/update.json",
    },
    "interface": {
        "start_page": "status",
        "accent": "cyan",
        "compact": False,
        "notifications": True,
        "notification_sound": True,
        "native_notifications": True,
        "important_notifications_only": True,
        "airline_theme_enabled": True,
        "airline_theme_mode": "full",
        "airline_theme_intensity": 38,
        "airline_branding_enabled": True,
        "airline_icao_override": "",
        "setup_completed": False,
        "streamer_mode": False,
        "finance_career_enabled": True,
        "units": {
            "weight": "kg",
            "distance": "nm",
            "altitude": "ft",
            "speed": "kt",
            "vertical_speed": "fpm",
        },
        "module_visibility": {
            "status": True, "fids": True, "dispatch": True, "briefing": True, "scratchpad": True,
            "watch": True, "performance": True, "raas": True, "network": True, "map": True,
            "datalink": True, "ground": True, "announcer": True, "procedures": True,
            "logbook": True, "blackbox": True, "finances": True, "obs": True, "system": True
        },
    },
}


def app_data_dir() -> Path:
    local = os.getenv("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / ".local" / "share"
    path = base / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _merge(default: Any, incoming: Any) -> Any:
    if isinstance(default, dict):
        result = deepcopy(default)
        if isinstance(incoming, dict):
            for key, value in incoming.items():
                result[key] = _merge(default.get(key), value) if key in default else value
        return result
    return incoming if incoming is not None else deepcopy(default)


def _migrate_lan_access(normalized: dict[str, Any]) -> bool:
    """#39: LAN / tablet access defaults ON, including first-time setup.

    Flips an old stored ``False`` to ``True`` unless the user has explicitly
    chosen OFF through the host setup UI (recorded as ``lan_access_user_off``).
    Returns True when flipped.

    The earlier ``lan_access_migrated`` marker was flawed: it was set in memory
    during ``load_settings`` and could then be persisted alongside a ``False``
    value, permanently disabling the flip (verified live — settings.json held
    ``lan_access: False`` with ``lan_access_migrated: True`` and the checkbox
    stayed disabled forever). The marker is now written only together with the
    flipped ``True`` value, and a ``False`` value is always re-flipped unless
    the user explicitly saved OFF.
    """
    server = normalized.setdefault("server", {})
    if server.get("lan_access_user_off") is True:
        server.pop("lan_access_migrated", None)
        return False
    if server.get("lan_access") is False:
        server["lan_access"] = True
        server["lan_access_migrated"] = True
        return True
    return False


def load_settings() -> dict[str, Any]:
    global _SETTINGS_CACHE, _SETTINGS_CACHE_TIME
    now = time.monotonic()
    if _SETTINGS_CACHE is not None and (now - _SETTINGS_CACHE_TIME) < 2.0:
        return _SETTINGS_CACHE
    path = app_data_dir() / SETTINGS_FILE
    if not path.exists():
        result = deepcopy(DEFAULT_SETTINGS)
        _SETTINGS_CACHE = result
        _SETTINGS_CACHE_TIME = now
        return result
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        result = _merge(DEFAULT_SETTINGS, raw)
        # #39: LAN / tablet access defaults ON. Apply the migration on every
        # load and persist the flipped value immediately, so a stale file that
        # already holds the old marker can never lock the checkbox off again.
        # (Verified live: settings.json had lan_access False + migrated True.)
        if _migrate_lan_access(result):
            try:
                target = app_data_dir() / SETTINGS_FILE
                target.parent.mkdir(parents=True, exist_ok=True)
                fd, temp_name = tempfile.mkstemp(prefix="settings-", suffix=".tmp", dir=str(target.parent))
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        json.dump(result, handle, indent=2, ensure_ascii=False)
                        handle.write("\n")
                    os.replace(temp_name, target)
                finally:
                    try:
                        if os.path.exists(temp_name):
                            os.unlink(temp_name)
                    except OSError:
                        pass
            except Exception:
                pass
        _SETTINGS_CACHE = result
        _SETTINGS_CACHE_TIME = now
        return result
    except (OSError, ValueError, TypeError):
        result = deepcopy(DEFAULT_SETTINGS)
        _SETTINGS_CACHE = result
        _SETTINGS_CACHE_TIME = now
        return result


def save_settings(settings: dict[str, Any]) -> dict[str, Any]:
    normalized = _merge(DEFAULT_SETTINGS, settings)
    port = normalized.get("server", {}).get("port", 8080)
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = 8080
    normalized["server"]["port"] = max(1024, min(port, 65535))
    # #39: LAN / tablet access defaults ON, including first-time setup. A save
    # from the host setup UI is the only way an explicit OFF is recorded
    # (lan_access_user_off) — everything else keeps the ON default. This also
    # heals the old poisoned state (lan_access False + migrated marker) so the
    # checkbox can never be permanently locked off again.
    if isinstance(settings.get("server"), dict) and "lan_access" in settings["server"]:
        # The UI sends the checkbox state on every save; a deliberate OFF is
        # when the caller explicitly passed lan_access False.
        normalized["server"]["lan_access_user_off"] = not bool(settings["server"].get("lan_access"))
    normalized["server"]["lan_access"] = bool(normalized["server"].get("lan_access", True))
    _migrate_lan_access(normalized)
    normalized["server"]["device_security_enabled"] = bool(normalized["server"].get("device_security_enabled", False))
    pairing = "".join(ch for ch in str(normalized["server"].get("pairing_code", "") or "") if ch.isdigit())[:6]
    normalized["server"]["pairing_code"] = pairing
    try:
        trusted_days = int(normalized["server"].get("trusted_device_days", 180))
    except (TypeError, ValueError):
        trusted_days = 180
    normalized["server"]["trusted_device_days"] = max(1, min(trusted_days, 730))
    normalized["interface"]["compact"] = bool(normalized["interface"].get("compact", False))
    normalized["interface"]["notifications"] = bool(normalized["interface"].get("notifications", True))
    normalized["interface"]["notification_sound"] = bool(normalized["interface"].get("notification_sound", True))
    normalized["interface"]["native_notifications"] = bool(normalized["interface"].get("native_notifications", True))
    normalized["interface"]["important_notifications_only"] = bool(normalized["interface"].get("important_notifications_only", True))
    normalized["interface"]["airline_theme_enabled"] = bool(normalized["interface"].get("airline_theme_enabled", True))
    mode = str(normalized["interface"].get("airline_theme_mode", "full") or "full").strip().lower()
    normalized["interface"]["airline_theme_mode"] = mode if mode in {"off", "accent", "full"} else "full"
    try:
        intensity = int(normalized["interface"].get("airline_theme_intensity", 38))
    except (TypeError, ValueError):
        intensity = 38
    normalized["interface"]["airline_theme_intensity"] = max(0, min(intensity, 100))
    normalized["interface"]["airline_branding_enabled"] = bool(normalized["interface"].get("airline_branding_enabled", True))
    airline_override = "".join(ch for ch in str(normalized["interface"].get("airline_icao_override", "") or "").upper() if ch.isalnum())[:4]
    normalized["interface"]["airline_icao_override"] = airline_override if 2 <= len(airline_override) <= 4 else ""
    normalized["interface"]["setup_completed"] = bool(normalized["interface"].get("setup_completed", False))
    normalized["interface"]["streamer_mode"] = bool(normalized["interface"].get("streamer_mode", False))
    normalized["interface"]["finance_career_enabled"] = bool(normalized["interface"].get("finance_career_enabled", True))
    modules = normalized["interface"].setdefault("module_visibility", {})
    defaults_modules = DEFAULT_SETTINGS["interface"].get("module_visibility", {})
    if not isinstance(modules, dict):
        modules = {}
    normalized["interface"]["module_visibility"] = {key: bool(modules.get(key, default)) for key, default in defaults_modules.items()}

    units = normalized["interface"].setdefault("units", {})
    allowed_units = {
        "weight": {"kg", "lb"},
        "distance": {"nm", "km"},
        "altitude": {"ft", "m"},
        "speed": {"kt", "kmh"},
        "vertical_speed": {"fpm", "mps"},
    }
    defaults = DEFAULT_SETTINGS["interface"]["units"]
    for key, allowed in allowed_units.items():
        value = str(units.get(key, defaults[key])).lower()
        units[key] = value if value in allowed else defaults[key]
    normalized["integrations"]["fsuipc_enabled"] = bool(normalized["integrations"].get("fsuipc_enabled", True))
    normalized["integrations"]["fsuipc_autostart"] = bool(normalized["integrations"].get("fsuipc_autostart", True))
    normalized["integrations"]["fsuipc_path"] = str(normalized["integrations"].get("fsuipc_path", "") or "").strip()
    try:
        sample_seconds = float(normalized["integrations"].get("telemetry_sample_seconds", 1.0))
    except (TypeError, ValueError):
        sample_seconds = 1.0
    normalized["integrations"]["telemetry_sample_seconds"] = max(0.2, min(sample_seconds, 5.0))
    normalized["integrations"]["aip_charts_enabled"] = bool(normalized["integrations"].get("aip_charts_enabled", True))
    normalized["integrations"]["openaip_map_enabled"] = bool(normalized["integrations"].get("openaip_map_enabled", True))
    normalized["integrations"]["openaip_api_key"] = str(normalized["integrations"].get("openaip_api_key", "") or "").strip()[:128]
    normalized["integrations"]["openaip_proxy_url"] = str(normalized["integrations"].get("openaip_proxy_url", "") or "").strip()[:240]
    normalized["integrations"]["openaip_proxy_token"] = str(normalized["integrations"].get("openaip_proxy_token", "") or "").strip()[:240]
    normalized["integrations"]["local_surface_db_auto_detect"] = bool(normalized["integrations"].get("local_surface_db_auto_detect", True))
    normalized["integrations"]["local_surface_db_path"] = str(normalized["integrations"].get("local_surface_db_path", "") or "").strip()[:520]
    normalized["integrations"]["chartfox_enabled"] = bool(normalized["integrations"].get("chartfox_enabled", True))
    normalized["integrations"]["chartfox_embed_enabled"] = bool(normalized["integrations"].get("chartfox_embed_enabled", True))
    normalized["integrations"]["chartfox_api_enabled"] = bool(normalized["integrations"].get("chartfox_api_enabled", False))
    normalized["integrations"]["chartfox_api_base_url"] = str(normalized["integrations"].get("chartfox_api_base_url", "") or "").strip()[:240]
    normalized["integrations"]["chartfox_api_key"] = str(normalized["integrations"].get("chartfox_api_key", "") or "").strip()[:240]
    normalized["integrations"]["chartfox_oauth_client_id"] = str(normalized["integrations"].get("chartfox_oauth_client_id", "") or "").strip()[:240]
    normalized["integrations"]["chartfox_oauth_client_secret"] = str(normalized["integrations"].get("chartfox_oauth_client_secret", "") or "").strip()[:512]
    normalized["integrations"]["chartfox_oauth_redirect_uri"] = str(normalized["integrations"].get("chartfox_oauth_redirect_uri", "") or "").strip()[:520]
    normalized["integrations"]["raas_voice_path"] = str(normalized["integrations"].get("raas_voice_path", "") or "").strip()[:520]
    raas_unit = str(normalized["integrations"].get("raas_unit", "ft") or "ft").strip().lower()
    normalized["integrations"]["raas_unit"] = "m" if raas_unit in {"m", "meter", "meters", "metre", "metres"} else "ft"
    # v0.25.65: NOTAM alerting toggles (RAAS spoken closure call-outs and the
    # proximity pop-up channel). Default on; safe boolean normalization.
    normalized["integrations"]["raas_notam_callouts"] = bool(normalized["integrations"].get("raas_notam_callouts", True))
    normalized["integrations"]["notam_notifications"] = bool(normalized["integrations"].get("notam_notifications", True))
    normalized["integrations"]["simobjects_notam_markers"] = bool(normalized["integrations"].get("simobjects_notam_markers", False))
    try:
        marker_radius = float(normalized["integrations"].get("marker_radius_nm", 50.0))
    except (TypeError, ValueError):
        marker_radius = 50.0
    normalized["integrations"]["marker_radius_nm"] = max(1.0, min(marker_radius, 200.0))
    try:
        marker_gate = float(normalized["integrations"].get("marker_altitude_gate_ft", 15000.0))
    except (TypeError, ValueError):
        marker_gate = 15000.0
    normalized["integrations"]["marker_altitude_gate_ft"] = max(500.0, min(marker_gate, 60000.0))
    normalized["integrations"]["simbrief_auto_load"] = bool(normalized["integrations"].get("simbrief_auto_load", True))
    normalized["integrations"]["announcements_enabled"] = bool(normalized["integrations"].get("announcements_enabled", False))
    normalized["integrations"]["announcements_root"] = str(normalized["integrations"].get("announcements_root", "") or "").strip()
    try:
        volume = int(normalized["integrations"].get("announcements_volume", 80))
    except (TypeError, ValueError):
        volume = 80
    normalized["integrations"]["announcements_volume"] = max(0, min(volume, 100))
    normalized["integrations"]["announcements_callsign_override"] = str(
        normalized["integrations"].get("announcements_callsign_override", "") or ""
    ).strip().upper()[:16]
    normalized["integrations"]["announcements_airline_override"] = str(
        normalized["integrations"].get("announcements_airline_override", "") or ""
    ).strip().upper()[:4]
    normalized["integrations"]["announcements_hotkeys_enabled"] = bool(
        normalized["integrations"].get("announcements_hotkeys_enabled", True)
    )
    normalized["integrations"]["announcements_pause_hotkey"] = str(
        normalized["integrations"].get("announcements_pause_hotkey", "CTRL+ALT+P") or "CTRL+ALT+P"
    ).strip().upper()[:32]
    normalized["integrations"]["announcements_mute_hotkey"] = str(
        normalized["integrations"].get("announcements_mute_hotkey", "CTRL+ALT+M") or "CTRL+ALT+M"
    ).strip().upper()[:32]
    normalized["integrations"]["camera_volume_enabled"] = bool(
        normalized["integrations"].get("camera_volume_enabled", False)
    )
    for _cv_key in ("camera_volume_cockpit", "camera_volume_cabin", "camera_volume_external"):
        try:
            _cv_val = int(normalized["integrations"].get(_cv_key, 100))
        except (TypeError, ValueError):
            _cv_val = 100
        normalized["integrations"][_cv_key] = max(0, min(_cv_val, 100))
    normalized["integrations"]["gsx_automation_enabled"] = bool(
        normalized["integrations"].get("gsx_automation_enabled", True)
    )
    normalized["integrations"]["gsx_remote_url"] = str(
        normalized["integrations"].get("gsx_remote_url", "") or ""
    ).strip()[:220]
    try:
        gsx_remote_port = int(normalized["integrations"].get("gsx_remote_port", 8744))
    except (TypeError, ValueError):
        gsx_remote_port = 8744
    normalized["integrations"]["gsx_remote_port"] = max(1, min(gsx_remote_port, 65535))
    normalized["integrations"]["gsx_auto_pushback"] = bool(
        normalized["integrations"].get("gsx_auto_pushback", False)
    )
    for key, default in {
        "gsx_auto_prepare_after_services": True,
        "gsx_prepare_on_beacon": False,
        "gsx_departure_boarding": True,
        "gsx_departure_baggage": True,
        "gsx_departure_refuel": True,
        "gsx_departure_catering": True,
        "gsx_departure_water": True,
        "gsx_departure_cleaning": False,
        "gsx_departure_lavatory": False,
        "gsx_fenix_open_menu_handoff": False,
        "gsx_arrival_deboarding": True,
        "gsx_arrival_unload": True,
        "gsx_arrival_cleaning": True,
        "gsx_arrival_lavatory": True,
        "gsx_arrival_water": False,
        "gsx_arrival_catering": False,
        "gsx_arrival_refuel": False,
    }.items():
        normalized["integrations"][key] = bool(normalized["integrations"].get(key, default))
    normalized["integrations"]["hoppie_callsign_override"] = "".join(
        ch for ch in str(normalized["integrations"].get("hoppie_callsign_override", "") or "").upper() if ch.isalnum()
    )[:16]
    normalized["integrations"]["hoppie_auto_poll"] = bool(
        normalized["integrations"].get("hoppie_auto_poll", True)
    )
    normalized["integrations"]["map_online_enabled"] = bool(
        normalized["integrations"].get("map_online_enabled", True)
    )
    printing = normalized.setdefault("printing", {})
    printing["enabled"] = bool(printing.get("enabled", False))
    printing["printer_name"] = str(printing.get("printer_name", "") or "").strip()[:240]
    printing["cpdlc_auto_print"] = bool(printing.get("cpdlc_auto_print", True))
    printing["network_auto_print"] = bool(printing.get("network_auto_print", False))
    try:
        paper_width = int(printing.get("paper_width_mm", 80))
    except (TypeError, ValueError):
        paper_width = 80
    printing["paper_width_mm"] = max(48, min(paper_width, 112))

    updates = normalized.setdefault("updates", {})
    updates["enabled"] = bool(updates.get("enabled", True))
    updates["check_on_startup"] = bool(updates.get("check_on_startup", True))
    updates["manifest_url"] = str(
        updates.get("manifest_url", "https://opsroom.live/api/update.json") or ""
    ).strip()[:500]

    target = app_data_dir() / SETTINGS_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="settings-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(normalized, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp_name, target)
    finally:
        try:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        except OSError:
            pass
    # Invalidate cache so next load_settings() re-reads from disk
    global _SETTINGS_CACHE, _SETTINGS_CACHE_TIME
    _SETTINGS_CACHE = None
    _SETTINGS_CACHE_TIME = 0.0
    return normalized


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[DATA_BLOB, Any]:
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _dpapi_encrypt(data: bytes) -> bytes:
    if os.name != "nt":
        return b"PLAIN:" + base64.b64encode(data)
    in_blob, in_buffer = _blob(data)
    out_blob = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptProtectData(ctypes.byref(in_blob), "Ops Room", None, None, None, 0, ctypes.byref(out_blob)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)
        del in_buffer


def _dpapi_decrypt(data: bytes) -> bytes:
    if data.startswith(b"PLAIN:"):
        return base64.b64decode(data[6:])
    if os.name != "nt":
        raise RuntimeError("Windows DPAPI secret cannot be opened on this platform")
    in_blob, in_buffer = _blob(data)
    out_blob = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)
        del in_buffer


def load_secrets() -> dict[str, str]:
    path = app_data_dir() / SECRETS_FILE
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        protected = base64.b64decode(raw.get("protected", ""))
        return json.loads(_dpapi_decrypt(protected).decode("utf-8"))
    except Exception:
        return {}


def save_secrets(secrets: dict[str, str]) -> None:
    payload = json.dumps(secrets, ensure_ascii=False).encode("utf-8")
    protected = _dpapi_encrypt(payload)
    path = app_data_dir() / SECRETS_FILE
    path.write_text(json.dumps({"protected": base64.b64encode(protected).decode("ascii")}), encoding="utf-8")


def update_hoppie_code(code: str | None = None, clear: bool = False) -> bool:
    secrets = load_secrets()
    if clear:
        secrets.pop("hoppie_logon_code", None)
    elif code is not None and code.strip():
        secrets["hoppie_logon_code"] = code.strip()
    save_secrets(secrets)
    return bool(secrets.get("hoppie_logon_code"))


def update_protomaps_key(key: str | None = None, clear: bool = False) -> bool:
    secrets = load_secrets()
    if clear:
        secrets.pop("protomaps_api_key", None)
    elif key is not None and key.strip():
        secrets["protomaps_api_key"] = key.strip()
    save_secrets(secrets)
    return bool(secrets.get("protomaps_api_key"))


def protomaps_key() -> str:
    # Development key supplied by the project owner. It is used only by the
    # host-side tile proxy, never returned to browser clients. A replacement
    # key saved in Host settings takes precedence.
    return load_secrets().get("protomaps_api_key") or os.getenv("OPSROOM_PROTOMAPS_KEY", "") or "92eaba1a228fa7f3"
