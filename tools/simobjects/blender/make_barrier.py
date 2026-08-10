"""Build the OPS ROOM low-profile interlocking barrier (FAA AC 150/5370-2G).

A heavy-duty, water-filled plastic barrier built as a single manifold mesh
using primitive manipulation and boolean subtractions.

Dimensions (bounding box): Length 2.44 m (96"), Width 0.25 m (10"),
Height 0.25 m (10"). The barrier's length runs along the Y axis; the mesh
origin is the exact bottom-center (0,0,0) so it sits flush on MSFS pavement.

Geometry:
  - Main body cube scaled to global dimensions.
  - Male interlock: cylinder (r=0.06 m) protruding 0.1 m from the +Y end
    (long axis along Y, vertical when deployed on its side).
  - Female interlock: identical cylinder subtracted (Boolean Difference)
    from the -Y end to hollow a matching socket.
  - Forklift lift slots: two tine cubes (L 0.4 x W 0.2 x H 0.1 m) punched
    through the bottom width, symmetric 0.8 m from centre along the length.
  - Water fill cap: flat cylinder (r=0.05 m, h=0.02 m) on top centre.
  - Hazard-light screw mounts: recessed cylinder holes (r=0.02 m, depth
    0.03 m) in both upper shoulders.

Materials (MSFS Standard): matte safety orange #FF5500 (variant A) or stark
matte safety white #FFFFFF (variant B); roughness 0.65 for UV-stabilised HDPE.

Run headless:
    blender --background --python make_barrier.py -- --variant orange --output C:/path/to/Model/BARRIER_LOW_ORANGE
    blender --background --python make_barrier.py -- --variant white  --output C:/path/to/Model/BARRIER_LOW_WHITE
"""

import argparse
import sys

import bpy


def _cube(name: str, size: tuple, location: tuple) -> object:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = size
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return obj


def _cylinder(name: str, radius: float, depth: float, location: tuple, axis: str = "Z") -> object:
    """Cylinder; axis along 'X', 'Y' or 'Z' (cylinder primitive is Z-aligned)."""
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth, location=location)
    obj = bpy.context.active_object
    obj.name = name
    if axis == "X":
        obj.rotation_euler = (0.0, 1.5708, 0.0)
    elif axis == "Y":
        obj.rotation_euler = (1.5708, 0.0, 0.0)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return obj


def _material(name: str, color: tuple, roughness: float = 0.65,
              emissive: float = 0.0, emissive_color: tuple = None) -> object:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*color, 1.0)
        bsdf.inputs["Roughness"].default_value = roughness
        if emissive > 0.0:
            bsdf.inputs["Emission Color"].default_value = (*(emissive_color or color), 1.0)
            bsdf.inputs["Emission Strength"].default_value = emissive
    return mat


def _hemisphere(name: str, radius: float, location: tuple) -> object:
    """Upper-half dome - the rounded beacon lens."""
    import bmesh

    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=location, segments=20, ring_count=10)
    obj = bpy.context.active_object
    obj.name = name
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(obj.data)
    kill = [v for v in bm.verts if v.co.z < 0.0]
    bmesh.ops.delete(bm, geom=kill, context="VERTS")
    bmesh.update_edit_mesh(obj.data)
    bpy.ops.object.mode_set(mode="OBJECT")
    for poly in obj.data.polygons:
        poly.use_smooth = True
    return obj


def _boolean_cut(target: object, cutter: object) -> None:
    """Subtract cutter from target using a Boolean modifier, then apply it."""
    bpy.context.view_layer.objects.active = target
    target.select_set(True)
    bpy.ops.object.modifier_add(type="BOOLEAN")
    mod = target.modifiers[-1]
    mod.operation = "DIFFERENCE"
    mod.object = cutter
    mod.solver = "EXACT"
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(cutter, do_unlink=True)


def _apply_material(obj: object, mat: object) -> None:
    obj.data.materials.append(mat)


def build_barrier(variant: str) -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    color = (1.0, 0.333, 0.0) if variant == "orange" else (1.0, 1.0, 1.0)
    body_mat = _material(f"BARRIER_{variant.upper()}", color, roughness=0.65)
    cap_mat = _material("CAP_DARK", (0.25, 0.25, 0.25), roughness=0.5)

    length, width, height = 2.44, 0.25, 0.25

    # ── Main body (length along Y), bottom flush at z=0 ─────────────────────
    body = _cube("BARRIER_BODY", (width, length, height), (0.0, 0.0, height / 2))
    _apply_material(body, body_mat)

    # ── Male interlock: cylinder protruding 0.1 m from the +Y end ───────────
    male = _cylinder("MALE_TAB", 0.06, 0.1, (0.0, length / 2 + 0.05, height / 2), axis="Y")
    _apply_material(male, body_mat)

    # ── Female interlock: identical cylinder subtracted from the -Y end ─────
    female_cutter = _cylinder("FEMALE_CUTTER", 0.06, 0.12, (0.0, -length / 2 - 0.06, height / 2), axis="Y")
    _boolean_cut(body, female_cutter)

    # ── Forklift lift slots: two tines punched through the bottom width ─────
    for side in (-0.8, 0.8):
        tine = _cube(f"TINE_{side}", (0.4, 0.2, 0.1), (0.0, side, 0.05))
        _boolean_cut(body, tine)

    # ── Water fill cap on top centre ────────────────────────────────────────
    cap = _cylinder("FILL_CAP", 0.05, 0.02, (0.0, 0.0, height + 0.01))
    _apply_material(cap, cap_mat)

    # ── Small dim red warning beacon on top centre (FAA: barricades carry a
    #    small red obstruction light so the closure reads at night). Sits
    #    beside the fill cap, ~4 cm tall: a short cylinder base + rounded
    #    dome. MSFS 2024 reads the emissive multiplier as candela/m^2 -
    #    80 cd is a small, dim warning lamp (not a strobe), per user request.
    beacon_mat = _material("BEACON_RED_DIM", (0.6, 0.04, 0.03), roughness=0.2,
                           emissive=80.0, emissive_color=(1.0, 0.06, 0.04))
    beacon_base = _cylinder("BEACON_BASE", 0.018, 0.02, (0.0, 0.0, height + 0.03))
    _apply_material(beacon_base, beacon_mat)
    beacon_dome = _hemisphere("BEACON_DOME", 0.022, (0.0, 0.0, height + 0.042))
    _apply_material(beacon_dome, beacon_mat)

    # ── Hazard-light screw mounts: recessed holes in both upper shoulders ───
    for side in (-1, 1):
        mount_cutter = _cylinder(f"MOUNT_CUTTER_{side}", 0.02, 0.03, (side * 0.1, 0.0, height - 0.015))
        _boolean_cut(body, mount_cutter)


def _msfs_native(path: str) -> None:
    """Convert a plain Khronos glTF export to MSFS-native (ASOBO extensions).

    The stock exporter output silently fails to render in-sim; the package
    builder (tools/simobjects/package/build_package.py) also runs this, so a
    Blender re-export is native at the source too.
    """
    import os
    import sys as _sys

    pkg = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "package")
    if pkg not in _sys.path:
        _sys.path.insert(0, pkg)
    try:
        from msfs_native import convert_file  # type: ignore

        convert_file(path)
        print(f"[OK] msfs-native: {os.path.basename(path)}")
    except Exception as exc:  # never block the export
        print(f"[WARN] msfs-native conversion skipped: {exc}")


def export(variant: str, output_dir: str) -> None:
    path = output_dir.rstrip("/\\") + f"/BARRIER_LOW_{variant.upper()}.gltf"
    bpy.ops.export_scene.gltf(
        filepath=path,
        export_format="GLTF_SEPARATE",
        use_selection=False,
    )
    print(f"[OK] exported BARRIER_LOW_{variant.upper()}.gltf to {output_dir}")
    _msfs_native(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", default="orange", choices=("orange", "white"), help="Barrier color variant")
    parser.add_argument("--output", default="", help="Output directory for the glTF export")
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    args, _ = parser.parse_known_args(argv)
    output_dir = args.output or f"C:/closure-markers/Model/BARRIER_LOW_{args.variant.upper()}"
    build_barrier(args.variant)
    export(args.variant, output_dir)
    print("[NEXT] copy the package/closure-markers folder into the MSFS Community folder.")


if __name__ == "__main__":
    main()
