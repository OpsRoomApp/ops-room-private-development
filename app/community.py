"""OPS ROOM community integration.

End-user Discord connect, Discord Rich Presence, and the opt-in flight-event /
live-feed sender that backs the Discord channel posts, website leaderboard and
community map.

Design notes
------------
* Rich Presence talks to the user's *local* Discord client over the Discord
  IPC pipe (no OAuth, no server). It needs only the Discord application client
  id, which ships as a setting default.
* Flight events + live position are opt-in: they only leave the machine when
  the user has linked Discord (``community.discord_app_token`` set) AND turned
  on ``community.share_flights``. The live feed additionally requires
  ``community.visibility == "public"``.
* All outbound HTTP is performed on a background thread with a short timeout;
  a failed send is logged and dropped, never surfaced to the flight loop.

Privacy: only flight data (callsign, aircraft, registration, airports, times,
landing metrics) is sent. The Discord identity is resolved server-side from the
per-user ``app_token`` issued by the connect flow.
"""

from __future__ import annotations

import json
import logging
import os
import struct
import threading
import time
import webbrowser
from typing import Any

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from .settings_store import load_settings, save_settings

_LOGGER = logging.getLogger("opsroom.community")

DEFAULT_DISCORD_CLIENT_ID = "1532784515418951721"
DEFAULT_API_BASE = "https://admin.opsroom.live"

router = APIRouter(prefix="/api/community", tags=["community"])

_STARTED = False
_STOP = threading.Event()
_RPC: "_DiscordRPC | None" = None
_LAST_ACTIVITY_JSON: str | None = None
_ACTIVITY_START_EPOCH: float | None = None


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------

def community_settings() -> dict[str, Any]:
    return load_settings().get("community") or {}


def _save_community(**kwargs: Any) -> None:
    settings = load_settings()
    cfg = dict(settings.setdefault("community", {}))
    cfg.update(kwargs)
    settings["community"] = cfg
    save_settings(settings)


def is_connected() -> bool:
    return bool(community_settings().get("discord_app_token"))


def community_status() -> dict[str, Any]:
    cfg = community_settings()
    base = (cfg.get("api_base") or DEFAULT_API_BASE).rstrip("/")
    return {
        "ok": True,
        "connected": bool(cfg.get("discord_app_token")),
        "discord_username": cfg.get("discord_username") or "",
        "discord_id": cfg.get("discord_id") or "",
        "visibility": cfg.get("visibility") or "discord",
        "share_flights": bool(cfg.get("share_flights")),
        "rich_presence_enabled": bool(cfg.get("rich_presence_enabled", True)),
        "api_base": base,
        "authorize_url": f"{base}/api/community/connect",
    }


# ---------------------------------------------------------------------------
# Endpoints (loopback capture + connect control)
# ---------------------------------------------------------------------------

@router.get("/status")
async def _status() -> dict[str, Any]:
    return community_status()


@router.get("/connected")
async def _connected(
    discord_id: str = "",
    username: str = "",
    app_token: str = "",
    error: str = "",
) -> HTMLResponse:
    """Loopback redirect target for the OAuth connect flow.

    The admin API exchanges the Discord code server-side and redirects the
    user's browser back here with the resolved identity + per-user token. We
    persist it and render a tiny confirmation page the user can close.
    """
    if error:
        body = _connected_page(False, f"Discord connect failed: {error}")
        return HTMLResponse(body)

    if not app_token or not discord_id:
        body = _connected_page(False, "Discord connect returned no identity. Try again.")
        return HTMLResponse(body)

    _save_community(
        discord_id=str(discord_id).strip(),
        discord_username=str(username).strip(),
        discord_app_token=str(app_token).strip(),
    )
    _LOGGER.info("Discord connected: %s (%s)", username, discord_id)
    body = _connected_page(True, f"Connected as {username or discord_id}")
    return HTMLResponse(body)


def _connected_page(ok: bool, message: str) -> str:
    color = "#059669" if ok else "#dc2626"
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>OPS ROOM</title></head>"
        f"<body style='background:#0a0f14;color:#e2e8f0;font-family:Consolas,monospace;"
        "display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>"
        f"<div style='text-align:center'><div style='font-size:15px;color:{color};"
        "letter-spacing:.2em'>OPS ROOM</div>"
        f"<div style='margin-top:12px;font-size:14px'>{message}</div>"
        "<div style='margin-top:20px;font-size:12px;color:#64748b'>"
        "You can close this tab and return to OPS ROOM.</div></div></body></html>"
    )


@router.post("/connect")
async def _connect() -> dict[str, Any]:
    """Open the Discord OAuth authorize URL in the system browser."""
    cfg = community_settings()
    base = (cfg.get("api_base") or DEFAULT_API_BASE).rstrip("/")
    url = f"{base}/api/community/connect"
    try:
        webbrowser.open(url)
    except Exception as exc:
        _LOGGER.warning("Failed to open Discord connect URL: %s", exc)
        raise HTTPException(status_code=500, detail="Could not open the browser") from exc
    return {"ok": True, "url": url}


@router.post("/disconnect")
async def _disconnect() -> dict[str, Any]:
    _save_community(
        discord_id="",
        discord_username="",
        discord_app_token="",
        share_flights=False,
    )
    return community_status()


@router.post("/settings")
async def _settings(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None

    updates: dict[str, Any] = {}
    if "visibility" in body:
        value = str(body.get("visibility") or "discord").strip().lower()
        updates["visibility"] = value if value in ("discord", "public", "hidden") else "discord"
    if "share_flights" in body:
        updates["share_flights"] = bool(body.get("share_flights"))
    if "rich_presence_enabled" in body:
        updates["rich_presence_enabled"] = bool(body.get("rich_presence_enabled"))
    if "api_base" in body:
        updates["api_base"] = str(body.get("api_base") or DEFAULT_API_BASE).strip().rstrip("/")
    if updates:
        _save_community(**updates)
        # #100: sync the sharing settings to the server so the website map and
        # leaderboard see the same visibility the app shows. Best-effort and
        # async (never blocks the settings save).
        try:
            from threading import Thread

            def _sync() -> None:
                try:
                    _post("/api/community/settings", {"visibility": updates.get("visibility")})
                except Exception:
                    pass

            if "visibility" in updates:
                Thread(target=_sync, name="OpsRoom-CommunitySync", daemon=True).start()
        except Exception:
            pass
    return community_status()


# ---------------------------------------------------------------------------
# Flight events (called from the logbook on TAKEOFF / LANDING)
# ---------------------------------------------------------------------------

def _first_number(*values: Any) -> float | None:
    for value in values:
        try:
            number = float(value)
            if number == number:  # drop NaN
                return number
        except (TypeError, ValueError):
            continue
    return None


def _minutes(seconds: Any) -> float | None:
    value = _first_number(seconds)
    return round(value / 60.0, 1) if value is not None else None


def _event_block_seconds(meta: dict[str, Any]) -> float | None:
    """Block seconds for a community flight event.

    ``meta["durations"]`` (with ``block_seconds``) is only computed at logbook
    finalize (logbook.py:1558) — but takeoff/landing events fire mid-flight,
    so at event time ``durations`` is empty and the old code stored ``None``
    -> leaderboard hours were always 0. Fall back to the event times
    (block_out/block_in or landing) which are already populated.
    """
    durations = meta.get("durations") if isinstance(meta.get("durations"), dict) else {}
    value = durations.get("block_seconds")
    if value is not None:
        return _first_number(value)
    times_map = meta.get("times") if isinstance(meta.get("times"), dict) else {}
    start = times_map.get("block_out") or meta.get("started_utc")
    end = times_map.get("block_in") or times_map.get("landing")
    if not start or not end:
        return None
    try:
        from datetime import datetime
        start_dt = datetime.fromisoformat(str(start).rstrip("Z"))
        end_dt = datetime.fromisoformat(str(end).rstrip("Z"))
        seconds = (end_dt - start_dt).total_seconds()
        return seconds if seconds > 0 else None
    except Exception:
        return None


def _airport_name(icao: str) -> str:
    if not icao:
        return ""
    try:
        from .data_loader import load_airports
        airport = load_airports().get(icao.upper())
        if airport is not None:
            name = getattr(airport, "name", None)
            if name:
                return str(name)
    except Exception:
        pass
    return ""


def notify_flight_event(meta: dict[str, Any], event_type: str) -> None:
    """Queue a takeoff/landing community event (no-op unless opted in)."""
    try:
        cfg = community_settings()
        if not cfg.get("discord_app_token") or not cfg.get("share_flights"):
            return
        flight = meta.get("flight") if isinstance(meta.get("flight"), dict) else {}
        aircraft = meta.get("aircraft") if isinstance(meta.get("aircraft"), dict) else {}
        metrics = meta.get("metrics") if isinstance(meta.get("metrics"), dict) else {}
        snapshot = {
            "event_type": event_type,
            "flight_id": str(meta.get("id") or ""),
            "callsign": str(flight.get("callsign") or ""),
            "aircraft": str(flight.get("aircraft_icao") or aircraft.get("model") or aircraft.get("title") or ""),
            "registration": str(flight.get("registration") or ""),
            "origin": str(flight.get("origin") or "").upper(),
            "destination": str(flight.get("destination") or "").upper(),
            "landing_rate_fpm": metrics.get("landing_rate_fpm"),
            "touchdown_g": metrics.get("touchdown_g"),
            "touchdown_speed_kts": metrics.get("touchdown_speed_kts"),
            "duration_min": _minutes(_event_block_seconds(meta)),
            "score": (meta.get("debrief") or {}).get("score") if isinstance(meta.get("debrief"), dict) else None,
            "distance_nm": metrics.get("distance_nm") or flight.get("distance_nm"),
        }
    except Exception:
        _LOGGER.exception("community event snapshot failed")
        return

    threading.Thread(
        target=_post_event,
        args=(snapshot,),
        name="OpsRoom-Community-Event",
        daemon=True,
    ).start()


def _post_event(snapshot: dict[str, Any]) -> None:
    snapshot["origin_name"] = _airport_name(snapshot.get("origin") or "")
    snapshot["destination_name"] = _airport_name(snapshot.get("destination") or "")
    _post("/api/community/event", snapshot)


# ---------------------------------------------------------------------------
# Outbound HTTP (background, best-effort)
# ---------------------------------------------------------------------------

def _post(path: str, payload: dict[str, Any]) -> None:
    cfg = community_settings()
    token = str(cfg.get("discord_app_token") or "")
    if not token:
        return
    base = (cfg.get("api_base") or DEFAULT_API_BASE).rstrip("/")
    try:
        requests.post(
            f"{base}{path}",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
    except Exception as exc:
        _LOGGER.debug("community POST %s failed: %s", path, exc)


# ---------------------------------------------------------------------------
# Background loop: Rich Presence + live feed
# ---------------------------------------------------------------------------

def _live_payload() -> dict[str, Any] | None:
    try:
        from .flight_watch import build_flight_watch
    except Exception:
        return None
    try:
        fw = build_flight_watch(force=False)
    except Exception:
        return None
    if not fw.get("ok") or fw.get("state") != "live":
        return None
    telemetry = fw.get("telemetry") if isinstance(fw.get("telemetry"), dict) else {}
    flight = fw.get("flight") if isinstance(fw.get("flight"), dict) else {}
    aircraft_icao = str(flight.get("aircraft_icao") or "").upper()
    registration = str(flight.get("registration") or "").upper()
    if not aircraft_icao:
        # #103: fall back to the SimBrief plan's aircraft identity when the
        # flight-watch snapshot does not carry it.
        try:
            settings = load_settings()
            user_ref = str(settings.get("identity", {}).get("simbrief_user_id") or "")
            if user_ref:
                from .simbrief_client import cached_plan as _cached_plan

                plan = _cached_plan(user_ref)
                ac = (plan or {}).get("aircraft") if isinstance((plan or {}).get("aircraft"), dict) else {}
                aircraft_icao = aircraft_icao or str(ac.get("icao") or "").upper()
                registration = registration or str(ac.get("registration") or "").upper()
        except Exception:
            pass
    heading = telemetry.get("heading") or telemetry.get("heading_deg") or telemetry.get("true_heading_deg")
    return {
        "callsign": str(flight.get("callsign") or ""),
        "origin": str(flight.get("origin") or "").upper(),
        "destination": str(flight.get("destination") or "").upper(),
        # #103: aircraft type + heading so the website map can draw a rotated
        # aircraft marker instead of a dot, and show the route on hover.
        "aircraft": aircraft_icao,
        "registration": registration,
        "heading": heading,
        # #111: dotted FMS-style route from the SimBrief plan navlog so the
        # website map can draw the flight's route line.
        "route": _plan_route(),
        "phase": str(fw.get("phase") or ""),
        "latitude": telemetry.get("lat"),
        "longitude": telemetry.get("lon"),
        "altitude_ft": _first_number(telemetry.get("indicated_altitude_ft"), telemetry.get("altitude_ft")),
        "ground_speed_kts": telemetry.get("ground_speed_kts"),
    }


def _plan_route() -> list[list[float]]:
    """#111: compact [lat, lon] pairs from the cached SimBrief plan navlog.

    Decimated to at most 64 points so the 15 s live tick stays light; falls
    back to origin -> destination coordinates when the navlog is missing.
    """
    try:
        from .simbrief_client import cached_plan as _cached_plan
        settings = load_settings()
        user_ref = str(settings.get("identity", {}).get("simbrief_user_id") or "")
        plan = _cached_plan(user_ref) if user_ref else None
        if isinstance(plan, dict):
            navlog = plan.get("navlog")
            if isinstance(navlog, list):
                points: list[list[float]] = []
                for fix in navlog:
                    if not isinstance(fix, dict):
                        continue
                    lat = fix.get("latitude")
                    lon = fix.get("longitude")
                    if lat is None or lon is None:
                        continue
                    try:
                        lat = float(lat)
                        lon = float(lon)
                    except (TypeError, ValueError):
                        continue
                    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                        continue
                    points.append([round(lat, 5), round(lon, 5)])
                if points:
                    step = max(1, (len(points) + 63) // 64)
                    return points[::step]
            origin = plan.get("origin") if isinstance(plan.get("origin"), dict) else {}
            destination = plan.get("destination") if isinstance(plan.get("destination"), dict) else {}
            o_lat, o_lon = origin.get("latitude"), origin.get("longitude")
            d_lat, d_lon = destination.get("latitude"), destination.get("longitude")
            if o_lat is not None and o_lon is not None and d_lat is not None and d_lon is not None:
                return [[round(float(o_lat), 5), round(float(o_lon), 5)], [round(float(d_lat), 5), round(float(d_lon), 5)]]
    except Exception:
        pass
    return []


def _tick_live() -> None:
    cfg = community_settings()
    if not cfg.get("discord_app_token") or not cfg.get("share_flights"):
        return
    if cfg.get("visibility") != "public":
        return
    payload = _live_payload()
    if payload is None:
        return
    _post("/api/community/live", payload)


def _alt_label(alt_ft: float | None) -> str:
    if alt_ft is None:
        return ""
    if alt_ft >= 18000:
        return f"FL{int(round(alt_ft / 100)):03d}"
    return f"{int(round(alt_ft))} FT"


def _update_presence() -> None:
    global _RPC, _LAST_ACTIVITY_JSON, _ACTIVITY_START_EPOCH
    cfg = community_settings()
    enabled = bool(cfg.get("rich_presence_enabled", True))
    client_id = str(cfg.get("discord_client_id") or DEFAULT_DISCORD_CLIENT_ID)

    if not enabled:
        if _RPC is not None:
            try:
                _RPC.clear()
                _RPC.close()
            except Exception:
                pass
            _RPC = None
            _LAST_ACTIVITY_JSON = None
        return

    payload = _live_payload()
    activity: dict[str, Any] | None = None
    if payload is not None and payload.get("callsign"):
        details = payload["callsign"]
        if payload.get("origin") and payload.get("destination"):
            details = f"{payload['callsign']} · {payload['origin']} → {payload['destination']}"
        phase = str(payload.get("phase") or "").strip() or "FLYING"
        state = phase
        alt = payload.get("altitude_ft")
        if alt:
            state = f"{phase} · {_alt_label(alt)}"
        if _ACTIVITY_START_EPOCH is None:
            _ACTIVITY_START_EPOCH = time.time()
        activity = {
            "details": details,
            "state": state,
            "assets": {"large_text": "OPS ROOM"},
            "timestamps": {"start": int(_ACTIVITY_START_EPOCH)},
        }
    else:
        _ACTIVITY_START_EPOCH = None

    activity_json = json.dumps(activity, sort_keys=True, separators=(",", ":")) if activity else None
    if activity_json == _LAST_ACTIVITY_JSON:
        return

    if _RPC is None:
        _RPC = _DiscordRPC(client_id)
        if not _RPC.connect():
            _RPC = None
            return
    try:
        _RPC.set_activity(activity)
        _LAST_ACTIVITY_JSON = activity_json
        _LOGGER.info("Rich Presence updated: %s", details)
    except Exception as exc:
        _LOGGER.warning("Rich Presence update failed: %s", exc)
        _RPC.close()
        _RPC = None


def _sync_visibility_to_server() -> None:
    """#109: one-shot startup sync of the app-side visibility to the server.

    Runs once on app start so the website map sees the (now default) public
    visibility immediately — a fresh connect or app restart must never require
    a manual /flight-visibility command again. Best-effort, never blocks.
    """
    try:
        cfg = community_settings()
        visibility = str(cfg.get("visibility") or "discord")
        if visibility not in ("discord", "public", "hidden"):
            visibility = "discord"
        _post("/api/community/settings", {"visibility": visibility})
    except Exception:
        pass


def _community_loop() -> None:
    tick = 0
    synced = False
    while not _STOP.is_set():
        try:
            _update_presence()
            if not synced:
                synced = True
                _sync_visibility_to_server()
            if tick % 3 == 0:
                _tick_live()
        except Exception:
            _LOGGER.exception("community background loop error")
        tick += 1
        _STOP.wait(5.0)


def start_community() -> None:
    global _STARTED
    if _STARTED:
        return
    _STARTED = True
    threading.Thread(target=_community_loop, name="OpsRoom-Community", daemon=True).start()


def shutdown_community() -> None:
    _STOP.set()
    global _RPC
    if _RPC is not None:
        try:
            _RPC.clear()
            _RPC.close()
        except Exception:
            pass
        _RPC = None


# ---------------------------------------------------------------------------
# Discord IPC (local Rich Presence)
# ---------------------------------------------------------------------------

def _pipe_paths() -> list[str]:
    paths: list[str] = []
    if os.name == "nt":
        for index in range(10):
            paths.append(rf"\\.\pipe\discord-ipc-{index}")
    else:
        base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
        for index in range(10):
            paths.append(f"{base}/discord-ipc-{index}")
    return paths


class _DiscordRPC:
    """Minimal Discord IPC client (Rich Presence only).

    #102: every step is observable in opsroom.log (INFO on connect, WARNING
    with the reason on failure) and the handshake/read are timeout-guarded so
    a stale or orphaned pipe can never wedge the 5-second community loop
    (a blocking read with no timeout used to hang _update_presence forever).
    """

    _HANDSHAKE_TIMEOUT_SECONDS = 3.0

    def __init__(self, client_id: str) -> None:
        self.client_id = client_id
        self._pipe: Any = None
        self._connected = False

    def connect(self) -> bool:
        self.close()
        for path in _pipe_paths():
            try:
                pipe = open(path, "r+b", buffering=0)
            except OSError:
                continue
            self._pipe = pipe
            try:
                self._handshake()
                self._connected = True
                _LOGGER.info("Rich Presence connected via %s", path)
                return True
            except OSError as exc:
                _LOGGER.warning("Rich Presence pipe %s failed: %s", path, exc)
                self.close()
                continue
        _LOGGER.warning("Rich Presence not available: no usable Discord IPC pipe")
        return False

    def _handshake(self) -> None:
        self._write(0, {"v": 1, "client_id": self.client_id})
        op, _payload = self._read_timeout(self._HANDSHAKE_TIMEOUT_SECONDS)
        if op is None:
            raise OSError("no handshake response from Discord (timeout or closed pipe)")

    def _read_timeout(self, timeout: float) -> tuple[int | None, bytes | None]:
        """Read one IPC frame with a hard timeout (non-blocking join on a
        helper thread). Never wedges the caller on a silent pipe."""
        result: dict[str, Any] = {}

        def _blocking_read() -> None:
            try:
                result["value"] = self._read()
            except Exception as exc:  # noqa: BLE001
                result["error"] = exc

        worker = threading.Thread(target=_blocking_read, daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            raise OSError("Discord IPC read timed out")
        if "error" in result:
            raise result["error"]
        return result.get("value") or (None, None)

    def set_activity(self, activity: dict[str, Any] | None) -> None:
        if not self._connected or self._pipe is None:
            return
        self._write(
            1,
            {
                "cmd": "SET_ACTIVITY",
                "args": {"pid": os.getpid(), "activity": activity},
                "nonce": f"opsroom-{int(time.time() * 1000)}",
            },
        )

    def clear(self) -> None:
        self.set_activity(None)

    def _write(self, op: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self._pipe.write(struct.pack("<II", op, len(data)))
        self._pipe.write(data)
        self._pipe.flush()

    def _read(self) -> tuple[int | None, bytes | None]:
        header = self._pipe.read(8)
        if not header or len(header) < 8:
            return None, None
        op, length = struct.unpack("<II", header)
        payload = self._pipe.read(length) if length else b""
        return op, payload

    def close(self) -> None:
        if self._pipe is not None:
            try:
                self._pipe.close()
            except OSError:
                pass
        self._pipe = None
        self._connected = False
