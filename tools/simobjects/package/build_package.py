"""Build the OPS ROOM NOTAM closure-marker MSFS package.

Restructures ``package/closure-markers`` (sim.cfg + Model/) into the exact
package format proven in-sim by the OPS ROOM Bridge and the FNX cone on MSFS
2024 (and compatible with MSFS 2020):

    closure-markers/
    ├── manifest.json              # content_type MISC
    ├── layout.json                # path/size/date (Windows FILETIME)
    └── SimObjects/
        └── Misc/
            ├── X_MARKER_RUNWAY/       sim.cfg + model/model.cfg + gltf/bin
            ├── X_MARKER_TAXIWAY/      ...
            ├── X_LIGHTED_TRAILER/     ...
            ├── BARRIER_LOW_ORANGE/    ...
            ├── BARRIER_LOW_WHITE/     ...
            ├── BARRICADE_T3_ORANGE/   ...
            └── BARRICADE_T3_WHITE/    ...

Each SimObject gets its own ``sim.cfg`` with a single ``[fltsim.0]`` entry and
``[General] category = StaticObject`` (the category the FNX cone and the OPS
ROOM Bridge use for SimConnect-spawned static objects), plus a ``model/``
folder holding ``model.cfg`` + the exported glTF/bin files (LOD0 and ``_LOD1``).

The spawner in ``app/closure_markers.py`` matches on the exact ``title``
strings, which are preserved 1:1 from the old layout.

Usage:
    python tools/simobjects/package/build_package.py [--out DIR] [--install] [--target 2024|2020|all]

``--target 2024`` (default) builds a manifest with minimum_game_version 1.0.0
and, with ``--install``, installs into the MSFS 2024 Store Community folder
only. ``--target 2020`` builds the 2020 manifest (minimum_game_version
1.37.12, matching real 2020 addons like asfs) and installs into the MSFS 2020
Store + Steam Community folders. ``--target all`` builds the 2024 manifest
and installs into EVERY detected folder, writing the right manifest per
folder (2020 folders get the 2020 manifest). ``--out DIR`` writes the package
to a custom location instead of in place.

Run this AFTER regenerating any model glTF/bin (the Blender scripts under
``tools/simobjects/blender``) so manifest.json/layout.json reflect the new
sizes and dates.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import msfs_native

PACKAGE_NAME = "closure-markers"
PACKAGE_TITLE = "OPS ROOM NOTAM Closure Markers"
PACKAGE_VERSION = "0.25.72.0"

#: Per-target manifest settings. The Community-folder package format is
#: byte-identical between MSFS 2020 and 2024 (content_type MISC, same
#: SimObjects/Misc layout, same layout.json) -- only ``minimum_game_version``
#: differs, and only the real-world install path (2024 Store vs 2020 Store /
#: 2020 Steam). Ground truth from working addons on this machine: 2020
#: packages (asfs, fcs-flightcontrolspotter) ship ``1.37.12``/``1.39.9`` with
#: no ``builder`` field; 2024 packages (asfs, gsx-efb, fsltl) ship 1.x values
#: or ``0.0.0``. A ``1.0.0`` minimum is trivially satisfied by every real
#: install, but we generate the realistic per-target value so each variant
#: looks SDK-native.
TARGETS: dict[str, dict[str, str]] = {
    "2024": {"label": "MSFS 2024 (Store)", "minimum_game_version": "1.0.0"},
    "2020": {"label": "MSFS 2020", "minimum_game_version": "1.37.12"},
}

#: (label, target, Path) for every MSFS Community folder convention. MSFS
#: 2024 is the Store package (Microsoft.Limitless_8wekyb3d8bbwe). MSFS 2020
#: is the Store package (Microsoft.FlightSimulator_8wekyb3d8bbwe) or the
#: Steam %APPDATA% location. Mirrors app/simobjects_installer.py.
def _community_folder_candidates() -> list[tuple[str, str, Path]]:
    out: list[tuple[str, str, Path]] = []
    local = os.environ.get("LOCALAPPDATA", "")
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
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        out.append(("MSFS 2020 (Steam)", "2020", Path(appdata) / "Microsoft Flight Simulator" / "Packages" / "Community"))
    return out


def _matching_community_folders(target: str | None) -> list[tuple[str, str, Path]]:
    """Every detected Community folder whose target matches ``target`` (None
    or "all" matches everything). Returns (label, target, path)."""
    matches: list[tuple[str, str, Path]] = []
    for label, folder_target, path in _community_folder_candidates():
        if target in (None, "all") or target == folder_target:
            if path.exists():
                matches.append((label, folder_target, path))
    return matches

#: (folder name, fltsim title) -- titles MUST match app/closure_markers.py
#: SIMOBJECT_TITLE_* exactly. Folder names are the SimObjects/Misc/<NAME> dirs.
OBJECTS: list[tuple[str, str]] = [
    ("X_MARKER_RUNWAY", "ORS CLOSURE MARKER X RUNWAY"),
    ("X_MARKER_TAXIWAY", "ORS CLOSURE MARKER X TAXIWAY"),
    ("X_LIGHTED_TRAILER", "ORS CLOSURE MARKER X LIGHTED"),
    ("BARRIER_LOW_ORANGE", "ORS CLOSURE BARRIER LOW ORANGE"),
    ("BARRIER_LOW_WHITE", "ORS CLOSURE BARRIER LOW WHITE"),
    ("BARRICADE_T3_ORANGE", "ORS TYPE III BARRICADE ORANGE"),
    ("BARRICADE_T3_WHITE", "ORS TYPE III BARRICADE WHITE"),
]

# NOTE: every generated file (sim.cfg, model.cfg, manifest.json) MUST be
# written with LF line endings. MSFS's INI parser keeps the trailing \r from
# CRLF lines in the value, so ``title = X\r`` never matches the indexed
# SimObject title -- the object disappears from the DevMode SimObject spawner
# and AICreateSimulatedObject(title) finds nothing. The proven bridge/FNX
# packages are all LF.
SIM_CFG_TEMPLATE = """[VERSION]
major = 1
minor = 0

[fltsim.0]
title = {title}
model =
panel =
sound =

[General]
category = StaticObject
object_class = Misc
DistanceToNotAnimate = 100000

[Surface]
IgnoreObjectsCollision = 1
"""

MODEL_CFG_TEMPLATE = """[models]
normal = {model}.xml
model =
texture =

[General]
category=StaticObject
DistanceToNotAnimate=100000
"""


def _lod_xml(model: str, has_lod1: bool) -> str:
    """ModelInfo XML LOD wrapper -- the exact pattern the OPS ROOM Bridge uses
    (``model.cfg -> normal = <name>.xml -> <LODS><LOD ModelFile=...gltf/>``).
    A stable per-model GUID keeps the wrapper deterministic across rebuilds.
    """
    guid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"opsroom://closure/{model}")).upper()
    if has_lod1:
        lods = [
            f'    <LOD MinSize="30" ModelFile="{model}.gltf"/>',
            f'    <LOD MinSize="0" ModelFile="{model}_LOD1.gltf"/>',
        ]
    else:
        lods = [f'    <LOD MinSize="0" ModelFile="{model}.gltf"/>']
    return (
        '<?xml version="1.0" encoding="utf-8" ?>\n'
        f'<ModelInfo version="1.1" guid="{{{guid}}}">\n'
        '  <LODS>\n'
        + "\n".join(lods)
        + "\n  </LODS>\n"
        "</ModelInfo>\n"
    )


def _write_lf(path: Path, text: str) -> None:
    """Write text with LF line endings only (see note above)."""
    path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))

#: Windows FILETIME epoch offset: 1601-01-01 -> 1970-01-01 in 100ns units.
#: (11644473600 seconds * 10_000_000 = 116444736000000000 -- 18 digits. The
#: earlier 20-digit value overflowed signed int64 and MSFS rejected every
#: layout.json entry, so the package loaded but no model was ever visible.)
_FILETIME_EPOCH_DIFF = 116444736000000000


def _filetime(path: Path) -> int:
    """Convert a file's mtime to a Windows FILETIME (100ns since 1601)."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = time.time()
    return int(mtime * 10_000_000 + _FILETIME_EPOCH_DIFF)


#: Files the generator must never list (same exclusions MSFSLayoutGenerator
#: applies): the manifest, the layout itself and the generator binary.
_LAYOUT_EXCLUDES = {"manifest.json", "layout.json", "MSFSLayoutGenerator.exe"}


def _layout_via_generator(out: Path) -> bool:
    """Run the official MSFSLayoutGenerator.exe against the shipped content.

    The tool writes layout.json in the exact format proven in-sim (LF line
    endings, ``path/size/date`` key order, depth-first walk order, and it
    excludes manifest.json/layout.json/itself from the content list). It is
    run against a staging copy that contains ONLY the shipped files
    (SimObjects + manifest.json) -- the in-repo ``Model/`` Blender export
    source must never be listed. Returns True when it produced a layout.json.
    Never raises.
    """
    exe = Path(__file__).resolve().parent / "MSFSLayoutGenerator.exe"
    if not exe.is_file():
        return False
    try:
        stage = out / "_layout_stage"
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True)
        shutil.copy2(out / "manifest.json", stage / "manifest.json")
        shutil.copytree(out / "SimObjects", stage / "SimObjects")
        result = subprocess.run(
            [str(exe), "layout.json"],
            cwd=str(stage),
            capture_output=True,
            text=True,
            timeout=60,
        )
        produced = result.returncode == 0 and (stage / "layout.json").is_file()
        if produced:
            shutil.copy2(stage / "layout.json", out / "layout.json")
        shutil.rmtree(stage, ignore_errors=True)
        return produced
    except Exception:
        try:
            if (out / "_layout_stage").exists():
                shutil.rmtree(out / "_layout_stage", ignore_errors=True)
        except Exception:
            pass
        return False


def _layout_fallback(out: Path) -> None:
    """Python fallback that writes layout.json in the generator's exact format.

    Used only when MSFSLayoutGenerator.exe is unavailable. Emits LF line
    endings, ``path/size/date`` key order, depth-first walk order (files
    case-insensitively sorted, subdirectories last), and skips manifest.json /
    layout.json / the generator binary -- byte-format compatible with the
    official tool.
    """
    content: list[dict] = []

    def walk(directory: Path) -> None:
        files = sorted((p for p in directory.iterdir() if p.is_file()), key=lambda p: p.name.lower())
        for path in files:
            if path.name in _LAYOUT_EXCLUDES:
                continue
            content.append(
                {"path": str(path.relative_to(out)).replace("\\", "/"), "size": path.stat().st_size, "date": _filetime(path)}
            )
        for sub in sorted((p for p in directory.iterdir() if p.is_dir()), key=lambda p: p.name.lower()):
            walk(sub)

    walk(out)
    payload = json.dumps({"content": content}, indent=2)
    (out / "layout.json").write_bytes(payload.replace("\r\n", "\n").encode("utf-8"))
    print(f"  manifest.json + layout.json written ({len(content)} files, python fallback)")


def _write_layout(out: Path) -> None:
    """Write layout.json: official MSFSLayoutGenerator first, Python fallback."""
    if _layout_via_generator(out):
        entries = 0
        try:
            entries = len(json.loads((out / "layout.json").read_text(encoding="utf-8-sig"))["content"])
        except Exception:
            pass
        print(f"  layout.json written by MSFSLayoutGenerator.exe ({entries} files)")
    else:
        _layout_fallback(out)


def _manifest_for(target: str) -> dict:
    """manifest.json payload for a target ("2024" or "2020"). Only the
    minimum_game_version differs between the two Community-folder variants.
    """
    target_cfg = TARGETS.get(target, TARGETS["2024"])
    return {
        "dependencies": [],
        "content_type": "MISC",
        "title": PACKAGE_TITLE,
        "manufacturer": "OPS ROOM",
        "creator": "OPS ROOM",
        "package_version": PACKAGE_VERSION,
        "minimum_game_version": target_cfg["minimum_game_version"],
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


def build(source: Path, out: Path, target: str = "2024") -> None:
    """Assemble the SimObjects/Misc layout + manifest.json + layout.json."""
    model_root = source / "Model"
    simobjects = out / "SimObjects" / "Misc"

    for folder, title in OBJECTS:
        obj_dir = simobjects / folder
        model_dir = obj_dir / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        _write_lf(obj_dir / "sim.cfg", SIM_CFG_TEMPLATE.format(title=title))

        src_model = model_root / folder
        if not src_model.exists():
            print(f"  WARN: no model source {src_model.relative_to(source)} -- skipping {title}")
            continue
        # Copy every exported file: LOD0 gltf/bin, _LOD1 gltf/bin, textures,
        # fixtures.json. model.cfg is regenerated (not copied) so the format is
        # always the proven one.
        copied = 0
        for item in sorted(src_model.iterdir()):
            if not item.is_file():
                continue
            name_l = item.name.lower()
            if name_l == "model.cfg":
                continue
            # QA render outputs from the Blender pipeline (_preview/_front
            # PNGs) are never referenced by any glTF -- every glTF references
            # *.dds textures only. Keep them in Model/ as the export source
            # but never ship them (they are ~1.5 MB each and add nothing
            # in-sim).
            if name_l.endswith("_preview.png") or name_l.endswith("_front.png"):
                print(f"    skip QA render (not shipped): {item.name}")
                continue
            # .dds included so re-exports whose Blender hook already converted
            # textures to DDS (msfs_native) carry their textures into the
            # package -- the glTF then references *.dds, not *.png.
            if item.suffix.lower() not in {".gltf", ".bin", ".png", ".dds", ".json"}:
                continue
            if name_l.endswith(".blend") or name_l.endswith(".blend1"):
                continue
            shutil.copy2(item, model_dir / item.name)
            # Normalize line endings on text files (fixtures.json etc.) so the
            # whole package is LF -- see the note on SIM_CFG_TEMPLATE.
            if item.suffix.lower() in (".json", ".xml", ".txt"):
                _write_lf(model_dir / item.name, item.read_text(encoding="utf-8", errors="replace"))
            copied += 1
        # Convert every exported glTF to MSFS-native (ASOBO extensions: the
        # stock Khronos exporter output silently fails to render in-sim). Then
        # write the XML LOD wrapper + model.cfg that points at it, mirroring
        # the proven bridge/FNX pattern.
        for gt in sorted(model_dir.glob("*.gltf")):
            msfs_native.convert_file(gt)
        # Drop any .png the converter already baked into .dds -- after
        # conversion every glTF references *.dds only, so leftover texture
        # sources (small stripes, material maps) are dead weight in the
        # shipped package. QA renders are already skipped at copy time.
        referenced = set()
        for gt in sorted(model_dir.glob("*.gltf")):
            try:
                gltf = json.loads(gt.read_text(encoding="utf-8-sig"))
                for img in gltf.get("images", []):
                    uri = img.get("uri")
                    if uri:
                        referenced.add(Path(uri).name.lower())
            except Exception:
                continue
        for leftover in sorted(model_dir.glob("*.png")):
            if leftover.name.lower() not in referenced:
                leftover.unlink()
                print(f"    removed converted texture source (not referenced): {leftover.name}")
        has_lod1 = (model_dir / f"{folder}_LOD1.gltf").exists()
        _write_lf(model_dir / f"{folder}.xml", _lod_xml(folder, has_lod1))
        _write_lf(model_dir / "model.cfg", MODEL_CFG_TEMPLATE.format(model=folder))
        print(f"  {folder}: {copied} files + native glTF -> {model_dir.relative_to(out)}")

    manifest = _manifest_for(target)
    _write_lf(out / "manifest.json", json.dumps(manifest, indent=2))

    # layout.json -- the SimObjects/ tree only (matches the bridge and FNX
    # packages, which do not list manifest.json/layout.json themselves). The
    # Model/ Blender source is never listed because it is not installed.
    _write_layout(out)
    print(f"  package ready: {out}")


def _install_to(out: Path, community: Path, target: str, label: str) -> None:
    """Copy the built package into one Community folder, rewriting manifest.json
    with the target's minimum_game_version. Model/ never leaves the repo.
    """
    dest = community / PACKAGE_NAME
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    # layout.json is target-agnostic (it lists SimObjects + manifest only);
    # the manifest itself is rewritten per target so 2020 installs carry a
    # realistic 2020 minimum_game_version and 2024 installs carry 1.0.0.
    shutil.copy2(out / "layout.json", dest / "layout.json")
    shutil.copytree(out / "SimObjects", dest / "SimObjects")
    _write_lf(dest / "manifest.json", json.dumps(_manifest_for(target), indent=2))
    generator = Path(__file__).resolve().parent / "MSFSLayoutGenerator.exe"
    if generator.is_file():
        shutil.copy2(generator, dest / "MSFSLayoutGenerator.exe")
    print(f"  installed [{target}] -> {dest}  ({label})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the OPS ROOM closure-marker MSFS package")
    parser.add_argument("--out", help="custom output directory (default: rewrite package/closure-markers in place)")
    parser.add_argument("--install", action="store_true", help="copy the built package into every matching MSFS Community folder")
    parser.add_argument(
        "--target",
        choices=["2024", "2020", "all"],
        default="2024",
        help="manifest + install target (default: 2024; 'all' builds 2024 and installs into every detected folder with the right manifest per folder)",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    source = root / PACKAGE_NAME

    if args.out:
        out = Path(args.out).resolve()
    else:
        out = source

    print(f"Building {PACKAGE_TITLE} v{PACKAGE_VERSION}")
    print(f"  source: {source}")

    if not (source / "Model").exists():
        print(f"ERROR: model sources not found at {source / 'Model'}", file=sys.stderr)
        return 1

    build_target = "2024" if args.target == "all" else args.target

    # Preferred pipeline: the SDK-compiled package produced by the MSFS
    # Project Editor (tools/simobjects/feedback/fspkg_stage). This is the
    # ONLY output proven to render in-sim -- the legacy msfs_native converter
    # path below has never rendered in MSFS 2024. When fresh Project Editor
    # output exists, ship it verbatim (SimObjects + layout.json + manifest).
    sdk_build = Path(__file__).resolve().parent.parent / "feedback" / "fspkg_stage" / "Packages" / PACKAGE_NAME
    if (sdk_build / "SimObjects").is_dir() and (sdk_build / "layout.json").is_file():
        if out != source:
            if out.exists():
                shutil.rmtree(out)
            out.mkdir(parents=True)
        else:
            # In-place rebuild: clear only the shipped layout, never the
            # Model/ Blender export source.
            for stale in ("SimObjects", "layout.json", "manifest.json", "sim.cfg"):
                stale_path = out / stale
                if stale_path.exists():
                    if stale_path.is_dir():
                        shutil.rmtree(stale_path)
                    else:
                        stale_path.unlink()
        shutil.copytree(sdk_build / "SimObjects", out / "SimObjects")
        shutil.copy2(sdk_build / "layout.json", out / "layout.json")
        _write_lf(out / "manifest.json", json.dumps(_manifest_for(build_target), indent=2))
        print(f"  [SDK BUILD] shipped Project Editor output from {sdk_build}")
        print(f"  package ready: {out}")
        if args.install:
            matches = _matching_community_folders(args.target)
            if not matches:
                print("ERROR: --install requested but no matching MSFS Community folder found", file=sys.stderr)
                return 1
            for label, folder_target, community in matches:
                _install_to(out, community, folder_target, label)
        print("done.")
        return 0
    print("  WARNING: no SDK/Project Editor build found at")
    print(f"    {sdk_build}")
    print("  Falling back to the legacy msfs_native converter. Its output has")
    print("  never been verified to render in MSFS 2024 -- prefer a fresh")
    print("  Project Editor build (tools/simobjects/feedback/fspkg_stage).")

    if args.out and out != source:
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        # Copy the whole tree so manifest/layout are regenerated from scratch.
        shutil.copytree(source, out / "_src_tmp")
        build(out / "_src_tmp", out, target=build_target)
        shutil.rmtree(out / "_src_tmp", ignore_errors=True)
    else:
        # Rebuild in place: clear the old SimObjects dir to avoid stale models.
        # ``Model/`` is the Blender export SOURCE and is never deleted -- the
        # builder only regenerates the shipped ``SimObjects/Misc`` layout from it.
        old = out / "SimObjects"
        if old.exists():
            shutil.rmtree(old)
        (out / "SimObjects").mkdir(parents=True)
        build(source, out, target=build_target)
        # Remove the old single-file sim.cfg (superseded by per-object sim.cfg
        # files in SimObjects/Misc/*). Model/ stays as the re-export source.
        leftover = out / "sim.cfg"
        if leftover.is_file():
            leftover.unlink()
            print("  removed old-layout root sim.cfg")

    if args.install:
        matches = _matching_community_folders(args.target)
        if not matches:
            print("ERROR: --install requested but no matching MSFS Community folder found", file=sys.stderr)
            return 1
        for label, folder_target, community in matches:
            _install_to(out, community, folder_target, label)
    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
