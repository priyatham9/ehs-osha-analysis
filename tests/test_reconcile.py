"""Tests for the panel reconciliation against ehs-benchmarks."""

from __future__ import annotations

import unittest

import _context  # noqa: F401
import numpy as np
import pandas as pd

from ehs_osha.load import derive_fields
from ehs_osha.quality import PlausibilityConfig
from ehs_osha.reconcile import OLD_PUBLISHED, reconcile_panels


def _frame() -> pd.DataFrame:
    # Six plausible filings per year plus one absurd one in 2023 that holds
    # almost all the hours and no cases, so screening moves the aggregate.
    rows = []
    for year in (2016, 2023, 2024):
        for i in range(6):
            rows.append(dict(year_filing_for=year, annual_average_employees=50,
                             total_hours_worked=100_000, total_deaths=0,
                             total_dafw_cases=1, total_djtr_cases=0,
                             total_other_cases=1, naics_code=311111))
    rows.append(dict(year_filing_for=2023, annual_average_employees=5,
                     total_hours_worked=5_000_000, total_deaths=0,
                     total_dafw_cases=0, total_djtr_cases=0,
                     total_other_cases=0, naics_code=311111))
    # One filing at 110 hours per employee: in under the 100 floor, out under 120.
    rows.append(dict(year_filing_for=2024, annual_average_employees=100,
                     total_hours_worked=11_000, total_deaths=0,
                     total_dafw_cases=0, total_djtr_cases=0,
                     total_other_cases=0, naics_code=311111))
    return derive_fields(pd.DataFrame(rows))


class ReconcileTests(unittest.TestCase):
    def test_rows_and_columns(self) -> None:
        t = reconcile_panels(_frame())
        self.assertEqual(list(t["panel"][:2]), ["old", "new"])
        self.assertEqual((t["panel"] == "old_years_sensitivity").sum(), 4)
        for key in OLD_PUBLISHED:
            self.assertIn(f"published_{key}", t.columns)
            self.assertIn(f"rel_gap_{key}", t.columns)

    def test_old_panel_restricts_years_and_screen(self) -> None:
        t = reconcile_panels(_frame()).set_index("label")
        self.assertEqual(t.loc["old", "years_present"], "2023,2024")
        self.assertEqual(t.loc["old", "n_filings"], 14)
        self.assertEqual(t.loc["new", "n_filings"], 20)
        self.assertEqual(t.loc["old", "min_hours_per_employee"], 100.0)
        self.assertEqual(t.loc["new", "max_hours_per_employee"], 4500.0)
        # The 110 h/employee filing is flagged only when the floor is 120.
        self.assertEqual(t.loc["old", "n_implausible"], 1)
        self.assertEqual(t.loc["old_years_120-4000", "n_implausible"], 2)

    def test_ratio_matches_hand_computation(self) -> None:
        t = reconcile_panels(_frame()).set_index("label")
        cases, hours_good = 24.0, 12 * 100_000 + 11_000
        hours_all = hours_good + 5_000_000
        self.assertAlmostEqual(t.loc["old", "aggregate_trir_unscreened"], 200000 * cases / hours_all, places=6)
        self.assertAlmostEqual(t.loc["old", "aggregate_trir_screened"], 200000 * cases / hours_good, places=6)
        gap = t.loc["old", "rel_gap_ratio_screened_to_unscreened"]
        self.assertTrue(np.isfinite(gap))
        self.assertIsInstance(bool(t.loc["old", "ratio_reproduced_within_tolerance"]), bool)

    def test_custom_screen_object(self) -> None:
        t = reconcile_panels(_frame(), old_screen=PlausibilityConfig(200.0, 3000.0), lows=(200.0,), highs=(3000.0,))
        self.assertEqual(len(t), 3)


if __name__ == "__main__":
    unittest.main()
