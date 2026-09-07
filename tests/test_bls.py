"""Offline tests for the BLS fetcher (no network)."""

from __future__ import annotations

import unittest

import _context  # noqa: F401

from ehs_osha.bls import build_url, to_frame


class TestBls(unittest.TestCase):
    def test_build_url(self) -> None:
        self.assertEqual(
            build_url("ABC", 2016, 2024),
            "https://api.bls.gov/publicAPI/v2/timeseries/data/ABC?startyear=2016&endyear=2024",
        )

    def test_to_frame_parses_payload(self) -> None:
        payload = {"Results": {"series": [{"seriesID": "ABC", "data": [
            {"year": "2024", "value": "2.4"}, {"year": "2023", "value": "2.7"}]}]}}
        f = to_frame(payload)
        self.assertEqual(list(f["year"]), [2023, 2024])
        self.assertAlmostEqual(f["value"].iloc[0], 2.7)

    def test_to_frame_empty(self) -> None:
        f = to_frame({"Results": {"series": [{"seriesID": "ABC", "data": []}]}})
        self.assertEqual(len(f), 0)
        self.assertEqual(list(f.columns), ["series_id", "year", "value"])


if __name__ == "__main__":
    unittest.main()
