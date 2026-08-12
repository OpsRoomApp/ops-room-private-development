"""Validation tests for the performance calculator.

The engine is a port of the FlyByWire A32NX takeoff-performance model
(A320neo), the komed3 B737-800 V-speed tables (B738) and the A350
EFB takeoff tables (A359/A35X), with the PERF2601-derived profiles as the
generic fallback for every other aircraft.

These tests pin the exact-data families against their published reference
numbers and smoke-test the whole profile set so the Performance tab can
never 500 on any aircraft in the dropdown. v0.25.76 (#61) adds the Fenix
EFB exact takeoff engine as Tier-1 for Fenix A320 flights.
"""

from __future__ import annotations

import unittest

from app import performance as perf
from app.perf_engine import A350Takeoff
from app import fenix_perf


class A320NeoReference(unittest.TestCase):
    def test_a20n_speeds_plausible(self) -> None:
        r = perf.calculate({
            "aircraft": "A20N", "mode": "takeoff", "weight_kg": 60000,
            "runway_length_m": 2500, "oat_c": 15, "qnh_hpa": 1013,
            "elevation_ft": 0, "condition": "dry", "runway_heading": 0,
            "wind_dir": 0, "wind_speed": 0, "cg_pct": 24.5,
        })
        s = r["speeds"]
        self.assertEqual(r["status"], "OK")
        # A320-251N at 60 t: V1/VR ~138, V2 ~139 (A32NX reference ballpark).
        self.assertAlmostEqual(s["v1_kt"], 138, delta=4)
        self.assertAlmostEqual(s["vr_kt"], 138, delta=4)
        self.assertAlmostEqual(s["v2_kt"], 139, delta=4)
        self.assertGreaterEqual(s["v2_kt"], s["vr_kt"])
        self.assertGreaterEqual(s["vr_kt"], s["v1_kt"])
        self.assertIn("flex_or_assumed_c", s)  # FLEX supplied for A320neo

    def test_a320_family_scaled(self) -> None:
        r = perf.calculate({
            "aircraft": "A320", "mode": "takeoff", "weight_kg": 60000,
            "runway_length_m": 2500, "oat_c": 15, "qnh_hpa": 1013,
            "elevation_ft": 0, "condition": "dry", "runway_heading": 0,
            "wind_dir": 0, "wind_speed": 0, "cg_pct": 24.5,
        })
        s = r["speeds"]
        self.assertEqual(r["status"], "OK")
        self.assertGreaterEqual(s["v2_kt"], s["vr_kt"])
        self.assertGreaterEqual(s["vr_kt"], s["v1_kt"])


class FenixEfbContract(unittest.TestCase):
    """#61: Fenix EFB takeoff-engine mapping helpers and the perf override."""

    def test_flap_value_mapping(self) -> None:
        self.assertEqual(fenix_perf._flap_value("1+F"), 1)
        self.assertEqual(fenix_perf._flap_value("OPT"), 0)
        self.assertEqual(fenix_perf._flap_value("2"), 2)
        self.assertEqual(fenix_perf._flap_value("CONF 3"), 3)
        self.assertEqual(fenix_perf._flap_value(""), 0)

    def test_anti_ice_and_surface(self) -> None:
        self.assertEqual(fenix_perf._anti_ice_setting(True), "EngineAndWing")
        self.assertEqual(fenix_perf._anti_ice_setting("engine"), "Engine")
        self.assertEqual(fenix_perf._anti_ice_setting(False), "None")
        self.assertEqual(fenix_perf._surface_condition("wet"), "Wet")
        self.assertEqual(fenix_perf._surface_condition("dry"), "Dry")

    def test_aircraft_type_from_title(self) -> None:
        self.assertEqual(fenix_perf.aircraft_type_from_title("Fenix A320 CFM"), fenix_perf.AIRCRAFT_TYPE_CFM)
        self.assertEqual(fenix_perf.aircraft_type_from_title("Fenix A320 IAE"), fenix_perf.AIRCRAFT_TYPE_IAE)
        self.assertIsNone(fenix_perf.aircraft_type_from_title("Boeing 737-800"))
        self.assertIsNone(fenix_perf.aircraft_type_from_title("Fenix A321neo"))

    def test_fenix_override_applies_exact_speeds(self) -> None:
        """When the EFB returns V-speeds, they replace the built-in speeds."""
        payload = {
            "aircraft": "A20N", "mode": "takeoff", "weight_kg": 60000,
            "runway_length_m": 2500, "oat_c": 15, "qnh_hpa": 1013,
            "elevation_ft": 0, "condition": "dry", "runway_heading": 0,
            "wind_dir": 0, "wind_speed": 0, "cg_pct": 24.5,
        }
        fake = {
            "ok": True, "v1_kt": 149.0, "vr_kt": 149.0, "v2_kt": 152.0,
            "flex_c": 62.0, "flap": 2, "green_dot_kt": 221.0,
            "flap_retraction_kt": 150.0, "slat_retraction_kt": 195.0,
            "trim": 0.5, "trim_direction": "DN", "corrected_stop_margin": 536.0,
        }
        original = perf._fenix_takeoff_result
        perf._fenix_takeoff_result = lambda *a, **k: fake
        try:
            r = perf.calculate(payload)
        finally:
            perf._fenix_takeoff_result = original
        s = r["speeds"]
        self.assertEqual(s["v1_kt"], 149.0)
        self.assertEqual(s["vr_kt"], 149.0)
        self.assertEqual(s["v2_kt"], 152.0)
        self.assertEqual(s["flex_or_assumed_c"], 62.0)
        # Trim direction DN -> negative sign (frontend renders 'DN').
        self.assertEqual(s["pitch_trim"], -0.5)
        self.assertIn("Fenix EFB", r["source"])
        self.assertTrue(any("EFB" in w for w in r["warnings"]))

    def test_fenix_override_up_trim_positive(self) -> None:
        fake = {"ok": True, "v1_kt": 145.0, "vr_kt": 146.0, "v2_kt": 149.0,
                "trim": 1.0, "trim_direction": "UP"}
        original = perf._fenix_takeoff_result
        perf._fenix_takeoff_result = lambda *a, **k: fake
        try:
            r = perf.calculate({
                "aircraft": "A320", "mode": "takeoff", "weight_kg": 60000,
                "runway_length_m": 2500, "oat_c": 15, "qnh_hpa": 1013,
                "elevation_ft": 0, "condition": "dry", "runway_heading": 0,
                "wind_dir": 0, "wind_speed": 0, "cg_pct": 24.5,
            })
        finally:
            perf._fenix_takeoff_result = original
        self.assertEqual(r["speeds"]["pitch_trim"], 1.0)


class B738Reference(unittest.TestCase):
    def test_b738_matches_komed3(self) -> None:
        # komed3 table at 50 t / flaps 5 / sea-level 15C: 138/139/146 kt.
        r = perf.calculate({
            "aircraft": "B738", "mode": "takeoff", "weight_kg": 50000,
            "runway_length_m": 2600, "oat_c": 15, "qnh_hpa": 1013,
            "elevation_ft": 0, "condition": "dry", "runway_heading": 0,
            "wind_dir": 0, "wind_speed": 0, "flap": "5", "cg_pct": 22.0,
        })
        s = r["speeds"]
        self.assertEqual(r["status"], "OK")
        self.assertAlmostEqual(s["v1_kt"], 138, delta=2)
        self.assertAlmostEqual(s["vr_kt"], 139, delta=2)
        self.assertAlmostEqual(s["v2_kt"], 146, delta=2)
        # Boeing stab trim from CG % MAC.
        self.assertIsNotNone(s.get("pitch_trim"))

    def test_b738_above_table_extrapolates(self) -> None:
        r = perf.calculate({
            "aircraft": "B738", "mode": "takeoff", "weight_kg": 72000,
            "runway_length_m": 3200, "oat_c": 15, "qnh_hpa": 1013,
            "elevation_ft": 0, "condition": "dry", "runway_heading": 0,
            "wind_dir": 0, "wind_speed": 0, "cg_pct": 24.5,
        })
        s = r["speeds"]
        self.assertEqual(r["status"], "OK")
        self.assertGreaterEqual(s["v2_kt"], s["vr_kt"])
        self.assertGreaterEqual(s["vr_kt"], s["v1_kt"])


class A350Reference(unittest.TestCase):
    """A350 EFB takeoff-table port (TOPerfHelper).

    The reference numbers below were computed by walking the EFB algorithm
    over the raw bundle (see the extraction notes in perf_engine.py): the
    row selection takes the highest-OAT row whose runway-limited TOW plus
    the wind/bleed modifier still covers the TOW, then applies the anti-ice
    / packs / A350-900 flex corrections.
    """

    def test_a350_1000_flex_and_speeds(self) -> None:
        # 200 t, 2000 m runway, CONF 2, 5 kt headwind, 15 C, sea level:
        # flex 50 C, V1/VR/V2 = 134/138/148 at the limit row.
        r = A350Takeoff(variant="A350-1000").calculate(
            tow=200000, conf=2, tora=2000, wind=5, elevation=0,
            qnh=1013.25, oat=15)
        self.assertIsNone(r.get("error"))
        self.assertAlmostEqual(r["flex"], 50, delta=1)
        self.assertEqual(r["speeds"]["v1_kt"], 134)
        self.assertEqual(r["speeds"]["vr_kt"], 138)
        self.assertEqual(r["speeds"]["v2_kt"], 148)
        self.assertFalse(r["toga"])

    def test_a350_900_flex_correction(self) -> None:
        # The -900 applies a -6 C flex correction on the same tables.
        a1000 = A350Takeoff(variant="A350-1000").calculate(
            tow=200000, conf=2, tora=2000, wind=5, elevation=0,
            qnh=1013.25, oat=15)
        a900 = A350Takeoff(variant="A350-900").calculate(
            tow=200000, conf=2, tora=2000, wind=5, elevation=0,
            qnh=1013.25, oat=15)
        self.assertAlmostEqual(a900["flex"], a1000["flex"] - 6, delta=1)
        self.assertEqual(a900["speeds"], a1000["speeds"])

    def test_a350_heavy_forces_toga(self) -> None:
        # 250 t on a 2000 m runway exceeds the flex floor -> TOGA thrust,
        # no FLEX temperature.
        r = A350Takeoff(variant="A350-1000").calculate(
            tow=250000, conf=2, tora=2000, wind=5, elevation=0,
            qnh=1013.25, oat=15)
        self.assertIsNone(r.get("error"))
        self.assertIsNone(r["flex"])
        self.assertTrue(r["toga"])
        self.assertEqual(r["speeds"]["v1_kt"], 139)
        self.assertEqual(r["speeds"]["vr_kt"], 142)
        self.assertEqual(r["speeds"]["v2_kt"], 155)

    def test_a350_wet_lowers_mtow(self) -> None:
        dry = A350Takeoff(variant="A350-1000").calculate(
            tow=230000, conf=3, tora=2300, wind=10, elevation=0,
            qnh=1013.25, oat=20, wet=False)
        wet = A350Takeoff(variant="A350-1000").calculate(
            tow=230000, conf=3, tora=2300, wind=10, elevation=0,
            qnh=1013.25, oat=20, wet=True)
        self.assertIsNotNone(dry.get("mtow"))
        self.assertIsNotNone(wet.get("mtow"))
        self.assertLess(wet["mtow"], dry["mtow"])

    def test_a350_short_runway_refuses(self) -> None:
        r = A350Takeoff(variant="A350-1000").calculate(
            tow=200000, conf=2, tora=1500, wind=5, elevation=0,
            qnh=1013.25, oat=15)
        self.assertIsNotNone(r.get("error"))
        self.assertIsNone(r["speeds"]["v1_kt"])

    def test_a350_dispatch_exact_source(self) -> None:
        for icao in ("A359", "A35X"):
            r = perf.calculate({
                "aircraft": icao, "mode": "takeoff", "weight_kg": 230000,
                "runway_length_m": 3000, "oat_c": 18, "qnh_hpa": 1013,
                "elevation_ft": 400, "condition": "dry", "runway_heading": 90,
                "wind_dir": 70, "wind_speed": 12, "cg_pct": 25.0,
            })
            s = r["speeds"]
            self.assertEqual(r["status"], "OK")
            self.assertIn("A350 FCOM-derived tables", r["source"])
            self.assertIsNotNone(s["v1_kt"])
            self.assertIsNotNone(s["vr_kt"])
            self.assertIsNotNone(s["v2_kt"])
            self.assertGreaterEqual(s["v2_kt"], s["vr_kt"])
            self.assertGreaterEqual(s["vr_kt"], s["v1_kt"])

    def test_a350_data_integrity(self) -> None:
        doc = A350Takeoff(variant="A350-1000").tables
        self.assertEqual(len(doc), 24)
        for key, rows in doc.items():
            self.assertIn(key.split("_")[0], ("DRY", "WET"))
            expected = 1656 if key.startswith("DRY") else 3312
            self.assertEqual(len(rows), expected, key)
            for row in rows:
                self.assertEqual(len(row), 9, key)
                self.assertEqual(row[2] in (1, 2, 3), True, key)
                self.assertGreaterEqual(row[6], row[5], key)  # VR >= V1
                self.assertGreaterEqual(row[7], row[6], key)  # V2 >= VR


class AllProfilesSmoke(unittest.TestCase):
    def test_every_profile_returns_structured_result(self) -> None:
        db = perf.database()
        profiles = db.get("profiles", [])
        self.assertGreaterEqual(len(profiles), 50, "profile set should be loaded")
        for p in profiles:
            icao = str(p.get("icao", "")).upper()
            mtow = (p.get("weights") or {}).get("max_tow_kg") or 80000
            for rw in (1800, 2600, 4000):
                r = perf.calculate({
                    "aircraft": icao, "mode": "takeoff",
                    "weight_kg": mtow * 0.85, "runway_length_m": rw,
                    "oat_c": 15, "qnh_hpa": 1013, "elevation_ft": 0,
                    "condition": "dry", "runway_heading": 0,
                    "wind_dir": 0, "wind_speed": 0, "cg_pct": 24.5,
                })
                self.assertTrue(r.get("ok"), f"{icao} @ {rw} m")
                self.assertIn(r.get("status"), ("OK", "TIGHT", "NO GO"))
                s = r.get("speeds", {})
                self.assertIsNotNone(s.get("v1_kt"), f"{icao} @ {rw} m")
                self.assertIsNotNone(s.get("vr_kt"), f"{icao} @ {rw} m")
                self.assertIsNotNone(s.get("v2_kt"), f"{icao} @ {rw} m")
                self.assertGreaterEqual(s["v2_kt"], s["vr_kt"], f"{icao} @ {rw} m")
                self.assertGreaterEqual(s["vr_kt"], s["v1_kt"], f"{icao} @ {rw} m")

    def test_every_profile_landing(self) -> None:
        db = perf.database()
        for p in db.get("profiles", []):
            icao = str(p.get("icao", "")).upper()
            mlw = (p.get("weights") or {}).get("max_lw_kg") or 60000
            r = perf.calculate({
                "aircraft": icao, "mode": "landing",
                "weight_kg": mlw * 0.9, "runway_length_m": 2500,
                "oat_c": 15, "qnh_hpa": 1013, "elevation_ft": 0,
                "condition": "dry", "runway_heading": 0, "wind_dir": 0,
                "wind_speed": 0,
            })
            self.assertIsNotNone(r.get("speeds", {}).get("vref_kt"), icao)
            self.assertIsNotNone(r.get("speeds", {}).get("vapp_kt"), icao)


class EnrichmentTest(unittest.TestCase):
    def test_airport_enrichment(self) -> None:
        from app.simbrief_client import _enrich_plan_airport_data
        plan = {
            "ok": True,
            "origin": {"icao": "EGLL", "runway": "27L",
                       "metar": "EGLL 101250Z 25010KT 9999 FEW025 18/12 Q1013"},
            "destination": {"icao": "LJMB", "runway": "34",
                            "metar": "LJMB 101250Z 34005KT CAVOK 22/09 Q1015"},
        }
        _enrich_plan_airport_data(plan)
        origin = plan["origin"]
        self.assertEqual(origin["runway_length_m"], 3660)
        self.assertEqual(origin["runway_heading"], 270)
        self.assertEqual(origin["weather"]["qnh_hpa"], 1013)
        self.assertEqual(origin["weather"]["wind_kt"], 10)
        self.assertEqual(plan["destination"]["weather"]["temp_c"], 22.0)


if __name__ == "__main__":
    unittest.main()
