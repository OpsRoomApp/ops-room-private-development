from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import economy, gsx_receipts, logbook  # noqa: E402
from app.weather_client import decode_metar  # noqa: E402

passed: list[str] = []


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    passed.append(label)


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


# The exact raw report supplied with the release-blocking screenshot.
metar = decode_metar("EDDM 162220Z AUTO 31008KT 280V350 CAVOK 19/16 Q1018 RESHRA NOSIG")
check(metar["flight_category"] == "VFR", "CAVOK METAR decodes to VFR")
check(metar["wind"] == "310° at 8 KT (variable 280°–350°)", "Wind and variable sector decode from raw METAR")
check(metar["visibility"] == "9999 m or greater", "CAVOK visibility is displayed as 9999 m or greater")
check(metar["temperature"] == "19° C (66° F)" and metar["dewpoint"] == "16° C (61° F)", "Temperature and dew point include Celsius and Fahrenheit")
check(metar["humidity"] == "83 %", "Relative humidity is derived from temperature and dew point")
check(metar["altimeter"] == "1018 hPa (30.06 inHg)", "QNH includes hPa and inHg")

us_metar = decode_metar("KJFK 170051Z 18010KT 1 1/2SM BKN008 M02/M05 A2992")
check(us_metar["visibility"] == "1.5 statute miles", "Fractional statute-mile visibility decodes")
check(us_metar["temperature_c"] == -2 and us_metar["dewpoint_c"] == -5, "Negative METAR temperatures decode")
check(us_metar["flight_category"] == "IFR", "Ceiling and visibility produce the correct flight category")
check(us_metar["altimeter"] == "1013 hPa (29.92 inHg)", "US altimeter group converts to hPa")

# Reproduce the supplied GSX v1 receipt shape in the real category folders.
old_appdata = os.environ.get("APPDATA")
with tempfile.TemporaryDirectory() as temp:
    os.environ["APPDATA"] = temp
    root = Path(temp) / "Virtuali" / "GSX" / "Receipts"
    fixtures = {
        "Catering": ("20260716T215254Z_EDDM_D-AIUC", "Do&Co Catering", "CATERING RECEIPT", "€130.44 ~$ 149.44", "Beverage service"),
        "Fuel": ("20260716T221654Z_EDDM_D-AIUC", "Shell plc", "FUEL DELIVERY RECEIPT", "€1,266.56 ~$ 1,451.01", "Jet-A1 fuel"),
        "Handling": ("20260716T222737Z_EDDM_D-AIUC", "DLH,DLHX,LHT,CLH,GEC", "GROUND HANDLING RECEIPT", "€1,760.22 ~$ 2,016.56", "Passenger boarding"),
    }
    for category, (stem, operator, title, total, description) in fixtures.items():
        folder = root / category
        folder.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "operator": operator,
            "title": title,
            "receiptId": f"GSX-{stem[:15]}-EDDM",
            "icao": "EDDM",
            "airportName": "Munich",
            "airline": "Deutsche Lufthansa AG",
            "tail": "D-AIUC",
            "aircraftType": "A320",
            "serviceInfoRows": [["AIRCRAFT", "D-AIUC - A320"]],
            "items": [{"description": description, "qty": "1", "unitPrice": "€1.00", "amount": total.split(" ~")[0]}],
            "subtotal": total.split(" ~")[0],
            "taxes": [],
            "total": total,
        }
        (folder / f"{stem}.json").write_text(json.dumps(payload), encoding="utf-8")
        (folder / f"{stem}.html").write_text(f"<title>{title} - {operator}</title>", encoding="utf-8")

    parsed = gsx_receipts._iter_receipts(root)
    check(len(parsed) == 3, "Catering, Fuel and Handling JSON receipts parse once each")
    check({item["category"] for item in parsed} == {"Catering", "Fuel", "Handling"}, "Receipt category comes from the GSX folder")
    check(all(item["currency"] == "EUR" and item["amount"] for item in parsed), "Local-currency totals parse from GSX display strings")
    check(all(item["line_items"] and item["url"].endswith(".html") for item in parsed), "Itemised charges and receipt viewer links are retained")

    matched = gsx_receipts.recent_invoice_items(
        "2026-07-16T21:30:00Z", "2026-07-16T23:00:00Z", takeoff_utc="2026-07-16T22:30:00Z",
        landing_utc=None, origin="EDDM", destination="EDDF", tail="D AIUC",
    )
    check(len(matched) == 3, "Operational-window scan finds all three supplied-format receipts")
    check(all(item["tail"] == "D-AIUC" for item in matched), "Receipt registration is retained for display")
    check(gsx_receipts._normalise_registration("D-AIUC") == gsx_receipts._normalise_registration("D AIUC") == "DAIUC", "Registration punctuation cannot prevent matching")

if old_appdata is None:
    os.environ.pop("APPDATA", None)
else:
    os.environ["APPDATA"] = old_appdata

# Missing finance must be recoverable without duplicating a posted flight.
orig_enabled = economy.finance_enabled
orig_reconcile = economy.reconcile_flight
orig_rows = logbook._rows
try:
    economy.finance_enabled = lambda: True
    calls: list[str] = []
    def fake_reconcile(meta, previous_entries=None):
        calls.append(str(meta.get("id")))
        statement = {"ok": True, "currency": "EUR", "airline": {"invoices": copy.deepcopy(meta.get("gsx_invoices") or [])}, "pilot": {"pay": 100}}
        meta["finance"] = statement
        return statement
    economy.reconcile_flight = fake_reconcile
    logbook._rows = lambda *_args, **_kwargs: []
    meta = {"id": "flight-rc14", "state": "COMPLETE", "gsx_invoices": [{"receipt_id": "receipt-1"}]}
    recovered = logbook._refresh_entry_finance(meta, persist=False)
    check(calls == ["flight-rc14"] and recovered.get("finance", {}).get("ok"), "Opening a completed PIREP recovers a missing finance statement")
    again = logbook._refresh_entry_finance(recovered, persist=False)
    check(calls == ["flight-rc14"] and again["finance"]["airline"]["invoices"][0]["receipt_id"] == "receipt-1", "Matching finance and receipt ids do not reconcile twice")
finally:
    economy.finance_enabled = orig_enabled
    economy.reconcile_flight = orig_reconcile
    logbook._rows = orig_rows

# Browser source guards: one master chart profile and receipts independent of finance.
ops_js = (ROOT / "app/static/opsroom.js").read_text(encoding="utf-8")
pirep_js = (ROOT / "app/static/pirep.js").read_text(encoding="utf-8")
weather_py = (ROOT / "app/weather_client.py").read_text(encoding="utf-8")
logbook_py = (ROOT / "app/logbook.py").read_text(encoding="utf-8")
check("payload.analysis?.approach?.profile" in ops_js and "masterApproach.length?masterApproach:rawApproach" in ops_js, "Logbook charts use the Full PIREP master approach profile")
check(ops_js.count("reverseX:true") >= 4, "All four Logbook approach charts run from far-to-near threshold distance")
check("entry.gsx_invoices" in pirep_js and "statementReceipts.length?statementReceipts:attachedReceipts" in pirep_js, "Full PIREP displays attached receipts even without Finance")
check("OPEN RECEIPT" in pirep_js and "line_items" in pirep_js, "Full PIREP exposes receipt links and itemised charges")
check("_refresh_entry_receipts" in logbook_py and "_refresh_entry_finance" in logbook_py and "meta = _refresh_entry_finance(meta, persist=True)" in logbook_py, "PIREP open runs receipt scan then finance recovery")
check("def decode_metar" in weather_py and "humidity_percent" in weather_py and "flight_category" in weather_py, "Briefing METAR decode is local and raw-report driven")
check("metar-category" in (ROOT / "app/static/opsroom.css").read_text(encoding="utf-8"), "Decoded METAR presentation styles are packaged")

# Frozen operational systems: exact RC13/RC10 hashes remain intact.
frozen = {
    "app/announcements.py": "721f55088def610f5d66e5dddd3a00123a86ccba10e4f2c2d654dedd1284da1b",
    "app/telemetry_provider.py": "0c921fe33d076d68db66d479bb3db5388c844924924d7995358bdafe21c91de8",
    "app/fenix_adapter.py": "7a9597f65ea8f0e6e67f839fb607630faa4181d3bf725dd2160d1fc854571f46",
    "app/fenix_gsx_loading_state_machine.py": "6a9fc247e785228c210a3f2a3942925e29d1d744e9ce9a583f3dfaa495c0d2cd",
    "app/pirep_analysis.py": "a544897546cdbf03b2cb8d4e6d02a03b6c35b9e13f7d5a508e00f36ac63a6c3a",
    "app/economy.py": "7c65910e4807871fdf5ba922144c1af7f4e13ab23ff805e62170da273e702f87",
    "app/settings_store.py": "0bd2117c4a8412d113047514986f06e8552bc3508b91ef834cdce3d5aa26af05",
    "app/raas.py": "7e808122ebd1f8c6301421b28a0ca84585426b9d730bb9506408d99ee5e6578b",
}
for rel, expected in frozen.items():
    check(sha(rel) == expected, f"Frozen operational subsystem is unchanged: {rel}")

version = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
check(version["version"] == "0.24.48" and version["build"].endswith("18"), "Version metadata is v0.24.48 RC18")
check("OPS_ROOM_v0_24_48_Public_Beta_RC18_Windows_x64.zip" in (ROOT / "BUILD OPS ROOM COMPLETE.bat").read_text(encoding="utf-8"), "Windows build target is RC18")
check("Final Release Integrity" in (ROOT / "tools/write_update_manifest.py").read_text(encoding="utf-8"), "Updater manifest writer carries the RC18 codename")
check("New in v0.24.48" in (ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8"), "Cumulative release notes include RC18")

print(json.dumps({"ok": True, "passed": len(passed), "checks": passed}, indent=2))
