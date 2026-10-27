#!/usr/bin/env python3
"""Score the 2026-10-27 pre-registration once 2025 outputs are in the tables.

Reads the committed predictions (``docs/preregistration_2025_predictions.csv``,
never recomputed here, so later table updates cannot move the goalposts) and the
2025 values from ``outputs/tables`` after the pipeline has been rerun with the
2025 ITA release. Decision rule, fixed in advance (see
``docs/PREREGISTRATION_2025.md``): a prediction held if the observed 2025 value
lies inside its 95% interval (Q5: strictly above 1.0); otherwise it did not.
Outcomes are reported for every quantity and are not filtered.

Exit status: 0 when scored (whatever the verdicts), 2 when there is no 2025 row
yet, which is the expected state until the 2025 data are added.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import preregister_2025 as pre  # noqa: E402


def load_predictions(path: Path = pre.OUT_CSV) -> "list[dict]":
    """Read the committed predictions."""
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def observed_2025(tables: Path = pre.TABLES) -> "dict[str, float]":
    """Return the observed 2025 value per prediction id, or {} if absent."""
    specs = pre.yearly_quantities(tables, max_year=pre.TARGET_YEAR)
    obs = {}
    for spec in specs:
        if pre.TARGET_YEAR in spec["years"]:
            obs[spec["id"]] = spec["values"][spec["years"].index(pre.TARGET_YEAR)]
    return obs


def score(predictions: "list[dict]", observed: "dict[str, float]") -> "list[dict]":
    """Apply the decision rule to each prediction.

    Args:
        predictions: Rows from the committed predictions CSV.
        observed: Observed 2025 values keyed by prediction id.

    Returns:
        One result dict per prediction with ``verdict`` in
        ``held`` / ``not held`` / ``not evaluable``.
    """
    results = []
    for r in predictions:
        lo, hi = float(r["lo95"]), float(r["hi95"])
        val = observed.get(r["id"])
        if val is None:
            verdict = "not evaluable"
        elif r["transform"] == "threshold":
            verdict = "held" if val > lo else "not held"
        else:
            verdict = "held" if lo <= val <= hi else "not held"
        results.append({"id": r["id"], "quantity": r["quantity"], "pred": float(r["pred"]),
                        "lo95": lo, "hi95": hi, "observed": val, "verdict": verdict})
    return results


def summarize(results: "list[dict]") -> str:
    """Return a plain-text report including the coverage summary."""
    lines = ["id     verdict        observed        interval"]
    for x in results:
        obs = "n/a" if x["observed"] is None else "%.6g" % x["observed"]
        lines.append("%-6s %-14s %-15s %.6g to %.6g   %s"
                     % (x["id"], x["verdict"], obs, x["lo95"], x["hi95"], x["quantity"]))
    scored = [x for x in results if x["verdict"] != "not evaluable"]
    held = sum(1 for x in scored if x["verdict"] == "held")
    lines.append("")
    lines.append("held %d of %d scored predictions (nominal interval coverage is 95%%; "
                 "see the pre-registration for what miss counts are consistent with it)"
                 % (held, len(scored)))
    return "\n".join(lines)


def main(argv: "list[str] | None" = None) -> int:
    """Score the pre-registration against the current tables."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tables", type=Path, default=pre.TABLES)
    ap.add_argument("--predictions", type=Path, default=pre.OUT_CSV)
    args = ap.parse_args(argv)
    obs = observed_2025(args.tables)
    if not obs:
        print("No 2025 rows in %s yet; nothing to score." % args.tables)
        return 2
    print(summarize(score(load_predictions(args.predictions), obs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
