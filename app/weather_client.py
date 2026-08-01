from __future__ import annotations

import calendar
import html
import math
import re
import time
from datetime import datetime, timezone
from typing import Any

import requests

METAR_CACHE_SECONDS = 60
ATIS_CACHE_SECONDS = 120
_USER_AGENT = "VATSIM-Traffic-Board/0.4 simulation-only contact: local"

_metar_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_atis_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _cache_get(cache: dict[str, tuple[float, dict[str, Any]]], key: str, max_age: int) -> dict[str, Any] | None:
    hit = cache.get(key)
    if not hit:
        return None
    ts, value = hit
    if time.time() - ts <= max_age:
        return value
    return None


def _cache_set(cache: dict[str, tuple[float, dict[str, Any]]], key: str, value: dict[str, Any]) -> dict[str, Any]:
    cache[key] = (time.time(), value)
    return value


def extract_qnh(text: str | None) -> str | None:
    if not text:
        return None
    text_u = text.upper()
    patterns = [
        r"\bQNH\s*(\d{4})\s*(?:HPA)?\b",
        r"\bQ\s*(\d{4})\b",
        r"\bALTIMETER\s*(\d{2}\.\d{2})\b",
        r"\bA(\d{4})\b",
    ]
    for pat in patterns:
        m = re.search(pat, text_u)
        if m:
            val = m.group(1)
            if pat == r"\bA(\d{4})\b":
                return f"{val[:2]}.{val[2:]} inHg"
            return val if "." not in val else f"{val} inHg"
    return None



def extract_atis_code(text: str | None) -> str | None:
    if not text:
        return None
    match = re.search(r"\b(?:INFO|INFORMATION)\s+([A-Z])\b", text.upper())
    return match.group(1) if match else None


def extract_visibility(text: str | None) -> str | None:
    if not text:
        return None

    text_u = re.sub(r"\s+", " ", text.upper()).strip()
    if re.search(r"\bCAVOK\b", text_u):
        return "CAVOK"

    # Spoken or written ATIS visibility groups.
    patterns = [
        r"\bVIS(?:IBILITY)?\s+(?:GREATER\s+THAN\s+|MORE\s+THAN\s+)?((?:\d+\s+)?\d/\d|\d+(?:\.\d+)?)\s*(KM|KILOMET(?:ER|RE)S?|M|MET(?:ER|RE)S?|SM|STATUTE\s+MILES?)\b",
        r"\bVIS(?:IBILITY)?\s+(\d{4})\s*(?:M|MET(?:ER|RE)S?)?\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text_u)
        if not match:
            continue
        value = match.group(1).strip()
        unit = match.group(2).strip() if match.lastindex and match.lastindex >= 2 and match.group(2) else "M"
        if unit.startswith("KILOMET"):
            unit = "KM"
        elif unit.startswith("MET") or unit == "M":
            unit = "M"
        elif unit.startswith("STATUTE"):
            unit = "SM"
        return f"{value} {unit}"

    # METAR visibility immediately following the wind/variable-wind group.
    match = re.search(
        r"\b(?:\d{3}|VRB)\d{2,3}(?:G\d{2,3})?KT"
        r"(?:\s+\d{3}V\d{3})?\s+"
        r"(CAVOK|\d{4}|P?\d+(?:\s+\d/\d)?SM|M\d/\dSM)\b",
        text_u,
    )
    if match:
        value = match.group(1)
        if value == "CAVOK" or value.endswith("SM"):
            return value
        return f"{value} M"

    match = re.search(r"\b(P?\d+(?:\s+\d/\d)?SM|M\d/\dSM)\b", text_u)
    return match.group(1) if match else None


def extract_runways(text: str | None) -> list[str]:
    if not text:
        return []
    t = re.sub(r"\s+", " ", text.upper())
    candidates: list[str] = []
    patterns = [
        r"RWY(?:S|YS)?(?:\s+IN\s+USE)?(?:\s+FOR\s+(?:ARR|DEP))?\s+((?:\d{2}[LCR]?\s*(?:AND|,|/|\s)+){0,8}\d{2}[LCR]?)",
        r"RUNWAY(?:S)?(?:\s+IN\s+USE)?\s+((?:\d{2}[LCR]?\s*(?:AND|,|/|\s)+){0,8}\d{2}[LCR]?)",
        r"(?:ILS|RNAV|VOR|VISUAL)\s+(?:Z\s+|Y\s+|X\s+)?(?:APCH\s*)?RWY\s*(\d{2}[LCR]?)",
        r"(?:ARR|DEP)\s+RWY\s*(\d{2}[LCR]?)",
        r"(?:ARR|DEP)\s+(\d{2}[LCR]?)\b",
    ]
    for pat in patterns:
        for m in re.finditer(pat, t):
            chunk = m.group(1)
            for rwy in re.findall(r"\b\d{2}[LCR]?\b", chunk):
                if rwy not in candidates:
                    candidates.append(rwy)
    return candidates[:10]



def _metar_temperature(token: str | None) -> float | None:
    value = str(token or "").strip().upper()
    if not value or value == "//":
        return None
    sign = -1.0 if value.startswith("M") else 1.0
    if value.startswith("M"):
        value = value[1:]
    try:
        return sign * float(value)
    except (TypeError, ValueError):
        return None


def _metar_report_epoch(raw: str, report_time: Any = None) -> float | None:
    if report_time not in (None, ""):
        try:
            numeric = float(report_time)
            if numeric > 1_000_000_000:
                return numeric
        except (TypeError, ValueError):
            pass
        try:
            return datetime.fromisoformat(str(report_time).replace("Z", "+00:00")).timestamp()
        except Exception:
            pass
    match = re.search(r"\b(\d{2})(\d{2})(\d{2})Z\b", str(raw or "").upper())
    if not match:
        return None
    day, hour, minute = map(int, match.groups())
    now = datetime.now(timezone.utc)
    candidates: list[datetime] = []
    for month_offset in (-1, 0, 1):
        year, month = now.year, now.month + month_offset
        if month < 1:
            year -= 1
            month += 12
        elif month > 12:
            year += 1
            month -= 12
        if day <= calendar.monthrange(year, month)[1]:
            candidates.append(datetime(year, month, day, hour, minute, tzinfo=timezone.utc))
    if not candidates:
        return None
    return min(candidates, key=lambda value: abs((value - now).total_seconds())).timestamp()


def _metar_visibility(raw: str) -> tuple[float | None, str]:
    text = str(raw or "").upper()
    if re.search(r"\bCAVOK\b", text):
        return 9999.0, "9999 m or greater"
    metric = re.search(r"\b(\d{4})\b", text)
    if metric:
        metres = float(metric.group(1))
        return metres, "9999 m or greater" if metres >= 9999 else f"{int(metres):,} m"
    statute = re.search(r"\b([PM]?)(\d+(?:\s+\d/\d)?|\d/\d)SM\b", text)
    if statute:
        prefix, value = statute.groups()
        parts = value.split()
        miles = 0.0
        for part in parts:
            if "/" in part:
                numerator, denominator = part.split("/", 1)
                miles += float(numerator) / float(denominator)
            else:
                miles += float(part)
        if prefix == "P":
            label = f"More than {miles:g} statute miles"
        elif prefix == "M":
            label = f"Less than {miles:g} statute miles"
        else:
            label = f"{miles:g} statute miles"
        return miles * 1609.344, label
    return None, "Not reported"


def decode_metar(raw: str | None, report_time: Any = None) -> dict[str, Any]:
    """Decode Briefing fields from the raw METAR text."""
    text = re.sub(r"\s+", " ", str(raw or "").upper()).strip()
    decoded: dict[str, Any] = {
        "wind": "Not reported", "visibility": "Not reported", "temperature": "Not reported",
        "dewpoint": "Not reported", "humidity": "Not reported", "altimeter": "Not reported",
        "flight_category": "UNKNOWN", "age_seconds": None,
    }
    if not text:
        return decoded
    wind = re.search(r"\b(VRB|\d{3})(\d{2,3})(?:G(\d{2,3}))?(KT|MPS)\b", text)
    if wind:
        direction, speed_raw, gust_raw, unit = wind.groups()
        speed = int(speed_raw); gust = int(gust_raw) if gust_raw else None
        if unit == "MPS":
            speed = round(speed * 1.94384); gust = round(gust * 1.94384) if gust is not None else None; unit = "KT"
        if direction == "000" and speed == 0:
            wind_text = "Calm"
        else:
            wind_text = f"{'Variable' if direction == 'VRB' else direction + '°'} at {speed} {unit}"
            if gust is not None: wind_text += f", gusting {gust} {unit}"
        variation = re.search(r"\b(\d{3})V(\d{3})\b", text)
        if variation: wind_text += f" (variable {variation.group(1)}°–{variation.group(2)}°)"
        decoded.update({"wind": wind_text, "wind_direction_deg": None if direction == "VRB" else int(direction), "wind_speed_kts": speed, "wind_gust_kts": gust})
    visibility_m, visibility_text = _metar_visibility(text)
    decoded.update({"visibility_m": visibility_m, "visibility": visibility_text})
    temperature = re.search(r"\b(M?\d{2})/(M?\d{2}|//)\b", text)
    temp_c = _metar_temperature(temperature.group(1)) if temperature else None
    dew_c = _metar_temperature(temperature.group(2)) if temperature else None
    if temp_c is not None:
        decoded.update({"temperature_c": temp_c, "temperature": f"{temp_c:g}° C ({temp_c * 9 / 5 + 32:.0f}° F)"})
    if dew_c is not None:
        decoded.update({"dewpoint_c": dew_c, "dewpoint": f"{dew_c:g}° C ({dew_c * 9 / 5 + 32:.0f}° F)"})
    if temp_c is not None and dew_c is not None:
        humidity = max(0.0, min(100.0, 100.0 * math.exp((17.625 * dew_c) / (243.04 + dew_c) - (17.625 * temp_c) / (243.04 + temp_c))))
        decoded.update({"humidity_percent": round(humidity), "humidity": f"{round(humidity)} %"})
    qnh = re.search(r"\bQ(\d{4})\b", text); altimeter = re.search(r"\bA(\d{4})\b", text)
    if qnh:
        hpa = int(qnh.group(1)); inhg = hpa * 0.0295299830714
        decoded.update({"qnh_hpa": hpa, "altimeter_inhg": round(inhg, 2), "altimeter": f"{hpa} hPa ({inhg:.2f} inHg)"})
    elif altimeter:
        inhg = int(altimeter.group(1)) / 100.0; hpa = round(inhg / 0.0295299830714)
        decoded.update({"qnh_hpa": hpa, "altimeter_inhg": inhg, "altimeter": f"{hpa} hPa ({inhg:.2f} inHg)"})
    ceilings = [int(value) * 100 for value in re.findall(r"\b(?:BKN|OVC)(\d{3})\b", text)]
    vertical = re.search(r"\bVV(\d{3})\b", text)
    if vertical: ceilings.append(int(vertical.group(1)) * 100)
    ceiling_ft = min(ceilings) if ceilings else None; decoded["ceiling_ft"] = ceiling_ft
    visibility_sm = visibility_m / 1609.344 if visibility_m is not None else None
    if "CAVOK" in text: category = "VFR"
    elif (visibility_sm is not None and visibility_sm < 1.0) or (ceiling_ft is not None and ceiling_ft < 500): category = "LIFR"
    elif (visibility_sm is not None and visibility_sm < 3.0) or (ceiling_ft is not None and ceiling_ft < 1000): category = "IFR"
    elif (visibility_sm is not None and visibility_sm <= 5.0) or (ceiling_ft is not None and ceiling_ft <= 3000): category = "MVFR"
    else: category = "VFR"
    decoded["flight_category"] = category
    report_epoch = _metar_report_epoch(text, report_time)
    if report_epoch is not None:
        decoded.update({"report_epoch": report_epoch, "age_seconds": max(0, round(time.time() - report_epoch))})
    return decoded


def fetch_metar(icao: str, force: bool = False) -> dict[str, Any]:
    icao = icao.strip().upper()
    key = f"metar:{icao}"
    if not force:
        hit = _cache_get(_metar_cache, key, METAR_CACHE_SECONDS)
        if hit:
            return hit
    result: dict[str, Any] = {
        "ok": False,
        "source": "AviationWeather.gov",
        "icao": icao,
        "raw": None,
        "qnh": None,
        "visibility": None,
        "flight_category": None,
        "wind": None,
        "temp_dewpoint": None,
        "age_seconds": None,
        "error": None,
    }
    try:
        url = "https://aviationweather.gov/api/data/metar"
        resp = requests.get(url, params={"ids": icao, "format": "json"}, headers={"User-Agent": _USER_AGENT}, timeout=8)
        if resp.status_code == 204:
            result["error"] = "No recent METAR available"
            return _cache_set(_metar_cache, key, result)
        resp.raise_for_status()
        data = resp.json()
        item = data[0] if isinstance(data, list) and data else data if isinstance(data, dict) else None
        if not item:
            result["error"] = "No METAR record in response"
            return _cache_set(_metar_cache, key, result)
        raw = item.get("rawOb") or item.get("raw_text") or item.get("raw") or ""
        report_time = item.get("reportTime") or item.get("obsTime")
        decoded = decode_metar(raw, report_time)
        result.update({
            "ok": True,
            "raw": raw,
            "qnh": decoded.get("qnh_hpa") or extract_qnh(raw),
            "visibility": decoded.get("visibility") or extract_visibility(raw),
            "flight_category": decoded.get("flight_category") or item.get("fltCat") or item.get("flight_category"),
            "wind": decoded.get("wind"),
            "wind_speed": decoded.get("wind_speed_kts") if decoded.get("wind_speed_kts") is not None else item.get("wspd"),
            "temp": decoded.get("temperature_c") if decoded.get("temperature_c") is not None else item.get("temp"),
            "dewpoint": decoded.get("dewpoint_c") if decoded.get("dewpoint_c") is not None else item.get("dewp"),
            "report_time": report_time,
            "age_seconds": decoded.get("age_seconds"),
            "decoded": decoded,
        })
    except Exception as exc:
        result["error"] = str(exc)
    return _cache_set(_metar_cache, key, result)


def _strip_tags(s: str) -> str:
    s = re.sub(r"<script[\s\S]*?</script>", " ", s, flags=re.I)
    s = re.sub(r"<style[\s\S]*?</style>", " ", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", " \n ", s, flags=re.I)
    s = re.sub(r"</(?:p|div|h\d|section|li)>", " \n ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\n\s+", "\n", s)
    return re.sub(r"\n{2,}", "\n", s).strip()


def _section_after(text: str, title: str) -> str | None:
    # ATIS.guru pages often include a temporary "No ATIS available" placeholder
    # before the prerendered message. Do not treat the placeholder as final.
    t = re.sub(r"\s+", " ", text).strip()
    pat = rf"{re.escape(title)}\s+(?:\d{{4}}-\d{{2}}-\d{{2}}\s+\d{{2}}:\d{{2}}\s+UTC\s+)?(.*?)(?=\s+(?:Arrival ATIS|Departure ATIS|METAR|TAF|No ATIS available|An unhandled error|$))"
    matches = [m.group(1).strip() for m in re.finditer(pat, t, flags=re.I) if m.group(1).strip()]
    if not matches:
        return None
    # Prefer the longest section; it is usually the actual D-ATIS, not page chrome.
    best = max(matches, key=len)
    if len(best) < 8 or "NO ATIS AVAILABLE" in best.upper():
        return None
    return best[:1800]


def _generated_atis_from_metar(icao: str, metar: dict[str, Any]) -> dict[str, Any]:
    raw = metar.get("raw") or metar.get("error") or "No METAR available"
    qnh = metar.get("qnh")
    text = f"{icao} INFORMATION UNAVAILABLE. REAL D-ATIS NOT AVAILABLE. GENERATED SIMULATION FALLBACK FROM METAR: {raw}"
    return {
        "ok": bool(metar.get("ok")),
        "source": "METAR-generated fallback",
        "icao": icao,
        "arrival": None,
        "departure": None,
        "text": text,
        "atis_code": None,
        "qnh": qnh,
        "visibility": metar.get("visibility"),
        "runways": [],
        "generated": True,
        "error": None if metar.get("ok") else "No real D-ATIS and no METAR fallback available",
        "url": None,
    }


def fetch_realworld_atis(icao: str, force: bool = False) -> dict[str, Any]:
    icao = icao.strip().upper()
    key = f"atis:{icao}"
    if not force:
        hit = _cache_get(_atis_cache, key, ATIS_CACHE_SECONDS)
        if hit:
            return hit
    result: dict[str, Any] = {
        "ok": False,
        "source": "ATIS.guru",
        "icao": icao,
        "arrival": None,
        "departure": None,
        "text": None,
        "atis_code": None,
        "qnh": None,
        "visibility": None,
        "runways": [],
        "generated": False,
        "error": None,
        "url": f"https://atis.guru/atis/{icao}",
    }
    try:
        resp = requests.get(result["url"], headers={"User-Agent": _USER_AGENT}, timeout=8)
        resp.raise_for_status()
        text = _strip_tags(resp.text)
        arrival = _section_after(text, "Arrival ATIS")
        departure = _section_after(text, "Departure ATIS")
        combined_parts = []
        if arrival:
            combined_parts.append("ARR: " + arrival)
        if departure:
            combined_parts.append("DEP: " + departure)
        combined = "\n\n".join(combined_parts) if combined_parts else ""
        if combined:
            result.update({
                "ok": True,
                "arrival": arrival,
                "departure": departure,
                "text": combined[:2400],
                "atis_code": extract_atis_code(combined),
                "qnh": extract_qnh(combined),
                "visibility": extract_visibility(combined),
                "runways": extract_runways(combined),
                "generated": False,
            })
            return _cache_set(_atis_cache, key, result)
        result["error"] = "No real-world D-ATIS available on ATIS.guru"
    except Exception as exc:
        result["error"] = str(exc)

    # Fallback: not a real ATIS, but prevents a blank panel and helps stream overlays.
    metar = fetch_metar(icao, force=force)
    generated = _generated_atis_from_metar(icao, metar)
    if result.get("error"):
        generated["error"] = result["error"]
    return _cache_set(_atis_cache, key, generated)


def analyze_atis_text(text: str | None) -> dict[str, Any]:
    return {
        "atis_code": extract_atis_code(text),
        "qnh": extract_qnh(text),
        "visibility": extract_visibility(text),
        "runways": extract_runways(text),
    }
