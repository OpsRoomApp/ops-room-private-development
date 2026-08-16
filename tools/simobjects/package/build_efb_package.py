"""Build the OPS ROOM EFB app package (native MSFS 2024 EFB).

The EFB app is pure static content (JS + CSS + SVG icon); there is no .spb and
no fspackagetool step. This script regenerates ``manifest.json`` and
``layout.json`` so the shipped Community package can never drift from the
source files, mirroring ``build_tablet_package.py``.

Output layout (the standard MSFS 2024 EFB app package shape, identical to the
core ``fs-base-efb-app-*`` packages and GSX/Navigraph):

    ops-room-efb/
    ├── manifest.json
    ├── layout.json
    └── html_ui/
        └── efb_ui/
            └── efb_apps/
                └── OPSRoomEfb/
                    ├── OPSRoomEfb.js
                    ├── OPSRoomEfb.css
                    └── Assets/
                        └── app-icon.svg

Usage:
    python tools/simobjects/package/build_efb_package.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PACKAGE_NAME = "ops-room-efb"
PACKAGE_TITLE = "OPS ROOM EFB"
PACKAGE_VERSION = "0.25.1"
_MIN_GAME_VERSION = "1.0.0"

#: Windows FILETIME epoch offset: 1601-01-01 -> 1970-01-01 in 100ns units.
_FILETIME_EPOCH_DIFF = 116444736000000000

_LAYOUT_EXCLUDES = {"manifest.json", "layout.json"}


def _filetime(path: Path) -> int:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return int(mtime * 10_000_000 + _FILETIME_EPOCH_DIFF)


def _read_version() -> str:
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
        "minimum_game_version": _MIN_GAME_VERSION,
        "release_notes": {
            "neutral": {
                "LastUpdate": (
                    "OPS ROOM app for the native MSFS 2024 EFB. Opens the full operations "
                    "console (status, FIDS, dispatch, briefing, scratchpad, flight watch, "
                    "datalink, procedures, logbook, black box and more) inside the cockpit "
                    "tablet, talking to the OPS ROOM desktop app on localhost."
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


def main() -> int:
    pkg = Path(__file__).resolve().parent / PACKAGE_NAME
    if not (pkg / "html_ui" / "efb_ui" / "efb_apps" / "OPSRoomEfb").is_dir():
        print(f"ERROR: {PACKAGE_TITLE} package content not found at {pkg}", file=sys.stderr)
        return 1

    print(f"Building {PACKAGE_TITLE} package (native MSFS 2024 EFB)")
    print(f"  package: {pkg}")
    _write_manifest(pkg)
    _write_layout(pkg)
    print(f"  package ready: {pkg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
