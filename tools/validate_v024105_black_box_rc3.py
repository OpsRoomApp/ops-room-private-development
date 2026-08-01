from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
import time
import types
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
checks: list[tuple[str, bool]] = []


def check(name: str, value: object) -> None:
    ok = bool(value)
    checks.append((name, ok))
    print(("PASS" if ok else "FAIL") + ": " + name)


def text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


version = json.loads(text("version.json"))
manifest = json.loads(text("update.json"))
ui = text("app/static/opsroom.js")
css = text("app/static/opsroom.css")
black = text("app/black_box.py")
sim = text("app/simconnect_position.py")
telemetry = text("app/telemetry_provider.py")
aviation = text("app/aviation_data.py")
main = text("app/main.py")
complete = text("BUILD OPS ROOM COMPLETE.bat")
windows = text("BUILD WINDOWS APP ONLY.bat")
camera = text("BUILD CAMERA BRIDGE 2024.bat")

check(
    "version is v0.24.105 Black Box RC3",
    version
    == {
        "product": "OPS ROOM",
        "version": "0.24.105",
        "build": "public-beta-black-box-release-candidate-3",
        "codename": "Flight Data Recorder Release Candidate 3",
        "channel": "release-candidate",
    },
)
check(
    "runtime and launcher target v0.24.105",
    'FastAPI(title="OPS ROOM", version="0.24.105")' in main
    and "Starting OPS ROOM v0.24.105" in text("opsroom_launcher.py"),
)
check(
    "bundled updater manifest targets Black Box RC3",
    manifest.get("version") == "0.24.105"
    and str(manifest.get("download_url", "")).endswith(
        "OPS_ROOM_v0_24_105_Public_Beta_Black_Box_RC3_Windows_x64.zip"
    )
    and manifest.get("sha256") == "TO_BE_FILLED_BY_BUILD_SCRIPT",
)
check(
    "final dist remains beside build scripts",
    'set "DIST_DIR=%~dp0dist"' in complete and 'set "DIST_DIR=%~dp0dist"' in windows,
)
check(
    "only intermediates use short OR105 root",
    "%TEMP%\\OR105" in complete
    and "%TEMP%\\OR105" in windows
    and "%TEMP%\\OR105" in camera
    and "%OPSROOM_BUILD_ROOT%\\camera_bridge" in camera,
)
check(
    "build scripts and manifest writer agree on Black Box RC3 package",
    complete.count("OPS_ROOM_v0_24_105_Public_Beta_Black_Box_RC3_Windows_x64.zip") >= 3
    and windows.count("OPS_ROOM_v0_24_105_Public_Beta_Black_Box_RC3_Windows_x64.zip") >= 3
    and "Flight Data Recorder Release Candidate 3" in text("tools/write_update_manifest.py"),
)

# Map release-promotion checks.
check(
    "complete ordered taxi-path data replaces hard truncation",
    "from taxi_path" in aviation
    and "order by taxi_path_id" in aviation
    and "limit 12000" not in aviation.lower()
    and "_merge_taxi_segments" in aviation,
)
check(
    "runway payload carries individual end identifiers",
    all(token in aviation for token in ('"primary_name"', '"secondary_name"')),
)
check(
    "runways have width-aware surfaces and individual threshold markings",
    all(
        token in ui
        for token in (
            "runwayPolygonFromLine",
            "kind:'runway-surface'",
            "kind:'runway-centerline'",
            "kind:'runway-threshold'",
            "runwayThresholdStripes",
            "kind:'runway-end-label'",
        )
    ),
)
check(
    "taxiway presentation is reduced from the earlier heavy overlay",
    "Math.min(major?6.2:4.1" in ui
    and "width:px+2.4" in ui
    and "width:Math.max(.65,px*.13)" in ui,
)

# FDR schema and documented provider surfaces.
try:
    import app.black_box as bb

    check("FDR field schema contains no duplicates", len(bb.FIELDS) == len(set(bb.FIELDS)) and len(bb.FIELDS) >= 90)
except Exception as exc:
    print("BLACK BOX IMPORT ERROR:", exc)
    bb = None
    check("FDR field schema contains no duplicates", False)

check(
    "standard SimConnect control and indexed four-engine variables are requested",
    all(
        token in sim
        for token in (
            "YOKE_X_POSITION",
            "YOKE_Y_POSITION",
            "RUDDER_PEDAL_POSITION",
            "AILERON_LEFT_DEFLECTION_PCT",
            "ELEVATOR_DEFLECTION_PCT",
            "RUDDER_DEFLECTION_PCT",
            "GENERAL_ENG_THROTTLE_LEVER_POSITION:4",
            "TURB_ENG_N1:4",
            "TURB_ENG_N2:4",
            "GENERAL_ENG_EXHAUST_GAS_TEMPERATURE:4",
            "TURB_ENG_FUEL_FLOW_PPH:4",
        )
    ),
)
check(
    "SimConnect units are normalized by their documented unit type",
    all(
        token in sim
        for token in (
            "def position_16k",
            "def position_32k_percent",
            "def sdk_percent",
            "def percent_over_100",
            "one position step",
        )
    ),
)
check(
    "documented FSUIPC four-engine and post-calibration offsets are present",
    all(
        token in telemetry
        for token in (
            "0x088C",
            "0x0924",
            "0x09BC",
            "0x0A54",
            "0x0898",
            "0x0930",
            "0x09C8",
            "0x0A60",
            "0x08BE",
            "0x0956",
            "0x09EE",
            "0x0A86",
            "0x08A0",
            "0x0938",
            "0x09D0",
            "0x0A68",
            "0x0AEC",
            "0x3328",
            "0x332A",
            "0x332C",
            "0x3330",
            "0x3332",
            "0x3334",
            "0x3336",
            "0x3412",
            "0x3414",
            "0x3416",
            "0x3418",
        )
    ),
)
check(
    "provider category provenance and capability metadata are recorded",
    all(token in black for token in ("provider_categories", "capability_manifest", "aircraft_adapter", "_CAPABILITY_GROUPS"))
    and "provider_categories" in ui,
)
check(
    "Black Box workspace keeps live horizontal FDR-first presentation",
    "blackbox-layout" in css
    and "blackbox-replay-panel" in css
    and "function bbPanelGrid" in ui
    and "drawBlackBoxControls" in ui
    and "drawBlackBoxEngines" in ui,
)

# SimConnect unit-normalization test without a simulator connection.
try:
    import app.simconnect_position as sp

    values: dict[str, object] = {
        "PLANE_LATITUDE": 48.0,
        "PLANE_LONGITUDE": 11.0,
        "PLANE_ALTITUDE": 5000.0,
        "INDICATED_ALTITUDE": 5000.0,
        "PRESSURE_ALTITUDE": 1524.0,
        "AIRSPEED_INDICATED": 170.0,
        "AIRSPEED_TRUE": 180.0,
        "AIRSPEED_MACH": 0.3,
        "GROUND_VELOCITY": 175.0,
        "PLANE_HEADING_DEGREES_MAGNETIC": 81.0,
        "GPS_GROUND_MAGNETIC_TRACK": 82.0,
        "VERTICAL_SPEED": 700.0,
        "PLANE_ALT_ABOVE_GROUND": 4500.0,
        "RADIO_HEIGHT": 4500.0,
        "SIM_ON_GROUND": 0.0,
        "PLANE_PITCH_DEGREES": 3.0,
        "PLANE_BANK_DEGREES": 1.0,
        "G_FORCE": 1.01,
        "FLAPS_HANDLE_INDEX": 1.0,
        "TRAILING_EDGE_FLAPS_LEFT_PERCENT": 0.25,
        "FLAPS_HANDLE_PERCENT": 0.5,
        "GEAR_TOTAL_PCT_EXTENDED": 100.0,
        "SPOILERS_HANDLE_POSITION": 0.1,
        "SPOILERS_LEFT_POSITION": 0.4,
        "SPOILERS_RIGHT_POSITION": 0.3,
        "BRAKE_LEFT_POSITION": 16384.0,
        "BRAKE_RIGHT_POSITION": 8192.0,
        "AILERON_POSITION": 1.0,
        "ELEVATOR_POSITION": 1.0,
        "RUDDER_POSITION": 1.0,
        "YOKE_X_POSITION": 8192.0,
        "YOKE_Y_POSITION": -4096.0,
        "RUDDER_PEDAL_POSITION": 16384.0,
        "AILERON_LEFT_DEFLECTION_PCT": 0.4,
        "AILERON_RIGHT_DEFLECTION_PCT": -0.2,
        "ELEVATOR_DEFLECTION_PCT": -0.25,
        "RUDDER_DEFLECTION_PCT": 0.2,
        "GENERAL_ENG_THROTTLE_LEVER_POSITION:1": 73.0,
        "GENERAL_ENG_THROTTLE_LEVER_POSITION:2": 72.0,
        "NUMBER_OF_ENGINES": 2.0,
        "TURB_ENG_N1:1": 84.0,
        "TURB_ENG_N1:2": 83.0,
        "TURB_ENG_N2:1": 91.0,
        "TURB_ENG_N2:2": 90.0,
        "GENERAL_ENG_EXHAUST_GAS_TEMPERATURE:1": 650.0,
        "GENERAL_ENG_EXHAUST_GAS_TEMPERATURE:2": 645.0,
        "TURB_ENG_FUEL_FLOW_PPH:1": 2200.0,
        "TURB_ENG_FUEL_FLOW_PPH:2": 2180.0,
        "GENERAL_ENG_COMBUSTION:1": 1.0,
        "GENERAL_ENG_COMBUSTION:2": 1.0,
        "TITLE": "Fenix A320",
        "ATC_MODEL": "A320",
        "ATC_TYPE": "A320",
        "SIMULATION_RATE": 1.0,
        "IS_LATITUDE_LONGITUDE_FREEZE_ON": 0.0,
        "IS_SLEW_ACTIVE": 0.0,
    }

    class FakeAQ:
        def get(self, name: str):
            return values.get(name)

    original_diag = sp.simconnect_diagnostics
    original_session = sp._ensure_session
    prior_module = sys.modules.get("SimConnect")
    sys.modules["SimConnect"] = types.ModuleType("SimConnect")
    sp.simconnect_diagnostics = lambda: {"dll_path": "mock", "session_connected": True}
    sp._ensure_session = lambda diagnostics: (object(), FakeAQ())
    row = sp._read_position_uncached()
    sp.simconnect_diagnostics = original_diag
    sp._ensure_session = original_session
    if prior_module is None:
        sys.modules.pop("SimConnect", None)
    else:
        sys.modules["SimConnect"] = prior_module
    check(
        "dynamic SimConnect normalization preserves raw-unit meaning",
        row.get("ok") is True
        and abs(float(row.get("pilot_aileron_input")) - 0.5) < 1e-6
        and abs(float(row.get("pilot_elevator_input")) + 0.25) < 1e-6
        and abs(float(row.get("pilot_rudder_input")) - 1.0) < 1e-6
        and abs(float(row.get("actual_aileron_percent")) - 40.0) < 1e-6
        and abs(float(row.get("flap_percent")) - 25.0) < 1e-6
        and abs(float(row.get("flap_handle_percent")) - 50.0) < 1e-6
        and abs(float(row.get("spoiler_actual_percent")) - 40.0) < 1e-6
        and abs(float(row.get("brake_left_percent")) - 50.0) < 1e-6
        and abs(float(row.get("throttle_1_percent")) - 73.0) < 1e-6,
    )
except Exception as exc:
    print("SIMCONNECT NORMALIZATION ERROR:", exc)
    check("dynamic SimConnect normalization preserves raw-unit meaning", False)

# FSUIPC core plus optional SimConnect/category fusion; zero must remain data.
try:
    if bb is None:
        raise RuntimeError("black_box import unavailable")
    old_position = bb.read_position
    bb.read_position = lambda force=False: {
        "ok": True,
        "source": "simconnect",
        "pilot_aileron_input": 0.0,
        "pilot_elevator_input": -0.25,
        "pilot_rudder_input": 0.1,
        "throttle_1_percent": 73.0,
        "engine_1_n1_percent": 84.0,
        "provider_categories": {"controls": "SIMCONNECT", "engines": "SIMCONNECT"},
        "aircraft_adapter": {"key": "fenix", "label": "Fenix"},
        "systems": {"engines_running": True},
    }
    fused = bb._supplement_optional_parameters(
        {
            "ok": True,
            "source": "fsuipc7",
            "lat": 48.0,
            "lon": 11.0,
            "altitude_ft": 10000.0,
            "pilot_aileron_input": None,
            "engine_1_n1_percent": None,
            "systems": {"engines_running": True},
            "provider_categories": {"core": "FSUIPC7"},
        }
    )
    bb.read_position = old_position
    check(
        "FSUIPC core plus SimConnect supplement preserves core and legitimate zero",
        fused.get("source") == "fsuipc7"
        and fused.get("lat") == 48.0
        and fused.get("pilot_aileron_input") == 0.0
        and fused.get("pilot_elevator_input") == -0.25
        and fused.get("engine_1_n1_percent") == 84.0
        and (fused.get("provider_categories") or {}).get("core") == "FSUIPC7",
    )
except Exception as exc:
    print("FUSION ERROR:", exc)
    check("FSUIPC core plus SimConnect supplement preserves core and legitimate zero", False)

# Legacy row compatibility and short portable recording.
try:
    if bb is None:
        raise RuntimeError("black_box import unavailable")
    legacy_fields = ["lat", "lon", "altitude_ft", "source", "phase"]
    legacy_values = [[0.0, "2026-01-01T00:00:00Z", 48.0, 11.0, 1000.0, "fsuipc7", "TAXI OUT"]]
    legacy_payload = zlib.compress(json.dumps(legacy_values).encode("utf-8"))
    legacy_rows = bb._unpack_rows(legacy_payload, legacy_fields)
    check(
        "legacy short-field recording rows remain readable",
        legacy_rows[0].get("lat") == 48.0 and legacy_rows[0].get("phase") == "TAXI OUT",
    )
except Exception as exc:
    print("LEGACY ERROR:", exc)
    check("legacy short-field recording rows remain readable", False)

try:
    if bb is None:
        raise RuntimeError("black_box import unavailable")
    with tempfile.TemporaryDirectory(prefix="opsroom-v105-bb-") as tmp:
        old_root, old_tel, old_pos, old_settings = bb._root, bb.read_telemetry, bb.read_position, bb.load_settings
        isolated_root = Path(tmp) / "BlackBox"
        isolated_root.mkdir(parents=True, exist_ok=True)
        bb._root = lambda: isolated_root
        bb.load_settings = lambda: {
            "integrations": {
                "black_box_max_hz": 30,
                "black_box_simconnect_max_hz": 10,
                "black_box_enabled": True,
                "black_box_auto_record": True,
            }
        }
        counter = {"n": 0}

        def _tel(force: bool = False):
            counter["n"] += 1
            n = counter["n"]
            return {
                "ok": True,
                "source": "fsuipc7",
                "provider_categories": {"core": "FSUIPC7"},
                "lat": 48 + n * 1e-5,
                "lon": 11 + n * 1e-5,
                "altitude_ft": 1500 + n,
                "radio_altitude_ft": 300 + n,
                "indicated_speed_kts": 140,
                "ground_speed_kts": 142,
                "vertical_speed_fpm": 800,
                "heading_deg": 80,
                "pitch_deg": 4,
                "bank_deg": 1,
                "g_force": 1.01,
                "systems": {"parking_brake": False, "engines_running": True},
            }

        def _pos(force: bool = False):
            return {
                "ok": True,
                "source": "simconnect",
                "pilot_aileron_input": 0.0,
                "pilot_elevator_input": -0.15,
                "pilot_rudder_input": 0.05,
                "throttle_1_percent": 78.0,
                "throttle_2_percent": 77.5,
                "engine_count": 2,
                "engine_1_n1_percent": 88.0,
                "engine_2_n1_percent": 87.5,
                "provider_categories": {"controls": "SIMCONNECT", "engines": "SIMCONNECT"},
                "aircraft_adapter": {"key": "fenix", "label": "Fenix"},
                "systems": {"parking_brake": False, "engines_running": True},
            }

        bb.read_telemetry, bb.read_position = _tel, _pos
        bb._PHASE_CONTEXT.update({"flight_id": "rc3-test", "phase": "CLIMB", "meta": {}})
        started = bb.start_recording(
            "rc3-test",
            {
                "flight": {"callsign": "EWG7278", "origin": "EDDM", "destination": "LOWI"},
                "aircraft": {"registration": "D-AEWK"},
            },
        )
        time.sleep(0.55)
        finished = bb.stop_recording("VALIDATION")
        rows = bb.samples(finished.get("recording_id", ""), max_points=1000) if finished.get("ok") else []
        details = bb.recording(finished.get("recording_id", "")) if finished.get("ok") else {}
        path = Path(finished.get("path", "")) if finished.get("path") else None
        manifest_data = details.get("capability_manifest") or {}
        ok = bool(
            started.get("recording")
            and finished.get("ok")
            and path
            and path.is_file()
            and path.name.startswith("EWG7278_D-AEWK_EDDM-LOWI_")
            and path.suffix == ".opsbb"
            and rows
            and rows[-1].get("source") == "fsuipc7"
            and rows[-1].get("pilot_aileron_input") == 0.0
            and rows[-1].get("engine_1_n1_percent") == 88.0
            and manifest_data.get("providers", {}).get("core") == "FSUIPC7"
            and manifest_data.get("aircraft_adapter")
        )
        bb._root, bb.read_telemetry, bb.read_position, bb.load_settings = old_root, old_tel, old_pos, old_settings
        check("short recording finalizes with portable name and capability provenance", ok)
except Exception as exc:
    print("RECORDING ERROR:", exc)
    check("short recording finalizes with portable name and capability provenance", False)

# Central Black Box replay gate remains active.
try:
    if bb is None:
        raise RuntimeError("black_box import unavailable")
    old_guard = bb.replay_guard_active
    bb.replay_guard_active = lambda: True
    blocked = bb.start_recording("replay-test", {})
    bb.replay_guard_active = old_guard
    check(
        "Black Box recorder is still blocked during in-sim replay",
        blocked.get("recording") is False and blocked.get("replay_suppressed") is True,
    )
except Exception as exc:
    print("REPLAY GUARD ERROR:", exc)
    check("Black Box recorder is still blocked during in-sim replay", False)

expected = {
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
check(
    "12 protected operational/replay modules are byte-identical to v0.24.104",
    all(sha(rel) == digest for rel, digest in expected.items()),
)
check(
    "project context and beginner local guide are included",
    (ROOT / "OPS_ROOM_PROJECT_CONTEXT.md").is_file()
    and (ROOT / "OPS_ROOM_LOCAL_VSCODE_GUIDE.txt").is_file(),
)
check("airline logo collection remains complete", len(list((ROOT / "app/assets/logos").glob("*.png"))) == 3946)

# Updater/manifest generation gate using a real temporary ZIP.
try:
    import app.updater as updater

    valid_manifest = {
        "version": "0.24.105",
        "download_url": "https://example.invalid/OPS_ROOM_v0_24_105_Public_Beta_Black_Box_RC3_Windows_x64.zip",
        "sha256": "A" * 64,
    }
    accepted = updater._validate_manifest(dict(valid_manifest))
    rejected_http = False
    rejected_checksum = False
    try:
        updater._validate_manifest({**valid_manifest, "download_url": "http://example.invalid/update.zip"})
    except ValueError:
        rejected_http = True
    try:
        updater._validate_manifest({**valid_manifest, "sha256": "bad"})
    except ValueError:
        rejected_checksum = True
    with tempfile.TemporaryDirectory(prefix="opsroom-manifest-") as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / "OPS_ROOM_v0_24_105_Public_Beta_Black_Box_RC3_Windows_x64.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("OPS ROOM/version.json", json.dumps(version))
        out_path = tmp_path / "update.json"
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools/write_update_manifest.py"), "--version", "0.24.105", "--zip", str(zip_path), "--out", str(out_path)],
            cwd=ROOT, text=True, capture_output=True,
        )
        generated = json.loads(out_path.read_text(encoding="utf-8")) if out_path.is_file() else {}
        digest = hashlib.sha256(zip_path.read_bytes()).hexdigest().upper()
        sidecar = zip_path.with_suffix(zip_path.suffix + ".sha256")
        generated_ok = (
            proc.returncode == 0
            and generated.get("version") == "0.24.105"
            and generated.get("sha256") == digest
            and str(generated.get("download_url", "")).endswith(zip_path.name)
            and sidecar.is_file()
            and digest in sidecar.read_text(encoding="ascii")
        )
    check("updater validates secure manifests and build writer emits matching SHA-256", bool(accepted) and rejected_http and rejected_checksum and generated_ok)
except Exception as exc:
    print("UPDATER ERROR:", exc)
    check("updater validates secure manifests and build writer emits matching SHA-256", False)

try:
    from app.main import app

    check(
        "backend starts with expected route surface",
        app.version == "0.24.105" and len(app.routes) == 210 and len(app.openapi().get("paths", {})) == 185,
    )
except Exception as exc:
    print("BACKEND ERROR:", exc)
    check("backend starts with expected route surface", False)

proc = subprocess.run(
    ["node", str(ROOT / "tools/validate_airport_surface_renderer.js")],
    cwd=ROOT,
    text=True,
    capture_output=True,
)
print(proc.stdout, end="")
if proc.stderr:
    print(proc.stderr, end="")
check("deterministic OpenLayers airport renderer gate passes", proc.returncode == 0)

failed = [name for name, ok in checks if not ok]
print(f"RESULT: {len(checks) - len(failed)}/{len(checks)} checks passed")
if failed:
    print("FAILED: " + "; ".join(failed))
sys.exit(1 if failed else 0)
