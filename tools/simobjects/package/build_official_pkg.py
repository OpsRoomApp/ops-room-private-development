"""OPS ROOM -- official MSFS 2024 package build (Project Editor / fspackagetool).

Emits the *official* 2024 project layout, matching the SDK's Windsock sample
(Samples/DevmodeProjects/SimObjects/Landmarks/Windsock):

    <stage>/
    ├── Project.xml                      <Project Version="2" ...>   <- OPEN THIS
    ├── PackageDefinitions/
    │   └── closure-markers.xml          <AssetPackage Version="0.1.0">
    └── PackageSources/
        └── SimObjects/
            └── Misc/
                └── <NAME>/
                    ├── sim.cfg
                    ├── model/
                    │   ├── model.cfg
                    │   ├── <NAME>.xml          (LOD wrapper)
                    │   ├── <NAME>_LOD00.gltf/.bin
                    │   └── <NAME>_LOD01.gltf/.bin
                    └── texture/
                        └── <tex>.png + <tex>.png.xml

Input: official Blender 4.2 + MSFS addon exports (per-model folders).

Lights (X_LIGHTED_TRAILER + both BARRICADE_T3_*): v0.25.74 - all objects
(light markers included) now ship as Misc/StaticObject, the category of the
plain X markers that NEVER moved. The earlier GroundVehicle experiment
(rounds 10-13) made the fx emitters tick (round 7/8/9 had shown Misc/StaticObject
froze fx emitter timing, ASOBO_property_animation keyframes and ModelBehaviors
<EmissiveFactor>), but SimConnect-spawned AI ground vehicles in MSFS 2024
keep DRIVING no matter what, which broke every placement in-sim at EGKK.
The visible lights now come from the Blender ASOBO_street_light glTF nodes
(the airport-light mechanism - flash_frequency/duration/phase) plus the
static emissive lens materials; the systems.cfg [LIGHTS] + fx files below
are kept as a bonus that may or may not tick on a static object.
Each light marker ships:
  - a GroundVehicle sim.cfg (parked-vehicle layout, copied from the SDK
    AirportVehicles/Boarding_Stairs sample),
  - systems.cfg [ELECTRICAL] (always-on battery bus + beacon/strobe
    circuits) + [LIGHTS] lightdefs (Type:1 beacon / Type:2 strobe) with
    #Node: references pinning each light to a lens/beacon node,
  - per-node .fx effects in effects/: ORS_Beacon.fx (slow red beacon,
    FNX-style Rate/Delay/Lifetime emitter pattern with far-range spot light
    attributes) and 44 ORS_LED_*.fx with staggered emitter delays so the
    flash travels the X arms hub->tip (a chase) every cycle,
  - fx sprites reference the stock fx_0.png glow texture (as the FNX
    beacons do) - no custom texture is shipped.
The lens materials keep their full static emissive as the lens body, and the
model.xml ships with NO <Behaviors> block (Round 11: the earlier bare
<EmissiveFactor> codes were rejected by the MSFS 2024 behavior parser,
failing the whole model load while the fx lights kept working). The visible
chase/siren comes entirely from the fx emitter stagger in effects/.

Usage:
    python tools/simobjects/package/build_official_pkg.py [--models DIR]

Then either:
  A) Open <stage>/Project.xml in the in-sim Project Editor (Dev Mode) and Build.
  B) Run the CLI while the sim is closed:
        "C:\\MSFS 2024 SDK\\Tools\\bin\\fspackagetool.exe" <stage>/Project.xml
     (The CLI launches FlightSimulator2024.exe itself; Store installs may block
      that -- the Project Editor inside the running game is the reliable path.)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

PACKAGE_NAME = "closure-markers"
PROJECT_NAME = "OPSRoomClosureMarkers"
COMPANY = "opsroom"

OBJECTS: list[tuple[str, str]] = [
    ("X_MARKER_RUNWAY", "ORS CLOSURE MARKER X RUNWAY"),
    ("X_MARKER_TAXIWAY", "ORS CLOSURE MARKER X TAXIWAY"),
    ("X_LIGHTED_TRAILER", "ORS CLOSURE MARKER X LIGHTED"),
    ("BARRIER_LOW_ORANGE", "ORS CLOSURE BARRIER LOW ORANGE"),
    ("BARRIER_LOW_WHITE", "ORS CLOSURE BARRIER LOW WHITE"),
    ("BARRICADE_T3_ORANGE", "ORS TYPE III BARRICADE ORANGE"),
    ("BARRICADE_T3_WHITE", "ORS TYPE III BARRICADE WHITE"),
]

# ── Lights: model.xml <Behaviors> ───────────────────────────────────────
# Round 11: the light markers ship WITHOUT a <Behaviors> block in model.xml.
# The earlier round-9 attempt wrote bare <EmissiveFactor> codes (MSFS 2020
# syntax, directly under <Component>) which the MSFS 2024 behavior parser
# rejects at runtime: the whole model then fails to load (mesh invisible)
# while the systems.cfg [LIGHTS] + fx effects - a separate engine mechanism
# that never touches model.xml - kept flashing. Removing the block makes the
# light objects structurally identical to the static markers that always
# rendered. The visible chase/siren comes entirely from the fx emitter
# stagger in effects/ (Rate/Delay/Lifetime), which is proven to work in-sim.
# If emissive pulsing is ever needed again, the correct MSFS 2024 syntax is:
#   <Component ID="..." Node="LENS_0"
#     UpdateFrequencyPreset="Asobo_Default_NeverStop">
#     <Material>
#       <EmissiveFactor>
#         <Parameter><Code>...</Code></Parameter>
#         <OverrideBaseEmissive>False</OverrideBaseEmissive>
#       </EmissiveFactor>
#     </Material>
#   </Component>
# (EmissiveFactor lives inside <Material>, per TemplateExplorer
# Asobo_EX1/Base/Component/Material.xml.)

OBJECTS_WITH_LIGHTS = {"X_LIGHTED_TRAILER", "BARRICADE_T3_ORANGE", "BARRICADE_T3_WHITE"}

#: v0.25.74: ALL objects ship as Misc/StaticObject. The GroundVehicle
#: experiment (rounds 10-13) gave the fx emitters a ticking vehicle sim, but
#: SimConnect-spawned AI ground vehicles in MSFS 2024 keep DRIVING no matter
#: what (SIM DISABLED every 3 s + max_speed 0.1 + no [WAYPOINT] all failed
#: in-sim at EGKK 26L - "barricades still moving and going all over the
#: place"). Misc/StaticObject spawns are the category of the plain X markers
#: that NEVER moved. The Blender ASOBO_street_light glTF nodes (the
#: airport-light mechanism, flash_frequency/duration/phase) + the static
#: emissive lens materials carry the lights, so the models stay visible and
#: flashing without the vehicle sim. The systems.cfg [LIGHTS] + fx files are
#: kept as a harmless bonus (static-object fx may not tick, which is fine).
LIGHT_OBJECTS = frozenset(OBJECTS_WITH_LIGHTS)

#: LED fixture count per arm (must match make_lighted_x_trailer). LED index
#: i = arm * LEDS_PER_ARM + k with k=0 nearest the hub and k=10 the arm tip.
#: The fx chase stagger below (0.06 * k) uses k to delay each LED so the lit
#: band runs hub -> tip along each arm.
LEDS_PER_ARM = 11

# Maps the glTF base-color image to the MSFS bitmap slot sidecar we write.
TEXTURE_SLOT = "MTL_BITMAP_DECAL0"

SIM_CFG_TEMPLATE = """[fltsim.0]
title={title}
model=
texture=

[General]
category=StaticObject
DistanceToNotAnimate=2000
"""

#: Round 10: parked-ground-vehicle sim.cfg for the light markers (mirrors the
#: SDK AirportVehicles sample; vehicle category is what makes SimConnect AI
#: spawns run the real simulation, so the [LIGHTS] + .fx timing actually tick).
SIM_CFG_VEHICLE_TEMPLATE = """[VERSION]
Major=1
Minor=0

[fltsim.0]
title={title}
model=
texture=

[General]
category=GroundVehicle
DistanceToNotAnimate=2000

[contact_points]
wheel_radius=0.5
static_pitch=0.0
static_cg_height=0

[DesignSpecs]
max_speed_mph = 0.1
acceleration_constants = 0.3, 0.4
deceleration_constants = 0.2, 0.4
"""

# ── Round 10: [LIGHTS] lightdefs + per-node fx ───────────────────────────
# The engine flash for Type:1 (beacon) / Type:2 (strobe) lightdefs is driven
# by the referenced fx emitter (Rate/Delay/Lifetime), exactly like the FNX
# A320's working beacons (Type=19 particle, far-range spot LightAttributes).
# v0.25.76 (user: "the lights fade away from a distance"): the fx sprites are
# now the FAR-VISIBILITY glow - STEADY (Rate=0.05 / Life=20 keeps exactly one
# persistent billboard alive whether or not the sim animates fx on static
# SimObjects), with the far-range recipe Range=5000 m (the old 500 m culled
# the glow past half a kilometre), a 2-3x larger sprite, a much stronger
# LightAttributes intensity and a 4-5x brighter sprite alpha. The chase/siren
# animation stays on the ASOBO_street_light nodes embedded in the glTF (the
# mechanism the user confirmed animates in-sim), so the fx no longer stagger.

FX_TEMPLATE = """[Library Effect]
Lifetime=5
Version=2.0
Radius=-1
Priority=0

[Properties]

[Emitter.0]
Lifetime=0.0, 0.0
Delay={delay}, {delay}
Bounce=0.0
Light=1
No Interpolate=1
Rate={rate}, {rate}
X Emitter Velocity=0.0, 0.0
Y Emitter Velocity=0.0, 0.0
Z Emitter Velocity=0.0, 0.0
Drag=0.0, 0.0
X Particle Velocity=0.0, 0.0
Y Particle Velocity=0.0, 0.0
Z Particle Velocity=0.0, 0.0
X Rotation=0.0, 0.0
Y Rotation=0.0, 0.0
Z Rotation=0.0, 0.0
X Offset=0.0, 0.0
Y Offset=0.0, 0.0
Z Offset=0.0, 0.0

[Particle.0]
Lifetime={life}, {life}
Type=19
X Scale={scale}, {scale}
Y Scale={scale}, {scale}
Z Scale=0.0, 0.0
X Scale Rate=0.0, 0.0
Y Scale Rate=0.0, 0.0
Z Scale Rate=0.0, 0.0
Drag=0.0, 0.0
Color Rate=0.0, 0.0
X Offset=0.0, 0.0
Y Offset=0.0, 0.0
Z Offset=0.0, 0.0
Fade In=0.0, 0.0
Fade Out=0.0, 0.0
Rotation=0.0, 0.0
Static=1
Face=1, 1, 1

[ParticleAttributes.0]
Blend Mode=2
Texture=fx_0.png
Bounce=0.0
Color Start={r}, {g}, {b}, {alpha}
Color End={r}, {g}, {b}, {alpha}
Jitter Distance=0.0
Jitter Time=0.0
uv1=0.0, 0.0
uv2=1.0, 1.0
NearEndFade=1.0
NearFade=12.0
MinProjSize=0.4

[LightAttributes.0]
Type=spot
Size=0.12
Range={range}
Intensity={intensity}
Softness=0.0
SpotInner=80.0
SpotOuter=90.0
volumetric=0
ScatDir=0.0
"""


#: v0.25.76 far-range steady glow. Beacon: 1.0 m red sprite, Range 5000 m,
#: Intensity 2000 cd - the FNX far-recipe with the cull removed. LED: 0.7 m
#: amber sprite, Range 5000 m, Intensity 1500 cd. Rate=0.05 / Life=20 keeps
#: exactly one persistent sprite per node whether or not the sim animates fx
#: on static SimObjects (steady either way - the old Rate=0.8 / Life=0.1
#: blinked the glow off most of the time).
def _fx_text(kind: str, led_index: int | None = None) -> str:
    if kind == "beacon":
        params = {"delay": "0.00", "rate": "0.05", "life": "20.0", "scale": "1.0",
                   "range": "5000.0", "intensity": "2000.0", "alpha": "30",
                   "r": "255", "g": "0", "b": "0"}
    else:
        params = {"delay": "0.00", "rate": "0.05", "life": "20.0", "scale": "0.7",
                   "range": "5000.0", "intensity": "1500.0", "alpha": "25",
                   "r": "255", "g": "140", "b": "0"}
    return FX_TEMPLATE.format(**params)


#: lightdef for one light: Type:1 beacon / Type:2 strobe, pinned to the node
#: (the engine reads the node's world position - no feet/meter guessing).
def _lightdef(n: int, typ: int, idx: int, node: str, fx: str) -> str:
    """lightdef line matching the FNX A320's proven syntax verbatim
    (Type:1 beacon / Type:2 strobe). PotentiometerIndex:0 = battery-direct,
    always on - no switch wiring needed."""
    return (
        f"lightdef.{n} = Type:{typ}#Index:{idx}#"
        f"LocalPosition:0,0,0#LocalRotation:0,0,0#"
        f"EffectFile:{fx}#Node:{node}#PotentiometerIndex:0"
    )


def _systems_cfg_text(folder: str) -> str:
    lines = [
        "[ELECTRICAL]",
        "bus.1 = Name:Main_Bus_A",
        "max_battery_voltage = 28000",
        "battery.1 = Connections:bus.1#Capacity:28000#Voltage:curve.1#Name:Main_Battery",
        "curve.1 = 0:28, 1:28",
        # Always-on light circuits on the battery bus. MSFS 2024 key=value
        # syntax (SDK Implementing_Lights.htm); the lightdefs' Potentiometer
        # Index:0 powers them directly, these are belt-and-braces.
        "circuit.0 = Type:CIRCUIT_LIGHT_BEACON#Voltage:28#Amperage:1#Name:LightBeacon",
        "circuit.1 = Type:CIRCUIT_LIGHT_STROBE#Voltage:28#Amperage:1#Name:LightStrobe",
        "",
        "[LIGHTS]",
    ]
    if folder == "X_LIGHTED_TRAILER":
        lines.append(_lightdef(0, 1, 1, "CENTER_BEACON", "ORS_Beacon"))
        for i in range(44):
            lines.append(_lightdef(i + 1, 2, 1, f"LENS_{i}", f"ORS_LED_{i:02d}"))
    else:
        lines.append(_lightdef(0, 1, 1, "BEACON", "ORS_Beacon"))
    return "\n".join(lines) + "\n"


#: The fx sprites reference the STOCK fx_0.png glow texture built into the
#: sim (same sprite the FNX A320 beacons use) - nothing to ship, nothing for
#: the Project Editor to compile, one less failure mode.

MODEL_CFG_TEMPLATE = "[models]\r\nnormal={name}.xml\r\n"


def _write_lf(path: Path, text: str) -> None:
    path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))


def _project_xml() -> str:
    return (
        '<Project Version="2" Name="{proj}" FolderName="Packages">\r\n'
        "\t<OutputDirectory>.</OutputDirectory>\r\n"
        "\t<TemporaryOutputDirectory>_PackageInt</TemporaryOutputDirectory>\r\n"
        "\t<Packages>\r\n"
        "\t\t<Package>PackageDefinitions\\{pkg}.xml</Package>\r\n"
        "\t</Packages>\r\n"
        "</Project>\r\n"
    ).format(proj=PROJECT_NAME, pkg=PACKAGE_NAME)


def _object_subfolder(folder: str) -> str:
    # v0.25.74: every object (including the light markers) ships under
    # SimObjects/Misc as StaticObject - the category that stays parked.
    return "Misc"


def _package_definition_xml() -> str:
    groups = []
    for folder, _title in OBJECTS:
        sub = _object_subfolder(folder)
        groups.append(
            ('\t\t<AssetGroup Name="{folder}">\r\n'
             '\t\t\t<Type Version="1">SimObject</Type>\r\n'
             "\t\t\t<Flags>\r\n"
             "\t\t\t\t<FSXCompatibility>false</FSXCompatibility>\r\n"
             "\t\t\t</Flags>\r\n"
             '\t\t\t<AssetDir>PackageSources\\SimObjects\\{sub}\\{folder}\\</AssetDir>\r\n'
             '\t\t\t<OutputDir>SimObjects\\{sub}\\{folder}\\</OutputDir>\r\n'
             "\t\t</AssetGroup>")
            .format(folder=folder, sub=sub)
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\r\n'
        '<AssetPackage Version="0.1.0">\r\n'
        "\t<ItemSettings>\r\n"
        "\t\t<ContentType>SCENERY</ContentType>\r\n"
        "\t\t<Title>OPS ROOM NOTAM Closure Markers</Title>\r\n"
        "\t\t<Manufacturer/>\r\n"
        "\t\t<Creator>OPS ROOM</Creator>\r\n"
        "\t</ItemSettings>\r\n"
        "\t<Flags>\r\n"
        "\t\t<VisibleInStore>false</VisibleInStore>\r\n"
        "\t\t<CanBeReferenced>true</CanBeReferenced>\r\n"
        "\t</Flags>\r\n"
        "\t<PackageOrderHint>CUSTOM_SIMOBJECTS</PackageOrderHint>\r\n"
        "\t<AssetGroups>\r\n"
        + "\r\n".join(groups)
        + "\r\n\t</AssetGroups>\r\n"
        "</AssetPackage>\r\n"
    )


def _lod_xml(folder: str, has_lod1: bool) -> str:
    guid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"opsroom://closure/{folder}")).upper()
    lods = [
        f'\t\t<LOD MinSize="30" ModelFile="{folder}_LOD00.gltf"/>'
    ]
    if has_lod1:
        lods.append(f'\t\t<LOD MinSize="0" ModelFile="{folder}_LOD01.gltf"/>')
    return (
        '<?xml version="1.0" encoding="utf-8" ?>\r\n'
        '<ModelInfo version="1.1" guid="{' + guid + '}">\r\n'
        "\t<LODS>\r\n"
        + "\r\n".join(lods)
        + "\r\n\t</LODS>\r\n"
        # No <Behaviors> block (Round 11): see the lights section header.
        + "</ModelInfo>\r\n"
    )


def _rewrite_gltf(gltf_path: Path, folder: str, src_dir: Path, texture_dir: Path, models_root: Path) -> None:
    """Rename LOD files, fix buffer/image URIs, relink textures into texture/."""
    doc = json.loads(gltf_path.read_text(encoding="utf-8-sig"))

    # Buffer URI: <folder>.bin -> <folder>_LOD00.bin
    for buf in doc.get("buffers", []):
        uri = buf.get("uri", "")
        if uri.endswith(".bin"):
            if uri == f"{folder}.bin":
                buf["uri"] = f"{folder}_LOD00.bin"
            elif uri.endswith("_LOD1.bin"):
                buf["uri"] = uri.replace("_LOD1.bin", "_LOD01.bin")

    # Image URIs -> bare filename, textures copied into texture/
    for img in doc.get("images", []):
        uri = img.get("uri", "")
        if not uri:
            continue
        name = Path(uri.replace("\\", "/")).name
        rel = uri.replace("\\", "/")
        src_img = (src_dir / rel).resolve()
        if not src_img.exists():
            src_img = (src_dir.parent / rel).resolve()
        if not src_img.exists():
            src_img = (gltf_path.parent / rel).resolve()
        if not src_img.exists():
            # Bare filename: search the simobjects tree for it.
            for cand in models_root.parent.parent.resolve().rglob(name):
                src_img = cand
                break
        if src_img.exists() and src_img != texture_dir / name:
            shutil.copy2(src_img, texture_dir / name)
            # Write the MSFS bitmap-slot sidecar like the SDK samples do.
            sidecar = texture_dir / f"{name}.xml"
            if not sidecar.exists():
                _write_lf(
                    sidecar,
                    "<BitmapConfiguration>\r\n"
                    f"\t<BitmapSlot>{TEXTURE_SLOT}</BitmapSlot>\r\n"
                    "</BitmapConfiguration>\r\n",
                )
        img["uri"] = name

    gltf_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def stage(models_dir: Path, stage_root: Path) -> Path:
    """Assemble the official 2024 project tree."""
    if stage_root.exists():
        shutil.rmtree(stage_root)
    (stage_root / "PackageDefinitions").mkdir(parents=True, exist_ok=True)

    for folder, title in OBJECTS:
        src_model = models_dir / folder
        if not src_model.exists():
            print(f"  WARN: no source {src_model} -- skipping {title}")
            continue

        obj_dir = stage_root / "PackageSources" / "SimObjects" / _object_subfolder(folder) / folder
        model_dir = obj_dir / "model"
        texture_dir = obj_dir / "texture"
        model_dir.mkdir(parents=True, exist_ok=True)
        texture_dir.mkdir(parents=True, exist_ok=True)

        # v0.25.74: all objects use the StaticObject sim.cfg (Misc category)
        # - the category that never moves, exactly like the plain X markers.
        _write_lf(obj_dir / "sim.cfg", SIM_CFG_TEMPLATE.format(title=title))
        _write_lf(model_dir / "model.cfg", MODEL_CFG_TEMPLATE.format(name=folder))

        # Copy glTF/bin, renaming base -> _LOD00 and _LOD1 -> _LOD01.
        for item in sorted(src_model.iterdir()):
            if not item.is_file():
                continue
            if item.suffix.lower() not in (".gltf", ".bin"):
                continue
            target = item.name
            if target == f"{folder}.gltf":
                target = f"{folder}_LOD00.gltf"
            elif target == f"{folder}.bin":
                target = f"{folder}_LOD00.bin"
            elif "_LOD1" in target:
                target = target.replace("_LOD1", "_LOD01")
            shutil.copy2(item, model_dir / target)

        # Rewrite URIs + relink textures for every LOD.
        for gltf in sorted(model_dir.glob("*.gltf")):
            _rewrite_gltf(gltf, folder, src_model, texture_dir, models_dir)

        # v0.25.66 regression guard: the in-sim PackageBuilder SILENTLY drops
        # glTF/bin compiled from stock-Khronos exports ("Output path does not
        # exist ... LOD00.gltf/bin", _EndTreatCommands fails) and only accepts
        # the official Asobo MSFS2024 addon format. Fail loudly here instead
        # of shipping a package that can never compile.
        for gltf in sorted(model_dir.glob("*.gltf")):
            try:
                _doc = json.loads(gltf.read_text(encoding="utf-8-sig"))
                _gen = _doc.get("asset", {}).get("generator", "")
            except Exception as _exc:
                _gen = ""
            if "Asobo Studio MSFS2024" not in _gen:
                raise SystemExit(
                    f"STAGE ERROR: {gltf.name} was NOT exported by the official "
                    "Asobo MSFS2024 addon (generator=" + repr(_gen[:60]) +
                    "). Re-export with: E:/Blender 4.2/blender.exe --background "
                    "--python tools/simobjects/blender/export_msfs_official.py "
                    "-- <model> <outdir> (the in-sim Project Editor rejects "
                    "stock-Khronos glTFs)."
                )

        has_lod1 = (model_dir / f"{folder}_LOD01.gltf").exists()
        _write_lf(model_dir / f"{folder}.xml", _lod_xml(folder, has_lod1))

        if folder in LIGHT_OBJECTS:
            # Round 10/11: systems.cfg [LIGHTS] + per-node fx emitters. The
            # model.xml ships WITHOUT a <Behaviors> block (see header) - the
            # chase/siren animation comes entirely from these fx emitters.
            # v0.25.74: kept for the light objects even though they now live
            # under Misc/StaticObject - static-object fx emitters may not
            # tick, but the glTF street-light nodes + emissive lenses are the
            # primary lights; the fx files are a harmless bonus (and they
            # keep working if the sim does tick them).
            _write_lf(obj_dir / "systems.cfg", _systems_cfg_text(folder))
            fx_dir = obj_dir / "effects"
            fx_dir.mkdir(parents=True, exist_ok=True)
            _write_lf(fx_dir / "ORS_Beacon.fx", _fx_text("beacon"))
            if folder == "X_LIGHTED_TRAILER":
                for i in range(44):
                    _write_lf(fx_dir / f"ORS_LED_{i:02d}.fx", _fx_text("led", i))
            # fx sprites use the stock fx_0.png texture - nothing to ship.

        tex_files = [p.name for p in sorted(texture_dir.iterdir())]
        print(f"  {folder}: models={len(list(model_dir.glob('*.gltf')))} textures={tex_files or 'none'}"
              + (" lights=systems.cfg+fx" if folder in OBJECTS_WITH_LIGHTS else ""))

    _write_lf(stage_root / "Project.xml", _project_xml())
    _write_lf(stage_root / "PackageDefinitions" / f"{PACKAGE_NAME}.xml", _package_definition_xml())
    return stage_root / "Project.xml"


def _sdk_bin() -> Path:
    candidates = [
        Path(os.environ.get("MSFS_SDK_ROOT", "")) / "Tools" / "bin",
        Path("C:/MSFS 2024 SDK/Tools/bin"),
    ]
    for c in candidates:
        if (c / "fspackagetool.exe").exists():
            return c
    raise SystemExit("fspackagetool.exe not found -- pass --sdk or set MSFS_SDK_ROOT")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default="", help="Dir holding official exports (default: tools/simobjects/feedback/official_pilot_models)")
    parser.add_argument("--sdk", default="", help="MSFS 2024 SDK Tools/bin dir")
    parser.add_argument("--out", default="", help="Parent dir for compiled output")
    parser.add_argument("--run-cli", action="store_true", help="Also invoke fspackagetool on the staged project")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    models_dir = Path(args.models).resolve() if args.models else root / "feedback" / "official_pilot_models"
    if not models_dir.exists():
        print(f"ERROR: no model exports at {models_dir}", file=sys.stderr)
        return 1

    stage_root = root / "feedback" / "fspkg_stage"
    project = stage(models_dir, stage_root)
    print(f"\nSTAGED PROJECT: {project}")
    print("Open this file in Dev Mode -> Project Editor (File -> Open Project) and click Build.")

    if args.run_cli:
        sdk_bin = Path(args.sdk).resolve() if args.sdk else _sdk_bin()
        out_parent = Path(args.out).resolve() if args.out else root / "feedback" / "fspkg_out"
        out_parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            str(sdk_bin / "fspackagetool.exe"),
            str(project),
            "-outputdir",
            str(out_parent),
            "-rebuild",
            "-nopause",
        ]
        print(f"\nRunning: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=str(stage_root), capture_output=True, text=True, timeout=600)
        print(result.stdout[-6000:])
        if result.stderr:
            print("STDERR:", result.stderr[-2000:])
        built = out_parent / PACKAGE_NAME
        if built.exists() and (built / "manifest.json").exists():
            print(f"BUILT OK: {built}")
        else:
            print("CLI produced no package (Store install limitation). Use the Project Editor route.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
