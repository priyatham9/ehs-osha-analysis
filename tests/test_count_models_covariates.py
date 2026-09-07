"""Tests for the covariate-adjusted count models.

The parameter-recovery tests use a fabricated fixture generated in-process by
``_simulate``; it is synthetic, describes no real establishment, and no number
from it is reported anywhere. The real-data test runs the full covariate fit on
a small subsample and is skipped when the raw files are absent.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import _context  # noqa: F401
import numpy as np

from ehs_osha.count_models_covariates import (
    MODELS,
    compare_with_covariates,
    design_matrix,
    expected_count_distribution,
    fit_with_covariates,
)

ROOT = Path(__file__).resolve().parents[1]
TRUE_BETA = np.array([0.3, 0.4, 0.8, 1.2, -0.3, 0.5])
TRUE_ALPHA = 0.8
TRUE_PI = 0.2


def _simulate(n: int = 8000, seed: int = 1, alpha=TRUE_ALPHA, pi=TRUE_PI):
    """SYNTHETIC fixture: ZINB counts with known coefficients."""
    rng = np.random.default_rng(seed)
    sb = rng.choice(["1-10", "11-49", "50-249", "250+"], n)
    fe = rng.choice(["a", "b", "c"], n)
    X, names = design_matrix(sb, fe)
    e = rng.uniform(0.2, 5.0, n)
    m = e * np.exp(X @ TRUE_BETA)
    lam = rng.gamma(1.0 / alpha, alpha * m) if alpha > 0 else m
    y = rng.poisson(lam).astype("float64")
    if pi > 0:
        y[rng.uniform(size=n) < pi] = 0.0
    return y, e, X, names


class DesignMatrixTests(unittest.TestCase):
    def test_reference_levels_and_shape(self) -> None:
        X, names = design_matrix(["1-10", "11-49", "1-10"], ["a", "a", "b"])
        self.assertEqual(names, ["intercept", "size_band[11-49]", "fe[b]"])
        self.assertEqual(X.shape, (3, 3))
        np.testing.assert_array_equal(X[:, 0], 1.0)


class RecoveryTests(unittest.TestCase):
    def test_zinb_recovers_known_coefficients(self) -> None:
        y, e, X, names = _simulate()
        fit = fit_with_covariates(y, e, X, "zinb", names)
        beta = np.array([fit.params[nm] for nm in names])
        np.testing.assert_allclose(beta, TRUE_BETA, atol=0.08)
        self.assertAlmostEqual(fit.params["alpha"], TRUE_ALPHA, delta=0.15)
        self.assertAlmostEqual(fit.params["pi"], TRUE_PI, delta=0.04)
        self.assertEqual(fit.k, len(names) + 2)

    def test_nb2_recovers_when_no_inflation(self) -> None:
        y, e, X, names = _simulate(pi=0.0, seed=2)
        fit = fit_with_covariates(y, e, X, "nb2", names)
        beta = np.array([fit.params[nm] for nm in names])
        np.testing.assert_allclose(beta, TRUE_BETA, atol=0.08)
        self.assertAlmostEqual(fit.params["alpha"], TRUE_ALPHA, delta=0.12)
        self.assertTrue(fit.converged)

    def test_poisson_recovers_when_equidispersed(self) -> None:
        y, e, X, names = _simulate(pi=0.0, alpha=0.0, seed=3)
        fit = fit_with_covariates(y, e, X, "poisson", names)
        beta = np.array([fit.params[nm] for nm in names])
        np.testing.assert_allclose(beta, TRUE_BETA, atol=0.05)
        # NB2 must not claim overdispersion that is not there.
        nb = fit_with_covariates(y, e, X, "nb2", names)
        self.assertLess(nb.params["alpha"], 0.02)
        self.assertGreater(nb.aic, fit.aic - 2.5)

    def test_compare_orders_and_tests(self) -> None:
        y, e, X, names = _simulate(n=3000, seed=4)
        fits, tests = compare_with_covariates(y, e, X, names)
        self.assertEqual([f.model for f in fits], list(MODELS))
        self.assertLess(tests["nb2_vs_poisson"]["p_value_boundary"], 1e-6)
        self.assertLess(tests["zinb_vs_nb2"]["p_value_boundary"], 1e-3)
        pred = expected_count_distribution(fits[3], e, X, names)
        self.assertAlmostEqual(float(pred.sum()), float(len(y)), delta=1e-6 * len(y))

    def test_rejects_bad_input(self) -> None:
        y, e, X, names = _simulate(n=50)
        with self.assertRaises(ValueError):
            fit_with_covariates(y, e, X, "gamma", names)
        with self.assertRaises(ValueError):
            fit_with_covariates(y, e[:-1], X, "poisson", names)


class RealDataSubsampleTest(unittest.TestCase):
    def test_runner_completes_on_subsample(self) -> None:
        raw = ROOT / "data" / "raw"
        if not (raw / "manifest.json").exists():
            self.skipTest("raw OSHA files not present")
        import tempfile

        from ehs_osha.count_models_covariates import run_real_data

        with tempfile.TemporaryDirectory() as tmp:
            table = run_real_data(raw, Path(tmp), top_k=2, max_n=2000, verbose=False)
            self.assertEqual(sorted(table["model"].unique()), sorted(MODELS))
            self.assertTrue((Path(tmp) / "figures" / "fig04_count_model_fit.svg").exists())
            self.assertTrue((Path(tmp) / "tables" / "count_model_covariates_summary.csv").exists())


if __name__ == "__main__":
    unittest.main()
