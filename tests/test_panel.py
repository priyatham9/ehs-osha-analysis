"""Tests for the establishment-year persistence panel.

These tests do not need the 161 MB real dataset. They build small hand-crafted
frames (in the same style as ``tests/test_quality.py``) and check the panel
machinery against contingency tables and a Cohen's kappa value computed by
hand.
"""

from __future__ import annotations

import unittest

import _context  # noqa: F401
import numpy as np
import pandas as pd

from ehs_osha.load import derive_fields
from ehs_osha.panel import (
    _pair_counts,
    build_flag_panel,
    coverage_table,
    cohens_kappa,
    establishment_id_stability,
    odds_ratio,
    permutation_null,
    permutation_table,
    pooled_odds_ratio,
    transition_table,
    year_2019_table,
)


def make_frame(rows: list[dict]) -> pd.DataFrame:
    """Build a harmonised frame from partial row dicts, filling defaults.

    Mirrors ``tests/test_quality.py::make_frame``: every row is plausible by
    default (200,000 hours, 100 employees -> 2,000 hours/employee), so a test
    only needs to state what makes a row implausible.
    """
    default = {
        "annual_average_employees": 100.0,
        "total_hours_worked": 200000.0,
        "total_deaths": 0.0,
        "total_dafw_cases": 0.0,
        "total_djtr_cases": 0.0,
        "total_other_cases": 0.0,
        "no_injuries_illnesses": 2.0,
        "naics_code": 325199.0,
        "ein": 111111111.0,
        "company_name": "Acme",
        "state": "OH",
    }
    return derive_fields(pd.DataFrame([{**default, **r} for r in rows]))


class TestKeyStability(unittest.TestCase):
    """The panel key must actually identify one entity over time."""

    def test_stable_key_reports_no_multiplicity(self) -> None:
        df = make_frame(
            [
                {"establishment_id": 1.0, "year_filing_for": 2020.0},
                {"establishment_id": 1.0, "year_filing_for": 2021.0},
                {"establishment_id": 2.0, "year_filing_for": 2020.0},
            ]
        )
        rep = establishment_id_stability(df)
        self.assertEqual(rep.n_establishments, 2)
        self.assertEqual(rep.n_missing, 0)
        self.assertEqual(rep.multi_ein, 0)
        self.assertEqual(rep.multi_company_name, 0)
        self.assertEqual(rep.multi_state, 0)

    def test_reused_id_across_different_filers_is_flagged(self) -> None:
        df = make_frame(
            [
                {
                    "establishment_id": 1.0,
                    "year_filing_for": 2020.0,
                    "ein": 111111111.0,
                    "company_name": "Acme",
                    "state": "OH",
                },
                {
                    "establishment_id": 1.0,
                    "year_filing_for": 2021.0,
                    "ein": 222222222.0,
                    "company_name": "Other Co",
                    "state": "TX",
                },
            ]
        )
        rep = establishment_id_stability(df)
        self.assertEqual(rep.multi_ein, 1)
        self.assertEqual(rep.multi_company_name, 1)
        self.assertEqual(rep.multi_state, 1)


class TestPanelAndTransitions(unittest.TestCase):
    """Transition counts and conditional probabilities on a fixture with a
    contingency table chosen and verified by hand.

    Establishments 1-4 file in both 2020 and 2021 (2x2 cell membership below);
    establishment 5 files only in 2020 (drops out of every consecutive-pair
    count, which is the point of restricting to establishments present in
    both years of a pair).

        est  2020        2021        cell
        1    flagged     flagged     n11
        2    flagged     ok          n10
        3    ok          flagged     n01
        4    ok          ok          n00
        5    flagged     (absent)    -
    """

    def setUp(self) -> None:
        rows = [
            {"establishment_id": 1.0, "year_filing_for": 2020.0, "total_hours_worked": 1.0},
            {"establishment_id": 1.0, "year_filing_for": 2021.0, "total_hours_worked": 1.0},
            {"establishment_id": 2.0, "year_filing_for": 2020.0, "total_hours_worked": 1.0},
            {"establishment_id": 2.0, "year_filing_for": 2021.0},
            {"establishment_id": 3.0, "year_filing_for": 2020.0},
            {"establishment_id": 3.0, "year_filing_for": 2021.0, "total_hours_worked": 1.0},
            {"establishment_id": 4.0, "year_filing_for": 2020.0},
            {"establishment_id": 4.0, "year_filing_for": 2021.0},
            {"establishment_id": 5.0, "year_filing_for": 2020.0, "total_hours_worked": 1.0},
        ]
        self.df = make_frame(rows)
        self.wide = build_flag_panel(self.df)

    def test_wide_panel_shape_and_missingness(self) -> None:
        self.assertEqual(sorted(self.wide.columns.tolist()), [2020.0, 2021.0])
        self.assertEqual(self.wide.shape[0], 5)
        self.assertTrue(np.isnan(self.wide.loc[5.0, 2021.0]))

    def test_pair_counts_match_hand_built_table(self) -> None:
        arr = self.wide.to_numpy(dtype="float64")
        n11, n10, n01, n00 = _pair_counts(arr[:, 0], arr[:, 1])
        self.assertEqual((n11, n10, n01, n00), (1, 1, 1, 1))

    def test_transition_table_pooled_row_and_probabilities(self) -> None:
        table = transition_table(self.wide)
        self.assertEqual(len(table), 2)  # one pair + pooled
        pooled = table.iloc[-1]
        self.assertEqual(pooled["year_prev"], "pooled")
        self.assertEqual(pooled["n11_flag_then_flag"], 1)
        self.assertEqual(pooled["n10_flag_then_noflag"], 1)
        self.assertEqual(pooled["n01_noflag_then_flag"], 1)
        self.assertEqual(pooled["n00_noflag_then_noflag"], 1)
        self.assertEqual(pooled["n_total"], 4)
        self.assertAlmostEqual(pooled["p_flag_given_prev_flag"], 0.5)
        self.assertAlmostEqual(pooled["p_flag_given_prev_noflag"], 0.5)

    def test_odds_ratio_balanced_table_is_one(self) -> None:
        # n11=n00=n10=n01=1 -> OR = (1*1)/(1*1) = 1: no persistence signal.
        self.assertAlmostEqual(odds_ratio(1, 1, 1, 1), 1.0)

    def test_odds_ratio_undefined_when_a_discordant_cell_is_empty(self) -> None:
        self.assertTrue(np.isnan(odds_ratio(5, 0, 3, 2)))


class TestKappa(unittest.TestCase):
    """Kappa checked against a hand-computed value.

    Table: n11=40, n10=10, n01=10, n00=40, n=100.
    p_prev_flag = p_curr_flag = 0.5.
    p_observed = (40+40)/100 = 0.80.
    p_expected = 0.5*0.5 + 0.5*0.5 = 0.50.
    kappa = (0.80 - 0.50) / (1 - 0.50) = 0.60.
    """

    def test_matches_hand_computation(self) -> None:
        self.assertAlmostEqual(cohens_kappa(40, 10, 10, 40), 0.6)

    def test_perfect_agreement_is_one(self) -> None:
        self.assertAlmostEqual(cohens_kappa(50, 0, 0, 50), 1.0)

    def test_no_variance_marginal_is_nan(self) -> None:
        # Everyone flagged in both years: p_expected = 1 -> undefined.
        self.assertTrue(np.isnan(cohens_kappa(10, 0, 0, 0)))


class TestPermutationReproducibility(unittest.TestCase):
    """The permutation null must be exactly reproducible under a fixed seed."""

    def setUp(self) -> None:
        rng = np.random.default_rng(0)
        n = 400
        rows = []
        for est in range(n):
            persistent = est < 20  # a genuinely clustered subgroup
            for year in (2020.0, 2021.0, 2022.0):
                if persistent:
                    flagged = rng.random() < 0.8
                else:
                    flagged = rng.random() < 0.02
                hours = 1.0 if flagged else 200000.0
                rows.append(
                    {
                        "establishment_id": float(est),
                        "year_filing_for": year,
                        "total_hours_worked": hours,
                    }
                )
        self.wide = build_flag_panel(make_frame(rows))

    def test_two_runs_with_same_seed_are_identical(self) -> None:
        a = permutation_null(self.wide, n_perm=25, seed=20260909)
        b = permutation_null(self.wide, n_perm=25, seed=20260909)
        np.testing.assert_array_equal(a, b)

    def test_different_seed_can_differ(self) -> None:
        a = permutation_null(self.wide, n_perm=25, seed=20260909)
        b = permutation_null(self.wide, n_perm=25, seed=1)
        self.assertFalse(np.array_equal(a, b))

    def test_clustered_signal_exceeds_permutation_null(self) -> None:
        observed = pooled_odds_ratio(self.wide)
        table = permutation_table(self.wide, n_perm=50, seed=20260909)
        self.assertGreater(observed, float(table["permutation_p97_5"].iloc[0]))
        self.assertEqual(float(table["fraction_permutations_ge_observed"].iloc[0]), 0.0)


class TestCoverageAndYear2019(unittest.TestCase):
    """Coverage counts and the 2019-specific clustering check."""

    def test_coverage_counts(self) -> None:
        rows = [
            {"establishment_id": 1.0, "year_filing_for": 2020.0},
            {"establishment_id": 1.0, "year_filing_for": 2021.0},
            {"establishment_id": 2.0, "year_filing_for": 2020.0},
        ]
        df = make_frame(rows)
        wide = build_flag_panel(df)
        stability = establishment_id_stability(df)
        table = coverage_table(wide, stability)
        as_dict = dict(zip(table["metric"], table["value"]))
        self.assertEqual(as_dict["distinct_establishments"], 2)
        self.assertEqual(as_dict["establishments_in_2_or_more_years"], 1)

    def test_year_2019_absent_reports_a_note_not_a_crash(self) -> None:
        df = make_frame(
            [
                {"establishment_id": 1.0, "year_filing_for": 2020.0},
                {"establishment_id": 1.0, "year_filing_for": 2021.0},
            ]
        )
        table = year_2019_table(build_flag_panel(df))
        self.assertIn("note", table.columns)

    def test_year_2019_clustering_detected(self) -> None:
        # Establishment 1 is flagged in 2018, 2019 and 2020 (repeat offender).
        # Establishment 2 is flagged only in 2019 (one-off).
        # Establishments 3-6 are never flagged, present in all three years.
        rows = []
        for est in (1, 2, 3, 4, 5, 6):
            for year in (2018.0, 2019.0, 2020.0):
                flagged = est == 1 or (est == 2 and year == 2019.0)
                hours = 1.0 if flagged else 200000.0
                rows.append(
                    {
                        "establishment_id": float(est),
                        "year_filing_for": year,
                        "total_hours_worked": hours,
                    }
                )
        wide = build_flag_panel(make_frame(rows))
        table = year_2019_table(wide, focus_year=2019)
        by_comparison = table.set_index("comparison")
        self.assertEqual(by_comparison.loc["2019_summary", "n_flagged"], 2)
        # Of the 2 establishments flagged in 2019, 1 is also flagged in 2018.
        row_2018 = by_comparison.loc["2019_flagged_also_flagged_in_2018"]
        self.assertEqual(row_2018["n_flagged"], 1)
        self.assertEqual(row_2018["n_filers"], 2)
        self.assertGreater(row_2018["enrichment_ratio"], 1.0)


if __name__ == "__main__":
    unittest.main()
