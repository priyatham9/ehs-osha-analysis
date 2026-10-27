"""Tests for data expectations as code and the lineage spec.

The committed outputs must satisfy every expectation, the generated documents
must match what the generators render, and deliberately corrupted copies of the
tables (in a temp dir; the committed files are never touched) must make the
relevant expectations fail.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import _context  # noqa: F401
import pandas as pd

from ehs_osha.health import expectations as ex
from ehs_osha.health import lineage as lin

TABLES = _context.ROOT / "outputs" / "tables"
SUMMARY = _context.ROOT / "outputs" / "summary.json"
HAVE_OUTPUTS = TABLES.exists() and SUMMARY.exists()


def _main(args):
    """Run the CLI with its progress output suppressed."""
    with contextlib.redirect_stdout(io.StringIO()):
        return ex.main(args)


def _status(results, eid):
    return next(r for r in results if r.id == eid).status


class TestLineage(unittest.TestCase):
    def test_committed_lineage_is_valid(self) -> None:
        self.assertEqual(lin.validate(lin.load_spec()), [])

    def test_lineage_doc_is_up_to_date(self) -> None:
        self.assertEqual(lin.DOC.read_text(encoding="utf-8"), lin.build())

    def test_doc_has_mermaid_graph_and_every_stage(self) -> None:
        spec = lin.load_spec()
        doc = lin.build()
        self.assertIn("```mermaid", doc)
        for st in spec["stages"]:
            self.assertIn(f'S_{st["id"]}("{st["title"]}")', doc)

    def test_every_pipeline_stage_function_is_declared(self) -> None:
        declared = {(s.get("module"), s["function"]) for s in lin.load_spec()["stages"]}
        for fn in ("stage_quality", "stage_peers", "stage_count_models", "stage_stability",
                   "stage_metrics", "stage_count_models_covariates", "stage_reconcile"):
            self.assertIn(("ehs_osha.pipeline", fn), declared)

    def test_validator_catches_problems(self) -> None:
        def mutated(fn):
            spec = lin.load_spec()
            fn(spec)
            return lin.validate(spec)

        cases = {
            "function not defined": lambda s: s["stages"][2].update(function="no_such_function"),
            "module missing": lambda s: s["stages"][2].update(module="ehs_osha.no_such_module"),
            "undeclared artifact": lambda s: s["stages"][2]["inputs"].append("ghost"),
            "missing path": lambda s: s["artifacts"]["summary_json"]["paths"].append("outputs/nope.json"),
            "undeclared table": lambda s: s["artifacts"]["quality_tables"]["paths"].pop(),
            "double producer": lambda s: s["stages"][3]["outputs"].append("harmonised"),
            "cycle": lambda s: s["stages"][2]["inputs"].append("screened"),
        }
        for name, fn in cases.items():
            with self.subTest(name):
                self.assertTrue(mutated(fn), f"{name} was not detected")


class TestSpec(unittest.TestCase):
    def test_spec_loads_and_is_documented(self) -> None:
        spec = ex.load_spec()
        self.assertGreaterEqual(len(spec), 100)
        for e in spec:
            self.assertTrue(e["rationale"].strip(), e["id"])
            self.assertTrue(e["id"].startswith(e["target"] + "."), e["id"])

    def test_no_em_dashes_in_generated_text(self) -> None:
        for p in (ex.DOC, lin.DOC, ex.SPEC, lin.SPEC):
            self.assertNotIn("—", p.read_text(encoding="utf-8"), p.name)

    def test_every_committed_table_has_expectations(self) -> None:
        targets = {e["target"] for e in ex.load_spec()}
        for csv in TABLES.glob("*.csv"):
            self.assertIn(csv.stem, targets, f"no expectations for {csv.name}")


@unittest.skipUnless(HAVE_OUTPUTS, "committed outputs absent")
class TestCommittedOutputs(unittest.TestCase):
    def test_all_expectations_pass_on_committed_outputs(self) -> None:
        results = ex.run_expectations(TABLES, SUMMARY)
        bad = [(r.id, r.observed) for r in results if r.status != "pass"]
        self.assertEqual(bad, [])

    def test_health_doc_is_up_to_date(self) -> None:
        spec = ex.load_spec()
        doc = ex.render(ex.run_expectations(TABLES, SUMMARY, spec), spec)
        self.assertEqual(ex.DOC.read_text(encoding="utf-8"), doc)

    def test_cli_exits_zero_on_committed_outputs(self) -> None:
        self.assertEqual(_main(["--doc", ""]), 0)

    def test_headline_reconciliation_uses_summary(self) -> None:
        total = int(pd.read_csv(TABLES / "quality_by_naics2.csv")["n_filings"].sum())
        pooled = json.loads(SUMMARY.read_text())["quality"]["pooled"]["n_filings"]
        self.assertEqual(total, pooled)


@unittest.skipUnless(HAVE_OUTPUTS, "committed outputs absent")
class TestCorruptedCopies(unittest.TestCase):
    """Each mutation, applied to a temp copy, must fail the named expectation."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.tables = self.root / "tables"
        shutil.copytree(TABLES, self.tables)
        self.summary = self.root / "summary.json"
        shutil.copy(SUMMARY, self.summary)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def edit(self, name, fn) -> None:
        p = self.tables / f"{name}.csv"
        df = pd.read_csv(p)
        fn(df)
        df.to_csv(p, index=False)

    def results(self):
        return ex.run_expectations(self.tables, self.summary)

    def test_clean_copy_passes(self) -> None:
        self.assertTrue(all(r.status == "pass" for r in self.results()))

    def test_corruptions_are_detected(self) -> None:
        def drop_row(df): df.drop(df.index[5], inplace=True)
        def share_over_one(df): df.loc[0, "implausible_share"] = 1.5
        def bad_year(df): df.loc[0, "label"] = 2015
        def drop_col(df): df.drop(columns=["n_implausible"], inplace=True)
        def null_key(df): df.loc[1, "n_filings"] = None
        def double_trir(df): df.loc[0, "trir_screened"] *= 2
        def swap_pct(df): df[["p10", "p95"]] = df[["p95", "p10"]].values
        def negative_n(df): df.loc[0, "n"] = -5
        def impossible_hours(df): df.loc[0, "hours_per_employee"] = 100.0
        def too_many_flagged(df): df.loc[0, "n_implausible"] = df.loc[0, "n_filings"] + 1
        def bad_cells(df): df.loc[0, "n_total"] += 1
        def dup_year(df): df.loc[1, "label"] = df.loc[0, "label"]
        def rate_huge(df): df.loc[0, "aggregate_trir_screened"] = 5000.0
        def bad_rho(df): df.loc[0, "spearman_rho"] = 1.7

        cases = [
            ("quality_by_naics2", drop_row, "quality_by_naics2.sector_filings_sum_to_pooled"),
            ("quality_by_year", share_over_one, "quality_by_year.shares_in_unit_interval"),
            ("quality_by_year", bad_year, "quality_by_year.years_in_range"),
            ("quality_by_year", bad_year, "quality_by_year.years_complete"),
            ("quality_by_year", dup_year, "quality_by_year.key_unique"),
            ("quality_overall", drop_col, "quality_overall.columns_present"),
            ("quality_by_year", null_key, "quality_by_year.key_columns_not_null"),
            ("quality_by_year", null_key, "quality_by_year.n_filings_sums_to_pooled"),
            ("quality_by_year", too_many_flagged, "quality_by_year.implausible_le_filings"),
            ("metrics_pooled", double_trir, "metrics_pooled.trir_screened_formula"),
            ("metrics_pooled", double_trir, "metrics_pooled.trir_matches_quality_overall"),
            ("peer_percentiles_pooled", swap_pct, "peer_percentiles_pooled.percentiles_ordered"),
            ("size_band_effects", negative_n, "size_band_effects.moments_non_negative"),
            ("size_band_effects", negative_n, "size_band_effects.establishments_sum_to_screened"),
            ("quality_top50_implausible_hours", impossible_hours, "quality_top50_implausible_hours.hours_per_employee_impossible"),
            ("panel_transitions", bad_cells, "panel_transitions.cells_sum_to_total"),
            ("quality_by_year", rate_huge, "quality_by_year.rates_physical"),
            ("percentile_band_stability", bad_rho, "percentile_band_stability.rho_valid"),
        ]
        for table, fn, eid in cases:
            with self.subTest(eid=eid, mutation=fn.__name__):
                shutil.copy(TABLES / f"{table}.csv", self.tables / f"{table}.csv")
                self.edit(table, fn)
                self.assertEqual(_status(self.results(), eid), "fail")
                shutil.copy(TABLES / f"{table}.csv", self.tables / f"{table}.csv")

    def test_missing_table_fails(self) -> None:
        (self.tables / "size_band_effects.csv").unlink()
        self.assertEqual(_status(self.results(), "size_band_effects.columns_present"), "fail")
        skipped = ex.run_expectations(self.tables, self.summary, allow_missing=True)
        self.assertEqual(_status(skipped, "size_band_effects.columns_present"), "skip")

    def test_summary_mismatch_fails(self) -> None:
        data = json.loads(self.summary.read_text())
        data["quality"]["pooled"]["n_filings"] += 1
        self.summary.write_text(json.dumps(data))
        res = self.results()
        self.assertEqual(_status(res, "quality_overall.filings_match_summary"), "fail")
        self.assertEqual(_status(res, "quality_by_naics2.sector_filings_sum_to_pooled"), "fail")
        self.assertEqual(_status(res, "summary.pooled_filings_match_load"), "fail")

    def test_exit_codes(self) -> None:
        args = ["--tables", str(self.tables), "--summary", str(self.summary), "--doc", ""]
        self.assertEqual(_main(args), 0)
        self.edit("quality_by_year", lambda df: df.__setitem__("aggregate_trir_screened", 5000.0))
        self.assertEqual(_main(args), 0, "warn-only failure must not fail the run")
        self.assertEqual(_main(args + ["--strict"]), 1)
        self.edit("quality_by_year", lambda df: df.__setitem__("implausible_share", 1.5))
        self.assertEqual(_main(args), 1)

    def test_failure_is_reported_in_doc(self) -> None:
        self.edit("quality_by_year", lambda df: df.__setitem__("implausible_share", 1.5))
        spec = ex.load_spec()
        doc = ex.render(ex.run_expectations(self.tables, self.summary, spec), spec)
        self.assertIn("## Failing", doc)
        self.assertIn("quality_by_year.shares_in_unit_interval", doc)


@unittest.skipUnless(_context.fixture_available(), "synthetic fixture absent")
class TestStructuralOnFixture(unittest.TestCase):
    """Structural expectations hold for any pipeline run, fixture included."""

    def test_structural_expectations_pass_on_fixture_run(self) -> None:
        from test_pipeline_on_fixture import fixture_specs

        import ehs_osha.load as load_mod
        from ehs_osha.pipeline import PipelineConfig, run_pipeline
        from ehs_osha.quality import PlausibilityConfig

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            cfg = PipelineConfig(
                data_dir=_context.FIXTURE, out_dir=out, plausibility=PlausibilityConfig(),
                min_group_n=20, model_naics3=("325",), model_year=2024,
            )
            original = load_mod.all_files
            load_mod.all_files = lambda include_partial=False: fixture_specs()
            try:
                run_pipeline(cfg, verbose=False)
            finally:
                load_mod.all_files = original
            results = ex.run_expectations(
                out / "tables", out / "summary.json", structural_only=True, allow_missing=True
            )
        bad = [(r.id, r.observed) for r in results if r.status == "fail"]
        self.assertEqual(bad, [])
        self.assertGreater(sum(r.status == "pass" for r in results), 100)


if __name__ == "__main__":
    unittest.main()
