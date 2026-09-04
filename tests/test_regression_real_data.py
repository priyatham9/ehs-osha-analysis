"""Regression tests against the real OSHA ITA files.

These tests SKIP when ``data/raw`` does not hold the full catalog. They are the
guard on the empirical claims in the README: if a code change or an OSHA file
republish moves any headline number, one of these fails and names what moved.

Every expected value below was produced by running the pipeline in this
repository on the pinned file vintage recorded in ``src/ehs_osha/catalog.py``
(retrieved 2026-09-03). None was transcribed from any other source. Tolerances
are loose enough to survive floating-point and pandas-version differences and
tight enough that a genuine change in the data or the screen will fail.

Loading 2.8M rows takes roughly 25 s, so the frame is built once for the class.
"""

from __future__ import annotations

import unittest

import _context  # noqa: F401
import numpy as np
import pandas as pd

from ehs_osha.countmodels import compare_models, prepare_counts
from ehs_osha.load import load_ita_300a
from ehs_osha.peers import SIZE_BAND_LABELS, add_peer_keys
from ehs_osha.quality import (
    apply_screen,
    hours_concentration,
    sensitivity_grid,
    summarise_by,
    summarise_screen,
)

#: Values observed on the pinned vintage. See module docstring.
EXPECTED = {
    "rows_raw": 2_805_767,
    "rows_after_dedup": 2_801_064,
    "duplicate_rows_dropped": 4_703,
    "n_implausible": 57_857,
    "implausible_share": 0.020655,
    "hours_share_implausible": 0.966802,
    "aggregate_trir_unscreened": 0.134062,
    "aggregate_trir_screened": 3.983079,
    "ratio_screened_to_unscreened": 29.7108,
    "top1_hours_share": 0.888133,
    "naics325_zero_share": 0.3737,
    "years": list(range(2016, 2025)),
}


@unittest.skipUnless(
    _context.real_data_available(),
    "real OSHA files absent; run scripts/download_data.py to enable",
)
class TestRealDataRegression(unittest.TestCase):
    """Headline empirical results must be reproducible from the pinned files."""

    frame: pd.DataFrame
    screened: pd.DataFrame

    @classmethod
    def setUpClass(cls) -> None:
        cls.frame, cls.report = load_ita_300a(_context.DATA_RAW)
        cls.screened = apply_screen(cls.frame)

    def test_row_counts_and_dedup(self) -> None:
        self.assertEqual(self.report.rows_raw, EXPECTED["rows_raw"])
        self.assertEqual(self.report.rows_after_dedup, EXPECTED["rows_after_dedup"])
        self.assertEqual(
            self.report.duplicate_rows_dropped, EXPECTED["duplicate_rows_dropped"]
        )

    def test_years_present(self) -> None:
        years = sorted(int(v) for v in pd.unique(self.frame["year_filing_for"].dropna()))
        self.assertEqual(years, EXPECTED["years"])

    def test_cy2018_encoding_fallback_was_needed(self) -> None:
        # The 2018 file is not valid UTF-8. If this stops being true, the
        # encoding-fallback code path is no longer exercised by the real data
        # and the schema note should be revisited.
        used = {k: v for k, v in self.report.encodings_used.items() if "2018" in k}
        self.assertTrue(used, "no 2018 file was read")
        self.assertTrue(
            any(v != "utf-8" for v in used.values()),
            f"expected a non-UTF-8 encoding for the 2018 file, got {used}",
        )

    def test_plausibility_screen_headline_numbers(self) -> None:
        s = summarise_screen(self.screened)
        self.assertEqual(s.n_filings, EXPECTED["rows_after_dedup"])
        self.assertEqual(s.n_implausible, EXPECTED["n_implausible"])
        self.assertAlmostEqual(
            s.implausible_share, EXPECTED["implausible_share"], places=5
        )
        self.assertAlmostEqual(
            s.hours_share_implausible, EXPECTED["hours_share_implausible"], places=5
        )
        self.assertAlmostEqual(
            s.aggregate_trir_unscreened,
            EXPECTED["aggregate_trir_unscreened"],
            places=5,
        )
        self.assertAlmostEqual(
            s.aggregate_trir_screened, EXPECTED["aggregate_trir_screened"], places=4
        )
        self.assertAlmostEqual(
            s.ratio_screened_to_unscreened,
            EXPECTED["ratio_screened_to_unscreened"],
            places=2,
        )

    def test_the_structural_claim_holds_in_every_year(self) -> None:
        # This is the claim the README makes, stated as a test: in every
        # reporting year a small minority of filings is flagged, and removing
        # them raises the aggregate rate.
        by_year = summarise_by(self.screened, "year_filing_for")
        self.assertEqual(len(by_year), 9)
        for _, row in by_year.iterrows():
            year = row["label"]
            self.assertLess(row["implausible_share"], 0.05, f"{year}: screen too broad")
            self.assertGreater(
                row["implausible_share"], 0.005, f"{year}: screen fired on almost nothing"
            )
            self.assertGreater(
                row["aggregate_trir_screened"],
                row["aggregate_trir_unscreened"],
                f"{year}: screening did not raise the aggregate rate",
            )
            self.assertTrue(
                3.0 <= row["aggregate_trir_screened"] <= 5.0,
                f"{year}: screened aggregate TRIR {row['aggregate_trir_screened']:.3f} "
                f"outside the plausible 3-5 band",
            )

    def test_the_error_magnitude_is_not_a_stable_constant(self) -> None:
        # The point of the year-by-year table: the size of the aggregate error
        # is dominated by a handful of extreme filings, so it is not a fixed
        # multiplier. This asserts that instability explicitly.
        by_year = summarise_by(self.screened, "year_filing_for")
        ratios = by_year["ratio_screened_to_unscreened"].to_numpy(dtype="float64")
        self.assertLess(float(ratios.min()), 2.0)
        self.assertGreater(float(ratios.max()), 20.0)

    def test_a_single_filing_dominates_the_national_denominator(self) -> None:
        conc = hours_concentration(self.frame, top_ns=(1, 10, 100))
        top1 = float(conc.loc[conc["top_n_filings_by_hours"] == 1, "hours_share"].iloc[0])
        self.assertAlmostEqual(top1, EXPECTED["top1_hours_share"], places=4)
        top1_cases = float(
            conc.loc[conc["top_n_filings_by_hours"] == 1, "cases_share"].iloc[0]
        )
        self.assertLess(top1_cases, 1e-6)

    def test_conclusion_is_robust_to_the_screen_bounds(self) -> None:
        grid = sensitivity_grid(self.frame)
        self.assertGreater(len(grid), 10)
        corrected = grid["aggregate_trir_screened"].to_numpy(dtype="float64")
        self.assertTrue(
            np.all((corrected > 3.5) & (corrected < 4.5)),
            f"corrected TRIR ranged {corrected.min():.3f}-{corrected.max():.3f} "
            f"across the bounds grid; the result is more bound-sensitive than "
            f"the README claims",
        )
        self.assertTrue(np.all(grid["implausible_share"] < 0.05))

    def test_naics325_zero_share(self) -> None:
        clean = self.screened[~self.screened["implausible"]]
        sub = clean[clean["naics3"] == "325"]
        self.assertGreater(len(sub), 40_000)
        zero_share = float(np.mean(sub["recordable_cases"].to_numpy() == 0))
        self.assertAlmostEqual(zero_share, EXPECTED["naics325_zero_share"], places=3)

    def test_zero_share_falls_monotonically_with_size(self) -> None:
        keyed = add_peer_keys(self.screened)
        clean = keyed[~keyed["implausible"]]
        order = ["001-019", "020-049", "050-099", "100-249", "250-499"]
        shares = [
            float(np.mean(clean.loc[clean["size_band"] == b, "recordable_cases"] == 0))
            for b in order
        ]
        for a, b in zip(shares[:-1], shares[1:]):
            self.assertGreater(a, b, f"zero share not decreasing across {order}: {shares}")

    def test_size_field_is_not_comparable_across_years(self) -> None:
        # Schema trap: codes 21 and 22 appear only from 2022/2023. OSHA's
        # summary data dictionary documents them and records that code 2 was
        # split into 21 and 22 with the 2023 collection; the point of this test
        # is that the codes still coexist in a pooled panel, which is why
        # peers.py refuses to group on `size`.
        early = self.frame[self.frame["year_filing_for"] <= 2021]["size"]
        late = self.frame[self.frame["year_filing_for"] >= 2023]["size"]
        self.assertNotIn(21.0, set(pd.unique(early.dropna())))
        self.assertIn(21.0, set(pd.unique(late.dropna())))

    def test_size_codes_match_the_split_osha_documents(self) -> None:
        # OSHA documents 1 = <20, 2 = 20-249, 21 = 20-99, 22 = 100-249,
        # 3 = 250+. If the median employee counts stopped bracketing those
        # ranges, either the file changed or the documented reading is wrong,
        # and the README paragraph describing the split would need revisiting.
        size = pd.to_numeric(self.frame["size"], errors="coerce")
        emp = self.frame["annual_average_employees"]
        medians = {
            code: float(np.nanmedian(emp[size == code].to_numpy(dtype="float64")))
            for code in (1.0, 2.0, 3.0, 21.0, 22.0)
        }
        self.assertLess(medians[1.0], 20)
        self.assertTrue(20 <= medians[2.0] <= 249, medians)
        self.assertTrue(20 <= medians[21.0] <= 99, medians)
        self.assertTrue(100 <= medians[22.0] <= 249, medians)
        self.assertGreaterEqual(medians[3.0], 250)

    def test_no_injury_checkbox_coding_matches_the_published_dictionary(self) -> None:
        # OSHA's summary data dictionary: 1 = the establishment had injuries or
        # illnesses, 2 = it did not. Under that reading the contradiction rate
        # is tiny; under the reverse reading it would be the overwhelming
        # majority of filings. This test pins the direction so no future edit
        # can quietly reverse it.
        nii = pd.to_numeric(
            self.screened["no_injuries_illnesses"], errors="coerce"
        ).to_numpy(dtype="float64")
        rec = self.screened["recordable_cases"].to_numpy(dtype="float64")
        documented = int(np.sum(((nii == 2) & (rec > 0)) | ((nii == 1) & (rec == 0))))
        reversed_ = int(np.sum(((nii == 1) & (rec > 0)) | ((nii == 2) & (rec == 0))))
        self.assertLess(documented, reversed_ / 100)

    def test_no_injury_checkbox_agrees_with_case_counts_almost_always(self) -> None:
        contradictions = int(self.screened["flag_no_injury_contradiction"].sum())
        self.assertLess(contradictions / len(self.screened), 1e-3)
        self.assertGreater(contradictions, 0)

    def test_recordable_counts_are_overdispersed_in_every_large_industry(self) -> None:
        # The distributional claim the README makes. Poisson assumes
        # variance == mean; if that held anywhere, a Poisson model would
        # sometimes win on AIC. Across the largest industries it never does,
        # and the variance-to-mean ratio is far above 1 everywhere.
        keyed = add_peer_keys(self.screened)
        base = keyed[(~keyed["implausible"]) & (keyed["year_filing_for"] == 2024)]
        top = base["naics3"].value_counts()
        industries = [c for c in top[top >= 500].index[:8]]
        self.assertEqual(len(industries), 8)

        winners = []
        for naics in industries:
            sub = base[base["naics3"] == naics]
            y = sub["recordable_cases"].to_numpy(dtype="float64", na_value=np.nan)
            e = sub["total_hours_worked"].to_numpy(
                dtype="float64", na_value=np.nan
            ) / 200_000.0
            fits, _ = compare_models(y, e)
            yv, _ = prepare_counts(y, e)
            ratio = float(np.var(yv) / np.mean(yv))
            self.assertGreater(
                ratio, 2.0, f"NAICS {naics}: variance/mean {ratio:.2f} not overdispersed"
            )
            winners.append(min(fits, key=lambda f: f.aic).model)

        self.assertNotIn(
            "poisson", winners, f"Poisson won somewhere; winners were {winners}"
        )
        self.assertNotIn("zip", winners, f"ZIP won somewhere; winners were {winners}")
        self.assertTrue(
            set(winners) <= {"nb2", "zinb"}, f"unexpected winners: {winners}"
        )

    def test_zero_inflation_is_optional_but_overdispersion_is_not(self) -> None:
        # Where ZINB is selected the extra zero-inflation mass is small, and
        # where it is not selected the parameter collapses to the boundary.
        # Either way the negative-binomial dispersion term is doing the work.
        keyed = add_peer_keys(self.screened)
        base = keyed[(~keyed["implausible"]) & (keyed["year_filing_for"] == 2024)]
        top = base["naics3"].value_counts()
        collapsed = 0
        fitted = 0
        for naics in top[top >= 500].index[:8]:
            sub = base[base["naics3"] == naics]
            y = sub["recordable_cases"].to_numpy(dtype="float64", na_value=np.nan)
            e = sub["total_hours_worked"].to_numpy(
                dtype="float64", na_value=np.nan
            ) / 200_000.0
            fits, _ = compare_models(y, e)
            zinb = next(f for f in fits if f.model == "zinb")
            nb2 = next(f for f in fits if f.model == "nb2")
            self.assertGreater(
                nb2.params["alpha"], 0.01, f"NAICS {naics}: NB2 dispersion ~0"
            )
            pi = float(zinb.params["pi"])
            self.assertTrue(0.0 <= pi < 0.5, f"NAICS {naics}: implausible pi {pi}")
            fitted += 1
            if pi < 1e-6:
                collapsed += 1
        self.assertGreater(fitted, 0)
        self.assertGreater(
            collapsed, 0, "expected ZINB to collapse to NB2 in at least one industry"
        )

    def test_size_band_effects_are_ordered_by_band_not_alphabetically(self) -> None:
        # Guards the ordering bug where a lexical sort places "1000+" between
        # "100-249" and "250-499" and destroys the monotonic zero-share story.
        keyed = add_peer_keys(self.screened)
        clean = keyed[~keyed["implausible"]]
        present = [b for b in SIZE_BAND_LABELS if (clean["size_band"] == b).any()]
        self.assertEqual(present[0], "001-019")
        self.assertEqual(present[-1], "1000+")
        shares = [
            float(np.mean(clean.loc[clean["size_band"] == b, "recordable_cases"] == 0))
            for b in present
        ]
        self.assertGreater(shares[0], 0.5)
        self.assertLess(shares[-1], 0.2)


if __name__ == "__main__":
    unittest.main()
