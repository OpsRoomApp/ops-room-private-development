"""Regression tests for the #62 electronic loadsheet signature.

Covers the dedicated ``loadsheet_signatures`` table (created in logbook._init_db),
the get/set/clear helpers, and the pre-departure lock (no re-sign/clear after
takeoff or after the flight completes).  Plain-Python PASS/FAIL harness, no
network, throwaway DB.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

_TMP = tempfile.mkdtemp(prefix="opsroom_loadsheet_sign_test_")

# Point app_data_dir at the throwaway folder BEFORE importing logbook so the
# module-level _init_db_safe() builds the schema on the temp DB only.
import app.settings_store as settings_store  # noqa: E402

settings_store.app_data_dir = lambda: Path(_TMP)

import app.logbook as lb  # noqa: E402

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


def _insert_flight(flight_id: str, status: str = "RECORDING", times: dict | None = None, phase: str = "") -> None:
    meta = {
        "id": flight_id,
        "flight": {"callsign": "OR1234", "origin": "EGKK", "destination": "EDDF"},
        "phase": phase,
        "times": times or {},
    }
    with lb._connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO flights(id,started_utc,completed_utc,status,metadata_json,rating,notes,updated_utc) VALUES(?,?,?,?,?,?,?,?)",
            (flight_id, "2026-08-06T12:00:00Z", None if status == "RECORDING" else "2026-08-06T14:00:00Z",
             status, json.dumps(meta), 0, "", "2026-08-06T12:00:00Z"),
        )


# 1. unsigned flight -> None, never raises
check("unsigned returns None", lb.get_loadsheet_signature("FLT-A") is None)
check("unsigned empty id", lb.get_loadsheet_signature("") is None)
check("unsigned None id", lb.get_loadsheet_signature(None) is None)

# 2. set -> stored, get -> same snapshot
_insert_flight("FLT-A")
snapshot = {"tow": {"planned": 64284, "actual": 64500}, "phase": "PARKED", "signed_at": "2026-08-06T12:05:00Z"}
stored = lb.set_loadsheet_signature("FLT-A", "A. PILOT", role="CAPTAIN", sig_data_url="data:image/png;base64,AAAA", snapshot=snapshot)
check("set returns signer", stored.get("signer") == "A. PILOT", str(stored))
fetched = lb.get_loadsheet_signature("FLT-A")
check("get returns signer", fetched and fetched.get("signer") == "A. PILOT")
check("get returns role", fetched and fetched.get("role") == "CAPTAIN")
check("get returns png url", fetched and fetched.get("sig_data_url", "").startswith("data:image/png;base64,"))
check("get returns snapshot", fetched and fetched.get("snapshot", {}).get("tow", {}).get("actual") == 64500)
check("get returns signed_utc", fetched and bool(fetched.get("signed_utc")))

# 3. replace (re-sign) updates signer, keeps one row
lb.set_loadsheet_signature("FLT-A", "B. OFFICER", role="FIRST OFFICER", sig_data_url="", snapshot={})
fetched2 = lb.get_loadsheet_signature("FLT-A")
check("re-sign replaces signer", fetched2 and fetched2.get("signer") == "B. OFFICER")
with lb._connect() as conn:
    count = conn.execute("SELECT COUNT(*) FROM loadsheet_signatures WHERE flight_id='FLT-A'").fetchone()[0]
check("one row per flight", count == 1, str(count))

# 4. lock: RECORDING + no takeoff -> unlocked
_insert_flight("FLT-B")
rec = {"id": "FLT-B", "status": "RECORDING", "phase": "PARKED", "times": {}}
check("parked recording unlocked", lb.loadsheet_signature_locked(rec) is False)

# 5. lock: takeoff recorded -> locked
_insert_flight("FLT-C", times={"takeoff": "2026-08-06T12:30:00Z"})
rec_c = {"id": "FLT-C", "status": "RECORDING", "phase": "TAXI OUT", "times": {"takeoff": "2026-08-06T12:30:00Z"}}
check("takeoff time locks", lb.loadsheet_signature_locked(rec_c) is True)

# 6. lock: phase in the air -> locked even without a takeoff time
_insert_flight("FLT-D", phase="CLIMB")
rec_d = {"id": "FLT-D", "status": "RECORDING", "phase": "CLIMB", "times": {}}
check("airborne phase locks", lb.loadsheet_signature_locked(rec_d) is True)

# 7. lock: completed flight -> locked
_insert_flight("FLT-E", status="COMPLETE")
rec_e = {"id": "FLT-E", "status": "COMPLETE", "phase": "TAXI IN", "times": {}}
check("completed locks", lb.loadsheet_signature_locked(rec_e) is True)

# 8. lock: None entry -> locked (defensive)
check("no entry locks", lb.loadsheet_signature_locked(None) is True)

# 9. clear removes
_insert_flight("FLT-A")
lb.set_loadsheet_signature("FLT-A", "A. PILOT", snapshot={})
check("clear returns True", lb.clear_loadsheet_signature("FLT-A") is True)
check("cleared returns None", lb.get_loadsheet_signature("FLT-A") is None)
check("clear missing returns False", lb.clear_loadsheet_signature("FLT-A") is False)

# 10. get_entry surfaces the signed block (logbook detail / PIREP surface)
_insert_flight("FLT-G")
lb.set_loadsheet_signature("FLT-G", "A. PILOT", role="CAPTAIN", sig_data_url="data:image/png;base64,BBBB", snapshot={"tow": {"actual": 1}})
entry = lb.get_entry("FLT-G")
check("get_entry carries signed block", entry and entry.get("signed") and entry["signed"].get("signer") == "A. PILOT", str(entry.get("signed")) if entry else "no entry")

print(f"\n{'-' * 44}\nloadsheet signature tests: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
