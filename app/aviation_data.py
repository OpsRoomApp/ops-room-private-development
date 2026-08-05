from __future__ import annotations

import logging
import math
import os
import sqlite3
import struct
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from .settings_store import load_settings, app_data_dir

_LOGGER = logging.getLogger("opsroom.aviation_data")

DB_PATH = Path(__file__).resolve().parent / "data" / "navigation" / "opsroom_aviation.sqlite"
_SURFACE_PREFIX = "little_" + "navmap"
_SURFACE_FOLDER = _SURFACE_PREFIX + "_db"
_SURFACE_MSFS_FILE = _SURFACE_PREFIX + "_msfs.sqlite"


def _num(value: Any) -> float | None:
    try:
        v = float(value)
        if math.isfinite(v):
            return v
    except Exception:
        return None
    return None


def _bbox_parts(bbox: str | None) -> tuple[float, float, float, float] | None:
    if not bbox:
        return None
    try:
        a = [float(x.strip()) for x in str(bbox).split(",")]
        if len(a) != 4:
            return None
        min_lon, min_lat, max_lon, max_lat = a
        return min_lon, min_lat, max_lon, max_lat
    except Exception:
        return None


@lru_cache(maxsize=1)
def available() -> bool:
    return DB_PATH.is_file()


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _settings_integrations() -> dict[str, Any]:
    data = load_settings().get("integrations", {})
    return data if isinstance(data, dict) else {}


def _expand_user_path(value: str) -> Path:
    raw = os.path.expandvars(str(value or "").strip().strip('"'))
    return Path(raw).expanduser()


def _surface_candidate_paths() -> list[tuple[Path, str]]:
    integrations = _settings_integrations()
    out: list[tuple[Path, str]] = []
    configured = str(integrations.get("local_surface_db_path") or "").strip()
    if configured:
        p = _expand_user_path(configured)
        out.append(((p / _SURFACE_MSFS_FILE) if p.is_dir() else p, "configured"))
    env = os.getenv("OPSROOM_LOCAL_SURFACE_DB") or os.getenv("OPSROOM_SURFACE_DB_PATH")
    if env:
        p = _expand_user_path(env)
        out.append(((p / _SURFACE_MSFS_FILE) if p.is_dir() else p, "environment"))
    if bool(integrations.get("local_surface_db_auto_detect", True)):
        appdata = os.getenv("APPDATA")
        if appdata:
            out.append((Path(appdata) / "ABarthel" / _SURFACE_FOLDER / _SURFACE_MSFS_FILE, "auto-detected"))
        home = Path.home()
        out.append((home / "AppData" / "Roaming" / "ABarthel" / _SURFACE_FOLDER / _SURFACE_MSFS_FILE, "auto-detected"))
    seen: set[str] = set()
    unique: list[tuple[Path, str]] = []
    for path, source in out:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append((path, source))
    return unique


def _surface_schema_ok(path: Path) -> bool:
    try:
        con = sqlite3.connect(str(path), timeout=1.5)
        try:
            required = {"airport", "runway", "runway_end", "taxi_path"}
            names = {row[0] for row in con.execute("select name from sqlite_master where type='table'")}
            return required.issubset(names)
        finally:
            con.close()
    except Exception:
        return False


@lru_cache(maxsize=1)
def local_surface_source() -> dict[str, Any]:
    for path, source in _surface_candidate_paths():
        try:
            if path.is_file() and _surface_schema_ok(path):
                return {"available": True, "path": str(path), "source": source, "message": "Local airport surface data available"}
        except Exception:
            continue
    checked = [str(p) for p, _ in _surface_candidate_paths()[:4]]
    return {"available": False, "path": "", "source": "none", "checked": checked, "message": "Local airport surface data not configured or not detected"}


def clear_surface_cache() -> None:
    try:
        local_surface_source.cache_clear()
    except Exception:
        pass
    try:
        _airport_surface_from_local.cache_clear()
    except Exception:
        pass


def status() -> dict[str, Any]:
    counts: dict[str, int] = {}
    if available():
        con = _connect()
        try:
            for table in ["surface_airport", "surface_runway", "surface_runway_end", "nav_waypoint", "nav_navaid", "nav_airway", "nav_boundary"]:
                try:
                    counts[table] = int(con.execute(f"select count(*) from {table}").fetchone()[0])
                except Exception:
                    counts[table] = 0
        finally:
            con.close()
    surf = local_surface_source()
    return {
        "ok": bool(available()),
        "available": bool(available()),
        "database": "opsroom_aviation.sqlite" if available() else "",
        "mode": "slim-global-plus-local-surface",
        "counts": counts,
        "surface": {
            "available": bool(surf.get("available")),
            "source": surf.get("source"),
            "path": surf.get("path"),
            "message": surf.get("message"),
            "checked": surf.get("checked", []),
        },
        "message": "Slim global aviation layers ready. Detailed airport surface uses local simulator nav data when available." if available() else "Aviation layer database not installed",
    }


def _rows(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    con = _connect()
    try:
        return [dict(r) for r in con.execute(query, params).fetchall()]
    finally:
        con.close()


def airports_layer(bbox: str | None = None, limit: int = 1000) -> dict[str, Any]:
    if not available():
        return status()
    b = _bbox_parts(bbox)
    limit = max(1, min(int(limit or 1000), 5000))
    if b:
        min_lon, min_lat, max_lon, max_lat = b
        rows = _rows("""
            select ident,name,city,country,lat,lon,altitude_ft,longest_runway_ft,num_runways
            from surface_airport
            where lon between ? and ? and lat between ? and ?
            order by longest_runway_ft desc nulls last limit ?
        """, (min_lon, max_lon, min_lat, max_lat, limit))
    else:
        rows = _rows("""
            select ident,name,city,country,lat,lon,altitude_ft,longest_runway_ft,num_runways
            from surface_airport order by longest_runway_ft desc nulls last limit ?
        """, (limit,))
    return {"ok": True, "items": rows}


def navaids_layer(bbox: str | None = None, limit: int = 1500) -> dict[str, Any]:
    if not available():
        return status()
    b = _bbox_parts(bbox)
    limit = max(1, min(int(limit or 1500), 5000))
    where = ""
    if b:
        min_lon, min_lat, max_lon, max_lat = b
        where = "where lon between ? and ? and lat between ? and ?"
        params: tuple[Any, ...] = (min_lon, max_lon, min_lat, max_lat, limit)
    else:
        params = (limit,)
    rows = _rows(f"""
        select ident,name,kind,type,frequency,lat,lon,range_nm,altitude_ft
        from nav_navaid {where}
        order by kind, ident limit ?
    """, params)
    return {"ok": True, "items": rows}


def waypoints_layer(bbox: str | None = None, limit: int = 2000) -> dict[str, Any]:
    if not available():
        return status()
    b = _bbox_parts(bbox)
    limit = max(1, min(int(limit or 2000), 8000))
    if b:
        min_lon, min_lat, max_lon, max_lat = b
        rows = _rows("""
            select ident,name,type,lat,lon from nav_waypoint
            where lon between ? and ? and lat between ? and ?
            order by ident limit ?
        """, (min_lon, max_lon, min_lat, max_lat, limit))
    else:
        rows = []
    return {"ok": True, "items": rows}


def airways_layer(bbox: str | None = None, limit: int = 2000) -> dict[str, Any]:
    if not available():
        return status()
    b = _bbox_parts(bbox)
    limit = max(1, min(int(limit or 2000), 6000))
    if b:
        min_lon, min_lat, max_lon, max_lat = b
        rows = _rows("""
            select name,type,route_type,min_altitude_ft,max_altitude_ft,from_lat,from_lon,to_lat,to_lon
            from nav_airway
            where not (max_lon < ? or min_lon > ? or max_lat < ? or min_lat > ?)
            order by name limit ?
        """, (min_lon, max_lon, min_lat, max_lat, limit))
    else:
        rows = []
    return {"ok": True, "items": rows}


def _local_boundary_rows(b: tuple[float, float, float, float], limit: int) -> list[dict[str, Any]]:
    min_lon, min_lat, max_lon, max_lat = b
    return _rows("""
        select name,type,min_altitude,max_altitude,min_lat,min_lon,max_lat,max_lon
        from nav_boundary
        where not (max_lon < ? or min_lon > ? or max_lat < ? or min_lat > ?)
        order by type,name limit ?
    """, (min_lon, max_lon, min_lat, max_lat, limit))


def airspaces_layer(bbox: str | None = None, limit: int = 1000) -> dict[str, Any]:
    """Airspace layer for the live map.

    When OpenAIP enrichment is enabled (map toggle on), the layer supplements
    the built-in ``nav_boundary`` data with real OpenAIP airspace polygons
    (source-labelled). Local rows are always kept so no previously-working
    data disappears. Any OpenAIP failure degrades cleanly to the built-in
    local data, keeping the layer's prior behaviour and payload shape exactly
    intact when OpenAIP is unavailable or disabled.
    """
    if not available():
        return status()
    b = _bbox_parts(bbox)
    limit = max(1, min(int(limit or 1000), 3000))
    openaip_meta: dict[str, Any] | None = None
    if b:
        try:
            from .openaip_client import airspaces as openaip_airspaces, openaip_enabled
            if openaip_enabled():
                oa = openaip_airspaces(bbox, limit=limit)
                if oa.get("ok") and oa.get("items"):
                    items = list(oa["items"])
                    local_rows = _local_boundary_rows(b, limit)
                    if local_rows:
                        items.extend({**row, "source": "local", "source_label": "Local aviation DB"}
                                     for row in local_rows)
                        source = "mixed"
                    else:
                        source = "openaip"
                    meta = dict(oa.get("meta") or {})
                    meta.update({"source": source, "fetched_at": oa.get("fetched_at"),
                                "count": len(oa["items"]), "local_count": len(local_rows)})
                    return {"ok": True, "source": source, "items": items, "openaip": meta}
                openaip_meta = {"attempted": True, "failed": True,
                                "reason": oa.get("reason") or "request_failed",
                                "error": oa.get("error")}
        except Exception as exc:  # enrichment must never break the layer
            _LOGGER.warning("OpenAIP airspace enrichment failed: %s", exc)
            openaip_meta = {"attempted": True, "failed": True, "reason": "client_error"}
    if b:
        rows = _local_boundary_rows(b, limit)
    else:
        rows = []
    result: dict[str, Any] = {"ok": True, "items": rows}
    if openaip_meta is not None:
        result["source"] = "local"
        result["openaip"] = openaip_meta
    return result


def _decode_points(blob: bytes | None) -> list[list[float]]:
    if not blob or len(blob) < 12:
        return []
    for endian in (">", "<"):
        try:
            count = struct.unpack(endian + "I", blob[:4])[0]
            if count <= 0 or count > 20000 or len(blob) < 4 + count * 8:
                continue
            pts: list[list[float]] = []
            off = 4
            for _ in range(count):
                a, b = struct.unpack(endian + "ff", blob[off:off + 8])
                off += 8
                if -180 <= a <= 180 and -90 <= b <= 90:
                    pts.append([float(a), float(b)])
            if len(pts) >= 3:
                return pts
        except Exception:
            continue
    return []


def _local_con(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=5.0)
    con.row_factory = sqlite3.Row
    return con


def _airport_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "airport_id": row["airport_id"], "ident": row["ident"], "iata": row["iata"], "name": row["name"],
        "city": row["city"], "state": row["state"], "country": row["country"],
        "lat": row["laty"], "lon": row["lonx"], "altitude_ft": row["altitude"],
        "longest_runway_ft": row["longest_runway_length"], "num_runways": row["num_runways"],
        "num_parking_gate": row["num_parking_gate"], "num_taxi_path": row["num_taxi_path"], "num_apron": row["num_apron"],
    }


def _merge_taxi_segments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge connected taxi-path segments into browser-friendly polylines.

    The simulator surface database stores taxiways as thousands of tiny edges.
    Sending one OpenLayers feature per edge is needlessly expensive and makes
    labels appear late. Chains are merged only through degree-two vertices so
    junction topology is preserved and no taxiway is invented across a branch.
    """
    from collections import defaultdict

    def point_key(lon: Any, lat: Any) -> tuple[float, float]:
        return (round(float(lon), 7), round(float(lat), 7))

    grouped: dict[tuple[str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        try:
            a = point_key(row.get("start_lon"), row.get("start_lat")); b = point_key(row.get("end_lon"), row.get("end_lat"))
        except (TypeError, ValueError):
            continue
        if a == b:
            continue
        key = (
            str(row.get("name") or "").strip(), str(row.get("type") or "").strip(),
            str(row.get("surface") or "").strip(), int(round(float(row.get("width_ft") or 0) / 5.0) * 5),
        )
        grouped[key].append({**row, "_a": a, "_b": b})

    merged: list[dict[str, Any]] = []
    for (name, kind, surface, width), edges in grouped.items():
        adjacency: dict[tuple[float, float], list[int]] = defaultdict(list)
        for index, edge in enumerate(edges):
            adjacency[edge["_a"]].append(index); adjacency[edge["_b"]].append(index)
        unused = set(range(len(edges)))

        def walk(start_edge: int, start_point: tuple[float, float]) -> list[tuple[float, float]]:
            points = [start_point]; edge_index = start_edge; current = start_point
            while edge_index in unused:
                unused.remove(edge_index); edge = edges[edge_index]
                nxt = edge["_b"] if current == edge["_a"] else edge["_a"]
                points.append(nxt); current = nxt
                candidates = [idx for idx in adjacency[current] if idx in unused]
                if len(adjacency[current]) != 2 or len(candidates) != 1:
                    break
                edge_index = candidates[0]
            return points

        # Open chains and branches first, then any closed loops.
        while unused:
            preferred = None
            for idx in unused:
                edge = edges[idx]
                for endpoint in (edge["_a"], edge["_b"]):
                    if len(adjacency[endpoint]) != 2:
                        preferred = (idx, endpoint); break
                if preferred: break
            if preferred is None:
                idx = next(iter(unused)); preferred = (idx, edges[idx]["_a"])
            points = walk(*preferred)
            if len(points) < 2:
                continue
            merged.append({
                "name": name, "type": kind, "surface": surface, "width_ft": width,
                "points": [[lon, lat] for lon, lat in points],
                "start_lon": points[0][0], "start_lat": points[0][1],
                "end_lon": points[-1][0], "end_lat": points[-1][1],
                "segment_count": len(points) - 1,
            })
    return merged


@lru_cache(maxsize=64)
def _airport_surface_from_local(path: str, ident: str, mtime_bucket: int) -> dict[str, Any]:
    con = _local_con(path)
    try:
        ap = con.execute("select * from airport where upper(ident)=?", (ident,)).fetchone()
        if not ap:
            return {"ok": False, "icao": ident, "message": "Airport not found in local surface data"}
        airport_id = ap["airport_id"]
        runways = [dict(r) for r in con.execute("""
            select runway_id, airport_id,
                   coalesce((select name from runway_end e where e.runway_end_id=primary_end_id),'') as primary_name,
                   coalesce((select name from runway_end e where e.runway_end_id=secondary_end_id),'') as secondary_name,
                   coalesce((select name from runway_end e where e.runway_end_id=primary_end_id),'')||'/'||coalesce((select name from runway_end e where e.runway_end_id=secondary_end_id),'') as name,
                   surface, length as length_ft, width as width_ft, heading,
                   primary_lonx as primary_lon, primary_laty as primary_lat,
                   secondary_lonx as secondary_lon, secondary_laty as secondary_lat,
                   altitude as altitude_ft
            from runway where airport_id=? order by name
        """, (airport_id,))]
        ends = [dict(r) for r in con.execute("""
            select e.runway_end_id, r.airport_id, r.runway_id,
                   (select p.name from runway_end p where p.runway_end_id=r.primary_end_id)||'/'||(select q.name from runway_end q where q.runway_end_id=r.secondary_end_id) as runway_name,
                   e.name, e.heading, e.lonx as lon, e.laty as lat, e.altitude as altitude_ft,
                   e.offset_threshold as offset_threshold_ft, e.is_takeoff, e.is_landing
            from runway_end e join runway r on e.runway_end_id in (r.primary_end_id, r.secondary_end_id)
            where r.airport_id=? order by runway_name,name
        """, (airport_id,))]
        raw_taxi = [dict(r) for r in con.execute("""
            select taxi_path_id, airport_id, type, surface, width as width_ft, name,
                   start_lonx as start_lon, start_laty as start_lat, end_lonx as end_lon, end_laty as end_lat
            from taxi_path
            where airport_id=? and start_lonx is not null and start_laty is not null and end_lonx is not null and end_laty is not null
            order by taxi_path_id
        """, (airport_id,))]
        taxi = _merge_taxi_segments(raw_taxi)
        starts = [dict(r) for r in con.execute("""
            select start_id, airport_id, runway_end_id, runway_name, type, heading, lonx as lon, laty as lat, altitude as altitude_ft
            from start where airport_id=? and lonx is not null and laty is not null
        """, (airport_id,))]
        # v0.24.17 performance policy: the normal Live Map surface payload is
        # runway + taxiway only. Parking stands and apron polygons remain
        # available through dedicated backend logic such as nearest_parking(),
        # but they are not shipped to the browser surface layer because large
        # airports can contain thousands of stand/apron objects and labels.
        named_taxi = sum(1 for row in taxi if str(row.get("name") or "").strip())
        return {
            "ok": True, "source": "local", "airport": _airport_dict(ap),
            "runways": runways, "runway_ends": ends, "taxiways": taxi,
            "raw_taxi_segment_count": len(raw_taxi), "taxi_polyline_count": len(taxi),
            "feature_counts": {"runways": len(runways), "taxiways": len(taxi), "raw_taxi_segments": len(raw_taxi), "named_taxiways": named_taxi},
            "aprons": [], "parking": [], "starts": starts,
            "surface_render_policy": "complete_merged_runways_taxiways",
            "message": "Complete runway and merged taxiway surface loaded from local simulator nav data",
        }
    finally:
        con.close()


def _airport_surface_from_builtin(ident: str) -> dict[str, Any]:
    if not available():
        return status()
    con = _connect()
    try:
        ap = con.execute("select * from surface_airport where ident=?", (ident,)).fetchone()
        if not ap:
            return {"ok": False, "icao": ident, "message": "Airport not found in built-in aviation database"}
        airport_id = ap["airport_id"]
        runways = [dict(r) for r in con.execute("select * from surface_runway where airport_id=? order by name", (airport_id,))]
        ends = [dict(r) for r in con.execute("select * from surface_runway_end where airport_id=? order by runway_name,name", (airport_id,))]
        ends_by_runway: dict[str, list[str]] = {}
        for end in ends:
            ends_by_runway.setdefault(str(end.get("runway_name") or ""), []).append(str(end.get("name") or ""))
        for runway in runways:
            names = [name for name in ends_by_runway.get(str(runway.get("name") or ""), []) if name]
            fallback = [part.strip() for part in str(runway.get("name") or "").split("/") if part.strip()]
            runway["primary_name"] = names[0] if names else (fallback[0] if fallback else "")
            runway["secondary_name"] = names[1] if len(names) > 1 else (fallback[1] if len(fallback) > 1 else "")
        return {"ok": True, "source": "built-in", "airport": dict(ap), "runways": runways, "runway_ends": ends, "taxiways": [], "aprons": [], "parking": [], "starts": [], "message": "Runway surface only. Configure local surface data for taxiways, aprons and stands."}
    finally:
        con.close()


def airport_surface(icao: str) -> dict[str, Any]:
    ident = str(icao or "").upper().strip()[:4]
    if not ident:
        return {"ok": False, "icao": ident, "message": "No airport ICAO provided"}
    surf = local_surface_source()
    if surf.get("available") and surf.get("path"):
        try:
            path = Path(str(surf["path"]))
            mtime_bucket = int(path.stat().st_mtime // 60)
            data = _airport_surface_from_local(str(path), ident, mtime_bucket)
            if data.get("ok"):
                data["surface_status"] = {k: surf.get(k) for k in ("available", "source", "path", "message")}
                return data
        except Exception as exc:
            return {"ok": False, "icao": ident, "surface_status": surf, "message": f"Local surface data read failed: {type(exc).__name__}: {exc}"}
    data = _airport_surface_from_builtin(ident)
    data["surface_status"] = surf
    return data




def surface_diagnostics(icao: str) -> dict[str, Any]:
    ident = str(icao or "").upper().strip()[:4]
    started = time.perf_counter()
    data = airport_surface(ident) if ident else {"ok": False, "message": "No airport ICAO provided"}
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)
    return {
        "ok": bool(data.get("ok")),
        "icao": ident,
        "source": data.get("source"),
        "elapsed_ms": elapsed_ms,
        "feature_counts": {
            "runways": len(data.get("runways") or []),
            "runway_ends": len(data.get("runway_ends") or []),
            "taxiways": len(data.get("taxiways") or []),
            "aprons": len(data.get("aprons") or []),
            "parking": len(data.get("parking") or []),
        },
        "airport": data.get("airport"),
        "surface_status": data.get("surface_status"),
        "message": data.get("message"),
    }

def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1 = math.radians(lat1); p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def nearest_parking(icao: str, lat: float, lon: float, heading: float | None = None, max_m: float = 80.0) -> dict[str, Any]:
    """Detect the nearest parking/stand from local surface data.

    This is used only as a convenience/safety aid for arrival services. It never
    uses cached departure-gate state and it never forces a MARS/sub-position
    unless the detected option can be matched to the live destination menu.
    """
    ident = str(icao or "").upper().strip()[:4]
    if not ident:
        return {"ok": False, "message": "No airport ICAO provided"}
    surf = local_surface_source()
    if not surf.get("available") or not surf.get("path"):
        return {"ok": False, "icao": ident, "message": "Local surface data is not available"}
    path = str(surf.get("path") or "")
    try:
        con = _local_con(path)
        try:
            ap = con.execute("select airport_id, ident, name from airport where upper(ident)=?", (ident,)).fetchone()
            if not ap:
                return {"ok": False, "icao": ident, "message": "Airport not found in local surface data"}
            airport_id = ap["airport_id"]
            rows = [dict(r) for r in con.execute("""
                select parking_id, airport_id, type, name, number, suffix, airline_codes, radius as radius_ft,
                       heading, has_jetway, lonx as lon, laty as lat
                from parking where airport_id=? and lonx is not null and laty is not null
            """, (airport_id,)).fetchall()]
        finally:
            con.close()
    except Exception as exc:
        return {"ok": False, "icao": ident, "message": f"Local surface stand detection failed: {type(exc).__name__}: {exc}"}
    candidates: list[dict[str, Any]] = []
    for row in rows:
        plat = _num(row.get("lat")); plon = _num(row.get("lon"))
        if plat is None or plon is None:
            continue
        dist = _distance_m(float(lat), float(lon), plat, plon)
        if dist <= max_m:
            label = f"{row.get('name') or ''} {row.get('number') or ''}{row.get('suffix') or ''}".strip()
            raw_heading = _num(row.get("heading"))
            heading_delta = None
            if heading is not None and raw_heading is not None:
                heading_delta = abs(((float(heading) - raw_heading + 180.0) % 360.0) - 180.0)
            item = dict(row)
            item.update({"label": label or str(row.get("parking_id") or ""), "distance_m": round(dist, 1), "heading_delta_deg": round(heading_delta, 1) if heading_delta is not None else None})
            candidates.append(item)
    candidates.sort(key=lambda x: (float(x["distance_m"]) if x.get("distance_m") is not None else 9999.0, float(x["heading_delta_deg"]) if x.get("heading_delta_deg") is not None else 999.0))
    if not candidates:
        return {"ok": False, "icao": ident, "message": f"No parking stand detected within {int(max_m)} m"}
    best = candidates[0]
    best_dist = float(best["distance_m"]) if best.get("distance_m") is not None else 9999.0
    second_dist = float(candidates[1]["distance_m"]) if len(candidates) > 1 and candidates[1].get("distance_m") is not None else 9999.0
    ambiguous = len(candidates) > 1 and second_dist - best_dist < 12.0
    confidence = "high" if best_dist <= 35.0 and not ambiguous else ("medium" if best_dist <= 55.0 else "low")
    return {"ok": True, "icao": ident, "airport": {"ident": ap["ident"], "name": ap["name"]}, "stand": best, "candidates": candidates[:5], "confidence": confidence, "ambiguous": ambiguous, "surface_status": surf, "message": f"Detected {best.get('label') or 'stand'} at {best.get('distance_m')} m"}
