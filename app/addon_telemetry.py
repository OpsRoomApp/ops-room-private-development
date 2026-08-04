from __future__ import annotations

"""Aircraft-specific read-only enrichment for Flight Watch and Black Box."""

import math
import time
from typing import Any, Callable

from .aircraft_adapter_catalog import FAMILY_LABELS, LVarSpec, detect_family, specs_for_family
from .aircraft_adapter_installer import ADAPTER_VERSION, load_registry

_LAST_IDENTITY: dict[str, Any] = {}
_LAST_IDENTITY_AT = 0.0

# Family-detection hysteresis (Tier-1 stutter/flapping fix).
# detect_family() is a PURE function of the aircraft identity and is intentionally left
# untouched (its unit-tested outputs, e.g. Aerosoft A340 -> generic, must not change). The
# instability is at the CALLER: at startup the SimConnect/FSUIPC aircraft title arrives
# intermittently empty, so a per-sample detect_family() flaps generic<->supported every
# sample, flipping the whole adapter path (supported reads/merges the LVar spec set; generic
# early-returns) and churning telemetry + the frontend view every frame.
#
# A Fenix identity can also briefly degrade to a blank, placeholder, or an unbranded A319/A320/
# A321 model during loading. Grace is deliberately caller-side, bounded, and measured from the
# last discriminating Fenix observation: transient samples never extend it.
FAMILY_IDENTITY_GRACE_SECONDS = 5.0
_FENIX_TRANSIENT_IDENTITY_TOKENS = frozenset({
    "A319", "A320", "A321", "A32X", "AIRBUS", "CEO", "DEFAULT", "GENERIC", "NA",
    "NEO", "NONE", "PLACEHOLDER", "UNAVAILABLE", "UNKNOWN",
})
_STICKY_FAMILY: dict[str, Any] | None = None
_STICKY_FAMILY_AT = 0.0


def _stable_family(aircraft: dict[str, Any] | None) -> dict[str, Any]:
    """Return pure family detection with bounded caller-side Fenix identity grace.

    Supported identities always switch immediately. A prior Fenix family alone survives a
    blank, placeholder, or unbranded A319/A320/A321 identity for the fixed grace interval;
    a generic identity with any other discriminator is an immediate aircraft change.
    """
    global _STICKY_FAMILY, _STICKY_FAMILY_AT
    family = detect_family(aircraft)
    now = time.monotonic()

    if family["supported"]:
        _STICKY_FAMILY = dict(family)
        _STICKY_FAMILY_AT = now if family["key"] == "fenix_a32x" else 0.0
        return family

    identity_text = str(family.get("aircraft_text") or "").strip()
    identity_tokens = frozenset(
        token for token in identity_text.replace("N/A", "NA").replace("-", " ").replace("/", " ").split() if token
    )
    is_fenix_transient = not identity_text or (
        bool(identity_tokens) and identity_tokens <= _FENIX_TRANSIENT_IDENTITY_TOKENS
    )
    sticky_fenix = _STICKY_FAMILY if _STICKY_FAMILY and _STICKY_FAMILY.get("key") == "fenix_a32x" else None

    if sticky_fenix and is_fenix_transient:
        elapsed = now - _STICKY_FAMILY_AT
        if 0.0 <= elapsed < FAMILY_IDENTITY_GRACE_SECONDS:
            return dict(sticky_fenix)
        # Repeated partial samples cannot perpetually extend the Fenix grace window.
        _STICKY_FAMILY = None
        _STICKY_FAMILY_AT = 0.0
        return family

    if not identity_text and _STICKY_FAMILY and _STICKY_FAMILY.get("supported"):
        # Preserve the existing blank-identity hysteresis for non-Fenix adapters.
        return dict(_STICKY_FAMILY)

    # A stable non-empty generic identity (or grace expiry) is a real generic selection.
    _STICKY_FAMILY = None
    _STICKY_FAMILY_AT = 0.0
    return family

# Tier-2 adapter session lock. Once a supported adapter has been confirmed by
# successful LVar reads, this lock holds that family until the aircraft identity
# genuinely changes (different title/model/type). Prevents transient SimConnect
# identity degradation (e.g. Fenix title dropping "FENIX" under load) from
# causing adapter flapping mid-flight. The two-tier system:
#   Tier 1: _stable_family()  — per-sample grace for transient blanks (5s)
#   Tier 2: _LOCKED_ADAPTER   — session-level hold after confirmed LVar activity
_LOCKED_ADAPTER: dict[str, Any] | None = None
_LOCKED_ADAPTER_IDENTITY: dict[str, Any] | None = None


def _aircraft_changed(current: dict[str, Any], previous: dict[str, Any]) -> bool:
    """Detect a genuine aircraft type change across identifying fields.

    Returns True only when a non-empty field in both sides disagrees, so a
    transient blank on either side never triggers a false change detection.
    """
    for key in ("title", "model", "type", "manufacturer", "atc_model"):
        a = str(current.get(key) or "").strip().upper()
        b = str(previous.get(key) or "").strip().upper()
        if a and b and a != b:
            return True
    return False


_PMDG_META: dict[str, tuple[str, str]] = {
    "battery": ("BATTERY", "bool"), "apu_selector": ("APU SELECTOR", "enum"), "apu_running": ("APU", "bool"),
    "external_power_1": ("PRIMARY EXTERNAL POWER", "bool"), "external_power_2": ("SECONDARY EXTERNAL POWER", "bool"),
    "seatbelt_selector": ("SEAT BELTS", "enum"), "beacon": ("BEACON LIGHT", "bool"), "taxi_light": ("TAXI LIGHT", "bool"),
    "strobe": ("STROBE LIGHT", "bool"), "gear_handle": ("GEAR SELECTED", "enum"), "autobrake": ("AUTOBRAKE", "enum"),
    "master_warning": ("MASTER WARNING", "bool"), "master_caution": ("MASTER CAUTION", "bool"),
    "flap_handle": ("FLAPS SELECTED", "enum"), "speedbrake_handle": ("SPEEDBRAKE", "number"),
    "engine_1_master": ("ENGINE 1 FUEL CONTROL", "bool"), "engine_2_master": ("ENGINE 2 FUEL CONTROL", "bool"),
    "parking_brake": ("PARKING BRAKE", "bool"), "ap1": ("AUTOPILOT LEFT", "bool"), "ap2": ("AUTOPILOT RIGHT", "bool"),
    "autothrottle": ("AUTOTHROTTLE", "bool"), "lnav": ("LNAV", "bool"), "vnav": ("VNAV", "bool"),
    "flch": ("FLCH", "bool"), "loc": ("LOC", "bool"), "app": ("APP", "bool"),
    "mcp_speed": ("MCP SPEED", "number"), "mcp_heading": ("MCP HEADING", "number"),
    "mcp_altitude": ("MCP ALTITUDE", "number"), "mcp_vs": ("MCP V/S", "number"),
    "door_1l": ("DOOR 1L", "enum"), "door_1r": ("DOOR 1R", "enum"), "cargo_fwd": ("FORWARD CARGO DOOR", "enum"), "cargo_aft": ("AFT CARGO DOOR", "enum"),
}

_PMDG_META_VALUES: dict[str, dict[str, str]] = {
    "door_1l": {"0": "OPEN", "1": "CLOSED", "2": "CLOSED/ARMED", "3": "CLOSING", "4": "OPENING"},
    "door_1r": {"0": "OPEN", "1": "CLOSED", "2": "CLOSED/ARMED", "3": "CLOSING", "4": "OPENING"},
    "cargo_fwd": {"0": "OPEN", "1": "CLOSED", "2": "CLOSED/ARMED", "3": "CLOSING", "4": "OPENING"},
    "cargo_aft": {"0": "OPEN", "1": "CLOSED", "2": "CLOSED/ARMED", "3": "CLOSING", "4": "OPENING"},
    "seatbelt_selector": {"0": "OFF", "1": "AUTO", "2": "ON"},
    "gear_handle": {"0": "UP", "1": "DOWN"},
    "flap_handle": {"0": "UP", "1": "1", "2": "5", "3": "15", "4": "20", "5": "25", "6": "30"},
}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _identity(sample: dict[str, Any]) -> dict[str, Any]:
    global _LAST_IDENTITY, _LAST_IDENTITY_AT
    aircraft = sample.get("aircraft") if isinstance(sample.get("aircraft"), dict) else {}
    if aircraft:
        _LAST_IDENTITY = dict(aircraft); _LAST_IDENTITY_AT = time.monotonic(); return aircraft
    if _LAST_IDENTITY and time.monotonic() - _LAST_IDENTITY_AT < 5.0:
        return dict(_LAST_IDENTITY)
    try:
        from .simconnect_position import read_position
        extended = read_position(force=False)
        aircraft = extended.get("aircraft") if isinstance(extended.get("aircraft"), dict) else {}
        if aircraft:
            _LAST_IDENTITY = dict(aircraft); _LAST_IDENTITY_AT = time.monotonic()
    except Exception:
        aircraft = {}
    return aircraft


# Canonical unit contract (Black Box telemetry & UI fix - design "Fix Implementation 0").
# Each numeric ``LVarSpec.unit`` tag maps to the one canonical destination domain every
# source must agree on. ``scale``/``offset``/``clamp`` in _normalized convert the *raw*
# L:Var into the unit's natural domain; this table is the *final* guarantee of that domain
# so an adapter can never emit a field on the wrong scale regardless of the L:Var's native
# units. Keyed by the destination field's unit (Task 3), not by the raw L:Var.
_CANONICAL_UNIT_DOMAINS: dict[str, tuple[float, float]] = {
    "unit_interval": (-1.0, 1.0),        # pilot stick/pedal position
    "percent": (0.0, 100.0),             # brake / flap-handle / spoiler percent
    "signed_percent": (-25.0, 110.0),    # throttle lever (reverse..max)
    "deflection_percent": (-100.0, 100.0),  # actual control-surface deflection
}

# Boundary tolerance separating "clamp at a validated boundary" from "semantically
# impossible" (Req 2.9). A value within this margin of a domain edge is treated as a
# rounding artefact and clamped to the edge; anything grossly outside the domain - or
# non-finite - is rejected as unavailable (None), never fabricated into a neutral/zero.
# Matches the epsilon the existing ``spec.clamp`` branch below already uses.
_CANONICAL_UNIT_EPS = 1e-6


def _apply_canonical_unit(unit: str, value: Any) -> Any:
    """Guarantee ``value`` lands in the canonical domain for ``unit`` (or None).

    A strict no-op for the default ``"raw"`` tag and for discrete ``"enum"``/``"bool"``
    states (and any unrecognised tag), so every spec that has not opted into a numeric
    canonical domain is returned untouched. For a numeric unit: non-finite or grossly
    out-of-domain input -> ``None`` (unavailable, never a fabricated zero/neutral); a
    value slightly past a boundary is clamped to that boundary; a legitimate in-domain
    ``0.0`` is preserved as ``0.0``.
    """
    if unit != "index" and unit not in _CANONICAL_UNIT_DOMAINS:
        return value  # raw / enum / bool / unset / unknown -> untouched (no-op)
    if value is None:
        return None
    number = _number(value)
    if number is None:  # non-finite (NaN / inf) is semantically impossible -> unavailable
        return None
    if unit == "index":
        # Detent index: integer-ish and >= 0. A negative index is impossible -> None.
        index = int(round(number))
        return index if index >= 0 else None
    low, high = _CANONICAL_UNIT_DOMAINS[unit]
    if number < low - _CANONICAL_UNIT_EPS or number > high + _CANONICAL_UNIT_EPS:
        return None  # grossly out-of-domain -> unavailable rather than made plausible
    return max(low, min(high, number))  # clamp rounding noise to the validated boundary


def _normalized(spec: LVarSpec, raw: Any) -> Any:
    number = _number(raw)
    if number is None:
        return None
    number = number * spec.scale + spec.offset
    if spec.kind == "bool":
        return bool(abs(number) >= 0.5)
    if spec.kind == "enum":
        return int(round(number))
    if spec.kind == "pulse":
        return int(round(number))
    if spec.kind == "percent":
        return max(0.0, min(100.0, number))
    if spec.clamp:
        low, high = spec.clamp
        if number < low - 1e-6 or number > high + 1e-6:
            return None
        number = max(low, min(high, number))
    # Final canonical-domain guarantee keyed by the destination field's unit tag.
    # No-op for the default "raw" unit, so all existing specs are byte-for-byte unchanged.
    return _apply_canonical_unit(spec.unit, number)


# Fields an aircraft-specific validated adapter value is allowed to overwrite UNCONDITIONALLY
# (design "Fix Implementation 2" -> authoritative set; root cause 2). A validated adapter value
# - INCLUDING a fresh idle 0.0 - is authoritative over a stale generic value and must NOT fall
# through to the weak "replace-only-near-zero" branch below (which drops an authoritative 0).
_AUTHORITATIVE_TOP_LEVEL: frozenset[str] = frozenset({
    # Pre-existing authoritative discrete selections / already-canonical validated controls.
    "flap_index", "flap_handle_percent", "spoiler_percent", "parking_brake",
    "pilot_aileron_input", "pilot_elevator_input", "pilot_rudder_input",
    "actual_rudder_percent", "brake_left_percent", "brake_right_percent",
    # Task 6.1 additions - continuous throttle levers (commanded/engine throttle_n_percent AND the
    # physical pilot lever pilot_throttle_n_percent) so a validated adapter idle 0 wins per engine
    # (fixes Mechanism C). Each lever 1..4 is a DISTINCT independent axis - promoting them here
    # never coalesces independent signals (each spec targets its own top_level).
    "throttle_1_percent", "throttle_2_percent", "throttle_3_percent", "throttle_4_percent",
    "pilot_throttle_1_percent", "pilot_throttle_2_percent",
    "pilot_throttle_3_percent", "pilot_throttle_4_percent",
    # ... and the INDEPENDENT first-officer sidestick axes (captain axes already listed above);
    # an FBW single stick fills the captain axes only and the FO axes are never synthesised.
    "pilot_aileron_input_fo", "pilot_elevator_input_fo",
})


def _record_control_provenance(result: dict[str, Any], field: str, spec: LVarSpec, source: str) -> None:
    """Attach an additive ``control_provenance`` entry (``field -> {source, role, validated}``).

    Built during the merge for UI/recorder labeling (design "Fix Implementation 2" -> Provenance;
    recorded as a top-level field by Task 7). Additive and OPTIONAL: it never disturbs the existing
    ``adapter_status`` / ``provider_categories`` blocks. Called only when a value is actually
    written, so every merged top-level field carries a record of the source/role that set it.
    """
    provenance = result.get("control_provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    provenance[field] = {
        "source": source or "AIRCRAFT LVAR",
        "role": spec.role or "",
        "validated": bool(spec.validated),
    }
    result["control_provenance"] = provenance


def _provenance_allows_overwrite(result: dict[str, Any], field: str, spec: LVarSpec) -> bool:
    """Encode the Req 2.9 fallback precedence for a single field.

    A verified aircraft-specific (``validated``) source that has already written this field this
    pass is authoritative; a gated/fallback candidate (``validated=False``) MUST NOT overwrite it -
    not even a fresh authoritative ``0``. A validated source may still refine another validated
    source, and any source may fill a field only a fallback previously wrote. Independent axes each
    own a DISTINCT ``top_level``, so this per-field guard never merges two independent axes.
    """
    provenance = result.get("control_provenance")
    existing = provenance.get(field) if isinstance(provenance, dict) else None
    if not existing:
        return True  # no source has claimed this field yet this pass
    if existing.get("validated") and not spec.validated:
        return False  # a gated/fallback candidate cannot overwrite a fresh authoritative value
    return True


def _merge_top_level(result: dict[str, Any], spec: LVarSpec, value: Any, source: str = "") -> bool:
    key = spec.top_level
    if not key or value is None:
        return False
    # Req 2.9 fallback precedence: never let a gated/fallback candidate overwrite a value a
    # validated authoritative source already wrote this pass (a fresh authoritative 0 included).
    if not _provenance_allows_overwrite(result, key, spec):
        return False
    # Aircraft-specific discrete selections and validated continuous controls are authoritative:
    # a validated adapter value (INCLUDING a fresh idle 0.0) overwrites a stale generic value and
    # is not gated by the weak near-zero branch below. 0.0 is written, never coerced to None (the
    # ``value is None`` guard above already returned for genuine unavailability).
    if key in _AUTHORITATIVE_TOP_LEVEL:
        result[key] = value
        _record_control_provenance(result, key, spec, source)
        return True
    if key.startswith("ap_selected_"):
        if key == "ap_selected_heading_deg" or abs(float(value)) > 0.001:
            autopilot = dict(result.get("autopilot") or {})
            nested = {
                "ap_selected_altitude_ft":"selected_altitude_ft", "ap_selected_heading_deg":"selected_heading_deg",
                "ap_selected_speed_kts":"selected_speed_kts", "ap_selected_vertical_speed_fpm":"selected_vertical_speed_fpm",
            }.get(key)
            if nested: autopilot[nested] = value; result["autopilot"] = autopilot
            result[key] = value
            _record_control_provenance(result, key, spec, source)
            return True
        return False
    current = result.get(key)
    try:
        if current is None or abs(float(current)) <= 0.001 < abs(float(value)):
            result[key] = value
            _record_control_provenance(result, key, spec, source)
            return True
    except (TypeError, ValueError):
        if current is None:
            result[key] = value
            _record_control_provenance(result, key, spec, source)
            return True
    return False


def _merge_pmdg_sdk(result: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    try:
        from .pmdg777_sdk import snapshot as pmdg_snapshot, status as pmdg_status
        sdk = pmdg_snapshot()
        status = pmdg_status()
    except Exception as exc:
        return False, {"receiving": False, "reason": f"{type(exc).__name__}: {exc}"}
    if not sdk.get("ok") or not sdk.get("fresh"):
        return False, status
    systems = dict(result.get("systems") or {})
    pmdg_systems = sdk.get("systems") if isinstance(sdk.get("systems"), dict) else {}
    systems["pmdg777"] = pmdg_systems
    for key in ("parking_brake",):
        if pmdg_systems.get(key) is not None: systems[key] = pmdg_systems[key]
    systems["battery_master"] = pmdg_systems.get("battery_master")
    systems["beacon_light"] = pmdg_systems.get("beacon_light")
    systems["seatbelt_switch"] = pmdg_systems.get("seatbelt_selector")
    result["systems"] = systems
    if isinstance(sdk.get("autopilot"), dict):
        result["autopilot"] = dict(sdk["autopilot"])
    controls = sdk.get("controls") if isinstance(sdk.get("controls"), dict) else {}
    if controls.get("flap_index") is not None: result["flap_index"] = controls["flap_index"]
    if controls.get("spoiler_percent") is not None:
        result["spoiler_percent"] = controls["spoiler_percent"]
        result["spoiler_actual_percent"] = controls["spoiler_percent"]
    result["parking_brake"] = controls.get("parking_brake")
    addon = dict(result.get("addon_state") or {})
    addon.update(sdk.get("addon_state") or {})
    addon.update({f"pulse_{key}": value for key, value in (sdk.get("addon_pulses") or {}).items()})
    result["addon_state"] = addon
    event_meta = dict(result.get("addon_event_meta") or {})
    for key, (label, kind) in _PMDG_META.items():
        event_meta[key] = {
            "label": label, "kind": kind,
            "values": _PMDG_META_VALUES.get(key, {}),
            "source": "PMDG 777 SDK",
        }
    for key in (sdk.get("addon_pulses") or {}):
        event_meta[f"pulse_{key}"] = {"label": key.replace("_", " ").upper(), "kind": "pulse", "values": {}, "source": "PMDG 777 SDK"}
    result["addon_event_meta"] = event_meta
    result["pmdg777_sdk"] = {**status, "flight_management": sdk.get("flight_management"), "aircraft_model": sdk.get("aircraft_model")}
    result["extended_source"] = "PMDG 777 SDK + " + str(result.get("extended_source") or result.get("source") or "FSUIPC")
    return True, status


def enrich_telemetry(sample: dict[str, Any], offset_reader: Callable[[list[tuple[int, str]]], list[Any]] | None = None, simconnect_reader: Callable[[list[tuple[str, str]]], list[Any]] | None = None) -> dict[str, Any]:
    result = dict(sample or {})
    if not result.get("ok"):
        return result
    global _LOCKED_ADAPTER, _LOCKED_ADAPTER_IDENTITY
    aircraft = _identity(result)
    if _LOCKED_ADAPTER and aircraft:
        if _aircraft_changed(aircraft, _LOCKED_ADAPTER_IDENTITY):
            _LOCKED_ADAPTER = None
            _LOCKED_ADAPTER_IDENTITY = None
            family = _stable_family(aircraft)
        else:
            family = dict(_LOCKED_ADAPTER)
    else:
        family = _stable_family(aircraft)
    result["aircraft"] = aircraft or result.get("aircraft")
    adapter = dict(result.get("aircraft_adapter") or {})
    adapter.update({
        "key": family["key"], "label": family["label"], "supported": family["supported"],
        "target_write": False, "telemetry_mode": "GENERIC" if not family["supported"] else "AIRCRAFT-SPECIFIC READ ONLY",
        "version": ADAPTER_VERSION,
    })
    result["aircraft_adapter"] = adapter

    # Secondary Fenix detection: if detect_family() returned generic but the
    # aircraft title contains only Fenix-transient tokens (e.g. "A320"),
    # attempt LVar reads via SimConnect as a litmus test. If LVars succeed,
    # force the family to fenix_a32x and proceed through the supported path.
    if not family["supported"] and simconnect_reader:
        identity_text = str(family.get("aircraft_text") or "").strip()
        identity_tokens = frozenset(
            t for t in identity_text.replace("N/A", "NA").replace("-", " ").replace("/", " ").split() if t
        )
        if not identity_text or (identity_tokens and identity_tokens <= _FENIX_TRANSIENT_IDENTITY_TOKENS):
            fenix_specs = specs_for_family("fenix_a32x")
            if fenix_specs:
                try:
                    probe_specs = fenix_specs[:5]
                    # v0.25.60: SimConnect rejects "f" as a units token and answers
                    # SIMCONNECT_EXCEPTION_UNRECOGNIZED_ID, flooding the log on every
                    # telemetry tick. "Number" is the correct generic float units.
                    lvar_requests = [(s.lvar, "Number") for s in probe_specs]
                    values = list(simconnect_reader(lvar_requests))
                    # Only force the Fenix family when the probe actually returned a
                    # readable value — an all-None result means the LVars do not exist
                    # on the loaded aircraft (avoid false-positive family detection).
                    if values and any(v is not None for v in values) and len(values) == len(lvar_requests):
                        family = {"key": "fenix_a32x", "label": FAMILY_LABELS["fenix_a32x"], "supported": True, "aircraft_text": identity_text}
                        adapter.update({
                            "key": "fenix_a32x",
                            "label": FAMILY_LABELS["fenix_a32x"],
                            "supported": True,
                            "target_write": False,
                            "telemetry_mode": "AIRCRAFT-SPECIFIC READ ONLY",
                            "version": ADAPTER_VERSION,
                        })
                        result["aircraft_adapter"] = adapter
                except Exception:
                    pass

    if not family["supported"]:
        return result

    categories = dict(result.get("provider_categories") or {})
    categories["adapter"] = family["label"]
    registry = load_registry()
    offset_map = registry.get("offsets") if registry.get("version") == ADAPTER_VERSION and isinstance(registry.get("offsets"), dict) else {}
    active_specs = specs_for_family(family["key"])
    installed_specs = [spec for spec in active_specs if spec.lvar in offset_map]
    adapter_status = {
        "key": family["key"], "label": family["label"], "version": ADAPTER_VERSION,
        "mapping_count": len(active_specs), "installed_mapping_count": len(installed_specs),
        "lvar_offsets_installed": bool(installed_specs and len(installed_specs) == len(active_specs)),
        "lvar_values_read": 0, "sdk_receiving": False,
    }

    pmdg_active = False
    if family["key"] == "pmdg_777":
        pmdg_active, pmdg_status = _merge_pmdg_sdk(result)
        adapter_status["sdk_receiving"] = bool(pmdg_active)
        adapter_status["pmdg_sdk"] = pmdg_status
        if pmdg_active:
            categories["systems"] = "PMDG 777 OFFICIAL SDK + " + str(categories.get("systems") or "STANDARD")
            categories["adapter"] = "PMDG 777 OFFICIAL SDK / FSUIPC WASM"

    # For Fenix, prefer reading L:Vars directly through SimConnect rather than
    # relying on FSUIPC WASM offset copies, which have historically been unreliable
    # for Fenix aircraft. Falls back to FSUIPC offsets if SimConnect is unavailable.
    if family["key"] == "fenix_a32x" and simconnect_reader and active_specs:
        # v0.25.60: "f" is not a valid SimConnect units token. Passing it made
        # AddToDataDefinition fail and every L:Var read raised
        # SIMCONNECT_EXCEPTION_UNRECOGNIZED_ID — thousands of log lines per
        # session (each flushed to disk) and no Fenix data ever read.
        lvar_requests: list[tuple[str, str]] = [(spec.lvar, "Number") for spec in active_specs]
        try:
            values = list(simconnect_reader(lvar_requests))
        except Exception:
            values = []
        if values and any(v is not None for v in values) and len(values) == len(active_specs):
            addon = dict(result.get("addon_state") or {})
            event_meta = dict(result.get("addon_event_meta") or {})
            top_level_contributed = False
            for spec, raw in zip(active_specs, values):
                value = _normalized(spec, raw)
                if value is None:
                    continue
                addon[spec.key] = value
                adapter_status["lvar_values_read"] += 1
                if spec.event:
                    event_meta[spec.key] = {
                        "label": spec.event, "kind": spec.kind,
                        "values": {str(key): label for key,label in spec.values},
                        "raw_lvar": spec.lvar,
                    }
                top_level_contributed = _merge_top_level(result, spec, value, family["label"]) or top_level_contributed
            result["addon_state"] = addon
            result["addon_event_meta"] = event_meta
            left_brake = _number(result.get("brake_left_percent"))
            right_brake = _number(result.get("brake_right_percent"))
            if left_brake is not None or right_brake is not None:
                result["brake_percent"] = max(value for value in (left_brake, right_brake) if value is not None)
            if adapter_status["lvar_values_read"]:
                categories["systems"] = "SIMCONNECT LVARS + " + str(categories.get("systems") or "STANDARD")
                if top_level_contributed:
                    categories["controls"] = "AIRCRAFT LVAR + " + str(categories.get("controls") or "STANDARD")
                result["extended_source"] = (str(result.get("extended_source") or result.get("source") or "") + " + SIMCONNECT LVARS").strip(" +")
                installed_specs = []  # Skip FSUIPC offset path below
                adapter_status["mode"] = "SIMCONNECT LVARS"

    if offset_reader and installed_specs:
        requests: list[tuple[int, str]] = []
        used_specs: list[LVarSpec] = []
        for spec in installed_specs:
            try:
                offset = int(str(offset_map[spec.lvar]), 0)
            except Exception:
                continue
            requests.append((offset, "f")); used_specs.append(spec)
        values: list[Any] = []
        try:
            values = list(offset_reader(requests)) if requests else []
        except Exception as exc:
            adapter_status["lvar_error"] = f"{type(exc).__name__}: {exc}"
        if len(values) == len(used_specs):
            addon = dict(result.get("addon_state") or {})
            event_meta = dict(result.get("addon_event_meta") or {})
            top_level_contributed = False
            for spec, raw in zip(used_specs, values):
                value = _normalized(spec, raw)
                if value is None:
                    continue
                addon[spec.key] = value
                adapter_status["lvar_values_read"] += 1
                if spec.event:
                    event_meta[spec.key] = {
                        "label": spec.event, "kind": spec.kind,
                        "values": {str(key): label for key,label in spec.values},
                        "raw_lvar": spec.lvar,
                    }
                top_level_contributed = _merge_top_level(result, spec, value, family["label"]) or top_level_contributed
            result["addon_state"] = addon
            result["addon_event_meta"] = event_meta
            left_brake = _number(result.get("brake_left_percent"))
            right_brake = _number(result.get("brake_right_percent"))
            if left_brake is not None or right_brake is not None:
                result["brake_percent"] = max(value for value in (left_brake, right_brake) if value is not None)
            if adapter_status["lvar_values_read"]:
                categories["systems"] = "FSUIPC WASM LVAR OFFSETS + " + str(categories.get("systems") or "STANDARD")
                if top_level_contributed:
                    categories["controls"] = "AIRCRAFT LVAR + " + str(categories.get("controls") or "STANDARD")
                result["extended_source"] = (str(result.get("extended_source") or result.get("source") or "") + " + FSUIPC WASM LVAR").strip(" +")

    # Additively surface an APU-running signal from the active adapter's read-only
    # state into the canonical ``systems`` dict, so study-level aircraft that drive
    # their APU through L:Vars/SDK (e.g. Fenix ``apu_master``, or PMDG ``apu_running``)
    # fire the logbook APU-start recording trigger. This never removes or rescales an
    # existing field and never clears an APU flag another source already set True.
    addon_state = result.get("addon_state") if isinstance(result.get("addon_state"), dict) else {}
    systems_now = result.get("systems") if isinstance(result.get("systems"), dict) else {}
    if systems_now.get("apu_running") is not True:
        if any(addon_state.get(key) is True for key in ("apu_master", "apu_running", "apu_avail", "apu_available", "apu_on")):
            systems_now = dict(systems_now)
            systems_now["apu_running"] = True
            result["systems"] = systems_now

    adapter_status["active"] = bool(pmdg_active or adapter_status["lvar_values_read"])
    if "mode" not in adapter_status or adapter_status["mode"] != "SIMCONNECT LVARS":
        adapter_status["mode"] = "ENHANCED" if adapter_status["active"] else "GENERIC FALLBACK"
    result["adapter_status"] = adapter_status
    # v0.25.60: when the aircraft family is supported (e.g. Fenix) but the
    # adapter is inactive (SimConnect session broken / L:Vars unavailable),
    # the generic standard AP offsets the addon does not populate read 0, and
    # the Flight Watch renders a fabricated "0 FT / 0°". Null only those exact
    # zeros so the UI shows "---" instead of a misleading selection. A valid
    # non-zero selection is never touched.
    if family.get("supported") and not adapter_status.get("active"):
        ap_now = result.get("autopilot")
        if isinstance(ap_now, dict):
            for fcu_key in ("selected_altitude_ft", "selected_heading_deg", "selected_speed_kts", "selected_vertical_speed_fpm"):
                if ap_now.get(fcu_key) == 0:
                    ap_now[fcu_key] = None
    # Lock the adapter after the first confirmed LVar read. Once locked,
    # the family holds through transient identity degradation until a
    # genuine aircraft change is detected by _aircraft_changed().
    if adapter_status["active"] and not _LOCKED_ADAPTER:
        _LOCKED_ADAPTER = dict(family)
        _LOCKED_ADAPTER_IDENTITY = dict(aircraft) if aircraft else {}
    result["provider_categories"] = categories
    return result
