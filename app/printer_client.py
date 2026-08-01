from __future__ import annotations

import ctypes
import logging
import os
from ctypes import wintypes, c_ubyte, c_ulong, byref, create_string_buffer
from datetime import datetime, timezone
from typing import Any

_LOGGER = logging.getLogger("opsroom.printer")

# Windows GDI printer APIs via ctypes (no pywin32 required).
# Lazily loaded so PyInstaller does not crash at import time.
_winspool = None

PRINTER_ENUM_LOCAL = 0x00000002
PRINTER_ENUM_CONNECTIONS = 0x00000004


def _get_winspool():
    """Lazy-load winspool.drv; returns the CDLL or None."""
    global _winspool
    if _winspool is None:
        try:
            _winspool = ctypes.windll.winspool
        except (AttributeError, OSError, TypeError) as exc:
            _LOGGER.warning("winspool.drv not available: %s", exc)
            _winspool = False  # sentinel — don't retry
    return _winspool if _winspool is not False else None


class PRINTER_INFO_2A(ctypes.Structure):
    _fields_ = [
        ("pServerName", wintypes.LPSTR),
        ("pPrinterName", wintypes.LPSTR),
        ("pShareName", wintypes.LPSTR),
        ("pPortName", wintypes.LPSTR),
        ("pDriverName", wintypes.LPSTR),
        ("pComment", wintypes.LPSTR),
        ("pLocation", wintypes.LPSTR),
        ("pDevMode", ctypes.c_void_p),
        ("pSepFile", wintypes.LPSTR),
        ("pPrintProcessor", wintypes.LPSTR),
        ("pDatatype", wintypes.LPSTR),
        ("pParameters", wintypes.LPSTR),
        ("pSecurityDescriptor", ctypes.c_void_p),
        ("Attributes", ctypes.c_ulong),
        ("Priority", ctypes.c_ulong),
        ("DefaultPriority", ctypes.c_ulong),
        ("StartTime", ctypes.c_ulong),
        ("UntilTime", ctypes.c_ulong),
        ("Status", ctypes.c_ulong),
        ("cJobs", ctypes.c_ulong),
        ("AveragePPM", ctypes.c_ulong),
    ]


def _ensure_utf8(value: str) -> bytes:
    return str(value or "").encode("utf-8", errors="ignore")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def list_printers() -> list[dict[str, Any]]:
    """Enumerate installed Windows printers. Works without pywin32."""
    ws = _get_winspool()
    if ws is None:
        _LOGGER.warning("winspool not available, cannot list printers")
        return []
    try:
        needed = ctypes.c_ulong(0)
        returned = ctypes.c_ulong(0)
        # First call to get buffer size
        ws.EnumPrintersA(
            PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS,
            None, 1, None, 0, byref(needed), byref(returned)
        )
        if not needed.value:
            return []
        buf = create_string_buffer(needed.value)
        if not ws.EnumPrintersA(
            PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS,
            None, 1, buf, needed.value, byref(needed), byref(returned)
        ):
            return []
        printers: list[dict[str, Any]] = []
        ptr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))
        for i in range(returned.value):
            try:
                info = ctypes.cast(ptr[i], ctypes.POINTER(PRINTER_INFO_2A)).contents
                name = info.pPrinterName.decode("utf-8", errors="replace") if info.pPrinterName else ""
                port = info.pPortName.decode("utf-8", errors="replace") if info.pPortName else ""
                driver = info.pDriverName.decode("utf-8", errors="replace") if info.pDriverName else ""
                if name:
                    printers.append({
                        "name": name,
                        "port": port,
                        "driver": driver,
                        "status": info.Status,
                        "jobs": info.cJobs,
                    })
            except Exception:
                continue
        return printers
    except Exception as exc:
        _LOGGER.warning("Failed to enumerate printers: %s", exc)
        return []


def print_text(printer_name: str, text: str, title: str = "OPS ROOM") -> dict[str, Any]:
    """Send plain text to a Windows printer (raw print - works with thermal/POS printers).

    For thermal/POS printers that understand EscPOS, the text is sent as-is.
    For standard printers, Windows wraps it through the driver.
    """
    if not printer_name:
        return {"ok": False, "error": "No printer name specified"}
    if not text:
        return {"ok": False, "error": "No text to print"}

    printer_name_bytes = _ensure_utf8(printer_name)
    doc_name_bytes = _ensure_utf8(title)
    data_bytes = _ensure_utf8(text)

    ws = _get_winspool()
    if ws is None:
        return {"ok": False, "error": "winspool.drv not available on this system"}

    handle = wintypes.HANDLE()
    if not ws.OpenPrinterA(printer_name_bytes, byref(handle), None):
        return {"ok": False, "error": f"Cannot open printer: {printer_name}"}

    try:
        doc_info_1_type = ctypes.c_ubyte * 3
        di1 = (ctypes.c_char_p * 3)(
            doc_name_bytes,          # pDocName
            None,                     # pOutputFile
            b"RAW",                   # pDatatype
        )
        job_id = ws.StartDocPrinterA(handle, 1, di1)
        if not job_id:
            return {"ok": False, "error": "StartDocPrinter failed"}

        try:
            if not ws.StartPagePrinter(handle):
                return {"ok": False, "error": "StartPagePrinter failed"}

            written = ctypes.c_ulong(0)
            if not ws.WritePrinter(handle, data_bytes, len(data_bytes), byref(written)):
                return {"ok": False, "error": "WritePrinter failed"}

            ws.EndPagePrinter(handle)
        finally:
            ws.EndDocPrinter(handle)

        return {"ok": True, "job_id": job_id, "bytes_written": written.value}

    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    finally:
        ws.ClosePrinter(handle)


def print_receipt(
    printer_name: str,
    lines: list[str],
    title: str = "OPS ROOM RECEIPT",
    width: int = 48,
) -> dict[str, Any]:
    """Format and print a receipt-style document.

    For 80mm thermal printers using standard character width (~48 chars per line).
    """
    if not lines:
        return {"ok": False, "error": "No receipt lines to print"}

    sep = "=" * width
    thin = "-" * width

    receipt_lines = [
        sep,
        f"  {title.center(width - 4)}",
        sep,
        _utc().center(width),
        thin,
    ]
    for line in lines:
        receipt_lines.append(str(line).center(width) if not str(line).strip() else str(line))
    receipt_lines.extend([thin, "", ""])

    return print_text(printer_name, "\r\n".join(receipt_lines) + "\r\n", title=title)


def format_cpdlc_receipt(msg: dict[str, Any], width: int = 48) -> list[str]:
    """Format a CPDLC message as receipt lines."""
    direction = msg.get("direction", "IN")
    from_ = str(msg.get("from", "") or "")
    to = str(msg.get("to", "") or "")
    msg_type = str(msg.get("type", "") or "")
    message = str(msg.get("message", "") or "")
    timestamp = str(msg.get("time", "") or _utc())

    lines = [
        f"{'>> RECEIVED <<' if direction == 'IN' else '<< SENT >>'}",
        f"FROM: {from_}",
        f"TO:   {to}",
        f"TYPE: {msg_type.upper()}",
        f"TIME: {timestamp}",
        "-" * width,
    ]
    # Add message body
    if message:
        for line in message.split("\n"):
            for chunk in [line[i:i + width] for i in range(0, len(line), width)]:
                lines.append(chunk)
    return lines


def test_print(printer_name: str) -> dict[str, Any]:
    """Print a test receipt to verify printer connectivity."""
    lines = [
        "OPS ROOM PRINTER TEST",
        "",
        "If you can read this,",
        "your thermal/POS printer",
        "is configured correctly!",
        "",
        "CPDLC messages will auto-print",
        "when the feature is enabled.",
        "",
        f"Tested at: {_utc()}",
    ]
    return print_receipt(printer_name, lines, title="PRINTER TEST")


def status() -> dict[str, Any]:
    """Get printer system status."""
    printers = list_printers()
    return {
        "ok": True,
        "printers_available": len(printers),
        "printers": printers,
        "os": os.name,
        "platform": "Windows" if os.name == "nt" else "Other",
    }


def generate_receipt_preview(content: str, receipt_type: str = "cpdlc", width: int = 42, app_version: str = "") -> dict[str, Any]:
    """Generate an 80mm thermal receipt preview as markdown-formatted text.

    Returns a dict with raw_lines (list of receipt lines) and html (pre-rendered
    HTML block suitable for the printer preview modal).  The frontend renders this
    as a monospaced receipt inside the modal — no actual printing occurs.
    """
    import html as _html

    now = _utc()
    version_label = str(app_version or "OPS ROOM").strip()
    lines: list[str] = []

    # ── Header block ──
    lines.append(version_label.center(width))
    lines.append("THERMAL RECEIPT PREVIEW".center(width))
    lines.append("")
    lines.append(f"TYPE: {receipt_type.upper()}".ljust(width))
    lines.append(f"TIME: {now}".ljust(width))
    lines.append("─" * width)
    lines.append("")

    # ── Body ──
    body = str(content or "").strip()
    if body:
        for paragraph in body.split("\n"):
            if not paragraph.strip():
                lines.append("")
                continue
            for i in range(0, len(paragraph), width):
                chunk = paragraph[i:i + width]
                lines.append(chunk)
    else:
        lines.append("(empty receipt)".center(width))

    # ── Footer ──
    lines.append("")
    lines.append(("- " * (width // 2)).strip().ljust(width))
    lines.append("snip here".center(width))
    lines.append(("- " * (width // 2)).strip().ljust(width))
    lines.append("")
    lines.append("END OF RECEIPT".center(width))
    lines.append("")
    lines.append("OPS ROOM THERMAL PRINTER".center(width))
    lines.append("80mm roll  ·  42 col  ·  Courier".center(width))

    # Build HTML block
    html_parts = ['<div class="printer-receipt" style="background:#f9f6ea;color:#1a1a1a;font-family:Consolas,Courier New,monospace;font-size:11px;line-height:1.35;padding:1.2rem 1rem;width:315px;max-width:100%;margin:0 auto;border:1px solid #ddd;box-shadow:0 2px 12px rgba(0,0,0,.18);white-space:pre-wrap;word-break:break-all;overflow-wrap:anywhere">']
    for line in lines:
        html_parts.append(_html.escape(line))
    html_parts.append('</div>')

    return {
        "ok": True,
        "raw_lines": lines,
        "html": "\n".join(html_parts),
        "line_count": len(lines),
        "width": width,
        "receipt_type": receipt_type,
        "generated_at": now,
    }
