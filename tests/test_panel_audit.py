"""Tests for the establishment linkage and panel-quality audit.

The audit table and docs page are generated from committed tables by
:mod:`ehs_osha.panel_audit`; these tests regenerate them in memory, check them
against the committed inputs, and fail if the committed files drift.
"""

from __future__ import annotations

import unittest

import _context  # noqa: F401
import pandas as pd

from ehs_osha import panel_audit as pa

TABLES = _context.ROOT / "outputs" / "tables"


def _audit() -> pd.DataFrame:
    return pd.read_csv(TABLES / "panel_linkage_audit.csv")


def _val(df: pd.DataFrame, section: str, metric: str, basis: "str | None" = None) -> pd.Series:
    sel = df[(df.section == section) & (df.metric == metric)]
    if basis is not None:
        sel = sel[sel.share_basis == basis]
    assert len(sel) == 1, (section, metric, len(sel))
    return sel.iloc[0]


class TestCommittedFiles(unittest.TestCase):
    def test_table_matches_regeneration(self) -> None:
        import io

        buf = io.StringIO()
        pa.build_table().to_csv(buf, index=False)
        self.assertEqual((TABLES / "panel_linkage_audit.csv").read_text(encoding="utf-8"),
                         buf.getvalue())

    def test_doc_matches_regeneration(self) -> None:
        self.assertEqual(pa.DOC.read_text(encoding="utf-8"), pa.build_doc(pa.build_table()))


class TestAgainstInputs(unittest.TestCase):
    def setUp(self) -> None:
        self.cov = pd.read_csv(TABLES / "panel_coverage.csv").set_index("metric")["value"]
        self.qy = pd.read_csv(TABLES / "quality_by_year.csv")
        self.audit = _audit()

    def test_appearance_distribution_reconciles(self) -> None:
        rows = self.audit[self.audit.metric.str.match(r"ids_in_exactly_\d_years")]
        self.assertEqual(len(rows), 9)
        self.assertEqual(int(rows.value.sum()), int(self.cov["distinct_establishments"]))
        self.assertAlmostEqual(rows.share.sum(), 1.0, places=9)
        implied = _val(self.audit, "appearances", "filings_implied_by_year_distribution")
        self.assertEqual(int(implied.value), int(self.qy["n_filings"].sum()))
        self.assertAlmostEqual(implied.share, 1.0, places=12)

    def test_single_year_ids(self) -> None:
        one = _val(self.audit, "appearances", "ids_in_exactly_1_years")
        self.assertEqual(int(one.value), int(self.cov["establishments_in_exactly_1_years"]))
        self.assertEqual(int(one.value) + int(self.cov["establishments_in_2_or_more_years"]),
                         int(self.cov["distinct_establishments"]))

    def test_adjacent_links_bounded_by_filings(self) -> None:
        rows = self.audit[self.audit.section == "adjacent_year_linkage"]
        self.assertEqual(len(rows), 8)
        self.assertTrue(((rows.share > 0) & (rows.share < 1)).all())

    def test_drift_uses_multi_year_denominator(self) -> None:
        r = _val(self.audit, "identity_drift", "ids_with_more_than_one_ein",
                 "ids in 2+ years (only these can change)")
        self.assertAlmostEqual(
            r.share,
            self.cov["establishment_ids_with_multiple_ein"] / self.cov["establishments_in_2_or_more_years"],
        )

    def test_bounds_partition_flagged_filings(self) -> None:
        up = _val(self.audit, "correction_concentration", "flagged_filings_from_single_year_ids_at_most")
        lo = _val(self.audit, "correction_concentration", "flagged_filings_from_multi_year_ids_at_least")
        self.assertEqual(int(up.value) + int(lo.value), int(self.qy["n_implausible"].sum()))
        self.assertEqual(int(self.qy["n_implausible"].sum()), 57857)

    def test_2019_bound_matches_panel_2019(self) -> None:
        # 2019 flagged filers also present in 2018 / 2020 are committed in panel_2019.csv.
        p = pd.read_csv(TABLES / "panel_2019.csv").set_index("comparison")
        tr = pd.read_csv(TABLES / "panel_transitions.csv")
        tr = tr[tr.year_prev != "pooled"].astype({"year_prev": float, "year_curr": float})
        a = tr[(tr.year_prev == 2018) & (tr.year_curr == 2019)].iloc[0]
        b = tr[(tr.year_prev == 2019) & (tr.year_curr == 2020)].iloc[0]
        self.assertEqual(a.n11_flag_then_flag + a.n01_noflag_then_flag,
                         p.loc["2019_flagged_also_flagged_in_2018", "n_filers"])
        self.assertEqual(b.n11_flag_then_flag + b.n10_flag_then_noflag,
                         p.loc["2019_flagged_also_flagged_in_2020", "n_filers"])

    def test_flagged_hours_shares_sum_to_one(self) -> None:
        rows = self.audit[self.audit.metric.str.startswith("flagged_hours_in_")]
        self.assertEqual(len(rows), 9)
        self.assertAlmostEqual(rows.share.sum(), 1.0, places=6)
        self.assertEqual(int(_val(self.audit, "correction_concentration",
                                  "flagged_hours_in_2019").value) > 1e13, True)

    def test_pooled_ratio_is_29_7(self) -> None:
        r = _val(self.audit, "correction_concentration", "pooled_ratio_screened_to_unscreened")
        self.assertAlmostEqual(r.value, 29.7108, places=3)


class TestUnanswerableRowsStayEmpty(unittest.TestCase):
    def test_not_answerable_rows_have_no_value(self) -> None:
        rows = _audit()
        na = rows[rows.status == pa.NOT_ANSWERABLE]
        self.assertEqual(
            sorted(na.metric),
            ["correction_share_from_single_year_ids", "ids_changing_naics_between_years",
             "ids_changing_size_band_between_years"],
        )
        self.assertTrue(na.value.isna().all())
        self.assertTrue(na.share.isna().all())


if __name__ == "__main__":
    unittest.main()
