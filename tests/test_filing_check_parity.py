"""Parity: shared JSON rules give identical results in Python, JavaScript and quality.apply_screen."""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import unittest

import _context  # noqa: F401
import pandas as pd

from ehs_osha import filing_check, load, quality

ROOT = _context.ROOT
FLAGS = list(quality.FLAG_COLUMNS)


def _records(n: int = 400) -> list:
    rng = random.Random(7)
    recs = [
        {},
        {"total_hours_worked": 0, "annual_average_employees": 5},
        {"total_hours_worked": 4500, "annual_average_employees": 1, "total_deaths": 0,
         "total_dafw_cases": 0, "total_djtr_cases": 0, "total_other_cases": 0},
        {"total_hours_worked": 4500.5, "annual_average_employees": 1, "total_deaths": 0,
         "total_dafw_cases": 0, "total_djtr_cases": 0, "total_other_cases": 0},
        {"total_hours_worked": 120, "annual_average_employees": 1, "total_deaths": 0,
         "total_dafw_cases": 0, "total_djtr_cases": 0, "total_other_cases": 1,
         "no_injuries_illnesses": 2},
        {"total_hours_worked": 119.9, "annual_average_employees": 1, "total_deaths": -1,
         "total_dafw_cases": 0, "total_djtr_cases": 0, "total_other_cases": 3,
         "no_injuries_illnesses": 1},
        {"total_hours_worked": 1000, "annual_average_employees": 0.5, "total_deaths": 0,
         "total_dafw_cases": 0, "total_djtr_cases": 0, "total_other_cases": 0,
         "no_injuries_illnesses": 1},
    ]
    for _ in range(n):
        r = {}
        for k, choices in (
            ("total_hours_worked", [None, 0, -5, rng.uniform(1, 2e6), rng.choice([120, 4500])]),
            ("annual_average_employees", [None, 0, 0.5, 1, rng.randint(1, 800)]),
            ("total_deaths", [None, 0, 0, 0, -1, 1]),
            ("total_dafw_cases", [None, 0, 0, 2, 5, -2]),
            ("total_djtr_cases", [None, 0, 0, 1, 4]),
            ("total_other_cases", [None, 0, 0, 3, 9]),
            ("no_injuries_illnesses", [None, 1, 2, 2, 1]),
        ):
            r[k] = rng.choice(choices)
        recs.append(r)
    return recs


def _frame(recs: list) -> pd.DataFrame:
    cols = ["total_hours_worked", "annual_average_employees", "total_deaths",
            "total_dafw_cases", "total_djtr_cases", "total_other_cases", "no_injuries_illnesses"]
    df = pd.DataFrame([{c: r.get(c) for c in cols} for r in recs], columns=cols).astype("float64")
    df["naics_code"] = 311111.0
    return load.derive_fields(df)


class TestRulesSpec(unittest.TestCase):
    def test_docs_copy_identical(self) -> None:
        self.assertEqual((ROOT / "docs" / "plausibility_rules.json").read_bytes(),
                         filing_check.SPEC_PATH.read_bytes())

    def test_spec_matches_default_config(self) -> None:
        cfg = quality.PlausibilityConfig()
        p = filing_check.load_rules()["params"]
        self.assertEqual(p["min_hours_per_employee"], cfg.min_hours_per_employee)
        self.assertEqual(p["max_hours_per_employee"], cfg.max_hours_per_employee)
        self.assertEqual(p["hours_in_year"], quality.HOURS_IN_YEAR)
        self.assertEqual(p["treat_contradiction_as_implausible"],
                         cfg.treat_contradiction_as_implausible)
        self.assertEqual([f["id"] for f in filing_check.load_rules()["flags"]], FLAGS)


class TestPythonMatchesScreen(unittest.TestCase):
    def test_against_apply_screen(self) -> None:
        recs = _records()
        screened = quality.apply_screen(_frame(recs))
        for i, rec in enumerate(recs):
            res = filing_check.check_filing(rec)
            for f in FLAGS:
                self.assertEqual(res["flags"][f], bool(screened[f].iloc[i]), (f, rec))
            self.assertEqual(res["implausible"], bool(screened["implausible"].iloc[i]), rec)

    def test_override_matches_config(self) -> None:
        recs = _records(100)
        cfg = quality.PlausibilityConfig(min_hours_per_employee=200, max_hours_per_employee=3500,
                                         treat_contradiction_as_implausible=True)
        screened = quality.apply_screen(_frame(recs), cfg)
        for i, rec in enumerate(recs):
            res = filing_check.check_filing(
                rec, min_hours_per_employee=200, max_hours_per_employee=3500,
                treat_contradiction_as_implausible=True)
            self.assertEqual(res["implausible"], bool(screened["implausible"].iloc[i]), rec)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TestJavaScriptMatchesPython(unittest.TestCase):
    def test_parity(self) -> None:
        recs = _records()
        rules = filing_check.load_rules()
        proc = subprocess.run(
            ["node", str(ROOT / "scripts" / "check_filing_js.js")],
            input=json.dumps({"rules": rules, "records": recs}),
            capture_output=True, text=True, check=True,
        )
        js = json.loads(proc.stdout)
        self.assertEqual(len(js), len(recs))
        for rec, got in zip(recs, js):
            want = filing_check.check_filing(rec, rules)
            self.assertEqual(got["flags"], want["flags"], rec)
            self.assertEqual(got["implausible"], want["implausible"], rec)
            self.assertEqual(got["messages"], want["messages"], rec)


if __name__ == "__main__":
    unittest.main()
