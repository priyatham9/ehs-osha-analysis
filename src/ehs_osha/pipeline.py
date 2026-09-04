"""End-to-end analysis pipeline.

Every table under ``outputs/tables`` and every figure under ``outputs/figures``
is written by this module. Nothing is hand-entered. ``outputs/summary.json``
records the configuration, the input provenance and the headline numbers, so a
reader can diff two runs and see exactly what changed.

The pipeline runs in five stages:

1. Load and harmonise the ITA 300A files (:mod:`ehs_osha.load`).
2. Apply the plausibility screen and quantify its effect on aggregate rates,
   including a sensitivity grid over the screen bounds (:mod:`ehs_osha.quality`).
3. Build NAICS x size-band percentile tables (:mod:`ehs_osha.peers`).
4. Fit and compare count models on recordable-case counts
   (:mod:`ehs_osha.countmodels`).
5. Measure year-over-year stability of the percentile bands
   (:mod:`ehs_osha.stability`).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from . import countmodels, naics as naics_titles, peers, quality, stability, svgplot
from .load import LoadReport, load_ita_300a
from .quality import PlausibilityConfig

EXPOSURE_UNIT_HOURS = 200_000.0


@dataclass
class PipelineConfig:
    """Runtime configuration for :func:`run_pipeline`.

    Attributes:
        data_dir: Directory holding the raw OSHA downloads.
        out_dir: Directory to write tables, figures and the summary into.
        plausibility: Screen bounds.
        naics_level: NAICS prefix used for peer grouping.
        min_group_n: Minimum establishments for a publishable peer cell.
        model_naics3: Explicit NAICS 3-digit codes to fit count models on.
            ``None`` (the default) selects industries by size instead: the
            ``model_top_k`` largest groups with at least ``model_min_group_n``
            establishments. Size-based selection is preferred because it cannot
            be accused of picking industries that flatter a chosen model.
        model_top_k: Number of industries to fit when ``model_naics3`` is None.
        model_min_group_n: Minimum establishments for an industry to be fitted.
        model_year: Reporting year used for the count-model fits.
        model_max_n: Cap on rows per model fit, for runtime. Sampling is
            deterministic (fixed seed) and the realised n is reported.
        include_partial: Include partial-year source files.
        years: Restrict the load to these reporting years.
        random_seed: Seed for the model-fit subsample.
    """

    data_dir: Path
    out_dir: Path
    plausibility: PlausibilityConfig = field(default_factory=PlausibilityConfig)
    naics_level: str = "naics3"
    min_group_n: int = 30
    model_naics3: Optional[Sequence[str]] = None
    model_top_k: int = 30
    model_min_group_n: int = 500
    model_year: int = 2024
    model_max_n: int = 60_000
    include_partial: bool = False
    years: Optional[Sequence[int]] = None
    random_seed: int = 20260903

    def to_json(self) -> dict:
        """Return a JSON-serialisable dict of this configuration."""
        return {
            "data_dir": str(self.data_dir),
            "out_dir": str(self.out_dir),
            "plausibility": self.plausibility.to_json(),
            "naics_level": self.naics_level,
            "min_group_n": self.min_group_n,
            "model_naics3": list(self.model_naics3) if self.model_naics3 else None,
            "model_top_k": self.model_top_k,
            "model_min_group_n": self.model_min_group_n,
            "model_year": self.model_year,
            "model_max_n": self.model_max_n,
            "include_partial": self.include_partial,
            "years": list(self.years) if self.years else None,
            "random_seed": self.random_seed,
        }


def _write_table(df: pd.DataFrame, out_dir: Path, name: str) -> Path:
    """Write a DataFrame to ``out_dir/tables/<name>.csv``.

    Args:
        df: Table to write.
        out_dir: Pipeline output root.
        name: Base filename without extension.

    Returns:
        The path written.
    """
    path = Path(out_dir) / "tables" / f"{name}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


def stage_quality(
    df: pd.DataFrame, cfg: PipelineConfig
) -> "tuple[pd.DataFrame, Dict[str, object]]":
    """Run the plausibility screen and write every quality table.

    Args:
        df: Harmonised frame.
        cfg: Pipeline configuration.

    Returns:
        ``(screened_frame, summary_dict)``.
    """
    screened = quality.apply_screen(df, cfg.plausibility)

    overall = quality.summarise_screen(screened, label="pooled_all_years")
    by_year = quality.summarise_by(screened, "year_filing_for")
    by_naics2 = quality.summarise_by(screened, "naics2")
    flags = quality.flag_prevalence(screened)
    sens = quality.sensitivity_grid(df)
    conc = quality.hours_concentration(df, top_ns=(1, 10, 100, 1000, 10000))

    _write_table(pd.DataFrame([overall.to_json()]), cfg.out_dir, "quality_overall")
    _write_table(by_year, cfg.out_dir, "quality_by_year")
    _write_table(by_naics2, cfg.out_dir, "quality_by_naics2")
    _write_table(flags, cfg.out_dir, "quality_flag_prevalence")
    _write_table(sens, cfg.out_dir, "quality_sensitivity_grid")
    _write_table(conc, cfg.out_dir, "quality_hours_concentration")

    worst = (
        screened.loc[
            screened["flag_hours_per_employee_high"],
            [
                "year_filing_for",
                "establishment_id",
                "naics_code",
                "annual_average_employees",
                "total_hours_worked",
                "hours_per_employee",
                "recordable_cases",
            ],
        ]
        .sort_values("total_hours_worked", ascending=False)
        .head(50)
    )
    _write_table(worst, cfg.out_dir, "quality_top50_implausible_hours")

    summary: Dict[str, object] = {
        "screen_config": cfg.plausibility.to_json(),
        "pooled": overall.to_json(),
        "by_year": by_year.to_dict(orient="records"),
        "flag_prevalence": flags.to_dict(orient="records"),
        "hours_concentration": conc.to_dict(orient="records"),
        "sensitivity_min_ratio": float(
            np.nanmin(sens["ratio_screened_to_unscreened"])
        )
        if len(sens)
        else float("nan"),
        "sensitivity_max_ratio": float(
            np.nanmax(sens["ratio_screened_to_unscreened"])
        )
        if len(sens)
        else float("nan"),
        "sensitivity_min_corrected_trir": float(
            np.nanmin(sens["aggregate_trir_screened"])
        )
        if len(sens)
        else float("nan"),
        "sensitivity_max_corrected_trir": float(
            np.nanmax(sens["aggregate_trir_screened"])
        )
        if len(sens)
        else float("nan"),
        # The flagged share moves a good deal more across the grid than the
        # corrected aggregate does. Both ends are exported so the README quotes
        # the computed range rather than a remembered one.
        "sensitivity_min_flagged_share": float(np.nanmin(sens["implausible_share"]))
        if len(sens)
        else float("nan"),
        "sensitivity_max_flagged_share": float(np.nanmax(sens["implausible_share"]))
        if len(sens)
        else float("nan"),
        "zero_recordable_share": _zero_share_summary(screened),
    }
    return screened, summary


def _zero_share_summary(screened: pd.DataFrame) -> Dict[str, object]:
    """Share of plausible filings reporting zero recordable cases.

    Reported overall, for NAICS 325 (chemical manufacturing), and by year for
    both, because the README quotes those figures and every number the README
    quotes should come out of a generated artefact rather than a keyboard.

    Args:
        screened: Frame returned by :func:`ehs_osha.quality.apply_screen`.

    Returns:
        A JSON-serialisable dict of pooled and per-year zero shares.
    """
    clean = screened[~screened["implausible"]]

    def share(frame: pd.DataFrame) -> float:
        if not len(frame):
            return float("nan")
        rec = frame["recordable_cases"].to_numpy(dtype="float64", na_value=np.nan)
        return float(np.nanmean(rec == 0))

    naics3 = (
        clean["naics3"]
        if "naics3" in clean.columns
        else clean["naics_code"].astype("string").str.slice(0, 3)
    )
    chem = clean[naics3 == "325"]
    out: Dict[str, object] = {
        "all_industries_pooled": share(clean),
        "naics325_pooled": share(chem),
        "by_year": [],
    }
    for year in sorted(pd.unique(clean["year_filing_for"].dropna())):
        out["by_year"].append(
            {
                "year": int(year),
                "all_industries": share(clean[clean["year_filing_for"] == year]),
                "naics325": share(chem[chem["year_filing_for"] == year]),
            }
        )
    return out


def stage_peers(
    screened: pd.DataFrame, cfg: PipelineConfig
) -> "tuple[pd.DataFrame, pd.DataFrame, Dict[str, object]]":
    """Build peer keys and percentile tables.

    Args:
        screened: Output of :func:`stage_quality`.
        cfg: Pipeline configuration.

    Returns:
        ``(keyed_frame, percentile_table, summary_dict)``.
    """
    keyed = peers.add_peer_keys(screened, naics_level=cfg.naics_level)
    tcfg = peers.PeerTableConfig(
        metric="trir", min_group_n=cfg.min_group_n, naics_level=cfg.naics_level
    )
    table = peers.percentile_table(keyed, tcfg, year_column="year_filing_for")
    pooled = peers.percentile_table(keyed, tcfg, year_column=None)

    _write_table(table, cfg.out_dir, "peer_percentiles_by_year")
    _write_table(pooled, cfg.out_dir, "peer_percentiles_pooled")

    size_rows: List[dict] = []
    for band, grp in keyed[~keyed["implausible"]].groupby("size_band", observed=True):
        rec = grp["recordable_cases"].to_numpy(dtype="float64", na_value=np.nan)
        hrs = float(np.nansum(grp["total_hours_worked"].to_numpy(dtype="float64", na_value=np.nan)))
        size_rows.append(
            {
                "size_band": band,
                "n": int(len(grp)),
                "zero_share": float(np.nanmean(rec == 0)),
                "mean_recordables": float(np.nanmean(rec)),
                "var_recordables": float(np.nanvar(rec)),
                "variance_to_mean_ratio": float(
                    np.nanvar(rec) / np.nanmean(rec) if np.nanmean(rec) > 0 else np.nan
                ),
                "aggregate_trir": 200000.0 * float(np.nansum(rec)) / hrs
                if hrs > 0
                else float("nan"),
                "median_establishment_trir": float(
                    np.nanmedian(grp["trir"].to_numpy(dtype="float64", na_value=np.nan))
                ),
            }
        )
    # Order by the declared band sequence, not lexically: a plain string sort
    # puts "1000+" between "100-249" and "250-499", which silently breaks the
    # monotonicity the size-effect table exists to show.
    size_effects = pd.DataFrame(size_rows)
    if len(size_effects):
        band_rank = {label: i for i, label in enumerate(peers.SIZE_BAND_LABELS)}
        size_effects = (
            size_effects.assign(
                _rank=size_effects["size_band"].map(band_rank).fillna(len(band_rank))
            )
            .sort_values("_rank")
            .drop(columns="_rank")
            .reset_index(drop=True)
        )
    _write_table(size_effects, cfg.out_dir, "size_band_effects")

    return (
        keyed,
        table,
        {
            "coverage_by_year": peers.coverage_summary(table),
            "coverage_pooled": peers.coverage_summary(pooled),
            "size_band_effects": size_effects.to_dict(orient="records"),
        },
    )


def stage_count_models(
    keyed: pd.DataFrame, cfg: PipelineConfig
) -> "tuple[pd.DataFrame, Dict[str, object]]":
    """Fit and compare count models within selected NAICS 3-digit industries.

    Args:
        keyed: Frame from :func:`stage_peers`.
        cfg: Pipeline configuration.

    Returns:
        ``(comparison_table, summary_dict)``.
    """
    rng = np.random.default_rng(cfg.random_seed)
    rows: List[dict] = []
    detail: Dict[str, object] = {}
    zero_fit_rows: List[dict] = []

    base = keyed[
        (~keyed["implausible"]) & (keyed["year_filing_for"] == cfg.model_year)
    ]

    # Which industries to fit. A short hand-picked list invites the objection
    # that the industries were chosen after seeing which ones favoured a
    # particular model, so the default is data-driven: every NAICS 3-digit
    # group with at least `model_min_group_n` establishments, taken in
    # descending size order and capped at `model_top_k`. The selection rule
    # depends only on group size, never on fit quality or outcome values.
    if cfg.model_naics3 is not None:
        selected = [str(code) for code in cfg.model_naics3]
    else:
        counts = base["naics3"].value_counts()
        counts = counts[counts >= cfg.model_min_group_n]
        selected = [str(code) for code in counts.index[: cfg.model_top_k]]

    for naics in selected:
        sub = base[base["naics3"] == naics]
        if len(sub) < 200:
            continue
        if len(sub) > cfg.model_max_n:
            idx = rng.choice(len(sub), size=cfg.model_max_n, replace=False)
            sub = sub.iloc[np.sort(idx)]
        y = sub["recordable_cases"].to_numpy(dtype="float64", na_value=np.nan)
        e = (
            sub["total_hours_worked"].to_numpy(dtype="float64", na_value=np.nan)
            / EXPOSURE_UNIT_HOURS
        )
        try:
            fits, tests = countmodels.compare_models(y, e)
        except ValueError:
            continue
        yv, ev = countmodels.prepare_counts(y, e)
        best = min(fits, key=lambda f: f.aic)
        for f in fits:
            rec = f.to_json()
            rec.update(
                {
                    "naics3": naics,
                    "year": cfg.model_year,
                    # Official NAICS subsector title. This is the name of the
                    # group being modelled.
                    "naics3_title": naics_titles.naics3_title(naics) or "",
                    # The modal *establishment-supplied* description inside the
                    # group. It describes a 6-digit industry, not this group,
                    # so it must never be used as the group's label; it is kept
                    # only because it says which 6-digit industry dominates.
                    "modal_establishment_industry_description": str(
                        sub["industry_description"].mode().iat[0]
                    )
                    if "industry_description" in sub.columns and len(sub)
                    else "",
                    "is_best_by_aic": f.model == best.model,
                    # Pulled out of `params` so downstream code never has to
                    # parse a stringified dict back out of the written CSV.
                    "zero_inflation_pi": float(f.params.get("pi", float("nan"))),
                    "dispersion_alpha": float(f.params.get("alpha", float("nan"))),
                    "observed_mean": float(np.mean(yv)),
                    "observed_variance": float(np.var(yv)),
                    "variance_to_mean_ratio": float(np.var(yv) / np.mean(yv))
                    if np.mean(yv) > 0
                    else float("nan"),
                }
            )
            rows.append(rec)
        detail[naics] = {
            "n": int(yv.size),
            "tests": tests,
            "best_model_by_aic": best.model,
        }

        obs = np.bincount(yv.astype(int), minlength=11)[:11].astype("float64")
        obs[10] = float(np.sum(yv >= 10))
        for f in fits:
            pred = countmodels.predicted_count_distribution(f, ev, max_count=10)
            for k in range(11):
                zero_fit_rows.append(
                    {
                        "naics3": naics,
                        "model": f.model,
                        "count": k if k < 10 else "10+",
                        "observed": float(obs[k]),
                        "expected": float(pred[k]),
                    }
                )

    table = pd.DataFrame(rows)
    _write_table(table, cfg.out_dir, "count_model_comparison")
    _write_table(pd.DataFrame(zero_fit_rows), cfg.out_dir, "count_model_fit_detail")

    # Across-industry model selection. With one industry the winning family is
    # an anecdote; across every large industry it is a claim about the shape of
    # establishment-level recordable counts. `zinb_pi_effectively_zero` counts
    # the fits where the zero-inflation parameter collapsed to the boundary,
    # i.e. where ZINB reduced to NB2 and bought nothing but a spare parameter.
    selection = pd.DataFrame()
    if len(table):
        wins = (
            table[table["is_best_by_aic"]]
            .groupby("model")
            .size()
            .reindex(["poisson", "nb2", "zip", "zinb"], fill_value=0)
        )
        zinb_pi = table.loc[table["model"] == "zinb", "zero_inflation_pi"]
        pi_values = [float(v) for v in zinb_pi.to_numpy(dtype="float64")]
        n_groups = int(table["naics3"].nunique())
        selection = pd.DataFrame(
            [
                {
                    "model": model,
                    "n_industries_best_by_aic": int(wins.get(model, 0)),
                    "n_industries_fitted": n_groups,
                    "share_best_by_aic": float(wins.get(model, 0)) / n_groups
                    if n_groups
                    else float("nan"),
                }
                for model in ["poisson", "nb2", "zip", "zinb"]
            ]
        )
        selection.attrs["zinb_pi_effectively_zero"] = int(
            sum(1 for v in pi_values if v == v and v < 1e-6)
        )
        _write_table(selection, cfg.out_dir, "count_model_selection_summary")

    summary: Dict[str, object] = {
        "per_industry": detail,
        "industries_fitted": sorted(detail.keys()),
        "n_industries_fitted": len(detail),
        "selection_by_aic": selection.to_dict(orient="records")
        if len(selection)
        else [],
        "zinb_pi_collapsed_to_zero": int(
            selection.attrs.get("zinb_pi_effectively_zero", 0)
        )
        if len(selection)
        else 0,
    }
    return table, summary


def stage_stability(
    table: pd.DataFrame, cfg: PipelineConfig
) -> Dict[str, object]:
    """Measure year-over-year stability of the percentile bands.

    Args:
        table: Per-year percentile table from :func:`stage_peers`.
        cfg: Pipeline configuration.

    Returns:
        Summary dictionary.
    """
    stab = stability.year_pair_stability(
        table, group_columns=(cfg.naics_level, "size_band")
    )
    persist = stability.group_persistence(
        table, group_columns=(cfg.naics_level, "size_band")
    )
    _write_table(stab, cfg.out_dir, "percentile_band_stability")
    _write_table(persist, cfg.out_dir, "peer_group_persistence")
    return {
        "headline": stability.summarise_stability(stab),
        "persistence": persist.to_dict(orient="records"),
    }


def make_figures(
    screened: pd.DataFrame,
    keyed: pd.DataFrame,
    by_year: pd.DataFrame,
    count_table: pd.DataFrame,
    stab_table: pd.DataFrame,
    cfg: PipelineConfig,
    provenance: str,
) -> List[str]:
    """Render every figure. Returns the list of paths written.

    Args:
        screened: Screened frame.
        keyed: Frame with peer keys.
        by_year: Per-year quality summary.
        count_table: Count-model comparison table.
        stab_table: Per-year percentile table (for the stability scatter).
        cfg: Pipeline configuration.
        provenance: Subtitle text describing the data vintage.

    Returns:
        Paths of the SVG files written.
    """
    fig_dir = Path(cfg.out_dir) / "figures"
    written: List[str] = []

    # 1. Naive vs screened aggregate TRIR by year.
    if len(by_year):
        years = [str(int(float(v))) for v in by_year["label"]]
        naive = list(by_year["aggregate_trir_unscreened"].astype(float))
        scr = list(by_year["aggregate_trir_screened"].astype(float))
        ax = svgplot.Axes(ylim=(0.0, max(max(scr) * 1.15, 1.0)))
        f = svgplot.Figure(
            "Aggregate TRIR before and after the plausibility screen",
            "Reporting year",
            "Recordable cases per 200,000 hours",
            ax,
            provenance,
        )
        f.bars(years, {"unscreened (all filings)": naive, "screened": scr})
        written.append(str(f.save(fig_dir / "fig01_aggregate_trir_by_year.svg")))

    # 2. Share of reported hours carried by implausible filings, by year.
    if len(by_year):
        share = [100.0 * float(v) for v in by_year["hours_share_implausible"]]
        cnt = [100.0 * float(v) for v in by_year["implausible_share"]]
        ax = svgplot.Axes(ylim=(0.0, 105.0))
        f = svgplot.Figure(
            "A small share of filings carries most of the reported hours",
            "Reporting year",
            "Percent",
            ax,
            provenance,
        )
        f.bars(
            years,
            {
                "% of filings flagged implausible": cnt,
                "% of all reported hours held by them": share,
            },
        )
        written.append(str(f.save(fig_dir / "fig02_hours_share_implausible.svg")))

    # 3. Distribution of hours per employee (log x), with screen bounds marked.
    hpe = screened["hours_per_employee"].to_numpy(dtype="float64", na_value=np.nan)
    hpe = hpe[np.isfinite(hpe) & (hpe > 0)]
    if hpe.size:
        logs = np.log10(hpe)
        lo, hi = -1.0, 8.0
        edges = np.linspace(lo, hi, 91)
        counts, _ = np.histogram(np.clip(logs, lo, hi), bins=edges)
        centres = 0.5 * (edges[:-1] + edges[1:])
        ax = svgplot.Axes(
            xlim=(lo, hi), ylim=(0.5, max(float(counts.max()) * 1.4, 10.0)), ylog=True
        )
        f = svgplot.Figure(
            "Hours worked per average employee (log10 scale)",
            "log10(annual hours per average employee)",
            "Number of filings (log scale)",
            ax,
            provenance
            + f"  |  screen bounds: {cfg.plausibility.min_hours_per_employee:g}"
            f"-{cfg.plausibility.max_hours_per_employee:g} h",
        )
        f.line(list(centres), [max(float(c), 0.5) for c in counts], "filings", markers=False)
        for bound in (
            cfg.plausibility.min_hours_per_employee,
            cfg.plausibility.max_hours_per_employee,
            2080.0,
        ):
            x = ax.sx(math.log10(bound))
            f._body.append(
                f'<line x1="{x:.2f}" y1="{ax.plot_top}" x2="{x:.2f}" '
                f'y2="{ax.plot_bottom}" stroke="#D55E00" stroke-width="1" '
                f'stroke-dasharray="4,3" />'
            )
        written.append(
            str(f.save(fig_dir / "fig03_hours_per_employee.svg", x_ticks=list(range(0, 9))))
        )

    # 4. Observed vs model-expected count distribution for the primary industry.
    if len(count_table):
        # Which industry to draw. With an explicit list, honour the caller's
        # first choice; with size-based selection there is no "first", so use
        # the largest fitted industry.
        if cfg.model_naics3:
            primary = str(cfg.model_naics3[0])
        else:
            primary = str(
                count_table.sort_values("n", ascending=False)["naics3"].iloc[0]
            )
        detail_path = Path(cfg.out_dir) / "tables" / "count_model_fit_detail.csv"
        if detail_path.exists():
            det = pd.read_csv(detail_path)
            det = det[det["naics3"].astype(str) == primary]
            if len(det):
                labels = [str(v) for v in det[det["model"] == "poisson"]["count"]]
                obs = list(det[det["model"] == "poisson"]["observed"].astype(float))
                series = {"observed": obs}
                for m in ("poisson", "nb2", "zinb"):
                    sub = det[det["model"] == m]
                    if len(sub) == len(obs):
                        series[m] = list(sub["expected"].astype(float))
                ax = svgplot.Axes(ylim=(0.0, max(obs) * 1.2 if obs else 1.0))
                f = svgplot.Figure(
                    f"Recordable-case counts, NAICS {primary}, {cfg.model_year}: "
                    "observed vs fitted",
                    "Recordable cases in the reporting year",
                    "Number of establishments",
                    ax,
                    provenance,
                )
                f.bars(labels, series)
                written.append(
                    str(f.save(fig_dir / "fig04_count_model_fit.svg"))
                )

    # 5. Zero share and aggregate TRIR by size band.
    sb_path = Path(cfg.out_dir) / "tables" / "size_band_effects.csv"
    if sb_path.exists():
        sb = pd.read_csv(sb_path)
        if len(sb):
            ax = svgplot.Axes(ylim=(0.0, max(1.0, float(sb["zero_share"].max()) * 1.2)))
            f = svgplot.Figure(
                "Zero-recordable share falls sharply with establishment size",
                "Establishment size band (annual average employees)",
                "Share of establishments reporting zero recordables",
                ax,
                provenance,
            )
            f.bars(
                [str(v) for v in sb["size_band"]],
                {"zero-recordable share": list(sb["zero_share"].astype(float))},
            )
            written.append(str(f.save(fig_dir / "fig05_zero_share_by_size.svg")))

    # 6. Percentile band stability: p75 in year t vs t+1 across matched groups.
    if len(stab_table):
        years = sorted(pd.unique(stab_table["year_filing_for"].dropna()))
        if len(years) >= 2:
            y0, y1 = years[-2], years[-1]
            gcols = [cfg.naics_level, "size_band"]
            a = stab_table[
                (stab_table["year_filing_for"] == y0) & stab_table["publishable"]
            ].set_index(gcols)
            b = stab_table[
                (stab_table["year_filing_for"] == y1) & stab_table["publishable"]
            ].set_index(gcols)
            shared = a.index.intersection(b.index)
            if len(shared) >= 3 and "p75" in a.columns:
                va = a.loc[shared, "p75"].to_numpy(dtype="float64", na_value=np.nan)
                vb = b.loc[shared, "p75"].to_numpy(dtype="float64", na_value=np.nan)
                lim = svgplot.autoscale(np.concatenate([va, vb]))
                lim = (0.0, max(lim[1], 1.0))
                ax = svgplot.Axes(xlim=lim, ylim=lim)
                f = svgplot.Figure(
                    f"Peer-group 75th percentile TRIR: {int(y0)} vs {int(y1)}",
                    f"p75 TRIR in {int(y0)}",
                    f"p75 TRIR in {int(y1)}",
                    ax,
                    provenance + f"  |  {len(shared)} matched peer groups",
                )
                f.abline(1.0, 0.0)
                f.scatter(list(va), list(vb), "matched peer group")
                written.append(
                    str(
                        f.save(
                            fig_dir / "fig06_percentile_stability.svg",
                            x_ticks=svgplot._nice_ticks(lim[0], lim[1]),
                        )
                    )
                )
    return written


def run_pipeline(cfg: PipelineConfig, *, verbose: bool = True) -> Dict[str, object]:
    """Run the full analysis and write all outputs.

    Args:
        cfg: Pipeline configuration.
        verbose: Print stage progress.

    Returns:
        The summary dictionary that is also written to ``outputs/summary.json``.

    Raises:
        FileNotFoundError: If required raw files are absent.
    """
    t0 = datetime.now(timezone.utc)
    out_dir = Path(cfg.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if verbose:
        print("[1/5] loading OSHA ITA 300A files")
    df, load_report = load_ita_300a(
        cfg.data_dir, include_partial=cfg.include_partial, years=cfg.years
    )
    years_present = sorted(int(v) for v in pd.unique(df["year_filing_for"].dropna()))
    provenance = (
        f"OSHA ITA Form 300A, reporting years {years_present[0]}-{years_present[-1]}, "
        f"n={len(df):,} filings after deduplication"
    )

    if verbose:
        print(f"[2/5] plausibility screen over {len(df):,} filings")
    screened, quality_summary = stage_quality(df, cfg)

    if verbose:
        print("[3/5] peer groups and percentile tables")
    keyed, pct_table, peer_summary = stage_peers(screened, cfg)

    if verbose:
        print("[4/5] count models")
    count_table, count_summary = stage_count_models(keyed, cfg)

    if verbose:
        print("[5/5] percentile band stability")
    stab_summary = stage_stability(pct_table, cfg)

    figures = make_figures(
        screened, keyed, pd.DataFrame(quality_summary["by_year"]), count_table,
        pct_table, cfg, provenance
    )

    summary = {
        "generated_utc": t0.isoformat(timespec="seconds"),
        "runtime_seconds": (datetime.now(timezone.utc) - t0).total_seconds(),
        "config": cfg.to_json(),
        "load_report": load_report.to_json(),
        "years_present": years_present,
        "quality": quality_summary,
        "peers": peer_summary,
        "count_models": count_summary,
        "stability": stab_summary,
        "figures_written": figures,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, default=_json_default) + "\n"
    )
    if verbose:
        print(f"[done ] outputs in {out_dir}")
    return summary


def _json_default(o: object) -> object:
    """Fallback JSON encoder for NumPy scalars and NaN."""
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        v = float(o)
        return None if math.isnan(v) else v
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, Path):
        return str(o)
    return str(o)
