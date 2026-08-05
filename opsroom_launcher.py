from __future__ import annotations

import ctypes
import json
import os
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path
from typing import Any

from app.settings_store import app_data_dir, load_settings
from app.logging_utils import RotatingTextLog, log_policy
from app.fsuipc_manager import autostart_if_configured
from app.vpilot_installer import bridge_installation_status, install_bridge
from app.announcements import start_engine as start_announcement_engine, shutdown_engine as shutdown_announcement_engine
from app.announcement_hotkeys import start_hotkey_service, stop_hotkey_service

LOCAL_HOST = "127.0.0.1"


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    candidate = base / relative
    if candidate.exists():
        return candidate
    return Path(__file__).resolve().parent / relative



class Tee:
    def __init__(self, *streams: Any):
        self.streams = [stream for stream in streams if stream is not None]

    @property
    def encoding(self) -> str:
        for stream in self.streams:
            value = getattr(stream, "encoding", None)
            if value:
                return value
        return "utf-8"

    @property
    def errors(self) -> str:
        return "replace"

    def write(self, data: str) -> int:
        for stream in self.streams:
            try:
                stream.write(data)
                stream.flush()
            except (OSError, ValueError):
                continue
        return len(data)

    def flush(self) -> None:
        for stream in self.streams:
            try:
                stream.flush()
            except (OSError, ValueError):
                continue

    def isatty(self) -> bool:
        return False

    def writable(self) -> bool:
        return True


def enable_log_file() -> Path:
    log_dir = app_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "opsroom.log"
    max_bytes, backups = log_policy()
    log_file = RotatingTextLog(log_path, max_bytes=max_bytes, backup_count=backups)
    sys.stdout = Tee(sys.__stdout__, log_file)
    sys.stderr = Tee(sys.__stderr__, log_file)
    return log_path



def enable_high_dpi() -> None:
    """Enable crisp per-monitor rendering before WebView2 creates a window."""
    if os.name != "nt":
        return
    try:
        context = ctypes.c_void_p(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(context):
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def message_box(title: str, message: str, error: bool = False) -> None:
    if os.name == "nt":
        flags = 0x10 if error else 0x40
        try:
            ctypes.windll.user32.MessageBoxW(None, message, title, flags)
            return
        except Exception:
            pass
    print(f"{title}: {message}")


def port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def wait_until_ready(port: int, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((LOCAL_HOST, port), timeout=0.35):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def lan_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            address = sock.getsockname()[0]
            if address and not address.startswith("127."):
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


class ServerThread(threading.Thread):
    def __init__(self, host: str, port: int, *, name: str = "OpsRoom-WebServer", log_level: str = "info"):
        super().__init__(name=name, daemon=True)
        self.host = host
        self.port = port
        self._log_level = log_level
        self.server = None
        self.error: BaseException | None = None

    def run(self) -> None:
        try:
            import uvicorn
            from app.main import app
            config = uvicorn.Config(
                app,
                host=self.host,
                port=self.port,
                log_level=self._log_level,
                use_colors=False,
                access_log=False,
                ws="websockets",
                ws_ping_interval=20.0,
                ws_ping_timeout=20.0,
            )
            self.server = uvicorn.Server(config)
            self.server.run()
        except BaseException as exc:
            self.error = exc
            traceback.print_exc()

    def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True


def _start_ipv6_loopback_server(port: int) -> ServerThread | None:
    """v0.25.19 polish: bind a second uvicorn on ``::1`` so IPv6-only host
    clients can reach the service.

    Best-effort and silent on failure: if the host has no IPv6 stack, port
    8080 is already taken on ::1, or uvicorn cannot start on the second
    bind, the primary 127.0.0.1 server is left untouched and we just print
    a debug line in the log. State (telemetry, recorder, logbook) is shared
    by reference because both threads serve the same FastAPI ``app``.
    """
    if not socket.has_ipv6:
        return None
    if not port_available("::1", port):
        return None
    worker = ServerThread("::1", port, name="OpsRoom-WebServer-IPv6", log_level="warning")
    worker.start()
    return worker


def run_native(url: str) -> None:
    import webview
    webview.create_window(
        "OPS ROOM HOST - Operations Control Centre",
        url=f"{url}/host",
        width=1120,
        height=780,
        min_size=(860, 620),
        resizable=True,
        confirm_close=False,
        background_color="#101214",
    )
    webview.start(debug=False, private_mode=False)



def _tray_image():
    from PIL import Image, ImageDraw
    for rel in ("app/static/opsroom-icon-64.png", "app/static/opsroom-icon-128.png"):
        path = resource_path(rel)
        if path.is_file():
            return Image.open(path).convert("RGBA")
    image = Image.new("RGBA", (64, 64), (16, 18, 20, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 56, 56), outline=(113, 180, 195, 255), width=4)
    draw.polygon([(32, 14), (46, 45), (32, 36), (18, 45)], fill=(232, 228, 223, 255))
    draw.polygon([(32, 46), (38, 54), (26, 54)], fill=(224, 161, 42, 255))
    return image


def run_tray(url: str, server: ServerThread) -> None:
    import pystray

    settings = load_settings()
    start_url = f"{url}/host#settings" if not settings.get("interface", {}).get("setup_completed", False) else url
    webbrowser.open(start_url)

    def open_ops(icon, item=None):
        webbrowser.open(url)

    def open_host(icon, item=None):
        webbrowser.open(f"{url}/host")

    def open_fids(icon, item=None):
        webbrowser.open(f"{url}/vatsim-fids")

    def quit_ops(icon, item=None):
        try:
            shutdown_announcement_engine()
        except Exception:
            pass
        try:
            stop_hotkey_service()
        except Exception:
            pass
        try:
            from app.camera_bridge import stop_bridge as stop_camera_bridge
            stop_camera_bridge()
        except Exception as exc:
            print(f"Camera Bridge cleanup failed safely: {type(exc).__name__}: {exc}")
        server.stop()
        icon.stop()

    icon = pystray.Icon(
        "OPS ROOM",
        _tray_image(),
        "OPS ROOM",
        menu=pystray.Menu(
            pystray.MenuItem("Open OPS ROOM", open_ops, default=True),
            pystray.MenuItem("Open Host Console", open_host),
            pystray.MenuItem("Open VATSIM FIDS", open_fids),
            pystray.MenuItem("Exit OPS ROOM", quit_ops),
        ),
    )
    print("OPS ROOM is running in the Windows notification area.")
    icon.run()

def run_self_test() -> int:
    result: dict[str, Any] = {"ok": True, "checks": []}
    try:
        import app.raas_audio as raas_audio
        status = raas_audio.voice_pack_status()
        result["checks"].append({
            "name": "raas_audio_import_ok",
            "ok": True,
            "module_file": str(Path(getattr(raas_audio, "__file__", "")).resolve()),
            "voice_pack_available": bool(status.get("available")),
            "clip_count": int(status.get("clip_count") or 0),
            "path": status.get("path") or "",
        })
    except Exception as exc:
        result["ok"] = False
        result["checks"].append({"name": "raas_audio_import_ok", "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    try:
        import app.raas as raas
        result["checks"].append({"name": "raas_import_ok", "ok": True, "module_file": str(Path(getattr(raas, "__file__", "")).resolve())})
    except Exception as exc:
        result["ok"] = False
        result["checks"].append({"name": "raas_import_ok", "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    payload = json.dumps(result, indent=2)
    out = os.getenv("OPSROOM_SELF_TEST_OUT", "").strip()
    if out:
        try:
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_text(payload, encoding="utf-8")
        except Exception:
            pass
    print(payload)
    return 0 if result.get("ok") else 1


def main() -> int:
    if "--self-test" in sys.argv:
        return run_self_test()
    enable_high_dpi()
    log_path = enable_log_file()
    settings = load_settings()
    port = int(settings.get("server", {}).get("port", 8080))
    lan_access = bool(settings.get("server", {}).get("lan_access", False))
    bind_host = "0.0.0.0" if lan_access else LOCAL_HOST
    url = f"http://{LOCAL_HOST}:{port}"

    print("\n" + "=" * 72)
    print(f"Starting OPS ROOM 0.25.63 at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Log file: {log_path}")
    print(f"Server bind: {'0.0.0.0' if lan_access else 'localhost'}:{port}")

    if not port_available(bind_host, port):
        message_box(
            "OPS ROOM",
            f"Port {port} is already in use. Close the other Ops Room or server process, then try again.\n\nLog: {log_path}",
            error=True,
        )
        return 1

    # Start/attach FSUIPC7 before the FastAPI app imports its background
    # engines. Flight Watch, Logbook and Announcer should see FSUIPC7 first,
    # with SimConnect only as fallback.
    try:
        fsuipc = autostart_if_configured()
        print(f"FSUIPC7 early autostart: {fsuipc.get('reason') or ('started' if fsuipc.get('started') else 'not required')}")
    except Exception as exc:
        print(f"FSUIPC7 early autostart failed safely: {type(exc).__name__}: {exc}")

    server = ServerThread(bind_host, port)
    server.start()
    ipv6_server: ServerThread | None = None
    if not lan_access:
        # Try to add an IPv6 loopback listener so [::1]:port works alongside
        # the primary IPv4 bind. Best-effort and silent on failure.
        try:
            ipv6_server = _start_ipv6_loopback_server(port)
        except Exception as exc:
            print(f"IPv6 loopback bind attempt skipped: {type(exc).__name__}: {exc}")
    if not wait_until_ready(port):
        detail = f"\n\n{type(server.error).__name__}: {server.error}" if server.error else ""
        message_box("OPS ROOM", f"The local service did not start.{detail}\n\nLog: {log_path}", error=True)
        server.stop()
        return 1

    print(f"Local browser console: http://localhost:{port}")
    print(f"Desktop host console: http://localhost:{port}/host")
    try:
        fsuipc = autostart_if_configured()
        print(f"FSUIPC7 autostart: {fsuipc.get('reason') or ('started' if fsuipc.get('started') else 'not required')}")
    except Exception as exc:
        print(f"FSUIPC7 autostart failed safely: {type(exc).__name__}: {exc}")
    start_announcement_engine()
    start_hotkey_service()

    # First-run convenience: install the bridge automatically when a standard
    # vPilot installation and its official plugin API are present. OPS ROOM
    # never modifies vPilot itself; it only adds its own DLL to Plugins.
    try:
        bridge = bridge_installation_status()
        if bridge.get("supported") and bridge.get("api_found") and not bridge.get("installed"):
            print("vPilot detected. Installing OPS ROOM bridge automatically...")
            result = install_bridge()
            if result.get("ok"):
                print(result.get("message") or "vPilot bridge installed.")
            else:
                print(f"Automatic vPilot bridge installation skipped: {result.get('reason') or 'unknown error'}")
    except Exception as exc:
        print(f"Automatic vPilot bridge installation failed safely: {type(exc).__name__}: {exc}")
    if lan_access:
        # Do not write the user's private LAN IP into logs. The UI can reveal addresses only on explicit request.
        print(f"LAN interface: http://*:{port} (private address hidden)")

    settings = load_settings()
    start_url = f"{url}/host#settings" if not settings.get("interface", {}).get("setup_completed", False) else url
    force_browser = "--browser" in sys.argv or os.getenv("OPSROOM_FORCE_BROWSER") == "1"
    force_native = "--native" in sys.argv or os.getenv("OPSROOM_NATIVE_WINDOW") == "1"
    try:
        if force_browser:
            webbrowser.open(start_url)
            while server.is_alive():
                time.sleep(0.5)
        elif os.name == "nt" and not force_native:
            try:
                run_tray(url, server)
            except Exception as exc:
                print(f"Tray mode failed: {type(exc).__name__}: {exc}")
                traceback.print_exc()
                webbrowser.open(start_url)
                while server.is_alive():
                    time.sleep(0.5)
        else:
            try:
                run_native(url)
            except Exception as exc:
                print(f"Native window failed: {type(exc).__name__}: {exc}")
                traceback.print_exc()
                message_box(
                    "OPS ROOM",
                    "The native control-centre window could not start. Ops Room will open in your browser instead.\n\n"
                    f"Details are in {log_path}",
                    error=False,
                )
                webbrowser.open(url)
                while server.is_alive():
                    time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            shutdown_announcement_engine()
        except Exception:
            pass
        try:
            stop_hotkey_service()
        except Exception:
            pass
        try:
            from app.camera_bridge import stop_bridge as stop_camera_bridge
            stop_camera_bridge()
        except Exception as exc:
            print(f"Camera Bridge cleanup failed safely: {type(exc).__name__}: {exc}")
        server.stop()
        server.join(timeout=5)
        if ipv6_server is not None:
            try:
                ipv6_server.stop()
            except Exception:
                pass
        if server.is_alive():
            print("OPS ROOM server did not exit cleanly after 5 seconds; forcing process shutdown.")
            os._exit(0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
