"""Lighted \"X\" runway-closure marker on a tripod ground stand - MSFS 2024.

Round 4 redesign: a VERTICAL X sign (like the marker you see face-on on
approach to a closed runway), not a horizontal windmill on a trailer. The
trailer (chassis/wheels/axle/tongue) is gone entirely; a simple tripod
ground stand holds the X up, with the X's lowest point ~1.2 m above ground.

Design (all real-world meters, origin at the ground stand's base):
  - The X lies in a single VERTICAL plane (the XZ plane, y = 0), facing the
    +Y approach side. Two tubular beams cross at 90 deg at a central hub
    bracket: arms go up-left / up-right / down-left / down-right at 45 deg.
    Arm length 2.75 m hub-to-tip (tip-to-tip ~3.9 m, matching a real
    L-893-style closure marker). The hub sits at z = 3.10 m, so the lowest
    arm tips are ~1.16 m above the ground.
  - Ground stand: a short mast (z 0..3.10) plus three splayed legs from a
    joint at z = 1.15 down to flat round feet (azimuths 90/210/330 deg), and
    a base plate under the mast. Galvanized grey so it reads clearly
    SECONDARY to the yellow X.
  - One continuous joined body: mast + legs + feet + base plate + hub
    bracket + all four arms (bpy.ops.object.join, transforms applied). The
    arms overlap through the hub so the junction is solid; the visible hub
    bracket covers the crossing - no gap, no clipping.
  - Light fixtures (dark socket + rounded emissive amber dome) are their own
    small objects, 11 per arm = 44 total, evenly spaced t = 0.20..1.00 along
    each arm, positions COMPUTED from each arm's start/end coordinates in
    code (not placed by hand) and written to fixtures.json for light.xml.
  - CENTER_BEACON: a dominant red warning light at the hub - the intersection
    of the X (z = HUB.z). Clean cylinder base + hemisphere dome, larger than
    the amber fixtures, kept as its own object so it can flash independently
    in-sim (real lighted-X markers carry a red obstruction beacon at the
    hub). Round 9: the flashing is engine-side, delivered by the package's
    model.xml <EmissiveFactor> behaviors - RPN code evaluated every frame by
    the sim multiplies each lens material's STATIC emissive by a 0/1 pulse
    (44-LED chase + siren double-flash; see build_official_pkg). The dome IS
    the light, so it renders at LOD distance with no fx culling.

Deliverable: exactly ONE mesh body (X_SIGN_BODY) + 44 FIXTURE_/LENS_ pairs
+ CENTER_BEACON. QA verifies fixture count, center beacon presence/height,
arm symmetry + 45-deg vertical plane, lowest-X height, ground contact, and
that NO orphan objects exist.

Run headless:
    blender --background --python make_lighted_x_trailer.py -- --output C:/path/Model/X_LIGHTED_TRAILER --fixtures-out fixtures.json
"""

import argparse
import json
import math
import os
import sys

import bpy
import bmesh
from mathutils import Matrix, Vector

# ── Spec constants (meters) ────────────────────────────────────────────────
ARM_LEN = 2.75           # hub-to-tip arm length
ARM_R = 0.035            # arm tube radius
HUB = Vector((0.0, 0.0, 3.10))   # hub centre (X centre at ~1.16 m off ground)
HUB_BRACKET = (0.5, 0.2, 0.5)    # visible hub bracket box (X x Y x Z)
MAST_R = 0.055           # mast tube radius
LEG_R = 0.03             # leg tube radius
LEG_JOINT_Z = 1.15       # legs join the mast at this height
FOOT_R = 0.09            # flat foot radius
FOOT_H = 0.03            # foot thickness
FEET_RADIUS = 0.75       # feet splay radius from the mast
FIXTURES_PER_ARM = 11
FIXTURE_T_START = 0.20   # first fixture this far (as arm fraction) from hub
FIXTURE_T_STEP = 0.08    # linear step so the last fixture lands on the tip
# Round 12: the lamp fixtures protrude OUT of the vertical X plane toward the
# approach side (+Y), mounted on the front face of the tube like real L-893
# marker lamps. Previously the fixture origin sat ON the arm centreline, so
# the base cylinder (r=0.022) and dome (r=0.026) were buried INSIDE the arm
# tube (r=0.035) - the lights looked embedded in the rods. Offset the whole
# fixture by the tube radius + the base radius so the lamp head sits proud of
# the tube surface (and the lightdefs / embedded lights, which track the
# LENS mesh bounds, follow automatically).
FIXTURE_PROTRUDE = ARM_R + 0.022 + 0.004   # tube radius + base radius + gap
# Round 12: flashing via the streetLight light type (GSX/airport-lights
# mechanism - the addon exports ASOBO_street_light flash_frequency/duration/
# phase; the advancedLight type has NO flash support). All 44 LEDs share one
# frequency; each LED's PHASE is staggered by k steps so the lit band travels
# the arms hub -> tip every cycle (a chase/wave, like runway-end light waves).
# v0.25.73 (user: "blinding / reduced frequency"): the old 120/min (2 Hz)
# read as a frantic strobe; slowed to 40/min (0.67 Hz, 1.5 s cycle) with a
# 0.2 s lit pulse and a wider phase step so the chase is a calm visible wave.
FLASH_FREQ = 40.0         # 1/min -> 0.67 Hz (1.5 s chase cycle)
FLASH_DURATION = 0.20     # seconds lit per cycle (visible pulse, not strobe)
FLASH_PHASE_STEP = 0.05   # seconds between adjacent LEDs on the same arm
# v0.25.73: red obstruction beacon slowed to a classic 2 s beacon flash
# (30/min = 0.5 Hz) with a 0.5 s lit pulse instead of the 2 Hz strobe.
BEACON_FREQ = 30.0
BEACON_DURATION = 0.5
# Round 13 (user: "the lights are off in the day"): the daytime intensity
# override written into ASOBO_street_light when day_night_cycle is off.
# `intensity` is the NIGHT value; `daytime_intensity` is the DAY value the
# sim uses while the sun is up (real L-893/L-864 style markers are easily
# visible in daylight, so the day value must be much higher than the night
# value - the addon's own default is 10000 cd). Per-light values are passed
# at the call site (see _add_advanced_lights).
# Center red obstruction beacon at the hub (the X intersection).
CENTER_BASE_R = 0.045    # beacon base radius (9 cm diameter - dominant vs
                         # the 2.6 cm amber fixture domes)
CENTER_BASE_H = 0.05     # beacon base height
CENTER_DOME_R = 0.05     # beacon dome radius (slightly wider than the base)

_C45 = math.sqrt(2.0) / 2.0
ARM_DIRS = [Vector((_C45, 0.0, _C45)), Vector((-_C45, 0.0, _C45)),
            Vector((_C45, 0.0, -_C45)), Vector((-_C45, 0.0, -_C45))]

#: Global model scale (v0.25.66: user requested the lighted X at 1.5x the
#: previous size). Applied to every mesh object's vertices right before the
#: LOD split/export; fixture LIGHT positions in fixtures.json are scaled by
#: the same factor so the systems.cfg lightdefs stay glued to the domes.
MODEL_SCALE = 1.5


def _scale_scene(scale: float = MODEL_SCALE) -> None:
    """Scale every mesh object's vertices AND origin in place.

    v0.25.66 bugfix: scaling only ``obj.data.transform()`` leaves the object
    ORIGIN untouched, and the LENS domes (built by ``_hemisphere``, which
    does NOT apply its transform) keep their unscaled origin while their
    geometry grows -- so the LEDs ended up at 1x positions on 1.5x arms, and
    the lightdefs (scaled from fixtures.json) floated off the domes. Scaling
    ``obj.location`` by the same factor moves the origin with the geometry
    (a no-op for objects whose transform is already baked to the origin).
    Runs AFTER the QA checks (which validate against the unscaled spec
    constants) and BEFORE the LOD split/export."""
    if scale == 1.0:
        return
    bpy.context.view_layer.update()
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        obj.data.transform(Matrix.Scale(scale, 4))
        obj.location = obj.location * scale
        obj.data.update()
    print(f"[SCALE] applied {scale}x to all mesh objects (geometry + origin)")


def _clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


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


def _tube_along(name: str, radius: float, length: float, center: tuple, dirn: Vector) -> object:
    """Cylinder whose axis is aligned to dirn (real cross-section tube)."""
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=length, location=center)
    obj = bpy.context.active_object
    obj.name = name
    q = Vector((0.0, 0.0, 1.0)).rotation_difference(dirn.normalized())
    obj.rotation_euler = q.to_euler()
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return obj


def _cube(name: str, size: tuple, location: tuple, rotation: tuple = (0.0, 0.0, 0.0)) -> object:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = size
    obj.rotation_euler = rotation
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return obj


def _hemisphere(name: str, radius: float, location: tuple) -> object:
    """True dome (upper half of a UV sphere) - the rounded emissive lens cap."""
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=location, segments=24, ring_count=12)
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


def _material(name: str, color: tuple, roughness: float, metallic: float = 0.0,
              emissive: float = 0.0, emissive_color: tuple = None) -> object:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*color, 1.0)
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Metallic"].default_value = metallic
        if emissive > 0.0:
            bsdf.inputs["Emission Color"].default_value = (*(emissive_color or color), 1.0)
            bsdf.inputs["Emission Strength"].default_value = emissive
    return mat


def _apply(obj: object, mat: object) -> None:
    obj.data.materials.append(mat)


def _create_msfs_light(name: str, position: tuple, color: tuple, intensity: float,
                       flash_freq: float = 0.0, flash_duration: float = 0.0,
                       flash_phase: float = 0.0,
                       daytime_intensity: float | None = None) -> None:
    """Create an MSFS2024 streetLight (exports as a glTF
    ASOBO_street_light extension on its own node) at a world position.

    Round 12: switched from advancedLight to streetLight because the
    advancedLight extension does NOT support flashing - the streetLight
    type is the airport-light mechanism (GSX-style flashing ground-vehicle
    lights) and exports flash_frequency (1/min) / flash_duration (s) /
    flash_phase (s). A steady light is just flash_freq=0.

    The addon registers ``msfs_light_type`` / ``msfs_light_properties`` on
    bpy.types.Light, so this must run with the addon enabled
    (export_msfs_official enables it before building)."""
    light_data = bpy.data.lights.new(name=name, type="POINT")
    light_data.msfs_light_type = "streetLight"
    p = light_data.msfs_light_properties
    p.msfs_light_color = color
    p.msfs_light_intensity = intensity
    p.msfs_light_cone_angle = 360.0          # omnidirectional (a beacon)
    p.msfs_light_flash_frequency = flash_freq
    p.msfs_light_flash_duration = flash_duration
    p.msfs_light_flash_phase = flash_phase
    # Round 12b: the addon defaults random_phase=True, which makes the sim
    # randomize every light's flash phase and destroys the deterministic
    # LED chase stagger (verified exported as "random_phase": true). Lock it
    # off so the per-LED phases written above are honoured exactly.
    p.msfs_light_random_phase = False
    p.msfs_light_flare_enabled = True        # corona that reads at distance
    # Round 13 (user: "the lights are off in the day - they should be on
    # irrespective of time"): the addon's export() only writes
    # ``daytime_intensity`` when ``day_night_cycle == False``, and Blender
    # 5.2's PropertyGroup.get() returns None for properties we never touched
    # (so the export check failed and the key was dropped - the sim then
    # defaults the daytime intensity to 0 = lights off during the day).
    # Set BOTH explicitly: always-on day/night cycle OFF, and a daytime
    # intensity override that keeps the lamp lit (and visible) in daylight.
    # Default day value = 8x the night intensity (visible in the sun);
    # callers may pass a custom value (e.g. the red beacon).
    p.msfs_light_day_night_cycle = False
    p.msfs_light_daytime_intensity = daytime_intensity or (intensity * 8.0)
    light = bpy.data.objects.new(name, light_data)
    light.location = position
    bpy.context.collection.objects.link(light)


def _add_advanced_lights() -> None:
    """Round 11/12: embed MSFS2024 street lights in the model at every lens.

    The emissive domes are ~8 cm wide and go sub-pixel 15-18 m away - the
    hard cap on every previous round's draw distance. An embedded light
    renders as a true light source (corona/bloom + lens flare) whose
    intensity is in candela; the SDK's Lights page recommends this type
    "for use in SimObjects for things like beacon lights". One amber light
    per LENS dome + one red at the center beacon. Round 12: the lights are
    streetLight type with STAGGERED flash phases so the 44 LEDs chase
    hub->tip every cycle (a wave, like runway-end lights) and the red
    beacons flash at 2 Hz (GSX-style siren beacon). Called AFTER
    _scale_scene (positions must be the scaled ones) and BEFORE the LOD
    split / export, so both LOD files carry the lights (the SDK requires
    lights present on all LODs or they pop on the switch).
    """
    amber = (1.0, 0.55, 0.0)
    red = (1.0, 0.08, 0.04)
    total = FIXTURES_PER_ARM * len(ARM_DIRS)
    created = 0
    missing = []
    for i in range(total):
        lens = bpy.data.objects.get(f"LENS_{i}")
        if lens is None:
            missing.append(f"LENS_{i}")
            continue
        mins, maxs = _mesh_bounds(lens)
        # k = index along the arm (0 = nearest the hub, 10 = the tip): the
        # phase grows with k so the flash wave runs hub -> tip each cycle.
        k = i % FIXTURES_PER_ARM
        # v0.25.73 (user: "lights are blinding, someone will go blind from
        # 5 miles"): the amber LED street lights were 5000 cd - dropped to
        # 100 cd. v0.25.74 (user: "increase the brightness (little) and
        # draw distance of the lighted X"): 100 -> 200 cd - a visible lamp
        # with more range, still nowhere near the old blinding 5000 cd.
        # v0.25.75 (user: "increase the lighted X brightness more"):
        # 200 -> 600 cd (3x; ~1/8th of the old blinding 5000 cd).
        # v0.25.76 (user: "increase the draw distance"): 600 -> 1000 cd so
        # the street-light glow reads further; the fx sprites (Range 5000 m)
        # carry the far-field.
        # Round 13: daytime_intensity 12000 cd keeps the amber chase visible
        # in full daylight (night value stays 1000 cd - the approved balance).
        _create_msfs_light(f"LIGHT_LENS_{i:02d}", tuple((mins + maxs) / 2.0),
                           amber, 1000.0, FLASH_FREQ, FLASH_DURATION,
                           round(k * FLASH_PHASE_STEP, 3), 12000.0)
        created += 1
    if missing:
        raise SystemExit(f"LIGHT CHECK FAIL: {len(missing)} lens domes missing: {missing[:5]}")
    beacon = bpy.data.objects.get("CENTER_BEACON")
    if beacon is not None:
        mins, maxs = _mesh_bounds(beacon)
        # v0.25.73: red hub beacon was 25000 cd (blinding) - dropped to
        # 250 cd. v0.25.74 (user: "increase the brightness (little) and
        # draw distance of the lighted X"): 250 -> 500 cd for far-range
        # visibility (still 1/50th of the original blinding value).
        # v0.25.75 (user: "increase the lighted X brightness more"):
        # 500 -> 1500 cd (3x; ~1/16th of the old blinding 25000 cd).
        # v0.25.76 (user: "increase the draw distance"): 1500 -> 2500 cd.
        # Round 13: daytime_intensity 20000 cd keeps the red beacon visible
        # in daylight (night value stays 2500 cd).
        _create_msfs_light("LIGHT_BEACON", tuple((mins + maxs) / 2.0),
                           red, 2500.0, BEACON_FREQ, BEACON_DURATION, 0.0,
                           20000.0)
        created += 1
    print(f"[LIGHT] embedded {created} MSFS street lights "
          f"({total} amber flashing LEDs + 1 red flashing beacon)")


def _compute_fixture_positions() -> list:
    """11 evenly spaced fixtures per arm, t = 0.20 .. 1.00 (last on the tip),
    computed from each arm's hub start and tip end coordinates.

    Round 12: each fixture is offset OUT of the X plane (+Y, the approach
    side) by FIXTURE_PROTRUDE so the lamp heads sit proud of the tube
    surface instead of being buried inside the rods."""
    positions = []
    for arm_i, d in enumerate(ARM_DIRS):
        for k in range(FIXTURES_PER_ARM):
            t = FIXTURE_T_START + k * FIXTURE_T_STEP
            p = HUB + d * (ARM_LEN * t)
            p = Vector((p.x, p.y + FIXTURE_PROTRUDE, p.z))
            positions.append((round(p.x, 3), round(p.y, 3), round(p.z, 3)))
    return positions


def build_marker(fixture_positions: list) -> list:
    """Build the marker; returns the four ARM objects (used by QA) before the
    frame join collapses them into X_SIGN_BODY."""
    _clear_scene()

    yellow = _material("Frame_SafetyYellow", (0.9, 0.62, 0.08), roughness=0.4, metallic=0.35)
    stand = _material("Stand_Galvanized", (0.42, 0.44, 0.47), roughness=0.45, metallic=0.6)
    housing = _material("Light_Housing", (0.13, 0.13, 0.15), roughness=0.4, metallic=0.2)
    # Round 9: the lens STATIC emissive is the flash PEAK. The package's
    # model.xml behavior (<EmissiveFactor> RPN code) multiplies this by a
    # 0/1 pulse every frame, so the dome toggles between full brightness and
    # dark - the light IS the geometry (renders at LOD distance, no fx
    # culling). v0.25.73 (user: "blinding"): peak cut 400 -> 120 so the
    # domes read as lit LEDs, not floodlights; the amber tint (avoid pure
    # colours per SDK note) keeps it a yellow LED.
    lens = _material("MAT_LightedX_Glow", (1.0, 0.85, 0.05), roughness=0.2,
                     emissive=120.0, emissive_color=(1.0, 0.90, 0.12))
    # Dominant red obstruction beacon at the hub (the X intersection):
    # static emissive 100 cd is the flash peak (was 300 - v0.25.73 dim);
    # the model.xml behavior (siren double-flash RPN) toggles it 0/1, so it
    # is dark between pulses.
    center_red = _material("MAT_X_Center_Red", (1.0, 0.06, 0.04), roughness=0.15,
                           emissive=100.0, emissive_color=(1.0, 0.08, 0.05))

    # ── Ground stand: mast + base plate + three splayed legs + feet ───────
    mast = _cylinder("MAST", MAST_R, HUB.z, (0.0, 0.0, HUB.z / 2), axis="Z")
    _apply(mast, stand)
    plate = _cylinder("BASE_PLATE", 0.16, 0.04, (0.0, 0.0, 0.02), axis="Z")
    _apply(plate, stand)
    joint = Vector((0.0, 0.0, LEG_JOINT_Z))
    for leg_i in range(3):
        az = math.radians(90.0 + leg_i * 120.0)
        foot = Vector((FEET_RADIUS * math.cos(az), FEET_RADIUS * math.sin(az), 0.0))
        leg = _tube_along(f"LEG_{leg_i}", LEG_R, (foot - joint).length, (joint + foot) / 2, foot - joint)
        _apply(leg, stand)
        foot_obj = _cylinder(f"FOOT_{leg_i}", FOOT_R, FOOT_H, (foot.x, foot.y, FOOT_H / 2), axis="Z")
        _apply(foot_obj, stand)

    # ── Hub bracket: visible block the arms cross through (solid centre) ───
    hub = _cube("HUB_BRACKET", HUB_BRACKET, tuple(HUB))
    _apply(hub, yellow)

    # ── X arms: tubular beams at 45 deg in the VERTICAL XZ plane (y = 0) ───
    arms = []
    for arm_i, d in enumerate(ARM_DIRS):
        # Inner end tucks 0.25 m past the hub centre (solid overlap), outer
        # tip lands exactly at ARM_LEN so fixtures hug the true tip.
        center = HUB + d * (ARM_LEN / 2 - 0.125)
        arm = _tube_along(f"ARM_{arm_i}", ARM_R, ARM_LEN + 0.25, tuple(center), d)
        _apply(arm, yellow)
        arms.append(arm)

    # ── Light fixtures: dark socket + emissive dome at each computed pos ───
    for idx, (fx, fy, fz) in enumerate(fixture_positions):
        base = _cylinder(f"FIXTURE_{idx}", 0.022, 0.07, (fx, fy, fz + 0.035), axis="Z")
        _apply(base, housing)
        dome = _hemisphere("LENS_" + str(idx), 0.026, (fx, fy, fz + 0.075))
        # Each LED keeps its OWN material (a copy of the amber lens) so the
        # package's model.xml behavior can target every dome's material
        # independently with its own staggered chase code (the behavior
        # components bind to the LENS_<n> nodes).
        led_mat = lens.copy()
        led_mat.name = f"MAT_LED_{idx:02d}"
        _apply(dome, led_mat)

    # ── Center red beacon at the hub (the X intersection) ─────────────────
    # The hub bracket is HUB_BRACKET[2] tall centred on HUB, so it tops out at
    # HUB.z + HUB_BRACKET[2]/2 - the beacon must sit ON TOP of the bracket,
    # otherwise it is buried inside the hub block and never visible.
    bracket_top_z = HUB.z + HUB_BRACKET[2] / 2
    beacon_base = _cylinder("CENTER_BASE", CENTER_BASE_R, CENTER_BASE_H,
                            (HUB.x, HUB.y, bracket_top_z + CENTER_BASE_H / 2), axis="Z")
    _apply(beacon_base, center_red)
    beacon_dome = _hemisphere("CENTER_DOME", CENTER_DOME_R,
                              (HUB.x, HUB.y, bracket_top_z + CENTER_BASE_H + 0.004))
    _apply(beacon_dome, center_red)
    for _o in (beacon_base, beacon_dome):
        for _p in _o.data.polygons:
            _p.use_smooth = True
    bpy.ops.object.select_all(action="DESELECT")
    beacon_base.select_set(True)
    beacon_dome.select_set(True)
    bpy.context.view_layer.objects.active = beacon_base
    bpy.ops.object.join()
    beacon = bpy.context.active_object
    beacon.name = "CENTER_BEACON"
    return arms


def _extent_along(obj: object, d: Vector) -> float:
    d = d.normalized()
    proj = [(obj.matrix_world @ v.co).dot(d) for v in obj.data.vertices]
    return max(proj) - min(proj)


def _mesh_bounds(obj: object) -> tuple:
    mins = Vector((1e9, 1e9, 1e9))
    maxs = Vector((-1e9, -1e9, -1e9))
    for v in obj.data.vertices:
        wc = obj.matrix_world @ v.co
        for i in range(3):
            mins[i] = min(mins[i], wc[i])
            maxs[i] = max(maxs[i], wc[i])
    return mins, maxs


def _qa_verdict(fixture_count: int, arms: list) -> bool:
    results: list = []
    objs = {o.name: o for o in bpy.context.scene.objects
            if o.type == "MESH" and not o.name.endswith("_LOD1")}
    bases = [k for k in objs if k.startswith("FIXTURE_")]
    domes = [k for k in objs if k.startswith("LENS_")]
    ok_fix = len(bases) == fixture_count and len(domes) == fixture_count
    print(f"[QA] fixtures: bases={len(bases)} domes={len(domes)} (expected {fixture_count}/{fixture_count}) "
          f"-> {'PASS' if ok_fix else 'FAIL'}")
    results.append(("fixtures", ok_fix))

    # Arms: hub-to-tip distance along each arm's own direction (the tube is
    # ARM_LEN + 0.25 long because its inner end overlaps 0.25 m past the hub,
    # so the full-tube extent reads 3.0 m) + confirmation they lie in the
    # vertical XZ plane (y deviates only by the tube radius from y = 0).
    arm_lens = []
    for arm_i, arm in enumerate(arms):
        d = ARM_DIRS[arm_i]
        proj = [(arm.matrix_world @ v.co).dot(d) for v in arm.data.vertices]
        tip_dist = max(proj) - HUB.dot(d)          # hub centre -> outer tip
        y_dev = max(abs((arm.matrix_world @ v.co).y) for v in arm.data.vertices)
        ok_plane = y_dev < ARM_R + 0.02            # surface deviates by radius
        arm_lens.append(round(tip_dist, 3))
        print(f"[QA] arm {arm_i}: hub-to-tip={arm_lens[-1]} m, |y| dev={round(y_dev, 4)} "
              f"(vertical-plane {'PASS' if ok_plane else 'FAIL'})")
        results.append((f"arm{arm_i} hub-to-tip", 2.65 <= tip_dist <= 2.85))
        results.append((f"arm{arm_i} plane", ok_plane))
    symmetric = arm_lens and max(arm_lens) - min(arm_lens) < 0.05
    print(f"[QA] arms symmetric ~2.75 m -> {'PASS' if symmetric else 'FAIL'}")
    results.append(("arm symmetry", symmetric))

    # Lowest point of the X: min z of the arm tips (arms in the vertical
    # plane) should sit ~1.0-1.3 m above the ground.
    tip_z = min((arm.matrix_world @ v.co).z for arm in arms for v in arm.data.vertices)
    ok_low = 0.95 <= tip_z <= 1.35
    print(f"[QA] X lowest point z={round(tip_z, 3)} (spec ~1.0-1.2) -> {'PASS' if ok_low else 'FAIL'}")
    results.append(("X lowest height", ok_low))

    # Ground contact: lowest vertex of the feet must touch z ~ 0.
    ground = min((objs[k].matrix_world @ v.co).z for k in objs if k.startswith("FOOT_")
                 for v in objs[k].data.vertices)
    ok_ground = abs(ground) < 0.02
    print(f"[QA] stand ground contact z={round(ground, 3)} -> {'PASS' if ok_ground else 'FAIL'}")
    results.append(("ground contact", ok_ground))

    # Center red beacon: object present, sits at the hub (the X intersection)
    # with its dome above the hub bracket top.
    beacon_obj = objs.get("CENTER_BEACON")
    beacon_ok = bool(beacon_obj)
    beacon_height_ok = False
    bracket_top_z = HUB.z + HUB_BRACKET[2] / 2
    if beacon_obj:
        b_mins, b_maxs = _mesh_bounds(beacon_obj)
        beacon_height_ok = (b_mins.z >= bracket_top_z - 0.02 and
                            b_maxs.z >= bracket_top_z + CENTER_BASE_H + CENTER_DOME_R * 0.8)
        print(f"[QA] center beacon z: {b_mins.z:.3f}..{b_maxs.z:.3f} "
              f"(sits on hub bracket top {bracket_top_z:.2f} + dome above -> "
              f"{'PASS' if beacon_height_ok else 'FAIL'})")
    else:
        print(f"[QA] center beacon missing -> FAIL")
    results.append(("center beacon", beacon_ok))
    results.append(("center beacon height", beacon_height_ok))

    mat_names = {m.name for m in bpy.data.materials}
    for needed in ("Frame_SafetyYellow", "Stand_Galvanized", "Light_Housing",
                   "MAT_LightedX_Glow", "MAT_X_Center_Red"):
        ok = needed in mat_names
        print(f"[QA] material {needed}: {'PASS' if ok else 'FAIL'}")
        results.append((f"material {needed}", ok))

    # Orphan audit (run pre-join): every mesh must be a named part, never a
    # stray default primitive.
    allowed_prefixes = ("ARM_", "LEG_", "FOOT_", "FIXTURE_", "LENS_")
    allowed = ("MAST", "BASE_PLATE", "HUB_BRACKET", "CENTER_BEACON")
    orphans = [o.name for o in bpy.context.scene.objects if o.type == "MESH"
               and not (o.name.startswith(allowed_prefixes) or o.name in allowed)]
    ok_orphans = not orphans
    print(f"[QA] orphan objects: {orphans if orphans else 'none'} -> {'PASS' if ok_orphans else 'FAIL'}")
    results.append(("no orphans", ok_orphans))

    failed = [n for n, ok in results if not ok]
    print(f"[QA] end-state -> {'ALL PASS' if not failed else 'FAIL: ' + ', '.join(failed)}")
    return not failed


def _purge_none_slots(obj: object) -> None:
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


def _render_preview(prefix: str, output_dir: str, preview_out: str) -> str:
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
    return png_path


def _render_front(prefix: str, output_dir: str, preview_out: str) -> str:
    """Straight-on +Y view: the approach view that proves the X reads as an X."""
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
    target = bpy.data.objects.new("CAM_TARGET_FRONT", None)
    bpy.context.collection.objects.link(target)
    target.location = center
    bpy.ops.object.camera_add(location=center + Vector((0.0, -radius * 2.0, 0.0)))
    cam = bpy.context.active_object
    track = cam.constraints.new(type="TRACK_TO")
    track.target = target
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"
    scene.camera = cam

    png_path = os.path.join(output_dir, f"{prefix}_front.png")
    scene.render.filepath = png_path
    bpy.ops.render.render(write_still=True)
    print(f"[RENDER] {png_path}")
    if preview_out:
        import shutil
        os.makedirs(preview_out, exist_ok=True)
        shutil.copyfile(png_path, os.path.join(preview_out, f"{prefix}_FRONT.png"))
    return png_path


def add_light_behaviors() -> None:
    """Round 9: the lights are now delivered by model.xml BEHAVIORS, not by
    keyframe or fx animation.

    Round 8 proved both older mechanisms render FROZEN on static SimObjects
    in MSFS 2024: legacy .fx emitters ignore Rate/Particle Lifetime/Emitter
    Delay (steady, plus fx culling at ~50-60 ft), and ASOBO_property_animation
    material keyframes are not played (the user saw the round-8 domes frozen
    at frame 0 - beacons red, LEDs dark).

    The engine DOES evaluate ModelBehaviors <EmissiveFactor> code every
    frame on SimObjects (the SDK's Windsock sample ships <Behaviors> on a
    non-aircraft SimObject, and Asobo's own blink template uses this exact
    mechanism). The package builder writes one behavior component per lens
    node (LENS_0..43 + CENTER_BEACON) whose RPN code multiplies this
    material's STATIC emissive (exported here at full brightness) by a 0/1
    pulse: the 44 LEDs get a staggered chase wave (tips -> hub -> tips,
    2 s cycle), the centre beacon a siren double-flash (two 0.12 s pulses
    per 1.5 s). Static emissive = flash peak; the dome is dark between
    pulses because the code returns 0.

    Pre-export sanity check: every lens material must carry the MSFS emissive
    attributes (set by _apply_msfs_materials) or the behavior will multiply
    into a black material.
    """
    total_leds = FIXTURES_PER_ARM * len(ARM_DIRS)
    missing = []
    for i in range(total_leds):
        mat = bpy.data.materials.get(f"MAT_LED_{i:02d}")
        if mat is None or not hasattr(mat, "msfs_emissive_factor"):
            missing.append(f"MAT_LED_{i:02d}")
    center = bpy.data.materials.get("MAT_X_Center_Red")
    if center is None or not hasattr(center, "msfs_emissive_factor"):
        missing.append("MAT_X_Center_Red")
    if missing:
        raise SystemExit(f"LIGHT CHECK FAIL: lens materials missing/not MSFS: {missing}")
    print(f"[LIGHT] X: {total_leds} LED lens materials + centre beacon ready for "
          "model.xml <EmissiveFactor> behaviors (static emissive = flash peak)")


def _make_lods() -> tuple:
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
        # v0.25.66: flatten any parenting on the LOD1 copies so the exporter
        # never skips a child whose parent was unlinked for the LOD1 pass.
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
    lod0 = [o for o in bpy.context.scene.objects if o.type == "MESH" and not o.name.endswith("_LOD1")]
    all_m = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    v0 = sum(len(o.data.vertices) for o in lod0)
    f0 = sum(len(o.data.polygons) for o in lod0)
    va = sum(len(o.data.vertices) for o in all_m)
    fa = sum(len(o.data.polygons) for o in all_m)
    print(f"[STATS] LOD0 verts={v0} faces={f0} | total (with LOD1) verts={va} faces={fa}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="")
    parser.add_argument("--fixtures-out", default="", help="Write the computed fixture positions to this path")
    parser.add_argument("--preview-out", default="")
    parser.add_argument("--no-render", action="store_true")
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    args, _ = parser.parse_known_args(argv)

    output_dir = args.output or "C:/closure-markers/Model/X_LIGHTED_TRAILER"
    os.makedirs(output_dir, exist_ok=True)

    positions = _compute_fixture_positions()
    if args.fixtures_out:
        # The red beacon's LIGHT position is the DOME CENTRE - it sits ON TOP
        # of the hub bracket (bracket_top_z = HUB.z + HUB_BRACKET[2]/2), not
        # at HUB.z. A light.xml generated from fixtures.json must place the
        # light where the dome actually is, or it ends up buried in the hub.
        beacon_z = HUB.z + HUB_BRACKET[2] / 2 + CENTER_BASE_H + 0.004
        # NOTE: values are written UNSCALED (the raw generator coordinates).
        # build_official_pkg.py applies MODEL_SCALE/X_SCALE itself when it
        # turns these into systems.cfg lightdefs, so the scale factor lives
        # in exactly one place.
        with open(args.fixtures_out, "w", encoding="utf-8") as fh:
            json.dump({"fixtures": [{"arm": (i // FIXTURES_PER_ARM), "index": i % FIXTURES_PER_ARM,
                                     "x": p[0], "y": p[1], "z": p[2]}
                                    for i, p in enumerate(positions)],
                       "center_beacon": {"x": round(HUB.x, 3), "y": round(HUB.y, 3),
                                         "z": round(beacon_z, 3)},
                       "count": len(positions), "arm_length_m": ARM_LEN, "hub_z": round(HUB.z, 2),
                       "model_scale": MODEL_SCALE}, fh, indent=2)
        print(f"[FIXTURES] wrote {len(positions)} positions + center beacon to {args.fixtures_out} "
              f"(arm {ARM_LEN} m, hub z {HUB.z}, beacon z {beacon_z:.2f}, model_scale {MODEL_SCALE})")

    arms = build_marker(positions)
    _qa_verdict(len(positions), arms)

    # ── Join the whole frame (mast + legs + feet + plate + hub + arms) into
    # ONE continuous body. Fixtures + center beacon stay separate so they can
    # animate/light independently.
    bpy.ops.object.select_all(action="DESELECT")
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH" and not (obj.name.startswith(("FIXTURE_", "LENS_", "CENTER_BEACON"))):
            obj.select_set(True)
    active = bpy.context.scene.objects.get("MAST")
    bpy.context.view_layer.objects.active = active or bpy.context.selected_objects[0]
    bpy.ops.object.join()
    body = bpy.context.active_object
    body.name = "X_SIGN_BODY"
    _purge_none_slots(body)

    # v0.25.66: user requested the lighted X at 1.5x size (after QA, which
    # validates against the unscaled spec constants).
    _scale_scene(MODEL_SCALE)

    # Post-join orphan audit: only the body + fixtures + center beacon must
    # remain.
    names = sorted(o.name for o in bpy.context.scene.objects if o.type == "MESH" and not o.name.endswith("_LOD1"))
    expected = {"X_SIGN_BODY", "CENTER_BEACON"} | {f"FIXTURE_{i}" for i in range(len(positions))} | \
               {f"LENS_{i}" for i in range(len(positions))}
    missing = expected - set(names)
    extra = set(names) - expected
    print(f"[QA] post-join objects: {len(names)} (body + {len(positions)*2} fixture parts + center beacon) -> "
          f"{'PASS' if not missing and not extra else 'FAIL'}")
    if missing or extra:
        print(f"[QA]   missing={sorted(missing)[:5]} extra={sorted(extra)[:5]}")

    bpy.context.view_layer.update()
    _triangulate()
    lod0, lod1 = _make_lods()
    _stats()

    blend_path = os.path.join(output_dir, "X_LIGHTED_TRAILER.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print(f"[BLEND] {blend_path}")

    if not args.no_render:
        for obj in bpy.context.scene.objects:
            if obj.name.endswith("_LOD1"):
                obj.hide_set(True)
        _render_preview("X_LIGHTED_TRAILER", output_dir, args.preview_out)
        _render_front("X_LIGHTED_TRAILER", output_dir, args.preview_out)

    print("[NOTE] standalone export does NOT embed the Round-11 MSFS lights - "
          "run export_msfs_official.py x-lighted so the ASOBO advanced lights "
          "are written into the glTF")
    _export_lod(os.path.join(output_dir, "X_LIGHTED_TRAILER.gltf"), lod0, lod1, want_lod1=False)
    print("[OK] exported X_LIGHTED_TRAILER.gltf (LOD0 only)")
    _export_lod(os.path.join(output_dir, "X_LIGHTED_TRAILER_LOD1.gltf"), lod0, lod1, want_lod1=True)
    print("[OK] exported X_LIGHTED_TRAILER_LOD1.gltf")

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
