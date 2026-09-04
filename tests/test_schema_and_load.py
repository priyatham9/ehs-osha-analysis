"""Tests for schema harmonisation, encoding fallback, dedup and derived fields."""

from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

import _context  # noqa: F401
import numpy as np
import pandas as pd

from ehs_osha import schema
from ehs_osha.load import (
    LoadReport,
    SchemaError,
    coerce_numeric,
    deduplicate,
    derive_fields,
    load_csv_fixture,
    read_published_file,
)

MINIMAL_HEADER = (
    "id,establishment_id,naics_code,annual_average_employees,total_hours_worked,"
    "no_injuries_illnesses,total_deaths,total_dafw_cases,total_djtr_cases,"
    "total_other_cases,year_filing_for,company_name"
)


def _write_csv(path: Path, rows: list[str], encoding: str = "utf-8") -> Path:
    """Write a minimal ITA-shaped CSV for testing."""
    path.write_text("\n".join([MINIMAL_HEADER] + rows) + "\n", encoding=encoding)
    return path


class TestSchema(unittest.TestCase):
    """Schema helpers must be order-insensitive and explicit about gaps."""

    def test_normalise_strips_and_lowercases(self) -> None:
        self.assertEqual(
            schema.normalise_columns([" ID ", "Total_Hours_Worked"]),
            ["id", "total_hours_worked"],
        )

    def test_select_canonical_preserves_canonical_order(self) -> None:
        shuffled = ["total_hours_worked", "id", "naics_code"]
        got = schema.select_canonical(shuffled)
        self.assertEqual(got.index("id"), 0)
        self.assertIn("total_hours_worked", got)

    def test_missing_required_reports_gaps(self) -> None:
        self.assertEqual(schema.missing_required(schema.CANONICAL_COLUMNS), [])
        missing = schema.missing_required(["id", "company_name"])
        self.assertIn("total_hours_worked", missing)

    def test_recordable_components_do_not_double_count(self) -> None:
        # total_injuries and the illness columns are a different partition of the
        # same cases and must not be in the recordable sum.
        for col in ("total_injuries", "total_other_illnesses"):
            self.assertNotIn(col, schema.RECORDABLE_COMPONENTS)
        self.assertEqual(len(schema.RECORDABLE_COMPONENTS), 4)


class TestLoad(unittest.TestCase):
    """Loading must survive the real files' encoding and layout quirks."""

    def test_reads_zip_member(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            csv = _write_csv(Path(td) / "inner.csv", ["1,10,3251,50,100000,1,0,1,0,1,2024,ACME"])
            zpath = Path(td) / "outer.zip"
            with zipfile.ZipFile(zpath, "w") as zf:
                zf.write(csv, "inner.csv")
            df = read_published_file(zpath, LoadReport())
            self.assertEqual(len(df), 1)
            self.assertEqual(int(df["naics_code"].iloc[0]), 3251)

    def test_zip_with_multiple_csvs_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            zpath = Path(td) / "two.zip"
            with zipfile.ZipFile(zpath, "w") as zf:
                zf.writestr("a.csv", MINIMAL_HEADER + "\n")
                zf.writestr("b.csv", MINIMAL_HEADER + "\n")
            with self.assertRaises(SchemaError):
                read_published_file(zpath, LoadReport())

    def test_missing_required_column_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.csv"
            p.write_text("id,company_name\n1,ACME\n", encoding="utf-8")
            with self.assertRaises(SchemaError):
                read_published_file(p, LoadReport())

    def test_cp1252_bytes_do_not_abort_the_load(self) -> None:
        # 0x92 is a Windows-1252 right single quote and is not valid UTF-8; the
        # real ITA Data CY 2018 file contains such bytes.
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "cp1252.csv"
            body = (
                MINIMAL_HEADER
                + "\n1,10,3251,50,100000,1,0,1,0,1,2024,O’BRIEN INC\n"
            )
            encoded = body.encode("cp1252")
            self.assertIn(0x92, encoded, "test fixture must contain the 0x92 byte")
            p.write_bytes(encoded)
            report = LoadReport()
            df = read_published_file(p, report)
            self.assertEqual(len(df), 1)
            self.assertEqual(report.encodings_used[p.name], "cp1252")

    def test_column_order_does_not_matter(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cols = MINIMAL_HEADER.split(",")
            rev = ",".join(reversed(cols))
            vals = "ACME,2024,1,0,1,0,1,100000,50,3251,10,1"
            p = Path(td) / "rev.csv"
            p.write_text(rev + "\n" + vals + "\n", encoding="utf-8")
            df = derive_fields(coerce_numeric(read_published_file(p, LoadReport())))
            self.assertEqual(int(df["annual_average_employees"].iloc[0]), 50)
            self.assertEqual(float(df["recordable_cases"].iloc[0]), 2.0)

    def test_deduplicate_keeps_latest_id(self) -> None:
        df = pd.DataFrame(
            {
                "id": [1, 7, 3],
                "establishment_id": [100, 100, 200],
                "year_filing_for": [2024, 2024, 2024],
                "total_hours_worked": [1000.0, 2000.0, 3000.0],
            }
        )
        report = LoadReport()
        out = deduplicate(df, report)
        self.assertEqual(len(out), 2)
        self.assertEqual(report.duplicate_rows_dropped, 1)
        kept = out.loc[out["establishment_id"] == 100, "total_hours_worked"].iloc[0]
        self.assertEqual(kept, 2000.0)

    def test_derived_fields_are_correct(self) -> None:
        df = pd.DataFrame(
            {
                "annual_average_employees": [100.0, 0.0],
                "total_hours_worked": [200000.0, 0.0],
                "total_deaths": [0.0, 0.0],
                "total_dafw_cases": [2.0, 0.0],
                "total_djtr_cases": [1.0, 0.0],
                "total_other_cases": [1.0, 0.0],
                "naics_code": [325199.0, 23.0],
            }
        )
        out = derive_fields(df)
        self.assertEqual(out["recordable_cases"].iloc[0], 4.0)
        self.assertEqual(out["dart_cases"].iloc[0], 3.0)
        self.assertEqual(out["hours_per_employee"].iloc[0], 2000.0)
        self.assertAlmostEqual(out["trir"].iloc[0], 4.0)
        self.assertAlmostEqual(out["dart_rate"].iloc[0], 3.0)
        self.assertEqual(out["naics3"].iloc[0], "325")
        # Zero employees and zero hours must not produce inf, and a 2-digit
        # NAICS code must not yield a bogus 3-digit prefix.
        self.assertTrue(np.isnan(out["hours_per_employee"].iloc[1]))
        self.assertTrue(np.isnan(out["trir"].iloc[1]))
        self.assertIsNone(out["naics3"].iloc[1])

    def test_fixture_round_trip_if_present(self) -> None:
        if not _context.fixture_available():
            self.skipTest("synthetic fixture not generated")
        path = sorted(_context.FIXTURE.glob("SYNTHETIC_ITA_300A_*.csv"))[0]
        df = load_csv_fixture(path)
        self.assertGreater(len(df), 0)
        for col in ("recordable_cases", "trir", "hours_per_employee", "naics3"):
            self.assertIn(col, df.columns)


if __name__ == "__main__":
    unittest.main()


class TestNaicsTitles(unittest.TestCase):
    """The NAICS subsector titles must be official, not data-derived.

    The OSHA files carry an establishment-supplied ``industry_description``
    naming a 6-digit industry. Using the modal value of that field to label a
    3-digit subsector produces confidently wrong names, so subsector labels
    come from the Census 2022 NAICS structure file instead.
    """

    def test_known_subsector_titles(self) -> None:
        from ehs_osha.naics import naics3_title

        expected = {
            "238": "Specialty Trade Contractors",
            "325": "Chemical Manufacturing",
            "332": "Fabricated Metal Product Manufacturing",
            "445": "Food and Beverage Retailers",
            "621": "Ambulatory Health Care Services",
            "622": "Hospitals",
            "623": "Nursing and Residential Care Facilities",
        }
        for code, title in expected.items():
            self.assertEqual(naics3_title(code), title, code)

    def test_unknown_code_returns_none_rather_than_guessing(self) -> None:
        from ehs_osha.naics import naics3_title

        for bad in ("999", "", "12", "notacode", None):
            self.assertIsNone(naics3_title(bad), repr(bad))

    def test_float_like_codes_are_accepted(self) -> None:
        from ehs_osha.naics import naics3_title

        self.assertEqual(naics3_title("622.0"), "Hospitals")
        self.assertEqual(naics3_title(622), "Hospitals")

    def test_table_covers_every_subsector_in_the_canonical_columns(self) -> None:
        from ehs_osha.naics import NAICS3_TITLES

        self.assertGreater(len(NAICS3_TITLES), 90)
        for code, title in NAICS3_TITLES.items():
            self.assertRegex(code, r"^\d{3}$")
            self.assertTrue(title and not title.endswith("T"), code)
