"""Plausibility screening of OSHA ITA Form 300A filings.

The problem
-----------
Form 300A carries a numerator (case counts) and a denominator (total hours
worked). Case counts are bounded by how many people work at a site. Hours worked
is a free-text number that nothing validates, so a single mistyped field can be
off by many orders of magnitude. Because the standard incident rate is

    TRIR = 200000 * recordable_cases / total_hours_worked

and because an aggregate rate computed over many establishments is a
*ratio of sums*, one filing with an impossible hours value can dominate the
denominator of an entire industry, state or national aggregate while
contributing almost nothing to the numerator. The aggregate is then biased
towards zero.

This module makes that failure measurable rather than invisible.

The screen
----------
Each filing gets a set of independent boolean flags. A filing is *implausible*
if any flag is set. The flags are:

``flag_hours_missing``
    ``total_hours_worked`` is missing, non-finite, or <= 0.
``flag_employees_missing``
    ``annual_average_employees`` is missing, non-finite, or < 1.
``flag_negative_counts``
    Any recordable-case component is negative.
``flag_hours_per_employee_high``
    ``hours_per_employee`` exceeds ``max_hours_per_employee``. The absolute
    ceiling is 8,760 (24 x 365); the default of 4,500 corresponds to roughly
    86 hours per week sustained for every week of the year, which is already an
    extreme reading for an *average* employee.
``flag_hours_per_employee_low``
    ``hours_per_employee`` is below ``min_hours_per_employee``. Genuine seasonal
    and part-time sites exist, so this bound is deliberately loose (default 120
    hours per average employee-year, about three full-time weeks).
``flag_no_injury_contradiction``
    The self-declared ``no_injuries_illnesses`` checkbox contradicts the case
    counts on the same form.

The bounds are configuration, not truth. :func:`sensitivity_grid` re-runs the
whole comparison across a grid of bounds so a reader can see how much the
conclusion depends on where the lines are drawn. In the 2016-2024 pooled data
the flagged *share* is fairly sensitive to the bounds -- it roughly doubles
across the default grid -- but the corrected aggregate TRIR is not, because the
filings that move in and out of the flagged set at the margin carry almost none
of the hours. The computed ranges are written to
``outputs/tables/quality_sensitivity_grid.csv`` and summarised in
``outputs/summary.json``; no range is quoted in this docstring, so it cannot go
stale.

What the screen is not
----------------------
It is not a fraud detector and it does not identify which specific number on a
form is wrong. A filing flagged ``hours_per_employee_high`` might have a correct
hours value and a mistyped employee count. The screen identifies filings whose
numerator and denominator cannot both be right, which is the property that
matters for a rate.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

#: Hours in a calendar year. No employee can exceed this; used as a hard ceiling
#: on any user-supplied ``max_hours_per_employee``.
HOURS_IN_YEAR = 24 * 365

FLAG_COLUMNS: Sequence[str] = (
    "flag_hours_missing",
    "flag_employees_missing",
    "flag_negative_counts",
    "flag_hours_per_employee_high",
    "flag_hours_per_employee_low",
    "flag_no_injury_contradiction",
)


@dataclass(frozen=True)
class PlausibilityConfig:
    """Bounds for the plausibility screen.

    Attributes:
        min_hours_per_employee: Lower bound on annual hours per average
            employee. Default 120 (~3 full-time weeks).
        max_hours_per_employee: Upper bound. Default 4,500 (~86 h/week all year).
        treat_contradiction_as_implausible: Whether the ``no_injuries_illnesses``
            contradiction flag contributes to the overall implausible verdict.
            Default False: the contradiction is a real data defect but it does
            not by itself corrupt the rate denominator, so it is reported
            separately rather than folded into the headline screen.
    """

    min_hours_per_employee: float = 120.0
    max_hours_per_employee: float = 4500.0
    treat_contradiction_as_implausible: bool = False

    def __post_init__(self) -> None:
        if self.min_hours_per_employee <= 0:
            raise ValueError("min_hours_per_employee must be positive")
        if self.max_hours_per_employee <= self.min_hours_per_employee:
            raise ValueError("max_hours_per_employee must exceed the minimum")
        if self.max_hours_per_employee > HOURS_IN_YEAR:
            raise ValueError(
                f"max_hours_per_employee cannot exceed {HOURS_IN_YEAR} "
                f"(hours in a calendar year)"
            )

    def to_json(self) -> dict:
        """Return a JSON-serialisable dict of this configuration."""
        return asdict(self)


def apply_screen(
    df: pd.DataFrame, config: Optional[PlausibilityConfig] = None
) -> pd.DataFrame:
    """Attach plausibility flags to a harmonised ITA frame.

    Args:
        df: Frame produced by :func:`ehs_osha.load.derive_fields`.
        config: Bounds to apply. Defaults to :class:`PlausibilityConfig`.

    Returns:
        A copy of ``df`` with the columns in :data:`FLAG_COLUMNS` plus
        ``implausible`` (bool) appended.
    """
    cfg = config or PlausibilityConfig()
    out = df.copy()

    hours = out["total_hours_worked"].to_numpy(dtype="float64", na_value=np.nan)
    emp = out["annual_average_employees"].to_numpy(dtype="float64", na_value=np.nan)
    hpe = out["hours_per_employee"].to_numpy(dtype="float64", na_value=np.nan)
    rec = out["recordable_cases"].to_numpy(dtype="float64", na_value=np.nan)

    out["flag_hours_missing"] = ~np.isfinite(hours) | (hours <= 0)
    out["flag_employees_missing"] = ~np.isfinite(emp) | (emp < 1)

    comp = [
        c
        for c in (
            "total_deaths",
            "total_dafw_cases",
            "total_djtr_cases",
            "total_other_cases",
        )
        if c in out.columns
    ]
    neg = np.zeros(len(out), dtype=bool)
    for c in comp:
        v = out[c].to_numpy(dtype="float64", na_value=np.nan)
        neg |= np.isfinite(v) & (v < 0)
    neg |= ~np.isfinite(rec)
    out["flag_negative_counts"] = neg

    with np.errstate(invalid="ignore"):
        out["flag_hours_per_employee_high"] = np.isfinite(hpe) & (
            hpe > cfg.max_hours_per_employee
        )
        out["flag_hours_per_employee_low"] = np.isfinite(hpe) & (
            hpe < cfg.min_hours_per_employee
        )
    # A filing with no computable hours-per-employee is already caught by the
    # missing-hours or missing-employees flag; do not double-count it here.

    if "no_injuries_illnesses" in out.columns:
        nii = out["no_injuries_illnesses"].to_numpy(dtype="float64", na_value=np.nan)
        has_cases = np.isfinite(rec) & (rec > 0)
        zero_cases = np.isfinite(rec) & (rec == 0)
        out["flag_no_injury_contradiction"] = ((nii == 2) & has_cases) | (
            (nii == 1) & zero_cases
        )
    else:
        out["flag_no_injury_contradiction"] = False

    core = [c for c in FLAG_COLUMNS if c != "flag_no_injury_contradiction"]
    implausible = out[core].any(axis=1)
    if cfg.treat_contradiction_as_implausible:
        implausible = implausible | out["flag_no_injury_contradiction"]
    out["implausible"] = implausible
    return out


def aggregate_trir(cases: pd.Series, hours: pd.Series) -> float:
    """Aggregate (ratio-of-sums) total recordable incident rate.

    Args:
        cases: Recordable case counts.
        hours: Hours worked.

    Returns:
        ``200000 * sum(cases) / sum(hours)``, or NaN if hours sum to <= 0.
    """
    h = float(np.nansum(hours.to_numpy(dtype="float64", na_value=np.nan)))
    if not np.isfinite(h) or h <= 0:
        return float("nan")
    c = float(np.nansum(cases.to_numpy(dtype="float64", na_value=np.nan)))
    return 200000.0 * c / h


@dataclass
class ScreenSummary:
    """Result of comparing screened and unscreened aggregates for one stratum."""

    label: str
    n_filings: int
    n_implausible: int
    implausible_share: float
    hours_total: float
    hours_share_implausible: float
    cases_total: float
    cases_share_implausible: float
    aggregate_trir_unscreened: float
    aggregate_trir_screened: float
    ratio_screened_to_unscreened: float
    median_establishment_trir_screened: float

    def to_json(self) -> dict:
        """Return a JSON-serialisable dict of this summary."""
        return asdict(self)


def _safe_ratio(num: float, den: float) -> float:
    """Divide, returning NaN rather than raising on a zero or non-finite den."""
    if not np.isfinite(den) or den == 0:
        return float("nan")
    return num / den


def summarise_screen(
    screened: pd.DataFrame, label: str = "all"
) -> ScreenSummary:
    """Summarise the effect of the screen on one stratum.

    Args:
        screened: Frame returned by :func:`apply_screen`.
        label: Stratum name for reporting (e.g. a year or NAICS code).

    Returns:
        A :class:`ScreenSummary`.
    """
    bad = screened["implausible"].to_numpy(dtype=bool)
    hours = screened["total_hours_worked"].to_numpy(dtype="float64", na_value=np.nan)
    cases = screened["recordable_cases"].to_numpy(dtype="float64", na_value=np.nan)

    hours_total = float(np.nansum(hours))
    cases_total = float(np.nansum(cases))
    hours_bad = float(np.nansum(np.where(bad, hours, np.nan)))
    cases_bad = float(np.nansum(np.where(bad, cases, np.nan)))

    good = ~bad
    unscreened = _safe_ratio(200000.0 * cases_total, hours_total)
    scr = _safe_ratio(
        200000.0 * float(np.nansum(np.where(good, cases, np.nan))),
        float(np.nansum(np.where(good, hours, np.nan))),
    )
    med = float(
        np.nanmedian(screened.loc[good, "trir"].to_numpy(dtype="float64", na_value=np.nan))
    ) if good.any() else float("nan")

    return ScreenSummary(
        label=label,
        n_filings=int(len(screened)),
        n_implausible=int(bad.sum()),
        implausible_share=float(bad.mean()) if len(screened) else float("nan"),
        hours_total=hours_total,
        hours_share_implausible=_safe_ratio(hours_bad, hours_total),
        cases_total=cases_total,
        cases_share_implausible=_safe_ratio(cases_bad, cases_total),
        aggregate_trir_unscreened=unscreened,
        aggregate_trir_screened=scr,
        ratio_screened_to_unscreened=_safe_ratio(scr, unscreened),
        median_establishment_trir_screened=med,
    )


def summarise_by(
    screened: pd.DataFrame, by: str
) -> pd.DataFrame:
    """Run :func:`summarise_screen` within each level of a grouping column.

    Args:
        screened: Frame returned by :func:`apply_screen`.
        by: Column to group on, e.g. ``"year_filing_for"`` or ``"naics2"``.

    Returns:
        One row per group, sorted by group key.
    """
    rows: List[dict] = []
    for key, grp in screened.groupby(by, dropna=True, observed=True):
        rows.append(summarise_screen(grp, label=str(key)).to_json())
    out = pd.DataFrame(rows)
    return out.sort_values("label").reset_index(drop=True) if len(out) else out


def flag_prevalence(screened: pd.DataFrame) -> pd.DataFrame:
    """Count how often each individual flag fires, and the hours it carries.

    Flags are not mutually exclusive, so the counts do not sum to the number of
    implausible filings.

    Args:
        screened: Frame returned by :func:`apply_screen`.

    Returns:
        One row per flag with ``n``, ``share``, ``hours`` and ``hours_share``.
    """
    hours = screened["total_hours_worked"].to_numpy(dtype="float64", na_value=np.nan)
    total_hours = float(np.nansum(hours))
    rows = []
    for flag in FLAG_COLUMNS:
        mask = screened[flag].to_numpy(dtype=bool)
        h = float(np.nansum(np.where(mask, hours, np.nan)))
        rows.append(
            {
                "flag": flag,
                "n": int(mask.sum()),
                "share": float(mask.mean()) if len(screened) else float("nan"),
                "hours": h,
                "hours_share": _safe_ratio(h, total_hours),
            }
        )
    return pd.DataFrame(rows)


def sensitivity_grid(
    df: pd.DataFrame,
    lows: Iterable[float] = (100.0, 120.0, 200.0, 250.0, 400.0),
    highs: Iterable[float] = (3500.0, 4000.0, 4500.0, 5000.0, 6000.0),
) -> pd.DataFrame:
    """Re-run the screen across a grid of bounds and report the effect.

    This exists so the headline result is not an artefact of one arbitrary pair
    of thresholds. A reader can see directly how much the conclusion moves.

    Args:
        df: Harmonised frame (before screening).
        lows: Candidate ``min_hours_per_employee`` values.
        highs: Candidate ``max_hours_per_employee`` values.

    Returns:
        One row per (low, high) combination.
    """
    rows: List[dict] = []
    for lo in lows:
        for hi in highs:
            if hi <= lo:
                continue
            cfg = PlausibilityConfig(
                min_hours_per_employee=lo, max_hours_per_employee=hi
            )
            summ = summarise_screen(apply_screen(df, cfg), label=f"{lo:g}-{hi:g}")
            rec = summ.to_json()
            rec["min_hours_per_employee"] = lo
            rec["max_hours_per_employee"] = hi
            rows.append(rec)
    return pd.DataFrame(rows)


def hours_concentration(
    df: pd.DataFrame, top_ns: Sequence[int] = (1, 10, 100, 1000)
) -> pd.DataFrame:
    """Report what share of all reported hours the largest filings carry.

    This is the mechanism behind the aggregate-rate failure stated without any
    reference to a screen: if a handful of filings hold most of the denominator,
    the aggregate rate is a statement about those filings and not about the
    population.

    Args:
        df: Harmonised frame with ``total_hours_worked``.
        top_ns: Cut points to report.

    Returns:
        One row per cut point with ``hours_share`` and ``cases_share``.
    """
    h = df["total_hours_worked"].to_numpy(dtype="float64", na_value=np.nan)
    c = df["recordable_cases"].to_numpy(dtype="float64", na_value=np.nan)
    order = np.argsort(np.where(np.isfinite(h), h, -np.inf))[::-1]
    h_sorted, c_sorted = h[order], c[order]
    total_h, total_c = float(np.nansum(h)), float(np.nansum(c))
    rows = []
    for n in top_ns:
        n = min(int(n), len(h_sorted))
        rows.append(
            {
                "top_n_filings_by_hours": n,
                "hours_share": _safe_ratio(float(np.nansum(h_sorted[:n])), total_h),
                "cases_share": _safe_ratio(float(np.nansum(c_sorted[:n])), total_c),
            }
        )
    return pd.DataFrame(rows)
