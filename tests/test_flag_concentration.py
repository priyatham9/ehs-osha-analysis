"""Tests for the flag-concentration analysis (scripts/build_flag_concentration.py).

Headline numbers are recomputed here from the committed CSV outputs by an
independent route and compared with the doc text; generated files must match
what the script writes.
"""

from __future__ import annotations

import importlib.util
import re
import unittest

import _context  # noqa: F401
import pandas as pd

ROOT = _context.ROOT
spec = importlib.util.spec_from_file_location("build_flag_concentration", ROOT / "scripts" / "build_flag_concentration.py")
fc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fc)


class TestDrift(unittest.TestCase):
    def test_committed_files_match_script(self) -> None:
        for path, text in fc.outputs().items():
            self.assertTrue(path.exists(), path)
            self.assertEqual(path.read_text(encoding="utf-8"), text, f"{path.name} drifted; rerun the script")


class TestHeadlineNumbers(unittest.TestCase):
    def setUp(self) -> None:
        self.sec = pd.read_csv(ROOT / "outputs" / "flag_concentration_sectors.csv", dtype={"naics2": str})
        self.summary = pd.read_csv(ROOT / "outputs" / "flag_concentration_summary.csv").set_index("metric")["value"]
        self.doc = (ROOT / "docs" / "flag_concentration.md").read_text(encoding="utf-8")

    def test_counts_tie_to_source_table(self) -> None:
        src = pd.read_csv(ROOT / "outputs" / "tables" / "quality_by_naics2.csv", dtype={"label": str})
        src = src[src["label"].isin(self.sec["naics2"])]
        self.assertEqual(int(src["n_filings"].sum()), int(self.sec["n_filings"].sum()))
        self.assertEqual(int(src["n_implausible"].sum()), int(self.sec["n_flagged"].sum()))
        self.assertEqual(len(self.sec), 24)
        self.assertAlmostEqual(self.sec["share_of_flagged"].sum(), 1.0, places=7)

    def test_gini_recomputed_from_sector_csv(self) -> None:
        s = self.sec.assign(rate=self.sec["n_flagged"] / self.sec["n_filings"]).sort_values("rate")
        fx = s["n_filings"].cumsum() / s["n_filings"].sum()
        fy = s["n_flagged"].cumsum() / s["n_flagged"].sum()
        px, py = 0.0, 0.0
        area = 0.0
        for x, y in zip(fx, fy):
            area += (x - px) * (y + py) / 2
            px, py = x, y
        self.assertAlmostEqual(1 - 2 * area, self.summary["gini_flagged_filings"], places=8)

    def test_top5_share_and_interval_bracket(self) -> None:
        top = self.sec.assign(rate=self.sec["n_flagged"] / self.sec["n_filings"]).nlargest(5, "rate")
        share = top["n_flagged"].sum() / self.sec["n_flagged"].sum()
        self.assertAlmostEqual(share, self.summary["top5_rate_sectors_share_of_flagged"], places=8)
        self.assertLess(self.summary["top5_rate_sectors_share_of_flagged_cp_lo"], share)
        self.assertGreater(self.summary["top5_rate_sectors_share_of_flagged_cp_hi"], share)

    def test_bootstrap_interval_brackets_point(self) -> None:
        g = self.summary["gini_flagged_filings"]
        self.assertLess(self.summary["gini_flagged_filings_boot_lo"], g)
        self.assertGreater(self.summary["gini_flagged_filings_boot_hi"], g)

    def test_doc_quotes_csv_numbers(self) -> None:
        g = self.summary["gini_flagged_filings"]
        self.assertIn(f"**{g:.3f}**", self.doc)
        self.assertIn(f"{100 * self.summary['top5_rate_sectors_share_of_flagged']:.2f}%", self.doc)
        self.assertIn(f"{100 * self.summary['top1_flagged_hours_sector_share']:.1f}% of flagged hours alone", self.doc)
        self.assertIn("## Limitations", self.doc)
        self.assertIn("## Choice of analysis", self.doc)
        self.assertTrue(re.search(r"flag_concentration\.svg", self.doc))


class TestClopperPearson(unittest.TestCase):
    def test_known_values(self) -> None:
        lo, hi = fc.clopper_pearson(0, 10)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 1 - 0.025 ** (1 / 10), places=6)
        lo, hi = fc.clopper_pearson(5, 10)
        self.assertAlmostEqual(lo, 0.187086, places=5)
        self.assertAlmostEqual(hi, 0.812914, places=5)


if __name__ == "__main__":
    unittest.main()
