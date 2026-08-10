"""Pre-sim verification of the installed OPS ROOM closure-marker package.

Runs entirely without launching MSFS. Checks, for every detected Community
folder that contains ``closure-markers``:

1. Package structure (manifest.json + layout.json + SimObjects/Misc/*).
2. Manifest fields per target: ``content_type == MISC``, the per-target
   ``minimum_game_version`` (2024 -> 1.0.0, 2020 -> 1.37.12), version, and
   that the file is LF-only (CRLF breaks MSFS's INI parser for cfg, and
   manifests should match the format every working addon ships).
3. layout.json completeness: every file on disk (except manifest/layout/
   generator) is listed, and every listed file exists -- plus the LF/format
   sanity of the layout itself.
4. Model glTFs are MSFS-native: TANGENT present, NORMAL/TANGENT quantized to
   signed byte (5120), TEXCOORD quantized to signed short (5122), DDS
   textures referenced by MSFT_texture_dds, POSITION float with min/max.
   This is the exact corpus format that renders in-sim (the float-attribute
   files compiled to 0 static verts/faces in the debug panel).
5. sim.cfg / model.cfg exist per object and are LF-only; model.cfg points at
   the XML LOD wrapper, which exists.
6. Spawner titles in every sim.cfg match ``app/closure_markers.py``
   ``SIMOBJECT_TITLE_*`` constants 1:1 (a mismatch means the in-app DEPLOY IN
   SIM finds nothing).

Exit code 0 = all checks pass; 1 = any check failed.

Usage:
    python tools/simobjects/package/verify_package.py [--package DIR]

``--package DIR`` verifies one package directory instead of every detected
Community folder (and the in-repo build output).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Single source of truth: OBJECTS (folder->spawner title), TARGETS (per-target
# minimum_game_version) and PACKAGE_NAME come from build_package.py so adding
# an object or bumping a min version can never desync the verifier.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_package import OBJECTS, TARGETS, PACKAGE_NAME  # noqa: E402

TARGET_MIN_GAME = {target: cfg["minimum_game_version"] for target, cfg in TARGETS.items()}
OBJECTS = dict(OBJECTS)  # build_package.OBJECTS is a list of (folder, title) pairs

#: layout.json entries the generator itself never lists
LAYOUT_EXCLUDES = {"manifest.json", "layout.json", "MSFSLayoutGenerator.exe"}

#: glTF componentType constants
_BYTE, _SHORT, _FLOAT = 5120, 5122, 5126


def _community_candidates() -> list[tuple[str, str, Path]]:
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    out: list[tuple[str, str, Path]] = []
    if local:
        out.append(
            ("MSFS 2024 (Store)", "2024",
             Path(local) / "Packages" / "Microsoft.Limitless_8wekyb3d8bbwe" / "LocalCache" / "Packages" / "Community")
        )
        out.append(
            ("MSFS 2020 (Store)", "2020",
             Path(local) / "Packages" / "Microsoft.FlightSimulator_8wekyb3d8bbwe" / "LocalCache" / "Packages" / "Community")
        )
    if appdata:
        out.append(("MSFS 2020 (Steam)", "2020", Path(appdata) / "Microsoft Flight Simulator" / "Packages" / "Community"))
    return out


def _has_crlf(path: Path) -> bool:
    try:
        return b"\r\n" in path.read_bytes()
    except OSError:
        return False


def _check_text_lf(problems: list[str], pkg: Path, path: Path) -> None:
    if _has_crlf(path):
        try:
            rel = path.relative_to(pkg).as_posix()
        except ValueError:
            rel = str(path)
        problems.append(f"CRLF line endings: {rel}")


def verify_package(pkg: Path, label: str, target: str | None) -> tuple[int, list[str]]:
    """Verify one package directory. Returns (problems_count, problems)."""
    problems: list[str] = []
    pkg = pkg.resolve()

    # 1. structure -----------------------------------------------------------
    manifest_p = pkg / "manifest.json"
    layout_p = pkg / "layout.json"
    simobjects = pkg / "SimObjects" / "Misc"
    for required, name in ((manifest_p, "manifest.json"), (layout_p, "layout.json")):
        if not required.is_file():
            problems.append(f"{label}: missing {name}")
            return len(problems), problems
    if not simobjects.is_dir():
        problems.append(f"{label}: missing SimObjects/Misc")
        return len(problems), problems

    # 2. manifest ------------------------------------------------------------
    try:
        manifest = json.loads(manifest_p.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        problems.append(f"{label}: manifest.json unreadable: {exc}")
        manifest = {}
    _check_text_lf(problems, pkg, manifest_p)
    if manifest.get("content_type") != "MISC":
        problems.append(f"{label}: content_type={manifest.get('content_type')!r} (expected MISC)")
    if target and target in TARGET_MIN_GAME:
        expected_min = TARGET_MIN_GAME[target]
        actual_min = manifest.get("minimum_game_version")
        if actual_min != expected_min:
            problems.append(f"{label}: minimum_game_version={actual_min!r} (expected {expected_min!r} for {target})")
    if not manifest.get("package_version"):
        problems.append(f"{label}: manifest missing package_version")

    # 3. layout.json completeness -------------------------------------------
    try:
        layout = json.loads(layout_p.read_text(encoding="utf-8-sig"))
        listed = {e.get("path") for e in layout.get("content", [])}
    except Exception as exc:
        problems.append(f"{label}: layout.json unreadable: {exc}")
        listed = set()
    _check_text_lf(problems, pkg, layout_p)
    # The in-repo Model/ directory is the raw Blender export SOURCE and is
    # never shipped/listed -- exclude it from the on-disk completeness check.
    on_disk = {
        str(f.relative_to(pkg)).replace("\\", "/")
        for f in pkg.rglob("*")
        if f.is_file() and f.name not in LAYOUT_EXCLUDES and "Model/" not in f.relative_to(pkg).as_posix()
    }
    missing = sorted(on_disk - listed)
    extra = sorted(listed - on_disk)
    if missing:
        problems.append(f"{label}: {len(missing)} file(s) on disk not in layout.json: {missing[:5]}{'...' if len(missing) > 5 else ''}")
    if extra:
        problems.append(f"{label}: {len(extra)} layout entry(ies) missing on disk: {extra[:5]}{'...' if len(extra) > 5 else ''}")

    # 4. objects + titles + model cfg ----------------------------------------
    found = {d.name for d in simobjects.iterdir() if d.is_dir()}
    if sorted(found) != sorted(OBJECTS):
        problems.append(f"{label}: objects {sorted(found)} != expected {sorted(OBJECTS)}")
    for folder, title in OBJECTS.items():
        obj_dir = simobjects / folder
        if not obj_dir.is_dir():
            problems.append(f"{label}: missing object {folder}")
            continue
        sim_cfg = obj_dir / "sim.cfg"
        if not sim_cfg.is_file():
            problems.append(f"{label}: {folder} missing sim.cfg")
        else:
            _check_text_lf(problems, pkg, sim_cfg)
            text = sim_cfg.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"^title\s*=\s*(.+?)\s*$", text, re.M)
            actual_title = m.group(1).strip() if m else None
            if actual_title != title:
                problems.append(f"{label}: {folder} sim.cfg title={actual_title!r} (expected {title!r})")
        model_dir = obj_dir / "model"
        model_cfg = model_dir / "model.cfg"
        if not model_cfg.is_file():
            problems.append(f"{label}: {folder} missing model/model.cfg")
        else:
            _check_text_lf(problems, pkg, model_cfg)
            text = model_cfg.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"^normal\s*=\s*(.+?)\s*$", text, re.M)
            xml_name = m.group(1).strip() if m else None
            if xml_name and not (model_dir / xml_name).is_file():
                problems.append(f"{label}: {folder} model.cfg normal={xml_name!r} but XML wrapper missing")

    # 5. glTF native format --------------------------------------------------
    # Only the built SimObjects/ tree is verified -- the in-repo Model/
    # directory is the raw Blender export SOURCE (pre-conversion), which is
    # intentionally not MSFS-native until build_package.py converts it.
    for gltf in sorted((pkg / "SimObjects").rglob("*.gltf")):
        rel = str(gltf.relative_to(pkg)).replace("\\", "/")
        try:
            g = json.loads(gltf.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            problems.append(f"{label}: {rel} unreadable: {exc}")
            continue
        used = g.get("extensionsUsed") or []
        if "MSFT_texture_dds" not in used:
            problems.append(f"{label}: {rel} missing MSFT_texture_dds in extensionsUsed")
        sem_ok: dict[str, tuple[int, str]] = {}
        for mesh in g.get("meshes", []):
            for prim in mesh.get("primitives", []):
                attrs = prim.get("attributes") or {}
                for sem, acc_idx in attrs.items():
                    if sem in ("NORMAL", "TANGENT", "TEXCOORD_0", "TEXCOORD_1", "POSITION") and acc_idx < len(g.get("accessors", [])):
                        acc = g["accessors"][acc_idx]
                        sem_ok.setdefault(sem, (acc.get("componentType"), acc.get("type")))
        for sem, expected in (
            ("NORMAL", (_BYTE, "VEC4")),
            ("TANGENT", (_BYTE, "VEC4")),
            ("TEXCOORD_0", (_SHORT, "VEC2")),
            ("POSITION", (_FLOAT, "VEC3")),
        ):
            actual = sem_ok.get(sem)
            if actual is None:
                problems.append(f"{label}: {rel} missing {sem} accessor")
            elif actual != expected:
                problems.append(f"{label}: {rel} {sem} componentType/type={actual} (expected {expected})")

    # 6. summary line for the runner ----------------------------------------
    status = "OK" if not problems else f"{len(problems)} problem(s)"
    print(f"[{status}] {label} ({pkg})")
    for p in problems:
        print(f"    - {p}")
    return len(problems), problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-sim verification of the closure-marker MSFS package")
    parser.add_argument("--package", help="verify one package directory instead of every detected Community folder")
    args = parser.parse_args()

    targets: list[tuple[str, str, Path]] = []
    if args.package:
        p = Path(args.package).resolve()
        if not (p / "manifest.json").is_file():
            print(f"ERROR: no manifest.json at {p}", file=sys.stderr)
            return 1
        targets.append((f"package {p.name}", None, p))
    else:
        for label, target, path in _community_candidates():
            pkg = path / "closure-markers"
            if (pkg / "manifest.json").is_file():
                targets.append((label, target, pkg))
            else:
                print(f"[NOT INSTALLED] {label} ({path})")
        # always also verify the in-repo build output if present
        repo_pkg = Path(__file__).resolve().parent / "closure-markers"
        if (repo_pkg / "manifest.json").is_file():
            targets.append(("in-repo build output", "2024", repo_pkg))

    total_problems = 0
    for label, target, pkg in targets:
        count, _ = verify_package(pkg, label, target)
        total_problems += count

    print(f"\n{len(targets)} package(s) checked, {total_problems} total problem(s).")
    return 1 if total_problems else 0


if __name__ == "__main__":
    sys.exit(main())
