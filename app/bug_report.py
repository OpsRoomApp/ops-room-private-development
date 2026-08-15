from __future__ import annotations

import base64
import getpass
import json
import os
import platform
import re
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .settings_store import app_data_dir, load_settings

BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = Path(__file__).resolve().parent

# Bug reports now go to the OPS ROOM admin server (admin.opsroom.live) instead
# of the old Google Apps Script endpoint. The POST contract is unchanged (secret
# + report + optional base64 diagnostics ZIP), so the in-app UI needs no
# structural changes. Keep in sync with app/settings_store.py BUG_REPORT_ENDPOINT.
DEFAULT_ENDPOINT = "https://admin.opsroom.live/api/v1/bug-reports"
DEFAULT_SECRET = "e7eb1adf7e094220a3f5ad89fcf6d01ce4194a0fe4b2452f9415b97d808bbbab"
MAX_TEXT_CHARS = 200_000
MAX_ZIP_BYTES = 8 * 1024 * 1024

SENSITIVE_KEYS = {
    "secret", "token", "api_key", "apikey", "password", "hoppie_logon_code", "hoppie_code",
    "simbrief_user_id", "simbrief_username", "simbrief_token", "vatsim_cid", "cid", "pairing_code",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_version() -> dict[str, Any]:
    for path in (BASE_DIR / "version.json", APP_DIR / "version.json"):
        try:
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
    return {"product": "OPS ROOM", "version": "0.24.14", "build": "unknown"}


def config() -> dict[str, Any]:
    settings = load_settings()
    cfg = dict(settings.get("bug_report") or {})
    endpoint = os.getenv("OPSROOM_BUG_REPORT_ENDPOINT") or cfg.get("endpoint") or DEFAULT_ENDPOINT
    secret = os.getenv("OPSROOM_BUG_REPORT_SECRET") or cfg.get("secret") or DEFAULT_SECRET
    enabled = bool(cfg.get("enabled", True))
    try:
        max_log_lines = int(cfg.get("max_log_lines", 500))
    except (TypeError, ValueError):
        max_log_lines = 500
    return {
        "enabled": enabled,
        "provider": cfg.get("provider") or "opsroom_server",
        "endpoint": str(endpoint or "").strip(),
        "secret": str(secret or "").strip(),
        "max_log_lines": max(50, min(max_log_lines, 2000)),
        "include_diagnostics_zip": bool(cfg.get("include_diagnostics_zip", True)),
    }


def public_status() -> dict[str, Any]:
    cfg = config()
    return {
        "ok": True,
        "enabled": cfg["enabled"],
        "provider": cfg["provider"],
        "endpoint_configured": bool(cfg["endpoint"]),
        "diagnostics_zip": bool(cfg["include_diagnostics_zip"]),
        "max_log_lines": cfg["max_log_lines"],
    }


def _redact_scalar(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return redact_text(value)


def redact_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in SENSITIVE_KEYS or any(s in key_text for s in ("secret", "token", "password", "hoppie", "simbrief_user", "vatsim_cid", "pairing")):
                result[key] = "[REDACTED]" if item not in (None, "", False) else ""
            else:
                result[key] = redact_mapping(item)
        return result
    if isinstance(value, list):
        return [redact_mapping(item) for item in value]
    return _redact_scalar(value)


def redact_text(text: str) -> str:
    value = str(text or "")
    try:
        username = getpass.getuser()
        if username:
            value = value.replace(username, "[WINDOWS_USER]")
    except Exception:
        pass
    # Hide common token/key/value patterns while keeping the surrounding line useful.
    value = re.sub(r"(?i)(hoppie(?:_logon)?(?:_code)?\s*[:=]\s*)\S+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)(simbrief(?:_user(?:_id)?)?\s*[:=]\s*)\S+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)(vatsim(?:_cid| cid)?\s*[:=]\s*)\d+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)(secret|token|api[_-]?key|password)(\s*[:=]\s*)\S+", r"\1\2[REDACTED]", value)
    # Collapse full Windows user-profile paths without breaking filename context.
    value = re.sub(r"[A-Za-z]:\\Users\\[^\\\r\n]+", r"[USERPROFILE]", value)
    # Redact network identifiers from shared diagnostics. LAN URLs remain visible in the app UI, but never in reports.
    value = re.sub(r"https?://127\.0\.0\.1(:\d+)?", lambda m: "http://[LOCALHOST]" + (m.group(1) or ""), value)
    value = re.sub(r"https?://localhost(:\d+)?", lambda m: "http://[LOCALHOST]" + (m.group(1) or ""), value, flags=re.I)
    value = re.sub(r"https?://(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})(:\d+)?", lambda m: "http://[LAN_IP]" + (m.group(1) or ""), value)
    value = re.sub(r"(?<![\d.])127\.0\.0\.1(?::\d+)?", "[LOCALHOST]", value)
    value = re.sub(r"(?<![\d.])(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})(?::\d+)?", "[LAN_IP]", value)
    value = re.sub(r'INFO:\s+\[LAN_IP\]\s+-\s+"WebSocket', 'INFO: [CLIENT_IP] - "WebSocket', value)
    return value


def _safe_call(label: str, fn, *args, **kwargs) -> dict[str, Any]:
    try:
        data = fn(*args, **kwargs)
        return {"ok": True, "data": redact_mapping(data)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _tail_file(path: Path, max_lines: int) -> str:
    """Return a redacted tail of a log file without loading the whole file.

    Early beta builds used read_text().splitlines(), which could fail with
    MemoryError on long-running tester logs. Keep diagnostics lightweight by
    reading only the end of the file and then taking the requested line count.
    """
    if not path.is_file():
        return ""
    try:
        max_lines = max(1, min(int(max_lines or 300), 1000))
        # 768 KiB is enough for hundreds of verbose log lines but small enough
        # to avoid memory spikes on public beta machines.
        max_bytes = 768 * 1024
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(-max_bytes, 2)
                data = handle.read(max_bytes)
                # Drop a partial first line when we started mid-file.
                if b"\n" in data:
                    data = data.split(b"\n", 1)[1]
            else:
                data = handle.read()
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()[-max_lines:]
        return redact_text("\n".join(lines))
    except Exception as exc:
        return f"Could not read {path.name}: {type(exc).__name__}: {exc}"


def log_path() -> Path:
    return app_data_dir() / "logs" / "opsroom.log"


def _diagnostics_dir() -> Path:
    path = app_data_dir() / "diagnostics"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _report_id() -> str:
    return "OPS-" + _utc_now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8].upper()


def build_snapshot(module: str = "", last_error: str = "") -> dict[str, Any]:
    version = _read_version()
    settings = load_settings()
    snapshot: dict[str, Any] = {
        "generated_utc": _iso_now(),
        "version": version,
        "requested_module": module,
        "last_error": redact_text(last_error),
        "system": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
        "app_data_dir": str(app_data_dir()).replace(str(Path.home()), "[HOME]"),
        "settings_redacted": redact_mapping(settings),
        "logs": {
            "opsroom_log_path": str(log_path()).replace(str(Path.home()), "[HOME]"),
            "opsroom_log_exists": log_path().is_file(),
        },
    }

    # Import lazily so the diagnostics module cannot create circular imports at startup.
    try:
        from .system_status import build_system_summary
        snapshot["system_summary"] = _safe_call("system_summary", build_system_summary)
    except Exception as exc:
        snapshot["system_summary"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        from .simconnect_position import simconnect_diagnostics
        snapshot["simconnect"] = _safe_call("simconnect", simconnect_diagnostics)
    except Exception as exc:
        snapshot["simconnect"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        from .telemetry_provider import telemetry_diagnostics
        snapshot["telemetry"] = _safe_call("telemetry", telemetry_diagnostics)
    except Exception as exc:
        snapshot["telemetry"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        from .gsx_remote import status as gsx_status, automation_status as gsx_automation_status
        snapshot["gsx"] = _safe_call("gsx_status", gsx_status)
        snapshot["gsx_automation"] = _safe_call("gsx_automation", gsx_automation_status)
    except Exception as exc:
        snapshot["gsx"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        from .fenix_adapter import status as fenix_status
        snapshot["fenix"] = _safe_call("fenix", fenix_status)
    except Exception as exc:
        snapshot["fenix"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        from .vpilot_bridge import bridge_status, message_status
        snapshot["vpilot_bridge"] = _safe_call("vpilot_bridge", bridge_status)
        snapshot["vpilot_messages"] = _safe_call("vpilot_messages", message_status)
    except Exception as exc:
        snapshot["vpilot_bridge"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        from .hoppie_client import status as hoppie_status
        snapshot["hoppie"] = _safe_call("hoppie", hoppie_status)
    except Exception as exc:
        snapshot["hoppie"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return snapshot


def build_report(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    version = _read_version()
    report_id = str(payload.get("reportId") or _report_id())
    module = str(payload.get("module") or payload.get("activePage") or "").strip()[:80]
    last_error = str(payload.get("lastError") or "").strip()[:500]
    snapshot = build_snapshot(module=module, last_error=last_error)
    summary = snapshot.get("system_summary", {}).get("data", {}) if isinstance(snapshot.get("system_summary"), dict) else {}
    flight = summary.get("flight") or summary.get("active_flight") or {}
    position = summary.get("position") or {}
    integrations = summary.get("integrations") or {}

    report = {
        "reportId": report_id,
        "timestampUtc": _iso_now(),
        "version": version.get("version", "0.24.14"),
        "build": version.get("build", ""),
        "codename": version.get("codename", ""),
        "module": module or "Unknown",
        "simulator": str(payload.get("simulator") or "Auto-detected / unknown")[:80],
        "aircraft": str(payload.get("aircraft") or flight.get("aircraft") or flight.get("aircraft_icao") or "")[:120],
        "airport": str(payload.get("airport") or summary.get("nearest_airport") or position.get("nearest_airport") or "")[:20],
        "route": str(payload.get("route") or "")[:160],
        "addons": str(payload.get("addons") or "")[:240],
        "userDescription": str(payload.get("userDescription") or payload.get("description") or "").strip()[:4000],
        "expectedResult": str(payload.get("expectedResult") or "").strip()[:2000],
        "stepsToReproduce": str(payload.get("stepsToReproduce") or "").strip()[:3000],
        "errorSummary": last_error,
        "contact": str(payload.get("contact") or "").strip()[:160],
        "integrationSummary": _integration_summary(integrations),
        "diagnosticsIncluded": bool(payload.get("includeDiagnosticsZip", True)),
    }
    return {"report": redact_mapping(report), "snapshot": snapshot}


def _integration_summary(integrations: dict[str, Any]) -> str:
    if not isinstance(integrations, dict):
        return ""
    parts = []
    for key, value in integrations.items():
        if isinstance(value, dict):
            state = value.get("state") or value.get("label") or "unknown"
            parts.append(f"{key}:{state}")
        else:
            parts.append(f"{key}:{value}")
    return ", ".join(parts)[:1000]


def build_report_text(report: dict[str, Any], snapshot: dict[str, Any], max_log_lines: int = 120) -> str:
    log_tail = _tail_file(log_path(), max_log_lines)
    lines = [
        "OPS ROOM BUG REPORT",
        "===================",
        f"Report ID: {report.get('reportId','')}",
        f"Timestamp UTC: {report.get('timestampUtc','')}",
        f"Version: {report.get('version','')} ({report.get('build','')})",
        f"Module: {report.get('module','')}",
        f"Simulator: {report.get('simulator','')}",
        f"Aircraft: {report.get('aircraft','')}",
        f"Airport: {report.get('airport','')}",
        f"Route: {report.get('route','')}",
        f"Add-ons: {report.get('addons','')}",
        f"Error: {report.get('errorSummary','')}",
        "",
        "USER DESCRIPTION",
        report.get("userDescription", ""),
        "",
        "EXPECTED RESULT",
        report.get("expectedResult", ""),
        "",
        "STEPS TO REPRODUCE",
        report.get("stepsToReproduce", ""),
        "",
        "INTEGRATION SUMMARY",
        report.get("integrationSummary", ""),
        "",
        "RECENT OPS ROOM LOG",
        log_tail or "No log file available yet.",
    ]
    return redact_text("\n".join(lines))[:MAX_TEXT_CHARS]


def create_diagnostics_zip(payload: dict[str, Any] | None = None) -> Path:
    built = build_report(payload)
    report = built["report"]
    snapshot = built["snapshot"]
    cfg = config()
    report_text = build_report_text(report, snapshot, max_log_lines=cfg["max_log_lines"])
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", report["reportId"])
    module = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(report.get("module") or "module"))[:32]
    filename = f"OPS_ROOM_Diagnostics_{report.get('version','v')}_{safe_id}_{module}.zip"
    path = _diagnostics_dir() / filename

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bug_report.json", json.dumps(redact_mapping(report), indent=2, ensure_ascii=False))
        zf.writestr("bug_report.txt", report_text)
        zf.writestr("diagnostics_snapshot.json", json.dumps(redact_mapping(snapshot), indent=2, ensure_ascii=False, default=str))
        zf.writestr("config_redacted.json", json.dumps(redact_mapping(load_settings()), indent=2, ensure_ascii=False))
        log_tail = _tail_file(log_path(), cfg["max_log_lines"])
        zf.writestr("opsroom_log_tail.txt", log_tail or "No opsroom.log file available.")
        zf.writestr("privacy_notice.txt", PRIVACY_NOTICE)
        for rel in ("version.json", "RELEASE_NOTES.txt", "README.txt"):
            source = BASE_DIR / rel
            if source.is_file():
                try:
                    zf.writestr(rel, redact_text(source.read_text(encoding="utf-8", errors="replace")))
                except Exception:
                    pass
    if path.stat().st_size > MAX_ZIP_BYTES:
        # Rebuild a lean ZIP with only the essential text files.
        path.unlink(missing_ok=True)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("bug_report.json", json.dumps(redact_mapping(report), indent=2, ensure_ascii=False))
            zf.writestr("bug_report.txt", report_text[:80_000])
            zf.writestr("diagnostics_snapshot.json", json.dumps(redact_mapping(snapshot), indent=2, ensure_ascii=False, default=str)[:120_000])
            zf.writestr("privacy_notice.txt", PRIVACY_NOTICE)
    return path


def report_summary(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    built = build_report(payload)
    cfg = config()
    text = build_report_text(built["report"], built["snapshot"], max_log_lines=min(cfg["max_log_lines"], 200))
    return {"ok": True, "report": built["report"], "summaryText": text, "privacyNotice": PRIVACY_NOTICE}


def send_report(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    cfg = config()
    if not cfg["enabled"]:
        return {"ok": False, "error": "Bug reporting is disabled in OPS ROOM settings."}
    if not cfg["endpoint"]:
        return {"ok": False, "error": "Bug reporting endpoint is not configured."}

    built = build_report(payload)
    report = built["report"]
    snapshot = built["snapshot"]
    include_zip = bool(payload.get("includeDiagnosticsZip", cfg["include_diagnostics_zip"]))
    zip_path: Path | None = create_diagnostics_zip(payload) if include_zip else None
    report_text = build_report_text(report, snapshot, max_log_lines=cfg["max_log_lines"])

    post_payload: dict[str, Any] = {
        "secret": cfg["secret"],
        "report": {**report, "reportText": report_text},
        "diagnosticsZip": None,
    }
    if zip_path and zip_path.is_file():
        raw = zip_path.read_bytes()
        post_payload["diagnosticsZip"] = {
            "filename": zip_path.name,
            "mimeType": "application/zip",
            "base64": base64.b64encode(raw).decode("ascii"),
        }

    try:
        response = requests.post(cfg["endpoint"], json=post_payload, timeout=45)
        text = response.text or ""
        response.raise_for_status()
        try:
            result = response.json()
        except ValueError:
            return {
                "ok": False,
                "reportId": report.get("reportId"),
                "error": "Bug endpoint did not return JSON. Check the bug report server endpoint and access settings.",
                "responsePreview": text[:240],
                "localDiagnosticsZip": str(zip_path) if zip_path else "",
            }
        if not result.get("ok"):
            result.setdefault("reportId", report.get("reportId"))
            result.setdefault("localDiagnosticsZip", str(zip_path) if zip_path else "")
            return result
        return {
            "ok": True,
            "reportId": result.get("reportId") or report.get("reportId"),
            "diagnosticsFileUrl": result.get("diagnosticsFileUrl") or "",
            "sheetRow": result.get("sheetRow") or "",
            "localDiagnosticsZip": str(zip_path) if zip_path else "",
        }
    except requests.RequestException as exc:
        return {
            "ok": False,
            "reportId": report.get("reportId"),
            "error": f"Upload failed: {type(exc).__name__}: {exc}",
            "localDiagnosticsZip": str(zip_path) if zip_path else "",
        }


PRIVACY_NOTICE = (
    "OPS ROOM bug reports include OPS ROOM version, simulator/add-on status, recent OPS ROOM log lines, "
    "integration diagnostics, and the description typed by the user. OPS ROOM attempts to redact SimBrief IDs, "
    "Hoppie codes, VATSIM CID, pairing codes, tokens, secrets, passwords and Windows user-profile paths before export. "
    "Review the downloaded ZIP before sending if you need full control over what is shared."
)
