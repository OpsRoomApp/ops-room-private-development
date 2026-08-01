from __future__ import annotations

import copy
import json
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import economy
from app import gsx_remote
from app import pirep_analysis as pa

passed: list[str] = []

def check(condition, name: str) -> None:
    if not condition:
        raise AssertionError(name)
    passed.append(name)

check(pa._sample_time({'elapsed_seconds': 12.5}) == 12.5, 'Stored elapsed_seconds is accepted as the primary sample clock')

# Build a coherent synthetic flight with a clean FSUIPC -> SimConnect handover
# during final approach and deliberately late recorder phase labels.
runways = {
    'TEST': {
        'runway': '01', 'name_a': '01', 'name_b': '19', 'heading_deg': 0.0,
        'threshold_lat': 0.0, 'threshold_lon': 0.0, 'threshold_elevation_ft': 100.0,
        'length_ft': 8000.0, 'width_ft': 150.0, 'lda_ft': 8000.0, 'displaced_threshold_ft': 0.0,
    },
    'DEST': {
        'runway': '01', 'name_a': '01', 'name_b': '19', 'heading_deg': 0.0,
        'threshold_lat': 1.0, 'threshold_lon': 0.0, 'threshold_elevation_ft': 100.0,
        'length_ft': 8000.0, 'width_ft': 150.0, 'lda_ft': 8000.0, 'displaced_threshold_ft': 0.0,
    },
}
orig_by_name = pa.navdata.runway_by_name
orig_nearest = pa.navdata.nearest_runway_end
pa.navdata.runway_by_name = lambda airport, runway: copy.deepcopy(runways.get(str(airport).upper()))
pa.navdata.nearest_runway_end = lambda lat, lon, airport, track, max_nm=8.0: copy.deepcopy(runways.get(str(airport).upper()))

base = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
rows: list[dict] = []

def add(elapsed: float, **values) -> None:
    defaults = {
        'time': (base + timedelta(seconds=elapsed)).isoformat().replace('+00:00', 'Z'),
        'elapsed_seconds': elapsed,
        'source': 'fsuipc7', 'on_ground': False,
        'track_deg': 0.0, 'heading_deg': 0.0,
        'ground_speed_kts': 145.0, 'ias_kts': 140.0, 'indicated_speed_kts': 140.0,
        'vertical_speed_fpm': -700.0, 'pitch_deg': 2.5, 'bank_deg': 0.2,
        'gear_percent': 100.0, 'flap_percent': 35.0, 'fuel_total_lb': 9000.0,
    }
    defaults.update(values)
    rows.append(defaults)

# Departure roll and lift-off.
for i in range(8):
    add(i * 2.0, lat=-0.002 + i * 0.00025, lon=0.0, on_ground=True,
        ground_speed_kts=i * 18.0, ias_kts=i * 18.0, indicated_speed_kts=i * 18.0,
        vertical_speed_fpm=0.0, phase='TAKEOFF ROLL', altitude_ft=100.0, agl_ft=0.0, radio_altitude_ft=0.0)
add(16.0, lat=0.0005, lon=0.0, on_ground=False, ground_speed_kts=145.0,
    phase='INITIAL CLIMB', altitude_ft=140.0, agl_ft=40.0, radio_altitude_ft=40.0,
    vertical_speed_fpm=1500.0, pitch_deg=11.0)
add(300.0, lat=0.35, lon=0.0, phase='CRUISE', altitude_ft=12000.0, agl_ft=11900.0,
    radio_altitude_ft=11900.0, ground_speed_kts=300.0, ias_kts=250.0, indicated_speed_kts=250.0,
    vertical_speed_fpm=0.0, gear_percent=0.0, flap_percent=0.0)

# Final approach from 12 NM to 0.1 NM. Source changes near 5 NM.
elapsed = 600.0
for step in range(120):
    nm = 12.0 - step * 0.1
    lat = 1.0 - nm / 60.0
    agl = nm * pa.FT_PER_NM * math.tan(math.radians(3.0)) + 50.0
    source = 'fsuipc7' if nm > 5.0 else 'simconnect'
    # Emulate a one-sample provider bridge disagreement without corrupting the
    # remainder of the SimConnect approach stream.
    if abs(nm - 5.0) < 0.001:
        agl += 600.0
    # Keep phase deliberately generic until late final; geometry must remain authoritative.
    phase = 'CRUISE' if nm > 2.0 else 'APPROACH'
    add(elapsed, lat=lat, lon=0.00005, source=source, phase=phase,
        altitude_ft=100.0 + agl, agl_ft=agl, radio_altitude_ft=agl,
        ground_speed_kts=145.0, ias_kts=140.0, indicated_speed_kts=140.0,
        vertical_speed_fpm=-720.0, pitch_deg=2.8, bank_deg=0.3,
        gear_percent=100.0 if nm < 8.0 else 0.0, flap_percent=35.0 if nm < 5.0 else 10.0)
    elapsed += 3.0

# Touchdown 900 ft beyond the threshold, 18 ft right of centreline.
td_north_nm = 900.0 / pa.FT_PER_NM
cross_nm = 18.0 / pa.FT_PER_NM
add(elapsed, lat=1.0 + td_north_nm / 60.0, lon=cross_nm / 60.0, source='simconnect',
    on_ground=True, phase='LANDING ROLL', altitude_ft=100.0, agl_ft=0.0, radio_altitude_ft=0.0,
    ground_speed_kts=126.0, ias_kts=124.0, indicated_speed_kts=124.0,
    vertical_speed_fpm=-180.0, pitch_deg=3.1, bank_deg=0.4, gear_percent=100.0, flap_percent=35.0)
landing_time = rows[-1]['time']
for i in range(1, 25):
    elapsed += 2.0
    along = 900.0 + i * 170.0
    add(elapsed, lat=1.0 + (along / pa.FT_PER_NM) / 60.0, lon=cross_nm / 60.0,
        source='simconnect', on_ground=True, phase='LANDING ROLL', altitude_ft=100.0,
        agl_ft=0.0, radio_altitude_ft=0.0, ground_speed_kts=max(18.0, 126.0 - i * 5.0),
        ias_kts=max(15.0, 124.0 - i * 5.0), indicated_speed_kts=max(15.0, 124.0 - i * 5.0),
        vertical_speed_fpm=0.0, pitch_deg=0.0, bank_deg=0.0)

meta = {
    'id': 'synthetic-rc10',
    'flight': {'origin': 'TEST', 'destination': 'DEST', 'departure_runway': '01', 'arrival_runway': '01'},
    'times': {'landing': landing_time},
    'positions': {'landing': {'lat': rows[-25]['lat'], 'lon': rows[-25]['lon'], 'altitude_ft': 100.0}},
    'metrics': {'landing_rate_fpm': -180.0, 'touchdown_g': 1.12, 'touchdown_speed_kts': 126.0, 'touchdowns': 1},
    'fuel': {'used_lb': 1800.0}, 'durations': {'block_seconds': 3600, 'airborne_seconds': 3000},
}
try:
    analysis = pa.analyse_pirep(meta, rows)
finally:
    pa.navdata.runway_by_name = orig_by_name
    pa.navdata.nearest_runway_end = orig_nearest

check(analysis.get('ok'), 'Coherent stored flight produces a Full PIREP analysis')
profile = ((analysis.get('approach') or {}).get('profile') or [])
check(len(profile) >= 8, 'Final approach survives a clean FSUIPC to SimConnect handover')
check((analysis.get('data_quality') or {}).get('approach_reliable') is True, 'Recovered approach is marked reliable')
check((analysis.get('data_quality') or {}).get('provider_transition_samples_skipped') == 1, 'A provider bridge mismatch drops one sample instead of the whole approach')
landing = analysis.get('landing') or {}
check(650 <= float(landing.get('touchdown_distance_ft')) <= 1200, 'Touchdown point uses the actual contact sample')
check(abs(float(landing.get('touchdown_centerline_deviation_ft'))) <= 40, 'Centreline deviation is physically plausible')
check(landing.get('touchdown_pitch_deg') is not None and landing.get('touchdown_bank_deg') is not None, 'Touchdown attitude is retained')
check((analysis.get('version') or 0) >= 2, 'PIREP analysis version forces legacy Full PIREPs to refresh')

# Inferred geometry may still support generic approach plots, but it must never
# manufacture a touchdown point or centreline value.
orig_by_name = pa.navdata.runway_by_name
orig_nearest = pa.navdata.nearest_runway_end
try:
    pa.navdata.runway_by_name = lambda airport, runway: None
    pa.navdata.nearest_runway_end = lambda lat, lon, airport, track, max_nm=8.0: None
    inferred = pa.analyse_pirep(meta, rows)
finally:
    pa.navdata.runway_by_name = orig_by_name
    pa.navdata.nearest_runway_end = orig_nearest
check((inferred.get('landing') or {}).get('touchdown_distance_ft') is None, 'Missing runway geometry is reported as unavailable, not a fabricated touchdown point')
check((inferred.get('landing') or {}).get('touchdown_centerline_deviation_ft') is None, 'Missing runway geometry is reported as unavailable, not zero centreline deviation')

# One-shot arrival Cleaning safeguard.
orig_automation = copy.deepcopy(gsx_remote._AUTOMATION)
orig_mono = dict(gsx_remote._AUTOMATION_REQUESTED_MONO)
orig_call_service = gsx_remote.call_service
try:
    calls: list[str] = []
    gsx_remote._AUTOMATION.clear()
    gsx_remote._AUTOMATION.update({'requested': ['cleaning'], 'latches': {'deboarding_seen_active': True, 'cleaning_requested_once': True, 'cleaning_safeguard_attempted': False}})
    gsx_remote._AUTOMATION_REQUESTED_MONO.clear()
    gsx_remote._AUTOMATION_REQUESTED_MONO['arrival_deboarding_started_at'] = time.monotonic() - 301.0
    gsx_remote.call_service = lambda service, automate=False: (calls.append(service) or {'ok': True})
    gsx_remote._maybe_retry_arrival_cleaning_once({'progress': {'passengers_deboarding_total': 12}}, 5, None)
    gsx_remote._maybe_retry_arrival_cleaning_once({'progress': {'passengers_deboarding_total': 13}}, 5, None)
    check(calls == ['cleaning'], 'Cleaning safeguard sends exactly one follow-up request')
finally:
    gsx_remote._AUTOMATION.clear(); gsx_remote._AUTOMATION.update(orig_automation)
    gsx_remote._AUTOMATION_REQUESTED_MONO.clear(); gsx_remote._AUTOMATION_REQUESTED_MONO.update(orig_mono)
    gsx_remote.call_service = orig_call_service

# Finance reconciliation is idempotent and preserves pilot pay/revenue.
old_statement = {
    'ok': True, 'opening_balance': {'airline': 1000.0, 'pilot': 500.0},
    'closing_balance': {'airline': 1100.0, 'pilot': 623.0},
    'airline': {
        'revenue': {'passenger': 200.0, 'cargo': 0.0, 'total': 200.0},
        'costs': {'fuel': 10.0, 'ground_services': 50.0, 'ground_services_source': 'estimated', 'total': 100.0},
        'profit': 100.0, 'invoices': [],
    },
    'pilot': {'pay': 123.0, 'xp': 80, 'rank': {'key': 'fo'}},
}
fresh_statement = {
    'ok': True,
    'airline': {
        'revenue': {'passenger': 999.0, 'cargo': 999.0, 'total': 1998.0},
        'costs': {'fuel': 10.0, 'ground_services': 80.0, 'ground_services_source': 'gsx', 'total': 130.0},
        'profit': 1868.0, 'invoices': [{'service': 'Arrival handling', 'amount': 80.0}],
    },
    'pilot': {'pay': 9999.0, 'xp': 9999},
}
state = {'career': {
    'airline_balance': 1100.0, 'pilot_balance': 623.0,
    'totals': {'airline_costs': 100.0, 'airline_profit': 100.0, 'fuel_costs': 10.0,
               'estimated_service_costs': 50.0, 'gsx_service_costs': 0.0},
    'ledger': [{'flight_id': 'flight-1', 'statement': copy.deepcopy(old_statement)}],
}}
orig_enabled, orig_load, orig_save, orig_estimate = economy.finance_enabled, economy.load_career, economy.save_career, economy.estimate_statement
try:
    economy.finance_enabled = lambda: True
    economy.load_career = lambda: copy.deepcopy(state['career'])
    economy.save_career = lambda career: state.__setitem__('career', copy.deepcopy(career))
    economy.estimate_statement = lambda meta, career, previous_entries=None: copy.deepcopy(fresh_statement)
    flight_meta = {'id': 'flight-1', 'finance': copy.deepcopy(old_statement)}
    first = economy.reconcile_flight(flight_meta, [])
    second = economy.reconcile_flight(flight_meta, [])
    check(first['pilot']['pay'] == 123.0 and first['airline']['revenue']['total'] == 200.0, 'Late receipts preserve original pilot pay and revenue')
    check(first['airline']['costs']['ground_services'] == 80.0 and len(first['airline']['invoices']) == 1, 'Late arrival receipt replaces estimated handling cost')
    check(state['career']['airline_balance'] == 1070.0, 'Finance balance receives the cost delta once')
    check(second['airline']['profit'] == first['airline']['profit'] and state['career']['airline_balance'] == 1070.0, 'Receipt reconciliation is idempotent')
finally:
    economy.finance_enabled, economy.load_career, economy.save_career, economy.estimate_statement = orig_enabled, orig_load, orig_save, orig_estimate

# User-facing geometry never defaults null to zero.
ops_js = (ROOT / 'app/static/opsroom.js').read_text(encoding='utf-8')
pirep_js = (ROOT / 'app/static/pirep.js').read_text(encoding='utf-8')
check("value===null||value===undefined" in ops_js, 'Landing toast distinguishes unavailable values from zero')
check("marker=tdAlong!=null&&tdDev!=null" in pirep_js, 'Full PIREP hides an invalid touchdown marker')
check("if(value===null||value===undefined||value==='')return null" in pirep_js, 'Full PIREP formats unavailable metrics as a dash rather than zero')

version = json.loads((ROOT / 'version.json').read_text(encoding='utf-8'))
check(version['version'] == '0.24.48' and version['build'].endswith('18'), 'Version metadata preserves RC10 fixes in RC18')
check('OPS_ROOM_v0_24_48_Public_Beta_RC18_Windows_x64.zip' in (ROOT / 'BUILD OPS ROOM COMPLETE.bat').read_text(encoding='utf-8'), 'Windows build target is RC18')
notes = (ROOT / 'RELEASE_NOTES.md').read_text(encoding='utf-8')
check('New in v0.24.48' in notes and 'v0.24.40' in notes and 'v0.24.39' in notes, 'Cumulative user-facing release notes include RC18 and the protected RC10 baseline')

print(json.dumps({'ok': True, 'passed': len(passed), 'checks': passed}, indent=2))
