"""Check that the numbers written in README.md still match generated output.

A README is the part of a repository people actually read, and it is the part
most likely to drift: a bound changes, the pipeline is re-run, the tables update
and the prose quietly keeps its old figures. In a repository whose entire claim
is that published safety numbers go unchecked, that would be an unfortunate way
to fail.

These tests parse the headline figures back out of README.md and compare them
against ``outputs/summary.json`` and ``outputs/tables/*.csv``. They skip when the
pipeline has not been run, so a fresh clone still passes its suite; run
``python3 scripts/run_analysis.py`` to enable them.

Tolerances are set to the precision the README actually prints, so rounding in
the prose is fine and a real change is not.
"""

from __future__ import annotations

import json
import re
import unittest
from typing import Optional

import _context  # noqa: F401
import pandas as pd

README = _context.ROOT / "README.md"
OUT = _context.ROOT / "outputs"
SUMMARY = OUT / "summary.json"


def outputs_available() -> bool:
    """Return True if the pipeline has been run and wrote a summary."""
    return SUMMARY.exists()


def _readme_text() -> str:
    """Return the README contents."""
    return README.read_text(encoding="utf-8")


def _find_number(pattern: str, text: str, group: int = 1) -> Optional[float]:
    """Extract the first regex group as a float, stripping commas and percents.

    Searched with ``re.MULTILINE`` so ``^``/``$`` anchor to table rows rather
    than to the whole document.

    Args:
        pattern: Regular expression with at least one capturing group.
        text: Text to search.
        group: Which capturing group holds the number.

    Returns:
        The parsed float, or None if the pattern does not match.
    """
    m = re.search(pattern, text, flags=re.MULTILINE)
    if not m:
        return None
    return float(m.group(group).replace(",", "").replace("%", "").replace("*", ""))


@unittest.skipUnless(
    outputs_available(), "outputs/summary.json absent; run scripts/run_analysis.py"
)
class TestReadmeMatchesOutputs(unittest.TestCase):
    """Every headline figure in the README must match the generated outputs."""

    text: str
    summary: dict

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _readme_text()
        cls.summary = json.loads(SUMMARY.read_text(encoding="utf-8"))

    def test_filing_count_matches(self) -> None:
        pooled = self.summary["quality"]["pooled"]
        claimed = _find_number(r"Filings after deduplication \| ([\d,]+)", self.text)
        self.assertIsNotNone(claimed, "README headline table lost its filing count")
        self.assertEqual(int(claimed), pooled["n_filings"])

    def test_implausible_count_and_share_match(self) -> None:
        pooled = self.summary["quality"]["pooled"]
        n = _find_number(r"Flagged implausible \| ([\d,]+)", self.text)
        pct = _find_number(r"Flagged implausible \| [\d,]+ \(([\d.]+)%\)", self.text)
        self.assertIsNotNone(n)
        self.assertIsNotNone(pct)
        self.assertEqual(int(n), pooled["n_implausible"])
        self.assertAlmostEqual(pct / 100.0, pooled["implausible_share"], places=4)

    def test_hours_share_matches(self) -> None:
        pooled = self.summary["quality"]["pooled"]
        pct = _find_number(
            r"Share of all reported hours they hold \| ([\d.]+)%", self.text
        )
        self.assertIsNotNone(pct)
        self.assertAlmostEqual(pct / 100.0, pooled["hours_share_implausible"], places=4)

    def test_aggregate_trir_values_match(self) -> None:
        pooled = self.summary["quality"]["pooled"]
        un = _find_number(r"Aggregate TRIR, unscreened \| \*\*([\d.]+)\*\*", self.text)
        sc = _find_number(r"Aggregate TRIR, screened \| \*\*([\d.]+)\*\*", self.text)
        ratio = _find_number(r"\| Ratio \| \*\*([\d.]+)x\*\*", self.text)
        self.assertIsNotNone(un)
        self.assertIsNotNone(sc)
        self.assertIsNotNone(ratio)
        self.assertAlmostEqual(un, pooled["aggregate_trir_unscreened"], places=3)
        self.assertAlmostEqual(sc, pooled["aggregate_trir_screened"], places=3)
        self.assertAlmostEqual(ratio, pooled["ratio_screened_to_unscreened"], places=1)

    def test_per_year_table_matches_the_csv(self) -> None:
        by_year = pd.read_csv(OUT / "tables" / "quality_by_year.csv")
        rows = re.findall(
            r"^\| (20\d\d) \| ([\d,]+) \| ([\d.]+) \| ([\d.]+) \| "
            r"([\d.]+) \| ([\d.]+) \| ([\d.]+)x \|$",
            self.text,
            flags=re.MULTILINE,
        )
        self.assertEqual(
            len(rows), len(by_year), "README year table row count != quality_by_year.csv"
        )
        for year, n, pct_flag, pct_hours, un, sc, ratio in rows:
            src = by_year[by_year["label"].astype(float).astype(int) == int(year)]
            self.assertEqual(len(src), 1, f"no CSV row for {year}")
            r = src.iloc[0]
            self.assertEqual(int(n.replace(",", "")), int(r["n_filings"]), year)
            self.assertAlmostEqual(
                float(pct_flag) / 100.0, float(r["implausible_share"]), places=4, msg=year
            )
            self.assertAlmostEqual(
                float(pct_hours) / 100.0,
                float(r["hours_share_implausible"]),
                places=3,
                msg=year,
            )
            self.assertAlmostEqual(
                float(un), float(r["aggregate_trir_unscreened"]), places=2, msg=year
            )
            self.assertAlmostEqual(
                float(sc), float(r["aggregate_trir_screened"]), places=2, msg=year
            )
            self.assertAlmostEqual(
                float(ratio),
                float(r["ratio_screened_to_unscreened"]),
                delta=0.1,
                msg=year,
            )

    def test_sensitivity_range_matches(self) -> None:
        q = self.summary["quality"]
        lo = _find_number(r"screened aggregate TRIR stays within ([\d.]+)-", self.text)
        hi = _find_number(
            r"screened aggregate TRIR stays within [\d.]+-([\d.]+)", self.text
        )
        self.assertIsNotNone(lo)
        self.assertIsNotNone(hi)
        self.assertAlmostEqual(lo, q["sensitivity_min_corrected_trir"], places=2)
        self.assertAlmostEqual(hi, q["sensitivity_max_corrected_trir"], places=2)

    def test_top_filing_hours_share_matches(self) -> None:
        conc = pd.read_csv(OUT / "tables" / "quality_hours_concentration.csv")
        top1 = float(
            conc.loc[conc["top_n_filings_by_hours"] == 1, "hours_share"].iloc[0]
        )
        claimed = _find_number(r"holds ([\d.]+)% of all hours ever reported", self.text)
        self.assertIsNotNone(claimed, "README lost the single-filing concentration claim")
        self.assertAlmostEqual(claimed / 100.0, top1, places=3)

    def test_count_model_selection_counts_match(self) -> None:
        sel = pd.read_csv(OUT / "tables" / "count_model_selection_summary.csv")
        n_fitted = int(sel["n_industries_fitted"].iloc[0])
        claimed_fitted = _find_number(
            r"Industries best by AIC \(of (\d+)\)", self.text
        )
        self.assertIsNotNone(claimed_fitted)
        self.assertEqual(int(claimed_fitted), n_fitted)

        wins = dict(zip(sel["model"], sel["n_industries_best_by_aic"]))
        for label, key in [
            ("Poisson", "poisson"),
            ("ZIP", "zip"),
            ("NB2", "nb2"),
            ("ZINB", "zinb"),
        ]:
            claimed = _find_number(rf"^\| {label} \| (\d+) \|$", self.text)
            self.assertIsNotNone(claimed, f"README model table lost the {label} row")
            self.assertEqual(
                int(claimed), int(wins[key]), f"{label} win count disagrees"
            )

    def test_zinb_collapse_count_matches(self) -> None:
        claimed = _find_number(r"In (\d+) of the 30\s+industries the ZINB", self.text)
        self.assertIsNotNone(claimed, "README lost the ZINB collapse count")
        self.assertEqual(
            int(claimed), int(self.summary["count_models"]["zinb_pi_collapsed_to_zero"])
        )

    def test_sensitivity_flagged_share_range_matches(self) -> None:
        # This range was wrong in the README for one revision and no test
        # caught it, because only the corrected-TRIR range was checked.
        q = self.summary["quality"]
        lo = _find_number(r"it runs from ([\d.]+)% to [\d.]+% across", self.text)
        hi = _find_number(r"it runs from [\d.]+% to ([\d.]+)% across", self.text)
        self.assertIsNotNone(lo, "README lost the flagged-share sensitivity range")
        self.assertIsNotNone(hi)
        self.assertAlmostEqual(
            lo / 100.0, q["sensitivity_min_flagged_share"], places=4
        )
        self.assertAlmostEqual(
            hi / 100.0, q["sensitivity_max_flagged_share"], places=4
        )

    def test_zero_recordable_shares_match(self) -> None:
        z = self.summary["quality"]["zero_recordable_share"]
        overall = _find_number(
            r"Among plausible filings, ([\d.]+)% of all establishment-years", self.text
        )
        chem = _find_number(
            r"for NAICS 325 \(chemical\s+manufacturing\) it is ([\d.]+)%", self.text
        )
        first = _find_number(r"rising from\s+([\d.]+)% in 2016", self.text)
        last = _find_number(r"in 2016 to ([\d.]+)% in 2024", self.text)
        for value in (overall, chem, first, last):
            self.assertIsNotNone(value, "README lost a zero-recordable-share figure")
        self.assertAlmostEqual(overall / 100.0, z["all_industries_pooled"], places=3)
        self.assertAlmostEqual(chem / 100.0, z["naics325_pooled"], places=3)
        by_year = {int(r["year"]): r for r in z["by_year"]}
        self.assertAlmostEqual(first / 100.0, by_year[2016]["naics325"], places=3)
        self.assertAlmostEqual(last / 100.0, by_year[2024]["naics325"], places=3)

    def test_persistence_range_matches(self) -> None:
        pers = pd.read_csv(OUT / "tables" / "peer_group_persistence.csv")
        share = pers["matched_share_of_year_from"].astype(float)
        lo = _find_number(
            r"and\s+([\d.]+)-[\d.]+% of publishable cells persist", self.text
        )
        hi = _find_number(
            r"and\s+[\d.]+-([\d.]+)% of publishable cells persist", self.text
        )
        self.assertIsNotNone(lo, "README lost the cell-persistence range")
        self.assertIsNotNone(hi)
        self.assertAlmostEqual(lo / 100.0, float(share.min()), places=3)
        self.assertAlmostEqual(hi / 100.0, float(share.max()), places=3)

    def test_model_table_uses_official_naics_titles_not_the_data_field(self) -> None:
        # Integrity guard. The establishment-supplied ``industry_description``
        # names a 6-digit industry; using its modal value to label a 3-digit
        # subsector renamed NAICS 238 "Electrical contractors" in an earlier
        # revision of this README. Every subsector named in the model table
        # must match the official NAICS 2022 title.
        from ehs_osha.naics import naics3_title

        rows = re.findall(
            r"^\| (\d{3}) \| ([^|]+?) \| [\d,]+ \|", self.text, flags=re.MULTILINE
        )
        self.assertGreaterEqual(len(rows), 5, "README model example table not found")
        for code, label in rows:
            self.assertEqual(
                label.strip(),
                naics3_title(code),
                f"NAICS {code} is labelled {label.strip()!r} but the official "
                f"2022 subsector title is {naics3_title(code)!r}",
            )

    def test_model_tables_do_not_label_groups_with_the_free_text_field(self) -> None:
        comp = pd.read_csv(OUT / "tables" / "count_model_comparison.csv")
        self.assertIn("naics3_title", comp.columns)
        self.assertNotIn(
            "industry_description",
            comp.columns,
            "bare 'industry_description' reads as the group's name; it is the "
            "modal establishment-supplied 6-digit description and must be "
            "named as such",
        )
        self.assertIn("modal_establishment_industry_description", comp.columns)

    def test_readme_does_not_claim_to_reproduce_the_prior_multiplier(self) -> None:
        # Integrity guard. The prior repository reported 0.45 / 3.41 / 7.58x.
        # Those values are not reproduced here and the README must keep saying
        # so rather than quietly presenting them as this repository's result.
        self.assertIn("7.58x", self.text, "prior-work comparison was removed")
        self.assertRegex(
            self.text,
            r"not reproduced here",
            "README must state plainly that the prior figures were not reproduced",
        )


@unittest.skipUnless(
    outputs_available(), "outputs/summary.json absent; run scripts/run_analysis.py"
)
class TestReadmeTranscribedTables(unittest.TestCase):
    """The three README tables that are transcribed row-by-row from CSVs.

    These were previously described in the README as not individually checked.
    They are checked here, so that caveat no longer applies: every row printed
    in the README must match the generated CSV to the precision printed.
    """

    text: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _readme_text()

    def _row(self, label: str) -> list:
        """Return the cells of the README table row whose first cell is ``label``."""
        m = re.search(
            r"^\|\s*" + re.escape(label) + r"\s*\|(.+)\|\s*$",
            self.text,
            flags=re.MULTILINE,
        )
        self.assertIsNotNone(m, f"README row {label!r} not found")
        return [
            c.strip().replace("**", "").replace("%", "").replace(",", "")
            for c in m.group(1).split("|")
        ]

    def _assert_cell(self, cell: str, value: float, places: int, what: str) -> None:
        """Compare one README table cell to a computed value.

        ``~0`` is accepted in the README for a value that rounds to zero at the
        printed precision, and is checked as such rather than skipped.
        """
        if cell == "~0":
            self.assertLess(
                abs(value),
                0.5 * 10 ** (-places),
                f"README prints ~0 for the {what} but the CSV gives {value}",
            )
        else:
            self.assertAlmostEqual(
                float(cell),
                value,
                places=places,
                msg=f"README {what} does not match the CSV",
            )

    def test_flag_prevalence_rows_match_csv(self) -> None:
        d = pd.read_csv(OUT / "tables" / "quality_flag_prevalence.csv").set_index("flag")
        labels = {
            "hours per employee > 4,500": "flag_hours_per_employee_high",
            "hours per employee < 120": "flag_hours_per_employee_low",
            "employees missing or < 1": "flag_employees_missing",
            "hours missing or <= 0": "flag_hours_missing",
            '"no injuries" box contradicts case counts': "flag_no_injury_contradiction",
            "negative case count": "flag_negative_counts",
        }
        for label, flag in labels.items():
            cells = self._row(label)
            self.assertEqual(
                int(cells[0]),
                int(d.loc[flag, "n"]),
                f"README filing count for {label!r} does not match the CSV",
            )
            self._assert_cell(
                cells[1],
                100.0 * float(d.loc[flag, "share"]),
                places=3,
                what=f"filing share for {label!r}",
            )
            hours_share = 100.0 * float(d.loc[flag, "hours_share"])
            self._assert_cell(
                cells[2], hours_share, places=2, what=f"hours share for {label!r}"
            )

    def test_size_band_rows_match_csv(self) -> None:
        d = pd.read_csv(OUT / "tables" / "size_band_effects.csv")
        d["label"] = d["size_band"].str.replace(r"^0+", "", regex=True).str.replace(
            r"-0*", "-", regex=True
        )
        for _, r in d.iterrows():
            cells = self._row(r["label"])
            self.assertEqual(int(cells[0]), int(r["n"]), r["label"])
            self.assertAlmostEqual(float(cells[1]), float(r["zero_share"]), places=3)
            self.assertAlmostEqual(
                float(cells[2]), float(r["variance_to_mean_ratio"]), places=1
            )
            self.assertAlmostEqual(float(cells[3]), float(r["aggregate_trir"]), places=2)
            self.assertAlmostEqual(
                float(cells[4]), float(r["median_establishment_trir"]), places=2
            )

    def test_percentile_stability_rows_match_csv_and_omit_nothing(self) -> None:
        d = pd.read_csv(OUT / "tables" / "percentile_band_stability.csv")
        med = d.groupby("percentile")[["spearman_rho", "median_abs_rel_change"]].median()
        for pct, r in med.iterrows():
            cells = self._row(str(pct))
            self.assertAlmostEqual(
                float(cells[0]),
                float(r["spearman_rho"]),
                places=3,
                msg=f"README rho for {pct} does not match the CSV",
            )
            self.assertAlmostEqual(
                float(cells[1]),
                100.0 * float(r["median_abs_rel_change"]),
                places=1,
                msg=f"README relative change for {pct} does not match the CSV",
            )
        # Selective reporting guard: no percentile the pipeline computes may be
        # dropped from the README table.
        self.assertEqual(
            len(med),
            sum(1 for pct in med.index if re.search(r"^\|\s*" + str(pct) + r"\s*\|",
                                                    self.text, flags=re.MULTILINE)),
            "README stability table omits a percentile that the pipeline computes",
        )


@unittest.skipUnless(README.exists(), "README.md missing")
class TestReadmeHygiene(unittest.TestCase):
    """Cheap checks that do not need the pipeline to have been run."""

    def test_no_placeholder_text_left(self) -> None:
        text = _readme_text()
        for bad in ("TODO", "TBD", "FIXME", "XXX", "lorem ipsum"):
            self.assertNotIn(bad, text, f"placeholder {bad!r} left in README")

    def test_synthetic_data_is_disclosed_as_synthetic(self) -> None:
        # The fixture must never be presented as a finding.
        text = _readme_text()
        self.assertIn("synthetic", text.lower())
        self.assertRegex(
            text,
            r"[Nn]o number produced from the fixture appears anywhere in this README",
            "README must state that headline numbers are not from the fixture",
        )


if __name__ == "__main__":
    unittest.main()
