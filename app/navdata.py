from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
NAVDATA_PATH = BASE_DIR / "data" / "navigation" / "opsroom_navdata.sqlite"
EARTH_NM = 3440.065
FT_PER_NM = 6076.12


def _num(value: Any) -> float | None:
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def _connect() -> sqlite3.Connection | None:
    if not NAVDATA_PATH.is_file():
        return None
    con = sqlite3.connect(NAVDATA_PATH)
    con.row_factory = sqlite3.Row
    return con


def available() -> bool:
    return NAVDATA_PATH.is_file()


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return EARTH_NM * 2 * math.atan2(math.sqrt(h), math.sqrt(max(0.0, 1-h)))


def airport(ident: str | None) -> dict[str, Any] | None:
    code = str(ident or "").strip().upper()[:8]
    if not code:
        return None
    con = _connect()
    if con is None:
        return None
    try:
        row = con.execute("SELECT * FROM airport WHERE ident=?", (code,)).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def airport_com(ident: str | None) -> list[dict[str, Any]]:
    code = str(ident or "").strip().upper()[:8]
    if not code:
        return []
    con = _connect()
    if con is None:
        return []
    try:
        rows = con.execute("SELECT type,frequency_mhz,name FROM com WHERE airport_ident=? ORDER BY type,frequency_mhz", (code,)).fetchall()
        return [dict(row) for row in rows]
    finally:
        con.close()


def runway_candidates(ident: str | None) -> list[dict[str, Any]]:
    code = str(ident or "").strip().upper()[:8]
    if not code:
        return []
    con = _connect()
    if con is None:
        return []
    try:
        rows = con.execute("SELECT * FROM runway WHERE airport_ident=? ORDER BY length_ft DESC", (code,)).fetchall()
        return [dict(row) for row in rows]
    finally:
        con.close()


def _local_xy_ft(lat: float, lon: float, lat0: float, lon0: float, heading_deg: float) -> tuple[float, float]:
    north = (lat - lat0) * 60.0 * FT_PER_NM
    east = (lon - lon0) * 60.0 * math.cos(math.radians((lat + lat0) / 2.0)) * FT_PER_NM
    angle = math.radians(heading_deg)
    along = east * math.sin(angle) + north * math.cos(angle)
    cross = east * math.cos(angle) - north * math.sin(angle)
    return along, cross


def _heading_delta(a: float, b: float) -> float:
    return abs(((a - b + 180.0) % 360.0) - 180.0)


def _runway_end_entry(row: dict[str, Any], end: str) -> dict[str, Any]:
    """Return a single runway-end entry across both legacy and RC2 navdata schemas."""
    # Legacy schema from early builds
    if "name_a" in row or "name_b" in row:
        if end == "a":
            name, lat, lon, elev, offset, lda, heading, ils_ident, ils_freq = row.get("name_a"), row.get("lat_a"), row.get("lon_a"), row.get("elev_a_ft"), row.get("offset_a_ft"), row.get("lda_a_ft"), row.get("heading_true"), row.get("ils_a_ident"), row.get("ils_a_freq_mhz")
        else:
            name, lat, lon, elev, offset, lda, heading, ils_ident, ils_freq = row.get("name_b"), row.get("lat_b"), row.get("lon_b"), row.get("elev_b_ft"), row.get("offset_b_ft"), row.get("lda_b_ft"), (float(row.get("heading_true") or 0)+180)%360, row.get("ils_b_ident"), row.get("ils_b_freq_mhz")
        length = _num(row.get("length_ft"))
        width = _num(row.get("width_ft"))
        return {**row, "runway": str(name or "").upper(), "threshold_lat": lat, "threshold_lon": lon, "threshold_elevation_ft": elev, "heading_deg": heading, "displaced_threshold_ft": offset, "lda_ft": lda or (length - (_num(offset) or 0.0) if length else None), "length_ft": length, "width_ft": width, "ils_ident": ils_ident, "ils_frequency_mhz": ils_freq}

    # Current packaged navdata schema
    length = _num(row.get("length_ft"))
    width = _num(row.get("width_ft"))
    if end == "a":
        name = row.get("primary_end_name")
        lat = row.get("primary_lat")
        lon = row.get("primary_lon")
        heading = row.get("primary_heading_deg") or row.get("heading_deg")
        offset = _num(row.get("primary_offset_threshold_ft")) or 0.0
        lda = length - offset if length is not None else None
        has_tdz = row.get("primary_has_touchdown_lights")
        app = row.get("primary_app_light_system_type")
    else:
        name = row.get("secondary_end_name")
        lat = row.get("secondary_lat")
        lon = row.get("secondary_lon")
        heading = row.get("secondary_heading_deg")
        if heading is None and row.get("heading_deg") is not None:
            heading = (float(row.get("heading_deg") or 0)+180)%360
        offset = _num(row.get("secondary_offset_threshold_ft")) or 0.0
        lda = length - offset if length is not None else None
        has_tdz = row.get("secondary_has_touchdown_lights")
        app = row.get("secondary_app_light_system_type")
    return {
        **row,
        "runway": str(name or "").upper(),
        "threshold_lat": lat,
        "threshold_lon": lon,
        "threshold_elevation_ft": row.get("altitude_ft"),
        "heading_deg": heading,
        "displaced_threshold_ft": offset,
        "lda_ft": lda,
        "length_ft": length,
        "width_ft": width,
        "has_touchdown_lights": bool(has_tdz),
        "app_light_system_type": app,
    }

def runway_by_name(airport_ident: str | None, runway_name: str | None) -> dict[str, Any] | None:
    target = str(runway_name or "").upper().replace("RW", "").strip()
    if not target:
        return None
    for row in runway_candidates(airport_ident):
        primary = str(row.get("name_a") or row.get("primary_end_name") or "").upper()
        secondary = str(row.get("name_b") or row.get("secondary_end_name") or "").upper()
        if primary == target:
            return _runway_end_entry(row, "a")
        if secondary == target:
            return _runway_end_entry(row, "b")
    return None


def runway_full(airport_ident: str | None, runway_name: str | None) -> dict[str, Any] | None:
    """Return the full runway record (both ends + centerline) for a closed runway.

    Matches on either end name (``09L`` or ``27R`` for ``09L/27R``) and returns
    a dict with ``runway`` (canonical ``09L/27R``), ``length_ft``, ``width_ft``
    and both ends under ``primary`` / ``secondary`` (each with ``name``,
    ``lat``, ``lon``, ``heading_deg``, ``elevation_ft``) across both the
    legacy and current packaged navdata schemas. ``None`` when the runway is
    not in navdata.
    """
    target = str(runway_name or "").upper().replace("RW", "").strip()
    if not target:
        return None
    for row in runway_candidates(airport_ident):
        if "name_a" in row or "name_b" in row:
            primary_name = str(row.get("name_a") or "").upper()
            secondary_name = str(row.get("name_b") or "").upper()
        else:
            primary_name = str(row.get("primary_end_name") or "").upper()
            secondary_name = str(row.get("secondary_end_name") or "").upper()
        if target not in (primary_name, secondary_name):
            continue
        length = _num(row.get("length_ft"))
        width = _num(row.get("width_ft"))
        if "name_a" in row or "name_b" in row:
            primary = {
                "name": primary_name, "lat": row.get("lat_a"), "lon": row.get("lon_a"),
                "heading_deg": _num(row.get("heading_true")),
                "elevation_ft": row.get("elev_a_ft"),
            }
            hdg_b = _num(row.get("heading_true"))
            secondary = {
                "name": secondary_name, "lat": row.get("lat_b"), "lon": row.get("lon_b"),
                "heading_deg": ((hdg_b + 180.0) % 360.0) if hdg_b is not None else None,
                "elevation_ft": row.get("elev_b_ft"),
            }
        else:
            primary = {
                "name": primary_name, "lat": row.get("primary_lat"), "lon": row.get("primary_lon"),
                "heading_deg": _num(row.get("primary_heading_deg") or row.get("heading_deg")),
                "elevation_ft": row.get("altitude_ft"),
            }
            hdg_b = _num(row.get("secondary_heading_deg"))
            if hdg_b is None and row.get("heading_deg") is not None:
                hdg_b = (float(row.get("heading_deg") or 0.0) + 180.0) % 360.0
            secondary = {
                "name": secondary_name, "lat": row.get("secondary_lat"), "lon": row.get("secondary_lon"),
                "heading_deg": hdg_b,
                "elevation_ft": row.get("altitude_ft"),
            }
        if primary.get("lat") is None or primary.get("lon") is None or secondary.get("lat") is None or secondary.get("lon") is None:
            return None
        return {
            "runway": f"{primary_name}/{secondary_name}" if primary_name and secondary_name else target,
            "airport_ident": str(airport_ident or "").upper(),
            "length_ft": length, "width_ft": width,
            "primary": primary, "secondary": secondary,
        }
    return None


def nearest_runway_end(lat: float, lon: float, airport_ident: str | None = None, track_deg: float | None = None, max_nm: float = 15.0) -> dict[str, Any] | None:
    con = _connect()
    if con is None:
        return None
    try:
        rows: list[sqlite3.Row]
        if airport_ident:
            rows = con.execute("SELECT * FROM runway WHERE airport_ident=?", (str(airport_ident).upper(),)).fetchall()
        else:
            # Bounding box first, then exact geometry. 0.35 deg is ~21 NM in latitude.
            rows = con.execute("SELECT r.* FROM runway r JOIN airport a ON a.ident=r.airport_ident WHERE a.lat BETWEEN ? AND ? AND a.lon BETWEEN ? AND ?", (lat-0.35, lat+0.35, lon-0.55, lon+0.55)).fetchall()
        best: tuple[float, dict[str, Any]] | None = None
        for raw in rows:
            row = dict(raw)
            for end in ("a", "b"):
                entry = _runway_end_entry(row, end)
                tlat, tlon = _num(entry.get("threshold_lat")), _num(entry.get("threshold_lon"))
                heading = _num(entry.get("heading_deg"))
                if None in (tlat, tlon, heading):
                    continue
                dist = haversine_nm(lat, lon, tlat, tlon)
                if dist > max_nm:
                    continue
                along, cross = _local_xy_ft(lat, lon, tlat, tlon, heading)
                heading_penalty = 0.0
                if track_deg is not None:
                    heading_penalty = _heading_delta(float(track_deg), heading) / 45.0
                score = dist + abs(cross) / 2500.0 + heading_penalty
                entry.update({"distance_nm": round(dist, 3), "along_ft": round(along, 1), "cross_ft": round(cross, 1), "geometry_source": "OPS ROOM NAVDATA"})
                if best is None or score < best[0]:
                    best = (score, entry)
        return best[1] if best else None
    finally:
        con.close()


def runway_ends_near(lat: float, lon: float, airport_ident: str | None = None, track_deg: float | None = None, max_nm: float = 15.0, limit: int = 12) -> list[dict[str, Any]]:
    """Return nearby runway ends with live local-geometry projections.

    RAAS uses this instead of a single nearest threshold so it can detect
    runway-edge crossings, final approach alignment, and correct remaining
    distance direction from the full runway geometry.
    """
    con = _connect()
    if con is None:
        return []
    try:
        if airport_ident:
            rows = con.execute("SELECT * FROM runway WHERE airport_ident=?", (str(airport_ident).upper(),)).fetchall()
        else:
            rows = con.execute(
                "SELECT r.* FROM runway r JOIN airport a ON a.ident=r.airport_ident WHERE a.lat BETWEEN ? AND ? AND a.lon BETWEEN ? AND ?",
                (lat - 0.35, lat + 0.35, lon - 0.55, lon + 0.55),
            ).fetchall()
        out: list[tuple[float, dict[str, Any]]] = []
        for raw in rows:
            row = dict(raw)
            for end in ("a", "b"):
                entry = _runway_end_entry(row, end)
                tlat, tlon = _num(entry.get("threshold_lat")), _num(entry.get("threshold_lon"))
                heading = _num(entry.get("heading_deg"))
                if None in (tlat, tlon, heading):
                    continue
                dist = haversine_nm(lat, lon, tlat, tlon)
                if dist > max_nm:
                    continue
                along, cross = _local_xy_ft(lat, lon, tlat, tlon, heading)
                heading_penalty = 0.0
                if track_deg is not None:
                    heading_penalty = _heading_delta(float(track_deg), heading) / 90.0
                score = dist + abs(cross) / 3000.0 + abs(along) / 50000.0 + heading_penalty
                entry.update({
                    "distance_nm": round(dist, 3),
                    "along_ft": round(along, 1),
                    "cross_ft": round(cross, 1),
                    "geometry_source": "OPS ROOM NAVDATA",
                })
                out.append((score, entry))
        out.sort(key=lambda item: item[0])
        return [item for _, item in out[:max(1, int(limit or 12))]]
    finally:
        con.close()


def project_local(lat: float, lon: float, runway: dict[str, Any]) -> tuple[float, float] | None:
    tlat, tlon, hdg = _num(runway.get("threshold_lat")), _num(runway.get("threshold_lon")), _num(runway.get("heading_deg"))
    if None in (tlat, tlon, hdg):
        return None
    return _local_xy_ft(lat, lon, tlat, tlon, hdg)
