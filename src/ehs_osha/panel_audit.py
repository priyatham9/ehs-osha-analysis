"""Establishment linkage and panel-quality audit from committed tables only.

Reads these committed files in ``outputs/tables/`` (no raw OSHA data):

- ``panel_coverage.csv``: years-present distribution of ``establishment_id`` and
  id-level EIN / company-name / state drift counts
- ``panel_transitions.csv``: establishments present in both years of each pair,
  and how many of them were flagged
- ``peer_group_persistence.csv``: NAICS x size-band peer-group survival
- ``quality_by_year.csv`` and ``quality_overall.csv``: filings, flags, hours
- ``quality_hours_concentration.csv`` and ``quality_top50_implausible_hours.csv``

It writes ``outputs/tables/panel_linkage_audit.csv`` (one row per audited
quantity, including rows that the committed tables cannot answer) and
``docs/PANEL_AUDIT.md``. Run ``python3 -m ehs_osha.panel_audit`` with ``src`` on
``PYTHONPATH``. ``tests/test_panel_audit.py`` fails if either file drifts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TABLES = ROOT / "outputs" / "tables"
DOC = ROOT / "docs" / "PANEL_AUDIT.md"
TABLE = TABLES / "panel_linkage_audit.csv"

ANSWERED = "answered"
PARTIAL = "partial_bound"
NOT_ANSWERABLE = "not_answerable_from_committed_tables"

COLUMNS = ["section", "metric", "value", "share", "share_basis", "source_tables", "status"]


def _row(section, metric, value, share=None, basis="", source="", status=ANSWERED):
    return {
        "section": section,
        "metric": metric,
        "value": value,
        "share": share,
        "share_basis": basis,
        "source_tables": source,
        "status": status,
    }


def load(tables: Path = TABLES) -> Dict[str, pd.DataFrame]:
    """Read the committed input tables."""
    names = [
        "panel_coverage",
        "panel_transitions",
        "peer_group_persistence",
        "quality_by_year",
        "quality_overall",
        "quality_hours_concentration",
        "quality_top50_implausible_hours",
    ]
    return {n: pd.read_csv(tables / f"{n}.csv") for n in names}


def appearance_rows(t: Dict[str, pd.DataFrame]) -> List[dict]:
    """Rows on how many establishment ids appear in how many years."""
    cov = t["panel_coverage"].set_index("metric")["value"]
    total_ids = int(cov["distinct_establishments"])
    filings = int(t["quality_overall"]["n_filings"].iloc[0])
    src = "panel_coverage"
    rows = [_row("appearances", "distinct_establishment_ids", total_ids, source=src)]
    implied = 0
    for k in range(1, int(cov["years_covered"]) + 1):
        n = int(cov[f"establishments_in_exactly_{k}_years"])
        implied += k * n
        rows.append(_row("appearances", f"ids_in_exactly_{k}_years", n, n / total_ids,
                         "distinct ids", src))
    for k in (1, 2, 3):
        n = int(cov[f"establishments_in_exactly_{k}_years"])
        rows.append(_row("appearances", f"filings_from_ids_in_exactly_{k}_years", k * n,
                         k * n / filings, "all filings", f"{src};quality_overall"))
    rows.append(_row("appearances", "filings_implied_by_year_distribution", implied,
                     implied / filings, "all filings (1.0 means the tables reconcile)",
                     f"{src};quality_overall"))
    return rows


def adjacent_link_rows(t: Dict[str, pd.DataFrame]) -> List[dict]:
    """Share of each year's filers that also filed the next year."""
    tr = t["panel_transitions"]
    tr = tr[tr["year_prev"] != "pooled"]
    qy = t["quality_by_year"].set_index("label")["n_filings"]
    rows = []
    for _, r in tr.iterrows():
        a, b = float(r["year_prev"]), float(r["year_curr"])
        n = int(r["n_total"])
        rows.append(_row("adjacent_year_linkage", f"ids_in_both_{int(a)}_and_{int(b)}", n,
                         n / qy[a], f"{int(a)} filings", "panel_transitions;quality_by_year"))
    return rows


def drift_rows(t: Dict[str, pd.DataFrame]) -> List[dict]:
    """Attribute drift under a fixed establishment id, and the unanswerable ones."""
    cov = t["panel_coverage"].set_index("metric")["value"]
    ids = int(cov["distinct_establishments"])
    multi = int(cov["establishments_in_2_or_more_years"])
    rows = []
    for key, label in (
        ("establishment_ids_with_multiple_ein", "ein"),
        ("establishment_ids_with_multiple_company_name", "company_name"),
        ("establishment_ids_with_multiple_state", "state"),
    ):
        n = int(cov[key])
        rows.append(_row("identity_drift", f"ids_with_more_than_one_{label}", n, n / ids,
                         "all distinct ids", "panel_coverage"))
        rows.append(_row("identity_drift", f"ids_with_more_than_one_{label}", n, n / multi,
                         "ids in 2+ years (only these can change)", "panel_coverage"))
    pp = t["peer_group_persistence"]
    rows.append(_row("industry_size_drift", "peer_group_matched_share_min",
                     round(float(pp["matched_share_of_year_from"].min()), 6), None,
                     "NAICS x size-band groups, adjacent year pairs",
                     "peer_group_persistence", PARTIAL))
    rows.append(_row("industry_size_drift", "peer_group_matched_share_max",
                     round(float(pp["matched_share_of_year_from"].max()), 6), None,
                     "NAICS x size-band groups, adjacent year pairs",
                     "peer_group_persistence", PARTIAL))
    for m in ("ids_changing_naics_between_years", "ids_changing_size_band_between_years"):
        rows.append(_row("industry_size_drift", m, None, None, "",
                         "none (no table holds per-id NAICS or size by year)",
                         NOT_ANSWERABLE))
    return rows


def concentration_rows(t: Dict[str, pd.DataFrame]) -> List[dict]:
    """Where the pooled screening correction sits, as far as the tables show."""
    qy = t["quality_by_year"].copy()
    qo = t["quality_overall"].iloc[0]
    flagged_hours = qy["hours_total"] * qy["hours_share_implausible"]
    total_flagged_hours = float(qo["hours_total"] * qo["hours_share_implausible"])
    rows = [_row("correction_concentration", "pooled_ratio_screened_to_unscreened",
                 round(float(qo["ratio_screened_to_unscreened"]), 4), None, "", "quality_overall")]
    for lab, fh in zip(qy["label"], flagged_hours):
        rows.append(_row("correction_concentration", f"flagged_hours_in_{int(lab)}",
                         int(round(fh)), fh / total_flagged_hours, "pooled flagged hours",
                         "quality_by_year;quality_overall"))
    hc = t["quality_hours_concentration"].set_index("top_n_filings_by_hours")
    rows.append(_row("correction_concentration", "all_reported_hours_in_largest_1_filing",
                     None, float(hc.loc[1, "hours_share"]), "all reported hours (all filings)",
                     "quality_hours_concentration"))
    top = t["quality_top50_implausible_hours"]
    rows.append(_row("correction_concentration", "all_reported_hours_in_top50_flagged_filings",
                     int(top["total_hours_worked"].sum()),
                     float(top["total_hours_worked"].sum() / qo["hours_total"]),
                     "all reported hours (all filings)", "quality_top50_implausible_hours"))
    rows.append(_row("correction_concentration", "distinct_ids_among_top50_flagged_filings",
                     int(top["establishment_id"].nunique()), None, "", "quality_top50_implausible_hours"))

    # Bound on flagged filings whose id appears in only one year.
    tr = t["panel_transitions"]
    tr = tr[tr["year_prev"] != "pooled"].copy()
    tr[["year_prev", "year_curr"]] = tr[["year_prev", "year_curr"]].astype(float)
    tr = tr.set_index(["year_prev", "year_curr"])
    n_flag = qy.set_index("label")["n_implausible"]
    upper = lower = 0
    for y in n_flag.index:
        present = []
        if (y - 1, y) in tr.index:
            r = tr.loc[(y - 1, y)]
            present.append(int(r["n11_flag_then_flag"] + r["n01_noflag_then_flag"]))
        if (y, y + 1) in tr.index:
            r = tr.loc[(y, y + 1)]
            present.append(int(r["n11_flag_then_flag"] + r["n10_flag_then_noflag"]))
        best = max(present)
        lower += best
        upper += int(n_flag[y]) - best
    n_total_flag = int(n_flag.sum())
    rows.append(_row("correction_concentration", "flagged_filings_total", n_total_flag, None,
                     "", "quality_by_year"))
    rows.append(_row("correction_concentration", "flagged_filings_from_single_year_ids_at_most",
                     upper, upper / n_total_flag, "flagged filings",
                     "panel_transitions;quality_by_year", PARTIAL))
    rows.append(_row("correction_concentration", "flagged_filings_from_multi_year_ids_at_least",
                     lower, lower / n_total_flag, "flagged filings",
                     "panel_transitions;quality_by_year", PARTIAL))
    rows.append(_row("correction_concentration", "correction_share_from_single_year_ids", None,
                     None, "", "none (no table splits hours or cases by years-present)",
                     NOT_ANSWERABLE))
    return rows


def build_table(tables: Path = TABLES) -> pd.DataFrame:
    """Return the audit table."""
    t = load(tables)
    rows = (appearance_rows(t) + adjacent_link_rows(t) + drift_rows(t)
            + concentration_rows(t))
    return pd.DataFrame(rows, columns=COLUMNS)


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def build_doc(tab: pd.DataFrame) -> str:
    """Render the docs page from the audit table."""
    g = {(r.section, r.metric, r.share_basis): r for r in tab.itertuples()}

    def v(section, metric, basis=""):
        return g[(section, metric, basis)]

    ids = int(v("appearances", "distinct_establishment_ids", "").value)
    one = v("appearances", "ids_in_exactly_1_years", "distinct ids")
    nine = v("appearances", "ids_in_exactly_9_years", "distinct ids")
    f1 = v("appearances", "filings_from_ids_in_exactly_1_years", "all filings")
    adj = tab[tab.section == "adjacent_year_linkage"]
    lo, hi = adj.share.min(), adj.share.max()
    ein = v("identity_drift", "ids_with_more_than_one_ein", "ids in 2+ years (only these can change)")
    comp = v("identity_drift", "ids_with_more_than_one_company_name", "ids in 2+ years (only these can change)")
    st = v("identity_drift", "ids_with_more_than_one_state", "ids in 2+ years (only these can change)")
    pmin = v("industry_size_drift", "peer_group_matched_share_min",
             "NAICS x size-band groups, adjacent year pairs").value
    pmax = v("industry_size_drift", "peer_group_matched_share_max",
             "NAICS x size-band groups, adjacent year pairs").value
    cc = tab[tab.section == "correction_concentration"].set_index("metric")
    yr = cc[cc.index.str.startswith("flagged_hours_in_")]
    y2019, y2024 = yr.loc["flagged_hours_in_2019"], yr.loc["flagged_hours_in_2024"]
    top1 = cc.loc["all_reported_hours_in_largest_1_filing"]
    top50 = cc.loc["all_reported_hours_in_top50_flagged_filings"]
    up = cc.loc["flagged_filings_from_single_year_ids_at_most"]
    lw = cc.loc["flagged_filings_from_multi_year_ids_at_least"]
    ratio = cc.loc["pooled_ratio_screened_to_unscreened"].value
    dist = tab[(tab.section == "appearances") & tab.metric.str.match(r"ids_in_exactly_\d_years")]
    dist_rows = "\n".join(
        f"| {m.split('_')[3]} | {int(n):,} | {_pct(s)} |"
        for m, n, s in zip(dist.metric, dist.value, dist.share)
    )
    link_rows = "\n".join(
        f"| {m.replace('ids_in_both_', '').replace('_and_', ' and ')} | {int(n):,} | {_pct(s)} |"
        for m, n, s in zip(adj.metric, adj.value, adj.share)
    )
    return f"""# Establishment linkage and panel-quality audit

Generated by `python3 -m ehs_osha.panel_audit` from committed tables in `outputs/tables/`; the numbers are in `outputs/tables/panel_linkage_audit.csv`. Do not edit by hand: `tests/test_panel_audit.py` fails if this page differs from the script output.

## Question

The {ratio:.1f}x screening correction (pooled TRIR 0.134 to 3.983) is computed on filings keyed by `establishment_id`. Before relying on panel results, three things about that key need to be known: how many years each id appears, whether the attributes attached to an id (industry, size band, EIN) are stable, and whether the correction sits in ids that appear only once.

## Data and scope

Only committed outputs are read: `panel_coverage.csv`, `panel_transitions.csv`, `peer_group_persistence.csv`, `quality_by_year.csv`, `quality_overall.csv`, `quality_hours_concentration.csv`, `quality_top50_implausible_hours.csv`. No raw filings are used. Each row of the audit table has a `status`: `answered`, `partial_bound` (the tables give a bound or a proxy, not the quantity), or `not_answerable_from_committed_tables`.

## 1. How many establishments appear in how many years

{ids:,} distinct ids over 2016-2024. {_pct(one.share)} ({int(one.value):,}) appear in exactly one year; {_pct(nine.share)} ({int(nine.value):,}) appear in all nine. Ids seen in exactly one year account for {_pct(f1.share)} of all 2,801,064 filings. The year distribution reconciles with the filing total (implied filings divided by actual filings is 1.0).

| Years present | Ids | Share of ids |
|---:|---:|---:|
{dist_rows}

Adjacent-year linkage, from the establishments present in both years of each pair, as a share of the earlier year's filings: {_pct(lo)} to {_pct(hi)}.

| Year pair | Ids in both years | Share of earlier year's filings |
|---|---:|---:|
{link_rows}

## 2. Do ids change industry or size band between years

**Not answerable from committed tables.** No committed table holds NAICS code or employee size band per id per year (only the top-50 flagged-hours filings carry a NAICS code, one filing each). Counting ids that change industry or size band needs the raw filings. The only committed proxy is group-level: of the NAICS x size-band peer groups present in one year, {_pct(pmin)} to {_pct(pmax)} are present in the next (`peer_group_persistence.csv`). That measures whether groups survive, not whether establishments move between them, and a group can survive while its members change.

What the tables do show is drift in other attributes of an id. Among the ids that appear in 2 or more years (the only ones that can change), {_pct(ein.share)} carry more than one EIN, {_pct(comp.share)} more than one company name and {_pct(st.share)} more than one state. `establishment_id` therefore tracks a site more reliably than a legal filer.

## 3. How much of the {ratio:.1f}x correction sits in single-appearance establishments

**The share of the correction (hours or cases) from ids that appear once is not answerable from committed tables**, because no table splits hours or cases by years present. What the tables do support:

- By year: 2019 holds {_pct(y2019.share)} and 2024 holds {_pct(y2024.share)} of pooled flagged hours (`quality_by_year.csv`).
- By filing: the single largest filing holds {_pct(top1.share)} of all reported hours, and the 50 largest flagged filings hold {_pct(top50.share)} (`quality_hours_concentration.csv`, `quality_top50_implausible_hours.csv`). These 50 filings come from 50 distinct ids; whether those ids appear in other years is not in the committed tables.
- By count of flagged filings: from adjacent-year presence alone, at most {int(up.value):,} of 57,857 flagged filings ({_pct(up.share)}) belong to ids seen in only one year, and at least {int(lw.value):,} ({_pct(lw.share)}) belong to ids seen in two or more. This is a bound on filing counts, not on the correction: the correction is dominated by a few very large-hours filings, so a count share says little about a hours share.

## Limits

- Presence in adjacent years is the only linkage the transition table records; an id absent in both neighbours may still appear in a non-adjacent year, which is why the single-year figure is an upper bound.
- `establishment_id` stability was not tested against any substitute key.
- Resolving sections 2 and 3 exactly needs the raw filings, for example a per-id table of NAICS, size band and years present.
"""


def main() -> None:
    """Write the audit table and docs page."""
    tab = build_table()
    tab.to_csv(TABLE, index=False)
    DOC.write_text(build_doc(tab), encoding="utf-8")
    print(f"wrote {TABLE}\nwrote {DOC}")


if __name__ == "__main__":
    main()
