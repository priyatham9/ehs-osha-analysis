"""Deterministic review diagnostics; these functions never clean observations.

The prospective operational rule is to review any filing whose single removal
reverses an adjacent-year aggregate comparison. Applying this rule to historical
data is retrospective, not a preregistration. No sampling uncertainty, causality,
or erroneous-field classification is inferred from influence.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SCALE = 200000.0


def deletion_accounting(cases: float, hours: float, removed_cases: float,
                        removed_hours: float) -> dict:
    """Separate a deletion's numerator and denominator effects symmetrically.

The two effects average the two possible orders of changing cases and hours.
They therefore add exactly to the joint change without assigning the interaction
arbitrarily to one input. The single-input counterfactuals are arithmetic
diagnostics, not repaired filings.
"""
    values = np.array([cases, hours, removed_cases, removed_hours], dtype=float)
    if (not np.isfinite(values).all() or cases < 0 or hours <= 0
            or not 0 <= removed_cases <= cases or not 0 <= removed_hours < hours):
        raise ValueError("Deletion must leave positive hours and nonnegative cases")
    baseline = SCALE*cases/hours
    cases_only = SCALE*(cases-removed_cases)/hours
    hours_only = SCALE*cases/(hours-removed_hours)
    both = SCALE*(cases-removed_cases)/(hours-removed_hours)
    numerator = ((cases_only-baseline)+(both-hours_only))/2
    denominator = ((hours_only-baseline)+(both-cases_only))/2
    return {"baseline_rate": baseline, "removed_cases": removed_cases,
            "removed_hours": removed_hours, "cases_only_rate": cases_only,
            "hours_only_rate": hours_only, "joint_rate": both,
            "joint_change": both-baseline, "numerator_effect": numerator,
            "denominator_effect": denominator}


def scaled_pool_rate(cases: float, hours: float, row_hours: float, factor: float) -> float:
    """Pool rate when one row's hours and employees are scaled by factor >= 1."""
    if (not np.isfinite([cases, hours, row_hours, factor]).all() or cases < 0
            or hours <= 0 or not 0 < row_hours <= hours or factor < 1):
        raise ValueError("Require nonnegative cases, positive exposure and factor >= 1")
    denominator = hours+(factor-1)*row_hours
    if not np.isfinite(denominator):
        raise ValueError("Scaled exposure exceeds finite arithmetic")
    return SCALE*cases/denominator


def build_influence_audit(screened_good: pd.DataFrame) -> tuple[dict, dict[str, pd.DataFrame]]:
    """Evaluate every screened filing, retaining summaries and review candidates."""
    by_year, summary, ranked = {}, [], []
    for year, g in screened_good.groupby("year_filing_for"):
        g = g.copy()
        h, c = float(g.total_hours_worked.sum()), float(g.recordable_cases.sum())
        baseline = SCALE*c/h
        g["leave_one_out_rate"] = SCALE*(c-g.recordable_cases)/(h-g.total_hours_worked)
        g["leave_one_out_change"] = g.leave_one_out_rate-baseline
        g["hours_share"] = g.total_hours_worked/h
        g["cases_share"] = g.recordable_cases/c
        g["absolute_influence"] = g.leave_one_out_change.abs()
        ordered = g.sort_values(["absolute_influence", "id"], ascending=[False, True])
        top_hours = g.sort_values(["total_hours_worked", "id"], ascending=[False, True])
        hhi = float((g.hours_share**2).sum())
        summary.append({"year": int(year), "n_filings": len(g), "rate": baseline,
                        "hours": h, "cases": int(c),
                        "top_one_hours_share": float(top_hours.iloc[0].hours_share),
                        "top_two_hours_share": float(top_hours.head(2).hours_share.sum()),
                        "hours_hhi": hhi, "equivalent_equal_exposure_filings": 1/hhi,
                        "max_absolute_leave_one_out_change": float(ordered.iloc[0].absolute_influence),
                        "max_absolute_relative_leave_one_out_change": float(ordered.iloc[0].absolute_influence/baseline),
                        "largest_positive_change": float(g.leave_one_out_change.max()),
                        "largest_negative_change": float(g.leave_one_out_change.min()),
                        "most_influential_filing_id": int(ordered.iloc[0].id)})
        by_year[int(year)] = (g, baseline)
        for rank, (_, r) in enumerate(ordered.head(10).iterrows(), start=1):
            ranked.append({"year": int(year), "rank": rank, "filing_id": int(r.id),
                           "establishment_id": int(r.establishment_id), "hours": float(r.total_hours_worked),
                           "cases": int(r.recordable_cases), "hours_share": float(r.hours_share),
                           "cases_share": float(r.cases_share), "leave_one_out_rate": float(r.leave_one_out_rate),
                           "leave_one_out_change": float(r.leave_one_out_change)})
    candidates, decisions = [], []
    years = sorted(by_year)
    for y0, y1 in zip(years[:-1], years[1:]):
        a, r0 = by_year[y0]
        b, r1 = by_year[y1]
        original = r1-r0
        count = 0
        for removal_year, g in ((y0, a), (y1, b)):
            after = r1-g.leave_one_out_rate if removal_year == y0 else g.leave_one_out_rate-r0
            reversing = g[after*original < 0]
            count += len(reversing)
            for _, row in reversing.iterrows():
                new0 = float(row.leave_one_out_rate) if removal_year == y0 else r0
                new1 = float(row.leave_one_out_rate) if removal_year == y1 else r1
                candidates.append({"year_before": y0, "year_after": y1, "removal_year": removal_year,
                                   "filing_id": int(row.id), "establishment_id": int(row.establishment_id),
                                   "original_rate_before": r0, "original_rate_after": r1,
                                   "review_rate_before": new0, "review_rate_after": new1,
                                   "original_change_pct": 100*(r1/r0-1),
                                   "review_change_pct": 100*(new1/new0-1),
                                   "hours": float(row.total_hours_worked), "cases": int(row.recordable_cases)})
        decisions.append({"year_before": y0, "year_after": y1, "n_filings_tested": len(a)+len(b),
                          "n_single_filing_reversals": count,
                          "minimum_deletions_proven": 1 if count else None,
                          "minimum_deletions_lower_bound": 1 if count else 2,
                          "interpretation": "One deletion suffices; zero preserves the original sign." if count else
                          "No single deletion reverses the sign; no larger subset search is claimed."})
    source, _ = by_year[2023]
    h, c = float(source.total_hours_worked.sum()), float(source.recordable_cases.sum())
    top = source.sort_values(["total_hours_worked", "id"], ascending=[False, True]).head(2)
    accounting = []
    for label, group in (("largest_2023_hours_filing", top.head(1)),
                         ("second_largest_2023_hours_filing", top.tail(1)), ("two_largest_2023_hours_filings", top)):
        result = deletion_accounting(c, h, float(group.recordable_cases.sum()), float(group.total_hours_worked.sum()))
        result.update({"scenario": label, "filing_ids": [int(v) for v in group.id],
                       "review_2023_2024_change_pct": 100*(by_year[2024][1]/result["joint_rate"]-1)})
        accounting.append(result)
    other = [r for r in summary if r["year"] != 2023]
    context = {"comparison_years": [r["year"] for r in other],
               "other_years_top_two_hours_share_min": min(r["top_two_hours_share"] for r in other),
               "other_years_top_two_hours_share_max": max(r["top_two_hours_share"] for r in other),
               "year_2023_top_two_hours_share": next(r["top_two_hours_share"] for r in summary if r["year"] == 2023)}
    result = {
        "rule": "For each adjacent-year comparison, review every screened filing whose single deletion reverses the sign. Apply identically to both years. Keep observations pending review; influence is not an error classification.",
        "rule_status": "Deterministic prospective operational rule, applied retrospectively here; not historically preregistered.",
        "leave_one_out_identity": "R_without_i - R = (R*H_i - 200000*C_i)/(H-H_i)",
        "relative_identity": "(R_without_i-R)/R = (hours_share_i-cases_share_i)/(1-hours_share_i), when total cases > 0.",
        "scale_invariance": {
            "conditions": "A passing row has E>=1, H>0, finite values and valid case fields. Scale E and H by the same a>=1, keeping cases fixed and products finite.",
            "invariant": "(a*H)/(a*E) = H/E. All hours-per-employee thresholds and unchanged case flags retain their verdict.",
            "row_rate": "TRIR_scaled = TRIR_original/a",
            "pooled_rate": "R(a) = 200000*C_total / (H_total+(a-1)*H_i)",
            "consequence": "In real-number arithmetic, R(a) tends to zero as a grows. Ratio-screen acceptance alone supplies no lower bound on the pooled rate.",
            "qualification": "This theorem describes a blind spot, not the actual mechanism behind any reported field."},
        "concentration_definition": "Hours HHI is sum of squared filing exposure shares. Its reciprocal is the number of equally weighted filings with the same concentration; it is not an effective statistical sample size or uncertainty estimate.",
        "accounting_definition": "Numerator and denominator effects average both orders of removal and add to the joint rate change. Single-input changes are mathematical scenarios, not repaired filings.",
        "annual": summary, "ranked_filings": ranked, "review_candidates": candidates,
        "decision_fragility": decisions, "deletion_accounting": accounting, "concentration_context": context,
    }
    return result, {"annual_influence_audit": pd.DataFrame(summary),
                    "single_filing_review_candidates": pd.DataFrame(candidates),
                    "filing_influence_ranking": pd.DataFrame(ranked)}
