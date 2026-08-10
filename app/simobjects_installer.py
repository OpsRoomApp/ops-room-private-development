"""First-run auto-install of the OPS ROOM NOTAM closure-marker package.

Copies the built ``closure-markers`` package (manifest.json + layout.json +
SimObjects/Misc/*) into every detected MSFS Community folder so NOTAM
closure markers work out of the box for MSFS 2020 (Store and Steam) and
MSFS 2024. Mirrors the vPilot bridge auto-install philosophy: best-effort,
never blocks app startup, and reports per-folder status for the UI.

The package source is located next to the app (dist layout ships it as
``<app>/closure-markers``) or in the repo build tree
(``tools/simobjects/package/closure-markers``) in dev mode.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger("opsroom.simobjects_installer")

PACKAGE_NAME = "closure-markers"
PACKAGE_TITLE = "OPS ROOM NOTAM Closure Markers"

#: Per-target manifest minimum_game_version. The Community-folder package
#: format is identical between 2020 and 2024; only this field (and the real
#: install path) differ. Ground truth from working addons on this machine:
#: 2020 packages ship realistic SU versions (asfs = 1.37.12,
#: fcs-flightcontrolspotter = 1.39.9), 2024 packages ship 1.x values or 0.0.0.
_TARGET_MIN_GAME_VERSION = {"2024": "1.0.0", "2020": "1.37.12"}

#: (label, target, candidate Path) for every MSFS Community folder
#: convention. MSFS 2024 is the Store (Microsoft.Limitless_8wekyb3d8bbwe).
#: MSFS 2020 is the Store package (Microsoft.FlightSimulator_8wekyb3d8bbwe)
#: or the Steam %APPDATA% location.
def _community_folder_candidates() -> list[tuple[str, str, Path]]:
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    out: list[tuple[str, str, Path]] = []
    if local:
        out.append(
            (
                "MSFS 2024 (Store)",
                "2024",
                Path(local) / "Packages" / "Microsoft.Limitless_8wekyb3d8bbwe" / "LocalCache" / "Packages" / "Community",
            )
        )
        out.append(
            (
                "MSFS 2020 (Store)",
                "2020",
                Path(local) / "Packages" / "Microsoft.FlightSimulator_8wekyb3d8bbwe" / "LocalCache" / "Packages" / "Community",
            )
        )
    if appdata:
        out.append(("MSFS 2020 (Steam)", "2020", Path(appdata) / "Microsoft Flight Simulator" / "Packages" / "Community"))
    return out


def _manifest_for_target(source: Path, target: str) -> dict[str, Any]:
    """manifest.json payload for a target. Base fields (title, version,
    release_notes) are read from the built source package's manifest so the
    installer can never drift from build_package.py's PACKAGE_VERSION on a
    version bump; only ``minimum_game_version`` is rewritten per target.
    """
    base: dict[str, Any] = {
        "dependencies": [],
        "content_type": "MISC",
        "title": PACKAGE_TITLE,
        "manufacturer": "OPS ROOM",
        "creator": "OPS ROOM",
        "package_version": _package_version(source) or "0",
        "minimum_game_version": _TARGET_MIN_GAME_VERSION.get(target, "1.0.0"),
        "release_notes": {
            "neutral": {
                "LastUpdate": (
                    "NOTAM runway/taxiway closure markers: runway threshold X mats, "
                    "taxiway X mats, alternating orange/white water-filled barriers, "
                    "and a vertical LED X marker with red hub beacon (44 amber LED "
                    "fixtures via ASOBO_macro_light)."
                )
            }
        },
    }
    try:
        existing = json.loads((source / "manifest.json").read_text(encoding="utf-8-sig"))
        for key in ("title", "manufacturer", "creator", "package_version", "release_notes"):
            if existing.get(key) is not None:
                base[key] = existing[key]
    except Exception:
        pass  # fall back to the defaults above
    return base


def _package_roots() -> list[Path]:
    """Every place the built closure-markers package can live, nearest first."""
    roots: list[Path] = []
    try:
        if getattr(sys, "frozen", False):
            roots.append(Path(sys.executable).resolve().parent)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(Path(meipass))
    except Exception:
        pass
    roots.extend([Path.cwd(), Path(__file__).resolve().parents[1]])
    candidates: list[Path] = []
    for root in roots:
        candidates.extend(
            [
                root / PACKAGE_NAME,
                root / "_internal" / PACKAGE_NAME,
                root / "tools" / "simobjects" / "package" / PACKAGE_NAME,
            ]
        )
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate).lower()
        if key not in seen and (candidate / "manifest.json").exists():
            seen.add(key)
            unique.append(candidate)
    return unique


def _package_version(pkg: Path) -> str:
    try:
        manifest = json.loads((pkg / "manifest.json").read_text(encoding="utf-8-sig"))
        return str(manifest.get("package_version") or "0")
    except Exception:
        return "0"


def detect_community_folders() -> list[dict[str, Any]]:
    """Report every detected Community folder and whether the package is there."""
    result: list[dict[str, Any]] = []
    for label, target, path in _community_folder_candidates():
        entry: dict[str, Any] = {
            "label": label,
            "target": target,
            "path": str(path),
            "exists": path.exists(),
            "installed": False,
            "installed_version": "",
            "minimum_game_version": _TARGET_MIN_GAME_VERSION.get(target, "1.0.0"),
        }
        target = path / PACKAGE_NAME
        if target.is_dir() and (target / "manifest.json").is_file():
            entry["installed"] = True
            entry["installed_version"] = _package_version(target)
        result.append(entry)
    return result


def install_package() -> dict[str, Any]:
    """Copy the built package into every detected Community folder (idempotent)."""
    sources = _package_roots()
    if not sources:
        return {
            "ok": False,
            "reason": f"{PACKAGE_TITLE} package not found in app bundle",
            "installed": [],
        }
    source = sources[0]
    installed: list[dict[str, Any]] = []
    for label, folder_target, path in _community_folder_candidates():
        if not path.exists():
            continue
        dest = path / PACKAGE_NAME
        try:
            # Guard: never churn an up-to-date install. The launcher calls
            # install_package() on every app start; wiping + re-copying an
            # identical package can leave the sim seeing a half-copied
            # package while it is running (and previously reverted the
            # SDK-compiled build to a broken converter build). Only
            # reinstall when the version is missing or differs.
            if dest.is_dir() and (dest / "manifest.json").is_file():
                if _package_version(dest) == _package_version(source):
                    installed.append({
                        "label": label,
                        "target": folder_target,
                        "path": str(dest),
                        "ok": True,
                        "version": _package_version(dest),
                        "skipped": True,
                    })
                    continue
            if dest.exists():
                shutil.rmtree(dest)
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / "layout.json", dest / "layout.json")
            shutil.copytree(source / "SimObjects", dest / "SimObjects")
            # Manifest is rewritten per folder so 2020 installs carry a
            # realistic 2020 minimum_game_version (1.37.12) and 2024 installs
            # carry 1.0.0 -- never copy the source manifest verbatim across
            # targets. Written with LF so the whole package stays LF. Base
            # fields (title/version/notes) come from the source manifest so
            # version bumps can never desync from build_package.py.
            (dest / "manifest.json").write_text(
                json.dumps(_manifest_for_target(source, folder_target), indent=2).replace("\r\n", "\n") + "\n",
                encoding="utf-8",
            )
            # Normalize to LF everywhere. MSFS's INI parser keeps a trailing \r
            # from CRLF lines in the value, so a CRLF sim.cfg makes the
            # SimObject title never match the spawner index -- the object
            # disappears and AICreateSimulatedObject(title) finds nothing.
            for text_file in dest.rglob("*"):
                if text_file.is_file() and text_file.suffix.lower() in (".cfg", ".json", ".xml", ".txt"):
                    try:
                        raw = text_file.read_bytes()
                        if b"\r\n" in raw:
                            text_file.write_bytes(raw.replace(b"\r\n", b"\n"))
                    except OSError:
                        continue
            installed.append({"label": label, "target": folder_target, "path": str(dest), "ok": True, "version": _package_version(dest)})
            _LOGGER.info("installed %s into %s", PACKAGE_NAME, dest)
        except Exception as exc:  # pragma: no cover - per-folder guard
            _LOGGER.warning("failed to install %s into %s: %s", PACKAGE_NAME, path, exc)
            installed.append({"label": label, "target": folder_target, "path": str(dest), "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    if not installed:
        return {"ok": True, "reason": "no MSFS Community folder detected", "installed": [], "source": str(source)}
    ok_count = sum(1 for item in installed if item.get("ok"))
    skipped = sum(1 for item in installed if item.get("skipped"))
    reason = f"installed into {ok_count}/{len(installed)} Community folder(s)"
    if skipped:
        reason += f" ({skipped} already up to date)"
    return {
        "ok": ok_count > 0 or skipped > 0,
        "reason": reason,
        "installed": installed,
        "source": str(source),
    }


def install_status() -> dict[str, Any]:
    """Best-effort status for the UI (no filesystem writes)."""
    sources = _package_roots()
    return {
        "ok": True,
        "package": PACKAGE_TITLE,
        "package_available": bool(sources),
        "package_version": _package_version(sources[0]) if sources else "",
        "community_folders": detect_community_folders(),
    }
