"""Build the OPS ROOM Tablet in-game panel package (MSFS 2020 + MSFS 2024).

Regenerates the shipped Community-folder package at ``package/ops-room-tablet``
(manifest.json + layout.json) and, when the MSFS SDK is available,
recompiles the InGamePanels ``.spb`` from the source project
(``package/ops-room-tablet-src``) so the panel definition can never drift
from the shipped binary. The committed ``.spb`` is the fallback when no SDK
is present, so the app build never hard-depends on the SDK.

Output layout (identical to proven dual-sim InGamePanels addons such as the
Input Viewer, which ships one package that runs in MSFS 2020 and 2024):

    ops-room-tablet/
    ├── manifest.json
    ├── layout.json
    ├── InGamePanels/
    │   └── InGamePanel_OPSRoomTablet.spb
    └── html_ui/
        ├── icons/toolbar/ICON_TOOLBAR_OPS_ROOM.svg
        └── InGamePanels/OPSRoomTablet/OPSRoomTablet.html

Usage:
    python tools/simobjects/package/build_tablet_package.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PACKAGE_NAME = "ops-room-tablet"
PACKAGE_TITLE = "OPS ROOM Tablet"
PACKAGE_VERSION = "0.25.0"
_MIN_GAME_VERSION_2024 = "1.0.0"

#: Windows FILETIME epoch offset: 1601-01-01 -> 1970-01-01 in 100ns units.
#: Same constant as build_package.py; MSFS rejects layout.json dates that
#: overflow signed int64.
_FILETIME_EPOCH_DIFF = 116444736000000000

_LAYOUT_EXCLUDES = {"manifest.json", "layout.json"}


def _filetime(path: Path) -> int:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = time.time()
    return int(mtime * 10_000_000 + _FILETIME_EPOCH_DIFF)


def _read_version() -> str:
    """package_version: prefer the app version.json (single source of truth),
    fall back to the constant above when building outside the repo root."""
    for candidate in (
        Path.cwd() / "version.json",
        Path(__file__).resolve().parents[2] / "version.json",
    ):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8-sig"))
            version = str(data.get("version") or "").strip()
            if version:
                return version
        except Exception:
            continue
    return PACKAGE_VERSION


def _write_manifest(pkg: Path) -> None:
    manifest = {
        "dependencies": [],
        "content_type": "MISC",
        "title": PACKAGE_TITLE,
        "manufacturer": "OPS ROOM",
        "creator": "OPS ROOM",
        "package_version": _read_version(),
        "minimum_game_version": _MIN_GAME_VERSION_2024,
        "release_notes": {
            "neutral": {
                "LastUpdate": (
                    "In-game tablet panel for MSFS 2020 and MSFS 2024. Adds an OPS ROOM "
                    "toolbar button that opens the full operations console (status, FIDS, "
                    "dispatch, briefing, scratchpad, flight watch, live map, datalink, "
                    "procedures, logbook, black box and more) as a tablet-style panel "
                    "talking to the OPS ROOM desktop app on localhost."
                )
            }
        },
    }
    (pkg / "manifest.json").write_text(
        json.dumps(manifest, indent=2).replace("\r\n", "\n") + "\n", encoding="utf-8"
    )
    print(f"  manifest.json written (package_version {manifest['package_version']})")


def _write_layout(pkg: Path) -> None:
    content: list[dict] = []

    def walk(directory: Path) -> None:
        files = sorted((p for p in directory.iterdir() if p.is_file()), key=lambda p: p.name.lower())
        for path in files:
            if path.name in _LAYOUT_EXCLUDES:
                continue
            content.append(
                {"path": str(path.relative_to(pkg)).replace("\\", "/"), "size": path.stat().st_size, "date": _filetime(path)}
            )
        for sub in sorted((p for p in directory.iterdir() if p.is_dir()), key=lambda p: p.name.lower()):
            walk(sub)

    walk(pkg)
    payload = json.dumps({"content": content}, indent=2)
    (pkg / "layout.json").write_bytes(payload.replace("\r\n", "\n").encode("utf-8"))
    print(f"  layout.json written ({len(content)} files)")


def _find_sdk_packager() -> Path | None:
    """Locate fspackagetool.exe from the 2024 or 2020 SDK. OPSROOM_MSFS_SDK
    overrides the auto-detect (same env var the camera bridge build honors)."""
    env = os.environ.get("OPSROOM_MSFS_SDK")
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env) / "Tools" / "bin" / "fspackagetool.exe")
    for root in (r"C:\MSFS 2024 SDK", r"C:\MSFS SDK"):
        candidates.append(Path(root) / "Tools" / "bin" / "fspackagetool.exe")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _appx_game_path() -> str | None:
    """Resolve the real MSFS 2024 Store package folder (the SDK's override
    file frequently points at a stale WindowsApps package version)."""
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-AppxPackage -Name 'Microsoft.Limitless*' | Select-Object -ExpandProperty InstallLocation",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        path = (result.stdout or "").strip().splitlines()
        if path and path[0]:
            return path[0]
    except Exception:
        pass
    return None


def _recompile_spb() -> bool:
    """Recompile InGamePanels/*.spb from ops-room-tablet-src when possible.

    fspackagetool reads its game-exe override from a txt file next to the
    exe; that file commonly points at a stale WindowsApps package version, so
    the tool is run from a temp copy with a corrected override. Best effort:
    any failure keeps the committed .spb and prints a warning (the app build
    must never fail because the SDK is missing or misconfigured).
    """
    packager = _find_sdk_packager()
    if not packager:
        print("  SKIP spb recompile: MSFS SDK fspackagetool.exe not found (using committed .spb)")
        return False
    root = Path(__file__).resolve().parent
    src = root / "ops-room-tablet-src"
    if not (src / "package.xml").is_file():
        print("  SKIP spb recompile: source project missing (using committed .spb)")
        return False

    override_dir = packager.parent / "fspackagetool_overrideExePath.txt"
    game_path: str | None = None
    try:
        if override_dir.is_file():
            raw = override_dir.read_text(encoding="utf-8", errors="replace").strip()
            if raw and Path(raw).exists():
                game_path = raw
    except Exception:
        pass
    if not game_path:
        game_path = _appx_game_path()

    work = Path(os.environ.get("TEMP", ".")) / "OR250" / "tablet_fspkg"
    try:
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True, exist_ok=True)
        shutil.copy2(packager, work / "fspackagetool.exe")
        if game_path:
            (work / "fspackagetool_overrideExePath.txt").write_text(game_path, encoding="ascii")
        result = subprocess.run(
            [str(work / "fspackagetool.exe"), "package.xml"],
            cwd=str(src),
            capture_output=True,
            text=True,
            timeout=90,
        )
        produced = (src / "Packages" / PACKAGE_NAME / "InGamePanels" / "InGamePanel_OPSRoomTablet.spb").is_file()
        if result.returncode == 0 or produced:
            shutil.copy2(
                src / "Packages" / PACKAGE_NAME / "InGamePanels" / "InGamePanel_OPSRoomTablet.spb",
                root / PACKAGE_NAME / "InGamePanels" / "InGamePanel_OPSRoomTablet.spb",
            )
            print("  InGamePanel_OPSRoomTablet.spb recompiled from source project")
            return True
        print("  WARN: fspackagetool failed; keeping committed .spb")
        print("    " + (result.stdout or result.stderr or "").strip().splitlines()[-1][:200] if (result.stdout or result.stderr) else "")
        return False
    except Exception as exc:
        print(f"  WARN: spb recompile skipped ({type(exc).__name__}: {exc}); keeping committed .spb")
        return False
    finally:
        # Remove the SDK tool's transient outputs (Packages/, _Temp/ and the
        # PackagesMetadata sidecar it writes next to the project) so a build
        # never leaves junk in the source tree.
        for name in ("Packages", "_Temp", "PackagesMetadata"):
            try:
                path = src / name
                if path.is_dir():
                    shutil.rmtree(path)
            except Exception:
                pass
        try:
            if work.exists():
                shutil.rmtree(work)
        except Exception:
            pass


def _sync_html_assets(src: Path, pkg: Path) -> None:
    """Copy the tablet HTML and toolbar icon from the source project into the
    final package so the two can never drift (the source tree is the single
    source of truth for panel content, exactly like the .spb)."""
    html_src = src / "PackageSources" / "html_ui" / "InGamePanels" / "OPSRoomTablet" / "OPSRoomTablet.html"
    icon_src = src / "PackageSources" / "html_ui" / "icons" / "toolbar" / "ICON_TOOLBAR_OPS_ROOM.svg"
    if html_src.is_file():
        shutil.copy2(html_src, pkg / "html_ui" / "InGamePanels" / "OPSRoomTablet" / "OPSRoomTablet.html")
        print("  OPSRoomTablet.html synced from source project")
    if icon_src.is_file():
        shutil.copy2(icon_src, pkg / "html_ui" / "icons" / "toolbar" / "ICON_TOOLBAR_OPS_ROOM.svg")
        print("  ICON_TOOLBAR_OPS_ROOM.svg synced from source project")


def main() -> int:
    root = Path(__file__).resolve().parent
    pkg = root / PACKAGE_NAME
    if not (pkg / "html_ui").is_dir() or not (pkg / "InGamePanels").is_dir():
        print(f"ERROR: {PACKAGE_TITLE} package content not found at {pkg}", file=sys.stderr)
        return 1

    print(f"Building {PACKAGE_TITLE} package (MSFS 2020 + 2024)")
    print(f"  package: {pkg}")
    _recompile_spb()
    _sync_html_assets(root / "ops-room-tablet-src", pkg)
    _write_manifest(pkg)
    _write_layout(pkg)
    print(f"  package ready: {pkg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
