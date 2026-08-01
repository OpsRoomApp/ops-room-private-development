from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import telemetry_provider as tel  # noqa: E402
from app import announcements as ann  # noqa: E402
from app import pirep_analysis as pa  # noqa: E402

passed: list[str] = []

def check(condition: bool, name: str) -> None:
    if not condition:
        raise AssertionError(name)
    passed.append(name)

source = (ROOT / "app" / "telemetry_provider.py").read_text(encoding="utf-8")
check('(0x3364, "b")' in source and '(0x3365, "b")' in source, "FSUIPC byte offsets use supported lowercase pyuipc types")
check('(0x3364, "B")' not in source and '(0x3365, "B")' not in source, "Unsupported FSUIPC uppercase B types are absent")
check('name="OpsRoom-TelemetryRecovery"' in source, "FSUIPC recovery has a dedicated background worker")
check('recovered = _probe_preferred_fsuipc' not in source[source.index('def read_telemetry'):source.index('def telemetry_diagnostics')], "Normal telemetry requests never run FSUIPC recovery")
check('sim = read_position(force=False)' in source, "SimConnect reads use the shared session cache")
check('_CACHE_SECONDS = 0.18' in source, "Core telemetry cache is shared across simultaneous modules")
check('if _CACHE is not None and now - _CACHE_TIME < _CACHE_SECONDS' in source, "Forced callers cannot bypass a fresh shared snapshot")
check('read_telemetry(force=True)' not in (ROOT / 'app' / 'raas.py').read_text(encoding='utf-8'), "RAAS no longer forces duplicate simulator reads")

# Fresh cache must remain immediate even when a caller asks for a forced read.
orig = {
    'lock': tel._SOURCE_LOCK, 'cache': tel._CACHE, 'cache_time': tel._CACHE_TIME,
    'settings': tel._telemetry_settings, 'sim_running': tel._sim_process_running,
    'heartbeat': tel._sim_heartbeat, 'autostart': tel._maybe_autostart_fsuipc,
}
try:
    calls = {'heartbeat': 0}
    sample = {
        'ok': True, 'source': 'simconnect', 'lat': 50.0, 'lon': 8.0,
        'altitude_ft': 1000.0, 'indicated_altitude_ft': 1000.0,
        'agl_ft': 900.0, 'radio_altitude_ft': 900.0,
        'ground_speed_kts': 120.0, 'indicated_speed_kts': 115.0,
        'vertical_speed_fpm': 500.0, 'heading_deg': 90.0, 'track_deg': 90.0,
        'on_ground': False, 'sampled_monotonic': time.monotonic(),
    }
    tel._SOURCE_LOCK = 'simconnect'; tel._CACHE = None; tel._CACHE_TIME = 0.0
    tel._telemetry_settings = lambda: {'integrations': {'fsuipc_enabled': True}}  # type: ignore
    tel._sim_process_running = lambda: True  # type: ignore
    tel._maybe_autostart_fsuipc = lambda enabled: None  # type: ignore
    def heartbeat(now, force=False):
        calls['heartbeat'] += 1
        return dict(sample)
    tel._sim_heartbeat = heartbeat  # type: ignore
    first = tel.read_telemetry(force=True)
    second = tel.read_telemetry(force=True)
    check(first.get('source') == 'simconnect' and second.get('source') == 'simconnect', "Cached SimConnect sample remains available")
    check(calls['heartbeat'] == 1, "Two immediate module reads perform only one simulator read")
finally:
    tel._SOURCE_LOCK = orig['lock']; tel._CACHE = orig['cache']; tel._CACHE_TIME = orig['cache_time']
    tel._telemetry_settings = orig['settings']; tel._sim_process_running = orig['sim_running']
    tel._sim_heartbeat = orig['heartbeat']; tel._maybe_autostart_fsuipc = orig['autostart']

# Both providers use the same time-based conditioning and reject severe noise.
tel._FILTER_HISTORY.clear(); tel._FILTER_LAST.clear(); tel._FILTER_LAST_AT.clear()
base = {
    'ok': True, 'sampled_monotonic': 1.0, 'lat': 50.0, 'lon': 8.0,
    'altitude_ft': 5000.0, 'indicated_altitude_ft': 5000.0,
    'agl_ft': 4800.0, 'radio_altitude_ft': 4800.0,
    'ground_speed_kts': 220.0, 'indicated_speed_kts': 210.0,
    'vertical_speed_fpm': -700.0, 'heading_deg': 90.0, 'track_deg': 90.0,
    'pitch_deg': 2.0, 'bank_deg': 0.0, 'g_force': 1.0, 'on_ground': False,
}
tel._condition_sample(base, 'simconnect-test')
noisy = tel._condition_sample({**base, 'sampled_monotonic': 1.2, 'altitude_ft': 12000.0, 'indicated_altitude_ft': 12000.0, 'ground_speed_kts': 430.0, 'indicated_speed_kts': 390.0, 'vertical_speed_fpm': -9500.0}, 'simconnect-test')
check(noisy['altitude_ft'] < 6000.0, "SimConnect altitude spike is rejected")
check(noisy['ground_speed_kts'] < 300.0 and noisy['indicated_speed_kts'] < 300.0, "SimConnect speed spikes are rejected")
check(noisy['vertical_speed_fpm'] > -3000.0, "SimConnect vertical-speed spike is rejected")
check(noisy['raw_vertical_speed_fpm'] == -9500.0, "Raw landing-sensitive telemetry remains available separately")
sustained = tel._condition_sample({**base, 'sampled_monotonic': 1.4, 'vertical_speed_fpm': -3000.0}, 'simconnect-test')
sustained = tel._condition_sample({**base, 'sampled_monotonic': 1.6, 'vertical_speed_fpm': -3000.0}, 'simconnect-test')
check(sustained['vertical_speed_fpm'] <= -2500.0, "Sustained real vertical-speed changes are accepted after transient filtering")

# Airborne recorder phase must override missing generic Fenix power SimVars.
orig_phase = ann._active_recorder_phase
try:
    ann._READY_SAMPLES.clear()
    ann._active_recorder_phase = lambda: 'DESCENT'  # type: ignore
    airborne = {
        'ok': True, 'telemetry_valid': True, 'telemetry_fresh': True,
        'sim_process_running': True, 'lat': 48.0, 'lon': 11.0,
        'altitude_ft': 9200.0, 'agl_ft': 8000.0, 'ground_speed_kts': 250.0,
        'on_ground': False, 'systems': {},
    }
    check(ann._telemetry_ready(airborne), "Active airborne recorder phase does not depend on generic Fenix power SimVars")
finally:
    ann._active_recorder_phase = orig_phase

# Exact post-takeoff catch-up sequence.
orig_funcs = {
    'auto_live': ann._auto_sim_live, 'ready': ann._telemetry_ready,
    'stable': ann._stable_live_session, 'phase': ann._active_recorder_phase,
    'alt_rel': ann._altitude_reliable, 'push': ann._gsx_pushback_active_status,
    'files': ann._files_for_event, 'play': ann._auto_play,
}
try:
    played: list[str] = []
    ann._auto_sim_live = lambda t: True  # type: ignore
    ann._telemetry_ready = lambda t: True  # type: ignore
    ann._stable_live_session = lambda t: True  # type: ignore
    ann._active_recorder_phase = lambda: 'DESCENT'  # type: ignore
    ann._altitude_reliable = lambda t: True  # type: ignore
    ann._gsx_pushback_active_status = lambda: False  # type: ignore
    ann._files_for_event = lambda event: [Path(f'{event}.ogg')] if event in {'CallCabinSecureLanding', 'CabinDimLanding'} else []  # type: ignore
    def play(event, **kwargs):
        played.append(event); ann._QUEUED_EVENTS.add(event); ann._PLAYED.add(event)
        return {'ok': True}
    ann._auto_play = play  # type: ignore
    ann._SESSION_READY = True; ann._TAKEOFF_CONFIRMED = True; ann._EVER_AIRBORNE = True
    ann._ANN_VALID_PHASE = 'DESCENT'; ann._ANN_AIRBORNE_STARTED_AT = 1.0
    ann._PLAYED.clear(); ann._PLAYED.add('AfterTakeoff'); ann._QUEUED_EVENTS.clear(); ann._PREVIOUS.clear()
    ann._PREVIOUS.update({'altitude': 11000.0, 'on_ground': False})
    t = {
        'ok': True, 'telemetry_valid': True, 'telemetry_fresh': True,
        'lat': 48.0, 'lon': 11.0, 'altitude_ft': 9200.0, 'indicated_altitude_ft': 9200.0,
        'agl_ft': 8000.0, 'radio_altitude_ft': 8000.0, 'ground_speed_kts': 240.0,
        'indicated_speed_kts': 230.0, 'vertical_speed_fpm': -1200.0,
        'on_ground': False, 'systems': {},
    }
    ann._trigger_from_telemetry(t)
    check('DescentSeatbelts' in played, "Confirmed descent below 10,000 ft triggers DescentSeatbelts")
    ann._PREVIOUS['altitude'] = 9200.0
    ann._trigger_from_telemetry({**t, 'altitude_ft': 4500.0, 'indicated_altitude_ft': 4500.0, 'agl_ft': 4200.0, 'radio_altitude_ft': 4200.0})
    check('CallCabinSecureLanding' in played and 'CabinDimLanding' in played, "Available landing-preparation calls are included as literal events")
    check('CrewSeatsLanding' in played, "Confirmed descent below 5,000 ft triggers CrewSeatsLanding")
finally:
    ann._auto_sim_live = orig_funcs['auto_live']; ann._telemetry_ready = orig_funcs['ready']
    ann._stable_live_session = orig_funcs['stable']; ann._active_recorder_phase = orig_funcs['phase']
    ann._altitude_reliable = orig_funcs['alt_rel']; ann._gsx_pushback_active_status = orig_funcs['push']
    ann._files_for_event = orig_funcs['files']; ann._auto_play = orig_funcs['play']

# Approach plotting collapses duplicate distance points and has no unsafe loose fallback.
rows = [
    {'nm_to_threshold': 5.01, 'approach_agl_ft': 1600, 'vertical_speed_fpm': -700, 'ias_kts': 140},
    {'nm_to_threshold': 5.02, 'approach_agl_ft': 7000, 'vertical_speed_fpm': -9000, 'ias_kts': 320},
    {'nm_to_threshold': 5.00, 'approach_agl_ft': 1550, 'vertical_speed_fpm': -750, 'ias_kts': 142},
]
binned = pa._bin_approach_profile(rows, 0.05)
check(len(binned) == 1, "Repeated threshold distances collapse into one chart point")
check(1500 <= binned[0]['approach_agl_ft'] <= 2000, "Distance bin uses a median rather than drawing vertical telemetry teeth")
pa_source = (ROOT / 'app' / 'pirep_analysis.py').read_text(encoding='utf-8')
check('loose_approach_rows' not in pa_source, "Unsafe loose final-approach fallback is removed")
check('Insufficient continuous, physically plausible final-approach telemetry' in pa_source, "Unreliable approach data is reported instead of plotted")

# Version and release metadata.
current_version = json.loads((ROOT / 'version.json').read_text(encoding='utf-8'))['version']
check(f'version="{current_version}"' in (ROOT / 'app' / 'main.py').read_text(encoding='utf-8'), f"FastAPI version is {current_version}")
check(f'v{current_version}' in (ROOT / 'RELEASE_NOTES.md').read_text(encoding='utf-8'), f"Cumulative release notes include v{current_version}")
check('OPS_ROOM_v0_24_48_Public_Beta_RC18_Windows_x64.zip' in (ROOT / 'BUILD OPS ROOM COMPLETE.bat').read_text(encoding='utf-8'), "Complete build script targets RC18 Windows ZIP")

print(json.dumps({'ok': True, 'passed': len(passed), 'checks': passed}, indent=2))
