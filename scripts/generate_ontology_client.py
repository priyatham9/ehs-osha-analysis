#!/usr/bin/env python3
"""Generate src/ehs_osha/ontology/client.py from spec.json.

Usage:
    python scripts/generate_ontology_client.py           # write the file
    python scripts/generate_ontology_client.py --check   # exit 1 if it is stale
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ehs_osha.ontology.codegen import generate  # noqa: E402

TARGET = ROOT / "src" / "ehs_osha" / "ontology" / "client.py"


def main(argv: list) -> int:
    text = generate()
    if "--check" in argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != text:
            print(f"{TARGET} does not match spec.json; run scripts/generate_ontology_client.py")
            return 1
        print("ontology client is up to date")
        return 0
    TARGET.write_text(text, encoding="utf-8")
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
