from __future__ import annotations

import ast
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import gsx_remote as gsx  # noqa: E402
from app import logbook as lb  # noqa: E402
from app import settings_store as settings_store  # noqa: E402
from app.settings_store import DEFAULT_SETTINGS, _merge  # noqa: E402
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


def reset_latches(mode: str = "ARRIVAL") -> None:
    with gsx._AUTOMATION_LOCK:
        gsx._AUTOMATION.update(
            running=True,
            stage="TEST",
            detail="TEST",
            requested=[],
            requested_at={},
            history=[],
            mode=mode,
            latches={"mode": mode, "session_generation": 1},
        )
        gsx._AUTOMATION_REQUESTED_MONO.clear()
    gsx._AUTOMATION_STOP.clear()


# ---------------------------------------------------------------------------
# Frozen systems: exact RC21 package hashes. These are intentionally outside
# the three narrow service-readiness additions and must not drift.
# ---------------------------------------------------------------------------
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
}
for rel, expected in protected.items():
    check(sha(rel) == expected, f"Frozen subsystem unchanged: {rel}")

# Existing low-level service, door, pushback and Fenix mechanisms remain exact.
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

# ---------------------------------------------------------------------------
# Departure Catering / Water controls.
# ---------------------------------------------------------------------------
check(DEFAULT_SETTINGS["integrations"]["gsx_departure_catering"] is True, "Catering defaults enabled")
check(DEFAULT_SETTINGS["integrations"]["gsx_departure_water"] is True, "Water defaults enabled")
normalized = _merge(DEFAULT_SETTINGS, {"integrations": {"gsx_departure_catering": False, "gsx_departure_water": False}})
check(normalized["integrations"]["gsx_departure_catering"] is False, "Catering setting persists disabled")
check(normalized["integrations"]["gsx_departure_water"] is False, "Water setting persists disabled")
original_app_data_dir = settings_store.app_data_dir
try:
    with tempfile.TemporaryDirectory(prefix="opsroom-rc21-settings-") as tmp:
        settings_store.app_data_dir = lambda: Path(tmp)  # type: ignore[assignment]
        saved = settings_store.save_settings({"integrations": {"gsx_departure_catering": False, "gsx_departure_water": False}})
        loaded = settings_store.load_settings()
        check(saved["integrations"]["gsx_departure_catering"] is False and loaded["integrations"]["gsx_departure_catering"] is False, "Catering choice persists to settings file")
        check(saved["integrations"]["gsx_departure_water"] is False and loaded["integrations"]["gsx_departure_water"] is False, "Water choice persists to settings file")
finally:
    settings_store.app_data_dir = original_app_data_dir  # type: ignore[assignment]
raws = {"catering": 1, "refuel": 1, "water": 1}
all_plan = gsx._service_plan_for_mode("DEPARTURE", {"gsx_departure_catering": True, "gsx_departure_water": True, "gsx_departure_refuel": True}, raws, False)
no_cat = gsx._service_plan_for_mode("DEPARTURE", {"gsx_departure_catering": False, "gsx_departure_water": True, "gsx_departure_refuel": True}, raws, False)
no_water = gsx._service_plan_for_mode("DEPARTURE", {"gsx_departure_catering": True, "gsx_departure_water": False, "gsx_departure_refuel": True}, raws, False)
check(dict((name, enabled) for name, _raw, enabled in all_plan) == {"catering": True, "refuel": True, "water": True}, "Default Departure plan unchanged")
check(dict((name, enabled) for name, _raw, enabled in no_cat)["catering"] is False and dict((name, enabled) for name, _raw, enabled in no_cat)["water"] is True, "Catering disables independently")
check(dict((name, enabled) for name, _raw, enabled in no_water)["water"] is False and dict((name, enabled) for name, _raw, enabled in no_water)["catering"] is True, "Water disables independently")
host_html = (ROOT / "app/static/host.html").read_text(encoding="utf-8")
host_js = (ROOT / "app/static/host.js").read_text(encoding="utf-8")
ground_html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
ground_js = (ROOT / "app/static/opsroom.js").read_text(encoding="utf-8")
main_source = (ROOT / "app/main.py").read_text(encoding="utf-8")
check('id="groundDepartureCatering"' in ground_html, "Ground Control includes Catering control")
check('id="groundDepartureWater"' in ground_html, "Ground Control includes Water control")
check('id="hostGsxDepartureCatering"' not in host_html and 'id="hostGsxDepartureWater"' not in host_html, "Host UI no longer duplicates service controls")
check("gsx_departure_catering" not in host_js and "gsx_departure_water" not in host_js, "Host save cannot overwrite Ground Control choices")
check("saveGroundPreferences" in ground_js and "/api/ground/preferences" in ground_js, "Ground Control loads and saves both controls")
check('@app.put("/api/ground/preferences")' in main_source, "Public Ground Control preference endpoint is packaged")

# ---------------------------------------------------------------------------
# Legacy GSX passenger-target reconciliation.
# ---------------------------------------------------------------------------
legacy_originals = {
    "official_status": gsx._official_status,
    "simconnect_diagnostics": gsx.simconnect_diagnostics,
    "ensure_session": gsx._ensure_session,
    "read_value": gsx._read_value,
    "write_value": gsx._write_value,
    "invalidate": gsx._invalidate,
    "automation_record": gsx._automation_record,
}
try:
    reset_latches("DEPARTURE")
    writes: list[tuple[str, float]] = []
    value_box = {gsx.LVAR["pax_target"]: 143.0}
    gsx._official_status = lambda force=False: {"reachable": False, "ws_connected": False, "services_available": False}  # type: ignore[assignment]
    gsx.simconnect_diagnostics = lambda: {"session_connected": True, "dll_found": True}  # type: ignore[assignment]
    gsx._ensure_session = lambda diagnostics: (object(), object())  # type: ignore[assignment]
    gsx._read_value = lambda sm, name: value_box.get(name)  # type: ignore[assignment]

    def fake_write(sm: Any, name: str, value: float) -> bool:
        writes.append((name, value))
        value_box[name] = float(value)
        return True

    gsx._write_value = fake_write  # type: ignore[assignment]
    gsx._invalidate = lambda: None  # type: ignore[assignment]
    gsx._automation_record = lambda stage, detail: None  # type: ignore[assignment]
    result = gsx._legacy_gsx_passenger_target(149, force=True)
    check(result.get("ok") is True, "Legacy GSX target reconciliation succeeds")
    check(writes == [("L:FSDT_GSX_NUMPASSENGERS", 149)], "Legacy GSX writes only documented passenger target")
    check(result.get("verified") is True and result.get("readback") == 149, "Legacy GSX target is read back")
    writes.clear()
    result2 = gsx._legacy_gsx_passenger_target(149, force=True)
    check(result2.get("already_set") is True and not writes, "Matching legacy target is not rewritten")

    gsx._official_status = lambda force=False: {"reachable": True, "ws_connected": True, "services_available": False, "protocol": "official-remote-api-v2"}  # type: ignore[assignment]
    writes.clear()
    modern = gsx._legacy_gsx_passenger_target(149, force=True)
    check(modern.get("skipped") is True and modern.get("source") == "official-remote-api-v2", "Modern Remote API path is explicitly untouched")
    check(not writes, "Modern Remote API path performs no legacy LVar write")
finally:
    gsx._official_status = legacy_originals["official_status"]  # type: ignore[assignment]
    gsx.simconnect_diagnostics = legacy_originals["simconnect_diagnostics"]  # type: ignore[assignment]
    gsx._ensure_session = legacy_originals["ensure_session"]  # type: ignore[assignment]
    gsx._read_value = legacy_originals["read_value"]  # type: ignore[assignment]
    gsx._write_value = legacy_originals["write_value"]  # type: ignore[assignment]
    gsx._invalidate = legacy_originals["invalidate"]  # type: ignore[assignment]
    gsx._automation_record = legacy_originals["automation_record"]  # type: ignore[assignment]

source = (ROOT / "app/gsx_remote.py").read_text(encoding="utf-8")
request_start = source.index("def _request_fenix_loading_once")
request_end = source.index("\ndef ", request_start + 10)
request_block = source[request_start:request_end]
check(request_block.index("_legacy_gsx_passenger_target") < request_block.index("fenix_start_gsx_boarding"), "Legacy target is reconciled before unchanged Fenix task")
check('progress["passengers_target"] = authoritative_pax' in source, "Legacy status uses authoritative target immediately")
check('L:FSDT_GSX_NUMPASSENGERS' in source, "Documented GSX passenger target is packaged")
check('FSDT_GSX_NUMPASSENGERS_BOARDING_TOTAL' in source, "Existing live boarded counter remains packaged")

# ---------------------------------------------------------------------------
# Arrival-only invoice finalisation.
# ---------------------------------------------------------------------------
finalizer_originals = {
    "official_status": gsx._official_status,
    "official_command": gsx._official_command,
    "receipt_signatures": gsx._arrival_receipt_signatures,
    "invalidate": gsx._invalidate,
    "invalidate_official": gsx._invalidate_official,
    "stop_observer": gsx._stop_operator_observer,
    "automation_record": gsx._automation_record,
    "monotonic": gsx.time.monotonic,
    "sleep": gsx.time.sleep,
}
try:
    reset_latches("ARRIVAL")
    statuses = iter([
        {"reachable": True, "ws_connected": True, "protocol": "official-remote-api-v2", "gsx_running": True, "startup_active": False, "startup_sid": "old"},
        {"reachable": False, "ws_connected": False, "protocol": "official-remote-api-v2", "gsx_running": False, "startup_active": True, "startup_sid": "new"},
        {"reachable": True, "ws_connected": True, "protocol": "official-remote-api-v2", "gsx_running": True, "startup_active": False, "startup_sid": "new"},
    ])
    last_status = {"reachable": True, "ws_connected": True, "protocol": "official-remote-api-v2", "gsx_running": True, "startup_active": False, "startup_sid": "new"}

    def fake_status(force: bool = False) -> dict[str, Any]:
        nonlocal_status = next(statuses, last_status)
        return dict(nonlocal_status)

    commands: list[tuple[str, dict[str, Any] | None]] = []

    def fake_command(verb: str, args: dict[str, Any] | None = None, timeout: float = 0.95) -> dict[str, Any]:
        commands.append((verb, dict(args or {})))
        return {"ok": True, "verb": verb}

    receipt_calls = {"n": 0}

    def fake_receipts() -> set[tuple[str, str, str]]:
        receipt_calls["n"] += 1
        base = {("Handling", "old.json", "2026-07-17T20:00:00Z")}
        if receipt_calls["n"] >= 2:
            base.add(("Handling", "new.json", "2026-07-17T21:00:00Z"))
        return base

    clock = {"v": 100.0}

    def fake_monotonic() -> float:
        clock["v"] += 1.0
        return clock["v"]

    gsx._official_status = fake_status  # type: ignore[assignment]
    gsx._official_command = fake_command  # type: ignore[assignment]
    gsx._arrival_receipt_signatures = fake_receipts  # type: ignore[assignment]
    gsx._invalidate = lambda: None  # type: ignore[assignment]
    gsx._invalidate_official = lambda: None  # type: ignore[assignment]
    gsx._stop_operator_observer = lambda: None  # type: ignore[assignment]
    gsx._automation_record = lambda stage, detail: None  # type: ignore[assignment]
    gsx.time.monotonic = fake_monotonic  # type: ignore[assignment]
    gsx.time.sleep = lambda seconds: None  # type: ignore[assignment]

    check(gsx._finalize_arrival_handling_invoice() is True, "Remote API Arrival invoice finalisation completes")
    check(commands[0] == ("command.run", {"command": "RESTART_COUATL"}), "Arrival finalisation sends documented Couatl restart")
    check(("handler.set", {"target": "gate", "name": "autoSelectOperator", "value": False}) in commands, "Operator popup preference is restored after restart")
    check(bool(gsx._get_latch("arrival_invoice_finalized")), "Arrival session is latched finalised")
    initial_command_count = len(commands)
    check(gsx._finalize_arrival_handling_invoice() is True and len(commands) == initial_command_count, "Arrival invoice finalisation is one-shot")

    # Legacy installations must never receive guessed keyboard/menu restart input.
    reset_latches("ARRIVAL")
    commands.clear()
    gsx._official_status = lambda force=False: {"reachable": False, "ws_connected": False, "protocol": "official-remote-api-v2"}  # type: ignore[assignment]
    check(gsx._finalize_arrival_handling_invoice() is True, "Legacy Arrival completes with manual invoice instruction")
    check(bool(gsx._get_latch("arrival_invoice_manual_required")), "Legacy manual invoice latch is set")
    check(not commands, "Legacy GSX receives no unsafe restart command")
finally:
    gsx._official_status = finalizer_originals["official_status"]  # type: ignore[assignment]
    gsx._official_command = finalizer_originals["official_command"]  # type: ignore[assignment]
    gsx._arrival_receipt_signatures = finalizer_originals["receipt_signatures"]  # type: ignore[assignment]
    gsx._invalidate = finalizer_originals["invalidate"]  # type: ignore[assignment]
    gsx._invalidate_official = finalizer_originals["invalidate_official"]  # type: ignore[assignment]
    gsx._stop_operator_observer = finalizer_originals["stop_observer"]  # type: ignore[assignment]
    gsx._automation_record = finalizer_originals["automation_record"]  # type: ignore[assignment]
    gsx.time.monotonic = finalizer_originals["monotonic"]  # type: ignore[assignment]
    gsx.time.sleep = finalizer_originals["sleep"]  # type: ignore[assignment]

cycle_start = source.index("def _automation_cycle")
cycle_end = source.index("\ndef _pushback_direction_menu_visible", cycle_start)
cycle = source[cycle_start:cycle_end]
check('if mode == "ARRIVAL":\n            return _finalize_arrival_handling_invoice()' in cycle, "Automatic restart is confined to Arrival mode")
check("FULL_TURNAROUND" in cycle and 'if mode == "ARRIVAL"' in cycle, "Full Turnaround continues without invoice restart")
check('"arrival_invoice_finalization_started": False' in source and '"arrival_invoice_finalized": False' in source, "Invoice latches reset for every service session")

# ---------------------------------------------------------------------------
# RC19 release-gate protections remain present.
# ---------------------------------------------------------------------------
reset_latches("ARRIVAL")
requested_snap = {"provider": "remote-v2", "services": {"cleaning": {"remote_state": "requested", "source": "official-remote-api-v2"}}, "progress": {}}
check(gsx._arrival_service_complete_current(requested_snap, "cleaning", 1) is False, "Requested Cleaning remains pending")
check(gsx._maybe_defer_unavailable_arrival_service(requested_snap, "cleaning", 1) is False, "Active Cleaning cannot be timeout-skipped")
performing_snap = {"provider": "remote-v2", "services": {"cleaning": {"remote_state": "performing", "source": "official-remote-api-v2"}}, "progress": {}}
check(gsx._arrival_service_complete_current(performing_snap, "cleaning", 5) is False, "Performing Cleaning blocks Arrival completion")
completed_snap = {"provider": "remote-v2", "services": {"cleaning": {"remote_state": "completed", "source": "official-remote-api-v2"}}, "progress": {}}
check(gsx._arrival_service_complete_current(completed_snap, "cleaning", 6) is True, "Completed Cleaning closes on terminal state")

monotonic_marker = 'if _get_latch("fenix_targets_complete") and _get_latch("fenix_pushback_armed_after_loading"):'
boarding_gate = "_boarding_service_complete_from_snapshot"
check(monotonic_marker in cycle, "Monotonic Fenix completion branch remains packaged")
check(cycle.index(monotonic_marker) < cycle.index(boarding_gate), "Armed pushback timer precedes regressed passenger validation")
check('_coordinate_verified_pushback_handoff(snap)' in cycle, "Existing verified pushback handoff remains in use")
check('60.0 - (time.monotonic() - float(armed_at))' in cycle, "Pushback countdown remains exactly 60 seconds")

# Direct Full PIREP PDF path and renderer remain intact.
html_template = (ROOT / "app/static/pirep.html").read_text(encoding="utf-8")
logbook_source = (ROOT / "app/logbook.py").read_text(encoding="utf-8")
pirep_js = (ROOT / "app/static/pirep.js").read_text(encoding="utf-8")
check('pirep.css?v=0-24-51-rc21' in html_template and 'pirep.js?v=0-24-51-rc21' in html_template, "Full PIREP page targets RC21 assets")
check('"about:blank"' in logbook_source and "Page.setDocumentContent" in logbook_source, "Self-contained PDF renderer remains packaged")
check("Page.printToPDF" in logbook_source and "max_size=None" in logbook_source, "Full PIREP direct renderer remains large-response safe")
check("pirep-pdf-renderer.log" in logbook_source, "PDF renderer diagnostics remain packaged")
print_css = (ROOT / "app/static/pirep_print.css").read_text(encoding="utf-8")
print_js = (ROOT / "app/static/pirep_print.js").read_text(encoding="utf-8")
check("297mm" in print_css and "210mm" in print_css and "pdf-page" in print_css, "Dedicated fixed A4 landscape report layout is packaged")
check("window.__OPSROOM_PDF_READY__" in print_js and "pdf-source-${source.id}" in print_js, "Dedicated master-report pagination is packaged")
check("window.print()" not in pirep_js, "SAVE PDF never opens browser print dialog")
check("/api/logbook/${encodeURIComponent(id)}/export.pdf" in pirep_js, "SAVE PDF keeps direct endpoint")

old_get_entry = lb.get_entry
old_telemetry = lb.telemetry
try:
    lb.get_entry = lambda _entry_id: {
        "id": "rc21-pdf-test",
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
    snapshot = lb._pirep_snapshot_html("rc21-pdf-test", {"interface": {"units": "metric"}})
finally:
    lb.get_entry = old_get_entry  # type: ignore[assignment]
    lb.telemetry = old_telemetry  # type: ignore[assignment]
check("window.__OPSROOM_PIREP_PRELOADED__=" in snapshot, "PDF snapshot injects selected Full PIREP data")
check('<link rel="stylesheet" href="/static/pirep.css' not in snapshot, "PDF snapshot inlines master PIREP CSS")
check('<script src="/static/pirep.js' not in snapshot, "PDF snapshot inlines master PIREP JavaScript")
if lb._browser_candidates():
    rendered = lb._render_full_pirep_pdf_html(snapshot, timeout_seconds=30.0)
    check(bool(rendered and rendered.startswith(b"%PDF-") and len(rendered) > 5000), "Self-contained master Full PIREP renders to valid PDF")
else:
    passed.append("Self-contained master Full PIREP browser render skipped: no Chromium/Edge candidate")

# Weather and telemetry are deliberately unchanged for release safety.
check(decode_metar("LOWW 171200Z 00000KT CAVOK 20/10 Q1013")["flight_category"] == "VFR", "Weather classifies VFR")
check(decode_metar("LOWW 171200Z 00000KT 6000 BKN020 20/10 Q1013")["flight_category"] == "MVFR", "Weather classifies MVFR")
check(decode_metar("LOWW 171200Z 00000KT 3000 BKN008 20/10 Q1013")["flight_category"] == "IFR", "Weather classifies IFR")
check(decode_metar("LOWW 171200Z 00000KT 1000 OVC003 20/10 Q1013")["flight_category"] == "LIFR", "Weather classifies LIFR")
telemetry_source = (ROOT / "app/telemetry_provider.py").read_text(encoding="utf-8")
check("_CACHE_SECONDS = 0.18" in telemetry_source, "Telemetry cache rate remains frozen")
check("read_position(force=False)" in telemetry_source, "SimConnect shared-session behavior remains frozen")

# ---------------------------------------------------------------------------
# Release metadata and scope.
# ---------------------------------------------------------------------------
version = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
update = json.loads((ROOT / "update.json").read_text(encoding="utf-8"))
check(version == {"product": "OPS ROOM", "version": "0.24.51", "build": "public-beta-release-candidate-21", "codename": "Master PIREP Export", "channel": "release-candidate"}, "Version metadata is exact RC21")
check(update.get("version") == "0.24.51" and "RC21" in str(update.get("download_url")), "Updater metadata targets RC21")
check("OPS_ROOM_v0_24_51_Public_Beta_RC21_Windows_x64.zip" in (ROOT / "BUILD OPS ROOM COMPLETE.bat").read_text(encoding="utf-8"), "Complete build targets RC21 Windows ZIP")
check("Starting OPS ROOM v0.24.51" in (ROOT / "opsroom_launcher.py").read_text(encoding="utf-8"), "Launcher identifies v0.24.51")
check("Master PIREP Export" in (ROOT / "tools/write_update_manifest.py").read_text(encoding="utf-8"), "Manifest writer identifies RC21 codename")
notes = (ROOT / "OPS_ROOM_v0_24_51_RC21_RELEASE_NOTES.md").read_text(encoding="utf-8")
check("Ground Control service options" in notes and "Departure Catering" in notes and "Potable Water" in notes, "Release notes include relocated service toggles")
check("Legacy GSX passenger-target reconciliation" in notes, "Release notes retain legacy passenger fix")
check("Automatic Arrival-only Couatl restart" in notes, "Release notes retain Arrival invoice finalisation")
check("Black Box/flight-replay module" in notes and "v0.24.100" in notes, "Black Box work is assigned to the separate preview")
check("telemetry" in notes.lower() and "unchanged" in notes.lower(), "Telemetry release scope is explicit")

print(json.dumps({"ok": True, "passed": len(passed), "checks": passed}, indent=2))
