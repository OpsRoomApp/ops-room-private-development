"""Modular Type III airport barricade - MSFS 2024 scenery/SimObject asset.

A SINGLE barrier, same family as BARRIER_LOW_ORANGE (no folding leg, no
flag cluster): one continuous mesh body. Round 5: the pennant cone, flag
panel and both support poles are GONE - the rail carries only a small
beacon light. Bolt/rivet ring heads around the mounting holes and a subtle
top-edge highlight strip are the only detailing; the beacon stays a
separate object so it can flash/animate independently.

Geometry (all real-world meters; origin at bottom-center of the rail, so the
delivered file sits flush on MSFS pavement):

  Base rail (lies flat on the ground, length along X):
    - 1.80 m long x 0.10 m deep x 0.20 m tall, corner bevel ~1 cm.
    - Interlock notch at each end: 8 cm wide x 5 cm deep cut, boolean-
      differenced from a block (spans the full depth).
    - Mounting hole: 2 cm diameter through-hole (axis along depth), centred
      vertically, 15 cm in from each end - boolean-differenced.
    - Bolt/rivet ring heads (washer-style tori, so the pin hole stays open)
      around each hole on both faces.
    - Top-edge highlight: a thin lighter cap along the top face between the
      notches so the top edge catches light.
    - Diagonal reflective stripes across the FULL front face: tileable
      45-degree repeating stripe image (pre-rendered PNG, simple equal-width
      rectangular bands alternating orange/white) sampled over front-face
      UVs (6 tiles along the length) - a real exported texture, not an
      unevaluatable node tree.
  Beacon (centred on the top face): clean 6 cm cylinder base + 5 cm dome
  lens - separate object (parented to the body) so it can flash. Round 9:
  the flash is engine-side - the package's model.xml <EmissiveFactor>
  behavior (RPN code, evaluated every frame) multiplies the lens STATIC
  emissive (80 = the flash peak) by a 0/1 siren double-flash pulse, so the
  dome is genuinely dark between pulses.

End state: exactly 2 mesh objects - BARRICADE_BODY (rail + rings +
highlight + notches + holes + stripes) and BEACON (parented to the body).
Prints vertex/face counts, runs a 2-object + geometry QA, renders a 3/4-angle
PNG next to the .blend.

Run headless:
    blender --background --python make_type3_barricade.py -- --variant orange --output C:/path/Model/BARRICADE_T3_ORANGE
    blender --background --python make_type3_barricade.py -- --variant white  --output C:/path/Model/BARRICADE_T3_WHITE
"""

import argparse
import math
import os
import struct
import sys
import zlib

import bpy
import bmesh
from mathutils import Matrix, Vector


# ── Spec constants (meters) ────────────────────────────────────────────────
RAIL_LENGTH = 1.8       # rail 1 long axis (X)
RAIL_DEPTH = 0.10       # rail 1 thickness (Y)
RAIL_HEIGHT = 0.20      # rail 1 height (Z)
BEVEL_W = 0.010         # corner bevel radius ~1 cm
NOTCH_W = 0.08          # interlock notch width along X (8 cm)
NOTCH_D = 0.05          # interlock notch depth down from the top (5 cm)
HOLE_R = 0.01           # mounting through-hole radius (2 cm diameter)
HOLE_INSET = 0.15       # hole centre 15 cm in from each end
TOP_HIGHLIGHT_H = 0.006  # top-edge highlight cap thickness (minor detailing)
BOLT_RING_MAJOR = 0.013  # bolt/rivet ring centreline radius (annulus)
BOLT_RING_MINOR = 0.0035 # bolt ring tube radius
BEACON_X = 0.0          # beacon centred on the rail top face
BEACON_BASE_R = 0.03    # beacon base radius (6 cm diameter)
BEACON_BASE_H = 0.04    # beacon base height
BEACON_DOME_R = 0.035   # beacon dome radius (cap slightly wider than the base)

#: Global model scale (v0.25.66: user requested the Type III barricade at
#: 2x the previous size). Applied to every mesh object's vertices right
#: before the LOD split/export, so geometry, the beacon and the light
#: positions all scale together. The spec constants above stay unscaled
#: because the QA checks validate against them.
MODEL_SCALE = 2.0

# Seamless 45-degree stripe phase. The phase is q = (x + z) mod PERIOD with
# PERIOD = tile width, so the pattern repeats EXACTLY at every tile seam
# (one full cycle per tile along X: 0.30 mod 0.30 = 0) and the 6-tile repeat
# across the 1.8 m rail is continuous. The old phase (x+z)/sqrt(2) with a
# 0.30 period jumped by ~0.21 at each seam - the bands visibly broke every
# 30 cm and looked weird.
STRIPE_PERIOD = 0.30    # phase period in (x+z) units = tile width (seamless)
STRIPE_FRAC = 0.5       # equal-width bands: each ~10.6 cm perpendicular,
                        # ~15 cm of horizontal run at 45 deg
STRIPE_TILE_U = 0.30    # tile world width (m) - one stripe cycle
STRIPE_TILE_V = 0.20    # tile world height (m) - the rail's full height
STRIPE_TILES = 6        # tile repeats along the rail length


def _write_png(path: str, w: int, h: int, rgb_rows: list) -> None:
    """Minimal stdlib PNG writer (RGB, 8-bit, non-interlaced)."""
    def chunk(typ: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + typ + data
        return c + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + row for row in rgb_rows)   # filter 0 per scanline
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
        fh.write(chunk(b"IHDR", ihdr))
        fh.write(chunk(b"IDAT", zlib.compress(raw, 9)))
        fh.write(chunk(b"IEND", b""))


def _make_stripe_tile(path: str, color_a: tuple, color_b: tuple,
                      size: int = 256, period: float = STRIPE_PERIOD,
                      stripe_frac: float = STRIPE_FRAC) -> None:
    """Generate the tileable full-face stripe image (stdlib only, so the
    glTF exporter ships a real texture instead of an unevaluatable node
    tree). Simple EQUAL-WIDTH rectangular 45-degree bands alternating
    colour_a / colour_b - the classic barricade stripe, not a soft blend.

    Phase q = (x + z) with period = tile width: the pattern repeats exactly
    at every tile seam (one full cycle per tile along X), so the 6-tile
    repeat across the rail is continuous. The old (x+z)/sqrt(2) phase with
    a 0.30 period jumped by ~0.21 at each 0.30 m seam, breaking the bands -
    the stripes rendered discontinuous and "weird".

    2x2 supersampling smooths the diagonal band edges (a hard per-pixel
    threshold would stair-step visibly at this resolution).
    """
    ca = tuple(int(round(c * 255)) for c in color_a)
    cb = tuple(int(round(c * 255)) for c in color_b)
    band = period * stripe_frac
    ss = 2  # supersamples per axis (2x2 per pixel)
    rows = []
    for j in range(size):
        row = bytearray()
        for i in range(size):
            r_acc = g_acc = b_acc = 0
            for sj in range(ss):
                for si in range(ss):
                    x = (i + (si + 0.5) / ss) / size * STRIPE_TILE_U
                    # Row j=0 is the PNG TOP but UV v=0 is the image BOTTOM,
                    # so map the tile's z axis inverted to keep the phase
                    # orientation matching the face UVs (v = z / RAIL_HEIGHT).
                    z = (size - j - (sj + 0.5) / ss) / size * STRIPE_TILE_V
                    q = (x + z) % period
                    ch = cb if q < band else ca
                    r_acc += ch[0]
                    g_acc += ch[1]
                    b_acc += ch[2]
            n = ss * ss
            row += bytes((r_acc // n, g_acc // n, b_acc // n))
        rows.append(bytes(row))
    _write_png(path, size, size, rows)
    print(f"[TEXTURE] wrote {path} ({size}x{size}, seamless {STRIPE_TILES}-tile repeat)")


def _scale_scene(scale: float = MODEL_SCALE) -> None:
    """Scale every mesh object's vertices in place.

    All objects have their transforms applied by the generators, so object
    space == world space and ``mesh.transform(Matrix.Scale)`` is equivalent
    to a world-space scale. Runs AFTER the QA checks (which validate against
    the unscaled spec constants) and BEFORE the LOD split/export.
    """
    if scale == 1.0:
        return
    bpy.context.view_layer.update()
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        obj.data.transform(Matrix.Scale(scale, 4))
        obj.data.update()
    print(f"[SCALE] applied {scale}x to all mesh objects")


def _clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def _cube(name: str, size: tuple, location: tuple, rotation: tuple = (0.0, 0.0, 0.0)) -> object:
    """Solid box. Cube primitive has extent 1.0, so full-size scale == size."""
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = size
    obj.rotation_euler = rotation
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return obj


def _cylinder(name: str, radius: float, depth: float, location: tuple, axis: str = "Z") -> object:
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth, location=location)
    obj = bpy.context.active_object
    obj.name = name
    if axis == "X":
        obj.rotation_euler = (0.0, 1.5708, 0.0)
    elif axis == "Y":
        obj.rotation_euler = (1.5708, 0.0, 0.0)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return obj


def _hemisphere(name: str, radius: float, location: tuple) -> object:
    """True dome (upper half of a UV sphere) - reads as a rounded lens cap."""
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=location, segments=24, ring_count=10)
    obj = bpy.context.active_object
    obj.name = name
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(obj.data)
    kill = [v for v in bm.verts if v.co.z < 0.0]
    bmesh.ops.delete(bm, geom=kill, context="VERTS")
    bmesh.update_edit_mesh(obj.data)
    bpy.ops.object.mode_set(mode="OBJECT")
    return obj


def _torus(name: str, major_radius: float, minor_radius: float, location: tuple) -> object:
    """Torus whose hole axis runs along Y (washer/ring shape facing the rail
    side). Default torus axis is Z; rotate 90 deg about X to make it a ring
    facing the front/back face."""
    # Low-segment torus: these are 2.6 cm rivets, not large detail - 24x6
    # reads round at any realistic viewing distance and keeps the asset light.
    bpy.ops.mesh.primitive_torus_add(major_radius=major_radius, minor_radius=minor_radius,
                                     major_segments=24, minor_segments=6,
                                     location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.rotation_euler = (1.5708, 0.0, 0.0)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return obj


def _material(name: str, color: tuple, roughness: float = 0.5, metallic: float = 0.0,
              emissive: float = 0.0, emissive_color: tuple = None, noise: bool = False,
              reflective: bool = False) -> object:
    """Plain Principled material; optional noise bump, emission, Fresnel gloss."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    out = nt.nodes.get("Material Output")
    bsdf = nt.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic

    if noise:
        n = nt.nodes.new("ShaderNodeTexNoise")
        n.inputs["Scale"].default_value = 60.0
        n.inputs["Detail"].default_value = 2.0
        n2 = nt.nodes.new("ShaderNodeBump")
        n2.inputs["Strength"].default_value = 0.05
        nt.links.new(n.outputs["Fac"], n2.inputs["Height"])
        nt.links.new(n2.outputs["Normal"], bsdf.inputs["Normal"])

    if emissive > 0.0:
        bsdf.inputs["Emission Color"].default_value = (*(emissive_color or color), 1.0)
        bsdf.inputs["Emission Strength"].default_value = emissive

    if reflective:
        # Retroreflective sheeting: glossy layer mixed via Layer Weight (Fresnel).
        gloss = nt.nodes.new("ShaderNodeBsdfGlossy")
        gloss.inputs["Color"].default_value = (*color, 1.0)
        gloss.inputs["Roughness"].default_value = 0.08
        lw = nt.nodes.new("ShaderNodeLayerWeight")
        lw.inputs["Blend"].default_value = 0.6
        mix = nt.nodes.new("ShaderNodeMixShader")
        nt.links.new(lw.outputs["Fresnel"], mix.inputs["Fac"])
        nt.links.new(bsdf.outputs["BSDF"], mix.inputs[1])
        nt.links.new(gloss.outputs["BSDF"], mix.inputs[2])
        nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return mat


def _stripe_material(name: str, image_path: str, color_a: tuple) -> object:
    """Full-face diagonal reflective stripe as an EXPORTABLE texture.

    The stripe pattern is pre-rendered into a tileable PNG (see
    ``_make_stripe_tile``) and driven by an ImageTexture over the front-face
    UVs (6 tiles along the rail length, 1 tile tall) - this is what the glTF
    exporter can actually ship, unlike a math/coordinate node tree which it
    cannot evaluate and would export as a flat default color. A Layer Weight
    Fresnel mix over a low-roughness Glossy adds the retroreflective sheeting
    response (preview-only; glTF exports the base color texture).
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    out = nt.nodes.get("Material Output")
    bsdf = nt.nodes.get("Principled BSDF")
    bsdf.inputs["Roughness"].default_value = 0.5

    img = bpy.data.images.load(image_path)
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.extension = "REPEAT"
    uv = nt.nodes.new("ShaderNodeTexCoord")
    nt.links.new(uv.outputs["UV"], tex.inputs["Vector"])
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])

    gloss = nt.nodes.new("ShaderNodeBsdfGlossy")
    gloss.inputs["Color"].default_value = (*color_a, 1.0)
    gloss.inputs["Roughness"].default_value = 0.1
    lw = nt.nodes.new("ShaderNodeLayerWeight")
    lw.inputs["Blend"].default_value = 0.55
    mix2 = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(lw.outputs["Fresnel"], mix2.inputs["Fac"])
    nt.links.new(bsdf.outputs["BSDF"], mix2.inputs[1])
    nt.links.new(gloss.outputs["BSDF"], mix2.inputs[2])
    nt.links.new(mix2.outputs["Shader"], out.inputs["Surface"])
    return mat


def _apply(obj: object, mat: object) -> None:
    obj.data.materials.append(mat)


def _add_beacon_light() -> None:
    """Round 11/12: embed one MSFS2024 street light at the BEACON.

    Round 12 (user feedback): the Round-11 advanced light sat at the CENTRE
    of the base+dome BEACON mesh (inside the beacon, and the 25000 cd read
    as too bright / embedded in the barricade), and the advancedLight type
    cannot flash. Now: streetLight type (the GSX/airport-lights mechanism -
    exports flash_frequency/duration/phase), source moved UP to the top of
    the dome (matching the beacon model). v0.25.73: intensity cut to 250 cd
    and the flash slowed to 0.5 Hz (2 s cycle) - the user's "blinding /
    reduced frequency" feedback.

    Called AFTER _scale_scene (so the position is the scaled one) and
    BEFORE the LOD split / export, so both LOD files carry the light (the
    SDK requires lights present on all LODs or they pop on the switch)."""
    beacon = bpy.data.objects.get("BEACON")
    if beacon is None:
        raise SystemExit("LIGHT CHECK FAIL: BEACON object missing before light embed")
    mins, maxs = _mesh_bounds(beacon)
    # The visible lamp is the dome - put the light source at the TOP of the
    # dome (mins/maxs midpoint of the whole base+dome mesh sits inside the
    # beacon, which reads as "embedded").
    pos = (round((mins.x + maxs.x) / 2.0, 3),
           round((mins.y + maxs.y) / 2.0, 3),
           round(maxs.z - 0.005, 3))
    light_data = bpy.data.lights.new(name="LIGHT_BEACON", type="POINT")
    light_data.msfs_light_type = "streetLight"
    p = light_data.msfs_light_properties
    p.msfs_light_color = (1.0, 0.08, 0.04)
    # v0.25.73 (user: "the beacon is blinding / someone will go blind from
    # 5 miles"): the red beacon was 12000 cd at 2 Hz (a strobe) - dropped to
    # 250 cd at 0.5 Hz (30/min, a classic 2 s beacon flash) with a 0.5 s
    # lit pulse. Dim enough to look at, slow enough to read as a beacon.
    p.msfs_light_intensity = 250.0
    p.msfs_light_cone_angle = 360.0          # omnidirectional (a beacon)
    p.msfs_light_flash_frequency = 30.0      # 0.5 Hz (2 s beacon flash)
    p.msfs_light_flash_duration = 0.5
    p.msfs_light_flash_phase = 0.0
    # Round 12b: the addon defaults random_phase=True (sim randomizes each
    # light's flash phase); lock it off so the beacon flashes deterministically.
    p.msfs_light_random_phase = False
    p.msfs_light_flare_enabled = True        # corona that reads at distance
    # Round 13 (user: "the lights are off in the day - they should be on
    # irrespective of time"): same fix as the X - the addon's export() only
    # writes ``daytime_intensity`` when ``day_night_cycle == False``, and
    # Blender 5.2's PropertyGroup.get() returns None for properties we never
    # touched, so the key was dropped and the sim defaulted the daytime
    # intensity to 0 (off in the day). Set both explicitly: always-on, with
    # a strong day value (night stays 250 cd - the approved balance).
    p.msfs_light_day_night_cycle = False
    p.msfs_light_daytime_intensity = 10000.0
    light = bpy.data.objects.new("LIGHT_BEACON", light_data)
    light.location = pos
    bpy.context.collection.objects.link(light)
    print(f"[LIGHT] embedded T3 beacon street light (flashing, {p.msfs_light_intensity} cd at {p.msfs_light_flash_frequency}/min) at {pos}")


def _bevel(obj: object, segments: int = 3, width: float = BEVEL_W) -> None:
    mod = obj.modifiers.new(name=f"BEVEL_{obj.name}", type="BEVEL")
    mod.width = width
    mod.segments = segments
    mod.limit_method = "ANGLE"
    mod.angle_limit = math.radians(35)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=mod.name)


def _boolean(target: object, cutter: object, operation: str = "DIFFERENCE") -> None:
    """Apply a boolean to target and remove the cutter object (its geometry
    is absorbed or subtracted either way)."""
    bpy.context.view_layer.objects.active = target
    target.select_set(True)
    bpy.ops.object.modifier_add(type="BOOLEAN")
    mod = target.modifiers[-1]
    mod.operation = operation
    mod.object = cutter
    mod.solver = "EXACT"
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(cutter, do_unlink=True)


def _assign_rail_materials(obj: object, mat_stripe: object, mat_body: object) -> None:
    """Front face (local +Y normal) gets the stripe shader, everything else
    the plain dominant body material."""
    obj.data.materials.append(mat_stripe)   # slot 0
    obj.data.materials.append(mat_body)     # slot 1
    for poly in obj.data.polygons:
        poly.material_index = 0 if poly.normal.y > 0.5 else 1


def _set_side_uvs(obj: object) -> None:
    """Re-derive stripe UVs for BOTH long faces from world coordinates.

    Round-4 regression: Blender's boolean/join bookkeeping remapped the rail's
    BACK (-Y) face onto the stripe material slot with garbage UVs, so the
    straight-on render (camera on the -Y side) showed a flat solid colour and
    the stripes looked "gone". This helper runs AFTER the join and sets every
    |normal.y| > 0.5 face to 6 tile repeats along X (back face UVs mirrored
    so the 45-deg diagonal reads the same from either side), independent of
    whatever the booleans did to the loop indices."""
    mesh = obj.data
    if not mesh.uv_layers:
        mesh.uv_layers.new(name="UVMap")
    uv_layer = mesh.uv_layers["UVMap"].data
    # Map from the RAIL constants, not mesh bounds: the joined body also
    # carries the top highlight strip, so bounds-derived V could be off.
    # Rail is centred at x=0, z=0..RAIL_HEIGHT.
    for poly in mesh.polygons:
        if abs(poly.normal.y) <= 0.5:
            continue
        # z-range guard: only faces within the rail's own height get stripe
        # UVs - anything above (highlight strip caps, bevel spills) keeps its
        # own material, never sampling out-of-range wrapped UVs.
        if any(mesh.vertices[mesh.loops[li].vertex_index].co.z > RAIL_HEIGHT + 0.001
               for li in range(poly.loop_start, poly.loop_start + poly.loop_total)):
            continue
        mirror = poly.normal.y < 0.0
        for li in range(poly.loop_start, poly.loop_start + poly.loop_total):
            v = mesh.vertices[mesh.loops[li].vertex_index].co
            u = (v.x + RAIL_LENGTH / 2) / RAIL_LENGTH * STRIPE_TILES
            if mirror:
                u = STRIPE_TILES - u
            vv = v.z / RAIL_HEIGHT
            uv_layer[li].uv = (u, vv)


def _set_front_uvs(obj: object) -> None:
    """Tile the stripe image across the full front face: 6 tile repeats along
    the length (STRIPE_TILES), 1 tile over the height. Front-face loop UVs are
    set explicitly so the exported glTF samples the stripe texture exactly
    like the preview (survives the boolean cuts - the front face keeps its
    loops; cut walls are not front-facing and keep the body material)."""
    mesh = obj.data
    if not mesh.uv_layers:
        mesh.uv_layers.new(name="UVMap")
    uv_layer = mesh.uv_layers["UVMap"].data
    minx = min(v.co.x for v in mesh.vertices)
    maxx = max(v.co.x for v in mesh.vertices)
    minz = min(v.co.z for v in mesh.vertices)
    maxz = max(v.co.z for v in mesh.vertices)
    for poly in mesh.polygons:
        if poly.normal.y <= 0.5:
            continue
        for li in range(poly.loop_start, poly.loop_start + poly.loop_total):
            v = mesh.vertices[mesh.loops[li].vertex_index].co
            u = (v.x - minx) / (maxx - minx) * STRIPE_TILES
            vv = (v.z - minz) / (maxz - minz)
            uv_layer[li].uv = (u, vv)


def _mesh_bounds(obj: object) -> tuple:
    mins = Vector((1e9, 1e9, 1e9))
    maxs = Vector((-1e9, -1e9, -1e9))
    for v in obj.data.vertices:
        wc = obj.matrix_world @ v.co
        for i in range(3):
            mins[i] = min(mins[i], wc[i])
            maxs[i] = max(maxs[i], wc[i])
    return mins, maxs


def _make_base_rail(name: str, materials: tuple) -> object:
    """Rail profile (single piece): beveled box + interlock notches +
    mounting holes, materials assigned by face normal. Returns the finished
    mesh."""
    mat_stripe, mat_body = materials
    rail = _cube(name, (RAIL_LENGTH, RAIL_DEPTH, RAIL_HEIGHT), (0.0, 0.0, RAIL_HEIGHT / 2))
    _bevel(rail, segments=3, width=BEVEL_W)
    _assign_rail_materials(rail, mat_stripe, mat_body)
    _set_front_uvs(rail)

    # Interlock notch at each end: 8 cm wide x 5 cm deep, full depth.
    for sign in (-1, 1):
        cx = sign * (RAIL_LENGTH / 2 - NOTCH_W / 2)
        cutter = _cube(f"NOTCH_{sign}",
                       (NOTCH_W, RAIL_DEPTH + 0.004, NOTCH_D),
                       (cx, 0.0, RAIL_HEIGHT - NOTCH_D / 2))
        _boolean(rail, cutter, "DIFFERENCE")

    # Mounting through-hole: 2 cm diameter, centred vertically, 15 cm in.
    for sign in (-1, 1):
        cx = sign * (RAIL_LENGTH / 2 - HOLE_INSET)
        cutter = _cylinder(f"HOLE_{sign}", HOLE_R, RAIL_DEPTH + 0.01,
                           (cx, 0.0, RAIL_HEIGHT / 2), axis="Y")
        _boolean(rail, cutter, "DIFFERENCE")

    # Post-boolean guard: boolean-generated cut walls (notch/hole interiors)
    # can inherit the stripe material slot with garbage UVs - force every
    # non-front-facing poly back onto the plain body material.
    for poly in rail.data.polygons:
        if poly.normal.y <= 0.5:
            poly.material_index = 1
    return rail


def build_barricade(variant: str) -> None:
    _clear_scene()

    orange = (0.851, 0.325, 0.118)   # international orange ~#D9531E
    white = (0.96, 0.96, 0.96)
    dominant = orange if variant == "orange" else white
    secondary = white if variant == "orange" else orange

    script_dir = os.path.dirname(os.path.abspath(__file__))
    tile_path = os.path.join(script_dir, f"barricade_stripes_{variant}.png")
    _make_stripe_tile(tile_path, dominant, secondary)
    mat_stripe = _stripe_material("Barrier_Reflective_Stripe", tile_path, dominant)
    mat_body = _material("Barrier_Body", dominant, roughness=0.5, noise=True)
    mat_hardware = _material("Hardware_Metal", (0.45, 0.46, 0.48), roughness=0.4, metallic=0.6)
    # Beacon material: red warning-light LENS. Round 9: static emission 80 is
    # the FLASH PEAK - the package's model.xml <EmissiveFactor> behavior
    # (siren double-flash RPN code) multiplies it by 0/1 every frame, so the
    # dome toggles full red <-> dark and is never "always lit". Clean
    # cylinder base + hemisphere dome, smooth-shaded so it reads as polished
    # glass.
    mat_beacon = _material("Beacon_Red_Lens", (1.0, 0.12, 0.06), roughness=0.15,
                           # v0.25.73: peak 80 -> 55 (less glare on the lens)
                           emissive=55.0, emissive_color=(1.0, 0.15, 0.08), reflective=True)

    # ── Base rail (single barrier, on the ground) ─────────────────────────
    rail1 = _make_base_rail("RAIL_1", (mat_stripe, mat_body))

    # ── Top-edge highlight strip (minor detailing): a thin lighter cap along
    # the top face BETWEEN the notches (the strip spans only the notch-free
    # middle region, so no boolean cut is needed). Slightly lighter than the
    # dominant colour + lower roughness so the top edge catches light.
    highlight_col = (0.93, 0.40, 0.17) if variant == "orange" else (0.995, 0.995, 0.995)
    mat_highlight = _material("Top_Highlight", highlight_col, roughness=0.35)
    strip_len = RAIL_LENGTH - 2 * NOTCH_W - 0.06   # stays clear of both notches
    strip = _cube("TOP_HIGHLIGHT", (strip_len, RAIL_DEPTH * 0.66, TOP_HIGHLIGHT_H),
                  (0.0, 0.0, RAIL_HEIGHT - TOP_HIGHLIGHT_H / 2))
    _apply(strip, mat_highlight)

    # ── Bolt/rivet ring heads at the mounting holes (minor detailing): a
    # washer-style torus around each hole on BOTH faces so the pin hole stays
    # open. Silver hardware metal.
    mat_bolt = _material("Bolt_Metal", (0.72, 0.73, 0.75), roughness=0.35, metallic=0.75)
    bolt_rings = []
    for sign in (-1, 1):
        cx = sign * (RAIL_LENGTH / 2 - HOLE_INSET)
        for side in (-1, 1):
            ring = _torus(f"BOLT_RING_{'P' if side > 0 else 'N'}{'L' if sign < 0 else 'R'}",
                          BOLT_RING_MAJOR, BOLT_RING_MINOR,
                          (cx, side * (RAIL_DEPTH / 2 + 0.001), RAIL_HEIGHT / 2))
            _apply(ring, mat_bolt)
            bolt_rings.append(ring)

    # ── Beacon (separate object, parented later): clean cylinder base +
    # hemisphere dome with smooth shading - the one piece that can flash.
    beacon_base = _cylinder("BEACON_BASE", BEACON_BASE_R, BEACON_BASE_H,
                            (BEACON_X, 0.0, RAIL_HEIGHT + BEACON_BASE_H / 2))
    _apply(beacon_base, mat_beacon)
    beacon_dome = _hemisphere("BEACON_DOME", BEACON_DOME_R,
                              (BEACON_X, 0.0, RAIL_HEIGHT + BEACON_BASE_H + 0.004))
    _apply(beacon_dome, mat_beacon)
    for _o in (beacon_base, beacon_dome):
        for _p in _o.data.polygons:
            _p.use_smooth = True
    bpy.ops.object.select_all(action="DESELECT")
    beacon_base.select_set(True)
    beacon_dome.select_set(True)
    bpy.context.view_layer.objects.active = beacon_base
    bpy.ops.object.join()
    beacon = bpy.context.active_object
    beacon.name = "BEACON"

    # ── Join rail 1 + highlight strip + bolt rings into ONE body ──────────
    bpy.ops.object.select_all(action="DESELECT")
    rail1.select_set(True)
    strip.select_set(True)
    for ring in bolt_rings:
        ring.select_set(True)
    bpy.context.view_layer.objects.active = rail1
    bpy.ops.object.join()
    body = bpy.context.active_object
    body.name = "BARRICADE_BODY"

    # Parent the beacon to the body (keep world transform) so it can flash
    # independently of the main mesh in-sim.
    bpy.context.view_layer.update()
    beacon.parent = body
    beacon.matrix_parent_inverse = body.matrix_world.inverted()
    _purge_none_slots(body)

    # Round-4 stripe fix: after the join/booleans, re-derive stripe UVs for
    # BOTH long faces (back mirrored) and force both onto the stripe material
    # slot - the back face otherwise samples garbage UVs and renders flat.
    # Same z-range guard as _set_side_uvs so nothing above the rail height
    # (highlight caps, bevel spills) gets stripe UVs.
    _set_side_uvs(body)
    for poly in body.data.polygons:
        if abs(poly.normal.y) <= 0.5:
            continue
        if any(body.data.vertices[body.data.loops[li].vertex_index].co.z > RAIL_HEIGHT + 0.001
               for li in range(poly.loop_start, poly.loop_start + poly.loop_total)):
            continue
        poly.material_index = 0
    print("[MAT] both long faces -> stripe texture (UVs from world coords, back mirrored)")

    bpy.context.view_layer.update()


def _purge_none_slots(obj: object) -> None:
    """Drop dead (None) material slots left by boolean/join bookkeeping and
    remap face indices so the exported mesh has no empty material entries."""
    mesh = obj.data
    old = list(mesh.materials)
    valid = [m for m in old if m is not None]
    if len(valid) == len(old):
        return
    remap = {old.index(m): i for i, m in enumerate(valid)}
    mesh.materials.clear()
    for m in valid:
        mesh.materials.append(m)
    for poly in mesh.polygons:
        poly.material_index = remap.get(poly.material_index, 0)
    print(f"[CLEAN] purged {len(old) - len(valid)} dead material slot(s) from {obj.name}")


def _ray_hit(obj: object, origin_world: tuple, direction_world: tuple) -> tuple:
    """(hit, hit_location_world) using object-space ray_cast (identity
    transform for the body, so world == local)."""
    hit, loc, _n, _i = obj.ray_cast(Vector(origin_world), Vector(direction_world))
    return hit, Vector(loc)


def _qa_objects() -> None:
    """Verify the end state: exactly 2 mesh objects (body + beacon), computed
    positions, open holes, notches, ground contact. Every check feeds the
    final verdict so 'ALL PASS' only prints when ALL of them pass."""
    results: list = []
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    names = sorted(o.name for o in meshes)
    expect = ["BARRICADE_BODY", "BEACON"]
    print(f"[QA] mesh objects: {names}")
    ok_objects = names == expect
    results.append(("object set == 2 expected", ok_objects))

    verts = sum(len(o.data.vertices) for o in meshes)
    faces = sum(len(o.data.polygons) for o in meshes)
    print(f"[QA] verts={verts} faces={faces}")

    by_name = {o.name: o for o in meshes}
    body = by_name.get("BARRICADE_BODY")
    if body:
        mins, maxs = _mesh_bounds(body)
        ground_ok = abs(mins.z) < 0.005
        # Round 5: no flag cluster - the body should end at the rail top
        # (rail height + the thin highlight cap).
        body_ok = maxs.z <= RAIL_HEIGHT + TOP_HIGHLIGHT_H + 0.01
        print(f"[QA] body bbox z: {mins.z:.3f}..{maxs.z:.3f} "
              f"(ground flush {'PASS' if ground_ok else 'FAIL'}, "
              f"no flag cluster (maxz {RAIL_HEIGHT + TOP_HIGHLIGHT_H + 0.01:.2f}) "
              f"{'PASS' if body_ok else 'FAIL'})")
        results += [("ground flush", ground_ok), ("no flag cluster", body_ok)]
        # Mounting hole open? Ray through the hole centre must NOT hit.
        for cx in (-(RAIL_LENGTH / 2 - HOLE_INSET), RAIL_LENGTH / 2 - HOLE_INSET):
            hit, _loc = _ray_hit(body, (cx, 0.0, RAIL_HEIGHT / 2), (0.0, 1.0, 0.0))
            print(f"[QA] mounting hole @x={cx:+.2f} open -> {'PASS' if not hit else 'FAIL'}")
            results.append((f"mounting hole @{cx:+.2f}", not hit))
        # Interlock notch cut? Ray down from the notch centre hits its floor.
        for cx in (-(RAIL_LENGTH / 2 - NOTCH_W / 2), RAIL_LENGTH / 2 - NOTCH_W / 2):
            hit, loc = _ray_hit(body, (cx, 0.0, RAIL_HEIGHT - NOTCH_D / 2), (0.0, 0.0, -1.0))
            floor_ok = hit and loc.z < RAIL_HEIGHT - NOTCH_D + 0.01
            print(f"[QA] notch @x={cx:+.2f} floor z={loc.z:.3f} "
                  f"(need < {RAIL_HEIGHT - NOTCH_D + 0.01:.2f}) -> {'PASS' if floor_ok else 'FAIL'}")
            results.append((f"notch @{cx:+.2f}", floor_ok))
        # Stripes must cover BOTH long faces with world-derived UVs (round-4
        # regression: the back face carried the stripe slot but garbage UVs,
        # which rendered as a flat solid colour).
        uv_layer = body.data.uv_layers["UVMap"].data if body.data.uv_layers else None
        face_stats = {}
        for poly in body.data.polygons:
            if abs(poly.normal.y) > 0.5:
                key = ("front" if poly.normal.y > 0.0 else "back", poly.material_index)
                face_stats[key] = face_stats.get(key, 0) + 1
        # Pre-triangulation the long faces are large bevel/boolean-split
        # polys (dozens, not hundreds), so a modest lower bound suffices.
        front_ok = face_stats.get(("front", 0), 0) > 25
        back_ok = face_stats.get(("back", 0), 0) > 25
        back_uv_ok = False
        if uv_layer is not None:
            for poly in body.data.polygons:
                if poly.normal.y < -0.5:
                    for li in range(poly.loop_start, poly.loop_start + poly.loop_total):
                        if uv_layer[li].uv[0] > 1.0:
                            back_uv_ok = True
                            break
                    if back_uv_ok:
                        break
        ok_stripes = front_ok and back_ok and back_uv_ok
        print(f"[QA] stripes front={front_ok} back={back_ok} back-UV>1={back_uv_ok} "
              f"-> {'PASS' if ok_stripes else 'FAIL'}")
        results.append(("stripes both faces", ok_stripes))

    beacon = by_name.get("BEACON")
    beacon_ok = bool(beacon and beacon.parent and beacon.parent.name == "BARRICADE_BODY")
    beacon_shape_ok = False
    if beacon:
        b_mins, b_maxs = _mesh_bounds(beacon)
        # Clean profile: a single base cylinder + dome should span from the
        # rail top (RAIL_HEIGHT) up past the dome apex (~+base_h+dome_r).
        beacon_shape_ok = (b_mins.z >= RAIL_HEIGHT - 0.01 and
                           b_maxs.z >= RAIL_HEIGHT + BEACON_BASE_H + BEACON_DOME_R * 0.8)
        print(f"[QA] beacon bbox z: {b_mins.z:.3f}..{b_maxs.z:.3f} "
              f"(sits on rail top + dome above -> {'PASS' if beacon_shape_ok else 'FAIL'})")
    print(f"[QA] beacon parent -> {'PASS' if beacon_ok else 'FAIL'}")
    results.append(("beacon parent", beacon_ok))
    results.append(("beacon shape", beacon_shape_ok))

    failed = [name for name, ok in results if not ok]
    print(f"[QA] end-state -> {'ALL PASS' if not failed else 'FAIL: ' + ', '.join(failed)}")


def _scene_bounds() -> tuple:
    mins = Vector((1e9, 1e9, 1e9))
    maxs = Vector((-1e9, -1e9, -1e9))
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or obj.name.endswith("_LOD1"):
            continue
        for v in obj.data.vertices:
            wc = obj.matrix_world @ v.co
            for i in range(3):
                mins[i] = min(mins[i], wc[i])
                maxs[i] = max(maxs[i], wc[i])
    center = (mins + maxs) / 2.0
    radius = max((maxs - mins).length / 2.0, 1.0)
    return center, radius


def _fit_front_camera(cam: object, center: Vector, radius: float) -> None:
    """Distance the front camera by the object's own width so the face fills
    the frame. After the flag cluster was removed the scene is a low flat
    rail, and the old radius>=1.0 clamp parked the camera 2 m out (tiny dot,
    stripes unreadable). Fit the widest of X/Z extents to ~85% of the frame
    using the VERTICAL FOV (angle_y) - square render + sensor_fit AUTO means
    the horizontal angle is the wrong measure."""
    cam.data.lens = 35.0
    mins = Vector((1e9, 1e9, 1e9))
    maxs = Vector((-1e9, -1e9, -1e9))
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or obj.name.endswith("_LOD1"):
            continue
        for v in obj.data.vertices:
            wc = obj.matrix_world @ v.co
            for i in range(3):
                mins[i] = min(mins[i], wc[i])
                maxs[i] = max(maxs[i], wc[i])
    fit = max(maxs.x - mins.x, maxs.z - mins.z)
    half = math.tan(cam.data.angle_y / 2.0)
    dist = fit / (2.0 * half * 0.85)
    cam.location = center + Vector((0.0, -dist, 0.0))


def _render_preview(prefix: str, output_dir: str, preview_out: str) -> str:
    """3/4-angle EEVEE render of the LOD0 geometry -> PNG next to the .blend
    (and a copy in preview_out when given)."""
    scene = bpy.context.scene
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
        try:
            scene.render.engine = engine
            break
        except Exception:
            continue
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 1280
    scene.render.image_settings.file_format = "PNG"

    center, radius = _scene_bounds()
    target = bpy.data.objects.new("CAM_TARGET", None)
    bpy.context.collection.objects.link(target)
    target.location = center

    bpy.ops.object.camera_add(location=center + Vector((radius * 1.55, -radius * 1.35, radius * 1.15)))
    cam = bpy.context.active_object
    track = cam.constraints.new(type="TRACK_TO")
    track.target = target
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"
    scene.camera = cam

    for light_name, loc, energy in (("SUN_KEY", (1.6, -1.4, 1.1), 5.0), ("SUN_FILL", (-1.3, 1.2, 0.8), 1.6)):
        bpy.ops.object.light_add(type="SUN", location=center + Vector(loc) * radius)
        light = bpy.context.active_object
        light.name = light_name
        light.data.energy = energy
        ltrack = light.constraints.new(type="TRACK_TO")
        ltrack.target = target
        ltrack.track_axis = "TRACK_NEGATIVE_Z"

    world = bpy.data.worlds.new("PreviewWorld")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs[0].default_value = (0.14, 0.15, 0.17, 1.0)
        bg.inputs[1].default_value = 1.0

    png_path = os.path.join(output_dir, f"{prefix}_preview.png")
    scene.render.filepath = png_path
    bpy.ops.render.render(write_still=True)
    print(f"[RENDER] {png_path}")
    if preview_out:
        import shutil
        os.makedirs(preview_out, exist_ok=True)
        shutil.copyfile(png_path, os.path.join(preview_out, f"{prefix}.png"))
        print(f"[RENDER] copied preview to {preview_out}/{prefix}.png")
    return png_path


def _render_front(prefix: str, output_dir: str, preview_out: str) -> str:
    """Straight-on +Y view (camera on the -Y side looking at the front face).
    For the barricade this is the definitive check that the full-face diagonal
    stripes actually read; for the vertical X it is the approach view."""
    scene = bpy.context.scene
    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
        try:
            scene.render.engine = engine
            break
        except Exception:
            continue
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 1280
    scene.render.image_settings.file_format = "PNG"

    center, radius = _scene_bounds()

    # No TRACK_TO constraint here: for a face-on view the camera looks
    # straight along +Y, and the constraint is degenerate/unapplied in
    # --background (evaluated matrix stayed identity -> camera pointed at the
    # ground and the render came back empty). Set the orientation explicitly:
    # rotate 90 deg about X maps camera -Z (view) onto world +Y, camera +Y
    # (up) onto world +Z.
    bpy.ops.object.camera_add(location=center + Vector((0.0, -radius * 2.0, 0.0)))
    cam = bpy.context.active_object
    cam.rotation_euler = (1.5708, 0.0, 0.0)
    scene.camera = cam
    _fit_front_camera(cam, center, radius)

    png_path = os.path.join(output_dir, f"{prefix}_front.png")
    scene.render.filepath = png_path
    bpy.ops.render.render(write_still=True)
    print(f"[RENDER] {png_path}")
    if preview_out:
        import shutil
        os.makedirs(preview_out, exist_ok=True)
        shutil.copyfile(png_path, os.path.join(preview_out, f"{prefix}_FRONT.png"))
        print(f"[RENDER] copied front view to {preview_out}/{prefix}_FRONT.png")
    return png_path


def add_light_behavior_check() -> None:
    """Round 9: the beacon flash is delivered by the package's model.xml
    <EmissiveFactor> behavior, not by keyframe or fx animation.

    Round 8 proved both older mechanisms render FROZEN on static SimObjects
    in MSFS 2024: legacy .fx emitters ignore Rate/Particle Lifetime/Emitter
    Delay (steady + fx culling at ~50-60 ft), and ASOBO_property_animation
    material keyframes are not played (the user saw the round-8 beacon frozen
    at its frame-0 red - steady, no flash). The engine DOES evaluate
    ModelBehaviors <EmissiveFactor> code every frame on SimObjects (the SDK's
    Windsock sample ships <Behaviors> on a non-aircraft SimObject; Asobo's
    own blink template uses this exact mechanism).

    The builder writes a behavior component for the BEACON node whose RPN
    code multiplies this material's STATIC emissive (exported here at the
    flash peak, 80) by a 0/1 siren double-flash pulse (two 0.12 s pulses per
    1.5 s cycle) - dark between pulses because the code returns 0.

    Pre-export sanity check: the lens material must carry the MSFS emissive
    attributes (set by _apply_msfs_materials) or the behavior multiplies
    into a black material.
    """
    mat = bpy.data.materials.get("Beacon_Red_Lens")
    if mat is None or not hasattr(mat, "msfs_emissive_factor"):
        raise SystemExit("LIGHT CHECK FAIL: Beacon_Red_Lens missing/not MSFS material")
    print("[LIGHT] T3: beacon lens material ready for model.xml <EmissiveFactor> "
          "behavior (static emissive 80 = flash peak)")


def _make_lods() -> tuple:
    """Split into LOD0 (full) and LOD1 (~40% decimated) collections."""
    lod0 = bpy.data.collections.new("LOD0")
    lod1 = bpy.data.collections.new("LOD1")
    bpy.context.scene.collection.children.link(lod0)
    bpy.context.scene.collection.children.link(lod1)
    for obj in list(bpy.context.scene.objects):
        if obj.type != "MESH":
            continue
        for col in list(obj.users_collection):
            col.objects.unlink(obj)
        lod0.objects.link(obj)
        copy = obj.copy()
        copy.data = obj.data.copy()
        copy.name = obj.name + "_LOD1"
        # v0.25.66: un-parent the LOD1 copies. The BEACON is parented to the
        # body in LOD0; when the LOD1 pass unlinks the non-_LOD1 objects, the
        # parented BEACON_LOD1 was skipped by the exporter and the distant
        # LOD1 lost the beacon mesh + its EmMesh light entirely. Flattening
        # the copies keeps them in the export as their own roots.
        copy.parent = None
        copy.matrix_parent_inverse = Matrix.Identity(4)
        mod = copy.modifiers.new(name="DECIMATE", type="DECIMATE")
        mod.ratio = 0.4
        lod1.objects.link(copy)
        bpy.context.view_layer.objects.active = copy
        bpy.ops.object.modifier_apply(modifier=mod.name)
    return lod0, lod1


def _msfs_native(path: str) -> None:
    """Convert a plain Khronos glTF export to MSFS-native (ASOBO extensions).

    The stock exporter output silently fails to render in-sim; the package
    builder (tools/simobjects/package/build_package.py) also runs this, so a
    Blender re-export is native at the source too.
    """
    pkg = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "package")
    if pkg not in sys.path:
        sys.path.insert(0, pkg)
    try:
        from msfs_native import convert_file  # type: ignore

        convert_file(path)
        print(f"[OK] msfs-native: {os.path.basename(path)}")
    except Exception as exc:  # never block the export
        print(f"[WARN] msfs-native conversion skipped: {exc}")


def _export_lod(path: str, lod0: object, lod1: object, want_lod1: bool) -> None:
    """Export only the wanted LOD set (unlink the other from the scene)."""
    removed = []
    for obj in list(bpy.context.scene.objects):
        if obj.type != "MESH":
            continue
        if obj.name.endswith("_LOD1") == want_lod1:
            continue
        for col in list(obj.users_collection):
            col.objects.unlink(obj)
        removed.append(obj)
    try:
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLTF_SEPARATE", use_selection=False)
    finally:
        for obj in removed:
            (lod1 if obj.name.endswith("_LOD1") else lod0).objects.link(obj)
    _msfs_native(path)


def _assert_texture_in_gltf(path: str, variant: str) -> None:
    """Guard against regressing to an unevaluatable node tree: the exported
    glTF must reference the baked stripe texture by name. The msfs_native
    conversion rewrites the PNG reference to a .dds, so accept either."""
    with open(path, "r", encoding="utf-8") as fh:
        txt = fh.read()
    ok = f"barricade_stripes_{variant}.png" in txt or f"barricade_stripes_{variant}.dds" in txt
    print(f"[CHECK] texture in {os.path.basename(path)} -> {'PASS' if ok else 'FAIL'}")


def _triangulate() -> None:
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.quads_convert_to_tris(quad_method="BEAUTY", ngon_method="BEAUTY")
        bpy.ops.object.mode_set(mode="OBJECT")


def _stats() -> None:
    """Final triangulated counts: LOD0 (the delivered file) separately from
    the total including LOD1 copies, so the printed number matches the mesh
    actually exported."""
    lod0 = [o for o in bpy.context.scene.objects if o.type == "MESH" and not o.name.endswith("_LOD1")]
    all_m = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    v0 = sum(len(o.data.vertices) for o in lod0)
    f0 = sum(len(o.data.polygons) for o in lod0)
    va = sum(len(o.data.vertices) for o in all_m)
    fa = sum(len(o.data.polygons) for o in all_m)
    print(f"[STATS] LOD0 verts={v0} faces={f0} | total (with LOD1) verts={va} faces={fa}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", default="orange", choices=("orange", "white"))
    parser.add_argument("--output", default="")
    parser.add_argument("--preview-out", default="", help="Optional dir to copy the preview PNG into")
    parser.add_argument("--no-render", action="store_true", help="Skip the preview render")
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    args, _ = parser.parse_known_args(argv)

    output_dir = args.output or f"C:/closure-markers/Model/BARRICADE_T3_{args.variant.upper()}"
    os.makedirs(output_dir, exist_ok=True)

    build_barricade(args.variant)
    _qa_objects()
    # v0.25.66: user requested the Type III barricade at 2x size.
    _scale_scene(MODEL_SCALE)
    _triangulate()
    lod0, lod1 = _make_lods()
    _stats()

    blend_path = os.path.join(output_dir, f"BARRICADE_T3_{args.variant.upper()}.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print(f"[BLEND] {blend_path}")

    png_path = ""
    if not args.no_render:
        for obj in bpy.context.scene.objects:
            if obj.name.endswith("_LOD1"):
                obj.hide_set(True)
        png_path = _render_preview(f"BARRICADE_T3_{args.variant.upper()}", output_dir, args.preview_out)
        # Straight-on front view: proves the full-face diagonal stripes read
        # clearly (they are easy to miss in the 3/4 view).
        _render_front(f"BARRICADE_T3_{args.variant.upper()}", output_dir, args.preview_out)

    print("[NOTE] standalone export does NOT embed the Round-11 MSFS beacon "
          "light - run export_msfs_official.py barricade-<variant> so the "
          "ASOBO advanced light is written into the glTF")
    _export_lod(os.path.join(output_dir, f"BARRICADE_T3_{args.variant.upper()}.gltf"), lod0, lod1, want_lod1=False)
    print(f"[OK] exported BARRICADE_T3_{args.variant.upper()}.gltf (LOD0 only)")
    _export_lod(os.path.join(output_dir, f"BARRICADE_T3_{args.variant.upper()}_LOD1.gltf"), lod0, lod1, want_lod1=True)
    print(f"[OK] exported BARRICADE_T3_{args.variant.upper()}_LOD1.gltf")
    _assert_texture_in_gltf(os.path.join(output_dir, f"BARRICADE_T3_{args.variant.upper()}.gltf"), args.variant)
    _assert_texture_in_gltf(os.path.join(output_dir, f"BARRICADE_T3_{args.variant.upper()}_LOD1.gltf"), args.variant)

    # Guaranteed hard exit: EEVEE/GL leftovers can keep --background Blender
    # alive after the script finishes. os._exit skips all cleanup by design.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
