from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import briefing_data as bd
from app import gsx_remote as g
from app import logbook as lb

passed: list[str] = []

def check(condition, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    passed.append(label)


def source_hash(path: Path, function_name: str) -> str:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    node = next(
        item for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == function_name
    )
    segment = ast.get_source_segment(text, node) or ""
    return hashlib.sha256(segment.encode("utf-8")).hexdigest()

# Frozen RC14 service orchestration functions remain source-identical.
expected_functions = {
    "_request_once": "487c6b030bcb6bf3fb112ccc029942a8ad96412bab079a4a9d91b856ee1d2e98",
    "_service_plan_for_mode": "27a8c9c348efbb14809dc0efcf328c133bea59a5257395db3bd648860ba8747b",
    "_automation_cycle": "dfa827ca8e2ae45eab51e619155c87c65ab2144aa892b1565f9ea657a27f5f3c",
    "_request_fenix_loading_once": "1b5c4610e13255c5b0a274b4495e761fed7f84e50c97e64806053aaac4ef3d7c",
    "_fenix_authoritative_complete": "0d74348284bc847b3e7842ed4dfd118f9ab3559180a8cbb8ccd7002c71b2225a",
    "_apply_fenix_boarding_decision": "cb1c065b9a0c94516f5b1d540aee4a0e0089fe8086f3c0131152e0f69f83a885",
    "_coordinate_arrival_fenix_deboarding": "cba21df1801963f992c8e14aff8ef2ee01c40c7d7786a041aedc7e8f12590652",
    "_coordinate_arrival_cargo_doors": "cdcf2d025d268e9ab4a9cf15b74e114d8f21fe1911da908135d1801d81a87e1c",
}
for name, expected in expected_functions.items():
    check(source_hash(ROOT / "app/gsx_remote.py", name) == expected, f"Frozen RC14 service function is unchanged: {name}")

# Entire protected subsystems remain byte-identical to RC14.
frozen_files = {
    "app/fenix_adapter.py": "7a9597f65ea8f0e6e67f839fb607630faa4181d3bf725dd2160d1fc854571f46",
    "app/fenix_gsx_loading_state_machine.py": "6a9fc247e785228c210a3f2a3942925e29d1d744e9ce9a583f3dfaa495c0d2cd",
    "app/announcements.py": "721f55088def610f5d66e5dddd3a00123a86ccba10e4f2c2d654dedd1284da1b",
    "app/telemetry_provider.py": "0c921fe33d076d68db66d479bb3db5388c844924924d7995358bdafe21c91de8",
    "app/pirep_analysis.py": "a544897546cdbf03b2cb8d4e6d02a03b6c35b9e13f7d5a508e00f36ac63a6c3a",
    "app/gsx_receipts.py": "1af0c10b24f5e9acf28f951e49681f4faef92be4a6dc156ca5497191829a8e28",
    "app/economy.py": "7c65910e4807871fdf5ba922144c1af7f4e13ab23ff805e62170da273e702f87",
    "app/settings_store.py": "0bd2117c4a8412d113047514986f06e8552bc3508b91ef834cdce3d5aa26af05",
    "app/raas.py": "7e808122ebd1f8c6301421b28a0ca84585426b9d730bb9506408d99ee5e6578b",
}
for rel, expected in frozen_files.items():
    actual = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
    check(actual == expected, f"Frozen RC14 subsystem is unchanged: {rel}")

# TAXI OUT is not held by stale GSX COMPLETING, but physical PERFORMING still holds pushback.
old_status = g.status
try:
    g.status = lambda force=False: {"ok": True, "connected": True, "services": {"pushback": {"raw": 7, "state": "COMPLETING", "status_text": "Pushback completing"}}}
    check(lb._gsx_pushback_active() is False, "Stale GSX COMPLETING does not indefinitely hold PUSHBACK")
    g.status = lambda force=False: {"ok": True, "connected": True, "services": {"pushback": {"raw": 5, "state": "PERFORMING", "status_text": "Pushback in progress"}}}
    check(lb._gsx_pushback_active() is True, "Physical GSX PERFORMING still holds PUSHBACK")
finally:
    g.status = old_status
logbook_source = (ROOT / "app/logbook.py").read_text(encoding="utf-8")
check("float(gs or 0.0) >= 3.0" in logbook_source and "elapsed >= 5.0" in logbook_source and "distance_nm >= 0.010" in logbook_source, "Hybrid TAXI OUT uses sustained speed, delay and meaningful displacement")

# Exercise the real analyser: a first moving sample must remain PUSHBACK, while
# sustained forward movement with meaningful displacement must become TAXI OUT.
original_pushback_reader = lb._gsx_pushback_active
try:
    lb._gsx_pushback_active = lambda: False
    taxi_meta = {
        "flight": {},
        "times": {"block_out": None, "takeoff": None, "landing": None, "block_in": None},
        "fuel": {}, "metrics": {}, "events": [], "violations": [],
        "_state": {
            "phase": "PUSHBACK", "pushback_active": True, "pushback_seen": True,
            "recent_samples": [], "fuel_used_accum_lb": 0.0,
        },
    }
    first = {
        "time": "2026-07-17T09:31:00Z", "source": "validator",
        "on_ground": True, "ground_safe": True, "parking_brake": False,
        "ground_speed_kts": 4.0, "lat": 48.1000, "lon": 16.5000,
        "vertical_speed_fpm": 0.0, "agl_ft": 0.0, "fuel_total_lb": 10000.0,
        "engines_running": True,
    }
    lb._analyse(taxi_meta, first, None)
    check(first.get("phase") == "PUSHBACK", "A brief initial movement sample does not prematurely end PUSHBACK")
    second = dict(first)
    second.update({"time": "2026-07-17T09:31:06Z", "lon": 16.5003})
    lb._analyse(taxi_meta, second, first)
    check(second.get("phase") == "TAXI OUT" and taxi_meta["_state"].get("pushback_completed") is True, "Sustained forward movement transitions the real recorder from PUSHBACK to TAXI OUT")
finally:
    lb._gsx_pushback_active = original_pushback_reader

# Arrival cargo doors arm for 120 seconds and close only after the deadline.
originals = {
    "mode": g._arrival_mode_active,
    "bags": g._arrival_bags_complete,
    "get": g._get_latch,
    "set": g._set_latch,
    "close": g._close_fenix_cargo_doors_once,
    "mono": g.time.monotonic,
    "record": g._automation_record,
}
latches = {"arrival_cargo_doors_closed_once": False, "arrival_cargo_doors_close_due_mono": 0.0}
closed: list[tuple[str, str]] = []
clock = {"now": 1000.0}
try:
    g._arrival_mode_active = lambda: True
    g._arrival_bags_complete = lambda _snap, _raw: True
    g._get_latch = lambda key, default=None: latches.get(key, default)
    g._set_latch = lambda key, value: latches.__setitem__(key, value)
    g._close_fenix_cargo_doors_once = lambda latch, reason: closed.append((latch, reason))
    g.time.monotonic = lambda: clock["now"]
    g._automation_record = lambda *_args, **_kwargs: None
    g._coordinate_arrival_cargo_doors_closed({}, 6)
    check(latches["arrival_cargo_doors_close_due_mono"] == 1120.0 and not closed, "Arrival cargo-door close arms a two-minute timer")
    clock["now"] = 1119.9; g._coordinate_arrival_cargo_doors_closed({}, 6)
    check(not closed, "Arrival cargo doors remain open before the two-minute deadline")
    clock["now"] = 1120.0; g._coordinate_arrival_cargo_doors_closed({}, 6)
    check(len(closed) == 1 and closed[0][0] == "arrival_cargo_doors_closed_once", "Arrival cargo doors close once at the two-minute deadline")
finally:
    g._arrival_mode_active = originals["mode"]
    g._arrival_bags_complete = originals["bags"]
    g._get_latch = originals["get"]
    g._set_latch = originals["set"]
    g._close_fenix_cargo_doors_once = originals["close"]
    g.time.monotonic = originals["mono"]
    g._automation_record = originals["record"]

# Austrian matching uses live SimBrief identity and actual current menu index.
menu = {
    "available": True,
    "entries": ["Aerogate", "Austrian Airlines", "Lufthansa", "Back"],
    "disabled": [False, False, False, False],
    "icon_wide": [True, True, True, False],
    "title": "Select company",
}
choice = g._operator_observer_choice(menu, {"airline": "Austrian Airlines", "callsign": "AUA101"})
check(bool(choice and choice["index"] == 1 and choice["label"] == "Austrian Airlines"), "Austrian is selected from the latest live menu index")
gsx_source = (ROOT / "app/gsx_remote.py").read_text(encoding="utf-8")
check('"handler.set"' in gsx_source and '"autoSelectOperator"' in gsx_source and '"value": False' in gsx_source, "Operator observer asks GSX to expose the live operator popup")
check('pending.get("kind") == "handler_set"' in gsx_source and 'pending.get("kind")' in gsx_source, "Handler writes and menu picks use correlated command results")

# Flight-specific Briefing remains scoped to the current SimBrief route and
# retains a text fallback when the cached PDF is temporarily unavailable.
plan = {
    "ok": True, "callsign": "AUA101", "route": "LOWW DCT LOWI",
    "origin": {"icao": "LOWW"}, "destination": {"icao": "LOWI"}, "alternate": {"icao": "EDDM"},
    "navlog": [{"type": "FIR", "ident": "LOVV"}],
    "files": {"plan_text": """
[ NOTAM ]
A1234/26
A) LOWW
E) RWY 11/29 CLSD

B2345/26
A) LOWI
E) ILS RWY 26 U/S

SIGMETs:
LOVV SIGMET 2 VALID 170900/171300 LOWW- LOVV WI TS OBS

Departure:
LOWW
"""},
}
original_bd = (bd._current_plan, bd._pdf_path, bd._autorouter_notams, bd._awc_sigmets)
try:
    bd._CACHE = None; bd._CACHE_MONO = 0.0
    bd._current_plan = lambda: plan
    bd._pdf_path = lambda _plan: None
    bd._autorouter_notams = lambda ids: ([], None)
    bd._awc_sigmets = lambda ids: ([], {"name": "NOAA Aviation Weather Center", "state": "empty", "count": 0})
    result = bd.operational_briefing(force=True)
    check(result["ok"] and {"LOWW", "LOWI", "EDDM", "LOVV"}.issubset(set(result["flight"]["identifiers"])), "Briefing is scoped to OFP airports and crossed FIRs")
    check(any("LOWW" in row["text"] for row in result["notams"]), "Briefing retains SimBrief text NOTAM fallback")
    check(isinstance(result["sigwx"].get("charts"), list), "Briefing exposes structured SIGWX chart metadata")
finally:
    bd._current_plan, bd._pdf_path, bd._autorouter_notams, bd._awc_sigmets = original_bd
    bd._CACHE = None; bd._CACHE_MONO = 0.0

# Full PIREP is the PDF master and all interactive charts have dynamic zoom metadata.
pirep_js = (ROOT / "app/static/pirep.js").read_text(encoding="utf-8")
pirep_css = (ROOT / "app/static/pirep.css").read_text(encoding="utf-8")
main_source = (ROOT / "app/main.py").read_text(encoding="utf-8")
check("_render_full_pirep_pdf" in logbook_source and "?pdf_render=1" in main_source, "PDF endpoint prints the Full PIREP browser page")
check("downloadPirepPdf" in pirep_js and "/api/logbook/${encodeURIComponent(id)}/export.pdf" in pirep_js, "Full PIREP SAVE PDF downloads the master browser-rendered report directly")
check("Never silently substitute the old per-flight PDF" in logbook_source and "raise RuntimeError(\"Full PIREP PDF renderer unavailable" in logbook_source, "Per-flight PDF never falls back to the obsolete report generator")
check("document.documentElement.dataset.pirepReady='1'" in pirep_js and "pdf-render" in pirep_css, "Full PIREP exposes a deterministic browser-print render state")
check("visibleRowsForX" in pirep_js and "secondVisible=visibleRowsForX" in pirep_js, "Zoom recalculates primary and secondary Y-axis ranges from visible data")
check("canvas._opsChartRows={rows:allXY" in pirep_js and "zoomedXExtent('routeChart'" in pirep_js, "Route graph participates in the same zoom and reset system")

# Briefing navigation and new API are packaged.
ops_js = (ROOT / "app/static/opsroom.js").read_text(encoding="utf-8")
for label in ("overview", "weather", "notams", "hazards", "sigwx", "charts", "ofp"):
    check(f"['{label}'" in ops_js or f",['{label}'" in ops_js, f"Briefing includes {label.upper()} section")
check('/api/briefing/operational' in main_source, "Operational briefing endpoint is registered")

version = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
check(version["version"] == "0.24.48" and version["build"].endswith("18"), "Version metadata is v0.24.48 RC18")
check("OPS_ROOM_v0_24_48_Public_Beta_RC18_Windows_x64.zip" in (ROOT / "BUILD OPS ROOM COMPLETE.bat").read_text(encoding="utf-8"), "Windows build scripts target RC18")
check("New in v0.24.48" in (ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8"), "Cumulative release notes include RC18")

print(json.dumps({"ok": True, "passed": len(passed), "checks": passed}, indent=2))
