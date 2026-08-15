"""First-run auto-install of the OPS ROOM MSFS Community packages.

Copies every built package (NOTAM closure markers, the in-game tablet panel,
and the native MSFS 2024 EFB app) into every detected MSFS Community folder so
they work out of the box. The closure markers and tablet panel support MSFS
2020 (Store and Steam) and MSFS 2024 (Store and Steam); the EFB app is
MSFS 2024 only (2020 has no EFB). Mirrors the vPilot bridge auto-install
philosophy: best-effort, never blocks app startup, and reports per-folder
status for the UI.

Each package source is located next to the app (dist layout ships them as
``<app>/closure-markers``, ``<app>/ops-room-tablet`` and ``<app>/ops-room-efb``)
or in the repo build tree (``tools/simobjects/package/<name>``) in dev mode.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Iterable

_LOGGER = logging.getLogger("opsroom.simobjects_installer")

#: Every MSFS Community package OPS ROOM ships. The folder name in the
#: Community directory and the package title shown in the UI. ``exclude``
#: lists top-level source dirs that must never be installed (e.g. the
#: closure-marker Blender export source ``Model/`` stays in the repo).
#: ``targets`` limits which simulator a package is installed into during
#: auto-detection (the EFB app is MSFS 2024 only).
PACKAGE_SPECS: dict[str, dict[str, Any]] = {
    "closure-markers": {"title": "OPS ROOM NOTAM Closure Markers", "exclude": {"Model"}, "targets": {"2020", "2024"}},
    "ops-room-tablet": {"title": "OPS ROOM Tablet (in-game panel)", "exclude": set(), "targets": {"2020", "2024"}},
    "ops-room-efb": {"title": "OPS ROOM EFB (native MSFS 2024 EFB app)", "exclude": set(), "targets": {"2024"}},
}
DEFAULT_PACKAGES: tuple[str, ...] = tuple(PACKAGE_SPECS)


def _targets_for(name: str) -> set[str]:
    return set(PACKAGE_SPECS[name].get("targets") or {"2020", "2024"})

#: Per-target manifest minimum_game_version. The Community-folder package
#: format is identical between 2020 and 2024; only this field (and the real
#: install path) differ. Ground truth from working addons on this machine:
#: 2020 packages ship realistic SU versions (asfs = 1.37.12,
#: fcs-flightcontrolspotter = 1.39.9), 2024 packages ship 1.x values or 0.0.0.
_TARGET_MIN_GAME_VERSION = {"2024": "1.0.0", "2020": "1.37.12"}

#: (label, target, candidate Path) for every MSFS Community folder
#: convention. MSFS 2024 is the Store package (Microsoft.Limitless_8wekyb3d8bbwe)
#: or the Steam %APPDATA% location; MSFS 2020 is the Store package
#: (Microsoft.FlightSimulator_8wekyb3d8bbwe) or the Steam %APPDATA% location.
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
        out.append(("MSFS 2024 (Steam)", "2024", Path(appdata) / "Microsoft Flight Simulator 2024" / "Packages" / "Community"))
    return out


def _package_version(pkg: Path) -> str:
    try:
        manifest = json.loads((pkg / "manifest.json").read_text(encoding="utf-8-sig"))
        return str(manifest.get("package_version") or "0")
    except Exception:
        return "0"


def _manifest_for_target(source: Path, target: str) -> dict[str, Any]:
    """manifest.json payload for a target. Base fields (title, version,
    release_notes) are read from the built source package's manifest so the
    installer can never drift from the build scripts on a version bump; only
    ``minimum_game_version`` is rewritten per target.
    """
    base: dict[str, Any] = {
        "dependencies": [],
        "content_type": "MISC",
        "title": "OPS ROOM",
        "manufacturer": "OPS ROOM",
        "creator": "OPS ROOM",
        "package_version": _package_version(source) or "0",
        "minimum_game_version": _TARGET_MIN_GAME_VERSION.get(target, "1.0.0"),
        "release_notes": {"neutral": {"LastUpdate": ""}},
    }
    try:
        existing = json.loads((source / "manifest.json").read_text(encoding="utf-8-sig"))
        for key in ("dependencies", "content_type", "title", "manufacturer", "creator", "package_version", "release_notes"):
            if existing.get(key) is not None:
                base[key] = existing[key]
    except Exception:
        pass  # fall back to the defaults above
    return base


def _package_roots(name: str) -> list[Path]:
    """Every place the built ``name`` package can live, nearest first."""
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
                root / name,
                root / "_internal" / name,
                root / "tools" / "simobjects" / "package" / name,
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


def _package_available(name: str) -> bool:
    return bool(_package_roots(name))


def detect_community_folders() -> list[dict[str, Any]]:
    """Report every detected Community folder and which packages are there."""
    result: list[dict[str, Any]] = []
    for label, target, path in _community_folder_candidates():
        packages: dict[str, Any] = {}
        any_installed = False
        first_version = ""
        for name in PACKAGE_SPECS:
            if target not in _targets_for(name):
                continue
            target_dir = path / name
            installed = target_dir.is_dir() and (target_dir / "manifest.json").is_file()
            version = _package_version(target_dir) if installed else ""
            packages[name] = {"installed": installed, "installed_version": version, "title": PACKAGE_SPECS[name]["title"]}
            if installed:
                any_installed = True
                if not first_version:
                    first_version = version
        result.append(
            {
                "label": label,
                "target": target,
                "path": str(path),
                "exists": path.exists(),
                "packages": packages,
                "installed": any_installed,
                "installed_version": first_version,
                "minimum_game_version": _TARGET_MIN_GAME_VERSION.get(target, "1.0.0"),
            }
        )
    return result


def install_packages(
    names: Iterable[str] | None = None,
    folders: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Copy every requested package into the requested Community folders.

    ``names`` defaults to all shipped packages; ``folders`` defaults to every
    detected Community folder. Idempotent: a folder whose copy is already at
    the same package_version is left untouched (the launcher runs this on
    every app start, and wiping + re-copying an identical package can leave
    the sim seeing a half-copied package while it is running).
    """
    selected = list(names) if names is not None else list(DEFAULT_PACKAGES)
    selected = [name for name in selected if name in PACKAGE_SPECS]
    if not selected:
        return {"ok": False, "reason": "no MSFS packages requested", "installed": []}

    sources = {name: _package_roots(name) for name in selected}
    missing = [name for name, roots in sources.items() if not roots]
    if missing:
        return {
            "ok": False,
            "reason": f"{', '.join(PACKAGE_SPECS[name]['title'] for name in missing)} package(s) not found in app bundle",
            "installed": [],
            "missing": missing,
        }

    if folders is not None:
        explicit: list[tuple[str, str, Path]] = []
        for folder in folders:
            path = Path(str(folder)).expanduser()
            explicit.append((str(path), "2024", path))
        targets = explicit
    else:
        targets = _community_folder_candidates()

    installed: list[dict[str, Any]] = []
    for label, folder_target, path in targets:
        if not path.exists():
            continue
        for name in selected:
            # Auto-detect respects each package's supported sims; an explicit
            # user-chosen folder always gets everything requested.
            if folders is None and folder_target not in _targets_for(name):
                continue
            source = sources[name][0]
            dest = path / name
            folder_entry: dict[str, Any] = {
                "package": name,
                "title": PACKAGE_SPECS[name]["title"],
                "label": label,
                "target": folder_target,
                "path": str(dest),
            }
            try:
                # Guard: never churn an up-to-date install (see docstring).
                if dest.is_dir() and (dest / "manifest.json").is_file():
                    if _package_version(dest) == _package_version(source):
                        folder_entry.update({"ok": True, "version": _package_version(dest), "skipped": True})
                        installed.append(folder_entry)
                        continue
                if dest.exists():
                    shutil.rmtree(dest)
                dest.mkdir(parents=True, exist_ok=True)
                # Copy every shipped file except manifest.json/layout.json
                # (those are rewritten/regenerated below, never copied
                # verbatim across targets) and the spec's excluded source
                # dirs (Blender model sources never leave the repo).
                exclude = set(PACKAGE_SPECS[name].get("exclude") or set())
                for item in source.iterdir():
                    if item.name in ("manifest.json", "layout.json") or item.name in exclude:
                        continue
                    if item.is_dir():
                        shutil.copytree(item, dest / item.name)
                    else:
                        shutil.copy2(item, dest / item.name)
                # Manifest is rewritten per folder so 2020 installs carry a
                # realistic 2020 minimum_game_version (1.37.12) and 2024
                # installs carry 1.0.0 -- never copy the source manifest
                # verbatim across targets. Written with LF so the whole
                # package stays LF. Base fields (title/version/notes) come
                # from the source manifest so version bumps can never desync
                # from the build scripts.
                (dest / "manifest.json").write_text(
                    json.dumps(_manifest_for_target(source, folder_target), indent=2).replace("\r\n", "\n") + "\n",
                    encoding="utf-8",
                )
                # layout.json is target-agnostic (paths only), so copy the
                # build's version verbatim when present (preserves the exact
                # MSFSLayoutGenerator output, including path case); only
                # regenerate when the source has none.
                src_layout = source / "layout.json"
                if src_layout.is_file():
                    shutil.copy2(src_layout, dest / "layout.json")
                else:
                    (dest / "layout.json").write_text(
                        json.dumps(_layout_payload(dest), indent=2).replace("\r\n", "\n") + "\n",
                        encoding="utf-8",
                    )
                # Normalize to LF everywhere. MSFS's INI parser keeps a
                # trailing \r from CRLF lines in the value, so a CRLF
                # sim.cfg makes the SimObject title never match the spawner
                # index -- the object disappears and
                # AICreateSimulatedObject(title) finds nothing.
                for text_file in dest.rglob("*"):
                    if text_file.is_file() and text_file.suffix.lower() in (".cfg", ".json", ".xml", ".txt"):
                        try:
                            raw = text_file.read_bytes()
                            if b"\r\n" in raw:
                                text_file.write_bytes(raw.replace(b"\r\n", b"\n"))
                        except OSError:
                            continue
                folder_entry.update({"ok": True, "version": _package_version(dest)})
                installed.append(folder_entry)
                _LOGGER.info("installed %s into %s", name, dest)
            except Exception as exc:  # pragma: no cover - per-folder guard
                _LOGGER.warning("failed to install %s into %s: %s", name, path, exc)
                folder_entry.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
                installed.append(folder_entry)
    if not installed:
        return {"ok": True, "reason": "no MSFS Community folder detected", "installed": [], "packages": selected}
    ok_count = sum(1 for item in installed if item.get("ok"))
    skipped = sum(1 for item in installed if item.get("skipped"))
    reason = f"installed {ok_count}/{len(installed)} package(s) into Community folder(s)"
    if skipped:
        reason += f" ({skipped} already up to date)"
    return {
        "ok": ok_count > 0 or skipped > 0,
        "reason": reason,
        "installed": installed,
        "packages": selected,
    }


def _layout_payload(pkg: Path) -> dict[str, Any]:
    """Regenerate layout.json for an installed copy (path/size/date). The
    shipped layout.json is target-agnostic, but re-emit it so a copied
    package can never carry stale sizes/dates."""
    import time as _time

    def _filetime(path: Path) -> int:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = _time.time()
        return int(mtime * 10_000_000 + 116444736000000000)

    content: list[dict[str, Any]] = []

    def walk(directory: Path) -> None:
        files = sorted((p for p in directory.iterdir() if p.is_file()), key=lambda p: p.name.lower())
        for path in files:
            if path.name in ("manifest.json", "layout.json"):
                continue
            content.append(
                {"path": str(path.relative_to(pkg)).replace("\\", "/"), "size": path.stat().st_size, "date": _filetime(path)}
            )
        for sub in sorted((p for p in directory.iterdir() if p.is_dir()), key=lambda p: p.name.lower()):
            walk(sub)

    walk(pkg)
    return {"content": content}


def install_package() -> dict[str, Any]:
    """Backwards-compatible alias: install every shipped package into every
    detected Community folder."""
    return install_packages()


def install_status() -> dict[str, Any]:
    """Best-effort status for the UI (no filesystem writes)."""
    packages: dict[str, Any] = {}
    for name, spec in PACKAGE_SPECS.items():
        roots = _package_roots(name)
        packages[name] = {
            "title": spec["title"],
            "available": bool(roots),
            "package_version": _package_version(roots[0]) if roots else "",
        }
    return {
        "ok": True,
        "packages": packages,
        "community_folders": detect_community_folders(),
    }
