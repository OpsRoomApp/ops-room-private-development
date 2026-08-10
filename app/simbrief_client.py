from __future__ import annotations

import hashlib
import html as html_lib
import json
import logging
import os
import re
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


def _app_version() -> str:
    """v0.25.67: user-agent version comes from version.json, never a stale literal."""
    try:
        raw = (Path(__file__).resolve().parent.parent / "version.json").read_text(encoding="utf-8")
        return str(json.loads(raw).get("version") or "0.25.75")
    except Exception:  # pragma: no cover - defensive version read
        return "0.25.75"


_USER_AGENT = f"OPS ROOM/{_app_version()} (+flight-simulation utility)"
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from .settings_store import app_data_dir

SIMBRIEF_URL = "https://www.simbrief.com/api/xml.fetcher.php"
CACHE_SECONDS = 300
CACHE_FILE = "simbrief_latest.json"
RAW_CACHE_FILE = "simbrief_latest_raw.json"

_lock = threading.Lock()
_disk_lock = threading.Lock()
_resource_lock = threading.Lock()
_memory: dict[str, Any] = {
    "user_ref": "",
    "fetched_monotonic": 0.0,
    "plan": None,
    "last_error": None,
    "last_attempt_utc": None,
}
_LOGGER = logging.getLogger("opsroom.simbrief")


def _ofp_log(message: str, *args: Any) -> None:
    try:
        _LOGGER.info(message, *args)
    except Exception:
        pass


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return default


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return default
    return str(value).strip()


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(round(number)) if number is not None else None


def _timestamp(value: Any) -> int | None:
    number = _number(value)
    if number is not None:
        number = int(number)
        if number > 10_000_000_000:
            number //= 1000
        if number > 1_000_000_000:
            return number
    text = _text(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            parsed = datetime.strptime(text, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp())
        except ValueError:
            continue
    return None


def _utc_iso(timestamp: int | None) -> str | None:
    if not timestamp:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, OSError, OverflowError):
        return None


def _airport(section: Any) -> dict[str, Any]:
    data = _as_dict(section)
    atis = [dict(item) for item in _as_list(data.get("atis")) if isinstance(item, dict)]
    return {
        "icao": _text(_first(data.get("icao_code"), data.get("icao"))).upper(),
        "iata": _text(data.get("iata_code")).upper(),
        "name": _text(data.get("name")),
        "runway": _text(_first(data.get("plan_rwy"), data.get("runway"))).upper(),
        "metar": _text(data.get("metar")),
        "taf": _text(data.get("taf")),
        "metar_time": _text(data.get("metar_time")),
        "taf_time": _text(data.get("taf_time")),
        "atis": atis,
        "latitude": _number(_first(data.get("pos_lat"), data.get("latitude"))),
        "longitude": _number(_first(data.get("pos_long"), data.get("longitude"))),
    }

def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _tlr_runway(row: Any) -> dict[str, Any] | None:
    data = _as_dict(row)
    if not data:
        return None
    def pick(*keys: str) -> Any:
        return _first(*(data.get(k) for k in keys))
    item = {
        "runway": _text(pick("ident", "runway", "rwy", "name")).upper(),
        "flap_setting": _text(pick("flap_setting", "flaps", "flap")),
        "thrust_setting": _text(pick("thrust_setting", "thrust", "engine_mode", "derate")),
        "bleed_setting": _text(pick("bleed_setting", "bleeds")),
        "anti_ice_setting": _text(pick("anti_ice_setting", "anti_ice")),
        "flex_temperature": _text(pick("flex_temperature", "assumed_temperature", "assumed_temp", "flex_temp")),
        "max_temperature": _text(pick("max_temperature", "max_temp")),
        "max_weight": _number(pick("max_weight", "weight_limit", "limit_weight")),
        "limit_code": _text(pick("limit_code", "limit")),
        "limit_obstacle": _text(pick("limit_obstacle", "obstacle")),
        "distance_decide": _text(pick("distance_decide", "dist_decide")),
        "distance_reject": _text(pick("distance_reject", "dist_reject")),
        "distance_continue": _text(pick("distance_continue", "dist_continue")),
        "distance_margin": _text(pick("distance_margin", "margin")),
        "speeds_v1": _text(pick("speeds_v1", "v1")),
        "speeds_vr": _text(pick("speeds_vr", "vr")),
        "speeds_v2": _text(pick("speeds_v2", "v2")),
        "speeds_vref": _text(pick("speeds_vref", "vref")),
        "speeds_vapp": _text(pick("speeds_vapp", "vapp")),
    }
    return {k: v for k, v in item.items() if v not in (None, "")}


def _tlr_section(section: Any) -> dict[str, Any]:
    data = _as_dict(section)
    if not data:
        return {"available": False, "runways": []}
    raw_runways = data.get("runway") or data.get("runways") or data.get("rwy")
    runways = [x for x in (_tlr_runway(row) for row in _as_list(raw_runways)) if x]
    # Some layouts expose a single runway directly under the section.
    if not runways:
        direct = _tlr_runway(data)
        if direct:
            runways = [direct]
    return {"available": bool(runways), "runways": runways}


def _tlr(raw: dict[str, Any]) -> dict[str, Any]:
    data = _as_dict(raw.get("tlr") or raw.get("runway_analysis"))
    if not data:
        return {"available": False, "takeoff": {"available": False, "runways": []}, "landing": {"available": False, "runways": []}}
    takeoff = _tlr_section(data.get("takeoff") or data.get("departure"))
    landing = _tlr_section(data.get("landing") or data.get("arrival"))
    return {"available": bool(takeoff["available"] or landing["available"]), "takeoff": takeoff, "landing": landing}



def _deep_find_pdf_url(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
        if ".pdf" in text.lower() and "simbrief.com" in text.lower():
            import re
            m = re.search(r"https?://[^\s\"'<>]+\.pdf(?:\?[^\s\"'<>]*)?", text, flags=re.I)
            if m:
                return m.group(0)
            if text.lower().startswith(("http://", "https://")):
                return text
        return ""
    if isinstance(value, dict):
        # Prefer obvious document/file fields first.
        for key in ("pdf", "pdf_link", "pdf_url", "pdf_file", "ofp_pdf", "url"):
            found = _deep_find_pdf_url(value.get(key))
            if found:
                return found
        for item in value.values():
            found = _deep_find_pdf_url(item)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _deep_find_pdf_url(item)
            if found:
                return found
    return ""


def _deep_find_html_ofp(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("plan_html", "ofp_html", "html", "navlog_html"):
            item = value.get(key)
            if isinstance(item, str) and len(item.strip()) > 200:
                return item
        for item in value.values():
            found = _deep_find_html_ofp(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _deep_find_html_ofp(item)
            if found:
                return found
    return ""


def _deep_find_text_ofp(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("plan_text", "ofp_text", "text", "navlog_text"):
            item = value.get(key)
            if isinstance(item, str) and len(item.strip()) > 200:
                return item
        for item in value.values():
            found = _deep_find_text_ofp(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _deep_find_text_ofp(item)
            if found:
                return found
    return ""

def _dtg_iso(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    formats = ((r"\d{12}", "%Y%m%d%H%M"), (r"\d{10}", "%y%m%d%H%M"))
    for pattern, fmt in formats:
        if not re.fullmatch(pattern, text):
            continue
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            continue
    timestamp = _timestamp(text)
    return _utc_iso(timestamp)


def _raw_notam_validity(raw_text: str) -> dict[str, Any]:
    """Extract ICAO B)/C) validity when SimBrief omits normalized fields."""
    text = str(raw_text or "")
    effective_match = re.search(r"\bB\)\s*(\d{10}|\d{12})\b", text, flags=re.I)
    expiry_match = re.search(r"\bC\)\s*(PERM|\d{10}|\d{12})(EST)?\b", text, flags=re.I)
    permanent = bool(expiry_match and expiry_match.group(1).upper() == "PERM")
    return {
        "effective_utc": _dtg_iso(effective_match.group(1)) if effective_match else None,
        "expires_utc": None if permanent or not expiry_match else _dtg_iso(expiry_match.group(1)),
        "expires_estimated": bool(expiry_match and expiry_match.group(2)),
        "permanent": permanent,
    }


def _html_to_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(?:p|div|h[1-6]|tr|li)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_lib.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n"))


def _joined_url(directory: Any, link: Any) -> str:
    base = _text(directory)
    item = _text(link)
    if not item:
        return ""
    if item.lower().startswith(("http://", "https://")):
        return item
    return urljoin(base.rstrip("/") + "/", item)


def _extract_notam_body(raw_text: str) -> str:
    text = str(raw_text or "").strip()
    if not text:
        return ""
    match = re.search(r"(?:^|\n)\s*E\)\s*(.*?)(?=(?:\n\s*[FG]\)\s)|\Z)", text, flags=re.I | re.S)
    body = match.group(1).strip() if match else text
    return re.sub(r"\n[ \t]+", "\n", body).strip()


def _notam_category(row: dict[str, Any], body: str, scope_key: str) -> str:
    explicit = _text(row.get("notam_qcode_category"))
    if explicit:
        return explicit
    upper = body.upper()
    qcode = _text(row.get("notam_qcode")).upper()
    if row.get("notam_is_obstacle") or qcode.startswith("QOB") or any(word in upper for word in ("CRANE", "OBST", "WIND TURBINE")):
        return "Obstacles"
    if any(word in upper for word in ("RWY", "RUNWAY")):
        return "Runways"
    if any(word in upper for word in ("ILS", "RNP", "RNAV", "APPROACH", "MINIMA", "PROCEDURE")):
        return "Approach procedures"
    if any(word in upper for word in ("TWY", "TAXIWAY", "APRON", "PARKING", "PRKG", "STAND")):
        return "Airport surface"
    if any(word in upper for word in ("VOR", "NDB", "DME", "NAVAID", "NAVIGATION AID")):
        return "Navigation aids"
    if scope_key == "enroute" or any(word in upper for word in ("DANGER AREA", "RESTRICTED AREA", "UAS OPERATION", "MILITARY", "AIRSPACE")):
        return "Airspace"
    return "Airport" if scope_key in {"departure", "destination", "alternate"} else "General"


def _route_firs(raw: dict[str, Any]) -> list[str]:
    result: list[str] = []
    navlog = raw.get("navlog")
    if isinstance(navlog, dict):
        navlog = navlog.get("fix")
    for fix in _as_list(navlog):
        if not isinstance(fix, dict):
            continue
        for value in (fix.get("fir"),):
            code = _text(value).upper()
            if len(code) == 4 and code not in result:
                result.append(code)
        for crossing in _as_list(fix.get("fir_crossing")):
            code = _text(_as_dict(crossing).get("fir_icao")).upper()
            if len(code) == 4 and code not in result:
                result.append(code)
    return result


def _normalise_notams(raw: dict[str, Any], origin_icao: str, destination_icao: str, alternate_icaos: list[str]) -> list[dict[str, Any]]:
    enrichment: dict[tuple[str, str], dict[str, Any]] = {}
    # SimBrief's rendered LIDO OFP is the authoritative pre-flight bulletin
    # sequence. Use its NOTAM ID order when available, while retaining every
    # structured record that is not present in the rendered bulletin.
    bulletin_order: dict[str, int] = {}
    bulletin_text = _html_to_text(_deep_find_html_ofp(raw))
    for match in re.finditer(r"\b[A-Z]{1,2}\d{3,4}/\d{2}\b", bulletin_text, flags=re.I):
        ident = match.group(0).upper()
        if ident not in bulletin_order:
            bulletin_order[ident] = len(bulletin_order)
    airport_sections: list[tuple[str, Any]] = [
        ("departure", raw.get("origin")),
        ("destination", raw.get("destination")),
    ]
    airport_sections.extend(("alternate", item) for item in _as_list(raw.get("alternate")))
    fallback_rows: list[dict[str, Any]] = []
    for scope_key, section in airport_sections:
        data = _as_dict(section)
        location = _text(_first(data.get("icao_code"), data.get("icao"))).upper()
        for airport_order, item in enumerate(_as_list(data.get("notam"))):
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row["_scope_key"] = scope_key
            row["_location"] = location
            row["_source_order"] = airport_order
            key = (_text(row.get("notam_id")).upper(), location)
            enrichment[key] = row
            fallback_rows.append(row)

    rows = [dict(item) for item in _as_list(raw.get("notams")) if isinstance(item, dict)] or fallback_rows
    route_firs = set(_route_firs(raw))
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for source_order, raw_row in enumerate(rows):
        ident = _text(raw_row.get("notam_id")).upper()
        location = _text(_first(raw_row.get("location_icao"), raw_row.get("icao_id"), raw_row.get("cns_location_id"), raw_row.get("location_id"), raw_row.get("_location"))).upper()
        rich = enrichment.get((ident, location), {})
        merged = {**raw_row, **rich}
        if location == origin_icao:
            scope_key, scope = "departure", f"Departure · {location}"
        elif location == destination_icao:
            scope_key, scope = "destination", f"Destination · {location}"
        elif location in alternate_icaos:
            scope_key, scope = "alternate", f"Alternate · {location}"
        else:
            scope_key = "enroute"
            scope = f"En route / FIR · {location}" if location else "En route / FIR"
        raw_text = _text(_first(merged.get("notam_raw"), merged.get("notam_text")))
        body = _text(rich.get("notam_text")) or _extract_notam_body(raw_text) or _text(merged.get("notam_report"))
        raw_validity = _raw_notam_validity(raw_text)
        effective = (
            _dtg_iso(merged.get("date_effective"))
            or _dtg_iso(merged.get("notam_effective_dtg"))
            or raw_validity.get("effective_utc")
        )
        expiry_value = merged.get("date_expire")
        permanent = bool(expiry_value is False or raw_validity.get("permanent"))
        expiry = None if permanent else (
            _dtg_iso(expiry_value)
            or _dtg_iso(merged.get("notam_expire_dtg"))
            or raw_validity.get("expires_utc")
        )
        expires_estimated = bool(
            merged.get("date_expire_is_estimated")
            or raw_validity.get("expires_estimated")
            or ("ESTIMATED" in _text(merged.get("notam_report")).upper() and bool(expiry))
        )
        key = (ident, location, effective or "")
        if not ident or not body or key in seen:
            continue
        seen.add(key)
        resolved_order = int(rich.get("_source_order", source_order))
        sort_order = bulletin_order.get(ident, 100000 + resolved_order)
        result.append({
            "id": ident,
            "scope_key": scope_key,
            "scope": scope,
            "location": location,
            "location_name": _text(_first(merged.get("location_name"), merged.get("icao_name"))),
            "category": _notam_category(merged, body, scope_key),
            "status": _text(merged.get("notam_qcode_status")),
            "qcode": _text(merged.get("notam_qcode")).upper(),
            "qcode_subject": _text(merged.get("notam_qcode_subject")),
            "nrc": _text(merged.get("notam_nrc")).upper(),
            "effective_utc": effective,
            "expires_utc": None if permanent else (expiry or None),
            "expires_estimated": expires_estimated,
            "permanent": bool(permanent),
            "schedule": _text(_first(merged.get("notam_schedule"), merged.get("schedule"))),
            "text": body[:12000],
            "raw": raw_text[:16000],
            "source": "SimBrief",
            "source_order": sort_order,
        })
    order = {"departure": 0, "destination": 1, "alternate": 2, "enroute": 3}
    # Preserve SimBrief/LIDO bulletin order inside each operational scope.
    # Alphabetic or expiry sorting can separate related notices and is not the
    # normal default for a pre-flight information bulletin.
    result.sort(key=lambda row: (order.get(str(row.get("scope_key")), 9), int(row.get("source_order") or 0)))
    return result


def _normalise_sigmet_rows(rows: Any) -> list[dict[str, Any]]:
    if isinstance(rows, dict):
        candidates = _as_list(_first(rows.get("sigmet"), rows.get("items"), rows.get("item"), rows))
    elif isinstance(rows, str):
        candidates = [rows]
    else:
        candidates = _as_list(rows)
    result: list[dict[str, Any]] = []
    for index, item in enumerate(candidates, start=1):
        if isinstance(item, str):
            text = item.strip()
            data: dict[str, Any] = {}
        elif isinstance(item, dict):
            data = item
            text = _text(_first(data.get("raw_text"), data.get("rawSigmet"), data.get("sigmet_text"), data.get("text"), data.get("raw"), data.get("message")))
            if not text:
                text = " · ".join(_text(data.get(key)) for key in ("hazard", "phenomenon", "severity", "fir", "valid_from", "valid_to") if _text(data.get(key)))
        else:
            continue
        if not text:
            continue
        result.append({
            "id": _text(_first(data.get("id"), data.get("sigmet_id"), data.get("name")), f"SIGMET {index}"),
            "scope": _text(_first(data.get("fir"), data.get("location"), data.get("icao")), "Route"),
            "text": text[:12000],
            "effective_utc": _text(_first(data.get("valid_from"), data.get("date_effective"), data.get("start"))),
            "expires_utc": _text(_first(data.get("valid_to"), data.get("date_expire"), data.get("end"))),
            "source": "SimBrief",
        })
    return result


def _hazard_sections(plan_html: str, structured_sigmets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    text = _html_to_text(plan_html)
    start = text.upper().find("[ AIRPORT WX LIST ]")
    if start >= 0:
        text = text[start:]
    labels = [
        ("airmet", "AIRMET", r"AIRMETS:"),
        ("sigmet", "SIGMET", r"SIGMETS:"),
        ("tropical_cyclone", "Tropical cyclone SIGMET", r"TROPICAL CYCLONE SIGMETS:"),
        ("volcanic_ash", "Volcanic ash SIGMET", r"VOLCANIC ASH SIGMETS:"),
    ]
    sections: list[dict[str, Any]] = []
    for index, (key, label, pattern) in enumerate(labels):
        next_patterns = [entry[2] for entry in labels[index + 1 :]] + [r"DEPARTURE:"]
        stop = "|".join(next_patterns)
        match = re.search(pattern + r"\s*(.*?)(?=" + stop + r"|\Z)", text, flags=re.I | re.S)
        body = match.group(1).strip() if match else ""
        rows: list[dict[str, Any]] = []
        if key == "sigmet" and structured_sigmets:
            rows = structured_sigmets
        elif body and "NO WX DATA AVAILABLE" not in body.upper():
            chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", body) if chunk.strip()]
            for item_index, chunk in enumerate(chunks or [body], start=1):
                rows.append({"id": f"{label} {item_index}", "scope": "Route briefing", "text": chunk[:12000], "source": "SimBrief OFP"})
        state = "available" if rows else ("none" if match else "not_included")
        sections.append({"key": key, "label": label, "state": state, "items": rows})
    return sections


def _normalise_images(raw: dict[str, Any]) -> list[dict[str, Any]]:
    images = _as_dict(raw.get("images"))
    directory = images.get("directory")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(_as_list(images.get("map")), start=1):
        if not isinstance(item, dict):
            continue
        name = _text(_first(item.get("name"), item.get("title")), f"Chart {index}")
        remote_url = _joined_url(directory, _first(item.get("link"), item.get("url")))
        if not remote_url:
            continue
        lower = name.lower()
        if lower.startswith("sigwx") or "sigwx" in lower:
            category = "sigwx"
        elif lower.startswith("route"):
            category = "route"
        elif lower.startswith("uad") or "wind" in lower:
            category = "winds"
        elif "vertical" in lower or "profile" in lower:
            category = "profile"
        else:
            category = "other"
        suffix = Path(urlparse(remote_url).path).suffix.lower()
        if suffix not in {".gif", ".png", ".jpg", ".jpeg", ".webp"}:
            suffix = ".img"
        digest = hashlib.sha1(remote_url.encode("utf-8", "ignore")).hexdigest()[:16]
        filename = f"simbrief_img_{digest}{suffix}"
        result.append({
            "name": name,
            "category": category,
            "index": index,
            "remote_url": remote_url,
            "cache_filename": filename,
            "url": f"/api/simbrief/ofp-image/{filename}",
            "download_url": f"/api/simbrief/ofp-image/{filename}?download=true",
        })
    return result


def _normalise_database_updates(value: Any) -> dict[str, str]:
    """Return canonical UTC timestamps for SimBrief database source ages."""
    aliases = {
        "notam": "notams",
        "notams": "notams",
        "sigmet": "sigmet",
        "sigmets": "sigmet",
        "sigwx": "sigwx",
        "winds": "winds",
        "wind": "winds",
        "metar": "metar_taf",
        "taf": "metar_taf",
        "metar_taf": "metar_taf",
        "tracks": "tracks",
    }
    result: dict[str, str] = {}
    for raw_key, raw_value in _as_dict(value).items():
        key = aliases.get(str(raw_key or "").strip().lower(), str(raw_key or "").strip().lower())
        stamp = _dtg_iso(raw_value)
        if key and stamp:
            result[key] = stamp
    return result


def _normalize(raw: dict[str, Any], user_ref: str) -> dict[str, Any]:
    general = _as_dict(raw.get("general"))
    origin_raw = _as_dict(raw.get("origin"))
    destination_raw = _as_dict(raw.get("destination"))
    alternate_raw = [item for item in _as_list(raw.get("alternate")) if isinstance(item, dict)]
    origin = _airport(origin_raw)
    destination = _airport(destination_raw)
    alternates = [_airport(item) for item in alternate_raw]
    alternate = alternates[0] if alternates else _airport({})
    aircraft = _as_dict(raw.get("aircraft"))
    fuel = _as_dict(raw.get("fuel"))
    weights = _as_dict(raw.get("weights"))
    params = _as_dict(raw.get("params"))
    times = _as_dict(raw.get("times"))
    file_root = _as_dict(raw.get("files"))
    links = _as_dict(raw.get("links"))

    navlog_raw = raw.get("navlog")
    if isinstance(navlog_raw, dict):
        navlog_raw = navlog_raw.get("fix")
    navlog = []
    for fix in _as_list(navlog_raw):
        if not isinstance(fix, dict):
            continue
        lat = _number(_first(fix.get("pos_lat"), fix.get("latitude"), fix.get("lat")))
        lon = _number(_first(fix.get("pos_long"), fix.get("longitude"), fix.get("lon")))
        if lat is None or lon is None:
            continue
        navlog.append({
            "ident": _text(_first(fix.get("ident"), fix.get("name"))).upper(),
            "name": _text(fix.get("name")),
            "type": _text(_first(fix.get("type"), fix.get("type_code"))).upper(),
            "latitude": lat,
            "longitude": lon,
            "altitude_ft": _integer(_first(fix.get("altitude_feet"), fix.get("altitude"))),
            "fir": _text(fix.get("fir")).upper(),
            "fir_crossing": [dict(item) for item in _as_list(fix.get("fir_crossing")) if isinstance(item, dict)],
            "wind_data": [dict(item) for item in _as_list(fix.get("wind_data")) if isinstance(item, dict)],
        })

    airline = _text(_first(general.get("icao_airline"), general.get("airline"))).upper()
    flight_number = _text(_first(general.get("flight_number"), general.get("fltnum"))).upper()
    callsign = _text(_first(_as_dict(raw.get("atc")).get("callsign"), general.get("callsign"))).upper()
    if not callsign:
        callsign = f"{airline}{flight_number}".strip()

    generated_ts = _timestamp(_first(params.get("time_generated"), params.get("time_generated_utc"), general.get("time_generated"), raw.get("time_generated")))
    request_id = _text(params.get("request_id"))
    sequence_id = _text(params.get("sequence_id"))
    plan_id = _text(_first(request_id, sequence_id, params.get("static_id"), general.get("static_id"), general.get("plan_id")))
    route = _text(_first(general.get("route"), general.get("route_ifps")))
    cruise_altitude = _integer(_first(general.get("initial_altitude"), general.get("cruise_altitude")))

    scheduled_out = _timestamp(_first(times.get("sched_out"), times.get("est_out"), general.get("sched_out")))
    scheduled_off = _timestamp(_first(times.get("sched_off"), times.get("est_off"), general.get("sched_off")))
    scheduled_on = _timestamp(_first(times.get("sched_on"), times.get("est_on"), general.get("sched_on")))
    scheduled_in = _timestamp(_first(times.get("sched_in"), times.get("est_in"), general.get("sched_in")))

    pdf_entry = _as_dict(file_root.get("pdf"))
    pdf_url = _joined_url(file_root.get("directory"), _first(pdf_entry.get("link"), pdf_entry.get("url")))
    if not pdf_url:
        fms = _as_dict(raw.get("fms_downloads"))
        pdf_url = _joined_url(fms.get("directory"), _as_dict(fms.get("pdf")).get("link"))
    if not pdf_url:
        pdf_url = _text(_first(file_root.get("pdf"), file_root.get("pdf_link"), file_root.get("pdf_url"), links.get("pdf"), raw.get("pdf"), raw.get("ofp_pdf"), _deep_find_pdf_url(raw)))

    plan_html = _deep_find_html_ofp(raw)
    plan_text = _deep_find_text_ofp(raw)
    notams = _normalise_notams(raw, origin["icao"], destination["icao"], [item["icao"] for item in alternates if item.get("icao")])
    sigmets = _normalise_sigmet_rows(raw.get("sigmets"))
    hazard_sections = _hazard_sections(plan_html, sigmets)
    charts = _normalise_images(raw)
    database_updates = _normalise_database_updates(raw.get("database_updates"))

    result = {
        "ok": True,
        "source": "simbrief",
        "user_ref": user_ref,
        "plan_id": plan_id,
        "request_id": request_id,
        "sequence_id": sequence_id,
        "generated_utc": _utc_iso(generated_ts),
        "generated_timestamp": generated_ts,
        "callsign": callsign,
        "airline": airline,
        "flight_number": flight_number,
        "origin": origin,
        "destination": destination,
        "alternate": alternate,
        "alternates": alternates,
        "aircraft": {
            "icao": _text(_first(aircraft.get("icaocode"), aircraft.get("icao_code"), general.get("icao_aircraft"))).upper(),
            "name": _text(aircraft.get("name")),
            "registration": _text(_first(aircraft.get("reg"), aircraft.get("registration"))).upper(),
            "fin": _text(aircraft.get("fin")).upper(),
            "selcal": _text(aircraft.get("selcal")).upper(),
        },
        "route": route,
        "route_ifps": _text(general.get("route_ifps")),
        "navlog": navlog,
        "cruise_altitude_ft": cruise_altitude,
        "cost_index": _text(_first(general.get("costindex"), general.get("cost_index"))),
        "distance_nm": _integer(_first(general.get("air_distance"), general.get("gc_distance"), general.get("distance"))),
        "ete_seconds": _integer(_first(general.get("ete"), times.get("est_time_enroute"), times.get("ete"))),
        "block_time_seconds": _integer(_first(general.get("block_time"), times.get("sched_block"), times.get("block_time"))),
        "times": {
            "scheduled_out": _utc_iso(scheduled_out),
            "scheduled_off": _utc_iso(scheduled_off),
            "scheduled_on": _utc_iso(scheduled_on),
            "scheduled_in": _utc_iso(scheduled_in),
        },
        "fuel": {
            "units": _text(_first(params.get("units"), general.get("units"), fuel.get("units"))).upper(),
            "ramp": _integer(_first(fuel.get("plan_ramp"), fuel.get("ramp"))),
            "takeoff": _integer(_first(fuel.get("plan_takeoff"), fuel.get("takeoff"))),
            "trip": _integer(_first(fuel.get("enroute_burn"), fuel.get("trip"), fuel.get("trip_burn"))),
            "landing": _integer(_first(fuel.get("plan_landing"), fuel.get("landing"))),
            "reserve": _integer(_first(fuel.get("reserve"), fuel.get("reserve_fuel"))),
            "alternate": _integer(_first(fuel.get("alternate_burn"), fuel.get("alternate"))),
            "extra": _integer(fuel.get("extra")),
        },
        "weights": {
            "units": _text(_first(params.get("units"), weights.get("units"))).upper(),
            "passengers": _integer(_first(weights.get("pax_count"), weights.get("passengers"))),
            "cargo": _integer(weights.get("cargo")),
            "payload": _integer(weights.get("payload")),
            "zfw": _integer(_first(weights.get("est_zfw"), weights.get("zfw"))),
            "tow": _integer(_first(weights.get("est_tow"), weights.get("tow"))),
            "ldw": _integer(_first(weights.get("est_ldw"), weights.get("ldw"))),
            # v0.25.73: ZFW / TOW CG (% MAC) for the performance calculator.
            # SimBrief provides these in the OFP weights block; previously
            # dropped on parse, which left the Performance tab without the
            # CG input the takeoff V-speed / trim model needs.
            "zfwcg": _number(weights.get("zfwcg")),
            "towcg": _number(weights.get("towcg")),
            "ldwcg": _number(weights.get("ldwcg")),
            # v0.25.65: verified baggage/freight split + limits (raw payload
            # fields confirmed on real SimBrief responses).  ``cargo`` remains
            # the combined BAGS/CARGO hold; ``freight_added`` is commercial
            # freight.  See app/load_model.py for the split cross-check.
            "freight_added": _integer(weights.get("freight_added")),
            "bag_count": _integer(_first(weights.get("bag_count"), weights.get("bag_count_actual"))),
            "bag_weight": _integer(_first(weights.get("bag_weight"), weights.get("bag_weight_kg"))),
            "pax_weight": _integer(_first(weights.get("pax_weight"), weights.get("pax_weight_kg"))),
            "oew": _integer(weights.get("oew")),
            "max_zfw": _integer(weights.get("max_zfw")),
            "max_tow": _integer(weights.get("max_tow")),
            "max_ldw": _integer(weights.get("max_ldw")),
        },
        "remarks": _text(_first(general.get("remarks"), general.get("rmk"))),
        "files": {
            "pdf": pdf_url,
            "ofp": _text(_first(file_root.get("ofp"), links.get("ofp"))),
            "plan_html": plan_html,
            "plan_text": plan_text,
        },
        "briefing": {
            "notams": notams,
            "hazards": {"sections": hazard_sections},
            "sigmets": sigmets,
            "charts": charts,
            "database_updates": database_updates,
            "route_firs": _route_firs(raw),
        },
        "tlr": _tlr(raw),
    }

    if not origin["icao"] or not destination["icao"]:
        raise ValueError("SimBrief returned a flight plan without a valid origin or destination")
    try:
        from .airline_branding import resolve_airline_branding
        result["airline_branding"] = resolve_airline_branding(result)
    except Exception:
        result["airline_branding"] = {"enabled": True, "code": airline, "name": airline or "OPS ROOM", "source": "simbrief", "logo_url": None, "logo_available": False, "fallback": "monogram" if airline else "generic"}
    _enrich_plan_airport_data(result)
    return result


def _enrich_plan_airport_data(plan: dict[str, Any]) -> None:
    """Add runway / elevation / weather to origin & destination for the
    Performance tab auto-fill (v0.25.73).

    Additive only: existing consumers keep working because these keys are
    new.  Weather is decoded from the METAR text the OFP already carries, so
    no extra network fetch is needed; navdata supplies runway geometry and
    elevation when installed."""
    try:
        from . import navdata
        from .weather_client import decode_metar
        for key in ("origin", "destination"):
            station = plan.get(key)
            if not isinstance(station, dict):
                continue
            icao = str(station.get("icao") or "").upper()
            if not icao:
                continue
            airdata = navdata.airport(icao)
            if airdata:
                elev = airdata.get("altitude_ft") or airdata.get("elevation_ft")
                if elev:
                    station["elevation_ft"] = round(float(elev))
            rwy_name = str(station.get("runway") or "").replace("RWY", "").replace("RW", "").strip().upper()
            if rwy_name:
                rwy = navdata.runway_by_name(icao, rwy_name)
                if rwy:
                    length_ft = rwy.get("length_ft") or rwy.get("lda_ft")
                    if length_ft:
                        station["runway_length_m"] = round(float(length_ft) * 0.3048)
                    heading = rwy.get("heading_deg")
                    if heading is not None:
                        station["runway_heading"] = round(float(heading))
            metar = station.get("metar")
            if metar:
                wx = decode_metar(metar)
                station["weather"] = {
                    "temp_c": wx.get("temperature_c"),
                    "qnh_hpa": wx.get("qnh_hpa"),
                    "wind_dir": wx.get("wind_direction_deg"),
                    "wind_kt": wx.get("wind_speed_kts"),
                    "wind_gust_kt": wx.get("wind_gust_kts"),
                    "raw": metar,
                }
    except Exception as exc:
        _ofp_log("OFP_PERF_ENRICH_SKIPPED reason=%s", f"{type(exc).__name__}: {exc}")


def _cache_path() -> Path:
    return app_data_dir() / CACHE_FILE


def _raw_cache_path() -> Path:
    return app_data_dir() / RAW_CACHE_FILE


def ofp_cache_dir() -> Path:
    path = app_data_dir() / "simbrief_ofp_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cached_ofp_file(filename: str) -> Path | None:
    name = Path(str(filename or "")).name
    if not name or name != str(filename):
        return None
    path = ofp_cache_dir() / name
    if not path.is_file():
        return None
    # Never serve a partial/corrupt resource left by an interrupted prior run.
    kind = "pdf" if path.suffix.lower() == ".pdf" else "image" if name.startswith("simbrief_img_") else ""
    if kind and not _cached_resource_valid(path, kind):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    return path


def ofp_cache_filename(url: str, kind: str = "pdf") -> str:
    digest = hashlib.sha1(str(url or "").encode("utf-8", "ignore")).hexdigest()[:16]
    if kind == "pdf":
        return f"simbrief_ofp_{digest}.pdf"
    suffix = Path(urlparse(str(url or "")).path).suffix.lower()
    if suffix not in {".gif", ".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".img"
    return f"simbrief_img_{digest}{suffix}"


def _purge_old_ofp_files(keep: set[str] | None = None) -> None:
    keep = set(keep or set())
    try:
        folder = ofp_cache_dir()
        for item in folder.iterdir():
            if item.is_file() and item.name not in keep and not item.name.endswith(".tmp"):
                item.unlink(missing_ok=True)
            elif item.is_file() and item.name.endswith(".tmp"):
                item.unlink(missing_ok=True)
    except Exception:
        pass


def _valid_image(content: bytes) -> bool:
    return (
        content.startswith(b"GIF87a")
        or content.startswith(b"GIF89a")
        or content.startswith(b"\x89PNG\r\n\x1a\n")
        or content.startswith(b"\xff\xd8\xff")
        or (len(content) > 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP")
    )


def _resource_content_valid(content: bytes, kind: str) -> bool:
    if kind == "pdf":
        return content.startswith(b"%PDF") or b"%PDF" in content[:1024]
    return _valid_image(content)


def _cached_resource_valid(target: Path, kind: str) -> bool:
    try:
        if not target.is_file() or target.stat().st_size <= 32:
            return False
        with target.open("rb") as handle:
            head = handle.read(1024)
        return _resource_content_valid(head, kind)
    except OSError:
        return False


def _download_resource(url: str, target: Path, kind: str) -> Path:
    # Background prefetch and the browser's on-demand image request can arrive
    # together. Serialize the small critical section so both never write or
    # rename the same .tmp file concurrently.
    with _resource_lock:
        if _cached_resource_valid(target, kind):
            return target
        try:
            target.unlink(missing_ok=True)
            target.with_name(target.name + ".tmp").unlink(missing_ok=True)
        except OSError:
            pass
        response = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=(4, 15))
        response.raise_for_status()
        content = response.content or b""
        if not _resource_content_valid(content, kind):
            if kind == "pdf":
                raise RuntimeError("Downloaded OFP is not a PDF")
            raise RuntimeError("Downloaded OFP chart is not a supported image")
        temp = target.with_name(target.name + ".tmp")
        temp.write_bytes(content)
        os.replace(temp, target)
        return target


def _plan_identity(plan: dict[str, Any]) -> str:
    return _text(_first(plan.get("request_id"), plan.get("plan_id"), plan.get("sequence_id"), plan.get("generated_utc")))


def _write_raw_cache(user_ref: str, raw: dict[str, Any]) -> None:
    target = _raw_cache_path()
    temp = target.with_suffix(target.suffix + ".tmp")
    payload = {"user_ref": user_ref, "saved_utc": datetime.now(timezone.utc).isoformat(), "raw": raw}
    with _disk_lock:
        temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, target)


def _invalidate_briefing_cache() -> None:
    try:
        from .briefing_data import invalidate_cache
        invalidate_cache()
    except Exception:
        pass


def _publish_cached_resources(user_ref: str, identity: str, pdf_filename: str | None, cached_images: set[str], errors: list[str]) -> None:
    snapshot: dict[str, Any] | None = None
    with _lock:
        current = _memory.get("plan")
        if not isinstance(current, dict) or _memory.get("user_ref", "").lower() != user_ref.lower() or _plan_identity(current) != identity:
            return
        files = current.get("files") if isinstance(current.get("files"), dict) else {}
        if pdf_filename:
            files["pdf_local"] = f"/api/simbrief/ofp-cache/{pdf_filename}"
            files["pdf_path"] = str(ofp_cache_dir() / pdf_filename)
        if errors:
            files["resource_cache_error"] = " | ".join(errors)[:1000]
        else:
            files.pop("resource_cache_error", None)
        current["files"] = files
        briefing = current.get("briefing") if isinstance(current.get("briefing"), dict) else {}
        charts = briefing.get("charts") if isinstance(briefing.get("charts"), list) else []
        for chart in charts:
            if isinstance(chart, dict):
                filename = str(chart.get("cache_filename") or "")
                chart["cached"] = bool(filename and (filename in cached_images or (ofp_cache_dir() / filename).is_file()))
        briefing["charts"] = charts
        current["briefing"] = briefing
        _memory["plan"] = current
        snapshot = deepcopy(current)
    if snapshot is not None:
        _write_disk_cache(user_ref, snapshot)
        _invalidate_briefing_cache()


def _cache_ofp_resources(user_ref: str, identity: str, pdf_url: str, charts: list[dict[str, Any]]) -> None:
    keep: set[str] = set()
    errors: list[str] = []
    pdf_filename: str | None = None
    if pdf_url.lower().startswith(("http://", "https://")):
        pdf_filename = ofp_cache_filename(pdf_url, "pdf")
        keep.add(pdf_filename)
        try:
            _download_resource(pdf_url, ofp_cache_dir() / pdf_filename, "pdf")
        except Exception as exc:
            errors.append(f"PDF {type(exc).__name__}: {exc}")
            pdf_filename = None
    cached_images: set[str] = set()
    for chart in charts:
        if not isinstance(chart, dict):
            continue
        url = _text(chart.get("remote_url"))
        filename = _text(chart.get("cache_filename")) or ofp_cache_filename(url, "image")
        if not url.lower().startswith(("http://", "https://")) or not filename:
            continue
        keep.add(filename)
        try:
            _download_resource(url, ofp_cache_dir() / filename, "image")
            cached_images.add(filename)
        except Exception as exc:
            errors.append(f"{chart.get('name') or 'chart'} {type(exc).__name__}: {exc}")
    _purge_old_ofp_files(keep)
    _publish_cached_resources(user_ref, identity, pdf_filename, cached_images, errors)


def _start_resource_cache(user_ref: str, plan: dict[str, Any]) -> None:
    files = plan.get("files") if isinstance(plan.get("files"), dict) else {}
    briefing = plan.get("briefing") if isinstance(plan.get("briefing"), dict) else {}
    charts = [dict(item) for item in briefing.get("charts") or [] if isinstance(item, dict)]
    identity = _plan_identity(plan)
    if not identity:
        return
    threading.Thread(
        target=_cache_ofp_resources,
        args=(user_ref, identity, _text(files.get("pdf")), charts),
        name="OpsRoom-SimBrief-Resource-Cache",
        daemon=True,
    ).start()


def ensure_current_ofp_asset(filename: str) -> Path | None:
    name = Path(str(filename or "")).name
    if not name or name != str(filename):
        return None
    existing = cached_ofp_file(name)
    if existing:
        return existing
    with _lock:
        plan = deepcopy(_memory.get("plan")) if isinstance(_memory.get("plan"), dict) else None
        user_ref = _text(_memory.get("user_ref"))
    if not plan:
        return None
    charts = ((plan.get("briefing") or {}).get("charts") or []) if isinstance(plan.get("briefing"), dict) else []
    chart = next((item for item in charts if isinstance(item, dict) and _text(item.get("cache_filename")) == name), None)
    if not chart:
        return None
    try:
        path = _download_resource(_text(chart.get("remote_url")), ofp_cache_dir() / name, "image")
        _publish_cached_resources(user_ref, _plan_identity(plan), None, {name}, [])
        return path
    except Exception:
        return None


def _read_disk_cache(user_ref: str) -> dict[str, Any] | None:
    path = _cache_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if _text(data.get("user_ref")).lower() != user_ref.lower():
            return None
        plan = data.get("plan")
        if isinstance(plan, dict) and plan.get("ok"):
            plan = deepcopy(plan)
            plan["cache"] = "disk"
            return plan
    except (OSError, ValueError, TypeError):
        return None
    return None


def _write_disk_cache(user_ref: str, plan: dict[str, Any]) -> None:
    target = _cache_path()
    temp = target.with_suffix(target.suffix + ".tmp")
    payload = {"user_ref": user_ref, "saved_utc": datetime.now(timezone.utc).isoformat(), "plan": plan}
    with _disk_lock:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, target)


def cached_plan(user_ref: str) -> dict[str, Any] | None:
    user_ref = user_ref.strip()
    if not user_ref:
        return None
    with _lock:
        plan = _memory.get("plan")
        if _memory.get("user_ref", "").lower() == user_ref.lower() and isinstance(plan, dict):
            result = deepcopy(plan)
            result["cache"] = "memory"
            return result
    disk = _read_disk_cache(user_ref)
    if disk:
        with _lock:
            _memory.update(user_ref=user_ref, plan=deepcopy(disk), fetched_monotonic=0.0)
        _start_resource_cache(user_ref, disk)
    return disk


def _native_briefing_score(raw: dict[str, Any]) -> int:
    """Score structured NOTAM/chart content without depending on one schema revision."""
    score = len([item for item in _as_list(raw.get("notams")) if isinstance(item, dict)]) * 4
    score += len([item for item in _as_list(_as_dict(raw.get("images")).get("map")) if isinstance(item, dict)]) * 6
    score += len([item for item in _as_list(raw.get("sigmets")) if isinstance(item, dict)]) * 2
    for section in [raw.get("origin"), raw.get("destination"), *_as_list(raw.get("alternate"))]:
        score += len([item for item in _as_list(_as_dict(section).get("notam")) if isinstance(item, dict)])
    return score


def _fetch_simbrief_json(user_ref: str, key: str, json_format: str) -> dict[str, Any]:
    response = requests.get(
        SIMBRIEF_URL,
        params={key: user_ref, "json": json_format},
        headers={"User-Agent": _USER_AGENT},
        timeout=(3, 8),
    )
    if response.status_code >= 400:
        detail = response.text.strip().replace("\n", " ")[:240]
        raise RuntimeError(detail or f"SimBrief returned HTTP {response.status_code}")
    raw = response.json()
    if not isinstance(raw, dict):
        raise ValueError("SimBrief returned an unexpected response")
    return raw


def fetch_latest_ofp(user_ref: str, force: bool = False) -> dict[str, Any]:
    user_ref = user_ref.strip()
    if not user_ref:
        return {"ok": False, "state": "unconfigured", "reason": "SimBrief user ID is not configured"}

    with _lock:
        cached = _memory.get("plan")
        fresh = (
            _memory.get("user_ref", "").lower() == user_ref.lower()
            and isinstance(cached, dict)
            and time.monotonic() - float(_memory.get("fetched_monotonic", 0.0)) < CACHE_SECONDS
        )
        if fresh and not force:
            result = deepcopy(cached)
            result["cache"] = "memory"
            _ofp_log("OFP_CACHE_HIT age=%.0f", max(0.0, time.monotonic() - float(_memory.get("fetched_monotonic", 0.0))))
            return result
        _memory["last_attempt_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    key = "userid" if user_ref.isdigit() else "username"
    started = time.monotonic()
    _ofp_log("OFP_SIMBRIEF_START user=%s force=%s", user_ref, force)
    try:
        # Use SimBrief's documented JSON fetch first. Some deployments expose
        # additional structured route NOTAMs and native chart manifests through
        # the compatible v2 response; request it only when it is measurably
        # richer, and never let an unavailable v2 response break OFP loading.
        raw = _fetch_simbrief_json(user_ref, key, "1")
        selected_format = "json=1"
        documented_score = _native_briefing_score(raw)
        if not _as_list(raw.get("notams")) or not _as_list(_as_dict(raw.get("images")).get("map")):
            try:
                rich_raw = _fetch_simbrief_json(user_ref, key, "v2")
                rich_score = _native_briefing_score(rich_raw)
                if rich_score > documented_score:
                    raw = rich_raw
                    selected_format = "json=v2-compatible"
            except Exception as rich_exc:
                _ofp_log("OFP_SIMBRIEF_V2_OPTIONAL_UNAVAILABLE reason=%s", f"{type(rich_exc).__name__}: {rich_exc}")
        _ofp_log("OFP_SIMBRIEF_FORMAT %s score=%d", selected_format, _native_briefing_score(raw))
        fetch = _as_dict(raw.get("fetch"))
        fetch_status = _text(fetch.get("status")).lower()
        if fetch_status and fetch_status not in {"success", "ok"}:
            raise RuntimeError(_text(_first(fetch.get("message"), fetch.get("error")), "SimBrief could not return the latest OFP"))
        plan = _normalize(raw, user_ref)
        plan["fetched_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        plan["cache"] = "network"
        # Publish the authoritative plan before any background resource cache
        # worker starts. This prevents a fast download from being overwritten by
        # the original metadata-only plan.
        with _lock:
            _memory.update(
                user_ref=user_ref,
                fetched_monotonic=time.monotonic(),
                plan=deepcopy(plan),
                last_error=None,
            )
        _write_disk_cache(user_ref, plan)
        _write_raw_cache(user_ref, raw)
        _start_resource_cache(user_ref, plan)
        _ofp_log("OFP_SIMBRIEF_DONE duration_ms=%d", round((time.monotonic() - started) * 1000))
        _ofp_log("OFP_FETCH_RETURNED source=network")
        return plan
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, requests.Timeout):
            _ofp_log("OFP_SIMBRIEF_TIMEOUT duration_ms=%d", round((time.monotonic() - started) * 1000))
        else:
            _ofp_log("OFP_SIMBRIEF_DONE duration_ms=%d error=%s", round((time.monotonic() - started) * 1000), reason)
        with _lock:
            _memory["last_error"] = reason
        disk = cached_plan(user_ref)
        if disk and not force:
            disk["warning"] = reason
            disk["state"] = "cached"
            _ofp_log("OFP_FETCH_RETURNED source=disk-cache warning=%s", reason)
            return disk
        _ofp_log("OFP_FETCH_RETURNED source=error")
        return {"ok": False, "state": "fault", "reason": reason, "user_ref": user_ref}


def status(user_ref: str) -> dict[str, Any]:
    user_ref = user_ref.strip()
    if not user_ref:
        return {"state": "unconfigured", "label": "NOT SET", "detail": "Set a SimBrief Pilot ID in the OPS ROOM desktop host"}
    plan = cached_plan(user_ref)
    with _lock:
        last_error = _memory.get("last_error")
        last_attempt = _memory.get("last_attempt_utc")
    if plan:
        route = f'{plan.get("origin", {}).get("icao", "----")} TO {plan.get("destination", {}).get("icao", "----")}'
        callsign = plan.get("callsign") or "OFP"
        return {
            "state": "loaded",
            "label": "OFP LOADED",
            "detail": f"{callsign}  {route}",
            "plan": plan,
            "last_error": last_error,
            "last_attempt_utc": last_attempt,
        }
    if last_error:
        return {"state": "fault", "label": "FETCH FAILED", "detail": last_error, "last_attempt_utc": last_attempt}
    return {"state": "standby", "label": "READY TO FETCH", "detail": f"PILOT ID {user_ref}"}
