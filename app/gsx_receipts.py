from __future__ import annotations

import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CATEGORIES = ("Handling", "Fuel", "Catering", "PassengerBus")
# GSX receipts can be issued in local airport currencies.  Match the longest
# decorated symbols first so e.g. GI£ is preserved as GIP instead of being
# mislabelled as GBP merely because it contains a pound sign.
_SYMBOL_TO_CODE = {
    "GI£": "GIP", "GIP": "GIP", "US$": "USD", "CA$": "CAD",
    "AU$": "AUD", "NZ$": "NZD", "HK$": "HKD", "SG$": "SGD",
    "€": "EUR", "$": "USD", "£": "GBP", "EUR": "EUR",
    "USD": "USD", "GBP": "GBP", "CAD": "CAD", "AUD": "AUD",
    "NZD": "NZD", "HKD": "HKD", "SGD": "SGD",
}
_CURRENCY_TOKEN = r"(?:GI£|GIP|US\$|CA\$|AU\$|NZ\$|HK\$|SG\$|EUR|USD|GBP|CAD|AUD|NZD|HKD|SGD|€|\$|£)"
_AMOUNT_RE = re.compile(rf"({_CURRENCY_TOKEN})\s*([0-9][0-9, .]*)", re.I)
_TOTAL_RE = re.compile(rf"\bTOTAL\b\s*({_CURRENCY_TOKEN})\s*([0-9][0-9, .]*)", re.I)
_APPROX_RE = re.compile(rf"[~≈]\s*({_CURRENCY_TOKEN})\s*([0-9][0-9, .]*)", re.I)
_FILENAME_TS_RE = re.compile(r"^(\d{8}T\d{6}Z)_([A-Z0-9]{4})_(.+)$", re.I)


def _receipts_candidates() -> list[Path]:
    """Alternative GSX Pro receipt locations probed when the default is absent.

    GSX updates have moved the receipts folder in the past; probing known
    alternatives before falling back to the default keeps receipt detection
    working even when a new GSX build relocates the directory.
    """
    candidates: list[Path] = []
    local = os.getenv("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Virtuali" / "GSX" / "Receipts")
    program = os.getenv("PROGRAMDATA")
    if program:
        candidates.append(Path(program) / "Virtuali" / "GSX" / "Receipts")
    candidates.append(Path.home() / "AppData" / "Roaming" / "Virtuali" / "GSX" / "Receipts")
    return candidates


def receipts_root() -> Path:
    """Locate the GSX Pro receipts directory.

    The default GSX layout is %APPDATA%\\Virtuali\\GSX\\Receipts. A settings
    override (``integrations.gsx_receipts_dir``, mirroring the existing
    ``integrations.fenix_efb_url`` pattern) takes precedence; if the resolved
    directory is absent, known alternative layouts are probed so a GSX update
    that relocates the folder does not silently break receipt detection again.
    """
    try:
        from .settings_store import load_settings

        override = str((load_settings().get("integrations", {}) or {}).get("gsx_receipts_dir") or "").strip()
        if override:
            path = Path(override).expanduser()
            if path.is_dir():
                return path
    except Exception:
        pass
    appdata = os.getenv("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    primary = base / "Virtuali" / "GSX" / "Receipts"
    if primary.is_dir():
        return primary
    for candidate in _receipts_candidates():
        if candidate.is_dir():
            return candidate
    return primary


def _utc_from_epoch(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


def _epoch(value: Any) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _normalise_registration(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _money_number(raw: Any) -> float | None:
    value = str(raw or "").strip().replace(" ", "")
    if not value:
        return None
    if "," in value and "." in value:
        value = value.replace(",", "")
    elif "," in value:
        parts = value.split(",")
        value = ".".join(parts) if len(parts[-1]) == 2 else "".join(parts)
    try:
        number = float(value)
        return number if number >= 0 else None
    except Exception:
        return None


def _timestamp_from_stem(stem: str, fallback: float) -> tuple[float, str, str]:
    match = _FILENAME_TS_RE.match(stem)
    if not match:
        return fallback, "", ""
    try:
        stamp = datetime.strptime(match.group(1).upper(), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        stamp = fallback
    return stamp, match.group(2).upper(), match.group(3)


def _phase_for(stamp: float, takeoff: float | None, landing: float | None) -> str:
    # Service receipts are commonly issued well before block-out and shortly
    # before/after block-in.  Airport identity is applied by the caller first;
    # these time anchors are the fallback for receipts with incomplete metadata.
    if landing is not None and stamp >= landing - 30.0 * 60.0:
        return "arrival"
    if takeoff is not None and stamp <= takeoff + 15.0 * 60.0:
        return "departure"
    if takeoff is not None and landing is not None:
        return "departure" if stamp < (takeoff + landing) / 2.0 else "arrival"
    return "unknown"


def _json_money(value: Any) -> tuple[float | None, str, str]:
    if isinstance(value, dict):
        amount = _money_number(value.get("amount") if "amount" in value else value.get("value"))
        currency = str(value.get("currency") or value.get("code") or "").upper()
        display = str(value.get("display") or value.get("formatted") or "")
        return amount, currency, display
    if isinstance(value, (int, float)):
        return float(value), "", ""
    text = str(value or "")
    match = _AMOUNT_RE.search(text)
    if match:
        code = _SYMBOL_TO_CODE.get(match.group(1), match.group(1).upper())
        return _money_number(match.group(2)), code, text.strip()
    return _money_number(text), "", text.strip()


def _parse_json(path: Path, html_path: Path | None = None) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    if not isinstance(data, dict):
        raise ValueError("GSX receipt JSON is not an object")
    stat = path.stat()
    stamp, filename_icao, filename_tail = _timestamp_from_stem(path.stem, stat.st_mtime)
    total, currency, display = _json_money(data.get("total"))
    subtotal, subtotal_currency, _ = _json_money(data.get("subtotal"))
    if not currency:
        currency = subtotal_currency
    approx_amount = None
    approx_currency = ""
    # GSX stores the billed local total and its approximate reference value in
    # the total display string (for example "€105.27 ~$120.33"). The separate
    # FX disclosure contains only the exchange rate, so inspect the total first.
    approx = _APPROX_RE.search(display or str(data.get("total") or ""))
    if not approx:
        fx_text = str(data.get("fxDisclosure") or data.get("fx_disclosure") or "")
        approx = _APPROX_RE.search(fx_text)
    if approx:
        approx_currency = _SYMBOL_TO_CODE.get(approx.group(1), approx.group(1).upper())
        approx_amount = _money_number(approx.group(2))
    line_items: list[dict[str, Any]] = []
    for row in data.get("items") or []:
        if not isinstance(row, dict):
            continue
        amount, row_currency, row_display = _json_money(row.get("amount"))
        line_items.append({
            "item": str(row.get("description") or row.get("item") or row.get("name") or "Service")[:120],
            "qty": str(row.get("qty") or row.get("quantity") or "")[:50],
            "unit_price": str(row.get("unitPrice") or row.get("unit_price") or "")[:60],
            "amount": round(amount, 2) if amount is not None else None,
            "currency": row_currency or currency,
            "display_amount": row_display,
        })
    taxes: list[dict[str, Any]] = []
    for tax in data.get("taxes") or []:
        if not isinstance(tax, dict):
            continue
        amount, tax_currency, _ = _json_money(tax.get("amount"))
        taxes.append({
            "label": str(tax.get("label") or tax.get("name") or "Tax")[:80],
            "rate": tax.get("rate"),
            "amount": round(amount, 2) if amount is not None else None,
            "currency": tax_currency or currency,
            "reason": str(tax.get("reason") or "")[:160],
        })
    category = path.parent.name
    html_name = html_path.name if html_path and html_path.is_file() else ""
    return {
        "category": category,
        "filename": html_name or path.name,
        "json_filename": path.name,
        "receipt_id": str(data.get("receiptId") or data.get("receipt_id") or path.stem),
        "operator": str(data.get("operator") or category),
        "airline": str(data.get("airline") or ""),
        "airport": str(data.get("icao") or filename_icao).upper(),
        "airport_name": str(data.get("airportName") or data.get("airport_name") or ""),
        "tail": str(data.get("tail") or filename_tail).upper(),
        "aircraft_type": str(data.get("aircraftType") or data.get("aircraft_type") or ""),
        "callsign": str(data.get("callsign") or ""),
        "service": category,
        "title": str(data.get("title") or f"{category} receipt"),
        "amount": round(total, 2) if total is not None else None,
        "currency": currency,
        "display_amount": display or (f"{currency} {total:,.2f}" if total is not None and currency else ""),
        "subtotal": round(subtotal, 2) if subtotal is not None else None,
        "taxes": taxes,
        "approx_amount": round(approx_amount, 2) if approx_amount is not None else None,
        "approx_currency": approx_currency,
        "converted_amount": round(total, 2) if total is not None and not approx_currency else None,
        "line_items": line_items,
        "service_info": data.get("serviceInfoRows") or data.get("service_info") or [],
        "issued_utc": _utc_from_epoch(stamp),
        "modified_utc": _utc_from_epoch(stat.st_mtime),
        "source_format": "json",
        "url": f"/api/gsx/receipts/{category}/{html_name}" if html_name else "",
    }


def _clean_cell(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))).strip()


def _parse_html(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="ignore")[:500000]
    plain = _clean_cell(text)
    stat = path.stat()
    stamp, airport, tail = _timestamp_from_stem(path.stem, stat.st_mtime)
    title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    title = _clean_cell(title_match.group(1)) if title_match else path.parent.name
    total_match = _TOTAL_RE.search(plain)
    amount = _money_number(total_match.group(2)) if total_match else None
    currency = _SYMBOL_TO_CODE.get(total_match.group(1), total_match.group(1).upper()) if total_match else ""
    approx = _APPROX_RE.search(plain[total_match.end(): total_match.end()+160] if total_match else plain)
    operator = title.split(" - ")[-1].strip() if " - " in title else title
    return {
        "category": path.parent.name, "filename": path.name, "json_filename": "",
        "receipt_id": path.stem, "operator": operator, "airline": "", "airport": airport,
        "tail": tail.upper(), "aircraft_type": "", "callsign": "", "service": path.parent.name,
        "title": title, "amount": round(amount, 2) if amount is not None else None,
        "currency": currency, "display_amount": f"{currency} {amount:,.2f}" if amount is not None else "",
        "subtotal": None, "taxes": [], "approx_amount": _money_number(approx.group(2)) if approx else None,
        "approx_currency": _SYMBOL_TO_CODE.get(approx.group(1), approx.group(1).upper()) if approx else "",
        "converted_amount": round(amount, 2) if amount is not None and not approx else None,
        "line_items": [], "service_info": [], "issued_utc": _utc_from_epoch(stamp),
        "modified_utc": _utc_from_epoch(stat.st_mtime), "source_format": "html",
        "url": f"/api/gsx/receipts/{path.parent.name}/{path.name}",
    }


def parse_receipt(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".json":
        html_path = path.with_suffix(".html")
        return _parse_json(path, html_path if html_path.is_file() else None)
    json_path = path.with_suffix(".json")
    if json_path.is_file():
        return _parse_json(json_path, path)
    return _parse_html(path)


def _iter_receipts(root: Path) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    if not root.is_dir():
        return receipts
    for category in CATEGORIES:
        folder = root / category
        if not folder.is_dir():
            continue
        stems = {path.stem for path in folder.glob("*.json")} | {path.stem for path in folder.glob("*.html")}
        for stem in stems:
            json_path, html_path = folder / f"{stem}.json", folder / f"{stem}.html"
            try:
                receipts.append(parse_receipt(json_path if json_path.is_file() else html_path))
            except Exception as exc:
                fallback = json_path if json_path.is_file() else html_path
                try:
                    stat = fallback.stat()
                    receipts.append({"category": category, "filename": html_path.name if html_path.is_file() else fallback.name,
                                     "json_filename": json_path.name if json_path.is_file() else "", "operator": category,
                                     "service": category, "amount": None, "currency": "", "line_items": [],
                                     "modified_utc": _utc_from_epoch(stat.st_mtime), "issued_utc": _utc_from_epoch(stat.st_mtime),
                                     "source_format": fallback.suffix.lstrip("."), "parse_error": f"{type(exc).__name__}: {exc}",
                                     "url": f"/api/gsx/receipts/{category}/{html_path.name}" if html_path.is_file() else ""})
                except Exception:
                    pass
    return receipts


def recent_invoice_items(start_utc: str | None, end_utc: str | None, limit: int = 30, *,
                         takeoff_utc: str | None = None, landing_utc: str | None = None,
                         origin: str = "", destination: str = "", tail: str = "") -> list[dict[str, Any]]:
    start = _epoch(start_utc) or 0.0
    end = _epoch(end_utc) or datetime.now(timezone.utc).timestamp()
    takeoff, landing = _epoch(takeoff_utc), _epoch(landing_utc)
    origin, destination, tail = origin.upper(), destination.upper(), _normalise_registration(tail)

    # Recorder start is not the start of the ground operation: catering, fuel
    # and handling receipts can be issued hours before pushback.  Likewise an
    # arrival invoice can be written after block-in while post-flight services
    # finish.  Use an operational window and then require airport/tail identity.
    departure_anchor = takeoff if takeoff is not None else start
    arrival_anchor = landing if landing is not None else end
    window_start = min(start, departure_anchor) - 3.0 * 60.0 * 60.0
    window_end = max(end, arrival_anchor) + 3.0 * 60.0 * 60.0

    items: list[dict[str, Any]] = []
    for raw_item in _iter_receipts(receipts_root()):
        stamp = _epoch(raw_item.get("issued_utc") or raw_item.get("modified_utc")) or 0.0
        if not (window_start <= stamp <= window_end):
            continue
        receipt_airport = str(raw_item.get("airport") or "").upper()
        receipt_tail = _normalise_registration(raw_item.get("tail"))
        if tail and receipt_tail and tail != receipt_tail:
            continue
        if (origin or destination) and receipt_airport and receipt_airport not in {origin, destination}:
            continue

        item = dict(raw_item)
        if receipt_airport and origin and destination and origin != destination:
            if receipt_airport == origin:
                phase = "departure"
            elif receipt_airport == destination:
                phase = "arrival"
            else:
                phase = _phase_for(stamp, takeoff, landing)
        else:
            phase = _phase_for(stamp, takeoff, landing)
        if phase == "unknown" and receipt_airport:
            phase = "arrival" if destination and receipt_airport == destination and destination != origin else "departure"
        item["phase"] = phase
        item["match_basis"] = "registration + airport + operational time window"
        items.append(item)
    items.sort(key=lambda x: x.get("issued_utc") or x.get("modified_utc") or "")
    return items[-max(1, min(int(limit), 100)):]


def list_receipts(limit: int = 60) -> dict[str, Any]:
    root = receipts_root()
    items = _iter_receipts(root)
    items.sort(key=lambda x: x.get("issued_utc") or x.get("modified_utc") or "", reverse=True)
    return {"ok": True, "root": str(root), "root_available": root.is_dir(), "count": len(items),
            "categories": {category: (root / category).is_dir() for category in CATEGORIES},
            "items": items[:max(1, min(int(limit), 200))]}


def receipt_file(category: str, filename: str) -> Path:
    if category not in CATEGORIES or not re.fullmatch(r"[A-Za-z0-9 _.-]+\.html", filename or "", re.I):
        raise ValueError("Invalid receipt path")
    root = receipts_root().resolve()
    path = (root / category / filename).resolve()
    if root not in path.parents or not path.is_file():
        raise FileNotFoundError("GSX receipt not found")
    return path
