"""Tests for the Foundry-style ontology in ``src/ehs_osha/ontology``.

Establishment and Filing objects here are built from the SYNTHETIC fixture;
the numbers they produce are properties of the generator, not findings. The
point of these tests is that the spec is consistent, objects materialise with
the declared types, links resolve both ways, actions validate and log, and the
ontology functions return exactly what the pipeline's own code returns.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import math
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import _context  # noqa: F401
import pandas as pd

from ehs_osha import load, metrics, quality
from ehs_osha.naics import naics3_title
from ehs_osha.ontology import ActionRejected, ObjectStore, SpecError, load_spec
from ehs_osha.ontology import functions as F
from ehs_osha.ontology.__main__ import main
from ehs_osha.ontology.export import export_json, export_sqlite, to_json_dict
from ehs_osha.ontology.materialise import (
    SOURCE_FIXTURE,
    SOURCE_OUTPUTS,
    build_store,
    load_fixture_frame,
)
from ehs_osha.ontology.runtime import ObjectValidationError
from ehs_osha.ontology.spec import SPEC_PATH, validate

TABLES = _context.ROOT / "outputs" / "tables"
SUMMARY = _context.ROOT / "outputs" / "summary.json"

_FRAME = None


def fixture_frame() -> pd.DataFrame:
    """The harmonised fixture frame, loaded once per test run."""
    global _FRAME
    if _FRAME is None:
        _FRAME = load_fixture_frame()
    return _FRAME.copy()


def pinned_clock() -> datetime:
    return datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def small_store() -> ObjectStore:
    """A fresh store over a slice of the fixture: 20 sites plus 5 with a screen failure."""
    df = quality.apply_screen(fixture_frame())
    bad = df.loc[df["implausible"], "establishment_id"].unique()[:5]
    good = df.loc[~df["establishment_id"].isin(bad), "establishment_id"].unique()[:20]
    sub = fixture_frame()
    sub = sub[sub["establishment_id"].isin(list(bad) + list(good))].reset_index(drop=True)
    return build_store(frame=sub, clock=pinned_clock)


def raw_spec() -> dict:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


class TestSpecValidation(unittest.TestCase):
    def test_bundled_spec_is_valid(self) -> None:
        self.assertEqual(validate(raw_spec()), [])
        spec = load_spec()
        self.assertEqual(
            set(spec.object_types),
            {"Establishment", "Filing", "ReportingYear", "Sector", "Industry", "PeerGroup", "QualityFlag"},
        )
        self.assertEqual(len(spec.link_types), 7)
        self.assertEqual(
            set(spec.action_types),
            {"flag_filing_implausible", "clear_analyst_flag", "exclude_from_benchmark", "restore_to_benchmark"},
        )

    def test_every_spec_function_has_an_implementation(self) -> None:
        spec = load_spec()
        self.assertEqual(set(spec.functions), set(F.REGISTRY))
        F.check_registry(spec.functions)

    def test_functions_reuse_pipeline_modules(self) -> None:
        for fn in load_spec().functions.values():
            self.assertTrue(fn["reuses"].startswith("ehs_osha."), fn["api_name"])
            self.assertNotIn(".ontology.", fn["reuses"], fn["api_name"])

    def test_only_writeback_properties_are_editable(self) -> None:
        spec = load_spec()
        for name in spec.object_types:
            editable = {p for p, d in spec.properties(name).items() if d.get("editable")}
            if name == "Filing":
                self.assertEqual(
                    editable,
                    {"analyst_flag", "analyst_flag_reason", "analyst_flag_note", "benchmark_excluded",
                     "benchmark_exclusion_reason", "benchmark_exclusion_note"},
                )
            else:
                self.assertEqual(editable, set(), name)

    def _mutated(self, mutate) -> list:
        raw = raw_spec()
        mutate(raw)
        return validate(raw)

    def test_broken_specs_are_rejected_with_a_reason(self) -> None:
        def obj(raw, name):
            return next(o for o in raw["object_types"] if o["api_name"] == name)

        def link(raw, name):
            return next(lk for lk in raw["link_types"] if lk["api_name"] == name)

        def action(raw, name):
            return next(a for a in raw["action_types"] if a["api_name"] == name)

        cases = {
            "is not an object type": lambda r: link(r, "filing_industry").update(target="Nope"),
            "foreign key 'nope' is not a property": lambda r: link(r, "filing_industry").update(foreign_key="nope"),
            "does not match": lambda r: link(r, "filing_reporting_year").update(foreign_key="naics3"),
            "clashes": lambda r: link(r, "filing_industry").update(source_link_name="peer_group"),
            "primary key 'missing' is not a property": lambda r: obj(r, "Sector").update(primary_key="missing"),
            "unknown type 'decimal'": lambda r: obj(r, "Sector")["properties"][1].update(type="decimal"),
            "is not editable": lambda r: action(r, "flag_filing_implausible")["edits"][0]["set"].update(trir=0.0),
            "$who is not a parameter": lambda r: action(r, "clear_analyst_flag")["edits"][0]["set"].update(
                analyst_flag_note="$who"
            ),
            "criterion property": lambda r: action(r, "restore_to_benchmark")["submission_criteria"][0].update(
                property="ghost"
            ),
            "does not resolve": lambda r: r["functions"][0].update(reuses="ehs_osha.quality.no_such_function"),
            "missing top-level key": lambda r: r.pop("functions"),
        }
        for expected, mutate in cases.items():
            with self.subTest(expected=expected):
                errors = self._mutated(mutate)
                self.assertTrue(any(expected in e for e in errors), errors)

    def test_load_spec_reports_every_error_at_once(self) -> None:
        raw = raw_spec()
        raw["link_types"][0]["target"] = "Nope"
        raw["functions"][0]["reuses"] = "ehs_osha.nowhere.thing"
        with self.assertRaises(SpecError) as ctx:
            load_spec(raw)
        self.assertEqual(len(ctx.exception.errors), 2)


@unittest.skipUnless(_context.fixture_available(), "run `python synthetic/generate_fixture.py` to enable")
class TestMaterialisation(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = build_store(frame=fixture_frame())
        cls.screened = quality.apply_screen(fixture_frame())

    def test_object_counts_follow_their_sources(self) -> None:
        s = self.store
        self.assertEqual(s.objects("Filing").count(), len(self.screened))
        self.assertEqual(s.objects("Establishment").count(), self.screened["establishment_id"].nunique())
        self.assertEqual(s.objects("ReportingYear").count(), len(pd.read_csv(TABLES / "quality_by_year.csv")))
        self.assertEqual(s.objects("Sector").count(), len(pd.read_csv(TABLES / "quality_by_naics2.csv")))
        self.assertEqual(s.objects("PeerGroup").count(), len(pd.read_csv(TABLES / "peer_percentiles_pooled.csv")))
        self.assertEqual(s.objects("QualityFlag").primary_keys(), list(quality.FLAG_COLUMNS))

    def test_provenance_is_labelled(self) -> None:
        self.assertEqual({o["source"] for o in self.store.objects("Filing")}, {SOURCE_FIXTURE})
        for t in ("ReportingYear", "Sector", "Industry", "PeerGroup", "QualityFlag"):
            self.assertEqual({o["source"] for o in self.store.objects(t)}, {SOURCE_OUTPUTS}, t)

    def test_year_objects_carry_the_committed_numbers(self) -> None:
        summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
        by_year = {int(float(r["label"])): r for r in summary["quality"]["by_year"]}
        dart = {int(float(r["label"])): r["dart_screened"] for r in summary["metrics"]["by_year"]}
        for year, row in by_year.items():
            obj = self.store.get("ReportingYear", year)
            self.assertAlmostEqual(obj["aggregate_trir_screened"], row["aggregate_trir_screened"], places=12)
            self.assertAlmostEqual(obj["aggregate_trir_unscreened"], row["aggregate_trir_unscreened"], places=12)
            self.assertEqual(obj["n_filings"], row["n_filings"])
            self.assertAlmostEqual(obj["dart_screened"], dart[year], places=12)

    def test_flag_objects_carry_the_committed_prevalence(self) -> None:
        prev = pd.read_csv(TABLES / "quality_flag_prevalence.csv").set_index("flag")
        for obj in self.store.objects("QualityFlag"):
            self.assertEqual(obj["pooled_n"], int(prev.loc[obj.primary_key, "n"]))
        self.assertFalse(self.store.get("QualityFlag", "flag_no_injury_contradiction")["counts_in_verdict"])
        self.assertEqual(self.store.get("QualityFlag", "flag_hours_per_employee_high").title, "hours per employee > 4,500")

    def test_industries_use_official_titles_only(self) -> None:
        for obj in self.store.objects("Industry"):
            official = naics3_title(obj.primary_key)
            self.assertEqual(obj["has_official_title"], official is not None)
            self.assertEqual(obj.title, official or obj.primary_key)

    def test_every_many_to_one_link_resolves_on_the_fixture(self) -> None:
        for name, counts in self.store.integrity_report().items():
            self.assertEqual(counts["dangling"], 0, name)

    def test_screen_verdict_matches_the_pipeline(self) -> None:
        expected = int(self.screened["implausible"].sum())
        self.assertGreater(expected, 0)
        self.assertEqual(self.store.objects("Filing").where(screen_implausible=True).count(), expected)

    def test_objects_are_read_only_views(self) -> None:
        obj = next(iter(self.store.objects("Filing")))
        with self.assertRaises(TypeError):
            obj.properties["analyst_flag"] = True  # type: ignore[index]

    def test_type_and_key_violations_are_rejected(self) -> None:
        s = ObjectStore()
        row = {"year": 2030, "year_label": "x", "n_filings": 1, "n_implausible": 0, "implausible_share": 0.0,
               "hours_share_implausible": 0.0, "aggregate_trir_unscreened": 1.0, "aggregate_trir_screened": 1.0,
               "ratio_screened_to_unscreened": 1.0, "dart_screened": 1.0, "ltir_screened": 1.0,
               "severity_screened": 1.0, "source": "test"}
        s.add_objects("ReportingYear", [row])
        with self.assertRaisesRegex(ObjectValidationError, "duplicate"):
            s.add_objects("ReportingYear", [row])
        with self.assertRaisesRegex(ObjectValidationError, "not nullable"):
            s.add_objects("ReportingYear", [{**row, "year": 2031, "n_filings": None}])
        with self.assertRaisesRegex(ObjectValidationError, "not an integer"):
            s.add_objects("ReportingYear", [{**row, "year": 2032, "n_filings": 1.5}])


@unittest.skipUnless(_context.fixture_available(), "run `python synthetic/generate_fixture.py` to enable")
class TestLinkTraversal(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = build_store(frame=fixture_frame())

    def test_establishment_filings_round_trip(self) -> None:
        site = next(iter(self.store.objects("Establishment")))
        filings = self.store.linked(site, "filings")
        self.assertEqual(filings.count(), 4)
        for f in filings:
            self.assertEqual(self.store.linked(f, "establishment").one().primary_key, site.primary_key)

    def test_filing_to_peer_group_to_industry_to_sector(self) -> None:
        f = next(iter(self.store.objects("Filing").where(screen_implausible=False)))
        group = self.store.linked(f, "peer_group").one()
        self.assertEqual(group.primary_key, f["peer_group_key"])
        industry = self.store.linked(group, "industry").one()
        self.assertEqual(industry.primary_key, f["naics3"])
        self.assertEqual(self.store.linked(f, "industry").one().primary_key, industry.primary_key)
        self.assertEqual(self.store.linked(industry, "sector").one().primary_key, f["naics3"][:2])
        self.assertIn(group.primary_key, self.store.linked(industry, "peer_groups").primary_keys())

    def test_quality_flag_links_both_ways(self) -> None:
        high = self.store.get("QualityFlag", "flag_hours_per_employee_high")
        via_link = set(self.store.linked(high, "filings").primary_keys())
        via_prop = set(self.store.objects("Filing").where(flag_hours_per_employee_high=True).primary_keys())
        self.assertEqual(via_link, via_prop)
        for f in self.store.objects("Filing").where(screen_implausible=True):
            fired = self.store.linked(f, "quality_flags")
            self.assertTrue(any(q["counts_in_verdict"] for q in fired), f.primary_key)

    def test_search_around_deduplicates(self) -> None:
        years = self.store.objects("Filing").search_around("reporting_year")
        self.assertEqual(sorted(years.primary_keys()), [2021, 2022, 2023, 2024])

    def test_unknown_link_or_property_is_an_error(self) -> None:
        f = next(iter(self.store.objects("Filing")))
        with self.assertRaises(KeyError):
            self.store.linked(f, "inspections")
        with self.assertRaises(KeyError):
            self.store.objects("Filing").where(no_such_property=1)


@unittest.skipUnless(_context.fixture_available(), "run `python synthetic/generate_fixture.py` to enable")
class TestFunctionsMatchPipeline(unittest.TestCase):
    """Ontology functions must return what the pipeline's own code returns."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.store = build_store(frame=fixture_frame())
        cls.screened = quality.apply_screen(fixture_frame())

    def _assert_rows_equal(self, got: dict, want: dict) -> None:
        for key, value in want.items():
            if key == "label":
                continue
            if isinstance(value, float) and math.isnan(value):
                self.assertTrue(math.isnan(got[key]), key)
            else:
                self.assertAlmostEqual(got[key], value, places=9, msg=key)

    def test_aggregate_rates_pooled(self) -> None:
        self._assert_rows_equal(
            F.aggregate_rates(self.store.objects("Filing")), metrics.compute_rates(self.screened)
        )

    def test_aggregate_rates_by_year(self) -> None:
        for _, row in metrics.rates_by_year(self.screened).iterrows():
            year = int(row["label"])
            got = F.aggregate_rates(self.store.objects("Filing").where(year_filing_for=year))
            self._assert_rows_equal(got, row.to_dict())

    def test_aggregate_trir_matches_screen_summary(self) -> None:
        want = quality.summarise_screen(self.screened)
        self.assertAlmostEqual(F.aggregate_trir(self.store.objects("Filing")), want.aggregate_trir_screened, places=12)
        self.assertAlmostEqual(
            F.aggregate_trir(self.store.objects("Filing"), respect_writeback=False),
            want.aggregate_trir_screened,
            places=12,
        )

    def test_filing_rates_rederive_the_stored_values(self) -> None:
        for f in list(self.store.objects("Filing").where(screen_implausible=False))[:200]:
            got = F.filing_rates(f)
            self.assertAlmostEqual(got["trir"], f["trir"], places=9)
            self.assertAlmostEqual(got["dart_rate"], f["dart_rate"], places=9)

    def test_plausibility_screen_what_if(self) -> None:
        filings = self.store.objects("Filing")
        default = F.plausibility_screen(filings)
        for f in filings:
            self.assertEqual(default[f.primary_key], f["screen_implausible"])
        tight = F.plausibility_screen(filings, quality.PlausibilityConfig(500.0, 3000.0))
        self.assertGreaterEqual(sum(tight.values()), sum(default.values()))
        self.assertEqual(filings.where(screen_implausible=True).count(), sum(default.values()))

    def test_wrong_object_set_type_is_refused(self) -> None:
        with self.assertRaises(TypeError):
            F.aggregate_trir(self.store.objects("Establishment"))

    def test_peer_position_places_against_the_committed_percentiles(self) -> None:
        f = next(o for o in self.store.objects("Filing").where(screen_implausible=False) if o["trir"])
        pos = F.peer_position(self.store, f)
        self.assertEqual(pos["status"], "placed")
        group = self.store.get("PeerGroup", f["peer_group_key"])
        lo, hi = pos["band"].split("-") if "-" in pos["band"] else (None, None)
        if lo:
            self.assertLessEqual(group[lo], f["trir"])
            self.assertLess(f["trir"], group[hi])
        bad = next(iter(self.store.objects("Filing").where(screen_implausible=True)))
        self.assertEqual(F.peer_position(self.store, bad)["status"], "excluded")

    def test_peer_position_refuses_unpublishable_cells(self) -> None:
        groups = pd.read_csv(TABLES / "peer_percentiles_pooled.csv", dtype={"naics3": str})
        cell = groups[(~groups["publishable"]) & (groups["size_band"] == "050-099")].iloc[0]
        frame = fixture_frame().head(1).copy()
        frame["naics_code"] = float(cell["naics3"] + "111")
        frame["annual_average_employees"] = 60.0
        frame["total_hours_worked"] = 120000.0
        frame = load.derive_fields(frame)
        store = build_store(frame=frame)
        f = next(iter(store.objects("Filing")))
        self.assertEqual(f["peer_group_key"], cell["naics3"] + "|050-099")
        self.assertEqual(F.peer_position(store, f)["status"], "not_publishable")


@unittest.skipUnless(_context.fixture_available(), "run `python synthetic/generate_fixture.py` to enable")
class TestActions(unittest.TestCase):
    def setUp(self) -> None:
        self.store = small_store()
        self.good = next(iter(self.store.objects("Filing").where(screen_implausible=False)))
        self.bad = next(iter(self.store.objects("Filing").where(screen_implausible=True)))

    def test_flag_applies_edits_and_logs_who_when_why(self) -> None:
        before = F.aggregate_trir(self.store.objects("Filing"))
        entry = self.store.apply(
            "flag_filing_implausible",
            {"filing": self.good.primary_key, "reason": "employee_count_mistyped"},
            actor="analyst@example.org",
        )
        f = self.store.get("Filing", self.good.primary_key)
        self.assertTrue(f["analyst_flag"])
        self.assertEqual(f["analyst_flag_reason"], "employee_count_mistyped")
        self.assertEqual(entry.action_id, "act-000001")
        self.assertEqual(entry.actor, "analyst@example.org")
        self.assertEqual(entry.timestamp, "2026-01-02T03:04:05+00:00")
        self.assertIn({"object_type": "Filing", "primary_key": self.good.primary_key, "property": "analyst_flag",
                       "before": False, "after": True}, entry.edits)
        # Writeback reaches the function: same as the pipeline with that row excluded.
        frame = self.store.objects("Filing").to_frame()
        keep = frame[~frame["screen_implausible"] & (frame["filing_id"] != self.good.primary_key)]
        want = quality.aggregate_trir(keep["recordable_cases"].astype(float), keep["total_hours_worked"])
        self.assertAlmostEqual(F.aggregate_trir(self.store.objects("Filing")), want, places=12)
        self.assertEqual(F.peer_position(self.store, f)["status"], "excluded")
        if self.good["recordable_cases"]:
            self.assertNotAlmostEqual(F.aggregate_trir(self.store.objects("Filing")), before, places=12)

    def test_rejections_change_nothing_and_log_nothing(self) -> None:
        pk = self.good.primary_key
        cases = [
            ("flag_filing_implausible", {"filing": pk, "reason": "employee_count_mistyped"}, "", "actor is required"),
            ("flag_filing_implausible", {"filing": pk, "reason": "looks_odd"}, "a", "reason must be one of"),
            ("flag_filing_implausible", {"filing": pk, "reason": "other"}, "a", "note is required"),
            ("flag_filing_implausible", {"filing": pk, "reason": "other", "note": "x" * 501}, "a", "at most 500"),
            ("flag_filing_implausible", {"filing": "no-such-filing", "reason": "other", "note": "n"}, "a", "no Filing"),
            ("flag_filing_implausible", {"filing": pk, "reason": "other", "note": "n", "extra": 1}, "a", "unknown"),
            ("flag_filing_implausible", {"filing": self.bad.primary_key, "reason": "other", "note": "n"}, "a",
             "screen already excludes"),
            ("clear_analyst_flag", {"filing": pk, "note": "confirmed by site"}, "a", "carries no analyst flag"),
            ("clear_analyst_flag", {"filing": pk, "note": "short"}, "a", "at least 10"),
            ("restore_to_benchmark", {"filing": pk, "note": "back in scope now"}, "a", "not excluded"),
            ("exclude_from_benchmark", {"filing": self.bad.primary_key, "reason": "under_review"}, "a",
             "screen already excludes"),
        ]
        snapshot = copy.deepcopy(self.store._rows["Filing"])
        for action, params, actor, message in cases:
            with self.subTest(action=action, message=message):
                with self.assertRaises(ActionRejected) as ctx:
                    self.store.apply(action, params, actor=actor)
                self.assertTrue(any(message in e for e in ctx.exception.errors), ctx.exception.errors)
        self.assertEqual(self.store.action_log, [])
        self.assertEqual(self.store._rows["Filing"], snapshot)

    def test_cannot_flag_twice_then_clear_restores_the_aggregate(self) -> None:
        base = F.aggregate_trir(self.store.objects("Filing"))
        params = {"filing": self.good, "reason": "company_wide_hours_reported"}
        self.store.apply("flag_filing_implausible", params, actor="a")
        with self.assertRaisesRegex(ActionRejected, "already flagged"):
            self.store.apply("flag_filing_implausible", params, actor="a")
        self.store.apply("clear_analyst_flag", {"filing": self.good, "note": "site confirmed hours"}, actor="b")
        f = self.store.get("Filing", self.good.primary_key)
        self.assertFalse(f["analyst_flag"])
        self.assertIsNone(f["analyst_flag_reason"])
        self.assertAlmostEqual(F.aggregate_trir(self.store.objects("Filing")), base, places=12)

    def test_exclude_restore_round_trip_and_history(self) -> None:
        pk = self.good.primary_key
        self.store.apply("exclude_from_benchmark", {"filing": pk, "reason": "not_comparable_to_peers"}, actor="a")
        self.assertTrue(self.store.get("Filing", pk)["benchmark_excluded"])
        self.store.apply("restore_to_benchmark", {"filing": pk, "note": "comparable after review"}, actor="b")
        self.assertFalse(self.store.get("Filing", pk)["benchmark_excluded"])
        history = self.store.edit_history("Filing", pk)
        self.assertEqual([h["action_type"] for h in history if h["property"] == "benchmark_excluded"],
                         ["exclude_from_benchmark", "restore_to_benchmark"])
        self.assertEqual([h["actor"] for h in history if h["property"] == "benchmark_excluded"], ["a", "b"])


@unittest.skipUnless(_context.fixture_available(), "run `python synthetic/generate_fixture.py` to enable")
class TestExport(unittest.TestCase):
    def setUp(self) -> None:
        self.store = small_store()
        self.pk = next(iter(self.store.objects("Filing").where(screen_implausible=False))).primary_key
        self.store.apply("exclude_from_benchmark", {"filing": self.pk, "reason": "under_review"}, actor="a")
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_sqlite_export(self) -> None:
        path = export_sqlite(self.store, self.dir / "o.sqlite")
        con = sqlite3.connect(str(path))
        try:
            for t in self.store.spec.object_types:
                n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                self.assertEqual(n, self.store.objects(t).count(), t)
            excluded = con.execute('SELECT benchmark_excluded FROM "Filing" WHERE filing_id = ?', (self.pk,)).fetchone()
            self.assertEqual(excluded, (1,))
            log = con.execute("SELECT action_type, actor, edits FROM action_log").fetchall()
            self.assertEqual(log[0][:2], ("exclude_from_benchmark", "a"))
            self.assertEqual(json.loads(log[0][2])[0]["after"], True)
            n_links = con.execute('SELECT COUNT(*) FROM "link_filing_quality_flags"').fetchone()[0]
            self.assertEqual(n_links, len(self.store.link_pairs("filing_quality_flags")))
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute('INSERT INTO "Sector" (naics2, n_filings, implausible_share, source) '
                            "VALUES ('11', 1, 0.0, 'x')")
            spec = json.loads(con.execute("SELECT spec_json FROM ontology_spec").fetchone()[0])
            self.assertEqual(spec["ontology"]["api_name"], "ehs_osha_ita")
        finally:
            con.close()

    def test_json_export_is_strict_json(self) -> None:
        path = export_json(self.store, self.dir / "o.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["objects"]["Filing"]), self.store.objects("Filing").count())
        self.assertEqual(payload["action_log"][0]["action_type"], "exclude_from_benchmark")
        self.assertEqual(to_json_dict(self.store)["integrity"], self.store.integrity_report())

    def test_cli_writes_both_files(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(["--out", str(self.dir)]), 0)
        self.assertTrue((self.dir / "ontology.sqlite").exists())
        self.assertTrue((self.dir / "ontology.json").exists())
        self.assertIn("SYNTHETIC", out.getvalue())


if __name__ == "__main__":
    unittest.main()
