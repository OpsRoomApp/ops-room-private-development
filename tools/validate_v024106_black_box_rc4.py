from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, condition: Any, detail: str = "") -> None:
    ok = bool(condition)
    CHECKS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Release/build metadata
# ---------------------------------------------------------------------------
version = json.loads(text("version.json"))
manifest = json.loads(text("update.json"))
main_text = text("app/main.py")
ui = text("app/static/opsroom.js")
html = text("app/static/index.html")
css = text("app/static/opsroom.css")
complete = text("BUILD OPS ROOM COMPLETE.bat")
windows = text("BUILD WINDOWS APP ONLY.bat")
camera = text("BUILD CAMERA BRIDGE 2024.bat")

check("version metadata is v0.24.106 Black Box RC4", version == {
    "product": "OPS ROOM",
    "version": "0.24.106",
    "build": "public-beta-black-box-release-candidate-4",
    "codename": "Aircraft Adapter Integration",
    "channel": "release-candidate",
})
check("runtime and launcher target v0.24.106", 'FastAPI(title="OPS ROOM", version="0.24.106")' in main_text and "Starting OPS ROOM v0.24.106" in text("opsroom_launcher.py"))
check("updater manifest targets RC4 package", manifest.get("version") == "0.24.106" and str(manifest.get("download_url", "")).endswith("OPS_ROOM_v0_24_106_Public_Beta_Black_Box_RC4_Windows_x64.zip") and manifest.get("sha256") == "TO_BE_FILLED_BY_BUILD_SCRIPT")
check("short temp roots are intermediates only", "%TEMP%\\OR106" in complete and "%TEMP%\\OR106" in windows and "%TEMP%\\OR106" in camera and 'set "DIST_DIR=%~dp0dist"' in complete and 'set "DIST_DIR=%~dp0dist"' in windows)
check("build scripts agree on RC4 package", complete.count("OPS_ROOM_v0_24_106_Public_Beta_Black_Box_RC4_Windows_x64.zip") >= 3 and windows.count("OPS_ROOM_v0_24_106_Public_Beta_Black_Box_RC4_Windows_x64.zip") >= 3 and "Aircraft Adapter Integration" in text("tools/write_update_manifest.py"))
check("PMDG EULA is bundled by PyInstaller", "PMDG_777_SDK_EULA.txt" in text("OPS_ROOM.spec") and (ROOT / "PMDG_777_SDK_EULA.txt").stat().st_size > 10000)

# ---------------------------------------------------------------------------
# Catalogue and detection
# ---------------------------------------------------------------------------
from app.aircraft_adapter_catalog import LVAR_SPECS, catalog_summary, detect_family, specs_for_family
summary = catalog_summary()
check("compact LVar catalogue stays inside 128-float block", len(LVAR_SPECS) == 114 and len(LVAR_SPECS) <= 128 and summary.get("capacity") == 128)
check("catalogue LVar names are unique and compact", len({item.lvar for item in LVAR_SPECS}) == len(LVAR_SPECS) and max(len(item.lvar) for item in LVAR_SPECS) <= 55)
expected_families = {"fenix_a32x", "pmdg_777", "inibuilds_a300", "inibuilds_a340", "inibuilds_a350", "fbw_a32nx", "fbw_a380x"}
check("all requested adapter families have mappings", expected_families == set(summary.get("families") or {}) and all(specs_for_family(name) for name in expected_families))
check("family detection recognises requested add-ons", detect_family({"title":"Fenix A320 CFM"})["key"] == "fenix_a32x" and detect_family({"title":"PMDG 777-300ER"})["key"] == "pmdg_777" and detect_family({"title":"iniBuilds A300-600"})["key"] == "inibuilds_a300" and detect_family({"title":"iniBuilds A340-300"})["key"] == "inibuilds_a340" and detect_family({"title":"Aerosoft A340"})["key"] == "generic" and detect_family({"title":"FlyByWire A32NX"})["key"] == "fbw_a32nx" and detect_family({"title":"FlyByWire A380X"})["key"] == "fbw_a380x")
by_name = {item.lvar: item for item in LVAR_SPECS}
check("FBW documented fractional controls use correct scale", by_name["A32NX_FLAPS_HANDLE_PERCENT"].scale == 100.0 and by_name["A32NX_SPOILERS_HANDLE_POSITION"].scale == 100.0 and by_name["A32NX_SIDESTICK_POSITION_X"].scale == 100.0)
check("unsafe FBW ARINC words are not mapped as plain floats", not any("FCU_" in item.lvar and "ARINC" in item.lvar for item in LVAR_SPECS))
check("source tree does not bundle huge FSUIPC traces/catalogues", not list(ROOT.rglob("FSUIPC7.log")) and not list(ROOT.rglob("FSUIPC7.zip")) and not list(ROOT.rglob("events.txt")))

# ---------------------------------------------------------------------------
# Safe FSUIPC and PMDG installer
# ---------------------------------------------------------------------------
import app.aircraft_adapter_installer as installer
import app.pmdg777_eula as eula

with tempfile.TemporaryDirectory(prefix="opsroom-v106-installer-") as temp_name:
    temp = Path(temp_name)
    fsdir = temp / "FSUIPC7"; fsdir.mkdir()
    exe = fsdir / "FSUIPC7.exe"; exe.write_bytes(b"fake")
    ini = fsdir / "FSUIPC7.ini"
    ini.write_text("[General]\nUseProfiles=Files\n\n[LvarOffsets]\n0=L:USER_KEEP=UB0xA000\n\n[LvarOffsets.Fenix]\n5=L:PROFILE_KEEP=F0xA004\n", encoding="utf-8")
    profiles = fsdir / "Profiles"; profiles.mkdir()
    profile = profiles / "PMDG777.ini"
    profile.write_text("[Profile]\n1=PMDG 777\n\n[LvarOffsets]\n2=L:SEPARATE_KEEP=UW0xA008\n", encoding="utf-8")
    appdata = temp / "AppData"; appdata.mkdir()
    old_locate = installer.locate_fsuipc
    old_appdir_installer = installer.app_data_dir
    old_appdir_eula = eula.app_data_dir
    installer.locate_fsuipc = lambda: exe
    installer.app_data_dir = lambda: appdata
    eula.app_data_dir = lambda: appdata
    try:
        first = installer.install_lvar_offsets()
        main_after = ini.read_text(encoding="utf-8")
        profile_after = profile.read_text(encoding="utf-8")
        registry = json.loads((appdata / installer.REGISTRY_NAME).read_text(encoding="utf-8"))
        offsets = [int(value, 0) for value in registry["offsets"].values()]
        check("FSUIPC installer preserves user mappings", "USER_KEEP=UB0xA000" in main_after and "PROFILE_KEEP=F0xA004" in main_after and "SEPARATE_KEEP=UW0xA008" in profile_after)
        check("FSUIPC installer writes all compact mappings to general/profile scopes", first.get("ok") and first.get("mapping_count") == len(LVAR_SPECS) and main_after.count(installer.BEGIN_MARKER) == 2 and profile_after.count(installer.BEGIN_MARKER) == 1)
        check("FSUIPC installer allocates unique aligned free offsets", len(offsets) == len(set(offsets)) == len(LVAR_SPECS) and all(0xA000 <= value <= 0xA1FC and value % 4 == 0 for value in offsets) and not ({0xA000,0xA004,0xA008} & set(offsets)))
        check("FSUIPC installer creates backups and compact registry", bool(first.get("backups")) and all(Path(path).is_file() for path in first.get("backups") or []) and (appdata / installer.REGISTRY_NAME).stat().st_size < 50000)
        second = installer.install_lvar_offsets()
        check("FSUIPC installer is idempotent", second.get("ok") and second.get("changed") is False and ini.read_text(encoding="utf-8") == main_after and profile.read_text(encoding="utf-8") == profile_after)

        pmdg = temp / "777_Options.ini"
        pmdg.write_text("[ADIRU]\nLastPosValid=0\n\n[SDK]\nEnableCDUBroadcast.0=1\nEnableCDUBroadcast.1=1\n", encoding="utf-8")
        old_paths = installer.pmdg_options_paths
        installer.pmdg_options_paths = lambda: [pmdg]
        try:
            denied = installer.install_pmdg777_broadcast(eula_acceptance=False)
            check("PMDG installer requires manual SDK-EULA acceptance", denied.get("eula_required") is True and not eula.accepted())
            configured = installer.install_pmdg777_broadcast(eula_acceptance=True)
            pmdg_after = pmdg.read_text(encoding="utf-8")
            check("PMDG installer accepts EULA and writes only data broadcast", configured.get("ok") and eula.accepted() and "EnableDataBroadcast=1" in pmdg_after and "EnableCDUBroadcast.0=1" in pmdg_after and "EnableCDUBroadcast.1=1" in pmdg_after and "LastPosValid=0" in pmdg_after)
            check("PMDG installer backs up and is idempotent", bool(configured.get("backups")) and all(Path(path).is_file() for path in configured.get("backups") or []) and not installer.install_pmdg777_broadcast().get("changed_paths"))
        finally:
            installer.pmdg_options_paths = old_paths
    finally:
        installer.locate_fsuipc = old_locate
        installer.app_data_dir = old_appdir_installer
        eula.app_data_dir = old_appdir_eula

# ---------------------------------------------------------------------------
# Official PMDG data block decoder
# ---------------------------------------------------------------------------
from app.pmdg777_sdk import PMDG_DATA_SIZE, _decode
raw = bytearray(PMDG_DATA_SIZE)
raw[37] = 1; raw[41] = 2; raw[40] = 1; raw[99] = 1
raw[109:112] = bytes([1,1,1]); raw[112] = 1; raw[118] = 1; raw[119] = 1
raw[212] = 1; raw[222] = 5
struct.pack_into("<f", raw, 308, 250.0); struct.pack_into("<H", raw, 314, 270); struct.pack_into("<H", raw, 316, 12000); struct.pack_into("<h", raw, 318, -900)
raw[325:327] = bytes([1,1]); raw[338] = 1; raw[342] = 1; raw[356:358] = bytes([1,0]); raw[358] = 1; raw[359] = 1; raw[360] = 1
raw[389] = 1; raw[420] = 25; raw[421] = 2; raw[422:424] = bytes([1,1]); raw[424] = 1
raw[467:483] = bytes([2,1,1,1,1,1,1,1,1,1,0,4,1,1,1,1]); raw[483] = 1
raw[484:486] = bytes([1,0]); struct.pack_into("<f", raw, 488, 37.5); struct.pack_into("<f", raw, 492, 38.0); raw[512] = 1
raw[542] = 6; raw[546] = 5; raw[547:550] = bytes([145,150,155]); raw[556] = 30; raw[557] = 142; struct.pack_into("<H", raw, 558, 38000)
struct.pack_into("<f", raw, 568, 123.5); struct.pack_into("<f", raw, 572, 456.25); raw[576:585] = b"EWG7278\0\0"; raw[586] = 1; raw[588:598] = bytes([1,1,1,1,0,0,0,0,0,0])
decoded = _decode(bytes(raw))
check("PMDG decoder uses official 684-byte layout", PMDG_DATA_SIZE == 684 and decoded["aircraft_model"] == "777-300ER" and decoded["systems"]["battery_master"] is True and decoded["systems"]["apu_running"] is True)
check("PMDG decoder exposes controls/MCP/doors/FMC", decoded["controls"]["flap_index"] == 2 and decoded["controls"]["spoilers_armed"] is True and decoded["autopilot"]["selected_altitude_ft"] == 12000 and decoded["autopilot"]["modes"] == ["LNAV", "VNAV"] and decoded["systems"]["doors"][0]["label"] == "CLOSED/ARMED" and decoded["flight_management"]["flight_number"] == "EWG7278")

# ---------------------------------------------------------------------------
# Central telemetry enrichment
# ---------------------------------------------------------------------------
import app.addon_telemetry as addon
old_registry = addon.load_registry
try:
    fbw_specs = specs_for_family("fbw_a32nx")
    offsets = {spec.lvar: f"0x{0xA000 + index*4:04X}" for index, spec in enumerate(LVAR_SPECS)}
    addon.load_registry = lambda: {"version":"0.24.106", "offsets":offsets}
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
    check("FBW controls are normalized into Flight Watch/Black Box fields", enriched["pilot_aileron_input"] == 50.0 and enriched["pilot_elevator_input"] == -25.0 and enriched["pilot_rudder_input"] == 30.0 and enriched["brake_percent"] == 55.0 and enriched["flap_handle_percent"] == 50.0 and enriched["spoiler_percent"] == 30.0 and enriched["parking_brake"] is True)
    check("adapter provenance and curated state are attached", enriched["aircraft_adapter"]["key"] == "fbw_a32nx" and enriched["adapter_status"]["active"] and enriched["provider_categories"]["adapter"] == "FlyByWire A32NX" and isinstance(enriched.get("addon_state"), dict))
    generic = addon.enrich_telemetry({"ok":True,"source":"FSUIPC7","aircraft":{"title":"Cessna 172"},"throttle_1_percent":0.0}, reader)
    check("unknown aircraft retains generic fallback and legitimate zero", generic["aircraft_adapter"]["key"] == "generic" and generic["throttle_1_percent"] == 0.0 and "addon_state" not in generic)
finally:
    addon.load_registry = old_registry

# PMDG official SDK merge test (without a simulator).
import app.pmdg777_sdk as pmdg_sdk
old_snap, old_status = pmdg_sdk.snapshot, pmdg_sdk.status
try:
    fake = dict(decoded); fake["fresh"] = True
    pmdg_sdk.snapshot = lambda: fake
    pmdg_sdk.status = lambda: {"connected":True,"receiving":True,"eula_accepted":True}
    merged = addon.enrich_telemetry({"ok":True,"source":"FSUIPC7","aircraft":{"title":"PMDG 777-300ER"},"provider_categories":{"core":"FSUIPC7"}}, None)
    check("PMDG official SDK enriches systems without replacing core source", merged["source"] == "FSUIPC7" and merged["adapter_status"]["sdk_receiving"] and merged["systems"]["pmdg777"]["battery_master"] is True and merged["autopilot"]["selected_heading_deg"] == 270)
finally:
    pmdg_sdk.snapshot, pmdg_sdk.status = old_snap, old_status

# ---------------------------------------------------------------------------
# Black Box semantic event capture and schema compatibility
# ---------------------------------------------------------------------------
import app.black_box as bb
check("FDR schema contains curated add-on state without duplicates", "addon_state" in bb.FIELDS and len(bb.FIELDS) == len(set(bb.FIELDS)))
with tempfile.TemporaryDirectory(prefix="opsroom-v106-events-") as temp_name:
    db = Path(temp_name) / "events.opsbb.part"
    bb._init_recording(db, {"recording_id":"test"})
    active = {"path":db,"started_mono":time.monotonic(),"live_events":[],"addon_event_meta":{
        "ap1_button":{"label":"AP1 BUTTON","kind":"pulse","values":{}},
        "battery_1":{"label":"BATTERY 1","kind":"bool","values":{}},
        "engine_mode":{"label":"ENGINE MODE","kind":"enum","values":{"0":"CRANK","1":"NORM","2":"IGN/START"}},
        "selected_altitude":{"label":"FCU ALTITUDE","kind":"number","values":{}},
    }}
    first_row = {"phase":"PREFLIGHT","source":"FSUIPC7","elapsed":0.0,"addon_state":{"ap1_button":2,"battery_1":False,"engine_mode":1,"selected_altitude":10000}}
    bb._detect_events_locked(active, first_row)
    check("initial add-on snapshot is suppressed", not active["live_events"])
    second_row = {"phase":"PREFLIGHT","source":"FSUIPC7","elapsed":0.1,"addon_state":{"ap1_button":1,"battery_1":True,"engine_mode":2,"selected_altitude":10020}}
    bb._detect_events_locked(active, second_row)
    kinds = [(item["kind"],item["detail"]) for item in active["live_events"]]
    check("pulse/bool/enum events are semantic", ("AP1 BUTTON","PRESSED") in kinds and ("BATTERY 1","ON") in kinds and ("ENGINE MODE","IGN/START") in kinds)
    check("numeric event thresholds suppress noise", not any(kind == "FCU ALTITUDE" for kind,_detail in kinds))
    third_row = {"phase":"PREFLIGHT","source":"FSUIPC7","elapsed":0.2,"addon_state":{"ap1_button":2,"battery_1":True,"engine_mode":2,"selected_altitude":12000}}
    bb._detect_events_locked(active, third_row)
    check("meaningful selected-target changes become events", any(item["kind"] == "FCU ALTITUDE" and item["detail"] == "12000" for item in active["live_events"]))
    check("add-on state participates in duplicate fingerprint", bb._fingerprint(first_row) != bb._fingerprint(second_row))
    with sqlite3.connect(db) as conn:
        stored = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    check("semantic events are persisted in existing .opsbb schema", stored == len(active["live_events"]) and stored >= 4)

# ---------------------------------------------------------------------------
# UI/API surface and protected modules
# ---------------------------------------------------------------------------
check("adapter status/install/EULA API routes are registered", all(route in main_text for route in ('/api/blackbox/adapters/status','/api/blackbox/adapters/install','/api/blackbox/adapters/pmdg-eula')))
check("Black Box presents compact setup and manual PMDG opt-in", all(token in html+ui for token in ("blackBoxInstallAdapters","pmdgSdkEulaDialog","I HAVE READ AND ACCEPT THE PMDG 777 SDK EULA","accept_pmdg_sdk_eula")))
check("Flight Watch and Systems display adapter data", "ADD-ON LVAR MAPPINGS NOT INSTALLED" in ui and "addon_state" in ui and "AIRCRAFT-SPECIFIC READ ONLY" in text("app/addon_telemetry.py"))
check("no unnecessary MobiFlight/WebSocket/SPAD runtime integration", "MobiFlight, SPAD.neXt and the FSUIPC WebSocket server are not required" in html and not any(name in text("requirements.txt") for name in ("mobiflight","spad")))
node = subprocess.run(["node","--check",str(ROOT/"app/static/opsroom.js")],capture_output=True,text=True)
check("frontend JavaScript syntax passes", node.returncode == 0, node.stderr.strip())

try:
    from app.main import app
    check("FastAPI route/OpenAPI surface imports", len(app.routes) == 213 and len(app.openapi()["paths"]) == 188, f"routes={len(app.routes)} paths={len(app.openapi()['paths'])}")
except Exception as exc:
    check("FastAPI route/OpenAPI surface imports", False, f"{type(exc).__name__}: {exc}")

protected = {
    "app/black_box_replay.py": "e1fac1c6b529ad0fdb5679a6a5ade80faf4ab8d6c83a0e93e995ef01b1061420",
    "app/logbook.py": "ff03416ce9494935a6d8cf015469e507af8a9f54d35075532090fb9ea688f9c1",
    "app/gsx_remote.py": "0bb9c659c23b049b5c30839cc3760de3762e9bbb5d0f3fe1e3922bf2c7f93e8a",
    "app/fenix_adapter.py": "7a9597f65ea8f0e6e67f839fb607630faa4181d3bf725dd2160d1fc854571f46",
    "app/fenix_gsx_loading_state_machine.py": "6a9fc247e785228c210a3f2a3942925e29d1d744e9ce9a583f3dfaa495c0d2cd",
    "app/announcements.py": "52e6fb63ec88e3b70589d32574218defb2fe81db98579f8c8db00a94cb0dd488",
    "app/announcement_hotkeys.py": "999942533047e0ebacdb6d3a5b2e2beb714994556c8e41bfe06ea546591005f9",
    "app/gsx_receipts.py": "1af0c10b24f5e9acf28f951e49681f4faef92be4a6dc156ca5497191829a8e28",
    "app/economy.py": "7c65910e4807871fdf5ba922144c1af7f4e13ab23ff805e62170da273e702f87",
    "app/raas.py": "7e808122ebd1f8c6301421b28a0ca84585426b9d730bb9506408d99ee5e6578b",
    "app/raas_audio.py": "bbff9073c51d00c60d390d120ef63e33844e1b1d1785d5ead5497ac13154b445",
    "app/pirep_analysis.py": "a544897546cdbf03b2cb8d4e6d02a03b6c35b9e13f7d5a508e00f36ac63a6c3a",
}
check("protected operational/replay modules remain byte-identical", all(sha(path) == digest for path,digest in protected.items()))

compile_run = subprocess.run([sys.executable,"-m","compileall","-q",str(ROOT/"app"),str(ROOT/"tools")],capture_output=True,text=True)
check("Python compileall passes", compile_run.returncode == 0, compile_run.stderr.strip())

failed = [name for name,ok,_detail in CHECKS if not ok]
print("\nSUMMARY: %d/%d passed" % (len(CHECKS)-len(failed), len(CHECKS)))
if failed:
    print("FAILED CHECKS:")
    for name in failed: print(" -",name)
    raise SystemExit(1)
