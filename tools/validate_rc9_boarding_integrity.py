from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import announcements as ann
from app import gsx_remote

passed = []
def check(condition, name):
    if not condition:
        raise AssertionError(name)
    passed.append(name)

# Passenger count is authoritative over stale raw completion and bags 100%.
snap = {
    'services': {'boarding': {
        'raw': 6, 'remote_state': 'completed',
        'progress_text': 'pax 43/152 · bags 100%',
    }},
    'progress': {
        'passengers_boarding_total': 43,
        'passengers_target': 152,
        'boarding_cargo_percent': 100,
    },
}
check(not gsx_remote._boarding_service_complete_from_snapshot(snap), 'Explicit pax 43/152 overrides stale boarding completion')
snap['progress']['passengers_boarding_total'] = 152
snap['services']['boarding']['progress_text'] = 'pax 152/152 · bags 100%'
check(gsx_remote._boarding_service_complete_from_snapshot(snap), 'Passenger target completion authorizes boarding completion')

# Waiting/requested Departure is never physical pushback.
waiting = {
    'raw': 7, 'remote_state': 'requested', 'waiting': True,
    'waiting_reason': 'waiting for Boarding',
    'status_text': 'Departure service has been requested · waiting for Boarding',
}
check(not ann._service_is_physical_departure_active(waiting), 'Departure waiting for Boarding is not physical pushback')
check(ann._service_is_physical_departure_active({'raw': 5, 'remote_state': 'performing', 'waiting': False}), 'Performing Departure remains physical pushback')

# Boarding status keeps explicit incomplete pax active even with raw 6.
info = ann._gsx_boarding_status({
    'ok': True, 'connected': True,
    'services': {'boarding': {'raw': 6, 'remote_state': 'completed', 'progress_text': 'pax 43/152 · bags 100%'}},
    'progress': {'passengers_boarding_total': 43, 'passengers_target': 152, 'boarding_cargo_percent': 100},
})
check(info['explicit_incomplete'] and info['active'] and not info['complete'], 'Announcer keeps passenger boarding active at 43/152')

# Refuelling-specific welcome is optional; same-event normal variation remains eligible.
original_aircraft = ann._aircraft_variant
original_daypart = ann._local_daypart
original_refuel = ann._refueling_active
try:
    ann._aircraft_variant = lambda: 'A320'
    ann._local_daypart = lambda event: 'Morning'
    ann._refueling_active = lambda: True
    files = [Path('BoardingWelcome[Morning].ogg'), Path('CrewSeatsTakeoff.ogg')]
    chosen = ann._compatible_event_files('BoardingWelcome', files)
    check(chosen == [Path('BoardingWelcome[Morning].ogg')], 'Missing refuelling variant falls back within BoardingWelcome')
    files = [Path('BoardingWelcome[Morning].ogg'), Path('BoardingWelcome[Refueling].ogg')]
    chosen = ann._compatible_event_files('BoardingWelcome', files)
    check(chosen == [Path('BoardingWelcome[Refueling].ogg')], 'Refuelling welcome is preferred when available')
finally:
    ann._aircraft_variant = original_aircraft
    ann._local_daypart = original_daypart
    ann._refueling_active = original_refuel

# Full GSX trigger regression: no pushback stop/boarding complete while pax are incomplete.
original_status = None
original_start = ann._start_boarding_music
original_stop = ann._stop_boarding_music
original_play = ann._auto_play
original_allowed = ann._boarding_audio_allowed
try:
    import app.gsx_remote as remote
    original_status = remote.status
    remote.status = lambda force=False: {
        'ok': True, 'connected': True,
        'services': {
            'boarding': {'raw': 6, 'remote_state': 'completed', 'progress_text': 'pax 43/152 · bags 100%'},
            'departure': waiting,
            'pushback': {'raw': 0}, 'deboarding': {'raw': 0},
            'refuel': {'raw': 5}, 'catering': {'raw': 6},
            'jetway': {'raw': 1}, 'stairs': {'raw': 1},
        },
        'progress': {'passengers_boarding_total': 43, 'passengers_target': 152, 'boarding_cargo_percent': 100},
    }
    events = []
    ann._start_boarding_music = lambda reason='': events.append(('start', reason))
    ann._stop_boarding_music = lambda reason='': events.append(('stop', reason))
    ann._auto_play = lambda event, **kwargs: (events.append(('play', event)) or {'ok': True})
    ann._boarding_audio_allowed = lambda: True
    ann._PREVIOUS.clear(); ann._PLAYED.clear(); ann._QUEUED_EVENTS.clear()
    ann._BOARDING_PHASE_ACTIVE = False; ann._BOARDING_MUSIC_ACTIVE = False; ann._BOARDING_MUSIC_DUE_AT = 0.0
    ann._SESSION_READY = True; ann._TAKEOFF_CONFIRMED = False; ann._ARRIVAL_COMPLETE = False; ann._AUDIO_HARD_STOPPED = False
    ann._trigger_from_gsx()
    check(any(kind == 'start' for kind, _ in events), 'Active passenger boarding starts boarding audio')
    check(('play', 'BoardingWelcome') in events, 'Boarding start attempts the same-event welcome once')
    check(not any(kind == 'stop' for kind, _ in events), 'Incomplete passenger boarding cannot stop boarding audio')
    check(('play', 'BoardingComplete') not in events, 'Bags 100 percent cannot play BoardingComplete')
    check(not ann._PREVIOUS.get('pushback_active_seen'), 'Waiting Departure cannot latch pushback active')
finally:
    if original_status is not None:
        remote.status = original_status
    ann._start_boarding_music = original_start
    ann._stop_boarding_music = original_stop
    ann._auto_play = original_play
    ann._boarding_audio_allowed = original_allowed

# Telemetry-side regression: waiting Departure at zero ground speed cannot arm doors.
original_status = None
original_auto_live = ann._auto_sim_live
original_ready = ann._telemetry_ready
original_stable = ann._stable_live_session
original_phase = ann._active_recorder_phase
original_altitude = ann._altitude_reliable
original_files = ann._files_for_event
original_play = ann._auto_play
try:
    import app.gsx_remote as remote
    original_status = remote.status
    remote.status = lambda force=False: {
        'ok': True, 'connected': True,
        'services': {
            'boarding': {'raw': 6, 'remote_state': 'completed', 'progress_text': 'pax 43/152 · bags 100%'},
            'departure': waiting, 'pushback': {'raw': 0},
        },
        'progress': {'passengers_boarding_total': 43, 'passengers_target': 152, 'boarding_cargo_percent': 100},
    }
    played = []
    ann._auto_sim_live = lambda t: True
    ann._telemetry_ready = lambda t: True
    ann._stable_live_session = lambda t: True
    ann._active_recorder_phase = lambda: 'PARKED'
    ann._altitude_reliable = lambda t: True
    ann._files_for_event = lambda event: [Path(f'{event}.ogg')]
    ann._auto_play = lambda event, **kwargs: (played.append(event) or {'ok': True})
    ann._PREVIOUS.clear(); ann._PLAYED.clear(); ann._QUEUED_EVENTS.clear()
    ann._SESSION_READY = True; ann._TAKEOFF_CONFIRMED = False; ann._EVER_AIRBORNE = False
    ann._ARRIVAL_COMPLETE = False; ann._BOARDING_PHASE_ACTIVE = True; ann._BOARDING_MOVEMENT_SAMPLES = 0
    sample = {
        'ok': True, 'telemetry_valid': True, 'telemetry_fresh': True,
        'sim_process_running': True, 'lat': 36.1, 'lon': -5.3,
        'altitude_ft': 10.0, 'indicated_altitude_ft': 10.0, 'agl_ft': 5.0,
        'ground_speed_kts': 0.0, 'indicated_speed_kts': 0.0, 'vertical_speed_fpm': 0.0,
        'on_ground': True, 'systems': {'engines_running': False, 'parking_brake_set': True},
    }
    ann._trigger_from_telemetry(sample)
    check('ArmDoors' not in played, 'Waiting Departure and bags 100 percent cannot arm doors')
    check(not ann._PREVIOUS.get('pushback_active_seen'), 'Waiting Departure cannot become telemetry pushback')
finally:
    if original_status is not None:
        remote.status = original_status
    ann._auto_sim_live = original_auto_live
    ann._telemetry_ready = original_ready
    ann._stable_live_session = original_stable
    ann._active_recorder_phase = original_phase
    ann._altitude_reliable = original_altitude
    ann._files_for_event = original_files
    ann._auto_play = original_play

version = json.loads((ROOT / 'version.json').read_text(encoding='utf-8'))
check(version['version'] == '0.24.48' and version['build'].endswith('18'), 'Version metadata preserves RC9 fixes in RC18')
check('OPS_ROOM_v0_24_48_Public_Beta_RC18_Windows_x64.zip' in (ROOT / 'BUILD OPS ROOM COMPLETE.bat').read_text(encoding='utf-8'), 'Windows build target is RC18')
check('New in v0.24.48' in (ROOT / 'RELEASE_NOTES.md').read_text(encoding='utf-8'), 'Cumulative user-facing notes include RC18')

print(json.dumps({'ok': True, 'passed': len(passed), 'checks': passed}, indent=2))
