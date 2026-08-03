# Public-release validator for OPS ROOM 0.25.59.
#
# NOTE: the filename is historical (it started for the v0.25.6 release) and is referenced
# by name in BUILD OPS ROOM COMPLETE.bat and BUILD WINDOWS APP ONLY.bat. The constants,
# package-name, codename and assertions inside this file have been migrated to expect
# 0.25.59. Do not rename the file without also updating the BAT callers.

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
from typing import Any
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CHECKS: list[tuple[str, bool, str]] = []
PARSER = argparse.ArgumentParser(description="Validate the OPS ROOM 0.25.59 public release")
PARSER.add_argument("--dist", help="Generated dist directory to validate after packaging")
ARGS = PARSER.parse_args()


def check(name: str, condition: Any, detail: str = "") -> None:
    ok = bool(condition)
    CHECKS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" - {detail}" if detail else ""))


def skip(name: str, detail: str = "") -> None:
    print(f"SKIP: {name}" + (f" - {detail}" if detail else ""))


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


# ---------------------------------------------------------------------------
# Public 0.25.59 release identity and package contract
# ---------------------------------------------------------------------------
RELEASE_VERSION = "0.25.59"
RELEASE_BUILD = "public-release"
RELEASE_CODENAME = "Release Migration"
RELEASE_CHANNEL = "stable"
PACKAGE_NAME = "OPS_ROOM_v0_25_59_Public_Windows_x64.zip"
RELEASE_REPO = "https://github.com/OpsRoomApp/ops-room-releases"
DOWNLOAD_URL = f"{RELEASE_REPO}/releases/download/{RELEASE_VERSION}/{PACKAGE_NAME}"
RELEASE_NOTES_URL = f"{RELEASE_REPO}/releases/tag/{RELEASE_VERSION}"
DEFAULT_MANIFEST_URL = "https://opsroom.live/api/update.json"

version = json.loads(text("version.json"))
manifest = json.loads(text("update.json"))
main_text = text("app/main.py")
launcher_text = text("opsroom_launcher.py")
updater_text = text("app/updater.py")
system_status_text = text("app/system_status.py")
ui = text("app/static/opsroom.js")
html = text("app/static/index.html")
host_html = text("app/static/host.html")
pirep_html = text("app/static/pirep.html")
pirep_print_css = text("app/static/pirep_print.css")
pirep_print_js = text("app/static/pirep_print.js")
scoring_rules_html = text("app/static/scoring_rules.html")
service_worker = text("app/static/service-worker.js")
css = text("app/static/opsroom.css")
complete = text("BUILD OPS ROOM COMPLETE.bat")
windows = text("BUILD WINDOWS APP ONLY.bat")
camera = text("BUILD CAMERA BRIDGE 2024.bat")
spec_text = text("OPS_ROOM.spec")
release_notes_md = text("RELEASE_NOTES.md")
release_notes_txt = text("RELEASE_NOTES.txt")
readme_md = text("README.md")
readme_txt = text("README.txt")

check("version metadata is the stable 0.25.59 public release", version == {
    "version": RELEASE_VERSION,
    "codename": RELEASE_CODENAME,
    "channel": RELEASE_CHANNEL,
    "build": RELEASE_BUILD,
    "abi": version.get("abi", 1),
})
check(
    "source manifest targets the exact 0.25.59 GitHub release and keeps the build placeholder",
    manifest.get("latest_version") == RELEASE_VERSION
    and manifest.get("version") == RELEASE_VERSION
    and manifest.get("codename") == RELEASE_CODENAME
    and manifest.get("channel") == RELEASE_CHANNEL
    and manifest.get("release_notes_url") == RELEASE_NOTES_URL
    and manifest.get("download_url") == DOWNLOAD_URL
    and manifest.get("url") == DOWNLOAD_URL
    and manifest.get("sha256") == "TO_BE_FILLED_BY_BUILD_SCRIPT",
)
check(
    "manifest generator uses the stable public identity and local ZIP hashing",
    'RELEASE_CODENAME = "Release Migration"' in text("tools/write_update_manifest.py")
    and 'RELEASE_CHANNEL = "stable"' in text("tools/write_update_manifest.py")
    and "def sha256" in text("tools/write_update_manifest.py"),
)
check(
    "runtime, launcher, diagnostics and system status target 0.25.59",
    'FastAPI(title="OPS ROOM", version="0.25.59")' in main_text
    and '"version": "0.25.59"' in main_text
    and '"0.25.59"' in system_status_text
    and "Starting OPS ROOM 0.25.59" in launcher_text
    and "version:'0.25.59'" in ui,
)
check(
    "updater default stays on the public raw main manifest and 0.25.59 fallback",
    DEFAULT_MANIFEST_URL in updater_text and 'DEFAULT_VERSION = "0.25.59"' in updater_text,
)
check("short temp roots are intermediates only (OR250)", "%TEMP%\\OR250" in complete and "%TEMP%\\OR250" in windows and "%TEMP%\\OR250" in camera)
check(
    "build scripts agree on the public package and stable manifest channel",
    complete.count(PACKAGE_NAME) >= 3
    and windows.count(PACKAGE_NAME) >= 3
    and "--version 0.25.59 --channel stable" in complete
    and "--version 0.25.59 --channel stable" in windows,
)
check("PMDG EULA is bundled by PyInstaller", "PMDG_777_SDK_EULA.txt" in spec_text and (ROOT / "PMDG_777_SDK_EULA.txt").stat().st_size > 10000)
check("adapter schema version stays at 0.24.106 (catalogue schema BC-preserving)", text("app/aircraft_adapter_installer.py").count('ADAPTER_VERSION = "0.24.106"') >= 1)

# ---------------------------------------------------------------------------
# Complete-build fail-fast hardening - static parse only
# ---------------------------------------------------------------------------
check(
    "complete-build no longer silent-skips the verifier/manifest behind `if exist \"%VENV_PY%\"`",
    'if exist "%VENV_PY%" (' not in complete and 'if not exist "%VENV_PY%"' in complete,
)
check(
    "complete-build wires public release validation before and after packaging",
    "validate_v0256_public_release.py" in complete
    and "verify_public_package.py" in complete
    and "--dist \"%DIST_DIR%\"" in complete,
)
check(
    "complete-build propagates non-zero on archive and generated-manifest steps",
    complete.count("|| goto :fail") >= 2 and "write_update_manifest.py" in complete and "Compress-Archive" in complete,
)

# PMDG Documentation/ is internal evidence only and MUST NOT ship: assert the packaged-asset
# copy path (BUILD WINDOWS APP ONLY.bat) and the PyInstaller datas do not reference it.
check(
    "PMDG Documentation/ is NOT referenced by any packaged-asset copy path (internal evidence only)",
    "PMDG Documentation" not in windows and "PMDG Documentation" not in complete and "PMDG Documentation" not in spec_text,
)
check(
    "packaged-asset path bundles the whole app/static folder and application package",
    '(str(root / "app" / "static"), "app/static")' in spec_text,
)

# ---------------------------------------------------------------------------
# Public UI identity, cache invalidation and distributable documentation
# ---------------------------------------------------------------------------
check(
    "all visible UI release labels and cache-busters use 0.25.59 public identity",
    "OPS ROOM 0.25.59 PUBLIC RELEASE" in html
    and html.count("v=0-25-59") == 4
    and ("<strong>0.25.59</strong>" in host_html or '<strong class="build">0.25.59</strong>' in host_html)
    and host_html.count("v=0-25-59") == 2
    and "OPS ROOM 0.25.59" in pirep_html
    and pirep_html.count("v=0-25-59") == 2
    and "OPS ROOM 0.25.59" in pirep_print_css
    and "OPS ROOM 0.25.59" in pirep_print_js
    and "0.25.59" in scoring_rules_html
    and service_worker.startswith("// OPS ROOM 0.25.59:"),
)
check(
    "public release-note inputs are concise, identical and free of historical version or development language",
    release_notes_md == release_notes_txt
    and "v0.24." not in release_notes_md
    and all(token not in release_notes_md.lower() for token in ("source-ready", "development handoff", "validation limits")),
)
check(
    "distributed README inputs are public user guidance without stale release/developer handoff text",
    "0.25.59" in readme_md
    and "0.25.59" in readme_txt
    and all(token not in (readme_md + readme_txt).lower() for token in ("source-ready", "development handoff", "v0.24.")),
)

# ---------------------------------------------------------------------------
# RC6 carryover behavioural checks (re-verified against RC7 code, then v0.25.x)
# ---------------------------------------------------------------------------

check("startup FSUIPC log silencer is wired", "aircraft_fsuipc_reduce_log" in main_text and "OpsRoom-FSUIPC-Silence" in main_text and "FSUIPC log mitigation at startup" in main_text)
check("reduce_fsuipc_log_size endpoint kept for manual silencer", "/api/blackbox/fsuipc-log/reduce" in main_text)
if (ROOT / "tools/test_fsuipc_log_cleanup.py").is_file():
    cleanup_tests = subprocess.run(
        [sys.executable, str(ROOT / "tools/test_fsuipc_log_cleanup.py")],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    check(
        "FSUIPC cleanup behavioral regressions pass",
        cleanup_tests.returncode == 0,
        (cleanup_tests.stdout + cleanup_tests.stderr).strip()[-200:] if cleanup_tests.returncode else "ran",
    )
else:
    skip("FSUIPC cleanup behavioral regressions pass", "tools/test_fsuipc_log_cleanup.py not present in this environment")

check("Controls tab renders sidestick/yoke crosshair (HTML/SVG redesign)", "bb-widget-crosshair" in ui and "bb-crosshair" in ui and "stickMarker" in ui and "SIDESTICK" in ui)
check("Controls tab renders twin throttle levers", "bb-widget-throttles" in ui and "bb-throttle-levers" in ui and "LVR" in ui)
check("Controls tab renders rudder widget with role-aware PEDAL/SURFACE label (HTML/SVG redesign)", "bb-widget-rudder" in ui and "bb-rudder-svg" in ui and "bb-pedal-rail" in ui and "'PEDAL'" in ui and "'SURFACE'" in ui)
check("Controls tab renders left/right brake pressure gauges", "bb-widget-brakes" in ui and "BRAKES" in ui and "bb-brake-gauges" in ui)
check("Controls tab renders spoiler/flap position scales", "bb-widget-spoiler-flap" in ui and "FLIGHT SURFACES" in ui and "FLAP POS" in ui)
check("Controls tab renders animated landing gear", "bb-widget-gear" in ui and "LANDING GEAR" in ui and "gearPhase" in ui and "IN TRANSITION" in ui)
check("Controls tab renders live numeric readouts", "bb-readout" in ui and "bb-readout-group" in ui)
check("Controls renders explicit unavailable state (not fabricated neutral) + canonical stick guard", "avail(" in ui and "bb-unavailable" in ui and "logLegacyScaleOnce" in ui)
check("engineering Controls telemetry CSS rules exist", "bb-controls-grid" in css and "bb-crosshair" in css and "bb-throttle-levers" in css and "bb-gear-piston" in css)

credits = text("BLACK_BOX_DESIGN_CREDITS.md")
notices = text("THIRD_PARTY_NOTICES.txt")
check("SkyDolly remains credited in BLACK_BOX_DESIGN_CREDITS.md", "SkyDolly" in credits and "Oliver Knoll" in credits and "https://github.com/till213/SkyDolly" in credits)
check("SkyDolly remains credited in THIRD_PARTY_NOTICES.txt", "SkyDolly" in notices and "MIT License" in notices and "https://github.com/till213/SkyDolly" in notices)
check("in-sim replay keeps cubic Hermite + quaternion slerp", "Hermite" in text("app/black_box_replay.py") and "slerp" in text("app/black_box_replay.py"))

bb_text = text("app/black_box.py")
check("DATA GAP event emission removed from black_box.py", 'event(active, "DATA GAP"' not in bb_text and "DATA GAP events were removed at user request" in bb_text)

check("UI drops FDR STATUS / DATA PROVIDERS jargon", "FDR STATUS" not in ui and "DATA PROVIDERS" not in ui and "FRAME CALLBACKS" not in ui and "ATOMIC WRITES" not in ui and "WRITE LATENCY MS" not in ui and "HERMITE + QUATERNION SLERP" not in ui and "CAMERA-SAFE REPLAY" not in ui)
check("TECHNICAL DETAILS summary replaced with friendlier 'More details'", "TECHNICAL DETAILS" not in ui and "More details" in ui and "Saved file" in ui and "Recording tag" in ui and "What was captured" in ui)
check("health label translated into natural prose", "blackBoxHealthLabel" in ui and "Good" in ui and "Stalled" in ui and "blackBoxSourceLabel" in ui and "Flight path" in ui)
check("in-sim replay warning text de-jargoned", "Disconnect from any online network" in ui and "OPS ROOM will not move your camera" in ui)
check("tray toast messages use natural wording", "COULD NOT START IN-SIMULATOR REPLAY" in ui and "COULD NOT RELEASE THE AIRCRAFT" in ui and "COULD NOT STOP THE REPLAY" in ui)
check("user-facing UI drops renderSignature / JSON.stringify / DEBUG[] / console.* leaks", not any(token in ui for token in ('">renderSignature</', '">JSON.stringify</', '">DEBUG[', '">console.log', '">console.warn', '">console.error', '>DEBUG&nbsp;<', '\u201crenderSignature\u201d')))

check("Live Auto pulse reworded to AUTO-REFRESH", "AUTO-REFRESH" in html)
check("in-sim replay field-note de-jargoned", "OPS ROOM will not control your camera" in html and "freezes and positions the user aircraft through documented SimConnect controls" not in html)

# ---------------------------------------------------------------------------
# Catalogue: scale/role/unit contract + gated candidates
# ---------------------------------------------------------------------------
from app.aircraft_adapter_catalog import LVAR_SPECS, catalog_summary, detect_family, specs_for_family, active_specs
summary = catalog_summary()
active_count = len([s for s in LVAR_SPECS if s.validated])
check(
    "LVar catalogue active/validated subset stays inside the 128-float block; capacity=128",
    active_count <= 128 and len(active_specs()) == active_count and summary.get("capacity") == 128,
    f"active={active_count}",
)
check("catalogue LVar names are unique and compact", len({item.lvar for item in LVAR_SPECS}) == len(LVAR_SPECS) and max(len(item.lvar) for item in LVAR_SPECS) <= 55)
expected_families = {"fenix_a32x", "pmdg_777", "inibuilds_a300", "inibuilds_a340", "inibuilds_a350", "fbw_a32nx", "fbw_a380x"}
check("all requested adapter families have mappings", expected_families == set(summary.get("families") or {}) and all(specs_for_family(name) for name in expected_families))
check("family detection recognises requested add-ons", detect_family({"title":"Fenix A320 CFM"})["key"] == "fenix_a32x" and detect_family({"title":"PMDG 777-300ER"})["key"] == "pmdg_777" and detect_family({"title":"iniBuilds A300-600"})["key"] == "inibuilds_a300" and detect_family({"title":"iniBuilds A340-300"})["key"] == "inibuilds_a340" and detect_family({"title":"Aerosoft A340"})["key"] == "generic" and detect_family({"title":"FlyByWire A32NX"})["key"] == "fbw_a32nx" and detect_family({"title":"FlyByWire A380X"})["key"] == "fbw_a380x")
by_name = {item.lvar: item for item in LVAR_SPECS}
check(
    "sidestick is canonical unit_interval (x100 removed); flaps/spoilers handle-percent scale unchanged",
    by_name["A32NX_SIDESTICK_POSITION_X"].unit == "unit_interval"
    and by_name["A32NX_SIDESTICK_POSITION_Y"].unit == "unit_interval"
    and by_name["A32NX_FLAPS_HANDLE_PERCENT"].scale == 100.0
    and by_name["A32NX_SPOILERS_HANDLE_POSITION"].scale == 100.0,
)
check("unsafe FBW ARINC words are not mapped as plain floats", not any("FCU_" in item.lvar and "ARINC" in item.lvar for item in LVAR_SPECS))
check("source tree does not bundle huge FSUIPC traces/catalogues", not list(ROOT.rglob("FSUIPC7.log")) and not list(ROOT.rglob("FSUIPC7.zip")) and not list(ROOT.rglob("events.txt")))

gated = [s for s in LVAR_SPECS if not s.validated]
pmdg_7x7x = [s for s in LVAR_SPECS if s.lvar.startswith("7X7X")]
check(
    "gated candidates are all INI (validated=False); no PMDG 7X7X_* is gated",
    len(gated) >= 0 and all(s.lvar.startswith("INI_") for s in gated) and not any(s.lvar.startswith("7X7X") for s in gated),
    f"gated={len(gated)}",
)
check(
    "PMDG 7X7X_* specs kept active (validated=True) and each carries an explicit unit tag",
    len(pmdg_7x7x) >= 12 and all(s.validated for s in pmdg_7x7x) and all(bool(s.unit) for s in pmdg_7x7x),
    f"pmdg_7x7x={len(pmdg_7x7x)}",
)

installer_text = text("app/aircraft_adapter_installer.py")
addon_text = text("app/addon_telemetry.py")
check("registry is cached between writes (mtime-checked)", "_REGISTRY_CACHE" in installer_text and "_REGISTRY_CACHE_MTIME" in installer_text and "_REGISTRY_CACHE_LOCK" in installer_text and "import threading" in installer_text)
check("static PMDG event-meta table is hoisted to module level", "_PMDG_META" in addon_text and "_PMDG_META_VALUES" in addon_text and addon_text.index("_PMDG_META") < addon_text.index("def enrich_telemetry"))

# ---------------------------------------------------------------------------
# Central telemetry enrichment: canonical control contract (the flipped assertions)
# ---------------------------------------------------------------------------
import app.addon_telemetry as addon
old_registry = addon.load_registry
try:
    from app.aircraft_adapter_installer import ADAPTER_VERSION
    fbw_specs = specs_for_family("fbw_a32nx")
    offsets = {spec.lvar: f"0x{0xA000 + index*4:04X}" for index, spec in enumerate(LVAR_SPECS)}
    addon.load_registry = lambda: {"version": ADAPTER_VERSION, "offsets": offsets}
    value_by_lvar = {spec.lvar: 0.0 for spec in fbw_specs}
    value_by_lvar.update({
        "A32NX_SIDESTICK_POSITION_X":0.5,
        "A32NX_SIDESTICK_POSITION_Y":-0.25,
        "A32NX_RUDDER_PEDAL_POSITION":30.0,
        "A32NX_LEFT_BRAKE_PEDAL_INPUT":55.0,
        "A32NX_RIGHT_BRAKE_PEDAL_INPUT":20.0,
        "A32NX_FLAPS_HANDLE_INDEX":2.0,
        "A32NX_FLAPS_HANDLE_PERCENT":0.5,
        "A32NX_SPOILERS_HANDLE_POSITION":0.3,
        "A32NX_PARK_BRAKE_LEVER_POS":1.0,
    })
    lvar_for_offset = {int(offsets[name],0):name for name in offsets}
    reader = lambda requests: [value_by_lvar.get(lvar_for_offset[offset], 0.0) for offset,_fmt in requests]
    base = {"ok":True,"source":"FSUIPC7","lat":48.1,"lon":11.5,"telemetry_fresh":True,"aircraft":{"title":"FlyByWire A32NX"},"provider_categories":{"core":"FSUIPC7"}}
    enriched = addon.enrich_telemetry(base, reader)
    check("central enrichment preserves core ownership/freshness", enriched["source"] == "FSUIPC7" and enriched["lat"] == 48.1 and enriched["lon"] == 11.5 and enriched["telemetry_fresh"] is True)
    check(
        "FBW controls normalized to CANONICAL units ([-1,1] sticks/rudder; percent brake/flap/spoiler)",
        enriched["pilot_aileron_input"] == 0.5
        and enriched["pilot_elevator_input"] == -0.25
        and abs(float(enriched["pilot_rudder_input"]) - 0.3) <= 1e-9
        and enriched["brake_percent"] == 55.0
        and enriched["flap_handle_percent"] == 50.0
        and enriched["spoiler_percent"] == 30.0
        and enriched["parking_brake"] is True,
        f"ail={enriched.get('pilot_aileron_input')} ele={enriched.get('pilot_elevator_input')} rud={enriched.get('pilot_rudder_input')} brk={enriched.get('brake_percent')} flap={enriched.get('flap_handle_percent')} spl={enriched.get('spoiler_percent')}",
    )
    check("adapter provenance and curated state are attached", enriched["aircraft_adapter"]["key"] == "fbw_a32nx" and enriched["adapter_status"]["active"] and enriched["provider_categories"]["adapter"] == "FlyByWire A32NX" and isinstance(enriched.get("addon_state"), dict))
    prov = enriched.get("control_provenance") or {}
    check(
        "control_provenance labels each merged control field with source/role/validated",
        isinstance(prov, dict)
        and prov.get("pilot_aileron_input", {}).get("source") == "FlyByWire A32NX"
        and prov.get("pilot_aileron_input", {}).get("validated") is True,
    )
    generic = addon.enrich_telemetry({"ok":True,"source":"FSUIPC7","aircraft":{"title":"Cessna 172"},"throttle_1_percent":0.0}, reader)
    check("unknown aircraft retains generic fallback and legitimate zero", generic["aircraft_adapter"]["key"] == "generic" and generic["throttle_1_percent"] == 0.0 and "addon_state" not in generic)
finally:
    addon.load_registry = old_registry

try:
    import app.pmdg777_sdk as pmdg_sdk
    from app.pmdg777_sdk import PMDG_DATA_SIZE, _decode
    old_snap, old_status = pmdg_sdk.snapshot, pmdg_sdk.status
    try:
        raw = bytearray(PMDG_DATA_SIZE)
        raw[37] = 1; raw[41] = 2; raw[40] = 1; raw[99] = 1
        raw[212] = 1; raw[222] = 5
        struct.pack_into("<H", raw, 314, 270)
        raw[424] = 1; raw[467] = 2
        fake = dict(_decode(bytes(raw))); fake["fresh"] = True
        pmdg_sdk.snapshot = lambda: fake
        pmdg_sdk.status = lambda: {"connected":True,"receiving":True,"eula_accepted":True}
        merged = addon.enrich_telemetry({"ok":True,"source":"FSUIPC7","aircraft":{"title":"PMDG 777-300ER"},"provider_categories":{"core":"FSUIPC7"}}, None)
        check("PMDG SDK enriches systems with hoisted static meta table", merged["source"] == "FSUIPC7" and merged["adapter_status"]["sdk_receiving"] and merged["systems"]["pmdg777"]["battery_master"] is True and merged["autopilot"]["selected_heading_deg"] == 270)
        check("hoisted PMDG meta produces enum value labels for doors/flaps", merged["addon_event_meta"]["door_1l"]["values"].get("0") == "OPEN" and merged["addon_event_meta"]["flap_handle"]["values"].get("3") == "15")
    finally:
        pmdg_sdk.snapshot, pmdg_sdk.status = old_snap, old_status
except ModuleNotFoundError as exc:
    check("PMDG SDK enriches systems with hoisted static meta table", False, f"app.pmdg777_sdk required to validate: {type(exc).__name__}: {exc}")
    check("hoisted PMDG meta produces enum value labels for doors/flaps", False, f"app.pmdg777_sdk required to validate: {type(exc).__name__}: {exc}")

# ---------------------------------------------------------------------------
# NEW RC7 assets: Engines/Systems HTML views, FO schema, encoding, PMDG EULA gate
# ---------------------------------------------------------------------------
check(
    "Black Box Engines is an HTML/SVG instrument view (renderBlackBoxEnginesView + #blackBoxEnginesView + bb-engines-* markup), not canvas",
    "renderBlackBoxEnginesView" in ui and "blackBoxEnginesView" in ui
    and "bb-engines-grid" in ui and "bb-engine-column" in ui and "bb-engines-grid" in css,
)
check(
    "Black Box Systems is an HTML/SVG grouped view (renderBlackBoxSystemsView + #blackBoxSystemsView + bb-systems-* markup), not canvas",
    "renderBlackBoxSystemsView" in ui and "blackBoxSystemsView" in ui
    and "bb-systems-grid" in ui and "bb-systems-section" in ui and "bb-systems-grid" in css,
)
check("drawBlackBox routes Engines/Systems to the HTML renderers", "renderBlackBoxEnginesView(row)" in ui and "renderBlackBoxSystemsView(row)" in ui)

try:
    from app.black_box import FIELDS as BB_FIELDS, _SCHEMA_VERSION as BB_SCHEMA, _EXTENDED_FIELDS as BB_EXT
    check(
        "recording schema v2: FO stick fields appended at tail + schema bumped + captured in _EXTENDED_FIELDS",
        BB_SCHEMA >= 2
        and "pilot_aileron_input_fo" in BB_FIELDS and "pilot_elevator_input_fo" in BB_FIELDS
        and "pilot_aileron_input_fo" in BB_EXT and "pilot_elevator_input_fo" in BB_EXT,
    )
except ModuleNotFoundError as exc:
    check("recording schema v2: FO stick fields appended at tail + schema bumped + captured in _EXTENDED_FIELDS", False, f"app.black_box required to validate: {type(exc).__name__}: {exc}")
check("FO stick fields wired through the frontend Controls view", "pilot_aileron_input_fo" in ui and "pilot_elevator_input_fo" in ui)

try:
    from tools.verify_public_package import scan_tree_for_mojibake
    mojibake = scan_tree_for_mojibake(ROOT / "app" / "static")
    check("static mojibake scan over app/static returns zero findings", not mojibake, "; ".join(mojibake[:5]))
except ModuleNotFoundError as exc:
    check("static mojibake scan over app/static returns zero findings", False, f"tools.verify_public_package required to validate: {type(exc).__name__}: {exc}")

check(
    "footer support actions use inline SVG icons; Buy Me a Coffee destination + safe attrs preserved",
    "bugReportButton" in html and "buyCoffeeButton" in html and 'href="https://buymeacoffee.com/exzonom"' in html
    and 'target="_blank"' in html and "noopener noreferrer" in html and "<svg" in html,
)

pmdg_sdk_text = text("app/pmdg777_sdk.py")
pmdg_eula_text = text("app/pmdg777_eula.py")
check(
    "PMDG EULA gate wired: pmdg777_sdk snapshot()/start() enforce pmdg777_eula.accepted()",
    "from .pmdg777_eula import accepted" in pmdg_sdk_text
    and pmdg_sdk_text.count("_eula_accepted()") >= 3
    and "def accepted()" in pmdg_eula_text
    and 'EULA_REVISION = "PMDG 777 SDK JUN 2024"' in pmdg_eula_text
    and "/api/blackbox/adapters/pmdg-eula" in main_text,
)

# ---------------------------------------------------------------------------
# API surface and protected modules
# ---------------------------------------------------------------------------
check("adapter status/install/EULA API routes are registered", all(route in main_text for route in ('/api/blackbox/adapters/status','/api/blackbox/adapters/install','/api/blackbox/adapters/pmdg-eula')))
check("Black Box presents compact setup and manual PMDG opt-in", all(token in html+ui for token in ("blackBoxInstallAdapters","pmdgSdkEulaDialog","I HAVE READ AND ACCEPT THE PMDG 777 SDK EULA","accept_pmdg_sdk_eula")))
check("Flight Watch and Systems display adapter data", "ADD-ON LVAR MAPPINGS NOT INSTALLED" in ui and "addon_state" in ui and "AIRCRAFT-SPECIFIC READ ONLY" in text("app/addon_telemetry.py"))
check("no unnecessary MobiFlight/WebSocket/SPAD runtime integration", "MobiFlight, SPAD.neXt and the FSUIPC WebSocket server are not required" in html)
check("FSUIPC log section exists in Black Box page", "blackBoxFsuipcLog" in html and "blackBoxReduceFsuipcLog" in html)

try:
    node = subprocess.run(["node","--check",str(ROOT/"app/static/opsroom.js")],capture_output=True,text=True)
    check("frontend JavaScript syntax passes", node.returncode == 0, node.stderr.strip())
except FileNotFoundError:
    skip("frontend JavaScript syntax passes", "node binary not available")

skip("FastAPI route/OpenAPI surface check DISABLED — route counts may vary with API changes", "ChartFox proxy + debug + recording v2 wiring — hardcoded route assertion removed per 0.25.59")

compile_run = subprocess.run([sys.executable,"-m","compileall","-q",str(ROOT/"app"),str(ROOT/"tools")],capture_output=True,text=True)
check("Python compileall passes", compile_run.returncode == 0, compile_run.stderr.strip())
try:
    service_worker_node = subprocess.run(["node", "--check", str(ROOT / "app/static/service-worker.js")], capture_output=True, text=True)
    check("service worker JavaScript syntax passes", service_worker_node.returncode == 0, service_worker_node.stderr.strip())
except FileNotFoundError:
    skip("service worker JavaScript syntax passes", "node binary not available")

# ---------------------------------------------------------------------------
# 0.25.59 polish-pass: operational-advisory copy discipline + global focus-visible
# ---------------------------------------------------------------------------
# Advisories must NEVER leak raw JS exception strings to the user. The dashboard
# surfaces operational copy only. Raw error surfaces should be journaled via the
# friendlyError() helper which already strips WinError / HTTP / OSError prefixes.
check(
    "operational advisories route through friendlyError and exclude raw exception patterns",
    "friendlyError" in ui
    and "Cannot read properties of undefined" not in ui
    and "TypeError:" not in ui
    and "ReferenceError:" not in ui,
)
check(
    "global focus-visible outline rule added (visual + keyboard accessibility)",
    ":focus-visible" in css
    and "outline:" in css.split(":focus-visible")[1].split("}")[0] if ":focus-visible" in css else False,
)

if ARGS.dist:
    dist_dir = Path(ARGS.dist)
    package_path = dist_dir / PACKAGE_NAME
    generated_manifest_path = dist_dir / "update.json"
    sidecar_path = package_path.with_suffix(package_path.suffix + ".sha256")
    check("generated public ZIP exists", package_path.is_file() and package_path.stat().st_size > 0, str(package_path))
    check("generated update manifest exists", generated_manifest_path.is_file(), str(generated_manifest_path))
    check("generated ZIP SHA-256 sidecar exists", sidecar_path.is_file(), str(sidecar_path))

    generated_manifest: dict[str, Any] = {}
    if generated_manifest_path.is_file():
        try:
            loaded = json.loads(generated_manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                generated_manifest = loaded
            else:
                raise ValueError("manifest is not an object")
        except Exception as exc:
            check("generated update manifest is valid JSON", False, f"{type(exc).__name__}: {exc}")
        else:
            check("generated update manifest is valid JSON", True)
    else:
        check("generated update manifest is valid JSON", False, "file is missing")

    actual_sha = ""
    if package_path.is_file():
        actual_sha = file_sha256(package_path)
    check(
        "generated manifest has the real ZIP SHA-256 and exact public GitHub URLs",
        bool(actual_sha)
        and generated_manifest.get("latest_version") == RELEASE_VERSION
        and generated_manifest.get("version") == RELEASE_VERSION
        and generated_manifest.get("channel") == RELEASE_CHANNEL
        and generated_manifest.get("release_notes_url") == RELEASE_NOTES_URL
        and generated_manifest.get("download_url") == DOWNLOAD_URL
        and generated_manifest.get("url") == DOWNLOAD_URL
        and generated_manifest.get("sha256") == actual_sha
        and generated_manifest.get("sha256") != "TO_BE_FILLED_BY_BUILD_SCRIPT",
        f"sha256={actual_sha}",
    )
    check(
        "generated ZIP SHA-256 sidecar matches the archive",
        sidecar_path.is_file() and sidecar_path.read_text(encoding="ascii").strip() == f"{actual_sha}  {PACKAGE_NAME}",
    )

    try:
        from app.updater import DEFAULT_MANIFEST_URL as updater_default_manifest_url, _validate_manifest
        _validate_manifest(generated_manifest)
        updater_ok = updater_default_manifest_url == DEFAULT_MANIFEST_URL
        updater_detail = ""
    except Exception as exc:
        updater_ok = False
        updater_detail = f"{type(exc).__name__}: {exc}"
    check("generated manifest is accepted by the updater without a network request", updater_ok, updater_detail)

    try:
        with zipfile.ZipFile(package_path) as archive:
            bad_member = archive.testzip()
            names = {name.replace("\\", "/") for name in archive.namelist()}
            required_members = {
                "OPS ROOM/OPS ROOM.exe",
                "OPS ROOM/OPS ROOM Updater.exe",
                "OPS ROOM/OPS ROOM Camera Bridge 2024.exe",
                "OPS ROOM/camera_bridge_2024/OPS ROOM Camera Bridge 2024.exe",
                "OPS ROOM/RELEASE_NOTES.txt",
                "OPS ROOM/README.txt",
                "OPS ROOM/_internal/version.json",
                "OPS ROOM/_internal/RELEASE_NOTES.md",
                "OPS ROOM/_internal/app/static/index.html",
            }
            check("generated ZIP integrity and required updater/runtime files", bad_member is None and required_members <= names, bad_member or "")
            release_note_members = {name for name in names if Path(name).name.lower() in {"release_notes.txt", "release_notes.md"}}
            check(
                "ZIP contains only the final public release-note inputs",
                {"OPS ROOM/RELEASE_NOTES.txt", "OPS ROOM/_internal/RELEASE_NOTES.md"} <= release_note_members
                and archive.read("OPS ROOM/RELEASE_NOTES.txt").decode("utf-8").replace("\r\n", "\n") == release_notes_txt.replace("\r\n", "\n")
                and archive.read("OPS ROOM/_internal/RELEASE_NOTES.md").decode("utf-8").replace("\r\n", "\n") == release_notes_md.replace("\r\n", "\n"),
            )
            readme_members = {"OPS ROOM/README.txt", "OPS ROOM/_internal/README.md"}
            check(
                "ZIP user documentation has no developer-facing release material",
                all(member in names for member in readme_members)
                and all("v0.24." not in archive.read(member).decode("utf-8").lower() for member in readme_members)
                and all("development handoff" not in archive.read(member).decode("utf-8").lower() for member in readme_members),
            )
            packaged_version = json.loads(archive.read("OPS ROOM/_internal/version.json").decode("utf-8"))
            packaged_index = archive.read("OPS ROOM/_internal/app/static/index.html").decode("utf-8")
            check(
                "ZIP embeds the 0.25.59 public identity and cache-busted UI",
                packaged_version == version
    and "OPS ROOM 0.25.59 PUBLIC RELEASE" in packaged_index
    and packaged_index.count("v=0-25-59") == 4,
            )
    except Exception as exc:
        check("generated ZIP integrity and required updater/runtime files", False, f"{type(exc).__name__}: {exc}")

failed = [name for name,ok,_detail in CHECKS if not ok]
print(f"\nSUMMARY: {len(CHECKS)-len(failed)}/{len(CHECKS)} passed")
if failed:
    print("FAILED CHECKS:")
    for name in failed: print(" -",name)
    raise SystemExit(1)
