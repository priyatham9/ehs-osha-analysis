"""Hand-computed fixtures for the DART, LTIR and severity rates."""

from __future__ import annotations

import unittest

import _context  # noqa: F401
import pandas as pd

from ehs_osha.load import derive_fields
from ehs_osha.metrics import compute_rates, rates_by_year
from ehs_osha.quality import PlausibilityConfig, apply_screen


def make_frame(rows):
    default = {
        "annual_average_employees": 100.0,
        "total_hours_worked": 200000.0,
        "total_deaths": 0.0,
        "total_dafw_cases": 0.0,
        "total_djtr_cases": 0.0,
        "total_other_cases": 0.0,
        "total_dafw_days": 0.0,
        "total_djtr_days": 0.0,
        "no_injuries_illnesses": 2.0,
        "naics_code": 325199.0,
        "year_filing_for": 2024.0,
        "establishment_id": 1.0,
    }
    df = derive_fields(pd.DataFrame([{**default, **r} for r in rows]))
    return apply_screen(df, PlausibilityConfig())


class TestHandComputed(unittest.TestCase):
    def test_single_filing(self) -> None:
        # 400,000 hours: 1 death, 2 days-away, 3 restricted, 4 other; 30 + 10 days.
        f = make_frame([{
            "annual_average_employees": 200.0, "total_hours_worked": 400000.0,
            "total_deaths": 1.0, "total_dafw_cases": 2.0, "total_djtr_cases": 3.0,
            "total_other_cases": 4.0, "total_dafw_days": 30.0, "total_djtr_days": 10.0,
        }])
        r = compute_rates(f)
        self.assertAlmostEqual(r["trir_screened"], 200000 * 10 / 400000)   # 5.0
        self.assertAlmostEqual(r["dart_screened"], 200000 * 5 / 400000)    # 2.5
        self.assertAlmostEqual(r["ltir_screened"], 200000 * 2 / 400000)    # 1.0
        self.assertAlmostEqual(r["severity_screened"], 200000 * 40 / 400000)  # 20.0
        self.assertEqual(r["n_screened_in"], 1)

    def test_ratio_of_sums_not_mean_of_rates(self) -> None:
        # Two filings: 100k hours with 1 DART case, 300k hours with 0 cases.
        # Mean of establishment DART rates would be 1.0; ratio of sums is 0.5.
        f = make_frame([
            {"annual_average_employees": 50.0, "total_hours_worked": 100000.0, "total_dafw_cases": 1.0},
            {"annual_average_employees": 150.0, "total_hours_worked": 300000.0},
        ])
        r = compute_rates(f)
        self.assertAlmostEqual(r["dart_screened"], 0.5)
        self.assertAlmostEqual(r["ltir_screened"], 0.5)

    def test_screen_removes_implausible_filing(self) -> None:
        # The second filing claims 1e9 hours for 10 employees and is screened out.
        f = make_frame([
            {"total_dafw_cases": 2.0, "total_dafw_days": 20.0},
            {"annual_average_employees": 10.0, "total_hours_worked": 1e9, "total_djtr_cases": 1.0},
        ])
        r = compute_rates(f)
        self.assertEqual(r["n_screened_in"], 1)
        self.assertAlmostEqual(r["ltir_screened"], 2.0)
        self.assertAlmostEqual(r["severity_screened"], 20.0)
        self.assertLess(r["dart_unscreened"], 0.001)
        self.assertAlmostEqual(r["dart_screened"], 2.0)

    def test_by_year_splits(self) -> None:
        f = make_frame([
            {"year_filing_for": 2023.0, "total_dafw_cases": 1.0},
            {"year_filing_for": 2024.0, "total_djtr_cases": 4.0},
        ])
        t = rates_by_year(f).set_index("label")
        self.assertAlmostEqual(t.loc["2023", "ltir_screened"], 1.0)
        self.assertAlmostEqual(t.loc["2024", "ltir_screened"], 0.0)
        self.assertAlmostEqual(t.loc["2024", "dart_screened"], 4.0)


if __name__ == "__main__":
    unittest.main()
