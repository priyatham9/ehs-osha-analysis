"""Validate ``lineage.json`` against the repository and render ``docs/LINEAGE.md``.

Validation rules:

* every artifact path of a committed (``file``) artifact exists (artifacts
  marked ``generated_here`` are written by the same command and are checked
  for freshness by the tests instead);
* every stage names a producing module (resolved under ``src``) or script, and
  the named function is defined at the top level of that file (checked with
  :mod:`ast`, so nothing is imported or executed);
* every stage input and output refers to a declared artifact;
* every artifact is produced by at most one stage, and the stage graph has no
  cycle;
* every committed ``outputs/tables/*.csv`` is declared by some artifact, so a
  new table cannot be added without being placed in the lineage.

Output is deterministic: no timestamps, no absolute paths.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[3]
SPEC = Path(__file__).with_name("lineage.json")
DOC = ROOT / "docs" / "LINEAGE.md"


def load_spec(path: Path = SPEC) -> Dict[str, object]:
    """Read the lineage spec."""
    return json.loads(path.read_text(encoding="utf-8"))


def _stage_file(stage: Dict[str, object], root: Path) -> Path:
    if "script" in stage:
        return root / str(stage["script"])
    dotted = str(stage["module"]).split(".")
    base = root / "src" / Path(*dotted)
    return base.with_suffix(".py") if base.with_suffix(".py").exists() else base / "__init__.py"


def _top_level_names(path: Path) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}


def validate(spec: Dict[str, object], root: Path = ROOT) -> List[str]:
    """Return a list of problems; empty means the lineage is valid."""
    problems: List[str] = []
    artifacts: Dict[str, Dict[str, object]] = spec["artifacts"]  # type: ignore[assignment]
    stages: List[Dict[str, object]] = spec["stages"]  # type: ignore[assignment]

    declared_paths = set()
    for aid, art in artifacts.items():
        for rel in art["paths"]:  # type: ignore[union-attr]
            declared_paths.add(rel)
            if art["kind"] == "file" and not art.get("generated_here") and not (root / rel).exists():
                problems.append(f"artifact {aid}: path does not exist: {rel}")

    producer: Dict[str, str] = {}
    seen_ids = set()
    for st in stages:
        sid = str(st["id"])
        if sid in seen_ids:
            problems.append(f"duplicate stage id: {sid}")
        seen_ids.add(sid)
        f = _stage_file(st, root)
        if not f.exists():
            problems.append(f"stage {sid}: producing file not found: {f.relative_to(root)}")
        elif str(st["function"]) not in _top_level_names(f):
            problems.append(f"stage {sid}: function {st['function']} not defined in {f.relative_to(root)}")
        for ref in list(st["inputs"]) + list(st["outputs"]):  # type: ignore[arg-type]
            if ref not in artifacts:
                problems.append(f"stage {sid}: undeclared artifact {ref}")
        for out in st["outputs"]:  # type: ignore[union-attr]
            if out in producer:
                problems.append(f"artifact {out} produced by both {producer[out]} and {sid}")
            producer[out] = sid

    # Cycle check over the stage graph (Kahn).
    deps = {
        str(st["id"]): {producer[a] for a in st["inputs"] if a in producer}  # type: ignore[union-attr]
        for st in stages
    }
    remaining = dict(deps)
    while remaining:
        ready = [s for s, d in remaining.items() if not (d & set(remaining))]
        if not ready:
            problems.append("cycle among stages: " + ", ".join(sorted(remaining)))
            break
        for s in ready:
            del remaining[s]

    tables = root / "outputs" / "tables"
    if tables.exists():
        for csv in sorted(tables.glob("*.csv")):
            rel = f"outputs/tables/{csv.name}"
            if rel not in declared_paths:
                problems.append(f"table not declared in lineage: {rel}")
    return problems


def _topo(stages: List[Dict[str, object]], producer: Dict[str, str]) -> List[Dict[str, object]]:
    """Stable topological order, preserving spec order among ready stages."""
    by_id = {str(s["id"]): s for s in stages}
    deps = {i: {producer[a] for a in s["inputs"] if a in producer} for i, s in by_id.items()}  # type: ignore[union-attr]
    order: List[Dict[str, object]] = []
    done: set = set()
    while len(done) < len(by_id):
        for i in by_id:
            if i not in done and deps[i] <= done:
                order.append(by_id[i])
                done.add(i)
                break
        else:  # cycle; validate() reports it
            break
    return order


def render(spec: Dict[str, object]) -> str:
    """Render the lineage document as Markdown with a Mermaid graph."""
    artifacts: Dict[str, Dict[str, object]] = spec["artifacts"]  # type: ignore[assignment]
    stages: List[Dict[str, object]] = spec["stages"]  # type: ignore[assignment]
    producer = {a: str(s["id"]) for s in stages for a in s["outputs"]}  # type: ignore[union-attr]
    ordered = _topo(stages, producer)

    out: List[str] = []
    out.append("# Pipeline lineage")
    out.append("")
    out.append(
        "Generated by `python3 -m ehs_osha.health` from `src/ehs_osha/health/lineage.json`. "
        "Do not edit by hand: `tests/test_health.py` fails if this file differs from the "
        "generator output. The same command validates that every declared path exists, "
        "every producing function is defined, and every committed table is placed in the graph."
    )
    out.append("")
    out.append(
        f"{len(stages)} stages, {len(artifacts)} artifacts. Rounded boxes are stages, "
        "rectangles are committed files, cylinders are in-memory frames, "
        "and the hexagon is the external source."
    )
    out.append("")
    out.append("```mermaid")
    out.append("flowchart LR")
    shape = {"file": ("[", "]"), "memory": ("[(", ")]"), "external": ("{{", "}}")}
    for aid, art in artifacts.items():
        o, c = shape[str(art["kind"])]
        out.append(f'  A_{aid}{o}"{art["label"]}"{c}')
    for st in ordered:
        out.append(f'  S_{st["id"]}("{st["title"]}")')
    for st in ordered:
        for a in st["inputs"]:  # type: ignore[union-attr]
            out.append(f'  A_{a} --> S_{st["id"]}')
        for a in st["outputs"]:  # type: ignore[union-attr]
            out.append(f'  S_{st["id"]} --> A_{a}')
    out.append("```")
    out.append("")
    out.append("## Stages")
    out.append("")
    out.append("| Stage | Producer | Reads | Writes |")
    out.append("|---|---|---|---|")
    for st in ordered:
        where = st.get("script") or str(st["module"]).replace(".", "/")
        prod = f"`{where}.{st['function']}`" if "module" in st else f"`{where}:{st['function']}`"
        reads = ", ".join(str(artifacts[a]["label"]) for a in st["inputs"]) or "none"  # type: ignore[union-attr]
        writes = ", ".join(str(artifacts[a]["label"]) for a in st["outputs"])  # type: ignore[union-attr]
        out.append(f"| {st['title']} | {prod} | {reads} | {writes} |")
    out.append("")
    out.append("## Artifacts")
    out.append("")
    out.append("| Artifact | Kind | Produced by | Paths |")
    out.append("|---|---|---|---|")
    for aid, art in artifacts.items():
        paths = "<br>".join(f"`{p}`" for p in art["paths"]) or "in memory"  # type: ignore[union-attr]
        out.append(f"| {art['label']} | {art['kind']} | {producer.get(aid, 'none (source)')} | {paths} |")
    out.append("")
    return "\n".join(out)


def build() -> str:
    """Render the document from the committed spec."""
    return render(load_spec())


def main(out: Path = DOC) -> int:
    """Validate then write ``docs/LINEAGE.md``; return nonzero on problems."""
    problems = validate(load_spec())
    for p in problems:
        print(f"LINEAGE FAIL: {p}")
    if problems:
        return 1
    out.write_text(build(), encoding="utf-8")
    print(f"lineage ok, wrote {out}")
    return 0
