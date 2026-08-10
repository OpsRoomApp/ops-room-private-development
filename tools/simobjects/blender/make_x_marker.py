"""Build the OPS ROOM vinyl closure "X" mats and export glTF.

Real-world dimensions (ICAO/FAA):
  Runway mat : 60 ft x 10 ft per leg (~18.3 m x 3.0 m), stark white,
               high-roughness matte vinyl (windscreen fabric look).
  Taxiway mat: 30 ft x 4 ft per leg (~9.1 m x 1.2 m), aviation safety
               yellow with black painted trim along the leg edges.

A completely flat mat is raised ~0.005 m above ground so it never z-fights
with the runway/taxiway surface texture. Each leg is crossed at 90 degrees.

Run headless:
    blender --background --python make_x_marker.py -- --variant runway --output C:/path/to/Model/X_MARKER_RUNWAY
    blender --background --python make_x_marker.py -- --variant taxiway --output C:/path/to/Model/X_MARKER_TAXIWAY
Variant defaults to ``runway``. Exports <OUT>/X_MARKER_<VARIANT>.gltf (+ .bin).
"""

import argparse
import sys

import bpy


def _mat(name: str, color: tuple, roughness: float = 0.9) -> object:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*color, 1.0)
        bsdf.inputs["Roughness"].default_value = roughness
    return mat


def _mat_leg(name: str, size: tuple, location: tuple, mat: object) -> None:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = size
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    obj.data.materials.append(mat)


def build_x(variant: str) -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    if variant == "taxiway":
        length, width = 9.1, 1.2
        top_color = (0.92, 0.66, 0.0)      # aviation safety yellow
        trim_color = (0.02, 0.02, 0.02)    # black contrast trim
        with_trim = True
    else:
        length, width = 18.3, 3.0
        top_color = (0.97, 0.97, 0.97)     # stark white
        trim_color = (0.02, 0.02, 0.02)
        with_trim = False

    thickness = 0.02
    raised = 0.005  # z-fighting guard above the surface

    top = _mat("X_TOP", top_color, roughness=0.92)

    z = raised + thickness
    if with_trim:
        # Black trim layer slightly larger than the yellow mat, peeking out
        # along the long edges (heavy-duty contrast border). One trim box per
        # leg, sitting directly beneath the yellow mat.
        trim = _mat("X_TRIM", trim_color, roughness=0.85)
        _mat_leg("X_TRIM_A", (length + 0.2, width + 0.12, thickness), (0.0, 0.0, raised), trim)
        _mat_leg("X_TRIM_B", (width + 0.12, length + 0.2, thickness), (0.0, 0.0, raised), trim)

    _mat_leg("X_LEG_A", (length, width, thickness), (0.0, 0.0, z), top)
    _mat_leg("X_LEG_B", (width, length, thickness), (0.0, 0.0, z), top)


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
    path = output_dir.rstrip("/\\") + f"/X_MARKER_{variant.upper()}.gltf"
    bpy.ops.export_scene.gltf(
        filepath=path,
        export_format="GLTF_SEPARATE",
        use_selection=False,
    )
    print(f"[OK] exported X_MARKER_{variant.upper()}.gltf to {output_dir}")
    _msfs_native(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", default="runway", choices=("runway", "taxiway"), help="X mat variant")
    parser.add_argument("--output", default="", help="Output directory for the glTF export")
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    args, _ = parser.parse_known_args(argv)
    output_dir = args.output or f"C:/closure-markers/Model/X_MARKER_{args.variant.upper()}"
    build_x(args.variant)
    export(args.variant, output_dir)
    print("[NEXT] copy the package/closure-markers folder into the MSFS Community folder.")


if __name__ == "__main__":
    main()
