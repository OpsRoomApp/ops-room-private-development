from __future__ import annotations

import ast
import hashlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import gsx_remote as gsx  # noqa: E402
from app import logbook as lb  # noqa: E402
from app.weather_client import decode_metar  # noqa: E402

passed: list[str] = []


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    passed.append(label)


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def source_hash(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(
        item
        for item in ast.walk(tree)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
    )
    segment = ast.get_source_segment(source, node) or ""
    return hashlib.sha256(segment.encode("utf-8")).hexdigest()


# Preserve all unrelated live systems exactly.
protected = {
    "app/fenix_adapter.py": "7a9597f65ea8f0e6e67f839fb607630faa4181d3bf725dd2160d1fc854571f46",
    "app/fenix_gsx_loading_state_machine.py": "6a9fc247e785228c210a3f2a3942925e29d1d744e9ce9a583f3dfaa495c0d2cd",
    "app/announcements.py": "721f55088def610f5d66e5dddd3a00123a86ccba10e4f2c2d654dedd1284da1b",
    "app/telemetry_provider.py": "0c921fe33d076d68db66d479bb3db5388c844924924d7995358bdafe21c91de8",
    "app/simconnect_position.py": "0487bf2bae0ccfc34147edeca0871dc2879d627598ec90a21dd4b145de5d7445",
    "app/pirep_analysis.py": "a544897546cdbf03b2cb8d4e6d02a03b6c35b9e13f7d5a508e00f36ac63a6c3a",
    "app/gsx_receipts.py": "1af0c10b24f5e9acf28f951e49681f4faef92be4a6dc156ca5497191829a8e28",
    "app/economy.py": "7c65910e4807871fdf5ba922144c1af7f4e13ab23ff805e62170da273e702f87",
    "app/settings_store.py": "0bd2117c4a8412d113047514986f06e8552bc3508b91ef834cdce3d5aa26af05",
    "app/raas.py": "7e808122ebd1f8c6301421b28a0ca84585426b9d730bb9506408d99ee5e6578b",
    "app/briefing_data.py": "2bf48620aeb9da0504df7df6a886bb3648cd61d2a4eb15106ccec490ff279c50",
    "app/simbrief_client.py": "06fc49453fa9fdf28139ee2b759a1304d77e0d33fdf912a49254312db1e158cc",
    "app/static/opsroom.js": "5e43f13446c2a2b57f8a7ab5e849e2e3db894bb582b60f671e086e91c0a41eda",
}
for rel, expected in protected.items():
    check(sha(rel) == expected, f"Frozen live subsystem unchanged: {rel}")

# Within gsx_remote, preserve the existing request, Fenix, door and pushback mechanisms.
function_hashes = {
    "_request_arrival_service_when_available": "ac8e47bee61c54cf7bdfffed1d5d28a7eb08358c98e458f91e6f2130fbfe3a35",
    "_coordinate_verified_pushback_handoff": "68ae9987ed4e72c93ef00a1be39c03979559cfc44df117e1e9428db15a2b71fc",
    "_coordinate_arrival_fenix_deboarding": "cba21df1801963f992c8e14aff8ef2ee01c40c7d7786a041aedc7e8f12590652",
    "_coordinate_arrival_cargo_doors_closed": "77e7c1b5e8872d08020c32a2aff2e3dc5582789b08fd1f990a3e62ead5ef0ca5",
    "_service_plan_for_mode": "27a8c9c348efbb14809dc0efcf328c133bea59a5257395db3bd648860ba8747b",
    "_fenix_authoritative_complete": "0d74348284bc847b3e7842ed4dfd118f9ab3559180a8cbb8ccd7002c71b2225a",
    "_request_once": "487c6b030bcb6bf3fb112ccc029942a8ad96412bab079a4a9d91b856ee1d2e98",
    "call_service": "cf6ea78433bd42915441d8608dcffbb2b90e0b1f47ac32ca9ac81bcfe1eee82b",
}
for name, expected in function_hashes.items():
    check(source_hash(ROOT / "app/gsx_remote.py", name) == expected, f"Existing GSX mechanism unchanged: {name}")


def reset_automation() -> None:
    with gsx._AUTOMATION_LOCK:
        gsx._AUTOMATION.update(
            running=True,
            stage="TEST",
            detail="TEST",
            requested=[],
            requested_at={},
            history=[],
            mode="ARRIVAL",
            latches={},
        )
        gsx._AUTOMATION_REQUESTED_MONO.clear()


# Arrival: live Cleaning must be adopted and cannot be skipped by an availability timeout.
reset_automation()
requested_snap = {
    "provider": "remote-v2",
    "services": {"cleaning": {"remote_state": "requested", "source": "official-remote-api-v2"}},
    "progress": {},
}
check(gsx._arrival_service_complete_current(requested_snap, "cleaning", 1) is False, "Requested Cleaning remains pending")
check(bool(gsx._get_latch("cleaning_seen_active")), "Requested Cleaning is marked active")
check("cleaning" in set(gsx._AUTOMATION.get("requested") or []), "Live Cleaning is adopted into current Arrival session")
gsx._AUTOMATION_REQUESTED_MONO["arrival_deboarding_complete_at"] = time.monotonic() - 900.0
check(gsx._maybe_defer_unavailable_arrival_service(requested_snap, "cleaning", 1) is False, "Cleaning cannot be skipped by timeout")
check(not gsx._get_latch("cleaning_deferred_or_skipped"), "No false Cleaning skip latch is created")

performing_snap = {
    "provider": "remote-v2",
    "services": {"cleaning": {"remote_state": "performing", "source": "official-remote-api-v2"}},
    "progress": {},
}
check(gsx._arrival_service_complete_current(performing_snap, "cleaning", 5) is False, "Performing Cleaning blocks Arrival completion")
completed_snap = {
    "provider": "remote-v2",
    "services": {"cleaning": {"remote_state": "completed", "source": "official-remote-api-v2"}},
    "progress": {},
}
check(gsx._arrival_service_complete_current(completed_snap, "cleaning", 6) is True, "Completed Cleaning closes only after terminal state")
check(bool(gsx._get_latch("cleaning_complete")), "Cleaning completion latch is set by terminal state")

# Same invariant for Lavatory.
reset_automation()
lav_snap = {"services": {"lavatory": {"state": "performing"}}, "progress": {}}
check(gsx._arrival_service_complete_current(lav_snap, "lavatory", 5) is False, "Performing Lavatory blocks Arrival completion")
check(gsx._maybe_defer_unavailable_arrival_service(lav_snap, "lavatory", 5) is False, "Lavatory cannot be skipped while active")
check(gsx._arrival_service_complete_current({"services": {"lavatory": {"state": "completed"}}}, "lavatory", 6) is True, "Lavatory closes on terminal state")

# Pushback: the verified completion branch must run before fresh passenger validation.
gsx_source = (ROOT / "app/gsx_remote.py").read_text(encoding="utf-8")
automation_start = gsx_source.index("def _automation_cycle")
automation_end = gsx_source.index("\ndef _pushback_direction_menu_visible", automation_start)
automation_block = gsx_source[automation_start:automation_end]
monotonic_marker = 'if _get_latch("fenix_targets_complete") and _get_latch("fenix_pushback_armed_after_loading"):'
boarding_gate = "_boarding_service_complete_from_snapshot"
check(monotonic_marker in automation_block, "Monotonic Fenix completion branch is packaged")
check(automation_block.index(monotonic_marker) < automation_block.index(boarding_gate), "Armed pushback timer bypasses regressed passenger counters")
check('_coordinate_verified_pushback_handoff(snap)' in automation_block, "Existing verified pushback handoff remains in use")
check('60.0 - (time.monotonic() - float(armed_at))' in automation_block, "Existing 60-second delay remains exact")
check(automation_block.count('PUSHBACK_REQUESTED_AFTER_LOADING') >= 2, "Both normal and recovered completion paths retain one-shot handoff logging")

# Full PIREP PDF uses exactly the same page assets and preloaded report data.
html_template = (ROOT / "app/static/pirep.html").read_text(encoding="utf-8")
check('pirep.css?v=0-24-49-rc19' in html_template and 'pirep.js?v=0-24-49-rc19' in html_template, "Full PIREP page targets RC19 assets")

old_get_entry = lb.get_entry
old_telemetry = lb.telemetry
try:
    lb.get_entry = lambda _entry_id: {
        "id": "rc19-pdf-test",
        "state": "COMPLETE",
        "flight": {"callsign": "AUA101", "origin": "LOWW", "destination": "LOWI", "aircraft_icao": "A320"},
        "times": {"off_block_utc": "2026-07-17T09:30:00Z", "on_block_utc": "2026-07-17T10:14:00Z"},
        "durations": {"block_seconds": 2640, "airborne_seconds": 2340},
        "metrics": {"distance_nm": 234.0, "landing_rate_fpm": -121.0},
        "fuel": {"used_lb": 4213.0},
        "debrief": {"score": 94, "events": []},
        "finance": {},
        "receipts": [],
    }  # type: ignore[assignment]
    lb.telemetry = lambda _entry_id, max_points=5000: {
        "ok": True,
        "samples": [
            {"timestamp": "2026-07-17T09:30:00Z", "latitude": 48.11, "longitude": 16.57, "altitude_ft": 600, "groundspeed_kt": 0, "fuel_total_lb": 10400},
            {"timestamp": "2026-07-17T10:14:00Z", "latitude": 47.26, "longitude": 11.34, "altitude_ft": 1907, "groundspeed_kt": 0, "fuel_total_lb": 6100},
        ],
        "analysis": {},
    }  # type: ignore[assignment]
    snapshot = lb._pirep_snapshot_html("rc19-pdf-test", {"interface": {"units": "metric"}})
finally:
    lb.get_entry = old_get_entry  # type: ignore[assignment]
    lb.telemetry = old_telemetry  # type: ignore[assignment]

check("window.__OPSROOM_PIREP_PRELOADED__=" in snapshot, "PDF snapshot injects stored Full PIREP data")
check('<link rel="stylesheet" href="/static/pirep.css' not in snapshot, "PDF snapshot inlines the master PIREP CSS")
check('<script src="/static/pirep.js' not in snapshot, "PDF snapshot inlines the master PIREP JavaScript")
check("AUA101" in snapshot and "rc19-pdf-test" in snapshot, "PDF snapshot contains selected flight data")

logbook_source = (ROOT / "app/logbook.py").read_text(encoding="utf-8")
pirep_js = (ROOT / "app/static/pirep.js").read_text(encoding="utf-8")
main_source = (ROOT / "app/main.py").read_text(encoding="utf-8")
check('"about:blank"' in logbook_source and "Page.setDocumentContent" in logbook_source, "Renderer no longer navigates headless browser to localhost")
check("max_size=None" in logbook_source, "DevTools connection accepts large PDF responses")
check("Page.printToPDF" in logbook_source and "window.__OPSROOM_PIREP_READY__" in logbook_source, "Renderer waits for master PIREP before printing")
check("ignore_cleanup_errors=True" in logbook_source and '["taskkill", "/PID", str(process.pid), "/T", "/F"]' in logbook_source, "Windows renderer cleanup remains lock-safe")
check("pirep-pdf-renderer.log" in logbook_source, "Renderer writes actionable diagnostics")
check("window.print()" not in pirep_js, "SAVE PDF never opens browser print dialog")
check("/api/logbook/${encodeURIComponent(id)}/export.pdf" in pirep_js, "SAVE PDF uses direct download endpoint")
check("settings_payload=_public_settings()" in main_source, "PDF snapshot receives current public units/settings")

# Exercise the real CDP renderer when a browser is available in the validation environment.
if lb._browser_candidates():
    rendered = lb._render_full_pirep_pdf_html(snapshot, timeout_seconds=30.0)
    check(bool(rendered and rendered.startswith(b"%PDF-") and len(rendered) > 5000), "Self-contained Full PIREP renders to a valid PDF")
else:
    passed.append("Self-contained Full PIREP browser render skipped: no local Chromium/Edge candidate")

# Weather and telemetry behavior remain unchanged.
check(decode_metar("LOWW 171200Z 00000KT CAVOK 20/10 Q1013")["flight_category"] == "VFR", "Weather still classifies VFR")
check(decode_metar("LOWW 171200Z 00000KT 6000 BKN020 20/10 Q1013")["flight_category"] == "MVFR", "Weather still classifies MVFR")
check(decode_metar("LOWW 171200Z 00000KT 3000 BKN008 20/10 Q1013")["flight_category"] == "IFR", "Weather still classifies IFR")
check(decode_metar("LOWW 171200Z 00000KT 1000 OVC003 20/10 Q1013")["flight_category"] == "LIFR", "Weather still classifies LIFR")
telemetry_source = (ROOT / "app/telemetry_provider.py").read_text(encoding="utf-8")
check("_CACHE_SECONDS = 0.18" in telemetry_source, "Telemetry polling/cache baseline remains unchanged")
check("read_position(force=False)" in telemetry_source, "SimConnect shared-session behavior remains unchanged")

# Exact release/build metadata.
version = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
update = json.loads((ROOT / "update.json").read_text(encoding="utf-8"))
check(version == {"product": "OPS ROOM", "version": "0.24.49", "build": "public-beta-release-candidate-19", "codename": "Release Gate Integrity", "channel": "release-candidate"}, "Version metadata is exact RC19")
check(update.get("version") == "0.24.49" and "RC19" in str(update.get("download_url")), "Updater metadata targets RC19")
check("OPS_ROOM_v0_24_49_Public_Beta_RC19_Windows_x64.zip" in (ROOT / "BUILD OPS ROOM COMPLETE.bat").read_text(encoding="utf-8"), "Complete build targets RC19 Windows ZIP")
check("Starting OPS ROOM v0.24.49" in (ROOT / "opsroom_launcher.py").read_text(encoding="utf-8"), "Launcher identifies v0.24.49")
check("Release Gate Integrity" in (ROOT / "tools/write_update_manifest.py").read_text(encoding="utf-8"), "Manifest writer identifies RC19 codename")
notes = (ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8")
check("Arrival completion integrity" in notes and "Fenix pushback countdown continuity" in notes and "Reliable Full PIREP PDF" in notes, "Release notes disclose all three fixes")
check("not included" in notes and "Black Box" in notes, "Deferred tester feedback is explicitly excluded")

print(json.dumps({"ok": True, "passed": len(passed), "checks": passed}, indent=2))
