from __future__ import annotations

import base64
import binascii
import json
from pathlib import Path
from typing import Any

from .settings_store import app_data_dir

_MAX_BYTES = 2 * 1024 * 1024
_ALLOWED = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
_META = "obs-branding.json"


def _meta_path() -> Path:
    return app_data_dir() / _META


def _load_meta() -> dict[str, Any]:
    try:
        data = json.loads(_meta_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _logo_path() -> Path | None:
    meta = _load_meta()
    name = str(meta.get("file") or "")
    if not name.startswith("obs-logo."):
        return None
    path = app_data_dir() / name
    return path if path.is_file() else None


def status() -> dict[str, Any]:
    path = _logo_path()
    meta = _load_meta()
    return {
        "ok": True,
        "logo_available": bool(path),
        "logo_url": "/api/obs/logo" if path else None,
        "filename": meta.get("original_name") if path else None,
        "mime_type": meta.get("mime_type") if path else None,
    }


def save_logo(payload: dict[str, Any]) -> dict[str, Any]:
    data_url = str(payload.get("data_url") or "")
    original_name = str(payload.get("filename") or "overlay-logo")[:160]
    if not data_url.startswith("data:") or "," not in data_url:
        raise ValueError("Select a PNG, JPG or WebP logo.")
    header, encoded = data_url.split(",", 1)
    mime = header[5:].split(";", 1)[0].lower().strip()
    suffix = _ALLOWED.get(mime)
    if not suffix or ";base64" not in header.lower():
        raise ValueError("Logo must be PNG, JPG or WebP.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("The selected logo could not be decoded.") from exc
    if not raw or len(raw) > _MAX_BYTES:
        raise ValueError("Logo must be smaller than 2 MB.")
    clear_logo()
    target = app_data_dir() / f"obs-logo{suffix}"
    target.write_bytes(raw)
    _meta_path().write_text(json.dumps({"file": target.name, "original_name": original_name, "mime_type": mime}, indent=2), encoding="utf-8")
    return status()


def clear_logo() -> dict[str, Any]:
    for suffix in _ALLOWED.values():
        try:
            (app_data_dir() / f"obs-logo{suffix}").unlink(missing_ok=True)
        except OSError:
            pass
    try:
        _meta_path().unlink(missing_ok=True)
    except OSError:
        pass
    return status()


def logo_file() -> tuple[Path, str] | None:
    path = _logo_path()
    if not path:
        return None
    mime = str(_load_meta().get("mime_type") or "application/octet-stream")
    return path, mime
