"""Specification-curve / threshold-robustness analysis of the implausibility screen.

Reads only committed tables in ``outputs/tables/``:

- ``quality_sensitivity_grid.csv``: the screen re-run over 25 pairs of
  hours-per-employee bounds (lower 100-400, upper 3,500-6,000)
- ``quality_overall.csv``: the default screen (120-4,500)
- ``quality_hours_concentration.csv``: share of hours and cases held by the
  top-N filings by reported hours (a screen that uses no threshold at all)

It writes ``outputs/tables/threshold_robustness_cells.csv`` (one row per
specification, with the flagged hours and cases recovered from the grid),
``outputs/tables/threshold_robustness_summary.csv`` (one row per derived
quantity, including marginal-band rates and a rank-trim cross-check) and
``docs/THRESHOLD_ROBUSTNESS.md``. Run ``python3 -m ehs_osha.threshold_robustness``
with ``src`` on ``PYTHONPATH``. ``tests/test_threshold_robustness.py`` fails if
any of the three files drifts from the script output.

Nothing here re-screens raw filings: every number is arithmetic on committed
tables.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TABLES = ROOT / "outputs" / "tables"
DOC = ROOT / "docs" / "THRESHOLD_ROBUSTNESS.md"
CELLS = TABLES / "threshold_robustness_cells.csv"
SUMMARY = TABLES / "threshold_robustness_summary.csv"

DEFAULT_LOW = 120.0
DEFAULT_HIGH = 4500.0
TRIR_FACTOR = 200_000.0
ROUND = 9

CELL_COLUMNS = [
    "label",
    "min_hours_per_employee",
    "max_hours_per_employee",
    "is_default",
    "n_implausible",
    "implausible_share",
    "flagged_hours",
    "flagged_cases",
    "screened_hours",
    "screened_cases",
    "aggregate_trir_unscreened",
    "aggregate_trir_screened",
    "ratio_screened_to_unscreened",
    "trir_screened_minus_default",
    "trir_screened_pct_from_default",
    "implausible_share_over_default",
    "trir_rank_desc",
]
SUMMARY_COLUMNS = ["section", "metric", "value", "unit", "source_tables"]


def load(tables: Path = TABLES) -> Dict[str, pd.DataFrame]:
    """Read the committed input tables."""
    names = ["quality_sensitivity_grid", "quality_overall", "quality_hours_concentration"]
    return {n: pd.read_csv(tables / f"{n}.csv") for n in names}


def build_cells(grid: pd.DataFrame, overall: pd.DataFrame) -> pd.DataFrame:
    """One row per specification with the screened and flagged totals."""
    g = grid.copy()
    hours_total = float(g["hours_total"].iloc[0])
    cases_total = float(g["cases_total"].iloc[0])
    g["flagged_hours"] = (g["hours_share_implausible"] * hours_total).round().astype("int64")
    g["flagged_cases"] = (g["cases_share_implausible"] * cases_total).round().astype("int64")
    g["screened_hours"] = int(round(hours_total)) - g["flagged_hours"]
    g["screened_cases"] = int(round(cases_total)) - g["flagged_cases"]
    is_default = (g["min_hours_per_employee"] == DEFAULT_LOW) & (
        g["max_hours_per_employee"] == DEFAULT_HIGH
    )
    g["is_default"] = is_default
    default = g[is_default].iloc[0]
    if abs(default["aggregate_trir_screened"] - overall["aggregate_trir_screened"].iloc[0]) > 1e-12:
        raise ValueError("default grid cell does not match quality_overall.csv")
    g["trir_screened_minus_default"] = (
        g["aggregate_trir_screened"] - default["aggregate_trir_screened"]
    )
    g["trir_screened_pct_from_default"] = (
        100.0 * g["trir_screened_minus_default"] / default["aggregate_trir_screened"]
    )
    g["implausible_share_over_default"] = g["implausible_share"] / default["implausible_share"]
    g["trir_rank_desc"] = g["aggregate_trir_screened"].rank(ascending=False, method="first")
    g["trir_rank_desc"] = g["trir_rank_desc"].astype(int)
    g = g.sort_values(["min_hours_per_employee", "max_hours_per_employee"]).reset_index(drop=True)
    out = g[CELL_COLUMNS].copy()
    num = out.select_dtypes("float").columns
    out[num] = out[num].round(ROUND)
    return out


def _s(section, metric, value, unit, source):
    if isinstance(value, float):
        value = round(value, ROUND)
    return {
        "section": section,
        "metric": metric,
        "value": value,
        "unit": unit,
        "source_tables": source,
    }


def _cell(cells: pd.DataFrame, lo: float, hi: float) -> pd.Series:
    return cells[(cells.min_hours_per_employee == lo) & (cells.max_hours_per_employee == hi)].iloc[0]


def _band_rate(a: pd.Series, b: pd.Series) -> dict:
    """Filings, hours, cases and TRIR of the filings flagged in ``b`` but not ``a``.

    The flagged sets are nested along one bound, so the difference of the
    flagged totals is exactly the band that enters (or leaves) the flagged set.
    """
    d_n = int(abs(b.n_implausible - a.n_implausible))
    d_h = int(abs(b.flagged_hours - a.flagged_hours))
    d_c = int(abs(b.flagged_cases - a.flagged_cases))
    return {"filings": d_n, "hours": d_h, "cases": d_c, "trir": TRIR_FACTOR * d_c / d_h if d_h else float("nan")}


def build_summary(t: Dict[str, pd.DataFrame], cells: pd.DataFrame) -> pd.DataFrame:
    """Derived quantities: ranges, main effects, marginal bands, rank-trim check."""
    src = "quality_sensitivity_grid"
    rows: List[dict] = []
    d = _cell(cells, DEFAULT_LOW, DEFAULT_HIGH)
    trir = cells["aggregate_trir_screened"]
    rows += [
        _s("ranges", "n_specifications", int(len(cells)), "cells", src),
        _s("ranges", "trir_unscreened_all_cells", float(cells["aggregate_trir_unscreened"].iloc[0]), "TRIR", src),
        _s("ranges", "trir_unscreened_constant_across_cells", bool(cells["aggregate_trir_unscreened"].nunique() == 1), "flag", src),
        _s("ranges", "trir_screened_default", float(d.aggregate_trir_screened), "TRIR", src),
        _s("ranges", "trir_screened_min", float(trir.min()), "TRIR", src),
        _s("ranges", "trir_screened_max", float(trir.max()), "TRIR", src),
        _s("ranges", "trir_screened_range", float(trir.max() - trir.min()), "TRIR", src),
        _s("ranges", "trir_screened_max_abs_pct_from_default", float(cells["trir_screened_pct_from_default"].abs().max()), "percent", src),
        _s("ranges", "ratio_min", float(cells["ratio_screened_to_unscreened"].min()), "x", src),
        _s("ranges", "ratio_max", float(cells["ratio_screened_to_unscreened"].max()), "x", src),
        _s("ranges", "implausible_share_default", float(d.implausible_share), "share", src),
        _s("ranges", "implausible_share_min", float(cells["implausible_share"].min()), "share", src),
        _s("ranges", "implausible_share_max", float(cells["implausible_share"].max()), "share", src),
        _s("ranges", "implausible_share_max_over_min", float(cells["implausible_share"].max() / cells["implausible_share"].min()), "x", src),
        _s("ranges", "n_implausible_min", int(cells["n_implausible"].min()), "filings", src),
        _s("ranges", "n_implausible_max", int(cells["n_implausible"].max()), "filings", src),
        _s("ranges", "cells_with_screened_trir_above_unscreened", int((trir > cells["aggregate_trir_unscreened"]).sum()), "cells", src),
    ]
    # Share of hours held by flagged filings, from the grid directly.
    g = t["quality_sensitivity_grid"].set_index("label").loc[cells["label"]]
    rows += [
        _s("ranges", "hours_share_flagged_min", float(g["hours_share_implausible"].min()), "share", src),
        _s("ranges", "hours_share_flagged_max", float(g["hours_share_implausible"].max()), "share", src),
        _s("ranges", "cases_share_flagged_min", float(g["cases_share_implausible"].min()), "share", src),
        _s("ranges", "cases_share_flagged_max", float(g["cases_share_implausible"].max()), "share", src),
    ]
    # Main effects: mean screened TRIR by each bound, other bound averaged out.
    for col, name in (("min_hours_per_employee", "lower"), ("max_hours_per_employee", "upper")):
        means = cells.groupby(col)["aggregate_trir_screened"].mean()
        for k, v in means.items():
            rows.append(_s("main_effect", f"mean_screened_trir_{name}_bound_{k:g}", float(v), "TRIR", src))
        rows.append(_s("main_effect", f"{name}_bound_spread_of_means", float(means.max() - means.min()), "TRIR", src))
    # Marginal bands: the filings that change status as one bound moves, other bound fixed at default.
    pairs = [
        ("lower_bound_120_to_400", (DEFAULT_LOW, DEFAULT_HIGH), (400.0, DEFAULT_HIGH)),
        ("lower_bound_100_to_120", (100.0, DEFAULT_HIGH), (DEFAULT_LOW, DEFAULT_HIGH)),
        ("upper_bound_3500_to_4500", (DEFAULT_LOW, 3500.0), (DEFAULT_LOW, DEFAULT_HIGH)),
        ("upper_bound_4500_to_6000", (DEFAULT_LOW, DEFAULT_HIGH), (DEFAULT_LOW, 6000.0)),
    ]
    for name, a, b in pairs:
        r = _band_rate(_cell(cells, *a), _cell(cells, *b))
        rows += [
            _s("marginal_band", f"{name}_filings", r["filings"], "filings", src),
            _s("marginal_band", f"{name}_hours", r["hours"], "hours", src),
            _s("marginal_band", f"{name}_cases", r["cases"], "cases", src),
            _s("marginal_band", f"{name}_trir", r["trir"], "TRIR", src),
        ]
    # Corner-to-corner extremes of the whole grid.
    lo_c, hi_c = cells.loc[trir.idxmin()], cells.loc[trir.idxmax()]
    rows += [
        _s("extremes", "lowest_trir_cell", str(lo_c.label), "label", src),
        _s("extremes", "highest_trir_cell", str(hi_c.label), "label", src),
    ]
    # Threshold-free cross-check: drop the top-N filings by reported hours.
    conc = t["quality_hours_concentration"]
    ov = t["quality_overall"].iloc[0]
    hours_total, cases_total = float(ov["hours_total"]), float(d.screened_cases + d.flagged_cases)
    for _, r in conc.iterrows():
        n = int(r["top_n_filings_by_hours"])
        h = hours_total * (1.0 - float(r["hours_share"]))
        c = cases_total * (1.0 - float(r["cases_share"]))
        key = "quality_hours_concentration, quality_overall"
        rows += [
            _s("rank_trim", f"drop_top_{n}_by_hours_trir", TRIR_FACTOR * c / h, "TRIR", key),
            _s("rank_trim", f"drop_top_{n}_by_hours_share_of_filings", n / float(ov["n_filings"]), "share", key),
        ]
    out = pd.DataFrame(rows, columns=SUMMARY_COLUMNS)
    out["value"] = out["value"].astype(object)
    return out


def build_tables(tables: Path = TABLES) -> Dict[str, pd.DataFrame]:
    """Build both output tables from the committed inputs."""
    t = load(tables)
    cells = build_cells(t["quality_sensitivity_grid"], t["quality_overall"])
    return {"cells": cells, "summary": build_summary(t, cells)}


def _pct(x: float, nd: int = 2) -> str:
    return f"{100 * x:.{nd}f}%"


def build_doc(cells: pd.DataFrame, summary: pd.DataFrame) -> str:
    """Render docs/THRESHOLD_ROBUSTNESS.md from the two tables."""
    sv = summary.set_index("metric")["value"]

    def f(m: str) -> float:
        return float(sv[m])

    def i(m: str) -> int:
        return int(float(sv[m]))

    grid_rows = []
    highs = sorted(cells.max_hours_per_employee.unique())
    for lo in sorted(cells.min_hours_per_employee.unique()):
        parts = [f"{lo:g}"]
        for hi in highs:
            c = _cell(cells, lo, hi)
            parts.append(f"{c.aggregate_trir_screened:.3f} ({_pct(c.implausible_share)})")
        grid_rows.append("| " + " | ".join(parts) + " |")
    head = "| Lower bound (h) \\ upper bound (h) | " + " | ".join(f"{h:g}" for h in highs) + " |"
    sep = "|---|" + "---:|" * len(highs)

    def band(name: str) -> str:
        return (
            f"{i(name + '_filings'):,} filings, {i(name + '_hours'):,} hours, "
            f"{i(name + '_cases'):,} cases, band TRIR {f(name + '_trir'):.3f}"
        )

    total_hours = int(cells.screened_hours.iloc[0] + cells.flagged_hours.iloc[0])
    max_band_share = max(
        i(n + "_hours")
        for n in (
            "lower_bound_120_to_400",
            "lower_bound_100_to_120",
            "upper_bound_3500_to_4500",
            "upper_bound_4500_to_6000",
        )
    ) / total_hours
    band_trirs = [
        f(n + "_trir")
        for n in (
            "lower_bound_120_to_400",
            "lower_bound_100_to_120",
            "upper_bound_3500_to_4500",
            "upper_bound_4500_to_6000",
        )
    ]
    trim_rows = []
    for n in (1, 10, 100, 1000, 10000):
        trim_rows.append(
            f"| {n:,} | {_pct(f(f'drop_top_{n}_by_hours_share_of_filings'), 4)} | "
            f"{f(f'drop_top_{n}_by_hours_trir'):.3f} |"
        )

    return f"""# Threshold robustness of the implausibility screen

Generated by `python3 -m ehs_osha.threshold_robustness` from committed tables in `outputs/tables/`; the numbers are in `outputs/tables/threshold_robustness_cells.csv` and `outputs/tables/threshold_robustness_summary.csv`. Do not edit by hand: `tests/test_threshold_robustness.py` fails if this page differs from the script output.

## Question

The screen flags a filing when its hours per average employee fall outside a lower and an upper bound. The default (120 and 4,500) is a judgement. Do the two headline conclusions, that screening raises the pooled aggregate TRIR from {f('trir_unscreened_all_cells'):.3f} to {f('trir_screened_default'):.3f} and that about {_pct(f('implausible_share_default'), 1)} of filings are flagged, depend on that judgement?

## Method

This is a specification curve over the one researcher choice the screen has: all {i('n_specifications')} pairs of lower bound (100, 120, 200, 250, 400) and upper bound (3,500, 4,000, 4,500, 5,000, 6,000) in `quality_sensitivity_grid.csv`, which the pipeline computed on the real filings. Nothing is re-screened here. Because a filing is flagged by a bound on one variable, the flagged sets are nested along each bound, so subtracting flagged totals between two cells gives exactly the filings that change status between them (the marginal bands below). Flagged hours and cases are recovered as share times the pooled total. The other flags (missing or non-positive hours, missing employees, contradictory counts) do not depend on the bounds and are held fixed.

## Result 1: the aggregate TRIR barely moves

Screened TRIR and flagged share (in brackets) in every cell; default cell is 120 / 4,500.

{head}
{sep}
{chr(10).join(grid_rows)}

- Screened aggregate TRIR runs from {f('trir_screened_min'):.3f} to {f('trir_screened_max'):.3f}, a range of {f('trir_screened_range'):.3f}. The largest departure from the default ({f('trir_screened_default'):.3f}) is {f('trir_screened_max_abs_pct_from_default'):.2f}%.
- The unscreened TRIR is {f('trir_unscreened_all_cells'):.3f} in every cell, because it does not use the bounds. The screened rate exceeds it in {i('cells_with_screened_trir_above_unscreened')} of {i('n_specifications')} cells; the ratio runs from {f('ratio_min'):.2f}x to {f('ratio_max'):.2f}x.
- Averaging out the other bound, the mean screened TRIR changes by {f('lower_bound_spread_of_means'):.3f} across the five lower bounds and by {f('upper_bound_spread_of_means'):.3f} across the five upper bounds.
- The cell with the lowest screened TRIR is {sv['lowest_trir_cell']}; the highest is {sv['highest_trir_cell']}.

## Result 2: the flagged share does move, and that is expected

The flagged share runs from {_pct(f('implausible_share_min'))} ({i('n_implausible_min'):,} filings) to {_pct(f('implausible_share_max'))} ({i('n_implausible_max'):,} filings), a factor of {f('implausible_share_max_over_min'):.1f} between the extremes. So the statement "about 2% of filings are flagged" is a property of the chosen bounds and should be quoted with the range. What stays put is the weight of what is flagged: flagged filings hold {_pct(f('hours_share_flagged_min'))} to {_pct(f('hours_share_flagged_max'))} of all reported hours and {_pct(f('cases_share_flagged_min'))} to {_pct(f('cases_share_flagged_max'))} of all reported cases in every cell.

## Why: the filings that move carry almost no hours

Moving a bound re-classifies a band of filings. At the default for the other bound:

- Lower bound 120 to 400: {band('lower_bound_120_to_400')}.
- Lower bound 100 to 120: {band('lower_bound_100_to_120')}.
- Upper bound 4,500 to 3,500 (filings that enter the flagged set): {band('upper_bound_3500_to_4500')}.
- Upper bound 4,500 to 6,000: {band('upper_bound_4500_to_6000')}.

The largest band holds {_pct(max_band_share, 3)} of the {total_hours:,} pooled hours. The bands' own rates ({min(band_trirs):.1f} to {max(band_trirs):.1f}) differ from the screened aggregate, but they are too small a part of the denominator to move it. The aggregate is set by the few filings with enormous hours, which every cell flags.

## Cross-check with no threshold on hours per employee

Instead of a bound, drop the N filings with the most reported hours (`quality_hours_concentration.csv`) and recompute the aggregate TRIR:

| N dropped | Share of filings | Aggregate TRIR |
|---:|---:|---:|
{chr(10).join(trim_rows)}

Dropping the single largest filing lifts the rate from {f('trir_unscreened_all_cells'):.3f} to {f('drop_top_1_by_hours_trir'):.3f}; dropping the 10,000 largest (0.36% of filings) gives {f('drop_top_10000_by_hours_trir'):.3f}, the same order of magnitude as the screened {f('trir_screened_default'):.3f}. The trim is cruder than the screen and does not converge to it, but it points the same way: the unscreened rate is low because of a few extreme filings, not because of where a bound was drawn.

## Plain-language interpretation

Whatever reasonable bounds are used in the grid, the screened pooled rate comes out between {f('trir_screened_min'):.2f} and {f('trir_screened_max'):.2f} injuries per 100 full-time workers, against 0.13 unscreened. The choice of bounds changes how many filings are called implausible, but not how the aggregate looks, because a handful of filings with impossible hours dominate the denominator and every version of the screen catches them.

## Limits

- **Grid, not universe.** The lower bounds span 100 to 400 and the upper bounds 3,500 to 6,000, as set in `quality.sensitivity_grid`. Bounds outside that region are not tested; the committed tables cannot answer for them.
- **Pooled only.** The grid is committed for the pooled nine years. Per-year behaviour under other bounds is not in the committed tables; only the default is, in `quality_by_year.csv`. The year spread of the unscreened rate is a separate result in the README.
- **One variable.** Only the two hours-per-employee bounds vary. The other flags are fixed and their thresholds (for example employees below 1) are not varied.
- **Robust to thresholds is not the same as correct.** The analysis shows the aggregate is insensitive to where the bounds sit. It does not show that every flagged filing is wrong or that the screened rate equals a true national rate; the data are self-reported and not a sample of the US workforce.
- **Rank-trim check is crude.** Dropping the largest filings by hours also drops legitimately large employers, and it does not target implausible filings specifically. It is a check on mechanism, not a replacement screen.
- **Recovered totals.** Flagged hours and cases are recovered from shares times pooled totals and rounded to integers; differences between cells are exact up to that rounding.
- **No uncertainty interval.** The grid varies a specification, not the sample; no sampling variance is claimed.
"""


def main() -> None:
    """Write both tables and the docs page."""
    tabs = build_tables()
    tabs["cells"].to_csv(CELLS, index=False)
    tabs["summary"].to_csv(SUMMARY, index=False)
    DOC.write_text(build_doc(tabs["cells"], tabs["summary"]), encoding="utf-8")
    print(f"wrote {CELLS}\nwrote {SUMMARY}\nwrote {DOC}")


if __name__ == "__main__":
    main()
