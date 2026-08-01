from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import briefing_data as bd  # noqa: E402
from app import simbrief_client as sc  # noqa: E402
from app.weather_client import decode_metar  # noqa: E402

passed: list[str] = []


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    passed.append(label)


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


# Final RC deliberately leaves the live flight-service and telemetry baseline unchanged.
protected = {
    "app/gsx_remote.py": "aa24bf60a8fa4c1c88777c21755966440dad01c0559ac4bad68fd30effaf0f64",
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
    check(sha(rel) == expected, f"Protected live baseline unchanged: {rel}")


# Compact SimBrief response reproducing airport, FIR, validity and chart edge cases.
raw: dict[str, Any] = {
    "fetch": {"status": "Success"},
    "params": {
        "request_id": "rc18-test",
        "sequence_id": "seq-18",
        "time_generated": "2026-07-17T08:33:29Z",
        "units": "kgs",
    },
    "general": {
        "icao_airline": "AUA",
        "flight_number": "101",
        "route": "SOVIL DCT NANIT",
        "initial_altitude": "30000",
    },
    "origin": {
        "icao_code": "LOWW",
        "name": "SCHWECHAT",
        "notam": [
            {
                "notam_id": "A1001/26",
                "location_icao": "LOWW",
                "location_name": "SCHWECHAT",
                "date_effective": "2026-06-24T11:35:00Z",
                "date_expire": False,
                "notam_text": "PARKING POSITION RESTRICTION",
                "notam_raw": "A1001/26 NOTAMN\nA) LOWW B) 2606241135 C) PERM\nE) PARKING POSITION RESTRICTION",
                "notam_qcode_category": "Airport",
            },
            {
                "notam_id": "A1002/26",
                "location_icao": "LOWW",
                "location_name": "SCHWECHAT",
                "date_effective": "2026-07-01T09:00:00Z",
                "date_expire": "2026-07-20T18:00:00Z",
                "notam_text": "RUNWAY WORK IN PROGRESS",
                "notam_raw": "A1002/26 NOTAMN\nA) LOWW B) 2607010900 C) 2607201800\nE) RUNWAY WORK IN PROGRESS",
                "notam_qcode_category": "Runways",
            },
        ],
    },
    "destination": {
        "icao_code": "LOWI",
        "name": "INNSBRUCK",
        "notam": [
            {
                "notam_id": "B2001/26",
                "location_icao": "LOWI",
                "location_name": "INNSBRUCK",
                "notam_text": "RNP PROCEDURE SUSPENDED",
                "notam_raw": "B2001/26 NOTAMN\nA) LOWI B) 2606050612 C) 2609032359EST\nE) RNP PROCEDURE SUSPENDED",
                "notam_qcode_category": "Approach Procedures",
            }
        ],
    },
    "alternate": [
        {
            "icao_code": "LOWS",
            "name": "SALZBURG",
            "notam": [
                {
                    "notam_id": "C3001/26",
                    "location_icao": "LOWS",
                    "location_name": "SALZBURG",
                    "date_effective": "2026-05-13T14:07:00Z",
                    "date_expire": "2026-08-05T23:59:00Z",
                    "date_expire_is_estimated": True,
                    "notam_text": "ALTERNATE APPROACH RESTRICTION",
                    "notam_qcode_category": "Approach Procedures",
                }
            ],
        }
    ],
    "notams": [
        {
            "notam_id": "D4001/26",
            "icao_id": "LOVV",
            "icao_name": "VIENNA FIR",
            "notam_effective_dtg": "202607171145",
            "notam_text": "D4001/26 NOTAMN\nA) LOVV B) 2607171145 C) 2607171255\nE) MILITARY TRAINING AREA ACTIVE",
            "notam_report": "MILITARY TRAINING AREA ACTIVE",
            "notam_qcode": "QRTCA",
        },
        {
            "notam_id": "B2001/26",
            "icao_id": "LOWI",
            "notam_effective_dtg": "202606050612",
            "notam_text": "B2001/26 NOTAMN\nA) LOWI B) 2606050612 C) 2609032359EST\nE) RNP PROCEDURE SUSPENDED",
            "notam_report": "RNP PROCEDURE SUSPENDED",
        },
        {
            "notam_id": "A1001/26",
            "icao_id": "LOWW",
            "notam_effective_dtg": "202606241135",
            "notam_text": "A1001/26 NOTAMN\nA) LOWW B) 2606241135 C) PERM\nE) PARKING POSITION RESTRICTION",
            "notam_report": "PARKING POSITION RESTRICTION",
        },
        {
            "notam_id": "C3001/26",
            "icao_id": "LOWS",
            "notam_effective_dtg": "202605131407",
            "notam_text": "C3001/26 NOTAMN\nA) LOWS B) 2605131407 C) 2608052359EST\nE) ALTERNATE APPROACH RESTRICTION",
            "notam_report": "ALTERNATE APPROACH RESTRICTION",
        },
        {
            "notam_id": "A1002/26",
            "icao_id": "LOWW",
            "notam_effective_dtg": "202607010900",
            "notam_expire_dtg": "202607201800",
            "notam_text": "A1002/26 NOTAMN\nA) LOWW B) 2607010900 C) 2607201800\nE) RUNWAY WORK IN PROGRESS",
            "notam_report": "RUNWAY WORK IN PROGRESS",
        },
    ],
    "images": {
        "directory": "https://www.simbrief.com/ofp/uads/",
        "map": [
            {"name": "Route", "link": "ROUTE.gif"},
            {"name": "SigWx 1 of 2", "link": "SIGWX_A.gif"},
            {"name": "SigWx 2 of 2", "link": "SIGWX_B.gif"},
            {"name": "UAD 1 of 1", "link": "WINDS.gif"},
            {"name": "Vertical profile", "link": "PROFILE.gif"},
        ],
    },
    "database_updates": {
        "notams": "202607170831",
        "sigmet": "2026-07-17T08:32:01Z",
        "sigwx": 1784277122,
        "winds": "202607170000",
    },
    "text": {
        "plan_html": """
            <h1>[ NOTAM ]</h1>
            <p>DEPARTURE AIRPORT - DETAILED INFO</p>
            <p>A1002/26 RUNWAY WORK IN PROGRESS</p>
            <p>A1001/26 PARKING POSITION RESTRICTION</p>
            <p>DESTINATION AIRPORT - DETAILED INFO</p>
            <p>B2001/26 RNP PROCEDURE SUSPENDED</p>
            <p>DESTINATION ALTERNATE AIRPORT(S)</p>
            <p>C3001/26 ALTERNATE APPROACH RESTRICTION</p>
            <p>AREA ENROUTE DEPARTURE - DESTINATION</p>
            <p>D4001/26 MILITARY TRAINING AREA ACTIVE</p>
            <p>AIRMETs: No Wx data available</p>
            <p>SIGMETs: No Wx data available</p>
            <p>Tropical Cyclone SIGMETs: No Wx data available</p>
            <p>Volcanic Ash SIGMETs: No Wx data available</p>
        """,
    },
}

plan = sc._normalize(raw, "1293090")
briefing = plan["briefing"]
notams = briefing["notams"]
counts = Counter(row["scope_key"] for row in notams)
check(len(notams) == 5, "All structured test NOTAMs normalize")
check(counts == Counter({"departure": 2, "destination": 1, "alternate": 1, "enroute": 1}), "NOTAM scopes classify by flight role")
check([row["id"] for row in notams[:2]] == ["A1002/26", "A1001/26"], "Departure notices preserve rendered LIDO bulletin order")
check([row["scope_key"] for row in notams] == ["departure", "departure", "destination", "alternate", "enroute"], "Operational scopes remain grouped in briefing order")

by_id = {row["id"]: row for row in notams}
check(by_id["A1001/26"]["permanent"] and by_id["A1001/26"]["expires_utc"] is None, "Permanent NOTAM validity is preserved")
check(by_id["A1002/26"]["effective_utc"] == "2026-07-01T09:00:00Z", "Structured effective timestamp is normalized")
check(by_id["A1002/26"]["expires_utc"] == "2026-07-20T18:00:00Z", "Structured expiry timestamp is normalized")
check(by_id["B2001/26"]["effective_utc"] == "2026-06-05T06:12:00Z", "ICAO B-line supplies missing effective timestamp")
check(by_id["B2001/26"]["expires_utc"] == "2026-09-03T23:59:00Z", "ICAO C-line supplies missing expiry timestamp")
check(by_id["B2001/26"]["expires_estimated"] is True, "ICAO C-line EST marker is preserved")
check(by_id["C3001/26"]["expires_estimated"] is True, "Structured estimated-expiry marker is preserved")
check(by_id["D4001/26"]["location"] == "LOVV" and by_id["D4001/26"]["scope_key"] == "enroute", "FIR notice remains en-route")
check(all(row.get("source_order") is not None for row in notams), "Every NOTAM carries deterministic source order")

updates = briefing["database_updates"]
check(updates["notams"] == "2026-07-17T08:31:00Z", "Compact database DTG normalizes")
check(updates["sigmet"] == "2026-07-17T08:32:01Z", "ISO database timestamp normalizes")
check(updates["winds"] == "2026-07-17T00:00:00Z", "Winds source timestamp normalizes")
check(updates["sigwx"].endswith("Z"), "Epoch database timestamp normalizes to UTC")

chart_counts = Counter(row["category"] for row in briefing["charts"])
check(chart_counts["sigwx"] == 2, "Two native SIGWX charts classify")
check(chart_counts["route"] == 1, "Route chart classifies")
check(chart_counts["winds"] == 1, "Winds chart classifies")
check(chart_counts["profile"] == 1, "Vertical profile chart classifies")
check(plan["files"]["plan_html"] == raw["text"]["plan_html"], "View OFP plan_html remains unchanged")

# Operational API must expose accurate counts and source timestamps from the normalized plan.
old_current = bd._current_plan
try:
    bd._current_plan = lambda: plan  # type: ignore[assignment]
    bd.invalidate_cache()
    operational = bd.operational_briefing(force=True)
finally:
    bd._current_plan = old_current  # type: ignore[assignment]
    bd.invalidate_cache()
check(operational["notam_groups"] == {"all": 5, "departure": 2, "destination": 1, "alternate": 1, "enroute": 1}, "Operational API exposes correct filter counts")
check(operational["database_updates"]["notams"] == "2026-07-17T08:31:00Z", "Operational API exposes normalized source times")
check(len(operational["sigwx"]["charts"]) == 2, "Operational API uses native SIGWX manifest")

# PDF fallback must no longer dump every notice into en-route or retain page furniture.
pdf_text = """
[ NOTAM ]
DEPARTURE AIRPORT - DETAILED INFO
LOWW/VIE SCHWECHAT
++++++++++++++++++++ AIRPORT ++++++++++++++++++++
A9001/26
VALID: 17-JUL-26 1000 - 17-JUL-26 1200
RWY 11 CLSD
- Not for real world navigation -
12
DESTINATION AIRPORT - DETAILED INFO
LOWI/INN INNSBRUCK
++++++++++++++++ APPROACH PROCEDURES ++++++++++++++++
B9001/26
RNP RWY 26 SUSPENDED
OS 101/17 JUL/VIE-INN Page 13
END OF LIDO-NOTAM-BULLETIN
"""
fallback = bd._parse_lido_notams(pdf_text)
check([row["scope_key"] for row in fallback] == ["departure", "destination"], "PDF fallback classifies departure and destination")
check(fallback[0]["effective_utc"] == "2026-07-17T10:00:00Z" and fallback[0]["expires_utc"] == "2026-07-17T12:00:00Z", "PDF fallback parses explicit VALID range")
check("NOT FOR REAL WORLD" not in fallback[0]["text"].upper(), "PDF fallback removes navigation disclaimer")
check("PAGE 13" not in fallback[1]["text"].upper(), "PDF fallback removes OFP page header")
check(fallback[0]["text"].count("A9001/26") == 0, "PDF fallback removes duplicated NOTAM ID from body")

# SimBrief fetching: documented json=1 is first; v2 is optional and selected only when richer.
old_fetch = sc._fetch_simbrief_json
old_write_disk = sc._write_disk_cache
old_write_raw = sc._write_raw_cache
old_start = sc._start_resource_cache
try:
    calls: list[str] = []
    sparse = {**raw, "notams": [], "images": {"map": []}}
    rich = raw
    sc._fetch_simbrief_json = lambda _user, _key, fmt: (calls.append(fmt) or (sparse if fmt == "1" else rich))  # type: ignore[assignment]
    sc._write_disk_cache = lambda *_args, **_kwargs: None  # type: ignore[assignment]
    sc._write_raw_cache = lambda *_args, **_kwargs: None  # type: ignore[assignment]
    sc._start_resource_cache = lambda *_args, **_kwargs: None  # type: ignore[assignment]
    with sc._lock:
        sc._memory.clear()
        sc._memory.update(user_ref="", fetched_monotonic=0.0, plan=None, last_error=None, last_attempt_utc=None)
    fetched = sc.fetch_latest_ofp("1293090", force=True)
    check(calls == ["1", "v2"], "Sparse documented response triggers one optional richer probe")
    check(len(fetched["briefing"]["charts"]) == 5, "Richer compatible response is selected when it adds briefing data")

    calls.clear()
    sc._fetch_simbrief_json = lambda _user, _key, fmt: (calls.append(fmt) or rich)  # type: ignore[assignment]
    with sc._lock:
        sc._memory.clear()
        sc._memory.update(user_ref="", fetched_monotonic=0.0, plan=None, last_error=None, last_attempt_utc=None)
    fetched = sc.fetch_latest_ofp("1293090", force=True)
    check(calls == ["1"], "Rich documented response avoids an unnecessary second request")
    check(fetched["ok"] is True, "Documented SimBrief response remains sufficient by itself")
finally:
    sc._fetch_simbrief_json = old_fetch  # type: ignore[assignment]
    sc._write_disk_cache = old_write_disk  # type: ignore[assignment]
    sc._write_raw_cache = old_write_raw  # type: ignore[assignment]
    sc._start_resource_cache = old_start  # type: ignore[assignment]
    with sc._lock:
        sc._memory.clear()
        sc._memory.update(user_ref="", fetched_monotonic=0.0, plan=None, last_error=None, last_attempt_utc=None)

# Weather category is recalculated from each new METAR; verify all four bands.
check(decode_metar("LOWW 171200Z 00000KT CAVOK 20/10 Q1013")["flight_category"] == "VFR", "CAVOK classifies VFR")
check(decode_metar("LOWW 171200Z 00000KT 6000 BKN020 20/10 Q1013")["flight_category"] == "MVFR", "Reduced visibility/ceiling classifies MVFR")
check(decode_metar("LOWW 171200Z 00000KT 3000 BKN008 20/10 Q1013")["flight_category"] == "IFR", "Low visibility/ceiling classifies IFR")
check(decode_metar("LOWW 171200Z 00000KT 1000 OVC003 20/10 Q1013")["flight_category"] == "LIFR", "Very low visibility/ceiling classifies LIFR")

simbrief_source = (ROOT / "app/simbrief_client.py").read_text(encoding="utf-8")
briefing_source = (ROOT / "app/briefing_data.py").read_text(encoding="utf-8")
logbook_source = (ROOT / "app/logbook.py").read_text(encoding="utf-8")
ops_js = (ROOT / "app/static/opsroom.js").read_text(encoding="utf-8")
pirep_js = (ROOT / "app/static/pirep.js").read_text(encoding="utf-8")
main_source = (ROOT / "app/main.py").read_text(encoding="utf-8")

check('_fetch_simbrief_json(user_ref, key, "1")' in simbrief_source, "Documented SimBrief JSON fetch is packaged")
check('_native_briefing_score' in simbrief_source and 'rich_score > documented_score' in simbrief_source, "Optional richer response is feature-detected")
check('_raw_notam_validity' in simbrief_source and 'C\\)' in simbrief_source, "ICAO B/C validity fallback is packaged")
check('result.sort(key=lambda row: (order.get' in simbrief_source, "NOTAMs sort by operational scope and LIDO order")
check('briefingDateTime' in ops_js and 'EFFECTIVE ${briefingDateTime' in ops_js, "Full effective dates render in NOTAM cards")
check('EXPIRES PERMANENT' in ops_js and 'expires_estimated' in ops_js, "Permanent and estimated expiry states render")
check("stamp!=='---'" in ops_js and "parts.push(`${label} ${stamp}`)" in ops_js, "Unavailable source timestamps are omitted")
source_line_block = ops_js[ops_js.index('function briefingSourceLine'):ops_js.index('function briefingNoticeCard')]
check('----Z' not in source_line_block, "Briefing source line never renders dashed timestamps with a Z suffix")
check('`Updated ${utcHm(plan.generated_utc)}`' in ops_js, "Briefing header no longer appends a duplicate Z")
check(ops_js.count("target.innerHTML=briefingNotices(rows,query?") == 1, "NOTAM search results render once per filter update")
check('5*60*1000' in ops_js and 'refreshBriefingWeather(true)' in ops_js, "Briefing weather refresh remains five minutes")

# The WinError 32 fix must make Chromium profile cleanup best-effort and stop all children first.
check('ignore_cleanup_errors=True' in logbook_source, "Windows temporary browser profile cleanup ignores residual locked files")
check('["taskkill", "/PID", str(process.pid), "/T", "/F"]' in logbook_source, "PDF renderer stops Chromium process tree on Windows")
check('--disable-breakpad' in logbook_source and '--disable-crash-reporter' in logbook_source and '--no-crash-upload' in logbook_source, "PDF renderer disables crash-reporting helpers")
check('_stop_pdf_browser(process)' in logbook_source, "PDF renderer always executes process-tree cleanup")
check('Page.printToPDF' in logbook_source and 'window.__OPSROOM_PIREP_READY__' in logbook_source, "Master Full PIREP waits for complete DOM before PDF capture")
check('window.print()' not in pirep_js, "Full PIREP SAVE PDF never opens browser print dialog")
check('/api/logbook/${encodeURIComponent(id)}/export.pdf' in pirep_js, "Full PIREP downloads through direct export endpoint")
check('/api/logbook/{entry_id}/export.pdf' in main_source, "Direct Full PIREP PDF endpoint remains registered")

check('_CACHE_SECONDS = 0.18' in (ROOT / 'app/telemetry_provider.py').read_text(encoding='utf-8'), "Telemetry cache rate remains frozen for final RC")
check('read_position(force=False)' in (ROOT / 'app/telemetry_provider.py').read_text(encoding='utf-8'), "SimConnect shared-session behavior remains frozen")

version = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
update = json.loads((ROOT / "update.json").read_text(encoding="utf-8"))
check(version == {"product": "OPS ROOM", "version": "0.24.48", "build": "public-beta-release-candidate-18", "codename": "Final Release Integrity", "channel": "release-candidate"}, "Version metadata is exact RC18")
check(update.get("version") == "0.24.48" and "RC18" in str(update.get("download_url")), "Updater metadata targets RC18")
check("OPS_ROOM_v0_24_48_Public_Beta_RC18_Windows_x64.zip" in (ROOT / "BUILD OPS ROOM COMPLETE.bat").read_text(encoding="utf-8"), "Complete build targets final RC18 Windows ZIP")
check("Telemetry deliberately unchanged" in (ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8"), "Release notes disclose deferred telemetry redesign")
check("Weather categories remain live" in (ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8"), "Release notes document live category refresh")

print(json.dumps({"ok": True, "passed": len(passed), "checks": passed}, indent=2))
