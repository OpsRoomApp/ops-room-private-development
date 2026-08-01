from __future__ import annotations

import io
import re
import socket
from typing import Any
from urllib.parse import quote

import qrcode

from .device_security import pairing_code
from .settings_store import load_settings


def lan_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            address = sock.getsockname()[0]
            if address and not address.startswith(("127.", "169.254.")):
                addresses.add(address)
    except OSError:
        pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if address and not address.startswith(("127.", "169.254.")):
                addresses.add(address)
    except OSError:
        pass
    return sorted(addresses)


def mask_url(url: str) -> str:
    def replace(match: re.Match[str]) -> str:
        parts = match.group(0).split(".")
        return ".".join([parts[0], "***", "***", parts[-1]])
    return re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", replace, str(url or ""))


def build_server_info() -> dict[str, Any]:
    settings = load_settings()
    server = settings.get("server", {})
    port = int(server.get("port", 8080))
    lan_enabled = bool(server.get("lan_access", False))
    security_enabled = bool(server.get("device_security_enabled", False))
    local_url = f"http://127.0.0.1:{port}"
    lan_urls = [f"http://{address}:{port}" for address in lan_ipv4_addresses()]
    preferred_url = lan_urls[0] if lan_enabled and lan_urls else local_url
    pair_code = pairing_code() if security_enabled else ""
    qr_url = f"{preferred_url}/pair?code={quote(pair_code)}" if security_enabled and lan_enabled and lan_urls else preferred_url
    return {
        "ok": True,
        "lan_enabled": lan_enabled,
        "port": port,
        "local_url": local_url,
        "lan_urls": lan_urls,
        "preferred_url": preferred_url,
        "masked_local_url": mask_url(local_url),
        "masked_lan_urls": [mask_url(x) for x in lan_urls],
        "masked_preferred_url": mask_url(preferred_url),
        "tablet_ready": bool(lan_enabled and lan_urls),
        "device_security_enabled": security_enabled,
        "pairing_required": bool(security_enabled and lan_enabled),
        "pairing_code": pair_code,
        "trusted_device_days": int(server.get("trusted_device_days", 180) or 180),
        "qr_url": qr_url,
    }


def qr_png(url: str) -> bytes:
    code = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
    code.add_data(url)
    code.make(fit=True)
    image = code.make_image(fill_color="black", back_color="white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
