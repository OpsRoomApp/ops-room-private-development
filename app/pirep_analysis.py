from __future__ import annotations

import logging
import math
from datetime import datetime
from statistics import median
from typing import Any

from . import navdata
from . import notam_client  # v0.25.65: PIREP NOTAM conditions footnote
from . import notam_translate  # v0.25.65: plain-English expansion

_LOG = logging.getLogger("opsroom.pirep")

# Short-gap bridging tolerance. Recording runs at roughly 1 Hz, so a run of a
# few gap-flagged samples is usually a brief SimConnect<->FSUIPC failover or a
# one-off stall blip surrounded by clean data. Such short runs are bridged
# (kept) so PIREP phases do not lose contiguous data; only runs long enough to
# represent a real outage are discarded.
# v0.25.72 (#21): bridge short sample gaps. A degraded SimConnect session
# (#9) made the recorder drop most samples, leaving ~1 sample per 20 s for
# long stretches — the 5 s / 3-sample bridge then split every approach into
# fragments and produced "insufficient telemetry". 60 s / 6 samples tolerates
# that damage while the physical-plausibility filters still reject absurd
# values.
_GAP_BRIDGE_MAX_SAMPLES = 6
_GAP_BRIDGE_MAX_SECONDS = 60.0


def _is_gap_sample(row: dict[str, Any]) -> bool:
    return bool(row.get("telemetry_gap") or row.get("telemetry_hold"))

EARTH_NM = 3440.065
FT_PER_NM = 6076.12
ANALYSIS_VERSION = 2


def _num(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _distance_nm(a: dict[str, Any], b: dict[str, Any]) -> float | None:
    lat1, lon1, lat2, lon2 = (_num(a.get("lat")), _num(a.get("lon")), _num(b.get("lat")), _num(b.get("lon")))
    if None in (lat1, lon1, lat2, lon2):
        return None
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return EARTH_NM * 2 * math.atan2(math.sqrt(h), math.sqrt(max(0.0, 1 - h)))


def _path_distance_nm(rows: list[dict[str, Any]]) -> float:
    total = 0.0
    for a, b in zip(rows, rows[1:]):
        value = _distance_nm(a, b)
        if value is not None and value < 2.0:
            total += value
    return total


def _circular_mean(values: list[float], fallback: float = 0.0) -> float:
    values = [v % 360 for v in values if math.isfinite(v)]
    if not values:
        return fallback % 360
    s = sum(math.sin(math.radians(v)) for v in values)
    c = sum(math.cos(math.radians(v)) for v in values)
    return math.degrees(math.atan2(s, c)) % 360


def _heading(rows: list[dict[str, Any]], fallback: float = 0.0) -> float:
    values: list[float] = []
    for row in rows:
        value = _num(row.get("track_deg"))
        if value is None:
            value = _num(row.get("heading_deg"))
        if value is not None:
            values.append(value)
    return round(_circular_mean(values, fallback), 1)




def _heading_delta(a: float | None, b: float | None) -> float:
    if a is None or b is None:
        return 180.0
    return abs(((float(a) - float(b) + 180.0) % 360.0) - 180.0)


def _runway_ident_clean(value: Any) -> str:
    text = str(value or '').upper().replace('RWY', '').replace('RUNWAY', '').strip()
    return ''.join(ch for ch in text if ch.isalnum())


def _opposite_runway(nav: dict[str, Any] | None) -> str:
    if not nav:
        return ''
    current = _runway_ident_clean(nav.get('runway'))
    names = [nav.get('name_a'), nav.get('name_b'), nav.get('primary_end_name'), nav.get('secondary_end_name')]
    clean = [_runway_ident_clean(x) for x in names if x]
    for name in clean:
        if name and name != current:
            return name
    try:
        number = int(''.join(ch for ch in current if ch.isdigit())[:2] or '0')
        suffix = ''.join(ch for ch in current if ch.isalpha())
        reciprocal = ((number + 18 - 1) % 36) + 1
        return f'{reciprocal:02d}{suffix}'
    except Exception:
        return ''


def _valid_latlon(row: dict[str, Any] | None) -> bool:
    if not isinstance(row, dict):
        return False
    lat, lon = _num(row.get('lat')), _num(row.get('lon'))
    return lat is not None and lon is not None and abs(lat) <= 90 and abs(lon) <= 180


def _select_runway_end(airport: str, runway_name: str, sample: dict[str, Any], track_deg: float, max_nm: float = 8.0) -> tuple[dict[str, Any] | None, str]:
    """Pick the runway end that matches the actual recorded direction.

    SimBrief often supplies the planned runway, but a visual landing, runway
    change, reciprocal assignment, or stale plan can make that runway wrong for
    the recorded flight. For PIREP geometry the recorded track must win when the
    named runway is not aligned.
    """
    named = navdata.runway_by_name(airport, runway_name) if runway_name else None
    nearest = None
    if _valid_latlon(sample):
        nearest = navdata.nearest_runway_end(float(sample['lat']), float(sample['lon']), airport or None, track_deg, max_nm=max_nm)
    if named and nearest:
        named_delta = _heading_delta(track_deg, _num(named.get('heading_deg')))
        nearest_delta = _heading_delta(track_deg, _num(nearest.get('heading_deg')))
        # Prefer the named runway unless it is clearly the wrong end or the
        # recorded track/position strongly favours another end.
        if named_delta <= 55 or named_delta <= nearest_delta + 12:
            return named, 'OPS ROOM NAVDATA / PLANNED RUNWAY'
        return nearest, 'OPS ROOM NAVDATA / RECORDED TRACK'
    if named:
        return named, 'OPS ROOM NAVDATA / PLANNED RUNWAY'
    if nearest:
        return nearest, 'OPS ROOM NAVDATA / RECORDED TRACK'
    return None, 'INFERRED FROM RECORDED TELEMETRY'


def _path_along_span_ft(path: list[dict[str, Any]]) -> float | None:
    values = [_num(x.get('along_ft')) for x in path if _num(x.get('along_ft')) is not None]
    if len(values) < 2:
        return None
    return max(0.0, values[-1] - values[0])


def _clip_runway_path(path: list[dict[str, Any]], length_ft: float, width_ft: float, pad_ft: float = 450.0) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cross_limit = max(width_ft * 2.2, 350.0)
    for row in path:
        along, dev = _num(row.get('along_ft')), _num(row.get('deviation_ft'))
        if along is None or dev is None:
            continue
        if -pad_ft <= along <= length_ft + pad_ft and abs(dev) <= cross_limit:
            out.append(row)
    return out


def _dedupe_profile(rows: list[dict[str, Any]], key: str, min_delta: float = 0.015, limit: int = 900) -> list[dict[str, Any]]:
    if len(rows) <= limit:
        return rows
    out: list[dict[str, Any]] = []
    last_value: float | None = None
    for row in rows:
        value = _num(row.get(key))
        if value is None:
            continue
        if last_value is None or abs(value - last_value) >= min_delta:
            out.append(row); last_value = value
    if len(out) > limit:
        step = max(1, math.ceil(len(out) / limit))
        reduced = out[::step]
        if out and reduced[-1] is not out[-1]:
            reduced.append(out[-1])
        return reduced
    return out

def _local_xy_ft(point: dict[str, Any], origin: dict[str, Any], heading_deg: float) -> tuple[float, float] | None:
    lat, lon, lat0, lon0 = (_num(point.get("lat")), _num(point.get("lon")), _num(origin.get("lat")), _num(origin.get("lon")))
    if None in (lat, lon, lat0, lon0):
        return None
    north = (lat - lat0) * 60.0 * FT_PER_NM
    east = (lon - lon0) * 60.0 * math.cos(math.radians((lat + lat0) / 2.0)) * FT_PER_NM
    angle = math.radians(heading_deg)
    along = east * math.sin(angle) + north * math.cos(angle)
    cross = east * math.cos(angle) - north * math.sin(angle)
    return along, cross


def _project(origin: dict[str, Any], heading_deg: float, along_ft: float) -> dict[str, float]:
    lat0, lon0 = _num(origin.get("lat")), _num(origin.get("lon"))
    if lat0 is None or lon0 is None:
        return {"lat": 0.0, "lon": 0.0}
    distance_nm = along_ft / FT_PER_NM
    angle = math.radians(heading_deg)
    north_nm = distance_nm * math.cos(angle)
    east_nm = distance_nm * math.sin(angle)
    return {"lat": lat0 + north_nm / 60.0, "lon": lon0 + east_nm / (60.0 * max(0.15, math.cos(math.radians(lat0))))}


def _first_transition(samples: list[dict[str, Any]], from_ground: bool, to_ground: bool, start: int = 1) -> int | None:
    for index in range(max(1, start), len(samples)):
        if bool(samples[index - 1].get("on_ground")) == from_ground and bool(samples[index].get("on_ground")) == to_ground:
            return index
    return None


def _closest(rows: list[dict[str, Any]], key: str, target: float) -> dict[str, Any] | None:
    candidates = [(abs(float(value) - target), row) for row in rows if (value := _num(row.get(key))) is not None]
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def _event_distance(rows: list[dict[str, Any]], predicate) -> float | None:
    for row in rows:
        if predicate(row):
            value = _num(row.get("nm_to_threshold"))
            if value is not None:
                return round(value, 2)
    return None


def _phase_fuel(samples: list[dict[str, Any]]) -> dict[str, float]:
    first: dict[str, float] = {}
    last: dict[str, float] = {}
    for row in samples:
        phase = str(row.get("phase") or "UNKNOWN").upper()
        fuel = _num(row.get("fuel_total_lb"))
        if fuel is None:
            continue
        first.setdefault(phase, fuel)
        last[phase] = fuel
    return {phase: round(max(0.0, first[phase] - last.get(phase, first[phase])), 1) for phase in first}



def _sample_time(row: dict[str, Any]) -> float | None:
    for key in ("elapsed_seconds", "elapsed_s", "time_s", "sim_time_s", "timestamp", "time"):
        value = _num(row.get(key))
        if value is not None:
            return value
    return None


def _pirep_notam_footnote(dep_airport: str, arr_airport: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Active-window NOTAMs for departure/arrival, persisted with the PIREP
    record as a small 'conditions' section (v0.25.65).

    Uses the flight's actual recorded time window so a NOTAM cancelled after
    the flight is still included (history), and one that expired before the
    flight is excluded. Best-effort -- never raises.
    """
    if not rows:
        return []
    start = _sample_time(rows[0]) or 0.0
    end = _sample_time(rows[-1]) or start
    items: list[dict[str, Any]] = []
    for code in (str(dep_airport or "").upper(), str(arr_airport or "").upper()):
        if len(code) != 4 or not code.isalpha():
            continue
        try:
            package = notam_client.get_notams(code)
        except Exception:
            continue
        for row in package.get("notams") or []:
            effective = str(row.get("effective_utc") or "")
            expires = str(row.get("expires_utc") or "")
            try:
                if effective and end:
                    if datetime.fromisoformat(effective.replace("Z", "+00:00")).timestamp() > end:
                        continue
            except ValueError:
                pass
            try:
                if expires and expires.upper() != "PERM" and start:
                    if datetime.fromisoformat(expires.replace("Z", "+00:00")).timestamp() < start:
                        continue
            except ValueError:
                pass
            items.append(
                {
                    "icao": code,
                    "id": row.get("id"),
                    "classification": row.get("classification"),
                    "text": notam_translate.expand(row.get("text") or ""),
                    "effective_utc": effective or None,
                    "expires_utc": None if expires.upper() == "PERM" else (expires or None),
                }
            )
    return items[:24]


def _sanitize_samples(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Chronologically sanitize recorder samples before PIREP scoring/plotting."""
    # v0.25.60: telemetry_gap / telemetry_hold samples are no longer dropped
    # unconditionally. A second or two of flagged samples with clean, continuous
    # data on both sides is bridged (kept); the geometric jump filter below
    # still rejects genuinely impossible transitions. Only gap runs longer than
    # the bridge tolerance are discarded.
    candidates = [dict(x) for x in rows if isinstance(x, dict) and _valid_latlon(x)]
    gap_runs: list[tuple[int, int]] = []
    index = 0
    total = len(candidates)
    while index < total:
        if _is_gap_sample(candidates[index]):
            end = index
            while end < total and _is_gap_sample(candidates[end]):
                end += 1
            gap_runs.append((index, end))
            index = end
        else:
            index += 1
    keep = [True] * total
    bridged_samples = 0
    dropped_samples = 0
    dropped_runs = 0
    for start, end in gap_runs:
        first_t = _sample_time(candidates[start])
        last_t = _sample_time(candidates[end - 1])
        # Without timestamps we cannot verify the gap is short, so treat it as
        # too long to bridge (conservative: only bridge when we can prove clean
        # data bounds a brief window).
        if first_t is None or last_t is None:
            span = float("inf")
        else:
            span = max(0.0, last_t - first_t)
        length = end - start
        if length <= _GAP_BRIDGE_MAX_SAMPLES and span <= _GAP_BRIDGE_MAX_SECONDS:
            bridged_samples += length
        else:
            dropped_runs += 1
            dropped_samples += length
            for idx in range(start, end):
                keep[idx] = False
    cleaned = [row for row, is_kept in zip(candidates, keep) if is_kept]
    sortable = all(_sample_time(x) is not None for x in cleaned[: min(len(cleaned), 20)])
    if sortable:
        cleaned.sort(key=lambda x: _sample_time(x) or 0.0)
    out: list[dict[str, Any]] = []
    removed_duplicate = 0
    removed_jump = 0
    provider_transition_samples_skipped = 0
    last: dict[str, Any] | None = None
    last_t: float | None = None
    for row in cleaned:
        t = _sample_time(row)
        if last is not None:
            dist = _distance_nm(last, row)
            if t is not None and last_t is not None and t <= last_t:
                removed_duplicate += 1
                continue
            if dist is not None:
                dt = max(0.25, (t - last_t) if t is not None and last_t is not None else 1.0)
                gs = max(30.0, _num(row.get("ground_speed_kts")) or _num(last.get("ground_speed_kts")) or 250.0)
                expected_nm = gs * dt / 3600.0
                alt_jump = abs((_num(row.get("altitude_ft")) or 0.0) - (_num(last.get("altitude_ft")) or 0.0))
                ias_jump = abs((_num(row.get("ias_kts")) or 0.0) - (_num(last.get("ias_kts")) or 0.0))
                source_changed = str(row.get("source") or "") != str(last.get("source") or "")
                # Position discontinuities remain hard failures. For a clean provider
                # handover, discard only the bridge sample when the providers disagree
                # on altitude/speed, then advance the comparison baseline to the new
                # source. This prevents one rejected FSUIPC/SimConnect transition from
                # cascading into the loss of the complete final approach.
                position_impossible = dist > max(3.0, expected_nm * 10.0 + 1.0)
                provider_jump = source_changed and dt <= 8.0 and (alt_jump > 350.0 or ias_jump > 35.0)
                short_term_jump = dt <= 5.0 and (alt_jump > 1200.0 or ias_jump > 90.0)
                if position_impossible:
                    removed_jump += 1
                    continue
                if source_changed and (provider_jump or short_term_jump):
                    removed_jump += 1
                    provider_transition_samples_skipped += 1
                    last = row
                    last_t = t
                    continue
                if short_term_jump:
                    removed_jump += 1
                    continue
        out.append(row)
        last = row
        last_t = t
    return out, {
        "input_samples": len(rows),
        "kept_samples": len(out),
        "removed_duplicate_or_stale": removed_duplicate,
        "removed_jumps": removed_jump,
        "provider_transition_samples_skipped": provider_transition_samples_skipped,
        "gap_samples_bridged": bridged_samples,
        "gap_samples_dropped": dropped_samples,
        "gap_runs_dropped": dropped_runs,
        "gap_bridge_max_samples": _GAP_BRIDGE_MAX_SAMPLES,
        "gap_bridge_max_seconds": _GAP_BRIDGE_MAX_SECONDS,
    }


def _last_continuous_final(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the last coherent inbound segment that reaches the threshold.

    Provider changes are not segment boundaries by themselves. FSUIPC and
    SimConnect can hand over cleanly during an approach; continuity is decided
    from time and geometry after the shared sanitizer has rejected real jumps.
    """
    if len(rows) < 3:
        return rows
    ordered = sorted(rows, key=lambda row: (_sample_time(row) if _sample_time(row) is not None else float("inf")))
    segments: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    previous_nm: float | None = None
    previous_time: float | None = None
    for row in ordered:
        nm = _num(row.get("nm_to_threshold"))
        if nm is None:
            continue
        row_time = _sample_time(row)
        reset = False
        if previous_nm is not None:
            # Small GPS/runway-projection reversals are normal around localizer
            # intercepts. Only a clear movement away from the threshold or a
            # meaningful recording gap starts a new candidate segment.
            if nm > previous_nm + 0.75:
                reset = True
            if row_time is not None and previous_time is not None:
                dt = row_time - previous_time
                # v0.25.72 (#21): tolerate recorder gaps up to 60 s (the #9
                # SimConnect flood dropped samples), so a damaged stream still
                # yields a continuous-enough final approach.
                if dt <= 0.0 or dt > 60.0:
                    reset = True
        if reset and current:
            segments.append(current)
            current = []
        current.append(row)
        previous_nm = nm
        previous_time = row_time
    if current:
        segments.append(current)

    def credible(segment: list[dict[str, Any]], *, require_threshold: bool) -> bool:
        if len(segment) < 8:
            return False
        distances = [_num(item.get("nm_to_threshold")) for item in segment]
        distances = [value for value in distances if value is not None]
        if len(distances) < 8:
            return False
        if require_threshold and min(distances) > 1.25:
            return False
        # Require meaningful inbound progress, not a stationary cluster of
        # duplicate positions that merely happens to sit near the runway.
        return max(distances) - min(distances) >= 0.35

    good = [segment for segment in segments if credible(segment, require_threshold=True)]
    if good:
        return good[-1]
    candidates = [segment for segment in segments if credible(segment, require_threshold=False)]
    return candidates[-1] if candidates else []


def _touchdown_index(rows: list[dict[str, Any]], meta: dict[str, Any], takeoff_idx: int) -> int | None:
    """Find the first credible arrival contact sample.

    Prefer an actual airborne-to-ground transition. When a provider handover
    obscures one boolean sample, use the recorded landing time/position rather
    than falling back to the final parked sample.
    """
    transitions = [
        index for index in range(max(1, takeoff_idx + 1), len(rows))
        if not bool(rows[index - 1].get("on_ground")) and bool(rows[index].get("on_ground"))
    ]
    landing_epoch = None
    try:
        from datetime import datetime
        raw = ((meta.get("times") or {}).get("landing"))
        if raw:
            landing_epoch = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except Exception:
        landing_epoch = None

    if transitions:
        if landing_epoch is None:
            return transitions[0]
        def transition_distance(index: int) -> float:
            row = rows[index]
            raw_time = row.get("time")
            try:
                from datetime import datetime
                epoch = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00")).timestamp()
                return abs(epoch - landing_epoch)
            except Exception:
                return float("inf")
        return min(transitions, key=transition_distance)

    landing_position = (meta.get("positions") or {}).get("landing") or {}
    candidates: list[tuple[float, int]] = []
    for index in range(max(1, takeoff_idx + 1), len(rows)):
        row = rows[index]
        if not bool(row.get("on_ground")):
            continue
        gs = _num(row.get("ground_speed_kts")) or 0.0
        if gs < 25.0 or gs > 220.0:
            continue
        score = 0.0
        if _valid_latlon(landing_position):
            distance = _distance_nm(row, landing_position)
            score += (distance if distance is not None else 10.0) * 100.0
        if landing_epoch is not None:
            try:
                from datetime import datetime
                epoch = datetime.fromisoformat(str(row.get("time") or "").replace("Z", "+00:00")).timestamp()
                score += abs(epoch - landing_epoch)
            except Exception:
                score += 1000.0
        candidates.append((score, index))
    return min(candidates)[1] if candidates else None


def _row_heading(row: dict[str, Any]) -> float | None:
    value = _num(row.get("track_deg"))
    return value if value is not None else _num(row.get("heading_deg"))


def _approach_item(
    row: dict[str, Any],
    arrival_threshold: dict[str, Any],
    arrival_heading: float,
    threshold_alt: float,
) -> dict[str, Any] | None:
    xy = _local_xy_ft(row, arrival_threshold, arrival_heading)
    if not xy:
        return None
    nm_to_threshold = max(0.0, -xy[0] / FT_PER_NM)
    actual_agl = _num(row.get("radio_altitude_ft"))
    # A fixed zero radio-altimeter value above the runway is an unavailable
    # channel, not valid altitude. Prefer AGL/barometric geometry in that case.
    fallback_agl = _num(row.get("agl_ft"))
    if actual_agl is None or (actual_agl <= 1.0 and fallback_agl is not None and fallback_agl > 50.0):
        actual_agl = fallback_agl
    if actual_agl is None:
        actual_agl = max(0.0, (_num(row.get("altitude_ft")) or threshold_alt) - threshold_alt)
    ideal = nm_to_threshold * FT_PER_NM * math.tan(math.radians(3.0)) + 50.0
    item = dict(row)
    item.update({
        "nm_to_threshold": round(nm_to_threshold, 3),
        "lateral_deviation_ft": round(xy[1], 1),
        "approach_agl_ft": round(actual_agl, 1),
        "ideal_3deg_agl_ft": round(ideal, 1),
        "glidepath_deviation_ft": round(actual_agl - ideal, 1),
        "along_ft": round(xy[0], 1),
    })
    return item


def _bin_approach_profile(rows: list[dict[str, Any]], bin_nm: float = 0.05) -> list[dict[str, Any]]:
    """Collapse repeated threshold distances so charts cannot draw vertical teeth."""
    bins: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        nm = _num(row.get("nm_to_threshold"))
        if nm is None:
            continue
        bins.setdefault(int(round(nm / bin_nm)), []).append(row)
    result: list[dict[str, Any]] = []
    numeric = (
        "nm_to_threshold", "lateral_deviation_ft", "approach_agl_ft",
        "ideal_3deg_agl_ft", "glidepath_deviation_ft", "ground_speed_kts",
        "ias_kts", "indicated_speed_kts", "vertical_speed_fpm", "pitch_deg",
        "bank_deg", "gear_percent", "flap_percent",
    )
    for key in sorted(bins, reverse=True):
        group = bins[key]
        item = dict(group[-1])
        for field in numeric:
            values = [_num(row.get(field)) for row in group]
            values = [value for value in values if value is not None]
            if values:
                item[field] = round(float(median(values)), 3 if field == "nm_to_threshold" else 1)
        result.append(item)
    return result

def _stability_gate(rows: list[dict[str, Any]], target_agl: float) -> dict[str, Any]:
    sample = _closest(rows, "approach_agl_ft", target_agl)
    if not sample:
        return {"available": False, "target_agl_ft": target_agl, "stable": None, "checks": []}
    ias = _num(sample.get("ias_kts"))
    vs = _num(sample.get("vertical_speed_fpm"))
    bank = abs(_num(sample.get("bank_deg")) or 0.0)
    gear = _num(sample.get("gear_percent"))
    flap = _num(sample.get("flap_percent"))
    lateral = abs(_num(sample.get("lateral_deviation_ft")) or 0.0)
    glide = abs(_num(sample.get("glidepath_deviation_ft")) or 0.0)
    reference_speeds = [_num(x.get("ias_kts")) for x in rows if _num(x.get("approach_agl_ft")) is not None and 100 <= float(x.get("approach_agl_ft")) <= 800]
    reference_speeds = [x for x in reference_speeds if x is not None]
    vref_proxy = median(reference_speeds) if reference_speeds else ias
    checks = [
        {"key": "lateral", "label": "Lateral path", "ok": lateral <= (350 if target_agl >= 1000 else 250), "value": f"{lateral:.0f} ft"},
        {"key": "vertical", "label": "Vertical path", "ok": glide <= (350 if target_agl >= 1000 else 250), "value": f"{glide:.0f} ft"},
        {"key": "sink", "label": "Descent rate", "ok": vs is not None and -1200 <= vs <= -200, "value": f"{vs:.0f} fpm" if vs is not None else "No data"},
        {"key": "bank", "label": "Bank", "ok": bank <= 20, "value": f"{bank:.1f}°"},
        {"key": "gear", "label": "Gear", "ok": gear is not None and gear >= 90, "value": "DOWN" if gear is not None and gear >= 90 else ("No data" if gear is None else f"{gear:.0f}%")},
        {"key": "flaps", "label": "Flaps", "ok": flap is not None and flap >= (10 if target_agl >= 1000 else 20), "value": "SET" if flap is not None else "No data"},
        {"key": "speed", "label": "Speed", "ok": ias is not None and (vref_proxy is None or ias <= vref_proxy + 20), "value": f"{ias:.0f} kt" if ias is not None else "No data"},
    ]
    available_checks = [x for x in checks if x["value"] != "No data"]
    required_available = gear is not None and flap is not None
    stable = bool(available_checks) and required_available and all(x["ok"] for x in available_checks)
    return {
        "available": True,
        "target_agl_ft": target_agl,
        "stable": stable,
        "time": sample.get("time"),
        "distance_nm": _num(sample.get("nm_to_threshold")),
        "checks": checks,
    }


def _runway_ident(meta: dict[str, Any], arrival: bool) -> str:
    flight = meta.get("flight") or {}
    key = "arrival_runway" if arrival else "departure_runway"
    return str(flight.get(key) or "INFERRED").upper()


def analyse_pirep(meta: dict[str, Any], samples: list[dict[str, Any]]) -> dict[str, Any]:
    raw_rows = [dict(x) for x in samples if isinstance(x, dict)]
    rows, data_quality = _sanitize_samples(raw_rows)
    if data_quality.get("input_samples"):
        _LOG.info(
            "PIREP sample quality: input=%s kept=%s dup_or_stale=%s jumps=%s provider_transitions=%s gap_bridged=%s gap_dropped=%s gap_runs_dropped=%s",
            data_quality.get("input_samples"),
            data_quality.get("kept_samples"),
            data_quality.get("removed_duplicate_or_stale"),
            data_quality.get("removed_jumps"),
            data_quality.get("provider_transition_samples_skipped"),
            data_quality.get("gap_samples_bridged"),
            data_quality.get("gap_samples_dropped"),
            data_quality.get("gap_runs_dropped"),
        )
    if not rows:
        return {"ok": False, "reason": "No valid telemetry samples", "version": ANALYSIS_VERSION, "data_quality": data_quality}
    takeoff_idx = _first_transition(rows, True, False)
    if takeoff_idx is None:
        takeoff_idx = next((i for i, x in enumerate(rows) if str(x.get("phase")) in {"INITIAL CLIMB", "CLIMB"}), 0)
    landing_idx = _touchdown_index(rows, meta, takeoff_idx)
    if landing_idx is None:
        landing_idx = next((i for i in range(len(rows) - 1, takeoff_idx, -1) if bool(rows[i].get("on_ground"))), len(rows) - 1)
        data_quality["touchdown_reason"] = "No credible airborne-to-ground contact; using last available ground sample"
    else:
        data_quality["touchdown_sample_index"] = landing_idx

    # Begin the measured takeoff roll at the start of sustained runway
    # acceleration, not at the beginning of taxi or line-up. Keep a few
    # samples before 25 kt to show the start of the roll on the runway plot.
    roll_start = takeoff_idx
    while roll_start > 0 and bool(rows[roll_start - 1].get("on_ground")) and (_num(rows[roll_start - 1].get("ground_speed_kts")) or 0) >= 25:
        roll_start -= 1
    roll_start = max(0, roll_start - 5)
    # The final rollout limit is resolved after arrival runway geometry is
    # inferred. Do not allow taxi-in movement to inflate the runway rollout.
    roll_end = landing_idx

    departure_roll = rows[roll_start : takeoff_idx + 1]
    departure_heading = _heading([x for x in departure_roll if (_num(x.get("ground_speed_kts")) or 0) >= 25], _num(rows[takeoff_idx].get("track_deg")) or 0)
    departure_threshold = next((x for x in departure_roll if None not in (_num(x.get("lat")), _num(x.get("lon")))), rows[takeoff_idx])
    flight_meta = meta.get("flight") or {}
    dep_airport = str(flight_meta.get("origin") or ((meta.get("airports") or {}).get("takeoff") or {}).get("icao") or "").upper()
    arr_airport = str(flight_meta.get("destination") or ((meta.get("airports") or {}).get("landing") or {}).get("icao") or "").upper()
    dep_rwy_name = str(flight_meta.get("departure_runway") or "").upper()
    arr_rwy_name = str(flight_meta.get("arrival_runway") or "").upper()
    # v0.25.65: NOTAM conditions footnote for the PIREP record (dep/arr only).
    notam_footnote = _pirep_notam_footnote(dep_airport, arr_airport, rows)
    liftoff = rows[takeoff_idx]
    dep_nav, dep_geometry_source = _select_runway_end(dep_airport, dep_rwy_name, liftoff, departure_heading, max_nm=8.0)
    if dep_nav:
        departure_heading = float(dep_nav.get("heading_deg") or departure_heading)
        departure_threshold = {"lat": dep_nav.get("threshold_lat"), "lon": dep_nav.get("threshold_lon"), "altitude_ft": dep_nav.get("threshold_elevation_ft")}
    departure_profile: list[dict[str, Any]] = []
    departure_lateral: list[dict[str, Any]] = []
    liftoff_alt = _num(liftoff.get("altitude_ft")) or 0.0
    for row in rows[takeoff_idx : min(len(rows), takeoff_idx + 1800)]:
        dist = _distance_nm(liftoff, row)
        if dist is None:
            continue
        if dist > 15:
            break
        xy = _local_xy_ft(row, departure_threshold, departure_heading)
        if xy:
            departure_lateral.append({"distance_nm": round(dist, 3), "deviation_ft": round(xy[1], 1), "along_ft": round(xy[0], 1), "time": row.get("time")})
        departure_profile.append({"distance_nm": round(dist, 3), "altitude_agl_ft": round(max(0.0, (_num(row.get("altitude_ft")) or liftoff_alt) - liftoff_alt), 1), "ground_speed_kts": _num(row.get("ground_speed_kts")), "vertical_speed_fpm": _num(row.get("vertical_speed_fpm")), "time": row.get("time")})
    departure_runway_path = []
    for row in departure_roll:
        xy = _local_xy_ft(row, departure_threshold, departure_heading)
        if xy:
            departure_runway_path.append({"along_ft": round(xy[0], 1), "deviation_ft": round(xy[1], 1), "ground_speed_kts": _num(row.get("ground_speed_kts"))})
    takeoff_roll_path_ft = _path_distance_nm(departure_roll) * FT_PER_NM
    departure_along_span = _path_along_span_ft(departure_runway_path)
    dep_reference_length = _num((dep_nav or {}).get("length_ft")) or max(6000.0, takeoff_roll_path_ft + 1800.0)
    if departure_along_span is not None and 100.0 <= departure_along_span <= dep_reference_length * 1.18:
        takeoff_roll_ft = departure_along_span
    else:
        takeoff_roll_ft = takeoff_roll_path_ft
    liftoff_xy = _local_xy_ft(liftoff, departure_threshold, departure_heading) or (takeoff_roll_ft, 0.0)
    roll_start_xy = _local_xy_ft(departure_roll[0], departure_threshold, departure_heading) if departure_roll else None
    liftoff_distance_ft = max(0.0, liftoff_xy[0])
    roll_start_distance_ft = max(0.0, roll_start_xy[0]) if roll_start_xy else max(0.0, liftoff_distance_ft - takeoff_roll_ft)
    climb_sample = min(departure_profile, key=lambda x: abs(x["distance_nm"] - 5.0)) if departure_profile else None
    climb_gradient = (climb_sample["altitude_agl_ft"] / max(0.1, climb_sample["distance_nm"])) if climb_sample else None
    climb_rates = [_num(x.get("vertical_speed_fpm")) for x in rows[takeoff_idx : min(len(rows), takeoff_idx + 180)] if (_num(x.get("vertical_speed_fpm")) or 0) > 0]
    dep_gear = next((x for x in rows[takeoff_idx:] if (_num(x.get("gear_percent")) or 100) < 10), None)
    dep_flap = next((x for x in rows[takeoff_idx:] if (_num(x.get("flap_percent")) or 0) <= 1), None)

    touchdown = rows[landing_idx]
    approach_candidate = rows[max(takeoff_idx + 1, landing_idx - 2400) : landing_idx + 1]
    heading_rows = [x for x in approach_candidate if (_num(x.get("radio_altitude_ft")) or _num(x.get("agl_ft")) or 99999) < 1500]
    arrival_heading = _heading(heading_rows[-300:], _num(touchdown.get("track_deg")) or departure_heading)
    arr_nav, arr_geometry_source = _select_runway_end(arr_airport, arr_rwy_name, touchdown, arrival_heading, max_nm=8.0)
    if arr_nav:
        arrival_heading = float(arr_nav.get("heading_deg") or arrival_heading)
    threshold_sample = min(
        [x for x in approach_candidate if (_num(x.get("radio_altitude_ft")) or _num(x.get("agl_ft"))) is not None],
        key=lambda x: abs((_num(x.get("radio_altitude_ft")) if _num(x.get("radio_altitude_ft")) is not None else _num(x.get("agl_ft"))) - 50),
        default=None,
    )
    if arr_nav:
        threshold_sample = {"lat": arr_nav.get("threshold_lat"), "lon": arr_nav.get("threshold_lon"), "altitude_ft": arr_nav.get("threshold_elevation_ft")}
    elif threshold_sample is None or (_distance_nm(threshold_sample, touchdown) or 99) > 1.0:
        threshold_sample = _project(touchdown, arrival_heading, -1000.0)
    arrival_threshold = threshold_sample
    threshold_alt = (_num(threshold_sample.get("altitude_ft")) or (_num(touchdown.get("altitude_ft")) or 0.0))

    strict_approach_rows: list[dict[str, Any]] = []
    recovery_approach_rows: list[dict[str, Any]] = []
    for row in approach_candidate:
        item = _approach_item(row, arrival_threshold, arrival_heading, threshold_alt)
        if not item:
            continue
        nm_to_threshold = _num(item.get("nm_to_threshold")) or 0.0
        cross_ft = abs(_num(item.get("lateral_deviation_ft")) or 0.0)
        actual_agl = _num(item.get("approach_agl_ft")) or 0.0
        ideal = _num(item.get("ideal_3deg_agl_ft")) or 0.0
        gs_row = _num(row.get("ground_speed_kts")) or 0.0
        ias_row = _num(row.get("ias_kts")) or _num(row.get("indicated_speed_kts")) or gs_row
        vs_row = _num(row.get("vertical_speed_fpm")) or 0.0
        airborne = not bool(row.get("on_ground"))
        heading_delta = _heading_delta(_row_heading(row), arrival_heading)
        physically_final = (
            airborne
            and gs_row >= 40.0
            and 45.0 <= ias_row <= 280.0
            and -3500.0 <= vs_row <= 1800.0
            and 0.02 <= nm_to_threshold <= 15.5
            and cross_ft <= 6000.0
            and 0.0 <= actual_agl <= 9000.0
        )
        phase = str(row.get("phase") or "").upper()
        aligned_phase = phase in {"DESCENT", "APPROACH", "FINAL APPROACH", "LANDING", "LANDING ROLL"}
        strict_envelope = actual_agl <= max(3500.0, ideal + 2200.0)
        if physically_final and strict_envelope and (aligned_phase or nm_to_threshold <= 6.0 or actual_agl <= 2500.0):
            strict_approach_rows.append(item)

        # Recovery remains runway-aware and physically bounded, but it does not
        # depend on a perfect recorder phase label or a single telemetry source.
        # This restores coherent legacy PIREPs without reintroducing the loose
        # 16-NM fallback that previously drew impossible vertical teeth.
        recovery_cross_limit = min(6000.0, max(1400.0, nm_to_threshold * 380.0))
        recovery_envelope = actual_agl <= max(5000.0, ideal + 3500.0)
        heading_ok = heading_delta <= 50.0 or nm_to_threshold <= 3.0
        if physically_final and recovery_envelope and cross_ft <= recovery_cross_limit and heading_ok:
            recovery_approach_rows.append(item)

    approach_rows = _last_continuous_final(strict_approach_rows)
    analysis_mode = "strict"
    if len(approach_rows) < 8:
        approach_rows = _last_continuous_final(recovery_approach_rows)
        analysis_mode = "recovered" if len(approach_rows) >= 8 else "unavailable"
    if len(approach_rows) >= 8:
        approach_rows = _bin_approach_profile(approach_rows, 0.05)
    else:
        approach_rows = []
        data_quality["approach_reason"] = "Insufficient continuous, physically plausible final-approach telemetry"
    approach_rows.sort(key=lambda x: x["nm_to_threshold"], reverse=True)
    data_quality["approach_mode"] = analysis_mode
    data_quality["approach_samples"] = len(approach_rows)
    data_quality["approach_reliable"] = len(approach_rows) >= 8
    gate_1000 = _stability_gate(approach_rows, 1000)
    gate_500 = _stability_gate(approach_rows, 500)
    max_lateral = max((abs(_num(x.get("lateral_deviation_ft")) or 0.0) for x in approach_rows), default=None)
    max_glide = max((abs(_num(x.get("glidepath_deviation_ft")) or 0.0) for x in approach_rows), default=None)
    gear_distance = _event_distance(approach_rows, lambda x: (_num(x.get("gear_percent")) or 0) >= 90)
    max_flap = max((_num(x.get("flap_percent")) or 0 for x in approach_rows), default=0.0)
    flap_distance = _event_distance(approach_rows, lambda x: (_num(x.get("flap_percent")) or 0) >= max(20.0, max_flap * 0.9))

    touchdown_xy = _local_xy_ft(touchdown, arrival_threshold, arrival_heading)

    # Stop runway-roll analysis at sustained taxi speed, a clear runway exit,
    # a full stop, or five minutes after touchdown. This deliberately excludes
    # taxi-in and the turn toward the stand from rollout distance and centreline
    # metrics.
    roll_limit = min(len(rows) - 1, landing_idx + 300)
    roll_end = roll_limit
    for index in range(landing_idx + 5, roll_limit + 1):
        row = rows[index]
        if not bool(row.get("on_ground")):
            continue
        speed = _num(row.get("ground_speed_kts")) or 0.0
        window = rows[index : min(roll_limit + 1, index + 6)]
        window_speeds = [(_num(x.get("ground_speed_kts")) or 0.0) for x in window if bool(x.get("on_ground"))]
        xy = _local_xy_ft(row, arrival_threshold, arrival_heading)
        track = _num(row.get("track_deg"))
        if track is None:
            track = _num(row.get("heading_deg"))
        heading_delta = abs(((track - arrival_heading + 180.0) % 360.0) - 180.0) if track is not None else 0.0
        clear_exit = speed <= 60 and ((xy is not None and abs(xy[1]) > 110.0) or heading_delta > 25.0)
        taxi_speed = index - landing_idx >= 10 and window_speeds and max(window_speeds) <= 35.0
        if speed < 2.0 or clear_exit or taxi_speed:
            roll_end = index
            break

    rollout_rows = rows[landing_idx : roll_end + 1]
    landing_path: list[dict[str, Any]] = []
    for row in rollout_rows:
        xy = _local_xy_ft(row, arrival_threshold, arrival_heading)
        if xy:
            landing_path.append({"along_ft": round(xy[0], 1), "deviation_ft": round(xy[1], 1), "ground_speed_kts": _num(row.get("ground_speed_kts")), "time": row.get("time")})
    touchdown_distance_ft = max(0.0, touchdown_xy[0]) if touchdown_xy is not None else None
    rollout_path_ft = _path_distance_nm(rollout_rows) * FT_PER_NM
    rollout_along_ft = None
    if landing_path:
        last_along = _num(landing_path[-1].get("along_ft"))
        if last_along is not None:
            rollout_along_ft = max(0.0, last_along - touchdown_distance_ft) if touchdown_distance_ft is not None else None
    if rollout_along_ft is not None and rollout_along_ft <= max(18000.0, (_num((arr_nav or {}).get("length_ft")) or 12000.0) * 1.1):
        rollout_distance_ft = rollout_along_ft
    else:
        rollout_distance_ft = rollout_path_ft
    runway_length_est = max(6000.0, (touchdown_distance_ft or 0.0) + rollout_distance_ft + 1200.0, takeoff_roll_ft + 1800.0)
    if arr_nav and _num(arr_nav.get("length_ft")):
        runway_length_est = float(arr_nav.get("length_ft"))
    runway_length_est = math.ceil(runway_length_est / 100.0) * 100.0
    departure_runway_length = float(dep_nav.get("length_ft")) if dep_nav and _num(dep_nav.get("length_ft")) else runway_length_est
    departure_runway_width = float(dep_nav.get("width_ft")) if dep_nav and _num(dep_nav.get("width_ft")) else 150.0
    arrival_runway_width = float(arr_nav.get("width_ft")) if arr_nav and _num(arr_nav.get("width_ft")) else 150.0
    landing_geometry_valid = bool(arr_nav) and touchdown_xy is not None and touchdown_distance_ft is not None
    geometry_reason = None
    if not arr_nav:
        geometry_reason = "runway threshold geometry is unavailable"
    elif not landing_geometry_valid:
        geometry_reason = "touchdown position could not be projected onto the selected runway"
    elif abs(touchdown_xy[1]) > max(2500.0, arrival_runway_width * 12.0) or touchdown_distance_ft > runway_length_est + 2500.0:
        landing_geometry_valid = False
        geometry_reason = "invalid runway projection / touchdown geometry"
    data_quality["landing_geometry_valid"] = bool(landing_geometry_valid)
    if geometry_reason:
        data_quality["landing_geometry_reason"] = geometry_reason
    departure_runway_path = _clip_runway_path(departure_runway_path, departure_runway_length, departure_runway_width)
    landing_path = _clip_runway_path(landing_path, runway_length_est, arrival_runway_width) if landing_geometry_valid else []
    dep_rwy_label = str((dep_nav or {}).get("runway") or _runway_ident(meta, False)).upper()
    arr_rwy_label = str((arr_nav or {}).get("runway") or _runway_ident(meta, True)).upper()
    geometry_source = " / ".join(sorted({dep_geometry_source, arr_geometry_source}))
    max_rollout_deviation = max((abs(x["deviation_ft"]) for x in landing_path), default=None)

    phase_fuel = _phase_fuel(rows)
    flight = meta.get("flight") or {}
    durations = meta.get("durations") or {}
    fuel = meta.get("fuel") or {}
    metrics = meta.get("metrics") or {}
    actual_fuel = _num(fuel.get("used_lb"))
    planned_fuel = _num(flight.get("planned_trip_fuel"))
    actual_distance = _num(metrics.get("distance_nm"))
    planned_distance = _num(flight.get("distance_nm"))

    violations = meta.get("violations") or []
    violation_keys = {str(x.get("key") or "") for x in violations}
    departure_score = 15
    departure_score -= 3 if max((abs(x["deviation_ft"]) for x in departure_runway_path), default=0) > 50 else 0
    departure_score -= 2 if abs(_num(liftoff.get("bank_deg")) or 0) > 5 else 0
    departure_score -= 2 if takeoff_roll_ft > runway_length_est * 0.8 else 0
    enroute_score = 20 - sum(4 for key in violation_keys if key in {"overspeed", "stall", "speed-below-10k"})
    approach_score = 25
    if gate_1000.get("stable") is False: approach_score -= 8
    if gate_500.get("stable") is False: approach_score -= 10
    if max_lateral is not None and max_lateral > 600: approach_score -= 3
    landing_score = 25
    rate = abs(_num(metrics.get("landing_rate_fpm")) or 0)
    landing_score -= 0 if rate <= 200 else 3 if rate <= 350 else 7 if rate <= 500 else 14
    bounce_penalty = min(12, max(0, int(metrics.get("bounce_penalty") or 0)))
    landing_score -= bounce_penalty
    if landing_geometry_valid:
        landing_score -= 3 if touchdown_distance_ft is not None and touchdown_distance_ft > 3000 else 0
        landing_score -= 2 if touchdown_xy is not None and abs(touchdown_xy[1]) > 40 else 0
    integrity_score = 15
    if "slew" in violation_keys: integrity_score -= 10
    if "sim-rate" in violation_keys: integrity_score -= 4
    if "refuelling" in violation_keys: integrity_score -= 8
    if "pause" in violation_keys: integrity_score -= 1
    breakdown = {
        "departure": max(0, departure_score),
        "enroute": max(0, enroute_score),
        "approach": max(0, approach_score),
        "landing": max(0, landing_score),
        "integrity": max(0, integrity_score),
    }
    overall = max(0, min(100, sum(breakdown.values())))
    grade = "EXCELLENT" if overall >= 92 else "VERY GOOD" if overall >= 84 else "GOOD" if overall >= 74 else "ACCEPTABLE" if overall >= 62 else "REVIEW REQUIRED"

    return {
        "ok": True,
        "version": ANALYSIS_VERSION,
        "geometry_source": geometry_source,
        "notams": notam_footnote,
        "departure": {
            "runway": dep_rwy_label,
            "opposite_runway": _opposite_runway(dep_nav),
            "geometry_source": dep_geometry_source,
            "heading_deg": departure_heading,
            "runway_length_ft": departure_runway_length,
            "runway_width_ft": departure_runway_width,
            "runway_elevation_ft": _num((dep_nav or {}).get("threshold_elevation_ft")),
            "displaced_threshold_ft": _num((dep_nav or {}).get("displaced_threshold_ft")) or 0.0,
            "lda_ft": _num((dep_nav or {}).get("lda_ft")) or departure_runway_length,
            "takeoff_roll_ft": round(takeoff_roll_ft),
            "liftoff_distance_ft": round(liftoff_distance_ft),
            "roll_start_distance_ft": round(roll_start_distance_ft),
            "takeoff_roll_percent": round(takeoff_roll_ft / max(1.0, departure_runway_length) * 100, 1),
            "liftoff_speed_kts": _num(liftoff.get("ground_speed_kts")),
            "liftoff_ias_kts": _num(liftoff.get("ias_kts")),
            "liftoff_pitch_deg": _num(liftoff.get("pitch_deg")),
            "liftoff_bank_deg": _num(liftoff.get("bank_deg")),
            "max_centerline_deviation_ft": round(max((abs(x["deviation_ft"]) for x in departure_runway_path), default=0.0), 1),
            "climb_gradient_ft_nm": round(climb_gradient, 0) if climb_gradient is not None else None,
            "average_initial_climb_fpm": round(sum(x for x in climb_rates if x is not None) / len(climb_rates), 0) if climb_rates else None,
            "gear_up_time": dep_gear.get("time") if dep_gear else None,
            "flaps_up_time": dep_flap.get("time") if dep_flap else None,
            "runway_path": departure_runway_path,
            "lateral_profile": _dedupe_profile(departure_lateral, "distance_nm", min_delta=0.02, limit=900),
            "climb_profile": _dedupe_profile(departure_profile, "distance_nm", min_delta=0.02, limit=900),
        },
        "enroute": {
            "fuel_burn_by_phase_lb": phase_fuel,
            "actual_fuel_used_lb": actual_fuel,
            "planned_trip_fuel": planned_fuel,
            "fuel_variance": round(actual_fuel - planned_fuel, 1) if actual_fuel is not None and planned_fuel is not None else None,
            "actual_distance_nm": actual_distance,
            "planned_distance_nm": planned_distance,
            "distance_variance_nm": round(actual_distance - planned_distance, 1) if actual_distance is not None and planned_distance is not None else None,
            "actual_block_seconds": durations.get("block_seconds"),
            "planned_block_seconds": flight.get("block_time_seconds"),
            "actual_airborne_seconds": durations.get("airborne_seconds"),
            "planned_airborne_seconds": flight.get("ete_seconds"),
        },
        "approach": {
            "runway": arr_rwy_label,
            "opposite_runway": _opposite_runway(arr_nav),
            "geometry_source": arr_geometry_source,
            "heading_deg": arrival_heading,
            "max_lateral_deviation_ft": round(max_lateral, 1) if max_lateral is not None else None,
            "max_glidepath_deviation_ft": round(max_glide, 1) if max_glide is not None else None,
            "gear_down_distance_nm": gear_distance,
            "landing_flap_distance_nm": flap_distance,
            "stability_1000": gate_1000,
            "stability_500": gate_500,
            "profile": _dedupe_profile(approach_rows, "nm_to_threshold", min_delta=0.015, limit=1200),
        },
        "landing": {
            "runway": arr_rwy_label,
            "opposite_runway": _opposite_runway(arr_nav),
            "geometry_source": arr_geometry_source,
            "heading_deg": arrival_heading,
            "runway_length_ft": runway_length_est,
            "runway_width_ft": round(arrival_runway_width),
            "runway_elevation_ft": _num((arr_nav or {}).get("threshold_elevation_ft")),
            "displaced_threshold_ft": _num((arr_nav or {}).get("displaced_threshold_ft")) or 0.0,
            "lda_ft": _num((arr_nav or {}).get("lda_ft")) or runway_length_est,
            "touchdown_distance_ft": round(touchdown_distance_ft) if landing_geometry_valid and touchdown_distance_ft is not None else None,
            "touchdown_percent": round(touchdown_distance_ft / runway_length_est * 100, 1) if landing_geometry_valid and touchdown_distance_ft is not None else None,
            "touchdown_centerline_deviation_ft": round(touchdown_xy[1], 1) if landing_geometry_valid and touchdown_xy is not None else None,
            "touchdown_rate_fpm": _num(metrics.get("landing_rate_fpm")),
            "touchdown_g": _num(metrics.get("touchdown_g")),
            "touchdown_speed_kts": _num(metrics.get("touchdown_speed_kts")),
            "touchdown_pitch_deg": _num(touchdown.get("pitch_deg")),
            "touchdown_bank_deg": _num(touchdown.get("bank_deg")),
            "touchdowns": int(metrics.get("touchdowns") or 0),
            "bounce_count": int(metrics.get("bounce_count") or 0),
            "bounce_penalty": bounce_penalty,
            "bounce_severity": metrics.get("bounce_severity"),
            "rollout_distance_ft": round(rollout_distance_ft) if landing_geometry_valid else None,
            "max_rollout_deviation_ft": round(max_rollout_deviation, 1) if landing_geometry_valid and max_rollout_deviation is not None else None,
            "distance_remaining_at_touchdown_ft": round(max(0.0, runway_length_est - touchdown_distance_ft)) if landing_geometry_valid and touchdown_distance_ft is not None else None,
            "runway_path": landing_path,
        },
        "data_quality": data_quality,
        "score": {"overall": overall, "grade": grade, "breakdown": breakdown, "bounce_penalty": bounce_penalty, "model": "OPS ROOM PIREP PRO V1"},
        # v0.25.9: passenger satisfaction hook runs INSIDE analyse_pirep so
        # `meta`, `result`, `samples`, and the v0259 module-level context all
        # resolve correctly. Weights resolve in this precedence:
        #   1. meta["passenger_satisfaction_weights"] (per-flight override)
        #   2. load_settings()["integrations"]["passenger_satisfaction"] (Settings Store)
        #   3. passenger_satisfaction.DEFAULT_WEIGHTS
        # Idempotent and tolerant of missing telemetry fields.
        "passenger_satisfaction": _opsroom_pirep_compute_satisfaction(meta, result),
    }
    return result


def _opsroom_pirep_compute_satisfaction(meta: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    try:
        from .passenger_satisfaction import compute as _satisfaction_compute, DEFAULT_WEIGHTS as _SATIS_DEFAULT_WEIGHTS
        try:
            from .settings_store import load_settings as _opsroom_load_settings
            _satis_settings_weights = (_opsroom_load_settings().get("integrations", {}) or {}).get("passenger_satisfaction") or {}
        except Exception:
            _satis_settings_weights = {}
        _satis_weights = ((meta or {}).get("passenger_satisfaction_weights") if isinstance(meta, dict) else None) \
            or _satis_settings_weights or _SATIS_DEFAULT_WEIGHTS
        _satis_meta = {
            "departure_delay_minutes": (meta or {}).get("departure_delay_minutes"),
            "arrival_delay_minutes": (meta or {}).get("arrival_delay_minutes"),
            "emergency_events": (meta or {}).get("emergency_events") or (meta or {}).get("emergency_count"),
        }
        return _satisfaction_compute(_satis_meta, result, _satis_weights)
    except Exception as _satis_exc:  # missing telemetry must not break scoring
        return {"error": f"{type(_satis_exc).__name__}: {_satis_exc}"}
