"""Tests for the leave-one-year-out and year-over-year stability analysis.

The tables and docs page are generated from committed tables by
:mod:`ehs_osha.year_stability`; these tests regenerate them in memory, check
the arithmetic against the committed inputs, and fail on drift.
"""

from __future__ import annotations

import io
import unittest

import _context  # noqa: F401
import pandas as pd

from ehs_osha import year_stability as ys

TABLES = _context.ROOT / "outputs" / "tables"


def _csv(df: pd.DataFrame) -> str:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


class TestCommittedFiles(unittest.TestCase):
    def setUp(self) -> None:
        self.tabs = ys.build_tables()

    def test_loyo_matches_regeneration(self) -> None:
        self.assertEqual(ys.LOYO.read_text(encoding="utf-8"), _csv(self.tabs["loyo"]))

    def test_yoy_matches_regeneration(self) -> None:
        self.assertEqual(ys.YOY.read_text(encoding="utf-8"), _csv(self.tabs["yoy"]))

    def test_summary_matches_regeneration(self) -> None:
        self.assertEqual(ys.SUMMARY.read_text(encoding="utf-8"), _csv(self.tabs["summary"]))

    def test_doc_matches_regeneration(self) -> None:
        self.assertEqual(
            ys.DOC.read_text(encoding="utf-8"),
            ys.build_doc(self.tabs["loyo"], self.tabs["yoy"], self.tabs["summary"]),
        )


class TestAgainstInputs(unittest.TestCase):
    def setUp(self) -> None:
        self.overall = pd.read_csv(TABLES / "quality_overall.csv").iloc[0]
        self.by_year = pd.read_csv(TABLES / "quality_by_year.csv")
        self.loyo = pd.read_csv(ys.LOYO)
        self.yoy = pd.read_csv(ys.YOY)
        self.sm = pd.read_csv(ys.SUMMARY).set_index("metric")["value"]

    def test_full_pool_matches_headline(self) -> None:
        a = self.loyo[self.loyo.left_out_year == "all"].iloc[0]
        self.assertEqual(int(a.n_implausible), int(self.overall.n_implausible))
        self.assertAlmostEqual(a.aggregate_trir_screened, self.overall.aggregate_trir_screened, places=6)
        self.assertAlmostEqual(a.aggregate_trir_unscreened, self.overall.aggregate_trir_unscreened, places=6)
        self.assertAlmostEqual(a.implausible_share, self.overall.implausible_share, places=9)

    def test_one_row_per_year(self) -> None:
        self.assertEqual(len(self.yoy), len(self.by_year))
        self.assertEqual(list(self.yoy.year), [int(v) for v in self.by_year.label])
        self.assertEqual(len(self.loyo), len(self.by_year) + 1)

    def test_loyo_flagged_counts_exact(self) -> None:
        total = int(self.by_year.n_implausible.sum())
        for r in self.by_year.itertuples():
            row = self.loyo[self.loyo.left_out_year == str(int(r.label))].iloc[0]
            self.assertEqual(int(row.n_implausible), total - r.n_implausible)
            self.assertEqual(int(row.n_filings), int(self.by_year.n_filings.sum()) - r.n_filings)

    def test_loyo_unscreened_recomputed_from_year_totals(self) -> None:
        for r in self.by_year.itertuples():
            rest = self.by_year[self.by_year.label != r.label]
            want = 200_000 * rest.cases_total.sum() / rest.hours_total.sum()
            row = self.loyo[self.loyo.left_out_year == str(int(r.label))].iloc[0]
            self.assertAlmostEqual(row.aggregate_trir_unscreened, want, places=6)

    def test_yoy_values_match_quality_by_year(self) -> None:
        for r in self.by_year.itertuples():
            row = self.yoy[self.yoy.year == int(r.label)].iloc[0]
            self.assertAlmostEqual(row.aggregate_trir_screened, r.aggregate_trir_screened, places=6)
            self.assertAlmostEqual(row.aggregate_trir_unscreened, r.aggregate_trir_unscreened, places=6)
            self.assertAlmostEqual(row.implausible_share, r.implausible_share, places=9)

    def test_yoy_changes_are_differences(self) -> None:
        v = self.yoy.aggregate_trir_screened.diff().iloc[1:]
        for a, b in zip(v, self.yoy.aggregate_trir_screened_change.iloc[1:]):
            self.assertAlmostEqual(a, b, places=6)
        self.assertTrue(pd.isna(self.yoy.aggregate_trir_screened_change.iloc[0]))

    def test_leaving_out_a_year_drops_two_peer_pairs(self) -> None:
        pp = pd.read_csv(TABLES / "peer_group_persistence.csv")
        full = self.loyo[self.loyo.left_out_year == "all"].iloc[0]
        self.assertEqual(int(full.peer_pairs_remaining), len(pp))
        mid = self.loyo[self.loyo.left_out_year == "2020"].iloc[0]
        self.assertEqual(int(mid.peer_pairs_remaining), len(pp) - 2)
        end = self.loyo[self.loyo.left_out_year == "2016"].iloc[0]
        self.assertEqual(int(end.peer_pairs_remaining), len(pp) - 1)

    def test_peer_rho_summary_matches_source(self) -> None:
        s = pd.read_csv(TABLES / "percentile_band_stability.csv")
        self.assertAlmostEqual(float(self.sm["rho_min"]), s.spearman_rho.min(), places=6)
        self.assertAlmostEqual(float(self.sm["rho_mean"]), s.spearman_rho.mean(), places=6)

    def test_headline_claims_hold(self) -> None:
        lo = self.loyo[self.loyo.left_out_year != "all"]
        self.assertTrue((lo.ratio_screened_to_unscreened > 3).all())
        self.assertLess(lo.aggregate_trir_screened_pct_from_pooled.abs().max(), 5.0)
        self.assertLess(lo.implausible_share_minus_pooled.abs().max(), 0.005)

    def test_one_year_dominates_unscreened(self) -> None:
        lo = self.loyo.set_index("left_out_year")
        self.assertEqual(lo.aggregate_trir_unscreened.idxmax(), "2019")
        self.assertEqual(int(self.sm["trir_unscreened_loyo_most_influential_year"]), 2019)

    def test_inconsistent_totals_rejected(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            for p in TABLES.glob("*.csv"):
                (Path(d) / p.name).write_bytes(p.read_bytes())
            o = pd.read_csv(Path(d) / "quality_overall.csv")
            o["n_implausible"] = o["n_implausible"] + 1
            o.to_csv(Path(d) / "quality_overall.csv", index=False)
            with self.assertRaises(ValueError):
                ys.build_tables(Path(d))


if __name__ == "__main__":
    unittest.main()
