from __future__ import annotations

"""Curated aircraft-specific telemetry mappings for OPS ROOM.

Only operationally useful variables are included.  The catalogue is deliberately
small: FSUIPC7 may know thousands of LVars, but OPS ROOM maps only selected
controls, engines and system states into the reserved FSUIPC user-offset area.
"""

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class LVarSpec:
    lvar: str
    families: tuple[str, ...]
    key: str
    kind: str = "number"       # number | bool | percent | enum | pulse
    event: str = ""
    values: tuple[tuple[int, str], ...] = ()
    top_level: str = ""        # optional normalized OPS ROOM field
    scale: float = 1.0
    offset: float = 0.0
    clamp: tuple[float, float] | None = None
    priority: int = 50
    # Canonical unit contract (Black Box telemetry & UI fix - design "Fix Implementation 0").
    # These three fields are additive and behaviour-neutral: appended at the END of the field
    # list with defaults so existing positional/keyword construction is undisturbed and every
    # current spec keeps its exact behaviour. Later tasks populate them per spec and set
    # ``validated=False`` on new, unproven INI/PMDG candidate specs.
    unit: str = "raw"          # unit_interval | percent | signed_percent | deflection_percent | index | enum | bool | raw
    role: str = ""             # physical_lever | mapped_input | commanded_tla | engine_response ("" when N/A)
    validated: bool = True     # proven specs default True; gated INI/PMDG candidates set False

    @property
    def value_labels(self) -> dict[int, str]:
        return dict(self.values)


FAMILY_LABELS = {
    "fenix_a32x": "Fenix A319/A320/A321",
    "pmdg_777": "PMDG 777",
    "inibuilds_a300": "iniBuilds A300-600",
    "inibuilds_a340": "iniBuilds A340",
    "inibuilds_a350": "iniBuilds A350",
    "fbw_a32nx": "FlyByWire A32NX",
    "fbw_a380x": "FlyByWire A380X",
    "generic": "Generic MSFS aircraft",
}


def _s(lvar: str, families: str | Iterable[str], key: str, **kwargs: Any) -> LVarSpec:
    fams = (families,) if isinstance(families, str) else tuple(families)
    return LVarSpec(lvar=lvar, families=fams, key=key, **kwargs)


# The catalogue must stay below the 128-float capacity of FSUIPC's 0xA000-0xA1FF
# free user-offset block.  Shared variables are authored once and reused by each
# applicable aircraft family.
LVAR_SPECS: tuple[LVarSpec, ...] = (
    # Fenix A32X: cockpit selections / short command pulses. Continuous axes and
    # engines continue to use standard FSUIPC + SimConnect channels.
    _s("S_FCU_AP1", "fenix_a32x", "ap1_button", kind="pulse", event="AP1 BUTTON"),
    _s("S_FCU_AP2", "fenix_a32x", "ap2_button", kind="pulse", event="AP2 BUTTON"),
    _s("S_FCU_ATHR", "fenix_a32x", "athr_button", kind="pulse", event="A/THR BUTTON"),
    _s("S_FCU_LOC", "fenix_a32x", "loc_button", kind="pulse", event="LOC BUTTON"),
    _s("S_FCU_APPR", "fenix_a32x", "appr_button", kind="pulse", event="APPR BUTTON"),
    _s("E_FCU_SPEED", "fenix_a32x", "selected_speed", top_level="ap_selected_speed_kts", event="FCU SPEED"),
    _s("E_FCU_HEADING", "fenix_a32x", "selected_heading", top_level="ap_selected_heading_deg", event="FCU HEADING"),
    _s("E_FCU_ALTITUDE", "fenix_a32x", "selected_altitude", top_level="ap_selected_altitude_ft", event="FCU ALTITUDE"),
    _s("E_FCU_VS", "fenix_a32x", "selected_vertical_speed", top_level="ap_selected_vertical_speed_fpm", event="FCU V/S"),
    _s("S_FC_FLAPS", "fenix_a32x", "flap_handle", kind="enum", values=((0,"UP"),(1,"1"),(2,"2"),(3,"3"),(4,"FULL")), top_level="flap_index", event="FLAPS SELECTED"),
    _s("A_FC_SPEEDBRAKE", "fenix_a32x", "speedbrake_handle", kind="enum", values=((0,"ARMED"),(1,"RETRACTED"),(2,"DETENT")), event="SPEEDBRAKE"),
    _s("S_MIP_PARKING_BRAKE", "fenix_a32x", "parking_brake", kind="bool", top_level="parking_brake", event="PARKING BRAKE"),
    _s("S_ENG_MASTER_1", "fenix_a32x", "engine_1_master", kind="bool", event="ENGINE 1 MASTER"),
    _s("S_ENG_MASTER_2", "fenix_a32x", "engine_2_master", kind="bool", event="ENGINE 2 MASTER"),
    _s("S_ENG_MODE", "fenix_a32x", "engine_mode", kind="enum", values=((0,"CRANK"),(1,"NORM"),(2,"IGN/START")), event="ENGINE MODE"),
    _s("S_OH_ELEC_BAT1", "fenix_a32x", "battery_1", kind="bool", event="BATTERY 1"),
    _s("S_OH_ELEC_BAT2", "fenix_a32x", "battery_2", kind="bool", event="BATTERY 2"),
    _s("S_OH_ELEC_APU_MASTER", "fenix_a32x", "apu_master", kind="bool", event="APU MASTER"),
    _s("S_OH_ELEC_APU_START", "fenix_a32x", "apu_start", kind="pulse", event="APU START BUTTON"),
    _s("S_OH_PNEUMATIC_APU_BLEED", "fenix_a32x", "apu_bleed", kind="bool", event="APU BLEED"),
    _s("S_OH_HYD_ENG_1_PUMP", "fenix_a32x", "hyd_engine_1_pump", kind="bool", event="ENG 1 HYD PUMP"),
    _s("S_OH_HYD_ENG_2_PUMP", "fenix_a32x", "hyd_engine_2_pump", kind="bool", event="ENG 2 HYD PUMP"),
    _s("S_OH_HYD_PTU", "fenix_a32x", "hyd_ptu", kind="bool", event="HYD PTU"),
    _s("S_OH_HYD_BLUE_ELEC_PUMP", "fenix_a32x", "hyd_blue_elec_pump", kind="bool", event="BLUE ELEC PUMP"),
    _s("S_OH_EXT_LT_BEACON", "fenix_a32x", "beacon", kind="bool", event="BEACON LIGHT"),
    _s("S_OH_EXT_LT_STROBE", "fenix_a32x", "strobe", kind="enum", values=((0,"OFF"),(1,"AUTO"),(2,"ON")), event="STROBE LIGHT"),
    _s("S_OH_EXT_LT_LANDING_L", "fenix_a32x", "landing_light_left", kind="enum", values=((0,"RETRACT"),(1,"OFF"),(2,"ON")), event="LEFT LANDING LIGHT"),
    _s("S_OH_EXT_LT_LANDING_R", "fenix_a32x", "landing_light_right", kind="enum", values=((0,"RETRACT"),(1,"OFF"),(2,"ON")), event="RIGHT LANDING LIGHT"),
    _s("S_OH_EXT_LT_NOSE", "fenix_a32x", "nose_light", kind="enum", values=((0,"OFF"),(1,"TAXI"),(2,"T/O")), event="NOSE LIGHT"),
    _s("S_OH_SIGNS", "fenix_a32x", "seatbelt_sign", kind="bool", event="SEAT BELTS"),
    _s("S_OH_NAV_IR1_MODE", "fenix_a32x", "irs_1", kind="enum", values=((0,"OFF"),(1,"NAV"),(2,"ATT")), event="IR 1"),
    _s("S_OH_NAV_IR2_MODE", "fenix_a32x", "irs_2", kind="enum", values=((0,"OFF"),(1,"NAV"),(2,"ATT")), event="IR 2"),
    _s("S_OH_NAV_IR3_MODE", "fenix_a32x", "irs_3", kind="enum", values=((0,"OFF"),(1,"NAV"),(2,"ATT")), event="IR 3"),

    # iniBuilds shared Airbus cockpit interface (A300/A340/A350 where present).
    _s("INI_AP1_BUTTON", ("inibuilds_a300","inibuilds_a340","inibuilds_a350"), "ap1_button", kind="pulse", event="AP1 BUTTON"),
    _s("INI_AP2_BUTTON", ("inibuilds_a300","inibuilds_a340","inibuilds_a350"), "ap2_button", kind="pulse", event="AP2 BUTTON"),
    _s("AP8_BUTTON", ("inibuilds_a300","inibuilds_a340","inibuilds_a350"), "athr_button", kind="pulse", event="A/THR BUTTON"),
    _s("AP6_BUTTON", ("inibuilds_a300","inibuilds_a340","inibuilds_a350"), "loc_button", kind="pulse", event="LOC BUTTON"),
    _s("AP7_BUTTON", ("inibuilds_a300","inibuilds_a340","inibuilds_a350"), "appr_button", kind="pulse", event="APPR BUTTON"),
    _s("INI_AIRSPEED_DIAL", ("inibuilds_a300","inibuilds_a340","inibuilds_a350"), "selected_speed", top_level="ap_selected_speed_kts", event="FCU SPEED"),
    _s("INI_HEADING_DIAL", ("inibuilds_a300","inibuilds_a340","inibuilds_a350"), "selected_heading", top_level="ap_selected_heading_deg", event="FCU HEADING"),
    _s("INI_ALTITUDE_DIAL", ("inibuilds_a300","inibuilds_a340","inibuilds_a350"), "selected_altitude", top_level="ap_selected_altitude_ft", event="FCU ALTITUDE"),
    _s("INI_VVI_DIAL", ("inibuilds_a300","inibuilds_a340","inibuilds_a350"), "selected_vertical_speed", top_level="ap_selected_vertical_speed_fpm", event="FCU V/S"),
    _s("INI_IGNITION_KNOB", ("inibuilds_a300","inibuilds_a340","inibuilds_a350"), "engine_mode", kind="enum", values=((0,"CRANK"),(1,"NORM"),(2,"IGN/START")), event="ENGINE MODE"),
    _s("INI_MIXTURE_RATIO1_HANDLE", ("inibuilds_a300","inibuilds_a340","inibuilds_a350"), "engine_1_master", kind="bool", event="ENGINE 1 MASTER"),
    _s("INI_MIXTURE_RATIO2_HANDLE", ("inibuilds_a300","inibuilds_a340","inibuilds_a350"), "engine_2_master", kind="bool", event="ENGINE 2 MASTER"),
    _s("INI_MIXTURE_RATIO3_HANDLE", "inibuilds_a340", "engine_3_master", kind="bool", event="ENGINE 3 MASTER"),
    _s("INI_MIXTURE_RATIO4_HANDLE", "inibuilds_a340", "engine_4_master", kind="bool", event="ENGINE 4 MASTER"),
    _s("INI_BATTERY_1_SWITCH", ("inibuilds_a340","inibuilds_a350"), "battery_1", kind="bool", event="BATTERY 1"),
    _s("INI_BATTERY_2_SWITCH", ("inibuilds_a340","inibuilds_a350"), "battery_2", kind="bool", event="BATTERY 2"),
    _s("INI_AIR_PACK1_BUTTON", ("inibuilds_a340","inibuilds_a350"), "pack_1", kind="bool", event="PACK 1"),
    _s("INI_AIR_PACK2_BUTTON", ("inibuilds_a340","inibuilds_a350"), "pack_2", kind="bool", event="PACK 2"),
    _s("INI_IRS1_STATE", ("inibuilds_a340","inibuilds_a350"), "irs_1", kind="enum", values=((0,"OFF"),(1,"NAV"),(2,"ATT")), event="IRS 1"),
    _s("INI_IRS2_STATE", ("inibuilds_a340","inibuilds_a350"), "irs_2", kind="enum", values=((0,"OFF"),(1,"NAV"),(2,"ATT")), event="IRS 2"),
    _s("INI_IRS3_STATE", ("inibuilds_a340","inibuilds_a350"), "irs_3", kind="enum", values=((0,"OFF"),(1,"NAV"),(2,"ATT")), event="IRS 3"),
    _s("INI_MASTER_WARNING_COMMAND", ("inibuilds_a340","inibuilds_a350"), "master_warning_button", kind="pulse", event="MASTER WARNING RESET"),
    _s("INI_MASTER_CAUTION_COMMAND", ("inibuilds_a340","inibuilds_a350"), "master_caution_button", kind="pulse", event="MASTER CAUTION RESET"),
    _s("INI_GRAVITY_GEAR_HANDLE_STATE", ("inibuilds_a340","inibuilds_a350"), "gravity_gear", kind="enum", values=((0,"RESET"),(1,"OFF"),(2,"DOWN")), event="GRAVITY GEAR"),

    # A300 continuous / authoritative LVars from the supplied catalogue.
    # Rudder pedal scale fix (Black Box telemetry & UI fix - design "Fix Implementation 1").
    # The pedal position is the PILOT INPUT and is retargeted to the canonical [-1,1]
    # unit_interval. It is kept DISTINCT from the actual rudder-surface deflection below
    # (Property 5: pedal input vs surface deflection must never be merged). The prior
    # clamp=(-100,100) assumed a +/-100 native domain, so apply scale=0.01 (30 -> 0.30,
    # 0 -> 0, +/-100 -> +/-1) and drop the clamp - the Task 4 normalizer now guarantees
    # [-1,1]. LVC2 is the live-confirmation checkpoint for the exact per-aircraft native
    # pedal domain/scale; this is the existing active mapping (validated=True) with only
    # the wrong scale corrected, not a new unproven candidate.
    _s("INI_RUDDER_PEDAL_POSITION", "inibuilds_a300", "rudder_pedal", top_level="pilot_rudder_input", scale=0.01, unit="unit_interval"),
    _s("INI_rudder_deflection", "inibuilds_a300", "rudder_deflection", top_level="actual_rudder_percent", clamp=(-100.0,100.0), unit="deflection_percent"),
    _s("INI_FLAPS_HANDLE_INDEX", "inibuilds_a300", "flap_handle", top_level="flap_index", event="FLAPS SELECTED"),
    _s("INI_FLAPS_HANDLE_PERCENT", "inibuilds_a300", "flap_handle_percent", kind="percent", top_level="flap_handle_percent"),
    _s("INI_SPOILERS_HANDLE_POSITION", "inibuilds_a300", "speedbrake_handle", kind="percent", top_level="spoiler_percent", event="SPEEDBRAKE"),
    _s("INI_SPOILERS_ARMED", "inibuilds_a300", "spoilers_armed", kind="bool", event="SPOILERS ARMED"),
    _s("INI_SPOILERS_GROUND_SPOILERS_ACTIVE", "inibuilds_a300", "ground_spoilers", kind="bool", event="GROUND SPOILERS"),
    _s("INI_GEAR_HANDLE_STATUS", "inibuilds_a300", "gear_handle", kind="bool", event="GEAR SELECTED"),
    _s("INI_ENGINE1_EGT", "inibuilds_a300", "engine_1_egt", top_level="engine_1_egt_c"),
    _s("INI_ENGINE2_EGT", "inibuilds_a300", "engine_2_egt", top_level="engine_2_egt_c"),
    # Throttle role/units (Black Box telemetry & UI fix - design "Fix Implementation 1").
    # INI_AUTOTHROTTLE_TLA_* is a thrust-lever-angle signal. Tag it with the canonical
    # signed_percent throttle domain [-25,110] (reverse..max) and label role="commanded_tla".
    # Per the design it targets the COMMANDED/engine field throttle_n_percent, NOT the
    # physical pilot lever pilot_throttle_n_percent: the TLA is not proven to be the physical
    # pilot lever, and physical_lever / mapped_input / commanded_tla / engine_response roles
    # must never be equated without evidence (Req 2.2, Property 4). These stay ACTIVE
    # (validated=True default): they are existing mappings and a scale/role tag is a
    # refinement, not a new unproven candidate. The prior clamp=(-25,110) already matches
    # signed_percent and is retained (raw->natural-domain), while the Task 4 normalizer keyed
    # on unit now guarantees the final [-25,110] domain.
    # LVC3 is the live-confirmation checkpoint for role/domain/name - including reconciling
    # this catalog name against the requirement's DISTINCT INI_AUTOTHRUST_TLA:* candidate
    # (added separately as a gated candidate; NOT equated or merged here).
    _s("INI_AUTOTHROTTLE_TLA_1", "inibuilds_a300", "throttle_1", top_level="throttle_1_percent", clamp=(-25.0,110.0), unit="signed_percent", role="commanded_tla"),
    _s("INI_AUTOTHROTTLE_TLA_2", "inibuilds_a300", "throttle_2", top_level="throttle_2_percent", clamp=(-25.0,110.0), unit="signed_percent", role="commanded_tla"),
    _s("INI_hyd_green_pressure", "inibuilds_a300", "hyd_green_pressure"),
    _s("INI_hyd_blue_pressure", "inibuilds_a300", "hyd_blue_pressure"),
    _s("INI_MASTER_CAUTION_ACTIVE", "inibuilds_a300", "master_caution", kind="bool", event="MASTER CAUTION"),
    _s("INI_MASTER_WARNING_ACTIVE", "inibuilds_a300", "master_warning", kind="bool", event="MASTER WARNING"),
    _s("INI_MAIN_CARGO_DOOR", "inibuilds_a300", "main_cargo_door", event="MAIN CARGO DOOR"),
    _s("INI_COCKPIT_DOOR_STATE", "inibuilds_a300", "cockpit_door", event="COCKPIT DOOR"),

    # iniBuilds captain / first-officer sidestick CANDIDATE specs (Black Box telemetry & UI
    # fix - design "Fix Implementation 1", tasks.md Task 5.4). These are UNPROVEN CANDIDATES
    # gated by Live-validation Checkpoint LVC4 (existence/semantics of sidestick 1/2), so they
    # carry validated=False and MUST stay INERT: active_specs()/specs_for_family() exclude them
    # and the installer allocates them no FSUIPC offset, so a validated=False spec is never
    # installed nor read and can never emit a fabricated value (e.g. 0.0) for an aircraft until
    # a checkpoint promotes it (design: "clearing a checkpoint is what promotes a candidate spec
    # to active use"). They remain documented here as the record of the candidate mapping.
    #   * SIDESTICK1 -> CAPTAIN aileron/elevator; SIDESTICK2 -> FIRST OFFICER (pilot_*_input_fo).
    #     Captain and FO axes are carried INDEPENDENTLY (Property 3, Req 2.1/3.3): an FBW single
    #     stick fills the captain fields only and the FO axes are NEVER synthesised from captain.
    #   * unit="unit_interval": once LVC4 promotes them the Task 4 canonical normalizer guarantees
    #     the [-1,1] domain (the iniBuilds native sidestick domain is itself part of what LVC4 must
    #     confirm before promotion).
    #   * FAMILY (LVC4 assumption): the requirement's INI inventory (bugfix.md 2.6) is the
    #     iniBuilds fly-by-wire Airbus sidestick set (A320 / A350). There is no inibuilds_a320
    #     family and no existing catalog entry pins the exact family, so per Task 5.4 these are
    #     assigned to inibuilds_a350; the correct family/applicability is itself part of what LVC4
    #     must confirm before promotion.
    _s("INI_SIDESTICK1_POSITION_X", "inibuilds_a350", "sidestick1_x", top_level="pilot_aileron_input", unit="unit_interval", validated=False),
    _s("INI_SIDESTICK1_POSITION_Y", "inibuilds_a350", "sidestick1_y", top_level="pilot_elevator_input", unit="unit_interval", validated=False),
    _s("INI_SIDESTICK2_POSITION_X", "inibuilds_a350", "sidestick2_x", top_level="pilot_aileron_input_fo", unit="unit_interval", validated=False),
    _s("INI_SIDESTICK2_POSITION_Y", "inibuilds_a350", "sidestick2_y", top_level="pilot_elevator_input_fo", unit="unit_interval", validated=False),

    # ------------------------------------------------------------------------------------
    # Remaining iniBuilds INI candidate specs (Black Box telemetry & UI fix - design
    # "Fix Implementation 1" -> "Remaining INI candidates (Req 2.6)" + "Alias/index
    # reconciliation"; tasks.md Task 5.5). EVERY spec in this block is an UNPROVEN CANDIDATE:
    # validated=False, so it is INERT exactly like the Task 5.4 sidestick candidates above -
    # active_specs()/specs_for_family() exclude it and the installer allocates it no FSUIPC
    # offset, so it is never installed, read, or merged, and can never emit a fabricated
    # field for an aircraft until a Live-validation Checkpoint (LVC3/LVC4/LVC8) promotes it
    # ("clearing a checkpoint is what promotes a candidate spec to active use"). They are the
    # documented record of each candidate mapping and its assumed unit/role/family.
    #
    # DISTINCT-top_level invariant: every candidate below targets its OWN distinct top_level
    # so the semantics never collapse into one another (physical lever vs mapped input vs
    # commanded TLA; brake axis vs command vs pressure; spoiler handle vs actual deployment).
    # Evidence (LVC) later decides which candidate, if any, becomes the canonical source for a
    # shown label; until then each is carried separately and none overwrites another.
    #
    # unit/kind: these candidates carry the canonical ``unit`` tag only (kind stays the default
    # "number"); the Task 4 canonical normalizer keyed on ``unit`` guarantees the final domain
    # and REJECTS semantically impossible values as unavailable (None) per Req 2.9, rather than
    # kind="percent" which would clamp them into plausibility. Pressure is the deliberate
    # exception (unit="raw", see the brake block).

    # -- Throttle (FAMILY ASSUMPTION LVC3/LVC4: inibuilds_a350) ---------------------------
    # The physical-lever -> mapped-input -> commanded-TLA chain is the FBW-Airbus throttle
    # input model; the ":index" colon forms mirror the FBW A32NX ``AUTOTHRUST_TLA:index``
    # convention, so the whole chain is assigned to the FBW-Airbus-style iniBuilds family
    # (inibuilds_a350, matching the Task 5.4 sidestick assumption) and kept together so one
    # aircraft's throttle chain stays coherent. Each role is DISTINCT and must never be equated
    # without evidence (Req 2.2, Property 4): physical_lever -> pilot_throttle_n_percent (the
    # pilot lever), mapped_input -> throttle_mapping_input_n_percent, commanded_tla ->
    # autothrust_tla_n_percent. CRITICAL (LVC3): INI_AUTOTHRUST_TLA:* here is a SEPARATE
    # candidate from the existing ACTIVE INI_AUTOTHROTTLE_TLA_* (A300, -> throttle_n_percent) -
    # distinct lvar name, distinct top_level, distinct family - and is NEVER unified/merged with
    # it; the ":index" and "_n" forms are deliberately kept as distinct entries, resolved by
    # evidence. Assumed native domain is the signed_percent natural range [-25,110] (reverse..
    # max); the exact per-aircraft domain/sign/neutral is itself part of what LVC3/LVC4 confirm.
    _s("INI_THROTTLE_LEVER1_POS", "inibuilds_a350", "throttle_lever_1", top_level="pilot_throttle_1_percent", clamp=(-25.0,110.0), unit="signed_percent", role="physical_lever", validated=False),
    _s("INI_THROTTLE_LEVER2_POS", "inibuilds_a350", "throttle_lever_2", top_level="pilot_throttle_2_percent", clamp=(-25.0,110.0), unit="signed_percent", role="physical_lever", validated=False),
    _s("INI_THROTTLE_MAPPING_INPUT:1", "inibuilds_a350", "throttle_mapping_input_1", top_level="throttle_mapping_input_1_percent", clamp=(-25.0,110.0), unit="signed_percent", role="mapped_input", validated=False),
    _s("INI_THROTTLE_MAPPING_INPUT:2", "inibuilds_a350", "throttle_mapping_input_2", top_level="throttle_mapping_input_2_percent", clamp=(-25.0,110.0), unit="signed_percent", role="mapped_input", validated=False),
    _s("INI_AUTOTHRUST_TLA:1", "inibuilds_a350", "autothrust_tla_1", top_level="autothrust_tla_1_percent", clamp=(-25.0,110.0), unit="signed_percent", role="commanded_tla", validated=False),
    _s("INI_AUTOTHRUST_TLA:2", "inibuilds_a350", "autothrust_tla_2", top_level="autothrust_tla_2_percent", clamp=(-25.0,110.0), unit="signed_percent", role="commanded_tla", validated=False),

    # -- Brakes (FAMILY ASSUMPTION LVC4/LVC8: inibuilds_a300) -----------------------------
    # Extend the existing A300 continuous block. L/R independence is preserved - the sides are
    # NEVER merged (Property 6, Req 2.4). Axis vs command vs pressure are three DISTINCT signals
    # with distinct top_levels; LVC8 (brake source semantics per aircraft) decides which is
    # authoritative for a shown label.
    #   * axis    -> physical pedal-axis input   (unit=percent, role=physical_lever)
    #   * command -> commanded brake             (unit=percent; no throttle role applies -> "")
    #   * PRESSURE -> hydraulic brake PRESSURE, NOT percent. Uses a DISTINCT pressure top_level
    #     (brake_pressure_left/right_actual) and unit="raw" so the canonical normalizer does NOT
    #     force a [0,100] percent domain; the true pressure value passes through untouched and is
    #     labelled as pressure, per Req 2.4 ("identify pressure as pressure rather than percent").
    _s("INI_BRAKE_AXIS_LEFT", "inibuilds_a300", "brake_axis_left", top_level="brake_axis_left_percent", unit="percent", role="physical_lever", validated=False),
    _s("INI_BRAKE_AXIS_RIGHT", "inibuilds_a300", "brake_axis_right", top_level="brake_axis_right_percent", unit="percent", role="physical_lever", validated=False),
    _s("INI_BRAKE_LEFT_COMMAND", "inibuilds_a300", "brake_left_command", top_level="brake_left_command_percent", unit="percent", validated=False),
    _s("INI_BRAKE_RIGHT_COMMAND", "inibuilds_a300", "brake_right_command", top_level="brake_right_command_percent", unit="percent", validated=False),
    _s("INI_BRAKE_PRESSURE_LEFT_ACTUAL", "inibuilds_a300", "brake_pressure_left_actual", top_level="brake_pressure_left_actual", unit="raw", validated=False),
    _s("INI_BRAKE_PRESSURE_RIGHT_ACTUAL", "inibuilds_a300", "brake_pressure_right_actual", top_level="brake_pressure_right_actual", unit="raw", validated=False),

    # -- Flaps / slats actual deployment (FAMILY ASSUMPTION LVC4: inibuilds_a300) ---------
    # Actual slats/flaps DEPLOYMENT ratio, distinct from the handle/detent selection already
    # mapped by INI_FLAPS_HANDLE_INDEX/PERCENT (Property 5, Req 2.5). Native [0,1] -> [0,100]
    # via scale=100.0, unit=percent, distinct actual top_level flaps_slats_deployed_percent.
    _s("INI_FLAPS_SLATS_DEPLOYED_RATIO", "inibuilds_a300", "flaps_slats_deployed", top_level="flaps_slats_deployed_percent", scale=100.0, unit="percent", validated=False),

    # -- Spoilers (FAMILY ASSUMPTION LVC4: inibuilds_a300) --------------------------------
    # Handle position vs actual deployment kept DISTINCT (Property 5, Req 2.5):
    #   * INI_SPOILERS_SIM_HANDLE_POS -> handle position (unit=percent), distinct from the
    #     existing INI_SPOILERS_HANDLE_POSITION (-> spoiler_percent); own top_level
    #     spoiler_sim_handle_percent.
    #   * INI_speedbrake_ratio -> actual spoiler/speedbrake DEPLOYMENT, native [0,1] -> [0,100]
    #     via scale=100.0, unit=percent, distinct actual top_level spoiler_actual_percent.
    # Spoiler ARMED / DEPLOYED discrete variables: bugfix.md 2.6 refers to "the exact spoiler
    # deployment and armed variables present in the supplied inventory" but does NOT name them
    # verbatim. Armed/ground-spoiler state is already represented by the existing ACTIVE A300
    # specs INI_SPOILERS_ARMED and INI_SPOILERS_GROUND_SPOILERS_ACTIVE; any ADDITIONAL exact
    # deployment/armed L:Var names are not established, so they are intentionally left UNLISTED
    # pending evidence (LVC4) rather than guessed.
    _s("INI_SPOILERS_SIM_HANDLE_POS", "inibuilds_a300", "spoiler_sim_handle", top_level="spoiler_sim_handle_percent", unit="percent", validated=False),
    _s("INI_speedbrake_ratio", "inibuilds_a300", "speedbrake_ratio", top_level="spoiler_actual_percent", scale=100.0, unit="percent", validated=False),

    # FlyByWire A32NX/A380X official documented local SimVars. The A380 reuses
    # the A32NX namespace for many systems.
    _s("A32NX_FWC_FLIGHT_PHASE", ("fbw_a32nx","fbw_a380x"), "fwc_flight_phase", kind="enum", event="FWC FLIGHT PHASE"),
    _s("A32NX_FLAPS_HANDLE_INDEX", ("fbw_a32nx","fbw_a380x"), "flap_handle", top_level="flap_index", event="FLAPS SELECTED"),
    _s("A32NX_FLAPS_HANDLE_PERCENT", ("fbw_a32nx","fbw_a380x"), "flap_handle_percent", kind="percent", top_level="flap_handle_percent", scale=100.0),
    _s("A32NX_SPOILERS_ARMED", ("fbw_a32nx","fbw_a380x"), "spoilers_armed", kind="bool", event="SPOILERS ARMED"),
    _s("A32NX_SPOILERS_HANDLE_POSITION", ("fbw_a32nx","fbw_a380x"), "speedbrake_handle", kind="percent", top_level="spoiler_percent", scale=100.0, event="SPEEDBRAKE"),
    _s("A32NX_AUTOTHRUST_TLA:1", ("fbw_a32nx","fbw_a380x"), "throttle_angle_1", clamp=(-20.0,45.0)),
    _s("A32NX_AUTOTHRUST_TLA:2", ("fbw_a32nx","fbw_a380x"), "throttle_angle_2", clamp=(-20.0,45.0)),
    _s("A32NX_AUTOTHRUST_TLA:3", "fbw_a380x", "throttle_angle_3", clamp=(-20.0,45.0)),
    _s("A32NX_AUTOTHRUST_TLA:4", "fbw_a380x", "throttle_angle_4", clamp=(-20.0,45.0)),
    _s("A32NX_AUTOTHRUST_REVERSE:1", ("fbw_a32nx","fbw_a380x"), "reverse_1", kind="bool", event="ENGINE 1 REVERSE"),
    _s("A32NX_AUTOTHRUST_REVERSE:2", ("fbw_a32nx","fbw_a380x"), "reverse_2", kind="bool", event="ENGINE 2 REVERSE"),
    _s("A32NX_AUTOTHRUST_REVERSE:3", "fbw_a380x", "reverse_3", kind="bool", event="ENGINE 3 REVERSE"),
    _s("A32NX_AUTOTHRUST_REVERSE:4", "fbw_a380x", "reverse_4", kind="bool", event="ENGINE 4 REVERSE"),
    # FCU ARINC output-bus words are intentionally not mapped as plain floats.
    # Standard SimConnect/FSUIPC selected-target channels remain authoritative.
    # Sidestick scale fix (Black Box telemetry & UI fix - design "Fix Implementation 1").
    # FBW SIDESTICK_POSITION is natively [-1,1], so drop the x100 scale/clamp and tag the
    # canonical unit; the Task 4 normalizer then guarantees [-1,1] (0.5 -> 0.5, 0 -> 0, +/-1 -> +/-1).
    # LVC1 is the live-confirmation checkpoint for the FBW native [-1,1] domain. This is the
    # existing proven FBW mapping (validated=True default); only the wrong scale was corrected.
    _s("A32NX_SIDESTICK_POSITION_X", ("fbw_a32nx","fbw_a380x"), "sidestick_x", top_level="pilot_aileron_input", unit="unit_interval"),
    _s("A32NX_SIDESTICK_POSITION_Y", ("fbw_a32nx","fbw_a380x"), "sidestick_y", top_level="pilot_elevator_input", unit="unit_interval"),
    # Rudder pedal scale fix (see the A300 rudder note above; design "Fix Implementation 1").
    # FBW pedal input retargeted to canonical [-1,1]; prior clamp=(-100,100) implies a +/-100
    # native domain, so scale=0.01 (30 -> 0.30) and drop the clamp (Task 4 normalizer guarantees
    # [-1,1]). LVC2 is the live-confirmation checkpoint for the exact native pedal domain/scale;
    # existing active mapping (validated=True), only the wrong scale corrected.
    _s("A32NX_RUDDER_PEDAL_POSITION", ("fbw_a32nx","fbw_a380x"), "rudder_pedal", top_level="pilot_rudder_input", scale=0.01, unit="unit_interval"),
    _s("A32NX_LEFT_BRAKE_PEDAL_INPUT", ("fbw_a32nx","fbw_a380x"), "brake_left", kind="percent", top_level="brake_left_percent"),
    _s("A32NX_RIGHT_BRAKE_PEDAL_INPUT", ("fbw_a32nx","fbw_a380x"), "brake_right", kind="percent", top_level="brake_right_percent"),
    _s("A32NX_PARK_BRAKE_LEVER_POS", ("fbw_a32nx","fbw_a380x"), "parking_brake", kind="bool", top_level="parking_brake", event="PARKING BRAKE"),
    _s("A32NX_APU_N_RAW", ("fbw_a32nx","fbw_a380x"), "apu_n_percent", kind="percent"),
    _s("A32NX_APU_BLEED_AIR_VALVE_OPEN", ("fbw_a32nx","fbw_a380x"), "apu_bleed", kind="bool", event="APU BLEED"),
    _s("A32NX_HYD_GREEN_SYSTEM_1_SECTION_PRESSURE", "fbw_a32nx", "hyd_green_pressure"),
    _s("A32NX_HYD_BLUE_SYSTEM_1_SECTION_PRESSURE", "fbw_a32nx", "hyd_blue_pressure"),
    _s("A32NX_HYD_YELLOW_SYSTEM_1_SECTION_PRESSURE", "fbw_a32nx", "hyd_yellow_pressure"),
    _s("A32NX_GEAR_LEVER_POSITION_REQUEST", ("fbw_a32nx","fbw_a380x"), "gear_handle", kind="bool", event="GEAR SELECTED"),
    _s("A32NX_BRAKES_HOT", ("fbw_a32nx","fbw_a380x"), "brakes_hot", kind="bool", event="BRAKES HOT"),
    _s("A32NX_FIRE_BUTTON_APU", ("fbw_a32nx","fbw_a380x"), "apu_fire_button_released", kind="bool", event="APU FIRE BUTTON"),

    # PMDG 777 LVars supplement the official SDK stream for physical inputs and
    # surface animation values that are not part of PMDG_777X_Data.
    #
    # Canonical-unit tagging (Black Box telemetry & UI fix - design "Fix Implementation 1" ->
    # "PMDG 777 catalog specs"; tasks.md Task 5.7). These PMDG-only 7X7X_* specs are TAGGED
    # against the canonical unit contract, but - unlike the FBW/INI scale fixes above - their
    # numeric output is left EXACTLY as today (byte-identical pass-through). Two rules drive this:
    #
    #   1. STAY ACTIVE (validated=True). These are EXISTING active mappings, mirroring how the
    #      FBW sidestick/rudder existing mappings were kept active in 5.1/5.2. Setting them
    #      validated=False would make them INERT (excluded from active_specs()/specs_for_family()
    #      and allocated no FSUIPC offset), which would STOP recording PMDG engine N1/N2 and the
    #      surface/pedal/brake raw values entirely - a reduction of adapter coverage that violates
    #      preservation (Req 3.14 "no reduction of decoded add-on states"; Baseline B2). So they
    #      remain validated=True and the active-spec count is unchanged.
    #
    #   2. unit="raw" (a strict NO-OP). The canonical normalizer (addon_telemetry._apply_canonical_unit)
    #      leaves a "raw" value untouched, so tagging unit="raw" changes NO recorded value. Rule:
    #      only assert a canonical numeric unit here when it is a no-op for the current output. The
    #      native domains of every 7X7X_* value are NOT live-confirmed (LVC9 engines / LVC10
    #      surfaces+physical), so asserting a canonical unit now would clamp/re-scale and change the
    #      output - therefore each stays unit="raw" with the intended canonical unit documented per
    #      line, to be applied by the validated view after its checkpoint clears. All stay
    #      validated=False-equivalent in *trust* (gated by LVC9/LVC10 - MUST NOT be treated as
    #      proven) while remaining validated=True in *offset activation* so coverage is preserved.
    #
    # EVIDENCE HANDLING: the 7X7X* names are MSFS L:Vars that are NOT part of the documented
    # PMDG_777X_Data struct, so "PMDG Documentation/SDK/PMDG_777X_SDK.h" is NOT their authoritative
    # source; they are validated like any other L:Var candidate (aircraft behaviour + controlled
    # live observation), never inferred from the SDK header. The SDK header stays authoritative
    # only for the documented struct fields decoded in app/pmdg777_sdk.py (its enum/label maps and
    # source precedence are unchanged by this task). No PMDG source precedence or SDK-decoded
    # semantics are touched here.
    #
    # -- Surface animation positions (LVC10; intended unit "deflection_percent" [-100,100] or
    #    "unit_interval" [-1,1] per validated native domain). No top_level: these surface as
    #    addon_state[key] raw values today and MUST keep doing so, so no top_level is added and no
    #    scaling is applied - unit="raw" preserves the exact current addon_state value.
    _s("7X7XLeftAileron", "pmdg_777", "left_aileron_raw", unit="raw"),
    _s("7X7XRightAileron", "pmdg_777", "right_aileron_raw", unit="raw"),
    _s("7X7XLeftFlaperon", "pmdg_777", "left_flaperon_raw", unit="raw"),
    _s("7X7XRightFlaperon", "pmdg_777", "right_flaperon_raw", unit="raw"),
    # -- Physical pedal/brake inputs (LVC10; intended unit "unit_interval" [-1,1] for the rudder
    #    pedals, "percent" [0,100] for the foot brakes, per validated native domain). Same as the
    #    surfaces: no top_level (addon_state raw today), unit="raw" -> byte-identical pass-through.
    _s("7X7X_RudderPedals", "pmdg_777", "rudder_pedals_raw", unit="raw"),
    _s("7X7X_FootBrakeLeft", "pmdg_777", "brake_left_raw", unit="raw"),
    _s("7X7X_FootBrakeRight", "pmdg_777", "brake_right_raw", unit="raw"),
    # -- Engine N1/N2 gauges (LVC9; intended unit "percent" [0,110]). These already target the
    #    top_level engine_{1,2}_n{1,2}_percent fields. Their native N1/N2 scaling is NOT
    #    live-confirmed, and the canonical "percent" domain is [0,100] - which would WRONGLY clamp
    #    a real N1/N2 above 100 (e.g. an observed N2 of 101.4). So keep unit="raw" (scale/clamp
    #    unchanged) for a byte-identical pass-through today; LVC9 confirms the native N1/N2 scaling
    #    and the Task 10 Engines view then applies the validated [0,110] scaling. Do NOT force a
    #    percent domain now. (Semantically these are engine_response values; the role is left
    #    unset pending LVC9 rather than asserted as proven.)
    _s("7X7X_engine1_N1", "pmdg_777", "engine_1_n1", top_level="engine_1_n1_percent", unit="raw"),
    _s("7X7X_engine2_N1", "pmdg_777", "engine_2_n1", top_level="engine_2_n1_percent", unit="raw"),
    _s("7X7X_engine1_N2", "pmdg_777", "engine_1_n2", top_level="engine_1_n2_percent", unit="raw"),
    _s("7X7X_engine2_N2", "pmdg_777", "engine_2_n2", top_level="engine_2_n2_percent", unit="raw"),
    # -- Cabin door: event-based discrete state, left exactly as-is (no canonical numeric unit).
    _s("7X7XCabinDoor1L", "pmdg_777", "door_1l", event="DOOR 1L"),
)


_BY_LVAR = {spec.lvar: spec for spec in LVAR_SPECS}
if len(_BY_LVAR) != len(LVAR_SPECS):
    raise RuntimeError("Duplicate LVar name in OPS ROOM aircraft adapter catalogue")
# FSUIPC user-offset capacity (0xA000-0xA1FF = 128 floats) is consumed ONLY by
# OFFSET-CONSUMING specs, i.e. ACTIVE (validated=True) specs: the installer allocates one
# offset per active spec and enrich_telemetry reads only active specs (see active_specs()).
# Gated validated=False candidates are documentation-only - never installed, never read - so
# they consume NO offset and do NOT count against the 128 cap (design "Live-validation
# Checkpoints": only active family/validated specs consume offsets; gated candidates are
# documented but not installed). Enforce the cap on the ACTIVE subset only; the duplicate-name
# guard above still spans ALL specs (candidates included). ``active_specs()`` is defined below,
# so the active subset is computed inline here at module load. NOTE (future LVC concern):
# per-family offset staging is intentionally NOT implemented while candidates are gated;
# promoting many candidates to validated=True later MUST keep the ACTIVE count <= 128 (or
# introduce per-family offset staging at that point).
_active_specs = [spec for spec in LVAR_SPECS if spec.validated]
if len(_active_specs) > 128:
    raise RuntimeError(
        f"Aircraft adapter catalogue exceeds FSUIPC user-offset capacity: {len(_active_specs)} active > 128"
    )


def active_specs() -> tuple[LVarSpec, ...]:
    """The subset of :data:`LVAR_SPECS` promoted to active use.

    A spec with ``validated=False`` is a documented-but-unproven candidate gated behind a
    Live-validation Checkpoint (design "Live-validation Checkpoints"). It stays in
    ``LVAR_SPECS`` for the record but MUST be INERT until a checkpoint promotes it: neither
    installed to an FSUIPC user offset nor read/merged, so it can never emit a fabricated
    value for an aircraft. ``spec.validated`` is the single gate shared by the reading path
    (``specs_for_family`` -> ``addon_telemetry.enrich_telemetry``) and the installer's offset
    allocation (design: "clearing a checkpoint is what promotes a candidate spec to active use").
    """
    return tuple(spec for spec in LVAR_SPECS if spec.validated)


def specs_for_family(family: str) -> tuple[LVarSpec, ...]:
    # Only ACTIVE (validated) specs participate in family selection and reading; a gated
    # validated=False candidate is excluded here so it is never read/merged (see active_specs).
    return tuple(spec for spec in active_specs() if family in spec.families)


def detect_family(aircraft: dict[str, Any] | None) -> dict[str, Any]:
    aircraft = aircraft if isinstance(aircraft, dict) else {}
    haystack = " ".join(str(aircraft.get(key) or "") for key in ("title", "model", "type", "manufacturer", "atc_model")).upper()
    family = "generic"
    if any(token in haystack for token in ("FENIX", "FNX32", "FNX A3", "FENIX A319", "FENIX A321", "FENIX A20N", "FNX320", "FNX A320", "FENIX320")):
        family = "fenix_a32x"
    elif "PMDG" in haystack and any(token in haystack for token in ("777", "77W", "77F", "B77")):
        family = "pmdg_777"
    elif any(token in haystack for token in ("INIBUILDS A300", "A300-600", "A306", "A300")):
        family = "inibuilds_a300"
    elif "AEROSOFT" not in haystack and any(token in haystack for token in ("INIBUILDS A340", "A340-300", "A343", "A340")):
        family = "inibuilds_a340"
    elif any(token in haystack for token in ("INIBUILDS A350", "A350-900", "A359", "A350")):
        family = "inibuilds_a350"
    elif any(token in haystack for token in ("A380X", "FLYBYWIRE A380", "FBW A380")):
        family = "fbw_a380x"
    elif any(token in haystack for token in ("A32NX", "FLYBYWIRE A320", "FBW A320")):
        family = "fbw_a32nx"
    return {
        "key": family,
        "label": FAMILY_LABELS[family],
        "supported": family != "generic",
        "aircraft_text": haystack.strip(),
    }


def catalog_summary() -> dict[str, Any]:
    return {
        "mapping_count": len(LVAR_SPECS),
        "capacity": 128,
        "families": {
            family: {"label": label, "mapping_count": len(specs_for_family(family))}
            for family, label in FAMILY_LABELS.items() if family != "generic"
        },
    }
