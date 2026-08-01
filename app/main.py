from __future__ import annotations

from pathlib import Path
import asyncio
import json
import logging
import mimetypes
import os
import threading
import sys

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, Response, RedirectResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .board_logic import build_board, busiest_airports, airport_traffic_counts
from .data_loader import airport_option, airport_to_dict, load_airports, logo_status, nearest_airport, nearest_airports, search_airports, stand_sources_status
from .simconnect_position import read_position, simconnect_diagnostics, radio_state, set_radio_frequency, swap_radio, autopilot_state, set_autopilot_target, set_autopilot_action
from .vatsim_client import get_vatsim_data, CACHE_SECONDS
from .weather_client import fetch_metar, fetch_realworld_atis
from .camera_state import get_target, set_target, set_view as set_camera_view_state, reset_view as reset_camera_view_state, release_camera as release_camera_state
from .scratchpad import scratchpad_status, scratchpad_get_page, scratchpad_save_page, scratchpad_clear_page
from .camera_bridge import bridge_status as camera_bridge_status, start_bridge as camera_bridge_start, stop_bridge as camera_bridge_stop, log_tail as camera_bridge_log_tail
from .opsroom_native_bridge import stop as native_bridge_stop, status as native_bridge_runtime_status, request_charts as native_bridge_request_charts
from .settings_store import load_settings, save_settings, update_hoppie_code, app_data_dir
from .system_status import build_system_summary
from .performance import profiles as performance_profiles, calculate as performance_calculate
from .simbrief_client import fetch_latest_ofp, status as simbrief_status, cached_plan, cached_ofp_file, ensure_current_ofp_asset
from .briefing_data import operational_briefing, simbrief_pdf_page_png
from .charts import briefing_charts, ownship_overlay_status, chartfox_airport_grouped_charts, chartfox_oauth_authorize_url, chartfox_oauth_callback, chartfox_oauth_status, chartfox_oauth_disconnect, chartfox_airport_search, chartfox_chart_detail, _chartfox_chart_detail_cached, _chartfox_airport_grouped_charts_cached, _chartfox_overlay_compute, chartfox_diagnostics, chartfox_chart_file_proxy, chartfox_chart_file_status, chartfox_debug, chartfox_force_cache_cleanup, _airac_seconds_remaining
from .fenix_adapter import status as fenix_status, simbrief as fenix_simbrief, sync_load_targets as fenix_sync_load_targets, start_gsx_boarding as fenix_start_gsx_boarding
from .server_info import build_server_info, qr_png
from .dispatch_engine import dispatch_context, discover_routes
from .dispatch_state import get_active_dispatch, set_active_dispatch
from .flight_watch import build_flight_watch
from .network_status import build_network_status
from .map_data import build_live_map
from . import aviation_data
from .map_tiles import get_tile, tile_status
from .vpilot_bridge import bridge_status, record_heartbeat, record_event, poll_commands, message_status, queue_command
from .vpilot_installer import bridge_installation_status, install_bridge, remove_bridge
from .announcements import status as announcement_status, play_event as announcement_play, stop_audio as announcement_stop, reset_flight as announcement_reset, start_engine as start_announcement_engine, toggle_pause as announcement_toggle_pause, set_muted as announcement_set_muted, apply_runtime_settings as announcement_apply_runtime_settings, trigger_boarding_service as announcement_boarding_trigger, shutdown_engine as announcement_shutdown
from .gsx_remote import status as gsx_status, open_menu as gsx_open_menu, select_menu as gsx_select_menu, call_service as gsx_call_service, release_control as gsx_release_control, automation_status as gsx_automation_status, start_automation as gsx_start_automation, stop_automation as gsx_stop_automation, warm_operator_from_simbrief_plan as gsx_warm_operator
from .gsx_receipts import list_receipts, receipt_file
from .hoppie_client import status as hoppie_status, ping as hoppie_ping, poll_once as hoppie_poll, stop_polling as hoppie_stop, set_callsign_override as hoppie_callsign, send_message as hoppie_send, request_info as hoppie_info, cpdlc_logon as hoppie_cpdlc_logon, cpdlc_send as hoppie_cpdlc_send, cpdlc_reply as hoppie_cpdlc_reply, pdc_request as hoppie_pdc_request
from .procedures import build_procedures
from .economy import public_status as economy_status, configure as economy_configure, estimate_statement as economy_estimate_statement
from .non_normal_profiles import build_non_normal
from .telemetry_provider import telemetry_diagnostics, reselect_telemetry, start_telemetry_engine, shutdown_telemetry_engine
from .black_box import status as black_box_status, stop_recording as black_box_stop_recording, list_recordings as black_box_list, recording as black_box_recording, samples as black_box_samples, live_snapshot as black_box_live, file_path as black_box_file, export_csv as black_box_export_csv, export_gpx as black_box_export_gpx, export_kml as black_box_export_kml, recover_interrupted as black_box_recover, shutdown as black_box_shutdown, diagnose as black_box_diagnose
from .black_box_replay import status as black_box_replay_status, start as black_box_replay_start, control as black_box_replay_control, stop as black_box_replay_stop, shutdown as black_box_replay_shutdown
from .module_preloader import register as _preloader_register, prewarm_all as _preloader_prewarm_all, status as _preloader_status, diagnostics as _preloader_diagnostics
from .aircraft_adapter_installer import adapter_status as aircraft_adapter_status, install_adapters as aircraft_adapters_install, fsuipc_log_status as aircraft_fsuipc_log_status, reduce_fsuipc_log_size as aircraft_fsuipc_reduce_log
from .pmdg777_eula import eula_text as pmdg777_eula_text, status as pmdg777_eula_status
from .pmdg777_sdk import shutdown as pmdg777_sdk_shutdown

_LOGGER = logging.getLogger("opsroom.main")
try:
    from .raas import start as raas_start, stop as raas_stop, status as raas_status, test as raas_test, set_enabled as raas_set_enabled, set_voice_path as raas_set_voice_path, set_unit as raas_set_unit
except Exception as _exc:
    _RAAS_IMPORT_MESSAGE = f"RAAS import failed: {type(_exc).__name__}: {_exc}"
    def raas_start() -> dict:
        return {"ok": False, "state": "UNAVAILABLE", "display": "RAAS-FAULT", "message": _RAAS_IMPORT_MESSAGE}
    def raas_stop() -> dict:
        return {"ok": True, "state": "STOPPED", "display": "RAAS-STBY", "message": "Runway Awareness unavailable"}
    def raas_status() -> dict:
        return {"ok": False, "state": "UNAVAILABLE", "display": "RAAS-FAULT", "message": _RAAS_IMPORT_MESSAGE}
    def raas_test() -> dict:
        return raas_status()
    def raas_set_enabled(enabled: bool) -> dict:
        return raas_status()
    def raas_set_voice_path(path: str) -> dict:
        return raas_status()
    def raas_set_unit(unit: str) -> dict:
        return raas_status()
try:
    from .raas_audio import clip_path_for_name as raas_clip_path_for_name
except Exception:
    def raas_clip_path_for_name(filename: str):
        return None
from .notifications import status as notification_status
from .host_attention import flash_host
from .obs_branding import status as obs_branding_status, save_logo as obs_save_logo, clear_logo as obs_clear_logo, logo_file as obs_logo_file
from .airline_theme import theme_status, airline_background_file
from .airline_branding import status as airline_branding_status, resolve_airline_branding, save_custom_logo as airline_save_logo, clear_custom_logo as airline_clear_logo, custom_logo_file as airline_logo_file
from .navdata import available as navdata_available, airport as navdata_airport, airport_com as navdata_airport_com, runway_candidates as navdata_runway_candidates
from .device_security import enabled as device_security_enabled, pairing_code as device_pairing_code, rotate_pairing_code, pair as pair_device, validate as validate_device, list_devices as list_trusted_devices, revoke as revoke_trusted_device, revoke_all as revoke_all_trusted_devices, cookie_name as device_cookie_name, is_local_address
from .bug_report import public_status as bug_report_status, report_summary as bug_report_summary, create_diagnostics_zip as bug_report_create_zip, send_report as bug_report_send_report
from .storage_maintenance import storage_status, clear_local_logs_cache
from .updater import check_for_update, prepare_update, launch_prepared_update
from .printer_client import list_printers as printer_list, print_receipt as printer_receipt, test_print as printer_test, status as printer_status, format_cpdlc_receipt as printer_format_cpdlc, generate_receipt_preview as printer_generate_preview
from .logbook import (
    status as logbook_status, start_manual as logbook_start, finalize_active as logbook_finalize,
    discard_active as logbook_discard, force_discard_active as logbook_force_discard, update_entry as logbook_update, delete_entry as logbook_delete,
    latest_landing as logbook_latest_landing,
    export_csv as logbook_export_csv, export_json as logbook_export_json, export_pdf as logbook_export_pdf, export_entry_pdf as logbook_export_entry_pdf, telemetry as logbook_telemetry, get_entry as logbook_get_entry, start_engine as start_logbook_engine,
)

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="OPS ROOM", version="0.25.49")
app.add_middleware(GZipMiddleware, minimum_size=512)


@app.on_event("startup")
def _opsroom_startup_autofetch_ofp() -> None:
    """Warm telemetry and SimBrief caches without blocking the UI after app start."""
    start_telemetry_engine()
    # v0.25.49: purge stale ChartFox cache files from previous builds on every cold start.
    def _chartfox_cleanup() -> None:
        try:
            result = chartfox_force_cache_cleanup()
            if result.get("ok"):
                _LOGGER.info("ChartFox cache cleanup: removed %d files (%d bytes) across %d cycles",
                             result.get("deleted_files", 0), result.get("deleted_bytes", 0),
                             result.get("cycles", 0))
        except Exception as exc:
            _LOGGER.debug("ChartFox cache cleanup skipped: %s", exc)
    threading.Thread(target=_chartfox_cleanup, name="OpsRoom-ChartFox-Cleanup", daemon=True).start()
    try:
        black_box_recover()
    except Exception as exc:
        _LOGGER.debug("Black Box recovery skipped: %s", exc)
    # v0.25.17: register all prewarmable endpoints so module switching never blocks on a fresh fetch.
    # Each registration is wrapped individually so a missing symbol in one module cannot
    # cascade and leave the entire cache cold.
    def _safe_register(name: str, fn) -> None:
        try:
            if not callable(fn):
                raise TypeError(f"preload target for {name!r} is not callable")
            _preloader_register(name, fn)
        except Exception as exc:
            _LOGGER.debug("Preloader register %s skipped: %s: %s", name, type(exc).__name__, exc)
    try:
        _safe_register("briefing", lambda: operational_briefing(force=False))
        _safe_register("dispatch_context", dispatch_context)
        _safe_register("flight_watch", lambda: build_flight_watch(force=False))
        _safe_register("ground_preferences", ground_preferences_get)
        _safe_register("black_box_status", black_box_status)
        _safe_register("dispatch_recommendations", lambda: [r.to_dict() if hasattr(r, "to_dict") else r for r in dispatch_recommendations()])
    except Exception as exc:
        _LOGGER.debug("Preloader registration skipped: %s", exc)
    threading.Thread(target=_preloader_prewarm_all, name="opsroom-prewarm", daemon=True).start()
    def worker() -> None:
        try:
            settings = load_settings()
            if settings.get("integrations", {}).get("simbrief_auto_load", True) is False:
                return
            user_ref = str(settings.get("identity", {}).get("simbrief_user_id") or "").strip()
            if user_ref:
                plan = fetch_latest_ofp(user_ref, force=True)
                try:
                    if isinstance(plan, dict) and plan.get("ok"):
                        gsx_warm_operator(plan)
                except Exception as warm_exc:
                    _LOGGER.debug("startup GSX operator warm skipped: %s", warm_exc)
        except Exception as exc:
            _LOGGER.debug("startup OFP auto-fetch skipped: %s", exc)
    threading.Thread(target=worker, name="OpsRoom-OFP-AutoFetch", daemon=True).start()
    # Silence the FSUIPC7.ini verbose log switches at startup so FSUIPC7.log
    # and FSUIPC7.Previous.log cannot balloon to multi-gigabyte sizes during
    # normal flight. This is best-effort and never stops FSUIPC. Oversized
    # logs are truncated in place without full-file copies; a Windows share
    # lock is reported as pending so cleanup can be retried after the flight.
    # Only a bounded diagnostic tail is retained, and old OPS ROOM rotations
    # are reclaimed when Windows permits it.
    def silence_fsuipc() -> None:
        try:
            result = aircraft_fsuipc_reduce_log(rotate_logs=True, max_bytes=50 * 1024 * 1024)
            if result.get("ok"):
                _LOGGER.info("FSUIPC log mitigation at startup: cleanup=%s, bytes_reclaimed=%s, pending=%s, changed_keys=%s",
                             result.get("cleanup_status"), result.get("bytes_reclaimed"), result.get("pending"), result.get("changed_keys"))
            else:
                _LOGGER.debug("FSUIPC log silence skipped: %s", result.get("reason"))
        except Exception as exc:
            _LOGGER.debug("FSUIPC log silence skipped: %s", exc)
    threading.Thread(target=silence_fsuipc, name="OpsRoom-FSUIPC-Silence", daemon=True).start()


@app.on_event("shutdown")
def _opsroom_shutdown() -> None:
    """Release background services when uvicorn/tray mode exits."""
    try:
        shutdown_telemetry_engine()
    except Exception:
        pass
    try:
        black_box_replay_shutdown()
    except Exception:
        pass
    try:
        black_box_shutdown()
    except Exception:
        pass
    try:
        pmdg777_sdk_shutdown()
    except Exception:
        pass
    try:
        announcement_shutdown()
    except Exception:
        pass
    try:
        hoppie_stop()
    except Exception:
        pass
    try:
        gsx_stop_automation()
    except Exception:
        pass
    try:
        camera_bridge_stop()
    except Exception:
        pass
    try:
        native_bridge_stop()
    except Exception:
        pass
    try:
        raas_stop()
    except Exception:
        pass
start_announcement_engine()
start_logbook_engine()
try:
    raas_start()
except Exception:
    pass
# Native MSFS Charts/Camera WASM system activation is disabled by default; cameras use the restored external bridge provider.
# Camera uses the restored external Camera Bridge provider; charts use browser-readable sources only.


def _cors_allow_origins() -> list[str]:
    """v0.25.17 polish: compute a non-wildcard allow_origins list.

    Browsers reject ``Access-Control-Allow-Origin: *`` together with
    ``allow_credentials=True`` per the CORS spec, so the previous wildcard
    config silently broke credentialed cross-origin requests. Keep
    credentials on (the trusted-device cookie needs them) and list explicit
    scheme+host+port pairs: the configured port plus the common self-test
    ports. LAN clients still flow through ``trusted_device_gate`` for pair
    validation before any payload is returned.
    """
    origins: list[str] = []
    try:
        port = int(load_settings().get("server", {}).get("port", 8080))
    except (TypeError, ValueError):
        port = 8080
    for candidate in (port, 8080, 8090):
        origins.extend([f"http://127.0.0.1:{candidate}", f"http://localhost:{candidate}"])
    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for item in origins:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/assets", StaticFiles(directory=BASE_DIR / "assets"), name="assets")


@app.exception_handler(Exception)
async def opsroom_unhandled_exception_handler(request: Request, exc: Exception):
    # v0.25.17 polish: never ship raw exception text to the browser. The SPA
    # renders this payload into the operational advisories panel and a leaky
    # path or message fragment can leak internal names. Log the full context
    # server-side; return ``code`` as the stable category label. We KEEP the
    # ``detail`` key with a generic user-facing string so existing front-end
    # callers that read ``data.detail || ...`` (catch-all render paths in
    # opsroom.js) continue to display something meaningful instead of going
    # blank.
    # NOTE: HTTPException(5xx, detail=f"...: {exc}") raised by individual
    # routes is left unchanged on purpose; those are upstream-error messages
    # the SPA is expected to surface verbatim. Only the global catch-all is
    # sanitized here.
    _LOGGER.exception("Unhandled exception on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "code": "INTERNAL_ERROR",
            "detail": "Internal error. See opsroom.log for the server-side traceback.",
            "path": str(request.url.path),
        },
    )


_DEVICE_PUBLIC_PATHS = ("/pair", "/static/", "/assets/")
_STATIC_CACHE_PATHS = ("/static/", "/assets/")

@app.middleware("http")
async def static_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if any(request.url.path.startswith(p) for p in _STATIC_CACHE_PATHS):
        response.headers["Cache-Control"] = "public, max-age=86400, immutable"
    return response


@app.middleware("http")
async def trusted_device_gate(request: Request, call_next):
    host = request.client.host if request.client else ""
    if is_local_address(host) or not device_security_enabled():
        return await call_next(request)
    path = request.url.path
    if path == "/pair" or any(path.startswith(prefix) for prefix in _DEVICE_PUBLIC_PATHS[1:]):
        return await call_next(request)
    token = request.cookies.get(device_cookie_name())
    if validate_device(token, address=host):
        return await call_next(request)
    if request.method == "GET" and not path.startswith("/api/"):
        return RedirectResponse(url="/pair", status_code=307)
    return JSONResponse({"detail": "This device has not been paired with the OPS ROOM host."}, status_code=401)


async def _authorize_websocket(websocket: WebSocket) -> bool:
    host = websocket.client.host if websocket.client else ""
    if is_local_address(host) or not device_security_enabled() or validate_device(websocket.cookies.get(device_cookie_name()), address=host):
        await websocket.accept()
        return True
    await websocket.close(code=1008, reason="Device pairing required")
    return False


@app.get("/pair")
def pair_page(request: Request, code: str = "") -> Response:
    host = request.client.host if request.client else ""
    if is_local_address(host):
        return RedirectResponse(url="/", status_code=303)
    error = ""
    if code:
        try:
            token = pair_device(code, name=request.headers.get("user-agent", "LAN DEVICE")[:80], address=host, user_agent=request.headers.get("user-agent", ""))
            response = RedirectResponse(url="/", status_code=303)
            response.set_cookie(device_cookie_name(), token, max_age=60 * 60 * 24 * 180, httponly=True, samesite="lax")
            return response
        except ValueError:
            error = "The pairing code is incorrect."
    body = f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Pair OPS ROOM</title><style>body{{margin:0;background:#080a0a;color:#ece7d2;font-family:Arial,sans-serif;display:grid;place-items:center;min-height:100vh}}main{{width:min(420px,calc(100vw - 32px));border:1px solid #52646b;background:#121617;padding:28px}}h1{{letter-spacing:.08em}}p{{color:#aeb8bb;line-height:1.5}}input,button{{box-sizing:border-box;width:100%;padding:14px;margin-top:12px;background:#090c0d;color:#fff;border:1px solid #617780;font-size:18px}}button{{font-weight:700;cursor:pointer}}.error{{color:#ff7d73}}</style></head><body><main><h1>PAIR THIS DEVICE</h1><p>Enter the six-digit code shown on the OPS ROOM Host computer.</p>{f"<p class='error'>{error}</p>" if error else ""}<form method='get'><input name='code' inputmode='numeric' maxlength='6' pattern='[0-9]{{6}}' autofocus required placeholder='000000'><button type='submit'>PAIR DEVICE</button></form></main></body></html>"""
    return HTMLResponse(body)


@app.get("/api/security/status")
def security_status(request: Request) -> dict:
    _require_local_host(request)
    return {"ok": True, "enabled": device_security_enabled(), "pairing_code": device_pairing_code(), "devices": list_trusted_devices()}


@app.post("/api/security/rotate")
def security_rotate(request: Request) -> dict:
    _require_local_host(request)
    return {"ok": True, "pairing_code": rotate_pairing_code()}


@app.delete("/api/security/devices")
def security_revoke_all(request: Request) -> dict:
    _require_local_host(request)
    return {"ok": True, "revoked": revoke_all_trusted_devices()}


@app.delete("/api/security/devices/{device_id}")
def security_revoke(device_id: str, request: Request) -> dict:
    _require_local_host(request)
    if not revoke_trusted_device(device_id):
        raise HTTPException(status_code=404, detail="Trusted device not found")
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/obs")
def obs_overlay() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "obs.html")


def _active_airline_branding() -> dict:
    settings = load_settings()
    ref = str(settings.get("identity", {}).get("simbrief_user_id") or "").strip()
    plan = cached_plan(ref) if ref else None
    return airline_branding_status(plan)


@app.get("/api/airline-branding")
def airline_branding_get() -> dict:
    return _active_airline_branding()


@app.post("/api/airline-branding/logo")
def airline_branding_logo_post(payload: dict, request: Request) -> dict:
    _require_local_host(request)
    try:
        return airline_save_logo(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/airline-branding/logo")
def airline_branding_logo_delete(request: Request) -> dict:
    _require_local_host(request)
    return airline_clear_logo()


@app.get("/api/airline-branding/logo")
def airline_branding_logo_get() -> Response:
    item = airline_logo_file()
    if not item:
        raise HTTPException(status_code=404, detail="No custom airline logo has been configured.")
    path, mime = item
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "no-store"})


@app.get("/api/obs/branding")
def obs_branding_get() -> dict:
    data = obs_branding_status()
    data["airline"] = _active_airline_branding()
    data["default_mode"] = "custom" if data.get("logo_available") else "active_airline"
    return data


@app.post("/api/obs/logo")
def obs_logo_post(payload: dict, request: Request) -> dict:
    _require_local_host(request)
    try:
        return obs_save_logo(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/obs/logo")
def obs_logo_delete(request: Request) -> dict:
    _require_local_host(request)
    return obs_clear_logo()


@app.get("/api/obs/logo")
def obs_logo_get() -> Response:
    item = obs_logo_file()
    if not item:
        raise HTTPException(status_code=404, detail="No OBS logo has been configured.")
    path, mime = item
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "no-store"})


@app.get("/pirep/{entry_id}")
def pirep_page(entry_id: str) -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "pirep.html")


@app.get("/scoring-rules")
def scoring_rules_page() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "scoring_rules.html")




def _require_local_host(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=403, detail="Host configuration is available only on the OPS ROOM computer.")


def _public_settings() -> dict:
    current = load_settings()
    return {
        "identity": {
            "vatsim_configured": bool(current.get("identity", {}).get("vatsim_cid")),
            "simbrief_configured": bool(current.get("identity", {}).get("simbrief_user_id")),
        },
        "integrations": {
            "hoppie_configured": bool(current.get("integrations", {}).get("hoppie_configured")),
            "simbrief_auto_load": bool(current.get("integrations", {}).get("simbrief_auto_load", True)),
            "announcements_enabled": bool(current.get("integrations", {}).get("announcements_enabled", False)),
            "gsx_departure_catering": bool(current.get("integrations", {}).get("gsx_departure_catering", True)),
            "gsx_departure_water": bool(current.get("integrations", {}).get("gsx_departure_water", True)),
            "openaip_configured": bool(current.get("integrations", {}).get("openaip_api_key")),
        },
        "server": {k: v for k, v in dict(current.get("server", {})).items() if k != "pairing_code"},
        "interface": dict(current.get("interface", {})),
        "updates": {
            "enabled": bool(current.get("updates", {}).get("enabled", True)),
            "check_on_startup": bool(current.get("updates", {}).get("check_on_startup", True)),
        },
    }


@app.get("/host")
def host_console(request: Request) -> FileResponse:
    _require_local_host(request)
    return FileResponse(BASE_DIR / "static" / "host.html")


@app.get("/vatsim-fids")
@app.get("/traffic-board")
def vatsim_fids() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "traffic_board.html")


@app.get("/api/settings/public")
def settings_public_get() -> dict:
    return _public_settings()


@app.get("/api/ground/preferences")
def ground_preferences_get() -> dict:
    integrations = load_settings().get("integrations", {})
    values = {
        "gsx_departure_catering": bool(integrations.get("gsx_departure_catering", True)),
        "gsx_departure_water": bool(integrations.get("gsx_departure_water", True)),
    }
    return {"ok": True, "integrations": values, **values}


@app.put("/api/ground/preferences")
def ground_preferences_put(payload: dict) -> dict:
    current = load_settings()
    integrations = current.setdefault("integrations", {})
    if "gsx_departure_catering" in payload or "departure_catering" in payload:
        integrations["gsx_departure_catering"] = bool(payload.get("gsx_departure_catering", payload.get("departure_catering")))
    if "gsx_departure_water" in payload or "departure_water" in payload:
        integrations["gsx_departure_water"] = bool(payload.get("gsx_departure_water", payload.get("departure_water")))
    saved = save_settings(current)
    stored = saved.get("integrations", {})
    values = {
        "gsx_departure_catering": bool(stored.get("gsx_departure_catering", True)),
        "gsx_departure_water": bool(stored.get("gsx_departure_water", True)),
    }
    return {"ok": True, "integrations": values, **values}


@app.get("/api/updater/status")
def updater_status(request: Request, force: bool = False) -> dict:
    _require_local_host(request)
    return check_for_update(force=force)


@app.post("/api/updater/prepare")
def updater_prepare(payload: dict | None, request: Request) -> dict:
    _require_local_host(request)
    data = payload or {}
    manifest = data.get("manifest") or check_for_update(force=True).get("manifest")
    if not isinstance(manifest, dict):
        raise HTTPException(status_code=400, detail="No valid update manifest is available.")
    try:
        return prepare_update(manifest)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Update preparation failed: {type(exc).__name__}: {exc}") from exc


@app.post("/api/updater/apply")
def updater_apply(payload: dict | None, request: Request) -> dict:
    _require_local_host(request)
    data = payload or {}
    package = str(data.get("package") or "").strip()
    if not package:
        raise HTTPException(status_code=400, detail="No prepared update package was supplied.")
    try:
        result = launch_prepared_update(package, version=str(data.get("version") or ""), updater=str(data.get("updater") or ""))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Updater launch failed: {type(exc).__name__}: {exc}") from exc
    threading.Timer(0.75, lambda: os._exit(0)).start()
    return result


# ── Printer / POS Thermal Compatibility ────────────────────────────────────


@app.get("/api/printer/status")
def printer_status_endpoint(request: Request) -> dict:
    _require_local_host(request)
    return printer_status()


@app.get("/api/printer/list")
def printer_list_endpoint(request: Request) -> dict:
    _require_local_host(request)
    printers = printer_list()
    return {"ok": True, "printers": printers, "count": len(printers)}


@app.post("/api/printer/test")
def printer_test_endpoint(payload: dict | None, request: Request) -> dict:
    _require_local_host(request)
    data = payload or {}
    printer_name = str(data.get("printer_name") or "").strip()
    if not printer_name:
        raise HTTPException(status_code=400, detail="Printer name is required")
    return printer_test(printer_name)


@app.post("/api/printer/preview")
def printer_preview_endpoint(payload: dict | None, request: Request) -> dict:
    _require_local_host(request)
    data = payload or {}
    content = str(data.get("content") or "").strip()
    receipt_type = str(data.get("type") or "cpdlc").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Receipt content is required")
    return printer_generate_preview(content, receipt_type, app_version=app.version)


@app.get("/api/blackbox/diagnose")
def blackbox_diagnose_endpoint() -> dict:
    try:
        return black_box_diagnose()
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@app.get("/api/diagnostics/cache")
def diagnostics_cache_endpoint() -> dict:
    try:
        return {"ok": True, "modules": _preloader_diagnostics()}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@app.get("/api/diagnostics/storage")
def diagnostics_storage(request: Request) -> dict:
    _require_local_host(request)
    return storage_status()


@app.post("/api/diagnostics/clear-local-cache")
def diagnostics_clear_local_cache(payload: dict | None, request: Request) -> dict:
    _require_local_host(request)
    data = payload or {}
    return clear_local_logs_cache(
        logs=bool(data.get("logs", True)),
        diagnostics=bool(data.get("diagnostics", True)),
        map_cache=bool(data.get("map_cache", False)),
    )


@app.get("/api/navdata/status")
def navdata_status() -> dict:
    return {"ok": True, "available": navdata_available(), "source": "OPS ROOM compact MSFS runway cache" if navdata_available() else "fallback telemetry inference"}


@app.get("/api/navdata/airport/{icao}")
def navdata_airport_get(icao: str) -> dict:
    item = navdata_airport(icao)
    if not item:
        raise HTTPException(status_code=404, detail="Airport not found in OPS ROOM navdata cache")
    return {"ok": True, "airport": item, "runways": navdata_runway_candidates(icao), "com": navdata_airport_com(icao)}

@app.get("/api/settings")
def settings_get(request: Request) -> dict:
    _require_local_host(request)
    return load_settings()


@app.put("/api/settings")
def settings_put(payload: dict, request: Request) -> dict:
    _require_local_host(request)
    current = load_settings()
    previous_server = dict(current.get("server", {}))

    for section in ("identity", "integrations", "server", "interface"):
        incoming = payload.get(section)
        if isinstance(incoming, dict):
            current.setdefault(section, {}).update(incoming)
    current.setdefault("interface", {})["setup_completed"] = True

    configured = update_hoppie_code(
        payload.get("hoppie_logon_code"),
        clear=bool(payload.get("clear_hoppie", False)),
    )
    current.setdefault("integrations", {})["hoppie_configured"] = configured
    saved = save_settings(current)
    announcement_apply_runtime_settings()
    restart_required = previous_server != saved.get("server", {})
    return {"ok": True, "settings": saved, "restart_required": restart_required}


@app.get("/api/system/summary")
def system_summary(probe_simconnect: bool = False) -> dict:
    return build_system_summary(probe_simconnect=probe_simconnect)


@app.get("/api/system/console")
def system_console(lines: int = 220) -> dict:
    """Return a readable OPS ROOM startup/runtime console tail for the System page."""
    from collections import deque
    from .logging_utils import redact_private_ips
    limit = max(20, min(int(lines or 220), 600))
    log_path = app_data_dir() / "logs" / "opsroom.log"

    def explain(line: str) -> str:
        raw = redact_private_ips(str(line or "").strip())
        low = raw.lower()
        if not raw:
            return ""
        if "starting ops room" in low:
            return f"[STARTUP] {raw}"
        if "log file:" in low:
            return f"[LOG] {raw}"
        if "server bind:" in low:
            return f"[WEB] {raw}"
        if "local browser console:" in low or "desktop host console:" in low:
            return f"[READY] {raw}"
        if "lan interface:" in low:
            return f"[LAN] {raw}"
        if "fsuipc" in low:
            return f"[FSUIPC] {raw}"
        if "simconnect" in low:
            return f"[SIMCONNECT] {raw}"
        if "camera bridge" in low:
            return f"[CAMERA] {raw}"
        if "raas" in low or "runway awareness" in low:
            return f"[RUNWAY AWARENESS] {raw}"
        if "error" in low or "failed" in low or "traceback" in low or "exception" in low:
            return f"[ATTENTION] {raw}"
        if "uvicorn running" in low or "application startup complete" in low:
            return f"[WEB] {raw}"
        return f"[INFO] {raw}"

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    if not log_path.exists():
        return {"ok": True, "path": str(log_path), "lines": ["[STANDBY] OPS ROOM log file has not been created yet."]}
    try:
        tail: deque[str] = deque(maxlen=limit)
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                text = explain(line.rstrip("\r\n"))
                if text:
                    tail.append(text)
        return {"ok": True, "path": str(log_path), "lines": list(tail)}
    except Exception as exc:
        return {"ok": False, "path": str(log_path), "lines": [f"[ATTENTION] Console log read failed: {type(exc).__name__}: {exc}"]}


def _vatsim_atis_for_airport(icao: str, force: bool = False) -> dict:
    airport = str(icao or "").strip().upper()
    if not airport:
        return {"available": False, "source": "VATSIM", "error": "No airport supplied"}
    try:
        data = get_vatsim_data(force=force)
        rows = data.get("atis") or []
    except Exception as exc:
        return {"available": False, "source": "VATSIM", "error": f"{type(exc).__name__}: {exc}"}

    def matches(callsign: str) -> bool:
        c = str(callsign or "").upper()
        prefixes = {airport}
        if len(airport) == 4 and airport[0] in {"K", "C", "P"}:
            prefixes.add(airport[1:])
        return any(c == f"{prefix}_ATIS" or c.startswith(f"{prefix}_") for prefix in prefixes)

    candidates = [r for r in rows if isinstance(r, dict) and matches(str(r.get("callsign") or ""))]
    # Prefer explicit DEP/ARR ATIS rows if present, then the generic airport ATIS.
    candidates.sort(key=lambda r: (0 if "_ATIS" in str(r.get("callsign") or "").upper() else 1, str(r.get("callsign") or "")))
    if not candidates:
        return {"available": False, "source": "VATSIM", "airport": airport, "error": "No VATSIM ATIS online"}
    out=[]
    for row in candidates[:4]:
        lines = row.get("text_atis") or []
        if isinstance(lines, str):
            lines = [lines]
        text = " ".join(str(x).strip() for x in lines if str(x).strip())
        out.append({
            "callsign": str(row.get("callsign") or "").upper(),
            "frequency": str(row.get("frequency") or ""),
            "atis_code": row.get("atis_code"),
            "text": text,
            "lines": [str(x) for x in lines if str(x).strip()],
            "source": "VATSIM",
        })
    return {"available": True, "source": "VATSIM", "airport": airport, "items": out, "text": out[0].get("text") if out else ""}


def _ops_room_bridge_candidates() -> list[Path]:
    roots: list[Path] = []
    try:
        if getattr(sys, "frozen", False):
            roots.append(Path(sys.executable).resolve().parent)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(Path(meipass))
    except Exception:
        pass
    roots.extend([Path.cwd(), Path(__file__).resolve().parents[1]])

    candidates: list[Path] = []
    for root in roots:
        candidates.extend([
            root / "OPS ROOM Bridge" / "ops-room-bridge",
            root / "_internal" / "OPS ROOM Bridge" / "ops-room-bridge",
            root / "ops_room_bridge" / "build" / "ops-room-bridge",
            root / "ops_room_bridge" / "Community" / "ops-room-bridge",
        ])
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _ops_room_bridge_root() -> Path:
    candidates = _ops_room_bridge_candidates()
    for item in candidates:
        if (item / "Modules" / "OpsRoomBridge2024.wasm").exists() or (item / "modules" / "OpsRoomBridge2024.wasm").exists():
            return item
    for item in candidates:
        if item.exists():
            return item
    return candidates[0]


def _charts_bridge_log_tail(lines: int = 80) -> list[str]:
    path = app_data_dir() / "logs" / "opsroom_bridge_charts_probe.log"
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(10, min(int(lines), 300)):]
    except OSError:
        return []

@app.get("/api/simbrief/ofp-cache/{filename}")
def simbrief_ofp_cache(filename: str) -> FileResponse:
    path = cached_ofp_file(filename)
    if not path:
        raise HTTPException(status_code=404, detail="Cached OFP is not available")
    return FileResponse(path, media_type="application/pdf", filename=path.name)


def _ofp_html_escape(value: object) -> str:
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('\"', "&quot;")


@app.get("/api/simbrief/ofp-view")
def simbrief_ofp_generated_view(theme: str = "dark") -> HTMLResponse:
    settings = load_settings()
    user = str(settings.get("identity", {}).get("simbrief_user_id") or "").strip()
    plan = cached_plan(user) if user else None
    if not plan or not plan.get("ok"):
        raise HTTPException(status_code=404, detail="No SimBrief OFP is currently cached")
    files = plan.get("files") if isinstance(plan.get("files"), dict) else {}
    dark_mode = str(theme or "dark").lower() != "light"
    bg = "#050806" if dark_mode else "#f4f1e9"
    fg = "#f4f4ec" if dark_mode else "#10130f"
    line = "#2f3b32" if dark_mode else "#c8c0aa"
    panel = "#07100a" if dark_mode else "#fffdf6"
    accent = "#efbd47" if dark_mode else "#8a5c00"
    plan_html = str(files.get("plan_html") or "").strip()
    plan_text = str(files.get("plan_text") or "").strip()
    shared_css = f"""
    <style>
    :root{{color-scheme:{'dark' if dark_mode else 'light'}}}
    html,body{{margin:0;width:100%;min-height:100%;background:{bg}!important;color:{fg}!important;font:22px/1.62 ui-monospace,Consolas,Menlo,monospace!important}}
    body{{padding:0!important;box-sizing:border-box}}*{{box-sizing:border-box;scrollbar-color:{line} transparent}}
    a{{color:#77dff0!important}}table{{max-width:none!important;border-collapse:collapse}}
    pre,code,td,th,span,div,p,font,b,strong,i,u{{color:{fg}!important;background:transparent!important}}
    pre{{white-space:pre!important;line-height:1.62!important;margin:0;overflow:auto;font-size:22px!important}}
    .ops-ofp-document{{width:100%;min-height:100vh;background:{bg};padding:22px 26px}}
    .ops-ofp-card{{min-height:calc(100vh - 44px);background:{panel};border:1px solid {line};padding:22px 24px;overflow:auto}}
    .ops-ofp-title{{display:flex;justify-content:space-between;gap:16px;align-items:baseline;margin:0 0 16px;padding-bottom:12px;border-bottom:1px solid {line}}}
    .ops-ofp-title h1{{margin:0;font-size:22px;letter-spacing:.09em;color:{fg}!important}}
    .ops-ofp-title b{{font-size:12px;letter-spacing:.12em;color:{accent}!important}}
    .ops-ofp-html{{font-size:22px;line-height:1.62;min-width:1180px;transform-origin:top left}}
    .ops-ofp-html table,.ops-ofp-html tbody,.ops-ofp-html tr,.ops-ofp-html td,.ops-ofp-html th,.ops-ofp-html div,.ops-ofp-html span,.ops-ofp-html font{{font-size:22px!important;line-height:1.62!important}}
    .ops-ofp-html *{{max-width:none!important}}
    @media(max-width:900px){{html,body{{font-size:20px!important}}.ops-ofp-document{{padding:12px}}.ops-ofp-card{{padding:14px}}.ops-ofp-html{{font-size:20px;min-width:1060px}}.ops-ofp-html table,.ops-ofp-html tbody,.ops-ofp-html tr,.ops-ofp-html td,.ops-ofp-html th,.ops-ofp-html div,.ops-ofp-html span,.ops-ofp-html font{{font-size:20px!important}}}}
    </style>"""
    callsign = _ofp_html_escape(plan.get('callsign') or 'SIMBRIEF OFP')
    origin = plan.get("origin") or {}
    dest = plan.get("destination") or {}
    title_line = f'<div class="ops-ofp-title"><h1>{callsign}</h1><b>{_ofp_html_escape(origin.get("icao") or "----")} TO {_ofp_html_escape(dest.get("icao") or "----")}</b></div>'
    if plan_html:
        wrapped = f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">{shared_css}</head><body><main class="ops-ofp-document"><section class="ops-ofp-card">{title_line}<div class="ops-ofp-html">{plan_html}</div></section></main></body></html>'
        return HTMLResponse(wrapped, headers={"Cache-Control": "no-store", "X-OPSROOM-OFP-Source": "simbrief-plan-html"})
    if not plan_text:
        plan_text = "No SimBrief text OFP was returned in this fetch."
    wrapped = f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">{shared_css}</head><body><main class="ops-ofp-document"><section class="ops-ofp-card">{title_line}<pre>{_ofp_html_escape(plan_text)}</pre></section></main></body></html>'
    return HTMLResponse(wrapped, headers={"Cache-Control": "no-store", "X-OPSROOM-OFP-Source": "simbrief-text"})


@app.get("/api/briefing/operational")
def briefing_operational(force_refresh: bool = False) -> dict:
    return operational_briefing(force=force_refresh)


@app.get("/api/simbrief/ofp-image/{filename}")
def simbrief_ofp_image(filename: str, download: bool = False):
    path = cached_ofp_file(filename) or ensure_current_ofp_asset(filename)
    if not path or not path.is_file():
        raise HTTPException(status_code=404, detail="The requested SimBrief OFP image is unavailable")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = {"Cache-Control": "private, max-age=3600"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{path.name}"'
    return FileResponse(path, media_type=media_type, headers=headers)


@app.get("/api/briefing/simbrief-page/{page_number}.png")
def briefing_simbrief_page_png(page_number: int) -> Response:
    try:
        content = simbrief_pdf_page_png(page_number)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"SimBrief PDF page unavailable: {type(exc).__name__}: {exc}") from exc
    return Response(
        content=content,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )


@app.get("/api/simbrief/status")
def simbrief_status_get() -> dict:
    settings = load_settings()
    return simbrief_status(settings.get("identity", {}).get("simbrief_user_id", ""))


@app.get("/api/simbrief/latest")
def simbrief_latest(force_refresh: bool = False, sync_fenix: bool = False) -> dict:
    settings = load_settings()
    user_ref = settings.get("identity", {}).get("simbrief_user_id", "")
    _LOGGER.info("OFP_FETCH_CLICKED force=%s", force_refresh)
    result = fetch_latest_ofp(user_ref, force=force_refresh)
    try:
        if isinstance(result, dict) and result.get("ok"):
            gsx_warm_operator(result)
    except Exception as warm_exc:
        _LOGGER.debug("GSX operator warm skipped: %s", warm_exc)
    if sync_fenix and result.get("ok"):
        try:
            fstat = fenix_status(force=True)
            if fstat.get("efb_online") and (fstat.get("fenix_detected") or fstat.get("fenix_family_hint")):
                result["fenix_sync"] = fenix_sync_load_targets(result)
        except Exception as exc:
            result["fenix_sync"] = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    return result


@app.get("/api/dispatch/context")
def dispatch_context_get() -> dict:
    return dispatch_context()


@app.get("/api/dispatch/recommendations")
def dispatch_recommendations(
    origin: str = "",
    origin_source: str = "auto",
    target_minutes: int = 120,
    tolerance_minutes: int = 35,
    aircraft: str = "narrowbody",
    atc: str = "prefer",
    weather: str = "any",
    limit: int = 16,
    force_refresh: bool = False,
) -> dict:
    try:
        return discover_routes(
            origin=origin,
            origin_source=origin_source,
            target_minutes=target_minutes,
            tolerance_minutes=tolerance_minutes,
            aircraft=aircraft,
            atc=atc,
            weather=weather,
            limit=limit,
            force=force_refresh,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Dispatch search failed: {type(exc).__name__}: {exc}") from exc


@app.get("/api/dispatch/active")
def dispatch_active_get() -> dict:
    return {"ok": True, "route": get_active_dispatch()}


@app.put("/api/dispatch/active")
def dispatch_active_put(payload: dict) -> dict:
    try:
        return {"ok": True, "route": set_active_dispatch(payload)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/flight-watch")
def flight_watch_get(force_refresh: bool = False) -> dict:
    return build_flight_watch(force=force_refresh)


@app.websocket("/ws/flight-watch")
async def flight_watch_stream(websocket: WebSocket) -> None:
    if not await _authorize_websocket(websocket):
        return
    try:
        while True:
            payload = await asyncio.to_thread(build_flight_watch, False)
            payload["stream_interval_ms"] = 200
            await websocket.send_json(payload)
            await asyncio.sleep(0.20)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/api/network")
def network_get(force_refresh: bool = False, q: str = "") -> dict:
    try:
        return build_network_status(force=force_refresh, query=q)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Network refresh failed: {type(exc).__name__}: {exc}") from exc


@app.get("/api/map/tiles/status")
def map_tiles_status() -> dict:
    return tile_status()


@app.get("/api/map/tile/{z}/{x}/{y}.mvt")
def map_tile(z: int, x: int, y: int) -> Response:
    try:
        content, headers = get_tile(z, x, y)
        return Response(content=content, media_type="application/vnd.mapbox-vector-tile", headers=headers)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Online map tile failed: {type(exc).__name__}: {exc}") from exc




@app.get("/api/livemap/status")
def livemap_aviation_status() -> dict:
    return aviation_data.status()


@app.post("/api/livemap/surface/rescan")
def livemap_surface_rescan() -> dict:
    aviation_data.clear_surface_cache()
    return aviation_data.status()


@app.get("/api/livemap/airport-surface")
def livemap_airport_surface(icao: str) -> dict:
    return aviation_data.airport_surface(icao)

@app.get("/api/livemap/surface-diagnostics")
def livemap_surface_diagnostics(icao: str) -> dict:
    return aviation_data.surface_diagnostics(icao)


@app.get("/api/livemap/layers/airports")
def livemap_layer_airports(bbox: str = "", limit: int = 1000) -> dict:
    return aviation_data.airports_layer(bbox or None, limit=limit)


@app.get("/api/livemap/layers/navaids")
def livemap_layer_navaids(bbox: str = "", limit: int = 1500) -> dict:
    return aviation_data.navaids_layer(bbox or None, limit=limit)


@app.get("/api/livemap/layers/waypoints")
def livemap_layer_waypoints(bbox: str = "", limit: int = 2000) -> dict:
    return aviation_data.waypoints_layer(bbox or None, limit=limit)


@app.get("/api/livemap/layers/airways")
def livemap_layer_airways(bbox: str = "", limit: int = 2000) -> dict:
    return aviation_data.airways_layer(bbox or None, limit=limit)


@app.get("/api/livemap/layers/airspaces")
def livemap_layer_airspaces(bbox: str = "", limit: int = 1000) -> dict:
    return aviation_data.airspaces_layer(bbox or None, limit=limit)

@app.get("/api/map/live")
def map_live(force_refresh: bool = False, traffic_limit: int = 900) -> dict:
    try:
        return build_live_map(force=force_refresh, traffic_limit=traffic_limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Map refresh failed: {type(exc).__name__}: {exc}") from exc


@app.websocket("/ws/map")
async def map_stream(websocket: WebSocket) -> None:
    if not await _authorize_websocket(websocket):
        return
    try:
        while True:
            payload = await asyncio.to_thread(build_live_map, False, 900)
            payload["stream_interval_ms"] = 2500
            await websocket.send_json(payload)
            await asyncio.sleep(2.5)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/api/procedures")
def procedures_get(profile: str = "") -> dict:
    try:
        return build_procedures(profile_override=profile)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Procedures load failed: {type(exc).__name__}: {exc}") from exc




@app.get("/api/procedures/non-normal")
def procedures_non_normal_get(profile: str = "", q: str = "", condition: str = "") -> dict:
    try:
        return build_non_normal(profile_override=profile, query=q, selected_condition=condition)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Non-normal procedures load failed: {type(exc).__name__}: {exc}") from exc


@app.get("/api/blackbox/status")
def blackbox_status_get() -> dict:
    return {**black_box_status(), "replay": black_box_replay_status()}


@app.get("/api/blackbox/adapters/status")
def blackbox_adapters_status_get() -> dict:
    return aircraft_adapter_status()


@app.get("/api/blackbox/adapters/pmdg-eula")
def blackbox_adapters_pmdg_eula_get() -> dict:
    return {"ok": True, "text": pmdg777_eula_text(), "status": pmdg777_eula_status()}


@app.post("/api/blackbox/adapters/install")
def blackbox_adapters_install_post(payload: dict | None = None) -> dict:
    data = payload or {}
    result = aircraft_adapters_install(
        include_pmdg=bool(data.get("include_pmdg", True)),
        accept_pmdg_sdk_eula=bool(data.get("accept_pmdg_sdk_eula", False)),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result)
    return result


@app.get("/api/blackbox/fsuipc-log/status")
def blackbox_fsuipc_log_status_get() -> dict:
    return aircraft_fsuipc_log_status()


@app.post("/api/blackbox/fsuipc-log/reduce")
def blackbox_fsuipc_log_reduce_post(payload: dict | None = None) -> dict:
    data = payload or {}
    result = aircraft_fsuipc_reduce_log(
        rotate_logs=bool(data.get("rotate_logs", True)),
        max_bytes=int(data.get("max_bytes", 50 * 1024 * 1024)),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result)
    return result


@app.get("/api/blackbox/preferences")
def blackbox_preferences_get() -> dict:
    integrations = load_settings().get("integrations", {})
    return {"ok": True, "integrations": {
        "black_box_enabled": bool(integrations.get("black_box_enabled", True)),
        "black_box_auto_record": bool(integrations.get("black_box_auto_record", True)),
        "black_box_max_hz": int(integrations.get("black_box_max_hz") or 30),
        "black_box_simconnect_max_hz": int(integrations.get("black_box_simconnect_max_hz") or 10),
        "black_box_replay_fps": int(integrations.get("black_box_replay_fps") or 30),
    }}


# ── ChartFox canonical namespace (Briefing > Charts owns the OAuth flow) ────────

_CHARTFOX_CALLBACK_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>ChartFox OAuth</title></head><body style="font-family:system-ui,Arial;background:#0d1213;color:#e6efe8;margin:0;display:grid;place-items:center;min-height:100vh"><main style="max-width:520px;text-align:center;padding:32px;border:1px solid #2a3a3a;background:#121616"><h1 id="status" style="letter-spacing:.08em;font-size:16px;margin:0 0 14px">CHARTFOX OAUTH</h1><p id="detail" style="margin:0 0 8px;color:#a7b3b3">Completing authorization&hellip;</p><p id="hint" style="margin:0;font-size:12px;color:#7d8a8a;display:none"></p><button id="ops-done" type="button" style="margin-top:20px;padding:10px 22px;border:1px solid #3a4a4a;background:#1c2428;color:#e6efe8;font:600 13px/1 system-ui;cursor:pointer;letter-spacing:.08em">CLOSE THIS WINDOW</button></main><script>(function(){try{var payload=(function(){try{return JSON.parse('__OPSPAYLOAD__');}catch(_){return {};}})()||{};var opsOk=payload.ok;var opsDetail=payload.detail||'';var tokenType=payload.token_type||'';var cfError=payload.error||'';var cfErrorDesc=payload.error_description||payload.detail||'';var resolvedOk=false;var resolvedDetail='';var resolvedError='';var resolvedHint='';(function(){if(opsOk==='1'){resolvedOk=true;resolvedDetail='Token type: '+(tokenType||'bearer')+'. Click DONE below to close this window.';}else if(cfError){resolvedOk=false;resolvedError=cfError;resolvedDetail=cfErrorDesc;resolvedHint={invalid_client:'Open /api/charts/chartfox/diagnostic to verify the client_id is registered at chartfox.org.',invalid_request:'Check redirect_uri matches a URI registered with the ChartFox app.',access_denied:'Authorization was denied. Try again from Briefing > Charts.',unsupported_response_type:'ChartFox is rejecting the response_type. Confirm the registration supports PKCE public clients.'}[cfError]||'See /api/charts/chartfox/diagnostic for guidance.';}else if(opsOk==='0'){resolvedOk=false;resolvedDetail=opsDetail||'The authorization could not be completed.';}var status=document.getElementById('status');status.textContent=resolvedOk?'CHARTFOX CONNECTED':'CONNECT FAILED';status.style.color=resolvedOk?'#74ff7a':'#ff7d73';document.getElementById('detail').textContent=resolvedDetail;if(resolvedError){var r=document.createElement('span');r.style.cssText='display:block;margin-top:6px;color:#e7a4a4;font-size:13px';r.textContent='chartfox: '+resolvedError;document.getElementById('detail').after(r);}if(resolvedHint){var h=document.getElementById('hint');h.textContent=resolvedHint;h.style.display='block';}})();try{if(window.opener){window.opener.postMessage({type:'chartfox_oauth_complete',ok:resolvedOk,detail:resolvedDetail,error:resolvedError||null,token_type:tokenType||null},window.location.origin||'*');}}catch(_){}try{var doneBtn=document.getElementById('ops-done');if(doneBtn){doneBtn.addEventListener('click',function(){try{window.close();}catch(_){}});doneBtn.textContent=resolvedOk?'CHARTFOX CONNECTED \u2014 DONE':'CONNECTION FAILED \u2014 CLOSE';doneBtn.style.borderColor=resolvedOk?'#74ff7a':'#ff7d73';}}catch(_){};})();</script></body></html>"""


@app.get("/api/charts/chartfox/status")
@app.get("/api/chartfox/oauth/status")
def chartfox_oauth_status_get_legacy() -> dict:
    return chartfox_oauth_status()


@app.get("/api/charts/chartfox/diagnostic")
@app.get("/api/chartfox/oauth/diagnostic")
def chartfox_oauth_diagnostic_endpoint() -> dict:
    try:
        return chartfox_diagnostics()
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "hints": ["Check app/charts.py initializer ordering; settings_store may be unavailable."]}


@app.get("/api/charts/chartfox/debug")
@app.get("/api/chartfox/debug")
def chartfox_debug_endpoint(request: Request) -> dict:
    try:
        chart_id = str(request.query_params.get("chart_id", "")).strip()
        airport = str(request.query_params.get("airport", "")).strip()
        return chartfox_debug(chart_id=chart_id, airport=airport)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@app.post("/api/charts/chartfox/authorize")
@app.post("/api/chartfox/oauth/authorize")
async def chartfox_oauth_authorize_post(payload: dict | None = None, request: Request = None) -> dict:
    data = payload or {}
    host_header = request.headers.get("host", "") if request else ""
    try:
        port_value = int(load_settings().get("server", {}).get("port", 8080))
    except (TypeError, ValueError):
        port_value = 8080
    return chartfox_oauth_authorize_url(
        redirect_uri=str(data.get("redirect_uri") or ""),
        host_header=host_header,
        port=port_value,
    )


@app.get("/api/charts/chartfox/authorize")
async def chartfox_oauth_authorize_get(redirect_uri: str = "", request: Request = None) -> Response:
    host_header = request.headers.get("host", "") if request else ""
    try:
        port_value = int(load_settings().get("server", {}).get("port", 8080))
    except (TypeError, ValueError):
        port_value = 8080
    result = chartfox_oauth_authorize_url(redirect_uri=redirect_uri, host_header=host_header, port=port_value)
    if not result.get("ok"):
        return JSONResponse(result, status_code=400)
    return RedirectResponse(url=result["url"], status_code=302)


@app.get("/api/charts/chartfox/callback")
@app.get("/api/chartfox/oauth/callback")
async def chartfox_oauth_callback_get(code: str = "", state: str = "", error: str = "") -> HTMLResponse:
    """OAuth callback completion page.

    0.25.49 polish: build a JSON payload describing the result and inject
    it into the callback HTML as an embedded JS string literal in place of
    the previous ``_CHARTFOX_CALLBACK_HTML + urlencode({...})`` pattern.

    The previous implementation concatenated the params onto the end of the
    HTML body (``... </html>ok=1&token_type=Bearer``) which landed them in
    the document body, not in the URL query string. The page-side
    ``URLSearchParams(location.search)`` therefore always returned empty
    values, the page rendered only its default heading, and the close
    timer ran for 1200 ms. The user could neither tell whether sign-in
    succeeded nor correct an obviously-broken registration in time.
    """
    payload: dict = {"ok": "0", "detail": ""}
    if error:
        payload = {"ok": "0", "detail": str(error)}
    elif not code or not state:
        payload = {"ok": "0", "detail": "Missing code or state parameter"}
    else:
        try:
            result = chartfox_oauth_callback(code, state)
        except Exception as exc:
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if not isinstance(result, dict):
            result = {"ok": False, "error": "ChartFox callback returned an unexpected payload."}
        if not result.get("ok"):
            payload = {"ok": "0", "detail": str(result.get("error") or "Authorization failed.")}
        else:
            payload = {"ok": "1", "token_type": str(result.get("token_type") or "Bearer")}

    # Embed as a single-quoted JS string literal. The order matters:
    # backslash first, then close-tag, then apostrophe.
    payload_json = json.dumps(payload, ensure_ascii=False)
    safe_literal = (
        payload_json
        .replace("\\", "\\\\")
        .replace("</", "<\\/")
        .replace("'", "\\'")
    )
    html = _CHARTFOX_CALLBACK_HTML.replace("'__OPSPAYLOAD__'", "'" + safe_literal + "'")
    return HTMLResponse(html, status_code=200)


@app.post("/api/chartfox/oauth/callback")
async def chartfox_oauth_callback_post(payload: dict | None = None) -> dict:
    data = payload or {}
    return chartfox_oauth_callback(str(data.get("code") or ""), str(data.get("state") or ""))


@app.post("/api/charts/chartfox/disconnect")
@app.post("/api/chartfox/oauth/disconnect")
def chartfox_oauth_disconnect_post() -> dict:
    return chartfox_oauth_disconnect()


@app.get("/api/charts/chartfox/search")
def chartfox_airport_search_get(q: str = "", page: int = 1, page_size: int = 10) -> dict:
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = int(page_size)
    except (TypeError, ValueError):
        page_size = 10
    result = chartfox_airport_search(query=q, page=page, page_size=page_size)
    if not result.get("ok"):
        status = 401 if "OAuth" in (result.get("error") or "") else 502
        return JSONResponse(result, status_code=status)
    return result


@app.get("/api/charts/chartfox/chart/{chart_id}")
def chartfox_chart_detail_get(chart_id: str) -> dict:
    result = _chartfox_chart_detail_cached(chart_id)
    if not result.get("ok"):
        status = 401 if "OAuth" in (result.get("error") or "") else (404 if "chart id" in (result.get("error") or "") else 502)
        return JSONResponse(result, status_code=status)
    return result


@app.get("/api/charts/chartfox/file/{chart_id}")
def chartfox_chart_file_proxy_get(chart_id: str, request: Request):
    """v0.25.17: proxy ChartFox chart files through the backend.

    Supports three render modes:
      direct_file — returns binary PDF/IMG bytes
      iframe — returns JSON with redirect_url for iframe embedding
      unavailable — returns JSON error

    Pre-check via Accept: application/json header or ?precheck=1 query param.
    """
    # Support pre-check via Accept header
    is_precheck = False
    accept = request.headers.get("accept", "")
    if "application/json" in accept and "text/html" not in accept:
        is_precheck = True

    # Also support ?precheck=1 query parameter
    if request.query_params.get("precheck") == "1":
        is_precheck = True

    if is_precheck:
        # Lightweight pre-check without downloading the file
        status_result = chartfox_chart_file_status(chart_id)
        rm = status_result.get("render_mode", "unavailable")
        if rm == "direct_file":
            return JSONResponse(status_result)
        elif rm == "iframe":
            return JSONResponse(status_result)
        else:
            return JSONResponse(status_result, status_code=404)

    result = chartfox_chart_file_proxy(chart_id)
    rm = result.get("render_mode", "unavailable")

    if rm == "direct_file":
        max_age = _airac_seconds_remaining()
        return Response(content=result["body"], media_type=result["content_type"],
                        headers={"Content-Disposition": f'inline; filename="{result["filename"]}"',
                                 "Cache-Control": f"private, max-age={max_age}",
                                 "X-OPSROOM-Cache": "hit" if result.get("cached") else "miss",
                                 "X-OPSROOM-Render-Mode": "direct_file"})

    if rm == "iframe":
        # Return JSON with redirect_url; frontend sets iframe src to this URL
        return JSONResponse({
            "ok": True,
            "render_mode": "iframe",
            "redirect_url": result.get("redirect_url", ""),
            "chart_name": result.get("chart_name", ""),
            "airport_icao": result.get("airport_icao", ""),
            "copyright_short": result.get("copyright_short", ""),
        })

    # unavailable
    err = result.get("error", "")
    err_code = result.get("error_code", "")
    if err_code == "auth_missing":
        code = 401
    elif err_code == "no_direct_file":
        code = 404
    elif err_code == "invalid_request":
        code = 400
    elif err_code in ("api_call_failed", "file_fetch_failed", "timeout"):
        code = 502
    else:
        code = 401 if "token" in err.lower() or "oauth" in err.lower() else (404 if "not found" in err.lower() or "chart id" in err.lower() else 502)
    return JSONResponse(result, status_code=code)


@app.get("/api/charts/chartfox/file/{chart_id}/status")
def chartfox_chart_file_status_get(chart_id: str):
    """v0.25.17: lightweight pre-check endpoint for chart file availability.
    Returns render_mode without downloading the actual file.
    Used by the frontend before deciding how to render the chart.
    """
    result = chartfox_chart_file_status(chart_id)
    rm = result.get("render_mode", "unavailable")
    if rm == "unavailable":
        return JSONResponse(result, status_code=404)
    return JSONResponse(result)


@app.put("/api/blackbox/preferences")
def blackbox_preferences_put(payload: dict) -> dict:
    current = load_settings(); integrations = current.setdefault("integrations", {})
    for key in ("black_box_enabled", "black_box_auto_record"):
        if key in payload: integrations[key] = bool(payload[key])
    if "black_box_max_hz" in payload: integrations["black_box_max_hz"] = max(2, min(int(payload["black_box_max_hz"]), 30))
    if "black_box_simconnect_max_hz" in payload: integrations["black_box_simconnect_max_hz"] = max(2, min(int(payload["black_box_simconnect_max_hz"]), 20))
    if "black_box_replay_fps" in payload: integrations["black_box_replay_fps"] = max(10, min(int(payload["black_box_replay_fps"]), 60))
    save_settings(current)
    return blackbox_preferences_get()


@app.post("/api/blackbox/stop")
def blackbox_stop_post() -> dict:
    return black_box_stop_recording("USER REQUEST")


@app.get("/api/blackbox/recordings")
def blackbox_recordings_get(limit: int = Query(default=200, ge=1, le=1000)) -> dict:
    items = black_box_list(limit)
    for item in items:
        flight = item.get("flight") if isinstance(item.get("flight"), dict) else {}
        flight["airline_branding"] = resolve_airline_branding(flight, callsign=str(flight.get("callsign") or ""), airline_code=str(flight.get("airline") or ""))
        item["flight"] = flight
    return {"ok": True, "count": len(items), "items": items, "status": black_box_status(), "replay": black_box_replay_status()}


@app.get("/api/blackbox/replay/status")
def blackbox_replay_status_get() -> dict:
    return black_box_replay_status()


@app.post("/api/blackbox/replay/stop")
def blackbox_replay_stop_post() -> dict:
    return black_box_replay_stop()


@app.post("/api/blackbox/{recording_id}/replay/start")
def blackbox_replay_start_post(recording_id: str, payload: dict | None = None) -> dict:
    data = payload or {}
    result = black_box_replay_start(
        recording_id, speed=float(data.get("speed") or 1.0), loop=bool(data.get("loop")),
        start_elapsed=float(data.get("cursor") or 0.0), force=bool(data.get("force")),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("detail") or "Replay could not start")
    return result


@app.put("/api/blackbox/replay/control")
def blackbox_replay_control_put(payload: dict) -> dict:
    return black_box_replay_control(
        playing=payload.get("playing") if "playing" in payload else None,
        cursor=float(payload["cursor"]) if payload.get("cursor") is not None else None,
        speed=float(payload["speed"]) if payload.get("speed") is not None else None,
        loop=payload.get("loop") if "loop" in payload else None,
    )


@app.get("/api/blackbox/live")
def blackbox_live_get(recording_id: str = "", after_elapsed: float = Query(default=-1.0, ge=-1.0), max_points: int = Query(default=3000, ge=100, le=12000)) -> dict:
    return black_box_live(recording_id=recording_id, after_elapsed=after_elapsed, max_points=max_points)


@app.get("/api/blackbox/{recording_id}")
def blackbox_recording_get(recording_id: str) -> dict:
    try:
        item = black_box_recording(recording_id)
        flight = item.get("flight") if isinstance(item.get("flight"), dict) else {}
        flight["airline_branding"] = resolve_airline_branding(flight, callsign=str(flight.get("callsign") or ""), airline_code=str(flight.get("airline") or ""))
        item["flight"] = flight
        return item
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Black Box recording not found")


@app.get("/api/blackbox/{recording_id}/samples")
def blackbox_samples_get(recording_id: str, max_points: int = Query(default=5000, ge=100, le=50000)) -> dict:
    try:
        rows = black_box_samples(recording_id, max_points=max_points)
        return {"ok": True, "recording_id": recording_id, "count": len(rows), "samples": rows}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Black Box recording not found")


@app.get("/api/blackbox/{recording_id}/download")
def blackbox_download(recording_id: str) -> FileResponse:
    try:
        path = black_box_file(recording_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Black Box recording not found")
    return FileResponse(path, media_type="application/vnd.opsroom.blackbox", filename=path.name)


@app.get("/api/blackbox/{recording_id}/export.csv")
def blackbox_csv(recording_id: str) -> Response:
    try: data = black_box_export_csv(recording_id)
    except FileNotFoundError: raise HTTPException(status_code=404, detail="Black Box recording not found")
    return Response(data, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{recording_id}.csv"'})


@app.get("/api/blackbox/{recording_id}/export.gpx")
def blackbox_gpx(recording_id: str) -> Response:
    try: data = black_box_export_gpx(recording_id)
    except FileNotFoundError: raise HTTPException(status_code=404, detail="Black Box recording not found")
    return Response(data, media_type="application/gpx+xml", headers={"Content-Disposition": f'attachment; filename="{recording_id}.gpx"'})


@app.get("/api/blackbox/{recording_id}/export.kml")
def blackbox_kml(recording_id: str) -> Response:
    try: data = black_box_export_kml(recording_id)
    except FileNotFoundError: raise HTTPException(status_code=404, detail="Black Box recording not found")
    return Response(data, media_type="application/vnd.google-earth.kml+xml", headers={"Content-Disposition": f'attachment; filename="{recording_id}.kml"'})


@app.get("/api/logbook")
def logbook_get(limit: int = 100, q: str = "") -> dict:
    try:
        return logbook_status(limit=limit, query=q)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Logbook unavailable: {type(exc).__name__}: {exc}") from exc


@app.get("/api/economy/status")
def economy_status_get() -> dict:
    try:
        data = logbook_status(limit=5000, query="")
        return economy_status(data.get("entries") or [])
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Economy unavailable: {type(exc).__name__}: {exc}") from exc


@app.post("/api/economy/configure")
def economy_configure_post(payload: dict | None = None) -> dict:
    try:
        data = payload or {}
        return economy_configure(str(data.get("currency") or "EUR"), str(data.get("progression_pace") or "standard"), reset=bool(data.get("reset", False)), fare_settings=data.get("fare_settings") if isinstance(data.get("fare_settings"), dict) else None)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Economy setup failed: {type(exc).__name__}: {exc}") from exc


@app.post("/api/economy/estimate")
def economy_estimate_post(payload: dict | None = None) -> dict:
    try:
        return economy_estimate_statement(payload or {})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Economy estimate failed: {type(exc).__name__}: {exc}") from exc


@app.post("/api/logbook/start")
def logbook_start_post() -> dict:
    try:
        return logbook_start()
    except (ValueError, RuntimeError, ConnectionError, TimeoutError, FileNotFoundError, ImportError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/logbook/landing-latest")
def logbook_latest_landing_get() -> dict:
    try:
        return logbook_latest_landing()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Landing summary unavailable: {type(exc).__name__}: {exc}") from exc


@app.post("/api/logbook/finalize")
def logbook_finalize_post() -> dict:
    try:
        return logbook_finalize()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.delete("/api/logbook/active")
def logbook_discard_delete() -> dict:
    try:
        return logbook_discard()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.delete("/api/logbook/active/force")
def logbook_force_discard_delete() -> dict:
    return logbook_force_discard()


@app.get("/api/logbook/export.csv")
def logbook_csv(q: str = "") -> Response:
    try:
        return Response(
            content=logbook_export_csv(q),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=OPS_ROOM_Logbook.csv", "Cache-Control": "no-store"},
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Logbook export unavailable: {type(exc).__name__}: {exc}") from exc


@app.get("/api/logbook/export.json")
def logbook_json(q: str = "") -> Response:
    try:
        return Response(
            content=logbook_export_json(q),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=OPS_ROOM_Logbook.json", "Cache-Control": "no-store"},
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Logbook export unavailable: {type(exc).__name__}: {exc}") from exc


@app.get("/api/logbook/export.pdf")
def logbook_pdf(q: str = "") -> Response:
    try:
        return Response(content=logbook_export_pdf(q), media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=OPS_ROOM_Logbook.pdf", "Cache-Control": "no-store"})
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Logbook PDF unavailable: {type(exc).__name__}: {exc}") from exc


@app.get("/api/logbook/{entry_id}")
def logbook_entry_get(entry_id: str) -> dict:
    try:
        return {"ok": True, "entry": logbook_get_entry(entry_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("\'")) from exc


@app.get("/api/logbook/{entry_id}/telemetry")
def logbook_entry_telemetry(entry_id: str, max_points: int = 1800) -> dict:
    try:
        return logbook_telemetry(entry_id, max_points=max_points)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc


@app.get("/api/logbook/{entry_id}/export.pdf")
def logbook_entry_pdf(entry_id: str, request: Request) -> Response:
    try:
        base = str(request.base_url).rstrip("/")
        render_url = f"{base}/pirep/{entry_id}?pdf_render=1"
        content = logbook_export_entry_pdf(entry_id, render_url=render_url, settings_payload=_public_settings())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=content, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=OPS_ROOM_PIREP_{entry_id[:8]}.pdf", "Cache-Control": "no-store"})




@app.get("/api/diagnostics/bug-report/status")
def diagnostics_bug_report_status() -> dict:
    return bug_report_status()


@app.post("/api/diagnostics/bug-report/summary")
def diagnostics_bug_report_summary(payload: dict | None = None) -> dict:
    try:
        return bug_report_summary(payload or {})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@app.post("/api/diagnostics/bug-report/send")
def diagnostics_bug_report_send(payload: dict | None = None) -> dict:
    try:
        result = bug_report_send_report(payload or {})
        if not result.get("ok"):
            return result
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@app.post("/api/diagnostics/bug-report/download")
def diagnostics_bug_report_download(payload: dict | None = None) -> FileResponse:
    try:
        path = bug_report_create_zip(payload or {})
        return FileResponse(
            path,
            media_type="application/zip",
            filename=path.name,
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@app.get("/api/telemetry/diagnostics")
def telemetry_diagnostics_get(probe: bool = False) -> dict:
    return telemetry_diagnostics(probe=probe)


@app.post("/api/telemetry/reselect")
def telemetry_reselect_post() -> dict:
    sample = reselect_telemetry("user requested telemetry reselection")
    return {"ok": bool(sample.get("ok")), "sample": sample, "diagnostics": telemetry_diagnostics(False)}


@app.get("/api/notifications")
def notifications_get(after: str = "", limit: int = 100) -> dict:
    return notification_status(after=after, limit=limit)


@app.post("/api/host/attention")
def host_attention_post() -> dict:
    return flash_host()


@app.patch("/api/logbook/{entry_id}")
def logbook_entry_patch(entry_id: str, payload: dict) -> dict:
    try:
        return logbook_update(entry_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc


@app.delete("/api/logbook/{entry_id}")
def logbook_entry_delete(entry_id: str) -> dict:
    try:
        return logbook_delete(entry_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc


@app.get("/api/vpilot/bridge/status")
def vpilot_bridge_status() -> dict:
    return bridge_status()


@app.post("/api/vpilot/bridge/heartbeat")
def vpilot_bridge_heartbeat(payload: dict, request: Request) -> dict:
    _require_local_host(request)
    return record_heartbeat(payload)


@app.post("/api/vpilot/bridge/event")
def vpilot_bridge_event(payload: dict, request: Request) -> dict:
    _require_local_host(request)
    return record_event(payload)


@app.get("/api/vpilot/bridge/commands")
def vpilot_bridge_commands(request: Request) -> dict:
    _require_local_host(request)
    return poll_commands()


@app.get("/api/vpilot/messages")
def vpilot_messages(limit: int = 100, after_id: int = 0) -> dict:
    return message_status(limit=limit, after_id=after_id)


@app.post("/api/vpilot/messages/send")
def vpilot_send_message(payload: dict) -> dict:
    try:
        return queue_command("send_private_message", payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/vpilot/messages/send-radio")
def vpilot_send_radio_message(payload: dict) -> dict:
    try:
        return queue_command("send_radio_message", payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/vpilot/action")
def vpilot_action(payload: dict) -> dict:
    action = str(payload.get("action") or "").lower()
    try:
        if action == "ident":
            return queue_command("squawk_ident", {})
        if action == "mode_c":
            return queue_command("set_mode_c", {"enabled": bool(payload.get("enabled"))})
        raise ValueError("Unsupported vPilot action")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/vpilot/install/status")
def vpilot_install_status(request: Request) -> dict:
    _require_local_host(request)
    return bridge_installation_status()


@app.post("/api/vpilot/install")
def vpilot_install(request: Request) -> dict:
    _require_local_host(request)
    return install_bridge()


@app.delete("/api/vpilot/install")
def vpilot_remove(request: Request) -> dict:
    _require_local_host(request)
    return remove_bridge()


@app.websocket("/ws/vpilot")
async def vpilot_stream(websocket: WebSocket) -> None:
    if not await _authorize_websocket(websocket):
        return
    last_id = 0
    try:
        while True:
            payload = message_status(limit=100, after_id=last_id)
            ids = [int(item.get("id") or 0) for item in payload.get("events", [])]
            if ids:
                last_id = max(last_id, max(ids))
            await websocket.send_json(payload)
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/api/radios")
def radios_get(force_refresh: bool = False) -> dict:
    return radio_state(force=force_refresh)


@app.post("/api/radios/tune")
def radios_tune(payload: dict) -> dict:
    try:
        return set_radio_frequency(int(payload.get("radio") or 1), payload.get("frequency"), str(payload.get("target") or "standby"))
    except (ValueError, RuntimeError, ConnectionError, TimeoutError, FileNotFoundError, ImportError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/radios/swap")
def radios_swap(payload: dict) -> dict:
    try:
        return swap_radio(int(payload.get("radio") or 1))
    except (ValueError, RuntimeError, ConnectionError, TimeoutError, FileNotFoundError, ImportError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/autopilot")
def autopilot_get(force_refresh: bool = False) -> dict:
    return autopilot_state(force=force_refresh)


@app.post("/api/autopilot/target")
def autopilot_target(payload: dict) -> dict:
    try:
        return set_autopilot_target(str(payload.get("target") or ""), payload.get("value"))
    except (ValueError, RuntimeError, ConnectionError, TimeoutError, FileNotFoundError, ImportError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/autopilot/action")
def autopilot_action(payload: dict) -> dict:
    try:
        return set_autopilot_action(str(payload.get("action") or ""), payload.get("enabled"))
    except ValueError as exc:
        code = 409 if str(payload.get("action") or "").lower() == "ap2" else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    except (RuntimeError, ConnectionError, TimeoutError, FileNotFoundError, ImportError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/hoppie/status")
def hoppie_status_get() -> dict:
    return hoppie_status()


@app.post("/api/hoppie/ping")
def hoppie_ping_post() -> dict:
    return hoppie_ping()


@app.post("/api/hoppie/poll")
def hoppie_poll_post() -> dict:
    return hoppie_poll()


@app.post("/api/hoppie/stop")
def hoppie_stop_post() -> dict:
    hoppie_stop()
    return hoppie_status()


@app.post("/api/hoppie/callsign")
def hoppie_callsign_post(payload: dict) -> dict:
    return hoppie_callsign(str(payload.get("callsign") or ""))


@app.post("/api/hoppie/send")
def hoppie_send_post(payload: dict) -> dict:
    try:
        return hoppie_send(str(payload.get("to") or ""), str(payload.get("type") or "telex"), str(payload.get("message") or ""))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/hoppie/info")
def hoppie_info_post(payload: dict) -> dict:
    try:
        return hoppie_info(str(payload.get("kind") or ""), str(payload.get("station") or ""))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc




@app.post("/api/hoppie/pdc/request")
def hoppie_pdc_request_post(payload: dict) -> dict:
    try:
        return hoppie_pdc_request(
            str(payload.get("station") or payload.get("departure") or ""),
            str(payload.get("aircraft") or ""),
            str(payload.get("destination") or ""),
            str(payload.get("departure") or ""),
            str(payload.get("stand") or ""),
            str(payload.get("atis") or ""),
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/hoppie/cpdlc/logon")
def hoppie_cpdlc_logon_post(payload: dict) -> dict:
    try:
        return hoppie_cpdlc_logon(str(payload.get("atc") or ""))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/hoppie/cpdlc/send")
def hoppie_cpdlc_send_post(payload: dict) -> dict:
    try:
        return hoppie_cpdlc_send(str(payload.get("to") or ""), str(payload.get("message") or ""), str(payload.get("mrn") or ""), str(payload.get("response") or ""))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/hoppie/cpdlc/reply")
def hoppie_cpdlc_reply_post(payload: dict) -> dict:
    try:
        return hoppie_cpdlc_reply(str(payload.get("message_id") or ""), str(payload.get("reply") or ""))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.websocket("/ws/hoppie")
async def hoppie_stream(websocket: WebSocket) -> None:
    if not await _authorize_websocket(websocket):
        return
    try:
        while True:
            await websocket.send_json(hoppie_status())
            await asyncio.sleep(2.0)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/api/gsx/status")
def ground_status(force_refresh: bool = False) -> dict:
    return gsx_status(force=force_refresh)


@app.post("/api/gsx/menu/open")
def ground_menu_open() -> dict:
    try:
        return gsx_open_menu()
    except (ValueError, RuntimeError, ConnectionError, TimeoutError, FileNotFoundError, ImportError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/gsx/menu/select")
def ground_menu_select(payload: dict) -> dict:
    try:
        return gsx_select_menu(int(payload.get("index")))
    except (TypeError, ValueError, RuntimeError, ConnectionError, TimeoutError, FileNotFoundError, ImportError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/gsx/service")
def ground_service(payload: dict) -> dict:
    try:
        result = gsx_call_service(str(payload.get("service") or ""), automate=bool(payload.get("automate", True)))
        if not result.get("ok") and not result.get("requires_selection"):
            raise HTTPException(status_code=409, detail=result.get("reason", "GSX service could not be requested"))
        return result
    except HTTPException:
        raise
    except (ValueError, RuntimeError, ConnectionError, TimeoutError, FileNotFoundError, ImportError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/gsx/automation/status")
def ground_automation_status() -> dict:
    return gsx_automation_status()


@app.post("/api/gsx/automation/start")
def ground_automation_start(payload: dict | None = None) -> dict:
    try:
        mode = (payload or {}).get("mode") if isinstance(payload, dict) else None
        return gsx_start_automation(str(mode or "AUTO"))
    except (ValueError, RuntimeError, ConnectionError, TimeoutError, FileNotFoundError, ImportError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/gsx/automation/stop")
def ground_automation_stop() -> dict:
    return gsx_stop_automation()


@app.post("/api/gsx/release")
def ground_release() -> dict:
    try:
        return gsx_release_control()
    except (ValueError, RuntimeError, ConnectionError, TimeoutError, FileNotFoundError, ImportError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.websocket("/ws/gsx")
async def ground_stream(websocket: WebSocket) -> None:
    if not await _authorize_websocket(websocket):
        return
    try:
        while True:
            payload = await asyncio.to_thread(gsx_status, False)
            payload["stream_interval_ms"] = 1000
            await websocket.send_json(payload)
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/api/gsx/receipts")
def ground_receipts(limit: int = 60) -> dict:
    return list_receipts(limit=limit)


@app.get("/api/gsx/receipts/{category}/{filename}")
def ground_receipt_file(category: str, filename: str) -> FileResponse:
    try:
        return FileResponse(receipt_file(category, filename), media_type="text/html")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/announcements/status")
def announcements_status() -> dict:
    return announcement_status()


@app.post("/api/announcements/play")
def announcements_play(payload: dict) -> dict:
    result = announcement_play(str(payload.get("event") or ""), force=bool(payload.get("force", True)), manual=True, record=False)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "Announcement could not be played"))
    return result

@app.post("/api/announcements/boarding-trigger")
def announcements_boarding_trigger(payload: dict) -> dict:
    reason = str(payload.get("reason") or "jetway/stairs requested")
    return announcement_boarding_trigger(reason)



@app.post("/api/announcements/stop")
def announcements_stop() -> dict:
    return announcement_stop()


@app.post("/api/announcements/kill")
def announcements_kill() -> dict:
    return announcement_stop()


@app.post("/api/announcements/pause")
def announcements_pause() -> dict:
    result = announcement_toggle_pause()
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("reason", "No announcement is playing"))
    return result


@app.post("/api/announcements/mute")
def announcements_mute(payload: dict) -> dict:
    value = payload.get("muted") if "muted" in payload else None
    return announcement_set_muted(None if value is None else bool(value))


@app.post("/api/announcements/volume")
def announcements_volume(payload: dict) -> dict:
    current = load_settings()
    integrations = current.setdefault("integrations", {})
    try:
        volume = int(payload.get("volume", integrations.get("announcements_volume", 80)))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Volume must be 0-100")
    integrations["announcements_volume"] = max(0, min(volume, 100))
    save_settings(current)
    announcement_apply_runtime_settings()
    return announcement_status()


@app.post("/api/announcements/airline-override")
def announcements_airline_override(payload: dict) -> dict:
    current = load_settings()
    integrations = current.setdefault("integrations", {})
    raw = str(payload.get("airline") or "").strip().upper()
    airline = "".join(ch for ch in raw if ch.isalnum())[:4]
    integrations["announcements_airline_override"] = airline
    save_settings(current)
    result = announcement_status()
    result["override_saved"] = True
    return result


@app.post("/api/announcements/reset")
def announcements_reset() -> dict:
    announcement_reset()
    return {"ok": True}




@app.get("/api/fenix/status")
def api_fenix_status(force_refresh: bool = False) -> dict:
    return fenix_status(force=force_refresh)


@app.get("/api/fenix/simbrief")
def api_fenix_simbrief() -> dict:
    return fenix_simbrief()


@app.post("/api/fenix/sync-load-targets")
def api_fenix_sync_load_targets() -> dict:
    result = fenix_sync_load_targets()
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("reason", "Fenix EFB load target sync failed"))
    return result


@app.post("/api/fenix/start-gsx-loading")
def api_fenix_start_gsx_loading() -> dict:
    try:
        return fenix_start_gsx_boarding()
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/performance/profiles")
def api_performance_profiles() -> dict:
    return performance_profiles()

@app.post("/api/performance/calculate")
def api_performance_calculate(payload: dict) -> dict:
    try:
        return performance_calculate(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.get("/api/interface/theme")
def interface_theme_get() -> dict:
    return theme_status()


@app.get("/api/interface/theme/background")
def interface_theme_background() -> FileResponse:
    path = airline_background_file()
    if not path:
        raise HTTPException(status_code=404, detail="No airline background image is configured")
    suffix = path.suffix.lower()
    media_type = "image/png" if suffix == ".png" else "image/jpeg"
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-store"})

@app.get("/api/server/info")
def server_info_get() -> dict:
    return build_server_info()


@app.get("/api/server/qr.png")
def server_qr(request: Request) -> Response:
    _require_local_host(request)
    info = build_server_info()
    return Response(content=qr_png(info.get("qr_url") or info["preferred_url"]), media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "version": "0.25.49",
        "product": "OPS ROOM",
        "refresh_seconds": CACHE_SECONDS,
        "simconnect": simconnect_diagnostics(),
    }


@app.post("/api/frontend/log")
async def frontend_log(request: Request) -> dict:
    _require_local_host(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    try:
        import json
        from datetime import datetime, timezone
        log_dir = app_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        row = {
            "time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": str(payload.get("source") or "frontend")[:80],
            "page": str(payload.get("page") or "")[:80],
            "detail": str(payload.get("detail") or "")[:1200],
            "href": str(payload.get("href") or "")[:500],
            "version": str(payload.get("version") or "0.25.49")[:40],
        }
        with (log_dir / "frontend_errors.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return {"ok": True}


@app.get("/api/logos")
def logos() -> dict:
    return logo_status()




@app.get("/api/stands")
def stands() -> dict:
    return stand_sources_status()

@app.get("/api/airports")
def airports(q: str = Query("", min_length=0), limit: int = 40) -> dict:
    return {"items": search_airports(q, limit=limit)}


@app.get("/api/airport-options")
def airport_options(q: str = Query("", min_length=0), limit: int = 12) -> dict:
    q = q.strip()
    data = None
    traffic_counts = None
    if q:
        try:
            data = get_vatsim_data(force=False)
            traffic_counts = airport_traffic_counts(data)
        except Exception:
            traffic_counts = {}
        items = []
        for ap in search_airports(q, limit=limit):
            ap["source"] = "search"
            ap["traffic_count"] = int(traffic_counts.get(ap["ident"], 0)) if traffic_counts else 0
            ap["label"] = f'{ap["ident"]} - {ap["name"]}' + (f' â€¢ {ap["traffic_count"]} VATSIM flights' if ap["traffic_count"] else "")
            items.append(ap)
        return {"ok": True, "source": "search", "default_airport": items[0]["ident"] if items else None, "items": items}

    pos = read_position()
    if pos.get("ok"):
        near = nearest_airports(float(pos["lat"]), float(pos["lon"]), limit=max(limit, 10))
        items = []
        for i, (airport, dist) in enumerate(near[:limit]):
            items.append(airport_option(airport, source="current" if i == 0 else "nearby", distance_nm=dist))
        return {"ok": True, "source": "simconnect", "position": pos, "default_airport": items[0]["ident"] if items else None, "items": items}

    # SimConnect not available: show busiest VATSIM airports by traffic volume.
    try:
        data = get_vatsim_data(force=False)
        items = busiest_airports(data, limit=limit)
        return {"ok": True, "source": "busy", "reason": pos.get("reason"), "default_airport": items[0]["ident"] if items else "EHAM", "items": items}
    except Exception as exc:
        fallback = []
        for code in ["EHAM", "EDDF", "EGLL", "LFPG", "OMDB", "KJFK", "KLAX", "LOWW", "LEMD", "VHHH"][:limit]:
            ap = load_airports().get(code)
            if ap:
                fallback.append(airport_option(ap, source="fallback"))
        return {"ok": False, "source": "fallback", "reason": str(exc), "default_airport": fallback[0]["ident"] if fallback else "EHAM", "items": fallback}


@app.get("/api/airport/{icao}")
def airport(icao: str) -> dict:
    ap = load_airports().get(icao.upper())
    if not ap:
        raise HTTPException(status_code=404, detail="Airport not found")
    return airport_to_dict(ap)


@app.get("/api/simconnect/status")
def simconnect_status() -> dict:
    return {"ok": True, "runtime": simconnect_diagnostics()}


@app.get("/api/current-location")
def current_location() -> dict:
    pos = read_position(force=True)
    if not pos.get("ok"):
        return {
            "ok": False,
            "reason": pos.get("reason", "Unknown SimConnect error"),
            "diagnostics": pos.get("diagnostics", simconnect_diagnostics()),
        }
    nearest = nearest_airport(float(pos["lat"]), float(pos["lon"]))
    if not nearest:
        return {"ok": False, "reason": "No airports loaded"}
    airport, dist = nearest
    return {
        "ok": True,
        "position": pos,
        "nearest_airport": airport_to_dict(airport),
        "distance_nm": round(dist, 2),
        "label": f"Current location: {airport.ident} - {airport.name}",
    }




@app.get("/api/camera/target")
def camera_target_get() -> dict:
    return {"ok": True, "target": get_target()}


@app.post("/api/camera/target")
def camera_target_post(payload: dict) -> dict:
    target = set_target(payload)
    bridge = {}
    try:
        if isinstance(payload, dict) and (payload.get("callsign") or payload.get("label") or payload.get("target")):
            bridge = camera_bridge_start()
    except Exception as exc:
        bridge = {"ok": False, "error": str(exc)}
    return {"ok": True, "target": target, "bridge": bridge}


@app.post("/api/camera/view")
def camera_view_post(payload: dict) -> dict:
    target = set_camera_view_state(payload or {})
    return {"ok": True, "target": target}


@app.post("/api/camera/reset-view")
def camera_reset_view_post() -> dict:
    target = reset_camera_view_state()
    return {"ok": True, "target": target}


@app.post("/api/camera/release")
def camera_release_post() -> dict:
    # The legacy external bridge polls this command, returns the camera to the user aircraft/cockpit fallback, then releases owner control.
    target = release_camera_state()
    return {"ok": True, "target": target, "bridge": camera_bridge_status(), "release_mode": "return_to_cockpit"}


@app.post("/api/camera/bridge/release")
def camera_bridge_release_post() -> dict:
    # Explicit UI release path. Keep the bridge process alive so the next FIDS aircraft
    # selection can reacquire without forcing the user to restart the bridge.
    target = release_camera_state()
    return {"ok": True, "target": target, "bridge": camera_bridge_status()}


@app.get("/api/camera/bridge/status")
def camera_bridge_status_get() -> dict:
    data = camera_bridge_status()
    data["target"] = get_target()
    return data


@app.post("/api/camera/bridge/start")
def camera_bridge_start_post() -> dict:
    return camera_bridge_start()


@app.post("/api/camera/bridge/stop")
def camera_bridge_stop_post() -> dict:
    return camera_bridge_stop()


@app.get("/api/camera/bridge/log")
def camera_bridge_log_get(lines: int = Query(120, ge=20, le=800)) -> dict:
    return camera_bridge_log_tail(lines)




@app.get("/api/opsroom-bridge/status")
def opsroom_bridge_status() -> dict:
    root = _ops_room_bridge_root()
    native_wasm = (root / "Modules" / "OpsRoomBridge2024.wasm")
    if not native_wasm.exists():
        native_wasm = root / "modules" / "OpsRoomBridge2024.wasm"
    api_wasm = root / "SimObjects" / "Misc" / "OPS_ROOM_Native_API" / "wasm" / "OpsRoomNativeApi2024.wasm"
    api_systems_cfg = root / "SimObjects" / "Misc" / "OPS_ROOM_Native_API" / "systems.cfg"
    log_tail = _charts_bridge_log_tail(120)
    runtime = native_bridge_runtime_status()
    installed = root.exists() and native_wasm.exists()
    bridge_ready = bool(runtime.get("loaded") and runtime.get("connected"))
    return {
        "ok": True,
        "root": str(root),
        "checked_roots": [str(x) for x in _ops_room_bridge_candidates()],
        "installed": installed,
        "ready": bridge_ready,
        "native_bridge": {
            "available": native_wasm.exists(),
            "path": str(native_wasm),
            "type": "msfs2024_wasm_standalone_module",
            "runtime": runtime,
            "logs": log_tail,
        },
        "native_api_module": {
            "available": api_wasm.exists() and api_systems_cfg.exists(),
            "wasm_path": str(api_wasm),
            "systems_cfg": str(api_systems_cfg),
            "loaded": bool(runtime.get("native_api_loaded")),
            "activation_attempted": bool(runtime.get("native_api_activation_attempted")),
            "activation_hr": runtime.get("native_api_activation_hr"),
            "activation_message": runtime.get("native_api_activation_message"),
            "object_id": runtime.get("native_api_object_id"),
        },
        "camera_bridge": {
            "mode": "legacy_external_camera_bridge",
            "external_exe": True,
            "native_wasm_disabled": True,
            "status": camera_bridge_status(),
            "runtime": runtime,
        },
        "charts_bridge": {
            "mode": "community_wasm_client_data",
            "available": native_wasm.exists(),
            "ready": bool(runtime.get("chart_ready")),
            "items": runtime.get("chart_items") or [],
            "logs": log_tail,
        },
        "message": "Native MSFS Charts/Camera WASM system is disabled by default; camera uses the restored external bridge provider.",
    }



@app.get("/api/charts/briefing")
def charts_briefing_get() -> dict:
    return briefing_charts()


# 0.25.49 polish: removed six legacy OAuth handlers that were silently
# overriding the canonical block above (lines 1185-1316). Python silently
# rebinds the function-name, so the most-recent ``def chartfox_oauth_callback_get``
# wins at import time, and FastAPI then serves the LATEST-registered handler
# for``/api/chartfox/oauth/callback``. The legacy ``def chartfox_oauth_callback_get``
# here returned a JSON dict instead of the HTMLResponse that chartfox.org's
# redirect needs, so the OAuth callback window opened, showed raw JSON, and
# closed immediately without surfacing success/failure. Removing the duplicates
# restores the HTMLResponse handler.


@app.get("/api/charts/chartfox/grouped/{icao}")
def charts_chartfox_grouped_get(icao: str) -> dict:
    return _chartfox_airport_grouped_charts_cached(icao)


@app.get("/api/charts/ownship")
def charts_ownship_get() -> dict:
    return ownship_overlay_status()

@app.post("/api/charts/overlay/compute")
def charts_overlay_compute_post(body: dict[str, Any]) -> dict[str, Any]:
    georef = body.get("georeference") or {}
    width = float(body.get("display_width_px") or 800)
    height = float(body.get("display_height_px") or 600)
    return _chartfox_overlay_compute(georef, width, height)

@app.get("/api/raas/status")
def raas_status_get() -> dict:
    return raas_status()


@app.post("/api/raas/start")
def raas_start_post() -> dict:
    return raas_start()


@app.post("/api/raas/stop")
def raas_stop_post() -> dict:
    return raas_stop()


@app.post("/api/raas/test")
def raas_test_post() -> dict:
    return raas_test()


@app.post("/api/raas/enabled")
def raas_enabled_post(payload: dict) -> dict:
    return raas_set_enabled(bool((payload or {}).get("enabled", True)))


@app.post("/api/raas/voice-path")
def raas_voice_path_post(payload: dict) -> dict:
    return raas_set_voice_path(str((payload or {}).get("path") or ""))


@app.post("/api/raas/unit")
def raas_unit_post(payload: dict) -> dict:
    return raas_set_unit(str((payload or {}).get("unit") or "ft"))


@app.get("/api/raas/audio/{clip_name}")
def raas_audio_clip_get(clip_name: str) -> FileResponse:
    path = raas_clip_path_for_name(clip_name)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="RAAS phrase clip is not available")
    return FileResponse(path, media_type="audio/ogg", filename=path.name)


@app.get("/api/opsroom-bridge/charts/{icao}")
def opsroom_bridge_charts(icao: str) -> dict:
    airport = str(icao or "").upper().strip()
    status = opsroom_bridge_status()
    return {
        "ok": False,
        "airport": airport,
        "bridge": status,
        "ready": False,
        "items": [],
        "message": "Native MSFS Charts API browser-image path is disabled. OPS ROOM browser charts must use browser-readable chart sources or user-imported PDFs/images.",
        "logs": [],
        "runtime": native_bridge_runtime_status(),
    }


@app.get("/api/scratchpad/status")
def scratchpad_status_get() -> dict:
    return scratchpad_status()


@app.get("/api/scratchpad/page/{page_id}")
def scratchpad_page_get(page_id: str) -> dict:
    return scratchpad_get_page(page_id)


@app.post("/api/scratchpad/page/{page_id}")
def scratchpad_page_post(page_id: str, payload: dict | None = None) -> dict:
    return scratchpad_save_page(page_id, payload or {})


@app.delete("/api/scratchpad/page/{page_id}")
def scratchpad_page_delete(page_id: str) -> dict:
    return scratchpad_clear_page(page_id)


@app.get("/api/weather/{icao}")
def weather(icao: str, force_refresh: bool = False) -> dict:
    vatsim = _vatsim_atis_for_airport(icao, force=force_refresh)
    real = fetch_realworld_atis(icao, force=force_refresh)
    return {
        "metar": fetch_metar(icao, force=force_refresh),
        "vatsim_atis": vatsim,
        "realworld_atis": real,
        "atis": vatsim if vatsim.get("available") else real,
        "atis_source": "VATSIM" if vatsim.get("available") else "REALWORLD",
    }


@app.get("/api/board")
def board(
    airport: str = Query(..., description="ICAO airport, e.g. EHAM"),
    force_refresh: bool = False,
    upcoming_minutes: int = Query(120, ge=30, le=720),
    previous_minutes: int = Query(60, ge=0, le=240),
) -> dict:
    try:
        data = get_vatsim_data(force=force_refresh)
        settings = load_settings()
        cid = str(settings.get("identity", {}).get("vatsim_cid") or "")
        simbrief_user = str(settings.get("identity", {}).get("simbrief_user_id") or "")
        plan = cached_plan(simbrief_user) if simbrief_user else None
        user_callsign = str((plan or {}).get("callsign") or "")
        return build_board(data, airport, upcoming_minutes=upcoming_minutes, previous_minutes=previous_minutes, user_cid=cid, user_callsign=user_callsign)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
