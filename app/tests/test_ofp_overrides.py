"""Regression tests for live OFP manual overrides -- v0.25.65.

Covers the override store (whitelist, validation, persistence) and the pure
builder merge (manual times, weights, fuel; derived block/trip recompute;
manual marking in the payload).  Plain-Python PASS/FAIL harness, no network.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# Point the override store at a throwaway file before importing the store so
# tests never touch the user's real override data.
_TMP = tempfile.mkdtemp(prefix="opsroom_ofp_overrides_test_")

import app.ofp_overrides as store  # noqa: E402

store._store_path = Path(_TMP) / "ofp_overrides.json"
store._store.clear()
store._load_attempted = True

from app.ofp_actuals import build_live_ofp_actuals, plan_from_entry  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if condition:
        PASS += 1
        return True
    FAIL += 1
    print(f"  FAIL {name}" + (f" -- {detail}" if detail else ""))
    return False


def _plan() -> dict:
    return {
        "ok": True,
        "request_id": "TEST-REQ-1",
        "sequence_id": "SEQ-1",
        "plan_id": "PLAN-1",
        "generated_utc": "2026-08-06T12:00:00Z",
        "callsign": "OR1234",
        "origin": {"icao": "EGKK"},
        "destination": {"icao": "EDDF"},
        "aircraft": {"registration": "G-TEST"},
        "times": {
            "scheduled_out": "2026-08-06T12:15:00Z",
            "scheduled_off": "2026-08-06T12:30:00Z",
            "scheduled_on": "2026-08-06T13:45:00Z",
            "scheduled_in": "2026-08-06T14:00:00Z",
        },
        "block_time_seconds": 6300,
        "fuel": {
            "units": "LBS",
            "ramp": 19400,
            "takeoff": 19000,
            "trip": 9800,
            "landing": 9200,
            "reserve": 4200,
            "alternate": 3100,
            "extra": 500,
        },
        "weights": {
            "units": "LBS",
            "passengers": 120,
            "cargo": 4500,
            "payload": 14500,
            "zfw": 108700,
            "tow": 116400,
            "ldw": 113900,
            "max_zfw": 110000,
            "max_tow": 120000,
            "max_ldw": 115000,
        },
    }


def _recorder(overrides_flight: dict | None = None) -> dict:
    flight = {
        "weight_units": "LBS",
        "fuel_units": "LBS",
        "passengers": 120,
        "cargo_hold_total": 4500,
        "payload": 14500,
        "planned_zfw": 108700,
        "planned_tow": 116400,
        "planned_ldw": 113900,
        "planned_max_zfw": 110000,
        "planned_max_tow": 120000,
        "planned_max_ldw": 115000,
        "planned_ramp_fuel": 8600,
        "planned_takeoff_fuel": 8400,
        "planned_trip_fuel": 5600,
        "planned_landing_fuel": 2800,
        "planned_reserve_fuel": 1800,
        "planned_alternate_fuel": 700,
        "planned_extra_fuel": 300,
        "operation_type_requested": "auto",
        "operation_type_resolved": "passenger",
    }
    if overrides_flight:
        flight.update(overrides_flight)
    return {
        "id": "REC-1",
        "started_utc": "2026-08-06T12:10:00Z",
        "phase": "CRUISE",
        "telemetry_source": "fsuipc7",
        "updated_utc": "2026-08-06T13:00:00Z",
        "times": {
            "block_out": "2026-08-06T12:17:00Z",
            "takeoff": "2026-08-06T12:31:00Z",
            "landing": "2026-08-06T13:47:00Z",
            "block_in": "2026-08-06T14:02:00Z",
        },
        "operational_snapshots": {
            "out": {"time_utc": "2026-08-06T12:17:00Z", "fuel_lb": 8600, "calculated_zfw_lb": 108700, "estimated": False},
            "off": {"time_utc": "2026-08-06T12:31:00Z", "fuel_lb": 8400, "gross_weight_lb": 116400},
            "on": {"time_utc": "2026-08-06T13:47:00Z", "fuel_lb": 2800, "gross_weight_lb": 113900},
            "in": {"time_utc": "2026-08-06T14:02:00Z", "fuel_lb": 2500},
        },
        "flight": flight,
        "ofp_plan": {
            "identity": {"request_id": "TEST-REQ-1", "callsign": "OR1234", "origin": "EGKK", "destination": "EDDF", "scheduled_out": "2026-08-06T12:15:00Z"},
            "times": {"scheduled_out": "2026-08-06T12:15:00Z", "scheduled_off": "2026-08-06T12:30:00Z", "scheduled_on": "2026-08-06T13:45:00Z", "scheduled_in": "2026-08-06T14:00:00Z"},
            "units": {"weight": "LBS", "fuel": "LBS"},
        },
    }


# ---------------------------------------------------------------------------
# Store: whitelist + validation + persistence
# ---------------------------------------------------------------------------


def test_store_validation() -> None:
    store._store.clear()
    valid, errors = store.set_overrides("REC-1", {"times:out": "1617Z", "weights:zfw": 108.7, "fuel:ramp": 8600, "bogus:key": 1})
    check("unknown override key rejected", "bogus:key" in errors, str(errors))
    check("valid keys accepted", valid.get("times:out") == "1617" and valid.get("weights:zfw") == 108.7, str(valid))
    check("bad time rejected", "times:off" in store.set_overrides("REC-1", {"times:off": "25:99"})[1])
    check("negative weight rejected", "weights:tow" in store.set_overrides("REC-1", {"weights:tow": -5})[1])
    check("non-numeric fuel rejected", "fuel:blockin" in store.set_overrides("REC-1", {"fuel:blockin": "lots"})[1])


def test_store_persistence() -> None:
    store._store.clear()
    store.set_overrides("REC-1", {"times:in": "1402"})
    path = store.store_path()
    check("persisted file written", path.exists())
    saved = json.loads(path.read_text(encoding="utf-8"))
    check("persisted value survives reload", saved.get("REC-1", {}).get("times:in") == "1402", str(saved))
    store._store.clear()
    store._load_attempted = False
    reloaded = store.get_overrides("REC-1")
    check("get_overrides reloads from disk", reloaded.get("times:in") == "1402", str(reloaded))
    store.remove_override("REC-1", "times:in")
    check("remove_override clears single key", store.get_overrides("REC-1") == {})
    store.clear_overrides("REC-1")
    check("clear_overrides removes entry", store.get_overrides("REC-1") == {})


# ---------------------------------------------------------------------------
# Builder merge: times
# ---------------------------------------------------------------------------


def test_manual_time_merge() -> None:
    payload = build_live_ofp_actuals(_plan(), _recorder(), overrides={"times:out": "1218"})
    out = payload["times"]["out"]
    check("manual OUT applied", out.get("actual_utc", "").startswith("2026-08-06T12:18"), str(out))
    check("manual OUT source", out.get("source") == "manual" and out.get("manual") is True)
    check("manual OUT not estimated", out.get("estimated") is False)
    check("manual OUT delta recomputed", out.get("delta_seconds") == 180, str(out))  # 12:18 - 12:15
    # Full ISO accepted as-is.
    payload2 = build_live_ofp_actuals(_plan(), _recorder(), overrides={"times:on": "2026-08-06T13:40:00Z"})
    check("full ISO override accepted", payload2["times"]["on"].get("actual_utc") == "2026-08-06T13:40:00Z")


def test_manual_block_recompute() -> None:
    payload = build_live_ofp_actuals(_plan(), _recorder(), overrides={"times:out": "1218", "times:in": "1404"})
    block = payload["times"]["block"]
    check("block recomputed from manual times", block.get("actual_seconds") == (14 * 60 + 4) * 60 - (12 * 60 + 18) * 60, str(block))
    planned = block.get("planned_seconds")
    check("planned block retained", planned == 6300, str(planned))


# ---------------------------------------------------------------------------
# Builder merge: weights (display-unit entry -> plan-unit comparison)
# ---------------------------------------------------------------------------


def test_manual_weight_lb_direct() -> None:
    # Plan unit is LBS; entry unit is LBS -> no conversion.
    payload = build_live_ofp_actuals(_plan(), _recorder(), overrides={"weights:zfw": 109000})
    zfw = payload["weights"]["zfw"]
    check("manual ZFW applied", zfw.get("actual") == 109000.0, str(zfw))
    check("manual ZFW source", zfw.get("source") == "manual" and zfw.get("manual") is True)
    check("manual ZFW availability", zfw.get("availability") == "available")


def test_manual_weight_display_unit_conversion() -> None:
    # Display unit KG (host override); plan unit LBS.  49500 kg -> ~109128 lb.
    payload = build_live_ofp_actuals(_plan(), _recorder(), settings_override_unit="kg", overrides={"weights:tow": 49500})
    tow = payload["weights"]["tow"]
    check("manual TOW converted to plan lbs", tow.get("actual") is not None and 109000 < tow["actual"] < 109300, str(tow.get("actual")))
    check("manual TOW display shows kg", tow.get("actual_display") is not None and abs(tow["actual_display"] - 49500) < 1, str(tow.get("actual_display")))


def test_manual_pax() -> None:
    payload = build_live_ofp_actuals(_plan(), _recorder(), overrides={"weights:pax": 130})
    pax = payload["weights"]["passengers"]
    check("manual PAX applied", pax.get("actual") == 130 and pax.get("source") == "manual" and pax.get("manual") is True, str(pax))


# ---------------------------------------------------------------------------
# Live loading progress (GSX/Fenix boarding) -> measured PAX + BAG/CARGO
# ---------------------------------------------------------------------------


def test_loading_progress_pax_and_cargo() -> None:
    loading = {
        "passengers": 87,
        "target": 120,
        "boarding_cargo_percent": 65,
        "fenix": {"ok": True, "pax_loaded": 91, "cargo_loaded_kg": 1325.0},
        "updated_at": "2026-08-09T10:00:00Z",
    }
    payload = build_live_ofp_actuals(_plan(), _recorder(), loading_progress=loading)
    pax = payload["weights"]["passengers"]
    bags = payload["weights"]["bags_cargo"]
    check("Fenix PAX beats GSX count", pax.get("actual") == 91, str(pax))
    check("PAX availability", pax.get("availability") == "available" and pax.get("source") == "gsx/fenix loading", str(pax))
    # 1325 kg cargo -> plan unit LBS (1 kg = 2.20462 lb) ~ 2921 lb
    check("Fenix cargo kg converted to plan lbs", bags.get("actual") is not None and 2900 < bags["actual"] < 2945, str(bags.get("actual")))
    # #58: PAYLOAD actual = pax block + cargo. Plan split: payload 14500 - cargo
    # 4500 = 10000 lb over 120 pax -> 83.33 lb/pax. 91 pax * 83.33 + 2921 cargo
    # ~ 10504 lb.
    pl = payload["weights"]["payload"]
    check("PAYLOAD auto-fill from pax block + cargo", pl.get("actual") is not None and 10400 < pl["actual"] < 10600, str(pl.get("actual")))
    check("PAYLOAD availability", pl.get("availability") == "available" and pl.get("source") == "gsx/fenix loading", str(pl))


def test_loading_progress_payload_requires_both_sources() -> None:
    # Only pax measured, no cargo -> payload stays unavailable (never fabricate).
    loading = {"passengers": 87, "fenix": {"ok": True, "pax_loaded": 91}}
    payload = build_live_ofp_actuals(_plan(), _recorder(), loading_progress=loading)
    pl = payload["weights"]["payload"]
    check("PAYLOAD stays unavailable when cargo missing", pl.get("actual") is None and pl.get("availability") == "unavailable", str(pl))
    # Only cargo measured, no pax -> payload stays unavailable.
    loading2 = {"fenix": {"ok": True, "cargo_loaded_kg": 1000.0}}
    payload2 = build_live_ofp_actuals(_plan(), _recorder(), loading_progress=loading2)
    pl2 = payload2["weights"]["payload"]
    check("PAYLOAD stays unavailable when pax missing", pl2.get("actual") is None and pl2.get("availability") == "unavailable", str(pl2))
    # No loading at all -> stays unavailable.
    payload3 = build_live_ofp_actuals(_plan(), _recorder())
    pl3 = payload3["weights"]["payload"]
    check("PAYLOAD unavailable without loading source", pl3.get("actual") is None and pl3.get("availability") == "unavailable", str(pl3))


def test_loading_progress_gsx_fallback() -> None:
    # No Fenix fields -> GSX boarding count + cargo percent against planned hold.
    loading = {"passengers": 64, "target": 120, "boarding_cargo_percent": 50}
    payload = build_live_ofp_actuals(_plan(), _recorder(), loading_progress=loading)
    pax = payload["weights"]["passengers"]
    bags = payload["weights"]["bags_cargo"]
    check("GSX PAX fallback", pax.get("actual") == 64 and pax.get("availability") == "available", str(pax))
    check("cargo percent against planned hold", bags.get("actual") is not None and abs(bags["actual"] - 2250.0) < 1, str(bags.get("actual")))  # 4500 lb * 50%


def test_loading_progress_ignored_when_manual() -> None:
    loading = {"passengers": 87, "boarding_cargo_percent": 65}
    payload = build_live_ofp_actuals(_plan(), _recorder(), overrides={"weights:pax": 130}, loading_progress=loading)
    pax = payload["weights"]["passengers"]
    check("manual PAX outranks loading", pax.get("actual") == 130 and pax.get("manual") is True, str(pax))


def test_loading_progress_none_stays_unavailable() -> None:
    payload = build_live_ofp_actuals(_plan(), _recorder())
    pax = payload["weights"]["passengers"]
    bags = payload["weights"]["bags_cargo"]
    check("no loading -> PAX unavailable", pax.get("availability") == "unavailable" and pax.get("actual") is None, str(pax))
    check("no loading -> cargo unavailable", bags.get("availability") == "unavailable" and bags.get("actual") is None, str(bags))


# ---------------------------------------------------------------------------
# Builder merge: fuel (incl. derived trip + surplus)
# ---------------------------------------------------------------------------


def test_manual_fuel_and_derived_trip() -> None:
    payload = build_live_ofp_actuals(_plan(), _recorder(), overrides={"fuel:takeoff": 8500, "fuel:landing": 2600})
    fuel = payload["fuel"]
    check("manual takeoff fuel applied", fuel["takeoff_off"].get("source") == "manual" and fuel["takeoff_off"].get("actual") == 8500.0, str(fuel["takeoff_off"]))
    check("manual landing fuel applied", fuel["landing_on"].get("manual") is True and fuel["landing_on"].get("actual") == 2600.0)
    check("trip recomputed from manual fuels", fuel["trip"].get("actual") == 5900.0, str(fuel["trip"]))  # 8500 - 2600
    check("trip source is subtraction", fuel["trip"].get("source") == "off-on subtraction")


def test_manual_blockin_surplus() -> None:
    payload = build_live_ofp_actuals(_plan(), _recorder(), overrides={"fuel:blockin": 2800})
    surplus = payload["fuel"]["extra_surplus"]
    # 2800 - (1800 reserve + 700 alternate)
    check("surplus recomputed from manual block-in", surplus.get("actual") == 300.0, str(surplus))


# ---------------------------------------------------------------------------
# Payload surface
# ---------------------------------------------------------------------------


def test_manual_overrides_in_payload() -> None:
    overrides = {"times:out": "1218", "weights:zfw": 109000, "fuel:ramp": 8700}
    payload = build_live_ofp_actuals(_plan(), _recorder(), overrides=overrides)
    check("manual_overrides echoed in payload", payload.get("manual_overrides") == overrides, str(payload.get("manual_overrides")))
    check("revision changes when overrides change", build_live_ofp_actuals(_plan(), _recorder(), overrides=overrides)["revision"] != build_live_ofp_actuals(_plan(), _recorder())["revision"])


def test_override_ignores_unknown_keys() -> None:
    payload = build_live_ofp_actuals(_plan(), _recorder(), overrides={"bogus:key": 5, "times:out": "1218"})
    check("unknown keys filtered from payload", "bogus:key" not in payload.get("manual_overrides", {}), str(payload.get("manual_overrides")))
    check("known keys still applied", payload["times"]["out"].get("source") == "manual")


def test_no_recorder_state_unaffected() -> None:
    payload = build_live_ofp_actuals(_plan(), None, overrides={"times:out": "1218"})
    check("no recorder still returns waiting", payload.get("state") == "waiting")
    check("previous-flight overrides never leak into a waiting plan", payload.get("manual_overrides") == {}, str(payload.get("manual_overrides")))
    check("waiting payload still renders planned values", payload["times"]["out"].get("scheduled_utc") is not None)
    check("waiting payload carries planned fuel", payload["fuel"]["ramp_out"].get("planned") is not None)
    check("waiting payload carries planned weights", payload["weights"]["tow"].get("planned") is not None)


def test_manual_time_midnight_crossing() -> None:
    # Scheduled 23:50, pilot types 0005 (next UTC day): must not land on the
    # scheduled day with an absurd negative delta.
    plan = _plan()
    plan["times"] = {"scheduled_off": "2026-08-06T23:50:00Z"}
    payload = build_live_ofp_actuals(plan, _recorder(), overrides={"times:off": "0005"})
    off = payload["times"]["off"]
    check("midnight-crossing manual time pushes to next day", (off.get("actual_utc") or "").startswith("2026-08-07T00:05"), str(off.get("actual_utc")))
    check("midnight-crossing delta is small positive", off.get("delta_seconds") == 15 * 60, str(off.get("delta_seconds")))


def test_manual_time_date_from_recorder_start() -> None:
    # No scheduled time reference -> date taken from recorder start (12:10).
    plan = _plan()
    plan["times"] = {}
    payload = build_live_ofp_actuals(plan, _recorder(), overrides={"times:off": "1230"})
    off = payload["times"]["off"]
    check("manual time uses recorder date", (off.get("actual_utc") or "").startswith("2026-08-06T12:30"), str(off))


# ---------------------------------------------------------------------------
# Completed-entry (PIREP) path + Logbook export attachment
# ---------------------------------------------------------------------------


def _completed_entry() -> dict:
    rec = _recorder()
    return {
        "id": rec["id"],
        "started_utc": rec["started_utc"],
        "times": rec["times"],
        "operational_snapshots": rec["operational_snapshots"],
        # Real completed entries carry the immutable plan reference inside the
        # ``flight`` snapshot (``flight.ofp_plan``) -- plan_from_entry reads it
        # from there, so the fixture must nest it the same way.
        "flight": {**rec["flight"], "ofp_plan": rec["ofp_plan"]},
    }


def test_completed_entry_builder_merges_overrides() -> None:
    # The PIREP path rebuilds the plan from a completed entry and must surface
    # manual values exactly like the live panel does.
    entry = _completed_entry()
    payload = build_live_ofp_actuals(plan_from_entry(entry), None, completed_entry=entry, overrides={"times:out": "1218", "weights:zfw": 109000})
    out = payload["times"]["out"]
    check("completed-entry builder applies manual OUT", out.get("source") == "manual" and out.get("manual") is True, str(out))
    check("completed-entry builder keeps phase actual fallback", out.get("estimated") is False)
    zfw = payload["weights"]["zfw"]
    check("completed-entry builder applies manual ZFW", zfw.get("source") == "manual" and zfw.get("actual") == 109000.0, str(zfw))
    check("completed-entry builder echoes manual_overrides", payload.get("manual_overrides", {}).get("times:out") == "1218", str(payload.get("manual_overrides")))
    check("completed-entry builder no overrides stays empty", build_live_ofp_actuals(plan_from_entry(entry), None, completed_entry=entry).get("manual_overrides") == {})


def test_exports_attach_manual_overrides() -> None:
    import csv as _csv
    import io as _io
    import sqlite3 as _sqlite3

    import app.logbook as logbook

    db = Path(_TMP) / "logbook.sqlite3"
    logbook._db_path = lambda: db
    if db.exists():
        db.unlink()
    with _sqlite3.connect(db) as conn:
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS flights(id TEXT PRIMARY KEY, started_utc TEXT NOT NULL, completed_utc TEXT, status TEXT NOT NULL, metadata_json TEXT NOT NULL, rating INTEGER NOT NULL DEFAULT 0, notes TEXT NOT NULL DEFAULT '', updated_utc TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS samples(id INTEGER PRIMARY KEY AUTOINCREMENT, flight_id TEXT NOT NULL, sampled_utc TEXT NOT NULL, elapsed_seconds REAL NOT NULL, data_json TEXT NOT NULL);"
        )
        conn.execute(
            "INSERT OR REPLACE INTO flights(id, started_utc, completed_utc, status, metadata_json, rating, notes, updated_utc) VALUES (?,?,?,?,?,?,?,?)",
            ("FLT-EXPORT-1", "2026-08-06T10:00:00Z", "2026-08-06T12:00:00Z", "COMPLETE",
             json.dumps({"id": "FLT-EXPORT-1", "started_utc": "2026-08-06T10:00:00Z", "state": "COMPLETE", "flight": {"callsign": "OR123", "origin": "EGKK", "destination": "EDDF"}}),
             4, "note", "2026-08-06T12:00:00Z"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO flights(id, started_utc, completed_utc, status, metadata_json, rating, notes, updated_utc) VALUES (?,?,?,?,?,?,?,?)",
            ("FLT-EXPORT-2", "2026-08-06T14:00:00Z", "2026-08-06T15:30:00Z", "COMPLETE",
             json.dumps({"id": "FLT-EXPORT-2", "started_utc": "2026-08-06T14:00:00Z", "state": "COMPLETE", "flight": {"callsign": "OR456", "origin": "EDDF", "destination": "EGKK"}}),
             5, "", "2026-08-06T15:30:00Z"),
        )
    store._store.clear()
    store.set_overrides("FLT-EXPORT-1", {"times:out": "1017", "weights:zfw": 108.7})

    from app.briefing_data import _app_version as _bd_version
    _expected_version = str(_bd_version() or "0.25.77")
    payload = json.loads(logbook.export_json())
    check("export_json stamps real app version", str(payload.get("version")) == _expected_version, str(payload.get("version")))
    entry = next((e for e in payload["entries"] if e.get("id") == "FLT-EXPORT-1"), None)
    check("export_json attaches manual_overrides", entry is not None and entry.get("manual_overrides") == {"times:out": "1017", "weights:zfw": 108.7}, str(entry))
    check("export_json preserves existing fields", entry is not None and (entry.get("flight") or {}).get("callsign") == "OR123", str(entry))
    check("export_json leaves other entries untouched", all("manual_overrides" not in e for e in payload["entries"] if e.get("id") != "FLT-EXPORT-1"), str([e.get("id") for e in payload["entries"]]))

    text = logbook.export_csv().decode("utf-8-sig")
    rows = list(_csv.DictReader(_io.StringIO(text)))
    row = next((r for r in rows if r.get("callsign") == "OR123"), None)
    check("export_csv appends manual_overrides column", row is not None and row.get("manual_overrides") == json.dumps({"times:out": "1017", "weights:zfw": 108.7}, separators=(",", ":")), str(row))
    check("export_csv keeps existing columns", row is not None and row.get("callsign") == "OR123" and row.get("origin") == "EGKK" and row.get("status") == "COMPLETE", str(row))
    row2 = next((r for r in rows if r.get("callsign") == "OR456"), None)
    check("export_csv leaves other rows blank", row2 is not None and row2.get("manual_overrides") == "", str(row2))

    store.clear_overrides("FLT-EXPORT-1")


def test_prune_orphaned() -> None:
    store._store.clear()
    store.set_overrides("KEEP-1", {"times:out": "1000"})
    store.set_overrides("KEEP-2", {"times:in": "1130"})
    store.set_overrides("GONE-1", {"weights:zfw": 100000})
    removed = store.prune_orphaned(["KEEP-1", "KEEP-2"])
    check("prune_orphaned removes only unknown ids", removed == 1 and store.get_overrides("GONE-1") == {}, f"removed={removed}")
    check("prune_orphaned keeps known ids", store.get_overrides("KEEP-1").get("times:out") == "1000" and store.get_overrides("KEEP-2").get("times:in") == "1130")
    check("prune_orphaned persists removal", json.loads(store.store_path().read_text(encoding="utf-8")) == {"KEEP-1": {"times:out": "1000"}, "KEEP-2": {"times:in": "1130"}}, "")
    check("prune_orphaned with empty known removes all", store.prune_orphaned([]) == 2)
    check("prune_orphaned idempotent", store.prune_orphaned(["KEEP-1", "KEEP-2"]) == 0)
    store._store.clear()


def test_fenix_loadsheet_fills_tow_zfw_ldw() -> None:
    """#60: the Fenix EFB FINAL loadsheet fills TOW/ZFW/LDW actuals + maxes."""
    sheet = {
        "ok": True,
        "tow_kg": 52800.0,
        "zfw_kg": 49350.0,
        "law_kg": 51650.0,
        "max_tow_kg": 73500.0,
        "max_zfw_kg": 61000.0,
        "max_law_kg": 64500.0,
        "mac_tow": 30.6,
        "mac_zfw": 32.5,
    }
    payload = build_live_ofp_actuals(_plan(), _recorder(), loading_progress=None, fenix_loadsheet=sheet)
    weights = payload.get("weights") or {}
    tow = weights.get("tow") or {}
    zfw = weights.get("zfw") or {}
    ldw = weights.get("ldw") or {}
    # 52800 kg = 116,404 lb; 49350 kg = 108,798 lb; 51650 kg = 113,869 lb
    check("fenix TOW actual filled", tow.get("actual") is not None and abs(tow["actual"] - 116404.0) < 2.0, str(tow))
    check("fenix ZFW actual filled", zfw.get("actual") is not None and abs(zfw["actual"] - 108798.0) < 2.0, str(zfw))
    check("fenix LDW actual filled", ldw.get("actual") is not None and abs(ldw["actual"] - 113869.0) < 2.0, str(ldw))
    check("fenix TOW source", tow.get("source") == "fenix final loadsheet", str(tow))
    check("fenix TOW max from loadsheet", tow.get("max") is not None and abs(tow["max"] - 162040.0) < 2.0, str(tow))
    check("fenix ZFW max from loadsheet", zfw.get("max") is not None and abs(zfw["max"] - 134482.0) < 2.0, str(zfw))
    check("fenix LDW max from loadsheet", ldw.get("max") is not None and abs(ldw["max"] - 142198.0) < 2.0, str(ldw))


def test_fenix_loadsheet_absent_falls_back_to_snapshots() -> None:
    """#60: without the loadsheet the snapshot path still fills TOW/ZFW/LDW."""
    payload = build_live_ofp_actuals(_plan(), _recorder())
    weights = payload.get("weights") or {}
    tow = weights.get("tow") or {}
    zfw = weights.get("zfw") or {}
    check("snapshot TOW fallback kept", abs((tow.get("actual") or 0) - 116400.0) < 2.0, str(tow))
    check("snapshot ZFW fallback kept", abs((zfw.get("actual") or 0) - 108700.0) < 2.0, str(zfw))
    check("snapshot TOW source", tow.get("source") == "off-snapshot", str(tow))


def main() -> None:
    test_store_validation()
    test_store_persistence()
    test_manual_time_merge()
    test_manual_block_recompute()
    test_manual_weight_lb_direct()
    test_manual_weight_display_unit_conversion()
    test_manual_pax()
    test_manual_fuel_and_derived_trip()
    test_manual_blockin_surplus()
    test_manual_overrides_in_payload()
    test_override_ignores_unknown_keys()
    test_no_recorder_state_unaffected()
    test_manual_time_date_from_recorder_start()
    test_manual_time_midnight_crossing()
    test_completed_entry_builder_merges_overrides()
    test_exports_attach_manual_overrides()
    test_prune_orphaned()
    test_fenix_loadsheet_fills_tow_zfw_ldw()
    test_fenix_loadsheet_absent_falls_back_to_snapshots()

    print("=" * 60)
    total = PASS + FAIL
    print(f"RESULTS: {PASS}/{total} PASS, {FAIL} FAIL")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
