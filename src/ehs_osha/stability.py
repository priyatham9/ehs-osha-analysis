"""Year-over-year stability of peer-group percentile bands.

A benchmark table is used as though it were a fixed reference: an EHS manager
compares this year's site rate against "the industry 75th percentile" and treats
movement as signal. That only works if the band itself is stable when the
underlying safety performance is not moving. This module measures how much the
bands move between adjacent years for the same peer group.

Three statistics are reported per percentile:

``spearman_rho``
    Rank correlation of the percentile value across matched peer groups in
    consecutive years. High rho means the ordering of industries is reproducible.
``median_abs_change``
    Median absolute change in the percentile value, in TRIR points.
``median_abs_rel_change``
    Median absolute change divided by the earlier year's value. This is the
    number that answers "if my site sat exactly on last year's p75, how far off
    this year's p75 would it be through no change of its own?"

Spearman's rho is computed directly (rank-transform, then Pearson) because SciPy
is not available. Ties get average ranks, matching the standard definition.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd


def _nanmedian_or_nan(values: np.ndarray) -> float:
    """Median of the finite entries, or NaN when there are none.

    ``np.nanmedian`` emits a RuntimeWarning on an all-NaN slice, which happens
    legitimately here (a percentile column can be entirely zero, making every
    relative change undefined). This returns NaN quietly instead.

    Args:
        values: Numeric array, may be all NaN.

    Returns:
        The median of the finite entries, or NaN.
    """
    arr = np.asarray(values, dtype="float64").ravel()
    arr = arr[np.isfinite(arr)]
    return float(np.median(arr)) if arr.size else float("nan")


def rankdata_average(x: np.ndarray) -> np.ndarray:
    """Rank an array, assigning average ranks to ties.

    Args:
        x: Values to rank. Must not contain NaN.

    Returns:
        Ranks starting at 1.
    """
    x = np.asarray(x, dtype="float64").ravel()
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(x.size, dtype="float64")
    ranks[order] = np.arange(1, x.size + 1, dtype="float64")
    # Average ranks within tied runs.
    sorted_x = x[order]
    i = 0
    while i < x.size:
        j = i
        while j + 1 < x.size and sorted_x[j + 1] == sorted_x[i]:
            j += 1
        if j > i:
            avg = 0.5 * (i + j) + 1.0
            ranks[order[i : j + 1]] = avg
        i = j + 1
    return ranks


def spearman_rho(a: np.ndarray, b: np.ndarray) -> float:
    """Spearman rank correlation between two equal-length vectors.

    Args:
        a: First vector.
        b: Second vector.

    Returns:
        Rank correlation in [-1, 1], or NaN if fewer than 3 usable pairs remain
        or either vector is constant.

    Raises:
        ValueError: If the vectors differ in length.
    """
    a = np.asarray(a, dtype="float64").ravel()
    b = np.asarray(b, dtype="float64").ravel()
    if a.size != b.size:
        raise ValueError("vectors must be the same length")
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3:
        return float("nan")
    ra, rb = rankdata_average(a[ok]), rankdata_average(b[ok])
    ra -= ra.mean()
    rb -= rb.mean()
    denom = np.sqrt(float(np.sum(ra**2)) * float(np.sum(rb**2)))
    if denom == 0:
        return float("nan")
    return float(np.sum(ra * rb) / denom)


def _percentile_columns(table: pd.DataFrame) -> List[str]:
    """Return the ``p<number>`` columns present in a percentile table."""
    return [
        c
        for c in table.columns
        if c.startswith("p") and c[1:].replace(".", "", 1).isdigit()
    ]


def year_pair_stability(
    table: pd.DataFrame,
    *,
    year_column: str = "year_filing_for",
    group_columns: Sequence[str] = ("naics3", "size_band"),
    publishable_only: bool = True,
    metric_columns: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Compare each adjacent pair of years within matched peer groups.

    Args:
        table: Output of :func:`ehs_osha.peers.percentile_table`, containing a
            year column.
        year_column: Name of the year column.
        group_columns: Columns that jointly identify a peer group.
        publishable_only: Restrict to groups that met the minimum-n rule in
            *both* years of the pair.
        metric_columns: Percentile columns to evaluate; defaults to all present.

    Returns:
        One row per (year pair, percentile) with ``n_matched_groups``,
        ``spearman_rho``, ``median_abs_change`` and ``median_abs_rel_change``.

    Raises:
        KeyError: If required columns are missing.
    """
    needed = {year_column, *group_columns}
    missing = needed - set(table.columns)
    if missing:
        raise KeyError(f"stability input missing columns: {sorted(missing)}")

    cols = list(metric_columns or _percentile_columns(table))
    if not cols:
        return pd.DataFrame(
            columns=[
                "year_from",
                "year_to",
                "percentile",
                "n_matched_groups",
                "spearman_rho",
                "median_abs_change",
                "median_abs_rel_change",
            ]
        )

    df = table
    if publishable_only and "publishable" in df.columns:
        df = df[df["publishable"]]

    years = sorted(pd.unique(df[year_column].dropna()))
    rows: List[dict] = []
    for y0, y1 in zip(years[:-1], years[1:]):
        a = df[df[year_column] == y0].set_index(list(group_columns))
        b = df[df[year_column] == y1].set_index(list(group_columns))
        shared = a.index.intersection(b.index)
        if len(shared) < 3:
            continue
        a, b = a.loc[shared], b.loc[shared]
        for col in cols:
            va = a[col].to_numpy(dtype="float64", na_value=np.nan)
            vb = b[col].to_numpy(dtype="float64", na_value=np.nan)
            ok = np.isfinite(va) & np.isfinite(vb)
            if ok.sum() < 3:
                continue
            d = vb[ok] - va[ok]
            with np.errstate(divide="ignore", invalid="ignore"):
                rel = np.where(va[ok] > 0, np.abs(d) / va[ok], np.nan)
            rows.append(
                {
                    "year_from": y0,
                    "year_to": y1,
                    "percentile": col,
                    "n_matched_groups": int(ok.sum()),
                    "spearman_rho": spearman_rho(va[ok], vb[ok]),
                    "median_abs_change": float(np.median(np.abs(d))),
                    "median_abs_rel_change": _nanmedian_or_nan(rel),
                }
            )
    return pd.DataFrame(rows)


def group_persistence(
    table: pd.DataFrame,
    *,
    year_column: str = "year_filing_for",
    group_columns: Sequence[str] = ("naics3", "size_band"),
    publishable_only: bool = True,
) -> pd.DataFrame:
    """Report how many peer groups survive from one year to the next.

    A benchmark that loses a third of its cells between years is not usable as a
    fixed reference regardless of how stable the surviving cells look, so this
    is reported alongside the stability statistics rather than buried.

    Args:
        table: Output of :func:`ehs_osha.peers.percentile_table`.
        year_column: Name of the year column.
        group_columns: Columns identifying a peer group.
        publishable_only: Restrict to groups meeting the minimum-n rule.

    Returns:
        One row per adjacent year pair with group counts and the matched share.
    """
    df = table
    if publishable_only and "publishable" in df.columns:
        df = df[df["publishable"]]
    years = sorted(pd.unique(df[year_column].dropna()))
    rows: List[dict] = []
    for y0, y1 in zip(years[:-1], years[1:]):
        a = set(map(tuple, df.loc[df[year_column] == y0, list(group_columns)].values))
        b = set(map(tuple, df.loc[df[year_column] == y1, list(group_columns)].values))
        inter = a & b
        rows.append(
            {
                "year_from": y0,
                "year_to": y1,
                "groups_year_from": len(a),
                "groups_year_to": len(b),
                "groups_matched": len(inter),
                "matched_share_of_year_from": len(inter) / len(a) if a else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def summarise_stability(stability: pd.DataFrame) -> Dict[str, float]:
    """Collapse a stability table into headline numbers per percentile.

    Args:
        stability: Output of :func:`year_pair_stability`.

    Returns:
        Mapping of ``"<percentile>_median_rho"`` and
        ``"<percentile>_median_abs_rel_change"`` to values.
    """
    out: Dict[str, float] = {}
    if not len(stability):
        return out
    for pct, grp in stability.groupby("percentile"):
        out[f"{pct}_median_rho"] = _nanmedian_or_nan(
            grp["spearman_rho"].to_numpy(dtype="float64", na_value=np.nan)
        )
        out[f"{pct}_median_abs_rel_change"] = _nanmedian_or_nan(
            grp["median_abs_rel_change"].to_numpy(dtype="float64", na_value=np.nan)
        )
    return out
