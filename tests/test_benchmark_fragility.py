"""Accounting identities, influence diagnostics and reproducibility of the audit.

Floating reductions can differ by a few ULPs across NumPy/pandas versions, and
CSV artifacts round to 15 significant digits. Reproduction therefore permits
1e-12 relative/absolute error for floating results only, far below reported
precision. Source hashes, structure, row order and discrete values stay exact.
The public JSON must still be byte-identical to its research artifact.
"""
import csv
import io
import json
import math
import tempfile
import unittest
from pathlib import Path

import _context  # noqa: F401
import numpy as np
import pandas as pd

from ehs_osha import benchmark_fragility as audit
from ehs_osha.catalog import all_files
from ehs_osha.quality import apply_screen, PlausibilityConfig


FLOAT_RTOL = 1e-12
FLOAT_ATOL = 1e-12


def assert_reproduces(test, expected, actual, path="result"):
    """Compare JSON-shaped data without relaxing keys, types or list order."""
    if isinstance(expected, dict):
        test.assertIsInstance(actual, dict, path)
        test.assertEqual(set(expected), set(actual), f"{path}: keys")
        for key in expected:
            assert_reproduces(test, expected[key], actual[key], f"{path}.{key}")
    elif isinstance(expected, list):
        test.assertIsInstance(actual, list, path)
        test.assertEqual(len(expected), len(actual), f"{path}: length")
        for index, (left, right) in enumerate(zip(expected, actual)):
            assert_reproduces(test, left, right, f"{path}[{index}]")
    elif isinstance(expected, float):
        test.assertIsInstance(actual, float, path)
        test.assertTrue(math.isfinite(expected) and math.isfinite(actual), path)
        test.assertTrue(
            math.isclose(expected, actual, rel_tol=FLOAT_RTOL, abs_tol=FLOAT_ATOL),
            f"{path}: {actual!r} != {expected!r} within floating tolerance",
        )
    else:
        # In particular, bool/int and int/float substitutions must not pass
        # merely because Python's ordinary equality treats them as equal.
        test.assertIs(type(actual), type(expected), f"{path}: type")
        test.assertEqual(expected, actual, path)


def assert_csv_reproduces(test, saved_text, frame, path="table"):
    """Parse CSV while preserving exact identifiers, booleans and counts."""
    expected = list(csv.reader(io.StringIO(saved_text)))
    actual = list(csv.reader(io.StringIO(frame.to_csv(index=False, float_format="%.15g"))))
    test.assertEqual(expected[0], actual[0], f"{path}: columns")
    test.assertEqual(len(expected), len(actual), f"{path}: row count")
    test.assertEqual(len(actual[0]), len(set(actual[0])), f"{path}: duplicate columns")
    # Outer joins can store integral case counts as float64. They remain
    # discrete quantities; do not grant them a floating tolerance.
    floating = {column for column in frame.columns
                if pd.api.types.is_float_dtype(frame[column].dtype)
                and not column.startswith("cases_reconstructed")}
    for index, (left_row, right_row) in enumerate(zip(expected[1:], actual[1:])):
        test.assertEqual(len(left_row), len(actual[0]), f"{path}[{index}]: saved width")
        test.assertEqual(len(right_row), len(actual[0]), f"{path}[{index}]: generated width")
        for column, left, right in zip(actual[0], left_row, right_row):
            location = f"{path}[{index}].{column}"
            if column not in floating or left == "" or right == "":
                test.assertEqual(left, right, location)
            else:
                assert_reproduces(test, float(left), float(right), location)


class TestReproductionTolerance(unittest.TestCase):
    def test_ulp_noise_is_allowed_but_material_float_changes_are_not(self):
        saved = {"sha256": "source-digest", "rows": [{"year": 2023, "rate": 3.1466293096590285}]}
        noisy = {"sha256": "source-digest", "rows": [{"year": 2023, "rate": float(np.nextafter(saved["rows"][0]["rate"], np.inf))}]}
        assert_reproduces(self, saved, noisy)
        assert_reproduces(self, 0.0, 5e-16)
        noisy["rows"][0]["rate"] += 1e-8
        with self.assertRaises(AssertionError):
            assert_reproduces(self, saved, noisy)
        for changed in (1e-8, float("nan"), float("inf")):
            with self.subTest(changed=changed), self.assertRaises(AssertionError):
                assert_reproduces(self, 0.0, changed)

    def test_structure_fingerprints_order_and_discrete_values_are_exact(self):
        saved = {"sha256": "original", "rows": [{"id": "001", "n": 1000000, "ok": True},
                                                  {"id": "002", "n": 2, "ok": False}]}
        variants = []
        for key, value in (("id", "1"), ("n", 1000001), ("n", 1000000.0), ("ok", 1)):
            changed = json.loads(json.dumps(saved))
            changed["rows"][0][key] = value
            variants.append(changed)
        variants.extend([{**saved, "sha256": "changed"},
                         {**saved, "rows": list(reversed(saved["rows"]))},
                         {**saved, "unexpected": 1}])
        for changed in variants:
            with self.subTest(changed=changed), self.assertRaises(AssertionError):
                assert_reproduces(self, saved, changed)

    def test_csv_accepts_ulp_noise_but_rejects_drift_and_schema_changes(self):
        saved = "naics3,n,cases_reconstructed_before,rate,valid\n001,100,5000,3.14662930965903,True\n002,200,6000,4.5,False\n"
        frame = pd.DataFrame({"naics3": ["001", "002"], "n": [100, 200],
                              "cases_reconstructed_before": [5000.0, 6000.0],
                              "rate": [3.1466293096590285, 4.5], "valid": [True, False]})
        noisy = frame.copy()
        noisy.loc[0, "rate"] += 1e-15
        assert_csv_reproduces(self, saved, noisy)
        variants = [frame.iloc[::-1], frame.iloc[:1], frame.rename(columns={"rate": "different"})]
        for column, value in (("rate", 3.14663), ("naics3", "1"), ("n", 101),
                              ("cases_reconstructed_before", 5000.000000001), ("valid", False)):
            changed = frame.copy()
            changed.loc[0, column] = value
            variants.append(changed)
        for changed in variants:
            with self.subTest(columns=list(changed.columns)), self.assertRaises(AssertionError):
                assert_csv_reproduces(self, saved, changed)


def frame(year, hours, cases, names=("111", "222")):
    return pd.DataFrame({"year_filing_for": year, "naics3": names,
                         "size_band": "100-249", "n": 50, "hours_total": hours,
                         "cases_reconstructed": cases,
                         "aggregate_trir": np.array(cases)*200000/np.array(hours),
                         "publishable": True})


class TestDecompositionIdentities(unittest.TestCase):
    def test_composition_can_reverse_every_cell_direction(self):
        # Both cell rates fall from 1/10 to .5/9; mix moves toward the high cell.
        a = frame(2023, [1800000, 200000], [9, 10])
        b = frame(2024, [400000, 1600000], [1, 72])
        result, _ = audit.decompose_pair(a, b)
        self.assertGreater(result["full_change"], 0)
        self.assertLess(result["within_effect"], 0)
        self.assertEqual(result["declining_cells"], 2)
        self.assertAlmostEqual(result["within_effect"] + result["composition_effect"], result["full_change"])
        self.assertAlmostEqual(result["within_effect"], (result["within_effect_before_weights"] + result["within_effect_after_weights"])/2)

    def test_equal_weights_have_no_composition_effect(self):
        a = frame(2023, [200000, 600000], [4, 15])
        b = frame(2024, [400000, 1200000], [2, 24])
        result, _ = audit.decompose_pair(a, b)
        self.assertAlmostEqual(result["composition_effect"], 0)
        self.assertAlmostEqual(result["full_change"], result["within_effect"])

    def test_unchanged_rates_have_no_within_effect(self):
        a = frame(2023, [200000, 600000], [1, 15])
        b = frame(2024, [400000, 200000], [2, 5])
        result, _ = audit.decompose_pair(a, b)
        self.assertAlmostEqual(result["within_effect"], 0)
        self.assertAlmostEqual(result["full_change"], result["composition_effect"])

    def test_unmatched_support_is_not_assigned_to_within(self):
        a = frame(2023, [200000, 600000], [1, 30])
        b = frame(2024, [200000, 600000], [1, 3], names=("111", "333"))
        result, _ = audit.decompose_pair(a, b)
        self.assertEqual(result["n_cells_matched"], 1)
        self.assertEqual(result["within_effect"], 0)
        self.assertEqual(result["composition_effect"], 0)
        self.assertAlmostEqual(result["support_residual"], result["full_change"])
        self.assertEqual(result["hours_coverage_after"], .25)

    def test_leave_cell_out_matches_direct_removal_including_unmatched(self):
        a = frame(2023, [200000, 600000], [1, 30])
        b = frame(2024, [200000, 600000], [1, 3], names=("111", "333"))
        rows = audit.leave_one_cell_out(a, b)
        for r in rows.itertuples():
            expected = audit.rate(b[b.naics3 != r.naics3])-audit.rate(a[a.naics3 != r.naics3])
            self.assertAlmostEqual(r.change_after_exclusion, expected)

    def test_duplicate_keys_are_rejected(self):
        p = frame(2023, [200000, 600000], [1, 30], names=("111", "111"))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            audit.validate_peers(p)

    def test_inconsistent_reconstructed_counts_are_rejected(self):
        p = frame(2023, [200000, 600000], [1, 30])
        p.loc[0, "aggregate_trir"] = 1.2
        with self.assertRaisesRegex(ValueError, "integer case counts"):
            audit.validate_peers(p)


class TestScreenBlindSpot(unittest.TestCase):
    def test_joint_scaling_preserves_screen_and_changes_rate(self):
        # Constructed mathematical check, not a fabricated empirical filing.
        factors = np.array([1, 1000, 1000000])
        df = pd.DataFrame({"annual_average_employees": 80*factors,
                           "total_hours_worked": 160000*factors,
                           "hours_per_employee": 2000, "recordable_cases": 7})
        for low in (100, 120, 200, 250, 400):
            for high in (3500, 4000, 4500, 5000, 6000):
                self.assertFalse(apply_screen(df, PlausibilityConfig(low, high)).implausible.any())
        rates = 200000*df.recordable_cases/df.total_hours_worked
        np.testing.assert_allclose(rates.to_numpy()*factors, np.repeat(rates.iloc[0], 3))


class TestCommittedAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = audit.ROOT/"outputs"/"research"/"benchmark_fragility"
        cls.saved = json.loads((cls.path/"findings.json").read_text())
        cls.rebuilt, cls.tables = audit.build(audit.ROOT/"outputs"/"tables")

    def test_source_table_fingerprints_and_results_are_reproducible(self):
        for key in ("annual_rates", "decomposition", "provenance", "definitions", "limitations"):
            assert_reproduces(self, self.saved[key], self.rebuilt[key], key)

    def test_all_decompositions_reconcile(self):
        for r in self.saved["decomposition"]:
            self.assertAlmostEqual(r["full_change"], r["within_effect"] + r["composition_effect"] + r["support_residual"], places=10)

    def test_two_row_exclusion_conserves_cases_and_hours(self):
        selected = self.saved["suspect_filings"]
        annual = {r["year"]: r for r in self.saved["annual_rates"]}
        for r in self.saved["exclusion_sensitivity"]:
            self.assertAlmostEqual(r["remaining_hours"] + r["excluded_hours"], annual[r["year"]]["hours"])
            self.assertEqual(r["remaining_cases"] + r["excluded_cases"], annual[r["year"]]["cases"])
            self.assertAlmostEqual(r["rate"], 200000*r["remaining_cases"]/r["remaining_hours"])
        h = self.saved["headline"]
        self.assertEqual(sum(r["hours"] for r in selected), h["two_filings_hours"])
        self.assertEqual(sum(r["cases"] for r in selected), h["two_filings_cases"])
        self.assertGreater(h["reported_2023_2024_change_pct"], 0)
        self.assertLess(h["two_filing_exclusion_2023_2024_change_pct"], 0)
        self.assertLess(h["symmetric_top_two_2023_2024_change_pct"], 0)

    def test_real_selected_rows_pass_every_grid_bound(self):
        for r in self.saved["threshold_survival"]:
            self.assertEqual(r["selected_pass"], 2)
            for filing in self.saved["suspect_filings"]:
                ratio = filing["hours"]/filing["employees"]
                self.assertGreaterEqual(ratio, r["low"])
                self.assertLessEqual(ratio, r["high"])

    def test_trend_reversal_survives_every_original_screen_specification(self):
        for r in self.saved["threshold_trend_sensitivity"]:
            self.assertGreater(r["change_pct"], 0)
            self.assertLess(r["exclusion_change_pct"], 0)
            self.assertAlmostEqual(r["rate_2024"], r["exclusion_rate_2024"])
        default = next(r for r in self.saved["threshold_trend_sensitivity"] if r["low"] == 120 and r["high"] == 4500)
        self.assertEqual(default["rate_2023"], self.saved["headline"]["reported_2023_rate"])
        self.assertEqual(default["exclusion_rate_2023"], self.saved["headline"]["two_filing_exclusion_2023_rate"])

    def test_nine_year_context_and_linkage_are_reported_as_observed(self):
        self.assertEqual([r["year"] for r in self.saved["raw_provenance"]], list(range(2016, 2025)))
        shares = {r["year"]: r["hours_share"] for r in self.saved["exposure_concentration"] if r["top_n"] == 2}
        self.assertGreater(shares[2023], .16)
        self.assertLess(max(v for y, v in shares.items() if y != 2023), .007)
        rows = {r["year"]: r for r in self.saved["linked_filings"] if r["establishment_id"] == 621240}
        self.assertFalse(rows[2021]["passes_default_screen"])
        self.assertTrue(rows[2023]["passes_default_screen"])
        # This tests recorded key continuity, not physical establishment identity.
        self.assertGreater(rows[2021]["hours"], 1e9)
        self.assertGreater(rows[2023]["hours"], 1e9)

    def test_public_json_matches_research_artifact(self):
        self.assertEqual((audit.ROOT/"docs"/"decision-audit-data.json").read_bytes(), (self.path/"findings.json").read_bytes())

    def test_generated_csvs_match_saved_artifacts(self):
        for name, df in self.tables.items():
            assert_csv_reproduces(self, (self.path/f"{name}.csv").read_text(), df, name)


class TestPinnedRawAudit(unittest.TestCase):
    def test_raw_reproduction_when_snapshots_are_available(self):
        data = audit.ROOT/"data"/"raw"
        specs = all_files()
        if not all((data/f.local_name).exists() for f in specs):
            self.skipTest("Pinned 2016-2024 raw files not installed")
        saved = json.loads((audit.ROOT/"outputs"/"research"/"benchmark_fragility"/"findings.json").read_text())
        rebuilt, _ = audit.raw_analysis(data, saved["annual_rates"])
        for key, value in rebuilt.items():
            assert_reproduces(self, saved[key], value, key)

    def test_mismatched_source_fails_before_loading(self):
        spec = next(f for f in all_files() if f.calendar_year == 2022)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/spec.local_name).write_bytes(b"not the pinned snapshot")
            with self.assertRaisesRegex(ValueError, "differs from pinned catalog"):
                audit.raw_analysis(Path(tmp), [], years=(2022,))


if __name__ == "__main__":
    unittest.main()
