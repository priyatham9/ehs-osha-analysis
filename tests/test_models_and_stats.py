"""Tests for the optimiser, the count models and the stability statistics.

The count-model tests generate data from known parameters and check that the
estimators recover them, and check the chi-square tail function against values
computed independently by the Wilson-Hilferty approximation.
"""

from __future__ import annotations

import math
import unittest

import _context  # noqa: F401
import numpy as np
import pandas as pd

from ehs_osha.countmodels import (
    _chi2_sf,
    boundary_lrt,
    compare_models,
    fit_nb2,
    fit_poisson,
    fit_zinb,
    fit_zip,
    nb2_loglik,
    poisson_loglik,
    predicted_count_distribution,
    prepare_counts,
)
from ehs_osha.optimize import golden_section, nelder_mead
from ehs_osha.peers import (
    PeerTableConfig,
    add_peer_keys,
    assign_size_band,
    coverage_summary,
    percentile_table,
)
from ehs_osha.quality import apply_screen
from ehs_osha.load import derive_fields
from ehs_osha.stability import (
    group_persistence,
    rankdata_average,
    spearman_rho,
    summarise_stability,
    year_pair_stability,
)


def simulate_nb(
    rng: np.random.Generator, n: int, mu: float, alpha: float, pi: float = 0.0
) -> "tuple[np.ndarray, np.ndarray]":
    """Draw (counts, exposure) from a known ZINB, for parameter-recovery tests."""
    e = np.clip(rng.lognormal(0.0, 0.9, n), 0.05, 40.0)
    r = 1.0 / alpha
    g = rng.gamma(r, 1.0 / r, n)
    y = rng.poisson(e * mu * g).astype(float)
    if pi > 0:
        y = np.where(rng.random(n) < pi, 0.0, y)
    return y, e


class TestOptimize(unittest.TestCase):
    """The hand-rolled optimisers must solve standard problems."""

    def test_nelder_mead_on_rosenbrock(self) -> None:
        def rosen(v: np.ndarray) -> float:
            return float((1 - v[0]) ** 2 + 100 * (v[1] - v[0] ** 2) ** 2)

        res = nelder_mead(rosen, [-1.2, 1.0], max_iter=20000, xtol=1e-10, ftol=1e-14)
        self.assertTrue(res.converged)
        np.testing.assert_allclose(res.x, [1.0, 1.0], atol=1e-4)

    def test_nelder_mead_handles_infinite_objective(self) -> None:
        def guarded(v: np.ndarray) -> float:
            return float("inf") if v[0] < 0 else float((v[0] - 3.0) ** 2)

        res = nelder_mead(guarded, [1.0], step=0.5, max_iter=5000)
        self.assertAlmostEqual(float(res.x[0]), 3.0, places=4)

    def test_nelder_mead_rejects_bad_simplex(self) -> None:
        with self.assertRaises(ValueError):
            nelder_mead(lambda v: float(v[0] ** 2), [0.0], initial_simplex=np.zeros((5, 3)))

    def test_golden_section(self) -> None:
        x, fx = golden_section(lambda t: (t - 2.5) ** 2 + 1.0, 0.0, 10.0)
        self.assertAlmostEqual(x, 2.5, places=6)
        self.assertAlmostEqual(fx, 1.0, places=6)
        with self.assertRaises(ValueError):
            golden_section(lambda t: t, 5.0, 1.0)


class TestCountModels(unittest.TestCase):
    """Estimators must recover parameters they were not told."""

    def test_prepare_counts_validates(self) -> None:
        with self.assertRaises(ValueError):
            prepare_counts(np.array([1.0, 2.0]), np.array([1.0]))
        with self.assertRaises(ValueError):
            prepare_counts(np.array([1.5]), np.array([1.0]))
        with self.assertRaises(ValueError):
            prepare_counts(np.array([]), np.array([]))
        y, e = prepare_counts(np.array([1.0, 2.0, np.nan]), np.array([1.0, 1.0, 1.0]))
        self.assertEqual(y.size, 2)

    def test_poisson_closed_form_is_the_mle(self) -> None:
        rng = np.random.default_rng(1)
        e = np.full(5000, 2.0)
        y = rng.poisson(e * 1.7).astype(float)
        fit = fit_poisson(y, e)
        self.assertAlmostEqual(fit.params["mu"], float(y.sum() / e.sum()))
        # Perturbing mu must not improve the likelihood.
        base = poisson_loglik(y, e * fit.params["mu"])
        for delta in (0.98, 1.02):
            self.assertLess(poisson_loglik(y, e * fit.params["mu"] * delta), base)

    def test_poisson_handles_all_zero_data(self) -> None:
        fit = fit_poisson(np.zeros(100), np.ones(100))
        self.assertEqual(fit.params["mu"], 0.0)
        self.assertEqual(fit.loglik, 0.0)
        self.assertEqual(fit.expected_zeros, 100.0)

    def test_nb2_recovers_mu_and_alpha(self) -> None:
        rng = np.random.default_rng(11)
        y, e = simulate_nb(rng, 30000, mu=2.5, alpha=1.1)
        fit = fit_nb2(y, e)
        self.assertTrue(fit.converged)
        self.assertAlmostEqual(fit.params["mu"], 2.5, delta=0.20)
        self.assertAlmostEqual(fit.params["alpha"], 1.1, delta=0.20)

    def test_nb2_approaches_poisson_as_alpha_shrinks(self) -> None:
        y = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
        m = np.full(5, 2.0)
        self.assertAlmostEqual(nb2_loglik(y, m, 1e-7), poisson_loglik(y, m), places=3)

    def test_zip_recovers_pi(self) -> None:
        rng = np.random.default_rng(21)
        n = 40000
        e = np.full(n, 1.0)
        y = rng.poisson(e * 2.0).astype(float)
        y = np.where(rng.random(n) < 0.25, 0.0, y)
        fit = fit_zip(y, e)
        self.assertAlmostEqual(fit.params["pi"], 0.25, delta=0.03)
        self.assertAlmostEqual(fit.params["mu"], 2.0, delta=0.10)

    def test_zinb_recovers_all_three_parameters(self) -> None:
        rng = np.random.default_rng(31)
        y, e = simulate_nb(rng, 40000, mu=3.0, alpha=1.2, pi=0.20)
        fit = fit_zinb(y, e)
        self.assertTrue(fit.converged)
        self.assertAlmostEqual(fit.params["mu"], 3.0, delta=0.35)
        self.assertAlmostEqual(fit.params["alpha"], 1.2, delta=0.35)
        self.assertAlmostEqual(fit.params["pi"], 0.20, delta=0.06)

    def test_zinb_beats_nb2_when_data_are_truly_inflated(self) -> None:
        rng = np.random.default_rng(41)
        y, e = simulate_nb(rng, 20000, mu=3.0, alpha=0.8, pi=0.25)
        fits, tests = compare_models(y, e)
        by = {f.model: f for f in fits}
        self.assertLess(by["zinb"].aic, by["nb2"].aic)
        self.assertLess(tests["zinb_vs_nb2"]["p_value_boundary"], 0.01)

    def test_nb2_wins_when_there_is_no_extra_inflation(self) -> None:
        # Overdispersion alone produces many zeros without zero-inflation. The
        # comparison must not mistake one for the other.
        rng = np.random.default_rng(51)
        y, e = simulate_nb(rng, 20000, mu=2.0, alpha=1.5, pi=0.0)
        fits, tests = compare_models(y, e)
        by = {f.model: f for f in fits}
        self.assertGreater((y == 0).mean(), 0.3)  # plenty of zeros
        self.assertLessEqual(by["nb2"].aic, by["zinb"].aic + 2.5)
        self.assertLess(by["nb2"].aic, by["poisson"].aic)

    def test_compare_models_rejects_unknown_name(self) -> None:
        with self.assertRaises(ValueError):
            compare_models(np.array([0.0, 1.0]), np.ones(2), models=("logistic",))

    def test_information_criteria_and_zero_ratio(self) -> None:
        fit = fit_poisson(np.array([0.0, 1.0, 2.0, 0.0]), np.ones(4))
        self.assertAlmostEqual(fit.aic, 2 * fit.k - 2 * fit.loglik)
        self.assertAlmostEqual(fit.bic, fit.k * math.log(fit.n) - 2 * fit.loglik)
        self.assertAlmostEqual(fit.zero_ratio, fit.observed_zeros / fit.expected_zeros)

    def test_predicted_distribution_sums_to_n(self) -> None:
        rng = np.random.default_rng(61)
        y, e = simulate_nb(rng, 5000, mu=2.0, alpha=1.0, pi=0.1)
        for fit in (fit_poisson(y, e), fit_nb2(y, e), fit_zinb(y, e)):
            pred = predicted_count_distribution(fit, e, max_count=12)
            self.assertAlmostEqual(float(pred.sum()), float(len(y)), delta=1.0)

    def test_chi2_sf_matches_reference_values(self) -> None:
        # Reference values from the standard chi-square distribution.
        self.assertAlmostEqual(_chi2_sf(3.841458820694124, 1), 0.05, places=6)
        self.assertAlmostEqual(_chi2_sf(5.991464547107979, 2), 0.05, places=6)
        self.assertAlmostEqual(_chi2_sf(0.0, 1), 1.0, places=10)
        self.assertLess(_chi2_sf(100.0, 1), 1e-20)

    def test_boundary_lrt_halves_the_p_value(self) -> None:
        r = fit_poisson(np.array([0.0, 1.0, 2.0]), np.ones(3))
        f = fit_zip(np.array([0.0, 1.0, 2.0]), np.ones(3))
        out = boundary_lrt(r, f)
        self.assertAlmostEqual(
            out["p_value_boundary"], 0.5 * out["p_value_naive_chi2"], places=12
        )
        with self.assertRaises(ValueError):
            boundary_lrt(f, r)


class TestPeers(unittest.TestCase):
    """Peer grouping must not depend on the year-unstable ``size`` field."""

    def test_size_bands(self) -> None:
        s = assign_size_band(pd.Series([1, 19, 20, 99, 100, 249, 250, 5000, np.nan, 0]))
        self.assertEqual(
            list(s),
            [
                "001-019", "001-019", "020-049", "050-099", "100-249",
                "100-249", "250-499", "1000+", None, None,
            ],
        )

    def test_size_band_length_mismatch_raises(self) -> None:
        with self.assertRaises(ValueError):
            assign_size_band(pd.Series([1]), edges=(1, 10), labels=("a",))

    def test_percentile_table_applies_min_group_n(self) -> None:
        rows = []
        for i in range(40):
            rows.append(
                {
                    "annual_average_employees": 30.0,
                    "total_hours_worked": 60000.0,
                    "total_dafw_cases": float(i % 5),
                    "total_djtr_cases": 0.0,
                    "total_other_cases": 0.0,
                    "total_deaths": 0.0,
                    "no_injuries_illnesses": 1.0,
                    "naics_code": 325199.0,
                    "year_filing_for": 2024.0,
                    "establishment_id": float(i),
                }
            )
        for i in range(5):
            r = dict(rows[0])
            r.update({"naics_code": 311111.0, "establishment_id": 900.0 + i})
            rows.append(r)
        keyed = add_peer_keys(apply_screen(derive_fields(pd.DataFrame(rows))))
        table = percentile_table(keyed, PeerTableConfig(min_group_n=30))
        pub = dict(zip(table["naics3"], table["publishable"]))
        self.assertTrue(pub["325"])
        self.assertFalse(pub["311"])
        cov = coverage_summary(table)
        self.assertEqual(cov["groups_total"], 2)
        self.assertEqual(cov["groups_publishable"], 1)

    def test_percentile_table_reports_missing_columns(self) -> None:
        with self.assertRaises(KeyError):
            percentile_table(pd.DataFrame({"a": [1]}))

    def test_add_peer_keys_rejects_unknown_level(self) -> None:
        with self.assertRaises(KeyError):
            add_peer_keys(pd.DataFrame({"annual_average_employees": [1.0]}), "naics9")


class TestStability(unittest.TestCase):
    """Rank statistics must match their textbook definitions."""

    def test_rankdata_average_handles_ties(self) -> None:
        np.testing.assert_allclose(
            rankdata_average(np.array([10.0, 20.0, 20.0, 30.0])), [1.0, 2.5, 2.5, 4.0]
        )

    def test_spearman_perfect_and_reversed(self) -> None:
        a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertAlmostEqual(spearman_rho(a, a), 1.0)
        self.assertAlmostEqual(spearman_rho(a, a[::-1]), -1.0)

    def test_spearman_is_rank_based_not_value_based(self) -> None:
        a = np.array([1.0, 2.0, 3.0, 4.0])
        b = np.exp(a)  # monotone but strongly nonlinear
        self.assertAlmostEqual(spearman_rho(a, b), 1.0)

    def test_spearman_degenerate_cases(self) -> None:
        self.assertTrue(np.isnan(spearman_rho(np.array([1.0, 2.0]), np.array([1.0, 2.0]))))
        self.assertTrue(
            np.isnan(spearman_rho(np.ones(5), np.array([1.0, 2, 3, 4, 5])))
        )
        with self.assertRaises(ValueError):
            spearman_rho(np.ones(3), np.ones(4))

    def test_year_pair_stability_and_persistence(self) -> None:
        table = pd.DataFrame(
            {
                "year_filing_for": [2023] * 4 + [2024] * 4,
                "naics3": ["325", "311", "236", "484"] * 2,
                "size_band": ["020-049"] * 8,
                "p50": [1.0, 2.0, 3.0, 4.0, 1.1, 2.2, 3.3, 4.4],
                "publishable": [True] * 8,
            }
        )
        stab = year_pair_stability(table)
        self.assertEqual(len(stab), 1)
        self.assertAlmostEqual(float(stab["spearman_rho"].iloc[0]), 1.0)
        self.assertGreater(float(stab["median_abs_rel_change"].iloc[0]), 0.0)
        head = summarise_stability(stab)
        self.assertIn("p50_median_rho", head)

        pers = group_persistence(table)
        self.assertEqual(int(pers["groups_matched"].iloc[0]), 4)
        self.assertAlmostEqual(float(pers["matched_share_of_year_from"].iloc[0]), 1.0)

    def test_stability_requires_group_columns(self) -> None:
        with self.assertRaises(KeyError):
            year_pair_stability(pd.DataFrame({"year_filing_for": [2023]}))


if __name__ == "__main__":
    unittest.main()
