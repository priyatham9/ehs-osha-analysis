"""Tests for the plausibility screen.

The central test here is :meth:`TestMechanism.test_one_bad_filing_destroys_the_
aggregate`, which builds a population with a known true rate, adds a single
filing whose hours are inflated by a factor of a million, and checks that the
unscreened aggregate collapses while the screened aggregate recovers the truth.
That is the mechanism the real-data finding rests on, demonstrated on data whose
answer is known by construction.
"""

from __future__ import annotations

import unittest

import _context  # noqa: F401
import numpy as np
import pandas as pd

from ehs_osha.load import derive_fields
from ehs_osha.quality import (
    HOURS_IN_YEAR,
    PlausibilityConfig,
    aggregate_trir,
    apply_screen,
    flag_prevalence,
    hours_concentration,
    sensitivity_grid,
    summarise_by,
    summarise_screen,
)


def make_frame(rows: list[dict]) -> pd.DataFrame:
    """Build a harmonised frame from partial row dicts, filling defaults."""
    default = {
        "annual_average_employees": 100.0,
        "total_hours_worked": 200000.0,
        "total_deaths": 0.0,
        "total_dafw_cases": 0.0,
        "total_djtr_cases": 0.0,
        "total_other_cases": 0.0,
        "no_injuries_illnesses": 2.0,
        "naics_code": 325199.0,
        "year_filing_for": 2024.0,
        "establishment_id": 1.0,
    }
    return derive_fields(pd.DataFrame([{**default, **r} for r in rows]))


class TestConfig(unittest.TestCase):
    """Screen bounds must be validated, not trusted."""

    def test_rejects_inverted_bounds(self) -> None:
        with self.assertRaises(ValueError):
            PlausibilityConfig(min_hours_per_employee=3000, max_hours_per_employee=100)

    def test_rejects_physically_impossible_ceiling(self) -> None:
        with self.assertRaises(ValueError):
            PlausibilityConfig(max_hours_per_employee=HOURS_IN_YEAR + 1)

    def test_rejects_non_positive_floor(self) -> None:
        with self.assertRaises(ValueError):
            PlausibilityConfig(min_hours_per_employee=0)


class TestFlags(unittest.TestCase):
    """Each flag must fire on exactly the condition it names."""

    def test_hours_missing_and_non_positive(self) -> None:
        f = apply_screen(
            make_frame(
                [
                    {"total_hours_worked": np.nan},
                    {"total_hours_worked": 0.0},
                    {"total_hours_worked": -4.0},
                    {"total_hours_worked": 200000.0},
                ]
            )
        )
        self.assertEqual(list(f["flag_hours_missing"]), [True, True, True, False])

    def test_employees_missing(self) -> None:
        f = apply_screen(
            make_frame(
                [
                    {"annual_average_employees": 0.0},
                    {"annual_average_employees": np.nan},
                    {"annual_average_employees": 1.0, "total_hours_worked": 2000.0},
                ]
            )
        )
        self.assertEqual(list(f["flag_employees_missing"]), [True, True, False])

    def test_hours_per_employee_bounds(self) -> None:
        cfg = PlausibilityConfig(min_hours_per_employee=120, max_hours_per_employee=4500)
        f = apply_screen(
            make_frame(
                [
                    {"annual_average_employees": 10.0, "total_hours_worked": 20000.0},
                    {"annual_average_employees": 10.0, "total_hours_worked": 50000.0},
                    {"annual_average_employees": 10.0, "total_hours_worked": 500.0},
                ]
            ),
            cfg,
        )
        self.assertEqual(list(f["flag_hours_per_employee_high"]), [False, True, False])
        self.assertEqual(list(f["flag_hours_per_employee_low"]), [False, False, True])
        self.assertEqual(list(f["implausible"]), [False, True, True])

    def test_negative_case_counts(self) -> None:
        f = apply_screen(make_frame([{"total_dafw_cases": -1.0}, {"total_dafw_cases": 1.0}]))
        self.assertEqual(list(f["flag_negative_counts"]), [True, False])

    def test_no_injury_contradiction_detected_but_excluded_by_default(self) -> None:
        f = apply_screen(
            make_frame(
                [
                    {"no_injuries_illnesses": 2.0, "total_dafw_cases": 3.0},
                    {"no_injuries_illnesses": 1.0, "total_dafw_cases": 0.0},
                    {"no_injuries_illnesses": 1.0, "total_dafw_cases": 3.0},
                ]
            )
        )
        self.assertEqual(list(f["flag_no_injury_contradiction"]), [True, True, False])
        self.assertEqual(list(f["implausible"]), [False, False, False])

    def test_contradiction_can_be_promoted_to_implausible(self) -> None:
        cfg = PlausibilityConfig(treat_contradiction_as_implausible=True)
        f = apply_screen(
            make_frame([{"no_injuries_illnesses": 2.0, "total_dafw_cases": 3.0}]), cfg
        )
        self.assertTrue(bool(f["implausible"].iloc[0]))

    def test_flags_are_not_double_counted_for_missing_hours(self) -> None:
        f = apply_screen(make_frame([{"total_hours_worked": np.nan}]))
        self.assertTrue(bool(f["flag_hours_missing"].iloc[0]))
        self.assertFalse(bool(f["flag_hours_per_employee_high"].iloc[0]))
        self.assertFalse(bool(f["flag_hours_per_employee_low"].iloc[0]))


class TestMechanism(unittest.TestCase):
    """The denominator-corruption mechanism, on data with a known answer."""

    def test_aggregate_trir_matches_hand_calculation(self) -> None:
        cases = pd.Series([2.0, 4.0])
        hours = pd.Series([200000.0, 200000.0])
        self.assertAlmostEqual(aggregate_trir(cases, hours), 3.0)

    def test_aggregate_trir_nan_on_zero_hours(self) -> None:
        self.assertTrue(
            np.isnan(aggregate_trir(pd.Series([1.0]), pd.Series([0.0])))
        )

    def test_one_bad_filing_destroys_the_aggregate(self) -> None:
        # 1,000 honest establishments: 200,000 h and 4 recordables each, so the
        # true aggregate TRIR is exactly 4.0.
        rows = [
            {
                "establishment_id": float(i),
                "annual_average_employees": 100.0,
                "total_hours_worked": 200000.0,
                "total_dafw_cases": 4.0,
            }
            for i in range(1000)
        ]
        clean = make_frame(rows)
        self.assertAlmostEqual(
            aggregate_trir(clean["recordable_cases"], clean["total_hours_worked"]), 4.0
        )

        # One filing types six extra zeros on hours. Cases are unaffected.
        rows.append(
            {
                "establishment_id": 9999.0,
                "annual_average_employees": 100.0,
                "total_hours_worked": 200000.0 * 1_000_000,
                "total_dafw_cases": 4.0,
            }
        )
        dirty = make_frame(rows)
        naive = aggregate_trir(dirty["recordable_cases"], dirty["total_hours_worked"])
        self.assertLess(naive, 0.01)

        screened = apply_screen(dirty)
        summary = summarise_screen(screened)
        self.assertEqual(summary.n_implausible, 1)
        self.assertAlmostEqual(summary.implausible_share, 1 / 1001, places=6)
        self.assertGreater(summary.hours_share_implausible, 0.99)
        self.assertAlmostEqual(summary.aggregate_trir_screened, 4.0, places=6)
        self.assertGreater(summary.ratio_screened_to_unscreened, 100.0)

    def test_hours_concentration_finds_the_dominant_filing(self) -> None:
        rows = [{"establishment_id": float(i)} for i in range(100)]
        rows.append({"establishment_id": 999.0, "total_hours_worked": 1e12})
        conc = hours_concentration(make_frame(rows), top_ns=(1, 10))
        top1 = float(conc.loc[conc["top_n_filings_by_hours"] == 1, "hours_share"].iloc[0])
        self.assertGreater(top1, 0.99)

    def test_screened_median_is_robust_to_the_bad_filing(self) -> None:
        rows = [
            {"establishment_id": float(i), "total_dafw_cases": 4.0} for i in range(200)
        ]
        rows.append({"establishment_id": 999.0, "total_hours_worked": 1e13})
        s = summarise_screen(apply_screen(make_frame(rows)))
        self.assertAlmostEqual(s.median_establishment_trir_screened, 4.0, places=6)


class TestReporting(unittest.TestCase):
    """Summary helpers must be self-consistent."""

    def test_flag_prevalence_covers_every_flag(self) -> None:
        f = apply_screen(make_frame([{"total_hours_worked": 1e12}]))
        prev = flag_prevalence(f)
        self.assertEqual(len(prev), 6)
        self.assertEqual(
            int(prev.loc[prev["flag"] == "flag_hours_per_employee_high", "n"].iloc[0]), 1
        )

    def test_summarise_by_year_partitions_the_rows(self) -> None:
        rows = [{"year_filing_for": 2023.0}] * 5 + [{"year_filing_for": 2024.0}] * 7
        out = summarise_by(apply_screen(make_frame(rows)), "year_filing_for")
        self.assertEqual(sorted(out["n_filings"]), [5, 7])

    def test_sensitivity_grid_spans_the_bounds(self) -> None:
        rows = [{"establishment_id": float(i), "total_dafw_cases": 2.0} for i in range(50)]
        rows.append({"establishment_id": 999.0, "total_hours_worked": 1e12})
        grid = sensitivity_grid(make_frame(rows), lows=(100, 200), highs=(4000, 5000))
        self.assertEqual(len(grid), 4)
        self.assertTrue((grid["aggregate_trir_screened"] > 1.9).all())
        self.assertTrue((grid["aggregate_trir_screened"] < 2.1).all())

    def test_sensitivity_grid_skips_invalid_pairs(self) -> None:
        grid = sensitivity_grid(make_frame([{}]), lows=(5000,), highs=(4000,))
        self.assertEqual(len(grid), 0)


if __name__ == "__main__":
    unittest.main()
