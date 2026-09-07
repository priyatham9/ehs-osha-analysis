"""Reconcile this repository's aggregate-TRIR figures with ehs-benchmarks.

The author's earlier repository, ``github.com/priyatham9/ehs-benchmarks``,
reported on a smaller panel (the CY2023-2025 ITA files, 1.18M filings) with a
100-4,000 hours-per-employee screen and stated an aggregate TRIR of 0.45
unscreened against 3.41 screened, a 7.58x ratio. This repository pools
CY2016-2024 under a 120-4,500 screen. Both sets of figures are panel-specific,
and this module makes the dependence explicit by recomputing the aggregate under
both definitions from the same loaded frame.

Nothing here reads the older repository's output. The "old" row is what this
codebase produces when restricted to the old panel and the old screen; whether
it matches the older published figures is reported, not assumed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd

from .quality import PlausibilityConfig, apply_screen, summarise_screen

#: Figures published in the README of ehs-benchmarks, transcribed for comparison.
OLD_PUBLISHED: Dict[str, float] = {
    "n_filings": 1_180_000.0,
    "aggregate_trir_unscreened": 0.45,
    "aggregate_trir_screened": 3.41,
    "ratio_screened_to_unscreened": 7.58,
}

OLD_YEARS: Sequence[int] = (2023, 2024, 2025)
OLD_SCREEN = PlausibilityConfig(min_hours_per_employee=100.0, max_hours_per_employee=4000.0)
NEW_SCREEN = PlausibilityConfig()

RATIO_TOLERANCE = 0.05  # relative
TRIR_TOLERANCE = 0.05  # relative


def _panel_row(
    df: pd.DataFrame, years: Optional[Iterable[int]], cfg: PlausibilityConfig, label: str
) -> dict:
    sub = df if years is None else df[df["year_filing_for"].isin(list(years))]
    years_present = sorted(int(y) for y in sub["year_filing_for"].dropna().unique())
    summ = summarise_screen(apply_screen(sub, cfg), label=label)
    rec = summ.to_json()
    rec["years"] = "-".join(str(y) for y in (years_present[:1] + years_present[-1:])) if years_present else ""
    rec["years_present"] = ",".join(str(y) for y in years_present)
    rec["min_hours_per_employee"] = cfg.min_hours_per_employee
    rec["max_hours_per_employee"] = cfg.max_hours_per_employee
    return rec


def reconcile_panels(
    df: pd.DataFrame,
    *,
    old_years: Sequence[int] = OLD_YEARS,
    old_screen: PlausibilityConfig = OLD_SCREEN,
    new_screen: PlausibilityConfig = NEW_SCREEN,
    lows: Sequence[float] = (100.0, 120.0),
    highs: Sequence[float] = (4000.0, 4500.0),
) -> pd.DataFrame:
    """Recompute the aggregate TRIR under the old and new panel definitions.

    Args:
        df: Harmonised, deduplicated frame from :func:`ehs_osha.load.load_ita_300a`.
        old_years: Reporting years that define the older panel.
        old_screen: Bounds used by the older repository.
        new_screen: Bounds used here.
        lows: Lower bounds for the screen-sensitivity rows on the old years.
        highs: Upper bounds for the same.

    Returns:
        One row per panel definition. ``panel`` is ``old``, ``new`` or
        ``old_years_sensitivity``. The ``old`` row also carries the published
        ehs-benchmarks figures and the relative gap to each.
    """
    rows: List[dict] = []
    old = _panel_row(df, old_years, old_screen, "old")
    old["panel"] = "old"
    for key, pub in OLD_PUBLISHED.items():
        got = float(old[key])
        old[f"published_{key}"] = pub
        old[f"rel_gap_{key}"] = (got - pub) / pub if pub else float("nan")
    old["ratio_reproduced_within_tolerance"] = bool(
        abs(old["rel_gap_ratio_screened_to_unscreened"]) <= RATIO_TOLERANCE
    )
    rows.append(old)

    new = _panel_row(df, None, new_screen, "new")
    new["panel"] = "new"
    rows.append(new)

    for lo in lows:
        for hi in highs:
            if hi <= lo:
                continue
            cfg = PlausibilityConfig(min_hours_per_employee=lo, max_hours_per_employee=hi)
            rec = _panel_row(df, old_years, cfg, f"old_years_{lo:g}-{hi:g}")
            rec["panel"] = "old_years_sensitivity"
            rows.append(rec)

    out = pd.DataFrame(rows)
    lead = ["panel", "label", "years", "years_present", "min_hours_per_employee",
            "max_hours_per_employee", "n_filings", "n_implausible", "implausible_share",
            "hours_share_implausible", "aggregate_trir_unscreened",
            "aggregate_trir_screened", "ratio_screened_to_unscreened"]
    rest = [c for c in out.columns if c not in lead]
    return out[lead + rest]


def write_reconciliation(df: pd.DataFrame, out_dir: Path) -> Path:
    """Run :func:`reconcile_panels` and write ``reconciliation_panels.csv``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    table = reconcile_panels(df)
    path = out_dir / "reconciliation_panels.csv"
    table.to_csv(path, index=False)
    return path


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Load the real files and write the reconciliation table."""
    import argparse

    from .load import load_ita_300a

    root = Path(__file__).resolve().parents[2]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=root / "data" / "raw")
    ap.add_argument("--out-dir", type=Path, default=root / "outputs" / "tables")
    ap.add_argument("--include-partial", action="store_true",
                    help="Include the partial 2025 file if present locally.")
    args = ap.parse_args(argv)
    df, _ = load_ita_300a(args.data_dir, include_partial=args.include_partial)
    path = write_reconciliation(df, args.out_dir)
    table = pd.read_csv(path)
    with pd.option_context("display.width", 200, "display.max_columns", 40):
        print(table[["panel", "label", "years_present", "n_filings",
                     "aggregate_trir_unscreened", "aggregate_trir_screened",
                     "ratio_screened_to_unscreened"]].to_string(index=False))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
