"""Build the ontology and export it: ``python3 -m ehs_osha.ontology --out DIR``.

Establishment-level objects come from the SYNTHETIC fixture unless
``--data-dir`` points at the real ITA downloads. Output goes to ``--out`` only;
nothing is written under ``outputs/``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from . import functions
from .export import export_json, export_sqlite
from .materialise import SOURCE_FIXTURE, SOURCE_RAW, TABLES_DIR, build_store


def main(argv: Optional[List[str]] = None) -> int:
    """Materialise, print a short census, and write ontology.sqlite/json."""
    ap = argparse.ArgumentParser(description="Build and export the OSHA ITA ontology.")
    ap.add_argument("--out", required=True, help="directory for ontology.sqlite and ontology.json")
    ap.add_argument("--data-dir", help="real ITA raw files (default: SYNTHETIC fixture)")
    ap.add_argument("--tables-dir", default=str(TABLES_DIR))
    args = ap.parse_args(argv)

    frame, source = None, SOURCE_FIXTURE
    if args.data_dir:
        from ..load import load_ita_300a

        frame, _ = load_ita_300a(Path(args.data_dir))
        source = SOURCE_RAW
    store = build_store(frame=frame, tables_dir=Path(args.tables_dir), source=source)

    out = Path(args.out)
    export_sqlite(store, out / "ontology.sqlite")
    export_json(store, out / "ontology.json")
    census = {t: store.objects(t).count() for t in store.spec.object_types}
    print(json.dumps({"source": source, "objects": census, "integrity": store.integrity_report()}, indent=1))
    if source == SOURCE_FIXTURE:
        print("Establishment and Filing objects are SYNTHETIC; do not cite numbers computed from them.")
        rates = functions.aggregate_rates(store.objects("Filing"))
        print(f"fixture aggregate TRIR (plumbing check only): {rates['trir_screened']:.3f}")
    print(f"wrote {out / 'ontology.sqlite'} and {out / 'ontology.json'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
