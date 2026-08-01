from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
CHECKS: list[tuple[str, bool]] = []


def check(name: str, ok: object) -> None:
    passed = bool(ok)
    CHECKS.append((name, passed))
    print(("PASS" if passed else "FAIL") + ": " + name)


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="replace")


version = json.loads(text("version.json"))
manifest = json.loads(text("update.json"))
ui = text("app/static/opsroom.js")
html = text("app/static/index.html")
css = text("app/static/opsroom.css")
main = text("app/main.py")
black_box = text("app/black_box.py")
replay = text("app/black_box_replay.py")
simconnect = text("app/simconnect_position.py")
telemetry = text("app/telemetry_provider.py")
guard = text("app/replay_guard.py")
logbook = text("app/logbook.py")
complete = text("BUILD OPS ROOM COMPLETE.bat")
windows = text("BUILD WINDOWS APP ONLY.bat")
camera = text("BUILD CAMERA BRIDGE 2024.bat")

check("version metadata is v0.24.103 Black Box RC1", version.get("version") == "0.24.103" and version.get("channel") == "release-candidate")
check("FastAPI runtime version is v0.24.103", 'FastAPI(title="OPS ROOM", version="0.24.103")' in main)
check("bundled updater manifest targets v0.24.103", manifest.get("version") == "0.24.103" and str(manifest.get("download_url", "")).endswith("OPS_ROOM_v0_24_103_Public_Beta_Black_Box_RC1_Windows_x64.zip"))
check("final dist remains beside build scripts", 'set "DIST_DIR=%~dp0dist"' in complete and 'set "DIST_DIR=%~dp0dist"' in windows)
check("only intermediate build files use short OR103 root", "%TEMP%\\OR103" in complete and "%TEMP%\\OR103" in windows and "%OPSROOM_BUILD_ROOT%\\camera_bridge" in camera)
check("human-readable crash-safe .opsbb filenames", "callsign" in black_box and "registration" in black_box and "origin" in black_box and "destination" in black_box and ".opsbb.part" in black_box)
check("legacy UUID recordings remain discoverable", "Backward compatibility" in black_box and "recording_id" in black_box[black_box.find("def _path_for"):black_box.find("def _path_for") + 1300])
check("live Black Box API is present before dynamic recording route", "/api/blackbox/live" in main and "def live_snapshot" in black_box and main.find('/api/blackbox/live') < main.find('/api/blackbox/{recording_id}"'))
check("live FDR tabs are present", all(f'data-blackbox-view="{token}"' in html for token in ["flight", "controls", "engines", "systems", "track", "events"]))
check("live FDR polling is automatic and frequent", "/api/blackbox/live" in ui and "250" in ui and "blackBoxLive" in ui)
check("raw recording ID and giant watermark are not normal UI", "blackBoxTechnicalDetails" in ui and "<summary>TECHNICAL DETAILS</summary>" in ui and "blackbox-watermark" not in css and "recording/session ID" not in html)
check("FSUIPC extended FDR offsets are mapped", all(token in telemetry for token in ["0x088C", "0x0924", "0x0898", "0x0930", "0x0BB2", "0x0BB6", "0x0BBA", "0x0BD0"]))
check("unsupported advanced values can remain unavailable", "all-zero running-engine blocks" in telemetry and "engine_1_n1 = engine_1_n2 = engine_1_egt = engine_1_ff = None" in telemetry)
check("central replay guard has active and cooldown states", "def activate" in guard and "def release" in guard and "_UNTIL" in guard)
check("all normal logbook start paths consult replay guard", all(token in logbook for token in ["def _should_start", "def _start", "def _engine_iteration", "def start_departure_services", "def start_manual"]) and logbook.count("_replay_guarded()") >= 5)
check("Black Box auto recording consults replay guard", "replay_guard_active()" in black_box and "replay_suppressed" in black_box)
check("replay uses simulator Frame clock", "SubscribeToSystemEvent" in simconnect and 'b"Frame"' in simconnect and "ReplayFrameClock" in simconnect)
check("replay pose is sent atomically", "class _ReplayPose" in simconnect and "SetDataOnSimObject" in simconnect and "one ``SetDataOnSimObject`` data block" in simconnect)
check("replay interpolation uses Hermite and quaternion SLERP", "_hermite_value" in replay and "_quat_slerp" in replay and "_quat_from_euler" in replay)
check("camera-safe replay sends no camera/view events", all(token not in simconnect for token in ["CAMERA_SET", "CAMERA_RESET", "VIEW_MODE", "CHASE_VIEW"]))
check("seek uses pause, atomic reposition and settle", "seeking" in replay and "initial=True" in replay and "two visual frames" in replay)
check("shared RC24 operational fixes are included", all(token in ui for token in ["briefing-identity", "active-flight-hero", "function surfaceStyle", "requestAnimationFrame"]))
check("airline logo collection remains complete", len(list((ROOT / "app/assets/logos").glob("*.png"))) == 3946)

failed = [name for name, ok in CHECKS if not ok]
print(f"RESULT: {len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
if failed:
    print("FAILED: " + "; ".join(failed))
sys.exit(1 if failed else 0)
