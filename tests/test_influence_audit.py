"""Analytical identities and empirical decision-influence checks."""
import json
import unittest

import _context  # noqa: F401
from ehs_osha.influence_audit import deletion_accounting, scaled_pool_rate


class TestInfluenceAccounting(unittest.TestCase):
    def test_shapley_effects_add_and_have_expected_signs(self):
        r = deletion_accounting(100, 1000000, 1, 400000)
        self.assertAlmostEqual(r["numerator_effect"]+r["denominator_effect"], r["joint_change"])
        self.assertLess(r["numerator_effect"], 0)
        self.assertGreater(r["denominator_effect"], 0)
        self.assertAlmostEqual(r["joint_rate"], 200000*99/600000)

    def test_proportional_cases_and_hours_have_zero_joint_influence(self):
        r = deletion_accounting(100, 1000000, 20, 200000)
        self.assertAlmostEqual(r["joint_change"], 0)
        self.assertAlmostEqual(r["numerator_effect"], -r["denominator_effect"])

    def test_zero_case_removal_has_only_denominator_effect(self):
        r = deletion_accounting(100, 1000000, 0, 200000)
        self.assertEqual(r["numerator_effect"], 0)
        self.assertAlmostEqual(r["denominator_effect"], r["joint_change"])

    def test_relative_influence_identity(self):
        r = deletion_accounting(100, 1000000, 1, 400000)
        self.assertAlmostEqual(r["joint_change"]/r["baseline_rate"], (.4-.01)/(1-.4))

    def test_empty_denominator_and_invalid_deletions_fail(self):
        for args in ((100, 1000, 1, 1000), (100, 1000, 101, 10), (100, 1000, -1, 10)):
            with self.assertRaises(ValueError):
                deletion_accounting(*args)

    def test_joint_scaling_pool_formula_matches_direct_reconstruction(self):
        for factor in (1, 10, 1000, 1000000):
            expected = 200000*100/(800000+factor*200000)
            self.assertAlmostEqual(scaled_pool_rate(100, 1000000, 200000, factor), expected)
        self.assertLess(scaled_pool_rate(100, 1000000, 200000, 1000000), .0001)


class TestEmpiricalInfluenceAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = json.loads((_context.ROOT/"docs"/"decision-audit-data.json").read_text())
        cls.audit = cls.saved["influence_audit"]

    def test_single_filing_proves_minimum_one_deletion(self):
        pair = next(r for r in self.audit["decision_fragility"] if r["year_before"] == 2023)
        self.assertEqual(pair["minimum_deletions_proven"], 1)
        candidates = [r for r in self.audit["review_candidates"] if r["year_before"] == 2023]
        self.assertEqual(len(candidates), pair["n_single_filing_reversals"])
        self.assertTrue(any(r["filing_id"] == 2156121 for r in candidates))
        for r in candidates:
            self.assertGreater(r["original_change_pct"], 0)
            self.assertLess(r["review_change_pct"], 0)

    def test_numerator_denominator_attribution_reconciles(self):
        for r in self.audit["deletion_accounting"]:
            self.assertAlmostEqual(r["numerator_effect"]+r["denominator_effect"], r["joint_change"])
        two = next(r for r in self.audit["deletion_accounting"] if r["scenario"] == "two_largest_2023_hours_filings")
        self.assertEqual(two["joint_rate"], self.saved["headline"]["two_filing_exclusion_2023_rate"])

    def test_all_year_concentration_context_matches_curve(self):
        for r in self.audit["annual"]:
            source = next(v for v in self.saved["exposure_concentration"] if v["year"] == r["year"] and v["top_n"] == 2)
            self.assertAlmostEqual(r["top_two_hours_share"], source["hours_share"])
            self.assertAlmostEqual(r["hours_hhi"]*r["equivalent_equal_exposure_filings"], 1)


if __name__ == "__main__":
    unittest.main()
