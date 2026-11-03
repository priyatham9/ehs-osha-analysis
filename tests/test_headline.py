"""outputs/headline.json is the one canonical set of headline numbers.

These tests check that it is current with the committed pipeline outputs and
that README.md quotes it, including the figures with the single largest filing
left out.
"""

from __future__ import annotations

import importlib.util
import json
import unittest

import _context

SCRIPT = _context.ROOT / "scripts" / "build_headline.py"
HEADLINE = _context.ROOT / "outputs" / "headline.json"
SUMMARY = _context.ROOT / "outputs" / "summary.json"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_headline", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(SUMMARY.exists(), "pipeline outputs not present")
class HeadlineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_builder()
        cls.built = cls.mod.build()
        cls.committed = json.loads(HEADLINE.read_text(encoding="utf-8"))

    def test_committed_file_is_current(self):
        self.assertEqual(self.mod.render(self.built), HEADLINE.read_text(encoding="utf-8"),
                         "run python3 scripts/build_headline.py")

    def test_headline_matches_summary(self):
        p = json.loads(SUMMARY.read_text(encoding="utf-8"))["quality"]["pooled"]
        h = self.built["headline"]
        self.assertEqual(h["n_filings"], p["n_filings"])
        self.assertAlmostEqual(h["hours_share_flagged_pct"], 100 * p["hours_share_implausible"], places=2)
        self.assertAlmostEqual(h["trir_unscreened"], p["aggregate_trir_unscreened"], places=3)
        self.assertAlmostEqual(h["trir_screened"], p["aggregate_trir_screened"], places=3)
        self.assertAlmostEqual(h["ratio"], p["ratio_screened_to_unscreened"], places=1)

    def test_excluding_largest_filing_is_consistent(self):
        h, x = self.built["headline"], self.built["excluding_largest_filing"]
        self.assertEqual(x["n_filings"], h["n_filings"] - 1)
        self.assertEqual(x["trir_screened"], h["trir_screened"])
        self.assertLess(x["hours_share_flagged_pct"], h["hours_share_flagged_pct"])
        self.assertGreater(x["trir_unscreened"], h["trir_unscreened"])

    def test_readme_quotes_both_versions(self):
        readme = (_context.ROOT / "README.md").read_text(encoding="utf-8")
        h, x = self.committed["headline"], self.committed["excluding_largest_filing"]
        for s in (f"{h['hours_share_flagged_pct']:.2f}%", f"{h['ratio']:.1f}x",
                  f"{x['hours_share_flagged_pct']:.2f}%", f"{x['ratio']:.2f}x", f"{x['trir_unscreened']:.3f}"):
            self.assertIn(s, readme)


if __name__ == "__main__":
    unittest.main()
