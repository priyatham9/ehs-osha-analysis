"""Tests for the machine-readable data dictionary and the datasheet.

``docs/data_dictionary.csv`` documents every column of every committed table in
``outputs/tables/`` and every column of the (uncommitted) analytic frame the
pipeline builds. These tests fail when a table gains, loses or renames a column
without the dictionary following, when a documented type disagrees with the
committed values, and when the datasheet's headline counts drift from the
committed tables.
"""

from __future__ import annotations

import csv
import re
import unittest
from collections import Counter

import _context  # noqa: F401
from ehs_osha import quality, schema

ROOT = _context.ROOT
TABLES = ROOT / "outputs" / "tables"
DICT = ROOT / "docs" / "data_dictionary.csv"
DATASHEET = ROOT / "DATASHEET.md"
HEADER = ["table", "column", "type", "units", "source", "derivation", "known_issues"]
TYPES = {"integer", "float", "string", "boolean", "mixed"}
FRAME = "analytic_frame"

#: Columns the loader derives on top of the published schema (load.derive_fields,
#: quality.apply_screen, peers.add_peer_keys).
DERIVED_FRAME_COLUMNS = (
    "recordable_cases",
    "dart_cases",
    "hours_per_employee",
    "trir",
    "dart_rate",
    "naics2",
    "naics3",
    "naics4",
    "implausible",
    "size_band",
    "peer_group",
)


def _read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _header(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return next(csv.reader(fh))


def _is_float(text):
    try:
        float(text)
    except ValueError:
        return False
    return True


class TestDictionaryShape(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = _read(DICT)

    def test_header(self):
        self.assertEqual(_header(DICT), HEADER)

    def test_no_empty_cells(self):
        for r in self.rows:
            for k in HEADER:
                self.assertTrue(r[k].strip(), "empty %s for %s.%s" % (k, r["table"], r["column"]))

    def test_no_duplicate_keys(self):
        dupes = [k for k, n in Counter((r["table"], r["column"]) for r in self.rows).items() if n > 1]
        self.assertEqual(dupes, [])

    def test_types_are_from_the_vocabulary(self):
        bad = [(r["table"], r["column"], r["type"]) for r in self.rows if r["type"] not in TYPES]
        self.assertEqual(bad, [])


class TestCommittedTablesDocumented(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = _read(DICT)
        cls.doc = {(r["table"], r["column"]): r for r in cls.rows}
        cls.tables = sorted(p.stem for p in TABLES.glob("*.csv"))

    def test_there_are_committed_tables(self):
        self.assertGreater(len(self.tables), 0)

    def test_every_column_of_every_table_is_documented(self):
        missing = []
        for t in self.tables:
            for c in _header(TABLES / (t + ".csv")):
                if (t, c) not in self.doc:
                    missing.append("%s.%s" % (t, c))
        self.assertEqual(missing, [], "undocumented columns: %s" % missing)

    def test_no_stale_entries(self):
        stale = []
        for (t, c) in self.doc:
            if t == FRAME:
                continue
            path = TABLES / (t + ".csv")
            if not path.exists() or c not in _header(path):
                stale.append("%s.%s" % (t, c))
        self.assertEqual(stale, [], "documented but absent: %s" % stale)

    def test_documented_type_matches_committed_values(self):
        problems = []
        for t in self.tables:
            recs = _read(TABLES / (t + ".csv"))
            for c in _header(TABLES / (t + ".csv")):
                kind = self.doc[(t, c)]["type"]
                vals = [r[c] for r in recs if r[c] != ""]
                if kind == "boolean" and not all(v in ("True", "False") for v in vals):
                    problems.append("%s.%s not boolean" % (t, c))
                elif kind in ("integer", "float"):
                    if not all(_is_float(v) for v in vals):
                        problems.append("%s.%s not numeric" % (t, c))
                    elif kind == "integer" and not all(float(v) == int(float(v)) for v in vals):
                        problems.append("%s.%s not integral" % (t, c))
        self.assertEqual(problems, [])

    def test_every_row_names_its_source(self):
        for (t, c), r in self.doc.items():
            self.assertTrue(r["source"].strip(), "%s.%s source" % (t, c))


class TestAnalyticFrameDocumented(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = {r["column"] for r in _read(DICT) if r["table"] == FRAME}

    def test_schema_columns(self):
        missing = [c for c in schema.CANONICAL_COLUMNS if c not in self.doc]
        self.assertEqual(missing, [])

    def test_derived_and_flag_columns(self):
        want = list(DERIVED_FRAME_COLUMNS) + list(quality.FLAG_COLUMNS)
        self.assertEqual([c for c in want if c not in self.doc], [])

    def test_fixture_columns(self):
        for path in sorted((ROOT / "synthetic" / "fixture").glob("SYNTHETIC_ITA_300A_*.csv")):
            missing = [c for c in _header(path) if c not in self.doc]
            self.assertEqual(missing, [], path.name)


class TestDatasheet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DATASHEET.read_text(encoding="utf-8")

    def test_gebru_sections_present(self):
        for h in ("Motivation", "Composition", "Collection process",
                  "Preprocessing/cleaning/labeling", "Uses", "Distribution", "Maintenance"):
            self.assertRegex(self.text, r"(?m)^## %s\s*$" % re.escape(h))

    def test_links_the_dictionary(self):
        self.assertIn("docs/data_dictionary.csv", self.text)

    def test_headline_counts_match_committed_tables(self):
        overall = _read(TABLES / "quality_overall.csv")[0]
        n = int(float(overall["n_filings"]))
        flagged = int(float(overall["n_implausible"]))
        self.assertIn("{:,}".format(n), self.text)
        self.assertIn("{:,}".format(flagged), self.text)
        self.assertIn("{:,}".format(n - flagged), self.text)
        cov = {r["metric"]: int(r["value"]) for r in _read(TABLES / "panel_coverage.csv")}
        self.assertIn("{:,}".format(cov["distinct_establishment_ids"]), self.text)
        self.assertIn("{:,}".format(cov["establishment_ids_with_multiple_ein"]), self.text)

    def test_per_year_table_matches(self):
        for r in _read(TABLES / "quality_by_year.csv"):
            line = "| %d | %s | %s |" % (
                int(float(r["label"])),
                "{:,}".format(int(float(r["n_filings"]))),
                "{:,}".format(int(float(r["n_implausible"]))),
            )
            self.assertIn(line, self.text)


if __name__ == "__main__":
    unittest.main()
