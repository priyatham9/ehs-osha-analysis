"""Secondary OSHA rates alongside TRIR: DART, LTIR and severity rate.

All four rates share one normalisation, cases (or days) per 200,000 hours
worked, which is 100 full-time workers at 2,000 hours each. The Form 300A
fields used are:

``total_dafw_cases``   column (H), cases with days away from work
``total_djtr_cases``   column (I), cases with job transfer or restriction
``total_dafw_days``    column (K), days away from work
``total_djtr_days``    column (L), days of job transfer or restriction

Definitions used here::

    TRIR     = 200000 * (G + H + I + J) / hours
    DART     = 200000 * (H + I) / hours
    LTIR     = 200000 * H / hours            (lost-time = days-away cases)
    SEVERITY = 200000 * (K + L) / hours      (days lost per 200,000 hours)

Every aggregate is computed as a ratio of sums (total cases over total hours),
not as a mean of establishment rates, on the plausibility-screened panel from
:func:`ehs_osha.quality.apply_screen`. Unscreened values are carried alongside
so the effect of the screen on each rate is visible.

Run as a module to regenerate ``outputs/tables/metrics_by_year.csv`` and
``metrics_pooled.csv`` from the raw ITA files and add a ``metrics`` block to
``outputs/summary.json``::

    python3 -m ehs_osha.metrics
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from . import quality

PER_HOURS = 200000.0

#: Rate name -> numerator columns summed over filings.
RATE_NUMERATORS: Dict[str, List[str]] = {
    "trir": ["total_deaths", "total_dafw_cases", "total_djtr_cases", "total_other_cases"],
    "dart": ["total_dafw_cases", "total_djtr_cases"],
    "ltir": ["total_dafw_cases"],
    "severity": ["total_dafw_days", "total_djtr_days"],
}


def _rate(num: float, hours: float) -> float:
    return float(PER_HOURS * num / hours) if hours > 0 else float("nan")


def compute_rates(frame: pd.DataFrame, label: str = "pooled_all_years") -> Dict[str, object]:
    """Compute pooled TRIR, DART, LTIR and severity for one stratum.

    Args:
        frame: Frame returned by :func:`ehs_osha.quality.apply_screen`, i.e. it
            carries an ``implausible`` boolean column.
        label: Stratum label written into the row.

    Returns:
        Dict with ``label``, filing and hour totals, and for each rate the
        screened and unscreened value and their ratio. Numerator columns that
        are missing from the frame are treated as zero; a filing with a missing
        numerator contributes zero to that numerator (same convention as
        ``sum(skipna=True)``).
    """
    good = ~frame["implausible"].to_numpy(dtype=bool)
    hours = frame["total_hours_worked"].to_numpy(dtype="float64", na_value=np.nan)
    hours_all = float(np.nansum(hours))
    hours_scr = float(np.nansum(hours[good]))
    row: Dict[str, object] = {
        "label": label,
        "n_filings": int(len(frame)),
        "n_screened_in": int(good.sum()),
        "hours_unscreened": hours_all,
        "hours_screened": hours_scr,
    }
    for name, cols in RATE_NUMERATORS.items():
        present = [c for c in cols if c in frame.columns]
        if present:
            num = frame[present].sum(axis=1, min_count=1).to_numpy(dtype="float64", na_value=np.nan)
        else:
            num = np.zeros(len(frame))
        num_all = float(np.nansum(num))
        num_scr = float(np.nansum(num[good]))
        row[f"{name}_numerator_screened"] = num_scr
        row[f"{name}_unscreened"] = _rate(num_all, hours_all)
        row[f"{name}_screened"] = _rate(num_scr, hours_scr)
        u, s = row[f"{name}_unscreened"], row[f"{name}_screened"]
        row[f"{name}_ratio_screened_to_unscreened"] = float(s / u) if u and np.isfinite(u) else float("nan")
    return row


def rates_by_year(frame: pd.DataFrame) -> pd.DataFrame:
    """Run :func:`compute_rates` within each ``year_filing_for``."""
    rows = [
        compute_rates(grp, label=str(int(year)))
        for year, grp in frame.groupby("year_filing_for", dropna=True, observed=True)
    ]
    return pd.DataFrame(rows)


def rates_pooled(frame: pd.DataFrame) -> pd.DataFrame:
    """Single-row frame with the all-years pooled rates."""
    return pd.DataFrame([compute_rates(frame, label="pooled_all_years")])


def write_tables(frame: pd.DataFrame, out_dir: Path) -> Dict[str, object]:
    """Write ``metrics_by_year.csv`` and ``metrics_pooled.csv``.

    Returns:
        A JSON-ready dict with both tables as records, for ``summary.json``.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    by_year = rates_by_year(frame)
    pooled = rates_pooled(frame)
    by_year.to_csv(out_dir / "metrics_by_year.csv", index=False)
    pooled.to_csv(out_dir / "metrics_pooled.csv", index=False)
    return {
        "definitions": {k: "+".join(v) for k, v in RATE_NUMERATORS.items()},
        "per_hours": PER_HOURS,
        "pooled": pooled.to_dict(orient="records")[0],
        "by_year": by_year.to_dict(orient="records"),
    }


def main(argv: Optional[List[str]] = None) -> int:
    """Regenerate the metrics tables from the raw data on disk."""
    import argparse

    from .load import load_ita_300a
    from .pipeline import PipelineConfig

    root = Path(__file__).resolve().parents[2]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default=str(root / "data" / "raw"))
    ap.add_argument("--out-dir", default=str(root / "outputs"))
    args = ap.parse_args(argv)

    cfg = PipelineConfig(data_dir=Path(args.data_dir), out_dir=Path(args.out_dir))
    df, _ = load_ita_300a(cfg.data_dir, include_partial=cfg.include_partial, years=cfg.years)
    screened = quality.apply_screen(df, cfg.plausibility)
    block = write_tables(screened, Path(args.out_dir) / "tables")

    summary_path = Path(args.out_dir) / "summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())
        summary["metrics"] = block
        summary_path.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(pd.DataFrame([block["pooled"]]).T.to_string())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
