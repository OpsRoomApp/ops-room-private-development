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
DEFAULT_VERSION = "0.25.1"


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


def _hex64(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in text):
        raise ValueError("SHA256 must be 64 hexadecimal characters.")
    return text


def _validate_manifest(data: dict[str, Any]) -> dict[str, Any]:
    latest = str(data.get("latest_version") or data.get("version") or "").strip()
    download_url = str(data.get("download_url") or data.get("url") or "").strip()
    fallback_url = str(data.get("fallback_download_url") or "").strip()
    checksum = str(data.get("sha256") or "").strip()
    if not latest:
        raise ValueError("Update manifest has no version.")
    # #78 bridge: the primary download may now be a ZIP (legacy/loose-folder
    # path, kept exactly as before) or an EXE (installer era). SHA256 is
    # mandatory for both; old updaters ignore the additive installer_* fields.
    is_zip = download_url.lower().endswith(".zip")
    is_exe = download_url.lower().endswith(".exe")
    if not download_url.lower().startswith("https://") or not (is_zip or is_exe):
        raise ValueError("Update manifest download URL must be an HTTPS ZIP or EXE.")
    if fallback_url and (not fallback_url.lower().startswith("https://") or not (fallback_url.lower().endswith(".zip") or fallback_url.lower().endswith(".exe"))):
        raise ValueError("Update manifest fallback download URL must be an HTTPS ZIP or EXE.")
    _hex64(checksum)
    # #78: optional additive installer path (installer-managed installs).
    installer_url = str(data.get("installer_url") or "").strip()
    installer_sha = str(data.get("installer_sha256") or "").strip()
    if installer_url:
        if not installer_url.lower().startswith("https://") or not installer_url.lower().endswith(".exe"):
            raise ValueError("Update manifest installer_url must be an HTTPS EXE.")
        _hex64(installer_sha)
        data["installer_url"] = installer_url
        data["installer_sha256"] = installer_sha
    # Website-primary manifests carry a GitHub fallback for the installer too.
    fallback_installer_url = str(data.get("fallback_installer_url") or "").strip()
    fallback_installer_sha = str(data.get("fallback_installer_sha256") or "").strip()
    if fallback_installer_url:
        if not fallback_installer_url.lower().startswith("https://") or not fallback_installer_url.lower().endswith(".exe"):
            raise ValueError("Update manifest fallback_installer_url must be an HTTPS EXE.")
        if fallback_installer_sha:
            _hex64(fallback_installer_sha)
            data["fallback_installer_sha256"] = fallback_installer_sha
        data["fallback_installer_url"] = fallback_installer_url
    # v0.25.60: Normalise optional fields for downstream consumers
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
    # #78: if a silent installer run closed the app before post-install
    # verification could complete, confirm the new build here on the next start
    # (the installer writes its expected target/version into update_state.json).
    try:
        verify_pending_install()
    except Exception:
        pass
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
    installer_url = str(manifest.get("installer_url") or "").strip()
    installer_sha = str(manifest.get("installer_sha256") or "").strip()
    # #78: decide which path this install takes. Installer-managed installs
    # (Inno registry key present) use the installer when the manifest offers
    # one; loose-folder/zip installs keep the zip path exactly as before. The
    # installer era (download_url itself is an .exe) uses the installer for
    # everyone.
    install_mode = "zip"
    if download_url.lower().endswith(".exe"):
        install_mode = "installer"
    elif installer_url and _installer_managed_target() is not None:
        install_mode = "installer"
    result.update({
        "ok": True,
        "manifest": manifest,
        "latest_version": latest,
        "remote_version": latest,
        "installed_version": installed,
        "download_url": download_url,
        "fallback_download_url": str(manifest.get("fallback_download_url") or "").strip(),
        "installer_url": installer_url,
        "fallback_installer_url": str(manifest.get("fallback_installer_url") or "").strip(),
        "installer_sha256": installer_sha,
        "install_mode": install_mode,
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


def _download_with_fallback(urls: list[str], target: Path, version: str = "", expected_sha: str = "") -> str:
    """Download from the first URL that works, verifying the SHA256 once.

    ``urls`` is ordered primary-first (website, then GitHub fallback). The
    fallback is used when the primary is unreachable, returns an HTTP error,
    or serves a file that fails checksum verification. The checksum is pinned
    in the manifest, so every candidate must serve the same bytes.
    """
    expected = expected_sha.lower()
    last_error: Exception | None = None
    for url in urls:
        try:
            _download(url, target, version)
            if expected:
                actual = _sha256(target).lower()
                if not secrets.compare_digest(actual, expected):
                    raise ValueError("Downloaded update failed SHA256 verification")
            return url
        except Exception as exc:
            last_error = exc
            logging.getLogger(__name__).warning(
                "Download from %s failed (%s); trying the next URL.", url, type(exc).__name__
            )
            continue
    write_state({
        "stage": "failed",
        "version": version,
        "package": str(target),
        "reason": f"{type(last_error).__name__}: {last_error}" if last_error else "No download URL available",
    })
    raise last_error or ValueError("No download URL available.")


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


# ── #78: installer bridge (installer-managed installs) ─────────────────────
# Loose-folder/zip installs keep the historical zip path exactly as before.
# Installer-managed installs (detected via the Inno uninstall registry key,
# never by assuming Program Files) download the Setup.exe, verify its SHA256,
# run it silently and verify the result before reporting success. Verification
# is deferred to the next start when the installer closes the app mid-run.


def _installer_managed_target() -> Path | None:
    """Return the install folder recorded by the Inno Setup uninstall entry.

    ``None`` means a loose-folder/zip install (or non-Windows) -- those keep
    the zip update path.
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except Exception:
        return None
    # Inno Setup registers its uninstall entry as ``{AppName}_is1`` (the AppId
    # suffix), under both HKLM and HKCU with a WOW6432Node mirror on 64-bit.
    names = ("OPS ROOM", "OPS ROOM_is1")
    subkeys = []
    for name in names:
        base = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\" + name
        wow = base.replace("SOFTWARE\\", "SOFTWARE\\WOW6432Node\\", 1)
        subkeys.append((winreg.HKEY_LOCAL_MACHINE, base))
        subkeys.append((winreg.HKEY_LOCAL_MACHINE, wow))
        subkeys.append((winreg.HKEY_CURRENT_USER, base))
        subkeys.append((winreg.HKEY_CURRENT_USER, wow))
    for hive, subkey in subkeys:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _ = winreg.QueryValueEx(key, "InstallLocation")
            if isinstance(value, str) and value.strip() and os.path.isdir(value.strip()):
                return Path(value.strip())
        except OSError:
            continue
    return None


def _run_installer_silent(installer: Path, version: str) -> dict[str, Any]:
    """Run an Inno Setup installer with the silent-install contract.

    Flags: /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- ("don't show the
    'This will install...' prompt"). UAC, if any, is triggered by the
    installer itself -- the only prompt a silent install may show. A nonzero
    exit code or a timeout is a failure; the old install is left untouched.
    """
    args = [str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"]
    write_state({"stage": "installing", "version": version, "installer": str(installer)})
    try:
        proc = subprocess.run(args, timeout=900, check=False, cwd=str(installer.parent))
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "Installer timed out after 15 minutes."}
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    if proc.returncode != 0:
        return {"ok": False, "reason": f"Installer exited with code {proc.returncode}."}
    return {"ok": True, "returncode": proc.returncode}


def _verify_target_version(target: Path, version: str) -> dict[str, Any]:
    """Confirm the new build actually landed (exe present + version matches)."""
    exe = target / "OPS ROOM.exe"
    if not exe.is_file():
        return {"ok": False, "reason": "OPS ROOM.exe was not found in the install folder after the update."}
    vfile = target / "version.json"
    if vfile.is_file():
        try:
            data = json.loads(vfile.read_text(encoding="utf-8"))
            actual = normalize_version(data.get("version") or "")
        except Exception:
            actual = ""
        if actual and actual != version:
            return {"ok": False, "reason": f"Installed version v{actual} does not match target v{version}."}
    return {"ok": True, "exe": str(exe), "version": version}


def verify_pending_install() -> dict[str, Any]:
    """Confirm a silent installer update on the next start.

    Inno's CloseApplications can terminate the running app before
    ``subprocess.run`` returns; in that case prepare_update cannot verify
    inline. The state written before install carries the expected target and
    version, so the verification happens here -- success clears the state,
    failure is recorded but never touches the (unmodified) old install.
    """
    state = read_state()
    stage = str(state.get("stage") or "")
    if stage not in ("installing", "install_pending_verify"):
        return {"ok": True, "pending": False}
    version = str(state.get("version") or "")
    target = str(state.get("target") or "")
    if not version or not target:
        return {"ok": True, "pending": False}
    result = _verify_target_version(Path(target), version)
    if result.get("ok"):
        clear_state("installer verified")
        logging.getLogger(__name__).info("Installer update verified after restart (v%s).", version)
    else:
        write_state({**state, "stage": "failed", "reason": result.get("reason") or "Post-install verification failed"})
    return {"ok": True, "pending": True, "verified": bool(result.get("ok")), "reason": result.get("reason")}


def _prepare_installer_update(manifest: dict[str, Any], download_url: str, expected_sha: str, latest: str) -> dict[str, Any]:
    """Download, verify and silently run the Setup.exe for this update."""
    installer_url = str(manifest.get("installer_url") or "").strip()
    if not installer_url:
        installer_url = download_url if download_url.lower().endswith(".exe") else ""
    installer_sha = str(manifest.get("installer_sha256") or "").strip().lower() or expected_sha
    if not installer_url:
        raise ValueError("The update manifest does not provide an installer URL for this install.")
    if not installer_sha or len(installer_sha) != 64:
        raise ValueError("The update manifest does not provide a valid installer SHA256 checksum.")
    target = _installer_managed_target()
    staging = app_data_dir() / "updates" / f"v{latest or int(time.time())}"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    installer_path = staging / f"OPS_ROOM_Setup_{latest}_Windows_x64.exe"
    write_state({"stage": "downloading", "version": latest, "installer": str(installer_path), "target": str(target) if target else ""})
    # Website (installer_url) first; the GitHub release copy is a transparent
    # fallback when the site is unreachable or serves a bad file.
    candidates = [u for u in (installer_url, str(manifest.get("fallback_installer_url") or "").strip()) if u]
    _download_with_fallback(candidates, installer_path, latest, expected_sha=installer_sha)
    # Post-install verification targets the folder the installer manages. For
    # the installer era (no registry entry yet on a loose-folder install) fall
    # back to the current install dir -- the nudge phase converts those.
    verify_target = target if target is not None else _install_dir()
    write_state({
        "stage": "installing",
        "version": latest,
        "installer": str(installer_path),
        "target": str(verify_target),
    })
    run = _run_installer_silent(installer_path, latest)
    if not run.get("ok"):
        write_state({"stage": "failed", "version": latest, "reason": run.get("reason") or "Installer failed", "installer": str(installer_path)})
        raise ValueError(run.get("reason") or "Installer failed")
    # The installer just created the registry entry, so re-probe for the
    # authoritative install folder (an exe-era install onto a loose folder
    # lands in the installer's folder, not the old one).
    verify_target = _installer_managed_target() or verify_target
    write_state({"stage": "installing", "version": latest, "installer": str(installer_path), "target": str(verify_target)})
    # The installer may have closed this app (Inno CloseApplications); if we
    # are still alive, verify inline. Otherwise verify_pending_install()
    # confirms on the next start keyed by the state above.
    result = _verify_target_version(verify_target, latest)
    if result.get("ok"):
        clear_state("installer verified")
    else:
        write_state({"stage": "install_pending_verify", "version": latest, "target": str(verify_target), "installer": str(installer_path), "reason": result.get("reason")})
    return {
        "ok": True,
        "mode": "installer",
        "version": latest,
        "installer": str(installer_path),
        "target": str(verify_target),
        "verified": bool(result.get("ok")),
        "staging": str(staging),
    }


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
    # #78 bridge: installer path for installer-managed installs (or the
    # installer era where download_url itself is the .exe); zip path otherwise.
    installer_url = str(manifest.get("installer_url") or "").strip()
    if download_url.lower().endswith(".exe") or (installer_url and _installer_managed_target() is not None):
        return _prepare_installer_update(manifest, download_url, expected_sha, latest)
    staging = app_data_dir() / "updates" / f"v{latest or int(time.time())}"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    package = staging / f"OPS_ROOM_v{latest}_Windows_x64.zip"
    write_state({"stage": "downloading", "version": latest, "package": str(package)})
    # Website (download_url) first; the GitHub release copy (fallback_download_url)
    # is a transparent fallback when the site is unreachable or serves a bad file.
    candidates = [u for u in (download_url, str(manifest.get("fallback_download_url") or "").strip()) if u]
    _download_with_fallback(candidates, package, latest, expected_sha=expected_sha)
    actual_sha = _sha256(package).lower()
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
