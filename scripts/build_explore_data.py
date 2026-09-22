"""Build docs/explore-data.json for the denominator explorer (docs/explore.html).

Reads only committed pipeline outputs, so it runs without the raw OSHA files:

    outputs/tables/peer_percentiles_pooled.csv
    outputs/tables/quality_by_year.csv
    outputs/tables/quality_overall.csv
    outputs/tables/quality_top50_implausible_hours.csv
    outputs/summary.json            (screen bounds)

NAICS subsector titles come from ``ehs_osha.naics.NAICS3_TITLES``. A code with
no official title (the files contain some malformed codes) gets an empty title
rather than a guess.

Usage::

    python scripts/build_explore_data.py
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ehs_osha.naics import NAICS3_TITLES  # noqa: E402

TABLES = ROOT / "outputs" / "tables"
OUT = ROOT / "docs" / "explore-data.json"

SIZE_BANDS = ["001-019", "020-049", "050-099", "100-249", "250-499", "500-999", "1000+"]


def _rows(name: str) -> list:
    with open(TABLES / name, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _f(value: str, digits: int = 6):
    """Parse a float and round it for a compact JSON file; None for blanks."""
    if value in ("", "nan", "NaN", None):
        return None
    return round(float(value), digits)


def build() -> dict:
    peers_csv = _rows("peer_percentiles_pooled.csv")
    codes = sorted({r["naics3"] for r in peers_csv})
    titles = {c: NAICS3_TITLES[c] for c in codes if c in NAICS3_TITLES}

    peers = []
    for r in peers_csv:
        peers.append({
            "naics3": r["naics3"],
            "title": titles.get(r["naics3"], ""),
            "size_band": r["size_band"],
            "n": int(r["n"]),
            "n_with_metric": int(r["n_with_metric"]),
            "publishable": r["publishable"] == "True",
            "zero_share": _f(r["zero_share"]),
            "aggregate_trir": _f(r["aggregate_trir"]),
            "p10": _f(r["p10"]),
            "p25": _f(r["p25"]),
            "p50": _f(r["p50"]),
            "p75": _f(r["p75"]),
            "p90": _f(r["p90"]),
            "p95": _f(r["p95"]),
        })

    by_year = []
    for r in _rows("quality_by_year.csv"):
        by_year.append({
            "year": int(float(r["label"])),
            "n_filings": int(r["n_filings"]),
            "n_implausible": int(r["n_implausible"]),
            "implausible_share": _f(r["implausible_share"], 8),
            "hours_share_implausible": _f(r["hours_share_implausible"], 8),
            "trir_unscreened": _f(r["aggregate_trir_unscreened"], 8),
            "trir_screened": _f(r["aggregate_trir_screened"], 8),
            "ratio": _f(r["ratio_screened_to_unscreened"], 6),
        })
    y2019 = next(r for r in by_year if r["year"] == 2019)
    hours_2019 = next(float(r["hours_total"]) for r in _rows("quality_by_year.csv")
                      if int(float(r["label"])) == 2019)

    ov = _rows("quality_overall.csv")[0]
    pooled = {
        "n_filings": int(ov["n_filings"]),
        "n_implausible": int(ov["n_implausible"]),
        "implausible_share": _f(ov["implausible_share"], 8),
        "hours_share_implausible": _f(ov["hours_share_implausible"], 8),
        "trir_unscreened": _f(ov["aggregate_trir_unscreened"], 8),
        "trir_screened": _f(ov["aggregate_trir_screened"], 8),
        "ratio": _f(ov["ratio_screened_to_unscreened"], 6),
    }

    top = _rows("quality_top50_implausible_hours.csv")[0]
    top_hours = float(top["total_hours_worked"])
    top_filing = {
        "year": int(float(top["year_filing_for"])),
        "naics_code": str(int(float(top["naics_code"]))),
        "annual_average_employees": int(float(top["annual_average_employees"])),
        "total_hours_worked": top_hours,
        "recordable_cases": int(float(top["recordable_cases"])),
        "share_of_year_hours": round(top_hours / hours_2019, 6) if int(float(top["year_filing_for"])) == 2019 else None,
        "share_of_all_hours": round(top_hours / float(ov["hours_total"]), 6),
    }

    screen = json.loads((ROOT / "outputs" / "summary.json").read_text(encoding="utf-8"))["quality"]["screen_config"]

    return {
        "generated_from": ", ".join([
            "outputs/tables/peer_percentiles_pooled.csv",
            "outputs/tables/quality_by_year.csv",
            "outputs/tables/quality_overall.csv",
            "outputs/tables/quality_top50_implausible_hours.csv",
            "outputs/summary.json",
            "src/ehs_osha/naics.py (titles)",
        ]),
        "naics3_list": codes,
        "titles": titles,
        "size_bands": SIZE_BANDS,
        "peers": peers,
        "quality_by_year": by_year,
        "pooled": pooled,
        "note_2019": {
            "hours_share_implausible": y2019["hours_share_implausible"],
            "ratio_screened_to_unscreened": y2019["ratio"],
            "trir_unscreened": y2019["trir_unscreened"],
            "trir_screened": y2019["trir_screened"],
        },
        "top_filing": top_filing,
        "screen_rule": {
            "min_hours_per_employee": float(screen["min_hours_per_employee"]),
            "max_hours_per_employee": float(screen["max_hours_per_employee"]),
        },
    }


def main() -> None:
    data = build()
    OUT.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(data['peers'])} peer cells, "
          f"{len(data['titles'])} titled NAICS-3 codes")


if __name__ == "__main__":
    main()
