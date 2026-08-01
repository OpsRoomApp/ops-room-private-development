from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import briefing_data as bd
from app import simbrief_client as sc

passed: list[str] = []


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    passed.append(label)


# RC18 may change SimBrief import/Briefing files, but the flight-service baseline
# remains byte-identical to the live-confirmed RC15/RC14 source.
frozen = {
    "app/gsx_remote.py": "aa24bf60a8fa4c1c88777c21755966440dad01c0559ac4bad68fd30effaf0f64",
    "app/logbook.py": "6344635299b13298865fabf2299674281aa7163db6f74ea9097b887d5dcf94ae",
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
for rel, expected in frozen.items():
    actual = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
    check(actual == expected, f"Frozen operational file unchanged: {rel}")


plan_html = """
<b>[ Airport WX List ]</b>
AIRMETs:
 No Wx data available
SIGMETs:
 No Wx data available
Tropical Cyclone SIGMETs:
 No Wx data available
Volcanic Ash SIGMETs:
 No Wx data available
Departure:
LOWW
Route
<a href="https://www.simbrief.com/ofp/uads/TEST_ROUTE.gif"><img src="https://www.simbrief.com/ofp/uads/TEST_ROUTE.gif"></a>
SigWx 1 of 2
<a href="https://www.simbrief.com/ofp/uads/TEST_SIGWX_A.gif"><img src="https://www.simbrief.com/ofp/uads/TEST_SIGWX_A.gif"></a>
"""


def airport_notam(ident: str, icao: str, body: str, category: str) -> dict[str, Any]:
    return {
        "notam_id": ident,
        "location_icao": icao,
        "location_name": icao,
        "date_effective": "2026-07-17T08:00:00Z",
        "date_expire": "2026-07-18T08:00:00Z",
        "date_expire_is_estimated": False,
        "notam_text": body,
        "notam_raw": f"{ident} NOTAMN\n A) {icao} B) 2607170800 C) 2607180800\n E) {body}",
        "notam_qcode": "QPIAU",
        "notam_qcode_category": category,
        "notam_qcode_subject": "Instrument approach procedure",
        "notam_qcode_status": "Not available",
    }


raw: dict[str, Any] = {
    "fetch": {"status": "Success"},
    "params": {
        "request_id": "RC18TEST",
        "sequence_id": "SEQ17",
        "time_generated": "2026-07-17T08:33:29Z",
        "units": "kgs",
    },
    "general": {
        "icao_airline": "AUA",
        "flight_number": "101",
        "route": "SOVIL DCT SITNI DCT BAGSI DCT NANIT",
        "route_ifps": "SOVIL DCT SITNI DCT BAGSI DCT NANIT",
        "initial_altitude": "30000",
        "air_distance": "251",
        "costindex": "36",
    },
    "origin": {
        "icao_code": "LOWW", "name": "SCHWECHAT", "plan_rwy": "11",
        "notam": [airport_notam("A1001/26", "LOWW", "RWY 11 CLSD", "Runways")],
    },
    "destination": {
        "icao_code": "LOWI", "name": "INNSBRUCK", "plan_rwy": "26",
        "notam": [airport_notam("A1002/26", "LOWI", "RNP E RWY 26 SUSPENDED", "Approach Procedures")],
    },
    "alternate": [{
        "icao_code": "LOWS", "name": "SALZBURG", "plan_rwy": "33",
        "notam": [airport_notam("A1003/26", "LOWS", "ILS RWY 33 U/S", "Approach Procedures")],
    }],
    "navlog": [
        {"ident": "SOVIL", "pos_lat": "48.04", "pos_long": "15.37", "altitude_feet": "24500", "fir": "LOVV", "fir_crossing": []},
        {"ident": "TOD", "pos_lat": "47.60", "pos_long": "12.93", "altitude_feet": "30000", "fir": "LOVV", "fir_crossing": [{"fir_icao": "EDMM"}]},
    ],
    "notams": [
        {"notam_id": "A1001/26", "icao_id": "LOWW", "icao_name": "SCHWECHAT", "notam_effective_dtg": "202607170800", "notam_expire_dtg": "202607180800", "notam_text": "A1001/26 NOTAMN\n A) LOWW B) 2607170800 C) 2607180800\n E) RWY 11 CLSD", "notam_qcode": "QMRLC"},
        {"notam_id": "A1002/26", "icao_id": "LOWI", "icao_name": "INNSBRUCK", "notam_effective_dtg": "202607170800", "notam_expire_dtg": "202607180800", "notam_text": "A1002/26 NOTAMN\n A) LOWI B) 2607170800 C) 2607180800\n E) RNP E RWY 26 SUSPENDED", "notam_qcode": "QPIAU"},
        {"notam_id": "A1003/26", "icao_id": "LOWS", "icao_name": "SALZBURG", "notam_effective_dtg": "202607170800", "notam_expire_dtg": "202607180800", "notam_text": "A1003/26 NOTAMN\n A) LOWS B) 2607170800 C) 2607180800\n E) ILS RWY 33 U/S", "notam_qcode": "QICAS"},
        {"notam_id": "B1004/26", "icao_id": "EDMM", "icao_name": "MUNCHEN ACC/FIC", "notam_effective_dtg": "202607170800", "notam_expire_dtg": "202607180800", "notam_text": "B1004/26 NOTAMN\n A) EDMM B) 2607170800 C) 2607180800\n E) RESTRICTED AREA ACTIVE", "notam_qcode": "QRTCA"},
    ],
    "sigmets": [],
    "text": {"plan_html": plan_html},
    "database_updates": {
        "notams": "2026-07-17T08:31:00Z",
        "sigmet": "2026-07-17T08:32:01Z",
        "sigwx": "2026-07-17T06:32:02Z",
        "winds": "2026-07-17T00:00:00Z",
    },
    "files": {
        "directory": "https://www.simbrief.com/ofp/flightplans/",
        "pdf": {"name": "PDF Document", "link": "TEST_PDF.pdf"},
    },
    "images": {
        "directory": "https://www.simbrief.com/ofp/uads/",
        "map": [
            {"name": "Route", "link": "TEST_ROUTE.gif"},
            {"name": "SigWx 1 of 2", "link": "TEST_SIGWX_A.gif"},
            {"name": "SigWx 2 of 2", "link": "TEST_SIGWX_B.gif"},
            {"name": "UAD 1 of 3", "link": "TEST_WIND_240.gif"},
            {"name": "UAD 2 of 3", "link": "TEST_WIND_300.gif"},
            {"name": "UAD 3 of 3", "link": "TEST_WIND_340.gif"},
            {"name": "Vertical profile", "link": "TEST_PROFILE.gif"},
        ],
    },
    "aircraft": {"icaocode": "A320", "reg": "OE-LZE"},
    "fuel": {"plan_ramp": "4727", "plan_takeoff": "4669", "enroute_burn": "1911", "plan_landing": "2758"},
    "weights": {"pax_count": "134", "cargo": "2000", "payload": "12700", "est_zfw": "56759", "est_tow": "61428", "est_ldw": "59517"},
    "times": {"sched_out": "1784277000", "sched_off": "1784277300", "sched_on": "1784279640", "sched_in": "1784279640", "sched_block": "2640", "est_time_enroute": "2395"},
    "tlr": {},
}

plan = sc._normalize(raw, "1293090")
check(plan["origin"]["icao"] == "LOWW" and plan["destination"]["icao"] == "LOWI", "Origin and destination normalize")
check(plan["alternate"]["icao"] == "LOWS" and len(plan["alternates"]) == 1, "List-form alternate normalizes")
check(len(plan["navlog"]) == 2 and plan["navlog"][1]["fir_crossing"][0]["fir_icao"] == "EDMM", "List-form navlog and FIR crossing normalize")
check(plan["files"]["pdf"] == "https://www.simbrief.com/ofp/flightplans/TEST_PDF.pdf", "Nested PDF directory and link join correctly")
check(len(plan["briefing"]["notams"]) == 4, "Structured route NOTAM list is retained")
check({row["scope_key"] for row in plan["briefing"]["notams"]} == {"departure", "destination", "alternate", "enroute"}, "NOTAM scopes separate correctly")
check(next(row for row in plan["briefing"]["notams"] if row["id"] == "A1002/26")["category"] == "Approach Procedures", "Airport NOTAM enrichment is retained")
check(len(plan["briefing"]["charts"]) == 7, "All native SimBrief chart manifest entries are retained")
check([row["category"] for row in plan["briefing"]["charts"]].count("sigwx") == 2, "Two SIGWX images classify directly")
check([row["category"] for row in plan["briefing"]["charts"]].count("winds") == 3, "Three winds-aloft images classify directly")
check(any(row["category"] == "route" for row in plan["briefing"]["charts"]), "Route image classifies directly")
check(any(row["category"] == "profile" for row in plan["briefing"]["charts"]), "Vertical profile image classifies directly")
check(all(section["state"] == "none" for section in plan["briefing"]["hazards"]["sections"]), "No-data AIRMET/SIGMET/TC/VA blocks are genuine none states")
check(plan["files"]["plan_html"] == plan_html, "Working SimBrief plan_html is retained unchanged")


class FakeResponse:
    def __init__(self, content: bytes):
        self.content = content
    def raise_for_status(self) -> None:
        return None


def fake_get(url: str, **_kwargs: Any) -> FakeResponse:
    if str(url).lower().endswith(".pdf"):
        return FakeResponse(b"%PDF-1.7\nRC18 synthetic PDF")
    return FakeResponse(b"GIF89a" + b"\x00" * 128)


old_get = sc.requests.get
old_app_data = sc.app_data_dir
old_memory = dict(sc._memory)
try:
    with tempfile.TemporaryDirectory(prefix="opsroom-rc18-") as temp_dir:
        base = Path(temp_dir)
        sc.app_data_dir = lambda: base
        sc.requests.get = fake_get
        with sc._lock:
            sc._memory.update(user_ref="1293090", plan=json.loads(json.dumps(plan)), fetched_monotonic=time.monotonic())
        sc._write_disk_cache("1293090", plan)
        sc._write_raw_cache("1293090", raw)
        sc._cache_ofp_resources("1293090", sc._plan_identity(plan), plan["files"]["pdf"], plan["briefing"]["charts"])
        cached = sc.cached_plan("1293090")
        check(bool(cached and cached["files"].get("pdf_local")), "Background PDF cache path is published to memory")
        check(bool(cached and cached["files"].get("pdf_path")), "Background PDF filesystem path is persisted")
        check(all(row.get("cached") for row in cached["briefing"]["charts"]), "All native chart cache states publish to the authoritative plan")
        disk = json.loads((base / sc.CACHE_FILE).read_text(encoding="utf-8"))["plan"]
        check(bool(disk["files"].get("pdf_local")) and all(row.get("cached") for row in disk["briefing"]["charts"]), "Resource metadata persists to disk cache")
        check((base / sc.RAW_CACHE_FILE).exists(), "Raw SimBrief response is retained only in local runtime cache")
        chart = cached["briefing"]["charts"][0]
        chart_path = sc.cached_ofp_file(chart["cache_filename"])
        check(bool(chart_path and chart_path.read_bytes().startswith(b"GIF89a")), "Cached native chart validates as an image")
        chart_path.write_bytes(b"CORRUPT-IMAGE" * 16)
        restored = sc.ensure_current_ofp_asset(chart["cache_filename"])
        check(bool(restored and restored.read_bytes().startswith(b"GIF89a")), "Corrupt native chart is rejected and restored on demand")
        restored.unlink()
        restored = sc.ensure_current_ofp_asset(chart["cache_filename"])
        check(bool(restored and restored.exists()), "Missing native chart is restored on demand")
        check(sc.ensure_current_ofp_asset("../outside.gif") is None, "OFP image recovery rejects path traversal")

        newer = json.loads(json.dumps(cached))
        newer["request_id"] = "NEWER-FLIGHT"
        newer["plan_id"] = "NEWER-FLIGHT"
        with sc._lock:
            sc._memory.update(user_ref="1293090", plan=newer)
        sc._publish_cached_resources("1293090", "RC18TEST", "wrong.pdf", set(), [])
        check(sc._memory["plan"]["request_id"] == "NEWER-FLIGHT" and sc._memory["plan"]["files"].get("pdf_local") != "/api/simbrief/ofp-cache/wrong.pdf", "Old resource worker cannot overwrite a newer flight")
finally:
    sc.requests.get = old_get
    sc.app_data_dir = old_app_data
    with sc._lock:
        sc._memory.clear()
        sc._memory.update(old_memory)


old_current = bd._current_plan
old_extract = bd._extract_pdf_package
try:
    bd._current_plan = lambda: plan
    bd._extract_pdf_package = lambda _path: (_ for _ in ()).throw(AssertionError("native manifest should not require PDF scanning"))
    bd.invalidate_cache()
    briefing = bd.operational_briefing(force=True)
    check(len(briefing["notams"]) == 4 and briefing["notam_groups"]["enroute"] == 1, "Operational Briefing uses structured NOTAMs")
    check(len(briefing["sigwx"]["charts"]) == 2, "Operational Briefing exposes two native SIGWX images")
    check(len(briefing["charts"]) == 5, "Operational Briefing exposes route, winds and profile images separately")
    check(len(briefing["hazards"]["sections"]) == 4, "Operational Briefing exposes four hazard categories")
    check(briefing["sources"][0]["updates"]["notams"] == "2026-07-17T08:31:00Z", "SimBrief database update timestamps are exposed")
finally:
    bd._current_plan = old_current
    bd._extract_pdf_package = old_extract
    bd.invalidate_cache()


simbrief_source = (ROOT / "app/simbrief_client.py").read_text(encoding="utf-8")
briefing_source = (ROOT / "app/briefing_data.py").read_text(encoding="utf-8")
main_source = (ROOT / "app/main.py").read_text(encoding="utf-8")
ops_js = (ROOT / "app/static/opsroom.js").read_text(encoding="utf-8")
ops_css = (ROOT / "app/static/opsroom.css").read_text(encoding="utf-8")

check('_fetch_simbrief_json(user_ref, key, "1")' in simbrief_source and '_fetch_simbrief_json(user_ref, key, "v2")' in simbrief_source and simbrief_source.index('_fetch_simbrief_json(user_ref, key, "1")') < simbrief_source.index('_fetch_simbrief_json(user_ref, key, "v2")'), "Fetcher uses documented JSON first and only probes the compatible richer response when needed")
check('raw.get("notams")' in simbrief_source and 'raw.get("images")' in simbrief_source, "Native NOTAM and image arrays are parsed")
check("_write_raw_cache" in simbrief_source and "RAW_CACHE_FILE" in simbrief_source, "Raw response is retained locally without bloating normal API responses")
check("_start_resource_cache(user_ref, plan)" in simbrief_source and simbrief_source.index("_write_disk_cache(user_ref, plan)") < simbrief_source.index("_start_resource_cache(user_ref, plan)"), "Authoritative plan is stored before resource caching starts")
check("ofp_cache_filename(remote, \"pdf\")" in briefing_source, "Cached PDF path has URL-derived recovery fallback")
check("/api/simbrief/ofp-image/{filename}" in main_source and "ensure_current_ofp_asset" in main_source, "Local native-image endpoint supports on-demand recovery")
check('X-OPSROOM-OFP-Source": "simbrief-plan-html"' in main_source, "View OFP continues to use SimBrief plan_html")
check("HAZARDS" in ops_js and "briefingHazards" in ops_js, "Dedicated hazards section is packaged")
check("briefingNotamSearch" in ops_js and "data-notam-filter" in ops_js, "NOTAM search and scope filters are packaged")
check("briefingImageViewer" in ops_js and "briefingImageScale" in ops_js, "Expanded chart viewer supports zoom and pan")
check("briefing-simbrief-gallery" in ops_css and "briefing-image-viewer-stage" in ops_css, "Native chart gallery and viewer styling are packaged")
check("repeat(7" in ops_css, "Briefing navigation accommodates seven compact sections")
check("window.print()" not in (ROOT / "app/static/pirep.js").read_text(encoding="utf-8"), "RC16 direct Full PIREP PDF download remains intact")

version = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
check(version.get("version") == "0.24.48", "Version metadata is v0.24.48")
check(version.get("build") == "public-beta-release-candidate-18", "Version metadata is RC18")
check(version.get("codename") == "Final Release Integrity", "RC18 codename is Final Release Integrity")
check("OPS_ROOM_v0_24_48_Public_Beta_RC18_Windows_x64.zip" in (ROOT / "BUILD OPS ROOM COMPLETE.bat").read_text(encoding="utf-8"), "Complete build targets the RC18 Windows package")
check("New in v0.24.48" in (ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8"), "Release notes describe RC18")

print(json.dumps({"ok": True, "passed": len(passed), "checks": passed}, indent=2))
