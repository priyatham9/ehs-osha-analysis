"""Tests for the threshold-robustness (specification-curve) analysis.

The tables and docs page are generated from committed tables by
:mod:`ehs_osha.threshold_robustness`; these tests regenerate them in memory,
check the arithmetic against the committed inputs, and fail on drift.
"""

from __future__ import annotations

import io
import unittest

import _context  # noqa: F401
import pandas as pd

from ehs_osha import threshold_robustness as tr

TABLES = _context.ROOT / "outputs" / "tables"


def _csv(df: pd.DataFrame) -> str:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


class TestCommittedFiles(unittest.TestCase):
    def setUp(self) -> None:
        self.tabs = tr.build_tables()

    def test_cells_match_regeneration(self) -> None:
        self.assertEqual(tr.CELLS.read_text(encoding="utf-8"), _csv(self.tabs["cells"]))

    def test_summary_matches_regeneration(self) -> None:
        self.assertEqual(tr.SUMMARY.read_text(encoding="utf-8"), _csv(self.tabs["summary"]))

    def test_doc_matches_regeneration(self) -> None:
        self.assertEqual(
            tr.DOC.read_text(encoding="utf-8"),
            tr.build_doc(self.tabs["cells"], self.tabs["summary"]),
        )


class TestAgainstInputs(unittest.TestCase):
    def setUp(self) -> None:
        self.grid = pd.read_csv(TABLES / "quality_sensitivity_grid.csv")
        self.overall = pd.read_csv(TABLES / "quality_overall.csv").iloc[0]
        self.cells = pd.read_csv(tr.CELLS)
        self.sm = pd.read_csv(tr.SUMMARY).set_index("metric")["value"]

    def test_one_row_per_grid_cell(self) -> None:
        self.assertEqual(len(self.cells), len(self.grid))
        self.assertEqual(set(self.cells.label), set(self.grid.label))

    def test_default_cell_matches_headline(self) -> None:
        d = self.cells[self.cells.is_default]
        self.assertEqual(len(d), 1)
        d = d.iloc[0]
        self.assertAlmostEqual(d.aggregate_trir_screened, self.overall.aggregate_trir_screened, places=6)
        self.assertEqual(int(d.n_implausible), int(self.overall.n_implausible))
        self.assertAlmostEqual(d.trir_screened_minus_default, 0.0, places=9)

    def test_screened_trir_recomputed_from_totals(self) -> None:
        got = 200_000 * self.cells.screened_cases / self.cells.screened_hours
        for a, b in zip(got, self.cells.aggregate_trir_screened):
            self.assertAlmostEqual(a, b, places=6)

    def test_flagged_plus_screened_equals_total(self) -> None:
        total_h = int(round(self.grid.hours_total.iloc[0]))
        total_c = int(round(self.grid.cases_total.iloc[0]))
        self.assertTrue(((self.cells.flagged_hours + self.cells.screened_hours) == total_h).all())
        self.assertTrue(((self.cells.flagged_cases + self.cells.screened_cases) == total_c).all())

    def test_flagged_sets_nested_along_each_bound(self) -> None:
        c = self.cells
        for lo, sub in c.groupby("min_hours_per_employee"):
            sub = sub.sort_values("max_hours_per_employee")
            self.assertTrue(sub.n_implausible.is_monotonic_decreasing, lo)
            self.assertTrue(sub.flagged_hours.is_monotonic_decreasing, lo)
        for hi, sub in c.groupby("max_hours_per_employee"):
            sub = sub.sort_values("min_hours_per_employee")
            self.assertTrue(sub.n_implausible.is_monotonic_increasing, hi)
            self.assertTrue(sub.flagged_hours.is_monotonic_increasing, hi)

    def test_headline_conclusions_hold_in_every_cell(self) -> None:
        self.assertTrue((self.cells.aggregate_trir_screened > 10 * self.cells.aggregate_trir_unscreened).all())
        self.assertLess(self.cells.trir_screened_pct_from_default.abs().max(), 1.0)
        self.assertGreater(self.cells.implausible_share.max() / self.cells.implausible_share.min(), 2.0)

    def test_summary_ranges_match_cells(self) -> None:
        self.assertAlmostEqual(float(self.sm["trir_screened_min"]), self.cells.aggregate_trir_screened.min(), places=6)
        self.assertAlmostEqual(float(self.sm["trir_screened_max"]), self.cells.aggregate_trir_screened.max(), places=6)
        self.assertEqual(int(self.sm["n_implausible_max"]), int(self.cells.n_implausible.max()))

    def test_marginal_band_is_difference_of_cells(self) -> None:
        a = tr._cell(self.cells, 120.0, 4500.0)
        b = tr._cell(self.cells, 120.0, 6000.0)
        r = tr._band_rate(a, b)
        self.assertEqual(r["filings"], 57857 - 52953)
        self.assertEqual(r["filings"], int(self.sm["upper_bound_4500_to_6000_filings"]))
        self.assertAlmostEqual(r["trir"], 200_000 * r["cases"] / r["hours"], places=9)

    def test_rank_trim_top1(self) -> None:
        conc = pd.read_csv(TABLES / "quality_hours_concentration.csv").iloc[0]
        h = float(self.overall.hours_total) * (1 - conc.hours_share)
        c = float(self.overall.cases_total) * (1 - conc.cases_share)
        self.assertAlmostEqual(float(self.sm["drop_top_1_by_hours_trir"]), 200_000 * c / h, places=6)

    def test_rank_trim_is_increasing_in_n(self) -> None:
        v = [float(self.sm[f"drop_top_{n}_by_hours_trir"]) for n in (1, 10, 100, 1000, 10000)]
        self.assertEqual(v, sorted(v))

    def test_default_mismatch_is_rejected(self) -> None:
        bad = self.overall.to_frame().T.copy()
        bad["aggregate_trir_screened"] = 1.0
        with self.assertRaises(ValueError):
            tr.build_cells(self.grid, bad)


if __name__ == "__main__":
    unittest.main()
