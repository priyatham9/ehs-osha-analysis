#!/usr/bin/env python3
"""Download the public OSHA ITA Form 300A files this project analyses.

No API key is needed. OSHA's CDN rejects a default urllib User-Agent with
HTTP 403, so a browser-style UA is sent; that is the only special handling.

If a file cannot be retrieved intact the script exits non-zero with an error.
It never writes a placeholder and never substitutes synthetic data.

Usage:
    python scripts/download_data.py
    python scripts/download_data.py --dest data/raw --include-partial
    python scripts/download_data.py --list
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ehs_osha.catalog import DOCUMENTATION_URLS, all_files  # noqa: E402
from ehs_osha.download import DownloadError, download_all  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """Construct the command-line parser."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--dest",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "raw",
        help="Directory to download into (default: data/raw).",
    )
    p.add_argument(
        "--include-partial",
        action="store_true",
        help="Also fetch the partial-year 2025 file (excluded from analysis by default).",
    )
    p.add_argument("--force", action="store_true", help="Re-download files that already exist.")
    p.add_argument("--timeout", type=int, default=600, help="Socket timeout in seconds.")
    p.add_argument("--list", action="store_true", help="Print the catalog and exit.")
    return p


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    args = build_parser().parse_args(argv)

    if args.list:
        print("OSHA ITA Form 300A files (source: https://www.osha.gov/itadata)\n")
        for f in all_files(include_partial=True):
            size = f"{f.expected_bytes:,} B" if f.expected_bytes else "size unknown"
            print(f"  {f.key:24s} CY{f.calendar_year}  {size}")
            print(f"      {f.url}")
            if f.note:
                print(f"      note: {f.note}")
        print("\nSupporting documentation:")
        for k, v in DOCUMENTATION_URLS.items():
            print(f"  {k:28s} {v}")
        return 0

    try:
        records = download_all(
            args.dest,
            include_partial=args.include_partial,
            force=args.force,
            timeout=args.timeout,
        )
    except DownloadError as exc:
        print(f"\nDOWNLOAD FAILED: {exc}", file=sys.stderr)
        print(
            "\nNothing was substituted. Fix the network or URL and re-run; the "
            "analysis pipeline will refuse to start without these files.",
            file=sys.stderr,
        )
        return 2

    total = sum(r.bytes for r in records)
    print(f"\n{len(records)} files, {total:,} bytes total, in {args.dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
