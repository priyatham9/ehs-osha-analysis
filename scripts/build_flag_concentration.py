#!/usr/bin/env python3
"""Concentration of implausible filings and flagged hours across NAICS sectors.

Reads only ``outputs/tables/quality_by_naics2.csv`` and
``outputs/tables/quality_overall.csv``. Writes

- ``outputs/flag_concentration_sectors.csv``  (one row per sector)
- ``outputs/flag_concentration_summary.csv``  (headline metrics)
- ``outputs/flag_concentration_lorenz.csv``   (Lorenz / concentration curve points)
- ``docs/flag_concentration.md`` and ``docs/flag_concentration.svg``

Deterministic: the only randomness is a parametric bootstrap with a fixed seed.
Run ``python3 scripts/build_flag_concentration.py``; ``--check`` exits nonzero
if committed files differ from what the script would write.
"""

from __future__ import annotations

import io
import math
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ehs_osha import svgplot  # noqa: E402
from ehs_osha.industry_quality import MIN_SECTOR_FILINGS, SECTOR_TITLES  # noqa: E402

TABLES = ROOT / "outputs" / "tables"
SECTORS_CSV = ROOT / "outputs" / "flag_concentration_sectors.csv"
SUMMARY_CSV = ROOT / "outputs" / "flag_concentration_summary.csv"
LORENZ_CSV = ROOT / "outputs" / "flag_concentration_lorenz.csv"
DOC = ROOT / "docs" / "flag_concentration.md"
SVG = ROOT / "docs" / "flag_concentration.svg"

SEED = 20261105
N_BOOT = 2000
TOP_K = 5
ROUND = 9


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> Tuple[float, float]:
    """Exact two-sided binomial interval by bisection on the binomial cdf."""
    if n <= 0:
        return (float("nan"), float("nan"))
    i = np.arange(n + 1, dtype=float)
    lgam = np.vectorize(math.lgamma)
    log_choose = lgam(n + 1.0) - lgam(i + 1.0) - lgam(n - i + 1.0)

    def cdf(kk: int, p: float) -> float:  # P(X <= kk)
        if p <= 0.0:
            return 1.0
        if p >= 1.0:
            return 1.0 if kk >= n else 0.0
        lp = log_choose[: kk + 1] + i[: kk + 1] * math.log(p) + (n - i[: kk + 1]) * math.log1p(-p)
        return float(np.exp(lp).sum())

    def sf_ge(kk: int, p: float) -> float:  # P(X >= kk)
        return 1.0 - cdf(kk - 1, p) if kk > 0 else 1.0

    lo, hi = 0.0, 1.0
    if k > 0:
        a, b = 0.0, k / n
        for _ in range(60):
            m = (a + b) / 2
            if sf_ge(k, m) > alpha / 2:
                b = m
            else:
                a = m
        lo = (a + b) / 2
    if k < n:
        a, b = k / n, 1.0
        for _ in range(60):
            m = (a + b) / 2
            if cdf(k, m) > alpha / 2:
                a = m
            else:
                b = m
        hi = (a + b) / 2
    return (lo, hi)


def lorenz_points(weight: np.ndarray, flagged: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Concentration curve: sectors sorted by flagged/weight ascending."""
    order = np.argsort(flagged / weight, kind="stable")
    x = np.concatenate([[0.0], np.cumsum(weight[order]) / weight.sum()])
    y = np.concatenate([[0.0], np.cumsum(flagged[order]) / flagged.sum()])
    return x, y


def gini_from_curve(x: np.ndarray, y: np.ndarray) -> float:
    """1 - 2 * trapezoid area under the curve."""
    area = float(np.sum((x[1:] - x[:-1]) * (y[1:] + y[:-1]) / 2.0))
    return 1.0 - 2.0 * area


def load_sectors() -> pd.DataFrame:
    """Sector rows (NAICS sectors with >= MIN_SECTOR_FILINGS filings, excluding code 99)."""
    df = pd.read_csv(TABLES / "quality_by_naics2.csv", dtype={"label": str})
    df = df[(df["n_filings"] >= MIN_SECTOR_FILINGS) & df["label"].isin(SECTOR_TITLES) & (df["label"] != "99")]
    df = df.sort_values("label").reset_index(drop=True)
    df["flagged_hours"] = (df["hours_total"] * df["hours_share_implausible"]).round(0)
    return df


def compute() -> Dict[str, object]:
    """Compute all tables and headline numbers."""
    df = load_sectors()
    overall = pd.read_csv(TABLES / "quality_overall.csv").iloc[0]
    n = df["n_filings"].to_numpy(dtype=float)
    k = df["n_implausible"].to_numpy(dtype=float)
    h = df["hours_total"].to_numpy(dtype=float)
    fh = df["flagged_hours"].to_numpy(dtype=float)

    x1, y1 = lorenz_points(n, k)
    g_filings = gini_from_curve(x1, y1)
    x2, y2 = lorenz_points(h, fh)
    g_hours = gini_from_curve(x2, y2)

    rng = np.random.default_rng(SEED)
    p = k / n
    boots = []
    for _ in range(N_BOOT):
        kb = rng.binomial(n.astype(np.int64), p).astype(float)
        xb, yb = lorenz_points(n, kb)
        boots.append(gini_from_curve(xb, yb))
    g_lo, g_hi = (float(v) for v in np.percentile(boots, [2.5, 97.5]))

    # sector table
    out = pd.DataFrame(
        {
            "naics2": df["label"],
            "sector": [SECTOR_TITLES[c] for c in df["label"]],
            "n_filings": df["n_filings"].astype(int),
            "n_flagged": df["n_implausible"].astype(int),
            "flag_rate": k / n,
            "share_of_filings": n / n.sum(),
            "share_of_flagged": k / k.sum(),
            "flagged_over_filings_ratio": (k / k.sum()) / (n / n.sum()),
            "flagged_hours": fh,
            "share_of_hours": h / h.sum(),
            "share_of_flagged_hours": fh / fh.sum(),
        }
    )
    cps = [clopper_pearson(int(a), int(b)) for a, b in zip(k, n)]
    out["flag_rate_cp_lo"] = [c[0] for c in cps]
    out["flag_rate_cp_hi"] = [c[1] for c in cps]
    out = out.sort_values(["share_of_flagged", "naics2"], ascending=[False, True]).reset_index(drop=True)
    out.insert(0, "rank_by_flagged", np.arange(1, len(out) + 1))

    # top-k by rate
    by_rate = out.sort_values("flag_rate", ascending=False).head(TOP_K)
    top_rate_k = int(by_rate["n_flagged"].sum())
    top_rate_share_filings = float(by_rate["n_filings"].sum() / n.sum())
    cp_lo, cp_hi = clopper_pearson(top_rate_k, int(k.sum()))
    top3_count = out.head(3)
    by_fh = out.sort_values("share_of_flagged_hours", ascending=False)
    top3_fh = by_fh.head(3)
    hhi_h = float((out["share_of_flagged_hours"] ** 2).sum())
    hhi_n = float((out["share_of_flagged"] ** 2).sum())

    rows: List[Tuple[str, object, str]] = [
        ("n_sectors", len(out), "NAICS sector rows used (>=1,000 filings, code 99 excluded)"),
        ("n_filings_in_sectors", int(n.sum()), "filings in those rows"),
        ("n_flagged_in_sectors", int(k.sum()), "flagged filings in those rows"),
        ("pooled_flag_rate_all_rows", float(overall["implausible_share"]), "quality_overall.csv, all rows"),
        ("gini_flagged_filings", g_filings, "concentration Gini of flagged filings vs filings, sectors ordered by flag rate"),
        ("gini_flagged_filings_boot_lo", g_lo, f"2.5th percentile, {N_BOOT} binomial bootstrap draws, seed {SEED}"),
        ("gini_flagged_filings_boot_hi", g_hi, "97.5th percentile"),
        ("gini_flagged_hours", g_hours, "concentration Gini of flagged hours vs hours (near 0 because flagged filings carry most hours)"),
        (f"top{TOP_K}_rate_sectors_share_of_filings", top_rate_share_filings, "share of filings in the five highest-rate sectors"),
        (f"top{TOP_K}_rate_sectors_share_of_flagged", top_rate_k / k.sum(), "share of flagged filings in those sectors"),
        (f"top{TOP_K}_rate_sectors_share_of_flagged_cp_lo", cp_lo, "Clopper-Pearson 95% lower"),
        (f"top{TOP_K}_rate_sectors_share_of_flagged_cp_hi", cp_hi, "Clopper-Pearson 95% upper"),
        ("top3_count_sectors_share_of_flagged", float(top3_count["share_of_flagged"].sum()), "three sectors with most flagged filings"),
        ("top3_count_sectors_share_of_filings", float(top3_count["share_of_filings"].sum()), "their share of filings"),
        ("top3_flagged_hours_sectors_share_of_flagged_hours", float(top3_fh["share_of_flagged_hours"].sum()), "three sectors holding most flagged hours"),
        ("top3_flagged_hours_sectors_share_of_hours", float(top3_fh["share_of_hours"].sum()), "their share of all hours"),
        ("top1_flagged_hours_sector_share", float(top3_fh["share_of_flagged_hours"].iloc[0]), "share of flagged hours in the single largest sector (see sectors CSV)"),
        ("flagged_hours_share_of_all_hours", float(fh.sum() / h.sum()), "flagged hours / all hours in the sector rows"),
        ("hhi_flagged_filings", hhi_n, "Herfindahl index of share_of_flagged (1/24 = 0.0417 if even)"),
        ("hhi_flagged_hours", hhi_h, "Herfindahl index of share_of_flagged_hours"),
    ]
    summary = pd.DataFrame(rows, columns=["metric", "value", "note"])
    lorenz = pd.concat(
        [
            pd.DataFrame({"curve": "flagged_filings", "x_cum_share_of_filings": x1, "y_cum_share_of_flagged": y1}).rename(
                columns={"x_cum_share_of_filings": "x", "y_cum_share_of_flagged": "y"}
            ),
            pd.DataFrame({"curve": "flagged_hours", "x": x2, "y": y2}),
        ],
        ignore_index=True,
    )
    return {
        "sectors": out,
        "summary": summary,
        "lorenz": lorenz,
        "by_fh": by_fh,
        "by_rate": by_rate,
        "xy": (x1, y1, x2, y2),
    }


def _csv(df: pd.DataFrame) -> str:
    d = df.copy()
    for c in d.columns:
        if d[c].dtype == float:
            d[c] = d[c].round(ROUND)
    buf = io.StringIO()
    d.to_csv(buf, index=False, lineterminator="\n")
    return buf.getvalue()


def _s(summary: pd.DataFrame, name: str) -> float:
    return float(summary.loc[summary["metric"] == name, "value"].iloc[0])


def build_svg(res: Dict[str, object]) -> str:
    """Concentration curves as SVG."""
    x1, y1, x2, y2 = res["xy"]  # type: ignore[misc]
    s = res["summary"]
    fig = svgplot.Figure(
        title="Concentration of flagged filings and flagged hours across sectors",
        xlabel="cumulative share of filings (or hours), sectors ordered by flag rate",
        ylabel="cumulative share flagged",
        axes=svgplot.Axes(xlim=(0.0, 1.0), ylim=(0.0, 1.0)),
        subtitle=f"concentration Gini: filings {_s(s, 'gini_flagged_filings'):.3f}, hours {_s(s, 'gini_flagged_hours'):.3f}; 24 NAICS sectors",
    )
    fig.line([0.0, 1.0], [0.0, 1.0], "equal share (no concentration)", colour="#888888", markers=False)
    fig.line(list(x1), list(y1), "flagged filings", colour=svgplot.PALETTE[0])
    fig.line(list(x2), list(y2), "flagged hours", colour=svgplot.PALETTE[1])
    return fig.to_svg()


def _pct(v: float, d: int = 2) -> str:
    return f"{100 * v:.{d}f}%"


def build_doc(res: Dict[str, object]) -> str:
    """Render docs/flag_concentration.md."""
    s = res["summary"]
    sec = res["sectors"]
    g = lambda m: _s(s, m)  # noqa: E731
    top = sec.head(6)
    _b = res["by_fh"].iloc[0]
    top3_fh_names = f"NAICS {_b['naics2']} ({_b['sector']})"
    lines: List[str] = []
    a = lines.append
    a("# How concentrated are implausible filings across NAICS sectors?")
    a("")
    a("Generated by `scripts/build_flag_concentration.py` from committed tables. Do not edit by hand: `tests/test_flag_concentration.py` fails if this page, the CSVs or the chart differ from the script output.")
    a("")
    a("## Choice of analysis")
    a("")
    a("`docs/INDUSTRY_QUALITY.md` ranks sectors by flag rate with Wilson intervals, `docs/YEAR_STABILITY.md` leaves years out, and `docs/THRESHOLD_ROBUSTNESS.md` varies the bounds. None of them measures how unevenly the flagged filings and flagged hours are spread across sectors with a single summary. This page adds that: Lorenz-type concentration curves, a concentration Gini, top-k shares and exact intervals, using only `quality_by_naics2.csv` and `quality_overall.csv`.")
    a("")
    a("## Method")
    a("")
    a(f"- Rows: the {int(g('n_sectors'))} two-digit NAICS sector rows with at least {MIN_SECTOR_FILINGS:,} filings; code 99 (not a sector) and small codes are excluded. They hold {int(g('n_filings_in_sectors')):,} filings, of which {int(g('n_flagged_in_sectors')):,} are flagged.")
    a("- Concentration curve: sectors are sorted by flag rate from lowest to highest; x is the cumulative share of filings, y the cumulative share of flagged filings. The concentration Gini is 1 - 2 x (area under the curve), computed by the trapezoid rule. 0 means every sector holds flagged filings in proportion to its filings; values near 1 mean a few sectors hold nearly all of them.")
    a("- Flagged hours: per sector, `hours_total x hours_share_implausible`. The same curve and Gini are computed with hours as the weight, sectors ordered by flagged-hours share.")
    a(f"- Intervals: the Gini interval is the 2.5th to 97.5th percentile of {N_BOOT} parametric bootstrap draws (flagged count ~ Binomial(sector filings, observed sector rate), seed {SEED}). Per-sector flag rates and the top-{TOP_K} flagged share carry exact Clopper-Pearson 95% intervals (bisection on the binomial cdf, no SciPy).")
    a("")
    a("## Results")
    a("")
    a(f"1. **Filings.** The concentration Gini of flagged filings is **{g('gini_flagged_filings'):.3f}** (bootstrap 95% interval {g('gini_flagged_filings_boot_lo'):.3f} to {g('gini_flagged_filings_boot_hi'):.3f}). The {TOP_K} sectors with the highest flag rates hold {_pct(g(f'top{TOP_K}_rate_sectors_share_of_filings'))} of filings but {_pct(g(f'top{TOP_K}_rate_sectors_share_of_flagged'))} of flagged filings (exact 95% interval {_pct(g(f'top{TOP_K}_rate_sectors_share_of_flagged_cp_lo'))} to {_pct(g(f'top{TOP_K}_rate_sectors_share_of_flagged_cp_hi'))}).")
    a(f"2. **Hours.** Flagged filings carry {_pct(g('flagged_hours_share_of_all_hours'), 1)} of all reported hours, so the hours curve sits almost on the equality line and its concentration Gini ({g('gini_flagged_hours'):.3f}) is near zero. That low value is not evenness: it only says flagged hours track total hours. The absolute concentration is extreme. {top3_fh_names} holds {_pct(g('top1_flagged_hours_sector_share'), 1)} of flagged hours alone, and the top three sectors hold {_pct(g('top3_flagged_hours_sectors_share_of_flagged_hours'), 1)}.")
    a(f"3. **Count leaders.** The three sectors with the most flagged filings hold {_pct(g('top3_count_sectors_share_of_flagged'), 1)} of them against {_pct(g('top3_count_sectors_share_of_filings'), 1)} of filings. Herfindahl index of flagged filings: {g('hhi_flagged_filings'):.4f}; of flagged hours: {g('hhi_flagged_hours'):.4f} (an even split over 24 sectors would give 0.0417).")
    a("")
    a("![Concentration curves](flag_concentration.svg)")
    a("")
    a("### Sectors with the most flagged filings")
    a("")
    a("| Rank | NAICS | Sector | Flagged | % of flagged | % of filings | Flag rate (exact 95% CI) | % of flagged hours |")
    a("|---|---|---|---|---|---|---|---|")
    for _, r in top.iterrows():
        a(f"| {int(r['rank_by_flagged'])} | {r['naics2']} | {r['sector']} | {int(r['n_flagged']):,} | {_pct(r['share_of_flagged'], 1)} | {_pct(r['share_of_filings'], 1)} | {_pct(r['flag_rate'])} ({_pct(r['flag_rate_cp_lo'])} to {_pct(r['flag_rate_cp_hi'])}) | {_pct(r['share_of_flagged_hours'], 1)} |")
    a("")
    a("The full per-sector table is `outputs/flag_concentration_sectors.csv`; the curve points are in `outputs/flag_concentration_lorenz.csv`.")
    a("")
    a("## Limitations")
    a("")
    a("- Sampling intervals describe binomial noise given the filings that exist; they say nothing about measurement error in the filings or about which flag rule fired (the committed tables do not give per-flag counts by sector).")
    a("- Flagged hours are reconstructed as `hours_total x hours_share_implausible`, both committed and rounded to float precision. No interval is given for the hours Gini because a few single filings dominate hours and a binomial model does not describe that.")
    a("- Gini and top-k shares depend on how sectors are partitioned. Manufacturing, retail and transportation are each split across several two-digit codes in the source table, and this page keeps them split, which lowers measured concentration relative to a merged partition.")
    a(f"- The top-{TOP_K} sectors are chosen from the same data they are measured on, so the interval on their share is conditional on that selection and is narrower than a fully honest selection-adjusted one.")
    a("- Exclusions (code 99 and codes under 1,000 filings) are a choice. Code 99 has the highest flag rate but is not a sector.")
    a("- Concentration here is across sectors only; it says nothing about concentration across establishments or companies within a sector.")
    a("")
    return "\n".join(lines)


def outputs() -> Dict[Path, str]:
    """Return {path: content} for every generated file."""
    res = compute()
    return {
        SECTORS_CSV: _csv(res["sectors"]),
        SUMMARY_CSV: _csv(res["summary"]),
        LORENZ_CSV: _csv(res["lorenz"]),
        DOC: build_doc(res),
        SVG: build_svg(res),
    }


def main(argv: List[str]) -> int:
    """Write (or with --check, verify) the generated files."""
    outs = outputs()
    if "--check" in argv:
        bad = [str(p) for p, t in outs.items() if not p.exists() or p.read_text(encoding="utf-8") != t]
        if bad:
            print("drift: " + ", ".join(bad))
            return 1
        return 0
    for p, t in outs.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")
        print(f"wrote {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
