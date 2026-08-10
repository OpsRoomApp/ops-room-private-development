"""OPS ROOM -- official MSFS 2024 glTF export driver (Blender 4.2 LTS).

Rebuilds the closure-marker models through the SDK's own exporter instead of
the hand-rolled ``msfs_native`` repack.  Pipeline:

    Blender 4.2 LTS --background --addons io_scene_gltf2_msfs_2024 \\
        --python tools/simobjects/blender/export_msfs_official.py -- <model> <outdir>

The addon's hooks are activated exactly the way ``multi_export.py`` does it:

    from io_scene_gltf2_msfs_2024.io.exp.gltf_hooks import Export
    Export.msfs_export_settings = <MSFS2024_MultiExporterSettings preset>
    bpy.ops.export_scene.gltf( ... 4.2 kwarg set ... )

Models (must match a generator module under this folder):

    barrier-orange   -> make_barrier.build_barrier('orange')
    barrier-white    -> make_barrier.build_barrier('white')
    x-runway         -> make_x_marker.build_x('runway')
    x-taxiway        -> make_x_marker.build_x('taxiway')
    barricade-orange -> make_type3_barricade.build_barricade('orange')
    barricade-white  -> make_type3_barricade.build_barricade('white')
    x-lighted        -> make_lighted_x_trailer (full build + LODs)

Output: ``<outdir>/<MODEL>.gltf`` (+ .bin) with ASOBO_asset_normal extension
metadata and DirectX normals, ready for fspackagetool.
"""

from __future__ import annotations

import argparse
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# --------------------------------------------------------------------------
# Official MSFS export (mirrors io/exp/multi_export.py::_export_blender_4_2)
# --------------------------------------------------------------------------

def _new_settings_preset(context: bpy.types.Context):
    """Create + activate an MSFS settings preset with the extension on.

    Round 9: no material/object animations are exported any more - the
    flashing/chasing lights are delivered by the package's model.xml
    <EmissiveFactor> behaviors (RPN code evaluated every frame by the sim),
    not by ASOBO_property_animation keyframes (which round 8 proved render
    frozen on static SimObjects). The MSFS material hooks read the PRESET's
    own export_animations flag (gltf_hooks.gather_material_hook reads
    msfs_export_settings.export_animations), so keep it OFF.
    """
    presets = context.scene.msfs_multi_exporter_settings_presets
    preset = presets.add()
    preset.name = "ORS_OFFICIAL"
    preset.enable_msfs_extension = True
    preset.export_animations = False
    preset.export_animation_mode = "NLA_TRACKS"
    context.scene.msfs_multi_exporter_settings_presets_enum = preset.name
    return preset


def export_msfs(file_path: str, context: bpy.types.Context) -> None:
    """Export the current scene through the official MSFS 2024 path."""
    from io_scene_gltf2_msfs_2024.io.exp.gltf_hooks import Export  # noqa: PLC0415

    settings = _new_settings_preset(context)
    # The hooks class reads this class attribute (exactly like multi_export).
    Export.msfs_export_settings = settings
    bpy.ops.export_scene.gltf(
        filepath=file_path,
        check_existing=True,
        export_format="GLTF_SEPARATE",
        export_copyright="OPS ROOM",
        export_image_format="AUTO",
        export_jpeg_quality=75,
        export_texture_dir="",
        export_keep_originals=True,
        export_texcoords=True,
        export_normals=True,
        export_draco_mesh_compression_enable=False,
        export_tangents=True,
        export_materials="EXPORT",
        export_original_specular=False,
        export_attributes=False,
        use_mesh_edges=False,
        use_mesh_vertices=False,
        export_cameras=False,
        use_selection=False,
        use_visible=True,
        use_renderable=False,
        use_active_collection=False,
        use_active_scene=True,
        export_yup=True,
        export_apply=True,
        export_animations=True,
        export_frame_range=False,
        export_frame_step=1,
        export_force_sampling=False,
        export_animation_mode="NLA_TRACKS",
        export_def_bones=False,
        export_optimize_animation_size=False,
        export_optimize_animation_keep_anim_armature=False,
        export_optimize_animation_keep_anim_object=False,
        export_negative_frame="SLIDE",
        export_anim_slide_to_zero=False,
        export_reset_pose_bones=False,
        export_bake_animation=False,
        export_anim_single_armature=False,
        export_current_frame=False,
        export_rest_position_armature=True,
        export_anim_scene_split_object=False,
        export_skins=False,
        export_all_influences=False,
        export_morph=False,
        export_morph_normal=False,
        export_morph_tangent=False,
        export_morph_animation=False,
        # Round 11: the MSFS2024 light extensions (ASOBO_advanced_light) are
        # gathered through the punctual-light path - the hook converts each
        # POINT light to the MSFS extension and strips KHR_lights_punctual.
        # Must be True or the embedded beacon/LED lights are never exported.
        export_lights=True,
        will_save_settings=False,
        export_extras=False,
        export_gn_mesh=False,
        export_gpu_instances=False,
        export_hierarchy_flatten_objs=False,
        export_hierarchy_full_collections=False,
        export_vertex_color="NONE",
        export_all_vertex_colors=False,
        export_active_vertex_color_when_no_material=False,
        export_image_add_webp=False,
        export_image_webp_fallback=False,
        export_unused_images=False,
        export_unused_textures=False,
        export_try_sparse_sk=False,
        export_try_omit_sparse_sk=False,
        export_armature_object_remove=False,
        export_influence_nb=4,
        export_import_convert_lighting_mode="SPEC",
        export_optimize_disable_viewport=False,
    )


# --------------------------------------------------------------------------
# Model builders
# --------------------------------------------------------------------------

def _triangulate_scene() -> None:
    """Triangulate every mesh so tangents compute (MSFS wants tris)."""
    bpy.context.view_layer.update()
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.quads_convert_to_tris(quad_method="BEAUTY", ngon_method="BEAUTY")
        bpy.ops.object.mode_set(mode="OBJECT")


def _apply_msfs_materials() -> None:
    """NO-OP in v0.25.66a (Round 12).

    This used to convert the generators' Principled materials into the MSFS
    standard node group (``mat.msfs_material_type = "msfs_standard"``) and
    re-apply the captured values onto the ``msfs_*`` attributes. Round 12
    found that on this machine the addon's ``gather_material_hook`` CRASHES
    for every material:

        Extension hook gather_material_hook fails on io_scene_gltf2_msfs_2024
        ERROR: 'InlineShaderNodes' object has no attribute 'get'

    (an addon/Blender version mismatch). When the hook crashes the exporter
    falls back to the plain Khronos path -- which reads the *Principled node
    tree*. The conversion had already replaced that tree with the MSFS group
    and reset the attributes, so the fallback found NO base color and the X
    frame exported colorless (the "frame colours/textures missing" report).
    Verified empirically: a plain Principled material exports its base color
    factor + texture + emissive exactly as the generators define them (the
    same path X_MARKER_RUNWAY / BARRIER_LOW use and render correctly in-sim).
    The MSFS2024 material hook is broken on this Blender build, so leave the
    materials untouched and let the Khronos fallback do the work.
    """
    return


def build_and_export(model: str, output_dir: str) -> None:
    import make_barrier  # noqa: PLC0415
    import make_type3_barricade  # noqa: PLC0415
    import make_x_marker  # noqa: PLC0415
    import make_lighted_x_trailer  # noqa: PLC0415

    os.makedirs(output_dir, exist_ok=True)
    name = model.replace("-", "_").upper()

    if model in ("barrier-orange", "barrier-white"):
        variant = model.split("-")[1]
        make_barrier.build_barrier(variant)
        _triangulate_scene()
        _apply_msfs_materials()
        export_msfs(os.path.join(output_dir, f"BARRIER_LOW_{variant.upper()}.gltf"), bpy.context)
        print(f"[OK] {model} -> BARRIER_LOW_{variant.upper()}.gltf")
        return

    if model in ("x-runway", "x-taxiway"):
        variant = model.split("-")[1]
        make_x_marker.build_x(variant)
        _triangulate_scene()
        _apply_msfs_materials()
        export_msfs(os.path.join(output_dir, f"X_MARKER_{variant.upper()}.gltf"), bpy.context)
        print(f"[OK] {model} -> X_MARKER_{variant.upper()}.gltf")
        return

    if model in ("barricade-orange", "barricade-white"):
        variant = model.split("-")[1]
        make_type3_barricade.build_barricade(variant)
        # v0.25.66: user requested 2x barricade size (same call main() makes).
        make_type3_barricade._scale_scene()
        make_type3_barricade._triangulate()
        # Round 11: embed an MSFS advanced beacon light in the model (must
        # run AFTER scaling so the position is the scaled one).
        make_type3_barricade._add_beacon_light()
        _apply_msfs_materials()
        # Round 9: the beacon flash is engine-side via model.xml
        # <EmissiveFactor> behavior (RPN, evaluated every frame); the static
        # emissive exported here is the flash peak. No keyframe/fx animation.
        make_type3_barricade.add_light_behavior_check()
        lod0, lod1 = make_type3_barricade._make_lods()
        # Export LOD0 and LOD1 exactly like the generator does (unlink the other).
        _export_lod_pair(
            output_dir,
            f"BARRICADE_T3_{variant.upper()}",
            lod0,
            lod1,
        )
        print(f"[OK] {model} -> BARRICADE_T3_{variant.upper()}.gltf + _LOD1")
        return

    if model == "x-lighted":
        make_lighted_x_trailer._clear_scene()
        positions = make_lighted_x_trailer._compute_fixture_positions()
        make_lighted_x_trailer.build_marker(positions)
        # v0.25.66: user requested 1.5x X size (same call main() makes).
        make_lighted_x_trailer._scale_scene()
        make_lighted_x_trailer._triangulate()
        # Round 11: embed 45 MSFS advanced lights (amber LEDs + red beacon)
        # in the model (must run AFTER scaling so the positions are scaled).
        make_lighted_x_trailer._add_advanced_lights()
        _apply_msfs_materials()
        # Round 9: the X chase + siren are engine-side via model.xml
        # <EmissiveFactor> behaviors (RPN, evaluated every frame); the static
        # emissive exported here is the flash peak. No keyframe/fx animation.
        make_lighted_x_trailer.add_light_behaviors()
        lod0, lod1 = make_lighted_x_trailer._make_lods()
        _export_lod_pair(
            output_dir,
            "X_LIGHTED_TRAILER",
            lod0,
            lod1,
        )
        print("[OK] x-lighted -> X_LIGHTED_TRAILER.gltf + _LOD1")
        return

    raise SystemExit(f"Unknown model: {model}")


def _export_lod_pair(output_dir: str, name: str, lod0, lod1) -> None:
    """Export LOD0 (full) then LOD1 (decimated), each as its own glTF.

    IMPORTANT: the LOD0 file must contain ONLY the full (non-_LOD1) objects
    and the LOD1 file ONLY the decimated _LOD1 copies. An earlier version
    had the unlink test inverted - it unlinked the FULL objects first, so
    both output files contained only the decimated meshes (LOD00 geometry
    was missing and EmMesh node names came out as LENS_*_LOD1).
    """
    # LOD0: keep full objects, unlink the decimated copies.
    removed = []
    for obj in list(bpy.context.scene.objects):
        if obj.type != "MESH":
            continue
        if obj.name.endswith("_LOD1"):
            for col in list(obj.users_collection):
                col.objects.unlink(obj)
            removed.append(obj)
    try:
        export_msfs(os.path.join(output_dir, f"{name}.gltf"), bpy.context)
    finally:
        for obj in removed:
            lod1.objects.link(obj)

    # LOD1: keep only the decimated copies, exported under their BASE node
    # names. Round 7 fix: the copies are named X_LOD1, BEACON_LOD1, etc., but
    # the lightdef EmMesh keys (BEACON, LENS_0, CENTER_BEACON, ...) must
    # resolve in EVERY LOD - the SDK requires the emissive part to exist in
    # all LODs under the same name, otherwise the light + billboard sprite
    # silently detaches once the sim switches to LOD1 at distance. The Asobo
    # exporter names nodes after the Blender objects, so we temporarily strip
    # the _LOD1 suffix (parking the base objects under *_ORSHOLD to avoid
    # Blender's automatic .001 renames), export, then restore everything.
    removed2 = []
    copies = []          # [(copy_obj, base_name)] by reference
    for obj in list(bpy.context.scene.objects):
        if obj.type != "MESH":
            continue
        if obj.name.endswith("_LOD1"):
            copies.append((obj, obj.name[:-5]))
        else:
            for col in list(obj.users_collection):
                col.objects.unlink(obj)
            removed2.append(obj)
    parked = []
    for _copy, base_name in copies:
        base_obj = bpy.data.objects.get(base_name)
        if base_obj is not None:
            base_obj.name = base_name + "_ORSHOLD"
            parked.append(base_obj)
    try:
        for copy_obj, base_name in copies:
            copy_obj.name = base_name
        export_msfs(os.path.join(output_dir, f"{name}_LOD1.gltf"), bpy.context)
    finally:
        for copy_obj, base_name in copies:
            copy_obj.name = base_name + "_LOD1"
        for base_obj in parked:
            base_obj.name = base_obj.name[:-8]  # strip "_ORSHOLD"
        for obj in removed2:
            lod0.objects.link(obj)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model", help="barrier-orange|barrier-white|x-runway|x-taxiway|barricade-orange|barricade-white|x-lighted")
    parser.add_argument("output", help="Output directory for the glTF files")
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    args, _ = parser.parse_known_args(argv)

    bpy.ops.preferences.addon_enable(module="io_scene_gltf2_msfs_2024")
    build_and_export(args.model, args.output)

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
