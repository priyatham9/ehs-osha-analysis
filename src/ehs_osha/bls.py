"""Fetcher for BLS Survey of Occupational Injuries and Illnesses (SOII) rates.

Purpose: pull the published private-industry total recordable case (TRC) rate,
and where available the NAICS 325 (chemical manufacturing) rate, for the years
the ITA panel covers, so the screened and unscreened aggregate TRIR can be set
against an independent published benchmark.

Status (2026-09-07, see ``data/bls/PROVENANCE.txt``): from this machine the
BLS public API v2 endpoint answers, but ``www.bls.gov`` and
``download.bls.gov`` (where the SOII tables and the ``is.series`` catalog that
maps series IDs to titles live) return HTTP 403. Without the catalog the exact
SOII series ID for "private industry, total recordable cases, rate per 100 FTE"
cannot be confirmed, and an unconfirmed ID would be a guess. The fetcher is
therefore written and left parameterised on ``series_id``: no series ID is
hard-coded and no published rate is entered by hand. When a confirmed ID is
supplied, :func:`fetch_series` caches the raw JSON under ``data/bls/`` and
:func:`to_frame` turns it into a ``year, value`` table.

API used: ``https://api.bls.gov/publicAPI/v2/timeseries/data/<SERIES_ID>``
with ``startyear``/``endyear`` query parameters (no key needed, 10-year limit
per request). Public series catalog (blocked from this host at time of
writing): ``https://download.bls.gov/pub/time.series/is/is.series``.

Usage::

    python3 -m ehs_osha.bls --series-id <CONFIRMED_ID> --start 2016 --end 2024
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import pandas as pd

API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/{series_id}"
CATALOG_URL = "https://download.bls.gov/pub/time.series/is/is.series"
ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "data" / "bls"


def build_url(series_id: str, start: int, end: int) -> str:
    """Return the API URL for one series over a year range."""
    return API_URL.format(series_id=series_id) + f"?startyear={start}&endyear={end}"


def fetch_series(
    series_id: str, start: int, end: int, cache_dir: Path = CACHE_DIR, timeout: float = 30.0
) -> dict:
    """Download one BLS series as JSON, cache it and append provenance.

    Raises:
        RuntimeError: If the API reports a failure or an empty series (BLS
            answers "Series does not exist" with an empty ``data`` list).
    """
    url = build_url(series_id, start, end)
    req = urllib.request.Request(url, headers={"User-Agent": "ehs-osha-analysis"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    payload = json.loads(raw)
    series = payload.get("Results", {}).get("series", [])
    if payload.get("status") != "REQUEST_SUCCEEDED" or not series or not series[0].get("data"):
        raise RuntimeError(f"BLS returned no data for {series_id}: {payload.get('message')}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{series_id}_{start}_{end}.json").write_bytes(raw)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with (cache_dir / "PROVENANCE.txt").open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp}  {series_id}  {url}\n")
    return payload


def to_frame(payload: dict) -> pd.DataFrame:
    """Flatten an API payload into ``series_id, year, value`` rows."""
    rows: List[dict] = []
    for s in payload.get("Results", {}).get("series", []):
        for d in s.get("data", []):
            rows.append({"series_id": s["seriesID"], "year": int(d["year"]), "value": float(d["value"])})
    return pd.DataFrame(rows).sort_values(["series_id", "year"]).reset_index(drop=True) if rows else pd.DataFrame(
        columns=["series_id", "year", "value"]
    )


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Fetch and cache one BLS SOII series.")
    ap.add_argument("--series-id", required=True, help="Confirmed BLS series ID (see module docstring).")
    ap.add_argument("--start", type=int, default=2016)
    ap.add_argument("--end", type=int, default=2024)
    args = ap.parse_args(argv)
    frame = to_frame(fetch_series(args.series_id, args.start, args.end))
    frame.to_csv(CACHE_DIR / f"{args.series_id}_{args.start}_{args.end}.csv", index=False)
    print(frame.to_string(index=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
