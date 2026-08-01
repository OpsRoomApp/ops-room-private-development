from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .settings_store import app_data_dir, load_settings

BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = Path(__file__).resolve().parent
PRIMARY_MANIFEST_URL = "https://opsroom.live/api/update.json"
FALLBACK_MANIFEST_URL = "https://raw.githubusercontent.com/OpsRoomApp/ops-room-releases/main/update.json"
DEFAULT_MANIFEST_URL = PRIMARY_MANIFEST_URL
STATE_FILE = "update_state.json"
DOWNLOAD_TIMEOUT = 25
DEFAULT_VERSION = "0.25.49"


@dataclass(frozen=True)
class Version:
    parts: tuple[int, ...]

    @classmethod
    def parse(cls, value: Any) -> "Version":
        text = str(value or "0").strip().lower()
        if text.startswith("v"):
            text = text[1:]
        # Compare only the numeric semver prefix. This intentionally treats
        # 0.24.14, v0.24.14 and 0.24.14-public-beta as the same installed
        # release for update decisions.
        numbers: list[int] = []
        for part in text.replace("_", ".").replace("-", ".").split("."):
            digits = ""
            for ch in part:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            if digits == "":
                break
            numbers.append(int(digits))
        return cls(tuple(numbers or [0]))

    def normalized(self, width: int = 3) -> str:
        parts = self.parts + (0,) * max(0, width - len(self.parts))
        return ".".join(str(x) for x in parts[:max(width, len(self.parts))])

    def __lt__(self, other: "Version") -> bool:
        left = self.parts + (0,) * (max(len(self.parts), len(other.parts)) - len(self.parts))
        right = other.parts + (0,) * (max(len(self.parts), len(other.parts)) - len(other.parts))
        return left < right


def _version_candidates() -> list[Path]:
    candidates: list[Path] = []
    env_path = os.getenv("OPSROOM_VERSION_FILE")
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend([
        BASE_DIR / "version.json",
        APP_DIR / "version.json",
        BASE_DIR.parent / "version.json",
    ])
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend([exe_dir / "version.json", exe_dir / "_internal" / "version.json"])
    seen: set[str] = set()
    unique: list[Path] = []
    for path in candidates:
        key = str(path)
        if key not in seen:
            seen.add(key); unique.append(path)
    return unique


def _read_version() -> dict[str, Any]:
    for path in _version_candidates():
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("version"):
                    return data
        except Exception:
            continue
    return {"product": "OPS ROOM", "version": DEFAULT_VERSION, "build": "unknown", "source": "fallback"}


def normalize_version(value: Any) -> str:
    return Version.parse(value).normalized()


def current_version() -> str:
    return normalize_version(_read_version().get("version") or DEFAULT_VERSION)


def _update_settings() -> dict[str, Any]:
    settings = load_settings()
    cfg = dict(settings.get("updates") or {})
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "check_on_startup": bool(cfg.get("check_on_startup", True)),
        "manifest_url": str(cfg.get("manifest_url") or os.getenv("OPSROOM_UPDATE_MANIFEST") or DEFAULT_MANIFEST_URL).strip(),
    }


def _state_path() -> Path:
    path = app_data_dir() / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def read_state() -> dict[str, Any]:
    try:
        path = _state_path()
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def write_state(data: dict[str, Any]) -> None:
    path = _state_path()
    payload = dict(data)
    payload["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def clear_state(reason: str = "") -> None:
    try:
        path = _state_path()
        if path.exists():
            path.unlink()
    except Exception:
        if reason:
            try:
                write_state({"stage": "cleared", "reason": reason})
            except Exception:
                pass


def _validate_manifest(data: dict[str, Any]) -> dict[str, Any]:
    latest = str(data.get("latest_version") or data.get("version") or "").strip()
    download_url = str(data.get("download_url") or data.get("url") or "").strip()
    fallback_url = str(data.get("fallback_download_url") or "").strip()
    checksum = str(data.get("sha256") or "").strip()
    if not latest:
        raise ValueError("Update manifest has no version.")
    if not download_url.lower().startswith("https://") or not download_url.lower().endswith(".zip"):
        raise ValueError("Update manifest download URL must be an HTTPS ZIP.")
    if fallback_url and (not fallback_url.lower().startswith("https://") or not fallback_url.lower().endswith(".zip")):
        raise ValueError("Update manifest fallback download URL must be an HTTPS ZIP.")
    if len(checksum) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in checksum):
        raise ValueError("Update manifest SHA256 is missing or invalid.")
    # v0.25.49: Normalise optional fields for downstream consumers
    if fallback_url:
        data["fallback_download_url"] = fallback_url
    data["release_notes"] = str(data.get("release_notes") or "").strip()
    data["channel"] = str(data.get("channel") or "stable").strip()
    return data


def _try_fetch_manifest(url: str, force: bool = False) -> dict[str, Any]:
    """Fetch and validate a manifest from a single URL. Raises on any failure."""
    import requests

    response = requests.get(
        url,
        timeout=DOWNLOAD_TIMEOUT,
        headers={"Cache-Control": "no-cache" if force else "max-age=60"},
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Update manifest is not an object.")
    return _validate_manifest(data)


def fetch_manifest(force: bool = False) -> dict[str, Any]:
    import requests

    _log = logging.getLogger(__name__)
    cfg = _update_settings()
    if not cfg["enabled"]:
        return {"ok": False, "disabled": True, "reason": "Update checks are disabled."}
    url = cfg["manifest_url"]
    if not url:
        return {"ok": False, "reason": "No update manifest URL is configured."}

    # If the user has set a custom manifest URL (neither the primary nor the
    # old GitHub default), honour it exactly with no fallback.
    is_custom = url not in (PRIMARY_MANIFEST_URL, FALLBACK_MANIFEST_URL)
    if is_custom:
        return _try_fetch_manifest(url, force=force)

    # Primary (opsroom.live) first; GitHub raw manifest as transparent fallback
    # when the primary is unreachable (DNS, timeout, HTTP error, invalid JSON).
    last_error: Exception | None = None
    for attempt_url in (PRIMARY_MANIFEST_URL, FALLBACK_MANIFEST_URL):
        try:
            manifest = _try_fetch_manifest(attempt_url, force=force)
            if attempt_url == FALLBACK_MANIFEST_URL:
                _log.info("Update manifest served from GitHub fallback (opsroom.live was unreachable).")
            return manifest
        except Exception as exc:
            last_error = exc
            _log.debug("Update manifest fetch from %s failed: %s", attempt_url, exc)
            continue

    raise last_error or RuntimeError("All update manifest URLs failed.")


def check_for_update(force: bool = False) -> dict[str, Any]:
    cfg = _update_settings()
    state = read_state()
    installed = current_version()
    result: dict[str, Any] = {
        "ok": True,
        "enabled": cfg["enabled"],
        "check_on_startup": cfg["check_on_startup"],
        "current_version": installed,
        "update_available": False,
        "state": state,
    }
    if not cfg["enabled"]:
        result["reason"] = "Update checks are disabled."
        return result
    try:
        manifest = fetch_manifest(force=force)
    except Exception as exc:
        result.update({"ok": False, "reason": f"Update check failed: {type(exc).__name__}: {exc}"})
        return result
    latest_raw = manifest.get("latest_version") or manifest.get("version") or ""
    latest = normalize_version(latest_raw)
    if Version.parse(latest).parts == (0,) and not str(latest_raw).strip():
        result.update({"ok": False, "reason": "Update manifest does not contain latest_version or version.", "manifest": manifest})
        return result
    installed_v = Version.parse(installed)
    latest_v = Version.parse(latest)
    available = installed_v < latest_v
    if not available:
        clear_state("remote version is not newer than installed")
        state = {}
    download_url = str(manifest.get("download_url") or manifest.get("url") or "").strip()
    result.update({
        "ok": True,
        "manifest": manifest,
        "latest_version": latest,
        "remote_version": latest,
        "installed_version": installed,
        "download_url": download_url,
        "update_available": available,
        "mandatory": bool(manifest.get("mandatory", False)),
        "release_notes_url": manifest.get("release_notes_url") or "",
        "message": manifest.get("message") or manifest.get("notes") or "",
        "decision": "update_available" if available else "remote_not_newer",
        "manifest_url": cfg.get("manifest_url"),
        "state": state,
    })
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(url: str, target: Path, version: str = "") -> None:
    """Download to a .part file, validate non-empty output, then atomically rename.

    Older builds wrote directly to the final ZIP name, which could leave a 0 KB
    file if GitHub, the connection or antivirus interrupted the request. v0.24.14
    never exposes the final filename until bytes were actually received.
    """
    import requests

    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    for old in (part, target):
        try:
            old.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass

    bytes_written = 0
    last_status = 0.0
    with requests.get(url, timeout=(10, 180), stream=True, allow_redirects=True) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length") or 0)
        write_state({"stage": "downloading", "version": version, "package": str(target), "partial": str(part), "bytes": 0, "total_bytes": total})
        with part.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                handle.write(chunk)
                bytes_written += len(chunk)
                now = time.monotonic()
                if now - last_status > 0.5:
                    percent = round((bytes_written / total) * 100, 1) if total else None
                    write_state({"stage": "downloading", "version": version, "package": str(target), "partial": str(part), "bytes": bytes_written, "total_bytes": total, "percent": percent})
                    last_status = now

    if bytes_written <= 0 or not part.is_file() or part.stat().st_size <= 0:
        try:
            part.unlink(missing_ok=True)
        except Exception:
            pass
        write_state({"stage": "failed", "version": version, "reason": "Downloaded file was empty", "package": str(target), "bytes": bytes_written})
        raise ValueError("Downloaded update file is empty.")

    os.replace(part, target)


def _install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return BASE_DIR.resolve()


def _is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def _updater_exe_path() -> Path:
    app_dir = _install_dir()
    candidates = [
        app_dir / "OPS ROOM Updater.exe",
        app_dir / "_internal" / "OPS ROOM Updater.exe",
        BASE_DIR / "OPS ROOM Updater.exe",
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError("OPS ROOM Updater.exe was not found in the installation folder.")


def _safe_rmtree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _extract_updater_from_package(package: Path, staging: Path) -> Path | None:
    """Extract the updater shipped inside the downloaded package, if present.

    This lets a new release replace a broken older updater. The downloaded
    package is already SHA256-verified before this runs.
    """
    extract_dir = staging / "new_updater_runtime"
    _safe_rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(package) as zf:
            names = zf.namelist()
            exe_name = next((name for name in names if name.replace('\\', '/').endswith('OPS ROOM Updater.exe')), '')
            if not exe_name:
                return None
            root = exe_name.replace('\\', '/').rsplit('/', 1)[0]
            prefixes = [root + '/', root.rsplit('/', 1)[0] + '/_internal/' if '/' in root else '_internal/']
            wanted = []
            for name in names:
                clean = name.replace('\\', '/')
                if clean == exe_name.replace('\\', '/') or any(clean.startswith(prefix) for prefix in prefixes if prefix):
                    wanted.append(name)
            for name in wanted:
                clean = name.replace('\\', '/')
                if clean.endswith('/'):
                    continue
                if clean == exe_name.replace('\\', '/'):
                    rel = Path('OPS ROOM Updater.exe')
                else:
                    # Preserve _internal beside updater where PyInstaller expects it.
                    idx = clean.find('_internal/')
                    rel = Path(clean[idx:]) if idx >= 0 else Path(clean).name
                target = extract_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, target.open('wb') as dst:
                    shutil.copyfileobj(src, dst)
        updater = extract_dir / 'OPS ROOM Updater.exe'
        return updater if updater.is_file() else None
    except Exception:
        _safe_rmtree(extract_dir)
        return None


def _stage_updater_runtime(updater_source: Path, staging: Path) -> Path:
    """Copy the updater in a way that survives PyInstaller one-folder builds."""
    updater_run = staging / "OPS ROOM Updater.exe"
    shutil.copy2(updater_source, updater_run)

    install_dir = _install_dir()
    source_internal = updater_source.parent / "_internal"
    if not source_internal.is_dir():
        candidate = install_dir / "_internal"
        if candidate.is_dir():
            source_internal = candidate
    if source_internal.is_dir():
        target_internal = staging / "_internal"
        if target_internal.exists():
            shutil.rmtree(target_internal, ignore_errors=True)
        shutil.copytree(source_internal, target_internal)
    return updater_run


def prepare_update(manifest: dict[str, Any]) -> dict[str, Any]:
    download_url = str(manifest.get("download_url") or manifest.get("url") or "").strip()
    expected_sha = str(manifest.get("sha256") or "").strip().lower()
    latest = normalize_version(manifest.get("latest_version") or manifest.get("version") or "")
    if not (Version.parse(current_version()) < Version.parse(latest)):
        clear_state("prepare skipped because remote version is not newer")
        raise ValueError(f"Remote version v{latest} is not newer than installed v{current_version()}.")
    if not download_url:
        raise ValueError("The update manifest does not provide a download_url or url.")
    if not expected_sha:
        raise ValueError("The update manifest does not provide a SHA256 checksum.")
    staging = app_data_dir() / "updates" / f"v{latest or int(time.time())}"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    package = staging / f"OPS_ROOM_v{latest}_Windows_x64.zip"
    write_state({"stage": "downloading", "version": latest, "package": str(package)})
    _download(download_url, package, latest)
    actual_sha = _sha256(package).lower()
    # v0.25.17 polish: constant-time compare so a side-channel on the bytes-
    # length of the slowly-computed digest cannot be used to fingerprint
    # progress (the SHA256 is already public via update.json, this is
    # defense-in-depth only).
    if not secrets.compare_digest(actual_sha, expected_sha):
        write_state({"stage": "failed", "version": latest, "reason": "SHA256 mismatch", "expected": expected_sha, "actual": actual_sha, "package": str(package)})
        raise ValueError("Downloaded update failed SHA256 verification.")
    try:
        with zipfile.ZipFile(package) as zf:
            bad = zf.testzip()
            if bad:
                raise ValueError(f"ZIP integrity check failed at {bad}")
    except Exception:
        write_state({"stage": "failed", "version": latest, "reason": "ZIP verification failed", "package": str(package)})
        raise

    packaged_updater = _extract_updater_from_package(package, staging)
    if packaged_updater and packaged_updater.is_file():
        updater_run = packaged_updater
        updater_source_label = "package"
    else:
        updater_source = _updater_exe_path()
        updater_run = _stage_updater_runtime(updater_source, staging)
        updater_source_label = "installed"
    write_state({"stage": "ready", "version": latest, "package": str(package), "sha256": actual_sha, "updater": str(updater_run), "updater_source": updater_source_label})
    return {"ok": True, "version": latest, "package": str(package), "staging": str(staging), "updater": str(updater_run)}


def _candidate_updaters(package_path: Path, updater: str = "") -> list[Path]:
    candidates: list[Path] = []
    if updater:
        candidates.append(Path(updater))
    state_updater = str(read_state().get("updater") or "").strip()
    if state_updater:
        candidates.append(Path(state_updater))
    candidates.extend([
        package_path.parent / "new_updater_runtime" / "OPS ROOM Updater.exe",
        package_path.parent / "OPS ROOM Updater.exe",
    ])
    try:
        candidates.append(_updater_exe_path())
    except Exception:
        pass
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def launch_prepared_update(package: str, version: str = "", updater: str = "") -> dict[str, Any]:
    package_path = Path(package)
    if not package_path.is_file():
        raise FileNotFoundError("Prepared update package was not found.")

    target_dir = _install_dir()
    app_exe = target_dir / "OPS ROOM.exe"
    updater_run = next((p for p in _candidate_updaters(package_path, updater) if p.is_file()), None)
    if updater_run is None:
        write_state({"stage": "failed", "version": version, "package": str(package_path), "reason": "No updater executable was available to launch."})
        raise FileNotFoundError("No staged updater executable was available to launch.")
    if _is_inside(updater_run, target_dir):
        write_state({"stage": "failed", "version": version, "package": str(package_path), "target": str(target_dir), "updater": str(updater_run), "reason": "Refused to launch updater from the folder being replaced."})
        raise PermissionError(f"Refused to launch updater from the install folder being replaced: {updater_run}")

    args = [
        str(updater_run),
        "--package", str(package_path),
        "--target", str(target_dir),
        "--app-exe", str(app_exe),
        "--pid", str(os.getpid()),
        "--version", version or "",
    ]
    write_state({"stage": "launching", "version": version, "package": str(package_path), "target": str(target_dir), "updater": str(updater_run)})
    subprocess.Popen(args, close_fds=True, cwd=str(updater_run.parent))
    return {"ok": True, "message": "OPS ROOM will close and the updater will continue.", "target": str(target_dir), "updater": str(updater_run)}


def prepare_and_launch(manifest: dict[str, Any]) -> dict[str, Any]:
    prepared = prepare_update(manifest)
    return launch_prepared_update(prepared["package"], version=prepared.get("version", ""), updater=prepared.get("updater", ""))
