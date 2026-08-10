"""Inject MSFS ``ASOBO_macro_light`` glTF extensions into closure-marker models.

MSFS 2020/2024 reads SimObject lights from the ``ASOBO_macro_light`` glTF
extension (schema verified in both SDKs: ``Schemas/ASOBO_macro_light``). The
stock Blender glTF exporter cannot write it, so this tool post-processes the
exported ``.gltf`` files:

- For ``X_LIGHTED_TRAILER``: adds a light node on each ``FIXTURE_*`` mesh node
  (amber, day/night cycled) and on ``CENTER_BEACON`` (red obstruction beacon,
  slow flash).
- For ``BARRICADE_T3_*``: adds a red beacon light on the ``BEACON`` node.

Light positions are derived from the mesh bounds already baked into the glTF
(world-space vertices), so they are always correct regardless of Blender
coordinate conventions. The tool also appends ``ASOBO_macro_light`` to
``extensionsUsed`` and adds the extension to the node itself (MSFS reads the
extension on the node and uses the node's world transform for position).

Idempotent: nodes already carrying the extension are skipped.

Usage:
    python inject_lights.py [--model <path-to-gltf> ...]
Runs on every closure-marker glTF under the package by default.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent / "closure-markers"

AMBER = [1.0, 0.72, 0.08]
RED = [1.0, 0.05, 0.02]
INTENSITY_AMBER = 9000.0
INTENSITY_RED = 6000.0


def _read_accessor_min_max(gltf: dict, accessor_index: int) -> tuple[list[float], list[float]] | None:
    try:
        accessor = gltf["accessors"][accessor_index]
        if accessor.get("min") and accessor.get("max"):
            return list(accessor["min"]), list(accessor["max"])
    except (KeyError, IndexError, TypeError):
        return None
    return None


def _node_light_position(gltf: dict, node: dict) -> list[float] | None:
    """Center of the node's mesh bounds in glTF space (fallback: node translation)."""
    mesh_index = node.get("mesh")
    if mesh_index is not None:
        try:
            mesh = gltf["meshes"][mesh_index]
        except (KeyError, IndexError, TypeError):
            mesh = None
        if mesh:
            positions: list[list[float]] = []
            for primitive in mesh.get("primitives", []):
                pos_attrib = primitive.get("attributes", {}).get("POSITION")
                if pos_attrib is None:
                    continue
                bounds = _read_accessor_min_max(gltf, pos_attrib)
                if bounds:
                    positions.append(bounds)
            if positions:
                mins = [min(p[0][i] for p in positions) for i in range(3)]
                maxs = [max(p[1][i] for p in positions) for i in range(3)]
                return [(mins[i] + maxs[i]) / 2.0 for i in range(3)]
    translation = node.get("translation")
    if translation and len(translation) >= 3:
        return [float(translation[0]), float(translation[1]), float(translation[2])]
    return None


def _apply_light(gltf: dict, node: dict, color: list[float], intensity: float, flash: dict | None) -> bool:
    node_ext = node.setdefault("extensions", {})
    if "ASOBO_macro_light" in node_ext:
        return False  # already injected (idempotent)
    light_ext = {"color": color, "intensity": intensity}
    if flash:
        light_ext.update(flash)
    node_ext["ASOBO_macro_light"] = light_ext
    used = gltf.setdefault("extensionsUsed", [])
    if "ASOBO_macro_light" not in used:
        used.append("ASOBO_macro_light")
    return True


def _node_is_amber(name: str, amber_nodes: tuple[str, ...]) -> bool:
    """Match ``FIXTURE_N`` on LOD0 and ``FIXTURE_N_LOD1`` on the LOD1 export.

    The Blender scripts name LOD1 nodes with a ``_LOD1`` suffix (verified in
    the exports), so a prefix match on the fixture stem covers both.
    """
    for stem in amber_nodes:
        if name == stem or name.startswith(stem + "_"):
            return True
    return False


def _inject_file(path: Path, amber_nodes: tuple[str, ...], red_nodes: tuple[str, ...]) -> dict[str, int]:
    try:
        gltf = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"error": f"{path.name}: {exc}"}
    nodes = gltf.get("nodes", [])
    amber_done = red_done = 0
    for node in nodes:
        name = str(node.get("name") or "")
        if _node_is_amber(name, amber_nodes):
            position = _node_light_position(gltf, node)
            if position is not None:
                node["translation"] = position  # keep light anchor explicit
                if _apply_light(gltf, node, AMBER, INTENSITY_AMBER,
                                {"day_night_cycle": True}):
                    amber_done += 1
        elif any(name == stem or name.startswith(stem + "_") for stem in red_nodes):
            position = _node_light_position(gltf, node)
            if position is not None:
                node["translation"] = position
                if _apply_light(gltf, node, RED, INTENSITY_RED,
                                {"flash_frequency": 1.0, "flash_duration": 0.5, "day_night_cycle": True}):
                    red_done += 1
    if amber_done or red_done:
        path.write_text(json.dumps(gltf, indent=2), encoding="utf-8")
    return {"file": str(path), "amber": amber_done, "red": red_done}


def _collect_targets() -> list[tuple[Path, tuple[str, ...], tuple[str, ...]]]:
    """LOD0 + ``_LOD1`` glTF files so distant LODs keep their lights."""
    targets: list[tuple[Path, tuple[str, ...], tuple[str, ...]]] = []
    x_dir = PACKAGE / "Model" / "X_LIGHTED_TRAILER"
    for name in ("X_LIGHTED_TRAILER.gltf", "X_LIGHTED_TRAILER_LOD1.gltf"):
        gltf = x_dir / name
        if gltf.is_file():
            targets.append((gltf, tuple(f"FIXTURE_{i}" for i in range(48)), ("CENTER_BEACON",)))
    for variant in ("ORANGE", "WHITE"):
        b_dir = PACKAGE / "Model" / f"BARRICADE_T3_{variant}"
        for name in (f"BARRICADE_T3_{variant}.gltf", f"BARRICADE_T3_{variant}_LOD1.gltf"):
            gltf = b_dir / name
            if gltf.is_file():
                targets.append((gltf, (), ("BEACON",)))
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", default=None, help="Explicit gltf path (repeatable)")
    args = parser.parse_args()

    targets: list[tuple[Path, tuple[str, ...], tuple[str, ...]]] = []
    if args.model:
        for raw in args.model:
            path = Path(raw)
            if not path.is_file():
                print(f"SKIP missing model: {path}")
                continue
            targets.append((path, tuple(f"FIXTURE_{i}" for i in range(48)), ("CENTER_BEACON",)))
    else:
        targets = _collect_targets()

    if not targets:
        print("No closure-marker glTFs found under the package.")
        return 1

    total_amber = total_red = 0
    for path, amber, red in targets:
        result = _inject_file(path, amber, red)
        if "error" in result:
            print(f"ERROR {result['error']}")
            continue
        print(f"OK   {result['file']}  amber={result['amber']} red={result['red']}")
        total_amber += result["amber"]
        total_red += result["red"]
    print(f"SUMMARY amber lights injected: {total_amber}, red beacons: {total_red}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
