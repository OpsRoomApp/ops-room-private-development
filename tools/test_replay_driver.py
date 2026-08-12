#!/usr/bin/env python
"""Standalone SkyDolly-style Black Box in-sim replay test driver.

Runs completely independently of the running OPS ROOM app: it opens its OWN
SimConnect session, reuses the app's exact SkyDolly-parity engine pieces
(app.black_box_replay interpolation helpers + app.simconnect_position atomic
9-float64 pose writes), and verifies the aircraft actually moves by reading
live SimVars back.

Usage (from opsroom-app/source, sim must be running):
    python tools/test_replay_driver.py --list
    python tools/test_replay_driver.py --recording <id> --seconds 30 --speed 2.0
    python tools/test_replay_driver.py --recording <id> --start 700 --seconds 15 --speed 1.0
    python tools/test_replay_driver.py --recording <id> --dry-run          # no sim contact

--start selects the elapsed position (seconds into the recording). For RJA403:
    0      parked at OJAI, pushback / taxi out
    700    ~takeoff roll area (check with --dry-run if unsure)
The flight ends around 3550 s (landing roll at OLBA).
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from bisect import bisect_right

from app import black_box as bb  # noqa: E402
from app import simconnect_position as sc  # noqa: E402
from app.black_box_replay import (  # noqa: E402
    _ANGLE_FIELDS,
    _LINEAR_FIELDS,
    _angle,
    _euler_from_quat,
    _hermite_value,
    _lerp,
    _quat_from_euler,
    _quat_slerp,
)

DEFAULT_RECORDING = "6717d4e40bee48c3858033a8207a46cd-6b4e59c72f9b"  # RJA403 14:36Z


# ---------------------------------------------------------------------------
# Frame building - byte-for-byte the same interpolation the in-app replay uses
# (black_box_replay._frame_at): cubic Hermite lat/lon/alt, bounded linear
# altitude on the ground, slerped quaternion attitude.
# ---------------------------------------------------------------------------
def build_frame(rows: list[dict[str, Any]], times: list[float], cursor: float) -> dict[str, Any] | None:
    if not rows:
        return None
    if cursor <= times[0]:
        return dict(rows[0])
    if cursor >= times[-1]:
        return dict(rows[-1])
    index = max(0, min(len(rows) - 2, bisect_right(times, cursor) - 1))
    a, b = rows[index], rows[index + 1]
    span = max(0.0001, times[index + 1] - times[index])
    t = max(0.0, min(1.0, (cursor - times[index]) / span))
    frame = dict(a if t < 0.5 else b)
    frame["lat"] = _hermite_value(rows, times, index, cursor, "lat")
    frame["lon"] = _hermite_value(rows, times, index, cursor, "lon", angle=True)
    if bool(a.get("on_ground")) and bool(b.get("on_ground")):
        frame["altitude_ft"] = _lerp(a.get("altitude_ft"), b.get("altitude_ft"), t)
    else:
        frame["altitude_ft"] = _hermite_value(rows, times, index, cursor, "altitude_ft")
    for key in _LINEAR_FIELDS:
        frame[key] = _lerp(a.get(key), b.get(key), t)
    for key in _ANGLE_FIELDS:
        frame[key] = _angle(a.get(key), b.get(key), t)
    attitude_a = [_number(a.get(k)) for k in ("pitch_deg", "bank_deg", "heading_deg")]
    attitude_b = [_number(b.get(k)) for k in ("pitch_deg", "bank_deg", "heading_deg")]
    if all(value is not None for value in (*attitude_a, *attitude_b)):
        q = _quat_slerp(_quat_from_euler(*attitude_a), _quat_from_euler(*attitude_b), t)
        frame["pitch_deg"], frame["bank_deg"], frame["heading_deg"] = _euler_from_quat(q)
    else:
        frame["pitch_deg"] = _lerp(a.get("pitch_deg"), b.get("pitch_deg"), t)
        frame["bank_deg"] = _lerp(a.get("bank_deg"), b.get("bank_deg"), t)
        frame["heading_deg"] = _angle(a.get("heading_deg"), b.get("heading_deg"), t)
    frame["elapsed"] = cursor
    return frame


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # not NaN


# ---------------------------------------------------------------------------
# Sim-side helpers
# ---------------------------------------------------------------------------
def read_pose() -> dict[str, Any]:
    """Live readback of the USER aircraft position/attitude (independent check)."""
    try:
        aq = sc._SESSION_AQ
        if aq is not None:
            def val(key: str) -> float | None:
                try:
                    v = aq.get(key)
                    return float(v) if v is not None else None
                except Exception:
                    return None
            lat, lon = val("PLANE_LATITUDE"), val("PLANE_LONGITUDE")
            alt = val("PLANE_ALTITUDE")
            # NOTE: this wrapper returns heading in RADIANS despite the SimVar name
            hdg_rad = val("PLANE_HEADING_DEGREES_MAGNETIC")
            hdg = math.degrees(hdg_rad) % 360.0 if hdg_rad is not None else None
            gs = val("GROUND_VELOCITY")
            if any(v is not None for v in (lat, lon, alt, hdg, gs)):
                return {"lat": lat, "lon": lon, "altitude_ft": alt, "heading_deg": hdg, "ground_speed_kts": gs,
                        "source": "SIMCONNECT_READBACK"}
    except Exception:
        pass
    sensor = sc.replay_read_sensor()
    return {"ok": sensor.get("ok"), "altitude_ft": sensor.get("altitude_ft"),
            "source": sensor.get("source") or "OFFLINE"}


def fmt_pose(pose: dict[str, Any]) -> str:
    if not pose:
        return "(no readback)"
    lat = f"{pose['lat']:.5f}" if pose.get("lat") is not None else "---"
    lon = f"{pose['lon']:.5f}" if pose.get("lon") is not None else "---"
    alt = f"{pose['altitude_ft']:.0f} ft" if pose.get("altitude_ft") is not None else "---"
    hdg = f"{pose['heading_deg']:.1f} deg" if pose.get("heading_deg") is not None else "---"
    gs = f"{pose['ground_speed_kts']:.1f} kt" if pose.get("ground_speed_kts") is not None else "---"
    return f"lat={lat} lon={lon} alt={alt} hdg={hdg} gs={gs}"


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------
def cmd_list() -> int:
    print(f"{'RECORDING ID':<40} {'CALLSIGN':<10} {'STARTED (UTC)':<24} {'SAMPLES':>8} {'DURATION s':>10}")
    for item in bb.list_recordings(300):
        flight = item.get("flight") or {}
        print(f"{str(item.get('recording_id')):<40} {str(flight.get('callsign')):<10} "
              f"{str(item.get('started_utc')):<24} {int(item.get('sample_count') or 0):>8} "
              f"{round(float(item.get('duration_seconds') or 0)):>10}")
    return 0


def cmd_dry_run(recording_id: str, start: float, seconds: float) -> int:
    rows = load(recording_id)
    times = [float(r.get("elapsed") or 0.0) for r in rows]
    print(f"\nRecording: {recording_id}  samples={len(rows)}  duration={times[-1]:.1f} s")
    for cursor in (start, start + seconds * 0.25, start + seconds * 0.5, start + seconds * 0.75, start + seconds):
        c = max(times[0], min(float(cursor), times[-1]))
        frame = build_frame(rows, times, c)
        if frame is None:
            print(f"  t={c:8.1f}  (no frame)")
            continue
        print(f"  t={c:8.1f}  lat={frame.get('lat'):.5f} lon={frame.get('lon'):.5f} "
              f"alt={frame.get('altitude_ft'):8.1f} hdg={frame.get('heading_deg'):6.1f} deg "
              f"gs={frame.get('ground_speed_kts'):6.1f} kt on_ground={bool(frame.get('on_ground'))} "
              f"phase={frame.get('phase')}")
    print("\nDry run OK: the recording loads and interpolates (no sim contact made).")
    return 0


def load(recording_id: str) -> list[dict[str, Any]]:
    try:
        rows = list(bb.iter_samples(recording_id))
    except FileNotFoundError:
        print(f"ERROR: recording not found: {recording_id}")
        print("Run with --list to see available recording ids.")
        sys.exit(2)
    if len(rows) < 2:
        print(f"ERROR: recording has only {len(rows)} samples - cannot replay.")
        sys.exit(2)
    rows.sort(key=lambda r: float(r.get("elapsed") or 0.0))
    for key in ("lat", "lon", "altitude_ft", "pitch_deg", "bank_deg", "heading_deg"):
        if all(_number(r.get(key)) is None for r in rows):
            print(f"ERROR: recording has no usable '{key}' column - replay would fail.")
            sys.exit(2)
    return rows


def cmd_replay(recording_id: str, start: float, seconds: float, speed: float, yes: bool, no_freeze: bool = False) -> int:
    rows = load(recording_id)
    times = [float(r.get("elapsed") or 0.0) for r in rows]
    start = max(times[0], min(float(start), times[-1] - 1.0))
    end = min(float(start) + float(seconds), times[-1])
    flight_time = end - start
    wall_seconds = flight_time / speed
    print("\n" + "=" * 78)
    print("OPS ROOM - standalone SkyDolly-style in-sim replay test")
    print("=" * 78)
    print(f"  Recording : {recording_id}")
    print(f"  Samples   : {len(rows)}  (flight duration {times[-1]:.0f} s)")
    print(f"  Span      : t={start:.1f}s -> t={end:.1f}s  ({flight_time:.0f} s of flight at {speed}x = {wall_seconds:.0f} s wall)")
    print(f"  First pose: lat={rows[0].get('lat'):.5f} lon={rows[0].get('lon'):.5f} alt={rows[0].get('altitude_ft'):.0f} ft "
          f"phase={rows[0].get('phase')}")
    print("  WARNING   : this FREEZES the sim, takes over your aircraft and flies")
    print("              the recorded path. Disconnect from online networks first.")
    print("=" * 78)

    if not yes:
        try:
            answer = input("\nContinue? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer != "y":
            print("Aborted.")
            return 1

    saved_rate = sc.get_sim_rate()
    frozen = sc.replay_set_freeze(not no_freeze)
    print(f"  freeze={frozen.get('ok') if not no_freeze else 'OFF (--no-freeze)'} sim_rate_before={saved_rate}")
    sub = sc.replay_subscribe_frame()

    baseline = read_pose()
    print(f"  baseline readback : {fmt_pose(baseline)}")

    def restore_aircraft() -> None:
        """Teleport the user's aircraft back to where it was before the test."""
        b = baseline
        if not b or b.get("lat") is None or b.get("lon") is None:
            return
        rest = {
            "lat": b["lat"], "lon": b["lon"],
            "altitude_ft": float(b.get("altitude_ft") or 0.0),
            "pitch_deg": 0.0, "bank_deg": 0.0,
            "heading_deg": float(b.get("heading_deg") or 0.0),
            "on_ground": True, "indicated_speed_kts": 0.0,
        }
        try:
            r = sc.replay_apply_state(rest, initial=True)
            print(f"  aircraft restored to baseline: ok={r.get('ok')}")
        except Exception as exc:
            print(f"  restore failed: {type(exc).__name__}: {exc}")

    try:
        frame0 = build_frame(rows, times, start)
        if frame0 is None:
            print("ERROR: no frame at start cursor.")
            return 1
        initial = sc.replay_apply_state(frame0, initial=True)
        print(f"  initial pose applied: ok={initial.get('ok')} detail={initial.get('detail') or 'ok'}")
        after0 = read_pose()
        print(f"  after jump readback : {fmt_pose(after0)}")

        t0 = time.monotonic()
        last_report = t0
        applied = 0
        errors: list[str] = []
        while True:
            wall = time.monotonic()
            cursor = start + (wall - t0) * speed
            if cursor >= end:
                break
            frame = build_frame(rows, times, cursor)
            if frame is None:
                break
            try:
                sc.replay_apply_state(frame)
                applied += 1
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
                if len(errors) > 5:
                    print(f"ERROR: {errors[-1]}")
                    break
            sc.replay_wait_frame(0.02)
            if wall - last_report >= 4.0:
                last_report = wall
                live = read_pose()
                print(f"  t={cursor:7.1f} frame_alt={frame.get('altitude_ft'):8.1f} "
                      f"hdg={frame.get('heading_deg'):6.1f} gs={frame.get('ground_speed_kts'):6.1f} "
                      f"| sim readback: {fmt_pose(live)}")
    except KeyboardInterrupt:
        print("\n  Interrupted - restoring sim.")
    finally:
        sc.replay_unsubscribe_frame()
        sc.replay_set_freeze(False)
        sc.set_sim_rate(saved_rate)
        print("  unfrozen, sim rate restored")

    after = read_pose()
    print(f"\n  final readback    : {fmt_pose(after)}")
    restore_aircraft()
    print(f"  frames applied    : {applied}  (expected ~{int(wall_seconds * 30)})  errors={len(errors)}")

    # Verdict: the aircraft must have moved vs the baseline readback.
    def moved(a: dict[str, Any], b: dict[str, Any]) -> tuple[bool, str]:
        reasons: list[str] = []
        for key, label, thresh in (("altitude_ft", "altitude", 20.0), ("heading_deg", "heading", 2.0),
                                   ("ground_speed_kts", "ground speed", 5.0)):
            av, bv = a.get(key), b.get(key)
            if av is not None and bv is not None and abs(float(bv) - float(av)) >= thresh:
                reasons.append(f"{label} {av:.1f}->{bv:.1f}")
        return bool(reasons), ", ".join(reasons) or "no measurable motion"

    moved_ok, reason = moved(baseline, after)
    ok = bool(sub.get("ok")) and applied > 10 and not errors and moved_ok
    print("\n" + "=" * 78)
    print(f"  VERDICT: {'PASS PASS - the aircraft moved: ' + reason if ok else 'FAIL FAIL'}")
    if not bool(sub.get("ok")):
        print("    frame subscription failed:", sub.get("detail") or sub)
    if applied <= 10:
        print("    too few frames applied - SimConnect writes rejected or sim not delivering frames")
    if errors:
        print("    write errors:", errors[:3])
    if not moved_ok:
        print("    readback did not move:", reason)
    print("=" * 78)
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="list Black Box recordings")
    parser.add_argument("--recording", default=DEFAULT_RECORDING, help="recording id (default: RJA403)")
    parser.add_argument("--start", type=float, default=0.0, help="elapsed seconds into the recording to start at")
    parser.add_argument("--seconds", type=float, default=30.0, help="flight-time span to replay")
    parser.add_argument("--speed", type=float, default=2.0, help="replay speed multiplier (0.1x..16x)")
    parser.add_argument("--dry-run", action="store_true", help="validate samples + interpolation without touching the sim")
    parser.add_argument("--yes", "-y", action="store_true", help="skip the confirmation prompt")
    parser.add_argument("--no-freeze", action="store_true", help="do NOT freeze the user aircraft axes (SkyDolly continuous-write mode)")
    args = parser.parse_args()

    if args.list:
        return cmd_list()
    if args.dry_run:
        return cmd_dry_run(args.recording, args.start, args.seconds)
    return cmd_replay(args.recording, args.start, args.seconds, args.speed, args.yes, args.no_freeze)


if __name__ == "__main__":
    sys.exit(main())
