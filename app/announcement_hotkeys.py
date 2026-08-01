from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes
from typing import Any

from .announcements import set_muted, toggle_pause
from .settings_store import load_settings

_THREAD: threading.Thread | None = None
_STOP = threading.Event()

_MODIFIERS = {"ALT": 0x0001, "CTRL": 0x0002, "CONTROL": 0x0002, "SHIFT": 0x0004, "WIN": 0x0008, "WINDOWS": 0x0008}
_KEYS = {"SPACE": 0x20, **{chr(code): code for code in range(ord("A"), ord("Z") + 1)}, **{str(i): ord(str(i)) for i in range(10)}, **{f"F{i}": 0x6F + i for i in range(1, 13)}}


def _parse(combo: Any) -> tuple[int, int] | None:
    parts = [part.strip().upper() for part in str(combo or "").replace("-", "+").split("+") if part.strip()]
    if not parts:
        return None
    modifiers = 0
    key = None
    for part in parts:
        if part in _MODIFIERS:
            modifiers |= _MODIFIERS[part]
        elif part in _KEYS:
            key = _KEYS[part]
        else:
            return None
    return (modifiers, key) if key is not None else None


def _run() -> None:
    if os.name != "nt":
        return
    user32 = ctypes.windll.user32
    msg = wintypes.MSG()
    registered: dict[int, tuple[int, int]] = {}
    signature: tuple[Any, ...] | None = None
    while not _STOP.is_set():
        settings = load_settings().get("integrations", {})
        current_signature = (
            bool(settings.get("announcements_hotkeys_enabled", True)),
            settings.get("announcements_pause_hotkey", "CTRL+ALT+P"),
            settings.get("announcements_mute_hotkey", "CTRL+ALT+M"),
        )
        if current_signature != signature:
            for ident in list(registered):
                try:
                    user32.UnregisterHotKey(None, ident)
                except Exception:
                    pass
            registered.clear()
            signature = current_signature
            if current_signature[0]:
                for ident, combo in ((0x4F50, current_signature[1]), (0x4F51, current_signature[2])):
                    parsed = _parse(combo)
                    if parsed and user32.RegisterHotKey(None, ident, parsed[0] | 0x4000, parsed[1]):
                        registered[ident] = parsed
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            if msg.message == 0x0312:
                if msg.wParam == 0x4F50:
                    toggle_pause()
                elif msg.wParam == 0x4F51:
                    set_muted(None)
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.08)
    for ident in list(registered):
        try:
            user32.UnregisterHotKey(None, ident)
        except Exception:
            pass


def start_hotkey_service() -> None:
    global _THREAD
    if os.name != "nt" or (_THREAD and _THREAD.is_alive()):
        return
    _STOP.clear()
    _THREAD = threading.Thread(target=_run, name="OpsRoom-AnnouncementHotkeys", daemon=True)
    _THREAD.start()



def stop_hotkey_service() -> None:
    _STOP.set()
    try:
        thread = _THREAD
        if thread and thread.is_alive():
            thread.join(timeout=1.5)
    except Exception:
        pass
