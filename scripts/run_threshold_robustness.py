#!/usr/bin/env python3
"""Write the threshold-robustness tables and docs/THRESHOLD_ROBUSTNESS.md.

Reads committed tables in outputs/tables only (no raw data needed).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ehs_osha import threshold_robustness  # noqa: E402


def main() -> None:
    """Write the tables and docs page."""
    threshold_robustness.main()


if __name__ == "__main__":
    main()
