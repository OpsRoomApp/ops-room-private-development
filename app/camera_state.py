from __future__ import annotations
from datetime import datetime, timezone
from typing import Any

DEFAULT_VIEW: dict[str, Any] = {
    "mode": "tail_follow",
    "distance": 55.0,
    "height": 9.0,
    "sideOffset": 0.0,
    "pitch": -7.0,
    "orbitAngle": 180.0,
    "smoothing": 0.35,
}

CURRENT_TARGET: dict[str, Any] = {
    "callsign": None,
    "airport": "",
    "source": "",
    "label": "",
    "latitude": None,
    "longitude": None,
    "altitude": None,
    "object_id": None,
    "tab": "",
    "command": "idle",
    "released": True,
    "view": dict(DEFAULT_VIEW),
    "updated_at": None,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_callsign(value: Any) -> str:
    text = str(value or "").strip().upper()
    return "".join(ch for ch in text if ch.isalnum())


def _num(value: Any, fallback: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _view_from_payload(payload: dict[str, Any] | None, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    source = payload.get("view") if isinstance(payload.get("view"), dict) else payload
    view = dict(DEFAULT_VIEW)
    if previous:
        view.update({k: previous.get(k, v) for k, v in DEFAULT_VIEW.items()})

    mode = str(source.get("mode", view["mode"]) or view["mode"]).strip().lower().replace("-", "_")
    aliases = {"front_follow": "front_34", "tower_drone": "tower_static", "runway_end_drone": "runway_end_static", "apron_drone": "apron_static"}
    mode = aliases.get(mode, mode)
    if mode not in {"external_free", "tail_follow", "left_spotter", "right_spotter", "front_34", "tower_static", "runway_end_static", "apron_static", "orbit"}:
        mode = "tail_follow"
    view["mode"] = mode
    view["distance"] = max(5.0, min(1200.0, _num(source.get("distance"), view["distance"]) or view["distance"]))
    view["height"] = max(-50.0, min(500.0, _num(source.get("height"), view["height"]) or view["height"]))
    view["sideOffset"] = max(-600.0, min(600.0, _num(source.get("sideOffset"), view["sideOffset"]) or view["sideOffset"]))
    view["pitch"] = max(-89.0, min(45.0, _num(source.get("pitch"), view["pitch"]) or view["pitch"]))
    view["orbitAngle"] = (_num(source.get("orbitAngle"), view["orbitAngle"]) or view["orbitAngle"]) % 360.0
    view["smoothing"] = max(0.0, min(0.98, _num(source.get("smoothing"), view["smoothing"]) or view["smoothing"]))
    return view


def set_target(payload: dict[str, Any]) -> dict[str, Any]:
    payload = payload or {}
    previous_view = CURRENT_TARGET.get("view") if isinstance(CURRENT_TARGET.get("view"), dict) else DEFAULT_VIEW
    callsign = _clean_callsign(payload.get("callsign") or payload.get("label") or payload.get("target") or payload.get("flight"))

    CURRENT_TARGET.clear()
    CURRENT_TARGET.update({
        "callsign": callsign or None,
        "airport": str(payload.get("airport") or "").strip().upper(),
        "source": str(payload.get("source") or "opsroom").strip(),
        "label": str(payload.get("label") or callsign or "").strip().upper(),
        "latitude": _num(payload.get("latitude")),
        "longitude": _num(payload.get("longitude")),
        "altitude": _num(payload.get("altitude")),
        "object_id": _num(payload.get("object_id") or payload.get("objectId") or payload.get("simObjectId") or payload.get("sim_object_id")),
        "tab": str(payload.get("tab") or "").strip().lower(),
        "command": "watch",
        "released": False,
        "view": _view_from_payload(payload, previous_view),
        "updated_at": _now(),
    })
    return dict(CURRENT_TARGET)


def set_view(payload: dict[str, Any]) -> dict[str, Any]:
    previous_view = CURRENT_TARGET.get("view") if isinstance(CURRENT_TARGET.get("view"), dict) else DEFAULT_VIEW
    CURRENT_TARGET["view"] = _view_from_payload(payload or {}, previous_view)
    CURRENT_TARGET["command"] = "view"
    if CURRENT_TARGET.get("callsign"):
        CURRENT_TARGET["released"] = False
    CURRENT_TARGET["updated_at"] = _now()
    return dict(CURRENT_TARGET)


def reset_view() -> dict[str, Any]:
    CURRENT_TARGET["view"] = dict(DEFAULT_VIEW)
    CURRENT_TARGET["command"] = "view"
    CURRENT_TARGET["updated_at"] = _now()
    return dict(CURRENT_TARGET)


def release_camera() -> dict[str, Any]:
    previous_view = CURRENT_TARGET.get("view") if isinstance(CURRENT_TARGET.get("view"), dict) else DEFAULT_VIEW
    CURRENT_TARGET.clear()
    CURRENT_TARGET.update({
        "callsign": None,
        "airport": "",
        "source": "opsroom",
        "label": "",
        "latitude": None,
        "longitude": None,
        "altitude": None,
        "object_id": None,
        "tab": "",
        "command": "release",
        "released": True,
        "view": dict(previous_view),
        "updated_at": _now(),
    })
    return dict(CURRENT_TARGET)


def get_target() -> dict[str, Any]:
    return dict(CURRENT_TARGET)
