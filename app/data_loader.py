from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
# Support both locations because the first starter had a path mismatch in the instructions.
LOGO_DIRS = [
    (BASE_DIR / "assets" / "logos", "/assets/logos"),
    (BASE_DIR / "static" / "assets" / "logos", "/static/assets/logos"),
]


@dataclass(frozen=True)
class Airport:
    ident: str
    type: str
    name: str
    lat: float
    lon: float
    country: str


@dataclass(frozen=True)
class Airline:
    name: str
    iata: str
    icao: str
    callsign: str
    country: str
    active: str


def _safe_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def load_airports() -> dict[str, Airport]:
    airports: dict[str, Airport] = {}
    path = DATA_DIR / "airports.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ident = (row.get("ident") or "").strip().upper()
            lat = _safe_float(row.get("latitude_deg", ""))
            lon = _safe_float(row.get("longitude_deg", ""))
            if not ident or lat is None or lon is None:
                continue
            airports[ident] = Airport(
                ident=ident,
                type=(row.get("type") or "").strip(),
                name=(row.get("name") or ident).strip(),
                lat=lat,
                lon=lon,
                country=(row.get("iso_country") or "").strip(),
            )
    return airports


@lru_cache(maxsize=1)
def load_airlines() -> dict[str, Airline]:
    airlines: dict[str, Airline] = {}
    path = DATA_DIR / "airlines.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            icao = (row.get("ICAO") or "").strip().upper()
            if not re.fullmatch(r"[A-Z0-9]{2,4}", icao):
                continue
            airlines[icao] = Airline(
                name=(row.get("Name") or icao).strip(),
                iata=(row.get("IATA") or "").strip(),
                icao=icao,
                callsign=(row.get("Callsign") or "").strip(),
                country=(row.get("Country") or "").strip(),
                active=(row.get("Active") or "").strip(),
            )
    return airlines


@lru_cache(maxsize=1)
def logo_index() -> dict[str, str]:
    """Return ICAO code -> public URL for logo.

    We index both app/assets/logos and app/static/assets/logos. This fixes the
    common issue where logos were copied into one folder while the app looked in
    the other.
    """
    preferred_order = {".png": 0, ".webp": 1, ".svg": 2, ".jpg": 3, ".jpeg": 4}
    found: dict[str, tuple[int, str]] = {}
    for folder, public_prefix in LOGO_DIRS:
        if not folder.exists():
            continue
        for p in folder.rglob("*"):
            suffix = p.suffix.lower()
            if suffix not in preferred_order:
                continue
            code = p.stem.upper().strip()
            if not re.fullmatch(r"[A-Z0-9]{2,4}", code):
                continue
            rank = preferred_order[suffix]
            # If duplicate exists, prefer app/assets first and PNG over other extensions.
            url = f"{public_prefix}/{p.name}"
            if code not in found or rank < found[code][0]:
                found[code] = (rank, url)
    return {code: url for code, (_, url) in found.items()}


def logo_status() -> dict:
    idx = logo_index()
    dirs = []
    for folder, public_prefix in LOGO_DIRS:
        count = 0
        if folder.exists():
            count = sum(1 for p in folder.rglob("*") if p.suffix.lower() in {".png", ".webp", ".svg", ".jpg", ".jpeg"})
        dirs.append({"folder": str(folder), "public_prefix": public_prefix, "image_count": count})
    return {"indexed_icao_logos": len(idx), "directories": dirs, "sample": sorted(idx.items())[:20]}


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_nm = 3440.065
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    return 2 * r_nm * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def nearest_airport(lat: float, lon: float, airports: Iterable[Airport] | None = None) -> tuple[Airport, float] | None:
    candidates = list(airports or load_airports().values())
    best: tuple[Airport, float] | None = None
    for airport in candidates:
        if airport.type == "closed":
            continue
        dist = haversine_nm(lat, lon, airport.lat, airport.lon)
        if best is None or dist < best[1]:
            best = (airport, dist)
    return best


def nearest_airports(lat: float, lon: float, limit: int = 10) -> list[tuple[Airport, float]]:
    rows: list[tuple[Airport, float]] = []
    for airport in load_airports().values():
        if airport.type == "closed":
            continue
        rows.append((airport, haversine_nm(lat, lon, airport.lat, airport.lon)))
    rows.sort(key=lambda item: item[1])
    return rows[:limit]


def search_airports(query: str, limit: int = 40) -> list[dict]:
    q = query.strip().upper()
    if not q:
        return []
    results: list[tuple[int, Airport]] = []
    for airport in load_airports().values():
        hay = f"{airport.ident} {airport.name} {airport.country}".upper()
        if airport.ident == q:
            score = 0
        elif airport.ident.startswith(q):
            score = 1
        elif q in hay:
            score = 2
        else:
            continue
        # Prioritize larger airports slightly when searching by city/name.
        type_bonus = 0 if airport.type == "large_airport" else 1 if airport.type == "medium_airport" else 2
        results.append((score * 10 + type_bonus, airport))
    results.sort(key=lambda item: (item[0], item[1].ident))
    return [airport_to_dict(a) for _, a in results[:limit]]


def airport_to_dict(airport: Airport) -> dict:
    return {
        "ident": airport.ident,
        "type": airport.type,
        "name": airport.name,
        "lat": airport.lat,
        "lon": airport.lon,
        "country": airport.country,
    }


def airport_option(airport: Airport, *, source: str, distance_nm: float | None = None, traffic_count: int | None = None) -> dict:
    d = airport_to_dict(airport)
    d["source"] = source
    d["distance_nm"] = round(distance_nm, 1) if distance_nm is not None else None
    d["traffic_count"] = traffic_count
    if source == "current":
        d["label"] = f"Current location: {airport.ident} - {airport.name}"
    elif distance_nm is not None:
        d["label"] = f"{airport.ident} - {airport.name} • {round(distance_nm, 1)} NM"
    elif traffic_count is not None:
        d["label"] = f"{airport.ident} - {airport.name} • {traffic_count} VATSIM flights"
    else:
        d["label"] = f"{airport.ident} - {airport.name}"
    return d


def callsign_prefix(callsign: str) -> str:
    m = re.match(r"^([A-Z]{2,4})", (callsign or "").upper())
    return m.group(1) if m else ""


def match_airline(callsign: str) -> dict:
    airlines = load_airlines()
    logos = logo_index()
    prefix = callsign_prefix(callsign)
    # Most VATSIM airline callsigns use 3-letter ICAO. Check longest to shortest.
    for n in (4, 3, 2):
        code = prefix[:n]
        if not code:
            continue
        airline = airlines.get(code)
        logo_url = logos.get(code)
        if airline or logo_url:
            return {
                "code": code,
                "name": airline.name if airline else code,
                "callsign": airline.callsign if airline else "",
                "country": airline.country if airline else "",
                "logo_url": logo_url,
            }
    return {"code": prefix or "GEN", "name": "General Aviation / Unknown", "callsign": "", "country": "", "logo_url": None}

@dataclass(frozen=True)
class Stand:
    icao: str
    name: str
    lat: float
    lon: float
    type: str = "stand"
    source: str = "unknown"


STAND_SOURCE_FILES = [
    # Highest priority. Reserved for future live/user-scenery facility extraction.
    ("live", DATA_DIR / "stands_simconnect.csv"),
    ("sim", DATA_DIR / "stands_msfs.csv"),
    # Bundled extracted stand database. Keep the public filename/provider generic.
    ("bundled", DATA_DIR / "stands.csv"),
]


def _read_stand_file(path: Path, source: str) -> list[Stand]:
    if not path.exists():
        return []
    rows: list[Stand] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            icao = (row.get("icao") or row.get("ICAO") or "").strip().upper()
            name = (row.get("stand") or row.get("gate") or row.get("name") or "").strip().upper()
            lat = _safe_float(row.get("lat") or row.get("latitude") or "")
            lon = _safe_float(row.get("lon") or row.get("longitude") or "")
            if not icao or not name or lat is None or lon is None:
                continue
            rows.append(Stand(icao=icao, name=name, lat=lat, lon=lon, type=(row.get("type") or "stand").strip(), source=source))
    return rows


@lru_cache(maxsize=1)
def load_stands_by_source() -> dict[str, list[Stand]]:
    """Optional stand/gate databases, loaded by source priority.

    Priority order is live/user-scenery facility extraction first, then the
    bundled extracted stand database. Public package names stay provider-neutral.
    """
    out: dict[str, list[Stand]] = {}
    for source, path in STAND_SOURCE_FILES:
        rows = _read_stand_file(path, source)
        if rows:
            out.setdefault(source, []).extend(rows)
    return out


@lru_cache(maxsize=1)
def load_stands() -> list[Stand]:
    rows: list[Stand] = []
    for source in ("live", "sim", "bundled"):
        rows.extend(load_stands_by_source().get(source, []))
    return rows


def nearest_stands(icao: str, lat: float, lon: float, max_distance_nm: float = 0.08, limit: int = 8, exclude: set[str] | None = None) -> list[tuple[Stand, float]]:
    """Return nearest stand candidates, honoring source priority.

    Source priority stays live/user-scenery files first, bundled database
    second. The exclude set is used by the board renderer to avoid assigning
    the same stand to multiple online aircraft when positions are approximate.
    """
    icao = icao.upper()
    exclude = {x.upper() for x in (exclude or set())}
    for source in ("live", "sim", "bundled"):
        rows: list[tuple[Stand, float]] = []
        for stand in load_stands_by_source().get(source, []):
            if stand.icao != icao or stand.name.upper() in exclude:
                continue
            dist = haversine_nm(lat, lon, stand.lat, stand.lon)
            if dist <= max_distance_nm:
                rows.append((stand, dist))
        if rows:
            rows.sort(key=lambda item: item[1])
            return rows[:limit]
    return []


def nearest_stand(icao: str, lat: float, lon: float, max_distance_nm: float = 0.08) -> tuple[Stand, float] | None:
    hits = nearest_stands(icao, lat, lon, max_distance_nm=max_distance_nm, limit=1)
    return hits[0] if hits else None


def stand_count() -> int:
    return len(load_stands())


def stand_sources_status() -> dict:
    by_source = load_stands_by_source()
    files = []
    for source, path in STAND_SOURCE_FILES:
        files.append({"source": source, "file": str(path), "exists": path.exists()})
    return {
        "total": stand_count(),
        "sources": {source: len(rows) for source, rows in by_source.items()},
        "priority": ["live", "sim", "bundled"],
        "files": files,
    }


def stands_available() -> bool:
    return stand_count() > 0
