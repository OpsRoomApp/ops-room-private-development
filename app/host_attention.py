from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


def flash_host() -> dict:
    if os.name != "nt":
        return {"ok": False, "supported": False, "reason": "Windows taskbar attention is available in the packaged Windows host"}
    user32 = ctypes.windll.user32
    handles = []
    EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @EnumProc
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.upper()
        if "OPS ROOM" in title:
            handles.append(hwnd)
        return True

    user32.EnumWindows(callback, 0)
    class FLASHWINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND), ("dwFlags", wintypes.DWORD), ("uCount", wintypes.UINT), ("dwTimeout", wintypes.DWORD)]
    for hwnd in handles:
        info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 0x00000003 | 0x0000000C, 5, 0)  # caption + taskbar + until foreground
        user32.FlashWindowEx(ctypes.byref(info))
    return {"ok": bool(handles), "supported": True, "windows": len(handles)}
