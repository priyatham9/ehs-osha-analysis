#!/usr/bin/env python3
"""Write outputs/tables/panel_linkage_audit.csv and docs/PANEL_AUDIT.md.

Reads committed tables in outputs/tables only (no raw data needed).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ehs_osha.panel_audit import main  # noqa: E402

if __name__ == "__main__":
    main()
