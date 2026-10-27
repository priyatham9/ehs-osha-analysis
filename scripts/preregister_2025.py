#!/usr/bin/env python3
"""Pre-registered predictions for the reporting-year-2025 ITA release.

Registered on 2026-10-27, before any 2025 data exists in this repository. The
git history of this file and of ``docs/PREREGISTRATION_2025.md`` timestamps it.

Reads committed tables in ``outputs/tables`` only (no raw data, no network),
keeps only filing years <= 2024, and writes ``docs/preregistration_2025_predictions.csv``.
The computation is deterministic: no random numbers, no clock, no environment.

Model (identical for every quantity)
------------------------------------
1. Transform the yearly series: identity for aggregate screened TRIR, logit for
   shares, log for unscreened TRIR (a positive ratio-type quantity whose year
   composition effect is multiplicative).
2. Point prediction: mean of the last three observed years (2022-2024), on the
   transformed scale, mapped back.
3. Prediction interval: apply the same rule backwards. For every year t that has
   three earlier years (2019-2024, six one-step errors), the error is
   ``x_t - mean(x_{t-3}, x_{t-2}, x_{t-1})``. The interval half-width is
   ``T_975[6] * sqrt(mean(error**2))`` with T_975[6] = 2.4469 (Student t, 0.975
   quantile, 6 degrees of freedom; hard-coded because the project does not
   depend on SciPy). This is a 95% interval nominally; with six errors it is an
   approximation and is documented as such.
4. Q5 (screened/unscreened ratio) is a structural claim, not a trend model: the
   ratio stays strictly above 1.0, as it did in all nine observed years.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "outputs" / "tables"
OUT_CSV = ROOT / "docs" / "preregistration_2025_predictions.csv"

TARGET_YEAR = 2025
LAST_OBSERVED_YEAR = 2024
WINDOW = 3
T_975_DF6 = 2.4469  # Student t, 0.975 quantile, 6 d.f. (six one-step errors)
REGISTERED_ON = "2026-10-27"

FIELDS = [
    "id", "quantity", "group", "source_table", "transform", "n_history", "history",
    "window_mean", "rmse_transformed", "pred", "lo95", "hi95", "history_sha256",
]


def _logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def _expit(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


TRANSFORMS = {
    "identity": (lambda x: x, lambda z: z),
    "logit": (_logit, _expit),
    "log": (math.log, math.exp),
}


def forecast(values: "list[float]", transform: str) -> dict:
    """Return point prediction and 95% interval for the next value.

    Args:
        values: Yearly observations in time order (at least WINDOW + 1 values).
        transform: One of ``identity``, ``logit`` or ``log``.

    Returns:
        Dict with ``window_mean`` and ``rmse_transformed`` (transformed scale)
        and ``pred``, ``lo95``, ``hi95`` (original scale).
    """
    fwd, inv = TRANSFORMS[transform]
    x = [fwd(v) for v in values]
    errors = [x[t] - sum(x[t - WINDOW:t]) / WINDOW for t in range(WINDOW, len(x))]
    rmse = math.sqrt(sum(e * e for e in errors) / len(errors))
    center = sum(x[-WINDOW:]) / WINDOW
    half = T_975_DF6 * rmse
    return {
        "window_mean": center,
        "rmse_transformed": rmse,
        "pred": inv(center),
        "lo95": inv(center - half),
        "hi95": inv(center + half),
    }


def _g(v: float) -> str:
    """Format to 12 significant digits so last-bit platform differences cannot matter."""
    return "%.12g" % v


def _series_hash(values: "list[float]") -> str:
    return hashlib.sha256(";".join(_g(float(v)) for v in values).encode()).hexdigest()


def yearly_quantities(tables: Path, max_year: int = LAST_OBSERVED_YEAR) -> "list[dict]":
    """Extract the registered yearly series from committed tables.

    Args:
        tables: Directory holding ``quality_by_year.csv`` and
            ``peer_percentiles_by_year.csv``.
        max_year: Last filing year to use.

    Returns:
        One dict per registered quantity with ``id``, ``quantity``, ``group``,
        ``source_table``, ``transform`` and ``years`` / ``values`` lists.
    """
    q = pd.read_csv(tables / "quality_by_year.csv")
    q["year"] = q["label"].astype(float).astype(int)
    q = q[q["year"] <= max_year].sort_values("year")
    specs = [
        ("Q1", "flagged-filing share (n_implausible / n_filings)", "all",
         "implausible_share", "logit"),
        ("Q2", "aggregate TRIR, screened", "all", "aggregate_trir_screened", "identity"),
        ("Q3", "aggregate TRIR, unscreened", "all", "aggregate_trir_unscreened", "log"),
        ("Q4", "share of reported hours held by flagged filings", "all",
         "hours_share_implausible", "logit"),
    ]
    out = []
    for qid, name, group, col, tr in specs:
        out.append({"id": qid, "quantity": name, "group": group,
                    "source_table": "quality_by_year.csv:" + col, "transform": tr,
                    "years": q["year"].tolist(), "values": q[col].astype(float).tolist()})

    out.append({"id": "Q5",
                "quantity": "ratio of screened to unscreened aggregate TRIR (structural claim: above 1)",
                "group": "all", "source_table": "quality_by_year.csv:ratio_screened_to_unscreened",
                "transform": "threshold", "years": q["year"].tolist(),
                "values": q["ratio_screened_to_unscreened"].astype(float).tolist()})

    p = pd.read_csv(tables / "peer_percentiles_by_year.csv")
    p["year"] = p["year_filing_for"].astype(float).astype(int)
    p = p[p["year"] <= max_year].copy()
    p["zeros"] = p["zero_share"] * p["n_with_metric"]
    g = p.groupby(["size_band", "year"])[["zeros", "n_with_metric"]].sum().reset_index()
    g["share"] = g["zeros"] / g["n_with_metric"]
    for i, band in enumerate(sorted(g["size_band"].unique()), start=1):
        s = g[g["size_band"] == band].sort_values("year")
        out.append({"id": "Q6.%d" % i,
                    "quantity": "zero-injury share of establishments, size band " + band,
                    "group": band,
                    "source_table": "peer_percentiles_by_year.csv:zero_share (weighted by n_with_metric)",
                    "transform": "logit", "years": s["year"].tolist(),
                    "values": s["share"].astype(float).tolist()})
    return out


def build_predictions(tables: Path = TABLES) -> "list[dict]":
    """Return one prediction row per registered quantity."""
    rows = []
    for spec in yearly_quantities(tables):
        if spec["years"][-1] != LAST_OBSERVED_YEAR or len(spec["years"]) != 9:
            raise SystemExit("expected nine consecutive years 2016-2024 for " + spec["id"])
        if spec["transform"] == "threshold":
            # Structural claim, not a trend model: the ratio stays above 1.0, as in
            # every one of the nine observed years (minimum shown as the reference).
            f = {"window_mean": float("nan"), "rmse_transformed": float("nan"),
                 "pred": min(spec["values"]), "lo95": 1.0, "hi95": float("inf")}
        else:
            f = forecast(spec["values"], spec["transform"])
        rows.append({
            "id": spec["id"], "quantity": spec["quantity"], "group": spec["group"],
            "source_table": spec["source_table"], "transform": spec["transform"],
            "n_history": len(spec["values"]),
            "history": ";".join(_g(float(v)) for v in spec["values"]),
            "window_mean": _g(f["window_mean"]),
            "rmse_transformed": _g(f["rmse_transformed"]),
            "pred": _g(f["pred"]), "lo95": _g(f["lo95"]), "hi95": _g(f["hi95"]),
            "history_sha256": _series_hash(spec["values"]),
        })
    return rows


def render_csv(rows: "list[dict]") -> str:
    """Serialize prediction rows exactly as committed (LF line endings)."""
    import io

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def _fmt(v: float, transform: str) -> str:
    return "%.4f" % v


def render_markdown_table(rows: "list[dict]") -> str:
    """Return the human-readable prediction table embedded in the docs page."""
    lines = ["| ID | Quantity | Prediction for 2025 | 95% interval (held if inside) |",
             "|---|---|---|---|"]
    for r in rows:
        if r["transform"] == "threshold":
            lines.append("| %s | %s | above 1.0 (observed minimum %s) | strictly greater than 1.0 |"
                         % (r["id"], r["quantity"], _fmt(float(r["pred"]), r["transform"])))
            continue
        lines.append("| %s | %s | %s | %s to %s |" % (
            r["id"], r["quantity"], _fmt(float(r["pred"]), r["transform"]),
            _fmt(float(r["lo95"]), r["transform"]), _fmt(float(r["hi95"]), r["transform"])))
    return "\n".join(lines) + "\n"


def main(argv: "list[str] | None" = None) -> None:
    """Write the predictions CSV (or check it with ``--check``)."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="exit nonzero if the committed CSV differs from a rerun")
    args = ap.parse_args(argv)
    text = render_csv(build_predictions())
    if args.check:
        if OUT_CSV.read_text(encoding="utf-8") != text:
            raise SystemExit("docs/preregistration_2025_predictions.csv differs from rerun")
        print("predictions reproduce")
        return
    OUT_CSV.write_text(text, encoding="utf-8")
    print(render_markdown_table(build_predictions()))


if __name__ == "__main__":
    main()
