"""Test support: put ``src`` on the path and locate repo directories.

The project has no build step and no installed package, so tests import from
``src`` directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DATA_RAW = ROOT / "data" / "raw"
FIXTURE = ROOT / "synthetic" / "fixture"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def real_data_available() -> bool:
    """Return True if the full real OSHA catalog is present locally.

    Returns:
        True when every catalog file exists under ``data/raw``.
    """
    from ehs_osha.catalog import all_files

    return all((DATA_RAW / f.local_name).exists() for f in all_files())


def fixture_available() -> bool:
    """Return True if the synthetic fixture has been generated."""
    return FIXTURE.exists() and any(FIXTURE.glob("SYNTHETIC_ITA_300A_*.csv"))
