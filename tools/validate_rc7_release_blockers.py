from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import announcements as ann  # noqa: E402
from app import telemetry_provider as tel  # noqa: E402
from app import logbook as logbook  # noqa: E402

passed: list[str] = []


def check(condition: bool, name: str) -> None:
    if not condition:
        raise AssertionError(name)
    passed.append(name)


# 1-4: literal announcement events and contextual variants.
ann._aircraft_variant = lambda: "A320"  # type: ignore
ann._local_daypart = lambda _event: "Afternoon"  # type: ignore
ann._refueling_active = lambda: False  # type: ignore
files = [
    Path("AfterTakeoff[Afternoon][1].ogg"),
    Path("AfterTakeoff[Afternoon][2].ogg"),
    Path("AfterTakeoff[Morning].ogg"),
    Path("CrewSeatsTakeoff.ogg"),
]
selected = ann._compatible_event_files("AfterTakeoff", files)
check({p.name for p in selected} == {"AfterTakeoff[Afternoon][1].ogg", "AfterTakeoff[Afternoon][2].ogg"}, "AfterTakeoff variants stay within exact base event")
check(all(not p.name.startswith("CrewSeatsTakeoff") for p in selected), "CrewSeatsTakeoff can never substitute for AfterTakeoff")

aircraft_files = [Path("PreSafetyBriefing[1][A319].ogg"), Path("PreSafetyBriefing[1][A320].ogg"), Path("PreSafetyBriefing[2][A320].ogg")]
selected = ann._compatible_event_files("PreSafetyBriefing", aircraft_files)
check({p.name for p in selected} == {"PreSafetyBriefing[1][A320].ogg", "PreSafetyBriefing[2][A320].ogg"}, "Aircraft-specific selection prefers detected A320")

ann._refueling_active = lambda: True  # type: ignore
refuel_files = [Path("BoardingWelcome[Afternoon].ogg"), Path("BoardingWelcome[Refueling].ogg")]
selected = ann._compatible_event_files("BoardingWelcome", refuel_files)
check([p.name for p in selected] == ["BoardingWelcome[Refueling].ogg"], "Refueling welcome is preferred only while refueling is active")


ann._refueling_active = lambda: False  # type: ignore
ann._local_daypart = lambda _event: "Morning"  # type: ignore
numbered = [
    Path("AfterLanding[Morning][1].ogg"),
    Path("AfterLanding[Morning][2].ogg"),
    Path("AfterLanding[Evening][1].ogg"),
    Path("CrewSeatsLanding[Morning][1].ogg"),
]
selected = ann._compatible_event_files("AfterLanding", numbered)
check({p.name for p in selected} == {"AfterLanding[Morning][1].ogg", "AfterLanding[Morning][2].ogg"}, "Daypart filtering retains all equivalent numbered variants for random choice")
check("_EVENT_ALIASES" not in (ROOT / "app" / "announcements.py").read_text(encoding="utf-8"), "Cross-event announcement alias table is removed")

# 5-8: GSX pushback must be performing/completing, never available/requested/text noise.
from app import gsx_remote  # noqa: E402
original_status = gsx_remote.status
try:
    def set_status(raw: int, state: str):
        gsx_remote.status = lambda force=False: {"ok": True, "connected": True, "services": {"pushback": {"raw": raw, "state": state}, "departure": {"raw": 0, "state": ""}}}  # type: ignore

    set_status(1, "Pushback available")
    check(not ann._gsx_pushback_active_status(), "GSX raw 1 AVAILABLE is not pushback movement")
    set_status(4, "Pushback requested")
    check(not ann._gsx_pushback_active_status(), "GSX raw 4 REQUESTED is not physical movement")
    set_status(5, "Performing")
    check(ann._gsx_pushback_active_status(), "GSX raw 5 PERFORMING is active pushback")
    set_status(7, "Completing")
    check(ann._gsx_pushback_active_status(), "GSX raw 7 COMPLETING remains active pushback")
finally:
    gsx_remote.status = original_status

original_status = gsx_remote.status
try:
    gsx_remote.status = lambda force=False: {"ok": True, "connected": True, "services": {"pushback": {"raw": 4, "state": "REQUESTED"}, "departure": {"raw": 0, "state": ""}}}  # type: ignore
    check(not logbook._gsx_pushback_active(), "Recorder does not treat a requested pushback as physical movement")
    gsx_remote.status = lambda force=False: {"ok": True, "connected": True, "services": {"pushback": {"raw": 5, "state": "PERFORMING"}, "departure": {"raw": 0, "state": ""}}}  # type: ignore
    check(logbook._gsx_pushback_active(), "Recorder recognizes performing pushback")
finally:
    gsx_remote.status = original_status

ann._BOARDING_MOVEMENT_SAMPLES = 0
check(not ann._confirmed_departure_movement(False, True, 2.0), "One noisy movement sample does not stop boarding audio")
check(not ann._confirmed_departure_movement(False, True, 2.0), "Two movement samples remain unconfirmed")
check(ann._confirmed_departure_movement(False, True, 2.0), "Three sustained movement samples confirm departure movement")
ann._BOARDING_MOVEMENT_SAMPLES = 0
check(ann._confirmed_departure_movement(True, True, 0.0), "Authoritative performing pushback confirms movement without GS noise")

# 9-15: telemetry conditioning and FSUIPC freshness signals.
tel._FILTER_HISTORY.clear(); tel._FILTER_LAST.clear(); tel._FILTER_LAST_AT.clear()
base = {
    "ok": True, "source": "fsuipc7", "sampled_monotonic": 1.0,
    "lat": 50.0, "lon": 8.0, "altitude_ft": 100.0, "indicated_altitude_ft": 100.0,
    "agl_ft": 9.0, "radio_altitude_ft": 9.0, "ground_speed_kts": 0.4,
    "indicated_speed_kts": 0.0, "vertical_speed_fpm": 20.0,
    "heading_deg": 359.0, "track_deg": 359.0, "pitch_deg": 0.0,
    "bank_deg": 0.0, "g_force": 1.0, "on_ground": True,
}
tel._condition_sample(base, "test")
conditioned = tel._condition_sample({**base, "sampled_monotonic": 1.2, "lat": 50.00001, "lon": 8.00001, "ground_speed_kts": 0.6, "vertical_speed_fpm": -30.0, "heading_deg": 1.0}, "test")
check(conditioned["ground_speed_kts"] == 0.0, "Stationary FSUIPC ground-speed noise is deadbanded to zero")
check(conditioned["lat"] == 50.0 and conditioned["lon"] == 8.0, "Stationary position jitter is held")
check(conditioned["vertical_speed_fpm"] == 0.0, "Small vertical-speed noise is level-flight deadbanded")
check(conditioned["raw_ground_speed_kts"] == 0.6 and conditioned["raw_vertical_speed_fpm"] == -30.0, "Raw touchdown-sensitive channels are preserved")
check(0.0 <= conditioned["heading_deg"] < 360.0, "Circular heading filter handles 359/1 wrap")

spike = tel._condition_sample({**base, "sampled_monotonic": 1.4, "altitude_ft": 12000.0, "indicated_altitude_ft": 12000.0, "vertical_speed_fpm": 0.0}, "test")
check(spike["altitude_ft"] < 1000.0, "One-frame altitude spike is rejected")

fp1 = tel._fingerprint({**base, "simulator_elapsed_seconds": 10.0})
fp2 = tel._fingerprint({**base, "simulator_elapsed_seconds": 10.0, "lat": 50.0000001, "ground_speed_kts": 0.45, "vertical_speed_fpm": 22.0})
fp3 = tel._fingerprint({**base, "simulator_elapsed_seconds": 10.2})
check(fp1 == fp2, "Tiny numeric jitter cannot fake telemetry freshness")
check(fp1 != fp3, "FSUIPC elapsed simulated seconds proves the simulator advanced")

telemetry_source = (ROOT / "app" / "telemetry_provider.py").read_text(encoding="utf-8")
for token in ("0x04A8", "0x0588", "0x3364", "0x3365"):
    check(token in telemetry_source, f"Documented FSUIPC freshness offset {token} is read")
check('rounded("heading_deg", 0)' in telemetry_source and 'rounded("heading",' not in telemetry_source, "Freshness fingerprint uses the correct heading_deg key")

# 16-19: UI/presentation regression guards.
js = (ROOT / "app" / "static" / "opsroom.js").read_text(encoding="utf-8")
css = (ROOT / "app" / "static" / "opsroom.css").read_text(encoding="utf-8")
check("rankInsignia" in js and "rankBars" not in js and "▰" not in js, "Crude text rank bars are removed")
check("rank-insignia" in css and "flex-direction:column" in css, "Vertical epaulette rank ladder is present")
check("font-weight:400" in css and "font-weight:600" in css, "Finance secondary typography no longer uses excessive bold")
check('data-announcement="AfterLanding"' in (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8"), "After-landing manual control uses the literal event name")

# 20-21: logbook keeps raw touchdown peaks while storing conditioned operational data.
logbook_source = (ROOT / "app" / "logbook.py").read_text(encoding="utf-8")
check("raw_vertical_speed_fpm" in logbook_source and "raw_g_force" in logbook_source, "Recorder preserves raw touchdown VS and G channels")
check("raw_ground_speed_kts" in logbook_source and "raw_radio_altitude_ft" in logbook_source, "Recorder preserves raw touchdown speed and radio-altitude channels")


# RC7 departure completion: bags/cargo completion cannot impersonate passenger boarding.
original_age = gsx_remote._fenix_loading_age_s
try:
    gsx_remote._fenix_loading_age_s = lambda: 60.0  # type: ignore
    progress = {"passengers_boarding_total": 24, "passengers_target": 156, "boarding_cargo_percent": 100}
    fenix = {
        "pax_loaded": 24, "pax_target": 156,
        "fuel_loaded_kg": 5900, "fuel_target_kg": 5900,
        "cargo_loaded_kg": 1800, "cargo_target_kg": 1800,
        "aircraft_loaded": True,
    }
    check(not gsx_remote._fenix_authoritative_complete(progress, fenix), "Bags 100 percent cannot complete passenger boarding")
    complete_snap = {"services": {"boarding": {"raw": 5, "remote_state": "performing", "progress_text": "pax 24/156 · bags 100%"}}, "progress": progress}
    check(not gsx_remote._boarding_service_complete_from_snapshot(complete_snap), "Performing boarding with pax below target remains incomplete")
    progress_done = {**progress, "passengers_boarding_total": 156}
    fenix_done = {**fenix, "pax_loaded": 156}
    check(gsx_remote._fenix_authoritative_complete(progress_done, fenix_done), "Passenger cargo and fuel completion authorizes departure handoff")
finally:
    gsx_remote._fenix_loading_age_s = original_age

# RC7 receipt matching: operational window, registration/airport identity and local currency support.
from app import gsx_receipts  # noqa: E402
from app import economy  # noqa: E402
import os
from datetime import datetime, timezone, timedelta
old_appdata = os.environ.get("APPDATA")
with tempfile.TemporaryDirectory() as td:
    os.environ["APPDATA"] = td
    receipt_dir = Path(td) / "Virtuali" / "GSX" / "Receipts" / "Catering"
    receipt_dir.mkdir(parents=True)
    stamp = "20260715T131802Z"
    receipt_path = receipt_dir / f"{stamp}_LXGB_G-EUYY.json"
    receipt_path.write_text(json.dumps({
        "version": 1,
        "operator": "Air Culinaire Worldwide",
        "airline": "British Airways P.L.C.",
        "icao": "LXGB",
        "tail": "G-EUYY",
        "aircraftType": "A320",
        "total": "GI£165.36 (~US$218.40)",
        "items": [{"description": "Catering service", "amount": "GI£165.36"}],
    }), encoding="utf-8")
    invoices = gsx_receipts.recent_invoice_items(
        "2026-07-15T13:27:00Z", "2026-07-15T15:00:00Z",
        takeoff_utc="2026-07-15T13:40:00Z", origin="LXGB", destination="LEPA", tail="G-EUYY",
    )
    check(len(invoices) == 1 and invoices[0].get("phase") == "departure", "Pre-recorder departure receipt matches the operational service window")
    check(invoices[0].get("currency") == "GIP" and invoices[0].get("approx_currency") == "USD", "GI pound receipt preserves GIP and USD reference currencies")
    converted = economy._invoice_in_career_currency(invoices[0], "EUR")
    check(bool(converted and converted.get("amount", 0) > 0), "Local-currency GSX receipt converts through its audited USD reference")
if old_appdata is None:
    os.environ.pop("APPDATA", None)
else:
    os.environ["APPDATA"] = old_appdata

# RC7 provider recovery: SimConnect startup fallback must not become permanent.
original_read_fsuipc = tel._read_fsuipc
original_complete = tel._complete_snapshot
original_fresh = tel._assess_fsuipc_freshness
original_contradicts = tel._contradicts
try:
    sample = {**base, "ok": True, "source": "fsuipc7", "sampled_monotonic": 10.0, "simulator_elapsed_seconds": 50.0}
    tel._read_fsuipc = lambda: dict(sample)  # type: ignore
    tel._complete_snapshot = lambda row, source: (True, "")  # type: ignore
    tel._assess_fsuipc_freshness = lambda row, now: (True, 0.0, {}, False)  # type: ignore
    tel._contradicts = lambda f, s: False  # type: ignore
    tel._SOURCE_LOCK = "simconnect"
    tel._FAILOVER_ACTIVE = False
    tel._FSUIPC_RECOVERY_SINCE = 0.0
    tel._FSUIPC_RECOVERY_GOOD_SAMPLES = 0
    tel._FSUIPC_BACKGROUND_PROBE_AFTER = 0.0
    check(tel._probe_preferred_fsuipc({}, 100.0, force=True) is None, "One healthy FSUIPC probe does not flap providers")
    check(tel._probe_preferred_fsuipc({}, 104.0, force=True) is None, "FSUIPC recovery requires a stable hold")
    recovered = tel._probe_preferred_fsuipc({}, 109.0, force=True)
    check(bool(recovered and recovered.get("source") == "fsuipc7" and tel._SOURCE_LOCK == "fsuipc7"), "Healthy FSUIPC automatically replaces temporary SimConnect")
finally:
    tel._read_fsuipc = original_read_fsuipc
    tel._complete_snapshot = original_complete
    tel._assess_fsuipc_freshness = original_fresh
    tel._contradicts = original_contradicts

main_source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
status_source = (ROOT / "app" / "system_status.py").read_text(encoding="utf-8")
check('/api/telemetry/reselect' in main_source, "Dedicated telemetry reselection endpoint is available")
check('reselect_telemetry("Status Board reconnect")' in status_source, "Status Board reconnect performs genuine provider reselection")
check('.reverse()' in js and 'flex-direction:column' in css, "Rank ladder renders vertically from highest to lowest")
check('No matching GSX receipts' not in (ROOT / 'RELEASE_NOTES.md').read_text(encoding='utf-8'), "Cumulative release notes remain user-facing")

print(json.dumps({"ok": True, "passed": len(passed), "checks": passed}, indent=2))
