from pathlib import Path
import json, sys
ROOT=Path(__file__).resolve().parents[1]
checks=[]
def check(name, ok):
    checks.append((name,bool(ok))); print(("PASS" if ok else "FAIL")+": "+name)
version=json.loads((ROOT/"version.json").read_text(encoding="utf-8"))
check("version 0.24.102", version.get("version")=="0.24.102")
check("airline resolver", (ROOT/"app/airline_branding.py").is_file())
settings=(ROOT/"app/settings_store.py").read_text(encoding="utf-8")
check("global branding setting", "airline_branding_enabled" in settings and "airline_icao_override" in settings)
main=(ROOT/"app/main.py").read_text(encoding="utf-8")
check("branding API", all(x in main for x in ["/api/airline-branding","/api/obs/branding"]))
ui=(ROOT/"app/static/opsroom.js").read_text(encoding="utf-8")
check("shared UI surfaces", all(x in ui for x in ["dispatchAirlineIdentity","watchAirlineIdentity","financeAirlineIdentity","groundAirlineIdentity","announcerAirlineIdentity","mapAirlineIdentity"]))
check("OBS branding modes", "active_airline" in ui and "obsBrandingMode" in ui)
pirep=(ROOT/"app/static/pirep.js").read_text(encoding="utf-8")
logbook=(ROOT/"app/logbook.py").read_text(encoding="utf-8")
check("PIREP airline hero", "pirepBrandHtml" in pirep)
check("self-contained PDF logo", "logo_data_uri" in logbook and "logo_data_uri" in logbook)
check("3,946-logo package", len(list((ROOT/"app/assets/logos").glob("*.png")))==3946)
check("short build root", "%TEMP%\\OR102" in (ROOT/"BUILD WINDOWS APP ONLY.bat").read_text(encoding="utf-8") and "BRIDGE_BUILD_DIR=%OPSROOM_BUILD_ROOT%\\camera_bridge" in (ROOT/"BUILD CAMERA BRIDGE 2024.bat").read_text(encoding="utf-8"))
check("Black Box branding", "blackBoxAirlineIdentity" in ui and "resolve_airline_branding" in main)
failed=[name for name,ok in checks if not ok]
print(f"RESULT: {len(checks)-len(failed)}/{len(checks)} checks passed")
sys.exit(1 if failed else 0)
