"""``python3 -m ehs_osha.health``: validate lineage, run expectations, write docs."""

from __future__ import annotations

import sys

from . import expectations, lineage


def main() -> int:
    """Return nonzero if lineage validation or any error expectation fails."""
    rc = lineage.main()
    rc |= expectations.main([])
    return rc


if __name__ == "__main__":
    sys.exit(main())
