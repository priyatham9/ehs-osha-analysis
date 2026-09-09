#!/usr/bin/env python3
"""Run the full OSHA ITA analysis and write every table and figure.

Usage:
    python scripts/run_analysis.py
    python scripts/run_analysis.py --data-dir data/raw --out-dir outputs
    python scripts/run_analysis.py --years 2023 2024

This script runs only against the real OSHA ITA files named in the catalog. It
will not run against the synthetic fixture: the loader requires the catalog
filenames, so pointing --data-dir at synthetic/fixture fails rather than
producing fixture-derived output that could be mistaken for a finding. The
fixture is exercised through the library directly, in
tests/test_pipeline_on_fixture.py, which writes to a temporary directory.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ehs_osha.download import DownloadError, require_local_files  # noqa: E402
from ehs_osha.pipeline import PipelineConfig, run_pipeline  # noqa: E402
from ehs_osha.quality import PlausibilityConfig  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    """Construct the command-line parser."""
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--data-dir", type=Path, default=ROOT / "data" / "raw")
    p.add_argument("--out-dir", type=Path, default=ROOT / "outputs")
    p.add_argument(
        "--years", type=int, nargs="*", default=None, help="Restrict to these reporting years."
    )
    p.add_argument("--min-hours-per-employee", type=float, default=120.0)
    p.add_argument("--max-hours-per-employee", type=float, default=4500.0)
    p.add_argument("--min-group-n", type=int, default=30)
    p.add_argument("--naics-level", choices=("naics2", "naics3", "naics4"), default="naics3")
    p.add_argument("--model-year", type=int, default=2024)
    p.add_argument(
        "--model-naics3",
        nargs="*",
        default=None,
        help=(
            "Explicit NAICS 3-digit codes for the count models. Omit to select "
            "the largest industries by establishment count (see --model-top-k), "
            "which avoids any suggestion that industries were picked to suit a "
            "particular model."
        ),
    )
    p.add_argument(
        "--model-top-k",
        type=int,
        default=30,
        help="Industries to fit when --model-naics3 is not given (default 30).",
    )
    p.add_argument(
        "--model-min-group-n",
        type=int,
        default=500,
        help="Minimum establishments for an industry to be fitted (default 500).",
    )
    p.add_argument(
        "--model-max-n",
        type=int,
        default=60_000,
        help=(
            "Cap on establishments per model fit, for runtime. Larger groups "
            "are subsampled with the configured seed (default 60,000)."
        ),
    )
    p.add_argument("--include-partial", action="store_true")
    p.add_argument(
        "--skip-file-check",
        action="store_true",
        help="Do not require the full catalog to be present (used for fixtures).",
    )
    p.add_argument(
        "--skip-metrics",
        action="store_true",
        help=(
            "Skip the TRIR/DART/LTIR/SEVERITY metrics stage (ehs_osha.metrics). "
            "This is the slowest stage, roughly 3 minutes on the full data, "
            "because it reloads and rescreens the raw files."
        ),
    )
    p.add_argument(
        "--skip-count-models-covariates",
        action="store_true",
        help=(
            "Skip the covariate-adjusted count-model stage "
            "(ehs_osha.count_models_covariates). Skipping this leaves the "
            "older intercept-only fig04_count_model_fit.svg in place instead "
            "of the size-band + NAICS-4 fixed-effects version."
        ),
    )
    p.add_argument(
        "--skip-reconcile",
        action="store_true",
        help="Skip the reconciliation-against-published-figures stage (ehs_osha.reconcile).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    args = build_parser().parse_args(argv)

    if not args.skip_file_check:
        try:
            require_local_files(args.data_dir, include_partial=args.include_partial)
        except DownloadError as exc:
            print(f"\n{exc}", file=sys.stderr)
            return 2

    cfg = PipelineConfig(
        data_dir=args.data_dir,
        out_dir=args.out_dir,
        plausibility=PlausibilityConfig(
            min_hours_per_employee=args.min_hours_per_employee,
            max_hours_per_employee=args.max_hours_per_employee,
        ),
        naics_level=args.naics_level,
        min_group_n=args.min_group_n,
        model_naics3=list(args.model_naics3) if args.model_naics3 else None,
        model_top_k=args.model_top_k,
        model_min_group_n=args.model_min_group_n,
        model_year=args.model_year,
        model_max_n=args.model_max_n,
        include_partial=args.include_partial,
        years=args.years,
        skip_metrics=args.skip_metrics,
        skip_count_models_covariates=args.skip_count_models_covariates,
        skip_reconcile=args.skip_reconcile,
    )
    summary = run_pipeline(cfg)

    pooled = summary["quality"]["pooled"]
    print("\n--- headline numbers (recomputed, not transcribed) ---")
    print(f"filings analysed              : {pooled['n_filings']:,}")
    print(
        f"flagged implausible           : {pooled['n_implausible']:,} "
        f"({pooled['implausible_share'] * 100:.2f}%)"
    )
    print(
        f"share of all hours they hold  : "
        f"{pooled['hours_share_implausible'] * 100:.2f}%"
    )
    print(f"aggregate TRIR, unscreened    : {pooled['aggregate_trir_unscreened']:.4f}")
    print(f"aggregate TRIR, screened      : {pooled['aggregate_trir_screened']:.4f}")
    print(
        f"ratio screened : unscreened   : "
        f"{pooled['ratio_screened_to_unscreened']:.2f}x"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
