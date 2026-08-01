from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import briefing_data as bd

passed: list[str] = []


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    passed.append(label)


# RC18 changes only SimBrief import/Briefing presentation above the frozen operational baseline.
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
    check(actual == expected, f"Frozen RC15 operational file unchanged: {rel}")


# Build a compact SimBrief-like PDF so the validator exercises text extraction,
# route-map skipping, SIGWX chart discovery and dense wind-chart stopping.
def chart_png(kind: str) -> bytes:
    image = Image.new("RGB", (720, 900), (250, 249, 208))
    draw = ImageDraw.Draw(image)
    draw.rectangle((18, 18, 702, 882), outline=(20, 20, 20), width=2)
    draw.line((60, 690, 650, 390), fill=(0, 0, 0), width=4)
    if kind == "sigwx":
        for offset in range(0, 8):
            draw.arc((80 + offset * 35, 110, 620 - offset * 18, 650), 15, 210, fill=(25, 25, 25), width=3)
    elif kind == "wind":
        for y in range(40, 850, 8):
            draw.line((35, y, 690, y), fill=(70, 70, 70), width=3)
        for x in range(40, 690, 10):
            draw.line((x, 35, x, 850), fill=(90, 90, 90), width=2)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


with tempfile.TemporaryDirectory(prefix="opsroom-rc16-") as temp_dir:
    pdf_path = Path(temp_dir) / "simbrief.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((50, 60), "[ Airport WX List ]\nSIGMETs:\n No Wx data available\nTropical Cyclone SIGMETs:\n No Wx data available\nVolcanic Ash SIGMETs:\n No Wx data available\nDeparture:\nLOWW")
    page = document.new_page()
    page.insert_text((50, 60), "[ NOTAM ]\nLIDO-NOTAM-BULLETIN\nDEPARTURE AIRPORT - DETAILED INFO\nLOWW/VIE SCHWECHAT\n++++++++++++++++ AIRPORT ++++++++++++++++\nA1234/26\nRWY 11/29 CLSD")
    page = document.new_page()
    page.insert_text((50, 60), "DESTINATION AIRPORT - DETAILED INFO\nLOWI/INN INNSBRUCK\n++++++++++++++++ APPROACH PROCEDURES ++++++++++++++++\nB2345/26\nILS RWY 26 U/S\n[ Company NOTAM ]\nEND OF LIDO-NOTAM-BULLETIN")
    for kind in ("route", "sigwx", "wind"):
        page = document.new_page()
        page.insert_image(page.rect, stream=chart_png(kind))
    page = document.new_page()
    page.insert_text((50, 60), "End of Document")
    document.save(pdf_path)
    document.close()

    package = bd._extract_pdf_package(pdf_path)
    check(package.get("ok") is True, "Cached SimBrief PDF opens successfully")
    check(package.get("page_count") == 7, "PDF page count is retained")
    check(package.get("notam_pages") == [2, 3], "LIDO NOTAM page range is discovered")
    check([row.get("id") for row in package.get("notams", [])] == ["A1234/26", "B2345/26"], "Individual LIDO NOTAMs are parsed")
    check(package["notams"][0].get("scope", "").startswith("Departure airport"), "Departure NOTAM scope is preserved")
    check(package["notams"][1].get("scope", "").startswith("Destination airport"), "Destination NOTAM scope is preserved")
    check(package.get("sigmets") == [], "No-data SIGMET section is treated as genuinely empty")
    check(package.get("sigmet_states", {}).get("SIGMET") == "none", "Normal SIGMET no-data state is recorded")
    check(package.get("sigwx_pages") == [5], "Route map is skipped and sparse SIGWX page is discovered")

    old = (bd._current_plan, bd._pdf_path, bd._autorouter_notams, bd._awc_sigmets)
    try:
        bd._CACHE = None
        bd._CACHE_MONO = 0.0
        bd._current_plan = lambda: {
            "ok": True,
            "callsign": "AUA101",
            "route": "LOWW DCT LOWI",
            "origin": {"icao": "LOWW"},
            "destination": {"icao": "LOWI"},
            "alternate": {"icao": "LOWS"},
            "navlog": [{"type": "FIR", "ident": "LOVV"}],
            "files": {},
        }
        bd._pdf_path = lambda _plan: pdf_path
        bd._autorouter_notams = lambda _ids: ([], None)
        bd._awc_sigmets = lambda _ids: ([], {"name": "NOAA Aviation Weather Center", "state": "empty", "count": 0})
        briefing = bd.operational_briefing(force=True)
        check(briefing.get("ok") is True, "Operational Briefing is generated from cached PDF")
        check(len(briefing.get("notams", [])) == 2, "Operational Briefing exposes PDF NOTAMs")
        check(briefing.get("sigmet_summary", "").startswith("No current SIGMETs"), "No-SIGMET message is operational rather than an error")
        charts = briefing.get("sigwx", {}).get("charts", [])
        check(len(charts) == 1 and charts[0].get("page") == 5, "SIGWX API metadata identifies the real PDF page")
        check(charts[0].get("url") == "/api/briefing/simbrief-page/5.png", "SIGWX API supplies an in-app chart image URL")
        check(all(row.get("state") != "not_configured" for row in briefing.get("sources", [])), "Unconfigured optional providers are not shown as required setup")
        png = bd.simbrief_pdf_page_png(5)
        check(png.startswith(b"\x89PNG\r\n\x1a\n") and len(png) > 5000, "SimBrief chart page renders to a valid PNG")
    finally:
        bd._current_plan, bd._pdf_path, bd._autorouter_notams, bd._awc_sigmets = old
        bd._CACHE = None
        bd._CACHE_MONO = 0.0


briefing_source = (ROOT / "app/briefing_data.py").read_text(encoding="utf-8")
main_source = (ROOT / "app/main.py").read_text(encoding="utf-8")
ops_js = (ROOT / "app/static/opsroom.js").read_text(encoding="utf-8")
ops_css = (ROOT / "app/static/opsroom.css").read_text(encoding="utf-8")
pirep_js = (ROOT / "app/static/pirep.js").read_text(encoding="utf-8")
index_html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
requirements = (ROOT / "requirements_shipping.txt").read_text(encoding="utf-8")
spec = (ROOT / "OPS_ROOM.spec").read_text(encoding="utf-8")

check("ofp_cache_filename" in briefing_source and "_extract_pdf_package" in briefing_source, "Briefing retains cached-PDF fallback discovery")
check("_faa_nms_notams" not in briefing_source, "FAA NMS is not presented as a normal European-flight requirement")
check("/api/briefing/simbrief-page/{page_number}.png" in main_source, "Briefing PDF page image endpoint is registered")
check("briefing-simbrief-gallery" in ops_js and "data-briefing-image" in ops_js, "Briefing renders expandable SimBrief chart images")
check("Structured SimBrief OFP data" in ops_js and "briefingNotamSearch" in ops_js, "Structured NOTAM presentation and search are packaged")
check("#briefingContent>.briefing-section-tabs" in ops_css and "grid-column:1 / -1" in ops_css, "Briefing tabs and panels span the full content width")
check("grid-template-columns:repeat(7" in ops_css and "min-height:2.35rem" in ops_css, "Seven-section Briefing navigation is compact and horizontal")
check("PyMuPDF>=1.24" in requirements, "PyMuPDF runtime dependency is included")
check('collect_all("pymupdf")' in spec and "*pymupdf_binaries" in spec, "PyInstaller collects PyMuPDF data and binaries")

check("downloadPirepPdf" in pirep_js, "Full PIREP has a direct download function")
check("fetch(`/api/logbook/${encodeURIComponent(id)}/export.pdf`" in pirep_js, "Full PIREP downloads from the master browser-render endpoint")
check("pdfButton.addEventListener('click',()=>downloadPirepPdf" in pirep_js, "SAVE PDF no longer opens the print dialog")
check("/api/logbook/${encodeURIComponent(entry.id)}/export.pdf" in ops_js, "Logbook DOWNLOAD PDF uses the same Full PIREP endpoint")
check("DOWNLOAD PDF</a>" in index_html, "Logbook action is labelled DOWNLOAD PDF")

check("return [a,b,niceStep((b-a)/6)]" in pirep_js, "Zoomed X-axis gets a new tick interval")
check("tickCount=6" in pirep_js and "secondVisible=visibleRowsForX" in pirep_js, "Visible-window Y axes and dual axes are recalculated")
check("route2d:true" in pirep_js and "fullYExt" in pirep_js, "Route chart stores a two-dimensional zoom domain")
check("pctY" in pirep_js and "deltaY" in pirep_js, "Route wheel zoom and drag pan operate vertically as well as horizontally")
check("E / W OFFSET (NM)" in pirep_js and "N / S OFFSET (NM)" in pirep_js, "Route axes show viewport-aware NM scales")

version = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
check(version.get("version") == "0.24.48", "Version metadata is v0.24.48")
check(version.get("build") == "public-beta-release-candidate-18", "Version metadata is RC18")
check(version.get("codename") == "Final Release Integrity", "RC18 codename is Final Release Integrity")
check("OPS_ROOM_v0_24_48_Public_Beta_RC18_Windows_x64.zip" in (ROOT / "BUILD OPS ROOM COMPLETE.bat").read_text(encoding="utf-8"), "Complete build targets the RC18 Windows package")
check("New in v0.24.48" in (ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8"), "Release notes describe RC18")

print(json.dumps({"ok": True, "passed": len(passed), "checks": passed}, indent=2))
