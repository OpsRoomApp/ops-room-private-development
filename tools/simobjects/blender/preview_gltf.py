"""Render a headless preview image of a glTF model (for quick visual check).

Usage (headless):
    blender --background --python preview_gltf.py -- --input path/to/Model.gltf --output path/to/preview.png

Renders the imported model on a simple camera rig with studio lighting using
the EEVEE engine, falling back to Workbench if EEVEE is unavailable.
"""

import argparse
import math
import sys

import bpy
from mathutils import Vector


def _clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def _import_gltf(path: str) -> None:
    bpy.ops.import_scene.gltf(filepath=path)


def _scene_bounds() -> tuple[Vector, Vector, float]:
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        return Vector((0.0, 0.0, 0.0)), Vector((1.0, 1.0, 1.0)), 1.0
    min_c = Vector((1e12, 1e12, 1e12))
    max_c = Vector((-1e12, -1e12, -1e12))
    for obj in meshes:
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            min_c = Vector(map(min, min_c, world))
            max_c = Vector(map(max, max_c, world))
    center = (min_c + max_c) / 2.0
    size = (max_c - min_c).length
    return center, max_c - min_c, max(size, 0.001)


def _aim_camera(center: Vector, distance: float) -> None:
    cam_data = bpy.data.cameras.new("PreviewCamera")
    cam = bpy.data.objects.new("PreviewCamera", cam_data)
    bpy.context.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    location = center + Vector((distance * 0.55, -distance * 1.05, distance * 0.75))
    cam.location = location
    direction = center - location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _add_lights() -> None:
    bpy.ops.object.select_all(action="DESELECT")
    sun_data = bpy.data.lights.new("PreviewSun", type="SUN")
    sun = bpy.data.objects.new("PreviewSun", sun_data)
    sun_data.energy = 3.0
    sun.rotation_euler = (math.radians(45), 0.0, math.radians(-35))
    bpy.context.collection.objects.link(sun)
    area_data = bpy.data.lights.new("PreviewFill", type="AREA")
    area = bpy.data.objects.new("PreviewFill", area_data)
    area_data.energy = 80.0
    area_data.size = 4.0
    area.location = (0.0, -6.0, 4.0)
    bpy.context.collection.objects.link(area)


def _render(output: str) -> None:
    scene = bpy.context.scene
    scene.render.resolution_x = 1024
    scene.render.resolution_y = 1024
    scene.render.image_settings.file_format = "PNG"
    engine = None
    for candidate in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"):
        try:
            scene.render.engine = candidate
            engine = candidate
            break
        except Exception:
            continue
    print(f"[OK] rendering with engine {engine} -> {output}")
    scene.render.filepath = output
    bpy.ops.render.render(write_still=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="glTF file to preview")
    parser.add_argument("--output", required=True, help="PNG output path")
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    args, _ = parser.parse_known_args(argv)
    _clear_scene()
    _import_gltf(args.input)
    center, _extents, size = _scene_bounds()
    _aim_camera(center, size * 2.4)
    _add_lights()
    _render(args.output)
    print(f"[OK] preview written to {args.output}")


if __name__ == "__main__":
    main()
