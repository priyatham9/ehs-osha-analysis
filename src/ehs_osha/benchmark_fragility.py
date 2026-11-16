"""Audit trend reversals and scale blindness in screened injury benchmarks.

This is a descriptive sensitivity analysis, not a replacement plausibility
screen. Peer-cell changes do not track a fixed set of establishments. Excluding
high-influence filings supplies no estimate of their true hours or headcount.

The table-only part exactly decomposes rate changes on common support using
the symmetric (Kitagawa) identity:
    R1 - R0 = sum((w1+w0)/2 * (r1-r0))
            + sum((r1+r0)/2 * (w1-w0)).
The difference between the full-population and matched-cell changes is kept
explicitly as the support residual; it is never assigned to a within effect.

The raw-data part verifies source hashes and independently reconciles every
annual total before computing exclusions. Selection of influential rows uses
hours, not case counts. Raw filings are never changed or imputed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .catalog import all_files
from .load import load_ita_300a
from .quality import PlausibilityConfig, apply_screen
from .influence_audit import build_influence_audit

ROOT = Path(__file__).resolve().parents[2]
KEYS = ["naics3", "size_band"]
SCALE = 200000.0


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_peers(peers: pd.DataFrame) -> pd.DataFrame:
    """Reject ambiguous keys/nonfinite exposures; reconstruct counts from rates."""
    p = peers.copy()
    if p[["year_filing_for"] + KEYS].isna().any().any():
        raise ValueError("Peer keys cannot be missing")
    p["naics3"] = p.naics3.astype(str)
    p["year_filing_for"] = p.year_filing_for.astype(int)
    if p.duplicated(["year_filing_for"] + KEYS).any():
        raise ValueError("Duplicate year/peer-cell keys")
    for col in ("hours_total", "aggregate_trir", "n"):
        if not np.isfinite(p[col]).all():
            raise ValueError(f"Nonfinite {col}")
    if (p.hours_total <= 0).any() or (p.aggregate_trir < 0).any() or (p.n <= 0).any():
        raise ValueError("Hours and counts must be positive; rates nonnegative")
    p["cases_reconstructed"] = p.hours_total * p.aggregate_trir / SCALE
    if not np.allclose(p.cases_reconstructed, p.cases_reconstructed.round(), atol=1e-6, rtol=0):
        raise ValueError("Rates and exposures do not reconstruct integer case counts")
    p["cases_reconstructed"] = p.cases_reconstructed.round().astype("int64")
    return p


def annual_rates(peers: pd.DataFrame, quality: pd.DataFrame) -> list[dict]:
    """Reconcile all peer cells (including small cells) to screened totals."""
    rows = []
    q = quality.set_index(quality.label.astype(float).astype(int))
    for year, g in peers.groupby("year_filing_for"):
        h, c, n = float(g.hours_total.sum()), int(g.cases_reconstructed.sum()), int(g.n.sum())
        s = q.loc[year]
        expected_h = s.hours_total * (1 - s.hours_share_implausible)
        expected_c = s.cases_total * (1 - s.cases_share_implausible)
        if not (n == int(s.n_filings - s.n_implausible)
                and np.isclose(h, expected_h, rtol=1e-10)
                and np.isclose(c, expected_c, rtol=0, atol=1e-6)
                and np.isclose(SCALE * c / h, s.aggregate_trir_screened, rtol=1e-10)):
            raise ValueError(f"Peer-cell totals fail screened reconciliation for {year}")
        rows.append({"year": int(year), "n_filings": n, "hours": h,
                     "cases": c, "rate": SCALE * c / h})
    return rows


def rate(g: pd.DataFrame) -> float:
    h = float(g.hours_total.sum())
    return SCALE * float(g.cases_reconstructed.sum()) / h if h else float("nan")


def decompose_pair(before: pd.DataFrame, after: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """Exact common-support decomposition; all weights are exposure shares."""
    a, b = before.set_index(KEYS), after.set_index(KEYS)
    if a.index.has_duplicates or b.index.has_duplicates:
        raise ValueError("Duplicate peer keys")
    z = a.join(b, how="inner", lsuffix="_before", rsuffix="_after")
    if z.empty:
        raise ValueError("No common peer cells")
    h0, h1 = z.hours_total_before.sum(), z.hours_total_after.sum()
    w0, w1 = z.hours_total_before / h0, z.hours_total_after / h1
    r0, r1 = z.aggregate_trir_before, z.aggregate_trir_after
    z["weight_before"], z["weight_after"] = w0, w1
    z["within_contribution"] = (w0 + w1) / 2 * (r1 - r0)
    z["composition_contribution"] = (r0 + r1) / 2 * (w1 - w0)
    matched0, matched1 = float((w0 * r0).sum()), float((w1 * r1).sum())
    full0, full1 = rate(before), rate(after)
    within, composition = float(z.within_contribution.sum()), float(z.composition_contribution.sum())
    out = {
        "year_before": int(before.year_filing_for.iloc[0]),
        "year_after": int(after.year_filing_for.iloc[0]),
        "n_cells_matched": len(z), "n_cells_before": len(a), "n_cells_after": len(b),
        "n_filings_before": int(a.n.sum()), "n_filings_after": int(b.n.sum()),
        "n_filings_matched_before": int(z.n_before.sum()),
        "n_filings_matched_after": int(z.n_after.sum()),
        "hours_coverage_before": float(h0 / a.hours_total.sum()),
        "hours_coverage_after": float(h1 / b.hours_total.sum()),
        "full_rate_before": full0, "full_rate_after": full1,
        "full_change": full1 - full0,
        "matched_rate_before": matched0, "matched_rate_after": matched1,
        "matched_change": matched1 - matched0,
        "within_effect": within, "composition_effect": composition,
        "support_residual": (full1 - full0) - (matched1 - matched0),
        "fixed_before_weight_rate_after": float((w0 * r1).sum()),
        "fixed_after_weight_rate_before": float((w1 * r0).sum()),
        "within_effect_before_weights": float((w0 * (r1 - r0)).sum()),
        "within_effect_after_weights": float((w1 * (r1 - r0)).sum()),
        "declining_cells": int((r1 < r0).sum()),
        "unchanged_cells": int((r1 == r0).sum()),
        "rank_spearman": (float(r0.rank().corr(r1.rank()))
                          if len(z) > 1 and r0.nunique() > 1 and r1.nunique() > 1 else None),
    }
    if not np.isclose(within + composition, out["matched_change"], rtol=0, atol=1e-10):
        raise AssertionError("Decomposition identity failed")
    return out, z.reset_index()


def leave_one_cell_out(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    """Remove each cell from both populations; retain unmatched-cell effects."""
    a, b = before.set_index(KEYS), after.set_index(KEYS)
    z = a[["hours_total", "cases_reconstructed"]].join(
        b[["hours_total", "cases_reconstructed"]], how="outer", lsuffix="_before", rsuffix="_after").fillna(0)
    h0, h1 = a.hours_total.sum(), b.hours_total.sum()
    c0, c1 = a.cases_reconstructed.sum(), b.cases_reconstructed.sum()
    z["rate_before_exclusion"] = SCALE * (c0-z.cases_reconstructed_before) / (h0-z.hours_total_before)
    z["rate_after_exclusion"] = SCALE * (c1-z.cases_reconstructed_after) / (h1-z.hours_total_after)
    z["change_after_exclusion"] = z.rate_after_exclusion-z.rate_before_exclusion
    z["change_original"] = SCALE*c1/h1-SCALE*c0/h0
    z["direction_reversed"] = z.change_after_exclusion*z.change_original < 0
    z["year_before"] = int(before.year_filing_for.iloc[0])
    z["year_after"] = int(after.year_filing_for.iloc[0])
    return z.reset_index()


def table_analysis(peers: pd.DataFrame, quality: pd.DataFrame) -> tuple[dict, dict[str, pd.DataFrame]]:
    p = validate_peers(peers)
    annual = annual_rates(p, quality)
    summaries, cells, influence = [], [], []
    years = sorted(p.year_filing_for.unique())
    for y0, y1 in zip(years[:-1], years[1:]):
        a, b = p[p.year_filing_for == y0], p[p.year_filing_for == y1]
        scenarios = {
            "all_cells": (a, b),
            "publishable_cells": (a[a.publishable], b[b.publishable]),
            "exclude_623_1000plus": (a[~((a.naics3 == "623") & (a.size_band == "1000+"))], b[~((b.naics3 == "623") & (b.size_band == "1000+"))]),
            "exclude_623": (a[a.naics3 != "623"], b[b.naics3 != "623"]),
            "exclude_healthcare_621_622_623": (a[~a.naics3.isin(["621", "622", "623"])], b[~b.naics3.isin(["621", "622", "623"])]),
        }
        for name, (s0, s1) in scenarios.items():
            summary, contributions = decompose_pair(s0, s1)
            summary["scenario"] = name
            summaries.append(summary)
            if name == "all_cells":
                contributions = contributions[KEYS + [f"{field}_{suffix}"
                    for field in ("n", "hours_total", "aggregate_trir", "cases_reconstructed")
                    for suffix in ("before", "after")] +
                    ["weight_before", "weight_after", "within_contribution", "composition_contribution"]]
                contributions["year_before"], contributions["year_after"] = y0, y1
                cells.append(contributions)
        influence.append(leave_one_cell_out(a, b))
    tables = {"decomposition": pd.DataFrame(summaries),
              "cell_contributions": pd.concat(cells, ignore_index=True),
              "cell_influence": pd.concat(influence, ignore_index=True)}
    influence_summary = []
    for (y0, y1), g in tables["cell_influence"].groupby(["year_before", "year_after"]):
        reversing = g[g.direction_reversed]
        influence_summary.append({"year_before": int(y0), "year_after": int(y1),
                                  "n_cells_tested": len(g), "n_reversing_cells": len(reversing),
                                  "reversing_cells": reversing[KEYS + ["rate_before_exclusion", "rate_after_exclusion", "change_after_exclusion"]].to_dict("records")})
    trajectory = p[(p.naics3 == "623") & (p.size_band == "1000+")][
        ["year_filing_for"] + KEYS + ["n", "hours_total", "cases_reconstructed", "aggregate_trir"]]
    return {"annual_rates": annual, "decomposition": summaries,
            "cell_influence_summary": influence_summary,
            "selected_cell_trajectory": trajectory.to_dict("records")}, tables


def filing_record(row: pd.Series) -> dict:
    return {"year": int(row.year_filing_for), "filing_id": int(row.id),
            "establishment_id": int(row.establishment_id), "naics_code": int(row.naics_code),
            "employees": float(row.annual_average_employees), "hours": float(row.total_hours_worked),
            "cases": int(row.recordable_cases), "hours_per_employee": float(row.hours_per_employee),
            "passes_default_screen": not bool(row.implausible)}


def raw_analysis(data_dir: Path, annual: list[dict], years=tuple(range(2016, 2025))) -> tuple[dict, dict[str, pd.DataFrame]]:
    """Require exact pinned snapshots, reconcile totals, audit largest exposures."""
    specs = [f for f in all_files() if f.calendar_year in years]
    provenance, frames = [], []
    expected = {r["year"]: r for r in annual}
    for spec in specs:
        path = data_dir / spec.local_name
        digest = sha256(path)
        if digest != spec.expected_sha256:
            raise ValueError(f"Raw snapshot differs from pinned catalog: {path}")
        x, report = load_ita_300a(data_dir, files=[spec])
        x = apply_screen(x)
        good = x[~x.implausible]
        e = expected[spec.calendar_year]
        if not (len(good) == e["n_filings"] and good.recordable_cases.sum() == e["cases"]
                and good.total_hours_worked.sum() == e["hours"]):
            raise ValueError(f"Raw/table totals differ for {spec.calendar_year}")
        provenance.append({"year": spec.calendar_year, "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                           "url": spec.url, "sha256": digest, "bytes": path.stat().st_size,
                           "matches_catalog": True, "load_report": report.to_json()})
        frames.append(x[["id", "establishment_id", "year_filing_for", "naics_code", "annual_average_employees",
                         "total_hours_worked", "recordable_cases", "hours_per_employee", "implausible",
                         "flag_hours_missing", "flag_employees_missing", "flag_negative_counts"]])
    x = pd.concat(frames, ignore_index=True)
    good = x[~x.implausible]
    # Deterministic discovery rule: the two largest screened hours values in
    # the middle year. Outcomes are not used in this ranking.
    selected = good[good.year_filing_for == 2023].sort_values(
        ["total_hours_worked", "id"], ascending=[False, True]).head(2)
    suspects = [filing_record(r) for _, r in selected.iterrows()]
    selected_ids = selected.establishment_id.tolist()
    linked = x[x.establishment_id.isin(selected_ids)].sort_values(["establishment_id", "year_filing_for"])
    threshold_rows = []
    threshold_trends = []
    for low in (100, 120, 200, 250, 400):
        for high in (3500, 4000, 4500, 5000, 6000):
            screened = apply_screen(selected, PlausibilityConfig(low, high))
            threshold_rows.append({"low": low, "high": high, "selected_filings": len(selected),
                                   "selected_pass": int((~screened.implausible).sum())})
            trend = {"low": low, "high": high}
            for year in (2023, 2024):
                g = x[x.year_filing_for == year]
                valid = (~g[["flag_hours_missing", "flag_employees_missing", "flag_negative_counts"]].any(axis=1)
                         & g.hours_per_employee.between(low, high))
                g = g[valid]
                retained = g[~((g.year_filing_for == 2023) & g.establishment_id.isin(selected_ids))]
                trend[f"n_{year}"] = len(g)
                trend[f"rate_{year}"] = SCALE*float(g.recordable_cases.sum())/float(g.total_hours_worked.sum())
                trend[f"exclusion_rate_{year}"] = SCALE*float(retained.recordable_cases.sum())/float(retained.total_hours_worked.sum())
            trend["change_pct"] = 100*(trend["rate_2024"]/trend["rate_2023"]-1)
            trend["exclusion_change_pct"] = 100*(trend["exclusion_rate_2024"]/trend["exclusion_rate_2023"]-1)
            threshold_trends.append(trend)
    exclusion, concentration, top_rows = [], [], []
    for year, g in good.groupby("year_filing_for"):
        h, c = float(g.total_hours_worked.sum()), int(g.recordable_cases.sum())
        ordered = g.sort_values(["total_hours_worked", "id"], ascending=[False, True])
        top_rows.extend(filing_record(r) for _, r in ordered.head(10).iterrows())
        for n in (0, 1, 2, 5, 10, 50, 100):
            removed = ordered.head(n)
            rh, rc = float(removed.total_hours_worked.sum()), int(removed.recordable_cases.sum())
            concentration.append({"year": int(year), "top_n": n, "excluded_hours": rh, "excluded_cases": rc,
                                  "hours_share": rh/h, "cases_share": rc/c, "rate_after_exclusion": SCALE*(c-rc)/(h-rh)})
        masks = {"baseline": pd.Series(False, index=g.index),
                 "exclude_two_2023_filings": (g.year_filing_for == 2023) & g.establishment_id.isin(selected_ids),
                 "exclude_selected_ids_all_years": g.establishment_id.isin(selected_ids)}
        masks.update({f"exclude_top_{n}_hours_each_year": g.index.isin(ordered.head(n).index)
                      for n in (1, 2, 5, 10, 50, 100)})
        masks.update({f"exclude_employees_above_{bound}": g.annual_average_employees > bound
                      for bound in (10000, 25000, 50000, 100000, 250000, 1000000)})
        for name, mask in masks.items():
            removed = g[mask]
            rh, rc = float(removed.total_hours_worked.sum()), int(removed.recordable_cases.sum())
            exclusion.append({"year": int(year), "scenario": name, "n_excluded": len(removed),
                              "excluded_hours": rh, "excluded_cases": rc, "excluded_hours_share": rh/h,
                              "remaining_hours": h-rh, "remaining_cases": c-rc,
                              "rate": SCALE*(c-rc)/(h-rh)})
    result = {"raw_provenance": provenance, "suspect_filings": suspects,
              "linked_filings": [filing_record(r) for _, r in linked.iterrows()],
              "threshold_survival": threshold_rows, "exclusion_sensitivity": exclusion,
              "threshold_trend_sensitivity": threshold_trends,
              "exposure_concentration": concentration, "largest_screened_filings": top_rows}
    influence, influence_tables = build_influence_audit(good)
    result["influence_audit"] = influence
    output_tables = {"filing_exclusion_sensitivity": pd.DataFrame(exclusion),
                    "screened_exposure_concentration": pd.DataFrame(concentration),
                    "threshold_trend_sensitivity": pd.DataFrame(threshold_trends),
                    "largest_screened_filings": pd.DataFrame(top_rows)}
    output_tables.update(influence_tables)
    return result, output_tables


def build(tables_dir: Path, data_dir: Path | None = None) -> tuple[dict, dict[str, pd.DataFrame]]:
    peers_path, quality_path = tables_dir/"peer_percentiles_by_year.csv", tables_dir/"quality_by_year.csv"
    peers = pd.read_csv(peers_path, dtype={"naics3": str, "size_band": str})
    quality = pd.read_csv(quality_path)
    findings, tables = table_analysis(peers, quality)
    findings["schema_version"] = 1
    findings["provenance"] = [{"path": str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),
                                "sha256": sha256(p)} for p in (peers_path, quality_path)]
    findings["definitions"] = {
        "rate": "TRIR = 200000 * reported recordable cases / reported hours; not a national estimate.",
        "population": "Default plausibility-screen-passing filings, including all peer cells regardless of publishability.",
        "matched": "NAICS-3 by employee-size cells present in both years; membership can change within a cell.",
        "weights": "Each matched cell's hours divided by total matched hours in its own year.",
        "within_effect": "Sum of average of the two exposure weights times change in cell rate.",
        "composition_effect": "Sum of average of the two cell rates times change in exposure weight.",
        "support_residual": "Full-population change minus common-support change; exact additive reconciliation.",
        "fixed_weights": "Both earlier-year and later-year weights reported separately; the symmetric within effect averages them.",
        "suspect_selection": "Retrospective exploratory audit of 2023: rank its default-screen-passing filings by reported hours, without using case counts in that ranking. The choice to investigate 2023 is not preregistered.",
        "exclusions": "Sensitivity scenarios, not corrected rates, validated error classifications, or estimates of true hours.",
        "joint_scaling": "Multiplying hours and employees by the same positive constant leaves hours per employee unchanged.",
    }
    findings["limitations"] = [
        "Descriptive administrative filings, not a probability sample or a causal study.",
        "Within-cell differences include changing establishments, reporting practices and unmeasured mix; they are not same-site safety changes.",
        "Same establishment_id is a linkage hint, not verified physical identity. No institution names are needed for this audit.",
        "Exclusion sensitivity cannot identify which fields are wrong or recover their true values.",
        "Threshold stability does not establish absolute-scale validity: every tested bound acts on the same ratio.",
        "Symmetric decomposition is an accounting convention; earlier- and later-weight counterfactuals can differ materially.",
        "No uncertainty intervals or national extrapolation are claimed; observed snapshots and their deterministic sensitivity are reported.",
    ]
    if data_dir is not None:
        raw, raw_tables = raw_analysis(data_dir, findings["annual_rates"])
        findings.update(raw)
        tables.update(raw_tables)
        series = findings["exclusion_sensitivity"]
        lookup = {(r["year"], r["scenario"]): r for r in series}
        baseline23, baseline24 = lookup[2023, "baseline"], lookup[2024, "baseline"]
        removed23 = lookup[2023, "exclude_two_2023_filings"]
        findings["headline"] = {
            "reported_2023_rate": baseline23["rate"], "reported_2024_rate": baseline24["rate"],
            "reported_2023_2024_change_pct": 100*(baseline24["rate"]/baseline23["rate"]-1),
            "two_filing_exclusion_2023_rate": removed23["rate"],
            "two_filing_exclusion_2023_2024_change_pct": 100*(baseline24["rate"]/removed23["rate"]-1),
            "two_filings_hours": removed23["excluded_hours"],
            "two_filings_hours_share": removed23["excluded_hours_share"],
            "two_filings_cases": removed23["excluded_cases"],
            "two_filings_count_share": 2 / next(r["n_filings"] for r in findings["annual_rates"] if r["year"] == 2023),
            "threshold_grid_cells": len(findings["threshold_survival"]),
            "threshold_grid_cells_both_pass": sum(r["selected_pass"] == 2 for r in findings["threshold_survival"]),
            "symmetric_top_two_2023_rate": lookup[2023, "exclude_top_2_hours_each_year"]["rate"],
            "symmetric_top_two_2024_rate": lookup[2024, "exclude_top_2_hours_each_year"]["rate"],
            "symmetric_top_two_2023_2024_change_pct": 100*(lookup[2024, "exclude_top_2_hours_each_year"]["rate"] / lookup[2023, "exclude_top_2_hours_each_year"]["rate"]-1),
            "reported_2023_2024_cases_change_pct": 100*(baseline24["remaining_cases"]/baseline23["remaining_cases"]-1),
            "reported_2023_2024_hours_change_pct": 100*(baseline24["remaining_hours"]/baseline23["remaining_hours"]-1),
            "two_filing_exclusion_2023_2024_cases_change_pct": 100*(baseline24["remaining_cases"]/removed23["remaining_cases"]-1),
            "two_filing_exclusion_2023_2024_hours_change_pct": 100*(baseline24["remaining_hours"]/removed23["remaining_hours"]-1),
            "two_filings_share_of_net_hours_decline": removed23["excluded_hours"]/(baseline23["remaining_hours"]-baseline24["remaining_hours"]),
        }
    return findings, tables


def write_outputs(out: Path, findings: dict, tables: dict[str, pd.DataFrame]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    # Disallow NaN in the public JSON so consumers need no nonstandard parser.
    (out/"findings.json").write_text(json.dumps(findings, indent=2, allow_nan=False)+"\n")
    for name, table in tables.items():
        table.to_csv(out/f"{name}.csv", index=False, float_format="%.15g")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tables", type=Path, default=ROOT/"outputs"/"tables")
    parser.add_argument("--raw", type=Path, help="Verify pinned 2016-2024 raw files and include filing audit")
    parser.add_argument("--out", type=Path, default=ROOT/"outputs"/"research"/"benchmark_fragility")
    parser.add_argument("--public-json", type=Path, help="Also write the identical findings JSON for a static interface")
    args = parser.parse_args()
    if args.public_json and args.raw is None:
        parser.error("--public-json requires --raw; do not publish an incomplete filing audit")
    findings, tables = build(args.tables, args.raw)
    write_outputs(args.out, findings, tables)
    if args.public_json:
        args.public_json.parent.mkdir(parents=True, exist_ok=True)
        args.public_json.write_text((args.out/"findings.json").read_text())
    print(json.dumps(findings.get("headline", {"annual_pairs": len(findings["decomposition"])}), indent=2))


if __name__ == "__main__":
    main()
