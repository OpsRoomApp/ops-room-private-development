from __future__ import annotations

import hashlib
import json
import math
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import aviation_data  # noqa: E402
from app import black_box  # noqa: E402
from app import black_box_replay as replay  # noqa: E402
from app import logbook as lb  # noqa: E402
from app.settings_store import DEFAULT_SETTINGS  # noqa: E402

passed: list[str] = []


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    passed.append(label)


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


# Frozen operational systems: exact v0.24.51 hashes. Black Box and Live Map do
# not need to modify these service/analysis paths.
protected = {
    "app/fenix_adapter.py": "7a9597f65ea8f0e6e67f839fb607630faa4181d3bf725dd2160d1fc854571f46",
    "app/fenix_gsx_loading_state_machine.py": "6a9fc247e785228c210a3f2a3942925e29d1d744e9ce9a583f3dfaa495c0d2cd",
    "app/announcements.py": "721f55088def610f5d66e5dddd3a00123a86ccba10e4f2c2d654dedd1284da1b",
    "app/pirep_analysis.py": "a544897546cdbf03b2cb8d4e6d02a03b6c35b9e13f7d5a508e00f36ac63a6c3a",
    "app/gsx_receipts.py": "1af0c10b24f5e9acf28f951e49681f4faef92be4a6dc156ca5497191829a8e28",
    "app/economy.py": "7c65910e4807871fdf5ba922144c1af7f4e13ab23ff805e62170da273e702f87",
    "app/raas.py": "7e808122ebd1f8c6301421b28a0ca84585426b9d730bb9506408d99ee5e6578b",
    "app/gsx_remote.py": "092f44951bf98f35fd2fd12063c8743f3ae4f75efaef3cf5f89860764354a389",
}
for rel, expected in protected.items():
    check(sha(rel) == expected, f"Frozen operational subsystem unchanged: {rel}")

# v0.24.51 fixed-layout Full PIREP and Ground Control patch remain present.
print_css = (ROOT / "app/static/pirep_print.css").read_text(encoding="utf-8")
print_js = (ROOT / "app/static/pirep_print.js").read_text(encoding="utf-8")
pirep_js = (ROOT / "app/static/pirep.js").read_text(encoding="utf-8")
logbook_source = (ROOT / "app/logbook.py").read_text(encoding="utf-8")
index_html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
host_html = (ROOT / "app/static/host.html").read_text(encoding="utf-8")
ops_js = (ROOT / "app/static/opsroom.js").read_text(encoding="utf-8")
main_source = (ROOT / "app/main.py").read_text(encoding="utf-8")
check("297mm" in print_css and "210mm" in print_css and ".pdf-page" in print_css, "Fixed A4 landscape Full PIREP layout retained")
check("window.__OPSROOM_PDF_READY__" in print_js and "pdf-source-${source.id}" in print_js, "Dedicated Full PIREP report pagination retained")
check("Page.setDocumentContent" in logbook_source and "Page.printToPDF" in logbook_source, "Self-contained Chromium PDF renderer retained")
check("window.print()" not in pirep_js and "/api/logbook/${encodeURIComponent(id)}/export.pdf" in pirep_js, "SAVE PDF remains a direct download")
check('id="groundDepartureCatering"' in index_html and 'id="groundDepartureWater"' in index_html, "Catering and Water controls remain on Ground Control")
check('id="hostGsxDepartureCatering"' not in host_html and 'id="hostGsxDepartureWater"' not in host_html, "Catering and Water controls remain removed from Host Settings")
check("/api/ground/preferences" in ops_js and '@app.put("/api/ground/preferences")' in main_source, "Ground Control preference API remains wired")

# Black Box defaults and source boundaries.
ints = DEFAULT_SETTINGS["integrations"]
check(ints.get("black_box_enabled") is True, "Black Box enabled by default")
check(ints.get("black_box_auto_record") is True, "Automatic TAXI OUT to TAXI IN recording enabled")
check(ints.get("black_box_max_hz") == 30, "Black Box maximum configured at 30 Hz")
check(ints.get("black_box_simconnect_max_hz") == 10, "Current Python SimConnect recorder has a conservative 10 Hz default cap")
telemetry_source = (ROOT / "app/telemetry_provider.py").read_text(encoding="utf-8")
black_box_source = (ROOT / "app/black_box.py").read_text(encoding="utf-8")
check("_CACHE_SECONDS = 0.18" in telemetry_source, "Normal operational telemetry cache remains unchanged")
check("if not force and _CACHE is not None" in telemetry_source, "Only explicit fresh reads bypass the operational cache")
check("read_telemetry(force=True)" in black_box_source, "Black Box requests fresh telemetry independently")
check('phase_up == "TAXI OUT"' in black_box_source and 'phase_up == "TAXI IN"' in black_box_source, "Automatic recording boundaries are TAXI OUT and TAXI IN")
check("requested = 30.0" in black_box_source and "20.0 if phase_up" in black_box_source, "Adaptive capture rates are packaged")
check("zlib.compress" in black_box_source and "CREATE TABLE IF NOT EXISTS chunks" in black_box_source, "Black Box uses compressed chunk storage")
check("PRAGMA wal_checkpoint(TRUNCATE)" in black_box_source, "Completed OPSBB files are checkpointed for portability")

# Runtime Black Box recording, persistence, linking and exports in an isolated data folder.
orig_app_data = black_box.app_data_dir
orig_settings = black_box.load_settings
orig_read = black_box.read_telemetry
try:
    with tempfile.TemporaryDirectory(prefix="opsroom-blackbox-preview-") as tmp:
        root = Path(tmp)
        black_box.app_data_dir = lambda: root  # type: ignore[assignment]
        black_box.load_settings = lambda: {"integrations": {  # type: ignore[assignment]
            "black_box_enabled": True,
            "black_box_auto_record": True,
            "black_box_max_hz": 30,
            "black_box_simconnect_max_hz": 30,
        }}
        counter = {"n": 0}

        def fake_telemetry(force: bool = False) -> dict:
            counter["n"] += 1
            n = counter["n"]
            return {
                "ok": True, "telemetry_complete": True, "telemetry_fresh": True,
                "source": "fsuipc7", "lat": 48.0 + n * 0.00002, "lon": 11.0 + n * 0.00003,
                "altitude_ft": 1700 + n, "agl_ft": 3, "radio_altitude_ft": 3,
                "indicated_speed_kts": 12 + n * 0.1, "true_speed_kts": 12 + n * 0.1,
                "ground_speed_kts": 12 + n * 0.1, "mach": 0.02, "vertical_speed_fpm": 0,
                "heading_deg": (359 + n * 0.4) % 360, "track_deg": (359 + n * 0.4) % 360,
                "pitch_deg": 0.1, "bank_deg": 0.2, "g_force": 1.0,
                "flap_index": 1, "flap_percent": 10, "gear_percent": 100,
                "spoiler_percent": 0, "reverser_percent": 0, "brake_percent": 5,
                "aileron_position": 0.01 * n, "elevator_position": 0.0, "rudder_position": 0.0,
                "throttle_1_percent": 22, "throttle_2_percent": 22,
                "body_velocity_x_fps": 18, "body_velocity_y_fps": 0, "body_velocity_z_fps": 0,
                "fuel_total_lb": 9000, "fuel_flow_pph": 700, "engine_n1_percent": 25,
                "wind_speed_kts": 4, "wind_direction_deg": 250, "on_ground": True,
                "systems": {"parking_brake": False, "engines_running": True},
                "autopilot": {"engaged": False, "autothrottle": False},
                "sim_rate": 1, "paused": False, "slew_active": False,
                "stall_warning": False, "overspeed_warning": False,
            }

        black_box.read_telemetry = fake_telemetry  # type: ignore[assignment]
        with black_box._LOCK:
            black_box._ACTIVE = None
            black_box._THREAD = None
            black_box._STOP.clear()
            black_box._RING.clear()
            black_box._PHASE_CONTEXT.update({"flight_id": None, "phase": "", "meta": {}})
        meta = {"flight": {"callsign": "TEST100", "origin": "LOWW", "destination": "LOWI"}, "aircraft": {"icao": "A320"}}
        black_box.observe_phase("flight-preview-test", "TAXI OUT", meta)
        time.sleep(0.45)
        live = black_box.status()
        check(live.get("recording") is True, "TAXI OUT starts a Black Box recording")
        check(int((live.get("active") or {}).get("sample_count") or 0) >= 3, "Recorder captures multiple fresh telemetry samples")
        black_box.observe_phase("flight-preview-test", "TAXI IN", meta)
        check(black_box.status().get("recording") is False, "TAXI IN closes the Black Box recording")
        rows = black_box.list_recordings()
        check(len(rows) == 1 and rows[0].get("state") == "COMPLETE", "Completed recording is listed")
        recording_id = str(rows[0]["recording_id"])
        detail = black_box.recording(recording_id)
        check(detail.get("flight_id") == "flight-preview-test", "Recording is linked to the logbook flight id")
        check(int(detail.get("sample_count") or 0) >= 3 and float(detail.get("duration_seconds") or 0) > 0, "OPSBB metadata contains sample count and duration")
        sample_rows = black_box.samples(recording_id, max_points=1000)
        check(len(sample_rows) >= 3 and sample_rows[0].get("phase") == "TAXI OUT", "OPSBB samples can be decoded")
        opsbb = black_box.file_path(recording_id)
        check(opsbb.is_file() and opsbb.stat().st_size > 1000, "Portable OPSBB file is produced")
        check(not Path(str(opsbb) + "-wal").exists(), "Completed OPSBB has no pending WAL file")
        csv_data = black_box.export_csv(recording_id).decode("utf-8-sig")
        check(csv_data.startswith("elapsed,utc,lat,lon") and "fsuipc7" in csv_data, "CSV export contains flight data")
        check(b"<gpx" in black_box.export_gpx(recording_id) and b"<trkpt" in black_box.export_gpx(recording_id), "GPX route export is valid")
        check(b"<kml" in black_box.export_kml(recording_id) and b"<LineString>" in black_box.export_kml(recording_id), "KML route export is valid")
        check((black_box.recording_for_flight("flight-preview-test") or {}).get("recording_id") == recording_id, "Logbook-to-recording lookup works")

        # Replay interpolation and controller are exercised without a simulator.
        orig_freeze = replay.replay_set_freeze
        orig_apply = replay.replay_apply_state
        orig_normal = replay._normal_recording_active
        freezes: list[bool] = []
        applied: list[dict] = []
        try:
            replay.replay_set_freeze = lambda enabled: (freezes.append(bool(enabled)) or {"ok": True, "frozen": bool(enabled)})  # type: ignore[assignment]
            replay.replay_apply_state = lambda frame: (applied.append(dict(frame)) or {"ok": True, "writes": 6})  # type: ignore[assignment]
            replay._normal_recording_active = lambda: False  # type: ignore[assignment]
            result = replay.start(recording_id, speed=2.0, loop=True)
            check(result.get("ok") is True and result.get("active") is True, "In-simulator replay controller starts")
            time.sleep(0.08)
            controlled = replay.control(playing=False, cursor=0.1, speed=0.5, loop=False)
            check(controlled.get("active") is True and controlled.get("playing") is False, "Replay supports pause, seek, speed and loop controls")
            stopped = replay.stop()
            check(stopped.get("ok") is True and freezes[:1] == [True] and freezes[-1:] == [False], "Replay freezes and safely releases the aircraft")
            check(len(applied) >= 2, "Replay applies interpolated frames")
        finally:
            replay.stop()
            replay.replay_set_freeze = orig_freeze  # type: ignore[assignment]
            replay.replay_apply_state = orig_apply  # type: ignore[assignment]
            replay._normal_recording_active = orig_normal  # type: ignore[assignment]

        # Heading interpolation must take the shortest circular path.
        with replay._LOCK:
            replay._ROWS = [{"elapsed": 0.0, "heading_deg": 359.0}, {"elapsed": 1.0, "heading_deg": 1.0}]
            replay._TIMES = [0.0, 1.0]
        middle = replay._frame_at(0.5)
        heading = float((middle or {}).get("heading_deg") or 0.0)
        check(heading < 2.0 or heading > 358.0, "Replay heading interpolation crosses 359/0 correctly")
        with replay._LOCK:
            replay._ROWS = []
            replay._TIMES = []

        # Interrupted recordings are recoverable.
        interrupted_path = root / "BlackBox" / "interrupted-test.opsbb"
        black_box._init_recording(interrupted_path, {"recording_id": "interrupted-test", "flight_id": "interrupted-flight", "started_utc": "2026-07-18T00:00:00Z", "state": "RECORDING"})
        black_box.recover_interrupted()
        check(black_box._metadata(interrupted_path).get("state") == "INTERRUPTED", "Interrupted OPSBB is recovered on startup")
finally:
    try:
        replay.stop()
        if black_box.status().get("recording"):
            black_box.stop_recording("VALIDATOR CLEANUP")
    except Exception:
        pass
    black_box.app_data_dir = orig_app_data  # type: ignore[assignment]
    black_box.load_settings = orig_settings  # type: ignore[assignment]
    black_box.read_telemetry = orig_read  # type: ignore[assignment]

# Replay UI and APIs.
check('data-page="blackbox"' in index_html and 'id="page-blackbox"' in index_html, "Black Box module is present in the browser console")
for identifier in ("blackBoxRecordings", "blackBoxCanvas", "blackBoxTimeline", "blackBoxSimReplay", "blackBoxDownloads"):
    check(f'id="{identifier}"' in index_html, f"Black Box UI includes {identifier}")
for route in (
    '/api/blackbox/status', '/api/blackbox/preferences', '/api/blackbox/recordings',
    '/api/blackbox/replay/status', '/api/blackbox/replay/stop', '/api/blackbox/{recording_id}/replay/start',
    '/api/blackbox/{recording_id}/samples', '/api/blackbox/{recording_id}/download',
    '/api/blackbox/{recording_id}/export.csv', '/api/blackbox/{recording_id}/export.gpx', '/api/blackbox/{recording_id}/export.kml',
):
    check(route in main_source, f"Black Box API packaged: {route}")
check("BLACK BOX REPLAY" in ops_js and "startInSimReplay" in ops_js and "controlInSim" in ops_js, "Browser and in-simulator replay controls are wired")
check("recording_for_flight" in logbook_source and '"black_box"' in logbook_source, "Full logbook entries expose linked Black Box recordings")

# SimConnect replay uses documented freeze-event names and standard state writes.
sim_source = (ROOT / "app/simconnect_position.py").read_text(encoding="utf-8")
for event in ("FREEZE_LATITUDE_LONGITUDE_SET", "FREEZE_ALTITUDE_SET", "FREEZE_ATTITUDE_SET"):
    check(event in sim_source, f"Replay freeze event packaged: {event}")
for variable in ("PLANE_LATITUDE", "PLANE_LONGITUDE", "PLANE_ALTITUDE", "PLANE_PITCH_DEGREES", "PLANE_BANK_DEGREES", "PLANE_HEADING_DEGREES_TRUE"):
    check(variable in sim_source, f"Mandatory replay state packaged: {variable}")
check("optional_rejections" in sim_source, "Aircraft-specific optional replay writes cannot cancel position replay")

# Live Map surface merge and browser layer separation.
segments = [
    {"name": "A", "type": "TAXI", "surface": "ASPHALT", "width_ft": 75, "start_lon": 1.0, "start_lat": 2.0, "end_lon": 1.1, "end_lat": 2.0},
    {"name": "A", "type": "TAXI", "surface": "ASPHALT", "width_ft": 75, "start_lon": 1.1, "start_lat": 2.0, "end_lon": 1.2, "end_lat": 2.0},
    {"name": "A", "type": "TAXI", "surface": "ASPHALT", "width_ft": 75, "start_lon": 1.2, "start_lat": 2.0, "end_lon": 1.3, "end_lat": 2.0},
]
merged = aviation_data._merge_taxi_segments(segments)
check(len(merged) == 1 and merged[0].get("segment_count") == 3 and len(merged[0].get("points") or []) == 4, "Connected taxiway segments merge into one polyline")
av_source = (ROOT / "app/aviation_data.py").read_text(encoding="utf-8")
check("limit 12000" in av_source and "raw_taxi_segment_count" in av_source and "taxi_polyline_count" in av_source, "Backend returns merged taxiway diagnostics")
for marker in ("olRouteAirportLayer", "olSurfaceLabelLayer", "declutter:false", "taxi-label", "runway-label"):
    check(marker in ops_js, f"Live Map optimized layer marker packaged: {marker}")
check("src.clear();labelSrc.clear();src.addFeatures" in ops_js.replace(" ", ""), "Airport surface features replace atomically after preparation")
check("Array.isArray(t.points)" in ops_js, "Live Map renders merged taxiway polylines")

# Credits and licensing boundaries.
credits = (ROOT / "BLACK_BOX_DESIGN_CREDITS.md").read_text(encoding="utf-8")
notices = (ROOT / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8")
check("SkyDolly" in credits and "MIT" in credits and "original OPS ROOM implementation" in credits, "SkyDolly inspiration and original implementation are credited")
check("PilotPathRecorder" in credits and "MSFS Landing Inspector" in credits, "Related MIT projects are credited")
check("GPL" in credits and "No GPL-licensed source code" in credits, "GPL reference boundary is explicit")
check("SkyDolly" in notices and "PilotPathRecorder" in notices, "Third-party notices include design references")

# Version and packaging metadata.
version = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
update = json.loads((ROOT / "update.json").read_text(encoding="utf-8"))
check(version == {"product": "OPS ROOM", "version": "0.24.100", "build": "public-beta-black-box-preview-1", "codename": "Flight Data Recorder", "channel": "preview"}, "Version metadata identifies the Black Box Preview")
check(update.get("version") == "0.24.100" and update.get("channel") == "preview" and "Black_Box_Preview" in str(update.get("download_url")), "Updater metadata targets the preview package")
build = (ROOT / "BUILD OPS ROOM COMPLETE.bat").read_text(encoding="utf-8")
app_build = (ROOT / "BUILD WINDOWS APP ONLY.bat").read_text(encoding="utf-8")
check("OPS_ROOM_v0_24_100_Public_Beta_Black_Box_Preview_Windows_x64.zip" in build, "Complete Windows build targets the preview ZIP")
check("BLACK_BOX_DESIGN_CREDITS.md" in app_build and "THIRD_PARTY_NOTICES.txt" in app_build, "Windows distribution includes credits and notices")
notes = (ROOT / "OPS_ROOM_v0_24_100_BLACK_BOX_PREVIEW_RELEASE_NOTES.md").read_text(encoding="utf-8")
check("TAXI OUT" in notes and "TAXI IN" in notes and "in-simulator replay" in notes, "Release notes document recording and replay")
check("Live Map" in notes and "v0.24.51" in notes, "Release notes document map and inherited release patch")

# The packaged FastAPI application exposes the expected preview version/routes.
from app.main import app  # noqa: E402
check(app.version == "0.24.100", "FastAPI version is 0.24.100")
check(len(app.routes) >= 200, "FastAPI includes the expanded Black Box API surface")

# Render a small fixed-layout PDF with the packaged master report renderer when
# Chromium/Edge is available in the validation environment.
old_get_entry = lb.get_entry
old_telemetry = lb.telemetry
try:
    lb.get_entry = lambda _entry_id: {
        "id": "preview-pdf-test", "state": "COMPLETE",
        "flight": {"callsign": "TEST100", "origin": "LOWW", "destination": "LOWI", "aircraft_icao": "A320"},
        "times": {"off_block_utc": "2026-07-17T09:30:00Z", "on_block_utc": "2026-07-17T10:14:00Z"},
        "durations": {"block_seconds": 2640, "airborne_seconds": 2340},
        "metrics": {"distance_nm": 234.0, "landing_rate_fpm": -121.0},
        "fuel": {"used_lb": 4213.0}, "debrief": {"score": 94, "events": []},
        "finance": {}, "receipts": [],
    }  # type: ignore[assignment]
    lb.telemetry = lambda _entry_id, max_points=5000: {
        "ok": True, "samples": [
            {"timestamp": "2026-07-17T09:30:00Z", "latitude": 48.11, "longitude": 16.57, "altitude_ft": 600, "groundspeed_kt": 0, "fuel_total_lb": 10400},
            {"timestamp": "2026-07-17T10:14:00Z", "latitude": 47.26, "longitude": 11.34, "altitude_ft": 1907, "groundspeed_kt": 0, "fuel_total_lb": 6100},
        ], "analysis": {},
    }  # type: ignore[assignment]
    snapshot = lb._pirep_snapshot_html("preview-pdf-test", {"interface": {"units": "metric"}})
finally:
    lb.get_entry = old_get_entry  # type: ignore[assignment]
    lb.telemetry = old_telemetry  # type: ignore[assignment]
check("window.__OPSROOM_PIREP_PRELOADED__=" in snapshot, "PDF snapshot injects the Full PIREP master data")
if lb._browser_candidates():
    rendered = lb._render_full_pirep_pdf_html(snapshot, timeout_seconds=30.0)
    check(bool(rendered and rendered.startswith(b"%PDF-") and len(rendered) > 5000), "Fixed-layout Full PIREP renders to a valid PDF")
else:
    passed.append("Fixed-layout Full PIREP browser render skipped: no Chromium/Edge candidate")

print(json.dumps({"ok": True, "passed": len(passed), "checks": passed}, indent=2))
