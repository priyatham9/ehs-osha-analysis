"""End-to-end pipeline test on the SYNTHETIC fixture.

This exercises every stage of the pipeline without a network connection. The
numbers it produces are properties of ``synthetic/generate_fixture.py`` and are
not findings about anything. What is being tested is that the code runs, writes
what it says it writes, and recovers the generator's known parameters.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import _context  # noqa: F401
import numpy as np

from ehs_osha.catalog import DatasetFile
from ehs_osha.pipeline import PipelineConfig, run_pipeline
from ehs_osha.quality import PlausibilityConfig


def fixture_specs() -> list[DatasetFile]:
    """Build catalog entries pointing at the synthetic fixture CSVs."""
    specs = []
    for p in sorted(_context.FIXTURE.glob("SYNTHETIC_ITA_300A_*.csv")):
        year = int(p.stem.split("_")[-1])
        specs.append(
            DatasetFile(
                key=f"synthetic_{year}",
                calendar_year=year,
                url="file://SYNTHETIC-NOT-A-REAL-SOURCE",
                local_name=p.name,
                note="SYNTHETIC FIXTURE. Not real data.",
            )
        )
    return specs


@unittest.skipUnless(
    _context.fixture_available(),
    "run `python synthetic/generate_fixture.py` to enable",
)
class TestPipelineOnFixture(unittest.TestCase):
    """The pipeline must run start to finish and write every artefact."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        out = Path(cls.tmp.name)
        cfg = PipelineConfig(
            data_dir=_context.FIXTURE,
            out_dir=out,
            plausibility=PlausibilityConfig(),
            min_group_n=20,
            model_naics3=("325",),
            model_year=2024,
        )
        # Monkey-free: pass the fixture specs through the pipeline's loader by
        # temporarily substituting the catalog list used by load_ita_300a.
        import ehs_osha.load as load_mod

        original = load_mod.all_files
        load_mod.all_files = lambda include_partial=False: fixture_specs()
        try:
            cls.summary = run_pipeline(cfg, verbose=False)
        finally:
            load_mod.all_files = original
        cls.out = out

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_summary_written_and_parseable(self) -> None:
        payload = json.loads((self.out / "summary.json").read_text())
        self.assertIn("quality", payload)
        self.assertIn("count_models", payload)
        self.assertGreater(payload["quality"]["pooled"]["n_filings"], 1000)

    def test_all_expected_tables_exist_and_are_non_empty(self) -> None:
        expected = [
            "quality_overall",
            "quality_by_year",
            "quality_by_naics2",
            "quality_flag_prevalence",
            "quality_sensitivity_grid",
            "quality_hours_concentration",
            "quality_top50_implausible_hours",
            "peer_percentiles_by_year",
            "peer_percentiles_pooled",
            "size_band_effects",
            "count_model_comparison",
            "count_model_fit_detail",
            "percentile_band_stability",
            "peer_group_persistence",
        ]
        for name in expected:
            p = self.out / "tables" / f"{name}.csv"
            self.assertTrue(p.exists(), f"missing table {name}")
            self.assertGreater(p.stat().st_size, 0, f"empty table {name}")

    def test_figures_are_written_and_are_valid_xml(self) -> None:
        import xml.dom.minidom

        figs = sorted((self.out / "figures").glob("*.svg"))
        self.assertGreaterEqual(len(figs), 5)
        for f in figs:
            xml.dom.minidom.parse(str(f))

    def test_screen_recovers_the_injected_corruption_rate(self) -> None:
        truth = json.loads((_context.FIXTURE / "GROUND_TRUTH.json").read_text())
        injected = truth["parameters"]["implausible_share"]
        observed = self.summary["quality"]["pooled"]["implausible_share"]
        # Not every 10x multiplier pushes a filing past the 4,500 h/employee
        # bound, so the screen should catch most but not necessarily all.
        self.assertGreater(observed, injected * 0.5)
        self.assertLess(observed, injected * 1.5)

    def test_screened_rate_recovers_the_generator_rate(self) -> None:
        truth = json.loads((_context.FIXTURE / "GROUND_TRUTH.json").read_text())
        mu = truth["parameters"]["mu"]
        pi = truth["parameters"]["pi"]
        # The marginal mean rate is mu * (1 - pi), plus a small upward drift the
        # generator applies across years.
        expected = mu * (1 - pi)
        screened = self.summary["quality"]["pooled"]["aggregate_trir_screened"]
        self.assertAlmostEqual(screened, expected, delta=0.35 * expected)
        naive = self.summary["quality"]["pooled"]["aggregate_trir_unscreened"]
        self.assertLess(naive, screened)

    def test_count_models_recover_the_generator_parameters(self) -> None:
        import pandas as pd

        truth = json.loads((_context.FIXTURE / "GROUND_TRUTH.json").read_text())[
            "parameters"
        ]
        table = pd.read_csv(self.out / "tables" / "count_model_comparison.csv")
        zinb = table[table["model"] == "zinb"]
        self.assertEqual(len(zinb), 1)
        params = eval(zinb["params"].iloc[0])  # noqa: S307 - our own serialised dict
        self.assertAlmostEqual(params["alpha"], truth["alpha"], delta=0.6)
        self.assertAlmostEqual(params["pi"], truth["pi"], delta=0.12)
        self.assertTrue(bool(zinb["converged"].iloc[0]))

    def test_zero_inflated_generator_is_detected(self) -> None:
        import pandas as pd

        table = pd.read_csv(self.out / "tables" / "count_model_comparison.csv")
        best = table[table["is_best_by_aic"]]["model"].iloc[0]
        self.assertIn(best, {"zinb", "nb2"})
        poisson_aic = float(table[table["model"] == "poisson"]["aic"].iloc[0])
        best_aic = float(table[table["is_best_by_aic"]]["aic"].iloc[0])
        self.assertLess(best_aic, poisson_aic)

    def test_outputs_are_reproducible_across_runs(self) -> None:
        import pandas as pd

        with tempfile.TemporaryDirectory() as td:
            cfg = PipelineConfig(
                data_dir=_context.FIXTURE,
                out_dir=Path(td),
                min_group_n=20,
                model_naics3=("325",),
                model_year=2024,
            )
            import ehs_osha.load as load_mod

            original = load_mod.all_files
            load_mod.all_files = lambda include_partial=False: fixture_specs()
            try:
                run_pipeline(cfg, verbose=False)
            finally:
                load_mod.all_files = original
            a = pd.read_csv(self.out / "tables" / "quality_by_year.csv")
            b = pd.read_csv(Path(td) / "tables" / "quality_by_year.csv")
        pd.testing.assert_frame_equal(a, b)


if __name__ == "__main__":
    unittest.main()


class TestFixtureIsNotStale(unittest.TestCase):
    """The committed fixture must match what the generator produces today.

    A fixture is checked in so the suite runs offline, which creates a way for
    it to rot: change the generator's defaults and the committed files keep
    testing the old behaviour, and `GROUND_TRUTH.json` starts describing
    parameters that no longer produced the data beside it. That happened once
    (the committed files were generated with n=2500 while the default had moved
    to 3000), so it is now asserted.
    """

    @unittest.skipUnless(_context.fixture_available(), "fixture not generated")
    def test_committed_fixture_matches_a_fresh_generation(self) -> None:
        import hashlib
        import json
        import sys

        sys.path.insert(0, str(_context.ROOT / "synthetic"))
        from generate_fixture import GeneratorParams, write_fixture  # type: ignore

        committed_truth = json.loads(
            (_context.FIXTURE / "GROUND_TRUTH.json").read_text(encoding="utf-8")
        )
        params = GeneratorParams(**committed_truth["parameters"])

        with tempfile.TemporaryDirectory() as td:
            write_fixture(Path(td), params)
            for fresh in sorted(Path(td).glob("SYNTHETIC_ITA_300A_*.csv")):
                committed = _context.FIXTURE / fresh.name
                self.assertTrue(committed.exists(), f"{fresh.name} missing from fixture")
                # Byte equality is not portable: pandas and numpy change float
                # formatting between versions, so the same generator run emits
                # different bytes on a different interpreter. The property that
                # actually matters is that the committed rows are the rows the
                # generator produces today, so compare parsed content.
                import csv as _csv

                def _rows(path):
                    with open(path, newline="", encoding="utf-8") as fh:
                        return [
                            {k: _norm(v) for k, v in row.items()}
                            for row in _csv.DictReader(fh)
                        ]

                def _norm(v):
                    try:
                        return round(float(v), 6)
                    except (TypeError, ValueError):
                        return v

                self.assertEqual(
                    _rows(committed),
                    _rows(fresh),
                    f"{fresh.name} is stale; re-run synthetic/generate_fixture.py",
                )

    @unittest.skipUnless(_context.fixture_available(), "fixture not generated")
    def test_every_fixture_csv_has_a_synthetic_declaration(self) -> None:
        csvs = sorted(_context.FIXTURE.glob("SYNTHETIC_ITA_300A_*.csv"))
        self.assertTrue(csvs, "no fixture CSVs found")
        for path in csvs:
            sidecar = path.parent / (path.stem + ".HEADER.txt")
            self.assertTrue(sidecar.exists(), f"{path.name} has no .HEADER.txt")
            text = sidecar.read_text(encoding="utf-8").upper()
            self.assertIn("SYNTHETIC", text)
            self.assertIn("NOT REAL OSHA", text)
            # The rows must also be self-identifying, so a stray CSV that gets
            # separated from its sidecar still cannot be mistaken for real data.
            body = path.read_text(encoding="utf-8")[:4000].upper()
            self.assertIn("SYNTHETIC", body)
