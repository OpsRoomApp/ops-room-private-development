from __future__ import annotations

import hashlib
import json
import secrets
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .settings_store import app_data_dir, load_settings, save_settings

_FILE = "trusted_devices.json"
_COOKIE = "opsroom_device_token"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def cookie_name() -> str:
    return _COOKIE


def is_local_address(host: str | None) -> bool:
    value = str(host or "").split("%", 1)[0].lower()
    return value in {"127.0.0.1", "::1", "localhost"} or value.startswith("::ffff:127.")


def enabled() -> bool:
    return bool(load_settings().get("server", {}).get("device_security_enabled", False))


def pairing_code() -> str:
    settings = load_settings()
    server = settings.setdefault("server", {})
    value = "".join(ch for ch in str(server.get("pairing_code") or "") if ch.isdigit())[:6]
    if len(value) != 6 or value == "000000":
        value = f"{secrets.randbelow(1_000_000):06d}"
        server["pairing_code"] = value
        save_settings(settings)
    return value


def rotate_pairing_code() -> str:
    settings = load_settings()
    settings.setdefault("server", {})["pairing_code"] = f"{secrets.randbelow(1_000_000):06d}"
    save_settings(settings)
    return str(settings["server"]["pairing_code"])


def _path() -> Path:
    return app_data_dir() / _FILE


def _load() -> dict[str, Any]:
    path = _path()
    if not path.exists():
        return {"devices": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {"devices": []}
    except (OSError, ValueError, TypeError):
        return {"devices": []}


def _save(payload: dict[str, Any]) -> None:
    path = _path()
    fd, temp_name = tempfile.mkstemp(prefix="trusted-devices-", suffix=".tmp", dir=str(path.parent))
    try:
        with open(fd, "w", encoding="utf-8", closefd=True) as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        Path(temp_name).replace(path)
    finally:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except OSError:
            pass


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def pair(code: str, *, name: str = "", address: str = "", user_agent: str = "") -> str:
    if not secrets.compare_digest("".join(ch for ch in str(code or "") if ch.isdigit())[:6], pairing_code()):
        raise ValueError("The pairing code is not valid")
    token = secrets.token_urlsafe(32)
    now = _utc_now()
    settings = load_settings()
    days = int(settings.get("server", {}).get("trusted_device_days", 180) or 180)
    item = {
        "id": secrets.token_hex(6),
        "token_hash": _digest(token),
        "name": str(name or "LAN DEVICE").strip()[:80] or "LAN DEVICE",
        "address": str(address or "").strip()[:80],
        "user_agent": str(user_agent or "").strip()[:200],
        "created_utc": _iso(now),
        "last_seen_utc": _iso(now),
        "expires_utc": _iso(now + timedelta(days=max(1, min(days, 730)))),
    }
    payload = _load()
    devices = [x for x in payload.get("devices", []) if isinstance(x, dict)]
    devices.append(item)
    payload["devices"] = devices[-100:]
    _save(payload)
    return token


def validate(token: str | None, *, address: str = "") -> bool:
    if not token:
        return False
    digest = _digest(str(token))
    payload = _load()
    devices = [x for x in payload.get("devices", []) if isinstance(x, dict)]
    now = _utc_now()
    changed = False
    valid = False
    kept: list[dict[str, Any]] = []
    for item in devices:
        expiry = _parse(item.get("expires_utc"))
        if expiry and expiry < now:
            changed = True
            continue
        if secrets.compare_digest(str(item.get("token_hash") or ""), digest):
            valid = True
            item["last_seen_utc"] = _iso(now)
            if address:
                item["address"] = str(address)[:80]
            changed = True
        kept.append(item)
    if changed:
        payload["devices"] = kept
        _save(payload)
    return valid


def list_devices() -> list[dict[str, Any]]:
    now = _utc_now()
    result = []
    for item in _load().get("devices", []):
        if not isinstance(item, dict):
            continue
        expiry = _parse(item.get("expires_utc"))
        if expiry and expiry < now:
            continue
        result.append({k: item.get(k) for k in ("id", "name", "address", "created_utc", "last_seen_utc", "expires_utc")})
    result.sort(key=lambda x: str(x.get("last_seen_utc") or ""), reverse=True)
    return result


def revoke(device_id: str) -> bool:
    payload = _load()
    before = len(payload.get("devices", []))
    payload["devices"] = [x for x in payload.get("devices", []) if not isinstance(x, dict) or x.get("id") != device_id]
    if len(payload["devices"]) != before:
        _save(payload)
        return True
    return False


def revoke_all() -> int:
    payload = _load()
    count = len(payload.get("devices", []))
    payload["devices"] = []
    _save(payload)
    return count
