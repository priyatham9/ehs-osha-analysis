"""Export an :class:`ObjectStore` to SQLite and JSON so it runs anywhere.

SQLite layout: one table per object type (columns typed from the spec, primary
key enforced), one table per many-to-many link, ``action_log`` (one row per
applied action, edits as JSON) and ``ontology_spec`` (the spec itself, so the
file is self-describing). Many-to-one links are the foreign-key columns.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict

from .runtime import ObjectStore

_SQL_TYPES = {"string": "TEXT", "integer": "INTEGER", "double": "REAL", "boolean": "INTEGER", "timestamp": "TEXT"}


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def to_json_dict(store: ObjectStore) -> Dict[str, Any]:
    """Return the store as a JSON-serialisable dict (NaN never appears)."""
    return {
        "ontology": store.spec.raw["ontology"],
        "objects": {t: store.objects(t).to_frame().astype(object).where(lambda d: d.notna(), None).to_dict(orient="records") for t in store.spec.object_types},
        "links": {
            name: [list(p) for p in store.link_pairs(name)]
            for name, lk in store.spec.link_types.items()
            if lk["cardinality"] == "many_to_many"
        },
        "integrity": store.integrity_report(),
        "action_log": [e.to_json() for e in store.action_log],
    }


def export_json(store: ObjectStore, path: Path) -> Path:
    """Write :func:`to_json_dict` to ``path``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_json_dict(store), indent=1, allow_nan=False) + "\n", encoding="utf-8")
    return path


def export_sqlite(store: ObjectStore, path: Path) -> Path:
    """Write the store to a fresh SQLite database at ``path``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(str(path))
    try:
        for name, ot in store.spec.object_types.items():
            props = store.spec.properties(name)
            cols = ", ".join(
                f"{_q(p)} {_SQL_TYPES[d['type']]}{' PRIMARY KEY' if p == ot['primary_key'] else ''}"
                f"{' NOT NULL' if not d.get('nullable', True) else ''}"
                for p, d in props.items()
            )
            con.execute(f"CREATE TABLE {_q(name)} ({cols})")
            names = list(props)
            rows = store._rows[name].values()
            con.executemany(
                f"INSERT INTO {_q(name)} VALUES ({', '.join('?' * len(names))})",
                ([r[n] for n in names] for r in rows),
            )
        for name, lk in store.spec.link_types.items():
            if lk["cardinality"] != "many_to_many":
                continue
            con.execute(f"CREATE TABLE {_q('link_' + name)} (source_key TEXT NOT NULL, target_key TEXT NOT NULL)")
            con.executemany(f"INSERT INTO {_q('link_' + name)} VALUES (?, ?)", store.link_pairs(name))
        con.execute(
            "CREATE TABLE action_log (action_id TEXT PRIMARY KEY, action_type TEXT NOT NULL, "
            "actor TEXT NOT NULL, timestamp TEXT NOT NULL, parameters TEXT NOT NULL, edits TEXT NOT NULL)"
        )
        con.executemany(
            "INSERT INTO action_log VALUES (?, ?, ?, ?, ?, ?)",
            (
                (e.action_id, e.action_type, e.actor, e.timestamp, json.dumps(e.parameters), json.dumps(e.edits))
                for e in store.action_log
            ),
        )
        con.execute("CREATE TABLE ontology_spec (spec_json TEXT NOT NULL)")
        con.execute("INSERT INTO ontology_spec VALUES (?)", (json.dumps(store.spec.raw),))
        con.commit()
    finally:
        con.close()
    return path
