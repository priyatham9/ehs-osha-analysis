"""Tests for exact Poisson intervals and two-rate detectability."""

from __future__ import annotations

import math
import unittest

import _context  # noqa: F401
import numpy as np
import pandas as pd

from ehs_osha import detectability as D

TABLES = _context.ROOT / "outputs" / "tables"
DOC = _context.ROOT / "docs" / "DETECTABILITY.md"


class TestGarwood(unittest.TestCase):
    def test_published_values(self) -> None:
        # Standard exact Poisson 95% limits (Garwood 1936; tabulated in textbooks).
        for k, lo, hi in ((0, 0.0, 3.689), (1, 0.0253, 5.572), (10, 4.795, 18.390)):
            got = D.garwood_interval(k)
            self.assertAlmostEqual(got[0], lo, places=3)
            self.assertAlmostEqual(got[1], hi, places=3)

    def test_tail_probabilities(self) -> None:
        lo, hi = D.garwood_interval(7)
        self.assertAlmostEqual(D._poisson_cdf(7, hi), 0.025, places=8)
        self.assertAlmostEqual(1 - D._poisson_cdf(6, lo), 0.025, places=8)

    def test_trir_scaling(self) -> None:
        lo, hi = D.trir_interval(5, 100000.0)
        glo, ghi = D.garwood_interval(5)
        self.assertAlmostEqual(lo, 2.0 * glo)
        self.assertAlmostEqual(hi, 2.0 * ghi)
        with self.assertRaises(ValueError):
            D.trir_interval(1, 0)

    def test_precision_cases(self) -> None:
        k = D.cases_for_precision(2.0)
        lo, hi = D.garwood_interval(k)
        self.assertLessEqual(hi / lo, 2.0)
        lo, hi = D.garwood_interval(k - 1)
        self.assertGreater(hi / lo, 2.0)


class TestPower(unittest.TestCase):
    def test_size_under_null_not_above_alpha(self) -> None:
        self.assertLessEqual(D.power_two_rates(4.0, 4.0, 3e6), 0.05)

    def test_power_increases_to_one(self) -> None:
        self.assertGreater(D.power_two_rates(4.0, 8.0, 1e7), 0.999)

    def test_matches_simulation(self) -> None:
        rng = np.random.default_rng(12345)
        r1, r2, h = 4.0, 6.0, 2e6
        x1 = rng.poisson(r1 * h / 2e5, 20000)
        x2 = rng.poisson(r2 * h / 2e5, 20000)
        n = x1 + x2
        rej = 0
        for a, b, m in zip(x1, x2, n):
            c = D._critical_value(int(m), 0.05)
            rej += min(a, b) <= c
        self.assertAlmostEqual(rej / 20000, D.power_two_rates(r1, r2, h), delta=0.012)

    def test_hours_for_power_reaches_target(self) -> None:
        h = D.hours_for_power(4.0, 5.0)
        self.assertGreaterEqual(D.power_two_rates(4.0, 5.0, h), 0.8)
        self.assertLess(D.power_two_rates(4.0, 5.0, h / 1.05), 0.8)


class TestCommittedTable(unittest.TestCase):
    def test_csv_matches_rebuild(self) -> None:
        src = pd.read_csv(TABLES / "size_band_effects.csv", dtype={"size_band": str})
        want = D.build_table(src)
        got = pd.read_csv(TABLES / "detectability_by_size_band.csv", dtype={"size_band": str})
        pd.testing.assert_frame_equal(got, want, check_exact=False, rtol=1e-9)

    def test_hours_identity(self) -> None:
        got = pd.read_csv(TABLES / "detectability_by_size_band.csv")
        implied = got["mean_hours_per_filing"] * got["aggregate_trir"] / 200000.0
        np.testing.assert_allclose(implied, got["mean_cases_per_filing"])

    def test_methods_note_quotes_table(self) -> None:
        got = pd.read_csv(TABLES / "detectability_by_size_band.csv", dtype={"size_band": str})
        text = DOC.read_text(encoding="utf-8")
        for r in got.itertuples(index=False):
            self.assertIn(f"{r.size_band} | {r.n_filings:,} | {r.mean_hours_per_filing:,.0f} |", text)
            self.assertIn(f"{r.trir_upper_bound_if_zero_cases:.2f}", text)
            self.assertIn(f"{r.site_years_per_arm_80pct_ratio_1_5:.1f}", text)
        self.assertTrue(math.isfinite(got["aggregate_trir"].sum()))


if __name__ == "__main__":
    unittest.main()
