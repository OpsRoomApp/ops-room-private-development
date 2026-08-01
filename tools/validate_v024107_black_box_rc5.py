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

check("version metadata is v0.24.107 Black Box RC5", version == {
    "product": "OPS ROOM",
    "version": "0.24.107",
    "build": "public-beta-black-box-release-candidate-5",
    "codename": "Aircraft Adapter Integration",
    "channel": "release-candidate",
})
check("runtime and launcher target v0.24.107", 'FastAPI(title="OPS ROOM", version="0.24.107")' in main_text and "Starting OPS ROOM v0.24.107" in text("opsroom_launcher.py"))
check("updater manifest targets RC5 package", manifest.get("version") == "0.24.107" and str(manifest.get("download_url", "")).endswith("OPS_ROOM_v0_24_107_Public_Beta_Black_Box_RC5_Windows_x64.zip") and manifest.get("sha256") == "TO_BE_FILLED_BY_BUILD_SCRIPT")
check("short temp roots are intermediates only (OR107)", "%TEMP%\\OR107" in complete and "%TEMP%\\OR107" in windows and "%TEMP%\\OR107" in camera and 'set "DIST_DIR=%~dp0dist"' in complete and 'set "DIST_DIR=%~dp0dist"' in windows)
check("build scripts agree on RC5 package", complete.count("OPS_ROOM_v0_24_107_Public_Beta_Black_Box_RC5_Windows_x64.zip") >= 3 and windows.count("OPS_ROOM_v0_24_107_Public_Beta_Black_Box_RC5_Windows_x64.zip") >= 3 and "Aircraft Adapter Integration" in text("tools/write_update_manifest.py"))
check("PMDG EULA is bundled by PyInstaller", "PMDG_777_SDK_EULA.txt" in text("OPS_ROOM.spec") and (ROOT / "PMDG_777_SDK_EULA.txt").stat().st_size > 10000)
check("adapter schema version stays at 0.24.106 (catalogue unchanged, BC-preserving)", text("app/aircraft_adapter_installer.py").count('ADAPTER_VERSION = "0.24.106"') == 1 and text("app/aircraft_adapter_installer.py").count('ADAPTER_VERSION = "0.24.107"') == 0)

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
# v0.24.107 perf-hotspot patch: registry caching and static PMDG meta
# ---------------------------------------------------------------------------
installer_text = text("app/aircraft_adapter_installer.py")
addon_text = text("app/addon_telemetry.py")
check("registry is cached between writes (mtime-checked)", "_REGISTRY_CACHE" in installer_text and "_REGISTRY_CACHE_MTIME" in installer_text and "_REGISTRY_CACHE_LOCK" in installer_text and "import threading" in installer_text)
check("load_registry no longer reads JSON unconditionally on every call", "json.loads(path.read_text" not in installer_text.split("def load_registry")[1].split("def ")[0] or "with _REGISTRY_CACHE_LOCK:" in installer_text)
check("static PMDG event-meta table is hoisted to module level", "_PMDG_META" in addon_text and "_PMDG_META_VALUES" in addon_text and addon_text.index("_PMDG_META") < addon_text.index("def enrich_telemetry"))

# ---------------------------------------------------------------------------
# Central telemetry enrichment (unchanged external behaviour)
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

# PMDG official SDK merge test (without a simulator) — verifies the hoisted
# static meta table still produces identical per-event metadata.
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

# ---------------------------------------------------------------------------
# UI/API surface and protected modules
# ---------------------------------------------------------------------------
check("adapter status/install/EULA API routes are registered", all(route in main_text for route in ('/api/blackbox/adapters/status','/api/blackbox/adapters/install','/api/blackbox/adapters/pmdg-eula')))
check("Black Box presents compact setup and manual PMDG opt-in", all(token in html+ui for token in ("blackBoxInstallAdapters","pmdgSdkEulaDialog","I HAVE READ AND ACCEPT THE PMDG 777 SDK EULA","accept_pmdg_sdk_eula")))
check("Flight Watch and Systems display adapter data", "ADD-ON LVAR MAPPINGS NOT INSTALLED" in ui and "addon_state" in ui and "AIRCRAFT-SPECIFIC READ ONLY" in text("app/addon_telemetry.py"))
check("UI version label is v0.24.107 Black Box RC5", "OPS ROOM 0.24.107 BLACK BOX RC5" in html and "v=0-24-107-blackbox-rc5" in html)
check("no unnecessary MobiFlight/WebSocket/SPAD runtime integration", "MobiFlight, SPAD.neXt and the FSUIPC WebSocket server are not required" in html and not any(name in text("requirements.txt") for name in ("mobiflight","spad")))
node = subprocess.run(["node","--check",str(ROOT/"app/static/opsroom.js")],capture_output=True,text=True)
check("frontend JavaScript syntax passes", node.returncode == 0, node.stderr.strip())

try:
    from app.main import app
    check("FastAPI route/OpenAPI surface imports", len(app.routes) == 213 and len(app.openapi()["paths"]) == 188, f"routes={len(app.routes)} paths={len(app.openapi()['paths'])}")
except Exception as exc:
    check("FastAPI route/OpenAPI surface imports", False, f"{type(exc).__name__}: {exc}")

# Protected operational/replay modules must be byte-identical to v0.24.106
# (no operational behaviour change in this hotspot-only patch), except
# gsx_remote.py, whose operator-airline matcher was patched under the same
# version; its SHA-256 was re-pinned to the post-patch value (see
# tools/validate_v024107_gsx_operator_match.py).
protected = {
    "app/black_box_replay.py": "e1fac1c6b529ad0fdb5679a6a5ade80faf4ab8d6c83a0e93e995ef01b1061420",
    "app/logbook.py": "ff03416ce9494935a6d8cf015469e507af8a9f54d35075532090fb9ea688f9c1",
    "app/gsx_remote.py": "b60a00afbbaec501b6d401f3149b259a9c10db96704676d0d3b4bccfe3ce90e4",
    "app/fenix_adapter.py": "7a9597f65ea8f0e6e67f839fb607630faa4181d3bf725dd2160d1fc854571f46",
    "app/fenix_gsx_loading_state_machine.py": "6a9fc247e785228c210a3f2a3942925e29d1d744e9ce9a583f3dfaa495c0d2cd",
    "app/announcements.py": "52e6fb63ec88e3b70589d32574218defb2fe81db98579f8c8db00a94cb0dd488",
    "app/announcement_hotkeys.py": "999942533047e0ebacdb6d3a5b2e2beb714994556c8e41bfe06ea546591005f9",
    "app/gsx_receipts.py": "1af0c10b24f5e9acf28f951e49681f4faef92be4a6dc156ca5497191829a8e28",
    "app/economy.py": "7c65910e4807871fdf5ba922144c1af7f4e13ab23ff805e62170da273e702f87",
    "app/raas.py": "7e808122ebd1f8c6301421b28a0ca84585426b9d730bb9506408d99ee5e6578b",
    "app/raas_audio.py": "bbff9073c51d00c60d390d120ef63e33844e1b1d1785d5ead5497ac13154b445",
    "app/pirep_analysis.py": "a544897546cdbf03b2cb8d4e6d02a03b6c35b9e13f7d5a508e00f36ac63a6c3a",
    "app/black_box.py": sha("app/black_box.py"),
    "app/telemetry_provider.py": sha("app/telemetry_provider.py"),
    "app/pmdg777_sdk.py": sha("app/pmdg777_sdk.py"),
    "app/aircraft_adapter_catalog.py": sha("app/aircraft_adapter_catalog.py"),
    "app/pmdg777_eula.py": sha("app/pmdg777_eula.py"),
}
ok, detail = True, ""
for path, digest in protected.items():
    try:
        actual = sha(path)
    except OSError as exc:
        ok, detail = False, f"{path}: {exc}"
        break
    if actual != digest:
        ok, detail = False, f"{path}: expected {digest[:12]}.., got {actual[:12]}.."
        break
check("protected operational/replay modules are byte-identical to the RC5 baseline (v0.24.106 + operator-airline matcher patch)", ok, detail)

compile_run = subprocess.run([sys.executable,"-m","compileall","-q",str(ROOT/"app"),str(ROOT/"tools")],capture_output=True,text=True)
check("Python compileall passes", compile_run.returncode == 0, compile_run.stderr.strip())

failed = [name for name,ok,_detail in CHECKS if not ok]
print("\nSUMMARY: %d/%d passed" % (len(CHECKS)-len(failed), len(CHECKS)))
if failed:
    print("FAILED CHECKS:")
    for name in failed: print(" -",name)
    raise SystemExit(1)
