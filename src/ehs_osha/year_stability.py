"""Leave-one-year-out and year-over-year stability of the headline results.

Reads only committed tables in ``outputs/tables/``:

- ``quality_by_year.csv``: filings, flagged filings, hours and cases per year
- ``metrics_by_year.csv``: screened hours and TRIR numerator per year
- ``quality_overall.csv``: the pooled headline (used as a consistency check)
- ``percentile_band_stability.csv`` and ``peer_group_persistence.csv``:
  year-to-year Spearman rank correlation of peer-group percentiles

It writes ``outputs/tables/year_stability_loyo.csv`` (the pooled headline
recomputed with each year left out in turn, plus peer-group rank stability from
the adjacent-year pairs that remain), ``outputs/tables/year_stability_yoy.csv``
(per-year values and year-over-year changes),
``outputs/tables/year_stability_summary.csv`` and ``docs/YEAR_STABILITY.md``.
Run ``python3 -m ehs_osha.year_stability`` with ``src`` on ``PYTHONPATH``.
``tests/test_year_stability.py`` fails if any file drifts from the script output.

Nothing here re-screens raw filings: pooled quantities are exact sums of the
per-year committed totals, so leaving a year out is arithmetic, not a re-fit.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TABLES = ROOT / "outputs" / "tables"
DOC = ROOT / "docs" / "YEAR_STABILITY.md"
LOYO = TABLES / "year_stability_loyo.csv"
YOY = TABLES / "year_stability_yoy.csv"
SUMMARY = TABLES / "year_stability_summary.csv"

TRIR_FACTOR = 200_000.0
ROUND = 9
PCTS = ["p10", "p25", "p50", "p75", "p90", "p95"]

LOYO_COLUMNS = [
    "left_out_year",
    "n_filings",
    "n_implausible",
    "implausible_share",
    "implausible_share_minus_pooled",
    "hours_total",
    "hours_share_implausible",
    "aggregate_trir_unscreened",
    "aggregate_trir_unscreened_pct_from_pooled",
    "aggregate_trir_screened",
    "aggregate_trir_screened_pct_from_pooled",
    "ratio_screened_to_unscreened",
    "peer_pairs_remaining",
    "peer_mean_spearman_rho",
    "peer_min_spearman_rho",
]
YOY_COLUMNS = [
    "year",
    "n_filings",
    "implausible_share",
    "implausible_share_change",
    "hours_share_implausible",
    "aggregate_trir_unscreened",
    "aggregate_trir_screened",
    "aggregate_trir_screened_change",
    "aggregate_trir_screened_pct_change",
    "ratio_screened_to_unscreened",
    "peer_groups_matched_share_from_prior",
    "peer_mean_spearman_rho_from_prior",
    "peer_min_spearman_rho_from_prior",
]
SUMMARY_COLUMNS = ["section", "metric", "value", "unit", "source_tables"]


def load(tables: Path = TABLES) -> Dict[str, pd.DataFrame]:
    """Read the committed input tables."""
    names = [
        "quality_by_year",
        "quality_overall",
        "metrics_by_year",
        "percentile_band_stability",
        "peer_group_persistence",
    ]
    return {n: pd.read_csv(tables / f"{n}.csv") for n in names}


def year_totals(t: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per year with the additive totals needed to pool or leave out."""
    q = t["quality_by_year"].copy()
    q["year"] = q["label"].astype(float).astype(int)
    m = t["metrics_by_year"].copy()
    m["year"] = m["label"].astype(int)
    d = q.merge(m[["year", "hours_screened", "trir_numerator_screened"]], on="year", validate="1:1")
    d["flagged_hours"] = d["hours_share_implausible"] * d["hours_total"]
    d["cases_total"] = d["cases_total"].astype(float)
    cols = [
        "year",
        "n_filings",
        "n_implausible",
        "hours_total",
        "cases_total",
        "hours_screened",
        "trir_numerator_screened",
    ]
    out = d[cols].sort_values("year").reset_index(drop=True)
    return out


def _pool(d: pd.DataFrame) -> dict:
    """Pooled headline quantities from additive per-year totals."""
    n = float(d.n_filings.sum())
    flagged = float(d.n_implausible.sum())
    hours = float(d.hours_total.sum())
    cases = float(d.cases_total.sum())
    sh = float(d.hours_screened.sum())
    sc = float(d.trir_numerator_screened.sum())
    unscreened = TRIR_FACTOR * cases / hours
    screened = TRIR_FACTOR * sc / sh
    return {
        "n_filings": int(n),
        "n_implausible": int(flagged),
        "implausible_share": flagged / n,
        "hours_total": hours,
        "hours_share_implausible": 1.0 - sh / hours,
        "aggregate_trir_unscreened": unscreened,
        "aggregate_trir_screened": screened,
        "ratio_screened_to_unscreened": screened / unscreened,
    }


def peer_pairs(t: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per adjacent-year pair: mean and minimum rho over the six percentiles."""
    s = t["percentile_band_stability"].copy()
    s["year_from"] = s.year_from.astype(int)
    s["year_to"] = s.year_to.astype(int)
    g = s.groupby(["year_from", "year_to"])["spearman_rho"]
    out = pd.DataFrame({"mean_rho": g.mean(), "min_rho": g.min(), "n_percentiles": g.size()}).reset_index()
    p = t["peer_group_persistence"].copy()
    p["year_from"] = p.year_from.astype(int)
    p["year_to"] = p.year_to.astype(int)
    out = out.merge(p[["year_from", "year_to", "matched_share_of_year_from"]], on=["year_from", "year_to"], validate="1:1")
    return out


def build_loyo(d: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    """Pooled headline with each year left out; first row ``all`` is the full pool."""
    ref = _pool(d)
    rows = []
    for y in ["all"] + [int(v) for v in d.year]:
        sub = d if y == "all" else d[d.year != y]
        p = _pool(sub)
        pp = pairs if y == "all" else pairs[(pairs.year_from != y) & (pairs.year_to != y)]
        rows.append(
            {
                "left_out_year": str(y),
                **p,
                "implausible_share_minus_pooled": p["implausible_share"] - ref["implausible_share"],
                "aggregate_trir_unscreened_pct_from_pooled": 100.0
                * (p["aggregate_trir_unscreened"] / ref["aggregate_trir_unscreened"] - 1.0),
                "aggregate_trir_screened_pct_from_pooled": 100.0
                * (p["aggregate_trir_screened"] / ref["aggregate_trir_screened"] - 1.0),
                "peer_pairs_remaining": int(len(pp)),
                "peer_mean_spearman_rho": float(pp.mean_rho.mean()),
                "peer_min_spearman_rho": float(pp.min_rho.min()),
            }
        )
    out = pd.DataFrame(rows)[LOYO_COLUMNS]
    num = out.select_dtypes("float").columns
    out[num] = out[num].round(ROUND)
    return out


def build_yoy(d: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    """Per-year values and changes from the prior year."""
    rows = []
    prev = None
    for r in d.itertuples():
        share = r.n_implausible / r.n_filings
        unscreened = TRIR_FACTOR * r.cases_total / r.hours_total
        screened = TRIR_FACTOR * r.trir_numerator_screened / r.hours_screened
        row = {
            "year": int(r.year),
            "n_filings": int(r.n_filings),
            "implausible_share": share,
            "implausible_share_change": np.nan,
            "hours_share_implausible": 1.0 - r.hours_screened / r.hours_total,
            "aggregate_trir_unscreened": unscreened,
            "aggregate_trir_screened": screened,
            "aggregate_trir_screened_change": np.nan,
            "aggregate_trir_screened_pct_change": np.nan,
            "ratio_screened_to_unscreened": screened / unscreened,
            "peer_groups_matched_share_from_prior": np.nan,
            "peer_mean_spearman_rho_from_prior": np.nan,
            "peer_min_spearman_rho_from_prior": np.nan,
        }
        if prev is not None:
            row["implausible_share_change"] = share - prev[0]
            row["aggregate_trir_screened_change"] = screened - prev[1]
            row["aggregate_trir_screened_pct_change"] = 100.0 * (screened / prev[1] - 1.0)
            pr = pairs[(pairs.year_from == r.year - 1) & (pairs.year_to == r.year)]
            if len(pr):
                pr = pr.iloc[0]
                row["peer_groups_matched_share_from_prior"] = float(pr.matched_share_of_year_from)
                row["peer_mean_spearman_rho_from_prior"] = float(pr.mean_rho)
                row["peer_min_spearman_rho_from_prior"] = float(pr.min_rho)
        prev = (share, screened)
        rows.append(row)
    out = pd.DataFrame(rows)[YOY_COLUMNS]
    num = out.select_dtypes("float").columns
    out[num] = out[num].round(ROUND)
    return out


def _s(section, metric, value, unit, source):
    if isinstance(value, float):
        value = round(value, ROUND)
    return {"section": section, "metric": metric, "value": value, "unit": unit, "source_tables": source}


def build_summary(t: Dict[str, pd.DataFrame], loyo: pd.DataFrame, yoy: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    """Ranges, spreads and influence of single years."""
    q = "quality_by_year, metrics_by_year"
    pe = "percentile_band_stability, peer_group_persistence"
    full = loyo[loyo.left_out_year == "all"].iloc[0]
    lo = loyo[loyo.left_out_year != "all"].copy()
    rows: List[dict] = []

    def spread(section: str, name: str, series: pd.Series, unit: str, src: str) -> None:
        mean = float(series.mean())
        sd = float(series.std(ddof=1))
        rows.extend(
            [
                _s(section, f"{name}_min", float(series.min()), unit, src),
                _s(section, f"{name}_max", float(series.max()), unit, src),
                _s(section, f"{name}_mean", mean, unit, src),
                _s(section, f"{name}_sd", sd, unit, src),
                _s(section, f"{name}_cv", sd / mean, "ratio", src),
            ]
        )

    rows += [
        _s("pooled", "n_years", int(len(yoy)), "years", q),
        _s("pooled", "implausible_share_pooled", float(full.implausible_share), "share", q),
        _s("pooled", "trir_screened_pooled", float(full.aggregate_trir_screened), "TRIR", q),
        _s("pooled", "trir_unscreened_pooled", float(full.aggregate_trir_unscreened), "TRIR", q),
    ]
    spread("yearly", "implausible_share", yoy.implausible_share, "share", q)
    spread("yearly", "trir_screened", yoy.aggregate_trir_screened, "TRIR", q)
    spread("yearly", "trir_unscreened", yoy.aggregate_trir_unscreened, "TRIR", q)
    ys = yoy.set_index("year")
    rows += [
        _s("yearly", "trir_screened_lowest_year", int(ys.aggregate_trir_screened.idxmin()), "year", q),
        _s("yearly", "trir_screened_highest_year", int(ys.aggregate_trir_screened.idxmax()), "year", q),
        _s("yearly", "trir_screened_max_over_min", float(ys.aggregate_trir_screened.max() / ys.aggregate_trir_screened.min()), "ratio", q),
        _s("yearly", "trir_unscreened_max_over_min", float(ys.aggregate_trir_unscreened.max() / ys.aggregate_trir_unscreened.min()), "ratio", q),
        _s("yearly", "implausible_share_max_over_min", float(ys.implausible_share.max() / ys.implausible_share.min()), "ratio", q),
        _s("yearly", "years_screened_above_unscreened", int((ys.aggregate_trir_screened > ys.aggregate_trir_unscreened).sum()), "years", q),
        _s("yearly", "years_screened_above_pooled_unscreened_x10", int((ys.aggregate_trir_screened > 10 * full.aggregate_trir_unscreened).sum()), "years", q),
        _s("yearly", "hours_share_flagged_max", float(ys.hours_share_implausible.max()), "share", q),
        _s("yearly", "hours_share_flagged_max_year", int(ys.hours_share_implausible.idxmax()), "year", q),
    ]
    ch = yoy.dropna(subset=["aggregate_trir_screened_change"])
    big = ch.loc[ch.aggregate_trir_screened_pct_change.abs().idxmax()]
    bigs = ch.loc[ch.implausible_share_change.abs().idxmax()]
    rows += [
        _s("yoy", "n_changes", int(len(ch)), "year pairs", q),
        _s("yoy", "trir_screened_max_abs_pct_change", float(abs(big.aggregate_trir_screened_pct_change)), "percent", q),
        _s("yoy", "trir_screened_max_abs_pct_change_year", int(big.year), "year", q),
        _s("yoy", "trir_screened_median_abs_pct_change", float(ch.aggregate_trir_screened_pct_change.abs().median()), "percent", q),
        _s("yoy", "implausible_share_max_abs_change", float(abs(bigs.implausible_share_change)), "share points", q),
        _s("yoy", "implausible_share_max_abs_change_year", int(bigs.year), "year", q),
        _s("yoy", "implausible_share_median_abs_change", float(ch.implausible_share_change.abs().median()), "share points", q),
    ]
    for col, name, unit in [
        ("aggregate_trir_screened_pct_from_pooled", "trir_screened", "percent"),
        ("aggregate_trir_unscreened_pct_from_pooled", "trir_unscreened", "percent"),
    ]:
        i = lo[col].abs().idxmax()
        rows += [
            _s("loyo", f"{name}_loyo_min", float(lo[name.replace('trir', 'aggregate_trir')].min()), "TRIR", q),
            _s("loyo", f"{name}_loyo_max", float(lo[name.replace('trir', 'aggregate_trir')].max()), "TRIR", q),
            _s("loyo", f"{name}_loyo_max_abs_pct_from_pooled", float(abs(lo.loc[i, col])), unit, q),
            _s("loyo", f"{name}_loyo_most_influential_year", int(lo.loc[i, "left_out_year"]), "year", q),
        ]
    j = lo.implausible_share_minus_pooled.abs().idxmax()
    rows += [
        _s("loyo", "implausible_share_loyo_min", float(lo.implausible_share.min()), "share", q),
        _s("loyo", "implausible_share_loyo_max", float(lo.implausible_share.max()), "share", q),
        _s("loyo", "implausible_share_loyo_max_abs_change", float(abs(lo.loc[j, "implausible_share_minus_pooled"])), "share points", q),
        _s("loyo", "implausible_share_loyo_most_influential_year", int(lo.loc[j, "left_out_year"]), "year", q),
        _s("loyo", "loyo_screened_above_10x_unscreened_in_all", bool((lo.ratio_screened_to_unscreened > 10).all()), "flag", q),
        _s("loyo", "loyo_ratio_min", float(lo.ratio_screened_to_unscreened.min()), "ratio", q),
        _s("loyo", "loyo_ratio_max", float(lo.ratio_screened_to_unscreened.max()), "ratio", q),
    ]
    s = t["percentile_band_stability"]
    rows += [
        _s("peers", "n_year_pairs", int(len(pairs)), "year pairs", pe),
        _s("peers", "rho_min", float(s.spearman_rho.min()), "rho", pe),
        _s("peers", "rho_max", float(s.spearman_rho.max()), "rho", pe),
        _s("peers", "rho_mean", float(s.spearman_rho.mean()), "rho", pe),
        _s("peers", "rho_all_above_0_8", bool((s.spearman_rho > 0.8).all()), "flag", pe),
        _s("peers", "matched_share_min", float(pairs.matched_share_of_year_from.min()), "share", pe),
        _s("peers", "matched_share_max", float(pairs.matched_share_of_year_from.max()), "share", pe),
    ]
    worst = s.loc[s.spearman_rho.idxmin()]
    rows += [
        _s("peers", "rho_min_year_from", int(worst.year_from), "year", pe),
        _s("peers", "rho_min_percentile", str(worst.percentile), "percentile", pe),
    ]
    by_p = s.groupby("percentile")["spearman_rho"].mean()
    for p in PCTS:
        rows.append(_s("peers", f"rho_mean_{p}", float(by_p[p]), "rho", pe))
    rows += [
        _s("peers", "loyo_mean_rho_min", float(lo.peer_mean_spearman_rho.min()), "rho", pe),
        _s("peers", "loyo_mean_rho_max", float(lo.peer_mean_spearman_rho.max()), "rho", pe),
        _s("peers", "loyo_min_rho_lowest", float(lo.peer_min_spearman_rho.min()), "rho", pe),
    ]
    out = pd.DataFrame(rows, columns=SUMMARY_COLUMNS)
    out["value"] = out["value"].astype(object)
    return out


def build_tables(tables: Path = TABLES) -> Dict[str, pd.DataFrame]:
    """Build the three output tables from the committed inputs."""
    t = load(tables)
    d = year_totals(t)
    pooled = _pool(d)
    ov = t["quality_overall"].iloc[0]
    if abs(pooled["aggregate_trir_screened"] - ov["aggregate_trir_screened"]) > 1e-9:
        raise ValueError("per-year totals do not reproduce the pooled screened TRIR")
    if abs(pooled["aggregate_trir_unscreened"] - ov["aggregate_trir_unscreened"]) > 1e-9:
        raise ValueError("per-year totals do not reproduce the pooled unscreened TRIR")
    if pooled["n_implausible"] != int(ov["n_implausible"]):
        raise ValueError("per-year flagged counts do not sum to the pooled count")
    pairs = peer_pairs(t)
    loyo = build_loyo(d, pairs)
    yoy = build_yoy(d, pairs)
    return {"loyo": loyo, "yoy": yoy, "summary": build_summary(t, loyo, yoy, pairs)}


def _pct(x: float, nd: int = 2) -> str:
    return f"{100 * x:.{nd}f}%"


def build_doc(loyo: pd.DataFrame, yoy: pd.DataFrame, summary: pd.DataFrame) -> str:
    """Render docs/YEAR_STABILITY.md from the tables."""
    sv = summary.set_index("metric")["value"]

    def f(m: str) -> float:
        return float(sv[m])

    def i(m: str) -> int:
        return int(float(sv[m]))

    yrows = []
    for r in yoy.itertuples():
        ch = "" if np.isnan(r.aggregate_trir_screened_pct_change) else f"{r.aggregate_trir_screened_pct_change:+.1f}%"
        rho = "" if np.isnan(r.peer_mean_spearman_rho_from_prior) else f"{r.peer_mean_spearman_rho_from_prior:.3f}"
        yrows.append(
            f"| {r.year} | {_pct(r.implausible_share)} | {r.aggregate_trir_screened:.3f} | {ch} | "
            f"{r.aggregate_trir_unscreened:.3f} | {_pct(r.hours_share_implausible, 1)} | {rho} |"
        )
    lrows = []
    for r in loyo.itertuples():
        name = "none (all nine years)" if r.left_out_year == "all" else r.left_out_year
        lrows.append(
            f"| {name} | {_pct(r.implausible_share)} | {r.aggregate_trir_screened:.3f} | "
            f"{r.aggregate_trir_screened_pct_from_pooled:+.2f}% | {r.aggregate_trir_unscreened:.3f} | "
            f"{r.ratio_screened_to_unscreened:.1f}x | {r.peer_mean_spearman_rho:.3f} |"
        )
    pct_rows = " | ".join(f"{p} {f('rho_mean_' + p):.3f}" for p in PCTS)

    return f"""# Year stability of the headline results

Generated by `python3 -m ehs_osha.year_stability` from committed tables in `outputs/tables/`; the numbers are in `outputs/tables/year_stability_loyo.csv`, `outputs/tables/year_stability_yoy.csv` and `outputs/tables/year_stability_summary.csv`. Do not edit by hand: `tests/test_year_stability.py` fails if this page differs from the script output.

## Question

The headline results pool nine filing years (2016 to 2024): about {_pct(f('implausible_share_pooled'), 1)} of filings are flagged, the screened aggregate TRIR is {f('trir_screened_pooled'):.3f} against {f('trir_unscreened_pooled'):.3f} unscreened, and peer-group percentiles are stable from one year to the next. Would any of that change if one year were absent, and how much does each result move from year to year?

## Method

Three views, all arithmetic on committed per-year tables (nothing is re-screened or re-fitted).

1. **Leave one year out.** The pooled flagged count, hours, cases, screened hours and screened cases are sums over years, so the pooled headline without year y is the sum over the other eight years. The sums for all nine years are checked against `quality_overall.csv` and the build fails if they differ.
2. **Year over year.** Each year's own flagged share, screened and unscreened aggregate TRIR, and the change from the previous year.
3. **Peer-group rank stability.** `percentile_band_stability.csv` holds the Spearman rank correlation of peer-group percentiles (NAICS 3-digit by size band) between adjacent years for six percentiles. Leaving year y out removes the two adjacent-year pairs that involve y; the mean and minimum correlation over the remaining pairs is reported.

## Result 1: leaving a year out

| Year left out | Flagged share | Screened TRIR | vs pooled | Unscreened TRIR | Screened / unscreened | Peer mean rho |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(lrows)}

- **Screened aggregate TRIR is stable.** Across the nine leave-one-out pools it runs from {f('trir_screened_loyo_min'):.3f} to {f('trir_screened_loyo_max'):.3f}; the largest departure from the pooled {f('trir_screened_pooled'):.3f} is {f('trir_screened_loyo_max_abs_pct_from_pooled'):.2f}% (leaving out {i('trir_screened_loyo_most_influential_year')}).
- **Flagged share is stable.** It runs from {_pct(f('implausible_share_loyo_min'))} to {_pct(f('implausible_share_loyo_max'))}; the largest shift from the pooled value is {100 * f('implausible_share_loyo_max_abs_change'):.2f} percentage points (leaving out {i('implausible_share_loyo_most_influential_year')}).
- **The unscreened TRIR is not stable, and one year explains why.** It runs from {f('trir_unscreened_loyo_min'):.3f} to {f('trir_unscreened_loyo_max'):.3f}. Leaving out {i('trir_unscreened_loyo_most_influential_year')} changes it by {f('trir_unscreened_loyo_max_abs_pct_from_pooled'):.0f}%: that year holds {_pct(f('hours_share_flagged_max'), 1)} of its reported hours in flagged filings, and the pooled denominator is dominated by it. The conclusion "screening raises the aggregate rate by an order of magnitude or more" nonetheless holds in all nine pools (ratio {f('loyo_ratio_min'):.1f}x to {f('loyo_ratio_max'):.1f}x).

## Result 2: year over year

| Year | Flagged share | Screened TRIR | Change | Unscreened TRIR | Hours in flagged filings | Peer mean rho (vs prior year) |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(yrows)}

- The screened TRIR ranges from {f('trir_screened_min'):.3f} ({i('trir_screened_lowest_year')}) to {f('trir_screened_max'):.3f} ({i('trir_screened_highest_year')}), a factor of {f('trir_screened_max_over_min'):.2f}; its coefficient of variation across years is {f('trir_screened_cv'):.3f}. The median absolute year-over-year change is {f('trir_screened_median_abs_pct_change'):.1f}% and the largest is {f('trir_screened_max_abs_pct_change'):.1f}% ({i('trir_screened_max_abs_pct_change_year')}).
- The unscreened TRIR ranges from {f('trir_unscreened_min'):.3f} to {f('trir_unscreened_max'):.3f}, a factor of {f('trir_unscreened_max_over_min'):.0f}. It tracks the share of hours in a few flagged filings, not safety performance.
- The flagged share ranges from {_pct(f('implausible_share_min'))} to {_pct(f('implausible_share_max'))} (factor {f('implausible_share_max_over_min'):.2f}); the median absolute year-over-year change is {100 * f('implausible_share_median_abs_change'):.2f} points and the largest is {100 * f('implausible_share_max_abs_change'):.2f} points ({i('implausible_share_max_abs_change_year')}).
- The screened rate exceeds the unscreened rate in {i('years_screened_above_unscreened')} of {i('n_years')} years.

## Result 3: peer-group rank stability

- Across {i('n_year_pairs')} adjacent-year pairs and six percentiles, the Spearman rho runs from {f('rho_min'):.3f} to {f('rho_max'):.3f} (mean {f('rho_mean'):.3f}); the lowest is {sv['rho_min_percentile']} between {i('rho_min_year_from')} and {i('rho_min_year_from') + 1}. All {i('n_year_pairs') * 6} values exceed 0.8: {sv['rho_all_above_0_8']}.
- Mean rho by percentile: {pct_rows}.
- The share of a year's peer groups that also appear the next year is {_pct(f('matched_share_min'), 1)} to {_pct(f('matched_share_max'), 1)}.
- Leaving any one year out leaves the mean rho between {f('loyo_mean_rho_min'):.3f} and {f('loyo_mean_rho_max'):.3f}, so no single year's pairs carry the result.

## Plain-language interpretation

The two numbers the project leans on, the screened aggregate TRIR near 4 and about 2% of filings flagged, do not depend on any single year: dropping each year in turn moves the screened rate by at most {f('trir_screened_loyo_max_abs_pct_from_pooled'):.1f}% and the flagged share by at most {100 * f('implausible_share_loyo_max_abs_change'):.2f} percentage points. The screened rate does vary between years (it is lowest in {i('trir_screened_lowest_year')}, {f('trir_screened_min'):.2f}, and the largest single-year move is {f('trir_screened_max_abs_pct_change'):.0f}% in {i('trir_screened_max_abs_pct_change_year')}, which the committed tables describe but do not explain), so it should be quoted as a pooled figure with the yearly range, not as a constant. The unscreened rate is the opposite case: it is driven by the hours reported in a small number of filings and should not be compared across years or pooled without the screen. Peer-group ordering is persistent: groups that are high in one year are, with rank correlation around {f('rho_mean'):.2f}, high the next.

## Limits

- **Nine years, descriptive only.** With nine yearly points, spreads and ranges describe these filings; no sampling interval or significance test is claimed, and the coefficient of variation is not a forecast interval.
- **Leave-one-out is not independence.** The years are not independent samples: the same establishments file repeatedly, so stability across years partly reflects the same filers returning. `docs/PANEL_AUDIT.md` covers linkage.
- **Composition changes.** The number of filings rises every year from {yoy.n_filings.iloc[0]:,} in {yoy.year.iloc[0]} to {yoy.n_filings.iloc[-1]:,} in {yoy.year.iloc[-1]}, so year-to-year differences mix real change and a changing set of filers. Nothing here separates the two.
- **Adjacent years only for peers.** The committed rank-stability table compares consecutive years, so leaving a year out removes its pairs; it does not create a pair spanning the gap, and stability over longer gaps is not available from committed tables.
- **Peer groups are those that persist.** Rank correlation is computed on matched groups (see matched share above); groups that appear or vanish are excluded.
- **The screen is held fixed.** The default bounds (120 and 4,500 hours per employee) are used in every year; sensitivity to the bounds is a separate analysis (`docs/THRESHOLD_ROBUSTNESS.md`), and per-year behaviour under other bounds is not in the committed tables.
- **Stable is not correct.** Agreement across years does not show that screened rates equal true national rates; the data are self-reported filings, not a sample of the US workforce.
"""


def main() -> None:
    """Write the tables and the docs page."""
    tabs = build_tables()
    tabs["loyo"].to_csv(LOYO, index=False)
    tabs["yoy"].to_csv(YOY, index=False)
    tabs["summary"].to_csv(SUMMARY, index=False)
    DOC.write_text(build_doc(tabs["loyo"], tabs["yoy"], tabs["summary"]), encoding="utf-8")
    print(f"wrote {LOYO}\nwrote {YOY}\nwrote {SUMMARY}\nwrote {DOC}")


if __name__ == "__main__":
    main()
