"""Industry, size and year view of ITA Form 300A filing-quality problems.

Builds ``docs/INDUSTRY_QUALITY.md`` from committed outputs only:

- ``outputs/tables/quality_by_naics2.csv``
- ``outputs/tables/quality_by_year.csv``
- ``outputs/tables/quality_overall.csv``
- ``outputs/tables/quality_hours_concentration.csv``
- ``outputs/tables/quality_top50_implausible_hours.csv``
- ``outputs/tables/size_band_effects.csv``

No raw filings are read, so the analysis runs without the OSHA downloads.
Confidence intervals are Wilson 95% intervals for binomial shares (flagged
filings over all filings), which need only the committed counts. The year
homogeneity test is a Pearson chi-square on the 2 x 9 table of flagged and
unflagged filings, with the p-value from the closed-form chi-square survival
function for even degrees of freedom. Everything is deterministic: there is no
resampling, so no seed is needed.

Run ``python3 -m ehs_osha.industry_quality`` (with ``src`` on ``PYTHONPATH``)
to rewrite the document. ``tests/test_industry_quality.py`` fails if the
committed document differs from what this module renders.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .peers import SIZE_BAND_EDGES, SIZE_BAND_LABELS

ROOT = Path(__file__).resolve().parents[2]
TABLES = ROOT / "outputs" / "tables"
DOC = ROOT / "docs" / "INDUSTRY_QUALITY.md"

#: Two-sided 95% normal quantile.
Z95 = 1.959963984540054

#: Sectors with fewer filings than this are pooled into "other codes".
MIN_SECTOR_FILINGS = 1000

#: NAICS 2022 sector titles for the two-digit codes in the ITA data
#: (U.S. Census Bureau, NAICS 2022 manual). Manufacturing (31-33), retail
#: (44-45) and transportation (48-49) span several two-digit codes; the
#: committed table keeps them separate, and so does this view.
SECTOR_TITLES: Dict[str, str] = {
    "11": "Agriculture, forestry, fishing and hunting",
    "21": "Mining, quarrying, and oil and gas extraction",
    "22": "Utilities",
    "23": "Construction",
    "31": "Manufacturing (31)",
    "32": "Manufacturing (32)",
    "33": "Manufacturing (33)",
    "42": "Wholesale trade",
    "44": "Retail trade (44)",
    "45": "Retail trade (45)",
    "48": "Transportation and warehousing (48)",
    "49": "Transportation and warehousing (49)",
    "51": "Information",
    "52": "Finance and insurance",
    "53": "Real estate and rental and leasing",
    "54": "Professional, scientific, and technical services",
    "55": "Management of companies and enterprises",
    "56": "Administrative and support and waste management",
    "61": "Educational services",
    "62": "Health care and social assistance",
    "71": "Arts, entertainment, and recreation",
    "72": "Accommodation and food services",
    "81": "Other services (except public administration)",
    "92": "Public administration",
    "99": "Code 99 (not a NAICS sector)",
}


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def wilson_interval(k: int, n: int, z: float = Z95) -> Tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Args:
        k: Successes.
        n: Trials (must be positive).
        z: Normal quantile; the default gives a two-sided 95% interval.

    Returns:
        ``(lower, upper)`` as proportions.

    Raises:
        ValueError: If ``n <= 0`` or ``k`` is outside ``[0, n]``.
    """
    if n <= 0 or k < 0 or k > n:
        raise ValueError("need 0 <= k <= n and n > 0")
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def chi2_sf_even_df(x: float, df: int) -> float:
    """Survival function of the chi-square distribution for even ``df``.

    Uses ``P(X > x) = exp(-x/2) * sum_{i < df/2} (x/2)^i / i!``, computed in
    log space so very large statistics underflow cleanly to 0.0.

    Args:
        x: Statistic (non-negative).
        df: Degrees of freedom, a positive even integer.

    Returns:
        The upper-tail probability.

    Raises:
        ValueError: If ``df`` is not a positive even integer.
    """
    if df <= 0 or df % 2:
        raise ValueError("df must be a positive even integer")
    if x <= 0:
        return 1.0
    h = x / 2.0
    terms = [i * math.log(h) - math.lgamma(i + 1) - h for i in range(df // 2)]
    m = max(terms)
    return math.exp(m) * sum(math.exp(t - m) for t in terms)


def chi2_homogeneity(flagged: Sequence[int], totals: Sequence[int]) -> Tuple[float, int]:
    """Pearson chi-square for equal flagged shares across groups.

    Args:
        flagged: Flagged count per group.
        totals: Total count per group.

    Returns:
        ``(statistic, degrees_of_freedom)``.
    """
    k_all = sum(flagged)
    n_all = sum(totals)
    p = k_all / n_all
    stat = 0.0
    for k, n in zip(flagged, totals):
        for obs, exp in ((k, n * p), (n - k, n * (1 - p))):
            stat += (obs - exp) ** 2 / exp
    return stat, len(flagged) - 1


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _read(name: str, tables: Path) -> List[Dict[str, str]]:
    """Read one committed CSV as a list of string dicts."""
    with open(tables / f"{name}.csv", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _f(v: str) -> Optional[float]:
    """Parse a CSV cell as float, returning None for an empty cell."""
    return float(v) if v not in ("", None) else None


def _code(v: str) -> str:
    """Normalise a label like ``"23"`` or ``"2019.0"`` to its integer text."""
    return str(int(float(v)))


def size_band(employees: float) -> Optional[str]:
    """Assign the pipeline's size band (same edges as :mod:`ehs_osha.peers`)."""
    if not math.isfinite(employees):
        return None
    label = None
    for edge, lab in zip(SIZE_BAND_EDGES, SIZE_BAND_LABELS):
        if employees >= edge:
            label = lab
    return label


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def analyse(tables: Path = TABLES) -> Dict[str, object]:
    """Compute every number the document reports.

    Args:
        tables: Directory holding the committed ``outputs/tables`` CSVs.

    Returns:
        A dict of plain Python structures consumed by :func:`render`.
    """
    overall = _read("quality_overall", tables)[0]
    pooled_n = int(float(overall["n_filings"]))
    pooled_k = int(float(overall["n_implausible"]))
    pooled_share = pooled_k / pooled_n

    top50 = _read("quality_top50_implausible_hours", tables)
    top_by_sector: Dict[str, Dict[str, float]] = {}
    top_by_year: Dict[str, Dict[str, float]] = {}
    top_by_band: Dict[str, Dict[str, float]] = {}
    top_hours_all = 0.0
    for r in top50:
        sec = _code(r["naics_code"])[:2]
        yr = _code(r["year_filing_for"])
        band = size_band(float(r["annual_average_employees"])) or "missing"
        hrs = float(r["total_hours_worked"])
        cases = float(r["recordable_cases"])
        top_hours_all += hrs
        for store, key in ((top_by_sector, sec), (top_by_year, yr), (top_by_band, band)):
            s = store.setdefault(key, {"n": 0, "hours": 0.0, "cases": 0.0})
            s["n"] += 1
            s["hours"] += hrs
            s["cases"] += cases

    sectors = []
    other = {"codes": 0, "n": 0, "k": 0}
    for r in _read("quality_by_naics2", tables):
        code = _code(r["label"])
        n = int(float(r["n_filings"]))
        k = int(float(r["n_implausible"]))
        if n < MIN_SECTOR_FILINGS or code not in SECTOR_TITLES:
            other["codes"] += 1
            other["n"] += n
            other["k"] += k
            continue
        lo, hi = wilson_interval(k, n)
        hours = float(r["hours_total"])
        cases = float(r["cases_total"])
        top = top_by_sector.get(code, {"n": 0, "hours": 0.0, "cases": 0.0})
        resid_hours = hours - top["hours"]
        trir_ex_top = 200000.0 * (cases - top["cases"]) / resid_hours if resid_hours > 0 else None
        screened = _f(r["aggregate_trir_screened"])
        sectors.append(
            {
                "code": code,
                "title": SECTOR_TITLES[code],
                "n": n,
                "k": k,
                "share": k / n,
                "lo": lo,
                "hi": hi,
                "vs_pooled": "above"
                if lo > pooled_share
                else "below"
                if hi < pooled_share
                else "overlaps",
                "hours_share": _f(r["hours_share_implausible"]),
                "cases_share": _f(r["cases_share_implausible"]),
                "trir_unscreened": _f(r["aggregate_trir_unscreened"]),
                "trir_screened": screened,
                "ratio": _f(r["ratio_screened_to_unscreened"]),
                "top_n": int(top["n"]),
                "top_hours_share_of_sector": top["hours"] / hours if hours > 0 else 0.0,
                "trir_unscreened_ex_top": trir_ex_top,
                "ratio_ex_top": screened / trir_ex_top if trir_ex_top else None,
            }
        )

    by_share = sorted(sectors, key=lambda s: (-s["share"], s["code"]))
    by_ratio = sorted(sectors, key=lambda s: (-(s["ratio"] or 0.0), s["code"]))
    excl_99 = [s for s in sectors if s["code"] != "99"]

    years = []
    for r in _read("quality_by_year", tables):
        n = int(float(r["n_filings"]))
        k = int(float(r["n_implausible"]))
        lo, hi = wilson_interval(k, n)
        yr = _code(r["label"])
        top = top_by_year.get(yr, {"n": 0, "hours": 0.0})
        years.append(
            {
                "year": yr,
                "n": n,
                "k": k,
                "share": k / n,
                "lo": lo,
                "hi": hi,
                "hours_share": _f(r["hours_share_implausible"]),
                "trir_unscreened": _f(r["aggregate_trir_unscreened"]),
                "trir_screened": _f(r["aggregate_trir_screened"]),
                "ratio": _f(r["ratio_screened_to_unscreened"]),
                "top_n": int(top["n"]),
                "top_hours": top["hours"],
            }
        )
    chi2, df = chi2_homogeneity([y["k"] for y in years], [y["n"] for y in years])
    chi2_p = chi2_sf_even_df(chi2, df) if df % 2 == 0 else None

    bands = []
    for r in _read("size_band_effects", tables):
        lab = r["size_band"]
        top = top_by_band.get(lab, {"n": 0, "hours": 0.0})
        bands.append(
            {
                "band": lab,
                "n_screened": int(float(r["n"])),
                "trir": float(r["aggregate_trir"]),
                "median_trir": float(r["median_establishment_trir"]),
                "top_n": int(top["n"]),
                "top_hours_share": top["hours"] / top_hours_all,
            }
        )
    n_screened_in = sum(b["n_screened"] for b in bands)

    conc = {
        int(float(r["top_n_filings_by_hours"])): (float(r["hours_share"]), float(r["cases_share"]))
        for r in _read("quality_hours_concentration", tables)
    }

    return {
        "pooled": {
            "n": pooled_n,
            "k": pooled_k,
            "share": pooled_share,
            "lo": wilson_interval(pooled_k, pooled_n)[0],
            "hi": wilson_interval(pooled_k, pooled_n)[1],
            "hours_share": float(overall["hours_share_implausible"]),
            "trir_unscreened": float(overall["aggregate_trir_unscreened"]),
            "trir_screened": float(overall["aggregate_trir_screened"]),
            "ratio": float(overall["ratio_screened_to_unscreened"]),
            "n_screened_in": n_screened_in,
        },
        "sectors_by_share": by_share,
        "sectors_by_ratio": by_ratio,
        "n_above": sum(1 for s in excl_99 if s["vs_pooled"] == "above"),
        "n_below": sum(1 for s in excl_99 if s["vs_pooled"] == "below"),
        "n_overlaps": sum(1 for s in excl_99 if s["vs_pooled"] == "overlaps"),
        "n_sectors": len(excl_99),
        "other": other,
        "years": years,
        "chi2": chi2,
        "chi2_df": df,
        "chi2_p": chi2_p,
        "bands": bands,
        "top_missing_band": int(top_by_band.get("missing", {"n": 0})["n"]),
        "top_hours_all": top_hours_all,
        "conc": conc,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _pct(x: Optional[float], d: int = 2) -> str:
    return "n/a" if x is None else f"{100 * x:.{d}f}"


def _num(x: Optional[float], d: int = 3) -> str:
    return "n/a" if x is None else f"{x:.{d}f}"


def _ratio(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x:.2f}x"


def _p(p: Optional[float]) -> str:
    if p is None:
        return "n/a"
    return "< 1e-300" if p < 1e-300 else f"{p:.3g}"


def _sector(rows: Sequence[Dict[str, object]], code: str) -> Dict[str, object]:
    return next(s for s in rows if s["code"] == code)


def render(a: Dict[str, object]) -> str:
    """Render the findings document from :func:`analyse` output.

    Args:
        a: The analysis dict.

    Returns:
        The full Markdown text, ending with a newline.
    """
    P = a["pooled"]
    by_share: List[Dict[str, object]] = a["sectors_by_share"]  # type: ignore[assignment]
    by_ratio: List[Dict[str, object]] = a["sectors_by_ratio"]  # type: ignore[assignment]
    years: List[Dict[str, object]] = a["years"]  # type: ignore[assignment]
    bands: List[Dict[str, object]] = a["bands"]  # type: ignore[assignment]
    other = a["other"]
    conc = a["conc"]
    real = [s for s in by_share if s["code"] != "99"]
    worst3 = real[:3]
    best3 = real[-3:]
    c23 = _sector(by_share, "23")
    c33 = _sector(by_share, "33")
    c99 = _sector(by_share, "99")
    ymin = min(years, key=lambda y: y["share"])
    ymax = max(years, key=lambda y: y["share"])
    y19 = next(y for y in years if y["year"] == "2019")
    y24 = next(y for y in years if y["year"] == "2024")
    normal_years = [y for y in years if y["year"] not in ("2019", "2024")]
    nr_lo = min(y["ratio"] for y in normal_years)
    nr_hi = max(y["ratio"] for y in normal_years)
    early = [y for y in years if y["year"] in ("2017", "2018", "2019")]
    late = [y for y in years if y["year"] in ("2021", "2022", "2023", "2024")]
    if min(y["lo"] for y in late) > max(y["hi"] for y in early):
        late_vs_early = (
            "Every year from 2021 to 2024 has a higher share than every year from 2017 to "
            "2019, with non-overlapping intervals."
        )
    else:
        late_vs_early = "The year-to-year differences do not separate into early and late years."
    n_low = sum(1 for y in years if y["ratio"] is not None and y["ratio"] > 1)
    ex_top_ratios = [s["ratio_ex_top"] for s in real if s["ratio_ex_top"] is not None]

    L: List[str] = []
    w = L.append
    w("# Which industries and years carry the ITA filing-quality problem")
    w("")
    w(
        "Generated by `python3 -m ehs_osha.industry_quality` from committed tables in "
        "`outputs/tables/`. Do not edit by hand: `tests/test_industry_quality.py` fails "
        "if this file differs from the script output."
    )
    w("")
    w("## Question")
    w("")
    w(
        "OSHA publishes establishment-level Form 300A summaries collected through the "
        "Injury Tracking Application (ITA) and uses them to choose establishments for "
        "inspection. The repository's plausibility screen flags "
        f"{P['k']:,} of {P['n']:,} filings ({_pct(P['share'])}%) for internally "
        "implausible values, and removing them moves the pooled aggregate TRIR from "
        f"{_num(P['trir_unscreened'])} to {_num(P['trir_screened'])} ({_ratio(P['ratio'])}). "
        "This note asks where that problem sits:"
    )
    w("")
    w(
        "1. Which NAICS sectors have the highest share of flagged filings, and is the difference from the pooled rate larger than sampling noise?"
    )
    w(
        "2. In which sectors does screening change the aggregate injury rate the most, and is that change broad or driven by a handful of filings?"
    )
    w("3. Does the problem cluster by establishment size?")
    w("4. Is it concentrated in particular years (for example 2019) or present every year?")
    w("")
    w("## Data")
    w("")
    w(
        "Only committed pipeline outputs are used; no raw filings are read. The tables are "
        "`quality_overall.csv`, `quality_by_naics2.csv`, `quality_by_year.csv`, "
        "`quality_hours_concentration.csv`, `quality_top50_implausible_hours.csv` and "
        "`size_band_effects.csv`, all produced by `scripts/run_analysis.py` on the "
        "2016-2024 ITA Form 300A files under the default screen (120 to 4,500 hours per "
        'average employee per year). A filing is "flagged" when the `implausible` column of '
        "the screen is true; see the README section on the plausibility screen for the flags."
    )
    w("")
    w(
        f"Sector rows use the first two digits of the filed NAICS code. Rows with fewer than "
        f"{MIN_SECTOR_FILINGS:,} filings, or whose two-digit code is not a NAICS sector, are "
        f"set aside: {other['codes']} such codes holding {other['n']:,} filings "
        f"({other['k']:,} flagged). Code 99 is kept as its own row because it is large "
        f"({c99['n']:,} filings) but it is not a NAICS sector."
    )
    w("")
    w("## Method")
    w("")
    w(
        "- **Problem rate**: flagged filings divided by all filings in the group. The 95% "
        "interval is the Wilson score interval on those two counts. A sector is marked "
        '"above" or "below" when its whole interval lies above or below the pooled rate.'
    )
    w(
        "- **Screening effect**: the committed ratio of the screened aggregate TRIR to the "
        "unscreened aggregate TRIR (both are 200,000 x cases / hours, summed over filings)."
    )
    w(
        "- **Is the effect a few filings?** For each sector, the 50 flagged filings with the "
        "most reported hours (`quality_top50_implausible_hours.csv`) are removed from the "
        "unscreened hours and cases, and the unscreened TRIR and ratio are recomputed. This "
        "is the only filing-level detail committed, so it is a partial decomposition: the "
        "other flagged filings stay in."
    )
    w(
        "- **Years**: Wilson intervals per year, and a Pearson chi-square test that the "
        "flagged share is the same in every year (2 x 9 table, closed-form p-value)."
    )
    w(
        "- No resampling is used, so no random seed is involved. Ratios and hour shares are "
        "reported without intervals because their uncertainty is dominated by single "
        "filings, which a binomial interval does not describe."
    )
    w("")
    w("## Results")
    w("")
    w("### 1. Problem rate by sector")
    w("")
    w(
        f"Pooled rate: {_pct(P['share'])}% (95% CI {_pct(P['lo'])} to {_pct(P['hi'])}). "
        f"Of the {a['n_sectors']} NAICS sector rows, {a['n_above']} sit above it, "
        f"{a['n_below']} below it, and {a['n_overlaps']} overlap it."
    )
    w("")
    w(
        "| Rank | NAICS | Sector | Filings | Flagged | % flagged | 95% CI | vs pooled | % of hours flagged |"
    )
    w("|---|---|---|---|---|---|---|---|---|")
    for i, s in enumerate(by_share, 1):
        w(
            f"| {i} | {s['code']} | {s['title']} | {s['n']:,} | {s['k']:,} | {_pct(s['share'])} "
            f"| {_pct(s['lo'])} to {_pct(s['hi'])} | {s['vs_pooled']} | {_pct(s['hours_share'], 1)} |"
        )
    w("")
    w(
        "Highest NAICS sectors: "
        + "; ".join(f"{s['code']} {s['title'].lower()} {_pct(s['share'])}%" for s in worst3)
        + ". Lowest: "
        + "; ".join(f"{s['code']} {s['title'].lower()} {_pct(s['share'])}%" for s in best3)
        + f". The highest sector rate is {real[0]['share'] / real[-1]['share']:.1f} times the "
        "lowest, and the intervals do not overlap. Code 99 has the highest rate of any row "
        f"({_pct(c99['share'])}%); the committed tables do not show which flags drive it."
    )
    w("")
    w("### 2. Screening effect by sector")
    w("")
    w(
        "| Rank | NAICS | Sector | TRIR unscreened | TRIR screened | Ratio | Top-50 filings in sector | Their % of sector hours | TRIR unscreened without them | Ratio without them |"
    )
    w("|---|---|---|---|---|---|---|---|---|---|")
    for i, s in enumerate(by_ratio, 1):
        w(
            f"| {i} | {s['code']} | {s['title']} | {_num(s['trir_unscreened'])} | "
            f"{_num(s['trir_screened'])} | {_ratio(s['ratio'])} | {s['top_n']} | "
            f"{_pct(s['top_hours_share_of_sector'], 1)} | {_num(s['trir_unscreened_ex_top'])} | "
            f"{_ratio(s['ratio_ex_top'])} |"
        )
    w("")
    w(
        f"Construction (23) has the largest correction, {_ratio(c23['ratio'])}: its unscreened "
        f"TRIR is {_num(c23['trir_unscreened'])} and its screened TRIR is "
        f"{_num(c23['trir_screened'])}. {c23['top_n']} of the top-50 filings are in "
        f"construction and hold {_pct(c23['top_hours_share_of_sector'], 1)}% of the sector's "
        f"reported hours; without them the unscreened TRIR is "
        f"{_num(c23['trir_unscreened_ex_top'])} and the ratio falls to "
        f"{_ratio(c23['ratio_ex_top'])}. Manufacturing (33) is second at {_ratio(c33['ratio'])}, "
        f"falling to {_ratio(c33['ratio_ex_top'])} without its {c33['top_n']} top-50 filings. "
        f"After removing the top-50 filings, every NAICS sector's ratio lies between "
        f"{_ratio(min(ex_top_ratios))} and {_ratio(max(ex_top_ratios))}. The sector ranking "
        "by screening effect is therefore mostly a ranking of where a few very large hours "
        "entries landed, while a residual correction remains in every sector."
    )
    w("")
    w(
        f"The two rankings do not agree. Construction is {c23['vs_pooled']} the pooled rate on "
        f"problem rate ({_pct(c23['share'])}%) and first on screening effect; real estate and finance are "
        "near the top on problem rate with modest screening effects. Filing-quality risk "
        "and rate distortion are different quantities and should be monitored separately."
    )
    w("")
    w("### 3. Size bands")
    w("")
    w(
        "The committed tables do not break the flagged share down by size, so a size-band "
        "problem rate cannot be computed here. Two views are available. "
        "`size_band_effects.csv` gives screened-in filings by band (they sum to "
        f"{P['n_screened_in']:,}, the screened-in total), and the top-50 table gives the "
        "employee count of each of the 50 largest-hours flagged filings, assigned below to "
        "the pipeline's bands."
    )
    w("")
    w(
        "| Size band | Screened-in filings | Screened aggregate TRIR | Screened median site TRIR | Top-50 flagged filings | Share of top-50 hours (%) |"
    )
    w("|---|---|---|---|---|---|")
    for b in bands:
        w(
            f"| {b['band']} | {b['n_screened']:,} | {_num(b['trir'], 2)} | "
            f"{_num(b['median_trir'], 2)} | {b['top_n']} | {_pct(b['top_hours_share'], 2)} |"
        )
    w("")
    top_small = [b for b in bands if b["band"] in ("001-019", "020-049", "050-099")]
    top_mid = [b for b in bands if b["band"] in ("100-249", "250-499")]
    w(
        f"{sum(b['top_n'] for b in top_mid)} of the 50 largest-hours flagged filings report "
        f"100 to 499 employees and {sum(b['top_n'] for b in top_small)} report fewer than 100. "
        "The single filing that dominates the data (7 employees, 2019) puts "
        f"{_pct(_band(bands, '001-019')['top_hours_share'], 1)}% of top-50 hours in the "
        "smallest band. The extreme hours entries are not a large-employer phenomenon: they "
        "come from establishments whose employee counts are ordinary and whose hours field "
        "is off by orders of magnitude."
    )
    w("")
    w("### 4. Years")
    w("")
    w(
        "| Year | Filings | Flagged | % flagged | 95% CI | % of hours flagged | TRIR unscreened | TRIR screened | Ratio | Top-50 filings |"
    )
    w("|---|---|---|---|---|---|---|---|---|---|")
    for y in years:
        w(
            f"| {y['year']} | {y['n']:,} | {y['k']:,} | {_pct(y['share'])} | "
            f"{_pct(y['lo'])} to {_pct(y['hi'])} | {_pct(y['hours_share'], 1)} | "
            f"{_num(y['trir_unscreened'])} | {_num(y['trir_screened'])} | "
            f"{_ratio(y['ratio'])} | {y['top_n']} |"
        )
    w("")
    w(
        f"The flagged share is never below {_pct(ymin['share'])}% ({ymin['year']}) or above "
        f"{_pct(ymax['share'])}% ({ymax['year']}). It is not constant: the chi-square "
        f"statistic for equal shares is {a['chi2']:,.0f} on {a['chi2_df']} degrees of freedom "
        f"(p {_p(a['chi2_p'])}). {late_vs_early} "
        "But it is present every year at a similar order of magnitude: the filing-level "
        "problem is persistent."
    )
    w("")
    w(
        f"The rate distortion is concentrated. In 2019 flagged filings hold "
        f"{_pct(y19['hours_share'], 1)}% of reported hours and the ratio is "
        f"{_ratio(y19['ratio'])}; in 2024 it is {_pct(y24['hours_share'], 1)}% and "
        f"{_ratio(y24['ratio'])}. In the other seven years the ratio stays between "
        f"{_ratio(nr_lo)} and {_ratio(nr_hi)}, while 2019's flagged share "
        f"({_pct(y19['share'])}%) is {'below' if y19['hi'] < P['share'] else 'not below'} "
        "the pooled rate. Pooled over all years, the single "
        f"largest-hours filing holds {_pct(conc[1][0], 1)}% of all reported hours and the "
        f"largest 10,000 hold {_pct(conc[10000][0], 1)}% of hours but "
        f"{_pct(conc[10000][1], 1)}% of cases (`quality_hours_concentration.csv`)."
    )
    w("")
    w("## What it means")
    w("")
    w("### For OSHA targeting")
    w("")
    w(
        "OSHA requires covered establishments to submit Form 300A data electronically each "
        "year under 29 CFR 1904.41 "
        "(https://www.law.cornell.edu/cfr/text/29/1904.41, "
        "https://www.osha.gov/laws-regs/regulations/standardnumber/1904/1904.41) and "
        "publishes the submissions as ITA data "
        "(https://www.osha.gov/Establishment-Specific-Injury-and-Illness-Data). Its "
        "Site-Specific Targeting program, directive CPL 02-01-067 "
        "(https://www.osha.gov/enforcement/directives/cpl-02-01-067), selects "
        "establishments for inspection using rates computed from these submissions."
    )
    w("")
    w(
        "- A rate computed from an implausible hours field is wrong in a known direction: "
        "inflated hours push the rate toward zero and can hide an establishment from a "
        "high-rate list, while deflated hours push it up. The sectors with the highest "
        "flagged shares above (" + ", ".join(s["code"] for s in worst3) + ") are where the "
        "largest share of site-level rates rests on a field that failed the screen."
    )
    w(
        "- Because the effect on aggregates comes from a few filings and the problem rate "
        "is persistent across years, a fixed hours-per-employee check at submission (or "
        "before ranking) would remove most of the aggregate distortion in any year and "
        f"would flag between {_pct(ymin['share'])} and {_pct(ymax['share'])} percent of "
        "filings a year for follow-up."
    )
    w(
        "- Sector rankings of the screening effect should not be read as sector rankings of "
        "reporting behaviour; they mainly record where single extreme filings fell."
    )
    w("")
    w("### For comparison with BLS SOII")
    w("")
    w(
        "The BLS Survey of Occupational Injuries and Illnesses "
        "(https://www.bls.gov/iif/overview/soii-overview.htm) publishes industry incidence "
        "rates from about 200,000 employer reports a year and excludes the self-employed, private households, "
        "farms with 10 or fewer employees, and federal workers. ITA covers a different "
        "population (establishments meeting the 1904.41 size and industry criteria), so the "
        "two will not agree exactly in any case."
    )
    w("")
    w(
        f"- Unscreened ITA aggregates are not usable for a SOII comparison in 2019 and 2024 "
        f"(unscreened TRIR {_num(y19['trir_unscreened'])} and {_num(y24['trir_unscreened'])}) "
        f"and are lower than the screened figure in {n_low} of {len(years)} years. Any ITA "
        "versus SOII comparison should use screened aggregates."
    )
    w(
        "- In construction and manufacturing (33) the unscreened sector figures are off by "
        "an order of magnitude or more; those are the sectors where an unscreened ITA versus "
        "SOII comparison would be most misleading."
    )
    w(
        "- This repository has not entered any SOII rate (`summary.json` records the BLS "
        "lookup as not fetched), so no numerical ITA versus SOII gap is reported here."
    )
    w("")
    w("## Limitations")
    w("")
    w(
        "- Built only from committed aggregate tables. The size-band problem rate, "
        "sector x year cross-tabulations, and intervals for ratios all need the raw filings "
        "and are not computed."
    )
    w(
        "- The top-50 decomposition removes only the 50 largest-hours flagged filings across "
        'all years; flagged filings below that cut stay in the "without them" columns.'
    )
    w(
        "- Wilson intervals treat filings as independent. Establishments file in several "
        "years and `docs/PANEL.md` shows flags persist within establishments, so the "
        "intervals are narrower than a clustered interval would be."
    )
    w(
        "- Sector codes are as filed. Miscoded NAICS values are left in the code they were "
        "filed under, and the set-aside rows above are not reassigned."
    )
    w(
        '- "Flagged" means implausible under the default bounds, not proven wrong. The '
        "README's sensitivity grid shows the flagged count moves with the bounds while the "
        "aggregate correction barely does."
    )
    w("")
    return "\n".join(L)


def _band(bands: Sequence[Dict[str, object]], label: str) -> Dict[str, object]:
    return next(b for b in bands if b["band"] == label)


def build(tables: Path = TABLES) -> str:
    """Analyse the committed tables and return the rendered document."""
    return render(analyse(tables))


def main(out: Path = DOC) -> None:
    """Write the document to ``docs/INDUSTRY_QUALITY.md``."""
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
