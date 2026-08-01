from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

from .settings_store import load_settings
from .announcements import status as announcement_status

BACKGROUND_NAMES = ("bg.png", "bg.jpg", "bg.jpeg", "background.png", "background.jpg", "background.jpeg")


def _safe_root() -> Path | None:
    raw = str(load_settings().get("integrations", {}).get("announcements_root") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_dir() else None


def _clean_airline(value: Any) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())[:4]


def airline_background_file() -> Path | None:
    settings = load_settings()
    interface = settings.get("interface", {})
    if interface.get("airline_theme_enabled", True) is False or str(interface.get("airline_theme_mode", "full") or "full").lower() == "off":
        return None
    root = _safe_root()
    if not root:
        return None
    try:
        ann = announcement_status()
    except Exception:
        ann = {}
    airline = _clean_airline(ann.get("airline") or settings.get("integrations", {}).get("announcements_airline_override"))
    folders: list[Path] = []
    if airline:
        folders.append(root / airline)
    folders.extend([root / "Default", root / "DEFAULT", root])
    seen: set[str] = set()
    for folder in folders:
        key = str(folder).lower()
        if key in seen or not folder.is_dir():
            continue
        seen.add(key)
        for name in BACKGROUND_NAMES:
            candidate = folder / name
            if candidate.is_file():
                return candidate
    return None


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{max(0, min(255, int(v))):02x}" for v in rgb)


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(round(a[i] * (1 - factor) + b[i] * factor) for i in range(3))  # type: ignore[return-value]


@lru_cache(maxsize=32)
def _palette(path: str, mtime: int, size: int) -> dict[str, str]:
    try:
        from PIL import Image  # type: ignore
        image = Image.open(path).convert("RGB")
        image.thumbnail((160, 160))
        pixels = list(image.getdata())
        if not pixels:
            raise ValueError("empty image")
        # Prefer saturated / bright pixels so a red/orange airline EFB background becomes the accent.
        def score(px: tuple[int, int, int]) -> float:
            r, g, b = px
            mx, mn = max(px), min(px)
            sat = mx - mn
            lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
            return sat * 1.8 + lum * 0.35
        chosen = sorted(pixels, key=score, reverse=True)[: max(20, len(pixels) // 8)]
        r = int(sum(p[0] for p in chosen) / len(chosen))
        g = int(sum(p[1] for p in chosen) / len(chosen))
        b = int(sum(p[2] for p in chosen) / len(chosen))
        accent = (r, g, b)
    except Exception:
        accent = (113, 180, 195)
    pale = _mix(accent, (255, 255, 255), 0.42)
    dark = _mix(accent, (6, 8, 9), 0.88)
    panel = _mix(accent, (16, 18, 20), 0.82)
    line = _mix(accent, (89, 103, 109), 0.58)
    return {
        "accent": _hex(accent),
        "accent_pale": _hex(pale),
        "background": _hex(dark),
        "panel": _hex(panel),
        "line": _hex(line),
    }


def theme_status() -> dict[str, Any]:
    settings = load_settings()
    interface = settings.get("interface", {})
    enabled = interface.get("airline_theme_enabled", True) is not False
    mode = str(interface.get("airline_theme_mode", "full") or "full").strip().lower()
    if mode not in {"off", "accent", "full"}:
        mode = "full"
    try:
        intensity = int(interface.get("airline_theme_intensity", 38))
    except (TypeError, ValueError):
        intensity = 38
    intensity = max(0, min(intensity, 100))
    background = airline_background_file() if enabled and mode != "off" else None
    ann = {}
    try:
        ann = announcement_status()
    except Exception:
        pass
    if not background:
        return {
            "ok": True,
            "enabled": bool(enabled),
            "mode": mode,
            "intensity": intensity,
            "active": False,
            "airline": _clean_airline(ann.get("airline")) or "DEFAULT",
            "reason": "No airline background found" if enabled and mode != "off" else "Airline theme disabled",
        }
    stat = background.stat()
    palette = _palette(str(background), int(stat.st_mtime), int(stat.st_size))
    digest = hashlib.sha1(f"{background}|{stat.st_mtime_ns}|{stat.st_size}".encode("utf-8")).hexdigest()[:12]
    visible = intensity / 100.0
    start_alpha = max(0.34, 0.88 - visible * 0.42)
    end_alpha = max(0.46, 0.94 - visible * 0.36)
    return {
        "ok": True,
        "enabled": True,
        "mode": mode,
        "intensity": intensity,
        "active": True,
        "airline": _clean_airline(ann.get("airline")) or background.parent.name.upper()[:4],
        "source": str(background),
        "background_url": f"/api/interface/theme/background?token={digest}",
        "overlay_start": f"rgba(8, 10, 7, {start_alpha:.2f})",
        "overlay_end": f"rgba(8, 10, 7, {end_alpha:.2f})",
        **palette,
    }
