from __future__ import annotations

import base64
import binascii
import json
import mimetypes
import re
from pathlib import Path
from typing import Any

from .data_loader import BASE_DIR, callsign_prefix, load_airlines, logo_index
from .settings_store import app_data_dir, load_settings

_MAX_BYTES = 2 * 1024 * 1024
_ALLOWED = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
_META_FILE = "airline-branding.json"
_GENERIC_URL = "/assets/brand/opsroom-logo-icon.svg"


def _clean_code(value: Any) -> str:
    code = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    return code if re.fullmatch(r"[A-Z0-9]{2,4}", code or "") else ""


def _meta_path() -> Path:
    return app_data_dir() / _META_FILE


def _load_meta() -> dict[str, Any]:
    try:
        data = json.loads(_meta_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _custom_logo_path() -> Path | None:
    meta = _load_meta()
    name = str(meta.get("file") or "")
    if not name.startswith("airline-logo."):
        return None
    path = app_data_dir() / name
    return path if path.is_file() else None


def _direct(code: str) -> dict[str, Any]:
    code = _clean_code(code)
    airline = load_airlines().get(code)
    logo_url = logo_index().get(code)
    return {
        "code": code,
        "name": airline.name if airline else (code or "OPS ROOM"),
        "callsign_name": airline.callsign if airline else "",
        "country": airline.country if airline else "",
        "logo_url": logo_url,
        "known_airline": bool(airline),
        "packaged_logo": bool(logo_url),
    }


def resolve_airline_branding(
    plan: dict[str, Any] | None = None,
    *,
    callsign: str = "",
    airline_code: str = "",
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve presentation-only airline identity without touching flight logic.

    Automatic order follows the active OFP first, then the callsign/database.
    The user ICAO override is a fallback for virtual/missing airlines. A custom
    airline logo is used for the override or when no packaged logo is available.
    """
    cfg = settings or load_settings()
    interface = cfg.get("interface") if isinstance(cfg.get("interface"), dict) else {}
    enabled = interface.get("airline_branding_enabled", True) is not False
    if not enabled:
        return {
            "enabled": False,
            "code": "",
            "name": "OPS ROOM",
            "source": "disabled",
            "logo_url": None,
            "logo_available": False,
            "fallback": "generic",
            "generic_logo_url": _GENERIC_URL,
        }

    plan = plan if isinstance(plan, dict) else {}
    flight = plan.get("flight") if isinstance(plan.get("flight"), dict) else {}
    general = plan.get("general") if isinstance(plan.get("general"), dict) else {}
    plan_callsign = str(plan.get("callsign") or flight.get("callsign") or general.get("callsign") or callsign or "").upper()
    plan_airline = _clean_code(
        general.get("icao_airline")
        or plan.get("icao_airline")
        or flight.get("icao_airline")
        or plan.get("airline")
        or flight.get("airline")
        or general.get("airline")
        or airline_code
    )
    prefix = _clean_code(callsign_prefix(plan_callsign))
    override = _clean_code(interface.get("airline_icao_override"))

    candidates: list[tuple[str, str]] = []
    for source, code in (("simbrief", plan_airline), ("callsign", prefix)):
        if code and code not in {item[1] for item in candidates}:
            candidates.append((source, code))
    # Explicit database pass is kept separate in diagnostics even though the
    # prefix lookup above normally resolves it immediately.
    if prefix and prefix in load_airlines() and prefix not in {item[1] for item in candidates}:
        candidates.append(("database", prefix))
    if override and override not in {item[1] for item in candidates}:
        candidates.append(("override", override))

    chosen_source = "generic"
    chosen = _direct("")
    for source, code in candidates:
        item = _direct(code)
        # Preserve the OFP identity even when its packaged logo is absent.
        if source == "simbrief" or item["known_airline"] or item["packaged_logo"] or source == "override":
            chosen_source, chosen = source, item
            break

    custom_path = _custom_logo_path()
    use_custom = bool(custom_path and (chosen_source == "override" or not chosen.get("logo_url")))
    logo_url = "/api/airline-branding/logo" if use_custom else chosen.get("logo_url")
    code = chosen.get("code") or override or prefix or plan_airline
    name = chosen.get("name") if code else "OPS ROOM"
    fallback = "logo" if logo_url else ("monogram" if code else "generic")
    return {
        "enabled": True,
        "code": code,
        "name": name,
        "callsign_name": chosen.get("callsign_name") or "",
        "country": chosen.get("country") or "",
        "source": chosen_source,
        "logo_url": logo_url,
        "logo_available": bool(logo_url),
        "packaged_logo": bool(chosen.get("packaged_logo")),
        "custom_logo": use_custom,
        "custom_logo_available": bool(custom_path),
        "override": override,
        "fallback": fallback,
        "generic_logo_url": _GENERIC_URL,
    }


def status(plan: dict[str, Any] | None = None) -> dict[str, Any]:
    data = resolve_airline_branding(plan)
    meta = _load_meta()
    data.update({
        "ok": True,
        "custom_filename": meta.get("original_name") if _custom_logo_path() else None,
        "custom_mime_type": meta.get("mime_type") if _custom_logo_path() else None,
    })
    return data


def save_custom_logo(payload: dict[str, Any]) -> dict[str, Any]:
    data_url = str((payload or {}).get("data_url") or "")
    original_name = str((payload or {}).get("filename") or "airline-logo")[:160]
    if not data_url.startswith("data:") or "," not in data_url:
        raise ValueError("Select a PNG, JPG or WebP airline logo.")
    header, encoded = data_url.split(",", 1)
    mime = header[5:].split(";", 1)[0].lower().strip()
    suffix = _ALLOWED.get(mime)
    if not suffix or ";base64" not in header.lower():
        raise ValueError("Airline logo must be PNG, JPG or WebP.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("The selected airline logo could not be decoded.") from exc
    if not raw or len(raw) > _MAX_BYTES:
        raise ValueError("Airline logo must be smaller than 2 MB.")
    clear_custom_logo()
    target = app_data_dir() / f"airline-logo{suffix}"
    target.write_bytes(raw)
    _meta_path().write_text(json.dumps({"file": target.name, "original_name": original_name, "mime_type": mime}, indent=2), encoding="utf-8")
    return status()


def clear_custom_logo() -> dict[str, Any]:
    for suffix in _ALLOWED.values():
        try:
            (app_data_dir() / f"airline-logo{suffix}").unlink(missing_ok=True)
        except OSError:
            pass
    try:
        _meta_path().unlink(missing_ok=True)
    except OSError:
        pass
    return status()


def custom_logo_file() -> tuple[Path, str] | None:
    path = _custom_logo_path()
    if not path:
        return None
    mime = str(_load_meta().get("mime_type") or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    return path, mime


def _local_logo_file(branding: dict[str, Any]) -> tuple[Path, str] | None:
    url = str((branding or {}).get("logo_url") or "")
    if url == "/api/airline-branding/logo":
        return custom_logo_file()
    if url.startswith("/assets/logos/"):
        name = Path(url).name
        path = BASE_DIR / "assets" / "logos" / name
    elif url.startswith("/static/assets/logos/"):
        name = Path(url).name
        path = BASE_DIR / "static" / "assets" / "logos" / name
    else:
        return None
    if not path.is_file():
        return None
    return path, mimetypes.guess_type(path.name)[0] or "image/png"


def logo_data_uri(branding: dict[str, Any]) -> str | None:
    item = _local_logo_file(branding)
    if not item:
        return None
    path, mime = item
    try:
        return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"
    except OSError:
        return None
