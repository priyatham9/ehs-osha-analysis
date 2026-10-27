#!/usr/bin/env python3
"""Write outputs/tables/detectability_by_size_band.csv from committed tables.

Reads outputs/tables/size_band_effects.csv only (no raw data needed). Per band:
mean hours per filing is implied by the table itself, because
aggregate_trir = 200000 * sum(cases) / sum(hours) and mean_recordables is the
mean case count, so mean hours = mean_recordables * 200000 / aggregate_trir.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ehs_osha.detectability import build_table  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    import pandas as pd

    src = pd.read_csv(ROOT / "outputs" / "tables" / "size_band_effects.csv", dtype={"size_band": str})
    out = build_table(src)
    path = ROOT / "outputs" / "tables" / "detectability_by_size_band.csv"
    out.to_csv(path, index=False)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
