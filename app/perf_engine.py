"""
OPS ROOM -- takeoff/landing performance engine (v0.25.75).

Three-tier calculation:

* Tier 1 (exact, FCOM-derived data):
    - A320neo (A20N): full port of the FlyByWire A32NX A320-251N takeoff
      calculator (GPL-3.0, github.com/flybywiresim/aircraft,
      fbw-a32nx/src/systems/shared/src/performance/a32nx_takeoff.ts) --
      limiting-factor framework: for each takeoff config the max TOW is the
      minimum of the runway / second-segment / brake-energy / VMCG limits at
      OAT, Tref, Tmax and TflexMax; V1/VR/V2 come from per-limit speed
      factors reconciled against VMCG/VMCA/VMU minimums; FLEX temp is
      interpolated; wet-runway weight/flex/speed adjustments apply
      piecewise; the optimum config runs all three flap settings.
    - B738: port of the komed3 B737-800 takeoff-speed calculator (MIT,
      github.com/komed3/top-737-800) -- V1/VR/V2 tables indexed by
      pressure-altitude/temperature preference, flap 1/5/15 and weight.
    - A350 (A359/A35X): port of the A350 EFB takeoff calculator
      (TOPerfHelper, bundled with the MSFS A350 package) -- the full
      FCOM-derived takeoff database: runway-limited max TOW plus V1/VR/V2 at
      that limit per runway length (2000-4100 m) x pressure altitude
      (0-8500 ft) x OAT (-30..79 C) x CONF 1+F/2/3 x wind bucket, dry and
      wet; FLEX temp is the highest OAT row whose limit still covers the
      TOW (minus anti-ice / packs / A350-900 corrections); TOGA when the
      flex temp falls below OAT or the flex floor; weights and speeds come
      straight from the aircraft's own takeoff tables.

* Tier 2 (family calibration): the remaining A32x family is run through the
  A320neo engine scaled by its own OEW/MTOW (the limiting-factor framework is
  weight-driven; per-variant FCOM tables are not public).  The 737 family is
  run through the B738 tables scaled to its weight range.

* Tier 3 (generic PERF2601 + vr_isa anchor): every other aircraft uses the
  PERF2601-derived distance curves from performance_profiles.json with the
  profile's reference rotation speed (vr_isa_kt) anchoring the V-speed
  deltas.

All tier-1/2 outputs carry their source so the UI can label them; nothing
here talks to the sim, and everything degrades gracefully (never raises).

Data files: app/data/perf_a320neo_tables.json (A32NX source, A320-251N) and
app/data/perf_a350_tables.json (A350 EFB takeoff bundle, TrentXWB-97 /
XWB-84).
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA = Path(__file__).resolve().parent / "data" / "perf_a320neo_tables.json"
_A350_DATA = Path(__file__).resolve().parent / "data" / "perf_a350_tables.json"

# ---------------------------------------------------------------------------
# Lookup-table port (msfs-sdk LerpLookupTable / LerpVectorLookupTable).
#
# Breakpoints are rows of [value, key1, ..., keyN]; N = row length - 1.
# get(*keys) interpolates linearly per dimension and clamps to the nearest
# breakpoint (no extrapolation), exactly like the MSFS SDK tables the A32NX
# calculator uses.
# ---------------------------------------------------------------------------


class LerpTable:
    def __init__(self, rows: list[list[float] | list[list[float]]]):
        self.dim_count = 0
        self.rows: list[tuple[float, tuple[float, ...]]] = []
        self._build(rows)

    def _build(self, rows: list[Any]) -> None:
        # rows: [value, key...] or [[v1, v2...], key...] for vector tables
        if not rows:
            return
        first = rows[0]
        if isinstance(first[0], list):
            # vector table: value is a list of floats
            self.vector = True
            dim = len(first) - 1
            self.dim_count = dim
            parsed: list[tuple[tuple[float, ...], tuple[float, ...]]] = []
            for row in rows:
                value = tuple(float(x) for x in row[0])
                keys = tuple(float(x) for x in row[1:])
                parsed.append((keys, value))
        else:
            self.vector = False
            dim = len(first) - 1
            self.dim_count = dim
            parsed = []
            for row in rows:
                value = float(row[0])
                keys = tuple(float(x) for x in row[1:])
                parsed.append((keys, (value,)))
        parsed.sort(key=lambda item: item[0])
        self.parsed = parsed
        # Group breakpoints by dimension-1 key (then dimension-2 key, ...)
        self.tree = self._build_tree(parsed, 0)

    def _build_tree(self, items: list[tuple[tuple[float, ...], Any]], dim: int) -> Any:
        if dim >= self.dim_count:
            # leaf: single breakpoint
            return items[0][1] if items else None
        groups: dict[float, list[tuple[tuple[float, ...], Any]]] = {}
        for keys, value in items:
            groups.setdefault(keys[dim], []).append((keys, value))
        sorted_keys = sorted(groups)
        return {
            "keys": sorted_keys,
            "groups": {k: self._build_tree(groups[k], dim + 1) for k in sorted_keys},
        }

    def _interp_1d(self, x: float, a: float, b: float, va: float, vb: float) -> float:
        if b == a:
            return va
        return va + (x - a) * (vb - va) / (b - a)

    def _lookup(self, keys: tuple[float, ...], dim: int, node: Any) -> tuple[float, ...]:
        if dim >= self.dim_count:
            return node
        k = keys[dim]
        ks = node["keys"]
        groups = node["groups"]
        if k <= ks[0]:
            return self._lookup(keys, dim + 1, groups[ks[0]])
        if k >= ks[-1]:
            return self._lookup(keys, dim + 1, groups[ks[-1]])
        # find surrounding
        lo_i = 0
        hi_i = len(ks) - 1
        while hi_i - lo_i > 1:
            mid = (lo_i + hi_i) // 2
            if ks[mid] <= k:
                lo_i = mid
            else:
                hi_i = mid
        k0, k1 = ks[lo_i], ks[hi_i]
        v0 = self._lookup(keys, dim + 1, groups[k0])
        v1 = self._lookup(keys, dim + 1, groups[k1])
        return tuple(self._interp_1d(k, k0, k1, a, b) for a, b in zip(v0, v1))

    def get(self, *keys: float) -> float:
        if self.dim_count == 0:
            raise ValueError("zero-dimensional lookup table")
        if len(keys) < self.dim_count:
            raise ValueError(f"lookup needs {self.dim_count} keys, got {len(keys)}")
        result = self._lookup(tuple(float(x) for x in keys[: self.dim_count]), 0, self.tree)
        return result[0]

    def get_vector(self, *keys: float) -> list[float]:
        if self.dim_count == 0:
            raise ValueError("zero-dimensional lookup table")
        if len(keys) < self.dim_count:
            raise ValueError(f"lookup needs {self.dim_count} keys, got {len(keys)}")
        return list(self._lookup(tuple(float(x) for x in keys[: self.dim_count]), 0, self.tree))


def _vector_table(rows: list[list[float] | list[list[float]]]) -> LerpTable:
    """Build a LerpTable whose breakpoints carry vector values ([[v..], key])."""
    table = LerpTable(rows)
    table.vector = True
    return table


@lru_cache(maxsize=1)
def _tables() -> dict[str, Any]:
    try:
        return json.loads(_DATA.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _table(name: str) -> LerpTable:
    return LerpTable(_tables().get(name) or [])


def _rows_table(rows: Any) -> LerpTable:
    return LerpTable(rows or [])


def _factor_map(name: str) -> dict[int, list[float]]:
    raw = _tables().get(name) or {}
    out: dict[int, list[float]] = {}
    for k, v in raw.items():
        if isinstance(v, (int, float)):
            out[int(k)] = [float(v)]
        else:
            out[int(k)] = [float(x) for x in v]
    return out


def _vector_factor_map(name: str) -> dict[int, LerpTable]:
    raw = _tables().get(name) or {}
    return {int(k): _vector_table(v) for k, v in raw.items()}


# ---------------------------------------------------------------------------
# A320neo takeoff engine (port of A320251NTakeoffPerformanceCalculator)
# ---------------------------------------------------------------------------

_LIMIT_RUNWAY = "runway"
_LIMIT_SECOND_SEGMENT = "second_segment"
_LIMIT_BRAKE_ENERGY = "brake_energy"
_LIMIT_VMCG = "vmcg"


class A320NeoTakeoff:
    structural_mtow = 79_000.0
    max_pressure_alt = 9_200.0
    oew = 42_500.0
    max_headwind = 45.0
    max_tailwind = 15.0
    t_max_flex_disa = 59.0

    lineup_distances = {0: 0.0, 90: 20.5, 180: 41.0}

    def __init__(self, weight_scale: float = 1.0, oew_kg: float | None = None, mtow_kg: float | None = None) -> None:
        # Family calibration: the A32NX tables model the A320-251N (MTOW
        # 79,000 kg / OEW 42,500 kg).  Other A32x family members scale the
        # weight limits by their own MTOW/OEW so the limiting-factor
        # framework stays consistent for the whole narrow-body family.
        self.weight_scale = float(weight_scale or 1.0)
        self.structural_mtow = float(mtow_kg or self.structural_mtow)
        self.oew = float(oew_kg or self.oew)
        self.t_ref_table = _table("tRefTable")
        self.t_max_table = _table("tMaxTable")
        self.runway_perf_limit = {
            1: _table("runwayPerfLimitConf1"),
            2: _table("runwayPerfLimitConf2"),
            3: _table("runwayPerfLimitConf3"),
        }
        self.runway_slope_factor = _factor_map("runwaySlopeFactor")
        self.runway_pressure_alt_factor = _factor_map("runwayPressureAltFactor")
        self.runway_temperature_factor = _factor_map("runwayTemperatureFactor")
        self.runway_headwind_factor = _factor_map("runwayHeadWindFactor")
        self.runway_tailwind_factor = _factor_map("runwayTailWindFactor")

        self.second_segment_base_factor = _factor_map("secondSegmentBaseFactor")
        self.second_segment_slope_factor = _factor_map("secondSegmentSlopeFactor")
        self.second_segment_pressure_alt_factor = _factor_map("secondSegmentPressureAltFactor")
        self.second_segment_temperature_factor = _factor_map("secondSegmentTemperatureFactor")
        self.second_segment_headwind_factor = _factor_map("secondSegmentHeadWindFactor")
        self.second_segment_tailwind_factor = _factor_map("secondSegmentTailWindFactor")

        self.brake_energy_base_factor = _factor_map("brakeEnergyBaseFactor")
        self.brake_energy_slope_factor = _factor_map("brakeEnergySlopeFactor")
        self.brake_energy_pressure_alt_factor = _factor_map("brakeEnergyPressureAltFactor")
        self.brake_energy_temperature_factor = _factor_map("brakeEnergyTemperatureFactor")
        self.brake_energy_headwind_factor = _factor_map("brakeEnergyHeadWindFactor")
        self.brake_energy_tailwind_factor = _factor_map("brakeEnergyTailWindFactor")

        self.vmcg_base_factor = _factor_map("vmcgBaseFactor")
        self.vmcg_slope_factor = _factor_map("vmcgSlopeFactor")
        self.vmcg_pressure_alt_factor = _factor_map("vmcgPressureAltFactor")
        self.vmcg_temperature_factor = _factor_map("vmcgTemperatureFactor")
        self.vmcg_headwind_factor = _factor_map("vmcgHeadWindFactor")
        self.vmcg_tailwind_factor = _factor_map("vmcgTailWindFactor")

        self.takeoff_cg_limits = _vector_table(_tables().get("takeoffCgLimits") or [])
        self.cg_factors = _factor_map("cgFactors")

        self.minimum_v1_vmc = _table("minimumV1Vmc")
        self.minimum_vr_vmc = _table("minimumVrVmc")
        self.minimum_v2_vmc = {int(k): _rows_table(v) for k, v in (_tables().get("minimumV2Vmc") or {}).items()}
        self.minimum_v2_vmu = {int(k): _rows_table(v) for k, v in (_tables().get("minimumV2Vmu") or {}).items()}

        self.v2_runway_vmcg_base = _factor_map("v2RunwayVmcgBaseFactors")
        self.v2_runway_vmcg_alt = _factor_map("v2RunwayVmcgAltFactors")
        self.vr_runway_vmcg_base = _factor_map("vRRunwayVmcgBaseFactors")
        self.vr_runway_vmcg_runway = _factor_map("vRRunwayVmcgRunwayFactors")
        self.vr_runway_vmcg_alt = _factor_map("vRRunwayVmcgAltFactors")
        self.vr_runway_vmcg_slope = _factor_map("vRRunwayVmcgSlopeFactors")
        self.vr_runway_vmcg_headwind = _factor_map("vRRunwayVmcgHeadwindFactors")
        self.vr_runway_vmcg_tailwind = _factor_map("vRRunwayVmcgTailwindFactors")
        self.v1_runway_vmcg_base = _factor_map("v1RunwayVmcgBaseFactors")
        self.v1_runway_vmcg_runway = _factor_map("v1RunwayVmcgRunwayFactors")
        self.v1_runway_vmcg_alt = _factor_map("v1RunwayVmcgAltFactors")
        self.v1_runway_vmcg_slope = _factor_map("v1RunwayVmcgSlopeFactors")
        self.v1_runway_vmcg_headwind = _factor_map("v1RunwayVmcgHeadwindFactors")
        self.v1_runway_vmcg_tailwind = _factor_map("v1RunwayVmcgTailwindFactors")

        self.v2_second_seg_brake_thresholds = _factor_map("v2SecondSegBrakeThresholds")
        self.v2_second_seg_brake_base1 = _factor_map("v2SecondSegBrakeBaseTable1")
        self.v2_second_seg_brake_base2 = _factor_map("v2SecondSegBrakeBaseTable2")
        self.v2_second_seg_brake_runway1 = _factor_map("v2SecondSegBrakeRunwayTable1")
        self.v2_second_seg_brake_runway2 = _factor_map("v2SecondSegBrakeRunwayTable2")
        self.v2_second_seg_brake_alt = _factor_map("v2SecondSegBrakeAltFactors")
        self.v2_second_seg_brake_slope = _factor_map("v2SecondSegBrakeSlopeFactors")
        self.v2_second_seg_brake_headwind = _factor_map("v2SecondSegBrakeHeadwindFactors")
        self.v2_second_seg_brake_tailwind = _factor_map("v2SecondSegBrakeTailwindFactors")

        self.vr_second_seg_brake_base1 = _factor_map("vRSecondSegBrakeBaseTable1")
        self.vr_second_seg_brake_base2 = _factor_map("vRSecondSegBrakeBaseTable2")
        self.vr_second_seg_brake_runway1 = _factor_map("vRSecondSegBrakeRunwayTable1")
        self.vr_second_seg_brake_runway2 = _factor_map("vRSecondSegBrakeRunwayTable2")
        self.vr_second_seg_brake_alt1 = _factor_map("vRSecondSegBrakeAltTable1")
        self.vr_second_seg_brake_alt2 = _factor_map("vRSecondSegBrakeAltTable2")
        self.vr_second_seg_brake_slope = _factor_map("vRSecondSegBrakeSlopeFactors")
        self.vr_second_seg_brake_headwind = _factor_map("vRSecondSegBrakeHeadwindFactors")
        self.vr_second_seg_brake_tailwind = _factor_map("vRSecondSegBrakeTailwindFactors")

        self.v1_second_seg_brake_base1 = _factor_map("v1SecondSegBrakeBaseTable1")
        self.v1_second_seg_brake_base2 = _factor_map("v1SecondSegBrakeBaseTable2")
        self.v1_second_seg_brake_runway1 = _factor_map("v1SecondSegBrakeRunwayTable1")
        self.v1_second_seg_brake_runway2 = _factor_map("v1SecondSegBrakeRunwayTable2")
        self.v1_second_seg_brake_alt1 = _factor_map("v1SecondSegBrakeAltTable1")
        self.v1_second_seg_brake_alt2 = _factor_map("v1SecondSegBrakeAltTable2")
        self.v1_second_seg_brake_slope = _factor_map("v1SecondSegBrakeSlopeFactors")
        self.v1_second_seg_brake_headwind = _factor_map("v1SecondSegBrakeHeadwindFactors")
        self.v1_second_seg_brake_tailwind = _factor_map("v1SecondSegBrakeTailwindFactors")

        self.tvmcg_factors = _vector_factor_map("tvmcgFactors")
        self.wet_tow_adjustment_below = _vector_factor_map("wetTowAdjustmentFactorsAtOrBelowTvmcg")
        self.wet_tow_adjustment_above = _vector_factor_map("wetTowAdjustmentFactorsAboveTvmcg")
        self.wet_flex_adjustment_below = _vector_factor_map("wetFlexAdjustmentFactorsAtOrBelowTvmcg")
        self.wet_flex_adjustment_above = _vector_factor_map("wetFlexAdjustmentFactorsAboveTvmcg")
        self.wet_v1_adjustment_below = _vector_factor_map("wetV1AdjustmentFactorsAtOrBelowTvmcg")
        self.wet_v1_adjustment_above = _vector_factor_map("wetV1AdjustmentFactorsAboveTvmcg")
        self.wet_vr_adjustment_below = _vector_factor_map("wetVRAdjustmentFactorsAtOrBelowTvmcg")
        self.wet_v2_adjustment_below = _vector_factor_map("wetV2AdjustmentFactorsAtOrBelowTvmcg")

    # -- atmosphere ---------------------------------------------------------

    @staticmethod
    def isa_temp(elevation_ft: float) -> float:
        return 15.0 - elevation_ft * 0.0019812

    def tref(self, elevation_ft: float) -> float:
        return self.t_ref_table.get(elevation_ft)

    def tmax(self, pressure_alt_ft: float) -> float:
        return self.t_max_table.get(pressure_alt_ft)

    def tflexmax(self, isa: float) -> float:
        return isa + self.t_max_flex_disa

    @staticmethod
    def pressure_altitude(elevation_ft: float, qnh_hpa: float) -> float:
        return elevation_ft + 145442.15 * (1 - (qnh_hpa / 1013.25) ** 0.190263)

    # -- weight limits ------------------------------------------------------

    def base_runway_perf_limit(self, length_m: float, conf: int) -> float:
        return self.runway_perf_limit[conf].get(length_m) * self.weight_scale

    def base_limit(self, length_m: float, conf: int, factors: dict[int, list[float]]) -> float:
        f1, f2 = factors[conf]
        return 1000.0 * (length_m * f1 + f2) * self.weight_scale

    def _runway_temp_delta(self, temp, conf, t_ref, t_max, t_flex_max, runway_length, pressure_alt, isa) -> float:
        if temp > t_flex_max:
            return math.nan
        f = self.runway_temperature_factor[conf]
        runway_alt_factor = runway_length - pressure_alt / 12.0
        delta = 1000.0 * (runway_alt_factor * f[0] + f[1]) * (min(temp, t_ref) - isa)
        if temp > t_ref:
            delta += 1000.0 * (runway_alt_factor * f[2] + f[3]) * (min(temp, t_max) - t_ref)
        if temp > t_max:
            delta += 1000.0 * (runway_alt_factor * f[4] + f[5]) * (temp - t_max)
        return delta

    def _second_segment_temp_delta(self, temp, conf, t_ref, t_max, t_flex_max, runway_length, pressure_alt, isa) -> float:
        if temp > t_flex_max:
            return math.nan
        f = self.second_segment_temperature_factor[conf]
        runway_alt_factor = runway_length - pressure_alt / 5.0
        delta = 1000.0 * (runway_alt_factor * f[0] + f[1]) * (min(temp, t_ref) - isa)
        if temp > t_ref:
            delta += 1000.0 * (runway_alt_factor * f[2] + f[3]) * (min(temp, t_max) - t_ref)
        if temp > t_max:
            delta += 1000.0 * (runway_alt_factor * f[4] + f[5]) * (temp - t_max)
        return delta

    def _brake_energy_temp_delta(self, temp, conf, t_ref, t_max, t_flex_max, runway_length, pressure_alt, isa) -> float:
        if temp > t_flex_max:
            return math.nan
        f = self.brake_energy_temperature_factor[conf]
        delta = 1000.0 * f[0] * (min(temp, t_ref) - isa)
        if temp > t_ref:
            delta += 1000.0 * f[1] * (min(temp, t_max) - t_ref)
        return delta

    def _vmcg_temp_delta(self, temp, conf, t_ref, t_max, t_flex_max, runway_length, pressure_alt, isa) -> float:
        if temp > t_flex_max:
            return math.nan
        f = self.vmcg_temperature_factor[conf]
        delta = 1000.0 * (runway_length * f[0] + f[1]) * (min(temp, t_ref) - isa)
        if temp > t_ref:
            delta += 1000.0 * (runway_length * f[2] + f[3]) * (min(temp, t_max) - t_ref)
        if temp > t_max:
            delta += 1000.0 * (runway_length * f[4] + f[5]) * (temp - t_max)
        return delta

    def _wind_delta(self, factors, temp, conf, isa, t_ref, t_max, t_flex_max, runway_length, wind) -> float:
        if temp > t_flex_max:
            return math.nan
        wind_factors = factors[conf]
        delta = 1000.0 * (runway_length * wind_factors[0] + wind_factors[1]) * wind
        if temp > t_ref:
            delta += 1000.0 * wind_factors[2] * wind * (min(temp, t_max) - t_ref)
        if temp > t_max:
            delta += 1000.0 * wind_factors[3] * wind * (temp - t_max)
        # cover an edge case near the ends of the data
        if (delta > 0) == (wind > 0) and delta != 0 and wind != 0:
            return 0.0
        return delta

    def _runway_wind_delta(self, temp, conf, isa, t_ref, t_max, t_flex_max, runway_length, wind) -> float:
        factors = self.runway_headwind_factor if wind >= 0 else self.runway_tailwind_factor
        return self._wind_delta(factors, temp, conf, isa, t_ref, t_max, t_flex_max, runway_length, wind)

    def _second_segment_wind_delta(self, temp, conf, isa, t_ref, t_max, t_flex_max, runway_length, wind) -> float:
        factors = self.second_segment_headwind_factor if wind >= 0 else self.second_segment_tailwind_factor
        return self._wind_delta(factors, temp, conf, isa, t_ref, t_max, t_flex_max, runway_length, wind)

    def _brake_energy_wind_delta(self, temp, conf, isa, t_ref, t_max, t_flex_max, runway_length, wind) -> float:
        factors = self.brake_energy_headwind_factor if wind >= 0 else self.brake_energy_tailwind_factor
        return self._wind_delta(factors, temp, conf, isa, t_ref, t_max, t_flex_max, runway_length, wind)

    def _vmcg_wind_delta(self, temp, conf, isa, t_ref, t_max, t_flex_max, runway_length, wind) -> float:
        if temp > t_flex_max:
            return math.nan
        if wind >= 0:
            f = self.vmcg_headwind_factor[conf]
            delta = 1000.0 * (runway_length * f[0] + f[1]) * wind
            if temp > isa:
                delta += 1000.0 * (runway_length * f[2] + f[3]) * wind * (min(temp, t_ref) - isa)
            if temp > t_ref:
                delta += 1000.0 * (runway_length * f[4] + f[5]) * wind * (min(temp, t_max) - t_ref)
            if temp >= t_max:
                delta += 1000.0 * (runway_length * f[6] + f[7]) * wind * (temp - t_max)
        else:
            f = self.vmcg_tailwind_factor[conf]
            delta = 1000.0 * (runway_length * f[0] + f[1]) * wind
            if temp > isa:
                delta += 1000.0 * (runway_length * f[2] + f[3]) * wind * (min(temp, t_ref) - isa)
            if temp > t_ref:
                delta += 1000.0 * f[4] * wind * (min(temp, t_max) - t_ref)
            if temp > t_max:
                delta += 1000.0 * f[5] * wind * (temp - t_max)
        if (delta > 0) == (wind > 0) and delta != 0 and wind != 0:
            return 0.0
        return delta

    def weight_limits(self, limiting_factor: str, *, tow, conf, tora, slope, wind, elevation, qnh, oat,
                      anti_ice_wing, packs) -> dict[str, float]:
        isa = self.isa_temp(elevation)
        t_ref = self.tref(elevation)
        pressure_alt = self.pressure_altitude(elevation, qnh)
        t_max = self.tmax(pressure_alt)
        t_flex_max = self.tflexmax(isa)
        headwind = min(self.max_headwind, wind)

        if limiting_factor == _LIMIT_RUNWAY:
            base = self.base_runway_perf_limit(tora, conf)
            slope_factors = self.runway_slope_factor
            alt_factors = self.runway_pressure_alt_factor
            temp_delta = self._runway_temp_delta
            wind_delta = self._runway_wind_delta
        else:
            if limiting_factor == _LIMIT_SECOND_SEGMENT:
                base = self.base_limit(tora, conf, self.second_segment_base_factor)
                slope_factors = self.second_segment_slope_factor
                alt_factors = self.second_segment_pressure_alt_factor
                temp_delta = self._second_segment_temp_delta
                wind_delta = self._second_segment_wind_delta
            elif limiting_factor == _LIMIT_BRAKE_ENERGY:
                base = self.base_limit(tora, conf, self.brake_energy_base_factor)
                slope_factors = self.brake_energy_slope_factor
                alt_factors = self.brake_energy_pressure_alt_factor
                temp_delta = self._brake_energy_temp_delta
                wind_delta = self._brake_energy_wind_delta
            else:
                base = self.base_limit(tora, conf, self.vmcg_base_factor)
                slope_factors = self.vmcg_slope_factor
                alt_factors = self.vmcg_pressure_alt_factor
                temp_delta = self._vmcg_temp_delta
                wind_delta = self._vmcg_wind_delta

        ws = self.weight_scale
        delta_slope = 1000.0 * slope_factors[conf][0] * tora * slope * ws
        slope_limit = base - delta_slope

        alt1, alt2 = alt_factors[conf]
        delta_alt = 1000.0 * pressure_alt * (pressure_alt * alt1 + alt2) * ws
        alt_limit = slope_limit - delta_alt

        delta_bleed = ((1600.0 if anti_ice_wing else 0.0) + (1500.0 if packs else 0.0)) * ws

        oat_delta_temp = temp_delta(oat, conf, t_ref, t_max, t_flex_max, tora, pressure_alt, isa) * ws
        oat_delta_wind = wind_delta(oat, conf, isa, t_ref, t_max, t_flex_max, tora, headwind) * ws
        oat_limit_no_bleed = alt_limit - oat_delta_temp - oat_delta_wind
        oat_limit = oat_limit_no_bleed - delta_bleed

        t_ref_delta_temp = temp_delta(t_ref, conf, t_ref, t_max, t_flex_max, tora, pressure_alt, isa) * ws
        t_ref_delta_wind = wind_delta(t_ref, conf, isa, t_ref, t_max, t_flex_max, tora, headwind) * ws
        t_ref_limit_no_bleed = alt_limit - t_ref_delta_temp - t_ref_delta_wind
        t_ref_limit = t_ref_limit_no_bleed - delta_bleed

        t_max_delta_temp = temp_delta(t_max, conf, t_ref, t_max, t_flex_max, tora, pressure_alt, isa) * ws
        t_max_delta_wind = wind_delta(t_max, conf, isa, t_ref, t_max, t_flex_max, tora, headwind) * ws
        t_max_limit_no_bleed = alt_limit - t_max_delta_temp - t_max_delta_wind
        t_max_limit = t_max_limit_no_bleed - delta_bleed

        t_flex_delta_temp = temp_delta(t_flex_max, conf, t_ref, t_max, t_flex_max, tora, pressure_alt, isa) * ws
        t_flex_delta_wind = wind_delta(t_flex_max, conf, isa, t_ref, t_max, t_flex_max, tora, headwind) * ws
        t_flex_limit_no_bleed = alt_limit - t_flex_delta_temp - t_flex_delta_wind
        t_flex_limit = t_flex_limit_no_bleed - delta_bleed

        return {
            "baseLimit": base,
            "slopeLimit": slope_limit,
            "altLimit": alt_limit,
            "oatLimit": oat_limit,
            "tRefLimit": t_ref_limit,
            "tMaxLimit": t_max_limit,
            "tFlexMaxLimit": t_flex_limit,
            "oatLimitNoBleed": oat_limit_no_bleed,
            "tRefLimitNoBleed": t_ref_limit_no_bleed,
            "tMaxLimitNoBleed": t_max_limit_no_bleed,
            "tFlexMaxLimitNoBleed": t_flex_limit_no_bleed,
            "tRef": t_ref,
            "tMax": t_max,
            "tFlexMax": t_flex_max,
            "isaTemp": isa,
            "pressureAlt": pressure_alt,
            "headwind": headwind,
        }

    # -- flex temp ----------------------------------------------------------

    def _flex_tow(self, result, limiting_factor, limiting_weights, temperature) -> float:
        tora = result["tora"]
        conf = result["conf"]
        params = result["params"]
        ws = self.weight_scale
        if limiting_factor == _LIMIT_RUNWAY:
            return (
                limiting_weights["altLimit"]
                - self._runway_temp_delta(temperature, conf, params["tRef"], params["tMax"], params["tFlexMax"], tora, params["pressureAlt"], params["isaTemp"]) * ws
                - self._runway_wind_delta(temperature, conf, params["isaTemp"], params["tRef"], params["tMax"], params["tFlexMax"], tora, params["headwind"]) * ws
            )
        if limiting_factor == _LIMIT_SECOND_SEGMENT:
            return (
                limiting_weights["altLimit"]
                - self._second_segment_temp_delta(temperature, conf, params["tRef"], params["tMax"], params["tFlexMax"], tora, params["pressureAlt"], params["isaTemp"]) * ws
                - self._second_segment_wind_delta(temperature, conf, params["isaTemp"], params["tRef"], params["tMax"], params["tFlexMax"], tora, params["headwind"]) * ws
            )
        if limiting_factor == _LIMIT_BRAKE_ENERGY:
            return (
                limiting_weights["altLimit"]
                - self._brake_energy_temp_delta(temperature, conf, params["tRef"], params["tMax"], params["tFlexMax"], tora, params["pressureAlt"], params["isaTemp"]) * ws
                - self._brake_energy_wind_delta(temperature, conf, params["isaTemp"], params["tRef"], params["tMax"], params["tFlexMax"], tora, params["headwind"]) * ws
            )
        return (
            limiting_weights["altLimit"]
            - self._vmcg_temp_delta(temperature, conf, params["tRef"], params["tMax"], params["tFlexMax"], tora, params["pressureAlt"], params["isaTemp"]) * ws
            - self._vmcg_wind_delta(temperature, conf, params["isaTemp"], params["tRef"], params["tMax"], params["tFlexMax"], tora, params["headwind"]) * ws
        )

    def flex_temp(self, result, limits_by_factor, limiting_factors, tvmcg, wet: bool) -> tuple[float | None, str | None]:
        tow = result["tow"]
        params = result["params"]
        t_ref_factor = limiting_factors["tRef"]
        t_max_factor = limiting_factors["tMax"]
        t_flex_factor = limiting_factors["tFlexMax"]

        if tow < limits_by_factor[t_ref_factor]["tRefLimit"]:
            flex_temp = None
            flex_factor = None
            if tow > limits_by_factor[t_max_factor]["tMaxLimitNoBleed"]:
                iter_from, iter_to = params["tRef"], params["tMax"]
                from_factor, from_weights = t_ref_factor, limits_by_factor[t_ref_factor]
                to_factor, to_weights = t_max_factor, limits_by_factor[t_max_factor]
            elif tow > limits_by_factor[t_flex_factor]["tFlexMaxLimitNoBleed"]:
                iter_from, iter_to = params["tMax"], params["tFlexMax"]
                from_factor, from_weights = t_max_factor, limits_by_factor[t_max_factor]
                to_factor, to_weights = t_flex_factor, limits_by_factor[t_flex_factor]
            else:
                iter_from, iter_to = params["tFlexMax"], params["tFlexMax"] + 8
                from_factor, from_weights = t_flex_factor, limits_by_factor[t_flex_factor]
                to_factor, to_weights = t_flex_factor, from_weights

            for t in range(int(iter_from), int(iter_to) + 1):
                from_limit_tow = self._flex_tow(result, from_factor, from_weights, float(t))
                to_limit_tow = self._flex_tow(result, to_factor, to_weights, float(t))
                if tow <= min(from_limit_tow, to_limit_tow):
                    flex_temp = float(t)
                    flex_factor = from_factor if from_limit_tow <= to_limit_tow else to_factor

            if flex_temp is not None:
                # anti-ice / packs corrections (engine-anti-ice only and
                # engine+wing are merged into the boolean wing flag by callers)
                if result.get("anti_ice_wing"):
                    flex_temp -= 6.0
                elif result.get("anti_ice_engine"):
                    flex_temp -= 2.0
                if result.get("packs"):
                    flex_temp -= 2.0
                flex_temp = min(flex_temp, params["tFlexMax"])
                flex_temp = math.trunc(flex_temp)
                if wet:
                    factor_table = (
                        self.wet_flex_adjustment_above if result["oat"] > tvmcg else self.wet_flex_adjustment_below
                    )[result["conf"]]
                    f = factor_table.get_vector(params["headwind"])
                    length_alt_coef = result["tora"] - params["pressureAlt"] / 20.0
                    wet_flex_adjustment = min(0.0, f[0] * length_alt_coef + f[1], f[2] * length_alt_coef + f[3])
                    flex_temp -= wet_flex_adjustment
                if flex_temp > result["oat"]:
                    return flex_temp, flex_factor
        return None, None

    # -- speeds -------------------------------------------------------------

    def _reconcile_speeds(self, result, v1, vr, v2):
        pressure_alt = result["params"]["pressureAlt"]
        conf = result["conf"]
        min_v1_vmc = math.ceil(self.minimum_v1_vmc.get(pressure_alt))
        min_vr_vmc = math.ceil(self.minimum_vr_vmc.get(pressure_alt))
        min_v2_vmc = math.ceil(self.minimum_v2_vmc[conf].get(pressure_alt))
        min_v2_vmu = math.ceil(self.minimum_v2_vmu[conf].get(pressure_alt, result["tow"]))

        v1_c = round(max(v1, min_v1_vmc))
        vr_c = round(max(vr, min_vr_vmc))
        v2_c = round(max(v2, min_v2_vmc, min_v2_vmu))

        if vr_c > v2_c:
            vr_c = v2_c
        if v2_c > 195:
            max_vr = math.trunc(195 - (v2_c - 195))
            if vr_c > 195:
                result["error"] = "MAXIMUM TIRE SPEED"
            elif vr_c > max_vr:
                vr_c = max_vr
        if v1_c > vr_c:
            v1_c = vr_c
        return v1_c, vr_c, v2_c

    def _dry_speeds(self, result, forward_cg_speed_correction):
        tow = result["tow"]
        conf = result["conf"]
        params = result["params"]
        limiting_factor = result.get("flexLimitingFactor") or result["oatLimitingFactor"]

        if limiting_factor in (_LIMIT_RUNWAY, _LIMIT_VMCG):
            # v2
            b1, b2 = self.v2_runway_vmcg_base[conf]
            v2_base = (tow / 1000.0) * b1 + b2
            a1, a2 = self.v2_runway_vmcg_alt[conf]
            v2_delta_alt = ((tow / 1000.0) * a1 + a2) * params["pressureAlt"]
            v2 = v2_base + v2_delta_alt

            # vr
            b1, b2 = self.vr_runway_vmcg_base[conf]
            vr_base = (tow / 1000.0) * b1 + b2
            base_len, r1, r2 = self.vr_runway_vmcg_runway[conf]
            vr_delta_runway = (base_len - params["adjustedTora"]) * ((tow / 1000.0) * r1 + r2)
            a1, a2 = self.vr_runway_vmcg_alt[conf]
            vr_delta_alt = params["pressureAlt"] * ((tow / 1000.0) * a1 + a2)
            vr_delta_slope = result["slope"] * params["adjustedTora"] * self.vr_runway_vmcg_slope[conf][0]
            wind_factors = self.vr_runway_vmcg_headwind if params["headwind"] >= 0 else self.vr_runway_vmcg_tailwind
            w1, w2 = wind_factors[conf]
            vr_delta_wind = params["headwind"] * ((tow / 1000.0) * w1 + w2)
            vr = vr_base + vr_delta_runway + vr_delta_alt + vr_delta_slope + vr_delta_wind + (-1 if forward_cg_speed_correction else 0)

            # v1
            b1, b2 = self.v1_runway_vmcg_base[conf]
            v1_base = (tow / 1000.0) * b1 + b2
            base_len, r1, r2 = self.v1_runway_vmcg_runway[conf]
            v1_delta_runway = (base_len - params["adjustedTora"]) * ((tow / 1000.0) * r1 + r2)
            a1, a2 = self.v1_runway_vmcg_alt[conf]
            v1_delta_alt = params["pressureAlt"] * ((tow / 1000.0) * a1 + a2)
            v1_delta_slope = result["slope"] * params["adjustedTora"] * self.v1_runway_vmcg_slope[conf][0]
            wind_factors = self.v1_runway_vmcg_headwind if params["headwind"] >= 0 else self.v1_runway_vmcg_tailwind
            w1, w2 = wind_factors[conf]
            v1_delta_wind = params["headwind"] * ((tow / 1000.0) * w1 + w2)
            v1 = v1_base + v1_delta_runway + v1_delta_alt + v1_delta_slope + v1_delta_wind
        else:
            # second segment or brake energy limited
            v2_nowind = self._second_seg_brake_v2(result, False, False)
            t1, t2 = self.v2_second_seg_brake_thresholds[conf]
            v2_table2_threshold = params["adjustedTora"] * t1 + t2
            use_table2 = v2_nowind >= v2_table2_threshold
            v2 = self._second_seg_brake_v2(result, True, use_table2)

            vrb = self.vr_second_seg_brake_base2 if use_table2 else self.vr_second_seg_brake_base1
            b1, b2 = vrb[conf]
            vr_base = (tow / 1000.0) * b1 + b2
            runway_f = self.vr_second_seg_brake_runway2 if use_table2 else self.vr_second_seg_brake_runway1
            base_len, r1, r2 = runway_f[conf]
            vr_delta_runway = (base_len - params["adjustedTora"]) * ((tow / 1000.0) * r1 + r2)
            alt_f = self.vr_second_seg_brake_alt2 if use_table2 else self.vr_second_seg_brake_alt1
            a1, a2, a3, a4 = alt_f[conf]
            vr_delta_alt = params["pressureAlt"] * ((tow / 1000.0) * a1 + a2) * (params["adjustedTora"] * a3 + a4)
            s1, s2 = self.vr_second_seg_brake_slope[conf]
            vr_delta_slope = result["slope"] * params["adjustedTora"] * ((tow / 1000.0) * s1 + s2)
            wind_f = self.vr_second_seg_brake_headwind if params["headwind"] >= 0 else self.vr_second_seg_brake_tailwind
            w1, w2 = wind_f[conf]
            vr_delta_wind = params["headwind"] * ((tow / 1000.0) * w1 + w2)
            vr = vr_base + vr_delta_runway + vr_delta_alt + vr_delta_slope + vr_delta_wind

            v1 = self._second_seg_brake_v1(result, use_table2)
            if use_table2 and v2 - v1 > 8:
                v1 = self._second_seg_brake_v1(result, False)

        return self._reconcile_speeds(result, v1, vr, v2)

    def _second_seg_brake_v2(self, result, correct_wind, use_table2):
        tow = result["tow"]
        conf = result["conf"]
        params = result["params"]
        base_f = self.v2_second_seg_brake_base2 if use_table2 else self.v2_second_seg_brake_base1
        b1, b2 = base_f[conf]
        v2_base = (tow / 1000.0) * b1 + b2
        runway_f = self.v2_second_seg_brake_runway2 if use_table2 else self.v2_second_seg_brake_runway1
        base_len, r1 = runway_f[conf]
        v2_delta_runway = (base_len - params["adjustedTora"]) * r1
        a1, a2, a3, a4 = self.v2_second_seg_brake_alt[conf]
        v2_delta_alt = params["pressureAlt"] * ((tow / 1000.0) * a1 + a2) * (params["adjustedTora"] * a3 + a4)
        s1, s2 = self.v2_second_seg_brake_slope[conf]
        v2_delta_slope = result["slope"] * params["adjustedTora"] * ((tow / 1000.0) * s1 + s2)
        if correct_wind:
            wind_f = self.v2_second_seg_brake_headwind if params["headwind"] >= 0 else self.v2_second_seg_brake_tailwind
            v2_delta_wind = params["headwind"] * wind_f[conf][0]
        else:
            v2_delta_wind = 0.0
        return v2_base + v2_delta_runway + v2_delta_alt + v2_delta_slope + v2_delta_wind

    def _second_seg_brake_v1(self, result, use_table2):
        tow = result["tow"]
        conf = result["conf"]
        params = result["params"]
        base_f = self.v1_second_seg_brake_base2 if use_table2 else self.v1_second_seg_brake_base1
        b1, b2 = base_f[conf]
        v1_base = (tow / 1000.0) * b1 + b2
        runway_f = self.v1_second_seg_brake_runway2 if use_table2 else self.v1_second_seg_brake_runway1
        base_len, r1, r2 = runway_f[conf]
        v1_delta_runway = (base_len - params["adjustedTora"]) * ((tow / 1000.0) * r1 + r2)
        alt_f = self.v1_second_seg_brake_alt2 if use_table2 else self.v1_second_seg_brake_alt1
        a1, a2, a3, a4 = alt_f[conf]
        v1_delta_alt = params["pressureAlt"] * ((tow / 1000.0) * a1 + a2) * (params["adjustedTora"] * a3 + a4)
        s1, s2 = self.v1_second_seg_brake_slope[conf]
        v1_delta_slope = result["slope"] * params["adjustedTora"] * ((tow / 1000.0) * s1 + s2)
        wind_f = self.v1_second_seg_brake_headwind if params["headwind"] >= 0 else self.v1_second_seg_brake_tailwind
        w1, w2 = wind_f[conf]
        v1_delta_wind = params["headwind"] * ((tow / 1000.0) * w1 + w2)
        return v1_base + v1_delta_runway + v1_delta_alt + v1_delta_slope + v1_delta_wind

    # -- main entry ---------------------------------------------------------

    def calculate(
        self,
        *,
        tow: float,
        conf: int,
        tora: float,
        slope: float,
        wind: float,
        elevation: float,
        qnh: float,
        oat: float,
        anti_ice_engine: bool = False,
        anti_ice_wing: bool = False,
        packs: bool = False,
        wet: bool = False,
        cg: float | None = None,
        forward_cg: bool = False,
        lineup_angle: int = 0,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "tow": tow,
            "conf": conf,
            "tora": tora,
            "slope": slope,
            "wind": wind,
            "elevation": elevation,
            "qnh": qnh,
            "oat": oat,
            "anti_ice_engine": bool(anti_ice_engine),
            "anti_ice_wing": bool(anti_ice_wing),
            "packs": bool(packs),
            "wet": bool(wet),
            "cg": cg,
            "forward_cg": bool(forward_cg),
            "lineup_angle": lineup_angle,
        }
        isa = self.isa_temp(elevation)
        t_ref = self.tref(elevation)
        pressure_alt = self.pressure_altitude(elevation, qnh)
        t_max = self.tmax(pressure_alt)
        t_flex_max = self.tflexmax(isa)
        headwind = min(self.max_headwind, wind)
        result["params"] = {
            "adjustedTora": tora - (self.lineup_distances.get(lineup_angle, 0.0)),
            "pressureAlt": pressure_alt,
            "isaTemp": isa,
            "tRef": t_ref,
            "tMax": t_max,
            "tFlexMax": t_flex_max,
            "headwind": headwind,
        }
        result["error"] = None

        if tow > self.structural_mtow:
            result["error"] = "STRUCTURAL MTOW EXCEEDED"
        if pressure_alt > self.max_pressure_alt:
            result["error"] = result["error"] or "MAXIMUM PRESSURE ALTITUDE"
        if oat > t_max:
            result["error"] = result["error"] or "MAXIMUM TEMPERATURE"
        if tow < self.oew:
            result["error"] = result["error"] or "BELOW OPERATING EMPTY WEIGHT"
        if cg is not None:
            lo, hi = self.takeoff_cg_limits.get_vector(tow)
            if not (lo <= cg <= hi):
                result["error"] = result["error"] or "CG OUT OF LIMITS"
        if wind < -self.max_tailwind:
            result["error"] = result["error"] or "MAXIMUM TAILWIND EXCEEDED"
        if abs(slope) > 2:
            result["error"] = result["error"] or "MAXIMUM RUNWAY SLOPE"

        if result["error"]:
            result["speeds"] = {"v1_kt": None, "vr_kt": None, "v2_kt": None}
            result["flex"] = None
            result["mtow"] = None
            return result

        limits_by_factor = {
            _LIMIT_RUNWAY: self.weight_limits(_LIMIT_RUNWAY, tow=tow, conf=conf, tora=result["params"]["adjustedTora"],
                                              slope=slope, wind=wind, elevation=elevation, qnh=qnh, oat=oat,
                                              anti_ice_wing=anti_ice_wing, packs=packs),
            _LIMIT_SECOND_SEGMENT: self.weight_limits(_LIMIT_SECOND_SEGMENT, tow=tow, conf=conf, tora=result["params"]["adjustedTora"],
                                                      slope=slope, wind=wind, elevation=elevation, qnh=qnh, oat=oat,
                                                      anti_ice_wing=anti_ice_wing, packs=packs),
            _LIMIT_BRAKE_ENERGY: self.weight_limits(_LIMIT_BRAKE_ENERGY, tow=tow, conf=conf, tora=result["params"]["adjustedTora"],
                                                    slope=slope, wind=wind, elevation=elevation, qnh=qnh, oat=oat,
                                                    anti_ice_wing=anti_ice_wing, packs=packs),
            _LIMIT_VMCG: self.weight_limits(_LIMIT_VMCG, tow=tow, conf=conf, tora=result["params"]["adjustedTora"],
                                            slope=slope, wind=wind, elevation=elevation, qnh=qnh, oat=oat,
                                            anti_ice_wing=anti_ice_wing, packs=packs),
        }

        def limiting(temp_key: str) -> str:
            best = None
            best_weight = math.inf
            for factor, weights in limits_by_factor.items():
                w = weights[temp_key]
                if w < best_weight:
                    best_weight = w
                    best = factor
            return best or _LIMIT_RUNWAY

        result["oatLimitingFactor"] = limiting("oatLimit")
        result["tRefLimitingFactor"] = limiting("tRefLimit")
        result["tMaxLimitingFactor"] = limiting("tMaxLimit")
        result["tFlexMaxLimitingFactor"] = limiting("tFlexMaxLimit")

        dry_mtow = limits_by_factor[result["tRefLimitingFactor"]]["oatLimit"]
        tvmcg = self.tvmcg_factors[conf].get_vector(max(headwind, -15))
        tvmcg = tvmcg[0] * (result["params"]["adjustedTora"] - pressure_alt / 10.0) + tvmcg[1]

        mtow = dry_mtow
        if wet:
            factors = self.wet_tow_adjustment_above if oat > tvmcg else self.wet_tow_adjustment_below
            f = factors[conf].get_vector(headwind)
            length_alt_coef = result["params"]["adjustedTora"] - pressure_alt / 20.0
            wet_mtow_adjustment = min(0.0, f[0] * length_alt_coef + f[1], f[2] * length_alt_coef + f[3])
            mtow = dry_mtow - wet_mtow_adjustment
        result["mtow"] = mtow

        apply_forward_cg_weight = forward_cg and result["oatLimitingFactor"] in (_LIMIT_RUNWAY, _LIMIT_VMCG)
        apply_forward_cg_speed = apply_forward_cg_weight and mtow <= 73_000.0
        if apply_forward_cg_weight:
            c1, c2 = self.cg_factors[conf]
            mtow += max(0.0, c1 * mtow + c2)
        result["mtow_adjusted"] = mtow

        if mtow >= tow:
            # FLEX is only a thrust reduction; V-speeds are always computed
            # (flex only selects which limiting factor drives the speeds).
            result["flex"] = None
            result["flexLimitingFactor"] = None
            if not wet:
                limiting_factors = {
                    "tRef": result["tRefLimitingFactor"],
                    "tMax": result["tMaxLimitingFactor"],
                    "tFlexMax": result["tFlexMaxLimitingFactor"],
                }
                result["flex"], result["flexLimitingFactor"] = self.flex_temp(
                    result, limits_by_factor, limiting_factors, tvmcg, wet=False)
            v1, vr, v2 = self._dry_speeds(result, apply_forward_cg_speed)
            if wet:
                v1_factors = self.wet_v1_adjustment_above if oat > tvmcg else self.wet_v1_adjustment_below
                f1 = v1_factors[conf].get_vector(headwind)
                length_alt_coef = result["params"]["adjustedTora"] - pressure_alt / 20.0
                wet_v1_adjustment = min(0.0, f1[0] * length_alt_coef + f1[1], f1[2] * length_alt_coef + f1[3])
                vr_adjustment = 0.0
                v2_adjustment = 0.0
                if oat <= tvmcg:
                    vr_factors = self.wet_vr_adjustment_below[conf].get_vector(headwind)
                    vr_adjustment = min(0.0, vr_factors[0] * length_alt_coef + vr_factors[1],
                                        vr_factors[2] * length_alt_coef + vr_factors[3])
                    v2_factors = self.wet_v2_adjustment_below[conf].get_vector(headwind)
                    v2_adjustment = min(0.0, v2_factors[0] * length_alt_coef + v2_factors[1],
                                        v2_factors[2] * length_alt_coef + v2_factors[3])
                v1, vr, v2 = self._reconcile_speeds(result, v1 - wet_v1_adjustment, vr - vr_adjustment, v2 - v2_adjustment)
            result["speeds"] = {"v1_kt": v1, "vr_kt": vr, "v2_kt": v2}
        else:
            result["error"] = "TOO HEAVY"
            result["speeds"] = {"v1_kt": None, "vr_kt": None, "v2_kt": None}

        if cg is not None:
            result["stab_trim"] = round(self._stab_trim(cg), 1)
        else:
            result["stab_trim"] = None
        return result

    @staticmethod
    def _stab_trim(cg: float) -> float:
        # port of calculateStabTrim: lerp(cg, 17, 40, 3.8, -2.5)
        if cg <= 17:
            return 3.8
        if cg >= 40:
            return -2.5
        return 3.8 + (cg - 17) * (-2.5 - 3.8) / (40 - 17)

    def required_tora(self, *, tow: float, slope: float = 0.0, wind: float = 0.0, elevation: float = 0.0,
                      qnh: float = 1013.25, oat: float = 15.0, anti_ice_wing: bool = False,
                      packs: bool = False, conf: int = 2) -> float | None:
        """Minimum runway length (m) at which this TOW fits (runway-limited).

        Binary search over TORA on the runway factor's OAT limit.  Returns
        None when even 8 km is not enough (another factor caps below TOW).
        """
        def runway_limit(tora: float) -> float:
            weights = self.weight_limits(
                _LIMIT_RUNWAY, tow=tow, conf=conf, tora=tora, slope=slope, wind=wind,
                elevation=elevation, qnh=qnh, oat=oat, anti_ice_wing=anti_ice_wing, packs=packs)
            return weights["oatLimit"]

        lo, hi = 500.0, 8000.0
        if runway_limit(hi) < tow:
            return None
        for _ in range(40):
            mid = (lo + hi) / 2.0
            if runway_limit(mid) >= tow:
                hi = mid
            else:
                lo = mid
        return hi

    def calculate_opt_config(self, **kwargs: Any) -> dict[str, Any]:
        """Run all three takeoff configs and pick the best (highest flex, then
        lowest V1).  Mirrors calculateTakeoffPerformanceOptConf."""
        results = [self.calculate(conf=c, **kwargs) for c in (1, 2, 3)]
        ok = [r for r in results if not r.get("error")]
        if not ok:
            best = max(results, key=lambda r: r["conf"])
            best["configs"] = [{"conf": r["conf"], "error": r.get("error")} for r in results]
            return best
        ok.sort(key=lambda r: (r.get("flex") if r.get("flex") is not None else -1, r["speeds"]["v1_kt"] or 0), reverse=True)
        chosen = dict(ok[0])
        chosen["configs"] = [
            {
                "conf": r["conf"],
                "error": r.get("error"),
                "flex": r.get("flex"),
                "v1_kt": r["speeds"]["v1_kt"],
                "vr_kt": r["speeds"]["vr_kt"],
                "v2_kt": r["speeds"]["v2_kt"],
                "mtow": r.get("mtow"),
            }
            for r in results
        ]
        return chosen


# ---------------------------------------------------------------------------
# B738 takeoff engine (port of komed3/top-737-800, MIT)
# ---------------------------------------------------------------------------

# [pressure-altitude preference 0..4][flap 0..2 (1/5/15)][weight bucket 6..12 (30-65t, 5t steps)]
_B738_V1 = [
    [
        [None, None, None, None, None, None, 108, 118, 128, 138, 146, 154, 161],
        [None, None, None, None, None, None, 104, 114, 122, 131, 138, 146, 154],
        [None, None, None, None, None, None, 99, 108, 116, 124, 132, 140, None],
    ],
    [
        [None, None, None, None, None, None, 110, 120, 130, 140, 147, 155, 162],
        [None, None, None, None, None, None, 106, 115, 124, 132, 141, 148, 155],
        [None, None, None, None, None, None, 100, 109, 117, 125, 134, 141, None],
    ],
    [
        [None, None, None, None, None, None, 111, 222, 132, 141, 149, 156, None],
        [None, None, None, None, None, None, 107, 116, 125, 134, 141, 148, None],
        [None, None, None, None, None, None, 101, 110, 118, 127, 135, 142, None],
    ],
    [
        [None, None, None, None, None, None, 113, 123, 133, 143, None, None, None],
        [None, None, None, None, None, None, 108, 117, 126, 133, 142, None, None],
        [None, None, None, None, None, None, 103, 111, 120, 128, 136, None, None],
    ],
    [
        [None, None, None, None, None, None, 115, 125, None, None, None, None, None],
        [None, None, None, None, None, None, 109, 119, 128, None, None, None, None],
        [None, None, None, None, None, None, 104, 113, 122, None, None, None, None],
    ],
]

_B738_VR = [
    [
        [None, None, None, None, None, None, 108, 118, 128, 138, 147, 155, 163],
        [None, None, None, None, None, None, 104, 114, 122, 131, 139, 147, 155],
        [None, None, None, None, None, None, 99, 108, 116, 124, 132, 140, None],
    ],
    [
        [None, None, None, None, None, None, 110, 120, 130, 140, 148, 156, 164],
        [None, None, None, None, None, None, 106, 115, 124, 132, 141, 149, 156],
        [None, None, None, None, None, None, 100, 109, 117, 125, 134, 141, None],
    ],
    [
        [None, None, None, None, None, None, 111, 122, 132, 141, 150, 157, None],
        [None, None, None, None, None, None, 107, 116, 125, 134, 142, 150, None],
        [None, None, None, None, None, None, 101, 110, 118, 127, 135, 142, None],
    ],
    [
        [None, None, None, None, None, None, 113, 123, 133, 143, None, None, None],
        [None, None, None, None, None, None, 108, 117, 126, 135, 143, None, None],
        [None, None, None, None, None, None, 103, 111, 120, 128, 136, None, None],
    ],
    [
        [None, None, None, None, None, None, 115, 125, None, None, None, None, None],
        [None, None, None, None, None, None, 109, 119, 128, None, None, None, None],
        [None, None, None, None, None, None, 104, 113, 122, None, None, None, None],
    ],
]

_B738_V2 = [
    [
        [None, None, None, None, None, None, 122, 130, 138, 147, 154, 161, 167],
        [None, None, None, None, None, None, 118, 125, 132, 139, 146, 153, 159],
        [None, None, None, None, None, None, 112, 119, 126, 132, 139, 145, None],
    ],
    [
        [None, None, None, None, None, None, 122, 130, 138, 147, 154, 161, 167],
        [None, None, None, None, None, None, 118, 125, 132, 139, 146, 153, 160],
        [None, None, None, None, None, None, 112, 119, 125, 132, 139, 145, None],
    ],
    [
        [None, None, None, None, None, None, 121, 130, 138, 147, 154, 161, None],
        [None, None, None, None, None, None, 117, 124, 131, 139, 146, 153, None],
        [None, None, None, None, None, None, 111, 118, 125, 132, 139, 145, None],
    ],
    [
        [None, None, None, None, None, None, 121, 130, 138, 147, None, None, None],
        [None, None, None, None, None, None, 117, 124, 131, 139, 146, None, None],
        [None, None, None, None, None, None, 111, 118, 125, 132, 139, None, None],
    ],
    [
        [None, None, None, None, None, None, 121, 130, None, None, None, None, None],
        [None, None, None, None, None, None, 116, 124, 131, None, None, None, None],
        [None, None, None, None, None, None, 110, 117, 125, None, None, None, None],
    ],
]

# wet-runway V1 reduction [flap][runway length bucket 0..7]
_B738_V1_REDUC = [
    [0, 0, 14, 10, 8, 6, 5, 4],
    [0, 0, 14, 10, 8, 6, 5, 4],
    [0, 0, 12, 8, 6, 4, 3, 2],
]

# [pressure altitude (ft) index][temperature index 0..6] -> preference 0..4 or -1
_B738_PREF = [
    [0, 0, 0, 1, 2, 3, 4],
    [0, 0, 0, 1, 2, 3, 4],
    [0, 0, 0, 1, 2, 3, 4],
    [0, 0, 0, 1, 2, 4, -1],
    [0, 0, 1, 1, 3, 4, -1],
    [1, 1, 1, 2, 3, 4, -1],
    [1, 1, 1, 2, 3, 4, -1],
    [1, 1, 2, 3, 4, -1, -1],
    [2, 2, 2, 3, 4, -1, -1],
    [2, 2, 3, 3, 4, -1, -1],
]


class B738Takeoff:
    """komed3 B737-800 takeoff speed calculator (MIT).

    The komed3 tables cover 41.4-65 t TOW.  Above 65 t (the B738's real
    MTOW is ~79 t) the tables are linearly extrapolated from the top two
    weight buckets so the full dispatch envelope stays usable; the output is
    still clearly labelled as a sim-grade table.
    """

    empty_weight_kg = 41_413.0
    max_weight_kg = 65_000.0
    min_runway_ft = 6_900.0
    flap_labels = ["1", "5", "15"]

    def _speeds_at(self, pref: int, flap_index: int, weight_bucket: int) -> tuple[int, int, int] | None:
        v1 = _B738_V1[pref][flap_index][weight_bucket]
        vr = _B738_VR[pref][flap_index][weight_bucket]
        v2 = _B738_V2[pref][flap_index][weight_bucket]
        if v1 is None or vr is None or v2 is None:
            return None
        return int(v1), int(vr), int(v2)

    def calculate(
        self,
        *,
        tow: float,
        flap_index: int,
        tora_m: float,
        elevation_ft: float,
        qnh_hpa: float,
        oat_c: float,
        wet: bool = False,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"conf": flap_index, "flap": self.flap_labels[flap_index]}
        if tow < self.empty_weight_kg:
            result["error"] = "BELOW OPERATING EMPTY WEIGHT"
            result["speeds"] = {"v1_kt": None, "vr_kt": None, "v2_kt": None}
            return result
        runway_ft = tora_m * 3.280839895
        if runway_ft < self.min_runway_ft:
            result["error"] = "RUNWAY SHORTER THAN 6900 FT"
            result["speeds"] = {"v1_kt": None, "vr_kt": None, "v2_kt": None}
            return result

        pressure_alt_idx = int(min(9, max(0, math.ceil((elevation_ft + 1000 * (29.92 - qnh_hpa * 0.0295299831)) / 1000))))
        temp_idx = int(min(7, max(1, math.floor(oat_c / 10)))) - 1
        pref = _B738_PREF[pressure_alt_idx][temp_idx]
        if pref == -1:
            result["error"] = "FLIGHT NOT POSSIBLE UNDER THESE CONDITIONS"
            result["speeds"] = {"v1_kt": None, "vr_kt": None, "v2_kt": None}
            return result

        weight_bucket = int(math.ceil(tow / 5000))
        extrapolated = False
        speeds = None
        if weight_bucket <= 12:
            speeds = self._speeds_at(pref, flap_index, weight_bucket)
        if speeds is None and weight_bucket > 12:
            # Above the top table bucket (65 t): extrapolate from the top two
            # valid buckets using the 5 t per-bucket speed trend.
            top = self._speeds_at(pref, flap_index, 12)
            second = self._speeds_at(pref, flap_index, 11)
            if top is not None and second is not None:
                v1 = min(top[0] + int(round((tow - 65_000) / 5_000 * (top[0] - second[0]))),
                          top[1] + int(round((tow - 65_000) / 5_000 * (top[1] - second[1]))))
                vr = top[1] + int(round((tow - 65_000) / 5_000 * (top[1] - second[1])))
                v2 = max(top[2] + int(round((tow - 65_000) / 5_000 * (top[2] - second[2]))), vr)
                speeds = (v1, vr, v2)
                extrapolated = True
        if speeds is None:
            result["error"] = "FLIGHT NOT POSSIBLE UNDER THESE CONDITIONS"
            result["speeds"] = {"v1_kt": None, "vr_kt": None, "v2_kt": None}
            return result

        v1, vr, v2 = speeds
        if wet:
            runway_bucket = int(min(7, max(0, math.floor(runway_ft / 2000))))
            v1 -= _B738_V1_REDUC[flap_index][runway_bucket]

        result["speeds"] = {"v1_kt": v1, "vr_kt": vr, "v2_kt": v2}
        result["preference"] = pref
        result["pressure_altitude_ft"] = elevation_ft + 1000 * (29.92 - qnh_hpa * 0.0295299831)
        result["extrapolated_weight"] = extrapolated
        return result

    def calculate_all_flaps(self, **kwargs: Any) -> dict[str, Any]:
        results = [self.calculate(flap_index=i, **kwargs) for i in range(3)]
        ok = [r for r in results if not r.get("error")]
        if not ok:
            chosen = dict(results[0])
            chosen["configs"] = [{"flap": r["flap"], "error": r.get("error")} for r in results]
            return chosen
        ok.sort(key=lambda r: r["speeds"]["v1_kt"])
        chosen = dict(ok[0])
        chosen["configs"] = [
            {"flap": r["flap"], "error": r.get("error"), **r["speeds"]} for r in results
        ]
        return chosen


# ---------------------------------------------------------------------------
# A350 takeoff engine (port of the A350 EFB TOPerfHelper)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _a350_tables() -> dict[str, Any]:
    try:
        return json.loads(_A350_DATA.read_text(encoding="utf-8"))
    except Exception:
        return {}


class A350Takeoff:
    """A350 EFB takeoff calculator (TOPerfHelper).

    The bundle ships the full FCOM-derived takeoff database: for each
    runway length (2000-4100 m), pressure altitude (0-8500 ft), OAT
    (-30..79 C), CONF (1+F/2/3) and wind bucket the WEIGHT column is the
    runway-limited max TOW and V1/VR/V2 are the speeds at that limit.
    FLEX temp is the highest-OAT row whose limit (plus the wind / bleeds
    modifier) still covers the actual TOW; V-speeds come from that row.
    Both the A350-900 (XWB-84, -6 C flex correction) and A350-1000
    (XWB-97) share the same tables, exactly like the aircraft's EFB.

    Row layout: [runway, temp_c, config, wind_kt, weight_kg, v1_kt,
    vr_kt, v2_kt, code].  WET tables carry two rows per combination
    (wet limit first, dry reference second); the first wins, matching the
    EFB's dedup, so only the wet limit is ever used.
    """

    runway_lengths = [2000, 2300, 2600, 2900, 3200, 3500, 3800, 4100]
    pressure_alt_values = [0, 2000, 4000, 6000, 8000, 8500]
    headwind_values = [5, 10, 20]
    tailwind_values = [-5, -10, -15]
    isa_min_flex = 37.0
    isa_max_flex = 72.0

    # Weight modifier per kt of wind component (kg/kt), the anti-ice /
    # packs adjustments and the flex-temperature penalties, straight from
    # TOPerfHelper.  (The tailwind term looks generous because the tailwind
    # buckets themselves are extremely conservative -- the EFB compensates
    # the discretization the same way.)
    headwind_modifier_per_kt = 400.0
    tailwind_modifier_per_kt = 1240.0
    anti_ice_engine_modifier = 300.0
    anti_ice_wing_modifier = 500.0
    packs_off_modifier = 3700.0
    anti_ice_engine_flex = 3.0
    anti_ice_wing_flex = 5.0
    packs_flex = 2.0
    a350_900_flex = 6.0

    def __init__(self, variant: str = "A350-1000") -> None:
        self.variant = str(variant or "A350-1000")
        self.tables = _a350_tables().get("tables", {})

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _closest(values: list[float], target: float) -> float:
        """Nearest value; ties resolve to the earlier element (EFB reduce)."""
        best = values[0]
        best_d = abs(best - target)
        for v in values[1:]:
            d = abs(v - target)
            if d < best_d:
                best = v
                best_d = d
        return best

    def _table_key(self, wet: bool, pa: float, tailwind: bool) -> str | None:
        hw = "Tailwind" if tailwind else "Headwind"
        lw = "tailwind" if tailwind else "headwind"
        pa_i = int(pa)
        key = f"{'WET' if wet else 'DRY'}_PRESS ALT {pa_i}ft_{hw}_A350 {lw} PA{pa_i}ft"
        if wet:
            key += " Wet" if tailwind else " WET"
        return key if key in self.tables else None

    def _rows_for(self, key: str, runway_index: int, conf: int, wind_bucket: int) -> list[list[Any]]:
        """Deduped rows for the selection (first row per runway/temp/wind/
        conf wins -- the EFB's cache dedup), filtered to the runway index,
        config and wind bucket, excluding the no-takeoff (weight 0) rows."""
        dedup: dict[tuple[float, float, float, int], list[Any]] = {}
        for row in self.tables.get(key, []):
            dedup.setdefault((row[0], row[1], row[3], row[2]), row)
        out = []
        for r in dedup.values():
            if r[0] == runway_index and r[2] == conf and r[3] == wind_bucket and r[4] != 0:
                out.append(r)
        # rows are ordered by temp ascending per (runway, conf, wind), so the
        # last qualifying row is the highest OAT = the FLEX temperature.
        out.sort(key=lambda r: r[1])
        return out

    # -- main entry ---------------------------------------------------------

    def calculate(
        self,
        *,
        tow: float,
        conf: int,
        tora: float,
        slope: float = 0.0,
        wind: float = 0.0,
        elevation: float = 0.0,
        qnh: float = 1013.25,
        oat: float = 15.0,
        anti_ice_engine: bool = False,
        anti_ice_wing: bool = False,
        packs: bool = False,
        wet: bool = False,
        cg: float | None = None,
        lineup_angle: int = 0,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "tow": tow,
            "conf": conf,
            "tora": tora,
            "slope": slope,
            "wind": wind,
            "elevation": elevation,
            "qnh": qnh,
            "oat": oat,
            "anti_ice_engine": bool(anti_ice_engine),
            "anti_ice_wing": bool(anti_ice_wing),
            "packs": bool(packs),
            "wet": bool(wet),
            "cg": cg,
        }
        result["error"] = None

        # Pressure altitude from QNH + elevation, snapped to the table grid
        # (EFB CalculatePressureAltitudeForRef / FindClosest).
        qnh_inhg = qnh * 0.0295299831
        pa_ft = math.floor((29.92 - qnh_inhg) * 1000.0 + elevation)
        pa = self._closest(self.pressure_alt_values, pa_ft)

        # Wind component (positive = headwind in this engine's convention;
        # the EFB computes it from wind dir vs runway heading).
        component = abs(wind)
        tailwind = wind < 0
        if math.isnan(component) or component < 3:
            tailwind = False
            component = 0.0
        if tailwind:
            wind_bucket = int(self._closest(self.tailwind_values, -component))
        else:
            wind_bucket = int(self._closest(self.headwind_values, component))

        # Weight modifier: wind allowance + bleeds (EFB BASE MODIFIER).
        modifier = 0.0
        if tailwind:
            modifier += self.tailwind_modifier_per_kt * component
        else:
            modifier += self.headwind_modifier_per_kt * component
        if anti_ice_engine and not anti_ice_wing:
            modifier -= self.anti_ice_engine_modifier
        if anti_ice_wing:
            modifier -= self.anti_ice_wing_modifier
        if not packs:
            modifier += self.packs_off_modifier

        # Round the runway length DOWN to the largest table length <= TORA
        # (the RUNWAY column in the tables is the 1-based index into the
        # runway-length array -- EFB RoundToRunwayLength / IndexToRunway).
        runway_index = None
        for i, length in enumerate(self.runway_lengths):
            if tora >= length:
                runway_index = i + 1
        if runway_index is None:
            result["error"] = "DEPARTURE RUNWAY TOO SHORT [RUNWAY LIMITED]"
            result["speeds"] = {"v1_kt": None, "vr_kt": None, "v2_kt": None}
            result["flex"] = None
            result["mtow"] = None
            return result

        key = self._table_key(wet, pa, tailwind)
        rows = self._rows_for(key, runway_index, conf, wind_bucket) if key else []
        qualifying = [r for r in rows if r[4] + modifier >= tow]
        if not qualifying:
            result["error"] = "UNABLE TO FIND SAFE PERFORMANCE DATA [PERF LIMITED]"
            result["speeds"] = {"v1_kt": None, "vr_kt": None, "v2_kt": None}
            result["flex"] = None
            result["mtow"] = None
            return result

        # Highest qualifying OAT row = the FLEX (assumed) temperature; its
        # V1/VR/V2 are the speeds at that takeoff condition.
        row = qualifying[-1]
        flex_temp = float(row[1])
        v1 = int(row[5])
        vr = int(row[6])
        v2 = int(row[7])
        codes = str(row[8] or "")

        # FLEX corrections (anti-ice / packs / A350-900).
        if anti_ice_engine and not anti_ice_wing:
            flex_temp -= self.anti_ice_engine_flex
        if anti_ice_wing:
            flex_temp -= self.anti_ice_wing_flex
        if packs:
            flex_temp -= self.packs_flex
        if self.variant == "A350-900":
            flex_temp -= self.a350_900_flex

        toga = flex_temp < self.isa_min_flex or flex_temp < oat
        if not toga and flex_temp > self.isa_max_flex:
            flex_temp = self.isa_max_flex

        mtow_perf = max(r[4] for r in qualifying) + modifier
        if toga and mtow_perf < tow:
            result["error"] = "UNABLE TO FIND SAFE PERFORMANCE DATA [MTOW LESS THAN A/C WEIGHT]"
            result["speeds"] = {"v1_kt": None, "vr_kt": None, "v2_kt": None}
            result["flex"] = None
            result["mtow"] = None
            return result

        result["speeds"] = {"v1_kt": v1, "vr_kt": vr, "v2_kt": v2}
        result["flex"] = flex_temp if not toga else None
        result["toga"] = toga
        result["mtow"] = mtow_perf
        result["codes"] = codes
        result["pressure_altitude_ft"] = pa
        result["wind_bucket"] = wind_bucket
        result["modifier"] = modifier
        return result

    def calculate_opt_config(self, **kwargs: Any) -> dict[str, Any]:
        """Run all three takeoff configs and pick the best (highest flex,
        then lowest V1) -- mirrors the A320neo optimum-config pass."""
        results = [self.calculate(conf=c, **kwargs) for c in (1, 2, 3)]
        ok = [r for r in results if not r.get("error")]
        if not ok:
            best = max(results, key=lambda r: r["conf"])
            best["configs"] = [{"conf": r["conf"], "error": r.get("error")} for r in results]
            return best
        ok.sort(key=lambda r: (r.get("flex") if r.get("flex") is not None else -1, r["speeds"]["v1_kt"] or 0), reverse=True)
        chosen = dict(ok[0])
        chosen["configs"] = [
            {
                "conf": r["conf"],
                "error": r.get("error"),
                "flex": r.get("flex"),
                "v1_kt": r["speeds"]["v1_kt"],
                "vr_kt": r["speeds"]["vr_kt"],
                "v2_kt": r["speeds"]["v2_kt"],
                "mtow": r.get("mtow"),
            }
            for r in results
        ]
        return chosen


# ---------------------------------------------------------------------------
# Generic PERF2601 fallback (all other aircraft) -- vr_isa anchored
# ---------------------------------------------------------------------------


def generic_takeoff_speeds(profile: dict[str, Any], tow_kg: float, isa_delta: float, runway_margin_m: float) -> dict[str, Any]:
    """V1/VR/V2 anchored to the profile's vr_isa_kt reference rotation speed."""
    weights = profile.get("weights", {})
    max_tow = _num(weights.get("max_tow_kg"), 0)
    vr_isa = _num(profile.get("vr_isa_kt"), 140)
    vr = vr_isa + (tow_kg - max_tow * 0.82) / 1000.0 * 0.16 + max(isa_delta, 0) * 0.03
    v1 = vr - (6 if runway_margin_m < 700 else 4)
    v2 = vr + 5
    return {"v1_kt": round(v1), "vr_kt": round(vr), "v2_kt": round(v2)}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(str(value).replace(",", ""))
    except Exception:
        return default


def vref_for_profile(profile: dict[str, Any], weight_kg: float) -> float:
    weights = profile.get("weights", {})
    max_lw = _num(weights.get("max_lw_kg"), 0)
    vr_isa = _num(profile.get("vr_isa_kt"), 140)
    return max(95, vr_isa - 22 + (weight_kg - max_lw * 0.82) / 1000.0 * 0.12)
