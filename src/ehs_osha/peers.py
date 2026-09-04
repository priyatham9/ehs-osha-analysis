"""Peer grouping and percentile benchmark tables.

A benchmark is only useful if the peer group is defined by something stable.
Two decisions here are load-bearing:

**Size bands come from ``annual_average_employees``, not from the ``size``
field.** OSHA's ``size`` codes are documented (1 = <20, 2 = 20-249, 21 = 20-99,
22 = 100-249, 3 = 250+) but are not comparable across years: OSHA's summary
data dictionary records that code 2 was split into 21 and 22 with the
collection of 2023 data, and the files show it -- among plausible filings,
code 2 falls from 244,231 in 2022 to 41,343 in 2024 while codes 21 and 22
together rise to 224,266. A pooled panel therefore mixes a 20-249 band with
two narrower bands covering the same employees. Building peer groups on
``size`` would make every year-over-year comparison meaningless.
Employee-count bands are computed the same way in every year.

**A minimum group size is enforced.** Percentiles from a handful of
establishments are noise. Groups below ``min_group_n`` are reported with their
count but excluded from the published percentile table by default, and the
excluded share is reported rather than hidden.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

#: Employee-count band edges. Left-closed, right-open; the final band is open.
#: Chosen to bracket the reporting thresholds in 29 CFR 1904 Subpart E (20, 100
#: and 250 employees) while keeping enough establishments per cell.
SIZE_BAND_EDGES: Sequence[int] = (1, 20, 50, 100, 250, 500, 1000)

SIZE_BAND_LABELS: Sequence[str] = (
    "001-019",
    "020-049",
    "050-099",
    "100-249",
    "250-499",
    "500-999",
    "1000+",
)

DEFAULT_PERCENTILES: Sequence[float] = (10, 25, 50, 75, 90, 95)


def assign_size_band(
    employees: pd.Series,
    edges: Sequence[int] = SIZE_BAND_EDGES,
    labels: Sequence[str] = SIZE_BAND_LABELS,
) -> pd.Series:
    """Map an employee count to a size-band label.

    Args:
        employees: Annual average employee counts.
        edges: Left edges of each band, ascending. ``len(edges) == len(labels)``.
        labels: Band labels.

    Returns:
        An object Series of labels, NaN where the count is missing or < the
        first edge.

    Raises:
        ValueError: If ``edges`` and ``labels`` have different lengths.
    """
    if len(edges) != len(labels):
        raise ValueError("edges and labels must be the same length")
    v = employees.to_numpy(dtype="float64", na_value=np.nan)
    out = np.full(len(v), None, dtype=object)
    valid = np.isfinite(v)
    idx = np.searchsorted(np.asarray(edges, dtype="float64"), v, side="right") - 1
    ok = valid & (idx >= 0)
    lab = np.asarray(labels, dtype=object)
    out[ok] = lab[idx[ok]]
    return pd.Series(out, index=employees.index, dtype="object")


def add_peer_keys(
    df: pd.DataFrame,
    naics_level: str = "naics3",
    edges: Sequence[int] = SIZE_BAND_EDGES,
    labels: Sequence[str] = SIZE_BAND_LABELS,
) -> pd.DataFrame:
    """Attach ``size_band`` and ``peer_group`` columns.

    Args:
        df: Harmonised frame with ``annual_average_employees`` and NAICS prefix
            columns.
        naics_level: Which NAICS prefix column to use (``naics2``/``3``/``4``).
        edges: Size band edges.
        labels: Size band labels.

    Returns:
        A copy with ``size_band`` and ``peer_group`` (``"<naics>|<band>"``).

    Raises:
        KeyError: If ``naics_level`` is not a column of ``df``.
    """
    if naics_level not in df.columns:
        raise KeyError(f"{naics_level!r} not present; available: {list(df.columns)}")
    out = df.copy()
    out["size_band"] = assign_size_band(out["annual_average_employees"], edges, labels)
    naics = out[naics_level].astype("object")
    out["peer_group"] = np.where(
        naics.notna() & out["size_band"].notna(),
        naics.astype(str) + "|" + out["size_band"].astype(str),
        None,
    )
    return out


def _percentile_row(
    values: np.ndarray, percentiles: Sequence[float]
) -> Dict[str, float]:
    """Compute a dict of percentile values, NaN-safe.

    Args:
        values: Numeric array, may contain NaN.
        percentiles: Percentiles in 0-100.

    Returns:
        Mapping ``"p{q}"`` -> value.
    """
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return {f"p{q:g}": float("nan") for q in percentiles}
    qs = np.percentile(finite, list(percentiles))
    return {f"p{q:g}": float(v) for q, v in zip(percentiles, np.atleast_1d(qs))}


@dataclass
class PeerTableConfig:
    """Configuration for a percentile benchmark table.

    Attributes:
        metric: Column to summarise, e.g. ``"trir"``.
        percentiles: Percentiles to report.
        min_group_n: Groups with fewer establishments are marked
            ``publishable=False``.
        naics_level: NAICS prefix column used for grouping.
    """

    metric: str = "trir"
    percentiles: Sequence[float] = DEFAULT_PERCENTILES
    min_group_n: int = 30
    naics_level: str = "naics3"


def percentile_table(
    screened: pd.DataFrame,
    config: Optional[PeerTableConfig] = None,
    *,
    year_column: Optional[str] = "year_filing_for",
    plausible_only: bool = True,
) -> pd.DataFrame:
    """Build a NAICS x size-band percentile table for one metric.

    Args:
        screened: Frame from :func:`ehs_osha.quality.apply_screen`, already
            passed through :func:`add_peer_keys`.
        config: Table configuration.
        year_column: Group within year as well, or ``None`` to pool years.
        plausible_only: Drop filings flagged implausible before computing
            percentiles. Almost always what you want; ``False`` exists so the
            contrast can be shown.

    Returns:
        One row per (year, naics, size_band) with ``n``, ``zero_share``,
        percentile columns, ``aggregate_trir`` and ``publishable``.

    Raises:
        KeyError: If required columns are missing.
    """
    cfg = config or PeerTableConfig()
    required = {"peer_group", "size_band", cfg.naics_level, cfg.metric}
    missing = required - set(screened.columns)
    if missing:
        raise KeyError(f"percentile_table missing columns: {sorted(missing)}")

    frame = screened
    if plausible_only and "implausible" in frame.columns:
        frame = frame[~frame["implausible"]]
    frame = frame[frame["peer_group"].notna()]

    keys: List[str] = []
    if year_column is not None and year_column in frame.columns:
        keys.append(year_column)
    keys += [cfg.naics_level, "size_band"]

    rows: List[dict] = []
    for key, grp in frame.groupby(keys, dropna=True, observed=True):
        key_t: Tuple = key if isinstance(key, tuple) else (key,)
        rec: Dict[str, object] = dict(zip(keys, key_t))
        vals = grp[cfg.metric].to_numpy(dtype="float64", na_value=np.nan)
        rec["n"] = int(len(grp))
        rec["n_with_metric"] = int(np.isfinite(vals).sum())
        recs = grp["recordable_cases"].to_numpy(dtype="float64", na_value=np.nan)
        rec["zero_share"] = (
            float(np.nanmean(recs == 0)) if np.isfinite(recs).any() else float("nan")
        )
        hrs = float(np.nansum(grp["total_hours_worked"].to_numpy(dtype="float64", na_value=np.nan)))
        rec["hours_total"] = hrs
        rec["aggregate_trir"] = (
            200000.0 * float(np.nansum(recs)) / hrs if hrs > 0 else float("nan")
        )
        rec.update(_percentile_row(vals, cfg.percentiles))
        rec["publishable"] = bool(rec["n_with_metric"] >= cfg.min_group_n)
        rows.append(rec)

    out = pd.DataFrame(rows)
    if len(out):
        out = out.sort_values(keys).reset_index(drop=True)
    return out


def coverage_summary(table: pd.DataFrame) -> Dict[str, float]:
    """Summarise how much of the population survives the min-group-n rule.

    Args:
        table: Output of :func:`percentile_table`.

    Returns:
        Counts and shares of groups and establishments that are publishable.
    """
    if not len(table):
        return {
            "groups_total": 0,
            "groups_publishable": 0,
            "group_share_publishable": float("nan"),
            "establishments_total": 0,
            "establishments_in_publishable_groups": 0,
            "establishment_share_publishable": float("nan"),
        }
    pub = table["publishable"].to_numpy(dtype=bool)
    n = table["n"].to_numpy(dtype="float64")
    return {
        "groups_total": int(len(table)),
        "groups_publishable": int(pub.sum()),
        "group_share_publishable": float(pub.mean()),
        "establishments_total": int(n.sum()),
        "establishments_in_publishable_groups": int(n[pub].sum()),
        "establishment_share_publishable": float(n[pub].sum() / n.sum()),
    }
