from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests

from .settings_store import load_settings
from .simbrief_client import cached_ofp_file, cached_plan, ofp_cache_filename
from . import nms_client
from . import notam_client  # v0.25.65: server-side NOTAM store client (DB-first)
from . import notam_translate  # v0.25.65: plain-English NOTAM expansion

_LOCK = threading.RLock()
_CACHE: dict[str, Any] | None = None
_CACHE_MONO = 0.0
_CACHE_KEY = ""
_CACHE_TTL = 300.0
_PAGE_CACHE: dict[tuple[str, int, int], bytes] = {}


def _app_version() -> str:
    """v0.25.67: user-agent version comes from version.json, never a stale literal."""
    try:
        raw = (Path(__file__).resolve().parent.parent / "version.json").read_text(encoding="utf-8")
        return str(json.loads(raw).get("version") or "0.25.0")
    except Exception:  # pragma: no cover - defensive version read
        return "0.25.0"


_USER_AGENT = f"OPS ROOM/{_app_version()} flight briefing"

_NOTAM_ID = re.compile(r"^(?P<id>[A-Z]{1,2}\d{3,4}/\d{2})\b", re.I)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_lines(text: str) -> list[str]:
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    return [line.rstrip() for line in text.split("\n")]


def _flight_identifiers(plan: dict[str, Any]) -> list[str]:
    result: list[str] = []
    alternates = plan.get("alternates") if isinstance(plan.get("alternates"), list) else []
    airports = [plan.get("origin"), plan.get("destination"), plan.get("alternate"), *alternates]
    for airport in airports:
        value = str(((airport or {}).get("icao") or (airport or {}).get("icao_code")) or "").upper().strip() if isinstance(airport, dict) else ""
        if len(value) == 4 and value not in result:
            result.append(value)
    briefing = plan.get("briefing") if isinstance(plan.get("briefing"), dict) else {}
    for value in briefing.get("route_firs") or []:
        code = str(value or "").upper().strip()
        if len(code) == 4 and code not in result:
            result.append(code)
    for fix in plan.get("navlog") or []:
        if not isinstance(fix, dict):
            continue
        # Normalized navlogs carry ``fir`` and ``fir_crossing``. Keep the
        # legacy ``type=FIR, ident=XXXX`` shape for old cached plans/tests.
        candidates = [fix.get("fir")]
        if str(fix.get("type") or "").upper() == "FIR":
            candidates.append(fix.get("ident"))
        for value in candidates:
            code = str(value or "").upper().strip()
            if len(code) == 4 and code not in result:
                result.append(code)
        for crossing in fix.get("fir_crossing") or []:
            code = str((crossing or {}).get("fir_icao") or "").upper().strip() if isinstance(crossing, dict) else ""
            if len(code) == 4 and code not in result:
                result.append(code)
    return result


def _current_plan() -> dict[str, Any] | None:
    settings = load_settings()
    user = str(settings.get("identity", {}).get("simbrief_user_id") or "").strip()
    plan = cached_plan(user) if user else None
    return plan if isinstance(plan, dict) and plan.get("ok") else None


def _pdf_path(plan: dict[str, Any]) -> Path | None:
    files = plan.get("files") if isinstance(plan.get("files"), dict) else {}
    local = str(files.get("pdf_local") or "").strip()
    if local:
        parsed = urlparse(local)
        name = Path(unquote(parsed.path)).name
        path = cached_ofp_file(name)
        if path and path.exists():
            return path
    raw = str(files.get("pdf_path") or "").strip()
    if raw:
        path = Path(raw).expanduser()
        if path.is_file():
            return path
    remote = str(files.get("pdf") or "").strip()
    if remote.lower().startswith(("http://", "https://")):
        path = cached_ofp_file(ofp_cache_filename(remote, "pdf"))
        if path and path.exists():
            return path
    return None


def invalidate_cache() -> None:
    global _CACHE, _CACHE_MONO, _CACHE_KEY
    with _LOCK:
        _CACHE = None
        _CACHE_MONO = 0.0
        _CACHE_KEY = ""
        _PAGE_CACHE.clear()


def _plan_fingerprint(plan: dict[str, Any]) -> str:
    briefing = plan.get("briefing") if isinstance(plan.get("briefing"), dict) else {}
    charts = briefing.get("charts") if isinstance(briefing.get("charts"), list) else []
    files = plan.get("files") if isinstance(plan.get("files"), dict) else {}
    payload = {
        "plan": plan.get("request_id") or plan.get("plan_id") or plan.get("generated_utc"),
        "notams": len(briefing.get("notams") or []),
        "hazards": briefing.get("hazards") or {},
        "charts": [(item.get("name"), item.get("cache_filename"), item.get("cached")) for item in charts if isinstance(item, dict)],
        "pdf": files.get("pdf_local") or files.get("pdf") or "",
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _scope_from_line(line: str, current: str) -> str:
    upper = re.sub(r"\s+", " ", str(line or "").strip().upper())
    if not upper:
        return current
    rules = (
        ("DEPARTURE AIRPORT - DETAILED INFO", "Departure airport"),
        ("DESTINATION AIRPORT - DETAILED INFO", "Destination airport"),
        ("DESTINATION ALTERNATE AIRPORT", "Destination alternate"),
        ("EXTENDED AREA AROUND DEPARTURE", "Departure extended area / FIR"),
        ("EXTENDED AREA AROUND DESTINATION ALTERNATE", "Alternate extended area / FIR"),
        ("EXTENDED AREA AROUND DESTINATION", "Destination extended area / FIR"),
        ("AREA ENROUTE DEPARTURE - DESTINATION", "En route"),
        ("[ COMPANY NOTAM ]", "Company NOTAMs"),
    )
    for token, label in rules:
        if token in upper:
            return label
    return current


def _scope_key_from_scope(scope: str) -> str:
    value = str(scope or "").strip().lower()
    if value.startswith("departure airport"):
        return "departure"
    if value.startswith("destination airport"):
        return "destination"
    if value.startswith("destination alternate"):
        return "alternate"
    return "enroute"


def _parse_lido_validity(text: str) -> dict[str, Any]:
    value = re.sub(r"\s+", " ", str(text or "")).strip().upper()
    result: dict[str, Any] = {}
    match = re.search(r"\bVALID:\s*(\d{2}-[A-Z]{3}-\d{2})\s+(\d{4})\s*-\s*(\d{2}-[A-Z]{3}-\d{2})\s+(\d{4})", value)
    if match:
        try:
            start = datetime.strptime(f"{match.group(1)} {match.group(2)}", "%d-%b-%y %H%M").replace(tzinfo=timezone.utc)
            end = datetime.strptime(f"{match.group(3)} {match.group(4)}", "%d-%b-%y %H%M").replace(tzinfo=timezone.utc)
            result["effective_utc"] = start.isoformat().replace("+00:00", "Z")
            result["expires_utc"] = end.isoformat().replace("+00:00", "Z")
        except ValueError:
            pass
    if re.search(r"\bC\)\s*PERM\b|\bPERMANENT\b", value):
        result["permanent"] = True
        result["expires_utc"] = None
    return result


def _parse_lido_notams(text: str) -> list[dict[str, Any]]:
    lines = _clean_lines(text)
    result: list[dict[str, Any]] = []
    scope = "Flight route"
    location = ""
    category = ""
    active: dict[str, Any] | None = None

    def finish() -> None:
        nonlocal active
        if not active:
            return
        ident = str(active.get("id") or "").strip().upper()
        body_lines: list[str] = []
        for item in active.pop("lines", []):
            clean = str(item or "").strip()
            if not clean:
                continue
            upper = clean.upper()
            if upper == ident:
                continue
            if "NOT FOR REAL WORLD NAVIGATION" in upper:
                continue
            if re.fullmatch(r"(?:PAGE\s+)?\d+", upper):
                continue
            if re.match(r"^OS\s+\d+/.+PAGE\s+\d+$", clean, re.I):
                continue
            body_lines.append(clean)
        body = "\n".join(body_lines).strip()
        if body:
            active["text"] = body[:10000]
            active.update(_parse_lido_validity(body))
            result.append(active)
        active = None

    for raw in lines:
        line = raw.strip()
        scope = _scope_from_line(line, scope)
        if line.startswith("+") and line.endswith("+"):
            label = line.strip("+ ").strip()
            if label:
                category = label.title()
            continue
        if re.match(r"^[A-Z]{4}/[A-Z]{3}\b", line):
            location = line.split()[0]
        elif re.match(r"^[A-Z]{4}\s+.+\b(?:FIR|UIR)\b", line, re.I):
            location = line
        match = _NOTAM_ID.match(line)
        if match:
            finish()
            active = {
                "id": match.group("id").upper(),
                "scope_key": _scope_key_from_scope(scope),
                "scope": f"{scope} · {category}" if category else scope,
                "location": location,
                "source": "SimBrief OFP PDF",
                "lines": [],
                "source_order": len(result),
            }
            continue
        if active:
            if line.upper().startswith("END OF LIDO-NOTAM-BULLETIN"):
                finish()
                break
            # Decorative separators and duplicated page headers do not belong
            # inside an individual operational notice.
            if (
                line
                and not re.fullmatch(r"[-=+ ]+", line)
                and not re.match(r"^OS\s+\d+/.+PAGE\s+\d+$", line, re.I)
                and "NOT FOR REAL WORLD NAVIGATION" not in line.upper()
                and not re.fullmatch(r"(?:PAGE\s+)?\d+", line.upper())
            ):
                active["lines"].append(line)
    finish()
    return result[:250]


def _parse_sigmet_sections(text: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    lines = _clean_lines(text)
    wanted = {
        "SIGMETS:": "SIGMET",
        "TROPICAL CYCLONE SIGMETS:": "Tropical cyclone SIGMET",
        "VOLCANIC ASH SIGMETS:": "Volcanic ash SIGMET",
    }
    stop_headings = {"DEPARTURE:", "DESTINATION:", "DESTINATION ALTERNATES:", "AIRPORTLIST ENDED"}
    blocks: dict[str, list[str]] = {label: [] for label in wanted.values()}
    current = ""
    for raw in lines:
        line = raw.strip()
        upper = line.upper()
        if upper in wanted:
            current = wanted[upper]
            continue
        if upper in stop_headings or upper == "AIRMETS:":
            current = ""
            continue
        if current and line and not re.fullmatch(r"[-= ]+", line):
            blocks[current].append(line)

    rows: list[dict[str, Any]] = []
    states: dict[str, str] = {}
    for label, content in blocks.items():
        body = "\n".join(content).strip()
        if not body or "NO WX DATA AVAILABLE" in body.upper():
            states[label] = "none"
            continue
        states[label] = "available"
        chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", body) if chunk.strip()]
        for index, chunk in enumerate(chunks or [body], start=1):
            first = next((x.strip() for x in chunk.splitlines() if x.strip()), label)
            rows.append({
                "id": first[:80] if first else f"{label} {index}",
                "scope": label,
                "source": "SimBrief OFP PDF",
                "text": chunk[:10000],
            })
    return rows, states


def _page_density(page: Any) -> float:
    """Return a low-resolution ink/detail ratio for a raster chart page.

    SimBrief LIDO ordering places the route map first, then one or more sparse
    SIGWX maps, followed by visibly dense wind charts.  The ratio lets OPS ROOM
    discover the SIGWX run without OCR or hard-coded page numbers.
    """
    import pymupdf

    pix = page.get_pixmap(matrix=pymupdf.Matrix(0.28, 0.28), colorspace=pymupdf.csGRAY, alpha=False)
    width, height = int(pix.width), int(pix.height)
    samples = memoryview(pix.samples)
    x0, x1 = int(width * 0.05), int(width * 0.95)
    y0, y1 = int(height * 0.08), int(height * 0.88)
    total = max(1, (x1 - x0) * (y1 - y0))
    dark = 0
    for y in range(y0, y1):
        row = samples[y * width + x0 : y * width + x1]
        dark += sum(1 for value in row if value < 235)
    return dark / total


def _extract_pdf_package(path: Path) -> dict[str, Any]:
    try:
        import pymupdf
    except Exception as exc:  # pragma: no cover - build validation checks dependency
        return {"ok": False, "reason": f"PDF support unavailable: {type(exc).__name__}", "notams": [], "sigmets": [], "sigwx_pages": []}

    try:
        document = pymupdf.open(path)
    except Exception as exc:
        return {"ok": False, "reason": f"Could not open cached OFP PDF: {type(exc).__name__}", "notams": [], "sigmets": [], "sigwx_pages": []}

    try:
        texts = [document[index].get_text("text") or "" for index in range(document.page_count)]
        upper_texts = [text.upper() for text in texts]
        notam_start = next((i for i, text in enumerate(upper_texts) if "[ NOTAM ]" in text or "LIDO-NOTAM-BULLETIN" in text), None)
        notam_end = next((i for i, text in enumerate(upper_texts) if "END OF LIDO-NOTAM-BULLETIN" in text), None)
        if notam_start is not None and notam_end is None:
            notam_end = notam_start
            for i in range(notam_start + 1, document.page_count):
                if "[ COMPANY NOTAM ]" in upper_texts[i]:
                    notam_end = i
                elif len(texts[i].strip()) < 80 and document[i].get_images(full=True):
                    break
                else:
                    notam_end = i
        if notam_start is not None and notam_end is not None and notam_end >= notam_start:
            notam_text = "\n".join(texts[notam_start : notam_end + 1])
            notams = _parse_lido_notams(notam_text)
            notam_pages = list(range(notam_start + 1, notam_end + 2))
        else:
            notams, notam_pages = [], []

        wx_index = next((i for i, text in enumerate(upper_texts) if "[ AIRPORT WX LIST ]" in text), None)
        sigmets, sigmet_states = _parse_sigmet_sections(texts[wx_index]) if wx_index is not None else ([], {})

        # Find the raster chart block following the NOTAM bulletin. The first
        # sparse chart is the route map. Subsequent sparse chart pages are
        # SIGWX; the run stops at the denser wind charts.
        search_from = (notam_end + 1) if notam_end is not None else max(0, document.page_count - 10)
        raster_pages: list[int] = []
        for i in range(search_from, document.page_count):
            text = re.sub(r"\s+", " ", texts[i]).strip()
            if len(text) <= 120 and document[i].get_images(full=True):
                raster_pages.append(i)
        sigwx_pages: list[int] = []
        if len(raster_pages) >= 2:
            # SimBrief's first map page is the route chart, not SIGWX.
            for index in raster_pages[1:]:
                density = _page_density(document[index])
                if density >= 0.19:
                    break
                sigwx_pages.append(index + 1)  # public API is 1-based
                if len(sigwx_pages) >= 4:
                    break

        return {
            "ok": True,
            "page_count": document.page_count,
            "notams": notams,
            "notam_pages": notam_pages,
            "sigmets": sigmets,
            "sigmet_states": sigmet_states,
            "sigmet_page": (wx_index + 1) if wx_index is not None else None,
            "sigwx_pages": sigwx_pages,
        }
    finally:
        document.close()


def _extract_plan_text_fallback(plan: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    files = plan.get("files") if isinstance(plan.get("files"), dict) else {}
    text = str(files.get("plan_text") or "")
    upper = text.upper()
    notams: list[dict[str, Any]] = []
    sigmets: list[dict[str, Any]] = []
    if "NOTAM" in upper:
        start = upper.find("NOTAM")
        notams = _parse_lido_notams(text[start:])
        for row in notams:
            row["source"] = "SimBrief OFP text"
    if "SIGMET" in upper:
        sigmets, _ = _parse_sigmet_sections(text)
        for row in sigmets:
            row["source"] = "SimBrief OFP text"
    return notams, sigmets


def _autorouter_notams(identifiers: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    token = str(os.environ.get("OPSROOM_AUTOROUTER_TOKEN") or "").strip()
    if not token or not identifiers:
        return [], None
    params = {"itemas": json.dumps(identifiers), "offset": 0, "limit": 100}
    try:
        response = requests.get(
            "https://api.autorouter.aero/v1.0/notam",
            params=params,
            headers={"Authorization": f"Bearer {token}", "User-Agent": _USER_AGENT},
            timeout=4.0,
        )
        response.raise_for_status()
        payload = response.json() if response.content else {}
        rows = payload.get("rows") if isinstance(payload, dict) else []
        result = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            ident = f"{row.get('series') or ''}{row.get('number') or ''}/{str(row.get('year') or '')[-2:]}".strip("/")
            items = ", ".join(str(x) for x in (row.get("itema") or []) if x)
            text = f"{ident}  A) {items}\nE) {row.get('iteme') or ''}".strip()
            result.append({"id": ident or items or "NOTAM", "scope": items, "text": text, "source": "autorouter / EUROCONTROL EAD"})
        return result, {"name": "autorouter / EUROCONTROL EAD", "state": "ok" if result else "empty", "count": len(result)}
    except Exception as exc:
        return [], {"name": "autorouter / EUROCONTROL EAD", "state": "unavailable", "detail": type(exc).__name__}


def _awc_sigmets(identifiers: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        response = requests.get(
            "https://aviationweather.gov/api/data/airsigmet",
            params={"format": "json"},
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            timeout=4.0,
        )
        if response.status_code == 204:
            return [], {"name": "NOAA Aviation Weather Center", "state": "empty", "count": 0}
        response.raise_for_status()
        payload = response.json()
        result = []
        for row in payload if isinstance(payload, list) else []:
            if not isinstance(row, dict):
                continue
            ident = str(row.get("airsigmetId") or row.get("id") or row.get("hazard") or "SIGMET")
            text = str(row.get("rawAirSigmet") or row.get("raw_text") or row.get("raw") or "").strip()
            if not text:
                text = " · ".join(str(row.get(k) or "") for k in ("hazard", "severity", "validTimeFrom", "validTimeTo") if row.get(k))
            if text and (not identifiers or any(code in text.upper() for code in identifiers)):
                result.append({"id": ident, "scope": "Route supplement", "text": text[:5000], "source": "NOAA Aviation Weather Center"})
        return result[:100], {"name": "NOAA Aviation Weather Center", "state": "ok" if result else "empty", "count": len(result)}
    except Exception as exc:
        return [], {"name": "NOAA Aviation Weather Center", "state": "unavailable", "detail": type(exc).__name__}


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        text = re.sub(r"\s+", " ", str(row.get("text") or "")).strip()
        key = (str(row.get("id") or "").upper(), text.upper())
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _chart_record(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": str(item.get("name") or "SimBrief chart"),
        "name": str(item.get("name") or "SimBrief chart"),
        "category": str(item.get("category") or "other"),
        "url": str(item.get("url") or ""),
        "download_url": str(item.get("download_url") or item.get("url") or ""),
        "remote_url": str(item.get("remote_url") or ""),
        "cached": bool(item.get("cached")),
        "source": "SimBrief image manifest",
    }


def _notam_group_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    result = {"all": len(rows), "departure": 0, "destination": 0, "alternate": 0, "enroute": 0}
    for row in rows:
        key = str(row.get("scope_key") or "enroute")
        if key in result:
            result[key] += 1
    return result


def _nms_live_briefing(plan: dict[str, Any]) -> dict[str, Any]:
    """v0.25.60: FAA NMS live NOTAM enrichment for the current flight.

    Pure additive: SimBrief ``notams`` are never replaced. The NMS provider
    is an optional source that is only consulted when the integration is
    enabled and a shared token is configured, and any failure degrades to
    ``{"ok": False}`` -- the frontend keeps the flight-plan NOTAMs.
    """
    empty = {"ok": False, "enabled": False, "notams": [], "groups": {}, "sources": [], "state": "disabled"}
    # v0.25.68: the server-side NOTAM store (opsroom.live) is PUBLIC -- it
    # needs no OPSROOM_NMS_TOKEN, so the DB-first live enrichment runs even
    # when the NMS proxy integration is unconfigured. Only the NMS *proxy*
    # fallback (when the store is unreachable) still requires the token;
    # without one it degrades to the unavailable state instead of silently
    # showing 0 live NOTAMs (the v0.25.68 regression the user hit).
    try:
        origin = (plan.get("origin") or {}).get("icao") or ""
        destination = (plan.get("destination") or {}).get("icao") or ""
        alternates = [
            (item.get("icao") or "") for item in (plan.get("alternates") or []) if isinstance(item, dict)
        ]
        if not origin and not destination:
            return empty
        # v0.25.65: database first (server-side NOTAM store -- zero FAA
        # quota), with the proxy client as the fallback while the store is
        # still deploying. v0.25.68: the proxy fallback is gated on the NMS
        # token being configured -- calling it without one just wastes a
        # request and returns the same unavailable state.
        package = notam_client.route_notams(origin, destination, alternates)
        # v0.25.68: route_notams reports total failure as ok=True with
        # state="unavailable" (never ok=False once codes exist), so gate the
        # NMS proxy fallback on state too -- otherwise it is unreachable and
        # a store outage would silently show 0 live NOTAMs on release day.
        if (
            (not package.get("ok") or package.get("state") == "unavailable" or not package.get("notams"))
            and nms_client.nms_enabled()
            and nms_client.nms_configured()
        ):
            package = nms_client.route_notams(origin, destination, alternates)
        if not package.get("ok") or (package.get("state") == "unavailable" and not package.get("notams")):
            return {"ok": False, "enabled": True, "notams": [], "groups": {}, "sources": [], "state": "unavailable", "error": package.get("error")}
        rows = package.get("notams") or []
        # v0.25.65: plain-English expansion for display only; the raw ICAO text
        # stays available on each row for anyone who wants the original.
        for row in rows:
            if isinstance(row, dict):
                translated = notam_translate.expand(row.get("text"))
                if translated.strip() != str(row.get("text") or "").strip():
                    row["translated_text"] = translated
        return {
            "ok": True,
            "enabled": True,
            "notams": rows,
            "groups": _notam_group_counts(rows),
            "sources": package.get("sources") or [],
            "state": package.get("state", "ok"),
            "count": package.get("count", len(rows)),
        }
    except Exception as exc:
        return {"ok": False, "enabled": True, "notams": [], "groups": {}, "sources": [], "state": "unavailable", "error": type(exc).__name__}


def _geo_only_briefing() -> dict[str, Any]:
    """Position-based NOTAM briefing for when no SimBrief OFP is loaded.

    v0.25.67: reads the user aircraft position and returns NOTAMs within the
    closure-marker radius (same geo pipeline the deploy control uses), so the
    Briefing -> NOTAMS tab is never silently empty without an OFP. Returns
    the exact ``operational_briefing`` shape; the OFP-less fallback keeps the
    original reason when the simulator has no position.
    """
    empty = {"ok": False, "reason": "No SimBrief OFP is loaded", "notams": [], "notam_groups": {},
             "notams_live": [], "notam_groups_live": {}, "notams_live_state": {"enabled": False, "state": "disabled", "count": 0},
             "hazards": {"sections": []}, "sigmets": [], "sigwx": {"charts": []}, "charts": [], "sources": []}
    try:
        from . import notam_client, simconnect_position

        pos = simconnect_position.read_position(force=False)
        if not isinstance(pos, dict) or not pos.get("ok"):
            return empty
        radius = 50.0
        try:
            from . import closure_markers

            radius = closure_markers.marker_radius_nm()
        except Exception:  # pragma: no cover - defensive
            pass
        result = notam_client.get_notams_near(float(pos.get("lat") or 0.0), float(pos.get("lon") or 0.0), radius)
        rows = result.get("notams") if isinstance(result, dict) else None
        if not rows:
            return empty
        source = {"name": "aircraft-position geo NOTAMs", "state": "ok", "notams": len(rows),
                  "sigmets": 0, "sigwx": 0, "charts": 0, "updates": {}, "generated_utc": None}
        return {
            "ok": True,
            "reason": "No SimBrief OFP loaded - showing NOTAMs near the aircraft position",
            "flight": None,
            "notams": rows,
            "notam_groups": _notam_group_counts(rows),
            "notams_live": rows,
            "notam_groups_live": _notam_group_counts(rows),
            "notams_live_state": {"enabled": False, "state": "ok", "count": len(rows)},
            "hazards": {"sections": []},
            "sigmets": [],
            "sigwx": {"charts": []},
            "charts": [],
            "sources": [source],
        }
    except Exception as exc:  # pragma: no cover - defensive status path
        empty["reason"] = f"No SimBrief OFP is loaded ({type(exc).__name__})"
        return empty


def operational_briefing(force: bool = False) -> dict[str, Any]:
    global _CACHE, _CACHE_MONO, _CACHE_KEY
    plan = _current_plan()
    if not plan:
        # v0.25.67: without a loaded SimBrief OFP the Briefing -> NOTAMS tab
        # used to show 0 NOTAMs even while the aircraft sat at an airport
        # with active closures (and the closure-marker deploy was empty with
        # it). Fall back to position-based NOTAMs so both stay useful.
        return _geo_only_briefing()

    cache_key = _plan_fingerprint(plan)
    now = time.monotonic()
    with _LOCK:
        if not force and _CACHE is not None and _CACHE_KEY == cache_key and now - _CACHE_MONO < _CACHE_TTL:
            return dict(_CACHE)

    identifiers = _flight_identifiers(plan)
    briefing = plan.get("briefing") if isinstance(plan.get("briefing"), dict) else {}
    structured_notams = [dict(row) for row in briefing.get("notams") or [] if isinstance(row, dict)]
    hazard_data = briefing.get("hazards") if isinstance(briefing.get("hazards"), dict) else {"sections": []}
    hazard_sections = [dict(section) for section in hazard_data.get("sections") or [] if isinstance(section, dict)]
    manifest = [_chart_record(item) for item in briefing.get("charts") or [] if isinstance(item, dict)]
    updates = dict(briefing.get("database_updates") or {})

    path = _pdf_path(plan)
    package: dict[str, Any] = {"ok": False, "reason": "The cached SimBrief PDF is unavailable", "notams": [], "sigmets": [], "sigwx_pages": []}
    needs_pdf = not structured_notams or not any(item.get("category") == "sigwx" for item in manifest) or not hazard_sections
    if path and needs_pdf:
        package = _extract_pdf_package(path)

    fallback_notams, fallback_sigmets = _extract_plan_text_fallback(plan)
    notams = structured_notams or ((package.get("notams") or []) if package.get("ok") else fallback_notams)

    if not hazard_sections:
        sigmet_rows = (package.get("sigmets") or []) if package.get("ok") else fallback_sigmets
        states = package.get("sigmet_states") or {}
        hazard_sections = [
            {"key": "airmet", "label": "AIRMET", "state": "not_included", "items": []},
            {"key": "sigmet", "label": "SIGMET", "state": "available" if sigmet_rows else states.get("SIGMET", "none"), "items": sigmet_rows},
            {"key": "tropical_cyclone", "label": "Tropical cyclone SIGMET", "state": states.get("Tropical cyclone SIGMET", "none"), "items": []},
            {"key": "volcanic_ash", "label": "Volcanic ash SIGMET", "state": states.get("Volcanic ash SIGMET", "none"), "items": []},
        ]

    sigwx_charts = [item for item in manifest if item.get("category") == "sigwx"]
    other_charts = [item for item in manifest if item.get("category") != "sigwx"]
    sigwx_pages = [int(value) for value in package.get("sigwx_pages") or []]
    if not sigwx_charts and sigwx_pages:
        sigwx_charts = [
            {
                "label": f"SIGWX {index} of {len(sigwx_pages)}",
                "name": f"SIGWX {index} of {len(sigwx_pages)}",
                "category": "sigwx",
                "page": page,
                "url": f"/api/briefing/simbrief-page/{page}.png",
                "download_url": f"/api/briefing/simbrief-page/{page}.png",
                "cached": True,
                "source": "SimBrief OFP PDF fallback",
            }
            for index, page in enumerate(sigwx_pages, start=1)
        ]

    sigmets = []
    for section in hazard_sections:
        if str(section.get("key")) == "sigmet":
            sigmets = [dict(row) for row in section.get("items") or [] if isinstance(row, dict)]
            break

    notams = _dedupe(notams)
    sigmets = _dedupe(sigmets)

    # v0.25.60: FAA NMS live NOTAM enrichment. Additive only -- the SimBrief
    # ``notams`` array above is never replaced. The frontend selects the
    # default source (Live when available, otherwise Flight plan).
    nms_live = _nms_live_briefing(plan)
    live_notams = [dict(row) for row in (nms_live.get("notams") or []) if isinstance(row, dict)]

    source = {
        "name": "SimBrief OFP data",
        "state": "ok",
        "notams": len(notams),
        "sigmets": len(sigmets),
        "sigwx": len(sigwx_charts),
        "charts": len(other_charts),
        "updates": updates,
        "generated_utc": plan.get("generated_utc"),
    }
    files = plan.get("files") if isinstance(plan.get("files"), dict) else {}
    result = {
        "ok": True,
        "generated_utc": _utc(),
        "flight": {"callsign": plan.get("callsign"), "identifiers": identifiers, "route": plan.get("route")},
        "notams": notams,
        "notam_groups": _notam_group_counts(notams),
        "notams_live": live_notams,
        "notam_groups_live": _notam_group_counts(live_notams),
        "notams_live_state": {
            "enabled": bool(nms_live.get("enabled")),
            "state": nms_live.get("state", "disabled"),
            "count": len(live_notams),
            "error": nms_live.get("error"),
        },
        "hazards": {"sections": hazard_sections},
        "sigmets": sigmets,
        "sigmet_summary": "No current SIGMETs were included in the SimBrief route briefing." if not sigmets else "",
        "sigwx": {
            "charts": sigwx_charts,
            "source": "SimBrief image manifest" if any(item.get("source") == "SimBrief image manifest" for item in sigwx_charts) else "SimBrief OFP PDF fallback",
            "message": "" if sigwx_charts else "No SIGWX images were included in the current SimBrief OFP.",
        },
        "charts": other_charts,
        "database_updates": updates,
        "pdf": {
            "available": bool(path),
            "cache_pending": bool(files.get("pdf")) and not bool(path),
            "page_count": package.get("page_count"),
            "notam_pages": package.get("notam_pages") or [],
            "sigmet_page": package.get("sigmet_page"),
            "sigwx_pages": sigwx_pages,
        },
        "sources": [source],
    }
    if nms_live.get("sources"):
        result["sources"].extend([dict(item) for item in nms_live["sources"] if isinstance(item, dict)])
    with _LOCK:
        _CACHE = result
        _CACHE_MONO = now
        _CACHE_KEY = cache_key
    return dict(result)


def simbrief_pdf_page_png(page_number: int, scale: float = 1.7) -> bytes:
    plan = _current_plan()
    if not plan:
        raise FileNotFoundError("No SimBrief OFP is loaded")
    path = _pdf_path(plan)
    if not path:
        raise FileNotFoundError("The cached SimBrief PDF is unavailable")
    try:
        import pymupdf
    except Exception as exc:
        raise RuntimeError("PDF rendering support is unavailable") from exc

    stat = path.stat()
    page_number = int(page_number)
    key = (str(path.resolve()), int(stat.st_mtime_ns), page_number)
    with _LOCK:
        cached = _PAGE_CACHE.get(key)
        if cached:
            return cached
    document = pymupdf.open(path)
    try:
        if page_number < 1 or page_number > document.page_count:
            raise IndexError("SimBrief PDF page is out of range")
        pixmap = document[page_number - 1].get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        content = pixmap.tobytes("png")
    finally:
        document.close()
    with _LOCK:
        if len(_PAGE_CACHE) > 12:
            _PAGE_CACHE.clear()
        _PAGE_CACHE[key] = content
    return content
