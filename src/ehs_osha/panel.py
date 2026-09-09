"""Establishment-year panel analysis of plausibility-flag persistence.

The rest of this repository establishes that a small share of OSHA
establishment filings fail the hours-per-employee plausibility screen (see
:mod:`ehs_osha.quality`) while carrying almost all reported hours, and that the
resulting TRIR correction swings from 1.39x to 249x depending on the year.
That work does not say *why* filings fail the screen. This module tests two
competing, mutually exclusive explanations against the data:

TYPO HYPOTHESIS
    Implausible hours are independent keying errors. An establishment flagged
    in year *t* is no more likely than any other establishment to be flagged
    in year *t+1*.
SYSTEM HYPOTHESIS
    Certain establishments (or their filing software, or a shared corporate
    parent) systematically misreport hours. Flags cluster in the same
    establishments across years.

The method is a same-establishment transition analysis: build an
establishment x year panel of the ``implausible`` flag, keyed on
``establishment_id`` (reusing :mod:`ehs_osha.load` and :mod:`ehs_osha.quality`
rather than re-deriving either), compute the year-over-year transition matrix,
summarise persistence with an odds ratio and Cohen's kappa, and test both
against a permutation null that holds each year's flag *count* fixed but
reassigns which establishments carry it. See ``docs/PANEL.md`` for the
write-up and the result.

``establishment_id`` stability is not assumed - it is checked
(:func:`establishment_id_stability`) and the check is reported alongside the
substantive result, because a key that is reused across unrelated filers would
invalidate every persistence claim built on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from . import svgplot
from .quality import PlausibilityConfig, apply_screen

#: Permutation reps and seed are fixed constants, not parameters, so that the
#: reported result is exactly reproducible without a caller having to know
#: which values were used to produce ``docs/PANEL.md``.
N_PERMUTATIONS = 200
PERMUTATION_SEED = 20260909


# ---------------------------------------------------------------------------
# Key stability
# ---------------------------------------------------------------------------


@dataclass
class KeyStabilityReport:
    """How trustworthy ``establishment_id`` is as a panel key.

    Attributes:
        n_establishments: Distinct ``establishment_id`` values.
        n_missing: Filings with a missing/non-finite ``establishment_id``.
        multi_ein: Establishment IDs that appear with more than one distinct
            ``ein`` across years.
        multi_company_name: Establishment IDs with more than one distinct
            ``company_name``.
        multi_state: Establishment IDs with more than one distinct ``state``.
    """

    n_establishments: int
    n_missing: int
    multi_ein: int
    multi_company_name: int
    multi_state: int

    def to_frame(self) -> pd.DataFrame:
        """Render as the rows written into ``panel_coverage.csv``."""
        rows = [
            ("distinct_establishment_ids", self.n_establishments),
            ("filings_with_missing_establishment_id", self.n_missing),
            ("establishment_ids_with_multiple_ein", self.multi_ein),
            ("establishment_ids_with_multiple_company_name", self.multi_company_name),
            ("establishment_ids_with_multiple_state", self.multi_state),
        ]
        return pd.DataFrame(rows, columns=["metric", "value"])


def establishment_id_stability(df: pd.DataFrame) -> KeyStabilityReport:
    """Check whether ``establishment_id`` identifies a stable real-world entity.

    An establishment ID that is reused across unrelated filers (different EIN,
    company name or state in different years) would make any persistence
    result computed on it meaningless - it would not be tracking the same
    establishment over time. This does not decide usability by itself; see
    ``docs/PANEL.md`` for the interpretation of what it finds in this data.

    Args:
        df: A harmonised frame with ``establishment_id``, ``ein``,
            ``company_name`` and ``state`` columns (output of
            :func:`ehs_osha.load.derive_fields`).

    Returns:
        A :class:`KeyStabilityReport`.
    """
    n_missing = int((~np.isfinite(df["establishment_id"].to_numpy(dtype="float64", na_value=np.nan))).sum())
    valid = df[np.isfinite(df["establishment_id"].to_numpy(dtype="float64", na_value=np.nan))]
    g = valid.groupby("establishment_id")
    multi_ein = int((g["ein"].nunique(dropna=True) > 1).sum())
    multi_name = int((g["company_name"].nunique(dropna=True) > 1).sum())
    multi_state = int((g["state"].nunique(dropna=True) > 1).sum())
    return KeyStabilityReport(
        n_establishments=int(valid["establishment_id"].nunique()),
        n_missing=n_missing,
        multi_ein=multi_ein,
        multi_company_name=multi_name,
        multi_state=multi_state,
    )


# ---------------------------------------------------------------------------
# Panel construction
# ---------------------------------------------------------------------------


def build_flag_panel(
    df: pd.DataFrame, config: Optional[PlausibilityConfig] = None
) -> pd.DataFrame:
    """Screen filings and pivot to an establishment x year flag matrix.

    Args:
        df: A harmonised, deduplicated frame (output of
            :func:`ehs_osha.load.load_ita_300a` or
            :func:`ehs_osha.load.load_csv_fixture`).
        config: Plausibility bounds; defaults to :class:`PlausibilityConfig`.

    Returns:
        A frame indexed by ``establishment_id``, one column per
        ``year_filing_for`` present in ``df``, holding 1.0 (flagged), 0.0 (not
        flagged) or ``NaN`` (establishment did not file that year). At most one
        filing per ``(establishment_id, year)`` is assumed - :mod:`ehs_osha.load`
        already deduplicates amendments before this function is called.
    """
    screened = apply_screen(df, config)
    wide = screened.pivot_table(
        index="establishment_id",
        columns="year_filing_for",
        values="implausible",
        aggfunc="first",
    )
    wide = wide.reindex(sorted(wide.columns), axis=1)
    return wide


def coverage_table(wide: pd.DataFrame, stability: KeyStabilityReport) -> pd.DataFrame:
    """Build the ``panel_coverage.csv`` table.

    Args:
        wide: Output of :func:`build_flag_panel`.
        stability: Output of :func:`establishment_id_stability`, computed on
            the same underlying data.

    Returns:
        A ``(metric, value)`` frame.
    """
    present = wide.notna().to_numpy()
    n_years_present = present.sum(axis=1)
    n_years_total = wide.shape[1]

    rows: List[Tuple[str, object]] = [
        ("years_covered", n_years_total),
        ("distinct_establishments", int(wide.shape[0])),
        ("establishments_in_2_or_more_years", int((n_years_present >= 2).sum())),
        (
            f"establishments_in_all_{n_years_total}_years",
            int((n_years_present == n_years_total).sum()),
        ),
    ]
    for k in range(1, n_years_total + 1):
        rows.append((f"establishments_in_exactly_{k}_years", int((n_years_present == k).sum())))

    out = pd.DataFrame(rows, columns=["metric", "value"])
    return pd.concat([out, stability.to_frame()], ignore_index=True)


# ---------------------------------------------------------------------------
# Transition matrix, odds ratio, kappa
# ---------------------------------------------------------------------------


def _pair_counts(prev: np.ndarray, curr: np.ndarray) -> Tuple[int, int, int, int]:
    """2x2 contingency counts for one consecutive-year pair.

    Args:
        prev: Flag values (0.0/1.0/NaN) in year ``t - 1``.
        curr: Flag values (0.0/1.0/NaN) in year ``t``.

    Returns:
        ``(n11, n10, n01, n00)`` where the first index is the prior-year flag
        and the second is the current-year flag, restricted to establishments
        present (filed) in both years.
    """
    mask = ~np.isnan(prev) & ~np.isnan(curr)
    p = prev[mask].astype(bool)
    c = curr[mask].astype(bool)
    n11 = int(np.sum(p & c))
    n10 = int(np.sum(p & ~c))
    n01 = int(np.sum(~p & c))
    n00 = int(np.sum(~p & ~c))
    return n11, n10, n01, n00


def odds_ratio(n11: int, n10: int, n01: int, n00: int) -> float:
    """Odds ratio for flag persistence from a 2x2 count table.

    ``n11`` and ``n00`` are the concordant cells (flagged->flagged,
    not->not); ``n10`` and ``n01`` are the discordant cells.

    Returns:
        ``(n11 * n00) / (n10 * n01)``, or ``nan`` if either discordant cell is
        zero.
    """
    denom = n10 * n01
    if denom == 0:
        return float("nan")
    return (n11 * n00) / denom


def cohens_kappa(n11: int, n10: int, n01: int, n00: int) -> float:
    """Cohen's kappa for agreement between the prior- and current-year flag.

    Implemented directly (no scipy/statsmodels dependency):
    ``kappa = (p_observed - p_expected) / (1 - p_expected)`` where
    ``p_observed`` is the fraction of establishment-year-pairs on which the
    flag agrees (both flagged or both not) and ``p_expected`` is the agreement
    expected from the two years' marginal flag rates alone.

    Returns:
        Kappa, or ``nan`` if there is no variance in either marginal (making
        ``p_expected == 1``).
    """
    n = n11 + n10 + n01 + n00
    if n == 0:
        return float("nan")
    p_prev_flag = (n11 + n10) / n
    p_curr_flag = (n11 + n01) / n
    p_observed = (n11 + n00) / n
    p_expected = p_prev_flag * p_curr_flag + (1 - p_prev_flag) * (1 - p_curr_flag)
    if p_expected >= 1.0:
        return float("nan")
    return (p_observed - p_expected) / (1 - p_expected)


def transition_table(wide: pd.DataFrame) -> pd.DataFrame:
    """Build the year-pair and pooled transition table.

    Args:
        wide: Output of :func:`build_flag_panel`.

    Returns:
        One row per consecutive year pair present in ``wide.columns``, plus a
        final ``pooled`` row summing counts over all pairs. Columns: counts
        (``n11``/``n10``/``n01``/``n00``/``n_total``), the two conditional
        probabilities named in the task, the odds ratio and kappa.
    """
    years = list(wide.columns)
    arr = wide.to_numpy(dtype="float64")
    rows = []
    totals = [0, 0, 0, 0]
    for i in range(len(years) - 1):
        n11, n10, n01, n00 = _pair_counts(arr[:, i], arr[:, i + 1])
        rows.append(_transition_row(years[i], years[i + 1], n11, n10, n01, n00))
        totals[0] += n11
        totals[1] += n10
        totals[2] += n01
        totals[3] += n00
    rows.append(_transition_row("pooled", "pooled", *totals))
    return pd.DataFrame(rows)


def _transition_row(
    year_prev: object, year_curr: object, n11: int, n10: int, n01: int, n00: int
) -> Dict[str, object]:
    """One row of :func:`transition_table`."""
    p_flag_given_flag = n11 / (n11 + n10) if (n11 + n10) > 0 else float("nan")
    p_flag_given_noflag = n01 / (n01 + n00) if (n01 + n00) > 0 else float("nan")
    return {
        "year_prev": year_prev,
        "year_curr": year_curr,
        "n11_flag_then_flag": n11,
        "n10_flag_then_noflag": n10,
        "n01_noflag_then_flag": n01,
        "n00_noflag_then_noflag": n00,
        "n_total": n11 + n10 + n01 + n00,
        "p_flag_given_prev_flag": p_flag_given_flag,
        "p_flag_given_prev_noflag": p_flag_given_noflag,
        "odds_ratio": odds_ratio(n11, n10, n01, n00),
        "kappa": cohens_kappa(n11, n10, n01, n00),
    }


# ---------------------------------------------------------------------------
# Permutation test
# ---------------------------------------------------------------------------


def pooled_odds_ratio(wide: pd.DataFrame) -> float:
    """Pooled (all consecutive year pairs summed) persistence odds ratio.

    Args:
        wide: Output of :func:`build_flag_panel`.

    Returns:
        The odds ratio, or ``nan`` if it is undefined.
    """
    arr = wide.to_numpy(dtype="float64")
    totals = [0, 0, 0, 0]
    for i in range(arr.shape[1] - 1):
        counts = _pair_counts(arr[:, i], arr[:, i + 1])
        for j in range(4):
            totals[j] += counts[j]
    return odds_ratio(*totals)


def permutation_null(
    wide: pd.DataFrame,
    n_perm: int = N_PERMUTATIONS,
    seed: int = PERMUTATION_SEED,
) -> np.ndarray:
    """Simulate the pooled odds ratio under the typo (no-clustering) null.

    Each year's flag count is held fixed; the *identity* of which
    establishments present that year carry the flag is reassigned uniformly at
    random. This is implemented by shuffling each year's non-missing flag
    values independently (a fixed-margin permutation), then recomputing the
    pooled odds ratio across consecutive year pairs exactly as
    :func:`pooled_odds_ratio` does on the real data.

    Args:
        wide: Output of :func:`build_flag_panel`.
        n_perm: Number of permutation replicates.
        seed: RNG seed. Fixed at :data:`PERMUTATION_SEED` for the reported
            result so it is exactly reproducible.

    Returns:
        Array of length ``n_perm`` with one pooled odds ratio per replicate.
    """
    rng = np.random.default_rng(seed)
    base = wide.to_numpy(dtype="float64")
    n_years = base.shape[1]
    out = np.empty(n_perm, dtype="float64")
    for p in range(n_perm):
        arr = base.copy()
        for j in range(n_years):
            col = arr[:, j]
            mask = ~np.isnan(col)
            vals = col[mask]
            rng.shuffle(vals)
            col[mask] = vals
        totals = [0, 0, 0, 0]
        for i in range(n_years - 1):
            counts = _pair_counts(arr[:, i], arr[:, i + 1])
            for k in range(4):
                totals[k] += counts[k]
        out[p] = odds_ratio(*totals)
    return out


def permutation_table(
    wide: pd.DataFrame,
    n_perm: int = N_PERMUTATIONS,
    seed: int = PERMUTATION_SEED,
) -> pd.DataFrame:
    """Build the ``panel_permutation.csv`` summary table.

    Args:
        wide: Output of :func:`build_flag_panel`.
        n_perm: Number of permutation replicates.
        seed: RNG seed.

    Returns:
        A one-row frame with the observed odds ratio, the permutation
        distribution's mean and 95% interval, and the fraction of
        permutations reaching or exceeding the observed value (an empirical
        p-value under the typo null).
    """
    observed = pooled_odds_ratio(wide)
    perm = permutation_null(wide, n_perm=n_perm, seed=seed)
    finite = perm[np.isfinite(perm)]
    frac_ge = float(np.mean(finite >= observed)) if finite.size else float("nan")
    return pd.DataFrame(
        [
            {
                "observed_odds_ratio": observed,
                "n_permutations": n_perm,
                "seed": seed,
                "permutation_mean": float(finite.mean()) if finite.size else float("nan"),
                "permutation_p2_5": float(np.percentile(finite, 2.5)) if finite.size else float("nan"),
                "permutation_p97_5": float(np.percentile(finite, 97.5)) if finite.size else float("nan"),
                "fraction_permutations_ge_observed": frac_ge,
            }
        ]
    )


# ---------------------------------------------------------------------------
# 2019 question
# ---------------------------------------------------------------------------


def year_2019_table(wide: pd.DataFrame, focus_year: int = 2019) -> pd.DataFrame:
    """Test whether flagging in ``focus_year`` clusters in repeat offenders.

    Compares, among establishments flagged in ``focus_year``, the rate at
    which they are *also* flagged in the adjacent year against the baseline
    flag rate in that adjacent year among all filers. A ratio near 1 says
    2019 flagging is broad and shallow (consistent with the typo hypothesis);
    a ratio far above 1 says it concentrates in establishments that misreport
    repeatedly (consistent with the system hypothesis).

    Args:
        wide: Output of :func:`build_flag_panel`.
        focus_year: The year to examine (2019 by default; only used if
            present as a column of ``wide``).

    Returns:
        A frame with one row per adjacent year actually present (year - 1,
        year + 1), each row's co-flag rate, the adjacent year's baseline flag
        rate and their ratio, plus a summary row for the focus year itself.
    """
    if focus_year not in wide.columns:
        return pd.DataFrame(
            [{"note": f"{focus_year} not present in panel columns {list(wide.columns)}"}]
        )

    focus = wide[focus_year].to_numpy(dtype="float64")
    n_filers = int(np.sum(~np.isnan(focus)))
    n_flagged = int(np.nansum(focus))
    rows = [
        {
            "comparison": f"{focus_year}_summary",
            "n_filers": n_filers,
            "n_flagged": n_flagged,
            "flagged_share": n_flagged / n_filers if n_filers else float("nan"),
        }
    ]

    flagged_mask = (focus == 1.0)
    for adj_year in (focus_year - 1, focus_year + 1):
        if adj_year not in wide.columns:
            continue
        adj = wide[adj_year].to_numpy(dtype="float64")
        adj_present = ~np.isnan(adj)
        baseline_rate = float(np.nanmean(adj)) if adj_present.any() else float("nan")

        co_present = flagged_mask & adj_present
        n_co_present = int(co_present.sum())
        n_co_flagged = int(np.sum((adj == 1.0) & co_present))
        co_flag_rate = n_co_flagged / n_co_present if n_co_present else float("nan")
        ratio = co_flag_rate / baseline_rate if baseline_rate else float("nan")

        rows.append(
            {
                "comparison": f"{focus_year}_flagged_also_flagged_in_{adj_year}",
                "n_filers": n_co_present,
                "n_flagged": n_co_flagged,
                "flagged_share": co_flag_rate,
                "baseline_flag_rate": baseline_rate,
                "enrichment_ratio": ratio,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Figure
# ---------------------------------------------------------------------------


def make_persistence_figure(
    transitions: pd.DataFrame,
    permutation: pd.DataFrame,
) -> svgplot.Figure:
    """Render fig08: observed persistence odds ratio vs. the permutation null.

    Left-to-right: one bar per year-pair odds ratio (from ``transitions``,
    excluding the pooled row), plus a bar for the pooled observed value and
    the permutation mean, so the observed persistence is visually contrasted
    with what pure chance produces under the same year-by-year flag counts.

    Args:
        transitions: Output of :func:`transition_table`.
        permutation: Output of :func:`permutation_table`.

    Returns:
        A :class:`ehs_osha.svgplot.Figure`, not yet saved.
    """
    per_pair = transitions[transitions["year_prev"] != "pooled"].copy()
    categories = [f"{int(a)}-{int(b)}" for a, b in zip(per_pair["year_prev"], per_pair["year_curr"])]
    categories += ["pooled", "permutation\nnull"]

    values = list(per_pair["odds_ratio"])
    observed_pooled = float(permutation["observed_odds_ratio"].iloc[0])
    perm_mean = float(permutation["permutation_mean"].iloc[0])
    values += [observed_pooled, perm_mean]

    finite_vals = [v for v in values if np.isfinite(v)]
    ylo, yhi = svgplot.autoscale(finite_vals, pad=0.12)
    ylo = min(ylo, 0.0)

    fig = svgplot.Figure(
        title="Flag-persistence odds ratio: observed vs. permutation null",
        xlabel="Year pair",
        ylabel="Odds ratio",
        subtitle=(
            f"{permutation['n_permutations'].iloc[0]} permutations, seed "
            f"{permutation['seed'].iloc[0]}; null holds each year's flag count fixed"
        ),
        axes=svgplot.Axes(ylim=(ylo, yhi)),
    )
    colours = [svgplot.PALETTE[0]] * len(per_pair) + [svgplot.PALETTE[2], svgplot.PALETTE[1]]
    # Bars are drawn directly (rather than through Figure.bars) because each
    # bar here needs its own colour - one series per category, not one series
    # per bar-group - which Figure.bars does not support.
    n_cat = len(categories)
    fig.ax.xlim = (0.0, float(n_cat))
    slot = (fig.ax.plot_right - fig.ax.plot_left) / n_cat
    bw = slot * 0.8
    fig._legend = []
    fig.add_legend_entry("year-pair", colours[0])
    fig.add_legend_entry("pooled observed", colours[-2])
    fig.add_legend_entry("permutation mean", colours[-1])
    for ci, (v, colour) in enumerate(zip(values, colours)):
        if not np.isfinite(v):
            continue
        x0 = fig.ax.plot_left + ci * slot + slot * 0.1
        y1 = fig.ax.sy(max(v, fig.ax.ylim[0]))
        y0 = fig.ax.sy(fig.ax.ylim[0])
        fig._body.append(
            f'<rect x="{x0:.2f}" y="{min(y0, y1):.2f}" width="{bw:.2f}" '
            f'height="{abs(y0 - y1):.2f}" fill="{colour}" />'
        )
    for ci, cat in enumerate(categories):
        x = fig.ax.plot_left + (ci + 0.5) * slot
        fig._body.append(
            f'<text x="{x:.1f}" y="{fig.ax.plot_bottom + 16:.1f}" '
            f'font-size="10" text-anchor="middle" fill="#333">{svgplot._esc(cat)}</text>'
        )
    fig.abline(slope=0.0, intercept=1.0)
    return fig


def save_persistence_figure(
    transitions: pd.DataFrame, permutation: pd.DataFrame, path: Path
) -> Path:
    """Build and save :func:`make_persistence_figure` to ``path``."""
    fig = make_persistence_figure(transitions, permutation)
    return fig.save(path)


# ---------------------------------------------------------------------------
# End-to-end run
# ---------------------------------------------------------------------------


def run(data_dir: Path, out_dir: Path) -> Dict[str, pd.DataFrame]:
    """Run the full panel analysis and write every output this module owns.

    Args:
        data_dir: Directory holding the raw OSHA ITA zip/CSV files (passed to
            :func:`ehs_osha.load.load_ita_300a`).
        out_dir: Repository root under which ``outputs/tables`` and
            ``outputs/figures`` are written.

    Returns:
        The computed tables, keyed by output filename stem, for callers that
        want them in memory (e.g. to compose ``docs/PANEL.md``).
    """
    from .load import load_ita_300a  # local import: keeps a plain `import panel`

    df, _report = load_ita_300a(data_dir)
    stability = establishment_id_stability(df)
    wide = build_flag_panel(df)

    coverage = coverage_table(wide, stability)
    transitions = transition_table(wide)
    permutation = permutation_table(wide)
    year_2019 = year_2019_table(wide)

    tables_dir = Path(out_dir) / "outputs" / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(tables_dir / "panel_coverage.csv", index=False)
    transitions.to_csv(tables_dir / "panel_transitions.csv", index=False)
    permutation.to_csv(tables_dir / "panel_permutation.csv", index=False)
    year_2019.to_csv(tables_dir / "panel_2019.csv", index=False)

    fig_path = Path(out_dir) / "outputs" / "figures" / "fig08_panel_persistence.svg"
    save_persistence_figure(transitions, permutation, fig_path)

    return {
        "panel_coverage": coverage,
        "panel_transitions": transitions,
        "panel_permutation": permutation,
        "panel_2019": year_2019,
    }


if __name__ == "__main__":
    import sys

    root = Path(__file__).resolve().parents[2]
    result = run(root / "data" / "raw", root)
    for name, table in result.items():
        print(f"--- {name} ---")
        print(table.to_string(index=False))
    sys.exit(0)
